# COMPILE_FAIL: Tools/build/deepfreeze.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/deepfreeze.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, worktree-agent-a21934cd6fb7c6509 @ master `e60b9cd`): build still exits 0, 0 error lines, both open items unchanged

Fresh `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Tools/build/
deepfreeze.py` against this worktree (fast-forwarded to master
`e60b9cd`): `Built: .../deepfreeze`, exit 0, 0 `error:` lines —
byte-identical outcome to the entry directly below. Both open items
(link-mode sibling-import degradation; argparse-runtime
`AttributeError: verbose` from a Namespace default never actually
populated, root-caused as argparse never being compiled into the
binary at all) are unchanged and remain outside this compile-fail
doc's scope (runtime-fidelity/import-resolution features, not a
narrow compile bug). Not attempted; no code change.

## Status (re-verified + root cause CORRECTED, 2026-08-26, worktree fix/opencode-misc1 @ `e1e12bb` — build still exits 0; the "argparse runtime AttributeError" blocker re-root-caused: argparse is never compiled into the binary at all, in EITHER mode)

Fresh `mojo.py build` (safety-wrapped): still exits 0 with 0 own-file
error lines. Re-investigation this pass CORRECTS item 2's diagnosis
from the entries below:

- The runtime death (`Unhandled exception: AttributeError: verbose`) is
  NOT "argparse's default-population control flow not reaching
  Namespace" and needs NO auditing of argparse's compiled logic —
  **argparse is not compiled into the binary at all**. lldb on the
  inline-built binary shows `_gimple_main` → `mojo_obj_getattr` raising,
  and the generated `.ci` shows every argparse call lowered as a
  receiver-stub: `_t48 = _t41; /* int64_t.parse_args() stubbed */` — so
  `args` IS THE PARSER OBJECT and `args.verbose` is getattr(parser,
  'verbose'). A minimal `import argparse; add_argument("-v",
  action="store_true"); parse_args([]); print(args.verbose)` repro
  reproduces identically.
- WHY argparse never resolves: the inline importer's search path is
  sys.path-inserts + the importing file's dir + bounded ancestor walk +
  CWD/script_dir (`_module_candidate_paths`), and both resolver layers
  are `.mojo`-only for PATH-based resolution (`imports._find` looks for
  `<name>.mojo`/`<name>/__init__.mojo` only). From Tools/build/, no
  walk-up reaches CPython's Lib/, so `import argparse/contextlib/re/
  collections/types/builtins` all degrade silently to stubs — while
  sibling umarshal.py DOES resolve via the walk-up (17 umarshal symbols
  nm-verified in an inline-forced build). PYTHONPATH does NOT help:
  imports.py honors the env var for its search PATH, but `_find` only
  ever probes `<dir>/<name>.mojo` / `<dir>/<name>/__init__.mojo`
  candidates — a `.py` file on that path is still invisible; verified
  empirically that `PYTHONPATH=<tree>/Lib` leaves
  resolve_source('argparse') = None.
- A principled fix direction (recorded, deliberately not forced):
  detect a CPython source checkout (entry file whose ancestors contain
  a `Lib/` dir) and append `<root>/Lib` to the candidate search dirs.
  Bounded blast radius (only entry files inside such trees), but it
  would newly INLINE large Lib closures into currently-"green"
  stub-built binaries — e.g. deepfreeze would then hit contextlib.py's
  async-codegen refusal (see bugs/COMPILE_FAIL_Lib_contextlib_*.md) and
  fail honestly instead — a real behavioral shift across concurrent
  agents' baselines, so recorded here rather than forced.

Item 1 (link-mode sibling degradation) unchanged. Doc stays open;
still blocked on non-compile families (link-mode sibling support /
inline Lib resolution) plus, past those, contextlib's async feature.

## Status (re-verified 2026-08-26, worktree fix/rest-remainder19c — build still exits 0 with 0 errors; both remaining gaps re-investigated, neither newly tractable)

Fresh `mojo.py build .../Tools/build/deepfreeze.py`: still exits 0, 0
error lines, binary runs. Re-checked both open items:

1. **Link-mode sibling-import degradation** (item 1 below) — unchanged,
   still a real feature-sized gap (link mode's import loader has no
   support for arbitrary non-stdlib sibling files at all).

2. **Argparse-runtime `AttributeError: verbose`** (item 2 below) —
   traced one step further than before. Confirmed `setattr(self, name,
   kwargs[name])`-shaped dynamic-name writes DO lower to a real
   runtime call (`gimple_codegen.py`'s `BUILTIN_FUNCS['setattr'] =
   'mojo_setattr'`, calling `runtime/mojo_runtime.c`'s real per-object
   dynamic-attribute store, `mojo_setattr`/`mojo_obj_getattr` — this
   machinery already exists and IS exercised, per the 2026-08-25
   umarshal `Code.__dict__`-adjacent fix). The crash is NOT simply
   "dynamic getattr unimplemented" — `args.verbose` reads through this
   same real dispatch and gets a genuine "not found" (a correctly-
   raised `AttributeError`, not a segfault/garbage read), meaning the
   value is never actually written to the `Namespace` instance at
   runtime. `args.verbose` originates from an `action="store_true"`
   argparse option (`parser.add_argument("-v", "--verbose",
   action="store_true", ...)`), whose default-population path lives
   deep in `argparse.ArgumentParser.parse_known_args`/`_get_values`
   (iterating `self._actions`, calling `setattr(namespace, action.dest,
   action.default)` for every action not explicitly supplied on the
   command line) — real argparse runtime-fidelity territory, not a
   contained bug in the dynamic-attribute primitive itself. Tracing
   why THIS specific default-population call doesn't reach `Namespace`
   would mean auditing argparse's own compiled control flow (multiple
   nested loops/conditionals across `_actions`/`_get_values`), a real
   investigation into a large already-compiled stdlib file, not a
   narrow fix — still correctly out of scope for this compile-fail
   doc. Not attempted further.

Doc stays open, reclassified status unchanged from the entry below.

## Status (updated 2026-08-25, worktree fix/opencode-group2 — build exits 0 with 0 errors; the shared umarshal root cause is FIXED; remaining gaps are link-mode sibling-import degradation + argparse runtime, both outside this compile-fail doc's subject)

Re-verified fresh: `python3 mojo.py build .../Tools/build/deepfreeze.py`
**exits 0 with 0 error lines**, and deepfreeze.py's OWN source compiles
clean in isolation too (fresh `do_imports=False` + `gcc -fgimple
-fsyntax-only`: 0 errors — the 2026-08-09 entry's own-file `max()` fix
holds).

The SHARED root cause this doc always pointed at — umarshal.py's 17
compile errors — is now fully fixed (see that doc's 2026-08-25 entry:
missing-member writes route through `_mojo_dispatch_setattr` runtime
dispatch, plus the funcptr-`main` declaration fix).

**What is NOT yet resolved here, verified precisely**:

1. **Link mode still silently degrades `import umarshal`.** MOJO_DEBUG
   shows `load_module('umarshal') failed; treating module as empty:
   Only stdlib and test imports supported` — link mode's import loader
   has no support for non-stdlib SIBLING files, so the built binary
   contains no `Reader`/`_r_object`/`loads` symbols (`nm`-verified).
   Same treatment for its other imports (`__future__`, `typing`,
   `collections.abc`). This is exactly the masking gap the 2026-08-09
   entry documented — it just no longer hides any compile ERROR, only
   functionality. Fixing it means real per-module compilation of
   arbitrary sibling files into link mode (feature-sized, shared
   machinery) — not attempted.
2. **Runtime**: the binary starts and dies at deepfreeze's own
   `args = parser.parse_args(); verbose = args.verbose` with a runtime
   `AttributeError: verbose` — argparse's returned Namespace doesn't
   carry attributes readable by compiled dynamic-getattr yet. An
   ordinary-path runtime-support family, unrelated to compile failures.

No code change for THIS file; no gate run attributable to it beyond
those already run for the umarshal fixes (all green). Doc stays open,
reclassified as blocked on the two non-compile families above.


## Status (re-verified 2026-08-09): found + fixed a real, narrow, SEPARATE bug in this file's own code; the file's SHARED root cause (umarshal.py) is still open, now masked rather than fixed

Re-ran fresh against current master. Besides the shared `umarshal.py`
errors described below (unchanged, still open — see
`bugs/COMPILE_FAIL_Tools_build_umarshal.md`), this file has its OWN,
previously-undocumented, genuinely narrow bug (truncated out of the
2026-08-06 dump below, which cuts off after ~30 of ~3268 lines):

```
/Users/mrs/net/Python-3.14.6/Tools/build/deepfreeze.py:97:9: error: too many arguments to function 'mojo_max'; expected 1, have 2
```

at `analyze_character_width`'s `maxchar = max(maxchar, c)` (`maxchar`:
`char *`, `c`: bare `char`, from iterating a `str`). Root cause:
`_lower_call`'s min/max 2-arg ternary-fold fast path
(`gimple_codegen.py`, ~line 15568) only handles operands whose type is
in a fixed numeric-scalar set (`_NUM`); `char *`/`char` aren't in it,
so this call fell through to the generic call-expr path, which called
the real runtime's `mojo_max(void *args)` — a single-iterable-of-ints
signature — with 2 scalar args, a hard `-fgimple` "too many arguments"
error.

**Fixed** (narrow, self-contained, does not touch shared type-inference
machinery): added a second ternary-fold fast path, mirroring the
existing numeric one, for operands that are `char *` and/or bare
`char` (at least one must be `char *`) — using `mojo_cstr_cmp` for
real lexicographic string comparison (`<`/`>` directly on two `char *`
pointers would compare addresses, not content) and `mojo_char_to_str`
to normalize a bare `char` operand into a real 1-char string first,
mirroring the equality lowering's own identical `_to_char_star`
pattern immediately above it in the same file. Verified: this specific
error is gone from a fresh, independent (non-cached, direct
`gcc-mp-15 -fgimple`) compile of `deepfreeze.py`'s own generated code.

**Important caveat — do not read "`mojo.py build` reports success" as
this bug or the shared umarshal.py bug being fixed.** After this fix,
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Tools/build/
deepfreeze.py` does report `Built: ...` with 0 errors, reproducibly
(3 separate runs, including one with a fully isolated, empty
`GMOJO_HOME` to rule out a stale-cache false positive). But this is
NOT evidence the shared `umarshal.py` structural bug is fixed —
tracing `mojo.py build`'s actual dispatch (`mojo.py`'s `build`
handling) showed it tries `driver.compile_program` (`gimple_codegen.
compile_linked`, the newer "link mode" path — separately-compiled,
cached per-module dylibs) FIRST, falling back to the older, simpler
`build_executable`/`compile_to_gimple_cached(do_imports=True, ...)`
INLINING path only if `driver.compile_program` raises. Direct
instrumentation confirmed: with the fix in place, `compile_linked`
succeeds on its own (deepfreeze.py's own code no longer errors) and
the inlining fallback — the ONLY path that actually inlines and
compiles `umarshal.py`'s real body, and therefore the only path that
can surface `Reader._r_object`'s bug — is never reached at all.
Link mode's own import resolution (`_register_link_imports`/its
nested `_exports` helper, `gimple_codegen.py` ~line 5098) gracefully
degrades an import it can't resolve to a real dylib (confirmed by
reading its source: catches exceptions from `imports.resolve()` AND
`load_module()`, ultimately returning `({}, False, path)` — "treating
module as empty") rather than erroring. Confirmed empirically: the
built `deepfreeze` binary has ZERO `Reader`/`_r_object`/`umarshal`/
`loads` symbols (`nm`) or strings (`strings`) anywhere in it —
`import umarshal` and everything that depends on it (`umarshal.loads(
data)` at deepfreeze.py:476) is silently absent from the build, not
successfully compiled. Before this fix, deepfreeze.py's OWN `max()`
bug broke `compile_linked`'s compile of deepfreeze.py's own code,
forcing the fallback to the inlining path — which is why umarshal.py's
errors were directly visible in this doc's original 2026-08-06 dump
below. So the fix here (a) is real and worth keeping, but (b)
incidentally causes this file to stop exercising (and therefore stop
correctly reporting) the still-broken shared dependency, via an
unrelated, orthogonal masking gap in link mode's import-resolution
fallback. Leaving this doc open rather than deleting it — the
underlying compile-correctness problem (this file's actual behavior
depends on `umarshal.loads()`, which is silently missing from the
built binary) is not resolved, it's just no longer visible as a build
error. `bugs/COMPILE_FAIL_Tools_build_umarshal.md` (unchanged, still
open) remains the reliable, honest repro of the shared root cause —
compile `umarshal.py` directly as the entry file, which always goes
through the real inlining path.

## Status (updated 2026-08-06)

Re-ran; current error is entirely in a transitively-imported sibling:

```
error: 'MojoList' has no member named 'co_argcount'
error: 'MojoList' has no member named 'co_posonlyargcount'
... (one per Code field)
```

Same root cause as `bugs/COMPILE_FAIL_Tools_build_umarshal.md`
(`deepfreeze.py` imports `umarshal.py`): `Reader._r_object`'s big
`if/elif` type-tag dispatch reuses one local variable `retval` across
branches holding structurally different real types; the `Type.CODE`
branch's `retval` loses its `Code *` identity to whatever the
unification across all branches picks (`MojoList *`). Not fixed here
— see that doc for the fuller trace and why a real fix needs per-branch
local retyping rather than a narrow patch. Nothing specific to
`deepfreeze.py` itself was found.

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Code':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:71:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   71 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Reader':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:85:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   85 | class Reader:
      | ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'umarshal_Code___init__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:52:13: error: 'Code' has no member named '__dict__'
   52 |         self.__dict__.update(kwds)
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:174:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  174 |         old_level = self.level
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:172:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
  172 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:171:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
  171 |         return obj
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'umarshal_Code___repr__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:55:13: error: 'Code' has no member named '__dict__'
   55 |         return f"Code(**{self.__dict__})"
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |                 varnames.append(name)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'umarshal_Code_get_localsplus_names':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:75:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   75 | 
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:73:11: warning: variable '_t13' set but not used [-Wunused-but-set-variable]
   73 |     def co_cellvars(self) -> tuple[str, ...]:
      |           ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:72:10: warning: variable '_t12' set but not used [-Wunused-but-set-variable]
   72 |     @property
      |          ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:71:11: warning: variable '_t11' set but not used [-Wunused-but-set-variable]
   71 | 
      |           ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:70:14: warning: variable '_t10' set but not used [-Wunused-but-set-variable]
   70 |         return self.get_localsplus_names(CO_FAST_LOCAL)
      |              ^~~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:69:10: warning: variable '_t9' set but not used [-Wunused-but-set-variable]
   69 |     def co_varnames(self) -> tuple[str, ...]:
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:68:10: warning: variable '_t8' set but not used [-Wunused-but-set-variable]
   68 |     @property
... (3268 more lines)
```

Exit code: 1
Elapsed: 14.17s
