from .forms import DocumentTemplateUploadForm, DocumentCreateForm
from .models import DocumentTemplate, Document, DocumentFieldValue
from .services.docx_template_service import DocxTemplateService
from .services.document_docx_render_service import DocumentDocxRenderService
import json
import re
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .models import DocumentTemplate
from .services.docx_preview_service import DocxPreviewService
from django.utils.html import escape

from .forms import DocumentFromTemplateForm

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


@login_required
def document_fill(request, pk):
    document = get_object_or_404(
        Document.objects.select_related("template", "organization"),
        pk=pk,
        created_by=request.user
    )

    fields = document.field_values.all().order_by("field_name")

    if request.method == "POST":
        values = {}

        for field in fields:
            value = request.POST.get(f"field_{field.id}", "")
            field.field_value = value
            field.save(update_fields=["field_value"])
            values[field.field_name] = value

        rendered_html = document.template.body_template or ""

        for key, value in values.items():
            rendered_html = re.sub(
                r"{{\s*" + re.escape(key) + r"\s*}}",
                escape(value),
                rendered_html
            )

        document.rendered_html = rendered_html
        document.update_content_hash(save=False)
        document.save(update_fields=["rendered_html", "content_hash", "updated_at"])

        messages.success(request, "Document fields saved.")
        return redirect("documents:document_render_docx", pk=document.pk)

    return render(request, "documents/document_fill.html", {
        "document": document,
        "fields": fields
    })


@login_required
def document_render_docx(request, pk):
    document = get_object_or_404(
        Document,
        pk=pk,
        created_by=request.user
    )

    DocumentDocxRenderService.render(document)

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

    return render(request, "documents/template_edit.html", {
        "template": template,
        "editor_html": editor_html,
        "field_schema_json": json.dumps(template.field_schema or [], ensure_ascii=False),
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