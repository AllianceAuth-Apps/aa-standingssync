"""Managers for standingssync."""

# pylint: disable = redefined-builtin, missing-class-docstring

import datetime as dt
from collections import defaultdict
from typing import Any, Dict, Set, Tuple

from django.contrib.auth.models import User
from django.db import models, transaction
from django.db.models import Case, Value, When
from django.utils.timezone import now
from eveuniverse.models import EveEntity

from allianceauth.eveonline.models import EveAllianceInfo
from allianceauth.services.hooks import get_extension_logger

from .core import esi_api

logger = get_extension_logger(__name__)


class EveContactQuerySet(models.QuerySet):
    def grouped_by_standing(self) -> Dict[int, Any]:
        """Group alliance contacts by standing and convert into sorted dict."""
        contacts_by_standing = defaultdict(set)
        for contact in self.all():
            contacts_by_standing[contact.standing].add(contact)
        return dict(sorted(contacts_by_standing.items()))


class EveContactManagerBase(models.Manager):
    pass


EveContactManager = EveContactManagerBase.from_queryset(EveContactQuerySet)


class EveWarQuerySet(models.QuerySet):
    def annotate_state(self) -> models.QuerySet:
        """Add state field to queryset."""
        from .models import EveWar

        return self.annotate(
            state=Case(
                When(started__gt=now(), then=Value(EveWar.State.PENDING.value)),
                When(
                    started__lte=now(),
                    finished__isnull=True,
                    then=Value(EveWar.State.ONGOING.value),
                ),
                When(
                    started__lte=now(),
                    finished__gt=now(),
                    retracted__isnull=False,
                    then=Value(EveWar.State.RETRACTED.value),
                ),
                When(
                    started__lte=now(),
                    finished__gt=now(),
                    retracted__isnull=True,
                    then=Value(EveWar.State.CONCLUDING.value),
                ),
                default=Value(EveWar.State.FINISHED.value),
            )
        )

    def annotate_is_active(self) -> models.QuerySet:
        """Add is_active field to queryset. Requires prior annotation of state."""
        return self.annotate(
            is_active=Case(
                When(state__in=self.model.State.active_states(), then=Value(True)),
                default=Value(False),
            )
        )

    def current_wars(self) -> models.QuerySet:
        """Add filter for current wars.

        This includes wars that are about to start,
        active wars and wars that ended recently.
        """
        cutoff = now() - dt.timedelta(hours=24)
        qs = self.filter(declared__lt=now())
        return (
            qs.filter(finished__gt=cutoff) | qs.filter(finished__isnull=True)
        ).distinct()

    def active_wars(self) -> models.QuerySet:
        """Add filter for active wars."""
        qs = self.filter(started__lt=now())
        return (
            qs.filter(finished__gt=now()) | qs.filter(finished__isnull=True)
        ).distinct()

    def finished_wars(self) -> models.QuerySet:
        """Add filter for finished wars."""
        return self.filter(finished__lte=now())

    def alliance_wars(self, alliance: EveAllianceInfo) -> models.QuerySet:
        """Include wars where a given alliance is participating only."""
        return (
            self.filter(aggressor_id=alliance.alliance_id)
            | self.filter(defender_id=alliance.alliance_id)
            | self.filter(allies__id=alliance.alliance_id)
        ).distinct()


class EveWarManagerBase(models.Manager):
    def alliance_war_targets(
        self, alliance: EveAllianceInfo
    ) -> models.QuerySet[EveEntity]:
        """Identify current war targets of on alliance."""
        war_target_ids = set()
        for war in self.alliance_wars(alliance).active_wars():
            # case 1 alliance is aggressor
            if war.aggressor_id == alliance.alliance_id:
                war_target_ids.add(war.defender_id)
                war_target_ids |= set(war.allies.values_list("id", flat=True))

            # case 2 alliance is defender
            if war.defender_id == alliance.alliance_id:
                war_target_ids.add(war.aggressor_id)

            # case 3 alliance is ally
            if war.allies.filter(id=alliance.alliance_id).exists():
                war_target_ids.add(war.aggressor_id)

        return EveEntity.objects.filter(id__in=war_target_ids)

    def update_or_create_from_esi(self, id: int) -> Tuple[Any, bool]:
        """Updates existing or creates new objects from ESI with given ID."""

        entity_ids = set()
        war_info = esi_api.fetch_war(war_id=id)
        aggressor = self._get_or_create_eve_entity_from_participant(
            war_info["aggressor"]
        )
        entity_ids.add(aggressor.id)
        defender = self._get_or_create_eve_entity_from_participant(war_info["defender"])
        entity_ids.add(defender.id)
        with transaction.atomic():
            war, created = self.update_or_create(
                id=id,
                defaults={
                    "aggressor": aggressor,
                    "declared": war_info["declared"],
                    "defender": defender,
                    "is_mutual": war_info["mutual"],
                    "is_open_for_allies": war_info["open_for_allies"],
                    "retracted": war_info.get("retracted"),
                    "started": war_info.get("started"),
                    "finished": war_info.get("finished"),
                },
            )
            war.allies.clear()
            if war_info.get("allies"):
                for ally_info in war_info.get("allies", []):
                    try:
                        ally = self._get_or_create_eve_entity_from_participant(
                            ally_info
                        )
                    except ValueError:
                        logger.warning("%s: Could not identify ally: %s", id, ally_info)
                        continue
                    war.allies.add(ally)
                    entity_ids.add(ally.id)

        EveEntity.objects.bulk_resolve_ids(entity_ids)
        return war, created

    @staticmethod
    def _get_or_create_eve_entity_from_participant(participant: dict) -> EveEntity:
        """Get or create an EveEntity object from a war participant dict."""
        entity_id = participant.get("alliance_id") or participant.get("corporation_id")
        if not entity_id:
            raise ValueError(f"Invalid participant: {participant}")
        obj, _ = EveEntity.objects.get_or_create(id=entity_id)
        return obj

    def fetch_active_war_ids_esi(self) -> Set[int]:
        """Fetch IDs of all currently active wars."""
        war_ids = esi_api.fetch_war_ids()
        finished_war_ids = set(self.finished_wars().values_list("id", flat=True))
        war_ids = set(war_ids)
        return war_ids.difference(finished_war_ids)


EveWarManager = EveWarManagerBase.from_queryset(EveWarQuerySet)


class SyncManagerManager(models.Manager):
    def fetch_for_user(self, user: User) -> Any:
        """Fetch sync manager for given user. Return None if no match is found."""
        if not user.profile.main_character:
            return None

        try:
            alliance = EveAllianceInfo.objects.get(
                alliance_id=user.profile.main_character.alliance_id
            )
        except EveAllianceInfo.DoesNotExist:
            return None

        try:
            return self.get(alliance=alliance)
        except self.model.DoesNotExist:
            return None
