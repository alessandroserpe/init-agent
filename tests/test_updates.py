import json

from unittest.mock import patch

from init_agent.updates import check_latest_release
from tests.support import InitAgentTestCase


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class UpdateTests(InitAgentTestCase):
    def test_latest_release_reports_available_version(self) -> None:
        response = _Response({"tag_name": "v0.49.0", "html_url": "https://example.invalid/v0.49.0"})
        with patch("init_agent.updates.urlopen", return_value=response):
            result = check_latest_release("0.48.0")
        self.assertEqual(result["status"], "update_available")
        self.assertTrue(result["update_available"])

    def test_latest_release_failure_is_non_fatal(self) -> None:
        with patch("init_agent.updates.urlopen", side_effect=TimeoutError("timeout")):
            result = check_latest_release("0.48.0")
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["update_available"])

    def test_local_development_version_can_be_ahead_of_latest_release(self) -> None:
        response = _Response({"tag_name": "v0.48.0", "html_url": "https://example.invalid/v0.48.0"})
        with patch("init_agent.updates.urlopen", return_value=response):
            result = check_latest_release("0.49.0")
        self.assertEqual(result["status"], "ahead")
        self.assertFalse(result["update_available"])
