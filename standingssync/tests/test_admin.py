from django.test import TestCase

from app_utils.testdata_factories import UserFactory

from standingssync.tests.factories import SyncedCharacterFactory


class TestSyncedCharacterChangeList(TestCase):
    def test_should_open_main_page(self):
        # given
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        # when
        response = self.client.get("/admin/standingssync/syncedcharacter/")
        # then
        self.assertEqual(response.status_code, 200)

    def test_should_filter_by_character(self):
        # given
        SyncedCharacterFactory()
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        # when
        response = self.client.get("/admin/standingssync/syncedcharacter/?o=2")
        # then
        self.assertEqual(response.status_code, 200)
