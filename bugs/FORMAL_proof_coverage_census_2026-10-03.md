# FORMAL_proof_coverage_census_2026-10-03: 60 functions from THIS repository, both backends, with proofs on

**What this measures, and the one number nobody had.** `tools/formal_sweep.py`
covers the *code generator's* language coverage and deliberately builds
`--no-prove`, and says so in its own docstring:

> Proof generation and Lean typechecking are a separate, much narrower
> capability with their own coverage (and their own failures, several of them
> about function *shapes* rather than about anything the code generator could
> lower) — they are exercised by `test_formal.py` / `make check-formal`, not by
> this sweep.

`test_formal.py` exercises it over `formal/examples/*.mojo`: 49 two-to-five-line
programs written *for* this backend. So the proof layer's coverage of **this
repository's own ~300 `.py` files** had never been measured, and a whole file is
the wrong unit for it — a repository file is 500-15000 lines, most of it an
import, so a per-file verdict measures the import graph. This takes the
**function** as the unit, which is the unit `eval_eq_mojo` is actually about.

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label proofbreadth -- \
  python3 tools/formal_proof_breadth.py -j 2 -t 180      # 120 items, ~8 min
```

**Tool:** `tools/formal_proof_breadth.py`. **Ledger:** every verdict, one JSON
line each, at `$TMPDIR/formal_proof_breadth.ledger.jsonl`; the summary this
document quotes is that tool's own. **Machine:** 18 cores, load 13-40; peak
**7.8 GB** across 3 processes against the 8 GB reservation.

## 1. The workload, and why it is 60 functions and not 60 files

15 `formal/examples` programs verbatim (a fixed stride over the sorted stems,
so the choice is reproducible) and 45 functions **extracted from this
repository's own `*.py`**, each emitted as a standalone module together with the
module-level definitions it transitively needs plus a `main` that calls it, and
selected round-robin across files in sorted path order (the largest eligible
function per file, then the next file's). The sample reaches `formal/build.py`,
`formal/lean.py`, `fire_compiler.py`, `gimple_codegen.py`,
`mojo/backend_gimple/*`, `mojo/middle/*`, `cas.py`, `myinterpreter.py` and
`test_ast_formal.py`.

Selection is by **name discipline and nothing else**: every free name a
candidate reads must be a parameter, a local, a builtin, or a module-level
definition of the same file (pulled in verbatim, transitively). A function that
reaches for `os` is not eligible — that is `not-answerable/host-import` in the
sweep's vocabulary, already counted 241 times there, and measuring it again
here would only dilute the classes this census is about. Parameters annotated
with anything but `int` are excluded because the synthesised `main` calls the
function with the startup stub's integer, and a mismatch there would make the
census report a call-site refusal as if it were a statement about the function.
**Nothing is filtered by whether the backend can lower it** — which is the thing
being measured.

## 2. The classes

Two phases, because a Lean run costs ~100x a codegen run: phase A builds with
`prove=True, check=False` (the code generator AND the proof generator run, which
is what separates "the code generator refused" from "the proof generator
refused" without a tactician), and phase B runs the check only where phase A
produced a proof — through `formal/lean.py::run_lean`'s bounds, with the per-item
**wall** bound passed explicitly (`-t 180`) so one slow proof cannot consume the
run. Lean's CPU bound is left at its own default.

| | arm64 | x86-64 |
|---|---|---|
| `pass` — proof typechecks, **zero** holes | **10** | **0** |
| `admitted` — typechecks, admits `sorry` | 1 | **18** |
| `lean-rejected` — Lean did not accept it | 2 | 4 |
| `bound-exceeded` — `run_lean` killed it (**not a verdict**) | 2 | 0 |
| `proof-refused` — the generator refused, by name | 6 | 0 |
| `proof-crash` — the generator RAISED (a bug) | 1 | 0 |
| `codegen-refused` — the code generator refused | 38 | 38 |
| `build-crash` | 0 | 0 |
| **reached Lean at all** | **13** | **22** |
| median wall for one that reached Lean | **20.5 s** | **2.9 s** |

Two facts about the table that are the reason it is not "pass/total":

* **x86-64's hole floor is exactly 2.** All 18 x86-64 proofs that typechecked
  admitted **exactly 2** `sorry`s and not one more. Those two are that
  generator's designed trust boundaries (`<fn>_compile_correct`, and the step
  certificates where a certificate would be false), stated in the header of
  every x86-64 proof this generator writes. So on x86-64 `admitted` means "proved
  modulo the declared boundary, with nothing extra", and **22 of the 22 programs
  that got that far typechecked**. arm64's floor is **0**: 10 of its 11 have no
  hole at all, and the eleventh (`sum_range`, a `for`-range program whose AST
  model has no loop form) has exactly 2.
* **38 of 60 never reach the proof layer**, and they are the *same 38 functions
  with byte-identical refusal messages on both architectures*. The code
  generator's language frontier is one thing, not two — which is the same
  conclusion `…_b7.md` §2.5 reached for the sweep's 668 files, now measured at
  function granularity.

So the proof-layer denominator is 22, and over that denominator: **arm64 11/22
(50 %) produce a proof Lean accepts, x86-64 22/22 (100 %) do.**

## 3. The 38 codegen refusals, by family

These are facts about the code generator, not the proof layer; they are here so
the classes below are read against the right denominator, and because
`…_b7.md`'s ranking is over files while this is over functions.

| n | family | examples |
|---|---|---|
| 9 | a field access through a value (`x.y`) — no frame for a receiver-less struct read | `node.name`, `func_node.name`, `s.params`, `gen.loop_stack`, `body_fd._mojo_coro_body` |
| 7 | a module-level name the module does not declare (`'X' has no home`) | `'re'`, `'gimple_ctypes'`, `'gctypes'`, `'STDLIB_PATH'` |
| 4 | a String method outside the lowered set | `join()`, `rsplit()`, `startswith()` |
| 3 | the image binds a symbol nothing provides | 3 files |
| 3 | a method call on a value receiver | `asm.emit()`, `gen.lower_expr()`, `result.get()` |
| 3 | an arithmetic operator on a string | `'%'`, `'<='` |
| 3 | a NUMBER compared with a string literal | ``op == '*'``, ``k == 'start'``, ``c == 's'`` |
| 2 | `len()` of an integer | `len(vals)`, `len(dflts)` |
| 4 | one each | a construction with arguments where the class has no `__init__`, a module global that has storage read as a value, a subscript whose index is a string |

Every one of these is a refusal with a named reason, which is the shape this
backend uses everywhere: it is the sweep's `codegen` class, at function
granularity, and none of the 38 is a proof-layer fact.

## 4. The 22 that reached the proof layer — the ranked causes

Ranked over **both** architectures (an item that fails the same way on both is
one cause with two symptoms, and the count is items not verdicts):

| items | arch | class | cause | what it is |
|---|---|---|---|---|
| **4** | both | arm64 `proof-refused` / x86-64 `lean-rejected` | **a call to a second function in the same image** | arm64: `universal theorem: the call at 0x… targets 0x…, a second function in the same image … That is interprocedural walking: a return-address map in the framework`. x86-64: no such refusal, so the bridge was emitted and `eval_eq_mojo` came out `⊢ False` at its own line 44 — **the emitted theorem was false**. `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md` (step 2) has the diagnosis. **Fixed on this branch for the x86-64 half** — see §5. |
| 2 | both | arm64 `bound-exceeded` / x86-64 `pass`-equivalent | `pow2`, `sqsum` — dec1 recursion proofs over 180 s | an artifact of **this census's** bound, not a verdict: `wdiff` took 282 s in a verified run on 2026-10-03 (`8d05d94e`). Both typecheck on x86-64 in under 4 s. |
| 2 | arm64 | `lean-rejected` | `count`, `fib` | `fib` is a documented gap (`test_formal.py`'s `EXPECTED_FAILURES`). **`count` is NOT** — it is red on `master` and was green on 2026-10-03 04:44 (`8d05d94e`'s own verification: "arm64 count ok 0 sorry 43.8 s"). §5 and the bug doc. |
| 2 | arm64 | `proof-refused` | `model: a ListExpr / TupleExpr has no value in the semantic model` | `formal/arm64_proof_gen.py::_no_value_model` refusing by name. **The x86-64 generator CATCHES the same refusal and emits its documented placeholder**, so both programs build there with the 2 designed holes — a proof that passes against a placeholder model. Worth its own row: the two architectures degrade differently for the same gap. |
| 2 | both | x86-64 `admitted` | a zero-argument and a two-argument call, same limit as row 1 | arm64 reached the same limit as an `IndexError: list index out of range` out of `_expr_ast` (`e.args[0]` on an empty argument list). **Fixed on this branch** — §5. |
| 1 | arm64 | `proof-crash` | `IndexError: list index out of range` in `_expr_ast` | `cas.py:133 reset_stats` — the zero-argument call of row 5 on arm64, where the machine-half refusal used to be reached first only because `main` also calls a second function. **Fixed on this branch** (§5). |
| 1 | arm64 | `admitted` | `sum_range` | a `for`-range program: the untyped AST model has no loop form, so the bridge is omitted and the machine value flow carries it. Correct and documented in the emitted file. |

## 5. What this branch fixes

Three defects, all in the proof layer, all found by the census rather than by
`test_formal.py` (which covers 49 hand-written programs and shares none of these
shapes with the repository's own code):

1. **`_gen_universal_e2e_cfg`'s call arm emitted a hypothesis that does not
   exist.** The recursion-argument bound cited a literal `hsrc_0`, and no
   `hsrc_0` is ever emitted — so **every** dec1 program with a recursive call
   produced a proof referring to an unknown identifier. The two goals beside it
   unfolded with `hsid_0` + block 0's defs instead of the **path-scoped** set,
   which is correct one block deep and wrong at depth (`s_6` is written in terms
   of `s_4`): `hargeq` was left with an unsolved goal and `hspd` failed with
   "Expected type must not contain free variables", because `native_decide`
   cannot decide a statement mentioning a local. Measured on `count`: **5 error
   sites → 2**, all three of the gone ones being these. The path-scoped set is
   what the sibling goals in the same function already use, so this is one
   definition of "what has to be unfolded here", not a third.
2. **The AST bridge stated a call it cannot state, and the two backends
   disagreed about it.** `_expr_ast`'s `Call` arm rendered `e.args[0]` and
   dropped the rest, and `callFunc` answers **0** for any name but the proved
   function. So a program whose `main` returns a call's value emitted an
   `eval_eq_mojo` that is false: x86-64 reported `⊢ False` on a three-line
   program, and arm64 got there only because its machine half refuses first.
   A zero-argument call did not even get that far — `e.args[0]` raised
   `IndexError` out of the generator. Both are now **refused by name** from one
   shared check (`_ast_bridge_gaps`, one message for both architectures), so
   x86-64 drops the bridge and says why instead of emitting a false theorem, and
   arm64's better message (interprocedural CFG walking) is still the one a
   two-function program gets.
3. **x86-64's omission note described a behaviour the code did not have.** It
   read "calls, prints and method calls have none", while calls were rendered
   and the false theorem reached Lean. The note now quotes the refusal that
   caused it.

**Behaviour preservation, measured:** generating every proof in
`formal/examples` on both architectures before and after, **79 of the 95 emitted
files are byte-identical**; the 16 that changed are the 5 arm64 dec1 programs
(`count`, `fact`, `pow2`, `sqsum`, `sum` — fix 1) and the 11 x86-64 proofs whose
omission note quotes its real reason (fix 3). No example that typechecked before
stopped typechecking: **all 15 sampled x86-64 examples still typecheck at exactly
2 holes** (16 s for the lot).

## 6. What this census did NOT fix, and where it is written down

* **A call to a second function in the same image is still not provable** — 4 of
  22 items, the largest single cause. The limit is one limit with two ends
  (`MojoExpr.call` carries one argument; `callFunc` is unary and is a stub rather
  than the model's function table), and the work is measured, including the Lean
  limitation that blocks the obvious route:
  `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md`. This census adds the
  breadth measurement (4 of 22 items, both architectures) and the observation
  that **no example in `formal/examples` has a call to anything but itself**, which
  is why the whole corpus was blind to it.
* **arm64's remaining two `count` errors**, both about x30 and both the same
  root cause: the code generator now **reloads x30 from the frame** rather than
  leaving it in the register, so the generator's "x30 is unchanged here"
  obligations (`hx30fr_N`, and the x30 conjunct of `FrameOk`) are no longer
  `rfl` — they are true and need the same window-peel reasoning the memory clause
  gets. This is the CLAUDE.md hazard in its exact form: a codegen change
  invisible to the proof generator. `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md`.
* **x86-64's placeholder model.** A `ListExpr`/`TupleExpr` in the source is
  refused by name on arm64 and silently replaced by a documented placeholder on
  x86-64, so an x86-64 proof can pass against a model that is not the source's.
  Not fixed here: it is that generator's designed degradation and changing it is
  a trust-boundary decision, not a bug fix.

## 7. Reading the numbers honestly

* **The sample is 60 functions and it is not the repository's 30 % figure.**
  `…_b7.md`'s 126/415 = 30.4 % is codegen coverage over files; this is proof
  coverage over functions, and the two denominators are unrelated.
* **38 of the 60 say nothing about proofs.** They are the code generator's
  language frontier, and they are the same 38 on both architectures.
* **`bound-exceeded` is not a verdict.** It is `formal/lean.py`'s own
  distinction and it is why `-t 180` produced 2 rather than a number: both
  items typecheck on x86-64 in under 4 s, and `wdiff` is measured at 282 s
  elsewhere. A larger `-t` is the way to convert them; it was not spent here
  because two concurrent Lean runs at Lean's own 6 GB ceiling is what breached
  this census's 8 GB reservation on the first attempt (`memcap: BREACH 8.0 GB >
  8.0 GB ceiling (100%), 3 procs`).
* **The x86-64 row would read 0 `pass` and look catastrophic.** It is 22/22 at
  the design floor; a pass/fail count that cannot see the floor is the reason
  `formal/lean.py` counts holes from Lean's own `uses sorry` warnings.

## 8. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/formal_proof_breadth.py --list --verbose-select   # the workload
python3 tools/memslot.py --gb 8 --label proofbreadth -- \
  python3 tools/formal_proof_breadth.py -j 2 -t 180             # both arches
python3 tools/formal_proof_breadth.py --arch x86_64 -j 1 -t 300 # one arch
```

Every Lean run is content-addressed (`formal/lean.py`'s verdict CAS), so a
re-run with nothing changed is a file read per item; changing anything under
`formal/`, `lib/` or the parser invalidates it, which is why the 11 x86-64
re-checks above took 16 s.