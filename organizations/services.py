from django.db.models import Q

from .models import Department, Organization, OrganizationMember


MANAGER_ROLES = [
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
]

DEFAULT_DEPARTMENT_NAME = "General department"


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


def get_user_accessible_organizations(user):
    if not user.is_authenticated:
        return Organization.objects.none()

    return Organization.objects.filter(
        Q(created_by=user)
        | Q(members__user=user)
    ).distinct()


def get_default_accessible_organization(user):
    managed_organization = get_default_managed_organization(user)

    if managed_organization:
        return managed_organization

    if not user.is_authenticated:
        return None

    membership = (
        OrganizationMember.objects
        .select_related("organization")
        .filter(user=user)
        .order_by("created_at", "organization__name")
        .first()
    )

    if membership:
        return membership.organization

    return None


def user_can_manage_organization(user, organization):
    if not organization:
        return False

    return get_user_managed_organizations(user).filter(pk=organization.pk).exists()


def ensure_default_department(organization):
    if not organization:
        return None

    department, _ = Department.objects.get_or_create(
        organization=organization,
        name=DEFAULT_DEPARTMENT_NAME,
        defaults={"is_active": True},
    )
    return department


def get_user_department_ids(user):
    if not user.is_authenticated:
        return OrganizationMember.objects.none().values_list("department_id", flat=True)

    return (
        OrganizationMember.objects
        .filter(user=user, department__isnull=False, department__is_active=True)
        .values_list("department_id", flat=True)
    )


def get_user_accessible_departments(user, organization=None):
    if not user.is_authenticated:
        return Department.objects.none()

    if organization and user_can_manage_organization(user, organization):
        return organization.departments.filter(is_active=True)

    queryset = Department.objects.filter(
        members__user=user,
        is_active=True,
    )

    if organization:
        queryset = queryset.filter(organization=organization)

    managed_organizations = get_user_managed_organizations(user)
    if managed_organizations.exists():
        queryset = (
            queryset
            | Department.objects.filter(
                organization__in=managed_organizations,
                is_active=True,
            )
        )

    return queryset.distinct().order_by("organization__name", "name")


def get_default_department_for_user(user, organization):
    if not organization:
        return None

    if user_can_manage_organization(user, organization):
        return (
            organization.departments
            .filter(is_active=True)
            .order_by("name")
            .first()
            or ensure_default_department(organization)
        )

    membership = (
        OrganizationMember.objects
        .select_related("department")
        .filter(user=user, organization=organization)
        .first()
    )

    if membership and membership.department:
        return membership.department

    return None


def get_department_access_filter(user):
    managed_organizations = get_user_managed_organizations(user)
    department_ids = get_user_department_ids(user)

    return (
        Q(organization__in=managed_organizations)
        | Q(department_id__in=department_ids)
    )


def get_user_organization_memberships(user):
    if not user.is_authenticated:
        return OrganizationMember.objects.none()

    return (
        OrganizationMember.objects
        .select_related("organization", "department")
        .filter(user=user)
        .order_by("organization__name")
    )
