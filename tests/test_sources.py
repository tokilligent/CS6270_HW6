"""Unit tests for consumer.sources.S3RequestSource.

next_request paths: bucket empty -> None; key found -> get + delete -> RawRequest;
key vanished before get (NoSuchKey or 404) -> None; any other error -> raised.
The Stubber enforces call order and the fixture asserts every expected call was made.
"""
import io

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from consumer.sources import RawRequest, S3RequestSource

BUCKET = "requests-bucket"
LIST_PARAMS = {"Bucket": BUCKET, "MaxKeys": 1}


def _body(text):
    data = text.encode("utf-8")
    return StreamingBody(io.BytesIO(data), len(data))


@pytest.mark.parametrize("list_response", [{"KeyCount": 0}, {"KeyCount": 0, "Contents": []}])
def test_returns_none_when_bucket_empty(s3_stub, list_response):
    client, stub = s3_stub
    stub.add_response("list_objects_v2", list_response, LIST_PARAMS)

    result = S3RequestSource(client, BUCKET).next_request()

    assert result is None


def test_reads_then_deletes_smallest_key(s3_stub):
    client, stub = s3_stub
    stub.add_response("list_objects_v2", {"Contents": [{"Key": "1612306368338"}]}, LIST_PARAMS)
    stub.add_response("get_object", {"Body": _body('{"a":1}')},
                      {"Bucket": BUCKET, "Key": "1612306368338"})
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": "1612306368338"})

    result = S3RequestSource(client, BUCKET).next_request()

    assert result == RawRequest(source_id="1612306368338", body='{"a":1}')


def test_decodes_body_as_utf8(s3_stub):
    client, stub = s3_stub
    stub.add_response("list_objects_v2", {"Contents": [{"Key": "k"}]}, LIST_PARAMS)
    stub.add_response("get_object", {"Body": _body("café")}, {"Bucket": BUCKET, "Key": "k"})
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": "k"})

    result = S3RequestSource(client, BUCKET).next_request()

    assert result.body == "café"


@pytest.mark.parametrize("code, status", [("NoSuchKey", 404), ("404", 404)])
def test_returns_none_if_request_vanishes_before_get(s3_stub, code, status):
    client, stub = s3_stub
    stub.add_response("list_objects_v2", {"Contents": [{"Key": "k"}]}, LIST_PARAMS)
    stub.add_client_error("get_object", service_error_code=code, http_status_code=status)

    result = S3RequestSource(client, BUCKET).next_request()

    assert result is None  # and no delete_object was attempted


@pytest.mark.parametrize("operation", ["list_objects_v2", "get_object", "delete_object"])
def test_other_errors_propagate(s3_stub, operation):
    client, stub = s3_stub
    responses = [
        ("list_objects_v2", {"Contents": [{"Key": "k"}]}),
        ("get_object", {"Body": _body("{}")}),
        ("delete_object", {}),
    ]
    for name, response in responses:
        if name == operation:
            stub.add_client_error(name, service_error_code="AccessDenied", http_status_code=403)
            break
        stub.add_response(name, response)

    with pytest.raises(ClientError) as exc:
        S3RequestSource(client, BUCKET).next_request()

    assert exc.value.response["Error"]["Code"] == "AccessDenied"
