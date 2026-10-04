# FORMAL_fuzz_ledger: what `tools/formal_fuzz.py` has measured, and what came of it

**This is the ledger the differential fuzzer's sweeps are recorded in.** One row
per sweep (mix, seed, index range, programs, both architectures, the tally as the
tool printed it), then one entry per finding with what happened to it — fixed with
a commit, or filed as a bug doc — and one for each defect the TOOL turned out to
have, because those cost more than the backend bugs did and are invisible in a
tally.

It exists because a fuzzer's results are otherwise invisible: the tool prints a
tally and writes `findings.json` under `--work`, which is a temporary directory by
the next run. The numbers are also the only record of what the corpus COVERS,
which is the thing that decays silently — a mix that stops producing a construct
reports the same clean tally as one that never produced it.

## 1. The rule this ledger keeps

A row here is a MEASUREMENT of a run, never a target. A clean tally is not
evidence that a mix is correct; it is evidence that the corpus ran. What makes a
row worth reading is the mix beside it: `containers` 487/500 with 13 refusals is
a better row than `globals` 500/500, because the first one is where two silent
miscompiles and one one-sided refusal came from.

The anti-rot is `KNOWN_DIVERGENCES`': **a construct that stopped being generated
is invisible here**, so a mix deleted from the corpus must be deleted with its
reason in the tool's own docstring, and a construct added must show up in a
sweep. The five mixes in §2's "new" block were each added because the backend had
newly learned the construct and nothing could see it.

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 2` and BOTH
backends (`--backends x86_64,arm64`). Peak memory across every sweep in this
file: **0.1 GB** (`tools/memslot.py --gb 4`), so none of it is within an order of
magnitude of the 3-4 GB line.

**5212 programs over 25 sweeps.** Three bugs fixed, five limits filed, and eight
defects in the tool itself.

| date | mix | seed | indexes | programs | tally | what came of it |
|---|---|---|---|---|---|---|
| 2026-10-03 | `core` | `formal-fuzz` | 0-299 | 300 | 300 match | nothing (baseline: master's corpus) |
| 2026-10-03 | `calls` | `formal-fuzz` | 0-299 | 300 | 300 match | nothing (baseline) |
| 2026-10-03 | `core` | `sweepB` | 2000-2299 | 300 | 300 match | nothing |
| 2026-10-03 | `calls` | `sweepB` | 2000-2299 | 300 | 300 match | nothing |
| 2026-10-03 | `lists` | `sweepB` | 2000-2299 | 300 | 300 match | nothing |
| 2026-10-03 | `classes` | `sweepB` | 2000-2299 | 300 | 300 match | nothing |
| 2026-10-03 | `containers` | `sweepA` | 1000-1499 | 500 | 487 match, 13 refusal, 0 findings | the 13 refusals were ONE bug, on one architecture only — §3.2 |
| 2026-10-03 | `globals` | `sweepA` | 1000-1499 | 500 | 500 match | nothing |
| 2026-10-03 | `strmeth` | `sweepA` | 1000-1499 | 500 | 500 match | nothing |
| 2026-10-03 | `generics` | `sweepA` | 1000-1499 | 500 | 500 match | nothing |
| 2026-10-03 | `environ` | `sweepB` | 2000-2119 | 120 | 120 match | nothing |
| 2026-10-03 | `signed` | `sweepF` | 6000-6099 | 100 | 31 match, 69 `KNOWN` (28 `floordiv`, 27 `modulo`, 14 both), 0 findings | nothing — every disagreement reduced to the documented one |
| 2026-10-03 | `strings` | `sweepD` | 4000-4011 | 12 | 3 match, 7 `KNOWN:str_subscript`, 2 `MISMATCH-X86` | the 2 are §4.4, a minimiser artefact — **not** backend bugs |

The first two rows are a BASELINE rather than a result: they ran on master's
corpus with the five new mixes absent, which is what "the corpus covered
arithmetic, control flow, calls, one-word containers and a `class`" costs in
programs that could not be generated at all.

`signed` was run with `--max-min-steps 30` rather than the default 400, for the
reason §5 gives: a program whose disagreement is a KNOWN construct pays for a
reduction that attribution then neutralises anyway.

### 2.1 The arch-parity sweep (`sweepG`, 2026-10-03) — 1180 programs, twelve mixes

Seed name `sweepG` and index ranges from 7000, disjoint from every row above, so
no row double-counts another's programs. The subject of this block is the
three-way claim the tool's `--backends x86_64,arm64` makes: **arm64 == CPython,
x86-64 == CPython, and arm64 == x86-64 on exit code, stdout and refusals.** One
hundred and eighty of the programs are clean on all three, `strings` is four
minimiser artefacts (§3.6), and `limits` is the refusal surface (§3.5) — which is
a family that did not exist before this sweep.

| date | mix | seed | indexes | programs | tally | what came of it |
|---|---|---|---|---|---|---|
| 2026-10-03 | `core` | `sweepG` | 7000-7149 | 150 | 150 match | nothing |
| 2026-10-03 | `calls` | `sweepG` | 7000-7149 | 150 | 150 match | nothing |
| 2026-10-03 | `classes` | `sweepG` | 7000-7149 | 150 | 150 match | nothing |
| 2026-10-03 | `lists` | `sweepG` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `containers` | `sweepG` | 7000-7099 | 100 | 100 match | nothing — the family §3.2 came from, now clean on a fresh seed range |
| 2026-10-03 | `globals` | `sweepG` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `strmeth` | `sweepG` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `generics` | `sweepG` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `signed` | `sweepG` | 7000-7099 | 100 | 38 match, 62 `KNOWN` (31 `floordiv`, 20 `modulo`, 11 both), 0 findings | nothing — every disagreement reduced to the documented one |
| 2026-10-03 | `environ` | `sweepG` | 7000-7019 | 20 | 20 match | nothing |
| 2026-10-03 | `strings` | `sweepG` | 7000-7009 | 10 | 1 match, 5 `KNOWN:str_subscript`, 4 `MISMATCH-X86`, 0 findings after attribution | the 4 are minimiser artefacts — §3.6 |
| 2026-10-03 | `limits` | `sweepG` | 8000-8099 | 100 | 95 refusal (190 audited, `true=190`), 5 `REFUSAL-DIVERGES-X86+ARM` | the refusal surface itself — §3.5 |

`limits` was run with `--max-min-steps 30` for the same reason `signed` was: the
five divergences are all the container-budget pair (§3.5.3) and the shrinker
cannot reduce a construct that is not in the program.

## 3. Findings

Three, in the order they were found. Each is a SILENT wrong answer or a
one-sided refusal — not a crash, not a diagnostic — because that is the class
this tool exists for and the class every other suite here misses.

### 3.1 A walk over a dict read `k0, v0, k1`, and a membership test's bound was its own needle

**Found:** by hand-probing once the construct was in the corpus at all (the
pre-existing mixes cannot generate a dict), then confirmed by the `containers`
sweep.
**Fixed:** `3d49db7c` (`formal: a walk over a dict steps by the PAIR, and its
bound is not the needle`).
**Pinned:** `test_formal_value_model.py` — twelve cases, both backends, against
CPython.

| | CPython | arm64 | x86-64 (before) |
|---|---|---|---|
| `d = {10: 100, 20: 200}` ; `for k in d: print(k)` | `10 20` | `10 100` | `10 100` |
| `d = {30: 1, 10: 2, 20: 3}` ; `for k in d: print(k)` | `30 10 20` | `30 1 10` | `30 1 10` |
| `d = {"bb": 1}` ; `for k in d: print(k)` | `bb` | `bb` | `4302697832` |
| `xs = ["ab", "cde"]` ; `"zz" in xs` | `False` | `False` | **SIGSEGV** |
| `xs = [10, 20]` ; `999 in xs` | `False` | `False` | `False`, after reading 999 words of frame |

Three defects, one area, and the third is the one worth remembering:

1. both backends' `_emit_for_list` stepped one WORD over a dict's PAIR blob;
2. a `for` target over a dict classified as an INTEGER (a dict is a bare
   `list`, and nothing read the keys), so a string key printed as an address
   and `len(k)` was refused;
3. **x86-64's membership scan held the COUNT in `R10` and reloaded the NEEDDLE
   into `R10` inside the loop**, so from the second iteration the exit test was
   `i >= needle`.

A HIT was right **by luck** — the runaway scan reaches the next element on the
way past the end — so a corpus whose membership tests all hit would have
reported nothing about defect 3. That is the single strongest argument in this
file for generating the MISS as well as the hit.

### 3.2 A comprehension in an `elif` arm reserved no temps on x86-64

**Found:** `containers` sweep, seed `sweepA` index 1083 — reported as a plain
`refusal`, which is §4.1's subject.
**Fixed:** `b55c046e`.
**Pinned:** `test_formal_x86_64_parity.py` — `comprehension_in_an_elif_arm_reserves_its_temps`
and `dict_comprehension_in_an_elif_arm_reserves_its_temps`.

Minimal reproducer (arm64 builds and runs it; x86-64 refuses with "main:
`'_cb0'` has no home"):

```mojo
def main() -> Int32:
    if (1 > 0):
        w9 = 5
    elif (2 > 3):
        D11 = [10 + i for i in range(1)]
    return 0
```

`IfStmt.elifs` is a list of `(cond, body)` TUPLES, and the walk that reserves
comprehension temps hands the `body` LIST to a function that only descends into
dataclass fields. arm64's copy of the same walk has had an
`isinstance(node, list)` arm for this exact reason since the day its own
comprehension-temp bug was fixed — so this is a copy that drifted, not a second
design, and `formal/x86_64_codegen.py` now says so at the arm.

All 13 of the sweep's refusals were this one bug. After the fix, a re-run of
seeds 1000-1499 on x86-64 alone produced **zero** refusals and zero generator
errors.

### 3.3 A function with no `return` yields a word where CPython yields `None`

**Found:** `strings` mix, seeds 0-3 — and **not from the generator**: the
generated program agreed everywhere except one `print` of a call's result, and
the disagreement appeared only after the minimiser deleted a `return` from a
helper. A finding reached through the minimiser is a finding about a construct
the corpus does not cover, which is worth knowing as a property of the tool.
**Filed, not fixed:** `bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`.

`print(g(1, 2))` for a `g` with no `return` prints `0` on both images and
`None` in CPython, exit 0 on all three. It is deliberately NOT a
`KNOWN_DIVERGENCES` row: `Gen.define_function` always emits a `return`, so the
corpus cannot produce the construct, and a row nothing can trigger is a row that
has stopped measuring.

### 3.4 The x86-64 `int(s, base)` parse was refused by its OWN duplicate label

**Found:** by hand, probing what a `sum(xs)` refusal actually says (the probe
that became `--audit`), and confirmed by `--mix limits`' `unknown_callee` family.
**Fixed:** `1aa8edc6`. **Pinned:** `test_formal_x86_64_parity.py`'s five
`int_parse_*` rows, which run on BOTH machines.

`print(int("12"))` printed `12` on arm64 and REFUSED on x86-64:

    build: internal: label 'main_ip1_end' is defined twice, at 0x1000003ba and
    at 0x1000003ba. … A label name must carry a per-site counter.

`_emit_int_parse` ended in two identical `self.asm.label(endl)` emits, from the
commit that added the parse (`05d720ef`), so the whole parse was arm64-only from
that day. Three things had to be true for that to be invisible, and each is a
statement about the tool rather than about the bug:

1. **nothing ran the case on x86-64.** `test_formal_run.py`'s `INT_PARSE_CASES`
   pin these five programs through `run_case`, which builds THE HOST'S
   ARCHITECTURE for an answered case — so on an arm64 host they were arm64 rows.
   The five are now also in `test_formal_x86_64_parity.py`, where a case runs on
   both machines or not at all. With the duplicate label put back, two of them
   fail with the internal error and pass without it.
2. **the internal error was filed as a `refusal`** (§4.5) — a correctly-refused
   construct, in a sweep's tally, for a lowering bug only one machine had;
3. **both machines refusing was agreement** (§4.6), so even the pair arm64-answers
   / x86-64-refuses did not read as a divergence in the message — it read as one
   in the VERDICT, which is §4.1's already-fixed half.

The same static check over both emitters (`asm.label(X)` twice in a row) finds
this one occurrence and no others, which is the cheap form of the sweep: the
duplicate-label check the assembler already performs is a better oracle than a
thousand programs, and it was already refusing the build.

### 3.5 The refusal surface: three findings, none of them a miscompile

**Found:** `--mix limits`, which is new — see §5 for why the corpus had no
refusal coverage at all. All three are filed, none is fixed, and none is a wrong
answer: they are about **the messages**, which is the class §3.1-§3.4 are not.

Every refusal the corpus reaches is now audited (`--audit`, and every sweep),
and the 190 refusals of seeds 8000-8099 came back `true=190, unnamed=0, false=0,
no-predicate=0` — so the three below are not what the sweep found *in that
range*; they are what the same audit reports on the two families the range did
not reach, and on the five divergences it did.

#### 3.5.1 An unlowered callee is refused by the LINK AUDIT, which names no construct

`print(sum(xs))` — and `max`, `min`, `abs`, and any name nothing declares — is
refused on BOTH machines by `_unaccounted_report`, which says the image would
bind a symbol nothing provides and then, in its own words, cannot decide whether
that symbol is a call the codegen emitted. The construct is genuinely outside the
subset and the refusal genuinely stops the build; the message names a FILE and a
SYMBOL, and never says that `sum` is a call this path does not lower.
`bugs/FORMAL_an_unlowered_callee_is_refused_by_a_link_audit.md`.

#### 3.5.2 The audit's other three verdicts, and what it cannot decide

`unnamed` and `false` are findings and `no-predicate` is the honest answer for a
family with no CPython-checkable claim. What the audit CANNOT do is decide
whether a construct really is outside the modelled subset: that is a property of
`formal/model.py`, not of the message, and the only witnesses available here are
the two machines and CPython. So `no-predicate` is counted in the summary and
never folded into `true` — a sweep that audited nothing says so, which is the
difference between "the refusals were true" and "nothing looked at the refusals".

#### 3.5.3 The two machines have different container budgets

Five of a hundred `limits` programs are `REFUSAL-DIVERGES-X86+ARM` and all five
are one 17608-byte list literal: arm64's scratch is 128 KB and x86-64's blob
region 16 KB, so the same source builds and runs on one machine and is refused on
the other, and `frame_blob_refusal`'s docstring says so. The refusal is TRUE on
both machines and the parity finding is real all the same, because a construct
one machine declines is a parity finding whatever the reason.

**SUPERSEDED 2026-10-04.** The two budgets are now named constants
(`formal/model.py::ARM64_CONTAINER_BUDGET` 131072 and `X86_64_CONTAINER_BUDGET`
16384, with `CONTAINER_BUDGET = min(...)` as the documented answer to "which
machine decides"), both emitters read them, this corpus's `big_blob` row is sized
off `CONTAINER_BUDGET` rather than a typed-in range, and `classify` reports this
class as `REFUSAL-DIVERGES-FRAME-BUDGET-<which>` so a tally can subtract it and be
left with the parity findings that are about the language. The five programs of a
hundred are now five rows that say which is which instead of five rows a reader
had to re-derive two numbers to interpret. Pinned by
`test_formal_fuzz.py::check_frame_budget` and the two `classify` rows beside it.

The messages also differ for a second reason, worth separating from the first:
the machines refuse at different POINTS, so arm64 got past the literal and
refused a later construct in the same program. `test_formal_run.py` has the
vocabulary for that shape (`refuse_either:`) and the fuzzer has none — both
report one `REFUSAL-DIVERGES`, which is right, since "the two machines do not
agree about this program" is the finding either way.

### 3.6 The four `strings` disagreements are the minimiser, and this time it is §3.3

**Found:** `strings`, `sweepG` 7000-7009 — 4 `MISMATCH-X86` out of 9 programs,
against 2 in the `sweepD` row above. **Not backend bugs**, and the shape is §3.3
exactly: in every one of the four, arm64 and x86-64 print the SAME bytes, so
there is no x86-64 bug to find, and the reduced program disagrees with CPython
about something else — a `print(f(...))` where the minimiser deleted `f`'s
`return`, which is `FORMAL_a_function_with_no_return_yields_a_word_where_cpython_
yields_None.md` (images print a leftover register, CPython prints `None`).

So the tool is RIGHT to report them unexplained — neutralising `str_subscript`
leaves a disagreement that is not the known one, which is the rule §"THE KNOWN
DIVERGENCES" states — and the reproducer on disk is a program that disagrees for
a different reason than the one reported. Two of the four reduced programs
(7000, 7006) contain no subscript at all; the other two keep one and cannot be
attributed. §4.4 is the earlier measurement of the same failure; this is its
second instance and it is the argument for shrinking with `want` fixed per
verdict rather than at all.

## 4. EIGHT defects in the TOOL, all found by using it

None is a backend bug. Between them they cost more time than the backend bugs
did, and each one made the tool report LESS than it should. §4.5-§4.8 are the
four the `sweepG` arch-parity sweep added, and they share a shape: each one
classified something as a correctly-refused construct that was not one.

### 4.1 A one-sided refusal was not a finding

`classify` returned a plain `refusal` whenever any engine refused, so "arm64
answers, x86-64 declines" — the divergence `test_formal_x86_64_parity.py` is
built around — counted as a clean run. That is how §3.2 sat in a sweep's
`programs/` directory looking like a routine refusal. There is now a
`REFUSAL-DIVERGES-<engines>` verdict, and it fires only when one engine ANSWERS
and another refuses: a refusal every engine agrees on is still a correctly
refused construct, and counting those would spend the whole budget on
`bugs/FORMAL_known_limits.md`.

### 4.2 A refusal divergence could not be minimised at all

`_still_fails` had no predicate for a refusal, so `--minimize` reported "the
program does not fail here any more" about a program that still failed. Two
further things were needed, both measured on this reproducer rather than reasoned
about:

* **"still refuses" is not a predicate.** With one backend under `--min-kind x86`,
  ANY refusal satisfies it, and the shrink walked out of `_cb0 has no home` into
  "D7 is read before anything in this function stores it" — a real refusal,
  about a real program, and a different bug. The predicate is now the original
  program's `(verdict, diagnostic)` per backend, compared on the first 40
  characters of the message.
* **A candidate that does not PARSE satisfies everything.** `_statement_spans`
  builds a span from a block's opening line to each line inside it, so deleting
  a body's first statement deleted the `def` line with it and left an indented
  file. `_still_fails` now compiles the candidate before it builds it.

### 4.3 The oracle has THREE answers and two callers read two

`cpython_answer` answers an `(exit, stdout)` tuple, `("error", …)` for a program
CPython rejected, and **`None` for a CPython TIMEOUT**. Both the minimiser and the
attribution asked "is this the error tuple?" and then unpacked, so the timeout's
`None` took a whole sweep down with `TypeError: cannot unpack non-iterable NoneType
object` — the `signed` sweep, seeds 2000-2299, minimising a program whose
recursion runs CPython past its own recursion limit. A tool that dies on its own
oracle reports nothing about the backend, and its exit status says nothing
either. `has_oracle(ref)` is now the one reader of that three-way answer, and a
timeout in `check_one` is its own `CPYTHON-TIMEOUT` verdict.

### 4.4 A stack-floor TRAP is not evidence, and the shrink walked into one

`_still_fails` preserved a TRAP as well as a CRASH, and a trap is `exit 2` — the
stack-floor guard's verdict about the PROGRAM, which the tool's own docstring
calls a documented limit rather than a silent wrong answer, and which is a much
smaller program than any real disagreement.

Measured on the `strings` sweep in §2: 7 of 9 disagreements were attributed to
`s[i]`-is-a-byte as they should be, and 2 came back `MISMATCH-X86` with a
reproducer of

```python
def f8():
    print(f8())
```

26 bytes, traps on both images, raises `RecursionError` on CPython. The byte
divergence was still there — `f` where the image printed `102`, `r` for `114`,
`e` for `101` — but the reproducer no longer contained it, so `blame` had nothing
to attribute. **Those two rows are minimiser artefacts, not backend bugs**, and
they are in §2's table rather than deleted from it because a run that produced
them is part of the record. §3.6 is the same failure on a different corpus, four
times, and it is now the second measurement rather than the first.

### 4.5 An INTERNAL diagnostic was filed as a `refusal`

`run_on` separated a crash from a refusal by asking whether the diagnostic was a
traceback or a sentence. Both assemblers raise `CodegenError` for their OWN
consistency checks, so "internal: label 'main_ip1_end' is defined twice, at 0x…
and at 0x…" is a sentence about the COMPILER and it was counted as a sentence
about the program. §3.4 is the bug that hid there, and the tally said the file
was outside the modelled subset. Its own verdict now (`CODEGEN-INTERNAL`), on
the one prefix both assemblers use.

The lesson is §"WHAT IS AND IS NOT A FINDING"'s own rule applied one level down:
a refusal is a claim about the source, so anything that is not a claim about the
source is a different verdict, and a tool that has two words for "the compiler
said no" needs three for "the compiler disagreed with itself".

### 4.6 BOTH machines refusing was agreement, whatever the words said

One refusal is compared with the other machine; two identical refusals were not
compared with each other. So "arm64 answered it, x86-64 refused it" was a
finding (§4.1) while "arm64 refused it this way, x86-64 refused it that way" was
a clean run — which is §3.4's second hiding place, and it hid the SAME bug. The
comparison folds architecture labels through `formal_sweep_parity.fold_arch`
rather than a second copy of it, because that normaliser was settled by
measurement against real logs (12 of 542 rows differed for no reason other than
a machine name) and "on the formal arm64 path" against "on the formal x86-64
path" is one sentence told by two machines.

### 4.7 Refusals were counted in ONE bucket, which the docstring has never done

`WHAT IS AND IS NOT A FINDING` has said "counted by message so the construct mix
stays visible" since the tool was written, and `classify` returned the string
`"refusal"` for every one of them — so a sweep of two thousand programs could not
say whether it had met one limit thirteen times or thirteen limits once. The
count is now per (backend, construct), with the construct read off the message's
head and required to be something the PROGRAM contains. That requirement is what
makes it a measurement rather than a caption: it is what reports §3.5.1 as
`unnamed` rather than as `symbol(s)`.

### 4.8 The corpus could not produce a refusal at all, so the audit had nothing to audit

4032 programs over the thirteen sweeps above produced 13 refusals, and all 13
were one bug. That is not a corpus measuring the limits; it is a corpus that
cannot reach them, and every other mix here is built out of constructs the path is
supposed to LOWER — which is the right discipline for finding miscompiles and the
wrong one for measuring messages. `--mix limits` emits constructs outside the
modelled subset on purpose (string concatenation, the length-dependent methods, a
slice, a `try` arm with a body, a dict method, an unlowered callee, a container
past one machine's budget), and it is the first family in this file that is
DECLARED not to lower: `test_formal_fuzz.py`'s `MIXES_NOT_LOWERED` used to be
empty, and its emptiness was the point, so the row is a deliberate reversal of a
stated invariant with the measurement that forced it.

Two of its seven families are in the mix although they are known to produce
findings (§3.5.1 and §3.5.3). A family that produces a finding is a family that
measures, and a corpus tuned to be green is a corpus that has stopped.

## 5. What the corpus still cannot say, and what it costs to run

**`strings` costs 45 s to 3 min per program**, and the cost moved when §4.4 was
fixed: 12 programs took 536 s before it (the shrinker terminating early on traps)
and 12 took about 20 minutes after (it no longer accepts a trap, so it explores
the full step budget on programs it used to "reduce" instantly). Both numbers are
in this file because the fix was correct and the cost is real. The shrink budget
is the thing to change next — `--max-min-steps` exists and does it from the
command line, and a program whose disagreement is a KNOWN construct pays for a
reduction that attribution then neutralises anyway.

**`environ` costs 2.4 s per program** (120 programs in 293 s), because a program
that imports `os` rebuilds the host module's dylib every time and this tool has
no build cache.

**`limits` costs 0.03 s per program** (100 programs in 30.6 s), which is the
cheapest family in this file and the one that reaches the most refusals per
program: 190 audited refusals out of 100 programs, because every program is
refused by BOTH backends and both are audited. Its `--max-min-steps 30` is not
optional in practice — the five `REFUSAL-DIVERGES` it produces are the
container-budget pair, and the shrinker cannot reduce a construct that is not in
the program, so it spends the whole budget finding that out.

**The corpus cannot produce:** a function with no `return` (§3.3), a dict store
of a new key
(NOW GENERATED and measured: `d[k] = v` is CPython's INSERT on both backends,
`formal/model.py`'s `dict_store_capacity`, so this row was removed from the
list rather than worked around), an `append` inside a loop (a blob's capacity is the number of append SITES and
every execution counts), a name bound by TWO dict literals
(`model._note_dict_init` retracts the initializer, so a `for` over such a dict
has no answerable key kind — 15 of 40 programs until the mix was changed to bind
a dict once), `struct`/`var` (CPython cannot parse it), floats, pointers, and file
descriptors.

**…and the list above is now SPLIT BY MIX rather than by corpus.** String
concatenation, a length-dependent string method, a slice, a `try` arm with a
body, a dict method, an unlowered callee and a container past the frame budget
are all things this corpus as a whole could not produce and `--mix limits` now
does, deliberately (§4.8). They are refusals rather than lowerings, so what they
buy is the MESSAGE and not an answer — which is the trade §4.8 makes and the
reason the mix is declared not to lower.

**What would be the next thing to generate**, in this ledger's order: `while`/`else`
and `for`/`else` (the corpus emits neither), a `with` statement (measured: it is
REFUSED with a message that names the protocol and the remedy, and it needs a
context manager CPython can also run, which is why `limits` leaves it out — a
`with 1 as w` is a `TypeError` in CPython and would take the program's verdict
with it), a `try`/`except` shape (NOW GENERATED — `limits`' `try_handler`, which
is the single largest row in its construct mix at 114 of 190 refusals, so the
next thing to vary there is the arm body), a comprehension whose generator has a
CONDITION over a dict walk, and a `global` container mutated through two
different helpers. Each is a family whose absence from this table is a coverage
hole rather than a decision.

## 6. Reproducing a row

    python3 tools/memslot.py --gb 4 --label fz -- \
        python3 tools/formal_fuzz.py --mix <mix> --seed <seed> \
            --seeds <lo>-<hi> -j 2 --work .tmp/fz/<mix>

`make_program(seed, index, mix, stmts)` is a pure function of its arguments, so
every row above re-runs byte for byte on any machine. The `--seed` is part of the
row: two sweeps of the same mix with different seeds are two corpora, and the
seed ranges here are disjoint so no row double-counts another's programs.
