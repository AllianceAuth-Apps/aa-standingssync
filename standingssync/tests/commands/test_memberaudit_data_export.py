from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from app_utils.testing import NoSocketsTestCase

from standingssync.management.commands import standingssync_calc_war_ids
from standingssync.tests.factories import EveWarEmptyFactory, EveWarFactory


class TestCalcWarIds_Command(NoSocketsTestCase):
    def test_should_return_id_in_output(self):
        # given
        EveWarFactory(id=42)
        out = StringIO()

        # when
        call_command("standingssync_calc_war_ids", stdout=out)

        # then
        self.assertIn("42", out.getvalue())

    def test_should_allow_custom_number_of_special_ids(self):
        # given
        EveWarFactory(id=42)
        out = StringIO()

        # when
        call_command(
            "standingssync_calc_war_ids", "--max-special-ids", "30", stdout=out
        )

        # then
        self.assertIn("42", out.getvalue())

    def test_should_abort_when_no_wars_found(self):
        # when/then
        with self.assertRaises(CommandError):
            call_command("standingssync_calc_war_ids", stdout=StringIO())

    def test_should_abort_when_some_wars_are_empty(self):
        # given
        EveWarFactory()
        EveWarEmptyFactory()
        # when/then
        with self.assertRaises(CommandError):
            call_command("standingssync_calc_war_ids", stdout=StringIO())


class TestCalcWarIds_Logic(NoSocketsTestCase):
    def test_return_ids_and_min(self):
        # given
        EveWarFactory(id=1, is_finished=True)
        EveWarFactory(id=2)
        EveWarFactory(id=3)
        EveWarFactory(id=4, is_finished=True)
        EveWarFactory(id=5)
        EveWarFactory(id=6)

        # when
        got_ids, got_min = standingssync_calc_war_ids._calc_war_ids(2)

        # then
        self.assertCountEqual(got_ids, [2, 3])
        self.assertEqual(got_min, 5)

    def test_return_ids_and_min_2(self):
        # given
        EveWarFactory(id=1)

        # when
        got_ids, got_min = standingssync_calc_war_ids._calc_war_ids(2)

        # then
        self.assertCountEqual(got_ids, [1])
        self.assertEqual(got_min, 2)
