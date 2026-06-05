import datetime as dt
from unittest.mock import MagicMock, patch

from django.utils.timezone import now
from eveuniverse.tests.testdata.factories_2 import EveEntityAllianceFactory

from app_utils.testdata_factories import EveAllianceInfoFactory, UserFactory
from app_utils.testing import NoSocketsTestCase

from standingssync.models import EveWar, SyncManager
from standingssync.tests.factories import (
    EveContactFactory,
    EveWarEmptyFactory,
    EveWarFactory,
    SyncManagerFactory,
    UserMainDefaultFactory,
)
from standingssync.tests.helpers import extract

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

    def test_should_return_non_empty_wars(self):
        # given
        war = EveWarFactory()
        EveWarEmptyFactory()

        # when
        got = EveWar.objects.non_empty()

        # then
        self.assertCountEqual(got, [war])

    def test_should_return_empty_wars(self):
        # given
        EveWarFactory()
        war = EveWarEmptyFactory()

        # when
        got = EveWar.objects.empty()

        # then
        self.assertCountEqual(got, [war])

    def test_should_return_wars_that_need_update_only(self):
        # given
        EveWarFactory()  # should not include recently synced active wars
        EveWarFactory(finished=now())  # should not include finished wars
        war_1 = EveWarEmptyFactory()  # should include empty wars
        with patch("django.utils.timezone.now") as m:
            m.return_value = now() - dt.timedelta(hours=1, seconds=1)
            war_2 = EveWarFactory()  # should include stale active wars
            EveWarFactory(finished=now())  # should not include stale finished wars

        # when
        got = EveWar.objects.needs_update()

        # then
        want = [war_1, war_2]
        self.assertCountEqual(got, want)


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


class TestEveWarManager_Annotations(NoSocketsTestCase):
    def test_should_annotate_state(self):
        # given
        war_pending = EveWarFactory(declared=now())
        war_ongoing = EveWarFactory(declared=now() - dt.timedelta(hours=24))
        war_concluding = EveWarFactory(finished=now() + dt.timedelta(hours=24))
        war_retracted = EveWarFactory(retracted=now())
        war_finished = EveWarFactory(finished=now() - dt.timedelta(hours=1))
        war_unknown = EveWarEmptyFactory()

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
        self.assertEqual(qs.get(id=war_unknown.id).state, EveWar.State.UNKNOWN.value)

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


class TestEveWarManager_SyncKnownWars(NoSocketsTestCase):
    @patch(MANAGERS_PATH + ".esi_api.fetch_war_ids")
    def test_should_sync_wars(self, mock_fetch_war_ids_from_esi: MagicMock):
        # given
        mock_fetch_war_ids_from_esi.return_value = {99, 98, 42}
        EveWarFactory(id=42, finished=now() - dt.timedelta(days=1))
        # when
        EveWar.objects.sync_known_wars()
        # then
        args, _ = mock_fetch_war_ids_from_esi.call_args
        self.assertEqual(args[0], 42)
        got = extract(EveWar.objects, "id")
        want = {99, 98, 42}
        self.assertSetEqual(got, want)


class TestEveWarManager_UpdatedPercentage(NoSocketsTestCase):
    def test_should_return_correct_percentage(self):
        # given
        EveWarFactory()
        EveWarFactory()
        EveWarFactory()
        EveWarEmptyFactory()

        # when
        got = EveWar.objects.updated_percentage()

        # then
        self.assertEqual(got, 0.75)

    def test_should_return_1_when_completed(self):
        # given
        EveWarFactory()
        EveWarFactory()
        EveWarFactory()

        # when
        got = EveWar.objects.updated_percentage()

        # then
        self.assertEqual(got, 1)

    def test_should_return_0_when_no_wars(self):
        # when
        got = EveWar.objects.updated_percentage()

        # then
        self.assertEqual(got, 0)


class TestSyncManagerManager(NoSocketsTestCase):
    def test_should_return_matching_sync_manager(self):
        # given
        user = UserMainDefaultFactory()
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
        user = UserMainDefaultFactory()
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
