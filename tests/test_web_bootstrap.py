"""Execute the bootstrap JavaScript with controlled HTTP/network outcomes."""
import json
import shutil
import subprocess
import unittest

from init_agent.web_ui import _BOOTSTRAP


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed to execute browser bootstrap JavaScript')
class WebBootstrapTests(unittest.TestCase):
    def test_temporary_failures_preserve_capability_and_retry_works(self):
        script = _BOOTSTRAP.split('<script>', 1)[1].split('</script>', 1)[0]
        harness = r'''
const vm = require('node:vm');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', async () => {
  const source = JSON.parse(input);
  const results = [];
  for (const outcome of [503, 403, 'network', 'body', 401, 200]) {
    const storage = new Map([['init-agent-capability', 'private-test-token']]);
    const status = {textContent: ''};
    let page = '', next = outcome, requests = 0;
    const context = {URLSearchParams, location: {hash: '', pathname: '/'},
      history: {replaceState() {}},
      sessionStorage: {getItem: key => storage.get(key), setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)},
      document: {getElementById: () => status, open() {}, write(text) {page = text}, close() {}},
      fetch: async (url, options) => {
        requests++;
        if (options.headers.Authorization !== 'Bearer private-test-token') throw Error('bad authorization');
        if (next === 'network') throw Error('offline');
        return {ok: next === 200 || next === 'body', status: next,
                text: async () => {if (next === 'body') throw Error('interrupted body'); return '<html>dashboard</html>'}};
      }};
    await vm.runInNewContext(source, context);
    const retained = storage.has('init-agent-capability');
    const firstMessage = status.textContent;
    next = 200;
    await vm.runInNewContext(source, context);
    results.push({outcome, retained, firstMessage, page, requests});
  }
  process.stdout.write(JSON.stringify(results));
});
'''
        result = subprocess.run(['node', '-e', harness], input=json.dumps(script),
                                capture_output=True, text=True, check=True, timeout=10)
        for row in json.loads(result.stdout):
            with self.subTest(outcome=row['outcome']):
                unauthorized = row['outcome'] == 401
                self.assertEqual(row['retained'], not unauthorized)
                self.assertEqual(row['requests'], 1 if unauthorized else 2)
                self.assertEqual(row['page'], '' if unauthorized else '<html>dashboard</html>')
                if row['outcome'] != 200:
                    self.assertIn('Access expired' if unauthorized else 'Refresh', row['firstMessage'])
