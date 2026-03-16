"""CEMAF web UI — architecture advisor powered by CEMAF's own agent stack."""

from cemaf.web.app import app
from cemaf.web.architect import ArchitectAgent

__all__ = [
    "ArchitectAgent",
    "app",
]
