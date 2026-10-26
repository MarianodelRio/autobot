"""Replies a pack returns, common to every channel.

Limits are checked by `core.limits`, not here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Button:
    id: str
    title: str


@dataclass(frozen=True)
class Row:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class Section:
    title: str | None
    rows: list[Row]


@dataclass(frozen=True)
class Text:
    body: str


@dataclass(frozen=True)
class Buttons:
    body: str
    buttons: list[Button]
    header: str | None = None
    footer: str | None = None


@dataclass(frozen=True)
class List:
    body: str
    button_label: str
    sections: list[Section]
    header: str | None = None
    footer: str | None = None


type Reply = Text | Buttons | List
