# The trust boundary audited: every admitted contract, every `sorry`, every axiom

**Status: the audit is DONE and its findings are FIXED. What is left is written
down at the end** — one axiom census that needs a Lean run, and one limit of the
scope rule. This file is the table; it is kept because the audit is a reading of
the tree that nobody can re-derive for free, and because a reading with a
measurement beside it is what made the fifteen corrections possible.

Claim: `sweep20:admitted-audit`. Not one of the eight `formal19` FORMAL docs.

## What was audited, and what "the boundary" is

Three kinds of thing in this tree rests on something unproved, and they are not
the same kind of thing:

1. **the HOST** — `formal/admitted.py`'s `@admitted(...)` declarations in
   `formal/hostmods/`. Each becomes one `def admitted_<module>_<name> (req :
   UInt64) : UInt64 := sorry` in every generated proof whose file depends on it.
2. **GENERATED PROOFS** — the `sorry`s a generator emits, `formal/x86_64_proof_gen.py`
   and `formal/arm64_proof_gen.py`'s `_decide_or_admit` among them.
3. **the Lean MODEL** — `lib/*.lean`, which every generated proof rests on, where
   an unproved step is an `axiom`/`opaque` declaration, a `sorry`, or a tactic
   whose proof term reaches an axiom.

(1) is this project's own machinery and was the subject. (2) is enumerated below
with the bug doc that owns each site and was NOT touched. (3) had no census at
all, and the audit added one.

## Why the audit was needed: nothing asked whether an assumption was TRUE

`formal/admitted.py` had four instruments and every one of them was about form:

| instrument | what it decided | what it cannot decide |
|---|---|---|
| `counts_by_module` + `ADMITTED_COUNTS` | how many admissions there are | whether any of them is true |
| `contract_text_is_scoped` | the text constrains the ANSWER, not the host's behaviour | whether the answer is the one the host gives |
| `lean_declarations` | one countable `sorry` per contract | whether the statement is a true statement |
| `test_a_file_that_reaches_none_generates_no_hole` | the change is inert where nothing is admitted | anything about a file that does admit |

Fourteen of the nineteen contracts were false or true-only-under-a-narrower-
reading, and all four instruments were green on every one of them. That is not a
bug in any of the four; it is the shape of what each was built to decide. The
audit's first change is therefore a fifth instrument — `test_formal_admitted.py`'s
`truth` group — plus the rule that a contract cannot land without one.

## The table: 19 contracts, 19 probes

Verdicts are measured against CPython/the OS by that group; "false" means the
admission asserts something the host does not do, and every row's probe is named
so the measurement can be repeated.

| # | contract | assumed (pre-audit wording) | verdict | how it was measured |
|---|---|---|---|---|
| 1 | `subprocess.run` | "the child's exit status, an integer in 0..255, and the captured output bytes are an arbitrary byte string" | **FALSE** | `run(["/bin/sh","-c","kill -9 $$"]).returncode` is `-9` |
| 2 | `subprocess.call` | "the child's exit status, an integer in 0..255, and nothing is raised for a non-zero status" | **FALSE** | `call(["/bin/sh","-c","kill -TERM $$"])` is `-15` |
| 3 | `subprocess.check_call` | "the child's exit status, an integer in 0..255" | **FALSE**, and the word is not CPython's | CPython returns **0** on success (`return 0` in `subprocess.py`) and raises `CalledProcessError` otherwise; it never returns a status |
| 4 | `subprocess.check_output` | "the child's output on stdout, an arbitrary byte string" | **FALSE of the model** | `check_output(["/bin/sh","-c","printf 'a\\0b'"])` is three bytes; a `str` here is a NUL-terminated `char *` |
| 5 | `subprocess.getoutput` | same | **FALSE of the model** | `getoutput("printf 'a\\0b'")` contains a NUL |
| 6 | `subprocess.getstatusoutput` | "the shell command's exit status, an integer in 0..255, and its output is an arbitrary byte string" | **FALSE** | `getstatusoutput("/bin/sh -c 'kill -9 $$'")` is `(-9, '')` |
| 7 | `subprocess.Popen` | "the child's process id, a positive integer" | **TRUE** — unchanged | `Popen([...]).pid` is a positive int distinct from `os.getpid()` |
| 8 | `subprocess.popen_wait` | "the child's exit status, an integer in 0..255" | **FALSE** | a `SIGHUP` death is reported as `-1` |
| 9 | `subprocess.popen_poll` | "the child's exit status word, an integer in 0..255, and -1 while the child has not been collected" | **FALSE twice** | CPython answers `None` while running, and reports `-1` for a `SIGHUP` death — so the sentinel collided with a real answer |
| 10 | `subprocess.popen_kill` | "the signal reaches the child this handle names" | **FALSE as stated** | `Popen.send_signal` polls and RETURNS once the child is collected: `kill()` after `wait()` sends nothing and raises nothing |
| 11 | `subprocess.popen_terminate` | same | **FALSE as stated** | same row, `SIGTERM` |
| 12 | `subprocess.popen_communicate` | "the child's output on stdout and stderr, an arbitrary byte string" | **FALSE of the model** | `communicate()` returns a PAIR, and each half can hold a NUL |
| 13 | `ctypes.cdll_open` | "the loader handle is 0, meaning no library of that name is on this target, or a non-zero word this target's dynamic loader owns" | **FALSE** | a file that EXISTS and is not a loadable image makes `dlopen` fail: `OSError: slice is not valid mach-o file` |
| 14 | `ctypes.cdll_call` | "the value the foreign function returns is one word, and nothing is assumed about which value it is" | **FALSE without the default `restype`** | `lib.getpid.restype = None` answers `None`; a struct-returning foreign function has no word |
| 15 | `concurrent.futures.executor_submit` | "the submitted callable runs on some thread and its result is one word" | **FALSE for `ProcessPoolExecutor`** | the callable reports its own pid and it is not this process's |
| 16 | `concurrent.futures.executor_shutdown` | "every thread the pool started has stopped by the time this returns" | **TRUE only of the pool's OWN workers** | a thread a submitted callable started is still running when `shutdown(wait=True)` returns |
| 17 | `threading.thread_start` | "the thread exists and has run the target callable" | **TRUE only under one reading** | `start()` returns before a 0.4 s callable finishes, so it has BEGUN |
| 18 | `threading.thread_join` | "the thread has stopped" | **TRUE of `join()` with no timeout** | `join()` returns after the callable finishes; `join(0.01)` does not |
| 19 | `threading.lock_acquire` | "the lock is held by the kernel on a descriptor, and whether it is granted depends on every other holder" | **FALSE** | `threading.Lock` has no `fileno` and no `_handle`; a CHILD PROCESS took `fcntl.flock(LOCK_EX)` while this one held the lock |

**15 false, 3 true only under a reading the audit had to choose, 1 true.**

Every text is now the measured truth, and each carries a probe. The three that
were true got tighter wording rather than a correction, and `subprocess.Popen` is
unchanged — the pre-audit sentence for it is deliberately absent from
`PRE_AUDIT_TEXT`, because a row asserting a complaint about a true contract
would be asserting something false about the toolchain.

### What is NOT admitted, and stayed out of it

`subprocess`'s argument shapes, constants, `check_returncode`, `validate_run`,
`validate_check_output` and its three field constructors; `ctypes`' 13 sizes and
8 conversions/refusals; `fcntl`'s 11 flags (and `flock` itself — it is DECIDED,
so `fcntl` admits nothing and did not stop being in §7a's table by accident);
`concurrent.futures`' 15 state decisions; `threading`'s `TIMEOUT_MAX` and timeout
check. Those were already differential-tested against CPython and the audit found
nothing to add; they are listed here because "what was checked and found clean"
is half of an audit.

## The refusal marker: `ADMITTED_EXIT_STATUS = 125`

The most-read claim in the mechanism was false, in four hostmod docstrings, in
FORMAL.md §7a rule 5 and in two test messages:

> 125 is outside `0..255`, so it cannot be read as a child's exit status.

Both halves are wrong, and both are one line to measure:

```
$ python3 -c "import subprocess; print(subprocess.run(['/bin/sh','-c','exit 125']).returncode)"
125
$ python3 -c "import subprocess; print(subprocess.run(['/bin/sh','-c','exit 300']).returncode)"
44
```

125 is **inside** the range, and **no exit code can be outside it** — the kernel
masks one. So the number never had the property the comment claimed, and no
number could have. What 125 is for is narrower and now stated: it is nonzero, so
a caller sees the image did not answer, and it is reserved by this tree. What
identifies a refusal is the diagnostic `_admitted` prints on stdout, which every
admitted call does and which both test groups assert.

`group_runtime` now measures both facts on every run, and `group_truth`'s
`_exit_status_claims` walks the source window after each `ADMITTED_EXIT_STATUS`
declaration and refuses a sentence that puts "outside" and "0..255" together
without a word that makes it a correction — so the corrected text can quote the
false one, and the false one cannot come back.

## `lib/*.lean`: no `axiom`, no `sorry`, and 749 sites that are not kernel-checked

FORMAL.md §7 opens with *the project has no Lean `axiom` and no `opaque`
anywhere; everything is assumed in the `sorry` sense*. Measured on `lib/` with
`formal/admitted.py::library_trust` (comments and string literals stripped first,
so the count is sites and not mentions):

| module | `axiom`/`opaque` | `sorry` | `native_decide`/`bv_decide` |
|---|---|---|---|
| `Contracts` | 0 | 0 | 1 |
| `ProofLib` | 0 | 0 | 744 |
| `Refine` | 0 | 0 | 0 |
| `X86` | 0 | 0 | 4 |
| `work` | 0 | 0 | 0 |

The first two columns make §7's position true and are now pinned as hard
equalities, and the third vacuity shape — a declaration that asserts nothing — is
pinned at 0 for `lib/` **and for the emitted `admitted_*` declarations**, read
through `formal/lean.py::vacuous_declarations` over the comment-stripped text. The third is the finding: `native_decide` and `bv_decide` close a goal
by compiling and running a decision procedure, so their proof terms reach Lean's
`Lean.ofReduceBool` axiom and `#print axioms` reports it. `OPUS.md` §1 already
says this about a generated theorem ("plus the project's usual
`native_decide`/`bv_decide` step-lemma axioms"); §7's inventory had no row for
it, which made the largest admitted assumption in the model the one nobody could
see.

This is not a hole and it is not a bug: neither tactic can prove a **false**
statement, because it evaluates and answers. It moves WHERE the trust sits — from
the kernel to the generated C code and the C compiler — and that is why a
1.4M-step simulation finishes at all. §7 now has a row for it, the count is
pinned as a **ceiling** (a debt being paid down, in a file several branches edit
at once; an equality would turn every unrelated merge into a failure), and the
replacement plan is `bugs/FORMAL_native_decide_axiom.md`.

### Generated proofs: every `sorry` the generators emit

Enumerated for completeness and **not** changed — each belongs to another
worker's claim:

| site | what it admits | owner |
|---|---|---|
| `formal/arm64_proof_gen.py:5619, 5811, 5819, 6542, 6549, 6627, 6643, 6878` | `all_goals (first \| done \| sorry)` — CFG leaves | `bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` |
| `formal/arm64_proof_gen.py:9737` | a call through a callee the model has no `_go` for | `FORMAL_contract_work_handoff.md` |
| `formal/arm64_proof_gen.py:10496` | a caller theorem whose callee is admitted | this file's §"what depends on a contract", below |
| `formal/x86_64_proof_gen.py:332, 920` | the extern-call step, `True := by trivial` | FORMAL.md §7 rows 4–6 |

## What depends on a contract, and whether it is silent

Generated for a program whose body is `return subprocess.run(0)` (a literal, so
the model's string table does not refuse it first), on arm64:

```
18 sorry:  12 x `def admitted_subprocess_<name>`   (the contracts)
            5 x `theorem eval_eq_mojo_{0,1,2,5,test}` (the two model layers agree)
            1 x `theorem main_post_extern_given_callee_returns`
```

Only one theorem is a statement about the **machine**:

```lean
theorem main_post_extern_given_callee_returns :
  run_result_exit { main_pre_0 with pc := 4294968660 } main_code 4294968773 200000 = mojo 10 := by
  sorry
```

and `mojo` is the model that calls `admitted_subprocess_run`. So the whole
end-to-end claim for such a file rests on the contract, and it is **not silent**:
`_admitted_model_note` puts `GIVEN the admitted host contract(s) `subprocess.run`
above: this is a claim of TRUST, not a proof` in that theorem's own docstring,
and `formal/lean.py`'s census counts all 18. The five `eval_eq_mojo_*` theorems
are equalities between two representations of the same model, both defined
through the same admitted declarations, so they inherit the admission rather than
a falsity.

### The same file on x86-64

The whole mechanism is shared, so the correction reaches both backends from one
edit — `formal/x86_64_proof_gen.py::_admitted_lean` calls
`formal/admitted.py::lean_declarations` rather than writing its own.  Verified by
generating the same program on x86-64: 14 `sorry`s, being the same 12 contract
declarations and two theorems — `main_compile_correct` and
`main_compiles_correctly` where arm64 has the extern-step theorem and the five
`eval_eq_mojo_*` layers — and the corrected text, the `THE WORD IS THE MODEL'S`
clause and the real `subprocess.mojo:471`-style line numbers are all in that
file's Lean too.  Nothing here is arm64-only.

That is the important distinction for this audit: **a false contract does not make
a generated theorem false** — `admitted_subprocess_run` is unconstrained, so
`mojo 10` is whatever it is and the statement is an equality between two things
that agree by construction. What it does is leave a theorem whose justification
is a sentence that was false, published in a `trust:` line, in the generated
Lean's docstring, and in FORMAL.md's inventory. Fifteen of those sentences were
false. They are now true, and each is re-measured.

## What was changed, and what each change is pinned by

- all 19 `@admitted` texts; `truth` group, one probe per contract, and
  `every admitted contract has a truth row` so a contract cannot land without one
- `POLL_NOT_COLLECTED = -65`, a new decided constant in `subprocess.mojo`, with
  the argument for its value in its docstring
- `ADMITTED_EXIT_STATUS`'s four docstrings and `group_runtime`, which now measure
  that a child can exit 125 and that the OS masks 300 to 44
- `Contract.docstring()` gained `THE WORD IS THE MODEL'S` — **stamped in one
  place, not written nineteen times**: for most of these operations CPython
  returns `None`, a `Popen`, a `CompletedProcess`, a pair, a `Future` or a
  `bool`, so the `UInt64 → UInt64` declaration is a claim about the MODEL's
  answer and a reader who takes it for CPython's return type is reading a
  different claim. The decorator stays the only place an ASSUMPTION is written.
- `Contract.line`, which was 1 for all nineteen; now recovered from the source and
  checked by `every contract points at its own declaration`
- `formal/admitted.py::library_trust` / `lean_code_regions` /
  `library_trust_lines` — the census of §3 above, with the scanner's own limits
  asserted (no `"""` literal in `lib/`, no `exact_decide`/`implemented_by`/
  `unsafe`) so it cannot quietly stop counting
- `model_const` folds a unary minus, because `POLL_NOT_COLLECTED` is negative and
  `int(getattr(node, "value"))` is `None` for a `UnaryOp`
- FORMAL.md §7 preamble, row 8, new row 10, §7a rule 5, and §7a's per-module
  table — which said 15 contracts across five modules and `subprocess` 7 /
  `fcntl` 1, against 19 across four and 12 / 0. Nothing checked it;
  `test_the_formal_md_inventory_agrees` now reads the document and fails in both
  directions.

## Not fixed, and why

- **`contract_text_is_scoped` has a hole, and it is not a phrase list away.**
  `ctypes.CDLL`'s admission carried "meaning no library of that name is on this
  target" and the module's own docstring claimed the scope rule refuses such a
  text. It does not: the seven banned phrases are all behavioural adverbs, and a
  claim about the host's filesystem attached to a VALUE (`0` "meaning" …) is
  grammatical and passes. The text is fixed here; closing the rule needs a
  structural notion of "the claim is about the answer" rather than a longer word
  list, and guessing at it would reject sentences that are fine. Filed as
  `bugs/FORMAL_contract_scope_rule_is_a_phrase_list.md`.
- **The axiom census that needs Lean.** `library_trust` counts SITES in the
  source; `#print axioms` measures which theorems actually reach
  `Lean.ofReduceBool`, and that is transitivity no text scan can do.
  `bugs/FORMAL_native_decide_axiom.md` carries the command. Not run here: this
  worker does not launch Lean.

## Two surprises worth recording

- **`subprocess.check_call` does not return `None`.** It returns **0**
  (`return 0` at the end of `check_call` in CPython 3.14's `subprocess.py`) and
  raises `CalledProcessError` otherwise. The obvious answer — `None`, from the
  docstring's "then return" — is wrong on the toolchain this tree runs, and the
  audit's first correction of that contract introduced the wrong claim before the
  probe caught it. **A version-drift lesson: "returns nothing" is not a safe way
  to say "returns None".**
- **`kill()` after `wait()` does not raise.** CPython's `Popen.send_signal`
  calls `poll()` and returns early once `returncode is not None` ("Skip
  signalling a process that we know has already died"), so the obvious probe for
  "is the signal delivered" — catch `ProcessLookupError` — passes on a host that
  delivers nothing. The row therefore reads CPython's own source, which is the
  only evidence that distinguishes the two.