# FORMAL_no_exceptions: a `raise` is a TERMINATION on this path, not a value the caller can catch

**Status 2026-10-08 (`work/formal193-docs`): the RULE below is unchanged and
still load-bearing; two of the three MEASUREMENTS under "What I ran" are stale,
and the third has been fixed elsewhere. Read this before that section.**

- **(a) a `raise` under a handler with a body is now REFUSED, not run.** The
  program that printed nothing and exited 1 is now refused by NAME on both
  backends — *"a bare `except:` is a handler arm with a body this path cannot
  put in the image"* — which is the refusal this doc's rule argued for: the
  arm's effects would be silently missing from the image. Pinned by
  `test_formal_exceptions.py`'s three `an_except_..._is_refused_by_name` rows.
- **(c) the same `try`/`except` with a body is refused too, whether or not
  anything is raised**, so the program that measured "`try` is lowered and
  works" no longer runs. The positive half survives in the same file as
  `an_except_pass_arm_still_builds` and `else_runs_when_the_body_completed`.
- **(d) the arm64 flush divergence is GONE.** `raise 7` after a `printf` now
  prints `before@@` and exits 1 on arm64 as it always did on x86-64 — measured
  this session on both backends — so the doc's pointer to
  `bugs/FORMAL_raise_skips_the_stdio_flush.md` is that doc's and has been
  fixed there. Every `raise` row in `test_formal_exceptions.py` compares stdout
  to CPython, so a regression to the lost flush fails them.

**So next step 3 ("pin the behaviour so a backend change cannot quietly alter
it") is DONE, and by the exception work this rule predicted:**
`test_formal_exceptions.py` is the test the closing paragraph below said was
missing. It covers the uncaught contract, the `finally` contract and the
refused-arm contract on both architectures. Steps 1 and 2 — one shared
return-convention and an EH runtime — are unchanged and are not this update's.
Read the rest of this file as the record of 2026-09-30, with the three
measurements above corrected.

**Status:** open, and it is a LIMIT OF THE TARGET rather than a defect — but it
is load-bearing for every module under `formal/hostmods/`, and until it had a
document `formal/hostmods/json.mojo` cited a file that did not exist. Found
2026-09-30 while auditing the cross-references of the second host-module wave;
the measurement below is new, the behaviour is old.

**Why a document rather than a line in a module docstring.** Four modules now
answer the same question differently because of this, and each had to invent its
own wording: `os.makedirs` is CPython's `makedirs(path, exist_ok=True)` with no
spelling of the other one (`formal/hostmods/os/__init__.mojo`), `json` spells
"this document is malformed" as a return value rather than a `JSONDecodeError`,
and `hashlib` spells "these inputs disagree" as a status. A reader who has not
internalised the rule will read each of those as an approximation of CPython
and "fix" it into a raise. The rule belongs in one place, and the place is a
document every one of them can cite.

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
the `except` arm did not run and `after` did not either. **The lost `before` is
a separate defect with its own document** —
`bugs/FORMAL_raise_skips_the_stdio_flush.md` — and it is why this program's
output is empty rather than `before`.

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
   no test in the tree that raised on this path, which is why the arm64 flush
   divergence in `bugs/FORMAL_raise_skips_the_stdio_flush.md` sat unnoticed
   through both backends and both host-module waves. **DONE 2026-10-08**: the
   three-case group is `test_formal_exceptions.py`, which raises on this path,
   compares stdout to CPython and so pins the flush, and refuses a handler arm
   with a body on both backends. The doc's old pointer to
   `test_formal_link_accounting.py` was where the next test was expected; the
   exception contract's own file is where it landed.