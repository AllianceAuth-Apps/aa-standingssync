"""Utility functions and classes for tests"""

from dataclasses import dataclass
from typing import Iterable, Set
from unittest.mock import MagicMock

from django.core.cache import cache
from django.db.models import QuerySet
from django.test import TestCase
from esi.models import Token

from standingssync.core.esi_contacts import (
    EsiContact,
    EsiContactLabel,
    EsiContactsContainer,
)


@dataclass
class EsiCharacterContactsStub:
    """Simulates the contacts for a character on ESI"""

    _character_id: int
    _contacts: EsiContactsContainer = None

    def contacts(self) -> Set[EsiContact]:
        return self._contacts.contacts()

    def contact_ids(self) -> Set[int]:
        return {contact.contact_id for contact in self._contacts.contacts()}

    def _setup_esi_mock(self, mock_esi_api: MagicMock):
        """Sets the mock for ESI to this object."""
        mock_esi_api.add_character_contacts = self._add_contacts
        mock_esi_api.delete_character_contacts = self._delete_contacts
        mock_esi_api.fetch_character_contact_labels = self._fetch_labels
        mock_esi_api.fetch_character_contacts = self._fetch_contacts
        mock_esi_api.update_character_contacts = self._update_contacts

    def _setup_contacts(self, contacts):
        for contact in contacts:
            self._contacts.add_contact(contact)

    def _setup_labels(self, labels):
        for label in labels:
            self._contacts.add_label(label)

    @classmethod
    def create(
        cls,
        character_id: int,
        mock_esi: MagicMock,
        *,
        contacts: Iterable[EsiContact] = None,
        labels: Iterable[EsiContactLabel] = None,
    ) -> "EsiCharacterContactsStub":
        """Create new obj for tests."""
        obj = cls(character_id, EsiContactsContainer())
        if labels:
            obj._setup_labels(labels)
        if contacts:
            obj._setup_contacts(contacts)
        if mock_esi:
            obj._setup_esi_mock(mock_esi)
        return obj

    def _fetch_contacts(self, token: Token):
        self._assert_correct_character(token.character_id)
        return self._contacts.contacts()

    def _fetch_labels(self, token: Token):
        self._assert_correct_character(token.character_id)
        return self._contacts.labels()

    def _add_contacts(self, token: Token, contacts: Iterable[EsiContact]):
        self._assert_correct_character(token.character_id)
        label_ids = set()
        for c in contacts:
            label_ids |= c.label_ids
        self._check_label_ids_valid(label_ids)
        for c in contacts:
            self._contacts.add_contact(c)

    def _update_contacts(self, token: Token, contacts: Iterable[EsiContact]):
        self._assert_correct_character(token.character_id)
        label_ids = set()
        for c in contacts:
            label_ids |= c.label_ids
        for c in contacts:
            self._contacts.update_contact(c)

    def _delete_contacts(self, token: Token, contacts: Iterable[EsiContact]):
        self._assert_correct_character(token.character_id)
        for c in contacts:
            self._contacts.remove_contact(c)

    def _assert_correct_character(self, character_id: int):
        if character_id != self._character_id:
            raise ValueError(f"Unknown character ID: {character_id}")

    def _check_label_ids_valid(self, label_ids: Iterable[int]):
        for label_id in label_ids:
            self._contacts.label_by_id(label_id)


class TestCaseWithClearCache(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cache.clear()


def extract(qs: QuerySet, field: str) -> Set[int]:
    """Return the extracted fields from the items of a query set."""
    return set(qs.values_list(field, flat=True))
