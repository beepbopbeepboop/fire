# CODEGEN_do_imports_large_closure_residual_hotspots.md
# 
# After the binder-census memo, the compiler-sized `do_imports` closure still spends ~150s in two per-module walks and a one-time selfhost seed
# 
# **Status:** OPEN — filed 2026-11-08 as the RESIDUAL slowness left by fixing
# `MIDDLE_coro_import_compile_hangs_on_large_modules` (the binder-census memo
# in `mojo/middle/literal_bindings.py` + `mojo/middle/exprtypes.py`). That fix
# removed the O(N²) per-level re-derivation of the single binder census: the
# repro's `bound_names` work dropped from 60,259,179 calls (~60s) to one build
# per module, and the repro's wall went 205–211s → 177.5s. The remainder is in
# BACKEND passes, which the MIDDLE fix deliberately does not touch. NOTE: a
# parallel lane holds the `perf-nested-module-compile-walk` claim — check for
# overlap before taking hotspot 1.
# 
# ## Repro
# From the repo root (cold CAS; ~3 minutes):
# ```sh
# python3 - <<'PY'
# import sys, time; sys.path.insert(0, '.')
# import gimple_codegen
# t0 = time.time()
# out = gimple_codegen.compile_to_gimple_cached(
#     'from build_config import find_gcc\n'
#     'def main():\n    print(find_gcc())\n',
#     do_imports=True, filename='probe.mojo')
# print(f"{time.time()-t0:.1f}s, {len(out)} chars")
# PY
# ```
# The snippet's `do_imports` closure is 59 modules and REACHES THE COMPILER'S
# OWN MODULES (`build_config` -> `module_loader` -> ... -> `gimple_codegen` /
# `fire_compiler`, ~88 MB of generated C). That is why this is the expensive
# shape: every per-module pass runs against compiler-sized trees.
# 
# ## Observed (precise per-function timers, instrumented run, 285s wall)
# ```
# mojo.backend_gimple.emit_infra._local_bindings:        24954 calls,  90.42s
# mojo.backend_gimple.module_gen._drop_unreferenced_unimpl_stubs: 59 calls, 15.85s
# mojo.backend_gimple.module_gen._seed_selfhost_module_globals:  56 calls,   5.21s
# mojo.middle.literal_bindings (bound_names):              60.26M calls, 31.64s  <- REMOVED by the MIDDLE fix
# ```
# 1s stack sampling of the UNFIXED compile agrees: `_iter_ast`/`_add_binders`
# (== the two above) dominate; the one-time `_seed_selfhost` tokenization
# (43 compiler files) is a fixed ~5s and already per-file cached in
# `_SELFHOST_PARSE_CACHE`.
# 
# ## Hotspot 1 — `emit_infra._local_bindings` (the big one)
# `mojo/backend_gimple/emit_infra.py:3571` walks the WHOLE current function
# body (`gen._cur_func_body`) with `stmts_shared._iter_ast` (a deliberately
# unmemoized walker) for every QUERY, and `tagged_mixed_name` /
# `tagged_for_target_name` query it per statement, per name, during statement
# emission. That is O(S²) per function: on a compiler-sized function body
# (~1500 statements) every one of the ~300 assign statements pays a full-body
# walk. It is the same defect class as the binder census (re-derive a
# per-scope census per consumer call) in a different tier, with a third copy
# of the AST walk (`stmts_shared._iter_ast` "mirrors gimple_gen_coro._walk").
# 
# Next step: memoize the per-name answer per function body (key: `id(body
# list) + name`, dropped at the body's mutation sites / function boundary), or
# re-derive `_local_bindings` from the middle-tier binder census (`literal_bindings.scope_index`) so there is one census and one walker — the latter is the CLAUDE.md "no parallel implementations" shape but changes
# a subtle emission rule (its for-target regex over-counts), so measure the
# generated C before/after (byte-identical standard applies).
# 
# ## Hotspot 2 — `module_gen._drop_unreferenced_unimpl_stubs`
# `mojo/backend_gimple/module_gen.py:1582` is O(parts²) per module: for each
# of the 3 stub names it regex-scans EVERY other part's text for each part
# (59 modules × up to ~1.5k parts each). Next step: concatenate the parts once
# per name (or collect the set of referenced names in one pass) and test
# membership — the keep/drop decision is unchanged, so this is a pure speedup
# with the same byte-identical generated C expected.
# 
# ## Expected
# The repro compile of a compiler-sized `do_imports` closure finishes in well
# under a minute (the one-time work — tokenization, first walks, C emission —
# is the floor; the two per-module rescans above are what keep it at 177s).
# 
# ## Why this is a doc and not a fix in the MIDDLE commit
# The MIDDLE fix is scoped to `mojo/middle/literal_bindings.py` +
# `mojo/middle/coro.py` (the bug's claim and next step), and the two
# residuals live in `mojo/backend_gimple/`. Landing them in the same commit
# would mix tiers and step on the parallel `perf-nested-module-compile-walk`
# lane.