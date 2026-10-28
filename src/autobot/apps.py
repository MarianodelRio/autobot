from django.apps import AppConfig


class AutobotConfig(AppConfig):
    name = "autobot"

    def ready(self) -> None:
        from autobot.ops.logging import initialize_sentry

        initialize_sentry()
