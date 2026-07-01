from __future__ import annotations

import os
import json
import argparse
import sqlite3
import subprocess
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
from init_agent.text_tokens import identifier_terms, tokenize_query
from experiments.evaluate import (
    candidate_paths_for_case,
    case_command,
    expected_ranks,
    load_cases,
    measure_indexed_file_read,
    render_markdown_summary,
    resolve_case_repo,
    result_csv_row,
    scan_reduction_percent,
    strict_failures_for,
    summarize,
)


class InitAgentTestCase(unittest.TestCase):
    pass


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


def _create_php_trace_fixture(root: Path) -> Path:
    (root / "composer.json").write_text('{"name": "sample/trace"}\n', encoding="utf-8")
    include = root / "include"
    assets = root / "assets"
    include.mkdir()
    assets.mkdir()
    (root / "index.php").write_text(
        "<?php\n"
        "require_once 'include/bootstrap.php';\n"
        "include 'include/header.php';\n"
        "include 'include/page.php';\n"
        "include 'include/footer.php';\n",
        encoding="utf-8",
    )
    (include / "bootstrap.php").write_text(
        "<?php\n"
        "require_once 'helpers.php';\n"
        "$page = loadCurrentPage();\n",
        encoding="utf-8",
    )
    (include / "helpers.php").write_text(
        "<?php\n"
        "function loadCurrentPage() { return ['title' => 'Auto generated title', 'body' => 'Demo']; }\n"
        "function escapeText($value) { return htmlspecialchars($value, ENT_QUOTES, 'UTF-8'); }\n",
        encoding="utf-8",
    )
    (include / "header.php").write_text(
        "<?php ?><html><head><title><?= escapeText($page['title']) ?></title></head><body>\n",
        encoding="utf-8",
    )
    (include / "page.php").write_text(
        "<?php\n"
        "function renderPageTitle($page) { echo '<h1 class=\"page-title\">' . escapeText($page['title']) . '</h1>'; }\n"
        "renderPageTitle($page);\n"
        "echo '<main>' . escapeText($page['body']) . '</main>';\n",
        encoding="utf-8",
    )
    (include / "footer.php").write_text("<?php ?></body></html>\n", encoding="utf-8")
    (include / "admin_title_tools.php").write_text(
        "<?php\nfunction rebuildAllTitles() { echo 'title maintenance'; }\n",
        encoding="utf-8",
    )
    (assets / "title-preview.js").write_text(
        "export function previewTitle(value) { return `<h1>${value}</h1>`; }\n",
        encoding="utf-8",
    )
    return root


def _create_route_template_trace_fixture(root: Path) -> Path:
    (root / "project").mkdir(parents=True)
    (root / "blog" / "templates" / "blog").mkdir(parents=True)
    (root / "project" / "urls.py").write_text(
        "from django.urls import path\n"
        "from blog import views\n\n"
        "urlpatterns = [\n"
        "    path('posts/<int:pk>/', views.detail, name='detail'),\n"
        "]\n",
        encoding="utf-8",
    )
    (root / "blog" / "views.py").write_text(
        "from django.shortcuts import render\n"
        "from .models import Post\n\n"
        "def detail(request, pk):\n"
        "    post = Post.objects.get(pk=pk)\n"
        "    return render(request, 'blog/detail.html', {'post': post})\n",
        encoding="utf-8",
    )
    (root / "blog" / "models.py").write_text("class Post:\n    pass\n", encoding="utf-8")
    (root / "blog" / "templates" / "blog" / "detail.html").write_text("<h1>{{ post.title }}</h1>\n", encoding="utf-8")
    _prepare_index(root)
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


__all__ = [name for name in globals() if not name.startswith("__")]


if __name__ == "__main__":
    unittest.main()
