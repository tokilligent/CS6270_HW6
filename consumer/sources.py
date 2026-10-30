"""Request sources: where Widget Requests come from.

The Consumer only depends on the RequestSource interface, so a different
source (e.g. an SQS queue in a later assignment) can be swapped in at runtime.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class RawRequest:
    """An unparsed request plus an identifier for where it came from."""
    source_id: str
    body: str


class RequestSource(ABC):
    @abstractmethod
    def next_request(self) -> Optional[RawRequest]:
        """Remove and return the next request, or None if none is available."""


class S3RequestSource(RequestSource):
    """Reads requests one at a time from an S3 bucket, smallest key first."""

    def __init__(self, s3_client, bucket: str):
        self._s3 = s3_client
        self._bucket = bucket

    def next_request(self) -> Optional[RawRequest]:
        key = self._first_key()
        if key is None:
            return None

        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            # Another consumer may have taken it between the list and the get.
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                logger.debug("Request %s disappeared before it could be read", key)
                return None
            raise
        body = obj["Body"].read().decode("utf-8")

        self._s3.delete_object(Bucket=self._bucket, Key=key)
        logger.debug("Retrieved and deleted request s3://%s/%s", self._bucket, key)
        return RawRequest(source_id=key, body=body)

    def _first_key(self) -> Optional[str]:
        # S3 lists keys in ascending UTF-8 order, so MaxKeys=1 gives the smallest.
        resp = self._s3.list_objects_v2(Bucket=self._bucket, MaxKeys=1)
        contents = resp.get("Contents", [])
        return contents[0]["Key"] if contents else None
