# FORMAL: the doc index's queue misses every formal doc the swarm moved into bugs/mid/

Found 2026-11-13 while merging master into `work/fix-merge-bug-formal-dylib-branchy-termination-wal-2` (the
branchy-termination fix): the merge forced a re-derivation of `bugs/OPEN_WORK.md`'s generated queue, and the block the
tool renders from the merged tree names two documents when the tree carries five formal documents.

## Measured

`tools/formal_doc_index.py`'s `rows()` scans one directory:

    entries = [(n, os.path.join(BUGS, n)) for n in os.listdir(BUGS)]

under the comment "the formal documents live in bugs/ (moved there 2026-10-31); all in one directory". The swarm's
directory-class reorg (35e261a02, "The swarm moved 1 doc(s) to the directory of their class (the class is the location)",
and its siblings) moved formal documents into `bugs/mid/` without updating the tool. In the merged tree:

- `bugs/FORMAL_dylib_stack_floor_guard_never_fires.md` — IN the queue
- `bugs/FORMAL_doc_index_queue_misses_docs_in_bugs_mid.md` — IN the queue (this doc)
- `bugs/mid/FORMAL_arm64_instruction_coverage.md` — missing
- `bugs/mid/FORMAL_concrete_eval_eq_mojo_instances_omit_the_two_arg_env.md` — missing
- `bugs/mid/FORMAL_svc_exit_handling_incomplete.md` — missing, and it is the doc the formal-dylib marker in
  `tools/suite.py` cites for its 3 failures

`python3 tools/formal_doc_index.py --json` prints two records; `--check` is green on the two-record block, so the gap
is silent: the suite's formal-doc-index job passes, and the queue's own header ("THE QUEUE — derived, and it cannot be
edited by hand") describes a queue that is derived from a subset of the corpus.

## Expected

Every formal document in the tree is a row of the queue, wherever the class directories put it, so a worker triaging
from `bugs/OPEN_WORK.md` sees the same set `find bugs -name 'FORMAL_*.md' -o -name 'LEAN_*.md'` finds.

## Next step

1. Decide the scope in one line: `rows()` walks `bugs/` and its subdirectories (`os.walk`), or names the class
   directories explicitly. `bugs/sweeps/` and `bugs/hard/` are the questions the walk answers — a `FORMAL_*` sweep map
   is work, and a `hard/` doc is work too, so the walk is the right default unless the queue is meant to curate; say
   which in the fix.
2. Re-run `python3 tools/formal_doc_index.py --write` and `--check` (green afterwards, and the block grows from 2 rows
   to 5), `tools/dangling_doc_refs.py --ratchet` (the new rows cite nothing deleted), and `test_suite.py` (the
   formal-doc-index job reads the block; nothing else does).
3. Delete the "all in one directory" sentence in `rows()`'s comment, which is the rot this fix removes.
