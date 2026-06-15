import json
import base64
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from documents.models import Document, DocumentLawVisionReport
from documents.services.lawvision_service import LawVisionError, LawVisionService
from organizations.services import get_user_managed_organizations
from signing.forms import SignerForm
from signing.services.access_token_service import SignerAccessTokenService
from signing.services.egov_mobile_service import EgovMobileSigningService
from signing.services.signer_service import SignerService
from signing.services.sms_signing_service import SmsSigningService
from signing.services.sms_gateway_service import SmsGatewayService, SmsGatewayError
from signing.models import Signer, SigningSession, Signature, SigningAuditLog
from signing.services.audit_log_service import SigningAuditLogService
from signing.services.ecp_signing_service import EcpSigningService
from django.views.decorators.http import require_GET, require_http_methods, require_POST


def get_current_lawvision_report(document, *, include_failed=False):
    if not document.content_hash:
        return None

    queryset = DocumentLawVisionReport.objects.filter(
        document=document,
        content_hash=document.content_hash,
    )

    if not include_failed:
        queryset = queryset.filter(status=DocumentLawVisionReport.Status.SUCCESS)

    return queryset.order_by("-created_at").first()


def can_request_lawvision_report(document):
    return bool(
        document.rendered_pdf_file
        or document.rendered_docx_file
        or document.rendered_html
    )


def render_signer_lawvision_report_page(request, *, token, signer, document, report):
    return render(request, "documents/lawvision_report.html", {
        "document": document,
        "report": report,
        "analysis": report.analysis if report else {},
        "metadata": report.metadata if report else {},
        "start_url": reverse("signing:signer_lawvision_report", args=[token]),
        "back_url": reverse("signing:signer_public_page", args=[token]),
        "is_public": True,
        "signer": signer,
        "can_start_analysis": can_request_lawvision_report(document),
    })

@login_required
def document_signers(request, document_pk):
    document = get_object_or_404(
        Document.objects.select_related("template", "organization"),
        pk=document_pk,
        organization__in=get_user_managed_organizations(request.user),
    )

    if request.method == "POST":
        form = SignerForm(request.POST)

        if form.is_valid():
            try:
                SignerService.add_signer(
                    document=document,
                    full_name=form.cleaned_data["full_name"],
                    iin=form.cleaned_data["iin"],
                    phone=form.cleaned_data["phone"],
                    signing_order=form.cleaned_data["signing_order"],
                    signing_method=form.cleaned_data["signing_method"],
                    request=request,
                )

                messages.success(request, "Signer added successfully.")
                return redirect("signing:document_signers", document_pk=document.pk)

            except ValueError as exc:
                form.add_error(None, str(exc))
    else:
        form = SignerForm()

    signers = document.signers.all().order_by("signing_order", "created_at")

    return render(request, "signing/document_signers.html", {
        "document": document,
        "form": form,
        "signers": signers,
    })


@login_required
@require_POST
def create_signer_access_link(request, signer_pk):
    signer = get_object_or_404(
        Signer.objects.select_related("document"),
        pk=signer_pk,
        document__organization__in=get_user_managed_organizations(request.user),
    )

    try:
        created_token = SignerAccessTokenService.create_token(
            signer=signer,
            request=request,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:document_signers", document_pk=signer.document_id)

    relative_url = f"/signing/s/{created_token.raw_token}/"
    absolute_url = request.build_absolute_uri(relative_url)

    sms_text = (
        f"TrustMe: Вам отправлен документ на подпись: "
        f"{signer.document.title}. "
        f"Ссылка: {absolute_url}"
    )

    try:
        sms_result = SmsGatewayService.send_sms(
            phone=signer.phone,
            text=sms_text,
        )
    except SmsGatewayError as exc:
        messages.error(
            request,
            f"Signing link was created, but SMS was not sent: {exc}",
        )
        return redirect("signing:document_signers", document_pk=signer.document_id)

    SigningAuditLogService.log(
        document=signer.document,
        signer=signer,
        event=SigningAuditLog.Event.INVITATION_SMS_SENT,
        request=request,
        document_hash=signer.document.content_hash,
        metadata={
            "access_token_id": created_token.access_token.id,
            "sms_result": sms_result,
            "phone": signer.phone,
        },
    )

    if sms_result.get("backend") == "console":
        messages.success(
            request,
            _("Signing invitation SMS was printed to console. Link: %(link)s") % {
                "link": absolute_url,
            },
        )
    else:
        messages.success(
            request,
            _("Signing invitation SMS was sent successfully."),
        )

    return redirect("signing:document_signers", document_pk=signer.document_id)

def signer_public_page(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return render(request, "signing/signer_link_invalid.html", status=404)

    signer = access_token.signer
    document = signer.document

    if not access_token.used_at:
        access_token.used_at = timezone.now()
        access_token.save(update_fields=["used_at"])

    SigningAuditLogService.log(
        document=document,
        signer=signer,
        event=SigningAuditLog.Event.LINK_OPENED,
        request=request,
        metadata={
            "access_token_id": access_token.id,
        },
    )

    if signer.status in [Signer.Status.PENDING, Signer.Status.SMS_SENT]:
        signer.status = Signer.Status.OPENED
        signer.save(update_fields=["status", "updated_at"])

    latest_session = signer.signing_sessions.order_by("-created_at").first()

    latest_sms_session = (
        signer.signing_sessions
        .filter(provider=SigningSession.Provider.SMS)
        .order_by("-created_at")
        .first()
    )

    signature = getattr(signer, "signature", None)
    lawvision_report = get_current_lawvision_report(document)

    return render(request, "signing/signer_public_page.html", {
        "token": token,
        "signer": signer,
        "document": document,
        "latest_session": latest_session,
        "latest_sms_session": latest_sms_session,
        "signature": signature,
        "lawvision_report": lawvision_report,
    })


@require_http_methods(["GET", "POST"])
def signer_lawvision_report(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return render(request, "signing/signer_link_invalid.html", status=404)

    signer = access_token.signer
    document = signer.document
    report = get_current_lawvision_report(document, include_failed=True)

    if request.method == "POST":
        try:
            report, cached = LawVisionService.get_or_analyze_document(
                document=document,
                source=DocumentLawVisionReport.Source.PUBLIC_SIGNER,
                force=request.POST.get("force") == "1",
            )
        except LawVisionError as exc:
            report = get_current_lawvision_report(document, include_failed=True)
            messages.error(request, _("LawVision analysis failed: %(error)s") % {"error": exc})
        else:
            if cached:
                messages.info(request, _("Using saved LawVision report for this document."))
            else:
                messages.success(request, _("LawVision report is ready."))

    return render_signer_lawvision_report_page(
        request,
        token=token,
        signer=signer,
        document=document,
        report=report,
    )


@require_POST
def start_egov_signing(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return render(request, "signing/signer_link_invalid.html", status=404)

    signer = access_token.signer

    if signer.status == Signer.Status.SIGNED:
        messages.info(request, "This document has already been signed.")
        return redirect("signing:signer_public_page", token=token)

    try:
        EgovMobileSigningService.create_session(signer=signer, request=request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:signer_public_page", token=token)

    messages.success(request, "eGov Mobile signing session created.")
    return redirect("signing:signer_public_page", token=token)


def egov_api_1(request, session_id):
    if request.method != "GET":
        return JsonResponse({"message": "Only GET method is allowed."}, status=405)

    session = get_object_or_404(
        SigningSession.objects.select_related(
            "signer",
            "signer__document",
            "signer__document__organization",
        ),
        provider_session_id=session_id,
    )

    if session.expires_at and session.expires_at <= timezone.now():
        session.status = SigningSession.Status.EXPIRED
        session.save(update_fields=["status", "updated_at"])

        return JsonResponse({"message": "Signing session expired."}, status=403)

    payload = EgovMobileSigningService.build_api_1_response(
        session=session,
        request=request,
    )

    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
def egov_api_2(request, session_id):
    session = get_object_or_404(
        SigningSession.objects.select_related(
            "signer",
            "signer__document",
            "signer__document__organization",
        ),
        provider_session_id=session_id,
    )

    if session.expires_at and session.expires_at <= timezone.now():
        session.status = SigningSession.Status.EXPIRED
        session.save(update_fields=["status", "updated_at"])

        return JsonResponse({"message": "Signing session expired."}, status=403)

    if not EgovMobileSigningService.check_bearer_token(
        request=request,
        session=session,
    ):
        return JsonResponse({"message": "Invalid authorization token."}, status=401)

    if request.method == "GET":
        payload = EgovMobileSigningService.build_api_2_get_response(session=session)
        return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})

    if request.method == "PUT":
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid JSON."}, status=400)

        try:
            signature = EgovMobileSigningService.complete_session(
                session=session,
                payload=payload,
            )
        except ValueError as exc:
            return JsonResponse({"message": str(exc)}, status=403)

        return JsonResponse({
            "message": "success",
            "signature_id": signature.id,
        })

    return JsonResponse({"message": "Only GET and PUT methods are allowed."}, status=405)

@require_POST
def mock_complete_egov_signing(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return render(request, "signing/signer_link_invalid.html", status=404)

    signer = access_token.signer

    session = (
        signer.signing_sessions
        .filter(provider=SigningSession.Provider.EGOV_MOBILE)
        .order_by("-created_at")
        .first()
    )

    if not session:
        messages.error(request, "No eGov Mobile signing session found.")
        return redirect("signing:signer_public_page", token=token)

    if signer.status == Signer.Status.SIGNED:
        messages.info(request, "This document has already been signed.")
        return redirect("signing:signer_public_page", token=token)

    payload = {
        "signMethod": EgovMobileSigningService.SIGN_METHOD,
        "version": 1,
        "documentsToSign": [
            {
                "id": signer.document.id,
                "nameRu": signer.document.title,
                "nameKz": signer.document.title,
                "nameEn": signer.document.title,
                "meta": [
                    {
                        "name": "Mock",
                        "value": "Local mock eGov Mobile signed payload",
                    }
                ],
                "document": {
                    "file": {
                        "mime": EgovMobileSigningService.get_mime_type(signer.document),
                        "data": "MOCK_SIGNED_CMS_BASE64_FROM_EGOV_MOBILE",
                    }
                },
            }
        ],
    }

    try:
        EgovMobileSigningService.complete_session(
            session=session,
            payload=payload,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:signer_public_page", token=token)

    messages.success(request, "Mock eGov Mobile signing completed.")
    return redirect("signing:signer_public_page", token=token)

@require_POST
def start_sms_signing(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return render(request, "signing/signer_link_invalid.html", status=404)

    signer = access_token.signer

    if signer.status == Signer.Status.SIGNED:
        messages.info(request, "This document has already been signed.")
        return redirect("signing:signer_public_page", token=token)

    consent_accepted = request.POST.get("consent") == "on"

    ip_address = SigningAuditLogService.get_client_ip(request)
    user_agent = SigningAuditLogService.get_user_agent(request)

    try:
        session = SmsSigningService.create_session(
            signer=signer,
            consent_accepted=consent_accepted,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:signer_public_page", token=token)
    except SmsGatewayError as exc:
        messages.error(request, f"SMS code was not sent: {exc}")
        return redirect("signing:signer_public_page", token=token)

    dev_otp = (session.raw_response or {}).get("dev_otp")
    if dev_otp:
        messages.success(
            request,
            _("SMS confirmation code was printed to console. Code: %(code)s") % {
                "code": dev_otp,
            },
        )
    else:
        messages.success(
            request,
            _("SMS confirmation code was sent to your phone.")
        )

    return redirect("signing:signer_public_page", token=token)

@require_POST
def complete_sms_signing(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return render(request, "signing/signer_link_invalid.html", status=404)

    signer = access_token.signer

    session = (
        signer.signing_sessions
        .filter(
            provider=SigningSession.Provider.SMS,
        )
        .exclude(
            status__in=[
                SigningSession.Status.SIGNED,
                SigningSession.Status.USED,
                SigningSession.Status.EXPIRED,
                SigningSession.Status.CANCELED,
                SigningSession.Status.FAILED,
            ]
        )
        .order_by("-created_at")
        .first()
    )

    if not session:
        messages.error(request, "No active SMS signing session found.")
        return redirect("signing:signer_public_page", token=token)

    otp = request.POST.get("otp", "").strip()

    if not otp:
        messages.error(request, "SMS code is required.")
        return redirect("signing:signer_public_page", token=token)

    ip_address = SigningAuditLogService.get_client_ip(request)
    user_agent = SigningAuditLogService.get_user_agent(request)

    try:
        signature = SmsSigningService.complete_session(
            session=session,
            otp=otp,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:signer_public_page", token=token)

    messages.success(request, "Document signed successfully by SMS confirmation.")
    return redirect("signing:signature_confirmation", signature_pk=signature.pk)

def signature_confirmation(request, signature_pk):
    signature = get_object_or_404(
        Signature.objects.select_related(
            "document",
            "signer",
            "signing_session",
        ),
        pk=signature_pk,
    )

    return render(request, "signing/signature_confirmation.html", {
        "signature": signature,
        "document": signature.document,
        "signer": signature.signer,
        "signing_session": signature.signing_session,
    })


@require_GET
def ecp_signing_payload(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return JsonResponse(
            {"ok": False, "error": "Invalid or expired signing link."},
            status=404,
        )

    signer = access_token.signer

    if signer.status == Signer.Status.SIGNED:
        return JsonResponse(
            {"ok": False, "error": "Signer already signed."},
            status=400,
        )

    if signer.signing_method != Signer.SigningMethod.ECP:
        return JsonResponse(
            {"ok": False, "error": "Signer is not configured for ECP signing."},
            status=400,
        )

    document = signer.document

    if not document.content_hash:
        return JsonResponse(
            {"ok": False, "error": "Document hash is missing."},
            status=400,
        )

    payload = {
        "document_id": document.id,
        "signer_id": signer.id,
        "signer_iin": signer.iin,
        "document_hash": document.content_hash,
        "title": document.title,
    }

    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload_base64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

    SigningAuditLogService.log(
        document=document,
        signer=signer,
        event=SigningAuditLog.Event.ECP_SIGNING_STARTED,
        request=request,
        document_hash=document.content_hash,
        metadata={
            "signing_method": Signer.SigningMethod.ECP,
            "payload": payload,
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "payload_base64": payload_base64,
            "document_hash": document.content_hash,
            "signer_iin": signer.iin,
        }
    )


@require_POST
def ecp_signing_complete(request, token):
    access_token = SignerAccessTokenService.get_valid_token(raw_token=token)

    if not access_token:
        return JsonResponse(
            {"ok": False, "error": "Invalid or expired signing link."},
            status=404,
        )

    signer = access_token.signer

    if signer.status == Signer.Status.SIGNED:
        return JsonResponse(
            {"ok": False, "error": "Signer already signed."},
            status=400,
        )

    if signer.signing_method != Signer.SigningMethod.ECP:
        return JsonResponse(
            {"ok": False, "error": "Signer is not configured for ECP signing."},
            status=400,
        )

    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse(
            {"ok": False, "error": "Invalid JSON."},
            status=400,
        )

    cms_signature = body.get("cms_signature", "")
    certificate_subject = body.get("certificate_subject", "")
    certificate_serial_number = body.get("certificate_serial_number", "")

    if not cms_signature:
        return JsonResponse(
            {"ok": False, "error": "CMS signature is required."},
            status=400,
        )

    ip_address = SigningAuditLogService.get_client_ip(request)
    user_agent = SigningAuditLogService.get_user_agent(request)

    try:
        signature = EcpSigningService.complete_signing(
            signer=signer,
            cms_signature=cms_signature,
            signed_payload=body,
            certificate_subject=certificate_subject,
            certificate_serial_number=certificate_serial_number,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except ValueError as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc)},
            status=400,
        )

    return JsonResponse(
        {
            "ok": True,
            "signature_id": signature.id,
            "redirect_url": request.build_absolute_uri(
                f"/signing/signature/{signature.pk}/confirmation/"
            ),
        }
    )
