from django.urls import path

from admissions import views


app_name = "admissions"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/contracts/", views.admission_contract_api, name="admission_contract_api"),
    path(
        "api/contracts/<int:pk>/",
        views.admission_contract_detail_api,
        name="admission_contract_detail_api",
    ),
    path(
        "contracts/protected/<str:token>/",
        views.protected_contract_link_page,
        name="protected_contract_link_page",
    ),
    path("contracts/<str:token>/", views.applicant_contract, name="applicant_contract"),
    path("contracts/<str:token>/preview/", views.applicant_contract_preview, name="applicant_contract_preview"),
    path(
        "contracts/<str:token>/download/<str:kind>/<str:file_format>/",
        views.applicant_contract_download,
        name="applicant_contract_download",
    ),
    path("contracts/<str:token>/sign/", views.applicant_sign_contract, name="applicant_sign_contract"),
    path(
        "contracts/<str:token>/ecp/payload/",
        views.applicant_ecp_signing_payload,
        name="applicant_ecp_signing_payload",
    ),
    path(
        "contracts/<str:token>/ecp/complete/",
        views.applicant_ecp_signing_complete,
        name="applicant_ecp_signing_complete",
    ),
    path("commission/", views.commission_dashboard, name="commission_dashboard"),
    path(
        "commission/contracts/<int:pk>/delete/",
        views.commission_delete_contract,
        name="commission_delete_contract",
    ),
    path("vice-rector/", views.vice_rector_dashboard, name="vice_rector_dashboard"),
    path(
        "vice-rector/contracts/<int:pk>/sign/",
        views.vice_rector_sign_contract,
        name="vice_rector_sign_contract",
    ),
    path(
        "vice-rector/contracts/<int:pk>/ecp/payload/",
        views.vice_rector_ecp_signing_payload,
        name="vice_rector_ecp_signing_payload",
    ),
    path(
        "vice-rector/contracts/<int:pk>/ecp/complete/",
        views.vice_rector_ecp_signing_complete,
        name="vice_rector_ecp_signing_complete",
    ),
]
