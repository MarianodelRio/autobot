"""Pack health checks Calendar access; template approval is checked by the platform."""

from core.errors import PermanentError, TransientError
from core.pack import HealthIssue, PackContext
from packs.salon.booking import calendar


def check(ctx: PackContext) -> list[HealthIssue]:
    try:
        calendar(ctx).check_access()
    except PermanentError, TransientError:
        return [HealthIssue("calendar_unavailable", "No se puede acceder al calendario.")]
    return []
