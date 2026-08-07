from pathlib import Path
import unicodedata
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import Document, DocumentTemplate, TemplateParty, TemplatePartyField
from documents.services.docx_template_service import VARIABLE_PATTERN
from documents.services.money_amount_service import MoneyAmountService
from organizations.models import Department, Organization


class Command(BaseCommand):
    help = "Create KazNU Business School templates from prepared TrustMe DOCX files."

    PARTY_FIELD_LABELS = {
        "full_name": "ФИО",
        "iin_bin": "ИИН / БИН",
        "phone": "Телефон",
        "email": "Email",
        "signing_method": "Способ подписания",
        "address": "Адрес",
        "citizenship": "Гражданство",
        "identity_document": "Документ, удостоверяющий личность",
        "representative_full_name": "ФИО представителя",
        "authority_basis": "Основание полномочий",
    }

    PARTY_FIELD_TYPES = {
        "iin_bin": TemplatePartyField.FieldType.IIN_BIN,
        "phone": TemplatePartyField.FieldType.PHONE,
        "email": TemplatePartyField.FieldType.EMAIL,
        "signing_method": TemplatePartyField.FieldType.SIGNING_METHOD,
    }

    PROGRAM_FIELDS = [
        ("program_code", "Код образовательной программы"),
        ("program_name_ru", "Название программы (RU)"),
        ("program_name_kk", "Название программы (KZ)"),
        ("program_name_en", "Название программы (EN)"),
        ("program_faculty_ru", "Факультет (RU)"),
        ("program_faculty_kk", "Факультет (KZ)"),
        ("program_duration_ru", "Срок обучения (RU)"),
        ("program_duration_en", "Срок обучения (EN)"),
        ("qualification_ru", "Квалификация (RU)"),
        ("qualification_en", "Квалификация (EN)"),
    ]

    UNIVERSITY_FIELDS = [
        ("university_representative_full_name", "ФИО представителя университета"),
        ("university_authority_number", "Номер доверенности"),
        ("university_authority_date_ru", "Дата доверенности (RU)"),
        ("university_authority_date_kk", "Дата доверенности (KZ)"),
        ("university_authority_date_en", "Дата доверенности (EN)"),
        ("university_authority_year", "Год доверенности"),
    ]

    CONTRACT_TEXT_FIELDS = [
        ("contract_date_text_en", "Дата договора прописью (EN)"),
    ]

    MONEY_BASE_FIELDS = [
        ("tuition_amount", "Стоимость обучения"),
        ("year_1_amount", "Сумма за 1 год"),
        ("year_2_amount", "Сумма за 2 год"),
        ("year_3_amount", "Сумма за 3 год"),
    ]

    SYSTEM_VARIABLES = set(Document.SYSTEM_FIELD_NAMES)

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Owner user for created templates.")
        parser.add_argument("--organization", default="КазНУ", help="Organization name.")
        parser.add_argument("--department", default="Бизнес школа", help="Department name.")
        parser.add_argument(
            "--templates-dir",
            default="prepared_templates/trustme_docs",
            help="Directory with prepared TrustMe DOCX files.",
        )
        parser.add_argument(
            "--replace-files",
            action="store_true",
            help="Replace template files even when templates already exist.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        owner = User.objects.filter(username=options["username"]).first()
        if not owner:
            raise CommandError(f"User '{options['username']}' was not found.")

        templates_dir = Path(options["templates_dir"])
        if not templates_dir.is_absolute():
            templates_dir = Path.cwd() / templates_dir

        if not templates_dir.exists():
            raise CommandError(f"Templates directory does not exist: {templates_dir}")

        template_paths = sorted(templates_dir.glob("*_prepared.docx"))
        if not template_paths:
            raise CommandError(f"No prepared DOCX files were found in: {templates_dir}")

        organization, _ = Organization.objects.get_or_create(
            name=self.normalize_text(options["organization"]),
            defaults={"created_by": owner},
        )
        if organization.created_by_id != owner.id:
            organization.created_by = owner
            organization.save(update_fields=["created_by", "updated_at"])

        department, _ = Department.objects.get_or_create(
            organization=organization,
            name=self.normalize_text(options["department"]),
            defaults={"is_active": True},
        )
        if not department.is_active:
            department.is_active = True
            department.save(update_fields=["is_active", "updated_at"])

        for template_path in template_paths:
            template = self.ensure_template(
                template_path=template_path,
                owner=owner,
                organization=organization,
                department=department,
                replace_files=options["replace_files"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Ready: {template.id} {template.title} ({template.department})"
                )
            )

        self.stdout.write(self.style.SUCCESS("TrustMe templates are ready."))

    def ensure_template(
        self,
        *,
        template_path,
        owner,
        organization,
        department,
        replace_files,
    ):
        title = self.title_from_path(template_path)
        docx_variables = self.extract_docx_variables(template_path)
        is_three_party = self.is_three_party_template(template_path, docx_variables)

        field_schema = self.build_field_schema(docx_variables)

        template = DocumentTemplate.objects.filter(
            title=title,
            organization=organization,
            department=department,
        ).first()
        created = template is None

        if created:
            template = DocumentTemplate(
                title=title,
                organization=organization,
                department=department,
                created_by=owner,
                status=DocumentTemplate.Status.ACTIVE,
                body_template="",
                variables=[],
                field_schema=field_schema,
            )

        changed = False
        for field_name, value in {
            "organization": organization,
            "department": department,
            "created_by": owner,
            "status": DocumentTemplate.Status.ACTIVE,
            "field_schema": field_schema,
            "body_template": "",
        }.items():
            if getattr(template, field_name) != value:
                setattr(template, field_name, value)
                changed = True

        old_file_name = template.template_file.name if template.template_file else ""
        if created or replace_files or not template.template_file:
            with template_path.open("rb") as template_file:
                template.template_file.save(template_path.name, File(template_file), save=False)
            changed = True

        if changed:
            template.save()

        if old_file_name and old_file_name != template.template_file.name:
            default_storage.delete(old_file_name)

        self.ensure_parties(template=template, docx_variables=docx_variables, is_three_party=is_three_party)
        template.variables = self.build_template_variables(template, docx_variables, field_schema)
        template.save(update_fields=["variables", "updated_at"])
        return template

    @staticmethod
    def title_from_path(template_path):
        title = template_path.stem
        if title.endswith("_prepared"):
            title = title[: -len("_prepared")]
        return Command.normalize_text(title.strip())

    @staticmethod
    def normalize_text(value):
        return unicodedata.normalize("NFC", str(value or ""))

    @staticmethod
    def is_three_party_template(template_path, docx_variables):
        lower_name = template_path.name.lower()
        return "трехсторон" in lower_name or any(
            variable.startswith("side_2_") for variable in docx_variables
        )

    @staticmethod
    def extract_docx_variables(template_path):
        variables = []

        with ZipFile(template_path, "r") as archive:
            for item in archive.infolist():
                if not item.filename.startswith("word/") or not item.filename.endswith(".xml"):
                    continue

                text = archive.read(item.filename).decode("utf-8", errors="ignore")
                for variable in VARIABLE_PATTERN.findall(text):
                    if variable not in variables:
                        variables.append(variable)

        return variables

    def ensure_parties(self, *, template, docx_variables, is_three_party):
        side_1 = self.ensure_party(
            template=template,
            variable_prefix="side_1",
            title="Обучающийся",
            party_type=TemplateParty.PartyType.INDIVIDUAL,
            signing_order=1,
        )
        self.ensure_party_fields(
            party=side_1,
            docx_variables=docx_variables,
            extra_field_names=["address", "citizenship", "identity_document"],
        )

        if is_three_party:
            side_2 = self.ensure_party(
                template=template,
                variable_prefix="side_2",
                title="Заказчик",
                party_type=TemplateParty.PartyType.COMPANY,
                signing_order=2,
            )
            self.ensure_party_fields(
                party=side_2,
                docx_variables=docx_variables,
                extra_field_names=["address", "representative_full_name", "authority_basis", "email"],
            )

    @staticmethod
    def ensure_party(*, template, variable_prefix, title, party_type, signing_order):
        party, _ = TemplateParty.objects.update_or_create(
            template=template,
            variable_prefix=variable_prefix,
            defaults={
                "title": title,
                "party_type": party_type,
                "signing_order": signing_order,
                "is_signer": True,
            },
        )
        return party

    def ensure_party_fields(self, *, party, docx_variables, extra_field_names):
        field_names = [
            TemplatePartyField.SystemField.FULL_NAME,
            TemplatePartyField.SystemField.IIN_BIN,
            TemplatePartyField.SystemField.PHONE,
            TemplatePartyField.SystemField.EMAIL,
            TemplatePartyField.SystemField.SIGNING_METHOD,
        ]

        for extra_name in extra_field_names:
            if f"{party.variable_prefix}_{extra_name}" in docx_variables and extra_name not in field_names:
                field_names.append(extra_name)

        for index, field_name in enumerate(field_names, start=1):
            self.ensure_party_field(party=party, field_name=field_name, order=index)

    def ensure_party_field(self, *, party, field_name, order):
        is_system = field_name in TemplatePartyField.SystemField.values
        TemplatePartyField.objects.update_or_create(
            party=party,
            variable_name=field_name,
            defaults={
                "label": self.PARTY_FIELD_LABELS.get(field_name, field_name.replace("_", " ").title()),
                "field_type": self.PARTY_FIELD_TYPES.get(field_name, TemplatePartyField.FieldType.TEXT),
                "is_required": is_system,
                "is_system": is_system,
                "order": order,
            },
        )

    def build_field_schema(self, docx_variables):
        variable_set = set(docx_variables)
        groups = []

        self.add_group(
            groups,
            "Договор",
            self.fields_present(variable_set, self.CONTRACT_TEXT_FIELDS),
        )
        self.add_group(
            groups,
            "Образовательная программа",
            self.fields_present(variable_set, self.PROGRAM_FIELDS),
        )
        self.add_group(
            groups,
            "Университет",
            self.fields_present(variable_set, self.UNIVERSITY_FIELDS),
        )
        self.add_group(
            groups,
            "Стоимость обучения",
            self.money_fields_present(variable_set, self.MONEY_BASE_FIELDS)
            + self.fields_present(variable_set, [("tuition_amount_full_en", "Стоимость обучения прописью (EN)")]),
        )

        for year in range(1, 4):
            self.add_group(
                groups,
                f"График оплат - {year} год",
                self.tranche_fields_present(variable_set, year),
            )

        return groups

    @staticmethod
    def add_group(groups, title, fields):
        if fields:
            groups.append({"title": title, "fields": fields})

    @staticmethod
    def fields_present(variable_set, specs):
        fields = []
        for key, label in specs:
            if key in variable_set:
                fields.append({
                    "label": label,
                    "key": key,
                    "type": "text",
                    "placeholder": label,
                })
        return fields

    @staticmethod
    def money_fields_present(variable_set, specs):
        fields = []
        for key, label in specs:
            derived_keys = set(MoneyAmountService.derived_field_names(key))
            if key in variable_set or variable_set.intersection(derived_keys):
                fields.append({
                    "label": label,
                    "key": key,
                    "type": MoneyAmountService.FIELD_TYPE_MONEY,
                    "placeholder": label,
                })
        return fields

    @staticmethod
    def tranche_fields_present(variable_set, year):
        fields = []

        for tranche in range(1, 7):
            amount_key = f"year_{year}_tranche_{tranche}_amount"
            due_date_key = f"year_{year}_tranche_{tranche}_due_date"

            if amount_key in variable_set:
                fields.append({
                    "label": f"Транш {tranche} - сумма",
                    "key": amount_key,
                    "type": MoneyAmountService.FIELD_TYPE_MONEY,
                    "placeholder": f"Транш {tranche} - сумма",
                })

            if due_date_key in variable_set:
                fields.append({
                    "label": f"Транш {tranche} - срок оплаты",
                    "key": due_date_key,
                    "type": "text",
                    "placeholder": f"Транш {tranche} - срок оплаты",
                })

        return fields

    def build_template_variables(self, template, docx_variables, field_schema):
        variables = list(docx_variables)

        for group in field_schema or []:
            for field in group.get("fields", []):
                variables.extend(
                    MoneyAmountService.variable_names_for_field(
                        field.get("key", ""),
                        field.get("type", "text"),
                    )
                )

        for party in template.parties.prefetch_related("fields").all():
            for field in party.fields.all():
                variables.extend(
                    MoneyAmountService.variable_names_for_field(
                        f"{party.variable_prefix}_{field.variable_name}",
                        field.field_type,
                    )
                )

        return list(dict.fromkeys(variables))
