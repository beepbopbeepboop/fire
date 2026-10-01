# A frame refusal raised from `_prepare_functions` preempts the import diagnosis, so 6 files are reported as `codegen` gaps in themselves

**Status: OPEN, not fixed, and deliberately not fixed here — the fix moves every
frame refusal, which changes the class of files that belong to five other rows of
`bugs/FORMAL_sweep_work_map_2026-09-30.md`. The measurement is here so the
integrator can sequence it rather than re-derive it.**

Found while measuring the ceiling of the map's row 8
(`bugs/FORMAL_callee_no_def_ceiling_zero.md`), where the answer turned on it.

## The defect

`formal/build.py`'s `compile_formal` runs, in this order:

    _imported_structs → _prepare_functions → load_dylib_manifests
                       (frame refusals ↑)      → _resolve_imports (host-import /
                                                    module → dylib)

Every frame refusal — the hand-off family, the return family, the container and
field families — is raised from `_prepare_functions`, which is BEFORE the imports
are resolved. So for a file that both trips a frame clause and imports something,
the diagnostic the reader gets is the frame one, and it is a `codegen` class: a
gap in the backend, in this file. The sweep's own denominators then count it as
answerable-in-principle work.

The codebase already knows this and has fixed it twice, in the two late checks
`compile_formal`'s own comment names — `check_frame_field_blob_premises` and
`check_construction_shapes` were moved OUT of `_prepare_functions` for exactly
this reason:

> 14 files of this repository that import a host module were being reported as
> codegen gaps because of it.

The frame refusals were left inside, so they still do it.

## Measured

**The 12 files of row 8**, each re-built on a cold CAS with that ONE refusal
suppressed in-process (`bugs/FORMAL_callee_no_def_ceiling_zero.md` §1 for the
harness):

| file | what it reports instead |
|---|---|
| `std/base64/base64.mojo` | `imports 'std.memory', which cannot be built either: builtin_slice.mojo: Slice___eq__ …` → **`codegen/dependency`** |
| `std/collections/_conditional.mojo` | `imports 'std.builtin.device_passable' … function.mojo: __mlir_attr[…]` → **`codegen/dependency`** |
| `std/ffi/unsafe_union.mojo` | `imports 'std.builtin.rebind' … builtin_slice.mojo …` → **`codegen/dependency`** |
| `formal/build.py` | `imports 'copy', which is a host module (CPython standard library)` → **`not-answerable/host-import`** |
| `scripts/repro_ftplib_isolated.py` | `imports 'subprocess', which is a host module` → **`not-answerable/host-import`** |
| `test_formal_call_proof_gen.py` | `imports 'ast', which is a host module` → **`not-answerable/host-import`** |

**Six of twelve change class**, and none of the six becomes answerable — which is
the direction of drift that flatters a number, so it must be reported as a class
move and not as a loss. This is the same warning the two earlier fixes carry.

**How much is left**: over the repo, `std/` and `test/`, 80 in-scope files are
refused by a frame clause AND import at least one module — so 80 files are
candidates for this, of which 12 were measured here and 68 are not. The 68 need
one build each to size honestly; the defect is certain for them (the frame
refusal wins the race) and the size of the class move is not.

## The exact next step

1. Move the frame refusals the way the two late checks were moved: collect them
   in `_prepare_functions` (where the analysis is) and raise them from
   `compile_formal` AFTER `_resolve_imports` has had its say —
   `check_frame_subscript_escapes` is already deferred this way and is the
   precedent (`_defer_subscript_escape`).
2. **Sequence it against the work map.** This is the part that is not this row's
   to decide: the classes it moves are the map's rows 4, 5, 7, 8, 9 and 13 —
   `formal-frame-by-value` (`construct:frame-address-as-value`),
   `formal-frame-escape` (`construct:frame-address-escapes`),
   `formal-receiver-position` (`construct:receiver-position-family`) and this
   row. Re-running the sweep afterwards re-numbers six rows at once, so it wants
   the same cold-CAS gate the whole map does
   (`bugs/FORMAL_sweep_cache_ignores_imports.md`), and the affected workers should
   be told before it lands rather than after.
3. Pin it: a case in `test_formal_run.py` that imports a host module AND trips a
   frame clause, asserting the **import** diagnosis wins on both architectures.
   The three `refuse:` cases this file already has for cross-module hand-offs are
   the shape; nothing asserts the ORDER today, which is why two rounds of late
   checks had to be moved by hand.