"""Domain objects: Widget Requests, Widgets, and request parsing."""
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import jsonschema


class RequestType(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


# The assignment's schema names the types WidgetCreateRequest etc., but the
# Producer actually emits "create"/"update"/"delete". Accept either spelling.
_TYPE_ALIASES = {
    "create": RequestType.CREATE,
    "WidgetCreateRequest": RequestType.CREATE,
    "update": RequestType.UPDATE,
    "WidgetUpdateRequest": RequestType.UPDATE,
    "delete": RequestType.DELETE,
    "WidgetDeleteRequest": RequestType.DELETE,
}

# Appendix A schema, with anchored patterns. Null values are allowed for the
# optional properties because update requests use null to mean "unchanged".
REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "pattern": "^(create|update|delete|Widget(Create|Delete|Update)Request)$",
        },
        "requestId": {"type": "string"},
        "widgetId": {"type": "string"},
        "owner": {"type": "string", "pattern": "^[A-Za-z ]+$"},
        "label": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "otherAttributes": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": ["string", "null"]},
                },
                "required": ["name", "value"],
            },
        },
    },
    "required": ["type", "requestId", "widgetId", "owner"],
}


class InvalidRequestError(ValueError):
    """Raised when a Widget Request cannot be parsed or fails validation."""


@dataclass
class Attribute:
    name: str
    value: Optional[str]


@dataclass
class WidgetRequest:
    type: RequestType
    request_id: str
    widget_id: str
    owner: str
    label: Optional[str] = None
    description: Optional[str] = None
    other_attributes: List[Attribute] = field(default_factory=list)

    def to_widget(self) -> "Widget":
        """Build the Widget described by a create request."""
        return Widget(
            id=self.widget_id,
            owner=self.owner,
            label=self.label,
            description=self.description,
            other_attributes={a.name: a.value for a in self.other_attributes},
        )


@dataclass
class Widget:
    id: str
    owner: str
    label: Optional[str] = None
    description: Optional[str] = None
    other_attributes: Dict[str, Optional[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "owner": self.owner,
            "label": self.label,
            "description": self.description,
            "otherAttributes": [
                {"name": name, "value": value}
                for name, value in self.other_attributes.items()
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "Widget":
        return cls(
            id=data["id"],
            owner=data["owner"],
            label=data.get("label"),
            description=data.get("description"),
            other_attributes={a["name"]: a["value"] for a in data.get("otherAttributes") or []},
        )

    def apply_update(self, request: WidgetRequest) -> "Widget":
        """Return a copy of this widget with the changes in an update request applied.

        A missing or null value leaves a property unchanged; an empty string clears
        label/description (sets them to None) or removes an other attribute.
        The id and owner never change.
        """
        others = dict(self.other_attributes)
        for attr in request.other_attributes:
            if attr.value == "":
                others.pop(attr.name, None)
            elif attr.value is not None:
                others[attr.name] = attr.value
        return Widget(
            id=self.id,
            owner=self.owner,
            label=_updated(self.label, request.label),
            description=_updated(self.description, request.description),
            other_attributes=others,
        )


def _updated(current: Optional[str], new: Optional[str]) -> Optional[str]:
    if new is None:
        return current
    return None if new == "" else new


def parse_request(text: str) -> WidgetRequest:
    """Parse and validate a JSON Widget Request."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as e:
        raise InvalidRequestError(f"Request is not valid JSON: {e}") from e

    try:
        jsonschema.validate(data, REQUEST_SCHEMA)
    except jsonschema.ValidationError as e:
        raise InvalidRequestError(f"Request does not match schema: {e.message}") from e

    return WidgetRequest(
        type=_TYPE_ALIASES[data["type"]],
        request_id=data["requestId"],
        widget_id=data["widgetId"],
        owner=data["owner"],
        label=data.get("label"),
        description=data.get("description"),
        other_attributes=[
            Attribute(a["name"], a["value"]) for a in data.get("otherAttributes") or []
        ],
    )
