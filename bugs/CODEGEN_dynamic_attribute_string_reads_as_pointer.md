# CODEGEN_dynamic_attribute_string_reads_as_pointer: a dynamically-set attribute's string value reads back as a raw int64 pointer in the compiled path

## Status addendum (2026-10-01, `work/bugs3-codegen-2-r2` — residual 2 re-measured and narrowed to a call site; NOT fixed)

Re-measured on this tree, against CPython 3.14.7 on the same text. The
string-attribute half of the main defect is still fixed, and **residual 2 is
confirmed and localised further than the entry above says** — it is not the
runtime's miss path, it is which of the codegen's two 3-arg `getattr` branches
runs, and one of them drops the default from the answer entirely.

```
$ cat .tmp/ga2.mojo
class C:
    pass

def main():
    o = C()
    print(getattr(o, "nope", "dflt"))
    o.y = "set"
    print(getattr(o, "y", "dflt"))
    print(getattr(o, "nope", "dflt"))
    print(o.y)

$ python3 .tmp/ga2.py            # CPython, main() appended
dflt
set
dflt
set

$ python3 fire.py --jit .tmp/ga2.mojo
4335323912                        <-- getattr(o, "nope", "dflt")
set
4335323912                        <-- ditto, after a REAL attribute was set
set
```

So it is not specific to an object that has dynamic attributes: a brand-new
`C()` with none reproduces, on a hit-adjacent object too.

### The generated C shows the miss flag and the default are both right — and the answer is dropped anyway

```c
  _t3 = _slit_10001;                    /* "dflt"            */
  _t4 = (int64_t)_t3;
  _mojo_getattr_missed = 0;
  _mojo_getattr_nothrow = 1;
  _t5 = _mojo_dispatch_getattr (_t6, _t2);
  _mojo_getattr_nothrow = 0;
  _t7 = _mojo_getattr_missed;
  _t8 = _t7 != 0;
  _t9 = (char *)_t5;                    <-- the DEFAULT IS GONE
```

The runtime is exonerated by a direct measurement: linking `fire_runtime.c`
and calling `mojo_obj_getattr(o, "nope")` under the nothrow flag gives
`v=0 missed=1`, i.e. `mojo_obj_getattr` sets the flag and the flag is a
readable global. The emitted `_t8` (the `_Bool` for the miss) is computed and
**never used**, which is the whole bug: the ternary that selects the default
was not emitted.

### Why: it is a THIRD `getattr` site, not the two the entry names

`emit_calls.py` has three places that emit the nothrow probe:

* the 2-arg `hasattr` probe (~:2130), and
* the literal-name 3-arg `getattr` "A5" branch (~:2308-2335), which does
  build the ternary — `raw = gen._new_val('int64_t', f'{cond} ? {dv} : {raw}')`
  — and is what makes `getattr(o, "x", "dflt")` correct for a KNOWN field;
* the fall-through 3-arg branch (~:2337-2355), reached when the receiver's
  struct does not declare the attribute AND the name-keyed
  `_known_field_type` lookup found nothing. It emits the probe, computes
  `cond`, and then returns
  `gen._new_val('int64_t', f'{cond} ? {dv} : {raw}')` — which is right.

The measured case emits NEITHER ternary, which does not match either site, so
**one of these three is not the code that ran, and I did not finish
identifying which.** That is the honest state, and it is why this is an
addendum and not a fix: I made a plausible edit to the fall-through branch
(present the result as `char *` when the default lowers to `char *`, which is
the right SHAPE of answer for a miss), it changed the output from a pointer
decimal to `None`, and since I could not explain the mechanism I reverted it
rather than commit a change I could not account for. **The tree at
`work/bugs3-codegen-2-r2` carries no change for this residual.**

### Exact next step

Read the emitted C against `_gen_stmt`/`lower_expr` for this exact program with
a debugger rather than by inspection: put a `print` of the three sites'
`_attr`, `_boxed_ft` and `_nothrow3` in
`mojo/backend_gimple/emit_calls.py` and find which one emits
`_t9 = (char *)_t5;` with a computed-but-unused `_t8`. Once that is known the
fix is a few lines — either restore the ternary, or (if the site turns out to
be a fourth one) give the 3-arg `getattr` ONE implementation that all four
spellings go through, which is the shape CLAUDE.md's no-parallel-
implementations rule asks for anyway and is what made this hard to see.

Verify with a `test_gimple_runner.py` `test_gimple_stdout` case that runs
through the miss: `getattr(o, "nope", "dflt")` printing `dflt`, alongside the
hit `getattr(o, "x", "")` (which works today and must keep working) and the
`o.x` plain read — three spellings of the same question, so a fix to one
cannot be mistaken for a fix to the shape.

## Earlier status (2026-09-30, first entry — the string-attribute half ISOLATED and FIXED; see the main entry below)

## Status (2026-09-30 — the string-attribute half is FIXED, and it is a memory-level bug, not a display one; the three residuals below are separate and still open)

Re-measured at `86d862fc` before acting, against CPython on the same text
(single-TU `gimple_codegen.compile_to_gimple` + `gcc -fgimple` +
`runtime/fire_runtime.c`). The doc's 6-line repro reproduced exactly:
`9759608` / `9759608` where CPython printed `hello` twice, exit 0.

**The doc's mechanism is wrong, and the real one is worse.** It attributes
the wrong value to `mojo_obj_getattr` returning a boxed `int64_t` that
nothing re-types. Read out of the generated C, what actually happens is
that the attribute is never dynamic at all. `C` declares no field `x`, so
`_scan_body_for_local_field_access`
(`mojo/backend_gimple/module_gen.py`) MINTS a phantom field for it — its
documented job, for a member a known struct does not declare — and the
mint was unconditionally `int`, the "nothing is known about this member"
answer that is right for a read-only phantom. A member that is *assigned*
is not read-only, and the write went through that field:

```c
typedef struct C { int64_t __mojo_type_id; int x; } C;
...
_t2 = _slit_10000;              /* "hello"   */
_t4 = (void *)_t2;
_t5 = (int64_t)_t4;
_t3 = (int)_t5;                 /* the string POINTER, truncated to 32 bits */
o->x = _t3;                     /* stored into a 4-byte int field          */
```

So the value was **truncated to 32 bits on the way in**, and the read
printed those bits as a decimal. `mojo_obj_getattr` and the per-object
dynamic-attribute dict are not on this path at all for the plain `o.x`
spelling. The consequence is worse than a silent wrong value: `len(o.x)`
dereferenced the truncated value and **segfaulted**, and `o.big =
1099511627776` (an ordinary integer) is truncated the same way, to `0`.

**Fixed**: the minted field's type is now taken from the value actually
assigned to that member (`_scan_stmt_member_assigns` feeds the mint; the
answer is `_quick_type`'s, the same estimator the rest of codegen uses).
Deliberately restricted to POINTER-shaped and floating answers — those are
the ones a 4-byte `int` slot is provably wrong for — so a member assigned
an ordinary integer keeps exactly the declaration it always had, and a
read-only phantom still mints `int`. The doc's repro now prints `hello`
twice, and a wider program that reads the same attribute through `print`,
`len`, an f-string, `str()`, `%s`, `==` and `getattr` gets all of them
right; regression test
`gimple_dynamic_attribute_string_keeps_its_type` in
`test_gimple_runner.py`.

`getattr(o, "x", "")` needed a second, separate fix to join them, and it is
worth naming because the reason it was broken is not the one it looks like.
The value was already there — the generated `_mojo_getattr_C` reads the real
field (`strcmp(attr, "x") == 0 ? obj->x : ...`) — and the call site simply
never cast the boxed result back, because that cast is gated on
`_is_selfhost_file` (see the A5 comment above: a bare `_known_field_type`
by NAME is unsound for an arbitrary receiver, and `Lib/tempfile.py`'s
`getattr(file, 'buffer', file)` was the real regression that gate exists
for). The sound evidence is the RECEIVER's own declared field, which is
exactly what `_lower_MemberExpr`'s `o.x` read already uses, so
`_lower_builtin_getattr`'s literal-name branch now takes the field's C type
from the receiver's static struct when that struct really has the field —
making the two spellings agree by construction instead of one of them being
right by accident. The name-keyed gate is left exactly as it was.

MEASUREMENT NOTE, because it cost time and will cost it again: the two
spellings behaved DIFFERENTLY depending on whether `compile_to_gimple` was
given a `filename`, because `_is_selfhost_file` is
`os.path.abspath(_current_filename).startswith(_SELFHOST_DIR)` and
`_SELFHOST_DIR` is the directory `gimple_codegen.py` was loaded from — so
ANY file under the repo root counts as "self-hosted source", and any file
outside it does not. `test_gimple_runner.py` calls `compile_to_gimple(src)`
with NO filename, so a probe that passes one is exercising a different
build than the suite runs. Run the suite's own harness when the question is
what the suite will see. So the doc's proposed `mojo_dynattr_get_as(v,
want)` helper is not needed for this case, and would have been the wrong
layer: it would have re-typed a value that a 4-byte field had already
destroyed.

**Still open, and each is a different mechanism — recorded so none of them
is re-derived from this one:**

1. **A large integer assigned to a phantom field is still truncated**
   (`o.big = 1099511627776` reads back `0`). The restriction above is
   what leaves it: `_quick_type` answers `int64_t` both for a genuine
   integer literal and as its no-evidence default, so "the value is a
   wide integer" and "nothing is known" are indistinguishable there.
   Distinguishing them means classifying the value AST node directly
   rather than through the estimator, and then EVERY phantom field that
   is assigned an integer changes width — a layout change across the
   whole tree for a case that currently corrupts silently. Not attempted
   here.
2. **A 3-argument `getattr` whose key is absent still does not return the
   supplied default** (`getattr(o, "nope", "dflt")` printed a pointer
   decimal). Pre-existing and unchanged by either fix above; it is the miss
   path (`_mojo_getattr_missed` / `_mojo_getattr_nothrow`), not the value
   path. Worth its own look: the ternary that selects the default exists in
   the emitted C, so the flag is not being SET by a miss for this object.
3. **The dynamic-attribute dict path itself is still untyped** for a
   receiver whose static type is genuinely unknown (an `int64_t`-boxed
   object, not a known struct). This is where the doc's original analysis
   does apply, and the honest reading of it is that it needs a
   *data-dependent* type: the read's static type would have to depend on a
   runtime tag, which means a union-typed read and a consumer that
   branches on it. A name-keyed "this attribute held a string somewhere"
   table would be unsound (the same name on two objects can hold two
   types) and is the shape the existing narrow special case
   (`_except_attr_str_fields`, for caught-exception objects) already has.
   Recorded, not attempted.

The "Relationship to `make bootstrap`" section below is untouched by this:
the 44-file `#line` divergence is a self-host-wide phenomenon and this
change is a field type in one class, not a filename.

## Earlier status (2026-09-26, first entry — bug ISOLATED and REPRODUCED, NOT fixed; it is the leading suspect for `make bootstrap`'s 44-file `#line` divergence, but that link is NOT yet proven)

Found while triaging `make bootstrap` on `f6837c8` (see "Relationship to
`make bootstrap`" below). Reproduced in a self-contained 6-line program, so
it is not an artifact of the bootstrap's scale.

### The bug

```mojo
class C:
    pass

def main():
    o = C()
    o.x = "hello"
    print(getattr(o, "x", ""))
    print(o.x)

main()
```

- CPython: `hello` / `hello`
- compiled: `16235256` / `16235256`

Both the 3-argument `getattr` and the plain attribute read return the raw
`char *` **as an int64_t**, which the print path then formats as a decimal
address. The write itself is fine — the value really is stored, and it
round-trips through every other accessor; only the *type* presented to the
caller is wrong.

Also confirmed while narrowing it: a 3-argument `getattr` whose key is
**absent** does not reliably return the supplied default. A parameter is
also still treated as capturing-by-default in the lambda lifter whenever its
name is visible in `var_types` (fixed in `fce5798`, but recorded here
because the same visibility rule is what makes this class of bug hard to
see).

### Why it happens

A dynamically-set attribute has no static C type, so the codegen cannot
know the stored value is a string. The compiled `getattr`/member-read path
resolves the attribute through the runtime's per-object dynamic-attribute
dict (`mojo_obj_getattr`, `_mojo_dynattr_objects` in
`runtime/fire_runtime.c`), which returns a boxed `int64_t`, and the
codegen hands that straight back as `_boxed_ft` (see the
`_known_field_type` / `_boxed_ft` resolution in
`mojo/backend_gimple/emit_calls.py`'s `getattr` branch). Nothing in that
path consults the runtime discriminator the rest of the model already
relies on — `mojo_boxed_is_str` ("pointer-shaped and not a live registered
`MojoList` ⇒ string"), which `mojo_cstr_or_int_str` (added in `fce5798`)
and the repr walkers use.

### Candidate fix (not applied)

Dispatch the *comparison/typing* on the runtime discriminator at the point
the value is read, the way the repr helpers do, rather than letting the
static type decide. Concretely: a runtime helper that returns the value
already coerced for the requested static type (e.g.
`mojo_dynattr_get_as(v, want)`), used only on the dynamic-attribute path so
struct-typed reads keep their exact typing. This is deliberately NOT done
blindly — every dynamic-attribute consumer is affected, so it needs the
full gate (below) per iteration, and it is the kind of change that can
silently re-type a value that some other site was (accidentally) relying on
being an integer.

## Relationship to `make bootstrap`

`make bootstrap` on this tree's base commit now **runs to completion**: no
`SIGTRAP`, and **zero** dump failures across all three stages. Its `verify`
step reports 136 files byte-identical and 44 `.ci` files differing — and
**every one of the 44 is `stage1 vs stage2`; there is not a single
`stage2 vs stage3` failure.** So the self-hosted binary is deterministic
and reproduces itself exactly, and the whole divergence is
python-reference vs native, in one direction.

That 44-file divergence is a single systematic difference:

```
stage1/hello.ci:1155: #line 2 "../hello.mojo"
stage2/hello.ci:1155: #line 2
```

The native path emits a bare `#line N` with no filename, i.e.
`gen._current_filename` is empty in the self-hosted build, so
`gen_stmt`'s `getattr(gen, '_current_filename', '')` yields nothing. The
entire `hello.ci` diff is 48 lines, all of them `#line` directives.

**This is where the isolation above was done, and the honest state is that
the link is NOT established.** Note the symptom does not line up cleanly
with the bug as isolated: a raw pointer is *truthy*, which would produce
`#line 2 "<decimal>"`, not a bare `#line 2`. So either there is a second
step (an empty-string read rather than a pointer read) or the filename is
lost earlier — e.g. the argument not surviving the call into
`gimple_codegen.compile_to_gimple(src, do_imports=False, filename=...)`
from compiled `fire.py` (a cross-module call with a keyword argument;
keyword arguments were verified to work for same-module calls, and the
cross-module probe was inconclusive because the probe program itself turned
out to be invalid). Ruled out so far: the arity/keyword call path for
same-module functions, and the `gimple_codegen_compile_to_gimple` C shim in
`runtime/fire_runtime.c` (it does forward `filename`).

This supersedes nothing in
`CODEGEN_noshim_dumpfull_preexisting_divergence.md`; that doc's 14-file
`verify` failure is the same stage1-vs-stage2 shape and this entry is the
current, narrower measurement of it.

## Also open, found in the same session, independent of the above

1. **Imported-function prototypes go missing in the full self-host build**
   (introduced by `fce5798`, i.e. by this session's lambda-capture work):
   `make check-selfhost` fails with
   `assignment to 'char *' from 'int'` and
   `implicit declaration of function 'cas_lookup_1b532c'` inside LIFTED
   CLOSURES. A baseline worktree at the parent commit was green, and
   compiling `driver.py` standalone still emits all 30 `cas_*` declarations
   correctly — so it is an ordering interaction that only appears in the
   full build. Leading suspect: the new env-struct `typedef` is appended to
   `gen._elaborated_externs`, the same list the imported-function
   prototypes go into, from a different point in the emission order.

2. **Cross-module calls returning 0** — an unverified lead, recorded so it
   is not re-derived from scratch. The probe that suggested it was itself
   invalid (the interpreter also returned 0 for it), so treat it as
   unconfirmed.

3. **The two key-function gaps** deliberately left documented in
   `_lower_builtin_sorted_keyed` rather than papered over: a
   dict-subscripted global read inside a lifted lambda returns 0, and an
   **unannotated named function** handed a string element misreads it
   (`key=bylen` where `def bylen(s): return len(s)` gives lengths 2,3,1
   instead of 1,2,3 — correct when the same function is called directly). A
   lambda key and a builtin key both handle string elements correctly.

4. **`zip()`'s pair shape is deliberately left untyped.** The pairs print as
   tuples now, but `_lower_builtin_zip_n` still returns `void *` and records
   no element type, because typing it breaks a real self-host shape (a
   comprehension with a nested tuple target over `zip` reads a 2-slot pair
   spec and then indexes a list where a string was expected). The repr-only
   routing added in `fce5798` was an attempt to fix the printing without
   that hazard and has since been REMOVED in favour of the generated
   `_mojo_repr_pair`, which needs no metadata at all.

5. **`map`/`filter` with more than one iterable** are an honest refusal, not
   an implementation (`map(f, xs, ys)`).

## Gate required before any of this is called fixed

Per `CLAUDE.md`, none of the above is trustworthy on a partial run. A fix
landing here needs: `make check-linkmode`, `make check-selfhost`, a
from-scratch stdlib dylib build (skip count must not rise),
`python3 compile_stdlib.py` (`U` must not rise), `make bootstrap`, and
`make check-native-dumpfull`. Bootstrap and native-dumpfull are the two
steps that exercise the self-hosted binary's own codegen — every other step
drives the python3-interpreted reference, which is structurally blind to
exactly the class of bug in this document.
