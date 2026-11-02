# FORMAL_the_last_dylib_exports_exportEnd_includes_the_interned_strings: the
# last export of every dylib gets an unprovable `_semantics_total`, and the two
# `test_formal_dylib.py` hole-count rows are red for it

**Area:** FORMAL (the dylib contract emitter) —
`formal/arm64_proof_gen.py::_export_extent` / `_dylib_total_proof` and
`lib/ProofLib.lean`'s `DylibExport.exportEnd` (the fold the two must agree on).
**Status: NEW 2026-10-13 (`work/formal404-docs`), measured, NOT fixed — the fix
is a library/export-table change that invalidates every cached proof.** Filed
while resolving `bugs/formal/FORMAL_a_conditional_value_in_a_dylib_export.md`, whose
§1.4 attributed the same two red rows to a different cause that has since been
fixed and deleted, so this is the cause behind that one.

## The two red rows, and the one hole

`python3 test_formal_dylib.py` is 24/25 with two failures, and BOTH fail on the
same hole count:

```
  FAIL  several exports, and one with no derivable spec
        the 3-export proof admits 1 hole(s); every export with a derived spec
        should have a PROVED contract
  FAIL  a conditional value is not a branch
        the proof admits 2 hole(s); the cset-bearing contract should be proved,
        so the only hole left is the branching export's named `_spec`
```

In each image the extra hole is the LAST export's `{ident}_semantics_total`,
emitted as a `sorry` by `_dylib_total_proof`:

```
theorem dylib_export_1_branched_semantics_total :
    DylibExport.Total dylib_image dylib_export_1_branched := by
  sorry
```

## The root cause, measured

`_export_extent` gives an export "the next export's entry, or the end of the
image" (`base + codeSize`), and `lib/ProofLib.lean::DylibExport.exportEnd` is
the same fold, so the generator and the proof cannot drift. For the LAST export
that end is `base + codeSize`, and **`code` — `sections["text"]` — carries the
interned strings**: the stack-floor trap's `stack_trap_message()` is interned
like any other string (`arm64_codegen.py::_emit_stack_trap_message`, whose own
docstring says "the text is interned like any other string, so it is a `__TEXT`
address"). So the last export's extent runs from its entry, past its own `RET`,
into the string bytes.

`_gen_universal_e2e_cfg`'s constant-fuel arm then decodes those bytes as
instructions, finds a branch whose target is `<=` the branch (a spurious BACK
edge in the string), and `not _acyclic` makes it return `None` — so
`_dylib_total_proof` emits the `sorry` above. Measured on the two-export image
`test_a_conditional_value_is_not_a_branch` builds (`csetval`, `branched`):

```
last export entry     0x1000002ac
_export_extent        0x1000006ac   = base + codeSize
_walk_range           0x100000364   = past the last RET at/after the entry
_gen_universal_e2e_cfg(func_end=0x6ac) -> None      (strings decoded as code)
_gen_universal_e2e_cfg(func_end=0x364) -> a walk     (the real code only)
```

and the bytes at `0x100000364` are:

```
RecursionError: this program's call stack went past the stack budget of …
```

So the last export is the ONLY one whose extent can swallow data (every other
export's extent is the next entry), and it is the ONLY export whose
`_semantics_total` is a `sorry` — which is why a one-export dylib's proofs look
fine (its contract, not its total, is what the tests count) and the two rows
that COUNT holes are red.

## Why it is not a patch, and why it is filed rather than fixed

The walk's exit address must equal `runExport`'s `exportEnd`, because
`DylibExport.total_of_halts` takes the walk's theorem at `runExport`'s own type
— so the walk CANNOT simply be given `_walk_range`: the generated file would
state a run to one address and prove one to another, and Lean would reject it
(the drift is caught by the typechecker, which is the property the shared fold
exists for). The end has to change on BOTH sides at once, and:

* `DylibExport.exportEnd` is a fold over `image.exports` plus `base`/`codeSize`
  (`exportEndAux`), and an export entry carries NO size or end field
  (`_formal_exports`'s dicts are `module/name/symbol/entry/arity/call/…`), so
  the library CANNOT compute "past this export's last `RET`" from what it has.
  Giving the last export its own end therefore means an `end`/`size` field on
  the export table: the generator, the manifest writer, the Lean `DylibExport`
  structure, the emitted `exportEnd_here` `native_decide`, and every cached
  dylib proof at once.
* the alternative — moving the interned strings OUT of `sections["text"]` (a
  second `__TEXT` section, or a pool ahead of the code) — changes the ADRP/ADD
  layout `_intern_string` and `str_addrs` describe for BOTH the executable and
  the dylib path, so it is at least as wide.

Either way `lib/*.olean` must be rebuilt (`ensure_library`) and every cached
proof verdict invalidated, which is a `proofs`-bucket run and not something a
light worker may Lean-verify. **The exact next step is to decide between the
export-`end` field and the code/data split, then land it under the `proofs`
bucket; the measurement above is what tells the two apart, and the two rows in
`test_formal_dylib.py` are already the regression net for it.**

## What is NOT claimed

This is not the CSEL row and not the certificate cost — those are
`FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md` and
`FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`, both still open
and both still on the critical path for a `CSEL` model. It is also not the
stack-floor guard being wrong: `TestTheStackFloorGuardLeavesNoCallOnTheWalkedPath`
passes, the guard's `getrlimit` reads are in the startup stub, and there is no
`bl` in the last export's extent (`_cfg_blocks`'s `bl` count for it is 0 — the
trap uses `svc`, not `bl`). The only thing wrong here is where the last export's
`exportEnd` is.
