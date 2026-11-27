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
# The `==`/`!=` left side accepts one level of CALL too: the stage-4 tail's
# remaining sites are `decl.get(name) == 'MojoDict *'`,
# `gen._quick_type(node.right) == ...`, `_cpp_receiver_ctype(gen, x) == ...`.
# A `.strip()` after the call (`_as_str(x).strip() == 'bool'`) is part of the
# left side, not a new expression.
LHS_EQ = (r"(?P<lhs>_as_str\([^()]*\)(?:\.\w+\([^()]*\))?"
          r"|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\([^()]*\)(?:\.\w+\([^()]*\))?"
          r"|(?!(?:not|and|or|in|is|if|else|return|lambda)\b)"
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
      "MojoStr *": "is_str",
      "Span *": "is_span",
      # Stage 4 tail (2026-11-27): every remaining single-spelling equality.
      # Each predicate is an exact `t == '<spelling>'`, so a rewrite cannot
      # change which values match. `int`/`float` are now mapped: their exact
      # predicates (`is_c_int`/`is_c_float`) exist and the old note above is
      # discharged.
      "int": "is_c_int", "float": "is_c_float", "bool": "is_cpp_bool",
      "uint64_t": "is_uword", "uint8_t": "is_u8", "uint16_t": "is_u16",
      "uint32_t": "is_u32", "int8_t": "is_i8", "int16_t": "is_i16",
      "int32_t": "is_i32", "short": "is_short",
      "unsigned short": "is_ushort", "unsigned int": "is_unsigned_int",
      "__fp16": "is_fp16", "None": "is_none_type",
      "int64_t *": "is_word_ptr", "const char *": "is_const_cstr",
      "MojoGenerator *": "is_generator", "MojoAsync *": "is_async",
      "MojoBoundMethod *": "is_bound_method",
      "MojoMemoryView *": "is_memoryview",
      "MojoStructFmt *": "is_struct_fmt", "_SIterBytes *": "is_siter_bytes",
      "ModuleLoader *": "is_module_loader"}
# What may precede the left side. `=`/`,`/`:` are included so a test in a
# keyword argument or a container literal is reached
# (`force=gen.var_types.get(x) not in (None, 'int64_t')`).
PRE = r"(?:^|[\s(={,:])"
EQ_PATS = [(re.compile(r"(?P<pre>" + PRE + r"(?:not\s+)?)" + LHS_EQ
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
    # Stage 4 tail (2026-11-27): the tuples the widened census found, each
    # emitted as the exact `or` of its members' single-spelling predicates.
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'"]): ('is_set', 'is_dict', 'is_list'),
    frozenset(["'MojoBytes *'", "'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'", "'void *'"]): ('is_bytes', 'is_voidp', 'is_list', 'is_cstr', 'is_dict', 'is_set'),
    frozenset(["'double'"]): ('is_double',),
    frozenset(["'char *'", "'double'"]): ('is_cstr', 'is_double'),
    frozenset(["'MojoDict *'", "'MojoList *'"]): ('is_dict', 'is_list'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'", "'double'"]): ('is_list', 'is_cstr', 'is_dict', 'is_set', 'is_double'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'"]): ('is_set', 'is_dict', 'is_cstr', 'is_list'),
    frozenset(["'MojoList *'", "'MojoStr *'", "'char *'"]): ('is_str', 'is_cstr', 'is_list'),
    frozenset(["'double'", "'float'"]): ('is_double', 'is_c_float'),
    frozenset(["'_Bool'", "'bool'"]): ('is_bool', 'is_cpp_bool'),
    frozenset(["'char *'", "'const char *'"]): ('is_const_cstr', 'is_cstr'),
    frozenset(["'char'", "'int'"]): ('is_c_int', 'is_char'),
    frozenset(["'MojoStr *'", "'char *'"]): ('is_str', 'is_cstr'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'void *'"]): ('is_voidp', 'is_set', 'is_dict', 'is_list'),
    frozenset(["'__fp16'", "'double'", "'float'"]): ('is_fp16', 'is_double', 'is_c_float'),
    frozenset(["'MojoList *'", "'MojoSet *'"]): ('is_set', 'is_list'),
    frozenset(["'char *'", "'void *'"]): ('is_voidp', 'is_cstr'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'", "'void *'"]): ('is_voidp', 'is_list', 'is_cstr', 'is_dict', 'is_set'),
    frozenset(["'_Bool'", "'__fp16'", "'double'", "'float'"]): ('is_fp16', 'is_bool', 'is_double', 'is_c_float'),
    frozenset(["'MojoDict *'", "'MojoGenerator *'", "'MojoList *'", "'MojoSet *'", "'char *'", "'void *'"]): ('is_voidp', 'is_list', 'is_cstr', 'is_dict', 'is_generator', 'is_set'),
    frozenset(["'_Bool'", "'int'"]): ('is_c_int', 'is_bool'),
    frozenset(["'void *'"]): ('is_voidp',),
    frozenset(["'MojoBytes *'", "'MojoDict *'", "'MojoList *'", "'MojoMemoryView *'", "'MojoSet *'"]): ('is_bytes', 'is_memoryview', 'is_list', 'is_dict', 'is_set'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'MojoStr *'"]): ('is_set', 'is_dict', 'is_str', 'is_list'),
    frozenset(["'bool'", "'int'"]): ('is_c_int', 'is_cpp_bool'),
    frozenset(["'MojoBytes *'", "'MojoMemoryView *'"]): ('is_bytes', 'is_memoryview'),
    frozenset(["'_Bool'"]): ('is_bool',),
    frozenset(["'_Bool'", "'char *'", "'int'", "'void *'"]): ('is_c_int', 'is_cstr', 'is_bool', 'is_voidp'),
    frozenset(["'_Bool'", "'double'", "'float'"]): ('is_bool', 'is_double', 'is_c_float'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'", "'double'", "'float'"]): ('is_list', 'is_cstr', 'is_dict', 'is_c_float', 'is_set', 'is_double'),
    frozenset(["''", "'None'", "'unknown'", "'void'"]): ('is_no_type', 'is_void', 'is_none_type', 'is_unsolved'),
    frozenset(["'MojoBytes *'", "'MojoDict *'", "'MojoList *'", "'MojoSet *'"]): ('is_bytes', 'is_set', 'is_dict', 'is_list'),
    frozenset(["'MojoBytes *'", "'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'"]): ('is_bytes', 'is_list', 'is_cstr', 'is_dict', 'is_set'),
    frozenset(["'MojoBytes *'", "'char *'"]): ('is_bytes', 'is_cstr'),
    frozenset(["'int16_t'", "'short'", "'uint16_t'", "'unsigned short'"]): ('is_short', 'is_i16', 'is_u16', 'is_ushort'),
    frozenset(["'int'", "'int32_t'", "'uint32_t'", "'unsigned int'"]): ('is_c_int', 'is_u32', 'is_unsigned_int', 'is_i32'),
    frozenset(["'MojoAsync *'", "'MojoGenerator *'"]): ('is_async', 'is_generator'),
    frozenset(["'_Bool'", "'char *'", "'double'", "'float'", "'int'", "'int16_t'", "'int32_t'", "'int8_t'", "'uint16_t'", "'uint32_t'", "'uint64_t'", "'uint8_t'"]): ('is_u8', 'is_i8', 'is_uword', 'is_i16', 'is_u32', 'is_cstr', 'is_c_int', 'is_bool', 'is_u16', 'is_c_float', 'is_double', 'is_i32'),
    frozenset(["'_Bool'", "'char *'", "'double'"]): ('is_bool', 'is_cstr', 'is_double'),
    frozenset(["'_Bool'", "'double'"]): ('is_bool', 'is_double'),
    frozenset(["'char *'"]): ('is_cstr',),
    frozenset(["'void *'", "'void'"]): ('is_voidp', 'is_void'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'Span *'"]): ('is_set', 'is_dict', 'is_span', 'is_list'),
    frozenset(["'MojoBytes *'", "'char *'", "'double'"]): ('is_bytes', 'is_cstr', 'is_double'),
    frozenset(["'float'", "'int'"]): ('is_c_int', 'is_c_float'),
    frozenset(["''", "'void'"]): ('is_no_type', 'is_void'),
    frozenset(["'MojoDict *'", "'MojoGenerator *'", "'MojoList *'", "'MojoSet *'"]): ('is_generator', 'is_set', 'is_dict', 'is_list'),
    frozenset(["'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'MojoStr *'", "'char *'", "'void *'"]): ('is_voidp', 'is_list', 'is_cstr', 'is_dict', 'is_str', 'is_set'),
    frozenset(["'MojoBytes *'", "'MojoDict *'", "'MojoList *'", "'MojoSet *'", "'char *'", "'double'"]): ('is_bytes', 'is_list', 'is_cstr', 'is_dict', 'is_set', 'is_double'),
    frozenset(["'uint16_t'", "'uint32_t'", "'uint8_t'", "'unsigned int'"]): ('is_u32', 'is_u16', 'is_unsigned_int', 'is_u8'),
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
# The same pointer test written without the space (`char*`, a spelling the C++
# emitter's own text can produce). `ends_with_star` is the predicate that
# answers it; `ends_in_star` stays the canonical `... *` question.
ENDS_BARE = re.compile(r"(?<![\w.])" + LHS + r"\.endswith\('\*'\)")


def rewrite_line(line: str, prefix: str) -> str:
    if line.lstrip().startswith('#'):
        return line

    def ends(m):
        return '%sends_in_star(%s)' % (prefix, m.group('lhs'))
    line = ENDS.sub(ends, line)

    def ends_bare(m):
        return '%sends_with_star(%s)' % (prefix, m.group('lhs'))
    line = ENDS_BARE.sub(ends_bare, line)
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
