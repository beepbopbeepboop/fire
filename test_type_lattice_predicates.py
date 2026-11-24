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
     predicates it emits, taken together, must accept EXACTLY the tuple's
     members. No extra member is excused: a predicate that answers a wider
     class (`is_int` knows `unsigned int`, `is_float` knows `__fp16`,
     `is_unsolved` knows `'unknown'`) is not what a tuple test may emit, so
     the table spells the tuple as an `or` of single-spelling predicates.
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
    # The single-spelling integer and float predicates the exact rewrites use
    # (mojo/middle/types.py); each answers only its own spelling.
    'is_c_int': {'int'},
    'is_i8': {'int8_t'},
    'is_i16': {'int16_t'},
    'is_i32': {'int32_t'},
    'is_u16': {'uint16_t'},
    'is_u32': {'uint32_t'},
    'is_c_float': {'float'},
    'is_no_type': {''},
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
        if got - want:
            bad.append('%s -> %s accepts extra %s'
                       % (sorted(items), names, sorted(map(str, got - want))))
        if want - got:
            bad.append('%s -> %s misses %s'
                       % (sorted(items), names, sorted(map(str, want - got))))
    return bad


# Spellings beyond PROBES that a delegating predicate could get wrong: aliases
# `type_named` canonicalises (the reason `Type` keeps the spelling), spellings
# it would NORMALISE (`char*`), and text that is not a type at all.
WIDE_PROBES = PROBES + [
    'signed', 'signed char', 'unsigned char', 'unsigned', 'short', 'long int',
    'long long', 'unsigned long', 'ssize_t', 'size_t', 'intptr_t', 'pid_t',
    'long double', '_Float16', 'char*', ' int', 'int ', 'int64_t ', 'void*',
    'MojoList*', 'char **', 'long *', 'int64_t *', 'bool *', 'MojoStr',
    'int (*)(int)', 'struct Foo *', 'Foo', '*', ' *', 'int8_t *',
]

_I = {'int8_t': 1, 'int16_t': 1, 'int32_t': 1, 'int': 1, 'int64_t': 1,
      'uint8_t': 1, 'uint16_t': 1, 'uint32_t': 1, 'unsigned int': 1, 'uint64_t': 1}
_S = {'int8_t', 'int16_t', 'int32_t', 'int', 'int64_t'}


def _lit(*spellings):
    """The pre-delegation literal behaviour: `t` (truthy) equals a spelling."""
    return lambda t: bool(t) and t in spellings


def _lit_none(*spellings):
    return lambda t: t is None or t in spellings


# The predicates as they were BEFORE they delegated to mojo/ir/types.py, one
# literal per predicate (each is the tuple the answer key names, applied to
# every probe, so a spelling `type_named` canonicalises cannot slip through).
LEGACY = {
    'is_float': _lit('__fp16', 'float', 'double'),
    'is_signed': _lit(*_S),
    'is_unsigned': _lit('uint8_t', 'uint16_t', 'uint32_t', 'unsigned int', 'uint64_t'),
    'is_int': _lit(*_I),
    'is_cstr': _lit('char *'), 'is_str': _lit('MojoStr *'),
    'is_span': _lit('Span *'), 'is_list': _lit('MojoList *'),
    'is_dict': _lit('MojoDict *'), 'is_set': _lit('MojoSet *'),
    'is_bytes': _lit('MojoBytes *'),
    'is_word': _lit('int64_t'), 'is_uword': _lit('uint64_t'),
    'is_int_word': _lit('int', 'int64_t'), 'is_char': _lit('char'),
    'is_u8': _lit('uint8_t'), 'is_c_long': _lit('long'),
    'is_void': _lit('void'), 'is_voidp': _lit('void *'),
    'is_double': _lit('double'), 'is_bool': _lit('_Bool'),
    'is_cpp_bool': _lit('bool'),
    'is_int_word_or_bool': _lit('int', 'int64_t', '_Bool'),
    'is_py_scalar': _lit('int64_t', 'double', '_Bool', 'char *'),
    'is_word_or_cstr': _lit('int64_t', 'char *'),
    'is_word_or_bytes': _lit('int64_t', 'MojoBytes *'),
    'is_word_or_list': _lit('int64_t', 'MojoList *'),
    'is_int_word_or_none': _lit_none('int', 'int64_t'),
    'is_word_or_none': _lit_none('int64_t'),
    'is_int_word_or_voidp': _lit('int', 'int64_t', 'void *'),
    'is_unsolved': lambda t: t is not None and (t == '' or t == 'unknown'),
    'is_word_or_unsolved': lambda t: (t is not None and t in ('int64_t', '', 'unknown')),
    'is_int_word_or_unsolved': lambda t: (t is not None and t in ('int', 'int64_t', '', 'unknown')),
    'is_pointer': lambda t: bool(t) and '*' in t,
    'ends_in_star': lambda t: bool(t) and t.endswith(' *'),
    'is_cpp_int_scalar': _lit('int', 'int64_t', '_Bool', 'bool'),
}

FROZEN = ['is_int_word_or_bool', 'is_int_word_or_voidp', 'is_word_or_cstr',
          'is_int_word_or_none', 'is_word_or_none', 'is_word_or_bytes',
          'is_word_or_list', 'is_word_or_unsolved', 'is_int_word_or_unsolved']


def check_legacy_equivalence():
    """Each predicate, now an adapter over mojo/ir/types.py, answers every
    probe spelling exactly as its pre-delegation literal did."""
    bad = []
    for name in sorted(LEGACY):
        fn = getattr(TL, name, None)
        if fn is None:
            bad.append('%s: missing from TypeLattice' % name)
            continue
        for t in WIDE_PROBES:
            got, want = bool(fn(t)), LEGACY[name](t)
            if got != want:
                bad.append('%s(%r) = %s, the literal says %s' % (name, t, got, want))
    for name in FROZEN:
        doc = getattr(TL, name).__doc__ or ''
        if 'frozen: no new callers' not in doc:
            bad.append('%s: docstring must say it is frozen' % name)
    return bad


def check_type_vocabulary():
    """mojo/ir/types.py keeps spellings distinct and shares the class."""
    from mojo.ir import types as T
    bad = []
    for a, b in [('char', 'int8_t'), ('long', 'int64_t'), ('bool', '_Bool'),
                 ('unsigned int', 'uint32_t'), ('int32_t', 'int')]:
        ta, tb = T.type_named(a), T.type_named(b)
        if ta is tb:
            bad.append('%s and %s must be distinct objects' % (a, b))
        if ta.cls is not tb.cls:
            bad.append('%s and %s must share a class' % (a, b))
        if not T.trivially_convertible(ta, tb) or T.mismatch_class(ta, tb):
            bad.append('%s and %s must be one GIMPLE class' % (a, b))
    if T.type_named('long *').cls is not T.type_named('int64_t *'):
        bad.append('long * and int64_t * must share a class')
    ranked = set(k for k in T.RANKED_SPELLINGS)
    tables = set(gimple_ctypes._GD_SIGNED) | set(gimple_ctypes._GD_UNSIGNED) | set(gimple_ctypes._GD_FLOAT)
    if ranked != tables:
        bad.append('RANKED_SPELLINGS differs from generated_dispatch: %s'
                   % sorted(ranked ^ tables))
    return bad


def main() -> int:
    bad = (check_answer_key() + check_codemod_table()
           + check_legacy_equivalence() + check_type_vocabulary())
    for b in bad:
        print('  FAIL  ' + b)
    print('passed: %d failure(s)' % len(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
