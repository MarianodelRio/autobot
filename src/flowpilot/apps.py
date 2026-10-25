from django.apps import AppConfig


class FlowpilotConfig(AppConfig):
    name = "flowpilot"

    def ready(self) -> None:
        from flowpilot.ops.logging import initialize_sentry

        initialize_sentry()
