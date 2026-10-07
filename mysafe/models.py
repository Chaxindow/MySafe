"""Domain models: Category, Entry and Field."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FieldKind(StrEnum):
    """What kind of value a field holds. Controls masking, copying and icons."""

    TEXT = "text"
    EMAIL = "email"
    USERNAME = "username"
    PASSWORD = "password"  # noqa: S105 - this is a kind name, not a password
    URL = "url"
    NOTE = "note"
    RECOVERY_CODE = "recovery_code"
    SECURITY_QUESTION = "security_question"

    @property
    def is_secret_by_default(self) -> bool:
        return self in SECRET_KINDS

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES[self]


SECRET_KINDS: frozenset[FieldKind] = frozenset(
    {FieldKind.PASSWORD, FieldKind.RECOVERY_CODE, FieldKind.SECURITY_QUESTION}
)

_DISPLAY_NAMES: dict[FieldKind, str] = {
    FieldKind.TEXT: "Text",
    FieldKind.EMAIL: "Email",
    FieldKind.USERNAME: "Username",
    FieldKind.PASSWORD: "Password",
    FieldKind.URL: "URL",
    FieldKind.NOTE: "Note",
    FieldKind.RECOVERY_CODE: "Recovery code",
    FieldKind.SECURITY_QUESTION: "Security question",
}

DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Games", "gamepad"),
    ("Streaming", "tv"),
    ("Email", "mail"),
    ("Social Media", "users"),
    ("Shopping", "cart"),
    ("Other", "folder"),
)


@dataclass(slots=True)
class Category:
    id: str
    name: str
    icon: str | None
    sort_order: int
    created_at: int
    updated_at: int


@dataclass(slots=True)
class FieldInput:
    """A field as typed by the user, before it is saved."""

    label: str
    value: str
    kind: FieldKind = FieldKind.TEXT
    is_secret: bool | None = None  # None -> use the kind's default

    def resolved_secret(self) -> bool:
        return self.kind.is_secret_by_default if self.is_secret is None else self.is_secret


@dataclass(slots=True)
class Field:
    id: str
    entry_id: str
    label: str
    value: str = field(repr=False)  # never show values in logs / reprs
    kind: FieldKind
    is_secret: bool
    sort_order: int


@dataclass(slots=True)
class Entry:
    id: str
    category_id: str
    title: str
    url: str | None
    notes: str | None = field(repr=False)
    favorite: bool
    created_at: int
    updated_at: int
    fields: list[Field] = field(default_factory=list, repr=False)


@dataclass(slots=True, frozen=True)
class DeletedItem:
    """Record of a deletion, kept so Sync can apply it to the other vault."""

    id: str
    kind: str  # "entry" | "category"
    title: str
    deleted_at: int


def default_fields() -> list[FieldInput]:
    """Fields a brand-new entry starts with."""
    return [
        FieldInput(label="Email", value="", kind=FieldKind.EMAIL),
        FieldInput(label="Password", value="", kind=FieldKind.PASSWORD),
    ]
