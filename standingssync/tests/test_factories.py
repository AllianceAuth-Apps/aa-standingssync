from app_utils.testing import NoSocketsTestCase

from .factories import EveContactFactory, SyncedCharacterFactory, SyncManagerFactory


class TestEveContactFactory(NoSocketsTestCase):
    def test_basic(self):
        x = EveContactFactory()
        self.assertEqual(x.standing, 5)
        self.assertFalse(x.is_war_target)

    def test_should_create_war_target(self):
        x = EveContactFactory(is_war_target=True)
        self.assertEqual(x.standing, -10)
        self.assertTrue(x.is_war_target)


class TestSyncedCharacterFactory(NoSocketsTestCase):
    def test_can_create_empty(self):
        sc = SyncedCharacterFactory()
        self.assertTrue(sc)

    def test_should_create_character_matching_the_manager(self):
        sm = SyncManagerFactory()
        sc = SyncedCharacterFactory(manager=sm)
        self.assertEqual(sc.character.alliance_id, sm.alliance.alliance_id)
        self.assertEqual(sc.character_ownership.user.character_ownerships.count(), 1)

    def test_should_create_al(self):
        sm = SyncManagerFactory()
        sc = SyncedCharacterFactory(manager=sm, create_alt=True)
        self.assertEqual(sc.character_ownership.user.character_ownerships.count(), 2)
