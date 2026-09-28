# FORMAL: making the formal backend a first-class target

**Status: programme, not a bug.** No single defect is closed by this document and
none should be filed as one. It exists because the goal — *one runtime, two code
generators, one proof* — spans `formal/`, `mojo/`, `runtime/` and the proof
library, and because the honest state of that goal is currently spread across five
bug documents that each know one piece of it. Per-phase evidence belongs in that
phase's commit and, where a phase produces a standing fact, in the `bugs/FORMAL_*`
documents this one defers to. What lives *here* is the thesis, the measured current
state, the decisions taken, and the order.

Read with: `doc/ABI.md` (the boundary contract this must not contradict),
`bugs/FORMAL_known_limits.md` (the audited codegen residue),
`bugs/FORMAL_arm64_known_proof_gaps.md` (the proof census), and
`bugs/OPEN_WORK.md` A1 (the x86-64 `call_rel32`, which phase 3 needs).

**Citations.** Every line number below was verified against **`7604105`**. The tree
moves — `a5b8ceb` landed the same day this was written and shifted
`formal/model.py` and `formal/arm64_codegen.py` under an in-progress read — so
each citation names the function or construct first and the line second. A line
number that disagrees is stale, not wrong; the name is the claim.

---

## 1. The thesis

`fire.py` has two machine-code backends. The gimple backend emits C, links
`runtime/fire_runtime.c` (299 KB) plus the other runtime translation units, and
hands the result to a system linker. The formal backend emits Mach-O or ELF
itself, links **libSystem and nothing else**, and carries a Lean model of the
machine it emitted.

They are treated as two languages with two runtimes. They should be **one language
with one runtime, and a proof about it.** Concretely:

- The system-module surface — everything `ast_rewriter.py` and the dispatch arms in
  `mojo/backend_gimple/emit_{methods,exprs}.py` currently hardcode — should be
  *the runtime*, called identically from both backends, rather than a
  target-specific reimplementation of it in each.
- The runtime should be **provable in the same sense the compiled code is**. A
  runtime function is a `.o`/`.dylib` with a proof attached; the caller's proof
  consumes the callee's contract. That is what "combined with the other proof bits,
  the total proof works" means concretely.
- **The runtime is written in Mojo, not C.** Mojo is a C superset, so this is
  possible; and writing it in Mojo is strictly better than shipping C, because the
  runtime's own source then passes through the same frontend as everything else. A
  bug fixed on the formal path is then a bug fixed on both. C is retained only
  where bootstrapping requires it.

The bug-reduction property is the point, not a side effect. Today a formal refusal
is a fact about a *separate* implementation, so fixing it teaches us nothing about
gimple. Under this programme they are the same code and the proof is about both.

---

## 2. What exists today

### 2.1 The call machinery is real

The formal codegen already lowers a call to an external symbol, emits a `BL` to a
`__TEXT,__stubs` slot, patches the GOT, and writes a classic dyld bind stream:

| what | where |
|---|---|
| `emit_extern_bl` — the placeholder `BL` | `formal/arm64.py:638` |
| `resolve_extern` — stub patching against a target map | `formal/arm64.py:720` |
| `LIBSYSTEM_PATH`, the one hardcoded load command | `formal/macho_linker.py:92` |
| stubs + GOT + bind opcodes; ordinal 1 libSystem, `dylibs[k]` → `k+2` | `build_macho_executable_extern`, `formal/macho_linker.py:464` (bind stream at `_bind_info`, `:337`) |
| `load_dylib_manifests` — a dylib's export spellings rewrite the caller's callee mangling | `formal/build.py:3507` |

`test_formal_dylib.py` is 11/11, so cross-dylib calls work end to end. **"You can
already handle a function with a function call in it; it is just wiring" is
correct about the call half.**

### 2.2 Most of the runtime surface is word-shaped

`runtime/fire_runtime.h` declares **455** entry points:

| | count | note |
|---|---|---|
| return exactly one 64-bit word | **352** | `void`, `int`, `int64_t`, `double`, `char *`, `void *` |
| return a heap box | **101** | `MojoList*`, `MojoDict*`, `MojoSet*`, `MojoBytes*`, `MojoMemoryView*`, `MojoStr*`, `MojoStructFmt*`, `MojoCompletedProcess*` |

**The 352/101 split is by return type only, and is not the callable set.** A
function such as `mojo_list_get_int(MojoList *, int64_t) -> int64_t` is in the 352
and is *not* callable, because the box is in the parameter. Any table built for
phase 2 must filter over parameters **and** return.

`runtime/fire_sqlite3.c` — 22 functions, header and source in exact 1:1 agreement,
and the same 22 in `gimple_codegen.py:2364-2386`:

- **20 of 22 are pure word-in/word-out.** `void *`, `int64_t`, `double`,
  `const char *` in; one word out. Directly portable.
- The two exceptions are `mojo_sqlite3_query` and `mojo_sqlite3_query_dict`
  (`runtime/fire_sqlite3.h:17,27`). The latter returns a `MojoList *` whose
  elements are boxed `MojoDict *`, each stored as the `int64_t` bit-pattern of its
  pointer (`runtime/fire_sqlite3.c:156-157`). They are the *entire* obstruction.

`runtime/fire_python.c` — 15 functions, all word-shaped, with CPython behind
`#if USE_PYTHON` whose default is **0** (`runtime/fire_python.c:7`). At the default
the file compiles to 15 stubs with no `<Python.h>` include at all. This is the
scaffold for "the python runtime can be compiled too", and it already exists.

### 2.3 A runtime dylib already exists

`runtime_dylib()` (`build_stdlib_dylib.py:697`) builds exactly the artifact this
programme needs: a `-dynamiclib` exporting the `mojo_*` namespace, with an `@rpath`
install name. It is used today only by the gimple path. The formal linker simply
is not told about it.

### 2.4 The export table can already be read

`collect_runtime_exports_h` (`reflect.py:566`) scans a runtime header for exported
functions, and `build_stdlib_dylib.py:750-751` already uses it to populate the
stdlib dylib's reflection table. A formal-side provider registry has a scanner
available and needs no new parsing.

### 2.5 The refusal is already half shape-aware

`gimple_runtime_refusal` (`formal/model.py:4161`) is a single function shared by
both backends — deliberately, so the two architectures cannot drift in their
refusals — and it already special-cases `GIMPLE_LIST_PREFIX`
(`formal/model.py:4148`) with the correct reason: those take a `MojoList *`, a heap
box the gimple runtime owns, "while a list on a formal path is a frame blob whose
first word IS its count". The project has diagnosed the precise problem. Phase 2
generalises the diagnosis from one hand-picked prefix to the whole header.

---

## 3. What does not exist

### 3.1 The proof side, which is most of the work

At an extern call site today:

| what | where | what it actually asserts |
|---|---|---|
| the call step | `_gen_extern_test`, `formal/arm64_proof_gen.py:6910` | `theorem extern_<sym>_step : True := by trivial` — the trivial proposition |
| the post-call state | `formal/arm64_proof_gen.py:6923` | **fabricated** as `{pre with pc := bl+4}`; the callee's effect on registers and memory is discarded, and the following theorem proves a claim about code that ran as if the callee had been deleted |
| `DylibExport.Semantics` | `lib/ProofLib.lean:4617` | `∀ o, o ∈ [] → True` — vacuously true of *any* export in *any* image, because the observable list is hardcoded empty at `formal/arm64_proof_gen.py:8356` (`def dylib_observables : List (UInt64 → UInt64) := []`) |
| `dylib_export_contract_stub` | `lib/Refine.lean:660` | `by sorry`, invoked with `obs := fun n => n` — the contract claims every export is the **identity function** |

The root cause is mechanical: `lib/ProofLib.lean:1548-1549` gives `BL` a bare
`x30`/pc transfer with no callee, and a dylib/libc branch target is a stub address
*outside the image*, so `arm64_go_exit` returns `none` and the model halts. **To
make a call provable, the machine model needs call and return semantics: a call
frame, a callee entry, and return-to-`x30`.** Everything in this section is a
consequence of that one gap.

The x86-64 side is coarser: it emits **no run tests at all** for any program with
externs (`formal/x86_64_proof_gen.py:460`), and both its end-to-end theorem
(`:690`) and its AST⟷bytes theorem `_compile_correct` (`_compile_correct_section`,
`:239`) are unconditional `sorry`.

`formal/x86_64_proof_gen.py:26-31` says this itself: *"A `sorry` in Lean makes the
theorem ACCEPTED, so a `sorry` here is a claim of trust, not a proof."* The project
already knows. The programme is to stop needing the claim.

**Consequence for sequencing.** `generate_dylib_proof`
(`formal/arm64_proof_gen.py:8311`) genuinely produces real content — the code memory
function, per-instruction decode lemmas, per-instruction step and step-result
lemmas, and two cardinality theorems — and it typechecks. But its four per-export
*semantic* theorems rest on the stubs above. It is a well-formed skeleton with the
meaning removed. Building the runtime before the model has call semantics would
produce exactly that artifact, one level up.

### 3.2 The ABI is not unified, and today is incompatible

| | layout | storage |
|---|---|---|
| gimple `MojoList` (`runtime/fire_runtime.h:257-261`) | `{ int64_t *data; int64_t len; int64_t cap; }` | **heap**, two-level indirection, resizable |
| formal list (`formal/model.py:49-61`, `BLOB_HEADER_BYTES = 8`) | `[count:i64][elem0][elem1]…` | **frame blob**, contiguous, the address is a stack address |

Word 0 is a data pointer on one side and a count on the other.
`formal/model.py:4139-4148` already names this precisely: reading offset 0 of a
`MojoList *` "would be a plausible-looking wrong number rather than a crash."

The formal model also has **no allocator at all**. Blobs are frame-resident and
bounded: arm64 against a scratch region (`_SCRATCH = 131072`,
`formal/arm64_codegen.py:37`; `_blob_cap` at `:738`; over-capacity raises at
`:1909-1912`) and x86-64 against `_BLOB_BYTES = 16384`
(`formal/x86_64_codegen.py:63`). So the 101 box-returning entry points, and the
box-argument half of the 352, are not merely unwired — they have no representation.

### 3.3 The gimple premise needs establishing before anything is measured against it

The premise is that sqlite works from gimple and formal should match. Measured, it
does not:

- **No build rule compiles `runtime/fire_sqlite3.c`.** Nor `fire_python.c`,
  `fire_zlib.c`, `fire_ssl.c`, `fire_ncurses.c`. Only `fire_runtime.c` has one:
  `Makefile:333-334` (the `build/fire_runtime.o` rule, over `RUNTIME_SRC` at
  `Makefile:25`), `fire.py:583` (`runtime_cmd`, over `runtime_src` at `:541`),
  `build_stdlib_dylib.py:480` (`rt_src`, compiled at `:498`), `build_module.py:89-94`,
  and `comptime.py:78`.
- `mojo/backend_gimple/module_gen.py:6788-6791` `#include`s all four of those
  headers **unconditionally** into every generated translation unit, and
  `gimple_codegen.py:2364-2386` carries all 22 sqlite signatures in `_KNOWN_SIGS`.
  The declarations are therefore always visible while the definitions are in no
  build path: **a program calling `mojo_sqlite3_open` compiles clean and dies at
  load with "Undefined symbols."** That is a live defect on the gimple path.
- No driver builds `test_sqlite3*.mojo`, and `rg sqlite tools/suite.py Makefile`
  returns nothing.
- `test_sqlite3_min_proof.lean` proves nothing. `main_go` is `(0 : UInt64)`, the
  "compiled image" is a hardcoded literal byte blob, and both `main_compile_correct`
  and `main_compiles_correctly` are `sorry`. It contains a `mojo_sqlite3_close`
  call in its AST and executes no sqlite.

This is not an argument against the programme. It is phase 0, it is on the gimple
path where bug reduction is wanted anyway, and it turns the programme's baseline
from assumed into measured.

### 3.4 The provider notion is a hardcoded 19-name set

`_is_libsystem` (`formal/build.py:3591`) is a 19-element literal set with one caller
(`:4329`). It is the entire notion of "a symbol provided by a linked native
runtime", it is a *name* guess rather than a check of anything, and the audit that
uses it — "the library would bind N symbol(s) that nothing provides",
`formal/build.py:4332` — runs **only on the dylib path**. `build` / `build --formal`
emits `external_syms` with no such audit at all.

---

## 4. Decisions taken

1. **Phase 0 first.** Make gimple's sqlite real, and measure it. Everything after
   is compared against it.
2. **ABI: option (c) now, converging on (a).** Keep `doc/ABI.md`'s documented ABI
   (`List → MojoList *` and friends) exactly as it is, and write the runtime against
   an abstract container interface so each target picks its own layout. This does
   **not** fork the road; see §5.
3. **A dynamic allocator is written in Mojo against a slab, and carries its own
   proof.** A bump allocator over a region is provable without libc `malloc`:
   allocation returns a pointer inside the region, no two live allocations overlap,
   exhaustion is detectable. That is a tractable Lean target, and it is what lets
   the formal target's containers become genuinely heap-backed, which is what makes
   the documented ABI true on both sides.
4. **The runtime is written in Mojo.** C is retained only for bootstrapping.

---

## 5. The ABI arc: (c) is a phase of (a), not an alternative to it

This is stated separately because it is the load-bearing consequence of decision 3.

Under (c) alone, the formal target's containers stay frame blobs and the 101
box-returning entry points stay gimple-only, permanently. That is a real ceiling,
and it is why (c) cannot be the destination.

A slab allocator removes the ceiling. Once the formal target has a *proved* bump
allocator, its `MojoList` can be a real pointer into a region rather than a stack
blob; `doc/ABI.md`'s `List → MojoList *` becomes literally true on both backends;
and the 101 become callable **incrementally, one entry point at a time, each with
its own proof** — rather than in one change to the value model that would disturb a
proof library currently 34 of 40 clean.

So the sequence is: **(c) for the word surface → proved slab allocator → heap-backed
formal containers → (a) reached without a big bang.** The cost of (c) is bounded,
because (c) is where the work has to start anyway.

**One honest constraint on decision 3.** A bump allocator with no reclamation is the
tractable proved target; free is much harder than bump. An arena without
reclamation means long-running loops exhaust it, which is a real constraint on what
the formal runtime may do and belongs in a contract rather than in a discovery. A
per-size-class free list is the obvious next step and is proportionally harder.

---

## 6. Phases

Dependency-ordered. **Phase 3 gates 4, 5 and 6; nothing after it is worth building
before it.** Each phase's exit criterion is checkable and each names the trust it
removes.

### Phase 0 — make gimple's sqlite real

Add `fire_sqlite3.c` to the runtime build. Add a registered suite entry that builds
**and runs** `test_sqlite3.mojo`. Decide the other four translation units: compile
them, or stop `#include`ing their headers unconditionally — a declaration with no
definition is a latent link failure either way. Retire
`test_sqlite3_min_proof.lean`, or state on its face that it is a template.

Add a **link audit** that fails when a program calls a declared-but-undefined
runtime symbol. This is the test that would have caught §3.3, and it stops it
recurring as the runtime grows.

*Exit:* `test_sqlite3.mojo` builds, links, runs, and produces the expected rows.
*Removes:* a live gimple link defect. No proof content.

### Phase 1 — per-arch runtime dylibs and a real provider registry

`runtime_dylib()` already produces the artifact; add `-arch arm64` / `-arch x86_64`
to it. **No build rule in the tree has an `-arch` flag today** — everything is
host-only, and the sweep runs both architectures, so both are required. Make the
formal linker read the dylib's *actual* export table (via
`collect_runtime_exports_h`, §2.4) in place of `_is_libsystem`'s 19 names, and
extend the bind audit from the dylib path to the **executable** path.

*Exit:* a formal image links a clang-built runtime dylib and dyld resolves every
name in its bind stream; the executable path is audited.
*Removes:* the hardcoded provider guess, and a real class of silent link failures.

### Phase 2 — lift the `mojo_*` refusal, shaped by ABI

`is_gimple_runtime_builtin` (`formal/model.py:4151`) refuses any callee whose name
starts with `mojo_` (`GIMPLE_RUNTIME_PREFIX`, `:4136`), raised at
`formal/arm64_codegen.py:4936-4937` and `formal/x86_64_codegen.py:4563-4564`. The
refusal text is already correct about *why* it is currently right and wrong only in
being prefix-based.

Replace it with: **callable iff every parameter type and the return type in
`fire_runtime.h` are word-shaped, and the symbol is on the link line.** One table,
generated from the header by the existing scanner, so it cannot drift from the
runtime — a second hand-kept list would be exactly the rot phase 2 exists to
remove. This is a generalisation of the `GIMPLE_LIST_PREFIX` special case that
already exists (`formal/model.py:4148`), not a new idea.

*Exit:* the word-only surface is callable from formal; the box surface is still
refused, and the refusal now names the *type* mismatch rather than a prefix.
*Removes:* `gimple_runtime_refusal`'s over-broad claim. No proof content yet.

### Phase 3 — the proof model: call and return semantics. **THE GATE**

Extend `arm64_step`'s `BL` (`lib/ProofLib.lean:1548-1549`) with a call frame, a
callee entry, and return-to-`x30`. Wire the x86-64 `call_rel32`
(`x86_step_call_rel32`, `lib/X86.lean:720`), which `bugs/OPEN_WORK.md` A1 already
records as present but not connected to the generator's `_FORMS`/`_SUCCS`/`_resolve`
trio.

Then, in this order:

1. Replace `theorem extern_<sym>_step : True := by trivial` with a real obligation.
2. Give `DylibExport.Semantics` a non-vacuous definition, with real observables
   rather than the hardcoded `[]`.
3. Either prove `dylib_export_contract_stub` or **delete it**, so it cannot be read
   as a proof of a contract that currently asserts every export is the identity.

*Exit:* a dylib export has a semantics that is not vacuously true, and a caller can
discharge an obligation against it.
*Removes:* the two `sorry`s at `lib/ProofLib.lean:4624` and `:4627`, and
`lib/Refine.lean:660`; and the vacuous extern step theorem.

### Phase 4 — per-export contracts

With phase 3 done, a runtime object is provable. Emit one contract per export from
the header plus a spec, and have the caller's proof consume it. This is where "a
`.o` with a proof with it" stops being a name.

*Exit:* a runtime dylib proof contains no `sorry` **including the ones in `lib/`**,
and a caller proves its obligation against a real contract.

### Phase 5 — the Mojo runtime, in Mojo, bootstrapped separately

Order matters: the **gimple** Mojo runtime first, since it can compile the existing
C runtime and so cannot regress. Then the formal runtime, once phase 3 gives it
call semantics.

*Exit:* the gimple path runs on a Mojo-written runtime with no behavioural
regression; the formal path links the same source through the same ABI.

### Phase 6 — the proved slab allocator

Written in Mojo, proved in Lean: allocation returns a pointer within the region, no
two live allocations overlap, exhaustion is detectable. Per §5 this is what converts
option (c) into a route to option (a).

*Exit:* the formal target has a proved heap, and `doc/ABI.md`'s `List → MojoList *`
is true on both backends.

### Phase 7 — frontend breadth

Containers, floats (the model is int-only; floats truncate toward zero on emit,
`formal/types.py:166`), generics / Stage 5 monomorphization, `try`/`except`,
classes. This is where the formal sweep's codegen families shrink, and it is last
because each of these compounds with the above rather than preceding it.

---

## 7. The trust inventory

What a proof currently rests on, so that removing an item is visible. The project
has **no Lean `axiom` and no `opaque`** anywhere; everything is assumed in the
`sorry` sense, which is the harder habit to see.

| # | where | what is trusted |
|---|---|---|
| 1 | `lib/ProofLib.lean:4624` `in_image_stub` | a dylib export is in the image |
| 2 | `lib/ProofLib.lean:4627` `semantics_stub` | an export has a semantics; the goal is vacuous regardless |
| 3 | `lib/Refine.lean:660` `dylib_export_contract_stub` | an export computes its observable |
| 4 | `formal/x86_64_proof_gen.py:239` `_compile_correct_section` | the AST compiles to the emitted bytes (x86-64) |
| 5 | `formal/x86_64_proof_gen.py:690` | the x86-64 end-to-end theorem |
| 6 | `formal/arm64_proof_gen.py:6910` | every extern call step (`True := by trivial`) |
| 7 | `formal/arm64_proof_gen.py:4077,4258,4790,4797,4875,4891,5089` | `all_goals (first \| done \| sorry)` CFG leaves — 13 sorries in 9 of 43 arm64 proofs, owned by `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` |
| 8 | `lib/ProofLib.lean:895` | "All per-node lemmas currently admit" |

**Two holes in the mechanism that checks this**, both of which matter more than any
single entry above:

- `check_proof_cached` returns `n_sorries` and **nobody reads it**. Tree-wide,
  `proof_sorries` has exactly two references — `formal/build.py:931` and `:4386` —
  both writes, zero reads. `fire.py` prints only `proof_cached`. A proof with a
  thousand sorries is a `PASS`. The census is sound for what it measures and is
  never gated on it.
- **Vacuity is invisible to the census.** `extern_<sym>_step : True := by trivial`
  counts as **0 sorries** while being as uninformative as one.
  `test_formal_dylib.py:388` greps only the *generated file* for `sorry`, while the
  three that decide its verdict live in `lib/` and are never emitted as Lean
  "declaration uses sorry" warnings, being consumed from pre-built `.olean`s.

Under this programme a proof will be asked to carry real weight, so the honesty
mechanism has to see vacuity and not only holes. That is part of phase 3's exit
criterion, not a separate cleanup.

---

## 8. What this does not fix

Stated so no reader infers otherwise.

- **The 108-file sweep tier stays out of reach.** `subprocess`, `ctypes`,
  `asyncio`, `threading`, `socket` need a host process or an embedded interpreter.
  `fork`/`exec` exist in libSystem, but a *proved* model of them is a separate
  programme, and `ctypes` needs libpython, which by construction cannot be in a
  proved image. Measured on the current sweep: 288 repo files, 190 with a host
  import — 108 in this tier, 56 needing an engine, and only **24** importing
  nothing outside `{os, sys, math, struct, time}`. Phases 0-6 reach the 24 and a
  real slice of the 56. They do not reach the 108.
- **The external stdlib's 294 files import zero host modules.** The host-import
  problem is entirely a repository problem. Phases 0-6 move repository files; the
  stdlib scope is untouched by them, and its residue is the MLIR / generics /
  one-word families in `bugs/FORMAL_known_limits.md`.
- **Stage 5 monomorphization is still the single largest lever on the sweep
  headline** — 24 of family 1's 30 files (`bugs/FORMAL_known_limits.md` §1.2) — and
  it is **not** in this programme. It is phase 7, and it is weeks, not an
  afternoon.
- **The sweep's headline will move modestly.** What changes is that its largest
  unanswerable bucket stops resting on a claim we know to be false.

---

## 9. Verification obligations

- Anything touching `fire_compiler.py`, `gimple_codegen.py`, `module_loader.py`,
  `mojo/backend_gimple/*` or `mojo/middle/*` owes a full `make gate` per
  `CLAUDE.md` — including the two verdicts that need judgement rather than a zero
  exit: `stdlib-dylib`'s skip count must not increase, and `stdlib-syntax`'s `U`
  must not increase.
- For a change that is supposed to be behaviour-preserving, the standard is
  **byte-identical generated C** on a large succeeding case, compared before and
  after. Phases 1 and 2 are in that category.
- Phases 1 and 2 are the two most at risk from a provider-registry change, because
  it touches symbol resolution, and those are the same two that need the
  byte-identical-C comparison.
- A phase-0 link audit is a new test and must be registered in `tools/suite.py`,
  not left as a script.

---

## 10. Open

- **Reclamation.** Decision 3 proves a bump allocator. Free is harder, and an arena
  without it constrains what the formal runtime may do. The contract must say so
  rather than discover it at phase 6.
- **How far the phase-3 model goes.** A call frame in the Lean model is one thing; a
  *stack* discipline, reentrancy and unwinding are others. The exit criterion above
  is deliberately the minimum that makes phase 4 meaningful.
- **`doc/ABI.md` has two stale names**, and this document defers to it:
  `runtime/mojo_runtime.h` (`:55`, renamed to `fire_runtime.h`) and
  `mojo_compiler.py` (`:95`, renamed to `fire_compiler.py`). A separate one-line
  fix; flagged here so `FORMAL.md` does not inherit the staleness.
- **A duplicated block in `formal/arm64_proof_gen.py`.** `generate_arm64_proof` is
  defined at both `:6034` and `:7222`; `_gen_extern_test` at both `:5661` and
  `:6849`; `_find_extern_call` at both `:5556` and `:6744`. The copies are
  byte-identical so behaviour is unaffected and Python binds the second, but the
  live `_gen_extern_test` is the one at **`:6849`** and every line number above
  that touches it refers to that copy. The proof generator is the wrong place to be
  carrying two copies of anything. `formal/model.py` has 205 `def`s and no
  duplicates, so its line numbers are unambiguous.
- **Whether the two hand-kept module tables in `mojo/middle/` should be folded in
  during this programme.** `_MODULE_ATTR_CTYPES` (`mojo/middle/types.py:722`) and
  `_STRUCT_MODULE_FN_RETVALS` (`:360`) exist only to keep a type estimator and a
  lowering in sync by hand. Phases 2 and 5 add a third consumer, which is the point
  at which one table becomes cheaper than three.
