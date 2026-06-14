from .services.document_docx_render_service import DocumentDocxRenderService
import json
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_http_methods

from organizations.services import (
    get_default_managed_organization,
    get_user_managed_organizations,
)
from signing.models import Signer
from signing.services.signer_service import SignerService

from .forms import (
    DocumentTemplateUploadForm,
    DocumentCreateForm,
    DocumentFromTemplateForm,
    TemplatePartyForm,
    TemplatePartyFieldForm,
)
from .models import (
    DocumentTemplate,
    Document,
    DocumentFieldValue,
    DocumentLawVisionReport,
    TemplateParty,
    TemplatePartyField,
)
from .services.lawvision_service import LawVisionError, LawVisionService
from .services.template_file_service import TemplateFileService


VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def get_managed_templates_queryset(user):
    return (
        DocumentTemplate.objects
        .filter(organization__in=get_user_managed_organizations(user))
        .select_related("organization", "created_by")
        .distinct()
    )


def get_managed_documents_queryset(user):
    return (
        Document.objects
        .filter(organization__in=get_user_managed_organizations(user))
        .select_related("template", "organization", "created_by")
        .distinct()
    )


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


def attach_lawvision_reports(documents):
    documents = list(documents)
    document_ids = [document.id for document in documents if document.content_hash]
    content_hashes = [document.content_hash for document in documents if document.content_hash]

    reports = (
        DocumentLawVisionReport.objects
        .filter(
            document_id__in=document_ids,
            content_hash__in=content_hashes,
            status=DocumentLawVisionReport.Status.SUCCESS,
        )
        .order_by("-created_at")
    )

    report_by_key = {}
    for report in reports:
        key = (report.document_id, report.content_hash)
        report_by_key.setdefault(key, report)

    for document in documents:
        document.lawvision_report = report_by_key.get(
            (document.id, document.content_hash)
        )

    return documents


def can_request_lawvision_report(document):
    return bool(
        document.rendered_pdf_file
        or document.rendered_docx_file
        or document.rendered_html
    )


def render_lawvision_report_page(
    request,
    *,
    document,
    report,
    start_url,
    back_url,
    is_public=False,
):
    return render(request, "documents/lawvision_report.html", {
        "document": document,
        "report": report,
        "analysis": report.analysis if report else {},
        "metadata": report.metadata if report else {},
        "start_url": start_url,
        "back_url": back_url,
        "is_public": is_public,
        "can_start_analysis": can_request_lawvision_report(document),
    })


def create_field_values_for_template(document):
    for variable in document.template.variables or []:
        DocumentFieldValue.objects.get_or_create(
            document=document,
            field_name=variable,
            defaults={"field_value": ""},
        )

    field_schema = document.template.field_schema or []

    for group in field_schema:
        for field in group.get("fields", []):
            field_key = field.get("key", "").strip()

            if field_key:
                DocumentFieldValue.objects.get_or_create(
                    document=document,
                    field_name=field_key,
                    defaults={"field_value": ""},
                )

    for party in document.template.parties.prefetch_related("fields").all():
        for field in party.fields.all():
            field_key = f"{party.variable_prefix}_{field.variable_name}"

            DocumentFieldValue.objects.get_or_create(
                document=document,
                field_name=field_key,
                defaults={"field_value": field.default_value or ""},
            )


def get_template_preview_html(template):
    if template.body_template:
        return template.body_template

    if template.template_file:
        try:
            return TemplateFileService.convert_to_html(template.template_file.path)
        except ValueError:
            return ""

    return ""


def collect_field_schema_variables(field_schema):
    variables = []

    for group in field_schema or []:
        for field in group.get("fields", []):
            key = field.get("key", "").strip()
            if key:
                variables.append(key)

    return variables


def collect_party_variables(template):
    variables = []

    for party in template.parties.prefetch_related("fields").all():
        for field in party.fields.all():
            variables.append(f"{party.variable_prefix}_{field.variable_name}")

    return variables


def collect_template_variables(template, *, body_template="", field_schema=None):
    return list(dict.fromkeys(
        VARIABLE_PATTERN.findall(body_template or "")
        + collect_field_schema_variables(field_schema)
        + collect_party_variables(template)
    ))


def prepare_uploaded_template_file(template):
    TemplateFileService.normalize_template_file_to_docx(template)

    template.body_template = TemplateFileService.convert_to_html(
        template.template_file.path
    )
    template.variables = TemplateFileService.extract_variables(
        template.template_file.path
    )
    template.save(update_fields=[
        "body_template",
        "variables",
        "updated_at",
    ])


def ensure_document_editable_or_redirect(request, document):
    if hasattr(document, "can_be_edited") and not document.can_be_edited():
        messages.error(
            request,
            "Document cannot be edited after signer invitation.",
        )
        return redirect("documents:document_list")

    return None


@login_required
def template_list(request):
    templates = get_managed_templates_queryset(request.user).order_by("-created_at")

    return render(request, "documents/template_list.html", {
        "templates": templates,
    })


@login_required
def template_upload(request):
    organization = get_default_managed_organization(request.user)

    if not organization:
        messages.error(
            request,
            "Create an organization or ask an organization owner to add you first.",
        )
        return redirect("accounts:profile")

    if request.method == "POST":
        form = DocumentTemplateUploadForm(request.POST, request.FILES)

        if form.is_valid():
            template = form.save(commit=False)
            template.organization = organization
            template.created_by = request.user
            template.save()

            if template.template_file:
                try:
                    prepare_uploaded_template_file(template)
                except ValueError as exc:
                    template.template_file.delete(save=False)
                    template.delete()
                    form.add_error("template_file", str(exc))
                    return render(request, "documents/template_upload.html", {
                        "form": form,
                        "organization": organization,
                    })

            messages.success(request, "DOCX template uploaded successfully.")
            return redirect("documents:template_list")
    else:
        form = DocumentTemplateUploadForm()

    return render(request, "documents/template_upload.html", {
        "form": form,
        "organization": organization,
    })


@login_required
def document_list(request):
    documents = attach_lawvision_reports(
        get_managed_documents_queryset(request.user).order_by("-created_at")
    )

    return render(request, "documents/document_list.html", {
        "documents": documents,
    })


@login_required
@require_http_methods(["GET", "POST"])
def document_lawvision_report(request, pk):
    document = get_object_or_404(
        get_managed_documents_queryset(request.user),
        pk=pk,
    )

    report = get_current_lawvision_report(document, include_failed=True)

    if request.method == "POST":
        try:
            report, cached = LawVisionService.get_or_analyze_document(
                document=document,
                requested_by=request.user,
                source=DocumentLawVisionReport.Source.MANAGER,
                force=request.POST.get("force") == "1",
            )
        except LawVisionError as exc:
            report = get_current_lawvision_report(document, include_failed=True)
            messages.error(request, f"LawVision analysis failed: {exc}")
        else:
            if cached:
                messages.info(request, "Using saved LawVision report for this document.")
            else:
                messages.success(request, "LawVision report is ready.")

    return render_lawvision_report_page(
        request,
        document=document,
        report=report,
        start_url=reverse("documents:document_lawvision_report", args=[document.pk]),
        back_url=reverse("documents:document_list"),
    )


@login_required
def document_create(request):
    if request.method == "POST":
        form = DocumentCreateForm(request.POST, user=request.user)

        if form.is_valid():
            document = form.save(commit=False)
            document.organization = document.template.organization
            document.created_by = request.user
            document.status = Document.Status.DRAFT
            document.save()

            create_field_values_for_template(document)

            messages.success(request, "Document created. Fill the variables.")
            return redirect("documents:document_fill", pk=document.pk)
    else:
        form = DocumentCreateForm(user=request.user)

    return render(request, "documents/document_create.html", {
        "form": form,
    })


def create_signers_from_template_parties(document, values, request=None):
    for party in document.template.parties.prefetch_related("fields").all():
        if not party.is_signer:
            continue

        prefix = party.variable_prefix

        full_name = values.get(f"{prefix}_full_name", "").strip()
        iin = values.get(f"{prefix}_iin_bin", "").strip()
        phone = values.get(f"{prefix}_phone", "").strip()
        signing_method = values.get(f"{prefix}_signing_method", "").strip()

        if not signing_method:
            signing_method = Signer.SigningMethod.EGOV_MOBILE

        if not full_name or not iin or not phone:
            continue

        existing_signer = Signer.objects.filter(
            document=document,
            template_party=party,
        ).first()

        if existing_signer:
            existing_signer.full_name = full_name
            existing_signer.iin = iin
            existing_signer.phone = SignerService.normalize_phone(phone)
            existing_signer.signing_method = signing_method
            existing_signer.signing_order = party.signing_order
            existing_signer.role_title = party.title
            existing_signer.save(update_fields=[
                "full_name",
                "iin",
                "phone",
                "signing_method",
                "signing_order",
                "role_title",
                "updated_at",
            ])
        else:
            SignerService.add_signer(
                document=document,
                full_name=full_name,
                iin=iin,
                phone=phone,
                signing_order=party.signing_order,
                signing_method=signing_method,
                template_party=party,
                role_title=party.title,
                request=request,
            )


@login_required
def document_fill(request, pk):
    document = get_object_or_404(
        get_managed_documents_queryset(request.user),
        pk=pk,
    )

    locked_redirect = ensure_document_editable_or_redirect(request, document)
    if locked_redirect:
        return locked_redirect

    fields = document.field_values.all().order_by("field_name")
    parties = document.template.parties.prefetch_related("fields").all()

    if request.method == "POST":
        values = {}

        for field in fields:
            value = request.POST.get(f"field_{field.id}", "")
            field.field_value = value
            field.save(update_fields=["field_value"])
            values[field.field_name] = value

        create_signers_from_template_parties(document, values, request=request)

        rendered_html = document.template.body_template or ""

        for key, value in values.items():
            rendered_html = re.sub(
                r"{{\s*" + re.escape(key) + r"\s*}}",
                escape(value),
                rendered_html,
            )

        document.rendered_html = rendered_html
        document.status = Document.Status.DRAFT
        document.save(update_fields=[
            "rendered_html",
            "status",
            "updated_at",
        ])

        try:
            DocumentDocxRenderService.render(document)
        except (FileNotFoundError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect("documents:document_fill", pk=document.pk)

        messages.success(request, "Document prepared. Invite signers.")
        return redirect("signing:document_signers", document.pk)

    return render(request, "documents/document_fill.html", {
        "document": document,
        "fields": fields,
        "parties": parties,
        "preview_html": get_template_preview_html(document.template),
    })


@login_required
def document_render_docx(request, pk):
    document = get_object_or_404(
        get_managed_documents_queryset(request.user),
        pk=pk,
    )

    locked_redirect = ensure_document_editable_or_redirect(request, document)
    if locked_redirect:
        return locked_redirect

    try:
        DocumentDocxRenderService.render(document)
    except (FileNotFoundError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("documents:document_fill", pk=document.pk)

    document.update_content_hash(save=True)

    messages.success(request, "DOCX document rendered successfully.")
    return redirect("documents:document_list")


@login_required
def template_edit(request, pk):
    template = get_object_or_404(
        get_managed_templates_queryset(request.user),
        pk=pk,
    )

    if request.method == "POST":
        body_template = request.POST.get("body_template", "")
        field_schema_raw = request.POST.get("field_schema", "[]")

        try:
            field_schema = json.loads(field_schema_raw)
        except json.JSONDecodeError:
            field_schema = []

        template.body_template = body_template
        template.field_schema = field_schema
        template.variables = collect_template_variables(
            template,
            body_template=body_template,
            field_schema=field_schema,
        )

        template.save(update_fields=[
            "body_template",
            "field_schema",
            "variables",
            "updated_at",
        ])

        messages.success(request, "Template saved successfully.")
        return redirect("documents:template_edit", pk=template.pk)

    if template.body_template:
        editor_html = template.body_template
    elif template.template_file:
        try:
            editor_html = TemplateFileService.convert_to_html(template.template_file.path)
        except ValueError as exc:
            messages.warning(request, str(exc))
            editor_html = ""
    else:
        editor_html = ""

    parties = template.parties.prefetch_related("fields").all()

    return render(request, "documents/template_edit.html", {
        "template": template,
        "editor_html": editor_html,
        "field_schema_json": json.dumps(template.field_schema or [], ensure_ascii=False),
        "parties": parties,
        "party_form": TemplatePartyForm(),
        "party_field_form": TemplatePartyFieldForm(),
    })


@login_required
def document_create_from_template(request, template_pk):
    template = get_object_or_404(
        get_managed_templates_queryset(request.user),
        pk=template_pk,
    )

    if request.method == "POST":
        form = DocumentFromTemplateForm(request.POST)

        if form.is_valid():
            document = form.save(commit=False)
            document.template = template
            document.organization = template.organization
            document.created_by = request.user
            document.status = Document.Status.DRAFT
            document.save()

            create_field_values_for_template(document)

            messages.success(request, "Document created. Fill the fields.")
            return redirect("documents:document_fill", pk=document.pk)
    else:
        form = DocumentFromTemplateForm(initial={
            "title": template.title,
        })

    return render(request, "documents/document_create_from_template.html", {
        "form": form,
        "template": template,
    })


@login_required
def template_party_create(request, template_pk):
    template = get_object_or_404(
        get_managed_templates_queryset(request.user),
        pk=template_pk,
    )

    if request.method == "POST":
        form = TemplatePartyForm(request.POST)

        if form.is_valid():
            variable_prefix = form.cleaned_data["variable_prefix"].strip()

            exists = TemplateParty.objects.filter(
                template=template,
                variable_prefix=variable_prefix,
            ).exists()

            if exists:
                messages.error(
                    request,
                    f"Party with prefix '{variable_prefix}' already exists.",
                )
                return redirect("documents:template_edit", pk=template.pk)

            party = form.save(commit=False)
            party.template = template
            party.save()

            messages.success(request, "Document party created.")
        else:
            messages.error(request, "Could not create document party.")

    return redirect("documents:template_edit", pk=template.pk)


@login_required
def template_party_field_create(request, template_pk, party_pk):
    template = get_object_or_404(
        get_managed_templates_queryset(request.user),
        pk=template_pk,
    )

    party = get_object_or_404(
        TemplateParty,
        pk=party_pk,
        template=template,
    )

    if request.method == "POST":
        form = TemplatePartyFieldForm(request.POST)

        if form.is_valid():
            variable_name = form.cleaned_data["variable_name"].strip()

            exists = TemplatePartyField.objects.filter(
                party=party,
                variable_name=variable_name,
            ).exists()

            if exists:
                messages.error(
                    request,
                    f"Field '{variable_name}' already exists in this party.",
                )
                return redirect("documents:template_edit", pk=template.pk)

            field = form.save(commit=False)
            field.party = party
            field.is_system = False
            field.save()

            messages.success(request, "Party field created.")
        else:
            messages.error(request, "Could not create party field.")

    return redirect("documents:template_edit", pk=template.pk)


@login_required
def template_party_delete(request, template_pk, party_pk):
    template = get_object_or_404(
        get_managed_templates_queryset(request.user),
        pk=template_pk,
    )

    party = get_object_or_404(
        TemplateParty,
        pk=party_pk,
        template=template,
    )

    if request.method == "POST":
        party.delete()
        messages.success(request, "Special party group deleted.")

    return redirect("documents:template_edit", pk=template.pk)


@login_required
def template_party_field_delete(request, template_pk, party_pk, field_pk):
    template = get_object_or_404(
        get_managed_templates_queryset(request.user),
        pk=template_pk,
    )

    party = get_object_or_404(
        TemplateParty,
        pk=party_pk,
        template=template,
    )

    field = get_object_or_404(
        TemplatePartyField,
        pk=field_pk,
        party=party,
    )

    if request.method == "POST":
        if field.is_system:
            messages.error(request, "System fields cannot be deleted.")
        else:
            field.delete()
            messages.success(request, "Party field deleted.")

    return redirect("documents:template_edit", pk=template.pk)
