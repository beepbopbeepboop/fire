# Claim triage before the orchestrator restart (2026-11-11)

Before the restart, every registry entry that held a claim without having landed was triaged. Landing was cheap-gate
only (`stdlib-syntax`); the full gate was not run.

## Landed (merged to master, entry marked integrated, branch and worktree removed)
- `bug-codegen-cpp-path-container-literal-i`
- `bug-orch-cleanup-removes-a-worktree-unde-3292`
- `bug-python3-15-lazy-imports-8186`
- `fix-red-bug-import-ambiguous-sibling-function` (its worktree `work-6583` still holds an UNCOMMITTED edit to
  `mojo/backend_gimple/emit_funcs.py`, so that worktree and its branch were kept)

## Abandoned (claim released; branch and worktree kept)
- 16 `fix-replan-*` entries. Their branches change only docs and `TASK.md`, and the docs they touch are on master.

## Still holding a claim (left on purpose)
| entry | why it was not landed |
|---|---|
| `bug-diagnostics-module-not-found-suffix` | merges clean, but deletes its doc with no test change, so the deletion rule refuses it. Needs a person. |
| `bug-codegen-enum-member-eq-prints-int-no` | merge conflict with master |
| `bug-codegen-linked-list-hash-stubbed` | merge conflict with master |
| `bug-mid-suite-gimplegenerators-6583` | merge conflicts (2), SUITE work |
| `bug-suite-doc-refs-ratchet-red-r36` | 29 commits, merge conflict, SUITE work |
| `bug-suite-residue-budgets-after-estate-r` | SUITE work |
| `bug-mid-gate-red-recover-land-2026-11-02-2747` | gate-red history, not triaged |
| `bug-formal-elf-dylib-nonzero-tail-past-l-196` | formal lane, owned by the formal worker |
| `fix-red-fix-red-fix-red-fix-red-fix-red-fix-merge-fix-leftov` | its doc is gone; not triaged |
| `recover-apply-haiku-r2-r2-r2-r2-r2-r332` | other lane (archive), 167 commits, not touched |
| `recover-review-dangling-r2-r2-r2-r30` | other lane (archive), 30 commits, not touched |
