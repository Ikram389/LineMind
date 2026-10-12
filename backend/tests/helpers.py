"""Test helpers shared by all backend tests (fixtures live in backend/conftest.py)."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.organizations.models import (
    Factory,
    Machine,
    Membership,
    Organization,
    ProductionLine,
    Role,
)

TEST_PASSWORD = "test-password-123"

ApiFactory = Callable[[User | None], APIClient]


def create_member(
    email: str,
    organization: Organization,
    role: Role,
    factories: Iterable[Factory] | None = None,
) -> User:
    """Create a user with a membership. `factories=None` means all factories."""
    user = User.objects.create_user(email=email, password=TEST_PASSWORD)
    membership = Membership.objects.create(
        user=user, organization=organization, role=role, all_factories=factories is None
    )
    if factories is not None:
        membership.factories.set(factories)
    return user


def create_machine(line: ProductionLine, external_id: str, position: int) -> Machine:
    return Machine.objects.create(
        line=line,
        external_id=external_id,
        name=f"Machine {external_id}",
        machine_type="filler",
        position=position,
        nominal_speed_per_hour=6000,
    )


def client_for(user: User | None) -> APIClient:
    """An API client that sends a real JWT for `user` (or no token if None)."""
    client = APIClient()
    if user is not None:
        token = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@dataclass
class World:
    """Two organizations; the demo one has two factories (A and B)."""

    demo_org: Organization
    factory_a: Factory
    factory_b: Factory
    line_a: ProductionLine
    line_b: ProductionLine
    machine_a: Machine
    machine_b: Machine
    other_org: Organization
    other_factory: Factory
    other_line: ProductionLine
    other_machine: Machine
    users: dict[str, User] = field(default_factory=dict)


def build_world() -> World:
    demo_org = Organization.objects.create(name="Demo Beverages")
    factory_a = Factory.objects.create(organization=demo_org, name="Plant A", timezone="UTC")
    factory_b = Factory.objects.create(organization=demo_org, name="Plant B", timezone="UTC")
    line_a = ProductionLine.objects.create(factory=factory_a, name="Line A1")
    line_b = ProductionLine.objects.create(factory=factory_b, name="Line B1")

    other_org = Organization.objects.create(name="Other Company")
    other_factory = Factory.objects.create(
        organization=other_org, name="Other Plant", timezone="Europe/Paris"
    )
    other_line = ProductionLine.objects.create(factory=other_factory, name="Other Line")

    world = World(
        demo_org=demo_org,
        factory_a=factory_a,
        factory_b=factory_b,
        line_a=line_a,
        line_b=line_b,
        machine_a=create_machine(line_a, "M01", 1),
        machine_b=create_machine(line_b, "M01", 1),
        other_org=other_org,
        other_factory=other_factory,
        other_line=other_line,
        other_machine=create_machine(other_line, "M01", 1),
    )

    # One demo user per role, each with access to all demo factories.
    for role in Role:
        world.users[role.value] = create_member(f"{role.value}@demo.test", demo_org, role)
    world.users["limited_operator"] = create_member(
        "limited.operator@demo.test", demo_org, Role.MACHINE_OPERATOR, factories=[factory_a]
    )
    world.users["limited_manager"] = create_member(
        "limited.manager@demo.test", demo_org, Role.FACTORY_MANAGER, factories=[factory_a]
    )
    world.users["other_manager"] = create_member(
        "manager@other.test", other_org, Role.FACTORY_MANAGER
    )
    world.users["no_membership"] = User.objects.create_user(
        email="nobody@demo.test", password=TEST_PASSWORD
    )
    return world
