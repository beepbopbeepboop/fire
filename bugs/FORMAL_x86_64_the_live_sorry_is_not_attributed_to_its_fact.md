# the live `sorry` is not attributed to its fact, and the recipe this project would have reached for does not exist in the pinned Lean

**Area:** `formal/x86_64_endtoend_test.py`'s `admitted_facts` /
`admitted_phrase` · **filed 2026-10-04 on `work/formal25-6`**, NOT fixed ·
deliberately a different doc from the one this replaces's §"The exact next step"
· **both architectures** (the emitter is shared; the corpus runs on both)

## Status 2026-10-04 (`work/formal28-6`): the probe's RECIPE is wrong in two measured ways, and the mechanism it names does find the hole

**Not fixed. What landed is a measurement of the mechanism §"the next step"
describes, and it corrects two things that recipe gets wrong — so the next
session does not spend the day rediscovering them. Nothing about the report
changed: `fired` still comes from Lean's own `declaration uses 'sorry'`, and
`admitted_phrase` still says `candidate`.**

The mechanism EXISTS and works for half of what it is asked to do. Appending
this to the generated file for `formal/examples/const2.mojo`, with
`LEAN_PATH=lib` (without it the file does not even resolve `import X86`, which
is the first thing that looks like "the probe printed nothing") and one
`formal/lean.py::run_lean` at `wall_s=900`:

```lean
open Lean Elab Command in
run_cmd Lean.Elab.Command.liftTermElabM do
  let env ← Lean.getEnv
  for (name, val) in env.constants.toList do
    match val.value? with
    | some v =>
      Lean.Meta.forEachSorryM v fun e => do
        Lean.logInfo m!"SORRY-PROBE {name} :: {repr (← Lean.Meta.ppExpr e)}"
    | none => pure ()
```

**1.32 s, 1.5 GB, `exceeded: None`, and it prints exactly ONE row:**

    SORRY-PROBE _aux_P___1 :: sorry `«P:722:0»

**Which is the finding, and it is the half that matters.** The census over the
same generated text says `['hrip']` — one admitted named fact, 249 guarded side
conditions — and the probe says there is exactly **one** surviving `sorry` in the
whole environment, in `_aux_P___1`, which is the auxiliary declaration Lean
builds for the theorem's `∨` chain. So the doc's own bisection is confirmed by
the mechanism it proposed: the live hole is not `hrip`'s, and there is only one
of it.

**The two corrections, both measured rather than read:**

* **`Declaration.forEachSorryM` does not exist as a projection.** The recipe
  names it, and on the pinned 4.32.2 `error(lean.invalidField): Invalid field
  forEachSorryM: The environment does not contain
  Lean.ConstantInfo.forEachSorryM`. It is reachable only as the fully qualified
  `Lean.Declaration.forEachSorryM`, and it takes a `Lean.Declaration` (a
  `ConstantInfo` with a `.value`), not a `ConstantInfo` — `val.value` is not one.
  `Lean.Meta.forEachSorryM` takes the `Expr` and is what the working probe above
  calls.
* **`isLabeledSorry?` returns `none` on exactly the expression the recipe hands
  to `Meta.forEachSorryM`.** `Meta.forEachSorryM`'s callback receives
  `Expr.getSorry?`'s result, and `getSorry?` strips the tag argument
  (`getBoundedAppFn (getAppNumArgs - 3)`), so there is nothing left to decode.
  The tag survives PRETTY-PRINTING — `repr (← ppExpr e)` prints
  ``sorry `«P:722:0» `` — so the position is recoverable by parsing the tag in
  Python rather than by calling `isLabeledSorry?`. `Lean/Meta/Sorry.lean`'s
  `SorryLabelView.encode` is the format: module, `pos.line`, `pos.column`,
  `endPos.line`, `endPos.column`, `charUtf16`, `endCharUtf16`, as a `Name`.

**And the open question that is left, which is why this is not the fix.** The
one row prints `P:722:0` and the generated theorem occupies lines 1..719, so
the line the label names is not a line of the theorem. Three explanations and
this measurement does not choose between them: the label records the SOURCE REF
at `mkLabeledSorry` time (`Lean/Meta/Sorry.lean`: "If the current ref has a
source position"), which for a `sorry` produced inside a tactic block may be the
block's rather than the tactic's; the pretty-printed form may be showing only the
first numbers of a seven-component name; or `_aux_P___1`'s ref belongs to the
`∨` elaboration rather than to the proof. **Deciding between them is one
`logInfo` with the whole tag on it** — print `repr ((e.getAppArgs[2]?).name?)`
on the FULL application (which needs the raw expression, so a
`forEachExpr'`-based walk, and see the third correction below) — and then the
line maps back through `admitted_facts`'s own nearest-`have`-above rule, which is
already exact for the mapping half.

**A third thing cost an hour and is worth the two lines**, because it is silent
and it makes a working probe look broken: **a `let mut` in a `run_cmd` block
cannot be mutated from inside the `MetaM` closure** the walk passes
(`error: Variable 'log' cannot be mutated. Only variables declared using 'let
mut' can be mutated.` — the `let mut` is there, and the closure is lifted). So
accumulate into an `Array` by `logInfo`-ing inside the closure, never by
mutation. And `Lean.Meta.forEachExpr'` does NOT reach a proof term's sorries at
all — a two-`sorry` control theorem reports nothing through it while
`forEachSorryM` reports both — so the walk has to be `forEachSorryM`.

## What this is

The report line used to read `proved, 1 admitted (hrip), 249 guarded` and name
`hrip` as the hole, which it is not: `admitted_facts` charges every `sorry` to
the nearest `have NAME … :=` above it, and the emitter writes a step lemma with
the `:=` on the CONTINUATION line, so a side condition's `sorry` is charged to
the fact before it. Measured on `formal/examples/const2.mojo`:

    python3 - <<'PY'
    import sys, os; sys.path.insert(0, os.getcwd())
    import formal.x86_64_endtoend_test as T
    text = T.emit_terminates("formal/examples/const2.mojo")
    open(".tmp/const2.lean", "w").write(text)
    print(sorted({n for n, _l, k in T.admitted_facts(text) if k == "admitted"}))
    PY
    # ['hrip']

and deleting the two `hrip` blocks' `all_goals sorry` lines and nothing else
leaves the file checking with `returncode 0` and **no errors** while Lean still
reports `declaration uses sorry`. So the live hole is in one of the 249 guarded
side conditions.

**What landed instead** (`6325c87d`): the report says `admitted candidate`, both
theorem lines go through one `admitted_phrase`, and
`test_formal_sweep_truth.py::TestX86EndToEndEmitter` pins the wording, the
two-line step shape that reproduces the misattribution, and the absence of the
old form. The report no longer asserts what it cannot support; **it still does
not know which hole fired**, and this doc is that remainder.

## What I measured about the recipe, and this is the part that cost the day

The obvious mechanism is a trace option that reports where each `sorryAx` was
created. It does not exist:

    set_option trace.Meta.Tactic.sorryAx true
    # .tmp/leantest/probe.lean:1:0: error: Unknown option `trace.Meta.Tactic.sorryAx`

Measured on the pinned toolchain (leanprover/lean4:v4.32.2, `./lean-toolchain`)
through `formal/lean.py::run_lean`, on a three-theorem file that does nothing
else. `rc=1`, and the file is otherwise fine (`theorem t1 : 1 = 2 := by sorry`
still produces the expected `declaration uses 'sorry'` warning).

**The mechanism that does exist is a LABELED sorry.** In 4.32.2 the source
position is carried *in the term*:

* `Lean/Meta/Sorry.lean`: `mkSorry`/`mkLabeledSorry` — "If the current ref has a
  source position, then creates a labeled sorry … supporting pretty printing
  the sorry with an indication of source position when the option
  `pp.sorrySource` is true";
* `SorryLabelView` — "Records the origin module name, logical source position,
  and LSP range for the `sorry`", encoded in a `Name` the sorry's own type
  carries;
* `Declaration.forEachSorryM` / `Meta.forEachSorryM` — walks a declaration's
  elaborated term and hands back each surviving `sorry` expression, which
  `isLabeledSorry?` then decodes into the position.

So the attribution is a PROBE over the elaborated term, not a flag. Concretely:
append to the generated file a block that walks `Lean.getEnv`'s theorem values
with `Declaration.forEachSorryM` and prints each `isLabeledSorry?` position,
map each `file:line:col` back to the nearest `have` above it (the same rule
`admitted_facts` already implements, and now exact because the position is the
`sorry`'s own line rather than a guess from the shape), and print
`admitted (hstep31, side condition, line 812)`.

## The next step, and the cost question that has to be answered first

1. **Write the probe and run it on `const2`** — 16 steps, the file whose live
   hole is already located by the bisection above, so a correct probe must
   print a line that is NOT `hrip`'s own admission. That is the acceptance test
   and it is one Lean run of 3.4 s (`bugs/FORMAL_x86_64_the_stack_floor_guards_
   exit_call_leaves_the_image.md` quotes that figure) rather than a project.
2. **Measure the probe on `wide_recv`** (94 leaves / 12 241 step equations, the
   corpus's largest tree) before believing it. A walk over an elaborated term
   is proportional to the TERM, and these files' terms contain the `native_decide`
   evaluations that `FORMAL_native_decide_axiom.md` is paying down; if the walk
   costs more than the elaboration it is inspecting, the answer is to ask Lean
   for positions while the term is still small (a `have`-per-step marker) rather
   than to walk afterwards.
3. **Only then** change `admitted_phrase` to print an identified hole, and
   **delete `test_a_side_condition_is_charged_to_the_fact_before_it`'s assertion
   in the same commit** — it is written to fail the day the attribution is
   fixed, and leaving it would make the fix look like a regression.

If step 2 says no, the fallback is worth stating now so it is not re-derived: the
emitter can emit a `set_option pp.sorrySource true` in the generated file (a
DIAGNOSIS option rather than a trace class — it is the one the labelled sorry
exists for) and read the positions off the pretty-printed `sorryAx` in a
`#print axioms`-shaped probe. That is the same walk by another route, so it
inherits the same cost question.

## What is NOT attempted here

No change to the emitted file's text, and no change to what the report decides:
`fired` still comes from Lean's own `declaration uses 'sorry'`, which
`6325c87d`'s sibling commit (`6f2bbe97`) established is the only thing that
knows whether a guard's `sorry` is load-bearing. This doc is about the NAME
beside a verdict that is already true.

## Reproducing

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
    python3 formal/x86_64_endtoend_test.py formal/examples/const2.mojo

**And the probe itself**, which is the Status block's `PROBE` text appended to
`T.emit_terminates("formal/examples/const2.mojo")`, written to a file and run
with `LEAN_PATH` including this tree's `lib` — `formal/lean.py::run_lean`,
`wall_s=900`:

    python3 tools/memslot.py --gb 8 --label probe -- python3 - <<'PY'
    import os, sys, tempfile
    sys.path.insert(0, os.getcwd())
    import formal.x86_64_endtoend_test as T
    import formal.lean as L
    PROBE = open(".tmp/probe.lean").read()      # the Status block's text
    lib = os.path.join(os.getcwd(), "lib")
    L.ensure_library(L.find_lean(), lib)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "P.lean")
        open(p, "w").write(T.emit_terminates("formal/examples/const2.mojo") + PROBE)
        cp = L.run_lean(L.find_lean(), [p], cwd=d,
                        env=dict(os.environ, LEAN_PATH=os.pathsep.join((d, lib))),
                        wall_s=900, cpu_s=900)
        print(cp.exceeded)
        print("\n".join(l for l in (cp.stdout + cp.stderr).splitlines()
                         if "SORRY-PROBE" in l))
    PY
    # None
    # SORRY-PROBE _aux_P___1 :: sorry `«P:722:0»`