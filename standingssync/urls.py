"""Routes for standingssync."""

from django.urls import path

from standingssync import views

app_name = "standingssync"

urlpatterns = [
    path("", views.index, name="index"),
    path("characters", views.characters, name="characters"),
    path("add-character", views.add_character, name="add_character"),
    path(
        "remove-character/<int:alt_pk>", views.remove_character, name="remove_character"
    ),
    path(
        "add-alliance-manager", views.add_alliance_manager, name="add_alliance_manager"
    ),
    path("wars", views.wars, name="wars"),
    path("admin-update-wars", views.admin_update_wars, name="admin_update_wars"),
]
