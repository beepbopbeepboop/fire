# FORMAL_string_constructor_refuses_a_pointer_typed_value: `String(unsafe_from_utf8_ptr=p)` is refused because the value-kind reader calls a pointer `'int'`

**Area:** FORMAL (the string value model's constructor check). **Status: NOT
FIXED — filed 2026-10-13 by `work/formal348-docs`, found while re-measuring
`test_formal_external_call.py`.** On this tree the registered-but-ungated job
`formal-external-call` (the `proofs` bucket, not in `gate`) was red for a second
reason beside the stale baseline; this is that reason, named.

## What I ran, what I saw, what I expected

The smallest shape is an annotated pointer parameter:

```mojo
def f(p: Pointer[UInt8]) -> String:
    return String(unsafe_from_utf8_ptr=p)
```

```
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/strp.out .tmp/strp.mojo
build: String(p) is refused on this path: String is a string type constructor,
  and a string on this path IS a `char *` … and this build classifies p as 'int'
  …
```

The same on x86-64, and the same for a LOCAL rather than a parameter:

```mojo
def main() -> Int:
    var b: Pointer[UInt8] = malloc(4)
    var s = String(unsafe_from_utf8_ptr=b)
    return 0
```

→ `build: String(b) is refused … this build classifies b as 'int'`.

**Both programs are well-typed and the refusal is false about them.** On this
path a string IS a `char *`, so `String(unsafe_from_utf8_ptr=p)` is the identity
on a byte pointer — which is exactly what `formal/model.py`'s
`string_conversion_refusal` docstring SAYS the identity is correct for ("a
pointer already is what a string is", the `p.value()` paragraph). The refusal it
is firing is meant for a NUMBER (`str(n)` with `n = 10`), not for a pointer.

## Why: the reader's DEFAULT is being read as EVIDENCE

`string_conversion_refusal(callee_name, operand, operand_kind)` refuses when
`operand_kind` is neither `None` nor a string kind. The kind comes from the
backend's `_expr_str_kind`, which falls through to
`formal/model.py`'s `ValueKinds.kind_of`. That map seeds an ANNOTATED parameter
with `INT_KIND` for any annotation that is not in `string_names` / `float_names`
(`ValueKinds.__init__`'s parameter loop), and a body-bound local from its
right-hand side's shape. `Pointer[UInt8]` is in neither vocabulary, so it is
`'int'` — and `'int'` here is the "a word is an integer" DEFAULT, not a statement
that the source wrote an integer. The refusal's own docstring distinguishes
those two ("a kind that is not None and is not `STR_KIND`" vs
`own_shape_kind`, "the source SAYS this name holds an integer"), but the value it
receives is the default.

So the shape is: **a byte pointer nothing in the kind vocabulary knows about
falls to the integer default, and the constructor check reads that default as
positive evidence.** A pointer is not the only thing this can hit, but it is the
one that matters here because the constructor exists precisely to build a string
FROM one.

## What it costs, measured

- `test_formal_external_call.py`'s `env_round_trip` transcribed
  `std/os/env.mojo` with bare `ptr` (the source writes `ptr.value()`), which the
  refusal rejected; the transcription is corrected on this branch to the source's
  own `.value()`, so the suite is green — but the FALSE REFUSAL is independent of
  that test and remains: the two minimal programs above are refused on both
  architectures today.
- Not a sweep-sized number is claimed here. This is filed rather than fixed
  because the honest fix is a value-model change (below) that wants a sweep, and
  a light worker cannot take that sweep.

## The exact next step

Make the kind reader answer a STRING kind for a value whose DECLARED type is a
**byte** pointer, so the constructor check sees positive evidence the other way
— and only for a byte pointee, because `Pointer[Int64]` is not text:

1. `formal/model.py` already has the two readers a fix needs and a third that
   says whether the pointee is a byte: `receiver_declared_is_pointer`
   (`bool | None`) and `pointer_pointee`, plus `POINTEE_WIDTHS["UInt8"] == 1`.
   Either thread a `pointer_bytes_kind` hook into `ValueKinds` beside
   `declared_kind` / `deref_kind` (so an annotated parameter and a frame slot
   classify the same way), or have both backends' `_expr_str_kind` map a
   byte-pointer expression to `FOREIGN_BYTES_KIND` — the kind
   `string_operand_is_string` already admits and the one a `char *` from a host
   module gets.
2. **Do NOT add a pointer ctor name to `string_names`.** That vocabulary is a set
   of ANNOTATION SPELLINGS, and every spelling there (`String`, `str`) is text
   for every pointee; a `Pointer[Int64]` is not.
3. The regressions to add are the two programs above, build-and-run on both
   architectures, in `test_formal_external_call.py` or `test_formal_run.py`: the
   string read back must equal what was written, so a misclassification cannot
   pass by reading an address as a `char *`.
4. It is a value-model change, so it wants a sweep: `String(...)` sits on the
   `printf`/`print`/`len` paths, and `_expr_str_kind` is asked from all three.
   That is the reason this is a doc and not a patch.
