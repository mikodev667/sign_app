from django.conf import settings


class AdmissionsMssqlRouter:
    admissions_mssql_alias = "admissions_mssql"
    admissions_mssql_models = {"admissionmssqlcontractrecord"}

    @classmethod
    def is_admissions_mssql_enabled(cls):
        return (
            getattr(settings, "ADMISSIONS_MSSQL_ENABLED", False)
            and cls.admissions_mssql_alias in settings.DATABASES
        )

    @classmethod
    def is_admissions_mssql_model(cls, model):
        return (
            model._meta.app_label == "admissions"
            and model._meta.model_name in cls.admissions_mssql_models
        )

    def db_for_read(self, model, **hints):
        if self.is_admissions_mssql_model(model) and self.is_admissions_mssql_enabled():
            return self.admissions_mssql_alias

        return None

    def db_for_write(self, model, **hints):
        if self.is_admissions_mssql_model(model) and self.is_admissions_mssql_enabled():
            return self.admissions_mssql_alias

        return None

    def allow_relation(self, obj1, obj2, **hints):
        if self.is_admissions_mssql_model(obj1) or self.is_admissions_mssql_model(obj2):
            return False

        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == self.admissions_mssql_alias and app_label != "admissions":
            return False

        if app_label != "admissions":
            return None

        is_mssql_model = model_name in self.admissions_mssql_models

        if is_mssql_model:
            return db == self.admissions_mssql_alias and self.is_admissions_mssql_enabled()

        if db == self.admissions_mssql_alias:
            return False

        return None
