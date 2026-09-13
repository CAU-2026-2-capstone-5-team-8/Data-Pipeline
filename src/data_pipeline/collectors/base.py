"""Shared, lightweight collector response handling."""

import json
from typing import Any

import httpx


class InvalidProviderResponse(ValueError):
    """Raised when a provider returns a successful but unusable response."""


def parse_json_object(response: httpx.Response, provider: str) -> dict[str, Any]:
    """Decode one provider response and require a top-level JSON object."""
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise InvalidProviderResponse(f"{provider} returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise InvalidProviderResponse(f"{provider} returned a non-object response")
    return payload
