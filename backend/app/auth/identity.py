import uuid
from dataclasses import dataclass, field
from typing import Literal

READ = "films:read"
WRITE = "films:write"
ALL_SCOPES = frozenset({READ, WRITE})


@dataclass(frozen=True)
class Principal:
    """Who is calling and what they may do, whatever the credential."""

    user_id: uuid.UUID
    scopes: frozenset[str]
    via: Literal["session", "pat", "oauth"]
    token_id: uuid.UUID | None = None
    client_id: str | None = None
    csrf_token: str | None = field(default=None, repr=False)

    def has(self, scope: str) -> bool:
        """`films:write` implies `films:read`."""
        if scope in self.scopes:
            return True
        return scope == READ and WRITE in self.scopes
