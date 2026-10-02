# PERF: every printed container leaks its intermediate `mojo_str_cat` buffers (~500 B per `print` of an 8-element list)

## Status (2026-10-02 — the leak is FIXED; one bounded remainder is named below)

Found 2026-10-01 while fixing `bugs/CODEGEN_tuple_dict_key_hashed_by_address.md`
(deleted with that fix): the fix put a dict KEY's renderer on the same repr
walkers, so what was a slow leak on a debug print became a per-lookup leak, and
fixing it named the rest of the family. Standard:
`bugs/PERF_memory_over_4gb_is_a_bug.md`.

## What is fixed

Both places the report named, in one change and in ONE implementation of the
rule rather than two:

1. **`mojo_str_cat_free` is now a public runtime entry point** (it was the
   file-local `_cat_free`), and declared in `fire_runtime.h`. It is public
   precisely so the emitted walkers can call it: emitting a second copy into
   the preamble would have been two implementations of one rule in two
   languages, which is what this doc's own "why the choice is worth making
   deliberately" paragraph was about. `test_runtime_header_scan.py`'s ledger
   carries the two new names.
2. **Every walker named in (1) below releases its chain and its owned
   per-slot strings**: `mojo_repr_list_ints`, `_doubles`, `_bools`,
   `_bytes`, `_intlists`, `_slotkinds` and `_mojo_repr_pairlist` in
   `runtime/fire_runtime.c`; `_mojo_repr_list`, `_mojo_repr_pair`,
   `_mojo_repr_dict`, `_mojo_repr_set` and the per-struct `_mojo_repr_{sn}`
   dumps in `mojo/backend_gimple/module_gen.py`.
3. **The two SHARED returns were normalised rather than free()-ed.**
   `mojo_repr_obj` (a shared static) and `mojo_repr_bool` (literals) stay
   exactly as they are — a `free()` of either is a crash, and both have
   callers in other workers' write sets — so the walkers that must not free
   them say so in a comment, and the emitted `_mojo_generic_elem_repr` (whose
   `"None"` and `mojo_repr_obj` returns were the reason its callers could not
   free their per-slot strings at all) now `strdup`s those two answers, the
   same remedy `_key_slot_str` already applies on the dict-key path.

Measured on `gimple_printed_container_does_not_grow`
(`test_gimple_runner.py`), which prints SEVEN container shapes 60 000 times —
one per walker — under `MallocScribble`, so a `free()` of a shared buffer is a
wrong answer rather than silent heap corruption:

| tree | peak RSS |
|---|---|
| HEAD (`bc17a62b`, before this change) | **87.2 MB** |
| this change | **12.8 MB** |

and the text of every walker is pinned separately by
`gimple_container_repr_text_is_unchanged`, because a repr that printed the
wrong thing and leaked nothing would pass the memory case.

## What is NOT fixed, named precisely

* **The per-FIELD strings of a struct dump.** `_mojo_repr_{sn}`'s cat chain now
  releases its left operand (the O(F^2) part), but each field's `val_expr` is
  left alone: those expressions are one of a dozen shapes whose ownership
  differs (a `mojo_repr_*` helper owns its return; a `"True"`/`"None"` literal
  does not), and a wrong `free()` there is a crash rather than a leak. It
  wants the same treatment the dict walker just got: an explicit owned/not-owned
  answer per field shape, threaded through `part_exprs`.
* **`_mojo_dispatch_repr`.** Its result is freed by nobody, so there is nothing
  to release today; it would need an owner before it could be freed.

Both are strictly smaller than what is fixed (one string per field / per call,
against one buffer per element of every container printed) and both are noted
in the comments where the code is.

## What was run (the original report, kept)

```console
$ python3 -c "import test_gimple_runner as T; T.test_gimple_bounded_memory(
      'probe', open('prog.py').read(), <stdout>, 40)"
peak RSS 99.7 MB (limit 40)
```

`prog.py` is `xs = [1,2,3,4,5,6,7,8]` and `for i in range(200000): print(xs)` —
200 000 prints of an 8-element list, so ~500 B per print. The same program
with a string key instead of a tuple key peaked at 10.8 MB, which is what a
non-leaking loop of that shape costs; the compiler-emitted `_mojo_repr_list`
and the runtime's `mojo_repr_list_*` family are both reached from `print`.

## Mechanism

`mojo_str_cat(a, b)` allocates a NEW buffer and deliberately leaves both
arguments alone (`runtime/fire_runtime.c`). Every repr walker is a chain of it:

```c
    char *_buf = strdup("[");
    for (...) {
        if (_i > 0) _buf = mojo_str_cat(_buf, ", ");   /* the old _buf is leaked */
        _buf = mojo_str_cat(_buf, mojo_repr_int(...));  /* and so is this slot's */
    }
    return mojo_str_cat(_buf, "]");                     /* and this _buf */
```

An N-element list leaks N+1 buffers per repr, each sized to the text so far.

## A SIGSEGV found on the way, and fixed

`print({"c": 3.5})` — a dict literal with ONE float value — was a SIGSEGV on
`bc17a62b` (measured on a pristine `git archive bc17a62b` extraction, so it is
not a change in flight). The emitted `_mojo_repr_dict` reads a `kind == 2` slot
back as a string and a `kind == 3` slot as a bool, and sent everything else to
`_mojo_generic_elem_repr`, which treats `val > 65536` as a pointer and
dereferences it through `mojo_read_type_tag_safe`. A double's IEEE-754 bits are
exactly such a word — 3.5 is `0x400C000000000000` — and that predicate's guard
only rejects words below 2 GiB. Fixed with the branch the runtime's
`mojo_repr_list_kinds` already has for a float list slot, and one new accessor
(`mojo_dict_slot_double`, the double twin of `mojo_dict_slot_key`, because the
emitted repr walks slots by INDEX and `mojo_dict_get_double` takes a KEY).
`gimple_container_repr_text_is_unchanged` pins it.

A second, unrelated pre-existing crash sits on the same shape and is NOT fixed
here: `{"d": True}` does not COMPILE at all (five emitter sites still call the
deleted `mojo_mark_dict_bool_values`) —
`bugs/COMPILE_FAIL_dict_literal_with_a_bool_value_emits_a_deleted_runtime_entry_point.md`.

## Original next step, for the record

Do (2) first, since it is the copy every generated program carries, then (1).
The "byte-identical generated C" standard in the last section of the original
version of this doc does not apply to a fix that changes the emitted text by
construction; what it asks for — same printed text — is pinned by
`gimple_container_repr_text_is_unchanged` instead.
