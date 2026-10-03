#!/usr/bin/env python3
"""The proof-breadth census tool is a MEASUREMENT, so the measurement is pinned.

    python3 test_formal_proof_breadth.py [-v]

`tools/formal_proof_breadth.py` is the instrument behind
`bugs/FORMAL_proof_coverage_census_2026-10-03.md`: it takes 60 functions from
this repository's own `*.py` (plus `formal/examples`) and puts each through
`formal.build.compile_formal(prove=True, …)` on both architectures, then checks
the proof Lean actually accepts. Its numbers are quoted in a bug doc and will be
re-quoted, so three things about it have to hold or the numbers are not
comparable across runs:

  * **the workload is a function of the tree, not of the clock.** Two calls must
    produce the same 60 identifiers in the same order, or "before" and "after"
    are two different samples and the delta between them means nothing;
  * **every emitted program is a whole, closed module.** The synthesised `main`
    calls the function under test with the startup stub's integer, and the
    module carries the definitions that call needs. An item that read a name it
    does not define would be refused for a reason that has nothing to do with the
    proof layer — the refusal the census exists to avoid;
  * **the classifier says what it means.** Two programs with known verdicts, one
    per class that is a decision rather than a pass, checked without Lean so the
    test costs a codegen run and not a proof.

None of these runs Lean: the point is that the instrument is cheap and always
available, so it can be checked on every change to itself. The census's own
Lean-dependent numbers are its ledger's business
(`$TMPDIR/formal_proof_breadth.ledger.jsonl`).
"""
import ast
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_proof_breadth as B          # noqa: E402


class TestWorkload(unittest.TestCase):
    """The 60 items, and that they are the same 60 every time."""

    def test_the_workload_is_a_function_of_the_tree(self):
        first = [w.ident for w in B.build_workload()]
        second = [w.ident for w in B.build_workload()]
        self.assertEqual(first, second,
                         "two calls in one process disagree; the sample is "
                         "not reproducible and no two runs are comparable")
        self.assertEqual(len(first), len(set(first)),
                         "the same function is in the sample twice")

    def test_it_has_the_documented_shape(self):
        items = B.build_workload()
        self.assertEqual(len(items), B.EXAMPLE_STRIDE_TARGET
                         + B.REPO_FUNCTION_TARGET)
        origins = [w.origin for w in items]
        self.assertEqual(origins.count("example"), B.EXAMPLE_STRIDE_TARGET)
        self.assertEqual(origins.count("repo"), B.REPO_FUNCTION_TARGET)

    def test_the_repo_half_spreads_over_files(self):
        """Breadth is measured in FILES, and it is worth saying in which
        DIRECTORIES the sample lands, because it does not spread evenly: the
        round-robin walks files in sorted path order, so the alphabetically
        early directories (`formal/`, `mojo/`) contribute more of the 45 than
        their share of the tree. That is a bias in the sample, stated here
        rather than left for a reader to infer from the identifier list — and it
        is not fixed by changing the rule, because a census's sample must stay
        the same sample across runs for two runs to be comparable.

        **A floor rather than the exact 45 this used to assert**, because the
        eligibility filter now excludes a candidate whose container parameter the
        synthesised `main` cannot supply (see `_integer_unusable_in`), and that
        removed the last eligible candidate from four files: the round-robin
        then takes a second and third function from files it has already
        reached, and the sample is 45 functions over 41 files. What this
        protects is SPREAD — a census that collapsed onto a handful of files
        would be a census of those files — and the exact composition is
        reproducible from the tool, which the first test already pins.
        """
        files = {w.ident.split(":")[0] for w in B.build_workload()
                 if w.origin == "repo"}
        floor = (B.REPO_FUNCTION_TARGET * 9) // 10
        self.assertGreaterEqual(
            len(files), floor,
            f"the repo half must spread over at least {floor} files, or the "
            f"sample is a census of whichever file sorts first: {len(files)}")
        dirs = {os.path.dirname(f) for f in files}
        self.assertGreaterEqual(len(dirs), 4,
                                f"the repo half reached {sorted(dirs)}")

    def test_a_container_parameter_the_stub_cannot_supply_is_not_a_candidate(self):
        """The eligibility rule that keeps the harness out of the verdicts.

        `_entry_call` fills every parameter with the startup stub's integer, so
        a function that USES a parameter as a container gets a program the
        source does not have — and the census then counted the refusal that
        follows as a family of code-generator limits. `mojo/middle/exprtypes.py`'s
        `_trailing_default_at(dflts, …)` is the measured case: `len(dflts)` on an
        integer is "len() of a value classified as 'int'", and §3 of the census
        reported three of those as a fact about this backend.

        Each shape is a refusal the tool itself would have reported, so the test
        asks the WORKLOAD question rather than the verdict one: ineligible.
        """
        ineligible = [
            ("len", "def f(vals):\n    return len(vals) + 1\n"),
            ("subscript", "def f(vals):\n    return vals[0]\n"),
            ("iteration", "def f(vals):\n    t = 0\n"
             "    for v in vals:\n        t = t + v\n    return t\n"),
            ("a method call", "def f(text):\n    return text.strip()\n"),
            ("a sequence builtin", "def f(vals):\n    return sorted(vals)[0]\n"),
        ]
        for what, source in ineligible:
            stmts = ast.parse(source)
            fn = stmts.body[0]
            self.assertIsNotNone(
                B._integer_unusable_in(fn),
                f"a parameter used as {what} must be reported, or the census "
                f"fabricates its own call site and calls the result a verdict "
                f"about the backend")
        # …and the two directions, because a rule that removed every candidate
        # would measure nothing. An ARITHMETIC parameter is untouched: the
        # stub's integer is the value the source passes.
        for what, source in (
                ("arithmetic", "def f(n):\n    return n * 3 + 1\n"),
                ("passed on", "def f(n, g):\n    return g(n) + 1\n"),
                ("a local", "def f(n):\n    m = n + 1\n    return m * 2\n")):
            stmts = ast.parse(source)
            self.assertIsNone(B._integer_unusable_in(stmts.body[0]),
                              f"a parameter used as {what} must stay eligible")

    def test_every_emitted_program_is_closed_and_parses(self):
        """The property that keeps the census about the proof layer.

        A name the module does not define is refused by the code generator with
        a message about THAT, which is one of the 38 rows the census reports as
        `codegen-refused` — a fact about the target rather than about proofs.
        So: it parses, it has the entry `main` needs, and every name it reads is
        defined in it."""
        builtins = set(dir(__builtins__)) if not isinstance(
            __builtins__, dict) else set(__builtins__)
        # Only the EXTRACTED half: `formal/examples/*.mojo` is the Mojo dialect
        # (`@spec(count_spec; …)`), which CPython's `ast` cannot parse at all,
        # and those files are used verbatim — their validity is
        # `test_formal.py`'s business, and this tool does not touch them.
        for w in B.build_workload():
            if w.origin != "repo":
                continue
            with self.subTest(item=w.ident):
                try:
                    tree = ast.parse(w.source)
                except SyntaxError as e:
                    self.fail(f"{w.ident}: the emitted module does not parse: "
                              f"{e}")
                defined = {n.name for n in tree.body
                           if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
                for st in tree.body:
                    if isinstance(st, ast.Assign):
                        defined |= {t.id for t in st.targets
                                    if isinstance(t, ast.Name)}
                self.assertIn("main", defined,
                              f"{w.ident}: no entry, so the startup stub has "
                              f"nothing to call and the build is refused for "
                              f"the wrong reason")

                # Every name BOUND anywhere in the module — parameters, locals,
                # loop and comprehension targets, `with`/`except` aliases,
                # imports — against every name READ anywhere. Coarse on
                # purpose: a local of one function satisfying a read in another
                # can only make this check quieter, and what it must never do
                # is cry wolf. The property worth having is that the emitted
                # module is CLOSED: it defines `main` and everything its bodies
                # mention, so a refusal about it is about the PROOF LAYER and
                # not about a name the sample forgot to carry.
                bound, read = set(), set()

                class Walker(ast.NodeVisitor):
                    def visit_Name(self, node):
                        (bound if not isinstance(node.ctx, ast.Load)
                         else read).add(node.id)
                        self.generic_visit(node)

                    def visit_arg(self, node):
                        bound.add(node.arg)
                        self.generic_visit(node)

                    def visit_alias(self, node):
                        bound.add((node.asname or node.name).split(".")[0])
                        self.generic_visit(node)

                    def visit_ExceptHandler(self, node):
                        if node.name:
                            bound.add(node.name)
                        self.generic_visit(node)

                    def visit_FunctionDef(self, node):
                        bound.add(node.name)
                        self.generic_visit(node)

                    visit_AsyncFunctionDef = visit_FunctionDef

                    def visit_ClassDef(self, node):
                        bound.add(node.name)
                        self.generic_visit(node)

                    def visit_Lambda(self, node):
                        self.generic_visit(node)

                Walker().visit(tree)
                bound |= defined
                free = read - bound - set(B.BUILTIN_NAMES) - builtins
                self.assertEqual(free, set(),
                                 f"{w.ident}: reads names the module does not "
                                 f"define: {sorted(free)}")


class TestClassifier(unittest.TestCase):
    """One program per class that is a DECISION rather than a pass.

    All three refuse at GENERATION time, so none of them runs Lean, and each one
    is a class the census's own table depends on."""

    def _class_of(self, source, arch="arm64"):
        tmp = tempfile.mkdtemp(prefix="pbc-")
        try:
            item = B.Workload(ident="t", origin="repo", source=source,
                              detail="", weight=0)
            return B.run_item(item, arch, timeout=60, workdir=tmp).cls
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_call_to_a_second_function_is_a_proof_refusal(self):
        """The largest single cause in the census: 4 of 22 reachable items.

        Both backends refuse it, for different reasons and from the same shared
        check — arm64's machine half first (interprocedural CFG walking), and
        x86-64's bridge, which would otherwise state an `eval_eq_mojo` that is
        false."""
        src = ("def _m2(a, b):\n"
               "    if a > b:\n"
               "        return a\n"
               "    return b\n"
               "def main(x):\n"
               "    return _m2(x, x)\n")
        self.assertEqual(self._class_of(src), "proof-refused")
        self.assertEqual(self._class_of(src, arch="x86_64"), "admitted",
                         "x86-64 emits the rest of the file and counts its "
                         "two designed holes; the point is that it no longer "
                         "emits a FALSE theorem")

    def test_a_list_literal_is_a_proof_refusal_not_a_crash(self):
        """`formal/arm64_proof_gen.py::_no_value_model` refusing by name.

        The class matters because it is what separates "the model has no domain
        for this construct" (4% of the corpus, a real limit) from "the generator
        crashed" (a bug)."""
        src = ("def f(n):\n"
               "    xs = [1, 2, 3]\n"
               "    return xs[0] + n\n"
               "def main(x):\n"
               "    return f(x)\n")
        self.assertEqual(self._class_of(src), "proof-refused")

    def test_a_codegen_refusal_is_not_counted_against_the_proof_layer(self):
        """A string comparison the code generator refuses.

        The census's `codegen-refused` class is the reason the proof-layer
        denominator is 22 and not 60, and it has to stay a different class from
        everything the proof layer says."""
        src = ("def f(a, b):\n"
               "    if a == 'x':\n"
               "        return b\n"
               "    return a\n"
               "def main(x):\n"
               "    return f(x, x)\n")
        self.assertEqual(self._class_of(src), "codegen-refused")


if __name__ == "__main__":
    unittest.main(verbosity=2)