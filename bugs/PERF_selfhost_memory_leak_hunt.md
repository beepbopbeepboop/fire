# PERF: where the bytes go in `mojoc --dump-full fire.py` (leak hunt, 2026-09-29/30)

Working log; the durable write-up is doc/MEMORY.html section 11. Standard: nothing over 3-4 GB
(bugs/PERF_memory_over_4gb_is_a_bug.md).

## Method
`leaks` only sees unreachable memory and MallocStackLogging on this run is itself tens of GB, so the hunt used
`tools/heapprof.c` (DYLD_INSERT_LIBRARIES sampling heap profiler: per-allocation-stack live bytes, snapshots on growth,
at exit and on a crash with the crash stack; `HEAPPROF_QUARANTINE=N` poisons the last N freed blocks and reports a write
after free with the freeing stack; `HEAPPROF_TRAP_SEQ` + an lldb watchpoint names the writer) and
`tools/heapprof_report.py [--lines]` (atos; attributes to the first non-runtime frame, file:line from #line tables).
Runs: `python3 tools/memslot.py --gb N --label x -- ...`, one at a time. Subject: `MOJO_HOME=$PWD ./mojoc fire.py --dump-full`
(flag AFTER the file, cwd = repo root).

## Before / after (same command, same machine)
| build | peak RSS | wall | end state |
|---|---|---|---|
| master a0c0969 | 33.8 GB (31.3 by memcap) | 48 s | SIGSEGV |
| master + crash fixes only (heap overflow, `_bool_valued`) | 37.2 GB | 65 s | SIGSEGV (ownership_destruct) |
| + parse-once cache | 9.0 GB | 13 s | SIGSEGV |
| + 1-char strings, `in` display frees | 1.45 GB | 11 s | SIGSEGV (crashes hide later growth) |
| + all crashes fixed (run completes) | 22.4 GB | ~60 s | exit 0, "AttributeError: platform", no .ci |
| + scratch-dict pool (resolve_shared) | 13.1 GB | | |
| + pool at 5 more copy sites, source read cached, fn-index validated per compile, per-function sets emptied in place | **12.2 GB RSS (11.3 memcap)** | 61 s | same |
| ab-native snippet: `mojoc abfulltest_driver.mojo --dump-full` from the repo root | 17.6 GB / 26 s -> **0.44 GB / 3.7 s** | | generated .ci identical (see below) |

The early rows are PARTIAL runs (they die before the end); the honest comparison of a whole compile is the last rows.
`doc/MEMORY.html` has the byte tables.

## What the bytes were (heapprof, live bytes at the end)
1. **Tuple dict key never hits** (`_selfhost_parsed_modules` & two siblings keyed on `(path, mtime)`): every call re-tokenized,
   parsed and rewrote ~60 compiler sources, per imported module. 16 of 19 GB at the first crash. FIXED twice over: first
   at these call sites (string key, one shared per-file cache), then at the MECHANISM — a tuple dict key is now keyed by
   its CONTENT (`mojo_dict_key_for`), covered by test_dict_tuple_key.py, so the call sites no longer have to be defended
   individually. Both bugs' docs are deleted.
2. **A malloc per character** (`mojo_char_to_str`, plus a fresh list per `c in (...)` display): ~150 B per scanned character.
   FIXED (256 shared immortal strings; display freed after `in`). Test: gimple_char_scan_allocates_nothing_per_character
   (4377 MB -> 1.5 MB).
3. **Per-call dict copy in the hermetic type scans**: `dict(_base_var_types)` (~1,650 entries, every key strdup'd) on 153,580
   calls = 254M entries ~ 23 GB (counted with the python-hosted run, .tmp/tk/count_copies.py). FIXED (depth-indexed pool;
   python-hosted output byte-identical with and without the pool). Same pattern at 5 more `var_types` save/restore sites: FIXED.
4. Smaller: a whole source file re-read per imported symbol (800 MB), fn-index re-validated per call (1.3 GB), per-function
   `_fresh_vals`/... sets rebound instead of emptied (2.7M strings). FIXED.

## Status 2026-10-02 (`work/bugs4-9`): the "what remains" list is re-checked
## item by item, and it did not survive the check

This is a working log and the table below was written on 2026-09-30. Re-reading
it against the tree, **three of the six entries are already fixed, one was
mis-attributed, and one belongs to another claim.** Recorded here rather than
silently deleted, because "the list was stale" is only useful if a reader can
see WHICH items and why.

| item as written | state on this tree |
|---|---|
| ~720 MB `_walk_ast` flat node lists (`exprtypes.py:46`) | **FIXED, elsewhere.** `exprtypes.py` now has `_walk_ast_into(node, out)`, which appends into ONE caller-owned list instead of building and discarding a list per subtree, and its own docstring credits `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md` — **another claim's**, so it was never mine to land or verify. |
| ~650 MB `_dedup_variadic_externs` re-splitting the cumulative preamble | **FIXED, elsewhere, twice.** `emit_infra.py`'s `_DEDUP_EXTERN_PARTS_CACHE` (process-global, keyed on a part's exact text) plus a second phase that DERIVES a parent's entry from its children's rather than re-parsing it (`_record_output_parse`). Its comment names the same `PERF_nested_module_compile_walk_ast_quadratic_rescan.md` doc and says the 2026-09-26 re-profile put it at 34% of a 160-module chain. `test_gimple.py`'s `dedup_variadic_externs_cache_is_a_faithful_parse` is the regression. |
| ~320 MB x2 per-function `_infer_local_var_types` results and set adds under `_lower_call` | **BOTH MIS-ATTRIBUTED, and now measured.** The `_infer_local_var_types` half is measured below. The "set adds under `_lower_call" half names a function that has no such set: on this tree `_lower_call` (`mojo/backend_gimple/emit_calls.py`) contains exactly ONE `.add()` — `_asdict_dispatch_needed.add(1)`, a one-element flag read only as a boolean ("did a `dict`/`vars()` appear?"), which cannot grow. The `next(iter(_seen))` set the entry probably named was replaced years ago and its own comment says why (a self-host closure could not compile through it). |
| 512 MB the container-kind registry (`_reg_list`) | **STILL OPEN, and not fixable without a collector.** It grows with every container that is never freed and shrinks only as leaked ones are returned, so its size IS the leak count. The doc's own caution applies in reverse here: `leaks` would report little (the containers are reachable from the registry), and the fix is the durable one in item 3 of `PERF_memory_over_4gb_is_a_bug.md` — free what a pass has finished with — not a shrink at this site. |
| ~270 MB `ast_rewriter.py:709`, ~180 MB `collect_method_scalar_obs`, ~150 MB `param_ctype`, `py_tokenize` 170 MB | **NOT RE-CHECKED.** Each needs the profiler run this doc's own method describes, which is a whole-closure `--dump-full` — the integrator's job, explicitly not a worker's ("a worker's part is to read the report and fix sites"). Untouched rather than re-asserted. |
| "Retention by design: every parsed module's AST and every generated function's type tables live to the end" | **UNCHANGED and correctly filed as retention rather than leak — and now MEASURED as bounded.** See the second table below. |

### The "set adds under `_lower_call`" item, measured rather than asserted

The measurement the first item above needed is the one this doc's method can
afford at worker scale: compile a real module in-process
(`gimple_codegen._run_pipeline` on `mojo/middle/exprtypes.py`, 406 491 bytes of
generated C), then walk the root `GimpleGen`'s container attributes and print
the entry count of each, then compile a SECOND module through the same process
and print what GREW.

Everything that grows is a per-function or per-module table, bounded by the
input — the signature and import tables, `_emitted_line_pairs`, `_str_pool`,
`_calls_in_stmts_cache`, `_find_generic_visited`, `struct_field_types`. The
largest single container on the first module is 617 entries
(`_calls_in_stmts_cache`) and 519 (`_KNOWN_SIGS`); the biggest deltas on the
second are `func_return_types` +301 and `imported_symbols` +166, i.e. the second
module's own functions. Nothing grows per CALL, which is the shape this entry
described.

**That is the answer, and it is a negative one:** there is no set under
`_lower_call` that is added to and never emptied, so this entry retires rather
than becoming a fix. The honest residual of the measurement is that it is ONE
module-sized sample, at `-O0`-equivalent python-hosted codegen, and it says
nothing about the self-hosted binary's own heap — which is what item 2 of
`PERF_memory_over_4gb_is_a_bug.md` needs, and why that remains the integrator's.

### The mis-attribution, measured

The entry says "per-function `_infer_local_var_types` results and set adds under
`_lower_call` … unresolved attribution: some set that is added to and never
emptied". Measured directly on this tree, in-process, on a real module
(`mojo/middle/exprtypes.py`, 380,034 bytes of generated C):

```
_infer_local_var_types calls: 93      (3 per function: 31 distinct names)
total result entries:       231
largest single result:      11 entries
```

231 entries for a 380 KB artifact is kilobytes, not 320 MB — three orders of
magnitude off, and the shape explains it: `resolve_shared.py` builds a FRESH
`conflicting: set` per call and ASSIGNS it
(`gen._multi_kind_locals[name] = conflicting`), it never adds to one. So there
is no set that grows without emptying; what there is one small entry per
function, re-derived per pass, which is **bounded retention by design** and
belongs in the row above, not in the leak list.

The other half of that entry, "set adds under `_lower_call`", needed a
different measurement and got one the same day — see the table's row and the
section under it. It retires too, and for a sharper reason: the function has no
such set.

### What this branch did land against the standard

The leaks in this tree's own "before/after" story that were real programs, not
the self-hosted compiler, are all now measured:

* a printed container leaked its `mojo_str_cat` buffers — 200000 `print(xs)` of
  an 8-element list peaked at **99.7 MB**. All of that family is now fixed and
  its doc is deleted with the fix: seven container shapes 60000 times peak at
  **12.8 MB**, and a printed STRUCT's per-field strings went with it
  (176.7 -> 80.4 B/iteration, `gimple_printed_struct_repr_does_not_grow`). What
  remains in that family is the top-level repr result `print` never frees —
  16.4 B per container print —
  `bugs/CODEGEN_print_of_a_container_never_frees_the_repr_it_asked_for.md`;
* a per-character string scan allocated one `malloc(2)` per character —
  `gimple_char_scan_allocates_nothing_per_character` measured **246.7 MB** and
  now measures **1.6 MB**. That one was `s[i]` spelled `mojo_cstr_slice(s, i,
  i + 1)` (the slice allocates a two-byte buffer per character and nothing owns
  it) because gimple refuses a `char`-typed argument at a call; it now goes
  through a new `mojo_char_at(char *, int64_t)`, which answers from the same
  256 shared immortal character strings `c == "x"` already used.

Neither is the self-hosted-compiler subject of this doc, so neither moves the
number in the table above. They are here because the standard they are measured
against is `PERF_memory_over_4gb_is_a_bug.md`, and because a `--dump` is
exactly the shape that pays the first one.

## What remains (12 GB; top sites, each < 5 %, long tail of ~2,700 sites)
* 512 MB: the container-kind registry (`_reg_list`) table, one block: grows with every container that is never freed
  (32M+ of them). Shrinks only as leaked containers do.
* ~720 MB: `_walk_ast` flat node lists (exprtypes.py:46, `gen_module_impl.mk`): a list per call, consumed once, not owned.
* ~650 MB: `_dedup_variadic_externs` re-splitting the cumulative preamble (emit_infra.py:3707-3830) into substrings.
* ~320 MB x2: per-function `_infer_local_var_types` results and set adds under `_lower_call` (gimple_codegen.py:3387, unresolved
  attribution: some set that is added to and never emptied).
* ~270 MB `ast_rewriter.py:709`, ~180 MB `collect_method_scalar_obs`, ~150 MB `param_ctype`, py_tokenize 170 MB (one pass, retained AST).
* Retention by design: every parsed module's AST and every generated function's type tables live to the end.
Next lever, same shape as every fix above: find the per-call/per-function copy or temp, then pool it, empty it in place, or
give it an owner. Also grep the compiler for `while new != old` loops over containers (container `==` is pointer identity
self-hosted; CODEGEN_container_eq_is_pointer_identity.md on work/merge2-compiled).

## Verification done / not done
* python-hosted output, pool vs fresh-dict, `--dump-full fire.py`: byte-identical (51,348,075 bytes).
* python-hosted output, this tree vs the tree before the last batch (git HEAD), `--dump-full` of cas.py, module_loader.py,
  stdlib_core.mojo, test_fileio.mojo: byte-identical; the three inputs that import the compiler's own modules differ only where
  the edited compiler functions themselves appear (expected).
* native ab-native snippet: new native .ci == old native .ci except 14 lines of a runtime comment that arrived with the merge of master.
  Native-vs-python differs in `_gimple_main` (an extra `_t4`) in BOTH old and new: pre-existing, not from this work.
* NOT verified: native fire.py output (none is produced, see bugs/CODEGEN_selfhost_dumpfull_ends_in_attributeerror_platform.md);
  no gate was run. Needs: `python3 tools/integrate.py --only leakhunt --jobs mojoc ab-native native-dumpfull selfhost selfhost-memory
  selfhost-memory-fire` and the gimple runner / ownership tests (test_gimple_runner.py, test_ownership_destruct.py).
  ab-native is marked `expect=`: if it now passes the anti-rot rule will demand the marker be dropped.
