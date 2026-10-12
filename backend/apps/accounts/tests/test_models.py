import pytest

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_stores_email_in_lowercase() -> None:
    user = User.objects.create_user(email="Alice@Example.COM", password="secret-pass-1")

    assert user.email == "alice@example.com"
    assert user.check_password("secret-pass-1")
    assert not user.is_staff
    assert not user.is_superuser


def test_create_user_requires_email() -> None:
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="secret-pass-1")


def test_create_superuser_sets_admin_flags() -> None:
    user = User.objects.create_superuser(email="root@example.com", password="secret-pass-1")

    assert user.is_staff
    assert user.is_superuser


def test_user_has_no_username_field() -> None:
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User, "username")
