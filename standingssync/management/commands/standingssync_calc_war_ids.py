from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from standingssync.models import EveWar


class Command(BaseCommand):
    help = (
        "Calculates the minimum and special war IDs "
        "to reduce how many wars need to be fetched from ESI."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-special-ids",
            default=20,
            type=int,
            help="Maximum number of special unfinished IDs to compile",
        )
        parser.add_argument(
            "--disable-checks",
            action="store_true",
            help="When enabled will check if local data is sufficient for calc",
        )

    def handle(self, *args, **options):
        wars: QuerySet[EveWar] = EveWar.objects.non_empty()
        total_wars = wars.count()
        if not options["disable_checks"]:
            if not total_wars:
                raise CommandError(
                    "No non-stale wars found in database. "
                    "Please update wars from ESI before running this command."
                )

            updated: float = EveWar.objects.updated_percentage()
            if updated < 1:
                raise CommandError(
                    f"Only {updated * 100:.0f} wars are updated. "
                    "Please finished updating all wars from ESI before running this command."
                )

        self.stdout.write(f"Wars in database: {total_wars}")

        special_unfinished_war_ids, min_unfinished_war_id = _calc_war_ids(
            options["max_special_ids"]
        )
        remaining_count = wars.filter(id__gte=min_unfinished_war_id).count() + len(
            special_unfinished_war_ids
        )

        self.stdout.write("Calculated new war ID values for settings are:")
        self.stdout.write(
            f"STANDINGSSYNC_UNFINISHED_WARS_MINIMUM_ID = {min_unfinished_war_id}"
        )
        self.stdout.write(
            f"STANDINGSSYNC_UNFINISHED_WARS_EXCEPTION_IDS = {special_unfinished_war_ids}"
        )
        self.stdout.write(f"Total wars to fetch: {remaining_count}")


def _calc_war_ids(max_special_ids: int):
    unfinished_war_ids = list(
        EveWar.objects.non_empty()
        .filter(finished__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)
    )
    special_unfinished_war_ids = unfinished_war_ids[:max_special_ids]
    try:
        min_unfinished_war_id = unfinished_war_ids[max_special_ids]
    except IndexError:
        min_unfinished_war_id = max(special_unfinished_war_ids) + 1
    return special_unfinished_war_ids, min_unfinished_war_id
