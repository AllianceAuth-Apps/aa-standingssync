"""Models for standingssync."""

import datetime as dt
from typing import Optional, Set

from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.utils.timezone import now
from esi.errors import TokenExpiredError, TokenInvalidError
from esi.models import Token
from eveuniverse.models import EveEntity

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter
from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from .app_settings import (
    STANDINGSSYNC_ADD_WAR_TARGETS,
    STANDINGSSYNC_CHAR_MIN_STANDING,
    STANDINGSSYNC_REPLACE_CONTACTS,
    STANDINGSSYNC_STORE_ESI_CONTACTS_ENABLED,
    STANDINGSSYNC_SYNC_TIMEOUT,
)
from .core import esi_api
from .core.esi_contacts import EsiContact, EsiContactsContainer
from .helpers import store_json
from .managers import EveContactManager, EveWarManager, SyncManagerManager

logger = get_extension_logger(__name__)


class _SyncBaseModel(models.Model):
    """Common fields and logic for sync models."""

    last_sync_at = models.DateTimeField(
        null=True,
        default=None,
        help_text="When the last successful sync was completed.",
    )

    class Meta:
        abstract = True

    @property
    def is_sync_fresh(self) -> bool:
        """Return True, when sync is not stale, else False."""
        if not self.last_sync_at:
            return False

        deadline = now() - dt.timedelta(minutes=STANDINGSSYNC_SYNC_TIMEOUT)
        return self.last_sync_at > deadline

    def record_successful_sync(self):
        """Record date & time of a successful sync."""
        self.last_sync_at = now()
        self.save()


class SyncManager(_SyncBaseModel):
    """An object for managing syncing of contacts for an alliance."""

    alliance = models.OneToOneField(
        EveAllianceInfo,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="+",
        help_text="Alliance to sync contacts for",
    )
    character_ownership = models.OneToOneField(
        CharacterOwnership,
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        help_text="alliance contacts are fetched from this character",
    )
    version_hash = models.CharField(
        max_length=32,
        default="",
        help_text="hash over all contacts to identify when it has changed",
    )

    objects = SyncManagerManager()

    def __str__(self):
        return str(self.alliance)

    @property
    def character(self) -> EveCharacter:
        """Return character linked to this manager or raises exception of none exists."""
        if not self.character_ownership:
            raise ValueError("No character ownership")
        return self.character_ownership.character

    def contacts_for_sync(self, synced_character: "SyncedCharacter") -> models.QuerySet:
        """Relevant contacts for sync, which excludes the sync character."""
        return self.contacts.exclude(eve_entity_id=synced_character.character_id)

    def effective_standing_with_character(self, character: EveCharacter) -> float:
        """Effective standing of the alliance with a character."""
        try:
            return self.contacts.get(eve_entity_id=character.character_id).standing
        except EveContact.DoesNotExist:
            pass

        try:
            return self.contacts.get(eve_entity_id=character.corporation_id).standing
        except EveContact.DoesNotExist:
            pass

        if character.alliance_id:
            try:
                return self.contacts.get(eve_entity_id=character.alliance_id).standing
            except EveContact.DoesNotExist:
                pass

        return 0.0

    def synced_characters_for_user(
        self, user: User
    ) -> models.QuerySet["SyncedCharacter"]:
        """Synced characters of the given user."""
        return self.synced_characters.filter(character_ownership__user=user)

    def run_sync(self, force_update: bool = False) -> bool:
        """Run sync for this manager.

        Args:
            - force_update: when true will always update contacts in database

        Returns True when contacts where updated, else False.
        """
        if self.character_ownership is None:
            raise RuntimeError(f"{self}: Can not sync. No character configured.")

        if not self.character_ownership.user.has_perm("standingssync.add_syncmanager"):
            raise RuntimeError(
                f"{self}: Can not sync. Character does not have sufficient permission."
            )

        token = self.fetch_token()
        if not token:
            raise RuntimeError(f"{self}: Can not sync. No valid token found.")

        esi_contacts = esi_api.fetch_alliance_contacts(self.alliance.alliance_id, token)
        contacts = EsiContactsContainer.from_esi_contacts(esi_contacts)
        war_target_ids = self._add_war_targets(contacts)
        new_version_hash = contacts.version_hash()

        if force_update or new_version_hash != self.version_hash:
            self._save_new_contacts(contacts, war_target_ids, new_version_hash)
            EveEntity.objects.bulk_resolve_ids(contacts.contact_ids())
            was_updated = True
        else:
            logger.info("%s: Alliance contacts are unchanged.", self)
            was_updated = False

        self.record_successful_sync()
        return was_updated

    def fetch_token(self) -> Optional[Token]:
        """Fetch valid token with required scopes."""
        if not self.character_ownership:
            return None

        token = (
            Token.objects.filter(
                user=self.character_ownership.user,
                character_id=self.character.character_id,
            )
            .require_scopes(self.get_esi_scopes())
            .require_valid()
            .first()
        )
        return token

    def _add_war_targets(self, contacts: EsiContactsContainer) -> Set[int]:
        """Add war targets to contacts (if enabled).

        Returns contact IDs of war targets.
        """
        if not STANDINGSSYNC_ADD_WAR_TARGETS:
            return set()

        war_targets = EveWar.objects.alliance_war_targets(self.alliance)
        war_target_ids = set()
        for war_target in war_targets:
            try:
                contacts.add_contact(EsiContact.from_eve_entity(war_target, -10.0))
            except ValueError:  # eve_entity has no category
                logger.warning("Skipping unresolved war target: %s", war_target)
            else:
                war_target_ids.add(war_target.id)

        return war_target_ids

    # TODO: Replace delete & create with update & delete
    @transaction.atomic()
    def _save_new_contacts(
        self,
        current_contacts: EsiContactsContainer,
        war_target_ids: Set[int],
        new_version_hash: str,
    ):
        self.contacts.all().delete()
        contacts = [
            EveContact(
                manager=self,
                eve_entity=EveEntity.objects.get_or_create(id=contact.contact_id)[0],
                standing=contact.standing,
                is_war_target=contact.contact_id in war_target_ids,
            )
            for contact in current_contacts.contacts()
        ]
        EveContact.objects.bulk_create(contacts, batch_size=500)
        self.version_hash = new_version_hash
        self.save()
        logger.info("%s: Stored alliance update with %d contacts", self, len(contacts))

    @classmethod
    def get_esi_scopes(cls) -> list:
        """Return ESI scopes needed for this model."""
        return ["esi-alliances.read_contacts.v1"]


class SyncedCharacter(_SyncBaseModel):
    """A character that has his personal contacts synced with an alliance"""

    character_ownership = models.OneToOneField(
        CharacterOwnership,
        on_delete=models.CASCADE,
        primary_key=True,
        help_text="Character to sync",
    )
    has_war_targets_label = models.BooleanField(
        default=None,
        null=True,
        help_text="Whether this character has the war target label.",
    )
    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="synced_characters"
    )

    def __str__(self):
        try:
            character_name = self.character.character_name
        except ObjectDoesNotExist:
            character_name = "?"
        return f"{character_name} - {self.manager}"

    @property
    def character(self) -> EveCharacter:
        """Return EveCharacter used to sync."""
        return self.character_ownership.character

    @property
    def character_id(self) -> Optional[int]:
        """Return character ID of the EveCharacter used to sync."""
        return self.character.character_id if self.character else None

    def run_sync(self) -> Optional[bool]:
        """Sync in-game contacts for given character with alliance contacts
        and/or war targets.

        Will delete this sync character if necessary,
        e.g. if token is no longer valid or character is no longer blue

        Returns:
        - False when the sync character was deleted
        - None when no update was needed
        - True when update was done successfully
        """
        if not self._has_sync_permissions():
            return False

        if not self._has_standing_with_alliance():
            return False

        token = self.fetch_token()
        if not token:
            logger.error("%s: Can not sync. No valid token found.", self)
            return False

        if not self.manager.contacts_for_sync(self).exists():
            logger.info("%s: No contacts to sync", self)
            return None

        current_contacts = self._fetch_current_contacts(token)
        self._update_wt_label_info(current_contacts)

        new_contacts = self._identify_new_contacts(current_contacts)

        self._update_contacts_on_esi(token, current_contacts, new_contacts)

        if STANDINGSSYNC_STORE_ESI_CONTACTS_ENABLED:
            store_json(new_contacts.to_dict(), "new_contacts")

        self.record_successful_sync()
        return True

    def _identify_new_contacts(self, current_contacts):
        if STANDINGSSYNC_REPLACE_CONTACTS:
            new_contacts = EsiContactsContainer.from_esi_contacts(
                labels=current_contacts.labels()
            )
            new_contacts.add_eve_contacts(
                self.manager.contacts_for_sync(self).filter(is_war_target=False)
            )
        else:
            new_contacts = current_contacts.clone()

        if STANDINGSSYNC_ADD_WAR_TARGETS:
            # remove old war targets
            new_contacts.remove_war_targets()
            # add current war targets
            wt_label_id = current_contacts.war_target_label_id()
            new_contacts.add_eve_contacts(
                self.manager.contacts_for_sync(self).filter(is_war_target=True),
                label_ids=[wt_label_id] if wt_label_id else None,
            )

        return new_contacts

    def _update_contacts_on_esi(self, token, current_contacts, new_contacts):
        added, removed, changed = current_contacts.contacts_difference(new_contacts)
        if removed:
            esi_api.delete_character_contacts(token, removed)
            logger.info("%s: Deleted %d added contacts", self, len(removed))

        if added:
            esi_api.add_character_contacts(token, added)
            logger.info("%s: Added %d missing contacts", self, len(added))

        if changed:
            esi_api.update_character_contacts(token, changed)
            logger.info("%s: Updated %d changed contacts", self, len(changed))

        if not added and not removed and not changed:
            logger.info("%s: Nothing updated. Contacts were already up-to-date.", self)
        else:
            logger.info("%s: Contacts update completed.", self)

    def _update_wt_label_info(self, current_contacts: EsiContactsContainer):
        """Update info about WT label if it has changed."""
        has_wt_label = current_contacts.war_target_label_id() is not None
        if has_wt_label != self.has_war_targets_label:
            self.has_war_targets_label = has_wt_label
            self.save()

    def _has_sync_permissions(self) -> bool:
        if not self.character_ownership.user.has_perm(
            "standingssync.add_syncedcharacter"
        ):
            logger.info(
                "%s: sync deactivated due to insufficient user permissions", self
            )
            self._deactivate_sync("you no longer have permission for this service")
            return False

        return True

    def fetch_token(self) -> Optional[Token]:
        """Fetch valid token with required scopes.

        Will deactivate this character if any severe issues are encountered.
        """
        try:
            token = self._valid_token()

        except TokenInvalidError:
            self._deactivate_sync("your token is no longer valid")
            logger.info("%s: sync deactivated due to invalid token", self)
            return None

        except TokenExpiredError:
            self._deactivate_sync("your token has expired")
            logger.info("%s: sync deactivated due to expired token", self)
            return None

        if token is None:
            self._deactivate_sync("you do not have a token anymore")
            logger.info("%s: can not find suitable token for synced char", self)
            return None

        return token

    def _valid_token(self) -> Optional[Token]:
        return (
            Token.objects.filter(
                user=self.character_ownership.user,
                character_id=self.character_ownership.character.character_id,
            )
            .require_scopes(self.get_esi_scopes())
            .require_valid()
            .first()
        )

    def _deactivate_sync(self, message: str):
        """Deactivate character and send a message to the user about the issue."""
        message = (
            "Standings Sync has been deactivated for your "
            f"character {self}, because {message}.\n"
            "Feel free to activate sync for your character again, "
            "once the issue has been resolved."
        )
        notify(
            self.character_ownership.user,
            f"Standings Sync deactivated for {self}",
            message,
        )
        self.delete()

    def _has_standing_with_alliance(self) -> bool:
        """Clarify if this character has standing with the alliance
        and therefore is allowed to sync contacts.

        Deactivate character if it has no standing.
        """
        character_eff_standing = self.manager.effective_standing_with_character(
            self.character_ownership.character
        )
        if character_eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
            logger.info(
                "%s: sync deactivated because character is no longer considered blue. "
                f"It's standing is: {character_eff_standing}, "
                "while STANDINGSSYNC_CHAR_MIN_STANDING is: "
                f"{STANDINGSSYNC_CHAR_MIN_STANDING} ",
                self,
            )
            self._deactivate_sync(
                "your character is no longer blue with the alliance. "
                f"The standing value is: {character_eff_standing:.1f} "
            )
            return False

        return True

    def _fetch_current_contacts(self, token: Token) -> EsiContactsContainer:
        contacts = esi_api.fetch_character_contacts(token)
        labels = esi_api.fetch_character_contact_labels(token)
        current_contacts = EsiContactsContainer.from_esi_contacts(contacts, labels)

        if STANDINGSSYNC_STORE_ESI_CONTACTS_ENABLED:
            store_json(current_contacts.to_dict(), "current_contacts")

        logger.debug("%s: new version hash: %s", self, current_contacts.version_hash())
        return current_contacts

    def delete_all_contacts(self):
        """Delete all contacts of this character."""
        token = self._valid_token()
        if not token:
            logger.warning(
                "%s: Can not delete contacts, because no valid token found.", self
            )
            return

        contacts_clone = self._fetch_current_contacts(token)
        contacts = contacts_clone.contacts()
        esi_api.delete_character_contacts(token, contacts)
        logger.info("%s: Deleted all %d contacts", self, len(contacts))

    @staticmethod
    def get_esi_scopes() -> list:
        """Return required ESI scopes."""
        return ["esi-characters.read_contacts.v1", "esi-characters.write_contacts.v1"]


class EveContact(models.Model):
    """An Eve Online contact"""

    manager = models.ForeignKey(
        SyncManager, on_delete=models.CASCADE, related_name="contacts"
    )
    eve_entity = models.ForeignKey(
        EveEntity, on_delete=models.CASCADE, related_name="+"
    )
    standing = models.FloatField()
    is_war_target = models.BooleanField()

    objects = EveContactManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "eve_entity"], name="fk_eve_contact"
            )
        ]

    def __str__(self):
        return f"{self.eve_entity}"

    @property
    def contact_id(self) -> int:
        """Return contact ID."""
        return self.eve_entity_id


class EveWar(models.Model):
    """An EveOnline war"""

    class State(models.TextChoices):
        """A war state."""

        PENDING = "pending"  # declared, but not started yet
        ONGOING = "ongoing"  # active and without finish date
        CONCLUDING = "concluding"  # active and about to finish normally
        RETRACTED = "retracted"  # activate and about to finish after retraction
        FINISHED = "finished"  # finished war

        @classmethod
        def active_states(cls) -> Set["EveWar.State"]:
            """Return all states representing an active war."""
            return {cls.ONGOING, cls.CONCLUDING, cls.RETRACTED}

    id = models.PositiveIntegerField(primary_key=True)
    aggressor = models.ForeignKey(EveEntity, on_delete=models.CASCADE, related_name="+")
    allies = models.ManyToManyField(EveEntity, related_name="+")
    declared = models.DateTimeField()
    defender = models.ForeignKey(EveEntity, on_delete=models.CASCADE, related_name="+")
    finished = models.DateTimeField(null=True, default=None, db_index=True)
    is_mutual = models.BooleanField()
    is_open_for_allies = models.BooleanField()
    retracted = models.DateTimeField(null=True, default=None)
    started = models.DateTimeField(null=True, default=None, db_index=True)

    objects = EveWarManager()

    def __str__(self) -> str:
        return f"{self.aggressor} vs. {self.defender}"
