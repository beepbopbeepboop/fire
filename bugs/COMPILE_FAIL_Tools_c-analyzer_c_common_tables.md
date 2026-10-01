# COMPILE_FAIL: Tools/c-analyzer/c_common/tables.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/c_common/tables.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

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
`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md` — i.e. three of
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

