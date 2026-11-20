# Bootstrap dump chain part 2: an owned-kinds list survives extend

## Goal

Make the runtime's kinds grow path safe for a list whose per-slot kinds live in
a header-prefixed owned block. A list built by `_list_word_push` (`owned == 2`)
keeps its kinds in a malloc'd block whose 8-byte header holds the capacity, so
`_KindRow.kinds` is an interior pointer (`base + 8`). `_kinds_append` — the grow
path `mojo_list_extend` uses — used to call `realloc()` on that interior
pointer; macOS aborts the process:

    malloc: *** error for object 0x...: pointer being freed was not allocated
    _realloc <- mojo_list_extend <- ..._gmi_all_stmts_nonfunc

That abort is what killed the stage2 binary while dumping a plain bootstrap
input (measured on the 2026-11-15 stage2 binary; the Python reference exits 0).
`mojo/middle/closures.py::_gmi_all_stmts_nonfunc` appends each statement to a
list and then `extend`s it with each recursive call's list, so the compiled
compiler reaches exactly this path.

Grow an `owned == 2` buffer through its capacity header (and free the old
block) instead of `realloc()`ing the interior pointer; keep one implementation
of the fix. Master already carries it in `59bbf58de` (and it is an ancestor of
this tree); this part is the pin that keeps it, and the port if a tree does not
have it.

## Acceptance

- Extending a list whose kinds came from `append_word`, and extending a typed
  list into one, each compile through `compile_to_gimple`, link against
  `runtime/fire_runtime.c`, run, and print CPython's stdout with exit 0.
- `runtime/fire_runtime.c` has one kinds-grow implementation: an `owned == 2`
  row is grown via its capacity header, never `realloc()`ed as a plain pointer.
- No parallel `_kinds_make_private`-style copy helper is introduced.

## Done when

File: `test_regress_list_extend_owned_kinds.py`

Command:
`python3 tools/memslot.py --gb 8 --label kinds-extend -- python3 test_regress_list_extend_owned_kinds.py`

It takes ~9 s and 0.1 GB and prints `2 passed, 0 failed`. Without the fix both
cases exit -6 with empty stdout (the malloc abort).
