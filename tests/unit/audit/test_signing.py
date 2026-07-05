"""Unit tests for cemaf.audit.signing and cemaf.audit.models_v2."""

from __future__ import annotations

import base64
import os
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _gen_ed25519_seed() -> bytes:
    """Generate a fresh random 32-byte Ed25519 seed."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    key = Ed25519PrivateKey.generate()
    return key.private_bytes_raw()


def _seed_to_b64(seed: bytes) -> str:
    return base64.b64encode(seed).decode()


@pytest.fixture
def env_key_provider(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Provide a live EnvKeyProvider backed by a freshly generated key."""
    from cemaf.audit.signing import EnvKeyProvider  # noqa: PLC0415

    seed = _gen_ed25519_seed()
    monkeypatch.setenv("CEMAF_SIGNING_KEY_TESTKEY", _seed_to_b64(seed))
    return EnvKeyProvider("testkey")


@pytest.fixture
def sample_entry() -> Any:
    """Return a minimal AuditEntry for testing."""
    from cemaf.audit.models import AuditEntry, AuditEntryType  # noqa: PLC0415

    return AuditEntry.create(
        type=AuditEntryType.NODE_EXECUTED,
        run_id="run_test_001",
        source="test_agent",
        payload={"node": "step_1", "status": "ok"},
        metadata={"env": "test"},
    )


@pytest.fixture
def registry(env_key_provider: Any) -> Any:
    """Return a SigningKeyRegistry with a single provider."""
    from cemaf.audit.signing import SigningKeyRegistry  # noqa: PLC0415

    return SigningKeyRegistry(
        providers={"testkey": env_key_provider},
        current_key_id="testkey",
    )


# ---------------------------------------------------------------------------
# EnvKeyProvider
# ---------------------------------------------------------------------------


def test_env_provider_signs_and_verifies(env_key_provider: Any, sample_entry: Any) -> None:
    from cemaf.audit.signing import _canonical_payload  # noqa: PLC0415

    payload = _canonical_payload(sample_entry)
    sig = env_key_provider.sign(payload)

    assert isinstance(sig, bytes)
    assert len(sig) == 64
    assert env_key_provider.verify(payload, sig) is True


def test_tampered_payload_fails(env_key_provider: Any, sample_entry: Any) -> None:
    from cemaf.audit.signing import _canonical_payload  # noqa: PLC0415

    payload = _canonical_payload(sample_entry)
    sig = env_key_provider.sign(payload)

    tampered = payload[:-1] + bytes([payload[-1] ^ 0xFF])
    assert env_key_provider.verify(tampered, sig) is False


def test_tampered_signature_fails(env_key_provider: Any, sample_entry: Any) -> None:
    from cemaf.audit.signing import _canonical_payload  # noqa: PLC0415

    payload = _canonical_payload(sample_entry)
    sig = env_key_provider.sign(payload)

    bad_sig = bytes([b ^ 0x01 for b in sig])
    assert env_key_provider.verify(payload, bad_sig) is False


def test_env_provider_raises_without_env_var() -> None:
    from cemaf.audit.signing import EnvKeyProvider  # noqa: PLC0415

    env_var = "CEMAF_SIGNING_KEY_NONEXISTENT_XYZ"
    os.environ.pop(env_var, None)  # ensure absent

    with pytest.raises(EnvironmentError, match="CEMAF_SIGNING_KEY_NONEXISTENT_XYZ"):
        EnvKeyProvider("nonexistent_xyz")


# ---------------------------------------------------------------------------
# SigningKeyRegistry
# ---------------------------------------------------------------------------


def test_registry_signs_audit_entry(registry: Any, sample_entry: Any) -> None:
    from cemaf.audit.models_v2 import SignedAuditEntry  # noqa: PLC0415

    signed = registry.sign(sample_entry)

    assert isinstance(signed, SignedAuditEntry)
    assert signed.signature != b""
    assert len(signed.signature) == 64
    assert signed.signer_key_id == "testkey"
    assert signed.id == sample_entry.id


def test_registry_verify_valid_entry(registry: Any, sample_entry: Any) -> None:
    signed = registry.sign(sample_entry)
    assert registry.verify(signed) is True


def test_registry_verify_tampered_fails(registry: Any, sample_entry: Any) -> None:
    from cemaf.audit.models_v2 import SignedAuditEntry  # noqa: PLC0415

    signed = registry.sign(sample_entry)
    # Flip one bit of the signature
    bad_sig = bytes([b ^ 0x01 for b in signed.signature])
    tampered = SignedAuditEntry.from_audit_entry(
        entry=signed.to_audit_entry(),
        signature=bad_sig,
        signer_key_id=signed.signer_key_id,
    )
    assert registry.verify(tampered) is False


def test_registry_verify_unknown_key_id_returns_false(registry: Any, sample_entry: Any) -> None:
    from cemaf.audit.models_v2 import SignedAuditEntry  # noqa: PLC0415

    signed = registry.sign(sample_entry)
    # Replace signer_key_id with an unknown key
    mismatched = SignedAuditEntry.from_audit_entry(
        entry=signed.to_audit_entry(),
        signature=signed.signature,
        signer_key_id="unknown_key_xyz",
    )
    assert registry.verify(mismatched) is False


# ---------------------------------------------------------------------------
# verify_any — key rotation
# ---------------------------------------------------------------------------


def test_verify_any_survives_key_rotation(
    monkeypatch: pytest.MonkeyPatch,
    sample_entry: Any,
) -> None:
    """Old entry signed by key_A can still be verified when key_B is the current key."""
    from cemaf.audit.signing import EnvKeyProvider, SigningKeyRegistry  # noqa: PLC0415

    seed_a = _gen_ed25519_seed()
    seed_b = _gen_ed25519_seed()

    monkeypatch.setenv("CEMAF_SIGNING_KEY_KEY_A", _seed_to_b64(seed_a))
    monkeypatch.setenv("CEMAF_SIGNING_KEY_KEY_B", _seed_to_b64(seed_b))

    provider_a = EnvKeyProvider("key_a")
    provider_b = EnvKeyProvider("key_b")

    # Registry with key_a as current signer
    registry_old = SigningKeyRegistry(
        providers={"key_a": provider_a},
        current_key_id="key_a",
    )
    old_entry = registry_old.sign(sample_entry)

    # After rotation: both keys registered, key_b is now current
    registry_new = SigningKeyRegistry(
        providers={"key_a": provider_a, "key_b": provider_b},
        current_key_id="key_b",
    )

    # verify() uses the signer_key_id from the entry — still works
    assert registry_new.verify(old_entry) is True
    # verify_any() also works
    assert registry_new.verify_any(old_entry) is True


# ---------------------------------------------------------------------------
# Canonical serialization determinism
# ---------------------------------------------------------------------------


def test_canonical_serialization_deterministic(sample_entry: Any) -> None:
    """_canonical_payload must produce identical bytes on repeated calls."""
    from cemaf.audit.signing import _canonical_payload  # noqa: PLC0415

    payload_1 = _canonical_payload(sample_entry)
    payload_2 = _canonical_payload(sample_entry)

    assert payload_1 == payload_2
    assert isinstance(payload_1, bytes)


def test_canonical_serialization_is_valid_json(sample_entry: Any) -> None:
    """The canonical payload must be valid UTF-8 JSON with expected keys."""
    import json  # noqa: PLC0415

    from cemaf.audit.signing import _canonical_payload  # noqa: PLC0415

    payload = _canonical_payload(sample_entry)
    doc = json.loads(payload.decode("utf-8"))

    expected_keys = {"id", "type", "timestamp", "run_id", "source", "correlation_id", "payload", "metadata"}
    assert expected_keys == set(doc.keys())


# ---------------------------------------------------------------------------
# SignedAuditEntry.from_audit_entry round-trip
# ---------------------------------------------------------------------------


def test_signed_audit_entry_roundtrip(registry: Any, sample_entry: Any) -> None:
    signed = registry.sign(sample_entry)
    restored = signed.to_audit_entry()

    assert restored.id == sample_entry.id
    assert restored.type == sample_entry.type
    assert restored.run_id == sample_entry.run_id
    assert restored.payload == sample_entry.payload
