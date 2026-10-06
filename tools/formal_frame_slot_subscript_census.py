#!/usr/bin/env python3
"""How many corpus subscripts take a FRAME FIELD as their blob base, and which.

    python3 tools/formal_frame_slot_subscript_census.py [--frames]

**The number `model.frame_slot_element_refusal` has to beat, and the instrument
that says whether a `structs_declared` lookup is attributing the frame it
finds.** `formal/model.py`'s docstring carries the table this reproduces; the
table is a fact about a TREE and this is the code that can be re-run over
today's, which is the difference between a number and a claim.

**What counts as a site.** A `SubscriptExpr` whose base is a FIELD read
(`X.<field>[i]`) and whose index is not a slice. The base's spelling is what
makes the shape interesting: a bare name's frame-ness is `ValueKinds`' question
and a field's is the DECLARATION's, so the field case is the one
`frame_slot_element_refusal` answers by asking `_expr_str_kind`.

**How the field's type is resolved, and why the resolution is an UPPER BOUND.**
`self.<field>` is exact: `model.method_owner_struct` finds the owner from the
lifted name, so the declaration read is the right one. `x.<field>` for any other
`x` resolves through the SIBLING census's reader —
`formal_frame_field_census.frame_bound_structs`, imported rather than copied,
because a second copy of "which names hold a frame's address" is how two
cameras come to disagree about the corpus: a parameter annotated with a
multi-field struct of this file, or a name assigned from a construction of one.
That over-counts (a field name is not a unique key) and under-counts (a receiver
typed in another module resolves to nothing), and both directions are stated
here rather than discovered later:

* **over-counts**: two structs in one file declaring the same field name with
  different types make the row say `ambiguous` and count under NEITHER kind,
  which is the conservative direction — it cannot invent a frame bucket;
* **under-counts**: a base whose receiver this file cannot type is `unresolved`,
  and the emitter would answer `None` there too (`_declared_kind_for`'s
  `if not cands: return None`), so the two agree on those rows.

**What it is FOR.** `model.frame_slot_element_refusal` decides whether a container
operation on a FRAME-valued field is refused — a frame address read as a blob
answers `base + 8 + 8*count`, where the count is the frame's first FIELD, so the
number is not one anybody wrote — and the number this prints is the corpus cost
of refusing it. A count that cannot be re-run is not a cost, it is a rumour.

**And the misattribution column, which is why this is a tool and not a table.**
`model.declared_type_kind` reaches `FRAME_KIND` through `structs_declared(base,
decls)`, which finds a struct of the module BY NAME. A module that declares
`struct Pointer[...]` (`std/memory/pointer.mojo`) therefore makes an annotation
`Pointer[...]` a frame *there* — correctly — and the question this column asks
is whether that lookup fires anywhere it should not. The `identity-ctor` line is
the count of frame rows whose annotation's base name is in
`model.IDENTITY_TYPE_CTORS`: every one of them is a site a widening would
refuse on the strength of a name collision rather than of a frame.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M
from formal.types import DTYPE_TYPE_NAMES, STRING_TYPE_NAMES, TYPE_NAMES

sys.path.insert(0, os.path.join(HERE, "tools"))
from formal_frame_field_census import frame_bound_structs   # noqa: E402

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules"}


def parsed(path):
    try:
        with open(path) as f:
            return F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return None


def kind_of(ann, decls):
    """`model.declared_type_kind`, or the instrument's own two answers.

    The model returns a KIND or None; `ambiguous` and `unresolved` are this
    tool's, and they are deliberately not kinds so a reader cannot mistake one
    for the model's answer.
    """
    if not ann or not str(ann).strip():
        return "unresolved"
    return M.declared_type_kind(ann, TYPE_NAMES, STRING_TYPE_NAMES, decls,
                               dtype_names=DTYPE_TYPE_NAMES) or "unresolved"


def field_type(decls, owner, fn, base):
    """`(annotation, how)` for a field read, or `(None, why)`.

    `owner` is the method's own struct when the base is spelled `self.<f>`,
    which is the exact case. Any other `x.<f>` resolves through
    `frame_bound_structs`, the sibling census's reader, and says so in the
    returned `how` — a count that cannot say which reader produced it is a
    count nobody can check.
    """
    member = getattr(base, "member", None)
    if member is None:
        return None, "not a field"
    if not isinstance(base.obj, F.IdentExpr):
        return None, "a chain — the outer field's declared type is the type of "\
                     "the WORD, not of what it points at"
    root = base.obj.name
    if owner is not None and root in M.struct_receivers(owner):
        ann = M.struct_field_type(owner, member, decls)[1]
        return ann, "self.<field>"
    # `frame_bound_structs` already excludes a ONE-FIELD struct: its receiver is
    # a value rather than a frame, so `x.<f>` there is a word this census must
    # not claim is a frame base.
    holder = frame_bound_structs(fn, decls).get(root)
    if holder is not None:
        ann = M.struct_field_type(holder, member, decls)[1]
        return ann, "a frame-bound name"

    return None, "unresolved"


def functions_of(stmts, decls):
    """`(FunctionDef, owner StructDef or None)` for every function in the file.

    A BACKEND is handed methods already lifted to `<Struct>_<method>`, which is
    the only record of the owner a FunctionDef carries — but this census reads a
    PARSED tree, where a method is a member of its StructDef.  So the pairing is
    taken structurally here rather than reconstructed from a name: a split on `_`
    is wrong (`_DictKeyIter`), and `model.method_owner_struct` needs the lifted
    spelling this tree does not have.
    """
    owned = {}
    for st in (decls or {}).values():
        for m in M.struct_methods(st):
            owned[id(m)] = st
    for fn in M.iter_nodes(stmts):
        if not isinstance(fn, F.FunctionDef):
            continue
        yield fn, owned.get(id(fn))


def scan(path, rows):
    stmts = parsed(path)
    if stmts is None:
        return
    decls = {getattr(s, "name", None): s for s in stmts
             if isinstance(s, F.StructDef)}
    rel = os.path.relpath(path, HERE)
    for fn, owner in functions_of(stmts, decls):
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.SubscriptExpr):
                continue
            if isinstance(node.index, F.SliceExpr):
                continue
            if not isinstance(node.obj, F.MemberExpr):
                continue
            ann, how = field_type(decls, owner, fn, node.obj)
            kind = kind_of(ann, decls) if ann else how
            rows.append((rel, fn.name, getattr(node, "line", None),
                         M.spelled(node.obj), ann or "-", kind, how))


def main():
    from module_loader import STDLIB_PATH
    show_frames = "--frames" in sys.argv[1:]
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
    kinds = collections.Counter(r[5] for r in rows)
    frames = [r for r in rows if r[5] == M.FRAME_KIND]
    ident = [r for r in frames
             if (M.annotation_base_name(r[4]) or "") in M.IDENTITY_TYPE_CTORS]
    print("scanned %d .mojo files" % files)
    print("subscripts on a FIELD base: %d sites in %d files"
          % (len(rows), len({r[0] for r in rows})))
    print()
    print("by the field's declared kind (see the module docstring for how each")
    print("row is resolved, and which direction each can be wrong in):")
    for k, n in kinds.most_common():
        print("  %-28s %5d" % (k, n))
    print()
    print("FRAME_KIND bases — what refusing them would cost: %d sites in %d "
          "files" % (len(frames), len({r[0] for r in frames})))
    print("…of those, an annotation naming an IDENTITY_TYPE_CTOR, so a frame "
          "found by NAME collision: %d" % len(ident))
    if show_frames:
        print()
        for r in sorted(frames):
            print("  %-56s %-22s :%-5s %-22s %-22s %s"
                  % (r[0], r[1], r[2], r[3], r[4], r[6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())