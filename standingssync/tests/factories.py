"""Model test factories."""

import datetime as dt
import urllib.parse
from typing import Generic, TypeVar

import factory
import factory.fuzzy

from django.utils.timezone import now
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
)

from app_utils.testdata_factories import (
    EveAllianceInfoFactory,
    EveCharacterFactory,
    UserMainFactory,
)
from app_utils.testing import add_character_to_user

from standingssync.core.esi_contacts import EsiContact, EsiContactLabel
from standingssync.models import EveContact, EveWar, SyncedCharacter, SyncManager

T = TypeVar("T")
_BASE_URL = "https://esi.evetech.net/"


def make_esi_url(path: str) -> str:
    if path.startswith("/"):
        raise ValueError("path can not start with a slash")
    if path.endswith("/"):
        raise ValueError("path can not end with a slash")

    url = urllib.parse.urljoin(_BASE_URL, "/latest/" + path + "/")
    return url


class BaseMetaFactory(Generic[T], factory.base.FactoryMetaClass):
    def __call__(cls, *args, **kwargs) -> T:
        return super().__call__(*args, **kwargs)


class EveWarFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveWar]
):
    class Meta:
        model = EveWar

    id = factory.Sequence(lambda n: 1 + n)
    aggressor = factory.SubFactory(EveEntityAllianceFactory)
    declared = factory.fuzzy.FuzzyDateTime(
        now() - dt.timedelta(days=3), end_dt=now() - dt.timedelta(days=2)
    )
    defender = factory.SubFactory(EveEntityAllianceFactory)
    is_mutual = False
    is_open_for_allies = True
    started = factory.LazyAttribute(lambda obj: obj.declared + dt.timedelta(hours=24))
    retracted = None

    @factory.lazy_attribute
    def finished(self):
        return self.retracted + dt.timedelta(hours=24) if self.retracted else None

    @factory.post_generation
    def allies(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            for ally in extracted:
                self.allies.add(ally)  # type: ignore


class UserMainManagerFactory(UserMainFactory):
    main_character__scopes = ["esi-alliances.read_contacts.v1"]
    permissions__ = ["standingssync.add_syncmanager"]


class UserMainSyncerFactory(UserMainFactory):
    main_character__scopes = [
        "esi-characters.read_contacts.v1",
        "esi-characters.write_contacts.v1",
    ]
    permissions__ = ["standingssync.add_syncedcharacter"]


class SyncManagerFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[SyncManager]
):
    class Meta:
        model = SyncManager

    class Params:
        user = factory.SubFactory(UserMainManagerFactory)

    version_hash = factory.fuzzy.FuzzyText(length=32)

    @factory.lazy_attribute
    def alliance(self):
        return EveAllianceInfoFactory(
            alliance_id=self.user.profile.main_character.alliance_id  # type: ignore
        )

    @factory.lazy_attribute
    def character_ownership(self):
        return self.user.profile.main_character.character_ownership  # type: ignore

    @factory.post_generation
    def create_eve_entities(self, create, extracted, **kwargs):
        if not create:
            return
        EveEntityAllianceFactory(
            id=self.alliance.alliance_id, name=self.alliance.alliance_name  # type: ignore
        )


class SyncedCharacterFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[SyncedCharacter]
):
    class Meta:
        model = SyncedCharacter

    class Params:
        user = None

    manager = factory.SubFactory(SyncManagerFactory)

    @factory.lazy_attribute
    def character_ownership(self):
        if not self.user:
            character = EveCharacterFactory(corporation__alliance=self.manager.alliance)
            user = UserMainSyncerFactory(main_character__character=character)
            return user.profile.main_character.character_ownership  # type: ignore

        return self.user.profile.main_character.character_ownership  # type: ignore

    @factory.post_generation
    def create_alt(self, create, extracted, **kwargs):
        if not create or extracted is not True:
            return

        alt = EveCharacterFactory()
        add_character_to_user(self.character_ownership.user, alt)


class EveContactFactory(
    factory.django.DjangoModelFactory, metaclass=BaseMetaFactory[EveContact]
):
    class Meta:
        model = EveContact

    manager = factory.SubFactory(SyncManagerFactory)
    eve_entity = factory.SubFactory(EveEntityCharacterFactory)
    standing = factory.LazyAttribute(lambda o: -10 if o.is_war_target else 5)
    is_war_target = False


class EsiContactDictFactory(factory.base.DictFactory, metaclass=BaseMetaFactory[dict]):
    contact_id = factory.fuzzy.FuzzyInteger(90_000, 99_999)
    contact_type = factory.fuzzy.FuzzyChoice(["character", "corporation", "alliance"])
    standing = factory.fuzzy.FuzzyFloat(-10.0, 10.0)


class EsiLabelDictFactory(factory.base.DictFactory, metaclass=BaseMetaFactory[dict]):
    label_id = factory.fuzzy.FuzzyInteger(1, 9_999)
    label_name = factory.Faker("word")


class EsiContactFactory(factory.base.Factory, metaclass=BaseMetaFactory[EsiContact]):
    class Meta:
        model = EsiContact

    contact_id = factory.fuzzy.FuzzyInteger(90_000, 99_999)
    contact_type = factory.fuzzy.FuzzyChoice(list(EsiContact.Category))
    standing = factory.fuzzy.FuzzyFloat(-10.0, 10.0)


class EsiContactAllianceFactory(
    factory.base.Factory, metaclass=BaseMetaFactory[EsiContact]
):
    class Meta:
        model = EsiContact

    contact_id = factory.Sequence(lambda n: 99_909_001 + n)
    contact_type = EsiContact.Category.ALLIANCE
    standing = factory.fuzzy.FuzzyFloat(-10.0, 10.0)


class EsiContactCharacterFactory(
    factory.base.Factory, metaclass=BaseMetaFactory[EsiContact]
):
    class Meta:
        model = EsiContact

    contact_id = factory.Sequence(lambda n: 90_909_001 + n)
    contact_type = EsiContact.Category.CHARACTER
    standing = factory.fuzzy.FuzzyFloat(-10.0, 10.0)


class EsiContactCorporationFactory(
    factory.base.Factory, metaclass=BaseMetaFactory[EsiContact]
):
    class Meta:
        model = EsiContact

    contact_id = factory.Sequence(lambda n: 97_909_001 + n)
    contact_type = EsiContact.Category.CORPORATION
    standing = factory.fuzzy.FuzzyFloat(-10.0, 10.0)


class EsiContactLabelFactory(
    factory.base.Factory, metaclass=BaseMetaFactory[EsiContactLabel]
):
    class Meta:
        model = EsiContactLabel

    id = factory.fuzzy.FuzzyInteger(1, 9_999)
    name = factory.Faker("word")
