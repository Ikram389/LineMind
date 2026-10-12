"""Django admin: a superuser-only tool that can see every organization.

Tenant isolation applies to the API, not to the admin. Only give admin access
(is_staff) to trusted platform operators.
"""

from typing import Any

from django import forms
from django.contrib import admin

from apps.organizations.models import Factory, Machine, Membership, Organization, ProductionLine


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]


@admin.register(Factory)
class FactoryAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "timezone", "created_at"]
    list_filter = ["organization"]
    search_fields = ["name", "organization__name"]


class MachineInline(admin.TabularInline):
    model = Machine
    extra = 0
    fields = ["position", "external_id", "name", "machine_type", "nominal_speed_per_hour"]


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ["name", "factory", "created_at"]
    list_filter = ["factory__organization", "factory"]
    search_fields = ["name", "factory__name"]
    inlines = [MachineInline]


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = [
        "external_id",
        "name",
        "machine_type",
        "line",
        "position",
        "nominal_speed_per_hour",
    ]
    list_filter = ["line__factory__organization", "line__factory", "line"]
    search_fields = ["external_id", "name", "line__name"]


class MembershipAdminForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ["user", "organization", "role", "all_factories", "factories"]

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        organization = cleaned_data.get("organization")
        factories = cleaned_data.get("factories")
        if organization is not None and factories:
            foreign = [f.name for f in factories if f.organization_id != organization.pk]
            if foreign:
                self.add_error(
                    "factories",
                    f"These factories belong to another organization: {', '.join(foreign)}.",
                )
        return cleaned_data


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    form = MembershipAdminForm
    list_display = ["user", "organization", "role", "all_factories"]
    list_filter = ["organization", "role", "all_factories"]
    search_fields = ["user__email", "organization__name"]
    autocomplete_fields = ["user"]
    filter_horizontal = ["factories"]
