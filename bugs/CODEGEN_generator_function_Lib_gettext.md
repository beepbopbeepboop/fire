# CODEGEN_generator_function: Lib/gettext.py

## Status (updated 2026-08-18 — root cause #2, `mojo_enumerate`'s `start` gap, FIXED)

`enumerate(iterable, start)`'s `start` argument is now modeled everywhere
in `gimple_codegen.py` that lowers `enumerate(...)`:

- `_gen_for_enumerate` (bare `for i, x in enumerate(seq[, start]):`
  statement form) — previously silently DROPPED the 2nd argument
  entirely (no arity check at all), so `for i, x in enumerate(items,
  5):` compiled clean but silently produced 0-based indices instead of
  5-based ones. Now threads a `start` value through: the internal
  0-based loop counter (`idx_t`, used for every `mojo_list_get_*` call)
  is unchanged, but the user-visible index variable gets `idx_t +
  start` when `start` is present.
- The comprehension-embedded `for` clause form (dict/list/set/generator
  comprehensions, e.g. gettext.py:114's `{i: c for i, c in
  enumerate(_binary_ops, 1)}`) was a genuinely separate lowering path
  in `_lower_comprehension` with NO enumerate-awareness at all — it fell
  through to the generic iterable dispatch, which called
  `lower_expr(gen0.iterable)` and hit the `mojo_enumerate` runtime
  shim's real arity (1 arg) directly, producing the reported "too many
  arguments to function 'mojo_enumerate'; expected 1, have 2" error for
  the 2-arg form. Worse: even the 1-arg form (`enumerate(seq)` with no
  `start`) was previously silently producing an EMPTY comprehension
  result (`mojo_enumerate` is an identity passthrough returning the
  unchanged list; the generic tuple-target branch then treated each
  element as if it were itself a sub-list/tuple to unpack, which a
  plain enumerated list never is). Added a dedicated `is_enumerate`
  check in `_lower_comprehension` plus a new `_compr_enumerate_loop`
  method that walks the underlying list by index directly, mirroring
  `_gen_for_enumerate`'s index-loop shape, with the same `start`-offset
  handling. Fixes both the crash AND the pre-existing silent-empty-
  result bug for the 1-arg case.
- The separate C++20-coroutine scalar-body model's `_cpp_for_stmt`
  (used for `for`-loops inside compiled generator/async bodies) had an
  enumerate-tuple-target special case whose own docstring already used
  `enumerate(iterable, start=1)` as the motivating example but never
  actually implemented `start` (always looped from 0). Fixed the same
  way: the loop counter stays 0-based, only the value assigned to the
  first target slot gets the offset added.

The runtime shim `mojo_enumerate` itself (`runtime/mojo_runtime.c`) was
NOT touched — it's a 1-arg identity passthrough only ever consulted by
the generic (non-enumerate-aware) call-lowering fallback; all 3 real
codegen paths above bypass it entirely and lower the underlying
iterable directly, so no runtime-shim signature change was needed.

Interpreter path (`myinterpreter.py`) needed no fix: `self.scope.
define('enumerate', enumerate)` binds Python's own real builtin
directly, which already supports `start` correctly (confirmed with a
standalone test exercising both the bare-`for` and dict-comprehension
forms with `enumerate(items, 5)`/`enumerate(items, 1)`).

Verified narrowly (`for i, x in enumerate(items, 5):`, dict/list/set
comprehensions with `enumerate(items, 5)`/`enumerate(nums, 100)`) —
all produce correct start-offset indices in a real compiled binary.
Verified against the real target: gettext.py:114's `too many arguments
to function 'mojo_enumerate'` error is GONE from a full real build
(`python3 mojo.py build .../Lib/gettext.py`); root causes #1
(`mojo_open_file`, line 554) and the 843 red herring also no longer
appear in this run (likely resolved incidentally by unrelated work
since the 2026-08-10 entry — not investigated further here, out of
scope). Root cause #3 (lines 208/217, `_parse()`'s tuple-return-type
collapse) and the 472/485 dynamic-`%`-format gap are UNCHANGED and
still open, exactly as previously documented — both out of scope for
this fix.

Quality gate: `test_gimple.py` (248/248 pass), `test_module_cache.py`
(76/76 pass), `make check-selfhost` (clean), and a from-scratch stdlib
dylib rebuild (`rm -f build/libmojostdlib.dylib` +
`build_stdlib_dylib.build_stdlib(jobs=8)`) — 0 skip lines before AND
after (no regression). Committed.

## Status (updated 2026-08-10, re-verified + deepened, no code change — 3 real root causes pinned down precisely)

Re-verified against current master (`9d93746`): identical error list to
the 2026-08-09 entry below, character for character (208/217/472/485/
554/114, plus the 843 red herring). Confirmed still NOT a generator-
codegen-cluster failure — `_expand_lang` compiles clean, no
`MOJO_DEBUG=1` refusal naming it. Root-caused the three real remaining
gaps precisely (previously only described at the symptom level):

**1. `mojo_open_file`'s arity mismatch (line 554) is NOT a missing-
mode-parameter gap in the runtime shim — it's a call-routing bug, and
it's the SAME already-tracked hard bug as
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`,
just manifesting through a BUILTIN instead of a struct name.**
`_lower_builtin_open` (`gimple_codegen.py:15049`) already correctly
handles both `open(path)` -> `mojo_open_file` (1 arg) and `open(path,
mode)` -> `mojo_open` (2 args, `gimple_codegen.py:15059-15065`) — but
it's gated on `fname_raw == 'open' and 'open' not in
self.func_return_types` (`gimple_codegen.py:14449`). `Lib/_pyio.py`
defines a REAL top-level `def open(file, mode="r", ...)`
(`_pyio.py:75`); since `func_return_types` is a single FLAT, non-
module-scoped namespace shared across every module in the combined
compile (confirmed: no per-module key anywhere in this dict), once
`_pyio.py` is anywhere in the transitive import graph, `'open' in
self.func_return_types` is true GLOBALLY — including for `gettext.
py`'s own, unrelated `open(mofile, 'rb')` call. That routes past the
arity-aware special case straight to `_lower_named_call`
(`gimple_codegen.py:15599`), whose OWN dispatch
(`fname = self.BUILTIN_VALUE_MAP.get(fname_raw, self._func_csym(fname_
raw))`, line 15605/15608) prefers `BUILTIN_VALUE_MAP['open'] =
'mojo_open_file'` UNCONDITIONALLY over the real, arity-correct
resolution — so even here, the call still gets routed to the 1-arg
`mojo_open_file`, with both of the real 2 arguments (`mofile`, `'rb'`)
passed through, producing this error. Confirmed `mojo_enumerate`'s
appearance in this same doc's error list is NOT the same bug (see #2) —
this specific one is purely about `open`.

Not fixed: this is the identical flat-namespace architecture problem
already tracked (and re-verified as still open THIS session, see
`same_bare_name_struct_collision_across_modules.md`'s own 2026-08-09/10
entries) — any narrow, `open`-specific patch (e.g. reordering the
`BUILTIN_VALUE_MAP` vs. real-function preference in `_lower_named_call`)
risks silently breaking `_pyio.py`'s own compilation if anything in
that file calls its own top-level `open` bare (would then misroute to
itself instead of... itself, actually, so probably safe there — but
the SAME priority-ordering pattern is shared by `_lower_named_call`'s
handling of every other `BUILTIN_VALUE_MAP` entry — `print`, `len`,
`str`, `int`, `list`, `dict`, `enumerate`, `zip`, `map`, `filter`,
`type`, `max`, `min`, `sum`, etc. — so a real fix needs to reason about
ALL of them, not special-case `open`, without a full audit of what real
stdlib modules define same-named top-level functions/methods of their
own — genuinely the scope of the existing hard-bug doc, not a narrow
fix). Cross-referenced there is unnecessary (that doc already owns this
architecture); noting the concrete mechanism here for whoever revisits
`open()`/`enumerate()` specifically.

**2. `mojo_enumerate`'s 1-vs-2-arg gap (line 114, `enumerate(_binary_
ops, 1)` inside a dict comprehension) is a genuinely separate, narrower
feature gap — confirmed no shadowing involved.** Grepped for any
`_lower_builtin_enumerate`-style 2-arg (`start=`) handling anywhere in
`gimple_codegen.py`: none exists. The only `enumerate`-aware codegen
(`gimple_codegen.py:19348-19356`'s `_gen_for_enumerate`,
`gimple_codegen.py:24176`, `25505`) is for a bare `for i, x in
enumerate(seq):` statement, and even that has no `start=` parameter
handling. gettext.py's case is INSIDE a dict comprehension's `for`
clause (a different, comprehension-specific lowering path), which also
has nothing for the 2-arg form. `enumerate(iterable, start)`'s `start`
argument is simply never modeled anywhere in this codegen — a real,
narrow-but-nontrivial feature gap (thread a `start` value through
`mojo_enumerate`'s runtime shim and both call sites), independent of
gap #1. Not fixed here (out of scope for a generator-codegen pass, and
the comprehension-embedded case specifically needs its own lowering
path traced first).

**3. `_parse()`'s return-type collapse (lines 208/217) is a real,
unaddressed gap: this codegen has NO tuple-return-type inference for
ordinary (non-generator) multi-return-path functions at all.**
`c2py()`'s `result, nexttok = _parse(_tokenize(plural))` destructures a
2-tuple `(str, str)` that `_parse(tokens, priority=-1)` returns from
several different `return result, nexttok` sites (a recursive-descent
parser). Grepped for any per-function tuple-return-type registry
(`func_tuple_return_types` or equivalent): none exists anywhere in
`gimple_codegen.py`. Contrast with generators, where an analogous gap
for tuple-VALUED `yield` was real work fixed earlier this session
(commit `a7b71a0`, boxing into `MojoList *`) — no equivalent exists for
an ordinary function's tuple RETURN value. `MultiAssignStmt`'s CallExpr-
RHS lowering has nothing to consult for `result`'s real per-slot type,
so it defaults to a scalar (`int64_t`-ish), and both the `for c in
result:` string iteration (`mojo_strlen`) and the `elif c == ')'`-
adjacent `_mojo_at_char` access at line 217 get fed that wrong scalar
where a `char *` is expected. This is a real, nontrivial feature (new
per-function multi-return-path type-inference machinery, analogous to
but NOT a copy of the generator tuple-yield work), not a narrow fix —
not attempted here.

472/485 (dynamic `%`-format-string gap) and 843 (the textwrap.py
`#line`-stamping red herring) are unchanged from the 2026-08-09 entry
below; nothing new to add there.

No code change made for any of the 3 real gaps above; no gate run.

## Status (updated 2026-08-09)

Re-verified against current master (post-merge `7df52a0`). Still fails,
still NOT a generator-codegen-cluster failure — `gettext.py`'s one
generator (`_expand_lang`, `yield value`/`yield ''`) again shows up ONLY
in the warnings section of the build log (`_expand_lang_584a43`), no
errors, no `MOJO_DEBUG=1` "not eligible" refusal. Confirms the
2026-08-07 reclassification still holds.

Current error list has shifted again (line numbers move release to
release as unrelated fixes land elsewhere in the stack):
```
gettext.py:208:23 error: passing argument 1 of 'mojo_strlen' makes pointer from integer without a cast
gettext.py:217:25 error: passing argument 1 of '_mojo_at_char' makes pointer from integer without a cast
gettext.py:472:1  error: invalid types for 'trunc_mod_expr'   (npgettext's `self.CONTEXT % (context, msgid1)`)
gettext.py:485:1  error: invalid types for 'trunc_mod_expr'   (npgettext's `self.CONTEXT % (context, msgid1)`, 2nd call site)
gettext.py:554:10 error: too many arguments to function 'mojo_open_file'; expected 1, have 2
gettext.py:114:10 error: too many arguments to function 'mojo_enumerate'; expected 1, have 2
gettext.py:843:46 error: stray '\' in program / missing terminating ' character / expected ';' ...
```
The 208/217 pair is one root cause, not two: `c2py()`'s `result, nexttok
= _parse(_tokenize(plural))` (line 203) then `for c in result:` (line
208) — `result`'s inferred type collapses to a scalar (`int64_t`-ish)
instead of the real string/sequence type `_parse` returns, so both the
`mojo_strlen` call (line 208's `for` iteration) and `_mojo_at_char`
(line 217's `elif c == ')'`-adjacent codegen) get fed an int where a
`char *` is expected — matches the previously-documented "untouched"
208 line, now confirmed to have a sibling symptom at 217 from the same
cause. 472/485 are the SAME dynamic-`%`-format-string gap already
called out as deliberately out-of-scope. 554 (`mojo_open_file` 1-vs-2
arg — `open(mofile, 'rb')`, the mode string isn't modeled) is confirmed
still real and, per the note below, IS the same recurring gap suspected
in `turtle.py`'s re-diagnosis: `gimple_codegen.py`'s `mojo_open_file`
runtime shim (declared at line ~32669: `int64_t mojo_open_file(char
*path);`) only ever takes a path, never a mode — a systemic modeling
gap (would need runtime.c changes + mode-string handling), not a narrow
one-line fix. NEW this pass: `mojo_enumerate` has the identical 1-vs-2-
arg gap for the `start` parameter (`enumerate(_binary_ops, 1)` at line
114, a plain dict-comprehension, not generator-related) — same shape of
bug, different builtin.

`gettext.py:843` is a confirmed **red herring**, same #line-stamping
artifact documented in `glob.py`'s doc: `gettext.py` is only 657 lines
long, so line 843 cannot be real source. Checking the cached `.ci`
confirms the last `#line` stamp for `gettext.py` is `#line 657
"...gettext.py"`, immediately followed by unstamped code from a
transitively-imported module (`textwrap.py`'s `TextWrapper` — the
`_classattr_TextWrapper__letter` identifier in the error is textwrap's,
not gettext's). Not gettext.py's bug at all; mis-attributed by GCC's
line counter continuing past the last stamp.

**Classification unchanged: NOT a generator-codegen-cluster failure.**
Remaining errors are a small cluster of distinct, non-narrow, non-
generator gaps (a `_parse()`-return-type inference bug, the known %-
format gap, and TWO builtins — `open()`/`enumerate()` — missing their
optional second argument in the runtime shim). None attempted here —
out of scope for this generator-codegen pass; `mojo_open_file`'s gap in
particular looks worth its own dedicated non-generator bug doc given it
now has 2 confirmed sightings (gettext.py, turtle.py).

## Status (updated 2026-08-07)

Of the 4 errors listed below, the `gettext.py:445:1: error: invalid
conversion in gimple call` one is now FIXED — root cause was
`_gen_stmt_FromImportStmt`'s wrong `'int'` default for an unknown
function-scoped-imported symbol's return type (`from struct import
unpack` inside `GNUTranslations._parse`, line 353); see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` (Mechanism 1) for the full writeup. The other three
(`mojo_strlen` pointer/int conversion at line 208, `trunc_mod_expr` at
line 472 — the SAME dynamic-%-format-string gap documented as
deliberately out-of-scope in that doc's "Not fixed" section — and
`mojo_open_file` arg-count at line 554) are untouched, still open.

## Status (updated 2026-08-06, PARTIALLY STALE — see above)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'_token_pattern' was not declared` .cpp error no longer
reproduces. `gettext.py` has one small generator (`_expand_lang`,
`yield value`/`yield ''`, lines 95-96) — it does not appear anywhere in
the current error list, and `MOJO_DEBUG=1` shows no "not eligible"
refusal naming it: gettext.py's own generator now appears to compile
cleanly through the coroutine path. (Note: this build is one of the
slowest in this cluster — ~44 minutes wall clock — consistent with the
already-documented, unrelated `bugs/hard/PERF_nested_module_compile_
walk_ast_quadratic_rescan.md` perf issue for a moderately large
transitive import graph.)

**Classification: NOT a generator-codegen-cluster failure anymore.**
Current errors are all unrelated to generators — dominant pattern is
`%`-formatting/modulo type errors and pointer/int conversion bugs in
gettext.py's own translation-catalog parsing code:
```
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:208:23: error: passing argument 1 of 'mojo_strlen' makes pointer from integer without a cast [-Wint-conversion]
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:445:1: error: invalid conversion in gimple call
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:472:1: error: invalid types for 'trunc_mod_expr'
/Users/mrs/net/Python-3.14.6/Lib/gettext.py:554:10: error: too many arguments to function 'mojo_open_file'; expected 1, have 2
```
Not investigated further — out of scope for this generator-codegen
cluster (the `mojo_open_file` 2-vs-1-arg error also appeared in
`turtle.py`'s current re-diagnosis — may be a recurring non-generator
gap worth its own report).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/gettext.py
