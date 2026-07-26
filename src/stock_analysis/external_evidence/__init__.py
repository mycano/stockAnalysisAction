"""Built-in public-web evidence acquisition for investment research."""

from .models import (
    AcquisitionBudget,
    EvidenceQuery,
    ExternalEvidence,
    SearchResult,
    WebDocument,
)
from .plane import ExternalEvidencePlane, build_default_plane

__all__ = [
    "AcquisitionBudget",
    "EvidenceQuery",
    "ExternalEvidence",
    "ExternalEvidencePlane",
    "SearchResult",
    "WebDocument",
    "build_default_plane",
]
