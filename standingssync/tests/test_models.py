import datetime as dt
from http import HTTPStatus
from typing import Set
from unittest.mock import patch

import pook

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
from app_utils.testdata_factories import EveCharacterFactory, UserMainFactory
from app_utils.testing import NoSocketsTestCase

from standingssync.core.esi_contacts import EsiContact, EsiContactsContainer
from standingssync.models import (
    EveContact,
    SyncedCharacter,
    SyncManager,
    _get_or_create_eve_entity_from_participant,
)
from standingssync.tests.factories import (
    EsiContactCharacterFactory,
    EsiContactLabelFactory,
    EveContactFactory,
    EveWarEmptyFactory,
    EveWarFactory,
    SyncedCharacterFactory,
    SyncManagerFactory,
    UserMainManagerFactory,
    UserMainSyncerFactory,
    make_esi_url,
)
from standingssync.tests.helpers import (
    EsiCharacterContactsStub,
    TestCaseWithClearCache,
    extract,
)

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


@patch(MODELS_PATH + ".esi_api")
class TestSyncManager_RunSync(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserMainManagerFactory()
        cls.my_alliance_id = cls.user.profile.main_character.alliance_id

    def test_should_add_new_contacts_from_scratch_no_wt(self, mock_esi_api):
        # given
        contact_esi = EsiContactCharacterFactory()
        mock_esi_api.fetch_alliance_contacts.return_value = [contact_esi]
        EveEntityCharacterFactory(id=contact_esi.contact_id)
        sm = SyncManagerFactory(user=self.user)

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            sm.run_sync()

        # then
        self.assertEqual(sm.contacts.count(), 1)
        contact: EveContact = sm.contacts.first()
        self.assertEqual(contact.eve_entity.id, contact_esi.contact_id)
        self.assertEqual(contact.standing, contact_esi.standing)
        self.assertFalse(contact.is_war_target)

    def test_should_update_existing_contacts_no_wt(self, mock_esi_api):
        # given
        sm = SyncManagerFactory(user=self.user)
        contact = EveContactFactory(manager=sm, standing=-5)
        contact_esi: EsiContact = EsiContact.from_eve_entity(contact.eve_entity, 10.0)
        mock_esi_api.fetch_alliance_contacts.return_value = [contact_esi]

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            sm.run_sync()

        # then
        sm.refresh_from_db()
        self.assertEqual(sm.contacts.count(), 1)
        contact: EveContact = sm.contacts.first()
        self.assertEqual(contact.standing, 10.0)

    def test_should_not_update_contacts_when_unchanged(self, mock_esi_api):
        # given
        contact_esi = EsiContactCharacterFactory()
        mock_esi_api.fetch_alliance_contacts.return_value = [contact_esi]
        EveEntityCharacterFactory(id=contact_esi.contact_id)
        sm = SyncManagerFactory(user=self.user)

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            sm.run_sync()
            got = sm.run_sync()

        # then
        self.assertFalse(got)

    def test_should_update_contacts_when_unchanged_but_forced(self, mock_esi_api):
        # given
        contact_esi = EsiContactCharacterFactory()
        mock_esi_api.fetch_alliance_contacts.return_value = [contact_esi]
        EveEntityCharacterFactory(id=contact_esi.contact_id)
        sm = SyncManagerFactory(user=self.user)

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            sm.run_sync()
            got = sm.run_sync(force_update=True)

        # then
        self.assertTrue(got)

    def test_should_remove_obsolete_contacts_no_wt(self, mock_esi_api):
        # given
        sm = SyncManagerFactory(user=self.user)
        EveContactFactory(manager=sm)  # to be removed
        remaining_contact = EveContactFactory(manager=sm)
        contact = EsiContact.from_eve_contact(remaining_contact)
        mock_esi_api.fetch_alliance_contacts.return_value = [contact]

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            sm.run_sync()

        # then
        got = extract(sm.contacts, "eve_entity_id")
        want = {remaining_contact.contact_id}
        self.assertSetEqual(got, want)

    def test_should_add_new_contacts_from_scratch_with_wt(self, mock_esi_api):
        # given
        contact_esi = EsiContactCharacterFactory()
        mock_esi_api.fetch_alliance_contacts.return_value = [contact_esi]
        EveEntityCharacterFactory(id=contact_esi.contact_id)
        sm = SyncManagerFactory(user=self.user)
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory(id=self.my_alliance_id)
        EveWarFactory(aggressor=aggressor, defender=defender)
        EveWarFactory()  # should be ignored

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            sm.run_sync()

        # then
        got = extract(sm.contacts, "eve_entity_id")
        want = {aggressor.id, contact_esi.contact_id}
        self.assertSetEqual(got, want)
        contact: EveContact = sm.contacts.get(eve_entity_id=aggressor.id)
        self.assertEqual(contact.standing, -10.0)
        self.assertTrue(contact.is_war_target)

    def test_should_add_war_target_contacts_as_aggressor(self, mock_esi_api):
        # given
        mock_esi_api.fetch_alliance_contacts.return_value = []
        sm = SyncManagerFactory(user=self.user)
        aggressor = EveEntityAllianceFactory(id=self.my_alliance_id)
        defender = EveEntityAllianceFactory()
        ally = EveEntityAllianceFactory()
        EveWarFactory(aggressor=aggressor, defender=defender, allies=[ally])
        EveWarFactory()  # should be ignored

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            sm.run_sync()

        # then
        got = extract(sm.contacts, "eve_entity_id")
        want = {defender.id, ally.id}
        self.assertSetEqual(got, want)

        contact_1: EveContact = sm.contacts.get(eve_entity_id=defender.id)
        self.assertEqual(contact_1.standing, -10.0)
        self.assertTrue(contact_1.is_war_target)

        contact_2: EveContact = sm.contacts.get(eve_entity_id=ally.id)
        self.assertEqual(contact_2.standing, -10.0)
        self.assertTrue(contact_2.is_war_target)

    def test_should_add_war_target_contact_as_defender(self, mock_esi_api):
        # given
        mock_esi_api.fetch_alliance_contacts.return_value = []
        sm = SyncManagerFactory(user=self.user)
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory(id=self.my_alliance_id)
        EveWarFactory(aggressor=aggressor, defender=defender)
        EveWarFactory()  # should be ignored

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            sm.run_sync()

        # then
        got = extract(sm.contacts, "eve_entity_id")
        want = {aggressor.id}
        self.assertSetEqual(got, want)
        contact: EveContact = sm.contacts.get(eve_entity_id=aggressor.id)
        self.assertEqual(contact.standing, -10.0)
        self.assertTrue(contact.is_war_target)

    def test_should_add_war_target_contact_as_ally(self, mock_esi_api):
        # given
        mock_esi_api.fetch_alliance_contacts.return_value = []
        sm = SyncManagerFactory(user=self.user)
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory()
        ally = EveEntityAllianceFactory(id=self.my_alliance_id)
        EveWarFactory(aggressor=aggressor, defender=defender, allies=[ally])
        EveWarFactory()  # should be ignored

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            sm.run_sync()

        # then
        got = extract(sm.contacts, "eve_entity_id")
        want = {aggressor.id}
        self.assertSetEqual(got, want)
        contact: EveContact = sm.contacts.get(eve_entity_id=aggressor.id)
        self.assertEqual(contact.standing, -10.0)
        self.assertTrue(contact.is_war_target)

    def test_remove_outdated_war_target_contacts(self, mock_esi_api):
        # given
        mock_esi_api.fetch_alliance_contacts.return_value = []
        sm = SyncManagerFactory(user=self.user)
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory(id=self.my_alliance_id)
        EveWarFactory(
            aggressor=aggressor,
            defender=defender,
            finished=now(),
        )
        EveContactFactory(manager=sm, eve_entity=aggressor, is_war_target=True)
        EveWarFactory()  # should be ignored

        # when
        with patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            sm.run_sync()

        # then
        got = extract(sm.contacts, "eve_entity_id")
        want = set()
        self.assertSetEqual(got, want)
        self.assertFalse(sm.contacts.filter(eve_entity_id=aggressor.id).exists())

    def test_should_abort_when_no_char(self, mock_esi_api):
        # given
        sync_manager = SyncManagerFactory(character_ownership=None)
        # when/then
        with self.assertRaises(RuntimeError):
            sync_manager.run_sync()

    def test_should_abort_when_insufficient_permission(self, mock_esi_api):
        # given
        sync_manager = SyncManagerFactory(user=UserMainSyncerFactory())

        # when/then
        with self.assertRaises(RuntimeError):
            sync_manager.run_sync()

    def test_should_report_error_when_character_has_no_valid_token(self, mock_esi_api):
        # given
        user = UserMainManagerFactory()
        sync_manager = SyncManagerFactory(user=user)
        user.token_set.all().delete()

        # when/then
        with self.assertRaises(RuntimeError):
            sync_manager.run_sync()


class TestSyncManager_AddWarTargets(NoSocketsTestCase):
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


class TestSyncManager_EffectiveStandingWithCharacter(NoSocketsTestCase):
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


@patch(MODELS_PATH + ".notify")
class TestSyncCharacter_FetchToken(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync_manager = SyncManagerFactory()

    def test_should_return_token(self, mock_notify):
        # given
        sc = SyncedCharacterFactory(manager=self.sync_manager)

        # when
        result = sc.fetch_token()

        # then
        self.assertIsInstance(result, Token)
        self.assertFalse(mock_notify.called)

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
        self.assertTrue(mock_notify.called)

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
                self.assertTrue(mock_notify.called)

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
        self.assertTrue(mock_notify.called)


@patch(ESI_CONTACTS_PATH + ".STANDINGSSYNC_WAR_TARGETS_LABEL_NAME", WAR_TARGET_LABEL)
@patch(MODELS_PATH + ".notify")
@patch(MODELS_PATH + ".esi_api")
class TestSyncCharacter_RunSync(NoSocketsTestCase):
    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_replace_contacts_no_wt(self, mock_esi_api, mock_notify):
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
            mock_esi_api,
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
    def test_should_replace_contacts_no_wt_no_standing(self, mock_esi_api, mock_notify):
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
            mock_esi_api,
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
    def test_should_replace_contacts_incl_wt(self, mock_esi_api, mock_notify):
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
            mock_esi_api,
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
    def test_should_not_update_anything(self, mock_esi_api, mock_notify):
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
            mock_esi_api,
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
    def test_should_sync_war_targets_but_not_alliance_contacts(
        self, mock_esi_api, mock_notify
    ):
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
            mock_esi_api,
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
    def test_should_add_wt_label_info(self, mock_esi_api, mock_notify):
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
            synced_character.character_id, mock_esi_api, labels=[wt_label]
        )
        # when
        synced_character.run_sync()
        # then
        synced_character.refresh_from_db()
        self.assertTrue(synced_character.has_war_targets_label)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_remove_wt_label_info(self, mock_esi_api, mock_notify):
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
            synced_character.character_id, mock_esi_api, labels=[other_label]
        )
        # when
        synced_character.run_sync()
        # then
        synced_character.refresh_from_db()
        self.assertFalse(synced_character.has_war_targets_label)

    @patch(MODELS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False)
    @patch(MODELS_PATH + ".STANDINGSSYNC_REPLACE_CONTACTS", True)
    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.01)
    def test_should_not_sync_when_no_contacts(self, mock_esi_api, mock_notify):
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
            mock_esi_api,
            contacts=[character_contact_1],
        )
        # when
        result = synced_character.run_sync()
        # then
        self.assertIsNone(result)

    def test_should_delete_contacts(self, mock_esi_api, mock_notify):
        # given
        synced_character = SyncedCharacterFactory()
        character_contact_1 = EsiContactCharacterFactory()
        esi_character_contacts = EsiCharacterContactsStub.create(
            synced_character.character_id,
            mock_esi_api,
            contacts=[character_contact_1],
        )
        # when
        synced_character.delete_all_contacts()
        # then
        self.assertSetEqual(esi_character_contacts.contacts(), set())

    def test_should_do_nothing_when_no_token(self, mock_esi_api, mock_notify):
        # given
        obj = SyncedCharacterFactory()
        obj.character_ownership.user.token_set.all().delete()
        with patch(MODELS_PATH + ".esi_api.delete_character_contacts") as esi_api:
            # when
            obj.delete_all_contacts()
            # then
            self.assertFalse(esi_api.called)

    def test_should_delete_when_insufficient_permission(
        self, mock_esi_api, mock_notify
    ):
        # given
        sm = SyncManagerFactory()
        character = EveCharacterFactory(corporation__alliance=sm.alliance)
        user = UserMainFactory(main_character__character=character)
        sc = SyncedCharacterFactory(manager=sm, user=user)
        # when
        result = sc.run_sync()

        # then
        self.assertFalse(result)
        self.assertFalse(SyncedCharacter.objects.filter(pk=sc.pk).exists())
        self.assertTrue(mock_notify.called)

    @patch(MODELS_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1)
    def test_should_delete_when_character_has_no_standing(
        self, mock_esi_api, mock_notify
    ):
        # given
        sm = SyncManagerFactory()
        sc = SyncedCharacterFactory(manager=sm)
        EveContactFactory(
            manager=sm,
            eve_entity=EveEntityCharacterFactory(id=sc.character_id),
            standing=-10,
        )

        # when
        result = sc.run_sync()

        # then
        self.assertFalse(result)
        self.assertFalse(SyncedCharacter.objects.filter(pk=sc.pk).exists())
        self.assertTrue(mock_notify.called)


class TestSyncCharacter_IsSyncFresh(NoSocketsTestCase):
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


class TestSyncCharacter_UpdateWtLabelInfo(NoSocketsTestCase):
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


class TestEveContact(NoSocketsTestCase):
    def test_str(self):
        # given
        contact = EveContactFactory(eve_entity__name="Alpha")
        # when/then
        self.assertEqual(str(contact), "Alpha")


class TestEveWar(NoSocketsTestCase):
    def test_str(self):
        # given
        aggressor = EveEntityAllianceFactory(name="Alpha")
        defender = EveEntityAllianceFactory(name="Bravo")
        war = EveWarFactory(aggressor=aggressor, defender=defender)
        # when/then
        self.assertEqual(str(war), "Alpha vs. Bravo")


class TestEveWar_UpdateFromESI(TestCaseWithClearCache):
    @pook.on
    def test_should_update_full_war_from_esi(self):
        # given
        war = EveWarEmptyFactory()
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        finished = now() + dt.timedelta(days=1)
        retracted = now()
        aggressor = EveEntityAllianceFactory()
        ally_1 = EveEntityAllianceFactory()
        ally_2 = EveEntityCorporationFactory()
        defender = EveEntityAllianceFactory()
        pook.get(
            make_esi_url(f"wars/{war.id}"),
            reply=HTTPStatus.OK,
            response_json={
                "aggressor": {
                    "alliance_id": aggressor.id,
                    "isk_destroyed": 0,
                    "ships_killed": 0,
                },
                "allies": [{"alliance_id": ally_1.id}, {"corporation_id": ally_2.id}],
                "declared": declared.isoformat(),
                "defender": {
                    "alliance_id": defender.id,
                    "isk_destroyed": 0,
                    "ships_killed": 0,
                },
                "finished": finished.isoformat(),
                "id": war.id,
                "mutual": False,
                "open_for_allies": True,
                "retracted": retracted.isoformat(),
                "started": started.isoformat(),
            },
        )

        # when
        war.update_from_esi()

        # then
        war.refresh_from_db()
        self.assertEqual(war.aggressor, aggressor)
        self.assertCountEqual(war.allies.all(), [ally_1, ally_2])
        self.assertEqual(war.declared, declared)
        self.assertEqual(war.defender, defender)
        self.assertEqual(war.finished, finished)
        self.assertFalse(war.is_mutual)
        self.assertTrue(war.is_open_for_allies)
        self.assertEqual(war.retracted, retracted)
        self.assertEqual(war.started, started)

    @pook.on
    def test_should_update_minimal_warfrom_esi(self):
        # given
        war = EveWarEmptyFactory()
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory()
        pook.get(
            make_esi_url(f"wars/{war.id}"),
            reply=HTTPStatus.OK,
            response_json={
                "aggressor": {
                    "alliance_id": aggressor.id,
                    "isk_destroyed": 0,
                    "ships_killed": 0,
                },
                "declared": declared.isoformat(),
                "defender": {
                    "alliance_id": defender.id,
                    "isk_destroyed": 0,
                    "ships_killed": 0,
                },
                "id": war.id,
                "mutual": False,
                "open_for_allies": True,
                "started": started.isoformat(),
            },
        )

        # when
        war.update_from_esi()

        # then
        war.refresh_from_db()
        self.assertEqual(war.aggressor, aggressor)
        self.assertEqual(war.allies.count(), 0)
        self.assertEqual(war.declared, declared)
        self.assertEqual(war.defender, defender)
        self.assertIsNone(war.finished)
        self.assertFalse(war.is_mutual)
        self.assertTrue(war.is_open_for_allies)
        self.assertIsNone(war.retracted)
        self.assertEqual(war.started, started)

    @pook.on
    def test_should_update_existing_war_from_esi(self):
        # given
        war = EveWarFactory()
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        finished = now() + dt.timedelta(days=1)
        retracted = now()
        aggressor = EveEntityAllianceFactory()
        ally_1 = EveEntityAllianceFactory()
        ally_2 = EveEntityCorporationFactory()
        defender = EveEntityAllianceFactory()
        pook.get(
            make_esi_url(f"wars/{war.id}"),
            reply=HTTPStatus.OK,
            response_json={
                "aggressor": {
                    "alliance_id": aggressor.id,
                    "isk_destroyed": 0,
                    "ships_killed": 0,
                },
                "allies": [{"alliance_id": ally_1.id}, {"corporation_id": ally_2.id}],
                "declared": declared.isoformat(),
                "defender": {
                    "alliance_id": defender.id,
                    "isk_destroyed": 0,
                    "ships_killed": 0,
                },
                "finished": finished.isoformat(),
                "id": war.id,
                "mutual": False,
                "open_for_allies": True,
                "retracted": retracted.isoformat(),
                "started": started.isoformat(),
            },
        )

        # when
        war.update_from_esi()

        # then
        war.refresh_from_db()
        self.assertEqual(war.aggressor, aggressor)
        self.assertCountEqual(war.allies.all(), [ally_1, ally_2])
        self.assertEqual(war.declared, declared)
        self.assertEqual(war.defender, defender)
        self.assertEqual(war.finished, finished)
        self.assertFalse(war.is_mutual)
        self.assertTrue(war.is_open_for_allies)
        self.assertEqual(war.retracted, retracted)
        self.assertEqual(war.started, started)


class TestEveWarManager__GetOrCreateEveEntityFromParticipant(NoSocketsTestCase):
    def test_should_create_from_alliance_id(self):
        # given
        alliance = EveEntityAllianceFactory()
        data = {"alliance_id": alliance.id}
        # when
        result = _get_or_create_eve_entity_from_participant(data)
        # then
        self.assertEqual(result, alliance)

    def test_should_create_from_corporation_id(self):
        # given
        corporation = EveEntityCorporationFactory()
        data = {"corporation_id": corporation.id}
        # when
        result = _get_or_create_eve_entity_from_participant(data)
        # then
        self.assertEqual(result, corporation)

    def test_should_raise_error_when_no_id_found(self):
        # given
        data = {}
        # when/then
        with self.assertRaises(ValueError):
            _get_or_create_eve_entity_from_participant(data)
