#!/usr/bin/env python3
"""How many corpus sites store a frame address into a FIELD, and of what shape.

    python3 tools/formal_frame_field_census.py

The measurement `bugs/FORMAL_receiver_stored_in_a_field.md` asks for before its
row A is attempted ("lift the field-store branch behind a temporary guard,
re-sweep the 24, and record where each lands"), done WITHOUT a sweep: parse plus
one walk per method, over this repository and the stdlib.

**Why not the sweep.** A sweep answers "does this FILE build", which is the
wrong question for a check that is one of six late checks in a pipeline: a file
refused for a host import never reaches the holder-use walk, and a file refused
by an earlier check is invisible to it. The same reasoning, and the same
instrument, as `bugs/FORMAL_read_before_store_what_is_left.md`'s census.

**What counts as a site.** `formal/build.py`'s `_refuse_holder_use` fires when a
field store's right-hand side is a BARE NAME that holds a frame. "Holds a frame"
is the refusal's own evidence — the holder set, `fn._frame_holders` — which is
DERIVED and so exists only for a file that survives every earlier check. This
census reads the DECLARATIONS instead: a name holds a frame if it is a
parameter annotated with a multi-field struct of its own file, or is assigned
from a construction of one.

So the count is an UPPER BOUND on the sites, in the same direction as the
refusal census's `FILES BLOCKED`, and for the same reason. The alternative
reading is worse than useless rather than merely loose: a first cut of this
census counted a name that has a METHOD CALLED ON IT, and this repository's own
source calls `.strip()` on strings and `.keys()` on dicts all day — 52 sites in
19 files, of which 28 were a word. Both filters are named here because that is
the mistake a syntactic census of this shape invites.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules"}


def param_names(fn):
    out = set()
    for n, _t in M.incoming_args(fn):
        if isinstance(n, str):
            out.add(n.lstrip("*").strip())
    return out


def root_name(node):
    while isinstance(node, (F.MemberExpr, F.SubscriptExpr)):
        node = node.obj
    return node.name if isinstance(node, F.IdentExpr) else None


def one_field(name, decls):
    st = decls.get(name)
    return st is not None and M.struct_is_one_field(st)


def frame_bound_names(fn, struct_names, decls):
    """Names this function can hold a MULTI-FIELD struct's frame address in.

    Two sources, and both are declarations rather than guesses:

      * a parameter whose ANNOTATION names a multi-field struct of this file —
        the receiver of one arrives as an address of a frame;
      * a name assigned from a CONSTRUCTION of one (`var q = R()`, `q = R()`,
        `q = other_struct_name`) — that is a fresh frame, and its address is what
        the name then holds.

    A name that merely has a method called on it is NOT one: this repository's
    own source calls `.strip()` on strings and `.keys()` on dicts all day, and a
    first cut of this census that used "used as a receiver" reported 52 sites of
    which 28 were a word. That is the same over-approximation the sweep's
    `FILES BLOCKED` column warns about, one level down.
    """
    out = set()
    for p in (getattr(fn, "params", None) or ()):
        pname, ann = (p[0], p[1]) if isinstance(p, (tuple, list)) else (p, None)
        base = M.annotation_base_name(ann) if ann else None
        if base in struct_names and not one_field(base, decls):
            out.add(pname)
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = (node.target if isinstance(node, F.AssignStmt)
                  else getattr(node, "name", None))
        name = target.name if isinstance(target, F.IdentExpr) else (
            target if isinstance(target, str) else None)
        if not name:
            continue
        value = getattr(node, "value", None)
        if not isinstance(value, F.CallExpr):
            continue
        callee = M.call_callee_name(value.func)
        if callee in struct_names and not one_field(callee, decls):
            out.add(name)
    return out


def local_names(fn):
    out = set()
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if isinstance(node, F.VarDecl) and isinstance(node.name, str):
            out.add(node.name)
    return out


def scan(path, rows):
    try:
        with open(path) as f:
            stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return
    decls = {getattr(s, "name", None): s for s in stmts
             if isinstance(s, F.StructDef)}
    struct_names = set(decls)
    for fn in M.iter_nodes(stmts):
        if not isinstance(fn, F.FunctionDef):
            continue
        pn = param_names(fn)
        recv_used = frame_bound_names(fn, struct_names, decls)
        locals_ = local_names(fn) - pn
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.AssignStmt):
                continue
            tgt, val = node.target, node.value
            if not isinstance(tgt, F.MemberExpr):
                continue
            if not isinstance(val, F.IdentExpr):
                continue
            root = root_name(tgt)
            if root not in pn:              # not `self.f = x`
                continue
            if val.name not in recv_used:   # not a frame-holding name
                continue
            if val.name in pn:
                kind = "parameter"
            elif val.name in locals_:
                kind = "local"
            else:
                kind = "other"
            rows.append((os.path.relpath(path, HERE), fn.name,
                         getattr(node, "line", None),
                         getattr(tgt, "member", None),
                         val.name, kind))


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
                if fn.endswith((".mojo", ".py")):
                    files += 1
                    scan(os.path.join(dirpath, fn), rows)
    print("scanned %d files" % files)
    print("`recv.field = <a frame-holding name>`: %d sites in %d files"
          % (len(rows), len({r[0] for r in rows})))
    by = collections.Counter(r[5] for r in rows)
    for k, n in by.most_common():
        print("  %-12s %3d" % (k, n))
    print()
    seen = set()
    for r in sorted(rows):
        if r[0] in seen:
            continue
        seen.add(r[0])
        print("  %s:%s  %s  self.%s = %s  [%s]"
              % (r[0], r[2], r[1], r[3], r[4], r[5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())