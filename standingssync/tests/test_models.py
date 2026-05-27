import datetime as dt
from typing import Set
from unittest.mock import patch

from django.utils.timezone import now
from esi.errors import TokenExpiredError, TokenInvalidError
from esi.models import Token
from eveuniverse.models import EveEntity
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
    EveEntityCorporationFactory,
)

from allianceauth.eveonline.models import EveCharacter
from app_utils.esi_testing import BravadoOperationStub, EsiClientStub, EsiEndpoint
from app_utils.testing import NoSocketsTestCase

from standingssync.core.esi_contacts import EsiContact, EsiContactsContainer
from standingssync.models import SyncedCharacter, SyncManager

from .factories import (
    EsiContactFactory,
    EsiContactLabelFactory,
    EveContactFactory,
    EveContactWarTargetFactory,
    EveWarFactory,
    SyncedCharacterFactory,
    SyncManagerFactory,
    UserMainManagerFactory,
    UserMainSyncerFactory,
)
from .utils import ALLIANCE_CONTACTS, EsiCharacterContactsStub, load_eve_entities

ESI_CONTACTS_PATH = "standingssync.core.esi_contacts"
ESI_API_PATH = "standingssync.core.esi_api"
MODELS_PATH = "standingssync.models"
WAR_TARGET_LABEL = "WAR TARGETS"


class TestSyncManager(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserMainManagerFactory()
        cls.alliance_id = cls.user.profile.main_character.alliance_id

    def test_should_return_token(self):
        # given
        obj = SyncManagerFactory()
        # when/then
        self.assertIsInstance(obj.fetch_token(), Token)

    def test_should_return_none_when_no_character_ownership(self):
        # given
        obj = SyncManagerFactory(character_ownership=None)
        # when/then
        self.assertIsNone(obj.fetch_token())

    def test_should_return_character(self):
        # given
        obj = SyncManagerFactory()
        # when/then
        self.assertEqual(obj.character, obj.character_ownership.character)  # type: ignore

    def test_should_raise_error_when_no_character(self):
        # given
        obj = SyncManagerFactory(character_ownership=None)
        # when
        with self.assertRaises(ValueError):
            _ = obj.character

    def test_should_report_sync_as_ok(self):
        # given
        my_dt = now()
        sync_manager = SyncManagerFactory(last_sync_at=my_dt - dt.timedelta(minutes=1))
        # when/then
        with patch(MODELS_PATH + ".STANDINGSSYNC_SYNC_TIMEOUT", 60):
            self.assertTrue(sync_manager.is_sync_fresh)

    def test_should_report_sync_as_not_ok(self):
        # given
        my_dt = now()
        sync_manager = SyncManagerFactory(last_sync_at=my_dt - dt.timedelta(minutes=61))
        # when/then
        with patch(MODELS_PATH + ".STANDINGSSYNC_SYNC_TIMEOUT", 60):
            self.assertFalse(sync_manager.is_sync_fresh)


def war_target_contact_ids(sync_manager: SyncManager) -> Set[int]:
    query = sync_manager.contacts.filter(is_war_target=True).values_list(
        "eve_entity_id", flat=True
    )
    return set(query)


@patch(ESI_API_PATH + ".esi")
class TestSyncManagerRunSync(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserMainManagerFactory()
        cls.alliance_id = cls.user.profile.main_character.alliance_id
        load_eve_entities()
        cls.endpoints = [
            EsiEndpoint(
                "Contacts",
                "get_alliances_alliance_id_contacts",
                "alliance_id",
                needs_token=True,
                data={
                    str(cls.alliance_id): ALLIANCE_CONTACTS,
                },
            )
        ]
        cls.esi_client_stub = EsiClientStub.create_from_endpoints(cls.endpoints)
        cls.expected_contact_ids = {obj["contact_id"] for obj in ALLIANCE_CONTACTS}
        cls.expected_contact_ids.add(cls.alliance_id)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_add_new_contacts_from_scratch_no_wt(self, mock_esi):
        # given
        mock_esi.client = self.esi_client_stub
        sync_manager = SyncManagerFactory(user=self.user)

        # when
        sync_manager.run_sync()

        # then
        sync_manager.refresh_from_db()
        result_contact_ids = set(
            sync_manager.contacts.values_list("eve_entity_id", flat=True)
        )
        self.assertSetEqual(self.expected_contact_ids, result_contact_ids)
        contact = sync_manager.contacts.get(eve_entity_id=3015)
        self.assertEqual(contact.standing, 10.0)
        self.assertFalse(contact.is_war_target)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_update_existing_contacts_no_wt(self, mock_esi):
        # given
        mock_esi.client = self.esi_client_stub
        sync_manager = SyncManagerFactory(user=self.user)
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=1002),
            standing=-5,
        )

        # when
        sync_manager.run_sync()

        # then
        sync_manager.refresh_from_db()
        result_contact_ids = set(
            sync_manager.contacts.values_list("eve_entity_id", flat=True)
        )
        self.assertSetEqual(self.expected_contact_ids, result_contact_ids)
        contact = sync_manager.contacts.get(eve_entity_id=1002)
        self.assertEqual(contact.standing, 10.0)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_remove_obsolete_contacts_no_wt(self, mock_esi):
        # given
        mock_esi.client = self.esi_client_stub
        sync_manager = SyncManagerFactory(user=self.user)
        new_contact = EveContactFactory(
            manager=sync_manager, eve_entity=EveEntityCharacterFactory(), standing=-5
        )

        # when
        sync_manager.run_sync()

        # then
        sync_manager.refresh_from_db()
        result_contact_ids = set(
            sync_manager.contacts.values_list("eve_entity_id", flat=True)
        )
        self.assertSetEqual(self.expected_contact_ids, result_contact_ids)
        self.assertFalse(
            sync_manager.contacts.filter(
                eve_entity_id=new_contact.eve_entity_id
            ).exists()
        )

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_add_new_contacts_from_scratch_with_wt(self, mock_esi):
        # given
        mock_esi.client = self.esi_client_stub
        sync_manager = SyncManagerFactory(user=self.user)
        EveWarFactory(
            aggressor=EveEntity.objects.get(id=3015),
            defender=EveEntity.objects.get(id=self.alliance_id),
        )

        # when
        sync_manager.run_sync()

        # then
        sync_manager.refresh_from_db()
        result_contact_ids = set(
            sync_manager.contacts.values_list("eve_entity_id", flat=True)
        )
        self.assertSetEqual(self.expected_contact_ids, result_contact_ids)
        contact = sync_manager.contacts.get(eve_entity_id=3015)
        self.assertEqual(contact.standing, -10.0)
        self.assertTrue(contact.is_war_target)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_not_update_contacts_when_unchanged(self, mock_esi):
        # given
        mock_esi.client = self.esi_client_stub
        sync_manager = SyncManagerFactory(user=self.user)
        sync_manager.run_sync()

        # when/then
        self.assertFalse(sync_manager.run_sync())

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_update_contacts_when_unchanged_but_forced(self, mock_esi):
        # given
        mock_esi.client = self.esi_client_stub
        sync_manager = SyncManagerFactory(user=self.user)
        sync_manager.run_sync()

        # when/then
        self.assertTrue(sync_manager.run_sync(force_update=True))

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_add_war_target_contact_as_aggressor_1(self, mock_esi):
        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub([])
        )
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            aggressor=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id)
        )
        # when
        sync_manager.run_sync()
        # then
        self.assertSetEqual(war_target_contact_ids(sync_manager), {war.defender.id})

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_add_war_target_contact_as_aggressor_2(self, mock_esi):
        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub([])
        )
        sync_manager = SyncManagerFactory()
        ally = EveEntityAllianceFactory()
        war = EveWarFactory(
            aggressor=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            allies=[ally],
        )
        # when
        sync_manager.run_sync()
        # then
        self.assertSetEqual(
            war_target_contact_ids(sync_manager), {war.defender.id, ally.id}
        )

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_add_war_target_contact_as_defender(self, mock_esi):
        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub([])
        )
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            defender=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id)
        )
        # when
        sync_manager.run_sync()
        # then
        self.assertSetEqual(war_target_contact_ids(sync_manager), {war.aggressor.id})

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_add_war_target_contact_as_ally(self, mock_esi):
        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub([])
        )
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            allies=[EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id)]
        )
        # when
        sync_manager.run_sync()
        # then
        self.assertSetEqual(war_target_contact_ids(sync_manager), {war.aggressor.id})

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_should_not_add_war_target_contact_from_unrelated_war(self, mock_esi):
        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub([])
        )
        sync_manager = SyncManagerFactory()
        EveWarFactory()
        EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id)
        # when
        sync_manager.run_sync()
        # then
        self.assertSetEqual(war_target_contact_ids(sync_manager), set())

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    def test_remove_outdated_war_target_contacts(self, mock_esi):
        # given
        mock_esi.client.Contacts.get_alliances_alliance_id_contacts.return_value = (
            BravadoOperationStub([])
        )
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            defender=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            finished=now(),
        )
        EveContactWarTargetFactory(manager=sync_manager, eve_entity=war.aggressor)
        # when
        sync_manager.run_sync()
        # then
        self.assertSetEqual(war_target_contact_ids(sync_manager), set())

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_abort_when_no_char(self, mock_esi):
        # given
        sync_manager = SyncManagerFactory(character_ownership=None)
        # when/then
        with self.assertRaises(RuntimeError):
            sync_manager.run_sync()

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_abort_when_insufficient_permission(self, mock_esi):
        # given
        user = UserMainManagerFactory(permissions__=[])
        sync_manager = SyncManagerFactory(user=user)

        # when/then
        with self.assertRaises(RuntimeError):
            sync_manager.run_sync()

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    def test_should_report_error_when_character_has_no_valid_token(self, mock_esi):
        # given
        user = UserMainManagerFactory()
        sync_manager = SyncManagerFactory(user=user)
        user.token_set.all().delete()

        # when/then
        with self.assertRaises(RuntimeError):
            sync_manager.run_sync()


class TestSyncManagerAddWarTargets(NoSocketsTestCase):
    def test_should_add_war_targets(self):
        # given
        sync_manager = SyncManagerFactory()
        alliance_entity = EveEntityAllianceFactory(
            id=sync_manager.alliance.alliance_id,
            name=sync_manager.alliance.alliance_name,
        )
        alliance_contacts = EsiContactsContainer()
        war = EveWarFactory(defender=alliance_entity)
        aggressor = EsiContact.from_eve_entity(war.aggressor, -10)
        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            result = sync_manager._add_war_targets(alliance_contacts)
        # then
        self.assertSetEqual(alliance_contacts.contacts(), {aggressor})
        self.assertSetEqual(result, {aggressor.contact_id})

    def test_should_not_add_war_targets_when_disabled(self):
        # given
        sync_manager = SyncManagerFactory()
        alliance_entity = EveEntityAllianceFactory(
            id=sync_manager.alliance.alliance_id,
            name=sync_manager.alliance.alliance_name,
        )
        alliance_contacts = EsiContactsContainer()
        EveWarFactory(defender=alliance_entity)
        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            result = sync_manager._add_war_targets(alliance_contacts)
        # then
        self.assertSetEqual(alliance_contacts.contacts(), set())
        self.assertSetEqual(result, set())

    def test_should_ignore_unknown_war_targets(self):
        # given
        sync_manager = SyncManagerFactory()
        alliance_entity = EveEntityAllianceFactory(
            id=sync_manager.alliance.alliance_id,
            name=sync_manager.alliance.alliance_name,
        )
        alliance_contacts = EsiContactsContainer()
        ally = EveEntity.objects.create(id=1234567)
        war = EveWarFactory(aggressor=alliance_entity, allies=[ally])
        defender = EsiContact.from_eve_entity(war.defender, -10)
        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            result = sync_manager._add_war_targets(alliance_contacts)
        # then
        self.assertSetEqual(alliance_contacts.contacts(), {defender})
        self.assertSetEqual(result, {defender.contact_id})


class TestSyncManagerEffectiveStanding(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync_manager = SyncManagerFactory()
        contacts = [
            (EveEntityCharacterFactory(id=1001), -10),
            (EveEntityCorporationFactory(id=2001), 10),
            (EveEntityAllianceFactory(id=3001), 5),
        ]
        for contact, standing in contacts:
            EveContactFactory(
                manager=cls.sync_manager, eve_entity=contact, standing=standing
            )

    def test_char_with_character_standing(self):
        c1 = EveCharacter(
            character_id=1001,
            character_name="Char 1",
            corporation_id=201,
            corporation_name="Corporation 1",
            corporation_ticker="C1",
        )
        self.assertEqual(self.sync_manager.effective_standing_with_character(c1), -10)

    def test_char_with_corporation_standing(self):
        c2 = EveCharacter(
            character_id=1002,
            character_name="Char 2",
            corporation_id=2001,
            corporation_name="Corporation 1",
            corporation_ticker="C1",
        )
        self.assertEqual(self.sync_manager.effective_standing_with_character(c2), 10)

    def test_char_with_alliance_standing(self):
        c3 = EveCharacter(
            character_id=1003,
            character_name="Char 3",
            corporation_id=2003,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=3001,
            alliance_name="Alliance 1",
            alliance_ticker="A1",
        )
        self.assertEqual(self.sync_manager.effective_standing_with_character(c3), 5)

    def test_char_without_standing_and_has_alliance(self):
        c4 = EveCharacter(
            character_id=1003,
            character_name="Char 3",
            corporation_id=2003,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=3002,
            alliance_name="Alliance 2",
            alliance_ticker="A2",
        )
        self.assertEqual(self.sync_manager.effective_standing_with_character(c4), 0.0)

    def test_char_without_standing_and_without_alliance_1(self):
        c4 = EveCharacter(
            character_id=1003,
            character_name="Char 3",
            corporation_id=2003,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
            alliance_id=None,
            alliance_name=None,
            alliance_ticker=None,
        )
        self.assertEqual(self.sync_manager.effective_standing_with_character(c4), 0.0)

    def test_char_without_standing_and_without_alliance_2(self):
        c4 = EveCharacter(
            character_id=1003,
            character_name="Char 3",
            corporation_id=2003,
            corporation_name="Corporation 3",
            corporation_ticker="C2",
        )
        self.assertEqual(self.sync_manager.effective_standing_with_character(c4), 0.0)


class TestSyncCharacter(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync_manager = SyncManagerFactory()

    def test_should_return_token(self):
        # given
        obj = SyncedCharacterFactory(manager=self.sync_manager)
        # when
        result = obj.fetch_token()
        # then
        self.assertIsInstance(result, Token)


@patch(MODELS_PATH + ".notify")
class TestSyncCharacterFetchToken(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync_manager = SyncManagerFactory()

    def test_should_return_none_and_delete_when_token_invalid(self, mock_notify):
        # given
        obj = SyncedCharacterFactory(manager=self.sync_manager)
        with patch(MODELS_PATH + ".SyncedCharacter._valid_token") as m:
            m.side_effect = TokenInvalidError
            # when
            result = obj.fetch_token()
        # then
        self.assertIsNone(result)
        self.assertFalse(SyncedCharacter.objects.filter(pk=obj.pk).exists())
        self.assertTrue(mock_notify)

    def test_should_return_none_and_delete_when_token_has_issues(self, mock_notify):
        params = [TokenInvalidError, TokenExpiredError]
        for exception in params:
            with self.subTest(exception=exception):
                # given
                obj = SyncedCharacterFactory(manager=self.sync_manager)
                # when
                with patch(MODELS_PATH + ".SyncedCharacter._valid_token") as m:
                    m.side_effect = exception
                    result = obj.fetch_token()
                # then
                self.assertIsNone(result)
                self.assertFalse(SyncedCharacter.objects.filter(pk=obj.pk).exists())
                self.assertTrue(mock_notify)

    def test_should_return_none_and_delete_when_token_not_found(self, mock_notify):
        # given
        obj = SyncedCharacterFactory(manager=self.sync_manager)
        # when
        with patch(MODELS_PATH + ".SyncedCharacter._valid_token") as m:
            m.return_value = None
            result = obj.fetch_token()
        # then
        self.assertIsNone(result)
        self.assertFalse(SyncedCharacter.objects.filter(pk=obj.pk).exists())
        self.assertTrue(mock_notify)


@patch(ESI_CONTACTS_PATH + ".STANDINGSSYNC_WAR_TARGETS_LABEL_NAME", WAR_TARGET_LABEL)
@patch(ESI_API_PATH + ".esi")
class TestSyncCharacterEsi(NoSocketsTestCase):
    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_replace_contacts_no_wt(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )
        alliance_contact_1 = EveContactFactory(manager=sync_manager)
        alliance_contact_2 = EveContactFactory(manager=sync_manager, standing=10)
        character_contact_1 = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -5
        )
        EveContactFactory(
            manager=sync_manager, standing=-10, is_war_target=True
        )  # alliance_wt_contact
        character_contact_2 = EsiContact.from_eve_contact(alliance_contact_2).clone(
            standing=-5
        )
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[character_contact_1, character_contact_2],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertTrue(result)
        synced_character.refresh_from_db()
        self.assertIsNotNone(synced_character.last_sync_at)
        expected = {
            EsiContact.from_eve_contact(alliance_contact_1),
            EsiContact.from_eve_contact(alliance_contact_2),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0)
    def test_should_replace_contacts_no_wt_no_standing(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=0,
        )
        alliance_contact_1 = EveContactFactory(manager=sync_manager)
        alliance_contact_2 = EveContactFactory(manager=sync_manager, standing=10)
        character_contact_1 = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -5
        )
        EveContactFactory(
            manager=sync_manager, standing=-10, is_war_target=True
        )  # alliance_wt_contact
        character_contact_2 = EsiContact.from_eve_contact(alliance_contact_2).clone(
            standing=-5
        )
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[character_contact_1, character_contact_2],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertTrue(result)
        synced_character.refresh_from_db()
        self.assertIsNotNone(synced_character.last_sync_at)
        expected = {
            EsiContact.from_eve_contact(alliance_contact_1),
            EsiContact.from_eve_contact(alliance_contact_2),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_replace_contacts_incl_wt(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )
        alliance_contact_1 = EveContactFactory(manager=sync_manager)
        alliance_contact_2 = EveContactFactory(manager=sync_manager, standing=10)
        alliance_wt_contact = EveContactFactory(
            manager=sync_manager, standing=-10, is_war_target=True
        )
        character_contact_1 = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -5
        )
        character_contact_2 = EsiContact.from_eve_contact(alliance_contact_2).clone(
            standing=-5
        )
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[character_contact_1, character_contact_2],
            labels=[wt_label],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertTrue(result)
        synced_character.refresh_from_db()
        self.assertIsNotNone(synced_character.last_sync_at)
        expected = {
            EsiContact.from_eve_contact(alliance_contact_1),
            EsiContact.from_eve_contact(alliance_contact_2),
            EsiContact.from_eve_contact(alliance_wt_contact, label_ids=[wt_label.id]),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_not_update_anything(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )
        EveContactFactory(manager=sync_manager)  # alliance_contact_1
        alliance_contact_2 = EveContactFactory(manager=sync_manager, standing=10)
        character_contact_1 = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -5
        )
        EveContactFactory(
            manager=sync_manager, standing=-10, is_war_target=True
        )  # alliance_wt_contact
        character_contact_2 = EsiContact.from_eve_contact(alliance_contact_2).clone(
            standing=-5
        )
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[character_contact_1, character_contact_2],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertTrue(result)
        synced_character.refresh_from_db()
        self.assertIsNotNone(synced_character.last_sync_at)
        expected = {character_contact_1, character_contact_2}
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_sync_war_targets_but_not_alliance_contacts(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        EveContactFactory(manager=sync_manager)  # should not sync this alliance contact
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )  # sync char must have standing with alliance
        alliance_wt_contact_1 = EveContactFactory(
            manager=sync_manager, standing=-10, is_war_target=True
        )  # new war target
        alliance_wt_contact_2 = EveContactFactory(
            manager=sync_manager, standing=-10, is_war_target=True
        )  # new war target
        character_contact_1 = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -5
        )  # character contact must be kept in place
        character_old_wt_contact = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -10, [wt_label.id]
        )  # should remove this old WT contact
        character_contact_2 = EsiContact.from_eve_contact(alliance_wt_contact_2).clone(
            standing=10
        )  # should replace this existing character contact with a WT
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[
                character_contact_1,
                character_old_wt_contact,
                character_contact_2,
            ],
            labels=[wt_label],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertTrue(result)
        synced_character.refresh_from_db()
        self.assertIsNotNone(synced_character.last_sync_at)
        expected = {
            character_contact_1,
            EsiContact.from_eve_contact(alliance_wt_contact_1, label_ids=[wt_label.id]),
            EsiContact.from_eve_contact(alliance_wt_contact_2, label_ids=[wt_label.id]),
        }
        self.assertSetEqual(esi_character_contacts.contacts(), expected)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_add_wt_label_info(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )
        EveContactFactory(manager=sync_manager)  # alliance_contact
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        EsiCharacterContactsStub.create(
            synced_character.character_id, mock_esi, labels=[wt_label]
        )
        # when
        synced_character.run_sync()
        # then
        synced_character.refresh_from_db()
        self.assertTrue(synced_character.has_war_targets_label)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_remove_wt_label_info(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory(has_war_targets_label=True)
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )
        EveContactFactory(manager=sync_manager)  # alliance_contact
        other_label = EsiContactLabelFactory()
        EsiCharacterContactsStub.create(
            synced_character.character_id, mock_esi, labels=[other_label]
        )
        # when
        synced_character.run_sync()
        # then
        synced_character.refresh_from_db()
        self.assertFalse(synced_character.has_war_targets_label)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_not_sync_when_no_contacts(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        sync_manager = synced_character.manager
        EveContactFactory(
            manager=sync_manager,
            eve_entity=EveEntityCharacterFactory(id=synced_character.character_id),
            standing=10,
        )
        character_contact_1 = EsiContact.from_eve_entity(
            EveEntityCharacterFactory(), -5
        )
        EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[character_contact_1],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertIsNone(result)

    def test_should_delete_contacts(self, mock_esi):
        # given
        synced_character = SyncedCharacterFactory()
        character_contact_1 = EsiContactFactory()
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi,
            contacts=[character_contact_1],
        )
        # when
        synced_character.delete_all_contacts()
        # then
        self.assertSetEqual(esi_character_contacts.contacts(), set())

    def test_should_do_nothing_when_no_token(self, mock_esi):
        # given
        obj = SyncedCharacterFactory()
        obj.character_ownership.user.token_set.all().delete()
        with patch(MODELS_PATH + ".esi_api.delete_character_contacts") as esi_api:
            # when
            obj.delete_all_contacts()
            # then
            self.assertFalse(esi_api.called)


@patch(MODELS_PATH + ".notify")
class TestSyncCharacterErrorCases(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync_manager = SyncManagerFactory()

    def test_should_delete_when_insufficient_permission(self, mock_notify):
        # given
        user = UserMainSyncerFactory(permissions__=[])
        sync_character = SyncedCharacterFactory(user=user, manager=self.sync_manager)

        # when
        result = sync_character.run_sync()

        # then
        self.assertFalse(result)
        self.assertFalse(SyncedCharacter.objects.filter(pk=sync_character.pk).exists())

    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1)
    def test_should_delete_when_character_has_no_standing(self, mock_notify):
        # given
        user = UserMainSyncerFactory()
        character = user.profile.main_character
        sync_character = SyncedCharacterFactory(manager=self.sync_manager, user=user)
        EveContactFactory(
            manager=self.sync_manager,
            eve_entity=EveEntityCharacterFactory(id=character.character_id),
            standing=-10,
        )

        # when
        result = sync_character.run_sync()

        # then
        self.assertFalse(result)
        self.assertFalse(SyncedCharacter.objects.filter(pk=sync_character.pk).exists())


class TestSyncCharacter2(NoSocketsTestCase):
    def test_should_report_sync_as_ok(self):
        # given
        my_dt = now()
        obj = SyncedCharacterFactory(last_sync_at=my_dt - dt.timedelta(minutes=1))
        # when/then
        with patch(MODELS_PATH + ".STANDINGSSYNC_SYNC_TIMEOUT", 60):
            self.assertTrue(obj.is_sync_fresh)

    def test_should_report_sync_as_not_ok(self):
        # given
        my_dt = now()
        obj = SyncedCharacterFactory(last_sync_at=my_dt - dt.timedelta(minutes=61))
        # when/then
        with patch(MODELS_PATH + ".STANDINGSSYNC_SYNC_TIMEOUT", 60):
            self.assertFalse(obj.is_sync_fresh)

    def test_should_update_wt_label_info(self):
        # given
        synced_character = SyncedCharacterFactory()
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        character_contacts = EsiContactsContainer.from_esi_contacts(labels=[wt_label])
        # when
        synced_character._update_wt_label_info(character_contacts)
        # then
        synced_character.refresh_from_db()
        self.assertTrue(synced_character.has_war_targets_label)

    def test_should_not_update_wt_label_info(self):
        # given
        synced_character = SyncedCharacterFactory(has_war_targets_label=True)
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        character_contacts = EsiContactsContainer.from_esi_contacts(labels=[wt_label])
        # when
        synced_character._update_wt_label_info(character_contacts)
        # then
        synced_character.refresh_from_db()
        self.assertTrue(synced_character.has_war_targets_label)


class TestEveWar(NoSocketsTestCase):
    def test_str(self):
        # given
        aggressor = EveEntityAllianceFactory(name="Alpha")
        defender = EveEntityAllianceFactory(name="Bravo")
        war = EveWarFactory(aggressor=aggressor, defender=defender)
        # when/then
        self.assertEqual(str(war), "Alpha vs. Bravo")


class TestEveContact(NoSocketsTestCase):
    def test_str(self):
        # given
        contact = EveContactFactory(eve_entity__name="Alpha")
        # when/then
        self.assertEqual(str(contact), "Alpha")
