# COMPILE_FAIL_Tools_cases_generator_analyzer-part1: positional class patterns bind through `__match_args__`

Part 1 of 4 of `bugs/hard/COMPILE_FAIL_Tools_cases_generator_analyzer.md`.

## Goal

Make a positional class pattern (`case C(x):`, `case C(x, y):`) mean what CPython
says it means on **both** front ends: `isinstance(subject, C)` and then each
capture bound from `subject.<C.__match_args__[i]>`. Today the compiled path binds
`subject.<capture name>` instead, and never consults `__match_args__` at all.
The interpreter is already correct (`myinterpreter.py:execute_MatchStmt`,
`__match_args__` at line 6634) and is the oracle for this part.

## Current state (measured 2026-11-11, HEAD `d210765a2`)

A seven-line program (`.tmp/match_args_probe.py`) whose class declares the
attributes in the opposite order to the captures:

```python
class P:
    __match_args__ = ('b', 'a')
    def __init__(self, a: int, b: int):
        self.a = a
        self.b = b

def f(x: P) -> str:
    match x:
        case P(p, q):
            return str(p) + "-" + str(q)
        case _:
            return "no"

print(f(P(1, 2)))
```

* `python3` (CPython 3.15 on this machine): `2-1`.
* `python3 fire.py run`: `2-1` (the interpreter is right).
* `python3 fire.py build` + run the binary:
  `Unhandled exception: AttributeError: p`, exit 1.

The binding site is `mojo/backend_gimple/emit_stmts.py:4616-4646`, in
`_gen_stmt_MatchStmt`'s `"class pattern (type test)"` branch: after the
`isinstance` guard it emits, for every positional argument,
`mojo_getattr_any((void *)subject, <sub-pattern name>)` and binds the result.
That is the capture name, not `__match_args__[i]`, so it reads an attribute that
does not exist (loud `AttributeError`) or, worse, a same-named unrelated
attribute (silent wrong answer). It also never raises CPython's `TypeError` for
a class without `__match_args__`, and never synthesizes `__match_args__` for a
`@dataclass` (grep of the analyzer build's generated C finds no
`__match_args__` anywhere; `parser.InstDef` is a dataclass, so its
`__match_args__` is CPython-generated, not written in the source).

The classifier already answers correctly: `formal/diagnostics.py:match_pattern_kind`
returns `"class pattern (type test)"` for `C()` and for positional-capture-only
`C(x, ...)` (lines 157-168). No classifier change is needed for this part.

The existing `test_match_class_pattern_positional.py` does **not** catch this:
its class declares `__match_args__ = ('n',)` and captures `n`, so the wrong
attribute and the right one have the same name. The new test must use a
different order.

## Plan

1. **Resolve the attribute names at compile time** in
   `mojo/backend_gimple/emit_stmts.py` (a helper next to `_gen_stmt_MatchStmt`,
   not a second classifier): given `pattern.func` (the class expression),
   resolve it to the same struct name `_lower_builtin_isinstance` already
   resolves (see `_lower_isinstance_one_type` in
   `mojo/backend_gimple/emit_calls.py`). Then, in this order:
   * an explicit class-level `__match_args__ = ('y', 'x')` in the class's
     `StructDef` (a literal tuple/list of string literals) is the answer;
   * a `@dataclass` class with no explicit `__match_args__` uses CPython's
     dataclass rule: the names of its fields that take part in `__init__`.
     Use the declaration order the struct already carries. If the compiler
     cannot prove `init=False` for a field (the parser may not model
     `field(init=False)`), **refuse** rather than guess — a wrong order binds
     the wrong value silently;
   * anything else (unknown class, non-literal `__match_args__`, a class the
     compiler cannot resolve) raises `CodegenError` naming the class and
     `__match_args__`, using CPython's wording where the shape is a genuine
     runtime `TypeError` (`C() accepts 0 positional sub-patterns (N given)`).
2. **Bind each capture from `subject.<name>`** using the ordinary attribute-read
   lowering (`_lower_MemberExpr` / the struct-field path), not
   `mojo_getattr_any` with the capture name. Keep the existing
   `if (!isinstance) goto fail;` short circuit so the attribute read never runs
   on a non-instance. Do not re-implement `isinstance`; reuse
   `_lower_builtin_isinstance`.
3. **Leave keyword sub-patterns refused.** `case C(x=0)` keeps
   `"class pattern"` and `MATCH_REFUSED_KINDS`, as today; that is a deconstruction
   whose keyword names are real attributes and is a different feature.
4. **Do not change the formal layer.** `formal/diagnostics.py` keeps
   `"class pattern (type test)"` in `MATCH_REFUSED_KINDS` because the formal
   model has no `isinstance`; `fire.py build --formal` keeps refusing it with
   its existing message. That is deliberate and out of this part (see
   `## Out of scope`).
5. **Tests** (new file, next to `test_match_class_pattern_positional.py`), as
   described under `## Acceptance`.

## Acceptance

* The reversed-`__match_args__` fixture above prints `2-1` through
  `driver.compile_program` (compiled, link mode) **and** through
  `python3 fire.py run`, matching CPython. Today the compiled path raises
  `AttributeError: p`.
* `case C(x)` on a class that defines **no** `__match_args__` must not bind any
  attribute. CPython raises `TypeError: C() accepts 0 positional sub-patterns
  (1 given)`; the interpreter already does. The compiled path may raise the
  same `TypeError` at run time or refuse at compile time, but it must not
  silently bind a same-named attribute.
* Too many positional sub-patterns (`case C(x, y)` with one entry in
  `__match_args__`) is the same story: CPython's `TypeError`, never a silent
  `y = None`.
* `case parser.InstDef(name):` in `analyzer.py:1136` still compiles, and the
  capture is CPython's first dataclass field (`annotations`), not the `name`
  field. This is the case the original doc names; assert it with a fixture that
  actually reads the capture, so the coincidence that currently hides the bug
  (capture name == field name in `Op(n)`) cannot hide it again.
* The existing `python3 test_match_class_pattern_positional.py` still runs the
  same expected values.

## Done when

`python3 test_match_class_pattern_match_args.py` (new file) exits 0.

It must fail on the current tree (compiled path prints
`Unhandled exception: AttributeError: p`) and pass after the change. It runs the
fixture through `driver.compile_program` and `subprocess` (the
`test_python_source_mut_capture.py` pattern), compares stdout to CPython, and
also covers the missing-`__match_args__` and too-many-sub-patterns cases.

## Out of scope

* The formal backend's refusal of class patterns (no `isinstance` in its model).
* Keyword class patterns (`case C(x=0)`).
* The analyzer build itself — that is part2/part3/part4. This part is a
  correctness fix on the same feature path; it is not what blocks the build
  today.
