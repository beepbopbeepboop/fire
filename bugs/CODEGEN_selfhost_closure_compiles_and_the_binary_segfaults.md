# `selfhost`: the self-host closure COMPILES AND LINKS; the produced binary segfaults on a two-line program

**State: OPEN, measured 2026-10-04, and it REPLACES six docs** — all six of
which described a failure this job no longer has. They were written on
2026-10-02 against trees where the generated C did not compile; that is fixed
on this tree, and their numbers (67 / 80 / 149 / 157 distinct `error:` lines,
`'_mojo_elem_repr_<Node>' undeclared`, `'struct _<module>_toplev' has no
member named 'X'`, `passing argument 1 of 'mojo_repr_list_ints' makes pointer
from integer`) no longer reproduce at all. Keeping six docs that each cost the
next reader a four-minute measurement to re-derive a conclusion that is now
false is the failure mode `bugs/` is supposed to prevent, so they are deleted
and this one carries the measured state.

## What I ran

```sh
python3 tools/memslot.py --gb 8 --label selfhost -- python3 tools/suite.py -j1 selfhost
```

which is `python3 test_selfhost.py` under the runner. 914 s and 643 s on two
runs of this branch, peak 4.4 GB.

## What I see

```
  self-host closure: 62 modules, every generator/async lowered in place or its module refused whole: True
  dylib module path refuses an unlinkable generated_cpp: True
  self-host closure: 1555 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Built: /Users/mrs/net/chatgpt/claude/work-422/.tmp/tmpjsttg9_q/mojo_selfhost
  self-hosted compiler on a two-line program: exit=-11 ci_bytes=0 stub_hits=0
  ✗ the self-hosted binary did not exit 0
Results: 1 passed, 1 failed
✗ self-host compile/link regressed (GCC error, ICE, undefined symbol, or the produced binary cannot compile)
```

`Built:` is the load-bearing line and it is NEW relative to every one of the
six docs it replaces: **the whole-closure `.ci` compiles AND links.** All three
static halves are green. `test_selfhost.py`'s verdict sentence still says
"compile/link regressed", which is its one fixed wording for the build half
being red — it is now the RUN half that is red, and the sentence is what makes
the job's own output misleading about which stage failed.

Independently confirmed at the gcc level, on the same closure, with the exact
recipe `bugs/CODEGEN_selfhost_closure_still_fails_gcc.md` gave:

```
$ python3 -c "import gimple_codegen; open('.tmp/fire_full.ci','w').write(
      gimple_codegen.compile_to_gimple_cached(open('fire.py').read(),
      do_imports=True, filename='fire.py'))"          # 44.6 MB, peak 1.3 GB
$ $(python3 -c 'from build_config import find_gcc; print(find_gcc())') \
      -fgimple -fsyntax-only -O0 -g3 -ftrivial-auto-var-init=zero \
      -I runtime $(python3-config --cflags) -x c .tmp/fire_full.ci
gcc rc=0
$ grep -cE "^[^ ].*\.(py|ci|h|c):[0-9]+:[0-9]+: error: " .tmp/selfhost_gcc.txt
0
$ grep -c " error: " .tmp/selfhost_gcc.txt
7
```

All seven unfiltered matches are the compiler's OWN source text quoting gcc
diagnostics inside the generated C (`gimple_codegen.py:4331`'s "internal
compiler error: in build2", `mojo/middle/types.py`'s "compile error: the
callee's C prototype carries no defaults", `fire.py`'s `print(f"JIT error: …")`)
— which is precisely the counting trap
`bugs/CODEGEN_selfhost_closure_still_fails_gcc.md` warned about, and why the
filtered count is the one to read. The tree is clean.

The same closure's companion, measured because
`bugs/CODEGEN_refuse_dropped_companion_matches_a_prefix_nothing_emits.md`
needed it and refused to guess:

```
_run_pipeline(fire.py, do_imports=True) ->
  ci bytes       44647501
  cpp bytes      0          <- NO C++ companion is produced at all
  cpp symbols    0
  ci  symbols    0
  mgco in ci     True       <- every generator goes down the stack-switch path
```

## It is NOT a regression from the branch that found it

The branch base (`ccb157ed`, the merge this worker started from) was extracted
with `git archive` into `.tmp/base` and `test_selfhost.py` run there
unmodified — same command, same ceiling, 4.3 GB:

```
  self-host closure: 62 modules, every generator/async lowered in place or its module refused whole: True
  self-host closure: 1548 functions, 1 of them declared in fire_runtime.h under a pinned C name; every such declaration matches its definition: True
Built: /Users/mrs/net/chatgpt/claude/work-422/.tmp/tmpgae36mkq/mojo_selfhost
  self-hosted compiler on a two-line program: exit=-11 ci_bytes=0 stub_hits=0
  ✗ the self-hosted binary did not exit 0
Results: 1 passed, 1 failed
```

**Identical stage, identical symptom, identical numbers** (`exit=-11`,
`ci_bytes=0`, `stub_hits=0`), and the only difference is the function count:
1548 on the base against 1555 here, which is exactly the seven functions this
branch added to the closure: the four from the star-spread fix
(`mojo/middle/types.py`'s `is_star_spread`, and
`mojo/backend_gimple/emit_exprs.py`'s `_is_star_spread`, `_emit_star_spread` and
`_literal_slot_kinds`), `mojo/middle/lambdareduce.py`'s `lambda_bound_to` and
`params_supplied_at_calls`, and `emit_calls.py`'s `_pad_lambda_defaults`.

So this is a standing red, it is not mine, and a session that reads a red
`selfhost` in the gate after merging this branch should read it as inherited.

## Why it still matters

`selfhost` is in `check` and in `gate` and carries **no `expect=` marker**, so
this is an *undeclared* red — every one of the six docs it replaces said so, and
it is still true. Everything downstream of the self-host BUILD is therefore
unmeasured too: `mojoc`, `native-dumpfull`, `bootstrap-stage1-*` and
`bootstrap-stage2-cc`.

## The exact next step

The failure is now a single, much narrower question than any of the six docs
posed, and it is a RUNTIME fault in the produced binary, not a codegen one:

1. Keep the binary. `test_selfhost.py`'s `build()` chdirs into a
   `tempfile.mkdtemp()` and nothing copies `mojo_selfhost` out, so the one
   artifact that would answer this is deleted at the end of every run —
   which is why this has cost three sessions a full build each. A two-line
   `shutil.copy(out, os.path.join(REPO, 'build', 'mojo_selfhost'))` after the
   `Built:` line would turn the next attempt into a 10-second lldb session
   instead of a 15-minute rebuild. That is a change to
   `bugs/TEST_*` territory rather than a compiler fix, and it is the cheapest
   thing on this page.
2. `x = 1\nprint(x)\n` is the whole input, so the crash is early and does not
   need the closure's full behaviour: run it under lldb, take the backtrace,
   and the first frame inside a `_mojo_*` runtime entry point names the
   mechanism. `ci_bytes=0` says the crash happens before any `.ci` is written,
   and `stub_hits=0` says no `weak` "unavailable in compiled mode" stub is in
   play — which rules out the whole class
   `run_produced_binary`'s own docstring documents (a stub returning nothing
   made every `for node in <stub>(...)` iterate zero times), and is worth
   recording so the next reader does not start there.
3. `bugs/CODEGEN_module_toplevel_undefined_in_selfhost.md` and
   `bugs/CODEGEN_cas_py_never_compiles_so_the_selfhost_closure_has_no_definitions.md`
   are the two live candidates this tree still carries for a self-hosted
   compile-time crash, and neither has been re-measured since the closure
   started linking. Start with whichever the backtrace names.

## What the six deleted docs contributed, and where it went

Not all of it was stale, so it is worth saying where the load-bearing parts
went rather than dropping them:

* **The counting trap** (`grep ' error: '` matches the compiler's own quoted
  diagnostics) — reproduced above, with the filtered count beside it.
* **`_KindRow.kinds` is one byte per slot**, and a spread breaks that
  invariant — that turned out to be a REAL bug on this tree, in
  `mojo/backend_gimple/emit_exprs.py`'s literal lowerings, and is fixed. The
  general statement it rests on is recorded in that function's docstring.
* **A module-level global read at function scope must be a field of its
  module's `_toplev` struct** — that no longer reproduces, and
  `mojo/backend_gimple/module_gen.py`'s own comment on the deliberate
  non-rollback of `_module_globals` (which one of the six docs named as the
  leading candidate) is unchanged and still the right place to read if it ever
  comes back.
* **157 errors is a property of an earlier tree, not of the registry** — kept
  here as the standing argument for why no doc here states a count.

## Related

- `bugs/CODEGEN_bootstrap_stage2_dump_is_empty.md` — the other half of the
  self-host story, and a different subject: this is about the produced BINARY,
  that one about the `--dump` artifact the stage2 compiler writes.
- `bugs/UNTESTED.md` §3.3 — "a non-zero exit is the only verdict
  `tools/suite.py` can see", and this is a step below that: the binary links,
  runs, and produces nothing.