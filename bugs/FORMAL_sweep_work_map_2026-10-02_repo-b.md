# FORMAL_sweep_work_map_2026-10-02_repo-b: the repo's own `g`-`m` files — one CRASH, one wrong refusal, and two of eight files the sweep cannot finish

**Slice:** `sweep:repo-b` = this repository's own top-level `*.py` files whose
names start `g`–`m` — 8 files, 13 692 lines:
`gimple_codegen.py`, `generated_dispatch.py`, `imports.py`, `mlir.py`,
`module_loader.py`, `module_spec_gen.py`, `monomorphize.py`,
`myinterpreter.py`. **arm64** (the slice does not name an architecture, and
arm64 is the default). No stdlib root (`--no-stdlib`).

**Status: TWO top causes FIXED and verified; SEVEN of the eight files
classified; one (`gimple_codegen.py`) is unmeasured because the sweep cannot
finish it in 90 minutes (§4).** The fixes are
`7b1f2643` (a backend CRASH, `backend-crash` 1 → 0) and `91db24b9`
(`codegen/dependency` 2 → 0, and `re.mojo` from "does not build" to 994/1008).
The first deleted `bugs/FORMAL_frame_receivers_is_handed_the_method_name_table.md`;
the second exposed 14 wrong answers in `re.mojo`, filed as
`bugs/FORMAL_re_word_boundary_never_matches.md`.

## 1. The run

Five invocations, because the first did not answer the slice and each fix
invalidated the CAS (both `formal/build.py` and `formal/model.py` are in the
cache key, so nothing replays after either). Every one below was really run, in
this order:

```
$ python3 tools/memslot.py --gb 8 --label sweep -- \
      python3 tools/formal_sweep.py -j 2 --no-stdlib --allow-concurrent \
      gimple_codegen.py generated_dispatch.py imports.py mlir.py \
      module_loader.py module_spec_gen.py monomorphize.py myinterpreter.py
# the default -t 30.  4 tool/timeouts, 1 backend-crash.

$ python3 tools/memslot.py --gb 8 --label sweep -- \
      python3 tools/formal_sweep.py -j 2 -t 900 --no-stdlib --allow-concurrent \
      gimple_codegen.py monomorphize.py myinterpreter.py
# the two biggest files, with the timeout the first run showed was too small.

$ python3 tools/memslot.py --gb 8 --label sweep-post -- \
      python3 tools/formal_sweep.py -j 3 -t 900 --no-stdlib --allow-concurrent \
      generated_dispatch.py imports.py mlir.py module_loader.py \
      module_spec_gen.py monomorphize.py
# the other six, after 7b1f2643.  6 misses: formal/build.py is in the CAS key,
# so the fix invalidated every verdict in this tree and nothing replayed.

$ python3 tools/memslot.py --gb 8 --label sweep-post2 -- \
      python3 tools/formal_sweep.py -j 3 -t 900 --no-stdlib --allow-concurrent \
      <the same six>
# the same six again, after 91db24b9 (formal/model.py is in the key too).  The
# run's own verdict-history line is the movement, name by name:
#   codegen/dependency -> codegen: 1
#   codegen/dependency -> not-answerable/host-import: 1
#   unchanged: 4

$ python3 tools/memslot.py --gb 8 --label sweep-big -- \
      python3 tools/formal_sweep.py -j 2 -t 5400 --no-stdlib --allow-concurrent \
      gimple_codegen.py myinterpreter.py
# the two the others cannot finish.  90 minutes each.  myinterpreter.py:
# not-answerable/host-import (importlib).  gimple_codegen.py: still no verdict.
```

`-t 900`, not the default 30: **the default is wrong for this slice.** Four of
the eight files were `tool`/timeout at `-t 30` and two of those are still
`tool`/timeout at `-t 900`, so for repo files the sweep's own advice ("a too-
small `-t` is the usual cause — raise it") is not enough; §4 has the numbers.
The sweep process peaked at **0.3 GB** across 6 processes for the whole slice,
so this is a CPU-bound slice and not a memory-bound one. Filed separately as
`bugs/FORMAL_sweep_default_timeout_hides_a_crash_on_the_repos_own_files.md`.

**The default `-t` also produced a MISCLASSIFICATION worth recording.**
`imports.py` was `TOOL: timeout (> 30s)` in the first run and
`BACKEND-CRASH` in the second, and both were true of the same tree: a 30-second
timeout kills the build before it reaches the census that raises, so a file
whose cost is "slow *and* crashing" is reported as whichever bound it happened
to hit first. The crash was only visible because the timeout was raised. A
`tool` verdict is therefore not evidence of absence on this slice, and the
causal order is: **raise `-t` before believing a `tool`.** The last run makes the
point three times over: at `-t 5400`, `myinterpreter.py` turned out to be a
permanent `importlib` refusal (§4) and `gimple_codegen.py` was still
unclassified.

## 2. Per-class counts — 7 of 8 classified, before and after each fix

| class | before | after `7b1f2643` | after `91db24b9` | files (final) |
|---|---|---|---|---|
| `pass` | 1 | 1 | 1 | `generated_dispatch.py` |
| `codegen` (THE FINDING) | 1 | 1 | **2** | `mlir.py`, **`module_spec_gen.py`** |
| `codegen/dependency` | 2 | 2 | **0** | — |
| `not-answerable/host-import` | 1 | 2 | **4** | `module_loader.py`, `imports.py`, `monomorphize.py`, **`myinterpreter.py`** |
| **`backend-crash`** | **1** | **0** | 0 | — |
| `tool` (no verdict) | 2 | 2 | **1** | `gimple_codegen.py` |
| **codegen coverage** | 1/4 = 25.0 % | 1/4 = 25.0 % | **1/3 = 33.3 %** | denominator = pass + the two codegen classes |

"before" is each file's verdict at the **largest `-t` it was given**, across the
five runs in §1; `myinterpreter.py`'s `importlib` refusal only arrived at
`-t 5400` (§4), and `gimple_codegen.py` is still unmeasured, so **the two end
columns differ on four of eight files and neither is a like-for-like
comparison at the same `-t`.** That is stated rather than smoothed over: a
slice swept at a too-small `-t` produces a *different set of classes*, not a
noisier version of the same one, which is the reason §4 and
`bugs/FORMAL_sweep_default_timeout_hides_a_crash_on_the_repos_own_files.md`
both argue for a per-closure default rather than a bigger number.

**The final tally is 1 + 2 + 0 + 4 + 0 + 1 = 8**, so the classes sum over the
whole slice, with one file in `tool` and therefore in no rate.

**Two movements, and they are movements of two different kinds.**

`backend-crash` 1 → 0 moved **nothing in the headline** and is still the first
fix to make: a `backend-crash` is a bug in the compiler's own plumbing and is
in **no rate at all** (`formal_sweep.py`'s class table says so), so
`codegen coverage` was 1/4 before and after it and a reader looking only at the
rate would see no reason to have done the work. It is first for two reasons the
rate cannot express — it is the only finding in the slice that is a defect in
*this* project rather than a limit in the target or a gap one level down, and
the sweep **exits 1 on a crash**, so a run carrying one has an exit code meaning
"something crashed" rather than "something was refused".

`codegen/dependency` 2 → 0 moved **the denominator** (4 → 3, so coverage rose
to 33.3 %) and, more usefully, **two files one level down**:
`monomorphize.py` went from `re.mojo`'s refusal to `tempfile`'s host import, and
`module_spec_gen.py` from `re.mojo`'s refusal to a refusal **in itself**. That
is the `codegen/dependency` contract working exactly as its own docstring
promises: the terminal cause is now in the file the reader is looking at, and
the new finding is a real one that the dependency was hiding.

## 3. The two fixes, and their measurements

### 3.1 `7b1f2643` — a backend CRASH (`imports.py`)

**Cause: two tables called "owners", one keyed by a bare method name and valued
by a `str`, the other keyed by the lifted `<Struct>_<method>` name and valued by
a `StructDef`; `_prepare_functions` passed the first where `_frame_receivers`
documents the second.**

`_frame_receivers`' own lookup `method_owners.get(fn.name)` therefore **MISSED
for every real method** (a lifted method's name is `<Struct>_<method>`, which is
not a key in the bare-name table) and **HIT for every module-level function
whose name happened to be one of a struct's method names**, answering with a
`str`. The string reached `_constant_read_sites` → `publish` →
`_overridden_comptime_names` and was asked for `.name`.

Measured, on this tree, both reproducers:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o out imports.py
  before: build: 'str' object has no attribute 'name'      <- AttributeError
  after:  build: imports.py imports 'cas', which cannot be built either:
          cas.py imports 'subprocess', which is a host module

$ python3 -c "import formal.build as B; B.compile_formal('formal/build.py', …)"
  before: AttributeError: 'str' object has no attribute 'name'
  after:  FormalBuildError: build.py imports 'copy', which is a host module …
```

`imports.py` is the shape because it declares its own module-level
`parse_module` (line 81) and imports `fire_compiler`, whose `Parser` has a
method of that name. `formal/build.py` is the same accident. **A module-level
function named like a method is not exotic** — it is what a corpus produces by
accident and a hand-written case never produces on purpose, which is why the
fix got a construct-level test rather than only the corpus case.

The fix **deletes** the parameter rather than handing it the right table:
`_frame_receivers` already builds `M.method_owner_names(structs)` from
`structs_by_name`, which is `_prepare_functions`' own list of the same nodes,
so there is nothing to thread through, and one table under one name is what
makes the repetition impossible. No `getattr` guard was added: a string that
silently skips the census is a worse failure than one that raises.

**Tests** — `test_formal_run.py`, `CASES`, beside the class-constant cluster
whose check raised:

| case | before the fix | after |
|---|---|---|
| `class_constant_census_survives_a_function_named_like_a_method` | **FAIL** — `AttributeError: 'str' object has no attribute 'name'` | PASS, exit 5 (`parse_module(1)` + `p.parse_module()` = 2 + 3) |
| `class_constant_none_through_a_receiver_is_still_refused_when_a_function_shares_its_name` | PASS | PASS |

The second row is the one that stops "the crash is gone" and "the check was
dropped" from being the same green. **Both halves of the minimal shape are
load-bearing and neither is incidental:** `refuse_none_comparisons` opens with
`if not none_names and not none_consts: return`, so the class-level `None` is
what stops the census short-circuiting, and the two-field struct is what makes
the unit hold a frame, because `_frame_receivers` returns before its own census
when no struct does.

### 3.2 `91db24b9` — a WRONG REFUSAL that also asserted a falsehood about CPython

**Cause: `_build_cfg` did `entry.succs += run(body, [], [entry.index])`. `run`
returns "the indices that fall through to the end" — the blocks control leaves
the FUNCTION by — and the only edge into the body is the one `open_block` makes
from `pending`. So when a function's LAST STATEMENT IS A LOOP, those blocks ARE
the loop's header and its latch, and each acquired a second, false predecessor:
the entry.** A definitely-stored fixpoint intersects over predecessors, so

```
header.IN = entry.OUT & preheader.OUT = {params} & {…, x} = {params}
```

and every name stored before the loop then looked unstored inside its body.

Measured, on this tree:

```
formal/hostmods/re.mojo    before: _p_alt: 'pend' is read at line 1401 before
                                    anything in this function stores it
                           after:  Built: .tmp/re.bin  [arm64/macho]
                           (pend = entry is line 1397; the read is 1401)

python3 test_re_formal.py   before:   6/264 checks passed
                          after: 994/1008 checks passed
```

**The refusal asserted something false about CPython**, which is what makes it
the more serious of the two fixes despite being found second.
`read_before_store_refusal` says "CPython raises `UnboundLocalError` for that
program"; for `_p_alt` CPython is silent, because `pend = entry` at 1397
dominates the read at 1401. A refusal whose message lies about the oracle is
worse for a reader than one that is merely wrong, because it sends them to fix
the source.

**Tests** — `test_formal_read_before_store.py`, six cases, and **every one of
that file's existing loop cases has a statement after the loop** (a `return t`, a
`return p`). That is not a style choice; it is the shape that let this survive,
because the trailing-loop shape was untested. Two of the six fail without the
fix and are the ones that catch it; the other four are guards, two of them
asserting that a one-armed store before a trailing loop is **still** refused,
because a fix that dropped the edge carelessly — or turned the header's IN into
a union — would pass the answered cases and fail those.

**The safety property, measured** — removing an intersection can only ever
*lower* the number of refusals, so the direction that could lose a true positive
needs a number and not a claim. Over every function of the 14 modules under
`formal/hostmods/` plus `re.mojo` — 5 888 CFG blocks — the orphan count (a
non-entry block with no predecessor at all) is **0 before the change and 0
after**. The fix subtracts a false edge and never creates an unreachable region,
which is the only way it could have lost a refusal.

**What it exposed** — `re.mojo` had never compiled, so 14 checks in
`test_re_formal.py` had never run. Seven of them are wrong answers in the regex
engine (`` never matches in any position; `re.VERBOSE` is accepted and
ignored; `\` is refused as unsupported), on both architectures identically.
Filed as `bugs/FORMAL_re_word_boundary_never_matches.md` with the localised next
step, and **not fixed here**: `re.mojo` is not this slice's file and the fix is a
diagnosis rather than a patch.

**Ownership** — no live claim covers this code. `formal3-6-r2` holds
`bug:FORMAL_read_before_store_dominating_store`, whose doc **does not exist**: it
was deleted in `1cfa8f80` together with the fix it described. `formal3-1-r2`'s
`FORMAL_a_local_read_before_its_first_assignment.md` is about the SYNTACTIC rule
and its next step is about making that scan cheap. Stated here because the
reasoning is the kind an integrator should be able to check rather than trust.

## 4. The one file the sweep cannot classify, and the one it needed 90 minutes for

| file | lines | `-t 30` | `-t 900` | `-t 5400` (90 min) |
|---|---|---|---|---|
| `myinterpreter.py` | 5 572 | timeout | timeout | **`not-answerable/host-import`** — imports `importlib` |
| `gimple_codegen.py` | 5 645 | timeout | timeout | **still no verdict** |

**`myinterpreter.py` took 90 minutes to be told it was never going to build.**
Its terminal reason is `importlib`, a host module with no Mojo source on any
path — the same permanent fact as `ctypes`, `subprocess` and `tempfile` — and
the sweep could only reach it after 90 minutes of compiling a 5 572-line file and
its whole import closure. That is the single most useful line in this section:
**a 90-minute run bought one refusal that is in no rate and has no next step.**

**`gimple_codegen.py` is the slice's one unmeasured file**, and it is
CPU-bound, not memory-bound: the whole 8-file sweep peaked at **0.3 GB** across
6 processes, and memcap's 4 GB per-file ceiling was never approached at any `-t`.
5 645 lines, no verdict in 90 minutes, against a 344-line file (`mlir.py`) that
classifies in under 600 s.

**Next step for whoever wants it classified — and it is not "raise `-t`".**
`-t 5400` is 180× the default and the file still did not finish, so the answer
is one of:

1. **Split the unit.** Construct coverage is a property of a file's
   *functions*, and the sweep's unit is a file. `gimple_codegen.py` at 5 645
   lines is a whole codegen backend in one file; nothing about the question
   needs one build. A `--split-by-function` mode would answer the same question
   for every large file in every slice, and both `codegen` findings this map
   does have are single-function.
2. **Find the quadratic.** 5 645 lines taking > 90 min against a 344-line file
   taking < 600 s is not a constant factor. `formal/build.py` walks the module's
   AST repeatedly per pass and `_frame_receivers` iterates its fixpoint over the
   whole function list; the AST-walk-per-pass shape is the first thing to
   profile, and `bugs/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`
   is a claim (`bugs3-hard`) for a shape in this neighbourhood — **that doc does
   not exist on this tree either**, so this may be the second stale claim in the
   area. **I did not make this measurement**: I have the two endpoints and no
   profile between them, and the profile is the whole of the next step.

Either way, a directory sweep will hit `gimple_codegen.py` and report it as
`tool` forever, so **the number a planner reads is missing one of eight files
for a reason that has nothing to do with the backend.** Every percentage in §2
is computed on the other seven, and nothing in this map should be read as a
statement about `gimple_codegen.py`, which is simply **unmeasured**.

## 5. Remaining causes, ranked, each with its example file and next step

`FILES BLOCKED` is an UPPER BOUND (a file's terminal cause is the first refusal
the walk reaches), so §5.1's marginal effect is measured before anything else.

### 5.1 `mlir.py` — FOUR constructs deep, and every one of them alone is worth 0 files

The single in-file `codegen` finding, and the most misleading row in this map if
it is read as "one missing call". `mlir.py`'s `unwrap` reads:

```python
m = member.strip()        # 38
if len(m) >= 2 and m.startswith('`') and m.endswith('`'):
    m = m[1:-1]           # 45
return m.strip()          # 46
```

The chain was measured by **patching a copy of `mlir.py` one construct at a
time and re-running `formal.build.compile_formal` on the copy** — not by
reading, so the order below is the order the walk reaches rather than the order
the constructs appear in the file. Each step replaced exactly one construct and
left the rest of the file alone:

```python
# .tmp/probe.py — the driver every step used
import sys, os; sys.path.insert(0, os.path.abspath('.'))
import formal.build as B
try:    B.compile_formal(sys.argv[1], output='.tmp/probe.bin', prove=False)
except B.CodegenError as e: print("REFUSED:", str(e)[:260])
except Exception as e:       print("RAISED:", type(e).__name__, str(e)[:200])
```

| # | construct | the refusal | docs |
|---|---|---|---|
| 1 | `s.strip()` (line 38) | *is a real method of String, but it returns a SHORTER string … the receiver's bytes cannot be written* | `FORMAL_string_value_model.md` (`formal3-8-r2`) |
| 2 | `m[1:-1]` (line 45) | *a slice of a string is refused … a container operation on [a bare `char *`]* | same doc, wave 6 §3 |
| 3 | `int(head, 0)` (lines 282, 289) | *int(...) takes exactly one value to convert on this path (got 2 argument(s))* | **no doc** — see below |
| 4 | `text.split(':', 1)` (line 287) | *is a real method of String, but it returns a SEQUENCE of strings* | nowhere — `FORMAL_known_limits.md` has no row for it (0 mentions of `split()`) |

**Marginal effect of each, measured: 0 files.** Lifting row 1 alone leaves row 2;
lifting 1+2 leaves row 3; lifting 1+2+3 leaves row 4. So the honest reading of
this map's only in-file finding is **"one file is four constructs from building"**
and not "one call is missing" — and the corollary for a planner is that row 3
(the only undocumented one) is worth **0 files on this slice even though it is
the only unowned one**, which is the argument for not picking it up on the
strength of "it has no doc".

Next step per row:

1. and 2. are the string value model and are claimed; the decision is **landed**
   and the doc says why a `{ptr,len}` descriptor is *strictly more expensive*
   than the `strlen`-based one it replaced (`lstrip` produces an interior
   pointer with no descriptor of its own). **There is no next step that is a
   lowering** — this is a value-model change shared by both backends and the Lean
   proof, and it needs someone who is going to make that change anyway.
3. `int(s, 0)` is a two-argument conversion, refused by the arity check at
   `formal/arm64_codegen.py:5533` and its x86-64 twin. It is answerable and is
   not a representation problem: base 0 is prefix detection (`0x`/`0o`/`0b`/
   decimal, with `_` separators and a sign), which is a `strtol` with base 0
   plus a validation the backend must not skip. **Unowned and undocumented**;
   filed as `FORMAL_two_argument_int_is_refused.md` with the reproducer. It is
   in both backend files rather than in `formal/model.py`, which is the
   pattern this tree has been consolidating away from — so the fix belongs in
   `model.py` first.
4. `s.split(sep, maxsplit)` returns a *sequence of strings*, and a sequence here
   is a frame-allocated blob with a compile-time capacity bound, so this is a
   container-representation change and not a method lowering. Same owner as row
   1 by consequence.

### 5.2 `module_spec_gen.py` — the `codegen/dependency` is GONE, and what it hid is now in the file

**This row was `codegen/dependency` (on `re.mojo`) and is now an in-file
`codegen` finding**, which is the `codegen/dependency` contract delivering what
it promises: the reader is now pointed at a construct in the file they opened,
and at a construct that is really there.

```
constructing ModuleSpecGenerator with arguments is a call to a user-defined
`__init__` whose body this path does not inline: a read of 'self' in the
right-hand side, which is the receiver of the constructor … a branch, a loop, a
call to a method, or a read of a name the constructor binds locally is a body
with an effect this path has not lowered. Use `ModuleSpecGenerator()` and assign
the fields, which is the same program with a representation.
```

Next step: read `module_spec_gen.py`'s `ModuleSpecGenerator.__init__` and either
split the initialiser into plain `self.<field> = …` assignments plus a
post-construction `configure()` (the message's own suggestion, and the shape
every other constructor on this path already has), or teach the inliner the one
extra statement kind the body uses. **Unowned and unclaimed** — there is no doc
for it and no claim over it. Marginal effect: **1 file, this one**, and it is
worth 1 file because the terminal cause is finally in the file rather than one
level down.

### 5.3 `monomorphize.py` — `codegen/dependency` is GONE, and it is now a host import

`monomorphize.py` was refused on `re.mojo` and is now refused on **`tempfile`**:
`monomorphize.py imports 'tempfile', which is a host module (CPython standard
library), which has no Mojo source for this backend to compile`. Same class as
`module_loader.py`'s `ctypes` and `imports.py`'s `subprocess` — a fact about the
target, not a gap in the backend, and in no rate.

**This row is the clearest argument in the map for fixing a one-level-down
cause.** `monomorphize.py` has now been refused three times in one session, each
time by the next thing in its import closure: `re.mojo`, then `tempfile`, and
before that `re` again at a lower `-t`. Nothing about `monomorphize.py` itself
has been measured at all, because it has never reached its own constructs — and
that will stay true until its whole closure is answerable, which is a statement
about the closure and not about the file. **No next step for this row** beyond
the general one: a host module for `tempfile` would need a process or a kernel
object, so it is permanent, and a reader should not spend effort here.

### 5.4 The four host imports, as a group — half the slice, and none of it work

(`monomorphize.py`'s own row is §5.3; it is listed here because the group is
what makes the coverage number legible.)

`module_loader.py` → `ctypes`; `imports.py` → `cas.py` → `subprocess`;
`monomorphize.py` → `tempfile`; `myinterpreter.py` → `importlib`. All four are
in the sweep's own "needs a host process, an embedded interpreter or a kernel
object this image does not have" bucket: **0 of the 4 import a module a
Mojo-side implementation could in principle provide**, so none of them is one
inversion away from answerable. `subprocess` needs a process, `ctypes` a foreign
function interface, `tempfile` a temporary directory and `importlib` an
interpreter to drive; none is a compiler gap and none is in any rate.

**No next step** — recorded so that a reader of the 33.3 % coverage figure knows
these four were never in the denominator, which is half the slice. It is also
the strongest single statement this map makes about where the slice's coverage
actually goes: **half of it is import closure this target cannot have**, and no
amount of codegen work moves that number.

`imports.py` was the slice's `backend-crash` before this change and is here
now; that is the fix, and §3 is the measurement.

### 5.5 `generated_dispatch.py` — `pass`, and it is the slice's only one

135 lines. Noted because a slice with one `pass` out of eight is a statement
about the files, not about the backend: **five of the seven classified files
are refused before codegen ever reaches their constructs** (four host imports,
one four-deep chain of string/container shapes), so the slice's 33.3 % is mostly
a statement about import closure and closure depth, and only `mlir.py` and
`module_spec_gen.py` are statements about what the backend can lower.

## 6. Ownership — nothing here was worked that someone else holds

Checked against `tools/control.py claims` before starting and before each edit:

| item | claim | in this branch? |
|---|---|---|
| `FORMAL_frame_receivers_is_handed_the_method_name_table.md` | **unowned** | fixed (`7b1f2643`); doc deleted |
| `formal/build.py` class-constant rewrite | `formal3-3-r2` holds the neighbouring docs only | **no conflict** — the fix DELETES a parameter and uses a table the function already builds; it adds no pass, no rule and no message, so it changes no other claim's behaviour |
| `formal/model.py` `_build_cfg` | `formal3-6-r2` holds `bug:FORMAL_read_before_store_dominating_store`, **whose doc does not exist** — deleted in `1cfa8f80` with the fix it described | **no live claim.** Stated explicitly because it is the one judgement in this branch an integrator should check rather than trust (§3.2) |
| `FORMAL_string_value_model.md` (rows 1–2, 4 of §5.1) | `formal3-8-r2` | untouched |
| `re.mojo`'s regex semantics (§3.2) | **unowned** | not touched — filed, with a localised next step |
| `FORMAL_module_state_no_storage.md` | `formal3-5` | untouched — and see §7 |

## 7. One red row this slice did not cause, recorded so it is not re-derived

`python3 test_formal_run.py` on this tree: **PASS=582 FAIL=1**, and the one
failure is `a_mutated_module_global_is_refused` — the backend now BUILDS a
program the row expects to be refused for `G is declared global in bump()`. It is
**not** from this change: reverting `formal/build.py` to `master`'s bytes and
running that one case alone fails identically. It is already documented as a
stale expectation in `bugs/TEST_a_mutated_module_global_is_refused_is_stale_after_the_slot_landed.md`,
which states the behaviour belongs to the `bug:FORMAL_module_state_no_storage`
claim. **Left alone**, and re-verified here rather than assumed, because a red
row in the file a change touches is exactly the thing that gets misattributed.