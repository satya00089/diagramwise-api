import json

from app.services.google_auth_handoff import (
    HANDOFF_PREFIX,
    RedisGoogleAuthHandoffStore,
)


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, ex, nx):
        assert ex == 60
        assert nx is True
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def getdel(self, key):
        return self.values.pop(key, None)


def test_google_auth_handoff_is_single_use_and_does_not_store_plain_code():
    redis = FakeRedis()
    store = RedisGoogleAuthHandoffStore(redis)

    code = store.create({"token": "jwt", "user": {"id": "user-1"}})

    assert code
    assert all(key.startswith(HANDOFF_PREFIX) for key in redis.values)
    assert code not in redis.values
    assert store.consume(code) == {
        "token": "jwt",
        "user": {"id": "user-1"},
    }
    assert store.consume(code) is None


def test_google_auth_handoff_ignores_malformed_payload():
    redis = FakeRedis()
    store = RedisGoogleAuthHandoffStore(redis)
    code = store.create({"token": "jwt"})
    key = next(iter(redis.values))
    redis.values[key] = json.dumps(["not", "a", "mapping"])

    assert store.consume(code) is None
