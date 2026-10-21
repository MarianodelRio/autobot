"""Conversation test harness (design.md §17.2): runs a pack with the same conversation
rules as the runtime (global commands, expiry and version, `plan_sends`), without a
database or network, simulating either channel type."""

from core.testing.clock import FixedClock
from core.testing.harness import Conversation, Turn, sample_tenant

__all__ = ["Conversation", "FixedClock", "Turn", "sample_tenant"]
