from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("templates/", views.template_list, name="template_list"),
    path("templates/upload/", views.template_upload, name="template_upload"),

    path("documents/", views.document_list, name="document_list"),
    path("documents/create/", views.document_create, name="document_create"),
    path("documents/<int:pk>/fill/", views.document_fill, name="document_fill"),
    path("documents/<int:pk>/render/", views.document_render_docx, name="document_render_docx"),
]