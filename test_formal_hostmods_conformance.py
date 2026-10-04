#!/usr/bin/env python3
r"""Every `formal/hostmods` module, against CPython's OWN regression tests.

    python3 test_formal_hostmods_conformance.py [-v] [--list] [group ...]
    python3 test_formal_hostmods_conformance.py --cases <group>
    python3 test_formal_hostmods_conformance.py --dump-cases <group> <file>

Groups are named after the module: `posixpath`, `textwrap`, `struct`,
`shlex`, `math`. With no argument, all of them. Every group builds and RUNs an
image on BOTH backends.

WHY THIS FILE EXISTS, AND WHY IT IS NOT ANOTHER `test_formal_<module>.py`
-------------------------------------------------------------------------
There is already one differential test per host module, and each of them builds
its corpus BY HAND. That is what they are for and it is not a criticism of them:
`test_formal_textwrap.py`'s corpus separates one rule of `dedent` from another
and says which, and a hand-picked corpus is the only way to say that. The cost
is that a hand-picked corpus is also the corpus whose OMISSION nobody notices.

**CPython ships a regression test for every module this tree models**, and the
machine has them:

    python3 -c 'import test, os; print(os.path.dirname(test.__file__))'
    .../lib/python3.14/test/test_posixpath.py, test_textwrap.py, ...

So the case table here is GENERATED from those files rather than transcribed,
which means it is CPython's own idea of what a module must answer, it grows when
CPython grows, and no case in it can be wrong in the way a transcription is
wrong. `test_formal_posixpath.py`'s 484 cases and this file's are different
sets over the same functions; a divergence in the overlap is a real one, and a
divergence outside this file's set is a hole this file closes.

WHERE THE CASES COME FROM, PRECISELY
------------------------------------
A case is a CALL in CPython's own test file whose arguments the harvester can
resolve to constants, calling a name the module under test owns, with no
non-literal argument left over. The harvester (`_Harvester` below) is a
straight-line constant propagator over the test file's `ast`, so it resolves
what CPython's tests resolve by construction: a name assigned a literal, a
concatenation of two literals, `-<literal>`, a `for` over a literal list, and a
class attribute built from literal tuples (`test_textwrap.py`'s `CASES`, which
is `ROUNDTRIP_CASES + (...)` and is where half of `indent`'s cases live). It does
NOT do flow analysis: a name assigned in two branches of an `if` resolves to
nothing, which is the conservative direction — a case that is really a
function of a runtime value is dropped rather than pinned to one of them.

Three things are deliberately NOT harvested, and the count of each is printed:

  * a call with an argument the harvester cannot resolve (`+12`),
  * a `bytes` argument — CPython's tests deliberately run every path case twice,
    once as `str` and once as `bytes`, and a `bytes` object has NO representation
    on this path at all (`formal/hostmods/struct.mojo`'s value-model section,
    `bugs/FORMAL_bytearray_and_bytes_have_no_representation.md`), so the `str`
    half is the half a model can answer;
  * a call CPython's own suite asserts something about whose answer this process
    cannot reproduce — the `expanduser` cases depend on `HOME` and the test
    guards it with `support.EnvironmentVarGuard`, which the harvester does not
    execute. Those are still COMPARED (model against this process's `posixpath`,
    same environment both sides) and they are listed as `unconfirmed`, because
    "CPython's suite asserts an answer this process did not reproduce" is a fact
    about the guard and not about the model.

ORACLE FIDELITY, WHICH IS THE PART THAT MAKES THE TABLE TRUSTWORTHY
-------------------------------------------------------------------
Every harvested call is classified by whether this process's own CPython
reproduces the value CPython's test file ASSERTS beside it. `assertEqual` and
`assertIs` in the test file carry the expectation as a literal in the common
case, so a case can be `confirmed` (this process answers what CPython's suite
says it answers), `unconfirmed` (it does not — the guard case above), or
`unasserted` (the call is not the subject of an assertion literal, e.g. it is an
argument to `checkEqual` or a loop over a computed expectation). A case is
compared against the model in all three states, because the question this file
asks is "does the model agree with CPython **in this process**", and the
fidelity label is what tells a reader whether an agreement is also agreement
with CPython's own expectation.

RECORDS, AND WHY THE ANSWER'S LENGTH IS IN THEM
------------------------------------------------
`<case>|<kind>:...` with a `@@` terminator, and a STRING answer is bracketed with
its own byte length:

    %lld|s:%lld:[%s]@@      a string, `<n>` bytes inside the brackets
    %lld|i:%lld@@           an integer
    %lld|t:<part>:%lld:[%s]@@   one element of a two-element answer

The length is what makes the parse sound. A path can contain `@@`, `]` and
`@`, so a record cannot be split on its terminator and must be split on a
COUNT; and the count is computed by the IMAGE over its own answer
(`strlen(v)`), not supplied here, so a value truncated in transport is reported
as a transport failure rather than compared as if it were an answer. This is
`test_formal_textwrap.py`'s record format, for the same reason, and
`test_formal_run.py`'s harness cases avoid line-structured output for it.

A string ARGUMENT is spelled through `mask`/`mj`/`unmask` from
`test_formal_json.py` — imported, not copied, because a third copy of an escape
table is a third thing to be right about — and the driver imports `json` for
the three byte helpers `unmask` calls. A string is carried as UTF-8 BYTES, and
that is a real narrowing worth stating: this path has no code points, so a case
with a non-ASCII argument is compared as "does the model reproduce CPython's
UTF-8 encoding of its own answer", which is the strongest claim available and
is not the same claim as code-point equality. Those cases are counted and
labelled `utf8` so a reader knows which ones they are.

THE MODEL'S SPELLING IS NOT ALWAYS CPython's, AND THE TABLE SAYS SO
--------------------------------------------------------------------
`formal/hostmods/posixpath.mojo` is a re-spelling of `os.path`, and
`formal/hostmods/math.mojo` is "every function in CPython's `math` that can
answer an `int`" with the variadic spellings re-shaped. So each function in
`MODULES` below carries the model's parameter names, and a case is skipped with
a counted reason when the model's spelling cannot express CPython's call:
`math.gcd()` with no arguments, `textwrap.indent` with a `predicate`, a
`posixpath.splitroot` tuple where the model ships only the root half. A skip is
not a pass: the counts are printed and `--list` reports them, so a function that
stops being harvestable is visible.

WHY NOT ALL TWENTY-SIX MODULES
------------------------------
Because the cases have to exist. `test_formal_stat.py` is a case table with
65,547 rows built by a loop, which is strictly more than any harvest of
`test_stat.py` could be (`test_stat.py` calls `self.statmod.filemode(st_mode)` —
a loop variable, so there is no literal call to harvest at all). `glob`,
`hashlib`, `json`, `ast`, `enum`, `sys`, `os`, `time`, `platform`, `re` and
`argparse` are listed in `NOT_YET` with the measured reason for each, and
`--list` prints that table. Adding a module is one entry in `MODULES`.
"""
import argparse
import ast
import contextlib
import importlib
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 300
REC = "@@"

sys.path.insert(0, HERE)

# The driver and the pass/fail helper live in the dylib suite, and the string
# mask with its Mojo half lives in the json suite. Both are imported rather than
# copied, for the reason this file's own docstring gives for its case table: a
# second copy of either is a second thing to be wrong about, and this file's
# records are read by the same parser that `test_formal_json.py` wrote.
from test_formal_dylib import (Failure, TestFailure, check, run_fire)  # noqa: E402,F401
from test_formal_json import UNMASK, mask, mj  # noqa: E402,F401

BACKENDS = ("arm64", "x86_64")

TEMP = None


# ── CPython's own regression tests ─────────────────────────────────────────

def cpython_test_dir():
    """Where this interpreter keeps `Lib/test`, or a hard failure.

    Asked of the interpreter rather than searched for, so the table and the
    oracle come from the SAME CPython: `test_posixpath.py` from one version and
    `posixpath` from another would be a comparison of two releases, and the
    failure would look like a model bug.
    """
    try:
        import test as _test
    except ImportError as exc:                          # pragma: no cover
        raise Failure(f"this interpreter has no `test` package ({exc}); the "
                      f"whole case table is CPython's own regression suite and "
                      f"there is nothing to generate it from")
    return os.path.dirname(os.path.abspath(_test.__file__))


CPY_TEST_DIR = cpython_test_dir()


def cpython_test_files(module):
    """`test_<module>` as a list of source files.

    A directory as well as a file, because five of the modules this tree models
    have a test PACKAGE upstream — `test_json/`, `test_dataclasses/`,
    `test_pathlib/`, `test_ast/`, `test_ctypes/` — and a harvester that only
    knew about `test_x.py` would report "no cases" for a module with thousands.
    `__init__.py` and `__main__.py` are included: `test_json/__init__.py` is
    where most of that suite's `loads` cases are.
    """
    base = os.path.join(CPY_TEST_DIR, "test_" + module)
    if os.path.isfile(base + ".py"):
        return [base + ".py"]
    if os.path.isdir(base):
        return sorted(os.path.join(base, f) for f in os.listdir(base)
                      if f.endswith(".py"))
    return []


# ── the harvester ──────────────────────────────────────────────────────────
#
# `ast.Constant` for a literal, plus the four shapes CPython's test files build
# their arguments out of, and nothing else. `_PRIMITIVE` excludes `bytes`,
# `None` and `complex` ON PURPOSE: a `bytes` argument has no representation on
# this path (`formal/hostmods/struct.mojo`'s "THE VALUE MODEL" section), and
# `None` is the word 0, so a case carried by either would compare a model answer
# with an answer to a different question.

_PRIMITIVE = (str, int, bool, float)


class _Harvester:
    """Constant propagation over one CPython test file.

    A case is emitted the moment a call to a name the module owns is resolved
    against the environment. Nothing is recorded about the test that contains
    it: the case is the CALL, so a case is a thing CPython's suite really does
    execute, and the expectation beside it is harvested separately by
    `_assertion_for` for the fidelity label.
    """

    def __init__(self, module, wanted, cases, stats):
        self.module = module
        self.wanted = wanted
        self.cases = cases
        self.stats = stats
        self.direct = {}
        self.alias = []

    # bindings ──────────────────────────────────────────────────────────────

    def read_bindings(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == self.module:
                for alias in node.names:
                    self.direct[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == self.module:
                        self.alias.append(alias.asname or alias.name)
        self.direct = {k: v for k, v in self.direct.items()
                       if v in self.wanted}

    # the constant folder ────────────────────────────────────────────────────

    def const(self, node, env):
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            return node.value if type(node.value) in _PRIMITIVE else None
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "self":
            return env.get(node.attr)
        if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant) \
                and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = node.operand.value
            if type(value) in (int, float):
                return -value if isinstance(node.op, ast.USub) else +value
        if isinstance(node, ast.BinOp):
            return self._binop(node, env)
        if isinstance(node, ast.Tuple):
            return self._sequence(node.elts, env)
        if isinstance(node, ast.List):
            return self._sequence(node.elts, env)
        return None

    def _sequence(self, elements, env):
        """A tuple of constants, or None.

        `test_textwrap.py`'s `CASES = ROUNDTRIP_CASES + ( ... )` is the reason
        this exists: without it every case in `IndentTestCase` is invisible,
        because the corpus is a class attribute concatenated at class level.
        """
        out = []
        for element in elements:
            value = self.const(element, env)
            if value is None:
                return None
            out.append(value)
        return tuple(out)

    def _binop(self, node, env):
        left = self.const(node.left, env)
        right = self.const(node.right, env)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
        except (TypeError, ZeroDivisionError):
            return None
        return None

    # the walk ───────────────────────────────────────────────────────────────

    def body(self, statements, env):
        for statement in statements:
            self.statement(statement, env)

    def statement(self, node, env):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # A method body starts from the CLASS environment and nothing else:
            # `self.CASES` has to be visible and a name the previous method
            # bound must not be.
            self.body(node.body, dict(env))
        elif isinstance(node, ast.ClassDef):
            self.body(node.body, dict(env))
        elif isinstance(node, ast.Assign):
            value = self.const(node.value, env)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if value is None:
                        env.pop(target.id, None)
                    else:
                        env[target.id] = value
                else:
                    self.descend(target, env)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = self.const(node.value, env) if node.value is not None else None
            if value is None:
                env.pop(node.target.id, None)
            else:
                env[node.target.id] = value
        elif isinstance(node, ast.If):
            # Both arms get their OWN environment and neither is kept: a name
            # bound under a condition is not a constant, and pinning it to one
            # arm would manufacture a case CPython's suite never runs.
            self.body(node.body, dict(env))
            self.body(node.orelse, dict(env))
        elif isinstance(node, ast.For):
            self._for(node, env)
            self.body(node.orelse, dict(env))
        elif isinstance(node, ast.While):
            self.body(node.body, dict(env))
            self.body(node.orelse, dict(env))
        elif isinstance(node, ast.With):
            self.body(node.body, dict(env))
        elif isinstance(node, ast.Try):
            self.body(node.body, dict(env))
            for handler in node.handlers:
                self.body(handler.body, dict(env))
            self.body(node.orelse, dict(env))
            self.body(node.finalbody, dict(env))
        elif isinstance(node, (ast.Expr, ast.Return)):
            self.descend(node.value, env) if node.value is not None else None
        # anything else contributes no constant and no case

    def _for(self, node, env):
        """Walk a `for` body once per LITERAL element.

        `test_posixpath.py` and `test_textwrap.py` both build their corpus in a
        loop, and a loop over a computed iterable yields nothing — which is the
        conservative answer. A loop over a list of literals yields one case per
        element, which is what the test file executes, so each of them is a case
        CPython's suite really runs.

        The loop variable and the body each get a fresh environment: nothing
        the body binds outlives the iteration, or a later case would be pinned
        to the last element's value.
        """
        iterable = self.const(node.iter, env)
        targets = node.target
        names = []
        if isinstance(targets, ast.Name):
            names = [targets]
        elif isinstance(targets, (ast.Tuple, ast.List)):
            names = [e for e in targets.elts if isinstance(e, ast.Name)]
        if iterable is None or isinstance(iterable, (str, bytes)) or not names:
            self.body(node.body, dict(env))
            return
        for element in iterable:
            scoped = dict(env)
            if len(names) == 1 and not isinstance(element, tuple):
                scoped[names[0].id] = element
            elif len(names) == 1 and isinstance(element, tuple):
                continue          # a destructuring loop: not one case
            else:
                if not isinstance(element, tuple) or len(element) != len(names):
                    continue
                for name, value in zip(names, element):
                    scoped[name.id] = value
            self.body(node.body, scoped)

    def descend(self, node, env):
        """Walk a subtree, recording each CALL exactly once.

        The recursion stops at a call rather than walking through it, because
        `call()` already descends into its own arguments. An `ast.walk` here
        instead visits `self.assertEqual(posixpath.basename(x), "bar")`'s outer
        call, descends into the argument, records `basename`, and then walks on
        to the SAME `basename` node and records it again — which is how
        `test_posixpath.py` came out with twenty harvested `basename` calls at
        five distinct lines and a case table twice the size of its subject.
        """
        if node is None:
            return
        if isinstance(node, ast.Call):
            self.call(node, env)
            return
        for child in ast.iter_child_nodes(node):
            self.descend(child, env)

    def call(self, node, env):
        name = None
        function = node.func
        if isinstance(function, ast.Name) and function.id in self.direct:
            name = self.direct[function.id]
        elif isinstance(function, ast.Attribute) \
                and isinstance(function.value, ast.Name) \
                and function.value.id in self.alias \
                and function.attr in self.wanted:
            name = function.attr
        if name is not None and name in self.wanted:
            self._record(node, name, env)
            return
        for argument in node.args:
            self.descend(argument, env)
        for keyword in node.keywords:
            self.descend(keyword.value, env)

    def _record(self, node, name, env):
        """One harvested case, or a counted reason there is not one.

        A case that cannot be expressed is COUNTED and named, never dropped
        quietly: a filter that discards cases silently is a filter whose
        coverage nobody can reason about, and `--list` prints these counts so a
        function that stops being harvestable is visible rather than gone.
        """
        if not node.args and not node.keywords:
            self.stats["no argument"] += 1
            return
        if isinstance(node.func, ast.Attribute) and node.func.attr in self.wanted \
                and node.func.attr not in self.direct.values() \
                and not (isinstance(node.func.value, ast.Name)
                         and node.func.value.id in self.alias):
            return                       # some other module's same-named call
        positional = [self.const(a, env) for a in node.args]
        keywords = {k.arg: self.const(k.value, env) for k in node.keywords}
        unresolved = any(v is None for v in positional) \
            or any(v is None for v in keywords.values())
        if unresolved:
            self.stats["argument not a constant"] += 1
            return
        if any(isinstance(v, (bytes, bytearray)) for v in positional):
            self.stats["bytes argument has no representation"] += 1
            return
        self.cases.append({
            "file": self.path,
            "line": node.lineno,
            "fn": name,
            "args": positional,
            "keywords": keywords,
            "node": node,
        })

    path = "<unknown>"


class _ParentTagger(ast.NodeTransformer):
    """Tag every node with its parent, so `_assertion_for` can look sideways.

    A `NodeTransformer` is the cheap way to do this without a second walk over
    every file with a hand-rolled visitor, and it is run on a THROWAWAY copy of
    the tree — the one the harvester then walks.
    """

    def generic_visit(self, node):
        node._conf_children = list(ast.iter_child_nodes(node))
        for child in node._conf_children:
            child._conf_parent = node
        return super().generic_visit(node)


def _literal_expectation(call_node):
    """The expectation beside `call_node`, when there is a literal one.

    `assertEqual` and `assertIs` are the two that carry an expectation in the
    common case. `assertRaises` carries an EXCEPTION, which is the other thing
    this file wants to know about a case, so it is reported as
    `("raises", "ValueError")` and the group below counts it.
    """
    parent = getattr(call_node, "_conf_parent", None)
    if parent is None or not isinstance(parent, ast.Call):
        return None
    function = parent.func
    if not isinstance(function, ast.Attribute):
        return None
    if function.attr in ("assertEqual", "assertIs"):
        # the expectation is the sibling literal AFTER the call node
        seen = False
        for child in getattr(parent, "_conf_children", []):
            if child is call_node:
                seen = True
                continue
            if seen and isinstance(child, ast.Constant) \
                    and type(child.value) in _PRIMITIVE:
                return ("value", child.value)
        return None
    if function.attr == "assertRaises":
        for child in getattr(parent, "_conf_children", []):
            if isinstance(child, ast.Name):
                return ("raises", child.id)
            if isinstance(child, ast.Attribute):
                return ("raises", child.attr)
        return None
    return None


# ── the case table ─────────────────────────────────────────────────────────

class Case:
    """One harvested case, with CPython's own answer to it."""

    __slots__ = ("module", "file", "line", "fn", "args", "keywords",
                 "oracle", "fidelity", "unicode", "case_number",
                 "bound", "kind", "template", "emit", "want", "status")

    def __init__(self, **kw):
        for key in self.__slots__:
            setattr(self, key, kw.get(key))

    def __repr__(self):
        return f"<Case {self.module}.{self.fn}{tuple(self.args)} line " \
               f"{self.line} -> {self.oracle!r}>"


def _encodable(value):
    """Whether `value` has a UTF-8 spelling, which is what the model is handed.

    `test_posixpath.py` has four cases that assert `posixpath.realpath` of a path
    beginning with U+DFFF RAISES `UnicodeEncodeError`, and four more that are the
    same case behind a variable. A lone surrogate is a real code point CPython
    can hold and this path cannot spell, so those cases are counted and left out
    rather than turned into a byte the model was never asked about.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _describe(fn, args, keywords):
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in keywords.items()]
    return f"{fn}({', '.join(parts)})"


def cpython_answer(module, fn, args, keywords):
    """CPython's own answer, computed HERE and now, or the exception it raises.

    There is no table of expected values anywhere in this file: every answer is
    a call into the interpreter that is reading this file. That is the whole
    point of a conformance table whose subject is conformance, and it is why a
    CPython upgrade cannot leave a stale expectation behind.
    """
    real = getattr(module, fn, None)
    if real is None:
        raise Failure(f"CPython's `{module.__name__}` has no `{fn}`; the "
                      f"model's table names a function this CPython does not")
    try:
        return ("value", real(*args, **keywords))
    except Exception as exc:                      # noqa: BLE001 — the point
        return ("raises", type(exc).__name__, str(exc))


def build_cases(spec):
    """The case table for `spec`: harvested, filtered, and answered.

    Returns `(cases, stats, stats_detail)`. `stats` counts what was dropped and
    why, per reason; nothing is dropped silently, because a filter that
    discards cases quietly is a filter whose coverage nobody can reason about.
    """
    cases = []
    stats = {"no argument": 0, "argument not a constant": 0,
             "bytes argument has no representation": 0,
             "model spelling cannot express the call": 0,
             "CPython raises and the model has no exception surface": 0,
             "argument is not a str where one is required": 0,
             "argument has no UTF-8 spelling (a lone surrogate)": 0,
             "argument is not ASCII and the model matches bytes": 0,
             "argument holds a NUL, which a formal string cannot": 0}
    files = cpython_test_files(spec.name)
    if not files:
        return [], stats, {"no CPython regression test for this module": 1}
    for path in files:
        source = open(path, encoding="utf-8").read()
        tree = _ParentTagger().visit(ast.parse(source, path))
        harvester = _Harvester(spec.name, set(spec.fns), cases, stats)
        harvester.read_bindings(tree)
        harvester.path = os.path.relpath(path, CPY_TEST_DIR)
        harvester.body(tree.body, {})
    # deduplicate: the same call reached twice (a base class's method and the
    # subclass's, or a helper called from two places) is ONE case, and keeping
    # both would make the table's size a fact about the test file's shape.
    seen = set()
    unique = []
    for case in cases:
        key = (case["fn"], tuple(map(repr, case["args"])),
               tuple(sorted(case["keywords"].items())))
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    cpy = importlib.import_module(spec.name)
    out = []
    for case in unique:
        entry = Fn(spec, case["fn"])
        if entry is None:
            stats["model spelling cannot express the call"] += 1
            continue
        bound = entry.bind(case["args"], case["keywords"])
        if bound is None:
            stats["model spelling cannot express the call"] += 1
            continue
        if entry.strings_only and any(not isinstance(v, str) for v in bound):
            stats["argument is not a str where one is required"] += 1
            continue
        if spec.ascii_only and any(isinstance(v, str) and not v.isascii()
                                   for v in bound):
            stats["argument is not ASCII and the model matches bytes"] += 1
            continue
        if any(isinstance(v, str) and "\x00" in v for v in bound):
            # A formal string is a bare NUL-TERMINATED `char *`
            # (`bugs/FORMAL_string_value_model.md`), so a NUL inside an
            # argument truncates it and the model would be asked about a
            # DIFFERENT input rather than about this one. CPython's
            # `test_re.py` has two cases that are exactly this --
            # `re.match('\\0', '\x00')` and `re.match('\\08', '\x008')` --
            # and answering them 0 is a wrong answer to a right question about
            # an input that cannot be asked about.
            stats["argument holds a NUL, which a formal string cannot"] += 1
            continue
        if any(isinstance(v, str) and not _encodable(v) for v in bound):
            # A lone SURROGATE is CPython's own answer to "what is this path",
            # and it has no UTF-8 spelling — `test_posixpath.py` has four cases
            # that assert exactly that. This path's value model is a byte
            # string, so the case has no question to put to the model.
            stats["argument has no UTF-8 spelling (a lone surrogate)"] += 1
            continue
        oracle = cpython_answer(cpy, case["fn"], case["args"], case["keywords"])
        if oracle[0] == "raises":
            # Reported, never compiled: the model has no exception surface, so
            # there is no question to put to it, and pretending otherwise would
            # mean a case that can only ever agree.
            stats["CPython raises and the model has no exception surface"] += 1
        asserted = _literal_expectation(case["node"])
        want = None
        if oracle[0] == "value" and entry.oracle is not None:
            want = entry.oracle(oracle[1])
        out.append(Case(
            module=spec.name, file=case["file"], line=case["line"],
            fn=case["fn"], args=case["args"], keywords=case["keywords"],
            oracle=oracle, fidelity=_fidelity(oracle, asserted),
            unicode=any(isinstance(v, str) and not v.isascii()
                        for v in bound),
            case_number=len(out),
            bound=bound, kind=entry.kind, template=entry.template,
            emit=entry.emit, want=want,
            status=spec.statuses.get(case["fn"], (None, None))[0],
        ))
    detail = {}
    for case in cases:
        key = (case["fn"], tuple(map(repr, case["args"])),
               tuple(sorted(case["keywords"].items())))
        detail[key] = detail.get(key, 0) + 1
    dropped = len(cases) - len(unique)
    if dropped:
        stats["duplicate call seen more than once"] = dropped
    return out, stats, None


def _fidelity(oracle, asserted):
    if asserted is None:
        return "unasserted"
    if asserted[0] == "raises":
        return "confirmed" if oracle[0] == "raises" and \
            oracle[1] == asserted[1] else "unconfirmed"
    if oracle[0] != "value":
        return "unconfirmed"
    return "confirmed" if oracle[1] == asserted[1] else "unconfirmed"


class Fn:
    """How one CPython function maps onto the MODEL's spelling of it."""

    def __init__(self, spec, name):
        entry = spec.fns.get(name)
        self.spec = spec
        self.name = name
        if entry is None:
            return
        kind, template, params, emit, oracle = entry
        self.kind = kind
        self.template = template
        self.params = params
        self.emit = emit
        # How CPython's ANSWER becomes the value the model's answer is compared
        # with. `re.match` answers a match OBJECT or None, and the model's
        # `match_at` answers a status word; comparing those two directly is
        # comparing a class to an integer and every case would differ. So the
        # entry says how to reduce CPython's answer to the same THING, and
        # `None` means "use it as it is".
        self.oracle = oracle
        self.strings_only = kind in ("s", "t")

    def bind(self, args, keywords):
        """The model's arguments, or None when the spelling cannot carry them.

        CPython's parameter NAMES are the model's too where the model has a
        real signature, so a keyword in CPython's suite is placed by name. A
        parameter the model does not have — `textwrap.indent`'s `predicate`,
        `math.prod`'s iterable — is a skip with a counted reason, not a guess.
        """
        if self.params is None:
            if args:
                return None
            return []
        if any(name not in self.params for name in keywords):
            # A keyword the MODEL does not have is not a keyword to drop:
            # `posixpath.realpath(p, strict=False)` is a different question from
            # `posixpath.realpath(p)` and answering the second for the first is
            # how a conformance table ends up quietly testing something nobody
            # wrote.
            return None
        values = dict(keywords)
        if len(args) > len(self.params):
            return None
        for name, value in zip(self.params, args):
            values[name] = value
        if any(name not in values for name in self.params):
            return None
        return [values[name] for name in self.params]


# ── the module table ───────────────────────────────────────────────────────
#
# `fns` maps a CPython name to `(kind, template, params, part)`:
#
#   kind      "s" a string answer, "i" an integer, "t" a two-element answer
#   template  the model's call, `%s` once per parameter
#   params    the model's parameter NAMES, in order, or None for a nullary one
#   part      for a projected tuple, which element the model actually answers

S1 = "s"
I1 = "i"
T2 = "t"


class Spec:
    """One module: where its source is, which CPython suite carries its cases,
    and how each of its functions is spelled by the MODEL.

    A class rather than a dict because the six fields are read in six different
    places and `spec.name` at all of them is worse to read than `spec.name`.
    """

    def __init__(self, name, source, fns, note, ascii_only=False, statuses=None):
        self.name = name
        self.source = source
        self.fns = fns
        self.note = note
        # `fn -> (value, reason)` for the functions whose answer the module
        # DECLARES a status for rather than a value. Empty for every module
        # here but `math`, and empty is not the same as absent: it says "no
        # function of this module has a documented degradation", which is what
        # makes a divergence report trustworthy.
        self.statuses = statuses or {}
        # `re` sets it: this path has no code points, so `\w`, `\d` and `\b`
        # are ASCII-only here whatever the flag says, which `re.mojo` records as
        # a real difference from CPython's Unicode default for a `str` pattern.
        # Comparing a non-ASCII case would measure that difference 26 times
        # instead of once, and it is a property of the VALUE MODEL rather than
        # of the matcher.
        self.ascii_only = ascii_only


def _hostmod(name):
    return os.path.join(HOSTMODS, name + ".mojo")



# `re`'s three-valued answer, lowered in the IMAGE.
#
# `STATUS_UNSUPPORTED` and `STATUS_LIMIT` are the module's own documented
# refusals -- `formal/hostmods/re.mojo` gives them for a pattern using
# lookahead, a lookbehind or a backreference, and for one bigger or deeper than
# it compiles -- and they are NOT "did not match". A table that read them as a
# boolean would report every refused pattern as a WRONG ANSWER, which is both
# wrong and useless: the whole point of a status is that the caller can tell the
# two apart. So the status becomes a third value, the checker counts it as a
# refusal, and a refusal is reported rather than passed over.
#
# The span list is a CALLER-owned literal of 20 words, which is
# `test_re_formal.py`'s spelling for the same reason (a list built inside the
# function lives in that function's frame). Twenty is room for ten groups; a
# pattern with more would answer `STATUS_LIMIT` rather than overflow, and that
# is the module's own guard doing its job.
RE_EMIT = """\
    var st = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    var r = {call}
    var bit = 2
    if r == re.STATUS_NO():
        bit = 0
    if r == re.STATUS_OK():
        bit = 1
    emit_i({k}, bit)"""

# The value the model emits for "this pattern is not one I compile".
REFUSED = 2


def IS_A_MATCH(value):
    """CPython's match object or None, as the 1 or 0 the model's status becomes.

    A named function rather than a lambda in the table above so the table stays
    readable, and named `IS_A_MATCH` rather than `truthy` because `None` is
    falsy and a match object is truthy -- the reduction is "did it match", not
    "is the answer truthy", and those differ for a pattern that matched an
    EMPTY string.
    """
    return 1 if value is not None else 0

MODULES = [
    Spec(
        "posixpath",
        _hostmod("posixpath"),
        {
            "basename":    (S1, "posixpath.basename(%s)", ["p"], None, None),
            "dirname":     (S1, "posixpath.dirname(%s)", ["p"], None, None),
            "normpath":    (S1, "posixpath.normpath(%s)", ["p"], None, None),
            "isabs":       (I1, "posixpath.isabs(%s)", ["p"], None, None),
            "abspath":     (S1, "posixpath.abspath(%s)", ["p"], None, None),
            "realpath":    (S1, "posixpath.realpath(%s)", ["p"], None, None),
            "expanduser":  (S1, "posixpath.expanduser(%s)", ["p"], None, None),
            "relpath":     (S1, "posixpath.relpath(%s, %s)", ["path", "start"], None, None),
            "split":       (T2, "posixpath.split(%s)", ["p"], None, None),
            "splitext":    (T2, "posixpath.splitext(%s)", ["p"], None, None),
            "splitdrive":  (T2, "posixpath.splitdrive(%s)", ["p"], None, None),
            "splitroot":   (S1, "posixpath.splitroot_root(%s)", ["p"], None, None),
        },
        "`splitroot` is PROJECTED: CPython answers a three-element tuple "
        "and the model ships only the root half, which is one word "
        "(`formal/hostmods/posixpath.mojo`'s `splitroot_root`). `commonprefix` "
        "and `join` are variadic in CPython and the model spells them "
        "`(a, b)` / `join_all`, so a literal one-argument call has no spelling "
        "here and is counted rather than guessed at.",
    ),
    Spec(
        "textwrap",
        _hostmod("textwrap"),
        {
            "dedent": (S1, "textwrap.dedent(%s)", ["text"], None, None),
            "indent": (S1, "textwrap.indent(%s, %s)", ["text", "prefix"], None, None),
        },
        "The model's `indent` has no `predicate`, so CPython's "
        "`indent(text, '    ', predicate)` cases are skipped and counted. "
        "`wrap`, `fill` and `shorten` return a LIST and are absent from the "
        "model by the argument in the module's own docstring.",
    ),
    Spec(
        "struct",
        _hostmod("struct"),
        {
            "calcsize": (I1, "struct.calcsize(%s)", ["fmt"], None, None),
        },
        "`calcsize` is the one of the four the model has that a literal "
        "CPython case can be expressed for: `pack`/`unpack_from`/`pack_into` "
        "want a BYTE STRING, which has no representation on this path "
        "(`formal/hostmods/struct.mojo`, 'THE VALUE MODEL').",
    ),
    Spec(
        "shlex",
        _hostmod("shlex"),
        {
            "quote": (S1, "shlex.quote(%s)", ["s"], None, None),
        },
        "`shlex.split` returns a LIST and is absent from the model; "
        "`shlex.shlex` is a generator (`formal/hostmods/shlex.mojo`).",
    ),
    Spec(
        "math",
        _hostmod("math"),
        {
            "isqrt":     (I1, "math.isqrt(%s)", ["n"], None, None),
            "factorial": (I1, "math.factorial(%s)", ["n"], None, None),
            "comb":      (I1, "math.comb(%s, %s)", ["n", "k"], None, None),
            "perm":      (I1, "math.perm(%s, %s)", ["n", "k"], None, None),
            "gcd":       (I1, "math.gcd(%s, %s)", ["a", "b"], None, None),
            "lcm":       (I1, "math.lcm(%s, %s)", ["a", "b"], None, None),
        },
        "`math.gcd`/`lcm`/`comb`/`perm` are variadic or optional in CPython; "
        "the model has the two-argument form and the list form "
        "(`gcdn(vals, n)`), so a call with a different arity is skipped and "
        "counted. `factorial` above 20 is the one DECLARED STATUS here: `20!` "
        "fits a 64-bit word and `21!` needs 66 bits, so the module answers -1 "
        "where CPython answers a 66-bit integer, and a case whose CPython answer "
        "does not fit is compared against that status rather than dropped or "
        "counted as a wrong answer.",
        statuses={"factorial": (-1, "`21!` does not fit a 64-bit word")},
    ),
    Spec(
        "re",
        _hostmod("re"),
        {
            "match":     (I1, "re.match_at(st, 20, %s, %s, 0)",
                          ["pattern", "string"], RE_EMIT, IS_A_MATCH),
            "fullmatch": (I1, "re.fullmatch(st, 20, %s, %s, 0)",
                          ["pattern", "string"], RE_EMIT, IS_A_MATCH),
            "search":    (I1, "re.search(st, 20, %s, %s, 0)",
                          ["pattern", "string"], RE_EMIT, IS_A_MATCH),
            "escape":    (S1, "re.escape(%s)", ["string"], None, None),
        },
        "**The biggest case table in this file, and the one whose selection rule "
        "is the model's own SUBSET rather than its name.** CPython's pattern "
        "language is far larger than `formal/hostmods/re.mojo` compiles, and a "
        "harvest that ignored that would report several hundred WRONG ANSWERS "
        "for patterns the module never claimed. So the third value above does "
        "the selecting: a pattern the module refuses is a documented refusal "
        "(`STATUS_UNSUPPORTED`), counted and printed, and only a pattern the "
        "module COMPILES and then answers differently is a divergence. That is "
        "the same discipline `test_re_formal.py`'s "
        "`test_unsupported_constructs_are_refused` applies, over CPython's own "
        "patterns instead of this repository's. `findall`, `sub` and `split` "
        "answer a LIST, which does not cross a dylib boundary in CPython's "
        "shape, and `compile` has nowhere to live; both are counted.",
        ascii_only=True,
    ),
]

# Every module that models a stdlib module and is NOT in `MODULES`, with the
# measured reason. `--list` prints this; it is the work queue for this file and
# it is a fact about the corpus, not an intention.
NOT_YET = [
    ("stat", "test_stat.py calls `self.statmod.filemode(st_mode)` — a loop "
             "variable, so there is no literal call. `test_formal_stat.py` "
             "already walks all 65,536 modes, which dominates any harvest."),
    ("glob", "`has_magic`/`escape` have no literal call in test_glob.py, and "
             "every `glob(...)` case needs a fixture tree the model reaches "
             "through `os.listdir`; `test_formal_glob.py` owns that corpus."),
    ("hashlib", "test_hashlib.py builds its vectors with `array`/`unhexlify`, "
                "not literals; `test_formal_hashlib.py` owns the digests."),
    ("json", "test_json/ is a package with 18 files and the model has `loads`, "
             "`dumps` and a scanner; needs the byte-string value model worked "
             "out before it can be driven at all."),
    ("ast", "204 literal `parse`/`literal_eval` cases, but the model's surface "
            "is its own and the mapping is unmeasured."),
    ("re", "1768 literal cases, and CPython's pattern language is far larger "
           "than the subset `formal/hostmods/re.mojo` implements; the selection "
           "rule has to be the module's own docstring, which is a project of its "
           "own."),
    ("enum", "two literal cases, both `Enum(...)` over a computed member list."),
    ("sys", "`sys.byteorder` and friends are read as constants, not called."),
    ("os", "test_os.py's cases are filesystem operations, not pure functions."),
    ("time", "test_time.py's literals are `strftime` formats, and `strftime` is "
             "absent from the model (`bugs/FORMAL_time_struct_shaped_answers.md`)."),
    ("platform", "no literal calls; the answer is a property of the machine."),
    ("argparse", "CPython's cases are `parse_args` over argv LISTS and "
                 "SystemExit, and a list cannot cross a dylib boundary."),
    ("collections", "owned by another worker's claim (`module:platform+fnmatch+"
                    "collections-rest`)."),
    ("fnmatch", "owned by another worker's claim."),
    ("subprocess", "owned by another worker's claim "
                   "(`sweep12:hostmods-subprocess`)."),
    ("ctypes", "no test file as a single module (test_ctypes/ is a package)."),
    ("dataclasses", "no test file as a single module (test_dataclasses/ is a "
                    "package), and `@dataclass` has no representation."),
]


def spec_by_name(name):
    for entry in MODULES:
        if entry.name == name:
            return entry
    raise Failure(f"no such group: {name!r}; the groups are "
                  f"{', '.join(m.name for m in MODULES)}")


# ── the generated program ───────────────────────────────────────────────────

PRELUDE = """\
import json
import %(module)s

%(unmask)s
def emit_s(k, v):
    printf("%%lld|s:%%lld:[%%s]@@", k, strlen(v), v)

def emit_i(k, v):
    printf("%%lld|i:%%lld@@", k, v)

def emit_t(k, a, b):
    printf("%%lld|t:0:%%lld:[%%s]@@", k, strlen(a), a)
    printf("%%lld|t:1:%%lld:[%%s]@@", k, strlen(b), b)

"""


def _bytes_of(value):
    """A harvested `str` as the BYTES the model is handed.

    UTF-8, always, and said so in the docstring: this path has no code points,
    so the strongest claim a case with a non-ASCII argument can carry is about
    UTF-8. `surrogateescape` would be the alternative and it is worse — it is
    lossy in a way UTF-8 is not, and a lone surrogate in CPython's corpus would
    become a byte the model cannot be asked about.
    """
    return value.encode("utf-8")


def program(spec, cases):
    """The Mojo source that runs every case in `cases` through the model.

    ONE FUNCTION PER CASE, and that is a measured limit rather than a style
    choice: a case's `unmask` result is a `var` in whatever function holds it,
    and a few hundred of them in one body is the shape
    `test_formal_stat.py`'s `sweep_source` measured a frame budget refusing
    ("a list literal longer than 4095 words dies on a bare AssertionError").
    A case per function moves the pressure off every frame and onto the
    program, which has no such budget.

    The two-element answers are `var`-free assignments, which is this path's
    spelling for destructuring a tuple (`formal/hostmods/posixpath.mojo`'s
    "ONE THING MEASURED" section).

    A STRING argument becomes a `var aN` and the call spells `aN`; an `int`
    argument is a literal in the call. The first version spelled the masked
    literal at BOTH places, which built, ran, and then failed to parse:
    `unmask` is the only thing that turns a masked literal back into bytes, so
    the model was handed the ESCAPED text and answered on `~x2f~x66~x6f~x6f`
    where CPython answers on `/foo`. A conformance table that cannot tell an
    escaped argument from an answer is worse than no table, so the argument is
    bound to a name once and the name is what the call uses.
    """
    lines = [PRELUDE % {"module": spec.name, "unmask": UNMASK}]
    for case in cases:
        if case.oracle[0] != "value":
            continue        # CPython raises; there is nothing to ask the model
        lines.append(f"def case_{case.case_number}() -> int:")
        spellings = []
        for slot, value in enumerate(case.bound):
            if isinstance(value, str):
                lines.append(f"    var a{slot} = unmask("
                             f"{mj(mask(_bytes_of(value)))})")
                spellings.append(f"a{slot}")
            else:
                spellings.append(repr(value))
        call = case.template % tuple(spellings)
        if case.emit is not None:
            # A module whose answer is a STATUS rather than a value. `re` is the
            # one here: its `search`/`match_at`/`fullmatch` return a status word
            # and a caller that cannot tell "did not match" from "this pattern
            # is refused" is reading a boolean out of an error. The snippet
            # lowers the status to a THREE-valued answer and the checker counts
            # the third value as the module's own documented refusal
            # (`formal/hostmods/re.mojo`'s STATUS_UNSUPPORTED), which is a
            # different thing from a wrong answer and is not allowed to pass
            # silently either.
            lines.extend(case.emit.format(k=case.case_number, call=call,
                                          a0=spellings[0] if spellings else "")
                         .split("\n"))
        elif case.kind == S1:
            lines.append(f"    emit_s({case.case_number}, {call})")
        elif case.kind == I1:
            lines.append(f"    emit_i({case.case_number}, {call})")
        else:
            lines.append(f"    t0, t1 = {call}")
            lines.append(f"    emit_t({case.case_number}, t0, t1)")
        lines.append("    return 0")
        lines.append("")
    lines.append("def main() -> int:")
    for case in cases:
        if case.oracle[0] == "value":
            lines.append(f"    case_{case.case_number}()")
    lines.append("    return 0")
    return "\n".join(lines) + "\n"


# ── build and run ───────────────────────────────────────────────────────────

def build(src, name, backend, tmpdir):
    path = os.path.join(tmpdir, f"{name}.mojo")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(src)
    out = os.path.join(tmpdir, f"{name}.{backend}")
    result = run_fire(["build", "--formal", "--no-prove", f"--backend={backend}",
                       "-o", out, path], cwd=HERE)
    check(result.returncode == 0,
          f"build failed on {backend}: "
          f"{(result.stderr or result.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out, backend):
    argv = [out]
    if backend == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", out]        # Rosetta 2
    result = subprocess.run(argv, capture_output=True, timeout=RUN_TIMEOUT,
                            cwd=HERE)
    return result.returncode, result.stdout


def x86_64_available():
    """Whether this host can run an x86-64 image, and why not if it cannot.

    SKIPPED rather than FAILED, with the reason printed: a machine with no
    x86-64 support has not found a model bug, and a red that says "Rosetta is
    missing" is a red nobody acts on. This is `test_formal_stat.py`'s rule.
    """
    if sys.platform != "darwin":
        return False, f"{sys.platform} has no `arch -x86_64`"
    probe = subprocess.run(["arch", "-x86_64", "/usr/bin/true"],
                           capture_output=True)
    if probe.returncode != 0:
        return False, ("`arch -x86_64 /usr/bin/true` exits "
                       f"{probe.returncode}: no Rosetta 2 on this host")
    return True, ""


def records(raw):
    """Decode the records, by COUNT and not by separator.

    A path can contain `@@`, `]` and `@`, so a record is `[<k>|<kind>:...]` and
    the parser reads exactly as many bytes as the record claims and then
    insists on the `]` and the terminator. A mismatch there is a transport
    failure and is reported as one — comparing the next record against this
    case's expectation would report a difference that is not one.
    """
    out = []
    pos = 0
    end = len(raw)
    while pos < end:
        bar = raw.find(b"|", pos)
        if bar < 0:
            raise Failure(f"{raw[pos:pos + 40]!r}: record with no bar")
        number = int(raw[pos:bar])
        cursor = bar + 1
        colon = raw.find(b":", cursor)
        kind = raw[cursor:colon]
        cursor = colon + 1
        if kind == b"i":
            terminator = raw.find(b"@@", cursor)
            value = int(raw[cursor:terminator])
            pos = terminator + 2
            out.append((number, "i", None, value))
            continue
        if kind == b"t":
            colon = raw.find(b":", cursor)
            part = int(raw[cursor:colon])
            cursor = colon + 1
        else:
            part = 0
        length = int(raw[cursor:raw.find(b":[", cursor)])
        cursor = raw.find(b":[", cursor) + 2
        value = raw[cursor:cursor + length]
        cursor += length
        terminator = b"]" + REC.encode()
        if raw[cursor:cursor + len(terminator)] != terminator:
            raise Failure(f"case {number}: answer of {length} bytes is not "
                          f"followed by `{terminator!r}`; the value was "
                          f"truncated or grew in transport, which is a "
                          f"different bug from a wrong answer")
        cursor += len(terminator)
        out.append((number, kind.decode(), part, value))
        pos = cursor
    return out


# ── the comparison ──────────────────────────────────────────────────────────

WORD_MIN = -(2 ** 63)
WORD_MAX = 2 ** 63 - 1


def _fits_a_word(value):
    """Whether `value` is an integer this path can hold at all.

    A formal value is ONE 64-bit word (`formal/model.py`), so an integer
    CPython can compute and this path cannot is a question with no answer here
    rather than a wrong one -- which is the difference a conformance table has
    to keep, because a module that answers -1 for it is being HONEST and a
    table that reads that as a wrong answer sends the next person looking for a
    bug that is not there.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return True
    return WORD_MIN <= value <= WORD_MAX


def expected_parts(case):
    """CPython's answer as the LIST OF PARTS the model's records are read as.

    Normalising to a list is what makes the comparison uniform: an `s` answer is
    a one-element list, an `i` answer is a one-element list holding the integer,
    and a `t` answer is the tuple CPython returned, each element encoded. The
    comparison then walks the model's records and this list in step, so a record
    count that does not line up is a divergence rather than a wrong element read
    from the wrong case.

    `None` for a case CPython raises, which has no parts because the model has
    no exception surface to answer with.
    """
    if case.oracle[0] == "raises":
        return None
    value = case.want if case.want is not None else case.oracle[1]
    if case.status is not None and not _fits_a_word(value):
        # The model DECLARES a status for this function -- `math.factorial`
        # answers -1 above 20 because `21!` needs 66 bits and this path has 64
        # -- and CPython's answer for the same input does not fit a word. So
        # there is no value to compare: what is being compared is the module's
        # documented degradation against the fact that the question has an
        # answer CPython can give and this path cannot. Counting it as a
        # divergence would report a documented limit as a bug; calling it a
        # pass would report a limit as conformance.
        return [case.status]
    if case.kind == I1:
        return [value]
    if case.kind == S1:
        return [_bytes_of(value)]
    return [part if isinstance(part, int) else _bytes_of(part)
            for part in value]


def model_parts(case, got):
    """The model's records for one case, in the same shape as `expected_parts`."""
    if case.kind == I1:
        return [got.get(0)]
    if case.kind == S1:
        return [got.get(0)]
    return [got.get(0), got.get(1)]


def run_group(spec, verbose, backends):
    """Build, run, and compare every case in one module's table."""
    cases, stats, missing = build_cases(spec)
    if missing:
        return False, "; ".join(missing)
    check(cases, f"{spec.name}: CPython's own test suite yielded no case "
                 f"this model's surface can express, and an empty table is not "
                 f"a pass — {stats}")
    src = program(spec, cases)
    per_backend = {}
    for backend in backends:
        image = build(src, f"conf_{spec.name}", backend, TEMP)
        status, raw = run(image, backend)
        check(status == 0,
              f"[{backend}] image exited {status}: the program emits one "
              f"record per case and an image that exits non-zero has not "
              f"answered any of them")
        recs = records(raw)
        # Only the cases the PROGRAM runs, which is the cases CPython answers:
        # a case CPython raises is reported and not compiled, so counting it
        # here would ask for a record the generated source never emits.
        emitted = sum(2 if case.kind == T2 else 1 for case in cases
                      if case.oracle[0] == "value")
        check(len(recs) == emitted,
              f"[{backend}] the image emitted {len(recs)} records for "
              f"{len(cases)} cases, which emit {emitted} between them — a "
              f"program that printed fewer answers than it computed is not a "
              f"program whose answers can be compared")
        per_backend[backend] = recs

    by_backend = {}
    for backend, recs in per_backend.items():
        answers = {}
        for number, kind, part, value in recs:
            answers.setdefault(number, {})[part if part else 0] = value
        by_backend[backend] = answers

    # cross-backend first: two architectures of ONE language implementation may
    # not disagree, and that is a class of bug no oracle comparison can see —
    # both would have to be wrong about the same input, in the same direction,
    # for CPython's answer to match either of them.
    #
    # The message is BUILT only when there is something wrong, because `check`
    # takes it eagerly and `divergent[0]` on an empty list is an IndexError in
    # the one place where there is nothing to report. That is not a style
    # preference; it is the difference between a green run and a crash.
    if len(by_backend) == 2:
        arm, other = by_backend["arm64"], by_backend["x86_64"]
        divergent = [n for n in sorted(arm) if arm.get(n) != other.get(n)]
        if divergent:
            first = divergent[0]
            raise Failure(
                f"the two backends disagree on {len(divergent)} of "
                f"{len(arm)} cases, and no oracle can see that class of bug: "
                f"first is case {first}, arm64 {arm.get(first)} vs x86-64 "
                f"{other.get(first)}")

    failures = []
    refused = []
    for case in cases:
        want = expected_parts(case)
        if want is None:
            continue
        for backend, answers in by_backend.items():
            if case.case_number not in answers:
                failures.append(f"[{backend}] case {case.case_number} "
                                f"({case.fn}): the image emitted NO record")
                continue
            got = model_parts(case, answers[case.case_number])
            if len(want) == 1 and got[0] == REFUSED:
                # The model's own documented refusal for a pattern it does not
                # compile. Counted and printed, and NOT a pass either: a table
                # that could not say how many of CPython's patterns this
                # engine declines would be reporting a smaller number than it
                # measured.
                refused.append((backend, case))
                continue
            for part, (g, w) in enumerate(zip(got, want)):
                if g != w:
                    failures.append(
                        f"[{backend}] {_describe(case.fn, case.args, case.keywords)}"
                        + (f" element {part}" if len(want) > 1 else "")
                        + f" -> model {g!r}, CPython {w!r} "
                        f"({case.file}:{case.line})")
                    break
            else:
                if len(got) != len(want):
                    failures.append(
                        f"[{backend}] case {case.case_number} ({case.fn}): the "
                        f"model answered {len(got)} parts where CPython answers "
                        f"{len(want)} ({case.file}:{case.line})")

    counted = {k: v for k, v in stats.items() if v}
    if verbose:
        fidelity = {}
        for case in cases:
            fidelity[case.fidelity] = fidelity.get(case.fidelity, 0) + 1
        print(f"    {spec.name}: {len(cases)} cases from CPython's own "
              f"{spec.name} tests, {fidelity}")
        if counted:
            print(f"      not expressible here: {counted}")
    if refused:
        # The distinct PATTERNS, not the cases: twelve refused cases over one
        # construct is one limit, and a reader wants to know which construct.
        # Counted ONCE per case, not once per backend: `refused` has an entry
        # per (backend, case) and the two backends refuse the same patterns, so
        # counting the list would double the headline on a two-backend run and
        # make the number a function of the backend count.
        cases_refused = {case.case_number for _b, case in refused}
        distinct = sorted({(case.fn, case.args[0]) for _b, case in refused})
        print(f"    {spec.name}: {len(cases_refused)} of CPython's own cases "
              f"are a pattern this engine REFUSES (its own STATUS_UNSUPPORTED / "
              f"STATUS_LIMIT), which is a documented limit and not an "
              f"agreement. {len(distinct)} distinct (function, PATTERN) pairs:")
        for fn, pattern in distinct[:14]:
            print(f"      refused: {fn}({pattern!r})")
        if len(distinct) > 14:
            print(f"      ... and {len(distinct) - 14} more")
    check(not failures,
          f"{spec.name}: {len(failures)} divergences from CPython on "
          f"{len(cases)} of its own cases; first six:\n      "
          + "\n      ".join(failures[:6]))
    return True, (f"{spec.name}: {len(cases)} of CPython's own cases agree "
                  f"on {', '.join(backends)}"
                  + (f" ({counted} not expressible)" if counted else ""))


# ── the case table, printed ─────────────────────────────────────────────────

def print_table(name, limit=None):
    """The generated case table for one module: CPython's own answer per case.

    This is the file's deliverable in the form a reader can check, and it is
    PRINTED rather than stored because nothing here is stored: every answer is
    a call into the interpreter reading this line, and a stored copy would be
    a transcription of the oracle — the thing this file exists to avoid.
    """
    spec = spec_by_name(name)
    cases, stats, missing = build_cases(spec)
    if missing:
        print(f"{name}: {missing}")
        return
    print(f"# {name}: {len(cases)} cases, generated from CPython's own "
          f"{', '.join(os.path.relpath(f, CPY_TEST_DIR) for f in cpython_test_files(name))}")
    print(f"# {spec.note}")
    for reason, count in stats.items():
        if count:
            print(f"# not expressible: {reason}: {count}")
    shown = cases if limit is None else cases[:limit]
    for case in shown:
        oracle = case.oracle
        if oracle[0] == "raises":
            answer = f"raises {oracle[1]}: {oracle[2]}"
        else:
            answer = repr(oracle[1])
        tag = "utf8" if case.unicode else "ascii"
        print(f"{case.case_number:5d} {case.file}:{case.line:<5d} "
              f"{_describe(case.fn, case.args, case.keywords)} -> {answer}"
              f"   [{case.fidelity}, {tag}]")
    if limit is not None and len(cases) > limit:
        print(f"# ... {len(cases) - limit} more")


def list_modules():
    """The registry and the queue, with the counts each module actually has."""
    print(f"CPython's own regression tests: {CPY_TEST_DIR} "
          f"(python {sys.version.split()[0]})")
    print()
    for spec in MODULES:
        files = cpython_test_files(spec.name)
        cases, stats, missing = build_cases(spec)
        if missing:
            print(f"{spec.name:12s} NO CPython test suite")
            continue
        by_fn = {}
        for case in cases:
            by_fn[case.fn] = by_fn.get(case.fn, 0) + 1
        counted = {k: v for k, v in stats.items() if v}
        print(f"{spec.name:12s} {len(cases):4d} cases from "
              f"{len(files)} file(s), {len(by_fn)} function(s): "
              + ", ".join(f"{k}={v}" for k, v in sorted(by_fn.items())))
        for reason, count in sorted(counted.items()):
            print(f"             {count:4d} {reason}")
    print()
    print("NOT YET, with the measured reason:")
    for name, reason in NOT_YET:
        print(f"  {name:12s} {reason}")


def main():
    global TEMP
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("groups", nargs="*",
                        help="module groups; default is all of them")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--list", action="store_true",
                        help="print the registry and the queue, build nothing")
    parser.add_argument("--cases", metavar="GROUP",
                        help="print one module's generated case table")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --cases, show only the first N")
    parser.add_argument("--dump-cases", nargs=2, metavar=("GROUP", "FILE"),
                        help="write one module's case table to FILE")
    parser.add_argument("--backend", action="append", choices=BACKENDS,
                        help="restrict to one backend (default is both)")
    args = parser.parse_args()

    if args.list:
        list_modules()
        return 0

    if args.cases:
        print_table(args.cases, args.limit)
        return 0

    if args.dump_cases:
        name, path = args.dump_cases
        TEMP = tempfile.mkdtemp(prefix="formal_conf_")
        try:
            cases, _, missing = build_cases(spec_by_name(name))
            if missing:
                raise Failure(missing)
            with open(path, "w", encoding="utf-8") as handle:
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    print_table(name)
                handle.write(buffer.getvalue())
        finally:
            shutil.rmtree(TEMP, ignore_errors=True)
        print(f"{name}: {len(cases)} cases written to {path}")
        return 0

    backends = tuple(args.backend) if args.backend else BACKENDS
    if "x86_64" in backends:
        ok, why = x86_64_available()
        if not ok:
            print(f"SKIP x86-64: {why}")
            backends = tuple(b for b in backends if b != "x86_64")
    names = args.groups or [spec.name for spec in MODULES]
    for name in names:
        spec = spec_by_name(name)
        TEMP = tempfile.mkdtemp(prefix="formal_conf_")
        try:
            ok, message = run_group(spec, args.verbose, backends)
        except (Failure, TestFailure) as exc:
            print(f"FAILED  {name}: {exc}")
            continue
        finally:
            shutil.rmtree(TEMP, ignore_errors=True)
        print(f"{'ok  ' if ok else 'FAIL'}  {message}")


if __name__ == "__main__":
    sys.exit(main())