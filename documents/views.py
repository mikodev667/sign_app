from .services.docx_template_service import DocxTemplateService
from .services.document_docx_render_service import DocumentDocxRenderService
import json
import re
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .services.docx_preview_service import DocxPreviewService
from django.utils.html import escape
from signing.models import Signer
from django.db import transaction
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
    TemplateParty,
    TemplatePartyField,
)

def ensure_document_editable_or_redirect(request, document):
    if hasattr(document, "can_be_edited") and not document.can_be_edited():
        messages.error(
            request,
            "Document cannot be edited after signer invitation."
        )
        return redirect("documents:document_list")

    return None

@login_required
def template_list(request):
    templates = DocumentTemplate.objects.filter(
        created_by=request.user
    ).order_by("-created_at")

    return render(request, "documents/template_list.html", {
        "templates": templates
    })


@login_required
def template_upload(request):
    if request.method == "POST":
        form = DocumentTemplateUploadForm(request.POST, request.FILES)

        if form.is_valid():
            template = form.save(commit=False)
            template.created_by = request.user
            template.save()

            if template.template_file:
                template.variables = DocxTemplateService.extract_variables(
                    template.template_file.path
                )
                template.save(update_fields=["variables", "updated_at"])

            messages.success(request, "DOCX template uploaded successfully.")
            return redirect("documents:template_list")
    else:
        form = DocumentTemplateUploadForm()

    return render(request, "documents/template_upload.html", {
        "form": form
    })


@login_required
def document_list(request):
    documents = Document.objects.filter(
        created_by=request.user
    ).select_related("template", "organization").order_by("-created_at")

    return render(request, "documents/document_list.html", {
        "documents": documents
    })


@login_required
def document_create(request):
    if request.method == "POST":
        form = DocumentCreateForm(request.POST)

        if form.is_valid():
            document = form.save(commit=False)
            document.created_by = request.user
            document.status = Document.Status.DRAFT
            document.save()

            for variable in document.template.variables or []:
                DocumentFieldValue.objects.get_or_create(
                    document=document,
                    field_name=variable,
                    defaults={"field_value": ""}
                )

            messages.success(request, "Document created. Fill the variables.")
            return redirect("documents:document_fill", pk=document.pk)
    else:
        form = DocumentCreateForm()

    return render(request, "documents/document_create.html", {
        "form": form
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
        Document.objects.select_related("template", "organization"),
        pk=pk,
        created_by=request.user
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
                rendered_html
            )

        document.rendered_html = rendered_html
        document.status = Document.Status.DRAFT
        document.update_content_hash(save=False)
        document.save(update_fields=[
            "rendered_html",
            "status",
            "content_hash",
            "updated_at",
        ])

        DocumentDocxRenderService.render(document)

        messages.success(request, "Document prepared. Invite signers.")
        return redirect("signing:document_signers", document.pk)

    return render(request, "documents/document_fill.html", {
        "document": document,
        "fields": fields,
        "parties": parties,
    })

@login_required
def document_render_docx(request, pk):
    document = get_object_or_404(
        Document,
        pk=pk,
        created_by=request.user
    )

    locked_redirect = ensure_document_editable_or_redirect(request, document)
    if locked_redirect:
        return locked_redirect

    DocumentDocxRenderService.render(document)

    document.update_content_hash(save=True)

    messages.success(request, "DOCX document rendered successfully.")
    return redirect("documents:document_list")


VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


@login_required
def template_edit(request, pk):
    template = get_object_or_404(
        DocumentTemplate,
        pk=pk,
        created_by=request.user
    )

    if request.method == "POST":
        body_template = request.POST.get("body_template", "")
        field_schema_raw = request.POST.get("field_schema", "[]")

        try:
            field_schema = json.loads(field_schema_raw)
        except json.JSONDecodeError:
            field_schema = []

        variables_from_document = VARIABLE_PATTERN.findall(body_template)

        variables_from_schema = []
        for group in field_schema:
            for field in group.get("fields", []):
                key = field.get("key", "").strip()
                if key:
                    variables_from_schema.append(key)

        all_variables = list(dict.fromkeys(
            variables_from_document + variables_from_schema
        ))

        template.body_template = body_template
        template.field_schema = field_schema
        template.variables = all_variables

        template.save(update_fields=[
            "body_template",
            "field_schema",
            "variables",
            "updated_at"
        ])

        messages.success(request, "Template saved successfully.")
        return redirect("documents:template_edit", pk=template.pk)

    if template.body_template:
        editor_html = template.body_template
    elif template.template_file:
        editor_html = DocxPreviewService.convert_docx_to_html(
            template.template_file.path
        )
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
        DocumentTemplate,
        pk=template_pk,
        created_by=request.user
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

            field_schema = template.field_schema or []

            for group in field_schema:
                for field in group.get("fields", []):
                    field_key = field.get("key", "").strip()

                    if field_key:
                        DocumentFieldValue.objects.get_or_create(
                            document=document,
                            field_name=field_key,
                            defaults={"field_value": ""}
                        )

            for party in template.parties.prefetch_related("fields").all():
                for field in party.fields.all():
                    field_key = f"{party.variable_prefix}_{field.variable_name}"

                    DocumentFieldValue.objects.get_or_create(
                        document=document,
                        field_name=field_key,
                        defaults={"field_value": field.default_value or ""}
                    )

            messages.success(request, "Document created. Fill the fields.")
            return redirect("documents:document_fill", pk=document.pk)
    else:
        form = DocumentFromTemplateForm(initial={
            "title": template.title
        })

    return render(request, "documents/document_create_from_template.html", {
        "form": form,
        "template": template,
    })


@login_required
def template_party_create(request, template_pk):
    template = get_object_or_404(
        DocumentTemplate,
        pk=template_pk,
        created_by=request.user
    )

    if request.method == "POST":
        form = TemplatePartyForm(request.POST)

        if form.is_valid():
            variable_prefix = form.cleaned_data["variable_prefix"].strip()

            exists = TemplateParty.objects.filter(
                template=template,
                variable_prefix=variable_prefix
            ).exists()

            if exists:
                messages.error(
                    request,
                    f"Party with prefix '{variable_prefix}' already exists."
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
        DocumentTemplate,
        pk=template_pk,
        created_by=request.user
    )

    party = get_object_or_404(
        TemplateParty,
        pk=party_pk,
        template=template
    )

    if request.method == "POST":
        form = TemplatePartyFieldForm(request.POST)

        if form.is_valid():
            variable_name = form.cleaned_data["variable_name"].strip()

            exists = TemplatePartyField.objects.filter(
                party=party,
                variable_name=variable_name
            ).exists()

            if exists:
                messages.error(
                    request,
                    f"Field '{variable_name}' already exists in this party."
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
        DocumentTemplate,
        pk=template_pk,
        created_by=request.user
    )

    party = get_object_or_404(
        TemplateParty,
        pk=party_pk,
        template=template
    )

    if request.method == "POST":
        party.delete()
        messages.success(request, "Special party group deleted.")

    return redirect("documents:template_edit", pk=template.pk)


@login_required
def template_party_field_delete(request, template_pk, party_pk, field_pk):
    template = get_object_or_404(
        DocumentTemplate,
        pk=template_pk,
        created_by=request.user
    )

    party = get_object_or_404(
        TemplateParty,
        pk=party_pk,
        template=template
    )

    field = get_object_or_404(
        TemplatePartyField,
        pk=field_pk,
        party=party
    )

    if request.method == "POST":
        if field.is_system:
            messages.error(request, "System fields cannot be deleted.")
        else:
            field.delete()
            messages.success(request, "Party field deleted.")

    return redirect("documents:template_edit", pk=template.pk)