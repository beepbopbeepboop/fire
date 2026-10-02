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
   parsed and rewrote ~60 compiler sources, per imported module. 16 of 19 GB at the first crash. FIXED (string key, one
   shared per-file cache). General bug: bugs/CODEGEN_tuple_dict_key_hashed_by_address.md.
2. **A malloc per character** (`mojo_char_to_str`, plus a fresh list per `c in (...)` display): ~150 B per scanned character.
   FIXED (256 shared immortal strings; display freed after `in`). Test: gimple_char_scan_allocates_nothing_per_character
   (4377 MB -> 1.5 MB).
3. **Per-call dict copy in the hermetic type scans**: `dict(_base_var_types)` (~1,650 entries, every key strdup'd) on 153,580
   calls = 254M entries ~ 23 GB (counted with the python-hosted run, .tmp/tk/count_copies.py). FIXED (depth-indexed pool;
   python-hosted output byte-identical with and without the pool). Same pattern at 5 more `var_types` save/restore sites: FIXED.
4. Smaller: a whole source file re-read per imported symbol (800 MB), fn-index re-validated per call (1.3 GB), per-function
   `_fresh_vals`/... sets rebound instead of emptied (2.7M strings). FIXED.

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
