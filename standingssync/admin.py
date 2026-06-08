"""Admin site for standingssync."""

# pylint: disable = missing-class-docstring, missing-function-docstring

from django.contrib import admin
from django.db.models import Prefetch
from django.utils.html import format_html
from eveuniverse.models import EveEntity

from standingssync import tasks
from standingssync.models import EveContact, EveWar, SyncedCharacter, SyncManager


@admin.register(EveContact)
class EveContactAdmin(admin.ModelAdmin):
    list_display = (
        "_entity_name",
        "_entity_category",
        "standing",
        "is_war_target",
        "manager",
    )
    list_display_links = None
    ordering = ("eve_entity__name",)
    list_select_related = True
    list_filter = ("manager", "eve_entity__category", "is_war_target")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "eve_entity",
            "manager",
            "manager__alliance",
            "manager__character_ownership__character",
        )

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, *args, **kwargs) -> bool:
        return False

    @admin.display(ordering="eve_entity_id")
    def _entity_name(self, obj):
        return obj.eve_entity.name

    @admin.display(ordering="eve_entity__category")
    def _entity_category(self, obj):
        return obj.eve_entity.get_category_display()


class EveWarActiveWarsListFilter(admin.SimpleListFilter):
    title = "active wars"
    parameter_name = "active_wars"

    def lookups(self, request, model_admin):
        return (
            ("yes", "yes"),
            ("no", "no"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_active=True)
        if self.value() == "no":
            return queryset.filter(is_active=False)
        return queryset


class EveWarEmptyWarsListFilter(admin.SimpleListFilter):
    title = "empty wars"
    parameter_name = "empty_wars"

    def lookups(self, request, model_admin):
        return (
            ("yes", "yes"),
            ("no", "no"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.empty()
        if self.value() == "no":
            return queryset.non_empty()
        return queryset


class EveWarStateListFilter(admin.SimpleListFilter):
    title = "state"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return EveWar.State.choices

    def queryset(self, request, queryset):
        if value := self.value():
            return queryset.filter(state=value)

        return queryset


class AlliesInline(admin.TabularInline):
    model = EveWar.allies.through


@admin.register(EveWar)
class EveWarAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "_state",
        "aggressor",
        "defender",
        "declared",
        "started",
        "retracted",
        "finished",
    )
    ordering = ("-id",)
    list_filter = (
        "declared",
        EveWarActiveWarsListFilter,
        EveWarStateListFilter,
        EveWarEmptyWarsListFilter,
    )
    search_fields = ("aggressor__name", "defender__name", "allies__name")
    inlines = (AlliesInline,)

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_change_permission(self, *args, **kwargs) -> bool:
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request).annotate_state().annotate_is_active()
        return qs.prefetch_related(
            Prefetch("allies", queryset=EveEntity.objects.select_related())
        ).annotate_state()

    def _state(self, obj) -> str:
        return EveWar.State(obj.state).label

    # def _allies(self, obj):
    #     allies = sorted([str(ally) for ally in obj.allies.all()])
    #     return format_html("<br>".join(allies)) if allies else "-"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        p = round(EveWar.objects.updated_percentage() * 100, 1)
        extra_context["completion_p"] = p
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(SyncedCharacter)
class SyncedCharacterAdmin(admin.ModelAdmin):
    list_display = (
        "_user",
        "_character_name",
        "_has_war_targets_label",
        "_is_fresh",
        "last_sync_at",
        "manager",
    )
    list_filter = (
        "manager",
        "last_sync_at",
        ("character_ownership__user", admin.RelatedOnlyFieldListFilter),
    )
    actions = ["sync_characters", "delete_all_contacts"]
    list_display_links = None

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            "manager__alliance",
            "manager__character_ownership__character",
            "character_ownership__character",
            "character_ownership__user",
        )

    def has_add_permission(self, request):
        return False

    @admin.display(ordering="character_ownership__user")
    def _user(self, obj):
        return obj.character_ownership.user

    @admin.display(ordering="character_ownership__character__character_name")
    def _character_name(self, obj):
        return str(obj)

    @admin.display(boolean=True, description="Has WT label")
    def _has_war_targets_label(self, obj):
        return obj.has_war_targets_label

    @admin.display(boolean=True)
    def _is_fresh(self, obj):
        return obj.is_sync_fresh

    @admin.display(description="Start sync for selected synced characters")
    def sync_characters(self, request, queryset):
        names = []
        for obj in queryset:
            tasks.run_character_sync.delay(obj.pk)
            names.append(str(obj))
        names_text = ", ".join(names)
        self.message_user(request, f"Started normal syncing for: {names_text}")

    @admin.display(description="Delete all contacts of selected synced characters")
    def delete_all_contacts(self, request, queryset):
        names = []
        for obj in queryset:
            tasks.character_delete_all_contacts.delay(obj.pk)
            names.append(str(obj))
        names_text = ", ".join(names)
        self.message_user(request, f"Started deleting contacts for: {names_text}")


@admin.register(SyncManager)
class SyncManagerAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("admin/custom_admin.css",)}

    list_display = (
        "_alliance_name",
        "_contacts_count",
        "_filters",
        "_characters_count",
        "_user",
        "_character_name",
        "_is_fresh",
        "last_sync_at",
    )
    list_filter = (("character_ownership__user", admin.RelatedOnlyFieldListFilter),)
    actions = ["start_sync_managers"]
    readonly_fields = (
        "alliance",
        "character_ownership",
        "version_hash",
        "last_sync_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": ("alliance", "character_ownership", "last_sync_at"),
            },
        ),
        (
            "Contact filters",
            {
                "fields": (
                    "compress_contacts",
                    "exclude_character_contacts",
                    "exclude_negative_standings",
                    "exclude_positive_standings",
                ),
                "description": (
                    "Changes to filters will be applied at the next sync. "
                    "Filters do not effect war target contacts."
                ),
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("alliance", "character_ownership__character")

    def has_add_permission(self, request):
        return False

    @admin.display(ordering="character_ownership__user__username", description="User")
    def _user(self, obj):
        return obj.character_ownership.user if obj.character_ownership else None

    @admin.display(
        ordering="character_ownership__character__character_name",
        description="Character",
    )
    def _character_name(self, obj):
        try:
            return obj.character.character_name
        except ValueError:
            return ""

    @admin.display(ordering="alliance__alliance_name", description="Alliance")
    def _alliance_name(self, obj):
        return obj.alliance.alliance_name

    @admin.display(description="Contacts")
    def _contacts_count(self, obj):
        return f"{obj.contacts.count():,}"

    @admin.display(description="Filters")
    def _filters(self, obj):
        names = [
            "compress_contacts",
            "exclude_character_contacts",
            "exclude_negative_standings",
            "exclude_positive_standings",
        ]
        parts = []
        for n in names:
            value = getattr(obj, n)
            parts.append(f"{n} = {value}")
        return format_html("<br>".join(parts))

    @admin.display(description="Characters")
    def _characters_count(self, obj):
        return f"{obj.synced_characters.count():,}"

    @admin.display(boolean=True)
    def _is_fresh(self, obj):
        return obj.is_sync_fresh

    @admin.display(description="Start sync for selected managers")
    def start_sync_managers(self, request, queryset):
        names = []
        for obj in queryset:
            tasks.run_manager_sync.delay(manager_pk=obj.pk, force_update=True)
            names.append(str(obj))
        text = f"Started syncing for: {', '.join(names)} "
        self.message_user(request, text)
