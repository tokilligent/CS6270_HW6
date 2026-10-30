"""Widget storage strategies: S3 bucket or DynamoDB table."""
import logging
from abc import ABC, abstractmethod

from .models import Widget

logger = logging.getLogger(__name__)


class WidgetStore(ABC):
    @abstractmethod
    def save(self, widget: Widget) -> None:
        """Create or overwrite a widget."""


def owner_key_part(owner: str) -> str:
    return owner.replace(" ", "-").lower()


def s3_widget_key(owner: str, widget_id: str) -> str:
    return f"widgets/{owner_key_part(owner)}/{widget_id}"


class S3WidgetStore(WidgetStore):
    """Stores each widget as a JSON object at widgets/{owner}/{widget id}."""

    def __init__(self, s3_client, bucket: str):
        self._s3 = s3_client
        self._bucket = bucket

    def save(self, widget: Widget) -> None:
        key = s3_widget_key(widget.owner, widget.id)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=widget.to_json().encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Stored widget %s in s3://%s/%s", widget.id, self._bucket, key)


class DynamoWidgetStore(WidgetStore):
    """Stores each widget as an item, one DynamoDB attribute per widget property."""

    KEY_ATTRIBUTE = "id"
    RESERVED = {"id", "owner", "label", "description"}

    def __init__(self, dynamodb_client, table: str):
        self._ddb = dynamodb_client
        self._table = table

    def save(self, widget: Widget) -> None:
        self._ddb.put_item(TableName=self._table, Item=self.to_item(widget))
        logger.info("Stored widget %s in DynamoDB table %s", widget.id, self._table)

    @classmethod
    def to_item(cls, widget: Widget) -> dict:
        item = {
            cls.KEY_ATTRIBUTE: {"S": widget.id},
            "owner": {"S": widget.owner},
        }
        if widget.label is not None:
            item["label"] = {"S": widget.label}
        if widget.description is not None:
            item["description"] = {"S": widget.description}
        for name, value in widget.other_attributes.items():
            if name in cls.RESERVED:
                logger.warning(
                    "Widget %s: other attribute '%s' clashes with a core attribute; skipped",
                    widget.id, name,
                )
                continue
            if value is not None:
                item[name] = {"S": value}
        return item
