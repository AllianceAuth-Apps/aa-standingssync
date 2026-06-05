from django.template import Context, Template
from django.test import TestCase
from eveuniverse.models import EveEntity
from eveuniverse.tests.testdata.factories_2 import (
    EveEntityAllianceFactory,
    EveEntityCharacterFactory,
    EveEntityCorporationFactory,
)


class TestTemplateTags(TestCase):
    def test_should_render_alliance_war_participant(self):
        # given
        template = Template("""
            {% load standingssync %}
            {% war_participant obj %}
            """)
        params = [
            (EveEntityAllianceFactory(), "alliance"),
            (EveEntityCorporationFactory(), "corporation"),
            (EveEntityCharacterFactory(), ""),
        ]
        for obj, expected in params:
            with self.subTest(category=obj.category):
                context = Context({"obj": obj})
                # when
                result = template.render(context)
                # then
                self.assertIn(str(obj.id), result)
                self.assertIn(expected, result)

    def test_should_display_no_data_for_empty_obj(self):
        # given
        template = Template("""
            {% load standingssync %}
            {% war_participant obj %}
            """)
        obj = EveEntity.objects.create(id=1)
        context = Context({"obj": obj})
        # when
        result = template.render(context)
        # then
        self.assertIn("[NO DATA]", result)

    def test_should_display_no_data_for_invalid_obj(self):
        # given
        template = Template("""
            {% load standingssync %}
            {% war_participant obj %}
            """)
        context = Context({"obj": "abc"})
        # when
        result = template.render(context)
        # then
        self.assertIn("[NO DATA]", result)
