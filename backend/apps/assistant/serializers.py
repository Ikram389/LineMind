from typing import Any

from rest_framework import serializers

from apps.assistant.models import AnswerFeedback, Conversation, Message, ToolCall
from apps.organizations.models import ProductionLine
from apps.organizations.serializers import ScopedPrimaryKeyRelatedField

MAX_QUESTION_LENGTH = 1000


class ToolCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolCall
        fields = ["order", "name", "arguments", "invalid", "error", "duration_ms"]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    tool_calls = ToolCallSerializer(many=True, read_only=True)
    feedback = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "status",
            "language",
            "resolved_ranges",
            "sources",
            "key_metrics",
            "warnings",
            "number_check",
            "unchecked",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "duration_ms",
            "created_at",
            "tool_calls",
            "feedback",
        ]
        read_only_fields = fields

    def get_feedback(self, obj: Message) -> dict[str, Any] | None:
        try:
            feedback = obj.feedback
        except AnswerFeedback.DoesNotExist:
            return None
        return {"helpful": feedback.helpful, "comment": feedback.comment}


class ConversationSerializer(serializers.ModelSerializer):
    line = ScopedPrimaryKeyRelatedField(
        queryset=ProductionLine.objects.all(),
        factory_path="factory",
        required=False,
        allow_null=True,
    )
    line_name = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "title",
            "line",
            "line_name",
            "context_start",
            "context_end",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "title", "line_name", "created_at", "updated_at"]

    def get_line_name(self, obj: Conversation) -> str | None:
        return obj.line.name if obj.line else None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("context_start"), attrs.get("context_end")
        if (start is None) != (end is None):
            raise serializers.ValidationError(
                "Give both context_start and context_end, or neither."
            )
        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError({"context_end": "Must be after context_start."})
        return attrs


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = [*ConversationSerializer.Meta.fields, "messages"]
        read_only_fields = [*ConversationSerializer.Meta.read_only_fields, "messages"]


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=MAX_QUESTION_LENGTH, trim_whitespace=True)


class FeedbackSerializer(serializers.Serializer):
    helpful = serializers.BooleanField()
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
