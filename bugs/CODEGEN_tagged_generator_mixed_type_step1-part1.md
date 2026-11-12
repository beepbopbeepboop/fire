# CODEGEN_tagged_generator_mixed_type_step1-part1: document the store side of the tagged box

Class: **easy** (this doc lives in `bugs/`, the easy class).

## Parent

`bugs/hard/CODEGEN_tagged_generator_mixed_type_step1.md` (split), which is
step 1 of `docs/tagged_generator_mixed_type-plan.md`. Step 1's acceptance is
"document how the box is stored and read"; that is two halves, and this part
owns the STORE half (and creates the doc file the other part appends to).

## Why this part exists

Step 1 tells a worker to read the tagged-word machinery in
`mojo/backend_gimple/emit_infra.py` and document it. Nothing is broken and no
code changes: the box representation is fully in place (checked 2026-11-11 at
f9c83c88f — `MojoBox` in `runtime/fire_runtime.c`, the per-function tracking
sets, the bind arms in `emit_stmts.py`/`emit_loops.py`). What is missing is
the document itself. Steps 3-5 of the plan (and the already-split step 2
parts) all assume a shared, verified picture of what a tagged word is, where
it lives, and how it is written; today that picture exists only in scattered
comments. This part writes it down, on the store side, as a new `docs/`
reference doc.

## Scope

Create `docs/tagged_generator_mixed_type-box.md` ("The tagged word box: how it
is stored and read", with a header line pointing at
`docs/tagged_generator_mixed_type-plan.md`) and write its STORE sections:

1. **The cell.** `MojoBox` (`runtime/fire_runtime.c` ~1675): a heap cell of
   `uint64_t magic` (`MOJO_BOX_MAGIC`, "MBOX1" — chosen so it can never equal
   a 31-bit class-name-CRC struct type tag), `int64_t bits` (the payload
   word), `char kind` (the discriminator). A boxed value IS the cell's
   address passed as an `int64_t`, and the only way to tell a box from a real
   value is `mojo_is_boxed` (a registered address in the `_reg_box` pointer
   registry; `v < 65536` is never a box). List the kind alphabet with its
   constructor: `'d'` `mojo_box_from_double`, `'p'` `mojo_box_from_str`,
   `'b'` `mojo_box_from_bool`, `'n'` `mojo_box_none`, `'i'` `mojo_id`'s
   pointer-shaped int token (interned per identity in `_id_tab`). The `'s'`
   (bytes) and `'l'` (nested list) kinds ride the list slot's own kind byte
   (see `mojo_list_get_boxed`, which copies the slot kind into the box). The
   full kind/producer/consumer table in
   `bugs/CODEGEN_tagged_generator_mixed_type_step2-part1.md` is already
   verified in the tree — reuse it, do not re-derive it.
2. **The tracking.** Where codegen records "a name's value is a box", all
   per-function in `mojo/backend_gimple/emit_infra.py`: `gen._boxed_vals`
   (a value name is a box), `gen._tagged_word_vals` (subset: a mixed-
   generator word), `gen._dyn_word_vals` / `gen._dyn_word_locals` (a word
   whose kind only the runtime knows), `gen.var_types` (the local's declared
   C type). Cite where they are created/cleared per function (`_reset_func`,
   the clears at ~515) and where they are saved/restored across a
   function-scope swap (the `fs_*` fields, ~906-1037; `_local_bindings_cache`
   at ~132/1116/1200). State the scope rule: a box is a property of the VALUE,
   and a temp name cannot outlive the function that made it.
3. **The stores.** The two places a box is written into a local:
   - the simple-name assignment arm in `mojo/backend_gimple/emit_stmts.py`
     (~1574-1657): the `_keep_tagged_box` arm (a tag-pure name keeps the box:
     local declared `int64_t`, name registered in `_boxed_vals` /
     `_tagged_word_vals` / `_dyn_word_locals`); the mixed-name arm that boxes
     a plain int64 store with `mojo_box_int`; the
     `MIXED_NAME_NON_INT64_REFUSAL` raise (its two trigger halves, and what
     each would do without it — a bare word read as a box segfaults for str,
     prints `1.0`/`0.0` for float); the `mojo_box_word` fallback arm that
     unwraps a boxed value that does not keep the box.
   - the generator for-target arm in `mojo/backend_gimple/emit_loops.py`
     (~3987-4011): a `mixed_slots` generator's loop target is registered the
     same way a `next(g)` bind is (`_boxed_vals` + `_tagged_word_vals` when
     the local is `int64_t`); the tuple-unpack variant (~3994); the
     `_dyn_word_locals` arm for a runtime-kinded int64 slot.
   For each, record the trigger condition in one sentence and the exact
   symbol names, so a later worker can grep them.

No code change. No `tools/suite.py` change. No test change.

## Files

- `docs/tagged_generator_mixed_type-box.md` (new; this part owns the file).

Reads only: `runtime/fire_runtime.c`, `mojo/backend_gimple/emit_infra.py`,
`mojo/backend_gimple/emit_stmts.py`, `mojo/backend_gimple/emit_loops.py`.

## Test

The plan's step 1 test is "existing tests pass". The narrow check:

    python3 tools/memslot.py --gb 8 --label tgbox-doc -- python3 test_gimple_generator_runner.py

Baseline at f9c83c88f (measured 2026-11-11, deterministic across two runs):
`434 passed, 22 failed`. The 22 failures are pre-existing and tracked in
`bugs/mid/SUITE_gimplegenerators.md`; the list is:

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

Do not chase those; this part needs NO NEW failure against that list, and
every `tagged_for_target_*` case passing.

## Acceptance

- `docs/tagged_generator_mixed_type-box.md` exists with the three store
  sections above.
- Every function/symbol named in it exists: spot-check by grepping the cited
  file for each one (`MojoBox`, `MOJO_BOX_MAGIC`, `mojo_is_boxed`,
  `mojo_box_from_double`, `mojo_box_from_str`, `mojo_box_from_bool`,
  `mojo_box_none`, `mojo_id`, `mojo_list_get_boxed`, `_boxed_vals`,
  `_tagged_word_vals`, `_dyn_word_locals`, `_keep_tagged_box`,
  `MIXED_NAME_NON_INT64_REFUSAL`, `mojo_box_int`, `mojo_box_word`).
- Every behavioural claim cites the function/line it was read from, and a
  second reader can confirm it against the code at HEAD.
- The test command above ends with no new failure against the baseline list,
  and every `tagged_for_target_*` case passes.

## Status

Not started. This part has no dependency on part 2; part 2 appends its
sections to the file this part creates.
