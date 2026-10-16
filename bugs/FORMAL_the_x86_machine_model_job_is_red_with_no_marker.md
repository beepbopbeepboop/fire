# `formal-x86-machine-model` is RED with no `expect=` marker, and the registration comment says it is red for a reason that is no longer true

**Area:** FORMAL (the x86-64 model-vs-hardware differential). Found 2026-10-05 on
`work/formal69-docs`, while verifying a `lib/X86.lean` change against the only
check that executes the model against a CPU.

**Status: OPEN, measured, and NOT one of my claims — reported rather than fixed.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label x86mm -- python3 formal/x86_64_model_test.py
  accum_max      NO-RUN at input 0
  printf_int     NO-RUN: the model stopped before returning
  str_len        NO-RUN: the model stopped before returning
x86-64 model vs hardware: agree 91  WRONG 0  NO-RUN 3  build-fail 0  (of 93)
memcap: done, peak 1.7 GB across up to 2 procs (ceiling 8.0 GB), child exit 1
```

`exit 1` with **zero** `WRONG` rows. The three failures are all `NO-RUN`: the
model stopped before returning, which is `x86_exec_exit` answering `none` — it
hit a byte it cannot step, or it ran out of fuel.

## Why this is a bug about the REGISTRY and not about the model

`tools/suite.py` registers the job with **no `expect=`**:

```python
test('formal-x86-machine-model', [PY, 'formal/x86_64_model_test.py'],
     deps=['preflight', 'prooflib'], mem='tiny',
     extra=['formal/x86_64_model_test.py', 'formal/x86_64.py', 'lib/X86.lean'],
     desc='lib/X86.lean EXECUTED against the hardware it models, every example')
```

and the comment above it says

> It is RED, and deliberately `expect=`-marked rather than left unregistered:
> `udivmod` disagrees with the hardware (real 4, model 7905747460161236410).

**Both halves of that are now false.** The job carries no marker, and `udivmod`
is not among the failures — it is one of the 91 that AGREE. So the comment
describes a state that has passed, and the job is an **undeclared red of a
registered job**, which is the shape `CLAUDE.md` calls the expensive kind of red:
a reader of the registration learns that the model disagrees with the hardware on a
divide, and a reader of the run learns that three programs cannot be executed at
all. Neither is what the tree's state is.

The census that would show this is `python3 tools/suite.py --list`, and it shows
the job with no `expect=` — that is the honest half; the other half is that the
run is red.

## The three `NO-RUN`s, and which of them are a known gap

Two of the three are named by the tree already, and one is not:

| example | the diagnostic, read off `formal/x86_64_endtoend_test.py::_plan` | is it a known gap |
|---|---|---|
| `printf_int` | `no step lemma wired for: movsxd_r64_r32` | **not recorded anywhere** — the decoder names the form, `lib/X86.lean` steps it (`op = 0x63`), and the ISA census counts it covered |
| `str_len` | `body does not decode` | `formal/x86_64_instruction_coverage_backlog.md`'s Shape 1 (the nine SSE2 scalar binary64 forms have no decoder arm), which is why a `printf`-shaped program cannot be walked |
| `accum_max` | `_plan` succeeds — it has a tree | **not recorded**: it plans and builds, so its `NO-RUN` is a different thing, and it is the one to look at first |

`accum_max` is the interesting one because it is not a naming gap: the plan is
fine, so the model stops at a byte the plan accepted — which means the DECODER
(`formal/x86_64_decode.py`, used by the emitter's `_plan`) and the MODEL
(`lib/X86.lean`'s `x86_step`, which is what actually ran) disagree about what is
decodable, or the run ran out of fuel. Those are different defects and the
report's single `NO-RUN` line does not say which.

## The next step

1. **Decide the registry question, which is one edit.** The job is red, so it
   either gets an `expect=` with a reason, or it gets fixed. It cannot stay as it
   is: a comment saying "RED, deliberately `expect=`-marked" beside a
   registration with no marker is a claim about the tree that is not true, and
   the first thing a reader does with it is trust it.
2. **`accum_max`, with the fuel number printed.** `formal/x86_64_model_test.py`'s
   `NO-RUN` line does not report how much fuel `x86_exec_exit` had or how many
   steps it took, so "stopped before returning" cannot be told from "the model
   cannot decode this byte". Printing the last address it reached would make the
   three rows here decidable in one run each, and it is the same information
   `formal/x86_64_endtoend_test.py`'s `_tree` computes (`by_addr`/`_leaf_halts`).
3. **`movsxd_r64_r32`** is the one form in this table that no document names, and
   the shape of that gap is written up as the "fourth shape" in
   `bugs/FORMAL_x86_64_instruction_coverage_backlog.md` — decoded, stepped,
   sampled, and (here) unreachable by the prover. A step lemma plus a successor
   row is the fix, and `formal/x86_64_endtoend_test.py::_plan` is how you see
   that it is needed.

## Reproducing

```console
$ python3 formal/x86_64_model_test.py          # exit 1, 91 agree / 0 wrong / 3 NO-RUN
$ python3 tools/suite.py --list | grep -A2 formal-x86-machine-model
$ grep -n "formal-x86-machine-model" -B 8 tools/suite.py | head -20
```