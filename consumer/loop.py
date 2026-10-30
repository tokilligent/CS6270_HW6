"""The Consumer polling loop."""
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from botocore.exceptions import BotoCoreError, ClientError

from .models import InvalidRequestError, parse_request
from .processor import RequestProcessor
from .sources import RequestSource

logger = logging.getLogger(__name__)


@dataclass
class ConsumerStats:
    processed: int = 0
    failed: int = 0


class Consumer:
    def __init__(
        self,
        source: RequestSource,
        processor: RequestProcessor,
        poll_interval: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._source = source
        self._processor = processor
        self._poll_interval = poll_interval
        self._sleep = sleep
        self._clock = clock
        self.stats = ConsumerStats()

    def run(self, max_runtime: Optional[float] = None, max_idle: Optional[float] = None) -> ConsumerStats:
        """Poll until max_runtime seconds elapse or no request arrives for max_idle seconds.

        None for either limit means no limit.
        """
        start = last_activity = self._clock()
        logger.info("Consumer started (max_runtime=%s, max_idle=%s)", max_runtime, max_idle)
        while True:
            now = self._clock()
            if max_runtime is not None and now - start >= max_runtime:
                logger.info("Maximum runtime reached; stopping")
                break
            if max_idle is not None and now - last_activity >= max_idle:
                logger.info("No requests for %.1fs; stopping", max_idle)
                break

            if self.poll_once():
                last_activity = self._clock()
            else:
                self._sleep(self._poll_interval)

        logger.info("Consumer stopped: %d processed, %d failed",
                    self.stats.processed, self.stats.failed)
        return self.stats

    def poll_once(self) -> bool:
        """Try to get and process one request. Returns True if a request was retrieved."""
        try:
            raw = self._source.next_request()
        except (ClientError, BotoCoreError) as e:
            logger.error("Failed to retrieve request: %s", e)
            return False
        if raw is None:
            return False

        try:
            request = parse_request(raw.body)
            self._processor.process(request)
            self.stats.processed += 1
        except InvalidRequestError as e:
            self.stats.failed += 1
            logger.error("Skipping invalid request %s: %s", raw.source_id, e)
        except (ClientError, BotoCoreError) as e:
            self.stats.failed += 1
            logger.error("Failed to process request %s: %s", raw.source_id, e)
        return True
