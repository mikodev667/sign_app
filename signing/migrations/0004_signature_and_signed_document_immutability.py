from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("signing", "0003_signingauditlog_entry_hash_and_more"),
        ("documents", "0007_storedobject"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION prevent_signature_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'signing_signature is immutable';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS signing_signature_no_update ON signing_signature;
            CREATE TRIGGER signing_signature_no_update
            BEFORE UPDATE ON signing_signature
            FOR EACH ROW EXECUTE FUNCTION prevent_signature_mutation();

            DROP TRIGGER IF EXISTS signing_signature_no_delete ON signing_signature;
            CREATE TRIGGER signing_signature_no_delete
            BEFORE DELETE ON signing_signature
            FOR EACH ROW EXECUTE FUNCTION prevent_signature_mutation();

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

            DROP TRIGGER IF EXISTS documents_document_no_signed_update ON documents_document;
            CREATE TRIGGER documents_document_no_signed_update
            BEFORE UPDATE ON documents_document
            FOR EACH ROW EXECUTE FUNCTION prevent_signed_document_mutation();

            DROP TRIGGER IF EXISTS documents_document_no_signed_delete ON documents_document;
            CREATE TRIGGER documents_document_no_signed_delete
            BEFORE DELETE ON documents_document
            FOR EACH ROW EXECUTE FUNCTION prevent_signed_document_delete();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS signing_signature_no_update ON signing_signature;
            DROP TRIGGER IF EXISTS signing_signature_no_delete ON signing_signature;
            DROP FUNCTION IF EXISTS prevent_signature_mutation();

            DROP TRIGGER IF EXISTS documents_document_no_signed_update ON documents_document;
            DROP TRIGGER IF EXISTS documents_document_no_signed_delete ON documents_document;
            DROP FUNCTION IF EXISTS prevent_signed_document_mutation();
            DROP FUNCTION IF EXISTS prevent_signed_document_delete();
            """,
        ),
    ]
