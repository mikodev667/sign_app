from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from docx import Document as WordDocument
from docx.shared import Cm

from documents.forms import DocumentTemplateUploadForm
from documents.models import (
    Document,
    DocumentFieldValue,
    DocumentTemplate,
    StoredObject,
    TemplateParty,
)
from documents.services.object_storage_service import ObjectStorageService
from documents.services.docx_preview_service import DocxPreviewService
from documents.services.template_file_service import TemplateFileService
from organizations.models import Organization, OrganizationMember


class TemplateFileServiceTests(SimpleTestCase):
    def test_validate_file_name_allows_doc_and_docx(self):
        for file_name in ["template.doc", "template.docx"]:
            with self.subTest(file_name=file_name):
                TemplateFileService.validate_file_name(file_name)

    def test_validate_file_name_rejects_pdf_and_other_formats(self):
        for file_name in ["template.pdf", "template.txt"]:
            with self.subTest(file_name=file_name):
                with self.assertRaises(ValueError):
                    TemplateFileService.validate_file_name(file_name)

    def test_extract_variables_from_text_keeps_order_and_removes_duplicates(self):
        variables = TemplateFileService.extract_variables_from_text(
            "Hello {{ full_name }}. IIN {{ iin }}. Again {{ full_name }}."
        )

        self.assertEqual(variables, ["full_name", "iin"])

    def test_as_docx_path_yields_docx_file_without_conversion(self):
        with TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "template.docx"
            docx_path.write_bytes(self.create_docx_bytes())

            with TemplateFileService.as_docx_path(str(docx_path)) as resolved_path:
                self.assertEqual(resolved_path, str(docx_path))

    def test_convert_to_html_reads_docx_content(self):
        with TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "template.docx"
            docx_path.write_bytes(self.create_docx_bytes("Hello {{ full_name }}"))

            with patch.object(
                DocxPreviewService,
                "convert_docx_to_html_with_libreoffice",
                return_value="",
            ):
                html = TemplateFileService.convert_to_html(str(docx_path))

        self.assertIn("Hello {{ full_name }}", html)

    def test_get_page_layout_reads_docx_page_margins(self):
        with TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "template.docx"
            docx_path.write_bytes(self.create_docx_bytes_with_margins())

            layout = DocxPreviewService.get_page_layout(str(docx_path))

        self.assertEqual(layout["margin_top"], "1")
        self.assertEqual(layout["margin_right"], "1.5")
        self.assertEqual(layout["margin_bottom"], "1.25")
        self.assertEqual(layout["margin_left"], "1.5")
        self.assertTrue(layout["width_px"])
        self.assertTrue(layout["height_px"])

    def test_prepare_editor_html_extracts_body_and_scopes_styles(self):
        html = """<!doctype html>
<html>
<head>
    <style>
        @page { size: A4; margin-left: 1in }
        p, table td { margin-bottom: 0; color: #111827 }
        body { margin: 0 }
    </style>
    <script>alert("x")</script>
</head>
<body lang="kk-KZ" dir="ltr">
    <p>Hello contract</p>
</body>
</html>"""

        prepared = DocxPreviewService.prepare_editor_html(html)

        self.assertIn('class="q-docx-html-fragment"', prepared)
        self.assertIn('lang="kk-KZ"', prepared)
        self.assertIn("Hello contract", prepared)
        self.assertIn(".q-docx-html-fragment p", prepared)
        self.assertIn(".q-docx-html-fragment table td", prepared)
        self.assertNotIn("<html", prepared.lower())
        self.assertNotIn("<body", prepared.lower())
        self.assertNotIn("@page", prepared)
        self.assertNotIn("<script", prepared.lower())

    def test_resolve_soffice_path_accepts_executable_path(self):
        with TemporaryDirectory() as temp_dir:
            soffice_path = Path(temp_dir) / "soffice.exe"
            soffice_path.touch()

            resolved = TemplateFileService.resolve_soffice_path(str(soffice_path))

        self.assertEqual(resolved, str(soffice_path))

    def test_resolve_soffice_path_accepts_program_directory(self):
        with TemporaryDirectory() as temp_dir:
            program_dir = Path(temp_dir) / "program"
            program_dir.mkdir()
            soffice_path = program_dir / "soffice.exe"
            soffice_path.touch()

            resolved = TemplateFileService.resolve_soffice_path(str(program_dir))

        self.assertEqual(resolved, str(soffice_path))

    @staticmethod
    def create_docx_bytes(text="Hello {{ full_name }}"):
        buffer = BytesIO()
        document = WordDocument()
        document.add_paragraph(text)
        document.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def create_docx_bytes_with_margins():
        buffer = BytesIO()
        document = WordDocument()
        section = document.sections[0]
        section.top_margin = Cm(1)
        section.right_margin = Cm(1.5)
        section.bottom_margin = Cm(1.25)
        section.left_margin = Cm(1.5)
        document.add_paragraph("Document with custom margins")
        document.save(buffer)
        return buffer.getvalue()


class TemplateUploadFlowTests(TestCase):
    def test_upload_form_rejects_pdf(self):
        user, organization = self.create_user_and_organization()
        form = DocumentTemplateUploadForm(
            data={
                "organization": str(organization.pk),
                "title": "PDF template",
                "status": "active",
            },
            files={
                "template_file": SimpleUploadedFile(
                    "template.pdf",
                    b"%PDF-1.4",
                    content_type="application/pdf",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("template_file", form.errors)

    def test_docx_upload_stores_editable_html_and_variables(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            self.client.force_login(user)

            response = self.client.post(
                reverse("documents:template_upload"),
                {
                    "title": "DOCX template",
                    "status": "active",
                    "template_file": SimpleUploadedFile(
                        "template.docx",
                        self.create_docx_bytes("Hello {{ full_name }}"),
                        content_type=(
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                    ),
                },
            )

            self.assertRedirects(response, reverse("documents:template_list"))

            template = DocumentTemplate.objects.get(title="DOCX template")
            self.assertTrue(template.template_file.name.endswith(".docx"))
            self.assertEqual(template.organization, organization)
            self.assertIn("Hello {{ full_name }}", template.body_template)
            self.assertEqual(template.variables, ["full_name"])

    def test_doc_upload_is_normalized_to_docx(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            template = DocumentTemplate.objects.create(
                organization=organization,
                created_by=user,
                title="DOC template",
            )
            template.template_file.save(
                "legacy.doc",
                ContentFile(b"legacy binary content"),
                save=True,
            )

            def fake_convert_doc_to_docx(*, file_path, output_path):
                Path(output_path).write_bytes(
                    self.create_docx_bytes("Converted {{ contract_number }}")
                )

            with patch.object(
                TemplateFileService,
                "convert_doc_to_docx",
                side_effect=fake_convert_doc_to_docx,
            ):
                converted = TemplateFileService.normalize_template_file_to_docx(template)

            template.refresh_from_db()

            self.assertTrue(converted)
            self.assertTrue(template.template_file.name.endswith(".docx"))
            self.assertIn("contract_number", TemplateFileService.extract_variables(
                template.template_file.path
            ))

    @staticmethod
    def create_docx_bytes(text):
        buffer = BytesIO()
        document = WordDocument()
        document.add_paragraph(text)
        document.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def create_user_and_organization():
        user = get_user_model().objects.create_user(
            username="owner",
            password="password",
        )
        organization = Organization.objects.create(
            name="Test Organization",
            created_by=user,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=user,
            role=OrganizationMember.Role.OWNER,
        )
        return user, organization


class ObjectStorageServiceTests(TestCase):
    @override_settings(
        MINIO_BUCKET="test-bucket",
        MINIO_DEFAULT_RETENTION_DAYS=30,
        OBJECT_STORAGE_ENABLED=True,
    )
    def test_store_bytes_sets_minio_object_retention_for_uploaded_version(self):
        user, organization = self.create_user_and_organization()
        template = DocumentTemplate.objects.create(
            organization=organization,
            created_by=user,
            title="Storage template",
        )
        document = Document.objects.create(
            organization=organization,
            template=template,
            created_by=user,
            title="Storage document",
        )

        class FakeMinioClient:
            def __init__(self):
                self.retention_calls = []

            def put_object(self, *args, **kwargs):
                return SimpleNamespace(version_id="version-1", etag="etag-1")

            def set_object_retention(self, *args, **kwargs):
                self.retention_calls.append((args, kwargs))

        client = FakeMinioClient()

        with patch.object(ObjectStorageService, "_client", return_value=client):
            stored_object = ObjectStorageService.store_bytes(
                document=document,
                data=b"final document bytes",
                filename="final.pdf",
                content_type="application/pdf",
                object_type=StoredObject.ObjectType.FINAL_PDF,
                created_by=user,
            )

        self.assertEqual(stored_object.version_id, "version-1")
        self.assertEqual(stored_object.retention_mode, StoredObject.RetentionMode.COMPLIANCE)
        self.assertIsNotNone(stored_object.retention_until)
        self.assertEqual(len(client.retention_calls), 1)

        args, kwargs = client.retention_calls[0]
        self.assertEqual(args[0], "test-bucket")
        self.assertEqual(args[1], stored_object.object_key)
        self.assertEqual(args[2].mode, "COMPLIANCE")
        self.assertEqual(args[2].retain_until_date, stored_object.retention_until)
        self.assertEqual(kwargs["version_id"], "version-1")

    @staticmethod
    def create_user_and_organization():
        user = get_user_model().objects.create_user(
            username="storage-owner",
            password="password",
        )
        organization = Organization.objects.create(
            name="Storage Organization",
            created_by=user,
        )
        return user, organization


class DocumentDraftEditingTests(TestCase):
    def test_create_document_from_uploaded_docx_without_template(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            self.client.force_login(user)

            response = self.client.post(
                reverse("documents:document_create"),
                {
                    "title": "Uploaded document",
                    "document_file": SimpleUploadedFile(
                        "ready.docx",
                        self.create_docx_bytes("Ready document"),
                        content_type=(
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                    ),
                },
            )

            document = Document.objects.get(title="Uploaded document")

            self.assertRedirects(
                response,
                reverse("documents:document_editor", args=[document.pk]),
            )
            self.assertEqual(document.organization, organization)
            self.assertIsNone(document.template)
            self.assertTrue(document.rendered_docx_file.name.endswith(".docx"))
            self.assertTrue(document.content_hash)

    def test_create_document_from_uploaded_doc_is_converted_to_docx(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            self.client.force_login(user)

            def fake_convert_doc_to_docx(*, file_path, output_path):
                Path(output_path).write_bytes(self.create_docx_bytes("Converted document"))

            with patch.object(
                TemplateFileService,
                "convert_doc_to_docx",
                side_effect=fake_convert_doc_to_docx,
            ):
                response = self.client.post(
                    reverse("documents:document_create"),
                    {
                        "title": "Uploaded legacy document",
                        "document_file": SimpleUploadedFile(
                            "legacy.doc",
                            b"legacy binary content",
                            content_type="application/msword",
                        ),
                    },
                )

            document = Document.objects.get(title="Uploaded legacy document")

            self.assertRedirects(
                response,
                reverse("documents:document_editor", args=[document.pk]),
            )
            self.assertEqual(document.organization, organization)
            self.assertIsNone(document.template)
            self.assertTrue(document.rendered_docx_file.name.endswith(".docx"))
            self.assertTrue(document.content_hash)

    def test_uploaded_document_editor_shows_docx_content(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            document = Document.objects.create(
                organization=organization,
                created_by=user,
                title="Uploaded document",
                status=Document.Status.DRAFT,
            )
            document.rendered_docx_file.save(
                "ready.docx",
                ContentFile(self.create_docx_bytes("Ready document")),
                save=True,
            )
            self.client.force_login(user)

            with patch.object(
                DocxPreviewService,
                "convert_docx_to_html_with_libreoffice",
                return_value="",
            ):
                response = self.client.get(reverse("documents:document_editor", args=[document.pk]))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Ready document")
            self.assertContains(response, "data-editor-content")

    def test_uploaded_document_editor_uses_docx_page_layout(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            document = Document.objects.create(
                organization=organization,
                created_by=user,
                title="Uploaded document",
                status=Document.Status.DRAFT,
            )
            document.rendered_docx_file.save(
                "ready.docx",
                ContentFile(self.create_docx_bytes_with_margins("Ready document")),
                save=True,
            )
            self.client.force_login(user)

            with patch.object(
                DocxPreviewService,
                "convert_docx_to_html_with_libreoffice",
                return_value="",
            ):
                response = self.client.get(reverse("documents:document_editor", args=[document.pk]))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'data-default-margin-left="1.5"')
            self.assertContains(response, 'data-default-margin-right="1.5"')
            self.assertContains(response, "padding: 1cm 1.5cm 1.25cm 1.5cm;")

    def test_document_list_shows_edit_link_for_uploaded_draft_document(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            document = Document.objects.create(
                organization=organization,
                created_by=user,
                title="Uploaded document",
                status=Document.Status.DRAFT,
            )
            document.rendered_docx_file.save(
                "ready.docx",
                ContentFile(self.create_docx_bytes("Ready document")),
                save=True,
            )
            self.client.force_login(user)

            response = self.client.get(reverse("documents:document_list"))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, reverse("documents:document_editor", args=[document.pk]))

    def test_uploaded_document_editor_saves_html_and_redirects_to_signers(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            document = Document.objects.create(
                organization=organization,
                created_by=user,
                title="Uploaded document",
                status=Document.Status.DRAFT,
            )
            document.rendered_docx_file.save(
                "ready.docx",
                ContentFile(self.create_docx_bytes("Ready document")),
                save=True,
            )
            self.client.force_login(user)

            response = self.client.post(
                reverse("documents:document_editor", args=[document.pk]),
                {
                    "rendered_html": "<h1>Reviewed document</h1>",
                    "document_changed": "1",
                },
            )

            document.refresh_from_db()
            self.assertRedirects(response, reverse("signing:document_signers", args=[document.pk]))
            self.assertEqual(document.rendered_html, "<h1>Reviewed document</h1>")
            self.assertTrue(document.rendered_docx_file.name.endswith(".docx"))

    def test_uploaded_document_editor_preserves_original_docx_when_unchanged(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            document = Document.objects.create(
                organization=organization,
                created_by=user,
                title="Uploaded document",
                status=Document.Status.DRAFT,
            )
            document.rendered_docx_file.save(
                "ready.docx",
                ContentFile(self.create_docx_bytes("Ready document")),
                save=True,
            )
            original_docx_name = document.rendered_docx_file.name
            self.client.force_login(user)

            response = self.client.post(
                reverse("documents:document_editor", args=[document.pk]),
                {
                    "rendered_html": "<h1>Ready document</h1>",
                    "document_changed": "0",
                },
            )

            document.refresh_from_db()
            self.assertRedirects(response, reverse("signing:document_signers", args=[document.pk]))
            self.assertEqual(document.rendered_html, "")
            self.assertEqual(document.rendered_docx_file.name, original_docx_name)

    def test_uploaded_document_fill_redirects_to_signers_modal(self):
        with TemporaryDirectory() as temp_dir, override_settings(MEDIA_ROOT=temp_dir):
            user, organization = self.create_user_and_organization()
            document = Document.objects.create(
                organization=organization,
                created_by=user,
                title="Uploaded document",
                status=Document.Status.DRAFT,
            )
            document.rendered_docx_file.save(
                "ready.docx",
                ContentFile(self.create_docx_bytes("Ready document")),
                save=True,
            )
            self.client.force_login(user)

            response = self.client.get(reverse("documents:document_fill", args=[document.pk]))

            self.assertRedirects(
                response,
                reverse("signing:document_signers", args=[document.pk]),
            )

    def test_uploaded_document_signers_page_adds_manual_signer(self):
        user, organization = self.create_user_and_organization()
        document = Document.objects.create(
            organization=organization,
            created_by=user,
            title="Uploaded document",
            status=Document.Status.DRAFT,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("signing:document_signers", args=[document.pk]),
            {
                "full_name": "Manual Signer",
                "iin": "123456789012",
                "phone": "+77071234567",
                "signing_order": "1",
                "signing_method": "sms",
            },
        )

        self.assertRedirects(response, reverse("signing:document_signers", args=[document.pk]))
        signer = document.signers.get()
        self.assertEqual(signer.full_name, "Manual Signer")
        self.assertIsNone(signer.template_party)

    def test_document_list_shows_edit_link_only_for_drafts(self):
        user, organization = self.create_user_and_organization()
        template = self.create_template(user, organization)
        draft_document = self.create_document(
            user,
            organization,
            template,
            title="Draft document",
            status=Document.Status.DRAFT,
        )
        locked_document = self.create_document(
            user,
            organization,
            template,
            title="Waiting document",
            status=Document.Status.WAITING_FOR_SIGNERS,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("documents:document_list"))

        self.assertContains(
            response,
            reverse("documents:document_fill", args=[draft_document.pk]),
        )
        self.assertNotContains(
            response,
            reverse("documents:document_fill", args=[locked_document.pk]),
        )

    def test_document_fill_redirects_when_document_is_not_draft(self):
        user, organization = self.create_user_and_organization()
        template = self.create_template(user, organization)
        document = self.create_document(
            user,
            organization,
            template,
            status=Document.Status.WAITING_FOR_SIGNERS,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("documents:document_fill", args=[document.pk]))

        self.assertRedirects(response, reverse("documents:document_list"))

    def test_document_fill_handles_invalid_template_party_signer_data(self):
        user, organization = self.create_user_and_organization()
        template = self.create_template(user, organization)
        party = TemplateParty.objects.create(
            template=template,
            title="Customer",
            variable_prefix="customer",
            is_signer=True,
        )
        document = self.create_document(user, organization, template)
        for field_name in [
            "customer_full_name",
            "customer_iin_bin",
            "customer_phone",
        ]:
            DocumentFieldValue.objects.create(
                document=document,
                field_name=field_name,
            )
        self.client.force_login(user)
        field_inputs = {
            field.field_name: field.id
            for field in document.field_values.all()
        }

        response = self.client.post(
            reverse("documents:document_fill", args=[document.pk]),
            {
                f"field_{field_inputs['customer_full_name']}": "Test Signer",
                f"field_{field_inputs['customer_iin_bin']}": "123",
                f"field_{field_inputs['customer_phone']}": "+77071234567",
            },
        )

        self.assertRedirects(response, reverse("documents:document_fill", args=[document.pk]))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("ИИН должен содержать ровно 12 цифр" in str(item) for item in messages))

    @staticmethod
    def create_template(user, organization):
        return DocumentTemplate.objects.create(
            organization=organization,
            created_by=user,
            title="Editable template",
            body_template=(
                "Hello {{ full_name }} {{ customer_full_name }} "
                "{{ customer_iin_bin }} {{ customer_phone }}"
            ),
            variables=[
                "full_name",
                "customer_full_name",
                "customer_iin_bin",
                "customer_phone",
            ],
        )

    @staticmethod
    def create_document(user, organization, template, title="Document", status=Document.Status.DRAFT):
        return Document.objects.create(
            organization=organization,
            template=template,
            created_by=user,
            title=title,
            status=status,
        )

    @staticmethod
    def create_docx_bytes(text):
        buffer = BytesIO()
        document = WordDocument()
        document.add_paragraph(text)
        document.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def create_docx_bytes_with_margins(text):
        buffer = BytesIO()
        document = WordDocument()
        section = document.sections[0]
        section.top_margin = Cm(1)
        section.right_margin = Cm(1.5)
        section.bottom_margin = Cm(1.25)
        section.left_margin = Cm(1.5)
        document.add_paragraph(text)
        document.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def create_user_and_organization():
        user = get_user_model().objects.create_user(
            username="document-owner",
            password="password",
        )
        organization = Organization.objects.create(
            name="Document Test Organization",
            created_by=user,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=user,
            role=OrganizationMember.Role.OWNER,
        )
        return user, organization


class OrganizationAccessTests(TestCase):
    def test_organization_admin_sees_templates_and_documents_created_by_another_user(self):
        owner = self.create_user("owner")
        admin = self.create_user("admin")
        creator = self.create_user("creator")
        organization = self.create_organization(owner)
        OrganizationMember.objects.create(
            organization=organization,
            user=admin,
            role=OrganizationMember.Role.ADMIN,
        )
        template = self.create_template(creator, organization, title="Shared template")
        document = self.create_document(creator, organization, template, title="Shared document")
        self.client.force_login(admin)

        template_list_response = self.client.get(reverse("documents:template_list"))
        document_list_response = self.client.get(reverse("documents:document_list"))

        self.assertContains(template_list_response, "Shared template")
        self.assertContains(document_list_response, "Shared document")
        self.assertEqual(
            self.client.get(reverse("documents:template_edit", args=[template.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("documents:document_fill", args=[document.pk])).status_code,
            200,
        )

    def test_organization_member_cannot_see_or_access_templates_and_documents(self):
        owner = self.create_user("owner")
        member = self.create_user("member")
        organization = self.create_organization(owner)
        OrganizationMember.objects.create(
            organization=organization,
            user=member,
            role=OrganizationMember.Role.MEMBER,
        )
        template = self.create_template(owner, organization, title="Manager template")
        document = self.create_document(owner, organization, template, title="Manager document")
        self.client.force_login(member)

        template_list_response = self.client.get(reverse("documents:template_list"))
        document_list_response = self.client.get(reverse("documents:document_list"))

        self.assertNotContains(template_list_response, "Manager template")
        self.assertNotContains(document_list_response, "Manager document")
        self.assertEqual(
            self.client.get(reverse("documents:template_edit", args=[template.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("documents:document_fill", args=[document.pk])).status_code,
            404,
        )

    def test_foreign_admin_cannot_access_other_organization_documents(self):
        owner = self.create_user("owner")
        foreign_owner = self.create_user("foreign-owner")
        organization = self.create_organization(owner, name="Owner Org")
        foreign_organization = self.create_organization(foreign_owner, name="Foreign Org")
        template = self.create_template(owner, organization)
        document = self.create_document(owner, organization, template)
        self.client.force_login(foreign_owner)

        self.assertNotContains(
            self.client.get(reverse("documents:document_list")),
            document.title,
        )
        self.assertEqual(
            self.client.get(reverse("documents:document_fill", args=[document.pk])).status_code,
            404,
        )
        self.assertNotEqual(organization.pk, foreign_organization.pk)

    @staticmethod
    def create_user(username):
        return get_user_model().objects.create_user(
            username=username,
            password="password",
        )

    @staticmethod
    def create_organization(user, name="Access Organization"):
        organization = Organization.objects.create(
            name=name,
            created_by=user,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=user,
            role=OrganizationMember.Role.OWNER,
        )
        return organization

    @staticmethod
    def create_template(user, organization, title="Access template"):
        return DocumentTemplate.objects.create(
            organization=organization,
            created_by=user,
            title=title,
            body_template="Hello {{ full_name }}",
            variables=["full_name"],
        )

    @staticmethod
    def create_document(user, organization, template, title="Access document"):
        return Document.objects.create(
            organization=organization,
            template=template,
            created_by=user,
            title=title,
            status=Document.Status.DRAFT,
        )
