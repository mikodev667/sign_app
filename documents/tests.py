from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from docx import Document as WordDocument

from documents.forms import DocumentTemplateUploadForm
from documents.models import Document, DocumentTemplate
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

            html = TemplateFileService.convert_to_html(str(docx_path))

        self.assertIn("Hello {{ full_name }}", html)

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


class DocumentDraftEditingTests(TestCase):
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

    @staticmethod
    def create_template(user, organization):
        return DocumentTemplate.objects.create(
            organization=organization,
            created_by=user,
            title="Editable template",
            body_template="Hello {{ full_name }}",
            variables=["full_name"],
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
