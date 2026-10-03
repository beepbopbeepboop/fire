# FORMAL_dylib_module_body_has_no_load_time_entry_point: 16 files are refused because a library has nowhere to run a module's top level

**Claim** `sweep:7` on `work/formal11-sweep`, found by
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3/§6 — **the largest codegen row in
the 668-file corpus that no doc and no claim owns.** Nothing here is fixed; §"What
is left" says exactly what is needed and in what order, and the first item is a
TEST, not a code change.

## The refusal, and why it is right

`formal/build.py`, in `_prepare_functions`, on the dylib path:

```python
    body = M.module_body(stmts, symbols)
    if as_dylib:
        if body:
            kinds = sorted({type(s).__name__ for s in body})
            raise CodegenError(
                f"{_first_body_where(body)}this module's API is its "
                f"top-level statements ({', '.join(kinds[:4])}"
                f"{' …' if len(kinds) > 4 else ''}), and a library has no "
                f"entry point to run them. …")
```

**The refusal is correct and should stay.** A dylib has no entry point, so a module
body compiled into one is a function nothing calls: the module's top-level code
would be compiled, dead, and the importing file would build, link, and do nothing at
load time — the same silent no-op an executable had, one level down, and worse than
the executable case because a caller linking the library cannot see that the store
never ran. The comment above the check says this, and it is right.

**The gap is not the refusal; it is that nothing on this path gives a library a load
time.** So the answer available today for a module with a top level is "refuse",
and 16 files pay for it.

## What it costs, measured 2026-10-03 (`master` at `e7fbe6ef`)

`python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-7.txt` —
**the same 16 files on both architectures** (arm64 16 / x86_64 16, and of the 542
files both arms classified, the class is identical on every one).

| refusing module | files blocked | blocked files naming anything it declares |
|---|---|---|
| `module_loader.py` | 7 | **0** (`_ReflectSym`, `_ReflectTable`, `_find_stdlib_path`, `_is_stdlib_root`, `_mkfn`, `_ml_as_str`) |
| `tools/memslot.py` | 5 | **0** (`_alive`, `_envf`) |
| `formal/x86_64.py` | 2 | **1** (`_alu_digit`, `_alu_rr`, `_group3`, `_jcc_rel32`, `_jcc_rel8`, `_mem_modrm`) |
| `determinism_trace.py` | 2 | **0** (`_trace_file`) |

**15 of the 16 do not use anything the refusing module declares.** They are refused
for having imported it. The blocked files are this repository's own —
`build_config.py`, `formal/x86_64_model_coverage_test.py`,
`mojo/backend_gimple/emit_resolve.py`, `mojo/middle/resolve_shared.py`,
`tools/pipeline.py`, `formal/macho_linker.py` and others — so this is the row that
keeps the repository's own modules out of the formal corpus.

## The 13 statements that make the row, which is what a fix has to run

**Measured 2026-10-03** by asking `model.module_body` the same question the dylib
path asks, one line of Python per module (no build):

```
determinism_trace.py   1 statement   _ENABLED = None                    (line 67)
formal/x86_64.py       1 statement   RETURN_REG = Reg.RAX               (line 66)
module_loader.py       5 statements  _C_KEYWORDS = frozenset({...})     (line 13)
                                    HERE = os.path.dirname(...)        (line 25)
                                    STDLIB_PATH = _find_stdlib_path()   (line 126)
                                    TEST_PATH = os.path.join(...)      (line 127)
                                    _module_loader = ModuleLoader()     (line 1050)
tools/memslot.py       6 statements  HERE = os.path.dirname(...)        (line 67)
                                    DEFAULT_BUDGET_GB = 96.0            (line 68)
                                    SNEAK_MAX_GB = 8.0                  (line 80)
                                    SNEAK_CAP_GB = 32.0                 (line 81)
                                    SNEAK_MARGIN_GB = 16.0              (line 82)
                                    if __name__ == "__main__":          (line 420)
```

**Nine are computed values and four are float literals** — and the float ones are
body only because this path cannot fold a float, which is a separate (and honest)
finding at the end of "What is left".

**Why these four modules and not the other 412 files in the sweep:** `module_body`
exempts every top-level store the IMAGE already holds, in two ways — a value that
folds and is substituted at each read (`X = 5`), and a name that is a `__DATA` slot
whose initializer the image lays out before anything runs (`X = ["a", "b"]`, which
is storage-shaped rather than foldable). `determinism_trace.py`'s `_MASK`,
`_MASK63` and `_iota` are all in the first class and are therefore **not** body:
the one statement that keeps that module out is `_ENABLED = None`, and `None` is
neither a foldable literal nor a slot initializer (`_static_initializer` answers
`("unknown", None)`, because one untagged word cannot say whether a 0 arrived as
`None` or as the integer 0). That is the whole of its 2-file row, and the reason
is a representation question, not a lowering one.

**And that exemption is MEASURED, not read off a docstring.** A module with exactly
that shape — `COUNT = 5` (folded) and `NAMES = ["alpha", "beta"]` (a slot), plus a
function that reads the first and one that writes it — builds as a dylib today, and
a program linking it prints `first=5@second=7@width=2@@` and exits 0, which is what
CPython prints for the same text
(`test_formal_cross_module.py::test_a_module_stores_that_the_image_already_holds_cross_the_boundary`,
added with this document). **A dylib's `__DATA` already carries what the image
holds.** An earlier draft of this document claimed 4 of the 16 files were blocked by
bodies with "no code to run" and would need no entry point; the measurement says
otherwise and the draft was wrong.

## What is left, in order

**0. DONE on this branch, and it is what makes the rest possible: the
precondition test, and the measurement that says the precondition holds.**

`test_formal_cross_module.py::test_a_module_stores_that_the_image_already_holds_cross_the_boundary`
(a module with `COUNT = 5` and `NAMES = ["alpha", "beta"]`, read and written from
another image) **builds, runs, and matches CPython exactly** —
`first=5@second=7@width=2@@`, exit 0 — and its control
`test_a_module_body_with_code_in_it_is_still_refused` pins the refusal for a body
that genuinely must run (`COMPUTED = compute()`), by words.

**So the `__DATA` in a dylib already carries what the image holds**, and the next
step is not gated on a measurement any more. Before this test, nothing in the suite
asserted it: every other case in that file crosses the boundary with a VALUE and
never with the module's own initialized data, so a slot that read as `0` where the
source says `5` would have left the file green.

1. **The load-time initializer**, in both object writers, plus a linker section
   each — `formal/arm64_codegen.py`'s Mach-O path and `formal/x86_64_codegen.py`'s
   ELF path. The function to emit already exists (`_module_body_function`); what is
   missing is anything that calls it, and a section the custom linkers must not
   dead-strip. Measured ceiling: **16 files.**
2. **Then measure whether the row is worth it, before building it.** The nine
   computed stores are `frozenset({...})`, `os.path.dirname(...)` (×2),
   `os.path.join(...)`, `_find_stdlib_path()`, `ModuleLoader()`, `Reg.RAX`, and
   `None` — and three of those are calls into `os`, which on this target is a host
   module with no Mojo source except through `formal/hostmods/os/`. **A module
   whose body calls a host module may be unbuildable here for a second, permanent
   reason, and then the initializer buys 9 files rather than 16.** That question is
   answerable by asking whether each of the four modules builds with its body
   deleted, which is four builds.
3. **Separately, and worth more than its file count says: a module-level FLOAT
   constant is body, and it should not be.** Four of `tools/memslot.py`'s six body
   statements are `DEFAULT_BUDGET_GB = 96.0`, `SNEAK_MAX_GB = 8.0`,
   `SNEAK_CAP_GB = 32.0`, `SNEAK_MARGIN_GB = 16.0` — float literals that
   `collect_module_symbols` does not fold (`site` is `rebound`, not `assigned`, so
   `_is_folded_constant` declines them), which makes them "code that has to run".
   The reader is then told *"this module's API is its top-level statements
   (AssignStmt, IfStmt)"*, which is a statement about the module's API and not
   about the one fact that matters: **this path has no float value for a store to
   produce.** Refusing a float constant by name is the honest answer and it is a
   small change; it unblocks **0 files** and improves a message.

## What is NOT the next step

* **Not** re-running the export-table analysis. This row is not the export gate; the
  165-file row above it is (`FORMAL_dylib_export_loops_and_frame_bounds`,
  `formal10-2`), and this one is 16.
* **Not** a stdlib edit. Every module in the row is in THIS repository, so unlike
  most of the corpus's large rows, the whole fix is makeable from a worktree.
* **Not** "delete the module's top-level statements" in `module_loader.py` and
  `memslot.py`. That would work around the backend's limit by rewriting the
  compiler's own source to a shape the compiler can compile — a shortcut, and one
  that hides the gap rather than closing it.

## Reproducing the measurement

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/formal_sweep_causes.py bugs/sweeps/sweep-arm-7.txt | grep -A6 "top-level statements"
grep "API is its top-level statements" bugs/sweeps/sweep-arm-7.txt
```