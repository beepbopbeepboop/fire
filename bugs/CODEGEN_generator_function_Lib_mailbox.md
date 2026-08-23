# CODEGEN_generator_function: Lib/mailbox.py

## Status (updated 2026-08-23 — BOTH remaining "too few arguments" errors FIXED (struct-method default-arg padding); own-file .cpp down to 1 error, the unannotated-field family)

**Fixed**: `_mojogen__singlefileMailbox_iterkeys_impl` emitting
`_singlefileMailbox__lookup(self)` ("too few arguments... expected 2,
have 1") and `_mojogen__ProxyFile___iter___impl` emitting
`_ProxyFile_readline(self)` — both are `self.<method>()` calls OMITTING a
defaulted trailing parameter (`def _lookup(self, key=None)`, `def
readline(self, size=None)`) inside a compiled generator body. The
coroutine-body struct-method call branches (`self.`/`cls.`/
`<struct-ptr-local>.`) emitted given arguments verbatim; they now share a
padding helper (arity from `func_param_types` incl. the receiver slot,
real declared defaults via `_default_expr_to_pair` — registered per bare
mangled key by gen_module's method pre-pass — falling back to the None/0
box exactly like the ordinary path's own padding loop). Commit: `8efc157`.
Verified end-to-end with a compiled-and-run repro
(`generator_self_method_defaulted_arg`: `self.scaled()` → default 2 ×100 =
200, `self.scaled(5)` → 500).

Also improved incidentally by the same session's list-literal work: this
doc's old `lines = []`-style accumulators inside generator bodies now get
real MojoList* locals.

**mailbox.py's own .cpp is down to ONE error**: line 240
`self->_toc.keys()` — `_toc` is typed int64_t because `__init__` assigns
it dynamically (`self._toc = None` then `{}`) with no annotation: the
SAME unannotated-init-param/field hard-bug family tracked elsewhere, not
a generator-machinery bug. Plus the usual transitively-imported-file
errors in the whole-program build. Not attempted here.

Full mandatory gate (CLAUDE.md): test_gimple.py 250/250,
test_module_cache.py 76/76, make check-selfhost clean, from-scratch
stdlib dylib rebuild 0 skip lines before and after.


## Status (updated 2026-08-20 — unbound-instance-method arity bug FIXED; file still blocked by 2 other, unrelated errors)

Root-caused and fixed the `too many arguments to function
'Mailbox___init__'; expected 4, have 5` (line 634) and `too many
arguments to function '_ProxyFile__read'; expected 3, have 4` (line
2126) errors — both real instances of the pre-`super()` cooperative-
inheritance idiom `BaseClassName.method(self, other_args...)`
(`Mailbox.__init__(self, path, factory, create)` /
`_ProxyFile._read(self, size, read_method)`), an ORDINARY (non-static,
non-classmethod) instance method called unbound-style with `self`
passed explicitly by the caller.

`gimple_codegen.py`'s `_lower_call` "Class/static method call" gate
(`IdentExpr(ClassName).method(args)`, ~line 13020) only distinguished
`@staticmethod` (no implicit arg) from everything else (always prepend
the class-ref value as an implicit first arg) — correct for a real
`@classmethod` call, but wrong for this unbound-instance-method idiom,
which double-counted `self` (caller already passed it) on top of the
wrongly-prepended class-ref value. Fixed by gating the prepend on
`self._classmethod_names` (real classmethods only — explicit
`@classmethod` or the two dunders Python makes implicit classmethods)
instead of `not in self._static_methods`; a static method still falls
through to the same no-prepend `else` branch as before (the two sets
are populated by mutually-exclusive checks).

Also fixed a related, latent cross-module sharing gap found while
verifying this: `_static_methods`/`_classmethod_names` were never
propagated into `_compile_imported_module`'s nested `temp_gen`
instances (unlike `func_return_types`, which IS shared there) — so a
class dedup'd-away by `self._compiled_modules` (compiled once, while
processing an earlier sibling/ancestor module) would leave a LATER
importing module's own local `_classmethod_names` empty for that
class's methods, even though the (correctly, globally-shared)
`func_return_types` still finds the mangled symbol and fires this call
site. Before this session's fix, that silently defaulted to "prepend"
(happened to be right for classmethods, wrong for statics via the same
dedup path); after gating on `_classmethod_names`, an un-shared, empty
set would have wrongly flipped to "never prepend" for a real cross-
module-deduped classmethod call — a NEW regression this fix would have
introduced without also sharing the two sets. Fixed by adding
`temp_gen._static_methods = self._static_methods` /
`temp_gen._classmethod_names = self._classmethod_names` alongside the
existing `func_return_types` sharing line.

Verified via isolated `compile_to_gimple(do_imports=False)` +
`gcc-mp-15 -fgimple -fsyntax-only`: A/B'd against the pre-fix code (via
a temporary `git checkout --` of just `gimple_codegen.py` in this same
worktree, restored after) — mailbox.py's own distinct errors went from
4 (2 target arity errors + 2 unrelated: `mailbox.py:32` int/pointer
mismatch, `mailbox.py:404` `cte` not callable) down to 2 (the same 2
unrelated ones, confirmed still present and NOT touched by this fix).
Also verified via a real `mojo.py build` whole-program run (not just
isolated compile) — same result, 4 -> 2 own-file errors, `grep -c
"too many arguments\|too few arguments"` for `Mailbox___init__`/
`_ProxyFile__read` specifically: zero after, matching before.

Also verified the fix generalizes and doesn't regress the real
classmethod idiom: isolated `Base.classmethod_name(args)` repro
compiles AND runs end-to-end with the correct result (`Base.double_of(5)`
-> `10`), and an unbound-`self`-cast base-`__init__` repro
(`Derived.__init__` calling `Base.__init__(self, v)`) compiles and
runs with the correct field value read back afterward (`Derived(7).val`
-> `7`, when Derived adds no fields of its own — see the SEPARATE bug
this verification surfaced, `bugs/hard/
CODEGEN_struct_typedef_alphabetical_field_order_breaks_inheritance_
layout.md`, for a case where Derived DOES add its own fields).

mailbox.py **still does not build** — the same 2 non-generator,
non-arity errors from the 2026-08-11 entry below remain (`mailbox.py:32`
int/pointer mismatch and the `cte` "not a function or function
pointer" at line 404), plus errors in transitively-compiled files.
Not investigated here (out of scope for this fix). Doc kept open.

Full mandatory gate (CLAUDE.md): `test_gimple.py` 248/248 (unchanged),
`test_module_cache.py` 76/76 (unchanged), `make check-selfhost` clean,
from-scratch stdlib dylib rebuild 0 skipped both before and after (A/B
via a separate `git worktree add` checkout at the pre-fix commit, not
`git stash`), `compile_stdlib.py -j8` 664/664 clean both before and
after — no regression anywhere.

## Status (updated 2026-08-20 — bug #2 (`email_message_Message_*` redefinition) FIXED; file still blocked by other, unrelated errors)

Root-caused and fixed bug #2 from the 2026-08-11 entry below (the
`redefinition of 'email_message_Message___str__'` cluster, ~45 sibling
methods). The 2026-08-11 entry's own guess ("an inherited-method stub
emitted under the base class's own qualified symbol name") was exactly
right, traced to its precise mechanism in
`gimple_codegen.py`'s `_struct_method_qualifier`
(~line 25808): `mailbox.py` defines its own `class Message(email.
message.Message):` — a genuine subclass, bare-named identically to its
real imported base. `_merge_struct_inheritance` correctly splices the
base's own method objects (by reference) into mailbox.py's derived
struct's `.methods` so each concrete struct gets its own callable
copies (no C++ vtable in this codegen). But `_struct_method_qualifier`
checked the shared, whole-program `_imported_struct_home` registry
(keyed purely by bare struct name, registered when Phase 0 compiled
the REAL `email.message.Message`) BEFORE checking whether the struct
being emitted right now is genuinely LOCALLY declared in the file
currently being compiled (`_local_struct_names`) — so mailbox.py's own
"Message" struct's methods (both the spliced-in inherited ones AND its
own locally-overridden ones like `__init__`) all got wrongly qualified
as `email_message_*`, colliding with the base module's own genuine
emissions.

Fixed by reordering the two checks: a struct genuinely declared in the
CURRENTLY-compiling module's own top-level stmts now always wins that
module's own qualifier, checked before falling back to the shared
imported-struct registry. This only changes behavior for the narrow,
genuinely-ambiguous case (a bare name present in BOTH sets at once);
every other struct's qualification is unchanged (see the code comment
at that call site for the full reasoning and additional real-world
instance found: `Lib/typing.py`'s own `_CallableGenericAlias`, bare-name
identical to `Lib/_collections_abc.py`'s unrelated class of the same
name, hit the exact same mechanism and is now also fixed).

Verified via a fresh `python3 mojo.py build
/Users/mrs/net/Python-3.14.6/Lib/mailbox.py`: zero
`email_message_Message_*`/`email_message_*` redefinition errors (was
48). **mailbox.py still does not build** — 11 errors of its own plus
many more in transitively-compiled files (`argparse.py` 40,
`codecs.py` 36, `email/message.py` 35, `email/generator.py` 22,
`typing.py` 16, `inspect.py` 14, `enum.py` 10, `posixpath.py` 9,
`os.py` 9, ...), none of them struct-collision-shaped anymore — a
completely different, much larger grab-bag of independent pre-existing
bugs, not investigated further here (out of scope for this fix). Doc
kept open.

Full quality gate: `test_gimple.py` 248/248, `test_module_cache.py`
76/76, `make check-selfhost` clean, from-scratch stdlib dylib rebuild
0 skipped (baseline via a separate `git worktree add` checkout at the
pre-fix commit: also 0 skipped), `compile_stdlib.py -j8` 664/664 clean
— all pass, no regression. Spot-checked
`bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`'s
own two real-world triggers (`Lib/tkinter/filedialog.py`,
`Lib/tkinter/simpledialog.py`) still build clean (unaffected, as
expected — they go through link mode, not this inline-path mechanism).

## Status (updated 2026-08-11 — RECLASSIFIED: generator/tuple-yield concern now fully FIXED; file blocked by 3 unrelated, pre-existing structural bugs, none generator-related)

Re-verified against current master via a fresh
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/mailbox.py`.

**The generator-codegen issue this doc originally tracked (tuple-valued
`yield (key, value)` in `Mailbox.iteritems`, and the follow-on
`mojo_cstr_slice` "forming reference to void" gap noted 2026-08-10) is
now completely gone.** No `RuntimeError: cannot compile module`
refusal, no `mojo_cstr_slice` error anywhere in the log; `Mailbox_
iteritems` (and every other `_iteritems`/`_popitem` generator-derived
function across all mailbox format subclasses) compiles clean, only
ordinary unused-variable/label warnings. This confirms this session's
tuple-yield boxing work (`_cpp_yield_tuple`) is genuinely complete for
this file.

mailbox.py **still does not build**, now purely due to non-generator
issues — investigated in real depth (traced actual root causes in
`gimple_codegen.py`, not just error text), genuine fix attempts made
on the first one, concrete blockers found on both:

1. **`too many arguments to function 'mojo_open_file'; expected 1, have
   2`** (mailbox.py lines 397, 395, 1108, 1110, 1128, 2186, plus
   `_ProxyFile__read` arity at 2126). Root cause fully traced:
   `_lower_named_call`'s builtin-`open` dispatch
   (`gimple_codegen.py:14449`, `if fname_raw == 'open' and 'open' not
   in self.func_return_types: return self._lower_builtin_open(node)`)
   is gated on a **global, non-module-scoped** dict. In this file's
   whole-program `do_imports=True` inline compile (triggered because
   `driver.compile_program`'s link-mode path returns `None` for this
   file), `Lib/tokenize.py`'s own module-level `def open(filename):`
   (and similar in codecs.py/gzip.py/bz2.py/lzma.py/wave.py/shelve.py/
   webbrowser.py, all transitively reachable) registers
   `self.func_return_types['open'] = ...` via the generic free-function
   registration at `gimple_codegen.py:22802`
   (`self.func_return_types[node.name] = ret_type`) — keyed by bare
   name only, no module qualifier. Once ANY transitively-compiled
   module defines a top-level `open`, the guard flips false *for every
   module in the same translation unit*, so mailbox.py's own genuine
   `open(path, mode)` builtin calls fall through to generic call
   lowering, which maps bare `open` to `mojo_open_file` (the 1-arg
   builtin-open C symbol) via `BUILTIN_VALUE_MAP` and passes both
   arguments positionally — hence the arity error.
   Traced further: `self.module_name`/`self._current_module_ctx` are
   **not actually module-scoped per originating function** in the
   whole-program inline path either — `self.module_name` is set once
   at `GimpleGen.__init__` and never changes as functions from
   different transitively-imported modules are code-generated in the
   same pass (confirmed by reading every `self._current_module_ctx =
   self.module_name or "root"` assignment site — all unconditional,
   none keyed off which module a given `FunctionDef` actually came
   from). So there is no cheap per-call-site "is `open` really shadowed
   in THIS module" check available today.
   **Fix attempted and rejected**: unconditionally routing bare
   `open(...)` calls through `_lower_builtin_open` (dropping the
   collision guard entirely) would fix mailbox.py, but is a **real,
   confirmed regression** against another file already in the 664-file
   gate corpus — `Lib/webbrowser.py` deliberately shadows the builtin
   (`# Please note: the following definition hides a builtin
   function.`) and its own `open_new(url)`/`open_new_tab(url)` genuinely
   bare-call `open(url, 1)`/`open(url, 2)` expecting **its own**
   3-arg `open(url, new=0, autoraise=True)`, not the file-open builtin.
   Verified this is a real, load-bearing case (not dead code) by reading
   the call sites directly. A correct fix needs real per-module
   free-function-name scoping in the whole-program inline compile path
   — currently absent entirely (not just for `open`, the same
   `self.func_return_types[node.name] = ret_type` bare-key pattern
   applies to every free function in every merged module) — which is
   the same class of foundational, shared bare-name-collision machinery
   already documented and deliberately deprioritized for **structs** in
   `bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md`.
   That doc currently asserts the bug is "structurally unreachable"
   through `mojo.py build`'s primary (link-mode) path and only reachable
   via the inline fallback or `--dump-full`; this file is a **live,
   concrete counter-example** — `driver.compile_program` fails for
   mailbox.py and falls back to the inline path, which is exactly where
   the collision (now confirmed to also affect free functions, not just
   struct types) actually bites. Left a cross-reference note in that
   doc.

2. **`redefinition of 'email_message_Message___str__'`** (and ~25
   sibling methods) at mailbox.py:1564 (`class Message(email.message.
   Message):`), conflicting with `email/message.py`'s own definitions
   in the same translation unit. Root cause not fully traced (budget
   went to bug #1 above) but the signature — a subclass that doesn't
   override a base method apparently gets an inherited-method stub
   emitted under the *base class's own qualified symbol name*
   (`email_message_Message___str__`) rather than a subclass-specific
   one, colliding with the base class's real definition once both are
   in the same whole-program unit — looks structurally related to
   bug #1 (another bare/under-qualified symbol-naming gap in the same
   whole-program inline path), not to generators.

3. `type mismatch in 'pointer_diff_expr'` at mailbox.py:1299 — not
   investigated (unreached in priority order; likely also downstream of
   #1/#2 once those are fixed, or a separate narrow issue).

None of 1-3 involve `yield`/`yield from`/coroutine lowering in any way.
**Doc kept open** (file still doesn't build) but reclassified: this is
no longer a generator-codegen bug. Suggest renaming/refiling under a
non-generator bare-name-collision bucket in a future pass, once
resolved — left as-is here since the required workflow for this task
is scoped to re-verifying/fixing the generator concern specifically.

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs (this file included, per the 2026-08-06 entry below).
Confirmed via a fresh `python3 mojo.py build` rebuild: this file has
**zero** occurrences of that exact error — it was already fully fixed
by the two already-landed mechanism-1/mechanism-2 fixes referenced
below (`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md`, deleted as resolved), consistent with this doc's own
2026-08-07 note. Not this file's live blocker; no re-classification
needed.

While tracing the pattern's mechanism, found and fixed one closely
related, previously-undocumented residual bug in the same struct-
family area: `_gen_struct_method`/`_gen_lifted_closure` (gimple_
codegen.py) never set `self._current_module_ctx`, so a `global`-
statement write inside a class method (or a closure nested in one)
compiled as the FIRST thing in its module's own recursive compile
inherited stale/default module context and routed the write to the
wrong module's globals struct (typing.py's `_LazyAnnotationLib.
__getattr__` was the confirmed repro: `struct '_root_toplev' has no
member named '_lazy_annotationlib'`, since the write landed on the
ENTRY module's struct instead of typing's own). Also fixed a related
`_safe_coerce_emit` gap (`is_field` only recognized `->`-accessed
struct fields, not plain `.`-accessed ones, causing an invalid
combined cast+store GIMPLE statement once the write-target routing
above was corrected). Full details/verification in `bugs/hard/COMPILE_
FAIL_module_toplev_struct_never_fully_defined.md`'s history and this
session's commit message.

Effect on this file: total build error count dropped 651 -> 649 (2
fewer — the fixed bug's own signature) via a fresh rebuild; the
tuple-yield-then-`mojo_cstr_slice` blocker described below is
unaffected and remains this file's real blocker. No reclassification.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a separate, pre-existing gap now blocks)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes` — boxes a tuple's elements into a real `MojoList *` at the
yield site). Confirmed via an isolated compile: `Mailbox.iteritems`'s
`yield (key, value)` (line 129) is no longer refused. Its OWN
`co_yield`/boxing text is syntactically valid, correctly heterogeneous
C++ — `key` boxed via `mojo_list_append_int`, `value` (correctly
inferred `char *`, from an earlier `mojo_cstr_slice` assignment) via
`mojo_list_append_str` — no g++ errors on those lines.

**mailbox.py still does not build**, blocked by an INDEPENDENT,
pre-existing gap one statement earlier in the SAME function:
`value = mojo_cstr_slice((char *)(self), key, (key) + 1);` — g++:
"forming reference to void" (a call-signature/return-type mismatch for
`mojo_cstr_slice` in the coroutine-body expression lowering). Unrelated
to tuple-yield. Matches this doc's own 2026-08-07 status, which already
predicted the next blocker would be the previously-documented
`mojo_open_file`-arity/type-mismatch cluster once tuple-yield unblocked
`iteritems` — the underlying non-generator issues in that cluster are
plausibly the same family as this `mojo_cstr_slice` finding, not
independently re-verified in full here.

Doc kept open (not deleted) — tuple-yield is no longer this file's
blocker, but the file genuinely still doesn't build.

## Status (updated 2026-08-09 — RECLASSIFIED: real tuple-valued-yield refusal, now the blocking error)

Re-verified against current master (`5ba7d4b`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/mailbox.py`.
The build now fails immediately, before reaching any GCC-stage error, on
a hard Python-level `RuntimeError` from `gen_module`
(`gimple_codegen.py:30968`):

```
Error building: cannot compile module: function(s) iteritems
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

Root cause, confirmed by reading the source: `Mailbox.iteritems`
(mailbox.py:122) does `yield (key, value)` at line 129 — a real
**tuple-valued yield** (parenthesized 2-tuple). This is the same
well-known, already-tracked structural gap as `ipaddress.py`'s
`_find_address_range` (see that bug doc's 2026-08-09 update for the
mechanism: coroutine promises only support a single scalar, and
`_infer_generator_yield_ctype`'s `TupleExpr` branch at
`gimple_codegen.py:2699-2724` now honestly refuses rather than
mis-emitting a broken `co_yield {a, b, c};`). This supersedes the
2026-08-06/07 statuses below — at that time `iteritems` apparently
compiled through the coroutine path without refusal (or wasn't yet
subject to this tightened check); a later session's work (visible in
current `gimple_codegen.py`) made the tuple-yield eligibility check
stricter, so `iteritems` now correctly aborts the whole-module compile
before any of the previously-reported `mojo_open_file`-arity/pointer-
conversion GCC-stage errors are even reached. mailbox.py's other 4
`yield`/`yield from` sites (lines 113, 456, 680, 2035) are all
single-value/delegating, not tuple-valued.

**Classification: matches the tracked "tuple-valued yield" structural
generator-codegen gap** — out of scope for a narrow fix per this task's
guidance. Not attempted here. The previously-noted `mojo_open_file`
arity mismatch and other non-generator GCC-stage errors are no longer
reachable until tuple-yield support (or a source-level workaround)
unblocks the whole module; left undisturbed below for reference.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. The
`struct _subprocess_toplev`/`struct _genericpath_toplev` "undefined
module-namespace pseudo-struct" errors quoted in the 2026-08-06 note
below are GONE (consistent with `bugs/hard/COMPILE_FAIL_module_toplev_
struct_never_fully_defined.md`'s "mechanism 2" fix having since landed).
Confirmed `MOJO_DEBUG=1` still shows NO "not eligible" refusal for any
of mailbox.py's own generators — all 5 `yield`/`yield from` sites still
compile cleanly through the coroutine path, same as before.

The build still fails, now on a large, entirely different batch of
non-generator `.ci` errors (~1300+ error lines, dominated by repeats
across mailbox.py's several near-identical mailbox-format subclasses):
`mojo_open_file` called with 2 args where 1 is expected (mailbox.py's
own `open(path, mode)`-shaped calls vs. this codegen's built-in
`mojo_open_file`'s fixed 1-arg signature), `assignment to 'char *' from
'int64_t'` at many sites in the 1470-1520 range, and repeated
`non-trivial conversion in 'component_ref'`/`type mismatch in
'pointer_diff_expr'` around lines 1299-1455. None of these are inside a
generator body or involve `yield`/coroutine machinery — **still NOT a
generator-codegen-cluster failure** — but this is a materially
different (and much larger) error set than the 2026-08-06 snapshot, so
not re-classified further here; worth a fresh, dedicated non-generator
investigation (starting with the `mojo_open_file` arity mismatch, which
looks like the most tractable/narrow of the batch) rather than folding
into this doc.

## Status (updated 2026-08-06, superseded above — struct_toplev errors since fixed)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'Mailbox'` .cpp error no longer reproduces. `mailbox.py` has
5 `yield`/`yield from` sites across several generator methods (lines
113, 129, 456, 680, 2035) — none appear in the current error list, and
`MOJO_DEBUG=1` shows no "not eligible" refusal for any of them: all of
mailbox.py's own generator bodies (including the `yield from
self._toc.keys()` delegation at line 680) now appear to compile cleanly
through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is the SAME `struct _subprocess_toplev`/`struct
_genericpath_toplev` "undefined module-namespace pseudo-struct" pattern
already seen in `Lib/glob.py`'s and `Lib/modulefinder.py`'s current
re-diagnoses (this is now the 3rd of my 41 files hitting this exact
signature — worth someone folding into its own non-generator hard-bug
doc once a 4th confirms the pattern):

```
/Users/mrs/net/Python-3.14.6/Lib/mailbox.py:78:28: error: invalid use of undefined type 'struct _subprocess_toplev'
/Users/mrs/net/Python-3.14.6/Lib/mailbox.py:282:30: error: invalid use of undefined type 'struct _genericpath_toplev'
```

Not investigated further — out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/mailbox.py
