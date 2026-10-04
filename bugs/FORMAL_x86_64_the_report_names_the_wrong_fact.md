# FORMAL_x86_64_the_report_names_the_wrong_fact: a live `sorry` in a side condition is charged to the `hrip` above it

**Area:** FORMAL (the x86-64 end-to-end reporter). Found 2026-10-04 on
`work/formal23-6`, while landing the concrete-read proof in
`formal/x86_64_endtoend_test.py`.

## What I ran

`const2` — `formal/examples/const2.mojo`, 16 steps, no `call`, so its closing
read is the one at `X86State.init`'s stack:

```sh
python3 - <<'PY'
import sys, os; sys.path.insert(0, os.getcwd())
import formal.x86_64_endtoend_test as T
text = T.emit_terminates("formal/examples/const2.mojo")
open(".tmp/const2.lean", "w").write(text)
print(sorted({n for n, _l, k in T.admitted_facts(text) if k == "admitted"}))
PY
# ['hrip']

python3 tools/memslot.py --gb 8 --label c2 -- python3 .tmp/runlean3.py .tmp/const2.lean
# secs 3.4  returncode 0  errors 0
# sorry: ['…: warning: declaration uses `sorry`']
```

## What I saw

The census says the hole is `hrip`. It is not. Deleting the two `hrip` blocks'
`all_goals sorry` lines — and nothing else — leaves the file checking with
`returncode 0` and **no errors**, while Lean still reports
`declaration uses sorry`:

```
hrip blocks patched: 2   # the admissions removed, nothing else
secs 3.9  returncode 0  errors: 0
sorry: ['…: warning: declaration uses `sorry`']
```

So the live `sorry` is in one of the 249 side conditions, and the name in the
report line — `proved, 1 admitted (hrip), 249 guarded` — is wrong. The same
measurement on the pre-change emitter gives the same line and the same sorry, so
**this is pre-existing and not a regression**; what changed is that the reader is
now told there is a hole and is given a name for it, and the name is not the
hole's.

Why the census cannot see it: `admitted_facts` attributes a `sorry` to the last
`have … :=` it read, and a side condition's `sorry` belongs to the step
application that encloses it, which is a different `have`. The two classes are
distinguished by the LINE (a fact's own admission is `all_goals sorry` alone; a
side condition's shares its line with the `)` that closes the inline `by`), which
is exact for the emitter's two shapes and says nothing about *which* of several
hundred side conditions fired.

The verdict itself is now correct — `_run_lean` asks Lean, and Lean says the
file uses `sorry` — so the gap is the NAME, not the pass/fail.

## What I expected

Either that the report say the hole is unattributed when there are guarded facts
to choose from, or that something could attribute it.

## The exact next step

Two options, and the first is a day of work and the second is an afternoon:

1. **Attribute it in Lean.** `set_option trace.Meta.Tactic.sorryAx true` (or
   `Lean.collect sorryAx` over the elaborated term) reports the position of every
   `sorryAx` the elaboration actually kept, which is the one thing the text census
   cannot know. `formal/lean.py` already has a `Census` that reads Lean's own
   hole report, so the machinery is there; what is missing is the per-fact
   position. That makes the report's names true, and it retires the whole class
   rather than this instance.
2. **Stop claiming more than the census knows.** When `fired` is true and there
   is at least one guarded fact, print the admitted names as *candidates*:
   `proved, 1 admitted candidate (hrip), 249 guarded`. Cheap, honest, and it
   stops the report from asserting a name it cannot support. It is a wording
   change in `main`'s `term_gap` branch plus a line in `admitted_facts`'s
   docstring.

Either way the sentence in `admitted_facts`' docstring that the counts "are for
NAMING a hole once Lean has said there is one" needs the other half of the
claim: a name is a candidate, not an identification.
