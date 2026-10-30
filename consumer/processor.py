"""Applies parsed Widget Requests to a WidgetStore."""
import logging

from .models import RequestType, WidgetRequest
from .storage import WidgetStore

logger = logging.getLogger(__name__)


class RequestProcessor:
    def __init__(self, store: WidgetStore):
        self._store = store
        self._handlers = {
            RequestType.CREATE: self._create,
            RequestType.UPDATE: self._update,
            RequestType.DELETE: self._delete,
        }

    def process(self, request: WidgetRequest) -> None:
        logger.info(
            "Processing %s request %s for widget %s (owner %s)",
            request.type.value, request.request_id, request.widget_id, request.owner,
        )
        self._handlers[request.type](request)

    def _create(self, request: WidgetRequest) -> None:
        self._store.save(request.to_widget())

    def _update(self, request: WidgetRequest) -> None:
        # HW7: add WidgetStore.get, apply the changes, then save.
        logger.warning("Update requests are not supported yet; skipped request %s",
                       request.request_id)

    def _delete(self, request: WidgetRequest) -> None:
        # HW7: add WidgetStore.delete, warn if the widget did not exist.
        logger.warning("Delete requests are not supported yet; skipped request %s",
                       request.request_id)
