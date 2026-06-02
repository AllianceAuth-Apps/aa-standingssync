"""Tasks for standingssync."""

from celery import shared_task

from esi.decorators import rate_limit_retry_task
from eveuniverse.core.esitools import is_esi_online
from eveuniverse.tasks import update_unresolved_eve_entities

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from .app_settings import STANDINGSSYNC_ADD_WAR_TARGETS
from .models import EveWar, SyncedCharacter, SyncManager

logger = get_extension_logger(__name__)


DEFAULT_TASK_PRIORITY = 6


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


@shared_task(base=QueueOnce)
def sync_all_wars():
    """Sync all wars from ESI."""
    war_ids = EveWar.objects.fetch_active_war_ids_esi()
    if war_ids:
        logger.info(
            "Updating details for %d active wars from ESI.",
            len(war_ids),
        )
        for war_id in war_ids:
            run_war_sync.apply_async(args=[war_id], priority=DEFAULT_TASK_PRIORITY)

    update_unresolved_eve_entities.apply_async(priority=DEFAULT_TASK_PRIORITY)


@shared_task(base=QueueOnce, bind=True)
@rate_limit_retry_task
def run_war_sync(_self, war_id: int):
    """Sync given war from ESI."""
    EveWar.objects.update_or_create_from_esi(war_id)
