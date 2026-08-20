import hashlib
import re

from init_agent.mcp_installer import codex_mcp_status
from init_agent.skill_installer import SKILL_MANIFEST, codex_skill_status, sync_codex_skill

from tests.support import *


class DocsInstallTests(InitAgentTestCase):
    def test_agent_skill_template_documents_core_workflow(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_path = root / "skills" / "init-agent-orientation" / "SKILL.md"
        bundled_path = root / "init_agent" / "resources" / "skills" / "init-agent-orientation" / "SKILL.md"
        self.assertTrue(skill_path.exists())
        content = skill_path.read_text(encoding="utf-8")
        self.assertEqual(content, bundled_path.read_text(encoding="utf-8"))
        self.assertIn("init-agent run --overview", content)
        self.assertIn("Use the smallest useful loop", content)
        self.assertIn("repo_reading_plan", content)
        self.assertIn("repo_reading_plan_finish", content)
        self.assertIn("repo_related_file", content)
        self.assertIn("repo_symbol_callers", content)
        self.assertIn("repo_memory_add", content)
        self.assertIn("repo_session_close", content)
        self.assertIn("Do not call every available command", content)
        self.assertIn("Delegation advice is disabled by default", content)

    def test_agent_skill_readme_documents_install_and_shim(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme_path = root / "skills" / "README.md"
        self.assertTrue(readme_path.exists())
        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("init-agent install-skill codex", content)
        self.assertIn("init-agent sync", content)
        self.assertIn("cp -R skills/init-agent-orientation ~/.codex/skills/", content)
        self.assertIn("PYTHONPATH", content)
        self.assertIn("MCP `core` profile", content)
        self.assertIn("repo_reading_plan_finish", content)
        self.assertIn("repo_session_close", content)

    def test_public_docs_keep_the_default_loop_compact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        agent_usage = (root / "docs" / "agent-usage.md").read_text(encoding="utf-8")
        commands = (root / "docs" / "commands.md").read_text(encoding="utf-8")

        readme_loop = readme.split("## Example Output", 1)[0]
        agent_loop = agent_usage.split("## Generic Workflow", 1)[0]
        commands_loop = commands.split("## Summary", 1)[0]
        for section in (readme_loop, agent_loop, commands_loop):
            self.assertIn("plan finish", section)
            self.assertNotIn("plan read", section)
            self.assertNotIn("plan diff", section)

    def test_release_and_task_history_use_single_sources(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contributing = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertFalse((root / "CHANGELOG.md").exists())
        self.assertFalse((root / "TASKS.md").exists())
        self.assertIn("GitHub Releases", contributing)

    def test_experiments_readme_points_to_full_methodology(self) -> None:
        root = Path(__file__).resolve().parents[1]
        content = (root / "experiments" / "README.md").read_text(encoding="utf-8")
        self.assertIn("../docs/experiments.md", content)
        self.assertIn("do not prove", content)
        self.assertIn("--strict --min-cases 4", content)

    def test_public_markdown_links_resolve_locally(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = [root / "README.md", root / "CONTRIBUTING.md"]
        paths.extend(sorted((root / "docs").glob("*.md")))
        paths.extend(sorted((root / "experiments").glob("**/*.md")))
        paths.append(root / "skills" / "README.md")

        for path in paths:
            content = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", content):
                if target.startswith(("http://", "https://", "#")):
                    continue
                local_target = target.split("#", 1)[0]
                if not local_target:
                    continue
                self.assertTrue(
                    (path.parent / local_target).resolve().exists(),
                    f"broken Markdown link in {path.relative_to(root)}: {target}",
                )

    def test_main_readme_documents_two_command_codex_install(self) -> None:
        root = Path(__file__).resolve().parents[1]
        content = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Use With Codex", content)
        self.assertIn("pipx install git+https://github.com/alessandroserpe/init-agent.git", content)
        self.assertIn("init-agent mcp install-codex", content)
        self.assertIn("init-agent install-skill codex", content)
        self.assertIn("init-agent sync", content)
        self.assertIn("init-agent doctor --check-updates", content)
        self.assertIn("recommended daily workflow", content)
        self.assertIn('init-agent plan "<task>" --read 3', content)
        self.assertIn("init-agent session close", content)
        self.assertIn("init-agent web", content)

    def test_mcp_docs_include_codex_config_and_smoke_test(self) -> None:
        root = Path(__file__).resolve().parents[1]
        content = (root / "docs" / "mcp.md").read_text(encoding="utf-8")
        self.assertIn("codex mcp add", content)
        self.assertIn("--manual-config --experimental", content)
        self.assertIn("Content-Length", content)
        self.assertIn("tools/list", content)
        self.assertIn("repo_reading_plan", content)
        self.assertIn("--profile full", content)

    def test_docs_cover_session_close_and_optional_tree_sitter(self) -> None:
        root = Path(__file__).resolve().parents[1]
        commands = (root / "docs" / "commands.md").read_text(encoding="utf-8")
        parsing = (root / "docs" / "parsing.md").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        mcp = (root / "docs" / "mcp.md").read_text(encoding="utf-8")
        skill = (root / "init_agent" / "resources" / "skills" / "init-agent-orientation" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("repo_session_close", commands)
        self.assertIn("Recommended Daily Workflow", commands)
        self.assertIn("repo_task_add", commands)
        self.assertIn("repo_reading_plan_finish", commands)
        self.assertIn("repo_reading_plan_read", commands)
        self.assertIn("repo_reading_plan_diff", commands)
        self.assertIn("repo_reading_plan_mark", commands)
        self.assertIn("repo_reading_plan_stats", commands)
        self.assertIn("repo_workstream_report", commands)
        self.assertIn("repo_workstream_review", commands)
        self.assertIn("init-agent scorecard", commands)
        self.assertIn("repo_flow_topics", commands)
        self.assertIn("init-agent web", commands)
        self.assertIn("init-agent web", readme)
        self.assertIn("init-agent plan finish", readme)
        self.assertIn("MCP `core` profile", readme)
        self.assertIn("init-agent scorecard", readme)
        self.assertIn("repo_reading_plan_finish", mcp)
        self.assertIn("repo_memory_search", mcp)
        self.assertIn("repo_session_close", mcp)
        self.assertIn("--profile full", mcp)
        self.assertIn("Full Compatibility Profile", mcp)
        self.assertIn("repo_reading_plan_finish", skill)
        self.assertIn("repo_reading_plan", skill)
        self.assertIn("repo_memory_add", skill)
        self.assertIn("repo_session_close", skill)
        self.assertIn("Only then broaden filesystem exploration", skill)
        self.assertIn("pipx inject init-agent tree-sitter tree-sitter-php", commands)
        self.assertIn("tree-sitter", parsing)
        self.assertIn("falls back to the built-in PHP parser", parsing)
        self.assertIn("docs/parsing.md", readme)

    def test_docs_define_optional_privacy_preserving_trajectory_workflow(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        commands = (root / "docs" / "commands.md").read_text(encoding="utf-8")
        security = (root / "docs" / "security.md").read_text(encoding="utf-8")
        trajectory = (root / "docs" / "trajectory.md").read_text(encoding="utf-8")
        source_skill = (root / "skills" / "init-agent-orientation" / "SKILL.md").read_text(encoding="utf-8")
        bundled_skill = (
            root / "init_agent" / "resources" / "skills" / "init-agent-orientation" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("init-agent trajectory install-codex", readme)
        self.assertIn("init-agent trajectory uninstall-codex", commands)
        self.assertIn("does not store prompts", security)
        self.assertIn("not model chain-of-thought", trajectory)
        self.assertIn("Do not add telemetry calls", source_skill)
        self.assertEqual(source_skill, bundled_skill)

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
            self.assertEqual(len(args), 7)
            self.assertEqual(args[-2:], ["--profile", "core"])
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

    def test_mcp_install_codex_can_request_full_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            log_path = Path(tmp) / "codex_args.json"
            fake_codex = _fake_codex(Path(tmp), log_path)

            previous_codex_home = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = str(codex_home)
            try:
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(["mcp", "install-codex", "--profile", "full", "--codex-command", str(fake_codex), "--json"]),
                        0,
                    )
            finally:
                if previous_codex_home is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = previous_codex_home

            args = json.loads(log_path.read_text(encoding="utf-8"))[-1]
            self.assertEqual(args[-2:], ["--profile", "full"])

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
            self.assertIn(f'args = ["--profile", "core", "--root", "{root.resolve()}"]', updated)
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
            self.assertIn(f'args = ["--profile", "core", "--root", "{root.resolve()}"]', updated)
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
            manifest = json.loads((target / "init-agent-orientation" / SKILL_MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(manifest["package_version"], __import__("init_agent").__version__)

    def test_sync_skill_is_idempotent_and_backs_up_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            first = sync_codex_skill(target)
            self.assertTrue(first["installed"])
            second = sync_codex_skill(target)
            self.assertEqual(second["status"], "current")
            self.assertFalse(second["updated"])

            installed = target / "init-agent-orientation" / "SKILL.md"
            installed.write_text(installed.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
            self.assertEqual(codex_skill_status(target)["status"], "modified")
            synced = sync_codex_skill(target)
            self.assertTrue(synced["updated"])
            backup = Path(synced["backup_path"])
            self.assertTrue(backup.is_dir())
            self.assertNotEqual(backup.parent, target)
            self.assertFalse(list(target.glob("init-agent-orientation.bak-*")))
            self.assertEqual(codex_skill_status(target)["status"], "current")

    def test_sync_migrates_legacy_backups_outside_skill_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            sync_codex_skill(target)
            legacy = target / "init-agent-orientation.bak-legacy"
            legacy.mkdir()
            (legacy / "SKILL.md").write_text("legacy backup\n", encoding="utf-8")

            result = sync_codex_skill(target)

            self.assertFalse(legacy.exists())
            self.assertEqual(len(result["migrated_backups"]), 1)
            migrated = Path(result["migrated_backups"][0])
            self.assertTrue(migrated.is_dir())
            self.assertEqual(migrated.parent, Path(tmp) / "init-agent-backups" / "skills")
            discovered = [path.name for path in target.iterdir() if (path / "SKILL.md").is_file()]
            self.assertEqual(discovered, ["init-agent-orientation"])

    def test_skill_status_distinguishes_outdated_generated_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            sync_codex_skill(target)
            installed_dir = target / "init-agent-orientation"
            installed_file = installed_dir / "SKILL.md"
            old_content = "---\nname: old\n---\n"
            installed_file.write_text(old_content, encoding="utf-8")
            manifest_path = installed_dir / SKILL_MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["installed_sha256"] = hashlib.sha256(old_content.encode("utf-8")).hexdigest()
            manifest["package_version"] = "0.1.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            status = codex_skill_status(target)
            self.assertEqual(status["status"], "outdated")
            self.assertFalse(status["modified"])

    def test_sync_cli_updates_skill_and_checks_mcp_without_writing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "skills"
            config = Path(tmp) / "config.toml"
            original = '[mcp_servers.init_agent]\ncommand = "init-agent-mcp"\n'
            config.write_text(original, encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "sync",
                            "--target-dir",
                            str(target),
                            "--config-path",
                            str(config),
                            "--hooks-path",
                            str(Path(tmp) / "hooks.json"),
                            "--json",
                        ]
                    ),
                    0,
                )
            data = json.loads(output.getvalue())
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["skill"]["installed"])
            self.assertEqual(data["mcp"]["status"], "configured")
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_codex_mcp_status_reports_missing_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")
            result = codex_mcp_status(config)
            self.assertFalse(result["configured"])
            self.assertEqual(result["status"], "missing_server")

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
