from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("templates/", views.template_list, name="template_list"),
    path("templates/upload/", views.template_upload, name="template_upload"),

    path("documents/", views.document_list, name="document_list"),
    path("documents/create/", views.document_create, name="document_create"),
    path("documents/editor-1/", views.editor_one, name="editor_one"),
    path("documents/<int:pk>/editor/", views.document_editor, name="document_editor"),
    path("documents/<int:pk>/fill/", views.document_fill, name="document_fill"),
    path("documents/<int:pk>/render/", views.document_render_docx, name="document_render_docx"),
    path("documents/<int:pk>/lawvision/", views.document_lawvision_report, name="document_lawvision_report"),
    path("documents/<int:pk>/evidence-bundle/", views.document_evidence_bundle, name="document_evidence_bundle"),

    path("templates/<int:pk>/edit/", views.template_edit, name="template_edit"),
    path("templates/<int:template_pk>/documents/create/", views.document_create_from_template, name="document_create_from_template"),
    path(
        "templates/<int:template_pk>/parties/create/",
        views.template_party_create,
        name="template_party_create"
    ),

    path(
        "templates/<int:template_pk>/parties/<int:party_pk>/fields/create/",
        views.template_party_field_create,
        name="template_party_field_create"
    ),

    path(
        "templates/<int:template_pk>/parties/<int:party_pk>/delete/",
        views.template_party_delete,
        name="template_party_delete"
    ),

    path(
        "templates/<int:template_pk>/parties/<int:party_pk>/fields/<int:field_pk>/delete/",
        views.template_party_field_delete,
        name="template_party_field_delete"
    ),
]
