"""`GET packs`, `.../schema` and `.../template`."""

from django.http import HttpRequest
from ninja import Router

from autobot.panel.services import forms
from autobot.panel.services.forms import PackOut, PackSchemaOut, PackTemplateOut

router = Router(tags=["packs"])


@router.get("/packs", response=list[PackOut])
def packs(request: HttpRequest) -> list[forms.PackSummary]:
    return forms.list_packs()


@router.get("/packs/{pack}/schema", response=PackSchemaOut)
def pack_schema(request: HttpRequest, pack: str) -> PackSchemaOut:
    return PackSchemaOut(document=forms.document_schema(pack), ui_schema=forms.ui_schema(pack))


@router.get("/packs/{pack}/template", response=PackTemplateOut)
def pack_template(request: HttpRequest, pack: str) -> PackTemplateOut:
    return PackTemplateOut(config=forms.pack_template(pack))
