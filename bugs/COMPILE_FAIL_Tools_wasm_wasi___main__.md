# COMPILE_FAIL: Tools/wasm/wasi/__main__.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/wasm/wasi/__main__.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (updated 2026-08-25, wtOpencode_group3): `step(context)` half FIXED (commit `1dcbcf9`); `working_dir(context)` half root-caused DEEPER than previously documented — the parser has no `nonlocal` support at all

Fresh reproduction confirms issue 2's two errors, but investigation
showed they have DIFFERENT root causes, and one is now fixed:

1. **FIXED (`1dcbcf9`, shared compiler source) — line 408,
   `build_steps`'s `step(context)`.** Not a missing "callable contract
   kind" in Pass 1.3d at all. The loop var `step` was declared `char *`
   by `_gen_for_iter`'s generic arm (its dict-key convention), and
   `_gen_stmt_ExprStmt`'s fnptr guard only checked the declared ctype
   against the scalar-box list — unlike `_lower_call`'s expression-path
   twin, which ALSO fires on plain local-variable MEMBERSHIP precisely
   because a first-decl-wins `char *` decl can't disqualify a callable.
   Adding the membership half to the statement-level guard mirrors that
   proven pattern verbatim; in any valid Python a locally-bound name
   called as a function IS a callable, so routing through
   `mojo_fnptr_call_N` is semantics-preserving. Verified end-to-end
   with a distilled repro (functions stored in a list, iterated, called
   through the loop var): builds AND runs correctly. Full gate clean
   (256/256, 76/76, selfhost, dylib 0 skips).

2. **STILL OPEN — line 104, `wrapper`'s `working_dir = working_dir
   (context)`: the root cause is UPSTREAM of type inference entirely:
   this parser has NO `nonlocal` support.** `nonlocal` is not in
   mojo_compiler.py's keyword set and has no statement parser, so
   `nonlocal working_dir` degrades to stray EXPRESSION statements
   (visible in the generated .ci as literal-0 reads commented
   `/* ct param or undeclared: nonlocal */`). The closure-capture pass
   therefore sees `working_dir` as an ASSIGNED-LOCAL of `wrapper`
   (correct Python only because of the nonlocal declaration it never
   saw): it is not added to `subdir_decorator_wrapper_env` (which
   captures only `clean_ok` and `func`), its pre-assignment reads emit
   constant 0, and the call emits on the uninitialized local. A real
   fix needs: parser support for a NonlocalStmt (mirroring
   GlobalStmt), capture-analysis treating nonlocal-declared names as
   captured, and env-threading of their values (writeback semantics —
   real Python cells mutate the enclosing scope — would additionally
   need by-reference capture). That is shared-parser + closure-machinery
   surgery (mojo_compiler.py AST shapes feed gimple_codegen's lowering
   AND myinterpreter's evaluator AND this compiler's own self-hosting
   source, which itself contains real `nonlocal`) — feature-sized,
   deliberately not attempted per campaign rules.

Also exposed while testing (separate gap, NOT part of this file's
build): a `*args` tuple captured into a nested closure loses its
container type (the env slot boxes it to int64_t), so a lifted inner
function iterating it hits `mojo_unsupported_iter`. Distinct from both
issues above; noted here because the file's `build_steps` idiom
naturally pairs the two features.

Net: down from 2 errors to 1; the remaining one is a genuine feature
gap in closure/nonlocal machinery, not type inference.

## Status (2026-08-23): re-verified — STILL-OPEN, narrowed to issue 2 exactly.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`): the build
now fails with ONLY issue 2's two documented `invalid call to non-function
before ';' token` errors (`working_dir(context)` in `subdir`'s `wrapper`, and
`step(context)` in `build_steps`' `builder` — callable-typed unannotated
parameters defaulting to `int64_t`; structural per the 2026-08-09 analysis).
The additional later-line `char*`/`int64_t` binary-`/` error that the 2026-08-09
note's issue 3 mentioned (`context.wasi_sdk_path` dynamic attribute read) no
longer reproduces — absorbed by intervening dynamic-attribute work — so issue 2
is now the sole blocker on this file.

## Status (updated 2026-08-09, historical — superseded header only)

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
