"""First-layer privacy notice of the demo bot: here the platform, not a business,
answers and is the controller. The last line of the pack's menu every time it is shown,
and of a demo contact's first reply (`core.conversation.with_notice`)."""

from django.conf import settings


def demo_first_contact_notice() -> str:
    url = settings.PLATFORM_PRIVACY_URL
    if url:
        return f"_🤖 Demo de Autobot · Privacidad:_ {url}"
    return "_🤖 Demo de Autobot_"  # the platform, named already, is the controller
