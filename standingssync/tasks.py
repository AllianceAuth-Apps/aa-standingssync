"""Tasks for standingssync."""

import time

from celery import Task, shared_task

from django.db.models import QuerySet
from esi.decorators import rate_limit_retry_task
from eveuniverse.core.esitools import is_esi_online

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from standingssync.app_settings import STANDINGSSYNC_ADD_WAR_TARGETS
from standingssync.models import EveWar, SyncedCharacter, SyncManager

logger = get_extension_logger(__name__)


DEFAULT_TASK_PRIORITY = 6
ONCE_TIMEOUT = 1000  # once timeout determined by max rate limit reset + contingency
SYNC_WAR_DELAY = 0.55  # delay in seconds for fetching each war with contigency.


@shared_task(base=QueueOnce)
def run_regular_sync():
    """update all wars, managers and related characters if needed"""
    if not is_esi_online():
        logger.warning("ESI is not online. aborting")
        return

    if STANDINGSSYNC_ADD_WAR_TARGETS:
        sync_all_wars.apply_async(priority=DEFAULT_TASK_PRIORITY)

    for sync_manager_pk in SyncManager.objects.values_list("pk", flat=True):
        run_manager_sync.apply_async(
            args=[sync_manager_pk], priority=DEFAULT_TASK_PRIORITY
        )


@shared_task(base=QueueOnce, bind=True)
@rate_limit_retry_task
def run_manager_sync(_self, manager_pk: int, force_update: bool = False):
    """updates contacts for given manager and related characters

    Args:
    - manage_pk: primary key of sync manager to run sync for
    - force_update: will force update of manager even if not needed
    """
    sync_manager = SyncManager.objects.get(pk=manager_pk)
    sync_manager.run_sync(force_update)
    sync_characters = sync_manager.synced_characters.values_list("pk", flat=True)
    for character_pk in sync_characters:
        run_character_sync.apply_async(
            kwargs={"sync_char_pk": character_pk}, priority=DEFAULT_TASK_PRIORITY
        )


@shared_task(base=QueueOnce, bind=True)
@rate_limit_retry_task
def run_character_sync(_self, sync_char_pk: int):
    """updates in-game contacts for given character

    Args:
    - sync_char_pk: primary key of sync character to run sync for
    """
    synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    synced_character.run_sync()


@shared_task
def character_delete_all_contacts(sync_char_pk: int):
    """Delete contacts of this character."""
    synced_character = SyncedCharacter.objects.get(pk=sync_char_pk)
    synced_character.delete_all_contacts()


@shared_task(base=QueueOnce, bind=True, once={"timeout": ONCE_TIMEOUT})
@rate_limit_retry_task
def sync_all_wars(_self):
    """Sync all wars from ESI."""
    EveWar.objects.sync_known_wars()
    if EveWar.objects.needs_update().exists():
        sync_stale_war.apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(
    base=QueueOnce, bind=True, max_retries=None, once={"timeout": ONCE_TIMEOUT}
)
@rate_limit_retry_task
def sync_stale_war(self: Task):
    """Update the newest stale war from ESI."""
    wars_to_update: QuerySet[EveWar] = EveWar.objects.needs_update()
    war: EveWar = wars_to_update.order_by("-id").first()
    if not war:
        return

    logger.info(
        "%d stale wars need to be updated. Starting to update war ID %d",
        wars_to_update.count(),
        war.id,
    )
    war.update_from_esi()
    logger.info("Updated war with ID %d", war.id)

    delay = SYNC_WAR_DELAY
    logger.debug("Waiting %f seconds for next rate limit slot", delay)
    time.sleep(delay)

    if EveWar.objects.needs_update().exists():
        self.retry(countdown=0.01)
