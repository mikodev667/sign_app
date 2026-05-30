import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from documents.models import Document
from signing.forms import SignerForm
from signing.services.access_token_service import SignerAccessTokenService
from signing.services.egov_mobile_service import EgovMobileSigningService
from signing.services.signer_service import SignerService
from signing.services.sms_signing_service import SmsSigningService
from signing.services.sms_gateway_service import SmsGatewayService, SmsGatewayError
from signing.models import Signer, SigningSession, Signature, SigningAuditLog
from signing.services.audit_log_service import SigningAuditLogService

@login_required
def document_signers(request, document_pk):
    document = get_object_or_404(
        Document.objects.select_related("template", "organization"),
        pk=document_pk,
        created_by=request.user,
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
                )

                if document.status == Document.Status.DRAFT:
                    document.status = Document.Status.WAITING_FOR_SIGNERS
                    document.save(update_fields=["status", "updated_at"])

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
        document__created_by=request.user,
    )

    created_token = SignerAccessTokenService.create_token(signer=signer)

    signer.status = Signer.Status.SMS_SENT
    signer.save(update_fields=["status", "updated_at"])

    relative_url = f"/signing/s/{created_token.raw_token}/"
    absolute_url = request.build_absolute_uri(relative_url)

    sms_text = (
        f"TrustMe: Вам отправлен документ на подпись: "
        f"{signer.document.title}. "
        f"Ссылка: {absolute_url}"
    )

    try:
        SmsGatewayService.send_sms(
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
        metadata={
            "access_token_id": created_token.access_token.id,
            "sms_provider": "mobizon",
            "phone": signer.phone,
        },
    )

    messages.success(
        request,
        "Signing invitation SMS was sent successfully.",
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

    return render(request, "signing/signer_public_page.html", {
        "token": token,
        "signer": signer,
        "document": document,
        "latest_session": latest_session,
        "latest_sms_session": latest_sms_session,
    })


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

    try:
        session = SmsSigningService.create_session(signer=signer)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:signer_public_page", token=token)
    except SmsGatewayError as exc:
        messages.error(request, f"SMS code was not sent: {exc}")
        return redirect("signing:signer_public_page", token=token)

    SigningAuditLogService.log(
        document=signer.document,
        signer=signer,
        signing_session=session,
        event=SigningAuditLog.Event.SMS_CODE_SENT,
        request=request,
        metadata={
            "sms_provider": "mobizon",
            "phone": signer.phone,
        },
    )

    messages.success(
        request,
        "SMS confirmation code was sent to your phone."
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
        .filter(provider=SigningSession.Provider.SMS)
        .order_by("-created_at")
        .first()
    )

    if not session:
        messages.error(request, "No SMS signing session found.")
        return redirect("signing:signer_public_page", token=token)

    otp = request.POST.get("otp", "").strip()

    if not otp:
        messages.error(request, "SMS code is required.")
        return redirect("signing:signer_public_page", token=token)

    try:
        signature = SmsSigningService.complete_session(
            session=session,
            otp=otp,
            ip_address=request.META.get("REMOTE_ADDR", ""),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("signing:signer_public_page", token=token)

    SigningAuditLogService.log(
        document=signer.document,
        signer=signer,
        signing_session=session,
        event=SigningAuditLog.Event.DOCUMENT_SIGNED,
        request=request,
        signed_content_hash=signature.signed_content_hash,
        metadata={
            "provider": "sms",
            "signature_id": signature.id,
        },
    )

    messages.success(request, "Document signed successfully by SMS confirmation.")
    return redirect("signing:signer_public_page", token=token)