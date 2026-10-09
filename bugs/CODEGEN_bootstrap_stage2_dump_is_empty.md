# CODEGEN_bootstrap_stage2_dump_is_empty: the self-hosted binary cannot yet compile the compiler's own closure

## Status (2026-10-09)

**The per-file class is CLOSED; the whole-closure class is OPEN.** The old title
(`--dump` exits 0 and writes an empty `.ci`) described a binary that crashed or
no-op'd on every input. Measured now, on this tree:

* `bootstrap-stage2-dumps` passes **46 of 46** (its `expect=` is gone). `.tok`
  is byte-identical to stage1's for all 46; `.ast` and `.ci` are identical for
  most single-module inputs and differ in a short list of classes below.
* `bootstrap-stage2-transitive` (`./mojo --dump-full fire.py`, the binary
  compiling its own 58 MB closure) does NOT finish. It is `disabled=` pointing
  here, so `bootstrap-stage3-*`, `bootstrap-verify` and `bootstrap-validate`
  SKIP behind it. Before this session it "passed" by writing a 378 KB skeleton
  (the per-file bugs below aborted the compile silently), which is why it used
  to look green.

### What was wrong (all fixed; each is a self-host-subset rule the closure's own
### source broke, found with `lldb` on a `-g` rebuild of `stage1/fire.ci`)

* keyword arguments were bound by call-site ORDER, not parameter name
  (`_eligible(s, prop_names=x)` filled `struct_name`): no generator could be lowered
* tuple-keyed dicts of sets / nested-tuple `for` targets / `set.update(list)`
  (module_gen, boundnames, emit_infra): replaced by flat string-keyed forms
* a local rebound from `char *` to int (struct tag hash) became a string concat
* `x = None` declared a 32-bit `int` that later held a pointer
* a nested `def` inside an `if`/`try` had its env freed on paths that never made it
  (cleanup-stack underflow overwrote the regex group-name table)
* cross-cycle calls (`ginf.begin_function(...)`) resolved to weak "unavailable in
  compiled mode" stubs: GimpleGen delegates / direct imports
* default parameters padded as 0 across modules; same-name locals of different
  container kinds in one function; `os.path.sep`; NULL dict key

### What is left

1. `stage2/mojo --dump-full ../fire.py` dies deep in the closure compile. Last
   measured stop: `lower_struct_method_call` (`emit_methods.py` ~6284) indexing
   `_method_dflts[...][1]` on a value that is the integer 2 for
   `GimpleGen._find_symbol_home_module`'s defaulted `want_abs`: the frozen
   GimpleGen signature table's `dflts` entries are not `(name, node)` pairs on
   the compiled path. Reproduce: `cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo
   --dump-full ../fire.py` (rebuild with `gcc -g` per-object + `dsymutil` for line
   numbers; `bt` works).
2. Expect more of the same class one after another (each fix moved the crash
   ~one pass further: dedup externs, bound names, bool-field registry, ...).
   The census tool is `tools/bootstrap_verify.py` once the closure completes.
3. Single-module diffs still open (stage1 vs stage2): `.ast` prints `None` as
   `0` inside `params` tuples (20 inputs); `.ci` for most inputs differs only in
   address-ordered or missing tails (see `bootstrap_verify` output).
4. Memory: an earlier run grew to 40 GB before SIGKILL; that was a runaway
   `set.add` (fixed) but the closure compile is still expected to be the large
   `bugs/CODEGEN_bootstrap_resource_blowup.md` case once it runs to completion.
