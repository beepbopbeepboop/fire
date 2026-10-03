# FORMAL_a_module_cannot_store_through_a_pointer_with_a_declared_pointee: the missing half of every `struct tm` answer

**Class:** value-model gap (the store side of what
`bugs/FORMAL_pointer_value_model.md` gives for the load side).
**Effect:** a module can READ a C library's struct field-wise and cannot WRITE
one, so every `time` name whose answer is a struct — and every `stat` out
parameter — is refused at the ARGUMENT rather than at the layout.

Found while closing `bugs/FORMAL_time_struct_shaped_answers.md`, whose next step
was "give a struct an addressable field layout across a dylib boundary". The
measurement says the layout is **not** what is missing, which is why this is a
separate doc rather than a line in that one: the read half already works.

## What was run

```
$ python3 test_formal_time.py structroute
PASS structroute  read yes / store no
```

That group is the standing measurement, added with this doc
(`test_formal_time.py`, `group_structroute`). Three facts, all on arm64 and
x86-64:

| what a module tries | result |
|---|---|
| `var p: Pointer[UInt8] = external_call["getenv", Pointer[UInt8]](name)` then `(p + k).value()` | **works** — byte loads, checked against the bytes of a value the test put in the environment |
| the same with `Pointer[Int32]` | refused: "the load's width is the pointee's — the address is the result of a call, and a callee that returns `p + k` hides its arithmetic" |
| `p.value() = 1` (a parameter annotated `Pointer[UInt8]`) | refused: "assignment target must be a plain name" (arm64) / "assignment to CallExpr is not lowered … only a plain name has a home" (x86-64) |

`p[0] = 1` is refused too, by the subscript-store path rather than the
assignment path.

## Why that blocks five `time` names

`localtime`, `gmtime`, `mktime`, `strftime` and `get_clock_info` are absent from
`formal/hostmods/time.mojo` because a `struct tm` has no representation on this
path. With the read half working, the exact missing piece is narrower than that,
and it is not the layout:

* `localtime`/`gmtime` take a `const time_t *`. A module cannot build the eight
  bytes that pointer must address — no store, no module state — so there is no
  valid ARGUMENT to pass. Passing an integer literal instead passes a null
  `time_t *` and the image segfaults inside libc (measured: exit -11);
* `mktime`/`strftime` take a `struct tm *`, i.e. 36 bytes the module would have
  to fill, one field at a time — the same missing store;
* `get_clock_info` returns a record, which is a different absence (a host-object
  type, not a memory question) and is not what this doc is about.

So the fix is ONE capability, and it is the mirror of the load rule the model
already implements (`formal/model.py`'s "a SCALAR pointee is a LOAD"): **a
STORE of the pointee's width to the address a pointer expression denotes, under
the same agree-or-refuse rule** — the receiver must have a recorded pointee, and
a value wider than the pointee must be refused rather than truncated.

## The exact next step

1. **One analysis, both backends, in `formal/model.py`.** The two emitters each
   raise their own spelling of the same refusal today
   (`formal/arm64_codegen.py:1782`, `formal/x86_64_codegen.py:1654`-region), so
   a rule added per backend would be two answers to "what does `p.value() = v`
   mean". The recogniser belongs beside `pointee_of_type_text` /
   `dereference_lowering`, where the load side already decides the same
   question, and it must answer "which pointer, which pointee, which width".
2. **Emit a store of that width.** `arm64_codegen.py` has `_store_var` and a
   `str` byte store; `x86_64_codegen.py` has `_store_at_abs(addr, src)`. Both
   need a pointee-width store at a computed address, which is the same shape as
   their existing subscript store — the one that already handles
   `buf[i] = v`.
3. **Refuse the cases the load refuses**, so this cannot become a way to emit a
   store at a width nothing established: a receiver with no recorded pointee, a
   receiver that is a frame address (a `struct` field's `.value()`), and a
   value whose width exceeds the pointee's. `bugs/FORMAL_pointer_value_model.md`
   owns the load-side rule and its reasoning; this is its mirror, and the
   refusals must be worded from the same argument so the two do not drift.
4. **Then, and only then, the five names.** `localtime_year(t)` and friends need
   a `time_t` written into a buffer and then read back field-wise, and each
   field is four little-endian byte loads — which the measurement above says
   already works. The API shape (nine scalar functions against CPython's one
   struct) is a judgement and is written down in the `time` doc; the capability
   is not.

## What this is NOT

Not the layout table `bugs/FORMAL_stat_out_parameter_is_unreadable.md` asks for,
and not `bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md`'s
pointer-with-declared-pointee rule: both are about reading, and reading works
for a byte-wise pointee today. Whoever takes those two should start from the
`structroute` group rather than from their own reproduction, because it is the
measurement that tells them which half is missing.