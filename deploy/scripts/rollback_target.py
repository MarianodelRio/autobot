"""Compute the SHA `make rollback` should redeploy (A7).

Reads `deploys.jsonl` lines from stdin and prints the SHA to roll back to, or exits
1 with a message on stderr. Refuses to chain a second rollback onto the broken SHA
the first one moved away from: deploy.sh tags a deploy that exactly undoes the
previous entry's target as `"via": "rollback"`, and the last deployed entry having
that tag means the currently running image is already a rollback target, so its
own `previous` is the broken image, not something to go back to again.
"""

import json
import sys


def rollback_target(lines: list[str]) -> tuple[str | None, str | None]:
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    deployed = [e for e in entries if e.get("result") == "deployed"]
    if not deployed:
        return None, "No previous successful deployment found to roll back to"
    last = deployed[-1]
    if last.get("via") == "rollback":
        return None, (
            "The running deployment is itself a rollback; "
            "use `make deploy SHA=<sha>` to go further back"
        )
    previous = last.get("previous") or None
    if not previous:
        return None, "No previous successful deployment found to roll back to"
    return previous, None


def main() -> int:
    target, error = rollback_target(sys.stdin.readlines())
    if error:
        print(error, file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
