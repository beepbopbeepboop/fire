# FORMAL_fuzz_ledger: what `tools/formal_fuzz.py` has measured, and what came of it

**This is the ledger the differential fuzzer's sweeps are recorded in.** One row
per sweep (mix, seed range, programs, both architectures, the tally as the tool
printed it), then one entry per finding with what happened to it — fixed with a
commit, or filed as a bug doc. A sweep that is not here did not happen, and a
finding that is not here was not found by this tool.

It exists because a fuzzer's results are otherwise invisible: the tool prints a
tally and writes `findings.json` under `--work`, which is a temporary directory
by the next run. The numbers are also the only record of what the corpus
COVERS, which is the thing that decays silently — a mix that stops producing a
construct reports the same clean tally as one that never produced it.

## 1. The rule this ledger keeps

A row here is a MEASUREMENT of a run, never a target. A clean tally is not
evidence that a mix is correct; it is evidence that the corpus ran. What makes a
row worth reading is the mix beside it: `containers` 487/500 with 13 refusals
is a better row than `globals` 500/500, because the first one is where two
silent miscompiles and one one-sided refusal came from.

The anti-rot is the same as `KNOWN_DIVERGENCES`': **a construct in this corpus
that stopped being generated is invisible here**, so a mix that is deleted must
be deleted with its reason, and a construct added must show up in a sweep.

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7, every sweep `-j 2` and both
backends (`--backends x86_64,arm64`) unless the row says otherwise. Peak memory
across every sweep in this file: **0.1 GB** (`tools/memslot.py --gb 4`), so
none of it is anywhere near the 3-4 GB line.

| date | mix | seed | indexes | programs | tally | what came of it |
|---|---|---|---|---|---|---|
| 2026-10-03 | `core` | `formal-fuzz` | 0-299 | 300 | 300 match, 0 refusal | nothing |
| 2026-10-03 | `calls` | `formal-fuzz` | 0-299 | 300 | 300 match, 0 refusal | nothing |
| 2026-10-03 | `containers` | `sweepA` | 1000-1499 | 500 | 487 match, 13 refusal, 0 findings | the 13 refusals were one bug, on one architecture only — §3.1 |
| 2026-10-03 | `globals` | `sweepA` | 1000-1499 | 500 | 500 match, 0 refusal | nothing |
| 2026-10-03 | `core` | `sweepB` | 2000-2299 | 300 | 300 match, 0 refusal | nothing |
| 2026-10-03 | `calls` | `sweepB` | 2000-2299 | 300 | 300 match, 0 refusal | nothing |
| 2026-10-03 | `lists` | `sweepB` | 2000-2299 | 300 | 300 match, 0 refusal | nothing |
| 2026-10-03 | `classes` | `sweepB` | 2000-2299 | 300 | 300 match, 0 refusal | nothing |

The first three rows of the table are a BASELINE, not a result: they ran on
master's corpus with the five new mixes absent, which is what "the corpus
covered arithmetic, control flow, calls, one-word containers and a `class`"
costs in programs that could not be generated at all.

## 3. Findings

Three, in the order they were found. Each is a SILENT wrong answer or a
one-sided refusal — not a crash, not a diagnostic — because that is the class
this tool exists for and the class every other suite here misses.

### 3.1 A walk over a dict read `k0, v0, k1` — and a membership test's bound was its own needle

**Found:** `containers` sweep, seeds 1000-1499, plus hand-probing once the
construct was in the corpus at all.
**Fixed:** `3d49db7c` (`formal: a walk over a dict steps by the PAIR, and its
bound is not the needle`).
**Pinned:** `test_formal_value_model.py` — six cases, both backends, against
CPython.

| | CPython | arm64 | x86-64 (before) |
|---|---|---|---|
| `d = {10: 100, 20: 200}` ; `for k in d: print(k)` | `10 20` | `10 100` | `10 100` |
| `d = {30: 1, 10: 2, 20: 3}` ; `for k in d: print(k)` | `30 10 20` | `30 1 10` | `30 1 10` |
| `d = {"bb": 1}` ; `for k in d: print(k)` | `bb` | `bb` | `4302697832` |
| `xs = ["ab", "cde"]` ; `"zz" in xs` | `False` | `False` | **SIGSEGV** |
| `xs = [10, 20]` ; `999 in xs` | `False` | `False` | `False`, after reading 999 words of frame |

Three defects, one area:

1. both backends' `_emit_for_list` stepped one WORD over a dict's PAIR blob;
2. a `for` target over a dict classified as an INTEGER (a dict is a bare
   `list`, and nothing read the keys), so a string key printed as an address
   and `len(k)` was refused;
3. x86-64's membership scan held the COUNT in `R10` and reloaded the NEEDDLE
   into `R10` inside the loop, so from the second iteration the exit test was
   `i >= needle`.

The third is the one worth remembering: **a HIT was right by luck**, because the
runaway scan reaches the next element on the way past the end. A corpus whose
membership tests all hit would have reported nothing.

### 3.2 A comprehension in an `elif` arm reserved no temps on x86-64

**Found:** `containers` sweep, seed `sweepA` index 1083 — reported as a plain
`refusal`, which is §4's subject.
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

`IfStmt.elifs` is a list of `(cond, body)` TUPLES, and the reservation walk's
tuple branch handed the `body` LIST straight to a function that only descends
into dataclass fields. arm64's copy of the same walk has had a
`isinstance(node, list)` arm for this exact reason since the day its own
comprehension-temp bug was fixed.

### 3.3 A function with no `return` yields a word where CPython yields `None`

**Found:** `strings` mix, seeds 0-3 — and **not from the generator**: the
generated program agreed everywhere except one `print` of a call's result, and
the disagreement appeared only after the minimiser deleted a `return` from a
helper. A finding reached through the minimiser is a finding about a construct
the corpus does not cover.
**Filed, not fixed:** `bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`.

`print(g(1, 2))` for a `g` with no `return` prints `0` on both images and
`None` in CPython, exit 0 on all three. It is deliberately NOT a
`KNOWN_DIVERGENCES` row: `Gen.define_function` always emits a `return`, so the
corpus cannot produce the construct and a row nothing can trigger is a row that
has stopped measuring.

## 4. Two holes in the TOOL, both found by using it

Neither is a backend bug, and both cost more than the bugs did.

**A one-sided refusal was not a finding.** `classify` returned a plain
`refusal` whenever any engine refused, so "arm64 answers, x86-64 declines" —
the divergence `test_formal_x86_64_parity.py` is built around — counted as a
clean run. That is how §3.2 sat in a sweep's `programs/` directory looking like a
routine refusal. There is now a `REFUSAL-DIVERGES-<engines>` verdict, and it
fires only when one engine ANSWERS and another refuses, because a refusal every
engine agrees on is still a correctly-refused construct.

**A refusal divergence could not be minimised.** `_still_fails` had no predicate
for a refusal, so `--minimize` reported "the program does not fail here any more"
about a program that still failed. Fixing that needed two further things, both
measured on this reproducer rather than reasoned about:

* *"still refuses" is not a predicate.* With one backend under `--min-kind x86`,
  ANY refusal satisfies it, and the shrink walked out of `_cb0 has no home` into
  a different refusal. The predicate is now the original program's
  `(verdict, diagnostic)` per backend, compared on the first 40 characters of
  the message.
* *A candidate that does not PARSE satisfies everything.* `_statement_spans`
  builds a span from a block's opening line to each line inside it, so deleting
  a body's first statement deleted the `def` line with it. The result does not
  compile, which the old mismatch path rejected by accident and the new refusal
  path did not. `_still_fails` now compiles the candidate before building it.

## 5. What the corpus still cannot say, and what it costs to run

**The `strings` mix costs ~70 s/program** — 282 s for four programs, against
~1 s for `core` — because every `KNOWN:str_subscript` program pays for a
`shrink` (up to 400 candidate builds) and then a `blame` (one build per known
construct, plus one per construct on its own). A 300-program sweep of it is six
hours; the first attempt at one was killed after 2.4 hours having finished
`core` and `calls`. **A sweep of `strings` must be counted in tens, not
hundreds**, and that is a property of the attribution machinery rather than of
the corpus. The obvious fix is to shrink a `KNOWN:` program less (the reduction
buys attribution nothing when the construct is already named by the first
neutralisation that agrees), which is a change to `shrink`'s budget rather than
to its predicate.

**`environ` costs 7 s/program** (221 s for 30), because a program that imports
`os` pays for the host module's dylib on every build and this tool has no
build cache. Its sweeps are a tenth the size of `core`'s for the same build
count.

**The corpus cannot produce:** a function with no `return` (§3.3), a string
concatenation or a length-dependent string method (refused, with the
measurement in the refusal), a dict grown by a subscript store of a new key
(`bugs/FORMAL_a_dict_store_of_a_new_key_is_a_run_time_miss.md`), an `append`
inside a loop (the blob's capacity is the number of append SITES), a name bound
by TWO dict literals (`model._note_dict_init` retracts the initializer, so a
`for` over such a dict has no answerable key kind), `struct`/`var` (CPython
cannot parse it), floats, pointers, and file descriptors.

**What would be the next thing to generate**, in the order this ledger would put
it: a `try`/`except` shape (the model refuses an except arm per
`bugs/FORMAL_except_arm_is_never_emitted.md`, so it would measure a refusal),
`while`/`else` and `for`/`else` (the corpus emits neither), a `with` statement,
and a comprehension over a DICT walk with the key in a condition. Each is a
family whose absence from this table is a coverage hole rather than a decision.
