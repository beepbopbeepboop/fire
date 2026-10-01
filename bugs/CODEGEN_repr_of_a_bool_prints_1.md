# `repr()` of a `bool` prints `1`/`0` — the value is right, its type is not

**State: OPEN.** Not fixed. Found 2026-09-29 while building the
differential harness for the bytes work; it is a general `repr()` bug, not a
bytes one, and it was deliberately left out of that work.

## What I ran and what I saw

    def main():
        x = 1 == 1
        print(repr(x))
        print(repr(x == 2))
        print('%r' % (x,))

| | CPython | compiled |
|---|---|---|
| `repr(True)` | `True` | `1` |
| `repr(False)` | `False` | `0` |
| `'%r' % (True,)` | `True` | `1` |

Same harness as the bytes work: `gimple_codegen.compile_to_gimple`, then
`gcc -fgimple` against `runtime/fire_runtime.c`, run beside CPython.

**`print()` is already correct** — `print(True)` prints `True`, because
`emit_infra.py`'s print path has an explicit `_Bool` branch calling
`mojo_repr_bool`. It is specifically `repr()` and `%r` that are wrong, which
is why this survived: the obvious smoke test passes.

## Mechanism

`mojo/backend_gimple/emit_resolve.py`, `_repr_value`:

    if rat == 'char *':            ...
    if rat == 'MojoList *':        ...
    if rat == 'MojoDict *':        ...
    if rat == 'MojoBytes *':       ...
    if rat == 'MojoMemoryView *':  ...
    if rat.endswith(' *') or rat == 'void *': ...
    if rat in ('double', 'float'): ...
    rav64 = rav if rat == 'int64_t' else gen._new_val('int64_t', f'(int64_t){rav}')
    return gen._call_expr('char *', 'mojo_repr_int', [('int64_t', rav64)])

There is no `rat == '_Bool'` case, so a `_Bool` falls to the last line and
is formatted as an integer. `mojo_repr_bool` already exists in the runtime
and the print path already uses it, so the fix is one branch in one
function — the reason it was not simply made is that `emit_resolve.py` is a
shared compiler file and this was a bytes task; the change is small but it
belongs to whoever owns `repr`/formatting.

## Why it is worth a doc and not just a note

A bool and an int are the same value here, so this is "only" a repr
difference — but the two print paths disagreeing is exactly the class this
directory keeps re-finding: `print(x)` right, `repr(x)` wrong, so the test
that gets written (a `print`) passes and the code that ships
(`f'{x!r}'`, `%r`, a dict repr, a logged value) does not. The bytes work hit
this directly: its own differential harness reported ~30 spurious diffs
because `repr(True)` is `1`, and normalising for it in the harness is
precisely the kind of accommodation that hides the next one.

Also worth measuring before fixing: `%d`/`%i` on a `_Bool` presumably takes
the same path, and `str(_Bool)` inside an f-string. A fix should check
those three, not just `repr()`.

## Exact next step

1. Add a `rat == '_Bool'` branch to `_repr_value` calling `mojo_repr_bool`
   (`(int)` cast, as the print path does) — it must come BEFORE the
   `rat.endswith(' *')` test, which is the same ordering trap
   `_isinstance_one_type`'s NULL branch had.
2. Measure `%d`, `%i`, `%s` and `f'{x}'` on a `_Bool` against CPython and
   record the answers in the test, so the next reader does not assume.
3. Add `repr(True)` / `repr(False)` / `repr(1 == 1)` / `'%r' % (True,)` to
   `test_gimple_runner.py` with CPython's exact text.

No suite-bucket question arises: `test_gimple_runner.py` is registered as
`gimplerunner`, in both `check` and `gate` (confirmed with
`python3 tools/suite.py --list` on 2026-09-29).
