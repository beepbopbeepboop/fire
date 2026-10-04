#!/usr/bin/env python3
"""How many corpus subscripts take the BLOB reading on a base nothing establishes,
and what the base is.

    python3 tools/formal_unstated_base_subscript_census.py

**The question `bugs/FORMAL_a_subscript_of_an_unannotated_pointer_parameter_
reads_the_next_word.md` needs answered before anything is changed.**
`formal/model.py`'s `subscript_base_lowering` routes `obj[i]` three ways: a
`load` at the pointee's width when the base is established to be a pointer, a
refusal when it is a pointer whose pointee has no width, and — for every base
whose kind nothing establishes — the **blob** reading, where element `i` is at
`base + 8 + 8*count`. That third answer is right for a list and WRONG BY ONE
WHOLE ELEMENT for a word that happens to hold an address: the blob's first word
is its count, and an address has no count there.

Its own docstring states the trade and then declines to measure it:

> What is deliberately NOT refused: a base whose kind nothing establishes. […]
> "refuse every unestablished base" would refuse every `p[i]` where `p` came
> from a caller. Measured over the 395 `.mojo` files of the sweep corpus that is
> ~2 200 sites whose base is a word, most of them `List`/`Fence`/SIMD
> type-parameter subscripts that are refused further down the same path anyway.

**This is that measurement, and it is the number a fix has to beat.** Done
WITHOUT a sweep, for the reason `tools/formal_frame_field_census.py` gives: a
sweep answers "does this FILE build", which is the wrong question for a change
to a lowering rule — a file refused for a host import never reaches the rule, so
a sweep can only count refusals the change adds, never the sites it reclassifies.

**Every count here is an UPPER BOUND, and the direction is stated because it
decides how the number is read.** The instrument asks the real
`subscript_base_lowering` and the real `model.ValueKinds` on each parsed file, so
for the sites it can classify without a backend's `declared_kind` /
`ctor_field_value` hooks it is exact; those hooks can only ADD container
classifications, so the exposure is at most what is printed here and at least the
`kind is NOTHING` subset, which is the part nothing else in the image speaks for.
The split by base KIND is the useful half: a `list:…` base is the blob reading
being RIGHT, and only the others are the guess.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M
from formal.types import STRING_TYPE_NAMES, TYPE_NAMES

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules"}


def parsed(path):
    try:
        with open(path) as f:
            return F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return None


def base_shape(node):
    """How the base is SPELLED, which is what a reader can act on."""
    obj = node.obj
    if isinstance(obj, F.IdentExpr):
        return "a name"
    if isinstance(obj, F.CallExpr):
        return "a call result"
    if isinstance(obj, F.MemberExpr):
        return "a field read"
    if isinstance(obj, F.SubscriptExpr):
        return "a subscript"
    return type(obj).__name__


def scan(path, rows):
    stmts = parsed(path)
    if stmts is None:
        return
    decls = {getattr(s, "name", None): s for s in stmts
             if isinstance(s, F.StructDef)}
    functions = {getattr(f, "name", None): f for f in M.iter_nodes(stmts)
                 if isinstance(f, F.FunctionDef)}
    rel = os.path.relpath(path, HERE)
    for fn in M.iter_nodes(stmts):
        if not isinstance(fn, F.FunctionDef):
            continue
        try:
            vk = M.ValueKinds(fn, int_names=TYPE_NAMES,
                              string_names=STRING_TYPE_NAMES,
                              slot_key=lambda expr: None)
        except Exception:
            continue
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.SubscriptExpr):
                continue
            if isinstance(node.index, F.SliceExpr):
                continue
            try:
                shape, _w, _s, _why = M.subscript_base_lowering(
                    fn, node.obj, decls, functions, decls)
                kind = vk.kind_of(node.obj)
            except Exception:
                continue
            if shape != "blob":
                continue
            rows.append((rel, fn.name, getattr(node, "line", None),
                         node.obj.name if isinstance(node.obj, F.IdentExpr)
                         else "?", base_shape(node), kind or "NOTHING",
                         M.is_list_kind(kind)))


def main():
    from module_loader import STDLIB_PATH
    roots = [HERE, os.path.join(STDLIB_PATH, "std")]
    rows = []
    files = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith(".mojo"):
                    files += 1
                    scan(os.path.join(dirpath, fn), rows)
    guesses = [r for r in rows if not r[6]]
    print("scanned %d .mojo files" % files)
    print("subscripts that take the BLOB reading: %d sites in %d files"
          % (len(rows), len({r[0] for r in rows})))
    print("…whose base is a LIST, so the reading is RIGHT: %d"
          % (len(rows) - len(guesses)))
    print("…whose base is NOT a list — THE EXPOSURE, an upper bound: %d sites "
          "in %d files" % (len(guesses), len({r[0] for r in guesses})))
    print()
    print("the exposure, by what the base's kind is:")
    for k, n in collections.Counter(r[5] for r in guesses).most_common():
        print("  %-24s %4d" % (k, n))
    print()
    print("the exposure, by how the base is spelled:")
    for k, n in collections.Counter(r[4] for r in guesses).most_common():
        print("  %-24s %4d" % (k, n))
    print()
    by_file = collections.Counter(r[0] for r in guesses)
    print("the exposure, by file (the twenty largest):")
    for f, n in by_file.most_common(20):
        print("  %-58s %4d" % (f, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())