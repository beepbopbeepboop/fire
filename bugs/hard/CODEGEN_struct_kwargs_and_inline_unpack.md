# HARD BUG: `struct` keyword arguments are silently dropped, and the inline mixed int+float unpack still returns raw bits

**State: FULLY FIXED 2026-09-29 — this doc is kept open for one more pass
over the evidence, not because a named residue is left.** Both headline
items were already closed; the residue under item 2 (reads with no
compile-time slot index, copies of a mixed result, and a class attribute's
`Struct` handle) is now fixed too, in two parts — see "Residue" below for
what landed and what each measurement was before. The one thing still
missing is a different bug this work uncovered, filed separately and named
in the last section: a function that returns a `MojoList *` it built in a
LOCAL is typed `int64_t` by return-type inference, so the caller print()s
the pointer's address and iterating it SEGFAULTS — pre-existing, and
independent of `struct`.

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

### Residue — CLOSED 2026-09-29, in two parts

The residue above was real, and the reason it was hard is a single design
decision: the per-slot kinds lived in a **codegen-side table keyed by the C
value name** the unpack was assigned to. Every derivation of that value
lost them, and a read with no compile-time slot index had nowhere to put a
value with no single right C type. Both halves are now fixed.

**Part 1 — the kinds travel with the VALUE.** `mojo_list_set_kinds`
(`runtime/fire_runtime.c`) records one byte per slot against the live
`MojoList` address, in a payload-carrying open-addressed side table beside
the existing `_PtrReg` registries — deliberately not a field on `MojoList`,
which would move every stack-declared list in every generated program plus
the C++ backend's own copy of the container. The format compiler already
builds the per-op list, so the kinds cannot disagree with the values
`_struct_unpack_at` stores; a UNIFORM format records nothing at all
(`MojoStructFmt.kinds` stays NULL), which is why `struct.unpack('<HH', buf)`
pays exactly zero for this. Every list->list copy hands them along, and
every list repr defers to a value's own kinds before reading it through one
accessor — so the answer is right whichever helper the codegen picked,
which is what a derived value (whose compile-time element type is a guess)
needs.

**Part 2 — a read with no compile-time index is boxed.** The kind has to
leave the slot next to the value, because the C type cannot carry it:
`mojo_list_get_boxed` returns the raw word for every slot that is not a
float, and the address of a 16-byte box for a float slot. `mojo_is_boxed`
is the one predicate a consumer needs (same registry shape as
`mojo_is_registered_list`), `mojo_boxed_is_str` excludes a box so it is
never handed to `strlen`, and `print`/`str` resolve it in one call via
`mojo_repr_boxed`. Boxes are cached per (list, slot) rather than per read.

A class attribute's `Struct` handle — the fourth residue bullet, which is a
*tracking* gap and not a container one — is fixed separately: the
declaration's format is recovered and keyed by (owning struct, attribute),
so two classes declaring the same name with DIFFERENT formats both come out
right instead of one of them being guessed at.

Measured against CPython 3.14 on the same program, all of these were wrong
before and are right now:

    for x in struct.unpack('<if', struct.pack('<if', 1, 1.0)): print(x)
      was  1 / 4607182418800017408        now  1 / 1.0
    print(struct.unpack('<if', b)[i])      was  4607182418800017408  now  1.0
    print(list(struct.unpack('<if', b)))   was  [1, 4607182418800017408]
                                           now  [1, 1.0]
    print(struct.unpack('>dhh', ...)[:])   was  [4607182418800017408, 2, 1]
                                           now  (1.0, 2, 1)
    struct A: var F = struct.Struct('<if')  then  A.F.unpack(b)[1]
      was  4612811918334230528            now  2.5
    print([1, 2.5])                        was  [1.0, 2.5]           now  [1, 2.5]
    for y in [1, 2.5]: print(y)            was  1.0 / 2.5            now  1 / 2.5

Uniform formats (`<2f`, `<3i`, `<4s`, and also `>dhh`, `<Bd`, `<fd`) are
correct through the subscript AND the whole-result repr, and are covered by
both spellings in `test_gimple_runner.py` so they cannot regress silently.
An ordinary int-list subscript still emits the `mojo_list_get_int` it
always did: the boxed read is chosen by a compile-time marker
(`gen._maybe_kinds_vals`), not by changing the general case.

Six new regression tests in `test_gimple_runner.py`:
`gimple_struct_mixed_reads_survive_a_derivation`,
`gimple_struct_mixed_reads_without_a_static_index`,
`gimple_struct_mixed_reads_survive_a_function_boundary`,
`gimple_heterogeneous_list_literal_keeps_each_slot`,
`gimple_struct_class_attribute_handle_format_known`, and the extended
`gimple_struct_uniform_formats_still_uniform`.

### What is still missing, and where it is written down

A mixed unpack result that crosses a function boundary **through a local**
(`var t = struct.unpack(...); return t`) never becomes a `MojoList *` in the
first place, so it is a return-TYPE inference bug, not a per-slot-kinds one:
the caller print()s the pointer's address and `for y in f()` segfaults —
on the base commit too, and for an ordinary `return [1, 2, 3]` as well.
Filed as `bugs/CODEGEN_list_return_via_local_types_the_return_int64_t.md`
with the two gaps in the seed and the blast radius to check. The
cross-function half that IS this mechanism (`def f(): return
struct.unpack(...)`) is fixed and tested.

## 3. Genuinely closed, and worth keeping in mind as done

Verified correct, for the record, so nobody re-opens them:

- `struct E: var F = struct.Struct('<HH')` then `E.F.unpack(b'\x01\x00\x02\x00')`
  -> `(1, 2)`, no segfault (the class-field-init path).
- Scalar class attrs `var NAME/N/ITEMS/TABLE` -> `hello 5 0.0 0`, matching CPython.
- Bare `FIELD_STRUCT = struct.Struct('<HH')` class attribute.
- `pack(fmt, a, *rest)` splat and the `pack(...) + X` tail form.

## 4. Found while fixing the above, and NOT this doc's bug

**FIXED 2026-09-27, doc deleted. Re-verified 2026-09-29, still fixed:**
`print(f"{a_list}")`, `print(str(a_list))` and `print(f"{a_set}")` /
`f"{a_dict}"` all give the container's repr, matching CPython, on the
current tree. `_stringify_value` (`mojo/backend_gimple/emit_infra.py`) had
gained the `MojoList *`/`MojoSet *`/`MojoDict *` branches `print`'s dispatch
already had (reusing `_list_repr_call`/`_mojo_repr_set`/`_mojo_repr_dict`),
plus the same boxed-container re-typing check (`_get_actual_type`) `print`
does before its own branches, so a call result boxed into
`int64_t`/`void *` resolves too. Regression: `test_gimple_runner.py`'s
`gimple_fstring_and_str_of_containers`. It has no doc left in `bugs/` to
re-open, which is why the task's "file one if there isn't one" does not
apply — there is nothing left to file.

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
  `_struct_slot_kinds` / `_struct_elem_ctype` docstrings;
  `_struct_tag_unpack_result`'s `_maybe_kinds_vals` mark;
  `_struct_attr_format` (the class-attribute lookup);
  `_struct_value_codes` (now a thin delegate).
- `mojo/backend_gimple/emit_infra.py` — `_list_repr_fn`'s kinds branch,
  `_struct_slot_kind_bytes`, `_list_repr_call`; the `mojo_repr_boxed` arms
  in `_gen_print` and `_stringify_value`.
- `mojo/backend_gimple/emit_calls.py` — the boxed subscript in the
  `MojoList *` branch of `_lower_subscript`; `list(x)`'s kinds inheritance
  in `_lower_ctor_from_iterable`; the return-boundary mark in
  `_lower_named_call`.
- `mojo/backend_gimple/emit_exprs.py` — `_lower_list_literal`'s per-element
  append for a numeric mix, and `_list_literal_slot_kind`.
- `mojo/backend_gimple/emit_loops.py` — `_gen_for_list`'s boxed read and
  the loop target's `int64_t` declaration for a kinds-carrying list.
- `mojo/backend_gimple/emit_stmts.py` — the `var` propagation of a
  `struct.Struct` handle's format, of the per-slot kinds, and of the
  kinds-carrying marker.
- `mojo/backend_gimple/module_gen.py` — the class-attribute format table
  in `gen_module_impl`; `_returns_kinds_valued` /
  `_infer_return_maybe_kinds` and the single pass over them.
- `mojo/middle/types.py` — `_struct_ctor_format`, `_struct_format_codes`,
  `_struct_format_is_mixed`.
- `mojo/middle/loops_shared.py` — `_tuple_elem_value`.
- `gimple_codegen.py` — `_struct_formats`, `_struct_attr_formats` /
  `_struct_attr_formats_scoped`, `_maybe_kinds_vals`, `_boxed_vals`,
  `_return_maybe_kinds`, the `_list_repr_call` delegate, and the
  `mojo_repr_boxed` / `mojo_list_get_boxed` / `mojo_list_inherit_kinds`
  runtime signatures.
- `runtime/fire_runtime.c/.h` — `mojo_repr_list_kinds`; the kinds side table
  (`mojo_list_set_kinds` / `_get_kinds` / `mojo_list_slot_kind` /
  `mojo_list_inherit_kinds`) and its uses in the list->list derivations;
  `MojoStructFmt.kinds` and `_struct_op_kind`; the box
  (`mojo_list_get_boxed`, `mojo_is_boxed`, `mojo_box_double`,
  `mojo_box_int`, `mojo_repr_boxed`) and the `mojo_boxed_is_str` exclusion.
- `mojo/backend_gimple/module_gen.py` — the one emitted `_mojo_repr_list`
  guard that consults a value's own kinds.
- Tests: `test_gimple_runner.py`'s `gimple_struct_mixed_int_float_formats`
  (extended: it previously wrote ONLY the `var m = ...` spelling, so it
  structurally could not see this item), `gimple_struct_uniform_formats_still_uniform`
  (extended with the whole-result repr), `gimple_struct_keyword_arguments`
  (all thirteen keyword-reachable failure messages compared against
  CPython's text), and the five new ones named under "Residue".

