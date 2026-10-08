"""
Repository data model for CodeLens AI.
"""

from dataclasses import asdict, dataclass
from typing import Dict


@dataclass(frozen=True)
class Repository:
    """Represents a validated GitHub repository ready for analysis."""

    url: str
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        """Return the owner/name format."""
        return f"{self.owner}/{self.name}"

    def to_dict(self) -> Dict[str, str]:
        """Convert repository model to serializable dictionary."""
        return asdict(self)
