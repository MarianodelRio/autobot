class TransientError(Exception):
    """A temporary failure (network, timeout, lock not acquired): the job is retried."""
