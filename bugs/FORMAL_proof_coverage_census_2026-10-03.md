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
  python3 tools/formal_proof_breadth.py -j 2 -t 400      # 120 items
```

**Tool:** `tools/formal_proof_breadth.py`. **Ledger: every verdict is committed**
— `bugs/sweeps/proof_breadth_2026-10-03.jsonl`, one JSON line per item per
architecture (120 lines), so every number below is a `Counter` over a file in
the tree and a reader who disagrees with one can check it without re-running 120
builds. **Machine:** 18 cores, load 13-40.
**Cost:** a cold run is **~8 min wall, peak 7.8 GB** across 3 processes against
the 8 GB reservation; a re-run with nothing changed is **17 s** for all 120
verdicts, because every Lean verdict is content-addressed
(`formal/lean.py`'s CAS). **7.8 GB is 2x the 3-4 GB line
`bugs/PERF_memory_over_4gb_is_a_bug.md` sets**, and it is entirely Lean's own
6 GB ceiling for one generated proof rather than anything in the census: the
first attempt at `-j 2` with two *heavy* proofs at once BREACHED the 8 GB
reservation (`memcap: BREACH 8.0 GB > 8.0 GB ceiling (100%), 3 procs`) and the
published run is `-j 1`.

## 1. The workload, and why it is 60 functions and not 60 files

15 `formal/examples` programs verbatim (a fixed stride over the sorted stems, so
the choice is reproducible) and 45 functions **extracted from this repository's
own `*.py`**, each emitted as a standalone module together with the module-level
definitions it transitively needs plus a `main` that calls it, and selected
round-robin across files in sorted path order (the largest eligible function per
file, then the next file's). The sample reaches `formal/build.py`,
`formal/lean.py`, `fire_compiler.py`, `gimple_codegen.py`, `module_loader.py`,
`myinterpreter.py`, `mojo/backend_gimple/*`, `mojo/middle/*` and eleven
`test_formal_*.py` files.

Selection is by **name discipline and nothing else**: every free name a
candidate reads must be a parameter, a local, a builtin, or a module-level
definition of the same file (pulled in verbatim, transitively — and *checked* at
every level: a function's body, a class's body and bases, a constant's
right-hand side, a signature's annotations). A function that reaches for `os` is
not eligible — that is `not-answerable/host-import` in the sweep's vocabulary,
already counted 241 times there, and measuring it again here would only dilute
the classes this census is about. Parameters annotated with anything but `int`
are excluded because the synthesised `main` calls the function with the startup
stub's integer, and a mismatch there would make the census report a call-site
refusal as if it were a statement about the function. **Nothing is filtered by
whether the backend can lower it** — which is the thing being measured. The
instrument's own test (`test_formal_proof_breadth.py`) checks that every emitted
module is closed, which is what that claim rests on.

**One bias, stated rather than hidden:** sorted-path round-robin lands more of the
45 in `formal/` and `mojo/` than their share of the tree (4 distinct
directories, 45 distinct files). Changing the rule would change the sample, and a
census's sample has to be the same sample for two runs to be comparable — so it
is a stated bias, not a bug.

## 2. The classes

Two phases, because a Lean run costs ~100x a codegen run: phase A builds with
`prove=True, check=False` (the code generator AND the proof generator run, which
is what separates "the code generator refused" from "the proof generator
refused" without a tactician), and phase B runs the check only where phase A
produced a proof — through `formal/lean.py::run_lean`'s bounds, with the per-item
**wall** bound passed explicitly (`-t 400`) so one slow proof cannot consume the
run. Lean's CPU bound is left at its own default.

| | arm64 | x86-64 |
|---|---|---|
| `pass` — proof typechecks, **zero** holes | **10** | **0** |
| `admitted` — typechecks, admits `sorry` | 1 | **20** |
| `lean-rejected` — Lean did not accept it | 4 | 1 |
| `bound-exceeded` — `run_lean` killed it (**not a verdict**) | 0 | 0 |
| `proof-refused` — the generator refused, by name | 6 | 0 |
| `proof-crash` — the generator RAISED (a bug) | 0 | 0 |
| `codegen-refused` — the code generator refused | 39 | 39 |
| **reached Lean at all** | **15** | **21** |
| median wall for one that reached Lean | 20.5 s | 2.9 s |

Two facts about the table that are the reason it is not "pass/total":

* **x86-64's hole floor is exactly 2.** All 20 x86-64 proofs that typechecked
  admitted **exactly 2** `sorry`s and not one more. Those two are that
  generator's designed trust boundaries (`<fn>_compile_correct`, and the step
  certificates where a certificate would be false), stated in the header of
  every x86-64 proof this generator writes. So on x86-64 `admitted` means "proved
  modulo the declared boundary, with nothing extra", and **20 of the 21 programs
  that got that far typechecked**. arm64's floor is **0**: 10 of its 11 have no
  hole at all, and the eleventh (`sum_range`, a `for`-range program whose AST
  model has no loop form) has exactly 2.
* **39 of 60 never reach the proof layer, and they are the same 39 functions on
  both architectures** — 36 of them with byte-identical refusal messages, the
  other 3 differing only in which of the two identical arch-specific sentences
  (`the formal arm64 path` / `the formal x86-64 path`) a `print(flush=…)`
  refusal quotes. The code generator's language frontier is one thing, not two,
  which is the conclusion `…_b7.md` §2.5 reached over the sweep's 668 files, now
  measured at function granularity.

So the proof-layer denominator is **21**, and over it: **arm64 11/21 (52 %)
produce a proof Lean accepts, x86-64 20/21 (95 %) do.** 40 of the 60 items get
the same class on both architectures.

## 3. The 39 codegen refusals, by family

Facts about the code generator, not the proof layer. They are here so §4 is read
against the right denominator, and because `…_b7.md`'s ranking is over files
while this is over functions.

| n | family | examples |
|---|---|---|
| 5 | an arithmetic operator on a string | `'%'`, `'<='` |
| 5 | a String method that returns a SEQUENCE | `text.split()` ×5, `stdout.splitlines()` |
| 4 | a field access through a value (`x.y`) | `call.args`, `s.required`, `body_fd._mojo_coro_body`, `gen._owned_stack_allocated` |
| 3 | a subscript whose index is a string | `info['symbol']`, `kw['dest']`, `result['status']` |
| 3 | `len()` of an integer | `len(vals)`, `len(dflts)`, `len(m)` |
| 3 | `print(flush=…)` on this path | three files |
| 4 | another String method (`join`, `partition`, `rsplit`, `strip`) | |
| 2 | a NUMBER compared with a string literal | ``k == 'start'``, ``c == 's'`` |
| 2 | the image binds a symbol nothing provides | |
| 1 each | 8 more | a module global with storage read as a value, `+` on two strings, a tuple-keyed subscript, a method on a string whose receiver is classified, and one refusal per file |

Every one is a refusal with a named reason, which is this backend's shape
everywhere: this is the sweep's `codegen` class at function granularity, and none
of the 39 is a proof-layer fact.

## 4. The 21 that reached the proof layer — the ranked causes

Ranked over **both** architectures; an item that fails the same way on both is
one cause with two symptoms, so the counts are items, not verdicts.

| items | arm64 | x86-64 | cause |
|---|---|---|---|
| **4** | `proof-refused` | **`admitted` — was `lean-rejected`** | **a call to a second function in the same image.** arm64: `universal theorem: the call at 0x… targets 0x…, a second function in the same image … That is interprocedural walking: a return-address map in the framework`. x86-64 used to emit the bridge anyway and get `⊢ False` at its own line 44 — **the emitted theorem was false**. **Fixed on this branch** (§5.2): x86-64 now omits the bridge and names the call. `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md` has the rest. |
| **4** | `lean-rejected` | `admitted` | **the dec1 recursion family** — `count`, `pow2`, `sqsum` (and `fact`, `sum`, which the stride did not select). One cause, measured on all five: the code generator now **reloads x30 from the frame**, so the generator's "x30 is unchanged here" obligation is true and no longer `rfl`. `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md`. |
| 1 | `lean-rejected` | `admitted` | `fib` — a documented gap (`test_formal.py`'s `EXPECTED_FAILURES`), tree recursion's `FrameOk` window. |
| 1 | `proof-refused` | `admitted` | `model: a TernaryExpr has no value in the semantic model` — `formal/arm64_proof_gen.py::_no_value_model` refusing by name, and **the x86-64 generator CATCHING the same refusal and emitting its documented placeholder**, so the program builds there against a model that is not the source's. The two architectures degrade differently for one gap. |
| **1** | `proof-refused` | **`lean-rejected`** | **`~x` modelled as a logical `not`.** `formal/macho_linker.py:236`'s `& ~31`: the machine computes 64 (as CPython does) and the model's `~31` is `if 31 = 0 then 1 else 0`, i.e. 0 — so `mojo 5 = 0` and x86-64's own `native_decide` run test reports `main_result 5 = mojo 5 is false`. **A wrong model, caught by the teeth.** `bugs/FORMAL_the_semantic_model_renders_a_bitwise_not_as_a_logical_one.md`. |
| 1 | `proof-refused` | `admitted` | a zero-argument call (`cas.py:133 reset_stats`), the same `MojoExpr.call` limit as row 1 — arm64 reaches it as a second-function call; before this branch it was an `IndexError` out of `_expr_ast`. **Fixed** (§5.2). |
| 1 | `admitted` | — | `sum_range`: a `for`-range program, whose AST model has no loop form, so the bridge is omitted and the machine value flow carries it. Correct, and the emitted file says so. |

## 5. What this branch fixes

Three defects, all in the proof layer, none of them visible to
`test_formal.py` (49 hand-written programs that share none of these shapes with
the repository's own code):

1. **The dec1 recursion walk cited a hypothesis it never emitted and unfolded
   one block deep.** `_gen_universal_e2e_cfg`'s `bl` arm named a literal
   `hsrc_0`, which no emitted proof defines: at `master`, `count`, `fact`,
   `pow2`, `sqsum` and `sum` each emit **4 citations of `hsrc_0` and define 1
   `hsrc_N`** — a hard Lean error in all five, counted without running Lean. The
   two goals beside it unfolded with `hsid_0` plus block 0's definitions, which is
   right one block deep and wrong at depth (`s_6` is written in terms of `s_4`):
   `hargeq` kept an unsolved goal and `hspd` failed with "Expected type must not
   contain free variables", `native_decide` being unable to decide a statement
   that mentions a local. Both now use the path-scoped set the sibling goals in
   the same function already use. `count`: **5 error sites → 2**, the three gone
   ones being these.
2. **The AST bridge stated a call it cannot state, and the two backends
   disagreed about it.** `_expr_ast`'s `Call` arm rendered `e.args[0]` and
   dropped the rest, and `callFunc` answers **0** for any name but the proved
   function — so a program whose `main` returns a call's value emitted an
   `eval_eq_mojo` that is **false** (x86-64's `⊢ False`, 4 of 21 items), and a
   zero-argument call raised `IndexError: list index out of range` out of the
   generator. One shared check (`_ast_bridge_gaps`, one message for both
   architectures) now refuses both by name, so x86-64 drops the bridge and says
   which call it gave up on. It knows which calls can matter: an expression
   statement's value is **discarded** by the evaluator
   (`lib/ProofLib.lean:875`), so `fn main(): print(42)` is not a gap and keeps
   proving with no holes — which is why the arity rule is unconditional and the
   stub rule is not. arm64's message for a two-function program is unchanged
   (its machine half is the bigger gap and says so), because the check is emitted
   after that refusal.
3. **x86-64's omission note described a behaviour the code did not have.** It
   read "calls, prints and method calls have none" while calls were rendered and
   the false theorem reached Lean. It now quotes the refusal that caused it.

**Behaviour preservation, measured:** generating every proof in
`formal/examples` on both architectures before and after, **79 of the 95 emitted
files are byte-identical**. The 16 that changed are the 5 arm64 dec1 programs
(fix 1) and the 11 x86-64 proofs whose note quotes its real reason (fix 3).
Nothing that typechecked before stopped: **all 15 sampled x86-64 examples still
typecheck at exactly 2 holes** (16 s for the lot) and arm64's 10 hole-free proofs
are unchanged.

## 6. What this census did NOT fix

* **The whole dec1 family on arm64 — 4 of 21 items, the largest remaining
  cause** — is behind one fact: `x30` is reloaded from the frame, so the
  generator's x30 obligations need the same window-peel chain `FrameOk`'s memory
  clause uses, and `FrameOk`'s 15 conjuncts need per-conjunct tactics instead of
  one `all_goals intro j hj` (14 of the 15 have no binders for it).
  `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` carries the reduced
  sides, the per-program measurements, and the two-step next step.
* **A call to a second function in the same image is still not provable** — 4 of
  21 items. The limit is one limit with two ends (`MojoExpr.call` carries one
  argument; `callFunc` is a unary stub rather than the model's function table),
  and the work is measured, including the Lean limitation that blocks the
  obvious route: `bugs/FORMAL_ast_bridge_carries_one_argument_per_call.md`. This
  census adds the breadth number (4 of 21, both architectures) and the
  observation that **no example in `formal/examples` calls anything but itself**,
  which is why the whole corpus was blind to it.
* **`~x` is modelled as a logical `not`, on both architectures** — a wrong model
  that `native_decide` has been catching. The fix needs `lib/ProofLib.lean` (a
  `unop "bnot"` arm), so it invalidates every cached proof verdict and wants the
  whole formal suite behind it rather than one example:
  `bugs/FORMAL_the_semantic_model_renders_a_bitwise_not_as_a_logical_one.md`.
* **x86-64's placeholder model.** A `TernaryExpr`/`ListExpr`/`TupleExpr` is
  refused by name on arm64 and silently replaced by a documented placeholder on
  x86-64, so an x86-64 proof can pass against a model that is not the source's.
  Not a bug fix; it is that generator's designed degradation, and changing it is
  a trust-boundary decision.

## 7. Reading the numbers honestly

* **The sample is 60 functions and it is not the repository's 30 % figure.**
  `…_b7.md`'s 126/415 = 30.4 % is codegen coverage over files; this is proof
  coverage over functions, and the two denominators are unrelated.
* **39 of the 60 say nothing about proofs.** They are the code generator's
  language frontier, and they are the same 39 on both architectures.
* **`bound-exceeded` is not a verdict, and this run has none — because the first
  one did.** At `-t 180` the census reported `pow2` and `sqsum` as bound breaches;
  at `-t 400`/`-t 700` both are real verdicts with one error each (§4). That is
  `formal/lean.py`'s own distinction doing its job, and the cost of getting it
  wrong is visible: two items would have been reported as "slow" instead of as
  the x30 bug they are.
* **The x86-64 row would read 0 `pass` and look catastrophic.** It is 20/21 at
  the design floor; a pass/fail count that cannot see the floor is why
  `formal/lean.py` counts holes from Lean's own `uses sorry` warnings.
* **The medians are for different things.** arm64's 20.5 s median is real Lean
  work; x86-64's 2.9 s is `native_decide` over a smaller model. Comparing them as
  "x86-64 is 7x faster to prove" would be reading the two machines' Lean models,
  not the backends.

## 8. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/formal_proof_breadth.py --list --verbose-select   # the workload
python3 tools/memslot.py --gb 8 --label proofbreadth -- \
  python3 tools/formal_proof_breadth.py -j 1 -t 400             # both arches
python3 tools/formal_proof_breadth.py --arch x86_64 -j 1 -t 300 # one arch
python3 test_formal_proof_breadth.py                            # the instrument
```

The published run's ledger is committed, so re-deriving any count is a
`Counter` over `bugs/sweeps/proof_breadth_2026-10-03.jsonl` and not a run.

Every Lean run is content-addressed, so a re-run with nothing changed is a file
read per item (17 s for all 120 above); changing anything under `formal/`,
`lib/` or the parser invalidates it, which is why the 11 x86-64 re-checks after
the generator change took 16 s.