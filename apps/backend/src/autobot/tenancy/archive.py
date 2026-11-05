"""Portable UTF-8 tenant directories and tar streams, without exported secrets."""

import sys
import tarfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import yaml
from django.core.management.base import CommandError

from autobot.tenancy.registry import TenantSource, _dataset_path, source_from_dir
from autobot.tenancy.store import StoreError, current_sources


def current(slug: str) -> TenantSource:
    for source in current_sources():
        if isinstance(source.document, dict) and source.document.get("slug") == slug:
            return source
    raise StoreError("not_found", "No se encuentra el negocio")


@contextmanager
def input_directory(location: str) -> Iterator[Path]:
    if location != "-":
        directory = Path(location)
        if not directory.is_dir():
            raise CommandError("El directorio no existe")
        yield directory
        return
    with TemporaryDirectory(prefix="autobot-import-") as temporary:
        directory = Path(temporary)
        try:
            with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
                archive.extractall(directory, filter="data")
        except tarfile.TarError, OSError, EOFError:
            raise CommandError("No se pudo leer el tar.gz de entrada") from None
        yield directory


def read_secret_file(path: Path, slug: str) -> Mapping[str, str] | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, yaml.YAMLError:
        raise CommandError("No se pudo leer el fichero de secretos") from None
    if not isinstance(raw, dict):
        raise CommandError("El fichero de secretos debe contener un mapa de slugs")
    secrets = raw.get(slug)
    if secrets is not None and not isinstance(secrets, dict):
        raise CommandError("Los secretos del negocio deben ser un mapa")
    return secrets


def read_source(directory: Path, secrets_file: str | None) -> TenantSource:
    source = source_from_dir(directory)
    if source.document_error:
        raise CommandError(source.document_error)
    if not isinstance(source.document, dict) or not isinstance(source.document.get("slug"), str):
        raise CommandError("El documento debe declarar el slug del negocio")
    secret_path = Path(secrets_file) if secrets_file else directory / "secrets.yaml"
    if secrets_file or secret_path.is_file():
        from dataclasses import replace

        source = replace(source, secrets=read_secret_file(secret_path, source.document["slug"]))
    return source


def read_files(directory: Path) -> dict[str, str]:
    files = {}
    try:
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise CommandError("Los datasets no admiten enlaces simbólicos")
            if path.is_file():
                files[path.relative_to(directory).as_posix()] = path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        raise CommandError("Los datasets solo admiten ficheros de texto UTF-8") from None
    return files


def write_files(directory: Path, files: Mapping[str, str]) -> None:
    for name, content in files.items():
        if not _dataset_path(name) or not isinstance(content, str):
            raise CommandError("El dataset contiene una ruta o contenido no válido")
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@contextmanager
def output_directory(location: str) -> Iterator[Path]:
    if location != "-":
        directory = Path(location)
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise CommandError("El directorio de salida debe estar vacío")
        directory.mkdir(parents=True, exist_ok=True)
        yield directory
        return
    with TemporaryDirectory(prefix="autobot-export-") as temporary:
        directory = Path(temporary)
        yield directory
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
            archive.add(directory, arcname=".")


def write_source(directory: Path, source: TenantSource) -> None:
    (directory / "document.yaml").write_text(
        yaml.safe_dump(source.document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for name, files in source.datasets.items():
        if not _dataset_path(name) or len(PurePosixPath(name).parts) != 1:
            raise CommandError("El dataset tiene un nombre no válido")
        write_files(directory / "datasets" / name, files)


def command_error(error: StoreError) -> CommandError:
    return CommandError("; ".join([error.message, *error.details]))
