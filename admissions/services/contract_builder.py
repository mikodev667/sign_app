import logging
import time

from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Q, Value, When

from documents.models import Document, DocumentFieldValue
from documents.services.document_docx_render_service import DocumentDocxRenderService
from documents.services.document_render_service import DocumentRenderService
from documents.services.money_amount_service import MoneyAmountService
from signing.models import Signer
from signing.services.signer_service import SignerService

from admissions.models import AdmissionContract, AdmissionTemplateRule
from admissions.services.payload_mapper import AdmissionPayloadMapper


logger = logging.getLogger(__name__)


class AdmissionContractBuildError(ValueError):
    pass


class AdmissionContractAlreadyExists(AdmissionContractBuildError):
    pass


class AdmissionContractCannotBeUpdated(AdmissionContractBuildError):
    pass


class AdmissionContractBuilder:
    @classmethod
    @transaction.atomic
    def create_from_payload(cls, *, api_client, normalized_payload, request=None):
        contract = cls._create_contract_shell(
            api_client=api_client,
            normalized_payload=normalized_payload,
        )
        raw_token = getattr(contract, "_raw_access_token", "")
        contract = cls.render_contract_documents(contract=contract, request=request)
        contract._raw_access_token = raw_token
        return contract

    @classmethod
    @transaction.atomic
    def create_pending_from_payload(cls, *, api_client, normalized_payload):
        return cls._create_contract_shell(
            api_client=api_client,
            normalized_payload=normalized_payload,
        )

    @classmethod
    @transaction.atomic
    def update_from_payload(cls, *, contract, api_client, normalized_payload, request=None):
        contract = cls._update_contract_shell(
            contract=contract,
            api_client=api_client,
            normalized_payload=normalized_payload,
        )
        return cls.render_contract_documents(contract=contract, request=request)

    @classmethod
    @transaction.atomic
    def update_pending_from_payload(cls, *, contract, api_client, normalized_payload):
        return cls._update_contract_shell(
            contract=contract,
            api_client=api_client,
            normalized_payload=normalized_payload,
        )

    @classmethod
    def _create_contract_shell(cls, *, api_client, normalized_payload):
        logger.info(
            "admission_contract_create_shell_started external_id=%s api_client_id=%s education_level=%s funding_type=%s language=%s program_code=%s",
            normalized_payload["external_id"],
            api_client.pk,
            normalized_payload["education_level"],
            normalized_payload["funding_type"],
            normalized_payload["language"],
            normalized_payload["program_code"],
        )
        if AdmissionContract.objects.filter(
            external_id=normalized_payload["external_id"],
        ).exists():
            raise AdmissionContractAlreadyExists("Admission contract already exists.")

        template_rule = cls.get_template_rule(normalized_payload)
        if not template_rule:
            raise AdmissionContractBuildError("No active admission template rule matches this payload.")

        raw_token = cls.generate_unique_public_token()
        contract = AdmissionContract.objects.create(
            api_client=api_client,
            template_rule=template_rule,
            external_id=normalized_payload["external_id"],
            access_token_hash=AdmissionContract.hash_access_token(raw_token),
            education_level=normalized_payload["education_level"],
            funding_type=normalized_payload["funding_type"],
            language=normalized_payload["language"],
            program_code=normalized_payload["program_code"],
            program_name_ru=normalized_payload["program_name_ru"],
            program_name_kk=normalized_payload["program_name_kk"],
            applicant_full_name=normalized_payload["applicant_full_name"],
            applicant_iin=normalized_payload["applicant_iin"],
            applicant_phone=normalized_payload["applicant_phone"],
            applicant_email=normalized_payload["applicant_email"],
            tuition_amount=normalized_payload["tuition_amount"],
            raw_payload=normalized_payload["raw_payload"],
            expires_at=AdmissionContract.default_expires_at(),
            status=AdmissionContract.Status.RECEIVED,
        )

        document = cls.create_document(
            template=template_rule.template,
            template_rule=template_rule,
            normalized_payload=normalized_payload,
        )
        application_document = cls.create_application_document(
            template_rule=template_rule,
            normalized_payload=normalized_payload,
        )

        contract.document = document
        contract.application_document = application_document
        contract.status = AdmissionContract.Status.DOCUMENT_CREATED
        contract.save(update_fields=[
            "document",
            "application_document",
            "status",
            "updated_at",
        ])
        contract._raw_access_token = raw_token
        logger.info(
            "admission_contract_create_shell_done external_id=%s contract_id=%s document_id=%s application_document_id=%s template_rule_id=%s",
            contract.external_id,
            contract.pk,
            contract.document_id,
            contract.application_document_id,
            template_rule.pk,
        )
        return contract

    @classmethod
    def _update_contract_shell(cls, *, contract, api_client, normalized_payload):
        logger.info(
            "admission_contract_update_shell_started external_id=%s contract_id=%s api_client_id=%s education_level=%s funding_type=%s language=%s program_code=%s",
            normalized_payload["external_id"],
            contract.pk,
            api_client.pk,
            normalized_payload["education_level"],
            normalized_payload["funding_type"],
            normalized_payload["language"],
            normalized_payload["program_code"],
        )
        contract = AdmissionContract.objects.select_for_update().get(pk=contract.pk)
        if contract.api_client_id != api_client.id:
            raise AdmissionContractAlreadyExists("Admission contract already exists.")

        cls.ensure_contract_can_be_updated(contract)
        normalized_payload = cls.merge_preserved_manual_edits(
            normalized_payload=normalized_payload,
            existing_payload=contract.raw_payload,
        )

        template_rule = cls.get_template_rule(normalized_payload)
        if not template_rule:
            raise AdmissionContractBuildError("No active admission template rule matches this payload.")

        document = contract.document
        if document:
            cls.update_document_metadata(
                document=document,
                template=template_rule.template,
                template_rule=template_rule,
                normalized_payload=normalized_payload,
            )
        else:
            document = cls.create_document(
                template=template_rule.template,
                template_rule=template_rule,
                normalized_payload=normalized_payload,
            )

        application_document = contract.application_document
        if template_rule.application_template:
            if application_document:
                cls.update_document_metadata(
                    document=application_document,
                    template=template_rule.application_template,
                    template_rule=template_rule,
                    normalized_payload=normalized_payload,
                    assign_contract_number=False,
                )
            else:
                application_document = cls.create_application_document(
                    template_rule=template_rule,
                    normalized_payload=normalized_payload,
                )
        else:
            application_document = None

        contract.api_client = api_client
        contract.template_rule = template_rule
        contract.document = document
        contract.application_document = application_document
        contract.education_level = normalized_payload["education_level"]
        contract.funding_type = normalized_payload["funding_type"]
        contract.language = normalized_payload["language"]
        contract.program_code = normalized_payload["program_code"]
        contract.program_name_ru = normalized_payload["program_name_ru"]
        contract.program_name_kk = normalized_payload["program_name_kk"]
        contract.applicant_full_name = normalized_payload["applicant_full_name"]
        contract.applicant_iin = normalized_payload["applicant_iin"]
        contract.applicant_phone = normalized_payload["applicant_phone"]
        contract.applicant_email = normalized_payload["applicant_email"]
        contract.tuition_amount = normalized_payload["tuition_amount"]
        contract.raw_payload = normalized_payload["raw_payload"]
        contract.status = AdmissionContract.Status.DOCUMENT_CREATED
        contract.error_message = ""
        contract.save(update_fields=[
            "api_client",
            "template_rule",
            "document",
            "application_document",
            "education_level",
            "funding_type",
            "language",
            "program_code",
            "program_name_ru",
            "program_name_kk",
            "applicant_full_name",
            "applicant_iin",
            "applicant_phone",
            "applicant_email",
            "tuition_amount",
            "raw_payload",
            "status",
            "error_message",
            "updated_at",
        ])
        logger.info(
            "admission_contract_update_shell_done external_id=%s contract_id=%s document_id=%s application_document_id=%s template_rule_id=%s",
            contract.external_id,
            contract.pk,
            contract.document_id,
            contract.application_document_id,
            template_rule.pk,
        )
        return contract

    @classmethod
    @transaction.atomic
    def render_contract_documents(cls, *, contract, request=None):
        started_at = time.monotonic()
        contract = (
            AdmissionContract.objects
            .select_related(
                "document",
                "application_document",
                "template_rule",
                "template_rule__template",
                "template_rule__application_template",
                "template_rule__vice_rector",
                "student_signer",
                "vice_rector_signer",
            )
            .get(pk=contract.pk)
        )

        normalized_payload = AdmissionPayloadMapper.normalize_payload(contract.raw_payload or {})
        template_rule = contract.template_rule or cls.get_template_rule(normalized_payload)
        if not template_rule:
            raise AdmissionContractBuildError("No active admission template rule matches this payload.")

        logger.info(
            "admission_contract_render_started external_id=%s contract_id=%s document_id=%s application_document_id=%s template_rule_id=%s",
            contract.external_id,
            contract.pk,
            contract.document_id,
            contract.application_document_id,
            template_rule.pk,
        )

        document = contract.document or cls.create_document(
            template=template_rule.template,
            template_rule=template_rule,
            normalized_payload=normalized_payload,
        )
        application_document = contract.application_document or cls.create_application_document(
            template_rule=template_rule,
            normalized_payload=normalized_payload,
        )
        shared_contract_system_values = document.get_contract_system_values()

        if application_document:
            application_values = cls.build_values(
                template=template_rule.application_template,
                template_rule=template_rule,
                normalized_payload=normalized_payload,
                document=application_document,
                system_values=shared_contract_system_values,
            )
            cls.write_document_values(document=application_document, values=application_values)
            cls.render_document(
                document=application_document,
                request=request,
                append_verification_page=False,
                system_values=shared_contract_system_values,
                assign_contract_number=False,
            )

        values = cls.build_values(
            template=template_rule.template,
            template_rule=template_rule,
            normalized_payload=normalized_payload,
            document=document,
            system_values=shared_contract_system_values,
        )
        cls.write_document_values(document=document, values=values)
        cls.render_document(document=document, request=request)

        if contract.student_signer:
            student_signer = cls.update_student_signer(
                signer=contract.student_signer,
                document=document,
                normalized_payload=normalized_payload,
                template_rule=template_rule,
            )
        else:
            student_signer = cls.create_student_signer(
                document=document,
                normalized_payload=normalized_payload,
                template_rule=template_rule,
                request=request,
            )

        if contract.vice_rector_signer:
            vice_rector_signer = cls.update_vice_rector_signer(
                signer=contract.vice_rector_signer,
                document=document,
                template_rule=template_rule,
            )
        else:
            vice_rector_signer = cls.create_vice_rector_signer(
                document=document,
                template_rule=template_rule,
                request=request,
            )

        contract.template_rule = template_rule
        contract.document = document
        contract.application_document = application_document
        contract.student_signer = student_signer
        contract.vice_rector_signer = vice_rector_signer
        contract.status = AdmissionContract.Status.STUDENT_SIGNING
        contract.error_message = ""
        contract.save(update_fields=[
            "template_rule",
            "document",
            "application_document",
            "student_signer",
            "vice_rector_signer",
            "status",
            "error_message",
            "updated_at",
        ])
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "admission_contract_render_done external_id=%s contract_id=%s document_id=%s application_document_id=%s student_signer_id=%s vice_rector_signer_id=%s elapsed_ms=%s",
            contract.external_id,
            contract.pk,
            contract.document_id,
            contract.application_document_id,
            contract.student_signer_id,
            contract.vice_rector_signer_id,
            elapsed_ms,
        )
        return contract

    @classmethod
    def get_template_rule(cls, normalized_payload):
        program_code = normalized_payload.get("program_code") or ""
        language = normalized_payload.get("language") or AdmissionTemplateRule.Language.RU

        return (
            AdmissionTemplateRule.objects
            .select_related(
                "template",
                "template__organization",
                "template__department",
                "template__created_by",
                "vice_rector",
            )
            .filter(
                is_active=True,
                funding_type=normalized_payload["funding_type"],
            )
            .filter(
                Q(education_level=normalized_payload["education_level"])
                | Q(education_level=AdmissionTemplateRule.EducationLevel.ANY)
            )
            .filter(Q(language=language) | Q(language=AdmissionTemplateRule.Language.ANY))
            .filter(Q(program_code="") | Q(program_code=program_code))
            .annotate(
                education_match_rank=Case(
                    When(education_level=normalized_payload["education_level"], then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
            )
            .order_by("priority", "education_match_rank", "-program_code", "id")
            .first()
        )

    @classmethod
    def create_application_document(cls, *, template_rule, normalized_payload):
        if not template_rule.application_template:
            return None

        return cls.create_document(
            template=template_rule.application_template,
            template_rule=template_rule,
            normalized_payload=normalized_payload,
            assign_contract_number=False,
        )

    @classmethod
    def create_document(cls, *, template, template_rule, normalized_payload, assign_contract_number=True):
        title = cls.build_document_title(template=template, normalized_payload=normalized_payload)

        document = Document(
            organization=template.organization,
            department=template.department,
            template=template,
            created_by=template.created_by,
            title=title,
            status=Document.Status.DRAFT,
        )
        if not assign_contract_number:
            document._skip_contract_number_generation = True
        document.save()
        return document

    @classmethod
    def update_document_metadata(
        cls,
        *,
        document,
        template,
        template_rule,
        normalized_payload,
        assign_contract_number=True,
    ):
        document.organization = template.organization
        document.department = template.department
        document.template = template
        document.created_by = template.created_by
        document.title = cls.build_document_title(
            template=template,
            normalized_payload=normalized_payload,
        )
        document.status = Document.Status.DRAFT
        document.locked_at = None
        document.signed_at = None
        if not assign_contract_number:
            document.contract_number = None
            document._skip_contract_number_generation = True
        cls.clear_document_render_outputs(document)
        update_fields = [
            "organization",
            "department",
            "template",
            "created_by",
            "title",
            "status",
            "locked_at",
            "signed_at",
            "rendered_html",
            "rendered_pdf_file",
            "rendered_docx_file",
            "content_hash",
            "updated_at",
        ]
        if not assign_contract_number:
            update_fields.append("contract_number")
        document.save(update_fields=update_fields)
        return document

    @staticmethod
    def clear_document_render_outputs(document):
        document.rendered_html = ""
        document.rendered_pdf_file = None
        document.rendered_docx_file = None
        document.content_hash = ""

    @classmethod
    def ensure_contract_can_be_updated(cls, contract):
        signer_ids = [
            signer_id
            for signer_id in [contract.student_signer_id, contract.vice_rector_signer_id]
            if signer_id
        ]
        if signer_ids and Signer.objects.filter(
            pk__in=signer_ids,
            status=Signer.Status.SIGNED,
        ).exists():
            raise AdmissionContractCannotBeUpdated(
                "Admission contract has already been signed and cannot be updated."
            )

        documents = [
            document
            for document in [contract.document, contract.application_document]
            if document
        ]
        for document in documents:
            if document.status == Document.Status.SIGNED or document.signed_at:
                raise AdmissionContractCannotBeUpdated(
                    "Admission contract has already been signed and cannot be updated."
                )
            if document.signers.filter(status=Signer.Status.SIGNED).exists():
                raise AdmissionContractCannotBeUpdated(
                    "Admission contract has already been signed and cannot be updated."
                )

    @classmethod
    def merge_preserved_manual_edits(cls, *, normalized_payload, existing_payload):
        existing_payload = existing_payload or {}
        manual_edits = existing_payload.get("_manual_edits")
        if not isinstance(manual_edits, dict) or not manual_edits:
            return normalized_payload

        raw_payload = dict(normalized_payload["raw_payload"] or {})
        raw_payload["_manual_edits"] = manual_edits

        for key, value in manual_edits.items():
            if key in {Document.SYSTEM_CONTRACT_NUMBER, Document.SYSTEM_CONTRACT_DATE}:
                continue
            if key == "tuition_amount":
                tuition = raw_payload.get("tuition")
                if not isinstance(tuition, dict):
                    tuition = {}
                tuition["amount"] = value
                raw_payload["tuition"] = tuition
            raw_payload[key] = value

        return AdmissionPayloadMapper.normalize_payload(raw_payload)

    @staticmethod
    def build_document_title(*, template, normalized_payload):
        title_parts = [
            template.title,
            normalized_payload["applicant_full_name"],
            normalized_payload["external_id"],
        ]
        return " - ".join(part for part in title_parts if part)

    @classmethod
    def build_values(cls, *, template, template_rule, normalized_payload, document, system_values=None):
        values = {}
        values.update(system_values or document.get_contract_system_values())
        values.update(AdmissionPayloadMapper.build_document_values(normalized_payload))
        values.update(cls.build_party_values(template_rule=template_rule, normalized_payload=normalized_payload))
        values.update(cls.get_manual_edit_values(normalized_payload))
        cls.apply_admission_application_defaults(values=values, normalized_payload=normalized_payload)
        values = MoneyAmountService.expand_template_values(template, values)
        return values

    @staticmethod
    def get_manual_edit_values(normalized_payload):
        raw_payload = normalized_payload.get("raw_payload") or {}
        manual_edits = raw_payload.get("_manual_edits")
        if not isinstance(manual_edits, dict):
            return {}

        return {
            str(key): value
            for key, value in manual_edits.items()
            if key and key not in Document.SYSTEM_FIELD_NAMES
        }

    @staticmethod
    def apply_admission_application_defaults(*, values, normalized_payload):
        language = normalized_payload.get("language")
        funding_type = normalized_payload.get("funding_type")
        contract_number = values.get("contract_number", "")
        grant_number = (
            values.get("grant_certificate_number")
            or values.get("grant_number")
            or values.get("certificate_number")
            or ""
        )

        if funding_type == AdmissionTemplateRule.FundingType.GRANT:
            values.setdefault(
                "admission_basis_ru",
                f"свидетельства о гранте № {grant_number}".strip(),
            )
            values.setdefault(
                "admission_basis_kk",
                f"№ {grant_number} білім гранты куәлігі".strip(),
            )
        else:
            values.setdefault("admission_basis_ru", f"договора № {contract_number}".strip())
            values.setdefault("admission_basis_kk", f"№ {contract_number} келісімшарт".strip())

        if language == AdmissionTemplateRule.Language.KK:
            values.setdefault("study_language_ru", "казахское")
            values.setdefault("study_language_kk", "қазақ")
        elif language == AdmissionTemplateRule.Language.EN:
            values.setdefault("study_language_ru", "английское")
            values.setdefault("study_language_kk", "ағылшын")
        else:
            values.setdefault("study_language_ru", "русское")
            values.setdefault("study_language_kk", "орыс")

        values.setdefault("dormitory_need_ru", "")
        values.setdefault("dormitory_need_kk", "")

    @classmethod
    def build_party_values(cls, *, template_rule, normalized_payload):
        parties = [
            party
            for party in template_rule.template.parties.prefetch_related("fields").all()
            if party.is_signer
        ]
        parties.sort(key=lambda party: (party.signing_order, party.id))

        values = {}
        values.update(cls.build_prefixed_party_values(
            prefix="side_1",
            full_name=normalized_payload["applicant_full_name"],
            full_name_genitive=normalized_payload["applicant_full_name_genitive"],
            iin=normalized_payload["applicant_iin"],
            phone=normalized_payload["applicant_phone"],
            email=normalized_payload["applicant_email"],
        ))
        if parties:
            values.update(cls.build_party_field_values(
                party=parties[0],
                full_name=normalized_payload["applicant_full_name"],
                full_name_genitive=normalized_payload["applicant_full_name_genitive"],
                iin=normalized_payload["applicant_iin"],
                phone=normalized_payload["applicant_phone"],
                email=normalized_payload["applicant_email"],
            ))

        if template_rule.vice_rector:
            vice_rector = template_rule.vice_rector
            values.update(cls.build_prefixed_party_values(
                prefix="side_2",
                full_name=vice_rector.full_name,
                full_name_genitive=vice_rector.full_name,
                iin=vice_rector.iin,
                phone=vice_rector.phone,
                email=vice_rector.email,
            ))
            values.update({
                "university_representative_full_name": vice_rector.full_name,
                "university_representative_iin": vice_rector.iin,
                "university_representative_phone": vice_rector.phone,
                "university_representative_email": vice_rector.email,
                "university_representative_signature_full_name": vice_rector.full_name,
                "side_2_role_title": "Проректор",
            })

        if len(parties) > 1 and template_rule.vice_rector:
            vice_rector = template_rule.vice_rector
            values.update(cls.build_party_field_values(
                party=parties[1],
                full_name=vice_rector.full_name,
                full_name_genitive=vice_rector.full_name,
                iin=vice_rector.iin,
                phone=vice_rector.phone,
                email=vice_rector.email,
            ))

        return values

    @staticmethod
    def build_prefixed_party_values(*, prefix, full_name, iin, phone, email, full_name_genitive=""):
        return {
            f"{prefix}_full_name": full_name,
            f"{prefix}_full_name_genitive": full_name_genitive or full_name,
            f"{prefix}_iin_bin": iin,
            f"{prefix}_iin": iin,
            f"{prefix}_phone": phone,
            f"{prefix}_email": email,
            f"{prefix}_signing_method": Signer.SigningMethod.ECP,
        }

    @staticmethod
    def build_party_field_values(*, party, full_name, iin, phone, email, full_name_genitive=""):
        prefix = party.variable_prefix
        values = AdmissionContractBuilder.build_prefixed_party_values(
            prefix=prefix,
            full_name=full_name,
            full_name_genitive=full_name_genitive,
            iin=iin,
            phone=phone,
            email=email,
        )

        for field in party.fields.all():
            key = f"{prefix}_{field.variable_name}"
            if key in values:
                continue

            if field.variable_name == "full_name":
                values[key] = full_name
            elif field.variable_name == "full_name_genitive":
                values[key] = full_name_genitive or full_name
            elif field.variable_name in {"iin", "iin_bin"}:
                values[key] = iin
            elif field.variable_name == "phone":
                values[key] = phone
            elif field.variable_name == "email":
                values[key] = email
            elif field.variable_name == "signing_method":
                values[key] = Signer.SigningMethod.ECP
            elif field.default_value:
                values[key] = field.default_value

        return values

    @classmethod
    def write_document_values(cls, *, document, values):
        template = document.template
        field_names = set(template.variables or [])
        field_names.update(document.SYSTEM_FIELD_NAMES)
        field_names.update(values.keys())

        for group in template.field_schema or []:
            for field in group.get("fields", []):
                key = (field.get("key") or "").strip()
                if key:
                    field_names.add(key)

        for party in template.parties.prefetch_related("fields").all():
            for field in party.fields.all():
                field_names.add(f"{party.variable_prefix}_{field.variable_name}")

        money_field_names = MoneyAmountService.get_template_money_field_names(template)
        for field_name in MoneyAmountService.derived_field_names_for_fields(money_field_names):
            field_names.discard(field_name)

        for field_name in sorted(field_names):
            if not field_name:
                continue

            DocumentFieldValue.objects.update_or_create(
                document=document,
                field_name=field_name,
                defaults={"field_value": str(values.get(field_name, ""))},
            )

    @classmethod
    def render_document(
        cls,
        *,
        document,
        request=None,
        append_verification_page=True,
        system_values=None,
        assign_contract_number=True,
    ):
        template = document.template

        if not assign_contract_number:
            document.contract_number = None
            document._skip_contract_number_generation = True

        if not template.template_file:
            DocumentRenderService.render_document(document=document)

        if not assign_contract_number:
            document.contract_number = None
            document._skip_contract_number_generation = True

        DocumentDocxRenderService.render(
            document,
            request=request,
            append_verification_page=append_verification_page,
            system_values=system_values,
        )

        if not assign_contract_number and document.contract_number:
            document.contract_number = None
            Document.objects.filter(pk=document.pk).update(contract_number=None)

    @classmethod
    def create_student_signer(cls, *, document, normalized_payload, template_rule, request=None):
        return SignerService.add_signer(
            document=document,
            full_name=normalized_payload["applicant_full_name"],
            iin=normalized_payload["applicant_iin"],
            phone=normalized_payload["applicant_phone"],
            email="",
            signing_order=1,
            signing_method=Signer.SigningMethod.ECP,
            template_party=cls.get_signer_party_for_template(
                template_rule.template,
                order_index=0,
            ),
            role_title="Поступающий",
            require_phone=False,
            request=request,
        )

    @classmethod
    def create_vice_rector_signer(cls, *, document, template_rule, request=None):
        vice_rector = template_rule.vice_rector
        if not vice_rector or not vice_rector.is_active:
            return None

        return SignerService.add_signer(
            document=document,
            full_name=vice_rector.full_name,
            iin=vice_rector.iin,
            phone=vice_rector.phone,
            email="",
            signing_order=2,
            signing_method=Signer.SigningMethod.ECP,
            template_party=cls.get_signer_party_for_template(
                template_rule.template,
                order_index=1,
            ),
            role_title="Проректор",
            require_phone=False,
            request=request,
        )

    @classmethod
    def update_student_signer(cls, *, signer, document, normalized_payload, template_rule):
        return cls.update_signer(
            signer=signer,
            document=document,
            full_name=normalized_payload["applicant_full_name"],
            iin=normalized_payload["applicant_iin"],
            phone=normalized_payload["applicant_phone"],
            email="",
            signing_order=1,
            signing_method=Signer.SigningMethod.ECP,
            template_party=cls.get_signer_party_for_template(
                template_rule.template,
                order_index=0,
            ),
            role_title=signer.role_title or "Applicant",
        )

    @classmethod
    def update_vice_rector_signer(cls, *, signer, document, template_rule):
        vice_rector = template_rule.vice_rector
        if not vice_rector or not vice_rector.is_active:
            return None

        return cls.update_signer(
            signer=signer,
            document=document,
            full_name=vice_rector.full_name,
            iin=vice_rector.iin,
            phone=vice_rector.phone,
            email="",
            signing_order=2,
            signing_method=Signer.SigningMethod.ECP,
            template_party=cls.get_signer_party_for_template(
                template_rule.template,
                order_index=1,
            ),
            role_title=signer.role_title or "Vice rector",
        )

    @staticmethod
    def update_signer(
        *,
        signer,
        document,
        full_name,
        iin,
        phone,
        email,
        signing_order,
        signing_method,
        template_party,
        role_title,
    ):
        full_name = full_name.strip() if full_name else ""
        iin = iin.strip() if iin else ""
        phone = phone.strip() if phone else ""
        email = email.strip() if email else ""
        role_title = role_title.strip() if role_title else ""

        if not full_name:
            raise ValueError("Full name is required.")

        SignerService.validate_iin(iin)
        if phone:
            SignerService.validate_phone(phone)
        SignerService.validate_email(email)

        if Signer.objects.filter(document=document, iin=iin).exclude(pk=signer.pk).exists():
            raise ValueError("Signer with this IIN is already added to this document.")

        signer.document = document
        signer.full_name = full_name
        signer.iin = iin
        signer.phone = SignerService.normalize_phone(phone) if phone else ""
        signer.email = email
        signer.signing_order = signing_order
        signer.signing_method = signing_method
        signer.template_party = template_party
        signer.role_title = role_title
        signer.status = Signer.Status.PENDING
        signer.signed_at = None
        signer.save(update_fields=[
            "document",
            "full_name",
            "iin",
            "phone",
            "email",
            "signing_order",
            "signing_method",
            "template_party",
            "role_title",
            "status",
            "signed_at",
            "updated_at",
        ])
        return signer

    @staticmethod
    def get_signer_party_for_template(template, *, order_index):
        if not template:
            return None

        parties = [
            party
            for party in template.parties.all()
            if party.is_signer
        ]
        parties.sort(key=lambda party: (party.signing_order, party.id))

        if order_index >= len(parties):
            return None

        return parties[order_index]

    @classmethod
    def generate_unique_public_token(cls):
        for _ in range(10):
            raw_token = AdmissionContract.generate_raw_access_token()
            token_hash = AdmissionContract.hash_access_token(raw_token)

            if not AdmissionContract.objects.filter(access_token_hash=token_hash).exists():
                return raw_token

        raise IntegrityError("Could not generate a unique admission contract token.")
