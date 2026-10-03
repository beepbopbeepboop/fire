# dylib exports: the loop-fuel obligation, and a `FrameBound` that is ALREADY
# depth-indexed

**Status: two of the three open items are now closed or corrected; the third
(loops) is unchanged and is still a scheme extension.** The x86-64 item is
answered and the answer was worse than "never measured"; the `bl` item's
premise was wrong, and the corrected reading makes it a different and smaller
piece of work than it looked.

**For an agent starting with no context.** §2 of the document this replaces
recorded two rules that have already cost this project real time and still do:
a `sorry` over a FALSE statement is indistinguishable from one over a true one,
and replacing a literal with a function hides it from every tactic. Both are
load-bearing for what follows and neither is re-derived here.

## 1. What closed, and what it was

| was | now |
|---|---|
| `formal-dylib` RED on `default path emits a checked proof`; the emitted 210 KB proof "did not finish in 30 minutes" | **GREEN.** `python3 tools/suite.py formal-dylib --no-cache` -> 3 passed / 0 failed. The generated proof of `def triple(n): return n * 3` checks in **9.0 s wall / 14.4 s CPU / 1.63 GB peak**, rc 0, **0 holes** |
| `OPUS-1` "`hreg` exhausts `maxHeartbeats`; raise it and measure the real cost" | **Not a budget question, and no budget was raised.** The goal had to get smaller: a fourteen-fold nest of the runner's own `if pc = pc then .. else ..` is what `bv_decide` could not normalise. The emitter emits that `if` **resolved** for every step it knows moves no pc |
| `OPUS-2` "`test_formal_dylib.py:402-410` pins the obligation set by EQUALITY" | **Fixed**, and then widened: 20 cases, including a multi-export image with a proved contract per export and a case that four WRONG specs are rejected for that image |
| `OPUS-3` "the `noEarly` unfold I added is a suspected cost centre" | **It was one, and a bigger one than `hreg`.** Fifteen `simp only [S15…, st0…]` blocks, each re-unfolding the composed state. They are now fifteen `omega`s off one per-step `pc` lemma |
| the eight gate tests `disabled=` | Re-enabled (`0cfe0d16`), and `test_formal_dylib.py` is **19/19** on this tree |

## 2. The two rules that have already cost this project real time

### A `sorry` over a FALSE statement is indistinguishable from one over a true one

This has happened **four** times, which is why it is a rule and not an
anecdote:

1. `Total` was `∀ n s, runExport … n = some s`. Refuted by a toy, and fixed to
   `∀ n, ∃ s, …`.
2. The constant `exportFuel` made `Total` **false** for `countdown`; a named
   `sorry` sat on the impossibility while the census reported it as an open
   obligation. Checked by `total_refuted_backward_branch`.
3. Every all-states theorem written here was false for any image containing a
   `ret` (arbitrary `x30`) or a pc below `image.base`.
4. `st_i`'s composed effect was `n * 243` for a machine computing `n * 3`, under
   a `hreg` that was a `sorry`.

The instrument that catches all four is the cheapest one there is: **state the
predicate at a concrete instance and see whether it survives.** The census counts
holes; `vacuous_declarations` counts vacuous bodies; neither asks whether a
statement is **inhabited**, and none of the three would have caught #4.

### Replacing a literal with a function hides it from every tactic

`fuel_lean` replaced the emitted fuel *literal* `100000` with the library
*function* `DylibExport.exportFuel dylib_image n`, so the two could not drift.
Good change. But the walk's step-accounting goals are `omega` calls, and `omega`
**cannot unfold a library function**. The generalisable part: **both `omega` and
`native_decide` work on literals.** A no-drift property bought by swapping a
literal for a function has to be paid for by re-supplying the bounds the literal
used to carry. `e0af987` paid it by going back to literal arithmetic (`200000 +
15 * n.toNat`); the hazard is live for any future swap of the same shape.

## 3. `OPUS-6` — x86-64: the answer is that there IS no x86-64 dylib contract

The item said "**Measure** the acyclic/no-call boundary on x86 the way §1
measured it for arm64 … `formal/x86_64_proof_gen.py` is untouched by everything
above." Measured, and the measurement is a defect rather than a data point.

**`--backend` is a GLOBAL flag and the `dylib` command never read it.**
`compile_formal_dylib` takes `arch` (and `build --formal` passes it), but
`fire.py`'s `dylib --formal` branch called it without one. So:

```console
$ python3 fire.py dylib --formal --no-prove --backend=x86_64 -o s_x s.mojo
Built: .tmp/opus6/s_x86_64
$ file .tmp/opus6/s_arm64 .tmp/opus6/s_x86_64
.tmp/opus6/s_arm64:   Mach-O 64-bit dynamically linked shared library arm64
.tmp/opus6/s_x86_64:  Mach-O 64-bit dynamically linked shared library arm64
```

**Both arm64.** `--backend` was accepted, consumed by the global parser so it
never appeared as a stray input filename, and ignored. A reader running the
measurement this document prescribed would have got an arm64 answer and written
down "the same argument applies" — the hypothesis §OPUS-6 explicitly says must
not be assumed.

And going through the API reaches the same place one layer worse:
`compile_formal_dylib([src], prove=True, arch="x86_64")` feeds x86-64 machine
code to `formal/arm64_proof_gen.py`, which raises

```
File "formal/arm64_proof_gen.py", line 3012, in _gen_run_cert
    idx = _step_branch_index(words[pc])
KeyError: 4294967948
```

— the generator decoding x86-64 words as arm64 and not finding one.

**Fixed, at the layer that has the conflict.** `compile_formal_dylib` now refuses
`arch != "arm64"` with `prove=True`, by name, naming both halves (`arch` reaches
the CODE generator and the image builds; the CONTRACT is arm64-only because
`generate_dylib_proof` and `DylibExport` are stated over `arm64_go_exit` /
`arm64_step` / `arm64_runs`), and saying `prove=False` is how to ask for the
x86-64 image that does build. `fire.py` checks first, with a better message and
exit 2, and also refuses `--backend` on the plain gimple `dylib` — where the
architecture is the HOST's, so that request is right only by coincidence on an
arm64 host. Pinned by
`test_a_proved_dylib_is_an_arm64_artifact_and_says_so`: the x86-64 image's
Mach-O cputype, the API refusal's wording, and both CLI refusals.

So `OPUS-6` is answered, and the answer is that the x86-64 dylib **contract** is
a generator that does not exist. Writing it is `formal/x86_64_proof_gen.py`'s
`DylibExport` analogue over `X86.lean`, and nothing here needs to be guessed
first.

## 4. `OPUS-5` — `bl`: the premise was wrong, and the work is smaller than it looked

The item said: "The real fix: state and prove a depth-indexed frame bound
(`∀ k ≤ depth, FrameBound … at level k`) discharged from the instruction count,
and re-thread `hbnd` in terms of it. Not started; real work." And: "The claim to
check before writing anything is whether `depth` is already a parameter of the
walk; if it is not, that is the change, and it is not small."

**`depth` is not a parameter, and does not need to be — `arg` IS the depth
index.** Measured from the library rather than inferred:

* `Refine.FrameBound stride st arg` (`lib/Refine.lean:293`) is an `abbrev` for
  `stride * (arg.toNat + 1) ≤ st.sp.toNat`. At recursion depth `k`, where
  `arg.toNat = k`, that is *exactly* `stride * (k + 1) ≤ sp` — a depth-indexed
  bound, indexed by the recursion argument, not by a separate counter.
* `contract_sound` (`lib/Refine.lean:526`) inducts on `k` with the side
  condition `arg.toNat = k`, and the induction hypothesis is the caller's
  `FrameBound stride st arg`. **The frame bound is already threaded through the
  recursion**, per level, which is what the item described as the missing thing.
* The induction step is `frameBound_succ` / `frameBound_succ_call` /
  `frameBound_descend_le`, each taking the level's own `P` and re-deriving the
  bound. `stride` is discharged from the emitter's frame layout (the
  `_SCRATCH` reservation plus the callee-saved pairs), which is the
  "discharged from the instruction count" the item asked for.

**So what is actually missing for a `bl` export?** Not a frame bound. The walk
declines for a *different* reason, and it is one line
(`formal/arm64_proof_gen.py`, `_gen_universal_e2e_cfg`):

```python
if (recursive or not _acyclic or fuel < _TOTAL
        or any(b["kind"] == "bl" for b in blocks)):
    return None
```

The `bl` arm refuses because the walk is called with `recursive=False,
halt_only=True` and a CONSTANT fuel, so it cannot produce the pair of per-level
CFG walks (`hbase` and `hstep`) that `contract_sound` consumes. Producing them
is the work: a base-case walk at `arg = 0` and a step-case walk that reaches the
call site and re-applies the contract for `arg - 1`, each discharged from
`Refine`'s existing generic lemmas. Every ingredient those need
(`frameBound_succ`, `Post`, `Post.exit_correct`, `block_advance`) is already in
`lib/Refine.lean` and proved.

**Therefore `OPUS-5` is not "not started, real work" about a frame bound. It is
"the dylib emitter does not emit the recursion contract, and the library side of
it is finished."** That is a scoping correction worth more than the frame bound
would have been, because the frame-bound reading implies a change to
`lib/ProofLib.lean` that nothing needs.

## 5. The classification, measured (arm64, and it is what §4 is scoped against)

Three dylibs, one build each, read off `_dylib_total_proof`'s own output — the
method §OPUS-6 prescribed:

| export | shape | words | its own extent | `_semantics_total` |
|---|---|---|---|---|
| `triple` | straight line, no call | 15 | 15 | **`total_of_halts`** — proved |
| `twice` | straight line, no call (in a two-export image) | 33 | 15 | **`total_of_halts`** — proved |
| `quad` | calls `twice` | 33 | 18 | NAMED obligation |
| `countdown` | `while` loop | 27 | 27 | NAMED obligation |

## 6. `OPUS-4` — loops: `Total` is true, and still unproved. Unchanged.

`e0af987` closed the *falsehood* (`exportFuel` is `200000 + PATH * n`, and a
measured `countdown` halts through `n = 5000`, returns `none` at `8000`). It did
not produce a proof: `total_of_halts` consumes an acyclic, call-free CFG walk,
which is exactly what a loop is not, so `_dylib_total_proof` falls back to the
named `sorry` obligation — measured above for `countdown`.

Closing it is a **scheme extension, not a fix** — a ranking function, or a fuel
invariant the walk carries. Do not report "fuel grows with `n`" as termination:
that is the false-versus-unproved confusion this project has been bitten by three
times (§2). The honest next step is to read the `halt_only` walk's fuel
accounting and decide between a ranking function and a per-back-edge counter,
because a `while` that decrements a counter is the case `exportFuel`'s `PATH * n`
was sized for and a proof of it would be a *fuel* invariant rather than a new
induction.

## 7. State bits that will save a fresh context time

- **`lib/Contracts.lean` is registered** in `formal/lean.py`'s
  `LIBRARY_MODULES` and builds, so the emitter's `import Contracts` resolves.
- **`formal/arm64_proof_gen.py` has duplicated definitions** (`FORMAL.md` §10):
  `generate_arm64_proof`, `_gen_extern_test`, `_find_extern_call`. Byte-identical
  so behaviour is unaffected and Python binds the second — but **the live
  `_gen_extern_test` is the later one**, and any line number referring to the
  other copy is wrong. `_dylib_contract_proof` is NOT duplicated.
- **Do not `rm lib/*.olean` or `*.srcsha256`.** They are shared and built under
  an exclusive `flock`; `ensure_library` rebuilds on its own.
- **An export's extent is `DylibExport.exportEnd`**, a fold over the image's own
  export table — derived, never a field, so the proof's notion and the
  generator's cannot drift without the file failing to typecheck. The Python
  side is `_export_extent`, the same rule, and each export states its exit as a
  `native_decide`d `exportEnd_here`.
- **The ceiling on proved contracts is `_dylib_spec_lean`, not `Refine`.** See
  `bugs/FORMAL_dylib_block_layer_is_not_the_ceiling.md`, which measured it.
- **Never `git commit` a bare path in a tree with concurrent agents**: it commits
  everything STAGED, which is how the golden file
  `formal/golden/arm64_dylib_contract_triple.lean` was deleted by accident. Use
  `git commit -o <paths>`, or check `git status` first.