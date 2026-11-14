"""Regression: unpacking in set/dict/list comprehensions (PYTHON3.15).

Covers:
- Parser: `{**d for d in ds}` is a dict comprehension with a spread element.
- Interpreter/runtime (fire.py run): `[*x for x in ...]`, `{*x for x in ...}`,
  `{**d for d in ds}` evaluate by spreading each element/mapping.
"""
import os
import subprocess
import sys
import tempfile

import fire_compiler as N

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def parse_expr(src):
    return N.Parser(N.py_tokenize(src))._parse_expr(0)


def run_fire(src):
    """Run `src` via `fire.py run` and return (rc, stdout, stderr)."""
    tmpdir = os.path.join(HERE, ".tmp")
    os.makedirs(tmpdir, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".py", dir=tmpdir)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(src)
        p = subprocess.run(
            [sys.executable, FIRE, "run", path],
            text=True, capture_output=True, cwd=HERE,
            timeout=60,
        )
        return p.returncode, p.stdout, p.stderr
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_parse():
    c = parse_expr("{**d for d in ds}")
    check("dict_spread_comp_kind", c.kind == "dict", getattr(c, "kind", None))
    check("dict_spread_comp_value_none", c.value is None, repr(c.value))
    check("dict_spread_comp_element_starstar",
          isinstance(c.element, N.UnaryOp) and c.element.op == "**",
          repr(c.element))

    c = parse_expr("{*x for x in xs}")
    check("set_star_comp_kind", c.kind == "set", getattr(c, "kind", None))
    check("set_star_comp_element_star",
          isinstance(c.element, N.UnaryOp) and c.element.op == "*",
          repr(c.element))

    c = parse_expr("[*x for x in xs]")
    check("list_star_comp_kind", c.kind == "list", getattr(c, "kind", None))
    check("list_star_comp_element_star",
          isinstance(c.element, N.UnaryOp) and c.element.op == "*",
          repr(c.element))


def test_runtime():
    cases = [
        ("list_star_comp",
         "print([*x for x in [[1, 2], [3]]])\n", "0", "[1, 2, 3]\n"),
        ("set_star_comp",
         "print(sorted({*x for x in [[1, 2], [3]]}))\n", "0", "[1, 2, 3]\n"),
        ("dict_spread_comp",
         "print({**d for d in [{'a': 1}, {'b': 2}]})\n", "0",
         "{'a': 1, 'b': 2}\n"),
        ("dict_spread_comp_overwrite",
         "print({**d for d in [{'a': 1}, {'a': 2}]})\n", "0", "{'a': 2}\n"),
    ]
    for name, src, exp_rc, exp_out in cases:
        rc, out, err = run_fire(src)
        ok = (str(rc) == exp_rc and out == exp_out)
        detail = f"rc={rc} out={out!r} err={err!r}" if not ok else ""
        check(name, ok, detail)


if __name__ == "__main__":
    test_parse()
    test_runtime()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    sys.exit(0 if _FAIL == 0 else 1)
