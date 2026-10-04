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
newly learned the construct and nothing could see it; the nine in §2.1 were each
added because the CORPUS could not produce a construct at all, and three of them
found a defect the day they were written (§3.7, §3.8, §3.9).

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 2` and BOTH
backends (`--backends x86_64,arm64`). Peak memory across every sweep in this
file: **0.1 GB** (`tools/memslot.py --gb 4`), so none of it is within an order of
magnitude of the 3-4 GB line.

**5212 programs over 25 sweeps** — §2's thirteen rows and §2.2's twelve. Three
bugs fixed, five limits filed, and eight defects in the tool itself. §2.1 adds
**5100 programs over 41 more sweeps**, THREE more fixes and three more tool
defects, and §2.1a one more sweep of 100 programs and one more fix. §2.3 adds
**1020 programs over 13 sweeps**, TWO more fixes (§3.10's dict-walk stride and
§3.11's `del` register clobber), one new `KNOWN_DIVERGENCES` row
(`set_order`, owned by `bugs/FORMAL_set_value_model.md`), one new limit filed
(`FORMAL_a_comprehension_target_over_a_string_keyed_dict_is_an_int.md`) and TWO
more tool defects — so the whole file is **11432 programs over 80 sweeps** and
**fourteen** tool defects. The last three rows of §2.3 are the OLD mixes on a
fresh seed range, which is what says this session's two fixes did not cost the
corpus anything it already had.

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
| 2026-10-04 | `signed` | `floor21` | 9000-9099 | 100 | **100 match**, 0 findings | the two `KNOWN_DIVERGENCES` rows this row retires were worth 62 of `sweepG`'s 100 (§2.1) — see §2.1a |

The first two rows are a BASELINE rather than a result: they ran on master's
corpus with the five new mixes absent, which is what "the corpus covered
arithmetic, control flow, calls, one-word containers and a `class`" costs in
programs that could not be generated at all.

`signed` was run with `--max-min-steps 30` rather than the default 400, for the
reason §5 gives: a program whose disagreement is a KNOWN construct pays for a
reduction that attribution then neutralises anyway.

### 2.1 The fuzz-3 sweep (2026-10-03, seed `sweep19c`)

**5100 programs over 41 sweeps.** The first eleven rows are the nine mixes this
session ADDED — the corpus could not produce a loop's `else` arm, a closure, a
default or keyword argument, a list slice, a tuple unpack, a word-boundary
integer, a comparison chain as a value, a `try`/`finally`, or an interpolated
string literal — and each was PROBED ON BOTH ARCHITECTURES before it was written
down, because a mix that measures a refusal is a mix that spends its budget
re-deriving `FORMAL_known_limits.md`. The last eleven rows are the SEVEN
PRE-EXISTING mixes on fresh seed ranges, which is the other half of the result:
three fixes did not cost the corpus anything it already had.

`-j 4` (the earlier rows used `-j 2`), both backends, `tools/memslot.py --gb 8`.
Peak memory: **0.2 GB**. Cost: **0.7–2.8 programs/second** except `fstrings`,
which is 17/s because every program is a refusal that never reaches the image.
A sweep row is one `(mix, range, options)` triple, so the 41 rows below are 41
runs and the "sweeps" this file counts are rows — the earlier table's 13 are the
same thing.

The cost is not flat, and the shape of the cost is worth reading: `--stmts 30 50`
is **3–7x slower per program** than the default body, because a wide body is a
longer function to lower and two images to emit (`chains` went from 2.1/s to
0.2/s, `bignum` from 2.0/s to 0.4/s). A family that looked cheap at the default
body is not necessarily cheap at the width where the SPILL paths are.

**Ranges are recorded here so no row ever re-runs another's programs**, and
`make_program(seed, index, mix)` is a pure function of its arguments. Two ranges
are used per mix where the corpus changed between them, and both are listed —
the first `bignum` row is a different CORPUS from the second, which is why the
same indexes give different programs.

| date | mix | seed | indexes | programs | tally | what came of it |
|---|---|---|---|---|---|---|
| 2026-10-03 | `loopelse` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `closures` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `argshape` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing |
| 2026-10-03 | `slicing` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing (after §4.9: the first version of this family was 2 of 2 REFUSED) |
| 2026-10-03 | `unpack` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing — and 100 more after the fix it prompted |
| 2026-10-03 | `bignum` | `sweep19c` | 7000-7099 | 100 | 99 match, 1 `MISMATCH-X86` | **the corpus's own value discipline**, §4.9— not a backend bug |
| 2026-10-03 | `bignum` | `sweep19c` | 7000-7099 (re-run, corpus fixed) | 100 | 100 match | nothing |
| 2026-10-03 | `bignum` | `sweep19c` | 7100-7199 | 100 | 100 match | nothing |
| 2026-10-03 | `chains` | `sweep19c` | 7100-7199 | 100 | 100 match | nothing |
| 2026-10-03 | `strfmt` | `sweep19c` | 7100-7199 | 100 | 100 match | nothing |
| 2026-10-03 | `fstrings` | `sweep19c` | 7100-7199 | 100 | 100 refusal | nothing — 100 refusals is what the mix is (§3.7) |
| 2026-10-03 | `tryfinally` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `loopelse` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `closures` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `argshape` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `slicing` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `unpack` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `bignum` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `chains` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `strfmt` | `sweep19c` | 7200-7399 | 200 | 200 match | nothing |
| 2026-10-03 | `fstrings` | `sweep19c` | 7200-7399 | 200 | 200 refusal | nothing |
| 2026-10-03 | `closures` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing — the SPILL paths (a wide body is what reaches them) |
| 2026-10-03 | `unpack` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing |
| 2026-10-03 | `argshape` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing |
| 2026-10-03 | `loopelse` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing |
| 2026-10-03 | `tryfinally` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing |
| 2026-10-03 | `bignum` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing — and the SLOWEST mix per program (0.4/s) |
| 2026-10-03 | `chains` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 100 match | nothing — 400 s for 100 programs, the widest body in this table |
| 2026-10-03 | `strfmt` | `sweep19c` | 7400-7499, `--stmts 30 50` | 100 | 95 match, **5 `TIMEOUT`** | the machine, not the programs — §4.10|
| 2026-10-03 | `strfmt` | `sweep19c` | 7400-7499, `--stmts 30 50` (re-run after §4.10) | 100 | 100 match | nothing |
| 2026-10-03 | `closures` | `sweep19c` | 7500-7599 (captured-container corpus) | 100 | 100 match | nothing |
| 2026-10-03 | `slicing` | `sweep19c` | 7500-7599 (negative-bound corpus) | 100 | 100 match | nothing |
| 2026-10-03 | `unpack` | `sweep19c` | 7600-7699 | 100 | 100 match | nothing — after §3.9's fix |
| 2026-10-03 | `unpack` | `sweep19c` | 7700-7799 (dict-unpack corpus, first version) | 100 | 79 match, 21 `generator-error` | the corpus drew the SAME dict key twice — §4.9's last paragraph |
| 2026-10-03 | `unpack` | `sweep19c` | 7700-7799 (re-run, corpus fixed) | 100 | 100 match | nothing |
| 2026-10-03 | `containers` | `sweep19c` | 7800-7899 | 100 | 100 match | nothing |
| 2026-10-03 | `lists` | `sweep19c` | 7800-7899 | 100 | 100 match | nothing |
| 2026-10-03 | `strings` | `sweep19c` | 7800-7899, `--max-min-steps 30` | 100 | 21 match, 52 `KNOWN:str_subscript`, 27 `MISMATCH-X86` | **all 27 are classes §3.3 and §4.4 already name** — §4.11|
| 2026-10-03 | `strmeth` | `sweep19c` | 7800-7899 | 100 | 100 match | nothing |
| 2026-10-03 | `generics` | `sweep19c` | 7800-7899 | 100 | 100 match | nothing |
| 2026-10-03 | `globals` | `sweep19c` | 7800-7899 | 100 | 100 match | nothing |

The three `--stmts 30 50` rows are a different AXIS rather than more of the same:
x86-64 has fifteen usable general registers, so a function with twenty live
locals has to put some of them in its frame, and a lowering that reads a spilled
slot at the wrong offset is silent. A twelve-statement body never has enough
live values to spill one.

Five hand-written INTERACTION probes were also run against both architectures,
because the mixes generate the constructs but not every pairing of them: a
closure called from inside a loop after the captured local has changed twice; a
tuple SLICE and a keyword-argument call with a default in one function; a
`for`/`else` inside a `try`/`finally` whose `break` must reach both arms; a
closure whose own body does a two-element unpack of its parameters; and a slice
of a list beside a four-link comparison chain. **Five of five agree on both
architectures.**

The first two rows are a BASELINE rather than a result: they ran on master's
corpus with the five new mixes absent, which is what "the corpus covered
arithmetic, control flow, calls, one-word containers and a `class`" costs in
programs that could not be generated at all.

`signed` was run with `--max-min-steps 30` rather than the default 400, for the
reason §5 gives: a program whose disagreement is a KNOWN construct pays for a
reduction that attribution then neutralises anyway.

### 2.1a The `signed` row after the floor fix (2026-10-04) — and what it cost to find

The row above is the last one whose tally carries a `KNOWN` verdict for
`//`/`%`. Both backends now floor: `model.division_floors` is the one decision
they ask, `lib/ProofLib.lean`'s `fdiv64`/`frem64` are what the source model
names, and `tools/formal_fuzz.py`'s `floordiv` and `modulo` rows are DELETED in
the same commit as the fix — a row naming a construct that is now right forgives
the next disagreement that happens to contain it. What replaces them is
`formal_fuzz.MIX_MUST_GENERATE`, which asserts the weaker and still
load-bearing thing (`--mix signed` must still GENERATE a signed-over-signed
division), checked by `test_formal_fuzz.py::_check_generation`.

**Two measurements worth reading, and the second is the one to keep.**

1. **The tally.** Seed `floor21`, indexes 9000-9099, both backends: **100 match,
   0 findings, 0 refused, 0 trapped**, in **59.6 s** against `sweepG`'s `signed`
   row's 100 programs. The same mix before the fix was **38 match, 62 `KNOWN`**
   (31 `floordiv`, 20 `modulo`, 11 both) — so the construct this mix exists for
   went from two thirds of the corpus to none of it.
2. **What found the defect the hand-written rows could not.** The FIRST run of
   this row was 66 match / **34 `MISMATCH-X86`** with arm64 agreeing with CPython
   on all 34 — an x86-64 `%` that added the divisor to a ZERO remainder, because
   the correction's negation was applied to `c2` (the second `SETcc`) instead of
   to `c = c1 AND c2`. **Every hand-written `//`/`%` row agrees on that bug**,
   because `r == 0` is the only case where `c1` and `c2` disagree, and the
   generator had not produced `0 % <negative>` in the eight rows of the floor
   table. It is now
   `test_formal_run.py::both_arch_an_exact_multiple_of_a_negative_divisor`, and
   it is a better row than the table it joins because it was written *by* the
   sweep rather than beside it.

**And the cost of the run fell by 5x** — 299.9 s to 59.6 s for the same 100
programs — which is §5's "a program whose disagreement is a KNOWN construct pays
for a reduction that attribution then neutralises anyway" measured from the other
side: with no disagreement there is nothing to minimise. **The shrinker was not
the thing making `signed` expensive; the disagreements were.**

### 2.2 The arch-parity sweep (`sweepG`, 2026-10-03) — 1180 programs, twelve mixes

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

### 2.3 The fuzz-5 sweep (2026-10-04, seed `fuzz5`) — 900 programs, seven mixes

**Four new mixes over two index ranges each, plus three old mixes on one fresh
range.** The four are the constructs §5 listed as things the corpus could not
produce, and each was PROBED ON BOTH ARCHITECTURES before it was written down,
for §2.1's reason: a mix that measures a refusal spends its budget
re-deriving `bugs/FORMAL_known_limits.md`. Three findings came out of the
probing and one out of the sweeps — **§3.10** and **§3.11** — and the two
`KNOWN_DIVERGENCES` rows and the twenty-six regression rows that pin them are
named under each.

| date | mix | seed | indexes | programs | tally | what came of it |
|---|---|---|---|---|---|---|
| 2026-10-04 | `comps` | `fuzz5` | 9000-9099 | 100 | 100 match | nothing — after §3.10's fix; the range that found it is §3.10's |
| 2026-10-04 | `comps` | `fuzz5` | 9200-9299 | 100 | 100 match | nothing |
| 2026-10-04 | `objs` | `fuzz5` | 9000-9099 | 100 | 100 match | nothing |
| 2026-10-04 | `objs` | `fuzz5` | 9200-9299 | 100 | 100 match | nothing |
| 2026-10-04 | `refs` | `fuzz5` | 9000-9099 | 100 | 99 match, 1 refusal (`!=`, `true=2`) | the `del` clobber — §3.11 |
| 2026-10-04 | `refs` | `fuzz5` | 9200-9299 | 100 | 96 match, 4 refusal (`==`/`!=`, `true=8`) | nothing |
| 2026-10-04 | `sets` | `fuzz5` | 9000-9099, `--max-min-steps 30` | 100 | 34 match, 66 `KNOWN:set_order`, 0 findings | nothing — every disagreement attributed |
| 2026-10-04 | `sets` | `fuzz5` | 9200-9299, `--max-min-steps 30` | 100 | 34 match, 66 `KNOWN:set_order`, 0 findings | nothing |
| 2026-10-04 | `refs` | `fuzz5` | 9300-9399 | 100 | 100 match | nothing |
| 2026-10-04 | `comps` | `fuzz5` | 9300-9319, `--stmts 30 50` | 20 | 1 match, 19 `REFUSAL-DIVERGES-FRAME-BUDGET-X86` | the container-budget pair again (§3.5.3) — and the cost |
| 2026-10-04 | `containers` | `fuzz5` | 9200-9299 | 100 | 100 match | nothing — the old mixes on a fresh range: two fixes cost the corpus nothing it had |
| 2026-10-04 | `lists` | `fuzz5` | 9200-9299 | 100 | 100 match | nothing |
| 2026-10-04 | `classes` | `fuzz5` | 9200-9299 | 100 | 100 match | nothing |

**The two ranges are worth reading together, because agreeing with each other is
the measurement.** `comps`, `objs` and `sets` score identically on both ranges
(100, 100, 34+66), and `refs` reaches the same `==`/`!=` refusals at different
indexes on each (99+1 and 96+4) plus a clean 100 on the third. A mix whose
tallies track across disjoint ranges is measuring the MIX; one that does not is
measuring its seed, and §1's warning is the other direction.

**The `--stmts 30 50` row is the SPILL axis and it costs 143 s a program** — 20
programs in 2865 s, the slowest row in this file and 70x the same mix at the
default body (§2.1 records `chains` at 400 s for 100 as "the widest body in this
table", so `comps` at this width is worse). 19 of its 20 are
`REFUSAL-DIVERGES-FRAME-BUDGET-X86`, which is §3.5.3's container-budget pair
understood and not a capability difference: x86-64's blob region is 16384 bytes
and a fifty-statement body holding a dozen comprehensions does not fit in it,
while arm64's frame scratch is 131072. The one match is the program that stayed
inside the smaller budget. The row is here because a corpus that cannot be run
at the width where the SPILL paths live is a corpus that does not measure them,
and because the cost is the number a future session needs before choosing the
size.

**The cost is 0.2 GB peak** (`tools/memslot.py --gb 8`), `-j 4`, both backends —
nothing here is within an order of magnitude of the 3-4 GB line. Per program:
`comps` and `objs` 1.5-2.0/s, `refs` 1.6-2.1/s, and **`sets` 0.2/s** — 8x
everything else, because two thirds of its programs disagree with CPython and
every one pays for a reduction that attribution then neutralises. `--max-min-
steps 30` is what keeps that at 465 s for 100 rather than the 20 minutes §5
warns about for `strings`; it is not optional for this mix in practice, and the
mix's own comment says so.

**What the four mixes are, and what each one is for:**

- `comps` — the comprehension walks and the `*` splice: the OTHER TWO walks that
  bind one thing per count, beside `for k in d` and `k in d`. §3.10 is theirs.
  Every observation WALKS its result rather than measuring its `len`, and the
  reason is §3.10's: the count was right.
- `refs` — aliasing and mutation through a REFERENCE. Two names for one blob, a
  write through the second read through the first and then the other way round,
  a container in a struct field aliased to a local, a write through a PARAMETER
  across a call, a straight-line `del`, and the ORDER a walk yields (printed one
  key per line — an accumulator is commutative and blind to order, which is the
  same trap as §3.10's one level up, and the corpus's own `dict_iter` was doing
  it). §3.11 is this mix's.
- `objs` — a class whose `__init__` takes ARGUMENTS, `__len__` as a dunder
  reached through a builtin rather than a method call, and nested data in a
  struct field. `define_class` has always built `C()` with two fields set to
  constants, so the constructor's own argument passing was reachable from no mix.
- `sets` — a set, which `formal/model.py` lowers as a LIST, so `len` and
  membership agree with CPython and the iteration order does not. That
  divergence is `KNOWN_DIVERGENCES`' new `set_order` row and it is generated on
  purpose, owned by `bugs/FORMAL_set_value_model.md`.

## 3. Findings

**Eleven.** Nine from the first three sweeps and two from this one; §3.10 is the
dict-walk stride and §3.11 is the `del` register clobber. Each is a SILENT wrong
answer or a
one-sided refusal — not a crash, not a diagnostic — because that is the class
this tool exists for and the class every other suite here misses. §3.7, §3.8 and
§3.9 are the fuzz-3 sweep's three, and each was found by a construct the corpus
could not produce at all: two of them by probing it before a family was written
around it, one by probing a shape that family did not reach. §3.5 is about the
MESSAGES rather than about a lowering, and §3.6 is not a backend bug at all.

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
`the link audit's naming of an unlowered callee (landed in ee704916)`.

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

### 3.7 A tuple unpack bound the CONTAINER's kind to every target, so `print(a)` was refused on both architectures

**Found:** by probing the construct before writing the family around it, which is
the order this ledger's §2.1 describes — and it is why the probe is a probe and
not a sweep row: the sweep could not have found it, because the corpus could not
produce an unpack.
**Fixed:** `6b8a1de2` (`formal: a tuple unpack binds an ELEMENT, not the
container`).
**Pinned:** `test_formal_value_model.py` — five `a_tuple_unpack*` cases and one
REFUSAL, both backends, against CPython.

```mojo
t = (1, 2, 3)
a, b, c = t
print(a)     # CPython 1; both images REFUSE
```

| | CPython | arm64 | x86-64 (before) |
|---|---|---|---|
| `a, b, c = t` ; `print(a, b, c)` | `1 2 3` | *refused* | *refused* |
| `e = 1` ; `f = 2` ; `e, f = f, e` ; `print(e, f)` | `2 1` | *refused* | *refused* |
| `a, b = [7, 9]` ; `print(a, b)` | `7 9` | *refused* | *refused* |
| `a, (b, c) = (1, (2, 3))` ; `print(a, b, c)` | `1 2 3` | *refused* | *refused* |

One cause: `ValueKinds._scan`'s `AssignStmt` arm bound every name in a tuple
TARGET the kind of the whole VALUE, and a container kind (`list:int`) is not one
of the two kinds `print` chooses between, so the refusal was "print() cannot
tell whether IdentExpr is a string or a number on the formal arm64 path" — a
sentence false about a source that says twice what each name holds.
`_unpacked_element_kind` asks the ELEMENT kind, the same way `_iterable_kind`
already did for a `for` over the same container.

The second row is the part that was not a special case: `e, f = f, e` is a tuple
of two NAMES, and `_kind_of_simple` (which is what classifies a container
literal) classifies literals and nothing else, so the swap had no element kind
to inherit. It needs the elements asked through `kind_of`. A fix that handled
only `(1, 2, 3)` would have left the swap refusing.

### 3.8 An f-string printed ITS OWN SOURCE SPELLING, on both architectures, exit 0

**Found:** the same probe-first order as §3.7, and it is the worse of the two:
there was no refusal to notice, only an answer.
**Fixed:** `9b40c019` (`formal: an f-string literal is REFUSED, not printed as
its own spelling`).
**Pinned:** `test_formal_run.py` — `fstring_literal_refused`,
`tstring_literal_refused`, and `braces_in_an_ordinary_string_are_not_a_fstring`
(a guard against matching the TEXT instead of the prefix), both architectures.

```mojo
n = 7
print(f"n={n}")        # CPython n=7;  both images  f"n={n}"
print(len(f"n={n}"))   # CPython 3;    both images  8
if f"n={n}" == "n=7":  # CPython True; both images  false
print(f"{{lit}}")      # CPython {lit}; both images f"{{lit}}"
```

`fire_compiler.replace_tstrings_with_placeholders` puts an interpolated
literal's whole SOURCE TOKEN into the string cache, `eval_StringLiteral`
evaluates the `{...}` fields from it (which is why `fire.py run` and the
COMPILED path both print `n=7` — measured, and the compiled path's answer is the
one that makes this a defect rather than a design), and `decoded_literal` — the
reader every engine shares — handed the same text to both formal emitters.

**The fix is a REFUSAL and not a lowering**, and the reason is the same missing
buffer `string_concat_refusal` names: a string here is a bare `char *` interned
into read+execute `__TEXT`, so `"n=" + decimal(n)` has nowhere to be laid down
at compile time (the field may be a runtime value) or at run time (there is no
heap). Asked once from `formal/build.py`'s shared pipeline, over
`model.iter_nodes`, so a literal nested under a call is reached by the same walk
the frame layout uses and the two front ends cannot answer differently.

**What the fix does not cover**, filed as
`bugs/PARSE_FAIL_an_ordinary_string_whose_text_starts_with_an_f_prefix.md`: the
test is the value's PREFIX, and an ordinary string whose TEXT starts with `f"` or
`t'` is indistinguishable from an interpolated one in this AST. Measured on
` s = 'f"n"' `: the interpreter and the compiled path both print `n` where CPython
prints `f"n"`, and the formal path now refuses. The fix belongs in the parser —
a flag beside `is_raw`, set where the placeholder is built from the RAW token.

### 3.9 `k, v = d` bound a key and then a VALUE, and printed an address for the first

**Found:** by hand, while probing the shapes a tuple unpack's right-hand side can
be once the basic one was fixed. **Not** by a sweep, and this is the part worth
recording: the corpus cannot produce it either, because `unpack`'s right-hand side
is a tuple LITERAL — so the sequence was probe, fix, add the family, sweep.
**Fixed:** `bf554772`.
**Pinned:** `test_formal_value_model.py`'s `tuple_store_from_a_dict_binds_keys`,
which needs BOTH halves to pass.

```mojo
d = {"a": 1, "b": 2}
k, v = d
print(k)     # CPython: a
print(v)     # CPython: b
```

| | CPython | arm64 (before) | x86-64 (before) |
|---|---|---|---|
| `print(k)` | `a` | `4373316948` | `4309468543` |
| `print(v)` | `b` | `1` | `1` |

Two architectures, two DIFFERENT addresses for the same key, and `v` holding the
first value — so this was a wrong answer on both machines *and* a divergence
between them, all at exit 0. Three parts, and any one alone still leaves a wrong
answer:

1. **the stride.** Both emitters' blob unpack read element `i` at
   `8 + 8*i`. A dict is `[npairs][k0][v0][k1][v1]…`, so it must be
   `8 + 16*i` — `M.walk_stride`'s question, the one `for k in d` already asked and
   the one `walk_stride` was written for (§3.1). The count check was already
   right, because a dict's count field holds its pair count, which is why only the
   loads moved.
2. **the kind.** `ValueKinds._unpacked_element_kind` reads
   `_iterable_dict_key_kind` — the same reader a dict walk's target uses — so the
   targets classify as the strings they are and `print` has a conversion to
   choose. Gating that on `is_dict_value` does **not** work, and the measurement
   is the interesting part: that reader works from `_dict_names`, which a plain
   `d = {…}` assignment never reaches, so the arm never ran and `len(k)` still
   said "classified as 'int'". A gate that cannot be true is worse than none.
3. **the conservative direction.** A name pre-bound to an integer (`k = 0`) and
   then bound to a dict key is a flow-insensitive CONFLICT, and it now says so —
   `print() cannot tell whether IdentExpr is a string or a number`, where it used
   to print an address. A refusal, and the right one: the corpus's own preamble
   discipline (every local declared with the value CPython would not have) puts
   exactly that shape on the path, which is why the generator declares a dict
   unpack's targets as STRINGS.

### 3.10 A comprehension over a dict, and a `*` splice of one, read the VALUES as keys

**Found:** by hand-probing `references`/`comprehensions` shapes while writing
the `comps` mix — which is what §5 had already listed as the next thing to
generate ("a comprehension whose generator has a CONDITION over a dict walk").
**Fixed:** `086cd7f7`, four emitters.
**Pinned:** `test_formal_value_model.py` — eight `comprehension_over_a_dict_*` /
`dict_comprehension_over_a_dict_*` / `star_splice_of_*` rows, ORACLE rows against
CPython on both backends, plus two control rows that a list still steps one word.

    d = {10: 100, 20: 200, 30: 300}
    ks = [k for k in d]
    for k in ks:
        print(k)

| | CPython | arm64 and x86-64 (before) |
|---|---|---|
| the three keys | `10 20 30` | `10 100 20` |
| `len([k for k in d])` | `3` | **`3` — correct** |
| `[k for k in d if k > 15]`; `len` | `2` | `1` |
| the same, accumulated | `50` | `20` |
| `{k: 1 for k in d}` walked | `10 20 30` | `10 100 20` |
| `[*d]` walked | `10 20 30` | `10 100 20` |

A dict is a PAIR blob, `[count][k0][v0][k1][v1]…`, and its count is a count of
PAIRS. At the ELEMENT stride a walk alternates keys and values, so bounded by the
pair count it reads `k0, v0, k1` — half the values bound as keys, half the keys
never read.

**The count of the result was RIGHT, and that is the whole measurement.** Three
PAIRS and three WORDS are the same number, so `len` of the buggy list agreed with
CPython. The corpus's only dict-comprehension family, `dict_comp_count`, measures
exactly `len` and a trip count — so no sweep of `containers` could ever have seen
this, and §3.1's fix (which repaired the `for`-in walk's stride) could not have
caught it either. A generator CONDITION is what turned a wrong CONTENT into a
wrong COUNT, which is what made it findable at all: `[k for k in d if k > 15]`
filters the word sequence `10, 100, 20` against `15` and keeps one element where
CPython keeps two.

The four sites, and the reason they drifted: `model.walk_stride` exists for
precisely this question, both `for`-in walkers read it, and its docstring
enumerated its consumers — naming **two**, and saying "and nothing else". Both
named ones were real and both were fixed together, and the enumeration read as
exhaustive, so a comprehension generator and a `*` splice — which yield one
thing per count in exactly the same way and live in different emitters — kept a
hardcoded `LSL #3` / `scale=3` on both backends. **The docstring is part of the
fix** and now names all four, because a consumer it does not name is one nobody
audits. §4.13 is the static check that keeps the two ends of that honest.

### 3.11 `del` destroyed a LOCAL, on x86-64 only, because the lowering used the registers the allocator hands out

**Found:** the `refs` mix, seed `fuzz5` index 9000 — reported as 8 `MISMATCH-X86`
out of 20 programs, with arm64 agreeing with CPython on every one.
**Fixed:** `086cd7f7`, all three x86-64 `del` lowerings.
**Pinned:** `test_formal_x86_64_parity.py` — four rows, one per lowering plus the
reversed declaration order, plus `static_del_scratch_check`.

    def main() -> Int32:
        a = 11
        xs = [0]
        b = 22
        del xs[0]
        print(a, b)          # CPython and arm64: 11 22   x86-64: 11 0
        return 0

`formal/x86_64.py`'s `CALLEE_SAVED` is `(RBX, R12, R13, R14, R15)` and it is the
WHOLE of the allocator's pool — `self._var_regs` maps names onto it and nothing
else. All three `del` lowerings used R12–R15 as scratch, holding a blob base, a
count and an index across a loop. `b`'s home was R13, which the list lowering
loaded with the blob's COUNT and then decremented, so `print(b)` answered 0; move
the `xs = [0]` line above the two integers and the home is R12 and the printed
value is the blob's ADDRESS (13095839192 above) — one defect, two wrong answers,
selected by nothing but declaration order. `del d[k]` and `del xs[a:b]` are the
same class and the same measurement (`11 1` where CPython says `11 22`).

arm64 was never affected, and the reason is what makes the rule statable rather
than a list of registers: arm64's local file stops at X9 and its `del` lowerings
use X10–X15, so the property is "scratch outside the allocator's pool", and x86-64
has no such gap — R8–R11 are the emitter's own and the nine non-callee-saved
registers are enough for every one of these loops.

**Why no existing row caught it.** Every `del` row in
`test_formal_x86_64_parity.py` puts the container and the observation in the same
statement or reads the container back, so none of them can see an unrelated
LOCAL that the `del` overwrote. The four new rows put two integers on either
side of the container and print them afterwards, and `static_del_scratch_check`
reads the three emitters' source — a register-allocation property is not
something four programs can check.

### 4.13 The tool's OWN minimiser reduced a real disagreement to a program CPython cannot run

**Found:** the `refs` sweep, on §3.11's finding. `--minimize` on the program the
sweep saved returned this:

    def mu13(p14, p15, p16):
        print(w25, w30, w38, w39, s1)

**which is not a reduction of anything** — `main` is gone, five names are
undefined, CPython raises `NameError`, and no image can agree with it. The
finding is real and reproducible; the reproducer is not, and §4.12 is the
sibling of this (a record describing a program other than the one on disk).

**Why `_still_fails` accepts it.** `--min-kind x86` asks whether the x86-64
image still disagrees with the ORIGINAL's recorded `want`, and this program
produces no output at all against a `want` that has output — so the test is
satisfied by a program that computes nothing. The two properties a reduction has
to keep are "the disagreement is still there" and "the program still RUNS", and
only the first is checked. The second is one call: `cpython_answer(reduced)`
must produce an answer rather than `("error", …)`.

**What to do instead of trusting `--minimize` on this class**, which is what the
finding was minimised with in the end: a 40-line line-granularity ddmin that
keeps a reduction only when CPython answers it, the x86-64 build succeeds, and
the two still differ. It took the 60-line generated program to 12 lines and then
to the five-line reproducer in §3.11 in about four minutes — so the shape is
right and only the acceptance test is wrong.

### 4.14 A caller's own reading of the oracle's return shape is a coin flip

`cpython_answer` returns `((exit, stdout), stderr)`, and **every caller in the
tool unpacks it first** (`ref, err = cpython_answer(...)`), which is what makes
`ref[0] == "error"` mean "CPython rejected the program": unpacked, `ref[0]` is
either the answer tuple or the literal `"error"`. Reading the nested shape
instead — `has_oracle` on the un-unpacked value — answers **True for a rejected
program**, because `ref[0]` is then the tuple `("error", …)`, which is not the
string `"error"`.

Measured, twice, in the same session: a minimiser written against the nested
shape reported a disagreement on **every** program including
`class H: … def main(): return 0`, and reduced a real x86-64 miscompile to a
one-line `SyntaxError`. The signature is not the problem — `check_one`'s
unpacking makes the convention correct everywhere it is followed — so the
defect is that the convention is invisible at the definition. The fix is a
named accessor (`oracle_answer(ref)` returning the pair or `None`), which cannot
be read the other way.

## 4. FOURTEEN defects in the TOOL, all found by using it

(EIGHT after `sweepG`, THREE more from the fuzz-3 sweep, one more from the
floor sweep and TWO from the fuzz-5 sweep — `## 4` was renumbered each time one
landed, so a §4.9 in this file is the fuzz-3 sweep's, §4.12 is the floor
sweep's, and §4.13-§4.14 are this one's.)

None is a backend bug. Between them they cost more time than the backend bugs
did, and each one made the tool report LESS than it should. §4.5-§4.8 are the
four the `sweepG` arch-parity sweep added, and they share a shape: each one
classified something as a correctly-refused construct that was not one. §4.9-§4.11
are the fuzz-3 sweep's three, and the first of those is the CORPUS's own
invariants being wrong rather than the runner's. §4.12 is the odd one out: it
classified nothing wrongly and simply left the record describing a program
other than the one on disk.

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

### 4.9 A new family's own invariants, and the two of them that were wrong

The ninth of the twelve, and the same SHAPE as §4.1 through §4.4: it is the one a
sweep finds fastest, because a new family is written once and runs immediately:
**two thirds of the programs can be measuring the corpus rather than the
backend.** Both of this session's were found by the checks that are already in
`test_formal_fuzz.py`, which is the argument for having them.

**A preamble copy of the wrong SHAPE turns the family's first statement into a
refusal.** `slice_stmt` declared `S = []` for a name the body assigns
`S = L5[0:2]`. `[]` classifies as the BARE list prefix (`_kind_of_elements` of
nothing is nothing), so the body's binding disagrees with the preamble's and the
value scan calls that a conflict and withdraws the answer — and the first thing a
conflict costs is `len(S)`, the statement the family exists to run. **2 of 2
programs of `--mix slicing` were refused for this**, and `check_mix_builds` is
what said so ("a family that is always refused measures nothing and reports
numbers anyway"). The preamble copy now has the slice's own LENGTH, for the
reason `list_build` already gave.

**A literal outside the word reports the word-size MODEL.** `bignum` masked its
operands with `& 0xFFFFFFFFFFFFFFFF` and included 2\*\*64-1, and one program in a
hundred disagreed:

```python
B = (((18446744073709551615 & 0xFFFFFFFFFFFFFFFF) >> 63) & 0xFFFF)
print(B)     # CPython 1;  both images 65535
```

Three facts, none of them a lowering:

1. a literal that does not fit a signed word is WRAPPED, not refused — measured
   directly, `print(18446744073709551615)` prints `-1` and
   `print(2147483647 << 33)` prints `-8589934592` on BOTH architectures;
2. `-1 >> 63` is an ARITHMETIC shift, while CPython's shift of the unbounded
   2\*\*64-1 is logical and answers 1. The `& 0xFFFF` was masking that
   difference into `65535`;
3. `& 0xFFFFFFFFFFFFFFFF` is the IDENTITY on a non-negative value in CPython and
   is ALREADY WRAPPED to -1 on this path, so the mask moved a negative operand
   positive on one side only — it caused the divergence rather than preventing
   it.

So the fix is the corpus's, and it is the third time in this file that the answer
is "keep the generator inside the modelled subset": the literals are now inside
the word and unmasked, with the fold-back mask only at the end, and the family
still measures the boundary it was written for (2\*\*31, 2\*\*32, 2\*\*63-1, the
negatives, and shift counts up to 63).

**Two more corpus invariants the same hour, recorded because they cost programs
rather than sweeps.** An `else` after a plain statement is a syntax error in
CPython, so `loop_nested`'s inner arm had to belong to an inner LOOP (48 of the
first 80 `loopelse` programs failed to compile); and a `return` inside `main`'s
body truncates the program there, so the `try_finally_return` arm moved into a
helper — dead code on both engines measures nothing.

**And a third, from the dict-unpack family (§3.9): a dict literal with a
DUPLICATE key.** `rng.choice` drew `""` twice for the two keys in 21 of 100
programs; a dict with one pair then fails a 2-element unpack in the ORACLE
("not enough values to unpack"), so 21 of the sweep's programs were
`generator-error` — the corpus measuring itself. `rng.sample` over the non-empty
words cannot collide with itself, and the preamble copy carries the same two
keys for the reason every other preamble copy does: a walk that reaches the blob
before the statement that fills it reads the pair COUNT first, and a count that
differs between the two copies is a different program.

### 4.10 A `TIMEOUT` was reported about the SCHEDULER

The tenth defect, and the only one in this file that is about the harness rather
than about the corpus or the backend: **the tool believed a timeout on the first
observation.** Measured on the `strfmt` row of §2.1 — 5 `TIMEOUT` verdicts out of
100 programs at `--stmts 30 50`, all five of which:

* run in **0.58 s or less** (four of them in 0.01 s), on both architectures,
  repeatedly, timed directly;
* re-ran as `match` the moment the sweep was asked for those five indexes
  alone (`--seeds 7480-7484`, `-j 2`: 5 match), with CPython's own output as the
  oracle and both images agreeing with it.

A 0.01 s program does not become a 30 s one, so what the tally said was about
the machine — this sweep ran `-j 4` alongside other work on a shared box, and
`RUN_TIMEOUT` is a wall-clock limit measured against a scheduler the tool does
not own. It was NOT a finding (`classify` counts `TIMEOUT` apart from
`MISMATCH-*`), so the run still exited 0 and nothing was claimed as a defect; but
it was in the table as a fact, and a fact that is a measurement of the weather is
worse than no fact.

`run_on` now re-runs a timeout once and believes the verdict only if the second
run agrees. A program that times out twice is still a `TIMEOUT` and is still not
a finding — it is now a statement about the program. The same re-run argument
would apply to a BUILD timeout, and does not yet: a build that exceeds 120 s is
expensive enough to be worth believing, which is the only reason it is spelled
one way and not the other.

### 4.11 The `strings` mix at scale: 27 `MISMATCH` out of 100, and every one is a class this file already names

The first sweep here at the `strings` mix's own scale (100 programs, seed
`sweep19c` 7800-7899, `--max-min-steps 30`): **52 `KNOWN:str_subscript`, 27
`MISMATCH-X86`, 21 `match`.** Characterised by reading all 27 reproducers:

| how many | what the reproducer is | which section |
|---|---|---|
| 21 | a `def` whose body the MINIMISER stripped of its `return`, so `print(helper(...))` is the no-`return` bug | §3.3 — filed, deliberately not in `KNOWN_DIVERGENCES` |
| 6 | the `str_subscript` divergence itself, in a spelling the neutraliser cannot take apart | §3.1's row, and §4.4's attribution limit |

**No new backend bug is in there, and the fact that 27 rows had to be read by
hand to establish that is the finding.** Both classes are known and both are
properties of the ATTRIBUTION, not of the backends:

* the no-`return` class is reachable only through the minimiser (§3.3 says so
  and measured it), which is also why it has no `KNOWN_DIVERGENCES` row — a row
  the corpus cannot trigger is a row that has stopped measuring, and this is the
  proof: the minimiser triggers it constantly and `blame` has no way to name it;
* the six are the known byte-vs-character divergence in a reduced program where
  the neutraliser's precondition (the `print(<name>[<literal>])` spelling with the
  name bound by its own literal statement) no longer holds, so a REAL known bug
  is reported as unexplained. One extra report rather than one hidden bug is the
  documented direction to err in (§"What the blame cannot do").

The cheap improvement is a second marker on the no-`return` shape — the corpus
can produce it by emitting a helper whose body ends without a `return`, which is
exactly what the minimiser discovered — but that is a change to what the corpus
measures, so it belongs in a session whose claim is the corpus rather than one
commit at the end of another.


### 4.12 The reproducer on disk is the SHRUNK program and the recorded answers are the ORIGINAL's

**Found 2026-10-04** by trying to rebuild one of §2.1a's 34 findings. The
finding says

```
      want  exit=0 '3\n4095 28 3 5 -8\n…'
      x86_64  exit=0 '3\n4095 28 3 5 -8\n…'
```

and `programs/p9011.mojo` is 894 bytes against `reduced_from: 1966` — so the file
on disk cannot print the `3\n` the record quotes, and building it answers
something else. It is not a stale-file artefact and not a mis-minimised predicate:
`check_one` records `want` and `results` for the ORIGINAL text, then shrinks, sets
`rec["text"] = small`, and writes that. The comment beside the write says "the
minimised text is kept on the record so the reproducer on disk is the one the
verdict is about", and **that is half true** — the VERDICT is reproduced (the
shrinker's predicate is `(verdict, diagnostic)` per backend, so the reduced
program fails the same way) and the OUTPUTS are not.

That is §4.4's and §3.6's failure again and not the same instance of it: those
are about the shrinker accepting a *trap* and landing somewhere that disagrees
for a different reason, and this is about the RECORD — a reader who takes the
reproducer at its word spends ten minutes looking for a defect that is not in it.
Three things would fix it and the cheapest is first:

1. **re-run the reduced program and record ITS answers too**, so the record
   carries both and a mismatch between them is visible in `findings.json` rather
   than in the next reader's afternoon. `check_one` already has the machinery;
   `blame` re-builds the reduced program on every attribution, so the cost is one
   extra build per finding, and findings are rare by construction.
2. Or state the rule in the record: `want`/`results` describe the program the
   finding is ABOUT and the file is a REDUCTION whose answers are not recorded —
   which makes the comment above true by weakening it.
3. Or keep both programs (`p9011.mojo` and `p9011.reduced.mojo`), which costs one
   more file per finding and nothing else.

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

The two that have an ANSWER as well as a refusal are now generated both ways,
which is the distinction worth keeping: `strmeth`/`strfmt` and `slicing` measure
the five lowered string methods and a list slice as lowerings, while `limits`'s
`slice_print` measures the same slice as the refusal it is when the slice
EXPRESSION is what `print` is handed. One construct, two questions, two mix
names, one generator each (`slice_stmt` against `limits_stmt`) — the two were
the same name on two branches, and a name two generators answer to is a name
whose arm depends on which `elif` reached it first. `limits`' recorded row
(`sweepG` 8000-8099) is therefore reproducible up to that rename, because a mix
name is part of the program's seed (`make_program` seeds on
`f"{seed}:{index}:{mix}"`) and the weights it draws from changed with it.

**What would be the next thing to generate**, in this ledger's order — `while`/`else`
and `for`/`else` are no longer on it (§5.1: `loopelse`, 600 programs clean) — a
`with` statement (measured: it is
REFUSED with a message that names the protocol and the remedy, and it needs a
context manager CPython can also run, which is why `limits` leaves it out — a
`with 1 as w` is a `TypeError` in CPython and would take the program's verdict
with it), a `try`/`except` shape (NOW GENERATED — `limits`' `try_handler`, which
is the single largest row in its construct mix at 114 of 190 refusals, so the
next thing to vary there is the arm body), a comprehension whose generator has a
CONDITION over a dict walk (NOW GENERATED — `comps`' `comp_cond`, and it is what
found §3.10), a `global` container mutated through two different helpers, an
INHERITED class (`class B(A)` — probed on both architectures and it DROPS the
base's fields and methods: `b.m()` reads `1` where CPython reads the inherited
value, exit 0 on both, filed as a separate doc rather than fixed here), a
comprehension whose target is over a string-keyed dict (§5.1), and
`len()` of a subscript of a list of lists (`inner = rows[0]; len(inner)` is
REFUSED on both backends with "classified as 'int'", which is a kind rule and not
a family). Each is a family whose absence from this table is a coverage hole
rather than a decision.

### 5.1 What the fuzz-3 sweep closed in this list, and what is still open

**Closed by the nine new mixes** (§2.1): `while`/`else` and `for`/`else`
(`loopelse`, 400 programs clean), `try`/`finally` (`tryfinally`, 200 clean — the
`try`/`except` half stays refused, which is the decision above and not a gap),
and string formatting (`strfmt`, 300 clean; `fstrings`, 300 refusals by design).

**Still open, each with the measurement that says why it is a LIMIT rather than a
gap.** All three were probed on both architectures before this list was written,
which is what makes them entries rather than guesses:

| construct | what the backends do | why it is not a family |
|---|---|---|
| `nonlocal` | REFUSED on both: "unsupported statement NonlocalStmt" | no lowering exists, so a mix would measure one refusal per program |
| a `try` whose HANDLER would run | the operation TRAPS (exit 1, nothing printed) where CPython takes the handler and prints `0` | this path has no exception VALUES, so the only way to reach a handler is a trap — and a program whose answer depends on a trap is not a differential test |
| float formatting | a `double` is a word here: `print(1.5)` truncates | the tool's docstring's reason, and it stands — a fuzz oracle built on a truncated float measures the model |
| an integer that does not fit the word | WRAPPED, silently (`print(18446744073303095535)` prints `-1`) | `formal/model.py`'s deliberate word model; §4.9|

The `nonlocal` row is a one-line refusal message away from a family, and it is
the cheapest of these to close: `NonlocalStmt` is refused by name in both
emitters' statement dispatch, so the decision is one function in
`formal/model.py` and a `formal/model.py`-level lowering of a captured cell
(which the closure flattening already builds for a closure — §3.7's fix is in the
same table). Filed as the next thing to generate rather than fixed here, because
it is a FEATURE and this sweep's claim is the corpus.

## 6. Reproducing a row

    python3 tools/memslot.py --gb 4 --label fz -- \
        python3 tools/formal_fuzz.py --mix <mix> --seed <seed> \
            --seeds <lo>-<hi> -j 2 --work .tmp/fz/<mix>

`make_program(seed, index, mix, stmts)` is a pure function of its arguments, so
every row above re-runs byte for byte on any machine. The `--seed` is part of the
row: two sweeps of the same mix with different seeds are two corpora, and the
seed ranges here are disjoint so no row double-counts another's programs.
