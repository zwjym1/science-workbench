"""Public field states; storage and adapters share these string values."""
from dataclasses import asdict, dataclass, field
from enum import Enum


class FieldStatus(str, Enum):
    AVAILABLE = 'available'
    PARTIAL = 'partial'
    OBSERVED_EMPTY = 'observed_empty'
    MISSING = 'missing'
    BLOCKED_LOGIN = 'blocked_login'
    BLOCKED_VERIFICATION = 'blocked_verification'
    ERROR = 'error'
    NOT_REQUESTED = 'not_requested'


@dataclass
class CommentCollection:
    status: str = 'missing'
    items: list[dict] = field(default_factory=list)
    unique_count: int = 0
    platform_total: int | None = None
    has_more: bool | None = None
    pages: list[dict] = field(default_factory=list)
    stop_reason: str | None = None

    def to_dict(self):
        return asdict(self)
