#!/usr/bin/env python3
"""Regression: the TypeLattice C-type predicates answer exactly their tuples.

doc/GIR.md stage 4 replaces the backend's hand-written C-type membership tests
(`t in ('int', 'int64_t', ...)`) with the named predicates in
`mojo/middle/types.py`. A predicate that answers one value too many or too few
silently changes generated C at every call site that uses it, so this pins the
vocabulary three ways:

  1. Each predicate's EXACT membership — the answer key below is independent of
     the implementation (it is the tuple the predicate replaced).
  2. Every entry of `tools/type_string_codemod.py`'s tuple table: the
     predicates it emits, taken together, must accept exactly the tuple's
     members. The only advertised exceptions are the classes that are wider on
     purpose (`is_int` knows `unsigned int`; `is_float` knows `__fp16`), and
     each is listed with the member it adds.
  3. Every predicate the codemod emits exists on `TypeLattice`.

Run: `python3 test_type_lattice_predicates.py` (no build, no compiler run).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tools'))

import mojo.middle.types as gimple_ctypes
import type_string_codemod

TL = gimple_ctypes.TypeLattice

# Spelling probes: every member of every predicate, plus spellings that look
# close enough to be caught by a sloppy predicate ('' and None are the
# "unsolved type" markers the backend really passes).
PROBES = [
    None, '', 'unknown', 'void',
    'int', 'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', 'unsigned int',
    'char', 'bool', '_Bool', 'long', 'double', 'float', '__fp16',
    'char *', 'void *', 'int *', 'Span *', 'long *',
    'MojoList *', 'MojoDict *', 'MojoSet *', 'MojoBytes *', 'MojoStr *',
]

# The answer key: each predicate and EXACTLY the members it must accept.
# These are the tuples the predicates replaced (see the docstrings in
# mojo/middle/types.py); `unsigned int`/`__fp16` appear only where the C
# class really contains them.
ANSWER_KEY = {
    'is_word': {'int64_t'},
    'is_uword': {'uint64_t'},
    'is_int_word': {'int', 'int64_t'},
    'is_int': {'int', 'int8_t', 'int16_t', 'int32_t', 'int64_t',
               'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', 'unsigned int'},
    'is_char': {'char'},
    'is_bool': {'_Bool'},
    'is_double': {'double'},
    'is_float': {'double', 'float', '__fp16'},
    'is_cstr': {'char *'},
    'is_str': {'MojoStr *'},
    'is_span': {'Span *'},
    'is_voidp': {'void *'},
    'is_void': {'void'},
    'is_u8': {'uint8_t'},
    'is_c_long': {'long'},
    'is_cpp_bool': {'bool'},
    'is_cpp_int_scalar': {'int', 'int64_t', '_Bool', 'bool'},
    'is_unsolved': {'', 'unknown'},
    'is_word_or_unsolved': {'int64_t', '', 'unknown'},
    'is_int_word_or_unsolved': {'int', 'int64_t', '', 'unknown'},
    'is_list': {'MojoList *'},
    'is_dict': {'MojoDict *'},
    'is_set': {'MojoSet *'},
    'is_bytes': {'MojoBytes *'},
    'is_py_scalar': {'int64_t', 'double', '_Bool', 'char *'},
    'is_word_or_cstr': {'int64_t', 'char *'},
    'is_word_or_bytes': {'int64_t', 'MojoBytes *'},
    'is_word_or_list': {'int64_t', 'MojoList *'},
    'is_int_word_or_bool': {'int', 'int64_t', '_Bool'},
    'is_int_word_or_voidp': {'int', 'int64_t', 'void *'},
    'is_int_word_or_none': {None, 'int', 'int64_t'},
    'is_word_or_none': {None, 'int64_t'},
    'is_boxable': {'int64_t', 'double', '_Bool', 'char *', 'MojoList *',
                   'MojoDict *', 'MojoSet *'},
    'is_word_value': {'int64_t', 'char *', 'MojoList *', 'MojoDict *',
                      'MojoSet *'},
    'is_c_scalar': {'int', 'int64_t', 'double', '_Bool', 'char *'},
    'is_number_scalar': {'int', 'int64_t', 'double', '_Bool'},
}

# Codemod table entries whose emitted disjunction is deliberately WIDER than
# the tuple it replaces: the class it composed is the C-correct answer and the
# hand-written tuple had simply forgotten the member. Keyed by the tuple, so a
# second tuple that happens to emit the same predicates is not excused by it;
# the value is the extra member(s) tolerated — no other extra is ever accepted.
ALLOWED_EXTRA = {
    # is_int is the lattice's integer table: the tuples listing every width
    # forgot 'unsigned int'.
    frozenset(["'int'", "'int16_t'", "'int32_t'", "'int64_t'", "'int8_t'",
               "'uint16_t'", "'uint32_t'", "'uint64_t'", "'uint8_t'"]):
        {'unsigned int'},
    frozenset(["'_Bool'", "'int'", "'int16_t'", "'int32_t'", "'int64_t'",
               "'int8_t'", "'uint16_t'", "'uint32_t'", "'uint64_t'",
               "'uint8_t'"]): {'unsigned int'},
    # The dict-value boxing sites asked "is this an int?" and listed three of
    # the ten spellings; every other integer width boxes the same way.
    frozenset(["'int'", "'int32_t'", "'int64_t'"]):
        {'int8_t', 'int16_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
         'unsigned int'},
    # is_float knows __fp16 as well as the double/float the tuples listed.
    frozenset(["'double'", "'float'", "'int'", "'int64_t'"]): {'__fp16'},
    frozenset(["'_Bool'", "'double'", "'float'", "'int'", "'int64_t'"]): {'__fp16'},
    frozenset(["'_Bool'", "'char *'", "'double'", "'float'", "'int'",
               "'int64_t'"]): {'__fp16'},
    # The unsolved marker has two spellings (`''` and `'unknown'`, see
    # is_unsolved) and the hand-written tuples named one of them — one tuple
    # even named both side by side. A predicate that asks the question
    # therefore answers for both, so every tuple below is accepted with
    # 'unknown' as the one extra member. The tuple that already named both
    # spellings needs no exception and is not listed.
    frozenset(["''", "'int64_t'"]): {'unknown'},
    frozenset(["''", "'int'", "'int64_t'"]): {'unknown'},
    frozenset(["''", "'int64_t'", "'void *'"]): {'unknown'},
    frozenset(["''", "'int64_t'", "'void'"]): {'unknown'},
    frozenset(["''", "'_Bool'", "'double'", "'int'", "'int64_t'"]): {'unknown'},
    frozenset(["''", "'int'", "'int64_t'", "None"]): {'unknown'},
    frozenset(["''", "'int'", "'int64_t'", "'long'"]): {'unknown'},
}


def _members(items):
    out = set()
    for item in items:
        item = item.strip()
        if item == 'None':
            out.add(None)
        else:
            out.add(item[1:-1])
    return out


def check_answer_key():
    """Every predicate accepts exactly its answer-key set."""
    bad = []
    for name in sorted(ANSWER_KEY):
        fn = getattr(TL, name, None)
        if fn is None:
            bad.append('%s: missing from TypeLattice' % name)
            continue
        got = set(t for t in PROBES if fn(t))
        want = ANSWER_KEY[name]
        if got != want:
            bad.append('%s: accepts %s, must accept %s'
                       % (name, sorted(map(str, got - want)) or '-',
                          sorted(map(str, want - got)) or '-'))
    return bad


def check_codemod_table():
    """The predicates the codemod emits together accept exactly each tuple."""
    bad = []
    for items, names in type_string_codemod.TUPLES.items():
        for name in names:
            if not hasattr(TL, name):
                bad.append('%s emits %s, which TypeLattice does not define'
                           % (sorted(items), name))
        want = _members(items)
        got = set(t for t in PROBES
                  if any(getattr(TL, n)(t) for n in names if hasattr(TL, n)))
        allowed = want | ALLOWED_EXTRA.get(items, set())
        if got - allowed:
            bad.append('%s -> %s accepts extra %s'
                       % (sorted(items), names, sorted(map(str, got - allowed))))
        if want - got:
            bad.append('%s -> %s misses %s'
                       % (sorted(items), names, sorted(map(str, want - got))))
    return bad


def main() -> int:
    bad = check_answer_key() + check_codemod_table()
    for b in bad:
        print('  FAIL  ' + b)
    print('passed: %d failure(s)' % len(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
