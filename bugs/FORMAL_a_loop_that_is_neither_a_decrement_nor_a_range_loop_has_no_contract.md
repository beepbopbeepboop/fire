# FORMAL_a_loop_that_is_neither_a_decrement_nor_a_range_loop_has_no_contract: 8 of the 44 examples added to `formal/examples` on 2026-10-05, and the model it used to emit for them was a diverging `partial def`

**Area:** FORMAL (the proof layer's source→Lean model fold, shared by both
backends) · **found by** growing `formal/examples` from 52 programs to 96 and
running the new ones through `tools/formal_proof_census.py` · **both
architectures**, because `formal/x86_64_proof_gen.py` shares the fold
(`_go_defs_for`) · **filed 2026-10-05, the diverging-model half FIXED in the same
commit, the missing contract NOT fixed** — see §"What landed" and §"What is
still open".

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
it is the same shape as `bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`,
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

**The oracle for any of this is a proof, so it needs the formal suite behind it**
— the same sentence `bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`
carries for the same reason. The cheap half (the refusal, the fold's
completeness, the byte-identity over the corpus) is done and pinned above.
