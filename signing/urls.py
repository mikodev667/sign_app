from django.urls import path

from signing import views

app_name = "signing"

urlpatterns = [
    path(
        "documents/<int:document_pk>/signers/",
        views.document_signers,
        name="document_signers",
    ),

    path(
        "signers/<int:signer_pk>/link/create/",
        views.create_signer_access_link,
        name="create_signer_access_link",
    ),

    path(
        "s/<str:token>/",
        views.signer_public_page,
        name="signer_public_page",
    ),
    path(
        "s/<str:token>/preview/",
        views.signer_document_preview,
        name="signer_document_preview",
    ),
    path(
        "s/<str:token>/lawvision/",
        views.signer_lawvision_report,
        name="signer_lawvision_report",
    ),
    path(
        "s/<str:token>/method/",
        views.choose_signing_method,
        name="choose_signing_method",
    ),

    # eGov Mobile public flow
    path(
        "s/<str:token>/egov/start/",
        views.start_egov_signing,
        name="start_egov_signing",
    ),
    path(
        "s/<str:token>/egov/mock-complete/",
        views.mock_complete_egov_signing,
        name="mock_complete_egov_signing",
    ),

    # eGov Mobile API №1
    path(
        "egov/api-1/<str:session_id>/",
        views.egov_api_1,
        name="egov_api_1",
    ),

    # eGov Mobile API №2
    path(
        "egov/api-2/<str:session_id>/",
        views.egov_api_2,
        name="egov_api_2",
    ),

    # SMS signing flow
    path(
        "s/<str:token>/sms/start/",
        views.start_sms_signing,
        name="start_sms_signing",
    ),
    path(
        "s/<str:token>/sms/complete/",
        views.complete_sms_signing,
        name="complete_sms_signing",
    ),

    # Confirmation sheet
    path(
        "signature/<int:signature_pk>/confirmation/",
        views.signature_confirmation,
        name="signature_confirmation",
    ),
    path(
        "signature/<int:signature_pk>/cms/",
        views.signature_cms_download,
        name="signature_cms_download",
    ),
    #ecp confirmation
    path(
        "s/<str:token>/ecp/payload/",
        views.ecp_signing_payload,
        name="ecp_signing_payload",
    ),
    path(
        "s/<str:token>/ecp/complete/",
        views.ecp_signing_complete,
        name="ecp_signing_complete",
    ),
]
