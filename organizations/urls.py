from django.urls import path

from . import views

app_name = "organizations"

urlpatterns = [
    path(
        "",
        views.organization_list,
        name="organization_list",
    ),
    path(
        "<int:organization_pk>/members/",
        views.organization_members,
        name="organization_members",
    ),
]
