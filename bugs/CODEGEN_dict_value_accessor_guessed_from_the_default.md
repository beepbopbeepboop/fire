# A dict's value accessor is guessed from the DEFAULT argument, so `d.get(k, default)` reads the wrong slot and `pop` drops its default

Found 2026-10-01 while fixing
`bugs/CODEGEN_tuple_dict_key_hashed_by_address.md` (deleted with that fix) —
`d.get(k, <other type>)` on an int-valued dict SIGSEGVs and turned up while
writing that fix's regression test. **Not a key bug and not a leak**: the key
path is fine; the VALUE side of the dict is where this is.

## What I ran

`gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c` (`fire.py build` compiles the whole stdlib and is not
the way to measure a four-line program), against CPython on the same text.

## What I saw

| program | CPython | compiled |
|---|---|---|
| `d = {"a": 1}; print(d.get("a", "y"))` | `1` | **SIGSEGV** |
| `d = {"a": 1}; print(d.get("z", "y"))` | `y` | `y` |
| `d = {"a": "s"}; d["b"] = 1; print(d["b"])` | `1` | **SIGSEGV** |
| `d = {"a": 1}; d["b"] = "s"; print(d["b"])` | `s` | `s` |
| `s = {"a": "hello"}; print(s.pop("a"))` | `hello` | `4297550240` |
| `s = {"a": 5}; print(s.pop("a"))` | `5` | `5` |
| `d = {"a": "s"}; print(d.pop("z", 7))` | `7` | `0` |
| `d = {"a": 1}; print(d.pop("z", "y"))` | `y` | `0` |

Two distinct defects, one shared cause (below): `get` with a default of a
different type than the dict's values **crashes**; `pop` **silently returns the
wrong value and ignores its default entirely**.

## Mechanism — `get`

`mojo/backend_gimple/emit_methods.py:3829`:

```python
        val_type = gen._dict_val_of(ov)
        if val_type == 'int64_t' and default_ty == 'char *':
            val_type = 'char *'
```

`_dict_val_of` returns `'int64_t'` both for a dict **known** to hold ints (the
literal `{"a": 1}` records `int64_t` in `gen._dict_val_types`) and for a dict
whose value type is **unknown**. The arm cannot tell those two apart, so it
infers the value type from the DEFAULT argument — and for the reproducer emits:

```c
  _t7 = mojo_dict_get_str (d, _t5);   /* d holds the int 1 */
```

`mojo_dict_get_str` returns the slot's word as a `char *`, so `print` calls
`strlen(1)` and the program dies at the `print`. The MISS rows pass because the
absent-key path never reads the slot at all: only a HIT touches the value. The
comment above the arm is explicit that this was for a dict whose value type is
not statically known, which is true and is not this case.

`d = {"a": "s"}; d["b"] = 1; print(d["b"])` is the same mistake one store later:
`_dict_val_types` is set by the first store (`emit_stmts.py:1414`) and the
later store of another kind does not update it, so the read uses the first
store's accessor. This one is a "homogeneous dict" assumption rather than the
`get` inference, and it is deliberate and documented at that site ("Homogeneous
assumption, matching list element-type tracking") — but the consequence is a
segfault rather than a wrong value, which is worth more than the comment says.

## Mechanism — `pop`

`mojo/backend_gimple/emit_methods.py:3961`, whose own comment two branches
earlier says the str/double siblings "exist because the slot is one int64_t of
bits: without them a bytes-keyed dict holding strings popped its value as a raw
pointer decimal" — then does exactly that for a NON-bytes key:

```python
        return 'int64_t', gen._call_expr('int64_t', 'mojo_dict_pop_int',
                                         [('MojoDict *', ov), (key_type, key_val)])
```

No `val_type` arm, so a `char *` or `double` value is returned as its raw word
(`4297550240` for `"hello"`), and `args[1]` — the default — is never lowered at
all, which is where `pop("z", 7) == 0` comes from. The bytes branch above it
calls `mojo_dict_pop_bytes_int(d, k, dflt)` for exactly this reason; there is no
`mojo_dict_pop_str`/`_double`, and `mojo_dict_pop_int` has no `dflt` parameter
at all, so the default cannot be expressed until the runtime grows them.

## The next step, in order

1. **Make "unknown" distinguishable from "int64_t".** `gen._dict_val_types`
   already only records an entry when it saw a store, so the absent case is
   available: `_dict_val_of` (or a sibling that answers `(known, type)`) plus a
   sentinel distinct from `'int64_t'` for "no evidence". That one change is what
   makes the `get` arm correct — with a known `int64_t` the default's type stops
   overriding it, and the int accessor is emitted. Check every other reader of
   `_dict_val_of` for the same "int64_t means unknown" assumption; this is the
   one that bites.
2. **`pop`: add the value-type arms and the runtime `dflt`.** `pop` needs
   `mojo_dict_pop_str`/`_double` and a `dflt` parameter on all three, or one
   `mojo_dict_pop(MojoDict *, char *, int64_t dflt, int kind)` that returns the
   word and lets the caller coerce. The bytes family already shows the shape and
   the reason. `runtime/fire_runtime.h` gains three declarations, so
   `test_runtime_header_scan.py`'s expected set needs them.
3. **The heterogeneous-dict segfault (row 3)** is the "homogeneous assumption"
   above. A full fix means a per-slot `kind` the READ side consults — which
   `_DictSlot` already has (`keykind` is the key's; the value's is `kind`) — so
   the runtime half exists and the codegen half does not. Until then, a store
   whose value type differs from the recorded one should at least not produce a
   program that dies in `strlen`.

None of this is a regression test away today: the dict suite in
`test_gimple_runner.py` covers homogeneous dicts only. `d.get(k, default)` with
a default of the other type and `pop` from a `char *`/double dict are the two
cases to add when these are fixed.
