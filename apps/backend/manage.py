#!/usr/bin/env python
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if (
        len(sys.argv) > 2
        and (
            (sys.argv[1] == "tenant_config" and sys.argv[2] == "export")
            or (sys.argv[1] == "dataset_library" and sys.argv[2] == "pull")
        )
        and "-" in sys.argv[3:]
    ):
        os.environ["AUTOBOT_BINARY_STDOUT"] = "1"
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
