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

## The two halves, which are different projects

The row splits on a question the source answers, and the split is not a matter of
taste: **does the body contain CODE, or only VALUES?**

### Half 1 — 4 files, and there is no code to run

`formal/x86_64.py`'s whole top level is `COND_O = 0x0`, `COND_NO = 0x1`, …
`determinism_trace.py`'s is `_MASK = 0x7FFFFFFF`, `_TRUTHY = ('1', 'true', …)`,
`_iota = 0`. Every statement is an assignment whose value is a literal or a
container literal.

**Those are not statements that must run; they are the image's static data**, and
this backend already knows how to say so:

* `model._static_initializer(value)` returns `("int", n)` / `("str", text)` /
  `("blob", shape, words)` for exactly those, and `("unknown", None)` for anything
  else — "deliberately exhaustive over what a `__DATA` word can hold and honest
  about the rest".
* `model.collect_global_slots` already gives a name that a function WRITES a slot
  whose `init` is that static initializer, and `model.build_data_image` already
  writes every slot's `init` into the image (with the link-time address fixups both
  linkers need).
* A name nothing writes and whose value is a literal is not in the slot table at
  all: `_substitute_module_constants` folds it at every read, so it needs no storage
  and no initializer.

So for this half the correct lowering is: **no function is emitted, the body's
values are the image's data, and the refusal does not apply.** That is a narrowing
of the check from "the body is non-empty" to "the body has an EFFECT in it"
(`model.module_body`'s kinds are already the discriminator; the per-statement
question is `_static_initializer` on each assignment's value).

**Not started here**, for the reason in "What is left" item 2.

### Half 2 — 12 files, and a load-time initializer is the only correct answer

`module_loader.py` and `tools/memslot.py` compute:

```python
HERE = os.path.dirname(os.path.abspath(__file__))      # module_loader.py:25, memslot.py:67
STDLIB_PATH = _find_stdlib_path()                      # module_loader.py:126
_module_loader = ModuleLoader()                         # module_loader.py:1050
if __name__ == "__main__":                              # memslot.py:420
```

Those are **effects**: the values do not exist until something runs. An importer
that calls `_find_stdlib_path()` needs that call to have happened first, so the
code has to run at load, before any dependent's code.

**The only correct home for it is a load-time initializer**: a `__mod_init_func`
entry in the dylib's `__DATA` pointing at the module body, which dyld runs in
dependency order (a dependent's initializer runs after its dependencies'), and
which the custom linkers must not dead-strip. That is an emitter feature in **two**
object writers (`formal/arm64_codegen.py`'s Mach-O path and
`formal/x86_64_codegen.py`'s ELF path), plus a linker section each — a real project,
not a patch. **It is not started here.**

The alternative — exporting `__mod_init__` and having each importer's module body
call its dependencies' — needs a "has this run" flag per module image to avoid
double initialization when a module is reachable by two paths, which is more
machinery for the same result and one more thing to get wrong.

## What is left, in order

1. **Write the test that does not exist: a program reading another module's WRITTEN
   global gets the right number.** `test_formal_dylib.py` has
   `test_exported_functions_execute` (ctypes into a built dylib) and
   `test_executable_links_a_dylib` (a program linking one) — the harness is there.
   No test asserts that a `__DATA` slot **in a dylib** carries its static
   initializer. Until one does, relaxing the refusal in half 1 converts a loud
   refusal into a **silent wrong answer** (`X = 5` read as 0), which is the one
   trade this refusal exists to refuse. **This is the first thing to do and it is a
   test, not a change.**
2. **Then half 1**: narrow the dylib-path refusal to a body with an effect in it,
   with `_static_initializer` as the discriminator, reusing `collect_global_slots`
   and `build_data_image` unchanged. Measured ceiling: **4 files** (`formal/x86_64.py`
   ×2, `determinism_trace.py` ×2), and the 1 file that uses a declared name is
   `formal/macho_linker.py` behind `formal/x86_64.py`.
3. **Then half 2**, as its own project: `__mod_init_func` in both emitters, plus the
   `control.py guard`-visible memory cost of an image that now runs code at load.
   Measured ceiling: **12 files**, 0 of which use anything the two refusing modules
   declare — so half 2's honest value is "12 files stop being blocked by an import
   they do not use", and it should be weighed against the risk of running code at
   load time in an image whose whole discipline is refusing what it cannot represent.

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