"""Download or publish timetable versions through the local or SSH operator CLI."""

import argparse
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from packs.bus.formato import validar
from tools.bus.tenant import REPO_ROOT, TenantDesconocido, dataset_dir, dataset_path, published_dir


def _command(action: str, slug: str, production: bool, comment: str) -> list[str]:
    arguments = ["tenant_dataset", action, slug, "timetable", "-"]
    if action == "import":
        arguments += ["--comment", comment]
    if production:
        host = os.environ.get("HOST", "autobot")
        return [
            "ssh",
            f"deploy@{host}",
            shlex.join(["/srv/autobot/deploy/scripts/manage.sh", *arguments]),
        ]
    return [sys.executable, str(REPO_ROOT / "apps" / "backend" / "manage.py"), *arguments]


def _replace(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".bus-copy-", dir=target.parent) as staging:
        prepared = Path(staging) / "new"
        shutil.copytree(source, prepared, symlinks=True)
        backup = Path(staging) / "old"
        if target.exists():
            target.rename(backup)
        try:
            prepared.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise


def _check_files(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("El dataset no admite enlaces simbólicos")
        if path.is_file():
            path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Baja o publica horarios versionados en BD.")
    parser.add_argument("action", choices=["download", "publish"])
    parser.add_argument("--tenant", default=os.environ.get("TENANT", ""))
    parser.add_argument("--comment", default=os.environ.get("COMMENT", ""))
    parser.add_argument("--prod", action="store_true", default=os.environ.get("PROD") == "1")
    args = parser.parse_args(argv)
    try:
        working = repo_root / dataset_path(args.tenant)
        published = published_dir(args.tenant, repo_root)
        if args.action == "download":
            result = subprocess.run(
                _command("export", args.tenant, args.prod, ""),
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            )
            if result.returncode:
                sys.stderr.write(result.stderr.decode(errors="replace"))
                return 1
            with TemporaryDirectory(prefix="autobot-bus-download-") as temporary:
                extracted = Path(temporary)
                with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:gz") as archive:
                    archive.extractall(extracted, filter="data")
                _check_files(extracted)
                _replace(extracted, working)
                _replace(extracted, published)
            print(f"Descargado: {working}; base: {published}")
        else:
            if not args.comment.strip():
                raise ValueError("COMMENT es obligatorio para publicar")
            current = dataset_dir(args.tenant, repo_root)
            with TemporaryDirectory(prefix="autobot-bus-publish-") as temporary:
                snapshot = Path(temporary) / "timetable"
                shutil.copytree(current, snapshot, symlinks=True)
                _check_files(snapshot)
                result_validation = validar(snapshot)
                if result_validation.errores:
                    raise ValueError("El dataset no valida; ejecuta make bus-validar")
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                    archive.add(snapshot, arcname=".")
                result = subprocess.run(
                    _command("import", args.tenant, args.prod, args.comment),
                    cwd=REPO_ROOT,
                    input=stream.getvalue(),
                    capture_output=True,
                    check=False,
                )
                if result.returncode:
                    sys.stderr.write(result.stderr.decode(errors="replace"))
                    return 1
                _replace(snapshot, published)
                sys.stdout.write(result.stdout.decode(errors="replace"))
            print(f"Base publicada actualizada: {published}")
    except (TenantDesconocido, ValueError, OSError, UnicodeError, tarfile.TarError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
