"""SignedAuditEntry extends AuditEntry with Ed25519 signature fields."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cemaf.audit.models import AuditEntry, AuditEntryType
from cemaf.core.types import JSON


@dataclass(frozen=True, slots=True)
class SignedAuditEntry:
    """
    An AuditEntry that has been cryptographically signed with Ed25519.

    Fields mirror AuditEntry exactly, with three additional fields:
    ``signature``, ``signer_key_id``, and ``signature_algorithm``.

    The canonical serialization used for signing is defined in
    ``cemaf.audit.signing.SigningKeyRegistry._canonical_payload()``.
    """

    # --- AuditEntry fields (duplicated to preserve slots=True) ---
    id: str
    type: AuditEntryType
    timestamp: datetime
    run_id: str
    source: str
    correlation_id: str | None = None
    payload: JSON = field(default_factory=dict)
    metadata: JSON = field(default_factory=dict)

    # --- Signature fields ---
    signature: bytes = field(default=b"")
    signer_key_id: str = field(default="")
    signature_algorithm: str = field(default="ed25519")

    @classmethod
    def from_audit_entry(
        cls,
        entry: AuditEntry,
        signature: bytes,
        signer_key_id: str,
    ) -> SignedAuditEntry:
        """Construct a SignedAuditEntry from an unsigned AuditEntry + signature."""
        return cls(
            id=entry.id,
            type=entry.type,
            timestamp=entry.timestamp,
            run_id=entry.run_id,
            source=entry.source,
            correlation_id=entry.correlation_id,
            payload=entry.payload,
            metadata=entry.metadata,
            signature=signature,
            signer_key_id=signer_key_id,
        )

    def to_audit_entry(self) -> AuditEntry:
        """Return the underlying AuditEntry (without signature fields)."""
        return AuditEntry(
            id=self.id,
            type=self.type,
            timestamp=self.timestamp,
            run_id=self.run_id,
            source=self.source,
            correlation_id=self.correlation_id,
            payload=self.payload,
            metadata=self.metadata,
        )
