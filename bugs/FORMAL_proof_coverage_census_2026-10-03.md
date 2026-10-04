# FORMAL_proof_coverage_census_2026-10-03: 60 functions from THIS repository, both backends, with proofs on

**§0.6 is new (2026-10-04, `work/formal19-4`): §0.2's "a module global with
storage but no initializer" family is 0, and it was a MISDIAGNOSIS rather than a
capability — `None` is a word on this path and `_static_word` had no arm for
it.** Both of the family's items are re-measured per item with
`tools/formal_proof_breadth.py --show`, off the tool's own emitted source rather
than re-selected:

| item | §0.2's class | now |
|---|---|---|
| `formal/arm64_proof_gen.py:_step_branch_index` | a module global with storage but no initializer | the image would bind `enumerate`, which nothing provides |
| `gimple_codegen.py:_selfhost_syms` | the same | `'_out.sort()' is a method call on a value` |

Both are one ROW along rather than to `pass`, which is §3's own warning ("a file's
terminal cause is the FIRST refusal") and not a new measurement. What the census
gains is that a 2-item family was not a family at all: `_STEP_CONDS`'s first
entry is `(None, 0xd65f03c0)` and `_SELFHOST_SIGS` holds `NoneType`-shaped
values, and the reason string `static_initializer_refusal_reason` picked —
**"one of its elements is computed by a call"** — is false of a program with no
call in it. The full account, and the second false clause found beside it, is
`bugs/FORMAL_module_state_no_storage.md`'s Status at the head;
`test_formal_globals.py` is 54/54 with the two new rows.

**Status: §0 is new and it CORRECTS this census. Twenty-eight of its 39
`codegen-refused` items emitted a program the source does not have — the synthesised `main`
hands every parameter the startup stub's integer, so a function that uses a
parameter as a container got a program the source does not have, and the census
reported what that fabricated program did as a limit of this compiler. The
eligibility filter now excludes those candidates (`tools/formal_proof_breadth.py`'s
`_integer_unusable_in`, pinned by `test_formal_proof_breadth.py`), the arm64 half
is re-measured in §0.2 with the new sample, and the Lean half is NOT re-measured
because it is not re-measurable on this tree — see §0.3, which is a finding about
master rather than about this census. §0.4 closes the largest family §0.2 found:
**`print(flush=…)` was one refusal whose stated reason was false, and it is
answered rather than ignored.** Everything below §0 is the state of the
tree the first run was taken on, kept because §0's numbers are only readable
against it, and §3's family table is superseded by §0.2's.**

**§0.5 is new, and it is a DIFFERENT measurement of the same subject.** §2–§4
count what the proof generator emits over a hand-built corpus of 60 functions.
§0.5 counts what happens over a GENERATED corpus, because that is the only way to
ask the question the rest of this document cannot: whether a proof Lean ACCEPTS
is a proof about what the program MEANS. On this tree the answer is **64 of 64
programs (40 x86-64, 24 arm64) with zero soundness findings**, over 372 image
runs compared with CPython — and it took TWO generator blockers out of the
proof layer to be able to ask it at all. Its corpus is not §0.2's, so none of its
counts are comparable with §0.2's or §0.4's; §0.5 opens by saying which.

**§0.6 is new, and it is the SECOND ROUND over the same subject: 78 functions
that share NONE of the first round's, both architectures, every non-pass
classified.** It exists because a census of 60 functions answers one question
about one sample, and §0.6 is what the answer looks like on a different 78 —
of which **46 reach the proof layer against §2's 21**, and the largest single
cause is a construct no amount of corpus would have found. It is phase A only
(`--no-check`, no Lean at all) and says so in its own first paragraph; the two
fixes it carries are in `formal/build.py` and `formal/model.py`, and both are
measured on round 0's own sample so the movement is a `Counter` over two
committed ledgers rather than a claim.

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

## 0.1 The harness was eleven of the 39, and the rule that says so
## (`work/formal16-6`)

**The eligibility test already said why this was a hazard.** §1: *"Parameters
annotated with anything but `int` are excluded, because the synthesised `main`
calls the function with the startup stub's integer and a mismatch there would
make the census report a CALL-SITE refusal as if it were a statement about the
function."* That is exactly right, and it is implemented — for ANNOTATIONS. An
**unannotated** parameter reaches the same place with less evidence, and nothing
asked.

**Twenty-eight of the 39 emitted a program the source does not have**, measured
by asking the new predicate of each of the 39 from the committed ledger (the
ident, the function, `_integer_unusable_in(function)` — a `Counter` over a file in
the tree, not a re-run):

| | n | of which the refusal is about the fabricated value |
|---|---|---|
| items whose parameter the stub's integer cannot serve | **28** | 16 — the string-method, string-subscript and `len()` families |
| items that survive the filter | **11** | — |

The 28, by the shape the parameter is used in: `len(p)` 3, a subscript `p[k]` 2,
a method call on `p` 16, iteration over `p` 7. The clearest of them is the one
whose own refusal names the problem — `test_formal_call_proof_gen.py`'s
`_arm64_step_branch`: **"src.find() is a method on a string, and its receiver is
classified as 'int' rather than a string"**. `src` is an unannotated parameter of
a function about the ARM64 branch encoder; the string is the reader's
assumption and the int is the harness's. A census that prints that as a
code-generator limit is reporting itself.

The 11 that survive, and their refusals are about the backend:

| n | family |
|---|---|
| 5 | an arithmetic operator on a string (`%` ×3, `<=` ×1 — and one more the family counts separately) |
| 3 | `print(flush=…)` must be a string literal |
| 1 | `+` on two strings |
| 1 | `c == 's'` compares a NUMBER with a string literal |
| 1 | a module global with storage but no initializer (`_SELFHOST_SIGS`) |
| 1 | a field access through a value (`body_fd._mojo_coro_body`) |

**The rule is `_integer_unusable_in`, and it is decidable from the source.** A
parameter the harness fills with an integer is unusable in exactly five shapes:
`len(p)`, `p[…]`, iteration over `p` (`for … in p`, a comprehension's iterable,
`iter`/`sorted`/`next`/…), and a method call on `p`. Everything else — arithmetic,
comparison, being passed on — constrains nothing about what the value IS, so it
stays eligible. **The rule can only REMOVE candidates**, which is the direction a
refusal-shaped filter has to go in.

**What it costs, and it is a number a reader should have.** The repo half is 45
functions over **41** files, not 45 over 45: the filter removed the last eligible
candidate from four files, so the round-robin takes a second and third function
from files it has already reached. `test_formal_proof_breadth.py`'s
`test_the_repo_half_spreads_over_files` is a floor (90 % of the slots) rather
than the exact 45 it was, and says why in its own docstring — what it protects is
SPREAD, and the exact composition is reproducible from the tool, which the first
test already pins.

## 0.2 The arm64 half, re-measured with the new sample, phase A only

```console
$ python3 tools/memslot.py --gb 8 --label proofbreadth -- \
      python3 tools/formal_proof_breadth.py --arch arm64 -j 2 -t 1 \
      --ledger bugs/sweeps/proof_breadth_2026-10-04-harness-filter-phaseA.jsonl
60/60 verdicts in 6s
```

| class | before (60 items, both arches) | after, arm64, new sample |
|---|---|---|
| `codegen-refused` | 39 | **32** |
| `proof-refused` | 6 | **13** |
| `proof-crash` | 0 | **1** — `sum_range.mojo`, and it is NOT this change's (§0.3) |
| reached Lean at all | 21 of 60 | 25 of 60 (13 refused + 1 crashed + 3 pass + 3 rejected + 8 hit the 1 s bound) |

**The movement is the point, and it is the movement the fix predicts.** Seven
items left the `codegen-refused` class and thirteen entered the proof layer,
because the items that were being stopped by a fabricated call site are exactly
the items that reach a proof. A census whose denominator moves because its
HARNESS stopped lying is a better measurement of the same thing.

The 32 refusals, by family (arm64, read off the committed ledger):

| n | family |
|---|---|
| 9 | `print(flush=…)` must be a string literal |
| 5 | an arithmetic operator on a string (`%` ×4, `<=` ×1) |
| 4 | `+` on two strings |
| 3 | a NUMBER compared with a string literal |
| 4 | a field access through a value (`node.kids`, `body_fd._mojo_coro_body`, `args.posonlyargs`, `args.min_kind`) |
| 2 | a module global with storage but no initializer |
| 5 | one each: a method call on a value, a shorter string (`ln.strip()`), `len()` of an int (`items` is a LOCAL, so this one is real), a repetition `[None] * rows`, a symbol the image binds and nothing provides |

## 0.3 Why the Lean half is not re-measured here, which is a finding about master

**Two things this census counted as green are not green on this tree, and neither
is this session's work.** Both measured with the guard change of
`bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md` REVERTED, so they are
not caused by anything in this branch:

| item | the census's ledger | this tree, arm64 |
|---|---|---|
| `formal/examples/either.mojo` | `pass`, 0 holes | **`(kernel) excessive memory consumption detected`** at `either_proof.lean:5517` — with and without the guard widening |
| `formal/examples/sum_range.mojo` | `admitted`, 2 holes | **`ValueError: unsupported cbz taken continuation to 0x100000330`** out of the proof generator — with and without it |

So a full re-run of this census is not a light worker's measurement on this tree:
Lean's own memory ceiling is now the binding constraint on the proof half, and one
example raises instead of refusing. The re-measurement above is therefore
phase A — `codegen-refused`, `proof-refused` and `proof-crash` are all decided
before Lean runs — plus whatever Lean verdicts the content-addressed CAS already
held, which is where the `pass`/`lean-rejected`/`bound-exceeded` rows come from.
**That is a weaker claim than §2's table and is labelled as one.**

## 0.4 The largest family is CLOSED, and it was a false refusal rather than a
## value model (`work/formal18-5`, 2026-10-03)

**Nine of §0.2's 32 were ONE refusal whose stated reason was false about every
one of them, and all nine build past it now.**

    print(…, flush=True)
      ->  print(flush=...) must be a string literal on the formal arm64 path
          (got BoolLiteral): the separator and the line ending are baked into
          the format string, which is built before the call is emitted

Every clause of that sentence is about `sep` and `end`. `flush` is a bool, it is
baked into nothing, and the refusal fired because `_print_kwargs` asked **"is
this value a string literal?" before it looked at the keyword** — so a keyword
whose value is not text at all was judged by the rule written for the two
keywords that want text. The ledger's own `(got BoolLiteral)` is the proof in the
refusal's mouth: the value it complains about is the one keyword in the language
that is never text. And it is the commonest keyword in this repository's own
source — every one of the nine is the same `print(…, flush=True)` in a test's
`check` helper, in nine files.

**What landed is two changes, and the second is the one that matters.**

  * `model.print_kwargs` — the decision, in ONE place. `_print_kwargs` was a
    private method in `arm64_codegen.py` and the same method again in
    `x86_64_codegen.py`, differing only in the backend word three messages
    quote, and this document's own §2 says two emitters disagreeing is the
    failure mode of this area. Both are now two lines of delegation, beside
    `printf_format_refusal`, which already argues that shape.
  * `flush=` is answered, and ANSWERED rather than tolerated: each emitter
    writes `fflush(NULL)` after the `printf` when it is true. Not a dropped
    keyword — the one thing a formal image cannot show by not flushing is a
    program whose output has not reached the pipe yet, which is a MISSING line
    rather than a wrong one. `fflush(NULL)` rather than `fflush(stdout)` because
    this model has one stream, which is the fact `print(file=…)`'s refusal is
    already stated on. `flush` of a NAME is still refused, and the message now
    says what is wanted instead of what the separator is doing.

**Measured per item, both architectures, off the tool's own `--show` output** so
the modules are the census's own rather than anything re-selected:

| | items | where each one lands |
|---|---|---|
| left `print(flush=…)` | **8 of 9** | `'+' on two strings` ×7, `print() cannot tell whether BinaryOp is a string or a number` ×1 |
| …with byte-identical wording on the two machines | all 8 | the next refusal is a shared one, which §2's 39-of-60 measures over the whole class and this re-measures on the 8 |

**The ninth item is not in the sample any more, and this change did not do
that.** The ledger records `test_formal_link_accounting.py:69:check`; master's
selection for that file is `test_formal_link_accounting.py:1036:_short_repr`,
because the two have the same weight (3 top-level statements — the selector's
`weight` is the statement count) and the tie is broken by the ident as a
STRING, where `…:1036:…` sorts before `…:69:…`. `_short_repr` is refused for
`len()` of an int, which is §0.1's class. So the family is 9 → 0 on the
ledger's reading and on master's sample, but the ninth verdict belongs to a
different function now, and the table above says so rather than counting it.

**What it was worth, in this census's units — and it is NOT a coverage number.**
**Twenty-three** of the sixty items are still `codegen-refused`, which is §0.2's
32 less this family's 9 and is the same 23 the last paragraph counts families
over (a `Counter` over `bugs/sweeps/proof_breadth_2026-10-04-harness-filter-phaseA.jsonl`,
the ledger §0.2 is read off; the 8 are only the items `--show` re-ran, so the
eight is not a census figure). Each of the 23 now stops on the next row, which
is the same shape `bugs/FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it.md`
§2 reached by hand: a spelling a file must be rewritten into is not a construct
it was waiting on. What it bought is a class the corpus reaches at nine sites
whose refusal named the wrong rule, and a duplicated decision collapsed into one.

**And it makes the NEXT row the largest one, which is the useful number here.**
After this change `'+' on two strings` is **11 of the 23 remaining**
refusals (4 in §0.2 plus the 7 measured above) and `'%'`/`'<=` on a string is 5,
so 16 of 23 are one subject: **a string VALUE model**, which is §6's first item
and `FORMAL_string_value_model.md`, not a decision this kind of fix can make.


## 0.5 The Lean half, over a GENERATED corpus: is an accepted proof about what
## the program MEANS? (`work/formal17-fuzz-continue-b`, 2026-10-04)

**The number is §0.5's, not §0.2's, and the corpus is why.** This is a
*generated* corpus, so nothing here is comparable with §0.2's 32
`codegen-refused` or with §0.4's 23 — the two sections are measured over
different 60s and their families are counted independently. What §0.5 shares
with §0.2 and §0.4 is the vocabulary and the tool, not the denominators.

**The question §2–§4 do not ask.** Every row above is a verdict about a FILE:
the generator emitted a proof, and Lean accepted or rejected it. None of them
compares the thing the proof is *about* with the thing the program does. A proof
can check, cleanly and with zero holes, and be about a model that is not the
source — §6's third bullet is one (`~x` modelled as a logical `not`), and it was
found by a concrete `native_decide` instance rather than by a corpus, because a
corpus of hand-written programs cannot be trusted to contain the case.

**The instrument.** `tools/formal_proof_fuzz.py`. It generates programs in the
shape the semantic model can state — one entry function, a few straight-line
`int` statements, one final `print`, nothing else — builds each with
`prove=True`, checks the emitted proof through `formal/lean.py::run_lean`'s
bounds, and puts Lean's verdict in one column and the image's answer against
CPython in the other. The cell the tool exists for is **`MISMATCH` under a proof
Lean ACCEPTED**: Lean has checked that the compiled bytes compute the semantic
model, and the image says the model is not what the program means, so the proof
is a proof about a wrong model. That is a soundness bug, and no amount of fixing
the code generator touches it. `tools/formal_fuzz.py` measures the other half
(`--no-prove`, image against CPython) and shares this one's oracle, runner,
classifier, minimiser and `KNOWN_DIVERGENCES` by import — there is one of each in
the repository.

**The run.** Seed `formal-proof-fuzz`, `--mix plain`, 6 inputs per program (its
own, drawn from the seed, plus `0 1 3 7 32768`). Ledgers are committed, one JSON
line per program, so every number here is a `Counter` over a file in the tree:

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ppf-x86 -- \
  python3 -u tools/formal_proof_fuzz.py --count 40 --arch x86_64 -j 2 -t 400 \
  --work .tmp/ppf/x86            # 555 s wall, 6.8 GB peak — the COLD run
python3 tools/memslot.py --gb 8 --label ppf-arm -- \
  python3 -u tools/formal_proof_fuzz.py --count 24 --arch arm64 -j 1 -t 900 \
  --work .tmp/ppf/arm           # ~2 min a program, 6.0 GB peak
```

`bugs/sweeps/proof_fuzz_2026-10-04_x86_64.jsonl` (40 programs) and
`…_arm64.jsonl` (24). The x86-64 warm re-run is
**52 s** for all 40 verdicts — every Lean verdict is content-addressed
(`formal/lean.py`'s CAS) and the rest is codegen — and it reproduced the cold
run's classes exactly, which is the CAS doing its job and not a claim that the
corpus is easy. arm64 is `-j 1`: two Lean proofs BREACH the 8 GB reservation
(the same measurement §0.1 records for this census), and arm64 is where the
hole-free `pass` rows come from, so it is the half worth spending the memory on.

| | x86-64 | arm64 |
|---|---|---|
| programs | 40 | 24 |
| image runs compared against CPython | **228** | **144** |
| `pass` — proof typechecks, **0 holes** | 0 | **8** |
| `admitted` — typechecks, N holes | **30**, every one at **N = 2** | 0 |
| `lean-rejected` | 10 | 2 |
| `lean-memory-exceeded` (not a verdict — §0.3) | 0 | **14** |
| `proof-refused` / `codegen-refused` / `proof-crash` | 0 | 0 |
| reached Lean at all | **40 of 40** | **24 of 24** |
| `match` — image and CPython agreed at every input | **40** | **24** |
| **`SOUNDNESS-MISMATCH`** | **0** | **0** |

**The x86-64 row moved while this section was being written, and the movement is
the point.** It read `admitted 33 / lean-rejected 7` when the first 40-program
run finished. Then the x86-64 half of the environment fix below landed, and the
same 40 programs read **30 / 10**. Ten of the forty are two-parameter entries,
and for **all ten** the `eval_eq_mojo` bridge was silently OMITTED before
(`AST bridge omitted: this function's shape (recursive/looping)` — a shape
claim FALSE of a straight-line program) and is now EMITTED. Seven of the ten
close with Lean; three now fail to elaborate, on the §0.5-tactic gap below. So
the fix removed ten holes and turned three quiet passes into reds, which is the
direction this census argues for throughout: **a hole is not a pass**, and
`bugs/FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n.md` is where the three
reds go to be finished.

The one-argument half is unmoved (23 admitted / 7 rejected before and after),
which is what "at arity one the two environments are the same single entry"
predicts and is the reason `formal/examples` is byte-identical throughout.

**What the zero is and is not.** It is 372 comparisons over 64 programs in which
every image answered CPython, and every proof Lean accepted was therefore a proof
about a model that computes those programs correctly. Only 38 of the 64 had a
proof Lean accepted at all (30 x86-64 `admitted` + 8 arm64 `pass`); the other 26
are the honest half of the measurement — 16 of them Lean could not hold in
memory, and 12 it rejected — and a verdict nobody read is not a verdict.

It is NOT a statement that the model is right. It is bounded by the corpus (one
function, `int` only, no loop, no call, no container — the shape the model can
state at all, and `bugs/FORMAL_known_limits.md` owns the rest) and by the typed
model being absent (CPython has no `Int8`, so every typed program would need a
hand-written wrap-around oracle, and an oracle built from the same reading of
the language as the model under test cannot catch that model). §6's `~x` row is outside this
corpus by construction: it is in `formal/macho_linker.py`, not in a program.

**The `pass` rows are the ones worth having** — 8 of them on arm64, against 14
programs Lean could not hold in memory and 2 it rejected. Those 8 are proofs
with **no hole anywhere in the chain** — machine ≡ bytes ≡ AST ≡ `mojo` — for
generated programs nobody wrote. On x86-64 a hole-free `pass` is not reachable at
all (the generator's declared floor is exactly 2), so the tool's `--holes-below`
defaults to each architecture's floor rather than to 0: at the floor the
AST-to-`mojo` half is still fully proved, and that is the half a wrong model
lives in.

**What it cost, and what it found.** Getting 40 of 40 to *reach* Lean was one
generator blocker: `_cond_nodes`/`_collect_conds_t` rendered every branch
condition in `{param: param}` and folded no assignment into the environment, so
any program whose `if` reads a local raised `model: 'b' is read here and this
generator binds it to nothing` — a message false about the source, on 34 of 60
generated programs. The rule was written out at FIVE call sites — two of them folding no assignment
at all, one accepting an `env` argument and discarding it, and two mapping the
entry's parameters the wrong way round — and is now at two helpers
(`_bind_one`, `_entry_env`), which both backends call. Before/after, programs
generating a proof:

| | arm64 | x86-64 |
|---|---|---|
| before | 26 of 60 | 51 of 60 |
| after | **60 of 60** | **60 of 60** |

Two more findings, and both are coverage:

* **`bugs/FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n.md`** — the x86-64
  rejections, 7 of 40 before the environment fix and 10 of 40 after it. `eval_eq_mojo`'s goal over a free `n` is not closed by
  `simp`, and neither `simp (maxSteps …)` nor `bv_decide` recovers it, so it is
  not a fuel limit.
* **A refusal that was a crash.** A program with two calls out of the image
  raised `ValueError: unsupported: recursion argument bound (not a dec1
  pattern)` — about recursion, for a program with none — because the walk halts
  at ONE address and a second call has paths of its own. It now refuses by name.
* **The x86-64 fallback model was written at arity 1**, so the promise its own
  comment makes ("rather than failing the build") held only for an entry of one
  argument, which is every program in `formal/examples`. Over the `ternary` mix
  it was 9 of 60 there and 0 of 60 after; arm64 is unmoved because it propagates
  the shared generator's refusal rather than degrading.

**And the largest thing still in the way** is a construct, not a bug in a
generator: a conditional expression has no value in the arm64 semantic model, and
the CODE GENERATOR already lowers it (`_emit_csel_ternary`). Over the same
corpus it is 37 of 60 programs, against 0 of 60 for the default `plain` mix —
`bugs/FORMAL_a_conditional_expression_has_no_value_in_the_semantic_model.md`
carries the measurement and why closing it is three layers deep rather than a
ten-line arm.

## 0.6 Round 2: 78 functions that share NONE of round 1's, and what stops each

**This is phase A only, and the Lean-dependent classes of §2 are therefore NOT
MEASURED here.** The run is `tools/formal_proof_breadth.py --no-check`, which
builds with `prove=True` and does not ask Lean anything: every item that reaches
a proof is reported as `proof-emitted`, a class the report prints as *not a
verdict* because nobody has checked it. So there is no `pass`, no `admitted`, no
`lean-rejected` and no `bound-exceeded` row below, and their absence is a
property of the run rather than a measurement of zero. §0.3 is the precedent and
the reason: a worker who may not start Lean gets the phase-A half, which is
exactly the half that separates "the code generator refused" from "the proof
generator refused", and the tool grew a mode for it rather than a flag that
quietly lowered the wall bound.

```console
$ python3 tools/memslot.py --gb 8 --label proofbreadth2 -- \
    python3 -u tools/formal_proof_breadth.py --no-check --arch both -j 4 -t 400 \
      --repo 60 --examples 45 --example-offset 1 --admit-returns \
      --exclude-seen bugs/sweeps/proof_breadth_2026-10-03.jsonl \
      --ledger bugs/sweeps/proof_breadth_2026-10-04_round2-phaseA.jsonl
156/156 verdicts in 2s; peak 0.1 GB
```

Every number in this section is a `Counter` over that committed ledger.

### 0.6.1 The sample, and the three things a second census over one tree needed

**The eligible pool is 76 functions and round 1 took 45 of them, so a ~80-function
sample that shares none of the first is arithmetically out of reach without
changing something.** Three changes to the SELECTOR made it reachable, and all
three leave round 0 — the first census's sample — exactly as it was, because a
number already quoted from this document has to keep meaning what it meant:

  * **`--round-offset` / `--example-offset`** shift the selection (round 1 is
    each file's *largest* eligible function; offset 1 is each file's second).
  * **`--exclude-seen`** reads an earlier census's committed ledger. The key is
    `path:name` and not `path:lineno:name`, and that is a measurement rather than
    a preference: **only 10 of round 1's 45 repo idents still exist on this
    tree**, 16 more exist at a moved line, and **22 of its 41 files are no longer
    sampled at all**. An ident is not a stable key, so an exclusion keyed on it
    forgets a function the moment anything above it changes — a second census so
    keyed shares 38 of its 78 items with `--list`. It also excludes round 0's
    CURRENT sample, because that is the comparison a reader makes.
  * **`--admit-returns`** widens the pool, and it relaxes exactly one eligibility
    rule. The rule it relaxes is stated in terms of a CALL SITE — "the synthesised
    `main` calls the function with the startup stub's integer, and a mismatch
    there would make the census report a CALL-SITE refusal as if it were a
    statement about the function" — which is true of a **parameter** (`str` is a
    value the harness cannot supply) and **false of a return** (`main` returns
    whatever the function returns and nothing asserts a type on it). Measured,
    both architectures: `def f(n: int) -> bool` builds and emits its proof exactly
    as the same function without the annotation does, and so do `-> str` and
    `-> None`. That one rule was excluding ~550 real functions over no hazard.

The result is **78 items — 18 `formal/examples` programs and 60 functions from
this repository's own `*.py`, over 32 files, with zero overlap with round 1's
ledger or with `--list` today.** Two biases, both stated rather than hidden: 32
files is fewer than round 1's 41, because excluding round 0 costs the widest
files their best candidate (`formal/model.py` alone is 16 of them); and the two
samples are NOT two independent draws from one population, so §0.6's percentages
and §2's are not comparable — round 1's sample is string-heavy in a way this
one is not, which is itself the finding below.

### 0.6.2 The classes

| | arm64 | x86-64 |
|---|---|---|
| `pass` / `admitted` / `lean-rejected` / `bound-exceeded` | **not measured** (§0.6's first paragraph) | **not measured** |
| `proof-emitted` — a proof was written, nobody asked Lean | **17** | **46** |
| `proof-refused` — the generator refused, by name | **29** | **0** |
| `codegen-refused` — the code generator refused | **32** | **32** |
| reached the proof layer at all | **46 of 78 (59 %)** | **46 of 78 (59 %)** |

By item, which is the unit worth reading in: **32 items are `codegen-refused` on
both machines, 29 are `proof-refused` on arm64 and `proof-emitted` on x86-64, and
17 emit a proof on both.** arm64's `proof-refused` is never a crash — every one is
a `NotImplementedError` from a raise site that names its reason, which is what
`tools/formal_proof_breadth.py`'s `_PHASE` instrumentation exists to tell apart
from a generator bug.

**The x86-64 column has no `proof-refused` at all, and that is its designed
degradation rather than a capability.** It catches the same refusals arm64
propagates and emits a documented placeholder instead (§6's last bullet), so its
column answers a different question: how much the generator could state, against
arm64's how much it could state *without inventing*. Both columns are reported;
neither is the coverage number.

### 0.6.3 Every non-pass, by the construct that stops it

61 of the 78 items meet a refusal; the other 17 emit a proof on both machines and
have no row here. The subject is read off the refusal's own words, and each row
is a `Counter` over the ledger.

| items | class | the construct | whose it is |
|---|---|---|---|
| **20** | arm64 `proof-refused` | **a call to a second function in the same image** — `universal theorem: the call at 0x… targets 0x…, a second function in the same image. The machine model follows it -- every byte is present, and the callee's `ret` returns through x30 -- but the CFG walk is per-function` | `bugs/FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md` (filed here) |
| **16** | both `codegen-refused` | **a string VALUE**: `'+'` on two strings, `'%'`/`<=`/`==` with a string operand, `join()`, `strip()`, `replace`, an f-string reaching `print()` | `FORMAL_string_value_model.md` (formal16-7) |
| **7** | both `codegen-refused` | **a field access through a value** (`x.y`), which the path has no way to type | `FORMAL_pointer_value_model.md` (formal13-5) |
| **6** | both `codegen-refused` | **a call this path does not lower**, refused by the LINK AUDIT rather than by name — `list`, `enumerate`, `max`, `min`, `REPORT.append`, `_DISPATCH_TABLE_GLOBAL_CTYPES.get` | `the link audit's naming of an unlowered callee.md` |
| **4** | arm64 `proof-refused` | **a container literal with no value in the model** — `model: a ListExpr has no value in the semantic model`, and its Tuple/Dict/Ternary arms | the representation work; §6 |
| **4** | arm64 `proof-refused` | **a call with no model** — `model: call to \`str\` has no model in this image`, `…to \`int\`…` | the same, one layer out |
| 1 | arm64 `proof-refused` | `model: \`None\` is read here and this generator binds it to nothing` | §6 |
| 1 | both `codegen-refused` | a method call on a value (`value.to_bytes()`) | — |
| 1 | both `codegen-refused` | a module-level constant with storage but no initializer (`BIG_N = [2 ** 32, …]`) | — |
| 1 | both `codegen-refused` | a `range()` literal over the frame budget (524296 bytes, 131072 left on arm64 / 16384 on x86-64) | — |

**Two of the three biggest rows are claimed by other workers and are listed here
so nobody re-derives them.** The largest, by a factor of two and a half, is the
one with no doc of its own until this section filed one.

**The string row is 16 of the 61 and it is one subject**, so the arithmetic of
this section is worth doing once: a string is a bare `char *` on this path, so
`+` is integer arithmetic on two addresses, `%` is an integer operation with a
string where a number belongs, and a comparison needs `strcmp`, which dereferences.
Every one of those is a refusal with a named reason and none is a proof-layer
fact. 59 % of this corpus reaching the proof layer is therefore bounded by a
construct that has nothing to do with proofs.

### 0.6.4 What this round fixed, measured on round 0's sample

Two false refusals, both in the module-constant machinery, both found by the
census and both with the same shape: **a name the build HAD read was reported as a
name it could not place**, and the message named something else entirely.

| | the construct | before | after |
|---|---|---|---|
| `formal/build.py` | **a subscript index is a READ even when the subscript is a store** — `out[K] = v` stores into `out` and reads `K` | `codegen-refused` on both: *"'POOL' has no home: the register allocator collected no home for it, so the emitter and the allocation walk disagree about this function's locals"* | arm64 `proof-refused` (the DictExpr model gap), x86-64 `proof-emitted` (2292 lines) |
| `formal/model.py` | **a module constant is folded through its own operators** — `MAX64 = 2 ** 63 - 1`, `SHL = 1 << 20` | `codegen-refused`, and **the two backends named DIFFERENT subjects for the same function**: arm64 *"'MAX64' has no home: this module declares no module-level name by that spelling"*, x86-64 *"'%' is refused when the left operand is a string"* | both refuse it on the string |

The second is the more interesting of the two and not for the item it moved. A
census with one column per architecture is only worth reading if the columns are
about the same thing, and one item in 78 was quietly comparing arm64's answer to
a module constant against x86-64's answer to a string operator — **before this,
3 of the 32 `codegen-refused` items had a different refusal text on the two
machines, and after it, 2 do** (one is the frame budget genuinely differing, one
is a real construct divergence and is filed).

Both fixes are measured on **round 0's own 60-item sample**, before and after, as
two committed ledgers with the same 120 keys:

| | `codegen-refused` | `proof-refused` | `proof-emitted` |
|---|---|---|---|
| `…_round0-phaseA-before-both-fixes.jsonl` | 66 | 12 | 42 |
| `…_round0-phaseA.jsonl` | 64 | 13 | 43 |

**What was run to cover them**, so the integrator does not have to guess which
suites this touches: `test_formal_globals.py` 53/53 (three engines per case,
which is where both fixes' pins live), `test_formal_run.py` **954/954**,
`test_formal_toplevel.py` 111/111 — the module-level statements are the fold's
blast radius — `test_formal_target_queries.py` 32/32 (the other reader of the
module-level folder), `test_formal_x86_64_parity.py` 51/51 (the refusals both
machines have to word identically), `test_formal_proof_breadth.py` 14/14 and
`test_suite.py` 299/299. **No gate, no Lean, no stdlib sweep** — this worker may
run neither, and §0.6.5's last bullet is what is left. One static fact that
bounds the stdlib verdicts by construction: **no `.mojo` file in this tree has a
module-level constant whose initializer uses `**`, `<<`, `>>`, `|`, `&` or `^`**
(250 module-level bindings scanned, 0 hits), so the two module-level folders
cannot reclassify a stdlib module's body from this change.

Two verdicts changed, both `tools/memslot.py:448:held_env`, and both off the
code generator's frontier into the proof layer. It is worth being precise about
what that is worth: `held_env` is not yet proved, it is now *provable-shaped* —
arm64 refuses it for the DictExpr model gap and x86-64 emits a proof nobody has
checked. The census counts a hole as not a pass and this is the same discipline
one layer earlier: a function that reaches the proof layer is not a function that
has a proof.

### 0.6.5 What this round did NOT fix, and why

* **The arm64 universal theorem cannot follow a call into the same image — 20 of
  78 items, the largest cause in the census.** It is a per-function CFG walk, and
  the callee's `ret` dispatches on `x30`, whose value is a property of the call
  path rather than of the block. Closing it is a return-address map in the
  machine framework, not an arm in the generator, and it cannot be verified by a
  worker who may not run Lean — a machine-model change whose only oracle is the
  proof it produces. Filed, with the reduce and the two ends of the limit.
* **A container and a string still have no value in the model** — 24 of the 61
  refusals between them, and every one of them is somebody else's claim.
* **The Lean half of this round is not measured**, so nothing here says whether
  any of the 46 proofs Lean would accept. The integrator has the budget for it;
  §0.3 says what to expect when it is spent.

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
| **1** | `proof-refused` | **`lean-rejected`** | **`~x` modelled as a logical `not`.** `formal/macho_linker.py:236`'s `& ~31`: the machine computes 64 (as CPython does) and the model's `~31` is `if 31 = 0 then 1 else 0`, i.e. 0 — so `mojo 5 = 0` and x86-64's own `native_decide` run test reports `main_result 5 = mojo 5 is false`. **A wrong model, caught by the teeth.** FIXED: `~` is a bitwise complement in both the model (`formal/arm64_proof_gen.py`) and the AST bridge's name (`evalExpr`'s `unop "bnot"` arm in `lib/ProofLib.lean`), so this row is kept as the measurement that found it and its doc is deleted with the fix. |
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
  whole formal suite behind it rather than one example. **LANDED**: the arm is
  in `lib/ProofLib.lean`, `formal/arm64_proof_gen.py` renders `~` as the
  bitwise complement rather than as `x = 0`, `_expr_ast` spells it `"bnot"` so
  the bridge and the model cannot disagree about it again, and the executed
  rows are `test_formal_run.py`'s three `both_arch_bitwise_not_*` cases. Kept
  here because it is the one row in this census that was a WRONG MODEL rather
  than a hole, and that is the distinction the next reader needs.
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

# ROUND 2 (§0.6): a different sample, and phase A only — no Lean is started.
python3 tools/memslot.py --gb 8 --label proofbreadth2 -- \
  python3 -u tools/formal_proof_breadth.py --no-check --arch both -j 4 -t 400 \
    --repo 60 --examples 45 --example-offset 1 --admit-returns \
    --exclude-seen bugs/sweeps/proof_breadth_2026-10-03.jsonl \
    --ledger bugs/sweeps/proof_breadth_2026-10-04_round2-phaseA.jsonl
```

The published run's ledger is committed, so re-deriving any count is a
`Counter` over `bugs/sweeps/proof_breadth_2026-10-03.jsonl` and not a run.
**Three ledgers carry §0.6's numbers and they are named for what they are:**
`proof_breadth_2026-10-04_round2-phaseA.jsonl` (round 2's 78 items, phase A),
`proof_breadth_2026-10-04_round0-phaseA.jsonl` (round 0's own 60 items, after
the two fixes of §0.6.4) and `…_round0-phaseA-before-both-fixes.jsonl` (the same
120 keys before them, so §0.6.4's table is a diff of two files rather than a
claim).

Every Lean run is content-addressed, so a re-run with nothing changed is a file
read per item (17 s for all 120 above); changing anything under `formal/`,
`lib/` or the parser invalidates it, which is why the 11 x86-64 re-checks after
the generator change took 16 s.