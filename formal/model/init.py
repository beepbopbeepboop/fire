from . import *

# ── `__init__`'s ASSIGNMENTS: a second source for a field's type ─────────
#
# `struct_field_declared_type` above reads a field's type out of the class
# body's ANNOTATION, and it has exactly one source, which left this shape
# refused by name:
#
#     class Tail:
#         __slots__ = ('limit', '_chunks', '_size')
#         def __init__(self, limit=4 << 20):
#             self.limit, self._chunks, self._size = limit, [], 0
#
# Nothing here is unusual Python, and nothing here declares a type — but
# `self._chunks = []` says what the slot holds every bit as plainly as
# `var _chunks: List[Int]` does, and this path consumed only the annotation.  So
# the answer it gave was "the declared type is the only thing here that could say
# so, and it does not", about a class that had said so in the only other way
# Python has.  `FORMAL_class_assigns_its_fields_in_init`.
#
# WHAT THE ASSIGNED VALUE IS EVIDENCE FOR, and what it is not, is the whole of
# the safety argument, so it is stated before the code:
#
#   * `__init__` is evidence about a field's TYPE and never about its VALUE.
#     Premise (B2) is that `S()` does not run `__init__` on this path, so the
#     word in a fresh instance's slot is whatever the CONSTRUCTOR stores there —
#     a class-level default, a zero, or a nested frame address the constructor
#     itself placed.  Reading the type off the assignment is therefore reading a
#     fact about the class; reading the VALUE off it would be reading a word
#     that is not in the image.  Every gate that turns a type into a VALUE
#     (`struct_field_kind`'s materializable-default test, `declared_type_kind`'s
#     table) is downstream of this and unchanged, so a class-level default is
#     still the only thing that can supply one.
#   * `__init__` and ONLY `__init__`. An assignment in an EXECUTED method is a
#     real write, which is `struct_fields_written_outside_init`'s business and
#     stays there: a written field answers `_REASSIGNED` and is refused, and it
#     must not instead answer "the type is a frame" and place one.
#   * UNANIMITY OR NOTHING, the same rule `ValueKinds._bind` applies to a local
#     name and for the same reason: two assignments that classify differently, or
#     one that classifies and one that cannot, give no answer at all.  Picking
#     either would make the answer depend on which use site asked.
#
# The classifier is deliberately short, because each row is a case where the
# VALUE settles the question no matter what the program does later, and the
# omitted ones are all "not provable":
#
#   * `S()` where `S` is a bare name — a construction of the struct named `S`.
#     If `S` is one of THIS UNIT's framed structs the slot holds that struct's
#     address, which is a nested frame the constructor places; if it is
#     anything else it is provably not one.  One recogniser, both answers, and
#     the answer is looked up in `decls` by the caller exactly as an annotation
#     would be — which is why this is evidence about a NAME and not a decision.
#   * a container literal — `[]`, `{}`, `()`, `{…}`: a container, and a
#     container is a frame-allocated blob on this path, never a frame address.
#   * a literal scalar — a string, an int, a float, a bool, `None`: a word.
#
# Everything else is the untyped direction: a name, a member, a ternary, a
# comprehension, a call with a non-name callee, a subscripted callee
# (`Pointer[Int](…)` — the base name there is the CONSTRUCTOR's, which is not
# what the annotation would have said).  Returning None for those is the safe
# direction twice over: no nested frame is placed, and no frame diagnostic is
# suppressed.


# The second evidence source for a field's type, and the one that unblocks the
# largest remaining group in the sweep: a class that ASSIGNS its fields in
# `__init__` and declares none.  Both shapes are ordinary Python and both are
# the whole field set (`struct_field_names` already counts the `self.<name>`
# reads, which is why such a class measures as a multi-field framed struct at
# all) — so the slot exists, the frame exists, and the only thing missing was
# the name of the type in it.
#
# Why the assignment is EVIDENCE rather than a guess, and the answer is premise
# (B2) rather than anything about `__init__`.  `S()` does not run `__init__` on
# this path (`FRAME_FIELD_BLOB_PREMISE_B2`): every slot's value is the
# constructor's, and for a typed-nested field the constructor's value is the
# nested frame it PLACES.  So what `__init__` says about the field's type is not
# a description of a store that happens — it is the only place the source NAMES
# the type, and the type is all the decision needs.  That is also why a
# conditional, repeated or `None`-defaulted assignment inside `__init__` is not a
# problem here while it would be in any other inference: the value that matters
# never comes from those lines.
#
# What it is NOT allowed to be is a type this module cannot lay out.  The
# inference names a struct only when `decls` has it, so it can never turn an
# unknown name into "provably a plain value" — `field_type_is_value`'s
# dangerous direction — by accident.  A call to something else, a name, a
# literal, an augmented assignment: all of them yield no evidence, which is the
# absent answer, and the field stays refused with the disagreement spelled.
def _method_field_stores(m, receivers) -> list:
    """`[(field_name, value_node), …]` — one method's `self.<name> = …` stores.

    The scan, over ONE method body, and the only place it is written: the two
    questions asked of it differ in *which methods they ask about* and agree
    about everything else, so a second scanner would be a second thing that
    could learn a spelling the first one does not read.

    Both assignment spellings matter and only one of them is a `MemberExpr`
    target of a plain `AssignStmt`: `self.a, self.b = limit, [], 0` parses as an
    `AssignStmt` whose TARGET is a `TupleExpr` of `MemberExpr`, so a scan
    looking for `target: MemberExpr` reads a class as assigning nothing at all.
    The tuple form is read through `_init_statement_field_stores` — the same
    table `init_body_stores` inlines from — so a type can never be read out of a
    store the emitter is going to refuse.

    `MultiAssignStmt` (`a = b = v`) is the other shape, and the parser gives the
    chain ONE node with a `targets` list rather than a chain of nodes, so
    `iter_nodes` alone would miss every target on it.

    An `AugAssignStmt` contributes the FIELD and no value: `self.n += 1` in
    `__init__` says the slot is a counter and says nothing about its type.
    """
    out = []
    for node in iter_nodes(getattr(m, "body", None)):
        if isinstance(node, F.AssignStmt):
            for target, value in _init_statement_field_stores(node,
                                                              receivers) or ():
                out.append((target.member, value))
            continue
        if isinstance(node, F.MultiAssignStmt):
            # `a = b = v` is a chain of `AssignStmt` in this AST, and the
            # parser gives the chain ONE node with a `targets` list, so this
            # is the shape `iter_nodes` alone would miss.  Every target here
            # is a plain name or a member — the grammar does not admit a
            # chain of tuple targets — so one value serves them all.
            for t in (getattr(node, "targets", None) or []):
                if isinstance(t, F.MemberExpr) and isinstance(t.obj, F.IdentExpr) \
                        and t.obj.name in receivers:
                    out.append((t.member, node.value))
    return out


def _init_field_assignments(struct_def) -> dict:
    """`{field_name: [value_node, …]}` — what `__init__` assigns to each field.

    `__init__` alone, every spelling of `self.<name> = …` it uses, and the
    UNION of a field's assignments rather than the last one seen: unanimity is
    decided by `struct_init_field_types`, and it can only be decided over all
    of them.  The scan itself is `_method_field_stores`; what is narrow here is
    the method set, and `field_stores_a_caller_frame` asks the same scan about
    every method for the same reason this one asks it about one.
    """
    out: dict = {}
    for m in struct_methods(struct_def):
        if m.name != "__init__":
            continue
        for name, value in _method_field_stores(m, struct_receivers(struct_def)):
            out.setdefault(name, []).append(value)
    return out


def method_field_assignments(struct_def, name) -> list:
    """`[(method, value_node), …]` — every method's `self.<name> = …`.

    The all-methods projection of the same scan `_init_field_assignments` reads,
    and it carries the METHOD because the reader needs it: `field_stores_a_caller_frame`
    asks whether the stored value is one of *that method's own* annotated
    parameters, and a value read without knowing which method wrote it cannot be
    looked up in the right parameter table.
    """
    receivers = struct_receivers(struct_def)
    return [(m, value)
            for m in struct_methods(struct_def)
            for fname, value in _method_field_stores(m, receivers)
            if fname == name]


# The type NAME an assigned value provably has, for the rows the classifier can
# settle.  A key that is absent is the untyped direction; the value is what
# `struct_field_declared_type` hands back as the "annotation", which is why each
# one is spelled as a bare identifier — a message quoting it reads as a type, and
# `annotation_base_name` on it returns the same name.
#
# `int` and `str` are the PYTHON spellings, not this project's (`Int`,
# `String`), and that is deliberate in both directions.  These names are only
# ever consumed to answer "is this a FRAME of this unit", where "the name is not
# a struct this unit declares" IS the answer — so the spelling must be one that
# CANNOT name a struct of this unit, which is what
# `init_literal_type_names_are_not_structs` below enforces.  Spelling it `Int`
# instead would make it a lookup that could HIT a struct of this module named
# `Int`, which is a different claim about the same source text.
_INIT_ASSIGNED_BASE_NAMES = {
    F.ListExpr: "list", F.TupleExpr: "tuple", F.SetExpr: "set",
    F.DictExpr: "dict", F.StringLiteral: "str", F.IntLiteral: "int",
    F.FloatLiteral: "float", F.BoolLiteral: "bool",
}


# The names `_INIT_ASSIGNED_BASE_NAMES` spells a LITERAL with, and the reason
# they are looked up in `structs_declared` rather than in the struct table.
#
# `self.x = []` says the slot holds a list, and a list on this path is a
# frame-allocated blob, never a frame address — so the answer for a literal is
# decided without consulting a struct table at all.  It has to be, because the
# spelling is a PYTHON builtin name and a module is free to declare a struct
# called `list`: without this guard, a `struct list` anywhere in the unit would
# turn every `self.x = []` in it into "a nested frame", and the constructor would
# place a frame in a slot that holds a blob.  That is the silently-wrong
# direction, and the guard is the whole of it.
#
# The Mojo spellings (`List`, `Int`, `String`, …) are deliberately NOT here:
# they are ordinary type names that a struct of this unit may well be called,
# and `decls.get("List")` answering is then CORRECT.  Measured over this
# repository and `../modular/mojo/stdlib/std` (714 structs): zero structs named
# after any name in this set, so this is a guard and not a compatibility shim.
_INIT_LITERAL_TYPE_NAMES = frozenset(_INIT_ASSIGNED_BASE_NAMES.values())


def structs_declared(base, decls: dict):
    """`decls`'s StructDef for a type name, or None — refusing a builtin name.

    The ONE lookup every "is this a frame of this unit" question makes, and the
    reason it is a function rather than `decls.get` at each site: a type name
    that is a Python builtin cannot be a struct of this unit on this path, so
    the lookup must return None for it even if a module declared something by
    that name.  `init_literal_type_names_are_not_structs` says why, and
    `assigned_value_base_name` is the only producer of such a name.
    """
    if not isinstance(base, str) or base in _INIT_LITERAL_TYPE_NAMES:
        return None
    return (decls or {}).get(base)


def assigned_value_base_name(value, decls: dict = None):
    """The type NAME an assigned value provably holds, or None.

    The classifier the second evidence source is built on, and its `None` is the
    answer for anything the source does not settle — see the note above for the
    cases and for why each omission is the safe direction.

    `decls` is `{name: StructDef}` for the structs THIS MODULE DECLARES, and it
    is what makes the CONSTRUCTOR row conditional.  `self.x = Inner()` says the
    slot holds an `Inner`, and if `Inner` is one of this unit's framed structs
    that is a nested frame the constructor places; `self.x = make()` says the
    slot holds whatever `make` RETURNS, which is not a type at all and could be
    an `Inner`, a list, or an int.  Confusing the two is the mistake this
    parameter exists to prevent, and it is not a small one: a bare `make` read as
    "a type that is not a struct of this unit" answers the frame question
    "provably not a frame" about a slot that may well hold one.

    So WITHOUT `decls` the constructor row contributes nothing.  That is the safe
    direction, and it is the same one the whole rule is arranged around: an
    absent answer removes a name from the typed set, and a name that is not in the
    typed set can neither place a frame nor suppress a frame diagnostic.
    """
    kind = _INIT_ASSIGNED_BASE_NAMES.get(type(value))
    if kind is not None:
        # `type()` rather than `isinstance` because `BoolLiteral` and
        # `IntLiteral` are separate dataclasses and a subclass that changed its
        # meaning would silently take the wrong row.
        return kind
    if isinstance(value, F.CallExpr) and isinstance(value.func, F.IdentExpr):
        # A subscripted callee is not reached here (`value.func` is an
        # `IdentExpr`), so `Pointer[Int]()` and `Int(x)` stay apart.
        name = value.func.name
        if decls is None or not name.isidentifier():
            return None
        return name if structs_declared(name, decls) is not None else None
    if isinstance(value, F.IdentExpr) and value.name == "None":
        return "None"
    return None


def struct_init_field_types(struct_def, decls: dict = None) -> dict:
    """`{field_name: (base, spelling)}` — the type `__init__`'s assignments AGREE on.

    Unanimity or nothing, exactly as `ValueKinds._bind` binds a local name:
    every assignment of a field has to classify, and they have to classify the
    same way.  One that does not (`self.x = argv if argv else []`), or one that
    classifies to nothing (`self.x = make()`, without `decls`), or two that
    classify differently (`self.x = Scope()` and `self.x = None`) leave the field
    out of the answer — which is what puts it back on `_NOT_TYPED` and on
    today's refusal.

    Every field assigned NOTHING at all is left out too, so this is a map of the
    fields `__init__` says something about rather than a census of them.  The
    class-level default, the annotation and the field SET are the other three
    sources and each of them is somebody else's function.

    `decls` is `assigned_value_base_name`'s and its absence is why a
    constructor-only field is untyped for a caller that cannot supply it.
    """
    out = {}
    for name, values in _init_field_assignments(struct_def).items():
        bases = {assigned_value_base_name(v, decls) for v in values}
        if len(bases) != 1:
            continue
        base = bases.pop()
        if base is None:
            continue
        out[name] = (base, base)
    return out


def struct_init_field_type_why(struct_def, name, decls: dict = None) -> str:
    """Why `__init__` said nothing classifiable about `name` — for a refusal.

    The negative half of `struct_init_field_types`, and it exists because a
    refusal that says "no evidence" sends the reader looking for evidence the
    tool cannot read.  It says which of the three shapes it is: never assigned,
    assigned something this classifier cannot reduce to a type, or assigned two
    different things.
    """
    values = _init_field_assignments(struct_def).get(name)
    if not values:
        return ("__init__ does not assign it at all, so the only things naming "
                "it are __slots__ or another method's read of it")
    bases = [assigned_value_base_name(v, decls) for v in values]
    named = {b for b in bases if b is not None}
    if not named:
        return ("__init__ assigns it values this path cannot reduce to a type "
                "— a name, a member, a ternary, a comprehension, or a call to "
                "a function this module does not declare as a type — so there "
                "is no type to read")
    if len(named) > 1:
        return (f"__init__ assigns it {len(bases)} different types "
                f"({', '.join(sorted(named))}), so there is no single answer")
    return (f"__init__ assigns it a type this path cannot classify "
            f"({bases[0]!r}), alongside an assignment it can")


def struct_fields_written_outside_init(struct_def) -> set:
    """The fields some EXECUTED method of this struct assigns to.

    `__init__` is excluded, and that exclusion is premise (B2) again: it does
    not run on this path, so an assignment there is not a write.  See
    `frame_field_premise` for why the exclusion is a stated premise rather than
    a habit.

    This is the set that decides whether a field can hold a PLACED nested frame,
    and the reason is not conservatism for its own sake.  A placed nested frame
    is sound exactly while the slot still holds it, so the only field that may
    be treated as one is a field nothing writes: a field that IS written holds
    whatever the assignment put there, and on this path a value of a multi-field
    struct is a frame address belonging to whichever function ran the
    assignment.  Treating a written field as ours is how the constructor's
    lifetime guarantee would be lost while still being claimed.
    """
    receivers = struct_receivers(struct_def)
    out = set()
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            continue
        for node in iter_nodes(getattr(m, "body", None)):
            # An augmented assignment is a read AND a write, so it disqualifies
            # a field exactly as a plain one does; both node types are taken
            # here rather than only `AssignStmt` because the two have the same
            # `target` shape and treating one as read-only would leave
            # `self.inner.a += 1` looking like a field nobody writes.
            if not isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
                continue
            tgt = getattr(node, "target", None)
            if isinstance(tgt, F.MemberExpr) and isinstance(tgt.obj, F.IdentExpr) \
                    and tgt.obj.name in receivers:
                out.add(tgt.member)
    return out


def struct_nested_frame_fields(struct_def, decls: dict, depth=None):
    """`[(field_name, slot, struct)]` — the fields of `st` that hold a nested frame.

    The PLACEMENT decision, and the reason a declared type is not the
    silently-wrong direction: this is the list the constructor walks to reserve
    a     block per field and store each nested frame's address into its own slot.
    A declared type that this function did not place is not used, so the
    negative cases (`frame_field_type_candidates`'s `None`) cannot leak into
    the emitter.

    Four conditions, and all four are load-bearing:


      * the field is in `struct_frame_slots`, so the frame layout has a slot to
        put an address in — the same discipline `struct_frame_slot` applies;
      * every binding of the name agrees on a declared type naming a framed
        struct of this module (`frame_field_type_candidates`);
      * **nothing writes the field outside `__init__`**
        (`struct_fields_written_outside_init`).  The third is the one an early
        version of this function left out, and leaving it out is not a
        simplification: it makes a REASSIGNED field look like the constructor's
        frame, and the constructor's lifetime argument — the whole reason the
        nested frame is better than the refusal it replaces — then does not
        apply to the value actually in the slot.  Measured on the stdlib sweep,
        dropping the condition moved 164 files' verdicts, every one of them
        because ordinary code (`self._bytes = remaining`) was being refused for
        a frame the program had just replaced.
      * **the constructor BUILDS one there**, rather than storing a name
        (`init_stores_a_parameter_struct`).  The fourth is the newest and the
        smallest in source and the largest in what it unblocks: a DELEGATING
        constructor — `self.src = r` where `r: R` is `__init__`'s own annotated
        parameter — does not build a nested frame in that slot, it stores the
        CALLER's frame address, so the slot is a pointer slot and reserving a
        block for it is what makes the delegating store unsound
        (`formal/build.py`'s `_frame_field_store_is_sound`, whose lifetime
        argument the placement was cancelling out).  It is the last reason
        `“FORMAL_receiver_stored_in_a_field: a frame address in a struct field”`'s delegating row was still
        refused, and the predicate is asked only AFTER the first three so it can
        only ever REMOVE a placement.

    A declared type this function did not place is not used, so the negative
    cases (`frame_field_type_candidates`'s `None`) cannot leak into the emitter.

    `depth` is the recursion bound; a chain longer than it is dropped from the
    answer rather than silently truncated, which is what makes the bound a
    refusal instead of a wrong layout.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    out = []
    if depth <= 0:
        return out
    written = struct_fields_written_outside_init(struct_def)
    for name in struct_frame_slots(struct_def):
        if name in written:
            continue
        nested, (disagree, _rows) = frame_field_type_candidates(
            [struct_def], name, decls)
        if nested is None or disagree:
            continue
        slot = struct_frame_slot(struct_def, name)
        if slot is None:
            continue
        if init_stores_a_parameter_struct(struct_def, name, decls) is not None:
            continue
        out.append((name, slot, nested))
    return out


def nested_frame_hop_unplaced(chain, base, field, rows) -> str:
    """An INTERMEDIATE hop of a nested read has no slot to load.

    Only reachable for a chain of three or more field accesses, because the
    first hop is the depth-2 case the two-level refusal already covers. It is
    its own message and not a reuse of that one because the two say different
    things: that one says the OUTER field is a plain VALUE, and this says a
    field the chain has already agreed is a nested FRAME has no index in the
    layout — which is a disagreement between two tables rather than a missing
    type, and a reader sent to add an annotation would find one already there.
    """
    return (
        f"{chain} reads through {base}.{field}, and the field is agreed to be "
        f"a nested FRAME — the hop before it named its struct and every "
        f"binding of it agrees — but there is no slot to load it from: a slot "
        f"index is what the read loads, and the layout for the struct that "
        f"declares {field!r} has none. That is a disagreement between the frame "
        f"layout and the declaration rather than a missing type, so adding an "
        f"annotation will not close it. The candidates for the field, for a "
        f"reader who wants them: {rows}"
    )


def struct_frame_bytes(struct_def) -> int:
    """How many bytes of stack one instance of this struct's frame occupies.

    8 per field, rounded UP to a multiple of 16 because that is the stack
    alignment AAPCS requires and the receiver frame is carved out of the
    function's own prologue rather than out of the expression-evaluation push
    area — so the rounding has to keep the frame pointer 16-byte aligned."""
    n = 8 * struct_field_count(struct_def)
    return n + (-n % 16)


def struct_field_default(struct_def, name,
                         structs_by_name: dict = None) -> tuple:
    """`(kind, payload)` — the word slot `name` holds in a FRESH instance.

    The per-field reading of the same rule `struct_default_word` states for a
    one-field struct, and deliberately the same rule: only a LITERAL class-level
    initializer is materialized, because a literal has no free names and so has
    the same value at every call site in every function.  Anything else — a
    name, a call, a container — is `(DEFAULT_OPAQUE, name)`, and the caller
    refuses the constructor naming the field rather than substituting 0, which
    is the one answer a formal backend may not invent.

    A field with no class-level initializer at all (`x: Int`, or a field only
    ever assigned in `__init__`) is `(DEFAULT_NONE, None)`: a fresh word of
    zeros, which is what the constructor has always emitted for one.

    `structs_by_name` is what adds ONE shape to "a literal", and it is a shape
    rather than a second rule: a default that NAMES another class's constant
    (`origin: TypeOrigin = TypeOrigin.DEFAULT` — the enum idiom, and this
    repository's `type_system.py`) is that constant's value, and
    `class_constant_word_in` is the same resolution `formal/build.py` performs
    when the READ is substituted. It is a parameter rather than a global
    because a declaration is not a fact about itself: answering it needs the
    image's other declarations, and the three readers below that have no table
    get exactly the literal-only answer they got before.

    **AN INHERITED name is answered from the BASE's initializer**, which
    `attach_inherited_fields` carried over with the name. `Base.x = 5` /
    `class Sub(Base): pass` / `Sub().x` is 5 in CPython, and a subclass that
    declares nothing of its own is exactly the case where the class body has no
    node to read — so the `(DEFAULT_NONE, None)` this used to return, a zero
    word, was a wrong answer rather than a missing one. A name the subclass
    re-declares is answered from the subclass's own body above, which is
    CPython's rule for a re-declared field."""
    # The names THIS struct binds, which is what `fold_literal_expr`'s `bound`
    # is for: a field or a bracket parameter named `len` shadows the builtin
    # inside this class body, and a fold that read it as the builtin would put a
    # number in a slot the source never computed. Derived here rather than
    # threaded because a field default IS this struct's own initializer.
    bound = struct_bound_names(struct_def)
    for field in struct_fields(struct_def):
        if struct_field_name(field) == name:
            value = getattr(field, "value", None)
            kind, payload = _field_default_word(struct_def, name, value,
                                                structs_by_name, bound)
            return kind, payload
    inherited = getattr(struct_def, "_inherited_field_defaults", None) or {}
    if name in inherited:
        value = inherited[name]
        kind, payload = _field_default_word(struct_def, name, value,
                                            structs_by_name, bound)
        return kind, payload
    kind, payload = _field_default_word(struct_def, name, None,
                                        structs_by_name, bound)
    return kind, payload


def _field_default_word(struct_def, name, value, structs_by_name, bound=()):
    """One field's initializer read as a word — the `Optional` row included.

    The `Optional` row is asked only when the initializer IS a `None` (or is
    absent), because that is the one case where "no initializer" and "empty
    `Optional`" are the same fact; an `Optional` field initialized with a
    literal has an ordinary literal word and the ordinary rule is right. It
    returns `(DEFAULT_INT, niche)` so both readers of a field default —
    `struct_field_default` here and `struct_default_word` for the one-field
    case — agree about what an absent `Optional` is, which is the same
    one-reader rule the rest of this file keeps.

    **`bound` is threaded rather than dropped**, and it is the difference between
    this and the version that read the initializer directly: a field or a
    bracket parameter named `len` shadows the builtin inside this struct's own
    class body, and a fold that read it as the builtin would put a number in a
    slot the source never computed (`struct_bound_names` above for where the
    names come from, `literal_default_word`'s own use of them).  Extracting the
    row into a function is the right shape — the `Optional` case belongs in one
    reader rather than in the two call sites — and a helper that cannot be handed
    the shadowing evidence is a helper that answers a question the caller's
    answer depended on.
    """
    if is_none_expr(value) or value is None:
        niche = optional_field_none_word(struct_def, name, structs_by_name)
        if niche is not None:
            return (DEFAULT_INT, niche)
    if structs_by_name is None:
        kind, payload = class_constant_word(name, value, bound)
    else:
        kind, payload = class_constant_word_in(structs_by_name, value,
                                               bound=bound)
    return (kind, name if kind == DEFAULT_OPAQUE else payload)


def struct_frame_defaults(struct_def, structs_by_name: dict = None) -> list:
    """`[(kind, payload)]` per slot, in slot order — what `S()` must store."""
    return [struct_field_default(struct_def, name, structs_by_name)
            for name in struct_frame_slots(struct_def)]


def struct_frame_representable(struct_def, structs_by_name: dict = None):
    """`(ok, reason)` — can `S()` bring every one of this struct's fields up?

    `ok` is False exactly when some field's declared default is a real value
    this path cannot evaluate at a call site.  The reason names the field,
    because a refusal that does not is a refusal the reader has to re-derive."""
    for name, (kind, payload) in zip(
            struct_frame_slots(struct_def),
            struct_frame_defaults(struct_def, structs_by_name)):
        if kind == DEFAULT_OPAQUE:
            return (False, name)
    return (True, None)




# ── THE THREE CONSTRUCTION SHAPES ────────────────────────────────────────
#
# `S()`, `S(a, b, …)` and `S(x)` are three different lowerings and until now
# only the first existed.  What they have in common is that all three end with
# a FRESH BLOCK whose bytes belong to the function that created it, so all
# three are confined to that function's activation and none of them can hand
# the block anywhere.  That confinement is what makes the other two
# representable, and it is the whole content of this section — so it is worth
# stating precisely, because it is the difference between the second and third
# shapes being lowerings and being wrong answers:
#
#     A block built at a construction SITE belongs to the function the site is
#     in, and `_check_frame_escapes` refuses every channel by which it could
#     leave that activation: returning it, putting it in a container, parking
#     it in another object's field, handing it to a callee in a non-first
#     parameter position.  So the object is read only while its creator is
#     still on the stack, and:
#
#       * a WORD stored into one of its slots came from a live local or
#         parameter of that same function or of an ancestor of it, so it
#         outlives the block's last read.  A frame address is the interesting
#         case of that and is ALLOWED here — which is exactly what the
#         assignment form `o.inner = i` may not be, and the difference is
#         worth naming because the two look identical in the source: `o` in
#         `o.inner = i` may be an object built by an ANCESTOR, so the slot
#         outlives `i`'s creator and the next use of `o` reads reclaimed
#         stack.  At a construction site the object is new here, so there is
#         no such ancestor-built object to be.
#
# The two per-argument checks below are the ones that argument does NOT
# survive, and each is refused by name rather than stored.

CONSTRUCTION_DEFAULT = "default"
CONSTRUCTION_POSITIONAL = "positional"
CONSTRUCTION_COPY = "copy"
# The FOURTH shape, and the one that makes the other three exhaustive over what
# Mojo source can say.  `S(...)` on a struct that declares a user-defined
# `__init__` is a CALL to it — premise (B2) used to be the reason this path
# could not lower that, and the resolution is that the constructor need not be
# CALLED to be RUN: a body this path can express becomes the same stores, at the
# same construction site, in the same block.  See `init_body_stores`.
CONSTRUCTION_INIT = "init"
# `S(a=1, b=2)` — the KEYWORD form — is NOT a kind of its own.  It used to be,
# as `CONSTRUCTION_KEYWORD`, with its own resolver
# (`keyword_construction_stores`) beside `_construction_field_bindings`: two
# implementations of one rule ("a positional takes the fields in declaration
# order, a keyword names its field, nothing twice, the rest keeps its
# class-level default") that disagreed about the last clause, because the
# keyword resolver filled an unfilled field from its default without asking
# whether the field HAD one.  `_construction_field_bindings` is now the only
# reader, so a keyword construction is a POSITIONAL construction whose bindings
# some keywords supplied — `StringSlice(unsafe_from_ptr=p)` (the corpus's own
# spelling, `std/collections/string/string_slice.mojo`) and
# `Config(7)` on `width = 80, height = 24` are the same shape — and the
# payload is `CONSTRUCTION_INIT`'s when a field is left at its default and
# `CONSTRUCTION_POSITIONAL`'s when every field is covered.
#
# `construction_keyword_refusal` is what the three ways it cannot bind a keyword
# say, one sentence each.


def _construction_arg_spelling(arg) -> str:
    """How a refusal names the argument it is about.

    A refusal that says "an argument" when the source has four of them sends
    the reader to count them again, so the argument is named the way the
    source spells it."""
    if isinstance(arg, F.IdentExpr):
        return f"argument {arg.name!r}"
    if isinstance(arg, F.MemberExpr):
        return f"argument {_member_chain_text(arg)}"
    if isinstance(arg, F.CallExpr):
        # `call_callee_name`, so a specialization is named as the function it
        # specializes: `mklist[1]()` is the call to `mklist`, and a refusal that
        # says `?` sends the reader to a callee that is not in their source.
        # `None` — a dotted name or a computed callee — stays `?`, which is the
        # honest answer for a callee this path cannot name.
        callee = call_callee_name(arg.func)
        return f"the call to {callee!r}" if callee is not None \
            else "the call to '?'"
    if isinstance(arg, (F.ListExpr, F.DictExpr, F.TupleExpr)):
        return "a container literal"
    if isinstance(arg, (F.IntLiteral, F.BoolLiteral, F.StringLiteral)):
        # The VALUE, not the node class: `an argument of type IntLiteral` tells
        # a reader nothing they can look for in their own source, and the
        # literal's spelling is the one thing about it that is in the source.
        return f"the literal {getattr(arg, 'value', '?')!r}"
    return f"an argument of type {type(arg).__name__}"


def _member_chain_text(node) -> str:
    """`a.b.c` for a MemberExpr chain, without importing build.py's walker.

    Deliberately a second, tiny implementation rather than a shared import:
    `formal/model.py` is imported by the BACKENDS as well as the build pass and
    must not acquire a dependency on it, and a member chain is three lines.
    """
    parts = []
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if isinstance(node, F.IdentExpr):
        parts.append(node.name)
    return ".".join(reversed(parts))


def construction_dead_blob_refusal(name: str, field: str, arg,
                                   evidence: str = "declared") -> str:
    """A construction argument that is a blob belonging to a CALLEE.

    The one per-argument hazard the confinement above does not cover, and the
    reason it is a call and not a container: a container LITERAL is built here,
    in the function whose block is being filled, so it lives at least as long
    as the slot; a name was bound here or in an ancestor, so the region it
    names does too.  A CALL is neither — `List[T]()` and every other container
    constructor on this path is a bump-allocated region of the CALLEE's own
    reserved scratch, and the callee has returned by the time the store
    happens.  Storing it would give `self.<field>.append(x)` in a method a
    blob in reclaimed stack, which is premise (B1)'s hazard arrived at from a
    direction the premise's own check does not walk: `check_frame_field_blob_
    premises` looks at what a METHOD BODY writes, and this is a constructor
    argument.

    `evidence` is WHICH of the two sources said so, and it is a parameter
    because the message has to name the one that fired: a reader who is told
    "is declared to return a container" about a callee that declares nothing
    goes looking for a declaration that does not exist, and comes back
    concluding the compiler cannot see what is in front of it.  `"declared"` is
    `BLOB_TYPE_NAMES` on the return annotation; `"inferred"` is
    `callees_returning_containers` on the callee's return statements, which is
    what says it when the callee declares no return type at all.

    The exception is a call to a struct this path PLACES: that is a frame
    address, one word, with a lifetime the frame layout governs, and
    `_callee_is_placed_frame` is the one predicate that knows.
    """
# `call_callee_name`, for the reason `_construction_arg_spelling` gives: a
    # specialization names the same function as its bare twin, and a message
    # that says `?()` where the source says `mklist[1]()` sends the reader to
    # look for a callee that is not there.  Measured: with this reading the
    # refusal fires for `Bag2(mklist[1](), 5)` — which BUILT before
    # `_construction_arg_is_dead_blob` learned the same name — and the message
    # names `mklist`.
    callee = call_callee_name(arg.func) or "?"
    because = (
        f"{callee}() declares no return type and every `return` in it yields a "
        f"container"
        if evidence == "inferred" else
        f"{callee}() is declared to return a container")
    return (f"constructing {name} with {_construction_arg_spelling(arg)} as "
            f"field {field!r} is refused on this path: {because}, and a "
            f"container on this path is a bump-allocated region of the CALLEE's "
            f"own reserved scratch, so by the time the constructor stores it the "
            f"bytes are reclaimed — and a method reaching through the slot "
            f"afterwards appends into reclaimed stack. A container LITERAL, or a "
            f"name bound here or in a caller, is fine for exactly the opposite "
            f"reason: it is built in a function that is still running, and so is "
            f"any call whose declared return type is not a container — and a call "
            f"that declares nothing at all and does not return a container "
            f"consistently either. Build the container and assign the field "
            f"after `S()`, which is the same program with a lifetime this "
            f"analysis can see")


def construction_arg_dead_blob_refusal(name: str, field: str, arg,
                                       rets=None, struct_def=None):
    """The refusal for `arg` if it is a callee's container, else None.

    ONE function rather than a predicate plus three `if refused:` sites at the
    three callers, because the two halves are not separable: the DECISION is
    which source of evidence fired and the MESSAGE names that source, so a
    predicate that returned a bool would force each caller to re-derive it and
    the three could drift.

    `rets` is `CalleeReturnTable` — the declared annotations plus the inferred
    reading — and a plain dict is accepted so that anything holding only the
    declared table keeps working with the declared-only answer.

    `struct_def` is the struct being CONSTRUCTED, and it is what
    `_callee_is_placed_frame` reads: the placed-frame callees are a fact about
    the unit that declares the struct, attached to the struct by
    `attach_placed_frame_callees`, and a caller that does not have it in hand
    gets the conservative answer (the callee is not placed) — which is a refusal
    rather than a wrong number.
    """
    evidence = _callee_container_evidence(arg, rets, struct_def)
    if evidence is None:
        return None
    return construction_dead_blob_refusal(name, field, arg, evidence)


def construction_frame_in_value_refusal(name: str, field: str, arg,
                                        struct_names) -> str:
    """A frame address as the whole value of a ONE-WORD struct.

    The one argument kind a framed construction accepts and a one-word one
    does not, and the asymmetry is the confinement argument read from the
    other side.  A framed object has a BLOCK, and a block is confined to the
    function that built it, so a frame address parked in one of its slots is
    read only while that function is still running.  A one-field struct has no
    block: its receiver IS the field, so the word is the struct, and this path
    has no lifetime analysis for a plain word at all — it can be passed to any
    callee, stored anywhere, and laundered past every frame check on the way,
    because a name bound from a ONE-word constructor is deliberately not a
    holder.  That is the same reason `byref_refuse_frame_address_in_a_field`
    exists, one level out.
    """
    who = ", ".join(struct_names) if struct_names else "another struct"
    return (f"constructing {name} with {_construction_arg_spelling(arg)} as "
            f"field {field!r} is refused on this path: that argument is the "
            f"ADDRESS of a {who} frame of 8-byte slots, and {name} has one "
            f"field, so its whole value IS that word — there is no block "
            f"confining it to the function that built it, and a one-field "
            f"struct's value is passed around as an ordinary word, which every "
            f"frame-lifetime check here is bypassed by. Copy the value out of "
            f"the frame first (`{name}(frame.field)`), which is the same "
            f"program with a lifetime this analysis can see")


def one_word_store_refusal(name: str, field: str, arg, candidates: dict,
                           rets=None):
    """The two refusals a ONE-WORD struct's own value has, or None.

    **One rule for both the POSITIONAL construction and a DECLARED
    `__init__`'s store, and the second caller is the reason this is a
    function.** A one-field struct's value IS its field, so an argument stored
    into that field is the whole value — and whether the argument got there by
    `S(x)` or by `self.inner = x` inside a constructor is not a fact about the
    lifetime argument at all: the constructor's store is inlined at the
    CONSTRUCTION SITE, so the word that lands in the caller's hand is the
    argument either way. Answering it on one path and not the other is how
    `struct Box: var inner: Opt` with `def __init__(self, o: Opt)` came to be
    planned as a plain inlined store while the same struct with no constructor
    was refused — the same word, the same hazard, two answers.

    ORDER, and it is the order the positional path has always used: the DEAD
    BLOB check first, because a container callee's address is a more specific
    fact about the argument than "it is a frame of some struct", and its
    message is the one a reader can act on.
    """
    refusal = construction_arg_dead_blob_refusal(name, field, arg, rets)
    if refusal is not None:
        return refusal
    src = _frame_source_structs(arg, candidates)
    if src:
        return construction_frame_in_value_refusal(
            name, field, arg, [s.name for s in src])
    return None


from typing import NamedTuple


class InitShape(NamedTuple):
    method: object
    params: object
    positional: object
    required: object
    optional: object
    required_names: object
InitShape.__doc__ = (
    "One `__init__` this struct declares.  A named tuple and not a bare one "
    "because the arity window below is arithmetic over four of the five "
    "fields, and `s.required + s.optional` is legible where `s[3] + s[4]` is "
    "a puzzle.  Unpacks as a 6-tuple, so the diagnostics that only need the "
    "shapes are unaffected.\n\n"
    "`required_names` is WHICH parameters have no default, which is not the "
    "first `required` entries of `params`: `def __init__(out self, a: Int = 3, "
    "*, b: Int)` has one required parameter and it is `b`.  It is carried "
    "rather than re-derived because the binder "
    "(`init_call_bindings`) needs it and a second walk of `param_has_default` "
    "would be a second answer to \"which parameters must this call supply\", "
    "and a disagreement between the two is a construction that binds a "
    "defaulted parameter and demands a missing one.")


def struct_init_shapes(struct_def) -> list:
    """`[(method, params, positional, required, optional)]` per declared `__init__`.

    The shapes of the struct's user-defined CONSTRUCTORS, which is a different
    question from its field list and the one that decides what `S(a, b)` means
    when `S` declares any.

    `required` counts the parameters with no default, EXCLUDING the receiver:
    `out self` is where the object is written, not something the caller passes,
    and counting it would make every arity in this file off by one.  The
    receiver is recognised per METHOD and by `method_declares_receiver`, so a
    class spelling it `this` is read the same as one spelling it `self` and an
    `@implicit` converting constructor — whose first parameter is an ordinary
    argument, not a receiver — keeps it.

    `params` is `[(name, default_expression)]` in DECLARATION ORDER with the
    receiver removed, and it is the binding order: positional argument `i` is
    parameter `i`, which is what turns a `__init__` body into stores.  `None` for
    a default means the parser recorded that the parameter has one without
    keeping the expression, and `init_body_stores` refuses rather than guessing.

    `positional` is how many of them a POSITIONAL call can reach — the index of
    the first keyword-only parameter, or all of them.  It is separate from
    `required + optional` because `def f(a, *, b)` has two parameters and one
    positional, and a call that binds `b` by position is a different program
    from one that does not.

    Empty when the struct declares no `__init__` at all, and that emptiness is
    the whole of the distinction: with no `__init__`, Mojo's `S(...)` fills the
    fields in declaration order, which is what `struct_frame_slots` describes
    and what the positional construction lowers.  With one, `S(...)` calls it.
    """
    out = []
    for m in struct_methods(struct_def):
        if m.name != "__init__":
            continue
        defaults = getattr(m, "param_defaults", None) or {}
        has_default = getattr(m, "param_has_default", None) or {}
        kwonly = set(getattr(m, "kwonly", None) or ())
        # The receiver of THIS method, not of the class. Two things were wrong
        # with asking `struct_receivers`, which is a class-wide SET:
        #
        #   * it is built from `method_receiver_name`, which takes the first
        #     parameter's name whatever it is called, so an `@implicit`
        #     CONVERTING constructor — `@implicit def __init__(_value: Int) ->
        #     Cell`, which has no receiver at all and whose first parameter is an
        #     ordinary argument — contributed `_value` to the set, and the loop
        #     below then skipped that argument as "the receiver". The shape
        #     counted 0 required parameters and 0 names, so it became
        #     indistinguishable from `def __init__(out self)` and a `Cell()`
        #     was refused as AMBIGUOUS between two constructors with different
        #     arities;
        #   * a set has no owner, so one overload's receiver name exempts the
        #     same-spelled ordinary parameter of a DIFFERENT overload.
        #
        # `method_declares_receiver` is the reader that asks the question
        # properly — the parameter must be spelled as a receiver
        # (`RECEIVER_PARAMETER_SPELLINGS`), which is the same rule
        # `_rewrite_method_calls` already refuses anything outside of, so a
        # receiver spelled some other way never reached this loop working in the
        # first place. Asking it per method is also what `method_receiver_name`'s
        # own docstring requires ("a caller that needs the receiver of the
        # method it is looking at must not answer a slightly different
        # question").
        recv = (method_receiver_name(m)
                if method_declares_receiver(m) else None)
        names, params, required, optional = [], [], 0, 0
        required_names = []
        for p in (getattr(m, "params", None) or []):
            pname = p[0] if isinstance(p, (tuple, list)) else p
            if recv is not None and pname == recv:
                continue
            names.append(pname)
            params.append((pname, defaults.get(pname)))
            if has_default.get(pname):
                optional += 1
            else:
                required += 1
                required_names.append(pname)
        positional = len(params)
        for i, pname in enumerate(names):
            if pname in kwonly:
                positional = i
                break
        out.append(InitShape(m, params, positional, required, optional,
                             tuple(required_names)))
    return out


def init_call_bindings(shape, args, kwargs):
    """`({parameter name: argument}, why, names)` — how ONE `__init__` binds a
    call.

    The binding the language defines, and the whole of what turns
    `Rng(seed=7)` from a refusal into a program: a positional argument takes
    parameter `i` in DECLARATION ORDER (up to the keyword-only boundary), a
    keyword takes the parameter it NAMES, and a parameter the call leaves out
    keeps the default its signature gave it.

    `bindings` is None when `why` is not None, and `names` is what the
    refusal has to spell: the keyword that names no parameter, or the
    parameters the call left unfilled.  Each `why` is a different fact about
    the program with a different repair, which is why `init_overload_for_call`
    reports them separately rather than collapsing them into "no match":

      * `"unknown_parameter"` — a keyword names no parameter of THIS
        constructor.  CPython's `got an unexpected keyword argument`.
      * `"too_many_positionals"` — more positionals than `positional`, so one
        of them would bind a keyword-only parameter by position.
      * `"missing"` — a parameter with no default that the call did not supply.
        CPython's `missing 1 required positional argument`.
      * `"twice"` — one parameter given twice, by a positional and a keyword or
        by two keywords.  CPython's `got multiple values for argument`.

    **`init_body_stores` substitutes through this map and not through an index
    arithmetic of its own.**  It used to ask "is parameter `i` below the
    positional count, and if so what is argument `i`", which is the same
    question for a call with no keywords and cannot answer it for a call with
    any: a keyword names its parameter out of order, so the parameter that
    bound is not the parameter at the argument's own index.
    """
    _method, params, positional, _required, _optional, required_names = shape
    names = [p for p, _d in params]
    if len(args) > positional:
        return (None, "too_many_positionals", ())
    bound = {names[i]: value for i, value in enumerate(args)}
    for key, value in kwargs:
        if key not in names:
            return (None, "unknown_parameter", (key,))
        if key in bound:
            return (None, "twice", (key,))
        bound[key] = value
    unfilled = tuple(n for n in required_names if n not in bound)
    if unfilled:
        return (None, "missing", unfilled)
    return (bound, None, ())


def init_overload_for_call(shapes, args, kwargs):
    """`(shape, bindings, why, names)` — the `__init__` this call NAMES.

    The keyword-aware sibling of `init_overload_for_arity`, and the reason a
    keyword construction against a declared constructor is a program rather
    than a refusal.  That refusal (`construction_keyword_refusal`'s old `"init"`
    arm) said `CONSTRUCTION_INIT` "selects the overload by ARGUMENT COUNT —
    nothing here resolves by type or by parameter name, so a keyword call
    cannot say which one it means".  **The first clause was true and the second
    was not, and the second is what the refusal rested on:** a keyword DOES name
    a parameter, and one constructor declaring that parameter is selected by
    that alone.  So the selection is over the whole call now — positionals in
    order plus the parameter names the keywords give — and the count-only rule
    survives as `init_overload_for_arity` for a call that has no keywords.

    Why it is still a refusal rather than "pick the widest": this path resolves
    nothing by TYPE, so two constructors that both admit the call's parameter
    names are indistinguishable here, and a construction chosen by guess is a
    program the source did not write.  That is `ambiguous`, unchanged.

    The failure codes are reported in the order a reader can act on them,
    because they are not the same severity and not the same repair:

      1. `unknown_parameter` — a keyword names no parameter of ANY declared
         constructor.  First because it is a typo-shaped fact about the call
         and nothing about the positionals can improve on it.  The names are
         read off the CALL against the union of the overloads' parameter names,
         not off one overload's answer: a name one overload declares was
         understood, and reporting it would send the reader after a parameter
         the call did get right.
      2. `twice` — one parameter given two values, by a positional and a keyword
         or by two keywords.  CPython's `got multiple values for argument`.
         Second for the same reason as the first: it is a fact about the
         SPELLING, and it is the only one of the four whose own repair (drop one
         of the two) leaves the rest of the call unchanged.
      3. `too_many_positionals` — more positionals than the constructor's
         positional boundary, so one of them would bind a keyword-only parameter
         by position.  It carries no names of its own — which parameter the
         surplus argument would have hit is not a fact about the call — so it is
         reported on its presence rather than on the intersection rule the other
         three use.
      4. `missing` — every keyword is spelled right and something the
         constructor REQUIRES was left out.  Last because it is the fallback
         shape of "you did not supply enough", and it is the only one of the four
         whose names come from the constructor rather than from the call.

    For the two codes the overloads answer with names, the names are the
    INTERSECTION over the overloads that produced that code, and that is a
    deliberate choice rather than a convenience: when two constructors disagree
    about what the call leaves out, neither set is what the call left out, so the
    honest message is the count-based one below ("none of them takes that
    count"), which is a statement about every declared overload at once.  A union
    would name `b` and `c` for `S()` against `(a, b)` and `(a, c)` as though
    supplying both would do.
    """
    bound = []
    whys = {}
    for shape in shapes:
        bindings, code, names = init_call_bindings(shape, args, kwargs)
        if code is None:
            bound.append((shape, bindings))
        else:
            whys.setdefault(code, []).append(names)
    if len(bound) == 1:
        return (bound[0][0], bound[0][1], None, ())
    if len(bound) > 1:
        return (None, None, "ambiguous", ())
    declared = {p for shape in shapes for p, _d in shape.params}
    unknown = tuple(k for k, _v in kwargs if k not in declared)
    if unknown:
        return (None, None, "unknown_parameter", unknown)
    for code in ("twice", "missing"):
        if code not in whys:
            continue
        # The intersection is a set and a set has no order; the names are taken
        # back in the FIRST overload's declaration order, which is the order
        # CPython reports them in (`missing 2 required positional arguments: 'n'
        # and 'm'`, not the alphabetical one).
        common = set.intersection(*[set(group) for group in whys[code]])
        names = tuple(dict.fromkeys(
            n for n in whys[code][0] if n in common))
        if names:
            return (None, None, code, names)
    if "too_many_positionals" in whys:
        return (None, None, "too_many_positionals", ())
    # The positionals are what failed, and this is the pre-existing question
    # with its own two reasons and its own message.
    hit = [s for s in shapes
           if s.required <= len(args) <= s.required + s.optional
           and len(args) <= s.positional]
    return (None, None, "ambiguous" if hit else "no_overload", ())


def init_overload_for_arity(shapes, got: int):
    """`(shape, why)` — the `__init__` a call of `got` positionals names.

    `why` is None on a unique match, `"no_overload"` when no declared arity
    admits the count, and `"ambiguous"` when two do.

    AMBIGUITY is a refusal and not a choice between the candidates, and the
    reason is that this path resolves nothing by type: a call site carries the
    argument COUNT and the arguments themselves, never their types, so two
    constructors of the same arity are indistinguishable here.  Real Mojo picks
    by argument type; picking the first would be picking a program the source
    did not write, and the reader would have no way to see which one was chosen.
    `Slice`'s two shapes are exactly the case that has to work: `(2 required)`
    and `(3 required, 1 defaulted)` partition the counts, so `Slice(a, b)` and
    `Slice(a, b, c)` each have exactly one.
    """
    hits = [s for s in shapes
            if s.required <= got <= s.required + s.optional and got <= s.positional]
    if len(hits) == 1:
        return hits[0], None
    return (None, "ambiguous" if hits else "no_overload")


def init_body_stores(struct_def, call, shape, bindings, decls: dict, rets=None):
    """`([(field, slot, value)], refusal)` — an `__init__` body as STORES.

    The lowering of a user-defined constructor, and the whole of what premise
    (B2) used to be a refusal about.  A `__init__` does not have to be CALLED to
    be RUN: if its body is a straight line of `self.<field> = <expr>` stores
    then the construction `S(a, b)` and the construction followed by those
    stores are the same program, and the second one is what this path already
    knows how to emit — a fresh block, one store per field, at the SITE.  So the
    stores are returned for the emitters to emit in that block, in the body's
    own order, which is the order the language gives them.

    `value` is an AST node to evaluate AT THE SITE, and resolving a
    right-hand side to one is most of the work:

      * a bare PARAMETER name is the argument that bound to it, or — for a
        parameter the caller left to its default — the default expression from
        the signature.  `Slice`'s two-parameter `__init__` ends in
        `self.step = None`, and `None` is not a parameter of anything: it is a
        parameter-shaped fact that arrives as a value the construction has to
        materialize.  Both spellings of it, `None` as a bare name (which is how
        Python's parser leaves it) and `NoneLiteral`, are the same word and are
        accepted as the same word.
      * a bare name that is NOT a parameter is refused, and it has to be: the
        body runs at a CONSTRUCTION SITE, in the caller's function, where that
        local does not exist.  Reading it would be reading whatever register
        held.  This is the one asymmetry with running the body in place, and it
        is why the accepted set is a set and not "whatever the parser produced".
      * anything else — a literal, arithmetic over the parameters, a read of one
        of them, a container display — is emitted by the same `_emit_expr` a
        positional construction argument already goes through, and is subject to
        the same per-argument refusals.  The ONE thing that is not is a
        construction of a FRAMED struct of this module: its receiver block was
        reserved per call SITE in the prologue of the function whose body names
        the call, and a body inlined into a construction elsewhere has no such
        site.  Refused by name, because the alternative is a frame the prologue
        never reserved.

    A field the body does NOT assign is not an error: the language
    default-initializes the object before the constructor runs, so such a field
    keeps its class-level default — which is what the `CONSTRUCTION_INIT` shape
    leaves in the slot by bringing every slot up first, exactly as `S()` does.
    The class-level default still has to be materializable, and the emitters
    check that (`struct_frame_representable`); the arithmetic of "which fields
    does this constructor leave alone" is deliberately not done here.

    A statement that is not a receiver-field store — a branch, a loop, a call to
    a method, a write to a local — is refused with that statement spelled out,
    because a reader who has been told "this constructor is not lowered" needs
    to know WHICH LINE of it is responsible, and the two questions have
    different fixes.

    `rets` is the construction pass's `CalleeReturnTable`, and it is asked here
    for the same fact it is asked about a positional argument: a right-hand side
    that is a CALL to a function returning a container is a blob in the CALLEE's
    reclaimed scratch, and an inlined constructor body runs at a construction
    site in the CALLING function, so nothing about the lifetime differs.

    `bindings` is `init_call_bindings`' answer for THIS shape — `{parameter
    name: the caller's expression}` — and it is passed in rather than re-derived
    from `call.args` because the selection (`init_overload_for_call`) has
    already asked, and a body that substituted through a count of its own would
    be answering the keyword case by a rule that does not have one.
    """
    method, params, _positional, _required, _optional, _req = shape
    args = list(getattr(call, "args", None) or [])
    receivers = struct_receivers(struct_def)
    framed_names = {name for name, s in (decls or {}).items()
                    if struct_is_framed(s)}
    # The fields this struct's own layout ALREADY brings up as a nested frame,
    # and the store that would be redundant against one — the drop this walk
    # does, and the thing its third refusal arm was standing in front of.
    placed = {field: child.name
              for field, _slot, child
              in struct_nested_frame_fields(struct_def, decls)}
    stores = []
    for stmt in (getattr(method, "body", None) or []):
        if isinstance(stmt, F.PassStmt):
            continue
        if isinstance(stmt, F.ExprStmt) and isinstance(stmt.value,
                                                      F.StringLiteral):
            # A docstring.  `expr("a string")` is a statement here and has no
            # effect in the language, so skipping it is the semantics rather
            # than a convenience.
            continue
        if not isinstance(stmt, F.AssignStmt):
            # Everything this walk inlines is a plain `self.<field> = <expr>`
            # store, so every other statement shape is a refusal — and the
            # AUGMENTED assignment is the one whose spelling has to be named,
            # because it is a receiver-field store that merely looks like this
            # one: it is a read AND a write, so its value depends on what is
            # already in the slot, and the slot holds the CLASS-LEVEL default
            # where the constructor's stores run rather than whatever an earlier
            # statement stored.  `_init_statement_spelling` says "an augmented
            # assignment to `self.b`" for that statement and "a local assignment"
            # for the others, which is the whole reason it exists.
            return (None, construction_init_body_refusal(
                struct_def.name, _init_statement_spelling(stmt)))
        pairs = _init_statement_field_stores(stmt, receivers)
        if pairs is None:
            target = getattr(stmt, "target", None)
            tuple_why = _init_tuple_target_refusal(stmt, target,
                                                   getattr(stmt, "value", None),
                                                   receivers)
            return (None, construction_init_body_refusal(
                struct_def.name,
                tuple_why if tuple_why is not None
                else _init_statement_spelling(stmt)))
        for target, raw in pairs:
            field = target.member
            if field in placed and _init_store_is_redundant(raw,
                                                            placed[field]):
                # The store is the SAME program as no store at all, and dropping
                # it is what makes the class that assigns a nested frame in its
                # constructor lower again. `struct_nested_frame_fields` already
                # placed that frame in the object under construction's OWN
                # block and the `CONSTRUCTION_INIT` lowering brings it up, so
                # `self.in1 = Inner()` writes over a slot that already holds
                # that frame's address — the same value, from the same place,
                # by a longer route.
                #
                # It is dropped rather than refused because the alternative is
                # refusing a program whose object is already correct: this
                # construct is what `scripts/stage2_mojo_interpreter.mojo` and
                # several stdlib classes are written in, and it is the ONLY
                # shape that says a field holds a nested frame without declaring
                # it, so refusing it takes the assigned-type evidence source out
                # of reach entirely.
                #
                # Narrow on purpose, and the narrowness is the whole safety of
                # dropping a store the language requires. The store must name
                # the struct the placement made (`placed[field]`) and take no
                # arguments: a construction of a DIFFERENT struct is a different
                # value, and one with arguments fills fields the placement's
                # defaults do not. Both fall through to the checks below, which
                # refuse them by name.
                #
                # `raw` and not `stmt.value`: this is per PAIR, so a TUPLE
                # target asks about the value bound to ITS element. That is the
                # same question the single-target case asks, and it is why the
                # check sits inside the loop rather than above it —
                # `self.in1, self.n = Inner(), 7` drops its first store and
                # keeps its second, which is the only reading of the statement
                # that is either correct or obviously not.
                continue
            slot = struct_frame_slot(struct_def, field)
            if slot is None:
                return (None, construction_init_body_refusal(
                    struct_def.name,
                    f"`{spelled(target)}`, which assigns a field "
                    f"({struct_field_summary(struct_def)}) this struct does "
                    f"not have"))
            value, refusal = _init_store_value(struct_def, raw, params,
                                              bindings, rets, framed_names, call,
                                              decls)
            if refusal is not None:
                return (None, refusal)
            stores.append((field, slot, value))
    return (stores, None)


def struct_ctor_field_value(struct_def, call, field, decls: dict = None):
    """The AST node this construction puts in `field`'s slot, or None.

    `init_body_stores` is asked rather than re-walked, and that is the whole
    point: it is the ONE function that decides what `S(a, b)` stores where, and
    the emitters emit from its answer. So the VALUE this returns is the very
    expression the image will evaluate into the slot — a bare parameter name
    already resolved to the CALLER's argument expression, which is the step
    that makes the answer about this construction rather than about the
    constructor. A second walk of `__init__` would be a second opinion about
    which argument lands in which slot, and a disagreement between the two is a
    kind read off the wrong word.

    None means "this construction says nothing about that field", and it is the
    answer for every case where the question is not decidable rather than
    merely absent: no `__init__` at all (the positional filling of a struct
    that declares no constructor is a different question, and `S()` brings
    every slot up from its class default instead), an arity that matches no
    declared overload or more than one, a keyword against a declared
    constructor, a body statement this path refuses to lower, and a field the
    constructor does not assign. Every one of those is a refusal at the
    CONSTRUCTION for all but the last, so a program that reaches codegen is
    only ever asking about a construction that really does perform the store.

    The one case that is not a refusal anywhere and still has to answer None is
    a field some OTHER method writes. Nothing here knows the whole struct's
    methods, and a kind claimed from the constructor alone would be a claim
    about the slot at the construction site and nowhere else — so the caller
    pairs this with `struct_field_written_outside_init`, which is the check
    that keeps it a claim about the object's field rather than about its
    first instruction."""
    shapes = struct_init_shapes(struct_def)
    if not shapes:
        return None
    # `init_overload_for_call` and not `init_overload_for_arity`, because this
    # question is "which expression does THIS call put in this field" and a
    # keyword construction's answer is not derivable from a positional count: a
    # struct whose only constructor takes `(out self, *, seed: Int)` has no
    # positional arity at all, and asking for one answered "no overload" for a
    # call that binds perfectly well. `None` below then means "this
    # construction says nothing about that field", which is the answer its
    # caller already handles.
    shape, bindings, why, _names = init_overload_for_call(
        shapes, list(getattr(call, "args", None) or []),
        list(getattr(call, "kwargs", None) or []))
    if shape is None or why is not None:
        return None
    stores, refusal = init_body_stores(struct_def, call, shape, bindings,
                                       decls or {})
    if refusal is not None:
        return None
    for name, _slot, value in stores or ():
        if name == field:
            return value
    return None


def struct_field_written_outside_init(struct_def, field) -> bool:
    """True when some method OTHER than `__init__` writes `self.<field>`.

    The check that makes a constructor argument a claim about the FIELD rather
    than about the moment of construction. `ValueKinds` is flow-INsensitive by
    construction (its own docstring), so a name it saw built by `Point(3, 4)`
    answers the same wherever it is asked; if a setter ran in between, the slot
    holds whatever the setter put there and the constructor's argument says
    nothing about it. `FORMAL_method_param_field`'s neighbourhood is
    where field stores through a method are measured, so this is asked of the
    whole method set rather than of the constructor alone.

    Every method of the struct is read, and an assignment is recognised only
    in the two shapes the emitter performs: `self.f = v` and `self.a, self.b =
    v, w` (`_init_statement_field_stores`, the one reader of that shape). A
    write this predicate cannot see is a write it does not veto, which is the
    wrong direction — so the callers' evidence test (`own_shape_kind`) is what
    keeps an unclassifiable argument out, and this is a second gate rather than
    the only one."""
    receivers = struct_receivers(struct_def)
    for method in struct_methods(struct_def):
        if method.name == "__init__":
            continue
        for stmt in (getattr(method, "body", None) or []):
            for target, _value in (_init_statement_field_stores(stmt, receivers)
                                   or ()):
                if isinstance(target, F.MemberExpr) and \
                        target.member == field:
                    return True
    return False


def _init_statement_field_stores(stmt, receivers) -> list | None:
    """`[(target, value_node)]` — the receiver-field stores one statement IS.

    The shape question `init_body_stores` asks per statement, split out because
    three callers need the same answer and a disagreement between them is a
    silent wrong answer rather than a refusal: the emitter inlines what this
    returns, `struct_init_field_type`'s second evidence source reads a TYPE out
    of it, and `_init_store_shape_refusal` decides whether the store settles
    anything.  Before this existed the third of those had to REFUSE a tuple
    target the first two were about to perform, which is the band-aid
    `FORMAL_tuple_store_to_a_field` describes.

    TWO shapes, and they are the same program: `self.<f> = <v>` and
    `self.<a>, self.<b> = <v>, <w>`.  The second is not a special case to be
    tolerated, it is ordinary Python that this repository writes —
    `tools/procrun.py` opens with
    `self.limit, self._chunks, self._size = limit, [], 0` — and it parses as one
    `AssignStmt` whose TARGET is a `TupleExpr` of `MemberExpr`, so a reader that
    knows only `target: MemberExpr` sees a class that assigns three fields as
    one that assigns none.  Pairing is POSITIONAL, which is what the language
    guarantees and what both backends already emit (`arm64_codegen.py`'s
    `_tup_slot` and `x86_64_codegen.py`'s `_tuple_target_key` answer the same
    three target shapes with the same three answers).

    `None` means the statement is not a straight line of receiver-field stores,
    and every way of failing that is refused rather than partly performed:

      * a target element that is not a field of a receiver — `self.a, b.c = X(), Y()`
        is a field store AND a register store, and only the first has a slot
        here;
      * a starred element (`self.a, *rest = …`), which has no positional
        partner at all;
      * a nested group (`(self.a, self.b), self.c = (x, y), z`), whose inner
        pair is an unpack this walk does not perform;
      * a right-hand side that is not a tuple/list display of the SAME arity —
        `self.a, self.b = f()` is an unpack of a runtime blob whose arity the
        walk cannot know, and `self.a, self.b, self.c = 1, 2` is a parse whose
        pairing this path does not understand.

    All four are the ABSENT answer, which is the safe direction twice over: a
    statement that is not one of these stores contributes no field type, and a
    field with no type can neither place a frame nor suppress a frame
    diagnostic.
    """
    target = getattr(stmt, "target", None)
    value = getattr(stmt, "value", None)
    if isinstance(target, F.MemberExpr):
        if isinstance(target.obj, F.IdentExpr) and target.obj.name in receivers:
            return [(target, value)]
        return None
    if not isinstance(target, (F.TupleExpr, F.ListExpr)):
        return None
    targets = list(getattr(target, "elements", None) or [])
    if not isinstance(value, (F.TupleExpr, F.ListExpr)):
        return None
    values = list(getattr(value, "elements", None) or [])
    if len(values) != len(targets):
        return None
    for t in targets:
        if not (isinstance(t, F.MemberExpr) and isinstance(t.obj, F.IdentExpr)
                and t.obj.name in receivers):
            return None
    return list(zip(targets, values))


def _init_tuple_target_refusal(stmt, target, value, receivers) -> str | None:
    """Why a TUPLE target in an `__init__` is not a straight line of stores.

    Four shapes reach here that `_init_statement_field_stores` declines, and
    they are declined for four different reasons, so "a local assignment" —
    which is what the statement's own shape says and what a reader cannot act
    on — is the one answer none of them can use.  Each is named by the thing
    that makes it not a per-field store, which is also the thing a fix has to
    supply:

      * a target that is not a field of the receiver (`self.a, b.c = X(), Y()`):
        the second element is a store into something this walk has no slot for;
      * a STARRED element (`self.a, *rest = …`): it absorbs a variable number
        of values, so no element has a positional partner;
      * a NESTED GROUP (`(self.a, self.b), self.c = (x, y), z`): the inner pair
        is itself an unpack, so its two values come out of one blob rather than
        two stores;
      * a right-hand side that is not a display of the SAME arity
        (`self.a, self.b = f()`): an unpack of a runtime blob whose count the
        walk cannot know, or a pairing this parse does not state.

    `None` when the target is not a tuple at all, so the caller falls back to
    the statement's own spelling — this is the tuple half of that question and
    not a second answer to all of it.
    """
    if not isinstance(target, (F.TupleExpr, F.ListExpr)):
        return None
    targets = list(getattr(target, "elements", None) or [])
    for t in targets:
        if isinstance(t, (F.TupleExpr, F.ListExpr)):
            return (f"a tuple target whose group `({', '.join(spelled(e) for e in targets)})` "
                    f"holds a nested pair, and an inner unpack is not a store "
                    f"into one field: give each field its own assignment")
        if isinstance(t, F.UnaryOp):
            return (f"a starred target (`{spelled(t)}`), which absorbs a "
                    f"variable number of values and so has no positional "
                    f"partner for one of them")
        if not (isinstance(t, F.MemberExpr) and isinstance(t.obj, F.IdentExpr)
                and t.obj.name in receivers):
            return (f"a tuple target that mixes a field of the receiver with "
                    f"`{spelled(t)}`, which is not one: only the first has a "
                    f"slot in the block this stores into")
    if not isinstance(value, (F.TupleExpr, F.ListExpr)):
        return (f"a tuple target of {len(targets)} fields assigned from "
                f"`{spelled(value)}`, which is not a display of "
                f"{len(targets)} values: unpacking a runtime container needs a "
                f"count this path does not read at a construction site")
    values = list(getattr(value, "elements", None) or [])
    return (f"a tuple target of {len(targets)} fields assigned "
            f"{len(values)} value(s), so there is no positional pairing to "
            f"store")


def _init_store_is_redundant(value, placed_struct: str) -> bool:
    """Is this `self.<placed nested frame> = …` the store the placement already made?

    True only for a construction of `placed_struct` — the struct
    `struct_nested_frame_fields` put in that slot — with NO arguments, which is
    `self.in1 = Inner()`.

    Both halves are load-bearing and each refuses something real:

      * naming `placed_struct` is what makes it the SAME frame. A construction of
        a different struct is a different value, and dropping it would leave the
        field holding the declared type's frame while the source put another
        one there — the two can share a field count and a field list, which is
        exactly `bugs/formal/FORMAL_declared_parameter_against_its_call_sites.md`'s
        subject, so "the layout happens to match" is not available as a test.
        `assigned_type_a_declaration_still_wins` is the program that measures
        it: `Outer` declares `var in1: Inner` and `__init__` assigns
        `Other()`.
      * no arguments is what makes it a DEFAULT construction. The placement
        brings the frame up at its defaults; `Inner(7)` fills fields those
        defaults do not, so the store is not redundant even when it names the
        right struct.

    A zero-argument construction of the right struct is the frame the placement
    made and nothing else, because `struct_nested_frame_fields` places by the
    field's DECLARED type (or, for an undeclared field, by the type its
    `__init__` assigns — `model.struct_field_assigned_type`, which is the
    evidence source this restores) and `T()` is `T`'s default value.
    """
    return (isinstance(value, F.CallExpr)
            and isinstance(value.func, F.IdentExpr)
            and value.func.name == placed_struct
            and not (value.args or [])
            and not (value.kwargs or []))
def _init_statement_spelling(stmt) -> str:
    """How a refusal names the `__init__` statement it is about.

    The SHAPE, spelled in the reader's own words, because "an `AssignStmt`" is
    a class name from the parser and "a local assignment" is the thing they
    wrote.  A statement can be a long expression and the reader needs to know
    which of theirs it is, not a reprint of it; the one exception is a local
    assignment, which is quoted as well as named because `t = a + b` next to
    "a local assignment" saves a trip to the class body.
    """
    if isinstance(stmt, F.AugAssignStmt):
        return f"an augmented assignment to `{spelled(getattr(stmt, 'target', None))}`"
    if isinstance(stmt, (F.VarDecl, F.AssignStmt)):
        target = getattr(stmt, "target", None) or getattr(stmt, "name", None)
        return f"a local assignment (`{spelled(target)} = …`)"
    if isinstance(stmt, (F.IfStmt, F.WhileStmt, F.ForStmt, F.TryStmt,
                         F.WithStmt, F.MatchStmt, F.ReturnStmt, F.RaiseStmt,
                         F.AssertStmt)):
        return f"a `{type(stmt).__name__[:-4].lower()}` statement"
    if isinstance(stmt, F.ExprStmt):
        return f"`{spelled(getattr(stmt, 'value', None))}`"
    return f"a `{type(stmt).__name__}` statement"


# The three Python singletons, as a NAME.  `None` parses as a bare `IdentExpr`
# and `is`/`is not` and a comptime fold can produce the same for `True` and
# `False`, so all three reach a name position in source.  They are not locals
# of an `__init__` and not parameters of one, which is why the free-name
# refusal has to let them past deliberately: it is about names the body binds,
# and these are the language's own.  Both backends already materialize them to
# a word before `_load_var` is reached (`_UNRESOLVED_NAME_ALLOWED` records that
# and `arm64_codegen.py` / `x86_64_codegen.py` do it), so passing the name
# through to `_emit_expr` produces exactly the store either of them would have
# made — and `Slice`'s two-parameter constructor ends in `self.step = None`, so
# this is the case that makes the family worth naming at all.
_INIT_SINGLETON_NAMES = frozenset({"None", "True", "False"})




# ── An inlined `__init__`'s own receiver ───────────────────────────────────
#
# An inlined constructor body runs at the CONSTRUCTION SITE, in the CALLING
# function, where the name `self` does not exist.  Everything else the body does
# is a store the site can perform — a literal, arithmetic over the caller's own
# arguments — so those substitute directly and the body needs nothing from its
# own scope.  A read of the RECEIVER was the one thing it could not do, and it
# was refused: the refusal's own words were that the block's address has to be
# "threaded through as a receiver" and that this path had no lowering for it.
#
# It has one now, and the block's address is the thing that was missing from the
# IMPLEMENTATION rather than from the model: `struct_constructor_sites` reserved
# a block for this exact call in this exact function's prologue, and the store
# loop below is already writing into it.  So a receiver read is resolved against
# THAT block, in the only two ways the language's own `self` can be read:
#
#   * `self.<m>(…)` — a METHOD CALL, lifted to the call it is
#     (`Class_m(<block>, …)`, `method_function_name`) with the block's address
#     as the receiver.  The callee is compiled as a function in its own right
#     with its receiver bound to its first parameter, so the body that runs is
#     the source's body: a method that reads fields, calls other methods or
#     branches lowers exactly as it does anywhere else, which is why this covers
#     `self.spec_content = self._read_spec()` and not only a method that returns
#     a constant.
#   * `self.<f>` — a FIELD, a load at `[block + 8·slot]` with the slot from the
#     same `struct_frame_slot` table the store above it uses, so a read and a
#     write of one field cannot disagree about where it lives.  Reading a field
#     the body has not stored yet yields the class-level default, which is what
#     the language says the field holds at that point: every slot is brought up
#     at its default before the body's first store.
#
# A receiver read that is neither of those — the object handed to a free
# function, a `self.<f>` whose value is a NESTED frame that is then read
# through, a name bound to the object — is still refused, and
# `init_receiver_rewrite`'s message says which and why.  So is the whole family
# on a struct of zero or one field, where the receiver IS the field's own word
# and there is no block to read a slot of.


@dataclasses.dataclass
class CtorReceiver:
    """The object an inlined `__init__` is constructing, as a receiver.

    NOT an AST node the parser produced: nothing in the source spells it, and
    it never appears in a tree the parser built.  It is what a `self` in an
    inlined constructor body becomes once the body's stores are decided to be
    emitted at the construction site — the one expression in that position which
    is not the caller's own code, so it has to be said rather than substituted.

    `call` is the CONSTRUCTION this receiver belongs to, and it is what makes
    the node answerable rather than ambient: the block is per call SITE
    (`struct_constructor_sites`), so two constructions of the same struct in one
    function are two blocks and a receiver has to say which one it is.  Both
    emitters look the site up by `id(call)`, which is the same key
    `struct_constructor_sites` publishes.
    """

    call: object = None


@dataclasses.dataclass
class CtorField:
    """`<field>` of the object an inlined `__init__` is constructing.

    The read half of `CtorReceiver`, and a separate node rather than a field on
    it because the two are answered by different arithmetic: the receiver is an
    ADDRESS and this is a LOAD at that address plus an offset.  `slot` is the
    field's own index in `struct_frame_slots` — the table the store in the same
    body uses — so the read and the write are the same slot by construction and
    not by two walks agreeing.  `field` is the NAME, kept beside the slot so a
    refusal about one of these can quote the source (`self.inner.q`) instead of
    the node class, which is a name from this file and not from anyone's program.
    """

    call: object = None
    slot: int = 0
    field: str = ""


class _CtorReceiverUnlowerable(Exception):
    """One receiver read an inlined `__init__` cannot resolve against the block.

    A private control-flow signal rather than a refusal string, because the walk
    that meets it is recursive and seven levels down: `init_receiver_rewrite` is
    the ONE function that turns the sentence into a diagnostic, so the level that
    noticed the shape hands back what it saw and the level that knows the
    message says it.
    """


@dataclasses.dataclass
class _CtorCtx:
    """Everything the receiver rewrite needs about ONE construction site.

    A context rather than three more positional parameters on every level of a
    recursion, and the fields are the three facts that are true of a construction
    and false of anything else: which STRUCT is being built, which CALL this is
    — the block is per site, so a receiver has to name its own — and the unit's
    struct table, which is what answers "does some OTHER struct declare this
    method too".

    What is NOT here is the constructor's parameters and the caller's arguments,
    and their absence is a rule rather than a simplification: a bare parameter is
    substituted where it stands ALONE (`_init_store_value`) and refused
    everywhere else, and keeping them out of this context is what makes that a
    property of the BODY's names rather than something a lifted call could
    quietly widen. Substituting a parameter in an argument position would
    evaluate the caller's expression once per occurrence, so `S(next())` would
    call `next()` twice — a different program from the one the source wrote, and
    the reason the standalone rule is the only one.
    """

    struct: object = None
    call: object = None
    decls: dict = field(default_factory=dict)

    @property
    def receivers(self) -> set:
        return struct_receivers(self.struct)


def _is_ctor_receiver(node, receivers) -> bool:
    """Is `node` a bare read of the constructor's receiver?

    A bare NAME and nothing else: `self.f` is a `MemberExpr` whose base this
    function also answers true for, and the level that owns the parent is what
    tells a field read from a method call.
    """
    return isinstance(node, F.IdentExpr) and node.name in receivers


def _ctor_needs_a_block(ctx) -> None:
    """Refuse a receiver read for a struct that has no block to read.

    A struct of zero or one field is a plain WORD on this path and its receiver
    IS that word, so there is no block, no slot and no address — both lowerings
    above are "compute something out of an address", and neither has an address
    here.  It is a refusal rather than a third lowering because the word a
    one-field construction evaluates to is the LAST store of the inlined body
    (`one_word_construction`): a receiver read EARLIER in the body has no value
    to read yet, so answering it with the field's default would be a different
    program from the one the source wrote.
    """
    if not struct_is_framed(ctx.struct):
        raise _CtorReceiverUnlowerable(
            f"a read of the receiver of {ctx.struct.name}, which is a struct of "
            f"{struct_field_count(ctx.struct)} field(s) and so its receiver IS "
            f"its own word rather than the address of a block — there is "
            f"nothing here to read a slot of")


def _ctor_method_owners(ctx, member):
    """The structs of THIS IMAGE that declare a method called `member`.

    `structs_declaring_method` over the unit's struct table, which is the one
    `init_body_stores` is already handed for the nested-frame question and which
    already CONTAINS the struct being built whenever it is non-empty.  A length is
    the whole of the answer, and BOTH of its answers are refusals rather than a
    pick: this path dispatches a method by NAME alone (`find_method_owner`),
    because a call site carries the name and the receiver's type is not inferred,
    so one owner is what makes the dispatch a fact and two owners is a question
    this compiler cannot answer.
    """
    table = list((ctx.decls or {}).values())
    if not any(st is ctx.struct for st in table):
        table.append(ctx.struct)
    return structs_declaring_method(table, member)


def _ctor_method_call(ctx, node):
    """`self.<m>(…)` as the call it is, with the block as its receiver.

    THE shape two files of this repository's own source are written in
    (`self.spec_content = self._read_spec()`).  Lifted by `method_function_name`
    rather than left as a `MemberExpr` callee because that is how every other
    method call in the image is spelled by the time an emitter sees it
    (`formal/build.py`'s `_rewrite_method_calls`), and the only difference here
    is that the receiver is a NODE rather than a name — so the argument binder,
    the callee's frame-holder contract on its first parameter and the argument
    registers are all the code a method call has always run.

    A method declared with NO receiver (`def m():`, a `@staticmethod`) gets no
    receiver word, by `method_receiver_name` and for the reason
    `formal/build.py`'s `_receiverless_methods` gives: there is nothing for an
    address to be handed to, and a class name is not a value.
    """
    member = node.func.member
    owners = _ctor_method_owners(ctx, member)
    if not owners:
        raise _CtorReceiverUnlowerable(
            f"a call to `{member}(…)`, which no struct this image declares has "
            f"as a method")
    if len(owners) > 1:
        raise _CtorReceiverUnlowerable(
            f"a call to `{member}(…)`, which {len(owners)} structs of this image "
            f"declare as a method ({', '.join(st.name for st in owners)}) and "
            f"this path dispatches a method by NAME alone, so it cannot say "
            f"which one of them the source means")
    method = next(m for m in struct_methods(ctx.struct) if m.name == member)
    args = [_ctor_receiver_rewrite(ctx, a)
            for a in (getattr(node, "args", None) or [])]
    kwargs = [(k, _ctor_receiver_rewrite(ctx, v))
              for k, v in (getattr(node, "kwargs", None) or [])]
    for a in args:
        _ctor_field_not_passthrough(ctx, a, member)
    if method_receiver_name(method) is not None:
        args = [CtorReceiver(call=ctx.call)] + args
    return F.CallExpr(func=F.IdentExpr(
        name=method_function_name(ctx.struct.name, member)),
        args=args, kwargs=kwargs)


def _holds_ctor_field(node) -> bool:
    return any(isinstance(sub, CtorField) for sub in iter_nodes(node))


def _ctor_field_not_passthrough(ctx, node, member):
    """Refuse a field of the object under construction handed to a CALL.

    The one consumer of a `CtorField` that is not a plain read, and the reason it
    is a refusal is about what the word in that slot MIGHT be.  A slot holds one
    word; the word is an integer or a `char *` for most fields and the ADDRESS of
    a frame for a field another struct's layout placed in it.  Reading it is
    right either way — a load is a load — but handing it to a callee is a
    question only the callee's own convention can answer, and this is the one
    place in the compiler that cannot ask: the frame-holder analysis
    (`formal/build.py`'s `_frame_receivers`) reads the FUNCTION BODIES, and a
    call lifted out of an inlined constructor body is not in any of them.  So a
    parameter whose kind nobody established would be read as a plain word, and
    `other.q` inside the callee would compute an address out of a number — the
    silent wrong answer this path exists to prevent, reached by a path the
    refusal could not otherwise see.

    Refused rather than guessed in either direction, and it is a narrow cost:
    passing a field to a method of the same struct reads as arithmetic over the
    object's own state, which is what the corpus writes.
    """
    if not _holds_ctor_field(node):
        return
    field = next(sub.field for sub in iter_nodes(node)
                 if isinstance(sub, CtorField))
    # "as an argument" and NOT "in argument position": that phrase is the marker
    # of a different cause in `tools/formal_sweep_causes.py` — the frame-escape
    # family, whose subject is a frame ADDRESS reaching a callee that wanted a
    # value.  This is a refusal rather than an escape, and a message that shares
    # the family's marker would file it in the wrong column.
    raise _CtorReceiverUnlowerable(
        f"`self.{field}` handed to `{member}(…)` as an argument: a slot's word "
        f"is an address when the field holds a nested frame, and nothing here "
        f"can say which way this callee reads its parameter")


def _ctor_field_read(ctx, node):
    """`self.<f>` as the load of one slot of the block, or a refusal.

    One level, and the level is the whole of what makes it answerable: the slot
    index comes from `struct_frame_slots`, which knows the struct's OWN fields
    and nothing about frames placed inside them.  So `self.<nested>.<field>` — a
    load at an offset inside a frame whose ADDRESS the slot holds, laid out by a
    DIFFERENT struct — is refused by name rather than answered with this struct's
    slot table, which would be a load of the wrong offset and a program that
    computes a number nobody wrote.
    """
    field = node.member
    slot = struct_frame_slot(ctx.struct, field)
    if slot is None:
        if any(m.name == field for m in struct_methods(ctx.struct)):
            raise _CtorReceiverUnlowerable(
                f"`{field}`, which is a METHOD of {ctx.struct.name} and not a "
                f"field of it: a bound method is not a value, so there is no "
                f"slot to read it out of")
        raise _CtorReceiverUnlowerable(
            f"`{field}`, which is not a field of {ctx.struct.name} "
            f"({struct_field_summary(ctx.struct)})")
    return CtorField(call=ctx.call, slot=slot, field=field)


def _ctor_receiver_rewrite(ctx, node):
    """`node`, rebuilt with every read of the receiver resolved against the block.

    A RECURSIVE walk rather than a top-level test, and the difference is a
    refused program rather than a missed one: `self.b = self.a + b` does not
    mention the receiver at the top level, so a top-level test would let the
    `BinOp` through to `_init_free_names`, which would refuse it for naming a
    name — true, and naming the wrong thing, because that name is one this walk
    knows how to resolve.

    It dispatches on a node's OWN shape before descending, which is what makes
    the two lowerings parent-aware without a parent pointer: a `MemberExpr` whose
    base is the receiver is a FIELD READ, and the same `MemberExpr` as a call's
    `func` is a METHOD CALL, and only the level that can see the `CallExpr` can
    tell those apart.

    A node it does not change is returned AS IS rather than rebuilt, so the
    identity test `new is not old` at the parent is what decides whether a
    subtree was rebuilt at all — the alternative, rebuilding unconditionally,
    would allocate a copy of every node of every constructor body in the image
    to discover there was nothing to change in any of them.
    """
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr) \
            and _is_ctor_receiver(node.func.obj, ctx.receivers):
        _ctor_needs_a_block(ctx)
        return _ctor_method_call(ctx, node)
    if isinstance(node, F.MemberExpr) \
            and _is_ctor_receiver(node.obj, ctx.receivers):
        _ctor_needs_a_block(ctx)
        return _ctor_field_read(ctx, node)
    if _is_ctor_receiver(node, ctx.receivers):
        raise _CtorReceiverUnlowerable(
            f"a bare read of `{node.name}`, which is the object under "
            f"construction and neither one of its fields nor a method call on it")
    if isinstance(node, (list, tuple)):
        rebuilt = [_ctor_receiver_rewrite(ctx, x) for x in node]
        if all(new is old for new, old in zip(rebuilt, node)):
            return node
        return tuple(rebuilt) if isinstance(node, tuple) else rebuilt
    names = _node_field_names(node) if node is not None else None
    if not names:
        return node
    changed = {}
    for name in names:
        old = getattr(node, name, None)
        if old is None or name in ("line", "col"):
            continue
        new = _ctor_receiver_rewrite(ctx, old)
        if new is not old:
            changed[name] = new
    rebuilt = node if not changed else dataclasses.replace(node, **changed)
    # The two consumers of a field read that are not plain reads, checked on the
    # REBUILT node rather than on the source, because that is the only place a
    # `CtorField` exists at all: a member access ABOVE one needs the nested
    # frame's own layout, and an argument POSITION hands the word to a callee
    # whose parameter convention nothing here can establish.
    if isinstance(rebuilt, F.MemberExpr) and _holds_ctor_field(rebuilt):
        through = next(sub for sub in iter_nodes(rebuilt)
                       if isinstance(sub, CtorField))
        raise _CtorReceiverUnlowerable(
            f"`self.{through.field}.{rebuilt.member}`, a read THROUGH a field of "
            f"{ctx.struct.name}: the slot holds the address of a frame and the "
            f"offset into it is a layout this struct's own field table does not "
            f"describe")
    if isinstance(rebuilt, F.CallExpr):
        callee = _flat_callee(rebuilt) or spelled(rebuilt.func)
        for a in (getattr(rebuilt, "args", None) or []):
            _ctor_field_not_passthrough(ctx, a, callee)
    return rebuilt


def init_receiver_rewrite(struct_def, value, call, decls):
    """`(value, refusal)` — the receiver's reads in one store's right-hand side.

    `value` comes back UNCHANGED when it does not read the receiver at all, and
    that is the common case: `self.a = n` is answerable by substituting the
    caller's argument and the walk has nothing to do with it.  A refusal is the
    one shape no lowering here covers, and it names the SHAPE rather than the
    name, because "a read of `self`" was the whole of the old message and the
    reader's next question — "so what CAN this body say?" — is not answered by
    it.
    """
    receivers = struct_receivers(struct_def)
    if not any(_is_ctor_receiver(node, receivers) for node in iter_nodes(value)):
        return (value, None)
    ctx = _CtorCtx(struct=struct_def, call=call, decls=decls or {})
    try:
        return (_ctor_receiver_rewrite(ctx, value), None)
    except _CtorReceiverUnlowerable as why:
        return (None, construction_init_body_refusal(
            struct_def.name,
            f"a read of the receiver this path cannot resolve against the block "
            f"being constructed: {why}. A method call and a one-level field "
            f"read ARE resolved — the block's address is passed as the "
            f"receiver, and a field is a load at `block + 8·slot` — so "
            f"what is left is a shape with no address to compute from"))


def _init_store_value(struct_def, value, params, bindings, rets,
                      framed_names, call=None, decls=None):
    """`(value_node, refusal)` — what one `self.<f> = …` stores.

    The parameter case, the receiver's own reads, the free-name refusal and
    the one expression kind the site cannot host are decided here so
    `init_body_stores` reads as the walk it is; each of the five is a fact
    about ONE right-hand side and none of them is about the walk.
    """
    if isinstance(value, F.IdentExpr) and value.name in _INIT_SINGLETON_NAMES:
        return (value, None)
    if isinstance(value, F.IdentExpr):
        for pname, default in params:
            if pname != value.name:
                continue
            if pname in bindings:
                return (bindings[pname], None)
            if default is None:
                return (None, construction_init_body_refusal(
                    struct_def.name,
                    f"a read of the defaulted parameter {value.name!r}, whose "
                    f"default expression this compiler did not record"))
            return (default, None)
        return (None, construction_init_body_refusal(
            struct_def.name,
            f"`{value.name}`, which is a local of the `__init__` and not one of "
            f"its parameters: this body is inlined at the CONSTRUCTION SITE, in "
            f"the calling function, where that name does not exist"))
    if isinstance(value, F.CallExpr) and isinstance(value.func, F.IdentExpr) \
            and value.func.name in framed_names:
        return (None, construction_init_body_refusal(
            struct_def.name,
            f"`{value.func.name}(…)`, a construction of a struct whose receiver "
            f"is a frame: its block is reserved per call SITE in the prologue of "
            f"the function whose body names the call, and a body inlined into a "
            f"construction elsewhere has no such site"))
    framed = _init_framed_construction(value, framed_names)
    if framed is not None:
        return (None, construction_init_body_refusal(
            struct_def.name,
            f"`{framed}(…)`, a construction of a struct whose receiver is a "
            f"frame: its block is reserved per call SITE in the prologue of the "
            f"function whose body names the call, and a body inlined into a "
            f"construction elsewhere has no such site"))
    lifted, receiver_refusal = init_receiver_rewrite(
        struct_def, value, call, decls or {})
    if receiver_refusal is not None:
        return (None, receiver_refusal)
    # The free-name check is asked of the ORIGINAL right-hand side, not of the
    # lifted one, and the ordering is the whole of why: the lift's own output
    # contains names that are not the body's — the callee it named
    # (`S_scale`) and whatever caller's expressions the parameter substitution
    # brought in — and asking about THOSE would refuse a construction for naming
    # a local of the calling function, which is the one function whose scope a
    # construction site shares with it.
    free = _init_free_names(struct_def, value)
    if free is not None:
        return (None, free)
    refusal = construction_arg_dead_blob_refusal(
        struct_def.name, "of this `__init__`", value, rets, struct_def)
    if refusal is not None:
        return (None, refusal)
    return (lifted, None)


def _init_framed_construction(value, framed_names):
    """The name of a FRAMED struct this right-hand side constructs, or None.

    A walk rather than a top-level test, and the difference is a wrong answer
    rather than a missed one: `self.x = [Inner(a, b)]` does not mention the
    construction at the top level, and a top-level test would let it through to
    `_emit_expr`, which would look the node up in this function's reserved
    sites, not find it, and refuse with "the frame layout and the body
    disagree … which is a compiler bug" — a diagnostic about the compiler
    printed for a program that is merely a shape this path cannot lower.
    """
    for node in iter_nodes(value):
        if isinstance(node, F.CallExpr) and isinstance(node.func, F.IdentExpr) \
                and node.func.name in framed_names:
            return node.func.name
    return None


def _init_free_names(struct_def, value):
    """A refusal for a name an inlined `__init__` body cannot bring with it, or None.

    A name the body reads is one of three things, and this answers for the two
    it cannot substitute: a LOCAL of the body, and a module constant, which is
    folded elsewhere in this compiler and not re-derived here.  At a construction
    site in the CALLING function neither exists — the body is inlined, not moved,
    there is no scope to bring them along in, and reading one would be reading
    whatever register the calling function happened to leave in it.

    A PARAMETER is the third case and the one that is easy to miss, because a
    bare `self.x = p` has already been replaced by the caller's own expression
    for `p` and is fine.  It is `self.x = 1 + p` that is not: the arithmetic
    names `p`, and `p` is a word the caller's function does not have.  So the
    check is on the names INSIDE the right-hand side, after the bare-parameter
    case has been handled, and it is a walk rather than a top-level test for
    exactly that reason.

    The RECEIVER is not answered here.  `init_receiver_rewrite` runs first, on
    the same right-hand side, and has already resolved every receiver read it
    can — a method call and a one-level field read both lower against the block
    under construction — and named the ones it cannot, so a receiver read
    reaching this walk is a shape that walk has already refused.  It is
    therefore SKIPPED rather than refused, and skipping it is also what lets the
    rewrite's output stay out of this question: a lift is a different tree (a
    callee name, a node for the receiver, the caller's own expressions where the
    parameters were) and this walk is about the names the BODY reads.

    A TYPE-POSITION name is skipped for a different reason and is not a scope
    question at all: `Self.T` and a trait conjunction bind nothing, so a name
    that only ever appears in a type is not one of the locals whose absence at a
    construction site would make a read pick up whatever register the calling
    function left in it.  `_init_type_position_names` is the walk that knows
    which names those are.

    The three singletons are excluded because they are the language's own and
    both backends already materialize them (see `_INIT_SINGLETON_NAMES`).
    """
    receivers = struct_receivers(struct_def)
    type_names = _init_type_position_names(value) - receivers
    locals_ = []
    for node in iter_nodes(value):
        if not isinstance(node, F.IdentExpr) or node.name in _INIT_SINGLETON_NAMES:
            continue
        if node.name in receivers:
            continue
        if node.name in type_names:
            continue
        locals_.append(node.name)
    if not locals_:
        return None
    who = ", ".join(repr(n) for n in dict.fromkeys(locals_))
    return construction_init_body_refusal(
        struct_def.name,
        f"a read of {who} in the right-hand side — a name the `__init__` binds "
        f"or takes, which this body does not substitute for a construction "
        f"argument. Only a bare parameter can be: only a bare parameter has the "
        f"caller's own expression standing in for it at the construction site")


def _init_type_position_names(value) -> set:
    """The names this right-hand side reads in TYPE position, which bind nothing.

    The exception to `_init_free_names`, and it is an exception about NAMES
    rather than about scopes: a type name is not a value, so it is not one of
    the locals whose absence at a construction site would make a read pick up
    whatever register the calling function happened to leave in it.  The
    emitter resolves `List[Self.T]` through its type-constructor path and never
    looks for a binding, so refusing it as a free name refuses a name the
    program does not have.

    **One position, not "any name that looks like a type".** A `CallExpr` whose
    `func` is a TYPE CONSTRUCTOR — the bare name (`List()`) or a subscript over
    one (`List[Self.T]()`, `Dict[String, List[Int]]()`) — spells a
    construction, and every name inside that callee is part of the type being
    constructed: the base, `Self`, and the type arguments.  A subscript on
    anything else is a specialization of a FUNCTION, and there the bracket
    holds an expression this path would have to evaluate, so it is not exempt
    and the free-name rule reads it exactly as before.  The `&`-conjunction and
    the rest of `Self.X` are the same statement about type arguments, so the
    walk covers the whole callee subtree rather than the base alone.

    Measured, and the case is a real stdlib file rather than a synthetic one:
    `std/collections/binary_heap.mojo`'s `__init__(out self)` is one statement,
    `self._data = List[Self.T]()`, and it was refused by name with "a read of
    'List', 'Self' in the right-hand side — a name the `__init__` binds or
    takes".  Neither name is bound by anything.  A container-backed struct is
    the shape that needs it: without it, NO field of this shape can be given
    its value by a constructor, so `struct_field_kind`'s constructor door is
    unreachable for every one of them.
    """
    out = set()
    for node in iter_nodes(value):
        if not isinstance(node, F.CallExpr):
            continue
        callee = node.func
        base = callee
        while isinstance(base, F.SubscriptExpr):
            base = getattr(base, "obj", None)
        if not isinstance(base, F.IdentExpr):
            continue
        if type_constructor_kind(base.name) is None \
                and not empty_blob_constructor(base.name):
            continue
        for sub in iter_nodes(callee):
            if isinstance(sub, F.IdentExpr):
                out.add(sub.name)
    return out


def _init_overload_spelling(shapes) -> str:
    """The declared shapes as one clause, for a message about selecting one.

    "it has a constructor" is not actionable, and `Slice`'s two shapes are
    small enough to print, so the arities and the parameter names both appear.
    The KEYWORD-ONLY boundary is printed where there is one because it is the
    boundary `too_many_positionals` refuses against: a reader who passed two
    positionals to `(a, *, b)` cannot tell from `2 required (a, b)` which of
    the two parameters was meant to take the second one.
    """
    out = []
    for shape in shapes:
        names = [p for p, _d in shape.params]
        text = (f"{shape.required} required"
                + (f" and {shape.optional} defaulted" if shape.optional else "")
                + (f" ({', '.join(names)})" if names else ""))
        only = names[shape.positional:]
        if only:
            text += f", {', '.join(only)} keyword-only"
        out.append(text)
    return "; ".join(out)


def construction_init_arity_refusal(name: str, shapes, got: int,
                                    why: str, missing=()) -> str:
    """`S(...)` at a count no declared `__init__` admits, two of them admit, one
    crosses a keyword-only boundary, or one is left short of what it REQUIRES.

    Still a refusal that has to come BEFORE the plain arity one, because that
    message's claim — "a struct's fields are filled in DECLARATION ORDER and
    there is no other form" — is FALSE for a struct that declares a
    constructor, and a message that is false about the program in front of the
    reader is worse than no message.

    The reasons are different problems and are stated differently, because
    they have different fixes:

      * `no_overload` — the count is outside every declared arity.  This is an
        error the language would report at the call, and the fix is on the
        caller's side: `Slice` admits 2, 3 and 4 positionals and nothing else.
      * `ambiguous` — two declared constructors admit the call, and this path
        resolves nothing by type, so it cannot say which one the source named.
        The fix is NOT "pick the first": a construction chosen by guess is a
        program the source did not write.
      * `missing` — the keywords were all understood and the constructor still
        wants something the call did not give it.  This is the reason the
        keyword construction used to be refused with a message about overload
        SELECTION instead, and it is the honest one: `S3(end=7)` against
        `def __init__(out self, start: Int, end: Int)` names a real parameter
        and leaves `start` unfilled, and CPython says
        `TypeError: __init__() missing 1 required positional argument:
        'start'`.  `missing` is the names to say so with.
      * `too_many_positionals` — the call passed more positionals than the
        constructor will take by position, so one of them would have to bind a
        keyword-only parameter by position, which is not a binding.  CPython
        reports the boundary (`takes 1 positional argument but 2 were given`),
        and this does too, naming which parameters have no positional slot.

    `std/builtin/builtin_slice.mojo`'s `Slice` is why this family exists at all:
    it declares a two-parameter constructor and a four-parameter one with a
    defaulted fourth, and the corpus writes `Slice(6, len(lst))`,
    `Slice(start, end)` and `Slice(start, end, step)`.  Those three counts
    partition cleanly, so all three now lower; what is left here is the counts
    `Slice` genuinely does not have, and the counts two of its overloads would
    both claim.
    """
    spelling = _init_overload_spelling(shapes)
    if why == "ambiguous":
        return (f"constructing {name} with {got} argument(s) is a call to a "
                f"user-defined `__init__` and TWO of them admit that call: "
                f"{name} declares {len(shapes)} `__init__` overload"
                f"{'' if len(shapes) == 1 else 's'} ({spelling}). This path "
                f"resolves nothing by type — a call site carries the arguments "
                f"and their parameter names, never their types — so it cannot "
                f"say which of them the source named, and picking either would "
                f"be running a constructor the program did not choose. Pass the "
                f"arguments only one of them takes, or give the two different "
                f"parameter lists")
    if why == "too_many_positionals":
        wide = max(s.positional for s in shapes)
        if any(len(s.params) > s.positional for s in shapes):
            return (f"constructing {name} with {got} positional argument(s) "
                    f"crosses a keyword-only boundary: {name} declares "
                    f"{len(shapes)} `__init__` overload"
                    f"{'' if len(shapes) == 1 else 's'} ({spelling}) — the "
                    f"parameters after that boundary have no positional slot, "
                    f"so they have to be named, as `{name}(name=value)`, and a "
                    f"surplus positional argument is not a binding. This is "
                    f"CPython's `TypeError`: __init__() takes fewer positional "
                    f"arguments than were given")
        return (f"constructing {name} with {got} positional argument(s) is a "
                f"call to a user-defined `__init__` and the widest one declared "
                f"takes {wide} by position: {name} declares {len(shapes)} "
                f"`__init__` overload{'' if len(shapes) == 1 else 's'} "
                f"({spelling}). In Mojo a declared `__init__` is what "
                f"`{name}(...)` calls, and this path lowers that call by "
                f"inlining the constructor body at the construction site, where "
                f"there is no `*args` to put the surplus argument in. This is "
                f"CPython's `TypeError`: __init__() takes {wide + 1} "
                f"positional argument{'' if wide == 0 else 's'} but "
                f"{got + 1} were given")
    if why == "missing":
        # CPython words the two kinds of required parameter differently, and
        # saying "positional" about a keyword-only one is false: `T(1)` against
        # `def __init__(out self, a: Int, *, b: Int)` raises `missing 1
        # required keyword-only argument: 'b'`, not the positional spelling.
        # The split is per NAME and reads every overload, because `missing` is
        # only reported when they agree on the names.
        kwonly = {n for n in missing if all(
            n in [p for p, _d in s.params][s.positional:] for s in shapes)}
        clauses = ", ".join(
            f"missing {len(group)} required {kind} argument"
            f"{'' if len(group) == 1 else 's'}: "
            f"{', '.join(repr(n) for n in group)}"
            for kind, group in (("positional",
                                 tuple(n for n in missing if n not in kwonly)),
                                ("keyword-only",
                                 tuple(n for n in missing if n in kwonly)))
            if group)
        names = ", ".join(repr(m) for m in missing)
        return (f"constructing {name} with {got} positional argument(s) leaves "
                f"{names} unfilled, and {name} declares "
                f"{len(shapes)} `__init__` overload"
                f"{'' if len(shapes) == 1 else 's'} ({spelling}) — a "
                f"declared `__init__` is what `{name}(...)` calls, and its own "
                f"parameters that have no default are arguments the call has "
                f"to supply by position or by name. This is CPython's "
                f"`TypeError`: __init__() {clauses}")
    return (f"constructing {name} with {got} positional argument(s) is a call "
            f"to a user-defined `__init__` and none of them takes that call: "
            f"{name} declares {len(shapes)} `__init__` overload"
            f"{'' if len(shapes) == 1 else 's'} ({spelling}). In Mojo a "
            f"declared `__init__` is what `{name}(...)` calls, and this path "
            f"lowers that call by inlining the constructor body at the "
            f"construction site — so the call has to name exactly one of them, "
            f"by its positional count together with the parameter names its "
            f"keywords spell. Pass arguments one of them takes")


def construction_init_body_refusal(name: str, why: str) -> str:
    """A declared `__init__` this path cannot inline, and WHICH LINE says so.

    The same construction `construction_init_arity_refusal` describes — a
    declared `__init__` is what `name(...)` calls — narrowed to the one
    statement that stops the inline, named.

    What is refused is a body this path has no lowering for as a sequence of
    stores into the fresh block: a branch, a loop, a call to a method, a read
    of a local of the constructor, a construction of a framed struct whose
    receiver block no prologue here reserved.  Naming the statement is the
    whole content, because the two questions a reader arrives with — "which
    line?" and "what would fix it?" — have different answers per line, and a
    message that said only "this constructor is not lowered" would send them
    back to the class to work out which of its lines mattered.

    What is NOT refused, and the reason it is worth stating: the body need not
    be a call.  A body that is a straight line of `self.<field> = <expr>`
    stores is the same program as the construction followed by those stores,
    which is the shape this path has always emitted, so it is inlined rather
    than refused.  That is what makes `Slice(6, len(lst))` — a call to a
    two-parameter constructor that assigns `self.step = None` itself — the
    answer it is instead of a refusal.
    """
    return (f"constructing {name} with arguments is a call to a user-defined "
            f"`__init__` whose body this path does not inline: {why}. This "
            f"path lowers that call by storing each of the constructor's "
            f"`self.<field> = …` assignments into the fresh block at the "
            f"construction site, so what it needs from the body is that it "
            f"IS a sequence of those — a branch, a loop, a call to a method, or "
            f"a read of a name the constructor binds locally is a body with an "
            f"effect this path has not lowered. Use `{name}()` and assign the "
            f"fields, which is the same program with a representation")


def construction_arity_refusal(name: str, got: int, summary: str,
                               missing=(), bases=()) -> str:
    """A construction whose arguments do not cover every field of this struct.

    Named with both counts and the field list, because "wrong number of
    arguments" without the field list is the reader's next question and the
    field list is the answer.

    `missing` is the fields no argument reached, and it changes what the
    message says and why.  With none named it is the arity error this has
    always reported.  With some named, each is a field with NO class-level
    default to fall back on, which is a different fact with a different
    repair: a field WITH a declared default is filled from it, so
    `Config(7)` on `width = 80, height = 24` is a program and this is not
    that.  The partial-construction measurement is why the two cannot share an
    answer (its doc is deleted with the fix; `test_dataclasses_formal.py` and
    `test_formal_run.py` both carry rows for the prefix fill).

    `bases` is the bases this unit does not declare, and it is the clause that
    keeps the message honest about WHY the field list is short. A class with a
    base it inherits its fields from and a class that declares none are the
    same refusal with opposite repairs: the first is fixed by making the base
    visible, the second by declaring the fields. The sentence this replaces
    told the reader of `LaunchError(Exception)` — a docstring and no fields —
    to "give the fields explicitly", which is advice about a class whose
    missing fields are not the problem."""
    # THE BASE CLAUSE, and it is asked FIRST because a class whose fields are
    # short because of a base this image cannot see is a different program from
    # one whose fields are short because the call under-fills them: the first is
    # fixed by making the base visible and the second by naming the fields, and
    # the sentence below each one is advice for the other case. The parameter was
    # plumbed in with the merge that computes it and its sentence went missing
    # from both arms, so a reader of `class MyErr(Widget): """no fields at
    # all"""` was told to "give the fields explicitly" about a class whose
    # missing fields are not the problem — which is the failure this docstring
    # was written to prevent, and `test_formal_run.py`'s
    # `constr_refuse_an_undeclared_base_by_name` is the row that caught it.
    if bases:
        spelled = ", ".join(repr(b) for b in bases)
        return (f"constructing {name} with {got} argument(s) does not match "
                f"its fields ({summary}), and the reason is not the call: "
                f"{name} derives from {spelled}, which this image does not "
                f"declare, so the fields {spelled} would have contributed "
                f"cannot be named here and the field list this call is checked "
                f"against is {name}'s own. Make the base visible to this image "
                f"(declare it in a module this unit compiles, or replace the "
                f"inheritance), which is the same program with a layout this "
                f"path can compute")
    if not missing:
        return (f"constructing {name} with {got} argument(s) does not match "
                f"its fields ({summary}), and {name} declares no `__init__` "
                f"for it to call instead: with no user-defined constructor, a "
                f"struct's fields are filled in DECLARATION ORDER from "
                f"positional arguments and there is no other form, so this "
                f"path can only place a word in a slot it can name. Give the "
                f"fields explicitly (`{name}()` then `obj.<field> = …`), "
                f"which is the same program with a representation")
    names = ", ".join(repr(f) for f in missing)
    return (f"constructing {name} with {got} argument(s) leaves "
            f"{names} unfilled, and {names} {'has' if len(missing) == 1 else 'have'} "
            f"no default this path could materialize: a field is filled from "
            f"its own class-level initializer when the call leaves it out "
            f"({summary}), so a field without one has nothing to fall back on "
            f"and this is the same TypeError the language raises. Pass it, or "
            f"give it a default in the class body")


def construction_keyword_refusal(name: str, keys, why: str,
                                 fields=(), field: str = None,
                                 shapes=()) -> str:
    """`S(a=1)` — a keyword construction the field or parameter binding could not
    resolve.

    One message per `why`, because the failures are different facts
    about the program, and it is the ONE function for all of them because the
    three spellings the keyword form is refused in (a name that is not a field,
    a field given twice, a name that is not a declared `__init__` parameter)
    are three arms of the same rule rather than three rules.

    `why` is one of:

    * `"unknown"` — a keyword names no field of `name`. `fields` is the field
      list and it is printed, because "unknown keyword argument" without the
      names is the shape of message that sends the reader to grep the source
      for a field that is right there in the declaration.
    * `"twice"` — a field is given a value twice: named by a keyword AND
      covered by a positional (`S(1, a=2)` for fields `a, b`), or named by two
      keywords if the parser ever lets that through. CPython calls this
      `got multiple values for argument`; `field` names it.
    * `"twice_parameter"` — the same shape against a declared `__init__`, where
      the word is PARAMETER and not field. It is a separate arm rather than a
      flag on `"twice"` because the sentence has to name the thing the reader
      wrote: "`x` is not a field of P3 (x, y)" is a diagnostic about a struct
      with no constructor, and repeating it for a constructor's own parameter
      would be the same false-vocabulary defect in a new place.
    * `"unknown_parameter"` — `name` declares a user-defined `__init__` and a
      keyword names no parameter of ANY of them, which is CPython's
      `got an unexpected keyword argument`. `shapes` is the declared
      constructors' `InitShape` list and the parameter NAMES are printed,
      because the reader's next move is to compare one name against one list.

    It used to have a fourth, `"init"`, which refused **every** keyword
    against a declared `__init__` on the grounds that "nothing here resolves by
    type or by parameter name, so a keyword call cannot say which one it
    means".  That is deleted rather than narrowed, and the deletion is the fix:
    a keyword DOES name a parameter, so `init_overload_for_call` selects on the
    parameter names the keywords give plus the positional order, and
    `Rng(seed=7)` against `def __init__(out self, *, seed: Int)` is now a
    program.  What is left here is the two facts that binding cannot decide —
    a name nothing declares, and a parameter given twice.

    It used to be ONE blanket refusal for every keyword construction, and the
    reason it gave — "reading a keyword as positional would make the program's
    meaning depend on the order the keywords appear in" — was true of the
    naive reading and irrelevant to the real one: the field binding matches each
    keyword against the field list by NAME, which is the one reading that cannot
    depend on any order. `StringSlice(unsafe_from_ptr=p)` is the corpus's own
    spelling of the shape.
    """
    keys = ", ".join(repr(k) for k in keys)
    fields = ", ".join(fields) if fields else "none"
    if why == "unknown":
        return (f"constructing {name} with {keys} — {keys.split(',')[0]} is "
                f"not a field of {name} ({fields}), and a keyword "
                f"construction matches each keyword against the FIELD LIST by "
                f"name, so a keyword that names no field has nowhere to put its "
                f"value")
    if why == "twice":
        return (f"constructing {name} with {keys} gives field {field!r} more "
                f"than one value: a keyword names its field, the positionals "
                f"take the remaining fields in DECLARATION ORDER, and the two "
                f"together must cover each field exactly once. This is the same "
                f"`TypeError` CPython raises — got multiple values for argument "
                f"{field!r}")
    if why == "twice_parameter":
        return (f"constructing {name} with {keys} gives parameter {field!r} "
                f"more than one value: a keyword names its parameter and the "
                f"positionals take the rest in DECLARATION ORDER, so the two "
                f"together must cover each parameter exactly once and neither "
                f"store is a program the source wrote. This is the same "
                f"`TypeError` CPython raises — got multiple values for argument "
                f"{field!r}")
    if why == "unknown_parameter":
        declared = "; ".join(
            ", ".join(p for p, _d in shape.params) for shape in shapes
            if shape.params) or "none"
        return (f"constructing {name} with {keys} is a call to a user-defined "
                f"`__init__`, and {keys.split(',')[0]} is not a parameter of "
                f"any of them ({declared}). A keyword is bound to the parameter "
                f"it NAMES, which is how this call selects the overload — the "
                f"positional arguments take the rest in DECLARATION ORDER — so "
                f"a keyword that names no parameter has nowhere to put its "
                f"value. This is CPython's `TypeError`: __init__() got an "
                f"unexpected keyword argument")
    return (f"constructing {name} with {keys} is a keyword construction this "
            f"path does not lower, and the reason is not the keyword itself — "
            f"see `construction_keyword_refusal`'s caller")


def keyword_spread_refusal(subject: str, operand: str) -> str:
    """Why `S(a=1, **m)` / `f(a=1, **m)` is refused: the KEYS are not knowable.

    `subject` is the phrase the refusal is about, already spelled by its caller
    in that caller's own terms — `constructing P`, `call f()` — because the two
    sites that raise it are different constructs and a message that named the
    wrong one would send the reader to the wrong line, which is the failure mode
    `bugs/formal/FORMAL_known_limits.md` records.

    ARCH-FREE and asked from the shared plan (`struct_construction_plan`), which
    is where the false sentence it replaces was produced.

    **The sentence it replaces was false about the program.** `**m` reaches the
    AST as an entry of `args` wrapped in `UnaryOp('**')`, and the field binding
    zipped `args` against the FIELD LIST, so the spread was read as a POSITIONAL
    value: `S(a=1, **{'b': 2})` bound `a` to the whole mapping and then reported
    that field `a` had "more than one value" — a duplicate the source does not
    contain — and one keyword fewer would have stored the mapping's own word
    into `a`'s slot. A literal spread is now un-spread into the keyword list
    before any of that, so this message is only reached by a spread whose keys
    cannot be read at the construction site.

    **CPython agrees with the refusal**, which is what makes it a limitation and
    not a defect: `S(a=1, **{"a": 2})` is a run-time `TypeError` there too, and
    the only way to know which is which is to know the keys. Answering it the
    other way — "the explicit keywords win and the spread fills the rest" —
    would silently accept the program the rule exists to catch.

    The last sentence names the OTHER half of the gap, because a reader who
    reaches for `**kwargs` hits it immediately and it is the true blocker: a
    `**`-PARAMETER is not readable on this path at all — a formal value is one
    64-bit word and a callee has no variadic ABI to find the extra arguments in
    — so the keys cannot be carried through one either. See
    `“`struct` keyword arguments are silently dropped”` for the gimple-side
    half of the same question.
    """
    return (
        f"{subject} spreads `{operand}` with `**`, and a spread's "
        f"KEYS are not knowable at the construction site: the mapping is a value "
        f"this path cannot enumerate, so there is no saying which field each key "
        f"names, and `S(a=1, **{{'a': 2}})` is a run-time `TypeError` in "
        f"CPython too — the only way to tell it from `S(a=1, **{{'b': 2}})` is "
        f"to know the keys. A spread of a dict LITERAL is un-spread and "
        f"answered like any other keyword (both keys and values are in the "
        f"source), so write the keywords out, or pass the mapping as an ordinary "
        f"parameter this path can carry. Note that a `**`-PARAMETER cannot be "
        f"the operand here either: a formal value is one 64-bit word and this "
        f"target has no variadic ABI, so a callee cannot read its own "
        f"`**kwargs` — which is the capability to build before a spread through "
        f"one is answerable."
    )


def _unspread_keyword_mappings(args, kwargs, name: str = "this construction",
                               mappings=None):
    """`(args, kwargs, refusal)` — `**` spreads folded in, or why one cannot be.

    A `**mapping` is not an argument: it is a set of arguments whose NAMES are in
    the mapping. `fire_compiler.py`'s `_parse_paren_args` keeps the `**` marker
    alive by appending `UnaryOp('**', mapping)` to `args`, which is right for an
    interpreter (it splices at call time) and was wrong here, because the field
    binding zips `args` against the field list and so read the spread as the
    next POSITIONAL value.

    **A dict LITERAL is un-spread, with its VALUES**, which is the whole of what
    makes this an added capability rather than a new refusal: `S(a=1, **{'b':
    2})` is ordinary Python, both keys and both values are written in the
    source, and a dict subscript by a literal key already lowers (`d['a']` is
    1), so the keyword list the rest of the plan sees is exactly the one the
    source wrote. The duplicate check then applies unchanged, which is what keeps
    `S(a=1, **{'a': 2})` a refusal — CPython's `TypeError` — rather than
    something this path invented.

    Any other operand (a name with no single literal binding, a computed dict, a
    call) is refused by name: the keys are not in the source at this point and
    guessing them is the fabrication `formal/known_limits.md` calls a false PASS.
    A `*` spread is deliberately NOT touched: it is a POSITIONAL expansion rather
    than a keyword one, it has its own refusal, and it is not this function's
    business.

    **A LOCAL whose only ever binding is such a literal is un-spread the same
    way**, and `mappings` is that evidence: `{name: DictExpr}` from
    `ValueKinds.dict_inits`, passed by every caller that holds the enclosing
    function's `ValueKinds` (the build pass builds one; the emitters already
    have one). The keys are then as knowable as a literal's, because the name has
    exactly one home and it is in the source; a name bound twice is absent from
    `mappings` and falls through to the refusal above, which is the same
    tombstone rule the subscript path reads.
    """
    plain, folded, refusal = [], list(kwargs), None
    for arg in args:
        if isinstance(arg, F.UnaryOp) and arg.op == "**":
            operand = arg.operand
            if mappings and isinstance(operand, F.IdentExpr):
                # A name whose only binding is a dict literal resolves to that
                # literal; a name with no such binding (or a tombstone) keeps
                # itself, and `literal_dict_items` then answers None.
                operand = mappings.get(operand.name) or operand
            items = literal_dict_items(operand)
            if items is None:
                refusal = keyword_spread_refusal(name, spelled(arg.operand))
                break
            folded.extend(items)
            continue
        plain.append(arg)
    return plain, folded, refusal


def literal_dict_items(expr):
    """`[(key, value)]` for a dict LITERAL with literal keys, else None.

    None for anything whose keys are not written where the mapping is: a name, a
    call, a comprehension, a dict with a non-literal key. `None` is what the
    caller turns into a refusal, so the conservative answer has to be the
    un-answerable one — a key that is computed could be any of the struct's
    fields, or none of them.

    Both halves are needed, not just the keys: the value is what the field gets
    stored, and a spread whose keys are known but whose values are computed
    would have to be evaluated through the mapping, which is the read this path
    has no representation for. `StringLiteral` and `IntLiteral` keys only, since
    those are the two a struct field name can be spelled as in a dict display
    that this parser produces (`{'a': 1}` is a keyword; `{"a": 1}` is a
    string).

    **A duplicate key inside the literal is COLLAPSED, last value wins**, which
    is CPython's own dict-display rule and the difference between `{'b': 2, 'b':
    3}` (one key, value 3) and a keyword given twice.  The collapse is here
    because it is the literal's semantics; a duplicate ACROSS the call site (an
    explicit keyword against a spread) is still the ordinary duplicate check's.
    """
    if not isinstance(expr, F.DictExpr):
        return None
    out = []
    index = {}
    for pair in (getattr(expr, "pairs", None) or ()):
        key = pair[0] if isinstance(pair, (list, tuple)) and pair else None
        value = pair[1] if isinstance(pair, (list, tuple)) and len(pair) > 1 \
            else None
        if isinstance(key, F.StringLiteral):
            name = key.value
        elif isinstance(key, F.IntLiteral):
            name = str(key.value)
        else:
            return None
        if name in index:
            # A dict LITERAL's later duplicate key OVERWRITES the earlier one —
            # CPython's own rule, so `{'b': 2, 'b': 3}` is `{'b': 3}` and
            # `f(a=1, **{'b': 2, 'b': 3})` is `f(a=1, b=3)`, not a duplicate
            # keyword.  Collapsing here keeps the literal's semantics: the
            # duplicate check downstream is about a keyword given twice AT THE
            # CALL SITE (an explicit keyword against a spread, or a key two
            # spreads both carry), and a literal's own duplicate is neither.
            # Without this the un-spread handed the check both pairs and a
            # program CPython runs was refused with "got multiple values for
            # argument 'b'".
            out[index[name]] = (name, value)
        else:
            index[name] = len(out)
            out.append((name, value))
    return out


def local_dict_literals(fn) -> dict:
    """`ValueKinds(fn).dict_inits()` — the locals of `fn` whose only binding is
    a dict literal, for the callers that have a function and no `ValueKinds` of
    their own. The build pass is the one such caller; the emitters already hold
    the `ValueKinds` they scanned and pass `ValueKinds.dict_inits` directly. One
    reader of `_dict_inits` for the spread path, so the two callers cannot
    disagree about which `**` a local can be un-spread through.
    """
    return ValueKinds(fn).dict_inits()


def construction_nested_slot_refusal(name: str, field: str, arg,
                                    nested_name: str) -> str:
    """A construction argument landing on a field the constructor PLACED.

    The one positional argument this path must refuse for a reason of its own.
    The slot is not an ordinary slot: `struct_nested_frame_fields` placed a
    frame in it, in the object's OWN block, and that placement is what makes
    the word in it mean anything — it is a frame address whose layout this
    compiler chose.  Storing an argument over it would leave a word in a slot
    that every reader (`self.<field>.<field>`) treats as a frame base, so a
    field read would compute an address out of a value.

    The two honest ways out are both in the message, and neither is "just store
    it": assign the field, which the write path already handles and which is
    why a written field is excluded from the placement list in the first
    place, or declare the field untyped, which takes it out of the placed set.
    """
    return (f"constructing {name} with {_construction_arg_spelling(arg)} as "
            f"field {field!r} is refused on this path: {field!r} is declared "
            f"as a {nested_name}, a struct of this module whose receiver is a "
            f"frame of 8-byte slots, so the constructor PLACED a {nested_name} "
            f"frame in that slot and in the object's own block — a word stored "
            f"over it would leave a value where every read of "
            f"`self.{field}.…` computes a frame base from it. Assign the field "
            f"after `{name}(…)`, which is the same program and is the form the "
            f"placement's own write-once rule already anticipates")


def construction_copy_source_refusal(name: str, arg, struct_names) -> str:
    """`S(x)` where `x` is a frame, but not a frame of `S`.

    The one copy that cannot be a copy, and the reason is that a copy here is a
    SLOT-FOR-SLOT copy: slot `k` of the source into slot `k` of the
    destination, which means anything only if the two layouts are the same
    layout.  A different struct is a different layout by definition, and a
    name that may be either is two layouts with no path sensitivity to say
    which — the same `struct_frame_slot_candidates` question one level in, and
    it has the same answer: agree or refuse.
    """
    who = ", ".join(struct_names) if struct_names else "another struct"
    return (f"constructing {name} with {_construction_arg_spelling(arg)} is a "
            f"COPY CONSTRUCTION and the argument is a {who} frame, not a "
            f"{name} one: a copy on this path is a slot-for-slot copy — slot k "
            f"of the source into slot k of the destination — so it is only "
            f"defined when the two layouts are the same layout. Construct "
            f"{name}() and assign the fields, which is the same program with "
            f"a representation")


def construction_copy_unrecognised_refusal(name: str, arg) -> str:
    """`S(x)` where nothing here can say what `x` is.

    The refusal that matters most in this section, because it is the one whose
    absence is a silently-wrong answer rather than a missing feature.  A copy
    needs a BASE to copy from, and on this path the only thing that says a word
    is a frame address is the holder analysis — a name bound from a framed
    struct's constructor, a copy of such a name, a method receiver, or a
    visible callee's first parameter, carried to a fixpoint.  A name outside
    that set is a plain word, and reading slot `k` of it would be reading
    whatever eight bytes the word happens to name.

    So an ABSENT answer is the answer, which is the same tie-break
    `frame_field_type_candidates` uses and for the same reason: a doubtful
    case must be able to fall out of the typed set and never into it.
    """
    return (f"constructing {name} with {_construction_arg_spelling(arg)} is a "
            f"COPY CONSTRUCTION and nothing here can say that argument is a "
            f"{name} frame: a copy needs a base to copy from, and the only "
            f"thing on this path that says a word is a frame address is the "
            f"holder analysis — a name bound from a framed struct's "
            f"constructor, a copy of one, a method receiver, or a visible "
            f"callee's first parameter. This name is none of those, so it is a "
            f"plain word, and copying slot k out of it would copy whatever "
            f"eight bytes that word happens to name. Construct {name}() and "
            f"assign the fields, which is the same program with a "
            f"representation")


def struct_construction_plan(struct_def, call, decls: dict,
                             candidates: dict, rets=None, mappings=None) -> tuple:
    """`(plan, refusal)` — which of the three shapes `S(...)` is, or why not.

    THE decision, in the shared model, so the two backends cannot answer it
    differently and the build pass (which refuses before either backend runs)
    and the emitters (which have to emit) read one table.  `decls` is
    `{name: StructDef}` for the structs this module declares; `candidates` is
    `formal/build.py`'s `{holder name: [StructDef, …]}` for the function the
    call is in — the recognition a copy construction needs, and the only thing
    in the compiler that can say a word is a frame address, and `rets` is
    `CalleeReturnTable`'s `{name: declared return annotation}` plus its reading
    of a callee that declares none — the evidence for the one argument kind that
    is refused, a container returned by a callee (`_callee_container_evidence`).

    A `plan` is `(kind, …)`:

    | kind | payload | what the emitter does |
    |---|---|---|
    | `CONSTRUCTION_DEFAULT` | — | the existing `S()`: every field at its own default, and every placed nested frame brought up |
    | `CONSTRUCTION_POSITIONAL` | `[(field, slot)]` in DECLARATION ORDER, one per argument | evaluate each argument, store it at `base + 8·slot` |
    | `CONSTRUCTION_INIT` | `[(field, slot, value)]` in the CONSTRUCTOR BODY's order | every field at its default first, then evaluate each `value` and store it at `base + 8·slot` |
    | `CONSTRUCTION_COPY` | the slot count | evaluate the source, then `n`-slot copy into the fresh block |

    `slot` is `None` in the positional payload exactly when the struct is a
    one-word VALUE rather than a frame: there the argument is not stored at
    all, it IS the result, which is the same statement as "stored at slot 0 of
    a zero-byte frame" and is the only reading of `S(x)` that does not invent
    storage.  `CONSTRUCTION_INIT`'s `value` is an AST node to evaluate at the
    site — a constructor's own parameter, defaulted or bound — and for a
    one-word struct the LAST such store is the whole value, for the same
    reason.

    The refusals, each with its own message and its own reason, are in the
    functions above; a reader who wants to know which construct is being
    refused can tell from the first clause of each.
    """
    name = struct_def.name
    decls = decls or {}
    candidates = candidates or {}
    args = list(getattr(call, "args", None) or [])
    kwargs = list(getattr(call, "kwargs", None) or [])
    # A `**` SPREAD is folded into the keyword list before anything reads
    # `args`, and this is the only place it can be: `args` is zipped against the
    # field list further down, so a spread left in it would be read as a
    # POSITIONAL value — which is how `S(a=1, **{'b': 2})` came to say that
    # field `a` had "more than one value". `_unspread_keyword_mappings`'s own
    # docstring has the measurement and the reason a literal spread is answered
    # rather than refused.
    args, kwargs, spread_refusal = _unspread_keyword_mappings(
        args, kwargs, f"constructing {name}", mappings)
    if spread_refusal is not None:
        return (None, spread_refusal)
    slots = struct_frame_slots(struct_def)
    shapes = struct_init_shapes(struct_def)
    summary = struct_field_summary(struct_def)
    # A DECLARED `__init__` outranks everything below, and it has to: with one,
    # `S(a, b)` is a call to it, so every message underneath — the arity one
    # included — is describing a construct the source does not contain.
    # `Slice(6, len(lst))` against a three-field `Slice` is the case, and it is
    # twenty stdlib files' first blocking fact.
    #
    # It is a CALL, and a call does not have to be emitted to be RUN: a body
    # that is a straight line of `self.<field> = …` stores is the same program
    # as the construction followed by those stores, which is a shape this path
    # already emits, so the stores are the plan.  What is left of the old
    # blanket refusal is the two facts the inline genuinely needs and cannot
    # supply — an arity that selects exactly one overload, and a body that is
    # only those stores.
    #
    # READ BEFORE the zero-argument case, and that ordering is the whole of
    # premise (B2)'s removal.  `S()` used to return `CONSTRUCTION_DEFAULT`
    # before this lookup, so a declared `__init__` was inlined only where the
    # call had ARGUMENTS to bind to it — and `S()` on a struct whose
    # constructor takes none came up at its class-level defaults with the body
    # never run.  Measured: `struct Z(a=8, b=9)`, `var z = Z()` then `z.a`,
    # returned 0 where CPython returns 8, on BOTH architectures, with nothing
    # refused and nothing printed.
    #
    # "THE COUNT SELECTS NOTHING" was the stated reason for the early return
    # and it is answered here rather than avoided: `init_overload_for_arity` is
    # the same function that selects an overload for every other count, it
    # admits a count of 0 exactly when some declared overload takes no required
    # parameter, and it answers `ambiguous` — a refusal — when two of them
    # would.  So `S()` is decided by the same rule as `S(1)` and neither of the
    # two holes the early return was avoiding is open.  A `__init__` that
    # REQUIRES a parameter is the other half and is now what the language
    # says: `Bag4()` against `def __init__(out self, n, m)` is a `TypeError`,
    # and it is refused as one, naming the declared overloads.
    if shapes:
        # **READ THIS BRANCH BEFORE THE TWO BELOW, and that ordering is what
        # this comment used to only claim.** `unmatched` matched every keyword
        # against the FIELD LIST and `construction_arity_refusal` said "with no
        # user-defined constructor … and Rng declares no `__init__` for it to
        # call instead" — both of them answers about a struct that HAS a
        # constructor, so both were false about `struct Rng: def __init__(out
        # self, seed: Int): …` constructed as `Rng(7)`, and `Rng(seed=7)` was
        # refused as a keyword naming "no field". The claim at the top of this
        # function ("a DECLARED `__init__` outranks everything below, and it has
        # to") was right and was not true of the code.
        shape, bindings, why, why_names = init_overload_for_call(
            shapes, args, kwargs)
        if why == "unknown_parameter":
            return (None, construction_keyword_refusal(
                name, why_names, "unknown_parameter", shapes=shapes))
        if why == "twice":
            return (None, construction_keyword_refusal(
                name, why_names, "twice_parameter", field=why_names[0]))
        if why is not None:
            return (None, construction_init_arity_refusal(
                name, shapes, len(args), why, missing=list(why_names)))
        stores, refusal = init_body_stores(struct_def, call, shape, bindings,
                                           decls, rets)
        if refusal is not None:
            return (None, refusal)
        # A ONE-FIELD struct whose constructor stores into its only field: the
        # inlined store is the whole value, so the one-word rule applies here for
        # the reason `one_word_store_refusal`'s docstring gives. Read off
        # `slots`, the same list the positional path reads, so "which field is
        # the value" has one answer.
        if len(slots) == 1 and not struct_is_framed(struct_def):
            only = slots[0]
            for store_field, _slot, value in stores:
                if store_field != only:
                    continue
                refusal = one_word_store_refusal(name, only, value,
                                                 candidates, rets)
                if refusal is not None:
                    return (None, refusal)
                break
        placed = {field: child.name
                  for field, _slot, child in struct_nested_frame_fields(
                      struct_def, decls)}
        for field, _slot, value in stores:
            if field in placed:
                # A field the layout PLACED, still being assigned. It cannot be
                # the redundant store `init_body_stores` drops — that one never
                # reaches here — so it is a word over a frame, which is the
                # corruption this refusal has always named. Kept as its own
                # check rather than folded into the one above because it is a
                # different question: "may this store exist" was answered yes
                # and dropped; "may this store overwrite a placed frame" is no.
                return (None, construction_nested_slot_refusal(
                    name, field, value, placed[field]))
        # A field the body does NOT assign keeps its class-level default, and
        # the language default-initializes before the constructor runs, so the
        # emitters bring every slot up first exactly as `S()` does.  A default
        # that cannot be materialized is refused by them, by field, as it is
        # for `S()`.
        return ((CONSTRUCTION_INIT, stores), None)
    # Everything below is a struct that declares NO constructor, which is what
    # makes these three the right questions here: `S(...)` fills the FIELD LIST
    # in declaration order, and the two refusals above are about a field list
    # this struct actually has.
    unmatched = [k for k, _v in kwargs if k not in slots]
    if unmatched:
        # A keyword that names no field is a `TypeError` in every language this
        # path stands in for, and it is asked BEFORE the shape refusals below
        # because it is the more specific fact about the call: a reader who
        # wrote `Config(widht=7)` needs to be told the name is wrong, not that
        # the argument count does not match.
        return (None, construction_keyword_refusal(
            name, unmatched, "unknown", slots))
    if not struct_is_framed(struct_def) and len(slots) != 1 and (args or kwargs):
        # Zero or two-plus fields with no block to fill: a formal value is one
        # 64-bit word and a multi-field struct has no value form, so there is
        # nowhere to put an argument at all.  Asked BEFORE the field binding so
        # the message is about the shape rather than about a keyword that could
        # not have been matched to a field list this struct does not have.
        return (None, construction_arity_refusal(
            name, len(args), summary,
            bases=struct_unresolved_bases(struct_def)))
    if not args and not kwargs:
        # The existing shape, for a struct that declares no constructor at all:
        # every field at its own default, and every placed nested frame brought
        # up.  Deliberately NOT re-decided here: `S()`'s refusal for a
        # non-literal default belongs to `struct_frame_representable` /
        # `struct_default_word` and has its own message, and a second copy of
        # the decision is a second thing to keep in step with the first.
        return ((CONSTRUCTION_DEFAULT,), None)
    framed = struct_is_framed(struct_def)
    # A FRAMED struct.  One argument that is a recognised frame of THIS struct
    # is a copy, and it is checked before the arity rule because arity is what
    # makes it look wrong: `R(r)` on a two-field `R` is not a one-field
    # construction, it is a copy of a two-field object.
    if framed and len(args) == 1 and not kwargs:
        src = _frame_source_structs(args[0], candidates)
        if src is not None:
            if len(src) != 1 or src[0] is not struct_def:
                return (None, construction_copy_source_refusal(
                    name, args[0], [s.name for s in src]))
            return ((CONSTRUCTION_COPY, len(slots)), None)
        if isinstance(args[0], F.IdentExpr):
            # A name, and NOT a holder: a plain word.  `S(x)` with a plain word
            # is an arity error on a multi-field struct and saying so is the
            # whole content — but the copy reading is the one a reader will
            # have in mind, so it is named as such rather than left to be
            # inferred from a count.
            return (None, construction_copy_unrecognised_refusal(name, args[0]))
    # WHICH FIELD each supplied argument fills, and whether the ones no
    # argument reached have a class-level default to come from.  This is the
    # whole of "supply some of the fields": a positional argument takes the
    # slot at its own index, a keyword takes the field it NAMES, and a field
    # neither reached is filled from its own declared initializer — which is
    # CPython's generated `__init__` and the language's own rule for a
    # `@dataclass` field default, and is why `Config(7)` on `width = 80,
    # height = 24` is a program.
    #
    # A field with NO declared default keeps this an arity refusal, and that
    # is not timidity: `struct_field_default` reports `DEFAULT_NONE` for a field
    # with no initializer, which is the zeros a fresh word of memory holds, not
    # a value the language would substitute for an omitted argument. Accepting
    # it would build `Config(7)` as `width = 7, height = 0`, which runs and
    # prints a number the source never wrote, where both Mojo and CPython raise
    # `TypeError`. So the one condition on the partial fill is that the unfilled
    # field has something real to be filled from.
    bound, refusal = _construction_field_bindings(
        struct_def, args, kwargs, slots, summary)
    if refusal is not None:
        return (None, refusal)
    if not framed:
        # One field: the whole value IS that field, so there is nothing to
        # store — the argument is the result.  The only question left is
        # whether an argument reached the field at all, and
        # `_construction_field_bindings` has already refused a call that named
        # no field, named one twice, or left a field with no default unfilled.
        only = slots[0]
        arg = bound[only]
        if arg is None:
            return ((CONSTRUCTION_DEFAULT,), None)
        refusal = one_word_store_refusal(name, only, arg, candidates, rets)
        if refusal is not None:
            return (None, refusal)
        return ((CONSTRUCTION_POSITIONAL, [(only, None)]), None)
    placed = {field: child.name
              for field, _slot, child in struct_nested_frame_fields(
                  struct_def, decls)}
    partial = bool(kwargs) or any(arg is None for arg in bound.values())
    for field, arg in bound.items():
        if field in placed:
            return (None, construction_nested_slot_refusal(
                name, field, arg, placed[field]))
        refusal = construction_arg_dead_blob_refusal(name, field, arg, rets,
                                                     struct_def)
        if refusal is not None:
            return (None, refusal)
        if arg is not None:
            continue
        # A field filled from its own default and holding a nested FRAME: the
        # default is a word and the slot is about to hold an address, and the
        # nested-frame loops overwrite it — so the only thing to check is that
        # the default itself is materializable, which is `placed` saying this
        # struct has one there. Nothing more to refuse.
    if not partial:
        return ((CONSTRUCTION_POSITIONAL,
                 [(field, struct_frame_slot(struct_def, field))
                  for field in slots]), None)
    # Every slot is brought up at its class-level default first and then these
    # stores are applied, which is `CONSTRUCTION_INIT`'s shape and its emitter —
    # the same one a declared `__init__` body's stores go through. Two
    # producers, one lowering, and no second copy of "bring the block up then
    # write into it".
    return ((CONSTRUCTION_INIT,
             [(field, struct_frame_slot(struct_def, field), arg)
              for field, arg in bound.items() if arg is not None]), None)


def one_word_construction(struct_def, call, decls: dict, candidates: dict,
                          rets=None, mappings=None) -> tuple:
    """`(value, refusal)` — the ONE WORD a construction of a zero-or-one-field
    struct evaluates to at the site, or why there is not one.

    `value` is an AST node for the emitter to evaluate, or None for "a fresh
    word" — the zero a construction that stores nothing evaluates to.  The two
    are kept apart because None is also what a REFUSAL returns, and a refusal
    must never lower to a zero: that is the shape of wrong answer this whole
    path exists to prevent, and a caller that read the refusal as the value
    would produce exactly one, silently.

    **THE decision, in the shared model, because it was in two emitters and one
    of them was wrong.**  Both backends asked `struct_construction_plan` only
    when the call carried an ARGUMENT, and answered `S()` — no argument at all
    — with a fresh zero word without asking.  So a one-field struct whose
    `__init__` takes no required parameter had its constructor body DROPPED at
    the construction site:

        class C:
            def __init__(self):
                self.n = 20
            def get(self):
                return self.n

        def main(n: Int) -> Int:
            var c = C()
            return c.get()

    built, ran, and returned 0 on both architectures, where CPython returns 20.
    Nothing was refused, nothing was printed, the exit status was a plausible
    small integer, and the two machines AGREED — so no parity row, no
    `refuse:` row and no engine diff could see it.  A two-field struct with the
    same constructor answered 203, because the framed emitter has always asked
    the plan for every shape; the difference was never about `__init__`, it was
    about which emitter the construction reached.

    Reading the plan for EVERY shape is also what makes the argument-less
    constructions that already worked here stop being special cases.  `S()`
    against a struct with no constructor is `CONSTRUCTION_DEFAULT` with no
    stores, and a constructor that assigns nothing is `CONSTRUCTION_INIT` with
    no stores: both are None here, which is the fresh word they always were. A
    constructor the caller left an argument to defaults on is `CONSTRUCTION_INIT`
    with that default's expression in it, which is a store the previous gate
    could not see.  And a constructor that REQUIRES a parameter is now the
    arity refusal the plan has always described ("`Bag4()` against
    `def __init__(out self, n, m)` is a `TypeError`") instead of a silent zero,
    which is the same refusal the framed emitter and the build pass have always
    raised for it.

    The rule that turns a plan into a word is the one `struct_construction_plan`
    already states for a one-word struct: there is nowhere to STORE the
    constructor's value — the receiver IS the field — so the LAST of the inlined
    body's stores is the whole result.  A one-field struct has at most one such
    store, so "last" is the only one; saying it this way keeps the emitters from
    having to know that, and keeps a future multi-store body on the same
    sentence rather than on an assumption about field counts."""
    plan, refusal = struct_construction_plan(struct_def, call, decls, candidates,
                                             rets, mappings)
    if refusal is not None:
        return (None, refusal)
    # `CONSTRUCTION_DEFAULT` carries NO payload at all (it is the one-element
    # `(CONSTRUCTION_DEFAULT,)`), so the payload is read by arity and not by
    # indexing: the emitters' old `plan[1]` was a shape that would have raised
    # the moment a partial construction came back as DEFAULT, and the fix for a
    # wrong answer is not a second wrong answer wearing an IndexError.
    payload = plan[1] if len(plan) > 1 else ()
    if plan[0] in (CONSTRUCTION_INIT, CONSTRUCTION_DEFAULT):
        return (payload[-1][2] if payload else None, None)
    return (construction_supplied_argument(call), None)


def construction_supplied_argument(call):
    """The argument that reached a ONE-FIELD struct's field, which IS its value.

    Positional first, else the single keyword's value — and reading the keyword
    here is safe because `struct_construction_plan` has already refused every
    call for which that is not exactly one argument: a keyword naming no field,
    a field named twice, and a field no argument reached each return a refusal
    before an emitter runs. So this is a READ of the decision, not a second
    opinion about it, which is why it is here rather than each emitter reaching
    for `e.args[0]` — the one thing a construction of a one-field struct
    actually evaluates changed shape when keywords stopped being refused, and
    an emitter that kept indexing `e.args` would raise `IndexError` on
    `One(x=9)`."""
    args = list(getattr(call, "args", None) or [])
    if args:
        return args[0]
    return list(getattr(call, "kwargs", None) or [])[0][1]


def _field_has_a_declared_default(struct_def, name: str) -> bool:
    """Does this field carry a class-level initializer this path can read?

    `struct_field_default`'s own distinction, read as a predicate: a LITERAL
    initializer is a value the language has at every call site, and
    `DEFAULT_NONE` — a field with no initializer at all — is the zeros a fresh
    word of memory happens to hold.  Substituting the second for the first is
    the one thing a partial construction must not do, which is why
    `_construction_field_bindings` asks this rather than assuming an unfilled
    slot is free."""
    return struct_field_default(struct_def, name)[0] != DEFAULT_NONE


def _construction_field_bindings(struct_def, args, kwargs, slots, summary: str):
    """`({field: argument or None}, refusal)` — which field each argument fills.

    THE rule for "supply some of the fields", and one function for it because
    the positional and keyword spellings have to agree about what is left over:
    two readers would be two chances to compute a different set of unfilled
    fields, and a field that is unfilled in one and filled in the other is a
    word in the wrong slot.

    Three rules, and the third is the load-bearing one:

      * a positional argument takes the slot at its own index, in declaration
        order — the reading `S(a, b)` has always had, unchanged;
      * a keyword takes the field it NAMES, so the program's meaning cannot
        depend on the order the keywords happen to appear in. That was the
        stated reason for refusing every keyword, and matching them is the
        answer to it. A keyword naming no field is a `TypeError` and is
        refused by name; a field reached twice is a `TypeError` and is
        refused by name;
      * a field no argument reached is filled from its own class-level
        initializer, and MAY be — so `None` in the payload is "from the
        default", which is exactly what `CONSTRUCTION_INIT` leaves in the slot
        when it is not in the store list. A field with no declared default has
        nothing to be filled from and the whole construction is an arity
        refusal naming it.

    The refusal for the last case is the arity one rather than a new message
    because it IS the arity one — the count does not cover the fields — and
    `construction_arity_refusal`'s `missing=` clause is what distinguishes the
    two in the words."""
    if len(args) > len(slots):
        return (None, construction_arity_refusal(
            struct_def.name, len(args), summary,
            bases=struct_unresolved_bases(struct_def)))
    bound = {}
    for arg, field in zip(args, slots):
        bound[field] = arg
    for key, value in kwargs:
        if key not in slots:
            return (None, construction_keyword_refusal(
                struct_def.name, [key], "unknown", slots))
        if key in bound:
            return (None, construction_keyword_refusal(
                struct_def.name, [key], "twice", slots, field=key))
        bound[key] = value
    missing = [f for f in slots
               if f not in bound and not _field_has_a_declared_default(
                   struct_def, f)]
    if missing:
        return (None, construction_arity_refusal(
            struct_def.name, len(args), summary, missing=missing,
            bases=struct_unresolved_bases(struct_def)))
    return ({f: bound.get(f) for f in slots}, None)


def _callee_container_evidence(arg, rets=None, struct_def=None):
    """`"declared"`, `"inferred"` or None — WHICH evidence says `arg` is a blob.

    The decision half of `construction_arg_dead_blob_refusal`, split out because
    three call sites need it and one of them (`_init_store_value`) asks it about
    an `__init__` body's right-hand side rather than about a construction
    argument.  It replaced `_construction_arg_is_dead_blob`, which returned a
    bool and so could not say WHICH source of evidence fired — which is the fact
    the message names.  The two sources and why the second exists:

    A container LITERAL and a name are not here at all: a literal is built by
    the function whose block is being filled and a name was bound in that
    function or an ancestor, so in both cases the region outlives every read of
    the slot.  `construction_dead_blob_refusal` is where that argument is spelled
    out for the reader.

      * `"declared"` — the callee's return annotation names a bump-allocated
        region (`BLOB_TYPE_NAMES` through `return_type_is_blob`);
      * `"inferred"` — the callee declares NO return type and every one of its
        definitions returns a container (`CalleeReturnTable.returns_container`),
        which is a spelling real Mojo uses constantly and which used to be
        allowed here on the strength of an absence;
      * None — anything else.  A callee this unit does not define, a
        `-> Int` declaration, a callee whose returns disagree with one another,
        an argument that is not a call to a NAME at all (a dotted callee or a
        computed one — `call_callee_name` is the reader, so a comptime
        specialization `f[a]()` IS one, and `List[Self.T]()` / `a.b()` /
        `f()[0]()` are not), and a call to a struct this path PLACES (a frame
        address, one word, with a lifetime the frame layout governs —
        `_callee_is_placed_frame` is the one predicate that knows).  An absent
        answer is the PERMISSIVE one, and the argument for that is the one this
        predicate replaced, restated here because a permission needs its reason
        in the place it is granted: this function's caller: a wrong word in a
        slot is a value the source did not write, while a missed blob is only
        reachable if some method later mutates the container through the slot —
        and that is refused on its own terms today (`list.append()` needs the
        capacity to be known where the list is built, and a slot is not a list
        literal).
    """
    if not isinstance(arg, F.CallExpr):
        # Not a call, so not a value belonging to a callee: a container literal
        # and a name are answered above.
        return None
    # `call_callee_name`, NOT `isinstance(arg.func, F.IdentExpr)`. It is the
    # tree's one reader of "which function does this call name", and a comptime
    # SPECIALIZATION `f[a]` names the same function as its bare twin —
    # which is the whole content of `bugs/formal/FORMAL_a_specialization_defeats_the_
    # frame_escape_refusals.md`, in a reader that decides a REPRESENTATION.
    #
    # Measured here, and it was the permissive direction, which is the expensive
    # one: `Bag2(mklist(), 5)` is refused by
    # `constr_refuse_container_returned_by_a_callee` and `Bag2(mklist[1](), 5)`
    # BUILT, on both architectures. Same callee, same declared `-> List[Int]`,
    # same reclaimed scratch — the only difference is the brackets, and a word
    # that is a pointer into reclaimed memory is exactly what premise (B1) is
    # about.
    #
    # `rets` is keyed by the function's NAME, so the specialized spelling is in
    # it under the bare one; that is why this needs the shared reader rather
    # than a second subscript test here. `None` — a dotted name, a computed
    # callee — is the answer this file's other refusals give for the same reason
    # (`call_callee_name`'s docstring lists both exclusions), and it lands on the
    # permissive tie-break above, which is where an absent answer belongs.
    callee = call_callee_name(arg.func)
    if callee is None:
        return None
    if _callee_is_placed_frame(struct_def, callee):
        return None
    if return_type_is_blob((rets or {}).get(callee)):
        return "declared"
    if getattr(rets, "returns_container", None) is not None \
            and rets.returns_container(callee):
        return "inferred"
    return None


# The annotations that name a BUMP-ALLOCATED REGION on this path — the types
# whose value is a word pointing into the creating function's own reserved
# scratch, as opposed to a word that means something on its own.  `String` and
# its relatives are deliberately NOT here: a string literal has static storage
# duration, so a string is the one pointer on this path with no lifetime
# problem at all, and treating it as a blob would refuse the most common
# argument in the corpus.
BLOB_TYPE_NAMES = frozenset({
    "List", "Dict", "Set", "Tuple", "Optional", "InlineArray", "StaticTuple",
    "Array", "StringRef",
}) | BYTE_BLOB_CTORS


def return_type_is_blob(annotation) -> bool:
    """Whether a declared return type names a bump-allocated region.

    `List[Self.T]` and `unsafe Pointer[Int32]` both reduce through
    `annotation_base_name`, so the type ARGUMENTS are dropped rather than
    compared — the same reading `annotation_base_name` gives a field's declared
    type and for the same reason: the base decides which KIND of thing the word
    is, and the arguments decide nothing this value model has a slot for.

    False for an absent or unreadable annotation.  That is the permissive
    direction and `_callee_container_evidence` says why, at length, because a
    reader who finds this predicate alone would reasonably guess the other way
    round.
    """
    base = annotation_base_name(annotation)
    return base is not None and base in BLOB_TYPE_NAMES


def function_return_types(functions) -> dict:
    """`{name: declared return annotation}` for a unit's functions.

    Read once and passed down rather than reached for, because
    `struct_construction_plan` is called from three places (the build pass and
    the two backends) and each of them has a different shape of function list.
    One reader means all three see the same evidence.
    """
    out = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if name:
            out[name] = getattr(fn, "return_type", None)
    return out


def callees_returning_containers(functions, int_names=None,
                                 string_names=None) -> dict:
    """`{name: element kind or None}` for every callee whose RETURNS are containers.

    The SECOND source of the dead-blob evidence, beside the declared return
    annotation, and it exists because the declaration is absent about half the
    time in real Mojo: `def make(): return [1, 2]` is an ordinary spelling and
    `Bag2(make(), 5)` stores exactly the same dead region a `-> List[Int]`
    declaration would have warned about.  Read with NO `func_kind` hook, which is
    the safety argument rather than a shortcut — the same one
    `_callee_blob_elem_kind` gives: a hook resolves a call in a return position
    by recursing into the callee, and an undecidable answer has to be the
    permissive one.

    The rule is UNANIMITY over every definition of the name, for the reason
    `_callee_blob_elem_kind` states: Mojo overloads are ordinary (`std/builtin/
    reversed` is defined eight times over) and a name that means several bodies
    answers no single question.  One definition returning a list and another
    returning an integer therefore claims nothing, which is the direction that
    keeps a refusal from being a guess.

    The VALUE is the element kind where the returns pin one and `None` where
    they agree only that it is a container — `is_list_kind` is the question the
    callers ask, and an element it does not need is not guessed at."""
    by_name: dict = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if name:
            by_name.setdefault(name, []).append(fn)
    out: dict = {}
    for name, defs in by_name.items():
        elems = set()
        for fn in defs:
            kind = ValueKinds(
                fn, int_names=int_names or INT_TYPE_CTORS,
                string_names=string_names or STRING_TYPE_CTORS).return_kind
            if not is_list_kind(kind):
                break
            elems.add(list_elem_kind(kind))
        else:
            out[name] = elems.pop() if len(elems) == 1 else None
    return out


class CalleeReturnTable(dict):
    """`function_return_types`' table, able to answer the INFERRED case too.

    A dict SUBCLASS rather than a second table, and the reason is that the
    construction pass is handed ONE evidence argument by three callers
    (`formal/build.py` and the two emitters): a separate table would be a second
    thing to thread through all three and a second thing to keep in step with the
    first.  As a subclass, every existing reader of the declared table keeps
    reading a mapping and the extra evidence is a question asked of the same
    object.

    `returns_container(name)` is the dead-blob question, and the ORDER in it is
    the whole decision:

      * a callee that DECLARES a return type is answered by that declaration
        alone, both ways.  A `-> List[Int]` is refused as a dead blob, and a
        `-> Int` is allowed even if its body returns a list — the declaration is
        the contract, and a body that contradicts it is a bug in the program
        rather than a fact about this path's representation;
      * a callee that declares NOTHING is then read from its RETURN STATEMENTS
        (`callees_returning_containers`), which is the case this class exists
        for;
      * anything else — a name this unit does not define, a definition whose
        returns disagree, a `ValueKinds` that could not classify them — claims
        nothing, and claiming nothing is allowed here for the reason
        `_callee_container_evidence` argues at length: a wrong word in a slot
        is a value the source did not write, while a missed blob is only
        reachable through a method that mutates the container through the slot.

    The inference is computed AT MOST ONCE and only when it is asked, so a unit
    with no positional construction that passes a call pays nothing for it."""
    def __init__(self, functions, int_names=None, string_names=None):
        super().__init__(function_return_types(functions))
        self._functions = list(functions or ())
        self._int_names = int_names
        self._string_names = string_names
        self._inferred = None

    def returns_container(self, name: str) -> bool:
        declared = self.get(name)
        if declared:
            return return_type_is_blob(declared)
        if self._inferred is None:
            self._inferred = callees_returning_containers(
                self._functions, self._int_names, self._string_names)
        return name in self._inferred


def _frame_source_structs(arg, candidates: dict):
    """The candidate structs for `arg` if it is a recognised FRAME, else None.

    Two answers and the difference between them is the copy construction's
    whole dependency on the holder analysis:

      * `[S]` — a frame of exactly one struct, and a copy into `S` is a
        slot-for-slot copy of one layout into itself;
      * `[A]`/`[A, B]`/`[A, B, C]` — a frame, but not of a single struct, so
        there is no one layout to copy;
      * `None` — NOT a frame at all.  A name bound from a constructor this path
        does not frame is in `candidates` with an EMPTY list, and that is a
        plain word; a name not in `candidates` at all is a plain word too, and
        the caller refuses it rather than treating it as one, because for a
        COPY the difference between "a plain word" and "a frame whose kind
        this analysis missed" is the difference between refusing a feature and
        copying eight bytes of unrelated memory.
    """
    if not isinstance(arg, F.IdentExpr) or arg.name not in candidates:
        return None
    return list(candidates[arg.name]) or None




# ── THE BLOB-IN-A-FIELD PREMISE ──────────────────────────────────────────
#
# C5's open item, and the one the value-method work meets head-on, so it is
# written down here as a premise with a CHECK rather than left as an accident
# of two unrelated decisions.  A blob (a list or a dict) is not heap storage on
# this path: it is a bump-allocated region of the FUNCTION'S OWN reserved
# scratch, and it dies when that function returns.  So a blob reachable from a
# frame slot has a lifetime that is the shorter of the two — and the moment a
# slot can hold a blob another function built, `self.items.append(x)` inside a
# method appends into reclaimed stack.  The program builds, runs, and returns a
# number nobody wrote.
#
# It is safe TODAY for two reasons, and NEITHER is a property of the frame
# layout.  Both are decisions made elsewhere, and an invariant that holds only
# because of a decision three files away is not an invariant:
#
#   (B1) no method body that actually EXECUTES writes a container into a slot.
#        A literal is materializable at the constructor; a container is a blob
#        with the creating function's lifetime and is not.  The other half of
#        (B1) — a non-literal class-level DEFAULT — is already refused, by
#        `struct_frame_representable`, and is deliberately NOT re-decided
#        below; see `frame_field_premise`.
#   (B2) `S()` does not run `__init__` on a struct whose constructor takes NO
#        REQUIRED PARAMETER, and that is now a refusal rather than a silent
#        zero.  A struct that declares NO constructor at all is premise-free:
#        there is no body to run.  Every slot's value for a refused `S()` is
#        still nothing, because nothing runs.
#
# The two have quite different standing and the check below says so:
#
#   * (B1) is a REAL constraint, enforced here.  A method other than `__init__`
#     runs, so `self.items = List[Self.T]()` inside it puts a blob in a slot
#     today, and the refusal is the point.  This is the one the value-method
#     work must keep true.
#   * (B2) is an ENABLING PREMISE for the `CONSTRUCTION_DEFAULT` shape, which is
#     what a struct that DECLARES no constructor lowers to.  It is reported by
#     name so a reader is told which premise a refusal rests on.  It is not
#     something this check can prove, and a check that appeared to prove it
#     would be the worst kind of check.  A struct that DOES declare a
#     constructor is not under (B2) at all — `S()` goes down the same
#     `CONSTRUCTION_INIT` path as `S(args)`, and the confinement argument in
#     the next paragraph is what keeps that safe.
#
# `S(args)` — and now `S()` on a struct whose `__init__` takes no required
# parameter — is the FOURTH door and it is neither premise: such a construction
# DOES run the constructor, because a constructor does not have to be called to
# be run — `init_body_stores` inlines the body's stores at the site, and the
# argument COUNT (zero included) is what `init_overload_for_arity` reads to pick
# the overload, exactly as it does for every other count.
# That cannot put an unreclaimable word in a slot, and the reason is the
# confinement argument above rather than (B2): the inlined body runs in the
# CONSTRUCTING function, whose scratch holds the block it writes into and
# cannot outlive it, so a container it builds is a container literal, which is
# the case `construction_dead_blob_refusal` already allows and for the same
# reason.  What the inline cannot admit is a container that came back from a
# CALLEE (`_init_store_value` refuses it by the same predicate), and a
# construction of a framed struct, whose receiver block no prologue here
# reserved.  So the three doors a blob can enter a slot through are still
# exactly three, and this is not a fourth one.
#
# Lift (B1)'s method half and a `reset()` in any struct is a use-after-free.
# Lift (B2) and every `__init__` in the corpus becomes one.  Either change turns
# `self.<container>.<op>()` in every method into appending into reclaimed stack,
# and neither change announces itself: the build stays green and the proof side
# sees one word per slot either way.
FRAME_FIELD_BLOB_PREMISE_B1 = \
    "no executed method writes a container into a field"
# (B2) is now a statement about a construction of a struct that DECLARES NO
# CONSTRUCTOR, and the wording says so, because "S() does not run __init__"
# read as a claim about every construction and stopped being one twice over:
# when `S(args)` began inlining the body, and then when `S()` on a struct whose
# `__init__` takes no required parameter began inlining it too.  A struct with
# no constructor has no body to run, so its fields are the class-level defaults
# and the word "run" is not the question.  What the text is FOR is telling a
# reader which of the two premises a refusal rests on, and a reader who is told
# the wrong one is sent to look for a violation of a rule that is not what
# stopped the build.
FRAME_FIELD_BLOB_PREMISE_B2 = "a struct that declares no __init__ has no body to run"


def _is_container_value(value, containers: set, struct_def=None) -> str:
    """A phrase for why `value` is a container, or "" if it is not one.

    A write into a frame slot is a blob write when the value put there is a
    container, and "is a container" is decidable for three shapes and NOT for
    the fourth, so the three are named and the fourth is a stated gap rather
    than a guess in either direction:

      * a list, tuple or dict DISPLAY — unconditionally a container;
      * a call to something this path does not place — conservatively a
        container, because `List[Self.T]()` is a bump-allocated region and a
        call this path cannot see through might be one.  There are TWO
        exceptions and both are about a result whose lifetime is not the
        callee's activation.  A call to a framed struct of this unit is a placed
        frame address, one word, with a lifetime the frame layout governs; and a
        call to a function of THIS unit whose DECLARED return type is a plain
        word (`_callee_returns_plain_word`, answered from the set
        `attach_plain_word_callees` puts on the struct) hands back a `malloc`'d
        buffer or a number rather than a region of the callee's scratch — which
        is what `self.name = mkdtemp(p)` inside a context manager's `__enter__`
        is, and it was refused here until that arm existed;
      * a NAME this method is known to have bound to a container
        (`containers`) — one hop of propagation, which is what catches
        `tmp = [1, 2, 3]; self.items = tmp`;
      * a bare name or an arithmetic expression — **unknown**, and unknown is
        NOT container.  Treating it as one would refuse `self.a = v` in every
        method, which is the shape the whole frame design exists to support,
        and treating it as definitely-not-one would be the guess this premise
        is arranged to avoid.  So it passes, the gap is written down, and what
        closes it is named: the VALUE KIND of a name, which is
        `model.ValueKinds`' question and the value-method table's, not a
        re-derivation to be smuggled in here.
    """
    if isinstance(value, (F.ListExpr, F.TupleExpr, F.DictExpr)):
        return "a container literal"
    if isinstance(value, F.CallExpr):
        callee = value.func.name if isinstance(value.func, F.IdentExpr) else None
        if callee and _callee_is_placed_frame(struct_def, callee):
            return ""
        if callee and _callee_returns_plain_word(struct_def, callee):
            # The callee is a function of THIS module and its declaration says
            # it returns a word. That settles the question premise (B1) asks,
            # because the hazard is specific: a container is a bump-allocated
            # region of the CALLEE's scratch, so it dies with the callee's
            # activation, while a `str` is a `malloc`'d buffer the caller owns
            # and a number is a number. Measured on the case that needed it:
            # `self.name = mkdtemp(p)` inside `TemporaryDirectory.__enter__` was
            # refused here, which is the refusal that stood between
            # `formal/hostmods/tempfile.mojo` and a `TemporaryDirectory` whose
            # contract is the removal on the way out of a `with`.
            return ""
        return (f"a call to {callee!r}, whose result this path does not place "
                f"— `List[T]()` and every other container constructor on this "
                f"path is a bump-allocated region, and this one may be")
    if isinstance(value, F.IdentExpr) and value.name in containers:
        return f"the name {value.name!r}, which this method binds to a container"
    return ""


def _container_binding_names(node, receivers, out: set) -> None:
    """Names this method body binds to a container, for the one-hop case.

    Deliberately ONE hop and deliberately local: the point is to catch
    `tmp = [...]; self.x = tmp`, not to compute a value kind.  A name bound in
    another function, or a parameter, is the stated gap above.

    **`var tmp = [...]` was missing and it is the spelling most of the corpus
    uses**, so the one hop it exists to make did not happen for a `var` binding
    and the write-through it was written to catch went uncaught: `var xs =
    [1, 2]; self.items = xs` reads to a reader as covered and is not.  A
    `VarDecl` binds its name in `.name`, not in `.target`, which is the whole
    difference; `frame_binding_target` is the one reader of that.
    """
    if isinstance(node, list):
        for x in node:
            _container_binding_names(x, receivers, out)
        return
    if isinstance(node, F.FunctionDef):
        return
    target = frame_binding_target(node)
    if target and isinstance(getattr(node, "value", None),
                             (F.ListExpr, F.TupleExpr, F.DictExpr)):
        out.add(target)
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        _container_binding_names(getattr(node, fname, None), receivers, out)


def _container_write(node, receivers, found: list, containers: set,
                     struct_def=None) -> None:
    """Collect `(field, why)` for every container written through a receiver.

    The receiver set is `struct_receivers(st)`, so `this.x = [1]` in a class
    whose methods spell the receiver `this` is seen as readily as `self.x`.
    `struct_def` is threaded down rather than published, because it is what the
    unit-scoped callee answer needs (`attach_plain_word_callees`).
    """
    if isinstance(node, list):
        for x in node:
            _container_write(x, receivers, found, containers, struct_def)
        return
    if isinstance(node, F.FunctionDef):
        return
    if isinstance(node, F.AssignStmt) and isinstance(node.target, F.MemberExpr) \
            and isinstance(node.target.obj, F.IdentExpr) \
            and node.target.obj.name in receivers:
        why = _is_container_value(node.value, containers, struct_def)
        if why:
            found.append((node.target.member, why))
        return
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        _container_write(getattr(node, fname, None), receivers, found,
                         containers, struct_def)


def attach_plain_word_callees(struct_defs, names) -> None:
    """Give every one of `struct_defs` this unit's plain-word callees, in place.

    On the struct rather than published in a module global, for the reason
    `attach_field_evidence` gives and MEASURED here: a module global is the LAST
    writer's answer, and a build compiles other units NESTED. Published, the set
    was whichever import compiled last — measured on
    `formal/hostmods/tempfile.mojo`, where `__enter__`'s `self.name = mkdtemp(p)`
    was checked against SHUTIL's callee list (tempfile imports shutil) and the
    premise refusal came back, while the same file built fine when reached
    through an importer that happened to publish in the other order. A fact
    about one unit attached to that unit's own structs cannot be overwritten by
    a nested build.
    """
    for st in struct_defs or []:
        setattr(st, "_plain_word_callees", frozenset(names or ()))


def _callee_returns_plain_word(struct_def, callee: str) -> bool:
    """Whether `callee` is one of THIS struct's unit's declared word-returning callees.

    Only functions of the unit are in the set, and that is the conservative
    direction rather than an omission: a callee in another unit is a call this
    path cannot see through whatever its source says, and the whole premise is
    about a value whose lifetime is the callee's activation — across a dylib
    boundary this build has the callee's declaration but not its allocation.
    """
    return callee in (getattr(struct_def, "_plain_word_callees", None) or ())


def plain_word_callee_names(functions, structs_by_name=None,
                            int_names=(), string_names=()) -> set:
    """The functions of a module whose declared return type is a plain word.

    `declared_type_kind` is asked rather than a private list of type names,
    because that function is the one place that maps an annotation to a
    representation and the two backends already read it — a second list here
    would be a second answer to "is `-> str` a word", and they would drift the
    first time a name was added to one of them.

    A FRAME return is a word too and is deliberately absent: a frame address is
    one word, but a frame belongs to the function that created it, so storing
    one in a slot has its own lifetime question and is not this table's answer.
    """
    out = set()
    decls = structs_by_name or {}
    for fn in functions or ():
        ann = getattr(fn, "return_type", None)
        kind = declared_type_kind(ann, int_names, string_names, decls)
        if kind in (STR_KIND, INT_KIND, "float", "bool"):
            out.add(fn.name)
    return out


def _callee_is_placed_frame(struct_def, callee: str) -> bool:
    """Whether a call to `callee` yields a frame this path PLACED.

    True for a struct of the module being compiled whose receiver is a frame —
    including a typed-nested field's, which `struct_nested_frame_fields` places
    inside its owner's block.  Both are one word with a lifetime the frame layout
    already governs, which is why a slot may hold them and may not hold a blob.

    Attached to the struct rather than published in a module global, for the
    reason `attach_plain_word_callees` gives and MEASURED on its sibling: a build
    compiles imported units NESTED, so a published set was whichever import
    compiled last.  The drift here is in the SAFE direction — a frame address
    read as "not placed" is an extra refusal, never a wrong answer — which is
    exactly why it went unnoticed and is why it is worth removing rather than
    leaving beside the table that had it backwards.
    """
    return callee in (getattr(struct_def, "_placed_frame_callees", None) or ())


def attach_placed_frame_callees(struct_defs, names) -> None:
    """Give every one of `struct_defs` this unit's placed-frame callees, in place.

    The one piece of unit knowledge `frame_field_premise` needs, carried on the
    struct for the reason `attach_field_evidence` gives: the consumer is a node
    walk with no unit in hand, and a unit-scoped fact that lives in a global is
    the last writer's answer.  Called from `_prepare_functions`, which is the
    single point where the compiled struct set is known.
    """
    for st in struct_defs or []:
        setattr(st, "_placed_frame_callees", frozenset(names or ()))


def struct_field_container_writes(struct_def) -> list:
    """`[(field, spelling)]` — the fields this struct's methods put blobs into.

    `__init__` is EXCLUDED, and the exclusion is the whole content of premise
    (B2): that method does not run on this path, so a container it assigns never
    reaches a slot.  Including it would report every container-shaped struct in
    the corpus as broken, which is a true statement about a program that never
    executes and a useless thing to refuse.
    """
    receivers = struct_receivers(struct_def)
    found: list = []
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            continue
        containers: set = set()
        _container_binding_names(getattr(m, "body", None), receivers,
                                containers)
        _container_write(getattr(m, "body", None), receivers, found, containers,
                         struct_def)
    return found


def frame_field_premise(struct_def) -> tuple:
    """`(ok, which, detail)` — is the blob-in-a-field premise true for `st`?

    The METHOD half of (B1) only, and the exclusion is deliberate rather than
    an omission.  The other half — a non-literal class-level default — is
    already refused, by `struct_frame_representable`, with a message that says
    what is actually wrong with it: the constructor has no scope to evaluate a
    default in.  Re-deciding it here and reporting the blob reasoning instead
    would replace an accurate diagnostic about the default with a true but
    secondary statement about a consequence, and it did: the first version of
    this function re-checked the defaults and turned 67 files' findings from
    "cannot bring its field 'X' up at its default" into the blob message, which
    is a regression in what the reader is told for no new refusal.

    So this is the half the frame layer introduces: a container written by a
    method that EXECUTES, which is the case that was previously unguarded and
    the one the value-method work depends on.

    A container written by `__init__` is not a failure and is not in the answer
    at all; `frame_field_premise_note` is what reports it, because it is the
    evidence that the premise is load-bearing rather than vacuous.
    """
    for field, spelling in struct_field_container_writes(struct_def):
        return (False, FRAME_FIELD_BLOB_PREMISE_B1,
                f"a method of {struct_def.name} assigns {spelling} to "
                f"self.{field}, and a method body RUNS: a list or a dict on "
                f"this path is a bump-allocated region of the function's own "
                f"reserved scratch, so the slot would hold a blob that dies "
                f"when that function returns, and a method reaching through "
                f"the slot afterwards appends into reclaimed stack")
    return (True, None, None)


def frame_field_premise_note(struct_def) -> str:
    """What the premise is resting on for THIS struct, for a diagnostic to say.

    Empty when there is nothing to say.  Non-empty exactly when `__init__` would
    have put a container in a slot had it run — which is the shape of nearly
    every container in the corpus, so this is the sentence that stops the
    premise from being an accident: it names the line whose non-execution is
    doing the work.

    The second sentence is the THIRD door, and it is here because the
    construction shapes added one.  A slot can now hold a container without any
    method writing it: `S([1, 2, 3])` puts a literal straight into a field.  That
    is sound and the reason is worth having on the record rather than in a
    comment three files away — a container LITERAL is built by the function
    whose block is being filled, and it is reachable only through that block,
    and the block is confined to that function's activation by
    `_check_frame_escapes`, so the region outlives every read of the slot.  The
    unsafe neighbour is a container that came back from a CALLEE
    (`construction_dead_blob_refusal` refuses exactly that), because that one
    is bump-allocated in the callee's scratch and the callee has returned by
    the time the store happens.  So the three doors are: a method's write
    (refused, premise B1), `__init__`'s write (does not run, premise B2), and
    a construction argument (a literal is confined with the block; a callee's
    container is refused by name).

    A FOURTH reader arrived with the `__init__` inline, and it changed the
    first sentence rather than adding one: a construction with ARGUMENTS does
    run a constructor now, so "safe only because S() does not run __init__" is
    true of the zero-argument construction and false of the other.  The
    sentence therefore names both reasons, and they are the same reason twice —
    a container a constructor builds is confined to the function that built it,
    and a constructor that never runs cannot build one at all.  Naming one of
    them would send the reader after a premise that is not what is holding.
    """
    receivers = struct_receivers(struct_def)
    found: list = []
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            containers: set = set()
            _container_binding_names(getattr(m, "body", None), receivers,
                                    containers)
            _container_write(getattr(m, "body", None), receivers, found,
                             containers)
    parts = []
    if found:
        field, spelling = found[0]
        parts.append(
            f"{struct_def.name}.__init__ assigns {spelling} to self.{field}, "
            f"which is a blob in the constructing function's scratch rather than "
            f"a word; that is safe for one of two reasons and which one applies "
            f"is decided per construction site — {FRAME_FIELD_BLOB_PREMISE_B2}, "
            f"so a fresh {struct_def.name} reads as zero where the language's "
            f"constructor would have put that container, or the body is inlined "
            f"at the construction site, where the container it builds belongs to "
            f"the block being filled and cannot outlive it")
    literal = _construction_literal_into_field(struct_def)
    if literal:
        field, arg = literal
        parts.append(
            f"{struct_def.name} can also be built with a container in "
            f"self.{field} — {_construction_arg_spelling(arg)} at a "
            f"construction site — and that one is safe for a different reason: "
            f"a container LITERAL is built by the function whose block is being "
            f"filled, it is reachable only through that block, and the block "
            f"cannot leave the function that made it, so the region outlives "
            f"every read of the slot. The unsafe neighbour is a container "
            f"returned by a CALLEE, whose region is bump-allocated in the "
            f"callee's scratch and reclaimed before the store — and that is "
            f"refused by name")
    return " ".join(parts)


def _construction_literal_into_field(struct_def):
    """`(field, argument)` when a construction site puts a container LITERAL in
    a field of this struct, or None.

    The evidence half of `frame_field_premise_note`'s second sentence, and it
    has to be a real walk rather than a guess in either direction: the note is
    printed next to a refusal, so a note that fires for a struct nothing builds
    that way would be sending the reader after a construct their file does not
    contain.

    The walk is over the struct's OWN methods and over every `S(...)` call in
    the same function that names it, which is the only place such a call can
    be: a construction is a call in some function's body, and a function that
    is not this struct's method is not part of `struct_methods`.  A call
    anywhere else in the unit is found by the caller that has the unit's
    statement list; what is here is the part the struct alone can answer.
    """
    for m in struct_methods(struct_def):
        for node in iter_nodes(getattr(m, "body", None)):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr) \
                    or node.func.name != struct_def.name:
                continue
            slots = struct_frame_slots(struct_def)
            for arg, field in zip(node.args or [], slots):
                if isinstance(arg, (F.ListExpr, F.DictExpr, F.TupleExpr)):
                    return (field, arg)
    return None


def frame_field_premise_refusal(struct_def) -> str:
    """The message for a struct whose blob-in-a-field premise does not hold."""
    ok, which, detail = frame_field_premise(struct_def)
    if ok:
        return ""
    note = frame_field_premise_note(struct_def)
    return (
        f"{struct_def.name} breaks the premise that makes a frame field safe "
        f"to reach through ({which}): {detail} — and `self.<field>.append(x)` "
        f"in a method would then append into reclaimed stack, which is a "
        f"number the source never wrote rather than a failure. "
        + (f"({note}) " if note else "")
        + f"FORMAL_wide_receiver_by_reference.md (deleted; fixed) records the premise and "
        f"which decisions it currently rests on; the value-method work is what "
        f"has to keep it true")


def framed_struct_names(structs) -> dict:
    """`{name: struct}` for every struct whose receiver is a frame pointer.

    The set the build pass hands the two backends, read out of the SHARED
    model rather than recomputed per backend, so that the pass that lifts a
    method and the pass that emits its field accesses cannot disagree about how
    wide the receiver is."""
    return {st.name: st for st in structs if struct_is_framed(st)}


def one_field_struct_names(structs) -> dict:
    """`{name: that ONE FIELD's NAME}` for every struct that is exactly ONE field.

    The third predicate of the partition `framed_struct_names` and the build's
    `wide` table already spell as module-level tables, and the reason this one
    exists is the same: `struct_is_one_field` is `struct_fits_one_word` plus
    `struct_field_count`, and each of those derives the struct's whole field set
    by walking **every method body of that struct twice**. So one ask is a
    whole-struct walk, and a per-FUNCTION asker pays it once per function per
    struct — 1 031 of them on `myinterpreter.py` from `_prepare_functions`'s
    loop alone, which is 2.9 s of that file's remaining 3.8 s.

    **The VALUE is the field NAME and not the struct, and that is what makes it
    the ONE derivation of the partition rather than one of two.** A one-field
    struct's identity on this path is its field: the receiver IS the field, so
    `self.<name>` and `self` are the same word, and every reader that wants to
    know "which struct is this" wants the name anyway. The last per-function
    asker of the underlying walk was `formal/build.py::_sole_field_name`, which
    asked `struct_sole_field_name` — a SECOND derivation of the same field set,
    asked once per function, because the partition's name was published and the
    field's name was not. Publishing the field's name here retires that reader
    instead of adding a second table beside this one, which is the shape two
    tables over one partition invites: they cannot disagree about WHICH structs
    have one field, because there is only one table.

    **Membership and `struct_is_one_field` are the same question, decided by
    identity rather than by agreement**: `struct_is_one_field` is
    `struct_fits_one_word(st) and struct_field_count(st) == 1`, and
    `struct_fits_one_word` is `struct_field_count(st) <= 1` with no dependency
    on `wide_receiver_by_reference()`, so the conjunction is
    `struct_field_count(st) == 1` — which is exactly what makes
    `struct_sole_field_name(st)` non-`None`. So this table's KEYS are
    `struct_is_one_field`'s set by construction, and
    `test_formal_bracketed_method_field_set.py`'s `module table` group asserts
    the two agree struct for struct anyway, because an identity is worth a test.

    **Sound by the measurement the framed table's threading was sound by**, not
    by an invalidation argument: `formal/model.py`'s `read_before_store`
    derivation and the 2026-10-03 build-cost measurement's §3.1 (doc in git history) walked
    146 779 asks of the four predicates over 7 788 (question, struct) pairs
    across 14 files and NOT ONE pair changed its answer between two asks inside
    one `_prepare_functions` call — `struct_is_one_field` was one of the four.

    And it is not a cache: nothing is remembered across a mutation, the way
    `framed_struct_names` is not one either. A caller with no module context
    keeps asking `struct_is_one_field`, which is the same answer at the cost of
    one walk, so a test reading one function's answer is unaffected.
    """
    out = {}
    for st in structs:
        field = struct_sole_field_name(st)
        if field is not None:
            out[st.name] = field
    return out


def one_field_answer(struct_def, one_field=None) -> bool:
    """`struct_is_one_field(struct_def)`, read off `one_field_struct_names`'
    table when the caller has one.

    The threaded form, and a FUNCTION rather than a `name in table` at each of
    the seven call sites because the table is OPTIONAL: a caller with no module
    context — a test, a tool reading one function's answer, any of the model
    functions `formal/build.py` calls before it has a module table — keeps
    asking `struct_is_one_field`, which is the same answer at the cost of one
    whole-struct walk rather than none.

    `None` in, the predicate out, INCLUDING for `struct_def is None`, which the
    predicate answers False and a `getattr(struct_def, "name", None)` membership
    test also answers False. The two paths must not differ on the shape that
    reaches both, or "the threaded table changed the answer" would be a question
    about which path ran rather than about the struct.
    """
    if one_field is None:
        return struct_is_one_field(struct_def)
    return getattr(struct_def, "name", None) in one_field


def sole_field_answer(struct_def, one_field=None):
    """`struct_sole_field_name(struct_def)`, read off `one_field_struct_names`'
    table when the caller has one.

    The companion of `one_field_answer`, and it is a FUNCTION for the same
    reason that one is: the table is OPTIONAL, so a caller with no module
    context keeps asking `struct_sole_field_name`, which is the same answer at
    the cost of one whole-struct walk rather than none.

    **The table can only answer for a struct of the module it was derived from**,
    which is the same constraint `one_field_answer` carries and the reason a
    `.get` rather than a `[...]`: a struct from another module has a name this
    table may not carry, and the honest answer for it is the predicate's. Every
    caller in `formal/build.py` reaches a struct it has already established is
    this module's — `st.name in structs_by_name`, or a struct
    `field_type_one_word_struct` resolved out of `structs_by_name` — so the
    fallback is not reached, and it is a `.get` rather than an assertion because
    an assertion here would turn "a caller threaded a table from another unit"
    into a crash on a shape the predicate answers.

    `None` in, `None` out for `struct_def is None`: `struct_sole_field_name`
    raises on it (it reads `struct_field_names(struct_def)`), and the callers
    that can be handed one guard before asking, so this path is the forgiving
    one — recorded here because "the table path is more forgiving than the
    predicate path" is a difference a reader has to be told about.
    """
    if one_field is None:
        return struct_sole_field_name(struct_def)
    return one_field.get(getattr(struct_def, "name", None))


# The largest slot offset `LDR Xt, [Xn, #imm]` / `MOV Xt, [Xn+imm]` can name
# without computing the address: the arm64 unsigned-offset form's imm12 is 12
# bits of EIGHT-BYTE units, so slot 4095 is the last one addressable directly.
# A struct wider than this is refused by name rather than given a second
# addressing mode, because a second addressing mode is a second thing to get
# right and this path's whole value is that there is one.
MAX_FRAME_SLOT = 4095


def struct_frame_fits_encoder(struct_def) -> bool:
    """Whether every one of this struct's slots is directly addressable."""
    return struct_field_count(struct_def) <= MAX_FRAME_SLOT + 1


# Per node CLASS, not per node: both caches below are keyed by `type(node)`
# and are sound without invalidation because a dataclass's field set is
# fixed at class-creation time (see each function's docstring).
_NODE_FIELDS: dict = {}
_NODE_SUBTREE_FIELDS: dict = {}


def _node_field_names(node) -> tuple:
    """`(all field names)` of a node's dataclass, or None if it is not one.

    Per CLASS, once, and the cache is sound with no invalidation logic because a
    dataclass's field set is fixed when the class is created: `__dataclass_fields__`
    is a class attribute, so every instance of a node type has the same one, and
    a type that is not a dataclass at all has none (that is the `None`, and it is
    why `None` and `()` are different answers — a dataclass with no fields must
    still be YIELDED by `iter_nodes`, which is what walks on it).

    The two walkers that use this, `iter_nodes` and `_self_field_names`, are the
    hottest loops in a `build --formal` over a large file: they re-derived this
    list for every node visit and, in `_self_field_names`'s case, re-tested every
    field name against `("line", "col")` to drop the two that carry no subtree.
    Measured on `gimple_codegen.py` (arm64): the descent was 87% of the build's
    samples before this and 71% after, with the traversal order and the node
    sequence byte-for-byte the same (the filter is by NAME, which is what makes
    the `line`/`col` exclusion a property of the class rather than of the
    instance)."""
    cls = type(node)
    names = _NODE_FIELDS.get(cls, False)
    if names is False:
        fields = getattr(cls, "__dataclass_fields__", None)
        names = None if fields is None else tuple(fields)
        _NODE_FIELDS[cls] = names
    return names


def _node_subtree_fields(node) -> tuple:
    """`_node_field_names`, less the two that hold no subtree.

    `("line", "col")` are a source position, so no walker that is looking for
    statements has anything to descend into; filtering them once per class is
    what lets `_self_field_names` drop them without a membership test per field
    per node."""
    cls = type(node)
    names = _NODE_SUBTREE_FIELDS.get(cls, False)
    if names is False:
        all_names = _node_field_names(node)
        names = None if all_names is None else tuple(
            f for f in all_names if f not in ("line", "col"))
        _NODE_SUBTREE_FIELDS[cls] = names
    return names


def iter_nodes(node, skip=None):
    """Every dataclass node in a statement tree, parents before children.

    Shared because the frame layout (`struct_constructor_sites`), the
    frame-holder analysis (`formal/build.py`) and the constant-read census all
    have to walk the SAME tree the same way; three private copies of this loop
    are three chances for one of them to see a node the others do not, and a
    node one of them missed is a frame nobody reserved.

    **`skip` is `(kind, field)` pairs NOT descended into**, and it defaults to
    None — i.e. every field is descended, which is what every caller that
    existed before 2026-10-05 got and still gets.  It exists for the one
    question this walk cannot answer on its own: whether a binding made inside
    a NESTED `def` is a binding of the enclosing function's name.
    `formal/build.py`'s `_SKIP_DESCEND_FIELDS` is the set its own statement
    rewrite already declines to cross for the same reason — a `with` inside a
    nested `def` is rewritten when THAT function is prepared, not when the
    enclosing one is — and passing the set in rather than hard-coding it here
    keeps one list of "these are separate scopes" in the tree instead of two
    that can come apart.

    A closure capture is the case this does NOT decide, and it is deliberate: a
    name the enclosing function reads because a nested `def` bound it is a
    CAPTURE, and what a capture costs is `_flatten_closures`' question, not this
    walk's.  A caller that must not see another scope's bindings asks with
    `skip`; a caller that wants the whole subtree says nothing.
    """
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from iter_nodes(x, skip)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    yield node
    kind = type(node).__name__
    for name in _node_field_names(node):
        if skip is not None and (kind, name) in skip:
            continue
        yield from iter_nodes(getattr(node, name), skip)


def iter_nodes_with_parent(node, parent=None):
    """`iter_nodes`, with each node's PARENT beside it.

    `iter_nodes` hands the visitor a node and no parent, so a visitor that has
    to know a node's POSITION — is this `MemberExpr` the callee of a call, or a
    value read? — cannot answer, and has to over-approximate.  That is fine for
    most of its callers and not fine for `formal/build.py`'s
    `check_value_position_method_reads`, whose docstring called the
    over-approximation harmless on the grounds that "a call cannot store into
    the name either": true of the NAME, but the question the check asks is
    whether `recv.name` is a FIELD READ, and in callee position there is no
    read at all.  `self._data.clear()` on a one-field `Wrap` becomes
    `self.clear()` when the one-word rewrite collapses `_data` into the
    receiver, and `clear` is one of `Wrap`'s own METHODS, so the check refused a
    method call as though the source had read a field.

    One walk and not a second traversal of the tree, for the reason `iter_nodes`
    exists at all: three private copies of this loop are three chances for one
    of them to see a node the others do not.

    `parent` is the node the yielded node was reached FROM, and a list or tuple
    is TRANSPARENT: the elements of `IfStmt.elifs` — which is a list of TUPLES,
    the one place the tree is not a list — are yielded with the `IfStmt` as
    their parent, not the tuple.
    """
    if isinstance(node, (list, tuple)):
        for x in node:
            yield from iter_nodes_with_parent(x, parent)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    yield node, parent
    for name in _node_field_names(node):
        yield from iter_nodes_with_parent(getattr(node, name), node)


def is_call_callee(node, parent) -> bool:
    """Is `node` the CALLEE of a call — `parent.func is node`?

    The one reader of the parent `iter_nodes_with_parent` supplies, because
    "callee position" is a spelling (`CallExpr.func`) and a second spelling of it
    is a second answer to the same question.
    """
    return (isinstance(parent, F.CallExpr) and parent.func is node)


# The tree shapes a walk has to know about, and the reason they are NAMED here
# rather than spelled out in each walk: **`IfStmt.elifs` is a list of TUPLES**,
# `(condition, body)`, which is the only place in the tree where a container is
# not a `list`, and it is invisible from the node's field list — a field is a
# field whether its value is a list or a tuple.
#
# A walk that recurses on `isinstance(node, list)` therefore descends every
# `if` body and every `else` and stops dead at the first `elif`, while
# `iter_nodes` — which tests `(list, tuple)` — walks all of them. Two walks over
# one tree that disagree about a third of the conditionals is not a small gap,
# because the readers and the rewriters are exactly the pair that disagrees: a
# rewrite that misses an `elif` leaves the source construct standing where a LATE
# check reads it and reports it as something it is not.
#
# Measured 2026-10-02, arm64 and x86-64 identically: a method call inside an
# `elif` arm is not lifted (`formal/build.py`'s `_rewrite_method_calls`), so
# `struct/testing/prop/random.mojo`'s `Rng.rand_scalar` reached
# `check_value_position_method_reads` with its `self._next(diff)` intact and the
# program was refused with
#
#     self._next is not a field of Rng — _next is one of its METHODS … Call it
#     (`self._next(...)`), which is a receiver and a call and lowers
#
# about a call that HAS its parentheses and was in an `elif`. Removing the
# `elif` (an `if` with the same body) builds and computes the right answer, so
# the arm and not the construct is the whole of it.


def rewrite_tree(node, visit):
    """`node` with `visit` applied to every node, replacements put back.

    The mutating sibling of `iter_nodes`, for a rewrite: `visit(node)` is called
    on each node and its return value decides what happens next.

      * `None` — handled, do NOT descend. This is the arm a rewrite takes when
        it has consumed the node (a lifted call's arguments are not part of the
        construct any more), and it is why this is not just
        `iter_nodes` plus a `setattr`: descending where the previous version did
        not is a BEHAVIOUR change, and a rewrite pass that starts refusing
        programs it used to build is not a refactor.
      * the node ITSELF — keep it, and descend into its children. The common
        case for a walk whose work is in place (this is what every current caller
        returns for a node they had nothing to do with).
      * any OTHER value — the replacement to put in the parent's slot, and NOT
        descended.

    The last clause is the one that had to be measured rather than assumed, and
    the reason is the sentence the `None` arm already argues: descending where the
    previous version did not is a BEHAVIOUR change. A visit that hands back a
    DIFFERENT node has already decided what that node is, and the node it was
    built from is usually the very construct it consumed — `c.bump(4)` as a
    statement of its own becomes `c = Cell_bump(c, 4)`, and the call inside that
    new store is the one the rewrite exists to place. Descending offered the
    replacement to the same rewrite that had just produced it, and that pass's
    own value-position refusal fired on the store it had just written: every
    one-field mutator call became "it is called here as a VALUE rather than as a
    statement of its own" (`_apply_receiver_writeback`). A caller that wants the
    walk to continue into a node it built mutates that node in place and hands
    the NODE back; a caller that has consumed the construct hands back `None`.

    Nothing that existed before this clause returned a replacement, so no walk
    that was already on this function changes what it reaches — checked by
    reading both callers (`_rewrite_method_calls`,
    `_rewrite_one_word_field_method_calls`), which return `None` or the node.

    Descends into every dataclass field AND through `list` and `tuple`
    containers, so a caller cannot forget the `elifs` shape — that is the entire
    reason this function exists rather than each rewrite spelling its own
    recursion.
    """
    if isinstance(node, (list, tuple)):
        rebuilt = [rewrite_tree(x, visit) for x in node]
        if isinstance(node, tuple):
            return tuple(rebuilt)
        node[:] = rebuilt
        return node
    if not hasattr(node, "__dataclass_fields__"):
        return node
    replaced = visit(node)
    if replaced is None:
        return node
    if replaced is node:
        for name in node.__dataclass_fields__:
            setattr(node, name, rewrite_tree(getattr(node, name), visit))
        return node
    return replaced


def struct_block_children(struct_def, decls: dict, base: int = 0,
                          depth=None) -> list:
    """`[(field, slot, child_struct, offset, parent_offset)]` — the nested frames
    in this struct's BLOCK and where each one sits, to EVERY depth the model
    places.

    The offset arithmetic `struct_frame_block_bytes` performs, made a function
    rather than an inline loop, because two readers need the answer and the
    bytes reserved have to be the bytes addressed: `struct_constructor_sites`
    uses it to lay a site out, and the emitters use it to bring the frames up.
    Written twice, one of them would place a nested frame at an offset the other
    had reserved a different one for, and the first field read of it would be a
    read of whatever else is there.

    `base` is added to every offset, so `base=0` answers "relative to this
    struct's own block" — which is what a caller that hands the block over
    wants, since the block it is building into is not at a compile-time offset
    in the callee's frame at all. The FIFTH element is the offset of the block
    that DECLARES the field, measured the same way, and it is the one that makes
    the store side of a nested frame correct at a second level: the address of a
    nested frame lives in its parent's slot array and nowhere else.

    The recursion's depth bookkeeping is `struct_frame_block_bytes`'s exactly:
    children come from `struct_nested_frame_fields(st, decls, depth)` and their
    own sizes from `struct_frame_block_bytes(child, decls, depth - 1)`.  Two
    functions walking one layout with two different depth rules is how a block
    ends up half its size.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    out = []
    for fname, slot, child, child_off in struct_block_direct_children(
            struct_def, decls, base, depth):
        out.append((fname, slot, child, child_off))
        out.extend(struct_block_children(child, decls, child_off, depth - 1))
    return out


def struct_block_direct_children(struct_def, decls: dict, base: int = 0,
                                 depth=None) -> list:
    """`[(field, slot, child, offset)]` — this struct's OWN nested frames.

    The same rows `struct_block_children` flattens, one level at a time, and it
    is its own function because that is the only shape a RECURSIVE walk can
    consume: the parent of each row is the struct the row was asked about, so a
    caller that stores `child`'s address into `slot` has the parent's offset in
    hand. A flat list has thrown that away, which is why the two placement loops
    in each backend used to disagree about where a depth-2 frame's address goes
    — and then crashed before either could be observed, because the row they were
    unpacking came from the three-value function rather than this four.

    `struct_block_children` is written in terms of this one, so the offset
    arithmetic exists once: `struct_frame_block_bytes` decides the sizes and this
    decides where each frame starts, which is the property
    `struct_frame_block_layout`'s docstring is about.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    out = []
    inner = base + struct_frame_bytes(struct_def)
    for fname, slot, child in struct_nested_frame_fields(struct_def, decls,
                                                          depth):
        out.append((fname, slot, child, inner))
        inner += struct_frame_block_bytes(child, decls, depth - 1)
    return out


def one_word_nested_frame_structs(decls: dict) -> dict:
    """`{struct name: the struct whose FRAME its sole field holds}`.

    The one-field structs of this module whose construction site has to reserve
    somebody else's bytes, and the reader `struct_constructor_sites` walks with.
    It is a table rather than a per-call question because the walk asks it once
    per call SITE and the answer is a property of the struct: two calls per
    question would be two chances for the two to disagree about which structs
    hold a frame, and that disagreement is a SIGSEGV rather than a message.

    Keyed by NAME, like `framed_struct_names`, because the constructor site is
    recognised from the callee spelling (`Box1()`) and the struct table is what
    the emitter holds.
    """
    out = {}
    for name, st in (decls or {}).items():
        nested = one_word_sole_field_frame(st, decls)
        if nested is not None:
            out[name] = nested
    return out


def struct_construction_yields_frame_address(struct_def, decls: dict) -> bool:
    """Whether constructing this struct puts a FRAME ADDRESS in the name.

    Two shapes, and the second is the one this function exists for:

      * a struct with a frame of its own — the construction reserves a block and
        the value IS that block's address (`struct_constructor_sites`);
      * **a ONE-FIELD struct whose sole field holds a placed nested frame** —
        there is no object, so there are no slots of its own to reserve and the
        value the caller receives is the NESTED frame's address.
        `struct_constructor_site_bytes` reserves the nested block alone and says
        why in its own words ("that struct's own 8 bytes are not reserved,
        because there is no object: the VALUE is the nested frame's address"),
        and both backends' `_emit_fresh_one_word` bring that frame up and hand
        back its address.

    It is asked by `formal/build.py::_value_may_be_a_frame`, which is the ONE
    recogniser in that file for "can this value put a frame in a name", and the
    second shape used to be missing from it: `struct_is_framed` is False for
    every one-field struct, so `var b = Box()` was not a frame value and the
    checks that ask the question refused the program —
    `check_one_word_frame_receivers` with "nothing in this function has put a
    frame there: `b` was built by `Box()`, whose construction fills the WORD
    rather than the frame that word will hold" — about a construction that has
    filled the frame since `4af77b16`. Two rows of `test_formal_run.py` were red
    on the tree for it (`one_word_holder_reads_the_frame_its_constructor_brought_
    up` and `two_one_word_constructions_get_two_different_frames`).

    Both shapes read `struct_is_framed` / `one_word_sole_field_frame` rather than
    a second opinion about either, because a disagreement here is a load at
    address 0 rather than a wrong message.
    """
    if struct_def is None:
        return False
    return (struct_is_framed(struct_def)
            or one_word_sole_field_frame(struct_def, decls or {}) is not None)


def nested_frame_constructor_stores(struct_def, decls: dict, candidates=None,
                                    rets=None) -> tuple:
    """`(stores, refusal)` — what a frame bring-up must WRITE for `struct_def`.

    **The half of the bring-up that is a CONSTRUCTION rather than a
    default-initialization.** A construction brings a nested frame up in two
    different places and they were
    not the same code: a construction of the struct ITSELF runs its
    `__init__` (`struct_construction_plan` → `CONSTRUCTION_INIT`, one store per
    field at the fresh block), while a construction that happens INSIDE another's
    frame goes through the emitters' own placement walk
    (`_emit_frame_nested` → `_emit_frame_defaults` →
    `_emit_frame_nested_addresses`) and that wrote each field's CLASS-LEVEL
    DEFAULT and nothing else. Measured, both architectures:

        struct Opt:  var v: Int;  var has: Int
                     def __init__(out self): self.v = 41; self.has = 1
        struct Box:  var inner: Opt
        var b = Box();  b.inner.v     # 0 here, 41 in CPython

    and the disagreement was invisible in both directions — `var o = Opt()`
    answered 41 from the same declarations in the same file.

    **It is `struct_construction_plan` asked with a synthesized zero-argument
    call, and not a second walk of the constructor body.** That function is the
    ONE reader of "which fields does this `__init__` store, and what goes in
    each": it selects the overload, substitutes a bare parameter name with the
    caller's expression or the signature's default, drops the store a nested
    placement already made redundant, and refuses the statements it cannot
    lower — each with its own message. A second walk here would be a second
    opinion about which argument lands in which slot, and it is asked about a
    construction with NO arguments, which is the case the zero-argument branch
    of `struct_construction_plan` is about.

    `([], None)` for a struct that declares no `__init__`, which is the ordinary
    case and the one that must keep the bring-up exactly as it was. A REFUSAL is
    returned rather than swallowed for the shape that cannot be inlined: a
    bring-up that silently dropped the constructor's stores is the silent wrong
    answer this fixes, so a body this path cannot lower has to stop the build
    with the sentence that says which statement is responsible.

    **A constructor that REQUIRES parameters keeps the defaults, and that is the
    language's rule rather than a retreat.** A frame bring-up has no arguments to
    supply — there is no call — so an `__init__` with a required parameter cannot
    be run, and what the field holds is the default-initialized object. Measured
    against the alternative, which was to ask `struct_construction_plan` with the
    synthesized zero-argument call and take its arity refusal: that turned
    `struct Inner: var inner2: Inner2; var z: Int` /
    `def __init__(self, i: Inner2, b: Int)` inside a `struct Outer: var inner:
    Inner`, brought up by `var o = Outer()`, into a BUILD FAILURE — and the
    program overwrites the whole field on the next line
    (`o.inner = Inner(Inner2(5), 6)`), so the frame it brought up was never
    read. That row is `byref_three_level_chain_with_the_type_assigned_in_init` in
    `test_formal_run.py` and it must keep passing: refusing the bring-up would
    refuse a program whose object is correct.

    **The residual, stated because it is a divergence and not a fix**: a program
    that brings up such a frame and READS it before assigning sees the defaults
    where Mojo's own default-initialization also puts them, so this is the
    language's own answer and not a hole — but it is a hole in the sense that no
    test here pins the READ, and `construction_bringup_is_complete`'s `why` is
    where a reader who cares will find the shape named.
    """
    if struct_def is None:
        return ([], None)
    shapes = struct_init_shapes(struct_def)
    if not shapes:
        return ([], None)
    name = struct_def.name
    # The zero-argument overload selection, asked DIRECTLY rather than through
    # `struct_construction_plan` with a synthesized call — because that function
    # refuses when no overload takes no required parameter, and here the answer
    # to that is "there is nothing to run", not "stop the build".
    shape, why = init_overload_for_arity(shapes, 0)
    if why is not None:
        return ([], None)
    plan, refusal = struct_construction_plan(
        struct_def,
        F.CallExpr(func=F.IdentExpr(name=name), args=[], kwargs=[]),
        decls or {}, candidates or {}, rets)
    if refusal is not None:
        return (None, f"bringing up a nested {name} runs its constructor, and "
                      f"that constructor is not lowered: {refusal}")
    if plan[0] == CONSTRUCTION_INIT:
        return (list(plan[1]), None)
    # `CONSTRUCTION_DEFAULT` for a declared `__init__` means the plan found one
    # and decided the call stores nothing — a body of only `pass`, or only
    # docstrings. `POSITIONAL` and `COPY` cannot arise from a zero-argument call
    # against a struct that declares a constructor, and falling through to the
    # default answer rather than raising keeps that a future shape's problem
    # rather than this bring-up's.
    return ([], None)


def construction_bringup_is_complete(struct_def, decls: dict, depth=None,
                                      _seen=None) -> tuple:
    """`(ok, why)` — can this construction's frame be LIFTED over?

    The question is about the METHOD-CALL path rather than about the
    construction itself: `formal/build.py::_call_receiver_verdict`'s
    `construction_frame` verdict refuses a method call on a construction whose
    frame a lift would not fully write, and this is the reader it asks.

    **It used to ask "does the bring-up run every `__init__` in the subtree",
    and that was the wrong question — the bring-up runs them now.**
    `nested_frame_constructor_stores` is what a bring-up emits, so a struct whose
    `__init__` this path CAN inline no longer leaves the frame half-written:

        struct Opt:  var v: Int;  var has: Int
                     def __init__(out self): self.v = 41; self.has = 1
        struct Box:  var inner: Opt
        Box().get()      # 41, on both architectures (was 0)

    Two shapes still make a lift unsound, and this is the reader for both:

      * **a constructor that REQUIRES parameters.** A bring-up is not a call, so
        it has no arguments to fill them with and the frame stays at its
        defaults — which is the language's own answer for a field nothing
        assigns, but it is not what a construction `Box(Opt(5))` would leave, so
        a lift that claimed the frame was fully written would be claiming a
        program the source does not contain.
      * **a constructor body this path does not lower.** `nested_frame_
        constructor_stores` returns a refusal for it rather than dropping the
        stores, so the build stops with the offending statement named — and a
        lift must not paper over that by answering from the defaults.

    So the answer is now "no struct in the subtree declares a constructor this
    path cannot run at a bring-up", recursively, and `why` names the struct that
    broke it so the refusal sends a reader to the declaration rather than to the
    shape. `nested_frame_constructor_stores` is asked directly rather than a
    structural rule being restated here, so the two cannot disagree about what a
    bring-up writes.

    `depth` is the recursion bound and it is `MAX_NESTED_FRAME_DEPTH` for the
    same reason `struct_nested_frame_fields` bounds itself: a chain longer than
    the layout supports is a refusal rather than a truncated answer, and
    truncating here would report a subtree the bring-up does not write.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    if depth <= 0 or struct_def is None:
        return (False, "nested frame deeper than the layout places")
    # The visited set is the PATH, not everything seen: a struct reachable by
    # two different fields is two branches of the same tree and each is walked,
    # while a struct that reaches ITSELF is a cycle and is reported. A plain
    # "already seen" set reported the second visit of a sibling as a cycle, and
    # `struct Box: var inner: Opt` reaches `Opt` twice — once through
    # `struct_nested_frame_fields` and once through
    # `one_word_sole_field_frame` — so it refused the shape it exists for.
    path = set() if _seen is None else _seen
    key = getattr(struct_def, "name", None) or id(struct_def)
    if key in path:
        return (False, f"{key} nests inside itself")
    path.add(key)
    try:
        # `nested_frame_constructor_stores` and not a structural rule restated
        # here: it is the reader that decides what a bring-up writes, so asking
        # it is what keeps "can this be lifted" and "what does the bring-up do"
        # from being two answers to one question. `(stores, None)` — which
        # includes the `([], None)` a struct with no constructor gets, and the
        # one a constructor that REQUIRES parameters gets — is a frame this path
        # can account for.
        stores, refusal = nested_frame_constructor_stores(struct_def, decls)
        if refusal is not None:
            return (False, refusal)
        shapes = struct_init_shapes(struct_def)
        if shapes:
            # A constructor that is DECLARED and produces nothing at a bring-up
            # is the one shape this predicate still refuses, and it is not the
            # shape it used to refuse. `nested_frame_constructor_stores` returns
            # `([], None)` for it, and there are two ways to get there and they
            # are opposite answers:
            #
            #   * a constructor whose body this path cannot lower, or whose
            #     parameters are REQUIRED. A bring-up is not a call, so it has
            #     no arguments to fill them with, and the frame keeps its
            #     defaults — which is the language's answer for a field nothing
            #     assigns, but is NOT what `Box(Opt(5))` would leave, so a LIFT
            #     that claimed the frame was written would be claiming a
            #     program the source does not contain.
            #   * a constructor whose body genuinely stores nothing (`pass`, or
            #     only docstrings). That frame IS fully written and lifting over
            #     it is fine.
            #
            # The first is what this refuses and the second is not, so the
            # distinction has to be made rather than inferred from an empty
            # store list — which is why `struct_init_shapes` is asked here and
            # the emptiness alone is not enough.
            shape, why = init_overload_for_arity(shapes, 0)
            key = getattr(struct_def, "name", None) or id(struct_def)
            if why is not None:
                return (False, f"{key} declares a constructor whose parameters "
                                f"a frame bring-up has no arguments for, so the "
                                f"frame it brings up holds the field DEFAULTS "
                                f"rather than what a call to that constructor "
                                f"would have stored")
            if not stores and any(m.name == "__init__" for m in
                                  struct_methods(struct_def)):
                return (False, f"{key} declares a constructor this path does "
                                f"not lower")
        for _fname, _slot, child in struct_nested_frame_fields(
                struct_def, decls, depth):
            ok, why = construction_bringup_is_complete(child, decls, depth - 1,
                                                       path)
            if not ok:
                return (False, why)
        nested = one_word_sole_field_frame(struct_def, decls or {})
        if nested is not None:
            ok, why = construction_bringup_is_complete(nested, decls,
                                                       depth - 1, path)
            if not ok:
                return (False, why)
    finally:
        path.discard(key)
    return (True, None)


def struct_constructor_site_bytes(struct_def, decls: dict) -> int:
    """Bytes ONE construction site of this struct reserves in the prologue.

    The size of a site is `struct_frame_block_bytes` for a struct with a frame
    of its own, and the NESTED block alone for a one-field struct whose sole
    field holds one — that struct's own 8 bytes are not reserved, because there
    is no object: the VALUE is the nested frame's address.

    It exists so that the two places that need the number ask ONE question. The
    emitters sum it to reserve the prologue's scratch, and `struct_constructor_
    sites` advances its layout cursor by it; a site that reserved one amount and
    was handed out another would put the second site's frame inside the first
    one's, and the symptom would be one struct's fields reading another's values
    — a wrong answer, on both architectures, with a green build.
    """
    nested = one_word_sole_field_frame(struct_def, decls or {})
    if nested is not None:
        return struct_frame_block_bytes(nested, decls)
    return struct_frame_block_bytes(struct_def, decls)


def struct_constructor_sites(fn, structs_by_name) -> dict:
    """`{id(call): (struct, offset, nested)}` — this function's receiver BLOCKS.

    A layout decision, so it lives in the shared model and both backends read
    the same answer: a frame is reserved in the function's PROLOGUE, so it has
    to exist before the body runs and cannot be handed out by a bump pointer
    that walks the body the way the list/dict blob cursor does.

    One BLOCK per call SITE, laid out in walk order. Per site rather than per
    call is what makes a constructor inside a loop safe: the loop reuses its
    site's block, exactly as a C local is reused, so a loop cannot grow the
    stack without bound. `offset` is the block's distance below the bottom of
    the function's ordinary frame — below `SP` on both machines, which is the
    placement `ProofLib.Frame.frameWrite_read_above_sp` needs and the reason a
    method's write to its receiver cannot reach the caller's window.

    `nested` is `[(field_name, slot, struct, offset)]`: the frames of this
    struct's typed-nested fields (`struct_nested_frame_fields`), each with its
    own absolute offset into the same scratch, immediately above the object's
    own frame.  This is the tuple's third element and it is additive: a struct
    with no typed-nested field has an empty list, so every existing unpack of
    two elements is still a struct with no nested frames — but the emitters
    read three, because the whole point of the declared-type check is that the
    nested frame is PLACED here rather than hoped for at the use site.

    **A ONE-FIELD STRUCT WHOSE SOLE FIELD HOLDS A FRAME IS IN THIS TABLE TOO,
    and its `nested` row is the whole of what its construction needs.** There is
    no object to lay out — the value IS the nested frame's address — so `offset`
    is the NESTED frame's offset, its row's `slot` is `None` (there is no slot
    array to store an address into; the word the caller receives is the address
    itself), and the cursor advances by `struct_constructor_site_bytes`, which
    is the nested block alone. Without this row the construction emitted
    `mov X0, #0` / `mov eax, 0` and every field read through it was a load from
    address 0 — a green build, a SIGSEGV on the first read, and no diagnostic
    (fixed 2026-10-03 in 4af77b16, where a one-field struct whose
        sole field holds a frame brings that frame up instead of a null
        word).

    A FLAT list cannot carry the parent of each row, which is why the emitters
    read `struct_block_direct_children` for placement and recurse on it rather
    than walking this one: the address of a frame two levels down has to go into
    the slot array of the block that DECLARES the field, and only a recursion
    knows which block that is.
    """
    one_word = one_word_nested_frame_structs(structs_by_name)
    framed = {name: st for name, st in framed_struct_names(
        list(structs_by_name.values())).items()
        if name not in one_word}
    if not framed and not one_word:
        return {}
    out, offset = {}, 0
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr):
            continue
        # A construction is a BARE `S(...)` or a DOTTED `mod.S(...)`, and both
        # reserve the same block: the object is laid out by whoever builds it,
        # and `mod.S(...)` builds it here. Reading only the bare spelling made
        # this table and the emitter disagree — the emitter emitted the
        # construction and this table had reserved nothing for it, which is the
        # "the frame layout and the body disagree" refusal, on a program with
        # nothing wrong with it.
        if isinstance(node.func, F.IdentExpr):
            name = node.func.name
        elif isinstance(node.func, F.MemberExpr) \
                and isinstance(node.func.member, str):
            name = node.func.member
        else:
            continue
        st = framed.get(name)
        if st is not None:
            nested, block = struct_frame_block_layout(st, structs_by_name)
            out[id(node)] = (st, offset, [(f, s, c, o + offset)
                                         for f, s, c, o in nested])
            offset += block
            continue
        nested_st = one_word.get(name)
        if nested_st is None:
            continue
        holder = structs_by_name[name]
        field = struct_sole_field_name(holder)
        out[id(node)] = (holder, offset,
                         [(field, None, nested_st, offset)])
        offset += struct_constructor_site_bytes(holder, structs_by_name)
    return out


def struct_frame_block_layout(struct_def, decls: dict, depth=None):
    """`(nested, total_bytes)` — one BLOCK's internal layout.

    `nested` is `[(field_name, slot, struct, offset_from_block_base,
    parent_offset_from_block_base)]`: the
    frames this struct's typed-nested fields get inside the SAME block, each
    with its own offset measured from the block's own base, in declaration
    order, immediately above the object's own slots.  `total_bytes` is the
    block's whole size, which is what a caller has to reserve for it.

    A reader of `struct_block_children` and not a second walk of the nested-field
    list, because three consumers of that list have to agree about it down to
    the last byte: the constructor sites turn the relative offsets into absolute
    ones by adding the site's base, the emitters use them to bring the frames up,
    and the returned-frame COPY uses them directly, because the destination block
    is reserved by `struct_returned_frame_sites` with the same rules and
    therefore has the same internal layout.  Two walks agree until the day one
    of them is edited, and a returned frame copied with a stale layout stores one
    struct's nested address in another struct's slot — which is the silent wrong
    number, not a crash.
    """
    return (struct_block_children(struct_def, decls, 0, depth),
            struct_frame_block_bytes(struct_def, decls, depth))
