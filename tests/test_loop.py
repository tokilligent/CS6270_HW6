"""Unit tests for consumer.loop.Consumer.

poll_once paths: no request; valid request; invalid request; retrieval error; processing error.
run loop boundaries: zero iterations, exactly one, many; each stop condition; idle timer reset.
A fake clock advances only when the consumer sleeps, so times are exact and tests are instant.
"""
import json
import logging

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from consumer.loop import Consumer, ConsumerStats
from consumer.processor import RequestProcessor
from consumer.sources import RawRequest
from tests.conftest import CREATE_REQUEST
from tests.fakes import FakeClock, FakeSource, FakeStore

POLL = 1.0


def _raw(widget_id):
    return RawRequest(widget_id, json.dumps({**CREATE_REQUEST, "widgetId": widget_id}))


def _consumer(source, store, clock):
    return Consumer(source, RequestProcessor(store), poll_interval=POLL,
                    sleep=clock.sleep, clock=clock)


class ErrorSource(FakeSource):
    """Raises the given error on the first call, then behaves like FakeSource."""

    def __init__(self, error, requests=()):
        super().__init__(requests)
        self.error = error

    def next_request(self):
        if self.error:
            error, self.error = self.error, None
            raise error
        return super().next_request()


class ErrorStore(FakeStore):
    """Raises the given error on the first save, then behaves like FakeStore."""

    def __init__(self, error):
        super().__init__()
        self.error = error

    def save(self, widget):
        if self.error:
            error, self.error = self.error, None
            raise error
        super().save(widget)


AWS_ERRORS = [
    ClientError({"Error": {"Code": "InternalError"}}, "Operation"),
    EndpointConnectionError(endpoint_url="https://example"),  # a BotoCoreError
]


@pytest.fixture
def clock():
    return FakeClock()


# ---- poll_once ----

def test_poll_once_with_no_request(clock):
    store = FakeStore()
    consumer = _consumer(FakeSource(), store, clock)

    got_request = consumer.poll_once()

    assert got_request is False
    assert consumer.stats == ConsumerStats(processed=0, failed=0)
    assert store.widgets == {}
    assert clock.sleeps == []  # poll_once itself never waits


def test_poll_once_processes_exactly_one_request(clock):
    source, store = FakeSource([_raw("a"), _raw("b")]), FakeStore()
    consumer = _consumer(source, store, clock)

    got_request = consumer.poll_once()

    assert got_request is True
    assert consumer.stats == ConsumerStats(processed=1, failed=0)
    assert list(store.widgets) == ["a"]
    assert source.requests == [_raw("b")]


def test_poll_once_with_invalid_request(clock, caplog):
    store = FakeStore()
    consumer = _consumer(FakeSource([RawRequest("bad-key", "{oops")]), store, clock)

    with caplog.at_level(logging.ERROR):
        got_request = consumer.poll_once()

    assert got_request is True
    assert consumer.stats == ConsumerStats(processed=0, failed=1)
    assert store.widgets == {}
    assert len(caplog.records) == 1 and "bad-key" in caplog.records[0].getMessage()


@pytest.mark.parametrize("error", AWS_ERRORS)
def test_poll_once_with_retrieval_error(clock, caplog, error):
    store = FakeStore()
    consumer = _consumer(ErrorSource(error), store, clock)

    with caplog.at_level(logging.ERROR):
        got_request = consumer.poll_once()

    assert got_request is False
    assert consumer.stats == ConsumerStats(processed=0, failed=0)
    assert len(caplog.records) == 1 and "retrieve" in caplog.records[0].getMessage()


@pytest.mark.parametrize("error", AWS_ERRORS)
def test_poll_once_with_processing_error(clock, caplog, error):
    store = ErrorStore(error)
    consumer = _consumer(FakeSource([_raw("a")]), store, clock)

    with caplog.at_level(logging.ERROR):
        got_request = consumer.poll_once()

    assert got_request is True
    assert consumer.stats == ConsumerStats(processed=0, failed=1)
    assert store.widgets == {}
    assert len(caplog.records) == 1 and "a" in caplog.records[0].getMessage()


# ---- run ----

def test_run_zero_iterations_when_max_runtime_is_zero(clock):
    source = FakeSource([_raw("a")])
    store = FakeStore()

    stats = _consumer(source, store, clock).run(max_runtime=0)

    assert stats == ConsumerStats(processed=0, failed=0)
    assert source.requests == [_raw("a")]
    assert clock.sleeps == []


def test_run_one_iteration_with_max_runtime_of_one_poll(clock):
    stats = _consumer(FakeSource(), FakeStore(), clock).run(max_runtime=POLL)

    assert stats == ConsumerStats(processed=0, failed=0)
    assert clock.sleeps == [POLL]


def test_run_processes_all_requests_in_order_without_waiting_between_them(clock):
    source, store = FakeSource([_raw("a"), _raw("b"), _raw("c")]), FakeStore()

    stats = _consumer(source, store, clock).run(max_runtime=2 * POLL)

    assert stats == ConsumerStats(processed=3, failed=0)
    assert list(store.widgets) == ["a", "b", "c"]
    assert source.requests == []
    assert clock.sleeps == [POLL, POLL]  # waits only once the source is empty


def test_run_stops_after_max_idle(clock):
    stats = _consumer(FakeSource(), FakeStore(), clock).run(max_idle=3 * POLL)

    assert stats == ConsumerStats(processed=0, failed=0)
    assert clock.now == 3 * POLL


def test_run_resets_idle_timer_when_request_arrives(clock):
    # Nothing for two polls, then a request, then nothing again.
    class LateSource(FakeSource):
        def next_request(self):
            return _raw("late") if clock.now == 2 * POLL and not store.widgets else None

    store = FakeStore()

    stats = _consumer(LateSource(), store, clock).run(max_idle=3 * POLL)

    assert stats == ConsumerStats(processed=1, failed=0)
    assert list(store.widgets) == ["late"]
    assert clock.now == 5 * POLL  # 2 polls before the request + 3 idle polls after it


def test_run_max_runtime_wins_over_longer_max_idle(clock):
    _consumer(FakeSource(), FakeStore(), clock).run(max_runtime=2 * POLL, max_idle=5 * POLL)

    assert clock.now == 2 * POLL


def test_run_continues_after_errors(clock):
    source = ErrorSource(AWS_ERRORS[0], [RawRequest("bad", "{oops"), _raw("a"), _raw("b")])
    store = ErrorStore(AWS_ERRORS[1])

    stats = _consumer(source, store, clock).run(max_idle=2 * POLL)

    # retrieval error -> wait; "bad" fails to parse; "a" fails to save; "b" succeeds
    assert stats == ConsumerStats(processed=1, failed=2)
    assert list(store.widgets) == ["b"]
    assert source.requests == []
