# The interpreter has no evaluation for a keyword-bracket call: `f[T=Int, y=5]()` is evaluated as a SUBSCRIPT on `f`

**Area:** FIRE_COMPILER's interpreter (`myinterpreter.py`), not the parser.
Found 2026-10-01 on `work/bugs3-codegen-2-r2` while fixing parts 1 and 2 of
`bugs/CODEGEN_comptime_function_type_alias_is_erased_by_the_parser.md`.
**Not fixed there** — it is the layer below the parser and it is a missing
feature, not a wrong answer to a question the interpreter already answers.

## What I ran and what it showed

```mojo
def f[T, y=0, *, linux=0]():
    return y

comptime A = f[T=Int, y=5]()
comptime B = f[T=Int]()
comptime C = f[T, 9]()

def main():
    print(A)
    print(B)
    print(C)
```

```
$ python3 fire.py run ct4.mojo
Traceback (most recent call last):
  ...
NameError: 6:15: name 'T' is not defined
```

CPython cannot run this at all (brackets are Mojo), so there is no reference
to diff against; the expected answers are the obvious ones (`5`, `0`, `9`) and
the compiled path's answers are the real comparison.

## Cause

`eval_SubscriptExpr` is what runs for `f[...]`, and a keyword-bracket
`SubscriptExpr` has `index = IntLiteral(0)` (the empty-subscript placeholder)
and its real arguments in `attrs`. The interpreter indexes with the
placeholder and never looks at `attrs` — so `f` is indexed with `0` (which
returns something), and the bracket's keyword values are dropped. `T` in the
source position `f[T=Int, y=5]` is parsed as an `IdentExpr` and evaluated in
the ENCLOSING scope, where nothing is bound to `T`, hence the `NameError`.

Which means the three spellings fail differently and none of them is the right
answer:

| spelling | parsed | interpreter |
|---|---|---|
| `f[T=Int]()` | `attrs=[('T', IdentExpr('Int'))]` | `NameError: T` |
| `f[T=Int, y=5]()` | `attrs=[('T',…), ('y', IntLiteral(5))]` | `NameError: T` |
| `f[T, 9]()` | `index=TupleExpr([T, 9])` | `NameError: T` |

The last one is instructive: the POSITIONAL-first spelling is the one that has
always parsed, and it fails by the same mechanism, so this is not new with the
bracket-mixing fix.

## Why it matters now, and what it is not

This is the next thing standing between the stdlib and a correct answer:
`std/io/file.mojo` computes `O_CREAT`, `O_APPEND` and `O_CLOEXEC` as
`platform_map[T=Int, "O_APPEND", linux=0x0400, macos=0x0008]()` and then ORs
them into the flags it passes to `open(2)`. Those three aliases' PARSER half
is now right (the bracket parses and every element is kept — see the parent
doc); their EVALUATION is this gap, and until it is closed the interpreter
builds those flags from a subscript-with-index-0 result.

It is NOT a silent wrong answer today: it raises, which is the right failure
for a shape the engine cannot lower. The hazard is that a fix which made it
silently return a subscript value instead would convert an honest `NameError`
into a wrong flag value.

## Exact next step

In `myinterpreter.py`, handle the keyword-bracket CALL before the generic
subscript path — the same ordering `_lower_subscript` uses in the compiled
backend, and for the same reason (a keyword bracket's `index` is a
placeholder, so the generic path cannot be right for it):

* recognise `CallExpr(func=SubscriptExpr(..., attrs=[...]))` where any
  `attrs` name is not a plain subscript key, and evaluate it as a call:
  bind the callee's `comptime_params` from the `(None, value)` positionals
  and the named parameters from the `attrs` pairs, then invoke the
  `FunctionDef` with the `attrs` keywords as its keyword arguments;
* leave the positional-first spelling (`f[T, 9]()`, `index = TupleExpr`) on
  whatever path it has — it is a different representation, and a fix that
  merges the two is a second change with its own blast radius;
* an unresolvable comptime parameter should be the honest refusal this
  interpreter already makes elsewhere (`_loc(node)` + a message), not a
  default.

Verify with `test_interp_oracle.py`, which is the right harness precisely
because a CPython-comparable case is impossible here: a program whose
`comptime` alias is a keyword-bracket call of a `def` with `comptime_params`,
printed, with every spelling of the bracket, plus the positional-first one as
the control. Add a `f[T=Int, "x", linux=1, macos=2]()` case, since that is the
`platform_map` shape and the one the stdlib uses.

## Evidence

- The 9-line program and its `NameError` above, on `work/bugs3-codegen-2-r2`
  after the parent doc's parts 1 and 2 landed.
- The parser side is asserted green: `test_new_syntax_parsing.py`'s
  `test_bracket_mixing_keyword_and_positional` and
  `test_comptime_rhs_misparse_is_refused` (111 passed, 0 failed).
- `mojo/backend_gimple/emit_calls.py` ~:1057-1077 for the compiled side's
  already-correct treatment of the same `attrs` pairs, which is the model for
  what the interpreter needs.
