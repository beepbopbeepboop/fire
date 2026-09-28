# FORMAL-PARALLEL: running the FORMAL.md programme as 5 concurrent agents

**Read this before you touch anything.** It is the coordination contract for
`FORMAL.md`. The programme — the thesis, the phases, the measured state — is in
`FORMAL.md` and is not restated here. This document is about how five agents work
on it at once without destroying each other's work, and about who owns what.

**Scope of this round: the EASY half only.** Phases 0, 1 and 2 of `FORMAL.md`,
plus the measurement work. **Phase 3 onward — the Lean call/return semantics and
everything downstream of it — is deliberately NOT in this round and no agent
should start it.** §6 says why, and records where that work stands so it is
planned properly later rather than absorbed sideways into a codegen ticket.

**The integrator is whoever merges.** `FORMAL.md` and `tools/suite.py` are
integrator-owned. No agent edits either. If you need a change in one of them,
file an INTERFACE REQUEST (§4) rather than making it.

---

## 0. The five rules that matter most

1. **Nobody runs a gate.** Not `make check`, not `make gate`, not `make
   bootstrap`, not `make native`, and **not** `tools/suite.py` at all — not even
   `tools/suite.py <one-test>`, because it writes `build/suite.log`, which the
   integrator needs intact. Run your own test files directly with `python3`.
2. **File ownership is the partition, not task dependency.** Your write set is
   listed and it is exclusive. If you need a file another agent owns, you do not
   touch it — you file an INTERFACE REQUEST. One writer per file, always.
3. **`GMOJO_HOME` is per-agent, always.** Every command, every time. One
   environment variable, and it removes every cache-contention, torn-cache and
   dylib-overwrite question at a stroke. See §3.
4. **Never `git checkout` / `git restore` a path.** It destroys uncommitted work
   with no recovery, and it already destroyed ~10 hours once in this project. If
   you want a file back, ask.
5. **Take the 80/20 and leave a note.** This round is the easy half *on purpose*.
   Where an item turns out to be a Stage-5-scale problem, **stop and write it
   down** — a bug doc in `bugs/`, or an INTERFACE REQUEST — rather than grinding.
   A precise "this costs weeks and here is why" is a deliverable here; a
   half-finished attempt is not. `bugs/FORMAL_known_limits.md` already has a
   "what would close it, and what it costs" table for the expensive residue:
   use it rather than re-deriving, and extend it when you find something new.

---

## 1. The five agents

Partitioned so that no two agents share a writable file. The label is how we talk
about work; put it in commit subjects and in INTERFACE REQUESTs.

| agent | theme | exclusive write set |
|---|---|---|
| **[1]** | gimple build path: land the optional runtime units, fix the `mojoc` regression | `build_config.py`, `driver.py`, `fire.py` · **new** `test_sqlite3_runtime.py` |
| **[2]** | the runtime dylib both backends consume: per-arch builds, export/import ABI | `build_stdlib_dylib.py`, `cas.py` · **new** `test_runtime_dylib.py` |
| **[3]** | formal codegen: the `mojo_*` refusal shaped by ABI, and the cheap refusal families | `formal/model.py`, `formal/arm64_codegen.py`, `formal/x86_64_codegen.py`, `reflect.py`, `formal/types.py` |
| **[4]** | formal link + import resolution: the provider registry, the executable-path bind audit, relative imports | `formal/imports.py`, `formal/build.py`, `formal/macho_linker.py`, `formal/macho.py`, `formal/elf.py` |
| **[5]** | the instruments: what we are allowed to believe, and what to do next | `tools/formal_sweep.py`, `formal/lean.py` · **new** `test_formal_sweep_truth.py` |

Everything not listed above belongs to somebody. If it seems to belong to nobody,
it belongs to whoever owns the nearest file, or it is an INTERFACE REQUEST.

**Deliberately unowned this round:** `lib/ProofLib.lean`, `lib/Refine.lean`,
`lib/X86.lean`, `formal/arm64_proof_gen.py`, `formal/x86_64_proof_gen.py`, and
`formal/arm64.py`. That is the deferred proof work (§6), and it is unowned on
purpose rather than accidentally. **Do not start it**, and do not "just fix the
message" in one of them — if something there blocks you, that is an INTERFACE
REQUEST to the integrator, because the next round wants to own those files
cleanly rather than inherit a half-change.

---

### [1] — gimple build path: land phase 0

**Why first in the list:** it holds the only known regression in the programme,
and it is the one item where a real user-visible thing is currently broken.

**The defect.** `runtime/fire_sqlite3.c` has **no build rule at all**, while its
header is `#include`d unconditionally into every generated translation unit
(`mojo/backend_gimple/module_gen.py:6788`) and all 22 of its signatures sit in
`gimple_codegen.py`'s `_KNOWN_SIGS`. So the generated C sees a prototype and
compiles clean, and the failure is at link:

```
$ python3 fire.py build -o sq test_sqlite3.mojo
Linking failed: Undefined symbols for architecture arm64:
  "_mojo_sqlite3_close", ... "_mojo_sqlite3_open", ... "_mojo_sqlite3_query"
```

Same for `fire_zlib.c`, `fire_ssl.c`, `fire_ncurses.c`. Nothing noticed: no
suite entry built any `test_sqlite3*.mojo`, and no `.mojo` file in the tree calls
any of these namespaces.

**(a) The regression, first.** A working version of this was written and reverted
because it broke the self-hosted compiler. `bugs/CODEGEN_optional_runtime_units_not_linked.md`
has the full record — **read it before you start**, it saves you the four
hypotheses already ruled out. `make mojoc` passes on a clean tree, so this is
yours:

```
python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc
rg -n "build_config_find_gcc" fire.ci
```

`fire.ci` is the only trustworthy place the answer is: the `#line` mapping is
imprecise enough that the "reflect.py:814" in the error is past the end of the
file it names. **First hypothesis worth trying, because it is cheapest:**
`OPTIONAL_RUNTIME_UNITS` is the only module-level dict-literal-containing-lists
newly introduced into a module the self-host closure compiles, and the
corruption may leak into the next function's forward declaration. Flat tuples
cost nothing. Try that before anything cleverer.

**(b) Then the registry**, in `build_config.py`: one entry per optional unit
(source, header, link libraries), with the `mojo_<unit>_` namespace **derived
from the header's own export list** — never hand-copied, because a hand-kept list
is the rot this removes. Plus, in **both** link pipelines, the probe `fire.py`
and `driver.py` already apply three times each for the generator `.cpp`,
`fire_async_runtime.cpp` and the coroutine runtime: *does the generated C
reference this namespace?*

**The trap that made a first attempt look like a no-op:** `fire.py build` uses
`driver.compile_program` and only falls back to `build_executable`. Patching one
changes nothing observable. Both need it.

`fire_python.c` stays **out** of the registry deliberately: its whole surface is
`#if USE_PYTHON 0` stubs, so linking it trades a loud link error for a silent
NULL from every `mojo_python_*` call. Its header is not `#include`d either, so
the failure stays loud. Do not "fix" that.

**Done when** `python3 test_sqlite3_runtime.py` is green and every
`test_sqlite3*.mojo` builds, links **and runs** — `test_sqlite3.mojo` printing
`rows: 1 hello 2 world` — a program that never mentions sqlite does not link
libsqlite3, and `python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc` succeeds.

---

### [2] — the runtime dylib, per-arch

**Why separate from [1]:** different file, different failure mode, and it is the
artifact the formal path will eventually consume. [1] builds *programs*; you
build *the library both backends link against*.

**No build rule in the tree has an `-arch` flag.** Everything is host-only, while
the sweep runs both architectures (`tools/formal_sweep.py --arch`), so both
`libmojostdlib.arm64.dylib` and `libmojostdlib.x86_64.dylib` are needed and
neither can overwrite the other. `runtime_dylib()`
(`build_stdlib_dylib.py:697`) already produces the right shape — a `-dynamiclib`
exporting the `mojo_*` namespace with an `@rpath` install name — and it is used
today only by the gimple path.

Your scope:

1. **Per-arch builds**, with the arch in the CAS key *and* in the output name.
   An arch that is not part of the artifact's identity is a cache key that is not
   the thing being cached, and the failure is a program linked against the wrong
   architecture's library — which dyld refuses at load, not at build.
2. **The export rule.** `_export_entries` and `reflect.collect_exports` decide
   what reaches a dylib, and the rule has a known hole recorded in
   `bugs/FORMAL_known_limits.md` §1.1: the `_CLIB_SYMS` exclusion is right for a
   *call* (the symbol is reachable via `dlsym`) and wrong for a *definition*.
   `std/sys/terminate.mojo` **defines** `exit`; if that module also exported one
   other symbol, an importer's `exit()` would bind libSystem's, silently, with no
   diagnostic. Decide it, or write down precisely why not — but do not leave it
   unexamined. `doc/ABI.md`'s public-symbol rule is the authority.
3. **The dead declarations.** `fire_runtime.h` declares `mojo_obj_enter`,
   `mojo_obj_exit`, `int___enter__`, `int___exit__`, `MojoList__write_to` and
   **none of them is defined anywhere**. `build_stdlib_dylib.py:590` already
   knows about one. Either define them or stop declaring them; a declaration with
   no definition is a link failure waiting for a caller.

**Done when:** both arch dylibs build, neither can clobber the other, the
reflection table names every symbol the dylib actually defines, and item 2 is
either fixed or written up as a decision with its trade-off stated.
`python3 test_runtime_dylib.py`. Do not run `make stdlib-dylib` — the integrator
gates that.

---

### [3] — formal codegen: the refusal, and the cheap families

**The single highest-value item on this list, and it is not proof work.** The
formal backend refuses the entire gimple C runtime by *name*:

`is_gimple_runtime_builtin` (`formal/model.py:4151`) is `startswith("mojo_")`
(`GIMPLE_RUNTIME_PREFIX`, `:4136`), raised at
`formal/arm64_codegen.py:4936-4937` and `formal/x86_64_codegen.py:4563-4564`. The
refusal *text* is already right about why it is currently right
(`gimple_runtime_refusal`, `:4161`) and wrong only in being prefix-based.

**Replace it with:** callable **iff** every parameter type *and* the return type
in `fire_runtime.h` are word-shaped (`void`, `int`, `int64_t`, `double`,
`char *`, `void *`) **and** the symbol is on the link line. One table, generated
from the header by `reflect.collect_runtime_exports_h` — never hand-kept. This
**generalises** the `GIMPLE_LIST_PREFIX` special case that already exists
(`formal/model.py:4148`); it is not a new idea.

**The trap, stated so you do not fall in it.** Filtering by *return* type alone
gives the wrong answer. `mojo_list_get_int(MojoList *, int64_t) -> int64_t`
returns a word and is **not** callable — the box is in the *parameter*. The
formal model's list is a frame blob whose first word is its count
(`formal/model.py:49-61`, constants at `:61-64`); the runtime's `MojoList` is
`{data, len, cap}` on the heap (`runtime/fire_runtime.h:257-261`). Reading offset
0 of one as the other is a plausible-looking wrong number, not a crash.

**What it buys, measured:** of 455 entry points, 352 return one 64-bit word and
101 return a heap box. For sqlite, **20 of 22** `mojo_sqlite3_*` routines are
pure word-in/word-out; the only two that are not are `mojo_sqlite3_query` and
`_query_dict`. **INTERFACE REQUEST to [1]** for the "is it on the link line"
half — you can build and test the whole table without it, so start there.

**Then, if you have room: the cheap refusal families.**
`bugs/FORMAL_known_limits.md` §3 lists the small shapes — 8 files, 6 causes —
which are the tractable end of the residue, as distinct from §1 (30 files, needs
Stage 5 monomorphization: **weeks, do not start it**) and §2 (46 files of MLIR
templates: **a permanent limit on this path, not work**). The tractable ones
include `unsupported expression EllipsisLiteral` and the two refusal *wordings*
that assert more than the backend checked. Prefer fixing a wrong message over
adding a capability: a refusal that says something false about a file is worse
than no refusal, because it sends the next reader looking for a construct that is
not there. Also worth a look: the arm64/x86-64 **refusal drift** in that same
table, where one construct gets different verdicts on the two architectures.

**Done when:** the word-only surface is callable from formal; the box surface is
still refused, and the refusal names the *type* mismatch rather than a prefix;
both architectures word it identically; and §3's families are either fixed or
recorded with a cost. Verify `python3 test_formal_run.py` and
`python3 test_formal_imports.py` **on both backends** — the two share
`formal/model.py` deliberately, so a wording difference is a real defect.

---

### [4] — formal link and import resolution

**The 19-name lie.** `_is_libsystem` (`formal/build.py:3591`) is a hardcoded
literal set with one caller (`:4329`), and it is the *entire* notion of "a symbol
provided by a linked native runtime". It is a guess at names, not a check of
anything, and the audit that uses it — "the library would bind N symbol(s) that
nothing provides", `:4309-4337` — runs **only on the dylib path**. The
executable path (`build --formal`, which is what the test suites drive) emits
`external_syms` with no such audit at all.

1. **Replace the 19 names with the linked library's real export table.** The
   scanner already exists: `reflect.collect_runtime_exports_h`
   (`reflect.py:566`), which [1] and [3] also use — read it, do not fork it.
   **INTERFACE REQUEST to [1]** for the unit registry so the two agree on what
   "on the link line" means.
2. **Extend the bind audit to the executable path.** A program that binds a
   symbol nothing provides is an image that builds and cannot load, and today the
   path most tests take has no check for it.
3. **The relative-import bug.** `formal/imports.py`'s `_candidates` does
   `rel = module_name.replace(".", os.sep)`, so `".."` becomes `"/"` and the real
   parent is never tried — the leaf fallback then finds the *importer's own*
   `__init__.mojo`. Recorded in `bugs/FORMAL_known_limits.md` §1.3 with a
   worked example. It inflates the sweep's unresolved-import class and puts one
   file in the wrong family. The leaf fallback is load-bearing for
   `import formal.types` inside `formal/`, so this needs a real fix — resolve
   `.`/`..` against the importing file's directory, parent before leaf — not a
   special case. **This is a well-scoped half-day and it is pure win.**
4. **The `HOST_MODULES` split** — see [5] item (c); you own the file, they file
   the request. Two tiers with a stated reason each: *modelled* (a Mojo-side
   implementation is possible in principle — `os`, `sys`, `math`, `struct`,
   `time`, `json`, `re`) and *unreachable* (needs a host process or an embedded
   interpreter — `subprocess`, `ctypes`, `asyncio`, `threading`, `socket`).
   The point is that today's single list makes the sweep assert something false
   about the first group. Do **not** change what the build accepts; this is a
   classification change only.

**Done when:** a formal image's every bound symbol is accounted for by a real
export table on **both** paths; `..` resolves to the real parent; the
`HOST_MODULES` split is in with per-entry reasons; and
`python3 tools/formal_sweep.py --no-stdlib` shows a *smaller* unresolved-import
class. Verify with `python3 test_formal_imports.py` and `test_formal_dylib.py`.

---

### [5] — the instruments

**Nobody can honestly claim progress without this.** An admitted proof and a
report that cannot see the admission are the same failure in two places — and
this agent is also the one who tells the programme what to plan next, including
the proof half this round is deferring.

**(a) The census is computed and thrown away.** `check_proof_cached` returns
`n_sorries`; `proof_sorries` has **exactly two references tree-wide**, both
writes, at `formal/build.py:931` and `:4386` — **zero readers**. `fire.py` prints
only `proof_cached`. A proof with a thousand sorries is a `PASS`. Make it read.
*INTERFACE REQUEST to [1] for the one-line `print` in `fire.py`; do the rest here.*

**(b) Vacuity is invisible to the census.** `extern_<sym>_step : True := by
trivial` counts as **0 sorries** while being as uninformative as one — and
`test_formal_dylib.py:388` greps only the *generated* file for `sorry`, while the
three `sorry`s that decide its verdict live in `lib/` and are consumed from
pre-built `.olean`s, so Lean never emits a "declaration uses sorry" warning for
them. Make both visible. **Report, do not gate**: this changes what the output
says, not what passes, so it cannot break another agent's work in flight.

**(c) The sweep's biggest bucket rests on a claim we know is false.**
`CLASS_HOST`'s own blurb says a host import is *"outside this backend's reach,
and not fixable"* — true of `subprocess`/`ctypes`/`tempfile`/`asyncio`, **false**
of `os`, `sys`, `math`, `struct`, `time`, `json`, `re`. The split itself is
[4]'s file; the sweep side is yours. Add a summary line printing the in-reach
count, and a refusal family for "a system-module call with no Mojo source on any
path" so it is never absorbed into `codegen`, which counts as a finding.
**Do not** add the in-reach ones to `ANSWERABLE` — they are unanswerable *today*,
and moving them would flatter the headline. The point is to size the work, not to
improve the number.

**(d) Rank the residue, and say what to plan next.** Run the four sweeps
(`--arch arm64`/`x86_64` × default/`--no-stdlib`) and turn the result into a
ranked backlog: for each remaining family, the file count, the distinct terminal
causes, whether the refusal is *true*, and **what it would cost to close**.
`bugs/FORMAL_known_limits.md` has the table shape; extend it rather than starting
a new list. The most useful thing you can produce is a short, honest answer to
"after this round, what is the biggest remaining lever" — and if the answer is
Stage 5 monomorphization, say so with the numbers, because that is the proof-adjacent
work this round deferred and it needs a plan rather than a side quest.

**Done when:** a sorried proof and a vacuous one are distinguishable in the
output; the sweep's host class no longer asserts something false; and the ranked
backlog exists with costs. Verify `python3 tools/formal_sweep.py --no-stdlib`
and `python3 test_formal.py` — **not** `tools/suite.py`.

---

## 2. The easy/hard line, so nobody grinds

This round is the easy half *on purpose*. Concretely:

| take it | leave it, and write it down |
|---|---|
| anything that makes a refusal **true** rather than more capable | Stage 5 monomorphization — `FORMAL.md` phase 7, scoped at "weeks, not an afternoon" in `FORMAL_known_limits.md` §1.2 |
| anything that makes a program **build, link and run** | MLIR attribute templates — 46 files, a **permanent** limit on this path, not work (`FORMAL_known_limits.md` §2) |
| anything measured in **one sitting** | anything needing a heap/allocator on the formal path — that is the slab allocator, `FORMAL.md` phase 6, and it is gated behind the deferred proof work |
| any import/link/dylib plumbing | a `mojo_*` call that returns a heap box — needs the ABI decision, not a codegen patch |
| fixing a **wrong message** | adding a **capability** whose value model does not exist yet |

If you hit the wall, the deliverable is a bug doc with a repro and a cost, or an
INTERFACE REQUEST. `bugs/FORMAL_known_limits.md` is the model: it records the
measured count, whether the refusal is *true*, and what closing it would take. A
precise "this costs weeks, here is why" is a **result** in this round.

---

## 3. Isolation, including in a shared directory

You will not all have your own checkout. Here is what is shared, what is safe,
and what is not.

### Set this on EVERY command, no exceptions

```bash
export GMOJO_HOME="$HOME/.gmojo-agent-N"     # N = your agent number
```

`cas.py:47` reads it; `CAS_DIR` is `$GMOJO_HOME/cas` (`cas.py:48`). This one
variable removes every question about concurrent builds, cache stampedes, torn
CAS entries, and `formal/imports`' per-arch dylib directory — which two agents
sharing a `GMOJO_HOME` would otherwise write into simultaneously. It costs
nothing and there is no excuse.

### The shared-writable-path audit

A build writes into the CWD. The rule that makes sharing safe:

> **The only repo-root collision that matters is building the same basename.**
> `fire.py:563` writes `<basename>.ci`; the Makefile's `mojoc` target writes
> `./mojoc`. Every other artifact is named after *your own test file*
> (`test_foo.ci`, `test_foo.o`, `test_foo.aout`, `test_foo_proof.lean`), so two
> agents running different tests do not collide.

| shared path | written by | who may write it |
|---|---|---|
| `fire.ci`, and `*.o` for `fire.py` | any `fire.py build fire.py` | **[1] only** |
| `mojoc` | `make mojoc` | **[1] only** |
| `lib/*.olean`, `*.srcsha256`, `*.buildlock` | `ensure_library` | see below |
| `build/suite.log` | `tools/suite.py` | **nobody** |
| `stage1/`, `stage2/`, `stage3/` | bootstrap | nobody — nobody runs bootstrap |
| `$GMOJO_HOME/cas` | everything | you, alone, in your own |
| `test_<yourtest>.*` | your test | you |

**If you need to build `fire.py` or `mojoc` and you are not [1], you are in the
wrong place** — file an INTERFACE REQUEST. Nobody else needs to: [3] and [4] work
on sources and run the formal backends, which do not write `fire.ci`.

### The `.olean` files — safe, but read this

`lib/ProofLib.olean` is 27 MB and ~90 s to build. `ensure_library`
(`formal/lean.py:150`) already handles concurrency correctly: an exclusive
`flock` per `.olean` (`:114-145`), the currency check **repeated inside the
lock**, and a private-temp + `os.replace` write so a partial file can never
appear where a valid one belongs. A shared `lib/` is therefore **safe from
corruption** — worst case you queue.

Nobody edits a `.lean` file this round, so in practice you will only be reading
these. But: do **not** `rm` anyone's `.olean`, `.srcsha256` or `.buildlock`, and
do not `rm -rf lib/` — it is someone's 90-second build. If you want total
isolation, copy `lib/*.lean` into your own directory and pass it as `repo_root`;
`formal/lean.py:305` derives `lib_dir` from that parameter, so it is genuinely
per-caller.

### Other things not to do in a shared tree

- Leave `build/`, `__pycache__` and `*.o` alone. They are gitignored but
  **shared**, and a stale one can be served from a cache you thought was yours.
  `GMOJO_HOME` per agent is the fix; do not go `rm -rf`-ing `build/`.
- Do not rename, reformat or "tidy" a file outside your write set.
- Do not edit `FORMAL.md` or `tools/suite.py`.
- Do not add an `expect=` marker to make something green. Prefer fixing; a marker
  is a silenced test and `CLAUDE.md` is explicit about it.

---

## 4. INTERFACE REQUEST

When you need something in a file you do not own, do not touch the file:

```
INTERFACE REQUEST  from=[N]  to=[M]  file=<one path>
WHAT:   the exact change, as a diff if you have written it somewhere legal
WHY:    one line
BLOCKS: what of yours cannot land without it
```

Writing the diff in a scratch file and handing it over is encouraged — the
integrator applies it, so the work is not lost, and there is exactly one writer
per file at every moment. Keep working on everything that does not depend on it;
three of the five requests in this round are non-blocking by design.

---

## 5. Merging

1. **[1]** first — it holds the only known regression, and [4] and [5] both have
   requests into it.
2. **[2]** — independent of everything; merges whenever it is ready.
3. **[3]** — independent of [2]; its link-line half waits on [1], its table does not.
4. **[4]** — after [1] for the registry, but the relative-import fix and the
   `HOST_MODULES` split merge on their own.
5. **[5]** last. It makes the instruments stricter, so merging it after the rest
   means its stricter reporting is applied to finished work rather than firing
   halfway through everyone else's.

The integrator, and only the integrator: applies held requests, registers all
new test files in `tools/suite.py`, resolves any overlap that turns out to be
real, updates `FORMAL.md` with what actually landed, deletes
`bugs/CODEGEN_optional_runtime_units_not_linked.md` **iff** [1] fixed it (a doc
for a fixed bug is a doc that lies), and then **runs the gate once**.

**An INTERFACE REQUEST file is deleted in the merge that answers it**, for the
same reason: a file whose seven sections are all resolved is indistinguishable
from an open one to whoever opens the queue next, and the sections that read
"OPEN, to=[4], file=formal/build.py:629" are the actively misleading part — the
line number no longer means what it meant. Each request's *content* is expected
to have landed as a commit, a test, or a row in `FORMAL.md` §7; none of it lives
only in the request file. To restate the rule the bug docs already follow: if
the answer is in the tree, the request is not.

## 6. What this round deliberately does not do, and where it stands

**Deferred: `FORMAL.md` phases 3–6.** The call/return semantics in the Lean
machine model, and everything downstream (per-export contracts, the Mojo runtime,
the proved slab allocator). Not assigned to anyone this round, and an agent who
finds themselves tempted is looking at the wrong item.

It is deferred because it is not a five-way parallel split — it is one
load-bearing modelling problem with a fan-out, and it wants its own plan. What
the next round needs to start from, so it is not re-derived:

- The root cause is mechanical. `lib/ProofLib.lean:1548-1549` gives `BL` a bare
  `x30`/pc transfer with **no callee**, and a dylib or libc branch target is a
  `__TEXT,__stubs` address *outside the image*, so `arm64_go_exit` returns `none`
  and the model halts. That single gap is why every symptom below exists.
- At an extern call site today: the step theorem is
  `extern_<sym>_step : True := by trivial`
  (`formal/arm64_proof_gen.py:6910`); the post-call state is **fabricated** as
  `{pre with pc := bl+4}` (`:6923`), so the callee's effect on registers and
  memory is discarded; `DylibExport.Semantics` is `∀ o, o ∈ [] → True`
  (`lib/ProofLib.lean:4617`) against a hardcoded empty observable list
  (`formal/arm64_proof_gen.py:8356`), vacuously true of any export in any image;
  and `dylib_export_contract_stub` is `sorry` (`lib/Refine.lean:660`) invoked
  with `obs := fun n => n`, i.e. asserting every export is the identity.
- x86-64 is cruder: no run tests at all for a program with externs
  (`formal/x86_64_proof_gen.py:460`), and both its end-to-end theorem (`:690`)
  and its AST⟷bytes theorem `_compile_correct` (`:239`) are unconditional
  `sorry`. Its `call_rel32` is **already modelled** at `lib/X86.lean:720` and
  simply not wired into the generator's `_FORMS`/`_SUCCS`/`_resolve` trio
  (`bugs/OPEN_WORK.md` A1) — a genuinely independent start, and the natural
  first item of the next plan.
- `formal/arm64_proof_gen.py` carries **byte-identical duplicated blocks**:
  `generate_arm64_proof` at `:6034` and `:7222`, `_gen_extern_test` at `:5661`
  and `:6849`, `_find_extern_call` at `:5556` and `:6744`. Python binds the
  second, so `:6849` is the live one. De-duplicate before the semantic work, not
  during it.
- The full trust inventory is `FORMAL.md` §7, including the two holes in the
  mechanism that checks it. [5] is fixing the *reporting* this round; the
  *assumptions* stay until the proof work is planned.

**One thing this round does deliver for the next:** [1] and [2] make a
per-arch, real-export-table runtime dylib exist, and [3] makes the word-shaped
part of that ABI callable from the formal backend. So the deferred phase 4 — "a
runtime object with a proof attached" — will have something real to attach a
proof to, which is the precondition it needs and did not have.

---

## 7. What "done" means for you, individually

Not the gate. Your own tests, run directly, plus one number each.

| agent | verify with | the number that proves it |
|---|---|---|
| [1] | `python3 test_sqlite3_runtime.py`; `python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc` | sqlite programs build, link **and run**; `mojoc` builds |
| [2] | `python3 test_runtime_dylib.py` | both arch dylibs build, neither clobbers the other, the reflection table names only real definitions |
| [3] | `python3 test_formal_run.py`; `python3 test_formal_imports.py` — **both backends** | word-only surface callable on both arches; box surface refused for the *type* reason, identically worded |
| [4] | `python3 test_formal_imports.py`; `python3 tools/formal_sweep.py --no-stdlib` | every bound symbol accounted for on both paths; `..` resolves to the real parent; unresolved-import class shrinks |
| [5] | `python3 tools/formal_sweep.py --no-stdlib`; `python3 test_formal.py` | a sorried proof and a vacuous one are distinguishable; the host class no longer asserts something false; a ranked backlog with costs exists |

For any change you believe is **behaviour-preserving**, the standard is higher
than "tests pass": **byte-identical generated C** on a large succeeding case,
compared before and after. `cmp` the artifacts. Anything less is a change you have
not finished verifying.
