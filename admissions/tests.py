import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from admissions.models import (
    AdmissionApiClient,
    AdmissionCommissionProfile,
    AdmissionContract,
    AdmissionRenderJob,
    AdmissionTemplateRule,
    AdmissionViceRectorProfile,
)
from admissions.services.payload_mapper import AdmissionPayloadMapper
from documents.models import Document, DocumentFieldValue, DocumentTemplate, TemplateParty
from documents.services.document_verification_appendix_service import (
    DocumentVerificationAppendixService,
)
from organizations.models import Department, Organization
from signing.models import (
    Signer,
    SignerAccessToken,
    SigningAuditLog,
    SigningSession,
    Signature,
)
from admissions.services.render_queue_service import AdmissionRenderQueueService


class AdmissionsApiTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="owner",
            password="pass",
        )
        self.vice_rector_user = get_user_model().objects.create_user(
            username="vice",
            password="pass",
        )
        self.commission_user = get_user_model().objects.create_user(
            username="commission",
            password="pass",
        )
        self.organization = Organization.objects.create(
            name="KazNU",
            created_by=self.owner,
        )
        self.department = Department.objects.create(
            organization=self.organization,
            name="Admissions",
        )
        self.template = DocumentTemplate.objects.create(
            organization=self.organization,
            department=self.department,
            created_by=self.owner,
            title="Admission Template",
            body_template=(
                "{{ side_1_full_name }} {{ side_1_iin_bin }} "
                "{{ side_2_full_name }} {{ tuition_amount_full_ru }}"
            ),
            variables=[
                "side_1_full_name",
                "side_1_iin_bin",
                "side_2_full_name",
                "tuition_amount_full_ru",
            ],
        )
        self.student_party = TemplateParty.objects.create(
            template=self.template,
            title="Student",
            variable_prefix="side_1",
            signing_order=1,
            is_signer=True,
        )
        self.vice_party = TemplateParty.objects.create(
            template=self.template,
            title="Vice rector",
            variable_prefix="side_2",
            signing_order=2,
            is_signer=True,
        )
        self.application_template = DocumentTemplate.objects.create(
            organization=self.organization,
            department=self.department,
            created_by=self.owner,
            title="Admission Application",
            body_template=(
                "{{ side_1_full_name_genitive }} {{ program_group_name_ru }} "
                "{{ contract_number }}"
            ),
            variables=[
                "side_1_full_name_genitive",
                "program_group_name_ru",
                "contract_number",
            ],
        )
        self.vice_rector = AdmissionViceRectorProfile.objects.create(
            user=self.vice_rector_user,
            organization=self.organization,
            department=self.department,
            full_name="Vice Rector",
            iin="222222222222",
            phone="77012223344",
            is_active=True,
        )
        self.commission_profile = AdmissionCommissionProfile.objects.create(
            user=self.commission_user,
            organization=self.organization,
            department=self.department,
            full_name="Commission Member",
            is_active=True,
        )
        self.rule = AdmissionTemplateRule.objects.create(
            title="Bachelor paid RU",
            education_level=AdmissionTemplateRule.EducationLevel.BACHELOR,
            funding_type=AdmissionTemplateRule.FundingType.PAID,
            language=AdmissionTemplateRule.Language.RU,
            template=self.template,
            application_template=self.application_template,
            vice_rector=self.vice_rector,
        )
        self.raw_api_token = AdmissionApiClient.generate_raw_token()
        self.api_client = AdmissionApiClient.objects.create(
            name="University",
            token_hash=AdmissionApiClient.hash_token(self.raw_api_token),
        )

    def test_admission_contract_api_requires_bearer_token(self):
        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_admission_contract_api_creates_contract_document_and_signers(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        contract = AdmissionContract.objects.get(pk=body["admission_contract_id"])

        self.assertEqual(contract.external_id, "app-1")
        self.assertEqual(contract.document.title, "Admission Template - Student Name - app-1")
        self.assertEqual(
            contract.application_document.title,
            "Admission Application - Student Name - app-1",
        )
        self.assertIsNone(contract.application_document.contract_number)
        self.assertEqual(
            DocumentVerificationAppendixService.get_external_reference(contract.document),
            "app-1",
        )
        self.assertEqual(
            DocumentVerificationAppendixService.get_external_reference(contract.application_document),
            "app-1",
        )
        self.assertEqual(contract.student_signer.signing_method, Signer.SigningMethod.ECP)
        self.assertEqual(contract.vice_rector_signer.signing_method, Signer.SigningMethod.ECP)
        self.assertEqual(contract.student_signer.signing_order, 1)
        self.assertEqual(contract.vice_rector_signer.signing_order, 2)
        public_token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]
        self.assertIn("/admissions/contracts/", contract.public_url)
        self.assertIn("/admissions/contracts/protected/", body["protected_contract_url"])
        self.assertEqual(set(body), {
            "status",
            "external_id",
            "admission_contract_id",
            "document_id",
            "protected_contract_url",
        })
        self.assertEqual(
            AdmissionContract.hash_access_token(public_token),
            contract.access_token_hash,
        )

        field_values = {
            value.field_name: value.field_value
            for value in DocumentFieldValue.objects.filter(document=contract.document)
        }
        self.assertEqual(field_values["side_1_full_name"], "Student Name")
        self.assertEqual(field_values["side_1_iin_bin"], "111111111111")
        self.assertEqual(field_values["side_2_full_name"], "Vice Rector")
        self.assertEqual(field_values["side_1_full_name_genitive"], "Student Name")
        self.assertEqual(field_values["student_address"], "Almaty")
        self.assertEqual(field_values["student_faculty"], "FIBS")
        self.assertEqual(field_values["identity_document_number"], "ID123456")
        self.assertEqual(field_values["father_full_name"], "Father Name")
        self.assertNotIn("student_parent_full_name", field_values)

        application_field_values = {
            value.field_name: value.field_value
            for value in DocumentFieldValue.objects.filter(document=contract.application_document)
        }
        self.assertEqual(application_field_values["side_1_full_name_genitive"], "Student Name")
        self.assertEqual(application_field_values["program_group_name_ru"], "Computer Science")
        self.assertEqual(
            application_field_values["contract_number"],
            field_values["contract_number"],
        )
        self.assertEqual(render_mock.call_count, 2)
        self.assertIs(render_mock.call_args_list[0].kwargs["append_verification_page"], False)
        self.assertIs(render_mock.call_args_list[1].kwargs["append_verification_page"], True)

        response = self.client.get(body["protected_contract_url"])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, contract.public_url)
        self.assertContains(response, "Student Name")

        response = self.client.get(
            reverse("admissions:admission_contract_detail_api", args=[contract.pk]),
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["external_id"], "app-1")
        self.assertEqual(detail["externalId"], "app-1")
        self.assertEqual(detail["admission_contract_id"], contract.pk)
        self.assertEqual(detail["admissionContractId"], contract.pk)
        self.assertEqual(detail["document_id"], contract.document_id)
        self.assertEqual(detail["documentId"], contract.document_id)
        self.assertEqual(detail["contract_url"], body["protected_contract_url"])
        self.assertEqual(detail["protected_contract_url"], body["protected_contract_url"])
        self.assertEqual(detail["protectedContractUrl"], body["protected_contract_url"])
        self.assertEqual(detail["contractUrl"], body["protected_contract_url"])
        self.assertEqual(detail["applicant"]["iin"], "111111111111")
        self.assertEqual(detail["signers"]["vice_rector"]["iin"], "222222222222")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_admission_contract_api_updates_existing_contract_for_duplicate_external_id(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="duplicate-app")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        self.assertEqual(response.status_code, 201)
        first_body = response.json()
        contract = AdmissionContract.objects.get(pk=first_body["admission_contract_id"])
        first_public_url = contract.public_url

        updated_payload = self.payload(external_id="duplicate-app")
        updated_payload["applicant"]["full_name"] = "Updated Student"
        updated_payload["applicant"]["iin"] = "333333333333"
        updated_payload["program"]["name_ru"] = "Updated Program"
        updated_payload["tuition"]["amount"] = 1500000

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(updated_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 200)
        second_body = response.json()
        self.assertEqual(second_body["status"], "updated")
        self.assertEqual(second_body["protected_contract_url"], first_body["protected_contract_url"])
        self.assertEqual(set(second_body), {
            "status",
            "external_id",
            "admission_contract_id",
            "document_id",
            "protected_contract_url",
        })
        self.assertEqual(AdmissionContract.objects.filter(external_id="duplicate-app").count(), 1)
        self.assertEqual(render_mock.call_count, 4)

        contract.refresh_from_db()
        contract.student_signer.refresh_from_db()
        self.assertEqual(contract.public_url, first_public_url)
        self.assertEqual(contract.applicant_full_name, "Updated Student")
        self.assertEqual(contract.applicant_iin, "333333333333")
        self.assertEqual(contract.program_name_ru, "Updated Program")
        self.assertEqual(contract.tuition_amount, 1500000)
        self.assertEqual(contract.student_signer.full_name, "Updated Student")
        self.assertEqual(contract.student_signer.iin, "333333333333")

        field_values = {
            value.field_name: value.field_value
            for value in DocumentFieldValue.objects.filter(document=contract.document)
        }
        self.assertEqual(field_values["side_1_full_name"], "Updated Student")
        self.assertEqual(field_values["side_1_iin_bin"], "333333333333")
        self.assertEqual(field_values["program_name_ru"], "Updated Program")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_admission_contract_api_blocks_update_after_student_signature(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="signed-duplicate-app")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        self.assertEqual(response.status_code, 201)
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.student_signer.mark_signed()

        updated_payload = self.payload(external_id="signed-duplicate-app")
        updated_payload["applicant"]["full_name"] = "Updated Signed Student"

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(updated_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("cannot be updated", response.json()["error"])
        contract.refresh_from_db()
        self.assertEqual(contract.applicant_full_name, "Student Name")
        self.assertEqual(render_mock.call_count, 2)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.views.AdmissionMssqlMirrorService.sync_contract")
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_admission_contract_api_returns_link_when_mssql_mirror_fails(
        self,
        render_mock,
        sync_contract_mock,
    ):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document
        sync_contract_mock.return_value = False

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="mssql-fail-app")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["status"], "created")
        self.assertIn("/admissions/contracts/protected/", body["protected_contract_url"])
        self.assertEqual(set(body), {
            "status",
            "external_id",
            "admission_contract_id",
            "document_id",
            "protected_contract_url",
        })
        sync_contract_mock.assert_called_once()
        self.assertIs(sync_contract_mock.call_args.kwargs["raise_on_error"], False)

    @override_settings(OBJECT_STORAGE_ENABLED=False, ADMISSIONS_ASYNC_RENDER_ENABLED=True)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_async_admission_contract_api_returns_link_before_render(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="async-app")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        contract = AdmissionContract.objects.get(pk=body["admission_contract_id"])
        job = AdmissionRenderJob.objects.get(contract=contract)

        self.assertEqual(body["status"], "created")
        self.assertIn("/admissions/contracts/protected/", body["protected_contract_url"])
        self.assertEqual(contract.status, AdmissionContract.Status.DOCUMENT_CREATED)
        self.assertEqual(job.status, AdmissionRenderJob.Status.QUEUED)
        self.assertIsNone(contract.student_signer_id)
        self.assertEqual(render_mock.call_count, 0)

        public_token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]
        response = self.client.get(reverse("admissions:applicant_contract", args=[public_token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Documents are being prepared")

        processed = AdmissionRenderQueueService.process_pending(limit=1)
        self.assertEqual(processed, 1)

        contract.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(job.status, AdmissionRenderJob.Status.DONE)
        self.assertEqual(contract.status, AdmissionContract.Status.STUDENT_SIGNING)
        self.assertIsNotNone(contract.student_signer_id)
        self.assertIsNotNone(contract.vice_rector_signer_id)
        self.assertEqual(render_mock.call_count, 2)

    @override_settings(OBJECT_STORAGE_ENABLED=False, ADMISSIONS_ASYNC_RENDER_ENABLED=True)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_async_admission_contract_api_updates_existing_link(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="async-duplicate")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        self.assertEqual(response.status_code, 201)
        first_body = response.json()

        updated_payload = self.payload(external_id="async-duplicate")
        updated_payload["applicant"]["full_name"] = "Async Updated Student"
        updated_payload["applicant"]["iin"] = "444444444444"

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(updated_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 200)
        second_body = response.json()
        self.assertEqual(second_body["status"], "updated")
        self.assertEqual(
            second_body["protected_contract_url"],
            first_body["protected_contract_url"],
        )
        self.assertEqual(AdmissionContract.objects.filter(external_id="async-duplicate").count(), 1)
        self.assertEqual(AdmissionRenderJob.objects.count(), 1)
        self.assertEqual(render_mock.call_count, 0)

        contract = AdmissionContract.objects.get(pk=second_body["admission_contract_id"])
        job = AdmissionRenderJob.objects.get(contract=contract)
        self.assertEqual(contract.applicant_full_name, "Async Updated Student")
        self.assertEqual(contract.applicant_iin, "444444444444")
        self.assertEqual(job.status, AdmissionRenderJob.Status.QUEUED)

        processed = AdmissionRenderQueueService.process_pending(limit=1)
        self.assertEqual(processed, 1)
        contract.refresh_from_db()
        self.assertEqual(contract.student_signer.full_name, "Async Updated Student")
        self.assertEqual(contract.student_signer.iin, "444444444444")
        self.assertEqual(render_mock.call_count, 2)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_vice_rector_phone_can_be_empty_for_ecp_signing(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document
        self.vice_rector.phone = ""
        self.vice_rector.save(update_fields=["phone"])

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="app-without-vice-phone")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        self.assertEqual(contract.vice_rector_signer.phone, "")

        field_values = {
            value.field_name: value.field_value
            for value in DocumentFieldValue.objects.filter(document=contract.document)
        }
        self.assertEqual(field_values["side_2_phone"], "")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_student_phone_can_be_empty_for_admission_ecp_signing(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document
        payload = self.payload(external_id="app-without-student-phone")
        payload["applicant"].pop("phone")

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        self.assertEqual(contract.applicant_phone, "")
        self.assertEqual(contract.student_signer.phone, "")

        field_values = {
            value.field_name: value.field_value
            for value in DocumentFieldValue.objects.filter(document=contract.document)
        }
        self.assertEqual(field_values["side_1_phone"], "")
        self.assertEqual(field_values["applicant_phone"], "")
        self.assertEqual(field_values["student_phone"], "")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_paid_contract_tuition_can_be_entered_on_applicant_page(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document
        payload = self.payload(external_id="app-without-tuition")
        payload.pop("tuition")

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]
        self.assertIsNone(contract.tuition_amount)

        field_values = {
            value.field_name: value.field_value
            for value in DocumentFieldValue.objects.filter(document=contract.document)
        }
        self.assertEqual(field_values["tuition_amount"], "")
        self.assertEqual(field_values["tuition_amount_full_ru"], "")

        response = self.client.get(reverse("admissions:applicant_contract", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="field_tuition_amount"')
        self.assertContains(response, "data-money-preview-input")
        self.assertContains(response, "required")

        response = self.client.get(reverse("admissions:applicant_ecp_signing_payload", args=[token]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Tuition amount is required before signing.")

        response = self.client.post(
            reverse("admissions:applicant_contract", args=[token]),
            data={"field_tuition_amount": "1300000"},
        )
        self.assertEqual(response.status_code, 302)

        contract.refresh_from_db()
        self.assertEqual(contract.tuition_amount, 1300000)
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.document,
                field_name="tuition_amount",
            ).field_value,
            "1 300 000",
        )
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.document,
                field_name="tuition_amount_full_ru",
            ).field_value,
            "1 300 000 (один миллион триста тысяч тенге)",
        )
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.document,
                field_name="tuition_amount_full_kk",
            ).field_value,
            "1 300 000 (бір миллион үш жүз мың теңге)",
        )

        response = self.client.get(reverse("admissions:applicant_ecp_signing_payload", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_grant_contract_does_not_show_tuition_edit_field(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document
        self.rule.funding_type = AdmissionTemplateRule.FundingType.GRANT
        self.rule.save(update_fields=["funding_type"])

        payload = self.payload(external_id="grant-without-tuition")
        payload["funding_type"] = "grant"
        payload.pop("tuition")

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]

        response = self.client.get(reverse("admissions:applicant_contract", args=[token]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="field_tuition_amount"')
        self.assertNotContains(response, "data-money-preview-input")
        self.assertNotContains(response, "Tuition amount")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_paid_rule_can_match_any_education_level(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document
        self.rule.education_level = AdmissionTemplateRule.EducationLevel.ANY
        self.rule.save(update_fields=["education_level"])

        payload = self.payload(
            external_id="app-any",
            education_level="master",
        )

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )

        self.assertEqual(response.status_code, 201)
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        self.assertEqual(contract.template_rule_id, self.rule.id)
        self.assertEqual(contract.education_level, AdmissionTemplateRule.EducationLevel.MASTER)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_applicant_sign_button_stays_on_admission_page(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        body = response.json()
        contract = AdmissionContract.objects.get(pk=body["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]

        response = self.client.post(reverse("admissions:applicant_sign_contract", args=[token]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admissions:applicant_contract", args=[token]))
        self.assertNotIn("/signing/s/", response["Location"])
        self.assertEqual(SignerAccessToken.objects.count(), 0)
        contract.student_signer.refresh_from_db()
        self.assertEqual(contract.student_signer.status, Signer.Status.SIGNING_STARTED)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_applicant_page_is_white_label_and_uses_inline_ecp(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]

        response = self.client.get(reverse("admissions:applicant_contract", args=[token]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "QolQoyu")
        self.assertNotContains(response, "LawVision")
        self.assertNotContains(response, "/signing/s/")
        self.assertContains(response, reverse("admissions:applicant_ecp_signing_payload", args=[token]))

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_admission_ecp_payload_is_prepared_without_signing_link(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]

        response = self.client.get(reverse("admissions:applicant_ecp_signing_payload", args=[token]))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["signer_iin"], "111111111111")
        self.assertEqual(SignerAccessToken.objects.count(), 0)
        contract.student_signer.refresh_from_db()
        self.assertEqual(contract.student_signer.status, Signer.Status.SIGNING_STARTED)

    @override_settings(OBJECT_STORAGE_ENABLED=False, LEDGER_ENABLED=False)
    @patch("signing.services.ecp_signing_service.DocumentLedgerService.submit_document_after_commit")
    @patch("signing.services.ecp_signing_service.EcpValidationClient.verify")
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_admission_ecp_complete_skips_backend_key_validation(
        self,
        render_mock,
        verify_mock,
        submit_ledger_mock,
    ):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]

        self.client.get(reverse("admissions:applicant_ecp_signing_payload", args=[token]))
        response = self.client.post(
            reverse("admissions:applicant_ecp_signing_complete", args=[token]),
            data=json.dumps({
                "cms_signature": "ADMISSION-CMS",
                "certificate_subject": "CN=Other Person, IIN 123456789012",
                "certificate_serial_number": "cert-1",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        verify_mock.assert_not_called()
        submit_ledger_mock.assert_called_once_with(document_id=contract.document_id)

        contract.student_signer.refresh_from_db()
        self.assertEqual(contract.student_signer.status, Signer.Status.SIGNED)

        signature = Signature.objects.get(signer=contract.student_signer)
        self.assertTrue(signature.is_valid)
        self.assertEqual(signature.certificate_iin, "123456789012")
        self.assertTrue(signature.raw_payload["validation_result"]["validation_skipped"])

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_vice_rector_dashboard_is_white_label_and_uses_inline_ecp(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.student_signer.mark_signed()
        contract.refresh_status_from_signers()

        self.client.force_login(self.vice_rector_user)
        response = self.client.get(reverse("admissions:vice_rector_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "QolQoyu")
        self.assertNotContains(response, "LawVision")
        self.assertNotContains(response, "/signing/s/")
        self.assertContains(
            response,
            reverse("admissions:vice_rector_ecp_signing_payload", args=[contract.pk]),
        )
        self.assertContains(
            response,
            reverse("admissions:vice_rector_ecp_signing_complete", args=[contract.pk]),
        )

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_vice_rector_dashboard_filters_contracts(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        first_payload = self.payload(external_id="app-filter-alpha")
        first_payload["applicant"]["full_name"] = "Alpha Student"
        first_response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(first_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        first_contract = AdmissionContract.objects.get(
            pk=first_response.json()["admission_contract_id"]
        )
        first_contract.student_signer.mark_signed()
        first_contract.vice_rector_signer.mark_signed()
        first_contract.refresh_status_from_signers()

        second_payload = self.payload(external_id="app-filter-beta")
        second_payload["applicant"]["full_name"] = "Beta Student"
        second_response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(second_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        AdmissionContract.objects.get(pk=second_response.json()["admission_contract_id"])

        self.client.force_login(self.vice_rector_user)

        response = self.client.get(reverse("admissions:vice_rector_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="created"')
        self.assertContains(response, 'value="student_signed"')
        self.assertContains(response, 'value="vice_rector_signed"')
        self.assertContains(response, 'value="completed"')
        self.assertNotContains(response, 'value="received"')
        self.assertNotContains(response, 'value="failed"')

        response = self.client.get(
            reverse("admissions:vice_rector_dashboard"),
            {"q": "Alpha"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Student")
        self.assertNotContains(response, "Beta Student")

        response = self.client.get(
            reverse("admissions:vice_rector_dashboard"),
            {"signature_state": "completed"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Student")
        self.assertNotContains(response, "Beta Student")

        response = self.client.get(
            reverse("admissions:vice_rector_dashboard"),
            {"status": "completed"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Student")
        self.assertNotContains(response, "Beta Student")

        response = self.client.get(
            reverse("admissions:vice_rector_dashboard"),
            {"status": "created"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Alpha Student")
        self.assertContains(response, "Beta Student")

        response = self.client.get(
            reverse("admissions:vice_rector_dashboard"),
            {"signature_state": "waiting_applicant"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Alpha Student")
        self.assertContains(response, "Beta Student")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_commission_dashboard_is_white_label_read_only_document_list(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="commission-doc")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.document.rendered_docx_file.name = "documents/docx/contract.docx"
        contract.document.save(update_fields=["rendered_docx_file"])
        contract.application_document.rendered_docx_file.name = "documents/docx/application.docx"
        contract.application_document.save(update_fields=["rendered_docx_file"])

        self.client.force_login(self.commission_user)
        response = self.client.get(reverse("admissions:commission_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "QolQoyu")
        self.assertNotContains(response, "LawVision")
        self.assertNotContains(response, "Sign with ECP")
        self.assertContains(response, "Commission Member")
        self.assertContains(response, "Student Name")
        self.assertContains(response, "Application DOCX")
        self.assertContains(response, "Contract DOCX")

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_commission_dashboard_backfills_missing_protected_url(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="commission-missing-protected")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.protected_url = ""
        contract.protected_access_token_hash = None
        contract.save(update_fields=["protected_url", "protected_access_token_hash"])

        self.client.force_login(self.commission_user)
        response = self.client.get(reverse("admissions:commission_dashboard"))

        contract.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(contract.protected_url)
        self.assertIn("/admissions/contracts/protected/", contract.protected_url)
        self.assertContains(response, contract.protected_url)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_commission_can_delete_unsigned_admission_contract(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="commission-delete-unsigned")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        document_ids = [contract.document_id, contract.application_document_id]
        signer_ids = [contract.student_signer_id, contract.vice_rector_signer_id]

        self.client.force_login(self.commission_user)
        response = self.client.post(
            reverse("admissions:commission_delete_contract", args=[contract.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AdmissionContract.objects.filter(pk=contract.pk).exists())
        self.assertFalse(Document.objects.filter(pk__in=document_ids).exists())
        self.assertFalse(Signer.objects.filter(pk__in=signer_ids).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_commission_can_delete_after_only_student_signed(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="commission-delete-student-signed")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        document = contract.document
        student_signer = contract.student_signer

        document.content_hash = "a" * 64
        document.status = Document.Status.PARTIALLY_SIGNED
        document.save(update_fields=["content_hash", "status", "updated_at"])
        student_signer.mark_signed()
        session = SigningSession.objects.create(
            signer=student_signer,
            provider=SigningSession.Provider.ECP,
            status=SigningSession.Status.SIGNED,
            document_hash=document.content_hash,
            used_at=timezone.now(),
        )
        signature = Signature.objects.create(
            signer=student_signer,
            document=document,
            signing_session=session,
            provider=SigningSession.Provider.ECP,
            signed_content_hash=document.content_hash,
            signed_at=timezone.now(),
            is_valid=True,
        )
        audit_log = SigningAuditLog.objects.create(
            document=document,
            signer=student_signer,
            signing_session=session,
            event=SigningAuditLog.Event.SIGNATURE_CREATED,
            signing_method=Signer.SigningMethod.ECP,
            iin=student_signer.iin,
            full_name=student_signer.full_name,
            document_hash=document.content_hash,
            signed_content_hash=document.content_hash,
            metadata={"signature_id": signature.id},
        )
        contract.refresh_status_from_signers()

        self.client.force_login(self.commission_user)
        response = self.client.post(
            reverse("admissions:commission_delete_contract", args=[contract.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AdmissionContract.objects.filter(pk=contract.pk).exists())
        self.assertFalse(Document.objects.filter(pk=document.pk).exists())
        self.assertFalse(Signature.objects.filter(pk=signature.pk).exists())
        self.assertFalse(SigningSession.objects.filter(pk=session.pk).exists())
        self.assertFalse(SigningAuditLog.objects.filter(pk=audit_log.pk).exists())

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_commission_cannot_delete_after_vice_rector_signed(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="commission-delete-blocked")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.student_signer.mark_signed()
        contract.vice_rector_signer.mark_signed()
        contract.refresh_status_from_signers()

        self.client.force_login(self.commission_user)
        response = self.client.post(
            reverse("admissions:commission_delete_contract", args=[contract.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AdmissionContract.objects.filter(pk=contract.pk).exists())
        self.assertTrue(Document.objects.filter(pk=contract.document_id).exists())

    def test_admission_login_redirects_commission_user_to_admissions_dashboard(self):
        response = self.client.post(reverse("accounts:admission_login"), {
            "username": "commission",
            "password": "pass",
        })

        self.assertRedirects(
            response,
            reverse("admissions:dashboard"),
            fetch_redirect_response=False,
        )

    def test_admissions_dashboard_lists_available_cabinets_without_branding(self):
        self.client.force_login(self.commission_user)

        response = self.client.get(reverse("admissions:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "QolQoyu")
        self.assertContains(response, reverse("admissions:commission_dashboard"))
        self.assertNotContains(response, reverse("admissions:vice_rector_dashboard"))

        self.client.force_login(self.vice_rector_user)
        response = self.client.get(reverse("admissions:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admissions:vice_rector_dashboard"))

    def test_commission_user_cannot_open_vice_rector_dashboard(self):
        self.client.force_login(self.commission_user)

        response = self.client.get(reverse("admissions:vice_rector_dashboard"))

        self.assertEqual(response.status_code, 403)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_vice_rector_ecp_payload_is_prepared_without_signing_link(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.student_signer.mark_signed()
        contract.refresh_status_from_signers()

        self.client.force_login(self.vice_rector_user)
        response = self.client.get(
            reverse("admissions:vice_rector_ecp_signing_payload", args=[contract.pk])
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["signer_iin"], "222222222222")
        self.assertEqual(SignerAccessToken.objects.count(), 0)
        contract.vice_rector_signer.refresh_from_db()
        self.assertEqual(contract.vice_rector_signer.status, Signer.Status.SIGNING_STARTED)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_legacy_vice_rector_sign_post_stays_in_admissions(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        contract.student_signer.mark_signed()
        contract.refresh_status_from_signers()

        self.client.force_login(self.vice_rector_user)
        response = self.client.post(
            reverse("admissions:vice_rector_sign_contract", args=[contract.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("admissions:vice_rector_dashboard"))
        self.assertEqual(SignerAccessToken.objects.count(), 0)
        contract.vice_rector_signer.refresh_from_db()
        self.assertEqual(contract.vice_rector_signer.status, Signer.Status.SIGNING_STARTED)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_applicant_can_edit_contract_data_before_signing(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]

        response = self.client.post(
            reverse("admissions:applicant_contract", args=[token]),
            data={"field_side_1_full_name": "Иванов Иван Иванович"},
        )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        self.assertEqual(contract.applicant_full_name, "Иванов Иван Иванович")
        contract.student_signer.refresh_from_db()
        self.assertEqual(contract.student_signer.full_name, "Иванов Иван Иванович")
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.document,
                field_name="side_1_full_name",
            ).field_value,
            "Иванов Иван Иванович",
        )
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.document,
                field_name="side_1_full_name_genitive",
            ).field_value,
            "Иванова Ивана Ивановича",
        )
        self.assertEqual(render_mock.call_count, 4)

    @override_settings(OBJECT_STORAGE_ENABLED=False)
    @patch("admissions.services.contract_builder.DocumentDocxRenderService.render")
    def test_applicant_can_edit_contract_date_but_not_contract_number_before_signing(self, render_mock):
        render_mock.side_effect = lambda document, request=None, **_kwargs: document

        response = self.client.post(
            reverse("admissions:admission_contract_api"),
            data=json.dumps(self.payload(external_id="manual-contract-meta")),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_api_token}",
        )
        contract = AdmissionContract.objects.get(pk=response.json()["admission_contract_id"])
        token = contract.public_url.rstrip("/").rsplit("/", 1)[-1]
        original_contract_number = contract.document.contract_number

        response = self.client.get(reverse("admissions:applicant_contract", args=[token]))
        self.assertNotContains(response, 'name="field_contract_number"')
        self.assertContains(response, 'name="field_contract_date"')
        self.assertContains(response, 'type="date"')

        response = self.client.post(
            reverse("admissions:applicant_contract", args=[token]),
            data={
                "field_contract_number": "285437",
                "field_contract_date": "2026-08-05",
            },
        )

        self.assertEqual(response.status_code, 302)
        contract.refresh_from_db()
        contract.document.refresh_from_db()
        contract.application_document.refresh_from_db()
        self.assertEqual(contract.document.contract_number, original_contract_number)
        self.assertEqual(contract.document.get_contract_date_display(), "05.08.2026")
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.application_document,
                field_name="contract_number",
            ).field_value,
            original_contract_number,
        )
        self.assertEqual(
            DocumentFieldValue.objects.get(
                document=contract.application_document,
                field_name="contract_date",
            ).field_value,
            "05.08.2026",
        )

    def test_russian_full_name_genitive_is_available_for_application_header(self):
        payload = self.payload()
        payload["applicant"]["full_name"] = "Иванов Иван Иванович"

        normalized = AdmissionPayloadMapper.normalize_payload(payload)
        values = AdmissionPayloadMapper.build_document_values(normalized)

        self.assertEqual(values["applicant_full_name_genitive"], "Иванова Ивана Ивановича")
        self.assertEqual(values["student_full_name_genitive"], "Иванова Ивана Ивановича")

    def test_payload_mapper_maps_full_admission_json_fields(self):
        payload = self.payload()
        payload["applicant"].update({
            "full_name": "Иванов Иван Иванович",
            "iin": "321321321321",
            "phone": "",
            "email": "",
            "birth_date": "02.07.2026",
            "gender": "male",
            "citizenship_ru": "Казахстан",
            "citizenship_kk": "Қазақстан",
            "nationality_ru": "казахи",
            "nationality_kk": "қазақ",
            "almaty_address": "Алматы",
            "registration_address": "Постоянный адрес",
        })
        payload["study_form"] = "очная"
        payload["dormitory_need"] = "yes"
        payload["foreign_language"] = {
            "name_ru": "Английский язык",
            "name_kk": "Ағылшын тілі",
        }
        payload["identity_document"] = {
            "number": "654654654",
            "issuer": "Министерство внутренних дел РК",
            "issue_date": "09.07.2026",
        }
        payload["previous_education"] = {
            "name_ru": "Школа № 1",
            "name_kk": "№ 1 мектеп",
            "graduation_year": "2026",
            "document": {
                "series": "fg",
                "number": "6546",
                "type": "Аттестат об общем среднем образовании",
                "issue_date": "02.07.2026",
            },
        }
        payload["parents"] = {
            "father": {
                "full_name": "Отец Абитуриента",
                "phone": "654654",
                "workplace": "TestF",
                "position": "TestF",
            },
            "mother": {
                "full_name": "Мать Абитуриента",
                "phone": "87987",
                "workplace": "TestM",
                "position": "TestM",
            },
        }
        payload["legal_representative"] = {
            "full_name": "",
            "iin": "",
            "phone": "654654",
            "address": "TestF",
        }
        payload["admission_results"] = {
            "certificate_score": "130",
            "average_grade": "5",
        }
        payload["quota_ru"] = ""
        payload["quota_kk"] = ""
        payload["dean_full_name"] = "Иманкулов Тимур Сакенович"

        normalized = AdmissionPayloadMapper.normalize_payload(payload)
        values = AdmissionPayloadMapper.build_document_values(normalized)

        self.assertEqual(values["side_1_iin_bin"], "321321321321")
        self.assertEqual(values["iin"], "321321321321")
        self.assertEqual(values["side_1_phone"], "")
        self.assertEqual(values["side_1_email"], "")
        self.assertEqual(values["side_1_full_name_genitive"], "Иванова Ивана Ивановича")
        self.assertEqual(values["birth_date_text_ru"], "02.07.2026")
        self.assertEqual(values["identity_document_number"], "654654654")
        self.assertEqual(values["identity_document_issuer_ru"], "Министерство внутренних дел РК")
        self.assertEqual(values["identity_document_issue_date_ru"], "09.07.2026")
        self.assertEqual(values["gender_ru"], "мужской")
        self.assertEqual(values["gender_kk"], "ер")
        self.assertEqual(values["study_form_ru"], "очная")
        self.assertEqual(values["study_form_kk"], "күндізгі")
        self.assertEqual(values["dormitory_need_ru"], "нуждаюсь")
        self.assertEqual(values["dormitory_need_kk"], "қажет")
        self.assertEqual(values["foreign_language_ru"], "Английский язык")
        self.assertEqual(values["foreign_language_kk"], "Ағылшын тілі")
        self.assertEqual(values["father_phone"], "654654")
        self.assertEqual(values["father_work_place"], "TestF")
        self.assertEqual(values["father_position"], "TestF")
        self.assertEqual(values["mother_phone"], "87987")
        self.assertEqual(values["mother_work_place"], "TestM")
        self.assertEqual(values["mother_position"], "TestM")
        self.assertEqual(values["certificate_score"], "130")
        self.assertEqual(values["average_grade"], "5")
        self.assertEqual(values["education_document_series"], "fg")
        self.assertEqual(values["education_document_number"], "6546")
        self.assertEqual(values["education_document_type_ru"], "Аттестат об общем среднем образовании")
        self.assertEqual(values["education_document_issue_date"], "02.07.2026")
        self.assertEqual(values.get("student_parent_full_name", ""), "")
        self.assertEqual(values["student_parent_phone"], "654654")
        self.assertEqual(values["student_parent_address"], "TestF")
        self.assertEqual(values["student_parent_details_ru"], "тел. 654654, адрес TestF")
        self.assertEqual(values["student_parent_details_kk"], "тел. 654654, мекенжайы TestF")
        self.assertEqual(values["admission_quota_ru"], "")
        self.assertEqual(values["admission_quota_kk"], "")
        self.assertEqual(values["dean_full_name"], "Иманкулов Тимур Сакенович")

    def test_payload_mapper_maps_nested_university_payload_format(self):
        payload = {
            "study": {
                "form": "очная",
                "dormitory_need": "yes",
                "foreign_language_kk": "Ағылшын тілі",
                "foreign_language_ru": "Английский язык",
            },
            "parents": {
                "father_phone": "654654",
                "mother_phone": "87987",
                "father_position": "TestF",
                "mother_position": "TestM",
                "father_full_name": "TestF TestF TestF",
                "mother_full_name": "TestM TestM TestM",
                "father_work_place": "TestF",
                "mother_work_place": "TestM",
            },
            "program": {
                "code": "6B06103",
                "name_kk": "Компьютерлік инженерия",
                "name_ru": "Компьютерная инженерия",
                "faculty_kk": "Ақпараттық технологиялар және жасанды интеллект",
                "faculty_ru": "Информационных технологий и искусственного интеллекта",
            },
            "tuition": {
                "amount": 0,
            },
            "language": "kk",
            "addresses": {
                "almaty": "Алматы, Алмалинский, УЛИЦА Айвазовского, д. 45",
                "registration": "Западно-Казахстанская, Акжаикский, Бударинский, Бударино, ЗИМОВКА АМАНЖОЛ",
            },
            "applicant": {
                "iin": "321321321321",
                "email": "",
                "phone": "",
                "gender": "male",
                "full_name": "Test Test Test",
                "birth_date": "02.07.2026",
                "citizenship_kk": "ҚАЗАҚСТАН",
                "citizenship_ru": "КАЗАХСТАН",
                "nationality_kk": "қазақтар",
                "nationality_ru": "казахи",
                "full_name_genitive": "",
            },
            "university": {
                "dean_full_name": "Иманкулов Тимур Сакенович",
                "technical_secretary_full_name": "",
            },
            "external_id": "285437",
            "funding_type": "grant",
            "grant_number": "dvdf",
            "program_group": {
                "code": "В057",
                "name_kk": "Ақпараттық технологиялар",
                "name_ru": "Информационные технологии",
            },
            "education_level": "bachelor",
            "admission_results": {
                "quota_kk": "",
                "quota_ru": "",
                "average_grade": "5",
                "certificate_score": "130",
                "olympiad_degree_kk": "",
                "olympiad_degree_ru": "",
                "olympiad_subject_kk": "",
                "olympiad_subject_ru": "",
                "distinction_award_kk": "",
                "distinction_award_ru": "",
            },
            "identity_document": {
                "number": "654654654",
                "issuer_kk": "ҚР Ішкі Істер министрлігі",
                "issuer_ru": "Министерство внутренних дел РК",
                "issue_date": "09.07.2026",
            },
            "previous_education": {
                "name_kk": "dfdf",
                "name_ru": "dfdf",
                "document_number": "6546",
                "document_series": "fg",
                "graduation_year": "2026",
                "document_type_kk": "Жалпы орта білім туралы аттестат",
                "document_type_ru": "Аттестат об общем среднем образовании",
                "document_issue_date": "02.07.2026",
            },
            "legal_representative": {
                "iin": "",
                "phone": "654654",
                "address": "TestF",
                "full_name": "",
            },
        }

        normalized = AdmissionPayloadMapper.normalize_payload(payload)
        values = AdmissionPayloadMapper.build_document_values(normalized)

        self.assertEqual(values["side_1_iin_bin"], "321321321321")
        self.assertEqual(values["side_1_phone"], "")
        self.assertEqual(values["side_1_email"], "")
        self.assertEqual(values["birth_date_text_ru"], "02.07.2026")
        self.assertEqual(values["identity_document_number"], "654654654")
        self.assertEqual(values["identity_document_issuer_ru"], "Министерство внутренних дел РК")
        self.assertEqual(values["identity_document_issuer_kk"], "ҚР Ішкі Істер министрлігі")
        self.assertEqual(values["identity_document_issue_date_ru"], "09.07.2026")
        self.assertEqual(values["gender_ru"], "мужской")
        self.assertEqual(values["gender_kk"], "ер")
        self.assertEqual(values["citizenship_ru"], "КАЗАХСТАН")
        self.assertEqual(values["citizenship_kk"], "ҚАЗАҚСТАН")
        self.assertEqual(values["nationality_ru"], "казахи")
        self.assertEqual(values["nationality_kk"], "қазақтар")
        self.assertEqual(values["study_form_ru"], "очная")
        self.assertEqual(values["study_form_kk"], "күндізгі")
        self.assertEqual(values["dormitory_need_ru"], "нуждаюсь")
        self.assertEqual(values["dormitory_need_kk"], "қажет")
        self.assertEqual(values["foreign_language_ru"], "Английский язык")
        self.assertEqual(values["foreign_language_kk"], "Ағылшын тілі")
        self.assertEqual(values["father_full_name"], "TestF TestF TestF")
        self.assertEqual(values["father_phone"], "654654")
        self.assertEqual(values["father_work_place"], "TestF")
        self.assertEqual(values["father_position"], "TestF")
        self.assertEqual(values["mother_full_name"], "TestM TestM TestM")
        self.assertEqual(values["mother_phone"], "87987")
        self.assertEqual(values["mother_work_place"], "TestM")
        self.assertEqual(values["mother_position"], "TestM")
        self.assertEqual(values["certificate_score"], "130")
        self.assertEqual(values["average_grade"], "5")
        self.assertEqual(values["education_document_series"], "fg")
        self.assertEqual(values["education_document_number"], "6546")
        self.assertEqual(values["education_document_type_ru"], "Аттестат об общем среднем образовании")
        self.assertEqual(values["education_document_type_kk"], "Жалпы орта білім туралы аттестат")
        self.assertEqual(values["education_document_issue_date"], "02.07.2026")
        self.assertEqual(values["graduation_year"], "2026")
        self.assertEqual(values["previous_education_ru"], "dfdf")
        self.assertEqual(values["previous_education_kk"], "dfdf")
        self.assertEqual(values["almaty_address"], "Алматы, Алмалинский, УЛИЦА Айвазовского, д. 45")
        self.assertEqual(
            values["student_address"],
            "Западно-Казахстанская, Акжаикский, Бударинский, Бударино, ЗИМОВКА АМАНЖОЛ",
        )
        self.assertEqual(values.get("student_parent_full_name", ""), "")
        self.assertEqual(values["student_parent_phone"], "654654")
        self.assertEqual(values["student_parent_address"], "TestF")
        self.assertEqual(values["student_parent_details_ru"], "тел. 654654, адрес TestF")
        self.assertEqual(values["student_parent_details_kk"], "тел. 654654, мекенжайы TestF")
        self.assertEqual(values["admission_quota_ru"], "По квоте не поступаю.")
        self.assertEqual(values["admission_quota_kk"], "Квота бойынша оқуға түспеймін.")
        self.assertEqual(values["dean_full_name"], "Иманкулов Тимур Сакенович")

    def payload(self, *, external_id="app-1", education_level="bachelor"):
        return {
            "external_id": external_id,
            "education_level": education_level,
            "funding_type": "paid",
            "language": "ru",
            "program": {
                "code": "6B001",
                "name_ru": "Computer Science",
                "faculty": "FIBS",
            },
            "applicant": {
                "full_name": "Student Name",
                "iin": "111111111111",
                "phone": "77015556677",
                "email": "student@example.com",
                "address": "Almaty",
            },
            "identity_document": {
                "number": "ID123456",
                "issuer_ru": "MIA RK",
            },
            "parents": {
                "father_full_name": "Father Name",
                "mother_full_name": "Mother Name",
            },
            "tuition": {
                "amount": 1200000,
            },
        }
