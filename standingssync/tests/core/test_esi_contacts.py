from http import HTTPStatus
from unittest.mock import patch

import pook

from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
    EveEntityCorporationFactory,
    EveEntityFactionFactory,
)

from app_utils.testing import NoSocketsTestCase

from standingssync.core.esi_contacts import (
    EsiContact,
    EsiContactLabel,
    EsiContactsContainer,
)
from standingssync.tests.factories import (
    EsiContactAllianceFactory,
    EsiContactCharacterFactory,
    EsiContactCorporationFactory,
    EsiContactFactionFactory,
    EsiContactFactory,
    EsiContactLabelFactory,
    EveContactFactory,
    make_esi_url,
)

MODULE_PATH = "standingssync.core.esi_contacts"
WAR_TARGET_LABEL = "WAR TARGETS"


class TestEsiContact(NoSocketsTestCase):
    def test_should_create_new_1(self):
        # when
        obj = EsiContact(1001, EsiContact.Category.CHARACTER, 5.0)
        # then
        self.assertEqual(obj.contact_id, 1001)
        self.assertEqual(obj.contact_type, EsiContact.Category.CHARACTER)
        self.assertEqual(obj.standing, 5.0)

    def test_should_create_new_2(self):
        # when
        obj = EsiContact(1001, "character", 5.0)  # type: ignore
        # then
        self.assertEqual(obj.contact_id, 1001)
        self.assertEqual(obj.contact_type, EsiContact.Category.CHARACTER)
        self.assertEqual(obj.standing, 5.0)

    def test_should_create_new_3(self):
        # when/then
        with self.assertRaises(ValueError):
            EsiContact(1001, "xyz", 5.0)  # type: ignore

    def test_should_create_all_types(self):
        # given
        params = [
            ("character", EsiContact.Category.CHARACTER),
            ("corporation", EsiContact.Category.CORPORATION),
            ("alliance", EsiContact.Category.ALLIANCE),
            ("faction", EsiContact.Category.FACTION),
        ]
        for input, expected in params:
            with self.subTest(input=input):
                # when
                obj = EsiContact(1001, input, 5.0)
                # then
                self.assertEqual(obj.contact_id, 1001)
                self.assertEqual(obj.contact_type, expected)
                self.assertEqual(obj.standing, 5.0)

    def test_should_clone_contact_1(self):
        # given
        a = EsiContact(1, EsiContact.Category.CHARACTER, 5.0, frozenset([1, 2]))
        # when
        b = a.clone()
        # then
        self.assertEqual(a, b)

    def test_should_clone_contact_2(self):
        # given
        a = EsiContact(1, EsiContact.Category.CHARACTER, 5.0, frozenset([1, 2]))
        # when
        b = a.clone(standing=-10)
        # then
        self.assertEqual(b.contact_id, a.contact_id)
        self.assertEqual(b.contact_type, a.contact_type)
        self.assertEqual(b.label_ids, a.label_ids)
        self.assertEqual(b.standing, -10)

    def test_should_create_from_esi_character(self):
        # given
        esi_dict = {"contact_id": 1, "contact_type": "character", "standing": 5.0}
        # when
        obj = EsiContact.from_esi_dict(esi_dict)
        # then
        self.assertEqual(obj, EsiContact(1, EsiContact.Category.CHARACTER, 5.0))

    def test_should_create_from_esi_corporation(self):
        # given
        esi_dict = {"contact_id": 1, "contact_type": "corporation", "standing": 5.0}
        # when
        obj = EsiContact.from_esi_dict(esi_dict)
        # then
        self.assertEqual(obj, EsiContact(1, EsiContact.Category.CORPORATION, 5.0))

    def test_should_create_from_esi_alliance(self):
        # given
        esi_dict = {"contact_id": 1, "contact_type": "alliance", "standing": 5.0}
        # when
        obj = EsiContact.from_esi_dict(esi_dict)
        # then
        self.assertEqual(obj, EsiContact(1, EsiContact.Category.ALLIANCE, 5.0))

    def test_should_create_from_esi_contact_when_labels_are_none(self):
        # given
        esi_dict = {
            "contact_id": 1,
            "contact_type": "alliance",
            "standing": 5.0,
            "label_ids": None,
        }
        # when
        obj = EsiContact.from_esi_dict(esi_dict)
        # then
        self.assertEqual(obj, EsiContact(1, EsiContact.Category.ALLIANCE, 5.0))

    def test_should_create_from_esi_faction(self):
        # given
        esi_dict = {"contact_id": 1, "contact_type": "faction", "standing": 5.0}
        # when
        obj = EsiContact.from_esi_dict(esi_dict)
        # then
        self.assertEqual(obj, EsiContact(1, EsiContact.Category.FACTION, 5.0))

    def test_should_create_from_eve_entities(self):
        # given
        params = [
            (EveEntityCharacterFactory(), EsiContact.Category.CHARACTER),
            (EveEntityCorporationFactory(), EsiContact.Category.CORPORATION),
            (EveEntityAllianceFactory(), EsiContact.Category.ALLIANCE),
            (EveEntityFactionFactory(), EsiContact.Category.FACTION),
        ]
        for eve_entity, expected in params:
            with self.subTest(category=eve_entity.category):
                # when
                got = EsiContact.from_eve_entity(eve_entity=eve_entity, standing=5.0)
                # then
                self.assertEqual(got, EsiContact(eve_entity.id, expected, 5.0))
                self.assertFalse(got.is_war_target)

    def test_should_create_from_eve_entities_as_war_target(self):
        # when
        got = EsiContact.from_eve_entity(
            eve_entity=EveEntityCharacterFactory(), standing=-10, is_war_target=True
        )
        # then
        self.assertTrue(got.is_war_target)


class TestEsiContactLabel(NoSocketsTestCase):
    def test_should_create_from_esi_dict(self):
        # given
        esi_dict = {"label_id": 42, "label_name": "alpha"}
        # when
        result = EsiContactLabel.from_esi_dict(esi_dict)
        # then
        self.assertEqual(result.id, 42)
        self.assertEqual(result.name, "alpha")

    def test_should_convert_to_dict(self):
        # given
        obj = EsiContactLabel(42, "alpha")
        # when
        result = obj.to_dict()
        # then
        expected = {42: "alpha"}
        self.assertDictEqual(expected, result)

    def test_should_convert_to_esi_dict(self):
        # given
        obj = EsiContactLabel(42, "alpha")
        # when
        result = obj.to_esi_dict()
        # then
        expected = {"label_id": 42, "label_name": "alpha"}
        self.assertDictEqual(expected, result)


@patch(MODULE_PATH + ".STANDINGSSYNC_WAR_TARGETS_LABEL_NAME", WAR_TARGET_LABEL)
class TestEsiContactsContainer(NoSocketsTestCase):
    def test_should_create_empty(self):
        # when
        obj = EsiContactsContainer()
        # then
        self.assertIsInstance(obj, EsiContactsContainer)

    def test_should_create_from_contacts_dict(self):
        # given
        contact_1 = EsiContactFactory()
        contact_2 = EsiContactFactory()
        esi_contacts = [contact_1.to_esi_dict(), contact_2.to_esi_dict()]
        # when
        obj = EsiContactsContainer.from_esi_dicts(esi_contacts)
        # then
        expected = {contact_1, contact_2}
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_create_from_contacts_dict_w_labels(self):
        # given
        label_1 = EsiContactLabelFactory()
        contact_1 = EsiContactFactory(label_ids=[label_1.id])
        label_2 = EsiContactLabelFactory()
        contact_2 = EsiContactFactory(label_ids=[label_1.id, label_2.id])
        esi_contacts = [contact_1.to_esi_dict(), contact_2.to_esi_dict()]
        esi_labels = [label_1.to_esi_dict(), label_2.to_esi_dict()]
        # when
        obj = EsiContactsContainer.from_esi_dicts(esi_contacts, esi_labels)
        # then
        expected = {contact_1, contact_2}
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_create_from_dicts_labels_only(self):
        # given
        label = EsiContactLabelFactory()
        esi_labels = [label.to_esi_dict()]
        # when
        obj = EsiContactsContainer.from_esi_dicts(labels=esi_labels)
        # then
        self.assertEqual(obj.labels(), {label})

    def test_should_create_empty_for_dicts(self):
        # when
        obj = EsiContactsContainer.from_esi_dicts()
        # then
        self.assertIsInstance(obj, EsiContactsContainer)

    def test_should_create_from_esi_contacts(self):
        # given
        contact_1 = EsiContactFactory()
        contact_2 = EsiContactFactory()
        esi_contacts = [contact_1, contact_2]
        # when
        obj = EsiContactsContainer.from_esi_contacts(esi_contacts)
        # then
        expected = {contact_1, contact_2}
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_create_from_esi_contacts_w_labels(self):
        # given
        label_1 = EsiContactLabelFactory()
        contact_1 = EsiContactFactory(label_ids=[label_1.id])
        label_2 = EsiContactLabelFactory()
        contact_2 = EsiContactFactory(label_ids=[label_1.id, label_2.id])
        esi_contacts = [contact_1, contact_2]
        esi_labels = [label_1, label_2]
        # when
        obj = EsiContactsContainer.from_esi_contacts(esi_contacts, esi_labels)
        # then
        expected = {contact_1, contact_2}
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_return_contacts_by_id(self):
        # given
        c1 = EsiContactFactory()
        c2 = EsiContactFactory()
        contacts = EsiContactsContainer.from_esi_contacts([c1, c2])
        # when
        result = contacts.contact_by_id(c1.contact_id)
        # then
        self.assertEqual(result, c1)

    def test_should_raise_error_when_contact_not_found(self):
        # given
        c1 = EsiContactFactory()
        c2 = EsiContactFactory()
        contacts = EsiContactsContainer.from_esi_contacts([c1, c2])
        # when/then
        with self.assertRaises(ValueError):
            contacts.contact_by_id(123456)

    def test_should_raise_error_when_label_not_found(self):
        # given
        contacts = EsiContactsContainer.from_esi_contacts()
        # when/then
        with self.assertRaises(ValueError):
            contacts.label_by_id(123456)

    def test_should_find_label_by_id(self):
        # given
        label = EsiContactLabelFactory()
        contacts = EsiContactsContainer.from_esi_contacts(labels=[label])
        # when
        new_label = contacts.label_by_id(label.id)
        # then
        self.assertEqual(label, new_label)

    def test_should_remove_unknown_label_ids(self):
        # given
        label_1 = EsiContactLabelFactory()
        label_2 = EsiContactLabelFactory()
        contacts = EsiContactsContainer.from_esi_contacts(labels=[label_1])
        contact_1 = EsiContactFactory(label_ids=[label_1.id, label_2.id])
        # when
        contacts.add_contact(contact_1)
        # then
        contact_1a = contacts.contact_by_id(contact_1.contact_id)
        self.assertEqual(contact_1a.label_ids, frozenset([label_1.id]))

    def test_should_return_labels(self):
        # given
        labels = {EsiContactLabelFactory(), EsiContactLabelFactory()}
        obj = EsiContactsContainer.from_esi_contacts(labels=labels)
        # when/then
        self.assertSetEqual(labels, obj.labels())

    def test_should_return_contacts(self):
        # given
        contacts = {EsiContactFactory(), EsiContactFactory()}
        obj = EsiContactsContainer.from_esi_contacts(contacts)
        # when/then
        self.assertSetEqual(contacts, obj.contacts())

    def test_should_remove_contact(self):
        # given
        contact_1 = EsiContactFactory()
        contact_2 = EsiContactFactory()
        esi_contacts = [contact_1.to_esi_dict(), contact_2.to_esi_dict()]
        obj = EsiContactsContainer.from_esi_dicts(esi_contacts)
        # when
        obj.remove_contact(contact_2)
        # then
        expected = {contact_1}
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_remove_several_contacts(self):
        # given
        contact_1 = EsiContactFactory()
        contact_2 = EsiContactFactory()
        contact_3 = EsiContactFactory()
        obj = EsiContactsContainer.from_esi_contacts([contact_1, contact_2, contact_3])
        # when
        obj.remove_contacts([contact_1, contact_2])
        # then
        expected = {contact_3}
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_raise_error_when_trying_to_remove_unknown_contact(self):
        # given
        contact_1 = EsiContactFactory()
        contact_2 = EsiContactFactory()
        obj = EsiContactsContainer.from_esi_contacts([contact_1])
        # when/then
        with self.assertRaises(ValueError):
            obj.remove_contact(contact_2)

    def test_should_convert_to_esi_dict(self):
        # given
        label_1 = EsiContactLabelFactory(id=1)
        contact_1 = EsiContactFactory(contact_id=11, label_ids=[label_1.id])
        label_2 = EsiContactLabelFactory(id=2)
        contact_2 = EsiContactFactory(contact_id=12, label_ids=[label_1.id, label_2.id])
        esi_contacts = [contact_1.to_esi_dict(), contact_2.to_esi_dict()]
        esi_labels = [label_1.to_esi_dict(), label_2.to_esi_dict()]
        obj = EsiContactsContainer.from_esi_dicts(esi_contacts, esi_labels)
        # when/then
        self.assertListEqual(obj.contacts_to_esi_dicts(), esi_contacts)
        self.assertListEqual(obj.labels_to_esi_dicts(), esi_labels)

    def test_should_generate_version_hash(self):
        # given
        label_1 = EsiContactLabelFactory()
        contact_1 = EsiContactFactory(label_ids=[label_1.id])
        label_2 = EsiContactLabelFactory()
        contact_2 = EsiContactFactory(label_ids=[label_1.id, label_2.id])
        esi_contacts = [contact_1.to_esi_dict(), contact_2.to_esi_dict()]
        esi_labels = [label_1.to_esi_dict(), label_2.to_esi_dict()]
        obj_1 = EsiContactsContainer.from_esi_dicts(esi_contacts, esi_labels)
        obj_2 = EsiContactsContainer.from_esi_dicts(esi_contacts, esi_labels)
        # when/then
        self.assertEqual(obj_1.version_hash(), obj_2.version_hash())

    def test_should_find_war_target_id(self):
        # given
        label_1 = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        label_2 = EsiContactLabelFactory()
        obj = EsiContactsContainer.from_esi_contacts(labels=[label_1, label_2])
        # when
        result = obj.war_target_label_id()
        # then
        self.assertEqual(result, label_1.id)

    def test_should_not_find_war_target_id(self):
        # given
        label_1 = EsiContactLabelFactory(name="alpha")
        label_2 = EsiContactLabelFactory(name="bravo")
        obj = EsiContactsContainer.from_esi_contacts(labels=[label_1, label_2])
        # when
        result = obj.war_target_label_id()
        # then
        self.assertIsNone(result)

    def test_should_return_war_targets(self):
        # given
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        other_label = EsiContactLabelFactory()
        other_contact = EsiContactFactory(label_ids=[other_label.id])
        war_target = EsiContactFactory(label_ids=[wt_label.id, other_label.id])
        obj = EsiContactsContainer.from_esi_contacts(
            contacts=[other_contact, war_target], labels=[wt_label, other_label]
        )
        # when
        result = obj.war_targets()
        # then
        self.assertSetEqual(result, {war_target})

    def test_should_remove_war_targets(self):
        # given
        wt_label = EsiContactLabelFactory(name=WAR_TARGET_LABEL)
        other_label = EsiContactLabelFactory()
        other_contact = EsiContactFactory(label_ids=[other_label.id])
        war_target = EsiContactFactory(label_ids=[wt_label.id, other_label.id])
        obj = EsiContactsContainer.from_esi_contacts(
            contacts=[other_contact, war_target], labels=[wt_label, other_label]
        )
        # when
        obj.remove_war_targets()
        # then
        self.assertSetEqual(obj.contacts(), {other_contact})

    def test_should_add_eve_contacts(self):
        # given
        obj = EsiContactsContainer()
        contact_1 = EveContactFactory()
        contact_2 = EveContactFactory()
        # when
        obj.add_eve_contacts([contact_1, contact_2])
        # then
        expected = {
            EsiContact.from_eve_contact(contact_1),
            EsiContact.from_eve_contact(contact_2),
        }
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_add_eve_contacts_w_labels(self):
        # given
        label = EsiContactLabelFactory()
        obj = EsiContactsContainer()
        obj.add_label(label)
        label_ids = [label.id]
        contact_1 = EveContactFactory()
        contact_2 = EveContactFactory()
        # when
        obj.add_eve_contacts([contact_1, contact_2], label_ids=label_ids)
        # then
        expected = {
            EsiContact.from_eve_contact(contact_1, label_ids=label_ids),
            EsiContact.from_eve_contact(contact_2, label_ids),
        }
        self.assertSetEqual(obj.contacts(), expected)

    def test_should_create_clone(self):
        # given
        label_1 = EsiContactLabelFactory()
        label_2 = EsiContactLabelFactory()
        contact_1 = EsiContactFactory(label_ids=[label_1.id])
        contact_2 = EsiContactFactory(label_ids=[label_2.id])
        first = EsiContactsContainer.from_esi_contacts(
            contacts=[contact_1, contact_2], labels=[label_1, label_2]
        )
        # when
        second = first.clone()
        # then
        self.assertEqual(first, second)
        second.remove_contact(contact_1)
        self.assertNotIn(contact_1, second.contacts())
        self.assertIn(contact_1, first.contacts())

    def test_should_return_all_contact_ids(self):
        # given
        c1 = EsiContactFactory()
        c2 = EsiContactFactory()
        contacts = EsiContactsContainer.from_esi_contacts([c1, c2])
        # when
        result = contacts.contact_ids()
        # then
        self.assertSetEqual(result, {c1.contact_id, c2.contact_id})


class TestEsiContactsCloneComparisons(NoSocketsTestCase):
    def test_should_return_contacts_difference(self):
        # given
        c1 = EsiContactFactory()
        c2 = EsiContactFactory()
        c3 = EsiContactFactory()
        c4 = EsiContactFactory(standing=5)
        c4a = c4.clone(standing=-10)
        a = EsiContactsContainer.from_esi_contacts([c1, c2, c4])
        b = EsiContactsContainer.from_esi_contacts([c1, c3, c4a])
        # when
        added, removed, changed = a.contacts_difference(b)
        # then
        self.assertSetEqual(added, {c3})
        self.assertSetEqual(removed, {c2})
        self.assertSetEqual(changed, {c4a})


class TestEsiContacts_Prune(NoSocketsTestCase):
    @pook.on
    def test_should_remove_neutral_alliances(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(standing=0)
        contacts = EsiContactsContainer.from_esi_contacts([alliance])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = set()
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_not_remove_neutral_alliances(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(standing=0)
        contacts = EsiContactsContainer.from_esi_contacts([alliance])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=False)

        # then
        got = contacts.contacts()
        want = {alliance}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_remove_faction_contacts(
        self,
    ):
        # given
        faction = EsiContactFactionFactory(standing=5)
        contacts = EsiContactsContainer.from_esi_contacts([faction])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = set()
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_not_remove_faction_contacts(
        self,
    ):
        # given
        faction = EsiContactFactionFactory(standing=5)
        contacts = EsiContactsContainer.from_esi_contacts([faction])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=False)

        # then
        got = contacts.contacts()
        want = {faction}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_remove_character_when_corporation_exists_and_has_same_standing(
        self,
    ):
        # given
        corporation = EsiContactCorporationFactory(contact_id=2001, standing=-5)
        character_1 = EsiContactCharacterFactory(standing=-5)
        character_2 = EsiContactCharacterFactory(standing=5)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "character_id": character_1.contact_id,
                    "corporation_id": corporation.contact_id,
                },
                {
                    "character_id": character_2.contact_id,
                    "corporation_id": corporation.contact_id,
                },
            ],
        )
        pook.get(
            make_esi_url(f"corporations/{corporation.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
        )
        contacts = EsiContactsContainer.from_esi_contacts(
            [corporation, character_1, character_2]
        )

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = {corporation, character_2}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_remove_character_when_alliance_exists_and_has_same_standing(
        self,
    ):
        # given
        corporation_id = 2001
        alliance = EsiContactAllianceFactory(contact_id=3001, standing=-5)
        character_1 = EsiContactCharacterFactory(contact_id=1001, standing=-5)
        character_2 = EsiContactCharacterFactory(contact_id=1002, standing=5)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "alliance_id": alliance.contact_id,
                    "character_id": character_1.contact_id,
                    "corporation_id": corporation_id,
                },
                {
                    "character_id": character_2.contact_id,
                    "corporation_id": corporation_id,
                },
            ],
        )
        contacts = EsiContactsContainer.from_esi_contacts(
            [alliance, character_1, character_2]
        )

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = {alliance, character_2}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_remove_corporation_when_alliance_exists_and_has_same_standing(
        self,
    ):
        # given
        corporation_1_id = 2001
        corporation_2_id = 2002
        alliance = EsiContactAllianceFactory(contact_id=3001, standing=-5)
        corporation_1 = EsiContactCorporationFactory(
            contact_id=corporation_1_id, standing=-5
        )
        corporation_2 = EsiContactCorporationFactory(
            contact_id=corporation_2_id, standing=5
        )
        pook.get(
            make_esi_url(f"corporations/{corporation_1_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "alliance_id": alliance.contact_id,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
            persist=True,
        )
        pook.get(
            make_esi_url(f"corporations/{corporation_2_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "alliance_id": alliance.contact_id,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
            persist=True,
        )
        all_contacts = [alliance, corporation_1, corporation_2]
        contacts_1 = EsiContactsContainer.from_esi_contacts(all_contacts)
        contacts_2 = EsiContactsContainer.from_esi_contacts(all_contacts)

        # when
        contacts_1.prune(unmask_war_targets=True, compress_contacts=True)
        contacts_2.prune(unmask_war_targets=True, compress_contacts=False)

        # then
        got = contacts_1.contacts()
        want = {alliance, corporation_2}
        self.assertSetEqual(got, want)
        self.assertSetEqual(contacts_2.contacts(), set(all_contacts))

    @pook.on
    def test_should_remove_neutral_characters_when_their_corporation_and_alliance_are_not_contacts(
        self,
    ):
        # given
        corporation = EsiContactCorporationFactory(contact_id=2001, standing=-5)
        character_1 = EsiContactCharacterFactory(contact_id=1001, standing=0)
        character_2 = EsiContactCharacterFactory(contact_id=1011, standing=0)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "character_id": character_1.contact_id,
                    "corporation_id": corporation.contact_id,
                },
                {
                    "character_id": character_2.contact_id,
                    "corporation_id": 2011,
                },
            ],
            persist=True,
        )
        pook.get(
            make_esi_url(f"corporations/{corporation.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
            persist=True,
        )
        all_contacts = [corporation, character_1, character_2]
        contacts_1 = EsiContactsContainer.from_esi_contacts(all_contacts)
        contacts_2 = EsiContactsContainer.from_esi_contacts(all_contacts)

        # when
        contacts_1.prune(unmask_war_targets=True, compress_contacts=True)
        contacts_2.prune(unmask_war_targets=True, compress_contacts=False)

        # then
        got = contacts_1.contacts()
        want = {corporation, character_1}
        self.assertSetEqual(got, want)
        self.assertSetEqual(contacts_2.contacts(), set(all_contacts))

    @pook.on
    def test_should_remove_neutral_corporations_when_their_alliances_are_not_contacts(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(contact_id=3001, standing=-5)
        corporation_1 = EsiContactCorporationFactory(contact_id=2001, standing=0)
        corporation_2 = EsiContactCorporationFactory(contact_id=2002, standing=0)
        pook.get(
            make_esi_url(f"corporations/{corporation_1.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "alliance_id": alliance.contact_id,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
            persist=True,
        )
        pook.get(
            make_esi_url(f"corporations/{corporation_2.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
            persist=True,
        )
        all_contacts = [alliance, corporation_1, corporation_2]
        contacts_1 = EsiContactsContainer.from_esi_contacts(all_contacts)
        contacts_2 = EsiContactsContainer.from_esi_contacts(all_contacts)

        # when
        contacts_1.prune(unmask_war_targets=True, compress_contacts=True)
        contacts_2.prune(unmask_war_targets=True, compress_contacts=False)

        # then
        got = contacts_1.contacts()

        want = {alliance, corporation_1}
        self.assertSetEqual(got, want)
        self.assertSetEqual(contacts_2.contacts(), set(all_contacts))

    @pook.on
    def test_should_remove_corporations_when_they_shadow_a_war_target(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(
            contact_id=3001, standing=-10, is_war_target=True
        )
        corporation = EsiContactCorporationFactory(contact_id=2001, standing=0)
        pook.get(
            make_esi_url(f"corporations/{corporation.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "alliance_id": alliance.contact_id,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
        )
        contacts = EsiContactsContainer.from_esi_contacts([alliance, corporation])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()

        want = {alliance}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_not_remove_corporations_when_they_shadow_a_war_target(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(
            contact_id=3001, standing=-10, is_war_target=True
        )
        corporation = EsiContactCorporationFactory(contact_id=2001, standing=0)
        pook.get(
            make_esi_url(f"corporations/{corporation.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "alliance_id": alliance.contact_id,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
        )
        contacts = EsiContactsContainer.from_esi_contacts([alliance, corporation])

        # when
        contacts.prune(unmask_war_targets=False, compress_contacts=True)

        # then
        got = contacts.contacts()

        want = {alliance, corporation}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_remove_characters_when_they_shadow_a_war_target_corporation(
        self,
    ):
        # given
        corporation = EsiContactCorporationFactory(
            contact_id=2001, standing=-10, is_war_target=True
        )
        character = EsiContactCharacterFactory(standing=5)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "character_id": character.contact_id,
                    "corporation_id": corporation.contact_id,
                },
            ],
        )
        pook.get(
            make_esi_url(f"corporations/{corporation.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
        )
        contacts = EsiContactsContainer.from_esi_contacts([corporation, character])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = {corporation}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_not_remove_characters_when_they_shadow_a_war_target_corporation(
        self,
    ):
        # given
        corporation = EsiContactCorporationFactory(
            contact_id=2001, standing=-10, is_war_target=True
        )
        character = EsiContactCharacterFactory(standing=5)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "character_id": character.contact_id,
                    "corporation_id": corporation.contact_id,
                },
            ],
        )
        pook.get(
            make_esi_url(f"corporations/{corporation.contact_id}"),
            reply=HTTPStatus.OK,
            response_json={
                "ceo_id": 90000001,
                "creator_id": 90000001,
                "member_count": 42,
                "name": "name",
                "tax_rate": 0,
                "ticker": "ticker",
            },
        )
        contacts = EsiContactsContainer.from_esi_contacts([corporation, character])

        # when
        contacts.prune(unmask_war_targets=False, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = {corporation, character}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_remove_characters_when_they_shadow_a_war_target_alliance(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(
            contact_id=3001, standing=-10, is_war_target=True
        )
        character = EsiContactCharacterFactory(standing=5)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "alliance_id": alliance.contact_id,
                    "character_id": character.contact_id,
                    "corporation_id": 2001,
                },
            ],
        )
        contacts = EsiContactsContainer.from_esi_contacts([alliance, character])

        # when
        contacts.prune(unmask_war_targets=True, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = {alliance}
        self.assertSetEqual(got, want)

    @pook.on
    def test_should_not_remove_characters_when_they_shadow_a_war_target_alliance(
        self,
    ):
        # given
        alliance = EsiContactAllianceFactory(
            contact_id=3001, standing=-10, is_war_target=True
        )
        character = EsiContactCharacterFactory(standing=5)
        pook.post(
            make_esi_url("characters/affiliation"),
            reply=HTTPStatus.OK,
            response_json=[
                {
                    "alliance_id": alliance.contact_id,
                    "character_id": character.contact_id,
                    "corporation_id": 2001,
                },
            ],
        )
        contacts = EsiContactsContainer.from_esi_contacts([alliance, character])

        # when
        contacts.prune(unmask_war_targets=False, compress_contacts=True)

        # then
        got = contacts.contacts()
        want = {alliance, character}
        self.assertSetEqual(got, want)
