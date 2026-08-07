import base64
import json
import logging
import time
from uuid import uuid4
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.http import require_http_methods

from documents.models import Document, DocumentFieldValue
from documents.services.money_amount_service import MoneyAmountService
from documents.services.object_storage_service import ObjectStorageService
from documents.services.pdf_export_service import OnlyOfficePdfExportService, PdfExportError
from signing.models import Signer
from signing.services.audit_log_service import SigningAuditLogService
from signing.services.ecp_signing_service import EcpSigningService
from signing.services.signer_service import SignerService
from signing.models import SigningAuditLog

from admissions.models import AdmissionContract, AdmissionTemplateRule
from admissions.services.api_auth import AdmissionApiAuthError, AdmissionApiAuthService
from admissions.services.contract_builder import (
    AdmissionContractAlreadyExists,
    AdmissionContractBuilder,
    AdmissionContractBuildError,
    AdmissionContractCannotBeUpdated,
)
from admissions.services.contract_deletion_service import (
    AdmissionContractDeletionError,
    AdmissionContractDeletionService,
)
from admissions.services.mssql_mirror_service import (
    AdmissionMssqlMirrorError,
    AdmissionMssqlMirrorService,
)
from admissions.services.render_queue_service import AdmissionRenderQueueService


ADMISSION_DASHBOARD_PAGE_SIZE = 50
from admissions.services.payload_mapper import AdmissionPayloadError, AdmissionPayloadMapper


logger = logging.getLogger("admissions.api")


ADMISSION_EDIT_FIELD_LABELS = {
    "side_1_full_name": _("Full name"),
    "side_1_full_name_genitive": _("Full name in genitive case"),
    "side_1_iin": _("IIN"),
    "side_1_iin_bin": _("IIN"),
    "side_1_phone": _("Phone"),
    "side_1_email": _("Email"),
    "applicant_full_name": _("Full name"),
    "applicant_full_name_genitive": _("Full name in genitive case"),
    "applicant_iin": _("IIN"),
    "applicant_phone": _("Phone"),
    "applicant_email": _("Email"),
    "student_full_name": _("Full name"),
    "student_full_name_genitive": _("Full name in genitive case"),
    "student_iin": _("IIN"),
    "student_phone": _("Phone"),
    "student_email": _("Email"),
    "program_code": _("Program code"),
    "program_name_ru": _("Program name (RU)"),
    "program_name_kk": _("Program name (KZ)"),
    "program_group_code": _("Program group code"),
    "program_group_name_ru": _("Program group (RU)"),
    "program_group_name_kk": _("Program group (KZ)"),
    "program_faculty_ru": _("Faculty (RU)"),
    "program_faculty_kk": _("Faculty (KZ)"),
    "student_faculty": _("Faculty"),
    "student_address": _("Address"),
    "almaty_address": _("Address in Almaty"),
    "identity_document_number": _("Identity document number"),
    "identity_document_series": _("Identity document series"),
    "identity_document_issue_date_ru": _("Identity document issue date (RU)"),
    "identity_document_issue_date_kk": _("Identity document issue date (KZ)"),
    "identity_document_issuer_ru": _("Identity document issuer (RU)"),
    "identity_document_issuer_kk": _("Identity document issuer (KZ)"),
    "birth_date_text_ru": _("Birth date (RU)"),
    "birth_date_text_kk": _("Birth date (KZ)"),
    "gender_ru": _("Gender (RU)"),
    "gender_kk": _("Gender (KZ)"),
    "citizenship_ru": _("Citizenship (RU)"),
    "citizenship_kk": _("Citizenship (KZ)"),
    "nationality_ru": _("Nationality (RU)"),
    "nationality_kk": _("Nationality (KZ)"),
    "previous_education_ru": _("Previous education (RU)"),
    "previous_education_kk": _("Previous education (KZ)"),
    "graduation_year": _("Graduation year"),
    "education_document_type_ru": _("Education document type (RU)"),
    "education_document_type_kk": _("Education document type (KZ)"),
    "education_document_series": _("Education document series"),
    "education_document_number": _("Education document number"),
    "education_document_issue_date": _("Education document issue date"),
    "certificate_score": _("Certificate score"),
    "average_grade": _("Average grade"),
    "admission_quota_ru": _("Admission quota (RU)"),
    "admission_quota_kk": _("Admission quota (KZ)"),
    "father_full_name": _("Father full name"),
    "father_phone": _("Father phone"),
    "father_work_place": _("Father workplace"),
    "father_position": _("Father position"),
    "mother_full_name": _("Mother full name"),
    "mother_phone": _("Mother phone"),
    "mother_work_place": _("Mother workplace"),
    "mother_position": _("Mother position"),
    "student_parent_full_name": _("Parent or legal representative"),
    "student_parent_iin": _("Parent IIN"),
    "student_parent_phone": _("Parent phone"),
    "student_parent_address": _("Parent address"),
    "foreign_language_ru": _("Foreign language (RU)"),
    "foreign_language_kk": _("Foreign language (KZ)"),
    "dormitory_need_ru": _("Dormitory choice (RU)"),
    "dormitory_need_kk": _("Dormitory choice (KZ)"),
    "applicant_signature_full_name": _("Applicant signature full name"),
    "student_signature_full_name": _("Student signature full name"),
    "technical_secretary_full_name": _("Technical secretary full name"),
    "dean_full_name": _("Dean full name"),
    "contract_number": _("Contract number"),
    "contract_date": _("Contract date"),
    "tuition_amount": _("Tuition amount"),
}

ADMISSION_EDIT_FIELD_PRIORITY = (
    "contract_date",
    "tuition_amount",
    "side_1_full_name",
    "side_1_iin_bin",
    "side_1_iin",
    "side_1_phone",
    "side_1_email",
    "applicant_full_name",
    "applicant_iin",
    "applicant_phone",
    "applicant_email",
    "student_full_name",
    "student_iin",
    "student_phone",
    "student_email",
    "program_code",
    "program_name_ru",
    "program_name_kk",
    "program_group_code",
    "program_group_name_ru",
    "program_group_name_kk",
    "program_faculty_ru",
    "program_faculty_kk",
    "student_faculty",
    "student_address",
    "almaty_address",
    "birth_date_text_ru",
    "birth_date_text_kk",
    "identity_document_number",
    "identity_document_series",
    "identity_document_issue_date_ru",
    "identity_document_issue_date_kk",
    "identity_document_issuer_ru",
    "identity_document_issuer_kk",
    "gender_ru",
    "gender_kk",
    "citizenship_ru",
    "citizenship_kk",
    "nationality_ru",
    "nationality_kk",
    "previous_education_ru",
    "previous_education_kk",
    "graduation_year",
    "education_document_type_ru",
    "education_document_type_kk",
    "education_document_series",
    "education_document_number",
    "education_document_issue_date",
    "certificate_score",
    "average_grade",
    "admission_quota_ru",
    "admission_quota_kk",
    "father_full_name",
    "father_phone",
    "father_work_place",
    "father_position",
    "mother_full_name",
    "mother_phone",
    "mother_work_place",
    "mother_position",
    "student_parent_full_name",
    "student_parent_iin",
    "student_parent_phone",
    "student_parent_address",
    "foreign_language_ru",
    "foreign_language_kk",
    "dormitory_need_ru",
    "dormitory_need_kk",
    "technical_secretary_full_name",
    "dean_full_name",
)

ADMISSION_MANUAL_SYSTEM_FIELDS = (
    Document.SYSTEM_CONTRACT_DATE,
)
ADMISSION_MANUAL_SYSTEM_FIELD_SET = set(ADMISSION_MANUAL_SYSTEM_FIELDS)


def get_request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()

    return request.META.get("REMOTE_ADDR", "")


def mask_sensitive_number(value, *, visible_digits=4):
    text = str(value or "").strip()
    if not text:
        return ""

    if len(text) <= visible_digits:
        return "*" * len(text)

    return f"{'*' * (len(text) - visible_digits)}{text[-visible_digits:]}"


@csrf_exempt
@require_POST
def admission_contract_api(request):
    request_id = uuid4().hex[:12]
    started_at = time.monotonic()

    try:
        api_client = AdmissionApiAuthService.authenticate(request)
    except AdmissionApiAuthError as exc:
        logger.warning(
            "admission_api_auth_failed request_id=%s ip=%s error=%s",
            request_id,
            get_request_ip(request),
            exc,
        )
        return JsonResponse({"error": str(exc)}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.warning(
            "admission_api_invalid_json request_id=%s api_client_id=%s ip=%s body_size=%s",
            request_id,
            api_client.pk,
            get_request_ip(request),
            len(request.body or b""),
        )
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)

    try:
        normalized_payload = AdmissionPayloadMapper.normalize_payload(payload)
    except AdmissionPayloadError as exc:
        logger.warning(
            "admission_api_payload_invalid request_id=%s api_client_id=%s ip=%s error=%s",
            request_id,
            api_client.pk,
            get_request_ip(request),
            exc,
        )
        return JsonResponse({"error": str(exc)}, status=422)

    logger.info(
        "admission_api_received request_id=%s api_client_id=%s external_id=%s applicant_iin=%s async=%s",
        request_id,
        api_client.pk,
        normalized_payload["external_id"],
        mask_sensitive_number(normalized_payload["applicant_iin"]),
        settings.ADMISSIONS_ASYNC_RENDER_ENABLED,
    )

    existing_contract = AdmissionContract.objects.filter(
        external_id=normalized_payload["external_id"],
    ).first()
    if existing_contract and existing_contract.api_client_id != api_client.id:
        logger.warning(
            "admission_api_external_id_conflict request_id=%s external_id=%s incoming_client_id=%s owner_client_id=%s",
            request_id,
            normalized_payload["external_id"],
            api_client.pk,
            existing_contract.api_client_id,
        )
        return JsonResponse({"error": "Admission contract already exists."}, status=409)

    try:
        if existing_contract:
            if settings.ADMISSIONS_ASYNC_RENDER_ENABLED:
                contract = AdmissionContractBuilder.update_pending_from_payload(
                    contract=existing_contract,
                    api_client=api_client,
                    normalized_payload=normalized_payload,
                )
            else:
                contract = AdmissionContractBuilder.update_from_payload(
                    contract=existing_contract,
                    api_client=api_client,
                    normalized_payload=normalized_payload,
                    request=request,
                )
            response_status = 200
            response_state = "updated"
        elif settings.ADMISSIONS_ASYNC_RENDER_ENABLED:
            contract = AdmissionContractBuilder.create_pending_from_payload(
                api_client=api_client,
                normalized_payload=normalized_payload,
            )
            response_status = 201
            response_state = "created"
        else:
            contract = AdmissionContractBuilder.create_from_payload(
                api_client=api_client,
                normalized_payload=normalized_payload,
                request=request,
            )
            response_status = 201
            response_state = "created"
    except (AdmissionContractAlreadyExists, IntegrityError):
        logger.warning(
            "admission_api_create_race request_id=%s external_id=%s",
            request_id,
            normalized_payload["external_id"],
        )
        contract = (
            AdmissionContract.objects
            .filter(
                api_client=api_client,
                external_id=normalized_payload["external_id"],
            )
            .first()
        )
        if not contract:
            logger.exception(
                "admission_api_duplicate_missing_after_race request_id=%s external_id=%s",
                request_id,
                normalized_payload["external_id"],
            )
            return JsonResponse({"error": "Admission contract already exists."}, status=409)

        try:
            if settings.ADMISSIONS_ASYNC_RENDER_ENABLED:
                contract = AdmissionContractBuilder.update_pending_from_payload(
                    contract=contract,
                    api_client=api_client,
                    normalized_payload=normalized_payload,
                )
            else:
                contract = AdmissionContractBuilder.update_from_payload(
                    contract=contract,
                    api_client=api_client,
                    normalized_payload=normalized_payload,
                    request=request,
                )
        except AdmissionContractCannotBeUpdated as exc:
            logger.warning(
                "admission_api_update_blocked request_id=%s external_id=%s contract_id=%s error=%s",
                request_id,
                normalized_payload["external_id"],
                contract.pk,
                exc,
            )
            return JsonResponse({"error": str(exc)}, status=409)

        response_status = 200
        response_state = "updated"
    except AdmissionContractCannotBeUpdated as exc:
        logger.warning(
            "admission_api_update_blocked request_id=%s external_id=%s contract_id=%s error=%s",
            request_id,
            normalized_payload["external_id"],
            existing_contract.pk if existing_contract else "",
            exc,
        )
        return JsonResponse({"error": str(exc)}, status=409)
    except AdmissionContractBuildError as exc:
        logger.warning(
            "admission_api_build_failed request_id=%s external_id=%s error=%s",
            request_id,
            normalized_payload["external_id"],
            exc,
        )
        return JsonResponse({"error": str(exc)}, status=422)
    except ValueError as exc:
        logger.warning(
            "admission_api_value_error request_id=%s external_id=%s error=%s",
            request_id,
            normalized_payload["external_id"],
            exc,
        )
        return JsonResponse({"error": str(exc)}, status=422)

    ensure_admission_contract_urls(request=request, contract=contract)
    render_job = None
    if settings.ADMISSIONS_ASYNC_RENDER_ENABLED:
        render_job = AdmissionRenderQueueService.enqueue_contract(
            contract=contract,
            reset_failed=response_state == "updated",
        )

    mssql_synced = AdmissionMssqlMirrorService.sync_contract(
        contract=contract,
        raise_on_error=False,
    )
    elapsed_ms = int((time.monotonic() - started_at) * 1000)

    logger.info(
        "admission_api_completed request_id=%s status=%s http_status=%s external_id=%s contract_id=%s document_id=%s application_document_id=%s protected_url=%s render_job_id=%s render_job_status=%s mssql_synced=%s elapsed_ms=%s",
        request_id,
        response_state,
        response_status,
        contract.external_id,
        contract.pk,
        contract.document_id,
        contract.application_document_id,
        bool(contract.protected_url),
        render_job.pk if render_job else "",
        render_job.status if render_job else "",
        mssql_synced,
        elapsed_ms,
    )

    return JsonResponse({
        "status": response_state,
        "external_id": contract.external_id,
        "admission_contract_id": contract.pk,
        "document_id": contract.document_id,
        "protected_contract_url": contract.protected_url,
    }, status=response_status)


@require_GET
def admission_contract_detail_api(request, pk):
    try:
        api_client = AdmissionApiAuthService.authenticate(request)
    except AdmissionApiAuthError as exc:
        return JsonResponse({"error": str(exc)}, status=401)

    contract = (
        AdmissionContract.objects
        .select_related(
            "document",
            "application_document",
            "student_signer",
            "vice_rector_signer",
            "render_job",
        )
        .filter(pk=pk, api_client=api_client)
        .first()
    )
    if not contract:
        return JsonResponse({"error": "Admission contract was not found."}, status=404)

    contract.refresh_status_from_signers()
    return JsonResponse(build_admission_contract_detail_payload(
        request=request,
        contract=contract,
    ))


@require_GET
def protected_contract_link_page(request, token):
    contract = get_protected_contract(token)

    if not contract or contract.is_expired() or not contract.public_url:
        return render(request, "admissions/applicant_contract_invalid.html", status=404)

    contract.refresh_status_from_signers()
    return render(request, "admissions/protected_contract_link.html", {
        "contract": contract,
        "contract_url": contract.public_url,
    })


@require_http_methods(["GET", "POST"])
def applicant_contract(request, token):
    contract = get_public_contract(token)

    if not contract or contract.is_expired():
        return render(request, "admissions/applicant_contract_invalid.html", status=404)

    contract.refresh_status_from_signers()
    if not is_admission_contract_ready_for_applicant(contract):
        if settings.ADMISSIONS_ASYNC_RENDER_ENABLED and contract.status != AdmissionContract.Status.FAILED:
            AdmissionRenderQueueService.enqueue_contract(contract=contract)

        return render(request, "admissions/applicant_contract_processing.html", {
            "contract": contract,
            "token": token,
            "render_job": getattr(contract, "render_job", None),
        })

    editable_fields = build_admission_edit_fields(contract)
    can_edit = can_edit_admission_contract(contract)

    if request.method == "POST":
        if not can_edit:
            messages.error(request, _("The contract cannot be edited after it has been signed."))
            return redirect("admissions:applicant_contract", token=token)

        try:
            update_admission_contract_fields(
                contract=contract,
                editable_fields=editable_fields,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Contract data was updated. Review the document before signing."))

        return redirect("admissions:applicant_contract", token=token)

    return render(request, "admissions/applicant_contract.html", {
        "contract": contract,
        "document": contract.document,
        "application_document": contract.application_document,
        "student_signer": contract.student_signer,
        "signature": getattr(contract.student_signer, "signature", None) if contract.student_signer else None,
        "token": token,
        "editable_fields": editable_fields,
        "can_edit": can_edit,
        "tuition_amount_display": (
            MoneyAmountService.format_amount(contract.tuition_amount)
            if contract.tuition_amount is not None
            else ""
        ),
    })


@require_POST
def applicant_sign_contract(request, token):
    contract = get_public_contract(token)

    if not contract or contract.is_expired():
        return render(request, "admissions/applicant_contract_invalid.html", status=404)

    if not is_admission_contract_ready_for_applicant(contract):
        messages.error(request, _("Documents are still being prepared. Please try again in a moment."))
        return redirect("admissions:applicant_contract", token=token)

    signer = contract.student_signer
    if not signer:
        messages.error(request, _("Applicant signer is not available."))
        return redirect("admissions:applicant_contract", token=token)

    if signer.is_signed():
        messages.info(request, _("You have already signed this document."))
        return redirect("admissions:applicant_contract", token=token)

    readiness_error = get_admission_contract_signing_readiness_error(contract)
    if readiness_error:
        messages.error(request, readiness_error)
        return redirect("admissions:applicant_contract", token=token)

    signer.signing_method = Signer.SigningMethod.ECP
    signer.status = Signer.Status.SIGNING_STARTED
    signer.save(update_fields=["signing_method", "status", "updated_at"])

    messages.info(request, _("ECP signing is ready on this page."))
    return redirect("admissions:applicant_contract", token=token)


@require_GET
@xframe_options_sameorigin
def applicant_contract_preview(request, token):
    contract = get_public_contract(token)

    if not contract or contract.is_expired():
        return HttpResponse(_("Contract link is unavailable."), status=404)

    document = get_admission_document_for_kind(contract, request.GET.get("kind", "contract"))

    if not document or not is_admission_document_ready(contract, request.GET.get("kind", "contract")):
        return HttpResponse(_("Documents are still being prepared."), status=409)

    try:
        pdf = OnlyOfficePdfExportService.export_document_pdf(document)
    except PdfExportError as exc:
        return HttpResponse(
            _("Document preview is not available: %(error)s") % {"error": exc},
            status=404,
        )

    response = HttpResponse(pdf.content, content_type=pdf.content_type)
    response["Content-Disposition"] = f'inline; filename="{pdf.filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def applicant_contract_download(request, token, kind, file_format):
    contract = get_public_contract(token)

    if not contract or contract.is_expired():
        return HttpResponse(_("Contract link is unavailable."), status=404)

    document = get_admission_document_for_kind(contract, kind)

    if not document or not is_admission_document_ready(contract, kind):
        return HttpResponse(_("Documents are still being prepared."), status=409)

    if file_format == "pdf":
        try:
            pdf = OnlyOfficePdfExportService.export_document_pdf(document)
        except PdfExportError as exc:
            return HttpResponse(
                _("PDF export is not available: %(error)s") % {"error": exc},
                status=404,
            )

        response = HttpResponse(pdf.content, content_type=pdf.content_type)
        response["Content-Disposition"] = f'attachment; filename="{pdf.filename}"'
        response["Cache-Control"] = "private, no-store"
        return response

    if file_format == "docx":
        if not document.rendered_docx_file:
            return HttpResponse(_("DOCX file is not available."), status=404)

        document.rendered_docx_file.open("rb")
        try:
            content = document.rendered_docx_file.read()
        finally:
            document.rendered_docx_file.close()

        filename = document.rendered_docx_file.name.rsplit("/", 1)[-1] or f"document-{document.pk}.docx"
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "private, no-store"
        return response

    return HttpResponse(_("Unsupported file format."), status=404)


@require_GET
def applicant_ecp_signing_payload(request, token):
    contract = get_public_contract(token)

    if not contract or contract.is_expired():
        return JsonResponse({"ok": False, "error": _("Contract link is unavailable.")}, status=404)

    if not is_admission_contract_ready_for_applicant(contract):
        return JsonResponse({"ok": False, "error": _("Documents are still being prepared.")}, status=409)

    signer = contract.student_signer

    if not signer:
        return JsonResponse({"ok": False, "error": _("Applicant signer is not available.")}, status=400)

    if signer.is_signed():
        return JsonResponse({"ok": False, "error": _("Signer already signed.")}, status=400)

    readiness_error = get_admission_contract_signing_readiness_error(contract)
    if readiness_error:
        return JsonResponse({"ok": False, "error": readiness_error}, status=400)

    return prepare_admission_ecp_signing_payload(
        request=request,
        signer=signer,
        source="admissions_applicant",
    )


@require_POST
def applicant_ecp_signing_complete(request, token):
    contract = get_public_contract(token)

    if not contract or contract.is_expired():
        return JsonResponse({"ok": False, "error": _("Contract link is unavailable.")}, status=404)

    if not is_admission_contract_ready_for_applicant(contract):
        return JsonResponse({"ok": False, "error": _("Documents are still being prepared.")}, status=409)

    signer = contract.student_signer

    if not signer:
        return JsonResponse({"ok": False, "error": _("Applicant signer is not available.")}, status=400)

    if signer.is_signed():
        return JsonResponse({"ok": False, "error": _("Signer already signed.")}, status=400)

    signature, error_response = complete_admission_ecp_signature(
        request=request,
        signer=signer,
    )
    if error_response:
        return error_response

    contract.refresh_status_from_signers()
    AdmissionMssqlMirrorService.sync_contract(
        contract=contract,
        public_url=request.build_absolute_uri(
            reverse("admissions:applicant_contract", args=[token])
        ),
        raise_on_error=False,
    )

    return JsonResponse({
        "ok": True,
        "signature_id": signature.id,
        "redirect_url": request.build_absolute_uri(
            reverse("admissions:applicant_contract", args=[token])
        ),
    })


def prepare_admission_ecp_signing_payload(*, request, signer, source):
    document = signer.document

    if not document.rendered_docx_file and not document.rendered_pdf_file and not document.rendered_html:
        return JsonResponse({"ok": False, "error": _("Document file is not rendered yet.")}, status=400)

    signer.signing_method = Signer.SigningMethod.ECP
    if signer.status in [Signer.Status.PENDING, Signer.Status.OPENED, Signer.Status.SMS_SENT]:
        signer.status = Signer.Status.SIGNING_STARTED
    signer.save(update_fields=["signing_method", "status", "updated_at"])

    if not document.content_hash:
        document.update_content_hash(save=True)

    document.lock_for_signing(save=True)

    try:
        stored_objects = ObjectStorageService.ensure_final_document_objects(
            document=document,
            created_by=None,
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": _("Final document could not be stored: %(error)s") % {"error": exc}},
            status=400,
        )

    if ObjectStorageService.is_enabled() and not stored_objects:
        return JsonResponse(
            {"ok": False, "error": _("Final document has no rendered file to store.")},
            status=400,
        )

    payload = {
        "document_id": document.id,
        "signer_id": signer.id,
        "signer_iin": signer.iin,
        "signer_email": signer.email,
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
            "source": source,
            "payload": payload,
        },
    )

    return JsonResponse({
        "ok": True,
        "payload_base64": payload_base64,
        "document_hash": document.content_hash,
        "signer_iin": signer.iin,
    })


def complete_admission_ecp_signature(*, request, signer):
    signer.signing_method = Signer.SigningMethod.ECP
    if signer.status in [Signer.Status.PENDING, Signer.Status.OPENED, Signer.Status.SMS_SENT]:
        signer.status = Signer.Status.SIGNING_STARTED
    signer.save(update_fields=["signing_method", "status", "updated_at"])

    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None, JsonResponse({"ok": False, "error": _("Invalid JSON.")}, status=400)

    cms_signature = body.get("cms_signature", "")

    if not cms_signature:
        return None, JsonResponse({"ok": False, "error": _("CMS signature is required.")}, status=400)

    try:
        signature = EcpSigningService.complete_signing(
            signer=signer,
            cms_signature=cms_signature,
            signed_payload=body,
            certificate_subject=body.get("certificate_subject", ""),
            certificate_serial_number=body.get("certificate_serial_number", ""),
            ip_address=SigningAuditLogService.get_client_ip(request),
            user_agent=SigningAuditLogService.get_user_agent(request),
            skip_key_validation=True,
        )
    except ValueError as exc:
        return None, JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return signature, None


def get_admission_user_access(user):
    commission_profile = getattr(user, "admission_commission_profile", None)
    vice_rector_profile = getattr(user, "admission_vice_rector_profile", None)

    return {
        "commission_profile": (
            commission_profile
            if commission_profile and commission_profile.is_active
            else None
        ),
        "vice_rector_profile": (
            vice_rector_profile
            if vice_rector_profile and vice_rector_profile.is_active
            else None
        ),
    }


@login_required(login_url="accounts:admission_login")
def dashboard(request):
    access = get_admission_user_access(request.user)

    return render(request, "admissions/dashboard.html", access)


@login_required(login_url="accounts:admission_login")
def vice_rector_dashboard(request):
    profile = getattr(request.user, "admission_vice_rector_profile", None)

    if not profile or not profile.is_active:
        return HttpResponseForbidden(_("Vice rector cabinet is not available for this account."))

    filters = {
        "q": request.GET.get("q", "").strip(),
        "signature_state": request.GET.get("signature_state", "").strip(),
        "status": request.GET.get("status", "").strip(),
        "date_from": request.GET.get("date_from", "").strip(),
        "date_to": request.GET.get("date_to", "").strip(),
        "education_level": request.GET.get("education_level", "").strip(),
        "funding_type": request.GET.get("funding_type", "").strip(),
    }

    contracts_qs = (
        AdmissionContract.objects
        .select_related(
            "document",
            "application_document",
            "template_rule",
            "student_signer",
            "vice_rector_signer",
        )
        .filter(template_rule__vice_rector=profile)
    )

    total_contracts = contracts_qs.count()

    if filters["q"]:
        query = filters["q"]
        contracts_qs = contracts_qs.filter(
            Q(external_id__icontains=query)
            | Q(applicant_full_name__icontains=query)
            | Q(applicant_iin__icontains=query)
            | Q(program_code__icontains=query)
            | Q(program_name_ru__icontains=query)
            | Q(program_name_kk__icontains=query)
            | Q(document__contract_number__icontains=query)
        )

    date_from = parse_date(filters["date_from"])
    if date_from:
        contracts_qs = contracts_qs.filter(created_at__date__gte=date_from)

    date_to = parse_date(filters["date_to"])
    if date_to:
        contracts_qs = contracts_qs.filter(created_at__date__lte=date_to)

    education_values = {value for value, _label in AdmissionTemplateRule.EducationLevel.choices}
    if filters["education_level"] in education_values:
        contracts_qs = contracts_qs.filter(education_level=filters["education_level"])

    funding_values = {value for value, _label in AdmissionTemplateRule.FundingType.choices}
    if filters["funding_type"] in funding_values:
        contracts_qs = contracts_qs.filter(funding_type=filters["funding_type"])

    contract_status_options = [
        ("created", _("Contract created")),
        ("student_signed", _("Student signed")),
        ("vice_rector_signed", _("Vice rector signed")),
        ("completed", _("Both sides signed")),
    ]
    contract_status_values = {value for value, _label in contract_status_options}

    if filters["status"] in contract_status_values:
        contracts_qs = filter_admission_contracts_by_dashboard_status(
            contracts_qs,
            filters["status"],
        )

    if filters["signature_state"] == "waiting_applicant":
        contracts_qs = contracts_qs.exclude(student_signer__status=Signer.Status.SIGNED)
    elif filters["signature_state"] == "ready_for_vice_rector":
        contracts_qs = contracts_qs.filter(
            student_signer__status=Signer.Status.SIGNED,
        ).exclude(
            vice_rector_signer__status=Signer.Status.SIGNED,
        )
    elif filters["signature_state"] == "completed":
        contracts_qs = contracts_qs.filter(
            student_signer__status=Signer.Status.SIGNED,
        ).filter(
            Q(vice_rector_signer__isnull=True)
            | Q(vice_rector_signer__status=Signer.Status.SIGNED)
        )
    elif filters["signature_state"] == "vice_rector_signed":
        contracts_qs = contracts_qs.filter(vice_rector_signer__status=Signer.Status.SIGNED)

    signature_state_options = [
        ("", _("All signatures")),
        ("waiting_applicant", _("Waiting for applicant")),
        ("ready_for_vice_rector", _("Ready for vice rector")),
        ("completed", _("Fully signed")),
        ("vice_rector_signed", _("Signed by vice rector")),
    ]

    page_obj, page_query_prefix = paginate_admission_contracts(
        request,
        contracts_qs.order_by("-created_at"),
    )
    contracts = list(page_obj.object_list)
    for contract in contracts:
        contract.refresh_status_from_signers(save=False)

    return render(request, "admissions/vice_rector_dashboard.html", {
        "profile": profile,
        "contracts": contracts,
        "filters": filters,
        "total_contracts": total_contracts,
        "filtered_contracts_count": page_obj.paginator.count,
        "page_obj": page_obj,
        "page_query_prefix": page_query_prefix,
        "signature_state_options": signature_state_options,
        "status_options": contract_status_options,
        "education_level_options": AdmissionTemplateRule.EducationLevel.choices,
        "funding_type_options": AdmissionTemplateRule.FundingType.choices,
        **get_admission_user_access(request.user),
    })


def admission_contract_matches_dashboard_status(contract, status):
    student_signed = bool(contract.student_signer and contract.student_signer.is_signed())
    vice_rector_signed = bool(
        contract.vice_rector_signer and contract.vice_rector_signer.is_signed()
    )

    if status == "created":
        return not student_signed and not vice_rector_signed

    if status == "student_signed":
        return student_signed and not vice_rector_signed

    if status == "vice_rector_signed":
        return vice_rector_signed and not student_signed

    if status == "completed":
        return student_signed and vice_rector_signed

    return True


def filter_admission_contracts_by_dashboard_status(contracts_qs, status):
    if status == "created":
        return contracts_qs.exclude(
            Q(student_signer__status=Signer.Status.SIGNED)
            | Q(vice_rector_signer__status=Signer.Status.SIGNED)
        )

    if status == "student_signed":
        return contracts_qs.filter(
            student_signer__status=Signer.Status.SIGNED,
        ).exclude(
            vice_rector_signer__status=Signer.Status.SIGNED,
        )

    if status == "vice_rector_signed":
        return contracts_qs.filter(
            vice_rector_signer__status=Signer.Status.SIGNED,
        ).exclude(
            student_signer__status=Signer.Status.SIGNED,
        )

    if status == "completed":
        return contracts_qs.filter(
            student_signer__status=Signer.Status.SIGNED,
            vice_rector_signer__status=Signer.Status.SIGNED,
        )

    return contracts_qs


def paginate_admission_contracts(request, contracts_qs):
    paginator = Paginator(contracts_qs, ADMISSION_DASHBOARD_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    query_params = request.GET.copy()
    query_params.pop("page", None)
    page_querystring = query_params.urlencode()
    page_query_prefix = f"{page_querystring}&" if page_querystring else ""

    return page_obj, page_query_prefix


@login_required(login_url="accounts:admission_login")
def commission_dashboard(request):
    profile = getattr(request.user, "admission_commission_profile", None)

    if not profile or not profile.is_active:
        return HttpResponseForbidden(_("Admission commission cabinet is not available for this account."))

    filters = {
        "q": request.GET.get("q", "").strip(),
        "status": request.GET.get("status", "").strip(),
        "date_from": request.GET.get("date_from", "").strip(),
        "date_to": request.GET.get("date_to", "").strip(),
        "education_level": request.GET.get("education_level", "").strip(),
        "funding_type": request.GET.get("funding_type", "").strip(),
    }

    contracts_qs = (
        AdmissionContract.objects
        .select_related(
            "document",
            "application_document",
            "template_rule",
            "student_signer",
            "vice_rector_signer",
            "template_rule__vice_rector",
            "template_rule__vice_rector__organization",
            "template_rule__vice_rector__department",
        )
        .filter(template_rule__vice_rector__organization=profile.organization)
    )

    if profile.department_id:
        contracts_qs = contracts_qs.filter(
            template_rule__vice_rector__department=profile.department,
        )

    total_contracts = contracts_qs.count()

    if filters["q"]:
        query = filters["q"]
        contracts_qs = contracts_qs.filter(
            Q(external_id__icontains=query)
            | Q(applicant_full_name__icontains=query)
            | Q(applicant_iin__icontains=query)
            | Q(program_code__icontains=query)
            | Q(program_name_ru__icontains=query)
            | Q(program_name_kk__icontains=query)
            | Q(document__contract_number__icontains=query)
        )

    date_from = parse_date(filters["date_from"])
    if date_from:
        contracts_qs = contracts_qs.filter(created_at__date__gte=date_from)

    date_to = parse_date(filters["date_to"])
    if date_to:
        contracts_qs = contracts_qs.filter(created_at__date__lte=date_to)

    education_values = {value for value, _label in AdmissionTemplateRule.EducationLevel.choices}
    if filters["education_level"] in education_values:
        contracts_qs = contracts_qs.filter(education_level=filters["education_level"])

    funding_values = {value for value, _label in AdmissionTemplateRule.FundingType.choices}
    if filters["funding_type"] in funding_values:
        contracts_qs = contracts_qs.filter(funding_type=filters["funding_type"])

    contract_status_options = [
        ("created", _("Contract created")),
        ("student_signed", _("Student signed")),
        ("vice_rector_signed", _("Vice rector signed")),
        ("completed", _("Both sides signed")),
    ]
    contract_status_values = {value for value, _label in contract_status_options}

    if filters["status"] in contract_status_values:
        contracts_qs = filter_admission_contracts_by_dashboard_status(
            contracts_qs,
            filters["status"],
        )

    page_obj, page_query_prefix = paginate_admission_contracts(
        request,
        contracts_qs.order_by("-created_at"),
    )
    contracts = list(page_obj.object_list)
    for contract in contracts:
        contract.refresh_status_from_signers(save=False)
        ensure_admission_contract_urls(request=request, contract=contract)
        contract.university_protected_url = (contract.protected_url or "").strip()
        contract.can_be_deleted_by_commission = AdmissionContractDeletionService.can_delete(contract)

    return render(request, "admissions/commission_dashboard.html", {
        "profile": profile,
        "contracts": contracts,
        "filters": filters,
        "total_contracts": total_contracts,
        "filtered_contracts_count": page_obj.paginator.count,
        "page_obj": page_obj,
        "page_query_prefix": page_query_prefix,
        "status_options": contract_status_options,
        "education_level_options": AdmissionTemplateRule.EducationLevel.choices,
        "funding_type_options": AdmissionTemplateRule.FundingType.choices,
        **get_admission_user_access(request.user),
    })


@login_required(login_url="accounts:admission_login")
@require_POST
def commission_delete_contract(request, pk):
    profile = getattr(request.user, "admission_commission_profile", None)

    if not profile or not profile.is_active:
        return HttpResponseForbidden(_("Admission commission cabinet is not available for this account."))

    contract = get_commission_contract(profile=profile, pk=pk)

    if not contract:
        return HttpResponseForbidden(_("Admission contract is not available."))

    try:
        result = AdmissionContractDeletionService.delete_contract(contract=contract)
    except AdmissionContractDeletionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            _("Applicant %(external_id)s and related documents were deleted.")
            % {"external_id": result["external_id"]},
        )

    return redirect("admissions:commission_dashboard")


@login_required(login_url="accounts:admission_login")
@require_GET
def vice_rector_ecp_signing_payload(request, pk):
    profile = getattr(request.user, "admission_vice_rector_profile", None)

    if not profile or not profile.is_active:
        return JsonResponse({"ok": False, "error": _("Vice rector cabinet is not available for this account.")}, status=403)

    contract = get_vice_rector_contract(profile=profile, pk=pk)
    if not contract:
        return JsonResponse({"ok": False, "error": _("Admission contract is not available.")}, status=404)

    contract.refresh_status_from_signers()
    signer = contract.vice_rector_signer

    if not signer:
        return JsonResponse({"ok": False, "error": _("Vice rector signer is not available.")}, status=400)

    if signer.is_signed():
        return JsonResponse({"ok": False, "error": _("Signer already signed.")}, status=400)

    if not contract.student_signer or not contract.student_signer.is_signed():
        return JsonResponse({"ok": False, "error": _("The applicant must sign the contract first.")}, status=400)

    try:
        SignerService.ensure_can_sign_now(signer=signer)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return prepare_admission_ecp_signing_payload(
        request=request,
        signer=signer,
        source="admissions_vice_rector",
    )


@login_required(login_url="accounts:admission_login")
@require_POST
def vice_rector_ecp_signing_complete(request, pk):
    profile = getattr(request.user, "admission_vice_rector_profile", None)

    if not profile or not profile.is_active:
        return JsonResponse({"ok": False, "error": _("Vice rector cabinet is not available for this account.")}, status=403)

    contract = get_vice_rector_contract(profile=profile, pk=pk)
    if not contract:
        return JsonResponse({"ok": False, "error": _("Admission contract is not available.")}, status=404)

    contract.refresh_status_from_signers()
    signer = contract.vice_rector_signer

    if not signer:
        return JsonResponse({"ok": False, "error": _("Vice rector signer is not available.")}, status=400)

    if signer.is_signed():
        return JsonResponse({"ok": False, "error": _("Signer already signed.")}, status=400)

    if not contract.student_signer or not contract.student_signer.is_signed():
        return JsonResponse({"ok": False, "error": _("The applicant must sign the contract first.")}, status=400)

    try:
        SignerService.ensure_can_sign_now(signer=signer)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    signature, error_response = complete_admission_ecp_signature(
        request=request,
        signer=signer,
    )
    if error_response:
        return error_response

    contract.refresh_status_from_signers()
    AdmissionMssqlMirrorService.sync_contract(
        contract=contract,
        raise_on_error=False,
    )

    return JsonResponse({
        "ok": True,
        "signature_id": signature.id,
        "redirect_url": request.build_absolute_uri(reverse("admissions:vice_rector_dashboard")),
    })


@login_required(login_url="accounts:admission_login")
@require_POST
def vice_rector_sign_contract(request, pk):
    profile = getattr(request.user, "admission_vice_rector_profile", None)

    if not profile or not profile.is_active:
        return HttpResponseForbidden(_("Vice rector cabinet is not available for this account."))

    contract = get_vice_rector_contract(profile=profile, pk=pk)

    if not contract:
        return HttpResponseForbidden(_("Admission contract is not available."))

    contract.refresh_status_from_signers()
    signer = contract.vice_rector_signer

    if not signer:
        messages.error(request, _("Vice rector signer is not available."))
        return redirect("admissions:vice_rector_dashboard")

    if signer.is_signed():
        messages.info(request, _("This document is already signed by the vice rector."))
        return redirect("admissions:vice_rector_dashboard")

    if not contract.student_signer or not contract.student_signer.is_signed():
        messages.error(request, _("The applicant must sign the contract first."))
        return redirect("admissions:vice_rector_dashboard")

    try:
        SignerService.ensure_can_sign_now(signer=signer)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("admissions:vice_rector_dashboard")

    signer.signing_method = Signer.SigningMethod.ECP
    signer.status = Signer.Status.SIGNING_STARTED
    signer.save(update_fields=["signing_method", "status", "updated_at"])

    messages.info(request, _("ECP signing is ready in the vice rector cabinet."))
    return redirect("admissions:vice_rector_dashboard")


def get_vice_rector_contract(*, profile, pk):
    return (
        AdmissionContract.objects
        .select_related("document", "student_signer", "vice_rector_signer", "template_rule")
        .filter(pk=pk, template_rule__vice_rector=profile)
        .first()
    )


def get_commission_contract(*, profile, pk):
    contracts_qs = (
        AdmissionContract.objects
        .select_related(
            "document",
            "application_document",
            "student_signer",
            "vice_rector_signer",
            "template_rule",
            "template_rule__vice_rector",
            "template_rule__vice_rector__organization",
            "template_rule__vice_rector__department",
        )
        .filter(
            pk=pk,
            template_rule__vice_rector__organization=profile.organization,
        )
    )

    if profile.department_id:
        contracts_qs = contracts_qs.filter(
            template_rule__vice_rector__department=profile.department,
        )

    return contracts_qs.first()


def get_public_contract(token):
    token_hash = AdmissionContract.hash_access_token(token)

    return (
        AdmissionContract.objects
        .select_related(
            "document",
            "document__template",
            "application_document",
            "application_document__template",
            "student_signer",
            "vice_rector_signer",
            "template_rule",
            "render_job",
        )
        .filter(access_token_hash=token_hash)
        .first()
    )


def get_protected_contract(token):
    token_hash = AdmissionContract.hash_access_token(token)

    return (
        AdmissionContract.objects
        .select_related(
            "document",
            "application_document",
            "student_signer",
            "vice_rector_signer",
            "render_job",
        )
        .filter(protected_access_token_hash=token_hash)
        .first()
    )


def generate_unique_admission_protected_token():
    while True:
        token = AdmissionContract.generate_raw_access_token()
        token_hash = AdmissionContract.hash_access_token(token)

        if not AdmissionContract.objects.filter(protected_access_token_hash=token_hash).exists():
            return token


def ensure_admission_contract_urls(*, request, contract):
    update_fields = []

    if not contract.public_url:
        raw_public_token = getattr(contract, "_raw_access_token", "")
        if raw_public_token:
            contract.public_url = request.build_absolute_uri(
                reverse("admissions:applicant_contract", args=[raw_public_token])
            )
            update_fields.append("public_url")

    if not contract.protected_url or not contract.protected_access_token_hash:
        protected_token = generate_unique_admission_protected_token()
        contract.protected_access_token_hash = AdmissionContract.hash_access_token(protected_token)
        contract.protected_url = request.build_absolute_uri(
            reverse("admissions:protected_contract_link_page", args=[protected_token])
        )
        update_fields.extend(["protected_access_token_hash", "protected_url"])

    if update_fields:
        contract.save(update_fields=[*update_fields, "updated_at"])

    return contract


def get_admission_document_for_kind(contract, kind):
    if kind == "application":
        return contract.application_document

    return contract.document


def is_admission_contract_ready_for_applicant(contract):
    return AdmissionRenderQueueService.is_contract_ready(contract)


def is_admission_document_ready(contract, kind):
    document = get_admission_document_for_kind(contract, kind)
    if not document:
        return False

    return bool(document.rendered_docx_file or document.rendered_pdf_file or document.rendered_html)


def can_edit_admission_contract(contract):
    if not contract or not contract.document_id:
        return False

    if contract.student_signer and contract.student_signer.is_signed():
        return False

    if contract.document.signers.filter(status=Signer.Status.SIGNED).exists():
        return False

    return contract.document.status != Document.Status.SIGNED


def get_admission_contract_signing_readiness_error(contract):
    if (
        contract.funding_type == AdmissionTemplateRule.FundingType.PAID
        and not contract.tuition_amount
    ):
        return _("Tuition amount is required before signing.")

    return ""


def build_admission_edit_fields(contract):
    documents = [
        document
        for document in [contract.application_document, contract.document]
        if document and document.template
    ]
    if not documents:
        return []

    field_names = []
    labels = {}
    field_types = {}
    money_field_names = set()

    for document in documents:
        template_field_names, template_labels, template_types = collect_template_field_metadata(
            document.template,
        )
        append_unique(field_names, template_field_names)
        labels.update({key: value for key, value in template_labels.items() if value})
        field_types.update({key: value for key, value in template_types.items() if value})
        money_field_names.update(MoneyAmountService.get_template_money_field_names(document.template))

    values = {}
    for document in documents:
        values.update({
            value.field_name: value.field_value
            for value in document.field_values.all()
        })

    add_admission_manual_system_fields(
        contract=contract,
        field_names=field_names,
        labels=labels,
        field_types=field_types,
        values=values,
    )

    if should_collect_tuition_amount(contract=contract, field_names=field_names):
        append_unique(field_names, ["tuition_amount"])
        labels.setdefault("tuition_amount", _("Tuition amount"))
        field_types["tuition_amount"] = MoneyAmountService.FIELD_TYPE_MONEY
        money_field_names.add("tuition_amount")
        if not values.get("tuition_amount") and contract.tuition_amount is not None:
            values["tuition_amount"] = MoneyAmountService.format_amount(contract.tuition_amount)

    result = []
    priority_index = {
        field_name: index
        for index, field_name in enumerate(ADMISSION_EDIT_FIELD_PRIORITY)
    }
    ordered_names = sorted(
        field_names,
        key=lambda field_name: (
            priority_index.get(field_name, len(priority_index)),
            field_names.index(field_name),
        ),
    )

    for field_name in ordered_names:
        if not is_admission_field_editable(
            field_name,
            money_field_names,
            contract=contract,
        ):
            continue

        field_type = field_types.get(field_name, "text")
        field_value = values.get(field_name, "")
        is_money = (
            field_type == MoneyAmountService.FIELD_TYPE_MONEY
            or field_name in money_field_names
        )
        money_context = (
            MoneyAmountService.build_value_context(field_name, field_value)
            if is_money
            else {}
        )
        result.append({
            "name": field_name,
            "label": labels.get(field_name) or ADMISSION_EDIT_FIELD_LABELS.get(field_name) or humanize_field_name(field_name),
            "value": field_value,
            "input_type": get_admission_input_type(field_type, field_name),
            "required": is_admission_field_required(contract=contract, field_name=field_name),
            "is_money": is_money,
            "money_full_ru": money_context.get(f"{field_name}_full_ru", ""),
            "money_full_kk": money_context.get(f"{field_name}_full_kk", ""),
        })

    return result


def add_admission_manual_system_fields(*, contract, field_names, labels, field_types, values):
    document = contract.document or contract.application_document
    if not document:
        return

    append_unique(field_names, ADMISSION_MANUAL_SYSTEM_FIELDS)
    labels.setdefault(Document.SYSTEM_CONTRACT_DATE, _("Contract date"))
    field_types[Document.SYSTEM_CONTRACT_DATE] = "date"

    values[Document.SYSTEM_CONTRACT_DATE] = (
        document.contract_date.isoformat()
        if document.contract_date
        else ""
    )


def should_collect_tuition_amount(*, contract, field_names):
    return contract.funding_type == AdmissionTemplateRule.FundingType.PAID


def is_admission_field_required(*, contract, field_name):
    if field_name in ADMISSION_MANUAL_SYSTEM_FIELD_SET:
        return True

    return (
        field_name == "tuition_amount"
        and contract.funding_type == AdmissionTemplateRule.FundingType.PAID
    )


def collect_template_field_metadata(template):
    field_names = list(template.variables or [])
    labels = {}
    field_types = {}

    for group in template.field_schema or []:
        for field in group.get("fields", []):
            key = (field.get("key") or "").strip()
            if not key:
                continue

            append_unique(field_names, [key])
            labels[key] = field.get("label") or ""
            field_types[key] = field.get("type", "text")

    for party in template.parties.prefetch_related("fields").all():
        for field in party.fields.all():
            key = f"{party.variable_prefix}_{field.variable_name}"
            append_unique(field_names, [key])
            labels[key] = str(field.display_label or field.label or "")
            field_types[key] = field.field_type

    return field_names, labels, field_types


def append_unique(target, values):
    seen = set(target)
    for value in values:
        if value and value not in seen:
            target.append(value)
            seen.add(value)


def is_admission_field_editable(field_name, money_field_names, *, contract):
    if not field_name:
        return False

    if (
        field_name == "tuition_amount"
        and contract.funding_type != AdmissionTemplateRule.FundingType.PAID
    ):
        return False

    if field_name in ADMISSION_MANUAL_SYSTEM_FIELD_SET:
        return True

    if field_name in Document.SYSTEM_FIELD_NAMES:
        return False

    if field_name in {
        "external_id",
        "application_id",
        "contract_number",
        "contract_date",
        "contract_year",
        "date",
        "language",
        "funding_type",
        "education_level",
        "side_1_signing_method",
        "side_2_signing_method",
        "side_1_full_name_genitive",
        "applicant_full_name_genitive",
        "student_full_name_genitive",
        "applicant_signature_full_name",
        "student_signature_full_name",
    }:
        return False

    if field_name.startswith("university_") or field_name.startswith("side_2_"):
        return False

    if MoneyAmountService.is_derived_field_name(field_name, money_field_names):
        return False

    return not any(
        field_name.endswith(f"_{suffix}")
        for suffix in MoneyAmountService.DERIVED_SUFFIXES
    )


def humanize_field_name(field_name):
    return " ".join(part for part in field_name.replace("_", " ").split()).capitalize()


def get_admission_input_type(field_type, field_name):
    if field_type == "email" or field_name.endswith("_email"):
        return "email"

    if field_name == Document.SYSTEM_CONTRACT_DATE:
        return "date"

    if field_type in {"number", MoneyAmountService.FIELD_TYPE_MONEY}:
        return "text"

    if field_type == "date":
        return "text"

    return "text"


def update_admission_contract_fields(*, contract, editable_fields, request):
    if not editable_fields:
        return

    new_values = {}

    for field in editable_fields:
        value = request.POST.get(f"field_{field['name']}", field.get("value", "")).strip()
        if field.get("required") and not value:
            raise ValueError(
                _("%(field)s is required.") % {
                    "field": field["label"],
                }
            )

        if field.get("is_money"):
            if not MoneyAmountService.is_valid_amount(value):
                raise ValueError(
                    _("Enter a valid whole amount for %(field)s.") % {
                        "field": field["label"],
                    }
                )
        new_values[field["name"]] = value

    documents = [
        document
        for document in [contract.application_document, contract.document]
        if document
    ]

    manual_system_values = extract_admission_manual_system_values(new_values)
    new_values = {
        field_name: field_value
        for field_name, field_value in new_values.items()
        if field_name not in ADMISSION_MANUAL_SYSTEM_FIELD_SET
    }

    update_admission_document_system_fields(
        document=contract.document,
        system_values=manual_system_values,
    )

    new_values = expand_admission_manual_values(new_values)
    system_field_values = build_admission_system_field_values(contract=contract)
    new_values.update(system_field_values)
    new_values.update(build_admission_basis_values(contract=contract))

    for document in documents:
        for field_name, field_value in new_values.items():
            DocumentFieldValue.objects.update_or_create(
                document=document,
                field_name=field_name,
                defaults={"field_value": field_value},
            )

    update_contract_summary_fields(contract=contract, values=new_values)

    if contract.application_document:
        AdmissionContractBuilder.render_document(
            document=contract.application_document,
            request=request,
            append_verification_page=False,
            system_values=system_field_values,
        )

    if contract.document:
        AdmissionContractBuilder.render_document(
            document=contract.document,
            request=request,
            append_verification_page=True,
            system_values=system_field_values,
        )

    if contract.student_signer and not contract.student_signer.is_signed():
        update_student_signer_from_contract(contract)

    raw_payload = dict(contract.raw_payload or {})
    raw_payload["_manual_edits"] = {
        **new_values,
        **format_admission_manual_system_values(manual_system_values),
    }
    contract.raw_payload = raw_payload
    contract.save(update_fields=[
        "applicant_full_name",
        "applicant_iin",
        "applicant_phone",
        "applicant_email",
        "program_code",
        "program_name_ru",
        "program_name_kk",
        "tuition_amount",
        "raw_payload",
        "updated_at",
    ])


def extract_admission_manual_system_values(values):
    result = {}

    if Document.SYSTEM_CONTRACT_DATE in values:
        result[Document.SYSTEM_CONTRACT_DATE] = parse_admission_contract_date(
            values[Document.SYSTEM_CONTRACT_DATE],
        )

    return result


def parse_admission_contract_date(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError(_("Contract date is required."))

    for date_format in AdmissionPayloadMapper.DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    raise ValueError(_("Enter a valid contract date."))


def update_admission_document_system_fields(*, document, system_values):
    if not document or not system_values:
        return

    update_fields = []

    if Document.SYSTEM_CONTRACT_DATE in system_values:
        document.contract_date = system_values[Document.SYSTEM_CONTRACT_DATE]
        update_fields.append("contract_date")

    if update_fields:
        document.save(update_fields=[*update_fields, "updated_at"])


def build_admission_system_field_values(*, contract):
    document = contract.document or contract.application_document
    if not document:
        return {}

    return document.get_contract_system_values()


def build_admission_basis_values(*, contract):
    if contract.funding_type != AdmissionTemplateRule.FundingType.PAID:
        return {}

    document = contract.document or contract.application_document
    if not document:
        return {}

    contract_number = document.contract_number or document.generate_contract_number()
    return {
        "admission_basis_ru": f"договора № {contract_number}".strip(),
        "admission_basis_kk": f"№ {contract_number} келісімшарт".strip(),
    }


def format_admission_manual_system_values(system_values):
    result = {}

    if Document.SYSTEM_CONTRACT_DATE in system_values:
        result[Document.SYSTEM_CONTRACT_DATE] = (
            system_values[Document.SYSTEM_CONTRACT_DATE].strftime("%d.%m.%Y")
        )

    return result


def build_admission_protected_contract_url(*, request, contract):
    return contract.protected_url or request.build_absolute_uri(
        reverse("admissions:admission_contract_detail_api", args=[contract.pk])
    )


def build_admission_contract_detail_payload(*, request, contract):
    document = contract.document
    protected_contract_url = build_admission_protected_contract_url(
        request=request,
        contract=contract,
    )
    render_job = getattr(contract, "render_job", None)

    return {
        "external_id": contract.external_id,
        "externalId": contract.external_id,
        "admission_contract_id": contract.pk,
        "admissionContractId": contract.pk,
        "document_id": contract.document_id,
        "documentId": contract.document_id,
        "application_document_id": contract.application_document_id,
        "applicationDocumentId": contract.application_document_id,
        "status": contract.status,
        "education_level": contract.education_level,
        "educationLevel": contract.education_level,
        "funding_type": contract.funding_type,
        "fundingType": contract.funding_type,
        "language": contract.language,
        "documents_ready": AdmissionRenderQueueService.is_contract_ready(contract),
        "documentsReady": AdmissionRenderQueueService.is_contract_ready(contract),
        "render_status": render_job.status if render_job else "",
        "renderStatus": render_job.status if render_job else "",
        "contract_url": protected_contract_url,
        "contractUrl": protected_contract_url,
        "protected_contract_url": protected_contract_url,
        "protectedContractUrl": protected_contract_url,
        "url": protected_contract_url,
        "link": protected_contract_url,
        "contract": {
            "number": document.contract_number if document else "",
            "date": document.get_contract_date_display() if document else "",
        },
        "applicant": {
            "full_name": contract.applicant_full_name,
            "iin": contract.applicant_iin,
            "phone": contract.applicant_phone,
            "email": contract.applicant_email,
        },
        "program": {
            "code": contract.program_code,
            "name_ru": contract.program_name_ru,
            "name_kk": contract.program_name_kk,
        },
        "tuition": {
            "amount": contract.tuition_amount,
        },
        "signers": {
            "student": build_admission_signer_payload(contract.student_signer),
            "vice_rector": build_admission_signer_payload(contract.vice_rector_signer),
        },
    }


def build_admission_signer_payload(signer):
    if not signer:
        return None

    return {
        "id": signer.pk,
        "full_name": signer.full_name,
        "iin": signer.iin,
        "status": signer.status,
        "signed_at": signer.signed_at.isoformat() if signer.signed_at else None,
    }


def update_contract_summary_fields(*, contract, values):
    contract.applicant_full_name = first_value(
        values,
        "side_1_full_name",
        "applicant_full_name",
        "student_full_name",
        default=contract.applicant_full_name,
    )
    contract.applicant_iin = first_value(
        values,
        "side_1_iin_bin",
        "side_1_iin",
        "applicant_iin",
        "student_iin",
        default=contract.applicant_iin,
    )
    contract.applicant_phone = first_value(
        values,
        "side_1_phone",
        "applicant_phone",
        "student_phone",
        default=contract.applicant_phone,
    )
    contract.applicant_email = first_value(
        values,
        "side_1_email",
        "applicant_email",
        "student_email",
        default=contract.applicant_email,
    )
    contract.program_code = first_value(values, "program_code", default=contract.program_code)
    contract.program_name_ru = first_value(values, "program_name_ru", default=contract.program_name_ru)
    contract.program_name_kk = first_value(values, "program_name_kk", default=contract.program_name_kk)

    if "tuition_amount" in values:
        tuition_amount = first_value(values, "tuition_amount", default="")
        contract.tuition_amount = (
            MoneyAmountService.parse_amount(tuition_amount)
            if tuition_amount
            else None
        )


def expand_admission_manual_values(values):
    expanded = dict(values)

    alias_groups = [
        (
            ["side_1_full_name", "applicant_full_name", "student_full_name"],
            ["side_1_full_name_genitive", "applicant_full_name_genitive", "student_full_name_genitive"],
            AdmissionPayloadMapper.inflect_full_name_genitive,
        ),
        (["side_1_iin_bin", "side_1_iin", "applicant_iin", "student_iin"], [], None),
        (["side_1_phone", "applicant_phone", "student_phone"], [], None),
        (["side_1_email", "applicant_email", "student_email"], [], None),
    ]

    for aliases, derived_aliases, derived_func in alias_groups:
        value = first_value(expanded, *aliases, default="")
        if not value:
            continue

        for alias in aliases:
            expanded.setdefault(alias, value)

        if derived_func:
            derived_value = derived_func(value)
            for alias in derived_aliases:
                expanded[alias] = derived_value

    if "tuition_amount" in expanded:
        tuition_amount = first_value(expanded, "tuition_amount", default="")
        expanded.update(
            MoneyAmountService.build_value_context("tuition_amount", tuition_amount)
        )

    AdmissionPayloadMapper.add_parent_representative_details(expanded)

    return expanded


def update_student_signer_from_contract(contract):
    signer = contract.student_signer
    signer.full_name = contract.applicant_full_name
    signer.iin = contract.applicant_iin
    signer.phone = contract.applicant_phone
    signer.email = contract.applicant_email
    signer.signing_method = Signer.SigningMethod.ECP
    signer.save(update_fields=[
        "full_name",
        "iin",
        "phone",
        "email",
        "signing_method",
        "updated_at",
    ])


def first_value(values, *keys, default=""):
    for key in keys:
        value = values.get(key)
        if value not in [None, ""]:
            return value

    return default
