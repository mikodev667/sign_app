import re
from decimal import Decimal, InvalidOperation


class MoneyAmountService:
    FIELD_TYPE_MONEY = "money"
    DERIVED_SUFFIXES = ("words_ru", "words_kk", "full_ru", "full_kk")

    RU_HUNDREDS = {
        1: "сто",
        2: "двести",
        3: "триста",
        4: "четыреста",
        5: "пятьсот",
        6: "шестьсот",
        7: "семьсот",
        8: "восемьсот",
        9: "девятьсот",
    }
    RU_TENS = {
        2: "двадцать",
        3: "тридцать",
        4: "сорок",
        5: "пятьдесят",
        6: "шестьдесят",
        7: "семьдесят",
        8: "восемьдесят",
        9: "девяносто",
    }
    RU_TEENS = {
        10: "десять",
        11: "одиннадцать",
        12: "двенадцать",
        13: "тринадцать",
        14: "четырнадцать",
        15: "пятнадцать",
        16: "шестнадцать",
        17: "семнадцать",
        18: "восемнадцать",
        19: "девятнадцать",
    }
    RU_UNITS_MASCULINE = {
        1: "один",
        2: "два",
        3: "три",
        4: "четыре",
        5: "пять",
        6: "шесть",
        7: "семь",
        8: "восемь",
        9: "девять",
    }
    RU_UNITS_FEMININE = {
        **RU_UNITS_MASCULINE,
        1: "одна",
        2: "две",
    }
    RU_SCALES = (
        None,
        ("тысяча", "тысячи", "тысяч"),
        ("миллион", "миллиона", "миллионов"),
        ("миллиард", "миллиарда", "миллиардов"),
        ("триллион", "триллиона", "триллионов"),
    )

    KK_UNITS = {
        1: "бір",
        2: "екі",
        3: "үш",
        4: "төрт",
        5: "бес",
        6: "алты",
        7: "жеті",
        8: "сегіз",
        9: "тоғыз",
    }
    KK_TENS = {
        1: "он",
        2: "жиырма",
        3: "отыз",
        4: "қырық",
        5: "елу",
        6: "алпыс",
        7: "жетпіс",
        8: "сексен",
        9: "тоқсан",
    }
    KK_SCALES = ("", "мың", "миллион", "миллиард", "триллион")

    @classmethod
    def variable_names_for_field(cls, field_name, field_type):
        field_name = (field_name or "").strip()

        if not field_name:
            return []

        names = [field_name]

        if field_type == cls.FIELD_TYPE_MONEY:
            names.extend(cls.derived_field_names(field_name))

        return names

    @classmethod
    def derived_field_names(cls, field_name):
        return [f"{field_name}_{suffix}" for suffix in cls.DERIVED_SUFFIXES]

    @classmethod
    def derived_field_names_for_fields(cls, field_names):
        result = []

        for field_name in field_names or []:
            result.extend(cls.derived_field_names(field_name))

        return result

    @classmethod
    def is_derived_field_name(cls, field_name, money_field_names):
        return field_name in cls.derived_field_names_for_fields(money_field_names)

    @classmethod
    def get_template_money_field_names(cls, template):
        if not template:
            return []

        result = []

        for group in template.field_schema or []:
            for field in group.get("fields", []):
                if field.get("type", "text") != cls.FIELD_TYPE_MONEY:
                    continue

                key = (field.get("key") or "").strip()
                if key:
                    result.append(key)

        for party in template.parties.prefetch_related("fields").all():
            for field in party.fields.all():
                if field.field_type == cls.FIELD_TYPE_MONEY:
                    result.append(f"{party.variable_prefix}_{field.variable_name}")

        return list(dict.fromkeys(result))

    @classmethod
    def get_template_field_type_map(cls, template):
        if not template:
            return {}

        field_types = {}

        for group in template.field_schema or []:
            for field in group.get("fields", []):
                key = (field.get("key") or "").strip()
                if key:
                    field_types[key] = field.get("type", "text")

        for party in template.parties.prefetch_related("fields").all():
            for field in party.fields.all():
                field_types[f"{party.variable_prefix}_{field.variable_name}"] = field.field_type

        return field_types

    @classmethod
    def expand_template_values(cls, template, values):
        expanded = dict(values or {})

        for field_name in cls.get_template_money_field_names(template):
            expanded.update(cls.build_value_context(field_name, expanded.get(field_name, "")))

        return expanded

    @classmethod
    def build_value_context(cls, field_name, raw_value):
        empty_context = {
            field_name: raw_value or "",
            f"{field_name}_words_ru": "",
            f"{field_name}_words_kk": "",
            f"{field_name}_full_ru": "",
            f"{field_name}_full_kk": "",
        }

        if not str(raw_value or "").strip():
            return empty_context

        amount = cls.parse_amount(raw_value)
        if amount is None:
            return empty_context

        formatted = cls.format_amount(amount)
        words_ru = cls.amount_to_words_ru(amount)
        words_kk = cls.amount_to_words_kk(amount)

        return {
            field_name: formatted,
            f"{field_name}_words_ru": words_ru,
            f"{field_name}_words_kk": words_kk,
            f"{field_name}_full_ru": f"{formatted} ({words_ru})",
            f"{field_name}_full_kk": f"{formatted} ({words_kk})",
        }

    @classmethod
    def is_valid_amount(cls, raw_value):
        if not str(raw_value or "").strip():
            return True

        return cls.parse_amount(raw_value) is not None

    @classmethod
    def parse_amount(cls, raw_value):
        normalized = str(raw_value or "").strip()

        if not normalized:
            return None

        normalized = (
            normalized
            .replace("\xa0", "")
            .replace(" ", "")
            .replace("_", "")
        )

        if "," in normalized and "." not in normalized:
            normalized = normalized.replace(",", ".")

        if not re.fullmatch(r"\d+(\.\d+)?", normalized):
            return None

        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            return None

        if amount < 0 or amount != amount.to_integral_value():
            return None

        return int(amount)

    @classmethod
    def format_amount(cls, amount):
        return f"{amount:,}".replace(",", " ")

    @classmethod
    def amount_to_words_ru(cls, amount):
        amount = int(amount)

        if amount == 0:
            return "ноль тенге"

        parts = []
        group_index = 0

        while amount:
            group_value = amount % 1000

            if group_value:
                gender = "feminine" if group_index == 1 else "masculine"
                group_parts = cls.triplet_to_words_ru(group_value, gender=gender)
                scale_forms = cls.RU_SCALES[group_index] if group_index < len(cls.RU_SCALES) else None

                if scale_forms:
                    group_parts.append(cls.plural_form_ru(group_value, scale_forms))

                parts.insert(0, " ".join(group_parts))

            amount //= 1000
            group_index += 1

        parts.append("тенге")
        return " ".join(parts)

    @classmethod
    def triplet_to_words_ru(cls, number, *, gender="masculine"):
        parts = []
        hundreds = number // 100
        rest = number % 100

        if hundreds:
            parts.append(cls.RU_HUNDREDS[hundreds])

        if 10 <= rest <= 19:
            parts.append(cls.RU_TEENS[rest])
            return parts

        tens = rest // 10
        units = rest % 10

        if tens:
            parts.append(cls.RU_TENS[tens])

        if units:
            unit_words = (
                cls.RU_UNITS_FEMININE
                if gender == "feminine"
                else cls.RU_UNITS_MASCULINE
            )
            parts.append(unit_words[units])

        return parts

    @classmethod
    def plural_form_ru(cls, number, forms):
        last_two = number % 100
        last = number % 10

        if 11 <= last_two <= 14:
            return forms[2]

        if last == 1:
            return forms[0]

        if 2 <= last <= 4:
            return forms[1]

        return forms[2]

    @classmethod
    def amount_to_words_kk(cls, amount):
        amount = int(amount)

        if amount == 0:
            return "нөл теңге"

        parts = []
        group_index = 0

        while amount:
            group_value = amount % 1000

            if group_value:
                group_parts = cls.triplet_to_words_kk(group_value)
                scale = cls.KK_SCALES[group_index] if group_index < len(cls.KK_SCALES) else ""

                if scale:
                    group_parts.append(scale)

                parts.insert(0, " ".join(group_parts))

            amount //= 1000
            group_index += 1

        parts.append("теңге")
        return " ".join(parts)

    @classmethod
    def triplet_to_words_kk(cls, number):
        parts = []
        hundreds = number // 100
        rest = number % 100
        tens = rest // 10
        units = rest % 10

        if hundreds:
            if hundreds > 1:
                parts.append(cls.KK_UNITS[hundreds])
            parts.append("жүз")

        if tens:
            parts.append(cls.KK_TENS[tens])

        if units:
            parts.append(cls.KK_UNITS[units])

        return parts
