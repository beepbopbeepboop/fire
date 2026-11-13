# CODEGEN: the regex scan loop emits `sizeof(...)` inside a `__GIMPLE` body, which raw GIMPLE cannot parse

Status: OPEN. Filed 2026-11-12 by the regex-table worker on HEAD aacfc103f. Pre-existing; found while checking whether the finditer lowering could pin the regex-table address fix from inside a method body.

## Symptom

`for m in PAT.finditer(s):` (a module-level `PAT = re.compile(...)`) inside a
struct/class method — a `__GIMPLE`-tagged body — is refused by gcc:

    import re
    PAT = re.compile(r"(?P<k>[a-z]+)([0-9]+)")
    class S:
        def count(self, s):
            n = 0
            for m in PAT.finditer(s):
                n = n + 1
            return n

`gcc -fgimple -fsyntax-only -x c` reports `expected expression before '(' token`
pointing into the method, and the emitted body contains:

    _t7 = (int64_t)(sizeof(int64_t) * 3);
    _t8 = malloc (_t7);

(`__GIMPLE` errors carry the enclosing function's `#line`, so the reported
physical line is the method's first line, not the `sizeof` statement.)

Minimal proof that `sizeof` is the offending token and not the cast:

    #include <stdint.h>
    __GIMPLE int64_t g(void) { int64_t t; t = (int64_t)(sizeof(int64_t) * 3); return t; }
    /* error: expected expression before '(' token */
    __GIMPLE int64_t g(void) { int64_t t; t = (int64_t)24; return t; }
    /* accepted */

The same method compiles when the file keeps its `.c` suffix (gcc lowers from
C); `fire.py build` compiles `.ci` with `-x c`, which is the raw-GIMPLE path.

## Root cause

`emit_loops.py::_gen_for_regex_iter` and the shared `_emit_regex_scan` compute
the group-offset array size as:

    gsize = gen._new_val('int64_t', f'(int64_t)(sizeof(int64_t) * {ngroups + 1})')

A `sizeof` expression is not a legal GIMPLE operand, so the statement cannot be
parsed. (The current self-host closure does not hit this because its finditer
call sits in a module-level `def`, whose body is ordinary C; a method or a
lifted closure that iterates a compiled pattern would.)

## Next step

1. Reproduce with `gimple_codegen.compile_to_gimple(src)` on the snippet above,
   writing the result to a `.ci` and running
   `gcc -fgimple -fsyntax-only -x c -Iruntime` on it.
2. Emit the size as a plain integer constant (the element is `int64_t`; use
   `8 * (ngroups + 1)`, or define the width once next to the table types) so
   the statement is a single constant assign. Re-run gcc afterwards — the
   `sizeof` parse error also cascades into "invalid operands in binary
   operation" reports from later lines (`_t23 = _t14 > _t7;` in the same
   block), so check what remains.
3. The quick test is the snippet compiled with `-x c` and run vs CPython in
   `test_gimple.py`, plus `test_runtime_re.py` staying green.

## Done when

The method-shaped finditer loop compiles with `gcc -fgimple -x c` and counts
matches like CPython. Then delete this doc in that commit.
