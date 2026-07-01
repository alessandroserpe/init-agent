from tests.support import *


class CliToolsTests(InitAgentTestCase):
    def test_tool_repo_graph_search_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["tool", "repo_graph_search", "--query", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_graph_search")
                self.assertEqual(data["contract"], "init-agent.tool.v1")
                self.assertEqual(data["query"], "login session")
                self.assertIn("preparation", data)
                self.assertGreaterEqual(len(data["candidate_files"]), 1)
                self.assertIn("src/auth/session.py", data["suggested_first_reads"])
                self.assertIn("symbols", data)
                self.assertIn("related_commits", data)
                self.assertIn("confidence", data)
                self.assertIn("next_agent_actions", data)
                self.assertIn("followup_commands", data)
                self.assertIn("warnings", data)
            finally:
                os.chdir(previous)

    def test_tool_repo_graph_search_limit_and_followups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["tool", "repo_graph_search", "--query", "login session", "--limit", "1", "--json"]),
                        0,
                    )
                data = json.loads(output.getvalue())
                self.assertEqual(len(data["candidate_files"]), 1)
                commands = [item["command"] for item in data["followup_commands"]]
                self.assertTrue(any(command.startswith("init-agent tool repo_related_file ") for command in commands))
                self.assertTrue(any(command.startswith("init-agent tool repo_feedback_add ") for command in commands))
            finally:
                os.chdir(previous)

    def test_tool_repo_trace_follows_php_entrypoint_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_trace_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main([
                            "tool",
                            "repo_trace",
                            "--query",
                            "bug frontend h1 titolo auto generato visualizzazione",
                            "--json",
                        ]),
                        0,
                    )
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_trace")
                self.assertEqual(data["contract"], "init-agent.tool.v1")
                self.assertEqual(data["profile"], "entrypoint_render")
                self.assertEqual(data["paths"][0]["target"], "include/page.php")
                self.assertEqual(data["paths"][0]["path"], ["index.php", "include/page.php"])
                self.assertIn("include/page.php", data["suggested_first_reads"])
                commands = [item["command"] for item in data["followup_commands"]]
                self.assertTrue(any("include/page.php" in command for command in commands))
            finally:
                os.chdir(previous)

    def test_tool_repo_trace_follows_route_handler_to_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_route_template_trace_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main([
                            "tool",
                            "repo_trace",
                            "--query",
                            "request detail route handler render template",
                            "--json",
                        ]),
                        0,
                    )
                data = json.loads(output.getvalue())
                paths = [item["path"] for item in data["paths"]]
                self.assertIn(
                    ["project/urls.py", "blog/views.py", "blog/templates/blog/detail.html"],
                    paths,
                )
                targets = [item["target"] for item in data["paths"]]
                self.assertIn("blog/views.py", targets)
                self.assertIn("blog/templates/blog/detail.html", targets)
            finally:
                os.chdir(previous)

    def test_tool_repo_related_file_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["tool", "repo_related_file", "--path", "include/functions.php", "--json"]),
                        0,
                    )
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_related_file")
                self.assertEqual(data["contract"], "init-agent.tool.v1")
                self.assertEqual(data["path"], "include/functions.php")
                self.assertEqual(data["file"]["path"], "include/functions.php")
                self.assertIn("buildForm", {item["name"] for item in data["symbols"]})
                self.assertIn(("index.php", "buildForm"), {(item["path"], item["name"]) for item in data["called_by"]})
                commands = [item["command"] for item in data["followup_commands"]]
                self.assertTrue(any("repo_symbol_callers" in command for command in commands))
            finally:
                os.chdir(previous)

    def test_tool_repo_symbol_callers_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["tool", "repo_symbol_callers", "--symbol", "buildForm", "--json"]),
                        0,
                    )
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_symbol_callers")
                self.assertEqual(data["contract"], "init-agent.tool.v1")
                self.assertEqual(data["symbol"], "buildForm")
                self.assertIn("include/functions.php", {item["path"] for item in data["definitions"]})
                self.assertIn("index.php", {item["path"] for item in data["callers"]})
                commands = [item["command"] for item in data["followup_commands"]]
                self.assertTrue(any("repo_related_file" in command for command in commands))
            finally:
                os.chdir(previous)

    def test_tool_repo_overview_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["tool", "repo_overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_overview")
                self.assertEqual(data["contract"], "init-agent.tool.v1")
                self.assertEqual(data["project"]["name"], root.name)
                self.assertIn("pyproject.toml", {item["path"] for item in data["suggested_first_reads"]})
                self.assertIn("pyproject.toml", {item["path"] for item in data["manifests"]})
                commands = [item["command"] for item in data["followup_commands"]]
                self.assertTrue(any("repo_related_file" in command for command in commands))
            finally:
                os.chdir(previous)

    def test_tool_repo_entrypoints_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Run\n\nDocumentation run instructions.\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["tool", "repo_entrypoints", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_entrypoints")
                self.assertEqual(data["contract"], "init-agent.tool.v1")
                self.assertTrue(data["entry_points"])
                self.assertNotIn("heading", {item["kind"] for item in data["entry_points"]})
                self.assertNotIn("docs/guide.md", {item["path"] for item in data["entry_points"]})
                self.assertIn("pyproject.toml", {item["path"] for item in data["manifests"]})
                commands = [item["command"] for item in data["followup_commands"]]
                self.assertTrue(any("repo_related_file" in command for command in commands))
            finally:
                os.chdir(previous)

    def test_tool_repo_feedback_add_and_explain_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                add_output = StringIO()
                with redirect_stdout(add_output):
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
                                "crucial",
                                "--reason",
                                "verified session flow",
                                "--json",
                            ]
                        ),
                        0,
                    )
                added = json.loads(add_output.getvalue())
                self.assertEqual(added["tool"], "repo_feedback_add")
                self.assertTrue(added["recorded"])
                self.assertEqual(added["feedback"]["rating"], "crucial")

                explain_output = StringIO()
                with redirect_stdout(explain_output):
                    self.assertEqual(
                        main(["tool", "repo_feedback_explain", "--query", "login session", "--json"]),
                        0,
                    )
                explained = json.loads(explain_output.getvalue())
                self.assertEqual(explained["tool"], "repo_feedback_explain")
                paths = {item["path"] for item in explained["feedback"]["signals"]}
                self.assertIn("src/auth/session.py", paths)

                summary_output = StringIO()
                with redirect_stdout(summary_output):
                    self.assertEqual(main(["tool", "repo_session_summary", "--json"]), 0)
                summary = json.loads(summary_output.getvalue())
                self.assertEqual(summary["tool"], "repo_session_summary")
                self.assertEqual(summary["contract"], "init-agent.tool.v1")
                self.assertEqual(summary["project"]["name"], root.name)
                self.assertTrue(summary["recent_feedback"])
                self.assertEqual(summary["recent_feedback"][0]["path"], "src/auth/session.py")

                close_output = StringIO()
                with redirect_stdout(close_output):
                    self.assertEqual(main(["session", "close", "--json"]), 0)
                closed = json.loads(close_output.getvalue())
                self.assertEqual(closed["tool"], "repo_session_close")
                self.assertEqual(closed["contract"], "init-agent.tool.v1")
                self.assertTrue(any(item["id"] == "review_git_status" for item in closed["checklist"]))
            finally:
                os.chdir(previous)

    def test_tool_repo_memory_add_search_and_file_notes_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                add_output = StringIO()
                with redirect_stdout(add_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_memory_add",
                                "--path",
                                "src/auth/session.py",
                                "--topic",
                                "login session",
                                "--query",
                                "debug login session",
                                "--note",
                                "Session validation lives here; verified during login redirect debugging.",
                            "--evidence",
                            "read_full_file",
                            "--tag",
                            "login_session",
                            "--tag",
                            "redirectFlow",
                            "--json",
                            ]
                        ),
                        0,
                    )
                added = json.loads(add_output.getvalue())
                self.assertEqual(added["tool"], "repo_memory_add")
                self.assertTrue(added["recorded"])
                self.assertEqual(added["memory"]["scope"], "file")
                self.assertFalse(added["memory"]["stale"])
                self.assertEqual(added["memory"]["evidence"], "read_full_file")
                self.assertIn("login", added["memory"]["tags"])
                self.assertIn("redirect", added["memory"]["tags"])

                search_output = StringIO()
                with redirect_stdout(search_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_search", "--query", "login session validation", "--json"]),
                        0,
                    )
                searched = json.loads(search_output.getvalue())
                self.assertEqual(searched["tool"], "repo_memory_search")
                self.assertEqual(searched["memory"]["matches"][0]["path"], "src/auth/session.py")
                self.assertIn("login", searched["memory"]["matches"][0]["tags"])

                topics_output = StringIO()
                with redirect_stdout(topics_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_topics", "--topic", "login session", "--json"]),
                        0,
                    )
                topics = json.loads(topics_output.getvalue())
                self.assertEqual(topics["tool"], "repo_memory_topics")
                self.assertEqual(topics["memory"]["topics"][0]["topic"], "login session")
                self.assertEqual(topics["memory"]["topics"][0]["note_count"], 1)
                self.assertEqual(topics["memory"]["topics"][0]["paths"], ["src/auth/session.py"])

                audit_output = StringIO()
                with redirect_stdout(audit_output):
                    self.assertEqual(main(["tool", "repo_memory_audit", "--json"]), 0)
                audit = json.loads(audit_output.getvalue())
                self.assertEqual(audit["tool"], "repo_memory_audit")
                self.assertEqual(audit["audit"]["note_count"], 1)
                self.assertEqual(audit["audit"]["summary"]["stale"], 0)

                notes_output = StringIO()
                with redirect_stdout(notes_output):
                    self.assertEqual(
                        main(["tool", "repo_file_notes", "--path", "src/auth/session.py", "--json"]),
                        0,
                    )
                notes = json.loads(notes_output.getvalue())
                self.assertEqual(notes["tool"], "repo_file_notes")
                self.assertEqual(notes["notes"][0]["path"], "src/auth/session.py")
                self.assertFalse(notes["notes"][0]["stale"])
                self.assertEqual(notes["notes"][0]["evidence"], "read_full_file")

                list_output = StringIO()
                with redirect_stdout(list_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_list", "--topic", "login session", "--json"]),
                        0,
                    )
                listed = json.loads(list_output.getvalue())
                self.assertEqual(listed["tool"], "repo_memory_list")
                self.assertEqual(listed["notes"][0]["path"], "src/auth/session.py")
                self.assertEqual(listed["notes"][0]["scope"], "file")

                delete_output = StringIO()
                with redirect_stdout(delete_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_delete", "--id", str(added["memory"]["id"]), "--json"]),
                        0,
                    )
                deleted = json.loads(delete_output.getvalue())
                self.assertEqual(deleted["tool"], "repo_memory_delete")
                self.assertTrue(deleted["deleted"])

                empty_output = StringIO()
                with redirect_stdout(empty_output):
                    self.assertEqual(
                        main(["tool", "repo_file_notes", "--path", "src/auth/session.py", "--json"]),
                        0,
                    )
                empty_notes = json.loads(empty_output.getvalue())
                self.assertEqual(empty_notes["notes"], [])
            finally:
                os.chdir(previous)

    def test_tool_repo_reading_plan_uses_memory_tags_feedback_and_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(
                    main(
                        [
                            "tool",
                            "repo_memory_add",
                            "--path",
                            "src/auth/session.py",
                            "--topic",
                            "login session",
                            "--query",
                            "debug login session",
                            "--note",
                            "Session validation lives here.",
                            "--tag",
                            "login_session",
                            "--json",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "tool",
                            "repo_feedback_add",
                            "--query",
                            "debug login session",
                            "--path",
                            "README.md",
                            "--rating",
                            "noisy",
                            "--reason",
                            "verified docs-only for this task",
                            "--json",
                        ]
                    ),
                    0,
                )
                session = root / "src" / "auth" / "session.py"
                session.write_text(session.read_text(encoding="utf-8") + "\nSESSION_TIMEOUT = 60\n", encoding="utf-8")
                self.assertEqual(main(["map"]), 0)

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["tool", "repo_reading_plan", "--query", "debug login session", "--read", "1", "--json"]),
                        0,
                    )
                data = json.loads(output.getvalue())
                self.assertEqual(data["tool"], "repo_reading_plan")
                self.assertIsInstance(data["id"], int)
                self.assertEqual(data["read_budget"], 1)
                by_path = {item["path"]: item for item in data["plan_items"]}
                self.assertIn("src/auth/session.py", by_path)
                self.assertEqual(by_path["src/auth/session.py"]["action"], "verify_stale")
                self.assertEqual(by_path["src/auth/session.py"]["read_priority"], "read_now")
                self.assertEqual(by_path["src/auth/session.py"]["read_budget_rank"], 1)
                self.assertIn("memory", by_path["src/auth/session.py"]["sources"])
                self.assertIn("login", by_path["src/auth/session.py"]["tags"])
                self.assertTrue(by_path["src/auth/session.py"]["memory"][0]["stale"])
                self.assertTrue(data["recommended_actions"])

                read_output = StringIO()
                with redirect_stdout(read_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_reading_plan_read",
                                "--id",
                                str(data["id"]),
                                "--path",
                                "src/auth/session.py",
                                "--note",
                                "opened stale session file",
                                "--json",
                            ]
                        ),
                        0,
                    )
                read_data = json.loads(read_output.getvalue())
                self.assertEqual(read_data["tool"], "repo_reading_plan_read")
                self.assertTrue(read_data["updated"])
                self.assertEqual(read_data["events"][0]["event"], "opened")

                diff_output = StringIO()
                with redirect_stdout(diff_output):
                    self.assertEqual(main(["tool", "repo_reading_plan_diff", "--id", str(data["id"]), "--json"]), 0)
                diff = json.loads(diff_output.getvalue())
                self.assertEqual(diff["tool"], "repo_reading_plan_diff")
                self.assertIn("src/auth/session.py", diff["diff"]["read_paths"])
                self.assertIn("src/auth/session.py", diff["diff"]["read_without_outcome"])

                finish_output = StringIO()
                with redirect_stdout(finish_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_reading_plan_finish",
                                "--id",
                                str(data["id"]),
                                "--read",
                                "src/auth/session.py",
                                "--verified",
                                "src/auth/session.py",
                                "--useful",
                                "src/auth/session.py",
                                "--summary",
                                "verified session path",
                                "--json",
                            ]
                        ),
                        0,
                    )
                finished = json.loads(finish_output.getvalue())
                self.assertEqual(finished["tool"], "repo_reading_plan_finish")
                self.assertTrue(finished["updated"])
                self.assertEqual(len(finished["feedback"]), 1)
                self.assertEqual(finished["feedback"][0]["rating"], "useful")
                self.assertTrue(finished["suggested_memory"])

                post_finish_diff_output = StringIO()
                with redirect_stdout(post_finish_diff_output):
                    self.assertEqual(main(["tool", "repo_reading_plan_diff", "--id", str(data["id"]), "--json"]), 0)
                post_finish_diff = json.loads(post_finish_diff_output.getvalue())
                self.assertNotIn("src/auth/session.py", post_finish_diff["diff"]["read_without_outcome"])

                stats_output = StringIO()
                with redirect_stdout(stats_output):
                    self.assertEqual(main(["tool", "repo_reading_plan_stats", "--json"]), 0)
                stats = json.loads(stats_output.getvalue())
                self.assertEqual(stats["tool"], "repo_reading_plan_stats")
                self.assertEqual(stats["stats"]["plan_count"], 1)
                self.assertEqual(stats["stats"]["finished_plan_count"], 1)
                self.assertEqual(stats["stats"]["top1_verified_useful_rate"], 1.0)

                close_output = StringIO()
                with redirect_stdout(close_output):
                    self.assertEqual(main(["tool", "repo_session_close", "--json"]), 0)
                close = json.loads(close_output.getvalue())
                self.assertEqual(close["plan_activity"]["finished_plans"][0]["id"], data["id"])
                self.assertTrue(close["suggested_memory"])

                flow_output = StringIO()
                with redirect_stdout(flow_output):
                    self.assertEqual(main(["tool", "repo_flow_topics", "--tag", "login", "--json"]), 0)
                flows = json.loads(flow_output.getvalue())
                self.assertEqual(flows["tool"], "repo_flow_topics")
                self.assertTrue(flows["flows"]["flows"])
            finally:
                os.chdir(previous)

    def test_tool_repo_memory_supports_repo_scope_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                add_output = StringIO()
                with redirect_stdout(add_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_memory_add",
                                "--scope",
                                "repo",
                                "--topic",
                                "architecture",
                                "--query",
                                "start project from zero",
                                "--note",
                                "Use a local-only CLI with SQLite storage and no runtime dependencies.",
                                "--evidence",
                                "user_decision",
                                "--json",
                            ]
                        ),
                        0,
                    )
                added = json.loads(add_output.getvalue())
                self.assertTrue(added["recorded"])
                self.assertEqual(added["memory"]["scope"], "repo")
                self.assertEqual(added["memory"]["path"], "")
                self.assertIsNone(added["memory"]["stale"])
                self.assertEqual(added["memory"]["stale_reason"], "not applicable for repo-scoped memory")

                list_output = StringIO()
                with redirect_stdout(list_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_list", "--scope", "repo", "--json"]),
                        0,
                    )
                listed = json.loads(list_output.getvalue())
                self.assertEqual(listed["notes"][0]["scope"], "repo")
                self.assertEqual(listed["notes"][0]["evidence"], "user_decision")

                search_output = StringIO()
                with redirect_stdout(search_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_search", "--query", "local sqlite architecture", "--json"]),
                        0,
                    )
                searched = json.loads(search_output.getvalue())
                self.assertEqual(searched["memory"]["matches"][0]["scope"], "repo")
            finally:
                os.chdir(previous)

    def test_tool_repo_memory_audit_reports_quality_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                for note in ("One.", "Two."):
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
                                    note,
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
                                "repo_memory_add",
                                "--scope",
                                "repo",
                                "--note",
                                "tiny",
                                "--json",
                            ]
                        ),
                        0,
                    )
                audit_output = StringIO()
                with redirect_stdout(audit_output):
                    self.assertEqual(main(["tool", "repo_memory_audit", "--json"]), 0)
                audit = json.loads(audit_output.getvalue())
                self.assertEqual(audit["audit"]["summary"]["short_note"], 3)
                self.assertEqual(audit["audit"]["summary"]["missing_topic"], 1)
                self.assertEqual(audit["audit"]["summary"]["duplicate_file_topic"], 1)
                duplicate = audit["audit"]["issues"]["duplicate_file_topic"][0]
                self.assertEqual(duplicate["path"], "src/auth/session.py")
                self.assertEqual(duplicate["note_count"], 2)
            finally:
                os.chdir(previous)

    def test_tool_repo_task_lifecycle_and_session_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                add_output = StringIO()
                with redirect_stdout(add_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_task_add",
                                "--title",
                                "Fix login redirect",
                                "--topic",
                                "auth",
                                "--summary",
                                "Track the login redirect investigation.",
                                "--file",
                                "src/auth/session.py",
                                "--status",
                                "in_progress",
                                "--json",
                            ]
                        ),
                        0,
                    )
                added = json.loads(add_output.getvalue())
                self.assertEqual(added["tool"], "repo_task_add")
                self.assertTrue(added["recorded"])
                task_id = added["task"]["id"]
                self.assertEqual(added["task"]["files"], ["src/auth/session.py"])

                close_before_output = StringIO()
                with redirect_stdout(close_before_output):
                    self.assertEqual(main(["tool", "repo_session_close", "--json"]), 0)
                close_before = json.loads(close_before_output.getvalue())
                self.assertFalse(close_before["close_ready"])
                self.assertEqual(close_before["recent_tasks"][0]["id"], task_id)
                review_task = [item for item in close_before["checklist"] if item["id"] == "review_open_tasks"][0]
                self.assertEqual(review_task["status"], "needed")

                note_output = StringIO()
                with redirect_stdout(note_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_task_note",
                                "--id",
                                str(task_id),
                                "--note",
                                "Verified session validation and recorded the remaining redirect check.",
                                "--file",
                                "src/auth/login.py",
                                "--test",
                                "python -m unittest discover -s tests",
                                "--remaining",
                                "Check redirect behavior manually.",
                                "--json",
                            ]
                        ),
                        0,
                    )
                noted = json.loads(note_output.getvalue())
                self.assertTrue(noted["recorded"])
                self.assertIn("src/auth/login.py", noted["task"]["files"])
                self.assertEqual(noted["task"]["notes"][0]["task_id"], task_id)

                list_output = StringIO()
                with redirect_stdout(list_output):
                    self.assertEqual(main(["tool", "repo_task_list", "--topic", "auth", "--json"]), 0)
                listed = json.loads(list_output.getvalue())
                self.assertEqual(listed["tasks"][0]["id"], task_id)
                self.assertEqual(listed["tasks"][0]["remaining"], ["Check redirect behavior manually."])

                close_output = StringIO()
                with redirect_stdout(close_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_task_close",
                                "--id",
                                str(task_id),
                                "--summary",
                                "Login redirect task completed.",
                                "--test",
                                "python -m unittest discover -s tests",
                                "--json",
                            ]
                        ),
                        0,
                    )
                closed = json.loads(close_output.getvalue())
                self.assertTrue(closed["closed"])
                self.assertEqual(closed["task"]["status"], "done")

                close_after_output = StringIO()
                with redirect_stdout(close_after_output):
                    self.assertEqual(main(["tool", "repo_session_close", "--json"]), 0)
                close_after = json.loads(close_after_output.getvalue())
                review_after = [item for item in close_after["checklist"] if item["id"] == "review_open_tasks"][0]
                self.assertEqual(review_after["status"], "clean")
            finally:
                os.chdir(previous)

    def test_tool_repo_memory_audit_allows_multiple_repo_decisions_per_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = Path.cwd()
            try:
                os.chdir(root)
                for note in (
                    "Use a standard Python src layout for the initial package.",
                    "Keep the command line interface dependency-free while the project is small.",
                ):
                    with redirect_stdout(StringIO()):
                        self.assertEqual(
                            main(
                                [
                                    "tool",
                                    "repo_memory_add",
                                    "--scope",
                                    "repo",
                                    "--topic",
                                    "project_decisions",
                                    "--evidence",
                                    "planning_note",
                                    "--note",
                                    note,
                                    "--json",
                                ]
                            ),
                            0,
                        )
                audit_output = StringIO()
                with redirect_stdout(audit_output):
                    self.assertEqual(main(["tool", "repo_memory_audit", "--json"]), 0)
                audit = json.loads(audit_output.getvalue())
                self.assertEqual(audit["audit"]["summary"]["duplicate_file_topic"], 0)
                self.assertEqual(audit["audit"]["issues"]["duplicate_file_topic"], [])
            finally:
                os.chdir(previous)

    def test_tool_repo_memory_repo_scope_works_before_index_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = Path.cwd()
            try:
                os.chdir(root)
                add_output = StringIO()
                with redirect_stdout(add_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_memory_add",
                                "--scope",
                                "repo",
                                "--topic",
                                "architecture",
                                "--query",
                                "new empty project",
                                "--note",
                                "Start with a local-only PHP prototype and keep dependencies explicit.",
                                "--evidence",
                                "user_decision",
                                "--json",
                            ]
                        ),
                        0,
                    )
                added = json.loads(add_output.getvalue())
                self.assertTrue((root / ".agent" / "graph.sqlite").is_file())
                self.assertTrue(added["recorded"])
                self.assertIn("without file index", " ".join(added["warnings"]))
                self.assertEqual(added["memory"]["scope"], "repo")
                self.assertEqual(added["memory"]["path"], "")
                self.assertIsNone(added["memory"]["stale"])

                search_output = StringIO()
                with redirect_stdout(search_output):
                    self.assertEqual(
                        main(["tool", "repo_memory_search", "--query", "local-only php dependencies", "--json"]),
                        0,
                    )
                searched = json.loads(search_output.getvalue())
                self.assertEqual(searched["memory"]["matches"][0]["scope"], "repo")

                stale_output = StringIO()
                with redirect_stdout(stale_output):
                    self.assertEqual(main(["tool", "repo_memory_list", "--stale", "--json"]), 0)
                stale = json.loads(stale_output.getvalue())
                self.assertEqual(stale["notes"], [])
            finally:
                os.chdir(previous)

    def test_tool_repo_memory_marks_note_stale_after_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                add_output = StringIO()
                with redirect_stdout(add_output):
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
                                "--json",
                            ]
                        ),
                        0,
                    )
                added = json.loads(add_output.getvalue())
                (root / "src" / "auth" / "session.py").write_text(
                    "SESSION_TIMEOUT = 300\n\n"
                    "def validateSession():\n"
                    "    return False\n",
                    encoding="utf-8",
                )
                with redirect_stdout(StringIO()):
                    self.assertEqual(main(["refresh", "--json"]), 0)
                notes_output = StringIO()
                with redirect_stdout(notes_output):
                    self.assertEqual(
                        main(["tool", "repo_file_notes", "--path", "src/auth/session.py", "--json"]),
                        0,
                    )
                notes = json.loads(notes_output.getvalue())
                self.assertTrue(notes["notes"][0]["stale"])
                self.assertEqual(notes["notes"][0]["stale_reason"], "file changed since memory was recorded")
                stale_output = StringIO()
                with redirect_stdout(stale_output):
                    self.assertEqual(main(["tool", "repo_memory_list", "--stale", "--json"]), 0)
                stale_notes = json.loads(stale_output.getvalue())
                self.assertEqual(stale_notes["notes"][0]["path"], "src/auth/session.py")

                update_output = StringIO()
                with redirect_stdout(update_output):
                    self.assertEqual(
                        main(
                            [
                                "tool",
                                "repo_memory_update",
                                "--id",
                                str(added["memory"]["id"]),
                                "--evidence",
                                "read_full_file",
                                "--note",
                                "Session validation changed and was re-read after refresh.",
                                "--json",
                            ]
                        ),
                        0,
                    )
                updated = json.loads(update_output.getvalue())
                self.assertTrue(updated["updated"])
                self.assertFalse(updated["memory"]["stale"])
                self.assertEqual(updated["memory"]["evidence"], "read_full_file")

                refreshed_notes_output = StringIO()
                with redirect_stdout(refreshed_notes_output):
                    self.assertEqual(
                        main(["tool", "repo_file_notes", "--path", "src/auth/session.py", "--json"]),
                        0,
                    )
                refreshed_notes = json.loads(refreshed_notes_output.getvalue())
                self.assertFalse(refreshed_notes["notes"][0]["stale"])
                self.assertEqual(refreshed_notes["notes"][0]["note"], "Session validation changed and was re-read after refresh.")
            finally:
                os.chdir(previous)

    def test_agent_notes_schema_migrates_file_hash_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = root / ".agent"
            agent.mkdir()
            db = agent / "graph.sqlite"
            conn = sqlite3.connect(db)
            try:
                conn.executescript(
                    """
                    CREATE TABLE agent_notes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT NOT NULL,
                        topic TEXT,
                        query TEXT,
                        note TEXT NOT NULL,
                        note_tokens_json TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
            finally:
                conn.close()
            with GraphStore(root) as store:
                store.initialize()
                columns = {row["name"] for row in store.connection.execute("PRAGMA table_info(agent_notes)").fetchall()}
            self.assertIn("file_sha256", columns)
            self.assertIn("evidence", columns)
            self.assertIn("scope", columns)
