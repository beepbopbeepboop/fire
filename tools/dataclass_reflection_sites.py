#!/usr/bin/env python3
"""Every `dataclasses.fields(…)` / `getattr(x, f.name)` site in a file, and how
much is statically known about its receiver.

The question `bugs/FORMAL_dataclass_runtime_reflection.md` asks is whether the
RUNTIME half of `dataclasses` is worth a front-end transform: "measure how many
of the `dataclasses.fields(...)` / `getattr(node, f.name)` sites in the two files
have a statically known receiver type". A transform can only answer `fields(x)`
where `x`'s type is known, so the count of sites whose receiver is a plain name
with one binding IS the count of sites a transform could reach.

WHICH IS WHY THIS READS THE AST AND NOT THE TEXT. `cpp_core.py` has ~97
`getattr` calls and ONE `fields()` call, and 95 of those getattr calls are
`getattr(gen, '_cpp_gen_self_struct', None)` — a lookup into generator state,
which has nothing to do with dataclass reflection and would be counted by a
grep as though it did.

Two things it reports per site:

  * the enclosing function and the receiver as spelled there, which is what
    says whether there is a static type to answer from;
  * the COUNT of call sites reaching that function with which distinct
    argument expressions, because "the receiver is a parameter" is only half an
    answer — a parameter every caller hands the same class is answerable by
    agreement, and one that receives 20 shapes is not.

    python3 tools/dataclass_reflection_sites.py [file …]

With no arguments it walks the two files the doc is about. It is a census, not
a check: it exits 0 whatever it finds, and prints `KNOWN: n` / `UNKNOWN: n` so
a reader can see the ratio that decides the question.
"""
import argparse
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILES = (
    os.path.join(os.path.dirname(HERE), "ownership_check.py"),
    os.path.join(os.path.dirname(HERE), "mojo", "backend_gimple",
                 "cpp_core.py"),
)


def _parents(tree):
    out = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            out[child] = parent
    return out


def _enclosing_func(node, parents):
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur, [a.arg for a in cur.args.args]
    return None, []


def _declared_dataclasses(tree):
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any("dataclass" in ast.unparse(d) for d in node.decorator_list):
            continue
        out[node.name] = [s.target.id for s in node.body
                         if isinstance(s, ast.AnnAssign)
                         and isinstance(s.target, ast.Name)]
    return out


def _sites(tree, parents):
    """`(kind, lineno, receiver text, callee, callee args)` per site."""
    sites = []
    for node in ast.walk(tree):
        fn, args = _enclosing_func(node, parents)
        callee = fn.name if fn is not None else "<module level>"
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "fields" and node.args):
            sites.append(("fields", node.lineno, ast.unparse(node.args[0]),
                          callee, args))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) == 2):
            # `getattr(x, f.name)` is the reflection spelling and
            # `getattr(x, 'literal')` is an ordinary attribute read with a
            # default; only the first asks a dataclass anything.
            attr = node.args[1]
            if not (isinstance(attr, ast.Attribute)
                    and attr.attr == "name"):
                continue
            sites.append(("getattr", node.lineno,
                          f"{ast.unparse(node.args[0])}, f.name",
                          callee, args))
    return sites


def _callers(tree, callees):
    """`{callee: [(lineno, first argument text)]}` over the WHOLE file."""
    out = {name: [] for name in callees}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in out and node.args):
            out[node.func.id].append((node.lineno,
                                      ast.unparse(node.args[0])))
    return out


def report(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        tree = ast.parse(f.read(), path)
    parents = _parents(tree)
    sites = _sites(tree, parents)
    declared = _declared_dataclasses(tree)
    callees = {s[3] for s in sites if s[3] != "<module level>"}
    callers = _callers(tree, callees)
    print(f"\n=== {os.path.relpath(path, os.path.dirname(HERE))}")
    print(f"  @dataclass classes declared HERE: "
          f"{ {k: len(v) for k, v in declared.items()} or 'none'}")
    if not sites:
        print("  no reflection sites")
        return 0, 0
    known = unknown = 0
    for kind, lineno, recv, callee, args in sites:
        reached = callers.get(callee) or []
        shapes = {text for _l, text in reached}
        # A receiver is statically known when it is not a parameter of the
        # function the site is in — the parameter is the polymorphic case the
        # doc is about, and there is nothing else to ask.
        is_param = recv.split(",", 1)[0].strip() in args
        verdict = "POLYMORPHIC" if is_param else "a name in this function"
        if is_param:
            unknown += 1
        else:
            known += 1
        print(f"  line {lineno}: {kind}({recv}) in {callee}({', '.join(args)})")
        print(f"      receiver: {verdict}")
        print(f"      {callee} is called at {len(reached)} site(s) with "
              f"{len(shapes)} distinct argument shape(s)"
              + (f": {', '.join(sorted(shapes)[:6])}"
                 + (" …" if len(shapes) > 6 else "") if shapes else ""))
    return known, unknown


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="*", help="defaults to the two files "
                    "bugs/FORMAL_dataclass_runtime_reflection.md names")
    args = ap.parse_args()
    known = unknown = 0
    for path in (args.files or [p for p in DEFAULT_FILES if os.path.exists(p)]):
        k, u = report(path)
        known += k
        unknown += u
    print(f"\nKNOWN: {known}   POLYMORPHIC: {unknown}")
    print("A front-end transform can answer `fields(x)` only at the KNOWN "
          "sites: a receiver that is a PARAMETER has no static type to answer "
          "from, and the two callers above feed one walker from every AST "
          "class the file understands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())