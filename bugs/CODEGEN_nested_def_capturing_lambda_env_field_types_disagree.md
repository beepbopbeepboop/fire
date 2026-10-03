# A capturing lambda inside a NESTED `def` gets an env struct whose field types disagree with the stores into it

**State: OPEN. Found 2026-10-02 while working
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`, whose own table
names this shape. NOT the same bug as the doc that row points at
(`bugs/CODEGEN_lambda_in_nested_def_body_never_emitted.md`, claimed by another
worker): that one is the lifted function being *declared and referenced but
never defined* — a LINK error. Here the body **is** emitted and the whole
program links; what is wrong is the type of the env struct's fields relative
to the stores that fill them.**

## What I ran

`.tmp/b3/v1.py`, `v2.py`, `v3.py`, compiled and run through
`test_gimple_runner.py`'s `compile_mojo_to_gimple_exe` (single-TU
`compile_to_gimple`, no imports). The three differ only in the captured
local's type.

```python
def main():
    def outer():
        s = <9 | 'x' | 9.5>
        return (lambda: s)
    print(outer()())

main()
```

## What I saw

| captured local | CPython | compiled | exit |
|---|---|---|---|
| `s = 9` (`int`) | `9` | **BUILD FAILS**: `non-trivial conversion in 'var_decl'` in `main_outer` | 1 |
| `s = 'x'` (`char *`) | `x` | **`4367411224`** (the `char *`'s own bits) | **0** |
| `s = 9.5` (`double`) | `9.5` | **`4342405872`** | **0** |

The same program with `outer` at **module** scope is correct for all three —
`test_gimple_runner.py`'s existing lambda coverage passes — so the trigger is
the extra level of nesting, not the capture.

## The generated C

`s = 9`, nested (`.tmp/b3/n2.py`), vs `outer` at module scope
(`.tmp/b3/lam2.py`):

```c
/* nested: FAILS to compile */
typedef struct main_outer_lambda_1_env { int z; } main_outer_lambda_1_env;

int64_t __GIMPLE main_outer (void)
{
  int z;                        /* <-- local is `int`          */
  main_outer_lambda_1_env * _t2;
  int64_t _t4;
  ...
  _t4 = (int64_t)z;
  _t2->z = _t4;                 /* <-- int64_t into an `int` field */
}

/* module scope: compiles and is correct */
typedef struct outer_lambda_1_env { int64_t z; } outer_lambda_1_env;

int64_t outer (void)
{
  int64_t z;                    /* <-- local is `int64_t`       */
  ...
  _t4 = (int64_t)z;
  _t2->z = _t4;                 /* <-- matches */
}
```

`-fgimple` requires a GIMPLE assignment's RHS to already have the assigned
variable's exact type, so the `int` field against an `int64_t` store is the
build failure. The pointer cases do not fail to build because the coercion
`char *`/`double` -> `int64_t` is itself legal; they are the SILENT wrong
value instead, which is why they are the more dangerous half.

## Where the two disagree

Two sites read the capture's ctype, and they are not reading the same thing:

- **The env struct's field list** — `mojo/backend_gimple/emit_calls.py`'s
  `_lower_LambdaExpr`, the `_env_typedef` block (~line 4663). Its field types
  come from `_known`, the union of `_env_fields`, `ci.captures` and
  `gen._captures`, normalised by
  `_ct in ('int','int64_t','_Bool','char','double') or _ct.endswith(' *')`
  with everything else forced to `int64_t`.
- **The store into it** — `mojo/backend_gimple/emit_funcs.py`'s closure
  prologue (~line 164), `gen._safe_coerce_emit(local_type, vtype, cname,
  f"{env_var}->{field}")`, where `vtype` is `ci.captures`'s entry and
  `local_type` is `gen.var_types.get(vname, vtype)`.

The `char *` and `double` rows pin which side is stale rather than leaving it
open: both capture a value the LOCAL holds as `char *`/`double` and both store
`(int64_t)`, i.e. `vtype == 'int64_t'` at the store, while the field came out
narrow — so `ci.captures` (or `gen._captures`) answered `int64_t` for the
store and something narrower for the typedef. The `int` row is the same
disagreement with the field landing on the store's own value, so neither side
is simply "always narrower".

## Exact next step

Instrument one compile of `.tmp/b3/v2.py` and print, at each of the two sites
above, the `ci.captures` / `gen._captures` / `_env_fields` entry for `z` and
which object identity the `ci` is. `discover_closures` re-runs per nesting
level (`mojo/middle/closures.py`, and its sibling-merge arm reassigns
`_mci.captures = list(_merged_list)`), and `_lower_LambdaExpr` saves and
restores `gen._captures` around the lift — so the two sites are very plausibly
looking at two different generations of the same `ClosureInfo`. Whichever is
stale, the fix is to make ONE of them authoritative for the field type, and
the shape to follow is the one already used two lines above in
`discover_closures` for exactly this class of disagreement: the
`MojoBoundMethod *` special case there exists because

> A mismatched — or `void` — capture makes the env-struct field disagree with
> the body's local (hard C error).

This bug is that same failure one C type over, for ordinary scalars, and the
comment shows the mechanism was already understood once.

The narrower and safer of the two candidate fixes is in `_lower_LambdaExpr`:
derive the field ctype from the STORE's expression, the same way it already
derives the field NAME from the emitted body text (the `_read` scan a few lines
up). The whole reason that scan exists is "the body names exactly the fields
the struct must have" — and this is the same argument applied to the field's
type, which the name-only version cannot see.

## Blast radius and why this matters more than it looks

A capturing lambda inside a nested `def` is not an exotic shape: it is what
`functools.wraps`-style decorators, `functools.partial`-alikes, `sorted(...,
key=...)` over a comprehension variable, and every "build a closure in a
factory function" idiom compile to. `tools/` and real stdlib code contain
several. Two thirds of the cases are a silent pointer decimal with exit 0.

It is also the reason `bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`
cannot simply be closed by fixing its three named rows: this shape is live and
is not one of them.