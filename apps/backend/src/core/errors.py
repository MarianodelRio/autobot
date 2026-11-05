class TransientError(Exception):
    """A temporary failure (network, timeout, lock not acquired): the job is retried."""


class PermanentError(Exception):
    """An external operation cannot succeed by retrying the same request."""
