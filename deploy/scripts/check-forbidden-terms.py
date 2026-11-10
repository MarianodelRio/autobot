#!/usr/bin/env python3
"""CI gate: fail if any tracked file contains a real-customer name from
deploy/ci/forbidden-terms.sha256 (docs/plan-lanzamiento.md, block R).

The hash file holds only SHA-256 digests, never the plaintext terms, so a
leaked term cannot be recovered by reading this repo. To check text against
it, every run of 1-4 consecutive words in each tracked file is normalized
the same way and hashed; a match means that exact term is present somewhere
in the repo, and the script prints the offending file (not the term itself,
since the hash does not reveal it) for a human to grep for and remove.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HASHES_FILE = REPO_ROOT / "deploy" / "ci" / "forbidden-terms.sha256"
MAX_WORDS_PER_TERM = 4
# Binary or irrelevant paths that would otherwise slow the scan down or produce
# meaningless matches (lockfiles, generated bundles).
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".svg"}


def load_hashes() -> set[str]:
    hashes: set[str] = set()
    for line in HASHES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            hashes.add(line)
    return hashes


def normalize_words(text: str) -> list[str]:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", without_accents)


def hash_term(term: str) -> str:
    import hashlib

    return hashlib.sha256(term.encode("utf-8")).hexdigest()


def tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [REPO_ROOT / line for line in output.splitlines() if line]


def check_file(path: Path, forbidden_hashes: set[str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return True
    words = normalize_words(text)
    for size in range(1, MAX_WORDS_PER_TERM + 1):
        for start in range(len(words) - size + 1):
            candidate = " ".join(words[start : start + size])
            if hash_term(candidate) in forbidden_hashes:
                print(
                    f"{path.relative_to(REPO_ROOT)}: contains a forbidden term "
                    f"({size}-word match, see deploy/ci/forbidden-terms.sha256)",
                    file=sys.stderr,
                )
                return False
    return True


def main() -> int:
    forbidden_hashes = load_hashes()
    ok = True
    for path in tracked_files():
        if (
            path == HASHES_FILE
            or path.suffix in SKIP_SUFFIXES
            or not path.is_file()
        ):
            continue
        if not check_file(path, forbidden_hashes):
            ok = False
    if not ok:
        print(
            "Forbidden real-customer terms found; see docs/plan-lanzamiento.md (block R).",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
