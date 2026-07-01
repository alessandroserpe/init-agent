from tests.support import *


class DocsInstallTests(InitAgentTestCase):
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
        self.assertIn("keep a tiny verification ledger", content)
        self.assertIn("Noisy Or Empty Results", content)
        self.assertIn("do not start reading the whole repository", content)
        self.assertIn("Feedback is expected after non-trivial verified work", content)
        self.assertIn("Memory is expected after non-trivial work", content)
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

    def test_docs_cover_session_close_and_optional_tree_sitter(self) -> None:
        root = Path(__file__).resolve().parents[1]
        commands = (root / "docs" / "commands.md").read_text(encoding="utf-8")
        parsing = (root / "docs" / "parsing.md").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        mcp = (root / "docs" / "mcp.md").read_text(encoding="utf-8")
        skill = (root / "init_agent" / "resources" / "skills" / "init-agent-orientation" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("repo_session_close", commands)
        self.assertIn("repo_task_add", commands)
        self.assertIn("repo_reading_plan_finish", commands)
        self.assertIn("repo_reading_plan_read", commands)
        self.assertIn("repo_reading_plan_diff", commands)
        self.assertIn("repo_reading_plan_stats", commands)
        self.assertIn("repo_flow_topics", commands)
        self.assertIn("init-agent web", commands)
        self.assertIn("repo_task_note", readme)
        self.assertIn("init-agent web", readme)
        self.assertIn("repo_reading_plan_finish", readme)
        self.assertIn("repo_reading_plan_read", readme)
        self.assertIn("repo_reading_plan_diff", readme)
        self.assertIn("repo_task_close", mcp)
        self.assertIn("repo_reading_plan_finish", mcp)
        self.assertIn("repo_reading_plan_read", mcp)
        self.assertIn("repo_reading_plan_diff", mcp)
        self.assertIn("repo_flow_topics", mcp)
        self.assertIn("repo_task_list", skill)
        self.assertIn("repo_reading_plan_finish", skill)
        self.assertIn("repo_reading_plan_read", skill)
        self.assertIn("repo_reading_plan_diff", skill)
        self.assertIn("init-agent plan \"<user task>\" --read 3", skill)
        self.assertIn("Do not wait for the user to ask", skill)
        self.assertIn("Prefer updating an existing memory", skill)
        self.assertIn("Only fall back to broad filesystem exploration after this recovery loop fails", skill)
        self.assertIn("pipx inject init-agent tree-sitter tree-sitter-php", commands)
        self.assertIn("tree-sitter", parsing)
        self.assertIn("falls back to the built-in PHP parser", parsing)
        self.assertIn("docs/parsing.md", readme)

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
