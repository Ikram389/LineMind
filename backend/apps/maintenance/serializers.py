from typing import Any

from rest_framework import serializers

from apps.accounts.models import User
from apps.downtime.models import DowntimeReason
from apps.maintenance.models import (
    ActionLink,
    MaintenanceAction,
    MaintenanceDiagnosis,
    MaintenanceEntry,
    MaintenanceStatusChange,
    Status,
    VerificationResult,
)
from apps.maintenance.services.workflow import allowed_steps
from apps.organizations.models import Machine
from apps.organizations.serializers import ScopedPrimaryKeyRelatedField
from apps.organizations.tenancy import scope_to_organization

MAX_TEXT = 4000


class UserField(serializers.PrimaryKeyRelatedField):
    """A user of the requesting user's organization (factory access is checked by the service)."""

    def get_queryset(self):  # type: ignore[no-untyped-def]
        request = self.context.get("request")
        if request is None:
            return User.objects.none()
        return scope_to_organization(User.objects.all(), request.user, "membership__organization")


class _Person(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()


def person(user: User | None) -> dict[str, Any] | None:
    return {"id": user.pk, "email": user.email} if user else None


class LinkInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["downtime_event", "incident", "alert", "inspection_result", "signature"]
    )
    id = serializers.IntegerField(required=False)
    machine = serializers.IntegerField(required=False)
    reason = serializers.IntegerField(required=False, allow_null=True)
    alarm_code = serializers.CharField(required=False, allow_blank=True, max_length=50)


class ActionLinkSerializer(serializers.ModelSerializer):
    target = serializers.SerializerMethodField()

    class Meta:
        model = ActionLink
        fields = ["id", "kind", "target", "created_at"]

    def get_target(self, link: ActionLink) -> dict[str, Any]:
        if link.kind == "downtime_event" and link.downtime_event:
            e = link.downtime_event
            reason = e.current_classification.reason if e.current_classification else None
            return {
                "id": e.pk,
                "machine": e.machine.name,
                "started_at": e.started_at,
                "ended_at": e.ended_at,
                "alarm_code": e.alarm_code,
                "category": e.category,
                "incident_id": e.incident_id,
                "reason": reason.code if reason else None,
            }
        if link.kind == "incident" and link.incident:
            i = link.incident
            return {
                "id": i.pk,
                "started_at": i.started_at,
                "ended_at": i.ended_at,
                "first_machine": i.first_machine.name if i.first_machine else None,
            }
        if link.kind == "alert" and link.alert:
            a = link.alert
            return {
                "id": a.pk,
                "message_key": a.message_key,
                "message_values": a.message_values,
                "severity": a.severity,
                "status": a.status,
                "opened_at": a.opened_at,
            }
        if link.kind == "inspection_result" and link.inspection_result:
            r = link.inspection_result
            return {
                "id": r.pk,
                "timestamp": r.timestamp,
                "reported_code": r.reported_code,
                "machine": r.machine.name,
            }
        return {
            "machine": {"id": link.signature_machine_id, "name": link.signature_machine.name},
            "reason": (
                {
                    "id": link.signature_reason_id,
                    "code": link.signature_reason.code,
                    "name": link.signature_reason.name,
                }
                if link.signature_reason
                else None
            ),
            "alarm_code": link.signature_alarm_code or None,
        }


class MaintenanceActionSerializer(serializers.ModelSerializer):
    machine = ScopedPrimaryKeyRelatedField(
        queryset=Machine.objects.all(), factory_path="line__factory"
    )
    assignee = UserField(required=False, allow_null=True)
    links = LinkInputSerializer(many=True, write_only=True, required=False)
    reporter = serializers.SerializerMethodField()
    assignee_detail = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    machine_name = serializers.CharField(source="machine.name", read_only=True)
    line_name = serializers.CharField(source="line.name", read_only=True)
    factory_timezone = serializers.CharField(source="factory.timezone", read_only=True)
    is_overdue = serializers.SerializerMethodField()
    allowed_steps = serializers.SerializerMethodField()
    link_count = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceAction
        fields = [
            "id",
            "factory",
            "line",
            "line_name",
            "machine",
            "machine_name",
            "factory_timezone",
            "title",
            "problem",
            "action_type",
            "priority",
            "status",
            "reporter",
            "assignee",
            "assignee_detail",
            "due_date",
            "is_overdue",
            "started_at",
            "completed_at",
            "fixed_at",
            "verified_by",
            "verified_at",
            "verification_result",
            "verification_note",
            "effectiveness_window_days",
            "min_after_run_hours",
            "created_at",
            "updated_at",
            "allowed_steps",
            "link_count",
            "links",
        ]
        read_only_fields = [
            "factory",
            "line",
            "status",
            "started_at",
            "completed_at",
            "fixed_at",
            "verified_at",
            "verification_result",
            "verification_note",
            "created_at",
            "updated_at",
        ]

    def get_reporter(self, obj: MaintenanceAction) -> dict[str, Any] | None:
        return person(obj.reporter)

    def get_assignee_detail(self, obj: MaintenanceAction) -> dict[str, Any] | None:
        return person(obj.assignee)

    def get_verified_by(self, obj: MaintenanceAction) -> dict[str, Any] | None:
        return person(obj.verified_by)

    def get_is_overdue(self, obj: MaintenanceAction) -> bool:
        return bool(getattr(obj, "is_overdue", False))

    def get_allowed_steps(self, obj: MaintenanceAction) -> list[dict[str, Any]]:
        request = self.context.get("request")
        return allowed_steps(obj, request.user) if request else []

    def get_link_count(self, obj: MaintenanceAction) -> int:
        return getattr(obj, "link_count", None) or obj.links.count()

    def validate_title(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("A title is required.")
        return value.strip()


class TransitionSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=MAX_TEXT)
    assignee = UserField(required=False, allow_null=True)
    fixed_at = serializers.DateTimeField(required=False, allow_null=True)


class VerifySerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=VerificationResult.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=MAX_TEXT)


class PartSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    quantity = serializers.FloatField(min_value=0)


class EntrySerializer(serializers.ModelSerializer):
    parts = PartSerializer(many=True, required=False)
    author = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceEntry
        fields = ["id", "kind", "text", "time_spent_minutes", "parts", "author", "created_at"]
        read_only_fields = ["created_at"]

    def get_author(self, obj: MaintenanceEntry) -> dict[str, Any] | None:
        return person(obj.author)

    def validate_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Write what was found or done.")
        return value.strip()[:MAX_TEXT]


class StatusChangeSerializer(serializers.ModelSerializer):
    changed_by = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceStatusChange
        fields = ["id", "from_status", "to_status", "event", "note", "changed_by", "changed_at"]

    def get_changed_by(self, obj: MaintenanceStatusChange) -> dict[str, Any] | None:
        return person(obj.changed_by)


class DiagnosisInputSerializer(serializers.Serializer):
    reason = serializers.PrimaryKeyRelatedField(queryset=DowntimeReason.objects.all())
    text = serializers.CharField(required=False, allow_blank=True, default="", max_length=MAX_TEXT)
    apply_to_linked_stops = serializers.BooleanField(default=False)
    replace_other_reasons = serializers.BooleanField(default=False)


class DiagnosisSerializer(serializers.ModelSerializer):
    reason = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceDiagnosis
        fields = [
            "id",
            "reason",
            "text",
            "applied_to_stops",
            "replace_other_reasons",
            "applied_count",
            "skipped_count",
            "created_by",
            "created_at",
        ]

    def get_reason(self, obj: MaintenanceDiagnosis) -> dict[str, Any]:
        return {"id": obj.reason_id, "code": obj.reason.code, "name": obj.reason.name}

    def get_created_by(self, obj: MaintenanceDiagnosis) -> dict[str, Any] | None:
        return person(obj.created_by)
