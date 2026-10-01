# CODEGEN: `print(...)` in a lambda body emits no separator and no newline

Found 2026-10-01 while testing
`bugs/CODEGEN_annotated_str_param_given_an_int_segfaults.md`'s fix (both
lambda-string cases had to stay working, and one did not print its line
ending). Pre-existing: it reproduces identically on the parent commit, and
none of this commit's edits touch `print` lowering.

## What I ran and what I saw

```python
def main():
    a = lambda: print("A")
    a()
    b = lambda x: print("B")
    b(1)
    c = lambda x: print(x)
    c("C")
main()
```

| | CPython | compiled |
|---|---|---|
| stdout | `A\nB\nC\n` | `ABC` |

Every argument prints with the right VALUE — so this is not a value bug, it
is a missing-terminator bug — but every line ending is gone, so all three
run together on one line. Exit 0, no diagnostic.

A lambda that prints a computed string loses the terminator the same way:

```python
h = lambda s: print(s + "!")
h("hello")
```
CPython `hello!\n`; compiled `hello!` — and whatever prints next continues
on the same line.

## Mechanism

`_gen_print` (`mojo/backend_gimple/emit_infra.py`) is the one print lowering:
it emits the value, then `_emit_literal_print(' ', print_fn)` between
arguments, then `_emit_literal_print('\\n', print_fn)` unconditionally at the
end. `emit_stmts._gen_stmt_ExprStmt` routes a bare `print(...)` statement
there (`if raw_name == 'print': gen._gen_print(...)`).

A `print` inside a **lifted lambda body does not reach `_gen_print` at all**.
The whole argument list is lowered as an ordinary call to `mojo_print` through
the generic path, and `mojo_print`'s own signature is a single `char *` — so
the separator and the newline, which live in `_gen_print` and nowhere else,
are never emitted. Generated C for the minimal case:

```c
int64_t __GIMPLE main_lambda_1 (int64_t s)
{
  char * _t1;
  ...
bb_2:
  _t1 = mojo_cstr_or_int_str (s);
  mojo_print (_t1);        /* the value ... */
                               /* ... and nothing else. No "\n". */
  _t3 = (int64_t)_t2;
  return _t3;
}
```

The same `def` in an ordinary function is correct, which is what localises it
to the lambda-lifting path:

```c
void g_d719e0 (char * s)
{
  mojo_print (s);
  _t1 = _slit_10000;       /* "\n" */
  mojo_print (_t1);
}
```

Also note this is NOT the same defect as
`bugs/CODEGEN_print_in_a_nested_def_body_prints_the_argument_as_a_decimal_address.md`
(a `print` in a lifted nested `def` DOES go through `_gen_print` and DOES emit
the newline; it gets the argument's VALUE wrong instead). Two separate gaps in
the same area, filed separately.

## What I expected

`A\nB\nC\n`, byte for byte. `print` is a statement-level builtin with
fixed separators, and `_gen_print` already models that; there is no reason a
lambda body should get a different set of rules.

## Exact next step

Find where a lifted lambda body is lowered. The statement dispatcher in
`emit_stmts._gen_stmt_ExprStmt` checks `raw_name == 'print'`, so the lifted
body's statements are reaching some OTHER statement path — most likely the
lambda/closure body compiler reuses a generic expression-statement emitter
rather than `_gen_stmt_ExprStmt`, which is also why the `mojo_print` call
arrives with a `char *` parameter to be coerced rather than as a
`_gen_print` call. Making the lifted body go through the same statement
dispatcher fixes all three spellings at once and is almost certainly the
whole fix; if the lifted body genuinely cannot reuse it, the narrow version
is to route `print` to `_gen_print` in that path specifically.

Cheap confirmation once there: the generated C should contain TWO
`mojo_print` calls for `c = lambda x: print(x)` (value, then `_slit` newline),
exactly as `g_d719e0` above does.