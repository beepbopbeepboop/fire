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
`bugs/FORMAL_arm64_known_proof_gaps.md` (the proof census),
`bugs/CODEGEN_bootstrap_resource_blowup.md` (the upstream cause of the
self-host divergence), and `bugs/OPEN_WORK.md` A1 (the x86-64 `call_rel32`,
which [3] needs). **§11 is the operating contract** — the five agents, their
exclusive write sets, the isolation rules, the interface-request mechanism and
the merge order all live here now; `FORMAL-PARALLEL.md` is folded in and
deleted.

**Citations.** Line numbers were verified against **`7604105`**; §2.2, §7 and
§11 were re-measured against **`21a82d6`** + the sqlite work on 2026-09-28, and
§2.2's figures are corrected there. The tree
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

### 2.2 A minority of the runtime surface is word-shaped

**Corrected 2026-09-28.** The figures this section used to carry — 455 entry
points, 352 word-returning, 101 box-returning, "20 of 22" for sqlite — are
stale in *every* number, and one of them is nearly inverted. `formal.model`'s
`runtime_abi()` is the authority and it reads **every** header in `runtime/`,
not just `fire_runtime.h`:

| | count | note |
|---|---|---|
| entry points across 10 headers | **540** | `fire_runtime.h` 450, `fire_sqlite3.h` 22, `fire_ncurses.h` 18, `fire_python.h` 15, `fire_ssl.h` 13, `fire_async_runtime.h` 13, `fire_zlib.h` 6, `fire_coro_ctx.h` 3; `fire_coro.h` and `fire_wd.h` scan to **zero** |
| **word in, word out** | **219** | every parameter and the return value is one 64-bit word |
| not word-shaped | **321** | a box crosses the boundary — in an argument, in the return, or both |

So **219 of 540 (40.6%)** is the reachable-surface ceiling, against the 352 of
455 (77%) this section previously claimed. The reachable surface is **smaller**
than believed, not larger, and the number to beat is 219 rather than 352.

**The word/box split is over parameters AND return, and never was only the
return.** The old table split by return type alone, which is why it read
352/101; `mojo_list_get_int(MojoList *, int64_t) -> int64_t` returns a single
word and is in neither column, because the box is in the *parameter*. Phase 2's
table filters both, and `runtime_abi()`'s per-entry `word` flag is that filter —
`word: True` means every type crossing the boundary is one word, so an entry
with a word return and a boxed argument is `word: False`.

`runtime/fire_sqlite3.c` — 22 functions, header and source in exact 1:1
agreement:

- **18 of 22 are pure word-in/word-out** (`runtime/fire_sqlite3.h`, measured via
  `runtime_abi_entry`). This section previously said 20; the correction is
  recorded in `bugs/FORMAL_known_limits.md` and is right there — `void *`,
  `int64_t`, `double`, `const char *` in, one word out, directly portable.
- The exceptions include `mojo_sqlite3_query` and `mojo_sqlite3_query_dict`
  (`runtime/fire_sqlite3.h:17,27`). The latter returns a `MojoList *` whose
  elements are boxed `MojoDict *`, each stored as the `int64_t` bit-pattern of
its pointer (`runtime/fire_sqlite3.c:156-157`). The remaining two are
`mojo_sqlite3_open`/`_close`, whose `void *` handle is a box on **both** sides.

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
(`formal/x86_64_codegen.py:63`). So the 321 non-word entry points are not merely
unwired — they have no representation.

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

### 3.4 ~~The provider notion is a hardcoded 19-name set~~ — FIXED, with a caveat

`_is_libsystem` was a 19-element literal set: a *name* guess rather than a check of
anything, and the audit using it ran only on the dylib path. Both halves are
closed — the provider is now a real `dlsym` probe of the C library, and the
executable path is audited too (`formal/build.py`'s `_unaccounted_report`, pinned
by `test_formal_link_accounting.py`, 83 checks).

**The caveat, and it is the reason this is not simply struck.** The audit can
only say *nothing on this link line defines these names*; it cannot say **why**.
`info` carries `external_syms` and nothing recording a construct the codegen
failed to lower, so no code in the backend can distinguish a dangling emitted
call from a bare reference with no call site behind it. The message says so
rather than guessing. Distinguishing them is a real, small piece of work and it
is not in §11.2's five.

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

Under (c) alone, the formal target's containers stay frame blobs and the 321
box-returning entry points stay gimple-only, permanently. That is a real ceiling,
and it is why (c) cannot be the destination.

A slab allocator removes the ceiling. Once the formal target has a *proved* bump
allocator, its `MojoList` can be a real pointer into a region rather than a stack
blob; `doc/ABI.md`'s `List → MojoList *` becomes literally true on both backends;
and the 321 become callable **incrementally, one entry point at a time, each with
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
definition is a latent link failure either way. **The 2026-09-27 decision:** the
four are registered in `build_config.OPTIONAL_RUNTIME_UNITS` and compiled on
demand; `fire_python.c` is deliberately NOT, because its whole surface is
`#if USE_PYTHON 0` stubs and linking it would convert a loud link error into a
silent NULL. Its header was never `#include`d either, so the failure stays loud.

`test_sqlite3_min_proof.lean` **cannot** be annotated, which the original version
of this phase assumed: every `*_proof.lean` is a gitignored build artifact
(`.gitignore:64`), untracked, rewritten by any formal build. Editing it is
possible and pointless — the next `fire.py build --formal` clobbers it. The
finding therefore lives here and in `test_sqlite3_runtime.py`, not in the file
whose name was the problem.

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

**The two holes in the mechanism that checks this** were both closed in the
five-agent round of 2026-09-27, by that round's [5] (`formal/lean.py`) and the
integration that followed it. What they were, and what they are now:

- ~~`check_proof_cached` returns `n_sorries` and **nobody reads it**.~~ Now
  `fire.py` prints the admitted count next to `Proof:` ([4]), `test_formal.py`
  prints the figure per proof **and** the `lib/` halves ([5] + integration), and
  the number is Lean-reported rather than a text count, so it does not move for
  a losing `first | … | sorry` tactic alternative.
- ~~**Vacuity is invisible to the census.**~~ `vacuous_declarations` finds both
  vacuous shapes, and `proof_census` returns a `Census` carrying generated-file
  sorries, library holes and vacuous declarations together. The first thing the
  new census found, on a tree where nothing had reported it:
  `lib/ProofLib.lean:4617` `Semantics`, which states `∀ …, … → True` — vacuous
  by construction, so it carries no information and emits no `sorry` to count.
  `test_formal_dylib.py` now asks the census for the library holes beside its
  text grep, because the grep cannot see them.

**And one thing the census made visible that was not previously written down**,
which is the reason the inventory above is a table and not a paragraph: the
`dylib_export_contract_stub` hole (row 3) is invoked from
`formal/arm64_proof_gen.py:8338` with `obs := fun n => n`, which asserts that
**every** dylib export's behaviour is the identity map. That is not a vacuous
proof; it is an admitted `sorry` over a claim that is false, and it is the
sharpest entry in this table. `lib/` is out of scope for the parallel round, so
nothing was changed — but the figure is now *read* on every run rather than
merely known.

**What the five-agent round did to phase 2, measured.** The word-shaped
callable surface is now *unblocked but not yet reachable*, and the distinction
is the whole remaining step. [3] made the refusal ABI-shaped: a call is refused
for its type, and a word-in/word-out call is explicitly named as one a formal
image **could** make. [2] then made the library exist — a per-architecture
runtime dylib, whose export table now advertises 1964 of 1968 entry points
with 0 misresolved. And [1] made the optional units link, so the non-formal
path is whole: a program calling `mojo_strlen` builds, links and prints `5`.

A *formal* image still refuses `mojo_strlen`, and the refusal is now honest
about why — the image is freestanding, it links libSystem and nothing else, and
the per-arch runtime dylib is simply not on its link line. That is the next
piece of work and it is a `formal/build.py` change, not a codegen one: opt the
formal path into the dylib [2] already builds. Until then the honest statement
of the surface is "0 of the word-shaped calls are callable from a proof", and
the number that will move first when that is done is the phase 2 coverage
figure.

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
- **The sweep's headline has already moved, further than this section predicted.**
  Measured 2026-09-28: **108/416 = 26.0%** on arm64, against the ~8% this
  section was written against. What changed is not that the backend got 3x
  better but that the largest unanswerable bucket stopped resting on a claim we
  knew to be false (`CLASS_HOST`'s "not fixable" was wrong of `os`, `sys`,
  `re`, `json` and 10 more), and that 9 stdlib files stopped being falsely
  classified by the relative-import bug. The lesson worth keeping: a coverage
  number is only as good as the *classification* under it, and the cheapest
  large win in this programme was a truthfulness fix, not a capability.

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

---

## 11. Running this as concurrent work

This section used to be a pointer to `FORMAL-PARALLEL.md`, which held the `[1]`–`[5]`
scopes, the exclusive write sets, the isolation mechanics, the INTERFACE REQUEST
mechanism and the merge order. That document is now **folded in here** and
deleted. The separation was a mistake of bookkeeping, not of judgement: the
scopes are the phases, the write sets are the phases' files, and a round that
had to be looked up in a second file was one more thing to go stale. The
lifetime argument that justified the split has expired — the first round is
merged, so there is no longer a "this week" to be separate from.

### 11.1 The measured state this round starts from

Everything below was measured on `21a82d6` + the sqlite work, not inferred. It
is here because a plan built on the numbers in §2 as they *were* would be
planning against a fiction.

**The sweep says the backend is much further along than §8 implies.**
`tools/formal_sweep.py`, arm64: **590 files, PASS=108, coverage 108/416 =
26.0%** (the denominator excludes the 174 in a not-answerable or tool class,
because a fact about the target is not a gap in the backend). Of the 127
in-file codegen findings, **123 are one unnamed family, "other refusal"** — so
97% of what is actually blocking is not classified at all. That single number
is the strongest argument for agent [4] below. 30 of the 127 sit in files that
also import a host module, so closing them would not raise the rate; they are
counted as findings on purpose, because reclassifying them would improve the
headline without anyone writing code.

**The sorry counter says the proof side is barely started, and now says so out
loud.** `formal/lean.py`'s census, over the 29-proof arm64 corpus: **7 admitted
`sorry` in generated files** across 6 proofs, **2 in `lib/`**
(`in_image_stub`, `semantics_stub`), **1 vacuous** (`Semantics` at
`lib/ProofLib.lean:4617`, which states `∀ …, … → True`), plus
`dylib_export_contract_stub` in `lib/Refine.lean`, invoked with
`obs := fun n => n` — an admitted `sorry` over a claim that is **false**. None
of these were visible before the counter existed; all are still open. And the
number that does *not* appear in any census is the largest one: every extern
call site generates `extern_<sym>_step : True := by trivial`, which is
vacuously true and so contributes **zero** sorries while being worth nothing.

**Self-certification — the actual goal — is blocked in three distinct places,
and only one of them is an error message.** The goal is that the compiled
`fire.py`, fed the same input as the python3 one, produces the same output.
Measured:

1. **Proof generation fails on any program that makes a call.**
   `formal/arm64_proof_gen.py`'s `emit_block` raises
   `ValueError: unsupported: recursion argument bound (not a dec1 pattern)` for
   `fn main(): print(42)` and for anything else with a call; only a bare
   `return` survives. So a large part of the corpus currently has no proof at
   all, and `fire.py build --formal` prints no `Proof:` line to put a sorry
   count on. The compiled path is not behind here — it is *absent*.
2. **The self-hosted binary runs but computes wrong answers.**
   `bootstrap-stage2-dumps` no longer segfaults (re-measured 2026-09-27: exit 0
   on a two-line program, 12.1 MB, 94.6 M instructions) but does not reproduce
   the reference dumps: sub-jobs return `mojo_unsupported_iter` no-ops or a
   wrong dump. It is emitted from **exactly one place** —
   `mojo/backend_gimple/emit_loops.py:206`, the generic loop fallback, which
   emits the call and **runs the body zero times**. The other 16 textual hits
   across the gimple backend are comments recording this same bug, and they
   name the forms that fall into it: no `zip()` lowering, no `reversed(<list>)`
   lowering, `for w in pat.findall(s)`, `with` blocks, and generator
   expressions. So this is one site with a known list of offenders, not 17
   independent ones — which makes it a much better-shaped piece of work than
   the grep count first suggests. A silent no-op is the worst class
   of defect for this goal: it cannot be caught by an exit code, and it is
   exactly what a self-certifying compiler must not do to its own input.
3. **The resource blowup** (`bugs/CODEGEN_bootstrap_resource_blowup.md`,
   58.6 GB / 1.24 T instructions on a real self-host input) is the documented
   *upstream* cause and is localised, not fixed. Not assigned below, because it
   is one optimisation with a known shape rather than five parallel items — but
   agent [1] is expected to shrink it as a side effect, since a no-op that
   silently discards work is also work not done.

**`comptime` is the clean example of why a self-certifying compiler needs a
parity test rather than a test per feature.** Measured, same program both ways:

| | statement form `comptime { … }` | expression form `comptime f()` |
|---|---|---|
| `python3 fire.py run` | **`NameError: name 'comptime' is not defined`** | **`NameError`** |
| `fire.py build` then run | works, prints | **prints `0`, where `f()` returns `7`** |

Three different answers for one construct, and the worst one is silent. The
sweep independently names the same family — `comptime value does not fold`, 2
findings. The general shape is the point: the interpreter is *behind* the
compiled backend here, which inverts the usual direction, so a test that only
exercises the compiled path would pass.

### 11.2 The five agents

Partitioned so that no two agents share a writable file. The label is how we talk
about work; put it in commit subjects and in INTERFACE REQUESTs.

| agent | theme | exclusive write set |
|---|---|---|
| **[1]** | **the silent no-op class** — make every `mojo_unsupported_iter` correct or loud | `mojo/backend_gimple/emit_loops.py`, `emit_stmts.py`, `emit_exprs.py`, `emit_calls.py`, `emit_funcs.py`, `emit_methods.py`, `emit_infra.py` |
| **[2]** | **proof generation correctness** — the `ValueError` that kills any program with a call | `formal/arm64_proof_gen.py`, `formal/x86_64_proof_gen.py` |
| **[3]** | **the Lean model, owned for the first time** — call/return semantics, non-vacuous semantics | `lib/ProofLib.lean`, `lib/Refine.lean`, `lib/X86.lean` |
| **[4]** | **feature parity and the refusal taxonomy** — `comptime`, and naming the 123 | `myinterpreter.py`, `gimple_codegen.py`, `tools/formal_sweep.py` |
| **[5]** | **the formal path links the runtime dylib** — the phase-2 payoff | `formal/model.py`, `formal/build.py`, `formal/imports.py` |

Everything not listed above belongs to somebody. If it seems to belong to
nobody, it belongs to whoever owns the nearest file, or it is an INTERFACE
REQUEST.

**Why these five, and not the phases.** Phases 0–2 landed in the previous round
and are done. What remains is phase 3 (the Lean model) and its dependants, plus
the three self-certification blockers above — and those five blockers partition
cleanly by file, which phases do not: phase 3 is one modelling problem with a
fan-out, and the self-certification work is three unrelated ones. The write sets
are disjoint, which is the property that actually makes five agents safe. Order
matters only in that [1] and [2] are the two whose fixes change what the gate
measures, so they want merging first.

**Deliberately unowned this round:** `runtime/`, `build_config.py`, `driver.py`,
`build_stdlib_dylib.py`, `cas.py`, `reflect.py`, `fire_compiler.py`,
`mojo/middle/*`, and `test_sqlite3_runtime.py`. Those are settled — agents [1]
and [2] of the *previous* round landed them, and this round is not to reopen
them. In particular [1] must not "fix" the no-op class by making the compiler
call into `runtime/`, and nobody edits a `.lean` file except [3].

#### [1] The silent no-op class

*Why first.* It is the only item on this list that makes the compiled compiler
**lie** rather than fail, and self-certification is precisely the property that
a lie destroys. Everything else on this list produces a red test.

*What.* One emission site, `emit_loops.py:206`, reached by a generic fallback
whenever a loop's iterable has no lowering. It emits the call and the body runs
**zero times** — a silent wrong answer, and the reason a self-hosted `fire.py`
compiles and exits 0 while being wrong about its own input.

The work is twofold, and the second half is the honest one. Either **lower the
named forms** — `zip`, `reversed(<list>)`, `re.findall`, `with`, generator
expressions — each a bounded piece of `emit_loops.py`; or **refuse the
construct** by name, which is a perfectly good outcome and is what should happen
to anything whose semantics the backend cannot model, because a loop form the
backend cannot lower is also a loop form no proof can reason about. What is not
acceptable is the third option: falling through.

*Do not trust the comment count.* Sixteen of the seventeen textual hits are
comments about this one site. Reading them as a work list produces seventeen
phantom items; reading them as a *list of offenders* produces the real one.

*Trap.* Making it loud is easy in a way that is useless: refusing every
unlowered iterable turns the self-host build red without making anything true,
because the compiler's own source uses these forms. The bar is that each named
form either computes the right answer or is refused *specifically*, and the
self-host build still completes. Measure `fire.py build fire.py` before and
after, and keep the artifact.

*Done when:* the named forms are lowered or individually refused, the
`bootstrap-stage2-dumps` sub-jobs that currently return no-ops either produce
reference-matching output or a named refusal, and `make mojoc` still works.

#### [2] Proof generation correctness

*What.* `emit_block`'s `ValueError: unsupported: recursion argument bound (not
a dec1 pattern)` — pre-existing, reproduces on `fn main(): print(42)`, and
therefore means the arm64 corpus has **no proofs at all** for any program with a
call. That is upstream of everything in `FORMAL.md` §7's inventory: a `sorry`
census is meaningless while the generator cannot emit a proof. Then the two
other Python-side defects the previous round recorded but could not fix:
post-call state **fabricated** as `{pre with pc := bl+4}`, and the byte-identical
duplicated blocks (`generate_arm64_proof` at both `:6034` and `:7222`,
`_gen_extern_test` at both `:5661` and `:6849`, `_find_extern_call` at both
`:5556` and `:6744` — Python binds the second, so `:6849` is live).

*Order.* De-duplicate **before** the semantic work, not during it. Three copies
of a function that is about to change is how a fix lands in the dead one.

*Done when:* `fire.py build --formal` emits a `Proof:` line for a
call-containing program, and the emitted proof for one fixed input is
byte-identical across two runs.

#### [3] The Lean model, owned for the first time

*Why it was unowned and is not any more.* Every previous round deliberately left
`lib/*.lean` alone so this work would be owned cleanly rather than inherited
half-changed. It is now the largest unowned piece of the programme and the
gate for phases 4–7, so it gets an agent.

*What.* Root cause is mechanical and single: the `BL` arm of `arm64_step`'s dispatch
(`lib/ProofLib.lean:1549`, whose comment at `:1548` names the encoding) gives
`BL` a bare `x30`/pc transfer with **no callee**. A dylib or libc branch target
is a `__TEXT,__stubs` address *outside the image*, so `arm64_go_exit` returns
`none` and the model halts. One gap, every downstream symptom. Then, in order:
(1) a call frame, a callee entry, and return-to-`x30`; (2) wire the x86-64
`call_rel32`, which is **already modelled** at `lib/X86.lean:720` and merely
unwired from `_FORMS`/`_SUCCS`/`_resolve` (`bugs/OPEN_WORK.md` A1) — the
cheapest real step in the whole programme; (3) give `DylibExport.Semantics` a
non-vacuous definition against real observables rather than a hardcoded `[]`;
(4) either prove `dylib_export_contract_stub` or **delete it**, since asserting
every export is the identity is false.

*Done when:* a dylib export has a non-vacuous semantics, a caller can discharge
an obligation against it, and `lib/ProofLib.lean:4617` no longer states
`∀ …, … → True`.

#### [4] Feature parity, and the refusal taxonomy

*What, first:* `comptime`. The table in §11.1 is the whole bug — the
interpreter does not have the construct, the compiled backend has it in
statement form, and in expression form it silently yields `0`. Make all three
paths agree, and whichever way they agree, make it agree *loudly*.

*What, second:* the 123 "other refusal" findings. 97% of the in-file codegen
findings are one unnamed family, so the sweep currently cannot answer "what is
actually left". Naming them is not a cosmetic change — it is what turns 26.0%
into a plan. Extend the existing `CLASS_*` machinery rather than inventing a
second taxonomy, and do **not** reclassify a file out of the denominator to
improve the rate; that is the failure this programme has already committed once.

*Done when:* the sweep's family table has no bucket above ~10% of the findings,
and `comptime` gives the same answer on all three paths.

#### [5] The formal path links the runtime dylib

*What.* Phase 2's payoff, and the last thing standing between "the ABI is
word-shaped" and "a proof can call it". The refusal is now honest — a formal
image is freestanding, links libSystem and nothing else, and the per-arch
runtime dylib that the previous round built is **not on its link line**. Opt it
in. Then the number to move is 0 → as much of 219 as the link line can carry.

*Careful.* This is a `formal/build.py` change, not a codegen one, precisely
because it is not a codegen problem. Do not "fix" it by widening
`is_gimple_runtime_builtin` — that predicate answers *can this target bind
this*, and the honest answer stays no until the symbol is genuinely on the line.

*Done when:* a formal image links the per-arch runtime dylib, dyld resolves a
word-shaped `mojo_*` call, and the call is **not** refused. The box-returning
321 must still be refused, and the refusal must still name the type.

### 11.3 The operating rules

- **The partition is file ownership, not task dependency.** One writer per file
  at every moment. Needing a file you do not own is an INTERFACE REQUEST, never
  an edit.
- **Never `git checkout <path>` or `git restore <path>`.** Not to "reset" a
  file, not to clean up a merge, not to drop a stash. It destroys uncommitted
  work with no recovery, and it has destroyed about ten hours of work in this
  project already, in more than one session. `git checkout <branch>` is safe —
  the hazard is path-scoped. Before ANY checkout, run `git status --short` and
  look at what you are about to discard. If you need a file back, `git stash
  push -- <paths>` is recoverable and `git merge --abort` is safe; reach for
  those first.
- **Nobody runs a gate.** Each agent verifies with its own tests, run directly —
  not even `tools/suite.py <one-test>`, which writes the `build/suite.log` the
  integrator needs. The integrator registers the new tests, applies held
  requests, and runs the gate once at the end.
- **Do not add an `expect=` marker to make something green.** That is silencing
  a test, and `tools/suite.py` is set up to report an `expect`-marked test that
  *passes* as a failure precisely so a stale marker cannot survive.
- **Take the 80/20 and leave a note.** A precise "this costs weeks, and here is
  why" is a **deliverable**; a half-finished attempt is not.
  `bugs/FORMAL_known_limits.md` has the table shape for that — measured count,
  whether the refusal is *true*, what closing it takes.
- **`GMOJO_HOME` is per-agent, always.** One environment variable, and it removes
  every CAS contention, torn cache entry and dylib overwrite question. Set it
  on **every** command, no exceptions: `export GMOJO_HOME="$HOME/.gmojo-agent-N"`.
- **The one repo-root collision that matters is building the same basename**
  (`fire.ci` from `fire.py build fire.py`, `./mojoc` from `make mojoc`). Every
  other artifact is named after the test that produced it, so two agents running
  different tests in one directory do not collide.
- `lib/*.olean` is shared but **safe**: `ensure_library` (`formal/lean.py`) builds
  it under an exclusive `flock` and writes via a private temp + `os.replace`, so
  concurrent callers queue rather than corrupt. The hazard is staleness, not
  corruption. Do not `rm` anyone's `.olean`/`.srcsha256`/`.buildlock`, and do
  not `rm -rf lib/`. To work against your own copy, copy `lib/*.lean` into your
  own directory and pass it as `repo_root` — `formal/lean.py` derives `lib_dir`
  from it.
- **In a shared tree, leave alone:** `build/`, `__pycache__`, `*.o`. Do not
  rename, reformat or "tidy" anything outside your write set, however ugly it
  looks — that is how two agents end up fighting over a diff neither intended.
  Do not edit `FORMAL.md` or `tools/suite.py`; they are integrator-owned.

### 11.4 The easy/hard line, so nobody grinds

| take it | leave it, and write it down |
|---|---|
| anything in your write set that a test can pin | Stage 5 monomorphization (`FORMAL.md` phase 7 — "weeks, not an afternoon"; `FORMAL_known_limits.md` §1.2) |
| a refusal made **true** rather than more capable | MLIR attribute templates (46 files, a **permanent** limit, `FORMAL_known_limits.md` §2) |
| a number that is wrong, fixed by measurement | anything needing a heap or allocator — the slab allocator, phase 6, gated behind [3] |
| a silent wrong answer turned into a loud one | a `mojo_*` call returning a heap box (needs the ABI decision, not a codegen patch) |
| | adding a **capability** whose value model does not exist yet |

If you hit the wall, the deliverable is a bug doc with a repro and a cost, or an
INTERFACE REQUEST — not a grind.

### 11.5 INTERFACE REQUEST

For anything crossing an ownership boundary:

```
INTERFACE REQUEST  from=[N]  to=[M]  file=<one path>
WHAT:   the exact change, as a diff if you have written it somewhere legal
WHY:    one line
BLOCKS: what of yours cannot land without it
```

Writing the diff in a scratch file and handing it over is encouraged. Keep
working on everything that does not depend on it; most requests are
non-blocking by design.

**An INTERFACE REQUEST file is deleted in the merge that answers it.** A file
whose sections are all resolved is indistinguishable from an open one to whoever
opens the queue next, and the sections reading `OPEN, to=[4],
file=formal/build.py:629` are the actively misleading part — the line number no
longer means what it meant. Each request's content is expected to have landed as
a commit, a test, or a row in this document; none of it lives only in the
request file. To restate the rule the bug docs already follow: **if the answer
is in the tree, the request is not.**

### 11.6 Merging

1. **[1]** and **[2]** first — they are the two whose fixes change what the gate
   measures, so everything after them is measured against corrected code.
2. **[4]** next — it makes the instruments stricter, and applying that to
   finished work is better than firing halfway through everyone else's.
3. **[3]** then. It is the deepest change and the one most likely to need a
   second pass once the others are in.
4. **[5]** whenever it is ready; it is independent of all of them.

The integrator, and only the integrator: applies held requests, registers all new
test files in `tools/suite.py`, resolves any overlap that turns out to be real,
updates this document with what actually landed, deletes the bug doc for any bug
that is now **fixed** (a doc for a fixed bug is a doc that lies), and then
**runs the gate once**.
