# CODEGEN: two stale emission sites make ordinary programs fail to COMPILE — a deleted runtime symbol and a delegate that was never added

Found 2026-10-02 while triaging `test_gimple_runner.py` after unrelated work
(`work/bugs4-5`). Both are **pre-existing**: each fixture below compiles clean
on `bc17a62b` and fails identically on `bac12a36`, so neither is a regression.
Six red rows of the `gimplerunner` bucket come from these two, which is why they
are worth one doc rather than two: they are the same shape — the thing the
emission side names no longer exists, and nothing noticed because the failure is
a compile error rather than a wrong answer.

## 1. `mojo_mark_dict_bool_values` was deleted from the runtime; two sites still emit it

```
$ python3 -c "import sys; sys.path.insert(0,'.');
             import gimple_codegen as G;
             open('/tmp/db.c','w').write(G.compile_to_gimple(open(FIXTURE).read(), do_imports=False))"
$ gcc-mp-15 -fgimple -Iruntime -fsyntax-only /tmp/db.c
/tmp/db.c: In function '_toplevel':
/tmp/db.c:2:3: error: implicit declaration of function 'mojo_mark_dict_bool_values' [-Wimplicit-function-declaration]
```

Fixture (this is `test_gimple_runner.py`'s `gimple_dict_of_bool_values`):

```python
b = True
print({'k': b})
d = {}
d['a'] = b
print(d)
```

The per-slot replacement is `mojo_dict_set_bool` (`runtime/fire_runtime.c`,
`_DictSlot.kind == 3`), and BOTH surviving comments say so in as many words —
`fire_runtime.c`: "This replaces a whole-DICT registry
(`mojo_mark_dict_bool_values`, since deleted)", and
`mojo/middle/emit_infra.py::emit_dict_int_value_store`'s own docstring: "This
replaced a whole-dict registry (`mojo_mark_dict_bool_values`, since deleted)".
Two call sites were left behind:

- `mojo/backend_gimple/emit_exprs.py:5279` — a dict LITERAL with a bool value:
  `gen._emit(f"  mojo_mark_dict_bool_values ({t});")`
- `mojo/backend_gimple/emit_stmts.py:1534` — a dict STORE with a bool value,
  same shape.

**Exact fix:** delete both emissions. The literal path's own comment says the
`is_python_bool_expr` gate above it is the right test and that the STORE path
(which routes through `mojo_dict_set_bool`) is the mechanism — so the literal
path most likely needs to store through `mojo_dict_set_bool` rather than
`mojo_dict_set_int` (check `emit_dict_int_value_store` in `emit_infra.py`, which
already does exactly that, and reuse it).

## 2. `gen._emit_dict_int_value_store` has no delegate, so a bytes-keyed store raises

Four rows fail with the same exception rather than a compile error:

```
FAIL  gimple_bytes_membership_in_containers: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_membership_across_domains:  (same)
FAIL  gimple_bytes_dict_key_domain:             (same)
FAIL  gimple_bytes_dict_get_pop_bytes_key:      (same)
```

`mojo/backend_gimple/emit_infra.py:4544` defines the module-level
`emit_dict_int_value_store(gen, dict_val, key_ctype, key_val, vtype, v, node)`;
`mojo/backend_gimple/emit_stmts.py:1513` calls `gen._emit_dict_int_value_store(...)`
and **no such method exists on `GimpleGen`** (grep: one hit, the call site).
Every other backend helper has a one-line delegate in `gimple_codegen.py`; this
one was missed, so `d[<bytes key>] = <non-str value>` raises `AttributeError`
during compilation — which the module-level fallback turns into "interpret this
module from source", i.e. a silent loss of the compiled path rather than a
reported failure.

**Exact fix:** add the delegate beside its neighbours:

```python
    def _emit_dict_int_value_store(self, *a):
        return ginf.emit_dict_int_value_store(self, *a)
```

(`ginf` is the alias `gimple_codegen.py` already uses for `emit_infra`.) One
line; the parameter list can be spelled out for clarity, matching the file's
style.

## What was run

Both measurements are `compile_to_gimple(..., do_imports=False)` followed by
`gcc-mp-15 -fgimple -Iruntime -fsyntax-only`, once on `work/bugs4-5` and once on
`bc17a62b`, plus `python3 test_gimple_runner.py` (which is where both were
found). See the commit message on this branch for the full red list; the other
two rows in it are `gimple_tuple_dict_key_is_content_keyed` (pre-existing,
`bugs/CODEGEN_dict_content_key_aliases_a_string_key.md`) and
`gimple_char_scan_allocates_nothing_per_character` (a peak-RSS tripwire, 246.7 MB
against a 60 MB limit — `“PERF: the per-character `str` scan allocated one `malloc(2)` per character”`).