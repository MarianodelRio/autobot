"""Reply builders that respect the common limits. Ported from the
`interactive.py` helpers of both bots, building `core.replies` instead of WhatsApp
payloads. Titles are truncated as in the source; anything else out of limits is a
programming error and raises `LimitError`."""

from collections.abc import Sequence

from core.limits import (
    MAX_BUTTON_TITLE,
    MAX_LIST_BUTTON_LABEL,
    MAX_ROW_DESCRIPTION,
    MAX_ROW_TITLE,
    LimitError,
    check,
)
from core.replies import Button, Buttons, List, Reply, Row, Section

PER_PAGE = 8  # 8 rows + "more" + "back" = 10, the list limit


def trunc(text: str, max_len: int) -> str:
    return text[:max_len]


def button(id: str, title: str) -> Button:
    return Button(id, trunc(title, MAX_BUTTON_TITLE))


def row(id: str, title: str, description: str | None = None) -> Row:
    return Row(
        id,
        trunc(title, MAX_ROW_TITLE),
        trunc(description, MAX_ROW_DESCRIPTION) if description else None,
    )


def section(title: str | None, rows: list[Row]) -> Section:
    return Section(title, rows)


def buttons_msg(
    body: str, buttons: list[Button], header: str | None = None, footer: str | None = None
) -> Buttons:
    return _checked(Buttons(body, buttons, header, footer))


def list_msg(
    body: str,
    button_label: str,
    sections: list[Section],
    header: str | None = None,
    footer: str | None = None,
) -> List:
    label = trunc(button_label, MAX_LIST_BUTTON_LABEL)
    return _checked(List(body, label, sections, header, footer))


def paginate(
    items: Sequence[Row],
    page: int,
    per_page: int = PER_PAGE,
    *,
    more_id: str,
    back_id: str,
    more_title: str = "➡️ Ver más",
    back_title: str = "↩️ Volver",
) -> list[Row]:
    """Rows of `page` (0-based; out of range = first page), followed by a "more" row
    with `more_id` if there are later pages and always a "back" row with `back_id`.
    The caller encodes the next page in `more_id` (e.g. `lines:3`)."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    pages = max(1, -(-len(items) // per_page))
    if not 0 <= page < pages:
        page = 0
    start = page * per_page
    rows = list(items[start : start + per_page])
    if page + 1 < pages:
        rows.append(row(more_id, more_title))
    rows.append(row(back_id, back_title))
    return rows


def _checked[R: Reply](reply: R) -> R:
    fatal, long = check(reply)
    if fatal or long:
        raise LimitError("; ".join(fatal + long))
    return reply
