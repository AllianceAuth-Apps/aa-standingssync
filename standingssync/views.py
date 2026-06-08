"""Views for standingssync."""

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from esi.decorators import token_required

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter
from allianceauth.services.hooks import get_extension_logger

from standingssync import __title__, tasks
from standingssync.app_settings import (
    STANDINGSSYNC_ADD_WAR_TARGETS,
    STANDINGSSYNC_CHAR_MIN_STANDING,
    STANDINGSSYNC_REPLACE_CONTACTS,
    STANDINGSSYNC_WAR_TARGETS_LABEL_NAME,
)
from standingssync.constants import MAX_CHARACTER_CONTACTS
from standingssync.models import EveWar, SyncedCharacter, SyncManager

logger = get_extension_logger(__name__)

MY_DATETIME_FORMAT = "Y-M-d H:i"


def common_context(ctx: dict) -> dict:
    """Return common context used by several views."""
    result = {
        "app_title": __title__,
        "page_title": "PLACEHOLDER",
        "DATEFORMAT": MY_DATETIME_FORMAT,
        "STANDINGSSYNC_ADD_WAR_TARGETS": STANDINGSSYNC_ADD_WAR_TARGETS,
    }
    result.update(ctx)
    return result


@login_required
@permission_required("standingssync.add_syncedcharacter")
def index(request):
    """Render index page."""
    return redirect("standingssync:characters")


@login_required
@permission_required("standingssync.add_syncedcharacter")
def characters(request):
    """Render main page."""
    sync_manager: SyncManager = SyncManager.objects.fetch_for_user(request.user)
    synced_characters = []
    if sync_manager:
        qs = sync_manager.synced_characters_for_user(request.user).select_related(
            "character_ownership", "character_ownership__character"
        )
        for synced_character in qs:
            character = synced_character.character
            organization = str(character.corporation_name)
            if character.alliance_ticker:
                organization += f" [{character.alliance_ticker}]"

            errors = []
            if not synced_character.is_sync_fresh:
                errors.append("Sync is outdated.")
            if (
                STANDINGSSYNC_ADD_WAR_TARGETS
                and synced_character.has_war_targets_label is False
            ):
                errors.append(
                    f"Please create a contact label with the name: "
                    f"{STANDINGSSYNC_WAR_TARGETS_LABEL_NAME}"
                )
            synced_characters.append(
                {
                    "id": character.character_id,
                    "name": character.character_name,
                    "portrait_url": character.portrait_url,
                    "organization": organization,
                    "errors": errors,
                    "pk": synced_character.pk,
                }
            )

        alliance = sync_manager.alliance
        alliance_contacts_count = (
            sync_manager.contacts.filter(is_war_target=False).count()  # type: ignore
            if STANDINGSSYNC_REPLACE_CONTACTS
            else None
        )
        alliance_war_targets_count = (
            sync_manager.contacts.filter(is_war_target=True).count()  # type: ignore
            if STANDINGSSYNC_ADD_WAR_TARGETS
            else None
        )

    else:
        alliance = None
        alliance_contacts_count = None
        alliance_war_targets_count = None

    total_contacts = (alliance_contacts_count or 0) + (alliance_war_targets_count or 0)

    context = {
        "page_title": "My Characters",
        "synced_characters": synced_characters,
        "alliance": alliance,
        "has_synced_chars": len(synced_characters) > 0,
        "alliance_contacts_count": alliance_contacts_count,
        "alliance_war_targets_count": alliance_war_targets_count,
        "war_targets_label_name": STANDINGSSYNC_WAR_TARGETS_LABEL_NAME,
        "overflow": total_contacts > MAX_CHARACTER_CONTACTS,
    }

    return render(request, "standingssync/characters.html", common_context(context))


@login_required
@permission_required("standingssync.add_syncmanager")
@token_required(SyncManager.get_esi_scopes())  # type: ignore
def add_alliance_manager(request, token):
    """Add or update sync manager for an alliance."""
    token_char = get_object_or_404(EveCharacter, character_id=token.character_id)
    if not token_char.alliance_id:
        messages.warning(
            request,
            f"Can not add {token_char}, because it is not a member of any alliance.",
        )
    else:
        character_ownership = get_object_or_404(
            CharacterOwnership, user=request.user, character=token_char
        )
        try:
            alliance = EveAllianceInfo.objects.get(alliance_id=token_char.alliance_id)
        except EveAllianceInfo.DoesNotExist:
            alliance = EveAllianceInfo.objects.create_alliance(token_char.alliance_id)
            alliance.save()
        sync_manager, _ = SyncManager.objects.update_or_create(
            alliance=alliance, defaults={"character_ownership": character_ownership}
        )
        tasks.run_manager_sync.delay(sync_manager.pk)
        if STANDINGSSYNC_ADD_WAR_TARGETS:
            tasks.sync_all_wars.delay()
        messages.success(
            request,
            f"{sync_manager.character.character_name} "
            f"set as alliance character for {alliance.alliance_name}. "
            "Started syncing of alliance contacts. ",
        )
    return redirect("standingssync:index")


@login_required
@permission_required("standingssync.add_syncedcharacter")
@token_required(scopes=SyncedCharacter.get_esi_scopes())  # type: ignore
def add_character(request, token):
    """add character to receive alliance contacts"""
    alliance = get_object_or_404(
        EveAllianceInfo, alliance_id=request.user.profile.main_character.alliance_id
    )
    sync_manager = get_object_or_404(SyncManager, alliance=alliance)
    token_char = get_object_or_404(EveCharacter, character_id=token.character_id)
    if token_char.alliance_id == sync_manager.character.alliance_id:
        messages.warning(
            request,
            "Adding alliance members does not make much sense, "
            "since they already have access to alliance contacts.",
        )

    else:
        character_ownership = get_object_or_404(
            CharacterOwnership, user=request.user, character=token_char
        )
        eff_standing = sync_manager.effective_standing_with_character(
            character_ownership.character
        )
        if eff_standing < STANDINGSSYNC_CHAR_MIN_STANDING:
            messages.warning(
                request,
                "Can not activate sync for your "
                f"character {token_char.character_name}, "
                "because it does not have blue standing "
                "with the alliance. "
                f"The standing value is: {eff_standing:.1f}. "
                "Please first obtain blue "
                "standing for your character and then try again.",
            )
        else:
            sync_character, _ = SyncedCharacter.objects.update_or_create(
                character_ownership=character_ownership,
                defaults={"manager": sync_manager},
            )
            tasks.run_character_sync.delay(sync_character.pk)
            messages.success(
                request, f"Sync activated for {token_char.character_name}!"
            )
    return redirect("standingssync:characters")


@login_required
@permission_required("standingssync.add_syncedcharacter")
def remove_character(request, alt_pk):
    """remove character from receiving alliance contacts"""
    alt = get_object_or_404(SyncedCharacter, pk=alt_pk)
    alt_name = alt.character_ownership.character.character_name
    alt.delete()
    messages.success(request, f"Sync deactivated for {alt_name}")
    return redirect("standingssync:characters")


@login_required
@permission_required("standingssync.add_syncedcharacter")
def wars(request):
    """Render wars page."""
    sync_manager = SyncManager.objects.fetch_for_user(request.user)
    all_wars = []
    if sync_manager:
        query = (
            EveWar.objects.current_wars()
            .alliance_wars(alliance=sync_manager.alliance)
            .prefetch_related(Prefetch("allies", to_attr="allies_sorted"))
            .select_related("aggressor", "defender")
            .annotate_state()
            .annotate_is_active()
            .order_by("-started")
        )
        for war in query:
            allies = sorted(list(war.allies_sorted), key=lambda o: o.name)
            all_wars.append(
                {
                    "declared": war.declared,
                    "started": war.started,
                    "finished": war.finished,
                    "aggressor": war.aggressor,
                    "defender": war.defender,
                    "allies": allies,
                    "state": war.state,
                    "is_active": war.is_active,
                }
            )

    context = {
        "page_title": "Current Wars",
        "alliance": "Not configured",
        "wars": all_wars,
        "war_count": "?",
        "active_wars_count": "?",
        "State": EveWar.State,
    }

    if sync_manager:
        context.update(
            {
                "alliance": sync_manager.alliance,
                "war_count": len(all_wars),
                "active_wars_count": sum(1 for obj in all_wars if obj["is_active"]),
            }
        )

    return render(request, "standingssync/wars.html", common_context(context))


@login_required
@staff_member_required
def admin_update_wars(request):
    """Start updating eve wars."""
    wars_count = EveWar.objects.count()
    tasks.sync_all_wars.delay()
    messages.info(
        request,
        (
            f"Started updating approx. {wars_count:,} wars from ESI in the background. "
            "This can take a minute."
        ),
    )
    return redirect("admin:standingssync_evewar_changelist")
