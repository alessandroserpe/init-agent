# Optional test lookup

Use `repo_test_candidates` when a known Python function needs verification,
replacing a manual test-name search and test-body read. There is no prerequisite
orientation, index build, skill step or background service.

MCP (core and full profiles):

```json
{"module":"init_agent.signatures","symbol":"minimize_signature","limit":3}
```

CLI:

```sh
init-agent tool repo_test_candidates --module init_agent.signatures --symbol minimize_signature --json
```

The response includes directly calling tests, assertion lines, current test-file
SHA-256, complete bounded test source and a command candidate. Calls used directly
inside assertions rank ahead of call-only evidence. Read the assertion to judge
whether it checks the behavior being changed; execution remains a separate normal
verification action. When adding a regression, run its enclosing module as needed.
The tool does not import tests, execute commands or update repository metadata.

`no_direct_test_found` means no supported direct evidence was found, not that the
behavior is untested. No keyword-neighbor test is substituted. Fixtures, wildcard
and relative imports, indirect calls, result-variable propagation and dynamic
patching are not resolved. Input is a dotted module and top-level function name;
methods and other languages are not currently supported.

Test discovery currently scans eligible Python files under `tests/`, respecting
repository exclusions. Explicit import aliases are recognized. Shadowed bindings
are rejected conservatively. A class base ending in TestCase suggests unittest;
conventionally named Test classes and module-level tests suggest pytest. These
are runner candidates, not verified collection; unknown classes have no command.
Custom loaders, inheritance and decorators may require different execution.

## Bounds and freshness

At most 1,000 test files are scanned per call under the repository work budget.
Each file has a 256,000-character and 20,000-node parse cap plus existing parser
preflight limits. Unreadable or unparseable files are reported with bounded
warnings. Limit defaults to three candidates (maximum five). Test source is
omitted rather than cut if it exceeds 8,000 characters. The complete result is
bounded to 24,000 JSON characters; omitted sources/candidates are explicit.
Call/assertion evidence lists are bounded and marked when clipped. Snapshot
hashes reflect source read during the call, not atomic consistency across files.

An installed MCP process needs a new session after upgrading the package to expose
this tool. No skill sync is required when the skill has not changed. The schema
adds a small tool description to the MCP surface, but no mandatory workflow.
