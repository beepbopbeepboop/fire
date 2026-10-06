# A generated proof that exceeds Lean's memory ceiling is REJECTED, and four short-circuit proofs are red for that reason alone

**Area:** FORMAL (the arm64 proof generator's OUTPUT vs `formal/lean.py`'s Lean
run). Found 2026-10-03 on `work/formal16-7`, while landing a change to
`formal/arm64_proof_gen.py` and running `test_formal_short_circuit_cond.py` as
one of the narrow files that cover it.

**Status: the CAUSE is now measured and it is none of the three things this
doc listed; NOT FIXED. The cost is `native_decide`/`bv_decide` in the
per-block BRANCH-CONDITION facts, and what is missing is a lemma for a
short-circuit condition's value flow, not a smaller record and not a larger
ceiling.** §2 is the bisection; §3 is the fix direction; §4 is what was
already tried and measured against. **§6 is new (2026-10-05) and it is the
narrowest statement of the fix that has been measured: the per-block fact the
fix needs is one block WIDE, and the reason it cannot be made that narrow is a
specific register class that `hprior_*` does not cover.**
**§5 — the census half of this doc, the half that made the regression above
invisible — is FIXED (2026-10-04): a replayed verdict now says so in the
ledger, on the screen and in the summary, so a `wall_s: 0.1` row cannot be read
as coverage again.**

## What was run, and what it showed

`test_formal_short_circuit_cond.py` on this tree, arm64, Lean present:

```
$ python3 tools/memslot.py --gb 8 --label scc -- \
      python3 test_formal_short_circuit_cond.py
...
Ran 12 tests in 393.868s
FAILED (failures=4)
```

All four are the same subtest of one assertion, and all four say the same
thing:

```
FAIL: test_generated_proofs_typecheck_with_no_sorries (program='either')
AssertionError: False is not true : either: either_proof.lean:5517:8:
    error: (kernel) excessive memory consumption detected
FAIL: … (program='both')
FAIL: … (program='short_and')
FAIL: … (program='short_or')
```

`either` is `formal/examples/either.mojo` verbatim:

```python
def either(n):
    if n > 10 or n == 0:
        return 1
    else:
        return 0
```

and `bugs/sweeps/proof_breadth_2026-10-03.jsonl` records that file as
`{"ident": "examples/either.mojo", "arch": "arm64", "cls": "pass",
"n_sorries": 0}`. **So this is a regression against the 2026-10-03 census,
not a long-standing red**, and the eight generator-level tests in the same
file (`test_cond_nodes_agrees_with_collect_conds`,
`test_condition_pairing_filters_on_the_recorded_branch`, …) all pass — the
model, the branch pairing and the step lemmas are all fine. Only Lean's
kernel gives up.

**The census row is not evidence that it ever checked**, and that is worth
saying before anything else: it records `"wall_s": 0.1`, which is
`formal/lean.py`'s verdict-cache HIT and not a run. So "it passed on
2026-10-03" is a recorded verdict, and what regressed is unmeasured.

## 1. It reproduces, byte for byte, on this tree

```console
$ python3 tools/memslot.py --gb 8 --label pg -- \
      python3 fire.py build --formal -o .tmp/scc/either.proof .tmp/scc/either.mojo
build: proof check failed: either_proof.lean:5517:8: error:
  (kernel) excessive memory consumption detected
memcap: done, peak 7.6 GB across up to 2 procs (ceiling 8.0 GB), child exit 1
```

and standalone through `formal/lean.py::run_lean`, which is how every
measurement below was taken (`-j 4 -M 6144 -T 200000`, the launcher's own
bounds):

| the generated file | wall | CPU | peak RSS | verdict |
|---|---|---|---|---|
| as emitted (688 017 B, 7259 lines) | 208.8 s | 250.2 s | 8.00 GB | `either_proof.lean:5517:8: (kernel) excessive memory consumption detected` |

`either_proof.lean` is 16 `sorry`s, every one a named trust boundary, so the
hole count is not what is being complained about.

## 2. The bisection, and it refutes all three of this doc's options

Every row is the SAME generated file with one edit, run through
`formal/lean.py::run_lean`. **Only `rc=0` counts as cheap**: an edit that
introduces a syntax error makes the file look cheap because elaboration
aborts at the error, and two of the rows below were nearly mistaken for fixes
for exactly that reason before the error was read.

| the file | wall | peak RSS | verdict |
|---|---|---|---|
| as emitted | 208.8 s | 8.00 GB | the ceiling error |
| **`-M 100000000` (the ceiling lifted)** | — | **> 8.00 GB, killed by `memcap`** | the ceiling error is the bound doing its job |
| `blocks := []` in the record | 248.8 s | 8.03 GB | **the same error at the same line** |
| `fuel := fun _ => 0` in the record | 22.9 s | 2.51 GB | cheap — **but** the terminal `change` then fails, so the rest of the theorem is never elaborated (a false cheap, see below) |
| record's fuel as a named `def`/`abbrev` | 197–201 s | 7.88–8.05 GB | no better |
| **truncated immediately after `def either_prog : Prog := …`** | **21.0 s** | **2.51 GB** | **`rc=0` — it checks** |
| **`native_decide`/`bv_decide` (44 sites) replaced, body otherwise untouched** | 409.7 s | **2.82 GB** | the ceiling error is GONE; two `maxHeartbeats 20000000` timeouts instead |

Three things follow, and they are the whole of what is now known:

1. **The `Prog` record is not the cost.** The file up to and including
   `def either_prog : Prog := …` — the record, its seven `Block`s, their
   certificates, the code, the decode and step lemmas, and every
   `native_decide` run test — **checks clean in 21.0 s at 2.51 GB.** So
   option 2 of §4 of the old version of this doc ("shrink the `Prog` record",
   "`fuel := fun n => …` is a function inside a structure the kernel has to
   compare for conversion") is refuted by a measurement, not by an argument.
   Two of its variants looked like fixes for an hour: they are cheap only
   because a `change` failure aborts the theorem before the expensive part.
2. **The ceiling is not too small.** With `-M` lifted the same file crosses
   **8 GB of RSS** and is killed. Raising `LEAN_MEMORY_MB`
   (`formal/lean.py`) converts a loud rejection into the memory debt
   `bugs/PERF_memory_over_4gb_is_a_bug.md` is about. The doc's option 1 was
   the wrong lever and this is the measurement that says so.
3. **The memory is `native_decide` and `bv_decide`, in the theorem body.**
   The universal theorem's body — everything after the record — carries 16
   bare `native_decide` and 28 `bv_decide` sites, all of them in the
   per-block branch-condition facts (`by_cases h : <flag> <;> simp [h, …]
   <;> bv_decide`, `simp only […] ; simp […] ; native_decide ; all_goals try
   bv_decide ; all_goals try grind ; …`). Replacing those 44 sites drops the
   peak from 7.95 GB to **2.82 GB** and the ceiling error with it. The price
   is wall time (409.7 s) and two heartbeat timeouts, which is the shape of a
   cheap-but-incomplete recipe rather than of a cheap proof.

**And that is why exactly these four programs are red.** `either`, `both`,
`short_and` and `short_or` are the four short-circuit examples. A short-circuit
condition emits its own conditional branch (`_emit_truthy_word`), and the
merge block's condition register holds the LEFT operand's `cset` on the taken
edge and the RIGHT one's on the fallthrough — so the ordinary
`arm64_flag_*` facts do not apply and the generator's fallback chain has to
reach for a decision procedure. A straight-line `if` closes on `simp`;
these four do not.

## 3. The fix direction

**A lemma for a short-circuit condition's value flow, not a cheaper decision
procedure.** The generator already knows the shape — `_sc_by_merge` in
`_gen_universal_e2e_cfg` records, per merge block, the chain's kind (`and` /
`or`), the two operands rendered as `_truth_go` would, and the chain's own
branch pc — and it already refuses to attribute one proposition per block
where one is wrong ("one proposition per block cannot describe it"). What it
does not have is the FACT that would let a branch-condition leaf close on
`simp`: for each of the two edges into the merge block, *which* operand's
truth value the merge register holds, so that

```
arm64_reg r (merge_state edge) = 0 ↔ ¬(left)     -- on the short-circuit edge
arm64_reg r (merge_state edge) = 0 ↔ ¬(right)    -- on the fallthrough
```

are two ordinary `simp`-dischargeable `Arm64State` facts about two
concrete states, each of which the block's own `qS`/`qT` chain already names.
With those, the `by_cases` + `simp` + `bv_decide` + `grind` +
`native_decide` chain in `_CBZ`'s emitter has nothing left to decide, and
neither the memory nor the wall time goes with it.

The measurement that says this is the right shape and not a hope: the same
file with those 44 sites removed elaborates in 2.82 GB, i.e. the DECISION
PROCEDURES are the cost and nothing else in the body is. Two `sorry`s are
already admitted at this construct and are named trust boundaries; this is not
about those.

While that lands, the two `either`-class facts below are worth doing because
they are cheap and they are what a reader hits first:

* the verdict cache made a red invisible as a `wall_s: 0.1` row in a census
  file, so a proof regression of this size can be recorded as a pass. A proof
  that no longer checks should not be replayed from the cache — see §5.

## 4. What has been changed, and what has not

**Landed** (partial, and it is NOT the fix): the per-block step budget is now
ONE `Nat` subtraction against its base instead of a nested chain.
`emit_block` used to thread the fuel as a string and concatenate `- k` onto
whatever it was given, so `either`'s proof spelled
`(((FUEL - 8) - 1) - 3) - 2) …` — 15 terms deep — **298 times**, at every
`have`, every `rw [show … = … from by omega]` and every library call. It is
now `FUEL - 42`, once. `(x - a) - b` and `x - (a + b)` are the same `Nat`
value, so this changes what is emitted and not what it means, and `FUEL0`
deliberately stays INLINE: `omega` reads its `200000` literal to prove every
fuel obligation, and naming it hides the literal (measured: with the record's
fuel named, `arm64_go_exit_hit`'s `0 < fuel` is the first thing that goes
unproved). Verified on `formal/examples/const2.mojo` and `chain.mojo`
(build + proof check, both green). **This is emitter hygiene, not the fix:
`either` still fails identically, and the measurement in §2 row 1 is with the
chains already folded.**

**Tried and refuted, so a reader does not try them again:**

* `set_option maxMemory` in the generated preamble, or a bigger
  `LEAN_MEMORY_MB`. There is no `set_option maxMemory` in the preamble
  because the ceiling is imposed on the command line by
  `formal/lean.py::lean_flags` (`-M 6144`); adding a `set_option` would not
  change the bound that fires. Raising the bound moves 8 GB of RSS into the
  gate.
* naming the record's `fuel` field (`def`, then `abbrev`). No better at
  197–201 s / 7.9–8.1 GB, and it costs two things: `change` sees through a
  `def` only at `.reducible` transparency, so the terminal `change` fails
  with it, and `omega` does not unfold a reducible constant either, so the
  fuel obligations fail.
* `blocks := []` in the record: the error is unchanged, at the same line.

## 6. §3's lemma, built and measured: the per-block fact is one block WIDE, and
## `hprior_*` cannot be widened to cover what is missing (2026-10-05)

§3 says the missing thing is "a lemma for a short-circuit condition's value
flow … for each of the two edges into the merge block, *which* operand's truth
value the merge register holds". **The closest existing machinery is
`hprior_*`** — a fact per (path, prior block, variable) that
`(s_{pb}).x<reg> = <variable>`, proved by unfolding that ONE block's chain and
referencing the previous block's fact. So the experiment was: **give `hcond` the
same treatment** — for a merge block whose cset is in a PRIOR block, unfold only
that block's chain plus the `hprior_*` names, instead of the whole path prefix.
That is `_cs_defs` in `formal/arm64_proof_gen.py`'s `hcond` emitter, and it was
changed and measured and then **withdrawn**, for the reason below.

| the emitted `either` proof, arm64 | wall | peak RSS | verdict |
|---|---|---|---|
| as emitted (`_cs_defs` = the whole `flow_hsid` prefix) | 304 s | **6.10 GB** | `rc=0` through `run_lean`; `(kernel) excessive memory consumption detected` run twice by invoking `lean` directly on the same bytes — **the file is over `-M 6144` and the verdict is a coin flip** |
| `_cs_defs` = `hsid_{cset_bi}` + that block's `qS`/`qT` + `hprior_*` | 239 s | **3.52 GB** | **`rc=1`: 12 `bv_decide` counterexamples, one per `_cset_bi != bi` goal** |

**The narrowing is worth 2.6 GB and does not close, and the reason is a
specific register class.** All twelve failures are the same shape and the
message names the expressions `bv_decide` could not see:

```
- It abstracted the following unsupported expressions as opaque variables:
  [arm64_reg 0 {…}, arm64_reg 16 {…},
   mem_read_u64 (mem_write_u64 (mem_write_u64 mem✝² (sp✝² - 16).toNat n) …),
   arm64_matches_condition 2 nzcv✝²]
```

`arm64_reg 16` is the register the **literal `10`** was materialised into
(`mov x16, #10`, in the block before the one holding the cset), and
`nzcv✝²` is the flags the cset's own `subs`/`cmp` read. **Neither is a named
VARIABLE, so `hprior_*` reaches neither** — that table's loop is
`for _v in _vars if re.search(rf"\b{_v}\b", _src)`, i.e. it is keyed on the
variable names that appear in the SOURCE CONDITION, and a comparison operand
that has been lowered to a register, and a flag field, are not among them. With
the prefix unfolded, both reduce (`arm64_reg 16 s_0` becomes `10` by
`Arm64State.init`); with only `_cset_bi` unfolded, `s_0` is an opaque local and
they do not.

### The exact next step, and it is one predicate

**Extend the per-block fact from "a variable's register" to "every register and
flag the block's OWN chain reads".** The emitter has both halves:

* the chain's read set — `_cset_registers` is already the write-set reader for
  one instruction, and the operand registers of a `cmp`/`subs` are decodable
  from the same word;
* the value — for a register whose last writer on this path is an immediate
  store, the value is a literal, and `(s_{pb}).x<r> = K` is provable by
  unfolding that one block. That is the base case the induction needs, and
  `nzcv` is the same fact for the flag field.

Then `hcond`'s prefix disappears and §2's memory measurement has nothing left to
carry. **What this does NOT do:** it is a backward slice, so its size is a
function of how far the operand's chain reaches back — on a program whose
condition reads a value a CALL produced, the slice is the call, and the flag
this doc's §2 measured (`native_decide` over a symbolic `n`) is still there.
That is the same wall `FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`
owns, and this section does not claim to clear it.

**Not landed, and the reason is verification rather than the change.** The
narrowing above was written and measured and withdrawn because it does not close;
the predicate that would make it close is a dataflow addition to a 12 000-line
emitter, and each iteration of it costs a 4–5 minute `run_lean` per program
(`formal/lean.py`'s own bounds) plus the same on the x86-64 side, which has no
`_sc_by_merge` at all and therefore has no shared code to fix. That is not a
light worker's change.

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 -c "import sys; sys.path.insert(0,'.'); from formal import monomorph" #noop
$ python3 tools/memslot.py --gb 8 --label t -- python3 .tmp/pg/emit.py \
      formal/examples/either.mojo .tmp/pg/either.aout arm64   # proof text, no Lean
$ python3 tools/memslot.py --gb 8 --label pg -- python3 -c "
import sys,os; sys.path.insert(0,'.')
from formal import lean as L
env=dict(os.environ); env['LEAN_PATH']=os.path.join(os.getcwd(),'lib')
r=L.run_lean(L.find_lean(), ['.tmp/pg/either_proof.lean'], env=env)
print('rc',r.returncode,'wall',round(r.wall_s,1),'peak',round(r.peak_rss/2**30,2))"
rc 0 wall 304.0 peak 6.1
$ grep -n "_cs_defs = " formal/arm64_proof_gen.py          # the line to narrow
$ grep -n "for _v in _vars" formal/arm64_proof_gen.py       # the table to widen
```

## 5. A thing the census got wrong: FIXED 2026-10-04, and it is in this doc
## because it is how the regression above stayed invisible

`bugs/sweeps/proof_breadth_2026-10-03.jsonl` records `either` as
`{"cls": "pass", "wall_s": 0.1}`. `0.1 s` is `formal/lean.py`'s verdict-cache
HIT and not a run, so the file was never checked on that date — and a proof
regression this size was recorded as coverage. "The corpus still measures this
construct" is the claim `tools/formal_fuzz.py`'s `KNOWN_DIVERGENCES`
discipline rests on, and a replayed verdict does not support it.

**Landed.** `tools/formal_proof_breadth.py`'s `Verdict` carries a `cached`
field, `run_item` stops discarding `check_proof_cached`'s third element, the
ledger has a `cached` column, a replayed PASS prints on the screen (it used to
be the only row of a run with nothing on it), and the per-architecture summary
prints `of which replayed` so the counts cannot be read as a fresh measurement
without opening the ledger. It is a FIELD and not a distinct `cls` because
`pass`/`admitted` say what the PROOF is and every reader here aggregates on
that, while "measured or replayed" is a second axis of the same row.

`test_formal_proof_breadth.py::TestAReplayedVerdictSaysSo` pins it with the
cache stubbed, which is the only way to test it deterministically: the two rows
must carry the same class and opposite flags, and the summary must count the
replayed one.

**…and the same commit left that file's OTHER case red, which is repaired
2026-10-04 (`work/formal23-1`).** `Verdict` grew a ninth field, and
`test_the_report_says_when_the_two_architectures_mean_different_things`
constructs eight `Verdict`s positionally without it, so the case raised
`TypeError: Verdict.__new__() missing 1 required positional argument: 'cached'`
on every run — `Ran 16 tests … FAILED (errors=1)`, for a file that is the
instrument this very section landed. Worth recording because it is the shape
CLAUDE.md's `expect=` discipline exists to catch and this one slipped past it:
**a new field on a record a test constructs by hand is a red in the test that
constructs it**, and the fix is eight `False`s, one per row, because none of those
rows is a replayed verdict. `python3 test_formal_proof_breadth.py` is `OK` again
(16 tests).

**What this does NOT do:** it does not make a replayed verdict fail, and it
does not re-check `either`. `either` is still red for the reason in §1, and the
measurement that says so is a fresh run with `cached=False` in the ledger.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
mkdir -p .tmp/scc && cat > .tmp/scc/either.mojo <<'EOF'
def either(n):
    if n > 10 or n == 0:
        return 1
    else:
        return 0
EOF
python3 tools/memslot.py --gb 8 --label pg -- \
  python3 fire.py build --formal -o .tmp/scc/either.proof .tmp/scc/either.mojo
# build: proof check failed: either_proof.lean:5517:8: error:
#   (kernel) excessive memory consumption detected
```

and the bisection, which is the part a taker should redo rather than trust:

```sh
# .tmp/scc/probe2.py: run_lean(lean, [src]) with LEAN_PATH=lib, printing
# rc/wall/peak and the FIRST error lines (never the last 1200 chars).
python3 - <<'EOF'
s = open('.tmp/scc/either_proof.lean').read()
i = s.index('theorem either_compiles_correctly_universal')
open('.tmp/scc/t1.lean', 'w').write(s[:i])      # → rc=0, 21.0 s, 2.51 GB
body = s[i:]
body = body.replace('bv_decide', 'simp_all') \
            .replace('\n            native_decide\n', '\n            sorry\n')
open('.tmp/scc/noNat.lean', 'w').write(s[:i] + body)   # → 2.82 GB, no ceiling error
EOF
```

`formal/examples/both.mojo`, `short_and.mojo` and `short_or.mojo` are the
other three, and every number above holds for the one that was measured.
