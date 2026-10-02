from tests.support import *

from init_agent.web_ui import build_web_snapshot, render_dashboard_html
from init_agent.web_ui import serve_web_ui
from http.server import ThreadingHTTPServer
from unittest.mock import patch


class WebUiTests(InitAgentTestCase):
    def test_server_rejects_non_loopback_bindings(self) -> None:
        for host in ("0.0.0.0", "::", "192.168.1.10", "public.example"):
            with self.subTest(host=host), patch.object(ThreadingHTTPServer, "__init__") as initialize:
                with self.assertRaisesRegex(ValueError, "loopback"):
                    serve_web_ui(Path("."), host=host)
                initialize.assert_not_called()

    def test_server_checks_host_and_origin_before_loading_metadata(self) -> None:
        class RequestSocket:
            def __init__(self, request):
                self.input = BytesIO(request)
                self.output = BytesIO()

            def makefile(self, *args):
                return self.input

            def sendall(self, value):
                self.output.write(value)

        for bind_host, authority in (("127.0.0.1", "127.0.0.1:8765"), ("localhost", "localhost:8765"), ("::1", "[::1]:8765")):
            requests = [
                (f"Host: {authority}\r\nAuthorization: Bearer test-launch-token\r\n", 200),
                (f"Host: {authority}\r\n", 401),
                (f"Host: {authority}\r\nAuthorization: Bearer wrong-token\r\n", 401),
                (f"Host: {authority}\r\nAuthorization: Bearer test-launch-token\r\nAuthorization: Bearer test-launch-token\r\n", 401),
                (f"Host: {authority}\r\nOrigin: http://{authority}\r\nAuthorization: Bearer test-launch-token\r\n", 200),
                ("Host: untrusted.example\r\n", 403),
                ("", 403),
                (f"Host: {authority}\r\nHost: evil.example\r\n", 403),
                (f"Host: {authority}\r\nOrigin: https://evil.example\r\n", 403),
                (f"Host: {authority}\r\nOrigin: null\r\n", 403),
                (f"Host: {authority}\r\nSec-Fetch-Site: cross-site\r\n", 403),
                ("Host: localhost:9999\r\n", 403),
            ]
            responses = []

            def initialize(server, address, handler):
                server.server_port = 8765
                server.RequestHandlerClass = handler

            def run(server):
                for headers, expected in requests:
                    for path in ("/api/snapshot", "/"):
                        before = snapshot.call_count
                        request = RequestSocket(f"GET {path} HTTP/1.1\r\n{headers}\r\n".encode())
                        server.RequestHandlerClass(request, ("127.0.0.1", 1000), server)
                        status = 200 if path == "/" and headers == f"Host: {authority}\r\n" else expected
                        responses.append((request.output.getvalue(), status))
                        self.assertEqual(snapshot.call_count - before, int(expected == 200))
                        self.assertNotIn(b"test-launch-token", request.output.getvalue())
                # Capabilities in URLs or cookies do not authenticate API calls.
                for path, extra in (("/api/snapshot?token=test-launch-token", ""),
                                    ("/api/snapshot", "Cookie: token=test-launch-token\r\n")):
                    before = snapshot.call_count
                    request = RequestSocket(f"GET {path} HTTP/1.1\r\nHost: {authority}\r\n{extra}\r\n".encode())
                    server.RequestHandlerClass(request, ("127.0.0.1", 1000), server)
                    responses.append((request.output.getvalue(), 401))
                    self.assertEqual(snapshot.call_count, before)

            with self.subTest(host=bind_host), patch.object(ThreadingHTTPServer, "__init__", initialize), patch.object(ThreadingHTTPServer, "serve_forever", run), patch.object(ThreadingHTTPServer, "server_close"), patch("init_agent.web_ui.build_web_snapshot", return_value={}) as snapshot, patch("init_agent.web_ui.render_dashboard_html", return_value="<html>private</html>"), patch("init_agent.web_ui.secrets.token_urlsafe", return_value="test-launch-token") as generate, redirect_stdout(StringIO()):
                serve_web_ui(Path("."), host=bind_host)
                self.assertEqual(snapshot.call_count, 4)
                generate.assert_called_once_with(32)
            for response, expected in responses:
                self.assertIn(f" {expected} ".encode(), response.split(b"\r\n")[0])
                self.assertIn(b"Cache-Control: no-store", response)
                self.assertIn(b"X-Content-Type-Options: nosniff", response)

    def test_web_snapshot_json_reports_local_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_memory_add",
                                "--path",
                                "src/auth/session.py",
                                "--topic",
                                "login session",
                                "--note",
                                "Session validation lives here.",
                                "--evidence",
                                "read_excerpt",
                                "--json",
                            ]
                        ),
                        0,
                    )
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_feedback_add",
                                "--query",
                                "login session",
                                "--path",
                                "src/auth/session.py",
                                "--rating",
                                "useful",
                                "--reason",
                                "verified relevant",
                                "--json",
                            ]
                        ),
                        0,
                    )
                with redirect_stdout(StringIO()):
                    self.assertEqual(main(["task", "add", "Inspect login flow", "--topic", "auth", "--json"]), 0)
                plan_output = StringIO()
                with redirect_stdout(plan_output):
                    self.assertEqual(main(["tool", "repo_reading_plan", "--query", "login session", "--read", "1", "--json"]), 0)
                plan = json.loads(plan_output.getvalue())
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_reading_plan_finish",
                                "--id",
                                str(plan["id"]),
                                "--read",
                                "src/auth/session.py",
                                "--verified",
                                "src/auth/session.py",
                                "--useful",
                                "src/auth/session.py",
                                "--summary",
                                "verified web scorecard fixture",
                                "--json",
                            ]
                        ),
                        0,
                    )

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["web", "--snapshot-json", "--limit", "5"]), 0)
                data = json.loads(output.getvalue())
                self.assertTrue(data["project"]["initialized"])
                self.assertGreaterEqual(data["counts"]["files"], 1)
                self.assertEqual(data["recent_memory"][0]["path"], "src/auth/session.py")
                self.assertEqual(data["recent_feedback"][0]["rating"], "useful")
                self.assertEqual(data["open_tasks"][0]["title"], "Inspect login flow")
                self.assertEqual(data["scorecard"]["scorecard_evaluable_plan_count"], 1)
                self.assertEqual(data["scorecard"]["top1_hit_rate"], 1.0)
                self.assertEqual(data["scorecard"]["scorecard_confidence"], "low")
                self.assertIn("explicit_read_tracking_rate", data["scorecard"])
                self.assertTrue(any(item["path"] == "src/auth/session.py" for item in data["file_activity"]))
            finally:
                os.chdir(previous)

    def test_web_snapshot_and_html_handle_uninitialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = build_web_snapshot(root)
            self.assertFalse(snapshot["project"]["initialized"])
            self.assertIn("init-agent index not found", snapshot["warnings"][0])
            html = render_dashboard_html(snapshot)
            self.assertIn("Local Agent Observatory", html)
            self.assertIn('data-tab-target="memory"', html)
            self.assertIn('data-tab-target="scorecard"', html)
            self.assertIn('id="table-search"', html)
            self.assertIn("Warnings", html)
