from django.db import migrations


CLEANUP_FLAG = "qolqoyu.allow_admission_contract_delete"


def install_controlled_cleanup_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE OR REPLACE FUNCTION prevent_signature_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF current_setting('{CLEANUP_FLAG}', true) = 'on' THEN
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;

                    RETURN NEW;
                END IF;

                RAISE EXCEPTION 'signing_signature is immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION prevent_signing_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF current_setting('{CLEANUP_FLAG}', true) = 'on' THEN
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;

                    RETURN NEW;
                END IF;

                RAISE EXCEPTION 'signing_signingauditlog is append-only';
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION prevent_signed_document_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF current_setting('{CLEANUP_FLAG}', true) = 'on' THEN
                    RETURN NEW;
                END IF;

                IF OLD.status = 'signed' THEN
                    RAISE EXCEPTION 'signed documents are immutable';
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION prevent_signed_document_delete()
            RETURNS trigger AS $$
            BEGIN
                IF current_setting('{CLEANUP_FLAG}', true) = 'on' THEN
                    RETURN OLD;
                END IF;

                IF OLD.status = 'signed' THEN
                    RAISE EXCEPTION 'signed documents are immutable';
                END IF;

                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
            """
        )


def restore_strict_immutability_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_signature_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'signing_signature is immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION prevent_signing_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'signing_signingauditlog is append-only';
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION prevent_signed_document_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.status = 'signed' THEN
                    RAISE EXCEPTION 'signed documents are immutable';
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION prevent_signed_document_delete()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.status = 'signed' THEN
                    RAISE EXCEPTION 'signed documents are immutable';
                END IF;

                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0009_admissioncommissionprofile"),
        ("documents", "0014_alter_templatepartyfield_field_type_money"),
        ("signing", "0005_signer_email"),
    ]

    operations = [
        migrations.RunPython(
            install_controlled_cleanup_triggers,
            restore_strict_immutability_triggers,
        ),
    ]
