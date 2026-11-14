#!/usr/bin/env python3
"""Regression: Python 3.15 `lazy` import soft keyword (PEP 810).

Covers the whole feature this compiler implements:
  * the parser accepts `lazy import` / `lazy from ... import` at module
    scope, keeps `lazy` an ordinary identifier everywhere else, and rejects
    the three shapes CPython rejects (inside functions/classes/try, a lazy
    star-import, a lazy `__future__` import) with CPython 3.15's messages;
  * the interpreter binds a proxy immediately and defers loading side
    effects (and ImportError) to first use;
  * `__lazy_modules__`, `sys.set_lazy_imports`/`get_lazy_imports`,
    `sys.set_lazy_imports_filter`, `sys.lazy_modules` and
    `types.LazyImportType` behave as CPython 3.15.2 does.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as N


def _parse(src):
    return N.Parser(N.py_tokenize(src)).parse_module()


class TestLazyImportParser(unittest.TestCase):
    def test_lazy_import_statement(self):
        stmt = _parse("lazy import json")[0]
        self.assertIsInstance(stmt, N.ImportStmt)
        self.assertTrue(stmt.lazy)
        self.assertEqual(stmt.module, "json")

    def test_lazy_from_import_statement(self):
        stmt = _parse("lazy from pathlib import Path")[0]
        self.assertIsInstance(stmt, N.FromImportStmt)
        self.assertTrue(stmt.lazy)
        self.assertEqual(stmt.module, "pathlib")
        self.assertEqual(stmt.names, [("Path", None)])

    def test_lazy_is_still_an_ordinary_identifier(self):
        # Soft keyword: these must stay ordinary assignments/imports, not
        # become lazy imports.
        stmts = _parse("lazy = 5\nx = lazy\nimport lazy\n")
        self.assertIsInstance(stmts[0], N.AssignStmt)
        self.assertIsInstance(stmts[1], N.AssignStmt)
        self.assertIsInstance(stmts[2], N.ImportStmt)
        self.assertFalse(stmts[2].lazy)
        self.assertEqual(stmts[2].module, "lazy")

    def test_lazy_allowed_inside_module_level_if(self):
        # An `if` at module level does not create a function/class/try
        # scope, so CPython allows the keyword there.
        stmts = _parse("if True:\n    lazy import json\n")
        self.assertTrue(stmts[0].then_body[0].lazy)

    def _assert_syntax_error(self, src, message):
        with self.assertRaises(SyntaxError) as ctx:
            _parse(src)
        self.assertIn(message, str(ctx.exception))

    def test_lazy_import_rejected_in_function(self):
        self._assert_syntax_error(
            "def f():\n    lazy import json\n",
            "lazy import not allowed inside functions")

    def test_lazy_from_import_rejected_in_function(self):
        self._assert_syntax_error(
            "def f():\n    lazy from json import dumps\n",
            "lazy from ... import not allowed inside functions")

    def test_lazy_import_rejected_in_class(self):
        self._assert_syntax_error(
            "class C:\n    lazy import json\n",
            "lazy import not allowed inside classes")

    def test_lazy_import_rejected_in_try(self):
        self._assert_syntax_error(
            "try:\n    lazy import json\nexcept ImportError:\n    pass\n",
            "lazy import not allowed inside try/except blocks")

    def test_lazy_star_import_rejected(self):
        self._assert_syntax_error(
            "lazy from json import *",
            "lazy from ... import * is not allowed")

    def test_lazy_future_import_rejected(self):
        self._assert_syntax_error(
            "lazy from __future__ import annotations",
            "lazy from __future__ import is not allowed")

    def test_lazy_future_import_rejected_before_scope_check(self):
        # CPython's parser rejects this shape before the symtable checks the
        # enclosing function, so the future message wins.
        self._assert_syntax_error(
            "def f():\n    lazy from __future__ import annotations\n",
            "lazy from __future__ import is not allowed")

    def test_from_module_lazy_import_spelling_rejected(self):
        self._assert_syntax_error(
            "from json lazy import dumps",
            "use 'lazy from ... ' instead of 'from ... lazy import'")


class TestLazyImportInterpreter(unittest.TestCase):
    def _run_fire(self, source, siblings=None):
        with tempfile.TemporaryDirectory(dir=os.path.join(HERE, ".tmp")) as td:
            for name, text in (siblings or {}).items():
                with open(os.path.join(td, name), "w") as f:
                    f.write(text)
            path = os.path.join(td, "t.mojo")
            with open(path, "w") as f:
                f.write(source)
            return subprocess.run(
                [sys.executable, os.path.join(HERE, "fire.py"), "run", path],
                capture_output=True, text=True, timeout=60,
            )

    def test_lazy_import_defers_module_execution(self):
        heavy = "print('HEAVY LOADED')\nVALUE = 42\n"
        src = (
            "lazy import heavy\n"
            "print('before')\n"
            "print(heavy.VALUE)\n"
            "print('after')\n"
        )
        r = self._run_fire(src, siblings={"heavy.mojo": heavy})
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "before\nHEAVY LOADED\n42\nafter\n")

    def test_lazy_from_import_defers_module_execution(self):
        heavy = "print('HEAVY LOADED')\nVALUE = 42\ndef greet():\n    return 'hi'\n"
        src = (
            "lazy from heavy import VALUE, greet\n"
            "print('before')\n"
            "print(greet())\n"
            "print(VALUE)\n"
        )
        r = self._run_fire(src, siblings={"heavy.mojo": heavy})
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        # The module body runs once, on the first use of EITHER name.
        self.assertEqual(
            r.stdout, "before\nHEAVY LOADED\nhi\n42\n")

    def test_lazy_import_of_sys_and_types_resolves_canonical_proxies(self):
        # `lazy import sys` rebinds the name `sys` to a proxy whose resolver
        # must not look the module up through the same scope (that re-enters
        # resolve() forever); the same applies to the interpreter's `types`
        # proxy. Both are also exact targets of the PEP's "ordinary import"
        # behaviour.
        src = (
            "lazy import sys\n"
            "lazy import types\n"
            "print('before')\n"
            "print(sys.argv[0].endswith('t.mojo'))\n"
            "print(types.LazyImportType.__name__)\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "before\nTrue\nLazyImportType\n")

    def test_lazy_dotted_import_resolves_from_function_scope(self):
        # First use can happen inside a function, where that call's local
        # scope (not the module's) is current; resolving a dotted sibling
        # import must still build the namespace chain in the scope the lazy
        # statement ran in.
        siblings = {
            "pkg/__init__.mojo": "ROOT = 1\n",
            "pkg/sub.mojo": "VALUE = 7\n",
        }
        src = (
            "lazy import pkg.sub\n"
            "def get():\n"
            "    return pkg.sub.VALUE\n"
            "print('before')\n"
            "print(get())\n"
        )
        # sub.mojo lives in a package directory; the temporary-directory
        # helper writes flat files, so make the directory explicitly.
        with tempfile.TemporaryDirectory(dir=os.path.join(HERE, ".tmp")) as td:
            os.makedirs(os.path.join(td, "pkg"))
            for name, text in siblings.items():
                with open(os.path.join(td, name), "w") as f:
                    f.write(text)
            path = os.path.join(td, "t.mojo")
            with open(path, "w") as f:
                f.write(src)
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, "fire.py"), "run", path],
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "before\n7\n")

    def test_import_error_is_deferred_to_first_use(self):
        src = (
            "lazy import missing_module_xyz\n"
            "print('started')\n"
            "print('still ok')\n"
            "try:\n"
            "    print(missing_module_xyz.anything)\n"
            "except ModuleNotFoundError:\n"
            "    print('caught at use')\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout, "started\nstill ok\ncaught at use\n")

    def test_sys_modules_and_lazy_modules_track_reification(self):
        src = (
            "import sys\n"
            "import types\n"
            "lazy import fractions\n"
            "lazy from decimal import Decimal, getcontext\n"
            "print('before', 'fractions' in sys.modules, 'decimal' in sys.modules)\n"
            "print('lazy', 'fractions' in sys.lazy_modules)\n"
            "print('type', types.LazyImportType.__name__)\n"
            "print(fractions.Fraction(1, 2))\n"
            "print('after', 'fractions' in sys.modules, 'fractions' in sys.lazy_modules)\n"
            "print(Decimal('1.5') + Decimal('2.5'))\n"
            "print('decimal lazy', sorted([n for n in sys.lazy_modules if 'decimal' in n]))\n"
            "print(getcontext().prec > 0)\n"
            "print('decimal lazy after', sorted([n for n in sys.lazy_modules if 'decimal' in n]))\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "before False False")
        self.assertEqual(lines[1], "lazy True")
        self.assertEqual(lines[2], "type LazyImportType")
        self.assertEqual(lines[3], "1/2")
        self.assertEqual(lines[4], "after True False")
        # Resolving ONE name reifies only that name: getcontext is still
        # pending, and the shared module-load entry is gone.
        self.assertEqual(lines[5], "4.0")
        self.assertEqual(lines[6], "decimal lazy ['decimal.getcontext']")
        self.assertEqual(lines[7], "True")
        self.assertEqual(lines[8], "decimal lazy after []")

    def test_lazy_modules_attribute_makes_imports_lazy(self):
        src = (
            "__lazy_modules__ = ['fractions']\n"
            "import sys\n"
            "import fractions\n"
            "import decimal\n"
            "print('fractions', 'fractions' in sys.modules)\n"
            "print('decimal', 'decimal' in sys.modules)\n"
            "print(fractions.Fraction(1, 2))\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout, "fractions False\ndecimal True\n1/2\n")

    def test_lazy_modules_attribute_does_not_affect_function_imports(self):
        # Measured against CPython 3.15.2: __lazy_modules__ is only
        # consulted for module-level import statements.
        src = (
            "__lazy_modules__ = ['fractions']\n"
            "import sys\n"
            "def f():\n"
            "    import fractions\n"
            "    return 'fractions' in sys.modules\n"
            "print(f())\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(r.stdout, "True\n")

    def test_sys_set_lazy_imports_modes_and_validation(self):
        src = (
            "import sys\n"
            "print(sys.get_lazy_imports())\n"
            "sys.set_lazy_imports('all')\n"
            "print(sys.get_lazy_imports())\n"
            "sys.set_lazy_imports('normal')\n"
            "try:\n"
            "    sys.set_lazy_imports('none')\n"
            "except ValueError:\n"
            "    print('rejected mode')\n"
            "try:\n"
            "    sys.set_lazy_imports(1)\n"
            "except TypeError:\n"
            "    print('rejected type')\n"
            "try:\n"
            "    sys.set_lazy_imports_filter(1)\n"
            "except ValueError:\n"
            "    print('rejected filter')\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout, "normal\nall\nrejected mode\nrejected type\nrejected filter\n")

    def test_lazy_imports_mode_all(self):
        src = (
            "import sys\n"
            "sys.set_lazy_imports('all')\n"
            "import fractions\n"
            "import decimal\n"
            "print('loaded', 'fractions' in sys.modules, 'decimal' in sys.modules)\n"
            "print(fractions.Fraction(1, 2))\n"
            "print('after', 'fractions' in sys.modules)\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout, "loaded False False\n1/2\nafter True\n")

    def test_lazy_imports_filter_forces_eager(self):
        src = (
            "import sys\n"
            "def allow(importer, name, fromlist):\n"
            "    print('filter', name, fromlist)\n"
            "    return name != 'fractions'\n"
            "sys.set_lazy_imports_filter(allow)\n"
            "lazy import fractions\n"
            "lazy from decimal import Decimal\n"
            "print('fractions', 'fractions' in sys.modules)\n"
            "print('decimal', 'decimal' in sys.modules)\n"
            "sys.set_lazy_imports_filter(None)\n"
            "print(sys.get_lazy_imports_filter())\n"
        )
        r = self._run_fire(src)
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout,
            "filter fractions None\n"
            "filter decimal ('Decimal',)\n"
            "fractions True\n"
            "decimal False\n"
            "None\n")

    def test_lazy_from_import_of_mojo_sibling_module(self):
        heavy = "print('HEAVY LOADED')\nVALUE = 42\ndef greet():\n    return 'hi'\n"
        src = (
            "lazy from heavy import VALUE, greet\n"
            "print('before')\n"
            "print(greet())\n"
            "print(VALUE)\n"
        )
        r = self._run_fire(src, siblings={"heavy.mojo": heavy})
        self.assertEqual(r.returncode, 0, r.stderr + "\n" + r.stdout)
        self.assertEqual(
            r.stdout, "before\nHEAVY LOADED\nhi\n42\n")


if __name__ == "__main__":
    unittest.main()
