"""Managers for standingssync."""

# pylint: disable = redefined-builtin, missing-class-docstring

import datetime as dt
from collections import defaultdict
from typing import Any, Dict

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Case, Max, Q, Value, When
from django.utils.timezone import now
from eveuniverse.models import EveEntity

from allianceauth.eveonline.models import EveAllianceInfo
from allianceauth.services.hooks import get_extension_logger

from standingssync.core import esi_api

logger = get_extension_logger(__name__)


class EveContactQuerySet(models.QuerySet):
    def grouped_by_standing(self) -> Dict[int, Any]:
        """Group alliance contacts by standing and convert into sorted dict."""
        contacts_by_standing = defaultdict(set)
        for contact in self.all():
            contacts_by_standing[contact.standing].add(contact)
        return dict(sorted(contacts_by_standing.items()))


class EveContactManagerBase(models.Manager):
    pass


EveContactManager = EveContactManagerBase.from_queryset(EveContactQuerySet)


class EveWarQuerySet(models.QuerySet):
    def annotate_state(self) -> models.QuerySet:
        """Add state field to queryset."""
        from standingssync.models import EveWar

        return self.annotate(
            state=Case(
                When(started__gt=now(), then=Value(EveWar.State.PENDING.value)),
                When(
                    started__lte=now(),
                    finished__isnull=True,
                    then=Value(EveWar.State.ONGOING.value),
                ),
                When(
                    started__lte=now(),
                    finished__gt=now(),
                    retracted__isnull=False,
                    then=Value(EveWar.State.RETRACTED.value),
                ),
                When(
                    started__lte=now(),
                    finished__gt=now(),
                    retracted__isnull=True,
                    then=Value(EveWar.State.CONCLUDING.value),
                ),
                When(
                    finished__isnull=False,
                    then=Value(EveWar.State.FINISHED.value),
                ),
                default=Value(EveWar.State.UNKNOWN.value),
            )
        )

    def annotate_is_active(self) -> models.QuerySet:
        """Add is_active field to queryset. Requires prior annotation of state."""
        return self.annotate(
            is_active=Case(
                When(state__in=self.model.State.active_states(), then=Value(True)),
                default=Value(False),
            )
        )

    def current_wars(self) -> models.QuerySet:
        """Add filter for current wars.

        This includes wars that are about to start,
        active wars and wars that ended recently.
        """
        cutoff = now() - dt.timedelta(hours=24)
        qs = self.filter(declared__lt=now())
        return (
            qs.filter(finished__gt=cutoff) | qs.filter(finished__isnull=True)
        ).distinct()

    def active_wars(self) -> models.QuerySet:
        """Add filter for active wars."""
        qs = self.filter(
            Q(started__lt=now()) & (Q(finished__gt=now()) | Q(finished__isnull=True))
        ).distinct()
        return qs

    def alliance_wars(self, alliance: EveAllianceInfo) -> models.QuerySet:
        """Include wars where a given alliance is participating only."""
        qs = (
            self.filter(
                Q(aggressor_id=alliance.alliance_id)
                | Q(defender_id=alliance.alliance_id)
                | Q(allies__id=alliance.alliance_id)
            )
        ).distinct()
        return qs

    def needs_update(self) -> models.QuerySet:
        """Filter for wars that need to be updated."""
        threshold = now() - dt.timedelta(hours=1)
        qs = self.filter(
            Q(finished__isnull=True)
            & (
                Q(aggressor__isnull=True)  # empty wars
                | Q(last_modified__lt=threshold)  # stale active war
            )
        ).distinct()
        return qs

    def non_empty(self) -> models.QuerySet:
        """Filter non-empty war objects."""
        return self.filter(
            aggressor__isnull=False, declared__isnull=False, defender__isnull=False
        )


class EveWarManagerBase(models.Manager):
    def alliance_war_targets(
        self, alliance: EveAllianceInfo
    ) -> models.QuerySet[EveEntity]:
        """Identify current war targets of on alliance."""
        war_target_ids = set()
        for war in self.alliance_wars(alliance).active_wars():
            # case 1 alliance is aggressor
            if war.aggressor_id == alliance.alliance_id:
                war_target_ids.add(war.defender_id)
                war_target_ids |= set(war.allies.values_list("id", flat=True))

            # case 2 alliance is defender
            if war.defender_id == alliance.alliance_id:
                war_target_ids.add(war.aggressor_id)

            # case 3 alliance is ally
            if war.allies.filter(id=alliance.alliance_id).exists():
                war_target_ids.add(war.aggressor_id)

        return EveEntity.objects.filter(id__in=war_target_ids)

    def sync_known_wars(self):
        """Synchronizes which wars are known. Wars are known if they have an ID."""
        from standingssync.models import EveWar

        min_war_id = self.aggregate(Max("id", default=0)).get("id__max") or 0
        war_ids = esi_api.fetch_war_ids(min_war_id)
        known_ids = set(self.values_list("id", flat=True))
        unknown_ids = war_ids - known_ids
        if not unknown_ids:
            logger.info("No new wars")
            return

        wars = (EveWar(id=war_id) for war_id in unknown_ids)
        EveWar.objects.bulk_create(wars, batch_size=500, ignore_conflicts=True)
        logger.info("Created %d new wars", len(unknown_ids))


EveWarManager = EveWarManagerBase.from_queryset(EveWarQuerySet)


class SyncManagerManager(models.Manager):
    def fetch_for_user(self, user: User) -> Any:
        """Fetch sync manager for given user. Return None if no match is found."""
        if not user.profile.main_character:
            return None

        try:
            alliance = EveAllianceInfo.objects.get(
                alliance_id=user.profile.main_character.alliance_id
            )
        except EveAllianceInfo.DoesNotExist:
            return None

        try:
            return self.get(alliance=alliance)
        except self.model.DoesNotExist:
            return None
