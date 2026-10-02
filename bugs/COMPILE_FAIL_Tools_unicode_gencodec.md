# COMPILE_FAIL: Tools/unicode/gencodec.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-10-01 — BUILD IS exit 0; all four remaining items are RUNTIME content divergences, and item 1 is now root-caused to a filed, three-function defect)

`python3 fire.py build -o .tmp/out/gencodec/gencodec
/Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py` under
`tools/memslot.py --gb 8`: **exit 0, zero `error:` lines**, an 80 KB
executable. (The `-o` target's parent directory must exist — `-o
.tmp/out/gencodec` alone fails at LINK with `ld: open() failed` — which
is not a compiler bug.)

So this doc's original COMPILE_FAIL premise is long gone; what is left is
what the 2026-08-25 entry below called "the compile itself and the whole
convertdir control flow are correct". Measured side-by-side against real
CPython 3.14.7 on the same one-file directory (`run/readme.md` plus a
subdirectory), all four of that entry's items reproduce unchanged:

| | CPython | compiled |
|---|---|---|
| `converting …` line | `converting readme.md to readme.py and readme.mapping` | identical |
| header | `""" Python Character Mapping Codec readme generated from 'run/readme.md' with gencodec.py.` | `… Codec readme generated from '4385725232' …` |
| entry lines | `    97: 0x0020,` etc. | literally `    (): (0x%0*X, 0x%0*X),` |
| `readme.mapping` | 577 bytes | **0 bytes** |

**Item 1 (the pointer digits) is ROOT-CAUSED and filed as
`CODEGEN_string_arg_type_lost_across_forwarding_hop.md`** — reduced from
this file's `convertdir` → `pymap` → `codegen` chain to three functions,
and the mechanism is not the call-site-argument-shape visibility the
2026-08-25 entry guessed but an ORDERING fact: the free-function scalar
observation loop runs before any function's parameters are refined, so a
parameter passed straight through a forwarding hop is recorded as
no-evidence and never re-examined. Not fixed here — the fix is a bounded
fixpoint on shared cross-call type machinery, and `_arg_scalar_type`'s
own docstring records the `ntpath.split` regression that a single
un-fixpointed flip causes.

Items 2-4 are unchanged and un-attempted: `%`-formatting of runtime-boxed
values has no lowering (`_lower_percent_format` handles statically-string
operands only), `codecs.make_encoding_map` is unmodelled so
`decoding_table` never gets built, and `marshal.dump` has no runtime
implementation at all (real CPython's binary marshal format is a
standalone feature).

Doc kept open on three runtime-content items, one of them now with a
filed root cause and a named next step.

## Status (re-verified 2026-08-26, wtOpencode_ctypesutil2): build exit 0; runtime content gaps byte-identical to the 2026-08-26 diagnosis

Fresh end-to-end rebuild (exit 0, ~75s) + run against current tree past
d3e758a on a fresh 2-file test dir, side-by-side with real CPython:
`converting readme.md to readme.py and readme.mapping` line still
byte-identical; header still prints pointer digits plus a stray leading
`\` (`Codec 4383170576 generated from '4383170464'`; real: `Codec
readme generated from '/tmp/genc_ref/readme.md'`); mapping entry lines
still emit literally `    (): (0x%0*X, 0x%0*X),`; decoding_table
section still absent; `.mapping` still 0 bytes (marshal.dump honest
stub). Source-confirmed both remaining roots are unchanged and
untouched by any of this campaign's landings: zero marshal.dump/load
runtime implementation exists anywhere (real CPython marshal binary
format — a large standalone feature), and `_lower_percent_format`
(gimple_exprtypes.py) still only lowers %-formatting whose operands are
statically strings (the `%0*X`-against-runtime-boxed-values shape has
no lowering). Neither attempted — genuinely missing feature machinery,
not narrow gaps. No code change. Doc stays open.

## Status (re-verified 2026-08-26, branch fix/rest-remainder15 — unchanged, both remaining gaps confirmed genuinely missing runtime/codegen machinery)

Fresh end-to-end rebuild + run against current tree (`a913ab8`):
`python3 fire.py build .../Tools/unicode/gencodec.py` exits 0; running
the binary on a 2-file test dir prints both `converting ...` lines
identical to real CPython and writes `readme.py`/`readme.mapping` (this
took a moment to reproduce correctly — real CPython's own
`convertdir()` writes output files relative to the CURRENT WORKING
DIRECTORY, not the scanned `dir`, since `dirprefix=''` by default and
`codefile`/`marshalfile` are never joined with `dir`; the compiled
binary matches this exactly, confirmed by a side-by-side run of real
`python3 gencodec.py` from the same cwd — NOT a compiled-path bug, a
red herring from testing with cwd == target dir the first time).
Content confirmed identical to yesterday's diagnosis: header line
prints pointer digits (`Codec 49241363248 generated from
'49237138400'`), `readme.mapping` is 0 bytes. Source-confirmed both
remaining gaps are still real: `grep -rn marshal` across
gimple_gen_calls.py/gimple_module_gen.py/gimple_gen_infra.py finds zero
runtime implementation of `marshal.dump`/`marshal.load` anywhere (real
CPython marshal binary format was never implemented, a large feature on
its own), and the `%`-format-of-runtime-boxed-values gap
(`_lower_percent_format`, gimple_exprtypes.py) is unaffected by any of
this campaign's other landings (int()/float() coroutine builtins,
generator-consumption ordering, etc. — none touch `%`-format lowering).
Neither attempted — both are genuinely missing feature machinery, not
narrow gaps. No code change.

## Status (2026-08-25 later): both diagnosed gaps FIXED; output files are
## now PRODUCED. Doc re-scoped onto the newly-reached %-formatting/marshal
## gaps inside the generated content.

Both 2026-08-25 gaps landed on `fix/opencode-gencodec2`, each gated clean
(test_gimple.py 256/256, test_module_cache.py 76/76, `make check-selfhost`
clean, from-scratch stdlib dylib rebuild with 0 `skip <module>:` lines —
baseline 0 held after EACH of the three commits):

1. **String-literal-default params — FIXED** (`da93b2d`).
   `_param_ctype` (gimple_gen_funcs.py) now resolves an unannotated param
   whose declared default is a `StringLiteral` to `char *`, when nothing
   more specific resolved (annotations, usage inference and the cross-call
   scalar contract keep precedence). Matches `_default_expr_to_pair`,
   which already lowers such defaults to real C strings at padded call
   sites; both pre-existing "respect default-value inference" skip-guards
   in gimple_module_gen.py's scalar-observation passes had anticipated this
   exact rule. Verified: the convertdir print is now byte-identical to
   real CPython (`converting readme.md to readme.py and readme.mapping`;
   was `43713230804...readme.py`). Note the free-function path was the one
   gencodec.py needs; a METHOD with a string-literal default still pads
   omitted args with NULL at its call sites (method-call padding doesn't
   consult `_func_param_defaults`) — out of scope here, gencodec.py has no
   such method.
2. **`append = l.append` bound builtin-container method — FIXED**
   (`d0ecc2b`). Container methods have no per-method C symbol for a
   MojoBoundMethod* fn pointer to point at (they lower inline per call
   site), so the binding is RECORDED instead: `_lower_builtin_method_value`
   captures the receiver into a hidden void* local (rebind-safe: an
   already-taken bound method keeps pointing at the original list),
   boxes the handle exactly as the old getattr path did (no ABI change),
   and `_builtin_method_values` carries `(receiver ctype, receiver local,
   method name)` through assignments via the same side-table propagation
   pattern as `_bound_method_ret_types`. Calls through such a value
   dispatch in BOTH call paths (`_lower_named_call` AND
   `_gen_stmt_ExprStmt`'s statement-level twin, checked before the fnptr
   guard that would otherwise call through the opaque box) into
   `_lower_list_method`/`_lower_dict_method`/`_lower_set_method` VERBATIM
   — identical behavior to the direct `l.append(x)` spelling, including
   per-site int/str element typing. Verified: doc's minimal repro prints
   2; string-append + join, rebinding semantics, and dict.get aliases all
   match real Python.
3. **Bonus root cause found while verifying #2 end-to-end — FIXED**
   (`bec9f96`): `map.items()` never reached the statically-typed dict
   lowering because `_infer_param_types`' member-access struct match
   treated the CALLED method name as FIELD evidence and matched the single
   registered struct having an `items` field — `WithStmt` (an unrelated
   internal AST node, `WithStmt.items: list`; exactly the "why does map
   infer to WithStmt*" mystery flagged unresolved in the 2026-08-09 note
   below). Called builtin-container method names are now excluded from
   struct-field evidence, and a dict-only method call (items/keys/values/
   setdefault) with no better signal infers `MojoDict *`. marshalmap/
   python_mapdef_code/codegen all resolve their `map` params correctly,
   the nested `for e,(u,c) in map.items():` pair loop genuinely iterates,
   and convertdir completes for every entry in the test directory.

### Where the file stands now

Running the built binary on `/tmp/genc_test/dir` exits 0, prints both
`converting ...` lines identically to real CPython, and WRITES all four
output files (readme.py/test_a.py + .mapping). The .py outputs have the
correct overall skeleton (header docstring, codecs imports, Codec/
Incremental classes, decoding_map entries from the real parsed mappings)
but still differ from `python3 gencodec.py` output:

1. **Header line prints pointer digits**: `Codec 4354047104 generated from
   '36524001536'` plus a stray leading `\` line (real: `Codec readme
   generated from '/tmp/genc_test/dir/readme.md'`). Root cause: codegen's
   giant header template does `% (encodingname, name, ...)`, but those
   strings arrive typed int64_t through the pymap→codegen forwarding
   chain (pymap's own unannotated params get no string signal — no
   concat/subscript/str-method in its body — and Pass 1.3d's plain
   observation can't see through `os.path.join(...)` results or string-op
   locals at convertdir's call site either). Same class as fixed gap (a),
   but the fix needs call-site argument typing to see through more
   expression shapes (or forwarding-chain propagation) — left open.
2. **Entry lines are raw/unformatted**: mapping entries emit literally
   `    (): (0x%0*X, 0x%0*X),` — hexrepr's `'%0*X' % (precision, t)`
   against runtime-boxed values doesn't lower (the `%`-format machinery
   only handles cases where operands are statically strings), and tuple
   keys repr as `()`. This is the `%a`/`%`-formatting-of-runtime-values
   gap predicted below, now precisely located.
3. **decoding_table section missing / encoding_map empty**:
   python_tabledef_code produces nothing (so suffix takes the 'map'
   branch) and `codecs.make_encoding_map(map)` returns an empty dict —
   both unmodeled builtins/shapes, as predicted below.
4. **`.mapping` files are 0 bytes**: `marshal.dump(d, f)` ('wb' mode) is
   an honest stub — predicted below, unchanged.

Items 1–4 are all INSIDE the generated file content; the compile itself
and the whole convertdir control flow are correct. Given each remaining
item is another layer of the shared %-format/marshal/builtin modeling
work (not this doc's originally-diagnosed gaps), re-scoped here and left
for dedicated follow-ups rather than force-fixed.

### Why the doc stays open: first divergences from real CPython (both DOWNSTREAM of the fixed loop)

[2026-08-25 earlier analysis — gaps 1+2 above since FIXED]

The 2026-08-23 iteration gap is fixed for real. Branch
`fix/opencode-gencodec`, commits `6dce849` + `bdabb8a`. Four separate
root causes had to land before the loop body genuinely executed:

1. **`os.listdir` was an opaque stub returning the module marker itself.**
   The call fell through every module-method case in `_lower_method_call`
   to the generic scalar-receiver stub (`int64_t.listdir() stubbed`),
   which returned the `os` module marker (an int64_t) as the "list"; the
   for-loop then hit the not-a-registered-container fallback and ran zero
   times (`mojo_unsupported_iter`). Fixed with a real runtime helper,
   `mojo_listdir(path)` (runtime/mojo_runtime.c: opendir/readdir, "."/".."
   excluded), wired through `_lower_method_call`'s module-method dispatch,
   `_KNOWN_SIGS`, and both type-inference pre-passes (result infers as
   `MojoList *` of `char *`). Verified byte-for-byte against real CPython:
   a standalone repro iterating `/tmp/genc_test/dir` prints identical
   entries in identical (readdir) order with an identical count.
2. **`os.path.isfile` was a literal-0 stub** ("not a file"), so even with
   listdir fixed, `if not os.path.isfile(mappathname): continue` was
   UNCONDITIONAL — every iteration silently skipped, zero visible
   behavior. Fixed with `int_isfile` (S_ISREG twin of the existing
   `int_isdir`); the generator-body path (gimple_cpp_core.py) mirrors the
   same real helper now instead of its old literal-0 copy.
3. **`os.path.split(mapname)[1]` never reached any real lowering** — the
   chained `os.path.*` block had no `split` case, so it fell through to
   generic string-method dispatch with the `os.path` MODULE MARKER coerced
   into the SEPARATOR argument (`mojo_str_split((char *)0, mapname)`),
   i.e. element [1] of a whitespace-split of the path. Fixed with
   `int64_t_path_split` (cpython posixpath.split semantics verbatim,
   returned as a 2-element string list exactly like the existing splitext
   lowering). A standalone repro of convertdir()'s whole name-mangling
   prologue (listdir → join → isfile-guard → split[1] → replace('-','_')
   → split('.')[0] → lower()) now produces output IDENTICAL to real
   `python3 gencodec.py`'s first stage.
4. **`convertdir(*sys.argv[1:])` passed the argv-slice LIST POINTER as
   `dir`.** A '*'-spread survives `_lower_UnaryOp` as a single
   `('MojoList *', lst)` pair, which the generic coercion cast to the
   FIRST fixed param's type — so `opendir(list-pointer-as-path)` failed
   and the (now-real) listdir returned an empty list, again zero
   iterations, silently. Fixed by `_expand_sole_spread_into_fixed_slots`
   (gimple_gen_calls.py), shared between `_lower_named_call` and
   `_gen_stmt_ExprStmt`'s statement-level twin per this project's
   consolidate-duplicates rule: expands a sole '*'-spread across all
   fixed C param slots with per-slot in-range guards; out-of-range slots
   fall back to the callee's recorded parameter defaults (so
   `convertdir(dir)` still gets dirprefix=''/nameprefix=''/comments=1).

After all four: the built binary enters convertdir, iterates the real
directory listing, passes the isfile guard, and prints the
`converting <mapname> to ... and ...` line per entry — the loop body
provably executes end-to-end. Quality gates all clean at commits
`6dce849`+`bdabb8a`: test_gimple.py 252/252, test_module_cache.py 76/76,
`make check-selfhost` clean, from-scratch stdlib dylib rebuild with
0 `skip <module>:` lines (baseline 0).

### (Historical 2026-08-25 gap list, both since FIXED — kept for context)

Running `./gencodec /tmp/genc_test/dir` (one mapping file, one README,
one subdirectory) vs real `python3 gencodec.py` on the same dir:

1. **Garbage string prefixes from int64_t-typed string-default params.**
   Real: `converting readme.md to readme.py and readme.mapping`.
   Compiled: `converting readme.md to 43713230804371323080readme.py ...`.
   Root cause: `convertdir(dir, dirprefix='', nameprefix='', comments=1)`
   — an UNANNOTATED param whose default is a string literal still gets
   typed `int64_t` (`_param_ctype` consults only annotations and call-site
   usage inference, never the default expression), so `nameprefix + name`
   lowers as int-concat: `mojo_str_from_int(<boxed char* pointer>)`
   formats the pointer's decimal digits. The call site dutifully passes
   interned `""` as int64_t, so the value is a real string pointer being
   printed as an integer. Fix shape: teach `_param_ctype` that an
   unannotated param with a StringLiteral default is `char *` — small but
   signature-changing across every similarly-shaped function, so it needs
   its own gates pass (mangling/suffix implications), NOT smuggled into a
   doc-closing commit. (Note `comments=1` already works: an int default
   happens to coincide with the int64_t box.)
2. **`Unhandled exception: AttributeError: append` — a container method
   referenced as a first-class VALUE.** After the print, pymap → codegen →
   `python_mapdef_code` does the classic aliasing idiom `l = [];
   append = l.append; append(...)`. `_lower_bound_method_value` /
   MojoBoundMethod* covers USER-STRUCT methods only; a builtin-container
   member read as a value falls to generic getattr and raises at runtime.
   Minimal repro (compiles today, fails identically):
   `def g(): l = []; append = l.append; append(1); print(len(l)); g()`.
   This blocks python_mapdef_code/python_tabledef_code entirely, hence
   no .py/.mapping output files are produced yet.

Not yet reached (unverified, likely further gaps once 1+2 land):
`marshal.dump(d, f)` ('wb' mode), `codecs.make_encoding_map`,
`sorted(map.items())`, `%a` formatting in python_tabledef_code.
[2026-08-25 later: confirmed — see the re-scoped list in the current
status block above; `sorted(map.items())` itself works once map is
MoDict-typed, but %-formatting of runtime values does not.]

No-arg invocation divergence (minor, noted for completeness): real Python
raises TypeError (missing `dir`); the compiled binary now unpacks an empty
argv-slice into all-NULL/defaults and exits 0 having iterated nothing.
Honest-stub territory, harmless here, but not byte-equivalent.

## Status (2026-08-23, historical — superseded by 2026-08-25 above)
## COMPILED end-to-end (both old issues fixed);
## runtime smoke test exposed the (now-fixed) iteration gap.

`python3 fire.py build /Users/mrs/net/Python-3.14.6/Tools/unicode/gencodec.py`
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
error; `python3 fire.py build` now gets past this line entirely.

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
generated C and locating GCC's real line numbers directly. `fire.py build`'s
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
