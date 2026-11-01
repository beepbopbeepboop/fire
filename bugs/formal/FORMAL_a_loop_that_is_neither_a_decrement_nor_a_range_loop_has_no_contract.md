# FORMAL_a_loop_that_is_neither_a_decrement_nor_a_range_loop_has_no_contract: 8 of the 44 examples added to `formal/examples` on 2026-10-05, and the model it used to emit for them was a diverging `partial def`

**Area:** FORMAL (the proof layer's source→Lean model fold, shared by both
backends) · **found by** growing `formal/examples` from 52 programs to 96 and
running the new ones through `tools/formal_proof_census.py` · **both
architectures**, because `formal/x86_64_proof_gen.py` shares the fold
(`_go_defs_for`) · **filed 2026-10-05, the diverging-model half FIXED in the same
commit, the missing contract NOT fixed** — re-measured 2026-10-05, census
unchanged, and §"Re-measured" names the library half — see §"What landed" and
§"What is still open".

## What I ran

    # the frontier, one example at a time, no Lean (seconds):
    python3 tools/memslot.py --gb 8 --label proveprobe -- \
      python3 .tmp/proveprobe.py formal/examples

    # and the artifact the fold emitted for one of them, on x86-64:
    python3 tools/memslot.py --gb 8 --label x86p -- python3 -c "
    import sys; sys.path.insert(0,'.')
    import formal.build as B
    r = B.compile_formal('formal/examples/accum_max.mojo', output='.tmp/y.aout',
                         prove=True, check=True, test_input=10, arch='x86_64')
    print(r['proof_path'])"

from

```python
def accum_max(n):
    i = 0
    best = 0
    while i != n:
        if i > best:
            best = i
        i = i + 1
    return best
```

## What I saw

**The model's loop state is ONE word, and the fold said so by emitting a
definition that does not terminate.** `_stmts_go`'s `WhileStmt` arm
(`formal/arm64_proof_gen.py`) emits

```lean
partial def accum_max_go_loop_0 (n_0 : UInt64) : UInt64 :=
  (if ((UInt64.ofNat 1) ≠ n_0) then accum_max_go_loop_0 (n_0) else (UInt64.ofNat 0))
```

`n_0` is the entry PARAMETER, and this loop's induction variable is `i`, so the
recursion passes its own argument unchanged and the definition **diverges on
every input that enters the loop**. It is emitted as `mojo`, the function every
other theorem in the file is about.

The x86-64 generator then wrote its run test over it:

```lean
theorem accum_max_runs_10 : accum_max_result 10 = mojo 10 := by
  native_decide
```

`accum_max_result 10` is 9 (the machine's answer, verified by running the
image) and `mojo 10` diverges, so **that obligation is false**. `native_decide`
does not report a false obligation — it runs the interpreter until
`formal/lean.py`'s bound kills the run. Measured: **7+ minutes with no verdict**
(against 2–3 s for the sibling proofs), i.e. a `bound-exceeded` row, which is
the *absence* of a measurement rather than a finding about the proof.

**arm64 never got that far** — its `eval_eq_mojo` gate refuses a `while` that is
not `_dec_while_pattern` first — so the defect was invisible on the mature
backend and live on the other one.

**The refusal the fold should have made, for eight corpus programs.** With the
loop state named, the census says which programs are on the wrong side of it:

| example | the loop | census status (arm64, 2026-10-05) |
|---|---|---|
| `accum_max` | running maximum, induction variable is a local | `refused` |
| `while_ne_zero` | `while i != 0: total += i; i = i - 1` | `refused` |
| `var_typed_loop` | a `var` declared and read inside the body | `refused` |
| `ret_in_loop` | a `return` from inside the body | `refused` |
| `loop_break` | a `break` out of the body | `refused` |
| `nested_loop` | two nested `while` loops | `refused` |
| `digits` | a divide/modify pair per iteration | `refused` |
| `for_two_bounds` | a `for i in range(1, n)` | `refused` (`ForStmt needs the generic loop contract`) |

Eight of the 44 added examples, and **the 52-example corpus had exactly one
loop that could be stated at all** (`wdiff`, plus `countdown`/`wge`, which are
`_dec_while_pattern`'s three spellings). So the class was 1-in-52 before and is
8-in-96 now, and nothing measured it: every program that reached it was either
the one shape the fold could state or absent.

## What I expected

A refusal. The fold knows it is carrying one word — it built the helper with one
parameter — so a loop whose body changes any other name, or whose body is not a
straight-line run of bindings, is a loop it cannot state, and the file's own
policy is to refuse rather than fabricate ("refusing rather than modelling it as
0, which would be a false statement about the source", said at every other site
in the same function).

## What landed

**The refusal, in the same fold, in both directions** (`formal/arm64_proof_gen.py`,
`_stmts_go`'s `WhileStmt` arm):

* a body that changes a name the single loop argument cannot carry → refused,
  with the names in the message;
* a body that is not a straight-line run of bindings (an `if`, a `break`, a
  `return`) → refused, with the statement shapes in the message — this is the
  half that catches `accum_max`, whose `best = i` is inside an `if` and so is
  not even a binding the fold can see;
* **the loop-body binder now goes through `_bind_one`**, so `var x = e` and
  `x += e` bind inside a loop body exactly as `x = e` does. That fold was the
  FIFTH copy of "an assignment binds this name", and the copies had diverged by
  being incomplete (`_bind_one`'s own docstring names two of the others). It
  cost one false refusal — `var_typed_loop` was told "`step` is read here and
  this generator binds it to nothing", which was false about the source — and
  that refusal is what the first corpus example with a `var` in a loop body
  found.

**Measured after:** the x86-64 proof of `accum_max` **3 s** (was 7+ minutes with
no verdict), carrying a PLACEHOLDER model that states the gap and **omits the
run tests** rather than stating a false one — `x86_64_proof_gen`'s own
fallback, which is what the refusal is for. The three loops the fold CAN state
are unchanged: all 96 examples' generated proofs are byte-identical before and
after (`sha256` over every `<stem>_proof.lean`, 96/96).

Pinned by `test_formal_call_proof_gen.py::TestALoopTheModelCannotStateIsRefusedNotModelled`
(four cases, Lean-free, 0.2 s) and
`::TestTheLoopBodyBindsEveryAssignmentSpelling` (three, same).

## One candidate that was measured and dropped

`call_in_loop` (a `twice(total) + 1` accumulator whose body CALLS) generated a
proof, and the proof was **rejected with 806 s of Lean CPU and a 2.2 GB peak** —
3.8x the most expensive proof in the corpus (`sqsum`, 219 s CPU) and past
`test_formal.py`'s 900 s per-example build timeout on a loaded machine. It is
therefore NOT in `formal/examples`: a corpus member has to be checkable inside
the suite's per-example budget, and a row whose cost is a quarter of the
`formal` job's whole timeout is a row that makes the job flaky rather than
informative. The example is in `formal/examples/call_in_loop.mojo` in the
branch this doc was filed from, and the number is the finding: **the run test
executes the image through the machine model, so a loop in the image makes the
`native_decide` obligation superlinear in the trip count** — which is a cost
fact about the run tests, not about the loop contract.

### `if_not`, measured and dropped for the same reason

`if_not` is `if not (n == 3): return 1` / `return 0` — 3017 lines of proof, ONE
condition, nothing like `call_in_loop`'s loop. It ran **20+ minutes and 5.7 GB**
on a loaded machine against `cmp_ne`'s 53 s and 2.2 GB for the same shape
spelled with `!=`, and was on its way to Lean's own `-M 6144` ceiling. It is
also out of the corpus for the same reason, and the finding is sharper than the
one above: **the cost is in the `not`, not in the program.** `n != 4` is one
conditional branch whose condition the `by_cases` hypothesis decides; `not (n
== 4)` puts a negation in the model's `if`, and `simp_all +decide` over a
negated test is where the time goes. A `not` is the third control-flow
primitive in this corpus (`n > 0`, `a and b`, `not a`) and it is the one whose
proof cost is not visible in the program's size.

### `shift_right_neg`, measured and dropped for a third reason

`shift_right_neg` is `a = 0 - 8; b = a >> 2` and a compare against `0 - 2` —
an ARITHMETIC shift of a negative, i.e. the one shift whose result the
signedness decides. It generated a proof and Lean **refused it on its own
memory ceiling**: `(kernel) excessive memory consumption detected` at a 6.0 GB
peak (`formal/lean.py`'s `-M 6144`). That is `too-large`, which the census is
explicit about is *the absence of a measurement* rather than a verdict — so it
is not a row worth banking, and at 6.0 GB it is above the corpus's whole
documented band (1.5-3.0 GB per `tools/suite.py`'s `formal` registration, with
`sqsum`'s 4.40 GB the previous maximum). The signedness of a shift is covered
by `sign`, `n8`, `sgt8` and `sle8`; this example asked for a fourth row about it
and the checker said no.

### `bool_chain`, measured and dropped: 4.2 GB

`bool_chain` is `if n > 0 and n < 100 and n != 50: return 1` — a THREE-operand
short-circuit chain, the largest `by_cases` in the corpus (3 conditions → 8
cases, each carrying the whole model). Its proof is 6426 lines, which is not the
problem: it ran **9+ minutes at a 4.2 GB RSS** against 53 s / 2.2 GB for
`cmp_ne`'s single comparison, and it was still climbing. `formal/lean.py`'s
ceiling is `-M 6144` and the `formal` job's whole tree is capped at 8 GB, so a
4.2 GB member is not a member.

The two-operand shapes stay (`not_and` proves nothing yet costs 147 s / 3.15 GB,
`loop_and` and `loop_or` are refused for the loop contract), so the corpus keeps
the short-circuit coverage; what it does not keep is a chain whose proof cost is
not visible in the program. **The cost is the number of `by_cases`
hypotheses, not the number of lines** — that is the transferable finding, and
it is the same shape as `bugs/formal/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`,
which measured the same growth for a different reason.

## What is still open, and the exact next step

**The contract itself.** `_dec_while_pattern` and `_range_loop_pattern` are the
only two loop shapes the model can state, and between them they cover "a counter
that is the parameter" and "a range loop with one accumulator". Everything a real
program writes — a running total, an early exit, a nested loop, a `break` — is
outside both.

The next step is the loop's STATE, not its proof. The model is
`mojo : UInt64 → UInt64`, so a loop has to be a function of one word; the way to
give it more is the way `u64pow` already does it for the multiplication in
`formal/admitted.py`: an ADMITTED intermediate. Concretely, `while_ne_zero` is
the smallest program that wants one accumulator:

```python
def while_ne_zero(n):
    i = n
    total = 0
    while i != 0:
        total += i
        i = i - 1
    return total
```

Model `total` as a second `partial def` parameter threaded the way `n_0` is
(`{helper} (total') (i')` with `total'` the folded `total + i'`), which is a
change to ONE helper's signature and to the two sites that build it — and it
buys seven of the eight rows above, because `accum_max`, `ret_in_loop`,
`var_typed_loop` and `loop_break` differ from it only in what happens after the
update. `nested_loop` needs two, and `for_two_bounds` needs the induction
variable to be the range counter rather than the parameter, so it is the last of
the eight and not the first.

## Re-measured 2026-10-05: the census is unchanged, and the `u64pow` precedent is a `lib/` definition

This round was given the doc and did not land the contract — the next step is a
second accumulator in the loop model, which is a `lib/ProofLib.lean` theorem plus
a change to the helper's signature, and the brief allows no Lean run beyond the
one test covering a change. **So this is a measurement, not a fix.** It confirms
the census and names one thing §"The next step" left implicit.

**The census is exactly as §"What I saw" recorded it.** Asking the two patterns
directly over every `formal/examples/*.mojo` (no build, no Lean):

```
dec_while  (3): countdown.mojo, wdiff.mojo, wge.mojo
range_loop (1): sum_range.mojo
neither    (98), of which seven contain a `while`:
            accum_max, digits, loop_break, nested_loop,
            ret_in_loop, var_typed_loop, while_ne_zero
```

So between them the two patterns still cover four programs, and the seven that
want an accumulator are still outside both — the shape §"What I saw" described,
unchanged.

**The `u64pow` precedent is a LIBRARY change, not a generator change, and that
is the part worth being explicit about.** §"The next step" says to model `total`
"the way `u64pow` already does it", and it is worth being exact about where that
precedent lives:

```
$ grep -n u64pow lib/ProofLib.lean formal/*.py
lib/ProofLib.lean:930:def u64powGo (base exp acc : UInt64) (fuel : Nat) : UInt64 :=
lib/ProofLib.lean:939:def u64pow (base exp : UInt64) : UInt64 := u64powGo base exp 1 64
lib/ProofLib.lean:1111:  | MojoExpr.binop "**" l r => u64pow (evalExpr callFunc l env) ...
formal/x86_64_proof_gen.py:234:  "u64pow", "u64powGo", "sKey"] + ...
```

`u64pow` is a hand-written `lib/ProofLib.lean` definition, and the generator only
NAMES it in its `simp` set. So "model `total` as a second parameter the way
`u64pow` does" means **a new `lib/ProofLib.lean` definition plus its equation
theorem**, not a change to `_stmts_go` alone — which makes §"The next step" a
two-part job in the same way the range-loop fix's `arm64_slt_iff_lt` was, and for
the same reason: the statement has to be right in Lean before the generator half
is worth writing.

**What §"The next step" gets right, and it is the reason this is not simply
"write the induction":** the loop is a function of ONE WORD in this model, so
adding an accumulator is not a proof but a change to what the model IS. The
generator emits `partial def <fn>_go_loop_0 (n_0 : UInt64) : UInt64`, and a
second state word means a second parameter, which means every `loop_model`,
`loop_body_model`, `loop_exit_x0` and the `_ltb_loop` fuel are restated. The
seven programs it would buy are worth it; the change is a library contract and a
generator signature together, and it wants its own negative control — a loop
whose accumulator is deliberately wrong must make the induction FAIL rather than
merely elaborate, which is the same requirement §"The next step" states for the
specification layer and for the same reason.

**The oracle for any of this is a proof, so it needs the formal suite behind it**
— the same sentence `bugs/formal/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`
carries for the same reason. The cheap half (the refusal, the fold's
completeness, the byte-identity over the corpus) is done and pinned above.

## Re-measured 2026-10-28: the two-word contract landed in the shared fold; two of the eight rows are now stated, five are refused by name, one is unchanged

The next step above landed, in the minimal form it prescribes: "`total` as a
second `partial def` parameter threaded the way `n_0` is, a change to ONE
helper's signature and to the two sites that build it". The change is in
`_stmts_go`'s `WhileStmt` arm of `formal/arm64_proof_gen.py`, which both
backends share through `_go_defs_for`. There is NO `lib/ProofLib.lean` change:
the helper is a generated `partial def` inside the proof file, and on x86-64
the stated model is what the file's own typecheck and a direct model-evaluation
probe check, so the library equation-theorem half that §"Re-measured 2026-10-05"
flagged did not land with this round.

**What the fold now states.** A loop's state is at most TWO words: the
induction variable, the word the condition counts down to its exit, and, when
the body changes a second word, that word, the accumulator. The helper takes
one or two arguments, in the doc's order `(a_0) (n_0)` (the accumulator FIRST),
and the condition, the recursion and the exit are all evaluated in an
environment that binds the state words to the helper's own arguments, so at the
back edge every read is the value at THIS iteration. The entry app passes the
entry values, the way the one-word helper passed `n`. One more guard, applied
to both the one-word and the two-word paths: a loop helper is a top-level `def`
that PRECEDES the entry's own definition, so a read of a name the loop does not
thread as a state word (a condition like `i < n`) would splice the entry's
binder into the helper's body, where it is not in scope, and Lean would reject
the file at a line that does not name the loop; that read is refused by name
before it is emitted.

The one-word output is byte-for-byte what this arm has always emitted, so the
old corpus does not move: over the 93-stem x86-64 corpus probe (generation with
Lean, serial), exactly seven stems changed — the loop stems below — and 86 are
byte-identical before and after; the five placeholder stems differ only in the
NOTE that quotes the new refusal.

**The census moves two rows, not the seven the doc predicted.** Measured on
this tree (x86-64, `compile_formal(prove=True, check=True)`):

| example | status after this round |
|---|---|
| `while_ne_zero` | **STATED**: `partial def while_ne_zero_go_loop_0 (a_0) (n_0)` with the recursion `((a_0 + n_0)) ((n_0 - 1))`; the proof typechecks in 5.4 s, the model probe `mojo 10 = 55` closes by `native_decide`, and the image exits 55 |
| `digits` | **STATED**: `(a_0 + 1) (fdiv64 n_0 10)`; the proof typechecks |
| `accum_max`, `ret_in_loop`, `loop_break`, `nested_loop` | refused: the body is not a straight-line run of bindings (`IfStmt` / `Return` / `Break` / `WhileStmt` in the body), so the fold cannot compute the next value of the state |
| `var_typed_loop` | refused: the state is THREE words (`step`, `total`, `i`) and the helper carries at most two |
| `for_two_bounds` | unchanged: `ForStmt needs the generic loop contract` |

The doc said the second parameter "buys seven of the eight rows above, because
`accum_max`, `ret_in_loop`, `var_typed_loop` and `loop_break` differ from it
only in what happens after the update". That measured as TWO: those four differ
from `while_ne_zero` in what happens INSIDE the body, and the body is where the
two-word fold stops — a branch it cannot follow has no next state to thread.

**arm64 for the two stated rows is now a DIFFERENT gate.** The model generates
on arm64 too; what arm64 then refuses is the `eval_eq_mojo` bridge: "function
shape (recursive/while with AST eval) unsupported". `MojoStmt` in
`lib/ProofLib.lean` HAS a `while` form, but the bridge's proof cannot close it,
so arm64 stays red for `while_ne_zero` and `digits` (KNOWN-GAP; the arm64
entries in `test_formal.py`'s EXPECTED_FAILURES name this gate) — the permanent
arm64 obstacle for stated loops is now the bridge, not the model. And the
x86-64 run tests that would check the stated model against the machine are
suppressed tree-wide in this tree by the image's runtime stubs (`snprintf`,
`strtod` — the `NO RUN TESTS` note, pre-existing and not this round's change),
so the x86-64 oracle here is the stated model plus the file's typecheck, plus
the direct model-evaluation probe above.

**The negative control this doc required.** A loop whose accumulator threading
is deliberately wrong must make the statement FAIL rather than merely
elaborate, and it does: corrupting `while_ne_zero`'s recursion to pass
`(a_0 + (UInt64.ofNat 1))` instead of `(a_0 + n_0)` makes Lean report
"error: Tactic `native_decide` evaluated that the proposition mojo 10 = 55 is
false".

**Pinned** (Lean-free): `test_formal_call_proof_gen.py::TestALoopTheModelCannotStateIsRefusedNotModelled`
now carries six rows — the one-word real model, the two-word real model, the
shape that x86-64 states and arm64's bridge gate refuses, the leak refusal
naming `n`, the three-word refusal naming `step`, `total`, `i`, and the
straight-line refusal naming `IfStmt` — and
`::TestTheLoopBodyBindsEveryAssignmentSpelling` passes unchanged (its
environments are recorded before any refusal fires); the loop-callee row in
`::TestCallProofs` names the new leak sentence. `test_formal.py`'s arm64
EXPECTED_FAILURES re-states the same seven stems with this round's reasons.

**Still open** — the doc stays: bodies that are not a straight-line run of
bindings (`accum_max`, `ret_in_loop`, `loop_break`), a loop inside a loop
(`nested_loop`), a three-word state (`var_typed_loop`), the generic `for`
contract (`for_two_bounds`), and arm64's `eval_eq_mojo` bridge over a stated
loop.
