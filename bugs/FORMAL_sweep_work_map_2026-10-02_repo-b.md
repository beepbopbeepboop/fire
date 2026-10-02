# FORMAL_sweep_work_map_2026-10-02_repo-b: the repo's own `g`-`m` files, and the one crash behind 25 % of the slice

**Slice:** `sweep:repo-b` = this repository's own top-level `*.py` files whose
names start `g`–`m` — 8 files, 13 692 lines:
`gimple_codegen.py`, `generated_dispatch.py`, `imports.py`, `mlir.py`,
`module_loader.py`, `module_spec_gen.py`, `monomorphize.py`,
`myinterpreter.py`. **arm64** (the slice does not name an architecture, and
arm64 is the default). No stdlib root (`--no-stdlib`).

**Status: one top cause FIXED and verified; six of eight files classified; two
still unclassified because the sweep cannot finish them (§4).** The fix is
`7b1f2643`, and it deleted
`bugs/FORMAL_frame_receivers_is_handed_the_method_name_table.md`.

## 1. The run

```
$ python3 tools/memslot.py --gb 8 --label sweep -- \
      python3 tools/formal_sweep.py -j 2 -t 900 --no-stdlib --allow-concurrent \
      gimple_codegen.py generated_dispatch.py imports.py mlir.py \
      module_loader.py module_spec_gen.py monomorphize.py myinterpreter.py
```

`-t 900`, not the default 30: **the default is wrong for this slice.** Four of
the eight files were `tool`/timeout at `-t 30` and two of those are still
`tool`/timeout at `-t 900`, so for repo files the sweep's own advice ("a too-
small `-t` is the usual cause — raise it") is not enough; §4 has the numbers.
The sweep process peaked at **0.3 GB** across 6 processes for the whole slice,
so this is a CPU-bound slice and not a memory-bound one.

**The default `-t` also produced a MISCLASSIFICATION worth recording.**
`imports.py` was `TOOL: timeout (> 30s)` in the first run and
`BACKEND-CRASH` in the second, and both were true of the same tree: a 30-second
timeout kills the build before it reaches the census that raises, so a file
whose cost is "slow *and* crashing" is reported as whichever bound it happened
to hit first. The crash was only visible because the timeout was raised. A
`tool` verdict is therefore not evidence of absence on this slice, and the
causal order is: **raise `-t` before believing a `tool`.**

## 2. Per-class counts (post-fix, 6 of 8 classified)

| class | before the fix | after | files |
|---|---|---|---|
| `pass` | 1 | 1 | `generated_dispatch.py` |
| `codegen` (THE FINDING) | 1 | 1 | `mlir.py` |
| `codegen/dependency` | 2 | 2 | `module_spec_gen.py`, `monomorphize.py` |
| `not-answerable/host-import` | 1 | 2 | `module_loader.py`, **`imports.py`** |
| **`backend-crash`** | **1** | **0** | — (`imports.py`, now host-import) |
| `tool` (no verdict) | 2 | 2 | `gimple_codegen.py`, `myinterpreter.py` |
| **codegen coverage** | 1/4 = 25.0 % | **1/4 = 25.0 %** | denominator = pass + the two codegen classes |

"before" is each file's verdict at the **largest `-t` it was given**, which took
three runs to establish (8 files at `-t 30`, then the two that timed out at
900 s, then the five that had not been re-run since `formal/build.py` changed):
1 + 1 + 2 + 1 + 1 + 2 = 8. Both columns are therefore complete over the slice,
and the *only* difference between them is `imports.py`.

**The movement is `backend-crash` 1 → 0**, and it is worth being precise about
why that is the top cause to pick despite moving nothing in the headline: a
`backend-crash` is a bug in the compiler's own plumbing and is in **no rate at
all** (`formal_sweep.py`'s class table says so), so `codegen coverage` is
1/4 = 25.0 % before and after and a reader looking only at the rate would see no
reason to have done the work. It is still first, for two reasons the rate cannot
express: it is the only finding in the slice that is a defect in *this* project
rather than a limit in the target or a gap one level down, and the sweep **exits
1 on a crash** — so a run carrying one has an exit code that means "something
crashed" rather than "something was refused", and the two are not the same
signal to a caller retrying on the status.

## 3. What was fixed, and the measurement

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

## 4. The two files the sweep cannot classify, and why that is a fact about the files

| file | lines | `-t 30` | `-t 900` | `-t 5400` |
|---|---|---|---|---|
| `gimple_codegen.py` | 5 645 | timeout | timeout | see §1's note below |
| `myinterpreter.py` | 5 572 | timeout | timeout | ditto |

Both are the two largest files in the repo's root, and both are **CPU-bound,
not memory-bound**: the whole sweep peaked at 0.3 GB, and `tools/memcap.py`'s
4 GB per-file ceiling was never approached.

**Next step for whoever wants these classified — and it is not "raise `-t`".**
`-t 900` is 15× the default and neither file finished. A sweep over a whole
directory will hit exactly these two and report them as `tool` forever, so the
number a planner reads is missing two of eight files for a reason that has
nothing to do with the backend. Two options, in order of cost:

1. **Split the unit.** The construct coverage of a file is a property of its
   functions, and the sweep's unit is a file. `myinterpreter.py` at 5 572 lines
   is a whole compiler front end in one file; nothing about it needs one build.
   A `--split-by-function` mode (or a corpus that slices the file) would answer
   the same question for every large file in every slice, and the two
   `codegen` findings this map does have are both single-function.
2. **Find the quadratic.** 5 645 lines taking > 900 s against a 344-line file
   taking under 600 s is not a constant factor. `formal/build.py` walks the
   module's AST repeatedly per pass and `_frame_receivers` iterates its
   fixpoint over the whole function list; the AST-walk-per-pass shape is
   documented in `CLAUDE.md`'s own perf guidance and worth a profile before a
   third option is invented. **This is a measurement I did not make** — I have
   the two endpoints and no profile between them, and the profile is the whole
   of the next step.

The honest statement of what this slice knows: **6 of 8 files classified, and
25 % of the slice's files are unclassified for a reason that is about their
size, not about the backend.** Every percentage in §2 is computed on the 6.

## 5. Remaining causes, ranked, each with its example file and next step

`FILES BLOCKED` is an UPPER BOUND (a file's terminal cause is the first refusal
the walk reaches), so §5.1's marginal effect is measured before anything else.

### 5.1 `mlir.py` — FOUR constructs deep, and every one of them alone is worth 0 files

The single in-file `codegen` finding, and the most misleading row in this map if
it is read as "one missing call". `mlir.py`'s `unwrap` reads:

```python
m = member.strip()        # 38
if len(m) >= 2 and m.startswith('`') and m.endswith('`'):
    m = m[1:-1]           # 43
return m.strip()          # 46
```

Progressive patching of a copy (`.tmp/mlir_probe*.py`), each step replacing one
construct and re-running the compile, gives the chain **in the order the walk
reaches it**:

| # | construct | the refusal | docs |
|---|---|---|---|
| 1 | `s.strip()` (line 38) | *is a real method of String, but it returns a SHORTER string … the receiver's bytes cannot be written* | `FORMAL_string_value_model.md` (`formal3-8-r2`) |
| 2 | `m[1:-1]` (line 43) | *a slice of a string is refused … a container operation on [a bare `char *`]* | same doc, wave 6 §3 |
| 3 | `int(head, 0)` (lines 282, 289) | *int(...) takes exactly one value to convert on this path (got 2 argument(s))* | **no doc** — see below |
| 4 | `text.split(':', 1)` (line 287) | *is a real method of String, but it returns a SEQUENCE of strings* | not in `FORMAL_known_limits.md` |

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

### 5.2 `module_spec_gen.py`, `monomorphize.py` — one `codegen/dependency`, and it is not in these files

Both are refused at the same terminal reason one level down:

```
re.mojo: _p_alt: 'pend' is read at line 1401 before anything in this function
stores it, and CPython raises UnboundLocalError for that program …
This path cannot raise it: the register allocator gives 'pend' a home because
the function assigns it somewhere, and the emitted image has no way to mean
"unbound" — so the read would return whatever the CALLER left in that register,
a word that changes with the build and differs between the two backends.
```

**The refusal is correct and should stay.** CPython raises for this program, so
a build that answered it would be a wrong answer, and the backend's rule is that
a wrong answer is the one outcome it may not produce. This is the
`codegen/dependency` contract working as documented: the gap is in `re.mojo`, a
stdlib file, and neither of these two files is a finding about itself.

Owner: the **stdlib** slices (`sweep:std-*`) for the `re.mojo` source shape, and
`formal3-1-r2` (`FORMAL_a_local_read_before_its_first_assignment.md`) /
`formal3-6-r2` (`FORMAL_read_before_store_dominating_store.md`) for the backend
question of raising an unbound read at all. **Next step:** the cheapest correct
move is the one the message names — `re.mojo`'s `_p_alt` should store `pend`
before reading it, which is a stdlib source fix and not a backend change. Until
that lands, these two files cannot build for a reason no repo-side work removes.

### 5.3 `module_loader.py`, `imports.py` — host imports, and both are permanent

`module_loader.py` → `ctypes`; `imports.py` → `cas.py` → `subprocess`. Both are
in the sweep's own "needs a host process, an embedded interpreter or a kernel
object this image does not have" bucket: 0 of the 2 import a module a Mojo-side
implementation could in principle provide. `subprocess` needs a process and
`ctypes` needs a foreign function interface; neither is a compiler gap and
neither is in any rate. **No next step** — recorded so that a reader of the
25 % coverage figure knows these two were never in the denominator.

`imports.py` was the slice's `backend-crash` before this change and is here
now; that is the fix, and §3 is the measurement.

### 5.4 `generated_dispatch.py` — `pass`, and it is the slice's only one

135 lines. Noted because a slice with one `pass` out of eight is a statement
about the files, not about the backend: five of the six classified files are
refused before codegen gets to their constructs at all (two host imports, one
stdlib dependency, one chain of four string/container shapes), so **the slice's
25 % is mostly a statement about import closure, and only `mlir.py` is a
statement about what the backend can lower.**

## 6. Ownership — nothing here was worked that someone else holds

Checked against `tools/control.py claims` before starting and before each edit:

| item | claim | in this branch? |
|---|---|---|
| `FORMAL_frame_receivers_is_handed_the_method_name_table.md` | **unowned** | fixed; doc deleted |
| `formal/build.py` class-constant rewrite | `formal3-3-r2` holds the neighbouring docs only | **no conflict** — the fix DELETES a parameter and passes a table the function already builds; it adds no pass, no rule and no message, so it changes no other claim's behaviour |
| `FORMAL_string_value_model.md` (rows 1–2, 4 of §5.1) | `formal3-8-r2` | untouched |
| `re.mojo` unbound `pend` | `formal3-1-r2`, `formal3-6-r2` | untouched |
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