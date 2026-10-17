"""Remaining work is current state; progress notes retain historical evidence."""
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from init_agent.tasks import add_task, add_task_note, update_task, close_task, get_task
from init_agent.cli import main
from init_agent.mcp_server import InitAgentMcpServer


class TaskRemainingTests(unittest.TestCase):
    def test_remaining_lifecycle_across_interfaces(self):
        for interface in ('python', 'mcp', 'cli', 'cli_tool'):
            with self.subTest(interface=interface), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                task_id = add_task(root, 'Fix warning')['id']
                add_task_note(root, task_id, 'Initial investigation', remaining=['old check'], tests=['initial test'])

                def invoke(operation, **kwargs):
                    if interface == 'python':
                        return {'update': update_task, 'close': close_task}[operation](root, task_id, **kwargs)['task']
                    if interface == 'mcp':
                        server = InitAgentMcpServer(root, profile='full')
                        response = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                            'name': 'repo_task_' + operation, 'arguments': {'id': task_id, **kwargs}}})
                        result = response['result']
                        self.assertFalse(result.get('isError', False), result)
                        return result['structuredContent']['task']
                    args = (['task', operation, str(task_id)] if interface == 'cli'
                            else ['tool', 'repo_task_' + operation, '--id', str(task_id)])
                    for key, value in kwargs.items():
                        values = (value or ['']) if isinstance(value, list) else [value]
                        for item in values:
                            args.extend(['--' + key, item])
                    out = StringIO()
                    previous = Path.cwd()
                    try:
                        os.chdir(root)
                        with redirect_stdout(out):
                            self.assertEqual(main(args + ['--json']), 0)
                    finally:
                        os.chdir(previous)
                    return json.loads(out.getvalue())['task']

                self.assertEqual(invoke('update', summary='Progress')['remaining'], ['old check'])
                self.assertEqual(invoke('update', remaining=[' new check ', 'new check'])['remaining'], ['new check'])
                self.assertEqual(invoke('update', remaining=[])['remaining'], [])
                invoke('update', remaining=['obsolete'])
                self.assertEqual(invoke('close', remaining=['follow up'])['remaining'], ['follow up'])
                closed = invoke('close')
                self.assertEqual(closed['remaining'], [])
                self.assertEqual(closed['status'], 'done')
                saved = get_task(root, task_id)
                self.assertEqual(saved['notes'][0]['remaining'], ['old check'])
                self.assertEqual(saved['tests'], ['initial test'])
