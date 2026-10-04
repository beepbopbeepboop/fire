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

**4032 programs over 13 sweeps.** Two bugs fixed, two limits filed, and four
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

## 4. Four defects in the TOOL, all found by using it

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
in the refusal — `model.string_concat_refusal`), a dict grown by a subscript
store of a new key (`bugs/FORMAL_a_dict_store_of_a_new_key_is_a_run_time_miss.md`),
an `append` inside a loop (a blob's capacity is the number of append SITES and
every execution counts), a name bound by TWO dict literals
(`model._note_dict_init` retracts the initializer, so a `for` over such a dict
has no answerable key kind — 15 of 40 programs until the mix was changed to bind
a dict once), `struct`/`var` (CPython cannot parse it), floats, pointers, and file
descriptors.

**What would be the next thing to generate**, in this ledger's order: `while`/`else`
and `for`/`else` (the corpus emits neither), a `with` statement, a `try`/`except`
shape (the model never emits an except arm per
`bugs/FORMAL_except_arm_is_never_emitted.md`, so it would measure a refusal), a
comprehension whose generator has a CONDITION over a dict walk, and a
`global` container mutated through two different helpers. Each is a family whose
absence from this table is a coverage hole rather than a decision.

## 6. Reproducing a row

    python3 tools/memslot.py --gb 4 --label fz -- \
        python3 tools/formal_fuzz.py --mix <mix> --seed <seed> \
            --seeds <lo>-<hi> -j 2 --work .tmp/fz/<mix>

`make_program(seed, index, mix, stmts)` is a pure function of its arguments, so
every row above re-runs byte for byte on any machine. The `--seed` is part of the
row: two sweeps of the same mix with different seeds are two corpora, and the
seed ranges here are disjoint so no row double-counts another's programs.
