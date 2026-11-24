#!/usr/bin/env python3
"""The whole-closure type solver (mojo/tsolve, bugs/GIR_type_solver.md, section 4).

Pure unit tests: no backend, no compile. Each `join` row, each `from_annotation`
row, each `ret_ctype` row is checked; then small programs are summarized and
solved and their return types compared with what the language means.

Run directly: python3 test_tsolve.py   (exit 0 when every case passes)
"""
import sys
import unittest

import fire_compiler as N
import ast_rewriter
from mojo.tsolve import lower, sty, solve_closure
from mojo.tsolve.sty import (BOT, BOOL, DYN, FLOAT, FUNC, INT, NONE, STR,
                             dict_of, from_annotation, join, list_of, set_of,
                             struct_of, tuple_of)


def _parse(src):
    return ast_rewriter.rewrite(N.Parser(N.py_tokenize(src)).parse_module())


class _Files:
    """An in-memory closure: `load` resolves a module ref to '/t/<ref>.py'."""

    def __init__(self, files):
        self.files = files  # {ref: source}

    def load(self, ref, importer):
        if ref not in self.files:
            return None
        return ('/t/' + ref + '.py', _parse(self.files[ref]))


def _solve(files, root='main'):
    f = _Files(files)
    stmts = _parse(files[root])
    return solve_closure('/t/' + root + '.py', stmts, f.load)


def _ret(files, name, mod='main', root='main'):
    sol = _solve(files, root)
    t = sol.ret_sty('/t/' + mod + '.py', name)
    return None if t is None else t.key


class JoinTable(unittest.TestCase):
    """bugs/GIR_type_solver.md 2.1, rules 1-4 of `join`, row by row."""

    def test_bot_is_the_identity(self):
        self.assertIs(join(BOT, INT), INT)
        self.assertIs(join(STR, BOT), STR)
        self.assertIs(join(BOT, BOT), BOT)

    def test_equal_types_join_to_themselves(self):
        self.assertIs(join(INT, INT), INT)
        self.assertIs(join(list_of(STR), list_of(STR)), list_of(STR))

    def test_none_joined_with_a_pointer_is_the_pointer(self):
        for t in (STR, list_of(INT), tuple_of([INT]), dict_of(STR, INT),
                  set_of(INT), struct_of('Tok')):
            self.assertIs(join(NONE, t), t)
            self.assertIs(join(t, NONE), t)

    def test_none_joined_with_a_scalar_is_dyn(self):
        for t in (INT, FLOAT, BOOL, FUNC):
            self.assertIs(join(NONE, t), DYN)
            self.assertIs(join(t, NONE), DYN)

    def test_dyn_absorbs(self):
        self.assertIs(join(DYN, INT), DYN)
        self.assertIs(join(STR, DYN), DYN)

    def test_scalars_of_different_kinds_are_dyn(self):
        self.assertIs(join(BOOL, INT), DYN)
        self.assertIs(join(INT, FLOAT), DYN)
        self.assertIs(join(STR, list_of(STR)), DYN)
        self.assertIs(join(struct_of('A'), struct_of('B')), DYN)

    def test_containers_join_elementwise(self):
        self.assertIs(join(list_of(INT), list_of(BOT)), list_of(INT))
        self.assertIs(join(list_of(INT), list_of(STR)), list_of(DYN))
        self.assertIs(join(set_of(INT), set_of(INT)), set_of(INT))
        self.assertIs(join(dict_of(STR, INT), dict_of(STR, NONE)), dict_of(STR, DYN))

    def test_tuples_of_one_arity_join_slotwise(self):
        self.assertIs(join(tuple_of([INT, STR]), tuple_of([INT, STR])), tuple_of([INT, STR]))
        # None joined with str is str (rule 2), so the slot keeps str.
        self.assertIs(join(tuple_of([INT, STR]), tuple_of([INT, NONE])),
                      tuple_of([INT, STR]))
        self.assertIs(join(tuple_of([INT, STR]), tuple_of([STR, STR])),
                      tuple_of([DYN, STR]))

    def test_tuples_of_different_arity_give_a_list_of_all_slots(self):
        self.assertIs(join(tuple_of([INT]), tuple_of([INT, INT])), list_of(INT))
        self.assertIs(join(tuple_of([INT]), tuple_of([STR, STR])), list_of(DYN))

    def test_a_tuple_joined_with_a_list_is_a_list(self):
        self.assertIs(join(tuple_of([INT, INT]), list_of(INT)), list_of(INT))
        self.assertIs(join(list_of(INT), tuple_of([INT, STR])), list_of(DYN))

    def test_cap_limits_nesting_to_depth_three(self):
        deep = list_of(list_of(list_of(list_of(INT))))
        self.assertIs(sty.cap(deep), list_of(list_of(list_of(DYN))))
        ok = list_of(list_of(list_of(INT)))
        self.assertIs(sty.cap(ok), ok)

    def test_join_is_capped(self):
        deep = list_of(list_of(list_of(list_of(INT))))
        self.assertIs(join(deep, deep), sty.cap(deep))


class FromAnnotation(unittest.TestCase):
    """bugs/GIR_type_solver.md 2.1, `from_annotation`, row by row."""

    CLASSES = {'Tok': True}

    def fa(self, text):
        return from_annotation(text, self.CLASSES)

    def test_scalars(self):
        for t in ('int', 'Int', 'Int64'):
            self.assertIs(self.fa(t), INT)
        for t in ('float', 'Float64'):
            self.assertIs(self.fa(t), FLOAT)
        for t in ('bool', 'Bool'):
            self.assertIs(self.fa(t), BOOL)
        for t in ('str', 'String', 'StringLiteral'):
            self.assertIs(self.fa(t), STR)
        self.assertIs(self.fa('None'), NONE)

    def test_containers(self):
        self.assertIs(self.fa('list[str]'), list_of(STR))
        self.assertIs(self.fa('List[Int]'), list_of(INT))
        self.assertIs(self.fa('dict[str, int]'), dict_of(STR, INT))
        self.assertIs(self.fa('Dict[str, list[int]]'), dict_of(STR, list_of(INT)))
        self.assertIs(self.fa('set[str]'), set_of(STR))
        self.assertIs(self.fa('tuple[int, str]'), tuple_of([INT, STR]))
        self.assertIs(self.fa('tuple[int, ...]'), list_of(INT))

    def test_optional_and_union_with_none(self):
        self.assertIs(self.fa('Optional[str]'), STR)
        self.assertIs(self.fa('str | None'), STR)
        self.assertIs(self.fa('None | Tok'), struct_of('Tok'))
        self.assertIs(self.fa('int | None'), DYN)

    def test_a_class_name_is_a_struct(self):
        self.assertIs(self.fa('Tok'), struct_of('Tok'))

    def test_anything_else_is_dyn(self):
        self.assertIs(self.fa('Unknown'), DYN)
        self.assertIs(self.fa(''), DYN)
        self.assertIs(self.fa('list[Unknown]'), list_of(DYN))
        self.assertIs(self.fa('Span[Int]'), DYN)

    def test_commas_inside_brackets_do_not_split(self):
        self.assertIs(self.fa('dict[str, tuple[int, str]]'),
                      dict_of(STR, tuple_of([INT, STR])))


class LowerRows(unittest.TestCase):
    """bugs/GIR_type_solver.md 2.4: `ret_ctype`, row by row."""

    class _Gen:
        def _resolve_type(self, name):
            return name + ' *'

    def test_every_row(self):
        g = self._Gen()
        rows = [(BOT, 'void'), (NONE, 'void'), (BOOL, '_Bool'), (INT, 'int64_t'),
                (FUNC, 'int64_t'), (DYN, 'int64_t'), (FLOAT, 'double'),
                (STR, 'char *'), (list_of(INT), 'MojoList *'),
                (tuple_of([INT]), 'MojoList *'), (dict_of(STR, INT), 'MojoDict *'),
                (set_of(INT), 'MojoSet *'), (struct_of('Tok'), 'Tok *')]
        for t, c in rows:
            self.assertEqual(lower.ret_ctype(g, t), c, t.key)


class Origins(unittest.TestCase):
    """bugs/GIR_type_solver_precision.md, step 1: every flow records its statement's line,
    and why `ret_sty` has no answer."""

    def test_a_return_flow_carries_its_line(self):
        src = 'def f():\n    x = 1\n    return x\n'
        sol = _solve({'main': src})
        fs = sol.prog.fns['/t/main.py\x1ff']
        origins = [fl.origin for fl in sol.prog.flows if fl.dst == fs.ret]
        self.assertIn('/t/main.py:3', origins)

    def test_a_flow_made_while_solving_inherits_its_creators_origin(self):
        # The argument flow `1 -> put.v` exists only once the solver resolves `t.put`,
        # so it is made while solving; it must carry the line of the `return` that
        # made the call (line 6).
        src = ('struct Tok:\n    var kind: String\n'
               '    def put(self, v):\n        return v\n'
               'def use(t: Tok):\n    return t.put(1)\n')
        sol = _solve({'main': src})
        put = sol.prog.fns['/t/main.py\x1fTok.put']
        into_v = [fl for fl in sol.prog.flows if fl.dst == put.params[1]]
        self.assertTrue(into_v)
        self.assertIn('/t/main.py:6', [fl.origin for fl in into_v])

    def test_a_none_receiver_waits_for_the_real_value(self):
        # `x` is `None` and then the dict argument; a transient `None` receiver must give
        # `bot`, not `dyn`, so the answer is the dict's `.get` (bugs/GIR_type_solver_precision.md, 4.2d).
        src = ('def f(d):\n    x = None\n    x = d\n    return x.get("k")\n'
               'def g():\n    return f({"k": "v"})\n')
        self.assertEqual(_ret({'main': src}, 'g'), 'str')

    def test_a_bot_return_site_makes_the_answer_undecided(self):
        # `o.unknown_field` is `bot` (no caller feeds `o`); joining would silently drop it
        # and answer `none`, so the answer must be undecided with reason `bot-return`.
        src = 'def f(o):\n    if o:\n        return o.unknown_field\n    return None\n'
        sol = _solve({'main': src})
        self.assertIsNone(sol.ret_sty('/t/main.py', 'f'))
        self.assertEqual(sol.why_none('/t/main.py', 'f'), 'bot-return')

    def test_isinstance_with_a_dotted_class_narrows(self):
        files = {
            'main': ('import m\ndef f(x):\n    if isinstance(x, m.C):\n        return x.name\n'
                     '    return None\n'),
            'm': 'struct C:\n    var name: String\n',
        }
        self.assertEqual(_ret(files, 'f'), 'str')

    def test_isinstance_and_a_field_on_the_right(self):
        src = ('struct Tok:\n    var name: String\n'
               'def f(x):\n    if isinstance(x, Tok) and x.name:\n        return x.name\n'
               '    return ""\n')
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_a_ternary_narrows_each_arm(self):
        src = 'def f(x):\n    return x if isinstance(x, str) else str(x)\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_the_early_return_idiom_narrows_the_rest_of_the_block(self):
        src = 'def f(x):\n    if not isinstance(x, dict):\n        return None\n    return x\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'dict[dyn, dyn]')

    def test_an_isinstance_tuple_narrows_to_the_join(self):
        src = 'def f(x):\n    if isinstance(x, (int, float)):\n        return x\n    return 0\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'dyn')

    def test_a_rebound_name_is_not_narrowed(self):
        # The soundness guard: `x` is rebound in the branch, so the fact does not apply to it.
        # Without the guard, `x` inside the branch would be narrowed to str, and the join of
        # the two returns would be dyn. With it, both returns are int.
        src = 'def f(x):\n    if isinstance(x, str):\n        x = 1\n        return x\n    return 0\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'int')

    def test_why_none_names_the_reason(self):
        self.assertEqual(_solve({'main': 'def f():\n    return 1\n'}).why_none('/t/main.py', 'f'), '')
        self.assertEqual(_solve({'main': 'def f() -> Int:\n    return 1\n'}).why_none('/t/main.py', 'f'),
                         'annotated')
        self.assertEqual(_solve({'main': 'def f():\n    yield 1\n'}).why_none('/t/main.py', 'f'),
                         'undecidable')
        self.assertEqual(_solve({'main': 'x = 1\n'}).why_none('/t/main.py', 'nope'), 'not-defined')


class Externs(unittest.TestCase):
    """bugs/GIR_type_solver_precision.md, 4.2a: external modules have CPython's types."""

    def test_os_path_functions_have_their_types(self):
        src = 'import os\ndef f(p):\n    return os.path.basename(p)\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')
        src = 'import os\ndef f(p):\n    return os.path.splitext(p)[0]\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_a_from_import_of_an_external_function(self):
        src = 'from os.path import join\ndef f(a, b):\n    return join(a, b)\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_open_and_read(self):
        self.assertEqual(_ret({'main': 'def f(p):\n    return open(p).read()\n'}, 'f'), 'str')
        src = 'def f(p):\n    with open(p) as fh:\n        return fh.read()\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_an_unknown_external_call_is_dyn(self):
        src = 'import weird\ndef f(p):\n    return weird.thing(p)\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'dyn')

    def test_os_path_is_never_a_field_read(self):
        # A closure class with a `path: list` field must not answer for `os.path`.
        src = ('import os\nstruct Resolver:\n    var path: List[Int]\n'
               'def f(p):\n    return os.path.basename(p)\n')
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_os_environ_get_with_a_default(self):
        src = 'import os\ndef f():\n    return os.environ.get("K", "d")\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_enumerate_and_zip(self):
        src = 'def f(xs):\n    for i, x in enumerate(xs):\n        return i\n    return 0\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'int')

    def test_every_callable_row_agrees_with_cpython(self):
        """Each row of externs.FUNCS is a fact about CPython: call the function on a sample
        and compare the result's type name with the row's annotation (risk R4)."""
        import importlib
        from mojo.tsolve import externs
        samples = {
            'os.path.basename': ('a/b.txt',), 'os.path.dirname': ('a/b.txt',),
            'os.path.join': ('a', 'b'), 'os.path.abspath': ('a',), 'os.path.normpath': ('a//b',),
            'os.path.splitext': ('a.b',), 'os.path.split': ('a/b',), 'os.path.exists': ('/',),
            'os.path.isfile': ('/',), 'os.path.isdir': ('/',), 'os.getcwd': (),
            'json.dumps': ({'a': 1},), 'textwrap.dedent': ('  x',), 'textwrap.indent': ('x', '  '),
            'shlex.quote': ('a b',), 'math.floor': (1.5,), 'math.ceil': (1.5,), 'math.sqrt': (4,),
        }
        py_name = {'str': 'str', 'bool': 'bool', 'int': 'int', 'float': 'float', 'tuple[str, str]': 'tuple'}
        for dotted in externs.FUNCS:
            self.assertIn(dotted, samples, 'add a sample for ' + dotted)
            mod_name, rest = dotted.split('.', 1)
            obj = importlib.import_module(mod_name)
            for part in rest.split('.'):
                obj = getattr(obj, part)
            got = type(obj(*samples[dotted])).__name__
            self.assertEqual(got, py_name[externs.FUNCS[dotted]], dotted)


class Summaries(unittest.TestCase):
    """Small programs, summarized and solved; the answers are what the language means."""

    def test_a_literal_return(self):
        self.assertEqual(_ret({'main': 'def f():\n    return 1\n'}, 'f'), 'int')

    def test_none_or_str_is_str(self):
        src = 'def f(x):\n    if x:\n        return "yes"\n    return None\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_a_fall_off_the_end_is_none(self):
        src = 'def f(x):\n    if x:\n        return 1\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'dyn')

    def test_both_branches_return_is_not_a_fall_off(self):
        src = 'def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'int')

    def test_a_tuple_return(self):
        src = 'def f():\n    return (1, "a")\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'tuple[int, str]')

    def test_a_list_return_of_a_call_result(self):
        src = 'def g():\n    return "s"\ndef f():\n    return [g()]\n'
        self.assertEqual(_ret({'main': src}, 'f'), 'list[str]')

    def test_an_annotation_beats_a_flow(self):
        # `p`'s parameter is annotated int: the str flowing in from `q` is ignored.
        src = ('def p(a: Int):\n    return a\n'
               'def q():\n    return p("s")\n')
        self.assertEqual(_ret({'main': src}, 'q'), 'int')

    def test_an_annotated_return_is_not_inferred(self):
        src = 'def f() -> Int:\n    return 1\n'
        self.assertIsNone(_ret({'main': src}, 'f'))

    def test_a_generator_is_undecidable(self):
        src = 'def f():\n    yield 1\n'
        self.assertIsNone(_ret({'main': src}, 'f'))

    def test_a_decorated_function_is_undecidable(self):
        src = '@staticmethod\ndef f():\n    return 1\n'
        self.assertIsNone(_ret({'main': src}, 'f'))

    def test_a_method_through_self(self):
        src = ('struct Tok:\n'
               '    var kind: String\n'
               '    def __init__(out self, kind: String):\n'
               '        self.kind = kind\n'
               '    def show(self):\n'
               '        return self.kind\n'
               'def use():\n'
               '    t = Tok("x")\n'
               '    return t.show()\n')
        self.assertEqual(_ret({'main': src}, 'use'), 'str')

    def test_a_constructor_call_is_the_struct(self):
        src = ('struct Tok:\n'
               '    var kind: String\n'
               'def make():\n'
               '    return Tok("x")\n')
        self.assertEqual(_ret({'main': src}, 'make'), 'struct:Tok')

    def test_isinstance_narrows_inside_its_branch(self):
        src = ('struct Tok:\n'
               '    var kind: String\n'
               'def n(x):\n'
               '    if isinstance(x, Tok):\n'
               '        return x.kind\n'
               '    return None\n')
        self.assertEqual(_ret({'main': src}, 'n'), 'str')

    def test_field_name_is_unanimous_over_the_classes(self):
        src = ('struct Tok:\n'
               '    var kind: String\n'
               'def h(x: Unknown):\n'
               '    return x.kind\n')
        self.assertEqual(_ret({'main': src}, 'h'), 'str')

    def test_an_fstring_field_with_a_call_is_decidable(self):
        # The call inside the f-string is parsed, so the function is decidable.
        src = ('def p(a: Int):\n    return a\n'
               'def f(x):\n    return f"{p(len(x))}!{x!r:>3}"\n')
        self.assertEqual(_ret({'main': src}, 'f'), 'str')

    def test_a_loop_read_before_its_assignment_still_sees_the_variable(self):
        src = ('def f(xs: list[Int]):\n'
               '    last = 0\n'
               '    for x in xs:\n'
               '        if x:\n'
               '            return last\n'
               '        last = x\n'
               '    return last\n')
        self.assertEqual(_ret({'main': src}, 'f'), 'int')

    def test_a_mutual_recursion_across_two_modules_reaches_the_cap(self):
        files = {
            'main': 'import other\ndef f(n):\n    return [other.g(n)]\n',
            'other': 'import main\ndef g(n):\n    return main.f(n)\n',
        }
        self.assertEqual(_ret(files, 'f', 'main'), 'list[list[list[dyn]]]')
        self.assertEqual(_ret(files, 'g', 'other', root='main'), 'list[list[list[dyn]]]')

    def test_a_cross_module_return_is_seen_by_the_importer(self):
        files = {
            'main': 'from other import make\ndef use():\n    return make(3)\n',
            'other': 'def make(n):\n    return [n, n + 1]\n',
        }
        self.assertEqual(_ret(files, 'use', 'main'), 'list[int]')

    def test_a_name_defined_twice_is_undecidable(self):
        src = 'def f():\n    return 1\ndef f():\n    return "s"\n'
        self.assertIsNone(_ret({'main': src}, 'f'))

    def test_an_unknown_construct_is_undecidable(self):
        src = 'def f(x):\n    match x:\n        case 1:\n            return 1\n'
        self.assertIsNone(_ret({'main': src}, 'f'))

    def test_solving_twice_gives_identical_vars(self):
        files = {
            'main': 'import other\ndef f(n):\n    return [other.g(n)]\n',
            'other': 'import main\ndef g(n):\n    return main.f(n)\n',
        }
        a = _solve(files, 'main').prog.vars
        b = _solve(files, 'main').prog.vars
        self.assertEqual([t.key for t in a], [t.key for t in b])


def main():
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for case in (JoinTable, FromAnnotation, LowerRows, Origins, Externs, Summaries):
        suite.addTests(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
