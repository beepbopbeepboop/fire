#!/usr/bin/env python3
"""The GIR builder and `Instr` bodies (doc/GIR.md, stages 2b and 3c).

Two things this pins, because both are invisible in the generated C and so
neither can be caught by a corpus diff:

1. `mojo/ir/build.py` builds a STATEMENT SHAPE (`Instr`) whose `line()` is
   exactly the C text the backend used to spell by hand.  Every family that
   moves (copies, casts, arithmetic, calls, labels) is a transliteration of
   text that used to be concatenated at ~250 `gen._emit("...")` sites; the
   oracle for "byte-identical C" is `tools/pydiff_corpus`, and this file is
   the cheap unit-level version of it, one statement shape each.
2. `gen.body_lines` holds `Instr`, not text (stage 3c).  A body entry is
   rendered by `Instr.line()` at the four function-assembly sites, so the
   `#line` directive rule (one directive per statement, none in front of a
   label) lives in one place instead of in the emitter's text handling.

The rest of the subject is the ratchet: test_type_string_ratchet.py counts
`gen._emit(` (and `build.raw(`) and may only let them shrink, and
test_line_directives_per_generated_line.py checks the directives in a real
.build.  Run directly: python3 test_gir_builder.py
"""
import sys

import gimple_codegen
import mojo.backend_gimple.emit_infra as ginf
from mojo.ir import build
from mojo.ir.instr import Instr
from mojo.ir import types as gir_types

_fails = 0


def check(cond: bool, what: str) -> None:
    global _fails
    if cond:
        print(f"  ok    {what}")
    else:
        _fails += 1
        print(f"  FAIL  {what}")


def _gen():
    gen = gimple_codegen.GimpleGen(do_imports=False, module_name='p_builder')
    gen.var_types['i64'] = 'int64_t'
    gen.var_types['i32'] = 'int'
    gen.var_types['str'] = 'char *'
    gen.var_types['list'] = 'MojoList *'
    return gen


def _last(gen) -> str:
    return gen.body_lines[len(gen.body_lines) - 1].line()


def test_shapes_render_as_the_backend_spelled_them():
    print('statement shapes')
    gen = _gen()
    build.copy(gen, 'i64', 'i64')
    check(_last(gen) == '  i64 = i64;', 'copy')
    build.copy(gen, 'i64', 'i32', 'int64_t')
    check(_last(gen) == '  i64 = (int64_t)i32;', 'copy with a written conversion')
    build.cast_into(gen, 'str', 'char *', 'i64')
    check(_last(gen) == '  str = (char *)i64;', 'cast into an existing variable')
    build.binop_into(gen, 'i64', 'i64', '+', 'i32')
    check(_last(gen) == '  i64 = i64 + i32;', 'binary operation')
    build.binop_into(gen, 'i64', 'i64', '==', 'i64')
    check(_last(gen) == '  i64 = i64 == i64;', 'comparison')
    build.call_into(gen, 'i64', 'mojo_list_len_int', ['list'])
    check(_last(gen) == '  i64 = mojo_list_len_int (list);', 'call with a result')
    build.call_into(gen, 'i64', 'mojo_len_int', [])
    check(_last(gen) == '  i64 = mojo_len_int ();', 'call with no argument')
    build.call_void(gen, 'mojo_print_int', ['i64'])
    check(_last(gen) == '  mojo_print_int (i64);', 'call for effect')
    build.label(gen, 'bb_12')
    check(_last(gen) == '\nbb_12:', 'label on its own line, after a blank one')
    build.label(gen, 'bb_13', 'count(guessed_local(10))')
    check(_last(gen) == '\nbb_13:  /* count(guessed_local(10)) */',
          'label with its trip-count comment')
    build.raw(gen, '    free (_v);')
    check(_last(gen) == '    free (_v);', 'opaque text is printed verbatim')


def test_line_directive_rule():
    print('the #line rule')
    gen = _gen()
    gen._stmt_line_directive = '#line 7 "x.mojo"'
    build.copy(gen, 'i64', 'i64')
    check([s.line() for s in gen.body_lines] == ['#line 7 "x.mojo"', '  i64 = i64;'],
          'a statement is stamped with its source directive')
    gen.body_lines = []
    build.label(gen, 'bb_1')
    check([s.line() for s in gen.body_lines] == ['\nbb_1:'],
          'a label opens a block and is not stamped')
    gen.body_lines = []
    gen._stmt_line_directive = None
    build.raw(gen, '#line 9 "y.mojo"')
    build.raw(gen, '  i64 = i64;')
    check([s.line() for s in gen.body_lines] == ['#line 9 "y.mojo"', '  i64 = i64;'],
          'a directive is not stamped with itself')


def test_body_lines_hold_instr():
    print('bodies are Instr (stage 3c)')
    gen = _gen()
    gen._copy('i64', 'i32')
    gen._cast_into('i64', 'int64_t', 'i32')
    gen._binop_into('i64', 'i32', '-', 'i32')
    gen._rt_void('mojo_print_int', ['i64'])
    gen._emit_label('bb_2')
    check(all(isinstance(s, Instr) for s in gen.body_lines),
          'every body entry is an Instr')
    check(all(isinstance(d, str) for d in gen.decls),
          'declarations stay text')
    check(ginf.body_text(gen) == [
        '  i64 = (int64_t)i32;',
        '  i64 = (int64_t)i32;',
        '  _t1 = (int64_t)i32;',
        '  _t2 = (int64_t)i32;',
        '  i64 = _t1 - _t2;',
        '  mojo_print_int (i64);',
        '\nbb_2:',
    ], 'body_text renders the body the way the old text emitter did')


def test_compiled_function_keeps_its_shape():
    print('a compiled function')
    src = ('def main():\n'
           '    total: Int = 0\n'
           '    i: Int = 0\n'
           '    while i < 3:\n'
           '        total = total + i\n'
           '        i = i + 1\n'
           '    print(total)\n')
    # The filename is passed explicitly: it is what the `#line` directives
    # carry, and they are half of what this test pins.
    text = gimple_codegen.compile_to_gimple(src, False, 'builder_pin.mojo')
    lines = text.splitlines()
    # The pinned block is the whole loop body: a label, the comparison, the
    # copy of the loop counter, and the arithmetic -- one of each shape this
    # round moved, in the order the lowering emits them.
    want = [
        '  _mojo_classattr_init ();',
        '#line 2 "builder_pin.mojo"',
        '  total = 0LL;',
        '#line 3 "builder_pin.mojo"',
        '  i = 0LL;',
        '#line 4 "builder_pin.mojo"',
        '  goto bb_3;',
        '',
        'bb_3:',
        '#line 4 "builder_pin.mojo"',
        '  _t1 = 3LL;',
        '#line 4 "builder_pin.mojo"',
        '  _t2 = i < _t1;',
        '#line 4 "builder_pin.mojo"',
        '  if (_t2) goto bb_4; else goto bb_5;',
        '',
        'bb_4:  /* count(guessed_local(10)) */',
        '#line 5 "builder_pin.mojo"',
        '  _t3 = total + i;',
        '#line 5 "builder_pin.mojo"',
        '  total = _t3;',
        '#line 6 "builder_pin.mojo"',
        '  _t4 = 1LL;',
        '#line 6 "builder_pin.mojo"',
        '  _t5 = i + _t4;',
        '#line 6 "builder_pin.mojo"',
        '  i = _t5;',
        '#line 4 "builder_pin.mojo"',
        '  goto bb_3;',
    ]
    start = lines.index('  _mojo_classattr_init ();')
    got = lines[start:start + len(want)]
    for n in range(len(want)):
        if n >= len(got) or got[n] != want[n]:
            check(False, f'body line {n}: {got[n] if n < len(got) else "<missing>"!r} '
                         f'!= {want[n]!r}')
            return
    check(True, f'the loop body is unchanged ({len(want)} lines, every shape)')
    # The invariant the #line rule exists for: no directive sits directly in
    # front of a label (a label is not a source statement).
    bad = [lines[k] for k in range(1, len(lines))
           if lines[k].lstrip().startswith('bb_')
           and lines[k - 1].startswith('#line ')]
    check(not bad, f'no #line directive in front of a label ({len(bad)} found)')


def test_type_named():
    print('type spellings')
    check(gir_types.type_named('int64_t') is gir_types.I64, 'int64_t')
    check(gir_types.type_named('char *') is gir_types.CHARP, 'char *')
    check(gir_types.type_named('void *') is gir_types.VOIDP, 'void *')
    check(gir_types.type_named('MojoList *').is_ptr(), 'MojoList * is a pointer')
    check(gir_types.type_named('MojoList *').name == 'MojoList *',
          'a named struct pointer keeps its spelling')
    check(gir_types.type_named('struct MojoTuple_3 *').name
          == 'struct MojoTuple_3 *', 'a struct pointer keeps its spelling')
    check(gir_types.type_named('MojoList *') is gir_types.type_named('MojoList *'),
          'interning')


def main() -> int:
    test_shapes_render_as_the_backend_spelled_them()
    test_line_directive_rule()
    test_body_lines_hold_instr()
    test_compiled_function_keeps_its_shape()
    test_type_named()
    print(f"\n{'FAILED' if _fails else 'passed'}: {_fails} failure(s)")
    return 1 if _fails else 0


if __name__ == '__main__':
    sys.exit(main())
