# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status 2026-10-30 — PARTIAL, refusal pinned, full fix deferred (no make gate)

Verified with `python3 tools/memslot.py --gb 8 --label read-table-refusal -- ...`:
PASS `cpp_for_callable_param_read_table_like`; refusal message `callable-valued parameter '_get_reader'`
honest (not silent wrong). Root cause is Plan A (foreign-callable signature table + iterator
typing in `types.py`/`infra_infer.py`/`cpp_core.py` + `coro.py` eligibility) — a multi-session
feature project requiring `make gate`. Not attempted in this session per constraint.
Doc kept (not deleted): `tables.py` compile failure remains tracked; `c_analyzer/__init__.py`
and `c_common/fsutil.py` share the same callable-valued-parameter blocker.
Regression `test_gimple_generator_runner.py` line 991 updated to match refusal.

## Status 2026-10-29 (round 2) — planning guide; the blocker is a callable-signature feature, not a `for` branch

**Measured this round.** `_regression_read_table_callable_reader`
(`test_gimple_generator_runner.py`) passes on this tree under
`python3 tools/memslot.py --gb 8 --label read-table-refusal -- python3 -c
"import test_gimple_generator_runner as t; t._regression_read_table_callable_reader()"`
(PASS, peak 0.1 GB). The refusal text is the one the test pins.

**Why the `for` branch alone cannot land.** `_cpp_for_stmt` is not missing a
branch. Three things are missing, and the loop needs all three:

1. **The parameter is not a callable at all.** `_get_reader=__import__('csv').reader`
   is a keyword-only parameter with a DEFAULT. `mojo/middle/types.py`
   `_cpp_lambda_ctype(lam)` (≈ :2470) is only ever consulted for a lambda, and
   returns `None` on ANY parameter default (`if _d is not None: return None`).
   So `_infer_param_types` (`mojo/middle/infra_infer.py:256`) leaves
   `_get_reader` at its `int64_t` fallback. A call through it therefore never
   reaches a callable path.
2. **The default has no body and no signature in this TU.** `csv.reader` is a
   C-implemented stdlib builtin: there is no `def` to lower and no
   `_cpp_declared` entry. Its return type (an iterator of `list[str]`) is not
   knowable from the body. Anything that gives it a type must come from a
   table of known foreign callables or from the caller.
3. **Element access and `fix_row` typing.** Even with a return type, the loop
   target needs a real element ctype (a `MojoList *` of strings, with per-slot
   accessors), and `fix_row(row)` (`_normalize_fix_read`) must type over it.
   Neither exists for an iterator produced by a foreign callable.

**Decision needed (cannot be decided by reading the code):**

- **(A) Foreign-callable signature table.** Add a table of stdlib callables
  whose return shape this emitter can represent (`csv.reader` →
  iterator of `list[str]`), plus a runtime iterator for it. Under this answer,
  the default's type binds from the table and `read_table` compiles.
  Cost: a csv runtime in `runtime/` and a per-callable table that must stay in
  step with real CPython. This is a real feature project.
- **(B) Call-site signature discovery.** Infer `_get_reader`'s signature from
  the call sites in the program (`read_table(..., _get_reader=...)` and the
  default). Under this answer, the default still needs (A) for the element
  type in any program that calls with the default, so (B) alone does not close it.
- **(C) Permanent refusal, documented.** Callable-valued parameters whose
  default is a foreign C callable stay refused by name (the current behaviour,
  pinned by the test above). Under this answer, the doc is deleted with
  a note that `tables.py` is out of scope, and `c_analyzer/__init__.py`'s
  `check_all` and `c_common/fsutil.py` get the same decision.

**Recommended: (A).** It is the only answer that compiles the file, and the
other two stdlib-callable files (`fsutil`'s `glob_tree`, `check_all`) need the
same table, so the decision is shared.

**Implementation plan under (A), in order:**

1. `mojo/middle/types.py` `_cpp_lambda_ctype`: admit a default whose value is a
   known foreign callable (table lookup) rather than refusing every default.
   Test: `test_gimple_generator_runner.py` — a callable parameter with a
   `csv.reader` default now gets `_CPP_CALLABLE_CTYPE` and the refusal test's
   shape compiles past that point.
2. `mojo/middle/infra_infer.py` `_infer_param_types`: consult the same table so
   the parameter is typed as callable, not `int64_t`.
3. `mojo/backend_gimple/cpp_core.py` `_cpp_for_stmt`: a new branch, placed
   after the generator-handle branch and before the generic path, for
   `for <target> in <call through a callable local>` whose callee's table
   entry gives an iterator element ctype. Loop target gets that ctype; element
   access through a new per-row accessor. Refuse by name if the entry is absent
   (keep the current refusal for unknown callees).
4. `fix_row(row)`: type-check the body with the element ctype from step 3.
5. Flip `_regression_read_table_callable_reader` from a refusal to a
   stdlib-output comparison (CPython ground truth via `tools/mojo`), and keep the
   refusal test for an UNTABLED callable.

**Quick proof for the next round:** step 1's test alone (a default-valued
callable parameter with a table default compiles and calls through correctly).
Steps 2-4 then need `read_table` itself, which is an A3-ineligible
generator (kwonly params) on the cpp path, so it will also hit
`coro.py`'s `_eligible` rule. Measure that before step 3.

**Integrator note:** steps 1-4 are compiled-path changes (`types.py`,
`infra_infer.py`, `cpp_core.py`), so the full `make gate` is owed for them.
This round changed only this doc and makes no code change.

## Status 2026-10-29 — regression test added; structural blocker untouched (PARTIAL)

Added `cpp_for_callable_param_read_table_like` regression in
`test_gimple_generator_runner.py` (passes: refusal names `_get_reader(...)`
honestly, not silently wrong). The root cause — `_cpp_for_stmt` has no
path for `for <target> in <call through callable-valued param>` — is still
missing three pieces together (typed loop target from callable return,
element access, `fix_row` typing). Shared with `c_analyzer/__init__.py`
and `c_common/fsutil.py`. No code change to `cpp_core.py`; the refusal
is correctly named per `ad7ffd96` but the loop cannot yet compile.

## Status 2026-10-04 — the refusal names the callee and still will not answer; `read_table` is the module-level blocker

Re-measured on this tree (`python3 fire.py build -o .tmp/out .tmp/ca/c_common/tables.py`,
sources from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`, arm64, ~8 s). The file still
does not build and the module-level refusal is `read_table`:

    Error building: cannot compile module: function(s) read_table (generator function(s),
      contain a `yield`/`yield from`)

`MOJO_DEBUG=1` still prints the three refusal shapes this file contributes, all unchanged
and all naming their callee:

    read_table: a `for` over a call through the callable-valued local/parameter
      '_get_reader(...)' is not supported in a compiled generator/coroutine body
    chain:      every `yield` must carry a value, and all values must agree on one
                scalar type (int64_t/double/_Bool)

**Nothing in this entry's three sub-problems has moved**, and the entry's own correction
still stands: `_get_reader` is NOT declared with either callable ctype, so step 1 is two
steps (bind the default's type, then carry a signature).

One measurement that IS new and that a next session should not have to make: **this file's
closure reaches `c_common/fsutil.py`, and `MOJO_DEBUG=1` prints fsutil's own shapes while
building `tables.py`** — `_walk_tree` and `glob_tree` refused on the same
callable-valued-parameter `for`, plus `iter_files`' variadic lambda, plus a fourth,
`iter_many`, refused on `a call to unresolved callee 'onempty(...)'`. So the three-file
grouping in the entry below ("one fix, three files") is really four, and
`the (since-fixed) c_common/fsutil.py compile failure`'s own status says its blocker list
has shrunk from four to three — `process_filenames`' `Exception(...)` is no longer among
them, so `onempty(...)` is the same shape reached from another module and both should be
counted once.

## Status 2026-10-02 — the suggested first slice is DONE: the refusal names the callable

The slice the entry below asks for ("make the refusal NAME the
callable-local case ... so the three files' shared blocker is legible")
landed in commit `ad7ffd96`. The refusal is now:

```
read_table: a `for` over a call through the callable-valued
            local/parameter '_get_reader(...)' is not supported in a
            compiled generator/coroutine body: what that call RETURNS is
            not knowable here (it depends on which callable the caller
            passes), and a `for` target needs the returned ITERATOR's
            element type. It needs the callable's signature discovered
            from its call sites first.
```

Verified on all three files the entry below groups as sharing this
blocker, each of which now names its own callee:

| file | callee named |
|---|---|
| `c_common/tables.py` | `read_table` → `_get_reader(...)` |
| `c_analyzer/__init__.py` | `check_all` → `check(...)` |
| `c_common/fsutil.py` | `_walk_tree` → `_walk(...)`, `glob_tree` → `_glob(...)` |

Regressions `cpp_for_over_callable_param_names_the_callee` and
`cpp_for_over_callable_param_leaves_resolved_callees_alone` in
`test_gimple_generator_runner.py` — the second is the negative half, so
the gate cannot be quietly too wide.

**The blocker itself is untouched, and the three sub-problems the entry
below lists are still all three.** One correction to that entry's
reasoning, measured: `_get_reader` is NOT declared with one of the two
callable ctypes. Its parameter inference gives up on a default-valued
parameter and leaves it at the `int64_t` default (measured by dumping this
unit's `declared` at the `for`), which is why the refusal's gate is "the
callee is a bare name this unit has DECLARED" rather than "the callee is
declared as a callable" — the precise predicate misses every real
instance of this shape. That is worth knowing before item 1 is started:
the parameter is not yet recognised as a callable AT ALL, so step 1 is
two steps (bind the default's type, then carry a signature), not one.

## Status 2026-09-30 — one real blocker removed; a DIFFERENT, harder one is next

Re-verified against the current tree (`python3 fire.py build`, sources copied
from `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` into `.tmp/ca/`). The
sole remaining refusal:

```
Unsupported shape(s): read_table: unsupported for-loop iterable type: CallExpr.
```

**This is progress, not the same blocker.** Until this session the sole
refusal was

```
read_table: a call to unresolved callee 'next(...)' is not supported in a
compiled generator/coroutine body
```

— `read_table` doing `lines = strutil._iter_significant_lines(infile)` then
`next(lines)`, where `read_table` is NOT A3-eligible (kwonly params →
`coro.py`'s `_eligible` returns "kwonly params (v0)") and so compiles through
the cpp C++20-coroutine path, while `strutil._iter_significant_lines` IS
A3-lowered. That combination did not work at all, because the A3 backend
filed its lowered generators only in the per-bare-name `_generator_api` and
never in the whole-program `_generator_home_api` that
`_cpp_resolve_generator_call_api` searches — so the cpp emitter could not
build a handle for a foreign A3 generator even though both backends expose
the identical `{base}_start/_resume/_value/_destroy` ABI.

Fixed in commit `93eacde6`: `publish_a3_generators`
(`mojo/backend_gimple/emit_resolve.py`) + the `for x in <generator handle>:`
case in `_cpp_for_stmt`. Regression tests
`foreign_a3_generator_handle_next` / `..._for_loop` in
`test_gimple_generator_runner.py` (both verified failing before the change;
the `for` one failed with a silent wrong answer).

### The blocker now in front of this file, and why it is hard

`read_table` (c_common/tables.py:115):

```python
for row in _get_reader(lines, delimiter=sep or '\t'):
    yield tuple(fix_row(row))
```

`_get_reader` is a DEFAULT-VALUED CALLEDABLE PARAMETER (`_get_reader=csv.reader`
in the signature at :88). Its return value's shape — a `csv.reader` object —
is not knowable at compile time: it depends on the caller's override, and
this scalar body model has no representation for a dynamically-produced
iterator (it needs the loop-variable types, which come from the iterator's
element type). This is the same family as the `check_all` blocker in
`bugs/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___init__.md` and the
`unsupported for-loop iterable type: CallExpr` family in
`the (since-fixed) c_common/fsutil.py compile failure` — i.e. three of
my files now share ONE remaining blocker, which is the right grouping for a
follow-up.

### Next step

`for <target> in <call to a callable-value local>:` where the callee is a
declared callable local (`_CPP_CALLABLE_CTYPE`) and the loop target is a
tuple. Three things are needed together, and none is a one-liner:

1. A way to give the loop variable a real type. `_cpp_for_stmt`'s
   list-iterable branch already types the target from the element type it
   derives; a callable-local call has no such derivation, so either the
   callee's declared return type must be tracked into the body model (it is
   NOT in `_cpp_declared`) or the shape must be refused more precisely than
   today's flat "unsupported for-loop iterable type: CallExpr", which does
   not even name which call it could not type.
2. Element access. `csv.reader` yields rows; the ordinary path has per-slot
   accessors for a `MojoList *` but nothing that produces one from an
   unknown iterator.
3. A decision about `fix_row(row)` (`_normalize_fix_read`'s result) in the
   same body — likely fine once 1 and 2 exist, but not yet checked.

Suggested first slice, independent of the above: make the refusal NAME the
callable-local case (`for ... in <call through a callable local>`) so the
three files' shared blocker is legible in `Unsupported shape(s)` rather than
looking like one undifferentiated CallExpr gap.

