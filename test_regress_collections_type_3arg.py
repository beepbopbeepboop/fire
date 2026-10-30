"""Regression pin for the 3-arg type() gap (bug:COMPILE_FAIL_collections___init__).

`namedtuple` lowers at collections/__init__.py:515 to `type(typename,
(tuple,), class_namespace)`: a class built at run time. The compiled path has
no static struct to emit for that, so the 3-argument form is now refused by
name in the lowering (mojo/backend_gimple/emit_calls.py) instead of falling
through to the 1-argument `mojo_type` stub and producing a three-argument C
call that gcc rejects.

The feature (dynamic class construction) is still open; this pins the refusal.
"""
from gimple_codegen import compile_to_gimple

FAILURES = []

def test_namedtuple_3arg_type_is_refused_by_name():
    src = "result = type('T', (tuple,), {'x': 1})\n"
    try:
        compile_to_gimple(src, do_imports=False, filename="namedtuple.py")
    except RuntimeError as e:
        if 'cannot compile module' in str(e) and 'type(name, bases, namespace)' in str(e):
            return
        FAILURES.append(f"refused, but not with the named message: {e}")
        return
    FAILURES.append("3-arg type() compiled; it must be refused until the feature lands")

def test_namedtuple_non_literal_is_refused_by_name():
    """A `namedtuple` the module-level desugar does not lower (here the
    typename is a variable, not the bound name's literal) must be refused by
    name. Before the refusal it lowered to collections' unresolved-import stub,
    which printed `namedtuple: unavailable in compiled mode` and exited 0."""
    src = "def make(n: str):\n    return namedtuple(n, ['x'])\n"
    try:
        compile_to_gimple(src, do_imports=False, filename="namedtuple.py")
    except RuntimeError as e:
        if 'namedtuple(...)' in str(e):
            return
        FAILURES.append(f"refused, but not with the named message: {e}")
        return
    FAILURES.append("non-literal namedtuple() compiled; it must be refused")

def main():
    test_namedtuple_3arg_type_is_refused_by_name()
    test_namedtuple_non_literal_is_refused_by_name()
    if FAILURES:
        for f in FAILURES:
            print(f"FAIL  {f}")
        raise SystemExit(1)
    print("PASS  test_regress_collections_type_3arg")

if __name__ == "__main__":
    main()
