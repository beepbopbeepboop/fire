#!/usr/bin/env python3
"""`tools/formal_fuzz.py`'s own regression suite: the GENERATOR and the RUNNER.

Why this file exists
--------------------
The fuzzer is a measurement, and a measurement whose own machinery is untested
measures the machinery. Two things can be wrong with it, and both would look
like a clean backend:

* **the generator emits a program that is not a differential test at all** — a
  read before its first assignment, a divisor that can be zero, a `while` whose
  body came out empty. Each of those makes CPython the wrong oracle (a
  `NameError`, a trap, a `SyntaxError`) and the program counts towards the run's
  totals while reporting nothing about the backend. So every mix's output is
  checked for all three, with no compiler involved.
* **the runner's verdicts are not verdicts** — a build that reported success and
  wrote no binary, a comparison that stopped at the exit code and ignored the
  output, an attribution that dismissed everything. So a fixed index range is
  run end to end and every disagreement is required to be either attributed to a
  construct `KNOWN_DIVERGENCES` names or reported as unexplained, and the second
  of those is a failure here.

* **a construct family that has quietly become refusable** — a mix whose
  programs are all REFUSED still parses, still runs on CPython, still counts
  towards a run's totals and reports nothing about the backend, so it is
  indistinguishable from a clean one. `check_mix_builds` requires every mix to
  produce at least one ANSWER on one architecture. This is the check that would
  have caught `objects`' `field_read` on the day `print(obj.field)` started
  being refused — 284 of 300 generated class programs were that one refusal.

    python3 test_formal_fuzz.py [-v] [--count N] [--arch both|arm64|x86_64]
                                [--mix MIX]

The indexes are PINNED and the count is small on purpose. The point is not
coverage — a sweep is what covers this — it is that a change to the generator,
the classifier or the attribution which altered a verdict would fail HERE
instead of quietly changing what a sweep of two thousand programs measures.

Every mix is checked in the generator half, including `signed` and `strings`,
because those two exist to produce a construct on purpose: a mix that stopped
producing `//` with a signed divisor, or `s[i]`, would leave the corpus quietly
smaller. For `strings` that is a DEAD `KNOWN_DIVERGENCES` row; for `signed` it
is worse, because the row was DELETED when both backends learned to floor and
nothing else would have noticed. Both are asserted directly, not inferred.

NOT registered in `tools/suite.py` (it is declared in `test_suite.py`'s
`UNREGISTERED` with that reason). It builds twenty images per architecture, which
is more than a unit test's share, and its heavier setting — a few thousand
programs — is a sweep rather than a check.
"""

import argparse
import os
import re
import subprocess
import sys

# This file lives at the repository root, so HERE *is* the root — spelled this
# way rather than as `dirname(HERE)` because that is the bug a top-level test
# file invites, and `formal_fuzz` is in `tools/`.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import formal_fuzz as F  # noqa: E402

# How many indexes the generator half checks per mix, and how many the run half
# pins end to end. The generator half costs nothing (no compiler), so it is the
# wider of the two; the run half is the expensive one and is deliberately small.
GEN_INDEXES = 60
SEEDS = 20

# The corpus words CPython is handed the generated text with. A program CPython
# will not parse was never a differential test, and finding that here costs
# nothing rather than costing a build.
PYTHON_HEAD = F.PRELUDE + "\n"


def _fail(name, detail, verbose):
    print(f"  FAIL  {name}: {detail}")
    if verbose:
        print("        " + detail.replace("\n", "\n        "))
    return 1


#: (file, constant name, the model's constant it must be bound to). The two
#: container budgets, and the reason this check reads the SOURCE rather than the
#: values: `_SCRATCH` evaluating to 131072 is what a hardcoded literal also
#: does, and the property that matters is that the tree has ONE number.
BUDGET_BINDINGS = (
    ("formal/arm64_codegen.py", "_SCRATCH", "ARM64_CONTAINER_BUDGET"),
    ("formal/x86_64_codegen.py", "_BLOB_BYTES", "X86_64_CONTAINER_BUDGET"),
)


def check_frame_budget(verbose=False):
    """ONE container budget per architecture, and one that decides.

    Four properties, each of which is a way this could be quietly true in the
    tree and false in the run:

    * **both emitters READ the model's constant.** Read from the source with
      `ast`, because a value comparison passes on a literal: what has to be
      absent is a second copy of the number, not a disagreement about it.
    * **the refusal message this tool matches on is the model's own.** A
      reword of `frame_blob_refusal` that moved the phrase would turn every
      frame-budget divergence back into an unqualified parity finding, silently,
      which is the failure `test_formal_fuzz.py`'s classifier rows cannot see
      because they hand-write the message.
    * **the smaller budget is the one that decides**, so
      `formal/model.py::CONTAINER_BUDGET` is `min` and not a third number.
    * **the corpus's `big_blob` row is sized off that same budget** — past the
      smaller ceiling (so x86-64 refuses it) and inside the larger one (so arm64
      lowers it), which is precisely the pair the new classifier class names.
      Checked over generated programs, so a corpus that stopped emitting the
      row is caught as well as a corpus that resized it wrongly.
    """
    failures = 0
    import ast

    for rel, name, model_const in BUDGET_BINDINGS:
        path = os.path.join(ROOT, rel)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read(), path)
        except (OSError, SyntaxError) as e:
            failures += _fail(f"{name}_is_readable", f"{rel}: {e}", verbose)
            continue
        assigned = [n.value for n in tree.body
                    if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", None) == name for t in n.targets)]
        if not assigned:
            failures += _fail(f"{name}_is_assigned_at_module_level",
                              f"{rel} declares no module-level `{name}`", verbose)
            continue
        rhs = assigned[0]
        ok = (isinstance(rhs, ast.Attribute) and rhs.attr == model_const
              and isinstance(rhs.value, ast.Name) and rhs.value.id == "M")
        if not ok:
            failures += _fail(
                f"{name}_reads_the_models_constant",
                f"{rel}: `{name}` is bound to {ast.dump(rhs, annotate_fields=False)}"
                f", not `M.{model_const}` — a second literal in the tree is the "
                f"thing this row exists to prevent", verbose)

    message = F.M.frame_blob_refusal("a list literal", 17608, 16344)
    if F.FRAME_BLOB_REFUSAL_HEAD not in message:
        failures += _fail(
            "the_frame_budget_head_is_the_models_own",
            f"`frame_blob_refusal` opens {message[:70]!r}, which does not "
            f"contain {F.FRAME_BLOB_REFUSAL_HEAD!r} — every frame-budget "
            f"divergence in a sweep is now reported as an unqualified parity "
            f"finding", verbose)

    if F.M.CONTAINER_BUDGET != min(F.M.ARM64_CONTAINER_BUDGET,
                                   F.M.X86_64_CONTAINER_BUDGET):
        failures += _fail(
            "the_smaller_budget_decides",
            f"CONTAINER_BUDGET is {F.M.CONTAINER_BUDGET}, which is not the "
            f"smaller of {F.M.ARM64_CONTAINER_BUDGET} and "
            f"{F.M.X86_64_CONTAINER_BUDGET}", verbose)

    small = F.M.blob_ceiling(F.M.CONTAINER_BUDGET)
    large = F.M.blob_ceiling(F.M.ARM64_CONTAINER_BUDGET)
    if small >= large:
        failures += _fail(
            "the_two_ceilings_are_distinguishable",
            f"the smaller budget's ceiling is {small} and the larger's is "
            f"{large}, so no literal can be refused by one machine and lowered "
            f"by the other and the row this measures is unreachable", verbose)
    seen = 0
    for index in range(GEN_INDEXES):
        src = F.make_program("suite", index, "limits")
        for line in src.splitlines():
            body = line.strip()
            if not body.startswith("BL") or " = [" not in body:
                continue
            n = body.split(" = [", 1)[1].count(",") + 1
            seen += 1
            if not (small < n <= large):
                failures += _fail(
                    f"the_corpus_blob_is_the_shape_the_class_names",
                    f"{n} elements is not past the smaller ceiling ({small}) "
                    f"and inside the larger one ({large})", verbose)
            break
    if not seen:
        failures += _fail(
            "the_corpus_still_emits_a_oversized_blob",
            f"no `limits` program in 0..{GEN_INDEXES - 1} carried a `big_blob` "
            f"literal, so the class this row names is unreachable from the "
            f"corpus", verbose)

    print(f"formal fuzz: budgets    {'PASS' if not failures else 'FAIL'} "
          f"{len(BUDGET_BINDINGS)} bindings, {seen} blob(s) (no compiler)")
    return failures


def check_generator(mix, indexes, verbose=False):
    """Every generated program is a valid differential test.

    Four properties, and each is a way the corpus could stop measuring the
    backend while still reporting numbers:

    * **CPython parses it**, prelude and `main()` call included — that pair is
      what the run half actually executes, so it is what is checked here.
    * **It is deterministic.** `make_program` twice, and a different index
      giving a different program — the second half is what makes determinism
      useful rather than merely repeatable, since a generator that ignored its
      seed would satisfy the first.
    * **It still produces the shapes its mix exists to reach.** Two halves, and
      they fail in opposite directions. A mix that stops emitting a construct
      `KNOWN_DIVERGENCES` names leaves a DEAD row — `strings` and `s[i]`, checked
      by `_check_features`. A mix that stops emitting a construct the backend is
      now RIGHT about leaves a silently smaller corpus, which no tally would
      report — `signed` and the signed-over-signed `//`/`%`, checked by
      `_check_generation` against `formal_fuzz.MIX_MUST_GENERATE`. That is why
      `signed` is in the second table and not the first: its `floordiv` row was
      DELETED in the commit that fixed both backends, and deleting the row must
      not have deleted the coverage with it.
    * **The subset's stated invariants hold textually**: a `def main(`, and
      none of the Mojo-only keywords CPython cannot parse.
    """
    failures = 0
    first = make_first = F.make_program("suite", 0, mix)
    for index in range(indexes):
        src = F.make_program("suite", index, mix)
        try:
            compile(PYTHON_HEAD + src + "\nmain()\n", f"<{mix} {index}>", "exec")
        except SyntaxError as e:
            failures += _fail(f"{mix}_index_{index}_is_not_python",
                              f"line {e.lineno}: {e.msg}\n{src}", verbose)
            continue
        if "def main(" not in src:
            failures += _fail(f"{mix}_index_{index}_has_no_main", src, verbose)
        if F.make_program("suite", index, mix) != src:
            failures += _fail(f"{mix}_index_{index}_is_not_deterministic",
                              "two calls disagreed", verbose)
        if index and src == first:
            failures += _fail(f"{mix}_index_{index}_equals_index_0",
                              "the index is not reaching the generator", verbose)
        for banned in ("var ", "fn ", "struct ", "Self"):
            if banned in src:
                failures += _fail(
                    f"{mix}_index_{index}_is_not_valid_python",
                    f"contains {banned!r}, which CPython cannot parse:\n{src}",
                    verbose)

    failures += _check_generation(mix, indexes, verbose)
    failures += _check_features(mix, indexes, verbose)

    print(f"formal fuzz: generator {mix:9} PASS={indexes - failures} "
          f"FAIL={failures} ({indexes} indexes, no compiler)")
    return failures


#: mix -> the feature it must keep producing, and why that mix exists.
#:
#: **This is the KNOWN-DIVERGENCE half, and it is not where `signed` is any
#: more.**  A row here means the backend still gets the construct wrong, and the
#: anti-rot is that such a row must be DELETED the day it stops being true.  So
#: `signed` moved out of this table into `_check_generation` /
#: `formal_fuzz.MIX_MUST_GENERATE`, which asserts the weaker and still
#: load-bearing thing — that `--mix signed` still GENERATES a signed-over-signed
#: `//`/`%`.  That claim is about the generator rather than about the backend, so
#: it is true while the backend is right and it is what notices the day a change
#: stops emitting the shape.
MIX_MUST_REACH = {
    "strings": ("str_subscript",
                "`s[i]` is a byte rather than a one-character string, and the "
                "corpus has to produce it for the row to stay live"),
}


def _check_generation(mix, indexes, verbose):
    """Every mix that exists to PRODUCE a shape must still produce it.

    Checked over the same index range as the rest, and separate from the
    known-divergence half above because the two fail in opposite directions: a
    mix that stops emitting a construct `KNOWN_DIVERGENCES` still names leaves
    a dead row (a row nothing can trigger is a row that has stopped measuring),
    and a mix that stops emitting a construct the backend is now RIGHT about
    leaves a silently smaller corpus, which is the failure
    `bugs/FORMAL_fuzz_ledger.md` §1 states — "a mix that stops producing a
    construct reports the same clean tally as one that never produced it".  Only
    the second one has any way of being noticed, and it was `signed`'s, which is
    why it is checked on its own table (`formal_fuzz.MIX_MUST_GENERATE`) rather
    than inferred from a row that had to be deleted in the same commit.
    """
    want = F.MIX_MUST_GENERATE.get(mix)
    if not want:
        return 0
    pattern, why = want
    hits = 0
    for index in range(indexes):
        if re.search(pattern, F.make_program("suite", index, mix)):
            hits += 1
    if hits == 0:
        return _fail(f"{mix}_never_generates_its_own_construct", why, verbose)
    print(f"formal fuzz: generator {mix:9} still generates "
          f"{pattern!r} in {hits}/{indexes}")
    return 0


def _check_features(mix, indexes, verbose):
    """The mixes that carry a known divergence must still produce it.

    Checked over the same index range as the rest, and it is a separate check
    rather than a property of the syntax pass because the failure it catches is
    silent: a mix that stopped emitting signed divisors would still parse, would
    still run, and would still report numbers — every one of them clean — while
    `KNOWN_DIVERGENCES` had a row nothing could reach. That is a coverage hole
    dressed as a green run.
    """
    want = MIX_MUST_REACH.get(mix)
    if not want:
        return 0
    feature, why = want
    hits = 0
    for index in range(indexes):
        src = F.make_program("suite", index, mix)
        if feature in F.features_of(src):
            hits += 1
            # The neutraliser has to be able to TAKE IT OUT, or attribution
            # would fall through to "unexplained" on every program the mix
            # exists to produce.
            if F.neutralise(src, feature) is None:
                return _fail(f"{mix}_cannot_neutralise_{feature}",
                             f"{why}, and the neutraliser cannot remove it",
                             verbose)
    if hits == 0:
        return _fail(f"{mix}_never_reaches_{feature}", why, verbose)
    print(f"formal fuzz: generator {mix:9} reaches {feature} in "
          f"{hits}/{indexes}")
    return 0


# (name, results dict, want verdict).  `results` is what `check_one` hands
# `classify`, built by hand because the classifier is the one piece of the
# runner that decides EVERYTHING and that no case exercises on its own: every
# other row here goes through a real build, so it can only reach the verdicts
# the corpus happens to produce.
#
# `ok` is `{"verdict": "ok", "rc": <int>, "stdout": <str>}`; the oracle this
# table compares against is `(0, "1\n")`, so an `ok` carrying that is a match
# and anything else is a disagreement with it.
CLASSIFIER_CASES = [
    ("both_agree", {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
                    "arm64": {"verdict": "ok", "rc": 0, "stdout": "1\n"}},
     "match"),
    ("one_disagrees", {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
                       "arm64": {"verdict": "ok", "rc": 0, "stdout": "2\n"}},
     "MISMATCH-ARM64"),
    # Two different answers from two machines that both RAN. `ARM64-DIVERGES` is
    # the verdict this shape is about, and it is UNREACHABLE while the two
    # oracle comparisons come first: both answers are compared against the same
    # CPython output, so "both agree with CPython and differ from each other"
    # cannot happen. Measured by writing this case and getting `MISMATCH-X86` —
    # which is the RIGHT answer (x86-64 printed `2` where the source says `1`),
    # and which names the engine that is wrong about the program. The verdict is
    # kept because the docstring documents it and because it becomes reachable
    # the moment the ordering changes, but a reader must not expect to see it in
    # a sweep's tally.
    ("the_two_answers_differ", {"x86_64": {"verdict": "ok", "rc": 0,
                                           "stdout": "2\n"},
                                "arm64": {"verdict": "ok", "rc": 0,
                                          "stdout": "3\n"}},
     "MISMATCH-X86"),
    # BOTH refusing is NOT a finding. A construct with no representation is
    # correctly refused, and counting those as bugs would spend the whole
    # budget on `bugs/FORMAL_known_limits.md`.
    ("both_refuse", {"x86_64": {"verdict": "refusal", "diag": "no"},
                     "arm64": {"verdict": "refusal", "diag": "no"}},
     "refusal"),
    # …and ONE refusing while the other ANSWERS is, because the construct is
    # representable and this machine declines it. Measured on the tree this
    # landed on: arm64 built and ran a program x86-64 refused with "main:
    # '_cb0' has no home", and the sweep called it a plain `refusal`.
    ("one_refuses_while_the_other_answers",
     {"x86_64": {"verdict": "refusal", "diag": "no home"},
      "arm64": {"verdict": "ok", "rc": 0, "stdout": "1\n"}},
     "REFUSAL-DIVERGES-X86"),
    ("one_refuses_the_other_way",
     {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
      "arm64": {"verdict": "refusal", "diag": "no home"}},
     "REFUSAL-DIVERGES-ARM"),
    # BOTH refusing is agreement ONLY when the two say the same thing. These
    # two rows are the second shape of the same verdict, and it is the one that
    # hid a real bug: x86-64 refused every image containing an `int(s, base)`
    # with "internal: label 'main_ip1_end' is defined twice …" while arm64
    # answered the program, and the pair counted as one clean `refusal`.
    ("both_refuse_in_different_words",
     {"x86_64": {"verdict": "refusal", "diag": "'+' on two strings is refused"},
      "arm64": {"verdict": "refusal", "diag": "a list literal does not fit"}},
     "REFUSAL-DIVERGES-X86+ARM"),
    # …and the FOLD is what keeps that from firing on every refusal: "on the
    # formal arm64 path" and "on the formal x86-64 path" are one sentence told by
    # two machines, and a difference there would be a difference in this
    # classifier rather than in the backend. Written as the pair of strings a
    # real message pair differs by, and measured: with the fold removed this row
    # returns a divergence and the sweep is red on every slice it ever refused.
    ("both_refuse_with_only_the_arch_label_differing",
     {"x86_64": {"verdict": "refusal",
                 "diag": "print() cannot tell whether SliceExpr is a string on "
                         "the formal x86-64 path"},
      "arm64": {"verdict": "refusal",
                "diag": "print() cannot tell whether SliceExpr is a string on "
                        "the formal arm64 path"}},
     "refusal"),
    # The COMPILER talking about itself, where a reader is told about the
    # PROGRAM. Its own verdict: as a `refusal` it was a documented limit, and
    # the tally said so.
    ("an_internal_diagnostic_is_not_a_refusal",
     {"x86_64": {"verdict": "codegen-internal", "rc": 1,
                 "diag": "build: internal: label 'main_ip1_end' is defined "
                         "twice, at 0x1000003ba and at 0x1000003ba"},
      "arm64": {"verdict": "refusal", "diag": "'+' on two strings is refused"}},
     "CODEGEN-INTERNAL"),
    ("an_internal_diagnostic_where_both_machines_have_one",
     {"x86_64": {"verdict": "codegen-internal", "rc": 1, "diag": "internal: a"},
      "arm64": {"verdict": "codegen-internal", "rc": 1, "diag": "internal: a"}},
     "CODEGEN-INTERNAL"),
    # A refusal AND a wrong answer is the wrong answer, and it is reported as
    # one: the finding names the engine that is wrong about the program's
    # meaning, which is the engine that produced an answer.
    ("one_refuses_and_the_other_is_wrong",
     {"x86_64": {"verdict": "refusal", "diag": "no"},
      "arm64": {"verdict": "ok", "rc": 0, "stdout": "9\n"}},
     "MISMATCH-ARM64"),
    # A crash outranks a refusal and a trap: both are about the IMAGE rather
    # than about a difference between two of them.
    ("a_crash_is_a_finding",
     {"x86_64": {"verdict": "crash", "rc": 139},
      "arm64": {"verdict": "refusal", "diag": "no"}}, "CODEGEN-CRASH"),
    ("a_trap_is_not",
     {"x86_64": {"verdict": "ok", "rc": 0, "stdout": "1\n"},
      "arm64": {"verdict": "trapped", "rc": 2}}, "trapped"),
    # …and the ONE divergence that is not about the language: a container too
    # big for one machine's frame and small enough for the other's. The two
    # budgets are 8x apart (`formal/model.py::CONTAINER_BUDGET` is the smaller
    # and is the one a program must fit to build on both), so any literal
    # between the two ceilings lands here, BY DESIGN, and a tally that counts
    # it as a capability difference hides the parity findings that are not
    # designed. The budgets are `formal/model.py::ARM64_CONTAINER_BUDGET` and
    # `X86_64_CONTAINER_BUDGET`, the smaller is `CONTAINER_BUDGET`, and
    # `frame_budget_phrase()` is the one sentence that states all three.
    # The two rows below are the pair that matters and they are red under the
    # un-refined classifier in both directions: the class is added when the
    # refusal IS the frame message, and NOT added when it is anything else, so
    # a reword that moved the phrase out of `frame_blob_refusal` would put this
    # finding back into the unqualified bucket — which is the correct outcome,
    # because at that point nobody could tell it apart again.
    ("the_frame_budget_divergence_names_itself",
     {"x86_64": {"verdict": "refusal",
                 "diag": "build: a list literal does not fit in the frame: "
                         "it needs 17608 bytes and this function has 16344 "
                         "left for containers."},
      "arm64": {"verdict": "ok", "rc": 0, "stdout": "1\n"}},
     "REFUSAL-DIVERGES-FRAME-BUDGET-X86"),
    ("the_frame_class_is_not_a_spare_room_for_other_refusals",
     {"x86_64": {"verdict": "refusal",
                 "diag": "build: a dict literal does not fit in the frame is "
                         "not said; this is a capacity refusal: 8 slots are "
                         "reserved for a dynamic operand"},
      "arm64": {"verdict": "ok", "rc": 0, "stdout": "1\n"}},
     "REFUSAL-DIVERGES-X86"),
]


def check_classifier(verbose):
    """Every verdict `classify` can return, on results built by hand.

    No compiler and no corpus: this is the function that decides whether a
    program that computed the wrong number is a finding, and it is reached only
    through a real build everywhere else in this file — so a change to it that
    turned a `MISMATCH-*` into a `refusal` would pass every other row here and
    turn a sweep green.
    """
    args = argparse.Namespace(backends=["x86_64", "arm64"], min_kind="any")
    failures = 0
    for name, results, want in CLASSIFIER_CASES:
        got = F.classify(results, 0, "1\n", args)
        if got != want:
            failures += _fail(f"classify_{name}", f"said {got!r}, "
                              f"expected {want!r}", verbose)
    print(f"formal fuzz: classify    {'PASS' if not failures else 'FAIL'} "
          f"{len(CLASSIFIER_CASES)} verdicts (no compiler)")
    return failures


# (name, program text, diagnostic, cpython answer, want verdict, want construct).
# The programs and the diagnostics are MEASURED — each one is what both
# backends actually said for a program of that shape, off `limits` seeds
# 8000-8015 — because a table of invented sentences would test the audit's
# spelling of a language nobody writes.  `cpython` is `cpython_answer`'s
# three-way answer; `None` stands for a CPython TIMEOUT, which is the one
# answer the audit must not mistake for an oracle.
AUDIT_CASES = [
    # A quoted operator: the construct IS the operator and the message says so.
    ("a_quoted_operator",
     'def main():\n    s = "ab"\n    print(s + "cd")\n    return 0\n',
     "build: '+' on two strings is refused on this path. A string here is a "
     "bare `char *`, so `+` is integer arithmetic on two addresses.",
     (0, "abcd\n"), "true", "+"),
    # The method-call head, unquoted — the shape half of these messages use and
    # the one a quoted-token-only rule would call unnamed.
    ("a_dotted_method_head",
     'def main():\n    s = "ab"\n    print(s.upper())\n    return 0\n',
     "build: s.upper() is a real method of String, but it returns a NEW "
     "string of the same length, and the only buffer available for it is the "
     "receiver's own bytes.",
     (0, "AB\n"), "true", "s.upper()"),
    # …and the same message about a dict receiver.
    ("a_dict_method_head",
     'def main():\n    d = {10: 100}\n    print(d.keys())\n    return 0\n',
     "build: d.keys() is a method call on a value, and this backend lowers "
     "only append, close, write and the string methods count, endswith, find, "
     "lstrip, startswith — 'keys' is not one of those",
     (0, "dict_keys([10])\n"), "true", "d.keys()"),
    # A `line N:` site prefix in front of a quoted keyword. The prefix names
    # WHERE and must not become the construct: five of `limits`' first ten
    # programs were filed under the construct `line` before the prefix was
    # stripped as one thing.
    ("a_line_prefix_and_a_quoted_keyword",
     "def main():\n    try:\n        q = 1\n    except:\n        q = 2\n"
     "    print(q)\n    return 0\n",
     "build: line 29: a bare `except:` is a handler arm with a body this path "
     "cannot put in the image, so it is refused rather than dropped",
     (0, "1\n"), "true", "except:"),
    # A construct named as an AST node, which no token of the program can
    # match: `xs[1:3]` does not contain the word `SliceExpr`.
    ("a_slice_through_print",
     'def main():\n    xs = [1, 2, 3]\n    print(xs[1:3])\n    return 0\n',
     "build: print() cannot tell whether SliceExpr is a string or a number on "
     "the formal arm64 path, and guessing would print an address as if it were "
     "text.",
     (0, "[2, 3]\n"), "true", "print()"),
    # A construct named in PROSE, with no token of the program to match it: a
    # 2100-element literal of bare integers, and a message about "a list
    # literal". Flagged `unnamed` without the construct-word vocabulary, and that
    # would be a false finding on a message that names its construct perfectly
    # well.
    ("a_container_budget_refusal",
     "def main():\n    BL = [" + ", ".join(["1"] * 2100) + "]\n"
     "    print(len(BL))\n    return 0\n",
     "build: a list literal does not fit in the frame: it needs 17608 bytes "
     "and this function has 16344 left for containers.",
     (0, "2100\n"), "true", "list"),
    # THE FINDING, and it is FIXED: an unlowered callee used to reach the link
    # audit, whose message opened with the FILE name and named the symbol in the
    # middle of a sentence about symbols — four plausible leading tokens, none
    # of them the call in the source, because the message never said what `sum`
    # was. It says so now (`check_module_symbols` publishes each function's
    # bare-named callees and `formal/build.py`'s `_unaccounted_report` asks the
    # set which of its two causes each name is), so this row's verdict moves
    # from `unnamed` to `true` and its construct from nothing to the callee. It
    # is kept rather than deleted for the reason every row here is kept: it is
    # the measurement, and the measurement is what would catch the regression.
    # Both backends said byte-identical words for it before and after.
    ("an_unlowered_callee_names_the_call",
     'def main():\n    xs = [1, 2]\n    print(sum(xs))\n    return 0\n',
     "build: sum.mojo: the image would bind 1 symbol(s) that nothing provides, "
     "so it could not be loaded: sum. `sum` is a call this build emitted and "
     "nothing provides it, so that call is not lowered on this path: this "
     "backend has no call to bind there, which is a fact about the PROGRAM and "
     "not about the link line. Write the operation out, or bind the name from a "
     "library that provides it. Every name in this list is one of the calls "
     "named above, so nothing about the link line is left to explain. (Provider "
     "check: asked the C library (dlsym).)",
     (0, "3\n"), "true", "sum"),
    # The same shape with an INTERNAL diagnostic, which never reaches the audit
    # because `run_on` gives it its own verdict first — asserted here because
    # the two classifications are adjacent and a reordering would let the second
    # report the first's bugs.
    ("an_internal_diagnostic_names_nothing",
     "def main():\n    print(1)\n    return 0\n",
     "build: internal: label 'main_ip1_end' is defined twice, at 0x1000003ba "
     "and at 0x1000003ba.",
     (0, "1\n"), "unnamed", "unnamed"),
    # A promise about CPython, KEPT: the message says UnboundLocalError for a
    # read before its store and CPython raises UnboundLocalError.
    ("a_kept_cpython_promise",
     "def main():\n    print(y)\n    y = 3\n    return 0\n",
     "build: main: 'y' is read at line 2 before anything in this function "
     "stores it, and CPython raises UnboundLocalError for that program "
     "(NameError at module level).",
     ("error", "UnboundLocalError: local variable 'y' referenced before "
               "assignment"), "true", "y"),
    # …and REFUTED, which is the only `false` this tool can decide: the same
    # message over a program CPython runs. A refusal whose promise the reference
    # refutes is worse than one that names nothing, because the reader has been
    # told what to expect from the source and it is not that.
    ("a_refuted_cpython_promise",
     "def main():\n    print(y)\n    y = 3\n    return 0\n",
     "build: main: 'y' is read at line 2 before anything in this function "
     "stores it, and CPython raises UnboundLocalError for that program "
     "(NameError at module level).",
     (0, "3\n"), "false", "y"),
    # The promise with NO oracle to keep or refute it. `None` is a CPython
    # TIMEOUT and the audit must say so rather than pass the claim: the whole
    # value of the row is that it is checked, and an unchecked claim reported
    # as checked is the failure mode of an audit that cannot fail.
    ("a_cpython_promise_with_no_oracle",
     "def main():\n    print(y)\n    y = 3\n    return 0\n",
     "build: main: 'y' is read at line 2 before anything in this function "
     "stores it, and CPython raises UnboundLocalError for that program "
     "(NameError at module level).",
     None, "no-predicate", "y"),
]


def check_audit(verbose):
    """Every verdict `audit_refusal` can return, on measured messages.

    No compiler: the audit is a function of a PROGRAM and a MESSAGE, and both
    are in the table above.  It is the function that decides whether a refusal
    is worth reading, so a change to it that turned every verdict into `true`
    would pass the generator half and the run half of this file — those run real
    builds and compare ANSWERS, and neither of them looks at a diagnostic.
    """
    failures = 0
    for name, text, diag, cpython, want, want_construct in AUDIT_CASES:
        got, detail = F.audit_refusal(text, diag, cpython)
        if got != want:
            failures += _fail(
                f"audit_{name}",
                f"said {got!r} ({detail}), expected {want!r}", verbose)
        got_construct = F.refusal_construct(diag, text)
        if got_construct != want_construct:
            failures += _fail(
                f"audit_{name}_names",
                f"named the construct {got_construct!r}, expected "
                f"{want_construct!r}", verbose)
    # Every verdict the audit can return has a row above, so a new one cannot be
    # added without saying what it means.  Stated rather than inferred: the
    # summary prints `no-predicate` in the tally whether or not it happened, and
    # a verdict nobody has a case for is a verdict whose line never gets read.
    covered = {c[4] for c in AUDIT_CASES}
    missing = set(F.AUDIT_VERDICTS) - covered
    if missing:
        failures += _fail("audit_has_no_case_for",
                          f"{sorted(missing)} is in AUDIT_VERDICTS and in no "
                          f"row of AUDIT_CASES", verbose)
    print(f"formal fuzz: audit      {'PASS' if not failures else 'FAIL'} "
          f"{len(AUDIT_CASES)} verdicts (no compiler)")
    return failures


def check_run(arch, count, jobs, verbose):
    """`count` pinned indexes, end to end, and every verdict accounted for."""
    argv = [sys.executable, os.path.join(ROOT, "tools", "formal_fuzz.py"),
            "--seed", "suite", "--arch", arch, "--seeds", f"0-{count - 1}",
            "-j", str(jobs), "--work", os.path.join(ROOT, "build",
                                                    "formal-fuzz", f"suite-{arch}")]
    if verbose:
        argv.append("-v")
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    if verbose:
        print(out)
    failures = 0
    if proc.returncode != 0:
        # The tool exits 1 for an unexplained disagreement, a codegen crash or a
        # generator error, which is exactly what this asserts against; print its
        # report so the reason is the tool's own words and not a status.
        failures += _fail(f"run_{arch}", out.strip()[-3000:], verbose)

    counts = _counts(out)
    for label in ("match", "trapped", "refusal", "CPYTHON-TIMEOUT"):
        # `label in counts`, not `counts.get(label)`: the four are ALWAYS
        # printed, zero included, so their PRESENCE is the assertion and their
        # value is not.
        if label not in counts:
            failures += _fail(f"run_{arch}_printed_no_{label}_count",
                              out.strip()[-1500:], verbose)
    for label, n in sorted(counts.items()):
        if label == "CPYTHON-TIMEOUT" and n:
            failures += _fail(
                f"run_{arch}_reported_cpython_timeouts",
                f"{n} program(s) the ORACLE could not finish: the corpus has "
                f"outgrown the reference's patience, which measures the "
                f"generator's bounds and not the backend", verbose)
        elif label.startswith("generator-error"):
            failures += _fail(
                f"run_{arch}_reported_generator_errors",
                f"{n} program(s) CPython will not run: that is the oracle's "
                f"own traceback and measures the generator, not the backend",
                verbose)
        elif label.startswith(("MISMATCH", "ARM64-DIVERGES", "CODEGEN-",
                               "REFUSAL-DIVERGES", "REFUSAL-UNNAMED",
                               "REFUSAL-FALSE")):
            failures += _fail(f"run_{arch}_reported_{label}",
                              f"{n} unexplained — every disagreement in the "
                              f"known table must have reduced to it, and one "
                              f"architecture declining what another lowered, "
                              f"or a refusal that names nothing, is a finding "
                              f"whatever the known table says",
                              verbose)
    if not counts.get("match"):
        failures += _fail(f"run_{arch}_agreed_on_nothing",
                          f"a corpus of {count} programs where nothing agreed "
                          f"is a corpus that is not measuring the backend",
                          verbose)
    tally = " ".join(f"{v}={n}" for v, n in sorted(counts.items()))
    print(f"formal fuzz: run {arch:6} "
          f"{'PASS' if not failures else 'FAIL'} FAIL={failures} "
          f"({count} programs) — {tally or '?'}")
    return failures


def _counts(out):
    """The summary's own tally, read off its lines.

    A verdict name can contain a space-free `:` (`KNOWN:str_subscript`) but never
    a space, so the first two fields of each tally line are the name and the
    count. Read off the summary rather than off the exit status alone: the exit
    status says SOMETHING was wrong and this says what, and a runner that
    printed no summary would otherwise pass by printing nothing.
    """
    counts = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit() and not line.startswith(" " * 4):
            counts[parts[0]] = int(parts[1])
    return counts


#: How many pinned programs each mix is RUN for in `check_mix_builds`, and on
#: which architecture. Two programs is the smallest number that can distinguish
#: "this family builds" from "this family is refused", and ONE architecture is
#: enough because the question is about the FAMILY — the two are checked against
#: each other by the sweep, and every case in the other half of this file is
#: already run on both.
MIX_BUILD_INDEXES = 2
MIX_BUILD_ARCH = "x86_64"

#: Mixes whose constructs are NOT supposed to lower, so "no answer" is the
#: expected outcome for them and requiring one would be requiring a bug. The
#: table's shape is a MIX -> the reason it is here, because "a mix that is
#: refused" and "a mix that is refused BY DESIGN" are the same tally and only the
#: second one is allowed to sit here: the alternative reading of an all-refused
#: mix ("a family that measures nothing") is what the check below exists to
#: catch, and a doc per row is what tells the two apart.
#:
#:   `limits` — the REFUSAL half of the corpus, added because 4032 programs over
#:   the thirteen sweeps the ledger records produced 13 refusals and all 13 were
#:   one bug (`_cb0` has no home), so nothing in the corpus could measure a limit
#:   and nothing could measure a MESSAGE. Its whole job is to be refused, and
#:   what it must still produce is an AUDIT: it is the only mix that exercises
#:   `audit_refusal`, and a mix that stopped reaching a refusal would report a
#:   clean sweep while measuring nothing. `check_mix_refuses` is that check.
#:
#:   `fstrings` — `f"n={n}"` printed the literal's own SOURCE SPELLING on both
#:   architectures (exit 0) until the fuzz-3 sweep found it, and it is refused
#:   now because composition needs a buffer a `char *` has nowhere to put it in
#:   (`formal/model.py`'s `interpolated_literal_refusal`, pinned by
#:   `test_formal_run.py`'s `fstring_literal_refused`). So the mix answers with
#:   refusals BY DESIGN, and dropping it the day interpolation is implemented is
#:   what would turn this row into the hole the check is for.
#:
#: There were none before these two, and the rows above are why the small table
#: is a fact rather than a shrug: a family added to `MIXES` is a family whose
#: construct the backend lowers unless it comes with a doc saying otherwise. The
#: `field_read` row in `tools/formal_fuzz.py` is why the check exists at all —
#: 284 of 300 generated class programs were ONE refusal, which is a family that
#: measures nothing and a suite that reported numbers.
MIXES_NOT_LOWERED = {
    "limits": "the corpus's refusal half — every construct in it is outside "
              "the modelled subset, and it is the only mix that reaches "
              "`audit_refusal`",
    "fstrings": "formal/model.py:interpolated_literal_refusal (a documented "
                "refusal, pinned by test_formal_run.py)",
}


def check_mix_builds(mix, indexes, verbose):
    """Every mix produces at least one ANSWER, not only refusals.

    The generator half above proves the text is a valid differential program and
    the run half proves the verdicts are verdicts; neither can see that a whole
    construct family has quietly become refusable. A refused program still
    parses, still runs on CPython, still counts towards the run's totals, and
    reports nothing about the backend — so a mix that is 95% refused is a mix
    that finds nothing and looks exactly like a clean one.

    `generator-error` counts as a FAILURE here rather than as "not an answer":
    it is the generator's own failure (CPython rejected the text), which
    `check_generator` cannot see because it only compiles.
    """
    if mix in MIXES_NOT_LOWERED:
        return 0
    work = os.path.join(ROOT, "build", "formal-fuzz", f"builds-{mix}")
    argv = [sys.executable, os.path.join(ROOT, "tools", "formal_fuzz.py"),
            "--seed", "suite", "--arch", MIX_BUILD_ARCH, "--mix", mix,
            "--seeds", f"0-{indexes - 1}", "-j", str(indexes),
            "--work", work, "--quiet"]
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    counts = _counts(out)
    # An ANSWER is any verdict that means an image ran and said something. A
    # `KNOWN:…` disagreement counts, because the images answered and the
    # disagreement is a documented one — `strings` is mostly those, and a check
    # that required `match` would report the family that carries a known
    # divergence as a family that cannot build. A `trapped` counts too: the guard
    # stopped the program on purpose, which is an answer about the program. A
    # `refusal`, a `generator-error`, a `timeout` and a `codegen-crash` do not:
    # none of them is the backend saying what the program computes.
    answers = sum(n for k, n in counts.items()
                  if k == "match" or k == "trapped"
                  or k.startswith(("KNOWN:", "MISMATCH", "ARM64-")))
    failures = 0
    if counts.get("generator-error"):
        failures += _fail(
            f"{mix}_has_generator_errors",
            f"{counts['generator-error']} program(s) CPython will not run; the "
            f"generator half compiles nothing so this is where it shows",
            verbose)
    if not answers:
        failures += _fail(
            f"{mix}_produced_no_answer",
            f"{counts.get('refusal', 0)} refusal(s) and nothing else — a "
            f"family that is always refused measures nothing and reports "
            f"numbers anyway", verbose)
    print(f"formal fuzz: builds   {mix:9} "
          f"{'PASS' if not failures else 'FAIL'} "
          f"answers={answers}/{indexes} (1 arch, {counts.get('refusal', 0)} "
          f"refused)")
    return failures


def check_mix_refuses(mix, indexes, verbose):
    """A mix declared NOT-LOWERED still has to reach a refusal, and an audit.

    `check_mix_builds` asks whether a mix produces an ANSWER, which is the right
    question for eleven of the twelve and the wrong one for `limits`: this mix
    exists to produce REFUSALS, so the question here is whether it still
    produces them, and whether the audit has something to say about each.

    Both halves are needed. A mix that stopped reaching a refusal would report a
    clean sweep while measuring nothing — the same hole `check_mix_builds`
    exists for, one level down — and a refusal whose audit is `no-predicate`
    across the board would be a corpus that produces messages nobody reads.

    Cheaper than it looks: `check_mix_builds` is skipped for these mixes, so
    this does not add a second set of builds on top of it.
    """
    work = os.path.join(ROOT, "build", "formal-fuzz", f"refuses-{mix}")
    argv = [sys.executable, os.path.join(ROOT, "tools", "formal_fuzz.py"),
            "--seed", "suite", "--mix", mix, "--seeds", f"0-{indexes - 1}",
            "-j", str(indexes), "--max-min-steps", "10", "--work", work,
            "--quiet"]
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout or ""
    counts = _counts(out)
    audited = 0
    for line in out.splitlines():
        if line.startswith("  refusal audit:"):
            for field in line.split(":", 1)[1].split(","):
                name, _, n = field.strip().partition("=")
                if name == "true":
                    audited = int(n or 0)
    failures = 0
    if counts.get("generator-error"):
        failures += _fail(
            f"{mix}_has_generator_errors",
            f"{counts['generator-error']} program(s) CPython will not run — the "
            f"constructs in this mix are valid Python by construction, so one "
            f"that is not is the generator's arity or spelling", verbose)
    if not counts.get("refusal"):
        failures += _fail(
            f"{mix}_produced_no_refusal",
            f"{counts} — a mix declared not-lowered whose constructs now LOWER "
            f"is measuring nothing, and `MIXES_NOT_LOWERED` would be asserting a "
            f"limit that is gone", verbose)
    if not audited:
        failures += _fail(
            f"{mix}_audited_nothing",
            f"{counts.get('refusal', 0)} refusal(s) and no audit verdict of "
            f"`true`; the refusal-audit machinery is not being reached, which is "
            f"what this mix exists to reach", verbose)
    print(f"formal fuzz: refuses  {mix:9} "
          f"{'PASS' if not failures else 'FAIL'} "
          f"refusals={counts.get('refusal', 0)}/{indexes} audited-true={audited}")
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--count", type=int, default=SEEDS,
                    help=f"pinned programs to run per architecture "
                         f"(default {SEEDS})")
    ap.add_argument("--gen-indexes", type=int, default=GEN_INDEXES,
                    help=f"indexes the no-compiler generator check covers, per "
                         f"mix (default {GEN_INDEXES})")
    ap.add_argument("--arch", default="both", choices=("arm64", "x86_64", "both"))
    ap.add_argument("--mix", default=None, choices=sorted(F.MIXES),
                    help="one mix only; default is every mix")
    ap.add_argument("-j", "--jobs", type=int, default=2)
    ap.add_argument("--no-build-check", action="store_true",
                    help="skip the per-mix 'does this family BUILD' half, "
                         "which builds two programs per mix")
    args = ap.parse_args()

    print("=" * 68)
    print("FORMAL FUZZ — the generator's corpus and the runner's verdicts")
    print("=" * 68)
    mixes = [args.mix] if args.mix else sorted(F.MIXES)
    failures = check_classifier(args.verbose)
    failures += check_audit(args.verbose)
    failures += check_frame_budget(args.verbose)
    for mix in mixes:
        failures += check_generator(mix, args.gen_indexes, args.verbose)
    if not args.no_build_check:
        for mix in mixes:
            failures += check_mix_builds(mix, MIX_BUILD_INDEXES, args.verbose)
        for mix in mixes:
            if mix in MIXES_NOT_LOWERED:
                failures += check_mix_refuses(mix, args.gen_indexes // 2,
                                              args.verbose)
    arches = ("arm64", "x86_64") if args.arch == "both" else (args.arch,)
    for arch in arches:
        failures += check_run(arch, args.count, args.jobs, args.verbose)
    print()
    print(f"Results: {'PASS' if not failures else 'FAIL'} — "
          f"{failures} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())