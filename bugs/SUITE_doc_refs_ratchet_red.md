# SUITE_doc_refs_ratchet_red: the registered `doc-refs` gate job is red with no marker

**Status:** OPEN — recorded 2026-11-09 from `work/bug-suite-linkmode-5026-r3`
(the linkmode fix round; commit 26db2bab4). NOT introduced by that branch —
see "What I saw".

## What I ran

- `python3 tools/dangling_doc_refs.py --ratchet` at the HEAD of
  `work/bug-suite-linkmode-5026-r3` (26db2bab4).
- The same command in `git archive` snapshots of (a) the branch's base commit
  3733dc0c7 and (b) the then-tip of master, e8d10a21d (both extracted to a
  scratch dir inside the worktree; master moved underneath during the round —
  the integrator was landing other workers' branches).

## What I saw

- Exit 1 in ALL THREE trees. At my branch's HEAD and at the base commit the
  failing set is IDENTICAL: 28 files cite more deleted docs than the per-file
  ceilings in `tools/dangling_refs_baseline.py` allow (the file:count list is
  at the end of this doc; regenerate the names with
  `python3 tools/dangling_doc_refs.py --ratchet` or `--by-file`).
- `mojo/backend_gimple/module_gen.py` is in the list (5 BARE citations vs
  ceiling 4) — the file this round touched — but at the SAME count at the base
  commit: the linkmode fix commit adds no `.md` reference anywhere, so its
  overage predates the round. Every other listed file was likewise untouched by
  the branch.
- The only doc the branch deletes (the linkmode bug doc, removed in 26db2bab4)
  is cited by NO file in the tree, so that deletion contributes zero dangling
  citations — the ratchet's per-file counts are byte-for-byte the base's.
- The master-tip snapshot run flags the same 28 files plus a 29th,
  `tools/dangling_refs_baseline.py` (one BARE self-reference to a fixture name
  in its own docstring). That 29th is an enumeration artifact, not a tree
  state: in a snapshot without git, `candidates()` falls back to a filesystem
  walk that does not apply the `SELF_PATH` (baseline-file) exclusion the
  `git ls-files` path applies. A real checkout of master flags the same 28.
- `tools/suite.py` registers this ratchet as the `doc-refs` gate job (bucket
  `check`, `mem=tiny`, `cache=True`) with NO `expect=`/`disabled=` marker, so
  every `make check`/`make gate` on this tree is red on that job with nothing
  declaring it. This contradicts CLAUDE.md's "there is no undeclared red"
  statement about the registry: the corpus drifted red as other rounds deleted
  docs without rewriting the standing citations their deletions stranded — the
  script's own docstring calls this a CAMPAIGN (it grew 309→480 "while nothing
  was watching it").

## What I expected

A registered check job with no marker to be green, and the ratchet to stay
green through the linkmode doc deletion (it does — the branch is neutral).

## Why this round did not fix it

The 28 files span the whole repository — `fire_compiler.py`, `gimple_codegen.py`,
`formal/`, `mojo/middle/*`, `mojo/backend_gimple/*`, `docs/*`, `test_*.py`,
`CLAUDE.md`, `FORMAL.md`, `bugs/OPEN_WORK.md` — and most of them are in areas
other workers currently hold (`python3 tools/control.py claims`). The script's
design intent is that each citing file's owner rewrites its own stranded
citations, not that one branch absorbs the corpus. The linkmode round's scope
is the module_gen fix + its regression test + the linkmode doc deletion, all of
which leave the ratchet's per-file counts untouched.

## Exact next steps

1. For each of the 28 files below, rewrite each flagged citation to name the
   BUG (its symptom, or the commit that fixed it) instead of the deleted doc —
   or delete the sentence if the path was all it said (CLAUDE.md's
   "deleting a doc has a second half"). `python3 tools/dangling_doc_refs.py
   --by-file` prints the citing lines with line numbers.
2. Where a citation is deliberate history, put a same-line comment carrying one
   of the deleted-convention words (`bare_find` skips lines saying the doc was
   deleted: "deleted", "git rm", "now closed", "no longer", "used to give/cite/
   carry").
3. Raise a file's ceiling with `--write-baseline` ONLY after reading the diff
   it prints, for a citation that is a deliberate standing reference.
4. Until the campaign lands, add a one-line `expect=` marker to `doc-refs` in
   `tools/suite.py` naming THIS doc (a marker without a reason is a silenced
   test; the reason is the 28-file list below).
5. Verify with `python3 tools/dangling_doc_refs.py --ratchet` (exit 0) and the
   `doc-refs` job in `tools/suite.py`.

## The 28 over-ceiling files (run at 26db2bab4; regenerate anytime)

`bugs/`-prefixed class: FORMAL.md 11/10; mojo/backend_gimple/emit_exprs.py 8/7;
test_gimple_generator_runner.py 5/3; CRASH.md 4/2; mojo/backend_gimple/
emit_calls.py 4/3; CLAUDE.md 3/1; gimple_codegen.py 3/2; mojo/backend_gimple/
cpp_core.py 3/2; BLOW.md 2/1; doc/POLICY_memory_over_4gb.md 2/1;
docs/bootstrap-resource-blowup-plan.md 1/0; docs/enum-runtime-class-plan.md 1/0;
docs/linked-list-reflection-plan.md 1/0; docs/none-held-plan.md 1/0;
mojo/backend_gimple/cpp_async.py 1/0; mojo/middle/module_shared.py 1/0;
test_codegen_bootstrap_resource_regression.py 1/0;
test_generic_struct_local_linked_list.py 1/0; test_runtime_alloc_census.py 1/0;
test_runtime_class_creation.py 1/0.

BARE class: bugs/OPEN_WORK.md 16/15; mojo/backend_gimple/cpp_core.py 7/6;
bugs/hard/README.md 5/0; mojo/backend_gimple/module_gen.py 5/4;
mojo/middle/exprtypes.py 4/2; gimple_codegen.py 2/1;
mojo/middle/infra_infer.py 2/1; test_gimple_generator_runner.py 2/1.
