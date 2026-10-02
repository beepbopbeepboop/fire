# CODEGEN: `d.pop(k, default)` returns 0 on a MISS, whatever the default and whatever the key type

**State: OPEN, measured on the tree as of 2026-10-01, not fixed.** Found while
fixing `bugs/CODEGEN_tuple_dict_key_hashed_by_address.md` (which is fixed and
covered by `test_dict_tuple_key.py`). That fix was about which KEY a lookup uses;
this is about what a lookup answers when it finds NOTHING, and it is
key-type-independent, so it is not that bug and was not caused by its fix.

## What was run, and what it showed

```python
def main() raises:
    var d = {}
    d["a"] = 1
    print(d.pop("a", -1))
    print(d.pop("a", -1))     # the miss
    print(d.pop("zz", -1))    # a key that was never there
    return 0
```

CPython 3.14.7: `1`, `-1`, `-1`. The compiled program: `1`, `0`, `0`.

A string key, a genuine hit, and two misses — so this is not about the
content-key machinery added for tuple keys, and a str key is not special here:

```python
_C: dict = {}
def take(a) -> Int:
    var k = (a, 1)
    return _C.pop(k, -1)
# compiled: 0 where CPython says -1
```

## Why it is silent

`mojo_dict_pop_int` has no default parameter at all, and the generated C never
passes one:

```c
  _t5 = mojo_dict_pop_int (d, _t4);
  _t11 = mojo_dict_pop_int (d, _t10);
  _t17 = mojo_dict_pop_int (d, _t16);
```

Three call sites, three arguments, and the `-1` the source wrote is simply not
there. `mojo_dict_pop_int` returns `0` for a missing key, so the default is
dropped and 0 — a real value in this model, the same "plausible answer" shape as
every other silent-wrong-verdict bug in this family: a program computing a
running total, a default sentinel of 0, or a "was it already popped" flag gets
a wrong number with exit 0 and no diagnostic.

`d.pop(k)` with no default is CORRECT today (it raises KeyError, because
`_dict_remove_slot` is only reached for a found slot) — so this is specifically
the two-argument form.

## Blast radius

Every `d.pop(k, default)` on the compiled path, of any key type, on a miss. The
common shapes are a "remove if present, else report absence" idiom and a
`defaultdict`-style default value; both get 0.

## Exact next step

Two halves, and the second is the one that decides whether the first is worth
doing:

1. `mojo_dict_pop_int` / `mojo_dict_pop_int_kw` / `mojo_dict_pop_str` /
   `mojo_dict_pop_str_kw` need the default as a parameter, and the CALLER has to
   pass what the source wrote. The caller side is where the information is lost:
   find where `.pop` is lowered (probably `emit_methods.py`, next to the `get`
   and `setdefault` handlers — `mojo_dict_setdefault_int_kw` already takes a
   `dflt` argument, so the lowering knows how to pass one and `.pop` is the
   case that forgot). Emit the default through, and have the runtime return it
   when no slot was found.

2. **Whether to raise instead.** `mojo_bytes_partition` raises `ValueError`
   through `mojo_raise_value_error` (see its comment in the runtime), so the
   mechanism exists; the question is only whether a `pop` that cannot raise
   should. A default of `-1` and a default of `None` must come back as `-1` and
   as `None` respectively, and those are different C types on the value side, so
   the return type of `mojo_dict_pop_*` may have to become typed per spelling
   (`_int` / `_str`) rather than one `int64_t`. That is a real decision, not a
   mechanical edit.

A test belongs beside `test_dict_tuple_key.py`'s key-entry-point cases (which
deliberately avoid the two-argument form for exactly this reason, and say so),
as a `d.pop(k, -1)` case whose expected value is the default and not 0.