from http import HTTPStatus
from unittest.mock import patch

import pook

from eveuniverse.tests.testdata.factories_2 import EveEntityCharacterFactory

from app_utils.testing import NoSocketsTestCase

from standingssync.core import esi_api
from standingssync.core.esi_contacts import EsiContact
from standingssync.tests.factories import (
    EsiContactCharacterFactory,
    EsiContactLabelFactory,
    UserMainManagerFactory,
    UserMainSyncerFactory,
    make_esi_url,
)
from standingssync.tests.helpers import TestCaseWithClearCache

MODULE_PATH = "standingssync.core.esi_api"


class TestEsiApi(TestCaseWithClearCache):
    @pook.on
    def test_should_fetch_alliance_contacts(self):
        # given
        user = UserMainManagerFactory()
        alliance_id = user.profile.main_character.alliance_id
        token = user.token_set.first()
        contact_id = 1001
        EveEntityCharacterFactory
        pook.get(
            make_esi_url(f"alliances/{alliance_id}/contacts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "contact_id": contact_id,
                    "contact_type": "character",
                    "standing": 9.9,
                }
            ],
        )

        # when
        result = esi_api.fetch_alliance_contacts(alliance_id=alliance_id, token=token)

        # then
        expected = {
            EsiContact(contact_id, EsiContact.Category.CHARACTER, 9.9),
            EsiContact(alliance_id, EsiContact.Category.ALLIANCE, 10),
        }
        self.assertSetEqual(expected, result)

    @pook.on
    def test_should_fetch_character_contacts(self):
        # given
        user = UserMainSyncerFactory()
        character_id = user.profile.main_character.character_id
        token = user.token_set.first()
        contact_id = 1001
        pook.get(
            make_esi_url(f"characters/{character_id}/contacts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "contact_id": contact_id,
                    "contact_type": "corporation",
                    "standing": 9.9,
                }
            ],
        )

        # when
        result = esi_api.fetch_character_contacts(token=token)

        # then
        expected = {EsiContact(contact_id, EsiContact.Category.CORPORATION, 9.9)}
        self.assertSetEqual(expected, result)

    @pook.on
    def test_should_fetch_contact_labels(self):
        # given
        user = UserMainSyncerFactory()
        character_id = user.profile.main_character.character_id
        token = user.token_set.first()
        label_1 = EsiContactLabelFactory()
        label_2 = EsiContactLabelFactory()
        pook.get(
            make_esi_url(f"characters/{character_id}/contacts/labels"),
            reply=HTTPStatus.OK,
            response_json=[
                label_1.to_esi_dict(),
                label_2.to_esi_dict(),
            ],
        )

        # when
        result = esi_api.fetch_character_contact_labels(token=token)

        # then
        expected = {label_1, label_2}
        self.assertSetEqual(result, expected)

    @pook.on
    def test_should_add_character_contact(self):
        # given
        user = UserMainSyncerFactory()
        character_id = user.profile.main_character.character_id
        token = user.token_set.first()
        standing = 5.0
        contact = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), standing=standing
        )
        pook.post(
            url=make_esi_url(f"characters/{character_id}/contacts"),
            params={"standing": str(standing)},
            json=[contact.contact_id],
            reply=HTTPStatus.CREATED,
            response_json=[contact.contact_id],
        )

        # when
        esi_api.add_character_contacts(token, {contact})

        # then
        self.assertTrue(pook.isdone())

    @pook.on
    def test_should_update_character_contact(self):
        # given
        user = UserMainSyncerFactory()
        character_id = user.profile.main_character.character_id
        token = user.token_set.first()
        standing = 5.0
        contact = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), standing=standing
        )
        pook.put(
            url=make_esi_url(f"characters/{character_id}/contacts"),
            params={"standing": str(standing)},
            json=[contact.contact_id],
            reply=HTTPStatus.NO_CONTENT,
        )

        # when
        esi_api.update_character_contacts(token, {contact})

        # then
        self.assertTrue(pook.isdone())

    @pook.on
    def test_should_delete_character_contact(self):
        # given
        user = UserMainSyncerFactory()
        character_id = user.profile.main_character.character_id
        token = user.token_set.first()
        contact = EsiContact.from_eve_entity(EveEntityCharacterFactory(), standing=5.0)
        pook.delete(
            url=make_esi_url(f"characters/{character_id}/contacts"),
            params={"contact_ids": [str(contact.contact_id)]},
            reply=HTTPStatus.NO_CONTENT,
        )

        # when
        esi_api.delete_character_contacts(token, {contact})

        # then
        self.assertTrue(pook.isdone())


class TestEsiContactsHelpers(NoSocketsTestCase):
    def test_should_group_contacts_for_esi_update(self):
        # given
        label_1 = EsiContactLabelFactory(id=1)
        contact_1 = EsiContactCharacterFactory(contact_id=11, label_ids=[label_1.id])
        label_2 = EsiContactLabelFactory(id=2)
        contact_2 = EsiContactCharacterFactory(
            contact_id=12, label_ids=[label_1.id, label_2.id]
        )
        contact_3 = EsiContactCharacterFactory(contact_id=13, standing=2.0)
        contact_4 = EsiContactCharacterFactory(contact_id=14, standing=2.0)
        esi_contacts = [contact_1, contact_2, contact_3, contact_4]
        # when
        result = esi_api._group_for_esi_update(esi_contacts)
        self.maxDiff = None
        # then
        expected = {
            frozenset({1}): {contact_1.standing: {contact_1.contact_id}},
            frozenset({1, 2}): {contact_2.standing: {contact_2.contact_id}},
            frozenset(): {2.0: {contact_3.contact_id, contact_4.contact_id}},
        }
        self.assertEqual(expected, result)


class TestEsiWarsIDs(TestCaseWithClearCache):
    @pook.on
    def test_should_fetch_war_ids(self):
        # given
        exception_ids = [1]
        minimum_id = 3
        war_ids = [5, 4, 3, 2]
        pook.get(
            make_esi_url("wars"),
            reply=HTTPStatus.OK,
            response_json=war_ids,
        )

        # when
        with (
            patch(
                MODULE_PATH + ".STANDINGSSYNC_UNFINISHED_WARS_EXCEPTION_IDS",
                exception_ids,
            ),
            patch(
                MODULE_PATH + ".STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID", minimum_id
            ),
        ):
            got = esi_api.fetch_war_ids()

        # then
        self.assertSetEqual(got, {5, 4, 3, 1})
        self.assertTrue(pook.isdone())

    @pook.on
    def test_should_fetch_unknown_war_ids_only(self):
        # given
        exception_ids = [1]
        minimum_id = 3
        war_ids = [5, 4, 3, 2]
        pook.get(
            make_esi_url("wars"),
            reply=HTTPStatus.OK,
            response_json=war_ids,
        )

        # when
        with (
            patch(
                MODULE_PATH + ".STANDINGSSYNC_UNFINISHED_WARS_EXCEPTION_IDS",
                exception_ids,
            ),
            patch(
                MODULE_PATH + ".STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID", minimum_id
            ),
        ):
            got = esi_api.fetch_war_ids(4)

        # then
        self.assertSetEqual(got, {5})
        self.assertTrue(pook.isdone())

    @pook.on
    def test_should_fetch_war_ids_with_paging(self):
        # given
        exception_ids = [2]
        minimum_id = 4
        war_ids = [6, 5, 4]
        page_size = 2
        pook.get(
            make_esi_url("wars"),
            reply=HTTPStatus.OK,
            response_json=war_ids[:page_size],
        )
        pook.get(
            make_esi_url("wars"),
            params={"max_war_id": str(5)},
            reply=HTTPStatus.OK,
            response_json=war_ids[page_size:],
        )

        # when
        with (
            patch(
                MODULE_PATH + ".STANDINGSSYNC_UNFINISHED_WARS_EXCEPTION_IDS",
                exception_ids,
            ),
            patch(
                MODULE_PATH + ".STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID", minimum_id
            ),
            patch(MODULE_PATH + ".FETCH_WARS_MAX_ITEMS", page_size),
        ):
            got = esi_api.fetch_war_ids()

        # then
        self.assertSetEqual(got, set(war_ids) | set(exception_ids))
        self.assertTrue(pook.isdone())
