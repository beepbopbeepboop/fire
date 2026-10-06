"""Structural check: every `formal/examples/*.mojo` parses, and the three
decorator-argument shapes stay distinguishable.

This exists because a merge regression took 4 of those 45 files out of the
parser — and NOTHING in the everyday gate noticed. `19bc0dd` made a decorator's
parenthesised argument list a real parse (`_parse_paren_args`) where it had
previously been skipped token by token, which is the right fix — `@deco` and
`@deco(x)` had become the same node — but it also made the parser impose Mojo
call-argument syntax on a decorator whose arguments are not call arguments.
`@spec(fact_spec; fact_spec 0 = 1; ...)` (`formal/examples/{fact,fib,sum,count}
.mojo`, the equations the Lean proof pipeline is written against) is a `;`-
separated specification: juxtaposed application, a bare `=` in operator
position, and a `;` between clauses. The first `;` was a `SyntaxError`.

The blast radius was invisible from where it was found. The only consumers of
these files are the `formal*` steps, which live in the `proofs`/`x86` buckets
and are the most expensive tests in the repo; the only visible symptom was
`make check-formal` reporting 26/6/13 instead of 41/4/0, i.e. a coverage
number four points low and fifteen Lean failures that had nothing to do with
Lean. `make check` was green throughout. This is a 0.1s, toolchain-free,
`expect`-free structural check so the next one is a gate failure in `check`
rather than a number somebody has to notice has moved.

Registered as `examples-parse` in tools/suite.py, in the `check` bucket
deliberately: this is a PARSER invariant, and the file it guards is consumed
by buckets that do not otherwise constrain the parser. It is not a `deps`
precondition for the formal steps — those run the same parse themselves, this
just makes the failure legible and cheap.
"""
import glob
import os
import sys

import fire_compiler as N

# The spec-form node, resolved leniently: a regression that DELETES
# `DecoratorArgs` outright must be reported as a FAIL below, not as an
# AttributeError that aborts the run and hides every check after it.
_DecoratorArgs = getattr(N, 'DecoratorArgs', ())

_ROOT = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.join(_ROOT, 'formal', 'examples')

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def _parse(src: str):
    return N.Parser(N.py_tokenize(src)).parse_module()


def _try_parse(src: str):
    """`_parse`, or None if the parser rejected the source. Every shape check
    below goes through this rather than `_parse` so that a regression is
    reported as a FAIL with the SyntaxError attached — the whole point of
    this file — instead of aborting the run with a traceback on the first
    shape that stopped parsing. A test that dies instead of reporting is a
    test whose output has to be read to be useful."""
    try:
        return _parse(src)
    except Exception as exc:
        print(f"      (parse rejected: {type(exc).__name__}: {exc})")
        return None


def _first_decorator(src: str):
    mod = _try_parse(src)
    if not mod or not getattr(mod[0], 'decorators', None):
        return None
    return mod[0].decorators[0]


def run_tests():
    files = sorted(glob.glob(os.path.join(_EXAMPLES, '*.mojo')))
    check("examples_dir_is_populated", len(files) > 0, f"{_EXAMPLES} has no *.mojo")

    # The corpus sweep. Reported per-file so a failure names the file, and
    # with a COUNT as well, because "which examples are down" is the question
    # this exists to answer and a bare pass/fail does not answer it.
    failed = []
    for path in files:
        rel = os.path.relpath(path, _ROOT)
        try:
            with open(path) as fh:
                N.Parser(N.py_tokenize(fh.read())).with_filename(rel).parse_module()
        except Exception as exc:
            failed.append(f"{rel}: {type(exc).__name__}: {exc}")
    check("every_formal_example_parses", not failed,
          f"{len(failed)}/{len(files)} failed: " + "; ".join(failed))

    # ── The three decorator-argument shapes, which must stay distinct ──────
    # A bare `@deco` is a name; `@deco(x)` is a call whose arguments are
    # real expressions; `@spec(a; b)` is a specification kept as text. The
    # first two were made distinct by 19bc0dd and are what the interpreter's
    # `_apply_function_decorators` dispatches on; the third is
    # `fire_compiler.DecoratorArgs` (bound to `_DecoratorArgs` above so a
# deletion is a FAIL and not an AttributeError).

    mod = _try_parse("@deco\ndef f():\n    return 1\n")
    check("bare_decorator_is_the_name_string",
          bool(mod) and mod[0].decorators == ['deco'],
          repr(mod[0].decorators) if mod else "")

    d = _first_decorator("@deco(n >= 0, k=1)\ndef f(n):\n    return n\n")
    check("parameterised_decorator_is_a_CallExpr", isinstance(d, N.CallExpr), repr(d))
    check("parameterised_decorator_keeps_its_argument",
          isinstance(d, N.CallExpr) and len(d.args) == 1
          and isinstance(d.args[0], N.BinaryOp), repr(d))
    check("parameterised_decorator_keeps_its_kwarg",
          isinstance(d, N.CallExpr) and len(d.kwargs) == 1
          and d.kwargs[0][0] == 'k', repr(d))

    mod = _try_parse("@spec(f_spec; f_spec 0 = 1; f_spec (n+1) = (n+1) * f_spec n)\n"
                     "@require(n >= 0)\n"
                     "def f(n):\n    return n\n")
    spec = mod[0].decorators[0] if mod else None
    check("spec_decorator_is_DecoratorArgs", isinstance(spec, _DecoratorArgs),
          repr(mod[0].decorators) if mod else "")
    check("spec_decorator_keeps_its_name",
          isinstance(spec, _DecoratorArgs) and spec.name == 'spec', repr(spec))
    check("spec_decorator_splits_on_semicolon",
          isinstance(spec, _DecoratorArgs)
          and spec.clauses == ['f_spec', 'f_spec 0 = 1',
                               'f_spec ( n + 1 ) = ( n + 1 ) * f_spec n'],
          repr(getattr(spec, 'clauses', None)))
    # A sibling annotation on the same function must still parse as a call —
    # the `;` rule applies to the ONE decorator that has a `;`, not to all.
    check("sibling_decorator_still_a_CallExpr",
          bool(mod) and isinstance(mod[0].decorators[1], N.CallExpr),
          repr(mod[0].decorators[1:]) if mod else "")

    # The `;` rule is TOP-LEVEL only. A semicolon nested inside the
    # arguments is not a clause separator, so a `;` one level down leaves the
    # region as a call argument list, which rejects it: a `;` is not valid
    # anywhere in a Mojo expression. The point of the assertion is that the
    # spec form is not entered by a semicolon the author nested on purpose
    # inside a real call's arguments — that is a malformed call, and it stays
    # one rather than being quietly reinterpreted as a specification.
    d = _first_decorator("@deco(f(a, b))\ndef f(a, b):\n    return a\n")
    check("nested_call_decorator_still_a_CallExpr", isinstance(d, N.CallExpr), repr(d))
    check("nested_semicolon_is_not_a_clause_separator",
          _first_decorator("@deco(f(a; b))\ndef f(a, b):\n    return a\n") is None,
          "a `;` nested inside a call's arguments was accepted")

    # A dotted decorator name with arguments still lowers to nested
    # IdentExpr/MemberExpr, unchanged by the spec branch.
    d = _first_decorator("@a.b.c(1)\ndef f():\n    return 1\n")
    check("dotted_parameterised_decorator_is_a_CallExpr",
          isinstance(d, N.CallExpr), repr(d))

    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
