# HARD BUG: setting/getting an arbitrary attribute on a generically-typed object

## Status

**Step 0 implemented and verified 2026-08-06** (see "Step 0" below for
what landed). **Steps 1-4 implemented and verified 2026-08-07** (see
"Steps 1-4 implementation notes" below) — real per-object dynamic-
attribute storage, a genuine catchable AttributeError on a miss, and
Sub-case C (fixed-layout runtime structs like `MojoBoundMethod`) all now
work end-to-end, confirmed via full compile+run repros (not just "stops
erroring at compile time"). **The residual gap (caught exception objects,
e.g. `Lib/pathlib/_os.py`'s `err.filename = ...`) is now ALSO fixed, as of
2026-08-18** — see "Residual gap FIXED (2026-08-18)" below for the
narrower, syntactic (not type-keyed) approach used. **A same-day-of-
landing regression that silently broke Sub-case C's own `.__name__`
handling on a `MojoBoundMethod` is now found + fixed, ALSO 2026-08-18**
— see "Regression found + fixed (2026-08-18): `self.prop.attr` auto-
invoke ate Sub-case C's `.__name__` again" below.

**Segfault pinned down 2026-08-19 — real bug, root cause identified, NOT
actually about dynamic attributes or opaque objects at all**: the vague
mention below turned out to be real and reproducible, but its true cause is
a much broader, pre-existing gcc-toolchain-level bug this doc's own Sub-case
A/B repro happens to trigger only because its OWN canonical shape
(`Slot.__set_name__`) is a **method** — see "Segfault root-caused: setjmp/
longjmp inside a `__GIMPLE`-tagged function" below for the full
investigation, why the fix attempted this session was reverted (real,
demonstrated regression risk elsewhere in self-hosting), and what's left
for a future session. Not closing this doc yet — the underlying bug is
real and unfixed, just precisely characterized now instead of vague.

<details><summary>Original vague note (superseded by the section below, kept for history)</summary>

Not yet closing this doc: while re-verifying the regression fix above,
the fixing agent's own report noted in passing that "a standalone
opaque-object (Sub-case A/B) variant segfaults both before and after this
fix (pre-existing, unrelated — confirmed via stash diff)". This was NOT
independently pinned down to a concrete repro — a follow-up manual check
this same session (`x = get_thing(...)` returning a plain `int64_t`,
`x.__name__ = "hi"`, `print(x.__name__)`) did NOT reproduce a segfault
(printed `hi` correctly), so whatever shape the agent actually hit remains
unidentified. Since Sub-case A/B's own official regression test
(`gimple_dynamic_attribute_real_storage_and_attributeerror` in
`test_gimple_runner.py`) passes, this is likely a narrower/different shape
than a plain opaque `int64_t` receiver — flagged here for whoever next
touches this area to pin down and reproduce properly (check the git log
around commit `a05a5c7`'s own session for any surviving scratch repro
files/notes) before considering this doc closable.

</details>

### Segfault root-caused (2026-08-19): setjmp/longjmp inside a `__GIMPLE`-tagged function

**The repro, finally pinned down**: NOT about opaque objects, dynamic
attributes, or any of the hypotheses this doc's own task list anticipated
(by-value copies, NULL receivers, GC/reuse, recursive structures, scale).
It's simply: **a `try`/`except` (or a `with` block whose context manager
has `__exit__`) inside a struct METHOD segfaults**, unconditionally,
regardless of whether any dynamic attribute is involved at all:

```python
class Slot:
    def helper(self):
        try:
            raise ValueError("boom")
        except ValueError:
            print("caught")

def main():
    s = Slot()
    s.helper()
    print("done")
```

`python3 mojo.py build` on this compiles clean and **segfaults on run**
(`Segmentation fault: 11`, zero output — not even `"caught"` prints). The
byte-identical body as a plain top-level FUNCTION instead of a method —

```python
def helper():
    try:
        raise ValueError("boom")
    except ValueError:
        print("caught")

def main():
    helper()
    print("done")
```

— compiles and runs correctly (`caught` / `done`). This is exactly why the
doc's own canonical Sub-case A/B repro (`Slot.__set_name__`, always
written as a *method* in every real-world confirmed instance —
`cls.__slot_names__`, `self.__hardroot`, etc.) segfaults while the
OFFICIAL regression test in `test_gimple_runner.py`
(`gimple_dynamic_attribute_real_storage_and_attributeerror`, whose
`get_or_init(cls)` is a plain top-level FUNCTION, not a method) and the
earlier session's own manual check (`get_thing()`'s result, also not a
method) both pass: **every previously-verified "working" instance of this
bug's own fix happens to use a free function; the doc's own minimal repro
and every real-world confirmed file instance use a method.** Confirmed
directly: `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`'s own
minimal repro (`Slot.__set_name__`, restructured as a real callable
`s.__set_name__(f, "a")` / `s.__set_name__(f, "b")` sequence) segfaults via
`python3 mojo.py build` + run; the identical logic lowered into a plain
function instead of a method does not.

**Root cause, precisely identified**: `gimple_codegen.py`'s
`_gen_struct_method` (struct/class methods) and `_gen_lifted_closure`
(lambda-lifted closures) unconditionally emit their C function signature
with the `__GIMPLE` keyword (`gcc -fgimple`'s "trust this body is already
lowered GIMPLE, skip normal C-frontend gimplification" marker) — this is
long-standing, pre-existing, and intentional (`gen_func`, the top-level
free-function path, has ALWAYS deliberately been the LENIENT, non-
`__GIMPLE`-tagged path instead — see its own pre-existing "LENIENT" comment
near the `.wait()` pending-exception fix). `_gen_stmt_TryStmt` and the
`with`-as-context-manager-with-`__exit__` path both lower to a real
`setjmp(_mojo_exc_stack[...])`/`mojo_raise()`→`longjmp(...)` pair
(`runtime/mojo_runtime.c`'s exception machinery, unrelated to this bug's
own dynamic-attribute work). **Calling `setjmp` from inside a function fed
to gcc as raw, already-lowered `__GIMPLE` reliably segfaults on the later
`longjmp`** — confirmed with a hand-reduced, entirely Mojo-independent C
repro (no dynamic attributes, no Mojo codegen involved at all):

```c
#include <stdio.h>
#include <setjmp.h>
jmp_buf buf;
void __GIMPLE gtest(void) {
  int a;
bb_2:
  a = setjmp(buf);
  if (a) goto bb_4; else goto bb_3;
bb_3:
  longjmp(buf, 1);
bb_4:
  printf("gimple caught\n");
  return;
}
int main(void) { gtest(); return 0; }
```

`gcc-mp-15 -fgimple isolate.c -o isolate && ./isolate` segfaults inside
`_longjmp` (confirmed via `lldb`: `EXC_BAD_ACCESS` inside
`libsystem_platform.dylib`'s `_longjmp`, called from `mojo_raise` /
`mojo_raise_attribute_error` in the Mojo-specific case). Memory-inspected
via `lldb` (`x/40gx &_mojo_exc_stack`): the jmp_buf slot `setjmp` supposedly
wrote into reads back as **all zero** at the moment `mojo_raise` attempts
the `longjmp` into it — i.e. the raw-`__GIMPLE`-fed function's `setjmp`
call never actually took effect the way a normally-gimplified C function's
would. This matches `-fgimple`'s own documented purpose (GCC's internal
IPA-pass testing harness, not a general-purpose production C subset): raw
GIMPLE input bypasses the normal C frontend's gimplification pass, which is
what marks a setjmp-containing function's CFG with the special
"returns-twice" abnormal-edge handling real setjmp semantics require
(disabling the optimizations that would otherwise clobber the
stack/register state a later `longjmp` needs restored). This is a
toolchain-level limitation, not a Mojo-specific logic bug — it affects
`gcc-mp-15 -fgimple` on this machine regardless of what Mojo source
produced the `__GIMPLE`-tagged C.

Confirmed via BOTH the real `mojo.py build` CLI (dylib-linked) path AND
`test_gimple_runner.py`'s own static-link style (`gcc -fgimple client.c
runtime/mojo_runtime.c`) — ruling out an earlier suspicion that this might
be a dylib/shared-library boundary issue (e.g. a `-fcommon` tentative-
definition split between the client and a separately-linked runtime
dylib): it is not link-mode-dependent at all, it reproduces identically
either way, confirming the bug is purely about `__GIMPLE`-tagging, not
linking.

**Fix attempted this session, REVERTED — real regression risk, not landed**:
tracked whether a function's own body actually emitted a `setjmp` (a new
per-function flag, `GimpleGen._func_used_setjmp`, set by
`_gen_stmt_TryStmt` and the `with`-exit path, reset in `_reset_func`), and
conditionally dropped the `__GIMPLE` tag for exactly those method/closure
bodies — mirroring `gen_func`'s own already-working lenient path. This DID
fix both the hand-reduced C repro's Mojo-shaped analogue and the doc's own
`Slot.__set_name__`-shaped repro end to end via `python3 mojo.py build`
(verified: correct output, no crash), and `test_gimple.py` (248/248),
`test_gimple_runner.py` (18/18), and `test_module_cache.py` (76/76) all
stayed green. **However `make check-selfhost` (the MANDATORY gate for any
`gimple_codegen.py` change) broke**: two SEPARATE, unrelated self-hosted
compile failures surfaced, neither involving dynamic attributes or even
directly involving a setjmp-affected function:
1. Applying the drop to lifted closures (`_gen_lifted_closure`) broke
   `gimple_codegen.py`'s own `_register_link_imports`'s nested `scan(stmts)`
   closure — its RECURSIVE SELF-CALLS (`scan(stmt.body)`) started failing
   with "makes pointer from integer without a cast" once `scan` itself lost
   `__GIMPLE` (its SIBLING nested closure `_exports`, defined earlier in the
   same enclosing method, genuinely does contain `try`/`except`, correctly
   triggering the flag for `_exports` itself — but something about a
   recursive closure's own self-call lowering behaves differently once
   emitted non-`__GIMPLE`, a separate, narrower call-lowering gap this
   session didn't have scope to isolate further).
2. Reverting JUST the closure change (keeping ONLY `_gen_struct_method`'s
   drop) surfaced a SECOND, different failure: `myinterpreter.py`'s
   `Scope.__init__` — a method with **no try/except in its own body at
   all** — started getting a "makes integer from pointer without a cast"
   at ITS OWN call sites elsewhere in the self-hosted compile. Since
   `Scope.__init__`'s own `__GIMPLE`-tag decision is unaffected by the
   fix (nothing in its own body sets `_func_used_setjmp`), this points to
   some other method EARLIER in the same compile losing `__GIMPLE`
   (correctly, for a genuine try/except) and something about THAT
   perturbing shared/cross-function type-inference state
   (`func_param_types`/forward-declaration generation) in a way this
   session did not get to the bottom of. **Verified via a direct control
   test** (forcing the `_gen_struct_method` drop back to a no-op while
   leaving all the new tracking/instrumentation code in place, otherwise
   byte-identical): `make check-selfhost` passes clean — proving the
   regression is genuinely caused by the conditional `__GIMPLE`-dropping
   logic itself, not incidental to some unrelated line-count/hash
   sensitivity in this large file.

Two alternative fixes were also explored and rejected:
- **`__builtin_setjmp`/`__builtin_longjmp`** (GCC intrinsics specifically
  meant to work without full frontend gimplification): fails to LINK under
  `-fgimple` on this machine/target (`undefined symbols:
  ___builtin_longjmp`, `___builtin_setjmp_setup` — arm64 `-fgimple`
  apparently never lowers these to real code, it just leaves literal calls
  to internal GCC helper symbols that don't exist as real library
  functions). Confirmed via the same kind of hand-reduced, Mojo-independent
  C repro used above.
- **Indirecting through an ordinary (non-`__GIMPLE`) runtime helper
  function** that does the `setjmp` internally, called via a normal
  function call from the `__GIMPLE` body (`_t1 = mojo_try_push();`)
  instead of inlining `setjmp` directly: unreliable, not a real fix —
  a minimal repro without debug `printf`s silently failed to unwind at all
  (execution fell through past the `longjmp` as if it were a no-op,
  continuing normally instead of returning to the catch point — WRONG
  output, not a crash, arguably worse: a silent miscompile); the
  byte-identical repro WITH debug `printf`s added crashed instead. Both
  outcomes point to genuinely undefined/fragile behavior for this
  indirection shape, not a dependable fix.

**Net result this session**: all code changes were reverted (working tree
is byte-identical to master's `1fe4eed`, verified via `git diff` producing
no output) rather than landing a fix with demonstrated regression risk to
`make check-selfhost` — per this project's own quality-gate rule, a change
that breaks self-hosting is not a landable fix regardless of how well it
fixes the target repro. **The segfault remains real, reproducible, and
UNFIXED** — this is now a precisely-characterized, separate, and
significantly BROADER bug than "dynamic attributes on generic objects"
(it affects ANY method or closure containing `try`/`except`/`with`-cleanup,
independent of dynamic attributes entirely) that deserves its own
dedicated follow-up session, ideally with more time to either (a) isolate
and fix the recursive-closure-self-call and cross-function-type-inference
regressions the naive fix surfaced, or (b) find a genuinely reliable way to
make `setjmp`/`longjmp` (or an equivalent non-local control-transfer
primitive) safe inside a `__GIMPLE`-tagged function on this toolchain.

**Verification performed this session** (no production code changes
landed, so the full mandatory 5-part gate was not re-run — per this
project's own documented exception, "if you only investigated and found
nothing [i.e. shipped no fix], a lighter sanity check is sufficient since
no production code changed" applies here, since the code diff is empty):
- `python3 test_gimple.py`: 248 passed, 0 failed (unchanged from baseline).
- `python3 test_gimple_runner.py`: 18 passed, 0 failed, INCLUDING both of
  this doc's own dynamic-attribute regression tests
  (`gimple_dynamic_attribute_real_storage_and_attributeerror`,
  `gimple_dynamic_attribute_fixed_runtime_struct_bound_method`) — both
  still pass because, as established above, neither uses a method, only
  free functions.
- `python3 test_module_cache.py`: 76 passed, 0 failed.
- The segfault itself re-confirmed reproducible on the final, fully-
  reverted tree (`git diff` empty against `1fe4eed`) immediately before
  writing this section, via both the doc's own restructured minimal
  repro and the free-standing `Slot.helper()`-shaped repro above, each via
  a fresh `python3 mojo.py build` + run.
- All previously-confirmed-working real-world verification-table instances
  are untouched (no code changed) and remain valid as documented in their
  own original sessions.

### Regression found + fixed (2026-08-18): `self.prop.attr` auto-invoke ate Sub-case C's `.__name__` again

The permanent regression test added for Sub-case C,
`test_gimple_runner.py`'s `gimple_dynamic_attribute_fixed_runtime_struct_
bound_method`, was found FAILING at the start of this session (confirmed
directly: `python3 mojo.py build` on the exact repro compiled clean, but
the binary crashed with `Unhandled exception: AttributeError: __name__`
instead of printing `read_nonlocal`/`11`; `python3 test_gimple_runner.py`
showed 17 passed, 1 failed, this test the only failure).

**Root cause, found via `git bisect`** (a real `bisect run` against the
exact repro, `dfc0bee` — Steps 1-4's own landing commit — as the known-good
endpoint, current `HEAD` as known-bad): commit `f1d786d` ("Fix self.prop.
attr chaining off a bound method/@property resolving wrong"), landed the
SAME DAY as Steps 1-4 but ~18 hours later (`dfc0bee` 02:18, `f1d786d`
20:37, both 2026-08-07). That commit added an unconditional auto-invoke to
`_lower_MemberExpr`'s general object-lowering path: whenever the lowered
receiver's C type is `MojoBoundMethod *`, it now calls
`mojo_bound_method_call_0` on it FIRST, before any member-name-specific
handling runs — including the `__name__` special case and the
`_FIXED_RUNTIME_STRUCT_NAMES` dynamic-dispatch fallback both further down
the SAME function, making both permanently unreachable for this shape.
That commit's own comment explicitly asserted "a real, intentional 'read a
member off the bound-method OBJECT itself' (e.g. `self.method.__name__`)
isn't supported by this codegen either way" — which was simply wrong
already at the moment it was written: Sub-case C (this doc, landed hours
earlier that same day) had already made exactly that case work. The
session that wrote `f1d786d` was targeting a different, real bug
(`self.filename.parent`-shaped property chaining, `Lib/zipfile/_path/
__init__.py`) and had no way to know about the same-day Sub-case C
landing without re-reading this doc — its own before/after spot-check
corpus never happened to include a `.__name__`-on-a-closure repro, so nothing
caught it, and no session since (multiple, per this doc's own commit
history) happened to touch this exact code path directly enough to notice
either.

**The fix**: narrowed the auto-invoke's own condition, in
`_lower_MemberExpr` (`gimple_codegen.py`, the `if ot == 'MojoBoundMethod
*':` block reached via `else: ot, ov = self.lower_expr(node.obj)`), to
also require `isinstance(node.obj, MemberExpr)` — i.e., only auto-invoke
when the `MojoBoundMethod *` value being chained off of was ITSELF just
produced by a fresh member-access expression (`self.prop.attr`: `node.obj`
is the inner `MemberExpr` `self.prop`), which is exactly the shape
`f1d786d`'s own repro and every real-world instance in its commit message
use. A `MojoBoundMethod *` value already sitting in a plain variable
(`node.obj` an `IdentExpr`, e.g. `f = make_closure(); f.__name__ = ...`)
no longer auto-invokes, so it falls through to the `__name__` special case
/ `_FIXED_RUNTIME_STRUCT_NAMES` dispatch exactly as Steps 1-4 intended.
This is a real, narrow distinction available in the AST at zero extra
cost — not a heuristic on member names (which Sub-case C's whole point of
supporting ARBITRARY dynamic attribute names rules out as a viable
discriminator).

**Verification**:
- The exact failing repro (`f = make_closure(); f.__name__ = "read_
  nonlocal"; print(f.__name__); print(f())`) via `python3 mojo.py build` +
  run: now prints `read_nonlocal` / `11`, matching the test's expectation.
- `python3 test_gimple_runner.py`: 18 passed, 0 failed (was 17/1).
- The commit that introduced the auto-invoke's own target case, re-tested
  directly (a `self.prop.attr`-shaped repro — a `@property` on a class,
  read through a chained member access inside another method): still
  works, byte-for-byte identical output with and without this session's
  fix (`git stash` before/after comparison) — the narrowing genuinely
  doesn't regress what `f1d786d` fixed.
- Sibling repros re-verified: the caught-exception `err.filename = ...`
  repro from the 2026-08-18 "Residual gap FIXED" section above still
  prints `somepath` correctly (unaffected — that dispatch path never
  touches `MojoBoundMethod`). The opaque-object `cls.__slot_names__`-style
  Sub-case A/B repro (a fresh, not-in-suite variant of this doc's own
  minimal repro, built as a standalone class-based test rather than reusing
  the exact suite test) segfaults both BEFORE and AFTER this session's fix
  (confirmed via `git stash` before/after, byte-for-byte identical crash) —
  a genuinely pre-existing, unrelated gap in that specific variant shape,
  not something this session's change touches or should chase; the actual
  in-suite Sub-case A/B regression test
  (`gimple_dynamic_attribute_real_storage_and_attributeerror`) passes
  throughout.
- Quality gate: `python3 test_gimple.py` — 248 passed, 0 failed.
  `python3 test_module_cache.py` — 76 passed, 0 failed. `make
  check-selfhost` — clean. From-scratch stdlib dylib rebuild — clean, 0
  `skip <module>:` lines. `python3 compile_stdlib.py` (default jobs,
  full 664-file corpus) — 664/664 passed, 0 unexpected failures (unchanged
  from baseline).

### Steps 1-4 implementation notes (2026-08-07)

Implemented essentially as planned, in `runtime/mojo_runtime.c`/`.h` and
`gimple_codegen.py`:

- **Step 1 (runtime storage)**: `_mojo_dynattr_objects` (a lazily-
  allocated `MojoDict *` keyed by the object pointer's hex text, reusing
  `MojoDict`'s existing string-keyed hash table rather than a second
  pointer-keyed one) + `_mojo_dynattr_key`, exactly as the plan's own
  pseudocode. `mojo_setattr` now actually stores; `mojo_obj_getattr` now
  actually reads.
- **Step 2 (real AttributeError)**: `mojo_raise_attribute_error(char *
  attr)`, mirroring the EXACT runtime call sequence compiled `raise
  AttributeError(...)` itself lowers to (`_gen_stmt_RaiseStmt`:
  `mojo_exc_type_set` + `mojo_exc_msg_set` + `mojo_exc_obj_set` +
  `mojo_raise`) — including `mojo_exc_type_set`, which the plan's own
  illustrative pseudocode omitted. Without it, only the lenient
  untagged-exception fallback would match (correct for a single-handler
  `except AttributeError:` by coincidence, but not a real match, and
  wrong for a multi-handler try where `AttributeError` isn't the first
  clause). The tag is `GimpleGen._exc_type_id('AttributeError')` —
  `(zlib.crc32(b"AttributeError") & 0x7fffffff) or 1` = `1471495998`,
  computed once via Python and hardcoded as `_MOJO_EXC_TAG_ATTRIBUTEERROR`
  in the C runtime (this is a pure, deterministic function of the class
  name string per `_exc_type_id`'s own docstring, so a value computed
  once in Python and never revisited is safe as long as that function's
  algorithm doesn't change — flagged in the C comment so it stays
  discoverable if it ever does).
- **Step 3 (wire the dispatch)**: needed zero codegen changes, confirmed
  — `_mojo_dispatch_getattr`/`_mojo_dispatch_setattr`'s existing
  fallthrough already called `mojo_obj_getattr`/`mojo_setattr` (Steps
  1-2 alone make Sub-cases A/B work end to end).
- **Step 4 (Sub-case C, fixed-layout runtime structs)**: new
  `_FIXED_RUNTIME_STRUCT_NAMES = frozenset({'MojoBoundMethod',
  'MojoGenerator', 'MojoAsync'})`, checked at THREE write-side call sites
  (plain `AssignStmt` MemberExpr target, `AugAssignStmt` MemberExpr
  target, AND `MultiAssignStmt`/chained-assignment MemberExpr targets —
  see "A fourth call site found during verification" below for why the
  third one was necessary) and one read-side site (`_lower_MemberExpr`'s
  final "unknown struct field" fallback, which previously blindly emitted
  a raw `->member` access GCC rejects for a struct with no such field).

### A fourth call site found during verification, not in the original plan

The doc's own minimal repro (`slotnames = cls.__slot_names__ = []`) is a
**chained assignment** — Python's `a = b = c` shape, which this codegen
lowers via a wholly separate function, `_gen_stmt_MultiAssignStmt`, not
the single-target `_gen_stmt_AssignStmt` the plan's "gimple_codegen.py:
16498-16502" line reference pointed at. Running the repro through
`mojo.py build` immediately surfaced this: `MultiAssignStmt`'s own
`MemberExpr`-target handling had **neither** the opaque-object dispatch
(Sub-case A/B) **nor** the fixed-runtime-struct dispatch (Sub-case C) —
it unconditionally emitted a raw `ov->field = v`, for every target type.
Fixed by adding both checks there too, mirroring the single-target
branch exactly (including the `continue` to skip the shared fallback
write once handled). Worth flagging for anyone touching this dispatch
class of check in the future: **there are (at least) three distinct
write-side lowering functions for a `MemberExpr` target** (`AssignStmt`,
`AugAssignStmt`, `MultiAssignStmt`), and a fix scoped to just one or two
of them will compile clean for simple repros while silently missing the
chained-assignment shape specifically — which is exactly the shape this
bug's own canonical minimal repro uses.

### A fifth gap found during verification: `.__name__`'s own special case

`_lower_MemberExpr` has an EARLIER, unconditional special case for
`node.member == '__name__'` (the `type(x).__name__` / AST-walker
dispatch chokepoint, pre-existing and unrelated to this bug) that
returns a hardcoded `"<type>"` placeholder string for ANY receiver type
not in `self.struct_field_types` — including `MojoBoundMethod`,
intercepting `f.__name__` reads BEFORE they ever reach Step 4's new
fixed-runtime-struct branch further down the same function. Confirmed
via the Sub-case C repro below: it compiled and ran fine but printed
`<type>` instead of the dynamically-set name. Fixed narrowly: this
special case now routes through the same `_mojo_dispatch_getattr` (cast
back to `char *`, since `__name__` is always conceptually a string) when
the receiver is opaque OR a fixed-runtime-struct name — every OTHER
"not in struct_field_types" case (the special case's original, documented
purpose) keeps the original `"<type>"` stub unchanged.

### Residual gap: caught exception objects (found, NOT fixed)

`Lib/pathlib/_os.py`'s `except OSError as err: ... err.filename = ...`
(one of the doc's own confirmed real-world instances) is **still
broken** after Steps 1-4 — a real, distinct gap, not a verification
oversight. Traced via direct `.ci` inspection: the caught exception
object (`err`) is lowered as a bare `mojo_exc_obj_get()` result cast
directly to `char *` (`_t134 = (char *) _t133;`) — this runtime models
an exception's "object" payload as a plain message string, not a real
struct/object with its own identity. `err.filename = ...` therefore
tries to write through a `char *`-typed receiver, which is neither
Sub-case A/B (`ot` is `char *`, not `int`/`int64_t`/`void *`) nor
Sub-case C (`char *` isn't a `_FIXED_RUNTIME_STRUCT_NAMES` member) — it's
a genuinely different, third receiver-type shape this doc's Steps 1-4
scope never covered. Deliberately not fixed here: broadening the opaque-
dispatch condition to also match bare `char *` receivers would catch
this case, but `char *` is used PERVASIVELY throughout this codegen for
ordinary, unrelated string values — adding it to the same dispatch
condition risks matching unintended cases far outside this bug's scope
(this project's documented history of exactly this kind of narrowly-
scoped-looking change to shared dispatch/type machinery causing
hard-to-predict regressions — see `bugs/COMPILE_FAIL_collections___init__.md`
— made a same-session broadening attempt feel unjustifiably risky without
a much more careful, dedicated look at every other `ot in (...)` call
site sharing that exact tuple literal). Confirmed via direct `.ci`
inspection only (0 "structure or union" errors is the OTHER 4 confirmed-
instance files' verification method below) — `pathlib/_os.py` itself was
NOT re-verified against the full gate-style error-count comparison; it
simply still shows the exact same 2 "request for member 'filename'/
'filename2' in something not a structure or union" errors as before this
session's changes, unchanged.

### Residual gap FIXED (2026-08-18)

Fixed via the narrower alternative this section itself flagged as worth
trying instead of broadening the type-keyed `ot in (...)` dispatch
condition to include `char *`: key the new dispatch case off the
SYNTACTIC fact that a `MemberExpr`'s receiver is an identifier bound by an
`except <ExcType> as <name>:` clause, not off its C type. An ordinary
`char *` string variable is never introduced by an except-as binding, so
this can't accidentally widen to match unrelated string code, unlike the
rejected type-keyed broadening.

- **Tracking which names are except-as-bound**: a new per-function set,
  `GimpleGen._except_as_names`, populated/cleared by `_emit_except_handler`
  (gimple_codegen.py) using the exact same save/restore convention already
  used there for `_c_names`/`had_c_name`/`restore_c_name` (so sequential
  `except ... as e:` blocks in the same function, and nested/shadowed
  bindings, behave correctly — verified via a repro with two sequential
  `except OSError as e: / except ValueError as e:` blocks in the same
  function, both binding attributes on `e` correctly). Only added for the
  `char *`-typed binding case (builtin exceptions / bare `except as e`) —
  a struct-typed caught exception (a user-defined exception class already
  in `struct_field_types`) is untouched, since that case already has real
  field storage and was never part of this gap.
- **New dispatch call sites**: a new helper, `_is_except_as_member_target
  (obj_node)`, checks whether a `MemberExpr`'s `.obj` is an `IdentExpr`
  whose name is currently in `_except_as_names`. Added as a new `elif`
  branch (checked AFTER Sub-case A/B's `ot in (...)` check and Sub-case
  C's `_FIXED_RUNTIME_STRUCT_NAMES` check, so it only ever fires for the
  genuinely-uncovered case) at all three write-side call sites Steps 1-4
  already touched — `_gen_stmt_AssignStmt`, `_gen_stmt_AugAssignStmt`,
  `_gen_stmt_MultiAssignStmt`'s MemberExpr-target handling — routing
  through the SAME `_mojo_dispatch_setattr` Sub-case A/B/C already use.
  Factored into a small shared helper, `_emit_dynattr_setattr_dispatch`,
  since this would otherwise have been a FOURTH copy-pasted instance of
  that emission (Sub-case A/B and Sub-case C were already two separate
  copies at each of the three write sites — six total — before this
  change; the new case reuses one shared helper instead of adding a
  seventh/eighth/ninth).
- **Read side**: `_lower_MemberExpr`'s existing opaque-dispatch branch
  (`elif ot in ('int', 'int64_t', 'void *', 'char *') or ot in
  ('MojoList *', ...)`) turned out to ALREADY include `char *` in its type
  check — pre-existing, unrelated to this fix, and evidently added for a
  different reason at some earlier point (this session did not audit why;
  out of scope). So `err.filename` as a read already reached
  `_mojo_dispatch_getattr` before this session's changes — the real gap on
  the read side was TYPE, not dispatch: the call's result was always typed
  `int64_t` (the generic boxed default), so `print(err.filename)` printed
  raw pointer bits as a number instead of the string. Fixed with a second
  new piece of state, `GimpleGen._except_attr_str_fields` (a whole-program,
  NOT per-function-reset set, following the same convention as
  `_field_dict_val_types`/`_field_elem_types` right next to it in
  `__init__` — a field written in one function may be read in another):
  `_emit_dynattr_setattr_dispatch` records a member name into it whenever
  the value being written is `char *`-typed; `_lower_MemberExpr`'s
  existing `_boxed_ft = self._known_field_type(node.member)` computation
  (which already casts the boxed dispatch result back to a resolved type
  when non-None/non-`int64_t`) now also resolves to `char *` when
  `_known_field_type` found nothing AND the receiver is except-as-bound
  AND the member name was previously recorded as a string — reusing the
  EXISTING cast-back code path immediately below unchanged, not a new one.
  This mirrors the precedent set by the `.__name__`-special-case fix under
  Steps 1-4 above (also an unconditional "this attribute is always
  conceptually a string" cast), scoped here to attribute names actually
  observed being written as strings rather than assumed universally.
- **Verification**:
  - Minimal repro (`try: raise OSError("boom") except OSError as err:
    err.filename = "somepath"; print(err.filename)`) via `python3 mojo.py
    build`: compiles and RUNS, printing `somepath` (previously: compile
    error). Extended repro also confirmed: reading a never-set dynamic
    attribute on the same except-bound object raises a genuinely catchable
    `AttributeError` (`try: x = err.never_set except AttributeError:
    print("caught")` → prints the catch branch, not a crash), setting a
    SECOND attribute afterward and re-reading the first still round-trips
    correctly, the `AugAssignStmt` shape (`err.note += "-more"`) and the
    `MultiAssignStmt`/chained-assignment shape (`a = err.tag = "x"`) both
    work end to end.
  - Zero-regression check: an ordinary `char *` string variable literally
    NAMED `err` in a different function (never touched by an except-as
    binding) — `.` isn't applicable to a plain string in this repro since
    Python strings have no attribute syntax used this way, so the check
    used a same-named plain string var with ordinary string operations
    (`len()`, `+` concatenation) in one function while `err` is
    except-as-bound with attribute writes in a DIFFERENT function in the
    same compile unit — both behave correctly and independently, since
    `_except_as_names` is per-function state, exactly mirroring how
    `_c_names` already isolates the same kind of same-name-different-
    function collision for the exception-binding temp-rename mechanism
    this new set sits right next to. Two sequential `except ... as e:`
    blocks (different exception types, same bind name) in the SAME
    function also verified independent and correct.
  - Real `Lib/pathlib/_os.py` (`/Users/mrs/net/Python-3.14.6/Lib/pathlib/
    _os.py`), compiled via `gimple_codegen.compile_to_gimple(...,
    do_imports=True)` + `gcc -fgimple -fsyntax-only`: **0 errors of ANY
    kind** (not just 0 "structure or union" errors — the file now compiles
    fully clean). Confirmed via direct `.c` inspection that lines 158-159
    (`err.filename = source_f.name` / `err.filename2 = target_f.name`,
    inside `except OSError as err:`) now lower through
    `_mojo_dispatch_setattr`/`_mojo_dispatch_getattr` with interned
    `"filename"`/`"filename2"` key strings, instead of a rejected direct
    `->filename` access. (The file also has two OTHER, unrelated
    `err.filename = ...`/`err.filename2 = ...` write sites, at lines
    228-229 and 250-251, from a DIFFERENT pattern — `err = OSError(...)`
    directly assigned, not `except ... as err:` — that were already
    compiling clean before this session's changes, via the pre-existing
    Sub-case A/B opaque-object path; not part of this gap, not touched.)
- **Quality gate (2026-08-18)**: `python3 test_gimple.py` — 248 passed, 0
  failed. `python3 test_module_cache.py` — 76 passed, 0 failed. `make
  check-selfhost` — clean. From-scratch stdlib dylib rebuild — clean, 0
  `skip <module>:` lines. `python3 compile_stdlib.py` (default jobs, full
  664-file corpus) — 664/664 passed, 0 unexpected failures (unchanged from
  baseline). `python3 test_gimple_runner.py` — 17 passed, 1 failed
  (`gimple_dynamic_attribute_fixed_runtime_struct_bound_method`) — this
  failure is PRE-EXISTING and unrelated to this change: confirmed via
  `git stash` (reverting this session's `gimple_codegen.py` edit entirely)
  and re-running the same suite, which reproduces the identical single
  failure with this session's changes completely absent.

### Verification against real-world files (2026-08-07)

Direct `gimple_codegen.compile_to_gimple(..., do_imports=True)` +
`gcc -fsyntax-only` (0 "request for member ... in something not a
structure or union" errors is the pass criterion — a different,
unrelated error is an acceptable/expected outcome per this session's
established norm, since these are real, large, third-party files with
many independent gaps):

| file | doc's confirmed symptom | after Steps 1-4 |
|---|---|---|
| `Tools/c-analyzer/c_common/clsutil.py` | `cls.__slot_names__` (A/B) + `__del__._slotted` (C) | 0 "structure or union" errors (0 gcc errors at all); LINK fails on an unrelated, separate missing-symbol bug (`_Slot__ensure___del___lambda_1`, `_classonly_getter`) |
| `Lib/collections/__init__.py` | `self.__hardroot = _Link()` on opaque `self` | 0 "structure or union" errors; 6 unrelated errors (redefinition, pointer-type mismatches) |
| `Lib/ctypes/__init__.py` | `c_ubyte.__ctype_le__ = c_ubyte.__ctype_be__ = c_ubyte` on a class object | 0 "structure or union" errors; 2 unrelated "too many arguments" errors |
| `Lib/string/__init__.py` | `cls.pattern = re.compile(...)` in `__init_subclass__` | 0 "structure or union" errors; 2 unrelated "invalid conversion in gimple call" errors |
| `Tools/scripts/var_access_benchmark.py` | `inner.__name__ = ...` write + `f.__name__` read on `MojoBoundMethod` (Sub-case C) | 0 "structure or union"/"has no member named" errors; 2 unrelated "undeclared" errors |
| `Lib/pathlib/_os.py` | `err.filename = ...` on a caught exception object | **UNCHANGED** — see "Residual gap" above, a genuinely different receiver-type shape |

Two hand-written, self-contained repros were compiled AND RUN (not just
syntax-checked) end to end, confirming actual runtime behavior, not just
absence of a compile error — both also landed as permanent regression
tests, `test_gimple_runner.py`'s `gimple_dynamic_attribute_real_storage_
and_attributeerror` and `gimple_dynamic_attribute_fixed_runtime_struct_
bound_method`:

1. The doc's own minimal repro pattern (`try: x = cls.__slot_names__
   except AttributeError: x = cls.__slot_names__ = []`), extended to call
   twice with the SAME object: first call takes the `except` branch
   (`mojo_raise_attribute_error` genuinely fires and is genuinely caught)
   and initializes; second call takes the fast path and sees the value
   the FIRST call actually stored (`mojo_setattr`'s storage is real and
   persists per-object, not merely "no longer crashes"). Output matched
   exactly: `miss, initializing` / `after first call: 1` / `fast path,
   got: 1` / `after second call: 2`.
2. Sub-case C: a capturing closure (`MojoBoundMethod *`) gets `.__name__`
   set then read back, plus called — confirms both the write-side Step 4
   fix AND the separate `__name__`-special-case fix (see above) together.
   Output matched exactly: `read_nonlocal` / `11`.

### Quality gate (2026-08-07, Steps 1-4)

1. `python3 test_gimple.py` — 247 passed, 0 failed.
2. `python3 test_module_cache.py` — 76 passed, 0 failed (including the
   link-mode tiny-client-object size-budget check Step 0's own regression
   was found through).
3. `make check-selfhost` — clean.
4. From-scratch stdlib dylib rebuild — clean, 0 `skip <module>:` lines.
5. `python3 compile_stdlib.py -j8` — 664/664 passed, 0 unexpected
   failures (unchanged from baseline).
6. `python3 test_gimple_runner.py` — 18 passed, 0 failed (16 pre-existing
   + the 2 new regression tests above). Not one of the mandatory 5, but
   the only suite in this repo that actually EXECUTES compiled output and
   checks real stdout, which is what this fix's own correctness hinges
   on (compiling clean is necessary but not sufficient — Step 0's own
   `.__dict__`/`vars()` fix already documented this same distinction).

### Step 0 implementation notes

`obj.__dict__` (a `MemberExpr` with `.member == '__dict__'`, gated on
`struct_name in self.struct_field_types` — i.e. only for a struct with
statically-known fields, exactly Step 0's scope) and `vars(obj)` (the
1-arg builtin call, same gating) both now lower to a call to a new
`_mojo_dispatch_asdict(void *)` runtime-tag dispatcher, mirroring the
existing `_mojo_dispatch_fields`/`_mojo_dispatch_getattr` machinery
exactly. Each reflect-eligible struct gets a companion
`_mojo_asdict_<StructName>(StructName *)` that builds a real `MojoDict *`
of name→value pairs from the struct's own known fields (reusing the
per-struct field loop that already builds `_mojo_getattr_<sn>`/
`_mojo_setattr_<sn>`/`_mojo_fieldnames_<sn>`, not a second, separately-
maintained field enumeration), boxing every value via `mojo_dict_set_int`
— the same generic boxed-int64_t convention every other heterogeneous
`MojoDict *`/`MojoList *` this codegen builds already uses (see
`_mojo_generic_elem_repr`'s existing magnitude/registered-list-or-dict/
type-tag heuristic, which is what actually makes
`print(obj.__dict__)`/`pprint.pprint(retval.__dict__)` — the doc's own
real-world confirmed use case — print correctly: `{'name': 'hello',
'value': 42}`, not raw integers). Verified: a repro with `c.__dict__`
and `vars(c)` both compiled and ran, printing the correct dict repr for
a struct with a `char *` field and an `int64_t` field.

**Known limitation, by design, not a regression**: reading an individual
key back out of the resulting dict with a Python-level-typed expectation
(`obj.__dict__["name"]` used as a string, printed directly rather than
through the dict's own generic repr) prints the raw boxed int64_t
(pointer bits interpreted as a number), because a single `MojoDict *`
in this codegen has one static declared value type and there's no
runtime type tag stored per-key. This is inherent to how EVERY
heterogeneous/generic `MojoDict *`/`MojoList *` this codegen already
builds works (reflection tables, `dataclasses.fields()`'s field-name
list, etc.) — not something Step 0 introduces or could fix without a
genuinely new per-value type-tagging scheme, well outside "Step 0,
easiest, do first" scope. The confirmed real-world call sites
(`Tools/build/umarshal.py`/`deepfreeze.py`'s `retval.__dict__`) only
ever pass the whole dict to `pprint.pprint`, never re-subscript it with
a typed expectation, so this limitation doesn't block them.

**Gating to avoid a real regression found during verification**: an
early version emitted `_mojo_dispatch_asdict` and its forward
declaration unconditionally (matching its 4 siblings —
`_mojo_dispatch_getattr`/`setattr`/`fields`/`is_dataclass`, which
genuinely must stay unconditional since any module in a whole-program
closure might call bare `getattr()`/`dataclasses.fields()` on another
module's struct with no local trace of the call). Doing the same for
`_mojo_dispatch_asdict` regressed `test_module_cache.py`'s "reflect:
client object is tiny — bodies live in the dylib" size-budget check (a
link-mode client whose whole architectural point is staying tiny). Fixed
by gating both the per-struct `_mojo_asdict_<sn>` bodies and the
`_mojo_dispatch_asdict` dispatcher (definition AND forward declaration)
on a new shared flag, `GimpleGen._asdict_dispatch_needed` (a `set`, following
this codegen's established "shared mutable container across nested
temp_gens" pattern — see `_compiled_modules`/`_emitted_structs` etc.),
set by the two new call sites during lowering and checked at emission
time (which always happens after all lowering, so the flag is fully
populated by then regardless of import nesting). Verified: with no
`.__dict__`/`vars()` call anywhere in a compile, the dispatcher and its
per-struct bodies are entirely absent from the output, and
`test_module_cache.py`'s tiny-client-object check passes again.

Full 5-part quality gate after Step 0: `test_gimple.py` (247/247),
`test_module_cache.py` (76/76, including the size-budget check),
`make check-selfhost` (pass), from-scratch stdlib dylib rebuild (0
`skip <module>:` lines), `compile_stdlib.py -j8` (664/664, 0
unexpected — see this doc's own commit for the exact run).

## Symptom

`request for member 'X' in something not a structure or union` (GCC
`-fgimple` error), or (a second, distinct shape — see "Sub-case C" below)
`'MojoBoundMethod' has no member named 'X'`.

This codegen models attribute access (`obj.field`) as a real C struct-field
read/write, which requires knowing `obj`'s concrete struct layout ahead of
time. When `obj`'s static type can't be resolved to a known struct — most
commonly a bare, unannotated parameter whose real runtime type is something
generic like a class object (`type`) or a closure/function value — it falls
back to a generic `int64_t`/opaque representation with **no** attribute
storage at all.

## Minimal repro

```python
# dynamic_attr_repro.mojo
class Slot:
    def __set_name__(self, cls, name):
        try:
            slotnames = cls.__slot_names__
        except AttributeError:
            slotnames = cls.__slot_names__ = []
        slotnames.append(name)
```

## Real-world files exposing this (all confirmed live, 2026-08-06)

- `Tools/c-analyzer/c_common/clsutil.py` — `Slot.__set_name__`'s
  `cls.__slot_names__` (opaque `cls` param, Sub-case A/B below) AND
  `Slot._ensure___del__`'s `__del__._slotted = True` (Sub-case C below,
  `'MojoBoundMethod' has no member named '_slotted'`).
- `Lib/collections/__init__.py`'s `OrderedDict.__new__`: `self =
  dict.__new__(cls)` (opaque `self`) then `self.__hardroot = _Link()`.
- `Lib/ctypes/__init__.py`: `c_ubyte.__ctype_le__ = c_ubyte.__ctype_be__ =
  c_ubyte` at module top level, on a class object.
- `Lib/string/__init__.py`'s `Template.__init_subclass__`: `pat =
  cls.pattern = re.compile(...)`. (Also breaks `Lib/importlib/__init__.py`,
  which imports `string` transitively.)

### More real-world instances confirmed 2026-08-06 (Sub-case C, same as `__del__._slotted`)

- `Tools/scripts/var_access_benchmark.py`: `inner.__name__ =
  'read_nonlocal'` (setting `__name__` on a closure/`BoundMethod` value —
  a WRITE, same "fixed-layout runtime struct, unknown field" shape as the
  doc's own `__del__._slotted = True` example) and separately reads
  `f.__name__` on a `MojoBoundMethod` elsewhere in the same file
  ("'MojoBoundMethod' has no member named '__name__'").
- `Lib/importlib/_bootstrap.py`'s `PathFinder._resolve_filename`:
  `sep = cls._SEP` / `sep = cls._SEP = '\\' if ... else '/'` inside a
  classmethod — `cls` is the opaque implicit class-reference parameter,
  `_SEP` a lazily-stashed class attribute via the `hasattr`/
  `AttributeError`-catch idiom — "request for member '_SEP' in
  something not a structure or union".
- `Lib/importlib/__init__.py`'s `reload(module)`: `module.__spec__` read
  AND written (`module.__spec__ = _bootstrap._find_spec(...)`) on the
  bare, unannotated `module` parameter (any module object at the Python
  level) — "request for member '__spec__' in something not a structure
  or union".
- `Doc/tools/extensions/glossary_search.py` (Sphinx extension):
  `app.env.glossary_terms = {}` / `hasattr(app.env, 'glossary_terms')` —
  `app.env` is a `sphinx.environment.BuildEnvironment` instance from the
  third-party `sphinx` package (unresolvable to this compiler, same as
  `cls`/`self` being opaque in the doc's own Sub-case A/B examples above),
  and the WHOLE POINT of this code is Sphinx's own documented extension
  idiom of stashing arbitrary custom state on `app.env` via `hasattr`/
  dynamic-attribute assignment. "request for member 'glossary_terms' in
  something not a structure or union".
- `Lib/pathlib/_os.py` (confirmed 2026-08-06, via
  `bugs/COMPILE_FAIL_pathlib___init__.md`): `except OSError as err: ...
  err.filename = source_f.name; err.filename2 = target_f.name` —
  writing NEW attributes onto a caught EXCEPTION object. Same opaque-
  object shape as sub-cases A/B (the exception's real runtime type
  isn't one this compiler models with a known struct layout).
  "request for member 'filename'/'filename2' in something not a
  structure or union".
- `Tools/build/umarshal.py` / `Tools/build/deepfreeze.py`: `retval.__dict__`
  / `pprint.pprint(retval.__dict__)` where `retval`/the target is a KNOWN
  user struct (`Code`) — "'Code' has no member named '__dict__'". This is
  actually a THIRD variant, distinct from Sub-cases A-C: unlike `_slotted`
  (a genuinely NEW, never-declared field) or `.pattern`/`.__slot_names__`
  (opaque `cls`), `__dict__` here needs to return a real dict VIEW of the
  struct's OWN ALREADY-KNOWN fields (matching Python's real `obj.__dict__`
  semantics) — the fix doesn't need generic dynamic storage for this one
  specifically, it could reuse the EXISTING `_mojo_dispatch_fields`/
  `dataclasses.fields()` reflection machinery (already emits a
  `_mojo_fieldnames_<struct>()` per known struct) extended to build a real
  `MojoDict *` of name->value pairs instead of just a name list — worth
  implementing as an easy, narrow special case for `__dict__`/`vars()` on
  a struct with ALL-known fields, ahead of (or independent from) the full
  generic-dynamic-storage plan below, which remains necessary for the
  genuinely-new-attribute cases (Sub-cases A/B/C).

## What's ALREADY there (the key finding that shrinks this task)

This codegen already has a generic runtime-dispatch choke point for
exactly this situation, emitted once per module
(gimple_codegen.py:30332-30356):

```c
static int64_t _mojo_dispatch_getattr (void *obj, char *attr) {
  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);
  if (_tag == <known-struct-1-id>) return _mojo_getattr_<struct1>((...)obj, attr);
  ... /* one line per known struct */
  return mojo_obj_getattr(obj, attr);   /* <-- current dead end */
}
static void _mojo_dispatch_setattr (void *obj, char *attr, int64_t val) {
  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);
  if (_tag == <known-struct-1-id>) { _mojo_setattr_<struct1>(...); return; }
  ...
  mojo_setattr(obj, attr, val);          /* <-- current dead end */
}
```

And **every** codegen call site that lowers `obj.attr` (read or write) on
an opaquely/generically-typed value already routes through these two
functions rather than emitting a direct field access — confirmed by
reading the actual call sites, not assumed:

- Read: gimple_codegen.py:8470 (`ot in ('int','int64_t','void *') or ot in
  ('MojoList *', 'MojoDict *', ...)` branch of `_lower_MemberExpr`) and
  :13251/:13270 (a second, similarly-gated read path).
- Write: gimple_codegen.py:16496 (`ot in ('int', 'int64_t', 'void *')`
  branch of the assignment lowering) and :16737 (an augmented-assignment
  analogue).

So sub-cases A and B below (opaque `cls`/`self`/class-object values) need
**zero** new call sites in the lowering code — they already call into
`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr`. The only missing piece
is what those two functions do when no known-struct tag matches: today,
`mojo_obj_getattr` (runtime/mojo_runtime.c:2424) unconditionally
`fprintf`s a warning and returns 0, and `mojo_setattr`
(runtime/mojo_runtime.c:3335) is a silent no-op. Neither has ever
implemented real storage — this was always a deliberate stub, not a
regression.

## Sub-case C (`MojoBoundMethod` etc.): a separate, second gap

`__del__._slotted = True` does NOT go through the opaque-fallback path
above — `__del__` is a locally-defined closure, whose static type this
codegen already resolves to a *known* runtime struct (`MojoBoundMethod`).
The assignment lowering's `else` branch (gimple_codegen.py:16498-16502)
handles "known concrete struct type" by looking up the field with a
silent default:

```python
field_type = self.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
self._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{_safe_field(node.target.member)}")
```

For a user-defined Mojo class, a not-yet-seen field name here is fine —
`struct_field_types[struct_name]` is itself mutable and gets new fields
appended elsewhere as they're discovered (see `_collect_self_assigns`/
`_scan_body_for_local_field_access`), and the struct's actual C layout
grows to match (`target_def.fields.append(...)`, gimple_codegen.py:26503).
But `MojoBoundMethod` (and similarly `MojoGenerator`, `MojoAsync`, any
other **runtime-owned, fixed-layout C struct this codegen itself
defines**, as opposed to a user's own Mojo class) has a hardcoded C struct
definition in the runtime headers with no such extensibility — the
`.get(..., vtype)` default silently assumes the field exists and emits a
direct `->_slotted` access GCC then rejects because the struct genuinely
has no such member.

## Implementation plan

### Step 0 (independent, easiest, do first) — `__dict__`/`vars()` on a struct with all-known fields

Doesn't need Steps 1-4's dynamic storage at all. `_mojo_dispatch_fields`/
`_mojo_fieldnames_<struct>()` (gimple_codegen.py, emitted per reflect-
eligible struct — see the `reflect_structs`/`tag_cases_fields` preamble
emission near `_mojo_dispatch_getattr`) already returns a `MojoList *` of
FIELD NAMES for `dataclasses.fields()`. Add a companion `_mojo_asdict_
<struct>()` (or extend the existing one) that returns a real `MojoDict *`
of name->value pairs instead, by reading each known field off the
instance the same way `_mojo_getattr_<struct>` already does per-field —
then route `obj.__dict__` (a MemberExpr with `.member == '__dict__'` on a
value whose struct is known and reflect-eligible) and `vars(obj)` (the
1-arg form) to call it. Confirmed real instances: Tools/build/umarshal.py
Tools/build/deepfreeze.py's `retval.__dict__` where `retval: Code` (a
known struct with statically-enumerable fields) — "'Code' has no member
named '__dict__'".

### Step 1 — real per-object dynamic-attribute storage (runtime)

Add to `runtime/mojo_runtime.c`, next to `mojo_obj_getattr`/`mojo_setattr`:

```c
/* obj-pointer -> its dynamic-attribute MojoDict, keyed by the pointer's
 * hex text (reuses MojoDict's existing string-keyed hash table instead of
 * writing a second, pointer-keyed hash table implementation from scratch
 * for what is deliberately a RARE fallback path, not a hot one — see
 * mojo_obj_getattr's own docstring on why this path is only reached when
 * codegen couldn't resolve the access statically). Lazily allocated. */
static MojoDict *_mojo_dynattr_objects = NULL;

static void _mojo_dynattr_key(void *obj, char *buf, size_t buflen) {
    snprintf(buf, buflen, "%p", obj);
}

int64_t mojo_obj_getattr(void *obj, char *attr) {
    if (_mojo_dynattr_objects) {
        char key[32];
        _mojo_dynattr_key(obj, key, sizeof key);
        int64_t handle = mojo_dict_get_int(_mojo_dynattr_objects, key);
        if (handle) {
            MojoDict *attrs = (MojoDict *)(intptr_t)handle;
            if (mojo_dict_contains(attrs, attr))
                return mojo_dict_get_int(attrs, attr);
        }
    }
    mojo_raise_attribute_error(attr);   /* new — see Step 2 */
    return 0;  /* unreached: mojo_raise_attribute_error longjmps/raises */
}

void mojo_setattr(void *obj, char *attr, int64_t val) {
    if (!_mojo_dynattr_objects) _mojo_dynattr_objects = mojo_dict_new();
    char key[32];
    _mojo_dynattr_key(obj, key, sizeof key);
    int64_t handle = mojo_dict_get_int(_mojo_dynattr_objects, key);
    MojoDict *attrs;
    if (handle) {
        attrs = (MojoDict *)(intptr_t)handle;
    } else {
        attrs = mojo_dict_new();
        mojo_dict_set_int(_mojo_dynattr_objects, key, (int64_t)(intptr_t)attrs);
    }
    mojo_dict_set_int(attrs, attr, val);
}
```

Rename the doc comment above `mojo_obj_getattr` (currently says "there is
no dynamic module/object system at runtime to look this up in" — no
longer true once this lands) and update `mojo_runtime.h`'s declarations'
own comments to match.

This intentionally does NOT free `attrs` dicts when `obj` is freed — this
codegen has no object-lifetime/refcounting/GC story anywhere else either
(confirmed: no `free()` calls paired with any struct allocator in
gimple_codegen.py's `_alloc_*` emission), so a leaked per-object dict is
consistent with the rest of this runtime's existing memory model, not a
new regression.

### Step 2 — real AttributeError on a missing dynamic attribute

`mojo_obj_getattr`'s current abort-with-fprintf behavior was appropriate
for "codegen bug, should never happen" — but a MISSING dynamic attribute
(`cls.__slot_names__` before it's ever been set) is exactly the case the
bug's own minimal repro handles with `try/except AttributeError`, which
this compiler's exception machinery already supports for other error
paths (see `raise-never-worked-exception-hierarchy-fix` in memory — a
real, working typed-exception system exists: `mojo_raise`/exception-
hierarchy matching). Add a small `mojo_raise_attribute_error(char *attr)`
helper (formats a real `AttributeError` message including the attribute
name, calls the same `mojo_raise`-family entry point every other typed
exception in this runtime uses) so `except AttributeError:` in compiled
code around a missing dynamic attribute genuinely catches it — this is
required for the bug's OWN minimal repro to behave correctly, not
optional polish.

### Step 3 — wire the two dispatch functions to use real storage

`_mojo_dispatch_getattr`/`_mojo_dispatch_setattr`'s fallthrough lines
(gimple_codegen.py:30336, :30341) already call `mojo_obj_getattr`/
`mojo_setattr` — Steps 1-2 make those calls do the right thing with **no
codegen change needed at all** for sub-cases A/B (opaque `cls`/`self`/
class-object values). This is the highest-leverage part of the plan.

### Step 4 — Sub-case C: route fixed-layout runtime structs through dynamic dispatch too

In the assignment-lowering `else` branch (gimple_codegen.py:16498-16502)
and the parallel read-side "known struct" branch, add a check: is
`node.target.member` (or `node.member` for reads) actually present in
`self.struct_field_types.get(struct_name, {})`? If not, AND `struct_name`
is one of this codegen's own fixed runtime-owned struct names (a small,
enumerable set — `MojoBoundMethod`, `MojoGenerator`, `MojoAsync`, and any
other struct this file itself defines in `_emit_struct_defs`/the runtime
headers rather than one arising from a user's `class` statement — these
are already distinguishable from user structs since user structs all
appear in `struct_field_types` via `StructDef` processing, never
hardcoded), fall back to the same `_mojo_dispatch_getattr`/
`_mojo_dispatch_setattr` call emitted for the opaque case instead of a
direct `->member` access. A **user-defined** class hitting an unknown
field should keep its existing behavior (grow the struct, per
`_collect_self_assigns`) — this new check must be scoped to the fixed-
layout runtime set only, not user structs in general, or it would silently
change today's (working) dynamic-field-growth behavior for ordinary Mojo
classes into a slower dict-backed path for no reason.

### Step 5 — verification

1. The minimal repro (`dynamic_attr_repro.mojo` above) — `python3 mojo.py
   build` compiles clean, and (new, since Step 2 makes this meaningful) a
   `run`-mode test confirms the `try/except AttributeError` branch
   actually fires on the first call and the `else` branch (fast path,
   attribute already set) is hit on a second call with the same `cls`.
2. `Tools/c-analyzer/c_common/clsutil.py`, `Lib/collections/__init__.py`,
   `Lib/ctypes/__init__.py`, `Lib/string/__init__.py` (+ `Lib/importlib/
   __init__.py` transitively) via `py314_harness.py`/direct `mojo.py
   build` — confirm each file's specific error from this doc is gone (a
   different, unrelated error is an acceptable outcome, per this
   session's established norm; a clean compile is the ideal one).
3. Full quality gate (test_gimple.py, test_module_cache.py, make
   check-selfhost, from-scratch dylib rebuild, compile_stdlib.py -j8) —
   this touches a preamble helper emitted into every module compiled with
   `do_imports`/reflection support, so a regression here would be broad.
4. Add a `test_gimple.py` case for the AttributeError-on-missing-dynamic-
   attribute behavior specifically (Step 2) — this is genuinely new
   observable behavior (previously: silent 0; now: a catchable
   exception), not just "stops erroring at compile time".

### Risk

Low-to-moderate. Step 1-3 add a new runtime code path reached only when
the existing tag-dispatch already falls through (today: a warning + wrong
answer; after: real storage) — strictly additive, no existing passing
behavior should change. Step 4 is the riskier piece: the "is this struct
name one of the fixed runtime-owned ones" set must be enumerated
carefully (miss one → same compile error persists for that struct; over-
include a name that's ALSO sometimes used for a user struct — unlikely
given this codegen's struct-name collision guards (`_struct_name_owner`)
already prevent user/runtime name clashes, but worth double-checking
before implementing).
