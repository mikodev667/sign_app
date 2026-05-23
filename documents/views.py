from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import DocumentTemplateUploadForm, DocumentCreateForm
from .models import DocumentTemplate, Document, DocumentFieldValue
from .services.docx_template_service import DocxTemplateService
from .services.document_docx_render_service import DocumentDocxRenderService


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
        for field in fields:
            value = request.POST.get(f"field_{field.id}", "")
            field.field_value = value
            field.save(update_fields=["field_value"])

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