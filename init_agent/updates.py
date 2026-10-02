"""Explicit remote release checks for init-agent."""

from __future__ import annotations

import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


from .bounded_json import read_bounded, decode_bounded

MAX_RELEASE_BYTES = 256 * 1024

LATEST_RELEASE_URL = "https://api.github.com/repos/alessandroserpe/init-agent/releases/latest"


def check_latest_release(current_version: str, timeout: float = 3.0) -> dict[str, Any]:
    request = Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"init-agent/{current_version}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or len(length) > 10 or int(length) > MAX_RELEASE_BYTES):
                raise ValueError("release response exceeds byte limit")
            payload = decode_bounded(read_bounded(response, MAX_RELEASE_BYTES), MAX_RELEASE_BYTES)
        if not isinstance(payload, dict):
            raise ValueError("release response must be an object")
        for key, maximum in (("tag_name", 128), ("html_url", 2048)):
            value = payload.get(key, "")
            if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError("invalid release field")
        latest = str(payload.get("tag_name", "")).lstrip("v")
        if not latest:
            raise ValueError("latest release response has no tag_name")
        latest_key = _version_key(latest)
        current_key = _version_key(current_version)
        update_available = latest_key > current_key
        if update_available:
            status = "update_available"
            message = f"init-agent {latest} is available."
        elif current_key > latest_key:
            status = "ahead"
            message = f"init-agent {current_version} is newer than the latest published release {latest}."
        else:
            status = "current"
            message = f"init-agent {current_version} is current."
        return {
            "status": status,
            "current_version": current_version,
            "latest_version": latest,
            "update_available": update_available,
            "url": str(payload.get("html_url", "")),
            "message": message,
        }
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "current_version": current_version,
            "latest_version": "",
            "update_available": False,
            "url": "",
            "message": f"Could not check the latest GitHub release: {exc}",
        }


def _version_key(value: str) -> tuple[int, ...]:
    numbers = [int(item) for item in re.findall(r"\d+", value)]
    return tuple((numbers + [0, 0, 0])[:3])
