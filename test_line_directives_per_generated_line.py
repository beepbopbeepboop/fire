"""Every generated line in a function body carries its own `#line` directive.

GCC numbers a `-fgimple` diagnostic from the last `#line` directive, counting
PHYSICAL lines. A Mojo statement that lowers to N C lines therefore needs a
directive before EACH of them, or an error on its k-th line is reported at
`statement_line + k`. Before this test's fix the emitter put one directive
before a statement's first line, and only leaf statements were re-stamped, so:

* a lambda body was lifted to its own C function with no directive at all, so
  its lines were numbered from whatever `#line` came before it in the outer
  function (`re.sub(..., lambda m: ..., s)` on line 4 of an 8-line file was
  reported at line 74 of the generated `.ci`);
* the header and body lines of a compound statement (`for`, `while`, `if`
  conditions, `try`) that were emitted after its first line drifted the same way.

The check reads the generated C: inside every function body, each line that is
a statement (not a declaration, brace, label, blank or directive) must be
DIRECTLY preceded by a `#line` directive. The lambda case also pins that its
body is attributed to the lambda's own source line.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gimple_codegen import compile_to_gimple  # noqa: E402

_DECL = re.compile(r'^\s+(const\s+)?\w+(\s+\*+|\s*\*+\s*|\s+)\w+(\[[^\]]*\])?;$')
_LABEL = re.compile(r'^bb_\d+:')


def _function_bodies(c_src):
    """Yield (header_index, [(line_index, text), ...]) for each function body."""
    lines = c_src.splitlines()
    i = 0
    while i < len(lines):
        if lines[i] == '{' and i > 0 and lines[i - 1].strip() \
                and not lines[i - 1].rstrip().endswith(';') \
                and not lines[i - 1].startswith((' ', '#')):
            body = []
            j = i + 1
            while j < len(lines) and lines[j] != '}':
                body.append((j, lines[j]))
                j += 1
            yield i - 1, body
            i = j
        i += 1


def _unstamped_statement_lines(c_src):
    """Statement lines inside a function body with no `#line` directly above."""
    bad = []
    for _hdr, body in _function_bodies(c_src):
        prev = ''
        for idx, text in body:
            s = text.strip()
            exempt = (not s or s in ('{', '}') or s.startswith(('#', '/*', '__GIMPLE'))
                      or _LABEL.match(s) or _DECL.match(text))
            if not exempt and not prev.lstrip().startswith('#line'):
                bad.append((idx + 1, text))
            prev = text
    return bad


def _compile(src):
    return compile_to_gimple(src, do_imports=False, filename='prog.py')


def test_lambda_body_lines_each_carry_a_line_directive():
    src = (
        "import re\n"
        "\n"
        "\n"
        "def f(s: String) -> String:\n"
        "    x = 1\n"
        "    return re.sub(r'(\\N\\{[^{}]*\\})|([{}])', lambda m: m.group(0), s)\n"
    )
    c = _compile(src)
    assert _unstamped_statement_lines(c) == [], \
        f"generated lines with no #line above them: {_unstamped_statement_lines(c)[:5]}"
    # The lifted lambda body belongs to the lambda's own source line (line 6),
    # not to whatever directive preceded it in the enclosing function.
    lam = [l for l in c.splitlines() if l.startswith('#line ')]
    # The definition (not the forward declaration, which ends in `;`).
    lam_body = c[c.index('\n__GIMPLE char * f_lambda_1 (int64_t m)\n'):]
    lam_body = lam_body[:lam_body.index('\n}\n')]
    directives = re.findall(r'^#line (\d+) "prog\.py"$', lam_body, re.M)
    assert directives and set(directives) == {'6'}, \
        f"lambda body directives: {directives}; all directives: {lam[:12]}"


def test_compound_statement_lines_each_carry_a_line_directive():
    src = (
        "def g(a: Int, b: Int) -> Int:\n"
        "    total = 0\n"
        "    for i in range(a):\n"
        "        if i > b:\n"
        "            total = total + i * 2\n"
        "        else:\n"
        "            total = total - 1\n"
        "    while total > 100:\n"
        "        total = total // 2\n"
        "    return total\n"
    )
    c = _compile(src)
    assert _unstamped_statement_lines(c) == [], \
        f"generated lines with no #line above them: {_unstamped_statement_lines(c)[:5]}"


def test_stack_switch_generator_body_lines_each_carry_a_line_directive():
    # A generator on the stack-switch path is lowered to `__mgco_<name>_body`,
    # a plain function built from its body. Its parameter prologue is
    # synthesized, and that is where the first unstamped lines came from.
    src = (
        "def counts(n: Int) -> Int:\n"
        "    i = 0\n"
        "    while i < n:\n"
        "        yield i\n"
        "        i = i + 1\n"
    )
    c = _compile(src)
    assert '__mgco_counts_body (int64_t __c)' in c, "generator did not take the stack-switch path"
    assert _unstamped_statement_lines(c) == [], \
        f"generated lines with no #line above them: {_unstamped_statement_lines(c)[:5]}"


def test_call_argument_genexp_body_lines_carry_its_source_line():
    # `", ".join(... for c, s in ...)`: a generator expression written as a
    # call's sole argument is hoisted to `__genexp_N`, which is on the
    # stack-switch path. Its Comprehension used to be built without a line,
    # so its body's statements had none and emitted no `#line` at all.
    src = (
        "def show(d: Dict[String, Int]) -> String:\n"
        "    return \", \".join(\"%s=%d\" % (c, s) for c, s in sorted(d.items()))\n"
    )
    c = _compile(src)
    assert _unstamped_statement_lines(c) == [], \
        f"generated lines with no #line above them: {_unstamped_statement_lines(c)[:5]}"
    body = c[c.index('\nvoid __mgco___genexp_0_body (int64_t __c)\n'):]
    body = body[:body.index('\n}\n')]
    directives = re.findall(r'^#line (\d+) "prog\.py"$', body, re.M)
    assert directives and set(directives) == {'2'}, \
        f"genexp body directives: {directives}"


if __name__ == '__main__':
    test_lambda_body_lines_each_carry_a_line_directive()
    test_compound_statement_lines_each_carry_a_line_directive()
    test_stack_switch_generator_body_lines_each_carry_a_line_directive()
    test_call_argument_genexp_body_lines_carry_its_source_line()
    print('ok')
