from tests.support import *

from init_agent.web_ui import build_web_snapshot, render_dashboard_html


class WebUiTests(InitAgentTestCase):
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

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["web", "--snapshot-json", "--limit", "5"]), 0)
                data = json.loads(output.getvalue())
                self.assertTrue(data["project"]["initialized"])
                self.assertGreaterEqual(data["counts"]["files"], 1)
                self.assertEqual(data["recent_memory"][0]["path"], "src/auth/session.py")
                self.assertEqual(data["recent_feedback"][0]["rating"], "useful")
                self.assertEqual(data["open_tasks"][0]["title"], "Inspect login flow")
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
            self.assertIn('id="table-search"', html)
            self.assertIn("Warnings", html)
