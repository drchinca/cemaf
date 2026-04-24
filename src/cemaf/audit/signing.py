"""
Ed25519 cryptographic signing for AuditEntry tamper-evidence.

Uses the stdlib-adjacent ``cryptography`` library (FIPS 186-5 approved).
Private keys never leave the process unless VaultKeyProvider is used.

Key management
--------------
``EnvKeyProvider`` reads a base64-encoded 32-byte Ed25519 seed from the
environment variable ``CEMAF_SIGNING_KEY_{KEY_ID_UPPERCASED}``.  The seed
must be exactly 32 bytes after base64 decoding.

Canonical payload
-----------------
The payload signed for each AuditEntry is a deterministic JSON string
(sort_keys=True, no extra whitespace) of all core fields.  Signature and
signer fields are excluded so the payload is stable across key rotation.
"""

from __future__ import annotations

import base64
import json
import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cemaf.audit.models import AuditEntry
    from cemaf.audit.models_v2 import SignedAuditEntry


# ---------------------------------------------------------------------------
# KeyProvider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class KeyProvider(Protocol):
    """Contract for an Ed25519 key pair that can sign and verify payloads."""

    @property
    def key_id(self) -> str:
        """Stable identifier for this key (used to look up verifiers)."""
        ...

    def sign(self, payload: bytes) -> bytes:
        """Sign *payload* and return the raw 64-byte Ed25519 signature."""
        ...

    def verify(self, payload: bytes, signature: bytes) -> bool:
        """Return True if *signature* is valid for *payload* under this key."""
        ...


# ---------------------------------------------------------------------------
# EnvKeyProvider
# ---------------------------------------------------------------------------


class EnvKeyProvider:
    """
    Loads an Ed25519 key from an environment variable.

    The environment variable must be named
    ``CEMAF_SIGNING_KEY_{key_id.upper()}`` and must contain a base64-encoded
    32-byte Ed25519 seed (standard base64, not URL-safe).

    The ``cryptography`` package is required.  A helpful ``ImportError`` is
    raised at instantiation time if it is not installed.

    Args:
        key_id: A short, stable identifier (e.g. ``"prod_2024"``).
    """

    def __init__(self, key_id: str) -> None:
        self._key_id = key_id
        # Validate cryptography is installed eagerly so callers get a clear error.
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
                Ed25519PrivateKey,
            )
        except ImportError as exc:
            raise ImportError(
                "The 'cryptography' package is required for Ed25519 signing. "
                "Install it with: pip install 'cemaf[security]' or pip install cryptography>=42.0"
            ) from exc

        env_var = f"CEMAF_SIGNING_KEY_{key_id.upper()}"
        raw_b64 = os.environ.get(env_var)
        if not raw_b64:
            raise EnvironmentError(
                f"Environment variable '{env_var}' is not set. "
                "Provide a base64-encoded 32-byte Ed25519 seed."
            )

        try:
            seed = base64.b64decode(raw_b64)
        except Exception as exc:
            raise ValueError(
                f"Environment variable '{env_var}' is not valid base64."
            ) from exc

        if len(seed) != 32:
            raise ValueError(
                f"Ed25519 seed must be exactly 32 bytes; got {len(seed)} bytes "
                f"from '{env_var}'."
            )

        self._private_key = Ed25519PrivateKey.from_private_bytes(seed)
        self._public_key = self._private_key.public_key()

    # ------------------------------------------------------------------
    # KeyProvider implementation
    # ------------------------------------------------------------------

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, payload: bytes) -> bytes:
        """Return the raw 64-byte Ed25519 signature for *payload*."""
        return self._private_key.sign(payload)

    def verify(self, payload: bytes, signature: bytes) -> bool:
        """Return True if *signature* is a valid Ed25519 signature for *payload*."""
        from cryptography.exceptions import InvalidSignature  # noqa: PLC0415

        try:
            self._public_key.verify(signature, payload)
            return True
        except InvalidSignature:
            return False


# ---------------------------------------------------------------------------
# SigningKeyRegistry
# ---------------------------------------------------------------------------


def _canonical_payload(entry: "AuditEntry") -> bytes:
    """
    Produce a deterministic bytes representation of *entry* for signing.

    All core fields are serialised as a JSON object with sorted keys and
    no extra whitespace.  Signature-specific fields (``signature``,
    ``signer_key_id``, ``signature_algorithm``) are excluded so the
    canonical form is stable regardless of which key was used.
    """
    doc = {
        "id": entry.id,
        "type": entry.type if isinstance(entry.type, str) else entry.type.value,
        "timestamp": entry.timestamp.isoformat(),
        "run_id": entry.run_id,
        "source": entry.source,
        "correlation_id": entry.correlation_id,
        "payload": entry.payload,
        "metadata": entry.metadata,
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SigningKeyRegistry:
    """
    Registry of named KeyProviders with a designated current signing key.

    Usage::

        registry = SigningKeyRegistry(
            providers={
                "prod_2024": EnvKeyProvider("prod_2024"),
                "prod_2025": EnvKeyProvider("prod_2025"),
            },
            current_key_id="prod_2025",
        )

        signed = registry.sign(entry)
        assert registry.verify(signed)

    Key rotation:
        Retire old key IDs by keeping them as verifiers but not as the
        current signing key.  ``verify_any()`` tries all registered providers.

    Args:
        providers: Mapping of key_id -> KeyProvider.
        current_key_id: Key ID to use when signing new entries.  Must be
                        present in *providers*.  Defaults to the first key.
    """

    def __init__(
        self,
        providers: dict[str, KeyProvider],
        current_key_id: str | None = None,
    ) -> None:
        if not providers:
            raise ValueError("SigningKeyRegistry requires at least one KeyProvider.")
        self._providers = dict(providers)
        if current_key_id is not None:
            if current_key_id not in self._providers:
                raise KeyError(
                    f"current_key_id='{current_key_id}' not found in providers"
                )
            self._current_key_id = current_key_id
        else:
            self._current_key_id = next(iter(self._providers))

    @property
    def current_key_id(self) -> str:
        """Key ID of the default signing provider."""
        return self._current_key_id

    def sign(self, entry: "AuditEntry") -> "SignedAuditEntry":
        """
        Sign *entry* with the current signing key and return a SignedAuditEntry.

        The canonical payload (see ``_canonical_payload``) is signed.
        """
        from cemaf.audit.models_v2 import SignedAuditEntry  # noqa: PLC0415

        provider = self._providers[self._current_key_id]
        payload = _canonical_payload(entry)
        signature = provider.sign(payload)
        return SignedAuditEntry.from_audit_entry(
            entry=entry,
            signature=signature,
            signer_key_id=self._current_key_id,
        )

    def verify(self, entry: "SignedAuditEntry") -> bool:
        """
        Verify *entry*'s signature using the provider matching its signer_key_id.

        Returns False if the key_id is unknown or the signature is invalid.
        """
        provider = self._providers.get(entry.signer_key_id)
        if provider is None:
            return False
        payload = _canonical_payload(entry.to_audit_entry())
        return provider.verify(payload, entry.signature)

    def verify_any(self, entry: "SignedAuditEntry") -> bool:
        """
        Try every registered provider to verify *entry*.

        Useful during key rotation when entries may have been signed by
        either the old or new key.

        Returns True if any provider can verify the signature.
        """
        payload = _canonical_payload(entry.to_audit_entry())
        return any(
            provider.verify(payload, entry.signature)
            for provider in self._providers.values()
        )
