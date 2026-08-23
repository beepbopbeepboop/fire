# HARD BUG: compiled-generator free-function C symbols are never module-qualified, so two modules' same-named generators collide at compile

## Status (updated 2026-08-07)

**REOPENED 2026-08-23 (REGRESSED, different failure mode)**: this doc's
own minimal repro (a.mojo/b.mojo each with a top-level `walk`, main.mojo
importing both — the exact shape the 2026-08-07 verification ran
end-to-end clean with correct interleaved output) now FAILS to build:
`main.mojo:6:9: error: too many arguments to function 'a_walk'; expected
0, have 1` and `main.mojo:8:10: error: too many arguments to function
'b_walk'; expected 0, have 4` (RC=1). The ORIGINAL symptom this fix
addressed is genuinely gone (no `_mojogen_walk_start` conflicting-types
errors; symbols ARE module-qualified now) — but the call sites lower the
imported generators as ORDINARY qualified functions (`a_walk`/`b_walk`,
the SB-1 free-function convention) instead of routing through the
compiled-generator `_mojogen_*_start` delegation, and no arity is
registered for them cross-module ("expected 0"). This is adjacent to the
doc's own documented residual ("compiled generator support through
do_imports=True ... never worked at all for a generator reached only via
import") but strictly worse than the verified-fixed 2026-08-07 state,
where THIS exact direct-import repro built AND ran. Confirmed NOT caused
by concurrent perf work: identical failure with all working-tree changes
stashed. Fresh evidence recorded; root cause of the new call-site
routing not yet bisected (432 commits since 76e820e); fix not attempted
in this pass.

**FIXED** (task #146), scoped narrowly per the "Why a fix needs care"
analysis below — root-caused 2026-08-06 while classifying the
`CODEGEN_generator_function_Lib_*.md` cluster (tasks #95-135), fixed
2026-08-07.

`_gen_cpp_generator_unit`'s free-function `base` computation now calls
`self._func_qualifier(fn.name)` — the SAME, already-proven SB-1
machinery ordinary free functions use via `_func_csym` — exactly
mirroring the existing pattern rather than inventing a new one, as this
task's own framing suggested. `fn.name` at this call site is always one
of the currently-compiling module's own top-level FunctionDefs (both
callers iterate `stmts`/`_generator_fns`, themselves scoped to the
module gen_module() is currently processing), so tier 1 of
`_func_qualifier` (`_local_top_level_func_names`, purely per-instance,
never shared-dict-dependent) always fires — the same "always
authoritative for itself" guarantee ordinary functions already rely on.

**Scope decision**: this fix deliberately does NOT touch call-site
resolution (`self._generator_api[fname_raw]` — the ~11 read sites
throughout this file). Investigation found this is unnecessary for the
confirmed real-world case: `os.py`'s `walk` and the unrelated `walk`
reachable via `threading.py` never call each other (confirmed: "both
free functions in different files, no relation to each other"), and
every one of the ~11 call-site reads does exactly ONE `self.
_generator_api[fname_raw]` lookup, reused for both the extern "C"
forward-declaration/param-types registration AND the actual call
emission — so whatever that single dict read returns is automatically
self-consistent at its own call site, regardless of qualification.
Making `_gen_cpp_generator_unit`'s free-function base qualified is
therefore sufficient on its own to eliminate the reported "conflicting
types" collision; it does not need the call-site fix SB-1's own history
needed (that one was necessary because ordinary-function call sites
recompute their OWN qualifier independently at each use, creating a
cross-site-disagreement risk generators' single-dict-read-per-site
architecture doesn't have for the collision case that's actually
occurred in the wild).

The known, NOT-fixed-here residual: `self._generator_api` is still a
single dict shared (by object identity, `temp_gen._generator_api =
self._generator_api`) across every nested temp_gen in a `do_imports=
True` whole-program compile, keyed by bare function name — so a
CROSS-MODULE generator call (module A calling module B's same-bare-
name generator while a third module's own same-name generator is also
in scope) remains the same class of documented, accepted "first-
registered-module-wins" limitation `_imported_func_home`'s own
docstring already carries for ordinary functions (tier 3). Not
exercised by any confirmed repro; not attempted here, per this bug's
own preference for a narrowly-verified fix over a speculative,
higher-risk rework of call-site resolution across ~11 sites with no
concrete case forcing it.

## Verification

Hand-built minimal repro (two sibling `.mojo` files each with a
top-level generator literally named `walk`, differing signatures,
mirroring this doc's own "Minimal repro sketch"): confirmed the EXACT
`error: conflicting types for '_mojogen_walk_start'` reproduces via
`python3 mojo.py build main.mojo` on unfixed code, and is GONE (clean
build, exit 0, runs and produces correct interleaved output) after this
fix, for the direct-import (non-wrapper-indirection) shape.

**Found while verifying, explicitly OUT OF SCOPE for this bug**: a
wrapper-module variant of the same repro (mirroring test_module_cache.
py's `test_sb1_mojo_build_cli_wrapper_modules` SB-1 CLI-test shape)
still fails to LINK (`Undefined symbols ... __mojogen_mod_a_walk_start`)
— but this is a pre-existing, unrelated gap: confirmed via `git stash`
that the IDENTICAL wrapper-module shape ALSO fails to link on unfixed
master even with NO naming collision at all (a solo, uniquely-named
generator imported through one wrapper module already fails to link
today). Compiled generator support through `do_imports=True`'s
wrapper-module/multi-file-inlining path appears to have never worked at
all for a generator reached only via import (as opposed to defined
directly in the file being built) — a separate, broader gap than "the
symbol isn't qualified," worth its own hard-bug doc in a future session,
not attempted here.

## Gate

All five gates in CLAUDE.md's quality-gate section passed: `test_gimple.
py` (247/247), `test_module_cache.py` (76/76), `make check-selfhost`
clean, from-scratch `libmojostdlib.dylib` rebuild (0 `skip <module>:`
lines), `compile_stdlib.py -j8` (664/664, 0 unexpected — unchanged
count).

## Original diagnosis (unfixed-era notes, kept for history)

Not attempted at the time — see "Why a fix needs care" below; this
touches the same general symbol-naming area as the already-landed SB-1
fix (`bf96f55`/`13e6a5c`, "Module-qualify free-function C symbols to
fix SB-1 overload collisions"), and that project's own history shows
two rounds of real regressions from a first, confident-looking fix, so
a parallel change to the *generator* naming scheme deserved the same
care (its own dedicated verification pass), not a quick copy-paste.

## Symptom

```
$ python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py
...
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py:1208:23: error: conflicting types for '_mojogen_walk_start'; have 'MojoGenerator *(int64_t,  int64_t,  int64_t,  int64_t)' {aka 'MojoGenerator *(long long int,  long long int,  long long int,  long long int)'}
/Users/mrs/net/Python-3.14.6/Lib/threading.py:2160:23: note: previous declaration of '_mojogen_walk_start' with type 'MojoGenerator *(int64_t)' {aka 'MojoGenerator *(long long int)'}
/Users/mrs/net/Python-3.14.6/Lib/os.py:1553:23: error: conflicting types for '_mojogen_walk_start'; have 'MojoGenerator *(int64_t,  int64_t,  int64_t,  int64_t)' {aka 'MojoGenerator *(long long int,  long long int,  long long int,  long long int)'}
/Users/mrs/net/Python-3.14.6/Lib/threading.py:2160:23: note: previous declaration of '_mojogen_walk_start' with type 'MojoGenerator *(int64_t)' {aka 'MojoGenerator *(long long int)'}
/Users/mrs/net/Python-3.14.6/Lib/genericpath.py:467:23: error: conflicting types for '_mojogen_walk_start'; ...
/Users/mrs/net/Python-3.14.6/Lib/ntpath.py:4133:23: error: conflicting types for '_mojogen_walk_start'; ...
```

`os.py`'s own top-level generator function `walk` (4 params: `top,
topdown, onerror, followlinks`) and some unrelated generator ALSO named
`walk` reachable via `threading.py` (1 param) — both free functions in
different files, no relation to each other — both mangle to the exact
same bare C symbol `_mojogen_walk_start`, and every subsequent module in
the transitive closure that also reaches either one re-declares the same
symbol with the OTHER module's signature, producing GCC "conflicting
types" hard errors that make the whole-program compile fail.

## Root cause

`GimpleGen._gen_cpp_generator_unit` (`gimple_codegen.py`, the method that
translates one supported generator `FunctionDef` into its C++20 coroutine
fragment) computes its own 4-function extern "C" API's base name as:

```python
base = (f"_mojogen_{_safe_name(struct_name)}_{_safe_name(fn.name)}"
        if struct_name is not None else f"_mojogen_{_safe_name(fn.name)}")
```

For a generator **method** (`struct_name is not None`), the base
includes the struct name, which — same as an ordinary compiled method —
gets whatever module-qualification the struct's own name already
received (via `_struct_method_qualifier`, from the SB-1-adjacent struct
work). But for a **free-function** generator, `struct_name` is `None` and
the base is JUST `_mojogen_{fn.name}` — the function's own bare name,
with **no module qualifier applied at all**, unlike every ordinary
(non-generator) free function's C symbol, which since `bf96f55` goes
through `_func_csym`/`_func_qualifier` specifically to prevent this exact
collision shape (SB-1: "two modules' same-named free-function overloads
... collided at link").

The SB-1 fix's own module-qualification machinery
(`_func_qualifier`/`_imported_func_home`/`_own_imported_func_home`) was
never extended to cover the generator-coroutine naming convention
(`_mojogen_<name>_start`/`_resume`/`_value`/`_destroy`) — that whole
4-function API is generated by a structurally separate code path
(`_gen_cpp_generator_unit`, part of the newer C++20-coroutine codegen
project) that predates, and was never revisited after, the SB-1 fix
landed for ordinary functions.

## Why this is a distinct, high-value finding for this cluster

It's easy to assume every `CODEGEN_generator_function_Lib_*` failure is
about the coroutine .cpp itself failing to *compile* the generator's
*body* (the 5-bullet cluster already documented for `dyld.py`'s generator
functions — untyped params, undeclared sibling calls, missing
begin()/end(), unresolved module attributes, string methods on a
mistyped param). This is different: `walk`'s own body compiles FINE on
each side — the failure is a pure **naming collision** between two
completely unrelated generator functions that happen to share a bare
name, exactly the same failure shape SB-1 already fixed for ordinary
functions. `walk`/`items`/`values`/`keys`/`__iter__`/`run` are all common
enough generator names in real Python that this is likely to recur across
many files in the wider stdlib corpus, not just `os.py`.

## Why a fix needs care

A naive fix (thread `_func_qualifier`'s result into `_gen_cpp_generator_
unit`'s `base` computation for the `struct_name is None` case) sounds
narrow, but the SB-1 history (`13e6a5c`) shows the qualification
machinery itself has subtle correctness traps specific to `do_imports=
True` whole-program compiles:
- A locally-defined generator must be qualified with the COMPILING
  module's own name; an imported reference must independently resolve
  its TRUE home module (`_imported_func_home`), and the two call sites
  (definition in `_gen_cpp_generator_unit`, forward-declaration/call-site
  lowering wherever `<base>_start`/`_resume`/`_value`/`_destroy` are
  referenced — at least `_lower_call`'s generator-call branch, and
  `_quick_type`'s `self._generator_api` branch) must all agree on the
  exact same qualified name, or the call site links against a
  DIFFERENTLY-qualified symbol than the one actually emitted (the "silent
  miscompile" class of bug `13e6a5c` found and fixed for the ordinary-
  function case).
- The generator API's qualifier also needs to be consistent between the
  `.c`/`.ci` side (which only ever sees the OPAQUE extern "C" declarations
  of `<base>_start` etc.) and the `.cpp` side (which defines them) — two
  independently-maintained emission sites, same as the struct-typedef
  duplication `_gen_cpp_generator_unit`'s own docstring already calls out
  as a correctness-sensitive seam.
- `self._generator_api`/`self._supported_generators` (keyed by BARE
  function name today, e.g. `self._generator_api['walk']`) would also
  need to become collision-aware — two different `walk` generators
  currently silently overwrite each other's entry in these dicts even
  BEFORE reaching the C symbol-naming stage, which is arguably an even
  more fundamental instance of the same "keyed by bare name" root cause
  and needs to be part of any real fix's scope, not just the emitted
  symbol text.

Given the two-regression history of the analogous ordinary-function fix
and this session's standing guidance to avoid unverified changes to
shared naming/inference machinery, this is left fully diagnosed but
unfixed for a future dedicated session with room for the same "direct
CLI-driven verification, not just the unit test suite" rigor `13e6a5c`
used.

## Repro

Real: `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/os.py` (any
of `Lib/subprocess.py`, `Lib/genericpath.py`, `Lib/ntpath.py` also
transitively hit it, since all reach both `os.py`'s `walk` and
`threading.py`'s unrelated `walk` generator in the same whole-program
compile).

Minimal repro sketch (not yet hand-verified in isolation, but follows
directly from the root cause above and mirrors `bf96f55`'s own SB-1
free-function repro shape):

```python
# a.mojo
def walk(top):
    yield top

# b.mojo
def walk(top, topdown, onerror, followlinks):
    yield top
    yield topdown

# main.mojo
from a import walk as walk_a
from b import walk as walk_b
def main():
    for x in walk_a("x"):
        print(x)
    for x in walk_b("x", True, None, False):
        print(x)
main()
```

Expected: both compile and link distinctly. Actual (predicted from the
root cause, not yet run): `_mojogen_walk_start` conflicting-types error
identical in shape to the real `os.py`/`threading.py` case.
