from django.db.models import Q

from .models import Organization, OrganizationMember


MANAGER_ROLES = [
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
]


def get_user_managed_organizations(user):
    if not user.is_authenticated:
        return Organization.objects.none()

    return Organization.objects.filter(
        Q(created_by=user)
        | Q(members__user=user, members__role__in=MANAGER_ROLES)
    ).distinct()


def get_default_managed_organization(user):
    if not user.is_authenticated:
        return None

    membership = (
        OrganizationMember.objects
        .select_related("organization")
        .filter(user=user, role__in=MANAGER_ROLES)
        .order_by("created_at", "organization__name")
        .first()
    )

    if membership:
        return membership.organization

    return (
        Organization.objects
        .filter(created_by=user)
        .order_by("created_at", "name")
        .first()
    )


def user_can_manage_organization(user, organization):
    if not organization:
        return False

    return get_user_managed_organizations(user).filter(pk=organization.pk).exists()


def get_user_organization_memberships(user):
    if not user.is_authenticated:
        return OrganizationMember.objects.none()

    return (
        OrganizationMember.objects
        .select_related("organization")
        .filter(user=user)
        .order_by("organization__name")
    )
