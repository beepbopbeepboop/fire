# read-before-store: the three shapes that still decide wrongly, and how the corpus splits now

**Area:** FORMAL (`formal/model.py`'s `_build_cfg` / `read_before_store`, and
`formal/build.py`'s `_unstored_read`).
**Status: OPEN. Three residuals, one of them a false NEGATIVE (a real defect the
check does not report) and two false positives that need a decision no
statement-level reader can make. All three are measured on the whole corpus,
with the instrument described below — which is the deliverable here, because
until this week the only way to count them was a whole-closure sweep.**

The three fixes that closed the rest of the class are in
`6e0bf2fe` (a `try`'s `else` clause, and `_unstored_read`'s candidate set) and
the commit after it (the `finally`'s "the body may have raised" path). Each of them
refused, on both architectures, a program CPython runs, with a message that
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

**The doc this replaces measured 233 sites in 57 files with a syntactic scan
that predates the CFG.** That number was never about these shapes and should
not be compared with this one; it is recorded only so a reader who finds it
knows which measurement superseded it.

## Residual 1 — `finally` and a store later in the body: a FALSE NEGATIVE

```python
def probe(n):
    try:
        p = 1
        if n:
            q = 2
    finally:
        sink(q)          # CPython raises UnboundLocalError at probe(0)
```

`_build_cfg` models "the body may have raised" as ONE edge, because the arms do
not carry it and dropping it would hide the defect above. Where that edge comes
from is the whole question:

* at the try's **header** — the pre-fix answer. Not a point that can raise at
  all (`try:` evaluates nothing before the body), and it refused
  `try: exes = []; …; return 0 / finally: unlink(e) for e in exes`
  (`tools/mem_slope.py:180`), which is why the edge now starts at the body's
  first block;
* at the body's **first block**, unconditionally — which is where it belongs,
  and which was implemented and measured: **it costs 6 more refusals than it
  removes** (7 files; `test_container_ordering.py:602` and
  `test_gimple_runner.py:271` are two of them). `try: … total = … / finally:
  cleanup` then `print(total)` is the commonest reason to write a `finally` at
  all, and every one of those refusals is a program CPython runs;
* at **every block of the body**, which is what a compiler does. Sound, and it
  reports the defect in the snippet above — but it reports the defect in all 6
  of the programs in the row above too, and there the answer is wrong, because
  nothing between the two points can raise.

**The next step is one predicate: can this statement raise?** With it, the edge
from block *k* is dropped when no statement up to *k* can raise, and all three
shapes above are answered at once. The decidable core is small and mechanical:
an assignment of a literal, a `var` of a literal, arithmetic on literals, a
`pass`; and the interesting cases are a call, a subscript, an attribute access
and an await. This is the same kind of "literal-only" evidence
`_loop_body_always_runs` already uses (see
`bugs/FORMAL_while_body_store_refused_though_the_loop_runs.md`, which is the
same trade for a loop's preheader), so the two compose rather than competing —
and note that fixing THAT doc's loop case needs the same predicate, which is
why this is worth doing once rather than twice.

**Not measured here:** whether the emitter's `__exit__`/`finally` lowering can
actually produce the path. If it cannot — if a `finally` on this path is a
plain fallthrough — then the edge is not a real path at all and the residual is
a refusal bug rather than a soundness hole, which is a one-line deletion. That
question is answerable by reading `formal/{arm64,x86_64}_codegen.py`'s
`finally` arm, and it should be answered before any predicate is written: it
decides which of the two the fix is.

## Residual 2 — `with` and a store in the body

```python
def probe(n):
    with open(path) as f:
        binary = f.read()
    if n:
        sink(binary)     # refused; CPython runs it
```

Same shape as residual 1 and the same cause: the clause's body is not on every
path out of the statement, because `__exit__` may suppress the exception. It is
in `tools/formal_sweep.py:2139` (`run_one`, `binary`) — the `with` there is a
`tempfile.TemporaryDirectory`, whose `__exit__` does not suppress, so the
refusal is wrong for that file.

**Deliberately not fixed, and the reason is residual 1's:** the fix is to say a
`with` body always runs to its end, which is true for every `__exit__` in this
corpus and not true in general — and the price of being wrong in that direction
is a program that reads a word nobody wrote. `_refuse_variadic_reads` is the
model for the answer when it can be had: refuse by name, with the reason.

## Residual 3 — what the 25 remaining sites actually are

Classified by hand from the census, because "a false positive" and "another
check's refusal" look identical in the output and are not the same work:

* **module-global reads** (`tools/analyze_stdlib_errors.py:21`'s
  `STDLIB_PATH`, and every `__module_body__` the census reports) — not this
  check's question at all. `model.module_global_refusal` names the four kinds
  and the four repairs, and it is raised first, so a build never shows these.
* **genuine defects** — `tools/formal_sweep.py:2612`'s `base` is assigned in
  one arm of an `if` and read in another, which is what CPython raises for. The
  analysis is right about the file; the file is broken. (`tools/mem_slope.py`'s
  `exes` was in this class an hour ago and is not any more.)
* **the `finally` and `with` shapes above** — residuals 1 and 2.
* **the corpus's own dead branches** (`main: 'status'`, `main: 'gen'`,
  `run_tests: '_RUNTIME_DIR'` at line 0) — code after a `return` or an
  `os._exit`, which the fixpoint already treats as unreachable. These are
  reported because the name is read in a block the fixpoint considers reachable
  through a path the source does not have, which is worth a look but is not a
  false positive in any program that runs.

## Why this is filed rather than fixed

Residual 1's predicate is a real piece of work (a `can_raise` reader for
statements, composed with the loop preheader's constant propagation), and
residual 3's items are each a decision about a file rather than about the
analysis. Both are bigger than the budget of one focused change, and both are
now measurable in seconds instead of by a 644-file sweep — which is the thing
the next session needs and did not have.
