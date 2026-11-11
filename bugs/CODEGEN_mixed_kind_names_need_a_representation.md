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

Effect today: `mojo/middle/coro.py` cannot compile, and the dict-slot regression test (case 2) is refused by design.

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

## Status
Open. Not started. The design choice (1 vs 2 vs 3) is the owner's.

## Done when
A program with a float and a str in one name, and a program with a container and a number passed to one parameter,
both compile and print the CPython answer; `mojo/middle/coro.py` compiles; the fire.ci build is green. Then delete this
doc in the same commit as the change that closes it.
