from tests.support import *


class McpTests(InitAgentTestCase):
    def test_mcp_initialize_and_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = InitAgentMcpServer(Path(tmp))
            initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertIsNotNone(initialized)
            self.assertEqual(initialized["result"]["serverInfo"]["name"], "init-agent")
            listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            self.assertIsNotNone(listed)
            tool_names = {item["name"] for item in listed["result"]["tools"]}
            self.assertEqual(
                tool_names,
                {
                    "repo_graph_search",
                    "repo_reading_plan",
                    "repo_reading_plan_read",
                    "repo_reading_plan_diff",
                    "repo_reading_plan_finish",
                    "repo_reading_plan_stats",
                    "repo_trace",
                    "repo_entrypoints",
                    "repo_feedback_add",
                    "repo_feedback_explain",
                    "repo_file_notes",
                    "repo_overview",
                    "repo_memory_add",
                    "repo_memory_audit",
                    "repo_memory_delete",
                    "repo_memory_list",
                    "repo_memory_search",
                    "repo_session_close",
                    "repo_session_summary",
                    "repo_memory_topics",
                    "repo_flow_topics",
                    "repo_memory_update",
                    "repo_related_file",
                    "repo_symbol_callers",
                    "repo_task_add",
                    "repo_task_close",
                    "repo_task_list",
                    "repo_task_note",
                    "repo_task_update",
                },
            )

    def test_mcp_initialize_negotiates_supported_protocol_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = InitAgentMcpServer(Path(tmp))
            initialized = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                }
            )
            self.assertIsNotNone(initialized)
            self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")

    def test_mcp_ignores_messages_without_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = InitAgentMcpServer(Path(tmp))
            self.assertIsNone(server.handle({"jsonrpc": "2.0", "result": {"ok": True}}))
            self.assertIsNone(server.handle({"jsonrpc": "2.0", "id": None}))

    def test_mcp_debug_payload_records_error_messages(self) -> None:
        from init_agent.mcp_server import _debug_request_payload

        payload = _debug_request_payload({"jsonrpc": "2.0", "error": {"code": -32602, "message": "bad initialize"}})
        self.assertEqual(payload["error"]["code"], -32602)
        self.assertEqual(payload["error"]["message"], "bad initialize")

    def test_mcp_debug_log_records_start_and_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            debug_log = Path(tmp) / "mcp.log"
            previous_debug = os.environ.get("INIT_AGENT_MCP_DEBUG_LOG")
            os.environ["INIT_AGENT_MCP_DEBUG_LOG"] = str(debug_log)
            try:
                server = InitAgentMcpServer(Path(tmp))
                server._debug("request", {"id": 1, "method": "initialize"})
            finally:
                if previous_debug is None:
                    os.environ.pop("INIT_AGENT_MCP_DEBUG_LOG", None)
                else:
                    os.environ["INIT_AGENT_MCP_DEBUG_LOG"] = previous_debug
            content = debug_log.read_text(encoding="utf-8")
            self.assertIn('"event": "request"', content)
            self.assertIn('"method": "initialize"', content)

    def test_mcp_content_length_framing_round_trips(self) -> None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        body = json.dumps(request, separators=(",", ":")).encode("utf-8")
        framed = b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
        parsed, message_format = _read_message(BytesIO(framed))
        self.assertEqual(parsed, request)
        self.assertEqual(message_format, "content_length")

        output = BytesIO()
        _write_message({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, output)
        raw = output.getvalue()
        header, response_body = raw.split(b"\r\n\r\n", 1)
        self.assertTrue(header.startswith(b"Content-Length: "))
        self.assertEqual(int(header.split(b":", 1)[1].strip()), len(response_body))
        self.assertEqual(json.loads(response_body.decode("utf-8"))["result"]["ok"], True)

    def test_mcp_json_line_framing_round_trips(self) -> None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        parsed, message_format = _read_message(BytesIO(json.dumps(request).encode("utf-8") + b"\n"))
        self.assertEqual(parsed, request)
        self.assertEqual(message_format, "jsonl")

        output = BytesIO()
        _write_message({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}, output, response_format="jsonl")
        self.assertEqual(json.loads(output.getvalue().decode("utf-8"))["result"]["ok"], True)

    def test_mcp_framing_accepts_extra_headers_before_content_length(self) -> None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        body = json.dumps(request, separators=(",", ":")).encode("utf-8")
        framed = (
            b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
            + b"Content-Length: "
            + str(len(body)).encode("ascii")
            + b"\r\n\r\n"
            + body
        )
        parsed, message_format = _read_message(BytesIO(framed))
        self.assertEqual(parsed, request)
        self.assertEqual(message_format, "content_length")

    def test_mcp_tool_call_repo_graph_search_returns_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "repo_graph_search", "arguments": {"query": "login session", "limit": 3}},
                }
            )
            self.assertIsNotNone(response)
            result = response["result"]
            self.assertFalse(result["isError"])
            self.assertEqual(result["structuredContent"]["tool"], "repo_graph_search")
            self.assertIn("src/auth/session.py", result["structuredContent"]["suggested_first_reads"])
            self.assertEqual(result["content"][0]["type"], "text")

    def test_mcp_tool_call_repo_trace_returns_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_trace_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 91,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_trace",
                        "arguments": {"query": "bug frontend h1 titolo auto generato visualizzazione"},
                    },
                }
            )
            self.assertIsNotNone(response)
            result = response["result"]
            self.assertFalse(result["isError"])
            data = result["structuredContent"]
            self.assertEqual(data["tool"], "repo_trace")
            self.assertEqual(data["paths"][0]["target"], "include/page.php")
            self.assertIn("include/page.php", data["suggested_first_reads"])

    def test_mcp_tool_call_repo_entrypoints_returns_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 33,
                    "method": "tools/call",
                    "params": {"name": "repo_entrypoints", "arguments": {"limit": 5}},
                }
            )
            self.assertIsNotNone(response)
            result = response["result"]
            self.assertFalse(result["isError"])
            data = result["structuredContent"]
            self.assertEqual(data["tool"], "repo_entrypoints")
            self.assertTrue(data["entry_points"])
            self.assertIn("pyproject.toml", {item["path"] for item in data["manifests"]})

    def test_mcp_tool_call_repo_feedback_add_and_explain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            added = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 34,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_feedback_add",
                        "arguments": {
                            "query": "login session",
                            "path": "src/internal/state.py",
                            "rating": "missing",
                            "reason": "verified important file absent from first context pack",
                        },
                    },
                }
            )
            explained = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 35,
                    "method": "tools/call",
                    "params": {"name": "repo_feedback_explain", "arguments": {"query": "login session", "include_all": True}},
                }
            )
            self.assertIsNotNone(added)
            self.assertIsNotNone(explained)
            added_data = added["result"]["structuredContent"]
            self.assertEqual(added_data["tool"], "repo_feedback_add")
            self.assertTrue(added_data["recorded"])
            self.assertEqual(added_data["feedback"]["rating"], "missing")
            explained_data = explained["result"]["structuredContent"]
            self.assertEqual(explained_data["tool"], "repo_feedback_explain")
            self.assertEqual(explained_data["feedback"]["query"], "login session")

    def test_mcp_tool_call_repo_reading_plan_finish_stats_and_flow_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            memory_added = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 131,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_memory_add",
                        "arguments": {
                            "path": "src/auth/session.py",
                            "topic": "login session",
                            "query": "debug login session",
                            "note": "Session validation lives here.",
                            "evidence": "read_excerpt",
                            "tags": ["login_session"],
                        },
                    },
                }
            )
            plan = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 132,
                    "method": "tools/call",
                    "params": {"name": "repo_reading_plan", "arguments": {"query": "debug login session", "read_budget": 1}},
                }
            )
            self.assertIsNotNone(memory_added)
            self.assertIsNotNone(plan)
            plan_data = plan["result"]["structuredContent"]
            self.assertEqual(plan_data["tool"], "repo_reading_plan")
            self.assertEqual(plan_data["read_budget"], 1)
            self.assertIsInstance(plan_data["id"], int)
            by_path = {item["path"]: item for item in plan_data["plan_items"]}
            self.assertEqual(by_path["src/auth/session.py"]["read_priority"], "read_now")

            read = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 136,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_reading_plan_read",
                        "arguments": {
                            "id": plan_data["id"],
                            "paths": ["src/auth/session.py"],
                            "note": "opened session file",
                        },
                    },
                }
            )
            diff = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 137,
                    "method": "tools/call",
                    "params": {"name": "repo_reading_plan_diff", "arguments": {"id": plan_data["id"]}},
                }
            )
            self.assertIsNotNone(read)
            self.assertIsNotNone(diff)
            read_data = read["result"]["structuredContent"]
            self.assertEqual(read_data["tool"], "repo_reading_plan_read")
            self.assertTrue(read_data["updated"])
            diff_data = diff["result"]["structuredContent"]
            self.assertEqual(diff_data["tool"], "repo_reading_plan_diff")
            self.assertIn("src/auth/session.py", diff_data["diff"]["read_paths"])

            finished = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 133,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_reading_plan_finish",
                        "arguments": {
                            "id": plan_data["id"],
                            "read": ["src/auth/session.py"],
                            "verified": ["src/auth/session.py"],
                            "useful": ["src/auth/session.py"],
                            "summary": "verified session path",
                        },
                    },
                }
            )
            stats = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 134,
                    "method": "tools/call",
                    "params": {"name": "repo_reading_plan_stats", "arguments": {}},
                }
            )
            flows = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 135,
                    "method": "tools/call",
                    "params": {"name": "repo_flow_topics", "arguments": {"tag": "login"}},
                }
            )
            self.assertIsNotNone(finished)
            self.assertIsNotNone(stats)
            self.assertIsNotNone(flows)
            finished_data = finished["result"]["structuredContent"]
            self.assertEqual(finished_data["tool"], "repo_reading_plan_finish")
            self.assertTrue(finished_data["updated"])
            self.assertEqual(finished_data["feedback"][0]["rating"], "useful")
            stats_data = stats["result"]["structuredContent"]
            self.assertEqual(stats_data["tool"], "repo_reading_plan_stats")
            self.assertEqual(stats_data["stats"]["finished_plan_count"], 1)
            flows_data = flows["result"]["structuredContent"]
            self.assertEqual(flows_data["tool"], "repo_flow_topics")
            self.assertTrue(flows_data["flows"]["flows"])

    def test_mcp_tool_call_repo_memory_add_search_and_file_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            added = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 36,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_memory_add",
                        "arguments": {
                            "path": "src/auth/session.py",
                            "topic": "login session",
                            "query": "debug login session",
                            "note": "Session validation lives here; verified during login redirect debugging.",
                            "evidence": "read_full_file",
                        },
                    },
                }
            )
            searched = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 37,
                    "method": "tools/call",
                    "params": {"name": "repo_memory_search", "arguments": {"query": "login session validation"}},
                }
            )
            notes = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 38,
                    "method": "tools/call",
                    "params": {"name": "repo_file_notes", "arguments": {"path": "src/auth/session.py"}},
                }
            )
            listed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 39,
                    "method": "tools/call",
                    "params": {"name": "repo_memory_list", "arguments": {"topic": "login session"}},
                }
            )
            topics = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 44,
                    "method": "tools/call",
                    "params": {"name": "repo_memory_topics", "arguments": {"topic": "login session"}},
                }
            )
            audit = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 45,
                    "method": "tools/call",
                    "params": {"name": "repo_memory_audit", "arguments": {}},
                }
            )
            summary = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 46,
                    "method": "tools/call",
                    "params": {"name": "repo_session_summary", "arguments": {}},
                }
            )
            closed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 47,
                    "method": "tools/call",
                    "params": {"name": "repo_session_close", "arguments": {}},
                }
            )
            self.assertIsNotNone(added)
            self.assertIsNotNone(searched)
            self.assertIsNotNone(notes)
            self.assertIsNotNone(listed)
            self.assertIsNotNone(topics)
            self.assertIsNotNone(audit)
            self.assertIsNotNone(summary)
            self.assertIsNotNone(closed)
            self.assertTrue(added["result"]["structuredContent"]["recorded"])
            self.assertEqual(added["result"]["structuredContent"]["memory"]["scope"], "file")
            self.assertFalse(added["result"]["structuredContent"]["memory"]["stale"])
            self.assertEqual(added["result"]["structuredContent"]["memory"]["evidence"], "read_full_file")
            self.assertEqual(searched["result"]["structuredContent"]["memory"]["matches"][0]["path"], "src/auth/session.py")
            self.assertFalse(searched["result"]["structuredContent"]["memory"]["matches"][0]["stale"])
            self.assertEqual(notes["result"]["structuredContent"]["notes"][0]["path"], "src/auth/session.py")
            self.assertFalse(notes["result"]["structuredContent"]["notes"][0]["stale"])
            self.assertEqual(listed["result"]["structuredContent"]["notes"][0]["path"], "src/auth/session.py")
            self.assertEqual(topics["result"]["structuredContent"]["memory"]["topics"][0]["topic"], "login session")
            self.assertGreaterEqual(audit["result"]["structuredContent"]["audit"]["note_count"], 1)
            self.assertEqual(summary["result"]["structuredContent"]["tool"], "repo_session_summary")
            self.assertTrue(summary["result"]["structuredContent"]["recent_memory"])
            self.assertEqual(closed["result"]["structuredContent"]["tool"], "repo_session_close")
            self.assertTrue(closed["result"]["structuredContent"]["checklist"])

            repo_added = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 41,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_memory_add",
                        "arguments": {
                            "scope": "repo",
                            "topic": "architecture",
                            "query": "start project from zero",
                            "note": "Use a local-only CLI with SQLite storage and no runtime dependencies.",
                            "evidence": "user_decision",
                        },
                    },
                }
            )
            repo_listed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "tools/call",
                    "params": {"name": "repo_memory_list", "arguments": {"scope": "repo"}},
                }
            )
            self.assertIsNotNone(repo_added)
            self.assertIsNotNone(repo_listed)
            repo_memory = repo_added["result"]["structuredContent"]["memory"]
            self.assertEqual(repo_memory["scope"], "repo")
            self.assertEqual(repo_memory["path"], "")
            self.assertIsNone(repo_memory["stale"])
            self.assertEqual(repo_listed["result"]["structuredContent"]["notes"][0]["scope"], "repo")
            repo_updated = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 43,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_memory_update",
                        "arguments": {
                            "id": repo_memory["id"],
                            "note": "Use a local-only CLI with SQLite storage; refreshed after repo decision review.",
                            "evidence": "planning_note",
                        },
                    },
                }
            )
            self.assertIsNotNone(repo_updated)
            updated_memory = repo_updated["result"]["structuredContent"]["memory"]
            self.assertTrue(repo_updated["result"]["structuredContent"]["updated"])
            self.assertEqual(updated_memory["scope"], "repo")
            self.assertEqual(updated_memory["evidence"], "planning_note")
            self.assertIn("refreshed", updated_memory["note"])

            task_added = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 48,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_task_add",
                        "arguments": {
                            "title": "Track login redirect",
                            "topic": "auth",
                            "summary": "Keep task context across agent sessions.",
                            "files": ["src/auth/session.py"],
                            "status": "in_progress",
                        },
                    },
                }
            )
            self.assertIsNotNone(task_added)
            task_data = task_added["result"]["structuredContent"]
            self.assertEqual(task_data["tool"], "repo_task_add")
            self.assertTrue(task_data["recorded"])
            task_id = task_data["task"]["id"]

            task_noted = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 49,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_task_note",
                        "arguments": {
                            "id": task_id,
                            "note": "Verified the session file and left a redirect smoke check open.",
                            "files": ["src/auth/login.py"],
                            "tests": ["python -m unittest discover -s tests"],
                            "remaining": ["Run redirect smoke check."],
                        },
                    },
                }
            )
            self.assertIsNotNone(task_noted)
            self.assertTrue(task_noted["result"]["structuredContent"]["recorded"])

            tasks_listed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 50,
                    "method": "tools/call",
                    "params": {"name": "repo_task_list", "arguments": {"topic": "auth"}},
                }
            )
            self.assertIsNotNone(tasks_listed)
            self.assertEqual(tasks_listed["result"]["structuredContent"]["tasks"][0]["id"], task_id)

            task_closed = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 51,
                    "method": "tools/call",
                    "params": {
                        "name": "repo_task_close",
                        "arguments": {
                            "id": task_id,
                            "summary": "Task completed.",
                            "tests": ["python -m unittest discover -s tests"],
                        },
                    },
                }
            )
            self.assertIsNotNone(task_closed)
            self.assertTrue(task_closed["result"]["structuredContent"]["closed"])
            self.assertEqual(task_closed["result"]["structuredContent"]["task"]["status"], "done")

            deleted = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 40,
                    "method": "tools/call",
                    "params": {"name": "repo_memory_delete", "arguments": {"id": added["result"]["structuredContent"]["memory"]["id"]}},
                }
            )
            self.assertIsNotNone(deleted)
            self.assertTrue(deleted["result"]["structuredContent"]["deleted"])

    def test_mcp_tools_do_not_auto_initialize_or_refresh_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("def main():\n    return True\n", encoding="utf-8")
            server = InitAgentMcpServer(root)
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "repo_graph_search", "arguments": {"query": "main app"}},
                }
            )
            self.assertIsNotNone(response)
            result = response["result"]["structuredContent"]
            self.assertFalse((root / ".agent").exists())
            self.assertEqual(result["candidate_files"], [])
            self.assertTrue(result["warnings"])

    def test_mcp_tool_call_related_and_callers_are_json_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            _prepare_index(root)
            server = InitAgentMcpServer(root)
            related = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "repo_related_file", "arguments": {"path": "include/functions.php"}},
                }
            )
            callers = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "repo_symbol_callers", "arguments": {"symbol": "buildForm"}},
                }
            )
            self.assertIsNotNone(related)
            self.assertIsNotNone(callers)
            self.assertEqual(related["result"]["structuredContent"]["tool"], "repo_related_file")
            self.assertEqual(callers["result"]["structuredContent"]["tool"], "repo_symbol_callers")
            self.assertIn("index.php", {item["path"] for item in callers["result"]["structuredContent"]["callers"]})

    def test_mcp_unknown_tool_returns_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = InitAgentMcpServer(Path(tmp))
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "not_real", "arguments": {}},
                }
            )
            self.assertIsNotNone(response)
            self.assertTrue(response["result"]["isError"])
            self.assertIn("unknown tool", response["result"]["content"][0]["text"])
