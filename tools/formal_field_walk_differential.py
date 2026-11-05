#!/usr/bin/env python3
"""Does `formal/model.py`'s STATEMENT walk reach the same assignments as the
full walk, on every struct in this repository and the stdlib?

    python3 tools/formal_field_walk_differential.py

**The precondition `iter_statement_nodes` needs, measured rather than argued.**
`struct_receiver_stores` finds the fields a struct's methods write by walking
every method body, and it is asked once per (struct, question), so the walk
multiplies by every struct in the module: on `myinterpreter.py`, 2 245
derivations visiting 6 160 632 nodes to find the few thousand assignments they
exist for, 2.05 s of the 3.4 s left in that build.

`iter_statement_nodes` gets the same answers over ~8x fewer nodes by descending
only into list-valued fields of STATEMENT nodes and stopping at the first node
that is not one. That is sound exactly when no statement is reachable only
through a scalar field, which is a property of the parser's node set rather than
of any one program — so it is checked here, over the whole corpus, per struct,
by asking the two walks the same question and comparing the SETS.

**Why this is a tool and not only a test.** A sweep answers "does this FILE
build", which cannot count the sites a change REclassifies, and a corpus test in
the everyday gate that parses 516 files is a cost every run pays for a
conclusion that only changes when the parser does. So the corpus walk lives here,
where it can be run on demand and after any change to `fire_compiler.py`, and
`test_formal_field_walk.py` pins the instrument on sources small enough to keep
— including a hand-built node whose statement hides behind a scalar field, which
is the counterexample this whole arrangement exists to be able to SEE.

No build, no Lean, no sweep: a parse and two walks.
"""
# `collections` was imported here and read NOTHING through it, so it was
# one of the `collections` row's blocked files for the reason an absent
# module would be — a dead import blocks a file exactly as hard as a
# missing one and costs the same. `tools/formal_host_import_shapes.py`
# reads it as `DEAD` and `formal_sweep_causes.py`'s `mentions` column is
# the older measure of the same thing; see
# `bugs/FORMAL_a_call_result_field_access_has_no_representation.md` §3.
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules",
             "stage1", "stage2", "stage3"}


def parsed(path):
    try:
        with open(path) as f:
            return F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return None


def stores_full(struct_def, receivers) -> set:
    """`struct_receiver_stores`, over `iter_nodes` — the walk this replaced."""
    out = set()
    for method in M.struct_methods(struct_def):
        for node in M.iter_nodes(getattr(method, "body", None)):
            for target in M._assignment_targets(node):
                out.update(M.receiver_target_names(target, receivers))
    return out


def stores_statements(struct_def, receivers) -> set:
    """`struct_receiver_stores`, over `iter_statement_nodes` — the one in use."""
    out = set()
    for method in M.struct_methods(struct_def):
        for node in M.iter_statement_nodes(getattr(method, "body", None)):
            for target in M._assignment_targets(node):
                out.update(M.receiver_target_names(target, receivers))
    return out


def scan(path, rows, scalars, containers):
    """One file: every struct's two answers, plus both walk invariants."""
    stmts = parsed(path)
    if stmts is None:
        return
    rel = os.path.relpath(path, HERE)
    for st in M.iter_nodes(stmts):
        if not isinstance(st, F.StructDef):
            continue
        receivers = M.struct_receivers(st)
        full = stores_full(st, receivers)
        fast = stores_statements(st, receivers)
        if full != fast:
            rows.append((rel, getattr(st, "name", "?"), sorted(full - fast),
                         sorted(fast - full)))
    statements_behind_scalars(stmts, scalars, containers)


def _statements_behind_scalars(node, scalars, containers):
    if isinstance(node, (list, tuple)) or not hasattr(node, "__dataclass_fields__"):
        return
    statement = M._is_statement_node(node)
    for name in M._node_subtree_fields(node) or ():
        value = getattr(node, name, None)
        if isinstance(value, (list, tuple)):
            if not statement:
                for x in value:
                    if M._is_statement_node(x):
                        containers.add(type(node).__name__ + "." + name)
        elif value is not None and M._is_statement_node(value):
            scalars.add(type(node).__name__ + "." + name)


def statements_behind_scalars(stmts, scalars, containers):
    """Both invariants, measured: what holds statements, and what hides one.

    `containers` is what `formal/model.py`'s `_STATEMENT_CONTAINERS` has to
    name for the walk to be sound — a non-statement node with a LIST field full of
    statements — so printing it is how the tuple is checked against the parser
    rather than against the day it was written.
    """
    for node in M.iter_nodes(stmts):
        _statements_behind_scalars(node, scalars, containers)


def corpus():
    from module_loader import STDLIB_PATH
    roots = [HERE, os.path.join(STDLIB_PATH, "std")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith(".py") or fn.endswith(".mojo"):
                    yield os.path.join(dirpath, fn)


def main():
    rows, scalars, containers = [], set(), set()
    files = 0
    for path in corpus():
        files += 1
        scan(path, rows, scalars, containers)
    print("parsed %d files" % files)
    print("statements reachable only through a SCALAR field: %d %s"
          % (len(scalars), sorted(scalars) if scalars else ""))
    print("non-statement nodes holding statements in a LIST field — what "
          "`_STATEMENT_CONTAINERS` has to name:")
    for name in sorted(containers):
        named = name.split(".")[0] in {t.__name__ for t in M._STATEMENT_CONTAINERS}
        print("    %-28s %s" % (name, "in the tuple" if named else "MISSING"))
    if any(name.split(".")[0] not in {t.__name__ for t in M._STATEMENT_CONTAINERS}
           for name in containers):
        print("  a container type is missing from the tuple: add it, or the walk "
              "loses an assignment")
        return 1
    if rows:
        print("DIFFERENCES: %d structs" % len(rows))
        for rel, name, missing, extra in rows[:40]:
            print("  %-56s %-24s misses=%s adds=%s"
                  % (rel, name, missing, extra))
        return 1
    print("no differences: every struct's receiver-store set is the same "
          "under both walks")
    return 0


if __name__ == "__main__":
    sys.exit(main())