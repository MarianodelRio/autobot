"""Settings for local development tools and tests: `config.settings` with
`ENVIRONMENT=local` unless the environment says otherwise.

`config.settings` itself requires `ENVIRONMENT` to be set explicitly (an unset
variable is treated as `prod`, so a forgotten variable fails closed instead of
enabling DEBUG and the public example encryption key). Local entry points that
cannot count on the variable (pytest, mypy, `make` targets) point
`DJANGO_SETTINGS_MODULE` here.
"""

import os

os.environ.setdefault("ENVIRONMENT", "local")

from config.settings import *  # noqa: E402, F403
