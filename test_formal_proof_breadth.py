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

    def test_a_second_census_is_a_different_sample(self):
        """`--round-offset` / `--example-offset` / `--exclude-seen` / `--admit-returns`.

        **The workload is a function of the tree, which is what makes two runs
        comparable — and which is also what makes a SECOND census impossible
        without asking for a different sample.** Round 0 is each file's largest
        eligible function; the first census took 45 of them over 41 files, and
        the whole eligible pool is 76 functions, so a second spread of ~80 that
        shares none of the first cannot be reached by continuing the same
        round-robin. Three things make it reachable and each is checkable
        without a build:

          * the offsets move the SELECTION, never the defaults, so round 0 still
            means what round 0's committed ledger says it means;
          * `--exclude-seen` reads an earlier census's committed ledger — keyed by
            `path:name`, because a `path:lineno:name` ident forgets a function
            the moment anything above it changes (10 of this tree's own 45 first-
            census idents still exist) — and it excludes round 0's CURRENT sample
            as well, because that is what a reader compares against;
          * `--admit-returns` widens the POOL, and the measurement that says why
            it may is in `RETURN_ANNOTATIONS` (a `-> bool`/`-> str`/`-> None`
            return annotation is not a call-site mismatch — `main` returns the
            value and nothing asserts a type on it).
        """
        first = {B.function_key(w.ident) for w in B.build_workload()}
        # The defaults are untouched: this is the first census's sample.
        self.assertEqual(
            {B.function_key(w.ident) for w in B.build_workload(
                round_offset=0, example_offset=0, admit_returns=False,
                exclude=())},
            first,
            "the offsets changed the default sample, so every number taken "
            "before this option existed now describes a different 60 functions")

        # The second census: the same rule, a new sample, drawn off the first
        # census's own committed ledger.
        ledger = os.path.join(HERE, "bugs", "sweeps",
                              "proof_breadth_2026-10-03.jsonl")
        self.assertTrue(os.path.isfile(ledger),
                        f"the first census's ledger is gone: {ledger}")
        seen = B.ledger_idents([ledger])
        self.assertTrue(seen,
                        "the committed ledger carries no identifiers at all")
        second = B.build_workload(repo=60, examples=45, example_offset=1,
                                  admit_returns=True, exclude=seen)
        second_ids = {B.function_key(w.ident) for w in second}
        self.assertEqual(second_ids & seen, set(),
                         "the second census re-measures a function the first "
                         "census's ledger already recorded")
        self.assertEqual(second_ids & first, set(),
                         "the second census re-measures what `--list` prints "
                         "today, which is the comparison a reader makes")
        self.assertGreaterEqual(len(second), 75,
                                f"the second census is {len(second)} items; "
                                "the point of the widening is a ~80-function "
                                "spread")
        # …and it SPREADS, which is the property the first census's own
        # `test_the_repo_half_spreads_over_files` protects: a sample of one
        # file's second candidates would be a census of that file. The floor is
        # 30 files and not the 40 round 0 reaches, because excluding round 0
        # costs the widest files their FIRST candidate — `formal/model.py` alone
        # is 16 of them — and that cost is the price of the disjointness.
        files = {w.ident.split(":")[0] for w in second if w.origin == "repo"}
        self.assertGreaterEqual(len(files), 30,
                                f"the second census reached {len(files)} files")
        # …and every item is still a CLOSED module, which is the property the
        # census's verdicts rest on (a refusal about a name the sample forgot to
        # carry is not a fact about the proof layer).
        for w in second:
            if w.origin != "repo":
                continue
            with self.subTest(item=w.ident):
                try:
                    ast.parse(w.source)
                except SyntaxError as e:
                    self.fail(f"{w.ident}: the widened sample emits a module "
                              f"that does not parse: {e}")

    def test_an_ident_is_not_a_stable_key_and_the_line_number_is_why(self):
        """`function_key`: `path:lineno:name` forgets a function on any edit
        above it, which is measured on this tree's own first census — 10 of its
        45 repo idents still exist today, 16 more exist at a moved line, and 22
        of its 41 files are no longer sampled at all. A second census keyed on
        the ident would share 38 of its 78 items with `--list`; keyed on
        `path:name` it shares none."""
        self.assertEqual(B.function_key("a/b.py:1036:_short_repr"),
                         "a/b.py:_short_repr")
        self.assertEqual(B.function_key("a/b.py:1040:_short_repr"),
                         B.function_key("a/b.py:1036:_short_repr"))
        self.assertEqual(B.function_key("a/b.py:10:f"), "a/b.py:f")
        # An `examples/*.mojo` item has no line number and is its own key.
        self.assertEqual(B.function_key("examples/pair.mojo"),
                         "examples/pair.mojo")

    def test_a_ledger_that_is_not_one_is_refused(self):
        """`ledger_idents` reads a previous census's ledger, so it must not
        guess: a file of anything else would silently exclude nothing and the
        second census would be the first one wearing a new date."""
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "not-a-ledger.jsonl")
            with open(bad, "w") as f:
                f.write('{"not": "a verdict"}\n')
            with self.assertRaises(SystemExit):
                B.ledger_idents([bad])
            # A header line and a blank line are the tool's own, and are skipped;
            # the two architectures of one item are one key, not two.
            good = os.path.join(d, "good.jsonl")
            with open(good, "w") as f:
                f.write("# formal_proof_breadth 2026-10-03 timeout=400.0\n"
                        '{"ident": "a.py:1:f", "arch": "arm64", "cls": "pass"}\n'
                        '\n'
                        '{"ident": "a.py:1:f", "arch": "x86_64", '
                        '"cls": "pass"}\n'
                        '{"ident": "examples/p.mojo", "arch": "arm64", '
                        '"cls": "pass"}\n')
            self.assertEqual(B.ledger_idents([good]),
                             {"a.py:f", "examples/p.mojo"})

    def test_a_return_annotation_is_not_a_call_site_mismatch(self):
        """The one eligibility rule `--admit-returns` relaxes, and why.

        The rule it relaxes is stated in terms of a CALL SITE: "the synthesised
        `main` calls the function with the startup stub's integer, and a
        mismatch there would make the census report a CALL-SITE refusal as if it
        were a statement about the function". That is true of a PARAMETER
        (`_entry_call` passes the stub's integer to every one of them, so a
        `str` parameter is a value the source never passes) and false of a
        RETURN: `main` returns whatever the function returns and nothing in the
        harness asserts a type on that result.

        So each fixture asks whether its annotation is what excludes it — and the
        PARAMETER annotation must stay excluded either way, because that one
        really can mismatch the stub.
        """
        def _eligible(source, **kw):
            return B._eligible(ast.parse(source).body[0], {},
                               source.splitlines(), **kw)

        plain = "def f(n):\n    if n > 3:\n        return True\n    return False\n"
        self.assertIsNotNone(_eligible(plain)[0],
                             "the unannotated fixture must be eligible, or "
                             "this test is measuring the wrong thing")
        annotated = ("def f(n: int) -> bool:\n"
                     "    if n > 3:\n"
                     "        return True\n"
                     "    return False\n")
        self.assertIsNone(_eligible(annotated)[0],
                          "a RETURN annotation must not exclude a candidate")
        emitted, deps = _eligible(annotated, admit_returns=True)
        self.assertIsNotNone(emitted,
                             "admit_returns must admit a return-annotated "
                             f"candidate: {deps}")
        self.assertIn("-> bool", emitted,
                      "the emitted module carries the annotation verbatim, not "
                      "a paraphrase of it")
        # The asymmetry: a PARAMETER annotated `str` is still out, widened or
        # not, because the stub's integer is not the value the source passes.
        for source in ("def f(text: str) -> bool:\n"
                       "    return True\n",
                       "def f(text: str):\n"
                       "    return 1\n"):
            self.assertIsNone(_eligible(source, admit_returns=True)[0],
                              "a str PARAMETER must stay ineligible: the "
                              "harness has no str to hand it")

    def test_a_census_that_does_not_ask_lean_says_so(self):
        """`--no-check` is the mode a worker may run who may not start Lean.

        It reports `proof-emitted`, which is not a verdict, and the class is
        printed with that said — a census that reported a proof nobody checked
        as a row without a name would be counting a hope."""
        self.assertIn("proof-emitted", B.CLASS_ORDER)
        self.assertIn("proof-emitted", B.NOT_A_VERDICT)
        src = "def main(x):\n    y = x * 3\n    print(y)\n    return y\n"
        item = B.Workload(ident="t", origin="repo", source=src, detail="",
                          weight=0)
        tmp = tempfile.mkdtemp(prefix="pbc-nocheck-")
        try:
            v = B.run_item(item, "arm64", timeout=60, workdir=tmp,
                           check=False)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(v.cls, "proof-emitted")
        self.assertGreater(v.proof_lines, 0,
                           "a proof was written; that is what the class says")
        self.assertIsNone(v.n_sorries,
                          "no Lean ran, so no hole count can be reported — a "
                          "number here would be invented")
        # …and it is not counted as a proof in the report's own tally.
        text = B.report([v], ["arm64"])
        self.assertIn("proof-emitted", text)
        self.assertIn("not a verdict", text)
        self.assertIn("proved at all       0 (0.0%)", text)

    def test_the_report_says_when_the_two_architectures_mean_different_things(self):
        """A class is not a subject, and the report has to say so.

        Measured on this tree's round-2 census: one item's arm64 refusal named a
        module constant and its x86-64 refusal named a string operator two lines
        later, and the census's class column said `codegen-refused` for both. A
        cross-architecture column is only worth reading if its cells are about
        the same thing, so the report names the items where they are not —
        `bugs/FORMAL_the_two_backends_refuse_different_constructs_in_the_same_
        function.md` is the finding and this is the instrument for it.

        The other half of the rule matters as much: an arm64 refusal beside an
        x86-64 `proof-emitted` is that generator's documented degradation, and
        listing it as a disagreement would be crying wolf on 29 of 78 items.
        """
        V = B.Verdict
        results = [
            V("x.py:1:f", "arm64", "codegen-refused",
              "'A' has no home: this module declares no module-level name",
              "build", 0.1, None, 0, False),
            V("x.py:1:f", "x86_64", "codegen-refused",
              "'%' is refused when the left operand is a string", "build", 0.1,
              None, 0, False),
            V("y.py:2:g", "arm64", "codegen-refused", "the same words",
              "build", 0.1, None, 0, False),
            V("y.py:2:g", "x86_64", "codegen-refused", "the same words",
              "build", 0.1, None, 0, False),
            V("z.py:3:h", "arm64", "proof-refused",
              "model: a ListExpr has no value in the semantic model", "generate",
              0.1, None, 0, False),
            V("z.py:3:h", "x86_64", "proof-emitted", "phase A only: 100 lines",
              "generate", 0.1, None, 100, False),
        ]
        text = B.report(results, ["arm64", "x86_64"])
        self.assertIn("DIFFERENT CONSTRUCTS", text)
        self.assertIn("x.py:1:f", text)
        self.assertIn("'A' has no home", text)
        self.assertIn("'%' is refused", text)
        self.assertNotIn("y.py:2:g\n", text.split("DIFFERENT CONSTRUCTS")[1],
                         "an item both machines refused identically is not a "
                         "disagreement")
        self.assertNotIn("z.py:3:h", text.split("DIFFERENT CONSTRUCTS")[1],
                         "x86-64 emitting a proof where arm64 refuses is the "
                         "documented degradation, not a disagreement")
        # Two `proof-emitted` rows differ in their detail because the two
        # generators wrote proofs of different LENGTHS, which is a fact about
        # the generators and not a disagreement about a construct either.
        both = [V("w.py:4:k", "arm64", "proof-emitted",
                  "phase A only: 5348 lines of proof written", "generate", 0.1,
                  None, 5348, False),
                V("w.py:4:k", "x86_64", "proof-emitted",
                  "phase A only: 524 lines of proof written", "generate", 0.1,
                  None, 524, False)]
        self.assertIn("architectures agree on the refusal",
                      B.report(both, ["arm64", "x86_64"]),
                      "a proof-length difference is not a construct "
                      "disagreement and listing it would cry wolf on 46 of 78")
        # …and with nothing to report it says so rather than printing a header.
        same = [v for v in results if v.ident == "y.py:2:g"]
        self.assertIn("architectures agree on the refusal",
                      B.report(same, ["arm64", "x86_64"]))

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


class TestTheBuiltinAllowListIsAMeasurement(unittest.TestCase):
    """`BUILTIN_NAMES` is a set of NAMES; the backend's answer about each of them
    is a separate fact, and this class is what holds the two together.

    The finding this class exists for: of the 33 names the census lets a
    candidate read, the path lowers 11 and refuses 22, and nothing said which was
    which — so six items were reported as "the image would bind 1 symbol(s) that
    nothing provides", which is a fact about SYMBOLS and not an answer to the
    question a reader of a proof census is asking (is the frontier the proof
    layer or the code generator, and what would it take to move?).  Fixed in
    c8d877e9 (the model's measured table) + af313965 (this census reading it),
    with the doc deleted alongside.

    The fix has two halves and this class is both of them. The census now reads
    the ONE table `formal/model.py` publishes (`NOT_LOWERED_BUILTINS`) and
    classifies a refusal that names one of those builtins into a class of its
    own, and the partition is asserted here so that a name added to
    `BUILTIN_NAMES` without a measured verdict fails a test instead of becoming
    a frontier nobody reported. The MEASUREMENT half — one differential case per
    builtin against CPython, on both architectures — is
    `test_formal_value_model.py`'s `BUILTIN_CASES` / `BUILTIN_REFUSALS`, because
    that is the file whose stated job is "build, run, and require the same
    bytes CPython prints", and a table of sentences is not a measurement.
    """

    def test_every_allowed_name_is_either_lowered_or_named_as_missing(self):
        allowed = set(B.BUILTIN_NAMES)
        lowered = set(B.LOWERED_BUILTINS)
        missing = set(B.NOT_LOWERED_BUILTINS)
        self.assertEqual(allowed & lowered & missing, set(),
                         "a name is claimed both lowered and not lowered, so "
                         "one of the two halves is a stale sentence")
        self.assertEqual(
            allowed - lowered - missing, set(),
            "these names are in the census's allow-list and in NEITHER half: "
            "nobody has measured whether the formal path lowers them, which is "
            "the state this file's docstring says produced the finding")
        self.assertEqual(
            lowered | missing, allowed,
            "these names are measured and are not in the allow-list, so the "
            "census will disqualify a candidate for reading a name the "
            "measurement says is fine")

    def test_every_missing_name_says_what_lowering_it_would_take(self):
        for name, why in sorted(B.NOT_LOWERED_BUILTINS.items()):
            self.assertTrue(why.strip(), f"{name} has no sentence")
            self.assertGreater(len(why), 40,
                               f"{name}'s sentence is too short to be a "
                               f"measurement: {why!r}")

    def test_the_three_names_whose_absence_was_silent_are_in_the_table(self):
        """`abs`, `pow` and `round` are the ones that were not refused by
        anything: the C library defines all three, so the image bound
        libSystem's `int abs(int)`, its `double pow(double, double)` and its
        `double round(double)` and answered a different number.

        They are in `NOT_LOWERED_BUILTINS` because that is what the table means
        now, and in `formal/model.py`'s `FOREIGN_ABI_BUILTINS` because that is
        what the EMITTER asks: a name nothing provides is already refused by the
        bind audit, so only the subset that would otherwise BIND needs a refusal
        at the call site. If one of the three is lowered later it leaves both
        sets and this test is what says so."""
        import formal.model as M
        self.assertEqual(M.FOREIGN_ABI_BUILTINS, {"abs", "pow", "round"})
        self.assertTrue(M.FOREIGN_ABI_BUILTINS <= set(B.NOT_LOWERED_BUILTINS),
                        "a name the emitter refuses by name must also be in "
                        "the census's table, or the two halves disagree about "
                        "what is missing")
        for name in sorted(M.FOREIGN_ABI_BUILTINS):
            self.assertIn(name, M.builtin_binding_refusal(name),
                          "the refusal has to NAME the builtin")
        self.assertIsNone(M.builtin_binding_refusal("len"),
                          "a name the path lowers must not be refused as one "
                          "it cannot bind")

    def test_a_builtin_refusal_is_its_own_class_and_names_the_builtin(self):
        """Both architectures, because the link audit's message is one message
        and the class must not depend on which emitter produced it."""
        src = ("def f(n):\n"
               "    return max(n, 1)\n"
               "def main(x):\n"
               "    return f(x)\n")
        for arch in ("arm64", "x86_64"):
            self.assertEqual(self._class_of(src, arch),
                             "refused-builtin")
        detail = B.builtin_refusal_detail(B._unlowered_builtins_in(src),
                                          "f.mojo: the image would bind 1 "
                                          "symbol(s) that nothing provides")
        self.assertTrue(detail.startswith(B.BUILTIN_DETAIL_MARK), detail)
        self.assertEqual(B._builtins_named_in_detail(B._first_line(detail)),
                         ["max"],
                         "the names have to survive `_first_line`'s 300-"
                         "character cut, because the frontier section reads "
                         "them back out of the ledger row")

    def test_a_refusal_that_names_no_builtin_stays_where_it_was(self):
        """The marker says what KIND of refusal it is; the table says which
        builtin. A refusal carrying the marker with no name from the table — a
        method call on a frame, say — must not be reported as a missing
        builtin, because that would be reporting a name the census did not
        read."""
        marker = ("`append` is a call this build emitted and nothing provides "
                  "it, so that call is not lowered on this path")
        src = ("def f(n):\n"
               "    return max(n, 1)\n")          # a call, but not THE call
        src_without_call = "def f(n):\n    return n + 1\n"
        self.assertEqual(B._refusal_class(marker, src_without_call),
                         "codegen-refused")
        self.assertEqual(B._refusal_class(marker, src),
                         "refused-builtin")

    def test_the_report_prints_the_frontier_the_run_reached(self):
        """Counted from the ITEMS, not from the table: a builtin no item called
        is not in this run's frontier, and one four items called is worth four
        times the sentence."""
        src = ("def f(n):\n"
               "    return max(n, 1)\n"
               "def main(x):\n"
               "    return f(x)\n")
        import shutil
        import tempfile as tf
        tmp = tf.mkdtemp(prefix="pb-frontier-")
        try:
            item = B.Workload(ident="t", origin="repo", source=src,
                              detail="", weight=0)
            v = B.run_item(item, "arm64", timeout=60, workdir=tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        text = B.report([v], ["arm64"])
        self.assertIn("the builtins that stopped an item", text, text)
        self.assertIn("`max`", text, text)
        self.assertNotIn("`pow`", text,
                         "the frontier is what this run reached; `pow` stopped "
                         "nothing here and is printed as if it had")
        self.assertIn("a compare and a select", text,
                      "the frontier section without the sentence is the "
                      "allow-list assertion this file is about")

    def _class_of(self, source, arch="arm64"):
        import shutil
        tmp = tempfile.mkdtemp(prefix="pb-builtin-")
        try:
            item = B.Workload(ident="t", origin="repo", source=source,
                              detail="", weight=0)
            return B.run_item(item, arch, timeout=60, workdir=tmp).cls
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestAReplayedVerdictSaysSo(unittest.TestCase):
    """A verdict the cache answered is a fact about the measurement, and the
    ledger has to carry it.

    `formal/lean.py::check_proof_cached` answers `True` for "these exact proof
    bytes have been checked before" in about a tenth of a second. The census
    used to discard that flag, so a replayed row read exactly like a fresh one —
    `bugs/sweeps/proof_breadth_2026-10-03.jsonl` records
    `formal/examples/either.mojo` as `{"cls": "pass", "wall_s": 0.1}` on a date
    it was never checked, and a proof regression the size of
    `bugs/FORMAL_a_generated_proof_over_leans_memory_ceiling_is_rejected.md`'s
    was recorded as coverage. "The corpus still measures this construct" is the
    claim every `KNOWN_DIVERGENCES` discipline here rests on, and a replayed
    verdict does not support it.

    The check is on the plumbing, with the cache stubbed: what matters is that
    the flag reaches the `Verdict` and the summary, and that is a property of
    this file's code rather than of what the cache happens to hold on the day.
    """

    SOURCE = "def main(n):\n    return n + 1\n"

    def _verdict_with_cache(self, cached):
        import shutil
        import formal.lean
        real = formal.lean.check_proof_cached
        formal.lean.check_proof_cached = lambda *a, **k: (True, "", cached, 0)
        tmp = tempfile.mkdtemp(prefix="pb-cached-")
        try:
            item = B.Workload(ident="t", origin="repo", source=self.SOURCE,
                              detail="", weight=0)
            return B.run_item(item, "arm64", timeout=60, workdir=tmp)
        finally:
            formal.lean.check_proof_cached = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_replayed_verdict_is_flagged_and_a_fresh_one_is_not(self):
        fresh = self._verdict_with_cache(False)
        replayed = self._verdict_with_cache(True)
        self.assertEqual(fresh.cls, replayed.cls,
                         "the stub changed the class, so this test is not "
                         "measuring the flag")
        self.assertFalse(fresh.cached,
                         "a fresh check is reported as a replay")
        self.assertTrue(replayed.cached,
                        "a replayed check is reported as fresh — this is the "
                        "defect: the row reads as a measurement it was not")

    def test_the_report_counts_the_replayed_rows(self):
        fresh = self._verdict_with_cache(False)
        replayed = self._verdict_with_cache(True)
        text = B.report([fresh, replayed], ["arm64"])
        self.assertIn("of which replayed", text,
                      f"the summary cannot be read as a measurement without "
                      f"the ledger:\n{text}")


if __name__ == "__main__":
    unittest.main(verbosity=2)