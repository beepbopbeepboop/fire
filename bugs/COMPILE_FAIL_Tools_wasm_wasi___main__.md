# COMPILE_FAIL: Tools/wasm/wasi/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-09)

Re-verified fresh. Of the three originally-reported issues, 1 and 3 are
now resolved (1 by an earlier session's `try`/`except ImportError`
mechanism fix; 3 fixed in this session); issue 2 remains open and is
the only thing still blocking this file.

1. **FIXED** (earlier session): `redefinition of 'cpu_count'` from
   `try: from os import process_cpu_count as cpu_count / except
   ImportError: from os import cpu_count` no longer reproduces — the
   `try`/`except ImportError` fallback mechanism fix
   (`bugs/hard/CODEGEN_try_except_import_fallback_both_branches_
   compiled.md`) landed and covers this file's instance too (confirmed
   via a fresh `python3 mojo.py build`; sibling file `Tools/ssl/
   multissltests.py` was independently re-verified clean earlier this
   session as well).

2. **STILL OPEN** — `invalid call to non-function before ';' token`,
   two call sites:
   - `def subdir(working_dir, *, clean_ok=False): ... def wrapper
     (context): nonlocal working_dir; if callable(working_dir):
     working_dir = working_dir(context)` (~line 104) — `working_dir` is
     an unannotated parameter that is SOMETIMES a plain value
     (a `pathlib.Path`, later used as `working_dir.exists()`) and
     SOMETIMES a zero-arg callable returning one (`context ->
     Path`); real Python discriminates at runtime via `callable(...)`.
   - `def build_steps(*steps): def builder(context): for step in
     steps: step(context)` (~line 408) — same root cause: `step` is an
     element of an unannotated `*args` tuple, called as a function.
   Both are the SAME gap: this codegen's cross-call type-inference
   pass for unannotated free-function params ("Pass 1.3d", see
   `bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_
   int64.md`'s "Why this doesn't affect free functions the same way"
   section) only recognizes SCALAR contracts (`double`/`char *`); a
   callable-typed parameter isn't one of those, so both `working_dir`
   and `step` still default to `int64_t`, and calling that int64_t
   value as a function fails ("invalid call to non-function").
   Confirmed via a fresh re-run this session — not investigated
   further given this session's continued caution around Pass 1.3d
   (shared call-argument-lowering/type-inference machinery whose
   narrow-looking edits have previously caused broad silent
   regressions elsewhere in this codebase — the "_tuplegetter
   incidents"). A real fix would need a genuinely new "always called as
   a function value" contract kind recognized by that same shared pass,
   not a local one-line change — classified as structural, not narrow.

3. **FIXED** (this session): `invalid operands to binary / (have
   'char *' and 'int64_t')` at module-level `BUILD_DIR = CROSS_BUILD_DIR
   / sysconfig.get_config_var("BUILD_GNU_TYPE")` — `sysconfig.
   get_config_var(...)` wasn't modeled anywhere in `gimple_codegen.py`
   (no `_KNOWN_SIGS`/module-dispatch entry at all), so the call fell
   through to the generic default (`int64_t`), and the following `/`
   (pathlib path-join) then saw `(char *, int64_t)` instead of
   `(char *, char *)`. Fixed by adding a dedicated
   `module_name == 'sysconfig' and method_name == 'get_config_var'`
   case to the module-call dispatch in `_lower_call` (~line 11406) that
   stubs the result to an empty string via the existing `_stub_result`
   convention (this codegen has no real libpython build-config data to
   answer with — implementing the real semantics is a separate, much
   larger "model sysconfig's build config" project), typed correctly as
   `char *`; also added the matching `_quick_type` pre-pass entry
   (~line 7207) so a local/global variable holding the result infers
   the right C type too. Confirmed fixed by re-running the build: this
   specific error is gone; a DIFFERENT `char*`/`int64_t` `/` error
   remains at a later line (`sysroot = wasi_sdk_path / "share" /
   "wasi-sysroot"`, ~line 260) but that one is unrelated to sysconfig —
   `wasi_sdk_path = context.wasi_sdk_path` is a dynamic attribute read
   off an opaque object, the already-documented, separate
   `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md` structural
   gap, not attempted here.

Net: this file still does not compile clean (issue 2's two call sites
are still hard errors, and the `context.wasi_sdk_path` dynamic-attribute
gap noted under issue 3 is a further, separate blocker past that). Not
fixed here beyond issues 1/3 above.

Exit code: 1
