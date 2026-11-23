import uuid

from sqlalchemy import Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditMixin, Base


class ImportLedger(AuditMixin, Base):
    """One row per sheet row already imported, so a second run inserts nothing.

    The key is (tab, fingerprint, occurrence): identical rows in a tab share a fingerprint and
    are told apart by occurrence (1, 2, ...), so several rolls on the same day are all kept.
    """

    __tablename__ = "import_ledger"
    __table_args__ = (UniqueConstraint("tab", "fingerprint", "occurrence"),)

    tab: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String)
    occurrence: Mapped[int] = mapped_column(Integer)
    record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
