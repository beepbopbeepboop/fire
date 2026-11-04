# Plan: LinkedList reflection and struct elements

Source bug: bugs/hard/CODEGEN_linked_list_reflection_and_struct_elements.md

## Decomposition

Step 1 — Stub: LinkedList.__hash__
Step 2 — Stub: IteratorOwnedType alias
Step 3 — Stub: write_sequence_to / _write_self_to / FormatStruct / TypeNames / params / fields
Step 4 — Struct-valued elements: register imported non-generic struct before materialized methods
Step 5 — Lift scalar-argument gate in _positional_bracket_ctor_args
Step 6 — End-to-end build-and-run printing 1
