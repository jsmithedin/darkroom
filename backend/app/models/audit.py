import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    """One successful write made through an MCP tool, with the credential that made it."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    via: Mapped[str] = mapped_column(String)  # "pat" or "oauth"
    # A PAT id or an OAuth token id depending on `via`, so no foreign key.
    token_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    client_id: Mapped[str | None] = mapped_column(String, default=None)
    tool: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
