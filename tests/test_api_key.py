import uuid

from email_triage.auth.api_key import (
    hash_secret,
    issue_api_key,
    parse_api_key,
    secret_matches,
)


def test_issue_parse_verify_round_trip() -> None:
    tenant_id = uuid.uuid4()
    plaintext, stored_hash = issue_api_key(tenant_id)

    assert plaintext.startswith(f"et_{tenant_id}_")
    parsed = parse_api_key(plaintext)
    assert parsed is not None
    parsed_tenant, secret = parsed
    assert parsed_tenant == tenant_id
    assert secret_matches(secret, stored_hash)


def test_stored_hash_is_sha256_of_secret_only() -> None:
    tenant_id = uuid.uuid4()
    plaintext, stored_hash = issue_api_key(tenant_id)
    parsed = parse_api_key(plaintext)
    assert parsed is not None
    _, secret = parsed
    assert stored_hash == hash_secret(secret)
    # Plaintext key is never the thing we store.
    assert plaintext != stored_hash


def test_parse_rejects_malformed_keys() -> None:
    assert parse_api_key("") is None
    assert parse_api_key("nope") is None
    assert parse_api_key("et_not-a-uuid_secret") is None
    assert parse_api_key(f"xx_{uuid.uuid4()}_secret") is None  # wrong prefix


def test_secret_matches_rejects_wrong_secret() -> None:
    _, stored_hash = issue_api_key(uuid.uuid4())
    assert not secret_matches("some-other-secret", stored_hash)
