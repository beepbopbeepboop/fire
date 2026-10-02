# CODEGEN: iterating a value that is not a container at all answers `[]` (was SIGSEGV)

Found 2026-10-01 while fixing `bugs/CODEGEN_list_of_pairs_iterated_as_dict.md`
(removed with that fix). That fix routed `list(<ambiguous handle>)` through
`_materialize_as_list`, whose opaque arm ended in an unguarded
`(MojoList *)value` — so making that arm fail CLOSED was a precondition of the
fix, not an extra. The crash is gone; the wrong answer is not.

## Status: OPEN, and it is the honest half of a deliberate simplification.**

## What it does now

```python
def main():
    print(list(5))
    print(list(12345678))
main()
```

CPython: `TypeError: 'int' object is not iterable`, exit 1.
Compiled: `[]` and `[]`, exit 0.

Same shape on every other `_materialize_as_list` consumer — `all(5)`,
`any(12345678)`, `enumerate(7)`, `','.join(3)`, `b''.join(9)` — because they
share the chokepoint.

## What it did before

`SIGSEGV`. Measured on the intermediate tree (the fix applied, the fail-closed
arm not yet): `list(12345678)` exited `-11` with no output, because
`mojo_list_len((MojoList *)12345678)` read a length out of the middle of
nothing.

## Why `[]` and not a refusal

Two reasons, and both are about not making things worse:

1. A refusal is a compile-time decision, and the fact that decides it is a
   RUNTIME fact. `_materialize_as_list` is called from inside generated C
   branches (the R5 dispatch itself), so there is nowhere to raise. The
   available honest options are "ask the runtime" (done — `mojo_is_registered_
   list`/`_dict`/`_set`) and "produce nothing" (what the fallback does).
2. `[]` is what every consumer of this chokepoint already answered on the
   pre-R1 path, and it is what the compiled path still answers for
   `list(<a handle that is not a container>)` reached by any other route. A
   loud refusal here alone would split one behaviour into two for no gain.

## Why it is still worth doing

`[]` is a silent wrong answer: a program's loop body never runs and nothing
says so. `bugs/CODEGEN_all_any_dict_set_miscompile.md` (gone, closed by R5)
recorded the same shape for a different value class, and the project's own
rule for it — see `bugs/PERF_memory_over_4gb_is_a_bug.md`'s neighbourhood
wording in `CODEGEN_list_element_read_defaults_to_str_across_a_call.md` — is
"an uncertain guess must resolve to *ask the runtime*, never to *dereference
it*". The dereference is gone; the honest failure is not.

## Next step

The runtime CAN raise, and there is already a channel for it: every container
op in `runtime/fire_runtime.c` funnels a bad receiver through a helper
(`mojo_require_mutable_list` is the shape to copy), and the compiled runtime
turns a pending exception into the `Unhandled exception: <Type>` message plus
a non-zero exit that CPython's own `TypeError` produces.

So the change is:

1. a runtime entry point for the ambiguous-iterate case — something like
   `mojo_iter_type_error(int64_t v, const char *what)` that raises
   `TypeError: '<v>' object is not iterable` and returns a fresh empty list so
   the generated branch still has a value;
2. calling it from `_materialize_as_list`'s `bb_none` arm in place of the bare
   `mojo_list_new ()`.

Then the six consumers answer identically for free, and the arm stops being a
place where a program's loop body is silently skipped. Verify with
`test_gimple.py` (the `list`/`set`/`tuple` ctor rows) plus a new row per
consumer, since they are separate codegen sites even though they share the
chokepoint.