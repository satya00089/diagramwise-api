import pytest
from pydantic import ValidationError

from app.models.auth_models import User, UserAvatarUpdate, UserResponse


def test_avatar_update_accepts_a_curated_key_or_null():
    selected = UserAvatarUpdate(avatarKey="blobatar-v2-01")
    assert selected.avatarKey == "blobatar-v2-01"
    assert UserAvatarUpdate(avatarKey=None).avatarKey is None


def test_avatar_update_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        UserAvatarUpdate(avatarKey="blobatar-v3-unknown")


def test_users_without_an_avatar_key_remain_compatible():
    user = User(
        id="user-1",
        email="person@example.com",
        createdAt="2026-01-01T00:00:00+00:00",
        updatedAt="2026-01-01T00:00:00+00:00",
    )
    response = UserResponse(
        id=user.id,
        email=user.email,
        createdAt=user.createdAt,
    )

    assert user.avatarKey is None
    assert response.avatarKey is None
