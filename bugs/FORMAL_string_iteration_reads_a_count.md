# FORMAL: iterating a string reads its first eight bytes as an element COUNT

## Status: FIXED (refused, with the measurements) — 2026-09-30

The loop family — `for x in s`, `[x for x in s]` — walks its iterable as a
BLOB, and a blob's first word is its element count. A `char *` has no header
word, so the count is the first eight bytes of TEXT: the bounds check passes on
them and the element walk reads `base + 8 + 8k`, which is the middle of the
string and then whatever the text section puts after it.

Both backends now REFUSE it at build time, from
`formal/model.py:string_iteration_refusal` (the sibling of
`frame_container_operand_refusal`, which is the same mistake for a frame
address), raised from each backend's for-in and from `_emit_compr_gen`.

What it was, on the real binaries:

| case | CPython | x86-64 | arm64 |
|---|---|---|---|
| `t = 0; for c in "abc": t = t + 1` | `3` | **97** (`'a'` as the count) | **SIGBUS (-10)** |
| `s = "abcd"; for c in s: ...` | `4` | **SIGBUS (-10)** | **SIGBUS (-10)** |
| `[c for c in "abc"]`, `len` | `3` | **exit 1** (the comprehension's capacity guard) | **exit 1** |

Unaffected, on both backends, before and after: `len(s)` = 4, `s[1]` = 98 (a
byte load), and `[c for c in ["a","b","c"]]` = 3 (a comprehension over a LIST
of strings).

Note that this was **not** only a comprehension bug: the plain `for` loop had it
too, and the two architectures disagreed about the same source (97 vs a signal).
It is not in `CODEGEN_nested_comprehension.md` because that document's
`nested-str-elt` row was one instance of this and the doc is now deleted.

**Not fixed: iterating a string actually WORKING.** A string has no length in
this representation, so a correct lowering needs one — either a length-prefixed
interned string (which changes every string consumer, including `s[i]` and the
`String`-struct collision in `FORMAL_string_value_model.md`) or a
materialise-the-characters-into-a-blob lowering at the loop site. Until one of
those lands, refusing is the honest answer; the refusal says so.

Verified: `test_x86_64_containers.py` 59/60 (x86-64) and 52/60 (arm64) —
unchanged from before the change; `test_formal_run.py` 388/0;
`test_x86_64_examples.py` 45/45; `test_struct_formal.py` 146/148 (the two
failures are pre-existing `pack()` arity refusals, identical with and without
this change).