# DIAGNOSTICS mojoc imports, part 2 — part 3: conformance error against an imported struct with an implicit default

Part 3 of 3 of `bugs/hard/DIAGNOSTICS_mojoc_imports-part2.md`. Depends on
the precompiled signature artifact/reader (part 1, landed) and
`DIAGNOSTICS_mojoc_imports-part2-part2.md` (synthetic signature printer).

## Class
mid. It wires an existing conformance check to the imported signature and
emits the three-line diagnostic. The check itself exists for source structs
(`elaborate.py::check_conformance`, `fire_compiler.py` conformance paths), so
this is plumbing plus one new case, not a new checker.

## Current state

Modular's expectation for `import_mojoc_implicit_default_param.mojo`, with the
source deleted and `Container` imported from `pkg.mojoc`:

    # CHECK: error: 'Container' parameter 'T' has 'Marked' type, but value has type 'AnyStruct[NotMarked]'
    # CHECK: note: 'Container' declared here
    # CHECK: struct Container[T: Marked, W: Wrapper = __init__(Int(4))]
    # CHECK-SAME: # note - synthetic signature

The user program is `_ = Container[NotMarked]()` where `NotMarked` does not
conform to `Marked`. In this repo the check for a bracket parameter against an
imported struct's trait does not see the imported record, so nothing is
reported (or the importer fails differently; measure this first, see below).

## Goal

When a call or instantiation names an imported struct, run the same
trait-conformance check the source path runs against the part-1 record, and on
failure emit:

1. `error: '<Struct>' parameter '<P>' has '<Trait>' type, but value has type '<Actual>'`
2. `note: '<Struct>' declared here` at the import's location
3. the part-2 rendered signature as the note's detail line

Use the existing diagnostic emitter. Do not add a second message formatter.

## Measure first (the worker's first step)

Before changing code, write the three-file fixture from the modular test
(a `Marked` trait, a `Wrapper` with an `__init__(out self, Int)`, and
`Container[T: Marked, W: Wrapper = Wrapper(4)]`) under `.tmp/`, run
`python3 fire.py precompile` (or the part-1 command) and `python3 fire.py build`
on a `main.mojo` that instantiates `Container[NotMarked]`, and record the exact
current output. Put the measured output in this doc's Status before editing.
Compiling one small main is light; do not run a whole-closure compile (wrap in
`python3 tools/memslot.py --gb 8 --label mojoc-p2p3 -- ...`).

## Acceptance

The fixture from the modular test produces the three diagnostic lines above
with exit status non-zero, and the `CHECK-SAME` line matches the part-2 render.

## Done when

File: `test_mojoc_implicit_default_conformance.py` (repo root; created by this
part). It runs the in-process path only (parse + elaborate on the artifact
record; no native build), and asserts the error and note strings above with the
synthetic signature line.

Command: `python3 test_mojoc_implicit_default_conformance.py`

## Status

- **Open.** Blocked on parts 1 and 2. The measurement step above has not been
  run yet.
