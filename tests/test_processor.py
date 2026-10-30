"""Unit tests for consumer.processor.RequestProcessor.

process() paths: one per request type (create / update / delete), plus a store error on create.
"""
import logging

import pytest
from botocore.exceptions import ClientError

from consumer.models import RequestType, parse_request
from consumer.processor import RequestProcessor
from tests.fakes import FakeStore


def test_create_request_saves_widget(create_request_json, caplog):
    store = FakeStore()
    request = parse_request(create_request_json)

    with caplog.at_level(logging.INFO):
        RequestProcessor(store).process(request)

    assert store.widgets == {request.widget_id: request.to_widget()}
    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert request.request_id in caplog.records[0].getMessage()


@pytest.mark.parametrize("request_type, word", [
    (RequestType.UPDATE, "Update"),
    (RequestType.DELETE, "Delete"),
])
def test_update_and_delete_are_logged_and_skipped(create_request_json, caplog, request_type, word):
    store = FakeStore()
    request = parse_request(create_request_json)
    request.type = request_type

    with caplog.at_level(logging.INFO):
        RequestProcessor(store).process(request)

    assert store.widgets == {}
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert word in warnings[0] and request.request_id in warnings[0]


def test_store_errors_propagate(create_request_json):
    class FailingStore(FakeStore):
        def save(self, widget):
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutItem")

    with pytest.raises(ClientError):
        RequestProcessor(FailingStore()).process(parse_request(create_request_json))
