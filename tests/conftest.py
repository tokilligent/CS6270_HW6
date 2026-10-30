import json

import boto3
import pytest
from botocore.stub import Stubber

CREATE_REQUEST = {
    "type": "create",
    "requestId": "8b493c24-02b8-40c2-bca8-6a0cef8737c0",
    "widgetId": "6cea7243-924a-4bc9-9779-8bc89e91acdf",
    "owner": "Sue Smith",
    "label": "IUGSPN",
    "description": "ETHOQJFDFK",
    "otherAttributes": [
        {"name": "size", "value": "586"},
        {"name": "size-unit", "value": "cm"},
    ],
}


def _client(service):
    return boto3.client(service, region_name="us-east-1",
                        aws_access_key_id="test", aws_secret_access_key="test")


@pytest.fixture
def create_request_json():
    return json.dumps(CREATE_REQUEST)


@pytest.fixture
def s3_stub():
    client = _client("s3")
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


@pytest.fixture
def ddb_stub():
    client = _client("dynamodb")
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()
