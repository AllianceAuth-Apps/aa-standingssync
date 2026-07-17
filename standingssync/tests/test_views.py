from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse
from esi.models import Token
from eveuniverse.tests.testdata.factories_2 import EveEntityCharacterFactory

from allianceauth.eveonline.models import EveCharacter
from app_utils.testdata_factories import (
    EveAllianceInfoFactory,
    EveCharacterFactory,
    UserMainFactory,
)
from app_utils.testing import NoSocketsTestCase, add_character_to_user

from standingssync import views
from standingssync.models import SyncedCharacter, SyncManager
from standingssync.tests.factories import (
    EveContactFactory,
    SyncedCharacterFactory,
    SyncManagerFactory,
    UserMainDefaultFactory,
    UserMainManagerFactory,
)

MODULE_PATH = "standingssync.views"


class TestMainScreen(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.factory = RequestFactory()

        cls.user_manager = UserMainManagerFactory()
        cls.sync_manager = SyncManagerFactory(user=cls.user_manager)
        cls.user_normal = UserMainDefaultFactory(
            main_character__alliance_id=cls.sync_manager.alliance.alliance_id
        )
        cls.sync_char = SyncedCharacterFactory(
            manager=cls.sync_manager, user=cls.user_manager
        )

        cls.user_no_permission = UserMainFactory()

    def test_should_redirect_to_main_page(self):
        # given
        request = self.factory.get(reverse("standingssync:characters"))
        request.user = self.user_normal
        # when
        response = views.index(request)
        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:characters"))

    def test_user_with_permission_can_open_app(self):
        request = self.factory.get(reverse("standingssync:characters"))
        request.user = self.user_normal
        response = views.characters(request)
        self.assertEqual(response.status_code, 200)

    def test_user_wo_permission_can_not_open_app(self):
        request = self.factory.get(reverse("standingssync:characters"))
        request.user = self.user_no_permission
        response = views.characters(request)
        self.assertEqual(response.status_code, 302)

    @patch(MODULE_PATH + ".messages")
    def test_user_can_remove_sync_char(self, mock_messages):
        request = self.factory.get(
            reverse("standingssync:remove_character", args=(self.sync_char.pk,))
        )
        request.user = self.user_normal
        response = views.remove_character(request, self.sync_char.pk)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(mock_messages.success.called)
        self.assertFalse(SyncedCharacter.objects.filter(pk=self.sync_char.pk).exists())


@patch(MODULE_PATH + ".tasks.run_character_sync")
@patch(MODULE_PATH + ".messages")
class TestAddSyncChar(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

        alliance = EveAllianceInfoFactory()
        character = EveCharacterFactory(corporation__alliance=alliance)
        cls.user_manager = UserMainManagerFactory(main_character__character=character)
        cls.sync_manager = SyncManagerFactory(user=cls.user_manager)

        cls.character_normal = EveCharacterFactory(corporation__alliance=alliance)
        cls.user_normal = UserMainDefaultFactory(
            main_character__character=cls.character_normal
        )

    def make_request(self, user: User, character: EveCharacter):
        token: Token = user.token_set.get(character_id=character.character_id)
        token.character_id = character.character_id
        request = self.factory.get(reverse("standingssync:add_character"))
        request.user = user
        request.token = token  # type: ignore
        middleware = SessionMiddleware(Mock())
        middleware.process_request(request)
        orig_view = views.add_character.__wrapped__.__wrapped__.__wrapped__
        return orig_view(request, token)

    def test_user_can_add_blue_alt(self, mock_messages, mock_run_character_sync):
        # given
        alt_character = EveCharacterFactory()
        add_character_to_user(self.user_normal, alt_character)
        EveContactFactory(
            manager=self.sync_manager,
            eve_entity=EveEntityCharacterFactory(id=alt_character.character_id),
            standing=10,
        )

        # when
        response = self.make_request(self.user_normal, alt_character)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:characters"))
        self.assertTrue(mock_messages.success.called)
        self.assertTrue(mock_run_character_sync.delay.called)
        self.assertTrue(
            SyncedCharacter.objects.filter(manager=self.sync_manager)
            .filter(character_ownership__character=alt_character)
            .exists()
        )

    def test_users_can_not_add_alliance_members(
        self, mock_messages, mock_run_character_sync
    ):
        # when
        with patch(MODULE_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1):
            response = self.make_request(self.user_normal, self.character_normal)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:characters"))
        self.assertTrue(mock_messages.warning.called)
        self.assertFalse(mock_run_character_sync.delay.called)

    @patch(MODULE_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0)
    def test_user_can_add_neutral_alt(self, mock_messages, mock_run_character_sync):
        # given
        alt_character = EveCharacterFactory()
        add_character_to_user(self.user_normal, alt_character)

        # when
        with patch(MODULE_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.0):
            response = self.make_request(self.user_normal, alt_character)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:characters"))
        self.assertTrue(mock_messages.success.called)
        self.assertTrue(mock_run_character_sync.delay.called)
        self.assertTrue(
            SyncedCharacter.objects.filter(manager=self.sync_manager)
            .filter(character_ownership__character=alt_character)
            .exists()
        )

    def test_user_can_not_add_non_blue_alt(
        self, mock_messages, mock_run_character_sync
    ):
        # given
        alt_character = EveCharacterFactory()
        add_character_to_user(self.user_normal, alt_character)

        # when
        with patch(MODULE_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1):
            response = self.make_request(self.user_normal, alt_character)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:characters"))
        self.assertTrue(mock_messages.warning.called)
        self.assertFalse(mock_run_character_sync.delay.called)
        self.assertFalse(
            SyncedCharacter.objects.filter(manager=self.sync_manager)
            .filter(character_ownership__character=alt_character)
            .exists()
        )

    def test_can_handle_missing_alliance_character(
        self, mock_messages, mock_run_character_sync
    ):
        # given
        sm = SyncManagerFactory(character_ownership=None)
        main = EveCharacterFactory(corporation__alliance=sm.alliance)
        user = UserMainDefaultFactory(main_character__character=main)
        alt_character = EveCharacterFactory()
        add_character_to_user(user, alt_character)
        EveContactFactory(
            manager=sm,
            eve_entity=EveEntityCharacterFactory(id=alt_character.character_id),
            standing=10,
        )
        # when
        with patch(MODULE_PATH + ".STANDINGSSYNC_CHAR_MIN_STANDING", 0.1):
            response = self.make_request(user, alt_character)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:characters"))
        self.assertFalse(mock_messages.warning.called)
        self.assertTrue(mock_run_character_sync.delay.called)
        self.assertTrue(
            SyncedCharacter.objects.filter(manager=sm)
            .filter(character_ownership__character=alt_character)
            .exists()
        )


@patch(MODULE_PATH + ".tasks")
@patch(MODULE_PATH + ".messages")
class TestAddAllianceManager(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = RequestFactory()

    def make_request(self, user: User):
        character: EveCharacter = user.profile.main_character
        token: Token = user.token_set.get(character_id=character.character_id)
        token.character_id = character.character_id
        request = self.factory.get(reverse("standingssync:add_alliance_manager"))
        request.user = user
        request.token = token  # type: ignore
        middleware = SessionMiddleware(Mock())
        middleware.process_request(request)
        orig_view = views.add_alliance_manager.__wrapped__.__wrapped__.__wrapped__
        return orig_view(request, token)

    def test_user_with_permission_can_add_alliance_manager(
        self, mock_messages, mock_tasks
    ):
        # given
        user = UserMainManagerFactory()

        # when
        response = self.make_request(user)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:index"))
        self.assertTrue(mock_messages.success.called)
        self.assertTrue(mock_tasks.run_manager_sync.delay.called)
        self.assertTrue(SyncManager.objects.exists())

    # def test_user_wo_permission_can_not_add_alliance_manager(
    #     self, mock_messages, mock_tasks
    # ):
    #     # given
    #     user = UserMainSyncerFactory()

    #     # when
    #     response = self.make_request(user)

    #     # then
    #     self.assertEqual(response.status_code, 302)
    #     self.assertEqual(response.url, reverse("standingssync:index"))
    #     self.assertFalse(mock_messages.success.called)
    #     self.assertFalse(mock_tasks.run_manager_sync.delay.called)
    #     self.assertFalse(SyncManager.objects.exists())

    def test_should_sync_wars_when_adding_alliance_char_and_feature_enabled(
        self, mock_messages, mock_tasks
    ):
        # given
        user = UserMainManagerFactory()

        # when
        with patch(MODULE_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", True):
            self.make_request(user)

        # then
        self.assertTrue(mock_tasks.sync_all_wars.delay.called)

    def test_should_not_sync_wars_when_adding_alliance_char_and_feature_disabled(
        self, mock_messages, mock_tasks
    ):
        # given
        user = UserMainManagerFactory()

        # when
        with patch(MODULE_PATH + ".STANDINGSSYNC_ADD_WAR_TARGETS", False):
            self.make_request(user)

        # then
        self.assertFalse(mock_tasks.sync_all_wars.delay.called)

    def test_character_for_manager_must_be_alliance_member(
        self, mock_messages, mock_tasks
    ):
        # given
        character = EveCharacterFactory(alliance_id=None, alliance_name="")
        user = UserMainManagerFactory(main_character__character=character)

        # when
        response = self.make_request(user)

        # then
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("standingssync:index"))
        self.assertTrue(mock_messages.warning.called)
        self.assertFalse(mock_tasks.run_manager_sync.delay.called)
        self.assertFalse(SyncManager.objects.exists())
