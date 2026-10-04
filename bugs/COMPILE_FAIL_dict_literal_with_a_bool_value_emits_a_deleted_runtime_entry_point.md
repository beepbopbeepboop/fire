# COMPILE_FAIL: five emitter sites still call `mojo_mark_dict_bool_values`, which the runtime deleted

**Found 2026-10-02 by `bugs4-9` while adding a container-repr test, and NOT
caused by anything in flight.** Measured on this tree's HEAD (`bc17a62b`) with a
pristine `git archive HEAD` extraction in `.tmp/w9/pre`, so it is not a change
under test. **The write set belongs to
`bug:CODEGEN_bool_annotated_struct_field_prints_as_int` (claimed by
`bugs4-1`)**, which is where the fix goes; this doc is the evidence, not a
second claim on it.

## What was run

```sh
$ cat probe.py
def main():
    d = {"a": 1, "d": True}
    print(d)
main()
$ python3 -c "import test_gimple_runner as T; T.test_gimple_stdout('probe', open('probe.py').read(), \"{'a': 1, 'd': True}\n\")"
FAIL  probe: gcc -fgimple compilation failed: ... In function '_gimple_main':
  error: implicit declaration of function 'mojo_mark_dict_bool_values'
       [-Wimplicit-function-declaration]
```

Not a wrong answer — the program does not compile at all. Any dict literal or
dict store with a `True`/`False` value reaches this.

## The half-landed fix, stated precisely

`bugs/CODEGEN_bool_annotated_struct_field_prints_as_int.md` §2 moved the bool
tag from a whole-DICT registry to `_DictSlot.kind == 3`, and its own Status
says of the old pair:

> The whole-dict registry and both of its entry points are deleted; nothing
> else read them.

The RUNTIME half is deleted and the CONSUMER is gone (`_mojo_repr_dict` now
reads `d->slots[_i].kind == 3`, and `mojo_dict_set_bool` /
`mojo_dict_set_bytes_bool` set it). The five PRODUCER call sites were not
updated, so they now emit a reference to a function with no definition and no
declaration:

| file:line | what it emits |
|---|---|
| `mojo/backend_gimple/emit_exprs.py:5279` | `mojo_mark_dict_bool_values ({t});` |
| `mojo/backend_gimple/emit_stmts.py:1534` | `mojo_mark_dict_bool_values ({obj_v});` |
| `mojo/backend_gimple/emit_stmts.py:1590` | `mojo_mark_dict_bool_values ({dp});` |
| `mojo/backend_gimple/emit_stmts.py:2901` | `mojo_mark_dict_bool_values ({obj_v});` |
| `mojo/backend_gimple/emit_stmts.py:2930` | `mojo_mark_dict_bool_values ({dp});` |

`mojo_is_bool_dict` has no remaining caller at all, so the registry is dead
code in both directions and the five sites should simply not exist. The fix is
to delete them, which is the same consolidation §2 already did for the
call-site helper (`emit_infra.py`'s `emit_dict_int_value_store`, now one
function instead of five copies of "mark the dict then `mojo_dict_set_int`").

Confirm the shape from the runtime side before deleting:

```sh
grep -rn mojo_mark_dict_bool_values mojo/ runtime/ test_*.py
```

Expected after the fix: no hits outside `bugs/` prose and the comments that
document the removal.

## Why this is filed rather than fixed

Rule 5: the write set (`mojo/backend_gimple/emit_exprs.py`,
`mojo/backend_gimple/emit_stmts.py`) is the `CODEGEN_bool_annotated_struct_
field_prints_as_int` claim's, and that doc is still open — §"What is STILL
wrong" lists the bool-ANNOTATION half as unfixed, so the bool work is in
flight and these five sites are the same work. Editing them from here would be
two workers in one claim.

## What it costs until it lands

Every dict with a bool value fails to COMPILE, which the gates can only miss if
no registered case has one. `test_gimple_runner.py` does have
`gimple_dict_of_bool_values` — so either that case is not registered in a
bucket, or it is registered and RED, and either way this is worth checking
against `python3 tools/suite.py --list` when the fix lands.

## Coverage to add with the fix

The existing `gimple_dict_of_bool_values` case is the right home, and it
should also cover the shapes the five sites belong to separately: a dict
LITERAL (`emit_exprs.py:5279`) and a dict STORE into an existing dict
(`emit_stmts.py`'s four). The bug only reaches a program through the compiled
path, so `test_gimple.py`'s shape checks cannot see it — a `grep`-for-the-
function check in `test_gimple.py` is worth adding alongside, since it is the
check that would have caught the half-landing.

## Note for whoever fixes it

`mojo_str_cat_free`'s new per-slot ownership in the emitted `_mojo_repr_dict`
(the `kind == 3` branch there is a `"True"`/`"False"` LITERAL and must NOT be
freed, which is noted in the comment above it) landed in the same area on
`work/bugs4-9` and is independent of this — the bool literal is the one
non-owned branch in that walker, and it is marked as such.