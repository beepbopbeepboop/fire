# FORMAL sweep work map — slice `repo-a`, 2026-10-02 (arm64)

**The slice:** this repository's own `*.py` files whose names start `a`–`f`, plus
the `mojo/middle/` files of the same names — the compiler's front and middle
tier. 29 files. (The `mojo/backend_gimple/` `a`–`f` files are the BACK tier
and belong to a different slice; they are listed in §5 as out of scope here, not
as findings.)

**Machine:** arm64, the default. Two runs, both with `--no-stdlib`:

| run | flags | log |
|---|---|---|
| whole slice | `-j 2 -t 60` | `.tmp/sweep-repo-a.txt` |
| the 12 that timed out | `-j 2 -t 300` | `.tmp/sweep-repo-a-t300.txt` |
| after the fix, the 8 that `re.mojo` was blocking | `-j 2 -t 300` | `.tmp/sweep-repo-a-after8.txt` |

**`-t 60` is not a small number for this slice.** 12 of 29 files — every one of
them over 20 KB — got no verdict at all at `-t 60`, and `tool` is in no rate and
no cache, so the headline that run reports is over 17 files it never answered.
Everything in §2 is measured with the timeout high enough to get a verdict.

---

## 1. Class counts

| | files | of 29 |
|---|---|---|
| **pass** | **1** | `exec_budget.py` |
| codegen (a refusal in the file itself) | **1** | `determinism_trace.py` |
| codegen/dependency (refused in a module the file imports) | **8** | pre-fix |
| not-answerable/host-import | 18 | |
| not-answerable/unresolved-import | 1 | `fe_reader.py` (`lang_spec`) |
| backend-crash | 1 | `mojo/middle/funcs_shared.py` |
| tool / no verdict | 12 at `-t 60`, **0** at `-t 300` | |

**Before and after the one fix this slice produced** (the eight files, re-swept):

| | pre-fix | post-fix |
|---|---|---|
| codegen | 1 | 1 |
| codegen/dependency | 8 | **0** |
| not-answerable | 0 of the 8 | **8** (7 host-import, 1 unresolved-import) |

So the slice's codegen coverage goes from **1/10 = 10 %** to **1/1**, and the
honest reading of that number is not "the backend can now build those files" —
it is "those files import a CPython host module, so nothing about the backend
was ever going to answer them". §2 has why that is still worth having.

The 18 host-import files are out of scope by the task's own terms and are not
broken down here beyond the module census the sweep prints: `shutil` ×3,
`subprocess` ×2, `zlib` ×2, `ctypes`, `glob`, `copy`, `stat`, `importlib`,
`type_system`→`enum`, `collections`, `monomorphize`→`tempfile`,
`gimple_codegen`→`zlib`. Only `collections` and `enum` are in the sweep's "in
reach" group (a Mojo-side implementation could in principle provide them); the
other thirteen need a host process, an embedded interpreter or a kernel object.

---

## 2. The one cause that was worth a fix — `formal/model.py`'s CFG entry edges

**8 of 9 codegen/dependency lines, every one of them the same refusal:**

```
re.mojo: _p_alt: 'pend' is read at line 1401 before anything in this function
stores it, and CPython raises UnboundLocalError for that program …
```

`formal/hostmods/re.mojo:1397` says `pend = entry`, three lines above the read
the build reported, so the refusal was false — and `re` being out of the
backend puts every file that imports it out of the backend.

The cause is one line in `formal/model.py`'s `_build_cfg`:

```python
entry = new([])
entry.succs += run(body, [], [entry.index])      # ← the `+=`
```

`run` returns the exits that fall off the end of the body, and every one of
them is already reachable from its real predecessors. The `+=` added a second
edge from the ENTRY, which asserts a path from the function's first instruction
into the tail of the body. The fixpoint pays for it, because the entry's OUT is
only the parameter names: any region the trailing statement opened had its IN
intersected with the parameters, so every local stored before it dropped out.

The shape is therefore **not** "a loop reads a local" — it is **two**
conditions together: the body's LAST statement is a control-flow statement,
**and at least one path falls out of it.** The second half is not a detail, and
getting it wrong is how the coarse form of this rule gets re-derived: `run`
returns `[]` when every arm of the trailing statement terminates (`return`,
`raise`, `break` give no fall-through exit), so there is nothing to edge the
entry to and the bug cannot fire. Measured, on a program the coarse form says
must break:

```python
def main() -> int:
    acc = 0
    i = 0
    while i < 5:
        acc = acc + i
        i = i + 1
    if acc > 5:            # the body's LAST statement, reads `acc` in both arms
        return acc
    return 0
```

— the old code refuses nothing here, and neither does the new one. Both
directions are pinned in `test_formal_read_before_store.py` (`trailing_if_ok`
and `trailing_if_whose_arms_all_return_is_the_other_shape`), because a rule
stated in its coarse form and measured only in that form is how the next person
re-derives it. `_p_alt` does fire because its `while 1:`'s body ends in an
`if` with no `else`, and the false edge falls through.

**Fixed** (commit `5d64069a`), with 11 new rows in
`test_formal_read_before_store.py` — one per statement kind (`while`,
`while 1:`, `for`, `if`, `if`/`else`, `try`, `match`, `with`), two that must
still refuse, and the one that pins the rule's other direction. Eight of the
eleven go red on the pre-fix `model.py`.

**Measured blast radius, over this repository's 2819 top-level functions:**

| | |
|---|---|
| false refusals removed | **109** |
| new refusals added | **0** |
| of which inside this slice | **4** — `build_module.py:main`, `elaborate.py:check_bounds`, `mojo/middle/coro.py:_append_box_args`, `_append_cap_args` |

The removal-only direction is structural, not measured luck: dropping an edge
can only REMOVE refusals, and an entry block with no successor makes
`_definitely_stored` top-initialize everything downstream, which is the safe
direction for a name nothing path stores. The `0` above is the check that the
reasoning was right.

**What it is worth, stated honestly.** It unblocks **zero** files, because the
eight it unblocks all import a host module and were going to be
`not-answerable` whatever the backend did. What it is worth is (a) the sweep's
own accounting stops filing eight ordinary repo files as a codegen gap in a
module, (b) `re` — and every stdlib slice — gets `re` back, and (c) 109 real
functions in this repository stop being refused, four of them in files this
slice is responsible for. **The next slice that sweeps the stdlib should expect
a movement there and should not read it as a regression.**

---

## 3. Remaining causes, ranked, with the next step for each

Ranked by *what closes them*, not by file count — every row here is one or two
files, so a file count would rank by accident.

### 3.1 `mojo/middle/funcs_shared.py` — a backend CRASH, not a refusal. **Top in-file cause.**

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/fs.a.out mojo/middle/funcs_shared.py
build: 'str' object has no attribute 'name'
  formal/build.py:9065 _prepare_functions -> _frame_receivers
  formal/build.py:3099   method_owners.get(fn.name)          # a STR, not a StructDef
  formal/build.py:6255   publish(receiver, owner, ...)
  formal/build.py:6465   st.name                             # AttributeError
```

`backend-crash` is the one class that is a bug in the compiler's plumbing
rather than a limit of the language, and it is never cached, so it re-runs and
re-fails on every sweep until the cause is gone.

**This is already documented and the next step is already written:**
`FORMAL_frame_receivers_is_handed_the_method_name_table` — `_prepare_functions`
passes `owners` (`{method_name: struct_name}`, strings) into `_frame_receivers`'s
`method_owners` parameter, which its own docstring says it wants as
`{function name: struct}` (`M.method_owner_names(structs)`), and the collision
needs a module-level function whose name is a bare method name of an IMPORTED
struct. `formal/build.py` has one (`parse_module` vs `fire_compiler.Parser.parse_module`),
which is the only reason a corpus finds it and a hand-written case does not.

**NOT FIXED HERE, deliberately.** `python3 tools/control.py claims` lists
`bug:FORMAL_frame_receivers_is_handed_the_method_name_table` as a live claim
held by `formal3-4-r2-r2`. That task's state is `exited-ok / PARTIAL` with **+0
commits**, so it did not attempt the fix — but the claim is still live and the
rule is to report rather than edit. **Next step for the controller:** release or
reassign that claim; the fix is the doc's §"The next step" item 1, one argument
at one call site, and it makes `test_dataclasses_formal.py`'s corpus case green.

### 3.2 `determinism_trace.py` — a refusal that names a construct the file does not contain

The build says:

```
`_v == '1'` compares a NUMBER with a string, and the string comparison this
would lower to is `strcmp` … Ask one of the two questions instead — the byte's
value, `_v == 46` …
```

`_v` is `os.environ.get('MOJO_TRACE', '')`. The real fact is that the formal
`os` publishes no `environ` at all, and the build says exactly that when the
same expression is not followed by a comparison:

```
probe: os.environ reads 'environ' out of the imported module `os`, and a module
is not a value this path can place … What `os` publishes: chdir, chmod, curdir, …
```

Adding `.get(k, '')` and `== '1'` turns the right message into the wrong one,
because the module-attribute check exempts every link on a dotted CALL's spine
and `os.environ.get` is one — the same refusal, silently converted into advice
about a byte subscript.

**FIXED 2026-10-02 (`work/formal8-5`); the document is deleted with its fix.**
The spine is now skipped only while the link RESOLVES, and the discriminator is
the one this map predicted: an export of the module above it OR a submodule with
a dylib on this link line (`model.module_spine_link_resolves`, over the tables
`dylib_export_tables` builds — the ones both emitters resolve a callee through).
`os.environ.get(k, '')` is refused by the module-attribute check and the
string comparison is never reached; `os.path.join(…)` (532 call sites),
`os.getenv_or(…)` and `pkg.sub.twice(…)` all still build. The callee's own link
stays with `_extern_symbol`, whose message is the more precise one for a call.

**Still to be measured by the integrator:** `compile_stdlib.py`'s `U` count,
which is the only thing that covers the 664-file breadth. `os.path.*` is used by
a large share of them and none is a candidate for a new refusal.

**Note on the limit itself:** `os.environ` being absent is a TRUE limit and
stays refused. `formal/hostmods/os/__init__.mojo` says so in its own module
note — "`environ` IS ITS THREE FUNCTIONS … they are what `os.environ.get(k)`
and `os.environ[k]` have to become." Closing that half is a capability
question and not this slice's.

### 3.3 `fe_reader.py` — `not-answerable/unresolved-import` on `lang_spec`

`lang_spec` is not a stdlib module and not a sibling of anything, and no such
file exists in this checkout. That is a fact about the repository, not about
the backend: either the module was renamed and the import was not, or it lives
in a tree this checkout does not have. **Next step:** `git log --diff-filter=D
--name-only -- '*lang_spec*'` to find whether it was deleted or renamed; nothing
in the formal backend can answer it.

---

## 4. What this slice did NOT establish

* **It does not claim a coverage improvement.** Coverage for the slice went
  1/10 → 1/1 and the second number is a statement about host modules, not about
  the backend. Read §2's "what it is worth" instead.
* **It does not rank the repo's sweep against the stdlib's.** Two slices were
  running concurrently against the same `~/.gmojo/cas/formal-imports/arm64/`
  directory, and the sweep refuses to start a second arm64 run for that reason;
  both used `--allow-concurrent`. No row here was seen to move because of it (a
  manifest race shows up as a `tool` row carrying a `JSONDecodeError`, and there
  were none), but it is the reason a reader should re-run a slice before
  believing a count that moved.
* **It does not say the twelve `tool` rows are now clean.** They got real
  verdicts at `-t 300` and every one was `not-answerable/host-import` except the
  crash; at `-t 60` they had no verdict at all. A different machine under
  different load could still time one out, and `tool` is in no rate, so it does
  not change any number here either way.

## 5. Explicitly out of scope for this slice

* The `mojo/backend_gimple/` `a`–`f` files (`cpp_async`, `cpp_core`,
  `device_glue`, `device_select`, `emit_calls`, `emit_exprs`, `emit_funcs`,
  `emit_infra`, `emit_loops`, `emit_metal`, `emit_methods`, `emit_resolve`,
  `emit_stmts`). They are the BACK tier — 174 KB to 459 KB each, above the
  `-t` any light worker can afford, and they are the compiled path that
  `make gate` exists to check. If a slice is ever assigned for them it needs
  `-t` in the thousands and a memory class above `tiny`.
* The 18 host-import files, by the task's own terms.
* `_ab.py` (leading underscore, not an `a`–`f` name by the slice's rule).

## 6. Reproduction

```sh
python3 tools/memslot.py --gb 8 --label sweep -- \
  python3 tools/formal_sweep.py -j 2 -t 300 \
  analyze_benchmarks_types.py ast_rewriter.py build_config.py build_module.py \
  build_mojo_cli.py build_stdlib_dylib.py cas.py check_benchmarks_types.py \
  checked_run.py compile_stdlib.py comptime.py consolidate_string_pool.py \
  detect_real_type_errors.py determinism_trace.py driver.py elaborate.py \
  exec_budget.py fault_tolerance.py fe_reader.py fire.py fire_compiler.py \
  fire_main.py mojo/middle/boundnames.py mojo/middle/calls_shared.py \
  mojo/middle/closures.py mojo/middle/comptime.py mojo/middle/coro.py \
  mojo/middle/exprtypes.py mojo/middle/funcs_shared.py --no-stdlib
```

`--allow-concurrent` is needed while any other arm64 sweep is running; without
it the sweep refuses to start and says so. The run above is ~25 min at `-j 2`
on a machine also running six other sweeps, and its verdicts are cached, so a
second run of it is a file read per file.