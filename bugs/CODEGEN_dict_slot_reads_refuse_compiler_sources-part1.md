# Printing a container out of a container/scalar mixed name prints its repr, not its address (part 1)

Part 1 of 3 of `bugs/hard/CODEGEN_dict_slot_reads_refuse_compiler_sources.md`.
Class: easy — one print arm has to consult a set that already exists, using a
repr helper that already exists.

## Measured (2026-11-14, this tree)

`test_mixed_kind_name_representation.py` is 17/20, and the three failures are
one shape: a name that held a CONTAINER and then a SCALAR (`mixed_value_locals`)
prints the container's raw word as a decimal address.

    $ python3 test_mixed_kind_name_representation.py
    FAIL  list_then_int_print: CPython '[1, 2]\n3\n' (rc 0), compiled '4380774832\n3\n' (rc 0)
    FAIL  str_then_list_print: CPython 's\n[1, 2]\n' (rc 0), compiled 's\n4372320688\n' (rc 0)
    FAIL  list_then_float_and_str_and_bool: CPython '1.5\nt\nTrue\n[3]\n' (rc 0), compiled '1.5\nt\nTrue\n4376386560\n' (rc 0)
    3 of 20 cases FAILED

Measured by hand, the same shape for the other container kinds:

    x = {"k": 1}; print(x); x = 3; print(x)   ->  '4381403456\n3\n'   (CPython "{'k': 1}\n3\n")
    x = {1, 2};   print(x); x = "s"; print(x) ->  '4368492864\ns\n'   (CPython "{1, 2}\ns\n")

Two controls already pass, so this is the direct-operand arm only, not the box:
`print(str(x))` on the same name prints `[1, 2]`, and a bytes value prints
`b'ab'` correctly.

## Why

`emit_infra.mixed_value_locals` declares such a name `int64_t` and stores a
container as its bare word (see `box_mixed_store`, `emit_infra.py:4466`).
`_gen_print` (`emit_infra.py:8339`) dispatches an `int64_t` operand by its
static/`_actual_types` type; for this name neither answers "container" for the
store that is live, so the word falls through to the integer format and is
printed as a decimal. `_stringify` (`emit_infra.py:5800`) already has exactly
this arm for the same set and calls `_repr_boxed_container`
(`emit_infra.py:7755`), which dispatches on the runtime list/dict/set/str
registries. `print` does not use it.

## Goal

`print` of a container held in a `mixed_value_locals` name renders the value,
byte-identically to CPython, for every container kind the name can hold — and
keeps printing ints, floats, strs and bools exactly as it does today.

## Acceptance

- `x = [1, 2]; print(x); x = 3; print(x)` prints `[1, 2]\n3\n`.
- The same for a `dict` and a `set` (`{'k': 1}`, `{1, 2}`), and for the
  ordering where the container store comes last.
- `x = [1, 2]; print(str(x))` is unchanged (`[1, 2]`).
- `bytes`, `int`, `float`, `str` and `bool` values out of such a name are
  unchanged (`b'ab'`, `3`, `1.5`, `s`, `True`).
- No address decimal appears, and the program exits 0.
- The repr buffer is released on the paths that own it and the borrowed `str`
  arm of `_repr_boxed_container` is NOT freed (that helper's `str` arm is the
  value itself, not a `strdup`); use its existing ownership split, do not add a
  second repr dispatcher.
- `test_dict_slot_read_regression.py` and `test_tagged_mixed_readsites.py`
  stay green.

## Done when

File: `test_mixed_kind_name_representation.py` (repo root).

Command: `python3 test_mixed_kind_name_representation.py`

It is red today (3 of 20, the output above) and must reach 20/20.

## Where to start

- `mojo/backend_gimple/emit_infra.py:8339` — `_gen_print`'s operand loop; the
  `int`/`int64_t` arm is where the mixed-value ident read has to branch.
- `mojo/backend_gimple/emit_infra.py:5817-5830` — `_stringify`'s
  `mixed_value_locals` arm, the same decision already made for `str()`.
- `mojo/backend_gimple/emit_infra.py:7755` — `_repr_boxed_container`: it
  already dispatches list/dict/set/str and falls back to `mojo_repr_boxed`.
- `mojo/backend_gimple/emit_infra.py:8299` — `_own_repr`/`_owned_reprs`, the
  print-path release ledger.
