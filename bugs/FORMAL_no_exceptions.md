# FORMAL_no_exceptions: a `raise` is a TERMINATION on this path, not a value the caller can catch

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

**Status:** open, and it is a LIMIT OF THE TARGET rather than a defect — but it
is load-bearing for every module under `formal/hostmods/`, and until it had a
document `formal/hostmods/json.mojo` cited a file that did not exist. Found
2026-09-30 while auditing the cross-references of the second host-module wave;
the measurement below is new, the behaviour is old.

**Status 2026-10-07 (`formal112-docs`): the RULE is unchanged, next step 3 is
DONE, and case (a) below is STALE.** The uncaught half of the contract now has
its own suite — `test_formal_exceptions.py`, **285 checks, green**, both
architectures — so "there is no test in the tree that raises on this path" (next
step 3) is no longer true and the `arm64` flush divergence it says sat unnoticed
has its own document and its own rows. And case (a)'s shape is no longer a
build-and-die: `try: raise …` with an `except:` arm that has a BODY is now
REFUSED by name ("… is a handler arm with a body this path cannot put in the
image"), which is the honest form of the same fact — the arm could never run, so
the program is not built as one whose arm is absent. The rule this document
states is exactly what makes that refusal correct, and the measured table in
"what a `raise` actually lowers to" still holds for a `raise` the image DOES
build: evaluate the expression, run the enclosing `finally`, terminate. Next
steps 1 (one convention for the host modules) and 2 (an EH runtime, or not) are
untouched.

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
a separate defect** — on arm64 a `raise` left through an inline `svc`, a raw
Darwin `SYS_exit` that skips libc's `exit` and its stdout flush — and it is why
this program's output was empty rather than `before`. It is fixed: every exit
goes through `_emit_exit`, which flushes, and it is pinned by
`test_formal_x86_64_parity.py`'s `printed_output_survives_a_raise`.

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
document's bug and not this one.

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
| `hashlib` | each digest is one function returning a string; a disagreement is a status | `formal/hostmods/hashlib.mojo` |

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

1. **Decide the convention once, in one place, and make it discoverable.** Not a
   code change: a single exported pair of names every host module uses, so
   `os`, `json` and `hashlib` stop each inventing one. The cost is three
   modules' worth of churn and the benefit is that the next module does not
   have to decide anything.
2. **An EH runtime, or do not.** A raise that unwinds to a handler needs a
   landing-pad table, a personality routine per catch type, and a place for the
   exception object to live — and `FORMAL.md`'s own arithmetic says
   "adding a capability whose value model does not exist yet" is the wall
   (`bugs/FORMAL_module_state_no_storage.md` is the specific reason: an
   exception object is more than one 64-bit word). That is a real programme,
   not an afternoon, and until it is worth doing the honest thing is what the
   four modules above already do: refuse to raise, and say so at the function.
3. **Pin the behaviour so a backend change cannot quietly alter it.** There was
   no test in the tree that raises on this path, which is why the arm64 flush
   divergence (a `raise` leaving through an inline `svc` that skips libc's
   `exit`) sat unnoticed through both backends and both host-module waves. It is
   now pinned by `test_formal_x86_64_parity.py`'s `printed_output_survives_a_raise`.
   A three-case group —
   raise under a handler, `try` with nothing raised, and `return 1` — is enough,
   and it belongs beside `test_formal_link_accounting.py`, which is the
   gate-resident file that already owns "does the thing this claim names exist".