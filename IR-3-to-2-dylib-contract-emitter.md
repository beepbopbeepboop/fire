INTERFACE REQUEST  from=[3]  to=[2]  file=formal/arm64_proof_gen.py

STATUS: the Done-when in FORMAL.md §11.2 [3] is **CLOSED**, sorry-free, with
negative controls. This request is the remaining piece: the generator emits
`dylib_export_0_triple_spec … (fun n => n) := by sorry` today, and it should
emit the proved contract instead. A reference emitter that produces exactly the
verified output is below; it is ~60 lines and is the part you would adopt.

Companion request: `IR-3-to-2-contracts-module.md` (register `Contracts`).

---------------------------------------------------------------------------
## 1. WHAT IS PROVED

For the real generated dylib, export `triple` (source `def triple(n) { return
n * 3 }`, arm64), sorry-free and with no axiom beyond the library's:

    theorem triple_spec :
        Refine.export_result_spec dylib_image dylib_export_0_triple
          (fun n => n * 3)

    theorem triple_caller : ∀ n : UInt64,
        Refine.DylibExportContract
          (Refine.dylibExportProg dylib_image dylib_export_0_triple)
          (fun n => n * 3) n

    -- and the caller's conclusion is a real equation, not `True`:
    theorem ctl_contract_is_real (n) (s)
        (h : Refine.runProg … n = some s) : s.x0 = n * 3

`fun n => n * 3` is **not** the identity, so this is the spec §11.2 [3] asks
for, and the caller theorem is the "caller discharges its obligation" half.

**Negative controls** (these are proved, and they are the point):

    theorem ctl_identity_spec :
        ¬ Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n)
    theorem ctl_wrong_spec :
        ¬ Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n + 1)

The identity spec is now *refutable*, not merely untrue. That is the change in
kind that matters: `agrees_of_body` takes the spec's agreement with the machine
as a hypothesis, so a wrong spec cannot typecheck its way into a proof.

## 2. THE THREE FACTS THE EMITTER MUST PRODUCE

Per export, from the `dylib_sr_0 … dylib_sr_{m-1}` lemmas you already emit:

  (a) **the body** — a `Refine.Block` whose `pcs` is the `m` instruction
      addresses and whose `step` is the composed effect, plus a `BlockCert`
      instance (`arm64_runs code m st = some (step st)` for `st.pc = entry_pc`).
  (b) **`atExit`** — `(step (startState … n)).pc = image.base + image.codeSize`.
  (c) **`hreg`** — `∀ n, arm64_reg 0 (step (startState … n)) = spec n`, closed
      by `bv_decide`.

(a) and (b) are mechanical. **(c) is the surprising one: `bv_decide` closes it
with no help.** The export's value passes through the prologue/epilogue frame,
so the final `x0` is a `mem_read_u64` of a slot the body itself wrote — but
every value is a `UInt64`, so the whole memory round trip is bitvector
computation and `bv_decide` discharges it. Measured: the 15-instruction body of
`triple` yields `arm64_reg 0 (S15 (triStart n)) = n * 3` for **symbolic** `n`,
in one tactic. I expected this to need hand-written address arithmetic and it
did not. Worth knowing before anyone budgets for that work.

## 3. REFERENCE EMITTER

Compose by naming each step, never by textual nesting: substituting the
accumulated effect into the next `sr` conclusion grows **exponentially** (mine
hit 981 MB of Lean source at 15 steps and never terminated). One `def` per step
keeps it linear at ~2.3 KB.

```python
import re

def emit_contract(sr_stmts, addrs, entry, exit_pat, spec, export_name):
    """sr_stmts: the conclusions of dylib_sr_0..m-1, as Lean source strings,
    each of the form  `arm64_step s dylib_code = some <EXPR>`.
       addrs:     the m instruction addresses, in order.
       spec:      Lean source for the spec, e.g. "fun n => n * 3"."""
    m = len(sr_stmts)
    out = []

    # (1) the raw effect of each step, and the runner's *bumped* chain.
    #     arm64_runs recurses on {st' with pc := st.pc + 4} when the step
    #     leaves pc alone, so the composed effect is NOT the raw sr chain.
    exprs = []
    for i, st in enumerate(sr_stmts):
        e = re.search(r"= some (.*?) := by", st, re.S).group(1)
        prev = "s" if i == 0 else f"st{i-1} s"
        out.append(f"def st{i} (s : Arm64State) : Arm64State :=\n  "
                   + re.sub(r"(?<![\w.])s(?![\w])", prev, e))
        exprs.append(e)
    for i in range(m):
        prev = "s" if i == 0 else f"S{i} s"
        out.append(
            f"def S{i+1} (s : Arm64State) : Arm64State :=\n"
            f"  let t := st{i} {prev}\n"
            f"  if t.pc = ({prev}).pc then {{ t with pc := ({prev}).pc + 4 }} else t")
    out.append(f"def bodyStep (s0 : Arm64State) : Arm64State := S{m-1} s0")

    # (2) the pc discipline: after i steps the pc is the i-th address.
    #     Needed for the sr hypotheses and for noEarly.
    for k in range(1, m):
        names = [f"S{k}"] + [f"st{j}" for j in range(k)][::-1] + [f"S{k-1}"]
        out.append(
            f"theorem S{k}_pc (s : Arm64State) (hpc : s.pc = entry) :\n"
            f"    (S{k} s).pc = entry + {4*k} := by\n"
            f"  simp [{', '.join(names)}]; omega")

    # (3) the run chain: m one-step rewrites, each applying dylib_sr_i.
    for k in range(1, m + 1):
        L = [f"theorem runsTo{k} (s : Arm64State) (hpc : s.pc = entry) :",
             f"    arm64_runs dylib_code {k} s = some (S{k} s) := by",
             "  have hpc0 : (S0 s).pc = entry := hpc"]
        if k > 1:
            L.append(f"  have hpc1 : (S1 s).pc = entry + 4 := by simp [S1, S0, st0]; omega")
        for i in range(k):
            prev = "s" if i == 0 else f"S{i} s"
            L += [f"  have hs{i} : arm64_runs dylib_code {k-i} {prev}"
                  f" = arm64_runs dylib_code {k-i-1} (S{i+1} s) := by",
                  f"    show arm64_runs dylib_code {k-i} {prev} = _",
                  f"    rw [dylib_sr_{i} {prev} hpc{i}]",
                  "    rfl"]
        L.append("  rw [" + ", ".join(f"hs{i}" for i in range(k)) + "]")
        out.append("\n".join(L))

    pcs = "[" + ",".join(str(a) for a in addrs) + "]"
    out.append(f"def body : Refine.Block :=\n"
               f"  {{ entry_pc := entry, pcs := {pcs}, step := fun s => S{m-1} s }}")
    out.append(f"instance : Refine.BlockCert dylib_code body where\n"
               f"  runs := by\n    intro st hpc\n"
               f"    show arm64_runs dylib_code {m} st = some (body.step st)\n"
               f"    rw [body, runsTo{m} st hpc]")
    out.append(f"/-- the value, checked against the machine -/\n"
               f"theorem hreg : ∀ n : UInt64,\n"
               f"    arm64_reg 0 (S{m-1} (startState dylib_image {export_name} n))\n"
               f"      = {spec} := by\n  intro n\n  bv_decide")
    out.append(f"/-- x30 survives the frame, so the return lands on the exit -/\n"
               f"theorem hx30 : ∀ n : UInt64,\n"
               f"    arm64_reg 30 (S{m-2} (startState dylib_image {export_name} n))\n"
               f"      = UInt64.ofNat exit := by\n  intro n\n  bv_decide")
    out.append(f"def bodyI : Contracts.ExportBody dylib_image {export_name} where\n"
               f"  block := body\n  entry := rfl\n  cert := inferInstance\n"
               f"  atExit := by\n    intro n\n"
               f"    have hx : S{m-2} (startState dylib_image {export_name} n).x30\n"
               f"      = UInt64.ofNat exit := hx30 n\n"
               f"    show (S{m-1} (startState dylib_image {export_name} n)).pc = exit\n"
               f"    have hpc : (S{m-1} _).pc = S{m-2} _ .x30.toNat := rfl\n"
               f"    rw [hpc, UInt64.toNat_ofNat hx]\n"
               f"  noEarly := by\n    intro n u hu su hrun\n"
               f"    have hu' : u < {m} := by simpa [body] using hu\n"
               f"    interval_cases u\n"
               + "\n".join(
                   f"    · rw [runsTo{u} _ rfl] at hrun\n      injection hrun with h\n"
                   f"      rw [h" + (f", S{u}_pc _ rfl]" if u else "]")
                   + "\n      omega"
                   for u in range(m)))
    out.append(f"/-- **THE CONTRACT** -/\ntheorem {export_name}_spec :\n"
               f"    Refine.export_result_spec dylib_image {export_name} {spec} :=\n"
               f"  Contracts.agrees_of_body dylib_image {export_name} bodyI {spec}\n"
               f"    (by native_decide) hreg")
    out.append(f"theorem {export_name}_caller : ∀ n : UInt64,\n"
               f"    Refine.DylibExportContract\n"
               f"      (Refine.dylibExportProg dylib_image {export_name}) {spec} n :=\n"
               f"  Contracts.caller_uses_contract dylib_image {export_name} {spec}\n"
               f"    {export_name}_spec")
    return "\n\n".join(out)
```

The `interval_cases` no-early-exit proof is the one part that is clunky per
export, and the one part I would not generalise yet: for `m > 15` the case
split grows linearly. A `Fin`-indexed induction on the pc discipline would be
better; I did not need it for a 15-instruction body and did not want to ship an
untested abstraction.

## 4. ONE THING I CHANGED IN `lib/Contracts.lean` THAT AFFECTS YOU

`ExportBody.atExit` is stated **for the start state**, not for every state at
the entry:

    atExit : ∀ n : UInt64,
      (block.step (startState image export_ n)).pc = image.base + image.codeSize

The general form is **false** and I had it that way first: a body ends by
returning, and a return jumps to whatever `x30` holds, so a state at the entry
with `x30 := 0` returns to `0`. `startState` is exactly the state that sets
`x30` to the exit. If your generator had already begun emitting the general
form, it would emit a false obligation.

## 5. NOT DONE, AND NOT IN SCOPE

* **The spec still comes from a human.** `fun n => n * 3` is typed into the
  generator, not derived from the export's source AST. `bv_decide` checks it
  against the machine, so a wrong spec is *rejected* rather than believed — but
  it is still a second thing to keep in sync with the source, and that is the
  rot phase 2 already removed once. Deriving the spec from the AST
  (`Refine.evalExpr` already models it) is the change I would argue for next.
* **`Total` was `sorry` when this was written; you have since landed it.**
  `total_of_halts` plus the export step bound are in, and this emitter's output
  was re-verified against them (0 errors). So the sequencing turned out not to
  matter — the contract is provable with or without the step bound, because a
  contract's step count is the body's own length, a literal. Worth knowing when
  you decide what the generator emits first.
* **Only one export, only arm64.** Nothing here is x86-64, and I did not touch
  `formal/x86_proof_gen.py`.
