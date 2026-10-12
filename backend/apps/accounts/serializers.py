from rest_framework import serializers

from apps.accounts.models import User
from apps.organizations.serializers import FactorySummarySerializer
from apps.organizations.tenancy import get_membership, permitted_factories


class MeSerializer(serializers.ModelSerializer):
    """The logged-in user, with their organization, role and permitted factories."""

    organization = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    all_factories = serializers.SerializerMethodField()
    factories = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "organization", "role", "all_factories", "factories"]
        read_only_fields = fields

    def get_organization(self, user: User) -> dict[str, object] | None:
        membership = get_membership(user)
        if membership is None:
            return None
        return {"id": membership.organization_id, "name": membership.organization.name}

    def get_role(self, user: User) -> str | None:
        membership = get_membership(user)
        return membership.role if membership else None

    def get_all_factories(self, user: User) -> bool:
        membership = get_membership(user)
        return membership.all_factories if membership else False

    def get_factories(self, user: User) -> list[dict[str, object]]:
        return FactorySummarySerializer(permitted_factories(user), many=True).data
