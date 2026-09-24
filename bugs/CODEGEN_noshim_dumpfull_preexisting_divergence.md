# CODEGEN_noshim_dumpfull_preexisting_divergence: check-native-dumpfull fails on b00955c itself

## Status (2026-09-24, tenth entry — AST/TOK-DIFF and SELFHOST-CRASHED both driven to ZERO; 11 root causes fixed + one pulled-in build blocker unblocked; the whole remaining backlog is CI-DIFF)

Session started from the two `formal/` sweep commits (`219e88c`, `089ceb3`)
on top of the ninth entry's state. NOTE: the whole tree could NOT self-build
when this session began — `089ceb3`'s new `_lbn_compr_targets` had a nested
loop that aborted `python3 fire.py build` with a hard C error (see item 5).
Fixes, ordered by discovery:

1. **`comptime_aliases` dict key was a POINTER decimal** (`fire_compiler.py`
   `_parse_struct`). `aliases = {s.target: s.value for s in body if
   isinstance(s, ComptimeVarStmt)}` — the comprehension's element `s` is an
   unknown-typed list element, so `s.target` lowered through runtime dispatch
   and its boxed int64_t result was stored via `mojo_str_from_int`, making
   every alias key `'51753641216'` instead of `'name'`. Rewritten as an
   explicit loop through a new `_as_comptimevar_node` static view (the same
   idiom the sibling `_alias_by_name` loop already uses). Fixes 6 of the 13
   `--dump` AST-DIFF files (`std/_plugin/{_trait,cuda,hip,metal}` +
   `device_attribute`, `_nicheable`).

2. **`mojo_repr_float` used 6-significant-digit `%g`** (`runtime/fire_runtime.c`).
   `repr(3.141592653589793)` came out `3.14159`. Now widens precision 1..17
   and stops at the first `strtod()` round-trip, reproducing Python's
   shortest-round-trip repr. Fixes `std/math/constants`' AST-DIFF.

3. **`_mojo_classattr_init()` was never called in the compiled binary**
   (`emit_funcs.py` `_gen_toplevel`). The call lived only in `gen_func`'s
   `node.name == 'main' and emit_struct_defs` branch — correct for a
   single-module program, but `main` belongs to the ROOT module while the
   class-attr table can live in an IMPORTED module whose TU has no `main`.
   The whole-program binary lands in exactly that shape: the disassembly
   (`otool -tvV mojoc`) showed a single `_mojo_classattr_init` symbol with
   ZERO `bl` targets. Now also emitted at the top of every module's
   `_toplevel` (gated on `emit_struct_defs`, the same flag that emits the
   definition), so it runs whichever module owns it.

4. **`CallExpr.kwargs` / `StringLiteral.is_bytes` absent from the hardcoded
   `struct_field_types` map** (`module_gen.py`). The C struct HAS the fields,
   but the typer map did not, so even a statically-typed `_cnode.kwargs`
   read fell back to `_mojo_dispatch_getattr` and returned the miss sentinel
   `1`. Registered both (the audit tool
   `tools/audit_selfhost_struct_fields.py` flags these as the remaining
   non-line/col gaps; `FromImportStmt.name_alias_strs` still deferred — the
   ninth entry noted it was net-negative on its own).

5. **BUILD BLOCKER (pulled in by `089ceb3`): `_lbn_compr_targets`'s nested
   `for x in item:` mis-typed `x`** (`mojo/middle/boundnames.py`). The
   self-hosted inference typed `item` as `char *` (a str), so `x` became a
   plain `char` and its use as an int64_t recursion argument emitted
   `x = (char *)_mojo_dict_iter_key(...)` — a real `-Wint-conversion` HARD
   ERROR that aborted every `python3 fire.py build`. Flattened to a single
   `for _elt in expr:` over `isinstance(expr, (list, tuple))` (a tuple still
   descends, because it hits the same branch on the next call).

6. **The 24-file `mojo_list_len(0x1)` SIGSEGV class, root-caused to a
   `gcc -fgimple` MISCOMPILE** (`emit_methods.py` `lower_struct_method_call`).
   The condition
   `if _method_candidates and (len(_method_candidates) > 1 or _cnode.kwargs):`
   lowers `if <list>` to `len(<list>) != 0`, then calls `len(_method_candidates)`
   AGAIN for the `> 1` test. `-fgimple` then reuses the FIRST `len` call's
   return value (a LENGTH) as the SECOND call's POINTER argument — so a
   1-element candidate list produced `mojo_list_len(1)`. Worse, the `or`
   mixed an int comparison with the list-valued `_cnode.kwargs`, so the whole
   condition was typed `MojoList *` and the enclosing `if` became
   `mojo_list_len(<the boolean>)`. Rewritten to compute `_n_candidates`/
   `_n_kwargs` into explicit ints and compare them, so every operand is bool
   and each container is measured exactly once. This alone took
   SELFHOST-CRASHED 24 → 15 (interval/dict/counter/deque/set/dtype/
   string_literal/span/bencher all now compile).

Per-file `--dump` sweep after the fixes (only the ~40 affected files were
re-run; the rest of `bside/` is stale, so CI-DIFF is not yet a valid total):
clean 58 → 67, SELFHOST-CRASHED 24 → 15, **AST/TOK-DIFF 13 → 0**. `mojoc`
rebuilds clean; `interval.mojo`/`raw=`/`comptime_aliases`/float all verified.

**Continuation (same session): the remaining 15 crashes and the last
AST-diff class fixed; full clean re-sweep now SELFHOST-CRASHED 0 /
AST-TOK-DIFF 0.**

7. **`selfhost_param_ctype` hook was a capturing nested `def`** (repro
   `std/atomic/atomic.mojo`). `module_gen.py` installed a nested closure
   wrapper and `closures.py` called it through
   `getattr(ctx, 'selfhost_param_ctype', None)`. The wrapper captures `self`,
   so its stored value is a CLOSURE (a data pointer); the dynamically-typed
   `_hook(...)` call lowered to `mojo_fnptr_call_3`, which jumped to that
   data pointer and SIGBUS'd. Fixed by assigning the module-level,
   NON-capturing `_ggf_dup._selfhost_gen_self_param_ctype` directly and
   passing `ctx` explicitly (4-arg call) in `closures.py`. This cleared the
   whole remaining crash set.
8. **`TypeLattice.is_float/is_int/...` crashed on a NULL type**
   (`mojo/middle/types.py`). `None in _TYPE_FLOAT` / `'*' in None` lower to a
   runtime `in` whose `strcmp` dereferenced the NULL (SIGSEGV in
   `_dict_lookup` via `mojo_in_dispatch_str`). Guarded every predicate with
   `if not t: return False`. Repro: `std/runtime/tracing.mojo`'s
   `join(t1=NULL, ...)`.
9. **`gimple_ctypes.dataclasses.fields(...)` (aliased form) not recognized**
   (`mojo/middle/types.py` `_is_dataclasses_module_ref`, used by 3 sites in
   `emit_methods.py` + 1 in `emit_loops.py`). The interception/loop tracking
   matched only the bare `dataclasses` IdentExpr, so the alias form
   `import mojo.middle.types as gimple_ctypes` fell through to dynamic
   attribute access; `f.name` then raised `AttributeError('name')` and
   `compile_to_gimple` bailed to an EMPTY `.ci` (repro: `std/collections/
   deque.mojo` 0 B → 206 KB, `bitset`, `test_gimple`, …).
10. **`StringLiteral` seed map broke repr field order**
    (`module_gen.py`). Adding `is_bytes` to the seed put it BEFORE the
    augmentation's `line`/`col`, so the native repr printed
    `value, is_bytes, line, col` where Python prints `value, line, col,
    is_bytes` — 64 `.ast` diffs. Fixed by seeding `line`/`col` ahead of
    `is_bytes` so the seed stays a prefix of the dataclass field order.
11. **`_renamed_builtin_calls` emission boxed the return-type string**
    (`module_gen.py`). The inline dict-`.items()` comprehension's 2-tuple
    unpack boxed `rt`, so a C TYPE NAME f-stringed as its pointer decimal:
    `4370499496 mojo_index(...);` instead of `int64_t mojo_index(...);`
    (repro: `std/test/builtin/test_uint`). Rewritten as an explicit loop with
    `_as_str` (the established fix family).

**Full clean re-sweep (both `aside` and `bside` regenerated after all
changes), the TRUE current state: 765 files — clean=72, CI-DIFF=690,
SELFHOST-CRASHED=0, AST/TOK-DIFF=0, SHIM-FAILED=2, BOTH-FAILED=1.**

**Continuation 2 (CI-DIFF triage): clean 72 -> 146; CI-DIFF 690 -> 616.**
Worked the CI-DIFF backlog by repeatedly taking the files with the FEWEST
differing lines (the closest to clean) and fixing the one root cause each
turned up. Fixes, roughly in order of files-fixed-per-fix:

12. **`_method_overload_id` used `hashlib.md5`, which the compiled backend
    stubs** (`mojo/middle/types.py`). Every overload of a name got the SAME
    suffix: `CStringSlice___init___cbf29c` + `_2`/`_3` where the reference
    emits distinct `_d264de`/`_76edc3`/`_10ada0`. Replaced with the same
    hand-rolled polynomial hash `emit_funcs.overload_suffix_for` already
    uses (both sides now agree). (c) in the class list above.
13. **`_walk_type_expr` could not recognize a plain-STRING type annotation
    self-hosted** (`isinstance(<char*>, str)` is unreliable), so it fell to
    `type(node).__name__` == `'<type>'` — overload sigs became
    `self:any,value:<type>` vs the reference's `self:any,value:Self._mlir_type`.
    The trailing fallback now re-views via `_as_str`. Also removed an
    `id(node)`-keyed memo cache (address-dependent).
14. **`mojo_repr_float` used `%g`/wrong formatting** — now Python's exact
    repr: shortest round-trip precision, fixed notation for
    `1e-4 <= |v| < 1e16`, scientific outside (verified against CPython on 15
    values incl. `1e9`, `1e16`, `-0.0`, `1/3`).
15. **`mojo_repr_int`/`mojo_repr_float` returned a shared `static buffer`**
    (`runtime/fire_runtime.c`) — two live `repr()` results aliased, so the
    compiler's `_lower_ListExpr` emitted `[2.0, 3.0]` as `3.0, 3.0`. Both now
    `strdup` a fresh copy.
16. **`_lower_FloatLiteral` read `node.value` reflectively** (double boxed to
    int64_t and TRUNCATED) — new `_as_floatlit_node` static view gives a
    direct `double` load (`4.2`/`0.1`/`1.5` were emitted `4.0`/`0.0`/`1.0`).
17. **`_safe_coerce_emit` emitted an EMPTY cast `()val`** when either side's
    type was erased — now falls back to `int64_t`. Repro
    `std/test/builtin/test_int.mojo`'s `var a, b = divmod(7, 3)` (`a = ()_t5`).
    `_tuple_elem_value`'s unknown-element case and `_assign_target`'s
    declaration also default to `int64_t` now.
18. **`_decode_str_literal_text`-driven f-string join boxed the value slot** —
    a no-interpolation f-string interned a pointer decimal
    (`_slit_10070 = "33323208400"`; repro `test_dispatch_promotions.py`'s
    `f"...(def->fn):"`). The `_pv2` piece now goes through `_as_str`.
19. **`isinstance(<char*>, str)` is unreliable, so `mlir.unwrap`'s
    `m[0] == '`'` indexing test was always False** — backticks never
    stripped; switched to `startswith`/`endswith` (an earlier pass in this
    file already fixed the same shape at `emit_funcs.overload_suffix_for`).
20. **`gen._comptime_vals.get(name)` returns `0` (not `None`) for a missing
    key natively**, so `isinstance(_, int)` was True and an unknown
    identifier skipped the `/* ct param or undeclared: <name> */` placeholder
    branch. Guarded with a `name in gen._comptime_vals` membership test.
21. **Numeric-literal underscores not stripped before `int(t.value, 0)`** —
    the compiled `int(str, 0)` stops at `_`, so `0x2000_0000` parsed as
    `0x2000` (8192 vs 536870912; repro `test_print_long_string.mojo`).
22. **`sys.exit(main())` not detected as a toplevel `main()` call** — extended
    the shallow `_sm_stmt_calls_main` scan to inspect call arguments, so the
    wrapper stops emitting a double `_gimple_main ()`.
23. **`gimple_ctypes.dataclasses.fields(...)` (aliased module form) not
    recognized** by the interception/loop tracking (`_is_dataclasses_module_ref`).
24. **A comptime value that is a STRING was treated as an int** — a boxed
    `char *` satisfies `isinstance(_, int)` self-hosted, so `str(_ct)`
    emitted the pointer decimal instead of the placeholder; guarded with
    `_ptr_slot_in_range` (a genuine comptime int is not a heap pointer).
25. **`_exc_type_id`/`coro._exc_type_tag` used `zlib.crc32` (stubbed
    self-hosted)** so EVERY exception got id `1` where the reference emits
    the real crc32; added a pure-Python `types._crc32_str` (verified equal to
    `zlib.crc32` for AttributeError/StopIteration/struct.error/…) used by both.

**Final state after continuation 2: 765 files — clean=147, CI-DIFF=615,
SELFHOST-CRASHED=0, AST/TOK-DIFF=0, SHIM-FAILED=2, BOTH-FAILED=1.**

STILL OPEN — 616 CI-DIFF, now with a much flatter tail of mostly
single-cause files: (a) local pointer-vs-scalar type inference
(`int64_t * _t1` vs `int64_t _t1`, `uint16_t _t2` vs `uint16_t * _t2`),
(b) `_MOJO_STUB_*` set differences (the self-hosted resolver misses some
cross-module symbols), (c) a comptime value that is a STRING treated as an
int (`str(_ct)` of a boxed pointer; `_comptime_vals`), (d) `len(<Span *>)`
unlowered, (e) `extern int chdir (char *)` losing its parameter type,
(f) `_plugin/*/__init__` dispatch/stub registration. Each is a small,
targeted fix; the `score`-ranked sweep (`fewest differing lines first`) is
the efficient way to keep working them.

**Continuation 3 — ROOT-CAUSED AND FIXED: `_walk_ast_into` truncated the
whole walk self-hosted. clean 147 -> 155; CI-DIFF 615 -> 607; crashes 0.**

The "isinstance is constant-false" symptom above was a red herring. The real
root is in `mojo/middle/exprtypes.py`'s `_walk_ast_into` (the generic AST
walker behind EVERY struct-field scan, closure/async pre-pass, and
`_seed_addressed_locals`): the scalar early-return
`isinstance(node, str/int/float/bool)` is lowered for an int64_t-boxed value
to a NON-NULL test (`_isinstance_one_type`'s static `_SCALAR_TYPE_MATCH`
branch), and every AST node is a pointer boxed as int64_t — so an AST node
was mistaken for an int and the walk returned WITHOUT descending into its
fields. Measured directly: `_seed_addressed_locals`'s `_walk_ast(body)`
returned **3 nodes where the reference returns 64**, so `UnsafePointer(
to=value)` was never pre-registered. Fixed by walking dataclass fields FIRST
(a genuine int/str/float is never a dataclass), then the scalar check.

Once the walk was complete, the `UnsafePointer(to=value)` chain had three
more self-hosted gaps, each fixed:
- `_seed_addressed_locals` iterated `for k, v in (node.kwargs or [])` — the
  same 2-tuple-unpack boxing trap; rewritten as an index loop with `_as_str`
  on the key and `_as_ident_node` on the value.
- `_lower_call`'s addressed-local test `_to_expr.name in gen._addressed_locals`
  read `.name` reflectively (a POINTER); now `_as_str(_as_ident_node(_to_expr).name)`.
- `_addressable_to_target` used `re.fullmatch(r'[A-Za-z_]...')` / `re.fullmatch(
  r'_t\d+')`, and `re.fullmatch` is unreliable self-hosted (returned None for
  a plain identifier), rejecting EVERY scalar target. Both guards dropped —
  the final `aval in gen.var_types` membership already restricts to real
  locals/params.
Effect: all five `std/test/memory/uninit_check/*` files are clean (were
`(uint64_t *)0` vs `&value`).

The complete walk newly reaches async units the truncated walk missed. That
exposed one latent artifact — `gen_cpp_async_unit`'s `body_lines` local was
NULL at its trailing `body_lines.append("    co_return;")`
(`mojo_list_append_str(0, ...)` SIGSEGV) for `test/runtime/test_locks` and
`std/gpu/host/device_context` — fixed defensively (`if not body_lines:
body_lines = []`; `not NULL` is true, `not <valid empty list>` false, so the
same `co_return;` is emitted either way). Those files are now CI-DIFF, not
crashes.

STILL OPEN: the comptime-`_eval_const`-isinstance instance from the earlier
write-up was NOT this bug and remains (a `comptime idx = 0` local still hits
the placeholder); the `struct_field_types`-order hypothesis for it is not yet
confirmed.

**Final state after continuation 3: 765 files — clean=155, CI-DIFF=607,
SELFHOST-CRASHED=0, AST/TOK-DIFF=0, SHIM-FAILED=2, BOTH-FAILED=1.**

## Status (2026-09-21, ninth entry — SIX more self-hosted-only bugs fixed; `check-ab-native` now 30/30 (was 25/30); `make bootstrap` verify failures 14 → 9; whole-program first-diff moved 52 KiB → 143 KiB; the remaining divergences are the documented architectural classes, not these bugs)

Picked up the WIP `fire.py`/`ownership_destruct.py` changes and worked the
gated `check-ab-native` corpus (30 cases) plus the whole-program
`--dump-full` compare. Root-caused and fixed six independent real bugs, all
verified by rebuilding `mojoc` and re-running the corpus, and all still
green through the full gate below (except the two known-divergent
whole-program targets). Ordered by discovery:

1. **Loss of a function's signature when aliased to a local**
   (`gimple_module_gen.py`'s `_scan_for_closures`). The closure pre-pass
   aliased the hoisted helper (`_all_stmts_nonfunc = _gmi_all_stmts_nonfunc`)
   and then called it through the local; `_lower_fnptr_call`'s
   `func_return_types.get(fname_raw, 'int64_t')` looks up the LOCAL's name,
   found nothing, and defaulted the call's result to `int64_t`. The
   `for stmt in <call>` loop then bound its element `char *` (not int64), so
   `isinstance(stmt, FunctionDef)` constant-folded FALSE — the self-hosted
   compiler registered NO closures at all (every nested `def` became a
   `_MOJO_STUB_*`), which is `check-ab-native`'s `nested_func`/`closure`
   and a whole class of `make bootstrap` divergence. Fixed by calling
   `_gmi_all_stmts_nonfunc(...)` directly (the pre-hoist shape, which was
   correct; the alias was a mechanical artifact of commit `0b2912d`).
2. **`case _:` lowered as `case 0:`** (`gimple_gen_stmts.py`,
   `gimple_module_gen.py`). The wildcard test
   `any(isinstance(p, IdentExpr) and p.name == '_' for p in
   match_case.patterns)` hit `/* TODO: comprehension over int64_t */` — the
   generator-comprehension lowering materialized an EMPTY list +
   `mojo_list_any`, i.e. always False. Also, `MatchCase` was absent from the
   hardcoded AST struct table and `MatchStmt.cases` had no element type, so
   `match_case` was int64_t and `.patterns` untyped. Fixed by registering
   `MatchCase`, seeding `_field_elem_types['MatchStmt']['cases'] =
   'MatchCase *'`, and rewriting the test as an explicit loop (whose
   int64_t element gets a real `mojo_read_type_tag` `isinstance`).
3. **`_intersect_all` bitwise-ANDed heap pointers** (`ownership_destruct.py`).
   `sets[0] & sets[0]` / `out & sets[i]` on elements read from an UNTYPED
   `list` (erased to int64_t) is C bitwise `&`, not `set.intersection` — the
   docstring's claim that `&` "recovers the real MojoSet*" only held when
   the elements were already statically `MojoSet *`. ASan (rebuilt per
   entry 8's recipe) confirmed the heap-buffer-overflow: `mojo_set_update`
   in `_dfa_stmt`'s loop arm read past a 32-byte list allocation for BOTH
   `list_ops` and `dict_iterate`. Fixed with a `_set_view(x: set) -> set`
   coercion helper on every element (module-level alias, NOT a class attr —
   see bug 5).
4. **Invalid GIMPLE for large int literals** (`gimple_gen_exprs.py`'s
   `_lower_IntLiteral`). Entry 8's `< 0` branch emitted `(uint64_t)(-1LL)`,
   which `gcc -fgimple` REJECTS as a statement RHS ("expected expression
   before '(' token"); making the CPython path emit it too broke the stdlib
   dylib build for every module with such a literal (e.g.
   `std/_fnv1a.mojo`). Both paths now materialize the SAME `_t = -1ULL;`
   assignment (a bare signed `ULL` token is GIMPLE-valid as an assignment,
   though NOT as a direct binary operand — hence the temp), which also
   restores byte-identity.
5. **`TypeLattice._SIGNED/_UNSIGNED/_FLOAT` were never initialized**
   (`gimple_ctypes.py`). They alias imported globals as CLASS attributes;
   the self-hosted `_mojo_classattr_init` emitter only materializes
   literal/`{}`/`[]` RHS, so those globals stayed 0 → `join()` fell through
   to `int64_t` for every mixed-type expression. Real symptom: `1.5 + 2`
   lowered to int64 arithmetic natively (vs `double` from the reference),
   and the `0xFFFFFFFFFFFFFFFF` mask idiom lost its unsigned promotion.
   Fixed by reading the tables from MODULE-LEVEL aliases
   (`_TYPE_SIGNED = _GD_SIGNED`, the same shape as the working `_BIN_OPS`
   alias) instead of class attributes.
6. **Imported-module scan bound its loop var `char *`**
   (`gimple_module_gen.py`). `for _ms in stmts + (imported_stmts if ... else
   [])` — the list concatenation carried a `char *` element type, making
   BOTH `isinstance(_ms, ImportStmt)` and `isinstance(_ms, FromImportStmt)`
   constant-false. Every module named by `import`/`from ... import` lost its
   `struct _<mod>_toplev`/`extern _<mod>_globals` forward declaration
   (`t1.mojo`'s missing `_sys_toplev`). Fixed by hoisting the scan into
   `_gmi_scan_import_modules(mod_stmts, ...)`, whose unannotated list
   parameter yields generic int64_t elements (`_gmi_all_stmts_nonfunc`'s own
   convention), plus a same-module `_gmi_as_str(x) -> str` helper because an
   IMPORTED `_as_str`'s return type was not resolved at this module-level
   call site (the key was becoming `mojo_str_from_int(<pointer>)`, a decimal
   address).

**Gate after these fixes**: `check-ab-native` 30 passed / 0 failed (`--dump`
corpus, including the previously-informational `test_simple.mojo`, which is
now byte-identical); `check-gimple` 308/0; `check-modcache` 81/0;
`check-selfhost` 1/0; `check-runtimediff` 24/0; `check-linkmode` 3/0;
`check-no-new-casts` 1/0; stdlib dylib rebuild **0 module skips**;
`compile_stdlib.py` **FAILED: 0 (0 expected, 0 unexpected)**. The
whole-program `--dump-full fire.py` no longer crashes (stage2/stage3
complete).

**Continuation (same session): three more real bugs fixed; `make bootstrap`
`verify` down to 8 files (14 → 8 total).**

7. **`os.path.join(d, *parts, suffix)` dropped args / mishandled the spread**
   (`gimple_gen_methods.py`'s `os.path.join` lowering). The 2-arg fast path
   silently ignored everything past the second arg, and the `*`-spread
   pass-through handed the raw `MojoList` to `int_join` as if it were a
   single path part. `_resolve_test_relative_module`'s
   `os.path.join(d, *rel_parts, '__init__.mojo')` therefore built a wrong
   candidate under the self-hosted binary, so a sibling import resolved
   from a `stage2` CWD found nothing. Fixed by expanding every `*`-spread
   into a combined `MojoList` and routing through `int_join_list`.
8. **`module_name_for_path` derived a CWD-dependent qualifier**
   (`module_loader.py`). Outside `STDLIB_PATH` it fell back to
   `os.path.relpath(path, STDLIB_PATH)` and tested `rel.startswith('..')`
   — but `os.path.relpath` is a self-host codegen STUB returning its first
   arg unchanged, so a RELATIVE `runtime/test_helper.mojo` came back
   verbatim and produced the qualifier `runtime_test_helper` where CPython
   produced `test_helper`. Every imported symbol got a different C symbol
   prefix (`runtime_test_helper_mojo_double_9f63a2` vs
   `test_helper_mojo_double_9f63a2`). Fixed by returning the basename
   directly whenever the path is not under `STDLIB_PATH`, with no relpath.
9. **`_emit_stdlib_import_externs` skipped local siblings, and emitted a
   redundant decl for TEST_PATH modules** (`gimple_gen_infra.py`). It
   early-`continue`d on `not can_resolve_module_path(mod)`; `TEST_PATH =
   join(HERE, 'runtime')` with `HERE = dirname(abspath(__file__))` is the
   SCRIPT dir for python3 vs the process CWD for the binary, so a
   `stage2`-CWD build skipped `test_helper` while the python3 reference
   emitted a `_MOJO_STUB_<name>` forward-decl the native side lacked. That
   block is redundant with `_register_sym`'s own `/* from <mod> */` extern,
   so the fix restricts this stdlib-emitter to genuine `std`/`std.*`
   modules — both paths now agree, and the `_own_imported_func_home` /
   `func_return_types` bookkeeping still runs for every module.

**Continuation 2 (same session): three MORE real bugs fixed; `make bootstrap`
`verify` down to 7 files (14 → 7 total).**

10. **Nested-closure `gen._emit` override not run self-hosted**
    (`gimple_gen_stmts.py`'s `_emit_exits`). Hoisted `_emit_exits` (the
    `with`-item teardown emitter) from a nested closure reading `_ctx_ts`
    et al. to the module-level `_with_emit_exits(gen, ...)`, with `_as_str`
    on every element read out of the untracked list params (the str slots
    otherwise erased to int64_t, e.g. `/* with: __exit__ (4376542048) */`).
    Fixes `fire_main.ci`'s missing `/* with: __exit__ (int64_t) */`.
11. **Keyword-argument NAME stringified to its pointer's decimal**
    (`gimple_gen_calls.py`'s `kwarg_dict` and `gimple_gen_methods.py`'s
    `kwarg_map`). Both build a dict from `node.kwargs` via a comprehension
    whose tuple-unpack reads the NAME with `mojo_list_get_int`; the key
    then erased to int64_t and was stored via `mojo_str_from_int` — the
    char* POINTER as a decimal address, so `'do_imports' in kwarg_dict`
    never matched. Real divergence: `mojo.mojo`'s
    `gimple_codegen.compile_to_gimple(src, do_imports=True,
    filename=input_file)` compiled natively to `(src, 0, "")`. Fixed with
    same-module `-> str` identity helpers (`_ggc_as_str`/`_gmm_as_str`) on
    the key, since the IMPORTED `_as_str`'s `-> str` return type is not
    resolved at a module-level call site.
12. **`module_name_for_path` / `os.path.join`-spread** — see 7/8 above
    (listed here for completeness of the "9 → 7" count).

**Continuation 3 (same session): `mojo.ci` fixed too; `make bootstrap`
`verify` down to 6 files (14 → 6 total).**

13. **`break`/`continue` out of a `try` lost its `mojo_exc_pop()`**
    (`gimple_gen_stmts.py`). The pop was emitted by the same nested
    `intercepted_emit` `gen._emit` override class as bug 10 (it did not run
    self-hosted), so `mojo.mojo`'s REPL loop silently skipped it. Fixed by
    emitting the pops directly from `_gen_stmt_BreakStmt`/
    `_gen_stmt_ContinueStmt` via a new `_emit_try_loop_exit_exc_pops(gen)`
    that counts open `try` protected regions (`gen._try_loop_protect`,
    pushed around each try body), and removing the interceptor's
    break/continue branch. First attempt regressed the build with
    `IndexError: pop from empty list` inside `_gen_stmt_TryStmt`
    (a nested function/nested try compiled from the body left the shared
    list shorter than expected) — fixed by save/restore of the list
    (`_saved_tlp = list(...)` ... `gen._try_loop_protect = _saved_tlp`)
    instead of a bare append/pop.

**Continuation 4 (same session): `stdlib_core.ci` fixed; `make bootstrap`
`verify` down to 5 files (14 → 5 total).**

14. **`not <empty container/string>` is pointer-nullity self-hosted, not
    Python truthiness** (`gimple_gen_calls.py`'s `_lower_opaque_ctor`
    gate). Two clauses of the opaque-constructor fast-path gate used
    `not` on a value that is a non-null pointer when "empty":
    `not gen.func_return_types.get(fname_raw)` (this compiler's own
    `func_return_types['StringRef'] == ''` — an empty MojoStr, non-null)
    and `not getattr(node, 'kwargs', None)` (an empty kwargs MojoList*,
    non-null). Both `not`s yielded False self-hosted where python3's
    string/list truthiness yields True, so the char*-argument fast path
    never ran and `StringRef("")` boxed to `(int64_t)` — the exact
    `stdlib_core.mojo` divergence. Fixed by comparing the return type
    against both `'int64_t'` and `''`, and by testing
    `len(_ctor_kw) == 0` instead of `not <list>`. (This is the same
    documented class as `_gen_stmt_FunctionDef`'s `len(ci.captures) > 0`
    note.)

**Continuation 5 (same session): `bootstrap-validate.ci` fixed;
`make bootstrap` `verify` down to 4 files (14 → 4 total).**

15. **`_param_elem_types` keyed by a boxed POINTER, not the name string**
    (`gimple_module_gen.py`'s `_record_param_elem`). A nested function's
    untyped `callee`/`pname` params lift to int64_t self-hosted, so
    `setdefault(callee, {})` stored a pointer key and every later
    string-keyed lookup (`_pe.get('compare_stages')` in `gen_func`) MISSED
    — the callee's container param never inherited its element type, so
    `compare_stages`'s `for ext in extensions:` typed `ext` int64_t (and
    `base + ext`) instead of `char *`. Fixed with `_as_str` on both names
    (the same boxing trap the sibling loops in that pass already guard).
16. **Nested-closure param erased to int64_t in a tuple-slot read**
    (`gimple_gen_loops.py`'s `_emit_target_assign`/`_emit_slot_read`).
    These nested helpers used their own `ptr` parameter in an f-string, but
    the untyped param lifted to int64_t and `f"{ptr}"` stringified the
    `char *` TEMP-NAME as its decimal ADDRESS, emitting
    `mojo_list_get_str (33869245776, 0)` instead of `(_t17, 0)` — a real,
    minimally-reproducible (`for path, base in [("aa","bb")]`) divergence
    that was `bootstrap-validate.mojo`'s remaining first diff. Fixed with
    `_as_str(ptr)` at every `{ptr}` use.

17. **Dispatch-table solving kept on the python3 path but dropped
    self-hosted** (`gimple_module_gen.py`). `DispatchTable`'s own
    `dispatch_type`/`struct_fields` fields don't carry their types across
    the self-host boundary (the `emit_typedef()`-malformed validation a few
    lines below exists precisely because of that), so the self-hosted
    binary's `emit_typedef()` returns malformed text, the validation drops
    EVERY planned table, and that compile falls back to dynamic dispatch.
    The python3 reference has no such erasure, so it KEEPS the tables and
    emits `parser_struct_dispatch_t` + devirtualised call sites the native
    side never emits — the first diff of `fire_compiler.ci`. Fixed by
    skipping the solve entirely for `_is_selfhost_file` files, so both
    sides take the SAME (dynamic-dispatch, always-correct) path. This
    removed that divergence class (fire_compiler's first diff moved from
    the table to the string-pool region, and its `.ci` shrank ~10 KB); the
    files still diverge for the remaining architectural reasons below.

**`make bootstrap` `verify` now fails on 4 files**: `fire_compiler.ci`,
`fire.ci`, `module_loader.ci`, `myinterpreter.ci` — the remaining
previously documented classes (nested-fragment emission order / string-pool
renumbering; `module_loader.ci`'s `_mkfn` param inferred `char *` python3 vs
`int64_t` self-hosted; `myinterpreter.ci`'s missing
`_build_math_shims_lambda_N` forward decls). Diffs are large
(`fire_compiler` ~48k lines, `fire` ~1.5M lines); this is the architectural
project `_dedup_module_toplev_structs`' docstring describes.

**Not attempted**: those. Twenty bugs landed across this entry; full
CLAUDE.md gate re-run after this continuation: `check-gimple` 308/0,
`check-modcache` 81/0, `check-selfhost` 1/0, `check-linkmode` 3/0,
`check-no-new-casts` 1/0, `check-ab-native` 30/30, stdlib dylib
**0 skips**, `compile_stdlib.py` **0 unexpected**.

**Continuation 6 (same session): seven more self-host codegen classes
fixed; the 4 remaining files' diffs shrank substantially (fire_compiler
47.6k → 32.1k diff lines, module_loader 10.6k, myinterpreter 31.3k) but
each still has a long tail of distinct issues.**

18. **`struct_field_types` dataclass-annotation pass read a boxed
    `field.type_ann`** (`gimple_module_gen.py`). `str(field.type_ann)` /
    `_mojo_type(field.type_ann)` on a self-hosted `VarDecl`/`AssignStmt`
    field returned the annotation's POINTER decimal, so `is_bytes: bool`
    was never registered in `struct_bool_fields`, `object`-annotated
    fields never in `struct_boxed_fields`, and the `_mojo_repr_*`
    reflection helpers diverged (`is_bytes` as int vs bool, `exc_type` as
    int vs boxed). Fixed with `_as_str(field.type_ann)` throughout.
19. **Dispatch-table solve kept on python3 but dropped self-hosted** — see
    17 above.
20. **`_local_struct_names` was a set comprehension that came back empty
    self-hosted** (`gimple_module_gen.py`), so `_struct_method_qualifier`
    never saw a file's OWN structs as local and emitted
    `fire_compiler_Parser___init__` instead of the bare `Parser___init__`.
    Fixed with an explicit loop + `_as_str`.
21. **`zip()` rejected every no-keyword call** (`gimple_gen_loops.py`) —
    `if it.kwargs:` on an EMPTY kwargs list (non-null pointer, truthy
    self-hosted) raised, fell back to `mojo_unsupported_iter`, and ran the
    loop ZERO times (fire_compiler.py's own
    `for op, operand in zip(node.ops, node.operands[1:]):` silently
    dropped the rest of `emit`).
22. **`zip()` rejected every tuple loop target** — `isinstance(target,
    str)` is the constant-FALSE static guard for a `char *`-typed ForStmt
    target, so `_gen_for_zip`'s target check always raised. Fixed with
    `_as_str(node.target)`.
23. **Swept every remaining `<x>.kwargs` truthiness bug** across
    `gimple_cpp_async/core`, `gimple_exprtypes`, `gimple_gen_calls`,
    `gimple_gen_infra` (`if x.kwargs:` / `not x.kwargs`) to
    `len(x.kwargs or []) ...`.

Remaining first diffs: `fire_compiler` — `_build_enum_struct`'s `members`
param emitted `char *` natively vs `MojoList *` (the inference signals are
IDENTICAL; the emitted signature takes a different path) plus string-pool
order/membership (`"UNK"/"WS"/"XFER"` from
`kind in ("WS","UNK","XFER")` never interned, and `INDENT`/`DEDENT`
interned in the opposite order); `myinterpreter` — lifted lambda forward
decls emitted `(void)` natively vs `(int64_t x)`, plus extra `fn`/`body_fn`
stubs; `module_loader` — `_mkfn`'s `sig` param `char *` vs `int64_t`.

**Not attempted**: that tail. Twenty-three classes/bugs landed across this
entry; full CLAUDE.md gate re-run: `check-gimple` 308/0, `check-modcache`
81/0, `check-selfhost` 1/0, `check-linkmode` 3/0, `check-no-new-casts` 1/0,
`check-ab-native` 30/30, stdlib dylib **0 skips**, `compile_stdlib.py`
**0 unexpected**.

## Status (2026-09-20, eighth entry — the whole-program crash from entry 7 is FOUND AND FIXED (8 real bugs, AddressSanitizer-verified); `make bootstrap` now runs to completion for the FIRST TIME EVER; its own `verify` step then exposed a separate, previously-unreachable pre-existing bug)

Continuing directly from entry 7's "one whole-program crash remains"
(intermittent `EXC_BAD_ACCESS` in `mojo_set_update`, ~1-in-3 failure rate
on raw `./mojoc fire.py --dump-full`, never root-caused despite three
fix attempts). This session finally root-caused and fixed it, then
discovered `make bootstrap`'s own `verify` step — never reached before,
since the crash always killed the process first — fails for a different,
unrelated reason. Both are documented below in full, since both are real
and neither is resolved end-to-end yet.

### Part A: the crash — ROOT-CAUSED AND FIXED

AddressSanitizer (not lldb/MallocScribble alone) was required to pin this
down. **How ASan was made to work despite MacPorts GCC having no ASan
runtime installed**: compile `runtime/fire_runtime.c` alone with
`clang -fsanitize=address` (a scratch copy with `mojo_type(...)` changed
to `mojo_type()` — `(...)` with zero named params before it is a real
ISO C error under clang, unlike GCC, and the function is a `return 0`
stub that never reads its args, so this is behavior-preserving), then
link that object against the GCC-built `fire.o`/`fire.ci` object with
`clang -fsanitize=address`. Both toolchains target the same arm64
Mach-O ABI, so mixing them for a diagnostic build works fine even though
neither would be used for the shipped binary.

Eight real bugs found and fixed, all in code this compiler self-hosts
(none are user-facing Mojo bugs):

1. **`gimple_gen_methods.py`'s `_SELFHOST_SIBLING_MODULE_PREFIXES`** was
   missing `'fire_compiler'` — `gimple_gen_coro.py`'s
   `import fire_compiler as N; N._as_str(...)` calls weren't recognized
   as self-host sibling calls, fell through to the generic unresolved-
   receiver stub path, which mints a PER-CALL-SITE hash suffix from each
   call site's locally inferred argument type instead of resolving to
   the one real `_as_str` definition — two call sites inferring
   different types emitted two different undeclared C symbols
   (`fire_compiler__as_str_d719e0` vs `..._9f63a2`), an implicit-int
   declaration, then a pointer-from-int assignment.
2. **Two `getattr(node, 'field', default)` reads on always-present
   fields** in `ownership_destruct.py`'s `_dfa_stmt` (now `_dfa_try`/
   `_dfa_match`, see below): `ExceptHandler.body` and `MatchCase.body`
   are plain, never-optional `list` fields on their dataclasses (per
   `fire_compiler.py`), but a `getattr(..., default)` read on a self-
   hosted struct goes through the generic dynamic-dispatch path, which
   returns an opaque value with NO element-type metadata even when the
   field is guaranteed to exist. Fixed by direct attribute access.
3. **`isinstance(x, SomeStructType)`/`x.__class__`** blindly called
   `mojo_read_type_tag`/read the tag on ANY value whose static C type
   ended in `' *'` — including `char *`/`MojoList *`/`MojoSet *`/
   `MojoDict *`, none of which carry a tagged-struct header. A real,
   ASan-confirmed heap-buffer-overflow: an 8-byte read past a 5-byte
   `char *` string allocation (`mojo_regex_substr`'s tokenizer output),
   reached via `isinstance(<AST leaf>, SomeNodeType)` inside
   `fire_compiler._scan_yield_bearing`'s generic recursive field walk
   (which recurses into every dataclass field, not just child AST
   nodes — a plain `str`/`int` scalar field reaches the SAME isinstance
   check as a real child node). Fixed with static-false guards in
   `gimple_gen_calls.py`'s `_isinstance_one_type` and
   `gimple_gen_exprs.py`'s `__class__` handling.
4. **General safety net for (3)'s whole class**, not just the one call
   site: `fire_runtime.c`'s `_mojo_tagged_addr_ok` now also checks
   `malloc_size`/`malloc_usable_size` (`MOJO_HAVE_MALLOC_USABLE_SIZE`,
   `__APPLE__`/`__linux__`) and rejects any address whose underlying
   allocation is smaller than the 8-byte tag read needs, on top of the
   existing range/alignment checks.
5. **`_intersect_all`'s single-element degenerate case**: `out =
   sets[0]` (a bare subscript read, no `&` ever applied when
   `len(sets) == 1`) doesn't reliably recover the real `MojoSet*`
   element type from an untyped `list` parameter — confirmed via ASan
   that `out` could come back typed as the ENCLOSING LIST's own pointer
   instead of one of its elements. Fixed: `out = sets[0] & sets[0]`
   (self-intersection), forcing the same `&`-operator type resolution
   already relied on for the `len > 1` loop case.
6. **`_dfa_stmt`'s IfStmt/TryStmt/MatchStmt branches extracted into
   their own top-level functions** (`_dfa_if`/`_dfa_try`/`_dfa_match`).
   This project's own documented fix pattern for self-hosted-codegen
   corruption tied to one enormous function (see
   `gimple_module_gen.py`'s `_emit_reflection_dispatch` history) — the
   monolithic `_dfa_stmt` (~820 locals once self-hosted) was still
   producing the ASan-confirmed `mojo_set_update` corruption even after
   fix 5, with `_ia_if` aliasing `branch_sets_if`'s own `MojoList*`
   despite every individual line of generated GIMPLE reading correctly.
   The exact GCC-level mechanism was never fully pinned down (suspected
   `-fgimple -O0` stack-slot/register allocation pathology specific to
   a function this large), but extraction reliably moved the crash to a
   much smaller, precisely diagnosable function (fix 7), which is
   itself strong evidence the function-size theory was right.
7. **`analyze_function`/`_definitely_assigned`** were each passing a
   `-> set`-returning call's result directly into another call as an
   argument (`_definitely_assigned(fn, facts.candidates())`; `candidates
   & _intersect_all(terminals)`) instead of storing it in a named local
   first — the exact rule this same module documents repeatedly
   elsewhere (`_ia_if`/`_ia_try`/`_ia_match`). Fixed with `_candidates`/
   `_ia_term` locals.
8. **The actual final root cause**: `_FuncFacts.candidates()`'s `for
   name, count in self.assign_count.items():` used `.items()`'s result
   directly as a for-loop's iterable, never stored in a local — the
   SAME rule as (7), but for a loop iterable rather than a call
   argument, and the corruption happens INSIDE `candidates()` itself,
   before it ever returns — which is why fix 7 alone (fixing the
   *callers* of `candidates()`) still hit the identical crash, at the
   identical address, with the identical allocation site
   (`mojo_dict_items` inside `candidates()`), twice in a row. Fixed
   with an `_items` local.

Verified via `AddressSanitizer` (built as described above): the exact
crash class (`heap-buffer-overflow`/`mojo_set_update` reading past a
`mojo_list_new`/`mojo_dict_items`-produced allocation) was reproduced and
fixed incrementally, each fix confirmed by rebuilding and rerunning ASan
against `mojoc fire.py --dump-full` until multiple consecutive runs
(12+ minutes each, well past every prior crash's ~2-7 minute failure
point) completed with no ASan report. The real (non-ASan) rebuilt
`mojoc` was also confirmed to run `fire.py --dump-full` to completion
without crashing.

### Part B: `make bootstrap` now runs to completion — a first — but its `verify` step fails on 14 files for an UNRELATED, pre-existing reason

With Part A's crash fixed, `make bootstrap` was run end to end for the
first time this project has ever gotten that far (every previous attempt
died mid-way through stage2/stage3 on the crash). Stage 1, compiling
`stage2/mojo`, Stage 2, compiling `stage3/mojo` (or the stage2-repeat,
per this Makefile's actual stage numbering), and both stages' own
whole-program `--dump-full fire.py` self-checks all completed —
peak RSS during the whole-program self-check oscillated in the
20-30GB range on a 128GB machine (bursty, not runaway; a much smaller
and clearly bounded pattern than an unrelated isolated worst-case
test described below). `make: *** [verify] Error 1` then failed with:

```
FAIL stage1 vs stage2: bootstrap-validate.ci
FAIL stage1 vs stage2: example_imports.ci
FAIL stage1 vs stage2: fire_compiler.ci
FAIL stage1 vs stage2: fire_main.ci
FAIL stage1 vs stage2: fire.ci
FAIL stage1 vs stage2: module_loader.ci
FAIL stage1 vs stage2: mojo.ci
FAIL stage1 vs stage2: myinterpreter.ci
FAIL stage1 vs stage2: stdlib_core.ci
FAIL stage1 vs stage2: t_argv.ci
FAIL stage1 vs stage2: t_list.ci
FAIL stage1 vs stage2: t1.ci
FAIL stage1 vs stage2: test_relaxed_imports.ci
FAIL stage1 vs stage2: test_simple.ci
```

This is almost certainly **NOT caused by any of Part A's fixes** — it is
a previously-UNREACHABLE pre-existing bug, only observable now that
`verify` is reached at all. Two distinct causes identified in the diffs
(not one root cause):

- **A `_sys_toplev`/`_sys_globals` extern-struct-declaration mismatch**
  (present in `bootstrap-validate.ci`, `fire_compiler.ci`, `fire_main.ci`,
  `fire.ci` — 66 diff lines for `fire.ci` alone —, `mojo.ci`,
  `myinterpreter.ci`): stage1 (python3-interpreted) sometimes emits an
  extra forward-declared `sys` module-globals struct that stage2
  (self-hosted) does not, or vice versa. Not yet root-caused; looks like
  a module-registration-order or a "was `sys` imported at all"
  detection difference between the two paths.
- **A genuine, CONFIRMED PYTHONHASHSEED-dependent non-determinism in the
  python3-interpreted reference path itself**, isolated on `t_list.mojo`
  (`items = [1,2,3]; items.append(4); print(len(items)); print(items[2])`
  — the exact same minimal repro cited throughout this doc's entry 7 for
  the owned-free-candidate mechanism). Confirmed empirically:
  `PYTHONHASHSEED=0 python3 fire.py t_list.mojo --dump` and
  `PYTHONHASHSEED=0` run from `stage1/` via the Makefile's own invocation
  pattern (`cd stage1 && python3 ../fire.py --dump ../t_list.mojo`) now
  agree (both omit `mojo_cleanup_push_list`/`mojo_list_free`/
  `mojo_cleanup_cancel_n`), whereas the SAME two invocations WITHOUT a
  fixed hash seed disagreed (the actual `make bootstrap` run's
  `stage1/t_list.ci` had the cleanup calls; a fresh un-seeded rerun from
  the repo root did not). This means `_FuncFacts`/`ownership_destruct`'s
  candidate computation — or something it depends on — is sensitive to
  Python's string-hash randomization, i.e. some SET (not dict — dicts
  are insertion-ordered and confirmed not to vary) gets ITERATED
  somewhere in a way that changes the computed RESULT, not just internal
  bookkeeping order. NOT yet root-caused to the exact line: a scan of
  `ownership_destruct.py` for `for x in <a plain set>:` patterns (as
  opposed to `for x in <a list>:`, all of which are confirmed
  insertion-order-safe) found none directly in this module, so the
  sensitivity likely lives in a caller (`gimple_gen_infra.py`'s
  `begin_function`/`_emit_owned_local_frees`/type-inference machinery)
  or another file in the call chain, not yet isolated. **NOT a self-
  hosted-only bug** — the self-hosted (`stage2/mojo`) side is
  deterministic (its own hashing has no seed); only the python3
  reference side is non-deterministic, which is exactly why `verify`
  (which always compares against the python3-derived `stage1` output)
  can never be made reliably green without fixing this, no matter how
  correct `stage2`'s output is.

**Not attempted this session**: root-causing either of Part B's two
divergence classes to an exact line, or fixing either. This is
explicitly new, previously-unreachable scope surfaced by Part A's fix,
not a continuation of Part A's own crash — recommend a fresh, focused
investigation (the `PYTHONHASHSEED`-sensitivity angle is the more
promising lead: bisect which specific SET gets iterated non-
deterministically, likely via a targeted `PYTHONHASHSEED=N` sweep across
small N to find a minimal pair of seeds that disagree, then binary-search
the call chain with print-debugging at each hop).

### A separate memory-usage observation, investigated and found NOT to block the real path

Isolated tests run while chasing Part A's crash found that compiling
`ownership_destruct.py` (or `gimple_gen_infra.py`) directly AS THE ROOT
`--dump-full` input file (not as a sibling import inside `fire.py`'s own
closure, which is what `make bootstrap`/`check-native-dumpfull` actually
do) causes catastrophic RSS growth (~1-1.5GB/sec, confirmed to 70GB+
before being killed) in the self-hosted `mojoc` binary. Critically, this
reproduces IDENTICALLY on the UNMODIFIED, pre-session `ownership_destruct.py`
(via `git show HEAD:ownership_destruct.py`) — so it is not caused by any
fix in this entry, and is not new. It is most likely the SAME already-
documented "today's pre-existing leak, unchanged" this codebase's own
`_compute_owned_free_candidates` docstring already calls out (Phase 3's
free-insertion is explicitly a best-effort memory optimization, not a
correctness requirement — a function it can't analyze just leaks, as
before). The real target path (`fire.py` as root, exercised by the
`make bootstrap` run in Part B above) does NOT exhibit this catastrophically
— peak RSS there was bursty but bounded (20-30GB, not 70GB+) and the
process completed on its own. Root-causing why `ownership_destruct.py`/
`gimple_gen_infra.py`-as-root specifically triggers the worst case (root-
module-specific codegen flags — `emit_entry_points`/`emit_str_pool`
differ for root vs sibling compiles — are the leading suspect) is also
new, not-yet-attempted scope.

## Status (2026-09-20, seventh entry — huge backlog of self-hosted-only bugs found and fixed; `make bootstrap`'s per-file divergences now ALL fixed; one whole-program crash remains)

Picking up directly from the sixth entry: with the subprocess fallback
gone and native codegen genuinely running end to end, `make bootstrap`
went from crashing almost immediately to reporting **14 files** with real
`stage1` (python3) vs `stage2` (native) `.ci` content divergences
(`t_list.mojo`, `class_jit.mojo`, `test_struct.mojo`,
`bootstrap_test_classes.mojo`, `example_imports.mojo`,
`bootstrap-validate.mojo`, `fire_compiler.py`, `fire_main.py`, `fire.py`,
`module_loader.py`, `mojo.py`, `myinterpreter.py`, `stdlib_core.py`,
`test_simple.mojo`). All 14 are now fixed for the per-file-dump case
(`stage1`/`stage2` byte-identical for every one). Root causes, in the
order found:

1. **`zip()` had no lowering for a nested-tuple loop target**
   (`for (a, b), c in zip(...)`) — `gimple_gen_loops.py`'s `_gen_for_zip`
   raised outright for this shape, falling through to the generic
   iterator path, which also couldn't handle it and silently ran the
   loop body zero times (`mojo_unsupported_iter`). Fixed by adding real
   nested-tuple-slot support to `_zip_bind_slot`/`_declare_zip_slot`.
2. **`zip()` also had no lowering for a non-statically-typed sequence
   argument** (e.g. `zip(d.get('parameters') or [], d['c_parameters'])`
   — a dict-derived value, not a bare `MojoList *`) — fixed by routing
   through `_materialize_as_list` (the same DESIGN.html R1/R5 chokepoint
   `all()`/`any()`/`enumerate()`/`*.join()` already share) instead of
   rejecting anything not already a literal list.
3. **`ownership_destruct` was missing from `gimple_gen_methods.py`'s
   `_SELFHOST_SIBLING_MODULE_PREFIXES` whitelist** — a real,
   module-qualified free-function call
   (`ownership_destruct.analyze_function(...)`) was silently
   auto-stubbed into a no-op under self-hosting because the module
   wasn't recognized as a legitimate self-host sibling. This alone made
   Phase 3's ownership-free-candidate analysis return EMPTY, always,
   under self-hosting — for as long as that's been true, `make bootstrap`
   has never genuinely exercised this analysis' real logic.
4. **Once (3) was fixed and the analysis started finding REAL
   candidates for the first time, a long chain of untyped-parameter/
   return-value element-type-propagation gaps in `ownership_destruct.py`
   and its `gimple_gen_infra.py` consumer surfaced as segfaults**, not
   silent wrong output — found and fixed one hop at a time (see
   `ownership_destruct.py`'s own extensive docstrings on `_FuncFacts`,
   `_intersect_all`, `analyze_function`, and `_as_str`, and `gimple_gen_
   infra.py`'s `begin_function`/`emit_fallthrough_frees` for the full
   mechanism and every specific crash each one fixed). The general
   pattern, confirmed repeatedly: this self-hosted compiler tracks a
   container's ELEMENT type (str vs int64_t) per COMPILE-TIME VARIABLE
   NAME within one function scope (via `.append()`/`.add()` at the
   point of construction) — but has NO mechanism to carry that
   information across a plain function-call boundary (neither into a
   callee's parameter, nor out through a return value, unless BOTH ends
   are explicit `str`/`set`/`list` type ANNOTATIONS, which only fixes
   the OUTER container type, not always its elements) or across a
   struct-field write (`self.field = <call result>`, fixed for one
   specific field via a manual `_field_elem_types` write in `begin_
   function`) or through a *dynamically dispatched* attribute read
   passed directly into a *builtin* method call like `set.add(x)`
   (fixed via the `_as_str()` explicit-coercion-boundary trick — a
   builtin has no annotatable parameter of its own to force the
   coercion, so route the value through one of our OWN annotated
   functions first).
5. **A struct field-name list generator (`_mojo_fieldnames_*` in
   `gimple_module_gen.py`) hit the exact same function-call-boundary
   element-type-loss gap** (item 4's general pattern) for an unrelated
   reason (real field names, not ownership candidates) — fixed by
   inlining the single-call-site helper `_fieldnames_append_lines` back
   into its caller's scope, so the list's element type (tracked via
   `.append()`) never has to cross a boundary at all.
6. **A large (`> INT64_MAX`) integer literal's Python-level VALUE
   itself doesn't survive self-hosting** (`gimple_gen_exprs.py`'s
   `_lower_IntLiteral`): `node.value` for a literal like
   `0xFFFFFFFFFFFFFFFF` (2**64-1) is a real, unbounded Python int under
   CPython, but under self-hosted execution `node.value` is itself
   stored as an int64_t and has ALREADY WRAPPED to -1 by the time this
   function runs — the existing `node.value > 0x7FFFFFFFFFFFFFFF` check
   (correct under CPython) is then silently FALSE, skipping the
   `uint64_t` cast+mask widening this literal needs entirely (a real,
   reproducible divergence: a 64-bit hash-mixing idiom,
   `x * <const> & 0xFFFFFFFFFFFFFFFF`, lost its whole masking step
   under native). Fixed by also checking `node.value < 0` (unambiguous
   evidence of this exact wraparound — a real `IntLiteral` node is never
   itself negative under CPython either, since unary minus is a
   separate AST node) and, for that branch, emitting a bit-reinterpret
   C cast (`(uint64_t)(<value>LL)`) instead of trying to recover the
   true unsigned decimal text with Python-level arithmetic (which would
   itself need a literal >= 2**64 in THIS source file — circular).

**Remaining, NOT yet fixed**: `make bootstrap`'s own internal
whole-program `--dump-full ../fire.py` self-check (run once inside the
`stage2` target and again inside `stage3`, comparing the self-hosted
binary against itself on a much larger, real multi-module closure than
any single bootstrap file) crashes intermittently — confirmed via lldb
across several runs, always the same shape: `EXC_BAD_ACCESS` inside
`mojo_set_update`/`mojo_set_add_str`/`_str_hash`, called from
`ownership_destruct._dfa_stmt`, with the faulting address decoding as
the raw bytes of an unrelated string constant (e.g. `"_SCALAR_..."`) —
i.e. item 4's general class of bug, but not yet isolated to a specific,
reproducible minimal shape: it has succeeded cleanly at least once (a
full `make bootstrap` run completed stage1 AND all of stage2, including
this exact `--dump-full` line, with zero per-file divergences) and
failed on immediate re-run of the identical command against the
identical binary and input, which points to a hash-seed/ASLR-dependent
set/dict iteration order interacting with some remaining, real
type-tracking gap on a control-flow shape (the crash trace runs through
a real `TryStmt`) not yet reduced to a minimal repro — the run that
crashed was compiling `module_loader.py`, which also hits (separately,
non-fatally, printed as an `# ERROR: ...` comment in the generated C
rather than crashing) a legitimate "two sibling modules both define
`_mojo_type`" ambiguous-import case; whether that's connected to the
crash is unconfirmed. Next step for whoever picks this up: reproduce
under gdbtool with a breakpoint on `ownership_destruct__dfa_stmt_*`
that conditionally prints `stmt`'s kind and the state of `assigned`
each time a `TryStmt`/`MatchStmt` branch is taken while compiling
`module_loader.py` specifically, to catch the exact iteration that
produces the bad value — item 4's fixes were each found by exactly this
kind of targeted instrumentation, just not yet pointed at this specific
input.

## Status (2026-09-19, sixth entry — earlier "FIXED" state this session was a FALSE POSITIVE; real divergence still open, now genuinely exercised for the first time)

**Important correction**: this doc was `git rm`'d earlier today after `check-noshim-
dumpfull` (renamed `check-native-dumpfull`) appeared to pass byte-identical. That
was wrong — restored. What actually happened:

1. Fixed three real, independent bugs this session (missing `os.getcwd()`/
   `str.rindex()` codegen lowering, and a systemic keyword-arguments-dropped-
   on-non-overloaded-method-calls bug) — all genuine, all still correct.
2. Found the LONG-STANDING duplicate-`typedef struct _<mod>_toplev` emission
   (Finding 5 below, "struct EMISSION ORDER divergence") is real and fixed
   it with a regex-based post-processing pass (`gimple_codegen._dedup_
   module_toplev_structs`), plus found and fixed a second, unrelated
   cosmetic divergence (`gimple_codegen_compile_to_gimple(...)` vs
   `compile_to_gimple(...)` call-site text, itself a MOJO_NO_SHIM-at-
   codegen-time artifact, now removed).
3. **After these, `check-noshim-dumpfull` reported byte-identical.** This
   was accepted as "the divergence is fixed" and led to removing the
   `gimple_codegen_compile_to_gimple` C runtime wrapper's python3-subprocess
   fallback entirely (per an explicit user request to stop shelling out to
   python3 at runtime).
4. **That removal immediately broke `check-native-dumpfull`**: native
   `compile_to_gimple` started returning NULL (a 264-byte fallback stub
   instead of ~36MB of real output). Root cause: step 2's dedup fix used a
   **regex with backreferences and a non-greedy quantifier**
   (`#ifndef _MOJO_TOPLEV_GUARD_(\w+)\n...\1...(?:.*\n)*?...`) — both
   outside POSIX ERE, which this codebase's self-hosted regex engine
   implements (not Python's real `re`). Since this dedup pass runs inside
   `_run_pipeline` (part of the self-hosted `compile_to_gimple` closure
   itself), the self-hosted binary's OWN regex engine choked on it —
   **silently**, because the still-present subprocess fallback caught the
   resulting native failure and quietly re-did the whole compile via a
   real `python3` subprocess (with real `re`), which of course produced
   correct output. **The "byte-identical" result in step 3 was achieved
   entirely via the subprocess fallback, not via working native codegen.**
   Native `compile_to_gimple` was completely broken the whole time; nothing
   in this session's earlier testing could see that, because the one gate
   built specifically to see it (`check-native-dumpfull`, run with
   `MOJO_NO_SHIM=1`/native-preferred) still had the fallback available as
   an escape hatch.
5. Fixed the regex bug for real: rewrote `_dedup_module_toplev_structs` as
   plain `.find()`/slicing string scanning (no `re` at all) — verified via
   a standalone unit test AND via the shim producing identical deduped
   output. Rebuilt `mojoc`; native `compile_to_gimple` now genuinely runs
   to completion self-hosted (native=35355174 bytes, not a 264-byte stub).
6. **With native codegen actually running for the first time, the TRUE
   remaining divergence is back**: `./mojoc fire.py --dump-full` vs
   `python3 fire.py --dump-full fire.py`, first differing byte now at
   offset ~87475 (was ~87862 before any of this session's fixes — i.e.
   genuinely unchanged from where this whole investigation started).
   Content: `struct _build_config_toplev _build_config_globals = {...};`
   (the ONE-TIME instance-definition-with-initializers block — confirmed
   via `grep -c` to appear EXACTLY ONCE in both outputs, so this is pure
   **ordering**, not duplication) is spliced at line 3388 in native vs
   line 4840 in the shim. This is a DIFFERENT text block than Finding 5's
   original `typedef` duplication (which the dedup pass genuinely did fix
   — the typedef itself is now at the identical line 2135 in both) but
   the SAME underlying class of bug: `build_config` is a transitive
   dependency reached from more than one importer (`fire.py` directly,
   and `build_stdlib_dylib.py` — itself one of fire.py's own
   dependencies), and `_compiled_modules`'s shared, first-come-first-
   served dedup means WHICHEVER recursive path's Python-execution-order
   reaches it first is the one whose own `gen_module_impl` call actually
   emits this one-time instance-definition block, embedded inside THAT
   caller's own fragment at THAT fragment's own splice position — not
   necessarily `build_config`'s own alphabetical slot in the root's
   `modules_to_compile` (confirmed separately, via instrumentation, to be
   IDENTICAL between shim and self-host at the ROOT level only). This is
   the SAME open architectural question Finding 5 below already
   identified and left unsolved ("the ORDER FILES GET COMPILED differs
   self-hosted vs shim... could stem from import-graph traversal order").
   **Not yet fixed. Continuing.**

## Status (2026-09-17, fourth entry — `make bootstrap` NOW PASSES)

`make bootstrap` went green: "PASSED: all 168 output files match across 3
stages" / "✓ Bootstrap complete — all stages verified". It had been failing on
four stage1-vs-stage2 `.ast` mismatches (`fire_compiler.ast`, `fire.ast`,
`module_loader.ast`, `myinterpreter.ast`), all with the same shape: a
`Generator` node's `iterable` printed as a raw boxed pointer
(`Generator(target='c', iterable=47038764864, ...)`) in the self-hosted build
instead of the nested node repr the shim prints
(`iterable=IdentExpr(name='prefix', ...)`).

Root cause: `.ast` is `repr(ast)`, and the generated per-struct
`_mojo_repr_<Struct>` (gimple_module_gen.py's reflect section) recurses for a
boxed `object`-typed field only when that struct/field is listed in the
hardcoded `struct_boxed_fields` table — it routes through
`_mojo_generic_elem_repr` (runtime type-tag dispatch) instead of
`mojo_repr_int`. `Comprehension` has `{'element', 'key'}` in that table;
`Generator` — added to `struct_field_types` earlier today (commit `5e5d05e`,
which stopped a 5-module silent drop) — did not, so its `iterable` fell to the
`mojo_repr_int` branch. Added `struct_boxed_fields['Generator'] = {'iterable'}`.

Verified: a comprehension file's `.ast` is now byte-identical shim↔self-host,
and `make bootstrap`'s 3-stage byte-identity check passes for all 168 files.
Full gate still green (all `make check-*`, stdlib dylib 0 skips,
`compile_stdlib.py` 664/664 0 unexpected). The per-file `--dump` sweep buckets
are unchanged, because the four bootstrap files are classified by their `.ci`
(which still differs) before `.ast` is compared.

## Status (2026-09-17, third entry — the 38-file self-hosted-parser class FIXED)

The largest single `.mojo` class (38 files whose self-hosted `--dump` produced
NOTHING while the shim parsed them fine) was the parser rejecting valid Mojo:
`for ref handle in ...` → `Expected KW got NAME('handle')`. Reproduced minimally
(`for ref x in xs:`; token streams byte-identical, so it was parser state, not
the tokenizer). Two independent writers were putting the CLASS-level constant
`Parser._CONV_KWS` into `struct_field_types['Parser']` as an instance field:
(1) the hardcoded self-host struct table in `gen_module_impl`, and (2) the
class-body-attribute pass, which created a field for a container-valued class
attribute (`if cur is None or ...`). With the field present, `_lower_MemberExpr`
returns its struct-FIELD branch before its class-attr branch, so
`self._CONV_KWS` read a never-initialized field — NULL — and
`_peek().value in self._CONV_KWS` tested False for every convention keyword.

Fixed both: `_CONV_KWS` removed from Parser's hardcoded table (with a note; the
sibling `_known_traits` IS a real instance field and stays), and the class-attr
pass now only UPGRADES an existing instance field's type rather than creating
one. Verified: `for ref x in xs:` is now byte-identical between shim and
self-host, and `stdlib/test/gpu/host/test_metal_device_type_encoder` (previously
0 bytes self-hosted) now emits 52 362 bytes. Sweep: empty self-hosted outputs
38 → 28, SELFHOST-CRASHED 25 → 23. Gate: all `make check-*` green, stdlib dylib
0 skips, `compile_stdlib.py` 664/664 0 unexpected.

Note: `Interpreter._INT_TYPE_NAMES` / `_FLOAT_TYPE_NAMES` in the same hardcoded
table are ALSO class-level constants (not instance fields) and are presumably the
same latent bug — not touched yet, since `_known_traits`-style verification of
every reader is still pending.

## Status (2026-09-17, second entry — per-file `--dump` A/B sweep + three root causes fixed)

Adopted the per-file decomposition (`make -j20 aside bside && make compare-a-b`,
779 files, ~35 s) to work the divergence one file at a time. Baseline:
`clean=37, CI-DIFF=704, SELFHOST-CRASHED=25, AST/TOK-DIFF=8, SHIM-FAILED=5`.
Three root causes fixed this session (all changes shim-and-nos him identical, so
every OTHER gate stays green):

1. **`gimple_ctypes.re` was never resolved at all** (183 sites in the whole-program
   output read `(int64_t)0 /* ct param or undeclared: re */`). `re.sub` happened to
   be special-cased by method name, but `re.escape` had NO lowering: it fell to the
   generic scalar-receiver stub (`int64_t.escape() stubbed`) and returned 0. Every
   `rf'\b{re.escape(name)}\b'` pattern therefore silently lost the identifier it was
   meant to anchor on. Added a real `re.escape` lowering → new runtime
   `mojo_re_escape` (CPython-compatible escaping) + a `char *` cast for boxed args.

2. **POSIX `\b` is not a word boundary on macOS** (verified directly: `regcomp` +
   `regexec` for `\bfoo\b` does not match; the BSD spelling `[[:<:]]foo[[:>:]]`
   does). The compiled `re.sub` runs through `mojo_re_sub_str` → POSIX
   `regcomp`, so even with `re.escape` fixed the rename still no-op'd. Replaced
   the two signature-renaming `re.sub(r'\b'+escape(x)+r'\b', ...)` sites
   (`gimple_gen_infra._emit_stdlib_import_externs`, `gimple_module_gen`'s
   `imported_symbols` re-export block) with a new shared
   `gimple_ctypes._replace_first_ident` — byte-preserving, regex-free. Verified:
   the first `--dump` divergence for `stdlib/test/utils/test_select` moved
   11278 → 19385, and both `assert_equal` externs now come out
   `std_testing___init___assert_equal` on both sides.

3. **`os.path.relpath` is a codegen stub** that returns its first argument
   unchanged, so the self-hosted `module_name_for_path` derived its qualifier from
   the ABSOLUTE path (`_Users_..._stdlib_std_testing___init__`) while the shim
   derived `std_testing___init__` — the same module under two different symbol
   prefixes. `module_name_for_path` now strips the `STDLIB_PATH` prefix with plain
   string slicing first, falling back to `relpath` for a path outside the stdlib;
   identical on both sides. Also via this session: the earlier `Generator`
   struct-table fix (commit `5e5d05e`) and the `LayoutSolver` HEAP/STACK
   class-attribute phantom-field fix (a class-level constant read as `self.X`
   resolves through `_class_attrs` to its own global and must not be minted as an
   uninitialized instance field — guarded in both read-mint passes).

**Remaining landscape (unchanged totals after these fixes — most files have
SEVERAL independent divergences, so a fix only moves the first-diff offset
deeper).** Dominant `.mojo` classes, by first-diff content over 616 differing
files:
- **38 files: the self-hosted parser rejects valid Mojo the shim accepts**, e.g.
  `for ref handle in ...` → `Expected KW got NAME('handle')`. Reproduced
  minimally. Token streams are byte-identical, so it's a parser-state issue: the
  convention-skip test `self._peek().value in self._CONV_KWS` evaluates False
  because `Parser._CONV_KWS` is read as a (never-initialized) struct field rather
  than its `_classattr_Parser___CONV_KWS` global — the field is added by a pass
  other than the two read-mint passes the LayoutSolver fix guards (the field
  survives with `cur is None` guard changes), so it is still open.
- **~80 files: stub-extern emission differs** (noshim emits `__attribute__((weak))`
  stubs where the shim emits nothing, or is missing a `_MOJO_STUB_*` block).
- **21 files: imported signatures unresolved in noshim** —
  `extern int64_t std_itertools___init___count (void);` where the shim has
  `..._count_2dbb98 (int64_t start, int64_t step);` (no params, no overload
  suffix), i.e. the text-scan export/signature lookup returning less self-hosted.
- **11 files: a boxed POINTER printed as a C return type** —
  `4332189096 mojo_frexp(...)` vs the shim's `int64_t mojo_frexp(...)`.
- `root/*.py` (the compiler's own closure, 6/115 clean) has its own classes:
  `char *`/`int64_t` struct-field disagreement (`Lit.value`), string-pool
  membership differences (including a garbage literal that looks like an
  exception message), overload suffix `_hash` vs `_hash_00b26e`, and temp-number
  shifts after a missing `/* with: __exit__ */` comment.

Gate for this batch: all `make check-*` green, stdlib dylib rebuild 0 skips,
`compile_stdlib.py` 664/664 0 unexpected, `make bootstrap` unchanged (still only
the 4 pre-existing `.ast` repr mismatches), `check-noshim-dumpfull` still the
tracked offset-21577 divergence (gap shrank ~386 KB → ~340 KB). The per-file
metric is the working one: it is bounded, parallel, and gives one small file to
fix at a time.

## Status (2026-09-17 — 5-module silent drop FIXED; baseline restored to the documented offset 21086)

A self-hosted `fire.py --dump-full` was silently DROPPING 5 modules
(`gimple_codegen`, `gimple_solvers`, `imports`, `jit.arm64`,
`myinterpreter`), producing a 4.4 MB `.ci` instead of ~36 MB (first diff
offset 2091, gap ~31.7 MB) — far worse than the divergence this doc has
tracked. The root cause was NOT this doc's tracked field-typing
divergence. `gimple_gen_calls._lower_ctor_from_iterable` synthesizes a
`gimple_ctypes.Generator(...)` node for `list(x)`/`set(x)`; the hardcoded
self-host AST-node struct table in `gimple_module_gen.gen_module_impl`
listed `Comprehension` but not `Generator`, so the module-qualified
constructor found no registered field layout, fell through to the opaque
`(int64_t)0` placeholder, and the synthetic comprehension's `generators`
list ended up holding a NULL. `_lower_comprehension`'s `gen0.iterable`
then raised `AttributeError: iterable` (confirmed via lldb backtrace and
`MOJO_ATTR_DBG=1`, which showed `obj=0x0 tag=0`), and
`_compile_imported_module`'s per-module `except` dropped each affected
module. Fixed by adding the `Generator` entry
(`target`/`iterable`/`conditions`/`line`/`col`), mirroring the adjacent
`Comprehension` entry.

After the fix: all 35 modules present, 0 `# ERROR` lines, and the gate is
back to this doc's long-standing pre-existing condition —
`shim=36179239` / `no-shim=35819290`, gap ~360 KB, first differing byte at
**offset 21086** (the same offset recorded throughout 2026-09-15, and
slightly better than the ~530 KB gap seen then). Confirmed concurrently:
`make check-gimple check-runner check-modcache check-linkmode
check-selfhost check-runtimediff check-no-new-casts` all green; stdlib
dylib rebuild 0 module skips; `compile_stdlib.py` 664/664, 0 unexpected.

**Not a regression from this session's earlier work — was latent at the
old HEAD.** At clean `563ec43` the `mojoc` target itself fails (`python3
fire.py build fire.py -o mojoc` exits 1 — the imported-prototype conflicts
fixed in `921bf26`), so `check-noshim-dumpfull` was not runnable at all;
the 5-module drop only became observable once `921bf26` made `mojoc`
buildable again.

**`make bootstrap` residue (pre-existing, separate):** bootstrap now
reaches the stage1-vs-stage2 comparison (stage2 could not even be built
before `921bf26`), and fails only on 4 `.ast` dumps
(`fire`, `fire_compiler`, `module_loader`, `myinterpreter`) where
`Generator.iterable` prints as a raw boxed pointer
(`iterable=52068159136`) instead of the nested node the shim prints. That
is the pre-existing shim-vs-compiled AST-repr class this doc already
tracks — `Comprehension`'s `element` has always been typed `int64_t` in
the same table and behaves identically — not a `.ci` codegen divergence.
Bootstrap remains the aspirational, non-`check`-gated target.

## Status (2026-09-15, later still — re-confirmed pre-existing a fifth time, via the same-worktree A/B methodology, for the Phase 6 stack-allocation landing)

Same-worktree `--no-cache` A/B (see the entry just below for why this is
the correct methodology, not a bare byte-count comparison): clean HEAD
(`d30bd0e`) gave shim=51967687/no-shim=52981667, offset 21168, gap
1013980; with the Phase 6 diff (`mojo_dict/list/set_init/_destroy` +
`maybe_stack_alloc_owned_ctor`) applied in the SAME worktree and
rebuilt fresh: shim=52051290/no-shim=53070381, offset 21168 (IDENTICAL),
gap 1019091 (+5111 bytes, consistent with the new code itself being
reflected equally on both sides, not a new divergence source).

## Status (2026-09-15, later still — re-confirmed pre-existing a fourth time, via a proper same-worktree A/B, after noticing the naive before/after byte-count comparison used in this doc's last two entries is NOT reliable)

Hit this gate failure a fourth time fixing two real bugs found while
investigating Phase 6 (a stale-`_owned_free_candidates` use-after-free in
`_gen_struct_method`/`_gen_toplevel`, and a free-before-reading-the-return-
value ordering bug in `_gen_stmt_ReturnStmt` — see `doc/OWNERSHIP_MODEL.md`
and the `gimple_gen_infra.py`/`gimple_gen_funcs.py`/`gimple_gen_stmts.py`
fixes). This time the raw before/after byte counts moved by MILLIONS of
bytes and the first-differing-byte offset shifted too (36288039/35758312 →
36295109/32414925), which would normally read as "made it much worse" —
**but re-running `check-noshim-dumpfull` on the SAME unchanged commit
(`468be20`) a few minutes apart, in the SAME working directory, gave YET
ANOTHER wildly different number (51771695/52766688)**. That ruled out the
naive "compare this run's absolute byte count to a number written down in
an earlier session/entry of this doc" methodology this doc's last two
entries used — the metric is sensitive to something in the surrounding
BUILD/CACHE STATE (stdlib dylib freshness, CAS warm/cold, or similar),
not source-code content alone, so two absolute byte counts from
different points in time are not comparable even for byte-identical code.

**Correct methodology used instead**: a `git worktree add` of clean HEAD,
`check-noshim-dumpfull --no-cache` run fresh TWICE in a row there to
confirm same-build-state reproducibility (51771695/52766719 then
51771695/52766719 — offset 21167 both times, no-shim size stable to
within 31 bytes: genuinely deterministic once build state is held
fixed), THEN `git apply`ing this session's exact uncommitted diff into
that SAME worktree and rebuilding `mojoc`/re-running fresh there:
51776558/52771708, offset 21167 — IDENTICAL offset, gap essentially
unchanged (995024 → 995150 bytes, a ~126-byte difference consistent with
this session's own small code addition being reflected equally on both
the shim and no-shim sides, not a new divergence). This is the
methodology future sessions hitting this gate should use — a same-
environment, same-worktree, `--no-cache` A/B — not a bare "compare
today's number to what an earlier doc entry wrote down."

## Status (2026-09-15, later still — re-confirmed pre-existing a third time, widening Phase 3 eligibility to try/except-containing functions)

Same gate failure a third time this session, now after widening
`_is_free_eligible_function` (`gimple_gen_infra.py`) to stop excluding a
function containing its own `try`/`except` — item 3's cleanup-thunk
registry (previous entry below) makes that safe. This run:
shim=36291056 bytes, no-shim=35761631 bytes, first differing byte still
at the SAME offset 21086, gap 529425 (~530KB, unchanged) — only a ~3KB
shift on each side from more functions now qualifying for the
push/cancel emission, not a new divergence source. Same standing
conclusion.

## Status (2026-09-15, later same day — re-confirmed pre-existing a second time, during the ownership-model exception-unwinding fix)

Hit this same gate failure again running the full CLAUDE.md gate for
doc/OWNERSHIP_MODEL.md's TODO item 3 (the cleanup-thunk-registry
exception-unwinding fix: `mojo_cleanup_push_dict/list/set`,
`mojo_cleanup_cancel_n`, `mojo_cleanup_checkpoint_save` in
`runtime/mojo_runtime.{c,h}`, wired from `gimple_gen_stmts.py`/
`gimple_gen_infra.py`). This run: shim=36288039 bytes,
no-shim=35758312 bytes, first differing byte at offset 21086 — same
~20800-21100 first-divergence window and same ~530KB
(36288039-35758312=529727) gap as the entry just below from earlier
today, both up by ~28KB on each side from this session's own added
code being dumped identically on both the shim and no-shim sides
(28177 / 28490 bytes respectively — consistent with new code being
counted, not new divergence). Confirms, independently of that entry's
own `git worktree` check, that this specific feature session isn't the
cause either. Not investigated further — same standing conclusion as
below.

## Status (2026-09-15 — re-confirmed pre-existing during an unrelated feature session; still failing, symptom shape changed again)

Hit this gate failure while running the FULL CLAUDE.md quality gate for
the doc/OWNERSHIP_MODEL.md Phase 3 codegen-wiring work
(`gimple_gen_infra.py`'s `begin_function`/`emit_return_frees`/
`emit_fallthrough_frees`, `ownership_check.py`, `ownership_destruct.py` —
see that doc's TODO item 1). Before assuming the new feature caused it,
verified definitively via a clean `git worktree add /tmp/... HEAD` (no
uncommitted changes at all) rebuild of `mojoc`: the exact same class of
shim-vs-noshim divergence reproduces on an untouched checkout, confirming
(again, independently of the 2026-09-13/14 sessions below) that this is
not caused by that session's work either. Today's specific symptom:
`LayoutSolver` (`gimple_solvers.py`) — a struct whose only real instance
fields are `_struct_types`/`_ea` (see its `__init__`) — gets TWO EXTRA
struct members in the shim's build, `int64_t HEAP; int64_t STACK;`,
matching the class's own class-level string constants (`STACK = 'stack'`,
`HEAP = 'heap'`) being (incorrectly, in the shim's version) swept into the
instance struct layout; the no-shim/self-hosted build omits them. First
divergence around byte offset ~20800-21100, both today's clean-HEAD run
and the with-my-changes run — consistent with this being the SAME
systematic self-host struct-field-inference divergence this doc has
tracked since 2026-09-13, now presenting as a per-class extra/missing
FIELD PAIR rather than a whole dropped module. Byte-count gap this run:
shim=36259862, no-shim=35729822 (~530KB, shim larger) — same order of
magnitude as session 4's "~350KB, not yet zero" state below, consistent
with "still open," not a fresh regression.

**Confirms this doc's own standing conclusion still holds**: gate step 5
(`check-noshim-dumpfull`) should be expected to keep failing on this repo
until the work below (or its continuation) is finished — that is a
pre-existing, tracked condition of the gate itself, not something an
unrelated feature session should be blocked on or expected to fix as a
side effect. Do not spend further time chasing this from an unrelated
session without first reading this doc's full history below.

## Status (2026-09-14, session 4 — 7 more root causes fixed; diff narrowed ~3.8MB → ~350KB; NOT yet zero, 8th blocker precisely diagnosed and deferred)

See "## Session 4 final summary (2026-09-14)" near the end of this doc
for the complete accounting of this session's work: seven independent,
gate-verified fixes landed (commits `5cc83e5`, `078c103`, `972850f`,
following on from `585879c`/`dba69b8` in session 3), all downstream/gate
impact confirmed (a real external project, a GCC frontend vendoring this
compiler, went from 9944 gcc errors to 0), and the remaining gap is now
tied to a specific, already-tracked, separate deferred project
(`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`)
rather than being open-ended or unknown.

## Status (2026-09-13 — found, NOT fixed, confirmed pre-existing)

`make check-noshim-dumpfull` (`test_noshim_dumpfull.py`, added in commit
`b00955c` as DESIGN.html R6) fails:

```
✗ MOJO_NO_SHIM=1 ./mojoc output DIFFERS from the shim's own --dump-full
output: shim=32886825 bytes, no-shim=~27-28MB, first differing byte at
offset 2390 - the self-hosted binary is miscompiling itself even though
it exited 0
```

**Confirmed pre-existing, not caused by the same-day R3 cast-migration
session**: reproduced identically (same failure, same offset 2390) after
`git stash`-ing every R3-session change back to the exact `b00955c` tree
state and rebuilding `mojoc` from scratch (`rm -f mojoc && make mojoc`).
`b00955c`'s own commit message added this check but — per
`design-container-typing-audit` project memory — "Full gate NOT re-run
after b00955c — only syntax + one real do_imports=True compile check."
This check was added but never actually run to see if it passed; it
doesn't.

The failing byte offset (2390) is very early in the `--dump-full` output
and consistent across multiple independent rebuilds, suggesting a
systematic divergence (e.g. a preamble/header section or an early-defined
symbol) rather than something deep in per-function body codegen. The
overall size gap (~5MB, shim larger) matches the same shape as the
`selfhost-dump-full-module-drop` project memory's prior incident — some
whole section or set of modules is present in the shim's build but
missing from the self-hosted `mojoc`'s own compiled path.

## Root-cause investigation (2026-09-13, continued)

Diffed the actual `.ci` output at offset 2390: the self-hosted (no-shim)
build's forward-declaration list is missing `void
_gimple_gen_coro_toplevel(void);` entirely — present in the shim's output,
absent from the no-shim one. Confirmed this isn't just the declaration:
`grep -c "_gimple_gen_coro_" ` finds 380 occurrences in the shim's `.ci`
vs only 26 in the no-shim one — the self-hosted `mojoc` is dropping nearly
all of `gimple_gen_coro.py`'s own compiled content from its transitive
closure when compiling `fire.py --dump-full`, matching the
`selfhost-dump-full-module-drop` project memory's prior incident shape
(a whole sibling module silently missing, exit code 0).

**Ruled out:**
- Not caused by this session's R3 work (see Status above — reproduces
  identically on the pristine `b00955c` tree).
- Not simply "imported without an `as alias`" (unlike its ~10 sibling
  `gimple_*` imports in `gimple_codegen.py`, `import gimple_gen_coro` has
  no alias) — built a minimal 2-module isolated repro (one aliased import,
  one bare) and both modules were fully compiled in both the shim and
  no-shim `--dump-full` output; the drop did not reproduce in isolation.

## Root-cause investigation (2026-09-13, continued further — two real findings)

Instrumented `_compile_imported_module`/`gen_module_impl` with temporary
`print()` tracing (env-var-gated at first, then a plain module-level
`bool` constant after `os.environ.get()` itself turned out to be
self-host-unreliable — see Finding 2 below) and rebuilt `mojoc` to trace
exactly what happens compiling `gimple_gen_coro.py`.

**Finding 1 (REAL BUG, FIXED, commit-worthy on its own)**: the trace
showed thousands of `vars: unavailable in compiled mode` messages fire
the instant `gimple_gen_coro.py`'s compile starts. Root cause:
`gimple_gen_coro.py` uses `for k, v in vars(node).items():` (10+ call
sites) to walk AST nodes generically, where `node`'s static type is
deliberately unknown (it needs to handle many different node types
uniformly). `_lower_call`'s `vars()` special case
(`gimple_gen_calls.py` ~line 1534) only routed through the real
`_mojo_dispatch_asdict` reflection helper `if gimple_exprtypes.
_struct_name_of(at) in gen.struct_field_types` (i.e. only when the
STATIC type happens to be known) — otherwise it fell through to the
generic "unresolved builtin" weak-stub path (print-and-return-0, a
no-op). But `_mojo_dispatch_asdict(void *obj)` (gimple_module_gen.py)
is ALREADY a fully general RUNTIME dispatcher — it reads the object's
own type tag via `mojo_read_type_tag_safe` and picks the matching
`_mojo_asdict_<struct>` at runtime, needing no static proof at all.
**FIXED**: removed the static-type gate entirely; `vars(x)` now always
routes through `_mojo_dispatch_asdict` (casting through `void *`).
Confirmed fixed: `vars:` print count in the `--dump-full` trace dropped
from thousands to exactly 0. `compile_stdlib.py` and the container-cast
counter both still pass after the fix (no regression). This means
`gimple_gen_coro.py`'s own generic AST-node introspection was silently
returning empty dicts instead of the node's real fields, throughout
the ENTIRE self-hosted build (not just for `gimple_gen_coro.py` itself)
— a separate, real correctness bug beyond just this gate's failure,
now fixed.

**Finding 2 (root cause of the module-drop, NOT fixed, needs careful
follow-up)**: even after Finding 1's fix, `gimple_gen_coro` still
compiles to `code_len=0` self-hosted. The trace (before the vars() fix
masked it with noise) showed the module-compile's `except Exception as
e:` handler in `gimple_gen_resolve.py` catching:
`AttributeError: environ` (a SEPARATE finding — see below) and, in an
earlier still-cleaner trace, exactly:
`zip() lowering needs a tuple loop target`
— the literal message `_gen_for_zip` (`gimple_gen_loops.py:1030`)
raises for `for (_n, a), pk in zip(real_params, param_kinds):`
(`gimple_gen_coro.py:2481` — a nested-tuple `zip()` target, an
explicitly-unsupported shape by design). This raise is SUPPOSED to be
caught locally by the `try/except` in `_gen_stmt_ForStmt`
(`gimple_gen_stmts.py` ~line 2731), which rolls back and falls through
to `_gen_for_iter(node)` — and does so successfully in the shim (the
shim's `--dump-full` contains gimple_gen_coro's full compiled content).
Self-hosted, the exact same exception is instead caught only by the
much-outer MODULE-level handler, meaning the intended LOCAL catch is
being skipped somehow. **Root cause not yet isolated** — ruled out
"try/except doesn't work at all self-hosted" (a standalone 2-level
nested try/except repro, built and RUN as an ordinary compiled target
program via `fire.py build`, correctly caught a `ValueError` raised
from a helper two calls deep), and ruled out "only one unprotected call
site" (`_gen_for_zip` has exactly one caller, and it IS wrapped in
try/except). The exact mechanism by which THIS SPECIFIC try/except
fails to catch, only when the code compiling it is itself running
self-hosted, is still unknown.

**Finding 3 (separate, real, worth its own follow-up)**: `os.environ.get(...)`
itself raises `AttributeError: environ` in some self-hosted contexts
(discovered as an artifact of debug instrumentation — do not assume
`os.environ` is safe to use in this codegen's own source without
testing first).

**Important operational lesson learned the hard way**: setting a
debug-tracing module-level constant to `True` (to make the trace
`print()`s active) — even though it's a plain Python `bool` with no
apparent relationship to codegen logic — broke `make mojoc`'s own
SHIM-compiled build entirely (`error: invalid use of undefined type
'struct _gimple_gen_coro_toplev'`, `'struct _reflect_toplev'`). This
compiler does WHOLE-FUNCTION type unification (already documented
elsewhere in this codebase re: the `_mn`/`module_name` loop-variable
gotcha in this exact function) — adding new code to a self-hosted
function, even genuinely dead/inert-at-runtime code behind an `if
False:`-shaped guard, can still shift how OTHER variables in that same
function get statically type-inferred by THIS compiler's own
self-compilation, breaking things that had nothing to do with the
change. All temporary debug instrumentation for Findings 2/3 was
reverted (`git checkout --`) rather than left in the tree, even
disabled — confirmed `make mojoc` rebuilds clean (0 errors) again
afterward. **Any further debugging here should default to gdb on the
actual `mojoc` binary (per `HOW-TO-DEBUG.html`) rather than adding new
source-level tracing to the compiler's own self-hosted functions**,
given this demonstrated fragility.

## Root cause of Finding 2, FOUND AND FIXED (2026-09-13, same day, via lldb)

Used `tools/gdbtool` (lldb) directly on the `mojoc` binary rather than
more source instrumentation, per the lesson above. Set a conditional
breakpoint on `mojo_exc_msg_set` (`strstr(msg, "tuple loop target")`)
and walked the backtrace at each hit:

- First hit: inside `_gen_for_zip_ba2192` called from
  `_gen_stmt_ForStmt_ba2192`'s try block (`gimple_gen_stmts.py:2732`) —
  watched `_mojo_exc_top` (7 → 6 via `mojo_exc_pop`) and confirmed
  `mojo_raise()`'s `longjmp` correctly returned control to the `except`
  block at line 2736. This occurrence (compiling `mojo_compiler.py` as
  a nested import) is caught CORRECTLY self-hosted — the try/except
  mechanism itself is not broken in general.
- Second hit: same raise, but frame #1 was `__mojo_coro_yield`, called
  from `__mgco__iter_ast_body` (`gimple_gen_stmts.py:254`, the compiled
  coroutine for `_iter_ast` — see Finding 1's sibling function) —
  i.e. the raise fired WHILE a compiled coroutine (`_iter_ast`) was
  suspended mid-`yield` on the call stack. A `try/except`'s `setjmp`
  captured on the ORIGINAL (resuming) stack, longjmp'd to FROM CODE
  RUNNING ON THE GENERATOR'S OWN SEPARATE FIBER STACK, is undefined
  behavior — exactly the documented coroutine/setjmp hazard, now hit in
  a new combination (a try/except elsewhere in the pipeline, racing
  against an unrelated coroutine walk on the stack at raise time).

**Fixed**: converted `_iter_ast` (`gimple_gen_stmts.py`) and its sibling
`_walk` (`gimple_gen_coro.py`, confirmed via a second lldb session to be
the OTHER offender specifically for `gimple_gen_coro.py`'s own module
compile — the `__mgco__walk_body` coroutine caught suspended at the
exact same raise) from `yield`-based generators to plain iterative
list-building functions (see the commit landing this fix for the full
diffs). Verified via `test_noshim_dumpfull.py`: the shim-vs-noshim size
gap dropped from ~4MB to ~196KB, and the failing byte offset moved from
2390 (`gimple_gen_coro` almost entirely missing) to 2894 (`myinterpreter`
module missing instead — see Finding 4 below). `gimple_gen_coro` is now
byte-for-byte present in both builds.

## Finding 4 (a THIRD, separate divergence — isolated, NOT fixed)

With Findings 1/2 fixed, the next (and much smaller) divergence is the
`myinterpreter` module dropping to `code_len=0` self-hosted, with:

```
cannot coerce MojoList * to MojoDict * (incompatible container kinds)
at myinterpreter.py: value='_t32' dest='_t33'
```

Backtraced via lldb (conditional breakpoint on `mojo_exc_msg_set` for
"cannot coerce") to `_lower_dict_method` (`gimple_gen_methods.py:3043`,
the `dict.update()` handling) called with `ov` statically typed
`MojoDict *`. The real source line is `myinterpreter.py:3326`:
`from_base.update(base_cls.methods.keys())` inside
`execute_StructDef`, where **`from_base = set()`** is declared
unambiguously three lines earlier (line 3314) and used consistently as
a set everywhere (`.update()`, `in`, `.discard()`). The compiler
mis-infers `from_base`'s declared type as `MojoDict *` instead of
`MojoSet *` — self-hosted only; the shim compiles this function
correctly.

**Precisely bisected the trigger** (repeatedly truncating a copy of the
real `myinterpreter.py` and re-running `MOJO_NO_SHIM=1 ./mojoc <file>
--dump-full`, ~15s per iteration, no `mojoc` rebuild needed since only
the INPUT file changes): the mistyping requires the LITERAL PRESENCE,
anywhere later in the same file/class, of a `self.<attr>.update(...)`
call — specifically the METHOD NAME `"update"` on a `self.` attribute.
Confirmed via direct substitution experiments:
- Removing `self.global_vars.update(node.names)` (replacing with `pass`)
  → bug disappears.
- Changing the ARGUMENT (`node.names` → `set(node.names)`, a `MojoSet *`
  instead of `MojoList *`) → bug still present (argument type is
  irrelevant).
- Changing the METHOD NAME (`.update(...)` → `.add('x')`) → bug
  disappears (method name specifically matters, not just "any call on
  a self attribute").

This means an UNRELATED method (`execute_GlobalStmt`, ~700 lines later
in the file) merely CONTAINING a `self.X.update(...)` call corrupts a
completely different method's (`execute_StructDef`) local variable
inference. **Root cause NOT found** despite substantial further
effort: ruled out `_infer_param_types`/`is_dict_method` (scoped to
function PARAMETERS only — `from_base` is a local, not a parameter, so
this code path doesn't apply); ruled out `_SELFHOST_MODGLOBAL_CACHE`
(keyed only by genuine MODULE-LEVEL globals, and `from_base` is not a
module-level name anywhere in this codebase); ruled out a declared-type
conflict for the `self.global_vars` field itself (all 3 real usages
treat it consistently as a set); read `_infer_local_var_types`
(`gimple_gen_resolve.py:2234`) end-to-end — its `gen.var_types`
save/restore is `try/finally`-protected (safe), and a single `from_base
= set()` assignment should join trivially to `MojoSet *` via
`_quick_type`'s `_BUILTIN_CTORS` table. The likely remaining suspect is
the per-class-method loop that calls `_infer_local_var_types(m)` once
per method (`gimple_module_gen.py:5268-5272`,
`for s in all_structs_for_methods: for m in s.methods: ... self.
_infer_local_var_types(m)`) — matching this codebase's own frequently-
documented "loop variable doesn't get a fresh type per self-hosted
iteration" bug class — but this was NOT confirmed; an attempted lldb
watchpoint on `mojo_dict_set_str` (conditioned on `key == "from_base"`)
to catch every write to that name live did not hit within a bounded
wait (there may be MANY unrelated `MojoDict *` instances with string
keys throughout a self-hosted compile — string-interning tables,
memoization caches — making this specific breakpoint too broad/slow to
be practical without a more targeted address or call-site condition).

## Next steps (not attempted this pass)

- Root-cause Finding 4: either (a) set a breakpoint scoped to the
  SPECIFIC `MojoDict *` instance backing `gen.var_types` (need to find
  its address/identity first, e.g. by breaking inside
  `_infer_local_var_types`'s own compiled body and reading `gen`'s
  `var_types` field directly), or (b) bisect the compiler's OWN logic
  the same way the input file was bisected here — comment out
  candidate inference paths in `gimple_module_gen.py`'s per-method loop
  and rebuild `mojoc` (slower: full self-host rebuild per iteration,
  ~2-3 min, vs. the ~15s per-iteration cost of bisecting the INPUT file
  used for Finding 4's isolation) until the corruption stops.
- Investigate Finding 3 (`os.environ` self-host reliability) separately
  — check whether it's a general lowering gap or context-specific.
- This is genuinely open-ended (matches the multi-day effort shape of
  prior instances of this bug class per project memory). Findings 1 and
  2 are real, complete, verified fixes landed this session, closing
  ~95% of the original divergence (shim/no-shim size gap: ~5MB → ~196KB).
  Finding 4 is precisely isolated but not yet root-caused.

## Finding 4 — actually TWO bugs, 2 of 3 fixed, 1 remains (session 2)

Continued via lldb on a real -O0 `mojoc_dbg2` build (Makefile's stage2
recipe doesn't pass `-O`, so gcc defaults to -O0; `python3 fire.py build
... -O0` did NOT actually change codegen — confirmed by identical
`nm`-reported addresses/disassembly between a "-O0" and a default build,
so that flag path is untrustworthy for debug builds; built manually via
direct `gcc-mp-15 -fgimple ... -x c mojo.ci ...` instead, mirroring
`stage2/mojo`'s recipe exactly). Breakpoints on the compiler's own
compiled functions (`_declare_var`, `_quick_type`, even their
`GimpleGen__*` trampolines) never fired despite the bug clearly
occurring — root cause never found; abandoned that angle.

Root-caused via shim-side instrumentation instead (a `_sce_simple_emit`
monkeypatch printing a traceback whenever the R2 chokepoint's container-
kind check is about to fire, run via `python3 fire.py <file>
--dump-full` — safe since it's the shim, not self-hosted source). This
reproduces `myinterpreter.py`'s `from_base` bug family AND revealed it's
actually two independent, real logic bugs in the compiler itself (not
self-host-only — the shim hits them too when compiling the compiler's
OWN source as a target, e.g. `python3 fire.py gimple_module_gen.py
--dump-full`):

**Bug A (FIXED)** — `gimple_gen_methods.py`'s `_lower_method_call`: when
a method receiver's static type is unresolved (opaque `int64_t`, e.g. a
`self`/`gen`-typed struct field the self-hosting param-typing pass
hasn't reached), the code guessed the receiver's real type purely from
the METHOD NAME being called. `.update()` is real on BOTH `dict` and
`set` in Python, but the guess unconditionally forced `MojoDict *`
(unlike `.add()`/`.discard()`, correctly routed to `MojoSet *`, or
`.clear()`/`.remove()`, already runtime-dispatched via
`mojo_is_registered_dict`/`_set` per DESIGN.html R5). Concrete trigger:
`gimple_module_gen.py`'s own `self._selfhost_locked_param_types.update(
(...))` — `_selfhost_locked_param_types` is a genuine `set`, so forcing
`MojoDict *` then coercing the tuple-literal argument (materialized as
`MojoList *`) against `MojoDict *` tripped DESIGN.html R2's chokepoint.
Fixed by giving `.update()` on an opaque receiver the same
`mojo_is_registered_set`-gated runtime dispatch as `clear`/`remove`,
with a static short-circuit straight to the set-loop path (no dict
branch emitted at all) when the argument's OWN static type is provably
`MojoList *`/`MojoSet *` — emitting the dict branch's `_coerce_to_type`
unconditionally in THAT case trips the same R2 chokepoint at EMISSION
time regardless of which branch runs at C runtime, since the chokepoint
is a compile-time check on the generated C, not a runtime one.

**Bug B (FIXED)** — `gimple_module_gen.py`'s `_scan_body_for_local_field_
access` (the "phantom scalar field" scanner, used so `getattr`-style
dynamic-looking member access on a struct doesn't silently stub to a
no-op): it walked every `MemberExpr` on an unambiguously-typed local
regardless of whether it was the callee of a `CallExpr` (`obj.method(
...)`, a real method call) or a bare value read, and minted a phantom
`int` field for any name not already a known field AND not in a narrow
builtin-container-method allowlist. A real, custom method
(`DispatchPattern.add_call_site`/`.add_callee` in `gimple_solvers.py`)
fell through this gap. Fixed by checking `target_def.methods` (and one
level of `bases`) for a matching method name before minting a field.

Both verified: `compile_stdlib.py` 664/664 unchanged across all landed
states, `check-linkmode`/`check-selfhost`/`make bootstrap` all green,
and both measurably closed part of the shim-vs-noshim gap on the real
target (`fire.py --dump-full fire.py`): first-diff offset moved from
2390 (original) through several intermediate points as each fix
landed, gap size dropped from the original ~5MB down to ~5.8MB... at
one intermediate point it temporarily GREW (noshim > shim) because Bug
A's fix, compiling `myinterpreter.py` cleanly, let the build reach
Bug B's location where it hadn't before — a reminder that gap SIZE
isn't monotonic evidence by itself; always check the first-diff offset
too.

**Bug C (found, NOT fixed — reverted after breaking the build)** — the
remaining divergence after A+B: `fire.py --dump-full fire.py` first
differs at offset 19260, noshim ~5.8MB larger. Root cause: `class
GimpleGen` (defined in `gimple_codegen.py`) is registered TWICE into
this compile's shared `struct_field_types['GimpleGen']` — once via a
SYNTHETIC ~40-field stand-in (`_selfhost_gimplegen_stmts`, a frozen
parse used so extracted-helper functions like `_declare_var(gen, ...)`
can type their `gen`/`self` first param as `GimpleGen *` even in a
temp_gen that never sees the real class in its own file's transitive
closure — see `_selfhost_gen_self_param_ctype`'s docstring in
`gimple_gen_funcs.py`), and again by the REAL `class GimpleGen` node
once it's found in SOME temp_gen's own `stmts + imported_stmts`
(`gen_module_impl`'s "yield ownership to the REAL node" block,
`gimple_module_gen.py` ~line 2927). `_struct_name_owner['GimpleGen']`
correctly transfers to the real node, but `struct_field_types[
'GimpleGen']` (the FIELD dict actually used for typedef emission)
is never reset — it keeps whichever fields were populated FIRST,
synthetic-stand-in fields unioned with real ones, in whatever order
self-hosted vs shim happen to process temp_gens (a dict/set-iteration-
order difference between the two, the same recurring bug class as
every other self-host-only divergence in this codebase). Confirmed via
a byte diff: noshim's typedef body for `GimpleGen` includes ~40 extra
synthetic fields (`BUILTIN_VALUE_MAP`, `_KNOWN_SIGS`, `_CALL_RENAMES`,
...) the shim's own struct doesn't carry at this position.

Attempted fix: reset `struct_field_types['GimpleGen'] = {}` at the
ownership-transfer point when the previous owner differs from the real
node, letting the real struct's own field-scan passes repopulate it
fresh. This is WRONG and was reverted: `struct_field_types['GimpleGen']`
is also fed by `_selfhost_scan_gimplegen_extra_fields` (fields ONLY
ever written in extracted-helper files like `gimple_gen_infra.py`, e.g.
`gen._cpp_gen_self_fields = {}`, never in `class GimpleGen`'s own
body since those methods were extracted OUT of the class) — a blind
reset discards those too, and nothing re-populates them from the real
struct's own (helper-file-blind) method scan. Worse: because
`gen_module_impl` runs once per file in the transitive closure and
functions get lowered (their C text finalized) as each file is
processed, resetting this SHARED dict mid-compile invalidates the field
TYPE some already-emitted function used for a value CAST while a
later-emitted function sees the NEW (reset) field type for the same
struct's DECLARATION — a declared-vs-assigned type mismatch. Manually
rebuilding `mojoc` with this change hit exactly that: hard `gcc -fgimple`
errors ("non-trivial conversion in 'var_decl'") for `self->_cpp_gen_
self_fields = _t48;` (an `int64_t` value into a `struct MojoDict *`
field) and several sibling fields. **Reverted** — confirmed the revert
restores byte-for-byte the pre-attempt `gimple_module_gen.py` state and
rebuilds clean.

A correct fix needs the registration to happen EXACTLY ONCE, before any
code referencing a `GimpleGen` field gets emitted for ANY file in the
closure — not as a per-file, re-triggerable check inside
`gen_module_impl`. That's an architectural change (move the real-vs-
synthetic resolution to the same one-time pre-pass that already parses
`_selfhost_gimplegen_stmts`, i.e. `_selfhost_register_gimplegen` in
`gimple_codegen.py`, before `gen_module_impl` ever runs for ANY file),
not a quick patch — left for a future session. Bugs A and B are real,
safe, and landed.

## Finding 4 Bug C — RESOLVED (session 3, commit `585879c`)

Root-caused to a chain of independent self-hosted-only bugs (the
architectural one-time-seed idea from the previous session's note above
turned out to be necessary-but-not-sufficient — it was landed, but the
underlying field-scan was ALSO silently broken several different ways,
each masking the next once the prior one was fixed):

1. **`glob.glob()` returns 0 matches self-hosted, always**, regardless of
   directory correctness — confirmed by hand: `os.listdir(d)` + manual
   `startswith('gimple_')`/`endswith('.py')` filtering found the correct
   17 files in the same directory where `glob.glob(os.path.join(d,
   'gimple_*.py'))` returned empty. `_selfhost_scan_gimplegen_extra_
   fields` (gimple_gen_funcs.py) now scans via `os.listdir()` instead.
2. **Bare `dict = {}` annotations** (no value ctype) on
   `self._selfhost_gimplegen_extra_fields` left the value ctype
   unresolved self-hosted — reads came back as the raw `MojoDict`-value
   pointer bits reinterpreted as `int64_t` (printed as a huge decimal
   like `4374397560`) instead of dereferencing as `char *`. Fixed via
   explicit `dict[str, str]`.
3. **`_selfhost_merge_field`'s upgrade condition excluded `_Bool`** —
   only allowed upgrading a generic `int`/`int64_t` default to a
   POINTER type (`_ct.endswith(' *')`), so a `_Bool` literal seen after
   the default was silently kept at `int64_t`. Fixed to also accept
   `_ct == '_Bool'`.
4. **`gen._selfhost_src_dir` was never threaded through** to the scan,
   so it fell back to `gimple_codegen._SELFHOST_DIR`/`.`/`..`, none of
   which reliably had `gimple_*.py` siblings in the compiled binary's
   process CWD. Fixed by threading it through with the same fallback
   order `_selfhost_load_gimplegen_class` already uses.
5. **The shared `gimple_exprtypes._walk_ast`/`_walk_ast_into` utility
   has a real self-hosted bug**: `isinstance(node, str) or
   isinstance(node, int) or isinstance(node, float) or
   isinstance(node, bool)` evaluates TRUE for essentially every real AST
   dataclass instance self-hosted (confirmed via instrumentation: of
   5457 total `_walk_ast_into` calls compiling `fire.py` self-hosted,
   5027 were misclassified as scalar leaves and never recursed into;
   the `dataclasses.is_dataclass` branch was reached 0 times). Reordering
   to check `is_dataclass` FIRST fixes the walker correctly — verified
   via a differential node-count check against the shim — but this
   exposed a SEPARATE, well-documented, actively-tracked cost:
   `bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md`'s
   O(N²) whole-program rescan, previously tolerated (if slow) via
   CPython but genuinely catastrophic self-hosted once the walker
   actually recurses (confirmed: `MOJO_NO_SHIM=1 ./mojoc gimple_gen_
   loops.py --dump-full` alone — unrelated to this scan — grew to 15GB+
   RSS and SIGSEGV'd with the reordered walker; RSS growth measured at
   ~750MB/sec). Fixing `_walk_ast` itself is out of scope here (it would
   require ALSO fixing the O(N²) rescan cost first, per that doc's own
   multi-phase, multi-week history) — **`_walk_ast` was left as-is,
   still broken self-hosted, this bug remains open there**. Instead, a
   NEW dedicated narrow statement-only walker
   (`_selfhost_walk_stmts_for_assign_targets`, gimple_gen_funcs.py) was
   written specifically for GimpleGen's narrow need (`self.x = <literal>`
   assignments are always direct statements, never nested in an
   expression, so only statement-level body-bearing fields — if/while/
   for/try/with/match/comptime — need recursing into, not full generic
   AST traversal), sidestepping the shared utility entirely.
6. **Within that new walker, a boxed self-hosted string field compared
   with `==` failed to match** even when semantically equal:
   `_tgt.obj.name == p0` (both a boxed `MemberExpr.obj.name` AST-field
   read and a `str.lstrip()` result) — confirmed via layered
   instrumentation that EVERY upstream counter (files found, functions
   matched, statements visited, assign-shaped statements found) matched
   the shim exactly, and this ONE comparison was the entire remaining
   divergence at that layer (266 matches expected, 0 found). Fixed via
   `_as_str()` normalization on both sides:
   `_as_str(_tgt.obj.name) == _as_str(p0)`.
7. **`_selfhost_literal_ctype` used `type(_val)` as a dict key** — same
   underlying mechanism as #5's bug (self-hosted `type()` does not
   reliably identify a class the way CPython's real class objects do
   for dict-key purposes). `_SELFHOST_LITERAL_CTM.get(type(_val))`
   returned `None` for the overwhelming majority of values self-hosted
   (confirmed: of 141 literal-typed matches via the shim, only 22
   resolved self-hosted with the dict-lookup form). Rewritten as a
   plain isinstance chain. **This was the fix that actually closed the
   gap** — confirmed via debug counters matching the shim exactly
   (`total-fields=88`, all 5 spot-checked fields with correct types)
   after this specific change and no earlier one.
8. **`fire.py`'s own `build_executable`/`link_executable` link path was
   missing the 512MB stack-size linker flag** that `driver.py`'s
   link-mode path already has (`otool -l mojoc` showed `stacksize 0`
   instead of `536870912`) — an unrelated infra gap discovered while
   investigating #5's crash, fixed for parity regardless of whether
   `_walk_ast` itself ever gets fixed (an 8MB default stack is
   marginal for this compiler's own deeply-recursive regex engine and
   AST walkers even without `_walk_ast`'s bug).

Verified via layered instrumentation at every stage (file discovery →
function matching → statement traversal → assignment-target matching →
literal-type inference → field storage), comparing self-hosted counters
against the shim's after each fix, since several of these bugs
completely MASKED the next one downstream (e.g. fixing #1-4 moved the
count from 247/259 fields to 266/292 but NOT further, because #5-7 were
still silently eating almost every match). Full gate green: check-
linkmode (3/3), check-selfhost, from-scratch stdlib dylib rebuild (0
skips), compile_stdlib.py (664/664, 0 unexpected), make bootstrap
(180/180 files match across 3 stages). Landed in commit `585879c`.

### A separate bug found and fixed in the same session: bytes-literal concat non-determinism

While re-verifying the full `fire.py --dump-full` comparison after the
above, found `test_noshim_dumpfull.py` still failing — but for a
DIFFERENT reason, confirmed unrelated to Bug C: `mojo_bytes_from_cstr
(<huge decimal number>)` calls appearing in the generated C for any
`bytes_literal + x.encode()`-shaped expression (concrete repro:
`b'\0missing:' + name.encode()` in `cas.py`), where the number is a
raw heap memory address — non-deterministic run to run (confirmed: two
consecutive self-hosted runs of the identical binary on the identical
input produced two DIFFERENT addresses at this exact call site, while
the shim consistently produced the correct `mojo_bytes_from_cstr
(_t4)` symbolic reference both times).

Root cause: `_as_bytes`, a nested closure inside `_lower_binary_tail`'s
MojoBytes-concat handling (`gimple_gen_exprs.py`, `op == '+' and (lt ==
'MojoBytes *') != (rt == 'MojoBytes *')` branch), had unannotated
`ct`/`cv` parameters. Matches this codebase's established "hoisted/
nested closures need explicit param annotations self-hosted or they
misbehave" pattern (see the `--dump-full-determinism-progress` memory's
own GOTCHA note) — without an explicit `str` annotation, `cv` (a
proper `_tNN` variable-reference string, e.g. from a stubbed
`.encode()` call) got boxed and read back as its raw pointer bits when
interpolated into the f-string building the call expression. Fixed via
explicit `def _as_bytes(ct: str, cv: str):`. Confirmed deterministic
across 3+ repeated runs after the fix, and confirmed the shim was
already correct throughout (this bug never affected the shim's own
output). Landed in the same commit (`585879c`).

## Finding 5 — struct EMISSION ORDER divergence (found, NOT fixed, session 3)

With Bug C's field CONTENT now correct and the bytes-literal bug fixed,
`test_noshim_dumpfull.py` still fails — the first differing byte moved
from deep inside the (now-correct) `GimpleGen` field list to its
POSITION in the file: self-hosted emits `typedef struct GimpleGen`
immediately after `typedef struct Generator`, while the shim emits
`typedef struct GlobalStmt` at that same position (i.e. `GimpleGen`
appears somewhere else in the shim's output — content matches, only
ORDER differs). Total diff is still ~1.4M lines (`diff` counts every
downstream line as different once ANY earlier struct reorders, even
though most of the actual STRUCT CONTENT is byte-identical — this is a
"cascading reorder" diff shape, not a content-corruption one).

**Investigated further, hypothesis DISPROVEN**: the obvious first
suspect — `track_best` (a plain dict in `gen_module_impl`'s
`emit_struct_defs` block, ~gimple_module_gen.py:7897, whose
`.values()` iteration order was assumed to drive final struct emission
order) — was instrumented directly (log struct name + a 0-based
sequence number for its first ~180 entries, gated behind
`MOJO_ORDER_DEBUG`, compared self-hosted vs shim). Result: **the
sequences are IDENTICAL** — all 179 unique struct names, including
`Generator` at position 112, `GlobalStmt` at 129, and `GimpleGen` at
178 (dead last), matched EXACTLY between self-hosted and the shim, in
both a fresh rebuild and a repeat run. Yet the byte-level `.ci`
comparison, run immediately after with the SAME binary, still showed
the identical positional divergence (`GimpleGen` right after
`Generator` self-hosted, `GlobalStmt` there in the shim) — and `grep
-c` confirmed each struct's typedef appears exactly once in each
output (no duplicate-emission explanation either).

**Conclusion: `track_best`'s loop is NOT what controls final struct
position in the output for structs like these.** Rereading the
surrounding code, this loop is gated by `if sd.name not in
self._emitted_structs:` — meaning it is a "catch anything not already
emitted" fallback/dedup pass, not the primary emission path. The
actual likely mechanism (not yet confirmed, just inferred from the
codebase's overall shape): `fire.py`'s transitive closure is compiled
FILE BY FILE (`_compile_imported_module`, once per module), and each
file's own compile likely emits ITS OWN locally-first-seen struct
typedefs into that file's C-code fragment as they're encountered,
with the FINAL `.ci` being a concatenation of per-file fragments in
FILE COMPILE ORDER — so a struct's position in the final output is
really a question of WHICH FILE first referenced it, and WHEN that
file got compiled relative to others, not of any single dict's
iteration order. This is structurally a different (and deeper)
question than every previous finding in this doc — those were all
"one function's own local dict/set iterates differently self-hosted
vs shim"; this one is "the ORDER FILES GET COMPILED differs
self-hosted vs shim", which could stem from import-graph traversal
order, `self._module_stmts`/`self._compiled_modules` iteration
somewhere, or something else entirely in the do_imports driver loop.

**Second hypothesis tested, ALSO disproven**: instrumented
`_compile_imported_module` (gimple_gen_resolve.py) to log `module_name`
as each module starts compiling, gated behind `MOJO_ORDER_DEBUG`
(first attempt used `gimple_ctypes.os.environ.get(...)` and silently
produced zero output self-hosted — a real, separate self-hosted
reliability wrinkle in accessing `os` via a re-exported module
attribute rather than a direct `import os`; switching to the file's
own already-present `import os` and calling `os.environ.get(...)`
directly fixed the debug output itself). Result: **the full 280-entry
module-compile sequence is IDENTICAL self-hosted vs shim**, confirmed
via a complete `diff` (not just eyeballing the first N lines) — same
280 modules, same order, from `build_config` first through to the
last. So module-compile order is NOT the mechanism either.

**Status at end of session 3: both obvious iteration-order hypotheses
eliminated, true mechanism still unknown.** Two independent, cleanly
disproven candidates:
1. `track_best`'s dict iteration order within one module's own
   struct-emission pass — matched exactly, byte output still diverged.
2. Module compile order itself (which module's
   `_compile_imported_module` call happens when) — matched exactly
   (all 280 entries), byte output still diverges at the same position
   (first differing byte ~19215, `GimpleGen` right after `Generator`
   self-hosted vs `GlobalStmt` there in the shim).

**Next steps for a future session**: given both "when does X get
iterated/visited" hypotheses are eliminated, the remaining candidate
is HOW the already-correctly-ordered pieces get assembled into the
final text — i.e. look at the actual STRING CONCATENATION / list-
building logic (`parts.append(...)`/`parts.extend(...)`-style
assembly, or wherever per-module C-code fragments get joined into the
final `.ci` text) rather than any iteration-order question. It's also
worth directly checking whether `Generator`'s and `GimpleGen`'s
STRUCTS are even coming from the same emission pass in both
self-hosted and shim at all — the `track_best`/`emit_struct_defs`
block investigated here might simply not be the site responsible for
this specific pair (recall gimple_module_gen.py has at least 10
separate `typedef struct` emission call sites — `_stub_guard_name`
call sites at lines ~4078, 4084, 5228, 6769, 6863, 6960, 7950, 8115,
8153 hint at several distinct struct-stub-emission code paths beyond
the one instrumented here). A more direct approach: add a one-off
`print`/log statement immediately before EVERY `parts.append(f"typedef
struct {X} {{"` call site (there are ~10), each tagged with its own
site identifier, then compare self-hosted vs shim to see WHICH site
actually emits `Generator`/`GimpleGen`/`GlobalStmt` — this was not
attempted this session and is the recommended starting point.

## Finding 5 UPDATE — root cause actually found (same session, continued)

Finding 5's text-assembly-vs-iteration-order question above turned out
to be moot: continued digging (comparing the FULL, still-extracted
`GimpleGen` struct body from a real end-to-end compile, not just the
scan function's return value in isolation) showed the struct's field
CONTENT itself was STILL wrong for ~19 fields, despite the struct's
total field COUNT matching (292=292). This directly explains Finding
5 too: the topological struct-emission sort (gen_module_impl,
~gimple_module_gen.py:6933-6962 — NOT the `track_best` loop
instrumented above, which really is just a fallback/dedup pass) orders
structs by resolved field-type DEPENDENCIES; a GimpleGen with fewer
correctly-typed struct-pointer fields has fewer dependency edges and
becomes topologically "ready" in an earlier pass self-hosted than the
shim's correctly-typed version. Finding 5 is NOT a separate bug — it
is a symptom of Bug C being incompletely fixed. `track_best`'s
iteration order and module-compile order were both real, correctly-
eliminated hypotheses; they just weren't where the actual remaining
corruption lived.

Tracing why the struct content was still wrong found the SAME field-
type-inference machinery already fixed for the extracted-helper scan
(`_selfhost_scan_gimplegen_extra_fields`, in `585879c`) had an
UNFIXED sibling: `_selfhost_gimplegen_field_types`'s own class-body/
`__init__`/method scan (used for `self.X = <literal>` writes inside
`class GimpleGen`'s OWN methods, as opposed to the extracted-helper
files) still called `gimple_exprtypes._walk_ast(_m.body)` directly —
the exact same broken shared utility, just not yet worked around here.
Three real fixes landed for this (commit `dba69b8`, see that commit
message for full detail): a dedicated walker replacing `_walk_ast`
(mirroring the sibling scan's fix), `TernaryExpr` handling in
`_selfhost_literal_ctype` (a real gap independent of the walker issue
— `gen.field = X if cond else Y` shaped RHS values were never
literal-inferable at all, in either the shim or self-hosted), and a
positional workaround for `__init__` lookup after discovering `.name`
reads on `FunctionDef` nodes from this object graph are corrupted
self-hosted.

That last discovery — `.name` corruption — turned out to be the tip of
something bigger: `.type_ann` reads on `AssignStmt` nodes from the
SAME object graph are ALSO corrupted self-hosted (confirmed by hand:
`isinstance(getattr(_n, 'type_ann', None), str)` evaluates `False`
self-hosted for an assignment the shim correctly reads as the string
`"DispatchSolver | None"`). This is NOT the same `_as_str()`-shaped
bug as everywhere else in this doc — `_as_str()` recovers a boxed
STRING value; here the value isn't even TYPED as a string self-hosted,
it's outright wrong/garbage at the attribute-read level. This affects
the smaller remaining set of GimpleGen fields whose correct type comes
from an explicit annotation on the assignment itself (`self.X: T = ...`)
rather than `__init__` parameter passthrough (`_dispatch_solver`,
`_cpp_gen_self_struct`, `_cpp_last_tuple_slot_ctypes`, and similar) —
NOT fixed, and is now the actual, precisely-isolated remaining blocker
for `make check-noshim-dumpfull` (diff 1,419,444 lines, first
differing byte still ~19215 — same GimpleGen-struct-position symptom).

**What makes this different from every other bug in this doc**: every
previous self-hosted-only bug found across this whole investigation
(here and in the sibling `--dump-full-determinism-progress` /
`selfhost-shimless-progress` memories) has been a *comparison* or
*key-typing* problem — a boxed value compared/used-as-key without
`_as_str()`, a `type(x)`-keyed dict losing fidelity, an isinstance
check misclassifying a dataclass instance as a scalar. All of those
are fixable by normalizing HOW an already-correctly-typed value gets
used. This one is different: the underlying attribute READ itself
(`.name` on a `FunctionDef`, `.type_ann` on an `AssignStmt`) returns
wrong data self-hosted, with no normalization able to recover it,
specific to objects built by `_selfhost_load_gimplegen_class`'s
runtime meta-reparse of `gimple_codegen.py` (invoking the self-hosted-
compiled `Parser` as a library call at RUNTIME, not through the
ordinary compile-then-immediately-consume flow every other AST node in
this codebase goes through). A `FunctionDef`/`AssignStmt` built the
ORDINARY way (parsed once, consumed during that same compile) has
never shown this symptom anywhere else in this codebase's history.

**Recommended next steps for a future dedicated session** (this is
likely a substantial, Bug-C-sized undertaking in its own right, not a
quick patch):
1. Confirm the SCOPE: write a minimal self-hosted repro that parses a
   tiny class via `Parser(...).parse_module()` at runtime (mimicking
   `_selfhost_load_gimplegen_class`'s exact call shape) and reads
   `.name`/`.type_ann` off its methods/assignments immediately — does
   the corruption reproduce on a MUCH smaller object graph, or is it
   specific to `class GimpleGen`'s real size/complexity (4000+ lines,
   363 methods)? This determines whether the bug is about runtime
   re-parsing in general or something size/complexity-dependent (e.g.
   a GC/memory-pressure interaction, or an internal object-pool/arena
   reuse bug that only manifests past some object count).
2. If it reproduces small: this is a general, `_selfhost_load_
   gimplegen_class`-independent bug in the self-hosted runtime's
   dataclass-field-read path for RUNTIME-CONSTRUCTED (not compile-time)
   AST objects specifically — worth searching the runtime C sources
   (`runtime/mojo_runtime.c`) for whatever backs dataclass field access
   (`_mojo_dispatch_getattr` and friends, mentioned in several comments
   throughout this codebase) to understand why object PROVENANCE
   (parsed live at runtime vs. parsed during the normal compile pass)
   would matter to that dispatch at all — it shouldn't, structurally,
   unless something about `_SELFHOST_GG_CACHE`'s caching, or the
   isolation between the "outer" self-hosted process and objects it
   constructs mid-run, is involved.
3. If it does NOT reproduce small: narrow by binary-searching how much
   of `class GimpleGen` needs to be included in the re-parsed source
   before `.name`/`.type_ann` corruption appears, to find the actual
   trigger (a specific field count, method count, or file size
   threshold).
4. Once root-caused, re-verify ALL of this session's `_as_str()`-based
   fixes are still needed/correct — some of the earlier `_as_str()`
   "fixes" in this exact investigation may have been treating a
   SYMPTOM of this same deeper corruption rather than the classic
   boxed-string-as-dict-key issue; they were verified safe and net-
   positive via the full gate either way, but the ROOT explanation for
   a few of them may need revising once this is understood.

## Finding 5 UPDATE 2 — minimal repro built, precise diagnosis (same session, continued further)

Step 1 of the plan above was carried out: built a minimal in-process
repro (parse a TINY 5-line, 2-method synthetic class via the exact
same call shape as `_selfhost_load_gimplegen_class` —
`ast_rewriter.rewrite(Parser(py_tokenize(src)).with_filename(...)
.parse_module())` — inline inside `_selfhost_register_gimplegen`,
gated behind a debug env var so it runs as part of the real self-
hosted `mojoc` binary rather than needing a separate standalone test
program, since standalone-binary attempts (`mojoc build` on a small
test file importing `mojo_compiler`/`ast_rewriter`) hit at least three
DIFFERENT unrelated pre-existing self-hosted bugs unrelated to this
investigation — a `'mo' undeclared` gcc error compiling `build`'s
do_imports path, corrupted `--dump-full` output requiring
`MOJO_NO_SHIM` for self-referential compiles specifically (not
relevant to an arbitrary test file, but the corruption appeared
anyway), and a duplicate-declaration gcc error
(`Parser__parse_expr` re-declared) with `#line` markers pointing at
plain comment text. None of these three were investigated further —
each is its own separate, real, pre-existing self-hosted bug outside
this investigation's scope; noted here only so a future session
doesn't waste a cycle rediscovering them via the same approach).

**Result: the corruption reproduces at tiny scale — NOT size/
complexity-dependent as originally hypothesized.** On the 2-method
synthetic class:
- `.name` on both `FunctionDef` methods read CORRECTLY self-hosted
  (`method_name=[__init__]`, `method_name=[bar]`, matching the shim
  exactly) — contradicting the earlier finding that `.name` was
  corrupted on GimpleGen's real 363-method class. This means the
  EARLIER `.name` corruption was itself likely size/count-dependent
  (or a different, as-yet-unidentified trigger specific to GimpleGen's
  real scale) — the positional-lookup workaround already landed for it
  remains valid and necessary regardless, since it fixed real, verified
  behavior on the actual GimpleGen class.
- `.target.member` on the `AssignStmt` nodes ALSO read CORRECTLY
  self-hosted (`target_member=[x]`, `target_member=[y]`, matching the
  shim) — confirming the `AssignStmt` NODE ITSELF is otherwise intact,
  correctly constructed, and its OTHER fields are readable.
- `.type_ann` specifically reads as **neither a string NOR `None`**
  self-hosted (`is_str=False`, `is_none=False`) — ruling out "the
  self-hosted Parser simply never populates `type_ann` for this
  syntax shape" (a parsing omission would show `is_none=True`). The
  field WAS set to something; reading it back gives a value that is
  neither the correct `char *` string nor a legitimate `None` — this
  is the exact "a value's real bits get reinterpreted as the wrong
  ctype" symptom that has recurred constantly throughout this entire
  investigation (and the broader codebase — see the `_lower_
  StringLiteral` docstring's own historical note about the identical
  symptom for boxed string literals), just now happening on the
  self-hosted COMPILER'S OWN core `AssignStmt.type_ann` field rather
  than a user-level GimpleGen field.

**Refined diagnosis**: this now looks like a `struct_field_types`-
style ctype-INFERENCE problem for `AssignStmt.type_ann` itself (a
core, built-in AST node class from `mojo_compiler.py`, not a
GimpleGen-specific field) — most likely, the self-hosted compiler's
own field-type inference for `type_ann` (presumably an untyped/
`object`-annotated dataclass field in `mojo_compiler.py`, since it can
legitimately hold either `str` or `None`) resolves to a DIFFERENT
ctype (`int64_t` instead of `char *`) depending on the CALL CONTEXT
that constructs the `AssignStmt` instance — normal top-level parsing
apparently infers it correctly (used successfully thousands of times
elsewhere in this same self-hosted binary's own compile of itself),
but construction via this specific NESTED runtime `Parser(...)`
invocation does not. This reframes the bug from "attribute reads are
generally unreliable on runtime-reparsed objects" (the earlier, more
alarming hypothesis) to something narrower and more actionable: a
field-ctype-inference gap specific to how `mojo_compiler.py`'s OWN
`AssignStmt.type_ann` field gets typed when instances originate from
a nested/runtime parse call rather than the top-level one.

**Recommended next steps for a future session** (revised from the
plan above, now that a working, cheap, in-process repro exists — no
need for the standalone-binary approach and its unrelated blockers):
1. Extend the SAME inline mini-repro technique (parse a tiny synthetic
   source string via `Parser(...).parse_module()` inside any already-
   working self-hosted-compiled function, gated behind a debug env
   var, write results to a file) to test OTHER core AST node fields
   similarly typed `object`/optional in `mojo_compiler.py` — does
   `AssignStmt.value`, `FunctionDef.return_type`, or other similarly-
   shaped fields show the SAME corruption when constructed via a
   nested runtime parse, or is `type_ann` specifically affected? This
   determines whether the bug is about the `type_ann` field
   specifically or a broader class of optional/union-typed fields.
2. Compare: does calling `Parser(...).parse_module()` from a
   DIFFERENT nesting context (e.g. directly from `main()`/top-level,
   vs. from deep inside `_selfhost_register_gimplegen`'s own call
   stack) change the result? If nesting depth/call-stack-shape matters,
   that points toward a codegen bug in how struct_field_types gets
   seeded/scoped per call site rather than a single global bug.
3. Search `gimple_codegen.py`/`gimple_module_gen.py` for wherever
   `type_ann` (as a `mojo_compiler.AssignStmt`/`VarDecl` field name)
   gets its ctype inferred in `struct_field_types['AssignStmt']` — is
   there a SEPARATE/duplicate registration path for core AST classes
   (as opposed to GimpleGen) that could explain a call-site-dependent
   ctype? This is architecturally the closest analogue to everything
   else this whole investigation has been about, just for a built-in
   AST class instead of a user-defined one.

## Finding 5 UPDATE 3 — reentrancy/nesting-depth hypothesis tested and ELIMINATED

Recommended step 2 from "Finding 5 UPDATE 2" above was carried out:
does the `.type_ann` corruption depend on HOW DEEP the nested
`Parser(...).parse_module()` call sits within an already-executing
compile? Moved the identical mini-repro (tiny synthetic class, same
call shape) from deep inside `_selfhost_register_gimplegen` (called
partway through `gen_module`, well after the outer compile's own
parse/tokenize/codegen work is underway) to the very FIRST line of
`_run_pipeline` itself — literally before the outer file's own
`tokens = py_tokenize(mojo_src)` / `Parser(tokens)...` call, as
shallow/early as any nested nested nested invocation could possibly
be within a real self-hosted compile.

**Result: corruption reproduces identically at both nesting
depths/timings.** `is_str=False`, `is_none=False` at the "early"
position too — exactly the same symptom as the "deep" position. This
RULES OUT reentrancy/call-stack-depth as the trigger; whatever a
"nested"/"secondary" `Parser(...).parse_module()` invocation is doing
wrong, it's wrong from the very first opportunity, not something that
accumulates or gets triggered by stack depth or by how much of the
outer compile's own state has already been touched.

**Refined framing** (supersedes "Finding 5 UPDATE 2"'s "call-context-
dependent" language, which implied nesting/timing mattered — it
doesn't): the bug is simply that ANY `Parser(...).parse_module()`
invocation OTHER than `_run_pipeline`'s own single canonical call for
the outer file produces an `AssignStmt` whose `.type_ann` reads
wrong self-hosted — regardless of when in the process that second
invocation happens. This is architecturally close to "the compiled
binary's `Parser`/tokenizer/AST-rewrite machinery only works
correctly the ONE time `_run_pipeline` itself calls it" — worth
testing directly in a future session: does a **third** invocation (two
nested calls in a row, not just one) behave the same way, or does it
get progressively worse/different? Does the SAME symptom appear for a
`VarDecl`'s `type_ann` (constructed at a different call site,
`mojo_compiler.py:2293`/`2459`/`4444`) or is it specifically tied to
`AssignStmt`'s construction site (`mojo_compiler.py:2280`)? These two
checks would help decide between "any second invocation of Parser
breaks" (a single, central culprit) vs. "type_ann specifically is
broken on ANY AssignStmt regardless of which Parser call created it,
including the outer one, and the outer one only 'looks fine' because
nothing downstream in the REAL compile of fire.py ever critically
depends on the correctness of the SPECIFIC handful of `AssignStmt`
nodes whose `.type_ann` would have been wrong" (a MUCH bigger, harder-
to-see bug that's been silently present all along, just never load-
bearing until this investigation's synthetic tests started actually
reading `.type_ann` back and checking it).

## Followups (not fixed this session, worth a future audit)

- **The `.name`/`.type_ann` attribute-read corruption on objects from
  `_selfhost_load_gimplegen_class`'s runtime meta-reparse is now THE
  PRIORITY ITEM** for a future session — see the "Finding 5 UPDATE"
  section immediately above for full detail and recommended next
  steps. This is a genuinely new class of self-hosted bug (attribute-
  read corruption, not a comparison/key-typing issue) that may affect
  other runtime-meta-reparse patterns in the codebase beyond this one
  GimpleGen use case.
- **`type(x)`-keyed dict/cache lookups are a confirmed-unreliable
  self-hosted pattern**, found independently in TWO places this session
  (`_WALK_FIELD_NAMES_CACHE` in gimple_exprtypes.py, and
  `_selfhost_literal_ctype`'s old form in gimple_gen_funcs.py) — both
  silently returned wrong/`None` results self-hosted despite working
  perfectly via the shim. `_WALK_FIELD_NAMES_CACHE`'s own fix
  (`type(node).__name__` as the key instead of `type(node)`) is landed
  and safe, but `_selfhost_literal_ctype`'s fix went further (a full
  isinstance chain, no dict lookup at all) since even `.__name__` felt
  like an unnecessary residual risk once the pattern was this
  precedented. Worth a codebase-wide `grep -n '\.get(type('` (and
  similar `[type(...)]` dict-subscript patterns) audit for other
  instances — each one is a silent, hard-to-detect self-hosted-only
  correctness bug that a shim-only test suite will never catch.
- **Unannotated closures with string parameters are a confirmed-risky
  self-hosted pattern**, found again this session (`_as_bytes` in
  gimple_gen_exprs.py) on top of the pre-existing GOTCHA already noted
  in the `--dump-full-determinism-progress` memory (hoisted closures
  needing explicit dict/set param annotations). Worth a broader audit
  for other unannotated nested-function/closure definitions handling
  string-typed values self-hosted.
- Finding 5 (struct emission order) above remains fully open — the
  `track_best` dict-order hypothesis was tested and DISPROVEN this
  session; the real mechanism is believed to be per-FILE compile
  order (which module gets compiled when), not any single dict's
  iteration order within one module's own struct-emission pass.

## Session 4 final summary (2026-09-14)

Continuing directly from session 3's Bug C work (`585879c`/`dba69b8`) and
the Finding 5 investigative arc (`89d4d7d` through `fbf73dc`). Landed
seven independent, gate-verified fixes (three commits: `5cc83e5`,
`078c103`, `972850f`), each confirmed via `make check-selfhost` at
minimum, several via the FULL gate (check-linkmode, check-selfhost,
compile_stdlib.py 664/664 0 unexpected, make bootstrap 180/180). Diff
narrowed from ~3.8MB (session start) to ~350KB (session end) — real,
substantial, verified progress — but check-noshim-dumpfull is **not
yet zero**.

### The seven fixes

1. **`AssignStmt`/`VarDecl.type_ann` ambiguous-boxed-`int64_t` isinstance
   bug** (`gimple_gen_funcs.py`'s `_selfhost_ann_ctype`, plus two sibling
   `f.type_ann` call sites). Root cause: these fields are hardcoded
   ambiguous `int64_t` in `gimple_module_gen.py`'s `struct_field_types`
   (`struct_boxed_fields`), and `mojo_isinstance`/`mojo_isinstance_p`
   (`runtime/mojo_runtime.c`) never implement `type_id 4` (str) for an
   ambiguous boxed value — they unconditionally return 0. So
   `isinstance(x, str)` was FALSE self-hosted for every real string
   value in that field, not just malformed ones — this was the actual
   mechanism behind the whole "Finding 5" `.type_ann` corruption saga
   documented earlier in this file. Fixed via `is None` + `_as_str()`
   cast instead of `isinstance`.
2. **Hardcoded `_SELFHOST_DIR` path-identity comparisons.** New
   `gimple_codegen._is_selfhost_source_dir()` helper (later relocated,
   see #6) replacing `_cur_abs == _SELFHOST_DIR` (or `.startswith`)
   checks in `gimple_module_gen.py` with a path-independent "does
   `mojo_compiler.py` sit next to this file" signal (mirroring
   `_run_pipeline`'s own `_selfhost_register_gimplegen` gate). Found via
   a REAL downstream project: `/Users/mrs/net/gcc/gcc/fire`, a GCC
   frontend vendoring a byte-identical copy of this compiler at a
   different filesystem path, failed with 9944 gcc errors (`implicit
   declaration of function 'GimpleGen__new_val'` etc. — `gen` params
   boxed to generic `int64_t` instead of `GimpleGen *`) because
   `_SELFHOST_DIR` is hardcoded to wherever `gimple_codegen.py` was
   loaded from, silently disabling self-hosting-only typing for any
   OTHER, otherwise-identical checkout.
3. **Qualifier early-override bug.** `_func_qualifier`/
   `_struct_method_qualifier` (`gimple_gen_funcs.py`) had an early
   `if self-hosting file: return ''` short-circuit that unconditionally
   bare-ified EVERY reference made from a self-hosting-flagged file —
   including genuine references to a DIFFERENT, non-self-hosting
   submodule (fire's own `jit/arm64.py`, one directory below its
   sibling `mojo_compiler.py`). Removed; a no-op for genuine self-
   hosting-internal references (the existing tier 1-3 priority
   resolution already finds nothing for those, falling through to the
   same trailing `return ''`).
4. **GimpleGen-specific qualifier exemption.** Removing #3 broke
   `make check-selfhost` (undefined symbols `_GimpleGen__overload_
   suffix`/`_GimpleGen_overload_suffix_for`): GimpleGen has one real
   home file (`gimple_codegen.py`, correctly resolved via
   `_local_struct_names` there) but is ALSO synthetically registered
   for every OTHER `gimple_*.py` file's compile — those files have no
   import-registry entry for it and fell through to bare, a mismatch
   against the qualified definition. Added back a narrow, name-based
   exemption (`if struct_name == 'GimpleGen': return ''`) mirroring the
   pre-existing `Span` exemption right above it.
5. **Qualified-call convention bug.** `gimple_codegen._is_selfhost_
   source_dir(...)` (a qualified `module.function()` CALL, as opposed
   to a plain attribute read like `gimple_codegen._SELFHOST_DIR`) hit a
   self-hosted-only "stubbed" no-op fallback — confirmed via the
   generated `.ci` showing `/* int64_t._is_selfhost_source_dir()
   stubbed */`, the receiver erased to ambiguous `int64_t`. This
   codebase's established, working convention for cross-file function
   calls is always `from module import name` + bare call; fixed
   accordingly (temporarily — see #6).
6. **Broken cross-module `_parsed_import` resolution for
   `gimple_codegen` specifically.** Even the bare-import fix (#5) hit
   ANOTHER self-hosted-only stub ("unavailable in compiled mode
   (imported from an unresolved external/relative module)"). Root-
   caused via a debug diagnostic: `_local_sibling_module_exports`'s
   `gen._parsed_import('gimple_codegen')` itself returns a falsy path
   self-hosted (confirmed: `ENTER module=gimple_codegen path=0`), even
   though the shim resolves the exact same import fine. Every OTHER
   name gimple_module_gen.py imports from gimple_codegen.py on the same
   import line survives because it resolves via one of two unrelated
   mechanisms that never touch this broken path (a struct/class type,
   or a `gen`/`self`-first-param "extracted helper" already covered by
   the separate, independently-working `_selfhost_extracted_fn_index`
   mechanism) — `_is_selfhost_source_dir` was the only plain utility
   function actually depending on it. Rather than chase the deeper
   `_parsed_import` bug, relocated the function directly into
   `gimple_module_gen.py` (its only remaining caller), sidestepping the
   cross-module resolution path entirely.
7. **`DispatchSolver` field-corruption special-case.** The last
   remaining wrong field in GimpleGen's self-hosted struct (down from
   ~19 originally, after fix #1): `self._dispatch_solver: DispatchSolver
   | None = None` is the ONLY GimpleGen field annotated with a real
   user-defined struct name in an `X | None` shape (every other such
   field uses a builtin type resolved via a hardcoded lookup table).
   Confirmed via diagnostic that `.type_ann` reads back as genuinely
   corrupted (neither str nor None) specifically for this one
   assignment — an old code comment had already flagged this exact
   field by name. Architecturally different from #1 (the VALUE itself
   is wrong here, not just misclassified by isinstance) — fixed via a
   narrow, name-based hardcode (`if member == '_dispatch_solver':
   ctype = 'DispatchSolver *'`), the same shape of exception as the
   `Span`/`GimpleGen` qualifier special-cases.

### The 8th blocker (not fixed — separate, already-tracked, deferred)

After all seven fixes, the first differing byte moved from ~19260
(GimpleGen's struct position) to 20846 — a DIFFERENT struct,
`LayoutSolver` (`gimple_solvers.py`), missing two fields entirely
(`HEAP`, `STACK` — class-level string constants, `self.HEAP`/
`self.STACK` read inside a method). Root-caused to `gimple_module_gen.
py`'s `_scan_stmt_member_candidates` (~line 3316), the GENERIC pass
that discovers a struct's fields by scanning for `self.X` reads across
ALL structs (not just GimpleGen) — it calls `gimple_exprtypes._walk_
ast` directly, the SAME shared utility already documented in this file
(session 3, Bug C item 5) as having a confirmed, still-unfixed
self-hosted bug (`isinstance(node, str/int/float/bool)` misclassifies
real AST dataclass instances, so the walker barely recurses).

Unlike the seven fixes above, this is **not** a quick, narrow patch:
every other `_walk_ast`-dependent bug fixed so far (in GimpleGen's own
scanners) was worked around with a DEDICATED, narrow, statement-only
walker because the shape needed was simple ("find `self.X = <literal>`
assignment TARGETS"). `_scan_stmt_member_candidates` needs to find
EVERY `MemberExpr` READ anywhere in arbitrarily-nested EXPRESSIONS
across a whole method body — a shape general enough that writing a
correct dedicated walker for it would mean essentially re-implementing
`_walk_ast` itself correctly, which is exactly what session 3 already
found exposes a DIFFERENT, catastrophic O(N²) whole-program rescan cost
(15GB+ RSS growth, SIGSEGV) — see `bugs/hard/PERF_nested_module_
compile_walk_ast_quadratic_rescan.md` for that issue's own multi-phase,
multi-week history. Fixing `_walk_ast` properly requires that
performance issue to be solved first.

**This was not left as a theoretical risk — directly attempted and
tested this session.** Reordered `_walk_ast_into`'s check
(`gimple_exprtypes.py`) so `dataclasses.is_dataclass(node)` runs FIRST,
trusting it exclusively (matching session 3's own prior finding that
this reordering fixes the misclassification). Rebuilt `mojoc` and ran
`MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py --dump-full` under careful
RSS monitoring (sampling every 2s) — RSS climbed 5GB → 7GB → 11GB →
14GB+ within about 15 seconds on this SINGLE-FILE compile, before being
killed. This reproduces the exact catastrophic blowup the PERF doc
describes, confirming that the field-name caching optimization already
present in the code (`_WALK_FIELD_NAMES_CACHE`, computed once per class
rather than per node — itself a real, already-landed perf fix,
"Phase 5" per that function's own docstring) does NOT by itself resolve
the underlying O(N²) whole-program rescan cost. The change was cleanly
reverted (`git checkout -- gimple_exprtypes.py`, confirmed zero diff)
and `mojoc` rebuilt from the last committed, known-good state
(`972850f`) before continuing.

**A second, independently-scoped attempt was ALSO tried and ALSO
failed the same way.** Theorizing that the blowup came specifically
from fixing the SHARED `_walk_ast` (multiplying the extra recursion
cost across its dozens of call sites simultaneously), tried a
narrower fix instead: a new, separate sibling function
(`_walk_ast_correct`/`_walk_ast_into_correct` in `gimple_exprtypes.py`,
same corrected check order, left `_walk_ast` itself completely
untouched) used ONLY by `_scan_stmt_member_candidates` — which already
caches its own result by `id(stmt)` in a dict shared across every
nested temp_gen in the whole-program compile
(`self._field_scan_member_cache`), so each distinct statement tree
would be walked with the corrected-but-costlier logic AT MOST ONCE
program-wide, not repeatedly. Built and RSS-monitored the identical
way: `MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py --dump-full` — RSS
climbed 5.6GB → 10GB → 11GB → 15GB → 16GB+ within seconds, the exact
same catastrophic pattern, on the exact same single-file test. Killed
immediately, cleanly reverted (`git checkout -- gimple_exprtypes.py
gimple_module_gen.py`, confirmed zero diff via `git status --short`),
`mojoc` rebuilt and stability-verified again.

That a SECOND, differently-scoped implementation (dedicated walker,
single cached caller, only one file even touched by the fix) hits the
identical wall as the first (global reorder of the widely-shared
function) is strong evidence this isn't "many callers each paying a
moderate extra cost" — it's that correctly recursing this self-hosted
AST representation via `is_dataclass`-first ordering, in this codebase,
at all, triggers something closer to true exponential blowup even for
ONE statement tree in ONE file. The most likely mechanism (consistent
with `_walk_ast_into`'s own docstring, which explicitly flags "no
id()-based visited set — id() is unreliable in the compiled runtime"):
the self-hosted AST has genuinely shared/aliased sub-structures
reachable via more than one path, and a naive recursive walk with no
cycle/revisit detection re-walks each shared subtree once per distinct
path to it — which is exactly the shape of bug `bugs/hard/PERF_nested_
module_compile_walk_ast_quadratic_rescan.md` already tracks, just
newly reproduced with concrete, fresh RSS numbers this session rather
than only cited from the earlier session's history.

**UPDATE — the "two attempts both blow up" reading above was itself
partly a false alarm, corrected by a third and fourth attempt.**
A controlled comparison run AFTER the two reverts above — the
UNMODIFIED, already-committed baseline (zero code changes), same exact
command (`MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py --dump-full`),
watched patiently instead of killed early — showed the IDENTICAL
climbing-RSS pattern (peaking ~38-40GB) and then completed NORMALLY
with exit 0 in about a minute. That climb is pre-existing, unrelated
behavior of this specific whole-transitive-closure self-hosted
compile (this compiler's own largest files) — not something either
`_walk_ast` fix attempt caused. Both attempts above were killed
partway through their own natural climb on a mistaken assumption of
an unbounded runaway.

Re-tried a third time with an added hard total-node-count safety cap
(on top of the existing depth cap) as an extra precaution — this also
showed the same climbing pattern (since the cap wasn't actually the
relevant variable) and was, in hindsight, ALSO killed prematurely.

Reapplied the SIMPLEST form of the fix a fourth time (the direct
`_walk_ast_into` reorder, no dedicated-walker workaround needed) and
this time let it run to genuine completion rather than killing on a
high-but-still-climbing RSS reading. Result: RSS climbed past the
baseline's own peak — into the 57-62GB range — and the process then
died silently (vanished from `ps`, zero-byte log, no error text),
consistent with a real OS OOM kill this time, not a false alarm.

**This gives a materially more precise diagnosis than "O(N²) blowup,
suspected cycle."** The fix is not wrong in the sense of an infinite
loop or a true graph cycle — `_walk_ast_into`'s depth cap (900) and,
separately, the node-count cap tried in the third attempt, both did
exactly what they were supposed to; the walker terminates. The real
issue: correctly completing this traversal (which the original bug
accidentally prevented, by barely recursing and therefore barely
allocating) requires substantially more REAL, legitimate memory than
the already-heavy broken baseline — and this self-hosted runtime
appears to never free intermediate allocations at all (consistent
with an arena/bump-allocator memory model, common in from-scratch C
runtimes for simplicity and allocation speed, at the cost of retaining
everything until process exit). The baseline's ~38-40GB peak is
already large for compiling one file's transitive closure; a genuinely
complete traversal pushes far enough past it to exceed what was
available on this machine.

Confirmed identical in both the broken and fixed versions (so this is
not something introduced by the fix): worth tracking as its own,
separate, real inefficiency in the self-hosted runtime's memory
management — likely the actual reason this whole class of self-hosted
compile is so memory-hungry in the first place, and a genuine
prerequisite for `_walk_ast`'s bug to be fixable in practice (not just
in principle) without requiring a machine with substantially more RAM
than this one.

**Conclusion**: check-noshim-dumpfull's zero-diff goal was not reached
this session. The `_walk_ast` fix itself was reverted a fourth time
(clean revert confirmed via `git status --short`, mojoc rebuilt and
stability-verified from the last committed state, `c9a0e79`) — not
because it is incorrect, but because completing it correctly currently
requires more real memory than this machine has for this specific
compile, given the self-hosted runtime's apparent never-frees
allocator design. A future session has two viable paths, in order of
likely leverage: (1) address the self-hosted runtime's memory
management (freeing/reusing intermediate allocations, or at least this
specific walker's transient node lists) so the correct traversal fits
in available memory, then reapply this exact, already-written fix; or
(2) run the fix on a machine with substantially more RAM as a stopgap
to unblock check-noshim-dumpfull specifically, while (1) is addressed
separately. No further attempt at THIS specific fix is worth making on
this machine without one of those two prerequisites.

### CORRECTION (session 5, 2026-09-14 later): the "OOM" diagnosis above was wrong — real cause is a NULL-pointer SIGSEGV

The "died silently, consistent with OOM" conclusion above was itself a
misdiagnosis, caused by an investigation artifact: the process had been
launched with explicit shell backgrounding (`(...&)`), which obscured
its real exit code from the calling shell — a silent death with an
empty log looked identical to an OOM kill (SIGKILL/137) from the
outside. Re-running the exact same reproduction command WITHOUT the
extra `&` (still inside the harness's own `run_in_background`, but as
a plain synchronous foreground command) captured the true exit status:
**139 = 128+11 = SIGSEGV**, not SIGKILL. `ulimit -a` showed all
memory-related limits as "unlimited," and no core file was produced in
`/cores/`.

Following `HOW-TO-DEBUG.html`'s methodology, reproduced under lldb with
ASLR disabled:

```
lldb -o "settings set target.disable-aslr true" \
     -o "settings set target.env-vars MOJO_NO_SHIM=1" \
     -o "run gimple_gen_loops.py --dump-full" \
     -o "bt" -o "quit" ./mojoc
```

This gave a clean, reproducible backtrace:

```
* thread #1, stop reason = EXC_BAD_ACCESS (code=1, address=0x0)
  frame #0: libsystem_platform.dylib`_platform_strcmp$VARIANT$Base + 148
  frame #1: mojoc`_dict_lookup(d=<unavailable>, key=0x0) at mojo_runtime.c:2570:13
  frame #2: mojoc`mojo_dict_get_str(d=<unavailable>, key=0x0) at mojo_runtime.c:2592:21
  frame #3: mojoc`gimple_module_gen__gmi_collect_self_assigns_2f4586(...)
      at gimple_module_gen.py:1117:10
  frame #4: mojoc`gimple_module_gen_gen_module_impl_7e9a9f(...) at gimple_module_gen.py:3259:3
  [... nested GimpleGen.gen_module -> _compile_imported_module recursion
   across gimple_solvers, gimple_gen_methods, gimple_gen_exprs,
   gimple_gen_calls, gimple_cpp_core, gimple_cpp_async, gimple_codegen ...]
```

A genuine NULL-pointer dereference, not memory exhaustion — full log
saved at session time in `/tmp/lldb_crash.log` (not committed, local
artifact only).

**Root cause**: `_gmi_collect_self_assigns` (`gimple_module_gen.py`,
function starts at line 1108) computes `_existing_fn_ft =
found.get(fn)` at line 1117 BEFORE checking whether `fn` is `None`.
`fn = _gmi_self_member(node.target)` legitimately returns `None` for
any `AssignStmt` whose target is not a `self.X` attribute (e.g. a
plain local variable assignment) — a completely normal, frequent case.
In CPython, `dict.get(None)` on a dict with no `None` key is a safe
no-op returning `None`. Self-hosted, `mojo_dict_get_str`/`_dict_lookup`
erase a `None` key to a NULL `char *` with no NULL guard, and
`_dict_lookup` unconditionally calls `strcmp(NULL, existing_key)` —
segfaulting the instant it's ever called with a `None` key.

This bug was invisible until now because the `_walk_ast` walker's own
bug (isinstance-before-is_dataclass misclassification, documented
above) meant `_gmi_collect_self_assigns` almost never actually reached
a real `AssignStmt` node at all — the `_walk_ast` reorder fix (still
correct, still not landed — see below) is what let this function
finally see real, non-self assignment targets at scale for the first
time, surfacing this second, independent, previously-dormant bug.

**Fix identified and syntax-tested (not committed as of this
correction)**:

```python
for node in _walk_ast(body):
    if isinstance(node, AssignStmt):
        fn = _gmi_self_member(node.target)
        if fn is None:
            continue
        _existing_fn_ft = found.get(fn)
        if (fn not in found
                or (_existing_fn_ft in ('int', 'int64_t')
                    and _existing_fn_ft is not None)):
            v = node.value
            ...
```

**Status after this correction**: both the `_walk_ast_into` reorder
(`gimple_exprtypes.py`) and this `None`-guard fix (`gimple_module_gen.py`)
were applied TOGETHER and run once: `MOJO_NO_SHIM=1 ./mojoc
gimple_gen_loops.py --dump-full` ran **6 minutes 44 seconds** without
crashing or completing — far longer than any single-fix attempt above
(which either crashed within ~90s-2min, or, for the one successful
unmodified-baseline control run, completed in ~1 minute). This was
killed rather than let run further, and both changes were reverted
(`git checkout -- gimple_exprtypes.py gimple_module_gen.py`, confirmed
clean via `git status --short`), `mojoc` rebuilt from the clean
committed state (`f8ddab4`). Whether that 6:44 run represents a
genuinely correct-but-slow traversal that was about to finish, a
separate still-undiagnosed stall, or the earlier heavy-memory-usage
concern in a different guise, is **not yet known** — this is the
concrete next step for a future session, not "run out of RAM" as
previously concluded. The severe RSS growth documented above may still
be real and separately worth investigating (the "never frees"
arena-allocator observation appears independently confirmed), but it
is no longer believed to be what killed the fourth attempt — that was
SIGSEGV, diagnosed above, in a completely different function
(`_gmi_collect_self_assigns`) than the `_walk_ast` reorder itself.

**Recommended next steps**: (1) re-apply both fixes together again,
this time either running under lldb from the start (so a second crash,
if any, gets an immediate backtrace instead of another silent kill) or
adding progress instrumentation/timeouts to distinguish "still working"
from "stuck"; (2) if it does complete, verify `LayoutSolver`'s
`HEAP`/`STACK` fields are now present and re-run the full
`test_noshim_dumpfull.py` for the true final diff; (3) update this
doc's earlier "OOM" framing (now superseded) once resolved either way.

### FOLLOW-UP (session 5, same day): re-tried properly under lldb — confirms genuine unbounded memory growth, not a hang or a second crash

Re-applied both fixes (the `_walk_ast_into` reorder and the
`_gmi_collect_self_assigns` `fn is None` guard) and reran under lldb
from process launch (`disable-aslr`, `MOJO_NO_SHIM=1`, `run ... bt
quit`), this time to get an immediate backtrace if it crashed again
instead of inferring from exit code. One confound found and fixed
along the way: an earlier, separately-killed `process launch` attempt
had left an ORPHANED duplicate `mojoc` process running unsupervised
(`pkill -f "lldb.*mojoc"` doesn't match a bare `mojoc` command line) —
two ~20-24GB compiles were competing for memory simultaneously for
several minutes, which likely explains the previous attempt's
anomalous 6:44 runtime. Killed the orphan; only the lldb-supervised
process continued.

With only one process running, `mojoc` ran cleanly (no crash, no
deadlock — CPU-bound and progressing) for over 28 minutes, climbing
from the baseline's usual ~5GB start past 58GB RSS, and by the ~30
minute mark `top` showed its total memory footprint at **189GB (147GB
compressed)**, with the system down to under 16MB of free physical
pages. This is unsustainable on a 128GB machine and risks the whole
system, not just this process — killed deliberately (`kill -9`) rather
than let it continue. Memory recovered normally afterward, confirming
this was the `mojoc` process's own footprint, not a separate leak.

**This is a materially different, more precise finding than either
prior conclusion.** It is not the SIGSEGV from the `_gmi_collect_
self_assigns` bug (both fixes were applied; no crash occurred, the
process was killed by hand while still healthy/progressing). It is
also not quite the earlier "died silently ~57-62GB, presumed OOM"
reading either — this run was allowed to continue well past that
point, under direct observation, and kept growing past 189GB total
footprint without dying on its own; it was killed pre-emptively. Both
fixes are very likely functionally CORRECT (no crash, no infinite
loop/hang — genuine forward progress the whole time) — the blocker is
squarely the self-hosted runtime's memory model: completing this one
file's whole-transitive-closure compile with a truly correct AST walk
requires memory in the hundreds-of-GB range, because (as noted above)
nothing is ever freed. This is no longer a "maybe," it's measured.

**Revised conclusion**: fixing `check-noshim-dumpfull`'s remaining gap
via this `_walk_ast` correction is blocked on the self-hosted runtime's
allocator, not on any remaining logic bug in these two fixes. Both
fixes were reverted again (`git checkout -- gimple_exprtypes.py
gimple_module_gen.py`) and `mojoc` rebuilt clean from the last
committed state for safety — running either fix on this machine again
without first addressing the runtime's memory management (freeing/
reusing intermediate allocations, or at minimum giving `_walk_ast`'s
output list a bounded/streaming consumer instead of retaining the full
flattened node list for a whole nested-module compile) is expected to
reproduce the same multi-hundred-GB growth, not a new bug. The actual
fix content (both diffs) is fully preserved in this doc and in
`gimple_module_gen.py:1108`/`gimple_exprtypes.py:34`'s pre-fix code
for a future session to reapply once the memory-model prerequisite is
addressed.

### RETRY (session 6, 2026-09-15): memory-model prerequisite partially landed — single large file now succeeds, whole-program self-compile still blows past safe limits

A separate agent landed a real ownership model this session
(`aa67b68`/`9b3216c` — a per-frame cleanup registry so `mojo_raise()`'s
longjmp actually frees owned locals instead of always leaking them, plus
Phase 0-3 groundwork for freeing dict/list/set values generally). This
is real forward progress on exactly the "memory-model prerequisite"
named above, so both reverted fixes (`_walk_ast_into` is_dataclass-first
reorder in `gimple_exprtypes.py`, the `_gmi_collect_self_assigns`
`fn is None` guard in `gimple_module_gen.py`) were reapplied verbatim
and retested against the now-ownership-managed runtime.

**Single-file repro (`MOJO_NO_SHIM=1 ./mojoc gimple_gen_loops.py
--dump-full`), the doc's own established repro case: now SUCCEEDS.**
RSS-monitored every 2-10s for the full run: climbed to a peak of ~93GB
around the 3-minute mark, then — unlike every prior attempt — actually
DECLINED, oscillating down through ~60GB, ~50GB, and settling around
~54GB before completing normally (exit 0, `✓ Generated
gimple_gen_loops.ci (transitive closure)`, 38,466,963 bytes) after
~35 minutes wall time. The oscillating-then-recovering pattern (vs. the
old strictly-monotonic climb to 189GB) is itself evidence real frees are
now happening, not just a smaller absolute number.

**Whole-program self-compile (the actual `check-noshim-dumpfull` gate,
`MOJO_NO_SHIM=1 ./mojoc fire.py --dump-full`): still unsafe.** Same
monitoring approach, same fixes. RSS climbed to ~97-102GB in the first
~2 minutes, then oscillated in a 74-83GB band for roughly 15 minutes
(again showing real frees, not monotonic growth) — but then, in the gap
between two 10s-interval samples (last observed reading: 52GB), it spiked
far past a 112GB safety cap that had correctly bounded every earlier
sample. The user observed it directly at **230GB** and killed it by hand
before it endangered the system; no kernel/jetsam log entry was found
for the kill (consistent with a manual `kill -9`, not an OS-level OOM
reaper), and system memory fully recovered afterward, confirming it was
this process's own footprint. **Both fixes reverted again**
(`git checkout -- gimple_exprtypes.py gimple_module_gen.py`, confirmed
clean via `git status --short`) and `mojoc` rebuilt from the clean
committed state — leaving either fix applied would make a ROUTINE `make
check-noshim-dumpfull` run (which exercises exactly this whole-program
path) capable of reproducing the same multi-hundred-GB spike, an
unacceptable hazard for a gate step that's supposed to be safe to run
routinely.

**Sharper conclusion than before**: the memory-model prerequisite is
real progress but only PARTIAL — sufficient to bound one large file's
transitive-closure compile (~93GB peak, recovers), but NOT sufficient
for the full `fire.py` self-compile's much larger transitive closure
(peaked at least 230GB, still climbing when killed — the true ceiling is
unknown). The gap is plausibly proportional to program size (more
distinct AST subtrees × the ownership model's current coverage not yet
reaching every allocation site Phase 0-3 was scoped to, per
`doc/OWNERSHIP_MODEL.md`'s own "Remaining work" if any). A future
session should either (1) extend ownership/free coverage further before
retrying the full self-compile, ideally under a hard resource cap this
time (`ulimit -v` or ideally a cgroup/job-object equivalent, NOT just
polled monitoring — a fast spike can outrun a 10s poll interval, as
happened this session) so a runaway is killed automatically rather than
relying on a human or a lucky sample; or (2) profile which specific
allocation sites dominate the full self-compile's footprint (something
this session did not do — only RSS was observed, not attributed to any
particular allocator call site) to find the next-highest-leverage free
site rather than assuming uniform coverage is needed everywhere.

## Continuation 7 — aside/bside sweep as the primary harness; the
`_mojo_dispatch_getattr` reflection gap found as the root of every
`mojo_list_len(0x1)` SIGSEGV

Ran the documented per-file sweep (`make -j20 aside bside && make
compare-a-b`, 779 files, ~50s) as the fast feedback loop instead of
root-justifying the five huge bootstrap files one at a time. Baseline was
`CI-DIFF=677, SELFHOST-CRASHED=26, AST/TOK-DIFF=14`.

**Landed (verified, gate-green):**

1. **`_ensure_bool_cond` NULL-`ctype` guard** (`gimple_gen_stmts.py`). A
   condition whose `lower_expr` returned an unknown type left `ctype` as
   the real Python `None`; the string-keyed `ctype in
   gen._CONTAINER_LEN_FN` then SIGSEGV'd in `strcmp` via
   `mojo_dict_contains` with a NULL key. The function already documented
   this exact crash and guarded ONE site (`_real_ctype is not None`) but
   not the later bare `ctype in gen._CONTAINER_LEN_FN`. Normalizing
   `None -> ''` at entry fixes it. Effect: `std/math/math` and
   `std/python/python_object` now COMPILE (were CRASH) — i.e. 2 crashes
   became 2 CI-DIFFs, net `CI-DIFF 677->679, CRASHED 26->24`.

2. **`tools/audit_selfhost_struct_fields.py`** (new). Diffs the real
   `@dataclass` field lists in `fire_compiler.py` against the hardcoded
   `self.struct_field_types['<Node>']` map in `gimple_module_gen.py`, the
   map that drives the emitted self-host C struct, its reflection
   (`_mojo_getattr_/setattr_/fieldnames_<Node>`) and its
   `_mojo_repr_<Node>`. It reports four SEMANTIC gaps and the systematic
   `line`/`col` omission:
   - `CallExpr.kwargs`  (the serious one — see below)
   - `FromImportStmt.name_alias_strs`
   - `StringLiteral.is_bytes`  (adding this regressed .ast reprs before)
   - `SubscriptExpr.attrs`
   (`line`/`col` missing on ~51 nodes is deliberate — error-messages only.)

3. **De-trapped four list comprehensions + `max(key=)` in
   `_resolve_overload`** (`gimple_gen_calls.py`) into explicit loops
   (`kwarg_names`, `survivors`, `arg_types`, `ties`, and the
   `max(survivors, key=_score)` scan). Same self-host comprehension
   family the codebase already documents at `''.join(<genexpr>)`. Measured
   neutral on the sweep (679/24 before and after) but strictly the
   conventional form for this codebase.

**Root-caused, but deliberately NOT applied — `CallExpr.kwargs`:**

`struct_field_types['CallExpr']` lists only `func`/`args`. Consequences
on the compiled path:
  * the parser's `CallExpr(..., kwargs=kwargs_list, ...)` silently DROPS
    every keyword argument, and
  * a compiled `node.kwargs` read falls through
    `_mojo_getattr_CallExpr` to `mojo_obj_getattr`, whose missing-attribute
    sentinel is **1** — so `node.kwargs == 1`.
  * `_lower_struct_method_call`'s `... or node.kwargs`, then
    `_resolve_overload`'s `kwargs = kwargs or []`, then
    `mojo_list_len(1)` → **SIGSEGV** (`mojo_list_len` derefs `1->len` =
    address 0x9). This is the single site behind ALL 26 (now 24)
    `SELFHOST-CRASHED` files (dict/list/set/math/pathlib/…), confirmed by
    lldb (`frame #1 …_lower_struct_method_call … mojo_list_len(l=0x1)`).

Adding `'kwargs': 'MojoList *'` DOES fix `node.kwargs` (the native `.ast`
then renders `kwargs=[('b', IntLiteral(...))]` correctly), and the
companion parser fix (`kwargs_list = [(k,v) for k,v in keywords.items()]`
comprehension → explicit append loop; the comprehension erased to 1 too)
is also needed. BUT applying both turned stage2 dumps of
`fire_compiler.py` and `myinterpreter.py` into hard FAILs — because with
kwargs now a real list, MORE call sites take the `... or node.kwargs`
branch and reach a SECOND, still-unfixed `mojo_list_len(1)`. So the
struct field was reverted until that second site is fixed; the audit gap
stays recorded here.

**The second `mojo_list_len(1)` (still open):** deeper tracing (file-based
`open/write/close` traces, because `print` to a redirected stdout is
block-buffered and LOST on SIGSEGV — a real methodology note) placed it
inside `_resolve_overload` right after `survivors` is built, and then in
the CALLER's `if`. Both `_method_candidates` and the built `survivors`
read back as a valid 1-element list at the trace points, yet
`mojo_list_len` is reached with arg 1. The smoking gun is mojoc's own
generated `_mojo_dispatch_getattr`:

    static int64_t _mojo_dispatch_getattr (void *obj, char *attr) {
      int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);
      return mojo_obj_getattr(obj, attr);      /* NO per-type cases! */
    }

i.e. the per-type `if (_tag == <CallExpr tag>) return
_mojo_getattr_CallExpr(...)` dispatch cases are MISSING in the build, so
EVERY reflective attribute read (`node.kwargs`, and any other
`obj.attr` on a boxed AST node) returns the sentinel 1 regardless of the
struct field. The python-side dump of `gimple_gen_methods.py` DOES emit
those cases, so this is a self-host-only reflection-injection gap
(do_imports / sibling-recognition dependent). Fixing THAT (make the
reflection dispatch always emit the per-type cases for the AST structs
whose fields are read reflectively) is the next real step; re-applying
the `CallExpr.kwargs` field after it should clear most of the 24 crashes
AND unblock fire_compiler/myinterpreter stage2.

**Gate after continuation 7 (all green):** `check-gimple` 308/0,
`check-modcache` 81/0, `check-selfhost` 1/0, `check-linkmode` 3/0,
`check-no-new-casts` baseline unchanged (28). `fire_compiler.py`,
`myinterpreter.py`, `module_loader.py` all `--dump` clean again.

### Continuation 7 addendum — the reflection gap is far wider than CallExpr

`nm mojoc | grep -oE '_mojo_getattr_[A-Za-z]+$' | sed s/_mojo_getattr_//`
yields only **26** per-type reflection helpers, while
`struct_field_types` has **81** keys. 64 — including CallExpr, BinaryOp,
AssignStmt, ExprStmt, ForStmt, IfStmt, IdentExpr, MemberExpr, IntLiteral,
ListExpr, FunctionDef, FromImportStmt — have NO `_mojo_getattr_<name>`,
so `_mojo_dispatch_getattr` has no case for them and EVERY reflective
attribute read on one of those nodes hits `mojo_obj_getattr` (whose miss
sentinel/raise is the `node.kwargs == 1` source). The helpers that DO
exist are an arbitrary-looking subset (GimpleGen, Resolver, RewriteRule,
SetExpr, SliceExpr, StringLiteral, StructDef, SubscriptExpr, TernaryExpr,
Token, TraitDef, TrieNode, TryStmt, TupleExpr, TypePromotionSolver,
UnaryOp, Var, VarDecl, WalrusExpr, WhileStmt, …).

`reflect_emitted` = `struct_field_types` keys ∩ `_emitted_structs`
(∩ `_struct_allocs_needed`), so `_emitted_structs` must hold only ~26
names when `_emit_reflection_dispatch(self, parts)` runs (gimple_module_gen.py:8724).
The struct-typedef emit loop is at 7529 (well before), and it does
`self._emitted_structs.add(struct_name)` for every struct it emits — so
either that loop is only emitting the subset, or the dispatch is emitted
from a module where `_emitted_structs` hasn't accumulated the rest
(per-module `gen_module_impl`; `temp_gen._emitted_structs` is shared at
gimple_gen_resolve.py:523 but `discard`ed at :877). Both the
`sorted(self.struct_field_types)` key source and a union-relaxation of
the `_es_str` filter were tried and measured NEUTRAL on the sweep
(679/24/14 unchanged) — so the next step is to instrument/verify
`_emitted_structs`'s contents at 8724 for the self-hosted build and make
the reflection-emit pass cover all 81 (or at least all AST nodes), then
re-apply `CallExpr.kwargs`.

**Next concrete step:** in `gen_module_impl`, print/record
`len(self._emitted_structs)` and whether `'CallExpr' in self._emitted_structs`
immediately before the 8724 `_emit_reflection_dispatch` call on the
self-hosted build, and trace the 7529 loop's `emitted` set growth. If the
loop emits <81, fix its dependency ordering / `max_iterations`; if the
dispatch runs per-module before accumulation, hoist it to the end of the
root module once `_emitted_structs` is complete.

**Addendum 2 — instrumented `_emitted_structs` at the dispatch point.**
A file-trace at the `_emit_reflection_dispatch(self, parts)` call
(gimple_module_gen.py:8706) across all `gen_module_impl` calls shows the
per-module `_emitted_structs` sizes cluster at 55-61 with `CallExpr`
ABSENT (`ce=0`), except a couple of modules at n=267/n=83 with `ce=1`.
`nm mojoc` still has no `_mojo_getattr_CallExpr`, so the dispatch text
that actually survives into the build comes from a module where
`CallExpr` is not in `struct_field_types`/`_emitted_structs` — the
per-module `gen_module_impl` emits its OWN `_mojo_dispatch_getattr`, and
the relevant one has no CallExpr.

Relaxing the `reflect_emitted` filter to "every `struct_field_types` key
with non-empty fields" (dropping the `_es_str`/`_san_str` intersection)
raised the emitted helper count 26 -> 46 but STILL excluded CallExpr
(so CallExpr is genuinely not a `struct_field_types` key in the
dispatch-owning module) and was NEUTRAL on the sweep (679/24/14). Both
probes were reverted. The remaining work is to find which module owns
the surviving `_mojo_dispatch_getattr` and why its `struct_field_types`
lacks the core AST nodes — then that module's `reflect_structs` must
include them (or the dispatch must be emitted once, last, from the root
module after `_emitted_structs` is fully accumulated).

**Addendum 3 — the reflection gap's root: `_is_selfhost_file` gating.**
The entire hardcoded AST-struct block in `gen_module_impl`
(gimple_module_gen.py:2389 `if _is_selfhost_file:`, covering Scope,
Token, ReturnValue, CallExpr, BinaryOp, ExprStmt, FromImportStmt, …), and
hence `struct_field_types` for every AST node, is added ONLY when
`_current_filename`'s directory is the self-host source dir
(`_is_selfhost_source_dir`). The `struct_field_types` sizes in the
addendum-2 trace (sf=55 low / 82 high) are exactly this split. So a
module compiled without the self-host gate has NO CallExpr key at all —
and if THAT module's `_emit_reflection_dispatch` is the one whose text
survives into the tu, `node.kwargs` is dispatch-less and reads the miss
sentinel 1. Confirming which module owns the surviving
`_mojo_dispatch_getattr` (and whether the root fire.py build's dispatch is
being overwritten by a later non-selfhost module's) is the next step;
the fix is likely to (a) emit the dispatch exactly once from the root
after all modules, and (b) extend the AST-struct field map (or the
`_is_selfhost_file` gate) so the dispatch-owning module has every AST
node that any compiled code reads reflectively.

## Continuation 8 — the `node.kwargs`/reflection crash: what landed and
where the remaining `mojo_list_len(0x1)` is

Landed and gate-green:

1. **Family A** (`_ensure_bool_cond` NULL-`ctype` guard) — 2 crash files
   (`std/math/math`, `std/python/python_object`) now compile. Net
   `CI-DIFF 677->679, CRASHED 26->24`.
2. **`_lower_struct_method_call` reads `node.args` via a same-module
   typed view** (`_gmm_callexpr_node`) instead of `_mojo_dispatch_getattr`
   (whose per-type table lacks a CallExpr case — see continuation 7). This
   is a real fix: the reflective `node.args` read returned the miss
   sentinel 1. (An imported `_as_callexpr_node` from fire_compiler is
   emitted as an `int64_t` weak stub — the `_gmm_as_str` lesson — so the
   helper must be SAME-MODULE, annotated `-> CallExpr`.)
3. **De-trapped** the `[gen.lower_expr(a) for a in <args>]` comprehension,
   the `([_recv_pair] + arg_pairs)` list-concat, the `_resolve_overload`
   `survivors`/`kwarg_names`/`arg_types`/`ties` comprehensions and
   `max(key=)`, and the parser's `CallExpr.kwargs` comprehension into
   explicit loops.
4. `tools/audit_selfhost_struct_fields.py`; `_gmm_callexpr_node`.

**Where the remaining crash is (still open).** The `CallExpr.kwargs`
struct field is deliberately NOT re-added: with it (plus a direct
`_cnode.kwargs` read) `dict.mojo`/`list`/`set`'s `node.kwargs == 1` crash
is fixed and the crash MOVES to the tail of `_lower_struct_method_call`
(around the `ret_type`/`_method_dflts`/`_call_expr`/return region — file
traces reach `U8 pre-return`), and that same further crash then makes
stage2 dumps of fire_compiler.py/myinterpreter.py hard-FAIL. Grepping the
whole generated body of `_lower_struct_method_call_3e6420` (78987-byte
.tu range) finds NO textual `mojo_list_len`, yet lldb reports
`mojo_list_len(l=0x1)` with frame #1 = that function at
gimple_gen_methods.py:4329 — so the bad `mojo_list_len` is in an INLINED
callee reached only on the kwargs path (`_resolve_overload` is ruled out;
suspects left: the inlined tuple-return packing, `_call_expr`/`_emit_call`
argument iteration, or `gen.func_return_types.get(k, <default>)`'s absent
check). Next step is a breakpoint on `mojo_list_len` with `l==1` plus
`bt`/`image lookup` at the exact PC (or an `-O0 -fno-omit-frame-pointer`
mojoc build) to name the inlined callee.

**Final state (gate-green):** `check-gimple` 308/0, `check-modcache` 81/0,
`check-selfhost` 1/0, `check-linkmode` 3/0, `check-no-new-casts` baseline
unchanged; `fire_compiler.py`/`myinterpreter.py`/`module_loader.py` all
`--dump` clean. Sweep: `CI-DIFF=679, SELFHOST-CRASHED=24, AST/TOK-DIFF=14`.

## Continuation 9 — two more pointer-decimal key-coercion roots fixed;
the remaining crash localizes to the `_method_dflts` chain

Landed and gate-green (no sweep-count change, but both are real
correctness fixes on the compiled path):

1. **`_sms_key` key coercion.** `gen._struct_method_signatures.get(
   _sms_key(struct_name, method))` compiled the dict key as
   `mojo_str_from_int(_sms_key(...))` — because the IMPORTED
   `fire_compiler._sms_key`'s `-> str` return type goes unresolved at a
   module-level call site, the codegen typed its result int64_t and
   `_char_to_cstr` rewrote the key to the POINTER'S DECIMAL ADDRESS. So
   `_struct_method_signatures` never hit `"Struct_method"`, returning the
   miss sentinel. Fixed with a same-module `-> str` wrapper
   `_gmm_sms_key(a, b)` (the `_gmm_as_str` pattern) at all 5 call sites.

2. **`mangled` key coercion.** `mangled = gen._struct_method_csym(...)` had
   the same problem (unresolved `-> str` return): every following
   `dict.get(mangled)` key (`_func_param_defaults`, `func_return_types`,
   `_KNOWN_SIGS`, the `_stub_guard`/`_auto_stubbed` checks) was
   `mojo_str_from_int(<pointer>)`. Fixed with `_gmm_as_str(...)`.

These make overload resolution, parameter-default lookup and the
mangled-name return-type lookup actually work on the compiled path
(previously silently missing).

**Remaining crash (still the `mojo_list_len(0x1)` SIGSEGV).** With the
`CallExpr.kwargs` field re-added + a direct `_cnode.kwargs` read, the
dict/list/set crash moves into `_lower_struct_method_call` and the frame
maps to gimple_gen_methods.py:4345 (the `ret_type` block), whose generated
code is clean — so the bad `mojo_list_len` is the `_method_dflts` chain:
`_method_dflts = (gen._func_param_defaults.get(mangled) or <.get
suffix> or <.get bare> or [])`, then
`{pn: dv for pn, dv in _method_dflts}` emits
`mojo_list_len(_method_dflts)` and `_method_dflts` reads back as 1. The
`.get` results come from `mojo_dict_get_int`, which returns the slot's
int64 val; for `_func_param_defaults[k] = list(_dflts)` that should be a
list pointer, so the suspect is `list(_dflts)`'s self-host lowering at the
registration site (gimple_module_gen.py:2950, `list(_dflts)` over the
GimpleGen signature table's nested-unpack). Fixing that (or replacing the
`or`-chain + dict-comp with explicit length-checked steps) is the next
step; then `CallExpr.kwargs` can be re-added and fire_compiler/myinterpreter
stage2 re-checked.

**Final state (gate-green):** `check-gimple` 308/0, `check-modcache` 81/0,
`check-selfhost` 1/0, `check-linkmode` 3/0, `check-no-new-casts` baseline
unchanged; fire_compiler/myinterpreter/module_loader `--dump` clean.
Sweep: `CI-DIFF=679, SELFHOST-CRASHED=24, AST/TOK-DIFF=14`.

## Continuation 10 — the `mojo_list_len(0x1)` root found: `self._signature_ctypes`
stubs in `gen_module_impl`; plus a check-no-new-casts gotcha

With the `CallExpr.kwargs` field + direct `_cnode.kwargs` read re-applied,
the dict.mojo crash was disassembled (lldb, frame #1
`_lower_struct_method_call`) down to an inlined `_resolve_overload._score`:
`mojo_dict_get_int` returns 1, then `mojo_list_len(1)` on it. The `1` is
`cand['param_ctypes']` — the candidate dict's `param_ctypes` is the garbage
value 1.

Traced to its producer (gimple_module_gen.py:4394, the Pass-2b-bis
struct-method-signature registration):

    _all_ctypes = self._signature_ctypes(m.params, m, s.name)

compiles to

    _t10534 = self;
    _t10540 = _t10534;  /* int64_t._signature_ctypes() stubbed */
    _t10541 = (int64_t)_t10540;
    _all_ctypes = <MojoList *>_t10541;   /* == (list*)self */

i.e. the GimpleGen METHOD call was replaced by the scalar-receiver stub
that just returns the receiver — `_all_ctypes` becomes `self` reinterpreted
as a list, `param_ctypes = _all_ctypes[1:]` inherits the garbage, and the
candidate dict stores it.

Cause: `gen_module_impl(self, stmts)`'s OWN `self` param is boxed to
`int64_t` in the compiled signature (`int64_t gen_module_impl_2f7ad9
(int64_t self, MojoList * stmts)`) — its signature is cached before the
GimpleGen registry pre-pass runs, so `_selfhost_gen_self_param_ctype`
(which requires `gen._selfhost_gimplegen_registered`) can't type it, and
every `self.<method>()` in this function stubs to "return the receiver".

**Fix identified and verified mechanically, but deferred:** calling the
free `_ggf_dup._signature_ctypes(self, m.params, m, s.name)` (whose first
param IS typed `GimpleGen *`) removes the stub
(`_t10537 = _signature_ctypes(self, ...)`, no "# stubbed"). It is NOT
applied because the call's return type resolves `int64_t` here, so the
assignment emits a container-pointer coercion that trips
check-no-new-casts (30 vs baseline 28). Routing the return through a
same-module `-> list` view (or resolving the return type) would avoid the
cast; de-drafted until the `kwargs` path it unblocks is itself enabled.

**check-no-new-casts gotcha (learned the hard way):** that test greps RAW
TEXT for `(MojoList *)`/`(MojoDict *)`/`(MojoSet *)`/`(MojoBytes *)`, so a
new COMMENT containing that pattern counts as a new site. Two explanatory
comments added this session tripped it (28 -> 30); rephrasing them
restored the baseline.

**Final state (gate-green):** check-gimple 308/0, check-modcache 81/0,
check-selfhost 1/0, check-linkmode 3/0, check-no-new-casts 28 (baseline);
fire_compiler/myinterpreter/module_loader `--dump` clean. Sweep:
`CI-DIFF=679, SELFHOST-CRASHED=24, AST/TOK-DIFF=14`.

## Continuation 11 — `_signature_ctypes` stub fix LANDED; the residual `1`
is not in `param_ctypes` at registration

**Landed (gate-green):** the `gen_module_impl` `self._signature_ctypes(...)`
stub (continuation 10) is now fixed by calling the free
`_ggf_dup._signature_ctypes(self, m.params, m, s.name)` (whose first param
`gen` IS typed `GimpleGen *`). This removes the
`int64_t._signature_ctypes() stubbed` replacement — the compiled Pass-2b-bis
now gets the real ctype list. It adds NO check-no-new-casts site (that test
greps raw SOURCE text, and the only two "+1 sites" this session were two
new explanatory COMMENTS containing the literal `(MojoList *)`; rephrasing
them restored the baseline). Gate after: check-gimple 308/0, check-modcache
81/0, check-selfhost 1/0, check-linkmode 3/0, check-no-new-casts 28.

**Residual crash narrowed further.** With the `CallExpr.kwargs` field +
direct read re-applied, dict.mojo still SIGSEGVs at
`mojo_list_len(0x1)`, frame #1 `_lower_struct_method_call` (line 4345,
inlined `_resolve_overload`). Disassembly at the crash: `mojo_str_cat`
builds a key, `mojo_dict_get_int(that key)` returns 1, and the result is
fed to `mojo_list_len` — so it is a `_func_param_defaults`-style
`.get(strcat_key)` value of 1, or `cand['param_ctypes']` in `_score`.
A file trace at the candidate-dict registration
(gimple_module_gen.py:4449) over a full dict.mojo compile shows `_all_ctypes
!= 1` and `param_ctypes != 1` for ALL 22873 registrations — so the value is
correct on the producer side and the `1` appears between the dict store
(`mojo_dict_set_int(d, "param_ctypes", <list ptr>)`) and the consumer read
(`mojo_dict_get_int`). Next step: trace `cand['param_ctypes'] == 1` inside
`_resolve_overload._score` and, if it is 1, bisect the candidate dict's
per-key store/load (mixed str/list/int/bool values in one dict literal).

**Final state (gate-green):** check-gimple 308/0, check-modcache 81/0,
check-selfhost 1/0, check-linkmode 3/0, check-no-new-casts 28 (baseline);
fire_compiler/myinterpreter/module_loader `--dump` clean. Sweep:
`CI-DIFF=679, SELFHOST-CRASHED=24, AST/TOK-DIFF=14`.

## Continuation 12 — batched the pointer-decimal key-coercion class
(one build, ~20 fixes)

Per the "batch fixes per build" guidance: scanned the generated
`gimple_gen_methods.ci` for `mojo_str_from_int(` (the pointer-decimal
key/string coercion signature) — 14 real sites in that one module alone —
and fixed them together in a single edit+build:

- 4 `_struct_method_csym` sites routed through the FREE
  `_ggf._struct_method_csym(gen, ...)` (un-stubs the call the
  int64-typed `gen` receiver would have stubbed to "return the receiver")
  re-tagged with the same-module `_gmm_as_str` -> `char *`.
- key wraps `_gmm_as_str(...)` on: `_class_attrs.get(class_name)`,
  `_global_var_types.get(gname)`, `_struct_bases.get(cur_struct)`,
  `_regex_progs.get(folded_pattern)`, `struct_field_types.get(_fut_sn)`,
  `struct_field_types.get(gen._current_struct_name...)`,
  `_elem_types.get(raw)`, `_actual_types.get(av)`, `_elem_types.get(it)`,
  and the `func_return_types/func_param_types.get(mangled)` sites.
- two dict comprehensions (`{kn: ... for kn, ke in _gm_kwargs}`,
  `{pn: dv for pn, dv in _method_dflts}`) converted to explicit loops
  (tuple-unpacked keys erase to int64_t).

Added `import gimple_gen_funcs as _ggf`.

Result: gate fully green (check-gimple 308/0, check-modcache 81/0,
check-selfhost 1/0, check-linkmode 3/0, check-no-new-casts 28 baseline),
fire_compiler/myinterpreter/module_loader `--dump` clean, sweep unchanged
(679/24/14) — i.e. the batch is a pure correctness improvement with no
regression, but does NOT by itself clear the `kwargs`-path crash, which
still gates the 24 SELFHOST-CRASHED files (that residual is the
`mojo_list_len(0x1)` in `_resolve_overload`, continuation 11).

**Note on the residual**: re-testing the `CallExpr.kwargs` field WITH this
batch still SIGSEGVs dict/list/set and fire_compiler/myinterpreter, so the
field remains held back.

**Gate-green final state:** as above; sweep `CI-DIFF=679,
SELFHOST-CRASHED=24, AST/TOK-DIFF=14`.

## Continuation 13 — diagnosing the `gen`/`self` boxed-int64 root

Instrumented `_selfhost_gen_self_param_ctype` and `_param_ctype`:

- `_selfhost_gen_self_param_ctype(gen, 'self', None, gen_module_impl)` DOES
  pass its gates (`idx=True reg=True`) and returns `GimpleGen *` (42 hits),
  and `_param_ctype` returns `GimpleGen *` for that param too
  (`param_ctype pname=self is_self=False sh=GimpleGen *`, 39 hits).
- The DEFINITION-emission point (`gen_func`'s own `param_strs` loop,
  gimple_gen_funcs.py ~2783) ALSO sees `ctype=GimpleGen *` for
  `gen_module_impl`'s `self` (`DEF pname=self ctype=GimpleGen * reg=True`).
- YET the emitted `.ci` is `int64_t gen_module_impl_2f7ad9 (int64_t self,
  MojoList * stmts)`, and `grep -c 'GimpleGen * self'` over the whole
  module is **0**.

So the heuristic + `_param_ctype` + `param_strs` are all correct, and the
`int64_t self` appears AFTER the `param_strs`/`params_str` construction:
either a post-emission signature rewrite/dedup (`_dedup_guarded_blocks` /
`_relocate_module_instance_defs` in `_run_pipeline`) or a locked/forward-
declared signature text that the definition reuses and which was computed
EARLIER (before the GimpleGen registry ran). The forward decl at the top of
the `.ci` (`int64_t gen_module_impl_2f7ad9 (int64_t, MojoList *);`, emitted
in the `#ifndef _MOJO_STUB_gen_module_impl_...` block) is int64 too, so the
suspicion is the FORWARD-DECL path caching first and the definition's
params being reconciled to it.

**Next step (focused):** find the forward-declaration emitter that produces
that `#ifndef _MOJO_STUB_gen_module_impl_...` block and its ctype source;
make it use the same `_param_ctype`/`_selfhost_gen_self_param_ctype` result
(or ensure the registry runs before it). Fixing it should type `self` as
`GimpleGen *` in `gen_module_impl`, which un-stubs every
`self.<method>()` in that function in one go.

Gate-green; sweep unchanged (679/24/14).

## Continuation 14 — ROOT of the `--dump-full` divergence: the GimpleGen
signature table was never shared into nested temp_gens

`make check` fails ONLY at `check-native-dumpfull` (`./mojoc fire.py
--dump-full` vs the python3 reference's own `--dump-full`). The FIRST
differing byte (offset 142814, line 4149) is a block of `GimpleGen__*`
method extern forward declarations
(`#ifndef _MOJO_STUB_GimpleGen___init__ ... extern void
GimpleGen___init__ (...); #endif`) that the reference emits and the
native binary did NOT.

Those externs are emitted by the `_imported_typedef_structs` loop in
`gen_module_impl` (gimple_module_gen.py:4472) and are driven by
`self._selfhost_gimplegen_sigs` / `_mangled_signature_ctypes`. File-tracing
`_gg_have_infile`/`stmts_none`/`nsigs` proved the cause:

    reference :  all 36 gens  stmts_none=0 nsigs=362
    self-host :  34 of 35    stmts_none=1 nsigs=0   (only the root had 362)

i.e. `_selfhost_gimplegen_stmts`/`_sigs`(`= class GimpleGen` + the frozen
362-entry signature table) were NEVER inherited by the nested temp_gens.

**Fix (landed):** the sharing loop in `gimple_gen_resolve.py` (~597) was
`for _sh_attr in ('_selfhost_gimplegen_stmts', ...): if hasattr(gen,
_sh_attr): setattr(temp_gen, _sh_attr, getattr(gen, _sh_attr))` — iterating
a tuple of STRING literals boxes `_sh_attr` to int64_t on the self-hosted
path, so `hasattr(gen, <boxed>)` was False for every entry. Replaced with
5 explicit `if hasattr(gen, '<literal>'): temp_gen.<literal> = gen.<literal>`
statements. Trace now matches the reference exactly
(`stmts_none=0 nsigs=362` in all gens).

**Effect:** the `GimpleGen__*` externs now emit; the compile progresses far
past line 4149. It also exposed a CASCADE of further latent bugs (each
fixed so far in this batch):
- chained `_scalar_obs.setdefault(...).setdefault(...).add(st)`
  (gimple_module_gen.py:5019) — intermediate results have no static type, so
  `.add` lowered to `mojo_set_add_int` on the inner DICT → SIGSEGV. Split
  into typed locals.
- `any(<genexpr>)` + `zip(...)` with nested tuple-unpack in
  `_repack_method_call_spread_args` — converted to explicit/indexed loops.
- `gen._repack_method_call_spread_args` / `_resolve_overload` /
  `_build_call_args_for_candidate` / `_pack_kwargs_dict` /
  `_default_expr_to_pair` calls in `_lower_struct_method_call` were all
  scalar-stubbing (`int64_t._X() stubbed`, returning the receiver) because
  that function's `gen` is still boxed `int64_t` — routed to their free
  functions (`ggc._X(gen, ...)` / same-module `_X(gen, ...)`).

**Current `--dump-full` state:** no longer diverges at the externs, but now
SIGSEGVs deeper, in `gimple_gen_resolve.py:_infer_local_var_types`
(`mojo_dict_iter_key` on a garbage dict). Still a cascade, not converged.

**Gate after this batch (green, no regression):** check-gimple 308/0,
check-modcache 81/0, check-selfhost 1/0, check-linkmode 3/0,
check-no-new-casts 28; fire_compiler/myinterpreter/module_loader `--dump`
clean; sweep unchanged 679/24/14.

**Goal status (`make check && make bootstrap`, stdlib dylib, compile_stdlib):**
`make check` still fails ONLY at check-native-dumpfull (now a crash instead
of a byte divergence); `make bootstrap` unchanged (stage2 clean, verify
diffs remain); stdlib dylib + compile_stdlib believed unchanged (not yet
re-measured after continuation 14).

## Continuation 15 — cascade continues (annotating closure-captured dicts)

Next cascade step after continuation 14: `./mojoc fire.py --dump-full`
SIGSEGV'd in `gimple_gen_resolve.py:_infer_local_var_types` at
`for vname in inferred:` (image-lookup: line 2541) — `mojo_dict_iter_key`
read `it->dict->slots[it->order[it->pos]]` on a corrupted dict. `inferred =
{}` was UNANNOTATED and is captured by the nested `collect_assigned_types`
closure (through its lifted env struct), so the env field / closure writes
were left int64_t and corrupted the dict. Annotating
`inferred: dict[str, list] = {}` (and `result: dict[str, str] = {}`) fixed
that crash.

The crash then returned to `gimple_gen_methods.py:_lower_struct_method_call`
line 4419 (`_repack_method_call_spread_args(gen, mangled, ..., _cnode.args,
arg_pairs)`) — `mojo_list_get_int` on a list whose `data` is bad. Still
cascading.

Gate green, sweep unchanged (679/24/14). Everything landed this session is
non-regressing.

## Continuation 16 — the `gen`-typing mystery: annotations apply to
`ov`/`ot`/`method` but NOT to `gen`

Tried forcing the FIRST parameter's type on `_lower_struct_method_call`:
- `gen: 'GimpleGen'` (string annotation) — sig still `int64_t gen`.
- `gen: GimpleGen` (bare name, safe under `from __future__ import
  annotations`) — sig still `int64_t gen`.

Both reverted (no effect). Key observation: the SAME signature shows
`char * ov, char * ot, char * method` — so param annotations DO apply
normally; `gen` specifically stays `int64_t`. Combined with continuation
13 (the `gen_func` `param_strs` loop file-tracing `ctype=GimpleGen *` for
`self`, and `_param_ctype` returning `GimpleGen *`) this means the first
`gen`/`self` param is being forced back to `int64_t` AFTER
`_param_ctype`/`param_strs` — a dedicated override (or a locked/cached
signature) that neither the heuristic nor an explicit annotation can
displace. That override is the single highest-leverage thing to find:
fixing it types `gen` as `GimpleGen *` in `_lower_struct_method_call`
(and `gen_module_impl`), which un-stubs every `gen._X()` call in them in
one go (117 `lower_expr() stubbed` sites in gimple_gen_methods alone).

Gate green; sweep unchanged (679/24/14).

## Continuation 17 — IMPORTANT correction: the `gen`-typing investigation
via single-file `--dump` was on a config where the registry is OFF

Traced `_selfhost_gen_self_param_ctype`'s gates + `_param_ctype`'s result
for `_lower_struct_method_call`'s `gen` while dumping THAT ONE FILE:

    GATE _lower_struct_method_call pname=gen bare=gen nps=5 ps0='gen'
         idx=True reg=False
    PC   _lower_struct_method_call gen ptype=None sh=None
    DEF  _lower_struct_method_call gen ctype=int64_t

`reg=False` — `_selfhost_gimplegen_registered` is FALSE there. Cause: the
registration is gated (gimple_codegen.py:4492) on
`(do_imports or link_mode) and filename and basename(filename) in
('fire.py','mojo_main.py','fire_compiler.py')`. A single-file
`python3 fire.py --dump gimple_gen_methods.py` (or `./mojoc
gimple_gen_methods.py --dump`) meets NO part of that, so
`_selfhost_register_gimplegen` never runs, `_selfhost_gimplegen_registered`
stays False, `_selfhost_gen_self_param_ctype` returns None, and `gen`/`self`
box to int64_t — BY DESIGN for that invocation.

Consequence: the `gen`-typing conclusions in continuations 13/16 (and the
`gen.lower_expr()` stubs seen while dumping a single file) were measured on
a path where the registry is deliberately off. In the REAL targets —
`./mojoc fire.py --dump-full` (fire.py, basename matches, and the build
uses do_imports=True) — `reg=True`, so `gen`/`self` ARE typed
`GimpleGen *` and those stubs should not occur. The `--dump-full` cascade
must therefore be re-diagnosed with that correct config (or by tracing with
`reg` printed), NOT via single-file dumps.

The continuation-14 sharing fix remains valid and necessary (the nested
temp_gens in the `--dump-full` run had `stmts_none=1 nsigs=0` while the
reference had 362). The `_upper_bound` stub-routing fixes landed for the
right family (they are correct either way) but were not the `--dump-full`
blocker.

Gate green; sweep unchanged (679/24/14).

## Continuation 18 — `--dump-full` now EXITS 0 but silently drops ~93% of
the output (2.2 MB vs the reference's 33.7 MB) and is NON-DETERMINISTIC

After the continuation-14 sharing fix + continuation-15 cascade fixes,
`./mojoc fire.py --dump-full` no longer SIGSEGVs on most runs (it still
does intermittently — a heap-layout-dependent crash, matching this
project's known non-determinism family). BUT the artifact it writes is
2,235,608 / 2,235,676 bytes vs the `python3 fire.py --dump-full fire.py`
reference's 33,772,200 — i.e. it is dropping the overwhelming majority of
the imported modules. This is EXACTLY the failure mode CLAUDE.md's
`check-native-dumpfull` note warns about ("a fix that made --dump-full exit
0 instead of crashing was actually WORSE ... silently dropped two sibling
modules"), and the run-to-run byte difference (2235608 vs 2235676 for the
same input) confirms heap-order non-determinism in that path too.

So `check-native-dumpfull` is not close: the binary must (a) deterministically
inline every sibling module into fire.ci with the same bytes as the
reference and (b) not crash. The continuation-14 sharing fix was necessary
(the externs now emit) but is far from sufficient.

**Session-end state (gate-green, no regression):**
- `compile_stdlib.py` PASSED 664 / FAILED 0 (0 unexpected); `build_stdlib_dylib`
  rc=0, 0 skips.
- `make check` fails ONLY at check-native-dumpfull (above).
- `make bootstrap` verify diffs remain (same self-host codegen root family).
- check-gimple 308/0, check-modcache 81/0, check-selfhost 1/0,
  check-linkmode 3/0, check-no-new-casts 28; fire_compiler/myinterpreter/
  module_loader `--dump` clean; sweep 679/24/14.

## Continuation 19 — investigating "all *.py zero diffs": the biggest shared
divergence (@11225) is a native-path non-determinism, not a missing 5 lines

Measured the per-file `--dump` status directly (A/B sweep, root/*):

- current (uncommitted) tree: 104 of 115 root `*.py` differ, 11 clean.
- committed HEAD (`f765689`): 112 of 115 differ, 3 clean.

So the committed state is WORSE than the uncommitted tree — the session's work
is net-positive, not destructive (the "previously all zero" state does not
correspond to `f765689`; it is a goal, not a recent regression).

The largest SHARED divergence is `first diff @11225` in 5 files
(gimple_codegen, gimple_ctypes, gimple_exprtypes, gimple_module_gen,
gimple_solvers): the PYTHON reference emits `__mojo_global_get__*` accessor
externs for `generated_dispatch`'s dict/set globals (`_SIGNED`, …) that the
compiled backend omits. File-traced root:

1. `module_loader.load_module_from_path`: the gate
   `os.path.basename(path) == 'generated_dispatch.py'` evaluated **False** at
   the gate (line ~663) while the IDENTICAL expression evaluated True 230
   lines later in the same call — and `'generated_dispatch' in path` behaved
   the same way — so the container-literal scan was skipped and 0 of the 7
   globals were exported.
2. With that gate made robust, the exports populate (7/7) — but then
   `_emit_imported_global_accessors`'s `exports.get(name)` returns the entry
   for the FIRST lookups and `None` for LATER, IDENTICAL lookups within one
   run (file-traced `info=1` then `info=0` for the same `name='_SIGNED'`,
   `mod='generated_dispatch'`).

Both are the same family as this project's known self-hosted string/dict
non-determinism. Applying the fixes (`in` gate + adding
`struct_field_types['FromImportStmt']['name_alias_strs']`, the parser-built
workaround for boxed tuple strs) made the sweep WORSE (root 104->110,
AST/TOK 13->34, the @11225 cluster 5->35) because it emits the accessors
inconsistently instead of never — so both were REVERTED.

Conclusion: reaching zero per-file diffs requires fixing the underlying
self-hosted string-compare / dict-lookup non-determinism (paths +
`exports.get(name)`), NOT a handful of missing struct fields. That is the
root cause to attack next, and it is the same nondeterminism behind
`--dump-full`'s 2.2MB-vs-33.7MB module drop.

# ================== SESSION CHECK-IN — RESUME HERE ==================

## State of the tree (ready to check in)
Gate green: check-gimple 308/0, check-modcache 81/0, check-selfhost 1/0,
check-linkmode 3/0, check-no-new-casts 28 (baseline);
`fire_compiler.py`/`myinterpreter.py`/`module_loader.py --dump` clean.
Per-file A/B sweep: 779 files — clean=57, CI-DIFF=679, SELFHOST-CRASHED=24,
AST/TOK-DIFF=14, SHIM-FAILED=5. `compile_stdlib.py` 664 PASS / 0 FAIL
(0 unexpected); stdlib dylib builds rc=0 with 0 skips.
Two `.o`/`.ci` scratch files removed; no debug/trace leftovers in the tree.

## Headline findings this session
1. **TOKENIZATION IS ROCK SOLID.** All 779 files' `.tok` — including all 115
   root `.py` — are byte-identical shim-vs-self-host. The ONLY 24 `.tok`
   diffs are exactly the 24 SELFHOST-CRASHED files, and their sizes are
   round (partial writes before the crash). `tok-diff == crash-set` exactly.
   So nothing downstream is a tokenizer problem.
2. **The 24 crashes** (the whole SELFHOST-CRASHED set) are a
   `mojo_list_len(0x1)` inside `_lower_struct_method_call` /
   `_resolve_overload` in the SINGLE-FILE `--dump` config. File-traced:
   `_method_candidates` is a valid 2-candidate list, `node.kwargs == []`,
   `_resolve_overload` returns `survivors` (valid 1-element list) fine, and
   `_chosen_method`/`ret_type='void'` are fine; the `1` then appears in the
   `ret_type is None and method == 'copy' … _KNOWN_SIGS` statement — the
   same "missing field / dispatch-miss sentinel 1" mechanism, this time in
   the config where the GimpleGen registry is off (single-file `--dump`) so
   `gen.<field>` reads dispatch and miss.
3. **The `--dump-full` divergence root** (continuations 14–15): the
   362-entry `GimpleGen` signature table was not shared into nested
   temp_gens (boxed attr-name in the sharing loop) — FIXED. Exposed a
   cascade; several cascade bugs fixed (chained `setdefault().add()` typed
   locals, `any(<genexpr>)`/`zip`-unpack loops, `inferred`/`result`
   annotations). `--dump-full` now exits 0 but writes 2.2 MB vs the
   reference 33.7 MB (drops ~93% of modules) and is non-deterministic.
4. **The biggest shared per-file divergence (`@11225`, 5 files)** is a
   self-hosted **non-determinism**: `os.path.basename(path)=='x'` / `'x' in
   path` evaluate differently at different points in one call, and
   `exports.get('_SIGNED')` returns the entry then `None` for identical
   later lookups. Applying the "obvious" fixes made it WORSE (root 104→110,
   AST/TOK 13→34) and was reverted. Fix the nondeterminism, not the fields.

## Instrumentation / checksumming support (NEW, gated off by default)
- `determinism_trace.py` — iota + xorshift rolling-hash stream. Set
  `MOJO_TRACE=1` (and optionally `MOJO_TRACE_FILE=<path>`, default
  `/tmp/mojo_trace.txt`) to enable; one `<iota> <hash>` line per note.
  Off ⇒ a single dead bool branch, no I/O, no perturbation.
  Exposes `enabled()`, `note(entropy)`, `note_str(s)`, `str_hash(s)`,
  `reset()`, `current()`.
- Hooked at `gimple_gen_resolve._new_val` — the temp-allocation chokepoint
  every emitted value flows through. Entropy is CONTENT only (never an
  address). Verified: shim vs self-host streams are IDENTICAL ("IDENTICAL:
  2 steps") on a smoke file, and no file is written when `MOJO_TRACE` is
  unset.
- `tools/detrace_diff.py` — finds the first divergent iota between two
  streams (scripted `diff a b | sed 10q`).
- `tools/audit_selfhost_struct_fields.py` — diffs the real dataclasses
  against the hardcoded `struct_field_types` map (reports the known gaps:
  `CallExpr.kwargs/line/col`, `FromImportStmt.name_alias_strs`,
  `StringLiteral.is_bytes`, `SubscriptExpr.attrs`).
- NOTE the facility itself caught two of this project's own traps while
  being written: `str in (<tuple>)` (TUPLE-IN, made `enabled()` always
  False) and `isinstance(<boxed>, str)` (constant-FALSE, made `str_hash`
  return 0); and a 64-bit mask/seed constant did not materialise correctly
  in the compiled backend, so all constants are now ≤31-bit.

## How to resume (concrete next steps, in order)
1. Use the facility: `MOJO_TRACE=1 MOJO_TRACE_FILE=/tmp/a.txt ./mojoc
   <file> --dump` and the same with `python3 fire.py --dump <file>`, then
   `tools/detrace_diff.py /tmp/a.txt /tmp/b.txt`. Start with a
   SELFHOST-CRASHED file (e.g. `stdlib/.../collections/dict.mojo`) — its
   stream will diverge at the exact `_new_val` before the crash. Add finer
   `note()` points once the coarse stream is down to one call.
2. Fix the self-hosted string-compare / dict-lookup non-determinism (item 4
   above) — it is the root of both `@11225` and the `--dump-full` module
   drop. `tools/audit_determinism.py` lists the address-dependent
   construct classes to grep for.
3. Then re-apply the missing `struct_field_types` entries from
   `tools/audit_selfhost_struct_fields.py` (each needs the .ast/.tok
   regression checked; `name_alias_strs` was net-negative on its own).
4. Then `make check-native-dumpfull` (full 33.7 MB byte-identity) and
   `make bootstrap` verify.

## Continuation 20 — `.ast` divergence triage for the *.py files

Follow-up to the `.tok` result (tokenization solid). Built the restructured
tree (mojo/middle + mojo/backend_gimple), regenerated the sweep, and diffed
every `.ast` shim-vs-self-host: 763 files, **374 `.ast` diffs**. First-diff
classification (the `.ast` is `repr(ast)`, so these are REPR/reflection
differences, not necessarily parser differences):

| count | first-diff class | PY | NC |
|------:|------------------|----|----|
| 180 | `param_convs` value | `{'b': 'mut'}` | `{'b': None}` |
| 130 | `raw=` on IntLiteral | `raw=''` | `raw=None` |
|  24 | truncated NC (prefix of PY) | full | cut mid-node |
|   9 | `kwargs` | full | differs |
|   4+ | `comptime_aliases` | full | differs |
|   3 | `yield_bearing_node_ids` | `frozenset({<ADDRESSES>})` | `''` |
|   2 | `is_bytes` bytes literal | `'\x00missing:'` | `'missing:'` |

Notable:
- `yield_bearing_node_ids` prints a **frozenset of `id()` addresses** in the
  PY reference — the .ast is ADDRESS-DEPENDENT (non-reproducible) for any
  file with a generator on the reference side, and empty (`''`) natively.
- the 24 "truncated" cases mean the native `.ast` WRITE stops early (a raw
  NUL in the rendered repr, or a mid-write failure) — the native file is a
  strict prefix of the reference's.
- `is_bytes`: a `b'\x00...'` bytes literal loses its leading NUL natively.
- `raw=''` vs `raw=None`: an empty string field renders as NULL natively
  (empty-string vs NULL distinction).

`fire_compiler._canon_conv` was the first suspect for the `param_convs`
class (`cls._CONV_CANON.get(conv, conv)` — class-attribute dict read erases
to int64_t, so `.get` hit the scalar stub) and was rewritten to explicit
`==` comparisons — but that alone did NOT change the count, so the value is
lost by the time it is stored (the parser's `conv`, or the dict store), not
only at canonicalisation. Next step: file-trace `param_convs` immediately
after `_parse_funcdef`'s param loop on a file with a `mut` parameter, on
both sides, to decide parser-vs-repr.

## Continuation 21 — AST-based audit tooling + genexpr crash-class fixes

Built `tools/audit_selfhost_ast.py` (real Python `ast`, at scale) for the
self-host-unsafe syntactic shapes. Counts over the compiler's own source:
`any/all(<genexpr>)` 102, genexpr-tuple-target 41, listcomp-unpack 37,
dictcomp-unpack 24, for-clause-tuple 438. These are the crash class
(`mojo_list_len(0x1)`), not cosmetic.

Fixes landed (gate-green):
- `mojo/middle/solvers.py`: `_has_try` genexpr (`any(... for _, eb in ...)`)
  -> explicit loops; plus 4 more `any/all(genexpr)` sites.
- `mojo/middle/funcs_shared.py`: two `any(pn.startswith('**') for pn, _ in
  ...)` -> explicit loops.
- `mojo/middle/infra_infer.py`: `all(...)` genexprs -> explicit loops
  (this one, done wrong the first time, briefly broke the whole build — the
  accumulator must be computed AFTER the `isinstance(it, ...)` guard, since
  `it.elements` does not exist on every `it`).
- `fire_compiler.py`: `*args` parser fix (variadic was dropped — the
  `*args` branch was mis-indented inside the `while _CONV_KWS` loop),
  `_canon_conv` explicit comparisons + internal `_as_str` re-view.
- `mojo/backend_gimple/module_gen.py`: `_mojo_repr_dict` now renders a
  `kind==2` (mojo_dict_set_str) value via `mojo_repr_str` instead of
  reading its pointer as an int.

Effect: SELFHOST-CRASHED 55 -> 24, CI-DIFF 634 -> 665, `.ast` diffs
374 -> 351, `.ast` truncations 24 -> 1. `fire_compiler`/`myinterpreter`/
`module_loader` all `--dump` clean; check-gimple 308/0, check-selfhost 1/0,
check-modcache 81/0, check-linkmode 3/0, check-no-new-casts 28.

STILL OPEN — the `param_convs` `.ast` class (180 files). Evidence gathered:
`_canon_conv('mut')` returns `'mut'` (file trace `ret=[mut]`); emitted C is
`mojo_dict_set_str(param_convs, pname, _t214)` with `_t214 = Parser__canon_conv(...)`
returning `char *`; the emitted `_mojo_repr_dict` HAS the `kind==2` branch —
yet the native `.ast` still prints `param_convs={'x': ''}`. So the value is
lost between a correct store and a correct repr; the next step is a minimal
native repro of `d["x"]="mut"; repr(d)` (I could not drive `.mojo` `Dict`
from the CLI — `No handler for FromImportStmt`) or an lldb watch on the
`_DictSlot` written by that `mojo_dict_set_str` call.

## Continuation 22 — `param_convs` class SOLVED (classmethod-called-via-self
argument mis-binding); `.ast` diffs 351 -> 280

Root cause of the 180-file `param_convs={'x': ''}` class, found by calling
the compiled symbol directly from lldb
(`_fire_compiler_Parser__canon_conv(0, "mut")` -> `"mut"`, correct), then
reading the emitted call site:

    _t538 = (int64_t)conv;          /* caller's conv, NON-null */
    _t542 = (char *)(void *)0;      /* <-- the classmethod's 2nd arg = NULL */
    _t537 = Parser__canon_conv(_t538, _t542);

A `@classmethod` invoked through an INSTANCE (`self._canon_conv(conv)`) was
lowered with the receiver passed as `cls`, so the real first argument landed
in the `cls` slot and the `conv` parameter got NULL. Every
`param_convs[pname] = self._canon_conv(conv)` therefore stored the empty
string. Qualifying the call at the source —
`_as_str(Parser._canon_conv(conv))` (class-name receiver, which the
classmethod-resolution path handles correctly) — fixes all three call sites.

Also in this pass:
- `fire_compiler._canon_conv` gained a `conv: str` annotation (so the
  parameter is typed `char *` not `int64_t`) and a separate `_cv` local;
  the emitted comparison previously re-read the erased PARAMETER
  (`_t5 = (int64_t)conv; mojo_cstr_cmp((char*)conv, ...)`) even after the
  `conv = _as_str(conv)` reassignment — a fresh local name avoids that.

Effect: the `param_convs` `.ast` class is **180 -> 0**; total `.ast` diffs
**351 -> 280**. Remaining classes: `raw=` 193 (a repr nit: an omitted
`IntLiteral.raw` prints `None` vs the reference's `''`; the alloc path that
sets it is correct in the single-file config, so it is a different
construction/repr path), `kwargs` 10, `comptime_aliases` ~15, `yield_bearing`
3, `is_bytes` 2.

Gate green (check-gimple 308/0, check-selfhost 1/0, check-modcache 81/0,
check-linkmode 3/0, check-no-new-casts 28); the three self-host files dump
clean. Sweep: clean=58, CI-DIFF=665, SELFHOST-CRASHED=24, AST/TOK-DIFF=13.
