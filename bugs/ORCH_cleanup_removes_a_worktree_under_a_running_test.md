# ORCH: `control.py cleanup` removes a detached master worktree while a test runs in it

Found 2026-11-10. A full gimple-runner run on master was started in a detached worktree
`work-gr-master` (HEAD = master). Partway through, the directory was gone, and the run reported 219 passed / 360
failed, with messages such as "cannot compile this module to a single .ci". That result is invalid. A clean re-run from
`git archive master` (not a worktree) gives 550 passed / 29 failed.

## Cause

`tools/control.py cleanup` removes worktrees "whose HEAD is an ancestor of master, are clean and not running, with no
live opencode session and no outside claim". A detached worktree at master meets all of that, and a plain test run is
not a control worker, so nothing protects it.

## Next step

Either exempt worktrees that hold a live process (a `cwd` check, or a lock file written by the runner), or make the
runner export its own tree before it runs. Until then, run full-suite comparisons from `git archive <commit>` into a
scratch directory, which is not a worktree.
