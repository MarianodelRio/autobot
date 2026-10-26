"""Internal, OTP protected operations. All changes and their audit share owner transactions."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from django import forms
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import models, transaction
from django.db.models import Count, Min
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django_otp.admin import OTPAdminAuthenticationForm, OTPAdminSite  # type: ignore[import-untyped]
from procrastinate import App
from procrastinate.contrib.django.django_connector import DjangoConnector
from procrastinate.contrib.django.models import ProcrastinateEvent, ProcrastinateJob

from flowpilot.channels.demo.doors import door
from flowpilot.runtime.locks import contact_hash
from flowpilot.runtime.models import DEMO_CHANNELS, Channel, InboundEvent, OutboundMessage
from flowpilot.tenancy.models import Tenant
from flowpilot.tenancy.registry import get_registry

OWNER = "owner"


def queue_app() -> App:
    return App(connector=DjangoConnector(alias=OWNER))


def audit(request: HttpRequest, obj: models.Model, message: str) -> None:
    assert request.user.pk is not None
    LogEntry.objects.using(OWNER).create(
        user_id=request.user.pk,
        content_type_id=ContentType.objects.db_manager(OWNER).get_for_model(obj).pk,
        object_id=str(obj.pk),
        object_repr=f"{obj._meta.model_name} {obj.pk}",
        action_flag=CHANGE,
        change_message=message,
    )


class OwnerOTPForm(OTPAdminAuthenticationForm):  # type: ignore[misc]
    def clean_otp(self, user: Any) -> None:
        # django-otp's mixin opens atomic(default), which cannot protect owner row locks.
        if user is None:
            return
        error = None
        with transaction.atomic(using=OWNER):
            try:
                device = self._chosen_device(user)
                token = self.cleaned_data.get("otp_token")
                user.otp_device = None
                try:
                    if self.cleaned_data.get("otp_challenge"):
                        self._handle_challenge(device)
                    elif token:
                        user.otp_device = self._verify_token(user, token, device)
                    else:
                        raise forms.ValidationError(
                            self.otp_error_messages["token_required"], code="token_required"
                        )
                finally:
                    if user.otp_device is None:
                        self._update_form(user)
            except forms.ValidationError as exc:
                error = exc
        if error:
            raise error


class OperationsSite(OTPAdminSite):  # type: ignore[misc]
    login_form = OwnerOTPForm
    site_header = "FlowPilot"
    index_title = "Operación"
    index_template = "admin/flowpilot/index.html"

    def get_urls(self) -> list[Any]:
        return [path("estado/", self.admin_view(self.state), name="state")] + cast(
            list[Any], super().get_urls()
        )

    def each_context(self, request: HttpRequest) -> dict[str, Any]:
        return {**super().each_context(request), "state_url": "/admin/estado/"}

    def state(self, request: HttpRequest) -> HttpResponse:
        now = timezone.now()
        queues = list(
            ProcrastinateJob.objects.using(OWNER)
            .filter(status="todo")
            .values("queue_name")
            .annotate(pending=Count("id"), oldest=Min("scheduled_at"))
        )
        for queue in queues:
            oldest = (
                ProcrastinateEvent.objects.using(OWNER)
                .filter(job__status="todo", job__queue_name=queue["queue_name"], type="deferred")
                .aggregate(at=Min("at"))["at"]
            )
            queue["oldest"] = oldest
            queue["age"] = now - oldest if oldest else None
        rows = []
        for tenant in Tenant.objects.using(OWNER).all():
            loaded = get_registry().by_id.get(tenant.pk)
            local_now = now.astimezone(loaded.info.timezone) if loaded else now
            start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            health = cache.get(f"health:{tenant.pk}")
            if isinstance(health, dict):
                health = {
                    **health,
                    "stale": now.timestamp() - health["checked_at"] >= 86400,
                    "checked_at": datetime.fromtimestamp(health["checked_at"], UTC),
                }
            else:
                health = None
            demo = loaded is not None and loaded.is_demo
            channels = ("demo_tg", "demo_wa") if demo else ("main",)
            for channel in channels:
                outgoing = OutboundMessage.objects.using(OWNER).filter(
                    tenant=tenant, channel=channel, created_at__gte=start
                )
                signal = cache.get(f"runtime:{tenant.pk}:{channel}") or {}
                rows.append(
                    {
                        "tenant": tenant.slug,
                        "channel": channel,
                        "status": tenant.status,
                        "incoming": InboundEvent.objects.using(OWNER)
                        .filter(
                            tenant=tenant, channel=channel, kind="message", received_at__gte=start
                        )
                        .count(),
                        "outgoing": outgoing.count(),
                        "billable": OutboundMessage.objects.using(OWNER)
                        .filter(tenant=tenant, channel=channel, billable=True, sent_at__gte=start)
                        .count(),
                        "last_sweep": signal.get("last_sweep"),
                        "health": health,
                    }
                )
        return TemplateResponse(
            request,
            "admin/flowpilot/state.html",
            {
                **self.each_context(request),
                "title": "Estado",
                "queues": queues,
                "failed_jobs": ProcrastinateJob.objects.using(OWNER).filter(status="failed"),
                "messages": OutboundMessage.objects.using(OWNER).filter(
                    status__in=["unknown", "failed"]
                ),
                "rows": rows,
            },
        )


site = OperationsSite(name="admin")


class OwnerModelAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    using = OWNER

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[Any]:
        return super().get_queryset(request).using(self.using)

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        obj.save(using=self.using)

    def delete_model(self, request: HttpRequest, obj: Any) -> None:
        obj.delete(using=self.using)

    def formfield_for_foreignkey(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        return super().formfield_for_foreignkey(db_field, request, using=self.using, **kwargs)

    def formfield_for_manytomany(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        return super().formfield_for_manytomany(db_field, request, using=self.using, **kwargs)


class ReadOnlyAdmin(OwnerModelAdmin):
    actions: Any = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Tenant, site=site)
class TenantAdmin(ReadOnlyAdmin):
    list_display = ["slug", "status", "pack", "synced_at"]


@admin.register(OutboundMessage, site=site)
class OutboundAdmin(ReadOnlyAdmin):
    list_display = ["id", "tenant", "channel", "status", "unknown_at", "attempts"]
    list_filter = ["status", "channel", "tenant"]
    exclude = ["payload", "idem_key", "provider_message_id", "last_error"]

    @admin.action(description="Marcar enviado", permissions=["change"])
    def mark_sent(self, request: HttpRequest, queryset: models.QuerySet[OutboundMessage]) -> Any:
        return self.resolve(request, queryset, resend=False)

    @admin.action(description="Reenviar", permissions=["change"])
    def resend(self, request: HttpRequest, queryset: models.QuerySet[OutboundMessage]) -> Any:
        return self.resolve(request, queryset, resend=True)

    actions = [mark_sent, resend]

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return request.user.has_perm("flowpilot.change_outboundmessage")

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        return [field.name for field in self.model._meta.fields if field.name not in self.exclude]

    def resolve(
        self, request: HttpRequest, queryset: models.QuerySet[OutboundMessage], *, resend: bool
    ) -> Any:
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        if request.POST.get("confirm") != "yes":
            return TemplateResponse(
                request,
                "admin/flowpilot/confirm.html",
                {
                    **site.each_context(request),
                    "title": "Confirmar resolución",
                    "objects": queryset,
                    "action": "resend" if resend else "mark_sent",
                    "resend": resend,
                },
            )
        for pk in queryset.values_list("pk", flat=True):
            with transaction.atomic(using=OWNER):
                message = OutboundMessage.objects.using(OWNER).select_for_update().get(pk=pk)
                eligible = (
                    message.status == "unknown"
                    and message.unknown_at is not None
                    and message.unknown_at < timezone.now() - timedelta(minutes=10)
                )
                if resend:
                    tenant = get_registry().by_id.get(message.tenant_id)
                    db_tenant = (
                        Tenant.objects.using(OWNER).select_for_update().get(pk=message.tenant_id)
                    )
                    eligible = eligible and (
                        message.payload is not None
                        and tenant is not None
                        and tenant.file.status != "offboarded"
                        and db_tenant.status != "offboarded"
                        and not tenant.ambiguous
                        and (
                            (message.channel == "main" and tenant.main_enabled)
                            or (
                                message.channel in DEMO_CHANNELS
                                and door(Channel(message.channel)) is not None
                            )
                        )
                    )
                if not eligible:
                    self.message_user(
                        request, "Mensaje no elegible para resolver.", level="warning"
                    )
                    continue
                message.status = "pending" if resend else "sent"
                message.unknown_at = None
                if not resend:
                    message.sent_at = message.sent_at or timezone.now()
                message.save(using=OWNER, update_fields=["status", "unknown_at", "sent_at"])
                detail = "Operador confirma enviado."
                if resend:
                    contact = message.contact
                    lock = contact_hash(message.tenant_id, contact.channel, contact.external_id)
                    job = (
                        queue_app()
                        .configure_task(
                            name="send_message",
                            queue="outbound",
                            lock=f"out:{lock}",
                        )
                        .defer(tenant_id=str(message.tenant_id), outbound_id=str(message.pk))
                    )
                    detail = f"Operador autoriza reenvío con riesgo de duplicado; nuevo job {job}."
                audit(request, message, detail)
        return None


class EventInline(admin.TabularInline):  # type: ignore[type-arg]
    model = ProcrastinateEvent
    extra = 0
    can_delete = False

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[ProcrastinateEvent]:
        return super().get_queryset(request).using(OWNER)

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(ProcrastinateJob, site=site)
class JobAdmin(ReadOnlyAdmin):
    list_display = ["id", "task_name", "queue_name", "status", "scheduled_at", "attempts"]
    list_filter = ["status", "queue_name", "task_name"]
    inlines = [EventInline]

    @admin.action(description="Reintentar trabajo fallido", permissions=["change"])
    def retry(self, request: HttpRequest, queryset: models.QuerySet[ProcrastinateJob]) -> None:
        if not self.has_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        for pk in queryset.values_list("pk", flat=True):
            with transaction.atomic(using=OWNER):
                job = ProcrastinateJob.objects.using(OWNER).select_for_update().get(pk=pk)
                if job.status != "failed":
                    continue
                # Delivery failures need deliberate resolution, never a blind retry.
                if job.task_name in ("send_message", "send_notification"):
                    self.message_user(
                        request, "Revise el resultado del envío antes de actuar.", "warning"
                    )
                    continue
                from flowpilot.jobs import app

                if job.task_name not in app.tasks:
                    continue
                queue_app().job_manager.retry_job_by_id(job.pk, timezone.now())
                audit(request, job, "Operador reintenta trabajo fallido idempotente.")

    actions = [retry]

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return request.user.has_perm("procrastinate.change_procrastinatejob")

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> list[str]:
        return [field.name for field in self.model._meta.fields]
