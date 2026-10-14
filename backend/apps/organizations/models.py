"""Organization hierarchy: Organization -> Factory -> ProductionLine -> Machine,
plus Membership, which gives a user a role inside one organization.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.organizations.oee_settings import default_oee_settings, validate_oee_settings
from apps.organizations.validators import validate_timezone


class Organization(models.Model):
    """A customer (tenant). Its data is never visible to other organizations."""

    name = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Factory(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="factories", db_index=True
    )
    name = models.CharField(max_length=200)
    timezone = models.CharField(
        max_length=64,
        validators=[validate_timezone],
        help_text="IANA timezone used for display, e.g. 'Africa/Algiers'. Data is stored in UTC.",
    )
    oee_settings = models.JSONField(
        default=default_oee_settings,
        validators=[validate_oee_settings],
        help_text="OEE rules for this factory. See apps/organizations/oee_settings.py.",
    )
    stale_after_seconds = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1)],
        help_text=(
            "A machine with no event for longer than this is reported as 'unknown' "
            "(stale telemetry), never as 'running'."
        ),
    )
    escalation_after_seconds = models.PositiveIntegerField(
        default=600,
        validators=[MinValueValidator(1)],
        help_text="A stop lasting longer than this is flagged for escalation to maintenance.",
    )
    recurring_stop_threshold = models.PositiveIntegerField(
        default=3,
        validators=[MinValueValidator(2)],
        help_text="A machine stopping this many times for the same reason (or alarm) is recurring.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__id", "name"]
        verbose_name_plural = "factories"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="unique_factory_name_per_organization"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ProductionLine(models.Model):
    factory = models.ForeignKey(
        Factory, on_delete=models.PROTECT, related_name="lines", db_index=True
    )
    name = models.CharField(max_length=200)
    counting_machine = models.ForeignKey(
        "Machine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Machine whose counter defines the line's output. Empty = last machine.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["factory__id", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["factory", "name"], name="unique_line_name_per_factory"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def output_machine(self) -> "Machine | None":
        """The counting machine, or the last machine in the line if none is set."""
        if self.counting_machine_id is not None:
            return self.counting_machine
        return self.machines.order_by("-position").first()


class Machine(models.Model):
    line = models.ForeignKey(
        ProductionLine, on_delete=models.PROTECT, related_name="machines", db_index=True
    )
    external_id = models.CharField(
        max_length=64, help_text="Identifier used by the machine/simulator, e.g. 'M04'."
    )
    name = models.CharField(max_length=200)
    machine_type = models.CharField(max_length=100, help_text="Free text, e.g. 'filler'.")
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Order of the machine in the line, starting at 1.",
    )
    nominal_speed_per_hour = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Nominal speed in units per hour.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["line__id", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["line", "external_id"], name="unique_machine_external_id_per_line"
            ),
            models.UniqueConstraint(
                fields=["line", "position"], name="unique_machine_position_per_line"
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1), name="machine_position_at_least_1"
            ),
            models.CheckConstraint(
                condition=models.Q(nominal_speed_per_hour__gt=0),
                name="machine_nominal_speed_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.external_id} {self.name}"


class Role(models.TextChoices):
    PLATFORM_ADMIN = "platform_admin", "Platform admin"
    FACTORY_MANAGER = "factory_manager", "Factory manager"
    PRODUCTION_SUPERVISOR = "production_supervisor", "Production supervisor"
    MACHINE_OPERATOR = "machine_operator", "Machine operator"
    MAINTENANCE_TECHNICIAN = "maintenance_technician", "Maintenance technician"
    QUALITY_INSPECTOR = "quality_inspector", "Quality inspector"
    ANALYST = "analyst", "Analyst"


class Membership(models.Model):
    """Links a user to one organization with one role.

    If `all_factories` is True the user can access every factory of the
    organization (including ones created later). Otherwise only the factories
    listed in `factories`.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membership"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships", db_index=True
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    all_factories = models.BooleanField(
        default=False, help_text="Access every factory of the organization."
    )
    factories = models.ManyToManyField(
        Factory,
        blank=True,
        related_name="memberships",
        help_text="Factories this user can access when 'all factories' is off.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization__id", "user__email"]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()} @ {self.organization}"

    def clean(self) -> None:
        if self.role == Role.PLATFORM_ADMIN and not self.all_factories:
            raise ValidationError(
                {"all_factories": "A platform admin must have access to all factories."}
            )
