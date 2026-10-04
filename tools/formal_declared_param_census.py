#!/usr/bin/env python3
"""Which functions' declared parameter types contradict every call site in their
own file — the list behind `model.frame_declared_parameter_refusal`.

    python3 tools/formal_declared_param_census.py

`“FORMAL_receiver_stored_in_a_field: a frame address in a struct field”` §3 asks for this list and says it
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

**What it decides, and what it cannot.**  `Types` below derives the type of a
NAME (from an annotation, a construction, or a copy), of a FIELD (from the
struct's own declaration), of a class `comptime` alias (from its initialiser), of
a subscript's ELEMENT (`List[T]` → `T`, `formal.model.annotation_type_arg_base`),
and of a CALL (from the callee's declared return type).  With those, a row whose
argument is `report.runs[i]` or `ControlOffset.ready_flag` is DECIDED — the first
is whatever `Report.runs` is declared to hold, the second is a `ControlOffset` by
its own initialiser — instead of sitting in the undecidable bucket forever.
Everything else stays undecidable and says so: an unannotated name, an element
type no declaration states, a callee this file does not define.  The direction is
the same one `formal/model.py`'s own type readers take (an unrecognised spelling
is refused, never guessed), and a name the derivation cannot place is a MAYBE
rather than a disagreement, because a census that called its own missing
inference a stdlib bug is the failure this instrument was built to avoid.
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


def functions_of(stmts):
    out = {}
    for fn in M.iter_nodes(stmts):
        if isinstance(fn, F.FunctionDef) and fn.name not in out:
            out[fn.name] = fn
    return out


class Types:
    """What type each expression in ONE file holds, as far as a parse can say.

    The reader `formal/model.py` asks when it decides whether a call site's
    argument is a frame of the declared struct — which this instrument is a
    census OF, so deriving the same answers here is what makes its rows
    decidable instead of a permanent MAYBE.  One implementation per answer:
    `names_bound_to` below is expressed through this class rather than walking
    `__init__`-style bodies a second time, because two readers of "what type is
    this name" disagree the day one of them is taught a new spelling.

    `None` means "this file does not say", for every shape — an unannotated
    parameter, a subscript of a `List` with no element type, a call to a callee
    declared elsewhere.  Nothing here guesses: the consumer treats `None` as
    MAYBE, which is the honest answer and the one the instrument's own docstring
    promises.
    """

    def __init__(self, stmts):
        self.stmts = stmts
        self.structs = {getattr(s, "name", None): s for s in stmts
                        if isinstance(s, F.StructDef)}
        self.fns = functions_of(stmts)
        self.names = {}          # module-level name -> annotation text
        # The RECEIVER of the function currently being read, and the struct it
        # is a receiver OF.  Both are per-scope rather than per-file, and
        # leaving them out is not a simplification: `python_object.mojo`'s
        # `__lt__` spells `_rich_compare[Py_LT](self, rhs)` inside a
        # `PythonObject` method, so the first argument is a `PythonObject` by
        # being the receiver, and a reader that cannot see the receiver calls
        # every method call in the corpus a contradiction.  (The reader this
        # replaced got there by ACCIDENT — one method in that file writes
        # `self = Self(None)`, so a name-bound-from-a-`Self()` rule marked
        # `self` as a value of every struct in the file.)
        self.owner = None
        self.receiver = None
        self.scope = {}          # the current FUNCTION's own typed names
        self.local = set()       # …and every name it binds, typed or not
        self._collect()

    def in_function(self, fn, owner=None):
        """This reader, scoped to one function: its receiver, its OWN names.

        Returns a copy rather than mutating, because `scan` interleaves scopes:
        a file's calls are read one function at a time and the next call site
        may belong to a different class entirely.

        **The scope is not a refinement, it is the answer.** A name's type is a
        fact about the function that binds it, and `std/simd.mojo` is where
        that stops being pedantry: `_convert_float8_to_f32`'s body calls
        `_simd_apply[wrapper_fn, …](val)` where `val: SIMD[.float32, size]`, and
        the same file has a nested `def wrapper_fn(…)(val: Scalar[input_dtype])`
        — so one file-wide table binds `val` to whichever came first and calls
        a `SIMD` argument a `Scalar`. Resolution is the enclosing function first,
        then the module, which is what a reader of the source does too.
        """
        view = object.__new__(Types)
        view.__dict__.update(self.__dict__)
        view.owner = owner
        view.receiver = M.method_receiver_name(fn) if owner else None
        view.scope, view.local = self._function_names(fn)
        return view

    def _function_names(self, fn):
        """(`{name: annotation}`, `{name}`) for ONE function: its parameters and
        its own assignments, and nothing from any other function.

        The second set is the names the function BINDS but cannot type, and it is
        what stops the file-level table answering for them. `pointer.mojo`'s
        `unsafe_gather` writes `var base = offset.cast[.int]().fma(…)` and the
        same file has a `Some` construction bound to `base` further down; without
        this the call site reads as handing a `Some` to a `Pointer` parameter,
        which is what a file-wide name table says and is not what the source
        says.
        """
        out, local = {}, set()
        for p in (getattr(fn, "params", None) or ()):
            pname, ann = ((p[0], p[1]) if isinstance(p, (tuple, list))
                          else (p, None))
            if isinstance(pname, str) and ann:
                out.setdefault(pname, ann)
        # Two passes for the same reason the file-level walk has two: a local may
        # be copied from a local bound later in the same body.
        for _ in range(2):
            for node in M.iter_nodes(getattr(fn, "body", None) or []):
                if not isinstance(node, (F.AssignStmt, F.VarDecl)):
                    continue
                target = (node.target if isinstance(node, F.AssignStmt)
                          else getattr(node, "name", None))
                name = (target.name if isinstance(target, F.IdentExpr)
                        else (target if isinstance(target, str) else None))
                if not name:
                    continue
                local.add(name)
                if name in out:
                    continue
                ann = getattr(node, "type_ann", None)
                if ann:
                    out[name] = ann
                    continue
                value = getattr(node, "value", None)
                if value is None:
                    continue
                built = self._construction_name(value)
                if built is not None:
                    out[name] = built
                elif isinstance(value, F.IdentExpr) and value.name in out:
                    out[name] = out[value.name]
        return out, local

    # ── names ──────────────────────────────────────────────────────────────
    def _bind(self, name, ann):
        if name and ann and name not in self.names:
            self.names[name] = ann

    def _collect(self):
        """Two passes, because a copy needs its source typed first.

        `var a = Cell()` then `var b = a` is the shape the old `names_bound_to`
        handled in one walk by threading an `out` set; a file can also write the
        copy before the construction, and a fixed number of passes reads both
        without a worklist.  Two is enough because a chain of copies three deep
        is not a shape this corpus has, and a third pass costs nothing anyway.
        """
        for _ in range(2):
            for st in self.stmts:
                target = (getattr(st, "target", None)
                          or getattr(st, "name", None))
                name = (target.name if isinstance(target, F.IdentExpr)
                        else (target if isinstance(target, str) else None))
                if not name:
                    continue
                if name in self.names:
                    continue
                ann = getattr(st, "type_ann", None)
                if ann:
                    self._bind(name, ann)
                    continue
                value = getattr(st, "value", None)
                if value is None:
                    continue
                built = self._construction_name(value)
                if built is not None:
                    self._bind(name, built)
                elif isinstance(value, F.IdentExpr) and value.name in self.names:
                    self._bind(name, self.names[value.name])
                # A name bound from a CALL has whatever that callee returns,
                # and one bound from a field read or a subscript has whatever
                # that slot holds: neither is derivable from the binding alone,
                # so the name is simply left untyped, and `annotation` answers
                # None for it. `var byte_layout = layout.as_byte_layout()` is a
                # `Layout` in the source and was this instrument's first
                # "DECIDED contradiction" before the bucket existed.
            for fn in M.iter_nodes(self.stmts):
                if not isinstance(fn, F.FunctionDef):
                    continue
                for p in (getattr(fn, "params", None) or ()):
                    pname, ann = ((p[0], p[1]) if isinstance(p, (tuple, list))
                                  else (p, None))
                    self._bind(pname, ann)

    def _construction_name(self, value):
        """`S`, for a construction of the struct `S` — `S()`, `Self()` and the
        specialization spelling `S[D, N]()`, which is three spellings of one
        construction and the one this repository's own `utils/index.mojo` uses
        throughout."""
        if not isinstance(value, F.CallExpr):
            return None
        callee = M.call_callee_name(value.func)
        if callee == "Self" or M.subscript_callee_name(value) is not None:
            return callee
        return callee if callee in self.structs else None

    # ── expressions ────────────────────────────────────────────────────────
    def annotation(self, expr):
        """The declared type of `expr` as an annotation string, or None."""
        if expr is None:
            return None
        if isinstance(expr, F.IdentExpr):
            if expr.name == self.receiver and self.owner:
                return self.owner
            if expr.name in self.scope:
                return self.scope[expr.name]
            # A name this function binds and does not type is answered HERE and
            # not by the file's table: the enclosing binding is the one the
            # source means, and a file-wide table answers with whichever
            # function the walk reached first.
            if expr.name in self.local:
                return None
            return self.names.get(expr.name)
        if isinstance(expr, F.CallExpr):
            built = self._construction_name(expr)
            if built is not None:
                return built
            fn = self.fns.get(M.call_callee_name(expr.func))
            ret = getattr(fn, "return_type", None) if fn is not None else None
            return ret or None
        if isinstance(expr, F.MemberExpr):
            obj = getattr(expr, "obj", None)
            base = self.annotation(obj)
            # `ControlOffset.ready_flag` is a CLASS member access, not a read of
            # a value: the object names the struct itself, which no parameter or
            # binding ever binds. So the base is the struct's own name, and the
            # member is looked up in that class — which is how
            # `get_control_field(control, ControlOffset.ready_flag, …)` becomes
            # decidable instead of a MAYBE for the fourth time.
            if base is None and isinstance(obj, F.IdentExpr) \
                    and obj.name in self.structs:
                base = obj.name
            base_name = M.annotation_base_name(base) if base else None
            st = self.structs.get(base_name)
            if st is None:
                return None
            member = getattr(expr, "member", None)
            # A class-level `comptime ready_flag = Self(0)` is a value of the
            # class by its own initialiser, which is the reading that decides
            # `get_control_field(control, ControlOffset.ready_flag, …)`: the
            # field access is not evidence for or against the declaration, and
            # before this arm every `_amdgpu.mojo` row was a MAYBE.
            if member in (getattr(st, "comptime_aliases", None) or {}):
                return base_name
            for fld in (getattr(st, "fields", None) or []):
                if getattr(fld, "name", None) == member:
                    return getattr(fld, "type_ann", None)
            return None
        if isinstance(expr, F.SubscriptExpr):
            base = M.annotation_base_name(
                self.annotation(getattr(expr, "obj", None)) or "")
            if base in _ELEMENT_TYPES:
                return M.annotation_type_arg_base(
                    self.annotation(getattr(expr, "obj", None)) or "", 0)
            return None
        if isinstance(expr, F.UnaryOp):
            # `x^` is Mojo's TRANSFER — the value moved OUT of `x` — so it
            # agrees exactly when its operand does, and it is how this
            # repository's own `dealloc(allocation^)` passes an `Allocation`. A
            # census that read every unary operator as arithmetic reported that
            # as a contradiction, which is the same mistake as reading a
            # subscript as a wrong type.
            return (self.annotation(getattr(expr, "operand", None))
                    if getattr(expr, "op", None) == "^" else None)
        return None

    def constructs(self, expr, name):
        """True when `expr` is a CONSTRUCTION of `name`.

        The one thing `what_is_passed` cannot read off `base_name`, and it
        matters for exactly one bucket: `take(make_other())` where
        `make_other() -> Other` derives `Other` from a RETURN ANNOTATION, and a
        value of a struct is a value of it whatever width it has, while
        `take(Other())` is a construction that happens to have the same layout.
        """
        return self._construction_name(expr) == name

    def base_name(self, expr):
        """The bare struct/type name `expr` holds, or None."""
        ann = self.annotation(expr)
        return M.annotation_base_name(ann) if ann else None


# The containers whose FIRST type argument is the element type, which is what
# `x[i]` is.  Hand-kept, and the reason is the same one `_WORD_SCALARS` gives:
# a spelling this list has not heard of yields no element type, which is the
# conservative answer (MAYBE) rather than a guess.
_ELEMENT_TYPES = frozenset({
    'List', 'Array', 'Span', 'StaticList', 'OwnedList', 'ListView', 'Slice',
    'InlinedArray', 'SIMD',
})


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
    types = Types(stmts)
    # Which struct each FUNCTION belongs to, which is the one thing a whole-file
    # walk cannot know and the reason this loop is per-function: `self` is a
    # value of the struct whose method it appears in and of no other.  A
    # top-level function has no owner, so its `self`-shaped parameters stay
    # untyped, which is the honest answer rather than a guess.
    owners = {}
    method_names = set()
    for s in stmts:
        if not isinstance(s, F.StructDef):
            continue
        for m in (getattr(s, "methods", None) or ()):
            owners.setdefault(id(m), s.name)
            method_names.add(m.name)
    # One file's image: the calls in THIS file, which is what the sweep's
    # single-file build sees.
    for site_fn in M.iter_nodes(stmts):
        if not isinstance(site_fn, F.FunctionDef):
            continue
        reader = types.in_function(site_fn, owners.get(id(site_fn)))
        for call in M.iter_nodes(site_fn.body or []):
            if not isinstance(call, F.CallExpr):
                continue
            callee = M.call_callee_name(call.func)
            fn = functions.get(callee)
            if fn is None:
                continue
            # A METHOD call's first DECLARED parameter is the receiver, which the
            # source spells as `recv.m(x)` rather than as an argument — so the
            # two lists are offset by one and the receiver is compared against
            # parameter 0 in its own right. Getting this wrong reports every
            # `recv.m(a)` as handing `a` to the receiver's parameter.
            #
            # …and the same parameter can be passed IMPLICITLY, which is what
            # `pointer.mojo`'s `gather[alignment=…](base, mask, default)` does
            # inside `Pointer` itself (`@__allow_legacy_custom_self_type`, and
            # `formal/build.py`'s `_receiverless_methods` is the build's half of
            # this). Comparing `args[0]` against parameter 0 there reports the
            # method's own first real argument as the receiver, which is how
            # `gather` came out of this census as a call handing a `SIMD` to a
            # `Pointer`.
            recv = call.func.obj if isinstance(call.func, F.MemberExpr) else None
            implicit = recv is None and callee in method_names
            args = list(call.args or [])
            pairs = ([] if implicit else ([(0, recv)] if recv is not None else [])) \
                + [(i, a) for i, a in enumerate(args)]
            convs = getattr(fn, "param_convs", None) or {}
            for i, (pname, ann) in enumerate(getattr(fn, "params", None) or []):
                if not isinstance(pname, str) or not ann:
                    continue
                # A MUTATING parameter (`out node: Node[T]`) is not in the
                # argument list at all — the callee hands it back — so comparing
                # it with `args[0]` reports every such call as handing the wrong
                # thing to the callee's first parameter, which is how
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
                    rows.append((path, callee, pname, struct_name, pos, arg,
                                 reader))


def what_is_passed(arg, struct_name, types, structs_by_name):  # noqa: C901
    """`"agrees"`, or the bucket this argument falls in.

    FOUR buckets, and the split is the instrument's honesty about what a parse
    can decide:

      * `"agrees"` — the argument is a value of the declared struct, which is
        four shapes: a name `Types` has typed as that struct, a construction of
        it (`S()`, `Self()`, `S[D, N]()`), a CALL to a function declared here
        with that return type, and a subscript of a `List[It]` / a field of a
        struct declared with it. The last two are the ones this instrument could
        not read before, and they are most of what it had.
      * `"DISAGREES …"` — `Types` derived a type for the argument and it is not
        the declared one. A name declared as something else, a construction of a
        DIFFERENT struct of the same field count (reported as such, because it is
        a different bug with a different repair), an arithmetic or unary result,
        a literal, a subscript of a `List[Other]`, a field whose declared type is
        `Other`.
      * `"MAYBE …"` — the argument is an expression whose type THIS FILE does
        not state: an unannotated name, a subscript of a container with no
        element type, a field of a struct this file does not define. The element
        type is exactly the question being asked and nothing here derives it.
        Every measured false positive this instrument has is this row.
      * `"UNREAD …"` — a CALL to a callee this file does not define, whose
        return type is a fact about another declaration.
    """
    if arg is None:
        return "agrees"
    derived = types.base_name(arg)
    if derived is not None:
        if derived == struct_name or derived == "Self":
            return "agrees"
        # A derived type that is not a struct of this file cannot be the
        # declared struct, which IS one: that is what makes this DECIDED rather
        # than a maybe. `struct_name in structs_by_name` is the caller's filter,
        # so `derived` being a struct of ANOTHER module lands here too, and
        # correctly — it is not this struct.
        if derived in structs_by_name and types.constructs(arg, derived):
            # A CONSTRUCTION of another struct with the same field count is the
            # one derived type this instrument will not call a disagreement: it
            # has the same layout, so the slot the callee reads is the same slot
            # the caller filled, and that is a different bug with a different
            # repair. Anything else that derives `Other` is an `Other` whatever
            # its width — a field read, or a call whose declared return type is
            # `Other` — so the width question is asked of constructions only,
            # which is the shape the old reader could recognise at all.
            other = structs_by_name[derived]
            if len(getattr(other, "fields", None) or []) == len(
                    getattr(structs_by_name[struct_name], "fields", None) or []):
                return ("MAYBE a construction of %s, which has the same field "
                        "count and so the same layout" % derived)
        return "DISAGREES a value of %s" % derived
    if isinstance(arg, F.IdentExpr):
        # A name whose TYPE this file does not state carries no evidence either
        # way — an unannotated parameter, a name from a `from … import`, a legacy
        # custom `self`, or a name bound from a call or a field read whose own
        # type is not derived here — so it is MAYBE rather than a contradiction.
        # Only a name DECLARED as something else is decided, and that is the line
        # above; which of the three it is does not change what a reader can do
        # with the row, so the message does not enumerate them.
        return "MAYBE a name whose type this file does not state"
    if isinstance(arg, F.CallExpr):
        return "UNREAD a call to %s()" % (M.call_callee_name(arg.func)
                                          or "an unnamed callee")
    if isinstance(arg, F.SubscriptExpr):
        return "MAYBE a subscript"
    if isinstance(arg, F.MemberExpr):
        return "MAYBE a field read"
    if isinstance(arg, F.UnaryOp):
        if getattr(arg, "op", None) == "^":
            return what_is_passed(getattr(arg, "operand", None), struct_name,
                                  types, structs_by_name)
        return "DISAGREES a %s unary result" % getattr(arg, "op", "?")
    return "DISAGREES a %s" % type(arg).__name__.replace("Expr", "").lower()


def candidates(parsed, rows):
    """(`rows the refusal would produce`, `how many (callee, parameter) pairs
    the file was asked about`).

    The first half is one entry per (file, callee, parameter) whose EVERY call
    site fails to agree, as `(path, callee, parameter, struct, n sites, whys)`.

    Split out of `main` so `test_formal_declared_param_census.py` can ask the
    same question of a source it wrote, rather than re-deriving the grouping —
    two groupings are two verdicts, and the second one is the one nobody reads.
    """
    grouped = collections.OrderedDict()
    for path, callee, pname, struct_name, i, arg, reader in rows:
        grouped.setdefault((path, callee, pname, struct_name), []).append(
            (i, arg, reader))
    out = []
    for (path, callee, pname, struct_name), sites in grouped.items():
        stmts = parsed[path]
        structs_by_name = {getattr(s, "name", None): s for s in stmts
                           if isinstance(s, F.StructDef)}
        whys = [what_is_passed(arg, struct_name, reader, structs_by_name)
                for _i, arg, reader in sites]
        if any(w == "agrees" for w in whys):
            continue
        out.append((path, callee, pname, struct_name, len(sites), whys))
    return out, len(grouped)


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
    out, groups = candidates(parsed, rows)
    decided = [r for r in out
               if all(w.startswith("DISAGREES") for w in r[5])]
    print("scanned %d .mojo files; %d (callee, parameter) pairs with a "
          "struct-typed parameter called in their own file"
          % (files, groups))
    print("…no call site agrees with the declaration: %d pairs in %d files"
          % (len(out), len({os.path.relpath(r[0], HERE) for r in out})))
    print("…of those, EVERY site is a DECIDED disagreement: %d pairs in %d "
          "files — the rows a reader can act on without a type checker"
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
    print("MAYBE / UNREAD (an element type or a return type this file does not "
          "state):")
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
