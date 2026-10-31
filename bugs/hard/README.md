# bugs/hard — triage index

The hard-bug set. "Hard" here means one of two things, both of which make a
bug expensive to leave lying around:

- a **silent miscompile** — wrong value or garbage, exit 0, no diagnostic;
- a **compile refusal** on a shape real stdlib code actually uses.

Each doc carries a `**State: ...**` banner or a dated Status section directly
under its title, with the residue named. Start there.

Last updated 2026-10-29. This index is hand-maintained, so
`test_dangling_doc_refs.py` (`HardIndexIsTrue`) checks it against the
directory: every doc named here must exist, and every doc in this directory
must be named here. Adding or deleting a doc means editing this table in the
same commit.

## Docs in this directory

| doc | status as the doc states it | what remains |
|---|---|---|

## Removed docs: where their fix or residue went

A fully fixed doc is deleted, not kept (CLAUDE.md, "Bug docs"). Other files
that cited one of these were rewritten to name the commit, so grep for the
symptom and then `git log --diff-filter=D -- bugs/hard bugs` for the removal.

| removed in | what it was about | outcome |
|---|---|---|
| `dd0558b91` | function-scoped import call unresolved at link | fixed |
| `9ebea6d4c` | function-scoped import module not inlined (qualifier half) | fixed on both pipelines |
| `435cc7108` | function-scoped import rettype / literal-cast mismatches; coro nested-async closure capture; coro stackswitch yield-kind inference; generator consuming-generator value ctype; unannotated init param field type; struct format shadowed by `format` attribute | removed as verified-closed with residue; the residue went to new docs, most since removed |
| `b463d6193` | bytes value type; `struct` module | removed; residue went to new docs |
| `4f3d06b09` | bytes silent wrong values | fixed (`partition` tuple marker made load-bearing; bytes/memoryview sweep) |
| `a69524827` | coro stackswitch body semantics gaps (4 issues) | fixed |
| `82fa4a9b3` | generator non-plain assignment target refused; generator recursive yield-from with no-arg forwarding | fixed in the A3 stack-switch cutover |
| `36a1f27c4` | `*args`/`**kwargs` forwarding-only assumption; generator struct-typed param refused | fixed |
| `78daf365d` | `importlib._bootstrap` compile failure (vararg with trailing keyword-only param) | fixed |
| `5a5972336` | `tkinter.filedialog` compile failure | builds clean |
| `5b48b4756` | `Tools/cases_generator` cwriter compile failure | verified end-to-end |
| `1f7717c1f` | method call on a struct passed as a free-function parameter | fixed (8/8 names; the module-object spelling fixed here too) |
| `a0691784` (fix) / `e447341ab` (removal) | `import a.b; a.b.f(...)` two-hop attribute call; reexported-function import qualifier | fixed |
| `af80a8139` | link-mode bare submodule marker call (silent wrong value) | fixed |
| `70523c641` | `print` of an unannotated parameter typed `char *` (segfault); `*rest` in a for target | fixed |
| `4aaaa18f9` | cross-module struct constructor at module scope mistyped | fixed |
| `6c3d6ca0b` | container element type lost across functions (global / class-attribute append) | fixed |
| `48c03475f` | two same-bare-named structs in different modules shared one C identity | fixed |
| `53c51c774` | struct kwargs and inline unpack | removed; lambda env residue filed as its own bug |
| `9f8a9b783` | module-constructor return type erased; generator value slot loses bool | fixed (8-bug fix wave) |
| `0e87ed4ea` | constructor-argument field type, scalars only | fixed |
| `699ec9f60` | coro captured-param capture crashes | fixed |
| `5eb26a610` | coro yield kind unresolved at callsite | fixed; residue filed as three docs |
| `085ba7a72` | user-defined `__repr__` not consulted by `str()` / container spellings | fixed, pinned by a regression test |
| `658deff0d` | selfhost's dispatch-globals list forced every name to a dict lookup; also the only home of the selfhost error-count measurement recipe | fixed 2026-10-03 (gcc errors 35 → 0); removed 2026-10-29 with a pinning test |
| `1eacc36f8` | a lambda inside a nested `def` reads its outer-outer capture (read 0 instead of the captured value) | fixed; pinned by `gimple_lambda_in_nested_def_reads_outer_outer_local` |
| `bbac2b433` | `CODEGEN_param_used_only_as_method_receiver` | already fixed; deleted with two pinned tests |
| `316102957` | `PERF_struct_self_assign_scan_uncached` (uncached self-assign and self-read scans) | fixed: both scans memoized; pinned by `test_perf_self_assign_scan.py` |
| 2026-10-30 | `CODEGEN_generator_lambda_expr_unsupported` (lambda shapes in a compiled generator; every row closed, last two residue rows verified: a bool-then-float rebound yield is an honest refusal, `r = 2.5` after `False` is correct) and `COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil` (`fsutil.py` now builds, links and runs; `iter_files`/`walk_tree`/`glob_tree`/`process_filenames` match CPython) | fixed; the dynamic call/iteration layer for compiled generators landed with it |
| `b3b14a597` | `_walk_ast` re-scan blowup for large transitive-import graphs | closed 2026-10-29: the AST rescan is fixed and pinned. Its uncached self-assign scan was memoized in `316102957`. Its other cost, wall clock's per-level generated-C text join, has no doc in the tree now. |

## Lessons that outlived their docs

- **A fix closed on a narrower spelling than the one still broken** is the
  most common way a doc was wrongly closed. Write both spellings of the program
  down side by side and diff their answers before closing.
- **Two arms of one `if`/`elif` chain that match the same node type**: the
  second is dead code, with no error and no failing branch test. Found once
  after a merge (`a0691784` / `1f7717c1f`). Check each arm's type when a merge
  touches such a chain.
- **A test that skips itself counts nothing.** A regression case that vanished
  from the tally whenever `$TMPDIR` sat inside the checkout reads as coverage
  and is none.
- **A doc's stated reason for staying open can be stale.** "This runtime has no
  tuple type" was false: the marker existed and was only not load-bearing. Treat
  the explanation with the same suspicion as the description.
- **"No program can exhibit this" is a claim about the bugs in front of it.**
  Fixing the larger one made a two-hour fix out of a bug that had looked
  unreachable.
- **A regression test asserting the CPython-wrong answer protects the bug.**
  Check the expected value against CPython, and register the test in a bucket
  so something runs it.
