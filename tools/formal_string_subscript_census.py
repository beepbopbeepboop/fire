#!/usr/bin/env python3
"""Which corpus subscripts does the string-BYTE rule newly classify, and what is
done with the result.

    python3 tools/formal_string_subscript_census.py

The measurement `bugs/FORMAL_percent_s_of_a_string_byte_segfaults.md` names as
the thing its own author did not do: "whether any stdlib module subscripts a
string and relies on the element being unclassified". Done WITHOUT a sweep,
for the reason `tools/formal_frame_field_census.py` gives: a sweep answers "does
this FILE build", which is the wrong question for a change to a kind rule — a
file refused for a host import never reaches the rule, so the sweep counts the
refusals this change can only ever add to, never the sites it reclassifies.

**Two counts, and the direction of each one is stated because it decides how the
number is read.**

  * `reclassified` — the sites where the RULE changed its answer: a subscript
    whose base kind is `str`, which `list_elem_kind` answered None for (a
    string is not a blob) and `subscript_element_kind` answers `int`. This is
    asked of the real `model.ValueKinds`, so it is exact for the names that
    table can classify without a backend's `declared_kind` / `ctor_field_value`
    hooks — and those hooks can only ADD string classifications, so this count
    is a LOWER bound on the exposure.
  * `syntactic` — every subscript in the corpus whose base is a NAME that
    anything in the function says is a string: bound from a string literal,
    annotated `String`, or the result of a lowered string method. Deliberately
    over-approximate (the name may be rebound to something else in the same
    function), so this is the UPPER bound, and the gap between the two is
    exactly what a build would have to answer.

Each row carries the USE, because "a subscript of a string exists" and "the
value is used in a way this change turns into a refusal" are different
questions: `printf("%d", s[0])` renders the byte either way and is untouched,
`printf("%s", s[0])` is the SIGSEGV the rule closes, `len(s[0])` becomes an
honest refusal, and `print(s[0])` stops being refused and prints the byte.

**MEASURED 2026-10-03, on the tree this rule landed in: 17 sites in 4 files,
and not one of them is a `%s`, a `len` or a `print`.** The uses are
`String(s[i])` / `Int(s[i])` / `StringSlice(s[i])` conversions (5+3+1, all
word-for-word identities on this path), one `ord()`, and the rest a value in an
expression — including `str_slice[byte=start] == "0"` in
`std/collections/string`, which `string_compare_number_refusal` already refused
before the rule, because that function counts a `None` kind as "not a string"
and one string side is enough. So the answer to the question the rule's author
could not measure without a sweep is that this is a two-line change rather than a
diagnostic surface, and the four files are named here so the next reader does not
have to re-derive it.
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import fire_compiler as F
import formal.model as M
from formal.types import STRING_TYPE_NAMES, TYPE_NAMES

SKIP_DIRS = {".git", ".tmp", "build", "__pycache__", "cas", "node_modules",
             "formal/examples"}

_STRING_METHODS = frozenset(M.POINTER_BOUNDED_METHODS)


def parsed(path):
    try:
        with open(path) as f:
            return F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return None


def string_like_names(fn, struct_names):
    """Names this function says hold a string, read from its DECLARATIONS.

    The same three sources `ValueKinds` uses for a name — a literal, a
    parameter's annotation, a string method's result — and nothing else. A name
    with a method called on it is NOT one: this repository's own source calls
    `.strip()` on strings and `.keys()` on dicts all day.
    """
    out = set()
    for p in (getattr(fn, "params", None) or ()):
        pname, ann = (p[0], p[1]) if isinstance(p, (tuple, list)) else (p, None)
        base = M.annotation_base_name(ann) if ann else None
        if base in STRING_TYPE_NAMES:
            out.add(pname)
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        if isinstance(node, (F.AssignStmt, F.VarDecl)):
            target = (node.target if isinstance(node, F.AssignStmt)
                      else getattr(node, "name", None))
            name = target.name if isinstance(target, F.IdentExpr) else (
                target if isinstance(target, str) else None)
            value = getattr(node, "value", None)
            if not name or value is None:
                continue
            if isinstance(value, F.StringLiteral):
                out.add(name)
            elif isinstance(value, F.IdentExpr) and value.name in out:
                out.add(name)
            elif (isinstance(value, F.CallExpr)
                  and isinstance(value.func, F.MemberExpr)
                  and value.func.member in _STRING_METHODS
                  and M.string_method_yields_string(value, True)):
                out.add(name)
            elif (isinstance(value, F.CallExpr)
                  and M.call_callee_name(value.func) in STRING_TYPE_NAMES):
                out.add(name)
    return out


def use_sites(fn):
    """`id(subscript) -> how that subscript's value is USED`, from the calls.

    The question a site has to answer is not "does a string get subscripted" but
    "what is done with the byte", and the three uses that differ are the three
    the rule reaches: a `%s` conversion (closed, and the SIGSEGV it removes), a
    `%d`-shaped conversion or a `print` (renders the number either way — and
    `print` STOPS being refused, which is the half of the change that is not a
    refusal), and `len` (becomes an honest refusal). Everything else is a value
    in an expression, where the kind changes what a diagnostic says and nothing
    else.
    """
    out = {}
    for call in M.iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(call, F.CallExpr):
            continue
        callee = M.call_callee_name(call.func)
        args = [a for a in (getattr(call, "args", None) or [])
                if isinstance(a, F.SubscriptExpr)
                and not isinstance(a.index, F.SliceExpr)]
        if not args:
            continue
        fmt = None
        first = (getattr(call, "args", None) or [None])[0]
        if isinstance(first, F.StringLiteral):
            fmt = first.value
        convs = M.printf_conversion_specifiers(fmt) if (
            callee == "printf" and fmt is not None) else None
        for i, sub in enumerate(args):
            if callee == "printf":
                conv = convs[i] if convs is not None and i < len(convs) else "?"
                out[id(sub)] = "printf %%%s of a string byte" % conv if conv == "s" \
                    else "printf of a string byte (%%%s)" % conv
            elif callee == "print":
                out[id(sub)] = "print of a string byte"
            elif callee == "len":
                out[id(sub)] = "len of a string byte"
            else:
                out[id(sub)] = "value in a call to %s()" % callee
    return out


def scan(path, rows):
    stmts = parsed(path)
    if stmts is None:
        return
    struct_names = {getattr(s, "name", None) for s in stmts
                    if isinstance(s, F.StructDef)}
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
        strish = string_like_names(fn, struct_names)
        uses = use_sites(fn)
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.SubscriptExpr):
                continue
            if isinstance(node.index, F.SliceExpr):
                continue
            try:
                base_kind = vk.kind_of(node.obj)
                new = M.subscript_element_kind(base_kind)
                old = M.list_elem_kind(base_kind)
            except Exception:
                continue
            if not (old is None and new == M.INT_KIND):
                continue
            base = node.obj.name if isinstance(node.obj, F.IdentExpr) else "?"
            rows.append((rel, fn.name, getattr(node, "line", None), base,
                         uses.get(id(node), "a value in an expression"),
                         base in strish))


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
    print("string subscripts REclassified by the rule (ValueKinds' own answer,"
          " a LOWER bound): %d sites in %d files"
          % (len(rows), len({r[0] for r in rows})))
    print("…whose base a DECLARATION also calls a string: %d of %d"
          % (sum(1 for r in rows if r[5]), len(rows)))
    by = collections.Counter(r[4] for r in rows)
    for k, n in by.most_common():
        print("  %-34s %3d" % (k, n))
    for r in sorted(rows):
        print("  %s:%s  %s  %s  (base declared a string: %s)"
              % (r[0], r[2], r[1], r[4], r[5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
