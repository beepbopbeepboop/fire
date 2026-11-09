# FORMAL_no_exceptions: a `raise` is a TERMINATION on this path, not a value the caller can catch

> **PLANNED — this document's open work is decomposed into `bugs/plan/step-*.md`,
> and the design plus ordering live in `doc/finish-formal.md`.** The steps that
> own parts of this document: **step-26** (one discoverable host-module failure
> convention, item 1) and **step-27a…c** (the EH-runtime / `try`-handler-arm
> scaffold, item 2). Read the measurements here first; the step files are the
> work orders. Item 3 (pin the behaviour) is already DONE.

**Status 2026-10-31 (`formal2059-docs`): item 3 of "The next step" remains
DONE; steps 1 and 2 (discoverable convention; EH runtime) remain open design
projects. `test_formal_exceptions.py` is 331 checks, 0 failures (both
architectures), measured here with `python3 test_formal_exceptions.py` wrapped
in `python3 tools/memslot.py --gb 8 --label t` (exit 0, 0.2 GB peak). The
suite has grown from 285 (2026-10-07) through 315 (2026-10-12) to 331; the
rule, the three refusal rows, and the `finally`/termination behaviour are all
unchanged.** The arm64 flush divergence (`bugs/FORMAL_arm64_flush_...`) was
already deleted by its fix; no new divergence. The document stays open for
items 1 and 2.

**Status 2026-10-07 (`formal126-docs`): item 3 of "The next step" is DONE, and
the claim below that "there is no test in the tree that raises on this path" is
no longer true.** `test_formal_exceptions.py` landed 2026-10-05 and is 285
checks, 0 failures: it builds and runs, on BOTH architectures, every `raise`
shape this document describes and against CPython — a raise under a handler (a
`RFUSED` row that must name the construct), a `try` with nothing raised, a
`return` as the control, `SystemExit`'s status word, the two `ZeroDivisionError`
guards, the float divide, `assert`, and `finally` on the way out — plus the three
REFUSED rows that keep the handler-arm boundary a checked claim. Items 1 and 2
below (one discoverable convention; an EH runtime or not) are unchanged design
projects, and item 1's cost is three host modules' worth of churn, which is not
this document's to spend.

**Status 2026-10-08 (`work/formal193-docs`): the 10-07 records above are
re-verified, and the 2026-09-30 measurements under "What I ran" are corrected
where they have gone stale.** Read the rest of this file as the record of
2026-09-30, with the corrections below.

- **(c) the same `try`/`except` with a body is refused whether or not anything
  is raised**, so the program that measured "`try` is lowered and works" under
  "What I ran" no longer runs; the positive half survives in
  `test_formal_exceptions.py` as `an_except_pass_arm_still_builds` and
  `else_runs_when_the_body_completed`.
- **(d) the arm64 flush divergence is GONE** — a `raise 7` after a `printf` now
  prints `before@@` and exits 1 on arm64 as it always did on x86-64, measured
  that session on both backends; the 10-07 sections above already record the
  fix and the deletion of the divergence's own document.
- The handler-arm refusal the 10-07 sections record is confirmed by name on
  both backends; the three refusal rows it stands on are
  `an_except_arm_with_a_print_is_refused_by_name`,
  `an_except_as_binding_is_refused_by_name` and
  `a_bare_except_with_a_body_is_refused_by_name`.

Next step 3 remains DONE exactly as the 10-07 sections and the "The next
step" item below record it; steps 1 and 2 (one discoverable convention; an
EH runtime) are unchanged design projects and are not this update's.

**Status:** open, and it is a LIMIT OF THE TARGET rather than a defect — but it
is load-bearing for every module under `formal/hostmods/`, and until it had a
document `formal/hostmods/json.mojo` cited a file that did not exist. Found
2026-09-30 while auditing the cross-references of the second host-module wave;
the measurement below is new, the behaviour is old.

**Status 2026-10-07 (`formal112-docs`; `work/formal160-docs` recorded the same
state independently): the RULE is unchanged, next step 3 is
DONE, and case (a) below is STALE.** The uncaught half of the contract now has
its own suite — `test_formal_exceptions.py`, **285 checks, green**, both
architectures — it runs each program under `python3` and the image and
compares stdout AND exit status, which is the observable the exit-0-only
`test_formal_run.py` runner could not express — so "there is no test in the tree
that raises on this path" (next step 3) is no longer true and the `arm64` flush
divergence it says sat unnoticed has its own rows
(`test_formal_link_accounting.py::test_raise_flushes_stdout` and the parity
file's `printed_output_survives_a_raise`; the divergence's own document was
deleted with the fix). And case (a)'s shape is no longer a
build-and-die: `try: raise …` with an `except:` arm that has a BODY is now
REFUSED by name ("… is a handler arm with a body this path cannot put in the
image"), which is the honest form of the same fact — the arm could never run, so
the program is not built as one whose arm is absent. The rule this document
states is exactly what makes that refusal correct, and the measured table in
"what a `raise` actually lowers to" still holds for a `raise` the image DOES
build: evaluate the expression, run the enclosing `finally`, terminate. Next
steps 1 (one convention for the host modules) and 2 (an EH runtime, or not) are
untouched and open — item 2 is the reason this stays a limit-of-the-target
document.
**Why a document rather than a line in a module docstring.** Four modules now
answer the same question differently because of this, and each had to invent its
own wording: `os.makedirs` is CPython's `makedirs(path, exist_ok=True)` with no
spelling of the other one (`formal/hostmods/os/__init__.mojo`), `json` spells
"this document is malformed" as a return value rather than a `JSONDecodeError`,
and `hashlib` spells "these inputs disagree" as a status. A reader who has not
internalised the rule will read each of those as an approximation of CPython
and "fix" it into a raise. The rule belongs in one place, and the place is a
document every one of them can cite.

**Status 2026-10-07 (`work/formal143-docs`): "The next step" item 3 landed long
before this was written down, and §"What I ran" (a) is no longer the behaviour —
the caught half is now a NAMED REFUSAL rather than a silent termination, which is
this document's own disease (a diagnostic false about the path it describes)
fixed one layer in. Nothing in the RULE below moves; the two host-module
conventions and items 1 and 2 of "The next step" are unchanged.**

* **A `try`/`except` whose arm has a NON-EMPTY body is refused at BUILD time, by
  name, on both architectures and byte-identically** —
  `formal/model.py::refuse_dropped_handler_arm`, which
  `bugs/FORMAL_a_try_handler_arm_is_still_never_emitted.md` owns. So §"What I
  ran" (a)'s measurement ("the arm is never entered, and the output is lost",
  exit 1 with no `before`) describes a tree that no longer exists: that program
  does not build. The empty-body shapes still build and run — `except: pass`, and
  a `try` with nothing raised — because an arm with no effect to drop loses
  nothing by being left out.
* **Item 3 (pin the behaviour) is DONE, in a better place than the one it asked
  for.** `test_formal_exceptions.py` is 285 checks over both architectures: the
  uncaught half against CPython's own stdout and exit status (including
  `raise ValueError`/`OSError(...)`/a declared class/`SystemExit(<computed>)`,
  where the status is a value and not a literal), the `finally` half, and three
  `REFUSED` rows that keep the handler-arm refusal honest. The three-case group
  ("`raise` under a handler, `try` with nothing raised, `return 1`") is
  `a_bare_except_with_a_body_is_refused_by_name`, `an_except_pass_arm_still_builds`
  and the ordinary `return 1` rows, so the sentence "there is no test in the tree
  that raises on this path" below is stale.
* **The rule below still stands, and items 1 and 2 still do not have a fix.**
  There is still no unwinder: the uncaught `raise` is still `exit`/`_emit_diverge`,
  the exception object is still never constructed, and the host modules still
  choose a return convention each. This is a limit-of-the-target document with a
  narrower open remainder than it was filed with.

## What a `raise` actually lowers to

Both backends take the same decision, at the same place in their statement
walk, and neither has an exception-handling runtime.

`formal/arm64_codegen.py:1142`:

```python
        if isinstance(stmt, F.RaiseStmt):
            # No EH runtime: evaluate the exception expression for side
            # effects (args of `raise RuntimeError(...)` etc.), run every
            # enclosing finally (same stack as return), then Darwin
            # exit(1). except handlers stay unreachable — there is no
            # unwinder to route to; the nonzero status is the signal.
```

`formal/x86_64_codegen.py:997` is the same comment over
`self._emit_call_exit(1)`, whose own docstring at `:1392` reads *"Call the C
library's `exit(status)`"*.

So a raise is: evaluate the exception expression for its side effects, run the
enclosing `finally` blocks, and **terminate the process**. The exception OBJECT
is never constructed, never stored, and never delivered. `FORMAL.md` §Phase 7
lists `try`/`except` as future work, which is the same fact from the other
direction.

## What I ran

Four programs, arm64, built with `python3 fire.py build --formal --no-prove`
and run directly. `.tmp` paths, so nothing here is a repository file.

**(a) a raise under a handler — the arm is never entered, and the output is
lost:**

```
def main() -> int:
    printf("before@@")
    try:
        raise 7
    except:
        printf("caught@@")
    printf("after@@")
    return 0
```

```
$ ./.tmp/exc/a
$ echo $?
1
```

No output at all, and exit 1. `before` was printed (see the control below), so
the `except` arm did not run and `after` did not either. **The lost `before` was
a separate defect** — the arm64 `raise` left through a raw Darwin `SYS_exit`
that skips libc's `exit` and its stdout flush — and it is why this program's
output was empty rather than `before`. It is fixed: `_emit_exit` flushes
through `fflush(NULL)` before the trap and every error stop shares it; the
gate-resident pin is `test_formal_link_accounting.py::test_raise_flushes_stdout`,
and the class `test_formal_x86_64_parity.py`'s `FAILING_CASES` carries the same
shape (`printed_output_survives_a_raise`).

**STALE 2026-10-08: this program no longer builds at all.**  A `try` whose
`except` arm has a body is refused by name on both backends (the arm's effects
would be silently absent from the image that runs), so (a) and (c) below are
historical readings and not the current answers.  The flush half of the reading
is separately fixed — the control (b) and the bare raise (d) both print the line
now — and the live subject for the `try` half is
`bugs/FORMAL_a_try_handler_arm_is_still_never_emitted.md`.

**(b) the control — the same program with `return 1`, no raise:**

```
def main() -> int:
    printf("before@@")
    return 1
```

```
$ ./.tmp/exc/b
before@@
$ echo $?
1
```

So `printf` works, the status propagates, and stdout is flushed on the normal
path.

**(c) `try`/`except` with nothing raised — the machinery is not the problem:**

```
def main() -> int:
    printf("before@@")
    try:
        printf("body@@")
    except:
        printf("caught@@")
    printf("after@@")
    return 0
```

```
$ ./.tmp/exc/d
before@@body@@after@@
$ echo $?
0
```

The body runs, the arm is skipped, the code after the statement runs. **`try` is
lowered and works; it is only `raise` that cannot be caught.**

**(d) a bare raise with no handler at all, on BOTH backends:**

```
def main() -> int:
    printf("before@@")
    raise 7
```

```
$ ./.tmp/exc/e                 # arm64
$ echo $?
1
$ ./.tmp/exc/e64               # the same source, --backend=x86_64
before@@
$ echo $?
1
```

Identical control flow — terminate with status 1, no unwinder — and the two
backends differ in whether the buffered output survives, which is the flush
document's bug and not this one.  **Both backends now print `before@@` (measured
2026-10-08): `_emit_exit` flushes before the raw `svc`, so the divergence this
paragraph records is closed and the output above is the historical reading.**
The arm64 line printed nothing when this was written; it prints the line now.

## The rule, stated once

**On the formal path, "did this fail?" is a RETURN VALUE and cannot be an
exception.** A module that must report failure to a caller therefore picks a
return convention and says at each definition what it is, and a caller has to
read that convention rather than assume CPython's. The three conventions in the
tree today:

| module | convention | where it is stated |
|---|---|---|
| `os` | `0` on success, `-1` on failure; `makedirs` is `exist_ok=True` only | `formal/hostmods/os/__init__.mojo`, at each `def` |
| `json` | `valid` / `top_kind` / `member_kind` — names CPython's `json` does not have, carrying the answer as a word | `formal/hostmods/json.mojo`, at each `def` |
| `hashlib` | total function; no failure status | `formal/hostmods/hashlib.mojo` |

The convention is `formal/hostmods/hoststatus.mojo`: `status_ok()`/`status_err()`.

The reason a status is *not* invented where CPython has no failure to report is
`os.makedirs`: a target with no exceptions cannot report `FileExistsError` to a
caller that did not ask for it, and a status the caller cannot distinguish from
a real failure is worse than being permissive. That sentence is the rule.

## What it costs, and what it does not

It does **not** block the sweep. The formal sweep measures a file's ability to
be *built*, and a file that raises builds fine — it is the host-module
functions that are constrained, and those are exactly the ones this document
covers. The cost is API design: every future host module picks its own
convention, and a reader has to learn it per module.

## The next step

Ordered by what unblocks the most:

1. **Decide the convention once, in one place, and make it discoverable.** DONE 2026-11-05: `formal/hostmods/hoststatus.mojo` provides `status_ok()`/`status_err()` and is cited across host modules.
2. **An EH runtime, or do not.** A raise that unwinds to a handler needs a
   landing-pad table, a personality routine per catch type, and a place for the
   exception object to live — and `FORMAL.md`'s own arithmetic says
   "adding a capability whose value model does not exist yet" is the wall
   (`FORMAL_module_state_no_storage.md (deleted) (deleted)` is the specific reason: an
   exception object is more than one 64-bit word). That is a real programme,
   not an afternoon, and until it is worth doing the honest thing is what the
   four modules above already do: refuse to raise, and say so at the function.
3. **Pin the behaviour so a backend change cannot quietly alter it.** There was
   no test in the tree that raises on this path, which is why the arm64 flush
   divergence (a `raise` leaving through an inline `svc` that skips libc's
   `exit`) sat unnoticed through both backends and both host-module waves.
   **It is DONE:** that pin now exists — `test_formal_link_accounting.py::test_raise_flushes_stdout`
   builds `printf` then `raise`, the same source with `return 1`, and asserts
   both keep their stdout and exit 1 on both backends — the gate-resident file
   that already owns "does the thing this claim names exist" — and the class
   `test_formal_x86_64_parity.py`'s `FAILING_CASES` (`printed_output_survives_a_raise`)
   carries the same shape for the file that is in no bucket. The suite itself,
   `test_formal_exceptions.py`, is also not in a `tools/suite.py` bucket;
   registering it is a separate decision this document does not make.


## EH design (step-27a)

*Written 2026-11-07. Steps 27b and 27c landed first and cite this memo; the step file claimed DONE with no memo behind it. This records what was measured, what 27b/27c already implement, and the decisions that are still open, each ending in a RECOMMENDATION.*

### Measured state (2026-11-07)

`python3 -c "import formal.model"` works (the `threading` import the step feared was already fixed). Programs from `.tmp/27a/` built with `compile_formal(prove=False)` on BOTH arm64 and x86-64, identical on the two:

| program | result |
|---|---|
| `try: printf("a") / except ValueError: printf("b")` | builds, prints `a`, exit 0 (the handler is dead because the body cannot raise) |
| `try: raise ValueError("x") / except ValueError:` | REFUSED by `try_handler_refusal` ("this image has no unwinder: a `raise` here is an EXIT") |
| `try: boom() / except ValueError:` with `boom` raising | REFUSED (the body calls a function that can end the process and the arm cannot catch it) |
| `except ValueError as e:` | REFUSED by `unemitted_handler_arm` ("a handler arm with a body this path cannot put in the image") |
| `try: raise ValueError("x") / finally: printf("f")` | builds, prints `f`, exit 1 (the `finally` runs, then the process exits: correct for an uncaught raise) |

So the SUSPECT in the step ("handler arms silently dropped for a raising body") does NOT hold: there is no truth bug. `test_formal_exceptions.py` 331/331, `test_formal_try_model.py` OK, `test_formal_eh_tables.py` OK.

### Q1 — where the exception object lives
- **R1** a `malloc`'d record `[class_id: i64][msg: char*][cause: i64]`, its address the in-flight value. A value outlives its frame on this path only through `malloc` (the blob pattern); an exception outlives the frame that raised it by definition.
- **R2** a per-process global slot. Rejected: there is no module-state storage (every value is one word in a function's stack scratch).
- **R3** a caller-allocated frame record passed as a hidden argument to every raiser. Avoids `malloc` but changes the signature of every raiser and every function pointer to one.

**RECOMMENDATION: R1**, with `class_id` the index into the sorted union of `CPYTHON_EXCEPTION_BASE` (`formal/model/types.py:2496`) and the module's own declared exception classes, so a landing pad's `class_ids` are numbers fixed at BUILD time.

### Q2 — what `except A as e` binds
**RECOMMENDATION:** `e` is the R1 record's address as an OPAQUE word with no operation on it in the first slice, and `as e` stays REFUSED by name (`unemitted_handler_arm`, row `an_except_as_binding_is_refused_by_name`) until a later step gives `e` a message accessor. Nothing in the tree gives `e` a value today, so refusing is the only sound reading.

### Q3 — superclass matching
Already answered, not open: `handler_arm_matches(arm_name, flying_name, kinds, structs)` (`formal/model/types.py:2718`) returns True/False/None over the CPython hierarchy and is oracle-tested 71 x 71 by `test_formal_exceptions.py::run_matching_oracle`. A landing-pad row per (try region, arm) lists the `class_id`s for which it returned True, computed at build time. **This is exactly `formal/model/eh.py`** (`PersonalityArm`, `LandingPad`, `LandingPadTable.arm_for(region_id, class_id)`, `build_landing_pads`), landed by 27c with no codegen change. **RECOMMENDATION:** a `None` (undecidable) answer refuses the image; never a guess.

### Propagation
Which functions can raise is already computed: `_raises_somewhere` (`formal/build.py:17228`) and, across modules, `CrossModuleRaises` (`formal/imports.py:2179`). **RECOMMENDATION (a proposal for `doc/ABI.md`, not an edit of it):** only functions in the raiser set get the new convention; every other function's ABI is unchanged. A raiser returns its normal value in the first return register and an in-flight status in the SECOND return register (`x1` / `rdx`): 0 for a normal return, otherwise the R1 record's address. After every call to a raiser the caller tests the status register and branches to the enclosing landing pad (or, with none, returns the status upward unchanged). This keeps the cost on raisers and their callers.

### Proof-side plan
`MojoStmt` (`lib/ProofLib.lean:966`) has no `raise` or `try` constructor; 27b translates a flat `try` in the GENERATOR (`_stmts_go`, `_stmts_go_t`, `_stmts_ast`: body ++ else ++ finally) with no Lean change, which is sound only while the region cannot raise (the refusals above guarantee that today). **RECOMMENDATION:** add the minimal constructors `raise (cls : Nat)` and `tryStmt (body) (arms : List (List Nat × List MojoStmt)) (final)` only when 27e emits real dispatch, and state, as `sorry` holes ledgered in `formal/proof_gaps.py::SCAFFOLD_HOLES` (S1/S2), `try_flat_sound` (a `try` whose region cannot raise is body; else; finally) and `raise_terminates`. Not before: constructors nothing emits would be a model with no consumer.

### Slice order (each independently testable by `test_formal_exceptions.py`, oracle rows against CPython)
1. **27d** same-module raiser marking plus the status-register convention, arm64 first, behind the existing refusals (no handler runs yet): measure that programs without a handler arm are byte-identical, and raisers return status 0.
2. **27e** a `raise` caught by an arm in the SAME function (no calls): build the R1 record, dispatch through `LandingPadTable`, run the arm body; `as e` still refused.
3. **27f** calls through a raiser: test the status register after each call, route to the pad or propagate; the "calls boom()" row above becomes a built-and-run row.
4. **27g** `finally` with an exception in flight, and cross-module raisers via `CrossModuleRaises`; then x86-64.

Sizing note carried from the deleted design doc: hand-dispatching a same-function arm without the call convention moves 0 corpus files (every arm wraps a CALL), which is why 27e alone is not the milestone; 27f is.
