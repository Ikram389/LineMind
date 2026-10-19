"""Assistant API. Conversations belong to one user: anyone else gets 404.

POST /assistant/conversations/{id}/ask/ answers as server-sent events (text/event-stream),
read by the browser with fetch(): progress steps, text pieces, then the final answer.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from asgiref.sync import sync_to_async
from django.core.handlers.asgi import ASGIRequest
from django.db.models import Prefetch, QuerySet
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from apps.assistant.models import AnswerFeedback, Conversation, Message, MessageRole, ToolCall
from apps.assistant.serializers import (
    AskSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    FeedbackSerializer,
    MessageSerializer,
)
from apps.assistant.services.limits import daily_limit, is_enabled, questions_today
from apps.assistant.services.orchestrator import Event, ask
from apps.assistant.services.status import model_status
from apps.organizations.permissions import HasMembership
from apps.organizations.tenancy import get_membership


def own_conversations(request: Request) -> QuerySet[Conversation]:
    membership = get_membership(request.user)
    assert membership is not None  # HasMembership
    return Conversation.objects.filter(user=request.user, organization=membership.organization)


class StatusView(APIView):
    """GET /api/v1/assistant/status/[?refresh=1]: enabled, model, reachable, tool calling."""

    permission_classes = [IsAuthenticated, HasMembership]

    def get(self, request: Request) -> Response:
        membership = get_membership(request.user)
        assert membership is not None
        organization = membership.organization
        enabled = is_enabled(organization)
        body: dict[str, Any] = {
            "enabled": enabled,
            "daily_limit": daily_limit(organization),
            "questions_today": questions_today(request.user, timezone.now()),
        }
        if enabled:  # don't spend a model request for an organization that can't ask
            body.update(model_status(refresh=request.query_params.get("refresh") == "1"))
        else:
            body.update({"model": None, "reachable": None, "tool_calling": None, "error": ""})
        return Response(body)


class ConversationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, HasMembership]

    def get_queryset(self) -> QuerySet[Conversation]:
        queryset = own_conversations(self.request).select_related("line")
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "messages",
                    queryset=Message.objects.select_related("feedback").prefetch_related(
                        Prefetch("tool_calls", queryset=ToolCall.objects.order_by("order"))
                    ),
                )
            )
        return queryset[:100] if self.action == "list" else queryset

    def get_serializer_class(self) -> type[BaseSerializer]:
        return ConversationDetailSerializer if self.action == "retrieve" else ConversationSerializer

    def perform_create(self, serializer: BaseSerializer) -> None:
        membership = get_membership(self.request.user)
        assert membership is not None
        serializer.save(user=self.request.user, organization=membership.organization)


def sse(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def sse_lines(events: Iterator[Event]) -> Iterator[str]:
    yield ": connected\n\n"
    for name, data in events:
        yield sse(name, data)


async def as_async(lines: Iterator[str]) -> AsyncIterator[str]:
    """Under ASGI, a streaming response must be async: each step of the (blocking) question
    loop runs in Django's sync thread for this request, so database access stays normal."""
    done = object()
    step = sync_to_async(lambda: next(lines, done), thread_sensitive=True)
    try:
        while True:
            item = await step()
            if item is done:
                return
            yield item  # type: ignore[misc]
    finally:
        await sync_to_async(lines.close, thread_sensitive=True)()  # type: ignore[attr-defined]


class AskView(APIView):
    """POST /api/v1/assistant/conversations/{id}/ask/ {"question"} → text/event-stream."""

    permission_classes = [IsAuthenticated, HasMembership]

    def post(self, request: Request, pk: int) -> Response | StreamingHttpResponse:
        conversation = get_object_or_404(own_conversations(request).select_related("line"), pk=pk)
        organization = conversation.organization
        if not is_enabled(organization):
            return Response(
                {
                    "code": "disabled",
                    "detail": "The assistant is turned off for your organization.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        limit = daily_limit(organization)
        if questions_today(request.user, timezone.now()) >= limit:
            return Response(
                {"code": "daily_limit", "limit": limit, "detail": "Daily question limit reached."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        body = AskSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        lines = sse_lines(ask(conversation, body.validated_data["question"], request.user))
        content: Any = as_async(lines) if isinstance(request._request, ASGIRequest) else lines
        response = StreamingHttpResponse(content, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # no proxy buffering
        return response


class FeedbackView(APIView):
    """POST /api/v1/assistant/messages/{id}/feedback/ {"helpful", "comment"?}: own answers only."""

    permission_classes = [IsAuthenticated, HasMembership]

    def post(self, request: Request, pk: int) -> Response:
        answer = get_object_or_404(
            Message.objects.filter(
                conversation__in=own_conversations(request), role=MessageRole.ASSISTANT
            ),
            pk=pk,
        )
        body = FeedbackSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        AnswerFeedback.objects.update_or_create(
            message=answer,
            defaults={"user": request.user, **body.validated_data},
        )
        answer.refresh_from_db()
        return Response(MessageSerializer(answer).data)
