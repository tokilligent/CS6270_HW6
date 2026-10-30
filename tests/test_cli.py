"""Unit tests for consumer.cli.

Argument validation: required/optional options, allowed choices, numeric ranges.
main() paths: usage error, normal run, run interrupted by Ctrl-C.
Factories: one test per storage strategy.
"""
import logging

import pytest
from click.testing import CliRunner

from consumer import cli
from consumer.sources import S3RequestSource
from consumer.storage import DynamoWidgetStore, S3WidgetStore


class FakeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.clients = []

    def client(self, name):
        self.clients.append(name)
        return object()


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for h in root.handlers[len(handlers):]:
        h.close()
    root.handlers, root.level = handlers, level


@pytest.fixture
def fake_aws(monkeypatch):
    """Replace boto3.Session and Consumer.run; record what main() passes to them."""
    calls = {"sessions": [], "runs": []}

    def session(**kwargs):
        calls["sessions"].append(FakeSession(**kwargs))
        return calls["sessions"][-1]

    monkeypatch.setattr(cli.boto3, "Session", session)
    monkeypatch.setattr(cli.Consumer, "run", lambda self, **kw: calls["runs"].append((self, kw)))
    return calls


def _invoke(*args):
    return CliRunner().invoke(cli.main, list(args))


# ---- argument validation ----

def test_help_lists_options():
    result = _invoke("--help")

    assert result.exit_code == 0
    for opt in ("--request-bucket", "--storage", "--widget-bucket", "--table",
                "--poll-interval", "--max-runtime", "--max-idle", "--log-file"):
        assert opt in result.output


def test_request_bucket_is_required(fake_aws):
    result = _invoke("-s", "dynamodb")

    assert result.exit_code == 2
    assert "--request-bucket" in result.output
    assert fake_aws["runs"] == []


def test_s3_storage_requires_widget_bucket(fake_aws):
    result = _invoke("-rb", "req", "-s", "s3")

    assert result.exit_code == 2
    assert "--widget-bucket is required" in result.output
    assert fake_aws["runs"] == []


def test_storage_must_be_a_known_strategy(fake_aws):
    result = _invoke("-rb", "req", "-s", "mysql")

    assert result.exit_code == 2
    assert fake_aws["runs"] == []


@pytest.mark.parametrize("option", ["-pi", "-mrt", "-mit"])
@pytest.mark.parametrize("value", ["-1", "abc"])
def test_time_options_reject_negative_or_non_numeric(fake_aws, option, value):
    result = _invoke("-rb", "req", "-s", "dynamodb", option, value)

    assert result.exit_code == 2
    assert fake_aws["runs"] == []


@pytest.mark.parametrize("ms, expected", [(0, None), (1, 0.001), (5000, 5.0)])
def test_ms_to_seconds(ms, expected):
    assert cli._ms_to_seconds(ms) == expected


# ---- factories ----

def test_build_source():
    session = FakeSession()

    source = cli.build_source(session, "req")

    assert isinstance(source, S3RequestSource)
    assert source._bucket == "req"
    assert session.clients == ["s3"]


@pytest.mark.parametrize("storage, expected_type, expected_client, expected_target", [
    ("s3", S3WidgetStore, "s3", ("_bucket", "web")),
    ("dynamodb", DynamoWidgetStore, "dynamodb", ("_table", "widgets")),
])
def test_build_store(storage, expected_type, expected_client, expected_target):
    session = FakeSession()

    store = cli.build_store(session, storage, "web", "widgets")

    assert isinstance(store, expected_type)
    assert getattr(store, expected_target[0]) == expected_target[1]
    assert session.clients == [expected_client]


# ---- main ----

def test_main_with_defaults(fake_aws, tmp_path):
    log_file = tmp_path / "c.log"

    result = _invoke("-rb", "req", "-wb", "web", "-l", str(log_file))

    assert result.exit_code == 0, result.output
    assert fake_aws["sessions"][0].kwargs == {"profile_name": None, "region_name": "us-east-1"}
    consumer, kwargs = fake_aws["runs"][0]
    assert kwargs == {"max_runtime": None, "max_idle": None}
    assert consumer._poll_interval == 0.1
    assert consumer._source._bucket == "req"
    assert isinstance(consumer._processor._store, S3WidgetStore)
    assert consumer._processor._store._bucket == "web"
    assert "Starting consumer" in log_file.read_text()


def test_main_with_all_options(fake_aws, tmp_path):
    log_file = tmp_path / "c.log"

    result = _invoke("-rb", "req", "-s", "dynamodb", "-dwt", "tbl", "-p", "prof", "-r", "us-west-2",
                     "-pi", "250", "-mrt", "5000", "-mit", "2000", "-l", str(log_file))

    assert result.exit_code == 0, result.output
    assert fake_aws["sessions"][0].kwargs == {"profile_name": "prof", "region_name": "us-west-2"}
    consumer, kwargs = fake_aws["runs"][0]
    assert kwargs == {"max_runtime": 5.0, "max_idle": 2.0}
    assert consumer._poll_interval == 0.25
    assert isinstance(consumer._processor._store, DynamoWidgetStore)
    assert consumer._processor._store._table == "tbl"


def test_main_stops_cleanly_on_ctrl_c(fake_aws, monkeypatch, tmp_path):
    def interrupted_run(self, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.Consumer, "run", interrupted_run)
    log_file = tmp_path / "c.log"

    result = _invoke("-rb", "req", "-s", "dynamodb", "-l", str(log_file))

    assert result.exit_code == 0, result.output
    assert "Interrupted; stopping. 0 processed, 0 failed" in log_file.read_text()
