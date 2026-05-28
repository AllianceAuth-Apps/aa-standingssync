import datetime as dt
from http import HTTPStatus
from unittest.mock import patch

import pook

from django.utils.timezone import now
from eveuniverse.models import EveEntity
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCorporationFactory,
)

from app_utils.testdata_factories import EveAllianceInfoFactory, UserFactory
from app_utils.testing import NoSocketsTestCase

from standingssync.models import EveWar, SyncManager

from .factories import (
    EveContactFactory,
    EveWarFactory,
    SyncManagerFactory,
    UserMainSyncerFactory,
    make_esi_url,
)
from .helpers import TestCaseWithClearCache

MANAGERS_PATH = "standingssync.managers"


class TestEveContactManager(NoSocketsTestCase):
    def test_grouped_by_standing(self):
        # given
        sync_manager = SyncManagerFactory()

        contact_terrible = EveContactFactory(
            manager=sync_manager,
            standing=-10.0,
        )
        contact_bad = EveContactFactory(
            manager=sync_manager,
            standing=-5.0,
        )
        contact_neutral = EveContactFactory(
            manager=sync_manager,
            standing=0.0,
        )
        contact_good = EveContactFactory(
            manager=sync_manager,
            standing=5.0,
        )
        contact_excellent = EveContactFactory(
            manager=sync_manager,
            standing=10.0,
        )

        expected = {
            -10.0: {contact_terrible},
            -5.0: {contact_bad},
            0.0: {contact_neutral},
            5.0: {contact_good},
            10.0: {contact_excellent},
        }

        # when
        result = sync_manager.contacts.grouped_by_standing()

        # then
        self.maxDiff = None
        self.assertDictEqual(result, expected)
        self.assertListEqual(list(result.keys()), list(expected.keys()))


class TestEveWarManagerWarTargets(NoSocketsTestCase):
    def test_should_return_defender_and_allies_for_aggressor(self):
        # given
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory()
        ally_1 = EveEntityAllianceFactory()
        ally_2 = EveEntityAllianceFactory()
        EveWarFactory(aggressor=aggressor, defender=defender, allies=[ally_1, ally_2])
        alliance = EveAllianceInfoFactory(alliance_id=aggressor.id)
        # when
        result = EveWar.objects.alliance_war_targets(alliance)
        # then
        self.assertSetEqual(
            {obj.id for obj in result}, {defender.id, ally_1.id, ally_2.id}
        )

    def test_should_return_aggressor_for_defender(self):
        # given
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory()
        ally = EveEntityAllianceFactory()
        EveWarFactory(aggressor=aggressor, defender=defender, allies=[ally])
        alliance = EveAllianceInfoFactory(alliance_id=defender.id)
        # when
        result = EveWar.objects.alliance_war_targets(alliance)
        # then
        self.assertSetEqual({obj.id for obj in result}, {aggressor.id})

    def test_should_return_aggressor_for_ally(self):
        # given
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory()
        ally = EveEntityAllianceFactory()
        EveWarFactory(aggressor=aggressor, defender=defender, allies=[ally])
        alliance = EveAllianceInfoFactory(alliance_id=ally.id)
        # when
        result = EveWar.objects.alliance_war_targets(alliance)
        # then
        self.assertSetEqual({obj.id for obj in result}, {aggressor.id})


class TestEveWarManager(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        EveEntityCorporationFactory(id=2003)
        EveEntityAllianceFactory(id=3001)
        EveEntityAllianceFactory(id=3002)
        EveEntityAllianceFactory(id=3003)
        EveEntityAllianceFactory(id=3011)
        EveEntityAllianceFactory(id=3012)

        cls.war_declared = now() - dt.timedelta(days=3)
        cls.war_started = now() - dt.timedelta(days=2)
        EveWarFactory(
            id=8,
            aggressor=EveEntity.objects.get(id=3011),
            defender=EveEntity.objects.get(id=3001),
            declared=cls.war_declared,
            started=cls.war_started,
            allies=[EveEntity.objects.get(id=3012)],
        )

    def test_should_return_finished_wars(self):
        # given
        EveWarFactory(
            id=2,  # finished in the past
            aggressor=EveEntity.objects.get(id=3011),
            defender=EveEntity.objects.get(id=3001),
            declared=now() - dt.timedelta(days=5),
            started=now() - dt.timedelta(days=4),
            finished=now() - dt.timedelta(days=2),
        )
        EveWarFactory(
            id=3,  # about to finish
            aggressor=EveEntity.objects.get(id=3011),
            defender=EveEntity.objects.get(id=3001),
            declared=now() - dt.timedelta(days=5),
            started=now() - dt.timedelta(days=4),
            finished=now() + dt.timedelta(days=1),
        )
        EveWarFactory(
            id=4,  # not yet started
            aggressor=EveEntity.objects.get(id=3011),
            defender=EveEntity.objects.get(id=3001),
            declared=now() - dt.timedelta(days=1),
            started=now() + dt.timedelta(days=1),
        )
        # when
        result = EveWar.objects.finished_wars()
        # then
        self.assertSetEqual({obj.id for obj in result}, {2})


class TestEveWarManager_UpdateOrCreateFromEsi(TestCaseWithClearCache):
    @pook.on
    def test_should_create_full_war_object_from_esi(self):
        # given
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        finished = now() + dt.timedelta(days=1)
        retracted = now()
        war_id = 42
        aggressor = EveEntityAllianceFactory()
        ally_1 = EveEntityAllianceFactory()
        ally_2 = EveEntityCorporationFactory()
        defender = EveEntityAllianceFactory()
        pook.get(
            make_esi_url(f"wars/{war_id}"),
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
                "id": war_id,
                "mutual": False,
                "open_for_allies": True,
                "retracted": retracted.isoformat(),
                "started": started.isoformat(),
            },
        )

        # when
        war: EveWar
        war, created = EveWar.objects.update_or_create_from_esi(id=war_id)

        # then
        self.assertTrue(created)
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
    def test_should_create_minimal_war_object_from_esi(self):
        # given
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        war_id = 42
        aggressor = EveEntityAllianceFactory()
        defender = EveEntityAllianceFactory()
        pook.get(
            make_esi_url(f"wars/{war_id}"),
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
                "id": war_id,
                "mutual": False,
                "open_for_allies": True,
                "started": started.isoformat(),
            },
        )

        # when
        war: EveWar
        war, created = EveWar.objects.update_or_create_from_esi(id=war_id)

        # then
        self.assertTrue(created)
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
        declared = now() - dt.timedelta(days=5)
        started = now() - dt.timedelta(days=4)
        finished = now() + dt.timedelta(days=1)
        retracted = now()
        war_id = 42
        aggressor = EveEntityAllianceFactory()
        ally_1 = EveEntityAllianceFactory()
        ally_2 = EveEntityCorporationFactory()
        defender = EveEntityAllianceFactory()
        war_1 = EveWarFactory(id=war_id)
        pook.get(
            make_esi_url(f"wars/{war_id}"),
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
                "id": war_id,
                "mutual": False,
                "open_for_allies": True,
                "retracted": retracted.isoformat(),
                "started": started.isoformat(),
            },
        )

        # when
        war_2: EveWar
        war_2, created = EveWar.objects.update_or_create_from_esi(id=war_id)

        # then
        self.assertFalse(created)
        war_1.refresh_from_db()
        self.assertEqual(war_1.aggressor, aggressor)
        self.assertCountEqual(war_1.allies.all(), [ally_1, ally_2])
        self.assertEqual(war_1.declared, declared)
        self.assertEqual(war_1.defender, defender)
        self.assertEqual(war_1.finished, finished)
        self.assertFalse(war_1.is_mutual)
        self.assertTrue(war_1.is_open_for_allies)
        self.assertEqual(war_1.retracted, retracted)
        self.assertEqual(war_1.started, started)
        self.assertEqual(war_1, war_2)


class TestEveWarQueryset(NoSocketsTestCase):
    def test_should_return_wars_of_alliance_only(self):
        # given
        alliance_entity = EveEntityAllianceFactory()
        alliance = EveAllianceInfoFactory(alliance_id=alliance_entity.id)
        other_1 = EveEntityAllianceFactory()
        other_2 = EveEntityAllianceFactory()
        war_1 = EveWarFactory(aggressor=alliance_entity, defender=other_1)
        war_2 = EveWarFactory(aggressor=other_1, defender=alliance_entity)
        war_3 = EveWarFactory(
            aggressor=other_1, defender=other_2, allies=[alliance_entity]
        )
        EveWarFactory(aggressor=other_1, defender=other_2)
        # when
        qs = EveWar.objects.alliance_wars(alliance)
        # then
        expected = {war_1.id, war_2.id, war_3.id}
        result = set(qs.values_list("id", flat=True))
        self.assertSetEqual(expected, result)


class TestEveWarManager_FetchActiveWarIdsEsi(NoSocketsTestCase):
    @patch(MANAGERS_PATH + ".esi_api.fetch_war_ids")
    def test_should_return_unfinished_war_ids(self, mock_fetch_war_ids_from_esi):
        # given
        mock_fetch_war_ids_from_esi.return_value = {1, 2, 42}
        EveWarFactory(id=42, finished=now() - dt.timedelta(days=1))
        # when
        result = EveWar.objects.fetch_active_war_ids_esi()
        # then
        self.assertSetEqual(result, {1, 2})


class TestEveWarManager__GetOrCreateEveEntityFromParticipant(NoSocketsTestCase):
    def test_should_create_from_alliance_id(self):
        # given
        alliance = EveEntityAllianceFactory()
        data = {"alliance_id": alliance.id}
        # when
        result = EveWar.objects._get_or_create_eve_entity_from_participant(data)
        # then
        self.assertEqual(result, alliance)

    def test_should_create_from_corporation_id(self):
        # given
        corporation = EveEntityCorporationFactory()
        data = {"corporation_id": corporation.id}
        # when
        result = EveWar.objects._get_or_create_eve_entity_from_participant(data)
        # then
        self.assertEqual(result, corporation)

    def test_should_raise_error_when_no_id_found(self):
        # given
        data = {}
        # when/then
        with self.assertRaises(ValueError):
            EveWar.objects._get_or_create_eve_entity_from_participant(data)


class TestEveWarManager_Annotations(NoSocketsTestCase):
    def test_should_annotate_state(self):
        # given
        war_pending = EveWarFactory(declared=now())
        war_ongoing = EveWarFactory(declared=now() - dt.timedelta(hours=24))
        war_concluding = EveWarFactory(finished=now() + dt.timedelta(hours=24))
        war_retracted = EveWarFactory(retracted=now())
        war_finished = EveWarFactory(finished=now() - dt.timedelta(hours=1))
        # when
        qs = EveWar.objects.annotate_state()
        # then
        self.assertEqual(qs.get(id=war_pending.id).state, EveWar.State.PENDING.value)
        self.assertEqual(qs.get(id=war_ongoing.id).state, EveWar.State.ONGOING.value)
        self.assertEqual(
            qs.get(id=war_concluding.id).state, EveWar.State.CONCLUDING.value
        )
        self.assertEqual(
            qs.get(id=war_retracted.id).state, EveWar.State.RETRACTED.value
        )
        self.assertEqual(qs.get(id=war_finished.id).state, EveWar.State.FINISHED.value)

    def test_should_annotate_is_active(self):
        # given
        war_pending = EveWarFactory(declared=now())
        war_ongoing = EveWarFactory(declared=now() - dt.timedelta(hours=24))
        war_concluding = EveWarFactory(finished=now() + dt.timedelta(hours=24))
        war_retracted = EveWarFactory(retracted=now())
        war_finished = EveWarFactory(finished=now() - dt.timedelta(hours=1))
        # when
        qs = EveWar.objects.annotate_state().annotate_is_active()
        # then
        self.assertFalse(qs.get(id=war_pending.id).is_active)
        self.assertTrue(qs.get(id=war_ongoing.id).is_active)
        self.assertTrue(qs.get(id=war_concluding.id).is_active)
        self.assertTrue(qs.get(id=war_retracted.id).is_active)
        self.assertFalse(qs.get(id=war_finished.id).is_active)


class TestEveWarManager_CurrentWars(NoSocketsTestCase):
    def test_should_return_recently_declared_war(self):
        # given
        war = EveWarFactory(declared=now())
        # when
        result = EveWar.objects.current_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)

    def test_should_return_recently_finished_war(self):
        # given
        war = EveWarFactory(finished=now() - dt.timedelta(hours=23))
        # when
        result = EveWar.objects.current_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)

    def test_should_return_active_war(self):
        # given
        war = EveWarFactory(declared=now() - dt.timedelta(days=2))
        # when
        result = EveWar.objects.current_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)


class TestEveWarManager_ActiveWars(NoSocketsTestCase):
    def test_should_return_started_war_as_defender(self):
        # given
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            defender=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            declared=now() - dt.timedelta(days=2),
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)

    def test_should_return_started_war_as_attacker(self):
        # given
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            aggressor=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            declared=now() - dt.timedelta(days=2),
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)

    def test_should_return_started_war_as_ally(self):
        # given
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            allies=[EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id)],
            declared=now() - dt.timedelta(days=2),
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)

    def test_should_return_war_about_to_finish(self):
        # given
        sync_manager = SyncManagerFactory()
        war = EveWarFactory(
            defender=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            declared=now() - dt.timedelta(days=2),
            finished=now() + dt.timedelta(days=1),
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 1)
        self.assertEqual(result.first(), war)

    def test_should_not_return_finished_war(self):
        # given
        sync_manager = SyncManagerFactory()
        EveWarFactory(
            defender=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            declared=now() - dt.timedelta(days=2),
            finished=now() - dt.timedelta(days=1),
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 0)

    def test_should_not_return_war_not_yet_started(self):
        # given
        sync_manager = SyncManagerFactory()
        EveWarFactory(
            defender=EveEntityAllianceFactory(id=sync_manager.alliance.alliance_id),
            declared=now() - dt.timedelta(days=1),
            started=now() + dt.timedelta(hours=4),
        )
        # when
        result = EveWar.objects.active_wars()
        # then
        self.assertEqual(result.count(), 0)


class TestSyncManagerManager(NoSocketsTestCase):
    def test_should_return_matching_sync_manager(self):
        # given
        user = UserMainSyncerFactory()
        alliance = EveAllianceInfoFactory(
            alliance_id=user.profile.main_character.alliance_id
        )
        sync_manager = SyncManagerFactory(alliance=alliance)
        # when
        result = SyncManager.objects.fetch_for_user(user)
        # then
        self.assertEqual(result, sync_manager)

    def test_should_return_none_when_no_match(self):
        # given
        user = UserMainSyncerFactory()
        SyncManagerFactory()
        # when
        result = SyncManager.objects.fetch_for_user(user)
        # then
        self.assertIsNone(result)

    def test_should_return_none_when_user_has_no_main(self):
        # given
        user = UserFactory()
        # when
        result = SyncManager.objects.fetch_for_user(user)
        # then
        self.assertIsNone(result)
