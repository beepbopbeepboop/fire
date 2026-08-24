# COMPILE_FAIL: Tools/unicode/gencodec.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-23): COMPILES end-to-end now (both old issues fixed);
## runtime smoke test exposes a DIFFERENT, unrelated iteration gap.

`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py`
exits 0 and produces a real arm64 executable on branch `fix/tools-misc`
(`c16c05c`). Issue 1 (bare `len(t)` statement) was already fixed per the
2026-08-09 note. Issue 2 (nested tuple-unpack target `for e,(u,c) in
map.items():`) no longer produces any paren-fragment syntax errors — the
bracket-aware, depth-aware target splitting consolidated across
gimple_gen_infra.py/gimple_gen_loops.py/gimple_gen_stmts.py/gimple_codegen.py
(this branch's commit `c16c05c`, plus master's pair-value dict-items iteration
machinery) covers every previously-counted duplicated split site. The 2026-08-09
note's "even a syntactic fix would be semantically wrong" concern did NOT
materialize for this loop shape: values flow through the pair-value path rather
than the dummy-0 `_gen_for_dict` fallback.

Runtime caveat found by actually executing the built binary (no args): it exits
0 but emits `mojo_unsupported_iter: 'for' loop over unsupported iterable type
gencodec.py:375: int64_t (the loop body runs zero times)` — line 375 is `for
mapname in mapnames:` where `mapnames = os.listdir(dir)`: `os.listdir` is
unmodeled, its result defaults to opaque `int64_t`, and the loop silently runs
zero times (with that one diagnostic). That is a NEW, separate gap (`os.listdir`
modeling), not a regression of either fixed issue — but it means the built
binary is not yet behaviorally correct. Status: compile-level ALREADY-FIXED;
runtime PARTIAL pending os.listdir support.

## Status (updated 2026-08-09, historical — superseded by 2026-08-23 above)

Re-ran; the file had two distinct issues. One is now FIXED (narrow, landed
this session). The other is real-rooted and STRUCTURAL — not fixed.

### 1. `len(t)` as a bare, discarded-value statement — FIXED

`hexrepr()`'s `try: len(t) except TypeError: ...` (a type-probe idiom: call
`len()` just to see if it raises, discarding the result) produced `error:
passing argument 1 of 'mojo_len' makes integer from pointer without a cast
[-Wint-conversion]`.

Root cause: `_gen_stmt_ExprStmt` (gimple_codegen.py) has a long chain of
special-cased builtin/call handling for a bare, value-discarding call
statement (`print`, `exit`/`quit`, closures, `main`, etc.), but had no case
for `len`. It fell through to the generic "just call the C symbol with raw
argument types" path, which has no type-aware dispatch at all — unlike
`_lower_builtin_len` (the value-CONSUMING twin every other `len()` call site
already routes through via `_lower_call`), which dispatches by the operand's
actual type (`MojoStr *`/`MojoList *`/`MojoDict *`/`MojoSet *`/`char *`/an
int64_t-widened pointer). A non-pointer-typed operand therefore went straight
into the runtime's `mojo_len`, which expects a pointer.

Fixed by adding a `raw_name == 'len'` case to `_gen_stmt_ExprStmt` that calls
`self._lower_builtin_len(node.value)` and discards the result — reusing the
existing type-aware lowering rather than duplicating it, matching this same
function's established pattern for other "statement-level twin" bugs already
fixed here (see the `strided_load`/`strided_store`, `exit`/`quit`, closure-call
cases immediately around it).

Verified: `gencodec.py` no longer produces the `mojo_len` pointer/integer
error; `python3 mojo.py build` now gets past this line entirely.

### 2. Nested tuple-unpack target in a `for ... in dict.items():` loop — STRUCTURAL, NOT fixed

`marshalmap()`:
```python
d = {}
for e,(u,c) in map.items():
    d[e] = (u,c)
```
produces, after issue 1's fix, real syntax errors from directly-embedded
stray parentheses in emitted C identifiers:
```
error: expected ')' before ';' token
error: 'u' undeclared (first use in this function)
```
(Reported source lines 381/396/398 are misattributed to the caller —
`convertdir()` — not `marshalmap()` itself; the actual bug is inside
`marshalmap`, confirmed by stripping `#line` directives from the raw
generated C and locating GCC's real line numbers directly. `mojo.py build`'s
link-mode path (`GimpleGen(link_imports=True)`) and a direct
`compile_to_gimple(do_imports=True)` call produce byte-identical output here,
so this isn't a caching/link-mode artifact.)

Root-caused via direct `.c` inspection (stripped `#line` directives, compiled
with the exact `gcc -fgimple -fPIC -I<runtime> -O0 -g3` flags `driver.py`
uses): `marshalmap`'s `map` parameter is (for reasons not further
investigated — a SEPARATE, likely also-structural type-inference gap) typed
`WithStmt *` in the generated signature, an unrelated internal AST-node
struct name, not `MojoDict *`. Because of this, `map.items()` doesn't reach
the statically-typed `_lower_dict_method`'s `items` case (which correctly
returns a real `MojoList *` of pairs) — it falls back to the generic
opaque-object RUNTIME-dispatch path (`mojo_obj_call1` + a runtime
`mojo_is_registered_dict`/`mojo_is_registered_list` check), which lands in
`_gen_for_dict`'s (or an equivalent runtime-dispatch sibling's) "tuple
target" handling.

That handling's target-name splitting is a **naive, non-paren-aware
`inner.split(',')`** (gimple_codegen.py's `_gen_for_dict`, line ~21254, and
at least one sibling doing the identical thing for the runtime-dispatch
list-iteration branch). The for-loop's target string, built by
`mojo_compiler.py`'s `_parse_unpack_target` (which correctly preserves
nested-tuple structure as literal text, e.g. `"(e, (u, c))"`, exactly as
documented in its own docstring), is then torn apart by a flat comma-split
with no awareness of the embedded parens: `"e, (u, c)".split(',')` yields
`["e", " (u", " c)"]` — three fragments, two of which (`"(u"`, `"c)"`) still
carry a literal stray paren. Each fragment is declared and used VERBATIM as
a C identifier name (`int64_t (u;` / `int64_t c);` — a straight variable
declaration with a parenthesis embedded in the name, hence "expected ')'
before ';' token"), producing invalid C directly.

**This looks narrow at first glance (fix the split to be paren-aware) but is
not, for two independent reasons — both found during this investigation, not
assumed:**

1. **The naive split exists at multiple independently-duplicated call
   sites** (`gimple_codegen.py` lines ~16895, ~20681, ~21013-21014,
   ~21253-21254 — at least four `inner.split(',')`/`var[1:-1].split(',')`
   sites doing this same un-paren-aware tuple-target parsing for different
   loop/comprehension shapes). This project has documented history (see
   `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`'s "fourth call
   site found during verification") of a fix scoped to only one or two of
   several near-identical duplicated sites compiling clean for the obvious
   repro while silently missing the same shape elsewhere. A real fix needs
   either auditing and fixing every site consistently, or factoring them
   into one shared depth-aware splitter — the latter is the right
   "consolidate duplicates" move per this project's own conventions, but is
   a real (if contained) refactor, not a one-line patch.
2. **Even a syntactically-correct fix would still be semantically wrong.**
   `_gen_for_dict`'s own header comment is explicit: for a dict "tuple
   target", only the FIRST unpacked name gets the real key; every other name
   is unconditionally assigned a dummy `0`/`NULL` — this runtime's dict
   iteration has no way to yield real per-entry VALUES through this path at
   all (that's why the flat, non-nested case `for k, v in some_dict:` already
   silently sets `v` to `0` today — pre-existing, accepted behavior, not
   something this bug introduces). So `u` and `c` in the nested case would,
   even after a paren-aware-splitting fix, both silently end up `0` instead
   of the real unicode-codepoint/comment values `gencodec.py` actually reads
   from the character map. Making it COMPILE without producing correct
   VALUES would be a silent-miscompile trap, not a real fix — worse than
   leaving the compile error in place, which at least fails loudly.

A genuine fix needs real (key, value) pair iteration with correctly-typed
value slots wired all the way from `mojo_dict_items`/the runtime-dispatch
fallback through to the loop body — a real architectural addition to this
codegen's dict-iteration model, not a narrow stub/gap fix. Also unresolved,
and likely related but not investigated: why `map` (an ordinary,
unannotated function parameter) infers to `WithStmt *` at all.

Not fixed here. Left for a dedicated follow-up with its own investigation
budget.

## Quality gate (2026-08-09, for the `len()` fix only)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed.
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   (unchanged from baseline).
