from __future__ import annotations

import os
import json
import argparse
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path

from init_agent.context_builder import build_context_pack
from init_agent.cli import main
from init_agent.doctor import run_doctor
from init_agent.estimate import estimate_tokens
from init_agent.graph_store import GraphStore
from init_agent.language_detector import detect_role
from init_agent.mcp_server import InitAgentMcpServer, _read_message, _write_message
from init_agent.query import related as related_query
from init_agent.refresh import refresh_index
from init_agent.symbol_extractor import extract_symbols_and_relations
from experiments.evaluate import (
    candidate_paths_for_case,
    case_command,
    load_cases,
    measure_indexed_file_read,
    resolve_case_repo,
    scan_reduction_percent,
    strict_failures_for,
    summarize,
)


class InitAgentBaseTests(unittest.TestCase):
    def test_agent_skill_template_documents_core_workflow(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_path = root / "skills" / "init-agent-orientation" / "SKILL.md"
        self.assertTrue(skill_path.exists())
        content = skill_path.read_text(encoding="utf-8")
        self.assertIn("init-agent run --overview", content)
        self.assertIn("init-agent run", content)
        self.assertIn("init-agent symbol", content)
        self.assertIn("init-agent callers", content)
        self.assertIn("init-agent related", content)
        self.assertIn("init-agent feedback add", content)
        self.assertIn("init-agent feedback explain", content)
        self.assertIn("Do not treat the context pack as source of truth", content)

    def test_agent_skill_readme_documents_install_and_shim(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme_path = root / "skills" / "README.md"
        self.assertTrue(readme_path.exists())
        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("init-agent install-skill codex", content)
        self.assertIn("cp -R skills/init-agent-orientation ~/.codex/skills/", content)
        self.assertIn("PYTHONPATH", content)
        self.assertIn("init-agent: command not found", content)
        self.assertIn("Argument expected for the -m option", content)

    def test_main_readme_documents_two_command_codex_install(self) -> None:
        root = Path(__file__).resolve().parents[1]
        content = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Use With Codex", content)
        self.assertIn("pipx install git+https://github.com/alessandroserpe/init-agent.git", content)
        self.assertIn("init-agent mcp install-codex", content)
        self.assertIn("init-agent install-skill codex", content)

    def test_mcp_docs_include_codex_config_and_smoke_test(self) -> None:
        root = Path(__file__).resolve().parents[1]
        content = (root / "docs" / "mcp.md").read_text(encoding="utf-8")
        self.assertIn("codex mcp add", content)
        self.assertIn("--manual-config --experimental", content)
        self.assertIn("Content-Length", content)
        self.assertIn("tools/list", content)
        self.assertIn("repo_graph_search", content)

    def test_mcp_install_codex_uses_codex_cli_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            log_path = Path(tmp) / "codex_args.json"
            fake_codex = _fake_codex(Path(tmp), log_path)

            output = StringIO()
            previous_codex_home = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = str(codex_home)
            try:
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["mcp", "install-codex", "--codex-command", str(fake_codex), "--json"]),
                        0,
                    )
            finally:
                if previous_codex_home is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = previous_codex_home

            data = json.loads(output.getvalue())
            self.assertTrue(data["installed"])
            self.assertEqual(data["method"], "codex_cli")
            self.assertEqual(data["root_mode"], "dynamic")
            self.assertIsNone(data["root"])
            self.assertEqual(data["timeout_patch"]["status"], "updated")
            args = json.loads(log_path.read_text(encoding="utf-8"))[-1]
            self.assertEqual(args[:4], ["mcp", "add", "init_agent", "--"])
            self.assertEqual(len(args), 5)
            self.assertNotIn("--root", args)
            config = (codex_home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("startup_timeout_sec = 120", config)
            self.assertIn("tool_timeout_sec = 120", config)

    def test_mcp_install_codex_can_pin_root_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            log_path = Path(tmp) / "codex_args.json"
            fake_codex = _fake_codex(Path(tmp), log_path)

            output = StringIO()
            previous_codex_home = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = str(codex_home)
            try:
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["mcp", "install-codex", "--root", str(root), "--codex-command", str(fake_codex), "--json"]),
                        0,
                    )
            finally:
                if previous_codex_home is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = previous_codex_home

            data = json.loads(output.getvalue())
            self.assertTrue(data["installed"])
            self.assertEqual(data["root_mode"], "pinned")
            self.assertEqual(data["root"], str(root.resolve()))
            args = json.loads(log_path.read_text(encoding="utf-8"))[-1]
            self.assertEqual(args[:4], ["mcp", "add", "init_agent", "--"])
            self.assertEqual(args[-2:], ["--root", str(root.resolve())])

    def test_mcp_uninstall_codex_uses_codex_cli_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "codex_args.json"
            fake_codex = _fake_codex(Path(tmp), log_path)

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["mcp", "uninstall-codex", "--codex-command", str(fake_codex), "--json"]),
                    0,
                )

            data = json.loads(output.getvalue())
            self.assertTrue(data["removed"])
            self.assertEqual(data["method"], "codex_cli")
            args = json.loads(log_path.read_text(encoding="utf-8"))[-1]
            self.assertEqual(args, ["mcp", "remove", "init_agent"])

    def test_mcp_install_codex_appends_config_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            config = Path(tmp) / "config.toml"
            original = 'model = "gpt-5.5"\n\n[mcp_servers.node_repl]\ncommand = "node_repl"\n'
            config.write_text(original, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "mcp",
                            "install-codex",
                            "--root",
                            str(root),
                            "--manual-config",
                            "--config-path",
                            str(config),
                            "--experimental",
                        ]
                    ),
                    0,
                )

            updated = config.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith(original))
            self.assertIn("[mcp_servers.init_agent]", updated)
            self.assertRegex(updated, r'command = ".*init-agent-mcp"')
            self.assertIn(f'args = ["--root", "{root.resolve()}"]', updated)
            self.assertIn("startup_timeout_sec = 120", updated)
            backups = list(config.parent.glob("config.toml.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
            self.assertIn("Restart Codex", output.getvalue())

    def test_mcp_install_codex_json_is_valid_and_does_not_duplicate_existing_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            config = Path(tmp) / "config.toml"
            existing = '[mcp_servers.init_agent]\ncommand = "init-agent-mcp"\nargs = ["--root", "/old"]\n'
            config.write_text(existing, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "mcp",
                            "install-codex",
                            "--root",
                            str(root),
                            "--manual-config",
                            "--config-path",
                            str(config),
                            "--experimental",
                            "--json",
                        ]
                    ),
                    0,
                )

            data = json.loads(output.getvalue())
            self.assertFalse(data["installed"])
            self.assertEqual(data["status"], "exists")
            self.assertEqual(config.read_text(encoding="utf-8"), existing)
            self.assertEqual(list(config.parent.glob("config.toml.bak-*")), [])

    def test_mcp_install_codex_replace_updates_only_existing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            config = Path(tmp) / "config.toml"
            original = (
                'model = "gpt-5.5"\n\n'
                "[mcp_servers.init_agent]\n"
                'command = "init-agent-mcp"\n'
                'args = ["--root", "/old"]\n'
                "startup_timeout_sec = 30\n\n"
                "[mcp_servers.node_repl]\n"
                'command = "node_repl"\n'
            )
            config.write_text(original, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "mcp",
                            "install-codex",
                            "--root",
                            str(root),
                            "--manual-config",
                            "--config-path",
                            str(config),
                            "--replace",
                            "--experimental",
                        ]
                    ),
                    0,
                )

            updated = config.read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5.5"', updated)
            self.assertIn("[mcp_servers.node_repl]", updated)
            self.assertIn(f'args = ["--root", "{root.resolve()}"]', updated)
            self.assertIn("startup_timeout_sec = 120", updated)
            self.assertNotIn('args = ["--root", "/old"]', updated)
            backups = list(config.parent.glob("config.toml.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
            self.assertIn("Status: replaced", output.getvalue())

    def test_mcp_install_codex_manual_config_requires_experimental_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            config = Path(tmp) / "config.toml"
            original = 'model = "gpt-5.5"\n'
            config.write_text(original, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["mcp", "install-codex", "--root", str(root), "--manual-config", "--config-path", str(config), "--json"]),
                    2,
                )

            data = json.loads(output.getvalue())
            self.assertEqual(data["status"], "experimental_required")
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_mcp_uninstall_codex_removes_only_init_agent_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            original = (
                'model = "gpt-5.5"\n\n'
                "[mcp_servers.init_agent]\n"
                'command = "init-agent-mcp"\n'
                'args = ["--root", "/repo"]\n\n'
                "[mcp_servers.node_repl]\n"
                'command = "node_repl"\n'
            )
            config.write_text(original, encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["mcp", "uninstall-codex", "--manual-config", "--config-path", str(config), "--experimental", "--json"]),
                    0,
                )

            data = json.loads(output.getvalue())
            updated = config.read_text(encoding="utf-8")
            self.assertTrue(data["removed"])
            self.assertNotIn("[mcp_servers.init_agent]", updated)
            self.assertIn("[mcp_servers.node_repl]", updated)
            self.assertIn('model = "gpt-5.5"', updated)
            backups = list(config.parent.glob("config.toml.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)

    def test_install_skill_codex_copies_bundled_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["install-skill", "codex", "--target-dir", str(target)]), 0)
            installed = target / "init-agent-orientation" / "SKILL.md"
            self.assertTrue(installed.exists())
            self.assertIn("init-agent run --overview", installed.read_text(encoding="utf-8"))
            self.assertIn("Skill installed", output.getvalue())

    def test_install_skill_codex_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["install-skill", "codex", "--target-dir", str(target), "--json"]), 0)
            data = json.loads(output.getvalue())
            self.assertTrue(data["installed"])
            self.assertEqual(data["skill"], "init-agent-orientation")
            self.assertTrue((target / "init-agent-orientation" / "SKILL.md").exists())

    def test_export_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            _prepare_index(root)
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["map"]), 0)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["export", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["format"], "init-agent.graph.v1")
                self.assertEqual(data["project"]["name"], root.name)
                self.assertGreaterEqual(data["stats"]["files"], 3)
                self.assertGreaterEqual(data["stats"]["symbols"], 2)
                self.assertGreaterEqual(data["stats"]["relations"], 1)
                self.assertIn("files", data)
                self.assertIn("symbols", data)
                self.assertIn("relations", data)
                self.assertIn("git_commits", data)
                self.assertIn("feedback", data)
                self.assertIn("runs", data)
            finally:
                os.chdir(previous)

    def test_export_does_not_include_source_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            secret = "super_secret_source_literal"
            (root / "src" / "auth" / "secret.py").write_text(
                f"def hidden():\n    return '{secret}'\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["map"]), 0)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["export", "--json"]), 0)
                raw = output.getvalue()
                self.assertNotIn(secret, raw)
                data = json.loads(raw)
                paths = {item["path"] for item in data["files"]}
                self.assertIn("src/auth/secret.py", paths)
            finally:
                os.chdir(previous)

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
            finally:
                os.chdir(previous)

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
                    "repo_entrypoints",
                    "repo_feedback_add",
                    "repo_feedback_explain",
                    "repo_overview",
                    "repo_related_file",
                    "repo_symbol_callers",
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

    def test_experiment_cases_manifest_is_valid(self) -> None:
        cases_path = Path(__file__).resolve().parents[1] / "experiments" / "cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertGreater(len(cases), 0)
        for case in cases:
            self.assertIn("name", case)
            self.assertIn("repo", case)
            self.assertIn("query", case)
            self.assertIsInstance(case.get("expected_files"), list)
            self.assertIsInstance(case.get("noise_patterns"), list)

    def test_experiment_case_filter_loads_selected_case(self) -> None:
        cases = load_cases(["django-auth-session-middleware"])
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["name"], "django-auth-session-middleware")

    def test_experiment_case_filter_loads_overview_case(self) -> None:
        cases = load_cases(["init-agent-repository-overview"])
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["command"], "overview")

    def test_experiment_init_agent_case_falls_back_to_current_checkout(self) -> None:
        case = {
            "name": "init-agent-repository-overview",
            "repo": "/tmp/init-agent-bench-does-not-exist",
            "query": "repository overview",
        }
        self.assertEqual(resolve_case_repo(case), Path(__file__).resolve().parents[1])

    def test_experiment_case_filter_rejects_unknown_case(self) -> None:
        with self.assertRaises(SystemExit):
            load_cases(["not-a-real-benchmark-case"])

    def test_experiment_overview_case_uses_overview_candidates(self) -> None:
        case = {"command": "overview"}
        command = case_command(case)
        self.assertIn("--overview", command)
        paths = candidate_paths_for_case(
            case,
            {
                "overview": {
                    "suggested_first_reads": [{"path": "pyproject.toml"}],
                    "entry_points": [{"path": "src/app/cli.py"}],
                    "manifests": [{"path": "README.md"}],
                }
            },
        )
        self.assertEqual(paths, ["pyproject.toml", "src/app/cli.py", "README.md"])

    def test_scan_reduction_percent(self) -> None:
        self.assertEqual(scan_reduction_percent(100, 10), 90.0)
        self.assertEqual(scan_reduction_percent(3, 10), 0.0)
        self.assertIsNone(scan_reduction_percent(0, 10))
        self.assertIsNone(scan_reduction_percent(None, 10))

    def test_measure_indexed_file_read_uses_indexed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def app():\n    return 'ok'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                measurement = measure_indexed_file_read(root)
            finally:
                os.chdir(previous)
        self.assertIsNotNone(measurement)
        assert measurement is not None
        self.assertGreaterEqual(measurement["files"], 2)
        self.assertGreater(measurement["characters"], 0)
        self.assertGreaterEqual(measurement["elapsed_seconds"], 0.0)

    def test_experiment_summary_and_strict_thresholds(self) -> None:
        summary = summarize(
            [
                {
                    "status": "ok",
                    "top1_hit": True,
                    "top3_hit": True,
                    "top5_hit": True,
                    "noise_hit_count": 0,
                    "elapsed_seconds": 1.0,
                    "manual_scan_reduction_percent": 90.0,
                    "manual_scan_elapsed_seconds": 4.0,
                },
                {
                    "status": "ok",
                    "top1_hit": False,
                    "top3_hit": False,
                    "top5_hit": True,
                    "noise_hit_count": 1,
                    "elapsed_seconds": 2.0,
                    "manual_scan_reduction_percent": 80.0,
                    "manual_scan_elapsed_seconds": 6.0,
                },
            ]
        )
        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["top3_rate"], 0.5)
        self.assertEqual(summary["top5_rate"], 1.0)
        self.assertEqual(summary["average_manual_scan_reduction_percent"], 85.0)
        self.assertEqual(summary["average_manual_scan_elapsed_seconds"], 5.0)
        args = argparse.Namespace(min_top3_rate=0.85, min_top5_rate=1.0, max_noise=2)
        failures = strict_failures_for(summary, args)
        self.assertIn("top3_rate 0.5 < 0.85", failures)
        self.assertNotIn("top5_rate 1.0 < 1.0", failures)

    def test_role_detection_does_not_treat_pytest_package_as_test(self) -> None:
        self.assertEqual(detect_role("src/_pytest/fixtures.py"), "source")
        self.assertEqual(detect_role("testing/python/fixtures.py"), "test")
        self.assertEqual(detect_role("src/pkg/test_example.py"), "test")
        self.assertEqual(detect_role("src/pkg/component.spec.ts"), "test")

    def test_python_symbol_extraction(self) -> None:
        content = "import os\nfrom pathlib import Path\nclass Runner:\n    pass\ndef run(value):\n    return value\n"
        symbols, relations = extract_symbols_and_relations(content, "python")
        self.assertIn(("Runner", "class"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("run", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("os", [item.target for item in relations])
        self.assertIn("pathlib", [item.target for item in relations])

    def test_python_multiline_function_signature_extraction(self) -> None:
        content = "class Session:\n    def resolve_redirects(\n        self,\n        response,\n    ):\n        return []\n"
        symbols, _ = extract_symbols_and_relations(content, "python")
        self.assertIn(("Session", "class"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("resolve_redirects", "method"), [(item.name, item.kind) for item in symbols])

    def test_go_symbol_extraction(self) -> None:
        content = 'package main\nimport (\n  "net/http"\n)\ntype Engine struct {}\nfunc (e *Engine) ServeHTTP() {}\nfunc New() {}\n'
        symbols, relations = extract_symbols_and_relations(content, "go")
        self.assertIn(("Engine", "struct"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("ServeHTTP", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("New", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("net/http", [item.target for item in relations])

    def test_rust_symbol_extraction(self) -> None:
        content = "use tokio::net::TcpListener;\nstruct Listener {}\nimpl Listener {}\npub async fn run() {}\n"
        symbols, relations = extract_symbols_and_relations(content, "rust")
        self.assertIn(("Listener", "struct"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("Listener", "impl"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("run", "function"), [(item.name, item.kind) for item in symbols])
        self.assertIn("tokio", [item.target for item in relations])

    def test_markdown_heading_and_readme_command_extraction(self) -> None:
        content = "# Project\n\n## Install\n\n```bash\npython3 -m pip install -e .\ninit-agent run login\n```\n"
        symbols, relations = extract_symbols_and_relations(content, "markdown", "README.md")
        pairs = {(item.name, item.kind) for item in symbols}
        self.assertIn(("Project", "heading"), pairs)
        self.assertIn(("Install", "heading"), pairs)
        self.assertIn(("python3 -m pip install -e .", "command_example"), pairs)
        self.assertIn(("init-agent run login", "command_example"), pairs)
        self.assertEqual(relations, [])

    def test_non_readme_markdown_only_extracts_headings(self) -> None:
        content = "# Guide\n\n```bash\nmake publish\n```\n"
        symbols, _ = extract_symbols_and_relations(content, "markdown", "docs/guide.md")
        pairs = {(item.name, item.kind) for item in symbols}
        self.assertIn(("Guide", "heading"), pairs)
        self.assertNotIn(("make publish", "command_example"), pairs)

    def test_json_toml_yaml_config_symbol_extraction(self) -> None:
        json_symbols, _ = extract_symbols_and_relations(
            '{"name": "demo", "scripts": {"test": "pytest", "build": "vite build"}}',
            "json",
            "package.json",
        )
        self.assertIn(("name", "config_key"), [(item.name, item.kind) for item in json_symbols])
        self.assertIn(("test", "package_script"), [(item.name, item.kind) for item in json_symbols])
        self.assertIn(("build", "package_script"), [(item.name, item.kind) for item in json_symbols])

        toml_symbols, _ = extract_symbols_and_relations(
            "[project]\nname = 'demo'\n[project.scripts]\ndemo = 'demo.cli:main'\n[tool.demo]\nflag = true\n",
            "toml",
            "pyproject.toml",
        )
        self.assertIn(("project", "config_key"), [(item.name, item.kind) for item in toml_symbols])
        self.assertIn(("tool", "config_key"), [(item.name, item.kind) for item in toml_symbols])
        self.assertIn(("demo", "project_script"), [(item.name, item.kind) for item in toml_symbols])

        yaml_symbols, _ = extract_symbols_and_relations("name: demo\nservices:\n  web: {}\n", "yaml", "compose.yaml")
        self.assertIn(("name", "config_key"), [(item.name, item.kind) for item in yaml_symbols])
        self.assertIn(("services", "config_key"), [(item.name, item.kind) for item in yaml_symbols])

    def test_php_route_extraction(self) -> None:
        content = (
            "<?php\n"
            "Route::get('/login', 'AuthController@login');\n"
            "$router->post('/sessions', 'SessionController@store');\n"
            "$routes = ['/admin' => 'AdminController@index'];\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "php")
        self.assertIn(("/login", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/admin", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("login", handlers)
        self.assertIn("store", handlers)
        self.assertIn("index", handlers)

    def test_js_express_and_fastify_route_extraction(self) -> None:
        content = (
            "function showUser(req, res) {}\n"
            "app.get('/users/:id', showUser)\n"
            "fastify.route({\n"
            "  method: 'POST',\n"
            "  url: '/sessions',\n"
            "  handler: createSession\n"
            "})\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "javascript")
        self.assertIn(("/users/:id", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("showUser", handlers)
        self.assertIn("createSession", handlers)

    def test_python_flask_and_django_route_extraction(self) -> None:
        content = (
            "@app.route('/login')\n"
            "def login_view():\n"
            "    return 'ok'\n"
            "@bp.post('/sessions')\n"
            "def create_session():\n"
            "    return 'ok'\n"
            "urlpatterns = [\n"
            "    path('admin/', views.admin_dashboard),\n"
            "]\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "python")
        self.assertIn(("/login", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/admin", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("login_view", handlers)
        self.assertIn("create_session", handlers)
        self.assertIn("admin_dashboard", handlers)

    def test_go_gin_route_extraction(self) -> None:
        content = 'package main\nfunc setup(r *gin.Engine) {\n  r.GET("/users/:id", getUser)\n  authorized.POST("/sessions", auth.CreateSession)\n}\n'
        symbols, relations = extract_symbols_and_relations(content, "go")
        self.assertIn(("/users/:id", "route"), [(item.name, item.kind) for item in symbols])
        self.assertIn(("/sessions", "route"), [(item.name, item.kind) for item in symbols])
        handlers = [item.target for item in relations if item.relation == "route_to_handler"]
        self.assertIn("getUser", handlers)
        self.assertIn("CreateSession", handlers)

    def test_php_function_call_relation_extraction(self) -> None:
        content = (
            "<?php\n"
            "require_once 'functions.php';\n"
            "function pageController() { return renderDashboard(); }\n"
            "$result = buildForm($record);\n"
            "if (isset($result)) { echo sanitizeOutput(trim($result)); }\n"
            "$rows = mysqli_num_rows($query);\n"
            "$json = json_decode(file_get_contents($path), true);\n"
            "$service->methodCall();\n"
            "ClassName::staticCall();\n"
        )
        symbols, relations = extract_symbols_and_relations(content, "php")
        self.assertIn(("pageController", "function"), [(item.name, item.kind) for item in symbols])
        calls = [item.target for item in relations if item.relation == "calls"]
        self.assertIn("renderDashboard", calls)
        self.assertIn("buildForm", calls)
        self.assertIn("sanitizeOutput", calls)
        self.assertNotIn("isset", calls)
        self.assertNotIn("trim", calls)
        self.assertNotIn("mysqli_num_rows", calls)
        self.assertNotIn("json_decode", calls)
        self.assertNotIn("file_get_contents", calls)
        self.assertNotIn("methodCall", calls)
        self.assertNotIn("staticCall", calls)

    def test_cli_init_and_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("class App:\n    pass\n\ndef main():\n    return App()\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(main(["init"]), 0)
                self.assertEqual(main(["map"]), 0)
                with GraphStore(root) as store:
                    counts = store.counts()
                    term_count = store.connection.execute("SELECT COUNT(*) AS count FROM term_stats").fetchone()["count"]
                self.assertGreaterEqual(counts["files"], 2)
                self.assertGreaterEqual(counts["symbols"], 2)
                self.assertGreaterEqual(counts["relations"], 2)
                self.assertGreater(term_count, 0)
            finally:
                os.chdir(previous)

    def test_map_indexes_documentation_and_config_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\n## Quick Start\n\n```bash\ninit-agent run login\n```\n", encoding="utf-8")
            (root / "package.json").write_text('{"name": "demo", "scripts": {"test": "node test.js"}}\n', encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n[project.scripts]\ndemo = 'demo.cli:main'\n", encoding="utf-8")
            (root / "compose.yaml").write_text("services:\n  web: {}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    rows = {
                        (row["name"], row["kind"], row["path"])
                        for row in store.connection.execute(
                            """
                            SELECT s.name, s.kind, f.path
                            FROM symbols s
                            JOIN files f ON f.id = s.file_id
                            """
                        ).fetchall()
                    }
                self.assertIn(("Quick Start", "heading", "README.md"), rows)
                self.assertIn(("init-agent run login", "command_example", "README.md"), rows)
                self.assertIn(("test", "package_script", "package.json"), rows)
                self.assertIn(("demo", "project_script", "pyproject.toml"), rows)
                self.assertIn(("services", "config_key", "compose.yaml"), rows)
            finally:
                os.chdir(previous)

    def test_map_indexes_route_symbols_and_handler_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
            (root / "server.js").write_text("function showUser(req, res) {}\napp.get('/users/:id', showUser)\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    symbols = {
                        (row["name"], row["kind"])
                        for row in store.connection.execute("SELECT name, kind FROM symbols").fetchall()
                    }
                    relations = {
                        (row["relation"], row["target_type"], row["target_id"])
                        for row in store.connection.execute("SELECT relation, target_type, target_id FROM relations").fetchall()
                    }
                self.assertIn(("/users/:id", "route"), symbols)
                self.assertIn(("route_to_handler", "symbol_name", "showUser"), relations)
            finally:
                os.chdir(previous)

    def test_term_stats_downweight_common_repo_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            include = root / "include"
            include.mkdir()
            (include / "login.php").write_text("<?php\nfunction loginUser() { return true; }\n", encoding="utf-8")
            for index in range(8):
                (include / f"admin_{index}.php").write_text(
                    f"<?php\nfunction adminHelper{index}() {{ return true; }}\n",
                    encoding="utf-8",
                )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    rows = {
                        row["term"]: row["weight"]
                        for row in store.connection.execute(
                            "SELECT term, weight FROM term_stats WHERE source = 'all' AND term IN ('admin', 'login')"
                        ).fetchall()
                    }
                self.assertLess(rows["admin"], rows["login"])
                pack = build_context_pack(root, "login admin")
                self.assertEqual(pack["candidate_files"][0]["path"], "include/login.php")
            finally:
                os.chdir(previous)

    def test_query_returns_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "service.py").write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                self.assertEqual(main(["query", "calculate"]), 0)
            finally:
                os.chdir(previous)

    def test_context_command_base_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "fix login session bug"]), 0)
                rendered = output.getvalue()
                self.assertIn("Context pack for: fix login session bug", rendered)
                self.assertIn("src/auth/login.py", rendered)
                self.assertIn("Related symbols:", rendered)
            finally:
                os.chdir(previous)

    def test_context_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "fix login session bug", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "fix login session bug")
                self.assertIn("candidate_files", data)
                self.assertIn("suggested_first_reads", data)
                self.assertIn("related_symbols", data)
                self.assertIn("recent_commits", data)
            finally:
                os.chdir(previous)

    def test_context_scoring_prefers_path_symbol_and_commit_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                with GraphStore(root) as store:
                    store.replace_git_history(
                        [
                            {
                                "hash": "abc123456789",
                                "author": "Test",
                                "date": "2026-01-01T00:00:00+00:00",
                                "message": "fix login session bug",
                                "files": ["src/auth/login.py", "src/auth/session.py"],
                            }
                        ]
                )
                pack = build_context_pack(root, "fix login session bug")
                self.assertLessEqual(len(pack["candidate_files"]), 10)
                self.assertLessEqual(len(pack["related_symbols"]), 10)
                self.assertLessEqual(len(pack["recent_commits"]), 5)
                by_path = {item["path"]: item for item in pack["candidate_files"]}
                self.assertIn("src/auth/login.py", by_path)
                self.assertIn("src/auth/session.py", by_path)
                login = by_path["src/auth/login.py"]
                self.assertIn('path matches "login"', login["reasons"])
                self.assertIn('symbol matches "login"', login["reasons"])
                self.assertIn('commit message matches "fix"', login["reasons"])
            finally:
                os.chdir(previous)

    def test_context_deprioritizes_tests_for_non_test_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_scoring_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "context scoring symbols")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("init_agent/context_builder.py", paths)
                self.assertIn("tests/test_base.py", paths)
                self.assertLess(paths.index("init_agent/context_builder.py"), paths.index("tests/test_base.py"))
                test_item = next(item for item in pack["candidate_files"] if item["path"] == "tests/test_base.py")
                self.assertIn("test file deprioritized for non-test query", test_item["reasons"])
            finally:
                os.chdir(previous)

    def test_context_keeps_tests_for_test_aware_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_scoring_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "test context scoring")
                self.assertEqual(pack["candidate_files"][0]["path"], "tests/test_base.py")
                self.assertIn("test-aware query", pack["candidate_files"][0]["reasons"])
            finally:
                os.chdir(previous)

    def test_context_php_login_path_beats_common_admin_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_admin_commit_noise(root)
                pack = build_context_pack(root, "login sessione admin")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("include/login.php", paths)
                self.assertIn("include/crm.php", paths)
                self.assertIn("include/core/organization.php", paths)
                self.assertIn("css/login.css", paths)
                self.assertIn("install/migrations/2026-06-16-admin-role-permissions.sql", paths)
                self.assertLess(paths.index("include/login.php"), paths.index("include/crm.php"))
                self.assertLess(paths.index("include/login.php"), paths.index("include/core/organization.php"))
                self.assertLess(paths.index("include/login.php"), paths.index("css/login.css"))
                self.assertLess(paths.index("include/login.php"), paths.index("install/migrations/2026-06-16-admin-role-permissions.sql"))
            finally:
                os.chdir(previous)

    def test_context_css_login_does_not_penalize_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "css login")
                paths = [item["path"] for item in pack["candidate_files"][:3]]
                self.assertIn("css/login.css", paths)
                css_file = next(item for item in pack["candidate_files"] if item["path"] == "css/login.css")
                self.assertNotIn("asset file deprioritized for non-UI query", css_file["reasons"])
            finally:
                os.chdir(previous)

    def test_context_migration_intent_does_not_penalize_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "migration admin permissions")
                migration = next(
                    item
                    for item in pack["candidate_files"]
                    if item["path"] == "install/migrations/2026-06-16-admin-role-permissions.sql"
                )
                self.assertNotIn("migration file deprioritized for non-database query", migration["reasons"])
            finally:
                os.chdir(previous)

    def test_context_common_token_does_not_dominate_rare_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_admin_commit_noise(root)
                pack = build_context_pack(root, "login sessione admin")
                login = next(item for item in pack["candidate_files"] if item["path"] == "include/login.php")
                crm = next(item for item in pack["candidate_files"] if item["path"] == "include/crm.php")
                self.assertGreater(login["score"], crm["score"])
                self.assertTrue(any('specific token "login" boosted' == reason for reason in login["reasons"]))
                self.assertTrue(any('common token "admin" downweighted' == reason for reason in crm["reasons"]))
            finally:
                os.chdir(previous)

    def test_context_relation_boost_does_not_beat_direct_path_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "login admin")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(paths.index("include/login.php"), paths.index("include/crmFunction.php"))
                crm_function = next(item for item in pack["candidate_files"] if item["path"] == "include/crmFunction.php")
                related_reasons = [reason for reason in crm_function["reasons"] if reason.startswith("related to ")]
                self.assertLessEqual(len(related_reasons), 5)
            finally:
                os.chdir(previous)

    def test_context_php_login_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_login_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "login sessione admin", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login sessione admin")
                self.assertEqual(data["candidate_files"][0]["path"], "include/login.php")
            finally:
                os.chdir(previous)

    def test_context_php_call_relation_finds_caller_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "buildForm")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("index.php", paths)
                self.assertIn("include/functions.php", paths)
                index_item = next(item for item in pack["candidate_files"] if item["path"] == "index.php")
                self.assertIn('calls "buildForm"', index_item["reasons"])
            finally:
                os.chdir(previous)

    def test_related_php_call_relation_resolves_definition_and_callers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                index_related = related_query(root, "index.php")
                self.assertIsNotNone(index_related)
                raw_relation_names = {item["relation"] for item in index_related["relations"]}
                self.assertNotIn("calls", raw_relation_names)
                self.assertNotIn("defines", raw_relation_names)
                resolved = index_related["resolved_calls"]
                crea_form = next(item for item in resolved if item["name"] == "buildForm")
                self.assertEqual(crea_form["definitions"][0]["path"], "include/functions.php")

                functions_related = related_query(root, "include/functions.php")
                self.assertIsNotNone(functions_related)
                callers = {(item["path"], item["name"]) for item in functions_related["callers"]}
                self.assertIn(("index.php", "buildForm"), callers)
                index_caller = next(item for item in functions_related["callers"] if item["path"] == "index.php" and item["name"] == "buildForm")
                self.assertEqual(index_caller["call_count"], 1)
                self.assertEqual(index_caller["first_line"], 3)
            finally:
                os.chdir(previous)

    def test_callers_command_shows_php_callers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["callers", "buildForm"]), 0)
                rendered = output.getvalue()
                self.assertIn("Symbol: buildForm", rendered)
                self.assertIn("function include/functions.php:2", rendered)
                self.assertIn("index.php:3 calls buildForm (1x)", rendered)
            finally:
                os.chdir(previous)

    def test_symbol_command_shows_definitions_callers_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["symbol", "buildForm"]), 0)
                rendered = output.getvalue()
                self.assertIn("Symbol: buildForm", rendered)
                self.assertIn("Definitions:", rendered)
                self.assertIn("function include/functions.php:2", rendered)
                self.assertIn("Callers:", rendered)
                self.assertIn("index.php:3 calls buildForm (1x)", rendered)
                self.assertIn("Candidate files:", rendered)
                self.assertIn("include/functions.php", rendered)
                self.assertIn("Recent commits:", rendered)
            finally:
                os.chdir(previous)

    def test_context_soft_path_match_finds_installazione(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            install = root / "install"
            include = root / "include"
            install.mkdir()
            include.mkdir()
            (install / "index.php").write_text("<?php\nfunction runInstaller() { return true; }\n", encoding="utf-8")
            (install / "README.md").write_text("# Install\nOpen /install/ in the browser.\n", encoding="utf-8")
            (include / "crm.php").write_text("<?php\nfunction crmHome() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "procedura installazione")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("install/index.php", paths)
                self.assertLess(paths.index("install/index.php"), paths.index("include/crm.php") if "include/crm.php" in paths else 99)
                install_item = next(item for item in pack["candidate_files"] if item["path"] == "install/index.php")
                self.assertIn('path softly matches "installazione"', install_item["reasons"])
            finally:
                os.chdir(previous)

    def test_context_natural_italian_installation_query_prefers_install_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            (root / "install").mkdir()
            (root / "include").mkdir()
            (root / "js").mkdir()
            (root / "install" / "index.php").write_text(
                "<?php\nfunction runInstaller() { return true; }\n",
                encoding="utf-8",
            )
            (root / "install" / "schema.sql").write_text("CREATE TABLE settings (id INT);\n", encoding="utf-8")
            (root / "install" / "README.md").write_text("# Install\nOpen /install/ in the browser.\n", encoding="utf-8")
            (root / "include" / "session.php").write_text("<?php\nfunction sessionState() { return true; }\n", encoding="utf-8")
            (root / "include" / "core_modules.php").write_text(
                "<?php\nfunction fileRegistry() { return true; }\nfunction fileMetadata() { return true; }\n",
                encoding="utf-8",
            )
            (root / "js" / "app.footer.js").write_text("function footerReady() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(
                    root,
                    "usando la skill riesci a capire se questa repository ha un file di installazione?",
                )
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertEqual(paths[0], "install/index.php")
                if "include/core_modules.php" in paths:
                    self.assertLess(paths.index("install/index.php"), paths.index("include/core_modules.php"))
                if "js/app.footer.js" in paths:
                    self.assertLess(paths.index("install/index.php"), paths.index("js/app.footer.js"))
                self.assertIn("install/README.md", paths[:5])
            finally:
                os.chdir(previous)

    def test_context_ignores_function_words_for_django_like_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            for directory in [
                "django/contrib/admin/static/admin/js",
                "django/contrib/admin/templatetags",
                "django/core",
                "tests/validation",
                "django/contrib/auth/migrations",
            ]:
                (root / directory).mkdir(parents=True)
            (root / "django/contrib/admin/static/admin/js/change_form.js").write_text(
                "const form = document.querySelector('form');\nfunction displayMessages() { return form; }\n",
                encoding="utf-8",
            )
            (root / "django/contrib/admin/templatetags/admin_modify.py").write_text(
                "def render_change_form():\n    return 'form validation error messages'\n",
                encoding="utf-8",
            )
            (root / "django/core/exceptions.py").write_text(
                "class ValidationError(Exception):\n    pass\n\ndef not_are_after_noise():\n    return None\n",
                encoding="utf-8",
            )
            (root / "tests/validation/test_error_messages.py").write_text(
                "def test_validation_error_messages():\n    assert True\n",
                encoding="utf-8",
            )
            (root / "django/contrib/auth/migrations/0007_alter_validators_add_error_messages.py").write_text(
                "def alter_validators_add_error_messages():\n    return None\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "why are messages not displayed after form validation error in Django admin")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(
                    paths.index("django/contrib/admin/static/admin/js/change_form.js"),
                    paths.index("tests/validation/test_error_messages.py"),
                )
                if "django/contrib/auth/migrations/0007_alter_validators_add_error_messages.py" in paths:
                    self.assertLess(
                        paths.index("django/contrib/admin/static/admin/js/change_form.js"),
                        paths.index("django/contrib/auth/migrations/0007_alter_validators_add_error_messages.py"),
                    )
                rendered_reasons = "\n".join(reason for item in pack["candidate_files"] for reason in item["reasons"])
                self.assertNotIn('"are"', rendered_reasons)
                self.assertNotIn('"not"', rendered_reasons)
                self.assertNotIn('"after"', rendered_reasons)
                self.assertNotIn('"why"', rendered_reasons)
            finally:
                os.chdir(previous)

    def test_context_ignores_function_words_for_express_like_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
            (root / "lib").mkdir()
            (root / "examples").mkdir()
            (root / "lib" / "application.js").write_text(
                "function dispatch(req, res) { return req; }\nfunction middleware(fn) { return fn; }\n",
                encoding="utf-8",
            )
            (root / "examples" / "route-middleware.js").write_text(
                "function andRestrictToSelf(req, res) { return true; }\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "where routes and middleware requests are dispatched")
                rendered_reasons = "\n".join(reason for item in pack["candidate_files"] for reason in item["reasons"])
                self.assertNotIn('"and"', rendered_reasons)
                self.assertNotIn('"where"', rendered_reasons)
                self.assertNotIn('"are"', rendered_reasons)
                self.assertIn("lib/application.js", [item["path"] for item in pack["candidate_files"]])
            finally:
                os.chdir(previous)

    def test_context_deprioritizes_examples_and_docs_for_operational_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name": "sample"}\n', encoding="utf-8")
            for directory in ("src/optimizer", "playground/optimizer", "docs/guide"):
                (root / directory).mkdir(parents=True)
            (root / "src/optimizer/cache.ts").write_text(
                "export function optimizeDepsCache() { return true; }\n",
                encoding="utf-8",
            )
            for name in ("index", "resolve", "scanner", "metadata", "server", "plugin", "runtime", "invalidation"):
                (root / "src" / "optimizer" / f"{name}.ts").write_text(
                    f"export function {name}OptimizerCacheInvalidation() {{ return true; }}\n",
                    encoding="utf-8",
                )
            (root / "playground/optimizer/cache-demo.ts").write_text(
                "export function optimizeDepsCacheDemo() { return true; }\n",
                encoding="utf-8",
            )
            (root / "docs/guide/dep-pre-bundling.md").write_text(
                "# Optimize deps cache\n\nDependency optimizer cache guide.\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "debug optimizer cache invalidation")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(paths.index("src/optimizer/cache.ts"), paths.index("playground/optimizer/cache-demo.ts"))
                self.assertNotIn("docs/guide/dep-pre-bundling.md", paths)
                playground = next(item for item in pack["candidate_files"] if item["path"] == "playground/optimizer/cache-demo.ts")
                self.assertIn("example/playground deprioritized for non-example query", playground["reasons"])
                docs_pack = build_context_pack(root, "docs optimizer cache guide")
                self.assertEqual(docs_pack["candidate_files"][0]["path"], "docs/guide/dep-pre-bundling.md")
            finally:
                os.chdir(previous)

    def test_context_matches_query_token_inside_compound_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'tooling'\n", encoding="utf-8")
            source = root / "src" / "_pytest"
            source.mkdir(parents=True)
            (source / "fixtures.py").write_text(
                "def resolve_fixture():\n    return True\n",
                encoding="utf-8",
            )
            (source / "setupplan.py").write_text(
                "def pytest_fixture_setup():\n    return True\n",
                encoding="utf-8",
            )
            for name in ("capture", "debugging", "doctest", "hookspec", "logging", "python", "runner", "unittest"):
                (source / f"{name}.py").write_text(
                    "def setup():\n    return True\n",
                    encoding="utf-8",
                )
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                pack = build_context_pack(root, "pytest fixtures setup")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("src/_pytest/setupplan.py", paths[:5])
                setupplan = next(item for item in pack["candidate_files"] if item["path"] == "src/_pytest/setupplan.py")
                self.assertIn('filename contains "setup"', setupplan["reasons"])
            finally:
                os.chdir(previous)

    def test_doctor_without_agent_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["doctor"]), 0)
                self.assertIn("NOT_READY", output.getvalue())
                self.assertFalse((root / ".agent").exists())
                report = run_doctor(root)
                self.assertEqual(report["status"], "NOT_READY")
                self.assertIn("init-agent init", report["suggested_commands"])
            finally:
                os.chdir(previous)

    def test_doctor_after_init_before_map_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                report = run_doctor(root)
                self.assertEqual(report["status"], "NOT_READY")
                self.assertEqual(report["stats"]["files"], 0)
                self.assertIn("init-agent map", report["suggested_commands"])
            finally:
                os.chdir(previous)

    def test_doctor_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["doctor", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertIn(data["status"], {"READY", "READY_WITH_WARNINGS", "NOT_READY"})
                self.assertIn("checks", data)
                self.assertIn("stats", data)
                self.assertIn("warnings", data)
                self.assertIn("suggested_commands", data)
            finally:
                os.chdir(previous)

    def test_doctor_final_status_ready_after_map_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                report = run_doctor(root)
                self.assertEqual(report["status"], "READY")
                self.assertEqual(report["warnings"], [])
            finally:
                os.chdir(previous)

    def test_doctor_warns_when_index_version_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _mark_index_stale(root)
                report = run_doctor(root)
                self.assertEqual(report["status"], "READY_WITH_WARNINGS")
                self.assertIn("init-agent map", report["suggested_commands"])
                self.assertTrue(any("older extractor" in warning for warning in report["warnings"]))
            finally:
                os.chdir(previous)

    def test_doctor_no_crash_outside_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["doctor"]), 0)
                self.assertIn("Git repository: NO", output.getvalue())
            finally:
                os.chdir(previous)

    def test_refresh_without_agent_or_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["refresh"]), 1)
                self.assertIn("init-agent init", output.getvalue())
                report = refresh_index(root)
                self.assertEqual(report["status"], "ERROR")
                self.assertIn("init-agent init", report["suggested_commands"])
            finally:
                os.chdir(previous)

    def test_refresh_after_map_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertEqual(report["scanned_files"], 4)
                self.assertEqual(report["unchanged"], 4)
                self.assertEqual(report["added"], [])
                self.assertEqual(report["updated"], [])
                self.assertEqual(report["removed"], [])
            finally:
                os.chdir(previous)

    def test_refresh_reports_stale_index_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _mark_index_stale(root)
                report = refresh_index(root)
                self.assertEqual(report["status"], "ERROR")
                self.assertIn("init-agent map", report["suggested_commands"])
                self.assertTrue(any("older extractor" in error for error in report["errors"]))
            finally:
                os.chdir(previous)

    def test_refresh_detects_added_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                (root / "src" / "auth" / "token.py").write_text("def issueToken():\n    return 'x'\n", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertIn("src/auth/token.py", report["added"])
                with GraphStore(root) as store:
                    row = store.connection.execute("SELECT id FROM files WHERE path = ?", ("src/auth/token.py",)).fetchone()
                self.assertIsNotNone(row)
            finally:
                os.chdir(previous)

    def test_refresh_detects_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                target = root / "src" / "auth" / "login.py"
                target.write_text("def loginUser():\n    return 'changed'\n\ndef logoutUser():\n    return True\n", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertIn("src/auth/login.py", report["updated"])
                with GraphStore(root) as store:
                    names = [
                        row["name"]
                        for row in store.connection.execute(
                            """
                            SELECT s.name
                            FROM symbols s
                            JOIN files f ON f.id = s.file_id
                            WHERE f.path = ?
                            """,
                            ("src/auth/login.py",),
                        )
                    ]
                self.assertIn("logoutUser", names)
            finally:
                os.chdir(previous)

    def test_refresh_detects_removed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                (root / "src" / "auth" / "session.py").unlink()
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertIn("src/auth/session.py", report["removed"])
                with GraphStore(root) as store:
                    row = store.connection.execute("SELECT id FROM files WHERE path = ?", ("src/auth/session.py",)).fetchone()
                self.assertIsNone(row)
            finally:
                os.chdir(previous)

    def test_refresh_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["refresh", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["status"], "OK")
                self.assertIn("scanned_files", data)
                self.assertIn("unchanged", data)
                self.assertIn("added", data)
                self.assertIn("updated", data)
                self.assertIn("removed", data)
                self.assertIn("errors", data)
            finally:
                os.chdir(previous)

    def test_refresh_no_crash_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
            (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["refresh"]), 0)
                self.assertIn("Final result:\nOK", output.getvalue())
            finally:
                os.chdir(previous)

    def test_ignore_excludes_agents_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn(".agents/skills/impeccable/scripts/tool.py", paths)
                self.assertIn("app.php", paths)
            finally:
                os.chdir(previous)

    def test_ignore_excludes_github_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                self.assertNotIn(".github/workflows/ci.yml", _indexed_paths(root))
            finally:
                os.chdir(previous)

    def test_ignore_excludes_ds_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                self.assertNotIn("install/migrations/.DS_Store", _indexed_paths(root))
            finally:
                os.chdir(previous)

    def test_ignore_excludes_binary_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn("public/logo.png", paths)
                self.assertNotIn("public/icon.svg", paths)
                self.assertNotIn("public/logo.ai", paths)
                self.assertNotIn("docs/manual.pdf", paths)
                self.assertNotIn("data/cache.sqlite", paths)
            finally:
                os.chdir(previous)

    def test_ignore_excludes_python_package_metadata_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                paths = _indexed_paths(root)
                self.assertNotIn("sample.egg-info/PKG-INFO", paths)
                self.assertNotIn("sample-1.0.dist-info/METADATA", paths)
            finally:
                os.chdir(previous)

    def test_ignore_custom_exclude_dirs_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                config = root / ".agent" / "config.json"
                data = json.loads(config.read_text(encoding="utf-8"))
                data["exclude_dirs"] = ["excluded"]
                config.write_text(json.dumps(data), encoding="utf-8")
                main(["map"])
                self.assertNotIn("excluded/local_only.php", _indexed_paths(root))
            finally:
                os.chdir(previous)

    def test_doctor_ignores_excluded_unindexed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                report = run_doctor(root)
                self.assertEqual(report["status"], "READY")
                self.assertFalse(any("project files are not indexed" in warning for warning in report["warnings"]))
            finally:
                os.chdir(previous)

    def test_refresh_does_not_index_excluded_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            (root / "app.php").write_text("<?php\nfunction appMain() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                agents = root / ".agents" / "skills"
                agents.mkdir(parents=True)
                (agents / "new_tool.py").write_text("def ignored():\n    return True\n", encoding="utf-8")
                (root / ".DS_Store").write_text("ignored", encoding="utf-8")
                (root / "graph.sqlite").write_text("ignored", encoding="utf-8")
                egg_info = root / "sample.egg-info"
                egg_info.mkdir()
                (egg_info / "PKG-INFO").write_text("ignored", encoding="utf-8")
                report = refresh_index(root)
                self.assertEqual(report["status"], "OK")
                self.assertNotIn(".agents/skills/new_tool.py", report["added"])
                self.assertNotIn(".DS_Store", report["added"])
                self.assertNotIn("graph.sqlite", report["added"])
                self.assertNotIn("sample.egg-info/PKG-INFO", report["added"])
                paths = _indexed_paths(root)
                self.assertNotIn(".agents/skills/new_tool.py", paths)
                self.assertNotIn(".DS_Store", paths)
                self.assertNotIn("graph.sqlite", paths)
                self.assertNotIn("sample.egg-info/PKG-INFO", paths)
            finally:
                os.chdir(previous)

    def test_context_json_stays_valid_with_ignore_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["context", "app", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "app")
                self.assertIn("candidate_files", data)
            finally:
                os.chdir(previous)

    def test_run_on_uninitialized_project_creates_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
            (root / "include").mkdir()
            (root / "include" / "login.php").write_text("<?php\nfunction loginUser() { return true; }\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login"]), 0)
                self.assertTrue((root / ".agent").is_dir())
                self.assertTrue((root / ".agent" / "graph.sqlite").is_file())
                self.assertIn("Context pack for: login", output.getvalue())
            finally:
                os.chdir(previous)

    def test_run_on_mapped_project_uses_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login"]), 0)
                rendered = output.getvalue()
                self.assertIn("- Map: skipped", rendered)
                self.assertIn("- Refresh: OK", rendered)
            finally:
                os.chdir(previous)

    def test_run_rebuilds_stale_index_and_accepts_unquoted_query_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_php_call_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _mark_index_stale(root)
                with GraphStore(root) as store:
                    store.connection.execute("DELETE FROM relations WHERE relation = 'calls'")
                    store.connection.commit()
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "dove", "viene", "chiamata", "buildForm", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "dove viene chiamata buildForm")
                self.assertEqual(data["preparation"]["map"], "done")
                self.assertTrue(any("older extractor" in warning for warning in data["preparation"]["warnings"]))
                paths = [item["path"] for item in data["context"]["candidate_files"]]
                self.assertIn("index.php", paths)
                index_item = next(item for item in data["context"]["candidate_files"] if item["path"] == "index.php")
                self.assertIn('calls "buildForm"', index_item["reasons"])
            finally:
                os.chdir(previous)

    def test_run_without_git_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login"]), 0)
                self.assertIn("- Git: not available", output.getvalue())
            finally:
                os.chdir(previous)

    def test_run_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login")
                self.assertIn("preparation", data)
                self.assertIn("context", data)
                self.assertIn("candidate_files", data["context"])
            finally:
                os.chdir(previous)

    def test_run_markdown_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("# Init Agent Context Pack", rendered)
                self.assertIn("## Preparation", rendered)
                self.assertIn("## Suggested first reads", rendered)
                self.assertIn("## Useful follow-up commands", rendered)
                self.assertIn("## Safety notes", rendered)
                self.assertIn("init-agent related src/auth/login.py", rendered)
                self.assertIn('init-agent feedback add "login"', rendered)
                self.assertIn("Heuristic orientation only; verify files before editing.", rendered)
            finally:
                os.chdir(previous)

    def test_run_markdown_handoff_suggests_symbol_followups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login session", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("## Useful follow-up commands", rendered)
                self.assertIn("init-agent callers loginUser", rendered)
                self.assertIn("init-agent related src/auth/login.py", rendered)
                self.assertIn("Feedback should be recorded only after files are verified.", rendered)
            finally:
                os.chdir(previous)

    def test_run_generates_final_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "login session"]), 0)
                rendered = output.getvalue()
                self.assertIn("src/auth/login.py", rendered)
                self.assertIn("Suggested first reads:", rendered)
            finally:
                os.chdir(previous)

    def test_recent_commit_files_are_truncated_in_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=15)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=15)
                pack = build_context_pack(root, "admin login")
                commit = pack["recent_commits"][0]
                self.assertEqual(len(commit["files"]), 10)
                self.assertEqual(commit["total_files"], 15)
                self.assertTrue(commit["files_truncated"])
            finally:
                os.chdir(previous)

    def test_recent_commit_files_not_truncated_when_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=4)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=4)
                pack = build_context_pack(root, "admin login")
                commit = pack["recent_commits"][0]
                self.assertEqual(len(commit["files"]), 4)
                self.assertEqual(commit["total_files"], 4)
                self.assertFalse(commit["files_truncated"])
            finally:
                os.chdir(previous)

    def test_run_markdown_does_not_print_large_commit_file_lists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=15)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=15)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "admin login", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("files: 10 of 15 shown", rendered)
                recent_commits = rendered.split("## Recent related commits", 1)[1]
                self.assertNotIn("file_14.php", recent_commits)
            finally:
                os.chdir(previous)

    def test_run_json_with_truncated_commits_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_many_commit_files_fixture(Path(tmp), total_files=15)
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                _add_big_commit(root, total_files=15)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "admin login", "--json"]), 0)
                data = json.loads(output.getvalue())
                commit = data["context"]["recent_commits"][0]
                self.assertEqual(commit["total_files"], 15)
                self.assertTrue(commit["files_truncated"])
                self.assertEqual(len(commit["files"]), 10)
            finally:
                os.chdir(previous)

    def test_estimate_produces_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "login"]), 0)
                rendered = output.getvalue()
                self.assertIn("Init Agent Token Estimate", rendered)
                self.assertIn("Estimated savings:", rendered)
            finally:
                os.chdir(previous)

    def test_estimate_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "login", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login")
                self.assertIn("context_pack", data)
                self.assertIn("suggested_first_reads", data)
                self.assertIn("top_candidates", data)
                self.assertIn("indexed_project", data)
                self.assertIn("estimated_savings", data)
            finally:
                os.chdir(previous)

    def test_estimate_tokens_uses_ceil_chars_over_four(self) -> None:
        self.assertEqual(estimate_tokens(0), 0)
        self.assertEqual(estimate_tokens(1), 1)
        self.assertEqual(estimate_tokens(4), 1)
        self.assertEqual(estimate_tokens(5), 2)

    def test_estimate_does_not_crash_with_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                (root / "src" / "auth" / "login.py").unlink()
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "login", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertGreaterEqual(data["indexed_project"]["characters"], 0)
            finally:
                os.chdir(previous)

    def test_estimate_respects_excluded_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_ignore_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["estimate", "app", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertLess(data["indexed_project"]["files_count"], 5)
                self.assertNotIn("public/logo.png", data["suggested_first_reads"]["files"])
            finally:
                os.chdir(previous)

    def test_overview_prefers_manifest_entry_points_and_subsystems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview"]), 0)
                rendered = output.getvalue()
                self.assertIn("Init Agent Repository Overview", rendered)
                self.assertIn("pyproject.toml", rendered)
                self.assertIn("src/sample/cli.py", rendered)
                self.assertIn("src/sample/server.py", rendered)
                self.assertIn("frontend/package.json", rendered)
                self.assertIn("Major subsystems:", rendered)
            finally:
                os.chdir(previous)

    def test_overview_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertIn("project", data)
                self.assertIn("suggested_first_reads", data)
                self.assertIn("entry_points", data)
                self.assertIn("manifests", data)
                self.assertIn("subsystems", data)
                paths = [item["path"] for item in data["suggested_first_reads"]]
                self.assertIn("pyproject.toml", paths)
                self.assertLess(paths.index("pyproject.toml"), paths.index("tests/test_cli.py") if "tests/test_cli.py" in paths else 99)
            finally:
                os.chdir(previous)

    def test_run_overview_prepares_uninitialized_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "--overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["preparation"]["init"], "done")
                self.assertEqual(data["preparation"]["map"], "done")
                self.assertTrue((root / ".agent" / "graph.sqlite").exists())
                self.assertIn("overview", data)
                self.assertIn("pyproject.toml", [item["path"] for item in data["overview"]["manifests"]])
            finally:
                os.chdir(previous)

    def test_run_overview_markdown_is_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_overview_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", "--overview", "--markdown"]), 0)
                rendered = output.getvalue()
                self.assertIn("# Init Agent Repository Overview", rendered)
                self.assertIn("## Suggested first reads", rendered)
                self.assertIn("## Likely entry points", rendered)
                self.assertIn("Heuristic overview", rendered)
            finally:
                os.chdir(previous)

    def test_overview_caps_repeated_test_routes_and_prefers_core_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "composer.json").write_text('{"name": "sample/framework"}\n', encoding="utf-8")
            (root / "README.md").write_text("# Sample Framework\n", encoding="utf-8")
            source = root / "src" / "Framework" / "Foundation"
            tests = root / "tests" / "Integration" / "Routing"
            source.mkdir(parents=True)
            tests.mkdir(parents=True)
            (source / "Application.php").write_text(
                "<?php\nclass Application { public function boot() { return true; } }\n",
                encoding="utf-8",
            )
            noisy_routes = "\n".join(f"Route::get('/fixture-{index}', Handler::class);" for index in range(40))
            (tests / "RouteFixtureTest.php").write_text(f"<?php\n{noisy_routes}\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                paths = [item["path"] for item in data["suggested_first_reads"]]
                self.assertIn("composer.json", paths)
                self.assertIn("src/Framework/Foundation/Application.php", paths)
                if "tests/Integration/Routing/RouteFixtureTest.php" in paths:
                    self.assertLess(paths.index("composer.json"), paths.index("tests/Integration/Routing/RouteFixtureTest.php"))
                    self.assertLess(
                        paths.index("src/Framework/Foundation/Application.php"),
                        paths.index("tests/Integration/Routing/RouteFixtureTest.php"),
                    )
            finally:
                os.chdir(previous)

    def test_overview_detects_python_framework_package_entry_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname = 'frameworkish'\n", encoding="utf-8")
            package = root / "frameworkish" / "core" / "management"
            tests = root / "tests" / "management"
            docs = root / "docs"
            package.mkdir(parents=True)
            tests.mkdir(parents=True)
            docs.mkdir()
            (package / "__init__.py").write_text("def execute_from_command_line():\n    return None\n", encoding="utf-8")
            (package / "commands.py").write_text("def run_command():\n    return None\n", encoding="utf-8")
            (tests / "test_management.py").write_text("def test_management_command():\n    assert True\n", encoding="utf-8")
            (docs / "management.md").write_text("# Management commands\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["overview", "--json"]), 0)
                data = json.loads(output.getvalue())
                first_reads = [item["path"] for item in data["suggested_first_reads"]]
                entry_points = [item["path"] for item in data["entry_points"]]
                self.assertIn("frameworkish/core/management/__init__.py", first_reads)
                self.assertIn("frameworkish/core/management/__init__.py", entry_points)
                self.assertLess(
                    first_reads.index("frameworkish/core/management/__init__.py"),
                    first_reads.index("tests/management/test_management.py")
                    if "tests/management/test_management.py" in first_reads
                    else 99,
                )
            finally:
                os.chdir(previous)

    def test_feedback_add_and_list_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(
                            [
                                "feedback",
                                "add",
                                "auth session bug",
                                "src/auth/session.py",
                                "--rating",
                                "useful",
                                "--reason",
                                "verified session state",
                                "--source",
                                "agent",
                                "--json",
                            ]
                        ),
                        0,
                    )
                record = json.loads(output.getvalue())
                self.assertEqual(record["path"], "src/auth/session.py")
                self.assertEqual(record["rating"], "useful")

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "list", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(len(data["feedback"]), 1)
                self.assertEqual(data["feedback"][0]["reason"], "verified session state")
            finally:
                os.chdir(previous)

    def test_feedback_boosts_similar_context_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "authentication bug",
                        "src/auth/session.py",
                        "--rating",
                        "crucial",
                        "--reason",
                        "agent verified session handling",
                    ]
                )
                pack = build_context_pack(root, "authentication bug")
                self.assertEqual(pack["candidate_files"][0]["path"], "src/auth/session.py")
                self.assertIn("previously marked crucial for similar query", pack["candidate_files"][0]["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_does_not_overfit_unrelated_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "authentication bug", "src/auth/session.py", "--rating", "crucial"])
                pack = build_context_pack(root, "billing invoice export")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertNotIn("src/auth/session.py", paths)
            finally:
                os.chdir(previous)

    def test_feedback_noisy_penalizes_similar_context_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/login.py", "--rating", "noisy"])
                pack = build_context_pack(root, "login session")
                login = next(item for item in pack["candidate_files"] if item["path"] == "src/auth/login.py")
                self.assertIn("previously marked noisy for similar query", login["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_explain_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "login session",
                        "src/auth/session.py",
                        "--rating",
                        "crucial",
                        "--reason",
                        "verified session flow",
                    ]
                )
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login session")
                self.assertIn("login", data["query_tokens"])
                self.assertEqual(data["signals"][0]["path"], "src/auth/session.py")
                self.assertGreater(data["signals"][0]["boost"], 0)
                self.assertEqual(data["signals"][0]["items"][0]["rating"], "crucial")
                self.assertIn("similarity", data["signals"][0]["items"][0])
                self.assertIn("contribution", data["signals"][0]["items"][0])
            finally:
                os.chdir(previous)

    def test_feedback_explain_reports_source_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(
                    [
                        "feedback",
                        "add",
                        "login session",
                        "src/auth/session.py",
                        "--rating",
                        "useful",
                        "--source",
                        "user",
                    ]
                )
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                item = data["signals"][0]["items"][0]
                self.assertEqual(item["source"], "user")
                self.assertEqual(item["source_weight"], 1.2)
                self.assertEqual(item["contribution"], 12.0)
                self.assertEqual(data["signals"][0]["boost"], 12.0)
            finally:
                os.chdir(previous)

    def test_feedback_explain_accepts_unquoted_query_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/session.py", "--rating", "useful"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["query"], "login session")
                self.assertEqual(data["signals"][0]["path"], "src/auth/session.py")
            finally:
                os.chdir(previous)

    def test_feedback_explain_can_show_ignored_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "billing invoice", "src/auth/session.py", "--rating", "useful"])

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login session", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["signals"], [])
                self.assertEqual(data["ignored"], [])

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--all", "--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["signals"], [])
                self.assertEqual(data["ignored"][0]["path"], "src/auth/session.py")
                self.assertEqual(data["ignored"][0]["ignored_reason"], "similarity below threshold")
            finally:
                os.chdir(previous)

    def test_feedback_explain_does_not_match_unrelated_item_on_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/session.py", "--rating", "useful"])
                main(["feedback", "add", "billing invoice", "src/auth/session.py", "--rating", "useful"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "explain", "login", "session", "--all", "--json"]), 0)
                data = json.loads(output.getvalue())
                matched_queries = [item["query"] for item in data["signals"][0]["items"]]
                ignored_queries = [item["query"] for item in data["ignored"]]
                self.assertEqual(matched_queries, ["login session"])
                self.assertIn("billing invoice", ignored_queries)
            finally:
                os.chdir(previous)

    def test_feedback_noisy_demotes_strong_direct_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/auth/login.py", "--rating", "noisy"])
                main(["feedback", "add", "login session", "src/auth/session.py", "--rating", "useful"])
                pack = build_context_pack(root, "login session")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertLess(paths.index("src/auth/session.py"), paths.index("src/auth/login.py"))
                login = next(item for item in pack["candidate_files"] if item["path"] == "src/auth/login.py")
                self.assertLess(login["score"], 0.75)
            finally:
                os.chdir(previous)

    def test_feedback_crucial_surfaces_verified_file_without_direct_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            internal_dir = root / "src" / "internal"
            internal_dir.mkdir(parents=True)
            (internal_dir / "state.py").write_text("def mark_read():\n    return True\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login session", "src/internal/state.py", "--rating", "crucial"])
                pack = build_context_pack(root, "login session")
                paths = [item["path"] for item in pack["candidate_files"]]
                self.assertIn("src/internal/state.py", paths)
                state = next(item for item in pack["candidate_files"] if item["path"] == "src/internal/state.py")
                self.assertIn("previously marked crucial for similar query", state["reasons"])
            finally:
                os.chdir(previous)

    def test_feedback_improves_relative_rank_without_absolute_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            internal_dir = root / "src" / "internal"
            internal_dir.mkdir(parents=True)
            (internal_dir / "state.py").write_text("def mark_read():\n    return True\n", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                before = build_context_pack(root, "login session")
                before_paths = [item["path"] for item in before["candidate_files"]]
                before_rank = before_paths.index("src/internal/state.py") if "src/internal/state.py" in before_paths else 99
                main(["feedback", "add", "login session", "src/internal/state.py", "--rating", "crucial"])
                after = build_context_pack(root, "login session")
                after_paths = [item["path"] for item in after["candidate_files"]]
                self.assertIn("src/internal/state.py", after_paths)
                self.assertLess(after_paths.index("src/internal/state.py"), before_rank)
            finally:
                os.chdir(previous)

    def test_feedback_export_import_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_context_fixture(Path(tmp))
            previous = Path.cwd()
            try:
                os.chdir(root)
                main(["init"])
                main(["map"])
                main(["feedback", "add", "login bug", "src/auth/login.py", "--rating", "useful"])
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "export", "--json"]), 0)
                exported = json.loads(output.getvalue())
                self.assertEqual(len(exported["feedback"]), 1)

                export_path = root / "feedback.json"
                export_path.write_text(json.dumps(exported), encoding="utf-8")
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "clear", "--all", "--json"]), 0)
                self.assertEqual(json.loads(output.getvalue())["deleted"], 1)

                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["feedback", "import", str(export_path), "--json"]), 0)
                self.assertEqual(json.loads(output.getvalue())["imported"], 1)
            finally:
                os.chdir(previous)


def _create_context_fixture(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    auth_dir = root / "src" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "login.py").write_text(
        "from src.auth.session import validateSession\n\n"
        "def loginUser():\n"
        "    return validateSession()\n",
        encoding="utf-8",
    )
    (auth_dir / "session.py").write_text(
        "SESSION_TIMEOUT = 300\n\n"
        "def validateSession():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Sample\n", encoding="utf-8")
    return root


def _create_overview_fixture(root: Path) -> Path:
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\n[project.scripts]\nsample = 'sample.cli:main'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Sample\n\n## Usage\n\nRun the CLI.\n", encoding="utf-8")
    source = root / "src" / "sample"
    source.mkdir(parents=True)
    (source / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (source / "server.py").write_text("def create_app():\n    return object()\n", encoding="utf-8")
    (source / "routes.py").write_text("@app.route('/health')\ndef health():\n    return 'ok'\n", encoding="utf-8")
    frontend = root / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"name": "frontend", "scripts": {"dev": "vite --host 0.0.0.0"}}\n', encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_cli.py").write_text("def test_cli_main():\n    assert True\n", encoding="utf-8")
    return root


def _create_context_scoring_fixture(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    source_dir = root / "init_agent"
    test_dir = root / "tests"
    source_dir.mkdir()
    test_dir.mkdir()
    (source_dir / "context_builder.py").write_text(
        "def build_context_pack():\n"
        "    return []\n\n"
        "def score_context_symbols():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (test_dir / "test_base.py").write_text(
        "def test_context_scoring_symbols():\n"
        "    assert True\n\n"
        "def test_context_scoring_behavior():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    return root


def _create_php_login_fixture(root: Path) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    include = root / "include"
    core = include / "core"
    gst = include / "gst"
    css = root / "css"
    migrations = root / "install" / "migrations"
    core.mkdir(parents=True)
    gst.mkdir(parents=True)
    css.mkdir()
    migrations.mkdir(parents=True)
    (include / "login.php").write_text(
        "<?php\n"
        "function loginUtente($admin) { return validaSessione($admin); }\n"
        "function validaSessione($admin) { return true; }\n",
        encoding="utf-8",
    )
    (include / "crm.php").write_text(
        "<?php\n"
        "require_once 'login.php';\n"
        "function adminDashboard() { return true; }\n"
        "function adminCustomerList() { return true; }\n"
        "function adminCrmPanel() { return true; }\n",
        encoding="utf-8",
    )
    (include / "crmFunction.php").write_text(
        "<?php\n"
        "require_once 'login.php';\n"
        "function adminHelper() { return true; }\n"
        "function adminPermission() { return true; }\n"
        "function adminReport() { return true; }\n",
        encoding="utf-8",
    )
    (core / "organization.php").write_text(
        "<?php\n"
        "require_once '../login.php';\n"
        "function adminOrganization() { return true; }\n"
        "function adminUnit() { return true; }\n",
        encoding="utf-8",
    )
    (gst / "generate_config.php").write_text(
        "<?php\n"
        "function adminGenerateConfig() { return true; }\n",
        encoding="utf-8",
    )
    (css / "login.css").write_text(
        ".login-admin-panel { color: #111; }\n"
        ".session-warning { display: block; }\n",
        encoding="utf-8",
    )
    (migrations / "2026-06-16-admin-role-permissions.sql").write_text(
        "CREATE TABLE admin_role_permissions (id integer primary key, permission text);\n"
        "INSERT INTO admin_role_permissions(permission) VALUES ('login_sessione_admin');\n",
        encoding="utf-8",
    )
    return root


def _create_php_call_fixture(root: Path) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    include = root / "include"
    include.mkdir()
    (root / "index.php").write_text(
        "<?php\n"
        "require_once 'include/bootstrap.php';\n"
        "$html = buildForm($record);\n"
        "echo renderPage($html);\n",
        encoding="utf-8",
    )
    (include / "bootstrap.php").write_text(
        "<?php\n"
        "require_once 'crm.php';\n"
        "require_once 'db.php';\n"
        "require_once 'functions.php';\n",
        encoding="utf-8",
    )
    (include / "crm.php").write_text("<?php\nfunction crmTitle() { return 'CRM'; }\n", encoding="utf-8")
    (include / "db.php").write_text("<?php\nfunction dbConnect() { return true; }\n", encoding="utf-8")
    (include / "functions.php").write_text(
        "<?php\n"
        "function buildForm($record) { return '<form></form>'; }\n"
        "function renderPage($html) { return $html; }\n",
        encoding="utf-8",
    )
    return root


def _add_admin_commit_noise(root: Path) -> None:
    with GraphStore(root) as store:
        store.replace_git_history(
            [
                {
                    "hash": f"abc12345{index}",
                    "author": "Test",
                    "date": f"2026-01-0{index + 1}T00:00:00+00:00",
                    "message": f"admin crm organization update {index}",
                    "files": ["include/crm.php", "include/crmFunction.php", "include/core/organization.php"],
                }
                for index in range(5)
            ]
        )
        store.rebuild_term_stats()


def _create_many_commit_files_fixture(root: Path, total_files: int) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    include = root / "include"
    include.mkdir()
    for index in range(total_files):
        name = "login.php" if index == 0 else f"file_{index}.php"
        symbol = "loginAdmin" if index == 0 else f"adminFile{index}"
        (include / name).write_text(f"<?php\nfunction {symbol}() {{ return true; }}\n", encoding="utf-8")
    return root


def _add_big_commit(root: Path, total_files: int) -> None:
    files = ["include/login.php"] + [f"include/file_{index}.php" for index in range(1, total_files)]
    with GraphStore(root) as store:
        store.replace_git_history(
            [
                {
                    "hash": "abc123bigcommit",
                    "author": "Test",
                    "date": "2026-01-01T00:00:00+00:00",
                    "message": "admin login update",
                    "files": files,
                }
            ]
        )


def _create_ignore_fixture(root: Path) -> Path:
    (root / "composer.json").write_text('{"name": "sample/app"}\n', encoding="utf-8")
    (root / "app.php").write_text("<?php\nfunction appMain() { return true; }\n", encoding="utf-8")
    agents = root / ".agents" / "skills" / "impeccable" / "scripts"
    agents.mkdir(parents=True)
    (agents / "tool.py").write_text("def ignored():\n    return True\n", encoding="utf-8")
    migrations = root / "install" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / ".DS_Store").write_text("ignored", encoding="utf-8")
    public = root / "public"
    docs = root / "docs"
    data = root / "data"
    excluded = root / "excluded"
    public.mkdir()
    docs.mkdir()
    data.mkdir()
    excluded.mkdir()
    egg_info = root / "sample.egg-info"
    dist_info = root / "sample-1.0.dist-info"
    egg_info.mkdir()
    dist_info.mkdir()
    (public / "logo.png").write_bytes(b"png")
    (public / "icon.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (public / "logo.ai").write_bytes(b"ai")
    (docs / "manual.pdf").write_bytes(b"pdf")
    (data / "cache.sqlite").write_bytes(b"sqlite")
    (excluded / "local_only.php").write_text("<?php\nfunction localOnly() { return true; }\n", encoding="utf-8")
    (egg_info / "PKG-INFO").write_text("ignored", encoding="utf-8")
    (dist_info / "METADATA").write_text("ignored", encoding="utf-8")
    return root


def _prepare_index(root: Path) -> None:
    previous = Path.cwd()
    output = StringIO()
    try:
        os.chdir(root)
        with redirect_stdout(output):
            main(["init"])
            main(["map"])
    finally:
        os.chdir(previous)


def _indexed_paths(root: Path) -> set[str]:
    with GraphStore(root) as store:
        return {row["path"] for row in store.connection.execute("SELECT path FROM files").fetchall()}


def _mark_index_stale(root: Path) -> None:
    with GraphStore(root) as store:
        store.connection.execute("DELETE FROM project_meta WHERE key = 'index_version'")
        store.connection.commit()


def _fake_codex(tmp: Path, log_path: Path) -> Path:
    script = tmp / ("fake_codex.py" if os.name == "nt" else "fake-codex")
    script.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json",
                "import os",
                "import pathlib",
                "import sys",
                f"log = pathlib.Path({str(log_path)!r})",
                "entries = json.loads(log.read_text(encoding='utf-8')) if log.exists() else []",
                "entries.append(sys.argv[1:])",
                "log.write_text(json.dumps(entries), encoding='utf-8')",
                "if len(sys.argv) >= 5 and sys.argv[1:3] == ['mcp', 'add']:",
                "    codex_home = os.environ.get('CODEX_HOME')",
                "    if codex_home:",
                "        config = pathlib.Path(codex_home) / 'config.toml'",
                "        config.parent.mkdir(parents=True, exist_ok=True)",
                "        server = sys.argv[3]",
                "        command_index = sys.argv.index('--') + 1 if '--' in sys.argv else len(sys.argv)",
                "        command = sys.argv[command_index] if command_index < len(sys.argv) else 'init-agent-mcp'",
                "        args = sys.argv[command_index + 1:]",
                "        config.write_text('[mcp_servers.%s]\\ncommand = %r\\nargs = %r\\n' % (server, command, args), encoding='utf-8')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


if __name__ == "__main__":
    unittest.main()
