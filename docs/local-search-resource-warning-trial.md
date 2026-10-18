# Compact search on a SQLite resource-warning investigation

2026-10-18. Real local maintenance task; no model benchmark or paid API runs.

The existing full-suite log reported two unclosed SQLite connections without
identifying their allocation sites. One live MCP search for `sqlite connection
close metadata`, restricted to `init_agent/`, returned complete implementations
of `GraphStore.__init__` and `connect_metadata`. Both include exception cleanup.
No call paths were requested or automatically returned. Stale saved notes were
marked as such and were not treated as current implementation evidence.

The search did not locate the defect: the chosen prefix excluded tests. Direct
search for SQLite connections in `tests/` found two uses of
`with sqlite3.connect(...)` in `tests/test_trajectory.py`. That context manages
transactions but does not close the connection. Both blocks only read data.
They now use `contextlib.closing` to close the connection on exit.

Verification on Python 3.14.7 ran the eight trajectory tests with ResourceWarning
capture and explicit garbage collection. Before the change, all eight tests
passed but emitted two unclosed-database warnings. After the change, all eight
passed with zero resource warnings. The diagnostic full-suite run before the
fix separately attributed the warnings to the two trajectory tests; its known
Unix-socket sandbox error is unrelated. `git diff --check` passed.

This case confirms usable complete-function output and a real maintenance fix.
It does not demonstrate net savings from search: direct test search and runtime
warning capture found the cause, and the initial MCP query was an extra step.
No relations were needed, so the compact default avoided irrelevant expansion.
