from http import HTTPStatus
from unittest.mock import patch

import pook

from django.test import TestCase, override_settings
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
)

from allianceauth.eveonline.models import EveAllianceInfo

from standingssync import tasks

from .factories import (
    EveWarFactory,
    SyncedCharacterFactory,
    SyncManagerFactory,
    UserMainManagerFactory,
    UserMainSyncerFactory,
    make_esi_url,
)
from .helpers import TestCaseWithClearCache

ESI_CONTACTS_PATH = "standingssync.core.esi_contacts"
ESI_API_PATH = "standingssync.core.esi_api"
MODELS_PATH = "standingssync.models"


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestTasksE2E(TestCaseWithClearCache):
    @pook.on
    def test_should_sync_manager_and_character_without_war_targets(self):
        # given
        user_1 = UserMainManagerFactory()
        sm = SyncManagerFactory(user=user_1)
        alliance_id = user_1.profile.main_character.alliance_id
        contact_1_id = 1001
        EveEntityCharacterFactory(id=contact_1_id)
        standing = 9.9
        pook.get(
            make_esi_url(f"alliances/{alliance_id}/contacts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "contact_id": contact_1_id,
                    "contact_type": "character",
                    "standing": standing,
                }
            ],
        )
        sc = SyncedCharacterFactory(manager=sm)
        pook.get(
            make_esi_url(f"characters/{sc.character_id}/contacts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[],
        )
        pook.get(
            make_esi_url(f"characters/{sc.character_id}/contacts/labels"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[],
        )
        pook.post(
            url=make_esi_url(f"characters/{sc.character_id}/contacts"),
            params={"standing": str(10.0)},
            json=[sm.alliance.alliance_id],
            reply=HTTPStatus.CREATED,
            response_json=[sm.alliance.id],
        )
        pook.post(
            url=make_esi_url(f"characters/{sc.character_id}/contacts"),
            params={"standing": str(standing)},
            json=[contact_1_id],
            reply=HTTPStatus.CREATED,
            response_json=[contact_1_id],
        )

        # when
        with (
            patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True),
            patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True),
        ):
            tasks.run_manager_sync.delay(manager_pk=sm.pk)

        # then
        self.assertTrue(pook.isdone())

    @pook.on
    def test_should_sync_manager_and_character_with_war_targets(self):
        # given
        user_1 = UserMainManagerFactory()
        sm = SyncManagerFactory(user=user_1)
        alliance_id = user_1.profile.main_character.alliance_id
        contact_1_id = 1001
        EveEntityCharacterFactory(id=contact_1_id)
        standing = 9.9
        aggressor = EveEntityAllianceFactory()
        EveWarFactory(
            aggressor=aggressor, defender=EveEntityAllianceFactory(id=alliance_id)
        )
        pook.get(
            make_esi_url(f"alliances/{alliance_id}/contacts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "contact_id": contact_1_id,
                    "contact_type": "character",
                    "standing": standing,
                }
            ],
        )
        sc = SyncedCharacterFactory(manager=sm)
        pook.get(
            make_esi_url(f"characters/{sc.character_id}/contacts"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[],
        )
        wt_label_name = "WAR TARGETS"
        wt_label_id = 7
        pook.get(
            make_esi_url(f"characters/{sc.character_id}/contacts/labels"),
            reply=HTTPStatus.OK,
            response_headers={"X-Pages": "1"},
            response_json=[
                {
                    "label_id": wt_label_id,
                    "label_name": wt_label_name,
                }
            ],
        )
        pook.post(
            url=make_esi_url(f"characters/{sc.character_id}/contacts"),
            params={"standing": str(10.0)},
            json=[sm.alliance.alliance_id],
            reply=HTTPStatus.CREATED,
            response_json=[sm.alliance.id],
        )
        pook.post(
            url=make_esi_url(f"characters/{sc.character_id}/contacts"),
            params={"standing": str(standing)},
            json=[contact_1_id],
            reply=HTTPStatus.CREATED,
            response_json=[contact_1_id],
        )
        pook.post(
            url=make_esi_url(f"characters/{sc.character_id}/contacts"),
            params={"standing": str(-10.0), "label_ids": [str(wt_label_id)]},
            json=[aggressor.id],
            reply=HTTPStatus.CREATED,
            response_json=[aggressor.id],
        )

        # when
        with (
            patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True),
            patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True),
            patch(
                ESI_CONTACTS_PATH + ".STANDINGSSYNC_WAR_TARGETS_LABEL_NAME",
                wt_label_name,
            ),
        ):
            tasks.run_manager_sync.delay(manager_pk=sm.pk)

        # then
        self.assertTrue(pook.isdone())


class TestUI(TestCase):
    def test_should_open_main_page_wo_syn_manager(self):
        # given
        user = UserMainSyncerFactory()
        self.client.force_login(user)
        # when
        response = self.client.get("/standingssync/characters")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_should_open_main_page_w_sync_manager_and_chars(self):
        # given
        user = UserMainSyncerFactory()
        alliance = EveAllianceInfo.objects.get(
            alliance_id=user.profile.main_character.alliance_id
        )
        sync_manager = SyncManagerFactory(alliance=alliance)
        SyncedCharacterFactory(manager=sync_manager)
        self.client.force_login(user)
        # when
        response = self.client.get("/standingssync/characters")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_should_open_wars_page_w_sync_manager(self):
        # given
        user = UserMainSyncerFactory()
        alliance = EveAllianceInfo.objects.get(
            alliance_id=user.profile.main_character.alliance_id
        )
        sync_manager = SyncManagerFactory(alliance=alliance)
        SyncedCharacterFactory(manager=sync_manager)
        self.client.force_login(user)
        # when
        response = self.client.get("/standingssync/wars")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_should_open_wars_page_wo_sync_manager(self):
        # given
        user = UserMainSyncerFactory()
        self.client.force_login(user)
        # when
        response = self.client.get("/standingssync/wars")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
