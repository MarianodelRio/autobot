"""Common message limits and the send plan (design.md §6.1, §7.4).

Packs build replies that fit **both** channels, so the strictest value of each limit
applies. Exceeding a limit is a programming error: `plan_sends(strict=True)` (tests and
the conversation harness) raises; in production it truncates and logs. Problems that
cannot be fixed by truncating (ids too long, empty or repeated; repeated button titles;
no buttons, rows or rows in a section; several sections without title; empty body) always
raise. Lengths are counted in characters (code points).
"""

import dataclasses
import logging

from core.replies import Button, Buttons, List, Reply, Row, Section, Text

log = logging.getLogger(__name__)

MAX_TEXT = 4096
MAX_INTERACTIVE_BODY = 1024
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10  # in total, across all sections
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72
MAX_SECTION_TITLE = 24
MAX_LIST_BUTTON_LABEL = 20
MAX_HEADER = 60
MAX_FOOTER = 60
MAX_ID_BYTES = 64  # Telegram callback_data

# Separator used when texts are merged together or into an interactive body.
SEPARATOR = "\n\n"


class LimitError(ValueError):
    """A reply that does not fit the common limits."""


def check(reply: Reply) -> tuple[list[str], list[str]]:
    """Return `(fatal, truncatable)` limit violations of a reply, as descriptions
    without content (safe to log)."""
    fatal: list[str] = []
    long: list[str] = []

    def length(what: str, value: str | None, limit: int) -> None:
        if value is not None and len(value) > limit:
            long.append(f"{what} has {len(value)} characters (max {limit})")

    def ids(what: str, values: list[str]) -> None:
        for value in values:
            size = len(value.encode())
            if not value:
                fatal.append(f"{what} id is empty")
            elif size > MAX_ID_BYTES:
                fatal.append(f"{what} id has {size} bytes (max {MAX_ID_BYTES})")
        if len(set(values)) != len(values):
            fatal.append(f"{what} ids are repeated")

    match reply:
        case Text():
            if not reply.body:
                fatal.append("text body is empty")
            length("text body", reply.body, MAX_TEXT)
        case Buttons():
            if not reply.body:
                fatal.append("buttons body is empty")
            if not reply.buttons:
                fatal.append("buttons message has no buttons")
            length("buttons body", reply.body, MAX_INTERACTIVE_BODY)
            length("header", reply.header, MAX_HEADER)
            length("footer", reply.footer, MAX_FOOTER)
            if len(reply.buttons) > MAX_BUTTONS:
                long.append(f"{len(reply.buttons)} buttons (max {MAX_BUTTONS})")
            for b in reply.buttons:
                length("button title", b.title, MAX_BUTTON_TITLE)
            ids("button", [b.id for b in reply.buttons])
            titles = [b.title for b in reply.buttons]
            if len(set(titles)) != len(titles):
                fatal.append("button titles are repeated")
        case List():
            rows = [r for s in reply.sections for r in s.rows]
            if not reply.body:
                fatal.append("list body is empty")
            if not rows:
                fatal.append("list has no rows")
            length("list body", reply.body, MAX_INTERACTIVE_BODY)
            length("list button label", reply.button_label, MAX_LIST_BUTTON_LABEL)
            length("header", reply.header, MAX_HEADER)
            length("footer", reply.footer, MAX_FOOTER)
            if len(rows) > MAX_LIST_ROWS:
                long.append(f"{len(rows)} list rows (max {MAX_LIST_ROWS})")
            if len(reply.sections) > 1 and any(not s.title for s in reply.sections):
                fatal.append("several sections need a title each")
            for s in reply.sections:
                if not s.rows:
                    fatal.append("list section has no rows")
                length("section title", s.title, MAX_SECTION_TITLE)
            for r in rows:
                length("row title", r.title, MAX_ROW_TITLE)
                length("row description", r.description, MAX_ROW_DESCRIPTION)
            ids("row", [r.id for r in rows])
    return fatal, long


def plan_sends(replies: list[Reply], *, strict: bool = False) -> list[Reply]:
    """Turn a pack's replies into the final messages to send, in order (§7.4):
    merge consecutive texts, put a text into the following interactive body when they
    fit together, and enforce the limits."""
    for reply in replies:  # before merging, so a neighbour cannot hide a problem
        fatal, _ = check(reply)
        if fatal:
            raise LimitError("; ".join(fatal))
    planned: list[Reply] = []
    for reply in _merge(replies):
        fatal, long = check(reply)
        if fatal or (long and strict):
            raise LimitError("; ".join(fatal + long))
        if long:
            log.warning("Reply truncated to fit the common limits: %s", "; ".join(long))
            reply = _truncate(reply)
            fatal, _ = check(reply)  # e.g. two titles that become equal when cut
            if fatal:
                raise LimitError("; ".join(fatal))
        planned.append(reply)
    return planned


def _merge(replies: list[Reply]) -> list[Reply]:
    merged: list[Reply] = []
    texts: list[str] = []

    def flush() -> None:
        if texts:
            merged.append(Text(SEPARATOR.join(texts)))
            texts.clear()

    for reply in replies:
        if isinstance(reply, Text):
            if texts and len(SEPARATOR.join([*texts, reply.body])) > MAX_TEXT:
                flush()
            texts.append(reply.body)
            continue
        if texts:
            body = SEPARATOR.join([*texts, reply.body])
            if len(body) <= MAX_INTERACTIVE_BODY:
                reply = dataclasses.replace(reply, body=body)
                texts.clear()
            else:
                flush()
        merged.append(reply)
    flush()
    return merged


def _cut(value: str, limit: int) -> str:
    return value[:limit]


def _cut_optional(value: str | None, limit: int) -> str | None:
    return None if value is None else value[:limit]


def _truncate(reply: Reply) -> Reply:
    match reply:
        case Text():
            return Text(_cut(reply.body, MAX_TEXT))
        case Buttons():
            return Buttons(
                body=_cut(reply.body, MAX_INTERACTIVE_BODY),
                buttons=[
                    Button(b.id, _cut(b.title, MAX_BUTTON_TITLE))
                    for b in reply.buttons[:MAX_BUTTONS]
                ],
                header=_cut_optional(reply.header, MAX_HEADER),
                footer=_cut_optional(reply.footer, MAX_FOOTER),
            )
        case List():
            room = MAX_LIST_ROWS
            sections: list[Section] = []
            for s in reply.sections:
                rows = [
                    Row(
                        r.id,
                        _cut(r.title, MAX_ROW_TITLE),
                        _cut_optional(r.description, MAX_ROW_DESCRIPTION),
                    )
                    for r in s.rows[:room]
                ]
                room -= len(rows)
                if rows:
                    sections.append(Section(_cut_optional(s.title, MAX_SECTION_TITLE), rows))
            return List(
                body=_cut(reply.body, MAX_INTERACTIVE_BODY),
                button_label=_cut(reply.button_label, MAX_LIST_BUTTON_LABEL),
                sections=sections,
                header=_cut_optional(reply.header, MAX_HEADER),
                footer=_cut_optional(reply.footer, MAX_FOOTER),
            )
