"""First-layer privacy notice of the demo bot: here the platform, not a business,
answers and is the controller. Sent once per demo contact (`Contact.notice_sent_at`)."""

from django.conf import settings

from core.replies import Text


def demo_first_contact_notice(business_name: str) -> Text:
    url = settings.PLATFORM_PRIVACY_URL
    rights = (
        f"Más información y tus derechos: {url}."
        if url
        else "Para ejercer tus derechos contacta con quien te dio acceso a la demo."
    )
    return Text(
        f"Esto es una demo de Autobot ({business_name}): soy un asistente automático, no una "
        "persona. Uso tus datos solo para enseñarte cómo funciona. "
        f"Responsable: la plataforma Autobot. {rights} "
        "Escribe *PERSONA* para hablar con alguien o *BAJA* para dejar de recibir avisos."
    )
