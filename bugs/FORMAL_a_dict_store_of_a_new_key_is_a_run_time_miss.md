# FORMAL_a_dict_store_of_a_new_key_is_a_run_time_miss

**Area:** FORMAL, both backends — `formal/x86_64_codegen.py::_emit_dict_lookup_addr`
and `formal/arm64_codegen.py`'s twin, which is where a dict subscript STORE
lands: `_emit_subscript_addr` answers a dict base with the key SCAN, and the
scan's miss arm is `_emit_call_exit(1)`.
**Status: NOT FIXED. Measured on both architectures, minimised to two
statements, and a LIMIT rather than a defect in the sense the corpus needs: the
miss signal is documented, there is simply no diagnostic where the source wrote
an insert. §3 says why fixing it is not a patch.**

Found 2026-10-03 on `work/formal17-fuzz-continue-a` while extending
`tools/formal_fuzz.py` with the `containers` mix. It is the reason that mix's
`dict_store` statement names a key the literal wrote, and it is recorded here so
that the corpus's discipline is a documented decision rather than a workaround
nobody can check.

## 1. What is wrong

`d[k] = v` where `k` is NOT already in `d` is CPython's insert. On this path it
is a key scan that misses, and the miss signal is `exit(1)` — so the program
dies having printed nothing, and the diagnostic names neither the key nor the
table.

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/p54.mojo
```

`p54.mojo`:

```mojo
def main() -> Int32:
    d = {"a": 1, "b": 2}
    d["c"] = 3
    print(len(d))
    return 0
```

| source | CPython 3.14 | arm64 | x86-64 |
|---|---|---|---|
| everything above | `3`, exit 0 | exit 1, no output | exit 1, no output |

Four shapes, all the same, all measured on both architectures:

| program | CPython | both images |
|---|---|---|
| `d = {}` ; `d[10] = 1` ; `print(len(d))` | `1` | exit 1 |
| `d = {"a": 0}` ; `d["b"] = 2` ; `print(len(d))` | `2` | exit 1 |
| `d = {"a": 1, "b": 2}` ; `d["c"] = 3` ; `v = d["c"]` ; `print(v)` | `3` | exit 1 |
| `d = {"a": 1, "b": 2}` ; `d["c"] = 3` ; `print(len(d))` | `3` | exit 1 |

A store of a key the table DOES hold works and agrees: `d = {"a": 1, "b": 2}`;
`d["a"] = 7`; `v = d["a"]`; `print(v)`; `print(len(d))` prints `7` and `2` on
all three engines.

The order matters and is not a coincidence: `print(len(d))` BEFORE the store
makes the program work — measured on both architectures for
`d = {"a": 1, "b": 2}; print(len(d)); d["c"] = 3; print(d["c"]); print(len(d))`,
which prints `2`, `3`, `3` on all three engines. The read materialises the
literal into a reserved blob; the store into a blob that was never read has
nowhere to put the new pair. So the same source with a dead statement in front
of it is a working program, which is the worst shape for a limit to have.

## 2. Why the miss signal is `exit(1)` and is right for a READ

`exit(1)` is the documented signal for "this dict has no such key", and a READ
that misses cannot do better: CPython raises `KeyError`, this path has no
exception runtime, and `print()` of a missing container value would print the
address the scan left behind. `bugs/FORMAL_a_dict_subscript_has_no_value_kind.md`
and `test_formal_value_model.py`'s `REFUSALS` row
`a_dict_subscript_of_a_key_the_literal_lacks_is_refused` are the other half of
that decision, and both are right.

A STORE is the different case, and the reason is stated by
`formal/model.py`'s `_dict_inits` docstring in its own words: a dict literal
says "which element WORDS were written", and nothing says how many pairs the
blob has room for. `_emit_dict` reserves `[count][k0][v0]…` for the pairs the
literal wrote; there is no capacity field and no growth path, so an insert has
nowhere to write even if the miss were detected rather than exited on. The
`list.append` half of the same story HAS a capacity and says so out loud —
"list.append overflowed 'xs': its capacity is 2, the number of append SITES in
the function that built it, and every EXECUTION of a site counts against it" —
which is why an overflowing append is a documented limit and this is not yet
even that.

## 3. Why it is not a patch

Three things have to exist before `d[k] = v` can insert, and none of them is
local:

1. **A capacity in the blob layout.** `[count][k0][v0]…` is read by every
   subscript, every walk, every `len` and both emitters' pair arithmetic. Adding
   a capacity word changes `_emit_dict`'s header, `BLOB_HEADER_BYTES`'s users,
   `element_offset`/`pair_key_offset`/`walk_stride` and the `__init__`-shaped
   blobs every host module builds. That is a change to the layout constant, not
   to a function.
2. **A miss arm that knows it is a STORE.** `_emit_subscript_addr` is shared by
   the read, the store and the augmented assignment; only the store wants to
   append. The three-way answer ("hit → the address", "miss + read → exit 1",
   "miss + store → write a pair and bump the count") has to come out of the
   shared emitter or the two backends will answer it differently, which is the
   one thing this pair is not allowed to do.
3. **A `lib/ProofLib.lean` step for the append**, if the proofs are to keep
   checking the store — the same coupling `bugs/
   FORMAL_floor_division_on_a_signed_operand_is_truncated.md` §2 describes for
   the division fix, and for the same reason: the emitted code and the model
   move together or neither moves.

In the meantime the honest middle is a DIAGNOSTIC rather than an insert: a
miss on a store could `exit(1)` with a line saying "this key is not in the
table; growing a pair blob is not lowered on this path". That is small, it is
in the same place as the signal, and it turns a silent death into a sentence —
which is what `list.append`'s overflow already is.

## 4. The exact next step

1. Emit the diagnostic. It is one `CodegenError`-shaped message at the miss arm
   of each backend's dict-lookup, told apart from the read's miss by whether
   the caller is `_emit_subscript_addr` on a store. `model.py` owns the wording,
   as `string_concat_refusal` owns its own, so the two cannot drift.
2. Then decide (1)-(3) above as a project, not a patch. If the answer is "a dict
   on this path has the capacity its literal wrote", write THAT in
   `bugs/FORMAL_known_limits.md` and delete this doc, because a stated limit is
   the outcome this repository wants and a doc for a limit nobody reads is not.
3. Either way, the fuzzer's `containers` mix keeps naming a key the literal
   wrote, because a corpus that generates the limit reports it as a
   `MISMATCH-*` finding on every program that contains it — hundreds of times,
   for a thing that is not a miscompile. If step 1 lands and the diagnostic
   becomes a REFUSAL at build time rather than a run-time exit, the mix can
   generate a new key again; until then it cannot.
