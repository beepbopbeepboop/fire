# The tagged word box: how it is stored and read

Header: this is the reference for step 1 of
[`docs/tagged_generator_mixed_type-plan.md`](tagged_generator_mixed_type-plan.md).
Every claim below cites the function it was read from. The store sections are
written here; the read sections are appended by the step 1 part 2 round.

## 1. The cell (store side)

`MojoBox` is a heap cell in `runtime/fire_runtime.c` (~1673-1688):

- `uint64_t magic`, equal to `MOJO_BOX_MAGIC` (`0x4D4A424F58310001`, "MBOX1").
  The magic is chosen so it can never equal a 31-bit class-name CRC struct type
  tag.
- `int64_t bits`, the payload word.
- `char kind`, the discriminator. It is the slot's own kind byte, copied from
  the list at box time (see the comment on the struct).

A boxed value IS the cell's address passed as an `int64_t`. The only way to tell
a box from a real value is `mojo_is_boxed` (~1692), which asks the `_reg_box`
pointer registry (`_pr_add` at each constructor). `v < 65536` is never a box.

The constructors and the `kind` byte each one writes:

| constructor | kind | where |
|---|---|---|
| `mojo_box_from_double` | `'d'` | ~1814-1821 |
| `mojo_box_from_bool` | `'b'` | ~1828-1835 |
| `mojo_box_from_str` | `'p'` | ~1845-1852 |
| `mojo_box_none` | `'n'` | ~1860-1869 |
| `mojo_id` | `'i'` | ~2257-2276: a pointer-shaped int token, interned per identity in `_id_tab` |

Kinds that come from a list slot are copied by `mojo_list_get_boxed` (~1726).
It returns the bare word, unboxed, for an int slot (`'i'`), an object slot
(`'o'`), and a nested-container slot (`'l'`), because their words are already
self-describing. Every other slot kind, including bytes (`'s'`), is boxed with
its kind copied into `MojoBox.kind`, and boxes are cached per (list, slot).

## 2. The tracking (store side)

All per-function state lives in `mojo/backend_gimple/emit_infra.py`:

- `gen._boxed_vals` (set at ~245, cleared at ~515 by the function reset): a
  temp or local C name whose value is a box.
- `gen._tagged_word_vals` (set at ~250, cleared at ~516): the subset of
  `_boxed_vals` that is a mixed-generator word, which must be read by kind.
- `gen._dyn_word_vals` (~421) and `gen._dyn_word_locals` (~425, populated at
  ~442): a word whose kind only the runtime knows. The `_locals` set is keyed
  by the Mojo name, not the C name.
- `gen.var_types`: the local's declared C type. A box-holding local is declared
  `int64_t`.

Scope rule: a box is a property of the VALUE, and a temp name cannot outlive the
function that made it. That is why every set above is reset per function.

Function-scope swaps save and restore these sets in the `fs_*` fields (~906-1037,
with the save at ~1013-1040 and the restore at ~1130-1157). The
`_local_bindings_cache` is saved as `fs_local_bindings_cache` (~999, ~1116,
~1200).

## 3. The stores (store side)

### 3a. The simple-name assignment arm: `mojo/backend_gimple/emit_stmts.py` (~1590-1660)

- `_tagged_bind` and `_for_copy` (~1590-1600) decide whether the stored value
  is a tagged word.
- `_keep_tagged_box` (a local flag, not a module symbol; ~1598-1603) is the arm
  for a tag-pure name. It is true when the store is `int64_t` and the value is
  in `_tagged_word_vals` (or is a copy of a tagged for-target), and the name is
  a `tagged_next_bind_name` or `tagged_recv_name`. The local is then declared
  `int64_t` and the name is registered in `_boxed_vals`, `_tagged_word_vals`
  and `_dyn_word_locals` (~1646-1650).
- The mixed-name arm (~1629-1637): when `tagged_mixed_name` holds for an
  `int64_t` store into an `int64_t` local, a plain value (one not already in
  `_boxed_vals` or `_tagged_word_vals`) is boxed with `mojo_box_int` into a new
  temp, and the local keeps the box of the store that ran last.
- The refusal, at ~1612-1617. It raises `MIXED_NAME_NON_INT64_REFUSAL` (defined
  at `emit_infra.py` ~3744) in two cases:
  1. a tagged word stored into a name whose C type is a float or pointer
     (`_tagged_bind and is_non_int_c_type(var_types[name])`). Without the
     refusal a bare word read as a box segfaults for `char *`, and prints `1.0`
     or `0.0` for `double`;
  2. a non-int64 store (`is_non_int_c_type(vtype)`) into a name that
     `tagged_mixed_name` marks as mixed (`emit_infra.py` ~3758). The same
     bare-word hazard applies.
- A second refusal with the same message, at ~1623-1627: a `double` and a
  `char *` stored into the same name of one function. It is tracked in
  `gen._stored_kinds`, keyed by (function, name). No representation holds both.
- The `mojo_box_word` fallback (~1653-1657): an `int64_t` store into a name that
  is a box in `_boxed_vals` but does not keep the box is unwrapped with
  `mojo_box_word` into a temp, and that temp is added to `_dyn_word_vals`.

`tagged_mixed_name` (`emit_infra.py` ~3758-3795) is the predicate behind the
mixed-name arm and case 2. It is true when a name is bound to a tagged word
somewhere in the function (a copy of a tagged for-target, a copy of a tagged
`next()` name, or `next(g)` over a tagged generator) and also to plain values
elsewhere, and is not a `tagged_next_bind_name`.

### 3b. The generator for-target arm: `mojo/backend_gimple/emit_loops.py` (~3985-4011)

A generator whose `api` has `mixed_slots` yields tagged words, and the loop
target is registered the way a `next(g)` bind is:

- Single target (~3998-4006): when `mixed_slots` holds and the target is
  `int64_t`, the target is added to `_boxed_vals` and `_tagged_word_vals`.
- Tuple-unpack target (~3988-3997): each `int64_t` unpacked name is added to
  `_boxed_vals` only, not `_tagged_word_vals`. The comment there says the
  generator yields BOXES in its int64 slots when it iterates a kind-mixed list
  parameter.
- The `_dyn_word_locals` arm (~4007-4011, the `elif`): an `int64_t` value slot
  that the kind analysis could not prove is a word of unknown kind, so the
  Mojo name is added to `_dyn_word_locals`.

## Symbols to grep

`MojoBox`, `MOJO_BOX_MAGIC`, `mojo_is_boxed`, `mojo_box_from_double`,
`mojo_box_from_str`, `mojo_box_from_bool`, `mojo_box_none`, `mojo_id`,
`mojo_list_get_boxed`, `_boxed_vals`, `_tagged_word_vals`, `_dyn_word_locals`,
`_keep_tagged_box`, `MIXED_NAME_NON_INT64_REFUSAL`, `tagged_mixed_name`,
`mojo_box_int`, `mojo_box_word`, `_stored_kinds`.

## Test baseline for the step 1 round

Carried over from the step 1 part 1 round (measured there at f9c83c88f,
2026-11-11, deterministic across two runs; not re-measured since, and the
step is doc-only). The command was
`python3 tools/memslot.py --gb 8 --label tgbox-doc -- python3 test_gimple_generator_runner.py`,
which gave `434 passed, 22 failed`. The 22 failures are pre-existing and tracked in
`bugs/mid/SUITE_gimplegenerators.md`:

    cpp_coroutine_kwargs_lambda_str_value_refused
    cpp_coroutine_kwargs_lambda_value
    cpp_coroutine_kwargs_only_local_positional_call_refused
    cpp_coroutine_starargs_kwargs_lambda_value
    cpp_coroutine_starargs_lambda_bool_arg
    cpp_coroutine_starargs_lambda_double_arg_refused
    cpp_coroutine_starargs_lambda_rebound_across_branches
    cpp_coroutine_starargs_lambda_str_arg_refused
    cpp_coroutine_starargs_lambda_value
    cpp_coroutine_starargs_lambda_via_filter
    cpp_coroutine_starargs_lambda_via_map
    cpp_coroutine_starargs_only_local_kwarg_call_refused
    cpp_coroutine_unpack_boxed_source_refused
    cpp_coroutine_unpack_own_starargs_param
    cpp_for_over_callable_param_walks_and_globs
    cpp_fsutil_iter_files_walk_tree_glob_tree
    cpp_generator_double_param_called_by_keywords
    generator_method_call_pads_nonzero_offset_default
    generator_os_fwalk_fd_relative_walk
    kwargs_generator_method_packs_keywords
    nested_generator_method_self_escaping_refused
    received_or_str_operand_cpp

A change in this area must add no failure to that list, and every
`tagged_for_target_*` case must pass.
