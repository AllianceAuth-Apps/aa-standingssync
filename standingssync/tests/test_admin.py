from http import HTTPStatus

from django.contrib.admin.sites import AdminSite
from django.test import TestCase

from app_utils.testdata_factories import UserFactory

from standingssync.admin import SyncManagerAdmin
from standingssync.models import SyncManager
from standingssync.tests.factories import (
    EveContactFactory,
    SyncedCharacterFactory,
    SyncManagerFactory,
)


class TestSyncedCharacterChangeList(TestCase):
    def test_should_open_main_page(self):
        # given
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        # when
        response = self.client.get("/admin/standingssync/syncedcharacter/")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_should_filter_by_character(self):
        # given
        SyncedCharacterFactory()
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        # when
        response = self.client.get("/admin/standingssync/syncedcharacter/?o=2")
        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestSyncManagerChangeList_HTTP(TestCase):
    def test_can_open_page_normally(self):
        # given
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        SyncManagerFactory()

        # when
        response = self.client.get("/admin/standingssync/syncmanager/")

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestSyncManagerChangeList_Admin(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.modeladmin = SyncManagerAdmin(model=SyncManager, admin_site=AdminSite())
        cls.user = UserFactory(is_superuser=True, is_staff=True)

    def test_contacts_count(self):
        # given
        sm = SyncManagerFactory()
        EveContactFactory(manager=sm)
        EveContactFactory(manager=sm)
        EveContactFactory(manager=sm)

        # when
        got = self.modeladmin._contacts_count(sm)

        # then
        self.assertEqual(got, "3")


class TestEveWarChangeList(TestCase):
    def test_can_open_page_normally(self):
        # given
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        SyncManagerFactory()

        # when
        response = self.client.get("/admin/standingssync/evewar/")

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)


class TestEvContactChangeList(TestCase):
    def test_can_open_page_normally(self):
        # given
        user = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_login(user)
        sm = SyncManagerFactory()
        EveContactFactory(manager=sm)

        # when
        response = self.client.get("/admin/standingssync/evecontact/")

        # then
        self.assertEqual(response.status_code, HTTPStatus.OK)
