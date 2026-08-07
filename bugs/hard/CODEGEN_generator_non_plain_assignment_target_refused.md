# HARD BUG: any assignment inside a generator body whose target isn't a bare identifier is refused outright

## Status

Unfixed. Root-caused 2026-08-06 while classifying the `CODEGEN_generator_
function_Lib_*.md` cluster (tasks #95-135) — found in `Lib/test/crashers/
gc_inspection.py`'s own generator `g` (one of this cluster's 41 target
files), and independently confirmed twice more in `Lib/test/support`'s
`iter_builtin_types`/`patch_list` (reached transitively while diagnosing
`Lib/test/_test_eintr.py`). Not attempted — see "What a fix needs" below.

## Symptom

```
[gimple_codegen] generator 'g' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
[gimple_codegen] generator 'iter_builtin_types' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
[gimple_codegen] generator 'patch_list' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
```
Same fatal-whole-module-`RuntimeError`-escalation pattern documented in
the sibling hard-bug docs for this cluster (`CODEGEN_generator_struct_
typed_param_refused.md`, `CODEGEN_generator_raise_non_static_exception_
class.md`) when the refused generator is module-level.

## Root cause (confirmed via `gc_inspection.py`'s source)

```python
def g():
    marker = object()
    yield marker
    [tup] = [x for x in gc.get_referrers(marker) if type(x) is tuple]
    print(tup)
    print(tup[1])
```
`[tup] = [x for x in ...]` is a LIST-PATTERN destructuring assignment
(unpacking a single-element list into `tup`) — a real, if slightly
unusual, Python idiom equivalent to `tup, = [...]`/`(tup,) = [...]`. The
coroutine codegen's assignment-statement lowering inside a generator
body (`_cpp_stmt`'s `AssignStmt` case) only handles a bare `IdentExpr`
target — any other target shape (list-pattern unpack, tuple unpack,
subscript assignment, attribute assignment) is refused wholesale with
this one generic message, rather than each shape getting its own
specific diagnosis. (The plain, non-generator/non-coroutine codegen path
DOES support several of these target shapes — this is specifically a
narrower/less mature area of the coroutine `.cpp` emission path, same
overall theme as this cluster's other gaps.)

## Confirmed occurrences

- `Lib/test/crashers/gc_inspection.py`: `g` — `[tup] = [...]` (list-
  pattern unpack). One of this cluster's own 41 target files; see
  `bugs/CODEGEN_generator_function_Lib_test_crashers_gc_inspection.md`.
- `Lib/test/support` (exact submodule not pinned down, reached
  transitively while diagnosing `Lib/test/_test_eintr.py`, not itself
  one of this cluster's 41 targets): `iter_builtin_types` and
  `patch_list` — target shape not independently read from source in
  this pass, only the refusal message observed.
- `Lib/test/test_support.py`: `save_restore_warnings_filters` — target
  shape not independently read from source in this pass. One of this
  cluster's 41 target files; see `bugs/CODEGEN_generator_function_Lib_
  test_test_support.md`.
- `Lib/test/test_faulthandler.py`: `FaultHandlerTests.check_stderr_none`
  — `sys.stderr = None` (a MODULE-ATTRIBUTE assignment target, not a
  tuple/list unpack — confirms the refusal is general to ANY non-
  `IdentExpr` target, not just unpack patterns). One of this cluster's
  41 target files; see `bugs/CODEGEN_generator_function_Lib_test_test_
  faulthandler.md`.

## What a fix needs

`_cpp_stmt`'s `AssignStmt` handling for a generator body would need
dedicated lowering for at least: tuple/list-pattern unpack (`a, b = ...`
/ `[a] = ...`) — likely straightforward by decomposing into N
single-target assignments against a temporary, mirroring how the plain
codegen path already does it — and, separately, subscript/attribute
assignment targets (`self.x = ...`, `d[k] = ...`), which are a
meaningfully bigger step (the existing `_gen_cpp_generator_unit`
docstring already flags "mutating a self field" as explicitly out of
this step's current scope for the SEPARATE reason of self-field write
support, not this assignment-target-shape issue — worth keeping the two
distinct if picked up, since fixing target-shape support doesn't imply
self-field-write support is also ready). Not attempted here.

## Minimal repro

```python
def g():
    yield 1
    [x] = [42]
    print(x)

def main():
    for v in g():
        print(v)

main()
```
Expected (per root cause above): `g` refused at the generator-
eligibility pre-filter with "only a plain identifier assignment target
is supported", before any C++ is emitted.
