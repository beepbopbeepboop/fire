# CODEGEN_tagged_generator_mixed_type_step2-part3: let a mixed tagged name hold a str

Class: **mid** (this doc lives in `bugs/mid/`).

## Parent

`bugs/hard/CODEGEN_tagged_generator_mixed_type_step2.md` (split), step 2 of
`docs/tagged_generator_mixed_type-plan.md`. Part 2 landed the float arm of
this same store site; this part lands the string arm and the string read
consumers that arm exposes. Part 1 pins the runtime box contract.

## Current state (measured 2026-11-10)

The string half of the same defect is refused:

```
def g():
    yield 1
    yield None
    yield 2
def main():
    x = "s"
    for v in g():
        x = v
        print(x)
    x = "t"
    print(x)
main()
```

gives `RuntimeError: 'x': a name bound to a tagged generator word (a yield of
more than one kind) cannot also hold a value of another C type (str or float):
the box cannot carry it; refused`, raised from
`mojo/backend_gimple/emit_stmts.py`'s simple-name assignment arm. The
fixture is `_mixed_str` in `test_gimple_generator_runner.py`'s
`run_tagged_for_target_bind_tests`, currently a
`test_generator_refused("tagged_for_target_copy_into_str_refused", ...)`.

The runtime already has the representation: `mojo_box_from_str(char *)`
allocates a kind-`'p'` box, `mojo_box_word` returns its pointer,
`mojo_repr_boxed` and `mojo_cstr_or_int_str` render the string, and
`mojo_word_cstr_value` hands the pointer to a value consumer. A bare string
pointer is also accepted by those consumers when it is a registered literal or
a live heap block; the box exists so a C++ literal that is neither still
renders as a string. This part makes the codegen store a string into the
mixed name as that box, and keeps the read consumers honest for it.

## Scope

### 1. The store (same block part 2 touched)

In `mojo/backend_gimple/emit_stmts.py`'s simple-name assignment arm:

- When `ginf.tagged_mixed_name(gen, name)` is true and `vtype == 'char *'`,
  replace the refusal with
  `v = gen._call_expr('int64_t', 'mojo_box_from_str', [('char *', v)])`,
  `vtype = 'int64_t'`, `_keep_tagged_box = True`.
- Follow every rule in part 2's "Do not re-box the box": never let the fresh
  box reach the `mojo_box_int` / `mojo_box_word` arms. `_keep_tagged_box`
  set in the same block is what skips them, and the existing
  `if _keep_tagged_box:` arm then declares the local `int64_t` and registers
  it in `_boxed_vals` / `_tagged_word_vals` / `_dyn_word_locals`.
- Lift the refusal for exactly `char *`. Do **not** lift it for other pointer
  types (`MojoList *`, `MojoDict *`, `MojoStr *`, struct pointers): the box's
  runtime constructors at this site are `mojo_box_from_str` and
  `mojo_box_from_double`, and a container slot in a tagged name is a
  different representation question. If a real program needs one, it is its
  own bug doc, not an extra arm here.

### 2. The read consumers the string case exposes

The tagged-word consumers were built for `str` yields, so most reads already
work once the local is registered (the local's `_tagged_word_vals` membership
is what makes `print`, `==`, and `+` dispatch by kind). Verify each of these;
fix only the ones that actually misbehave, and write the test that proves it:

- **`print(x)` / f-string `f"<{x}>"`**: `mojo_cstr_or_int_str` has a
  `_box_spelled_by_kind` arm and calls `mojo_repr_boxed` for a kind-`'p'`
  box, so this should already work.
- **`x == "t"`**: the equality arm in `emit_exprs.py`
  (`_ident_ops`, the `lv in _boxed_vals` block near "A TAGGED word ...
  beside a str operand") uses `mojo_box_word`, which returns the pointer for
  a kind-`'p'` box, so this should already work.
- **`x + "!"`**: the same block deliberately keeps a tagged word boxed when
  the other operand is `char *` and the operator is `+`, and the
  concatenation lowering renders it by kind. Verify it; this is the shape
  that used to become `double + char *` in gcc.
- **`len(x)`**: this one is expected to be broken.
  `_lower_builtin_len` (`mojo/backend_gimple/emit_calls.py`) reaches
  `ginf._len_of_boxed` (`emit_infra.py`) for an `int64_t` slot, and that
  helper's string test is `mojo_boxed_is_str` on the RAW word.
  `mojo_boxed_is_str` deliberately answers false for every box
  (`runtime/fire_runtime.c`: it excludes the box registry so a boxed float
  is not taken as a string), so a kind-`'p'` box falls through to
  `mojo_list_len` and reads the box header as a list. Fix it with the
  existing accessor: test `mojo_boxed_is_str(mojo_box_word(word))` (the
  float box survives `mojo_box_word` unchanged and is rejected; a `'p'` box
  becomes its pointer and is accepted; a non-box is unchanged), or add a
  narrow kind-aware runtime predicate if that reads better. Do not make
  `mojo_boxed_is_str` itself accept boxes — its own comment and the float
  case depend on it rejecting them.
- **Methods on the receiver (`x.upper()`, `x.startswith(...)`)**: this
  codegen has no run-time method dispatch on a boxed word, and the local's
  declared C type is `int64_t`, so a string method on it is a separate gap.
  Keep it out of this part's acceptance. If a real program needs it, file it
  as its own bug doc under `bugs/` rather than widening this arm; do not
  silently compile it to a wrong method.

### Adjacent gap to record, not fix here

`emit_calls.py`'s `_tagged_word_value` (the `next(it, default)` default on a
tagged generator) explicitly stores a string as its raw **pointer**, not as
`mojo_box_from_str`. That is right for a registered literal (and is why the
existing tests pass), but a C++-path literal is not registered, and would
render as its address. It is the same representation question one call site
over; do not change it in this part unless the test you add can actually
distinguish a box from a registered literal. Note it in Status if you find a
reproducer.

## Files

- `mojo/backend_gimple/emit_stmts.py` — the store arm.
- `mojo/backend_gimple/emit_infra.py` (and/or `runtime/fire_runtime.[ch]`) —
  only if `len` needs the box-aware branch described above.
- `test_gimple_generator_runner.py` — `run_tagged_for_target_bind_tests`.

## Test

In `run_tagged_for_target_bind_tests`, replace
`tagged_for_target_copy_into_str_refused` and `_mixed_str` with a CPython
oracle (same helper as part 2, so the expected output is measured at test
time):

```
def g():
    yield 1
    yield None
    yield 2
def main():
    x = "s"
    print(x)
    for v in g():
        x = v
        print(x)
        print(x == None)
    x = "t"
    print(x)
    print(x + "!")
    print(len(x))
    print(f"<{x}>")
main()
```

CPython output: `s`, `1`, `False`, `None`, `True`, `2`, `False`, `t`, `t!`,
`1`, `<t>`.

A second case should cover the string-after-tagged direction
(`x = 0; for v in g(): x = v; ...; x = "t"`) so the first-declaration order is
not the only one exercised. Keep `tagged_for_target_copy_into_float` from
part 2 green — the two arms share the same block.

## Acceptance

```
python3 tools/memslot.py --gb 8 --label gemgen-str -- python3 test_gimple_generator_runner.py
```

The whole file is the registered `gimplegenerators` job and the narrowest
thing that covers this change. It must end with no failures; at minimum the
new `tagged_for_target_*_str*` cases and the part-2 float cases must `PASS`,
and no other case may regress. If `len` needs the `_len_of_boxed` change, the
same run covers it; do not add a new test file or a `tools/suite.py`
registration for it.

## Status

Not started. Depends on part 2 (same store block); if part 2 has not landed,
land its `mojo_box_from_double` arm in the same edit and say so in the commit,
rather than leaving the block with two divergent structures.
