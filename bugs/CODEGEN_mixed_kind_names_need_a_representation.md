# CODEGEN_mixed_kind_names_need_a_representation

## Summary
The compiled path has no representation that holds values of two kinds in one name, one parameter, or one slot:
a str and a float (`val = d["key"]` on a float dict, then `val = "text"`), or a container and a scalar (a parameter
passed a list at one call site and a number at another). The integer box (`mojo_box_int`) carries only integer kinds.
So the compiler refuses these programs on purpose, with two messages:
- `a name bound to a tagged generator word ... cannot also hold a value of another C type (str or float)`
  (`emit_infra.py`, `MIXED_NAME_NON_INT64_REFUSAL`; also raised for a str/float store into a name, `emit_stmts.py`)
- `parameter ... is passed a container at one call site and a str or number at another`
  (`module_gen.py`, `_refuse_mixed_container_params`)

Effect when this doc was written: `mojo/middle/coro.py` could not compile, and the dict-slot regression test
(case 2) was refused by design. Both of those specific refusals are now gone (see Status); `coro.py` still fails on a
separate generator shape.

## Why it matters
`coro.py` is part of the compiler's own sources. The fire.ci self-host build needs it, so the compiler cannot be
built from its own source while this refusal stands. See `CODEGEN_dict_slot_reads_refuse_compiler_sources.md`.

## Options
1. A per-kind representation: a tagged value struct (kind + payload) for names and parameters that see more than one
   kind. Needs runtime support and codegen at every read and store of such a name.
2. Specialise the function per kind (the existing per-kind clone pass, `_gmi_specialize_literal_kind_clones`), which
   covers literal arguments only today. Extending it to non-literal call sites is a smaller step, but a parameter that
   is rebound inside the body still needs option 1.
3. Rewrite the source so each name has one kind. This is what the compiler's own sources do today, and it is what `coro.py`
   would need unless option 1 or 2 lands.

Not decided. Option 3 is a source change, not a codegen fix.

## Status (2026-11-11)

- LANDED: the per-kind representation for a NAME that holds more than one
  SCALAR kind (`int` / `double` / `str`). `emit_infra.mixed_scalar_locals`
  finds such a name, the store arm in `emit_stmts.py` declares it `int64_t`
  and boxes a float/str store with `mojo_box_from_double` /
  `mojo_box_from_str` (a bool keeps its kind with `mojo_box_from_bool`; an
  int stays its bare word), and the consumers read the kind back
  (`mojo_repr_boxed`, `mojo_box_word`, `mojo_float_arith_select`,
  `mojo_len_word`, the box-aware `_len_of_boxed` str test, and box-aware dict
  keys in `_char_to_cstr`). Both store orders, the dict-read case, branches,
  and `var` declarations work. The tagged-generator mixed float/str cases
  (the two `bugs/mid/CODEGEN_tagged_generator_mixed_type_step2-part*` docs)
  are covered by the same path through `ginf.tagged_mixed_name`.
- LANDED: the container/scalar parameter refusal no longer fires for a false
  positive. `_is_noncontainer_arg` (`module_gen.py`) treated an `int64_t`
  local as "provably not a container", but `int64_t` is also the pre-pass's
  storage default for each target of a multi-value UNPACK
  (`a, b, ... = call()`), where the per-element type is genuinely unknown.
  It now exempts exactly those unpack targets (recorded as
  `_tuple_unpack_locals` by `resolve_shared._infer_local_var_types_core`); a
  literal argument, a call result, a parameter and every ordinary local are
  still non-container observers, so `each([4, 5])` beside `each("de")` or
  beside `each(n)` where `n = 3` is still refused. This removes `coro.py`'s
  `parameter 'real_params' ... passed a container at one call site and a str
  or number at another` refusal, which was false at every call site: all of
  them pass a list, and `real_params` is one target of a six-value unpack.
- STILL BLOCKED: `mojo/middle/coro.py` compiles past the parameter refusal and
  now stops on an INDEPENDENT generator shape: its two-level-deep recursive
  generator `_walk_lists` (inside `_lower_callable_choices._rewrite_fn`) uses
  a dynamic `getattr`, reaches the C++ coroutine companion instead of the A3
  stack-switch path, and that companion refuses dynamic attribute names. See
  `CODEGEN_coro_nested_recursive_generator_getattr.md` (filed with the exact
  repro and next step). `coro.py` therefore does not compile yet, and the
  fire.ci self-host build was NOT run.
- The dict-slot regression test's case 2 now compiles and prints the CPython
  answer (`test_dict_slot_read_regression.py`).

Option 2 (per-kind clone) was NOT taken: the box already exists and is the
representation the rest of the compiled path uses for kind-mixed words.

## Done when

`python3 tools/memslot.py --gb 8 --label mixed-kind -- python3
test_mixed_kind_name_representation.py` passes (a float and a str in one name
— literal, dict-read and branch shapes — plus a container and a number passed
to one parameter, all pinned to CPython), `mojo/middle/coro.py` compiles, and
the fire.ci build is green. Then delete this doc in the same commit as the
change that closes it.
