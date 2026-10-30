"""Unit tests for consumer.models.

parse_request paths: malformed JSON -> error, schema violation -> error, valid -> WidgetRequest.
Input partitions are tested per request field (valid / invalid / missing / null / wrong type).
"""
import json

import pytest

from consumer.models import Attribute, InvalidRequestError, RequestType, Widget, WidgetRequest, parse_request
from tests.conftest import CREATE_REQUEST


def _parse(**overrides):
    return parse_request(json.dumps({**CREATE_REQUEST, **overrides}))


def _parse_without(field):
    return parse_request(json.dumps({k: v for k, v in CREATE_REQUEST.items() if k != field}))


# ---- parse_request: valid path ----

def test_parse_full_create_request(create_request_json):
    request = parse_request(create_request_json)

    assert request == WidgetRequest(
        type=RequestType.CREATE,
        request_id=CREATE_REQUEST["requestId"],
        widget_id=CREATE_REQUEST["widgetId"],
        owner="Sue Smith",
        label="IUGSPN",
        description="ETHOQJFDFK",
        other_attributes=[Attribute("size", "586"), Attribute("size-unit", "cm")],
    )


def test_parse_minimal_request_defaults_optional_fields():
    text = '{"type":"delete","requestId":"r","widgetId":"w","owner":"Sue Smith"}'

    request = parse_request(text)

    assert request == WidgetRequest(type=RequestType.DELETE, request_id="r", widget_id="w",
                                    owner="Sue Smith", label=None, description=None,
                                    other_attributes=[])


# ---- type ----

@pytest.mark.parametrize("value, expected", [
    ("create", RequestType.CREATE),
    ("update", RequestType.UPDATE),
    ("delete", RequestType.DELETE),
    ("WidgetCreateRequest", RequestType.CREATE),
    ("WidgetUpdateRequest", RequestType.UPDATE),
    ("WidgetDeleteRequest", RequestType.DELETE),
])
def test_type_valid_values(value, expected):
    assert _parse(type=value).type is expected


@pytest.mark.parametrize("value", [
    "",                      # empty string
    "Create",                # wrong case
    "recreate",              # valid name embedded in a longer string
    "WidgetCreateRequests",
    "frobnicate",            # unknown name
    5,                       # wrong type
    None,                    # null
])
def test_type_invalid_values(value):
    with pytest.raises(InvalidRequestError):
        _parse(type=value)


# ---- owner ----

@pytest.mark.parametrize("value", ["Henry", "Sue Smith", "mary ann matthews"])
def test_owner_valid_values(value):
    assert _parse(owner=value).owner == value


@pytest.mark.parametrize("value", ["", "Sue_Smith", "Sue Smith2", "Zoë", 42, None])
def test_owner_invalid_values(value):
    with pytest.raises(InvalidRequestError):
        _parse(owner=value)


# ---- required fields ----

@pytest.mark.parametrize("field", ["type", "requestId", "widgetId", "owner"])
def test_missing_required_field_is_rejected(field):
    with pytest.raises(InvalidRequestError):
        _parse_without(field)


@pytest.mark.parametrize("field", ["requestId", "widgetId"])
@pytest.mark.parametrize("value", [123, None, ["x"]])
def test_id_fields_must_be_strings(field, value):
    with pytest.raises(InvalidRequestError):
        _parse(**{field: value})


# ---- label / description (optional strings) ----

@pytest.mark.parametrize("field, attr", [("label", "label"), ("description", "description")])
@pytest.mark.parametrize("value", ["text", "", None])
def test_optional_string_fields_accept_string_empty_or_null(field, attr, value):
    assert getattr(_parse(**{field: value}), attr) == value


@pytest.mark.parametrize("field", ["label", "description"])
def test_optional_string_fields_absent_become_none(field):
    assert getattr(_parse_without(field), field) is None


@pytest.mark.parametrize("field", ["label", "description"])
def test_optional_string_fields_reject_non_strings(field):
    with pytest.raises(InvalidRequestError):
        _parse(**{field: 7})


# ---- otherAttributes ----

@pytest.mark.parametrize("value, expected", [
    (None, []),
    ([], []),
    ([{"name": "color", "value": "red"}], [Attribute("color", "red")]),
    ([{"name": "a", "value": "1"}, {"name": "b", "value": "2"}],
     [Attribute("a", "1"), Attribute("b", "2")]),
    ([{"name": "color", "value": ""}], [Attribute("color", "")]),
    ([{"name": "color", "value": None}], [Attribute("color", None)]),
])
def test_other_attributes_valid_values(value, expected):
    assert _parse(otherAttributes=value).other_attributes == expected


def test_other_attributes_absent_becomes_empty():
    assert _parse_without("otherAttributes").other_attributes == []


@pytest.mark.parametrize("value", [
    "color=red",                         # not an array
    [{"name": "color"}],                 # item missing value
    [{"value": "red"}],                  # item missing name
    [{"name": 1, "value": "red"}],       # name not a string
    [{"name": "color", "value": 3}],     # value not a string
    ["color"],                           # item not an object
])
def test_other_attributes_invalid_values(value):
    with pytest.raises(InvalidRequestError):
        _parse(otherAttributes=value)


# ---- malformed input ----

@pytest.mark.parametrize("text", ["{not json", "", "null", "[]", '"create"', None])
def test_malformed_or_non_object_input_is_rejected(text):
    with pytest.raises(InvalidRequestError):
        parse_request(text)


# ---- WidgetRequest.to_widget ----

def test_to_widget_copies_all_request_data(create_request_json):
    request = parse_request(create_request_json)

    widget = request.to_widget()

    assert widget == Widget(
        id=CREATE_REQUEST["widgetId"],
        owner="Sue Smith",
        label="IUGSPN",
        description="ETHOQJFDFK",
        other_attributes={"size": "586", "size-unit": "cm"},
    )


def test_to_widget_without_optional_data():
    request = WidgetRequest(RequestType.CREATE, "r", "w", "Sue Smith")

    widget = request.to_widget()

    assert widget == Widget(id="w", owner="Sue Smith", label=None, description=None,
                            other_attributes={})


def test_to_widget_duplicate_attribute_names_keep_last_value():
    request = WidgetRequest(RequestType.CREATE, "r", "w", "Sue Smith",
                            other_attributes=[Attribute("color", "red"), Attribute("color", "blue")])

    assert request.to_widget().other_attributes == {"color": "blue"}


# ---- Widget serialization ----

def test_widget_to_json_includes_all_properties():
    widget = Widget(id="w1", owner="Sue Smith", label="L", description="D",
                    other_attributes={"color": "red", "size": "5"})

    data = json.loads(widget.to_json())

    assert data == {
        "id": "w1", "owner": "Sue Smith", "label": "L", "description": "D",
        "otherAttributes": [{"name": "color", "value": "red"}, {"name": "size", "value": "5"}],
    }


def test_widget_to_json_with_no_optional_data():
    widget = Widget(id="w1", owner="Sue Smith")

    data = json.loads(widget.to_json())

    assert data == {"id": "w1", "owner": "Sue Smith", "label": None, "description": None,
                    "otherAttributes": []}
