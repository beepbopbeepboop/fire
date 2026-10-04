#!/usr/bin/env python3
"""How many corpus subscripts read a PARAMETER nothing declares, and what the
module's own call sites pass to it.

    python3 tools/formal_untyped_param_subscript_census.py

**The measurement `bugs/FORMAL_a_subscript_through_an_untyped_PARAMETER_is_a_blob_
element_and_through_an_annotated_pointer_is_a_word.md` §next-step 1 asks for,
and the one that decides whether a call site's own answer for its argument can
replace the callee's annotation as the thing that chooses `p + i*width` over
`p + 8 + i*8`.** Within one image every call site of the callee is in the same
function tree, so the fact the callee cannot see — what its caller already does
with that name — IS derivable.

It asks `formal/model.py`'s `parameter_call_site_pointers` — the real function,
with the real `subscript_base_lowering` and the real `pointer_pointee` behind
it — so the three numbers it prints are the three cases that function answers
differently, and nothing here re-implements a decision:

  * **BECOMES-LOAD** — every call site reads its argument as MEMORY, so the
    parameter is memory too and the callee's subscript moves from `base + 8 +
    i*8` to `base + i*width`. This is the bug the change fixes.
  * **DISAGREE** — the call sites read it two ways, which is
    `frame_holder_disagreement_refusal`'s shape one layer down: one parameter,
    two kinds of value, and any single answer is wrong somewhere.
  * **UNCHANGED** — no call site to ask, only the callee's own recursion, or
    every site reading it as a container already. The container reading is the
    answer `tools/formal_unstated_base_subscript_census.py` measured as not
    refusable.

The `caller` column prints how the caller itself indexes that name, which is
the invariant the answer is drawn from: one value, one convention, wherever the
name is written.

No build, no Lean and no sweep, for the reason
`tools/formal_unstated_base_subscript_census.py` gives: a sweep answers "does
this FILE build", which cannot count the sites a lowering change RECLASSIFIES.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules"}


def parsed(path):
    try:
        with open(path) as f:
            return F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return None


def param_name_at(fn, position):
    """The name at `position` in `fn`'s parameter list, or None."""
    params = list(getattr(fn, "params", None) or [])
    if position >= len(params):
        return None
    p = params[position]
    if isinstance(p, (tuple, list)):
        return p[0] or None
    return p if isinstance(p, str) else None


def declared_annotation(fn, name):
    """The annotation `fn` gives `name`, or None — the callee's own spelling."""
    for p in (list(getattr(fn, "params", None) or [])):
        if isinstance(p, (tuple, list)) and len(p) > 1 and p[0] == name \
                and isinstance(p[1], str) and p[1].strip():
            return p[1]
    return None


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
            name = f.name if isinstance(f, F.IdentExpr) else (
                f.member if isinstance(f, F.MemberExpr) else None)
            if name != callee_name:
                continue
            out.append((fn, list(getattr(node, "args", None) or [])))
    return out


def classify_site(caller, arg, decls, functions):
    """What the CALLER's own answer for `arg` is — the convention the value has
    where the caller holds it, which is what a parameter inherits.

    `"load:<w>"` is memory at a width; `"blob"` is the container walk; `"?"` is a
    refusal, which says nothing about the value.
    """
    try:
        shape, width, _signed, _why = M.subscript_base_lowering(
            caller, arg, decls, functions, decls)
    except Exception:
        return "?"
    if shape is None:
        return "?"
    return "blob" if shape == "blob" else f"{shape}:{width}"


def caller_subscripts(caller, name):
    """How the CALLER spells `name[i]`, printed beside the verdict.

    Not part of the answer — the answer is `classify_site` — but it is the
    evidence a reader wants next to it: the same convention at the call site and
    in the callee is what "one value, one convention" means, and a `blob`
    argument whose caller indexes it as memory is the disagreement the refusal
    is about.
    """
    shapes = set()
    for node in M.iter_nodes(getattr(caller, "body", None) or []):
        if not isinstance(node, F.SubscriptExpr):
            continue
        obj = node.obj
        if isinstance(obj, F.IdentExpr) and obj.name == name:
            try:
                shape = M.subscript_base_lowering(caller, obj, {}, {}, {})[0]
            except Exception:
                shape = None
            shapes.add(shape or "?")
    if not shapes:
        return "never"
    if shapes == {"blob"}:
        return "blob"
    if "blob" in shapes:
        return "mixed"
    return "load"


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
            if not isinstance(node, F.SubscriptExpr) \
                    or isinstance(node.index, F.SliceExpr):
                continue
            obj = node.obj
            if not isinstance(obj, F.IdentExpr):
                continue
            if declared_annotation(fn, obj.name) is not None:
                continue
            try:
                if M.subscript_base_lowering(fn, obj, decls, functions,
                                             decls)[0] != "blob":
                    continue
            except Exception:
                continue
            derived = M.parameter_call_site_pointers(fn, obj.name, decls,
                                                     functions, decls)
            if derived is None:
                verdict, classes = "UNCHANGED", ()
            elif derived[0] == "disagree":
                verdict, classes = "DISAGREE", tuple(
                    sorted(f"{k[0]}:{k[1]}" for k in derived[1]))
            else:
                verdict = "BECOMES-LOAD"
                classes = (f"{derived[0]}:{derived[1]}",)
            sites, subs = [], []
            for caller, args in call_sites(stmts, fn.name):
                position = param_position(fn, obj.name)
                if position is None or position >= len(args):
                    continue
                sites.append(classify_site(caller, args[position], decls,
                                           functions))
                subs.append(caller_subscripts(caller, args[position].name)
                            if isinstance(args[position], F.IdentExpr) else "expr")
            rows.append((rel, fn.name, obj.name, verdict,
                         tuple(sorted(set(sites))), tuple(sorted(set(subs))),
                         len(call_sites(stmts, fn.name))))


def param_position(fn, name):
    for i, p in enumerate(list(getattr(fn, "params", None) or [])):
        if (p[0] if isinstance(p, (tuple, list)) else p) == name:
            return i
    return None


def main():
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
        print("── %-9s %d parameter-subscript sites in %d files"
              % (label, len(rows), len({r[0] for r in rows})))
        for v in ("BECOMES-LOAD", "DISAGREE", "UNCHANGED"):
            print("   %-14s %d" % (v, sum(1 for r in rows if r[3] == v)))
        for r in rows:
            if r[3] != "UNCHANGED":
                print("     %-46s %s(%s) -> %s  sites=%s caller=%s (%d call sites)"
                      % (r[0], r[1], r[2], r[3], ",".join(r[4]),
                         ",".join(r[5]), r[6]))
        print()
        allrows.extend(rows)
    print("TOTAL %d sites in %d .mojo files" % (len(allrows), files))
    for v in ("BECOMES-LOAD", "DISAGREE", "UNCHANGED"):
        print("  %-14s %d" % (v, sum(1 for r in allrows if r[3] == v)))
    return 0


if __name__ == "__main__":
    sys.exit(main())