# PERF_formal_import_asks_are_products_of_the_closure: a formal build asked per-MODULE questions about the module ONCE, and the tokenizer was half the build

**Class:** performance. **Area:** `formal/monomorph.py` — **the two costs below
are FIXED**, in `a829a0b7` and `dcc27620`, byte-identical on both
architectures. What is left is four residues, each MEASURED, each with its
exact next step; three of the four live in `formal/imports.py`, which another
worker holds, and §5 says why they were not taken here.

Round 2 of the cost pass whose round 1 is
`bugs/FORMAL_build_cost_2026-10-03.md` (that doc's §2 and §6 are about
`formal/build.py` and `formal/model.py`, and this one is about the import
closure in front of them). **Re-measured on master first, and the picture had
moved: the costs that doc found are no longer the top of the profile, and the
top is somewhere it never looked.**

---

## 1. Re-measurement, 44 files, both architectures

**The base these numbers were taken on is `3c3516db`, and master was 27 commits
ahead of it by the end of the pass** (the integrator merged `work/formal19-1`,
`work/formal19-2`, `work/gatefix5` and others underneath). §4a and §4b were
re-read against master's tip and are still open there; §4c was closed there
while this pass ran and says so. Every measurement below is a measurement of
`3c3516db` plus this branch's three commits, and the two fixed costs are
behaviour-preserving (byte-identical artifacts, §2.2), so the fix composes with
whatever landed after it.

The spread is round 1's: 21 small `formal/examples/*.mojo` (the fixed cost),
the stdlib's largest files sampled across its tree, and this repository's
largest `.py`, chosen so the sample contains both ends.

    # .tmp/costmeasure.py — one process per file, each inside
    # tools/memslot.py --gb 8, peak measured by /usr/bin/time -l
    python3 .tmp/costmeasure.py --arch arm64 --label base --cold \
        --out .tmp/cost-arm64-base.csv --n-stdlib 14

| arm64, cold, 44 files | wall | max peak RSS |
|---|---|---|
| base (`17ddeaec`'s tree, current master) | **571.5 s** | 105.4 MB |
| after §2 + §3 | **75.4 s** | 106.3 MB |

**Nothing here is a memory problem, and that is unchanged from round 1**: the
largest peak over the whole spread is 106 MB against the 3-4 GB standard in
`bugs/PERF_memory_over_4gb_is_a_bug.md`, so this doc is entirely about TIME.
Peak RSS did not move either (105.4 → 106.3 MB, and the per-file rows went DOWN
on most files), which is what a cache keyed on a 16-byte digest should look
like; §2.2 has the measurement behind that choice.

### 1.1 What moved, and what did not

The wall clock alone cannot decide this on a loaded box, so the verdict is an
ALTERNATING best-of-2 per file with the old and new `formal/monomorph.py` in
place back to back (`.tmp/timeboth.py`), which is the only comparison on this
machine that load cannot bias:

| file | arm64 base | arm64 after | | x86-64 base | x86-64 after | |
|---|---|---|---|---|---|---|
| `std/simd.mojo` | 58.56 s | **6.13 s** | **9.6x** | 52.40 s | **5.39 s** | **9.7x** |
| `std/collections/string/string.mojo` | 46.35 | **3.97** | **11.7x** | 45.98 | **3.85** | **12.0x** |
| `std/builtin/variadics.mojo` | 20.34 | **4.87** | 4.2x | 19.93 | **4.95** | 4.0x |
| `std/math/math.mojo` | 33.68 | **4.14** | 8.1x | 33.18 | **3.99** | 8.3x |
| `std/python/_cpython.mojo` | 34.38 | **5.04** | 6.8x | 32.82 | **4.58** | 7.2x |
| `std/python/bindings.mojo` | 31.25 | **4.31** | 7.3x | — | — | — |
| `gimple_codegen.py` | 5.90 | **2.30** | 2.6x | 6.56 | **2.59** | 2.5x |
| `test_formal_run.py` | 1.46 | **0.50** | 2.9x | — | — | — |
| `myinterpreter.py` | 1.93 | **1.04** | 1.9x | 2.07 | **1.15** | 1.8x |
| `formal/examples/count.mojo`, `fib.mojo` | 0.11 | 0.11 | 1.0x | — | — | — |
| **total, the 11 files above** | **234.07 s** | **32.51 s** | **7.20x** | **192.95 s** | **26.50 s** | **7.28x** |

Both architectures move together, which is what "shared front end, so both
backends" predicts and only the measurement confirms.

**The two `formal/examples` rows are a wash, and that is the shape of the fix
rather than a gap in it**: a 200-byte example with a two-module closure has
almost nothing to re-ask, so the win is a property of how DEEP a file's
import closure is. A file that imports nothing pays the digest (0.001 ms) and
nothing else.

### 1.2 The sweep-level number, which is the one that matters

`tools/formal_sweep.py` over the 13 largest stdlib files, at its own per-file
bound of `-t 30`, before and after (`.tmp/sweepboth.sh`, x86-64):

| | before | after |
|---|---|---|
| files with **no verdict at all** | **9 of 13 (69.2%)** | **0** |
| `codegen` (a finding about the file) | 1 | 3 |
| `codegen/dependency` (one level down) | 3 | 10 |
| denominator — files that could have answered | **4** | **13** |

Before, the sweep's own summary said so in as many words: *"re-answer the 9
stdlib files with a larger -t: `python3 tools/formal_sweep.py --arch x86_64 -t
90`"*, and *"9 of the 13 classified files (69.2%) got no verdict at all and are
in NO rate"*. After, its verdict history records `tool -> codegen: 2`,
`tool -> codegen/dependency: 7`, `unchanged: 4`.

**So this is not a speed change with a coverage side effect; it moves 9 files
out of the class that contributes no claim either way and into real codegen
findings**, which is the denominator every sweep-map percentage is computed
over. It does not make any file PASS — these 13 are refused for reasons that
have nothing to do with cost — and it should not be read as doing so.

---

## 2. Cost 1, FIXED (`a829a0b7`): the export rule ran 7 042 times over 160 modules

`cProfile` on `std/simd.mojo` at base, ordered by internal time:

| | time | calls | what it is |
|---|---|---|---|
| `fire_compiler.py_tokenize_named` | **28.2 s** (100.6 s cum) | **7 335** | the front end's lexer |
| `fire_compiler.py:_split_on_separators` | 14.7 s | 2 128 570 | inside it |
| `fire_compiler.py:_scan_yield_bearing` | 11.5 s | 15 818 301 | inside it |
| `elaborate.py:_bracket_depth_by_line` | 7.0 s | 600 | §3 |
| `formal/model.py:iter_nodes` | 3.3 s | 15 199 738 | what round 1 spent its budget on |

**100.6 s of a 197.5 s instrumented build was the tokenizer, and `formal/
model.py`'s walks — the entire subject of round 1 — came to 1.8 s of the 84 s
uninstrumented.** Attributing each tokenization to its caller
(`.tmp`-shaped wrapper over `fire_compiler.py_tokenize_named` with a 5-frame
stack) named one caller for 7 042 of the 7 335:

    monomorph.py:108(template_names) <- reflect.py:469(export_exclusions)
        <- imports.py:1600(collect) <- imports.py:1609(collect)

`formal/monomorph.py::template_names(src)` is "which of this module's declared
names are generic templates" — a function of the source text and nothing else.
It was asked once per module of the consumer's re-export closure, inside
`formal/imports.py::module_templates_by_path`'s recursive `collect`, and that
walk itself runs once per imported module (from
`formal/imports.py::instantiation_demands`) and once more from
`formal/build.py::_resolve_imports`. 160 modules × ~44 walks. Each ask is
`reflect.export_exclusions(src)`, which **tokenizes and parses the whole
module** (`reflect.py:469`, `parsed=None`).

The same file's second entry is the other half of the same shape:
`all_instantiation_calls(consumer_src)` re-parsed the consumer once per
imported module over one unchanged source — 7 extra full parses of a 271 KB
`myinterpreter.py` (0.68 s of a 2.7 s build) and 22 each of `std/simd.mojo`.

Both are now derived once per distinct source through one shared helper,
`_derived_from_source`.

### 2.1 What makes the cache SOUND, and what makes it CORRECT

* **It is not a cache of something that changes.** Both answers are functions
  of the source text alone; a build that edits a module reads a different key.
  So there is no invalidation question to answer — which is the same argument
  `formal/imports.py::module_statements` makes for its own content-keyed parse
  cache, and the reason round 1's §3.1 preferred threading to a memo.
* **The key is (question, subkey, 16-byte blake2b of the text).** The question
  is in the key because the first version keyed on the digest ALONE and a
  module asked BOTH questions about itself — which
  `formal/imports.py::build_module_dylib` does, handing the same
  `module_source_text(path)` to `template_names` as `own_templates` and to
  `instantiation_demands` as `consumer_src` — read one answer out of the
  other's slot. **Measured as a crash on 4 of the spread's 43 files**
  (`'tuple' object has no attribute 'items'`, a cached template-name tuple read
  as a demand set). That is the whole argument for the `tag`, and it is why the
  byte-comparison below is a build-and-compare rather than a test.
* **A digest, not the text, because of memory.** Holding the sources as keys
  retains every module of every build this process ever did, where
  `formal/imports.py::_SOURCE_TEXT` already holds them for the build in flight.
  blake2b over a 200 KB module is **0.157 ms** against the 13 ms parse it
  stands in for, and 16 bytes against 200 KB of retained key. Measured peak
  RSS is unmoved (§1), which is the check that this is not a memory bug.
* **Bounded, FIFO, 4 096 entries** — far above one build's working set, so a
  build never evicts what it is about to ask again, and an eviction is a
  re-derivation rather than a wrong answer.
* **Every caller still gets a fresh container.** `template_names` returns
  `list(cached_tuple)` and `all_instantiation_calls` a fresh dict of fresh
  lists, so a caller that mutates what it got cannot reach into the next
  caller's answer — which is what it could do if the cached value were handed
  out directly.

### 2.2 Verification

**Byte-identical on both architectures**, `.tmp/bytecmp.sh` over the 43-file
spread: 22 rows produce an image and every one is `cmp`-equal; the other 21
are refusals and every one's exit code and **full diagnostic text** is
unchanged (the one `-o` path token normalised out). arm64 and x86-64 both exit
0. A behaviour-preserving change's bar is byte-identical output, and a refusal
counts: a change that silently swapped a refusal's wording has changed what the
tool tells the reader.

**Pinned by a count, not by a timing** — a build that got slow again would be
noticed by nobody, and one that got fast by answering a different question
would pass every refusal test in the tree.
`test_formal_monomorph.py::test_a_source_derived_answer_is_made_once_per_source_and_never_shared`
counts the derivations by wrapping `reflect.export_exclusions` and
`MM._consumer_statements`: one per distinct source over seven asks, two
interleaved sources kept apart, a fresh container per call, and both questions
about ONE source (the case the shared key broke). Verified to fail with the key
removed — the same `'tuple' object has no attribute 'items'`.

---

## 3. Cost 2, FIXED (`dcc27620`): a template was LOCATED 300 times over 4 (source, name) pairs

After §2, `elaborate.py:_bracket_depth_by_line` was the top entry on
`std/simd.mojo`: **600 calls, 5.4 s tottime / 8.4 s cumulative of a 21.6 s
instrumented build — 39% of what was left.**

`formal/monomorph.py::instantiate` asks `template_kind(src, name)` and then
`_template_source(src, name, kind)` about the same pair, and both read the
module through `elaborate`'s extractors, each of which `splitlines()` the
module and runs `_bracket_depth_by_line` over it. `instantiate_all` calls
`instantiate` once per (template, argument-list) pair. Measured:

    instantiate        300 calls
    distinct (src,name)  4
    template_kind      300 calls   -> _bracket_depth_by_line 600 calls

So 600 whole-module scans for four questions. Both now go through
`_derived_from_source` with the name as the subkey (and the kind as well, for
`_template_source`, which is a different question about the same pair).

**A refusal is not stored.** `_derived_from_source` only caches a value that is
not `None`, so a name no extractor finds is re-derived and re-refused exactly
as before, rather than a cache going stale against a source that later declares
it. `test_formal_monomorph.py::test_a_template_is_located_once_per_source_and_name`
asserts that (three asks of an undeclared name are three refusals), that 6 + 6
+ 3 asks over two templates stay within 16 whole-module scans, and that the
three instantiations still mangle per `doc/ABI.md` §Generics. Verified to fail
with the memo removed (20 scans for 20 asks instead of 1).

**The ROOT of this one is `elaborate.py`, not `formal/monomorph.py`** — see §4d.

---

## 4. What is left, with the next step

Re-profiled after §2 + §3, `std/simd.mojo` is 6.3 s and its whole remaining
`formal/model.py` cost is 0.18 s of `unit_field_evidence` and 0.09 s of
`struct_method_receiver_reads`. The profile's shape has inverted: what is left
is the import closure walking, not the per-function model work — and on master's
tip, with §c below already landed, less of it still.

### a. `module_templates_by_path` is still walked once per imported module

**In `formal/imports.py`, so not taken here** (§5). `instantiation_demands`
calls it per `dep`, and each call walks `dep`'s whole re-export closure with a
`visited` set that is per CALL: `posix.stat` **491 375 calls / 0.63 s** on
`std/simd.mojo` after §2, against ~160 distinct modules. §2 made the per-module
ask cheap (a digest and a dict lookup); the WALK is still a product.

**Next step, one function:** derive it once from the consumer's own closure in
`imported_instantiations` and hand each `dep` its slice, the way
`instantiation_demands` already derives `found` once for the whole loop. That is
a sum where there is a product, and `visited` becomes a module-level set rather
than a per-call one.

### b. `_attach_declared_census` recomputes the field evidence once per STRUCT

**Also `formal/imports.py`.** It calls `M.unit_field_evidence(module_statements(
declaring_path))` once per struct it collects, and the answer is a function of
the module — so a module declaring S structs pays S whole-module walks. On
`std/simd.mojo` after §2: **89 calls, 0.177 s**; on `myinterpreter.py`, 10
calls / 0.206 s. Round 1 measured 78 calls / 2.34 s on a deeper case. Its own
docstring already names the shape ("the walk asks once per struct it collects …
it is idempotent") without fixing it.

**Next step:** hoist the call out of the per-struct loop in
`module_struct_defs`/`imported_struct_defs` and call
`M.attach_field_evidence(list(M.iter_struct_defs(stmts)), evidence)` once per
MODULE, which is what `formal/build.py::parse_module` already does for an entry
file. `attach_field_evidence` is already the whole-module form.

### c. `struct_receiver_stores` visited every node — **ALREADY FIXED ON MASTER, do not redo it**

**This residue was open when this pass ran and master closed it while this pass
was running** (`078ecbed` "the receiver-store census walks STATEMENTS, and the
differential that says it may", plus `tools/formal_field_walk_differential.py`).
`formal/model.py::struct_receiver_stores` on master's tip reads through
`iter_statement_nodes` rather than `iter_nodes`, which is exactly the walk
round 1's §6 specified. **Nothing to do here; the point of recording it is that
a doc which names a landed fix as an open residue sends the next reader to redo
it.** This branch was cut from `3c3516db` and master was 27 commits ahead of it
when these numbers were taken, which is why §4a and §4b below were re-checked
against master's tip and §4c had not.

What this pass contributes is the PREMISE measured on its own base
(`.tmp/walkbench.py`, identical node sequences checked, `myinterpreter.py` /
`formal/model.py` / `formal/build.py`):

| | nodes in the full walk | nodes in a statement walk | time |
|---|---|---|---|
| `myinterpreter.py` | 14 393 | 3 159 (4.6x fewer) | 14.97 → 2.65 ms |
| `formal/model.py` | 41 167 | 8 121 (5.1x) | 47.15 → 6.55 ms |
| `formal/build.py` | 28 160 | 4 922 (5.7x) | 27.19 → 3.27 ms |

and one negative measurement that is **not** on master and should not be
re-derived: replacing `iter_nodes`'s recursive generator with an explicit stack,
which is the obvious "make the hot loop cheaper" move, is **not** faster —
16.24 ms against 14.97 ms per walk on `myinterpreter.py`, 45.16 against 47.15 on
`formal/model.py`, i.e. inside noise in both directions. `yield from` delegation
is not the cost; the per-node Python work is. So a future pass should look for
fewer NODES, not a faster descent.

### d. `_bracket_depth_by_line` is a whole-module scan inside `elaborate.py` — FIXED 2026-10-05 (`work/bugs7-4`)

§3 fixed the CALL SITE; the root is that three readers in `elaborate.py`
recompute it about the same module — `extract_fn_source` (`:129`),
`extract_overloads` (`:159`) and `extract_struct_source` (`:432`).
**`type_param_names` is not one of them**: it takes `template_src` and goes
through `mm.head_match` alone, so this doc's list of four readers was three.

The memo is now there, and the two decisions in it are the whole of it:

* **A TUPLE, not a list.** The memo hands every reader the SAME object, and a
  reader that mutated it would corrupt every later one — the hazard this same
  doc's own "the memo's hazards" section states for a shared list. A tuple
  removes it structurally rather than by a check a future caller could forget:
  `_find_block_end` only READS it, so nothing has to be migrated.
* **Keyed by the source TEXT, bounded to 8 entries in an insertion-order LIST
  beside the dict.** Keyed by the text rather than by `id()` because an address
  can be handed to a different object once the first is freed (this doc's
  hazard 2), and hashing the text costs far less than the scan it stands in
  for. The ORDER is a list and not `next(iter(the_dict))` — which is the
  spelling `formal/monomorph.py::_derived_from_source` uses and which this file
  may NOT, because `elaborate.py` is inside the self-host closure
  (`cas.selfhost_inputs()` lists it, `formal/*` does not) and `next()` over a
  container is one of the constructs the self-hosted codegen does not lower.
  Measured, not argued: with `next(iter(...))` the self-hosted compile fails
  with a GCC error; with the list it compiles and `test_selfhost.py`'s failure is
  the pre-existing `exit=-11` one.

Measured on this tree, which has no stdlib checkout beside it, so the largest
sources available stand in for `std/simd.mojo`:

| source | bytes | cold | warm |
|---|---|---|---|
| `formal/model.py` | 2 111 422 | 85.8 ms | 0.001 ms |
| `formal/build.py` | 1 097 043 | 46.8 ms | 0.022 ms |

and 12 interleaved sources asked three times each: 0 wrong answers, cache 8,
order 8, at the cap. `d[0] = 999` on a returned value raises `TypeError`, which
is the point.

Equivalence evidence: **208 artifacts byte-identical** (every
`formal/examples/*.mojo`, both backends, `compile_formal`'s emitter text),
`test_formal_monomorph.py` 23/0, `test_comptime_parity.py` 9/9,
`test_x86_64_examples.py` 52/52, and `test_selfhost.py`'s failure is the
pre-existing `exit=-11` with and without the diff. Still owed by the integrator:
`make bootstrap`'s three stage trees and `stdlib-dylib`'s skip count, which no
light worker may run.

### e. The proof path was NOT measured, and why

Round 1's brief for this task named the proof path under `run_lean`
(ProofLib build 112 s, proofs 9-300 s). **This worker may not launch lean**
(`formal/lean.py::run_lean`), so nothing here is a measurement of it and
nothing here should be read as one. What §2 does change for it is upstream: a
build that spends 51% of its wall clock in the tokenizer produces its
`prog`/`code`/`info` later, and the sweep builds with `--no-prove`, so the
84 s → 6.3 s on `std/simd.mojo` is the `--no-prove` figure and the proof path
on top of it is unchanged by construction. **Whether the 300 instantiations
§3 collapsed were each also a separate `.lean` artifact to check is a question
for a worker who can run lean**, and it is the one place where this pass's
result might have a second-order effect on the 9-300 s.

---

## 5. Why the `formal/imports.py` residues were not taken here

Two of the four residues are in `formal/imports.py`, and the rule for a light
worker is to report an area another worker holds rather than edit it. No claim
in `tools/control.py claims` is a path prefix of `formal/imports.py` — every
live claim is a `bug:`/`sweep:`/`module:` key — so this is not a mechanical
block, it is the substantive one: `sweep20:hostmods-wave3`
(`formal20-hostmods-wave3`) and `sweep12:hostmods-subprocess`
(`formal12-hostmods-subprocess`) are both live and both are working the
host-module machinery, which is what `formal/imports.py` IS. Round 1 declined
the same file for the same reason, and this pass fixed the cost whose ROOT is
on the other side of that boundary (`formal/monomorph.py`, which both those
workers also depend on) rather than the cost whose fix is inside it.

## 6. Reproducing every number here

    # §1  the 44-file spread, one process per file, cold CAS
    python3 .tmp/costmeasure.py --arch arm64 --label base --cold \
        --out .tmp/cost-arm64-base.csv --n-stdlib 14

    # §1.1  the alternating best-of-2 old/new comparison (arm64 or x86-64)
    OLD=HEAD~2 python3 .tmp/timeboth.py --arch arm64 --reps 2 <files>

    # §1.2  the sweep-level before/after at its own -t
    ARCH=x86_64 bash .tmp/sweepboth.sh .tmp/sweep12.txt

    # §2  who calls the tokenizer, and how often
    TARGETS=... python3 .tmp/callers.py -- <build argv>
    # §3  the walk node counts, with the sequences checked equal
    python3 .tmp/walkbench.py myinterpreter.py formal/model.py

    # §2.2  the byte comparison, both architectures
    ARCH=arm64 bash .tmp/bytecmp.sh spread $(cat .tmp/spread.txt)