"""Database rules and model validation."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.organizations.admin import MembershipAdminForm
from apps.organizations.models import Factory, Membership, Organization, Role
from apps.organizations.oee_settings import DEFAULT_OEE_SETTINGS
from apps.organizations.tenancy import permitted_factories
from tests.helpers import World, create_machine


def test_external_id_is_unique_within_a_line(world: World) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create_machine(world.line_a, "M01", 2)


def test_same_external_id_is_allowed_on_another_line(world: World) -> None:
    # The fixture already has M01 on both line_a and line_b; one more line to be explicit.
    line = world.factory_a.lines.create(name="Line A2")
    machine = create_machine(line, "M01", 1)

    assert machine.pk is not None


def test_position_is_unique_within_a_line(world: World) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create_machine(world.line_a, "M02", 1)


def test_position_must_be_at_least_one(world: World) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create_machine(world.line_a, "M09", 0)


def test_new_factory_gets_default_oee_settings(world: World) -> None:
    factory = Factory.objects.create(organization=world.demo_org, name="X", timezone="UTC")

    assert factory.oee_settings == DEFAULT_OEE_SETTINGS
    assert factory.oee_settings is not DEFAULT_OEE_SETTINGS


def test_platform_admin_must_cover_all_factories(world: World) -> None:
    membership = Membership(
        user=world.users["no_membership"],
        organization=world.demo_org,
        role=Role.PLATFORM_ADMIN,
        all_factories=False,
    )

    with pytest.raises(ValidationError):
        membership.full_clean()


def test_membership_form_rejects_factories_of_another_organization(world: World) -> None:
    form = MembershipAdminForm(
        data={
            "user": world.users["no_membership"].pk,
            "organization": world.demo_org.pk,
            "role": Role.MACHINE_OPERATOR,
            "all_factories": False,
            "factories": [world.factory_a.pk, world.other_factory.pk],
        }
    )

    assert not form.is_valid()
    assert "factories" in form.errors


def test_membership_form_accepts_own_factories(world: World) -> None:
    form = MembershipAdminForm(
        data={
            "user": world.users["no_membership"].pk,
            "organization": world.demo_org.pk,
            "role": Role.MACHINE_OPERATOR,
            "all_factories": False,
            "factories": [world.factory_a.pk],
        }
    )

    assert form.is_valid(), form.errors


def test_permitted_factories_ignores_wrongly_linked_foreign_factory(world: World) -> None:
    # Even if a foreign factory is linked by mistake (bypassing the form), it is never visible.
    user = world.users["limited_operator"]
    user.membership.factories.add(world.other_factory)

    assert set(permitted_factories(user)) == {world.factory_a}


def test_all_factories_includes_factories_created_later(world: World) -> None:
    new_factory = Factory.objects.create(organization=world.demo_org, name="New", timezone="UTC")

    assert new_factory in permitted_factories(world.users["analyst"])


def test_organization_names_are_unique(db: None) -> None:
    Organization.objects.create(name="Acme")

    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(name="Acme")
