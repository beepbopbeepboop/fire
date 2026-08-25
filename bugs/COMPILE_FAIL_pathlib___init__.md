# COMPILE_FAIL: Lib/pathlib/__init__.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/pathlib/__init__.py`

## Status (updated 2026-08-24, worktree fix/rest-remainder — the `'os' was not declared` coroutine-body error (from the 2026-08-23 entry below) is ALSO fixed by this session's module-attribute-value fix; several OTHER, unrelated .cpp errors remain in the same generators)

This session's `_cpp_expr` MemberExpr fix (see `bugs/CODEGEN_generator_
function_Lib_test_test_dbm.md`'s 2026-08-24 entry) covers this file's
own trigger too: `Path.walk`'s `follow_symlinks = os._walk_symlinks_as_
files` (a module-import name read as a bare attribute VALUE). Verified
via a fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` +
`g++-mp-15 -std=c++20 -fsyntax-only`: `'os' was not declared` no longer
appears anywhere in the output.

The file is nowhere close to building even so — several OTHER,
unrelated, pre-existing `.cpp`-stage errors remain in the SAME two
generators (`Path._filter_trailing_slash`, `Path.walk`), all distinct
from this fix and not attempted: `self->parser.sep` accessed through a
field typed plain `int` (the "field-under-widening" family the
2026-08-23 entry below already names); an `anchor_len` local cast from
a `std::function<int64_t()>` bound-method-value wrapper straight to
`int64_t` (invalid cast — the callable needs to be INVOKED, not
reinterpreted); a pointer-vs-int64_t comparison and a `char*`-to-
`int64_t` conversion downstream of the same untyped chain; and a tuple-
target redeclaration conflict (`path_str` declared once as `char *`,
then again as `int64_t` a few lines later in the same function, from
`Path.walk`'s tuple-unpacking machinery disagreeing with an earlier
declaration). None of these were investigated further this session —
each looks like its own narrow-but-real gap, but chasing them wasn't
this fix's purpose.

Full mandatory gate for the underlying fix: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild EXIT=0 with 0 skip lines (see the dbm doc's entry
for the shared gate run).

Doc stays open — file still does not build.


## Status (updated 2026-08-23, wt09 fix/stdlib-mods `de9b885` — GIMPLE stage now passes; PARTIAL progress, file still doesn't build)

Root-caused the then-current blocker (6x GCC `type mismatch in binary
expression`, `int = int64_t + int64_t`, all pointing at
`PurePath.anchor`'s `return self.drive + self.root`) and FIXED it at its
own level:

`PurePath.drive`/`.root` are `@property` getters whose statically
inferred C return type is plain `int` (their `self._drv`/`self._root`
fields get typed `int` by `_collect_self_assigns`' MultiAssignStmt case,
gimple_module_gen.py — `self._drv, self._root, self._tail_cached =
self._parse_path(...)` types every target `'int'` without consulting the
value). At emission, `self.drive` lowers to a deferred MojoBoundMethod*
that the BinaryOp path auto-invokes via `mojo_bound_method_call_0` (an
int64_t-valued call) — but the auto-invoke sites CLAIMED the recorded
static type (`'int'`) for the operand while handing callers the raw
int64_t temp. The enclosing add therefore emitted `int _t10 = int64_t +
int64_t`, which `-fgimple` rejects outright.

Fix (gimple_gen_methods.py `_auto_invoke_bound_method_value`, replacing
three identical copies in _lower_MemberExpr's chained-member path,
_lower_binary's operand path, and _lower_subscript): when the inferred
return type is anything other than int64_t, materialize a correctly-
typed temp with an explicit cast before claiming that type. With this,
the ENTIRE GIMPLE (.ci) stage of pathlib compiles clean.

**The file still does not build** — it now reaches the further C++
generator stage (`__init___gen.cpp`) and fails there on the SAME
coroutine-emitter gaps the 2026-08-10 status below already documented:
`'os' was not declared in this scope` inside `walk`'s body, plus new
sibling instances surfaced by the progress (a `self->Path::parser` field
read typed `int` used as `.sep` receiver, an f-string/char* vs int64_t
conflict for `path_str`). Those are all in the coroutine-body `_cpp_expr`
emitter (no module-call dispatch, no string-method dispatch) plus the
same field-under-widening family above feeding generator bodies — not
re-attempted here; the tuple-yield fix below remains landed and intact.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a separate, pre-existing gap now blocks)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes` — the design note in the 2026-08-09 section below, "making
tuple-valued yields actually compile needs a new value-representation
category," is exactly what landed: a tuple is boxed into the SAME
`MojoList *` representation an ordinary compiled tuple literal already
uses, and `MojoList *` was already a supported `co_yield` scalar
payload, so the promise type itself needed no redesign). Confirmed via
an isolated compile: `Path.walk()`'s `yield path, dirnames, filenames`
is no longer refused, and its own tuple-boxing/`co_yield` text is
syntactically valid C++ (`dirnames`/`filenames`, both lists, correctly
box into the generic non-string-pointer bucket, the same convention
this codegen already uses for any non-`char*` pointer stored in a list
slot).

**pathlib/__init__.py still does not build**, blocked by an
INDEPENDENT, pre-existing gap earlier in the SAME method: an
`os.<call>(...)` module-attribute call inside `walk`'s body has no
lowering in the coroutine-body expression emitter — g++: "'os' was not
declared in this scope". Unrelated to tuple-yield. This is the SAME
tuple-yield structural gap independently confirmed in `save_env.py`/
`test_exception_group.py`/`randdec.py` (cited below) — those 3 (plus
this file) are now all past that specific gate; this doc's "why not
fixed" section below (structural, feature-sized) no longer describes
the current blocker, but a real fix WAS landed this session for the
narrower tuple-yield mechanism it describes. Doc kept open (not
deleted) — this file genuinely still doesn't build.

## Status (updated 2026-08-09 — re-verified against current master, same
## structural gap, reference doc corrected)

Re-ran `python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/pathlib/
__init__.py` fresh against current master. Identical failure to the
2026-08-07 status below — still, and only, this:

```
Error building: cannot compile module: function(s) walk (generator
function(s), contain a `yield`/`yield from`) — this codegen compiles
every function into a single straight-line C function and has no
suspend/resume state-machine transform for generators, nor an event
loop / suspend-resume codegen for async functions, yet, so these
cannot be represented as compiled C without emitting silently wrong or
broken code; falling back to interpreting this module from source
instead
```

With `MOJO_DEBUG=1`, the underlying refusal is precise:
```
[gimple_codegen] generator method Path.'walk' not eligible for C++
coroutine path, falling back to honest refusal: walk: every `yield`
must carry a value, and all values must agree on one scalar type
(int64_t/double/_Bool)
```

**Root cause, precisely** (corrected from the 2026-08-07 status, which
pointed at a now-deleted doc, `bugs/hard/
CODEGEN_generator_struct_typed_param_refused.md` — that doc no longer
exists in this tree, and its title doesn't match this shape anyway):
`Path.walk()` does `yield path, dirnames, filenames` — a 3-element
TUPLE yield, not a struct-typed-parameter issue. `gimple_codegen.py`'s
`_generator_yield_ctype` (~line 2647) has a deliberate, documented
`if isinstance(n.value, TupleExpr): return None` early-out in its
YieldExpr case specifically to refuse multi-element tuple yields
honestly (propagating "unsupported" to `_gen_cpp_generator_unit`'s
`if value_ctype is None: raise _UnsupportedGeneratorShape(...)`)
instead of emitting invalid mismatched C++ (`co_yield {a, b, c};`
against a promise whose `yield_value` only accepts one scalar). The
compiled-generator ABI (`std::coroutine_handle` + a promise type) has
no representation for "yields a tuple of N values" at all — only a
single scalar (`int64_t`/`double`/`_Bool`/`char *`).

This is the EXACT SAME structural gap already independently root-caused
in three other real-world files this session:
- `bugs/CODEGEN_generator_function_Lib_test_libregrtest_save_env.md`
  (`resource_info`'s `yield name, getattr(...), getattr(...)`)
- `bugs/CODEGEN_generator_function_Lib_test_test_exception_group.md`
- `bugs/COMPILE_FAIL_Modules__decimal_tests_randdec.md` (14 of
  `randdec.py`'s own generator functions, e.g. `yield coeff, 1`)

`Path.walk()` is simply another real file hitting the same, still-open
gap — not a new or distinct bug.

**Why this is not being fixed here**: making tuple-valued yields
actually compile needs a new value-representation category threaded
through the whole generator-codegen subsystem — promoting `value_ctype`
to a heap-boxed tuple representation and threading that through
`<base>_value`'s C-side accessor plus every yield/yield-from-
delegation site's type-unification logic. That's structural, not a
local case fix, per this project's bug-triage convention (see
CLAUDE.md's quality-gate section) — confirmed independently four times
now across four different real files, so a real fix here would
correctly resolve all four docs at once, but is out of scope for a
narrow, single-bug session.

**Previously-reported issues now moot**: the 2026-08-06 `_os.py`
exception-attribute errors and the `__init__.py:72`/`:404` negative-
index-slice errors both no longer reproduce — compilation fails at
`walk`'s tuple-yield refusal before either would be reached (this was
already true as of 2026-08-07 and remains true now).

Left open. No code changes made for this bug.
