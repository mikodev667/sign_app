from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from admissions.models import AdmissionTemplateRule, AdmissionViceRectorProfile
from documents.models import DocumentTemplate, TemplateParty, TemplatePartyField
from organizations.models import Department, Organization


class Command(BaseCommand):
    help = "Create admission document templates, signer parties and template rules."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Owner user for created templates.")
        parser.add_argument("--organization", default="KazNU", help="Organization name.")
        parser.add_argument("--department", default="Admissions", help="Department name.")
        parser.add_argument("--vice-username", default="", help="Existing user for vice rector cabinet.")
        parser.add_argument("--vice-full-name", default="Представитель университета", help="Vice rector full name.")
        parser.add_argument("--vice-iin", default="222222222222", help="Vice rector IIN.")
        parser.add_argument("--vice-phone", default="", help="Vice rector phone.")
        parser.add_argument("--vice-email", default="", help="Vice rector email.")
        parser.add_argument(
            "--templates-dir",
            default="prepared_templates/admissions",
            help="Directory with prepared admissions DOCX files.",
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

        vice_user = owner
        if options["vice_username"]:
            vice_user = User.objects.filter(username=options["vice_username"]).first()
            if not vice_user:
                raise CommandError(f"Vice rector user '{options['vice_username']}' was not found.")

        organization, _ = Organization.objects.get_or_create(
            name=options["organization"],
            defaults={"created_by": owner},
        )
        department, _ = Department.objects.get_or_create(
            organization=organization,
            name=options["department"],
        )

        templates_dir = Path(options["templates_dir"])
        if not templates_dir.is_absolute():
            templates_dir = Path.cwd() / templates_dir

        if not templates_dir.exists():
            raise CommandError(f"Templates directory does not exist: {templates_dir}")

        templates = {
            "contract_paid": self.ensure_template(
                title="Admission contract paid 2026",
                filename="Договор_всеуровни_платный_2026_prepared.docx",
                templates_dir=templates_dir,
                owner=owner,
                organization=organization,
                department=department,
                contract_template=True,
                replace_files=options["replace_files"],
            ),
            "contract_bachelor_grant": self.ensure_template(
                title="Admission contract bachelor grant 2026",
                filename="Договор_бак_грант_2026_prepared.docx",
                templates_dir=templates_dir,
                owner=owner,
                organization=organization,
                department=department,
                contract_template=True,
                replace_files=options["replace_files"],
            ),
            "contract_master_grant": self.ensure_template(
                title="Admission contract master grant 2026",
                filename="Договор_маг_грант_2026_prepared.docx",
                templates_dir=templates_dir,
                owner=owner,
                organization=organization,
                department=department,
                contract_template=True,
                replace_files=options["replace_files"],
            ),
            "contract_doctoral_grant": self.ensure_template(
                title="Admission contract doctoral grant 2026",
                filename="Договор_док_грант_2026_prepared.docx",
                templates_dir=templates_dir,
                owner=owner,
                organization=organization,
                department=department,
                contract_template=True,
                replace_files=options["replace_files"],
            ),
            "application_bachelor": self.ensure_template(
                title="Admission application bachelor 2025",
                filename="1_Заявление_бак 2025_10000_prepared.docx",
                templates_dir=templates_dir,
                owner=owner,
                organization=organization,
                department=department,
                contract_template=False,
                replace_files=options["replace_files"],
            ),
            "application_master_doctoral": self.ensure_template(
                title="Admission application master doctoral 2025",
                filename="1_Заявление_маг_док 2025_3000_prepared.docx",
                templates_dir=templates_dir,
                owner=owner,
                organization=organization,
                department=department,
                contract_template=False,
                replace_files=options["replace_files"],
            ),
        }

        vice_rector, _ = AdmissionViceRectorProfile.objects.update_or_create(
            user=vice_user,
            defaults={
                "organization": organization,
                "department": department,
                "full_name": options["vice_full_name"],
                "iin": options["vice_iin"],
                "phone": options["vice_phone"],
                "email": options["vice_email"],
                "is_active": True,
            },
        )

        self.ensure_rules(templates=templates, vice_rector=vice_rector)

        self.stdout.write(self.style.SUCCESS("Admission templates and rules are ready."))

    def ensure_template(
        self,
        *,
        title,
        filename,
        templates_dir,
        owner,
        organization,
        department,
        contract_template,
        replace_files=False,
    ):
        path = templates_dir / filename
        if not path.exists():
            raise CommandError(f"Template file was not found: {path}")

        template, created = DocumentTemplate.objects.get_or_create(
            title=title,
            defaults={
                "organization": organization,
                "department": department,
                "created_by": owner,
                "variables": [],
                "field_schema": [],
            },
        )

        changed = False
        for field_name, value in {
            "organization": organization,
            "department": department,
            "created_by": owner,
            "status": DocumentTemplate.Status.ACTIVE,
        }.items():
            if getattr(template, field_name) != value:
                setattr(template, field_name, value)
                changed = True

        if replace_files or created or not template.template_file:
            with path.open("rb") as template_file:
                template.template_file.save(path.name, File(template_file), save=False)
            changed = True

        if changed:
            template.save()

        if contract_template:
            self.ensure_signer_parties(template)

        return template

    def ensure_signer_parties(self, template):
        student_party, _ = TemplateParty.objects.update_or_create(
            template=template,
            variable_prefix="side_1",
            defaults={
                "title": "Applicant",
                "party_type": TemplateParty.PartyType.INDIVIDUAL,
                "signing_order": 1,
                "is_signer": True,
            },
        )
        vice_party, _ = TemplateParty.objects.update_or_create(
            template=template,
            variable_prefix="side_2",
            defaults={
                "title": "Проректор",
                "party_type": TemplateParty.PartyType.INDIVIDUAL,
                "signing_order": 2,
                "is_signer": True,
            },
        )

        for party in [student_party, vice_party]:
            self.ensure_system_party_field(
                party=party,
                label="Full name",
                variable_name=TemplatePartyField.SystemField.FULL_NAME,
                field_type=TemplatePartyField.FieldType.TEXT,
                order=1,
            )
            self.ensure_system_party_field(
                party=party,
                label="IIN / BIN",
                variable_name=TemplatePartyField.SystemField.IIN_BIN,
                field_type=TemplatePartyField.FieldType.IIN_BIN,
                order=2,
            )
            self.ensure_system_party_field(
                party=party,
                label="Phone",
                variable_name=TemplatePartyField.SystemField.PHONE,
                field_type=TemplatePartyField.FieldType.PHONE,
                order=3,
            )
            self.ensure_system_party_field(
                party=party,
                label="Signing method",
                variable_name=TemplatePartyField.SystemField.SIGNING_METHOD,
                field_type=TemplatePartyField.FieldType.SIGNING_METHOD,
                order=4,
            )

    @staticmethod
    def ensure_system_party_field(*, party, label, variable_name, field_type, order):
        TemplatePartyField.objects.update_or_create(
            party=party,
            variable_name=variable_name,
            defaults={
                "label": label,
                "field_type": field_type,
                "is_required": True,
                "is_system": True,
                "order": order,
            },
        )

    def ensure_rules(self, *, templates, vice_rector):
        rule_specs = [
            (
                "Bachelor paid",
                AdmissionTemplateRule.EducationLevel.BACHELOR,
                AdmissionTemplateRule.FundingType.PAID,
                templates["contract_paid"],
                templates["application_bachelor"],
                100,
            ),
            (
                "Master paid",
                AdmissionTemplateRule.EducationLevel.MASTER,
                AdmissionTemplateRule.FundingType.PAID,
                templates["contract_paid"],
                templates["application_master_doctoral"],
                110,
            ),
            (
                "Doctoral paid",
                AdmissionTemplateRule.EducationLevel.DOCTORAL,
                AdmissionTemplateRule.FundingType.PAID,
                templates["contract_paid"],
                templates["application_master_doctoral"],
                120,
            ),
            (
                "Bachelor grant",
                AdmissionTemplateRule.EducationLevel.BACHELOR,
                AdmissionTemplateRule.FundingType.GRANT,
                templates["contract_bachelor_grant"],
                templates["application_bachelor"],
                200,
            ),
            (
                "Master grant",
                AdmissionTemplateRule.EducationLevel.MASTER,
                AdmissionTemplateRule.FundingType.GRANT,
                templates["contract_master_grant"],
                templates["application_master_doctoral"],
                210,
            ),
            (
                "Doctoral grant",
                AdmissionTemplateRule.EducationLevel.DOCTORAL,
                AdmissionTemplateRule.FundingType.GRANT,
                templates["contract_doctoral_grant"],
                templates["application_master_doctoral"],
                220,
            ),
        ]

        for title, education_level, funding_type, template, application_template, priority in rule_specs:
            AdmissionTemplateRule.objects.update_or_create(
                title=title,
                defaults={
                    "education_level": education_level,
                    "funding_type": funding_type,
                    "language": AdmissionTemplateRule.Language.ANY,
                    "program_code": "",
                    "template": template,
                    "application_template": application_template,
                    "vice_rector": vice_rector,
                    "priority": priority,
                    "is_active": True,
                },
            )
