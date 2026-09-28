# FORMAL-PARALLEL: running the FORMAL.md programme as 5 concurrent agents

**Read this before you touch anything.** It is the coordination contract for
`FORMAL.md`. The programme itself — the thesis, the phases, the measured current
state — is in `FORMAL.md` and is not restated here. This document is only about
how five agents work on it at once without destroying each other's work, and
about what each one is responsible for.

**The integrator is whoever merges.** `FORMAL.md` and `tools/suite.py` are
integrator-owned. No agent edits either. If you need a change in one of them,
write an INTERFACE REQUEST (below) instead of making it.

---

## 0. The five rules that matter most

1. **Nobody runs a gate.** Not `make check`, not `make gate`, not
   `tools/suite.py`, not `make bootstrap`, not `make native`. Not even
   `tools/suite.py <one-test>` — it writes `build/suite.log`, which the
   integrator needs intact. Run your own test files directly with `python3`.
2. **File ownership is the partition, not task dependency.** Your write set is
   listed and it is exclusive. If you need a file another agent owns, you do
   not touch it — you file an INTERFACE REQUEST. This is the whole mechanism.
3. **`GMOJO_HOME` is per-agent, always.** Every command you run gets your own
   CAS. This is one env var and it removes every cache-contention and
   torn-cache question at a stroke. See §2.
4. **Never `git checkout` / `git restore` a path.** It is how ~10 hours of work
   was destroyed once in this project. If you want a file back, ask.
5. **Commit on your branch as you go**, with a message that states what you
   measured. Small commits. Your branch is your only undo.

---

## 1. Agents

Five agents, labeled `[1]`–`[5]`. The label is how we talk about work; put it in
your commit subjects and in any INTERFACE REQUEST.

### [1] — build & link plumbing: land phase 0, then phase 1

**Write set (exclusive to you):**
`build_config.py`, `driver.py`, `fire.py`, `build_stdlib_dylib.py`, `cas.py`,
`formal/imports.py`, `formal/build.py` · **new:** `test_sqlite3_runtime.py`,
`test_runtime_dylib.py`

**Why you go first in the list:** you hold the only known regression in the
programme, and phases 2's "is the symbol on the link line" question is unanswerable
until your provider registry exists.

**(a) Land the optional-runtime-unit registry.** This was written and then
reverted; the diagnosis is in `bugs/CODEGEN_optional_runtime_units_not_linked.md`
and you should read that file first — it has the measured baseline, the four
already-ruled-out hypotheses, and the exact command that is the next diagnostic:

```
python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc
rg -n "build_config_find_gcc" fire.ci
```

The blocker is `error: conflicting types for 'build_config_find_gcc'; have
'char *(void)'`, emitted from three sites. `make mojoc` **passes on a clean
tree**, so this is yours. `fire.ci` is the only trustworthy place the answer is:
the `#line` mapping is imprecise enough that the "reflect.py:814" in
that message is past the end of the file it names.

*First hypothesis worth testing, cheapest to try:* `OPTIONAL_RUNTIME_UNITS` is
the only module-level dict-literal-containing-lists newly introduced into a
module the self-host closure compiles, and the corruption may leak into the
next function's forward declaration. Flat tuples instead of nested dicts costs
nothing. Try it before anything cleverer.

**(b) Then the registry itself**, in `build_config.py`: one entry per optional
unit (source, header, link libraries), namespace **derived from the header's own
export list** via `reflect.collect_runtime_exports_h` — never hand-copied. Plus,
in **both** link pipelines, the probe `fire.py` and `driver.py` already apply
three times each for the generator `.cpp`, `fire_async_runtime.cpp` and the
coroutine runtime: *does the generated C reference this namespace?*
`fire.py build` uses `driver.compile_program` and only falls back to
`build_executable`, so **patching one changes nothing observable.** That is how
the first attempt failed to fix anything.
`fire_python.c` stays **out** of the registry on purpose: its surface is
`#if USE_PYTHON 0` stubs, so linking it trades a loud link error for a silent
NULL.

**(c) Per-arch runtime dylibs.** No build rule in the tree has an `-arch` flag;
everything is host-only, and the sweep runs both architectures. `runtime_dylib()`
(`build_stdlib_dylib.py:697`) already produces the right artifact.

**(d) Replace `_is_libsystem` (`formal/build.py:3591`) with a provider registry**
read from the linked library's *actual* export table, and extend the "would bind
N symbol(s) that nothing provides" audit (`:4309-4337`) from the dylib path to
the **executable** path, where it does not run today.

**Done when:** `mojoc` builds; `test_sqlite3.mojo` builds, links and *runs*,
printing `rows: 1 hello 2 world`; a program that never mentions sqlite does not
link libsqlite3; the audit names a header-declared symbol when you feed it a
real `ld` failure. Verify with `python3 test_sqlite3_runtime.py` and
`python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc` — **not** with make.

**Interface requests you are likely to need:** a way for [4]'s table to ask "is
this symbol on the link line" (propose the function signature; [4] writes the
caller); a one-line `print` of `result['proof_sorries']` in `fire.py` for [5].

---

### [2] — arm64 machine model: call/return semantics (phase 3, arm64 half)

**Write set (exclusive to you):**
`lib/ProofLib.lean`, `lib/Refine.lean`, `formal/arm64_proof_gen.py`

**This is the gate for phases 4, 5 and 6.** Nothing downstream is worth building
before it, and it is the only item on the list that makes "the runtime is a
`.o` with a proof with it" true rather than aspirational.

**Today, at an extern call site:**

| what | where | what it actually asserts |
|---|---|---|
| the call step | `formal/arm64_proof_gen.py:6910` | `theorem extern_<sym>_step : True := by trivial` |
| the post-call state | `:6923` | **fabricated** as `{pre with pc := bl+4}` — the callee's effect on registers and memory is discarded |
| `DylibExport.Semantics` | `lib/ProofLib.lean:4617` | `∀ o, o ∈ [] → True`, against a hardcoded empty observable list (`:8356`) — vacuously true of any export in any image |
| `dylib_export_contract_stub` | `lib/Refine.lean:660` | `by sorry`, called with `obs := fun n => n` — claims every export is the identity |

**Root cause:** `lib/ProofLib.lean:1548-1549` gives `BL` a bare `x30`/pc
transfer with no callee, and the branch target is a `__TEXT,__stubs` address
outside the image, so the model halts.

**Do, in this order:**
1. Give `arm64_step`'s `BL` a **call frame, a callee entry, and return-to-`x30`**.
   This is the load-bearing change; the rest is downstream of it.
2. Replace the vacuous extern step theorem with a real obligation.
3. Make `DylibExport.Semantics` **non-vacuous** — real observables, not `[]`.
4. **Prove or delete** `dylib_export_contract_stub`. Deleting is a legitimate
   outcome; leaving it is not.
5. De-duplicate the byte-identical blocks in `arm64_proof_gen.py`:
   `generate_arm64_proof` at `:6034` and `:7222`, `_gen_extern_test` at `:5661`
   and `:6849`, `_find_extern_call` at `:5556` and `:6744`. Python binds the
   second copy, so `:6849` is the live `_gen_extern_test` and every line number
   about it refers to that one. Do this **last** — it is a large textual move and
   it should not be mixed into a semantic change.

**Constraint that matters for you specifically:** edits to `lib/ProofLib.lean`
are read by [3] and [5], because `lib/X86.lean` imports it and the generated
proofs typecheck against its `.olean`. Two rules:
**additive-only** — add new definitions, do not modify or delete existing ones
except where step 4 above explicitly requires it; and **say so** in your commit
subject if you do, so [3] knows to re-run rather than trust a cached `.olean`.

**Done when:** a dylib export has a semantics that is not vacuously true, and a
caller can discharge an obligation against it. Verify with
`python3 test_formal_dylib.py` and `python3 test_formal_run.py` — and read
`test_formal_dylib.py:388` first, because it currently greps only the *generated
file* for `sorry` while the three that decide its verdict live in `lib/` and
cannot be seen. Fixing that check is in scope for you.

---

### [3] — x86-64 machine model: `call_rel32`, and the AST⟷bytes trust boundary

**Write set (exclusive to you):**
`lib/X86.lean`, `formal/x86_64_proof_gen.py`

**Do not touch `formal/x86_64_codegen.py`** — it belongs to [4].

**Independently valuable, which is why this is a separate agent:** your first
item needs nothing from [2]. `x86_step_call_rel32` is **already modelled** at
`lib/X86.lean:720` and is simply not wired into the generator's
`_FORMS`/`_SUCCS`/`_resolve` trio (`bugs/OPEN_WORK.md` A1). It has two
successors and a memory write — the pushed return address must be shown
separated from the callee's frame, and the callee must be in the path tree at
all — so it is real design work, not a lookup. While you are in there: the
gate's "19 no finite tree (4 loop, 15 uncovered form)" split is not
self-consistent, because the emitter's own refusals disagree with the
`_has_loop` predicate (`OPEN_WORK.md` D2). Reconcile it.

**Then:**
2. **x86-64 currently emits NO run tests at all** for any program with externs
   (`formal/x86_64_proof_gen.py:460`) — it gives up with a comment explaining
   that the model has no memory for a `__TEXT,__stubs` trampoline. Once [2] has
   call/return semantics, that cop-out goes. Until then, do the part that does
   not need them.
3. **`_compile_correct` is `sorry`** (`formal/x86_64_proof_gen.py:239`, raising
   at the generated `sorry` around `:264`), and so is the end-to-end theorem
   (`:690`). The x86-64 AST⟷bytes boundary is *trusted* today. That is the
   single largest trust item on x86-64 and it is yours.

**Depends on [2] for:** consuming the new call/return vocabulary if your
`call_rel32` step should mirror it. Do the wiring first; do not block on it.

**Done when:** `x86_step_call_rel32` is reachable from the generator's step
table, and the two `sorry`s at `:239`/`:690` are either proved or recorded as
named, owned gaps. Verify with `python3 test_formal.py --backend x86_64`,
`python3 formal/x86_64_model_test.py` and
`python3 formal/x86_64_model_coverage_test.py`.

---

### [4] — the `mojo_*` refusal, shaped by ABI instead of by prefix (phase 2)

**Write set (exclusive to you):**
`formal/model.py`, `formal/arm64_codegen.py`, `formal/x86_64_codegen.py`,
`reflect.py`

**Do not touch `formal/build.py`** — it belongs to [1].

`is_gimple_runtime_builtin` (`formal/model.py:4151`) refuses any callee whose
name starts with `mojo_` (`GIMPLE_RUNTIME_PREFIX`, `:4136`), raised at
`formal/arm64_codegen.py:4936-4937` and `formal/x86_64_codegen.py:4563-4564`.
The refusal *text* is already correct about why it is currently right
(`gimple_runtime_refusal`, `:4161`) and wrong only in being prefix-based.

**Replace it with:** callable **iff** every parameter type *and* the return type
in `runtime/fire_runtime.h` are word-shaped (`void`, `int`, `int64_t`, `double`,
`char *`, `void *`) **and** the symbol is on the link line. One table, generated
from the header by `reflect.collect_runtime_exports_h`, never hand-kept — a
second hand-kept list is exactly the rot this removes. This **generalises** the
`GIMPLE_LIST_PREFIX` special case that already exists (`formal/model.py:4148`),
it is not a new idea.

**The trap, stated so you do not fall in it:** filtering by *return* type alone
gives the wrong answer. `mojo_list_get_int(MojoList *, int64_t) -> int64_t`
returns a word and is **not** callable — the box is in the *parameter*. The
formal model's list is a frame blob whose first word is its count
(`formal/model.py:49-61`) while the runtime's `MojoList` is
`{data, len, cap}` on the heap (`runtime/fire_runtime.h:257-261`). Reading
offset 0 of one as the other is a plausible-looking wrong number, not a crash.

**Measured scope, so you know what you are buying:** of 455 entry points, 352
return one 64-bit word and 101 return a heap box. For sqlite, **20 of 22**
`mojo_sqlite3_*` routines are pure word-in/word-out; the only two that are not
are `mojo_sqlite3_query` and `_query_dict`.

**Depends on [1] for:** the "on the link line" half. You can build and test the
whole table without it — start there.

**Done when:** the word-only surface is callable from formal; the box surface is
still refused, and the refusal names the *type* mismatch rather than a prefix.
Verify with `python3 test_formal_run.py` and
`python3 test_formal_imports.py`, on **both** architectures — the two backends
share `formal/model.py` deliberately, so a wording difference is a real defect.

---

### [5] — the instruments: what we are allowed to believe

**Write set (exclusive to you):**
`formal/lean.py`, `tools/formal_sweep.py`, `formal/types.py`

**Nobody else can honestly claim progress without this.** A proof that is
admitted, and a report that cannot see the admission, are the same failure in
two places.

**(a) The census is computed and thrown away.** `check_proof_cached` returns
`n_sorries`; `proof_sorries` has **exactly two references tree-wide**, both
writes, at `formal/build.py:931` and `:4386` — **zero readers**. `fire.py`
prints only `proof_cached`. A proof with a thousand sorries is a `PASS`. Make it
read. *(Interface request to [1] for the one-line `print` in `fire.py`; do the
rest here.)*

**(b) Vacuity is invisible to the census.** `extern_<sym>_step : True := by
trivial` counts as **0 sorries** while being as uninformative as one — and
`test_formal_dylib.py:388` greps only the *generated* file, while the three
`sorries` that decide its verdict live in `lib/` and are consumed from pre-built
`.olean`s, so Lean never emits a "declaration uses sorry" warning for them.
Make both visible. [2] is removing three of those sorries; you are making it
impossible for the next three to be invisible.

**(c) The sweep's largest bucket rests on a claim we know is false.**
`CLASS_HOST`'s own blurb says a host import is *"outside this backend's reach,
and not fixable"* — true of `subprocess`/`ctypes`/`tempfile`/`asyncio`, **false**
of `os`, `sys`, `math`, `struct`, `time`, `json`, `re`. Split
`formal/imports.py:50`'s `HOST_MODULES` into modelled vs unreachable, each with
its reason, and have the sweep print the in-reach count. **Do not** add the
in-reach ones to `ANSWERABLE`: they are unanswerable *today*, and moving them
would flatter the headline. This sizes the whole programme's real scope.
Also add a refusal family for "a system-module call with no Mojo source on any
path", so it is never absorbed into `codegen` — which counts as a finding.
*(`formal/imports.py` is [1]'s to edit: file an INTERFACE REQUEST for the
`HOST_MODULES` split; do the sweep side yourself.)*

**(d) `formal/types.py:166` — the formal path is int-only and floats truncate
toward zero on emit.** That is why `math.*` cannot simply be wired to libSystem:
`math.sqrt` is a *semantic* gap, not a lowering one. Either give the model a
real float representation, or make the refusal name this instead of reporting
`math.sqrt` as a missing symbol. Do not stub it — a stub is the
`os.path.normpath` anti-pattern (`mojo/backend_gimple/emit_methods.py:1955-1956`
lowers it to identity on the gimple path, which is known-wrong).

**Done when:** a sorried proof and a vacuous one are distinguishable in the
output; the sweep's host class stops asserting something false; `math.*` has an
honest verdict. Verify by running `tools/formal_sweep.py` **as a script with
your own `GMOJO_HOME`** (`--no-stdlib` for a fast pass) and by
`python3 test_formal.py` — not by `tools/suite.py`.

---

## 2. Isolation, including in a shared directory

You will not all have your own checkout. Here is exactly what is shared, what is
safe, and what is not.

### Set this on EVERY command, no exceptions

```bash
export GMOJO_HOME="$HOME/.gmojo-agent-N"     # N = your agent number
```

`cas.py:47` reads it; `CAS_DIR` is `$GMOJO_HOME/cas` (`cas.py:48`). This one
variable removes every question about concurrent builds, cache stampedes, torn
CAS entries, and `formal/imports`' per-arch dylib directory
(`build_module_dylib` writes into the CAS dir, so two agents otherwise share
`formal-imports/<arch>/` and can overwrite each other's dylibs). It costs
nothing and you have no excuse for skipping it.

### The shared-writable-path audit

A build writes into the CWD. The rule that makes sharing safe:

> **The only repo-root collision that matters is building the same basename.**
> `fire.py:563` writes `<basename>.ci`, and `Makefile`'s `mojoc` target writes
> `./mojoc`. Everything else is named after *your own test file*
> (`test_foo.ci`, `test_foo.o`, `test_foo.aout`, `test_foo_proof.lean`), so two
> agents running different tests do not collide.

Concretely, per agent:

| shared path | written by | who may write it |
|---|---|---|
| `fire.ci`, `*.o` for `fire.py` | any `fire.py build fire.py` | **[1] only** |
| `mojoc` | `make mojoc` | **[1] only** |
| `stage1/`, `stage2/`, `stage3/` | bootstrap | nobody (and nobody runs bootstrap) |
| `lib/*.olean`, `*.srcsha256`, `*.buildlock` | `ensure_library` | see below |
| `build/suite.log` | `tools/suite.py` | **nobody** |
| `$GMOJO_HOME/cas` | everything | you, alone, in your own |
| `test_<yourtest>.*` | your test | you |

**If you need to build `fire.py` or `mojoc` and you are not [1], you are in the
wrong place** — file an INTERFACE REQUEST. [3] does not need to: your work is
`lib/X86.lean` plus a proof generator, neither of which builds a binary.

### The `.olean` files — safe, but read this

`lib/ProofLib.olean` is 27 MB and ~90 s to build. `ensure_library`
(`formal/lean.py:150`) already does the right thing under concurrency: an
exclusive `flock` per `.olean` (`:114-145`), the currency check **repeated
inside the lock**, and a private-temp + `os.replace` write so a partial file can
never appear where a valid one belongs. So a shared `lib/` is **safe from
corruption** — worst case you queue.

The hazard is not corruption, it is **staleness**: if [2] edits
`lib/ProofLib.lean`, every subsequent `ensure_library` rebuilds it, and an agent
who typechecked a minute ago is now reasoning against a different library.

- Do **not** `rm` anyone's `.olean`, `.srcsha256` or `.buildlock`.
- Do not run `rm -rf lib/`. It is someone's 90-second build.
- If [2] lands a `ProofLib.lean` change, [3] and [5] should re-run their own
  tests from scratch rather than trust a cached verdict. [2] will say so in the
  commit subject.
- If you want total isolation, copy `lib/*.lean` into your own directory and
  pass it as `repo_root` — `formal/lean.py:305` derives `lib_dir` from that
  parameter, so it is genuinely per-caller.

### Other things not to do in a shared tree

- Leave `build/`, `__pycache__` and `*.o` alone; they are gitignored but they
  are *shared*, and a stale one can be served to you from a cache you thought
  was yours. `GMOJO_HOME` per agent is the fix; do not go `rm -rf`-ing `build/`.
- **Never** `git checkout -- <path>` or `git restore <path>`. It destroys
  uncommitted work with no recovery, and it already destroyed ~10 hours once in
  this project. If you need a file restored, say so and a human will do it.
- Do not rename, reformat, or "tidy" a file outside your write set.
- Do not edit `FORMAL.md` or `tools/suite.py`. The integrator owns both.
- Do not add an `expect=` marker to make something green. Prefer fixing; a
  marker is a silenced test and `CLAUDE.md` is explicit about it.

---

## 3. INTERFACE REQUEST

When you need something in a file you do not own, do not touch the file. Post
this, and keep working on everything that does not depend on it:

```
INTERFACE REQUEST  from=[N]  to=[M]  file=<one path>
WHAT:   the exact change, as a diff if you have written it somewhere legal
WHY:    one line
BLOCKS: what of yours cannot land without it
```

Writing the diff in a scratch file and handing it over is encouraged — the
integrator applies it, so the work is not lost, and there is exactly one writer
per file at every moment.

---

## 4. Merging

Integration order, and why:

1. **[1]** first. It holds the only known regression, and [4] and [5] both have
   interface requests into it.
2. **[2]** and **[3]** next, in either order — they are disjoint files, but [3]
   should re-run after [2] lands so its `call_rel32` step can mirror the new
   vocabulary. Land [3]'s wiring before [2] and it will not need to.
3. **[4]** after [1] (it wants the link-line half) — but its table is
   independent and can be reviewed earlier.
4. **[5]** last: it makes the instruments stricter, so merging it after the rest
   means its stricter reporting is applied to the finished work rather than
   firing halfway through everyone else's.

The integrator, and only the integrator: applies held interface requests,
registers all new test files in `tools/suite.py`, resolves any pair of edits that
turned out to overlap, updates `FORMAL.md` with what actually landed, deletes
`bugs/CODEGEN_optional_runtime_units_not_linked.md` **iff** [1] fixed it (a doc
for a fixed bug is a doc that lies — see `CLAUDE.md`), and then **runs the gate
once** over everything.

---

## 5. What "done" means for you, individually

Not the gate. Your own tests, run directly, plus one number each.

| agent | verify with | the number that proves it |
|---|---|---|
| [1] | `python3 test_sqlite3_runtime.py`; `python3 fire.py build fire.py -O2 -g0 -o /tmp/mojoc` | sqlite programs build, link **and run**; `mojoc` builds |
| [2] | `python3 test_formal_dylib.py`; `python3 test_formal_run.py` | 0 `sorry` in `lib/` reachable from a dylib proof, and the extern step theorem is not `True` |
| [3] | `python3 test_formal.py --backend x86_64`; `python3 formal/x86_64_model_coverage_test.py` | `call_rel32` in the covered-forms table; the two `sorry`s proved or recorded as named gaps |
| [4] | `python3 test_formal_run.py`; `python3 test_formal_imports.py` | word-only surface callable on **both** arches; box surface refused for the *type* reason, identically worded |
| [5] | `python3 tools/formal_sweep.py --no-stdlib`; `python3 test_formal.py` | a sorried proof and a vacuous one are distinguishable; the sweep's host class no longer asserts something false |

For any change you believe is **behaviour-preserving**, the standard is higher
than "tests pass": **byte-identical generated C** on a large succeeding case,
compared before and after. `cmp` the artifacts. Anything less is a change you
have not finished verifying.

And for everyone: `formal/known limits` and the trust inventory in `FORMAL.md` §7
are the record of what is currently *assumed*. If you remove an assumption, say
which one in your commit subject. If you add one, that is a finding, not a
detail.
