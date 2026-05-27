from unittest.mock import patch

from django.test import TestCase, override_settings
from eveuniverse.models import EveEntity
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
)

from allianceauth.eveonline.models import EveAllianceInfo
from app_utils.esi_testing import BravadoOperationStub
from app_utils.testing import NoSocketsTestCase, reset_celery_once_locks

from standingssync.core.esi_contacts import EsiContact, EsiContactLabel
from standingssync.tasks import run_manager_sync

from .factories import (
    EveWarFactory,
    SyncedCharacterFactory,
    SyncManagerFactory,
    UserMainSyncerFactory,
)
from .utils import EsiCharacterContactsStub, create_esi_contact

ESI_CONTACTS_PATH = "standingssync.core.esi_contacts"
ESI_API_PATH = "standingssync.core.esi_api"
MODELS_PATH = "standingssync.models"


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@patch(ESI_CONTACTS_PATH + ".STANDINGSSYNC_WAR_TARGETS_LABEL_NAME", "WAR TARGETS")
@patch(ESI_API_PATH + ".esi")
class TestTasksE2E(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reset_celery_once_locks("standingssync")

    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_sync_manager_and_character_no_wt(self, mock_esi):
        # given
        manager = SyncManagerFactory()
        sync_character = SyncedCharacterFactory(manager=manager)
        character = EveEntityCharacterFactory(
            id=sync_character.character.character_id,
            name=sync_character.character.character_name,
        )
        some_alliance_contact = EveEntityCharacterFactory()
        alliance_contacts = [
            create_esi_contact(character),
            create_esi_contact(some_alliance_contact),
        ]
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub(alliance_contacts)
        )
        esi_character_contacts = EsiCharacterContactsStub.create(
            sync_character.character.character_id, mock_esi
        )
        # when
        run_manager_sync.delay(manager_pk=manager.pk)
        # then
        expected = {
            EsiContact.from_eve_entity(some_alliance_contact, standing=5),
            EsiContact(manager.alliance.alliance_id, "alliance", standing=10),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)
        self.assertNotIn(
            sync_character.character.character_id, esi_character_contacts.contact_ids()
        )

    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_sync_manager_and_character_with_wt_as_defender(self, mock_esi):
        # given
        manager = SyncManagerFactory()
        alliance = EveEntity.objects.get(id=manager.alliance.alliance_id)
        war = EveWarFactory(defender=alliance)
        sync_character = SyncedCharacterFactory(manager=manager)
        character = EveEntityCharacterFactory(
            id=sync_character.character.character_id,
            name=sync_character.character.character_name,
        )
        some_alliance_contact = EveEntityCharacterFactory()
        alliance_contacts = [
            create_esi_contact(character),
            create_esi_contact(some_alliance_contact),
        ]
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub(alliance_contacts)
        )
        war_target_label = EsiContactLabel(1, "WAR TARGETS")
        esi_character_contacts = EsiCharacterContactsStub.create(
            character.id, mock_esi, labels=[war_target_label]
        )
        # when
        run_manager_sync.delay(manager_pk=manager.pk)
        # then
        expected = {
            EsiContact.from_eve_entity(some_alliance_contact, standing=5),
            EsiContact(
                manager.alliance.alliance_id,
                EsiContact.ContactType.ALLIANCE,
                standing=10,
            ),
            EsiContact.from_eve_entity(
                war.aggressor, standing=-10, label_ids=[war_target_label.id]
            ),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_sync_manager_and_character_with_wt_as_aggressor(self, mock_esi):
        # given
        manager = SyncManagerFactory()
        alliance = EveEntity.objects.get(id=manager.alliance.alliance_id)
        ally = EveEntityAllianceFactory()
        war = EveWarFactory(aggressor=alliance, allies=[ally])
        sync_character = SyncedCharacterFactory(manager=manager)
        character = EveEntityCharacterFactory(
            id=sync_character.character.character_id,
            name=sync_character.character.character_name,
        )
        some_alliance_contact = EveEntityCharacterFactory()
        some_character_contact = EveEntityCharacterFactory()
        alliance_contacts = [
            create_esi_contact(character),
            create_esi_contact(some_alliance_contact),
        ]
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub(alliance_contacts)
        )
        war_target_label = EsiContactLabel(1, "WAR TARGETS")
        esi_character_contacts = EsiCharacterContactsStub.create(
            character.id,
            mock_esi,
            contacts=[
                EsiContact.from_eve_entity(ally, standing=5),
                EsiContact.from_eve_entity(some_character_contact, standing=10),
            ],
            labels=[war_target_label],
        )
        # when
        run_manager_sync.delay(manager_pk=manager.pk)
        # then
        expected = {
            EsiContact.from_eve_entity(some_alliance_contact, standing=5),
            EsiContact(
                manager.alliance.alliance_id,
                EsiContact.ContactType.ALLIANCE,
                standing=10,
            ),
            EsiContact.from_eve_entity(
                war.defender, standing=-10, label_ids=[war_target_label.id]
            ),
            EsiContact.from_eve_entity(
                ally, standing=-10, label_ids=[war_target_label.id]
            ),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_sync_manager_and_character_with_wt_as_aggressor_2(self, mock_esi):
        # given
        manager = SyncManagerFactory()
        alliance = EveEntity.objects.get(id=manager.alliance.alliance_id)
        ally = EveEntityAllianceFactory()
        war = EveWarFactory(aggressor=alliance, allies=[ally])
        sync_character = SyncedCharacterFactory(manager=manager)
        character = EveEntityCharacterFactory(
            id=sync_character.character.character_id,
            name=sync_character.character.character_name,
        )
        some_alliance_contact = EveEntityCharacterFactory()
        some_character_contact = EveEntityCharacterFactory()
        alliance_contacts = [
            create_esi_contact(character),
            create_esi_contact(some_alliance_contact),
        ]
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub(alliance_contacts)
        )
        war_target_label = EsiContactLabel(1, "WAR TARGETS")
        esi_character_contacts = EsiCharacterContactsStub.create(
            character.id,
            mock_esi,
            labels=[war_target_label],
            contacts=[
                EsiContact.from_eve_entity(ally, standing=5),
                EsiContact.from_eve_entity(some_character_contact, standing=10),
            ],
        )
        # when
        run_manager_sync.delay(manager_pk=manager.pk)
        # then
        expected = {
            # EsiContact.from_eve_entity(alliance, standing=10),
            EsiContact.from_eve_entity(
                war.defender, standing=-10, label_ids=[war_target_label.id]
            ),
            EsiContact.from_eve_entity(
                ally, standing=-10, label_ids=[war_target_label.id]
            ),
            EsiContact.from_eve_entity(some_character_contact, standing=10),
            # EsiContact.from_eve_entity(some_alliance_contact, standing=5),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)


class TestUI(TestCase):
    def test_should_open_main_page_wo_syn_manager(self):
        # given
        user = UserMainSyncerFactory()
        self.client.force_login(user)
        # when
        response = self.client.get("/standingssync/characters")
        # then
        self.assertEqual(response.status_code, 200)

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
        self.assertEqual(response.status_code, 200)

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
        self.assertEqual(response.status_code, 200)

    def test_should_open_wars_page_wo_sync_manager(self):
        # given
        user = UserMainSyncerFactory()
        self.client.force_login(user)
        # when
        response = self.client.get("/standingssync/wars")
        # then
        self.assertEqual(response.status_code, 200)
