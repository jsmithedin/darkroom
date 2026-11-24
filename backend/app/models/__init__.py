"""Import every model module here so `Base.metadata` is complete for Alembic."""

from app.models.audit import AuditEvent
from app.models.auth import (
    OAuthClient,
    OAuthCode,
    OAuthToken,
    PersonalAccessToken,
    User,
    UserSession,
)
from app.models.base import AuditMixin, Base
from app.models.devtimes import DevTimeRef
from app.models.imports import ImportLedger
from app.models.reference import (
    AppSettings,
    Camera,
    Developer,
    Film,
    Filter,
    Format,
    Lens,
    RefKind,
)
from app.models.rolls import Roll
from app.models.stock import BulkRoll, StockMovement

__all__ = [
    "AuditEvent",
    "AppSettings",
    "AuditMixin",
    "Base",
    "BulkRoll",
    "Camera",
    "DevTimeRef",
    "Developer",
    "Film",
    "Filter",
    "Format",
    "ImportLedger",
    "Lens",
    "OAuthClient",
    "OAuthCode",
    "OAuthToken",
    "PersonalAccessToken",
    "RefKind",
    "Roll",
    "StockMovement",
    "User",
    "UserSession",
]
