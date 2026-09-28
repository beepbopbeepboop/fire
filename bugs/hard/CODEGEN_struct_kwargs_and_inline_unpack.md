# HARD BUG: `struct` keyword arguments are silently dropped, and the inline mixed int+float unpack still returns raw bits

**State: item 1 CLOSED, item 2 CLOSED for every statically-indexed read, with
named residue below.** Both items' headline repros are fixed; what is left is
the set of reads with no compile-time slot index, which is an architectural
limit rather than an oversight, and one genuinely separate bug found on the
way (`f"{list}"`/`str(list)`), which has its own doc.

Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_struct_module.md`. That doc was correctly closed for the mechanisms
it recorded, but two of its "closed" statements do not hold for all the
spellings they appear to cover, and one of them is a silent miscompile — the
exact class `bugs/hard/` exists for.

## 1. `struct.*` keyword arguments are dropped, not refused — **CLOSED**

The removed doc claimed keyword arguments "fall through (guarded out);
positional only", twice. There was no guard. `node.kwargs` was never inspected
at all, so a keyword call ran with the default and returned a plausible wrong
answer:

    s = struct.Struct('<HH'); b = b'\x00\x00\x05\x00\x06\x00'
    s.unpack_from(b, 2)                  -> (5, 6)     correct (positional)
    s.unpack_from(b, offset=2)           -> (0, 5)     read offset 0

    struct.unpack_from('<H', b'\xff\xff\x02\x00', 2)   -> (2,)   correct
    struct.unpack_from('<H', b'\xff\xff\x02\x00', offset=2) -> (0,) WRONG

    struct.calcsize('<HH')               -> 4
    struct.calcsize(fmt='<HH')           -> 0          CPython raises TypeError

The `unpack_from(offset=...)` case was the dangerous one: it returned
well-formed data read from the WRONG OFFSET, with no diagnostic. A caller
that uses `offset` to walk a record layout got silently misparsed records.

Root cause as recorded: `_lower_struct_module_call` did `args = list(node.args)`
and never looked at `node.kwargs`. The bytes/memoryview path
(`_lower_bytes_method`, reached with `node.kwargs` threaded through) does it
properly, so the omission was local to `struct`. The `Struct` INSTANCE methods
were worse than silent: `_lower_struct_instance_method` indexed `args[0]` with
no bound at all, so `s.unpack(buffer=b)` was a codegen-time `IndexError`.

### What landed

Arguments are now bound through `_struct_bind_args` before any of them are
lowered, against a per-entry-point signature table. The table is a
**measurement** of CPython 3.14, not an inference from the docs: every
candidate keyword name was passed to the real module and to a real
`struct.Struct` instance, and exactly three entry points came back accepting
any:

| accepts keywords | names |
|---|---|
| `struct.Struct` | `format` |
| `struct.unpack_from` | `buffer`, `offset` |
| `Struct.unpack_from` | `buffer`, `offset` |

Everything else takes none: `calcsize`, `pack`, `unpack`, `iter_unpack`,
`pack_into`, `Struct.pack`, `Struct.unpack`, `Struct.pack_into`. Note the
format string is positional-only even on `unpack_from`, which is why
`struct.unpack_from(fmt=..., buffer=..., offset=...)` reports "takes at least
1 positional argument" rather than binding.

A rejected call raises at RUNTIME (not as a codegen abort), after its argument
expressions have been evaluated, because the surrounding program is expected to
catch it. The messages are CPython's own, and so is the ORDER they are chosen
in, which is measurable and not the convenient one: an entry point with no
nameable parameter refuses every keyword before anything else is examined, on
`unpack_from` an unfilled required parameter outranks an unknown keyword, and a
keyword naming an already-filled slot is third. `struct.Struct`'s binder checks
the total argument COUNT before any name, so a second argument is always
"takes at most 1 ...".

Deliberately NOT implemented: the arity errors of a purely POSITIONAL call that
is short an argument. CPython's text for those is a different string per entry
point ("unpack expected 2 arguments, got 1", "missing format argument",
"pack_into expected offset argument") and they failed before this change and
fail the same way after. The one exception is a required parameter left empty
*by* a keyword, which is the binder's own doing.

An extra parity fix came with the binder and is called out because it is not
one of the two items: `struct.Struct()` with no argument at all used to compile
to a `Struct` with format `''` (a Struct that misparses everything) and is now
CPython's `TypeError`. Nothing in this tree calls it.

Also: the `and not getattr(node, 'kwargs', None)` condition another agent had
added to the struct dispatch gate in `_lower_method_call` is GONE. It did not
make kwargs safe — a keyword call fell through to the generic receiver
dispatch, which answered `0` for `calcsize(fmt=...)` and read offset 0 for
`unpack_from(offset=...)`, i.e. the same wrong answers one layer down — and
leaving it would have shadowed the correct binding.

## 2. Mixed int+float `unpack` still returns raw IEEE bits — **CLOSED for every statically-indexed read**

    print(struct.unpack('<if', struct.pack('<if', 1, 1.0)))
      CPython:    (1, 1.0)
      was:        (1, 4607182418800017408)      <- the float's IEEE-754 bits

> **The removed doc's mechanism for this item is wrong, and so is its
> "uniform formats are fine".** It recorded the degradation as happening
> "with no local name to hang the per-slot kinds on". That is not the
> mechanism: the kinds are a property of the VALUE, and the local-name case
> was equally broken. Measured on the tree this doc was written against, of
> the ways to consume a `'<if'` result, exactly ONE was correct — the
> literal-index subscript `m[1]`:
>
> | spelling | was |
> |---|---|
> | `print(m)` | `(1, 4607182418800017408)` — a LOCAL, still wrong |
> | `f"{m}"` | garbage bytes, not text at all |
> | `a, b = m` | `1`, `4607182418800017408` |
> | `list(m)` | `[1, 4607182418800017408]` |
> | `for x in m:` | `1`, `4607182418800017408` |
> | `m[1]` | correct |
>
> And `>dhh`, `<Bd` and `<fd` were only correct through that same subscript:
> `print(struct.unpack('>dhh', ...))` printed `(4607182418800017408, 2, 1)`.
> A mixed int+bytes format (`<2sH`) printed its bytes slot's pointer as a
> decimal address, `4376289936`.

### What landed

Three consumers, all of which read a slot whose index is a compile-time
constant, now consult `_struct_slot_kinds`:

- **the whole-result repr** — a new `mojo_repr_list_kinds(l, kinds)` runtime
  helper, chosen by `_list_repr_fn` and given the slot-kind string as a second
  argument. Covers `print(m)`, and the uniform formats' repr too, which now
  agrees with their subscript (they already had an exact helper; they just were
  not being asked in this shape before).
- **the `a, b = m` destructuring target** — `loops_shared._tuple_elem_value`,
  the single hook every statically-indexed tuple read goes through.
- **the `Struct` instance methods** — `_lower_struct_instance_method` was
  passing `codes=None` to `_struct_tag_unpack_result`, so `s.unpack(buf)` had
  no kinds at all and degraded exactly like the module spelling used to. A
  `struct.Struct(...)` handle now records its const-folded format, propagated
  across `var` bindings like `_struct_slot_kinds` already was.

`Struct` reached through a class ATTRIBUTE (`self.FMT.unpack(data)`) still has
no format: the receiver is a struct field read, not a tracked value name.

### Residue, with the reason it is residue

A `MojoList` slot holds no type tag, so a read whose slot index is not known at
compile time needs ONE static C type for a read that has no single right
answer. That is not specific to `struct` — a heterogeneous `[1, 2.5]` literal
prints `1.0` and iterates as `1.0, 2.5` for the same reason. Fixing it means
either boxing the elements or a per-slot tag in the container, which is a
container-architecture change, not a `struct` fix. So, still wrong, with the
reason recorded so nobody re-derives it:

- `for x in struct.unpack('<if', b):` — the loop variable has one C type.
- `struct.unpack('<if', b)[i]` with a computed `i`.
- `list(struct.unpack('<if', b))` / any copy — `mojo_list_copy` and
  `mojo_list_slice` build a fresh list, which has no kinds and no format to
  recover them from.
- `self.FMT.unpack(data)` where `FMT` is a class attribute (see above).

Uniform formats (`<2f`, `<3i`, `<4s`, and also `>dhh`, `<Bd`, `<fd`) are
correct through the subscript AND the whole-result repr, and are covered by
both spellings in `test_gimple_runner.py` so they cannot regress silently.

## 3. Genuinely closed, and worth keeping in mind as done

Verified correct, for the record, so nobody re-opens them:

- `struct E: var F = struct.Struct('<HH')` then `E.F.unpack(b'\x01\x00\x02\x00')`
  -> `(1, 2)`, no segfault (the class-field-init path).
- Scalar class attrs `var NAME/N/ITEMS/TABLE` -> `hello 5 0.0 0`, matching CPython.
- Bare `FIELD_STRUCT = struct.Struct('<HH')` class attribute.
- `pack(fmt, a, *rest)` splat and the `pack(...) + X` tail form.

## 4. Found while fixing the above, and NOT this doc's bug

**FIXED 2026-09-27, doc deleted.** `f"{a_list}"` and `str(a_list)` emitted
`mojo_str((void *)list)` instead of the list repr, printing the container
header as raw bytes — not `struct`-specific and not mixed-format-specific.
`_stringify_value` (`mojo/backend_gimple/emit_infra.py`) gained the
`MojoList *`/`MojoSet *`/`MojoDict *` branches `print`'s dispatch already
had (reusing `_list_repr_call`/`_mojo_repr_set`/`_mojo_repr_dict`), plus the
same boxed-container re-typing check (`_get_actual_type`) `print` does
before its own branches, so a call result boxed into `int64_t`/`void *`
resolves too. Regression: `test_gimple_runner.py`'s
`gimple_fstring_and_str_of_containers`.

## A claim in the removed doc that did NOT reproduce

It claimed no interpreter `struct` module exists, so a comptime-evaluated
`struct.Struct(...)` default still `NameError`s. Both shapes were reported as
working through `fire.py run` in the doc that replaced it. In THIS checkout
`fire.py run` on any `struct.*` call raises
`NameError: name 'struct' is not defined` — there is no interpreter `struct`
support at all, so the compiled path is strictly ahead of it and there is no
interpreter/compiled parity to hold. Reported, not fixed: the interpreter is
not where this doc's work belongs.

## Where

- `mojo/backend_gimple/emit_methods.py` — `_STRUCT_CALL_SIGS`,
  `_struct_kwarg_rejection`, `_struct_missing_required`, `_struct_bind_args`,
  `_struct_bind_or_raise`, and the two lowerings that call them;
  `_struct_slot_kinds` / `_struct_elem_ctype` docstrings.
- `mojo/backend_gimple/emit_infra.py` — `_list_repr_fn`'s kinds branch,
  `_struct_slot_kind_bytes`, `_list_repr_call`.
- `mojo/middle/loops_shared.py` — `_tuple_elem_value`.
- `mojo/backend_gimple/emit_stmts.py` — the `var` propagation of a
  `struct.Struct` handle's format.
- `gimple_codegen.py` — `_struct_formats`, the `_list_repr_call` delegate.
- `runtime/fire_runtime.c/.h` — `mojo_repr_list_kinds`.
- Tests: `test_gimple_runner.py`'s `gimple_struct_mixed_int_float_formats`
  (extended: it previously wrote ONLY the `var m = ...` spelling, so it
  structurally could not see this item), `gimple_struct_uniform_formats_still_uniform`
  (extended with the whole-result repr), and the new
  `gimple_struct_keyword_arguments`, which compares all thirteen
  keyword-reachable failure messages against CPython's text.

