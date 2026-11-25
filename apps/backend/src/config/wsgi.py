import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# Load the tenant registry in the background while the worker boots, so the first
# request does not wait for it (management commands stay lazy: they never import this).
from autobot.tenancy.registry import warm_up_in_background  # noqa: E402

warm_up_in_background(poll=True)
