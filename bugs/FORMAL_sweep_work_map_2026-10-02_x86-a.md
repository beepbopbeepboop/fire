# FORMAL_sweep_work_map_2026-10-02_x86-a: x86-64 sweep of this repository's own sources — 61.1% codegen coverage, ONE x86-64-only finding, and two defects the census cannot see

**Status: COMPLETE for the slice (`sweep:x86-a`), with two x86-64 codegen
fixes landed and two bug docs filed.** This is the x86-64 half of the
2026-10-02 sweep pair; `formal4-sweep-x86-b` has the stdlib half, and
`formal4-sweep-repo-a/b/c` have the arm64 repository half. Read §4 before
working any row: **15 of this slice's 16 in-file findings are arm64 findings
with byte-identical messages**, so almost nothing here is an x86-64 problem,
and the one that is already has a doc, a claim and a measured next step.

## 1. The run

    /opt/homebrew/bin/python3 tools/memslot.py --gb 8 --label sweep-x86a -- \
      /opt/homebrew/bin/python3 tools/formal_sweep.py -j 6 --arch x86_64 \
      --no-stdlib --allow-concurrent

392 files (this repository's own `*.py` / `*.mojo`, stdlib excluded), `-j6`,
`-t 30`, 4 GB per-file ceiling, peak 0.9 GB across 20 processes, exit 1 (the
sweep's own "there were findings", not a crash). `--allow-concurrent` because
the x86-b worker held the architecture lock; two x86-64 sweeps at once is what
that flag is for, and no `json.decoder.JSONDecodeError` appeared in the
`tool` class.

**The interpreter is not optional and the tool now says so.** The first attempt
ran under the `python3` a login shell finds by default — Apple's 3.9.6 — and
classified **392 of 392 files** as `backend-crash` with one repeated line
(`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` from
`formal/model.py:1668`'s `-> str | None`), i.e. "no file was built at all",
reported as the worst class in the tool. `tools/formal_sweep.py` now refuses to
start on an interpreter that cannot import the backend (exit 2, before the
scope is announced), with two cases in `test_formal_sweep_truth.py`.

Two restarts, for the record: at `-j2` the run classified 98 files in nine
minutes and was restarted at `-j6` (the second run's first process died without
a summary, so it was restarted again; the CAS is why the restarts were cheap).
The numbers below are the final complete run, extracted from the log as
`.tmp/sweep-x86-final.txt`.

**One observation from this run's own concurrency, recorded because it cost this
session an hour and would cost the next one the same.** Other workers were
running same-architecture sweeps throughout (`ps` showed 20+ `formal_sweep`
processes machine-wide), which is what `--allow-concurrent` permits and what
both backends' `~/.gmojo/cas/formal-imports/<arch>/` directory is not safe for.
Between roughly 03:50 and 04:20, eight hand-written probe programs built
successfully and answered **0** where the source says 101, 103, 213, 73, 21, 7,
203 and 7 — and the SAME programs, rebuilt afterwards, answer all eight
correctly. No refusal, no stderr, exit 0: a **silent wrong answer**, where the
documented failure mode for that race is a loud `json.decoder.JSONDecodeError`
in the `tool` class (`bugs/FORMAL_sweep_tool_json_decode_error.md`, superseded
by `FORMAL_dylib_manifest_written_in_place.md`, which is on another branch and
not in this tree). **Not reproducible on demand** — it did not recur once this
worker stopped sharing the directory — so it is filed here as an observation
rather than as a bug doc, and it is the reason every number in §5 below was
re-measured serially with the sweeps stopped. A probe-based comparison of two
backends should assume it can produce wrong answers while another same-arch
sweep runs, and should re-run anything surprising before believing it.

**One caveat a reader must have before comparing this map with an older one:**
the `_criteria_id()` in every cache key is a hash of `tools/formal_sweep.py`
itself, and the interpreter guard changed that file. This run's verdicts were
published under the pre-guard id, so re-running the sweep today recomputes all
392. No classification rule changed — the guard runs before the first build —
so the classes and the coverage number are the ones a re-run reports.

## 2. Class counts

| class | files |
|---|---|
| pass | **88** |
| codegen (in this file) | 24 |
| codegen/dependency | 32 |
| not-answerable/host-import | 83 |
| not-answerable/unresolved-import | 1 |
| not-answerable/unresolved-extern | 2 |
| not-answerable/target-limit | 3 |
| tool | 159 |
| **codegen coverage** | **88/144 = 61.1%** |

`cas: 2 hit / 390 miss / 0 not cached`. 152 of the 159 `tool` rows are
`timeout (> 30s)` and 7 are the cross-architecture dlopen limit ("this arm64
host cannot check whether their imports resolve"), so **41% of the slice got no
verdict at all** — almost all of it the big top-level `.py` modules
(`fire.py`, `myinterpreter.py`, `mojo/backend_gimple/*`), which are both slow
and, when they do finish, `not-answerable` on their imports. The headline is
therefore mostly a statement about this repository's own Python sources, which
are host modules by construction; the x86-64 stdlib half
(`bugs/FORMAL_sweep_work_map_2026-10-02_x86-b.md`) is the number with real
coverage in it.

## 3. Ranked causes (`tools/formal_sweep_causes.py --min 2`)

48 of the 56 `codegen` / `codegen/dependency` lines accounted for, in 6 causes
of 14. **FILES BLOCKED is an upper bound**: a file's terminal cause is the first
refusal its build walk reaches, so fixing one moves it to the next with the
count unchanged.

| files blocked | in-file | cause | owner / next step |
|---|---|---|---|
| **32** | 5 | a local read before its first assignment | `FORMAL_a_local_read_before_its_first_assignment` (claim `formal3-1-r2`). 26 of the 32 are the single name `pend` in `formal/hostmods/re.mojo:1401`, and the tool measures that 21 of the 25 files behind it name nothing `re.mojo` declares — so the row's value is `re.mojo` itself plus `formal/arm64.py`'s `sym_name` (3), not the 25 |
| 6 | 1 | too many parameters for the register ABI (8 arm64 / 6 x86-64) | `FORMAL_x86_64_argument_registers` (claim `formal3-9-r2-r2`). The single in-file row is `formal/hostmods/fnmatch.mojo` — **the only x86-64-only finding in this slice** (§4) |
| 3 | 3 | a module-global name has no storage | `FORMAL_module_state_no_storage` (claim `formal3-5`). `ELF_MAGIC` in `formal/elf.py`, `_MSL_FLOAT_TYPES` in `mojo/middle/metal_ops.py`, `REPO` in `tools/bootstrap_verify.py` |
| 3 | 3 | a module's ATTRIBUTE read as a value (`sys.argv`) | `FORMAL_module_state_no_storage`, "What is left" (claim `formal3-5`) — `t_argv.mojo`, `tools/ci_line.py`, `tools/detach.py` |
| 2 | 2 | `print()` cannot classify the argument's type | **unowned and NOT x86-specific** — arm64 refuses the same two files with the same words except "arm64" for "x86-64". The arm64 repository sweep (`sweep:repo-a/b/c`) is the natural owner; a lowering decision, not a wrong answer |
| 2 | 2 | a linked module exports no such name (`sys.exit`) | not attributed; the closest doc is `FORMAL_per_export_contracts` / `FORMAL_module_exports_nothing` (claim `formal3-5`) |

## 4. arm64 versus x86-64 on this slice: one file, and it is owned

Every one of the 16 in-file `codegen` files was rebuilt on **arm64** (a
16-file `--arch arm64 --no-stdlib` sweep, same tool, same tree, log
`.tmp/sweep-arm-cmp.log`):

| | files |
|---|---|
| both architectures refuse, **same construct and same message** | **15** |
| **x86-64 only** | **1** — `formal/hostmods/fnmatch.mojo` |
| arm64 only | **0** |

```
$ python3 fire.py build --formal --no-prove --backend=arm64   -o /tmp/fm formal/hostmods/fnmatch.mojo
Built: /tmp/fm  [arm64/macho]
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/fmx formal/hostmods/fnmatch.mojo
build: match_core: 7 parameters exceeds the 6 the formal x86-64 ABI passes in registers
```

This reproduces, on this tree and this scope, the 2026-10-01 measurement in
`bugs/FORMAL_sweep_work_map_2026-10-01_b3.md` §4 ("56 files are x86-64-only,
and all 56 are one construct: the register-argument count"), reduced to **1 file
in the repository scope** — `re.mojo` and `hashlib.mojo`, the two that doc names,
are behind host-import chains here. It is the largest x86-64/arm64 difference
that exists, it is not a bug (SysV passes six integer arguments in registers,
AAPCS64 passes eight), and the fix is an ABI change plus a proof-model change
that `FORMAL_x86_64_argument_registers` already measures. **Do not start it from
this map.**

**The same probe found one arm64-only WRONG ANSWER, which is the row to read
this map for.** `base ** <computed exponent>` is **0 on arm64** and correct on
x86-64: `2 ** 10` → 0 where the source says 1024, `3 ** y` → 0 where it says 27,
while the literal exponent (`2 ** 4` → 16) is right on both. It is
`bugs/FORMAL_variable_exponent_is_zero_on_arm64.md`, filed from this slice and
unfixed, and it is the direction that matters because `test_formal_run.py` builds
**the host's** architecture for a positive case — on this project's machines,
the one that gets it wrong.

**The census cannot see the defects that matter most, and the reason is
structural.** Both fixes below were found by building ~60 small constructs on
both backends and diffing the verdicts (`git show f89f9622`), because a sweep
only reports what a repository's own sources happen to *use*, and this
repository's sources are `not-answerable` here. That probe found two
x86-64-only answers and no third; the register-ABI row is the only x86-64-only
*refusal* in ordinary code.

## 5. Landed in this slice

### 5.1 `x /= 2`, `x //= 2`, `x %= 2`, `x **= 2` were refused by name (`f89f9622`)

arm64 has always routed all four to the same helper its binary form uses;
x86-64's `_emit_aug_assign` had no third route, so four spellings of one
construct were a diagnostic on one architecture and a program on the other.

### 5.2 `3 ** 3` answered 81 (`f89f9622`)

`_emit_pow`'s literal unroll copied the accumulator into R11 and popped the same
accumulator back into RAX, so every step computed `acc * acc` and the answer was
`base ** (2 ** (lit - 1))`. Measured on the old lowering, x86-64 against
arm64: `3 ** 3` 81 vs 27, `3 ** 4` 3\*\*8 vs 81, `3 ** 8` 3\*\*128 vs 6561.
Invisible in the suite because exponent 2 is the one value a squaring gets
right, and it was the only exponent anything tested. **This is the one place
this session found where x86-64 answered a different NUMBER rather than a
different verdict, which is why it was worth more than the sweep's top row.**

Both are pinned by `test_formal_x86_64_parity.py` (CPython as the oracle, both
architectures: 10/10 — one case routes the same delegation through a FRAME
SLOT, `self.n //= 2`, which is a different load/store path than a name and the
one a "store it as a local" mistake would survive; one `refuse:` row pins the
operator list both backends print for the spelling that is left, `@=`, keyed on
`model.AUG_OPS` rather than on the words around it) and, for the
divide-by-zero trap that no CPython oracle can express, by one
`BOTH_ARCH_CASES` row in `test_formal_run.py`.

## 6. Filed, not fixed

* **`bugs/FORMAL_del_of_a_subscript_is_a_silent_no_op_on_arm64.md`** — `del a[i]`
  and `del a[i:j]` build, run, exit 0 and **remove nothing** on arm64
  (`3 10` where CPython prints `2 20`), because the SubscriptExpr arm of
  `_emit_del` sits below an unconditional `continue`; the four helpers that
  lower it are dead code. x86-64 refuses every `del`, so the two do not even
  disagree about the answer. 39 uses in this repository, **0 in the stdlib**, so
  it moves no rate in either direction — it is a correctness defect, which is
  exactly why the sweep cannot find it.
* **`bugs/FORMAL_one_field_struct_field_stored_in_a_zero_arg_init_reads_as_zero.md`**
  — a **one-field** struct's field assigned in a **zero-argument** `__init__`
  reads back as 0 in every other method, on both backends. Two fields work, a
  parameterised `__init__` works, a tuple store works, a method that stores the
  field itself works. `test_formal_run.py`'s existing rows for this shape pass
  because they store through a tuple assignment.
* **`tools/formal_sweep.py`'s interpreter guard** (commit `5cd35093`) — the
  392-of-392 `backend-crash` run at the top of §1, turned into one line at
  startup and exit 2.

## 7. The rest of the causes, as work

Nothing below is unowned except where the table says so; this section exists so
that the next reader does not re-derive the attribution.

1. **`re.mojo`'s `pend` (26 files) and `formal/arm64.py`'s `sym_name` (3)** —
   `FORMAL_a_local_read_before_its_first_assignment` (claim `formal3-1-r2`) says
   the general rule is unenforced and measures what enforcing it costs. Note
   what the tool measured here: **21 of the 25 files behind `re.mojo` name
   nothing it declares**, so even a complete fix moves the row by a handful of
   files and lands most of them on the next refusal in their chain.
2. **`fnmatch.mojo`'s `match_core(7)`** — `FORMAL_x86_64_argument_registers`
   (claim `formal3-9-r2-r2`). Marginal effect **on this scope: 1 file**. The
   doc's own next step (a stack-argument convention in both emitters, plus
   `lib/ProofLib.lean`'s one-parameter `MojoFunc`) is unchanged and is still the
   biggest single x86-64 item in the tree.
3. **module-global storage and `sys.argv`** (6 files in-file) —
   `FORMAL_module_state_no_storage` (claim `formal3-5`), which states that the
   storage half landed and what is left is the three things a `__DATA` slot
   cannot be.
4. **`print()` of an unclassifiable operand** (2 files, both architectures) —
   **the one unowned row in this map.** It is a missing lowering rather than a
   wrong answer, so the cost of leaving it is a diagnostic a reader can see. It
   is not x86-specific and belongs with the arm64 repository sweep.
5. **152 files with no verdict at all** — a measurement of `-t 30` against this
   repository's largest modules, not a backend fact. Anyone wanting a census of
   *this* repository's contents rather than of the backend should re-run with
   `-t 300`; nobody should read the 61.1% as "61.1% of the repository".