"""Raw observations cannot be changed: not by code, not through the admin, not by cascades."""

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.production.models import (
    ImmutableObservationError,
    IngestedEvent,
    LineApiKey,
    MachineStateEvent,
    ProductionEvent,
)
from apps.production.tests.events import make_event
from tests.helpers import ApiFactory, World

RAW_MODELS = [IngestedEvent, MachineStateEvent, ProductionEvent]


@pytest.fixture
def stored(world: World, sender: APIClient) -> None:
    sender.post("/api/v1/events/", make_event("machine_stopped"), format="json")
    sender.post("/api/v1/events/", make_event("production_count_updated", count=5), format="json")


@pytest.fixture
def admin_client(db: None) -> Client:
    user = User.objects.create_superuser(email="root@example.com", password="x-strong-pass-1")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.parametrize("model", RAW_MODELS)
def test_saving_existing_observation_raises(stored: None, model: type) -> None:
    obj = model.objects.first()
    obj.received_at = obj.timestamp

    with pytest.raises(ImmutableObservationError):
        obj.save()


@pytest.mark.parametrize("model", RAW_MODELS)
def test_deleting_observation_raises(stored: None, model: type) -> None:
    with pytest.raises(ImmutableObservationError):
        model.objects.first().delete()


def test_machine_with_events_cannot_be_deleted(world: World, api: ApiFactory, stored: None) -> None:
    response = api(world.users["factory_manager"]).delete(f"/api/v1/machines/{world.machine_a.id}/")

    assert response.status_code == 409
    assert MachineStateEvent.objects.exists()


@pytest.mark.parametrize("model", RAW_MODELS)
def test_admin_can_view_but_not_change_observations(
    stored: None, admin_client: Client, model: type
) -> None:
    obj = model.objects.first()
    opts = model._meta
    change_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
    changelist_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
    add_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
    delete_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_delete", args=[obj.pk])

    assert admin_client.get(changelist_url).status_code == 200
    assert admin_client.get(change_url).status_code == 200  # read-only view
    assert admin_client.post(change_url, {}).status_code == 403
    assert admin_client.get(add_url).status_code == 403
    assert admin_client.post(delete_url, {"post": "yes"}).status_code == 403
    assert model.objects.filter(pk=obj.pk).exists()


def test_admin_hides_key_hash_and_can_revoke(
    world: World, line_a_key: str, admin_client: Client
) -> None:
    api_key = LineApiKey.objects.get()
    changelist_url = reverse("admin:production_lineapikey_changelist")
    change_url = reverse("admin:production_lineapikey_change", args=[api_key.pk])

    page = admin_client.get(change_url).content.decode()
    assert api_key.key_hash not in page
    assert line_a_key not in page

    admin_client.post(changelist_url, {"action": "revoke_keys", "_selected_action": [api_key.pk]})
    api_key.refresh_from_db()
    assert api_key.revoked_at is not None
