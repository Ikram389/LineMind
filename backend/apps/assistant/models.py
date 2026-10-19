"""The AI production assistant's settings, conversations and their traces.

Answers are AI assessments (docs/PRODUCT.md §12): stored apart from observations, with
the tools that were called, so every answer can be traced back to LineMind's own data.
"""

from django.conf import settings
from django.db import models

from apps.organizations.models import Organization, ProductionLine


class AssistantSettings(models.Model):
    """Per organization. Off by default: with a hosted model, questions and tool results
    leave the site (docs/PRODUCT.md §8)."""

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="assistant_settings"
    )
    enabled = models.BooleanField(default=False)
    daily_question_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Questions per user per day. Empty: the server default."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "assistant settings"

    def __str__(self) -> str:
        return f"Assistant for {self.organization} ({'on' if self.enabled else 'off'})"


class Conversation(models.Model):
    """One user's conversation. Never visible to anyone else."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="assistant_conversations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_conversations"
    )
    # What the user was looking at when they opened it (pre-fills the prompt context).
    line = models.ForeignKey(
        ProductionLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    context_start = models.DateTimeField(null=True, blank=True)
    context_end = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["user", "-updated_at"], name="conversation_user_idx")]

    def __str__(self) -> str:
        return self.title or f"Conversation {self.pk}"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class MessageStatus(models.TextChoices):
    OK = "ok", "Answered"
    BUSY = "busy", "Model busy (rate limited)"
    UNREACHABLE = "unreachable", "Model unreachable"
    TIMEOUT = "timeout", "Timed out"
    TOOL_LIMIT = "tool_limit", "Too many tool calls"
    FAILED = "failed", "Failed"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField()
    status = models.CharField(
        max_length=20, choices=MessageStatus.choices, default=MessageStatus.OK
    )
    language = models.CharField(max_length=5, blank=True)
    # Assistant answers only: what the answer is built on (see services/orchestrator.py).
    resolved_ranges = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    key_metrics = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    number_check = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=200, blank=True)
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="message_conv_idx")]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:60]}"


class ToolCall(models.Model):
    """One tool call made while answering, for "How I got this" and the evaluation."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="tool_calls")
    order = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    arguments = models.JSONField(default=dict, blank=True)
    invalid = models.BooleanField(default=False, help_text="The model sent invalid arguments.")
    error = models.TextField(blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["message_id", "order"]

    def __str__(self) -> str:
        return f"{self.name} ({'invalid' if self.invalid else 'ok'})"


class AnswerFeedback(models.Model):
    """Helpful / not helpful on one answer, by the conversation's owner. Can be changed."""

    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    helpful = models.BooleanField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{'helpful' if self.helpful else 'not helpful'} on message {self.message_id}"
