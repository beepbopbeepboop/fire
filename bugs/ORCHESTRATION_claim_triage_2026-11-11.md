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

## Follow-up: `bug-diagnostics-module-not-found-suffix` (landed as a clean branch)
The original branch also raised four ceilings in `dangling_refs_baseline.py` (BLOW, CLAUDE, CRASH, FORMAL). Those are
not carried over. The test passes on master (`test_attr_error_messages.py`), so the stale `expect=` and the doc were
removed on a clean branch, which landed as `8cace76b5`. The original entry is now abandoned; its branch and worktree
(`work-6576`) are kept, unmerged, as the record of the rejected ceilings.

## Second pass (2026-11-11), the remaining code holders
- **`bug-codegen-enum-member-eq-prints-int-no`: LANDED** (`00faedfd5`). The branch's test passes on master, so master's
  own `isinstance` fix already resolves it. The branch's doc deletion and marker removal were the change that landed.
- **`bug-codegen-linked-list-hash-stubbed`: abandoned.** The branch's test passes on master too, but the doc's open half
  (`hash(l)`) is still open: a probe of two equal lists does not link, on master and on the branch. Deleting the doc
  would have closed that. Filed as `bugs/CODEGEN_linked_list_hash_probe_link_error.md` (`b3d052c53`).
- **`bug-mid-gate-red-recover-land-2026-11-02-2747`: abandoned, not landed.** Its fix is in self-host codegen aimed at
  `mojoc` and the bootstrap jobs. Proving it needs a full self-host build, which is out of scope under the cheap-tests rule.
  Its branch stays as the record. The doc `bugs/mid/GATE_red_recover-land_2026-11-02.md` is still on master.
- **`fix-red-…-leftov`: abandoned.** Its code fix (the extern dedup publishing lists) is already on master; its only
  addition is a test assertion, not landed alone.
- **Still holding, left on purpose:** the three SUITE entries (`suite-gimplegenerators`, `suite-doc-refs-ratchet-red`,
  `suite-residue-budgets`), which you asked me to keep out of this; the formal entry (formal worker); and the two
  `recover-*` entries (other lane).

## Third pass (2026-11-11): the SUITE holders
- **`bug-suite-residue-budgets-after-estate-r`: not landed; abandoned.** The branch's census was built against an older
  master. Merged with current master, the residue check still fails: it sets the census to 23 where the walk finds 27
  files. The five files the walk counts and the census does not are `test_dict_slot_read_bug.py`,
  `test_dict_slot_read_bug_demo.py`, `test_dict_slot_read_regression.py`, `test_peekable_iterator_link.py`, and
  `test_python315_lazy_imports.py`. The check requires their call sites to be read before they are counted, which is
  review, not a number to paste. The merge is kept as `work/residue-land` (not on master).
- **`bug-mid-suite-gimplegenerators-6583`: not landed; abandoned.** Four commits of compiled-path codegen across six code
  files, with two merge conflicts. Proving it needs the generator runner, which is heavy, so it stays out under the
  cheap-tests rule. Branch and worktree (`work-6532`) kept.
- **`bug-suite-doc-refs-ratchet-red-r36`: not landed; abandoned.** Twenty-nine commits, most of them "re-verification"
  doc churn. It also raises the ceilings for BLOW, CLAUDE, CRASH and FORMAL in `dangling_refs_baseline.py`, the same
  change I refused for the module-not-found branch: the ratchet only shrinks. Branch and worktree (`work-6514`) kept.
- Note for the restart: abandoned entries whose doc is still on master will be fed again by the normal doc queue.
  That is by design, but it is the reason the SUITE docs need a decision, not just a claim release.
