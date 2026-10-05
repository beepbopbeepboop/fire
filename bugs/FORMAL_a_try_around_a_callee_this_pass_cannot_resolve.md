# A `try` around a callee this pass cannot RESOLVE is not asked whether that callee raises

**Area:** FORMAL, `formal/model.py`'s `RaiseGraph` (the refusal that stops a
`try`-around-a-raise from building is `uncatchable_raise` /
`refuse_uncatchable_raise`), both backends. **Status: OPEN, filed 2026-10-05
with the fix that closes everything else in this class, and NOT fixed here —
the fix's own measurement is why this is a doc and not a conservative `or`.**

## What is closed, and what this is

A `raise` is not an exception on this path: `_emit_diverge` flushes the pending
`finally` clauses and traps with `exit(1)`, from whatever function holds the
statement. So no frame anywhere can catch one, and a `try` with arms whose body
can reach a raise is a program whose statements after the `try` are missing
from the image. That is refused, through the module's own call graph, and it is
why `try: boom() / except: pass` around a raising `boom()` stopped building and
printing nothing:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/exc4.arm64 .tmp/exc4.mojo
build: the `try` body calls `boom(…)`, which can end the process, and the arm
written as a bare `except:` cannot catch it, so the `try` is refused rather than
silently ignored: …
```

`RaiseGraph._callee_raises` answers `False` for a callee it cannot place. This
doc is about that `False`.

## The measurement, which is why it is not conservative

Asking "can this `try`'s body reach a raise" over this repository and the
stdlib, parse-only and with no codegen (the question is a walk, so this is the
whole cost):

| roots | files scanned | refused |
|---|---|---|
| this repository (`.py` + `.mojo`) | 479 | **39** |
| `../new-modular/Mojo/stdlib/std` | 252 | **4** |

and splitting those 43 by the EVIDENCE for the hit:

| evidence | repo files | what it is |
|---|---|---|
| a `raise` written inside the `try`'s own region | 5 | certain |
| a resolved callee this module declares, which reaches a raise | 34 | certain |
| an UNRESOLVED callee (no definition here, no C prototype, or a callee that is an expression) | **82** | a possibility |

**82 against 34 is the whole decision.** Nearly all of the 82 is ordinary
Python: `try: … except OSError:` around `dict.get`, `Path.is_file`, a hostmod
entry point, a `subprocess` call — a module that has a `raise` somewhere and a
`try` around something this pass cannot resolve. Refusing those buys a
*possibility* at the price of five times as many files as the certain answer
takes, and every one of the 43 certain files is **already refused for another
reason on this tree** (25 of the 25 repo files absent from the b11 sweep log
build with `uncatchable_raise` monkeypatched to `None`, and fail on an import:
`fire_compiler`, `formal.build`, `collections`, `socket`; the 4 stdlib files are
behind the export gate). So the certain tier costs **zero files** and the
possible tier would cost most of a corpus's coverage for a hazard nobody has
measured.

## The hazard, stated as the thing to measure

An unresolved callee is one of:

* a **host-module entry point** — `formal/hostmods/*.mojo` are Mojo compiled by
  this backend, so a `raise` inside one is `exit(1)` inside that dylib and no
  frame of the caller's image can catch it. Nine hostmods have both a `raise`
  and an `except` today (`tempfile`, `pathlib`, `subprocess`, `ctypes`,
  `contextlib`, `os/_syscalls`, `os/path/__init__`, `os/__init__`, `glob`);
* a **function in another module of the same image**, reached through a dylib
  import or a module-qualified call (`mod.f(…)`) — same argument;
* a **bare C symbol with no entry in `BARE_C_RETURN_KINDS`** — this one cannot
  raise into our frame at all (C has no unwinder of ours to unwind into), so it
  is harmless and would only be refused by accident.

So the question a taker has to answer is per-callee and decidable: **does this
callee, or anything it calls, end the process?** Nothing in the tree asks it
across a module boundary, and the answer is not available where the refusal is
asked: `RaiseGraph` is built in `formal/build.py::_prepare_functions` from ONE
unit's function list, and by then the other units have been parsed and thrown
away.

## The exact next step

1. **Publish the answer per module, next to the module's symbols.**
   `formal/build.py` already calls `M.publish_module_symbols(symbols)` and
   re-publishes after a nested import build (the docstring there explains why
   the published copy is not durable). A second published table — module name →
   the set of its function names that can reach a raise — is the same mechanism
   and the same re-publish rule, and it makes `RaiseGraph`'s unresolved branch
   answerable for a `mod.f(…)` call by asking the module rather than the caller.
   `formal/imports.py` is the other candidate owner, and it is where the
   resolution of a module name to a unit already happens.
2. **Then host modules.** A hostmod is a dylib built from the same pipeline, so
   step 1's table covers it — provided the call is resolvable to a module name
   (`os.stat` → `os`, `pathlib.Path.is_file` → `pathlib`), which is a hostmod
   name table rather than a call-graph question.
3. **Keep the two-tier shape.** The certain tier stays as it is (it is the one
   that closed the bug); the possible tier switches on when step 1 can answer,
   and until then the residual is this doc rather than a refusal. Re-run the
   census above when it does: the number to watch is 82 falling towards 0 with
   the certain 43 unchanged, and the corpus cost staying at zero files.
4. **The measurement nobody has taken, and it is the cheap one**: build one
   hostmod program whose try-arm is reachable — `formal/hostmods/os.mojo`'s
   `makedirs` is in the repo's own census for exactly this shape — and see
   whether the image's answer differs from CPython's. If it does, this is a live
   wrong-program class and the tiers should be re-thought; if it does not, the
   residual is as narrow as it looks.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
# the census (scratch, not committed): parse every file, ask the two model
# questions, build nothing
python3 tools/memslot.py --gb 8 --label t -- python3 .tmp/census_raise.py .
python3 tools/memslot.py --gb 8 --label t -- python3 .tmp/census2.py .      # by evidence
python3 tools/memslot.py --gb 8 --label t -- python3 .tmp/census_raise.py \
      ../new-modular/Mojo/stdlib/std
# the cost of the certain tier: 25 repo files the b11 log does not classify,
# each built with the refusal disabled
while read -r f; do python3 tools/memslot.py --gb 8 --label t -- \
    python3 .tmp/build_nocheck.py build --formal --no-prove --backend=arm64 \
    -o .tmp/f5/x.bin "$f"; done < .tmp/absent25.txt
grep -rl "raise " --include="*.mojo" formal/hostmods | xargs grep -l except
```
