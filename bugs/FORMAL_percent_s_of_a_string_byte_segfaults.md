# FORMAL_percent_s_of_a_string_byte_segfaults: `%s` of `s[i]` walks bytes at 97

**Area:** FORMAL (the `%s` family; both backends; found 2026-10-03 on
`work/formal8-11` while closing
`bugs/FORMAL_struct_receiver_as_a_printf_string.md`). **NOT FIXED** — it is the
one shape left in that family, it is a SIGSEGV, and the fix is a kind-table
question this session did not want to answer without a sweep to measure it.

## What was run, and what was seen

```
$ cat .tmp/w11/last.mojo
def main(n: Int) -> Int:
    var s = "abc"
    printf("[%s]", s[0])
    return 0

$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
      --backend=$a -o .tmp/last.$a .tmp/last.mojo && .tmp/last.$a; done
Built: .tmp/last.arm64  [arm64/macho]
Segmentation fault: 11   exit 139
Built: .tmp/last.x86_64  [x86_64/macho]
Segmentation fault: 11   exit 139
```

**Identical on both architectures, from a green build.** `%s` walked bytes at
address 97 looking for a NUL.

## Why every check misses it, which is the finding

The three shapes that used to get through are closed as of 2026-10-03
(`model.printf_arg_text_evidence`, `one_word_value_text_evidence`,
`identity_conversion_operand` — see the commits on `work/formal8-11` and the
deleted `FORMAL_struct_receiver_as_a_printf_string.md`). The decision is:

| argument | answer | why |
|---|---|---|
| a string literal | text | no question |
| a name `_expr_str_kind` calls `STR_KIND` | text | the classification exists |
| a NAME bound to an integer on its own shape | not text | `ValueKinds.own_shape_kind` |
| a name in the one-field table | the field's declared kind | `one_word_value_text_evidence` |
| a CALL | unknown — never evidence | `kind_of` answers `INT_KIND` for a callee it does not know |
| anything ELSE whose `kind_of` is `INT_KIND` | not text | a literal, a binop — the default cannot reach a non-name |
| anything else | unknown | the permissive direction |

`s[0]` is a `SubscriptExpr`, so it lands in the second-to-last row — and
`ValueKinds.kind_of` answers it with `list_elem_kind(STR_KIND)`, which is
**None** — `list_elem_kind` answers for a LIST kind (`formal/model.py:10585`,
`is_list_kind` is the test) and a `char *` is not a list blob. So the row above it never fires and the last row
(forgiving) does.

**The missing fact is one the model already states elsewhere**:
`bugs/FORMAL_string_value_model.md` records, measured, that "`s[i]` gives the
BYTE, not a one-character String — `s[0]` is 97 on both backends, which is a true
fact about the representation rather than a fabricated value". So the value kind
of a subscript of a `char *` is an integer, and the kind table does not say so.

## The next step

Make the model say it, and let the refusal that already exists fire:

1. **`model.list_elem_kind` for a `STR_KIND` base returns an integer kind**
   (the byte), instead of `None`. Every consumer then sees the truth: `printf
   ("%d", s[i])` is unchanged (it renders the byte either way), `s[i] == 46` is
   unchanged, `len(s[i])` gets the honest "an integer has no length" instead of
   "the source does not say", and `printf("%s", s[i])` is refused by the row
   that is already there.
2. **A test in `test_formal_run.py`** beside the `%s` group, pinning the refusal,
   plus a GUARD that `%d` of `s[0]` still prints `97` — the byte is a fact about
   the representation and must not become a refusal by the back door.

**What was NOT measured, and is the reason this is not done here:** whether any
stdlib module subscripts a string and relies on the element being unclassified.
`s[i]` is ordinary C, so a corpus sweep (`tools/formal_sweep.py`, which this
session was not permitted to run) is what should decide whether row 1 is a
two-line change or a diagnostic surface. `bugs/FORMAL_string_value_model.md`'s
`s[i]` bullet says the same thing about a different fix — "it belongs in
`LENGTH_DEPENDENT_METHODS` rather than in a refusal" — and this is the other
half of it: the byte is real, and both readers of it should know.
