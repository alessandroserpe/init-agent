"""Adversarial repository-wide budgets and executable selection regressions."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from init_agent.cli import main
from init_agent.executables import resolve_executable
from init_agent.graph_store import GraphStore
from init_agent.repo_budget import (BudgetConnection, RepoBudget, WorkBudgetExceeded,
                                   CURRENT_BUDGET, budget_scope)
from init_agent.relation_resolver import rebuild_resolved_relations, _module_index
from init_agent.trajectory import CODEX_HOOK_EVENTS
from init_agent.trajectory_hooks import install_codex_trajectory_hooks, codex_trajectory_hook_status
from init_agent.utils import ensure_agent_dir, iter_indexable_files, run_git_read, sha256_file
from tests.support import _create_context_fixture, _prepare_index


def small_budget(**limits):
    budget = RepoBudget()
    budget.limits.update(limits)
    return budget


class RepositoryBudgetTests(unittest.TestCase):
    def test_git_and_default_hook_ignore_repository_path_lookalikes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            root.mkdir()
            (root / '.git').mkdir()
            for name in ('git', 'init-agent-hook'):
                executable = root / name
                executable.write_text('#!/bin/sh\ntouch EXECUTED\n')
                executable.chmod(0o700)
            with patch.dict(os.environ, {'PATH': '.:' + str(root)}), \
                 patch('init_agent.executables.sys.executable', str(root / 'python')), \
                 patch('init_agent.executables.sysconfig.get_path', return_value=str(root)):
                git = resolve_executable('git', root=root, required=True)
                self.assertTrue(Path(git).is_absolute())
                self.assertFalse(Path(git).is_relative_to(root))
                result = run_git_read(root, '--version')
                self.assertEqual(result.returncode, 0)
                self.assertTrue(result.stdout.startswith('git version'))
                hook = resolve_executable('init-agent-hook', root=root)
                if hook:
                    self.assertFalse(Path(hook).is_relative_to(root))
            self.assertFalse((root / 'EXECUTED').exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX executable permission checks')
    def test_hook_configuration_pins_absolute_executable_and_upgrades_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'hooks.json'
            legacy = {'hooks': {event: [{'hooks': [{'type': 'command', 'command': 'init-agent-hook --init-agent-trajectory-hook'}]}]
                                for event in CODEX_HOOK_EVENTS}}
            target.write_text(json.dumps(legacy))
            self.assertFalse(codex_trajectory_hook_status(target)['current'])
            with self.assertRaises(ValueError):
                install_codex_trajectory_hooks(target, command='./init-agent-hook')
            unsafe = Path(temp) / 'hook'
            unsafe.write_text('#!/bin/sh\nexit 0\n')
            unsafe.chmod(0o777)
            with self.assertRaises(ValueError):
                install_codex_trajectory_hooks(target, command=str(unsafe))
            result = install_codex_trajectory_hooks(target, command='/usr/bin/true')
            self.assertTrue(result['current'])
            for groups in json.loads(target.read_text())['hooks'].values():
                self.assertTrue(groups[0]['hooks'][0]['command'].startswith(str(Path('/usr/bin/true').resolve())))

    def test_database_fetchall_and_vm_work_stop_before_unbounded_materialization(self):
        with closing(sqlite3.connect(':memory:', factory=BudgetConnection)) as conn:
            conn.execute('CREATE TABLE items(value TEXT)')
            conn.executemany('INSERT INTO items VALUES (?)', [('small',)] * 100)
            conn.commit()
            budget = small_budget(rows=3)
            with self.assertRaisesRegex(WorkBudgetExceeded, 'rows'):
                with budget_scope(budget):
                    conn.execute('SELECT * FROM items').fetchall()
            self.assertEqual(budget.used['rows'], 4)
            with self.assertRaisesRegex(WorkBudgetExceeded, 'bytes'):
                with budget_scope(small_budget(bytes=300)):
                    conn.execute('SELECT * FROM items').fetchall()
            with self.assertRaisesRegex(WorkBudgetExceeded, 'sql_steps'):
                with budget_scope(small_budget(sql_steps=1000)):
                    conn.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n').fetchone()

    def test_enumeration_depth_and_file_bytes_share_operation_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(30):
                (root / f'f{index}.py').write_text('x=1')
            with self.assertRaisesRegex(WorkBudgetExceeded, 'entries'):
                with budget_scope(small_budget(entries=5)):
                    iter_indexable_files(root)
            with self.assertRaisesRegex(WorkBudgetExceeded, 'io_bytes'):
                with budget_scope(small_budget(io_bytes=4)):
                    sha256_file(root / 'f0.py')
                    sha256_file(root / 'f1.py')
            with self.assertRaisesRegex(WorkBudgetExceeded, 'path complexity'):
                _module_index({'/'.join(['deep'] * 65) + '/file.py': 1})

    def test_git_output_ceiling_terminates_child(self):
        with tempfile.TemporaryDirectory() as temp:
            command = [sys.executable, '-c', 'import os; os.write(1, b"x" * 1000000)']
            with patch('init_agent.utils.git_read_command', return_value=command), \
                 self.assertRaisesRegex(WorkBudgetExceeded, 'Git'):
                with budget_scope(small_budget(git_bytes=128)):
                    run_git_read(Path(temp))

    def test_cli_and_mcp_report_incomplete_operations(self):
        from init_agent.mcp_server import InitAgentMcpServer
        from init_agent import mcp_server
        with tempfile.TemporaryDirectory() as temp:
            root = _create_context_fixture(Path(temp))
            _prepare_index(root)
            output = io.StringIO()
            token = CURRENT_BUDGET.set(small_budget(rows=1))
            try:
                with patch('init_agent.cli.project_root', return_value=root), redirect_stdout(output):
                    self.assertEqual(main(['overview', '--json']), 1)
            finally:
                CURRENT_BUDGET.reset(token)
            self.assertTrue(json.loads(output.getvalue())['truncated'])
            server = InitAgentMcpServer(root)
            name = next(iter(server.enabled_tools))
            with patch.dict(mcp_server.MCP_TOOL_HANDLERS, {name: lambda *_: (_ for _ in ()).throw(WorkBudgetExceeded('incomplete'))}):
                result = server._call_tool({'name': name, 'arguments': {}})
            self.assertTrue(result['isError'])
            self.assertTrue(result['structuredContent']['truncated'])

    def test_relation_rebuild_budget_failure_rolls_back_deletions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ensure_agent_dir(root)
            with GraphStore(root) as store:
                store.initialize()
                store.connection.execute("INSERT INTO relations(source_type,source_id,relation,target_type,target_id,confidence,metadata_json) VALUES ('file',1,'calls','resolved_file','keep.py',1,'{}')")
                store.connection.commit()
                with self.assertRaises(WorkBudgetExceeded):
                    with budget_scope(small_budget(records=2)):
                        rebuild_resolved_relations(store)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM relations').fetchone()[0], 1)
