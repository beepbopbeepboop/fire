#!/usr/bin/env python3
"""How many corpus `value()`/`unsafe_value()` sites read through a PARAMETER
nothing declares, and what this image's call sites pass to it.

    python3 tools/formal_untyped_param_deref_census.py

**The sibling of `tools/formal_untyped_param_subscript_census.py`, and the same
measurement for the DEREFERENCE.** That tool asked whether a call site's own
answer for its argument can replace the callee's annotation as the thing that
chooses `p + i*width` over `p + 8 + i*8`; this one asks the same question of
`p.value()`, where the answer is a load's WIDTH rather than an element address,
and where the pointee is what the pointer value model
(`formal/model.py::dereference_lowering`) refuses without.

It asks the real functions — `formal/model.py`'s
`parameter_call_site_pointees` over the real `pointer_pointee`, with the real
`POINTEE_WIDTHS` behind it — so the four verdicts it prints are the four answers
that function can give, and nothing here re-implements a decision:

  * **ANSWERED** — every call site establishes a pointee and they agree, so the
    load is emitted at that width.  Before this the site was refused with the
    four-questions sentence, which is the 14-of-47 `unsafe_value` sites
    `bugs/FORMAL_pointer_value_model.md` §9 names as "a pointer that crossed a
    call boundary and lost its pointee on the way".
  * **DISAGREE** — the sites establish two pointees, which is
    `frame_holder_disagreement_refusal`'s shape one layer down.
  * **SILENT** — a site this image cannot place sits beside one it can, which is
    the blob hazard the sibling records and this one refuses: a list is a frame
    whose FIRST word is its count, so a width from the sites that answer would be
    a guess about the one that does not.
  * **UNCHANGED** — nothing to decide: the parameter is declared (the
    declaration already won), there is no call site in this file, only the
    callee's own recursion, or the derivation is a cycle.

The `width` column on an ANSWERED row is the width the load would be emitted at,
and it is printed from `POINTEE_WIDTHS` rather than counted here, so a reader can
see that a `UInt8` row changes nothing about the emitted instruction — which is
the invariant the pointer value model was built to keep.

Its sibling's own caveat is this one's: a call from ANOTHER image is invisible
here, so an exported function's unannotated parameter keeps the refusal, and this
census says nothing about how many of those there are.

No build, no Lean and no sweep: a sweep answers "does this FILE build", which
cannot count the sites a lowering change reclassifies.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules"}
DEREF_METHODS = set(M.DEREFERENCE_TRY_NAMES)


def parsed(path):
    try:
        with open(path) as f:
            return F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return None


def param_position(fn, name):
    """The 0-based position of the parameter spelled `name`, or None."""
    for i, p in enumerate(list(getattr(fn, "params", None) or [])):
        if (p[0] if isinstance(p, (tuple, list)) else p) == name:
            return i
    return None


def declared(fn, name):
    """The annotation `fn`'s OWN parameter list gives `name`, or None — the one
    reader (`model.declared_parameter_annotation`) rather than a second loop."""
    return M.declared_parameter_annotation(fn, name)


def call_sites(stmts, callee_name):
    """`(caller, args)` for every call to `callee_name` in this module."""
    out = []
    for fn in M.iter_nodes(stmts):
        if not isinstance(fn, F.FunctionDef):
            continue
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.CallExpr):
                continue
            f = node.func
            name = f.name if isinstance(f, F.IdentExpr) else None
            if name != callee_name:
                continue
            out.append((fn, list(getattr(node, "args", None) or [])))
    return out


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
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.MemberExpr) \
                    or node.func.member not in DEREF_METHODS:
                continue
            obj = node.func.obj
            names = [p[0] if isinstance(p, (tuple, list)) else p
                     for p in (getattr(fn, "params", None) or [])]
            if not isinstance(obj, F.IdentExpr) or obj.name not in names:
                continue
            if declared(fn, obj.name) is not None:
                continue
            try:
                derived = M.parameter_call_site_pointees(
                    fn, obj.name, decls, functions, decls)
            except Exception:
                derived = None
            nsites = len(call_sites(stmts, fn.name))
            if derived is None:
                verdict, width, pointees = "UNCHANGED", "", ()
            elif derived[0] == "pointee":
                base = derived[1]
                if base in M.POINTEES_REFUSED:
                    verdict, width = "UNCHANGED", f"{base}:refused"
                    pointees = (base,)
                elif base in M.POINTEE_WIDTHS:
                    verdict, width = "ANSWERED", f"{base}:{M.POINTEE_WIDTHS[base][0]}"
                    pointees = (base,)
                else:
                    verdict, width = "UNCHANGED", f"{base}:no-width"
                    pointees = (base,)
            elif derived[0] == "disagree":
                verdict, width = "DISAGREE", ""
                pointees = tuple(sorted(derived[1]))
            else:
                verdict, width = "SILENT", ""
                pointees = ()
            rows.append((rel, fn.name, obj.name, verdict, width, pointees,
                         nsites, node.func.member))


def main():
    show_all = "--all" in sys.argv[1:]
    from module_loader import STDLIB_PATH
    roots = [(os.path.join(HERE, "formal", "hostmods"), "hostmods"),
             (os.path.join(HERE, "formal", "examples"), "examples"),
             (HERE, "repo"),
             (os.path.join(STDLIB_PATH, "std"), "stdlib")]
    allrows, files = [], 0
    for root, label in roots:
        if not os.path.isdir(root):
            continue
        rows = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith(".mojo"):
                    files += 1
                    scan(os.path.join(dirpath, fn), rows)
        print("── %-9s %d parameter-dereference sites in %d files"
              % (label, len(rows), len({r[0] for r in rows})))
        for v in ("ANSWERED", "DISAGREE", "SILENT", "UNCHANGED"):
            print("   %-14s %d" % (v, sum(1 for r in rows if r[3] == v)))
        print("   of which a method RECEIVER (`self.…`): %d"
              % sum(1 for r in rows if r[2] == "self"))
        for r in rows:
            if r[3] != "UNCHANGED" or show_all:
                print("     %-46s %s(%s).%s() -> %s %s pointees=%s "
                      "(%d call sites)"
                      % (r[0], r[1], r[2], r[7], r[3], r[4], ",".join(r[5]),
                         r[6]))
        print()
        allrows.extend(rows)
    print("TOTAL %d sites in %d .mojo files" % (len(allrows), files))
    for v in ("ANSWERED", "DISAGREE", "SILENT", "UNCHANGED"):
        print("  %-14s %d" % (v, sum(1 for r in allrows if r[3] == v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())