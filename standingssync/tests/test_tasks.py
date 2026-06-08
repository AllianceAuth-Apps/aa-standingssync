from unittest.mock import MagicMock, patch

from celery.exceptions import Retry

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils.timezone import now
from esi.exceptions import ESIBucketLimitException
from esi.rate_limiting import ESIRateLimitBucket

from app_utils.testing import NoSocketsTestCase

from standingssync import tasks
from standingssync.models import SyncManager
from standingssync.tests.factories import (
    EveContactFactory,
    EveWarEmptyFactory,
    EveWarFactory,
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

    def setUp(self):
        cache.clear()

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

    def setUp(self):
        cache.clear()

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

    def setUp(self):
        cache.clear()

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
        sm = SyncManagerFactory(user=self.user_manager)

        # when/then
        with self.assertRaises(RuntimeError):
            tasks.run_manager_sync(sm.pk)

    @patch(MODELS_PATH + ".SyncManager.run_sync")
    def test_should_normally_run_character_sync(
        self, mock_update_from_esi, mock_run_character_sync
    ):
        # given
        mock_update_from_esi.return_value = "abc"
        sm = SyncManagerFactory(user=self.user_manager)
        sc = SyncedCharacterFactory(manager=sm)

        # when
        tasks.run_manager_sync(sm.pk)

        # then
        sm.refresh_from_db()
        _, kwargs = mock_run_character_sync.apply_async.call_args
        self.assertEqual(kwargs["kwargs"]["pk"], sc.pk)

    @patch(MODELS_PATH + ".SyncManager.run_sync")
    def test_should_abort_when_too_many_contacts(
        self, mock_update_from_esi, mock_run_character_sync
    ):
        # given
        mock_update_from_esi.return_value = "abc"
        sm = SyncManagerFactory(user=self.user_manager)

        for _ in range(1025):
            EveContactFactory(manager=sm)

        # when/then
        with self.assertRaises(RuntimeError):
            tasks.run_manager_sync(sm.pk)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@patch(TASKS_PATH + ".sync_stale_war")
@patch(TASKS_PATH + ".EveWar.objects.sync_known_wars")
class TestSyncAllWars(TestCase):
    def setUp(self):
        cache.clear()

    def test_should_start_sync_wars_task_when_wars_to_sync(
        self, mock_calc_relevant_war_ids: MagicMock, mock_sync_stale_war: MagicMock
    ):
        # given
        EveWarEmptyFactory()
        # when
        tasks.sync_all_wars.delay()
        # then
        self.assertEqual(mock_sync_stale_war.apply_async.call_count, 1)

    def test_should_not_start_sync_wars_tasks_when_no_wars_to_sync(
        self, mock_calc_relevant_war_ids: MagicMock, mock_sync_stale_war: MagicMock
    ):
        # given
        EveWarFactory(finished=now())
        # when
        tasks.sync_all_wars.delay()
        # then
        self.assertEqual(mock_sync_stale_war.apply_async.call_count, 0)


@override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@patch(TASKS_PATH + ".EveWar.update_from_esi")
class TestSyncWars(NoSocketsTestCase):
    def setUp(self):
        cache.clear()

    def test_should_update_war(self, mock_update_from_esi: MagicMock):
        # given
        war = EveWarEmptyFactory()

        def update():
            war.finished = now()
            war.save()

        mock_update_from_esi.side_effect = update
        # when
        tasks.sync_stale_war.delay()
        # then
        self.assertEqual(mock_update_from_esi.call_count, 1)

    def test_should_exit_when_no_wars_to_update(self, mock_update_from_esi: MagicMock):
        # given
        EveWarFactory(finished=now())
        # when
        tasks.sync_stale_war.delay()
        # then
        self.assertEqual(mock_update_from_esi.call_count, 0)

    def test_should_retry_on_rate_limit_exhausted(self, mock_update_from_esi):
        # given
        bucket = ESIRateLimitBucket("dummy", 10, 3600)
        ex = ESIBucketLimitException(bucket)
        mock_update_from_esi.side_effect = ex
        EveWarEmptyFactory()
        # when
        with self.assertRaises(Retry):
            tasks.sync_stale_war.delay()
