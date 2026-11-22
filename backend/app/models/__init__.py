"""Import every model module here so `Base.metadata` is complete for Alembic."""

from app.models.auth import User
from app.models.base import AuditMixin, Base

__all__ = ["AuditMixin", "Base", "User"]
