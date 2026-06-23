"""Core logic for handling ESI contacts."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from eveuniverse.models import EveEntity

from app_utils.helpers import chunks

from standingssync.app_settings import STANDINGSSYNC_WAR_TARGETS_LABEL_NAME
from standingssync.providers import esi


@dataclass(frozen=True)
class EsiContactLabel:
    """An ESI contact label. Immutable."""

    id: int
    name: str

    def __post_init__(self):
        object.__setattr__(self, "id", int(self.id))
        object.__setattr__(self, "name", str(self.name))

    def to_dict(self) -> dict:
        """Return as dict."""
        return {self.id: self.name}

    def to_esi_dict(self) -> dict:
        """Return as dict in ESI format."""
        return {"label_id": self.id, "label_name": self.name}

    @classmethod
    def from_esi_dict(cls, esi_dict: dict) -> "EsiContactLabel":
        """Create new obj from ESI dict."""
        return cls(id=esi_dict["label_id"], name=esi_dict["label_name"])


@dataclass(frozen=True)
class EsiContact:
    """An ESI contact. Immutable."""

    class Category(str, Enum):
        """The category of a contact."""

        ALLIANCE = "alliance"
        CHARACTER = "character"
        CORPORATION = "corporation"
        FACTION = "faction"

        @classmethod
        def from_esi_contact_type(cls, contact_type) -> "EsiContact.Category":
            """Create from an ESI contact type."""
            mapper = {
                "alliance": cls.ALLIANCE,
                "character": cls.CHARACTER,
                "corporation": cls.CORPORATION,
                "faction": cls.FACTION,
            }
            return mapper[contact_type]

    contact_id: int
    contact_type: Category
    standing: float
    label_ids: FrozenSet[int] = field(default_factory=frozenset)
    is_war_target: bool = False

    def __post_init__(self):
        object.__setattr__(self, "contact_id", int(self.contact_id))
        object.__setattr__(self, "contact_type", self.Category(self.contact_type))
        object.__setattr__(self, "standing", float(self.standing))
        object.__setattr__(self, "label_ids", frozenset(self.label_ids))
        object.__setattr__(self, "is_war_targets", bool(self.is_war_target))

    def clone(self, **kwargs) -> "EsiContact":
        """Clone this object and optional overwrite field values with kwargs."""
        field_names = [field.name for field in fields(self.__class__)]
        params = {key: getattr(self, key) for key in field_names}
        params.update(kwargs)
        new_obj = self.__class__(**params)
        return new_obj

    def to_esi_dict(self) -> dict:
        """Return as a dict."""
        obj = {
            "contact_id": self.contact_id,
            "contact_type": self.Category(self.contact_type).value,
            "standing": self.standing,
            "is_war_target": self.is_war_target,
        }
        if self.label_ids:
            obj["label_ids"] = sorted(list(self.label_ids))
        return obj

    @classmethod
    def from_esi_dict(cls, esi_dict: dict) -> "EsiContact":
        """Create new objects from an ESI contact."""
        return cls(
            contact_id=esi_dict["contact_id"],
            contact_type=EsiContact.Category.from_esi_contact_type(
                esi_dict["contact_type"]
            ),
            standing=esi_dict["standing"],
            label_ids=esi_dict.get("label_ids") or frozenset(),
        )

    @classmethod
    def from_eve_entity(
        cls,
        eve_entity: EveEntity,
        standing: float,
        label_ids: Optional[Iterable[int]] = None,
        is_war_target: bool = False,
    ) -> "EsiContact":
        """Create new instance from an EveEntity object."""
        contact_type_map = {
            EveEntity.CATEGORY_ALLIANCE: cls.Category.ALLIANCE,
            EveEntity.CATEGORY_CHARACTER: cls.Category.CHARACTER,
            EveEntity.CATEGORY_CORPORATION: cls.Category.CORPORATION,
            EveEntity.CATEGORY_FACTION: cls.Category.FACTION,
        }
        if eve_entity.category not in contact_type_map:
            raise ValueError(
                f"{eve_entity}: Can not create from eve entity without category"
            )
        return cls(
            contact_id=eve_entity.id,
            contact_type=contact_type_map[eve_entity.category],
            is_war_target=is_war_target,
            label_ids=label_ids if label_ids else frozenset(),
            standing=standing,
        )

    @classmethod
    def from_eve_contact(cls, eve_contact: Any, label_ids=None) -> "EsiContact":
        """Create new instance from an EveContact object."""
        contact_type_map = {
            EveEntity.CATEGORY_ALLIANCE: cls.Category.ALLIANCE,
            EveEntity.CATEGORY_CHARACTER: cls.Category.CHARACTER,
            EveEntity.CATEGORY_CORPORATION: cls.Category.CORPORATION,
        }
        return cls(
            contact_id=eve_contact.eve_entity.id,
            contact_type=contact_type_map[eve_contact.eve_entity.category],
            standing=eve_contact.standing,
            label_ids=label_ids if label_ids else frozenset(),
        )


@dataclass
class _character:
    id: int
    corporation_id: int
    standing: float
    alliance_id: Optional[int] = None


@dataclass
class _corporation:
    id: int
    standing: float
    alliance_id: Optional[int] = None
    faction_id: Optional[int] = None
    is_war_target: bool = False


@dataclass
class _alliance:
    id: int
    standing: float
    is_war_target: bool = False


# pylint: disable = too-many-public-methods
@dataclass
class EsiContactsContainer:
    """Container of ESI contacts with their labels."""

    _contacts: Dict[int, EsiContact] = field(
        default_factory=dict, init=False, repr=False
    )
    _labels: Dict[int, EsiContactLabel] = field(
        default_factory=dict, init=False, repr=False
    )

    def add_eve_contacts(
        self, contacts: Iterable[object], label_ids: Optional[List[int]] = None
    ):
        """Add eve contacts to this container."""
        for contact in contacts:
            self.add_contact(EsiContact.from_eve_contact(contact, label_ids=label_ids))

    def add_contact(self, contact: EsiContact):
        """Add contact to container. Unknown label IDs will be removed."""
        if contact.label_ids:
            label_ids = {
                label_id for label_id in contact.label_ids if label_id in self._labels
            }
        else:
            label_ids = []
        self._contacts[contact.contact_id] = contact.clone(label_ids=label_ids)

    def add_label(self, label: EsiContactLabel):
        """Add contact label."""
        self._labels[label.id] = deepcopy(label)

    def clone(self) -> "EsiContactsContainer":
        """Return a clone of this object."""
        other = self.__class__.from_esi_contacts(
            contacts=self.contacts(), labels=self.labels()
        )
        return other

    def contact_by_id(self, contact_id: int) -> EsiContact:
        """Returns contact by it's ID.

        Raises ValueError when contact is not found.
        """
        try:
            return self._contacts[contact_id]
        except KeyError:
            raise ValueError(f"Contact with ID {contact_id} not found.") from None

    def contact_ids(self) -> Set[int]:
        """Return all contact IDs"""
        result = set(self._contacts)
        return result

    def contacts(self) -> Set[EsiContact]:
        """Fetch all contacts."""
        return set(self._contacts.values())

    # pylint: disable = protected-access
    def contacts_difference(
        self, other: "EsiContactsContainer"
    ) -> Tuple[Set[EsiContact], Set[EsiContact], Set[EsiContact]]:
        """Identify which contacts have been added, removed or changed."""
        current_contact_ids = set(self._contacts.keys())
        other_contact_ids = set(other._contacts.keys())
        removed = {
            contact
            for contact_id, contact in self._contacts.items()
            if contact_id in (current_contact_ids - other_contact_ids)
        }
        added = {
            contact
            for contact_id, contact in other._contacts.items()
            if contact_id in (other_contact_ids - current_contact_ids)
        }
        added_and_changed = set(other._contacts.values()) - set(self._contacts.values())
        changed = added_and_changed - added
        return added, removed, changed

    def contacts_to_esi_dicts(self) -> List[dict]:
        """Convert contacts into a stable dictionary."""
        return [
            obj.to_esi_dict()
            for obj in sorted(self._contacts.values(), key=lambda o: o.contact_id)
        ]

    def labels_to_esi_dicts(self) -> List[dict]:
        """Convert labels into a stable dictionary."""
        return [
            obj.to_esi_dict()
            for obj in sorted(self._labels.values(), key=lambda o: o.id)
        ]

    def label_by_id(self, label_id) -> EsiContactLabel:
        """Returns label by it's ID.

        Raises ValueError when label is not found.
        """
        try:
            return self._labels[label_id]
        except KeyError:
            raise ValueError(f"Label with ID {label_id} not found.") from None

    def labels(self) -> Set[EsiContactLabel]:
        """Fetch all labels."""
        return set(self._labels.values())

    def prune(self, unmask_war_targets=True, compress_contacts=False) -> int:
        """Prune contacts.

        When unmask_war_targets is True, prune will remove contacts shadowing
        the standing of war targets:
        - characters belonging to a war target with different standings
        - corporations belonging to a war target with different standings

        When compress_contacts is True, prune will also remove contacts
        which are unnecessary to calculate their effective standing:
        - faction contacts
        - characters and when their alliances exist as contact and has same standing
        - characters when their corporations exist as contact and has same standing
        - corporations when their alliances exist as contact and has same standing
        - neutral characters when their corporation and alliance do not exist as contact
        - neutral corporations when their corporation and alliance do not exist as contact
        - neutral alliances
        """
        # collect contacts
        characters = {
            x.contact_id: _character(
                id=x.contact_id, corporation_id=0, standing=x.standing
            )
            for x in self.contacts()
            if x.contact_type == EsiContact.Category.CHARACTER
        }
        corporations = {
            x.contact_id: _corporation(
                id=x.contact_id, standing=x.standing, is_war_target=x.is_war_target
            )
            for x in self.contacts()
            if x.contact_type == EsiContact.Category.CORPORATION
        }
        alliances = {
            x.contact_id: _alliance(
                id=x.contact_id, standing=x.standing, is_war_target=x.is_war_target
            )
            for x in self.contacts()
            if x.contact_type == EsiContact.Category.ALLIANCE
        }

        # add character affiliations
        for chunk in chunks(list(characters.keys()), 1000):
            affiliations = esi.client.Character.PostCharactersAffiliation(
                body=chunk
            ).result(use_etag=False)
            for x in affiliations:
                characters[x.character_id].corporation_id = x.corporation_id
                characters[x.character_id].alliance_id = x.alliance_id

        # add corporation affiliations
        for corporation_id in corporations.keys():
            info = esi.client.Corporation.GetCorporationsCorporationId(
                corporation_id=corporation_id
            ).result(use_etag=False)
            corporations[corporation_id].alliance_id = info.alliance_id

        # remove alliances
        if compress_contacts:
            for alliance_id in list(alliances.keys()):
                obj = alliances[alliance_id]
                if obj.standing == 0:
                    del alliances[alliance_id]

        # remove corporations
        for corporation_id in list(corporations.keys()):
            obj = corporations[corporation_id]
            alliance = None
            if obj.alliance_id:
                try:
                    alliance = alliances[obj.alliance_id]
                except KeyError:
                    pass

            if unmask_war_targets and alliance and alliance.is_war_target:
                del corporations[corporation_id]
                continue

            if compress_contacts and alliance and alliance.standing == obj.standing:
                del corporations[corporation_id]
                continue

            if compress_contacts and obj.standing == 0 and not alliance:
                del corporations[corporation_id]
                continue

        # remove characters
        for character_id in list(characters.keys()):
            obj = characters[character_id]
            try:
                corporation = corporations[obj.corporation_id]
            except KeyError:
                corporation = None

            if unmask_war_targets and corporation and corporation.is_war_target:
                del characters[character_id]
                continue

            if (
                compress_contacts
                and corporation
                and corporation.standing == obj.standing
            ):
                del characters[character_id]
                continue

            alliance = None
            if obj.alliance_id:
                try:
                    alliance = alliances[obj.alliance_id]
                except KeyError:
                    pass

            if unmask_war_targets and alliance and alliance.is_war_target:
                del characters[character_id]
                continue

            if compress_contacts and alliance and alliance.standing == obj.standing:
                del characters[character_id]
                continue

            if (
                compress_contacts
                and obj.standing == 0
                and not corporation
                and not alliance
            ):
                del characters[character_id]
                continue

        # updated contacts
        remaining_ids = characters.keys() | corporations.keys() | alliances.keys()
        if not compress_contacts:
            remaining_ids |= {
                x.contact_id
                for x in self.contacts()
                if x.contact_type == EsiContact.Category.FACTION
            }
        to_delete = self.contact_ids().difference(remaining_ids)
        for contact_id in to_delete:
            del self._contacts[contact_id]

        return len(to_delete)

    def remove_contact(self, contact: EsiContact):
        """Remove contact."""
        try:
            del self._contacts[contact.contact_id]
        except KeyError:
            raise ValueError(
                f"Unknown contact {contact} could not be removed."
            ) from None

    def remove_contacts(self, contacts: Iterable[EsiContact]):
        """Remove several contacts."""
        for contact in contacts:
            self.remove_contact(contact)

    def remove_war_targets(self):
        """Remove war targets."""
        self.remove_contacts(self.war_targets())

    def to_dict(self) -> dict:
        """Convert this object into a stable dictionary."""
        data = {
            "contacts": self.contacts_to_esi_dicts(),
            "labels": self.labels_to_esi_dicts(),
        }
        return data

    def update_contact(self, contact: EsiContact) -> bool:
        """Update an existing contact and return whether it was successful."""
        if contact.contact_id not in self._contacts:
            return False
        self._contacts[contact.contact_id] = contact
        return True

    def version_hash(self) -> str:
        """Calculate hash for current contacts & label in order to identify changes."""
        data = self.to_dict()
        return hashlib.md5(json.dumps(data).encode("utf-8")).hexdigest()

    def war_targets(self) -> Set[EsiContact]:
        """Fetch contacts that are war targets."""
        war_target_id = self.war_target_label_id()
        contacts = {obj for obj in self.contacts() if war_target_id in obj.label_ids}
        return contacts

    def war_target_label_id(self) -> Optional[int]:
        """Fetch the ID of the configured war target label."""
        for label in self._labels.values():
            if label.name.lower() == STANDINGSSYNC_WAR_TARGETS_LABEL_NAME.lower():
                return label.id
        return None

    @classmethod
    def from_esi_contacts(
        cls,
        contacts: Optional[Iterable[EsiContact]] = None,
        labels: Optional[Iterable[EsiContactLabel]] = None,
    ) -> "EsiContactsContainer":
        """Create new object from Esi contacts."""
        obj = cls()
        if labels:
            for label in labels:
                obj.add_label(label)
        if contacts:
            for contact in contacts:
                obj.add_contact(contact)
        return obj

    @classmethod
    def from_esi_dicts(
        cls,
        contacts: Optional[Iterable[dict]] = None,
        labels: Optional[Iterable[dict]] = None,
    ) -> "EsiContactsContainer":
        """Create new object from ESI contacts and labels."""
        obj = cls()
        if labels:
            for label in labels:
                obj.add_label(EsiContactLabel.from_esi_dict(label))
        if contacts:
            for contact in contacts:
                obj.add_contact(EsiContact.from_esi_dict(contact))
        return obj
