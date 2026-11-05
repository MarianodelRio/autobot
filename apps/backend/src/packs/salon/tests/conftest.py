import pytest

from core.testing.harness import ChannelType, Conversation
from packs.salon.pack import pack
from packs.salon.testing import FakeCalendar
from packs.salon.tests.test_config import configuration


@pytest.fixture(params=["whatsapp", "telegram"])
def salon(request: pytest.FixtureRequest) -> Conversation:
    channel: ChannelType = request.param
    return Conversation(
        pack,
        config=configuration(),
        channel=channel,
        calendar=FakeCalendar(),
        now="2026-03-24T09:00:00+01:00",
    )
