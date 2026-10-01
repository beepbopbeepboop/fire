# A struct method that returns one of its own `str` fields SEGFAULTs

Found 2026-09-29 while fixing the same-bare-name struct collision
(`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`,
removed with that fix).
**NOT a struct-identity problem** — this reproduces with a SINGLE module
and no name collision anywhere, and identically on `master` (verified by
`git checkout master -- gimple_codegen.py mojo/`, re-running, and getting
the same SIGSEGV). Filed because it is a silent-wrong-behaviour-class bug
found adjacent to a fix, and nothing in `bugs/` records it.

## Repro

```python
# ma.py
class Dialog:
    def __init__(self, widgetName: str):
        self.widgetName = widgetName
    def show(self):
        return self.widgetName

# main.py
import ma
def main():
    a = ma.Dialog(5)
    print(a.widgetName)
    print(a.show())
main()
```

CPython: `5` / `5`, exit 0.

Compiled (`do_imports=True`, builds clean, links, runs):

```
--- stdout ---
--- exit: -11 ---
```

A SIGSEGV, exit -11, with **no output at all** — not even the
`print(a.widgetName)` on the line before the failing one, so the crash is
at (or before) the first call rather than isolated to `show()`.

## What was measured

- Same source on `master`: identical SIGSEGV. So this predates the
  struct-identity work and is untouched by it.
- Dropping `print(a.show())` and keeping only `print(a.widgetName)` makes
  the compiled program exit **1** with
  `Unhandled exception: AttributeError: widgetName` — i.e. the *field
  read at the call site* is separately wrong, even before any method is
  involved. So there are at least two symptoms here, and the plain field
  read is the smaller one.
- The identical shape with an `int` field (`self.n = n`, read back as
  `a.n`) does not crash — it prints the wrong thing instead (see the
  unannotated-param note below), so this is specific to the pointer-typed
  (`char *`) field.

## Why it is probably NOT the same bug as the unannotated-param one

`bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_int64.md`
(removed as fixed, but the shape still reproduces) is about an
unannotated `__init__` param defaulting its field to `int64_t` so a
`str` lands in an int slot. This repro **annotates** the param
(`widgetName: str`) and still segfaults, so the field ctype is not the
issue. The failure is in the value's *return path* out of the method.

## Next step

The crash is early enough that the first `print` produces nothing, so
start by bisecting what the generated C actually is for
`ma_Dialog___init__` / `ma_Dialog_show` / `_gimple_main` — specifically
whether `show`'s `return self.widgetName` is lowering to a `char *` load
at all, or to a dynamic-dispatch stub whose callee is NULL. A cheap
first probe: compile this exact pair with `--dump-full` and read
`ma_Dialog_show`'s body; the fix is almost certainly a missing field
ctype on the `self.<field>` return path, which is the same code region
`_lower_MemberExpr`'s struct-field branch drives.

Note the stale-`__pycache__` hazard when reproducing: a module named
`mod_a.py` that is edited in place can be picked up from a stale `.pyc`,
which produces confusing extra symptoms (`AttributeError: n` on a field
that plainly exists). Use a fresh module name per experiment, as the
`ma.py` repro above does.
