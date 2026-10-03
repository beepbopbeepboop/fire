#!/usr/bin/env python3
"""Which functions' declared parameter types contradict every call site in their
own file — the list behind `model.frame_declared_parameter_refusal`.

    python3 tools/formal_declared_param_census.py

`bugs/FORMAL_receiver_stored_in_a_field.md` §3 asks for this list and says it
"needs a sweep, because the refusal compares call sites inside one image and a
parse-and-walk instrument cannot answer it". That is true of the SWEEP and
false of the question: the sweep's unit is a FILE, and a file's image when built
on its own IS the file, so "every call site in this image" is answerable by
parsing that one file and looking at the calls in it. What the instrument cannot
answer is the OTHER half — whether the file's program is right in the first
place — so what comes out is a CANDIDATE list with both sides spelled, which is
exactly what §3 says is needed first ("for each of the 13, check whether CPython
raises on the same source… the terminal message already names the function and
the parameter").

**What counts as a candidate.** A parameter annotated with a struct declared in
the same file, whose call sites in that file are all something else:

  * a NAME that is not otherwise a value of that struct — the common case, and
    the one that is a wrong answer rather than a failure (`c.a` becomes a load
    at `[word + 8k]`);
  * a construction of a DIFFERENT struct of the same field count, which is
    reported separately because it is a different bug with a different repair;
  * a literal, a call, or an arithmetic result — always something else.

**The instrument's one weakness, stated because it decides how the list is
read.** It cannot see a call in ANOTHER file, so a function whose only agreeing
call site lives in a different module is reported here and is not refused in
practice (the sweep builds each file with its imports, and the import
manifest's `frame_params` contract is what the cross-module check reads). So the
list is an UPPER bound on the sweep's 13, in the same direction as every other
census here — and each row says how many call sites it saw, so a row with one
caller and a row with four are not the same claim.
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


def names_bound_to(stmts, struct_name, unknown=None):
    """Names this module binds to a value of `struct_name`, from declarations.

    A construction of it, a parameter annotated with it, and a name copied from
    either. Deliberately not "a name with a method called on it": this
    repository's own source calls `.strip()` on strings and `.keys()` on dicts
    all day, and a census that counted those reported 52 sites of which 28 were
    not objects at all (`tools/formal_frame_field_census.py`'s note).
    """
    out = set()
    for st in stmts:
        # A MODULE-LEVEL binding is one too, and leaving it out reported
        # `std/memory/alloc.mojo`'s `_alloc_bytes(byte_layout)` as a
        # contradiction when `byte_layout` is a module-level `Layout`.
        target = getattr(st, "target", None) or getattr(st, "name", None)
        value = getattr(st, "value", None)
        name = target.name if isinstance(target, F.IdentExpr) else (
            target if isinstance(target, str) else None)
        if name and isinstance(value, F.CallExpr) and (
                M.call_callee_name(value.func) in (struct_name, "Self")
                or M.subscript_callee_name(value) == struct_name):
            out.add(name)
    for fn in M.iter_nodes(stmts):
        if not isinstance(fn, F.FunctionDef):
            continue
        for p in (getattr(fn, "params", None) or ()):
            pname, ann = (p[0], p[1]) if isinstance(p, (tuple, list)) else (p, None)
            if not isinstance(pname, str) or not ann:
                continue
            if M.annotation_base_name(ann) == struct_name:
                out.add(pname)
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, (F.AssignStmt, F.VarDecl)):
                continue
            target = (node.target if isinstance(node, F.AssignStmt)
                      else getattr(node, "name", None))
            name = target.name if isinstance(target, F.IdentExpr) else (
                target if isinstance(target, str) else None)
            value = getattr(node, "value", None)
            if not name or value is None:
                continue
            if isinstance(value, F.CallExpr) and (
                    # `S()`, `Self()` and the specialization spelling `S[D, N]()`,
                    # which is three spellings of one construction and the one
                    # this repository's own `utils/index.mojo` uses throughout.
                    M.call_callee_name(value.func) in (struct_name, "Self")
                    or M.subscript_callee_name(value) == struct_name):
                out.add(name)
            elif isinstance(value, F.IdentExpr) and value.name in out:
                out.add(name)
            elif isinstance(value, (F.CallExpr, F.MemberExpr, F.SubscriptExpr)):
                # A name bound from a CALL has whatever that callee returns, and
                # a name bound from a field read or a subscript has whatever
                # that slot holds: neither is derivable here, so the name is
                # evidence for nothing in either direction. `var byte_layout =
                # layout.as_byte_layout()` is a `Layout` in the source and was
                # this instrument's first "DECIDED contradiction" before the
                # bucket existed.
                if unknown is not None:
                    unknown.add(name)
    return out


def what_is_passed(arg, struct_name, good_names, structs_by_name,
                   declared_names=frozenset(),
                   unknown_names=frozenset()):  # noqa: C901
    """`"agrees"`, or the bucket this argument falls in.

    THREE buckets, and the split is the instrument's honesty about what a parse
    can decide:

      * `"agrees"` — the argument is a name this file binds to the declared
        struct, or a construction of it (`S()`, `Self()`, `S[D, N]()`).
      * `"DISAGREES"` — it cannot be a value of that struct by any reading: a
        name of another type, an arithmetic or unary result, a literal, or a
        construction of a DIFFERENT struct.
      * `"MAYBE <why>"` — a SUBSCRIPT or a FIELD read, where the element type is
        exactly the question being asked and nothing here derives it:
        `report.runs[i]` handed to a parameter declared `Batch` IS a `Batch` in
        the source, and a census that called it a contradiction would be
        reporting its own missing inference as a stdlib bug. Every measured
        false positive this instrument has is this row.
      * `"UNREAD <callee>"` — a CALL, whose return type is a fact about another
        function's declaration.
    """
    if arg is None:
        return "agrees"
    if isinstance(arg, F.IdentExpr):
        if arg.name in good_names:
            return "agrees"
        # A name whose TYPE this file does not state carries no evidence either
        # way — an unannotated parameter, a name from a `from … import`, a
        # legacy custom `self`, or a name bound from a call or a field read
        # whose own type is not derived here — so it is MAYBE rather than a
        # contradiction.  Only a name DECLARED as something else is decided.
        return ("MAYBE a name whose type this file does not state"
                if (arg.name in declared_names
                    or arg.name in unknown_names)
                else "DISAGREES a name declared as something else")
    if isinstance(arg, F.CallExpr):
        callee = M.call_callee_name(arg.func)
        if callee == struct_name or callee == "Self" \
                or M.subscript_callee_name(arg) == struct_name:
            return "agrees"
        other = structs_by_name.get(callee)
        if other is not None:
            same_width = (len(getattr(other, "fields", None) or [])
                          == len(getattr(structs_by_name[struct_name],
                                         "fields", None) or []))
            return ("MAYBE a construction of %s%s"
                    % (callee, ", which has the same field count and so the "
                       "same layout" if same_width else "")
                    if same_width else "DISAGREES a construction of %s" % callee)
        return "UNREAD a call to %s()" % (callee or "an unnamed callee")
    if isinstance(arg, F.SubscriptExpr):
        return "MAYBE a subscript"
    if isinstance(arg, F.MemberExpr):
        return "MAYBE a field read"
    if isinstance(arg, F.UnaryOp):
        # `x^` is Mojo's TRANSFER — the value moved OUT of `x` — so it agrees
        # exactly when its operand does, and it is how this repository's own
        # `dealloc(allocation^)` passes an `Allocation`. A census that read
        # every unary operator as arithmetic reported that as a contradiction,
        # which is the same mistake as reading a subscript as a wrong type: the
        # operator's meaning is not derived here, so it is asked of the operand.
        if getattr(arg, "op", None) == "^":
            return what_is_passed(getattr(arg, "operand", None), struct_name,
                                  good_names, structs_by_name,
                                  declared_names)
        return "DISAGREES a %s unary result" % getattr(arg, "op", "?")
    return "DISAGREES a %s" % type(arg).__name__.replace("Expr", "").lower()


def functions_of(stmts):
    out = {}
    for fn in M.iter_nodes(stmts):
        if isinstance(fn, F.FunctionDef) and fn.name not in out:
            out[fn.name] = fn
    return out


def scan(path, rows, parsed):
    try:
        with open(path) as f:
            stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
    except Exception:
        return
    parsed[path] = stmts
    structs_by_name = {getattr(s, "name", None): s for s in stmts
                       if isinstance(s, F.StructDef)}
    functions = functions_of(stmts)
    # One file's image: the calls in THIS file, which is what the sweep's
    # single-file build sees.
    for call in M.iter_nodes(stmts):
        if not isinstance(call, F.CallExpr):
            continue
        callee = M.call_callee_name(call.func)
        fn = functions.get(callee)
        if fn is None:
            continue
        # A METHOD call's first DECLARED parameter is the receiver, which the
        # source spells as `recv.m(x)` rather than as an argument — so the two
        # lists are offset by one and the receiver is compared against
        # parameter 0 in its own right. Getting this wrong reports every
        # `recv.m(a)` as handing `a` to the receiver's parameter.
        recv = call.func.obj if isinstance(call.func, F.MemberExpr) else None
        args = list(call.args or [])
        pairs = ([(0, recv)] if recv is not None else []) \
            + [(i + (1 if recv is not None else 0), a)
               for i, a in enumerate(args)]
        convs = getattr(fn, "param_convs", None) or {}
        for i, (pname, ann) in enumerate(getattr(fn, "params", None) or []):
            if not isinstance(pname, str) or not ann:
                continue
            # A MUTATING parameter (`out node: Node[T]`) is not in the
            # argument list at all — the callee hands it back — so comparing it
            # with `args[0]` reports every such call as handing the wrong thing
            # to the callee's first parameter, which is how
            # `std/collections/linked_list.mojo`'s `_make_node(value^, None,
            # self._head)` first appeared here as a contradiction.
            if (convs.get(pname) or "") in M.MUTATING_RECEIVER_CONVENTIONS:
                continue
            struct_name = M.annotation_base_name(ann)
            if struct_name not in structs_by_name:
                continue
            for pos, arg in pairs:
                if pos != i or arg is None:
                    continue
                rows.append((path, callee, pname, struct_name, pos, arg))


def main():
    from module_loader import STDLIB_PATH
    roots = [HERE, os.path.join(STDLIB_PATH, "std")]
    rows = []
    parsed = {}
    files = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if fn.endswith(".mojo"):
                    files += 1
                    scan(os.path.join(dirpath, fn), rows, parsed)
    # Group by (file, callee, parameter) — the refusal's own unit — and keep the
    # groups where EVERY site disagrees.
    grouped = collections.OrderedDict()
    for path, callee, pname, struct_name, i, arg in rows:
        grouped.setdefault((path, callee, pname, struct_name), []).append(
            (i, arg))
    out = []
    for (path, callee, pname, struct_name), sites in grouped.items():
        stmts = parsed[path]
        structs_by_name = {getattr(s, "name", None): s for s in stmts
                           if isinstance(s, F.StructDef)}
        unknown = set()
        good = names_bound_to(stmts, struct_name, unknown)
        declared = {n for n, _t in M.incoming_args(
            functions_of(stmts).get(callee))}
        declared |= {t for st in stmts for t in
                     ((getattr(st, "target", None)
                       or getattr(st, "name", None)),)
                     if isinstance(t, str)}
        declared |= {t.name for st in stmts for t in [getattr(st, "target", None)]
                     if isinstance(t, F.IdentExpr)}
        whys = [what_is_passed(arg, struct_name, good, structs_by_name,
                               declared - unknown, unknown)
                for _i, arg in sites]
        if any(w == "agrees" for w in whys):
            continue
        out.append((path, callee, pname, struct_name, len(sites), whys))
    decided = [r for r in out
               if all(w.startswith("DISAGREES") for w in r[5])]
    print("scanned %d .mojo files; %d (callee, parameter) pairs with a "
          "struct-typed parameter called in their own file"
          % (files, len(grouped)))
    print("…no call site agrees with the declaration: %d pairs in %d files"
          % (len(out), len({os.path.relpath(r[0], HERE) for r in out})))
    print("…of those, EVERY site is a DECISED disagreement (no subscript, no "
          "field read, no unread call): %d pairs in %d files — the rows a "
          "reader can act on without a type checker"
          % (len(decided),
             len({os.path.relpath(r[0], HERE) for r in decided})))
    print()
    print("DECIDED:")
    for path, callee, pname, struct_name, n, whys in sorted(
            decided, key=lambda r: os.path.relpath(r[0], HERE)):
        print("  %s  %s(%s: %s)  — %d site(s): %s"
              % (os.path.relpath(path, HERE), callee, pname, struct_name, n,
                 ", ".join(sorted(set(whys)))))
    print()
    print("MAYBE / UNREAD (an element type or a return type this instrument "
          "does not derive):")
    for path, callee, pname, struct_name, n, whys in sorted(
            out, key=lambda r: os.path.relpath(r[0], HERE)):
        if all(w.startswith("DISAGREES") for w in whys):
            continue
        print("  %s  %s(%s: %s)  — %d site(s): %s"
              % (os.path.relpath(path, HERE), callee, pname, struct_name, n,
                 ", ".join(sorted(set(whys)))))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
