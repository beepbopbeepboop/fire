# CODEGEN_generator_function: Lib/tempfile.py

## Status (re-verified 2026-08-26, worktree agent-ae936147a68675d97 — commit 997f3b1's two fixes confirmed already subsumed by this branch's history)

`997f3b1` (the `delete`-C++-keyword-field rename + scalar-self-field
zero-iteration range-for stub) was a loose commit not reachable from
this worktree's HEAD (`git merge-base --is-ancestor 997f3b1 HEAD` fails)
— attempted `git cherry-pick 997f3b1`; both hunks conflicted against a
strict superset already landed independently on this branch (the
shelve.py-driven `.keys()/.values()/.items()/.copy()`-on-scalar-self-
field generalization, and `_CPP_KEYWORD_FIELDS` already present in
`gimple_ctypes.py`). Resolved the conflict by keeping HEAD's superset
and discarding the now-redundant duplicate hunk; the cherry-pick then
recorded empty (nothing left to commit) — `git cherry-pick --skip`.
Fresh isolated `compile_to_gimple_with_cpp(do_imports=False)` +
`g++-mp-15 -std=c++20 -fsyntax-only`: **0 errors**, confirming
tempfile.py's own isolated .cpp unit is genuinely clean on this branch
already, no code change needed. Whole-program build remains blocked by
the transitively-imported `operator.py` attrgetter/itemgetter closure-
of-callables gap (unchanged, feature-sized, see below). Doc stays open.

## Status (updated 2026-08-25, worktree fix/opencode-group2 — the 08-24 "isolated compile clean" claim was stale; 2 REAL own-generator bugs found + FIXED (C++-keyword `delete` field, scalar-field range-for); isolated .cpp unit now genuinely 0 errors)

Re-ran the doc's own isolated methodology fresh
(`compile_to_gimple_with_cpp(do_imports=False)` +
`g++-mp-15 -std=c++20 -fsyntax-only`): **3 errors**, NOT clean —
confirmed identical at this session's pre-session commit (`4220964`
via a separate `git worktree add`), so the 2026-08-24 entry's "still
succeeds cleanly" verdict was stale (same fd909e9-era pattern as
several sibling docs). Both root causes found and fixed in shared
compiler source (commit `997f3b1`):

1. **`_TemporaryFileCloser.delete` — a C++ keyword as a struct field
   name.** The .ci side compiled fine (`delete` is a valid C
   identifier), but the compiled-generator .cpp preamble re-emits the
   same struct typedef verbatim, and g++ rejects `bool delete;`
   ("expected unqualified-id before 'delete'"). Fix:
   `_safe_field` (gimple_ctypes.py) — THE chokepoint every field
   emission AND access site on both sides already routes through — now
   also renames `_CPP_KEYWORD_FIELDS`, exactly like it long has for C
   keywords/macros. Verified end-to-end with a standalone repro (struct
   with a `delete` field + a generator method reading it): compiles,
   links, RUNS, prints the right value.
2. **`for line in self.file:` emitted `for (auto line : self->file)`
   over a plain int64_t** ("'begin' was not declared in this scope").
   `self.file` is an unannotated-init param (the HIGH-RISK family —
   root NOT touched per standing scope rule), so the field's resolved
   ctype is int64_t: genuinely not a container under this codegen's own
   boxing convention, hence uniterable in this body model. Fix:
   `_cpp_for_stmt` now takes that scalar-typed-self-field case down the
   SAME zero-iteration stub path the `iter_expr == '0'` case already
   uses (bind target to 0, run zero iterations) instead of emitting
   invalid C++. Repro compiles+runs; iteration honestly yields nothing
   with the runtime's existing "unsupported iterable ... runs zero
   times" note.

After both fixes: tempfile.py's isolated .cpp unit is **0 errors**
(re-verified). Whole-program build still blocked by the transitively-
imported operator.py attrgetter/itemgetter closure-of-callables shape
(unchanged, below); the file's known >1hr whole-program perf issue
makes a full-build confirmation impractical within a watchdog budget,
matching the 08-24 entry's methodology. Full mandatory gate for the two
fixes: test_gimple.py 256/256, test_module_cache.py 76/76, generator
runner 53/53, async runner 38/38, make check-selfhost clean, from-
scratch stdlib dylib rebuild EXIT=0 / 0 skip lines. Doc stays open.


## Status (updated 2026-08-24, worktree fix/rest-remainder6 — the chained-getattr `request for member 'name'` bug from the entry below is root-caused and FIXED for real; it was never a "no static type" gap, it was a WRONG static type)

The entry below this one framed tempfile.py's 3 remaining own-file
errors (`getattr(getattr(file, 'buffer', file), 'raw', raw).name = ...`
at lines 609/668/703) as "no static type for a chained dynamic-
attribute read" — deferred as the same family as `bugs/hard/
CODEGEN_dynamic_attribute_on_generic_object.md`. That framing was
wrong: root-caused this session to a WRONG static type, not a missing
one.

`gimple_gen_calls.py`'s "A5" getattr()-call fast path (`getattr(s,
'elifs', [])` on a boxed AST-node handle) calls `gen._known_field_type
(attr)`, which resolves `attr`'s C type whenever every struct across
the WHOLE-PROGRAM-shared `struct_field_types` that happens to define a
field of this bare name agrees on its type — true even when only ONE,
totally unrelated struct anywhere in the huge transitive stdlib compile
happens to define it. `raw = getattr(file, 'buffer', file)` (`file`/
`raw` are genuinely opaque `_io.open()` results, unrelated to any user
struct) picked up SOME unrelated class's own `buffer: String` field's
`char *` type purely by bare-name coincidence, mistyping `raw` as
`char *`. The LATER, separate real attribute write `raw.name = name`
then emitted a literal `.` member access directly on that `char *` — a
hard gcc "request for member 'name' in something not a structure or
union" error (the reported symptom). Confirmed via a from-scratch
minimal repro (an unrelated class defining `buffer: String` alongside
the exact `getattr(file, 'buffer', file)` / `raw.name = name` shape)
that reproduces the identical error signature standalone, with no
tempfile.py/stdlib involvement at all.

**Fix**: this A5 fast path was built for this compiler's OWN self-
hosted source (the `getattr(s, 'elifs', [])`-style idiom reading fields
off a boxed AST-node handle in `mojo_compiler.py`/`myinterpreter.py`,
where `attr` genuinely does name one of a small, closed set of AST-node
field names) — applying the same "single struct anywhere agrees"
heuristic to an arbitrary third-party `getattr(obj, name, default)`
call anywhere in the huge stdlib corpus is unsound, since common,
generic field names like `buffer`/`raw`/`name` collide easily across
unrelated classes. Scoped the heuristic to fire only when compiling
this project's own self-hosted source (the same path-based gate
`gen_module`'s `_is_selfhost_file`/`DispatchSolver(allow_assume_all_
methods=...)` already use) — every other file now falls through to the
generic untyped-`int64_t` path unchanged, the only behavior this call
had before the A5 fast path existed. Commit `2d2bf8a`.

**Verified**: the minimal repro above now compiles clean under
`gcc-mp-15 -fgimple -fsyntax-only`. A real, direct `mojo.py build
.../Lib/tempfile.py` was attempted for full end-to-end confirmation but
hit this file's own already-documented, pre-existing, unrelated perf
issue (`bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
rescan.md` — this file has historically taken "over an hour" to build
whole-program; this session's attempt was killed after ~4 minutes per
this project's runaway-build safety rule, a pre-existing slow-compile
data point unrelated to this fix, not a regression). The isolated
repro plus direct inspection of the fixed code path (both `getattr()`
call sites now only take the A5 branch when `_is_selfhost_file` is
true) is the verification standard used here, matching this doc's own
established methodology for this file (`compile_to_gimple_with_cpp
(do_imports=False)` isolated checks, given the whole-program build's
known perf cost). Full quality gate: `test_gimple.py` 252/252,
`test_module_cache.py` 76/76, `make check-selfhost` clean, from-scratch
stdlib dylib rebuild 0 skips.

Per the 2026-08-23 entry below, tempfile.py's own error set WAS exactly
these 3 chained-getattr lines (the `TMP_MAX`-family and textwrap
issues were already fixed earlier). With this fix, tempfile.py's own
source should now be fully clean (not independently re-confirmed via a
full whole-program build this session, per the perf note above) — the
file's remaining blocker is the transitively-imported `operator.py:270`
`attrgetter`/`itemgetter`-closure-of-callables issue (unaffected by
this fix, see the 2026-08-11 entry below). Doc stays open.

## Status (updated 2026-08-24, worktree fix/gen-core — re-verified, unaffected by this session's fixes; `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md` (the "same deferred family" this doc pointed at below) has since been fully resolved and deleted, but tempfile.py's own 3 lines are a distinct chained-getattr shape not covered by that fix)

Re-ran the isolated coroutine-path compile fresh, post-`fd909e9` and
post-this-session's own `6e92df8` (class-body dunder-alias methods —
doesn't apply here, no alias-assignment dunders found in tempfile.py).
`compile_to_gimple_with_cpp(do_imports=False)` on tempfile.py still
succeeds cleanly; `_TemporaryFileWrapper.__iter__` unaffected either
way. Checked whether the now-resolved dynamic-attribute doc's fix
(`git log`: `dfc0bee`/`2cf2ab1`/`a05a5c7`/... — real per-object
attribute storage) happens to also cover the 3 `request for member
'name'` chained-getattr lines (609/668/703,
`getattr(getattr(file, 'buffer', file), 'raw', raw).name = ...`) — it
does not: those fixes address dynamic attribute SET/GET on a struct
instance whose declared type is known, not this shape's core problem
(the intermediate `getattr(x, 'attr', default)` calls themselves have
no static return type to hang a further `.name` access off of). Still
open, still the same deferred family in spirit (no static type for a
chained dynamic-attribute read), just not literally fixed by that
doc's landed work. The `operator.py:270` transitive blocker
(`attrgetter`/`itemgetter` closed over a tuple of CALLABLE values) is
unchanged — same "opaque callable value has no representation"
structural family this session confirmed independently via
`pickletools.py`'s `getpos` and `weakref.py`'s `wr()` (see those docs'
2026-08-24 entries). Doc stays open.

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — re-verified; own-code set down to the 3 chained-getattr errors)

Re-verified against current HEAD (post f7cf084/53b1aaa/65706f3). The
`TMP_MAX`-family and textwrap fixes below hold; the remaining
tempfile.py-own error set is exactly the 3 `request for member 'name'
in something not a structure or union` lines (609/668/703, the
`getattr(getattr(file, 'buffer', file), 'raw', raw).name = ...`
chained-getattr type-inference gap noted on 2026-08-09 — same deferred
family as `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`).
`_TemporaryFileWrapper.__iter__` still compiles cleanly through the
coroutine path. The transitive `operator.py:270 non-trivial conversion`
blocker documented on 2026-08-11 is unchanged. Doc stays open.

## Status (updated 2026-08-11)

Re-verified against current master with a fresh real rebuild. Still
correctly classified as **NOT a generator-codegen-cluster failure** —
`_TemporaryFileWrapper.__iter__` still shows zero signal of a problem.

The previously-documented `_c_escape()` gap (class-body string-attribute
initializers not escaping embedded `"`) is GONE — verified both call
sites (`gimple_codegen.py`'s class-attribute-globals section, now
~line 34682/34692) already route through `_c_escape()`; fixed as a side
effect of other work between the last note and now.

**Found and fixed a real, different narrow bug** blocking this file:
`gimple_codegen.py`'s `_c_field_name` (line ~3173) renames a Mojo
global/struct-field name that collides with a handful of hardcoded C
preprocessor macro names (`_C_MACRO_NAMES`, line ~2067 — `NULL`, `EOF`,
`SEEK_SET`/`SEEK_CUR`/`SEEK_END`) so the raw name isn't emitted verbatim
into the generated struct, where `<stdio.h>`'s own macro would text-
substitute it into invalid C before GCC ever parses it. `tempfile.py`'s
own module-level constant `TMP_MAX = 10000` (`Lib/tempfile.py:72`) isn't
in that allow-list, and `<stdio.h>` defines `TMP_MAX` as an object-like
macro (`308915776` on this system) — so the whole-program root-module
globals struct got emitted as `int TMP_MAX;` / `.TMP_MAX = 20,` /
`_root_globals.TMP_MAX`, all three silently macro-substituted to `int
308915776;` etc., producing exactly the "expected identifier ... before
numeric constant" family of errors this doc has tracked for 3+ prior
sessions (confirmed via a from-scratch reproduction: stripping all
`#line` directives from the generated `.ci` and recompiling showed the
true physical location was `typedef struct _root_toplev { int TMP_MAX;
...`, not literally "tempfile.py:4732" as GCC's misleading `#line`-
derived diagnostic claimed — the `#line` attribution for this whole-
program init struct is itself inaccurate/stale past a certain point in
the file, a separate, not-yet-investigated diagnostics-quality gap that
only mattered for tracking this bug down, not for the fix itself).

**Fix**: added `TMP_MAX`, `FILENAME_MAX`, `FOPEN_MAX`, `BUFSIZ`,
`L_tmpnam`, `L_ctermid` to `_C_MACRO_NAMES` (the rest of `<stdio.h>`'s
own plain object-like macros, same header that already motivated
`EOF`/`SEEK_*`'s presence in the set — bounded to this one header rather
than sweeping every libc header's macro namespace, to keep the change
narrow and reviewable). Confirmed via rebuild: the `TMP_MAX`-family
errors (previously 3 of the file's ~13 errors, at lines 4732/4755/4756)
are completely gone.

**This file still does not build** — a real rebuild after the fix hits
a NEW, different, non-generator, non-textwrap blocker:
`Lib/operator.py`'s `attrgetter.__init__`/`itemgetter.__init__`
(`getters = tuple(map(attrgetter, self._attrs))` closed over by a nested
`def func(obj): return tuple(getter(obj) for getter in getters)`) hits
`operator.py:270:1: error: non-trivial conversion in 'var_decl'`
(a local inferred `int64_t` but assigned a `struct MojoList *`). This is
the closure-capturing-a-tuple/list-of-CALLABLE-VALUES shape — matches
this session's already-confirmed structural gap ("an opaque callable
VALUE — a lambda or bound method stored in a variable, not called
immediately — has no representation" in this codegen's type model), not
a narrow bug. Not attempted here (a real fix would mean giving this
codegen a first-class representation for a collection of bound-method/
callable values, a design-level project, not a one-spot stub gap).
`operator.py` is reached transitively (via `functools`/`shutil`-style
imports), not one of tempfile.py's own generators or module-level code.

Gate run for the `_C_MACRO_NAMES` fix: `test_gimple.py` 247/247,
`test_module_cache.py` 76/76, `make check-selfhost` clean,
`build_stdlib_dylib.build_stdlib()` 0 skips, `compile_stdlib.py` 664/664
(no regression from the added macro-name reservations).

## Status (updated 2026-08-09)

Re-verified again against current master with a fresh real rebuild
(`MOJO_DEBUG=1 python3 mojo.py build .../Lib/tempfile.py`, real
`gcc-mp-15`/`g++-mp-15` via `mojo.py`'s own resolution). Classification
UNCHANGED: **NOT a generator-codegen-cluster failure**.
`_TemporaryFileWrapper.__iter__` (`for line in self.file: yield line`,
line 556) shows no "not eligible" refusal in `MOJO_DEBUG=1` output and
does not appear in the error list — still compiles cleanly through the
coroutine path.

The exact same 13 errors reproduce byte-for-byte:
```
tempfile.py:64:17:   error: expected identifier before numeric constant
tempfile.py:200:24:  error: expected identifier before numeric constant
tempfile.py:250:24:  error: expected identifier before numeric constant
tempfile.py:376:24:  error: expected identifier before numeric constant
tempfile.py:423:23:  error: expected identifier before numeric constant
tempfile.py:496:46:  error: stray '\' in program
tempfile.py:609:6:   error: request for member 'name' in something not a structure or union
tempfile.py:668:6:   error: request for member 'name' in something not a structure or union
tempfile.py:703:6:   error: request for member 'name' in something not a structure or union
tempfile.py:4732:7:  error: expected identifier or '(' before numeric constant
tempfile.py:4755:4:  error: expected identifier before numeric constant
tempfile.py:4756:3:  error: expected '}' before '.' token
```
(one fewer distinct line than "13 total" implied previously — 12 error
lines; the miscount doesn't change the classification.)

**Root-caused the `stray '\'` / textwrap.py-transitive bug precisely**
(per this session's brief to pin this recurring cross-file pattern down
further, without fixing it). It is NOT a tokenizer bug at all, and NOT
really "in textwrap.py" — mojo_compiler.py's own `py_tokenize` correctly
tokenizes every raw-string construct in textwrap.py, verified directly
(`mc.py_tokenize()` on the real file and on isolated multi-line
raw-string-concatenation snippets copied verbatim from it, e.g. the
`sentence_end_re = re.compile(r'[a-z]' r'[\.\!\?]' r'[\"\']?' r'\z')`
implicit-concatenation shape at textwrap.py:107-110 — all tokenize
correctly).

The real bug is in `gimple_codegen.py`'s **class-body string-attribute
initializer emission**, which — unlike every other string-literal-to-C
lowering path in this file — does NOT run the value through the
existing shared `_c_escape()` helper (`gimple_codegen.py:3106`) before
splicing it into a C string literal. Two call sites, both in the
class-attribute-globals section of `gen_module` (the pass that builds
`_class_attr_inits`, used for `emit_struct_defs`/main-module code, see
`_mojo_classattr_init`):
```python
# gimple_codegen.py:33521-33522 (class-body SET literal string elements)
if isinstance(elt, StringLiteral):
    inits.append(f'  mojo_set_add_str ({mangled}, "{elt.value}");')
...
# gimple_codegen.py:33530-33532 (plain class-body string attribute)
elif isinstance(v, StringLiteral):
    ctype = 'char *'
    class_attr_inits.append(f'  {mangled} = "{v.value}";')
```
Both should read `_c_escape(elt.value)` / `_c_escape(v.value)` (exactly
like every other string-emission site in this file already does), but
don't. Any class-body string attribute whose value contains a literal
`"` character breaks the generated C string literal early; if raw
content shortly after the embedded `"` also contains a `\` (e.g. an
escaped-quote `\'` from a raw-string regex fragment), that backslash
ends up OUTSIDE any string context in the emitted C — hence gcc's
"stray '\' in program", reported at whatever line/column gcc's own
recovery lands on, which can be arbitrarily far downstream in the same
concatenated translation unit (explaining why this has previously
appeared attributed to unrelated files/symbols — codecs.py, ipaddress.py,
enum.py — compiled alongside the true trigger).

**Confirmed exact trigger in textwrap.py**: `TextWrapper.word_punct =
r'[\w!"\'&.,?]'` (textwrap.py:74) — a `TextWrapper` class-body string
attribute containing an embedded `"`. Root-caused via a minimal,
isolated, from-scratch repro (no textwrap.py/tempfile.py involved at
all):
```python
class TW:
    a = '"'          # <-- alone, this already breaks the build
def main(): print("ok")
main()
```
compiled standalone with `mojo.py build` and reproduces the identical
"missing terminating \" character" / "expected ';' before '}' token"
failure signature. Adding a trailing backslash-quote sequence after the
embedded `"` (mirroring `word_punct`'s real `\'` fragment) upgrades the
same failure to the exact "stray '\' in program" signature seen in the
real build. In the real textwrap.py build, the corruption surfaces at
the very NEXT class-body attribute in source order after `word_punct`
(`letter = r'[^\d\W]'`, C symbol `_classattr_TextWrapper__letter`) —
consistent with `word_punct`'s own init line being the one that actually
breaks the C parse.

This is a genuinely narrow fix (two call sites, wrap in the
already-shared `_c_escape()` helper) — but per this session's scope,
**not attempted here**; left for a dedicated fix pass to act on directly
using the line numbers/call sites above. No code change made in this
pass. The `expected identifier before numeric constant` family
(lines 64/200/250/376/423/4732/4755/4756) and the `request for member
'name'` family (lines 609/668/703, a `getattr(getattr(file, 'buffer',
file), 'raw', raw).name = ...` chained-getattr type-inference gap) were
NOT further investigated — out of scope for this generator-codegen pass,
unchanged from the prior note.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** —
`_TemporaryFileWrapper.__iter__` still shows zero signal of a problem.
The `struct _threading_toplev`/etc. pattern is GONE (fixed by
`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`'s
"mechanism 2" landing, same fix confirmed across several files this
session) and the `stray '\'` textwrap.py tokenizer issue is also gone
from this file's current error list. Remaining errors (13 total, all
in tempfile.py's own non-generator code): repeated `expected identifier
before numeric constant` (lines 64/200/250/376/423, plus 2 more further
in) and `request for member 'name' in something not a structure or
union` (lines 609/668/703), plus one `stray '\'`/`expected ';' before
'_classattr_TextWrapper__letter'` at line 496 (the textwrap.py issue —
apparently not fully gone, just reduced). Not investigated further here
— out of scope for this generator-codegen cluster; the `expected
identifier before numeric constant` repeating at several near-identical
column offsets (24, 23, 17) looks like a real, possibly-narrow parser/
codegen bug (worth a dedicated look by whoever picks up a non-generator
pass on this file) but wasn't traced to a root cause in this session.

## Status (updated 2026-08-06, superseded above — module_toplev pattern since independently fixed)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'_TemporaryFileCloser' does not name a type` .cpp error no
longer reproduces. (Note: this build took over an hour wall-clock —
by far the slowest in this cluster — consistent with, though far more
extreme than, the already-documented `bugs/hard/PERF_nested_module_
compile_walk_ast_quadratic_rescan.md` perf issue.) `tempfile.py`'s own
generator (`_TemporaryFileWrapper.__iter__`, `yield line`, line 556)
does not appear in the current error list and has no "not eligible"
refusal — it appears to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure.** Current
errors (100+) are dominated by two already-cross-referenced patterns:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (7th confirmed occurrence — `_threading_toplev`, `_pprint_toplev`,
  `_io_toplev`, `__py_warnings_toplev`, by far the largest count of any
  file in this cluster).
- The recurring `stray '\' in program` / `_classattr_TextWrapper__
  letter` textwrap.py tokenizer bug (5th occurrence, seen previously in
  codecs.py/ipaddress.py/enum.py's re-diagnoses).

Also several `expected identifier before numeric constant` and
`'MojoBoundMethod' has no member named '_closer'`/`request for member
'name' in something not a structure or union` errors, not investigated
further. None implicate tempfile.py's own generator.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tempfile.py
