# FORMAL_metamorphic_ledger: what `tools/formal_metamorph.py` has measured, and what came of it

**This is the ledger metamorphic sweeps are recorded in.** One row per sweep (corpus, seed, index range, programs, pairs, both architectures, the tally as the tool printed it), then one entry per BACKEND finding with what happened to it, and one for each defect the TOOL turned out to have — because those cost more than the backend bugs did and a metamorphic tool's own defects are invisible in a tally of passes.

`bugs/FORMAL_fuzz_ledger.md` is the differential fuzzer's ledger and the two read together: `formal_fuzz` asks "does the image answer what CPython answers", this one asks "do two builds of the same meaning answer the same". See §3 for why the second question reaches a class the first cannot.

## 1. The rule this ledger keeps

A row is a MEASUREMENT of a run, never a target. What makes a row worth reading is the TRANSFORM table beside it, not its tally: a run where `inline_helper` skipped every program and one where it answered 200 pairs are the same tally, and the second measured something the first did not.

The anti-rot is the per-transform table the tool prints on every run, which is why `test_formal_metamorph.py::MUST_APPLY` exists: a transformation that stops applying reports the same clean tally as one that never worked. `test_no_transform_is_measured_on_nothing` checks that the table of "must apply somewhere" and the table of transformations cannot drift apart in either direction.

## 2. Sweeps

Machine: 18-core arm64 macOS, `python3` 3.14.7. Every sweep `-j 6` and BOTH backends. Peak memory across every sweep in this file: **0.2 GB** (`tools/memslot.py --gb 8`, which kills at 8), so nothing here is within an order of magnitude of the 3-4 GB line in `bugs/PERF_memory_over_4gb_is_a_bug.md`.

**Sweep 1** — `calls`, seed `metamorph`, indexes 0-59, `--stmts 8 14`, **600 pairs**, 265.6 s. 60 match, 0 findings. Peak 0.2 GB.
**Sweep 2** — `formal/examples`, **41 programs / 410 pairs**, 153.2 s. 41 match, 0 findings, 1 program carrying a pre-existing `DIVERGENCE` (`udivmod`, §4). Peak 0.1 GB.
**Sweep 3** — the remaining twenty mixes at 20 programs each: `core`, `lists`, `classes`, `containers`, `globals`, `generics`, `strmeth`, `signed`, `strings`, `argshape`, `slicing`, `closures`, `unpack`, `bignum`, `chains`, `loopelse`, `tryfinally`, `strfmt`, `fstrings`, `limits`, **4000 pairs**, 20 mix runs. 0 findings, 0 `transform-invalid`, 0 `transform-crash`.

Total on the tool's own sweeps: **5010 pairs over 22 corpora, both architectures**. Peak 0.2 GB.

## 3. What metamorphic testing reaches that differential testing cannot, and the measurement

`formal_fuzz` finds a miscompile only where the program PRINTS the value whose lowering is wrong. That is a property of the program, not of the backend, and it is structural: a register-allocation bug in a frame slot the program never prints is invisible to a corpus whose programs all have the same shape.

The measurement that the two questions are not the same question, and that this one is not a slower version of the other:

* **`if True:` was read as a branch by `read_before_store`'s CFG**, so a store inside a constant-true guard did not dominate the reads after it. Every such program was REFUSED — on BOTH architectures — with a sentence asserting "CPython raises UnboundLocalError for that program", which is false. Found as `TWIN-DIVERGES` on **8 of 30** programs of a `calls` sweep (one machine lowered the original and refused the twin), minimised to 12 lines, fixed at the root in `formal/model.py::_build_cfg`, with ten regression rows (six in `test_formal_read_before_store.py`, three each way, and four in `test_formal_run.py` on both backends). **The oracle would not have found it**: the program is one `formal_fuzz` would generate, and `formal_fuzz` reports a refusal as a refusal — a correct answer to "does the image compute this program", not a bug.
* **`k = -1` bound nothing in the CFG's preheader table**, so `for i in range(k)` with `k = -1` was undecidable, the loop target was treated as bound, and a read of `i` after the loop was accepted — on a program CPython refuses with `UnboundLocalError` for every probe value. Found by the same fold (`_cfg_int_literal` gained `UnaryOp('-', IntLiteral(1))`, which `_range_is_nonempty` had been folding for itself). Before/after table in `formal/model.py`'s docstring; rows `for_range_bound_decided_negative_refused` / `_positive_ok`.

## 4. The one `DIVERGENCE` in the examples sweep, and why it is not filed here

`formal/examples/udivmod.mojo` is `(n / 7) + (n % 7)` over `0`, `5`, `-5`. CPython answers `0.0`, `5.714…`, `1.285…`; both images answer `0`, `5`, `2`. `/` is INTEGER division on this path, and `n % 7` takes the sign of the divisor.

This is a real disagreement and it is **not** this tool's to file or attribute: `formal_fuzz.py` owns the differential queue with its own `KNOWN_DIVERGENCES` / `neutralise` / `blame` machinery, and this is a semantics gap in both backends rather than an x86-64 bug. So the tool reports it as `DIVERGENCE-<ARCH>` — counted, printed, named as `formal_fuzz`'s queue, and excluded from its own exit status. An earlier version reported it as a finding, which is the failure this split exists to prevent: see §5.

## 5. Defects in the TOOL, which cost more than the backend bugs and are invisible in a tally

Eleven, all caught by the tool's own CPython gate (`CPython(P) == CPython(T)`, run on BOTH sides before any backend is asked) or by the examples/classes/closures corpora. The gate is the reason each of them is a unit-test failure rather than a filed bug.

| # | what | how it showed | verdict it would have produced |
|---|---|---|---|
| 1 | `rename` renamed a parameter's USES but not its `ast.arg` | 6 of 30 `calls` programs, `not-answerable` | a `NameError` twin reported as a tool result |
| 2 | `global G` read as a LOCAL (the declaration is line 1, the conflicting store line 9) | 1 `globals` program, `not-answerable` | `rename` rewriting a global's reads |
| 3 | a `DictComp` has neither `elt` nor `keywords` | 6 programs, `transform-crash` | the whole `containers` mix unmeasurable |
| 4 | `reorder` treated `print(…)` beside `print(…)` as independent | 13 programs, `transform-invalid` | **every** backend bug |
| 5 | `reorder` read `L8[0] = 31` as a statement that writes nothing | 2 `lists` programs | the same |
| 6 | `reorder` swapped `c = 9` past the call that reads a closure's cell | 1 hand-written program | the same |
| 7 | `reorder` swapped `G = 57` past a call that mutates `G` from another function | 2 of 20 `globals` | the same |
| 8 | `inline_helper` substituted parameters one at a time and CAPTURED (`f(b, 2)` into `f(a, b)`) | 4 `closures` programs | the same |
| 9 | `inline_helper` asked the PROGRAM's parent index about a fresh subtree, so no substitution happened at all | 4 `closures` programs | a twin with a raw parameter name |
| 10 | a comprehension's target was bound in the ENCLOSING function, and a PEP 750 `TemplateStr` was invisible to the "source text" check | 9 `fstrings` + hand-written corpus | `rename` renaming half a name |
| 11 | `extract` deleted a binding a nested scope captures | 7 of 20 `closures` | a printed number moving |

Plus three that were about the TARGET's representation rather than the transforms, and would have been filed as backend bugs:

* **a constructor's body is INLINED at the construction site** (`formal/build.py`), so its shape IS the construction. `if_true` / `noop_loop` / `dead_local` inside `__init__` were declined — correctly, with a message naming the construct — and the tool was calling that `TWIN-DIVERGES`. Now `_is_constructor`.
* **a method's receiver is identified by the NAME of its first parameter** (`formal/model.py::RECEIVER_PARAMETER_SPELLINGS`), so `rename` deleted it: 20 of 30 `classes` programs came out `TWIN-DIVERGES` with `C5.m15() is declared with parameters and no receiver`. The spellings are imported, not re-spelled.
* **`_loop_target_defs` / the loop-target question** — not reached; recorded here because the `if <constant>:` rule touches the same preheader machinery and a reader should know the sweep did not exercise it.

## 6. Where the ledger's numbers came from, and what would change them

Every row in §2 is reproducible from the seed and the index range:

    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 60 --mix calls --stmts 8 14 -j 6
    python3 tools/memslot.py --gb 8 --label mm -- python3 tools/formal_metamorph.py \
        -n 0 --examples formal/examples -j 6

`tools/formal_metamorph.py --list-transforms` says what each transformation is FOR; `test_formal_metamorph.py` asserts that the soundness property holds over a hand-written corpus of 14 programs (one per documented rule), every generator mix, and every drivable example.

**What is NOT measured here**, and is the next thing a session should do:

1. **No `formal/examples` example that spells Mojo-only syntax** (8 of 52: `var`, `fn`) — CPython's parser declines them, so they are reported as unmeasured with the reason rather than dropped. Transforming them needs a transform that works on `fire_compiler`'s AST, which is a second implementation of the nine transformations and not a thing this ledger should quietly acquire.
2. **Two examples whose own `main` takes arguments** (`twoparams`, `subscript_var`) — measuring them properly means threading `-n` through the shared `formal_fuzz` harness (`build(test_input=…)` and `cpython_answer(args=…)` both take it) rather than writing a second harness here.
3. **`swap_add` reaches 8 of 41 examples and 43 of 60 `calls` programs.** The limit is `Analysis.int_only`: a parameter is classified as integer only when every call site passes an integer literal, and the corpus's `x = x & 0xFFFF` idiom makes most operands non-literal-derived. Widening it needs either more type inference or accepting a predicate that is coarser than "provably int", and the second would put the oracle to work on most of the corpus.
4. **No metamorphic sweep of the stdlib.** `formal/hostmods/*.mojo` is the largest body of real source this backend must keep working, and a metamorphic pair over it needs the import machinery the fuzzer does not have.
5. **`inline_helper` and `def_order` reach 8 and 23 of 41 examples but skip most generated programs** — the corpus has few single-`return` helpers and few top-level definition runs. A corpus with more of either would measure more; adding mixes is `formal_fuzz`'s call, not this ledger's.