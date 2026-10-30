"""In-memory test doubles for the Consumer's collaborators."""
from consumer.sources import RequestSource
from consumer.storage import WidgetStore


class FakeSource(RequestSource):
    def __init__(self, requests=()):
        self.requests = list(requests)

    def next_request(self):
        return self.requests.pop(0) if self.requests else None


class FakeStore(WidgetStore):
    def __init__(self):
        self.widgets = {}

    def save(self, widget):
        self.widgets[widget.id] = widget


class FakeClock:
    """A clock that advances only when sleep() is called."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
