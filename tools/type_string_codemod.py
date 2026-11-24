#!/usr/bin/env python3
"""Rewrite C-type string tests into TypeLattice predicates (doc/GIR.md stage 4).

    python3 tools/type_string_codemod.py            # rewrite every module in place
    python3 tools/type_string_codemod.py --check    # list what would change, change nothing

Turns `x == 'char *'` into `gimple_ctypes.TypeLattice.is_cstr(x)` (and `!=` into
`not ...`), likewise `'MojoList *'` -> is_list, `'_Bool'` -> is_bool,
`'double'` -> is_double, `'int64_t'` -> is_word, and `x.endswith(' *')` ->
ends_in_star(x), and the tuple tests in TUPLES below.
Only a simple left side (a name, attribute chain, subscripts, a single-level
call such as `d.get(k)`, or `_as_str(...)`) outside comments is rewritten;
anything else is left for a person. The generated C must stay byte-identical:
run it on a few programs before and after (tools/c_oracle.py is the oracle).
A tuple may span lines; one whose text contains a `#` (a commented-out member)
is never touched, because the comment text would otherwise become part of the
membership.

`test_type_string_ratchet.py` fails when a new string test is added; this tool
is the fix it points at.
"""
import ast
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The left side of a `==`/`!=` test: `_as_str(...)`, or a name / attribute chain /
# subscripts. Never a keyword: `et not in (...)` once matched `not` as the left
# side and was rewritten into `et is_int_word(not)`.
LHS = (r"(?P<lhs>_as_str\([^()]*\)|(?!(?:not|and|or|in|is|if|else|return|lambda)\b)"
       r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\[[^\[\]]*\])*)")
# A membership test may also ask about the value of a single-level call
# (`decl.get(name) in ('int64_t', '_char *')`). The call alternative comes
# first so `f(x)` is preferred over the bare `f` it starts with.
LHS_TUPLE = (r"(?P<lhs>_as_str\([^()]*\)|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\([^()]*\)"
             r"|(?!(?:not|and|or|in|is|if|else|return|lambda)\b)"
             r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\[[^\[\]]*\])*)")
EQ = {"char *": "is_cstr", "MojoList *": "is_list", "_Bool": "is_bool",
      "double": "is_double", "int64_t": "is_word",
      # The single-type equalities whose predicates are exact (each is `t == <spelling>`,
      # pinned by test_type_lattice_predicates.py's LEGACY table). 'int' and 'float' are
      # NOT mapped here, though is_c_int / is_c_float now exist: mapping a plain
      # `== 'int'` test is a separate change.
      "MojoDict *": "is_dict", "MojoBytes *": "is_bytes", "void": "is_void",
      "MojoSet *": "is_set", "void *": "is_voidp", "char": "is_char",
      "MojoStr *": "is_str"}
# What may precede the left side. `=`/`,`/`:` are included so a test in a
# keyword argument or a container literal is reached
# (`force=gen.var_types.get(x) not in (None, 'int64_t')`).
PRE = r"(?:^|[\s(={,:])"
EQ_PATS = [(re.compile(r"(?P<pre>" + PRE + r"(?:not\s+)?)" + LHS
                       + r" (?P<op>[=!]=) '" + re.escape(lit)
                       + r"'(?P<post>(?![\w\[(.]))"), fn)
           for lit, fn in EQ.items()]
# Tuple membership (order does not matter), as the TypeLattice predicates that
# each asks the same question. A tuple that is the union of several
# representation classes maps to a DISJUNCTION of their predicates rather than
# to a predicate of its own, so the classes keep their one definition each:
# `x in ('int', 'int64_t', 'uint64_t')` -> is_int_word(x) or is_uword(x).
# Every entry emits EXACTLY its tuple's members (`None` included where listed),
# so a rewrite cannot change which values match. A predicate that answers a
# wider class (`is_int`, `is_float`, `is_unsolved`) is never emitted for a
# tuple that names less: the entry is spelled as an `or` of the single-spelling
# predicates instead, and `test_type_lattice_predicates.py` checks each entry
# against its tuple with no exception.
TUPLES = {
    frozenset(["'int'", "'int64_t'"]): ('is_int_word',),
    frozenset(["'_Bool'", "'int'", "'int64_t'"]): ('is_int_word_or_bool',),
    frozenset(["'int'", "'int64_t'", "'void *'"]): ('is_int_word_or_voidp',),
    frozenset(["'_Bool'", "'char *'", "'double'", "'int64_t'"]): ('is_py_scalar',),
    frozenset(["'char *'", "'int64_t'"]): ('is_word_or_cstr',),
    frozenset(["'int'", "'int64_t'", "None"]): ('is_int_word_or_none',),
    frozenset(["'int64_t'", "None"]): ('is_word_or_none',),
    frozenset(["'MojoBytes *'", "'int64_t'"]): ('is_word_or_bytes',),
    frozenset(["'MojoList *'", "'int64_t'"]): ('is_word_or_list',),
    frozenset(["'int64_t'"]): ('is_word',),
    # The boxed-value classes (see mojo/middle/types.py).
    frozenset(["'_Bool'", "'char *'", "'double'", "'int64_t'",
               "'MojoDict *'", "'MojoList *'", "'MojoSet *'"]): ('is_boxable',),
    frozenset(["'char *'", "'int64_t'", "'MojoDict *'", "'MojoList *'",
               "'MojoSet *'"]): ('is_word_value',),
    frozenset(["'_Bool'", "'char *'", "'double'", "'int'", "'int64_t'"]): ('is_c_scalar',),
    frozenset(["'_Bool'", "'double'", "'int'", "'int64_t'"]): ('is_number_scalar',),
    # Unions of classes: a disjunction, never a new predicate.
    frozenset(["'int'", "'int64_t'", "'uint64_t'"]): ('is_int_word', 'is_uword'),
    frozenset(["'_Bool'", "'int'", "'int64_t'", "'uint64_t'"]):
        ('is_int_word_or_bool', 'is_uword'),
    frozenset(["'int64_t'", "'uint64_t'"]): ('is_word', 'is_uword'),
    frozenset(["'int64_t'", "'void *'"]): ('is_word', 'is_voidp'),
    frozenset(["'int64_t'", "'void *'", "'char *'"]): ('is_word_or_cstr', 'is_voidp'),
    frozenset(["'char'", "'int'", "'int64_t'"]): ('is_int_word', 'is_char'),
    frozenset(["'_Bool'", "'char'", "'int'", "'int64_t'"]):
        ('is_int_word_or_bool', 'is_char'),
    frozenset(["'_Bool'", "'char'", "'double'", "'int'", "'int64_t'"]):
        ('is_number_scalar', 'is_char'),
    frozenset(["'_Bool'", "'int64_t'"]): ('is_word', 'is_bool'),
    frozenset(["'double'", "'int64_t'"]): ('is_word', 'is_double'),
    frozenset(["'_Bool'", "'double'", "'int64_t'"]):
        ('is_word', 'is_double', 'is_bool'),
    frozenset(["'_Bool'", "'MojoDict *'", "'MojoList *'", "'MojoSet *'",
               "'char *'", "'int64_t'"]): ('is_word_value', 'is_bool'),
    frozenset(["'MojoBytes *'", "'MojoDict *'", "'MojoList *'", "'MojoSet *'",
               "'char *'", "'int'", "'int64_t'"]):
        ('is_word_value', 'is_bytes', 'is_int_word'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'",
               "'double'", "'int64_t'"]): ('is_word_value', 'is_double'),
    frozenset(["'double'", "'float'", "'int'", "'int64_t'"]):
        ('is_int_word', 'is_double', 'is_c_float'),
    # Every signed and unsigned width, spelled one predicate per width: `is_int`
    # is the lattice's whole integer table and also takes `unsigned int`, which
    # none of these tuples names, so it is not what they emit.
    frozenset(["'int'", "'int16_t'", "'int32_t'", "'int64_t'", "'int8_t'",
               "'uint16_t'", "'uint32_t'", "'uint64_t'", "'uint8_t'"]):
        ('is_word', 'is_c_int', 'is_i8', 'is_i16', 'is_i32',
         'is_u8', 'is_u16', 'is_u32', 'is_uword'),
    frozenset(["'_Bool'", "'int'", "'int16_t'", "'int32_t'", "'int64_t'", "'int8_t'",
               "'uint16_t'", "'uint32_t'", "'uint64_t'", "'uint8_t'"]):
        ('is_word', 'is_c_int', 'is_i8', 'is_i16', 'is_i32',
         'is_u8', 'is_u16', 'is_u32', 'is_uword', 'is_bool'),
    frozenset(["'int'", "'int32_t'", "'int64_t'"]): ('is_word', 'is_c_int', 'is_i32'),
    frozenset(["'int'", "'int64_t'", "'void *'", "'char *'"]):
        ('is_int_word_or_voidp', 'is_cstr'),
    frozenset(["'_Bool'", "'int'", "'int64_t'", "'void *'"]):
        ('is_int_word_or_voidp', 'is_bool'),
    frozenset(["'_Bool'", "'double'", "'float'", "'int'", "'int64_t'"]):
        ('is_number_scalar', 'is_c_float'),
    frozenset(["'MojoList *'", "'int'", "'int64_t'"]): ('is_list', 'is_int_word'),
    # The "not inferred yet" marker. A tuple that names only `''` asks
    # `is_no_type`, which does not take `'unknown'`; a tuple that names BOTH
    # spellings asks `is_unsolved`, which is exactly that pair. A tuple that
    # also lists `None` keeps its own `*_or_none` predicate for the absent
    # entry, because `not in` tests must still reject an absent entry.
    frozenset(["'int64_t'", "''"]): ('is_word', 'is_no_type'),
    frozenset(["'int'", "'int64_t'", "''"]): ('is_int_word', 'is_no_type'),
    frozenset(["'int64_t'", "'void *'", "''"]):
        ('is_word', 'is_voidp', 'is_no_type'),
    frozenset(["''", "'int64_t'", "'void'"]):
        ('is_word', 'is_no_type', 'is_void'),
    frozenset(["'_Bool'", "'double'", "'int'", "'int64_t'", "''"]):
        ('is_number_scalar', 'is_no_type'),
    frozenset(["''", "'int'", "'int64_t'", "None"]):
        ('is_int_word_or_none', 'is_no_type'),
    frozenset(["''", "'int'", "'int64_t'", "'long'"]):
        ('is_int_word', 'is_c_long', 'is_no_type'),
    frozenset(["''", "'_Bool'", "'char'", "'double'", "'int'", "'int64_t'",
               "'unknown'"]): ('is_number_scalar', 'is_char', 'is_unsolved'),
    # The single-type spellings the C++/Span/bytes paths needed (is_str is the
    # lazy MojoStr handle, is_u8 the unsigned byte, is_span the erased Span).
    frozenset(["'_Bool'", "'char *'", "'int'", "'int64_t'", "'MojoStr *'"]):
        ('is_int_word_or_bool', 'is_cstr', 'is_str'),
    frozenset(["'_Bool'", "'char'", "'int'", "'int64_t'", "'uint8_t'"]):
        ('is_int_word_or_bool', 'is_char', 'is_u8'),
    frozenset(["'Span *'", "'int64_t'"]): ('is_word', 'is_span'),
    frozenset(["'char *'", "'int'", "'int64_t'", "'long'"]):
        ('is_int_word', 'is_cstr', 'is_c_long'),
    # The C++ emitter's bool spelling (see is_cpp_bool).
    frozenset(["'int'", "'int64_t'", "'_Bool'", "'bool'"]): ('is_cpp_int_scalar',),
}

TUPLE_PAT = re.compile(r"(?P<pre>" + PRE + r")" + LHS_TUPLE + r"\s+(?P<neg>not )?in "
                       r"\((?P<items>(?:\s*(?:'[^'\n]*'|None)\s*,)+\s*(?:'[^'\n]*'|None)?\s*)\)"
                       r"(?P<post>(?![\w\[(.]))")


def _tuple(m, prefix):
    items = frozenset(x.strip() for x in m.group('items').split(',') if x.strip())
    names = TUPLES.get(items)
    if names is None:
        return m.group(0)
    lhs = m.group('lhs')
    call = ' or '.join('%s%s(%s)' % (prefix, fn, lhs) for fn in names)
    if len(names) > 1:
        # A disjunction is ONE operand: parenthesised so it keeps its meaning
        # beside `and`/`or`/`not` (the surrounding expression may be
        # `cstr(t) and <test>` or `a and <test>`, and Python binds `and`
        # tighter than `or`).
        call = '(' + call + ')'
    if m.group('neg'):
        call = 'not ' + call
    return m.group('pre') + call + m.group('post')


ENDS = re.compile(r"(?<![\w.])" + LHS + r"\.endswith\(' \*'\)")


def rewrite_line(line: str, prefix: str) -> str:
    if line.lstrip().startswith('#'):
        return line

    def ends(m):
        return '%sends_in_star(%s)' % (prefix, m.group('lhs'))
    line = ENDS.sub(ends, line)
    for pat, fn in EQ_PATS:
        def eq(m, fn=fn):
            call = '%s%s(%s)' % (prefix, fn, m.group('lhs'))
            if m.group('op') == '!=':
                if m.group('pre').rstrip().endswith('not'):
                    return m.group(0)
                call = 'not ' + call
            return m.group('pre') + call + m.group('post')
        line = pat.sub(eq, line)
    return line


def _commented(text: str, pos: int) -> bool:
    """True when `pos` sits after a `#` on its own line."""
    start = text.rfind('\n', 0, pos) + 1
    return '#' in text[start:pos]


def predicate_prefix(src: str):
    """The `TypeLattice` spelling this file can use at MODULE level, or None.

    Only a module-level binding counts. A substring test on the text does not
    tell a binding from a mention: `mojo/middle/closures.py` names
    `gimple_ctypes` only in a function-local import, and the text test rewrote
    its module-level comparisons to `gimple_ctypes.TypeLattice.is_void(...)`,
    a name that file never binds (a NameError at run time).
      `import mojo.middle.types as A`        -> `A.TypeLattice.x(..)`
      `from mojo.middle import types as A`   -> `A.TypeLattice.x(..)`
      `from mojo.middle.types import TypeLattice` -> `TypeLattice.x(..)`
    A file with none of these is not rewritten: adding an import is not this
    tool's job."""
    try:
        body = ast.parse(src).body
    except SyntaxError:
        return None
    for node in body:
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == 'mojo.middle.types' and a.asname:
                    return a.asname + '.TypeLattice.'
        if isinstance(node, ast.ImportFrom) and node.module == 'mojo.middle':
            for a in node.names:
                if a.name == 'types' and a.asname:
                    return a.asname + '.TypeLattice.'
    for node in body:
        if (isinstance(node, ast.ImportFrom) and node.module == 'mojo.middle.types'
                and any((a.asname or a.name) == 'TypeLattice' for a in node.names)):
            return 'TypeLattice.'
    return None


def rewrite_text(src: str, prefix: str) -> str:
    def sub(m):
        if _commented(src, m.start()):
            return m.group(0)
        return _tuple(m, prefix)
    # The tuple pass runs over the whole text so a membership test wrapped
    # across lines is still one test; `_commented` keeps prose out of it.
    text = TUPLE_PAT.sub(sub, src)
    return '\n'.join(rewrite_line(l, prefix) for l in text.split('\n'))


def modules() -> list:
    out = [os.path.join(HERE, 'gimple_codegen.py')]
    out += glob.glob(os.path.join(HERE, 'mojo', 'backend_gimple', '*.py'))
    out += glob.glob(os.path.join(HERE, 'mojo', 'middle', '*.py'))
    return sorted(p for p in out if not p.endswith(os.sep + 'types.py'))


def main(argv: list) -> int:
    check = '--check' in argv
    changed = 0
    for path in modules():
        src = open(path).read()
        prefix = predicate_prefix(src)
        if prefix is None:
            continue
        new = rewrite_text(src, prefix)
        if new != src:
            changed += 1
            print(('would change ' if check else 'rewrote ') + os.path.relpath(path, HERE))
            if not check:
                open(path, 'w').write(new)
    return 1 if (check and changed) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
