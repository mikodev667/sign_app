import re


class TemplateService:
    VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

    @classmethod
    def extract_variables(cls, body_template: str) -> list[str]:
        """
        Extract unique variable names from template text.

        Example:
            "Hello {{ full_name }}, amount {{ amount }}"
            -> ["full_name", "amount"]
        """
        if not body_template:
            return []

        variables = cls.VARIABLE_PATTERN.findall(body_template)

        # Keep original order, remove duplicates
        seen = set()
        result = []

        for variable in variables:
            if variable not in seen:
                seen.add(variable)
                result.append(variable)

        return result

    @classmethod
    def validate_template(cls, body_template: str) -> tuple[bool, list[str]]:
        """
        Basic validation for MVP.
        Returns:
            (is_valid, errors)
        """
        errors = []

        if not body_template or not body_template.strip():
            errors.append("Template body cannot be empty.")

        # Detect broken opening braces
        opening_count = body_template.count("{{")
        closing_count = body_template.count("}}")

        if opening_count != closing_count:
            errors.append("Template has invalid variable brackets.")

        return len(errors) == 0, errors