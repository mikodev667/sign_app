from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Organization, OrganizationMember


class OrganizationMembershipTests(TestCase):
    def test_registration_creates_user_without_organization_membership(self):
        response = self.client.post(reverse("accounts:register"), {
            "username": "new-user",
            "password1": "StrongPass12345",
            "password2": "StrongPass12345",
        })

        self.assertRedirects(response, reverse("documents:document_list"))

        user = get_user_model().objects.get(username="new-user")
        self.assertFalse(Organization.objects.filter(created_by=user).exists())
        self.assertFalse(OrganizationMember.objects.filter(user=user).exists())

    def test_owner_can_add_registered_user_to_organization(self):
        owner = get_user_model().objects.create_user(
            username="owner",
            password="password",
        )
        member = get_user_model().objects.create_user(
            username="member",
            email="member@example.com",
            password="password",
        )
        organization = Organization.objects.create(
            name="Owner Organization",
            created_by=owner,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=owner,
            role=OrganizationMember.Role.OWNER,
        )
        self.client.force_login(owner)

        response = self.client.post(
            reverse("organizations:organization_members", args=[organization.pk]),
            {
                "username_or_email": "member@example.com",
                "role": OrganizationMember.Role.MEMBER,
            },
        )

        self.assertRedirects(
            response,
            reverse("organizations:organization_members", args=[organization.pk]),
        )
        self.assertTrue(
            OrganizationMember.objects.filter(
                organization=organization,
                user=member,
                role=OrganizationMember.Role.MEMBER,
            ).exists()
        )

    def test_manager_sees_managed_organization_list(self):
        owner = get_user_model().objects.create_user(
            username="list-owner",
            password="password",
        )
        organization = Organization.objects.create(
            name="List Organization",
            created_by=owner,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=owner,
            role=OrganizationMember.Role.OWNER,
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("organizations:organization_list"))

        self.assertContains(response, "List Organization")
        self.assertContains(
            response,
            reverse("organizations:organization_members", args=[organization.pk]),
        )

    def test_regular_member_cannot_manage_organization_members(self):
        owner = get_user_model().objects.create_user(
            username="access-owner",
            password="password",
        )
        member = get_user_model().objects.create_user(
            username="regular-member",
            password="password",
        )
        organization = Organization.objects.create(
            name="Access Organization",
            created_by=owner,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=owner,
            role=OrganizationMember.Role.OWNER,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=member,
            role=OrganizationMember.Role.MEMBER,
        )
        self.client.force_login(member)

        list_response = self.client.get(reverse("organizations:organization_list"))
        members_response = self.client.get(
            reverse("organizations:organization_members", args=[organization.pk])
        )

        self.assertNotContains(list_response, "Access Organization")
        self.assertEqual(members_response.status_code, 404)

    def test_owner_cannot_add_user_who_already_belongs_to_another_organization(self):
        owner_one = get_user_model().objects.create_user(
            username="first-owner",
            password="password",
        )
        owner_two = get_user_model().objects.create_user(
            username="second-owner",
            password="password",
        )
        member = get_user_model().objects.create_user(
            username="single-org-user",
            email="single@example.com",
            password="password",
        )
        organization_one = Organization.objects.create(
            name="First Organization",
            created_by=owner_one,
        )
        organization_two = Organization.objects.create(
            name="Second Organization",
            created_by=owner_two,
        )
        OrganizationMember.objects.create(
            organization=organization_one,
            user=owner_one,
            role=OrganizationMember.Role.OWNER,
        )
        OrganizationMember.objects.create(
            organization=organization_two,
            user=owner_two,
            role=OrganizationMember.Role.OWNER,
        )
        OrganizationMember.objects.create(
            organization=organization_one,
            user=member,
            role=OrganizationMember.Role.MEMBER,
        )
        self.client.force_login(owner_two)

        response = self.client.post(
            reverse("organizations:organization_members", args=[organization_two.pk]),
            {
                "username_or_email": "single@example.com",
                "role": OrganizationMember.Role.MEMBER,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This user already belongs to another organization.")
        self.assertEqual(OrganizationMember.objects.filter(user=member).count(), 1)

    def test_membership_validation_rejects_user_in_second_organization(self):
        owner = get_user_model().objects.create_user(
            username="validation-owner",
            password="password",
        )
        user = get_user_model().objects.create_user(
            username="validation-user",
            password="password",
        )
        organization_one = Organization.objects.create(
            name="Validation One",
            created_by=owner,
        )
        organization_two = Organization.objects.create(
            name="Validation Two",
            created_by=owner,
        )
        OrganizationMember.objects.create(
            organization=organization_one,
            user=user,
            role=OrganizationMember.Role.MEMBER,
        )

        duplicate_membership = OrganizationMember(
            organization=organization_two,
            user=user,
            role=OrganizationMember.Role.MEMBER,
        )

        with self.assertRaises(ValidationError):
            duplicate_membership.full_clean()

    def test_organizations_navigation_is_visible_only_for_managers(self):
        owner = get_user_model().objects.create_user(
            username="nav-owner",
            password="password",
        )
        member = get_user_model().objects.create_user(
            username="nav-member",
            password="password",
        )
        organization = Organization.objects.create(
            name="Navigation Organization",
            created_by=owner,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=owner,
            role=OrganizationMember.Role.OWNER,
        )
        OrganizationMember.objects.create(
            organization=organization,
            user=member,
            role=OrganizationMember.Role.MEMBER,
        )

        self.client.force_login(owner)
        owner_response = self.client.get(reverse("documents:document_list"))
        self.assertContains(owner_response, reverse("organizations:organization_list"))

        self.client.force_login(member)
        member_response = self.client.get(reverse("documents:document_list"))
        self.assertNotContains(member_response, reverse("organizations:organization_list"))
