"""Unit tests for consumer.storage.

owner_key_part: partitions of owner strings (case, number/placement of spaces).
DynamoWidgetStore.to_item paths: optional fields present/absent, attribute value present/None,
attribute name reserved/not reserved.
save(): success path (request sent to AWS) and error path (ClientError propagates).
"""
import json
import logging
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from botocore.stub import ANY

from consumer.models import Widget
from consumer.storage import DynamoWidgetStore, S3WidgetStore, owner_key_part, s3_widget_key

WIDGET = Widget(id="w-1", owner="Mary Matthews", label="CI", description="desc",
                other_attributes={"color": "red", "width-unit": "cm"})


@pytest.mark.parametrize("owner, expected", [
    ("henry", "henry"),                       # already lower case, no spaces
    ("HENRY", "henry"),                       # upper case
    ("Sue Smith", "sue-smith"),               # one space
    ("Mary Ann Matthews", "mary-ann-matthews"),  # several spaces
    ("Mary  Matthews", "mary--matthews"),     # consecutive spaces
    (" Sue ", "-sue-"),                       # leading/trailing spaces
])
def test_owner_key_part(owner, expected):
    assert owner_key_part(owner) == expected


def test_s3_widget_key():
    assert s3_widget_key("Sue Smith", "abc-123") == "widgets/sue-smith/abc-123"


# ---- S3WidgetStore ----

def test_s3_store_puts_object_at_owner_key(s3_stub):
    client, stub = s3_stub
    stub.add_response("put_object", {}, {
        "Bucket": "web", "Key": "widgets/mary-matthews/w-1",
        "Body": ANY, "ContentType": "application/json",
    })

    S3WidgetStore(client, "web").save(WIDGET)

    # Stubber verified the parameters; the fixture verifies the call was made.


def test_s3_store_body_is_widget_json():
    client = Mock()

    S3WidgetStore(client, "web").save(WIDGET)

    client.put_object.assert_called_once()
    assert json.loads(client.put_object.call_args.kwargs["Body"]) == WIDGET.to_dict()


def test_s3_store_propagates_errors(s3_stub):
    client, stub = s3_stub
    stub.add_client_error("put_object", service_error_code="NoSuchBucket", http_status_code=404)

    with pytest.raises(ClientError):
        S3WidgetStore(client, "web").save(WIDGET)


# ---- DynamoWidgetStore ----

def test_dynamo_item_has_one_attribute_per_property():
    item = DynamoWidgetStore.to_item(WIDGET)

    assert item == {
        "id": {"S": "w-1"},
        "owner": {"S": "Mary Matthews"},
        "label": {"S": "CI"},
        "description": {"S": "desc"},
        "color": {"S": "red"},
        "width-unit": {"S": "cm"},
    }


def test_dynamo_item_with_only_required_properties():
    item = DynamoWidgetStore.to_item(Widget(id="w-2", owner="Sue Smith"))

    assert item == {"id": {"S": "w-2"}, "owner": {"S": "Sue Smith"}}


def test_dynamo_item_keeps_empty_strings():
    widget = Widget(id="w-3", owner="Sue Smith", label="", description="",
                    other_attributes={"note": ""})

    item = DynamoWidgetStore.to_item(widget)

    assert item == {"id": {"S": "w-3"}, "owner": {"S": "Sue Smith"}, "label": {"S": ""},
                    "description": {"S": ""}, "note": {"S": ""}}


def test_dynamo_item_omits_attributes_with_no_value():
    widget = Widget(id="w-4", owner="Sue Smith", other_attributes={"note": None, "size": "5"})

    item = DynamoWidgetStore.to_item(widget)

    assert item == {"id": {"S": "w-4"}, "owner": {"S": "Sue Smith"}, "size": {"S": "5"}}


@pytest.mark.parametrize("name", ["id", "owner", "label", "description"])
def test_dynamo_item_skips_attribute_that_clashes_with_core_property(name, caplog):
    widget = Widget(id="w-5", owner="Sue Smith", label="L", description="D",
                    other_attributes={name: "clash"})

    with caplog.at_level(logging.WARNING):
        item = DynamoWidgetStore.to_item(widget)

    assert item == {"id": {"S": "w-5"}, "owner": {"S": "Sue Smith"},
                    "label": {"S": "L"}, "description": {"S": "D"}}
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert f"'{name}'" in caplog.records[0].getMessage()


def test_dynamo_store_puts_item(ddb_stub):
    client, stub = ddb_stub
    stub.add_response("put_item", {},
                      {"TableName": "widgets", "Item": DynamoWidgetStore.to_item(WIDGET)})

    DynamoWidgetStore(client, "widgets").save(WIDGET)

    # Stubber verified the parameters; the fixture verifies the call was made.


def test_dynamo_store_propagates_errors(ddb_stub):
    client, stub = ddb_stub
    stub.add_client_error("put_item", service_error_code="ResourceNotFoundException",
                          http_status_code=400)

    with pytest.raises(ClientError):
        DynamoWidgetStore(client, "widgets").save(WIDGET)
