"""Manages the panel's single operator role (DESIGN §6.2): a `User` with `is_staff` and
a confirmed `TOTPDevice`. Run on the server with `make prod-manage TTY=1
CMD="panel_user create <usuario>"`."""

import getpass
import sys
from typing import Any

import qrcode  # type: ignore[import-untyped]
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django_otp.plugins.otp_totp.models import TOTPDevice  # type: ignore[import-untyped]

User = get_user_model()
DEVICE_NAME = "default"


def read_new_password() -> str:
    while True:
        password = getpass.getpass("Contraseña: ")
        again = getpass.getpass("Repita la contraseña: ")
        if password != again:
            print("Las contraseñas no coinciden.", file=sys.stderr)
            continue
        try:
            validate_password(password)
        except ValidationError as error:
            print("\n".join(error.messages), file=sys.stderr)
            continue
        return password


def get_user(username: str) -> AbstractUser:
    user = User.objects.using("owner").filter(username=username).first()
    if user is None:
        raise CommandError("No existe ese usuario.")
    return user


class Command(BaseCommand):
    help = "Gestiona el usuario único del panel: alta, TOTP y contraseña."

    def add_arguments(self, parser: CommandParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True)
        for name in ("create", "reset-totp", "set-password", "exists"):
            actions.add_parser(name).add_argument("username")

    def handle(self, *args: Any, **options: Any) -> None:
        username = options["username"]
        match options["action"]:
            case "create":
                self._create(username)
            case "reset-totp":
                self._reset_totp(username)
            case "set-password":
                self._set_password(username)
            case "exists":
                if not User.objects.using("owner").filter(username=username).exists():
                    raise CommandError("No existe ese usuario.")

    def _show_device_once(self, device: TOTPDevice) -> None:
        self.stdout.write(
            self.style.WARNING(
                "Guarde esta clave ahora: no se volverá a mostrar. "
                "Escanéela con una app de autenticación (Google Authenticator, Authy...)."
            )
        )
        self.stdout.write(device.config_url)
        code = qrcode.QRCode()
        code.add_data(device.config_url)
        # Raw sys.stdout: OutputWrapper.write() would add a newline after every
        # cell, since print_ascii writes one ASCII code at a time.
        code.print_ascii(out=sys.stdout)

    def _create(self, username: str) -> None:
        if User.objects.using("owner").filter(username=username).exists():
            raise CommandError("Ya existe ese usuario.")
        password = read_new_password()
        user = User.objects.db_manager("owner").create_user(
            username=username, password=password, is_staff=True
        )
        device = TOTPDevice.objects.using("owner").create(
            user=user, name=DEVICE_NAME, confirmed=True
        )
        self._show_device_once(device)

    def _reset_totp(self, username: str) -> None:
        user = get_user(username)
        TOTPDevice.objects.using("owner").filter(user=user).delete()
        device = TOTPDevice.objects.using("owner").create(
            user=user, name=DEVICE_NAME, confirmed=True
        )
        self._show_device_once(device)

    def _set_password(self, username: str) -> None:
        user = get_user(username)
        user.set_password(read_new_password())
        user.save(using="owner", update_fields=["password"])
