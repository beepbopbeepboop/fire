# DIAGNOSTICS step 6, part 1: reject malformed and non-power-of-2 constant `@align` arguments

Part of the split of `bugs/hard/DIAGNOSTICS_align_decorator.md`; the original
doc is part of the umbrella
`bugs/hard/DIAGNOSTICS_missing_validation_modular.md` and the plan is
`docs/diagnostics-missing-validation-plan.md` §6.

## Why this part

`@align(expr)` on a struct means "this struct has at least this alignment".
The value must be a positive power of 2. Modular rejects bad constant values
at parse time (`align_decorator_errors.mojo`) with:

- `@align requires exactly one argument` for `@align`, `@align()` and
  `@align(64, 128)`;
- `@align value must be a positive power of 2` for `0`, `-1`, `3`, `5`, `6`,
  `7`, `100`;
- `@align value exceeds maximum alignment (2^29)` for `2^30` and `2^32`.

This tree parses a parameterised struct decorator into a generic `CallExpr`
(`func` is `IdentExpr('align')`, `args` is the parsed argument list), but no
consumer validates it. A bad constant is silently accepted. Non-parametric
`@align(3)` is the smallest observable failure and is the acceptance target
for this part.

## Scope

`fire_compiler.py` only. Validate a `StructDef`'s `decorators` after
`_parse_struct` has built the node, in one helper that later parts reuse:

- recognise a decorator whose head is the identifier `align` (a bare `str`
  `"align"`, or a `CallExpr` whose `func` is `IdentExpr("align")`);
- reject a bare `@align`, `@align()` or any argument count other than one with
  `@align requires exactly one argument`;
- evaluate a *constant* integer argument (`IntLiteral`; `UnaryOp('-')` over
  one; parenthesised expressions are already flattened by the parser) and
  reject a value that is not `> 0` and a power of 2 with
  `@align value must be a positive power of 2`;
- reject a value above `2^29` with
  `@align value exceeds maximum alignment (2^29)`.

Raise the same `SyntaxError` shape the parser already uses, with its
`file:line:col` location prefix. A non-constant argument (`@align(alignment)`,
`@align(n * 2)`, `@align(f(3))`) is deliberately **accepted** by this part:
parts 2 and 3 evaluate it against the concrete instantiation. Do not evaluate
bracket parameters, aliases or calls here, and do not duplicate the evaluator
that parts 2/3 add.

Only `StructDef` is in scope. A `FunctionDef`/`TraitDef` decorated `@align` is
not a Mojo alignment declaration and must keep its existing generic
decorator treatment.

## Acceptance

Add `test_align_decorator_literal_diagnostic.py` beside
`test_constrained_diagnostic.py` and run it with:

    python3 test_align_decorator_literal_diagnostic.py

The test parses snippets with
`fire_compiler.Parser(fire_compiler.py_tokenize(src)).parse_module()` and
checks:

| source | expected |
|---|---|
| `@align` / `@align()` / `@align(64, 128)` | `@align requires exactly one argument` |
| `@align(0)`, `@align(-1)`, `@align(3)`, `@align(5)`, `@align(6)`, `@align(7)`, `@align(100)` | `@align value must be a positive power of 2` |
| `@align(1073741824)` and `@align(4294967296)` | `@align value exceeds maximum alignment (2^29)` |
| `@align(1)`, `@align(2)`, `@align(4)`, `@align(64)`, `@align(0x40)`, `@align(4096)` | parses; `StructDef.decorators` still contains the original `CallExpr` |
| `@align(alignment)` on a parametric struct | parses (deferred to part 2) |

Do not delete the original doc or edit the umbrella. This part does not need a
whole-closure compile; the parser test above is the narrow check.

## Status
- **Open.**
