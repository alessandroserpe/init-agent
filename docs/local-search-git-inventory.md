# Main-checkout Git inventory with linked worktrees

2026-10-16. This is an inventory correction, not a ranking-weight change.

## Cause and constrained correction

The validator recursively visits the main administrative directory. A normal
linked-worktree registration contains worktrees/<id>/commondir pointing back to
that same administrative directory. Previously, any nonempty commondir anywhere
caused rejection, including this internal reference. Inventory then fell back to
filesystem scanning, which does not apply .gitignore.

The correction accepts only that exact relative location and the canonical
../.. value. The rest of the tree is still inspected, including symlink/special
file checks. External gitdir files, top-level commondir, other nonempty common
pointers and all object alternates remain unsupported. Repository config checks
and subprocess restrictions are unchanged. No repository configuration or
administrative pointer is rewritten. Linked checkouts that point outside their
selected root remain unsupported; this fix concerns the main checkout only.

The distinction follows Git's documented separation between main administrative
data and per-worktree registrations:
[Git repository layout](https://git-scm.com/docs/gitrepository-layout),
[Git worktrees](https://git-scm.com/docs/git-worktree).

## Evidence

Three new tests reproduce the previous failure using real temporary Git
repositories and a real detached linked worktree. They verify nested ignore
rules, negation, tracked files matching ignore patterns, untracked source files,
removal of previously indexed ignored artifacts, and rejection of malformed or
external pointers before spawning Git. Existing transport/native-isolation and
ignore tests remain in the targeted checks, including executable Git filter
rejection. The initial targeted set passes 50 tests with two environment skips.

A maintenance call on the actual working repository changes graph file count
from 883 to 240. Previously indexed files under experiments/agent-runs/results
fall from 649 to zero. The source inventory also includes newly added working
files, so total removals are not equal to the final count difference. The query
for index-version/rollback handling still returns init_agent/local_search.py
first. Maintenance reports ready and the oversized-log coverage warning clears;
the usual warning about graph links remains. The measured call took about 2.3
seconds locally, not a controlled performance benchmark.

Only metadata/index entries are removed. Logs, source files, Git worktrees and
stored notes are not deleted. No claim of improved generic task ranking follows.
