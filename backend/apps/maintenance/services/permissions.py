"""Who may do what with maintenance actions (tenant scoping is applied separately)."""

from apps.accounts.models import User
from apps.maintenance.models import MaintenanceAction
from apps.organizations.models import Factory, Role
from apps.organizations.tenancy import get_membership

SUPERVISORS = frozenset({Role.PRODUCTION_SUPERVISOR, Role.FACTORY_MANAGER, Role.PLATFORM_ADMIN})
REQUESTERS = frozenset(
    {
        Role.MACHINE_OPERATOR,
        Role.QUALITY_INSPECTOR,
        Role.MAINTENANCE_TECHNICIAN,
        Role.PRODUCTION_SUPERVISOR,
        Role.FACTORY_MANAGER,
        Role.PLATFORM_ADMIN,
    }
)


def role(user: User) -> str | None:
    membership = get_membership(user)
    return membership.role if membership else None


def can_request(user: User) -> bool:
    return role(user) in REQUESTERS


def is_supervisor(user: User) -> bool:
    return role(user) in SUPERVISORS


def is_worker(user: User, action: MaintenanceAction) -> bool:
    """The assignee, or any maintenance technician of the action's factory."""
    return action.assignee_id == user.pk or role(user) == Role.MAINTENANCE_TECHNICIAN


def has_factory_access(user: User, factory: Factory) -> bool:
    membership = get_membership(user)
    if membership is None or not user.is_active:
        return False
    if membership.organization_id != factory.organization_id:
        return False
    return membership.all_factories or membership.factories.filter(pk=factory.pk).exists()
