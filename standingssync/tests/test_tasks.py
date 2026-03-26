from unittest.mock import patch

from django.test import TestCase, override_settings

from app_utils.testing import NoSocketsTestCase

from standingssync import tasks
from standingssync.models import SyncManager

from .factories import (
    SyncedCharacterFactory,
    SyncManagerFactory,
    UserMainManagerFactory,
)

MANAGERS_PATH = "standingssync.managers"
MODELS_PATH = "standingssync.models"
TASKS_PATH = "standingssync.tasks"


@patch(TASKS_PATH + ".run_manager_sync")
@patch(TASKS_PATH + ".sync_all_wars")
class TestRunRegularSync(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = UserMainManagerFactory()

    def test_should_not_sync_wars_if_disabled(
        self, mock_update_all_wars, mock_run_manager_sync
    ):
        # when
        with (
            patch(TASKS_PATH + ".is_esi_online", lambda: True),
            patch(TASKS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False),
        ):
            tasks.run_regular_sync()
        # then
        self.assertFalse(mock_update_all_wars.apply_async.called)

    def test_should_start_all_tasks(self, mock_update_all_wars, mock_run_manager_sync):
        # given
        sync_manager = SyncManagerFactory(user=self.user)
        # when
        with (
            patch(TASKS_PATH + ".is_esi_online", lambda: True),
            patch(TASKS_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True),
        ):
            tasks.run_regular_sync()
        # then
        self.assertTrue(mock_update_all_wars.apply_async.called)
        _, kwargs = mock_run_manager_sync.apply_async.call_args
        self.assertListEqual(kwargs["args"], [sync_manager.pk])

    def test_abort_when_esi_if_offline(
        self, mock_update_all_wars, mock_run_manager_sync
    ):
        # when
        with patch(TASKS_PATH + ".is_esi_online", lambda: False):
            tasks.run_regular_sync()
        # then
        self.assertFalse(mock_update_all_wars.apply_async.called)
        self.assertFalse(mock_run_manager_sync.apply_async.called)


@patch(TASKS_PATH + ".SyncedCharacter.run_sync")
class TestCharacterSync(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.synced_character = SyncedCharacterFactory()

    def test_should_call_update(self, mock_update):
        # given
        mock_update.return_value = True
        # when
        tasks.run_character_sync(self.synced_character.pk)
        # then
        self.assertTrue(mock_update.called)

    def test_should_raise_exception(self, mock_update):
        # given
        mock_update.side_effect = RuntimeError
        # when
        with self.assertRaises(RuntimeError):
            tasks.run_character_sync(self.synced_character.pk)


@patch(TASKS_PATH + ".run_character_sync")
class TestManagerSync(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_manager = UserMainManagerFactory()

    # run for non existing sync manager
    def test_run_sync_wrong_pk(self, mock_run_character_sync):
        with self.assertRaises(SyncManager.DoesNotExist):
            tasks.run_manager_sync(99999)

    @patch(MODELS_PATH + ".SyncManager.run_sync")
    def test_should_abort_when_unexpected_exception_occurs(
        self, mock_update_from_esi, mock_run_character_sync
    ):
        # given
        mock_update_from_esi.side_effect = RuntimeError
        sync_manager = SyncManagerFactory(user=self.user_manager)

        # when/then
        with self.assertRaises(RuntimeError):
            tasks.run_manager_sync(sync_manager.pk)
        # then

    @patch(MODELS_PATH + ".SyncManager.run_sync")
    def test_should_normally_run_character_sync(
        self, mock_update_from_esi, mock_run_character_sync
    ):
        # given
        mock_update_from_esi.return_value = "abc"
        sync_manager = SyncManagerFactory(user=self.user_manager)
        synced_character = SyncedCharacterFactory(manager=sync_manager)

        # when
        tasks.run_manager_sync(sync_manager.pk)

        # then
        sync_manager.refresh_from_db()
        _, kwargs = mock_run_character_sync.apply_async.call_args
        self.assertEqual(kwargs["kwargs"]["sync_char_pk"], synced_character.pk)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@patch(TASKS_PATH + ".run_war_sync")
@patch(TASKS_PATH + ".EveWar.objects.fetch_active_war_ids_esi")
class TestSyncAllWars(TestCase):
    def test_should_start_tasks_for_each_war_id(
        self, mock_calc_relevant_war_ids, mock_update_war
    ):
        # given
        mock_calc_relevant_war_ids.return_value = [1, 2, 3]
        # when
        tasks.sync_all_wars()
        # then
        result = {
            obj[1]["args"][0] for obj in mock_update_war.apply_async.call_args_list
        }
        self.assertSetEqual(result, {1, 2, 3})

    def test_should_not_start_any_war_update(
        self, mock_calc_relevant_war_ids, mock_update_war
    ):
        # given
        mock_calc_relevant_war_ids.return_value = []
        # when
        tasks.sync_all_wars()
        # then
        result = {
            obj[1]["args"][0] for obj in mock_update_war.apply_async.call_args_list
        }
        self.assertSetEqual(result, set())

    # @patch(TASKS_PATH + ".run_war_sync")
    # @patch(TASKS_PATH + ".EveWar.objects.fetch_active_war_ids_esi")
    # def test_should_remove_older_finished_wars(
    #     self, mock_calc_relevant_war_ids, mock_update_war
    # ):
    #     # given
    #     mock_calc_relevant_war_ids.return_value = [2]
    #     EveWarFactory(id=1)
    #     EveWarFactory(id=2)
    #     # when
    #     tasks.sync_all_wars()
    #     # then
    #     current_war_ids = set(EveWar.objects.values_list("id", flat=True))
    #     self.assertSetEqual(current_war_ids, {2})


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestRunWarSync(NoSocketsTestCase):
    @patch(TASKS_PATH + ".EveWar.objects.update_or_create_from_esi")
    def test_should_update_war(self, mock_update_from_esi):
        # when
        tasks.run_war_sync(42)
        # then
        args, _ = mock_update_from_esi.call_args
        self.assertEqual(args[0], 42)
