#!/usr/bin/env python3
"""Every `receiver = <value>` in any method of this repository and the stdlib,
by the owner's WIDTH and by what kind of value is stored.

    python3 tools/formal_receiver_rebind_census.py

The measurement behind `formal/build.py`'s `_collect_receiver_rebinds`, which is
a parse-and-walk census rather than a sweep for the reason
`tools/formal_frame_field_census.py` gives: a sweep answers "does this FILE
build", and a file refused for a host import never reaches the receiver rule, so
the sweep can only count what already refuses.

**The two widths answer the same source shape differently, and that is the whole
of what this census is for.** A store to a receiver is spelled `self = <value>`
in the source, and `formal/build.py`'s `_rewrite_self_fields` later collapses
`self.<sole field>` onto `self` — so for a ONE-FIELD struct the hand-written
rebinding and the field store are the same text:

| owner | `self` IS | so `self = other` means | measured, both arches |
|---|---|---|---|
| one field | the field (a word) | Python rebinds a local name, and the caller keeps its own value | propagates the word, so `x.a` reads 2 where CPython reads 1 |
| many fields | the address of a frame | Python rebinds a local name, and `self.a` then reads the other frame | already correct |

**And the kinds of value, because they have different right answers.**

  * a CONSTRUCTION of the receiver's own struct (`self = T()`, `self = Self(1)`)
    — a fresh word or a fresh frame; nothing is aliased, and both widths allow it.
  * a NAME of the receiver's own struct TYPE — an alias of an object somebody
    else holds. For a multi-field receiver this is exactly right (the receiver
    register becomes the other object's frame address, which is what Python's
    rebinding does), and it is what `formal/build.py`'s `same_type` set already
    allows for a PARAMETER. For a one-field receiver it cannot be delivered: the
    one return word is already the receiver, and copying the other object's word
    into the caller's object is a write the source never asked for.
  * a LOCAL of the method — callee-private, so Python's later stores through the
    rebound receiver are invisible outside, and a multi-field receiver's frame
    address answers that exactly.
  * anything else (a literal, a call, an arithmetic result) — a WORD, and this is
    the shape 28 of the 51 one-field sites are: the stdlib's own in-place
    operators spell their store `self = self & rhs` and mean it as "put this in
    my own field".

**MEASURED 2026-10-03, over 370 `.mojo` files (this repository and the stdlib):
151 sites in 34 files — 51 under a one-field owner, 100 under a framed one.**

  * **one-field owners: NOT ONE site is a parameter or a local of the receiver's
    own type.** 23 are a construction of their own struct and 28 are a value the
    method computed, so `formal/build.py`'s
    `_collect_one_field_receiver_rebinds` — which refuses exactly the aliasing
    spellings — costs **0 files** in this corpus, and the 28 word-shaped stores
    it deliberately leaves alone are what keeps `std/builtin/bool.mojo` and the
    other in-place operators building.
  * **framed owners: exactly ONE site is a local of its own type**, and it is
    `std/utils/index.mojo:231`, a CONSTRUCTOR: `var tup = Self(); …; self =
    tup`. Python's own answer for that source is an object with nothing in it
    (`AttributeError` on the first read), so allowing the rebinding would trade
    today's loud refusal for a caller that silently reads an uninitialised
    frame. That is why the multi-field rule keeps its parameter-only allowance.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules",
             "formal/examples"}


def declared_own_type_names(fn, owner):
    """`(parameters, locals)` — DELEGATED to the rule's own recogniser.

    `formal/model.py`'s `receiver_own_type_names`, which is what
    `formal/build.py`'s `_collect_one_field_receiver_rebinds` asks, so this
    census measures THE RULE rather than a second reading of the same idea. A
    census with its own copy of the recognition is a census of the copy.
    """
    return M.receiver_own_type_names(fn, owner)


def classify(value, receivers, own_params, own_locals, locals_):
    own_type_names = own_params | own_locals
    if isinstance(value, F.CallExpr):
        callee = M.call_callee_name(value.func)
        return "a construction of its own struct" if callee in ("Self",) \
            else ("a call to %s()" % (callee or "an unnamed callee"))
    if isinstance(value, F.IdentExpr):
        if value.name in receivers:
            return "the receiver itself"
        if value.name in own_type_names:
            return ("a PARAMETER of its own type" if value.name not in locals_
                    else "a local of its own type")
        if value.name in locals_:
            return "a local of another type"
        return "a name this function never bound"
    if isinstance(value, F.IntLiteral):
        return "an integer literal"
    if isinstance(value, F.BoolLiteral):
        return "a bool literal"
    return type(value).__name__.replace("Expr", "").lower()


def scan(path, rows):
    try:
        with open(path) as f:
            stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return
    # A method is reached through its OWN struct's `methods` list, not by
    # matching names against the module: at parse time a method's name is the
    # MEMBER spelling (`zero`), and the lifted `<Struct>_<member>` name
    # `formal/build.py` gives it does not exist yet. Walking `stmts` and
    # matching names found nothing at all, which is the kind of zero that looks
    # like a clean census.
    for owner in (s for s in stmts if isinstance(s, F.StructDef)):
        owner_name = getattr(owner, "name", None)
        if not owner_name:
            continue
        receivers = M.struct_receivers(owner)
        for fn in M.struct_methods(owner):
            own_params, own_locals = declared_own_type_names(fn, owner)
            locals_ = {getattr(n, "name", None) for n in M.iter_nodes(fn.body)
                       if isinstance(n, F.VarDecl)}
            locals_ |= {t.target.name for t in M.iter_nodes(fn.body)
                        if isinstance(t, F.AssignStmt)
                        and isinstance(t.target, F.IdentExpr)}
            for node in M.iter_nodes(getattr(fn, "body", None) or []):
                if not isinstance(node, (F.AssignStmt, F.VarDecl)):
                    continue
                if isinstance(node, F.VarDecl):
                    target, value = node.name, node.value
                else:
                    target = (node.target.name
                              if isinstance(node.target, F.IdentExpr) else None)
                    value = node.value
                if not isinstance(target, str) or target not in receivers:
                    continue
                if value is None:
                    continue
                rows.append((os.path.relpath(path, HERE), fn.name,
                             getattr(node, "line", None),
                             "one field" if M.struct_is_one_field(owner)
                             else "a frame", target,
                             classify(value, receivers, own_params,
                                      own_locals, locals_)))


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
    print("scanned %d .mojo files" % files)
    print("`receiver = <value>` in a method: %d sites in %d files"
          % (len(rows), len({r[0] for r in rows})))
    for width in ("one field", "a frame"):
        sel = [r for r in rows if r[3] == width]
        print("\n  owner is %s: %d sites in %d files"
              % (width, len(sel), len({r[0] for r in sel})))
        for k, n in collections.Counter(r[5] for r in sel).most_common():
            print("    %-38s %3d" % (k, n))
    print()
    for r in sorted(rows):
        print("  %s:%s  %s  [%s]  `%s = …`  %s"
              % (r[0], r[2], r[1], r[3], r[4], r[5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
