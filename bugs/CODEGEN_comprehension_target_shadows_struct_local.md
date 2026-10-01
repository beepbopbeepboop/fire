# CODEGEN: a comprehension target that shadows a struct-pointer local reuses that local's C variable

## Status (2026-09-30 — OPEN, confirmed against the compiler's own source; in-tree trigger removed, codegen NOT fixed)

`make mojoc` — the compiler compiling itself — failed with

    fire_compiler.py:3506:1: error: non-trivial conversion in 'var_decl'
    struct Token *
    int64_t
    t = _t152;

`selfhost` and `bootstrap-stage2-cc` failed with the same error from the same
function, so all three were one bug.

## Cause

In `Parser._parse_comptime` the local `t` is a `Token *`:

    while (self._peek().kind not in ("NEWLINE", "DEDENT", "EOF")):
        t = self._peek()            # <- t : Token * from here on

and a list comprehension I added for the multi-target `comptime a, b = expr()`
rebound that same name as its loop variable:

    return [ComptimeVarStmt(target=t, value=rhs) for t in targets]

In `fire.ci` that came out as

    _t151 = mojo_list_get_str (targets, _t149);   /* char *  */
    _t152 = (int64_t)_t151;                       /* int64_t — the bug */
    t = _t152;                                    /* into `struct Token * t` */
    _t153 = _alloc_ComptimeVarStmt ();
    _t155 = t;
    _t154 = (char *)_t155;

Two things go wrong, and either alone would be survivable:

1. **The comprehension target does not get its own local.** `t` is declared
   once, as `Token *`, from its first assignment, and the comprehension's
   element is assigned into that same C variable. A comprehension target is a
   new binding in every language this compiler accepts, so shadowing must not
   reuse the outer local's storage.
2. **The element temp is typed `int64_t`, not `char *`.** `mojo_list_get_str`
   returns `char *`, so the `(int64_t)` cast is wrong, and it is what turns the
   type mismatch into a hard gcc error instead of a silent aliasing bug.

## Fixed in the tree, but only at the call site

`_parse_comptime`'s comprehension variable is now `_name`, not `t`. `make mojoc`
builds clean (exit 0, no `error:` lines) and the emitted C no longer has the
cast. **The codegen defect is untouched**: any program that shadows a
struct-pointer local with a comprehension target can still hit it.

## What is NOT known

I could not build a **minimal user-level reproducer**, and the negative results
are part of the finding — they say the trigger is narrower than "shadows a
struct pointer". Tried and all correct (exit 0):

| shape | result |
|---|---|
| `t = 1`, then `[t for t in xs]` (int64 shadow) | ok |
| `var t = P(1,2)` (struct value), then `[t for t in xs]` | ok |
| `var t = [1,2,3]` (`MojoList *`), then `[t for t in xs]` | ok |
| `var t = String("hi")`, then `[t for t in xs]` | ok |
| `var t = {"k": 1}` (dict), then `[t for t in xs]` | ok |
| `var t = &p` / `return &p` | not reachable: `&` is `Unexpected OP('&')` in this parser |

So the shadowing alone is not sufficient. What is common to the real case and
absent from every repro above: the shadowed local is assigned **inside a `while`
loop** (so it has a hoisted declaration and several assignment sites), and the
comprehension sits in a **`return` inside a branch** further down the same
function. The obvious next experiment is to vary those two (loop-assigned
struct-pointer local; comprehension in a `return` inside an `if`) until a
repro lands, then reduce it.

## Next step

1. Reduce to a user-level reproducer by varying the two conditions above
   (loop-assigned struct-pointer local; comprehension in a `return` inside an
   `if`). Until one exists, a regression test cannot be written, and that is
   the reason this is filed rather than fixed.
2. Fix the comprehension lowering so the target always gets a fresh local
   rather than reusing an enclosing binding's C variable, and so a
   `char *`-valued element is not routed through an `int64_t` temp. Likely
   `mojo/middle/loops_shared.py` / the comprehension handling in
   `mojo/backend_gimple/emit_exprs.py`; the `MojoList`/pointer distinction is
   decided in `mojo/middle/types.py`, whose `mojo_list_get_str` result type this
   gets wrong.
3. Because step 2 is a compiled-path change it owes a full `make gate`, and
   `mojoc` / `selfhost` / `bootstrap-stage2-cc` are the three steps that
   actually exercise the shape — a green `gimple` or `runner` says nothing
   about it, which is exactly why this surfaced as three unrelated-looking gate
   failures.

## Evidence

- `build/gate_20260930.log` — the failing gate: `selfhost`, `bootstrap-stage2-cc`
  and `mojoc` all fail on this one error.
- `fire.ci` (generated), `fire_compiler_Parser__parse_comptime` — the
  `struct Token *` / `int64_t` clash quoted above.
- `make mojoc` after renaming the loop variable: exit 0.
