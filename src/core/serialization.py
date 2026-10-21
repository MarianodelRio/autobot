"""JSON (de)serialization of replies and proactive messages for `outbound_message.payload`
(design.md §12.1): the common form is stored, and the adapter renders it when sending."""

from typing import Any

from core.proactive import ProactiveMessage, TemplateSpec
from core.replies import Button, Buttons, List, Reply, Row, Section, Text

type Outbound = Reply | ProactiveMessage


def dump_outbound(out: Outbound) -> dict[str, Any]:
    match out:
        case Text():
            return {"type": "text", "body": out.body}
        case Buttons():
            return {
                "type": "buttons",
                "body": out.body,
                "buttons": [{"id": b.id, "title": b.title} for b in out.buttons],
                "header": out.header,
                "footer": out.footer,
            }
        case List():
            return {
                "type": "list",
                "body": out.body,
                "button_label": out.button_label,
                "sections": [
                    {
                        "title": s.title,
                        "rows": [
                            {"id": r.id, "title": r.title, "description": r.description}
                            for r in s.rows
                        ],
                    }
                    for s in out.sections
                ],
                "header": out.header,
                "footer": out.footer,
            }
        case ProactiveMessage():
            t = out.template
            return {
                "type": "proactive",
                "template": {
                    "name": t.name,
                    "language": t.language,
                    "text": t.text,
                    "buttons": t.buttons,
                },
                "params": out.params,
                "button_payloads": out.button_payloads,
            }


def load_outbound(data: dict[str, Any]) -> Outbound:
    match data["type"]:
        case "text":
            return Text(body=data["body"])
        case "buttons":
            return Buttons(
                body=data["body"],
                buttons=[Button(id=b["id"], title=b["title"]) for b in data["buttons"]],
                header=data["header"],
                footer=data["footer"],
            )
        case "list":
            return List(
                body=data["body"],
                button_label=data["button_label"],
                sections=[
                    Section(
                        title=s["title"],
                        rows=[
                            Row(id=r["id"], title=r["title"], description=r["description"])
                            for r in s["rows"]
                        ],
                    )
                    for s in data["sections"]
                ],
                header=data["header"],
                footer=data["footer"],
            )
        case "proactive":
            t = data["template"]
            return ProactiveMessage(
                template=TemplateSpec(
                    name=t["name"], language=t["language"], text=t["text"], buttons=t["buttons"]
                ),
                params=data["params"],
                button_payloads=data["button_payloads"],
            )
        case other:
            raise ValueError(f"Unknown outbound payload type: {other!r}")
