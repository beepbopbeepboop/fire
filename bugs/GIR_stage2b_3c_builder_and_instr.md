# GIR stages 2b and 3c: the IR builder and `Instr` statements

Plan source: `doc/GIR.md`, Stage 2b (`mojo/ir/build.py`) and Stage 3c (`gen.body_lines` holds `Instr`).

## Measured now

- `gen._emit(` text calls: 270 (ratchet `gen._emit( text`). Each one is a statement written as a string.
- Constant assignments already moved to `gen._cast_into` (stage 2b step, 27 sites).

## Next step

1. Stage 2b: add `mojo/ir/build.py` with the builder calls the plan lists (`call`, `cast(value, type)`,
   and the rest of the list in `doc/GIR.md`). Use it for one statement family at a time; check each
   family byte-identical on `tools/pydiff_corpus`.
2. Stage 3c: change `gen.body_lines` to hold `Instr` objects, with `gen._emit` as a thin adapter
   until the last caller moves.

## Acceptance

- The `gen._emit( text` ratchet only shrinks.
- Generated C byte-identical per family.
