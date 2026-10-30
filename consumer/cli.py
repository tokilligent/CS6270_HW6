"""Command-line entry point: parses arguments and wires the components together."""
import logging
import sys

import boto3
import click

from .loop import Consumer
from .processor import RequestProcessor
from .sources import RequestSource, S3RequestSource
from .storage import DynamoWidgetStore, S3WidgetStore, WidgetStore

logger = logging.getLogger("consumer")

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s - %(message)s"


def configure_logging(log_file: str, level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)
    for handler in (logging.FileHandler(log_file), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    # Keep the AWS SDK's own debug chatter out of our log.
    for noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_source(session, request_bucket: str) -> RequestSource:
    return S3RequestSource(session.client("s3"), request_bucket)


def build_store(session, storage: str, widget_bucket, table) -> WidgetStore:
    if storage == "s3":
        return S3WidgetStore(session.client("s3"), widget_bucket)
    return DynamoWidgetStore(session.client("dynamodb"), table)


def _ms_to_seconds(ms: int):
    return ms / 1000 if ms > 0 else None


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-p", "--profile", default=None, help="AWS profile to use for credentials.")
@click.option("-r", "--region", default="us-east-1", show_default=True, help="AWS region.")
@click.option("-rb", "--request-bucket", required=True, help="Bucket containing Widget Requests (Bucket 2).")
@click.option("-s", "--storage", type=click.Choice(["s3", "dynamodb"]), default="s3", show_default=True,
              help="Where to store widgets.")
@click.option("-wb", "--widget-bucket", default=None, help="Bucket to store widgets in (Bucket 3). Required with --storage s3.")
@click.option("-dwt", "--table", default="widgets", show_default=True, help="DynamoDB table to store widgets in.")
@click.option("-pi", "--poll-interval", default=100, show_default=True, type=click.IntRange(min=0),
              help="Milliseconds to wait when no request is available.")
@click.option("-mrt", "--max-runtime", default=0, show_default=True, type=click.IntRange(min=0),
              help="Stop after this many milliseconds (0 = run until interrupted).")
@click.option("-mit", "--max-idle", default=0, show_default=True, type=click.IntRange(min=0),
              help="Stop after this many milliseconds without a request (0 = never).")
@click.option("-l", "--log-file", default="consumer.log", show_default=True, help="Log file path.")
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]), default="INFO",
              show_default=True)
def main(profile, region, request_bucket, storage, widget_bucket, table,
         poll_interval, max_runtime, max_idle, log_file, log_level):
    """Consume Widget Requests from S3 and store widgets in S3 or DynamoDB.

    \b
    Examples:
      python -m consumer -rb usu-cs5270-toki-requests -s s3 -wb usu-cs5270-toki-web
      python -m consumer -rb usu-cs5270-toki-requests -s dynamodb -dwt widgets -mit 10000
    """
    if storage == "s3" and not widget_bucket:
        raise click.UsageError("--widget-bucket is required when --storage is s3")

    configure_logging(log_file, log_level)
    logger.info("Starting consumer: request-bucket=%s storage=%s target=%s region=%s",
                request_bucket, storage, widget_bucket if storage == "s3" else table, region)

    session = boto3.Session(profile_name=profile, region_name=region)
    consumer = Consumer(
        source=build_source(session, request_bucket),
        processor=RequestProcessor(build_store(session, storage, widget_bucket, table)),
        poll_interval=poll_interval / 1000,
    )
    try:
        consumer.run(max_runtime=_ms_to_seconds(max_runtime), max_idle=_ms_to_seconds(max_idle))
    except KeyboardInterrupt:
        logger.info("Interrupted; stopping. %d processed, %d failed",
                    consumer.stats.processed, consumer.stats.failed)
