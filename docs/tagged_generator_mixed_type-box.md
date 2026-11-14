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

## 4. The read side

### 4a. The binder census: `_local_bindings` (`emit_infra.py` ~3614-3687)

Returns every binding of a name in THIS function's body: the `value` for a
plain `name = <value>`, and `None` for every other binder (an augmented or
multi-assign, a for or with target, a comprehension generator, and any other
node whose `.name` is the name). An ambiguous form counts as a binder, so an
over-count only refuses an optimisation. Computed from `gen._cur_func_body` and
cached in `gen._local_bindings_cache` under `(id(body), name)`; the body id is
in the key because `module_gen` swaps the body without going through
`_reset_func`.

### 4b. The per-name rules (`emit_infra.py`)

Each takes `(gen, name)` and answers False for a parameter or an unbound name.

- `tagged_next_bind_name` (~3688). True: every binding is `name = next(g)` for
  one generator local `g` bound exactly once, or a copy of another name that is
  itself such a name (`_seen` breaks copy cycles). False: any other binder, two
  different generators, or a `g` that is a parameter or bound more than once.
  Safe because every store into the name is the same tagged word, so no store
  can hand a consumer a bare word where it expects a box.
- `tagged_for_target_name` (~3824). True: every binding is a `for name in <tagged
  generator>` target, and the count of such loops equals the count of binders.
  False: a plain assignment, a tuple target (`for_target_is_tuple`), or a loop
  whose iterable fails `_tagged_generator_iterable`. Safe because a rebinding
  anywhere makes the loop count differ from the binder count.
- `tagged_mixed_name` (~3758). True: the name is bound to a tagged word somewhere
  AND to a plain value elsewhere, and is not a `tagged_next_bind_name`. Exits
  early, with no body walk, when no `_generator_api` entry has `mixed_slots`.
  Safe because a mixed name's every store is boxed (see 3a), so the local is a
  box-holding local with no bare-word store.
- `tagged_recv_name` (~3857). True: every binding is `name = yield`
  (`__mojo_coro_yield_i`). False: any other binder. Safe because the resume word
  is either the None box or a bare integer, and a consumer renders both
  correctly (`mojo_repr_boxed`).
- `_tagged_generator_iterable` (~3798). True: the for-iterable is a call of a
  generator whose `_generator_api` entry has `mixed_slots` and
  `value_ctype == 'int64_t'`, either written directly or through a local bound
  exactly once to such a call. `_generator_api` is built before any body is
  emitted, so the answer does not depend on lowering order.

### 4c. The operand rule: `_is_tagged_box_operand` (`emit_exprs.py` ~1249)

An already-lowered operand `val` is a tagged box iff `val` is in `_boxed_vals`
AND (`val` is in `_tagged_word_vals`, or the AST node is an `IdentExpr` whose
name satisfies `tagged_for_target_name`).

The split doc asked to record why a for-target word is in `_boxed_vals` but not
in `_tagged_word_vals`. Read at HEAD, that premise does not hold in general:

- the single-target arm of `emit_loops.py` (~4005-4006) adds the target to
  BOTH `_boxed_vals` and `_tagged_word_vals`, so the first test in the rule
  already answers True for it;
- the tuple-unpack arm (~3988-3997) adds to `_boxed_vals` only, and
  `tagged_for_target_name` skips tuple targets, so a tuple-unpacked word is
  covered by neither test. This is an open gap in the operand rule, not a
  documented design.
- a copy of a for-target (`_for_copy` in `emit_stmts.py`) enters
  `_tagged_word_vals` through `_keep_tagged_box`.

### 4d. The per-kind readers (`runtime/fire_runtime.c`)

- `mojo_box_int` (~1983): unwraps. A `'d'` box is truncated toward zero
  (`(int64_t)mojo_box_double`), so a fresh double box must never be passed
  through it. Any other box returns its `bits`; a non-box returns itself.
- `mojo_box_word` (~1993): unwraps every box EXCEPT a `'d'` box, which is kept.
  A non-box returns itself.
- `mojo_box_double` (~1800): a `'d'` box returns its double bits; a non-double
  box returns its `bits` as a double; a non-box returns `(double)v`.
- `mojo_word_is_none` (~2026): true for a `'n'` box, and for a `'p'` or `'s'` box
  whose `bits` is 0 (a NULL slot). A bare word is never None.
- `mojo_unbox_plain` (~2012): a `'n'` box becomes 0, a `'b'` box its 0/1, a `'p'`
  or `'s'` box its pointer. Every other word, including a `'d'` box, is kept.
  Omitted from the split doc; it is what a tuple-unpack target uses.
- `mojo_repr_boxed` (~2143): the str() spelling by kind (`'d'` float, `'p'` the
  string itself, `'s'` bytes repr, `'l'` list repr, `'n'` None, `'b'` True/False,
  otherwise the integer). Its non-box arm: a registered string
  (`mojo_boxed_is_str`), a regex match, or the plain integer. Uses str() not
  repr() semantics.
- `mojo_cstr_or_int_str` (~14515): the value-side str spelling of a word. A box
  is spelled by kind (a `'d'` box as a float, others via `mojo_repr_boxed`), a
  registered str is returned as-is, bytes and regex matches are spelled, a
  registered list is keyed, and an integer is its decimal. Returns a fresh
  heap string.
- `mojo_word_cstr_value` (~14550): the value sibling, for a callee that
  dispatches on the word's kind. A `'p'` or `'s'` box, or a plain string or
  bytes word, returns the address borrowed, without quoting. Other boxes and
  integers follow `mojo_cstr_or_int_str`.
- `mojo_float_arith_select` (~1962) and `mojo_float_cmp_select` (~1972): if
  either operand is a `'d'` box, return a fresh double box holding the double
  result (arithmetic) or the double comparison (compare); otherwise the integer
  answer. The codegen treats the arithmetic result as a tagged word.

### 4e. The arithmetic dispatch (`emit_exprs.py`)

- `_tagged_unary_neg` (~1263): negation of a tagged operand.
- `_tagged_arith_select` (~4122): for `+ - * ...` beside an integer. It computes
  both the integer answer and the double answer, and `mojo_float_arith_select`
  picks by the operand's kind. A double operand is not handled here.
- `_tagged_cmp_select` (~4160): for `< <= > >=` beside an integer, the same shape
  with `mojo_float_cmp_select`.

### 4f. The refusal as the read path sees it

`MIXED_NAME_NON_INT64_REFUSAL` (`emit_infra.py` ~3744) and its two trigger halves
(`emit_stmts.py` ~1612-1617) refuse a tagged word stored into a non-int name,
and a non-int64 value stored into a mixed name. Without the refusal, a str
would be read as a box (a bare pointer read as a box, a segfault) and a float's
bits would sit in an int64 box slot (printing `1.0` or `0.0`). The box already
has the `'p'` and `'d'` kinds, so the step 2 parts lift the refusal by
handling those kinds in the store, not by changing the box format.

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
