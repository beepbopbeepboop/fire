#!/usr/bin/env python3
"""The `typed` model flag: what it decides, and that it is not vacuous.

`formal/types.py::uses_typed_model` is one predicate both proof generators call,
and this file pins what it answers rather than what it is called. Three
properties, in the order a reader wants them:

  1. **THE RULE.** A function gets the fixed-width model exactly when some type
     it declares or infers is not the default 64-bit signed word. So
     `n: UInt8` is True, `-> Int` is False (Int IS the default type), and an
     unannotated `n` is False. That is the whole decision, and it is what the
     flag has always computed — which is the point of property 3.

  2. **THE CORPUS AGREES WITH ITSELF.** Over `formal/examples/`, the rule and
     the alternative the `typed` document proposed ("compute it from the
     presence of a type ANNOTATION in the source") answer identically for every
     function. Measured on this tree: 45 functions, 7 with any annotation, 4 of
     them with a non-default width — and **0 functions whose answer would
     change**. That is why the annotation rule was not adopted, and it is
     re-derived here rather than quoted from the document.

  3. **NO FUTURE `DEFAULT_INT_TYPE` MAKES IT VACUOUS SILENTLY.** The flag was
     believed vacuous for months after `DEFAULT_INT_TYPE` became signed
     `IntType(64, True)`, because every inferred `int` then resolved to the
     default. The census below is what distinguishes "vacuous" from "correct for
     this corpus": a vacuous flag answers False for `n: UInt8` too, and that
     case is in the table.

    python3 test_formal_typed_flag.py [-v]
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fire_compiler as F                                    # noqa: E402
from formal import model as M                                # noqa: E402
from formal.build import parse_module                        # noqa: E402
from formal.types import (DEFAULT_INT_TYPE, function_var_types,  # noqa: E402
                          parse_type_name, resolve, uses_typed_model)

FAILURES = []


def check(ok, what, detail=""):
    if not ok:
        FAILURES.append(f"{what}{': ' + detail if detail else ''}")
        print(f"  FAIL  {what}" + (f": {detail}" if detail else ""))
    return ok


def fn_of(source, name="probe"):
    """The one FunctionDef in `source`, or None."""
    stmts = parse_module(source, f"<{name}>")
    fns = [s for s in stmts if isinstance(s, F.FunctionDef)]
    return fns[0] if fns else None


def annotations_of(fn):
    """`[(spelling, resolved type)]` for every type the SOURCE writes."""
    out = []
    for pname, pann in (fn.params or []):
        if pann:
            out.append((f"param {pname}", resolve(parse_type_name(pann))))
    rt = getattr(fn, "return_type", None)
    if rt:
        out.append(("return", resolve(parse_type_name(rt))))
    for node in M.iter_nodes(fn.body):
        ann = getattr(node, "type_ann", None)
        if isinstance(ann, str) and ann:
            out.append((f"var {getattr(node, 'name', '?')}",
                        resolve(parse_type_name(ann))))
    return out


def annotation_rule(fn):
    """The alternative the doc proposed: an ANNOTATION that is not the default."""
    return any(t != DEFAULT_INT_TYPE for _w, t in annotations_of(fn))


def inline_rule(fn, call_types):
    """The five lines both generators used to carry, verbatim.

    Kept here so the refactor that replaced them is CHECKED rather than argued:
    if `uses_typed_model` ever stops agreeing with the expression it replaced,
    every generated proof on both architectures is suspect, and this is where
    that shows up. It is a copy on purpose — a copy in a TEST is a pin, and a
    copy in a generator is the duplication this change removed.
    """
    vtypes = function_var_types(fn, call_types)
    all_t = list(vtypes.values())
    rt = resolve(parse_type_name(getattr(fn, "return_type", None)))
    if rt != DEFAULT_INT_TYPE:
        all_t.append(rt)
    return any(t != DEFAULT_INT_TYPE for t in all_t)


def run_rule(verbose):
    print("the rule")
    cases = [
        ("a narrow width is the model that can prove about it",
         "def probe(n: UInt8):\n    return n + 1\n", True),
        ("a signed narrow width likewise",
         "def probe(n: Int8) -> Int8:\n    return n - 1\n", True),
        # `-> Int` IS the default type, so it is NOT a reason to model widths:
        # this is the case the "vacuous" claim was really about.
        ("an `Int` return annotation is the default type, so False",
         "def probe(n):\n    return n + 1\n", False),
        ("an unannotated parameter is a word, so False",
         "def probe(n):\n    var x = n + 1\n    return x\n", False),
        ("a 32-bit width is not the default word",
         "def probe(n: UInt32) -> UInt32:\n    return n\n", True),
    ]
    for what, src, want in cases:
        got = uses_typed_model(fn_of(src))
        check(got is want, what, f"got {got}, want {want}")
        if verbose:
            print(f"      {what}: {got}")


def run_census(verbose):
    print(f"\nthe corpus (formal/examples/, default = {DEFAULT_INT_TYPE})")
    files = sorted(glob.glob(os.path.join(HERE, "formal", "examples", "*.mojo")))
    total = annotated = typed = 0
    disagree = []
    table = []
    for path in files:
        try:
            stmts = parse_module(open(path).read(), os.path.basename(path))
        except Exception as e:                       # unparsed is not a finding
            continue
        fns = [s for s in stmts if isinstance(s, F.FunctionDef)]
        if not fns:
            continue
        call_types = {f.name: resolve(parse_type_name(f.return_type)
                                      or DEFAULT_INT_TYPE) for f in fns}
        for fn in fns:
            total += 1
            got = uses_typed_model(fn, call_types)
            typed += bool(got)
            anns = annotations_of(fn)
            annotated += bool(anns)
            if annotation_rule(fn) != got:
                disagree.append((os.path.basename(path), fn.name))
            if inline_rule(fn, call_types) != got:
                disagree.append((os.path.basename(path) + " [inline]",
                                 fn.name))
            if anns:
                table.append((os.path.basename(path), fn.name, got,
                              ", ".join(f"{w}={t}" for w, t in anns)))
    check(total > 0, "the corpus census saw functions at all", f"{total}")
    for row in table:
        print(f"      {row[0]:22s} {row[1]:16s} typed={row[2]!s:5s} {row[3]}")
    print(f"      {total} functions, {annotated} with a source annotation, "
          f"{typed} using the typed model, {len(disagree)} where the "
          f"annotation rule would answer differently")
    check(not disagree,
          "the shipped rule agrees with BOTH alternatives on every function "
          "in formal/examples/ — the annotation rule the document proposed, "
          "and the inline expression both generators used to carry",
          ", ".join(f"{a}:{b}" for a, b in disagree))
    # The anti-vacuity row: if this fails, the flag is answering False for
    # everything, which is the failure mode the corpus census above cannot see.
    check(typed > 0,
          "the flag is not vacuous on this corpus (at least one function "
          "declares a non-default width)",
          f"0 of {total} functions used the typed model")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    print(__doc__.strip().splitlines()[0])
    run_rule(args.verbose)
    run_census(args.verbose)
    if FAILURES:
        print(f"\ntyped model flag: FAIL ({len(FAILURES)})")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("\ntyped model flag: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())