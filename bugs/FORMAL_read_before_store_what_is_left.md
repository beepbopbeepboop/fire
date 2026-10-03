# read-before-store: the shapes that still decide wrongly, and how the corpus splits now

**Area:** FORMAL (`formal/model.py`'s `_build_cfg` / `read_before_store`, and
`formal/build.py`'s `_unstored_read`).
**Status: OPEN, with ONE analysis rule left (residual 2). Residual 1 — the
`finally` clause — is FIXED (`0dc51ae3`, `706f3f8b`) and its section records
what landed and the measurements that decided it. Residual 3 does not reproduce
on this backend and says why. All of the numbers are from the instrument
described here, because until this week the only way to count this refusal was
a whole-closure sweep.**

The fixes that closed the rest of the class are in `6e0bf2fe` (a `try`'s `else`
clause, and `_unstored_read`'s candidate set), `d54eeb37` (the build-and-run row
for the first of them), `7ba9e6fc` (the `finally`'s "the body may have
raised" path — an edge that turned out to name a path this backend does not
have; residual 1 below is the correction, and `0dc51ae3` is the fix) and
`0dc51ae3`. Each of them refused, on both architectures, a program CPython
runs, with a message that
claimed CPython raises `UnboundLocalError` for it. Their measurements are in
`bugs/FORMAL_a_local_read_before_its_first_assignment.md`'s territory and are
repeated here only as the baseline the residuals are counted against.

## The instrument, because the number was not obtainable before

`formal_sweep.py` answers "does this FILE build", which is the wrong question
for a check that is one of six late checks in a pipeline: a file refused for a
host import never reaches the read-before-store question, and a file refused by
an earlier check is invisible to this one. So counting this refusal needed a
sweep, a sweep takes a 30 s timeout per file and 644 files, and it was run at
04:17 on 2026-10-02 (`.tmp/sweep-arm-5.txt`).

The same question is answerable without emitting anything:
`_prepare_functions(stmts)` then, per function, the same `placed` recipe
`check_module_symbols` builds, then `_unstored_read(fn, placed, frame_slots)`.
That is parse plus one name walk — microseconds per function against a build's
hundreds of milliseconds — and it is what produced every number below. **It is
not a build and it is not a proof**: it does not run the emitter, so a name it
reports can still be refused earlier by something else (the census below counts
one: a MODULE-global read, which is `module_global_refusal`'s question and is
raised first), and a file it cannot parse in 90 s is skipped and counted as
unknown rather than as clean.

## The corpus, before and after

`stdlib` is `new-modular/Mojo/stdlib/std` (252 files, the sweep's second root);
the repository is this worktree (397 `.py`/`.mojo` files).

| | before | after |
|---|---|---|
| repository | **98 sites in 63 files** | **20 sites in 17 files** |
| stdlib | **26 sites in 16 files** | **5 sites in 4 files** |
| total | 124 sites in 79 files | **25 sites in 21 files** |

Six repository files and six stdlib files exceed the 90 s per-file budget and
are excluded from both columns (`fe_reader.py`, `myinterpreter.py`,
`gimple_codegen.py`, `formal/{model,arm64_codegen,x86_64_codegen}.py`,
`collections/{list,dict,string,span,counter,deque}.mojo`,
`string/string_span.mojo`, `python/{python_object,_cpython}.mojo`), so both
columns are floors.

**Re-run on 2026-10-02 after the residual-1 fix, and it reproduces the "after"
column exactly** — 20 sites in 17 repository files and 5 in 4 stdlib files,
with 27 repository and 75 stdlib files counted as unknown. The unknown count is
larger than the timeout list above because the instrument also swallows a parse
or `_prepare_functions` failure, and those are counted as unknown rather than as
clean; that makes it a floor in the same direction, not a different measurement.
The files are 400 in the repository and 252 in the stdlib.

**The doc this replaces measured 233 sites in 57 files with a syntactic scan
that predates the CFG.** That number was never about these shapes and should
not be compared with this one; it is recorded only so a reader who finds it
knows which measurement superseded it.

## Residual 1 — `finally` and a store later in the body: FIXED, and it was NOT the predicate

**The open question this section used to end with has been answered, and the
answer is the one that makes it a deletion rather than a new analysis: the
emitter's `finally` CANNOT produce "the body may have raised".** Read
`formal/arm64_codegen.py:1916` and `formal/x86_64_codegen.py:1868`:

* `_emit_try` **skips the handler arms outright** — "formal has no unwinder, so
  there is no edge from a raise site to an except arm";
* `RaiseStmt` flushes the pending finallys and then `exit(1)`s
  (`arm64_codegen.py:1628`), so a raise leaves no path to the code after the
  statement either.

So no edge into a clause from an exception exists on this backend, and the edge
`_build_cfg` had added for that reason (`arm_exits or [body_first]`) was a claim
about a program the emitted image does not contain.

**The path the emitters DO have is the one that was missing.** `_flush_pending_
finally` (`arm64_codegen.py:1898`, `x86_64_codegen.py:1850`) walks the pending
frames and emits a clause's statements **at the `return`/`raise`/`break`/
`continue` site**. So the clause is entered from *every point the try statement
leaves early*, and it reads the frame as it stood **there**. That is a
different graph, and the difference was a silent wrong answer rather than a
refusal: this program

```python
def probe(n):
    try:
        if n > 0:
            return 100
        v = 7
    finally:
        sink(v)
    return 0
```

has non-empty `body_exits` (the `if`'s false arm falls through), so the old rule
added **no edge at all** and the build accepted it. Measured, arm64, before the
fix, with the clause emitted at `return 100` before `v = 7`:

```
$ ./finally.arm64
8432255232          # sink's argument: a word nobody wrote
exit 100            # CPython: UnboundLocalError, exit 1
```

and x86-64 printed a different word for the same source. That is the worst
outcome this path has — a number nobody wrote, a status of 0's opposite, and no
exit code that reports anything.

**What landed** (`0dc51ae3`): `_Block.leaves` / `_Block.breaks_at` and
`model._leaves_early`, so the clause's predecessors are every block of the body
and the `else` holding a `return`/`raise`, plus the falling-through exits. A
`break`/`continue` is included only when it targets a loop **outside** the
statement, because `_flush_pending_finally(self._loops[-1]["fin_depth"])` — the
depth the loop recorded on entry — reaches a frame the loop opened but not one
that was already pending; a `break` inside the body stays inside the body and
reaches the clause by falling through, past the store.

The **second** half of the rule is the `finally_does_not_store_refused`-
adjacent half and it is what removed the seven files: `_emit_try` suppresses the
clause's own fall-through once an early exit has flushed the frame
(`need_fallthrough = False`), so when neither the body nor the `else` can fall
through, nothing follows the clause and the code after the statement is
**unreachable** — which `_definitely_stored`'s top-initialization already
answers the safe way. The old rule instead judged that dead code on the state at
the body's FIRST block, and `try: … total = … / finally: cleanup` then
`print(total)` — the commonest reason to write a `finally` at all, and a program
CPython runs because nothing ever reaches the `print` — was refused on seven
files of the repository.

**No predicate was written, and the doc's proposal for one is withdrawn.** A
`can this statement raise?` reader is still the right shape for
`bugs/FORMAL_while_body_store_refused_though_the_loop_runs.md`'s loop
preheader, which is a different question: there the edge is a claim about an
ITERATION completing, and this backend does have iteration. Here it would have
been a reader for a path that does not exist.

### The measurement this rule costs on the corpus

`.tmp/rbs_delta.py` runs the analysis twice in one process — once with the
working `formal/model.py`, once with the previous commit's exec'd into a copy
of the module's namespace, so `_build_cfg` and `_definitely_stored` stay a
consistent pair inside each — over both corpora, and prints only the
differences. It is the instrument this section's numbers come from, and it is
the same `placed` recipe + `_unstored_read` call the census above uses.

| | repository (400 files) | stdlib (252 files) |
|---|---|---|
| sites before `0dc51ae3` | 20 in 17 files | 5 in 4 files |
| sites after `706f3f8b` | 20 in 17 files | 5 in 4 files |
| **newly refused** | **0** | **0** |
| **no longer refused** | **0** | **0** |

**So the corpus does not move, in either direction, and that is the point
rather than a disappointment: the defect it fixes is one the corpus does not
contain, and it was found by reading the emitters, not by counting files.** The
two columns above also match this document's own "after" column from before the
fix, which is the check that the instrument and the earlier measurement agree.

**The measurement that DID decide something was between two forms of the fix.**
The first form (`0dc51ae3`) entered the clause once, from the falling-through
exits plus every early exit. It closed the soundness hole and it added two
corpus sites that the second form does not: `test_gimple_runner.py:271`
(`want_out`) and `test_silent_noop_iter.py:503` (`gen`). Both are the shape the
two-copy rule explains — the code after the try inherits an IN set that is the
intersection over copies it does not follow — and `test_gimple_runner.py:271` is
the ordinary "compute it, then compare":

```python
try:
    py = subprocess.run([sys.executable, entry], …)
    if py.returncode != 0 or not py.stdout:
        …
        return
    want_out = py.stdout
finally:
    os.unlink(entry)
exe_path = compile_mojo_to_gimple_exe(mojo_src)
…
if got.stdout == want_out and got.returncode == want_rc:
```

A rule that only ever ADDS predecessors cannot fix that, which is why the row
`no_fall_through_copy_when_no_body_path_falls_through` exists and why
`FINALLY_SHAPES` is a list of copies rather than one block.

**What is NOT measured here, and is the honest limit of every number above:** the
instrument asks `read_before_store`, not the build. It does not run the emitter,
so a name it reports can still be refused earlier by another check, and it
cannot see a wrong answer the emitter produces on a name the analysis accepts —
which is precisely the class the fix above closed. `test_formal_run.py`'s three
rows are the only evidence here that comes from an image, and one of them is a
`refuse:` row on both architectures.

## Residual 2 — two `if`s with the SAME condition

```python
is_tuple = var.startswith('(') and var.endswith(')')
if is_tuple:
    var_names = gen._split_top_level_comma(inner)      # 2201, stores
    …
if is_tuple:
    emit(gen._cname(var_names[0]))                     # 2270, reads
```

`is_tuple` is assigned once and never reassigned, so every path that reaches the
second `if` passed the first, and `var_names` is always stored. The CFG does not
know that: it models each `if` as an independent branch, so the join after the
first one intersects the `then` path (which stores) with the `else` path (which
does not) and the name drops out — and the second `if` can be false on a path
where the first was true, which is precisely why.

Two sites in this repository, both the same function pair in one file:
`mojo/backend_gimple/emit_loops.py`'s `_gen_for_list:1921` (`slot_elems`) and
`_gen_for_dict:2270` (`var_names`). The file is the gimple backend's loop
lowering and is owned by another claim, so nothing here was changed in it.

**The next step is a condition-fact environment in `_build_cfg`, and the shape
of it is small.** Each branch seeds a fact keyed by the condition's canonical
form (`ast.dump` of the expression, or `M.expr_key` if one exists); a join
intersects them and a block that WRITES any name the condition reads kills
them, so `is_tuple = …` twice does the right thing and `is_tuple = f()` kills
the first fact at the assignment. This is the same mechanism a constant-
propagation pass would need, and **residual 1's withdrawal is what leaves it
first**: the "which names does this statement mention" reader that residual 1
was going to need for its `can_raise` predicate is the same one, and with that
predicate withdrawn this is the only thing that wants it.

## Residual 3 — `with` and a store in the body: NOT REPRODUCIBLE on this backend

```python
def probe(n):
    with open(path) as f:
        binary = f.read()
    if n:
        sink(binary)     # refused; CPython runs it
```

**This one does not reproduce, and the emitters say why.** `_emit_with` in both
backends (`arm64_codegen.py:1947`, `x86_64_codegen.py:1900`) has no
`__exit__`: *"The body always runs on the fall-through path; return/break/
continue inside do no cleanup (there is none)"*. So the body's blocks have one
predecessor and the statement after the `with` is reached from them — which is
exactly what `_build_cfg`'s `WithStmt` arm already models (`pending = run(body,
loops, [w.index])`), and no edge is missing.

Re-measured after the `finally` fix: the snippet above is **not refused** on
either backend, and neither is

```python
def probe(n):
    with sink(n) as s:
        v = 1
        if n > 0:
            return 3
        v = 2
    return v
```

**And the corpus site this section was written about has been re-classified.**
`tools/formal_sweep.py`'s `run_one` refusal is now at **2332**, not 2139, and it
is residual 2's shape, not this one: `binary` is stored inside a nested
`with open(out, "rb")` in the `try` at 2325 and read at

```python
        if proc.returncode == 0:
            with open(out, "rb") as f:
                binary = f.read()
    if proc.returncode == 0:            # 2332 — the SECOND test of one condition
        missing = _unresolved_imports(binary)
```

— the same condition tested twice, which is exactly residual 2. CPython raises
`UnboundLocalError` for it when `proc.returncode != 0`, so the file is broken
and the analysis is right about it; it is residual 4's "genuine defects" row,
not a `with` false positive.

## Residual 4 — what the 25 remaining sites actually are, re-measured

The census re-run after the `finally` fix gives the same figures the "before and
after" table above does — 20 sites in 17 repository files, 5 in 4 stdlib files —
and the classification is unchanged except where noted:

* **module-global reads** (`tools/analyze_stdlib_errors.py:21`'s
  `STDLIB_PATH`, and every `__module_body__` the census reports) — not this
  check's question at all. `model.module_global_refusal` names the four kinds
  and the four repairs, and it is raised first, so a build never shows these.
* **genuine defects** — `tools/formal_sweep.py`'s `run_one`/`binary` (2332) and
  `main`/`base` (2816), both the "second test of one condition" shape below, and
  CPython raises for both. The analysis is right about the files; the files are
  broken. (`tools/mem_slope.py`'s `exes` was in this class an hour ago and is
  not any more.)
* **the correlated-condition shape above** — residual 2, which is the only
  shape left that this check gets wrong about a file it should accept.
* **the corpus's own dead branches** (`main: 'status'` in
  `test_container_equality.py` and `test_container_membership.py`, `main:
  'gen'`, `run_tests: '_RUNTIME_DIR'` at line 0) — code after a `return` or an
  `os._exit`, or a name read after a loop that may run zero times. These are
  reported because the name is read in a block the fixpoint considers reachable
  through a path the source does not have, which is worth a look but is not a
  false positive in any program that runs.
* **NOT re-classified, and worth naming because it was never in this list:** the
  `try`/`except` shapes. `_build_cfg` runs the handler bodies and treats their
  exits as paths to the join, while both emitters SKIP the handler arms
  outright, so the two disagree in the false-positive direction on a program
  whose image is correct. 921 handler arms in 400 repository files and 78 in
  252 stdlib files; it has its own document, `FORMAL_except_arm_is_never_
  emitted.md`, because the fix overturns a test row somebody pinned
  deliberately and the silent half needs its own decision.

## Why this is filed rather than fixed

**Residual 2 is the only analysis rule left here**, and it is a real piece of
work: a fact environment in `_build_cfg`, keyed by a condition's canonical form,
invalidated by any write a condition mentions. It is bigger than one focused
change and it wants the "which names does this node mention" reader that a
constant-propagation pass would need anyway — which is why it should not be
written as a one-off rule inside `_build_cfg`'s statement arms.

**Residual 1 turned out not to want that reader at all**, which is the finding
worth carrying forward: it asked for a `can_raise` predicate, and the predicate
was for an exception path this backend does not have. Reading the emitter
instead of reasoning about the language turned a proposed new analysis into a
deletion plus the two rules above — and the corpus measurement says the fix costs
nothing there, so the shape to look for next time is a rule whose stated reason
is "X may happen" where X is something the emitters do not do.

Residual 4's items are each a decision about a file rather than about the
analysis. All of it is measurable in seconds rather than by a 644-file sweep,
which is the thing the next session needs and did not have.
