"""Wrapper for handling all access to the ESI API."""

from collections import defaultdict
from typing import Callable, Dict, FrozenSet, Iterable, Optional, Set

from esi.models import Token

from allianceauth.services.hooks import get_extension_logger
from app_utils.helpers import chunks

from standingssync.app_settings import (
    STANDINGSSYNC_UNFINISHED_WARS_EXCEPTION_IDS,
    STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID,
)
from standingssync.providers import esi

from .esi_contacts import EsiContact, EsiContactLabel

logger = get_extension_logger(__name__)

FETCH_WARS_MAX_ITEMS = 2000

logger = get_extension_logger(__name__)


def add_character_contacts(token: Token, contacts: Iterable[EsiContact]) -> None:
    """Add new contacts on ESI for a character."""
    _update_character_contacts(
        token=token,
        contacts=contacts,
        esi_method=esi.client.Contacts.post_characters_character_id_contacts,
    )
    logger.info("%s: Added %d contacts", token.character_name, len(contacts))


def delete_character_contacts(token: Token, contacts: Iterable[EsiContact]):
    """Delete character contacts on ESI."""
    max_items = 20
    contact_ids = sorted([contact.contact_id for contact in contacts])
    contact_ids_chunks = chunks(contact_ids, max_items)
    for contact_ids_chunk in contact_ids_chunks:
        esi.client.Contacts.delete_characters_character_id_contacts(
            token=token.valid_access_token(),
            character_id=token.character_id,
            contact_ids=contact_ids_chunk,
        ).results()

    logger.info("%s: Deleted %d contacts", token.character_name, len(contact_ids))


def fetch_alliance_contacts(alliance_id: int, token: Token) -> Set[EsiContact]:
    """Fetch alliance contacts from ESI."""
    contacts_raw = esi.client.Contacts.get_alliances_alliance_id_contacts(
        token=token.valid_access_token(), alliance_id=alliance_id
    ).results(ignore_cache=True)
    contacts = {
        int(row["contact_id"]): EsiContact.from_esi_dict(row) for row in contacts_raw
    }
    # add the sync alliance with max standing to contacts
    contacts[alliance_id] = EsiContact(
        contact_id=alliance_id,
        contact_type=EsiContact.Category.ALLIANCE,
        standing=10,
    )
    return set(contacts.values())


def fetch_character_contacts(token: Token) -> Set[EsiContact]:
    """Fetch character contacts from ESI."""
    character_contacts_raw = esi.client.Contacts.get_characters_character_id_contacts(
        token=token.valid_access_token(), character_id=token.character_id
    ).results(ignore_cache=True)
    logger.info(
        "%s: Fetched %d current contacts",
        token.character_name,
        len(character_contacts_raw),
    )
    character_contacts = {
        EsiContact.from_esi_dict(contact) for contact in character_contacts_raw
    }
    return character_contacts


def fetch_character_contact_labels(token: Token) -> Set[EsiContactLabel]:
    """Fetch contact labels for character from ESI."""
    labels_raw = esi.client.Contacts.get_characters_character_id_contacts_labels(
        character_id=token.character_id, token=token.valid_access_token()
    ).results(ignore_cache=True)
    logger.info("%s: Fetched %d current labels", token.character_name, len(labels_raw))
    labels = {EsiContactLabel.from_esi_dict(label) for label in labels_raw}
    return labels


def update_character_contacts(token: Token, contacts: Iterable[EsiContact]) -> None:
    """Update existing character contacts on ESI."""
    _update_character_contacts(
        token=token,
        contacts=contacts,
        esi_method=esi.client.Contacts.put_characters_character_id_contacts,
    )
    logger.info("%s: Updated %d contacts", token.character_name, len(contacts))


def _update_character_contacts(
    token: Token, contacts: Iterable[EsiContact], esi_method: Callable
) -> None:
    for label_ids, contacts_by_standing in _group_for_esi_update(contacts).items():
        _update_character_contacts_esi(
            token=token,
            contacts_by_standing=contacts_by_standing,
            esi_method=esi_method,
            label_ids=list(label_ids) if label_ids else None,
        )


def _update_character_contacts_esi(
    token: Token,
    contacts_by_standing: Dict[float, Iterable[int]],
    esi_method: Callable,
    label_ids: Optional[list] = None,
) -> None:
    """Add new or update existing character contacts on ESI."""
    max_items = 100
    for standing in contacts_by_standing:
        contact_ids = sorted(list(contacts_by_standing[standing]))
        for contact_ids_chunk in chunks(contact_ids, max_items):
            params = {
                "token": token.valid_access_token(),
                "character_id": token.character_id,
                "contact_ids": contact_ids_chunk,
                "standing": standing,
            }
            if label_ids is not None:
                params["label_ids"] = sorted(list(label_ids))
            esi_method(**params).results()


def _group_for_esi_update(
    contacts: Iterable["EsiContact"],
) -> Dict[FrozenSet, Dict[float, Iterable[int]]]:
    """Group contacts for ESI update."""
    contacts_grouped = {}
    for contact in contacts:
        if contact.label_ids not in contacts_grouped:
            contacts_grouped[contact.label_ids] = defaultdict(set)
        contacts_grouped[contact.label_ids][contact.standing].add(contact.contact_id)
    return contacts_grouped


def fetch_war_ids() -> Set[int]:
    """Fetch IDs for new and unfinished wars from ESI.

    Will ignore older wars which are known to be already finished.
    """
    war_ids = []
    war_ids_page = esi.client.Wars.get_wars().results(ignore_cache=True)
    while True:
        war_ids += war_ids_page
        if (
            len(war_ids_page) < FETCH_WARS_MAX_ITEMS
            or min(war_ids_page) < STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID
        ):
            break
        max_war_id = min(war_ids)
        war_ids_page = esi.client.Wars.get_wars(max_war_id=max_war_id).results(
            ignore_cache=True
        )

    logger.info("Fetched %d war IDs from ESI", len(war_ids))

    war_ids = {
        war_id
        for war_id in war_ids
        if war_id >= STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID
    }
    war_ids = war_ids.union(set(STANDINGSSYNC_UNFINISHED_WARS_EXCEPTION_IDS))

    return war_ids


def fetch_war(war_id: int) -> dict:
    """Fetch details about a war from ESI."""
    war_info = esi.client.Wars.get_wars_war_id(war_id=war_id).results(ignore_cache=True)
    logger.info("Retrieved war details for ID %s", war_id)
    return war_info
