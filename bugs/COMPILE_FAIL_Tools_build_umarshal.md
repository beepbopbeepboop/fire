# COMPILE_FAIL: Tools/build/umarshal.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (re-verified 2026-08-26, worktree-agent-a01a24fff53233531 @ master `43fb291`): unchanged, build still exits 0

Fresh `python3 mojo.py build .../Tools/build/umarshal.py` against this
worktree (fast-forwarded to master `43fb291`): `Built: .../umarshal`,
exit 0. All 17 prior compile errors remain fixed; the file stays
compile-RESOLVED. Runtime death remains purely the documented stubbed
marshal/pprint C-extension dependency chain (self-test only), not a
codegen defect. Not attempted further; no code change.

## Status (re-verified 2026-08-26, wtOpencode_genlib3): still exits 0; runtime death precisely located at loads()'s own assert on stubbed-marshal output

Fresh `python3 mojo.py build` against current master (f0f6e78):
**exits 0**, binary built in ~71s. Running it crashes with SIGTRAP and
zero output — lldb pinpoints frame #0 at umarshal.py:304,
`assert isinstance(data, bytes)` inside `loads()`: main()'s self-test
calls stubbed `marshal.dumps(sample)` (compiled mode emits
"unavailable in compiled mode" stubs for marshal/pprint), feeds its
garbage return to `loads()`, and the function's own bytes-check trap
fires. This confirms, with the exact instruction, that the runtime
death is purely the documented stubbed-C-extension dependency chain —
no codegen defect involved; every compile-side fix from the 2026-08-25
entry below holds. Doc remains compile-RESOLVED / runtime-blocked-on-
stubs.

## Status (updated 2026-08-25, worktree fix/opencode-group2 — ALL 17 compile errors FIXED via a shared root cause; `mojo.py build` now EXITS 0; runtime reaches the self-test but depends on stubbed C-extension modules)

Re-verified fresh: the 16 `'MojoList' has no member named 'co_*'`
errors AND the `'main' undeclared here` error are all GONE —
`python3 mojo.py build .../Tools/build/umarshal.py` now **exits 0**
(verified twice, second run after clearing stale CAS entries). Two
real fixes in shared compiler source (commit `cb85bf6`), both narrower
than the "per-branch retyping vs dynamic-dispatch routing" dilemma this
doc's 2026-08-09 entry posed — because option (b) turned out to have an
existing, general mechanism to plug into:

1. **Missing-member writes now route through dynamic dispatch.**
   `_gen_stmt_AssignStmt`'s member-write tail emitted `ov->member = val`
   unconditionally for any struct-pointer receiver, hard-erroring
   whenever the declared type lost a cross-branch unification (exactly
   this doc's retval/MojoList* case). It now checks: if the receiver's
   struct is KNOWN but lacks the member, or the receiver is a
   container/opaque pointer that is no user struct at all (`MojoList *`
   etc.), emit `_mojo_dispatch_setattr(obj, "member", val)` instead —
   the SAME runtime dispatch the fully-opaque-receiver branch right
   above already uses. At runtime the dispatch reads the object's REAL
   type tag, so when the Type.CODE branch executes with retval actually
   holding a tagged `Code` instance, every `co_*` write lands in Code's
   real storage; on any other branch's runtime type it degrades exactly
   like Python attribute assignment on an arbitrary object. This is the
   2026-08-09 entry's own option (b), realized through the existing
   machinery rather than new per-branch variable machinery — and it is
   fully general for every future "one local, many branch shapes"
   function.
2. **The `'main' undeclared here` error**: umarshal's `def main()` is
   renamed `_gimple_main` (entry-point convention), so the funcptr-table
   initializer `(void *)main` (from `sample2 = main.__code__`) referenced
   the generated C entrypoint with NO prior declaration. The funcptr
   emitter now declares `int main(int, const char **);` up front when
   its target set contains the entrypoint name.

**Runtime status, verified honestly**: the built binary starts and runs
into main()'s own self-test, then dies — because the self-test
(`marshal.dumps(sample)` round-tripped through `loads()`) depends on
CPython's `marshal` and `pprint` C modules, which compiled mode only
stubs ("unavailable in compiled mode"). That is not a compile-stage gap
and not reachable by compiler codegen: real marshal data would come from
the CPython build process, and `loads()` itself (this file's actual
purpose) compiles fully. Full mandatory gate for both fixes:
test_gimple.py 256/256, test_module_cache.py 76/76, generator runner
53/53, async runner 38/38, make check-selfhost clean, from-scratch
stdlib dylib rebuild EXIT=0 / 0 skips.

See the deepfreeze doc's matching 2026-08-25 entry for how this changes
THAT file's picture (build exits 0 there too, but link mode still
treats the non-stdlib sibling `import umarshal` as an empty module).


## Status (re-verified 2026-08-09): still genuinely broken, root cause now fully traced — confirmed structural

Re-ran fresh against current master (`python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py`): still fails,
17 errors — the 16 `'MojoList' has no member named 'co_*'` errors
below reproduce identically (the old `'Code' has no member named
'__dict__'` error from the 2026-08-06 dump below is GONE, fixed by
unrelated prior work; a separate `'main' undeclared here (not in a
function)` error at line 666 is new/unrelated — a bare top-level
`if __name__ == "__main__": main()` calling a `main()` defined only
inside that same `if` block, a distinct, narrow, NOT investigated
here). Also confirmed via a fully independent, non-cached path: wrote
the freshly-generated `.ci` to a `.c` file and compiled it directly
with the real toolchain (`/opt/local/bin/gcc-mp-15 -fgimple -fPIC
-Iruntime -c`, bypassing `mojo.py`/CAS entirely) — same 17 errors,
ruling out any caching artifact.

**Root cause, now precisely traced** (previous update below said "not
fully traced to the exact unification code site" — it's now fully
traced, confirming the "not a narrow patch" conclusion rather than
resolving it):

`_infer_local_var_types` (`gimple_codegen.py`, the whole-function
if/elif-aware pre-pass) DOES correctly scan every branch of `_r_object`'s
big `if/elif` chain and estimate `retval`'s type per branch via
`_quick_type` — but `_quick_type` has no special case for a bare
`tuple(...)` call (unlike `list()`/`dict()`/`set()`, which its
`_BUILTIN_CTORS` dict does recognize), so it falls through to
`func_return_types.get('tuple', 'int64_t')` = `'int64_t'`. Every other
branch (`R_REF([])`, `R_REF({})`, `R_REF(set())`, `R_REF(Code())`,
`self.refs[n]`) also estimates `int64_t` (their real boxed
representation). So this pre-pass's own `TypeLattice.join_all(...)`
correctly (if uselessly) computes `retval`'s type as `int64_t` for
the whole function — confirmed by direct instrumentation, all 4
compiles of this function within one build print `types=['int64_t',
...] joined='int64_t'`.

The ACTUAL declared C type ends up `MojoList *` anyway, via a
COMPLETELY SEPARATE mechanism: `_gen_stmt_AssignStmt` (~line 17852),
when a target isn't yet in `var_types`, starts from that `int64_t`
pre-pass hint but then has a "trust ground truth" override (~line
17886): `if ctype in ('int', 'int64_t') and vtype not in ('int',
'int64_t') and vtype.endswith('*'): ctype = vtype` — i.e. if the
ACTUAL lowered type of THIS SPECIFIC assignment's RHS is a real
pointer, trust that over the (wrong/generic) pre-pass hint. This
override exists for a legitimate, different bug (see
`bugs/CODEGEN_untyped_param_string_passthrough_wrong.md`-style cases:
an unannotated callee's return type only becomes known correctly
later). `retval`'s FIRST textual assignment in `_r_object` is the
`Type.SMALL_TUPLE` branch, `retval: Any = tuple(self.r_object() for
_ in range(n))` — and `tuple(...)`'s REAL lowering (not `_quick_type`'s
estimate) goes through `_lower_builtin_list` (`fname_raw in ('list',
'tuple')`, ~line 14159), which genuinely constructs and returns a real
`MojoList *`. So the override fires on this very first assignment,
`_declare_var('retval', 'MojoList *')` locks the declaration
permanently (`_declare_var` is a no-op once a name is in `var_types`),
and every LATER branch's differently-shaped boxed `int64_t` value
(from `R_REF(Code())`, `R_REF([])`, etc.) gets forcibly
`(MojoList *)`-cast at its own assignment to match — confirmed
directly in the generated `.ci`: `retval = _t132;` (the tuple's real
`MojoList *`, no cast) followed later by `retval = (MojoList
*)_t208;` etc. for every other branch. By the time the `Type.CODE`
branch's `retval.co_argcount = ...` runs, `retval` is unconditionally
`MojoList *`, which genuinely has no such member — a hard, correct
GCC error, not a subtler runtime bug.

This confirms the prior update's guess (`TypeLattice.join`'s "two
different pointer types → opaque int64_t handle" rule can't even
explain the specific `MojoList *` outcome by itself — it's this
`_gen_stmt_AssignStmt`-level "first real assignment wins, permanently"
behavior, layered on top of a whole-function pre-pass whose OWN
estimate was already coincidentally int64_t for every branch and thus
never got a chance to matter).

**Confirmed structural, not narrow-fixable**: neither half of this is
a safe, narrow patch.
- Reverting/narrowing the `_gen_stmt_AssignStmt` "trust ground truth"
  override would resurrect the (different, real) bug it was added to
  fix.
- Even fixing `_quick_type`'s `tuple(...)` blind spot (to match
  `_lower_builtin_list`'s real `MojoList *`) would NOT fix this: the
  whole-function pre-pass would then ALSO conclude `MojoList *` for
  `retval` (via `TypeLattice.join`'s "one pointer, one non-pointer →
  use the pointer type" rule joining `MojoList *` against the other
  branches' `int64_t` estimates) — same wrong answer, just reached
  through the "official" path instead of the override.
- The real, correct fix needs either (a) genuine per-branch local
  retyping — a fresh C variable per structurally-incompatible branch
  instead of one shared `retval` declaration for the whole function
  (a real decomposition of `_infer_local_var_types`'s single-type-per-
  name model), or (b) always routing a `self.__dict__.update(kwds)`-
  style dynamic-attrs class's field reads/writes (`Code` here) through
  this codebase's existing runtime dynamic-dispatch mechanism
  (`_mojo_dispatch_setattr`/`_mojo_dispatch_getattr` — the compiler DOES
  already generate these for `Code`, confirmed via unused-function
  warnings in the standalone build's own gcc output, but the
  `Type.CODE` branch's `retval.co_argcount = ...` codegen site doesn't
  route through them, using the ordinary static-struct-field/
  type-inferred path instead). Both are real, broad, shared-machinery
  changes — out of scope for a narrow patch, matching this project's
  own documented history of narrow-looking fixes to shared type-
  inference/call-lowering machinery causing broad silent regressions.
  Not attempted here.

See `bugs/COMPILE_FAIL_Tools_build_deepfreeze.md` for an important,
separate finding: that file's OWN direct compile bug (unrelated,
narrow, `max()`/`min()` on mixed `char`/`char *` args) IS fixed there,
but `python3 mojo.py build` now reports overall success for
`deepfreeze.py` NOT because this bug got fixed — `mojo.py build`'s
primary "link mode" path (`driver.compile_program`) silently drops
`deepfreeze.py`'s `import umarshal` as an unresolvable sibling
dependency (confirmed: the built binary has zero `Reader`/`_r_object`/
`umarshal`/`loads` symbols or strings) rather than actually compiling
it, so this bug is masked there, not resolved. Standalone
(`umarshal.py` as the entry file, which DOES inline-compile the real
body) remains the reliable repro and reproduces this bug consistently.

## Status (updated 2026-08-06)

Re-ran; current error:

```
error: 'MojoList' has no member named 'co_argcount'
error: 'MojoList' has no member named 'co_posonlyargcount'
... (one per Code field)
```

at `Reader._r_object`'s `Type.CODE` branch:
```python
elif type == Type.CODE:
    retval = R_REF(Code())
    retval.co_argcount = self.r_long()
    ...
```

Root-caused (partially): `_r_object` is a large `if/elif` chain over a
type tag byte, reusing the SAME local variable `retval` to hold a
completely different real type per branch (`int`, `str`, `list`, `set`,
`frozenset`, `Code`, ...). This codegen has no real union/variant local
type — it must pick ONE declared C type for `retval` across the WHOLE
function, and confirmed via the generated `.ci` that `R_REF` itself
(a locally-nested closure: `def R_REF(obj: Any) -> Any: ... return
obj`) is correctly boxed generic (`int64_t Reader__r_object_R_REF
(Reader__r_object_R_REF_env *, int64_t)` — takes and returns a boxed
value, not the bug). The bug is downstream: whatever unifies `retval`'s
declared type across this function's many branches picks `MojoList *`
(plausibly because an earlier/other branch assigns a genuine list/
set-shaped value to the same `retval` name, and the unification logic
joins to that rather than treating each branch as needing per-use
narrowing), losing the `Code *` identity by the time the `Type.CODE`
branch's own `retval.co_argcount = ...` field writes run.

Not fully traced to the exact unification code site (this is LOCAL
variable type inference across if/elif branches sharing one name — not
one of this session's three explicitly-flagged highest-risk categories,
but clearly adjacent/related machinery). Not fixed here given the time
this session had left; a real fix likely needs per-branch local
retyping (a fresh C variable per branch instead of one shared `retval`
declaration) rather than a narrow patch.

`bugs/COMPILE_FAIL_Tools_build_deepfreeze.md` shares this exact root
cause (transitively imports this file).

```
Compilation failed: cc1: note: '-g3' is not supported by the debug linker in use (set to 2)
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Code':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:105:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  105 |     def r_short(self) -> int:
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function '_alloc_Reader':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:119:1: warning: label 'bb_2' defined but not used [-Wunused-label]
  119 |         return x
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'Code___init__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:52:13: error: 'Code' has no member named '__dict__'
   52 |         self.__dict__.update(kwds)
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:347:1: warning: label 'bb_2' defined but not used [-Wunused-label]
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:345:11: warning: variable '_t2' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:344:10: warning: variable '_t1' set but not used [-Wunused-but-set-variable]
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'Code___repr__':
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:55:13: error: 'Code' has no member named '__dict__'
   55 |         return f"Code(**{self.__dict__})"
      |             ^~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:65:1: warning: label 'bb_2' defined but not used [-Wunused-label]
   65 |                 varnames.append(name)
      | ^   
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py: In function 'Code_get_localsplus_names':
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
      |          ^~~
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:67:11: warning: variable '_t7' set but not used [-Wunused-but-set-variable]
   67 | 
      |           ^  
/Users/mrs/net/Python-3.14.6/Tools/build/umarshal.py:66:10: warning: variable '_t6' set but not used [-Wunused-but-set-variable]
   66 |         return tuple(varnames)
... (1836 more lines)
```

Exit code: 1
Elapsed: 13.15s
