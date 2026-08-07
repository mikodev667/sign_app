import re
from datetime import datetime

from documents.services.money_amount_service import MoneyAmountService

from admissions.models import AdmissionTemplateRule


class AdmissionPayloadError(ValueError):
    pass


class AdmissionPayloadMapper:
    EDUCATION_ALIASES = {
        "bakalavr": AdmissionTemplateRule.EducationLevel.BACHELOR,
        "bachelor": AdmissionTemplateRule.EducationLevel.BACHELOR,
        "undergraduate": AdmissionTemplateRule.EducationLevel.BACHELOR,
        "master": AdmissionTemplateRule.EducationLevel.MASTER,
        "magistr": AdmissionTemplateRule.EducationLevel.MASTER,
        "magistracy": AdmissionTemplateRule.EducationLevel.MASTER,
        "doctoral": AdmissionTemplateRule.EducationLevel.DOCTORAL,
        "doctor": AdmissionTemplateRule.EducationLevel.DOCTORAL,
        "doktorant": AdmissionTemplateRule.EducationLevel.DOCTORAL,
        "phd": AdmissionTemplateRule.EducationLevel.DOCTORAL,
        "\u0431\u0430\u043a\u0430\u043b\u0430\u0432\u0440": AdmissionTemplateRule.EducationLevel.BACHELOR,
        "\u043c\u0430\u0433\u0438\u0441\u0442\u0440": AdmissionTemplateRule.EducationLevel.MASTER,
        "\u0434\u043e\u043a\u0442\u043e\u0440": AdmissionTemplateRule.EducationLevel.DOCTORAL,
        "\u0434\u043e\u043a\u0442\u043e\u0440\u0430\u043d\u0442": AdmissionTemplateRule.EducationLevel.DOCTORAL,
    }
    FUNDING_ALIASES = {
        "paid": AdmissionTemplateRule.FundingType.PAID,
        "commercial": AdmissionTemplateRule.FundingType.PAID,
        "contract": AdmissionTemplateRule.FundingType.PAID,
        "platnik": AdmissionTemplateRule.FundingType.PAID,
        "grant": AdmissionTemplateRule.FundingType.GRANT,
        "state_grant": AdmissionTemplateRule.FundingType.GRANT,
        "\u043f\u043b\u0430\u0442\u043d\u044b\u0439": AdmissionTemplateRule.FundingType.PAID,
        "\u043f\u043b\u0430\u0442\u043d\u0438\u043a": AdmissionTemplateRule.FundingType.PAID,
        "\u0433\u0440\u0430\u043d\u0442": AdmissionTemplateRule.FundingType.GRANT,
    }
    LANGUAGE_ALIASES = {
        "ru": AdmissionTemplateRule.Language.RU,
        "rus": AdmissionTemplateRule.Language.RU,
        "russian": AdmissionTemplateRule.Language.RU,
        "kk": AdmissionTemplateRule.Language.KK,
        "kz": AdmissionTemplateRule.Language.KK,
        "kazakh": AdmissionTemplateRule.Language.KK,
        "en": AdmissionTemplateRule.Language.EN,
        "eng": AdmissionTemplateRule.Language.EN,
        "english": AdmissionTemplateRule.Language.EN,
    }
    DATE_INPUT_FORMATS = (
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    )
    MALE_FIRST_NAME_ENDINGS = {
        "ан",
        "ей",
        "ий",
        "ил",
        "им",
        "ир",
        "ис",
        "ль",
        "нт",
        "рь",
        "ся",
        "ур",
        "ян",
    }

    @classmethod
    def normalize_payload(cls, payload):
        if not isinstance(payload, dict):
            raise AdmissionPayloadError("JSON payload must be an object.")

        applicant = payload.get("applicant") or {}
        program = payload.get("program") or {}
        program_group = payload.get("program_group") or {}
        tuition = payload.get("tuition") or {}

        if not isinstance(applicant, dict):
            raise AdmissionPayloadError("applicant must be an object.")

        if not isinstance(program, dict):
            raise AdmissionPayloadError("program must be an object.")

        if not isinstance(program_group, dict):
            raise AdmissionPayloadError("program_group must be an object.")

        if not isinstance(tuition, dict):
            raise AdmissionPayloadError("tuition must be an object.")

        external_id = cls.get_first(payload, "external_id", "application_id", "id")
        full_name = cls.get_first(applicant, "full_name", "fio", "name")
        full_name_genitive = cls.get_first(
            applicant,
            "full_name_genitive",
            "fio_genitive",
            "name_genitive",
        )
        iin = cls.get_first(applicant, "iin", "iin_bin")
        phone = cls.get_first(applicant, "phone", "mobile_phone")
        email = cls.get_first(applicant, "email")
        education_level = cls.normalize_choice(
            cls.get_first(payload, "education_level", "applicant_category", "category"),
            cls.EDUCATION_ALIASES,
            AdmissionTemplateRule.EducationLevel.OTHER,
        )
        funding_type = cls.normalize_choice(
            cls.get_first(payload, "funding_type", "payment_type", "payment"),
            cls.FUNDING_ALIASES,
            AdmissionTemplateRule.FundingType.OTHER,
        )
        language = cls.normalize_choice(
            cls.get_first(payload, "language", "lang"),
            cls.LANGUAGE_ALIASES,
            AdmissionTemplateRule.Language.RU,
        )
        program_code = cls.get_first(program, "code", "program_code") or cls.get_first(
            payload,
            "program_code",
        )
        program_group_code = (
            cls.get_first(program_group, "code", "program_group_code")
            or cls.get_first(program, "group_code", "program_group_code")
            or cls.get_first(payload, "program_group_code")
            or program_code
        )
        program_name_ru = cls.get_first(program, "name_ru", "ru", "name") or cls.get_first(
            payload,
            "program_name_ru",
        )
        program_name_kk = cls.get_first(program, "name_kk", "kk") or cls.get_first(
            payload,
            "program_name_kk",
        )
        program_name_ru = str(program_name_ru or program_name_kk or "").strip()
        program_name_kk = str(program_name_kk or program_name_ru or "").strip()
        program_group_name_ru = (
            cls.get_first(program_group, "name_ru", "ru", "name")
            or cls.get_first(program, "group_name_ru", "program_group_name_ru")
            or cls.get_first(payload, "program_group_name_ru")
            or program_name_ru
        )
        program_group_name_kk = (
            cls.get_first(program_group, "name_kk", "kk")
            or cls.get_first(program, "group_name_kk", "program_group_name_kk")
            or cls.get_first(payload, "program_group_name_kk")
            or program_name_kk
        )
        program_group_name_ru = str(program_group_name_ru or program_group_name_kk or "").strip()
        program_group_name_kk = str(program_group_name_kk or program_group_name_ru or "").strip()
        program_faculty = cls.get_first(program, "faculty", "faculty_name") or cls.get_first(
            payload,
            "faculty",
        )
        program_faculty_ru = (
            cls.get_first(program, "faculty_ru", "faculty_name_ru")
            or cls.get_first(payload, "faculty_ru", "faculty_name_ru")
            or program_faculty
        )
        program_faculty_kk = (
            cls.get_first(program, "faculty_kk", "faculty_name_kk")
            or cls.get_first(payload, "faculty_kk", "faculty_name_kk")
            or program_faculty_ru
        )
        program_faculty = str(program_faculty or program_faculty_ru or program_faculty_kk or "").strip()
        program_faculty_ru = str(program_faculty_ru or program_faculty or "").strip()
        program_faculty_kk = str(program_faculty_kk or program_faculty_ru or "").strip()
        program_faculty = cls.normalize_faculty_name(program_faculty, language="ru")
        program_faculty_ru = cls.normalize_faculty_name(program_faculty_ru, language="ru")
        program_faculty_kk = cls.normalize_faculty_name(program_faculty_kk, language="kk")
        raw_amount = cls.get_first(tuition, "amount", "tuition_amount") or cls.get_first(
            payload,
            "tuition_amount",
            "amount",
        )
        tuition_amount = (
            MoneyAmountService.parse_amount(raw_amount)
            if raw_amount not in [None, ""]
            else None
        )

        cls.require("external_id", external_id)
        cls.require("applicant.full_name", full_name)
        cls.require("applicant.iin", iin)

        if raw_amount not in [None, ""] and tuition_amount is None:
            raise AdmissionPayloadError("tuition_amount must be a whole numeric amount.")

        return {
            "external_id": str(external_id).strip(),
            "applicant_full_name": str(full_name).strip(),
            "applicant_full_name_genitive": (
                str(full_name_genitive).strip()
                if full_name_genitive
                else cls.inflect_full_name_genitive(full_name)
            ),
            "applicant_iin": str(iin).strip(),
            "applicant_phone": str(phone or "").strip(),
            "applicant_email": str(email or "").strip(),
            "education_level": education_level,
            "funding_type": funding_type,
            "language": language,
            "program_code": str(program_code or "").strip(),
            "program_group_code": str(program_group_code or "").strip(),
            "program_group_name_ru": program_group_name_ru,
            "program_group_name_kk": program_group_name_kk,
            "program_name_ru": program_name_ru,
            "program_name_kk": program_name_kk,
            "program_faculty": program_faculty,
            "program_faculty_ru": program_faculty_ru,
            "program_faculty_kk": program_faculty_kk,
            "tuition_amount": tuition_amount,
            "extra_values": cls.flatten_payload_values(payload),
            "raw_payload": payload,
        }

    @classmethod
    def build_document_values(cls, normalized):
        values = {
            "external_id": normalized["external_id"],
            "application_id": normalized["external_id"],
            "education_level": normalized["education_level"],
            "funding_type": normalized["funding_type"],
            "language": normalized["language"],
            "program_code": normalized["program_code"],
            "program_group_code": normalized["program_group_code"],
            "program_group_name_ru": normalized["program_group_name_ru"],
            "program_group_name_kk": normalized["program_group_name_kk"],
            "program_name_ru": normalized["program_name_ru"],
            "program_name_kk": normalized["program_name_kk"],
            "program_faculty": normalized["program_faculty"],
            "program_faculty_ru": normalized["program_faculty_ru"],
            "program_faculty_kk": normalized["program_faculty_kk"],
            "faculty": normalized["program_faculty"],
            "applicant_full_name": normalized["applicant_full_name"],
            "applicant_iin": normalized["applicant_iin"],
            "applicant_phone": normalized["applicant_phone"],
            "applicant_email": normalized["applicant_email"],
            "student_full_name": normalized["applicant_full_name"],
            "student_full_name_genitive": normalized["applicant_full_name_genitive"],
            "student_iin": normalized["applicant_iin"],
            "student_phone": normalized["applicant_phone"],
            "student_email": normalized["applicant_email"],
            "iin": normalized["applicant_iin"],
            "phone": normalized["applicant_phone"],
            "email": normalized["applicant_email"],
            "side_1_full_name": normalized["applicant_full_name"],
            "side_1_full_name_genitive": normalized["applicant_full_name_genitive"],
            "side_1_iin_bin": normalized["applicant_iin"],
            "side_1_iin": normalized["applicant_iin"],
            "side_1_phone": normalized["applicant_phone"],
            "side_1_email": normalized["applicant_email"],
            "student_faculty": normalized["program_faculty"],
            "student_faculty_ru": normalized["program_faculty_ru"],
            "student_faculty_kk": normalized["program_faculty_kk"],
            "applicant_signature_full_name": normalized["applicant_full_name"],
            "student_signature_full_name": normalized["applicant_full_name"],
        }
        values.update({
            key: value
            for key, value in normalized.get("extra_values", {}).items()
            if key not in values
        })
        cls.add_normalized_values(values)

        values.setdefault("study_form_ru", "очная")
        values.setdefault("study_form_kk", "күндізгі")

        values.update(
            MoneyAmountService.build_value_context(
                "tuition_amount",
                str(normalized["tuition_amount"])
                if normalized["tuition_amount"] is not None
                else "",
            )
        )

        return values

    @classmethod
    def flatten_payload_values(cls, payload):
        values = {}
        cls.add_nested_values(values, "", payload)

        for key, value in payload.items():
            if key in {"applicant", "program", "tuition"}:
                continue
            cls.add_flat_value(values, key, value)

        applicant = payload.get("applicant") or {}
        if isinstance(applicant, dict):
            for key, value in applicant.items():
                cleaned_key = cls.clean_key(key)
                if not cleaned_key:
                    continue

                cls.add_flat_value(values, f"applicant_{cleaned_key}", value)
                cls.add_flat_value(values, f"student_{cleaned_key}", value)

        program = payload.get("program") or {}
        if isinstance(program, dict):
            for key, value in program.items():
                cleaned_key = cls.clean_key(key)
                if not cleaned_key:
                    continue

                cls.add_flat_value(values, f"program_{cleaned_key}", value)

                if cleaned_key == "faculty":
                    cls.add_flat_value(values, "faculty", value)
                    cls.add_flat_value(values, "student_faculty", value)
                    cls.add_flat_value(values, "applicant_faculty", value)

        program_group = payload.get("program_group") or {}
        if isinstance(program_group, dict):
            for key, value in program_group.items():
                cleaned_key = cls.clean_key(key)
                if not cleaned_key:
                    continue

                cls.add_flat_value(values, f"program_group_{cleaned_key}", value)

        tuition = payload.get("tuition") or {}
        if isinstance(tuition, dict):
            for key, value in tuition.items():
                cleaned_key = cls.clean_key(key)
                if cleaned_key:
                    cls.add_flat_value(values, f"tuition_{cleaned_key}", value)

        cls.add_template_aliases(values)
        cls.add_normalized_values(values)
        return values

    @classmethod
    def add_nested_values(cls, values, prefix, value):
        if isinstance(value, dict):
            for key, nested_value in value.items():
                cleaned_key = cls.clean_key(key)
                if not cleaned_key:
                    continue

                nested_prefix = f"{prefix}_{cleaned_key}" if prefix else cleaned_key
                cls.add_nested_values(values, nested_prefix, nested_value)
            return

        if isinstance(value, list):
            scalar_values = [
                str(item).strip()
                for item in value
                if cls.is_scalar(item) and str(item or "").strip()
            ]
            if scalar_values:
                cls.add_flat_value(values, prefix, ", ".join(scalar_values))
            return

        cls.add_flat_value(values, prefix, value)

    @classmethod
    def add_flat_value(cls, values, key, value):
        cleaned_key = cls.clean_key(key)

        if not cleaned_key or not cls.is_scalar(value):
            return

        values.setdefault(cleaned_key, str(value).strip())

    @classmethod
    def add_template_aliases(cls, values):
        alias_groups = {
            "side_1_full_name": [
                "side_1_full_name",
                "applicant_full_name",
                "student_full_name",
                "full_name",
                "fio",
                "name",
            ],
            "side_1_full_name_genitive": [
                "side_1_full_name_genitive",
                "applicant_full_name_genitive",
                "student_full_name_genitive",
                "full_name_genitive",
                "fio_genitive",
                "name_genitive",
            ],
            "side_1_iin_bin": ["side_1_iin_bin", "side_1_iin", "applicant_iin", "student_iin", "iin"],
            "side_1_iin": ["side_1_iin", "side_1_iin_bin", "applicant_iin", "student_iin", "iin"],
            "side_1_phone": ["side_1_phone", "applicant_phone", "student_phone", "phone", "mobile_phone"],
            "side_1_email": ["side_1_email", "applicant_email", "student_email", "email"],
            "birth_date_text_ru": [
                "birth_date_text_ru",
                "applicant_birth_date_text_ru",
                "student_birth_date_text_ru",
                "birth_date_ru",
                "applicant_birth_date_ru",
                "student_birth_date_ru",
                "applicant_birth_date",
                "student_birth_date",
                "applicant_date_of_birth",
                "student_date_of_birth",
                "date_of_birth",
                "birth_date",
            ],
            "birth_date_text_kk": [
                "birth_date_text_kk",
                "applicant_birth_date_text_kk",
                "student_birth_date_text_kk",
                "birth_date_kk",
                "applicant_birth_date_kk",
                "student_birth_date_kk",
                "applicant_birth_date",
                "student_birth_date",
                "applicant_date_of_birth",
                "student_date_of_birth",
                "date_of_birth",
                "birth_date",
            ],
            "identity_document_number": [
                "identity_document_number",
                "identity_document_no",
                "identity_document_id_number",
                "identity_number",
                "identity_document_id",
                "identity_document_card_number",
                "identity_document_card_no",
                "document_number",
                "id_document_number",
                "id_card_number",
                "id_card_no",
                "applicant_identity_document_number",
                "student_identity_document_number",
            ],
            "identity_document_series": [
                "identity_document_series",
                "identity_series",
                "document_series",
                "id_document_series",
                "applicant_identity_document_series",
            ],
            "identity_document_issue_date_ru": [
                "identity_document_issue_date_ru",
                "identity_document_issue_date",
                "identity_document_issued_date",
                "identity_document_date_of_issue",
                "document_issue_date",
                "document_issued_date",
                "id_document_issue_date",
                "id_card_issue_date",
                "applicant_identity_document_issue_date",
                "student_identity_document_issue_date",
            ],
            "identity_document_issue_date_kk": [
                "identity_document_issue_date_kk",
                "identity_document_issue_date",
                "identity_document_issued_date",
                "identity_document_date_of_issue",
                "document_issue_date",
                "document_issued_date",
                "id_document_issue_date",
                "id_card_issue_date",
                "applicant_identity_document_issue_date",
                "student_identity_document_issue_date",
            ],
            "identity_document_issuer_ru": [
                "identity_document_issuer_ru",
                "identity_document_issuer",
                "identity_document_issued_by_ru",
                "identity_document_issued_by",
                "identity_document_issue_organization_ru",
                "identity_document_issue_organization",
                "identity_document_issuing_authority_ru",
                "identity_document_issuing_authority",
                "document_issuer_ru",
                "document_issuer",
                "document_issued_by",
                "id_document_issuer_ru",
                "id_document_issuer",
                "id_card_issuer",
                "applicant_identity_document_issuer_ru",
            ],
            "identity_document_issuer_kk": [
                "identity_document_issuer_kk",
                "identity_document_issuer",
                "identity_document_issued_by_kk",
                "identity_document_issued_by",
                "identity_document_issue_organization_kk",
                "identity_document_issue_organization",
                "identity_document_issuing_authority_kk",
                "identity_document_issuing_authority",
                "document_issuer_kk",
                "document_issuer",
                "document_issued_by",
                "id_document_issuer_kk",
                "id_document_issuer",
                "id_card_issuer",
                "applicant_identity_document_issuer_kk",
            ],
            "gender_ru": ["gender_ru", "gender", "applicant_gender_ru", "student_gender_ru", "applicant_gender", "student_gender"],
            "gender_kk": ["gender_kk", "gender", "applicant_gender_kk", "student_gender_kk", "applicant_gender", "student_gender"],
            "citizenship_ru": ["citizenship_ru", "citizenship", "applicant_citizenship_ru", "applicant_citizenship"],
            "citizenship_kk": ["citizenship_kk", "citizenship", "applicant_citizenship_kk", "applicant_citizenship"],
            "nationality_ru": ["nationality_ru", "nationality", "applicant_nationality_ru", "applicant_nationality"],
            "nationality_kk": ["nationality_kk", "nationality", "applicant_nationality_kk", "applicant_nationality"],
            "study_form_ru": ["study_form_ru", "study_form", "education_form_ru", "education_form"],
            "study_form_kk": ["study_form_kk", "study_form", "education_form_kk", "education_form"],
            "study_language_ru": ["study_language_ru", "study_language", "education_language_ru"],
            "study_language_kk": ["study_language_kk", "study_language", "education_language_kk"],
            "graduation_year": [
                "graduation_year",
                "previous_education_graduation_year",
                "education_graduation_year",
                "school_graduation_year",
            ],
            "previous_education_ru": [
                "previous_education_ru",
                "previous_education",
                "previous_education_name_ru",
                "education_previous_ru",
                "school_name_ru",
            ],
            "previous_education_kk": [
                "previous_education_kk",
                "previous_education",
                "previous_education_name_kk",
                "education_previous_kk",
                "school_name_kk",
            ],
            "education_document_series": [
                "education_document_series",
                "education_certificate_series",
                "diploma_series",
                "certificate_series",
                "attestat_series",
                "previous_education_document_series",
                "previous_education_certificate_series",
            ],
            "education_document_number": [
                "education_document_number",
                "education_certificate_number",
                "diploma_number",
                "certificate_number",
                "attestat_number",
                "previous_education_document_number",
                "previous_education_certificate_number",
            ],
            "education_document_issue_date": [
                "education_document_issue_date",
                "education_document_issued_date",
                "education_document_date_of_issue",
                "education_certificate_issue_date",
                "education_certificate_issued_date",
                "diploma_issue_date",
                "certificate_issue_date",
                "attestat_issue_date",
                "previous_education_document_issue_date",
                "previous_education_document_issued_date",
            ],
            "education_document_type_ru": [
                "education_document_type_ru",
                "education_document_type",
                "education_document_name_ru",
                "education_document_name",
                "education_certificate_type_ru",
                "education_certificate_type",
                "diploma_type_ru",
                "certificate_type_ru",
                "previous_education_document_type_ru",
                "previous_education_document_type",
            ],
            "education_document_type_kk": [
                "education_document_type_kk",
                "education_document_type",
                "education_document_name_kk",
                "education_document_name",
                "education_certificate_type_kk",
                "education_certificate_type",
                "diploma_type_kk",
                "certificate_type_kk",
                "previous_education_document_type_kk",
                "previous_education_document_type",
            ],
            "distinction_award_ru": [
                "distinction_award_ru",
                "distinction_award",
                "award_ru",
                "admission_results_distinction_award_ru",
            ],
            "distinction_award_kk": [
                "distinction_award_kk",
                "distinction_award",
                "award_kk",
                "admission_results_distinction_award_kk",
            ],
            "olympiad_subject_ru": [
                "olympiad_subject_ru",
                "olympiad_subject",
                "competition_subject_ru",
                "admission_results_olympiad_subject_ru",
            ],
            "olympiad_subject_kk": [
                "olympiad_subject_kk",
                "olympiad_subject",
                "competition_subject_kk",
                "admission_results_olympiad_subject_kk",
            ],
            "olympiad_degree_ru": [
                "olympiad_degree_ru",
                "olympiad_degree",
                "competition_degree_ru",
                "admission_results_olympiad_degree_ru",
            ],
            "olympiad_degree_kk": [
                "olympiad_degree_kk",
                "olympiad_degree",
                "competition_degree_kk",
                "admission_results_olympiad_degree_kk",
            ],
            "certificate_score": [
                "certificate_score",
                "ent_score",
                "ent_points",
                "test_score",
                "test_points",
                "score",
                "points",
                "grant_certificate_score",
                "admission_results_certificate_score",
                "admission_results_ent_score",
                "admission_result_certificate_score",
            ],
            "average_grade": [
                "average_grade",
                "avg_grade",
                "gpa",
                "diploma_average_grade",
                "certificate_average_grade",
                "admission_results_average_grade",
                "admission_result_average_grade",
            ],
            "grant_number": [
                "grant_number",
                "grant_certificate_number",
                "grant_certificate_no",
                "grant_no",
                "educational_grant_number",
                "education_grant_number",
            ],
            "admission_quota_ru": [
                "admission_quota_ru",
                "admission_quota",
                "quota_ru",
                "quota",
                "admission_results_quota_ru",
            ],
            "admission_quota_kk": [
                "admission_quota_kk",
                "admission_quota",
                "quota_kk",
                "quota",
                "admission_results_quota_kk",
            ],
            "father_full_name": [
                "father_full_name",
                "father_name",
                "parents_father_full_name",
                "parent_father_full_name",
                "applicant_father_full_name",
            ],
            "father_phone": ["father_phone", "father_mobile_phone", "parents_father_phone", "parent_father_phone"],
            "father_work_place": [
                "father_work_place",
                "father_workplace",
                "father_work",
                "father_job_place",
                "father_job",
                "parents_father_workplace",
                "parents_father_work_place",
            ],
            "father_position": ["father_position", "father_job_title", "father_post", "parents_father_position"],
            "mother_full_name": [
                "mother_full_name",
                "mother_name",
                "parents_mother_full_name",
                "parent_mother_full_name",
                "applicant_mother_full_name",
            ],
            "mother_phone": ["mother_phone", "mother_mobile_phone", "parents_mother_phone", "parent_mother_phone"],
            "mother_work_place": [
                "mother_work_place",
                "mother_workplace",
                "mother_work",
                "mother_job_place",
                "mother_job",
                "parents_mother_workplace",
                "parents_mother_work_place",
            ],
            "mother_position": ["mother_position", "mother_job_title", "mother_post", "parents_mother_position"],
            "student_parent_full_name": [
                "student_parent_full_name",
                "parent_full_name",
                "parents_full_name",
                "legal_representative_full_name",
                "guardian_full_name",
                "representative_full_name",
            ],
            "student_parent_iin": [
                "student_parent_iin",
                "parent_iin",
                "legal_representative_iin",
                "guardian_iin",
                "representative_iin",
            ],
            "student_parent_phone": [
                "student_parent_phone",
                "parent_phone",
                "legal_representative_phone",
                "guardian_phone",
                "representative_phone",
            ],
            "student_parent_address": [
                "student_parent_address",
                "parent_address",
                "legal_representative_address",
                "guardian_address",
                "representative_address",
            ],
            "almaty_address": [
                "almaty_address",
                "applicant_almaty_address",
                "student_almaty_address",
                "temporary_address",
                "local_address",
                "addresses_almaty",
                "addresses_temporary",
            ],
            "student_address": [
                "student_address",
                "applicant_address",
                "applicant_registration_address",
                "student_registration_address",
                "registration_address",
                "permanent_address",
                "home_address",
                "address",
                "addresses_permanent",
                "addresses_registration",
            ],
            "foreign_language_ru": [
                "foreign_language_ru",
                "foreign_language_name_ru",
                "study_foreign_language_ru",
                "foreign_language",
                "language_foreign_ru",
            ],
            "foreign_language_kk": [
                "foreign_language_kk",
                "foreign_language_name_kk",
                "study_foreign_language_kk",
                "foreign_language",
                "language_foreign_kk",
            ],
            "dormitory_need_ru": [
                "dormitory_need_ru",
                "dormitory_need",
                "study_dormitory_need",
                "needs_dormitory_ru",
                "needs_dormitory",
                "dormitory",
                "hostel",
            ],
            "dormitory_need_kk": [
                "dormitory_need_kk",
                "dormitory_need",
                "study_dormitory_need",
                "needs_dormitory_kk",
                "needs_dormitory",
                "dormitory",
                "hostel",
            ],
            "technical_secretary_full_name": [
                "technical_secretary_full_name",
                "university_technical_secretary_full_name",
                "secretary_full_name",
                "admission_secretary_full_name",
            ],
            "dean_full_name": [
                "dean_full_name",
                "university_dean_full_name",
                "dean_fio",
                "dean",
                "faculty_dean_full_name",
                "program_faculty_dean_full_name",
            ],
        }

        for target, aliases in alias_groups.items():
            cls.copy_first_alias(values, target, aliases)

    @classmethod
    def add_normalized_values(cls, values):
        full_name = cls.first_non_empty(
            values,
            "side_1_full_name",
            "applicant_full_name",
            "student_full_name",
            "full_name",
            "fio",
            "name",
        )
        full_name_genitive = cls.first_non_empty(
            values,
            "side_1_full_name_genitive",
            "applicant_full_name_genitive",
            "student_full_name_genitive",
            "full_name_genitive",
            "fio_genitive",
            "name_genitive",
        )
        if full_name and not full_name_genitive:
            full_name_genitive = cls.inflect_full_name_genitive(full_name)

        if full_name_genitive:
            for key in [
                "side_1_full_name_genitive",
                "applicant_full_name_genitive",
                "student_full_name_genitive",
            ]:
                values.setdefault(key, full_name_genitive)

        for key in [
            "birth_date_text_ru",
            "birth_date_text_kk",
            "identity_document_issue_date_ru",
            "identity_document_issue_date_kk",
            "education_document_issue_date",
        ]:
            if values.get(key):
                values[key] = cls.normalize_date_text(values[key])

        gender = cls.first_non_empty(values, "gender", "gender_ru", "gender_kk")
        if gender:
            gender_ru, gender_kk = cls.normalize_gender(gender)
            values["gender_ru"] = gender_ru
            values["gender_kk"] = gender_kk

        study_form = cls.first_non_empty(values, "study_form", "study_form_ru", "study_form_kk")
        if study_form:
            study_form_ru, study_form_kk = cls.normalize_study_form(study_form)
            values["study_form_ru"] = study_form_ru
            values["study_form_kk"] = study_form_kk

        dormitory_need = cls.first_non_empty(
            values,
            "dormitory_need",
            "study_dormitory_need",
            "dormitory_need_ru",
            "dormitory_need_kk",
            "needs_dormitory",
        )
        if dormitory_need:
            dormitory_ru, dormitory_kk = cls.normalize_dormitory_need(dormitory_need)
            values["dormitory_need_ru"] = dormitory_ru
            values["dormitory_need_kk"] = dormitory_kk

        foreign_language_ru = cls.first_non_empty(
            values,
            "foreign_language_ru",
            "study_foreign_language_ru",
            "language_foreign_ru",
            "foreign_language_name_ru",
            "foreign_language",
        )
        foreign_language_kk = cls.first_non_empty(
            values,
            "foreign_language_kk",
            "study_foreign_language_kk",
            "language_foreign_kk",
            "foreign_language_name_kk",
            "foreign_language",
        )
        if foreign_language_ru or foreign_language_kk:
            split_ru, split_kk = cls.split_bilingual_value(foreign_language_ru or foreign_language_kk)
            if foreign_language_ru and foreign_language_ru == foreign_language_kk:
                values["foreign_language_ru"] = split_ru
                values["foreign_language_kk"] = split_kk
            else:
                values["foreign_language_ru"] = foreign_language_ru or split_ru
                values["foreign_language_kk"] = foreign_language_kk or split_kk

        if not cls.first_non_empty(
            values,
            "admission_quota_ru",
            "quota_ru",
            "admission_results_quota_ru",
            "quota",
        ):
            values["admission_quota_ru"] = "По квоте не поступаю."

        if not cls.first_non_empty(
            values,
            "admission_quota_kk",
            "quota_kk",
            "admission_results_quota_kk",
            "quota",
        ):
            values["admission_quota_kk"] = "Квота бойынша оқуға түспеймін."

        cls.add_parent_representative_details(values)

        if full_name:
            values.setdefault("applicant_signature_full_name", full_name)
            values.setdefault("student_signature_full_name", full_name)

    @classmethod
    def add_parent_representative_details(cls, values):
        full_name = cls.first_non_empty(
            values,
            "student_parent_full_name",
            "parent_full_name",
            "legal_representative_full_name",
            "guardian_full_name",
            "representative_full_name",
        )
        iin = cls.first_non_empty(
            values,
            "student_parent_iin",
            "parent_iin",
            "legal_representative_iin",
            "guardian_iin",
            "representative_iin",
        )
        phone = cls.first_non_empty(
            values,
            "student_parent_phone",
            "parent_phone",
            "legal_representative_phone",
            "guardian_phone",
            "representative_phone",
        )
        address = cls.first_non_empty(
            values,
            "student_parent_address",
            "parent_address",
            "legal_representative_address",
            "guardian_address",
            "representative_address",
        )

        ru_parts = []
        kk_parts = []

        if full_name:
            ru_parts.append(full_name)
            kk_parts.append(full_name)

        if iin:
            ru_parts.append(f"ИИН {iin}")
            kk_parts.append(f"ЖСН {iin}")

        if phone:
            ru_parts.append(f"тел. {phone}")
            kk_parts.append(f"тел. {phone}")

        if address:
            ru_parts.append(f"адрес {address}")
            kk_parts.append(f"мекенжайы {address}")

        values.setdefault("student_parent_details_ru", ", ".join(ru_parts))
        values.setdefault("student_parent_details_kk", ", ".join(kk_parts))

    @staticmethod
    def copy_first_alias(values, target, aliases):
        if values.get(target):
            return

        for alias in aliases:
            value = values.get(alias)
            if value not in [None, ""]:
                values[target] = str(value).strip()
                return

    @staticmethod
    def first_non_empty(values, *keys):
        for key in keys:
            value = values.get(key)
            if value not in [None, ""]:
                return str(value).strip()
        return ""

    @classmethod
    def normalize_date_text(cls, value):
        text = str(value or "").strip()
        if not text:
            return ""

        for date_format in cls.DATE_INPUT_FORMATS:
            try:
                return datetime.strptime(text, date_format).strftime("%d.%m.%Y")
            except ValueError:
                continue

        return text

    @staticmethod
    def split_bilingual_value(value):
        text = str(value or "").strip()
        if not text:
            return "", ""

        for separator in [" / ", " | ", " — ", " - "]:
            if separator in text:
                left, right = text.split(separator, 1)
                return left.strip(), right.strip()

        return text, text

    @classmethod
    def normalize_gender(cls, value):
        normalized = str(value or "").strip().casefold()
        if normalized in {"m", "male", "man", "м", "муж", "мужской", "ер", "ер адам"}:
            return "мужской", "ер"
        if normalized in {"f", "female", "woman", "ж", "жен", "женский", "әйел", "әйел адам"}:
            return "женский", "әйел"
        text = str(value or "").strip()
        return text, text

    @classmethod
    def normalize_study_form(cls, value):
        normalized = str(value or "").strip().casefold()
        if normalized in {"full_time", "full-time", "offline", "day", "очная", "очное", "күндізгі"}:
            return "очная", "күндізгі"
        if normalized in {"part_time", "part-time", "evening", "заочная", "заочное", "сырттай"}:
            return "заочная", "сырттай"
        if normalized in {"distance", "online", "remote", "дистанционная", "дистанционное", "қашықтық"}:
            return "дистанционная", "қашықтық"
        text = str(value or "").strip()
        return text, text

    @classmethod
    def normalize_dormitory_need(cls, value):
        normalized = str(value or "").strip().casefold()
        if normalized in {"1", "true", "yes", "y", "да", "нуждаюсь", "need", "needed", "иә", "қажет"}:
            return "нуждаюсь", "қажет"
        if normalized in {"0", "false", "no", "n", "нет", "не нуждаюсь", "not_needed", "жоқ", "қажет емес"}:
            return "не нуждаюсь", "қажет емес"
        text = str(value or "").strip()
        return text, text

    @classmethod
    def inflect_full_name_genitive(cls, full_name):
        full_name = str(full_name or "").strip()
        if not re.search(r"[А-Яа-яЁёӘәІіҢңҒғҮүҰұҚқӨөҺһ]", full_name):
            return full_name

        parts = [part for part in full_name.split() if part]
        if not parts:
            return ""

        gender = cls.guess_gender(parts)
        result = []
        for index, part in enumerate(parts):
            if index == 0:
                result.append(cls.inflect_surname_genitive(part, gender))
            elif index == 1:
                result.append(cls.inflect_first_name_genitive(part, gender))
            else:
                result.append(cls.inflect_patronymic_genitive(part, gender))

        return " ".join(result)

    @staticmethod
    def guess_gender(parts):
        if len(parts) >= 3:
            patronymic = parts[2].casefold()
            if patronymic.endswith(("вна", "чна", "кызы", "қызы")):
                return "female"
            if patronymic.endswith(("вич", "ич", "улы", "ұлы")):
                return "male"

        if len(parts) >= 2:
            first_name = parts[1].casefold()
            if first_name.endswith(("а", "я")):
                return "female"

        return "male"

    @classmethod
    def inflect_surname_genitive(cls, value, gender):
        lower = value.casefold()
        if "-" in value:
            return "-".join(cls.inflect_surname_genitive(part, gender) for part in value.split("-"))

        if gender == "female":
            if lower.endswith(("ова", "ева", "ёва", "ина", "ына")):
                return value[:-1] + "ой"
            if lower.endswith(("ская", "цкая")):
                return value[:-2] + "ой"
            if lower.endswith("ая"):
                return value[:-2] + "ой"
            return value

        if lower.endswith(("ов", "ев", "ёв", "ин", "ын")):
            return value + "а"
        if lower.endswith(("ский", "цкий")):
            return value[:-2] + "ого"
        if lower.endswith("ой"):
            return value[:-2] + "ого"
        if lower.endswith("ий"):
            return value[:-2] + "ия"
        return value

    @classmethod
    def inflect_first_name_genitive(cls, value, gender):
        lower = value.casefold()
        if "-" in value:
            return "-".join(cls.inflect_first_name_genitive(part, gender) for part in value.split("-"))

        if gender == "female":
            if lower.endswith("ия"):
                return value[:-1] + "и"
            if lower.endswith("я"):
                return value[:-1] + "и"
            if lower.endswith("а"):
                return value[:-1] + "ы"
            return value

        if lower.endswith("й"):
            return value[:-1] + "я"
        if lower.endswith("ь"):
            return value[:-1] + "я"
        if lower.endswith("я"):
            return value[:-1] + "и"
        if lower.endswith(("а", "е", "ё", "и", "о", "у", "ы", "э", "ю")):
            return value
        return value + "а"

    @staticmethod
    def inflect_patronymic_genitive(value, gender):
        lower = value.casefold()
        if lower.endswith("вич") or lower.endswith("ич"):
            return value + "а"
        if lower.endswith("вна") or lower.endswith("чна"):
            return value[:-1] + "ы"
        return value

    @staticmethod
    def normalize_faculty_name(value, *, language):
        text = str(value or "").strip()
        if not text:
            return ""

        lowered = text.casefold()
        if language == "kk" and lowered.endswith(" факультеті"):
            return text[: -len(" факультеті")].strip()

        if language == "ru" and lowered.startswith("факультет "):
            return text[len("факультет "):].strip()

        return text

    @staticmethod
    def clean_key(key):
        key = str(key or "").strip().lower()
        key = re.sub(r"[^a-z0-9_]+", "_", key)
        key = re.sub(r"_+", "_", key).strip("_")
        return key

    @staticmethod
    def is_scalar(value):
        return isinstance(value, (str, int, float, bool)) or value is None

    @staticmethod
    def get_first(source, *keys):
        for key in keys:
            value = source.get(key)
            if value not in [None, ""]:
                return value

        return ""

    @staticmethod
    def normalize_choice(value, aliases, default):
        normalized = str(value or "").strip().casefold()

        if not normalized:
            return default

        return aliases.get(normalized, normalized)

    @staticmethod
    def require(field_name, value):
        if value in [None, ""] or not str(value).strip():
            raise AdmissionPayloadError(f"{field_name} is required.")
