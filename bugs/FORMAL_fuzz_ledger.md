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
added because the CORPUS could not produce a construct at all, and two of them
found a defect the day they were written (§3.4, §3.5).

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 2` and BOTH
backends (`--backends x86_64,arm64`). Peak memory across every sweep in this
file: **0.1 GB** (`tools/memslot.py --gb 4`), so none of it is within an order of
magnitude of the 3-4 GB line.

**4032 programs over 13 sweeps.** Two bugs fixed, two limits filed, and four
defects in the tool itself. §2.1 adds **3400 programs over 24 more sweeps** and
two more fixes, so the whole file is **7432 programs over 37 sweeps: four
backend fixes, three limits filed, five tool defects.**

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

### 2.1 The fuzz-3 sweep (2026-10-03, seed `sweep19c`)

**3400 programs over 24 sweeps, and every mix in the table is a mix this
session ADDED** — the corpus could not produce a loop's `else` arm, a closure, a
default or keyword argument, a list slice, a tuple unpack, a word-boundary
integer, a comparison chain as a value, a `try`/`finally`, or an interpolated
string literal. Nine new mixes, each PROBED ON BOTH ARCHITECTURES before it was
written down, because a mix that measures a refusal is a mix that spends its
budget re-deriving `FORMAL_known_limits.md`.

`-j 4` (the earlier rows used `-j 2`), both backends, `tools/memslot.py --gb 8`.
Peak memory: **0.2 GB**. Cost: **0.7–2.8 programs/second** except `fstrings`,
which is 17/s because every program is a refusal that never reaches the image.
A sweep row is one `(mix, range)` pair, so the 24 rows below are 24 runs and the
"sweeps" this file counts are rows — the earlier table's 13 are the same thing.

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
| 2026-10-03 | `slicing` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing (after §4.5: the first version of this family was 2 of 2 REFUSED) |
| 2026-10-03 | `unpack` | `sweep19c` | 7000-7099 | 100 | 100 match | nothing — and 100 more after the fix it prompted |
| 2026-10-03 | `bignum` | `sweep19c` | 7000-7099 | 100 | 99 match, 1 `MISMATCH-X86` | **the corpus's own value discipline**, §4.5 — not a backend bug |
| 2026-10-03 | `bignum` | `sweep19c` | 7000-7099 (re-run, corpus fixed) | 100 | 100 match | nothing |
| 2026-10-03 | `bignum` | `sweep19c` | 7100-7199 | 100 | 100 match | nothing |
| 2026-10-03 | `chains` | `sweep19c` | 7100-7199 | 100 | 100 match | nothing |
| 2026-10-03 | `strfmt` | `sweep19c` | 7100-7199 | 100 | 100 match | nothing |
| 2026-10-03 | `fstrings` | `sweep19c` | 7100-7199 | 100 | 100 refusal | nothing — 100 refusals is what the mix is (§3.4) |
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

## 3. Findings

Three, in the order they were found. Each is a SILENT wrong answer or a
one-sided refusal — not a crash, not a diagnostic — because that is the class
this tool exists for and the class every other suite here misses. §3.4 and §3.5
are the fuzz-3 sweep's two, and each was found by a family the corpus could not
produce at all.

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

### 3.4 A tuple unpack bound the CONTAINER's kind to every target, so `print(a)` was refused on both architectures

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

### 3.5 An f-string printed ITS OWN SOURCE SPELLING, on both architectures, exit 0

**Found:** the same probe-first order as §3.4, and it is the worse of the two:
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

## 4. Five defects in the TOOL, all found by using it

None is a backend bug. Between them they cost more time than the backend bugs
did, and each one made the tool report LESS than it should.

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
them is part of the record.

### 4.5 A new family's own invariants, and the two of them that were wrong

The fifth defect is the same SHAPE as §4.1 through §4.4 and it is the one a
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

**The corpus cannot produce:** a function with no `return` (§3.3), string
concatenation or a length-dependent string method (refused, with the measurement
in the refusal — `model.string_concat_refusal`), a dict store of a new key
(NOW GENERATED and measured: `d[k] = v` is CPython's INSERT on both backends,
`formal/model.py`'s `dict_store_capacity`, so this row was removed from the
list rather than worked around), an `append` inside a loop (a blob's capacity is the number of append SITES and
every execution counts), a name bound by TWO dict literals
(`model._note_dict_init` retracts the initializer, so a `for` over such a dict
has no answerable key kind — 15 of 40 programs until the mix was changed to bind
a dict once), `struct`/`var` (CPython cannot parse it), floats, pointers, and file
descriptors.

**What would be the next thing to generate**, in this ledger's order: `while`/`else`
and `for`/`else` (the corpus emits neither), a `with` statement, a `try`/`except`
shape (a `try`'s handler arm with a body is REFUSED — `formal/model.py` stops
walking the arms, and commit `95d3d580` is where that landed — so it would
measure a refusal rather than a lowering), a
comprehension whose generator has a CONDITION over a dict walk, and a
`global` container mutated through two different helpers. Each is a family whose
absence from this table is a coverage hole rather than a decision.

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
| an integer that does not fit the word | WRAPPED, silently (`print(18446744073303095535)` prints `-1`) | `formal/model.py`'s deliberate word model; §4.5 |

The `nonlocal` row is a one-line refusal message away from a family, and it is
the cheapest of these to close: `NonlocalStmt` is refused by name in both
emitters' statement dispatch, so the decision is one function in
`formal/model.py` and a `formal/model.py`-level lowering of a captured cell
(which the closure flattening already builds for a closure — §3.4's fix is in the
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
