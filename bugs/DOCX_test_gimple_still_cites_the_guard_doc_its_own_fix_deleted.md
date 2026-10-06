# `test_suite.py`'s dangling-refs sweep is red on the ONE citation `tools/dangling_doc_refs.py --ratchet` excuses

**Area:** tools / tests. **Status: OPEN, measured, PRE-EXISTING on `master`
(77b24183), not fixed here.** Found while merging five finished formal branches
into `work/merge-formal27a` and running `python3 test_suite.py`, which the merge
task requires. It is not caused by any of those five branches: a pristine
`git archive master` reproduces it (§"What I saw", second command).

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py
  ...
FAIL  dangling refs: ...and outside those controls the corpus is empty, which is
what a sweep buys: 1 dangling citation(s) outside test_suite.py
(['CODEGEN_refuse_dropped_companion_matches_a_prefix_nothing_emits']);
a new one is a ratchet failure

# attribution, on a pristine copy of master rather than on the merge:
$ mkdir -p .tmp/masterchk && git archive master | tar -x -C .tmp/masterchk
$ (cd .tmp/masterchk && python3 test_suite.py)      # same check, same 1
```

## Why it is not the ratchet's business, and why that is the confusing part

The two instruments disagree about this one citation, and both are green/red for
a reason that is correct on its own terms:

| instrument | verdict on this citation | why |
|---|---|---|
| `tools/dangling_doc_refs.py --ratchet` | **exit 0** | the citing file's per-file ceiling in `tools/dangling_refs_baseline.py` already allows it, so the corpus can only shrink |
| `test_suite.py`'s own sweep (`dangling refs: ...outside those controls the corpus is empty`) | **FAIL** | it asserts the corpus is *empty*, not "no larger than a baseline" — the message says so: "a new one is a ratchet failure" |

So `doc-refs` (the registered `check` job that runs the ratchet) is green and
`suite-self-test` (also a `check` job) is red, over one comment line. The ratchet
was written per file so that a worker who cannot edit another area is not made
red by it; `test_suite.py`'s sweep is the stricter instrument that says the
corpus is supposed to be zero.

## Where the citation is

`test_gimple.py:6816`, the last line of the comment block above
`test_raises("nested_generator_needing_the_cpp_companion_is_refused_by_name", …)`:

```python
    # It is now the intersection of the two artifacts' own symbol names, which
    # is what makes it un-rot-able: a rename on the emitting side moves both
    # halves together. See
    # bugs/<the guard's own doc, deleted by 1fa4c6e8>.
```

(The offending line is quoted with its filename replaced: a bug doc that cites
the dangling name it is reporting makes this doc its OWN ratchet failure, which
is a small enough joke that it is worth writing down rather than rediscovering.)

The guard's own doc — the one whose basename is the name this doc's FAIL line
prints — was deleted by `1fa4c6e8` ("Delete the guard doc: _refuse_dropped_companion now
fires, and it costs no job") — i.e. the bug is FIXED and the doc went with the
fix, which is what CLAUDE.md's rule asks for. The comment describing the fix is
the part worth keeping; only its last clause names a path that no longer exists.

## The exact next step

One line, in the compiled path's own test file:

1. Replace that trailing `See bugs/…` with the commit that fixed it (`1fa4c6e8`)
   or with the symptom the deleted doc described — the guard searched `.ci` for
   `__mojogen_` (two underscores) while `mojo/backend_gimple/cpp_async.py` emits
   `_mojogen_` (one), so it could never fire. Naming the SYMPTOM is enough and is
   what the ratchet asks for; it does not need the doc's filename.
2. That takes `tools/dangling_refs_baseline.py`'s ceiling for `test_gimple.py`
   down by one at the same time: `--write-baseline` regenerates the ceilings and
   prints what moved. **Read that diff** — the ceiling exists so the corpus can
   only shrink, and a regenerated baseline that does not shrink it means the
   citation was not the one you removed.

## Why it is filed rather than fixed here

`test_gimple.py` is the compiled path's test file, and `gimple_codegen.py` /
`mojo/backend_gimple/*` / `test_gimple.py` are the area several
`bugs4-*`/`bugs6-*`/`bugs7-*` workers hold claims in. The merge task's rule 5
says to report an obstacle in another worker's area rather than edit it, and a
one-line comment edit on a file that many branches touch is a collision waiting
to happen for no gain in a formal merge. It is also pre-existing, so no merge
made it worse.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_suite.py 2>&1 \
    | grep 'dangling refs'
$ python3 tools/dangling_doc_refs.py --ratchet; echo "ratchet exit=$?"   # 0
```