# the live `sorry` is not attributed to its fact, and the recipe this project would have reached for does not exist in the pinned Lean

**Area:** `formal/x86_64_endtoend_test.py`'s `admitted_facts` /
`admitted_phrase` · **filed 2026-10-04 on `work/formal25-6`**, NOT fixed ·
deliberately a different doc from the one this replaces's §"The exact next step"
· **both architectures** (the emitter is shared; the corpus runs on both)

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