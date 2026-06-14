from .services import get_user_managed_organizations


def organization_access(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {
            "has_managed_organizations": False,
        }

    return {
        "has_managed_organizations": get_user_managed_organizations(user).exists(),
    }
