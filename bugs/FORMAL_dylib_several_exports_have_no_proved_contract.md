# A dylib with more than one export can never have a proved per-export contract

**Status: OPEN. Found 2026-10-03 while fixing the non-terminating one; the fix
is a library change, so the emitter refuses instead of emitting something that
does not elaborate.**

## What I ran

`python3 test_formal_dylib.py`'s new case `several exports, and one with no
derivable spec` — a three-export dylib (`add1`, `mul2`, `pick`), `prove=True`,
`check=True`, arm64 — plus the six shapes in
`formal/arm64_proof_gen.py`'s emitter exercised by hand
(`triple`, a three-export image, `return n + 1 + 1`, a two-parameter export, a
`while` loop, and an `if`-returning export).

## What I saw

For the three-export image the emitted proof checks clean (2 named obligations,
2 admitted `sorry`s, 0 vacuous, both naming the spec derived from the source) —
but **neither export gets a PROVED contract, and neither can.** Each export's
body occupies `[entry, next export's entry)`, and
`Contracts.ExportBody`'s `atExit` is stated at

```lean
  atExit : ∀ n : UInt64,
    (block.step (startState image export_ n)).pc = image.base + image.codeSize
```

— the **IMAGE's** exit, not the export's. So a `Block` for one export of
several cannot end where `atExit` requires it to, and
`Contracts.runs_to_body` (which consumes `atExit`) is unreachable for it.

Before 2026-10-03 the emitter did not notice: it built the block over the WHOLE
image's address list (`pcs` = every word's address, `step` = the chain from the
export's entry to the end of the image) regardless of which export it was for.
For a single-export image that coincides with the truth, which is why the one
export in `test_formal_dylib.py` never showed it; for a multi-export image the
`BlockCert` was a theorem about a block nobody could run.

## What I expected

A per-export contract, because `ExportBody` is per-export in every other field
(`entry` is `export_.entry = block.entry_pc`, `pcs` is the block's own list, and
`noEarly` is over `block.pcs.length`). `atExit` is the one field that is
about the image, and reading it as about the export is what the emitter did.

## Why I did not fix it here

The fix is in `lib/Contracts.lean`, which is [3]'s file and not this round's
write set, and there are two honest ways to do it and they are not equivalent:

1. **`atExit` takes the exit as a parameter.**
   `atExit : (block.step (startState image export_ n)).pc = exit` with `exit`
   supplied by `runs_to_body`, which already knows it — it passes
   `image.base + image.codeSize` to `go_exit_within` explicitly. Then
   `ExportBody` is genuinely per-export and the emitter can emit a `Block` over
   `[entry, func_end)`. This is the smaller change and it is the one that makes
   the type say what is meant.
2. **A separate `ExportBodyIn` / a second structure for "an export that is the
   whole image".** Bigger, and it leaves the common case (one export per image)
   on the old shape for no reason.

Either way the emitter change is already in place and waiting:
`formal/arm64_proof_gen.py::_dylib_contract_proof` takes `func_end` and refuses
unless `entry == base and func_end == base + len(code)`, and the refusal emits
the derived spec as a NAMED obligation rather than a guessed one. Once
`atExit` is per-export, deleting those two lines of refusal is the whole
emitter-side change.

**The next step, in order:**

1. Read `lib/Contracts.lean`'s `ExportBody`, `runs_to_body` and `agrees_of_body`
   and change `atExit` per (1). `export_result_spec` and `runProg` are
   unaffected.
2. In `formal/arm64_proof_gen.py::_dylib_contract_proof`, drop the
   `entry != base or func_end != base + len(code)` refusal, and pass `func_end`
   as the block's end so `pcs` covers `[entry, func_end)`.
3. `test_formal_dylib.py`'s `several exports, and one with no derivable spec`
   then fails on `check(_re.search(rf"theorem {ident}_spec\b", text), ...)` —
   which is the assertion that has to change, and it is the point of the test:
   flip it to require `Contracts.agrees_of_body` for each of `add1`/`mul2`.
   `pick` keeps its refusal: a body with a branch is not a `Refine.Block`,
   which is a separate and much larger limitation (see §"also" below).

## Also found, and also not fixed here

**A body with a conditional branch has no contract either**, for a different
reason: `Refine.Block.step` is `Instr = Arm64State → Arm64State`, one function
of one state, and a conditional branch's effect is `fun s => if <flag> then
{pc := a} else {pc := b}` — which *is* such a function, so `Refine.Block` can
express it, but `Refine.BlockCert`'s `runs` (one composed effect for the whole
`pcs` run) cannot, because the run's `pc` discipline is then data-dependent and
`noEarly`'s `∀ u < pcs.length` split over literal addresses does not apply.
`_dylib_contract_proof` refuses any body whose `_step_rhs` mentions a
conditional (`if ` in the model's effect), which for this emitter means CBZ /
CBNZ / B.cond — the conditional pc-write shapes. The export's TERMINATION is
still proved or named (`total_refuted_backward_branch` handles the refuted
half: `pick` above reports 0 admitted `sorry`s), so what is missing is only the
per-export agreement-with-spec for a branching export.

That is a **scheme extension, not a fix**, in the sense
`bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §2 uses the phrase for
`OPUS-4`: the block layer needs a per-block `pc` FUNCTION rather than a literal
address list, which is a change to `Refine.Block` and `BlockCert` and to every
emitter that uses them. Not to be started without reading
`formal/arm64_proof_gen.py`'s main-path walk first, which already handles
branches with a different structure (`qS`/`qT` plus `self{i}` lemmas per block
address) and may already have most of it.
