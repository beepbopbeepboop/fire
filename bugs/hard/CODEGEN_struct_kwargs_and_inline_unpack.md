# HARD BUG: `struct` keyword arguments are silently dropped, and the inline mixed int+float unpack still returns raw bits

**State: OPEN.** Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_struct_module.md`. That doc was correctly closed for the mechanisms
it recorded, but two of its "closed" statements do not hold for all the
spellings they appear to cover, and one of them is a silent miscompile — the
exact class `bugs/hard/` exists for.

## 1. `struct.*` keyword arguments are dropped, not refused

The removed doc claimed keyword arguments "fall through (guarded out);
positional only", twice. There is no guard. `node.kwargs` is never inspected
at all, so a keyword call runs with the default and returns a plausible wrong
answer:

    s = struct.Struct('<HH'); b = b'\x00\x00\x05\x00\x06\x00'
    s.unpack_from(b, 2)                  -> (5, 6)     correct (positional)
    s.unpack_from(b, offset=2)           -> (0, 5)     reads offset 0

    struct.unpack_from('<H', b'\xff\xff\x02\x00', 2)   -> (2,)   correct
    struct.unpack_from('<H', b'\xff\xff\x02\x00', offset=2) -> (0,) WRONG

    struct.calcsize('<HH')               -> 4
    struct.calcsize(fmt='<HH')           -> 0          CPython raises TypeError

The `unpack_from(offset=...)` case is the dangerous one: it returns
well-formed data read from the WRONG OFFSET, with no diagnostic. A caller
that uses `offset` to walk a record layout gets silently misparsed records.

Root cause: `_lower_struct_module_call` (`mojo/backend_gimple/emit_methods.py:679-682`)
does `args = list(node.args)` and never looks at `node.kwargs`. The
bytes/memoryview path right next to it (`emit_methods.py:331-333`) threads
`node.kwargs` through properly, so the omission is local to `struct`.

## 2. Mixed int+float `unpack` still returns raw IEEE bits — in the inline spelling

The removed doc's headline closure was "mixed int+float unpack formats", and
the raw-bits value it quoted as the pre-fix symptom is still reachable:

    print(struct.unpack('<if', struct.pack('<if', 1, 1.0)))
      CPython:    (1, 1.0)
      compiled:   (1, 4607182418800017408)      <- the float's IEEE-754 bits

The mechanism the doc describes is real and does work — but only when the
result is bound to a local:

    var m = struct.unpack('<if', struct.pack('<if', 1, 1.0))
    print(m[0], m[1])                  ->  1 1.0        correct

That difference is the whole bug. Per-slot kinds are propagated "to the local
name by the `VarDecl` path", so with no local name there is nothing to hang
them on and it falls back to int64 slots. The removed doc recorded the
fallback only for a *computed index*, not for the un-assigned spelling, and
presented the case as closed without the caveat.

`test_gimple_runner.py`'s `gimple_struct_mixed_int_float_formats` only ever
writes the `var m = ...` form, so it cannot see this.

Uniform formats are fine: `<2f`, `<3i`, `<4s`, and also `>dhh`, `<Bd`, `<fd`
all match CPython exactly.

## 3. Genuinely closed, and worth keeping in mind as done

Verified correct, for the record, so nobody re-opens them:

- `struct E: var F = struct.Struct('<HH')` then `E.F.unpack(b'\x01\x00\x02\x00')`
  -> `(1, 2)`, no segfault (the class-field-init path).
- Scalar class attrs `var NAME/N/ITEMS/TABLE` -> `hello 5 0.0 0`, matching CPython.
- Bare `FIELD_STRUCT = struct.Struct('<HH')` class attribute.
- `pack(fmt, a, *rest)` splat and the `pack(...) + X` tail form.

## A claim in the removed doc that did NOT reproduce

It claimed no interpreter `struct` module exists, so a comptime-evaluated
`struct.Struct(...)` default still `NameError`s. Both shapes work through
`fire.py run` in this checkout: a class with `var FMT = struct.Struct('<HH')`
prints `4`, and `def make(fmt: String = struct.calcsize('<HH'))` prints `4`.
Reported as **not reproduced**, not as fixed — I did not construct every
shape the claim might have meant.

## Where

`mojo/backend_gimple/emit_methods.py` (`_lower_struct_module_call`,
`_struct_elem_ctypes`). Note `_struct_elem_ctype`'s own docstring
(`emit_methods.py:594-598`) still cites the removed
`bugs/hard/CODEGEN_struct_module.md` for the mixed-format degradation — that
cross-reference has been repointed at this doc, and the docstring should also
stop implying the degradation is confined to the assigned-to-a-local case,
because item 2 shows it is not.
