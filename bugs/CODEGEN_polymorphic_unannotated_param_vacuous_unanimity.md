# CODEGEN: an unannotated parameter whose call sites DISAGREE is typed by vacuous unanimity, then SIGSEGVs

**State: OPEN, mechanism located, not fixed.** Found 2026-09-30 while fixing
`bugs/CODEGEN_print_unannotated_param_typed_char_star_segfaults.md` (whose own
scope this is explicitly NOT — see "Why that doc is not this one"). That fix
removed the `print` entry from `BUILTIN_PARAM_TYPES`, which is correct and
complete for the *single-call-site* case; this is the remaining half.

## What I ran and what I saw

    def f(x):
        return x
    def main():
        print(f(1))
        print(f("s"))
    main()

| | CPython | compiled |
|---|---|---|
| `f(1)` then `f("s")` | `1` / `s` | no output, **SIGSEGV (exit -11)** |

Identical on `master` (measured before any of this work), so it predates it.
Generated C:

    char * f_d719e0 (char *);
    char * f_d719e0 (char * x) { return x; }
    ...
    _t1 = (void *)1;   _t2 = (char *) _t1;   _t3 = f_d719e0 (_t2);
    mojo_print (_t3);                    /* strlen(1) */
    _t4 = _slit_s;       _t5 = f_d719e0 (_t4);
    mojo_print (_t5);

The same shape through `print` instead of `return` is the identical failure:

    def g(x):
        print(x)
    def main():
        g(1)
        g("s")

    CPython: 1 / s        compiled: no output, SIGSEGV

## Mechanism — TWO defects, and both are needed for the fix

**1. Vacuous unanimity in Pass 1.3d.** `module_gen.py`'s free-function
call-site contract (the `for callee in sorted(_scalar_obs)` loop, ~line 4934)
resolves an unannotated parameter to `char *`/`double` when the set of observed
argument types is unanimous. It collects observations with `_arg_scalar_type`,
which returns `'double'` for a float literal and `'char *'` for a string
literal — and **nothing at all for an integer or bool literal**. So
`f(1); f("s")` yields `_scalar_obs['f']['x'] == {'char *'}`: one *observing*
call site, vacuously unanimous, resolved to `char *`, while the int call site
contributed silence that counted as agreement.

That silence is the bug, and it is asymmetric by construction: `g(1.5)` is
typed `double` correctly, `g("s")` is typed `char *` correctly, and `g(1)` is
typed `int64_t` only because `{'int64_t'}` fails the
`_has_dbl or _has_cs` whitelist — not because anyone observed it as one.

The principled fix is to make an integer/bool literal contribute `'int64_t'`
to that set, so a mixed int/str caller set stops being unanimous. **It is
deliberately NOT applied to `_arg_scalar_type` itself**: its other four
consumers (the struct-pointer observer, the struct-*method* contract, and the
two constructor observers) each whitelist its answers differently, and
widening what it returns changes all four. `_arg_struct_ptr_type` filters to
`endswith(' *')` and is unaffected; the other three would change behaviour,
which is a separate decision.

**2. No runtime discriminator for a genuinely polymorphic slot.** Fixing (1)
alone converts the SIGSEGV into a *silent wrong value*: the parameter falls to
the `int64_t` default, and `print(x)` — or any other consumer that needs a C
string — renders the pointer bits as a decimal (`4295847392`). That is the
worst outcome shape, so (1) and (2) must land together or not at all.

The answer for (2) already exists in this runtime and is already used for
exactly this question. `mojo_cstr_or_int_str` (runtime/fire_runtime.c, with
its ownership contract in `mojo_cstr_or_int_release`) is documented as:

> An int64_t being used where a C string is needed … return it AS itself when
> it is really a boxed `char *`, else its decimal string … a lambda parameter
> has no annotation and is typed `int64_t`, so a string passed to it arrives
> with its pointer bits in an int64_t with nothing recorded anywhere.

A named function's unannotated parameter is the same slot with the same
contents; only the bookkeeping that says so is missing. The discriminator
(`mojo_boxed_is_str`: pointer-shaped, not a live registered list, not a box) is
the project's own, already used by the dict-key path and by
`mojo_sorted_by_keys`.

**The precision requirement that makes this safe**: `mojo_cstr_or_int_str`
must be applied ONLY to a slot the codegen *knows* may hold a string, never to
an arbitrary `int64_t`. Its discriminator is unsound for a plain integer,
because a value in `[2^31, 2^47)` is pointer-SHAPED: applied to
`print(2**40)` it would hand a bare integer to `strlen` and trade this SIGSEGV
for a worse one. The set of provably-may-be-string slots is small and already
computable — exactly the parameters Pass 1.3d found **non**-unanimous and
therefore left at the `int64_t` default. That set does not exist yet; it is
the new bookkeeping, and it must be per-function (reset with the rest of
`_reset_func`, keyed by the enclosing function's name) because a forwarding
chain's second hop is a different slot with the same shape.

**Also unfixed and worth knowing**: a `float` argument to a polymorphic
parameter. It arrives as the `int64_t` IEEE-754 bit pattern, which is neither
pointer-shaped nor a registered box, so `mojo_cstr_or_int_str` renders it as
a large integer. `mojo_is_boxed`/`mojo_box_double`/`mojo_repr_boxed` are the
existing machinery for "an int64_t that may be a float"; a public
`mojo_box_new(double)` plus boxing at the call site that knows the argument is
a `double` is what a full fix needs. Measured: `a(1.5)` in the three-way
`def a(x): print(x)` program prints `1`, not `1.5`, today.

## Why the print-param doc is not this one

`bugs/CODEGEN_print_unannotated_param_typed_char_star_segfaults.md` says of
this shape:

> It is **not** the one-C-type-per-slot limitation. That applies when two call
> sites DISAGREE. `def g(x): return x` with `print(g(1))` is correct (row 8 of
> the table), and `def g(x): print(x)` segfaults with a **single** call site
> passing an int. There is no disagreement here at all.

Both halves of that are right, and together they delimit the two bugs
correctly: the doc owns the single-call-site case (fixed — the `print` entry
is gone from `BUILTIN_PARAM_TYPES`, and
`gimple_print_of_untyped_param_is_not_a_pointer` in `test_gimple_runner.py`
covers int, float and string), and this doc owns the disagreeing one. Its
correction of `bugs/hard/CODEGEN_coro_yield_kind_unresolved_callsite.md` is
likewise right: `def g(x): return x` does NOT do the same as
`def g(x): print(x)` for a single int call site, but both fail once a second,
disagreeing call site appears.

## Exact next step

1. In module_gen.py's free-function call-site walk, record `'int64_t'` for an
   `IntLiteral` / `BoolLiteral` / `NoneLiteral` argument — locally, not in
   `_arg_scalar_type` (see "Mechanism 1" for why the other four consumers
   must not see it yet).
2. In the same pass's application loop, when a parameter's observed types are
   NOT unanimous, add its name to a per-function
   `gen._int64_may_hold_str` set. Reset it in `_reset_func` alongside
   `_cur_func_params`.
3. In `emit_infra._gen_print`, for an `int64_t`-lowered expression that is an
   `IdentExpr` naming a parameter in that set, emit
   `_s = mojo_cstr_or_int_str (x); mojo_print (_s);
   mojo_cstr_or_int_release (x, _s);` — the release is required, not optional:
   the int case's answer is a pooled block (see `mojo_cstr_or_int_release`'s
   docstring and doc/MEMORY.html "Transient keys"). Any OTHER consumer of such
   a slot that needs a C string (dict key, f-string field, string comparison)
   needs the same treatment, and the set is what tells them.
4. The float case (above) is separable and can be a second commit.
5. Differential test: a function called with every PAIR of {int, float, str,
   bytes, list, None} arguments, printing the parameter and also using it as
   a dict key / f-string field, against CPython.

## Suite-bucket note

None. `test_gimple_runner.py` is registered as `gimplerunner` in both `check`
and `gate` (confirmed with `python3 tools/suite.py --list` on 2026-09-30), and
this is where its regression test belongs.
