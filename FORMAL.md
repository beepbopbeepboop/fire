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
5. **There is deliberately no logical-shift operator on this target, and `>>`
   is arithmetic even on a signed value.** `formal/model.py`'s
   `shift_signedness` reads the LEFT operand alone, because the right operand of
   a shift is a COUNT and how far to move says nothing about what to move in —
   `common_type`'s signed-wins rule is right for `/` and `%`, where the operands
   genuinely combine, and wrong here. A program that wants zeros shifted in says
   so with an unsigned type. Pinned by `test_formal_run.py`'s
   `ushift_u64_by_typed_int_amount`, `…_typed_u64_amount`, `…_literal_amount`,
   `…_variable_amount` and `signed_shift_by_unsigned_amount_stays_arithmetic`.

   **Do not add `>>>`.** It is not a way to spell this, and the reason is
   measured rather than remembered: `fire_compiler.py`'s `_PREC` has `<<` and
   `>>` and no `>>>`, and **CPython 3.14.7 rejects it too** — checked through
   `ast.parse`, through `exec`, and through `eval` of a string built at run time
   (`op = ">>" + ">"`), so it is the grammar and not the shell. Adding it would
   make this compiler accept a program its own oracle refuses. The bug doc that
   worked this out is deleted with its fix; this line is what is left of it,
   because "add the missing operator" is exactly the fix a future reader will
   propose.

6. **`with EXPR as TARGET:` is the context-manager PROTOCOL, and a value that is
   not enterable is REFUSED rather than bound.** `formal/build.py`'s
   `_rewrite_with_statements` lowers every `with` to `__enter__` (which produces
   the name the body sees) plus `__exit__` in a `finally`, and
   `formal/model.py`'s `struct_is_context_manager` says which values can be: a
   FRAMED struct declaring both dunders, whose receiver is the frame's address —
   which is the by-reference receiver, so no part of the value model moves. Every
   other `with` is refused by name, which is what CPython does with a value that
   has no `__enter__`.

   **The lowering this replaced bound the name to the expression's value and ran
   the body, and that is a wrong-but-exit-0 answer with nothing on the link line
   to catch it**: `with tempfile.TemporaryDirectory() as d:` printed every right
   answer and left the tree behind, and `with closing(7) as v:` printed `v=7`
   where CPython raises `AttributeError`. Both emitters' `_emit_with` docstrings
   said so at the time, which is how it stayed true for so long.

   **Do not add a `with` lowering to a backend.** One implementation, in the pass
   that owns statement rewriting; a `WithStmt` reaching an emitter is an internal
   invariant and is refused as one.

7. **A `finally`'s fall-through copy is emitted even when an exit edge inside the
   body already flushed it.** The old rule read "the frame was flushed, so the
   end of the block is unreachable" and dropped the copy, which is true only of an
   unconditional `return`. A conditional `return`, and a `continue`/`break` in a
   loop, are different paths through the same block and are still reachable —
   measured on both machines: `try: if n > 0: return 1 … finally: print()`
   printed nothing at all when `n` was 0. `formal/arm64_codegen.py`'s
   `_emit_try` and its x86-64 twin.

   **Do not restore the suppression to save bytes.** The copy is dead code in the
   unconditional case, and dead code costs bytes; the suppression costs a cleanup
   that does not run, which is the failure this project refuses everywhere else.

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

**That sentence is about the SOURCE TEXT, and a theorem's transitive closure is a
different question.** `native_decide` and `bv_decide` close a goal by compiling
and running a decision procedure rather than by producing a term the kernel
checks, so every theorem proved with one depends on a GENERATED AXIOM and
`#print axioms` reports it — which `OPUS.md` §1 already says about a generated
theorem.  **What that axiom is called is the one thing this paragraph got wrong
twice.**  It said `Lean.ofReduceBool`, and on the pinned toolchain
(`leanprover/lean4:v4.32.2`) `ofReduceBool` is DEPRECATED — "in-kernel native
reduction is deprecated; assert native evaluations with axioms instead" — and
each USE of a reflection tactic elaborates to a fresh axiom named after the
declaration that used it: `'work_step_mov._native.native_decide.ax_1_1'`, with
`_1_7` counting reflection uses in the whole MODULE.  A census that grepped for
`ofReduceBool` would therefore have called a library that reaches an axiom at
every one of its sites clean.  The instrument that matches what Lean prints is
`formal/lean.py::GENERATED_AXIOM_RE`, and the measurement is
`test_formal_axioms.py`.

There are no `axiom` declarations and no `sorry` in any of the five `lib/`
modules, and 688 proof sites go through one of those two tactics — 751 before
2026-10-04, and the 749 this section published until then was an UNDER-count
of its own scanner (`lean_code_regions` read an identifier's apostrophe as a
character literal, blanked 97 real declaration headers as prose, and so missed
two sites).  Both halves are counted by `test_formal_admitted.py`
(`LIBRARY_TRUST`, a hard 0 for the first two and a ceiling for the third,
because that number is a debt being paid down in a file several branches edit).
Neither tactic can prove a FALSE
statement — it evaluates and answers — so this is row 10 below about where the
trust SITS, not about whether it holds, and
`bugs/FORMAL_native_decide_axiom.md` carries the replacement plan and what is
left of it.

| # | where | what is trusted |
|---|---|---|
| 1 | `lib/ProofLib.lean:4624` `in_image_stub` | a dylib export is in the image |
| 2 | `lib/ProofLib.lean:4627` `semantics_stub` | an export has a semantics; the goal is vacuous regardless |
| 3 | `lib/Refine.lean:660` `dylib_export_contract_stub` | an export computes its observable |
| 4 | `formal/x86_64_proof_gen.py:239` `_compile_correct_section` | the AST compiles to the emitted bytes (x86-64) |
| 5 | `formal/x86_64_proof_gen.py:690` | the x86-64 end-to-end theorem |
| 6 | `formal/arm64_proof_gen.py:6910` | every extern call step (`True := by trivial`) |
| 7 | `formal/arm64_proof_gen.py`'s `CFG_LEAF_SITES` | every CFG leaf that admits — **fifteen named sites**, each stamping its name into the generated Lean: the eight `all_goals (first \| done \| sorry)` leaves of the walk, the five `for i in range(…)` obligations, and the two loop-contract closers. Owned by `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` and `bugs/FORMAL_arm64_a_cbz_on_a_literal_pool_register_admits_over_a_false_claim.md`. Named rather than counted by line number because this row and the trust audit's table had already disagreed about how many there were (seven here, eight there), and `cfg_leaf_census` / `no_admission_fallback` turn "which of them admits" into a measurement |
| 8 | FORMAL.md §7a | **the ADMITTED HOST CONTRACTS**: one `sorry` per `@admitted(...)` in a `formal/hostmods/` module, counted by the same census as every other hole, named per file by a `trust:` line, and classified by `tools/formal_sweep.py` as `built-with-admitted-contracts`. 19 of them across `concurrent.futures`, `ctypes`, `subprocess` and `threading`. `fcntl` admits nothing and is not among them; the figure was 15 and the list did name `fcntl`, until the audit of 2026-10-04 found both stale. This is the FIRST row here that is about the HOST rather than about this compiler's own code: it is a claim about a second process, a thread and a dynamic loader, declared in the Mojo source and checked for scope AND checked for TRUTH — every contract is probed against CPython or the OS, and fifteen of the nineteen were found asserting something the host does not do. The policy is §7a; the per-contract assumptions are in each module's own `@admitted` text, and `bugs/FORMAL_trust_audit_2026-10-04.md` is the audit that corrected them |
| 10 | `lib/ProofLib.lean`, `lib/Contracts.lean`, `lib/X86.lean` | `native_decide`/`bv_decide` sites, whose proofs reach a GENERATED AXIOM rather than the kernel — the largest admitted assumption in the model, and the one §7's preamble used to leave out of the inventory entirely. Counted as of 2026-10-03: total **751**, replaced **63**, remaining **688**. The 63 were CLOSED propositions over literals (`¬ (0xd65f03c0 &&& 0xffe00000 = 0x2a00fa00)`, `(1 : UInt64).toNat = 1`), which `decide` discharges in microseconds and the KERNEL checks; what remains is 685 `bv_decide` over a quantified 32-bit word plus three `native_decide` that evaluate the model at a ground image (`runExport … = none`, `InImage …`). `NATIVE_DECIDE_ALLOWED` in `test_formal_admitted.py` names the three, so a `native_decide` added anywhere else fails by name rather than as a module that grew. Owned by `bugs/FORMAL_native_decide_axiom.md`, which carries the plan, the per-shape timings, and the fact that the 686+ `bv_decide` sites are the shape `decide` cannot take |
| 9 | ~~`lib/ProofLib.lean:895`~~ | **REMOVED 2026-09-28.** This row said "All per-node lemmas currently admit". Read, they do not: all seven `evalExpr_*` lemmas are `rfl`, which is the whole content of each statement, and `lib/ProofLib.lean` contains no `sorry` or `admit` at all. The section comment above them said the same false thing and said so in the present tense; both are corrected. The trust that remains is row 4 — `rfl` proves the unfolding of `evalExpr`, not that `evalExpr` is what the machine runs. |

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

## 7a. ADMITTED HOST CONTRACTS — the one place the policy lives

A module can be **unreachable** on this target and still be answerable. `subprocess`
needs a second process, `ctypes` needs a dynamic loader for foreign code,
`threading` and `concurrent.futures` need a thread, `fcntl` needs a kernel-held
lock — none of which a freestanding image linking libSystem and nothing else has.
`formal/imports.py` refused every file importing one, which is a true statement
about the TARGET standing where a statement about the FILE belongs, and it is why
30 files of the arm64 sweep were reported for a fact no work in this tree can
change.

The question this adds is the one the `HOST_MODELLED`/`HOST_UNREACHABLE` split was
missing: **what would a proof have to ASSUME about the host to accept the file?**

Each such module gets a Mojo-side model of its **API shape** in
`formal/hostmods/`, and each operation whose answer is an external fact is
declared an **admitted contract**:

```mojo
@admitted("the child's exit status, an integer in 0..255, and the captured "
          "output bytes are an arbitrary byte string")
def run(request: str) -> int:
    ...
```

Five rules, each of which is enforced somewhere other than this paragraph, because
a rule stated only here is a rule that rots.

**1. The declaration is written once, in the Mojo source.** `formal/admitted.py`
is the only reader and the only place the text is shaped; the `trust:` line, the
generated Lean docstring and the sweep's class reason are all rendered from it. A
reader of `formal/hostmods/subprocess.mojo` reads the same sentence a reader of
the `trust:` line does.

**2. An admission may constrain the host's ANSWER and nothing else.**
`formal/admitted.py`'s `contract_text_is_scoped` refuses any contract text
containing "always", "never", "deterministic", "empty" or "no other". A claim
about what the host *does* is not an admission — it is an unproved assertion with a
proof attached to it, which is exactly what the deleted
`dylib_export_contract_stub`'s `fun n => n` was.

**3. It is `sorry`, not `axiom`, because `sorry` is countable.** §7's position is
that this project has no `axiom` and no `opaque` anywhere, and that is load-bearing
rather than stylistic: `formal/lean.py`'s census counts what Lean reports as
`declaration uses 'sorry'`, so an admission written as an `axiom` would be a claim
of trust that no count ever reports. Each contract is emitted as

```lean
def admitted_subprocess_run (req : UInt64) : UInt64 := by sorry
```

`def` and not `theorem`, because a `theorem`'s type must be a `Prop` and this
declaration's type is the contract's **value**; measured, `theorem` is refused
with `type of theorem … is not a proposition`. The `sorry` is counted all the
same — Lean's warning fires for any declaration reaching `sorryAx`.

**4. The contract IS the model, and only what depends on it is admitted.**
`formal/arm64_proof_gen.py`'s `_call_go` refuses any callee it has no `_go` for,
which is right for an extern (an extern's return value is not a term the model can
invent) and wrong for a callee whose return value *is* a declared contract. An
admitted call renders as the `sorry`-proved `admitted_*` applied to its argument,
so the model's value is the contract's. Then `native_decide` cannot close a
theorem about that value — it *executes* the model — so those theorems are
emitted as named `sorry`s by `_decide_or_admit`, and **everything else in the file
keeps its normal proof**. The condition is about CALLS, not about contracts being
present: a file that imports `subprocess` and never calls it links a library with
seven contracts in it and its own proof is decidable.

**5. An admitted call REFUSES at run time, and the refusal is identified by the
diagnostic, not by the number.** `subprocess.run` prints which contract stopped
it and exits **125**.  A refusal that RETURNED a plausible number would be a
fabricated answer wearing a diagnostic's clothes, so what makes the mistake
impossible is that it exits at all; the number then says only that the image did
not answer, and it says that by being nonzero and reserved by this tree.

This rule used to claim something false, and the correction is the kind of thing
an audit exists to find: it said 125 was *outside 0..255* and therefore could not
be read as a child's exit status.  125 is inside it (`sh -c 'exit 125'` is
reported as 125), and **no exit code can be outside it at all** — the kernel
masks one, so `sh -c 'exit 300'` is reported as 44.  The diagnostic on stdout is
the channel that distinguishes a refusal from an answer;
`test_formal_admitted.py`'s `truth` group re-measures both halves every run so the
claim cannot rot back.

### What each contract assumes

The counts in the next table are **checked against the declarations** —
`test_formal_admitted.py`'s `test_the_formal_md_inventory_agrees` reads this file
and fails in both directions.  A census published in prose is a census with two
copies, and until this row was added the second copy was free to describe a trust
boundary that no longer existed: it said `subprocess` admits 7 and `fcntl` 1,
against 12 and 0.  The ASSUMPTION column is a summary; each module's own
`@admitted` text is the text, and `bugs/FORMAL_trust_audit_2026-10-04.md` carries
the audit of it against CPython.

| module | contracts | assumes |
|---|---|---|
| `concurrent.futures` | 2 | `submit` runs the callable on a thread of this process or in a process of this machine and answers one word; `shutdown(wait=True)` has joined the pool's OWN workers |
| `ctypes` | 2 | `CDLL` returns 0 when `dlopen(3)` failed — the file may be absent, may not be a loadable image, or a symbol may be unresolvable — or a non-zero word this target's loader owns; a call through a handle answers one word under the default `restype`, unconstrained in value |
| `subprocess` | 12 | the child's status word: `0..255` for a normal exit or `-N` for a death by signal N; output answers stop at the first NUL byte, because a `str` here is a NUL-terminated `char *`; `poll`'s "not collected" marker is the model's own `-65`, outside every answer the host gives; `kill`/`terminate` deliver only while the child is still running |
| `threading` | 3 | `Thread.start` begins running the target; `Thread.join` with no timeout, it has stopped; `Lock.acquire` is a per-object userspace mutex inside this process, naming no descriptor |

**Fifteen of the nineteen were FALSE of the real host**, three more were true only
under a reading the audit had to guess at, and one was true and is unchanged:

| what was claimed | what the host does |
|---|---|
| six `subprocess` contracts: "the exit status, an integer in 0..255" | CPython reports `-N` for a death by signal, and `subprocess.run(["sh","-c","kill -9 $$"]).returncode` is `-9` |
| three `subprocess` contracts: the output is "an arbitrary byte string" | a `str` on this path is a NUL-terminated `char *`, and CPython's answer really does contain NULs: `check_output(["sh","-c","printf 'a\0b'"])` is three bytes |
| `popen_poll`: `-1` while the child has not been collected | `-1` is an answer CPython gives -- a child killed by `SIGHUP` -- so the model's "not collected" marker and a real answer were one word |
| `popen_kill`/`popen_terminate`: "the signal reaches the child this handle names" | once the child has been collected CPython sends **nothing** and raises nothing: `Popen.send_signal` polls and returns |
| `ctypes.CDLL`: "0, meaning no library of that name is on this target" | `dlopen` fails on files that EXIST and are not loadable images, so handle 0 does not mean the library is absent |
| a call through a `ctypes` handle: "the value the foreign function returns is one word" | true of `ctypes`' default `restype` of `c_int` and of nothing else: `restype = None` answers `None` |
| `threading.Lock.acquire`: "the lock is held by the kernel on a descriptor" | CPython's `threading.Lock` is a userspace semaphore with no `fileno`, no `_handle` and no descriptor, and a CHILD PROCESS took `fcntl.flock(LOCK_EX)` on a file while this process held one |
| `Executor.submit`: "the callable runs on some thread" | a `ProcessPoolExecutor` runs it in another PROCESS, measured by having the callable report its own pid |

True only under a reading the audit had to choose, and now said out loud:
`Thread.start` "has run the target callable" (it has BEGUN -- `start()` returns
before a sleeping callable finishes), `Thread.join` "the thread has stopped" (true
of `join()` with no timeout, false of `join(timeout)`), and
`Executor.shutdown(wait=True)` "every thread the pool started has stopped" (true
of the pool's OWN workers -- a thread a submitted callable started itself is
still running when it returns).

Every one of them now has a `truth` row in `test_formal_admitted.py` that
re-measures it, a contract that lands without one fails the
`every admitted contract has a truth row` check, and every row is checked in the
other direction too: `every truth probe rejects the pre-audit text` puts the old
sentence back through its own probe, so a probe that stopped testing what it was
written for fails as well.

Everything a hostmod **decides** rather than admits is checked against CPython's
own answer by `test_formal_admitted.py` — `subprocess`'s argument shapes and
constants, `ctypes`'s thirteen sizes and five conversions and three buffer
refusals, `fcntl`'s eleven flags, `Future`'s five states against a live `Future`,
`threading`'s `TIMEOUT_MAX` against CPython's own `Lock`. That half is what stops
the trust from growing to cover something CPython can simply be asked about, and it
has already earned its keep: it caught `TIMEOUT_MAX` written as 2^63−1 when
CPython's answer is 9223372036, and a timeout check that refused `-1` — the value
`Lock.acquire` passes itself.

### Where the trust is visible

| surface | what it shows |
|---|---|
| `fire.py build --formal` | a `trust:` line naming each contract and its assumption — on its OWN line, not appended to `Proof:`, because the sweep builds with `--no-prove` and a note attached there would vanish for exactly the files whose class depends on it |
| `result["admitted"]` | the same list as plain dicts, computed once, computed ALWAYS, handed to the proof generator so the proof and the verdict cannot describe different admissions |
| the generated Lean | one `def admitted_<module>_<name> … := by sorry` per contract, each with its assumption in its docstring, under a `/- ADMITTED HOST CONTRACTS -/` header naming all of them |
| `formal/lean.py`'s census | the count, as Lean reports it — the same instrument that counts every other hole in this project |
| `tools/formal_sweep.py` | the class `built-with-admitted-contracts`: in the answerable denominator, NOT in the numerator |
| `test_formal_admitted.py` | `ADMITTED_COUNTS`, pinned per module, failing in BOTH directions |
| `test_formal_admitted.py`'s `truth` group | every contract's ASSUMPTION against CPython or the OS, and this file's own inventory against `counts_by_module()` — the instrument that found the eight false contracts |

The sweep class is the one that matters for a coverage report. A `pass` is this
tool's claim that the image built and every symbol it binds is on its own link
line; a file that also asked a second process to answer a question has not had
that claim made for it. It is deliberately in the denominator and not the
numerator, so the headline rate can only go **down** as more of the tree is
admitted against — which is the direction a rate about provability has to move in.

### Two limits worth knowing, both stated rather than hidden

- **One word per admitted call.** `MojoExpr.call` in `lib/ProofLib.lean` carries a
  single `UInt64`, so the AST layer of a proof can only evaluate a one-argument
  call. An admission applied to two arguments in the source model and one in the
  AST model would make `eval_eq_mojo` — the statement that the two layers are the
  same function — *false* rather than merely unproved. So a call with any other
  arity is refused by `_call_go`, naming the call. `fcntl.flock(fd, operation)`
  keeps CPython's real two-argument signature anyway: the task is to model the API
  shape, and a one-parameter `flock` would be a signature CPython does not have.
- **A cross-dylib call whose value is used still has no machine half.** Admitting
  the model is what lets the proof be *generated and typechecked*; the end-to-end
  theorem about a program that calls into a dylib is a separate, pre-existing gap
  (`bugs/FORMAL_lean_model_call_semantics.md`), and the generated file says so at
  the call boundary rather than pretending.

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

### 11.1 What landed, measured

#### Round 1

Five agents, one tree, merged 2026-09-28 at `77c8b90`. Every number below was
measured after the merge, not carried over from a commit message.

| | before | after |
|---|---|---|
| `lib/` admitted holes | 3 modules, 4 sorries + 1 vacuous | **zero** (`lib/ProofLib.lean`, `lib/Refine.lean`, `lib/X86.lean` contain no `sorry` or `admit`; verified by reading) |
| a `mojo_*` call from a formal image | always refused, one reason | **three ways** — linked, refused for its TYPES, refused because the per-arch library does not export the name |
| proof generation on any program with a call | `ValueError: unsupported: recursion argument bound` | generates; `formal-run` **340/0** (was 338/2, then 339/1) |
| arm64 sweep codegen findings, named | 123 of 130 in one "other" bucket | **0** unclassified across 20 families |
| arm64 sweep coverage | 25.9% | 25.9% (595 files; the denominator moved, the rate did not) |
| `stdlib-syntax` unexpected failures | 0 | **0** — [1]'s compiled-path work regressed nothing |
| `test_formal_run.py` | 338/2 | **340/0** |

**The three holes in §7 are closed, and one of them was worse than recorded.**
`in_image_stub` is a decidable `in_image_decide` check; `Semantics` is split
into `Total` and `Functional`; and `dylib_export_contract_stub` — the admitted
`sorry` that asserted *every* dylib export computes the identity — is
**deleted**, replaced by an `export_result_spec` obligation plus a proved
`dylib_export_contract_of_spec`. The false claim was measured before it was
removed: `export_result dylib_image triple 7 = 21`, where the stub's shape
could not have distinguished that from `7`.

**§7 row 8 was itself wrong and is now struck.** It read "All per-node lemmas
currently admit" at `lib/ProofLib.lean:895`. Read, they do not: all seven
`evalExpr_*` lemmas are `rfl`, which is the whole content of each statement,
and the file contains no admitted hole. The section comment said the same false
thing in the present tense; both are corrected. The trust that remains is row 4
— `rfl` proves the unfolding of `evalExpr`, not that `evalExpr` is what the
machine runs.

**Nothing needed a `sorry` filling, and that is the finding rather than the
absence of one.** Every unproved obligation the round found is already encoded
honestly: as a decidable check (`in_image_decide`), as a hypothesis the caller
must discharge (`Total` is a `def … : Prop`, not an admitted theorem), or as a
deletion. [2] declined to assert a partial `x86-64` round-trip theorem that
stops at the register file, and recorded the missing induction in the
docstring instead — the right call, and the reason the old `Semantics` came to
state `True` is that a partial theorem can read like a whole one. **Adding
sorries here would have been a regression in exactly the property this
programme exists to improve.**

#### Round 2

Five agents, one tree, merged 2026-09-28. Every figure measured after the merge.

| | round 1 left it | round 2 |
|---|---|---|
| `lib/` admitted holes | 0 | **0** — and 0 `axiom`, 0 vacuous, across all five files |
| a dylib export's `Total` | stated, unproved | **proved**, and the statement was **false** before [2] looked |
| x86-64 call/return | stack pointer only | **both halves** — the `rip` half is a theorem |
| x86-64 `call_rel32` | wired, unverified | **verified on all 45 examples** |
| a `True` in a theorem statement | boundary 2 concluded `\| none => True` | **`False`**, with the completing as a hypothesis |
| silent wrong answers in the x86-64 model | 2, unmasked by a gap in the proof chain | **found and fixed** |
| test files run by a registered spec | 34 of 83 | **52 of 83**, 0 undeclared, 21 previously-red now reported |
| arm64 sweep codegen findings named | 0 of 130 in "other" | **0 of 131** |
| `stdlib-syntax` unexpected | 0 | **0** |

**[2] found that `Total` was not merely unproved but FALSE.**
`DylibExport.Total` was `∀ (n : UInt64) (s : Arm64State), runExport … n = some s`
— with `s` arbitrary that says the run returns *every* state, and it is refuted
by taking `s` to be a state that is not the result. Unprovable even for a
trivially total function. So the generator's `{ident}_semantics_total := by
sorry` was not standing on a hard theorem; it was standing on an impossibility,
and a named `sorry` is exactly what the hole census is trusted about. `Total` is
now `∀ n, ∃ s, …`, and the witness is the entire content of the step bound
[2] then proved. `Semantics_refutable` had to be restated accordingly, which is
the tell that the old shape was wrong.

**[1] found two silent wrong answers in the machine model, and a gap in a proof
chain is what hid them.** `x86_rm_read` with mod = 3 returns the whole register —
right for the 8-byte reads it also serves — and the movzx/movsx arm used
`x86_sign_extend32`, which extends **bit 31**, for the byte form too. So
`movzx rbx, bl` with `rbx = 0xff42` gave `0xff42`, and `movsx rbx, bl` with
`bl = 0xff` — that is, −1 — gave **255**. Confirmed by evaluating the model.
It was invisible because the only three examples emitting a byte `movsx` had no
step lemma wired, so the value test stopped at "no lemma" and never reached the
comparison. Correcting the model also broke `x86_step_movzx_rax_al`, which had
concluded `rax := s.rax` and been proved by `simp`: the theorem and the defect
had agreed with each other. And correcting it broke 14 examples until the
successor table in the test file — a second hand-written copy of the model's
semantics, correct only while the model was wrong — was corrected with it.

**[5]'s inventory is the round's quietest and most useful result.** 83 test
files; 50 were named by no registered spec and **21 of those exited non-zero**,
carrying known-failing assertions that no gate, tally or coverage number
reported. Between their measurement and the merge, three more had been added
and still ran by nothing — [4]'s `test_returned_frame_layout.py`, and my own two
instruments from the previous round, which I had flagged as integrator work and
then not done. 16 orphans are now registered, and the 11 red ones carry
`expect=` with a reason each: a declared red is a report and an unrun red is
silence, and the anti-rot now fails any of them that starts passing.

**And a green test that could never have failed.** `examples-parse` is
`cache=True` and its subject is the 45 files of `formal/examples/`, and its
cache key read 48 repo files and **none** of them under `formal/examples/`. A
`SyntaxError` in any of the 45 could not invalidate the key, so a recorded PASS
replayed — which is not hypothetical: `19bc0dd` took 4 of those files out of the
parser and the only symptom was a coverage number 4 points low.
`checked_run.py` now takes a **directory** in `--extra` and hashes its recursive
contents by relative path, so the 46th example is covered the day it is added
and a rename moves the key.

### 11.2 The five agents

The next round is the one this programme has been deferring: Lean, and the hard
part of it. Three of the five agents own a `lib/` file outright, which is what
makes them parallel — the round before could not assign `lib/` to anyone
because there was no honest way to split a model, and split it wrongly.

| agent | theme | exclusive write set |
|---|---|---|
| **[1]** | **x86-64, completed** — the `rip` half, `call_rel32`, and trust boundaries 2 and 3 | `lib/X86.lean`, `formal/x86_64_proof_gen.py`, `formal/x86_64_endtoend_test.py` |
| **[2]** | **the step bound** — what discharges `Total` | `lib/ProofLib.lean`, `formal/arm64_proof_gen.py` |
| **[3]** | **per-export contracts** — phase 4 proper, for the surface that is now callable | `lib/Refine.lean`, `lib/work.lean`, **new** `lib/Contracts.lean` |
| **[4]** | **the frame-address design** — ~45% of every remaining codegen finding | `formal/model.py`, `formal/arm64_codegen.py`, `formal/x86_64_codegen.py` |
| **[5]** | **the test estate** — what is not tested, and the machinery that would know | `test_suite.py`, `tools/checked_run.py`, `tools/memcap.py`, **new** test files |

**Lean running is now expected, not forbidden.** §11.3 still says nobody runs a
*gate* — that is unchanged and is about `build/suite.log`, not about Lean. An
agent running its own proofs is how [2] and [3] established that `Total` does
not evaluate and that `triple(7) = 21`; forbidding it would forbid the only
thing that distinguishes a proof from an assertion. `lib/*.olean` is shared but
safe (`ensure_library` takes an exclusive `flock` and writes via private temp +
`os.replace`), so eight agents proving at once queue rather than corrupt.

**[1] x86-64, completed.** The largest single gap and the most self-contained.
Three named pieces, in order:
* the `rip` half of the call/return round trip. `x86_call_ret_balances_stack`
  proves the stack-pointer half; that `ret` lands on `m + 5` additionally needs
  `mem_read_bytes (mem_write_bytes m a v n) a n = v &&& lowMask n`, which is
  **false as a general-width claim** (at width 0 the read is 0 whatever `v` is)
  and so needs the mask to induct on, and the induction needs the pointwise
  byte lemma because the tail of the step compares a `k`-write at `a+1` against
  a `k+1`-write at `a`. That is one medium induction in `mem` and it is the
  whole of what stands between this and a complete round trip.
* `call_rel32` wired into the tree. `bugs/OPEN_WORK.md` A1 is **stale about its
  mechanism** — `_FORMS`/`_SUCCEEDS`/`_resolve` are in
  `formal/x86_64_endtoend_test.py`, not the generator — but its substance
  holds: `call_rel32` is why 7 of the x86-64 examples have "no tree", and both
  successors and a separation fact now exist in `lib/X86.lean`.
* trust boundaries 2 and 3, which the generator's own header declares as `sorry`.

*Done when:* an x86-64 proof file contains no `sorry` in any of its three trust
boundaries, or each remaining one is a hypothesis a caller discharges — never a
`True`. **Trap:** asserting a theorem that stops at the register file. The old
`Semantics` did exactly that and read like a whole one.

**[2] the step bound.** `Total` is stated and not proved, and the reason is
measured: `arm64_go_exit` is structural recursion on fuel, so a symbolic `n`
means a symbolic number of steps and `native_decide` refuses outright
(`Expected type must not contain free variables`). Both directions were checked
— concrete `n` evaluates and is correct (`triple(7) = 21`), symbolic `n` does
not evaluate at all. So it cannot be discharged by evaluation, and this agent
must not pretend otherwise. Discharging it means proving a step bound: a run
confined to the image takes at most one step per instruction, and
`4 * codeSize + 8` is below the fuel. [2] called this "the next piece of phase
4" and "not a design question", and that assessment is the reason it is assigned
rather than filed.

*Done when:* `Total` is either proved for the exports it is stated for, or the
fuel is proved sufficient — and a theorem that assumes it says so at the call
site. **Trap:** proving it for a concrete `n` and generalising by hand.

**[3] per-export contracts.** Phase 4 proper. `export_result_spec` is an
obligation and `dylib_export_contract_of_spec` is proved, so a caller's theorem
now consumes a contract instead of asserting one — but no real *spec* exists
yet for any actual export. 219 of 540 entry points are word-in/word-out and the
per-arch library is on the link line, so there is a callable surface with no
contracts on it, which is the state phase 4 exists to end. Start with the
exports a caller can actually reach today.

*Done when:* at least one real export carries a spec that is not the identity
function, and a caller discharges its obligation against it. **Trap:** writing
`obs := fun n => n` again — that is the shape that made the old stub false, and
it typechecks.

**[4] the frame-address design.** The single biggest coverage lever left, and
not a patch. 45% of every remaining codegen finding is one design defect in five
costumes (`bugs/FORMAL_wide_receiver_by_reference.md`): the receiver of a
multi-field struct is the address of a frame that dies when the function
returns, so returning it is a use-after-free and passing it where a value is
wanted hands the callee a pointer. Measured with the check removed, the same
shape returns 10 on arm64 and 0 on x86-64 where the source says 7. One of the
five families **segfaults** rather than computing a wrong number, so this is the
one item on the list where the current behaviour is loud as well as wrong.

*Done when:* a multi-field struct's receiver has a lifetime the analysis can
follow, and the 18 "returned by its creator" findings are gone rather than
renamed. **Trap:** making the refusals *louder* without changing what is
computed. That converts a wrong answer into a red test, which is worth something
but is not this item.

**[5] the test estate.** The one non-Lean agent, and the one this programme has
underinvested in: every finding in the last two rounds was found by *writing a
program and comparing*, not by a suite. The instruction is to find what is not
tested and say so with evidence — and the standing candidate is already known:
[1] could not construct an input that changes an outcome for one of its four
fixes and has no test pinning it, and said so rather than dressing it up.
`test_silent_noop_iter.py` (16) and `test_formal_call_proof_gen.py` (387) are
this round's precedent: an agent writing the test that would have caught its own
bug.

*Done when:* a written, evidence-backed list of what is untested, ordered by
what a silent wrong answer would cost, and at least the top item pinned. **Trap:**
writing tests that pass. A test that cannot fail is how
`test_formal_dylib.py`'s `lib/` grep stayed green through two rounds of
vacuous theorems.

**Deliberately unowned:** `gimple_codegen.py`, `myinterpreter.py`,
`tools/formal_sweep.py`, `fire_compiler.py`, `build_config.py`,
`build_stdlib_dylib.py`, `driver.py`, `mojo/backend_gimple/*`, `mojo/middle/*`.
Two known items sit there and are next round, not this one: the `comptime`
expression evaluator (`bugs/FORMAL_known_limits.md` §7) and the container-kind
unanimity rule in `mojo/middle/infra_infer.py`
(`bugs/INTERFACE_REQUEST_1_to_middle_infra_infer.md`, which [2] repointed at
`module_gen.py` so it is [1]'s own follow-up rather than an orphan).

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
| a number that is wrong, fixed by measurement | anything needing a heap or allocator — the slab allocator, phase 6, gated behind [4]'s frame-address work |
| a silent wrong answer turned into a loud one | a `mojo_*` call returning a heap box (needs the ABI decision, not a codegen patch) |
| a `sorry` that is a *discharged* hole, replaced by a check or a hypothesis | the `comptime` expression evaluator (`FORMAL_known_limits.md` §7) — a feature, and `gimple_codegen.py` is unowned |
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

**Round 1's order, and why it is recorded though that round is merged:** [1] and
[2] first because their fixes changed what the gate measures, then [4] because
it made the instruments stricter, then [3], then [5]. It worked, and the
part that mattered was not the order but the *ownership* — no two agents shared
a writable file, and the one collision (both [3] and [5] editing
`bugs/FORMAL_known_limits.md`, because the plan partitioned code files and left
docs unassigned) auto-merged and cost nothing.

**This round:**

1. **[2]** first. It is the only agent whose work *unblocks* another's claim
   rather than merely landing beside it: `Total` is what a per-export contract
   is stated against, so [3] can write its specs while [2] proves the bound,
   but [3]'s theorems are only sound once [2] lands.
2. **[1]** next. It is the largest single change and the one most likely to need
   a second pass once the others are in.
3. **[4]** with it. Independent file set, and it is the biggest coverage lever,
   so the sweep should be re-measured against a corrected backend.
4. **[3]** when [2] has landed.
5. **[5]** whenever it is ready; it is independent of all of them and its output
   is a list, which is worth having early rather than late.

The integrator, and only the integrator: applies held requests, registers all new
test files in `tools/suite.py`, resolves any overlap that turns out to be real,
updates this document with what actually landed, deletes the bug doc for any bug
that is now **fixed** (a doc for a fixed bug is a doc that lies), and then
**runs the gate once**.

---

## 12. Every Lean run is bounded — the launch policy

`formal/lean.py::run_lean` is the **only** way this tree starts Lean 4, and
every run it makes carries an upper bound on wall time, on total CPU across the
whole process tree, and in Lean's own `maxHeartbeats`. The numbers and the
measurements behind them are in that module's docstring; this section is the
policy, and it is here rather than only there because a bound nobody can find is
not a policy.

**Why it exists.** On 2026-10-02 the user killed ten `lean` processes on this
machine by hand, some of them hundreds of CPU-hours old. A valid inductive proof
here checks in seconds to minutes, so those were non-terminating elaborations,
and nothing would have stopped them: the launch sites that had a bound at all
had a **wall** bound (`subprocess.run(timeout=1200)`), three of them had none,
and `maxHeartbeats` does not meter the thing that spins (`native_decide`, kernel
reduction, and `simp`'s congruence recursion — three separate budgets measured
FAILING to fire on the one case ever diagnosed; the numbers are in §12 below and
in `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §1).

| what | bound | why that size |
|---|---|---|
| one generated proof | `PROOF_WALL_S` / `PROOF_CPU_S` = 1500 s | 5x the slowest legitimate proof measured (`formal/examples/udivmod.mojo`, 297.8 s wall / 219.2 s CPU) |
| one `lib/*.olean` build or census | `LIBRARY_WALL_S` / `LIBRARY_CPU_S` = 1800 s | ~16x the slowest module build (`ProofLib`, 112.0 s / 83.1 s) |
| memory | `-M 6144` (proof), `-M 12288` (library) | 2x the measured peak of the largest of each: 3.00 GB and 7.82 GB. **Not** the project's 4 GB line: with `-M 4096` the `ProofLib` build fails outright ("(kernel) excessive memory consumption detected"), so that ceiling is a red suite, not a policy. The over-4 GB fact is `prooflib`'s `memwhy` |
| threads | `-j 4` | one file is elaborated sequentially; the threads only decide how fast a runaway burns the machine |

**The escape hatch is the library build and nothing else**
(`FORMAL_LEAN_LIBRARY_WALL_S`, `FORMAL_LEAN_LIBRARY_CPU_S`). A proof bound the
environment can lift is not a bound: the thing that needs lifting during a
runaway is exactly the thing somebody would lift it for.

**A breach is a verdict of its own.** `LeanRun.exceeded` says which bound was
broken, `proof_census` refuses to publish it to the verdict cache (a bound is a
fact about this machine at that moment, and a cached timeout is a permanent red),
and the hole census for a killed elaboration is `None` — UNMEASURED — rather than
`0`. Re-measure any of the numbers above with `FORMAL_LEAN_TRACE=1`, which makes
the launcher print wall/CPU/peak for every run it makes.

**What was switched off, and what switched it back on.** From `3b9bb56e` to
`7d0ac990` the eight gate tests that typecheck generated Lean — `formal`,
`formal-call-proofgen`, `formal-dylib`, `formal-imports`, `formal-sweep`,
`formal-x86`, `formal-x86-endtoend`, `formal-x86-model` — were `disabled=` in
`tools/suite.py` against
`bugs/FORMAL_gate_lean_proof_checks_have_no_time_bound.md`, which said plainly
that `formal7-lean-bound` owned the fix and that the doc was the switch: deleting
it re-enabled the tests, and `tools/suite.py` refused to load the registry while
a disabled test's doc was gone.

Both halves are now in, and the doc is deleted:

1. the launcher, above — `formal/lean.py::run_lean`, one bounded path for every
   Lean run in the tree, sized from the measured slowest legitimate proof;
2. the looping obligation, which was the per-export dylib contract in
   `formal/arm64_proof_gen.py::_dylib_contract_proof`. It emitted the runner's
   own pc bump as a **fourteen-fold nest** of `if <pc of the whole composed
   state> = <pc of the whole composed state> then .. else ..`, and `bv_decide`'s
   internal normalisation of that nest is what does not terminate — a case split
   per level, in a `simp` the emitted file has no way to configure, with
   `maxHeartbeats`, `maxSteps` and `maxRecDepth` all measured failing to fire.

   The emitter already knows statically which steps move the pc — `_step_rhs`
   writes the `pc` field exactly when the instruction does — so it emits the
   `if` **resolved** for every one of them, which is the same function, because
   `(st_i s).pc = s.pc` holds by `rfl` for a step whose effect is a record
   update on `sp`. One `if` survives, at the closing `ret`, where `BlockCert`
   quantifies over every state at the entry and the answer is genuinely
   data-dependent; it never reaches `bv_decide` (`arm64_reg_pc` projects a
   register read through both branches) and is decided for the start state by
   `ret_ne`. Measured on the generated proof of `def triple(n): return n * 3`:
   **9.0 s wall / 14.4 s CPU / 1.63 GB peak, rc 0, 0 holes**, against "did not
   finish" (177.1 s CPU in 79.9 s wall before `RLIMIT_CPU` fired; and 79.7 s
   wall / 296 s CPU even with `bv_decide` replaced by `sorry`, because
   `noEarly`'s fifteen `simp only [S15…, st0…]` blocks were a second cost
   centre — they are now one `omega` per step off a per-step `pc` lemma).

   **What that fix was NOT.** The contract had never been checked, and checking
   it found that it was wrong: `st_i` composed *itself* while `S_{i+1}` feeds it
   the running state, so every step ran once per earlier step again and the
   composed effect of `triple` was `n * 243` where the machine computes `n * 3`
   — a `sorry` over a false claim, which is what §`OPUS-9` below is about. Also
   wrong and also never elaborated: `body.step` was one step short of the block
   it certifies, the `BlockCert` was an `instance` of a `structure … : Prop`
   that is not a class, `runsTo0` was used but never emitted, and `noEarly`
   split its `u` with `interval_cases`, a Mathlib tactic this toolchain does not
   have. `test_formal_dylib.py`'s `a wrong spec is rejected, not believed` is
   what keeps any of that from coming back: a proof that merely elaborates says
   nothing, and `n * 243` elaborated.

The per-unit costs behind the bound, all on an idle box with
`FORMAL_LEAN_TRACE=1`:

* `prooflib` — 112 s wall, 7.82 GB peak on a cold CAS, and **0.3 s** on a warm
  one (five CAS hits).
* one generated proof — 8.6 s (`const2`) … 297.8 s (`udivmod`), 1.5–3.0 GB peak;
  eleven of the 45 `formal/examples/*.mojo` measured, the largest by SIZE are not
  the slowest (`wide_recv` is 703 KB and 93.4 s; `udivmod` is 437 KB and
  297.8 s), so size is not a usable proxy.
* `formal-x86-endtoend` and `formal-x86-model` — **still not measured**, and
  named as such rather than left to be discovered: their Lean runs are
  `formal/x86_64_endtoend_test.py`'s and
  `formal/x86_64_model_coverage_test.py`'s, bounded at `PROOF_WALL_S`/3600 s.
  One `make gate` replaces that sentence with a number, the same way it replaces
  `prooflib`'s `module` class.
