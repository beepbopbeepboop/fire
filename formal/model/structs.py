from . import *

# ── A multi-field receiver, BY REFERENCE ───────────────────────────────
#
# A value on this path is one 64-bit word, and a struct of two fields has
# nothing to *be* as a value.  It can nevertheless be given a representation
# WITHOUT changing the value model at all, by lowering the receiver **by
# reference**: the receiver word is the ADDRESS of an out-of-line frame of
# 8-byte slots, `self.<field>` is a load from `mem[base + 8*k]`, and a field
# write is a store to the same place.  A pointer is one word, so nothing that
# was one word before becomes two — `MojoFunc`'s single parameter is already
# `self` and is already the address, so `_rewrite_method_calls` needs no change
# at all, and `Refine.Post` / `contract_sound` / `runProg` (already
# `UInt64 → UInt64`) are untouched.
#
# The full design, its cost, and the proof-side algebra (`ProofLib.Frame`,
# `ProofLib.MF`, `Refine.FrameOk_except`) were in
# `FORMAL_wide_receiver_by_reference.md` (deleted; fixed).  What is here is the part the
# two backends have to agree on, which is why it is in the shared model rather
# than in either of them: a width that the build pass and the codegen pass
# measured differently is a struct whose receiver is the wrong number of bytes
# in one of them, and neither would notice.
#
# The switch.  Off means the pre-by-reference behaviour exactly: a wide
# receiver is refused by name, and every struct of at most one field is
# unaffected either way (a one-word struct's receiver IS its field, which is a
# different representation and the cheaper one).  It exists so the switch can
# be turned off to attribute a regression, and so a reader can see that nothing
# below it changes a one-field program.
WIDE_RECEIVER_ENV = "MOJO_FORMAL_WIDE_RECEIVER"


def wide_receiver_by_reference() -> bool:
    """Whether a multi-field receiver is lowered as a pointer to a frame.

    ON by default.  The two settings differ ONLY for a struct with more than
    one derived field, and for such a struct the "off" setting is a refusal —
    so turning it on can only turn a refusal into a build, never change the
    meaning of a program that already built.  `MOJO_FORMAL_WIDE_RECEIVER=0`
    restores the refusal, which is what one does to attribute a regression to
    this change rather than to whatever else moved."""
    return os.environ.get(WIDE_RECEIVER_ENV, "1") not in ("0", "no", "false")


def struct_is_framed(struct_def) -> bool:
    """True when this struct's receiver is a POINTER to a frame of fields.

    The complement of `struct_fits_one_word` for every struct of more than one
    field, and `False` for the one-field ones whatever the switch says: a
    one-field struct's receiver is its field, so it needs no frame and there is
    no reason to spend a word of indirection on it."""
    return struct_field_count(struct_def) > 1 and wide_receiver_by_reference()


def struct_is_one_field(struct_def) -> bool:
    """True when this struct's whole state is the ONE field `self` names.

    `struct_fits_one_word` alone is not the question, because it is also true of
    a struct with NO fields, and "the receiver IS its field" has no field to be
    when there is none.  Spelled once because three decisions ask it — the
    local-constructor binding in `_one_word_field_map`, a method's own `self`,
    and a parameter's declared type — and they must not come apart: they all
    rewrite `x.<field>` to `x`, and a rewrite one of them makes and another does
    not is a program whose field and its value are two different words.

    It is deliberately not the complement of `struct_is_framed`: a struct of
    several fields under `WIDE_RECEIVER_BY_REFERENCE=0` is neither, and a
    caller asking which of the two representations its receiver gets is
    `struct_is_framed` with `wide_receiver_by_reference` read there."""
    return struct_fits_one_word(struct_def) and struct_field_count(struct_def) == 1


# The argument conventions that say "this method may change the object its
# receiver names", as `param_convs` actually spells them.
#
# **NOT the surface syntax, and the difference is load-bearing.** `fire_compiler.py`'s
# `_CONV_CANON` collapses the spellings onto one canonical string — `inout self`
# to `mut`, `borrowed self` to `read`, `var self` to `owned` — so `"inout"` never
# reaches `param_convs` and an entry for it can never match; it was here until
# 2026-10-03 and is a lie about the parser's vocabulary rather than a safety net.
#
# **`owned` is deliberately NOT in the list**, and the measurement that decided it
# is over this repository's and the stdlib's 690 `.py`/`.mojo` files: 17 methods
# of a ONE-FIELD struct store that struct's own field, and 13 of them declare
# `mut` — the convention that makes `receiver_writeback_name` hand the receiver
# back. Exactly one declares `var self`
# (`std/python/python_object.mojo`'s `PythonObject.steal_data`, whose file is a
# host-import this backend never answers), and three declare a plain `self`.
# Adding `owned` would therefore make ~195 READERS write-back candidates, and for
# a one-field struct the write-back IS the receiver — so every reader that
# already returns something would start failing `mutating_receiver_return_refusal`
# instead. Whether `var self` MAY change the receiver it names is a question
# about the language's argument model; this path has no representation for
# ownership transfer either way, so it refuses by name
# (`RECEIVER_CONVENTION_NAMES`) and says which word of source fixes it.
#
# Kept as a tuple because adding an entry is a decision about the language's
# conventions, not a detail of the walk below.
MUTATING_RECEIVER_CONVENTIONS = ("out", "mut")


def receiver_writeback_name(fn) -> object:
    """The receiver a method must hand BACK to its caller, or None.

    **`mut self` on a ONE-FIELD struct, and why the receiver has to come back
    at all.** A multi-field struct's receiver is the ADDRESS of a frame of
    8-byte slots, so `self.f = x` in the callee writes into storage the caller
    still owns and the write is visible with no convention and no help. A
    one-field struct's receiver IS its field: `_one_word_field_map` rewrites
    `self.f` to `self` and `c.f` to `c`, so the caller's local and the callee's
    parameter are the same word in two registers and a store to the callee's
    copy is a store the caller never reads back. Measured:
    `self._value = self._value + 4` inside `def bump(out self)` built on both
    architectures, ran, and printed the value the caller had — the new one is
    computed and dropped (`FORMAL_one_field_struct_mutating_method_is_a_no_op`).

    **HOW it comes back, and the change of 2026-10-03 is the whole of what this
    docstring used to be about.** It used to be the return register: the callee
    appended `return self` on every path and the caller stored that over the
    expression the receiver was read from, which is only expressible when the
    call is a STATEMENT (`formal/build.py`'s `_apply_receiver_writeback`). It is
    now MEMORY: the caller passes the ADDRESS of the receiver's own storage and
    the callee writes the value back through it on every exit. Three measured
    facts forced it, each on both architectures, and all three are the same
    defect — the write-back was dropped and the caller kept the old word:

      * `mutating_receiver_return_refusal`, i.e. `def pop(mut self) -> Int`. The
        return register was the receiver, so a method that both changed the
        receiver and returned a value had nowhere to put the value. That is the
        shape `std/collections/binary_heap.mojo`'s `pop` is, and refusing it
        preempts every emitter refusal in that file;
      * a mutator call in an ARGUMENT — `sink(c.bump(5))` — has no statement to
        store into, so the rewrite left it alone: the callee computed 15, `sink`
        printed 15, and `c` was still 10;
      * a mutator call whose CALLEE IS IN ANOTHER MODULE is not in the
        per-module table the rewrite is built from, so the store was never
        generated: `from cellmod import Cell; c.bump(5)` printed `c=10`.

    None for anything else, and the two exclusions are both deliberate:

      * a receiver that is NOT declared mutating. `def f(self): self.x = 1` is
        not a program on this path — a plain receiver cannot be assigned
        through — so there is nothing here to give back and guessing would
        invent a copy semantic the source did not ask for;
      * a struct that is not one field, whose receiver is an address and
        therefore already shared — which is why the new mechanism changes
        nothing for it and is invisible there.
    """
    convs = getattr(fn, "param_convs", None) or {}
    name = method_receiver_name(fn)
    if name is None:
        return None
    if (convs.get(name) or "") not in MUTATING_RECEIVER_CONVENTIONS:
        return None
    return name


# One entry of `one_field_mutating_methods`' table: the receiver the method
# hands back, and the two names the diagnostics need. A named tuple because the
# call site joins on the KEY and reads only the receiver, while a refusal has to
# name the construct — and re-deriving the owner from the key at refusal time
# would be a second lookup that can disagree with the first.
def one_field_dropped_receiver_stores(fn, owner, one_field=None):
    """Where `fn` stores a ONE-FIELD struct's own field and the store is DROPPED.

    A one-field struct's receiver IS its field — `struct_is_one_field` is what
    says so, and `_rewrite_self_fields` is what acts on it — so `self.f = v` in
    the callee writes the callee's own copy of one word and the caller's object
    keeps whatever it had. `receiver_writeback_name` is the mechanism that makes
    such a store reach the caller, and it needs the receiver declared `out` /
    `inout` / `mut`; with any other convention the method is never handed back
    and the store is computed and thrown away.

    Measured on both architectures, 2026-10-03 (found by `tools/formal_fuzz.py`):

        class C:
            def __init__(self): self.a = 2
            def bump(self):     self.a = 7
            def get(self):      return self.a

        c = C(); c.bump(); print(c.get())      # CPython 7, this path 2

    which builds, runs and exits 0. The TWO-FIELD spelling of the same program
    is right (`self.a` is a slot in a frame the caller owns), which is why the
    rule is asked about width and not about stores.

    `__init__` is deliberately not in the answer: a constructor is not a call. Its
    stores are INLINED into the construction site (`init_receiver_rewrite`), so
    they run in the frame the object is being built in — which is where CPython
    runs them, and the reason the same source is correct there.

    **`__post_init__` is not in the answer for the other reason, and its absence
    was a wrong refusal.** CPython calls that hook at the end of the generated
    `__init__`, and this path never calls it at all — `dataclass_transform`'s
    `post_init_refusal` says so and refuses the class for it — so a store inside
    one cannot reach the caller whichever convention the receiver declares. The
    rule used to report it anyway, and the dataclass refusal lost its pre-emption:
    `test_dataclasses_formal.py`'s `post_init_is_refused_with_its_reason` was
    reading a one-field receiver message for a hook the file is refused for
    before, and the diagnosis it got named the wrong construct.

    Returns `[(field, convention)]` — the field stored and the receiver's
    convention as the source spelled it, `None` for a plain `self` — or `[]` when
    the method is not at risk.
    """
    if owner is None or not one_field_answer(owner, one_field):
        return []
    recv = method_receiver_name(fn)
    receivers = struct_receivers(owner)
    if recv is None or recv not in receivers:
        return []
    conv = (getattr(fn, "param_convs", None) or {}).get(recv)
    if (conv or "") in MUTATING_RECEIVER_CONVENTIONS:
        return []                      # the write-back delivers the store
    if method_member_name(owner, fn) in ("__init__", "__post_init__"):
        # `__init__` is INLINED at the construction site, so its stores run
        # where CPython runs them; `__post_init__` is never called here at all.
        # Same exclusion, two different reasons, both about there being no CALL
        # for a write-back to travel along.
        return []
    field = sole_field_answer(owner, one_field)
    if field is None:
        return []
    out = []
    for node in iter_nodes(getattr(fn, "body", None) or []):
        target = getattr(node, "target", None) if isinstance(
            node, (F.AssignStmt, F.AugAssignStmt)) else None
        if not isinstance(target, F.MemberExpr) or target.member != field:
            continue
        base = getattr(target, "obj", None)
        if isinstance(base, F.IdentExpr) and base.name == recv:
            out.append((field, conv))
    return out


# A `var self` / `owned self` receiver is a SPELLING question this rule does not
# decide: the parser folds both to the `owned` convention, and `owned` is not in
# `MUTATING_RECEIVER_CONVENTIONS`. One corpus site is written that way
# (`std/python/python_object.mojo`'s `PythonObject.steal_data`), and whether it
# should join the list is a question about the language's argument conventions
# rather than about this path, so the refusal below NAMES it instead of guessing.
RECEIVER_CONVENTION_NAMES = {None: "`self`", "owned": "`var self`",
                             "read": "`borrowed self`", "ref": "`ref self`"}

from typing import NamedTuple


class ReceiverWriteback(NamedTuple):
    receiver: object
    owner: object
    member: object
    decl: object


ReceiverWriteback.__doc__ = (
    "`receiver` is the local whose OWN STORAGE is handed to the callee as "
    "argument 0 — the address, not the value; `owner`/`member` are the class "
    "and the method as the source spells them, for the two refusals; `decl` is "
    "the FunctionDef itself, which is how a call SITE learns whether the method "
    "declares a return type and so has a value to put in a value position "
    "(`mutating_receiver_value_refusal`).")


def one_field_mutating_methods(functions, method_owners: dict,
                              one_field=None) -> dict:
    """`{lifted method name: ReceiverWriteback}` for every one-field mutator.

    Keyed by the function's OWN name, which is the LIFTED `<Struct>_<member>`
    spelling `formal/build.py`'s `_struct_methods` gives it and the same one
    `_rewrite_method_calls` puts on the call site — so the call site joins on
    the name it already carries, with no second lookup and therefore no second
    answer to "is this call a receiver hand-off". A table the call site cannot
    join on is how those two drift apart.

    **`ReceiverWriteback.receiver` is a NAME, and it is also the ARGUMENT the
    address goes in.** `formal/build.py` turns each entry into a `_recv_ref_receiver`
    on the callee (its prologue reads the word out of the cell and every exit
    writes it back) and a `_recv_ref_sites` table on each caller (its argument 0
    is the address of that name's own storage). So the emitter needs no second
    lookup to answer "is argument 0 of this call a receiver, and whose".

    `method_owners` is `formal/build.py`'s `{lifted name: StructDef}`: a
    FunctionDef carries no back-pointer to the class body it was written in, so
    the owner is the one thing this cannot derive for itself, and `functions` is
    what carries the receiver's convention.

    `one_field` is `one_field_struct_names`' table, handed in by the caller that
    already derived it (`formal/build.py::_prepare_functions`), because this loop
    asks the predicate once per METHOD — 377 of them on `myinterpreter.py`, each
    one a whole-struct walk of bodies. `None` keeps the per-method ask, which is
    the same answer at the cost of the walk; see
    the 2026-10-03 build-cost measurement (doc in git history: §6 for the
    measurement, §3.1 for why reading the table is sound).
    """
    out = {}
    for fn in (functions or ()):
        st = (method_owners or {}).get(fn.name)
        if st is None or not one_field_answer(st, one_field):
            continue
        recv = receiver_writeback_name(fn)
        if recv is None:
            continue
        # The MEMBER name, read off the class body rather than sliced out of
        # the lifted name: `method_function_name` is what produced that name, so
        # asking it the other way round is the one spelling of "which method is
        # this" that cannot drift from the key — and it is `method_member_name`
        # rather than a second copy of that loop, because the one-field rebind
        # refusal needs the same two names for the same method.
        member = method_member_name(st, fn)
        out[fn.name] = ReceiverWriteback(recv, st.name, member, fn)
    return out


def dropped_receiver_store_refusal(owner: str, member: str, field: str,
                                   convention) -> str:
    """The diagnostic for a store a one-field struct's receiver cannot deliver.

    The backend's rule is that a construct with no representation on this path
    says so rather than computing the wrong answer, and this is that rule for the
    one-field receiver: the receiver IS the field, so the callee stores into its
    own copy of one word and the caller's object is unchanged — a program that
    builds, runs, exits 0 and prints the value the constructor put there. Both
    ways out are the language's own, and the message gives both because a reader
    who has only met the two-field spelling of this program does not know either:

    * declare the receiver `out` / `inout` / `mut`, which is what makes
      `receiver_writeback_name` hand it back so the call site stores the new word
      over the object; or
    * split the method into one that changes the receiver and returns nothing,
      and one that reads it and returns the value — which is what a constructor
      already is, and why `__init__` is not refused.
    """
    spelled = RECEIVER_CONVENTION_NAMES.get(convention, "this receiver")
    return (
        f"{owner}.{member}() stores `{field}`, the one field its receiver IS, "
        f"and {spelled} is not a receiver this path hands back, so the store "
        f"cannot reach "
        f"the caller: on this path a one-field struct's receiver is its single "
        f"word rather than an address, so the method would compute the new value "
        f"and drop it, and the object the caller holds would keep the old one. "
        f"Declare the receiver `out self` (or `inout self` / `mut self`) so it is "
        f"handed back, or split the method into one that changes the receiver "
        f"and returns nothing and one that reads it. (The rule is "
        f"`formal/model.py`'s `one_field_dropped_receiver_stores`; "
        f"`receiver_writeback_name` is the mechanism it is about.)")


def mutating_receiver_address_refusal(owner: str, member: str, spelled) -> str:
    """The diagnostic for a mutator call whose receiver has no ADDRESS.

    The write-back is a store through the receiver's own storage, so the caller
    must be able to produce that storage's address. A NAME this path can place
    (a local or a parameter, lowered to a stack slot exactly so it has one)
    can; a SUBSCRIPT cannot — a formal value is one word with no address the
    compiler took, and `items[0]` is a computed word rather than a place — and
    neither can a call result. Refused rather than guessed, because the guess is
    the defect this mechanism used to have wearing a different hat: passing the
    VALUE where the callee expects the address made the callee store through a
    number, and the caller's object kept the old word.
    """
    return (
        f"{owner}.{member}() is a one-field struct's mutating method, so the "
        f"value it computed has to be stored back through the receiver's own "
        f"storage, which means the caller has to hand it the ADDRESS of that "
        f"storage. {spelled} is not a place this path can take the address of: "
        f"a formal value is one 64-bit word and nothing here computed a "
        f"location for it. Bind it to a local first — `var it = {spelled}` "
        f"then `it.{member}(...)` — which is the same computation and one "
        f"store this path can lower. (`formal/model.py`'s "
        f"`receiver_writeback_name` is the rule.)")


def mutating_receiver_order_refusal(owner: str, member: str, spelled,
                                    reader: str) -> str:
    """The diagnostic for a mutator call and a read of the SAME receiver in one
    argument list.

    `f(c.pop(), c.field)` asks two questions whose answers this path cannot both
    give in one order. The receiver's word lives in the storage the callee
    writes, so `c.field` reads whatever is in there WHEN it is evaluated — and
    the mutator's effect happens when the CALL is made. Left to right, the
    callee runs first and `c.field` is the new value; run as an address
    computation the mutator's store happens last and `c.field` is the old one.

    Making the second answer the source's would mean evaluating one argument
    before another, which no statement on this path says how to do, and getting
    it wrong is a wrong NUMBER rather than a refusal: the program runs and
    reports a value the source never wrote. Named instead.
    """
    return (
        f"{owner}.{member}() is called in the same argument list that reads "
        f"{reader}, the receiver it changes. The receiver's value is read out "
        f"of the storage the callee writes, and this path evaluates a call's "
        f"arguments before it makes the call, so the read would see the value "
        f"from BEFORE {spelled}.{member}(...) ran — where the source means the "
        f"one after. Take the two in separate statements, so the read is "
        f"either unambiguously before or unambiguously after.")


def statement_call_ids(fn) -> set:
    """`id()` of every call that is an `ExprStmt`'s OWN value.

    The one reader of "is this call's result thrown away", which is what
    separates the two positions a by-reference receiver can appear in: a call of
    its own (`c.bump(5)`) has nowhere to put a result and the callee's return
    register is unobserved, and a call inside an expression (`x = c.pop()`,
    `sink(c.pop())`) needs a real answer in it. An `ExprStmt` is a STATEMENT, so
    nothing inside an expression is one — which is why this is the statement's
    own `value` and not a search for a call with an unused result.
    """
    out = set()
    for node in iter_nodes(getattr(fn, "body", None)):
        if isinstance(node, F.ExprStmt) and isinstance(node.value, F.CallExpr):
            out.add(id(node.value))
    return out


def mutating_receiver_value_refusal(owner: str, member: str, spelled) -> str:
    """The diagnostic for a by-reference mutator's result used where there is
    none.

    Since the receiver stopped travelling in the return register, the call's
    result IS the method's declared return value and nothing else. A method that
    declares no return type has no result, so `sink(c.bump(5))` and
    `x = c.bump(5)` have an expression position with nothing to put in it —
    and what the callee happens to leave in the return register is the
    fall-through zero, which is a number the source never wrote.

    This is the boundary the old `mutating_receiver_value_refusal` drew, for the
    same reason and with one fewer case: it used to fire on every mutator used as
    a value, and now it fires only on one that has no value to give. The
    mutator that DOES declare a return type — `BinaryHeap.pop() -> Self.T` —
    is exactly the shape that was refused for a whole sweep row, and it builds.
    """
    return (
        f"{owner}.{member}() changes its receiver and declares no return type, so "
        f"the call has no value, and it is used as one here. On this path a "
        f"one-field struct's mutating method hands the receiver back by WRITING "
        f"through the address the caller passed, so the return register carries "
        f"whatever the body fell off its end with. Give {spelled}.{member} a "
        f"declared return type if the call is meant to produce one, or call it "
        f"as a statement of its own. (`formal/model.py`'s "
        f"`receiver_writeback_name` is the rule.)")


def receiver_writeback_plan(fn, writebacks: dict):
    """`({id(call): ReceiverWriteback}, [address-taken locals])` for one function.

    The CALLER's half of `receiver_writeback_name`, and the table both emitters
    read instead of re-deriving. A call whose callee is in `writebacks` is a
    receiver hand-off: argument 0 is the address of a local's own storage, and
    that local's home has to BE that storage — which is why the names come back
    here and go into `formal/arm64_codegen.py`'s `_allocation_order` rather than
    being copied into a spill slot around the call. A copy in and a copy out
    would have to be ordered against every other argument, and that ordering is
    `mutating_receiver_order_refusal`'s subject.

    `id(call)` rather than the node, and the same key `struct_returned_frame_sites`
    uses: a walk that hands the emitter a node it can look up beats one that
    re-derives a callee name and can disagree about it. EVERY call site is
    marked, whatever position the call is in, because with the store going
    through memory a value position and an argument position are the same
    lowering — which is the second and third of the three measurements
    `receiver_writeback_name`'s docstring records.

    Each value is `(ReceiverWriteback, the caller's name for the receiver)`. The
    pair is not redundancy: `ReceiverWriteback.receiver` is the CALLEE's receiver
    parameter (`self`, which is what the callee's prologue and exits need) and
    the local the caller passes is spelled something else (`c`), and
    `mutating_receiver_order_refusal` is about the caller's — so a table with
    only one of the two compares `self` against a set of caller locals and never
    matches.
    """
    sites, address_taken = {}, []
    statements = statement_call_ids(fn)
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr):
            continue
        wb = (writebacks or {}).get(call_callee_name(node.func))
        if wb is None:
            continue
        recv = node.args[0] if node.args else None
        if not isinstance(recv, F.IdentExpr):
            raise CodegenError(mutating_receiver_address_refusal(
                wb.owner, wb.member,
                receiver_spelling(recv) if recv is not None
                else "the receiver"))
        if id(node) not in statements and not declared_returns_a_value(wb.decl):
            raise CodegenError(mutating_receiver_value_refusal(
                wb.owner, wb.member, receiver_spelling(recv)))
        # The CALLER's spelling of the receiver, alongside the callee's: the
        # two are different names for the same word (`self` in the method, `c`
        # at the call site) and the evaluation-order refusal is about the
        # caller's, so a table carrying only the callee's would compare `self`
        # against a set of caller locals and never match.
        sites[id(node)] = (wb, recv.name)
        if recv.name not in address_taken:
            address_taken.append(recv.name)
    _refuse_receiver_read_in_own_argument_list(fn, writebacks, sites)
    return sites, address_taken


def declared_returns_a_value(decl) -> bool:
    """Whether `decl` has a value a caller can read.

    The DECLARED return type, or a `return` with an expression: a method that
    returns a bare literal declares nothing and this is the undeclared spelling
    of the same fact, so both are asked — `formal/build.py`'s
    `_return_the_receiver` asked exactly these two before the return register
    stopped carrying the receiver.

    A declared `None` return is not a value here: `-> None` is `void` at the ABI
    (`doc/ABI.md`'s scalar table), so it is read as no value rather than as one
    word that happens to be spelled `None`.
    """
    if getattr(decl, "return_type", None) is None:
        return False
    if str(getattr(decl, "return_type")).strip() in ("None", "NoneType"):
        return False
    return True


def declared_receiver_writeback(decl):
    """`decl`'s receiver, when the declaration says it is a one-field MUTATOR.

    **The one reader both backends ask about a callee, for all three ways a
    callee can be reached.** `formal/build.py` marks the definitions a module
    compiles (`_recv_ref_receiver`), and `formal/imports.py`'s
    `external_declarations` parses an imported module's own source so a call
    ACROSS a dylib boundary can ask the same question. That second half is not a
    convenience: before it, a cross-module `c.bump(5)` was passed by value to a
    callee that dereferences its argument 0, and the write-back the per-module
    table could not see was dropped — measured, `c=10` where CPython says 15, on
    both architectures.

    So the answer is read from the DECLARATION, never derived at the call site.
    A call site that had to decide for itself would have two answers (by value,
    by reference) and picking either one silently is the defect this convention
    exists to remove.

    The owner is `_owner_struct`, annotated by whoever parsed the declaration:
    `formal/imports.py`'s `external_declarations` finds the `StructDef` the
    method was written in, and `formal/build.py` has the same fact in its
    `method_owners` table. Without one the answer is None — a free function is
    not a receiver, and a declaration whose owner could not be resolved must not
    be guessed into one.
    """
    if decl is None:
        return None
    owner = getattr(decl, "_owner_struct", None)
    if owner is None or not struct_is_one_field(owner):
        return None
    return receiver_writeback_name(decl)


def receiver_address_refusal(callee: str, receiver: str) -> str:
    """The diagnostic for a receiver this function cannot hand over by ADDRESS.

    The by-reference convention is the whole of how a one-field mutator's
    effect reaches its caller, so a receiver with no address has no lowering:
    passing its VALUE is the pre-2026-03 defect under a new name (the callee
    would store through a number), and reading one out of a callee-saved
    register is the same wrong answer one step later. A name with a register but
    no spill slot is this case — `_allocation_order` puts address-taken names
    past every register-eligible one precisely so they have a slot — and so is
    a compiler bug rather than a source problem, which is why the message says
    so.
    """
    return (
        f"calling {callee}() hands over {receiver} as the ADDRESS of a one-word "
        f"cell for the callee to write its receiver back through, and {receiver} "
        f"has no address in this function: a receiver that is a local is given a "
        f"stack slot so it has one, and a receiver that is not a local has no place "
        f"at all (`_allocation_split` in either backend removes the name from "
        f"the register-eligible half for exactly this). Bind it to a local of "
        f"its own, or make the method a reader.")


def receiver_spelling(node) -> str:
    """The receiver as the reader wrote it, for a refusal's sentence.

    Moved here from `formal/build.py` so the model half that raises the refusal
    and the emitters that could have raised it print one spelling: a name, a
    field chain, a subscript, or the node's type when there is nothing to spell.
    """
    if isinstance(node, F.IdentExpr):
        return node.name
    if isinstance(node, F.MemberExpr):
        obj = receiver_spelling(node.obj)
        return f"{obj}.{node.member}" if obj else str(node.member)
    if isinstance(node, F.SubscriptExpr):
        obj = receiver_spelling(node.obj)
        return f"{obj}[…]" if obj else "[…]"
    return type(node).__name__


def _names_mentioned(node, into: set) -> None:
    """Every bare name `node` mentions, into `into`."""
    if isinstance(node, F.IdentExpr):
        into.add(node.name)
        return
    if isinstance(node, F.MemberExpr):
        _names_mentioned(node.obj, into)
        return
    if isinstance(node, (list, tuple)):
        for x in node:
            _names_mentioned(x, into)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    for f in node.__dataclass_fields__:
        _names_mentioned(getattr(node, f, None), into)


def _refuse_receiver_read_in_own_argument_list(fn, writebacks, sites) -> None:
    """Refuse a hand-off whose receiver is also READ in the same argument list.

    `mutating_receiver_order_refusal` is the diagnostic and this is where it
    fires. The shape is one CALL (`f(c.pop(), c.field)`, `sink(c.pop(), c.n)`)
    with two facts about the same local: an argument that is a receiver hand-off
    and another argument that mentions its name. Left to right, the read happens
    before the store, so it sees the old word; the source means the new one.
    """
    if not sites:
        return
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr):
            continue
        for i, arg in enumerate(node.args):
            if id(arg) not in sites:
                continue
            others = set()
            for j, other in enumerate(node.args):
                if j != i:
                    _names_mentioned(other, others)
            wb, spelling = sites[id(arg)]
            if spelling in others:
                raise CodegenError(mutating_receiver_order_refusal(
                    wb.owner, wb.member, spelling, spelling))


def mutating_receiver_return_refusal(owner: str, member: str) -> str:
    """The diagnostic for a one-field mutator that ALSO returns a FRAME.

    Since the receiver stopped travelling in the return register
    (`receiver_writeback_name`), a mutator may return a value, and an ordinary
    word is not what is left over: a function that returns a frame takes a
    trailing hidden word — the address of a block the CALLER reserved — and a
    mutator's receiver is the leading argument. Both fit, so this is not about
    running out of registers; it is that the block the frame convention copies
    into is the caller's, and the one-word cell the receiver convention writes
    through is the caller's too, so a function that does both has two
    conventions describing one argument list and there is no measured order
    between them on this path. Refused until there is.
    """
    return (
        f"{owner}.{member}() changes its receiver and returns a frame, and "
        f"this path has two hidden-word conventions — the frame's caller-"
        f"reserved block and the receiver's one-word cell — with no measured "
        f"order between them. Split it: have the method change the receiver "
        f"and return nothing, and read the frame from a separate call. The "
        f"rules are `formal/model.py`'s `receiver_writeback_name` and "
        f"`struct_returned_frame_sites`.")


def struct_frame_slots(struct_def) -> list:
    """The slot contents of a framed receiver, in slot order.

    Slot `k` holds field `k`, and that is the WHOLE of the per-struct layout
    this path needs: no padding, no alignment games, no field reordering.  The
    order is `struct_field_names`'s, which is a stable, documented order, so a
    slot index is a function of the class body and nothing else.

    `ProofLib.Frame.SLOT` / `frameOffset` is the same layout stated on the Lean
    side; `struct_frame_slot` is the `slotOf` table `Frame.SlotOf` requires."""
    return struct_field_names(struct_def)


def struct_frame_slot(struct_def, name):
    """The slot index field `name` occupies, or None if it is not a field.

    Injective because the slot list has no duplicates (`struct_field_names`
    de-duplicates), which is exactly `Frame.SlotOf`'s requirement: a write to
    one field must be invisible to a read of another."""
    names = struct_frame_slots(struct_def)
    return names.index(name) if name in names else None


# A local name does not always have ONE struct. `x = A()` on one path and
# `x = B()` on another is ordinary Python, and on this path both are frame
# addresses — of DIFFERENT frames, with DIFFERENT layouts. Which one a use of
# `x.f` means depends on the branch, and there is no path sensitivity here to
# answer it.
#
# The consequence is not a refusal; it is a wrong answer waiting to happen, and
# it is the reason this function exists. Two structs of two fields each:
#
#     struct A:  var v; var pad      ->  v is slot 0
#     struct B:  var pad; var v      ->  v is slot 1
#
#     def pick(c):
#         var x = A()
#         if c > 0: x = B()
#         return x.v
#
# An analysis that settles on ONE struct computes a slot index from it and
# emits `LDR [x, #8k]` — so on the `A` path it reads A.pad and on the `B` path
# it reads B.pad, and both are a number the source never wrote. The program
# builds, it runs, and it is wrong, which is the outcome this whole design
# exists to make impossible.
#
# So the rule is: AGREE or REFUSE. If every candidate struct puts `name` at the
# same slot index, the access is well defined whichever frame the name holds
# and is emitted once. If they disagree — or one candidate has no such field —
# there is no `k`, and the caller refuses naming the candidates and the slots
# they wanted. Nothing here infers a type; the caller supplies the candidates it
# recognised from the BINDINGS, and an empty candidate set means the name holds
# a plain word rather than a frame address at all.
def struct_frame_slot_candidates(structs, name):
    """`(slot, disagreeing)` — the one slot `name` can be at, if they agree.

    `structs` is the candidate list for the holder, in a stable order.
    `disagreeing` is `(True, [(struct_name, slot_or_None), …])` when there is no
    single answer, and `None` otherwise. An empty candidate list yields
    `(None, (False, []))`: the name is not a frame address, so there is no slot
    to compute and the caller's ordinary value lowering applies.

    "No single answer" has TWO shapes and both are disagreement, which is the
    part worth stating because only one of them looks like disagreement:

      * the candidates put `name` at DIFFERENT slots — `A` has it first, `B`
        has it second; or
      * SOME candidate has it and some do not — `A` has `pad` and `B` does
        not, so on the `B` path the access is a read of a word this layout
        never defined.

    The second is the one a "do they agree on the index?" test written as
    `len(slots) > 1` misses, and it is not a rare shape: any name rebound to a
    struct with a different field set produces one, and reading the agreed
    index anyway is the silently-wrong answer. `rows` is returned either way
    because the refusal has to name WHICH candidate lacks it."""
    rows, slots, have = [], set(), 0
    for st in structs:
        slot = struct_frame_slot(st, name)
        rows.append((st.name, slot))
        if slot is not None:
            slots.add(slot)
            have += 1
    if len(slots) > 1 or have != len(rows):
        return (None, (True, rows))
    return ((slots.pop() if slots else None), (False, rows))




# ── `len(x)` where x is a FRAME ADDRESS: the receiver's own `__len__` ─────────
#
# The third answer to "what is a frame address", after "read a field out of it"
# and "hand it to a method of its own struct", and the one the sweep's terminal
# finding was asking for.
#
# `len` is in `FRAME_VALUE_ONLY_CALLS` and the refusal there is right about the
# CATEGORY: a frame is a block of 8-byte slots with no header, so there is no
# count in it to read, and the number a count-field load would produce is the
# struct's FIRST FIELD.  What it is answering is the wrong QUESTION, because
# Mojo's answer to "how long is this object" for a user-defined type is the
# type's own `__len__` — and a method of the receiver's OWN struct is exactly
# the one hand-off a frame address does make.  So `len(h)` on a `Heap` frame is
# not "a length read out of a frame"; it is `h.__len__()`.
#
# That is why this is a REWRITE and not a new lowering: `h.__len__()` is already
# what `formal/build.py`'s `_rewrite_method_calls` turns into
# `Heap___len__(h)`, and the callee takes the frame address as its FIRST
# parameter, which is the whole of the by-reference ABI
# (`struct_is_framed` above, and `FRAME_ADDRESS_CTORS` for the shape where the
# callee dereferences what it is handed).  One lowering, so the two spellings of
# one question cannot come to disagree — the `_emit_binop` /
# `_emit_branch_unless` lesson, twice applied.
#
# Which is also the soundness argument in full.  A frame belongs to the function
# that created it, and an address only ever travels DOWN an active call chain,
# so for the instant of the `__len__` call the creator is an ancestor of the
# callee and every slot the callee reads is live: the same licence a method
# receiver already has, on the same evidence, for the same kind of callee.  What
# the argument does NOT buy is anything about the RESULT — `__len__` returns an
# `Int` here exactly as it does in the source, and that is ordinary value
# lowering.
DUNDER_LEN = "__len__"
# The COMPARISON dunders, which are the second spelling of the same idea: an
# operator is a method of the receiver's own struct, called by name, and the
# spelling in the source is `a == b` rather than `a.__eq__(b)`.
DUNDER_EQ = "__eq__"
DUNDER_NE = "__ne__"


def dunder_receiver_method(struct_def, name: str):
    """This struct's method called `name`, or None when none could be reached.

    A method declared with NO parameters has no receiver, by the same rule
    `struct_receivers` applies to a field read and
    `formal/build.py`'s `_receiverless_methods` applies to a call: there is
    nothing for a frame address to be handed to, so it cannot answer `len(x)`
    or `a == b`.  A `@staticmethod` is excluded for the same reason and by the
    same helper.

    ONE function for the whole family rather than one per dunder, because the
    predicate is about the DECLARATION's shape and not about which operator the
    method answers: three copies of `name != X or staticmethod or no params` is
    three places for the rule to change, and a `__eq__` that quietly accepted a
    parameterless declaration would be called with a receiver it cannot name.
    """
    for m in struct_methods(struct_def):
        if m.name != name:
            continue
        if "staticmethod" in _decorator_names(m):
            continue
        if not (getattr(m, "params", None) or []):
            continue
        return m
    return None


def dunder_len_method(struct_def):
    """This struct's `__len__`, or None when it declares none it could be reached by.

    The `__len__` spelling of `dunder_receiver_method`, kept as its own name
    because every existing caller reads better saying `dunder_len_method` than
    saying `dunder_receiver_method(st, DUNDER_LEN)`, and because it is the one
    of the family that existed before the family did."""
    return dunder_receiver_method(struct_def, DUNDER_LEN)


def struct_dunder_len_candidates(structs):
    """`(owner, disagreeing)` — the struct whose `__len__` answers `len(x)`.

    The same contract and the same reason as `struct_frame_slot_candidates`
    immediately above, over a different fact: WHICH struct the name's frame is,
    rather than which slot a field sits in.  `structs` is the holder's candidate
    list in a stable order; `disagreeing` is `(True, [(struct_name, has_it), …])`
    when there is no single answer and `None` otherwise.  An empty candidate list
    yields `(None, (False, []))`, which is the same "not a frame address at all"
    answer that function gives.

    "No single answer" has both of the shapes the slot version has, and the
    second is again the one a "did they agree?" test written over the SET of
    owners misses: one candidate declares `__len__` and another does not, so
    which call the rewrite emits depends on which frame the name holds — and
    which frame it holds depends on the path taken, and there is no path
    sensitivity here to answer it.  `rows` comes back either way because the
    refusal has to name WHICH candidate declares one.

    ONE difference from `struct_frame_slot_candidates`, and it is a difference
    in what the two facts mean rather than in the shape of the test.  A field
    that no candidate declares is a MISSING FIELD and the caller refuses it as
    one; a `__len__` that no candidate declares is simply the answer "this type
    has no length operator", which is what `len` on a list-free struct means and
    which the hand-off check reports with its own message.  So `have == 0` is
    `(None, (False, rows))` here and a DISAGREEMENT there, and the test is
    written with the `owners and` guard for exactly that reason: without it, a
    one-candidate holder whose struct simply has no `__len__` would be reported
    as two candidates disagreeing, which is false and is a message about a
    program that does not have the problem.
    """
    rows, owners, have = [], set(), 0
    for st in structs:
        found = dunder_len_method(st)
        rows.append((st.name, found is not None))
        if found is not None:
            owners.add(st.name)
            have += 1
    if owners and (len(owners) > 1 or have != len(rows)):
        return (None, (True, rows))
    return ((owners.pop() if owners else None), (False, rows))


# `a == b` is `type(a).__eq__(a, b)`, and `a != b` is `type(a).__ne__(a, b)` —
# with the language's own fallback, so the two are ONE question with two
# spellings rather than two questions.  The dunder each operator reaches, in the
# order it is tried: `!=` looks for `__ne__` and, finding none, for the negation
# of `__eq__`, which is what `object` does and therefore what a struct that
# declares only `__eq__` inherits.
EQ_DISPATCH_DUNDERS = {"==": ((DUNDER_EQ, False),),
                       "!=": ((DUNDER_NE, False), (DUNDER_EQ, True))}


def struct_dunder_dispatch_candidates(left_structs, right_structs, op: str):
    """`(owner, dunder, negate, disagreeing)` — the struct whose dunder answers
    `a op b`.

    The `struct_dunder_len_candidates` contract over a fact with one extra
    dimension, and the same answer for the same reason: WHICH struct, decided by
    AGREE-OR-REFUSE over every struct either name could hold.  The two candidate
    lists go in as ONE list, deduplicated by struct name, because the question is
    a property of the pair of names rather than of either alone: a call whose
    receiver might be `S` and might be `T` is not an `S.__eq__` with a fallback
    to `T`, it is one call or the other depending on the path taken, and this
    analysis has no path sensitivity.

    `dunder` is the name the answer was found under and the caller MUST call
    that one, not the operator's own: `!=` reaches `HasNe___ne__` when the struct
    declares a `__ne__` and `HasNe___eq__` under a `not` when it does not, and a
    caller that spelled the call from `op` would call `__eq__` for both — which
    is the wrong method for the first, and answers `a == b` for the second.
    `negate` says the operator is `!=` reached through the `__eq__` fallback, so
    the caller wraps the call in the language's `not`, which is the whole of that
    fallback.

    `owner is None` with no disagreement is the answer "this type has no
    comparison operator", and it is NOT a refusal: it is what makes CPython's
    INHERITED identity `__eq__` correct, and it is the same reason the frame
    length rewrite leaves a struct that declares no `__len__` alone.  On this
    path a frame's own address compare is already that identity, so leaving the
    operator alone is not a gap — it is the right answer for a struct with no
    dunder, and the case that would break it is a dunder on a DIFFERENT struct
    than the one the addresses are, which is what the disagreement arm is for.
    """
    structs, seen = [], set()
    for st in list(left_structs or []) + list(right_structs or []):
        if st.name not in seen:
            seen.add(st.name)
            structs.append(st)
    for dunder, negate in EQ_DISPATCH_DUNDERS.get(op, ()):
        rows, owners, have = [], set(), 0
        for st in structs:
            found = dunder_receiver_method(st, dunder)
            rows.append((st.name, found is not None))
            if found is not None:
                owners.add(st.name)
                have += 1
        if not owners:
            continue
        if len(owners) > 1 or have != len(rows):
            return (None, dunder, negate, (True, rows))
        return (owners.pop(), dunder, negate, (False, rows))
    return (None, None, False, (False, [(st.name, False) for st in structs]))


def eq_dispatch_candidates_disagree(spelled: str, struct_names, rows,
                                    left_count=None, right_count=None) -> str:
    """Why `a == b` has no single dunder to call, when the candidates disagree.

    The agree-or-refuse refusal for the comparison half, and a different message
    from `frame_len_candidates_disagree` because the answer is a different shape:
    there is nothing to READ that is missing here, there is a CALL that would be
    one of two, and the two are the two answers the program would give on the two
    paths.  `rows` is `[(struct_name, declares_it), …]` from
    `struct_dunder_dispatch_candidates` and the refusal names every row, for
    the reason its sibling gives: "they disagree" without saying which is which
    sends the reader to look at the wrong declaration.

    ## TWO DISAGREEMENTS AND TWO MESSAGES, and the second one is why

    `struct_dunder_dispatch_candidates` returns `disagree` for two different
    facts, and until 2026-10-05 they shared one message whose tail was FALSE
    about half of them. `left_count`/`right_count` are the sizes of the two
    per-side candidate lists, and they are what tells the two apart:

    * **A NAME IS NOT PINNED** (either side has more than one candidate). The
      existing text is exactly right: which struct is live at this comparison
      depends on the path, this analysis has no path sensitivity, and giving each
      name one binding does settle it.
    * **EACH SIDE IS PINNED AND THEY ARE DIFFERENT STRUCTS** — `A() == B()` with
      one `A` and one `B` in the whole function. There is no path to be
      insensitive to, the two names each hold exactly one frame, and the old
      text was not merely beside the point: **its advice cannot work.**
      "Give every candidate the same `__eq__`" makes `owners` hold two names,
      which is the `len(owners) > 1` arm of the very decision that refused — so
      a reader who follows the message is refused again with the same message,
      and "give each name one binding" is impossible when each already has one.

      The real reason is CPython's REFLECTED dispatch, and it is a value-model
      gap rather than an analysis one: `A.__eq__(a, b)` is handed a `B`, which
      in Mojo is not even a well-typed call, and CPython's answer for that is
      `NotImplemented` — which asks the other operand's `__eq__`, and falls back
      to identity when that is missing too. **This path has no representation
      for `NotImplemented` as a dunder's return value**, so the three-way answer
      a reflected `__eq__` needs cannot be lowered at all.

      So the message says that, names what a program CAN do instead (compare the
      fields, or give the two sides the same struct — which makes the comparison
      homogeneous and the dispatch unambiguous), and says plainly that this is
      not something an edit to the bindings will fix. That is the difference
      between a refusal that names its own cause and one that sends the next
      reader after a non-bug, which `formal/model.py`'s own note on
      `FRAME_KIND` calls the expensive direction and which
      `test_refusal_taxonomy.py` is the standing check for.
    """
    who = ", ".join(struct_names) if struct_names else "this struct"
    declared = "; ".join(f"{sn} declares one" if has else f"{sn} declares none"
                         for sn, has in rows)
    lead = (
        f"{spelled} compares two FRAME ADDRESSES, so the answer is the frame's "
        f"own struct's `__eq__` — which means WHICH struct is the whole of the "
        f"question, and {who} does not settle it: {declared}. ")
    if left_count is not None and right_count is not None \
            and left_count == 1 and right_count == 1:
        return lead + (
            "This one is not a question about which frame is live at this "
            "comparison: each name is bound once and to a single struct, so "
            "there is no path for a different struct to be the live one. It is "
            "CPython's REFLECTED dispatch, and it is not answerable here: "
            "`A.__eq__(a, b)` is handed a `B`, which is not a well-typed call "
            "in Mojo, and CPython's answer for it is `NotImplemented` — which "
            "asks the OTHER operand's `__eq__`, and falls back to identity when "
            "there is none. This path has no representation for "
            "`NotImplemented` as a dunder's return value, so the three-way "
            "answer a reflected `__eq__` needs cannot be lowered at all. "
            "Changing which frame a name holds will NOT fix this, and giving "
            "both structs a `__eq__` will not either: two owners is the case "
            "that refuses. Compare the fields, or make the two sides the same "
            "struct so the comparison names one `__eq__`")
    return lead + (
        "Each name holds a different frame on each path that binds it, and "
        "this analysis has no path sensitivity to say which one is live at "
        "this comparison, so the call this would lower to is one of two and "
        "the program would build, run, and answer with whichever struct's "
        "`__eq__` the other path would have called. Give each name one "
        "binding, or give every candidate the same `__eq__`")


def frame_len_candidates_disagree(spelled: str, struct_names, rows) -> str:
    """Why `len(<name>)` has no single `__len__` to call, when the name's
    candidate frames do not agree about declaring one.

    The AGREE-OR-REFUSE refusal for this one fact, and it is a different
    message from `frame_len_refusal` because the answer is a different shape:
    there is no length to refuse to read, there is a CALL that would be one of
    two.  `rows` is `[(struct_name, declares_it), …]` from
    `struct_dunder_len_candidates`, and the refusal names every row because
    "they disagree" without saying which is which sends the reader to look at
    the wrong declaration.
    """
    who = ", ".join(struct_names) if struct_names else "this struct"
    return (
        f"len({spelled}) is len() of a FRAME ADDRESS, whose answer is the "
        f"frame's own struct's `__len__({spelled})` — so WHICH struct's is "
        f"the whole of the question, and {who} does not settle it: "
        + "; ".join(f"{sn} declares one"
                    if has else f"{sn} declares none"
                    for sn, has in rows)
        + ". The name holds a different frame on each path that binds it, and "
          "this analysis has no path sensitivity to say which one is live at "
          "this call, so the call this would lower to is one of two and the "
          "program would build, run, and answer with the other struct's "
          "length. Give the name one binding, or give every candidate the "
          "same `__len__`")


def frame_len_refusal(spelled: str, struct_names) -> str:
    """Why `len(<frame address>)` cannot be lowered, for a frame whose struct
    declares no `__len__`.

    One message for both backends, and it says what the ANSWER to the question
    is rather than restating the rule, because the rule ("a frame has no
    header") is true and is not what is stopping this program: the answer in
    Mojo is the struct's own `__len__`, and a struct that declares none is a
    type with no length operator — which is what `len` on a list-free struct
    means in every language that has one.  So the message says that, and then
    names the two things the source can do about it, of which the second is the
    one this backend can lower.

    There is deliberately no "and the struct DOES declare one" arm.  Every shape
    where that is true is a shape the rewrite takes, or a shape whose REAL fault
    is something else:

      * `len(h)` with one argument — rewritten to `Struct___len__(h)`;
      * `len(h, x)` or `len(h, k=v)` — the ARITY is what is wrong, and the
        emitter has its own message for it ("len() takes exactly one argument
        on this path").  An arm that claimed the operand "is not a bare name"
        there would be false in its first clause — the operand IS the bare name
        `h` — and it is reachable, measured: `return len(b, b)` on a `Bag`
        frame hits it.  A refusal whose stated reason is entirely false is the
    worst outcome on this path (`test_refusal_taxonomy.py` is the standing
    # check for it), so
    the arm is not there to be right about a case that should have a different
        message.
    """
    who = ", ".join(struct_names) if struct_names else "this struct"
    return (
        f"len({spelled}) is len() of a FRAME ADDRESS — the address of a block "
        f"of 8-byte slots that is one struct's fields in declaration order. "
        f"There is no count anywhere in it: a blob's count is a header word "
        f"the blob itself carries, and a frame has no header. Reading 8 bytes "
        f"at offset 0 of a frame does not invent a length, it reads the FIRST "
        f"FIELD's value and calls it a count — which is a number of the right "
        f"magnitude meaning nothing, and that is why this is refused rather "
        f"than lowered. {who} declares no `__len__`, so there is no method of "
        f"its own struct to call and no length in the frame to read. Read the "
        f"field you mean (`len({spelled}.xs)` where the field is a list), or "
        f"give the struct a `__len__` — `len(x)` is `x.__len__()`, and a "
        f"method of the receiver's own struct is a call this backend makes")


def mutated_module_global_refusal(name: str, fn_name: str) -> str:
    """Why a function cannot WRITE a module global it declares `global` — and
    WHEN this still applies, which is narrower than the rest of this docstring
    suggests.

    **A `__DATA` slot changes the answer, and this message is now only for the
    names that do NOT have one.**  `formal-module-globals` landed per-module
    storage, so a module-level name with a slot is one some function writes
    through `global`, its value changes while the program runs, and the write
    has somewhere real to go; `formal/build.py`'s
    `_collect_shadowed_global_reads` gates the finding on
    `declared_globals & assigned - module_slots()` for exactly that reason.
    Measured, from that gate's own comment: the case was 6 of
    `test_formal_globals.py`'s 17 before the gate and 0 after, and the image
    answers CPython (`G = 5` with `global G; G = G + 1` called twice, read back
    after: 7). The numbers quoted in the rest of this docstring — 10601485 and
    5, 11 and 5 — are therefore the PRE-slot measurement, and they are the
    right answer for the no-slot case this message is still reached for. The
    sibling row in `test_formal_run.py` that used to assert this refusal for a
    slotted `G` is now `a_mutated_module_global_is_computed` and asserts exit
    12, which is CPython's.

    The design decision this path already made and this message reports is in
    the comment above `GlobalSymbol`: a module-level name is either FOLDED — its
    value is literal-only, substituted at every read, and needs no storage
    because nothing ever stores it — or it is a real mutable-or-computed global
    with nowhere to live, because a formal value lives in a function's own stack
    scratch and that scratch is reclaimed when the function returns.  There is no
    `__DATA` slot to redirect a write into, and the emitters say so where the
    declaration is handled: `formal/arm64_codegen.py`'s `GlobalStmt` branch is
    "the declaration is a no-op and the following AssignStmt still targets the
    local", with the same words in x86-64's.

    So `global G; G = G + 1` on a name with no slot writes a LOCAL, and the
    module's `G` keeps the value it was folded with — and the two architectures
    disagree about the local while both are wrong.  Measured, on

    ```
    G = 5
    def bump():
        global G
        G = G + 1
        return G
    def read():
        return G
    ```

    CPython answers 6 and 6.  This path answers **10601485 and 5** on arm64 and
    **11 and 5** on x86-64: the write landed in a register, the read of the
    module's name still folds to the 5 it was bound with, and the two
    architectures cannot agree on the first number because it was never
    computed.  A program that prints two numbers and gets four wrong ones, two of
    them architecture-dependent, is the shape this backend's refusals exist for.

    Declaring `global` is not the mistake — it is the only correct spelling for
    what the source means, and the analysis is what has nowhere to put it.  So
    the message says what the path can do instead: fold the value at module level
    and read it, or move the computation into a function and pass the result in.
    """
    return (
        f"{name} is declared `global` in {fn_name}() and assigned there, so the "
        f"program means to WRITE the module's {name} — and this path has no "
        f"storage for that. A formal value lives in a function's own stack "
        f"scratch and that scratch is reclaimed when the function returns, so "
        f"there is no location a write to a module-level name could outlive; a "
        f"module-level name whose value the build can FOLD is substituted at "
        f"every read and needs no storage precisely because nothing ever stores "
        f"it, and this assignment is that store. The declaration is not the "
        f"mistake — it is the only correct spelling for what the source means, "
        f"and the analysis is what has nowhere to put it. Measured: CPython "
        f"answers 6 and 6 for a `global {name}` increment read twice, and this "
        f"path answers 10601485 and 5 on arm64 and 11 and 5 on x86-64 — the "
        f"write landed in a register, the module's {name} still folds to the "
        f"value it was bound with, and the two architectures cannot agree on "
        f"the first number because it was never computed. Make the module-level "
        f"binding a literal (or literal-only arithmetic on literals) and read "
        f"it, or move the computation into a function and pass the result in")


def shadowed_module_global_read_refusal(fn_name: str, name: str,
                                       value_spelling: str) -> str:
    """Why a function cannot read a module global it also assigns.

    **The premise this corrects is worth stating, because the obvious reading of
    the program is wrong.**  For

    ```
    G = 5
    def bump():
        G = G + 1
        return G
    ```

    the right-hand `G` does NOT resolve in module scope.  A name assigned
    anywhere in a function body is LOCAL to that body from the first line — that
    is Python's rule, it is decided when the function is compiled, and it is why
    CPython raises here:

    ```
    UnboundLocalError: cannot access local variable 'G' where it is not
    associated with a value
    ```

    (measured, CPython 3.14, the same text).  So there is no number this program
    has, and the only honest answer is that it does not lower.  What this path
    does instead is read the name's LOCAL home, which has never been initialised,
    and answer whatever the register allocator left there: measured on this tree,
    `main` printed the local as **11** on x86-64 and as **78152773** on arm64,
    with the module's `G` correctly left at 5 in both.  Two architectures, two
    numbers, neither of them written by the source — and the difference between
    them is register allocation, which is the signature of a value that was never
    computed.

    The read is left unsubstituted because `_substitute_module_constants` treats
    the name as a local of this function, which it is; that is correct, and it is
    also why the read has no value to give.

    The repair named is the one the language offers, and it is not "make the gate
    order-dependent": a name that is local throughout cannot be made to read from
    the module before its first assignment, because there is no such reading.
    `global G` says the module's `G` IS the local, which is a different program
    and the right one to write when that is what is meant.
    """
    return (
        f"{name} is read in {fn_name}() at `{value_spelling}`, before anything in "
        f"that function has assigned it — and {name} IS a local of {fn_name}() "
        f"from its first line, because the function assigns it, and it is also a "
        f"module-level binding of this module. That is the collision: the read "
        f"has no home. The language's own answer is UnboundLocalError (measured, "
        f"CPython: \"cannot access local variable '{name}' where it is not "
        f"associated with a value\"), because a name assigned anywhere in a "
        f"function body is local to that body throughout — it does NOT resolve "
        f"in module scope until after the assignment, and there is no ordering "
        f"that makes this read valid. What this path did instead is read the "
        f"local's register, which holds whatever the allocator left there: "
        f"measured, {fn_name}() returned 11 on x86-64 and 78152773 on arm64, two "
        f"numbers and neither of them written by the source. Either declare "
        f"`global {name}`, which makes the module's binding the local and is a "
        f"different program, or read the module-level name from a function that "
        f"does not also assign it")


def value_position_method_refusal(fn_name: str, receiver: str, name: str,
                                  owner) -> str:
    """Why `recv.name` in a VALUE position is a bound method and not a field.

    The message for the sibling case `member_read_without_a_field` cannot reach,
    and the reason it cannot is worth stating because it is what made this a
    SEPARATE check rather than a branch there. That function is asked by the
    frame pass, which only sees a read whose base it has already classified as a
    frame address — and a method reference is most often a read of a receiver
    that is NOT a frame, because a struct with one field has its receiver BE
    the field. So the name is not a field, no frame slot was ever asked for, and
    the read falls through to the emitter, which answers it as a store with no
    home and blames the base's binding.

    …which is how `self.helper` came to be reported as "this path has no way to
    say what 'self' holds" when the truth is that `helper` is a method and there
    is nothing to say. The wrong answer it replaced was worse: the derived field
    set had a slot for it, nothing ever wrote it, and every read returned zero —
    a program that built, ran, and returned a number the source never wrote.

    The two halves of Python's own rule are both here, because the message has
    to tell the reader which one they are looking at. An instance attribute
    SHADOWS the class's method, so a struct that both declares `name` as a
    method and STORES `self.name` is a field, and this check does not fire on
    it — that is `struct_receiver_stores`, the same function the field-set
    derivation asks. Only a name the struct never stores into is a method here,
    and that is the only case where the answer is "call it".
    """
    who = owner.name if owner is not None else "this struct"
    return (
        f"{fn_name}: {receiver}.{name} is not a field of {who} — {name} is one "
        f"of its METHODS, and nothing in {who} stores into an attribute of that "
        f"name, so in Python this expression is the bound method. A method is "
        f"not a word: there is no slot to read it out of and nothing to store it "
        f"in, and this backend refuses that rather than inventing a slot nothing "
        f"writes — which is how the read used to answer zero, a number the "
        f"source never wrote. Call it (`{receiver}.{name}(...)`), which is a "
        f"receiver and a call and lowers, or write the operation out where it "
        f"was used"
    )


def holder_rebound_from_a_word_refusal(fn_name: str, name: str,
                                       value_spelling: str,
                                       frame_spelling: str,
                                       structs) -> str:
    """Why a name that holds a frame address cannot also hold a plain word.

    One message for both backends and for the build pass, because the defect is
    a property of the ANALYSIS and not of an instruction: a name enters the
    holder set and nothing ever removes it, so every field access through it is
    still lowered as `base + 8·slot` after a binding that left a word there.
    `r = R(); r.a = 7; r = 5; return r.a` therefore loads from address 5 —
    measured, SIGSEGV exit 139 on arm64 and on x86-64, from a green build.

    The two spellings go in the message because the reader has to be told WHICH
    line settles it, and the two readings — "`r` is a frame" and "`r` is a word"
    — are the whole disagreement.  `frame_spelling` is the binding that made the
    name a holder, which is the one that also settles what every OTHER access
    through the name is lowered as, so naming it tells the reader what the
    conflicting store is about to invalidate.

    The three allowed values are named too, because "why is THIS one refused"
    is the question a reader has after reading a list of other assignments in
    the same function that were not.
    """
    who = ", ".join(sorted({st.name for st in (structs or ())})) or "a struct"
    return (
        f"{name} is assigned {value_spelling} in {fn_name}(), and {name} also "
        f"holds the address of a {who} frame — {frame_spelling} binds it to one, "
        f"and this path has no way to say that a later binding changes what the "
        f"name is. Every field access through {name} is already lowered as a load "
        f"at `[base + 8·slot]` on the strength of the first binding, so after "
        f"this store the load reads address `{value_spelling} + 8·slot`: "
        f"measured, the program builds, runs, and dies with SIGSEGV (exit 139) "
        f"on both architectures, which is a fault rather than a wrong number only "
        f"because the word happened not to be mapped. A value that may be a "
        f"frame is one of three things and this is not any of them: a CONSTRUCTION "
        f"of a framed struct (`{name} = S(...)`), a COPY of another holder "
        f"(`{name} = other`), or a parameter of a method of a framed struct. Use "
        f"a different name for the word, or copy the value out of {name} first")


def receiver_rebound_from_a_word_refusal(fn_name: str, receiver: str,
                                         value_spelling: str,
                                         struct_names) -> str:
    """Why a method cannot rebind its own receiver to a plain word.

    The sibling of `holder_rebound_from_a_word_refusal`, and the reason it has
    to be a separate message is that the LOCAL rule's two repairs do not exist
    for a receiver: a receiver is not a name the caller can re-declare, and
    "copy the value out of it first" is not a thing. So the local check
    excludes the method's own receiver names — by NAME from
    `struct_receivers`, which covers `out self` and `inout self` and every
    other receiver spelling by the same rule — and what the exclusion leaves
    open is this.

    **The defect, measured.** A method's effect on a field reaches its caller
    because the caller holds the SAME address the method dereferences; that is
    the whole of the by-reference receiver. Rebinding the receiver points the
    method at a different word, so the write does not reach the caller at all —
    a silently dropped store with an address-shaped cause — and every later
    field read through the receiver is a load at `base + 8·slot` where `base` is
    whatever word was assigned:

        struct R:
            var a: Int
            var b: Int
            def rebind(self):
                self = 5
            def read(self):
                return self.a      # a load at 5 + 8·0

    CPython raises `TypeError` on the shape rather than answering it, and that
    is worth saying in the message: the source is not a program that computes
    something else, it is a program that does not mean what it looks like.

    **What is allowed, and why each one is not this defect.** A receiver
    rebound to a CONSTRUCTION of its own struct is the idiomatic Mojo
    constructor (`self = Self(...)`, and `self = <expr>` where the expression
    builds a frame of the receiver's own type): that is a fresh object, the
    address the caller holds is the one being replaced wholesale, and there is
    no dropped write to report. A receiver rebound to ANOTHER receiver — the
    same address, copied — is fine for the same reason and deserves a note
    because a rule of the form "never rebind a receiver" would break it for no
    reason: it copies the address, the caller's slot already holds it, and the
    method's field writes still land where the caller expects.

    **The two the rule now also allows, and both are about a receiver that is
    an ADDRESS** (`formal/build.py`'s `_collect_receiver_rebinds`, which asks
    `model.one_field_answer` for that rather than deciding it here). A name of
    the receiver's own type that is neither a receiver nor a parameter — a
    callee-private `var t = R()`, from `receiver_own_type_names`'s second set —
    is a copy of the same layout, and Python's rebinding points `self` at `t`
    too, with the caller's frame left alone; and a rebinding **nothing reads
    afterwards** cannot drop a store, because there is none left to drop and no
    later field read to load at `[base + 8·slot]`. A one-word struct whose sole
    field holds a placed frame is the case that gets NEITHER, and it is why this
    message does not promise them: there the receiver word IS the address the
    caller still holds, so the same assignment destroys it.

    `struct_names` is the struct the receiver belongs to, so the message can
    name it rather than making the reader re-derive it from the method."""
    who = ", ".join(sorted({st.name for st in (struct_names or ())})) or "its own"
    return (
        f"{receiver} is assigned {value_spelling} in {fn_name}(), and "
        f"{receiver} is this method's receiver, so it is the address the CALLER "
        f"passed rather than a name either side can re-declare. A method's "
        f"write to a field reaches its caller because the caller holds the same "
        f"address this method dereferences; rebinding the receiver points the "
        f"method at a different word, so the write never gets back to the "
        f"caller at all — measured, the program builds, runs, and prints what "
        f"the caller built the frame with — and every later field read through "
        f"{receiver} is a load at `[base + 8·slot]` with base = "
        f"{value_spelling}. CPython rejects this shape outright, so the source "
        f"is not a program that computes a different answer, it is one that does "
        f"not mean what it looks like. What a receiver may be assigned is a "
        f"CONSTRUCTION of {who} (`{receiver} = Self(...)`, which is how a Mojo "
        f"constructor rebinds its own object), another receiver of the same "
        f"type, or a name of that type this method binds for itself — each of "
        f"which copies an address the caller's slot already holds — and, when "
        f"this method never reads {receiver} again, any word at all")


def method_member_name(struct_def, fn) -> str:
    """The name the SOURCE gave the method `fn` of `struct_def`.

    Asked the only way that cannot drift from the lifted symbol: the other way
    round, by asking which of the struct's own methods lifts to `fn`'s name.
    `fn.name` is the answer whenever the join fails, so a method that reached
    this without an owner (a lifted lambda, a synthesized constructor) still
    names something rather than nothing — and the caller is a diagnostic, which
    must never raise on the question it is asking.
    """
    return next((m.name for m in struct_methods(struct_def)
                 if method_function_name(getattr(struct_def, "name", ""),
                                         m.name) == getattr(fn, "name", None)),
                getattr(fn, "name", ""))


def receiver_own_type_names(fn, owner, structs_by_name=None):
    """`(parameters, locals)` — names `fn` can hold a REFERENCE to an object of
    the RECEIVER'S OWN STRUCT TYPE in.

    One recogniser for both receiver rules, and the reason it returns two sets
    rather than one is that the two rules then disagree about them: a parameter
    is an object the CALLER owns, so pointing the receiver at it copies an
    address the caller's slot already holds (fine for a frame receiver, and for
    a one-field receiver it is a copy of a word into the caller's object, which
    Python does not do), while a local is callee-private, so Python's later
    stores through the rebound receiver are invisible outside — which a frame
    receiver gets exactly right by rebinding its own address, and which no
    one-field receiver can deliver at all.

    **A name is in one of these sets only from a DECLARATION.** A parameter
    annotated with the struct (`other: R`, `other: Self`) or assigned from a
    construction of it (`var t = R()`); a name that merely has a field read on
    it, or a method called on it, is a WORD — this repository's own source calls
    `.strip()` on strings all day, and a census that counted those reported 52
    sites of which 28 were not objects at all.

    `owner` is the StructDef the method belongs to and is what reduces a bare
    `Self`; it is required, because without it `other: Self` names nothing and
    the answer would silently lose exactly the spelling this exists for.
    """
    owner_name = getattr(owner, "name", None)
    decls = structs_by_name if structs_by_name is not None else (
        {owner_name: owner} if owner_name else {})
    params = {n for n, st in parameter_declared_structs(
        fn, decls, owner).items() if getattr(st, "name", None) == owner_name}
    locals_ = set()
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(node, (F.AssignStmt, F.VarDecl)):
            continue
        target = (node.target if isinstance(node, F.AssignStmt)
                  else getattr(node, "name", None))
        name = target.name if isinstance(target, F.IdentExpr) else (
            target if isinstance(target, str) else None)
        value = getattr(node, "value", None)
        if not name or name in params or not isinstance(value, F.CallExpr):
            continue
        if call_callee_name(value.func) in (owner_name, "Self"):
            locals_.add(name)
    return params, locals_


def one_field_receiver_rebind_refusal(owner: str, member: str, receiver: str,
                                      value: str, what: str) -> str:
    """Why a ONE-FIELD struct's mutator may not rebind its receiver to a name of
    its own type — the one receiver store this path cannot deliver.

    The sibling of `receiver_rebound_from_a_word_refusal`, which is about a
    receiver pointed at something that is not an object at all. This one is
    about a receiver pointed at a perfectly good object of its own type, and it
    is a DIFFERENT defect with the opposite sign: nothing is dropped, the wrong
    thing is copied.

    **The mechanism, because it is the opposite of the frame receiver's.** A
    multi-field struct's receiver is the ADDRESS of a frame of 8-byte slots, so
    the caller and the callee share storage and a rebinding changes only which
    object the method writes through — which is Python's own semantics, measured
    on both architectures and pinned by `test_formal_run.py`'s
    `both_arch_receiver_copied_from_another_keeps_the_callers_value`. A
    one-field struct has no frame: its receiver IS its single word
    (`_rewrite_self_fields` collapses `recv.<field>` onto `recv`), and its
    mutating method HANDS THAT WORD BACK so the caller stores it over the object
    (`receiver_writeback_name`) — which is what makes `self.a = self.a + 4`
    reach the caller at all. So for one field the same source text means
    "assign the CALLER", and a rebinding delivers an assignment Python never
    asked for:

        struct T:
            var a: Int
            def take(out self, other: Self):
                self = other

    CPython runs that and leaves the caller's object alone — Python has no
    "assign the receiver" operation at all, so after `self = other` the method's
    own `self.a` reads and writes go to `other` and the caller sees nothing.
    Measured on BOTH architectures from a GREEN build: this printed the OTHER
    object's value.

    **Why it is refused rather than delivered or dropped.** Delivering it is
    impossible: a one-field mutator's one return word is already the receiver,
    and Python's own semantics for this store is a write into `other`'s caller —
    a second word this ABI does not have. Dropping it (suppressing the
    write-back) would be right when the method stores nothing else afterwards
    and silently wrong when it does, because Python's later `self.a = v` goes
    through the alias and this path has nowhere to put it. So the shape is
    named, and `what` says which of the two it is: a parameter (an object the
    caller already holds) or a local of the method.

    **What is NOT this defect**, because the corpus is full of it and the rule
    must not cost a file: a store to the receiver's own word. `self = self + 4`,
    `self = False`, `self = <a value the method computed>` — 28 of the 51
    hand-written `self = …` sites in this repository and the stdlib
    (`tools/formal_receiver_rebind_census.py`) — means "my field is now this",
    the write-back is the mechanism that delivers it, and `self.a = other.a`
    means the same thing spelled as a field store.
    """
    return (
        f"{owner}.{member}() assigns its receiver `{receiver}` the name "
        f"`{value}`, and `{value}` is {what} of this method and holds a "
        f"`{owner}`, so this is "
        f"Python REBINDING a local name rather than storing into the object the "
        f"caller holds: Python has no \"assign the receiver\" operation at all, "
        f"so after `{receiver} = {value}` this method's own `{receiver}.<field>` "
        f"reads and writes go to `{value}` and the caller's object is untouched. "
        f"CPython runs that source and answers with the value the caller already "
        f"had. On this path the receiver of a struct of ONE field is that field "
        f"— a word, not an address — and a mutating method HANDS THE WORD BACK "
        f"so the caller stores it over its object (`formal/model.py`'s "
        f"`receiver_writeback_name`, which is what makes "
        f"`{receiver}.<field> = {receiver}.<field> + 4` reach the caller). So "
        f"the rebinding is delivered as a COPY and the caller reads `{value}`'s "
        f"value where the source says it keeps its own: measured on BOTH "
        f"architectures, this builds, runs, prints the other object's value and "
        f"exits 0. It cannot be delivered — one return word is already the "
        f"receiver, and Python's own reading of the store is a write into "
        f"`{value}`'s own caller — and it cannot simply be dropped, because "
        f"Python sends every later `{receiver}.<field> = …` through the alias "
        f"and this path has no second word to carry that. Spell the store as "
        f"`{receiver}.<field> = {value}.<field>`, which copies the value and is "
        f"what the source means when the object being changed is the receiver's, "
        f"and give the method a name of its own for the other one."
    )


def construction_mismatch_refusal(target: str, callee: str, summary: str,
                                  fn_name: str) -> str:
    """Why `{target} = {callee}(…)` and `{target}.<field>` are two answers to one
    name, and which of them the emitters picked.

    The stdlib's own `String` is the case this exists for, and its own comment
    says why the name is ambiguous: `std/collections/string/string.mojo` declares
    three fields AND lowers its methods under the `char *` reading, with a flag
    in the top of the capacity field choosing between the two forms at run time.
    So both readings are in force in one file, and a program that writes a field
    through the name is asking a question this path has one answer for.

    WHICH answer the emitters pick is the load-bearing half and it is the
    counterintuitive one: the string and identity tables win.  `String()` is
    intercepted as a string CONVERSION before `_emit_struct_constructor` is
    reached — `type_constructor_prefers_local_struct` deliberately does not
    override those two tables, because for `Pointer` the identity conversion is
    the one hand-off in the family that is correct — so the value is the address
    of an interned NUL-terminated `char *`, and `{target}.<field> = v` would be
    a store at `[interned_address + 8·slot]` in read-only `__TEXT`.  Measured on
    both architectures, before this refusal existed: SIGBUS, exit 138, from a
    green build, on a fourteen-line program with no imports.

    The message says both answers, names the emitters' choice, and gives the two
    things the source can do: give the local a different name, or do not write a
    field through a value this path is holding as text.
    """
    return (
        f"{target} = {callee}(...) binds {target} to a value this path holds as "
        f"TEXT, and {target}.<field> asks for a frame: {callee} is declared "
        f"here as a struct of {summary}, so the field has a slot, and {callee} "
        f"is also a type this path lowers as a conversion, so the call is a "
        f"conversion and {target} is the address of a NUL-terminated `char *`. "
        f"The emitters pick the conversion — {callee}() is intercepted before "
        f"any struct construction is reached, because the identity and string "
        f"tables are deliberately not overridden by a local declaration (see "
        f"`model.type_constructor_prefers_local_struct`) — and the two readings "
        f"of the name are then in force at once: the field store is emitted at "
        f"the interned address plus 8·slot, which is read-only text. Measured, "
        f"on both architectures before this check existed: the program builds, "
        f"runs, and "
        f"dies with SIGBUS (exit 138), on the fourteen lines of {fn_name}() and "
        f"no imports. Give the local a name of its own that is not {callee}'s, "
        f"or keep the value as text and do not write a field through it — a "
        f"`{callee}` local is a three-slot frame OR a `char *` on this path and "
        f"never both at once")




# ── A field's DECLARED type: agree, or refuse ─────────────────────────────
#
# `struct_frame_slot_candidates` above settles WHERE a field lives, from the
# bindings of the name holding the frame.  What it cannot settle is WHAT the
# word in that slot is, and C5's named next step is that a field's declared
# type is the one thing on this path that says:
#
#     struct B: var _rng: SomeStruct    ->  self._rng.step() is a nested frame
#     var p: Pointer                    ->  self.p.value is a load at an offset
#
# Both are one lookup away from the AST, and both are the silently-wrong
# direction if the lookup is done halfway.  A frame slot holds ONE word.  So:
#
#   * concluding "this slot holds a frame address" obliges the codegen to PLACE
#     that frame — reserve it, initialize it, and put its address in the slot.
#     An unplaced frame address is a number the source never wrote, which is the
#     outcome this whole design exists to prevent, and it is WORSE than the
#     refusal it replaces because it does not fail;
#   * concluding "this slot holds a pointer" obliges the proof side to know the
#     pointee's layout, element size and address space, and nothing here does.
#     An arbitrary `p + k*size` load is a second addressing mode, which is a
#     second thing to get right on a path whose entire value is that there is
#     one.
#
# So the rule is the SAME one, deliberately: **AGREE OR REFUSE**, and this time
# over TYPES.  A declared type is used only when every binding of the name
# agrees with it.  One counter-example — a second declaration naming something
# else, a candidate struct that does not declare the field at all — and the name
# is NOT typed, the case stays refused, and the refusal says which candidate
# wanted what.
#
# `struct_frame_slot_candidates` is the pattern being copied exactly, and the
# tie-break is what makes the copy safe: **disagreement and "the type is not one
# of this unit's" both fall out of the typed set, never into it.**  An absent
# answer is the answer.  A name is treated as holding a nested frame only when
# every candidate's declaration names a struct THIS MODULE DECLARES whose
# receiver is a frame, and there is no path by which a doubtful annotation
# reaches the emitter.
#
# What the check buys, in the two directions, and both are real:
#
#   * FORWARD — `self._rng.step()` becomes a method call on a nested frame this
#     compiler placed, and its lifetime is the outer object's rather than
#     something the analysis has to argue about.  That is strictly MORE than the
#     refusal it replaces: the refusal's whole complaint was that the frame
#     belongs to whichever function built the object, and a frame we placed in
#     the outer frame's own block belongs to exactly the function the outer
#     object belongs to.
#   * BACKWARD — a field declared `List[Self.T]`, `Int32`, `SIMD[…]` or
#     `UnsafePointer[…]` is PROVABLY not a frame address of this unit, so the
#     word in the slot is a plain value and the diagnostic that describes it is
#     the value-method one.  Lifting the frame refusal on a proof is the
#     difference between "the frame layout cannot represent this" (which was
#     never true) and the refusal that is actually about the callee.

# The spelling decorations a declared type carries, stripped before its base
# name is looked up. `ref[Inner]`, `borrowed[...]`, `mut Self`, `out self` —
# none of them changes WHICH struct the annotation names, and keeping any of
# them would make `var p: ref[Inner]` disagree with `var p: Inner` when they are
# the same declaration of the same thing.  The strip happens BEFORE the type
# arguments are dropped, so `ref[Inner]` reduces through the `ref` to `Inner`
# rather than to an empty string.
_TYPE_DECORATIONS = ("ref", "mut", "out", "inout", "borrowed", "read", "owned",
                     "unsafe", "raises", "Self")


def _strip_type_args(text: str) -> str:
    """Whatever is outside the outermost `[...]` pair — the type's own name."""
    depth, cut = 0, None
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                cut = i
            depth += 1
        elif ch == "]":
            depth -= 1
    return text if cut is None else text[:cut]


def _split_type_args(text: str) -> list:
    """The texts INSIDE the outermost `[...]` pair, top level split on commas.

    The complement of `_strip_type_args`, and the reason `List[Box]` can say
    which STRUCT its elements are where `List` alone cannot.  Splitting on top
    level commas only: `List[Dict[String, Int]]` is ONE argument, and a naive
    `split(",")` would hand back `Dict[String` and `Int]]`, neither of which
    names a struct.
    """
    depth, cut, close = 0, None, None
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                cut = i
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                close = i
                break
    if cut is None or close is None:
        return []
    inner, args, start = text[cut + 1:close], [], 0
    depth = 0
    for i, ch in enumerate(inner):
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(inner[start:i].strip())
            start = i + 1
    args.append(inner[start:].strip())
    return [a for a in args if a]


def _strip_type_decorations(text: str, self_type: str | None = None):
    """`text` with every leading `_TYPE_DECORATIONS` marker removed, or None.

    The loop `annotation_base_name` and `annotation_type_arg_base` both need,
    and one copy of it because the two answer questions about the SAME
    declaration: a decoration in front of a type does not change which type it
    names, and a `self_type` supplied for `Self` means the same thing to both.

    `None` for a marker with nothing after it (`out Self` reduced, a bare
    `mut`), and for a function-typed declaration (`fn(x: Int) -> Int` names no
    struct either way).  Both are the unagreed direction.
    """
    changed = True
    while changed:
        changed = False
        for deco in _TYPE_DECORATIONS:
            if text == deco:
                if deco == "Self" and self_type and self_type.isidentifier():
                    return self_type
                return None
            if text.startswith(deco) and text[len(deco):len(deco) + 1] in (" ", "["):
                text = text[len(deco):].strip()
                if text.startswith("["):
                    depth, close = 0, None
                    for i, ch in enumerate(text):
                        if ch == "[":
                            depth += 1
                        elif ch == "]":
                            depth -= 1
                            if depth == 0:
                                close = i
                                break
                    if close is None:
                        return None
                    text = text[1:close].strip()
                changed = True
    if "(" in text:
        return None
    return text


def annotation_type_arg_base(ann, arg: int = 0,
                             self_type: str | None = None) -> str | None:
    """The bare name of the `arg`-th type ARGUMENT, or None.

    `List[Box]` → `Box`, `StaticList[Box, 3]` → `Box`, `List` → None,
    `List[Self.T]` → `T`, `Dict[String, Int]` → `Int` at `arg=1`.

    This is the reader `annotation_base_name` cannot be, and the reason it is a
    separate function rather than a flag: the base answers "is this a LIST",
    which every `List[...]` agrees on, while this answers "of WHAT", and the
    element type is the whole of what a subscript receiver's type is made of.
    The measurement behind that split is the deleted
    `FORMAL_method_call_on_a_subscripted_receiver`: `def drain(vals:
    List, …)` declares no element and no pass over the source can supply one,
    while `def drain(vals: List[Box], …)` states it outright.

    Every doubtful answer is None, in the same direction as its sibling: an
    annotation with no brackets, an empty argument, one that does not reduce to
    an identifier, and a qualified name that is not a `Self` type-parameter
    access.  A caller that is handed None cannot claim a struct, which is the
    only safe reading of "the source does not say".
    """
    text = _strip_type_decorations(ann.strip() if isinstance(ann, str) else "",
                                   self_type)
    if not text:
        return None
    args = _split_type_args(text)
    if arg >= len(args):
        return None
    return annotation_base_name(args[arg], self_type=self_type)


def annotation_base_name(ann, self_type: str | None = None) -> str | None:
    """The bare type name a declared type names, or None if it names nothing.

    `List[Self.T]` → `List`, `PhiloxRandom[10]` → `PhiloxRandom`,
    `Random[Self.rounds]` → `Random`, `unsafe Pointer[Int32]` → `Pointer`,
    `ref[Inner]` → `Inner`, `Self.T` → `T`, `Int32` → `Int32`.

    `self_type` is the struct a bare `Self` stands for, for the one caller that
    knows it: a method of `S` writing `other: Self`. With it, `Self`,
    `out Self` and `ref[Self]` reduce to `S`'s own name; without it they reduce
    to None exactly as before, which is what every FIELD declaration wants —
    `Self` on a field of a class body is the class, and the caller asking about
    a field is the holder analysis, which has the struct in hand and passes it.
    `Self.T` is deliberately NOT affected, because a type-parameter access names
    a parameter rather than the enclosing struct and that answer is the same one
    the field path gives.

    The type ARGUMENTS are dropped rather than compared, and that is the safe
    direction for a specific reason: `List[Int]` and `List[String]` are different
    types but this path has ONE representation for both (a word), so treating
    them as the same base is not a lie about the value — it is a decision about
    which STRUCT the value is, and the struct is named by the base alone.  A
    base that is a struct of this unit decides a frame layout; the arguments
    decide nothing this path has a slot for.  A base that is NOT a struct of this
    unit decides nothing at all, and the caller says so.

    None is the important half, and it is returned for everything this function
    cannot reduce to a single identifier — which is the rule, stated positively
    because the cases are what matter:

      * no annotation at all (`x = 0`, a field only `__init__` assigns, a name
        from `__slots__`).  This is the untyped case the agree-or-refuse rule
        exists to detect, and it must not be confused with anything below.
      * a qualified name that is not a type-parameter access.  `ref[self._data]`
        is a reference to the type OF a field, and there is no declaration here
        that says what that is; returning `_data` would look up a struct named
        after a field.  `Self.origin` IS a type-parameter access and reduces to
        `origin`, which is a parameter and names no struct here.
      * a decoration with nothing after it (`out Self`, `mut`), and a
        function-typed declaration.  The one exception is the `self_type`
        argument above: a bare `Self` is not a decoration in front of nothing,
        it IS the enclosing struct, and refusing to reduce it is what left
        `other: Self` in `Slice.__eq__` unreadable.

    Every one of those is the UNAGREED direction, so a doubtful annotation can
    only ever remove a name from the typed set.
    """
    if not isinstance(ann, str):
        return None
    text = _strip_type_decorations(ann.strip(), self_type)
    if text is None:
        return None
    # A CALLABLE type (`fn(x: Int) -> Int`) is a function pointer here and names
    # no struct, so it is the untyped direction rather than a base of `fn`.
    # (Decided inside `_strip_type_decorations`, so the sibling reader of a
    # type's ARGUMENTS cannot answer "yes" where this one answers "no".)
    text = _strip_type_args(text)
    if not text or not (text[0].isalpha() or text[0] == "_"):
        return None
    if "." in text:
        head, _sep, tail = text.rpartition(".")
        if head != "Self":
            # A qualified name this path cannot resolve to a declaration in
            # this unit — `ref[self.items]`, `module.Type`, `a.b.C`. Returning
            # the last component would look up a name the declaration never
            # wrote.
            return None
        text = tail
    if not text.isidentifier() or text in _TYPE_DECORATIONS:
        return None
    return text


def parameter_declared_structs(fn, decls: dict, owner=None) -> dict:
    """`{parameter name: StructDef}` — the parameters whose DECLARED TYPE names
    a struct of THIS module.

    The PARAMETER half of `frame_field_type_candidates`'s question.  That
    function asks "a field's declared type names a struct of this module whose
    receiver is a frame", which is how `self.in1.total()` gets its nested frame
    placed; asked about a parameter it is the same question with the same
    answer, and it is the evidence for `other.start` in
    `Slice.__eq__(self, other: Self)`.

    It is a DECLARATION, and that is a different kind of evidence from the call
    site the holder fixpoint follows, in the way the caller needs to know: a
    declared type names the LAYOUT the callee was written against, so it holds
    at every call site whether or not this image contains one, whereas a word
    travelling into a parameter says what ONE call site passed.  So the two
    disagreeing is not a contradiction to be resolved by preferring one, it is
    the thing to refuse — which is the caller's job, not this function's.

    `owner` is the struct whose method `fn` is, and is what a bare `Self`
    reduces to (`annotation_base_name`'s `self_type`); it is None for a plain
    function, where `Self` names nothing.

    Every doubtful case answers None and so seeds nothing: no annotation at all,
    a name that is not a struct of this module, a starred parameter (`*args` is
    a TUPLE of the type, one word here, and a frame address is not what the
    declaration promises), and a name that has more than one spelling.
    """
    shape = function_param_shape(fn)
    starred = {n for n in (shape.vararg, shape.kwarg) if n}
    self_type = getattr(owner, "name", None) or None
    out = {}
    for pname, ann in shape.fixed:
        if not pname or pname in starred or pname in out:
            continue
        base = annotation_base_name(ann, self_type=self_type)
        st = decls.get(base) if base else None
        if st is not None:
            out[pname] = st
    return out




# ── What STRUCT does an expression name ───────────────────────────────────
#
# Dispatch on this path is by NAME: a method call is lifted to `S_m(recv, …)`
# from the method name alone, and a one-word struct's sole field IS its
# receiver.  Both need the same missing fact — which struct a receiver
# expression denotes — and there was no reader for it, so every consumer grew
# its own recogniser and `formal/build.py`'s `_receiver_shape_refusal` was
# left to refuse `bs[0].get()` with a message asking for a predicate nobody had
# built — which is what `FORMAL_method_call_on_a_subscripted_receiver`
# recorded, and which this function is the answer to, so that doc is deleted.
#
# The predicate is here, in the shared model, because it is asked by a build
# pass (the lift), by the frame analysis (which must agree about when a
# receiver's type is known, or the two refuse the same program for different
# reasons) and by both backends.  ONE answer, and every doubtful case answers
# None.

CONTAINER_TYPE_NAMES = ("List", "list", "StaticList", "Tuple", "tuple",
                        "Set", "set", "InlineStaticList", "Array", "array")




# ── calling through a VALUE: a function value is a code address ────────────
#
# The construct `std/algorithm/backend/tile.mojo` is refused for, and the four
# shapes it takes on this path.  One value is one 64-bit word with a home in a
# register, a spill slot, a receiver's frame or a folded module constant
# (`pointer_value_model`), and the word a FUNCTION value holds is a CODE ADDRESS
# — which is a perfectly good word, and the only thing it needs is something to
# materialize it and something to branch through it.  `encode_blr_xn` has been in
# `formal/arm64.py` since the beginning with no caller, and `encode_lea_r64_rip`
# is how a string literal's address reaches a register, so neither backend is
# missing a piece of machinery; what was missing was the DECISION, and it is
# here so the two machines cannot answer one construct differently:
#
#   `param_annotation`             — what the caller DECLARED about that word;
#   `value_callee_can_hold_a_function` / `value_call_bracket_reading` — the two
#                                     decisions the declaration settles;
#   `callee_value_refusal`, `value_bracket_reading_refusal`,
#   `value_call_keyword_refusal`, `function_value_argument_refusal` — the four
#                                     sentences for the shapes with no answer;
#   `function_value_refusal`       — a function with no code in this image.
#
# All eight live in THIS section rather than beside the caller that happens to
# reach them first, which is the only property here a 30,000-line file can lose:
# a construct whose readers are scattered is a construct whose readers disagree,
# and the two tables in `test_refusal_taxonomy.py` exist because that has
# happened.
#
# **What is still refused, and it is a real boundary rather than a remainder.**
# The word is an address, and this build does not prove the word IS an address:
# a program that calls a value holding a non-address traps at run time where it
# used to be refused at build time.  What this path cannot do is decide that
# soundly without a whole-module dataflow over every value the callee might
# have been handed — the callee cannot see its call sites, and the call sites
# cannot see the callee's body across a dylib boundary — so the check that is
# cheap and local is done and the rest is named rather than implied:
# (function value calls — fixed).

# Types this path SUBSCRIPTS.  A value of one of these answers `x[i]` with an
# element, which is the reading a bracketed callee has to be told apart from;
# everything else that is a type at all cannot be indexed, so a bracket on it
# says specialization and says it by deduction rather than by guess.
SUBSCRIPTABLE_TYPE_NAMES = tuple(
    dict.fromkeys(CONTAINER_TYPE_NAMES
                  + ("String", "StringRef", "StringLiteral", "SIMD",
                     "SIMDVector", "StaticTuple")))


def param_annotation(fn, name: str) -> str | None:
    """The declared type of `fn`'s parameter `name`, or None.

    None is not "untyped" alone — it is every case the reader cannot reduce,
    including a parameter this function does not have, so a caller asking this
    about a local always gets None and must not read that as a fact about the
    local's type.  `annotation_base_name` is the reducer, so the decorations
    (`inout`, `out`, `borrowed`, a trailing `?`) and `Self` are its problem and
    not this one's; a FUNCTION-typed declaration reduces to None, which is why
    `value_call_bracket_reading` looks at the raw text for it.
    """
    for p in (getattr(fn, "params", None) or []):
        pname = p[0] if isinstance(p, (list, tuple)) else getattr(p, "name", None)
        if pname != name:
            continue
        ann = p[1] if isinstance(p, (list, tuple)) and len(p) > 1 \
            else getattr(p, "annotation", None)
        return ann if isinstance(ann, str) and ann.strip() else None
    # A BRACKET parameter is a parameter too, and it is a different list: the
    # runtime parameter list above is `params`, and `def f[T: AnyType, keys:
    # List[T]](base: Int)` has `keys` in neither it nor anywhere else the old
    # parse kept -- the bracket block recorded the NAME and the default and threw
    # the TYPE away. Measured: `len(keys)` in such a body was refused with "the
    # source does not say what this operand holds" while `keys[0]` in the same
    # body lowered, so two readers of one word consulted different evidence.
    # `fire_compiler.py`'s `comptime_param_annotations` is where the annotation
    # is kept now; this is the one reader of it.
    ann = (getattr(fn, "comptime_param_annotations", None) or {}).get(name)
    return ann if isinstance(ann, str) and ann.strip() else None


def _outer_annotation_base(ann) -> str | None:
    """The bare name an annotation's OUTERMOST type names, or None.

    `annotation_base_name` cannot be this reader, and the reason is one line of
    that function: it answers None for any annotation containing a `(`, because
    a function-typed declaration names no struct — which is the right answer for
    ITS question and the wrong one here, because the question is what the
    annotation is made OF rather than what struct it is.  `Some[def[width:
    Int](Int) -> Int]` — the same construct spelled with the function type
    inline instead of through an alias — is an `Optional` of a function, and
    `annotation_base_name` says None about it.

    So this reads the outermost application directly, and it does NOT reuse
    `_strip_type_decorations` for the same reason it does not reuse
    `annotation_base_name`: that function returns None for any annotation
    holding a `(`, which is exactly the spelling this has to answer. The
    decorations are the same TABLE — one list, read here in the one place that
    needs it — and a `Self` with no `self_type` is left as the name `Self`,
    which no caller below claims anything from.
    """
    if not isinstance(ann, str) or not ann.strip():
        return None
    text = ann.strip()
    changed = True
    while changed:
        changed = False
        for deco in _TYPE_DECORATIONS:
            if text.startswith(deco) and text[len(deco):len(deco) + 1] in (" ", "["):
                text = text[len(deco):].strip()
                changed = True
    if not text:
        return None
    if text.startswith("def") or text.startswith("fn"):
        return "def"
    m = re.match(r"([A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*)", text)
    if not m:
        return None
    rest = text[m.end():].lstrip()
    if rest and not rest.startswith("["):
        return None
    return m.group(1).split(".")[0]


def declared_param_kind(fn, name: str, int_names=(), string_names=(),
                        dtype_names=(), float_names=()):
    """The kind a PARAMETER's own declaration gives for `name`, or None.

    **The one reader of "what does this name hold" that reads the DECLARATION**,
    and it exists because two readers that could answer were consulting
    different evidence and one of them had nothing at all:

      * `keys[0]` where the parameter is `keys: List[T]` lowers, because the
        subscript's base classifier reads the annotation;
      * `len(keys)` over the SAME parameter was refused with "the source does
        not say what this operand holds" — on a declaration that says it in the
        parameter list. Measured, both architectures:
        `def total[T: AnyType, keys: List[T]](base: Int) -> Int: return base +
        len(keys)` was refused with that sentence while `keys[0]` in the same
        body built and answered CPython.

    Two answers to the same question about the same word is the defect this
    repository has already paid for twice in this area, and the cost of a
    mismatch is a WRONG answer rather than a refusal whenever the first reading
    is the wrong one. So the reader is here, in the shared model, and both
    backends' `kind_of_slot` hooks ask it rather than each deciding.

    **`fn` is a FunctionDef and `name` must be one of ITS parameters.** That is
    the whole scope, and it is narrower than "any name in the function" on
    purpose: `param_annotation` returns None for a name the signature does not
    bind, and a LOCAL's declaration is a different question with its own reader
    (`optional_local_declared_annotation`, and the flow the emitter records). A
    name that is a parameter of a DIFFERENT function must not borrow that
    function's annotation.

    `None` is the answer for everything this path has no representation for, so
    an annotation naming a struct, a function type or an `Optional` leaves the
    pre-existing unclassified refusal exactly as it was — this widens what can
    be ANSWERED and never what is answered differently."""
    ann = param_annotation(fn, name)
    if not ann:
        return None
    return declared_type_kind(ann, int_names, string_names, None,
                              dtype_names=dtype_names, float_names=float_names)


def callee_value_refusal(name: str, fn, spelling: str = None,
                         ann=None) -> str:
    """The refusal for calling a name the calling function binds, when the
    build can see the word is not a function.

    ARCH-FREE, asked by BOTH backends from `_emit_call` beside
    `specialization_call_refusal` and for the same reason: one construct, one
    language implementation, one answer.

    `name` is a parameter or a local of `fn` (`callee_is_a_bound_value` is the
    reader that decides it), so the call goes THROUGH A VALUE — and a function
    value IS a word on this path now, its code address, so the question this
    function answers is not whether a value can be called but whether **this**
    value can be. `ann` is the parameter's declared type
    (`param_annotation`), and `value_callee_can_hold_a_function` is what
    decides: a container this path subscripts and a scalar cannot hold a code
    address, so `drain(f: List[Int])` calling `f(0)` is a program whose own
    declaration refutes it, and it is refused HERE rather than turned into a
    branch through whatever word the container held.

    **What this is not, and the sentence it replaced said the opposite.** It
    used to read "this path has no representation for a function value", and
    that was true when a function name had nowhere to live and `func(i)` had
    nowhere to branch. Both are answered now — a function name is an
    `ADRP`+`ADD` from its entry label (each backend's `_load_var`), and a call
    through a word is one `BLR` (arm64) or `CALL r64` (x86-64), each backend's
    `_emit_call` — so keeping the old words would have been a refusal that says
    a thing which is no longer true, on the construct it was written for.

    `spelling` is what the SOURCE wrote and `name` is what `_callee_symbol`
    flattened it to, and they are two names in the message when they differ
    because a refusal that names the base of `c.f` while the reader is looking
    at `c.f` sends them to the wrong line for the same reason the `no home`
    message does. `member_chain_text` is the reader for it, for the reason its
    own docstring gives.

    **The measured alternative is an image that cannot be loaded.** With the
    extern path taking the call, `map(size, func)` emitted a branch against a
    symbol spelled `func`, and the file built before the bind audit caught it —
    which is one verdict (`not-answerable/unresolved-extern`, a fact about the
    target) standing where another belongs (a codegen gap in this file, in the
    coverage denominator)."""
    where = ((getattr(fn, "name", None) or "this function")
             if fn is not None else "this function")
    subject = (f"`{name}`" if not spelling or spelling == name
               else f"`{spelling}`, which flattens to the base name `{name}`,")
    declared = (f" and it is declared `{ann.strip()}`" if isinstance(ann, str)
                and ann.strip() else "")
    return (
        f"{subject} is a call through a VALUE rather than through a function "
        f"of this unit \u2014 `{name}` is a name {where} binds, a parameter or "
        f"a local of it{declared}, and a word that is not a code address is "
        f"nothing to branch through. A formal value is one 64-bit word with a "
        f"home in a register, a spill slot, a receiver's frame or a folded "
        f"module constant; calling one is a branch to whatever that word is, so "
        f"a callee this build can see cannot hold a function is refused here "
        f"instead of at run time. Take what the operation DOES rather than the "
        f"operation \u2014 `apply(size, kind: Int)` with one arm per operation "
        f"is the same program with a representation \u2014 or declare the "
        f"parameter as the function type and pass the function of this unit "
        f"whose address it will hold"
    )


def function_value_argument_refusal(name: str, callee: str, param: str,
                                    ann, reader: str = None) -> str:
    """Why a function name cannot be passed where the callee declares something
    that cannot hold one.

    Arch-free, and asked from `formal/build.py`'s name-placement walk — the one
    pass that has both ends of the call in hand at once, which is the only place
    this question CAN be asked: the callee cannot see its call sites and a call
    site without a declaration cannot know the parameter.

    `call2(dbl, 5)` with `def call2(f: Int, a: Int): return f + a` is the
    program, and it is a build error in Mojo and CPython. Emitted here it would
    be `address_of_dbl + 5` — a number nobody wrote, with exit 0, and nothing on
    the link line to catch it, which is the failure
    `no_public_api_reason`'s own docstring calls trading a build error for a
    run-time wrong answer.

    Only the bare `dbl(x)` spelling reaches this, because that is the only one
    where the argument is DEFINITIONALLY a code address; a computed argument is
    a word of unknown provenance and is named in
    (function value call checks) rather than
    refused here, where the answer would be a sentence about a program this
    check cannot see.
    """
    who = f" in {reader}" if reader else ""
    declared = (f"declared `{ann.strip()}`" if isinstance(ann, str)
                and ann.strip() else "not a type a function can go into")
    return (
        f"{name!r} is a FUNCTION of this image read as a value, and it is "
        f"passed to `{callee}()`{who} as parameter `{param}`, which is "
        f"{declared}. A function value is a code ADDRESS — one 64-bit word, "
        f"the entry point of `{name}` — and a word of that kind is not an "
        f"arithmetic operand, a container or a number, so the callee would "
        f"compute with an address and answer a number the source never wrote. "
        f"Declare `{param}` as the function type and CALL it, or pass the "
        f"function's RESULT instead of the function"
    )


def value_bracket_reading_refusal(name: str, fn, ann=None) -> str:
    """Why a bracketed callee through a value cannot be read either way.

    Arch-free, and asked by both backends from `_emit_call` beside
    `value_call_keyword_refusal`. The bracket on a value is genuinely two
    constructs — a specialization's comptime parameters, or an index — and only
    the parameter's declared type separates them
    (`value_call_bracket_reading`). This is the refusal for the shapes that
    type does not separate, and it is a refusal rather than a guess in both
    directions: reading an index as a specialization passes an element as a
    leading argument to the wrong word, and reading a specialization as an index
    would subscript a value that cannot be subscripted.

    The advice is the annotation, because that is what the stdlib already
    writes for this construct — `workgroup_function: Some[Static1DTileUnitFunc]`
    in `std/algorithm/backend/tile.mojo` is what makes its own brackets a
    specialization — and a BARE `func(i)` needs no annotation at all, which is
    why this refusal is about the bracketed spelling alone.
    """
    where = getattr(fn, "name", None) if fn is not None else None
    where = where or "this function"
    declared = (f" It is declared `{ann.strip()}`" if isinstance(ann, str)
                and ann.strip() else " It is not declared at all.")
    return (
        f"`{name}[…](…)` is a bracketed call through a VALUE, and a "
        f"bracket on a value is two constructs: the comptime parameters of a "
        f"specialization, or an index into a container. This build separates "
        f"them from the callee's DECLARED type, because that is the only thing "
        f"that can, and `{name}` does not declare one this path can read."
        f"{declared} A parameter declared `Some[…]` or as a `def[…](…) "
        f"-> …` function type cannot be indexed, so a bracket on one is a "
        f"specialization and is passed as leading arguments; a `List`/a "
        f"`String` can only be indexed, so its brackets are an index and an "
        f"element is not callable here. Annotate the parameter, or write the "
        f"call without brackets (`{name}(…)`), which is the same program "
        f"on this path: a comptime parameter is an ordinary leading argument"
    )


def value_callee_can_hold_a_function(ann) -> bool:
    """True unless `ann` says the parameter CANNOT be holding a function.

    The one soundness check this construct can afford, and it is deliberately
    small: it reads the caller's own DECLARATION and refuses the two declared
    types that cannot hold a code address — a container this path subscripts
    and a scalar.  `workgroup_function: Some[Static1DTileUnitFunc]` passes
    (an `Optional` of a function), an UNANNOTATED `func` passes (a function
    value is the most likely thing an untyped parameter holds, and
    `stdlib/std/algorithm/backend/cpu/map.mojo`'s is one), and `f: List[Int]`
    does not.

    What it cannot do is the other direction — proving the value IS an address,
    which needs a whole-module dataflow and is named in
    (function value call checks) rather
    than implied here.
    """
    base = _outer_annotation_base(ann)
    if base is None:
        return True
    if base in SUBSCRIPTABLE_TYPE_NAMES:
        return False
    return not (base in POINTEE_WIDTHS
                or type_constructor_kind(base) is not None)


def value_call_bracket_reading(fn, name: str, ann) -> str:
    """`"specialization"` or `""` (refuse) for `name[a, b](…)` through a value.
    A bracket on a VALUE is genuinely ambiguous and the ambiguity is the whole
    difficulty of this construct, so the answer is read off the one fact the
    caller stated: the parameter's declared type.

      * a type this path SUBSCRIPTS (`List[Int]`, `String`, …) — the bracket is
        an INDEX.  `f[0](x)` with `f` a list of functions is a call of the
        element, and reading the bracket as a specialization would pass `0` as a
        leading argument to the wrong word;
      * a SCALAR (`Int`, `bool`, `DType`) — neither.  A specialization of an
        `Int` is not a program, so the bracket cannot be the index and the
        program is wrong; refused rather than turned into a branch through a
        number;
      * `Some[F]` / `Optional[F]`, or the function type itself — an OPTIONAL of
        a function, or the function.  **Neither can be subscripted on this
        path**, so the bracket cannot be an index and the only reading left is
        the specialization.  That is
        `std/algorithm/backend/tile.mojo`'s `workgroup_function:
        Some[Static1DTileUnitFunc]`, and it is a DEDUCTION from the annotation
        rather than a pattern match on the file;

        the bare function type arrives here as the spelling `def ... -> R`,
        because the parser does not keep a function-typed parameter's own
        parameter list (`('f', 'def ... -> Int')` is what it hands this
        reader).  **So the annotation cannot say how MANY brackets the
        specialization has**, and nothing here checks: `f[2, 5](x)` and
        `f[2](x)` are both "a specialization" as far as this decision goes, and
        both pass what they were given as leading arguments.  That is the same
        unagreed direction as everything else here, and it is the callee's own
        parameter list that would have to disagree for it to be wrong — which is
        a program whose two ends disagree, answered by passing what the call
        site wrote;
      * anything else — an alias this build cannot resolve, a struct, an
        UNANNOTATED parameter — `""`, and the caller refuses.

    The unannotated case is the one a reader will hit, because this corpus is
    full of `def apply(size, func)` (`stdlib/std/algorithm/backend/cpu/map.mojo`
    is exactly that) and the honest answer for a BARE `func(i)` is still yes:
    there is no bracket to read.  Only the bracketed spelling needs the
    annotation, and the refusal says so.
    """
    base = _outer_annotation_base(ann)
    if base is None:
        return ""
    if base in SUBSCRIPTABLE_TYPE_NAMES:
        return ""
    if base in POINTEE_WIDTHS or type_constructor_kind(base) is not None:
        return ""
    if base in ("Some", "Optional", "def"):
        return "specialization"
    # A struct of this module is not subscriptable either, but the emitter is
    # handed `structs` by each backend and this reader is not — so a struct
    # falls to the ambiguous answer rather than being answered by a table that
    # would have to be handed the whole unit to be right.
    return ""


def value_call_keyword_refusal(spelling: str, what: str) -> str:
    """Why a KEYWORD (or a keyword bracket) cannot be bound through a value.

    Arch-free and asked by both backends, because the construct is one and the
    two must not invent different defaults for it.  A keyword names a PARAMETER,
    and a callee reached through a value has no declaration here, so there is no
    parameter to name: `f(width=3)` and `f[width=3](x)` would have to be bound
    positionally against a list nobody has, which is how a defaulted parameter
    silently receives the wrong word.  Passed positionally, both are one program
    with a representation.
    """
    return (
        f"`{spelling}` is {what} a call through a VALUE, and this path has no "
        f"declaration to bind it by NAME: a callee reached through a word is "
        f"read as taking the arguments the call site writes, in order, and a "
        f"keyword — or a keyword item in the specialization bracket — names a "
        f"parameter this build cannot enumerate, so binding it would mean "
        f"inventing one. Write the argument positionally (`{spelling}` with the "
        f"words in bracket order), which is the same program on this path: a "
        f"comptime parameter is an ordinary leading argument and a default "
        f"parameter is filled by its declaration, and neither has a declaration "
        f"here"
    )




# ── Is the WORD a call branches through a code ADDRESS?  The decidable half ──
#
# A function value on this path is a CODE ADDRESS (`_load_var`'s last home in
# both backends), so `f(i)` through a word is one `BLR` / `CALL r64` and every
# word that is not an address is a branch to whatever those bits say.  Measured
# on both architectures before any of this existed, for the four shapes below
# and no others:
#
#     def apply(size: Int, f):            # the callee
#         var t = 0
#         var i = 0
#         while i < size:
#             t += f(i)
#             i += 1
#         return t
#     def main(n: Int) -> Int32:
#         return apply(3, 17)              # arm64 SIGBUS (138), x86-64 SIGSEGV (139)
#
# …and `formal/build.py`'s function-value pre-pass already refuses the OTHER
# direction — a function NAME handed to a parameter declared `Int` — because
# there the value is definitionally an address.  `bugs/
# (function value calls bug — fixed)
# the whole of the residual, and it is right that closing it in general is a
# whole-module dataflow: the callee cannot see its call sites and the call sites
# cannot see the callee's body across a dylib boundary.
#
# What is in here is that document's own two halves, restricted to the part each
# reader can DECIDE, and it is the same restriction the two existing checks
# already make: refuse on EVIDENCE, say nothing on silence.  The two halves are
# the two ends of one call, which is why they are two readers and ONE message:
#
#   * the CALLING end (`callee_word_is_not_an_address`) — every statement of the
#     calling function that binds the callee name writes something that cannot
#     be an address.  `ValueKinds` already decides that, flow-insensitively and
#     with unanimity, and a name it cannot decide is not in `locals` at all, so
#     the reader has no new imprecision to introduce;
#   * the PASSING end (`value_argument_is_not_an_address`) — the callee CALLS
#     that parameter through a word (`parameters_called_through_a_value`) and
#     the argument expression is, from its own shape, not an address.  This end
#     is asked from `formal/build.py`'s name-placement walk because that is the
#     only pass holding both ends of a call at once, which is the same reason
#     `function_value_argument_refusal` is raised there.
#
# Both are permissive on silence and loud on evidence, and that is the whole of
# the direction: the cost of a wrong answer here is a program that traps
# instead of being refused, so every rule below has to be one the SOURCE
# contradicts rather than one the analysis failed to follow.

# The kinds that cannot hold a code address, and the list is deliberately
# CLOSED rather than "any kind this file knows".  A new kind added to the value
# model is a decision about how a value PRINTS or how a container LAYS OUT, and
# neither says anything about being a branch target; admitting one by omission
# would make every future kind a silent trap.  `None` — "the source does not
# say" — is outside the list for the same reason and is the answer that keeps
# every uncertain call exactly where it was.
#
# A container is here for the reason it is a blob and not a number: a list's
# word is the ADDRESS OF ITS BLOB, and the code of this image is in a different
# segment from the frame and the heap, so branching to a container is branching
# to a header word.  `is_list_kind` rather than a spelling, so a byte blob and
# a list of lists are both in it without a second list.
CODE_ADDRESSLESS_KINDS = frozenset({
    INT_KIND, STR_KIND, FLOAT_KIND, TYPE_KIND, FRAME_KIND,
})


def kind_cannot_hold_a_code_address(kind) -> bool:
    """Whether a value of this KIND is provably not a function's entry address.

    One predicate for both halves above and both architectures, so the four
    questions the callers actually ask ("is this callee name's word an
    address", "is this argument's word an address") cannot be answered by four
    private copies that drift.  `None` answers False — the permissive direction,
    and the one that matters, because a wrong True here refuses a program that
    works and a wrong False emits a branch to a number.
    """
    if kind is None:
        return False
    return kind in CODE_ADDRESSLESS_KINDS or is_list_kind(kind)


def parameters_called_through_a_value(fn) -> set:
    """The parameters of `fn` its own body CALLS through the word.

    The predicate half of the passing end, and it is asked of a `FunctionDef`
    rather than of a call because the question belongs to the CALLEE: whether a
    parameter is ever branched through is a fact about the body that receives
    it, and a reader at the call site would have to re-derive it once per call
    site — which is how two call sites of one function come to disagree about
    whether the parameter is callable.

    Deliberately narrow about what counts as "calls it": `call_callee_name`, the
    ONE recogniser of a call's name, and only a name `fn` binds.  So `f(i)` and
    `f[2, 5](i)` — the bare and the specialized spelling, the second of which is
    `stdlib/std/algorithm/backend/tile.mojo`'s whole construct — both count, and
    `recv.f(i)`, a method call, does not: that is a dispatch on a receiver, and
    `sole_field_call_refusal` is the reader for the value-in-a-field shape
    rather than this one.  A name merely READ (`t = f`) is not a call and does
    not count, which is the difference between this and
    `callee_is_a_bound_value`'s question and the reason the two cannot be one
    function.
    """
    bound = set()
    for p in (getattr(fn, "params", None) or []):
        pname = p[0] if isinstance(p, (list, tuple)) else getattr(p, "name", None)
        if isinstance(pname, str):
            bound.add(pname)
    out = set()
    for call in iter_nodes(getattr(fn, "body", None) or []):
        if not isinstance(call, F.CallExpr):
            continue
        name = call_callee_name(call.func)
        if name in bound:
            out.add(name)
    return out


def functions_calling_a_parameter_through_a_value(functions: list) -> dict:
    """`{function name: {the parameters its body branches through}}`, per unit.

    The unit-level table for `parameters_called_through_a_value`, and the reason
    it exists is arithmetic rather than semantics: that reader walks a body, and
    `formal/build.py`'s name-placement walk already holds one loop over every
    call of every function, so asking it per CALL SITE would walk the same body
    once per call of that callee. A file with a hundred call sites of one
    helper would walk its body a hundred times.

    One entry per function and not one per `(callee, parameter)` because every
    use here is a membership test — "is this parameter one this callee branches
    through" — and the pair would have to be built again at every call site. It
    is computed once per unit for the same reason
    `functions_returning_containers` is: the answer is the same for every call
    site of a callee.

    **Transitive:** if a function passes a parameter to another function in a
    position that function calls through (directly or transitively), that
    parameter is also counted as called through a value.
    """
    by_name = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if name:
            by_name.setdefault(name, []).append(fn)

    # Start with direct calls
    out = {}
    for fn in functions or ():
        name = getattr(fn, "name", None)
        if not name:
            continue
        called = parameters_called_through_a_value(fn)
        if called:
            out[name] = set(called)

    # Fixpoint for transitive propagation
    changed = True
    while changed:
        changed = False
        for caller in functions or ():
            caller_name = getattr(caller, "name", None)
            if not caller_name:
                continue
            caller_params = set()
            for p in (getattr(caller, "params", None) or []):
                pname = p[0] if isinstance(p, (list, tuple)) else getattr(p, "name", None)
                if isinstance(pname, str):
                    caller_params.add(pname)
            # Find which params of caller are called through transitively
            caller_called = out.get(caller_name) or set()
            if not caller_called:
                continue
            # Look for calls where caller passes one of its called-through params
            for call in iter_nodes(getattr(caller, "body", None) or []):
                if not isinstance(call, F.CallExpr):
                    continue
                if isinstance(call.func, F.SubscriptExpr):
                    continue
                cname = call_callee_name(call.func)
                if cname is None or cname not in by_name:
                    continue
                callee_defs_list = by_name[cname]
                # Get positional param names for callee
                try:
                    shape = function_param_shape(callee_defs_list[0]) if callee_defs_list else None
                except Exception:
                    shape = None
                if not shape:
                    continue
                callee_positional = list(getattr(shape, "positional", []) or [])
                # Try to bind args
                try:
                    slots, _dropped, _err = bind_call_arguments(cname, callee_defs_list[0],
                                                               call.args or [], call.kwargs or [])
                except Exception:
                    continue
                if slots is None:
                    continue
                # Check each arg
                for i, (pname_callee, value) in enumerate(zip(callee_positional, slots)):
                    if pname_callee not in (out.get(cname) or set()):
                        continue
                    if not isinstance(value, F.IdentExpr):
                        continue
                    if value.name in caller_called and value.name in caller_params:
                        # caller passes a param that's called through transitively
                        # to a callee that calls through that position
                        if value.name not in (out.get(caller_name) or set()):
                            if caller_name not in out:
                                out[caller_name] = set()
                            out[caller_name].add(value.name)
                            changed = True

    # Convert sets to frozensets
    result = {}
    for k, v in out.items():
        if v:
            result[k] = frozenset(v)
    return result


def _binding_values(fn, name: str) -> list:
    """What every statement of `fn` that binds `name` writes into it.

    The sites of the bug doc's own list — "an assignment, an augmented
    assignment, a loop target, a `with … as`, a container store, a `return`" —
    read as EXPRESSIONS where the source states one and as `None` where it does
    not, and the `None` is the point rather than a gap in the walk:

      * a bare `f = 17` states the value, so the site carries `17`;
      * a `f = g` where `g` is an unannotated PARAMETER states nothing, because
        `ValueKinds` seeds an unannotated parameter as a word and a word is an
        integer here (its own header).  That is the leak this function exists to
        stop: `test_formal_specialization.py`'s `via_local` is `var g = f;
        return g(x, 100)`, the CORRECT program, and a reader that asked
        `ValueKinds` alone refused it;
      * an UNPACK target (`a, b = t`), a loop target, a `with … as`, and an
        augmented assignment all write a word this reader cannot state.  A loop
        target in particular binds an ELEMENT, and an element can be a function
        — a list of them is `map.mojo`'s own shape — so "the iterable is a
        container" says nothing about the element.

    **A write THROUGH a name is a different question from a write OF it, and
    this walk now records the two separately** (`_container_element_writes`
    below, one walk and two lists, so the two readers cannot disagree about
    which is which). Before it did not, and the asymmetry was a defect in both
    directions rather than a gap in one:

      * a SUBSCRIPT STORE (`xs[0] = v`, `d["k"] = v`) writes an ELEMENT of the
        container the name holds and does not rebind the name, so recording it
        as a binding made `caller_local_element_holds` claim unanimity over a
        literal whose element the source had since REPLACED — a FALSE REFUSAL of
        `xs = [10, 20, 30]; xs[0] = dbl; …xs[0]`, measured on both
        architectures, where CPython runs it;
      * an `APPEND` (`xs.append(v)`) writes an element the walk could not see at
        all, so `xs = []; xs.append(17); …xs[0]` had no stated element and the
        build emitted the image anyway — measured SIGBUS 138 on arm64 and SIGSEGV
        139 on x86-64 where CPython raises `TypeError`.

    Both are sites of the ELEMENT question and neither is a site of the VALUE
    question, which is why they are one walk returning two lists rather than two
    walks: the same disagreement this function's own paragraph warns about, in
    the only place the shapes are visible.

    `iter_nodes` rather than a second statement walk, for the reason every
    shared walk in this file is shared: the shapes that bind a name are
    `mojo/middle/boundnames.py`'s to own, and a private copy is how a 1-tuple
    target and a parenthesised name came to be indistinguishable.  What is read
    here is the TARGET — `fire_compiler.for_target_names`, the parser's own
    representation reader — and nothing about the walk itself.

    **The walk is `_binding_sites_index`'s and this function is its one-name
    reader**, so the two cannot disagree about which statements bind a name and
    the index is paid for once per function rather than once per name — the
    cost that decided it, with the measurement, is in that function's docstring.

    **The residual is stated rather than implied**: a site shape this walk does
    not name is a site this walk does not see, and a name bound at one of those
    and at an integer elsewhere would be refused on the strength of the integer
    alone.  That is the conservative direction (the program would trap on the
    integer path anyway), it is the same imprecision `formal/build.py`'s
    `_names_bound_in` documents about the allocator's own table, and the caller
    below requires the value model's UNANIMITY as well, which is what catches
    the disagreement rather than the missed shape.

    One shape this walk deliberately does NOT record, and it is a gap rather than
    an answer: **a name a function declares `global` is bound by the MODULE's
    statement, not by this function's**, and this walk only ever saw the
    function's. `_global_slot_value` is what closes that from the slot table
    rather than from a second walk of the module body, for the reason every other
    reader of a module global in this file reads the table: the table is where
    the module-level binding's shape ended up, so a name asked about twice gets
    one answer.
    """
    return list(_binding_sites_index(fn).get(name) or ())


def _binding_sites_index(fn) -> dict:
    """`{name: [site, …]}` — every name `fn` binds, and what each site writes.

    **One walk for the whole function, which is the whole point, and `_binding_values`
    is the one-name reader over this table.** It was a walk PER NAME, so a reader
    that follows a chain of names paid O(names × body) on a module with many
    locals: measured on `formal/hostmods/os/__init__.mojo`, arm64,
    `fire.py build --formal --no-prove` went 2.19 s → 2.72 s with the per-name
    walk and 2.24 s with this one (best of three each), and the standard this is
    measured against is the 2026-10-03 build-cost measurement's (doc in git history) — where the two
    residues left open were 0.094 s and 0.003 s on the largest file in the
    repository, and both were declined rather than taken.  There is one dispatch
    below and `_binding_values` reads it, so the two cannot disagree about which
    statements bind a name — the failure `_binding_values`'s own docstring names.

    Cached on `fn` beside `_declared_annotations`'s own cache and for its reason:
    the AST is fixed by the time any of this runs, so the answer cannot change,
    and every caller would otherwise re-derive the same table.
    """
    cached = getattr(fn, "_binding_sites_index", None)
    if cached is not None:
        return cached
    out: dict = {}

    def add(name, site):
        if name:
            out.setdefault(name, []).append(site)

    for node in iter_nodes(getattr(fn, "body", None) or []):
        if isinstance(node, F.AssignStmt):
            for name in _sole_target_leaf(node.target):
                add(name, node.value)
        elif isinstance(node, F.MultiAssignStmt):
            for target in node.targets or ():
                for name in _sole_target_leaf(target):
                    add(name, node.value)
        elif isinstance(node, F.AugAssignStmt):
            # `f += 1` writes `f + 1`, so what lands in the name depends on what
            # was there — the one site whose result no single expression states.
            for name in _target_leaves(node.target):
                add(name, None)
        elif isinstance(node, F.VarDecl):
            add(node.name, node.value)
        elif isinstance(node, (F.ForStmt, F.ComptimeForStmt, F.Comprehension)):
            for name in _target_leaves(getattr(node, "target", None)):
                add(name, None)
        elif isinstance(node, F.WithStmt):
            for item in node.items or ():
                for name in _target_leaves(getattr(item, "alias", None)):
                    add(name, None)
        elif isinstance(node, getattr(F, "TryStmt", object)):
            try:
                for h in getattr(node, "handlers", None) or []:
                    name = getattr(h, "name", None) or getattr(h, "exc_name", None)
                    if isinstance(name, str):
                        add(name, None)
                    elif name is not None:
                        for n in _target_leaves(name):
                            add(n, None)
            except Exception:
                pass
        elif isinstance(node, getattr(F, "ExceptHandler", object)):
            try:
                name = getattr(node, "name", None) or getattr(node, "exc_name", None)
                if isinstance(name, str):
                    add(name, None)
                elif name is not None:
                    for n in _target_leaves(name):
                        add(n, None)
            except Exception:
                pass
        elif isinstance(node, getattr(F, "MatchStmt", object)):
            try:
                for case in getattr(node, "cases", None) or []:
                    try:
                        if hasattr(case, "pattern"):
                            for n in _target_leaves(case.pattern):
                                add(n, None)
                        # also try pattern bindings
                        pats = getattr(case, "patterns", None)
                        if pats:
                            for p in pats:
                                for n in _target_leaves(p):
                                    add(n, None)
                    except Exception:
                        continue
            except Exception:
                pass
    fn._binding_sites_index = out
    return out


def _resolve_local_alias_to_function(fn, name: str, defined_set):
    """Resolve a local alias `name` in `fn` to function names defined in this image.

    Looks through all assignments/initializations of `name` and returns
    function names from `defined_set` that it is bound to. If any binding
    is unknown/unresolvable or binds to something that isn't a known function,
    return empty set (conservative) to avoid false positives.
    """
    if fn is None or not name or not defined_set:
        return set()
    try:
        sites = _syntactic_write_values(fn, name)
    except Exception:
        return set()
    if not sites or any(v is None for v in sites):
        return set()
    resolved = set()
    for v in sites:
        if isinstance(v, F.IdentExpr):
            vname = getattr(v, "name", None)
            if isinstance(vname, str) and vname in defined_set:
                resolved.add(vname)
                continue
        # If it's assigned from something else that's also a local alias,
        # try to resolve recursively (conservative depth limit)
        if isinstance(v, F.IdentExpr):
            vname = getattr(v, "name", None)
            if isinstance(vname, str):
                # Avoid cycles by checking simple case
                try:
                    sub = _resolve_local_alias_to_function(fn, vname, defined_set)
                    if sub:
                        resolved |= sub
                        continue
                except Exception:
                    pass
        return set()
    return resolved if resolved else set()


def _sole_target_leaf(target) -> list:
    """`[name]` when the target binds exactly one name, else `[]`.

    A target that binds SEVERAL names binds ELEMENTS, so the whole value is not
    what any one of them receives and the site is undecided — which is why the
    unpack case records nothing rather than recording the container. That was
    `_one_target_site`'s rule asked one name at a time, and it is gone with the
    per-name walk rather than left beside the index as a second copy of the same
    test.
    """
    leaves = _target_leaves(target)
    return leaves if len(leaves) == 1 else []


class _ElementWrite(NamedTuple):
    """One value a statement stores into a container a name holds.

    `index` is the subscript's index or key NODE when the source spells it as a
    literal and `None` when it is computed — `xs[i] = v` and `xs["k"] = v` say
    where they land and `xs[n] = v` does not, and that difference is the whole
    of the precision below. `value` is the value written, or `None` where this
    walk cannot state one (an augmented store, an `append` of several arguments,
    a `del`, which removes an element rather than writing one).

    `appends` and `removes` are the two writes that change where a LATER
    `append` lands, and nothing else does: an `append` adds an element at the
    end and a `del` removes one. They are separate fields rather than one
    `shifts` because only the first of them is excludable by the length
    argument — a `del` makes the count shorter, which is the direction that
    argues FOR including an `append`, so a reader that treated the two alike
    would exclude an `append` a `del` had moved into range.
    """
    index: object
    value: object
    appends: bool
    removes: bool



def _container_element_writes(fn, name: str) -> list:
    """Every value a statement of `fn` stores as an ELEMENT of `name`.

    The other half of `_binding_values`, and it answers the other of the two
    questions: `xs[0] = v` and `xs.append(v)` write into the container a name
    holds without rebinding the name, so the value question has nothing to learn
    from them and the ELEMENT question cannot proceed without them. Before this
    existed the walk recorded neither, and both mistakes were measurable on both
    architectures:

      * the MISSING append built and trapped (`xs = []; xs.append(17)` has no
        stated element, so the element reader said nothing and the image went
        out) — SIGBUS 138 on arm64, SIGSEGV 139 on x86-64, where CPython raises
        `TypeError: 'int' object is not callable`;
      * the SUBSCRIPT STORE recorded as if it bound the name produced a FALSE
        REFUSAL of `xs = [10, 20, 30]; xs[0] = dbl; … xs[0]`, which CPython runs
        and which this path used to build as well.

    An `append` whose receiver is a SUBSCRIPT or an attribute (`fs[0].append(v)`,
    `d["k"].append(v)`) is recorded as an unstated write rather than as its
    argument: this walk cannot see which container the receiver names, and a
    wrong container would be a refusal of a program that is correct.

    `extend` is the same shape with a LIST argument rather than a single value
    and is deliberately absent: it is not in `BUILTIN_VALUE_METHODS`, so no
    emitter lowers it, and a reader that answered for a shape no backend has
    would be answering about a program that cannot be built at all.
    """
    out: list = []
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
            value = getattr(node, "value", None)
            for target in _subscript_targets(getattr(node, "target", None)):
                if not _names_container(target.obj, name):
                    continue
                out.append(_ElementWrite(
                    target.index, None if isinstance(node, F.AugAssignStmt)
                    else value, False, False))
        elif isinstance(node, F.DelStmt):
            for target in _subscript_targets(
                    [t for t in (getattr(node, "targets", None) or ())]):
                if not _names_container(target.obj, name):
                    continue
                # `del xs[i]` REMOVES an element, which is why it is its own
                # flag: the next `append` lands one position earlier than it
                # otherwise would, so the length argument that excludes an
                # `append` does not apply while one of these is in the function.
                out.append(_ElementWrite(target.index, None, False, True))
        elif isinstance(node, F.ExprStmt):
            call = getattr(node, "value", None)
            if not isinstance(call, F.CallExpr):
                continue
            func = getattr(call, "func", None)
            if not isinstance(func, F.MemberExpr) or func.member != "append":
                continue
            if not _names_container(func.obj, name):
                continue
            args = list(getattr(call, "args", None) or ())
            out.append(_ElementWrite(None, args[0] if len(args) == 1 else None,
                                     True, False))
    return out


def _subscript_targets(target) -> list:
    """Every `SubscriptExpr` inside a binding target, at any nesting depth.

    `xs[0] = v` and `(a, d["k"]) = t` are the same shape at two depths, and the
    walk is over `iter_nodes` rather than over one level of the target precisely
    so the depth is not something a second reader has to agree about.
    """
    return [n for n in iter_nodes([target])
            if isinstance(n, F.SubscriptExpr)
            and not isinstance(getattr(n, "index", None), F.SliceExpr)]


def _names_container(obj, name: str) -> bool:
    """Whether `obj` is the bare name `name` — and only the bare name.

    A subscript or attribute receiver is deliberately `False`: `fs[0].append(v)`
    stores into a container this walk cannot name, and treating it as a store
    into `fs` would be a refusal of a program whose elements are elsewhere.
    """
    return isinstance(obj, F.IdentExpr) and obj.name == name


def _literal_index_value(node):
    """The value of a subscript index the source spells as a literal, else None.

    One reader for both containers, because both answers are the same question —
    "did the source say which one" — and two readers would be two places for the
    sequence and the mapping spellings to drift on it. `IntLiteral` and
    `StringLiteral` are the only two that can, and a computed index is the
    whole-set case the caller handles.
    """
    if isinstance(node, F.IntLiteral):
        return ("seq", node.value)
    if isinstance(node, F.StringLiteral):
        return ("dict", node.value)
    return None


def _global_slot_value(fn, name: str):
    """The value the MODULE binds a `global name`, when this function says so.

    The one write site of a module global that is not in the function that reads
    it, and it is asked of the SLOT TABLE rather than by walking the module body
    again: `GlobalSlot.site` is the module-level statement itself, so this reads
    the source rather than the words the linker laid out, which is the reason
    `global_slot_kind` gives for reading the same table.

    `None` for every function that does not declare the name `global`, and for a
    declared name the module does not publish a slot for — a slot the table does
    not have is a binding this walk cannot see, which is silence and not an
    answer. The `GlobalStmt` itself is what makes the question askable: without
    it a name that merely shares a module global's spelling is a local, and
    asking the table about it would answer for a name it does not bind.
    """
    from .module import declared_global_names
    if name not in declared_global_names(fn):
        return None
    slot = module_slot(name)
    if slot is None:
        return None
    return getattr(slot.site, "value", None)


def _target_leaves(target) -> list:
    """The NAMES a binding target binds, through the parser's own reader."""
    try:
        return [n.lstrip("*").strip() for n in F.for_target_names(target)]
    except Exception:
        return []


# The shapes whose ELEMENT is a value the container itself was not: a subscript
# of a container LITERAL and a subscript of a module-level name the slot says is
# a container.  A subscript of an ordinary NAME is deliberately absent — `d[k]`
# on a dict can hand back a function and `xs[i]` on a list cannot, and nothing
# about the spelling says which, so the narrow reading is the only honest one.
def _element_of_a_literal_container(arg) -> bool:
    if not isinstance(arg, F.SubscriptExpr) or isinstance(arg.index,
                                                          F.SliceExpr):
        return False
    obj = arg.obj
    if isinstance(obj, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr,
                        F.StringLiteral)):
        return True
    if isinstance(obj, F.IdentExpr):
        # `global_slot_kind` rather than a table of this function's own: a
        # module global's value's shape is stated at module level and a use site
        # has nothing else to go on, which is that reader's own stated reason
        # for existing.
        return is_list_kind(global_slot_kind(obj.name))
    return False


def value_argument_is_not_an_address(arg, caller=None, _asked=frozenset()) -> str | None:
    """What the argument's OWN SHAPE says it holds, when that is not an address.

    The PASSING end of the section's subject, asked from
    `formal/build.py`'s name-placement walk — the one pass that has the callee
    and the call site at once — and asked only when `parameters_called_through_a
    _value` has already said the callee BRANCHES through this parameter.  Without
    that conjunct the check would refuse `f(17)` for every `f`, which is the
    ordinary program; with it, it refuses exactly the program that traps.

    Every rule is one the source CONTRADICTS, and the set is small on purpose:

      * a literal of any kind — an integer, a string, a double, `True`;
      * a container literal, and a subscript OF a container literal (an element
        is a word the container was holding, never the container);
      * arithmetic over either of those, which is the same word computed, and a
        comparison, which is `0`/`1`;
      * a TYPE read as a value — one 64-bit tag, and `type_value_name` is the
        one reader of that, so this asks the same function both backends' member
        arms ask;
* a PARAMETER of the CALLER whose own declaration cannot hold a function,
        which is `value_callee_can_hold_a_function` again — the same reader the
        calling end asks about the callee, so the two ends of one call cannot
        disagree about what its declaration means. The same declaration decides
        a subscript of that parameter, whose element is a word the container was
        holding;
      * a LOCAL of the CALLER whose every syntactic write site states something
        this same function refuses as an address, which is `caller_local_holds`
        — the two ends of one call then read the SAME reader and the SAME
        unanimity rule, and the calling end's own two-legged structure (the
        value model plus every write site) has its counterpart here in one leg
        because `formal/build.py` has no `ValueKinds`.

    What is deliberately NOT here, because each would be a guess rather than a
    contradiction: a subscript of a NAME whose container the walk cannot see
    (`d[k]` on a dict can hand back a function and `xs[i]` on a list cannot, and
    nothing about the spelling says which — `caller_local_holds` narrows that to
    a name whose every binding is a container LITERAL, which is the one case
    where the element is decidable); and anything whose kind is undecided.
    Silence claims nothing, so a missed case is the residual the bug doc names
    and never a false refusal.
    """
    if arg is None:
        return None
    kind = _kind_of_simple(arg)
    if kind is not None:
        return {INT_KIND: "an integer", STR_KIND: "a string",
                FLOAT_KIND: "a double", TYPE_KIND: "a type tag"}.get(
                    kind, f"a value of kind {kind}")
    if isinstance(arg, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr)):
        return "a container"
    if _element_of_a_literal_container(arg):
        return "an element read out of a container"
    if isinstance(arg, F.UnaryOp):
        return value_argument_is_not_an_address(arg.operand, caller, _asked)
    if isinstance(arg, F.BinaryOp):
        # `and`/`or` HAND BACK ONE OF THEIR SIDES, so one side being a number
        # says nothing about the other; every other operator computes.  A
        # comparison is `0`/`1` by definition, which is why it is named rather
        # than left to the operands.
        if arg.op in ("and", "or"):
            left = value_argument_is_not_an_address(arg.left, caller, _asked)
            right = value_argument_is_not_an_address(arg.right, caller, _asked)
            return left if left and right else None
        if arg.op in _COMPARISON_OPS:
            return "the result of a comparison"
        return (value_argument_is_not_an_address(arg.left, caller, _asked)
                or value_argument_is_not_an_address(arg.right, caller, _asked))
    if isinstance(arg, F.CompareChain):
        return "the result of a comparison"
    if isinstance(arg, F.SubscriptExpr) and caller is not None:
        base = arg.obj
        if isinstance(base, F.IdentExpr) and not isinstance(
                arg.index, F.SliceExpr):
            ann = param_annotation(caller, base.name)
            if ann and not value_callee_can_hold_a_function(ann):
                return f"an element read out of `{ann.strip()}`"
            element = caller_local_element_holds(caller, base.name, arg.index,
                                                _asked)
            if element is not None:
                return element
    if isinstance(arg, F.IdentExpr) and caller is not None:
        ann = param_annotation(caller, arg.name)
        if ann and not value_callee_can_hold_a_function(ann):
            return f"a value declared `{ann.strip()}`"
        holds = caller_local_holds(caller, arg.name, _asked)
        if holds is not None:
            return holds
    return None


def _syntactic_write_values(fn, name: str) -> list:
    """Every value a statement of `fn` writes into `name`, UNDECIDED sites kept.

    `_binding_values`, which is the one walk of these shapes, with the
    distinction its sites already make preserved: an `AugAssignStmt`, an
    unpack target, a loop target and a `with … as` write a word nothing in the
    source states, and `_binding_values` records `None` for exactly those. A
    `None` here is therefore "this walk cannot say", which is the answer that
    makes a reader below stay silent — the permissive direction, and the same
    one `callee_word_is_not_an_address`'s own paragraph describes for the CALLING
    end's syntactic leg.

    **A `global` declaration contributes the MODULE's binding of the name** (see
    `_global_slot_value`), and it contributes it as a SITE rather than replacing
    the function's own writes, so `global g; g = compute()` still asks the
    unanimity question over both rather than answering from whichever came
    first. Before this existed the function's own writes were the only sites, so
    a name bound ONLY at module level had no site at all — measured: `var g = 17`
    with `global g` in `main` and `g` passed to a function that calls it through
    a value built on both architectures and died of SIGSEGV, where CPython raises
    `TypeError`.

    Named separately so both readers of it (the value's own reader and the
    element's) ask the same walk: two walks over the same shapes is how a name
    two statements disagree about becomes a refusal in one reader and a pass in
    the other.
    """
    if not name:
        return []
    sites = _binding_values(fn, name)
    module_site = _global_slot_value(fn, name)
    if module_site is not None:
        sites.append(module_site)
    return sites


def caller_local_holds(fn, name: str, _asked=frozenset()) -> str | None:
    """What a LOCAL of `fn` holds, when every site that writes it says so.

    The PASSING end's half for an argument the caller BOUND rather than spelled,
    which is the residual
    (fixed) names as
    `apply_arg(3, xs[0])` — measured on that tree as still building and still
    trapping, with `xs` a local list.

    **It asks UNANIMITY over the write sites and needs no value-model table**,
    which is what makes it usable from `formal/build.py`: the CALLING end can
    afford to want two kinds of evidence because each backend already holds a
    `ValueKinds`, and this pass holds none. So the rule is the one that needs
    only the SOURCE:

      * every syntactic write site of the name must state a value this module's
        own `value_argument_is_not_an_address` refuses as an address, and
      * there must be at least one such site, so a name with no write here (a
        parameter, a module global, a name this walk does not see) is silence
        rather than a vacuous agreement.

    A `None` site — an augmented assignment, an unpack target, a loop target, a
    `with … as`, exactly the shapes `_binding_values` documents — is a site this
    walk cannot state, and one of them makes the answer silence. That is the
    conservative direction and it is the one the doc's own list of residual site
    shapes gives as the reason a MISSED write is worse than a missed warning:
    this reader cannot claim a name is a number when a statement writes a word
    it does not understand.

    **What this deliberately cannot see**, and it is the same limit
    `_binding_values` states rather than a new one: a write from a function this
    unit does not compile (`helper()` returns nothing in particular — a caller
    that binds `g = mk()` has no answer here), and a name the walk does not bind
    at all. Both are silence.

    **`_asked` is a CYCLE guard and it is not optional.** This reader, the
    element reader and `value_argument_is_not_an_address` are mutually
    recursive — asking what `xs[0]` holds asks what each of the elements holds,
    which asks what those names hold — so `var a = b` and `var b = a` in one
    function is a loop with no base case. Measured over this repository's corpus
    (every `.py` and `.mojo`, the reader driven with the
    `parameters_called_through_a_value` conjunct dropped): `RecursionError` on
    real files, before this guard. The key is the `(function, name)` QUESTION
    rather than the function alone, because asking two different names of one
    function is not a cycle, and re-asking one is: a question already on the
    stack has no smaller instance of itself to reduce to, so the answer is
    silence — which is this reader's answer for everything it cannot see.
    """
    if (id(fn), name) in _asked:
        return None
    asked = _asked | {(id(fn), name)}
    sites = _syntactic_write_values(fn, name)
    if not sites or any(v is None for v in sites):
        return None
    phrases = {value_argument_is_not_an_address(v, fn, asked) for v in sites}
    if None in phrases:
        # A site whose value is an ordinary local or a call states nothing this
        # reader can use, which is silence and not agreement.
        return None
    if len(phrases) != 1:
        # Two sites that state DIFFERENT non-address kinds (`g = 1` and
        # `g = "s"`) are still not an address, so this names the one thing they
        # agree on rather than picking a kind.
        return "a local of this function that no statement writes an address into"
    # The phrase is the KIND, not a sentence about how it was established: the
    # message already says which end of the call the build stopped at, and it
    # quotes `holds` twice, so a clause about unanimity would be read twice too.
    # The unanimity is this reader's own precondition and belongs in its
    # docstring rather than in the reader's output.
    return phrases.pop()


def caller_local_element_holds(fn, name: str, index=None,
                             _asked=frozenset()) -> str | None:
    """What `name[i]` holds, when the walk can see every value it can hold.

    The element case, and it is narrower than the value case on purpose. An
    element of a container can be a function — a list of them is
    `std/collections/map.mojo`'s own shape — so `xs[i]` on a list is not an
    answer in general. What IS an answer is the one case where the walk can see
    every value the subscript could ever hand back: **every element the name
    holds comes from a container LITERAL or from a store this walk can see, and
    every such value is itself something `value_argument_is_not_an_address`
    refuses as an address.** Then the element is one of those values and the
    answer follows.

    **The sites are the literals PLUS the writes THROUGH the name**
    (`_container_element_writes`), which is what makes the rule above true
    rather than nearly true. Reading only the literals was wrong in both
    directions, and both were measured on both architectures:

      * `xs = []; xs.append(17)` states no element in any literal, so the reader
        was silent, the build emitted the image, and it died of SIGBUS 138 on
        arm64 / SIGSEGV 139 on x86-64 — CPython raises `TypeError: 'int' object
        is not callable`;
      * `xs = [10, 20, 30]; xs[0] = dbl` — a correct program, run by CPython —
        was REFUSED, because the walk saw only the literal and did not know the
        source had replaced element 0 with a function. Its dict spelling
        (`d = {"k": 17}; d["k"] = dbl`) was not refused at all, so the two
        spellings of one shape got two answers.

    A DICT literal is one of the literals because its VALUES are what a subscript
    hands back and they are as visible as a list's elements: `d["k"]` on
    `{"k": 17}` is 17, and `d[k]` on `{"k": 17}` is 17 or a `KeyError`, never a
    function. That is the answer (fixed).
    called missing ("a subscript of a DICT name … which no spelling
    distinguishes from a list") — no spelling of the SUBSCRIPT distinguishes
    them, but the spelling of the BINDING does, and that is what this reader
    reads.

    **`index` narrows the question to the element the source NAMED, and it is
    what keeps a correct program out of the refusal.** With no index the reader
    has to hold that EVERY element of the container is a non-address, which is
    right and is silence the moment one of them is a function — `xs = [10, 20];
    xs.append(dbl); xs[0]` cannot be answered, because the reader cannot see
    that the `append` lands at index 2 and `xs[0]` is still the `10`. With an
    index of `0` it can: the literal's element at 0 is a candidate, the `append`
    is not one (see below), and the answer is "an integer". The rule for
    excluding an `append` is stated where it is used because it is the one place
    this reader reasons about POSITION rather than about values.

    A name bound to a literal-shaped site this reader cannot read, and a name
    with any store the walk cannot attribute (`fs[0].append(v)`, an `append` of
    several arguments, an augmented store), are silence rather than wrong: this
    reader cannot claim a name is a number when a statement writes a word it does
    not understand. `_asked` is the same CYCLE guard `caller_local_holds`
    documents, carried through the same mutual recursion.
    """
    if (id(fn), name) in _asked:
        return None
    asked = _asked | {(id(fn), name)}
    sites = _syntactic_write_values(fn, name)
    if not sites:
        return None
    # `(which container, its elements)` per binding site, in the walk's order.
    literals: list = []
    for site in sites:
        if isinstance(site, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            literals.append(("seq", list(site.elements or ())))
        elif isinstance(site, F.DictExpr):
            # The VALUES, not the keys: `d[k]` hands back a value, and the count
            # word the blob carries is the pair count either way.
            literals.append(("dict", [(k, v) for (k, v) in (site.pairs or ())]))
        else:
            # A loop target, a subscript store of something that is not a
            # container literal — every shape whose elements the source does not
            # state in one place.
            return None
    writes = _container_element_writes(fn, name)
    # NOT `asked`: that is the cycle guard, and reusing the name here
    # overwrote the guard with this None on every computed index.
    at = _literal_index_value(index)
    candidates = (_elements_at(literals, writes, at) if at is not None
                  else _every_element(literals, writes))
    if not candidates:
        # `xs = []` states no element, so there is nothing to have read one out
        # of and nothing to answer — unless an `append` added one, which is why
        # the walk above is asked before this test and not after it.
        return None
    phrases = {value_argument_is_not_an_address(e, fn, asked)
               for e in candidates}
    if None in phrases:
        # A value this walk cannot classify is EXACTLY the case this reader
        # exists to be right about: `[dbl, dbl]` is a list of addresses and
        # `xs[0]` is one, and `[dbl, 17]` is a list whose element 0 is one. So
        # an unclassified candidate makes the answer silence and never agreement.
        return None
    if len(phrases) != 1:
        return None
    return "an element read out of a container literal"


def _every_element(literals: list, writes: list) -> list:
    """Every value the container can hold, for a subscript the source did not
    narrow to one element.

    The whole-container question, and the reason it is the whole container is
    that `xs[i]` with a computed `i` can read any of them — which is why
    `_literal_index_value` returning `None` is not a smaller answer but a
    different one.
    """
    out: list = []
    for container, elements in literals:
        out += ([v for (_k, v) in elements] if container == "dict"
                else list(elements))
    out += [w.value for w in writes]
    return out


def _elements_at(literals: list, writes: list, asked) -> list:
    """The values a subscript naming `asked` (`("seq", i)` / `("dict", k)`) can
    hand back.

    Three sources, and the third is the only one that needs a position argument:

      * the element (or the value under that key) of every literal that HAS
        one — a literal too short states nothing about that position, which is
        silence rather than an out-of-range answer this path has no message for;
      * every store whose own index is either the one asked for or COMPUTED,
        because a computed index could have landed there. A store whose index is
        a different LITERAL is excluded: it says where it went;
      * every `append`, unless the literals rule it out. **The rule:** an
        `append` lands at the element after the last one, so it cannot be at
        position `i` if EVERY literal binding of the name holds MORE than `i`
        elements. `xs = [10, 20]; xs.append(dbl)` with `xs[0]` is that case and
        is measured (it built and trapped before this existed); `xs = []` with
        `xs.append(17)` and `xs[0]` is not, because the empty literal holds no
        more than 0 elements and the append is element 0 — which is exactly the
        program that used to trap. A `del` disables the rule outright, because
        it removes an element and so moves every later `append` one place
        earlier than any literal states.

    A `dict` has no positions, so the `append` rule is sequence-only and a dict
    subscript excludes appends outright — `d.append(v)` is not a dict operation
    on this path at all.
    """
    kind, key = asked
    out: list = []
    for container, elements in literals:
        if container != kind:
            continue
        if kind == "dict":
            out += [v for (k, v) in elements
                    if _literal_index_value(k) == asked]
        elif isinstance(key, int) and -len(elements) <= key < len(elements):
            out.append(elements[key])
    for w in writes:
        if w.removes or not w.appends:
            # A `del` at the position asked, or a computed `del`, is a removal
            # this reader cannot price; a plain store is a candidate when its
            # own index is the one asked for or could have been it.
            if w.removes and _literal_index_value(w.index) != asked:
                continue
            if w.index is None or _literal_index_value(w.index) == asked:
                out.append(w.value)
    if any(w.appends for w in writes) and not _appends_cannot_reach(
            kind, key, literals, writes):
        out += [w.value for w in writes if w.appends]
    return out


def _appends_cannot_reach(kind, key, literals: list, writes: list) -> bool:
    """Whether no `append` can land at the position a subscript named.

    True only when the name is a SEQUENCE, the key is an integer position, some
    literal binding holds an element at that position, and EVERY literal binding
    of that container holds more elements than the position — so the count an
    `append` sees is at least one past it. A `del` makes it False outright: it
    removes an element, so the count afterwards is one lower than the literals
    say and the argument no longer holds. A binding this reader could not read
    never reaches here — its site is not a literal, and the reader has already
    answered None.
    """
    if kind != "seq" or not isinstance(key, int):
        return False
    if any(w.removes for w in writes):
        return False
    lengths = [len(e) for container, e in literals if container == "seq"]
    return bool(lengths) and all(n > key for n in lengths)



def callee_word_is_not_an_address(fn, name: str, vkinds=None) -> str | None:
    """What the calling function's own statements say the callee WORD holds.

    The CALLING end of the section's subject, asked from both backends at the
    line that has already decided the call goes through a value, and it returns
    a PHRASE (`"an integer"`, `"a container"`) or None rather than a boolean
    because the phrase is what the one message needs and a boolean here would
    mean each backend composing its own sentence out of a kind string — the same
    drift `callee_value_refusal` and its x86-64 reader exist to prevent.

    **It takes TWO kinds of evidence and needs both**, and neither alone is
    right, which is what `_binding_values`'s own paragraph is about:

      * the VALUE MODEL's agreed kind (`vkinds.locals[name]`), which is the walk
        that sees every statement and records a name two statements disagree
        about as undecidable — the completeness leg;
      * every SYNTACTIC write site, which is the leg that stops the model
        propagating its own default.  `ValueKinds` seeds an unannotated
        parameter as an integer, so `var g = f` inside a function that received
        `f` is an integer as far as the model is concerned, and
        `test_formal_specialization.py`'s `via_local` — `var g = f; return
        g(x, 100)`, the correct program and this construct's own positive row —
        was refused by the model alone, measured on both architectures before
        this conjunct was added.

    Two guards, and each of them is a case that would otherwise be a false
    refusal rather than a wrong answer:

      * **a PARAMETER is not asked about.**  Same default, one level out: the
        declaration is the evidence for a parameter, and
        `value_callee_can_hold_a_function` is the reader that already has it;
      * **an UNANNOTATED parameter stays permissive** for the same reason, so
        the only parameter case this can reach is one the declaration already
        refuses.

    `vkinds` is the caller's own `ValueKinds` and `None` means "no answer",
    which is the permissive direction: a caller that has not built one yet
    behaves exactly as it did before this reader existed.
    """
    if vkinds is None or not name:
        return None
    if name in {p[0] if isinstance(p, (list, tuple)) else p
                for p in _param_list(fn)}:
        return None
    kind = (vkinds.locals or {}).get(name)
    if not kind_cannot_hold_a_code_address(kind):
        return None
    binding_sites = _binding_values(fn, name)
    # If we cannot see binding sites, we cannot establish agreement - be permissive
    if not binding_sites:
        return None
    for value in binding_sites:
        if value_argument_is_not_an_address(value, fn) is None:
            return None
    if is_list_kind(kind):
        return "a container"
    return {INT_KIND: "an integer", STR_KIND: "a string",
            FLOAT_KIND: "a double", TYPE_KIND: "a type tag",
            FRAME_KIND: "a frame address"}.get(kind, f"a value of kind {kind}")


def not_a_code_address_refusal(spelling: str, holds: str, where: str = None,
                               passed: str = None) -> str:
    """The one message for a call through a word the source says is not code.

    ONE function for both ends of the analysis, and the reason is that they are
    one construct: the same word, read by two passes because each holds one end
    of the call.  Two messages would be two families in
    `test_refusal_taxonomy.py` and two causes in `tools/formal_sweep_causes.py`
    for a defect a sweep would report as one, and the sweep's row is what a
    planner reads.

    `passed` is what makes it the passing end rather than the calling one, and
    it is a CLAUSE rather than a separate sentence: "`17`, passed to `apply()`
    as parameter `f`, which apply() calls through a value".  The wording
    discipline is `string_concat_refusal`'s and `returnless_value_refusal`'s:
    name the construct, say what CPython answers, say what this path would have
    done (with the measurement), and say what to do instead.  A reader told only
    "not an address" has no way to know which of the two ends the build stopped
    at, and the fix is different at each.
    """
    where = f"{where}: " if where else ""
    clause = (f", {passed}" if passed else
              f", and every statement of the function that binds it writes "
              f"that")
    return (
        f"{where}`{spelling}` is called as a FUNCTION and the source says it "
        f"holds {holds}{clause} — a formal value is one 64-bit word, and a "
        f"function value is the ADDRESS of a function's entry, so there is no "
        f"instruction at a number the program wrote as {holds}. CPython raises "
        f"`TypeError` on this program, and this path used to build it, branch "
        f"to whatever the word was, and die of SIGBUS on arm64 / SIGSEGV on "
        f"x86-64 (measured, both architectures). Refused at build time "
        f"instead. Pass a FUNCTION — a name of this unit, whose value is its "
        f"address — or declare the parameter with the function type, and take "
        f"what the operation DOES rather than the operation (`apply(size, "
        f"kind: Int)` with one arm per operation is the same program with a "
        f"representation)"
    )


def list_element_structs(fn, structs_by_name: dict, decls: dict,
                         owner=None) -> dict:
    """`{name: ONE-FIELD struct}` for every name in `fn` holding a LIST of them.

    The SUBSCRIPT half of `receiver_struct`'s question — "which struct does
    `bs[0]` hold" — for the two spellings that state it:

      * a local bound to a container LITERAL of constructor calls, `var bs =
        [Box(), Box()]`.  The element type is the constructor's own declaration,
        and the calls must agree: a literal holding two different structs (or a
        constructor and an integer) claims nothing, which is `_kind_of_elements`'s
        unanimity rule applied to a stricter question — a name that could be two
        things is not a type;
      * a PARAMETER declared `List[Box]` — `annotation_type_arg_base` for the
        element, against `CONTAINER_TYPE_NAMES` for the container.  `List` with
        no argument declares no element and claims nothing, which is row 4 of
        the doc's table and the shape no pass over the source can answer.

    Only a ONE-FIELD struct is answered, and that restriction is what makes every
    answer sound rather than merely likely: the receiver of a one-field struct
    IS its field (`struct_fits_one_word`), so the element WORD of the blob is the
    struct and `bs[0].get()` can be lifted to `Box_get(bs[0])` with the element
    word as the receiver.  A multi-field struct in a container is a frame address
    in a container with no layout for it, which is refused by name and loudly
    (`wide_receiver_by_reference_refusal`), so answering it here would replace a
    true refusal with a wrong answer.

    The first spelling wins over the second: a local that is assigned two
    different container literals claims nothing rather than taking whichever was
    seen last, because `ValueKinds` is deliberately flow-insensitive for the same
    reason and two readers of one set of bindings must not disagree.
    """
    out, seen_binding = {}, set()

    def _one_kind(elems):
        kinds = set()
        for el in (elems or []):
            if not isinstance(el, F.CallExpr) or not isinstance(el.func,
                                                               F.IdentExpr):
                return None
            st = (structs_by_name or {}).get(el.func.name)
            if st is None:
                return None
            kinds.add(st.name)
        return kinds.pop() if len(kinds) == 1 else None

    for node in iter_nodes(getattr(fn, "body", None)):
        target = value = None
        if isinstance(node, F.VarDecl):
            target, value = node.name, node.value
        elif isinstance(node, F.AssignStmt) and isinstance(node.target,
                                                           F.IdentExpr):
            target, value = node.target.name, node.value
        if not target or not isinstance(value, (F.ListExpr, F.TupleExpr,
                                                F.SetExpr)):
            continue
        if target in seen_binding:
            out.pop(target, None)
            continue
        seen_binding.add(target)
        name = _one_kind(value.elements)
        st = (structs_by_name or {}).get(name) if name else None
        if st is not None:
            out[target] = st
    self_type = getattr(owner, "name", None) or None
    shape = function_param_shape(fn)
    starred = {n for n in (shape.vararg, shape.kwarg) if n}
    for pname, ann in shape.fixed:
        if not pname or pname in starred or pname in out \
                or pname in seen_binding:
            continue
        if annotation_base_name(ann, self_type=self_type) \
                not in CONTAINER_TYPE_NAMES:
            continue
        elem = annotation_type_arg_base(ann, self_type=self_type)
        st = (structs_by_name or {}).get(elem) if elem else None
        if st is not None:
            out[pname] = st
    return {name: st for name, st in out.items()
            if struct_is_one_field(st)}


def receiver_struct(expr, fn, structs_by_name: dict, owner=None,
                    bound: dict = None, elems: dict = None, functions=None,
                    one_field: bool = True):
    """The ONE-FIELD struct `expr` denotes, or None when nothing says which.

    The receiver-type predicate, and it is ONE function for the reason
    `struct_frame_slot_candidates` is: two consumers asking "which struct does
    this receiver name" and answering differently is how the same program gets
    two verdicts.  The build pass lifts the call and the frame analysis then
    reads a parameter list it would not otherwise have had, so the two cannot
    disagree by construction — but only if they ask the same question, and this
    is where they ask it.

    Four sources, which is the census the deleted
    `FORMAL_method_call_on_a_subscripted_receiver` tabulated:

      * a SUBSCRIPT — `bs[0]`, `messages[i]`.  The element type of `elems`, which
        `list_element_structs` built from the two spellings that state one;
      * a CALL — `S()`, a call whose declared return type names a struct, or a
        METHOD call `recv.m(...)`, whose result type is the method's own `-> T`.
        The constructor's own declaration, for the second the callee's `-> T` out
        of `functions` read by `annotation_base_name`, and for the third
        `_method_call_result_struct`, which reads that `-> T` off the METHOD
        after establishing the receiver's struct — added 2026-10-04, and the
        refusal sentence `subscript_receiver_method_refusal` prints used to be
        false about `std/builtin/float_literal.mojo` because of it ("this path
        has no inference that answers which struct does `self.
        __int_literal__()` hold" — the return annotation answers exactly that);
      * a bare NAME — `self`, a parameter declared with a struct annotation, or a
        name bound to a constructor call (`bound`, which the caller already
        computed for the one-word field rewrite and passes in rather than
        recomputing: two walks of one set of bindings is two recognisers);
      * a FIELD — `self.mojo_value`, `Tensor.registry`.  The field's DECLARED
        type, read by `struct_field_declared_type`, which is the one reader of a
        declared type and so cannot answer differently from a field's own
        analysis.

    `bound` and `elems` are the caller's per-function tables; both default to
    None, which means "no evidence in hand from the caller" and not "empty",
    because the binding-derived sources have no other way to see the function's
    statements.  A caller that has the tables passes them; a caller with nothing
    gets the declaration-only sources, which are the ones that hold at every call
    site whether or not this image contains one.

    **The answer is a ONE-FIELD struct or nothing.**  `struct_is_one_field` is
    the gate every source passes through, and it is what lets a caller use the
    answer as a VALUE rather than as a name: the word `bs[0]` already holds is
    the struct, so `Box_get(bs[0], …)` passes the receiver this path would have
    passed for a local.  A multi-field struct's receiver is an address of a frame
    that belongs to the function which created it, which is a different lifetime
    and a different refusal, and this predicate does not speak for it.

    **`one_field=False` waives that gate, and exactly one caller needs it: the
    refusal that has to NAME the struct.**  `formal/build.py::
    _call_receiver_verdict` asks with the gate off, so a receiver whose type is
    a multi-field struct is refused with the sentence about the REPRESENTATION
    rather than with the one about a missing type — which would be false, since
    a parameter declared `Wide` says exactly which struct it is.  A caller that
    waives the gate takes on the gate's rule: what comes back is a NAME, not a
    value, and passing it as a receiver is the thing the gate exists to stop.
    """
    st = _receiver_struct_source(expr, fn, structs_by_name, owner, bound,
                                 elems, functions or {}, one_field)
    if st is None:
        return None
    return st if (not one_field or struct_is_one_field(st)) else None


def _receiver_struct_source(expr, fn, structs_by_name: dict, owner,
                            bound: dict, elems: dict, functions: dict,
                            one_field: bool = True):
    """The struct ONE source names, or None.  `receiver_struct`'s four rows."""
    structs_by_name = structs_by_name or {}
    bound = bound or {}
    self_name = getattr(owner, "receiver", None) or "self"
    if isinstance(expr, F.SubscriptExpr):
        base = expr.obj
        # `a.b[0]` — the element type of a field's value.  There is no table
        # for that (a field's list is not a name), so it claims nothing.
        return (elems or {}).get(base.name) if isinstance(base, F.IdentExpr) \
            else None
    if isinstance(expr, F.CallExpr):
        if isinstance(expr.func, F.MemberExpr):
            # `recv.m(...)` — a METHOD call, whose result type is the METHOD's
            # own `-> T`.  This is the row `formal/build.py::_call_receiver_target`
            # asks at the lift, and it is the same answer read one hop further
            # out: `self.__int_literal__().__int__()` (`std/builtin/
            # float_literal.mojo`) is `IntLiteral___int__(self.
            # __int_literal__())`, and the only fact that settles which
            # `___int__` it is — `__int__` is declared by `FloatLiteral` HERE and
            # by `IntLiteral` in another module, so the name alone picks the
            # wrong one — is the method's declared return type.
            return _method_call_result_struct(expr, fn, structs_by_name,
                                             owner, bound, elems, functions,
                                             one_field)
        if not isinstance(expr.func, F.IdentExpr):
            return None
        st = structs_by_name.get(expr.func.name)
        if st is not None:
            return st
        callee = functions.get(expr.func.name)
        ret = getattr(callee, "return_type", None)
        base = annotation_base_name(ret, self_type=getattr(owner, "name", None))
        return structs_by_name.get(base) if base else None
    if isinstance(expr, F.IdentExpr):
        st = bound.get(expr.name)
        if st is not None:
            return st
        if owner is not None and expr.name == self_name:
            return owner
        return parameter_declared_structs(fn, structs_by_name,
                                          owner).get(expr.name)
    if isinstance(expr, F.MemberExpr):
        holder, path = _single_field_chain(expr)
        if path is None:
            return None
        st = bound.get(holder)
        if st is None and owner is not None and holder == self_name:
            st = owner
        if st is None:
            return None
        base, _ann, _why, declared = struct_field_declared_type(st, path)
        return structs_by_name.get(base) if (declared and base) else None
    return None


def call_result_type_name(expr, fn, structs_by_name: dict, owner,
                          bound: dict, elems: dict, functions: dict,
                          one_field: bool = True) -> str:
    """The TYPE NAME `expr` evaluates to by its own declaration, or None.

    The ONE reader of a callee's declared `-> T`, and it is here rather than in
    the two rows that need it because they must not be able to disagree: the
    CALL row of `_receiver_struct_source` answers "which STRUCT", and a
    refusal needs "which NAME" as well — `formal/build.py::
    _call_receiver_verdict` asks this one to say `IntLiteral` out loud when the
    struct of that name is declared in another module and there is therefore no
    struct to lift to.  Two readers of one annotation is how one of them starts
    reporting a different type for the same call.

    Three spellings, all of them declarations rather than inferences:

      * a CONSTRUCTION `S()` names `S`;
      * a call to a function of this module — `mk()` — names whatever its `-> T`
        spells, or nothing when it declares none;
      * a METHOD call `recv.m(...)` names the method's `-> T`, and only once the
        receiver's own struct is settled AND the struct declares that method
        exactly once.  Two declarations of one method are two `-> T`s with
        nothing in the call saying which was meant, so the answer is None and
        not "the first one".

    `one_field` is `receiver_struct`'s own gate, passed through rather than
    re-derived: a caller that waived it to get a NAME for a multi-field
    receiver has to get that name from the same chain of hops, or the answer
    stops one step short of where the gate was waived.

    `None` is the answer for every doubtful case, which is what makes the
    caller's refusal safe to read: a name this prints is a name the source
    wrote.
    """
    if not isinstance(expr, F.CallExpr):
        return None
    if isinstance(expr.func, F.MemberExpr):
        recv = receiver_struct(expr.func.obj, fn, structs_by_name, owner, bound,
                               elems, functions, one_field)
        if recv is None:
            return None
        named = [m for m in struct_methods(recv)
                 if m.name == expr.func.member]
        if len(named) != 1:
            return None
        ret = getattr(named[0], "return_type", None)
        return annotation_base_name(ret, self_type=getattr(recv, "name", None))
    if not isinstance(expr.func, F.IdentExpr):
        return None
    if expr.func.name in (structs_by_name or {}):
        return expr.func.name
    callee = (functions or {}).get(expr.func.name)
    ret = getattr(callee, "return_type", None)
    return annotation_base_name(ret, self_type=getattr(owner, "name", None))


def _method_call_result_struct(call, fn, structs_by_name: dict, owner,
                               bound: dict, elems: dict, functions: dict,
                               one_field: bool = True):
    """The struct `recv.m(...)` returns, from the METHOD's own `-> T`, or None.

    The CALL row's method half, and it is asked by `receiver_struct` rather than
    by the build pass so the two cannot disagree about which receiver's type is
    established — the reason this predicate is one function at all.

    One line of work, and `call_result_type_name` is the line: a NAME this
    module declares is a struct here, and a NAME it does not is nothing to lift
    to.  Which is why `std/builtin/float_literal.mojo` still refuses, and why
    the sentence it gets says so — see `formal/build.py::CALL_RECEIVER_WHY`'s
    `other module` row and `_call_receiver_verdict`.

    `struct_methods` is the one reader of a struct's methods, so this cannot
    disagree with `_derived_overrides` about which struct declares what; the
    derived-struct hazard is checked by the LIFT (`formal/build.py::
    _call_receiver_target`), which is the place that acts on the answer, and
    checking it here as well would be two gates that can only ever agree.

    The two paragraphs above are `call_result_type_name`'s, and that function
    is where they now live: it reads the same annotations and answers with the
    NAME rather than the struct, which is what a refusal about a struct this
    module does not declare needs to print.
    """
    base = call_result_type_name(call, fn, structs_by_name, owner, bound, elems,
                                 functions, one_field)
    return (structs_by_name or {}).get(base) if base else None


def _single_field_chain(expr) -> tuple:
    """`(holder name, field)` for a ONE-LEVEL MemberExpr chain, else `("", None)`.

    `x.f` is a field of a name and this can answer it.  `x.f.g` is a field of a
    FIELD, whose holder is itself an expression with no declared type in reach,
    so it claims nothing rather than pretending the leaf's holder is `x` — the
    two would differ about a struct that nests one-field structs, which is the
    chain `_one_word_sole_field_chain` already walks and which this predicate
    does not duplicate.  A subscript anywhere in the chain claims nothing for
    the same reason.
    """
    if not isinstance(expr.obj, F.IdentExpr):
        return "", None
    return expr.obj.name, expr.member


def struct_field_declared_type(struct_def, name) -> tuple:
    """`(base_name, annotation, why, is_declared)` for a field's declaration.

    The ONE reading of a declared type, so a caller that wants to know what a
    field holds and a caller that wants to refuse a field cannot answer
    differently.

    `(None, None, why, False)` when the field is not declared here at all — a
    class that assigns its fields in `__init__`, or one whose storage is named
    by `__slots__` or by nothing but `self.<name>` reads in a method — and
    `(None, None, why, True)` when it is declared TWICE with two different
    annotations.  The second is a real disagreement and not a corner case: a
    class body that says `var p: Pointer` and is then handed an `Int` somewhere
    has two answers, and picking one is the whole class of bug this section is
    arranged to prevent.

    `is_declared` is carried rather than left to the caller to work out, because
    the two negative answers are different facts and only the first of them has
    a SECOND evidence source to try: `struct_field_type` falls back to the
    constructor spelling for a field that is not declared, and must not for one
    whose two declarations disagree — there is no better of the two to prefer,
    and an assignment spelling would turn a refusal naming both annotations into
    one naming neither.

    This function reads the DECLARATION and only the declaration; the
    constructor-assignment spelling (`struct_field_assigned_type`) is a second
    evidence source and the two are combined by `struct_field_type`, so a
    caller that wants a type and a caller that wants to see whether it was
    *declared* are not the same question.

    The `why` is returned rather than discarded because a reader of a refusal has
    to be able to see WHY a name was or was not treated as typed — that is the
    difference between a rule and a guess.
    """
    anns = []
    for field in struct_fields(struct_def):
        if struct_field_name(field) != name:
            continue
        for spelling in (getattr(field, "type_ann", None),
                         getattr(field.target, "type_ann", None)
                         if isinstance(field, F.AssignStmt) else None):
            if isinstance(spelling, str) and spelling.strip():
                if spelling not in anns:
                    anns.append(spelling)
    if not anns:
        return (None, None,
                f"{struct_def.name} does not declare {name!r}, so nothing here "
                f"says what the slot holds — a field named only by __slots__ or "
                f"only by a method's read of self.{name}, and one only ever "
                f"handed a value this path cannot type, are both that shape",
                False)
    if len(anns) > 1:
        return (None, None,
                f"{struct_def.name} declares {name!r} more than once and the "
                f"declarations disagree — {', '.join(map(repr, anns))} — so "
                f"there is no single answer, and one of them would be a guess",
                True)
    return (annotation_base_name(anns[0]), anns[0], None, True)


def struct_field_assigned_type(struct_def, name, decls: dict) -> tuple:
    """`(base_name, spelling, why)` for the type `__init__` ASSIGNS, or `(None, None, why)`.

    `decls` is `{name: StructDef}` for the structs THIS MODULE DECLARES, and it
    is required rather than optional because it is the gate: only a name it
    holds can become an answer, so a name it does not hold stays on the
    untyped side of `frame_field_type_candidates` exactly as it did before.

    The returned `spelling` is the constructed type's own name, which is
    deliberately the same shape a DECLARATION would have produced
    (`annotation_base_name` and every kind table downstream read it unchanged),
    so nothing after this function has to know there are two sources.

    TWO assignment shapes are RECOGNISED, and both are EVIDENCE, because both
    are stores this path PERFORMS.  `self.x = T()` and
    `self.x, self.y = T(), U()` are read through `_init_statement_field_stores`
    — one table, which the `__init__` inline itself emits from, so a type can
    only be read out of a store that is actually going to happen.
    `tools/procrun.py` writes the second
    (`self.limit, self._chunks, self._size = limit, [], 0`) and skipping it
    said "its __init__ does not assign it" about a field the `__init__` plainly
    assigns — the reader sent to look for an assignment two lines above the one
    they were looking at.

    It USED to be the case that the tuple form was recognised and then
    REFUSED as evidence, on the measured ground that a tuple store to a field
    was refused by name on x86-64 and accepted-and-dropped on arm64, where
    `self.p, self.q, self.r = 3, 4, 7` in an `__init__` built, ran, and
    computed 0.  Both of those are fixed (see
    `FORMAL_tuple_store_to_a_field`'s successor), so the band-aid's
    reason is gone and it was deleted rather than left to rot: with the store
    performed, a type read out of it is a type of a slot something WAS written
    to.  The shape facts that remain are about an AUGMENTED assignment, which
    is a read and a write and so still settles nothing.
    """
    # The SHAPE facts first, and they come first because they are about the
    # STORE while the inference below is about the VALUE.
    shape = _init_store_shape_refusal(struct_def, name)
    if shape is not None:
        return (None, None, shape)
    inferred = struct_init_field_types(struct_def, decls).get(name)
    if inferred is not None:
        base, spelling = inferred
        return (base, spelling, None)
    if not _init_field_assignments(struct_def).get(name):
        return (None, None, f"{struct_def.name} declares {name!r} nowhere and "
                            f"its __init__ never assigns it — a store in "
                            f"ANOTHER method does run, and a value is not a "
                            f"type")
    return (None, None, struct_init_field_type_why(struct_def, name, decls))


def _init_store_shape_refusal(struct_def, name) -> str | None:
    """Why the SHAPE of `__init__`'s store to `self.<name>` settles nothing.

    ONE shape remains, and it is kept apart from the type inference because it
    is about the store rather than the value: an AUGMENTED assignment is a read
    and a write, so what the slot holds afterwards depends on what was in it
    before, and the object under construction is at its CLASS-LEVEL default
    where the constructor's stores run rather than at whatever an earlier
    statement stored.

    The TUPLE store used to be the second shape here, refused as
    non-evidence on the measured ground that the emitters did not perform it
    (x86-64 by name, arm64 by dropping the store).  Both emitters lower it now
    and `init_body_stores` inlines it, so the reason is gone: this asks
    `_init_statement_field_stores` — the same table the inline emits from — and
    so a field's type can only be read out of a store that is going to happen.
    A statement that table DECLINES (a starred target, a nested group, a mixed
    target) contributes nothing here either, which is the absent answer and the
    safe direction: no type, so no nested frame placed and no frame diagnostic
    suppressed.

    `None` means the shape is fine and the question is the value's, which is
    `struct_init_field_types`'s to answer.
    """
    init = next((m for m in struct_methods(struct_def)
                 if m.name == "__init__"), None)
    if init is None:
        return (f"{struct_def.name} declares {name!r} nowhere and has no "
                f"__init__ at all, so nothing names its type")
    receivers = struct_receivers(struct_def)
    untyped = None
    for node in iter_nodes(getattr(init, "body", None)):
        if not isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
            continue
        how, _value = _assigned_value_for(node, name, receivers)
        if how == _STORE_AUGMENTED:
            untyped = (f"__init__ also does an augmented assignment to "
                       f"self.{name}, which is a read and a write and so says "
                       f"nothing about the type")
    return untyped


# The three shapes `_assigned_value_for` reports.  `_STORE_TUPLE` is gone: a
# tuple store to a field is a store this path performs, so it is a `_STORE_PLAIN`
# and the shape question is `_init_statement_field_stores`'s.
_STORE_ELSEWHERE = "elsewhere"
_STORE_PLAIN = "plain"
_STORE_AUGMENTED = "augmented"


def _assigned_value_for(node, name, receivers):
    """`(how, value)` for what `node` stores into `self.<name>`.

    `how` is one of the three `_STORE_*` names; `value` is the right-hand side
    for the one that has it.  A starred target (`self.a, *rest = …`) has no
    positional answer and a target that pairs a member with something else is
    not a per-field store, so both come back `_STORE_ELSEWHERE` and the field
    stays untyped — the absent answer, in the same direction.

    The tuple case asks `_init_statement_field_stores`, the table the emitter
    inlines from, so this cannot report a store the build will refuse.  That is
    what replaced `_STORE_TUPLE`: it existed because the two emitters used to
    DISAGREE about the tuple target — x86-64 refused it by name, arm64 lowered
    it and dropped the store — so a type read out of it would have been a type
    of a slot nothing wrote to.  Both lower it and `init_body_stores` inlines
    it now, so the disagreement is gone and so is the arm.
    """
    target = getattr(node, "target", None)
    if isinstance(target, F.MemberExpr):
        if not (isinstance(target.obj, F.IdentExpr)
                and target.obj.name in receivers and target.member == name):
            return (_STORE_ELSEWHERE, None)
        return ((_STORE_AUGMENTED, None) if isinstance(node, F.AugAssignStmt)
                else (_STORE_PLAIN, getattr(node, "value", None)))
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        for t, value in _init_statement_field_stores(node, receivers) or ():
            if t.member == name:
                return (_STORE_PLAIN, value)
    return (_STORE_ELSEWHERE, None)


def _constructed_struct_name(value, decls: dict):
    """The struct of THIS MODULE a `… = <expr>` value constructs, or None.

    Only the plain construction shape is read — a call whose callee is a bare
    name `decls` holds.  A subscripted callee (`List[Self.T]()`), an attribute
    callee (`other.Inner()`), a bare name, a literal and a container display all
    return None, and that is the conservative direction: a type this path has no
    StructDef for has no frame layout here, so nothing downstream could act on
    it even if it were named.
    """
    if not isinstance(value, F.CallExpr):
        return None
    callee = value.func
    if not isinstance(callee, F.IdentExpr):
        return None
    return callee.name if decls.get(callee.name) is not None else None


def struct_field_type(struct_def, name, decls=None) -> tuple:
    """`(base, spelling, evidence, why)` — a field's type, and WHERE it came from.

    The one place the two evidence sources are combined, so the decision
    (`frame_field_type_candidates`), the placement (`struct_nested_frame_fields`)
    and the diagnostic (`field_type_disagreement`) cannot answer differently
    about the same field.

    `evidence` is `"declared"`, `"assigned"`, or None, and it is carried rather
    than discarded because a message that says a class "declares" a field the
    class only ever assigns is a refusal with a reason that is not operating —
    the exact defect this section exists to prevent, one level down.

    A DECLARATION wins over an assignment, and not by preference: premise (B2)
    says the assignment does not execute, so the declaration is the better
    evidence about the word the slot actually holds.  The two are therefore not
    a disagreement, and cross-checking them would refuse correct code.  A
    declaration that is ITSELF a disagreement is not overridden either — that
    is the `is_declared` flag, and the reason for it is on
    `struct_field_declared_type`.
    """
    base, spelling, why, declared = struct_field_declared_type(struct_def, name)
    if declared:
        return (base, spelling, "declared" if base else None,
                None if base else why)
    if decls is None:
        return (None, None, None, why)
    assigned, spelling, why = struct_field_assigned_type(struct_def, name, decls)
    if assigned is None:
        return (None, None, None, why)
    return (assigned, spelling, "assigned", None)


def field_type_rows(structs, name, decls=None):
    """`[(struct_name, base, annotation, why, evidence)]` per candidate.

    The evidence a refusal quotes, computed once and shared: which candidate
    declared — or, failing that, assigned — what, and, for a candidate that
    cannot answer, why.  Split out from `frame_field_type_candidates` so the
    diagnostic and the decision read the same table rather than two walks of the
    same candidates that could disagree.

    `decls` is what makes the second source reachable; a reader with no
    declaration table has no way to tell a struct of this module from any other
    name, so it gets the declaration-only answer rather than a guess.  It is
    `frame_field_type_candidates` and `_member_pointee` that pass it.
    """
    out = []
    for st in structs:
        base, ann, evidence, why = struct_field_type(st, name, decls)
        out.append((st.name, base, ann, why, evidence))
    return out


def frame_field_type_candidates(structs, name, decls: dict):
    """`(struct_or_None, (disagree, rows))` — the NESTED FRAME a field holds.

    The agree-or-refuse check for DECLARED types, and the exact analogue of
    `struct_frame_slot_candidates` one level in.  `structs` is the candidate
    list for the holder (the same list the slot check gets), `decls` is
    `{name: StructDef}` for the structs THIS MODULE DECLARES — the only ones
    whose frame layout this compiler could possibly place.

    A `struct_or_None` answer means: every candidate declares `name`, every
    declaration reduces to the SAME base name, that base names a struct of this
    module, and that struct's receiver is a frame.  Under those four conditions
    the slot holds the address of a frame whose layout is known, and the codegen
    PLACES it (`struct_nested_frame_fields`, `struct_frame_block_bytes`) rather
    than reading the agreed index on faith — which is the difference between
    this being a lowering and being the silently-wrong answer C5 named.

    `None` is returned in every other case, and `disagree` says which:

    * a candidate does not declare the field at all, or declares it twice with
      different annotations;
    * the candidates name DIFFERENT base types — the type-level twin of two
      layouts putting one field at two slots, and the same wrong answer at one
      remove;
    * the agreed base is not a struct of this module, or is one whose receiver
      is a value rather than a frame.

    The last two are not failures of the rule; they are the rule's OTHER
    answer, and the caller wants them separately because they go to different
    places.  `field_type_is_value` below is the accessor for that, so no caller
    has to re-derive the distinction from `rows` and get it subtly wrong.
    """
    rows, bases, have = field_type_rows(structs, name, decls), set(), 0
    for _sn, base, _ann, _why, _ev in rows:
        if base is not None:
            bases.add(base)
            have += 1
    if not rows or have != len(rows) or len(bases) > 1:
        return (None, (True, rows))
    base = bases.pop()
    st = structs_declared(base, decls)
    if st is None or not struct_is_framed(st):
        return (None, (False, rows))
    return (st, (False, rows))


def one_word_field_struct(struct_def, name, decls: dict):
    """`(StructDef, evidence)` for the struct `struct_def.<name>` holds as a word.

    THE READER FOR THE ONE-WORD IDENTITY, and its own name because it is
    deliberately not `struct_field_type`.  Those two disagree on one shape, and
    the difference is what this function exists for:

      * `struct_field_type` answers for a FRAME SLOT — "is there a nested frame
        here, and if so which one" — so it must be unanimous across every
        store and every declaration and it treats a store it cannot classify as
        no evidence at all.  That is right there and wrong here.
      * the identity `x.<f>.<g>` is ONE word (`_one_word_field_map`,
        `_one_word_sole_field_chain`), and the question is whether the chain
        keeps being a chain, which a single declaration settles.

    The shape they disagree on is the commonest one in this repository's own
    source: a field assigned from `__init__`'s own ANNOTATED PARAMETER.

        class Outer:
            def __init__(self, inner: Inner):
                self._inner = inner        # stores a name, not a constructor

    `assigned_value_base_name` classifies `Inner()` and not `inner`, so
    `struct_field_type` reports "assigned values this path cannot reduce to a
    type" — and the type is right there in the signature of the method three
    lines above the store.  Reading it is not inference: `inner: Inner` is a
    declaration about the word the caller passes, and the store is a store this
    path performs, which is exactly the pair of premises `struct_field_type`'s
    own docstring rests on.

    It is a SEPARATE function rather than a fourth source inside
    `struct_field_type` because of what that would change: adding the parameter
    row there would make every such field TYPED for
    `frame_field_type_candidates` as well, so a field holding a FRAMED struct
    would start placing a nested frame where it is answered "not typed" today.
    That is a frame-layout decision for every caller of the slot decision, and
    it is not this function's question to change; here the only thing at stake
    is whether a chain continues.

    `(None, None)` for a field whose assigned values are not unanimously ONE
    parameter of `__init__`, or whose parameter declares no struct of this
    module — the same unanimous-or-nothing rule `struct_init_field_types`
    applies, and for the same reason.
    """
    base, _spelling, evidence, _why = struct_field_type(struct_def, name, decls)
    st = (decls or {}).get(base) if base and evidence else None
    if st is not None:
        return st, evidence
    st = init_stores_a_parameter_struct(struct_def, name, decls)
    return (st, "assigned") if st is not None else (None, None)


def field_stores_a_caller_frame(struct_def, name, decls: dict, only_init=False):
    """The `StructDef` of this module every `self.<name>` store hands the CALLER
    a frame of, or None.

    **THE LIFETIME ARGUMENT, and it is one rule asked about two method sets.**
    A field whose declared type names a framed struct of this module holds a
    FRAME ADDRESS, and the question every reader of such a field has to answer
    is *whose* frame — because the one thing that makes the address safe is that
    the frame outlives nothing that can read the slot. When every store of the
    field is a bare NAME that is a parameter of the writing method, annotated
    with a struct of this module, the frame in the slot is one the CALLER
    reserved in the caller's own scratch and passed down; and the object it is
    stored into is the RECEIVER, which is storage the caller owns (the frame
    checks are what refuse to let a receiver be anything else). Both die
    together, so no read of the slot can name reclaimed stack. `__init__` is not
    a premise of any of that — it is one writer among several, and the reason it
    was the only one considered is history, not lifetime.

    `only_init=True` narrows the question to `__init__`, which is what
    `struct_nested_frame_fields` asks: PLACEMENT is the constructor's job, so
    whether the constructor builds a block there is a question about the
    constructor and not about the writers. `only_init=False` — every method — is
    what a READ asks, because a read cannot know which writer ran.

    Unanimous-or-nothing, as everywhere else on this axis, and the negative
    direction is the one that keeps the refusal: any stored value that is not a
    bare parameter NAME — a construction `R()`, a call `mk(4)`, a ternary, a
    nested field `other.inner`, a name the parameter table does not resolve, an
    `AugAssignStmt` — answers None, and so does a field no method writes. This is
    deliberately the same CONSERVATIVE rule `init_stores_a_parameter_struct`
    applied to the shape it already covered, so lifting this to every method
    cannot also widen what counts as a delegating store.

    **`only_init=False` is what `formal/build.py`'s `_typed_nested_frame` asks**,
    and it is the same argument that predicate's own comment made while it
    exempted the `__init__` case: "the only assignment is `__init__`'s, and its
    argument is the CALLER's, so the two die together" reads as a statement
    about `__init__` and is a statement about every writer. What it is NOT is
    licensed for a store into anything but the receiver — `b.inner = o` where
    `b` is a LOCAL, and `b` is returned, hands a frame that dies with this call
    to an object that outlives it, so that shape has no writer this predicate
    counts and keeps its refusal.
    """
    stores = _init_field_assignments(struct_def).get(name) or [] \
        if only_init else method_field_assignments(struct_def, name)
    if not stores:
        return None
    params_by_method = {}
    named = set()
    for entry in stores:
        m, v = (None, entry) if only_init else entry
        if not (isinstance(v, F.IdentExpr) and v.name != "None"):
            return None
        if only_init:
            table = params_by_method.get(None)
            if table is None:
                table = params_by_method[None] = _init_declared_parameters(
                    struct_def, decls)
        else:
            key = id(m)
            table = params_by_method.get(key)
            if table is None:
                table = params_by_method[key] = parameter_declared_structs(
                    m, decls or {}, owner=struct_def)
        st = table.get(v.name)
        if st is None:
            return None
        named.add(st.name)
    if len(named) != 1:
        return None
    return structs_declared(named.pop(), decls)


def init_stores_a_parameter_struct(struct_def, name, decls: dict):
    """The `StructDef` of this module a `__init__` field store is a NAME of, or
    None.

    **THE PLACEMENT PREDICATE, and it is the one question `struct_nested_frame_fields`
    was not asking.** That function placed a nested frame in every field whose
    DECLARED type names a framed struct of this module and whose only writer is
    `__init__` — which is the constructor reserving a block in the object's own
    block and storing that block's ADDRESS in the slot. But the constructor does
    not always build one there:

        struct Holder:
            var src: R                     # declared R, a framed struct of THIS module
            def __init__(self, r: R):
                self.src = r               # … and stores a NAME

    Here the slot holds the CALLER's frame, not one this constructor made, so
    reserving a block for it and writing a block address into it is wrong twice
    over: the block is never filled, and the store that would fill it —
    `formal/build.py`'s `_frame_field_store_is_sound` — is right to refuse
    ("the slot belongs to the function that created THAT frame") because the slot
    IS placed. That is the deadlock `“FORMAL_receiver_stored_in_a_field: a frame address in a struct field”`
    measured: a DELEGATING constructor over a struct of this module is refused
    for a reason that only exists because of the placement, and the placement
    exists because of the declared type.

    **`self.src = r` is a POINTER slot, and `struct_nested_frame_fields` now says
    so.** It is a pointer slot for a lifetime reason, not a typing one: `r`
    arrived as an argument, so the CALLER reserved its bytes in the caller's own
    scratch and the two die together — which is exactly the argument
    `_frame_field_store_is_sound` already makes and which the placement was
    cancelling out.

    The rule itself is `field_stores_a_caller_frame(..., only_init=True)`, and
    this is the narrower question asked by the narrower caller: whether the
    CONSTRUCTOR builds a block there is a question about the constructor, even
    though the lifetime argument is about the caller and holds for every writer.

    `one_word_field_struct` is the other reader of the same evidence and calls
    this, rather than the two walking `__init__`'s body separately and one of
    them learning about a spelling the other does not.
    """
    return field_stores_a_caller_frame(struct_def, name, decls, only_init=True)


def _init_declared_parameters(struct_def, decls: dict) -> dict:
    """`{parameter name: StructDef}` for `__init__`'s annotated parameters."""
    for m in struct_methods(struct_def):
        if m.name == "__init__":
            return parameter_declared_structs(m, decls or {}, owner=struct_def)
    return {}


def field_type_one_word_struct(structs, name, decls: dict):
    """The ONE-FIELD struct of this module every candidate agrees `name` holds.

    The third answer `frame_field_type_candidates` does not distinguish, and
    the only one of the three that is a LOWERING rather than a verdict.

    That function returns `None` for "agreed, and not a frame of this unit",
    which is right as a verdict — a frame slot holds one word and there is no
    second layout to read through — but it is three different facts wearing one
    answer:

      * the agreed type is a scalar or a host type (`Int32`, a `List`, a
        pointer).  There is nothing to read a field out of.
      * the agreed type names NO struct of this module.  Same.
      * **the agreed type names a struct of this module whose receiver is its
        one field** (`struct_is_one_field`).  The word in the slot IS that
        field's value, so `<holder>.<name>.<sole field>` is ONE load at
        `<holder>.<name>`'s own slot and not a second layout at all.

    Only the third has a lowering, and without this the depth-2 branch in
    `formal/build.py` declined it as "agreed, and not a frame" and the emitter
    then reported `field_access_refusal`'s `holder=True` sentence — "the frame
    analysis and the emitter disagree about this function's receivers — a
    compiler bug rather than a limit of the path".  Neither half was true. The
    frame analysis was RIGHT (there is no nested frame) and the emitter was
    right that the access had no slot; what was missing was the one load.

    This is the same scalar replacement `formal/build.py`'s `_one_word_field_map`
    computes for a receiver (`self`, a local built from a constructor, a
    parameter declared as a one-field struct) — that function rewrites `x.f` to
    `x`, and this is the frame-slot spelling of the identical fact. Reading it
    off the DECLARED type rather than off a binding is what makes it available
    here: the field's slot is placed by the holder's layout, and the struct is
    named by the class body, so there is no binding to find.

    **Why the DEMOTION that produced the one-field struct is not in question.**
    This was filed as "the two passes disagree about `struct_is_framed`", with
    an offer to stop the demotion (its option B) as the semantically honest
    repair; that filing is deleted, its defect fixed and measured. Measured
    here: the same
    refusal, byte-identical, with a `struct Inner` that declares exactly ONE
    field and no class-level default at all — so the demotion is not the
    trigger and there is no layout to un-cement. What was missing was the
    lowering, and it was missing for every one-field nested field rather than
    for the defaulted ones. Two of three fields defaulted builds; one does not,
    and the difference is the width and nothing else. The case that pins it is
    `test_formal_run.py`'s `one_word_nested_declared_single_field_read`, beside
    the defaulted `one_word_nested_demoted_width_method_call`.

    Returns None for every other case, and `disagree` is not spelled here: a
    caller that gets None cannot tell "not one word" from "disagree", and both
    are answers to the same question ("is there one load for this"), which is
    the question the caller asked. A caller that needs the distinction asks
    `field_type_is_value` for it, exactly as `frame_field_type_candidates`'s own
    docstring says its callers should.
    """
    rows, bases, have = field_type_rows(structs, name, decls), set(), 0
    for _sn, base, _ann, _why, _ev in rows:
        if base is not None:
            bases.add(base)
            have += 1
    if not rows or have != len(rows) or len(bases) > 1:
        return None
    st = structs_declared(bases.pop(), decls)
    if st is None or not struct_is_one_field(st):
        return None
    return st


def one_word_sole_field_frame(struct_def, decls: dict, one_field=None):
    """The FRAMED struct a ONE-FIELD struct's sole field holds, or None.

    **The one fact two callers need for opposite reasons, and neither of them
    can derive it.**

    A one-word struct's receiver IS its field: `struct_is_framed` is False, so
    every frame table in the tree skips it and the word the caller hands it is
    that field's storage. That storage can be a FRAME ADDRESS rather than a
    value, and the two consequences pull opposite ways:

      * `formal/build.py::_frame_receivers` seeds a method of such a struct as a
        HOLDER of that frame. Without it, `self.v` has no home: the receiver is
        not in the holder set, the field analysis has no case for a word that is
        both a receiver and an address, and the emitter reports
        `field_access_refusal` about an expression the source never spells.
      * `formal/build.py::_collect_receiver_rebinds` must NOT grant its
        one-field exemption there, because `self = <a word>` overwrites the
        frame address the CALLER still holds. The method's own later reads then
        read the caller's object and its store never reaches its caller, which
        is a wrong answer on both machines rather than a crash.

    So the answer is read ONCE, here, and both callers' predicates are opposites
    of each other: `struct_is_one_field(owner) and this is None` is a plain
    word, `not None` is an address. Two copies of the question would be two
    places for them to disagree about which kind of receiver a struct has, and
    that disagreement is a segfault rather than a wrong message.

    Read off the DECLARED type through `frame_field_type_candidates` — the same
    agree-or-refuse reader every other declared-type question on this path goes
    through — so a field two candidates annotate differently answers None rather
    than a pick. None is also the answer for a sole field that is a value, for
    a field whose type names no struct of this module, and for an owner that is
    not one field at all; the caller that needs the "agreed and a value" case
    apart from the "disagreed" one asks `field_type_is_value`, as
    `frame_field_type_candidates`' own docstring says its callers should.
    """
    if not one_field_answer(struct_def, one_field):
        return None
    sole = sole_field_answer(struct_def, one_field)
    if sole is None:
        return None
    nested, (disagree, _rows) = frame_field_type_candidates([struct_def], sole,
                                                            decls)
    return None if disagree else nested


def one_word_nested_sole_field_refusal(slot: str, st) -> str:
    """`slot.f` where `f` is not the one field of the one-word struct in `slot`.

    The third of the three refusals this lowering can raise, and the only one
    about a name rather than about a layout. `field_type_one_word_struct`
    agreed the slot holds a one-field struct of this module; this is the case
    where the field being read through it is not that struct's one field, so
    there is no word to read and no second layout to read it from.

    The alternative answers were measured and are all worse. Continuing to the
    value path reaches the emitter with no slot for the chain, and the emitter
    reports `field_access_refusal`'s `holder=True` sentence — "the frame
    analysis and the emitter disagree about this function's receivers — a
    compiler bug rather than a limit of the path" — which is false of both
    halves: the analysis placed the chain correctly and the emitter asked for
    a load that does not exist because the name does not. And guessing the
    field's slot index would be the wrong answer rather than a failure, which
    is the outcome every refusal in this family exists to prevent.
    """
    return (f"{slot} is a {st.name} frame slot and every binding of it agrees "
            f"its declared type is a {st.name}, which has exactly one field "
            f"and whose receiver IS that field — so {slot} holds the value of "
            f"that one field and there is no second layout to read anything "
            f"else out of. Read the field you mean, or give {st.name} a field "
            f"for it")


def field_type_is_value(structs, name, decls: dict) -> bool:
    """True when every candidate AGREES the field is not a frame of this unit.

    The other answer, and it is an answer rather than a failure: if every
    candidate types the field and they all name the same base, and that base
    is not one of this module's framed structs, then the word in the slot is
    PROVABLY a plain value — an `Int32`, a `List`, a `SIMD`, a pointer, a type
    this image does not compile.  Nothing about the frame layout is in question
    any more, and a diagnostic about the frame layout is then a diagnostic about
    the wrong thing.

    It is deliberately a weaker claim than "the type is a scalar".  It does not
    need to be: the single thing a caller wants to know is whether the
    FRAME-SLOT reading is the right one, and a type this module does not
    declare settles that without settling anything else.
    """
    if not structs:
        return False
    bases = set()
    for st in structs:
        base, _ann, _ev, _why = struct_field_type(st, name, decls)
        if base is None:
            return False
        bases.add(base)
    if len(bases) > 1:
        return False
    only = bases.pop()
    inner = structs_declared(only, decls)
    return inner is None or not struct_is_framed(inner)


def field_type_disagreement(structs, name, rows) -> str:
    """Why a field's name was NOT typed — the diagnostic for the negative case.

    A refusal that says "the name is not typed" and stops there is a refusal
    the reader has to re-derive, and the derivation is the interesting part:
    the point of the agree-or-refuse rule is that a reader can SEE which
    candidate disagreed and with what.  So every row is spelled, and the
    candidates that agreed are listed too — a refusal that only prints the
    problem rows leaves the reader unable to tell an absent annotation from a
    contradicted one.

    An agreed row says WHERE its type came from, in the source's own words for
    each: "declares 'x' as 'Inner'" for a declaration and "assigns 'x' an Inner
    in __init__" for the constructor spelling.  Printing "declares" for the
    second is a reason that is not operating — the class declares nothing, and a
    reader sent to look for a declaration that does not exist loses the thread.
    """
    parts = []
    for sn, base, ann, why, evidence in rows:
        if base is None:
            parts.append(f"{sn}: {why}")
        elif evidence == "assigned":
            parts.append(f"{sn} assigns {name!r} a {ann} in __init__ "
                         f"(base {base})")
        else:
            parts.append(f"{sn} declares {name!r} as {ann!r} (base {base})")
    return "; ".join(parts) if parts else "no candidate types it"


def struct_frame_block_bytes(struct_def, decls: dict,
                             depth=None) -> int:
    """Bytes one construction of this struct occupies: its frame AND its nested.

    A field whose agreed declared type is a framed struct of this module holds
    the ADDRESS of that struct's frame, and the address has to name bytes
    somebody reserved.  So the unit of allocation stops being "one frame per
    constructor site" and becomes "one BLOCK per site": the object's own frame,
    then the frames of its typed-nested fields, laid out in declaration order
    immediately above it.

    The nested frames go ABOVE the object's own slots rather than below for one
    reason, and it is the reason the proof wants: a value read out of a frame
    consults exactly one slot, and that slot's 8 bytes lie below the first
    nested byte.  A nested frame's address is therefore not a value any read of
    the object can produce, which is `Frame.frameRead_below_nested` and is what
    keeps "the callee was handed a value" and "the callee was handed a frame"
    from ever being the same word.  Placing them below would put a frame address
    inside the outer frame's own byte range and destroy that.

    Recursive, because a nested struct's own typed-nested fields need blocks
    too, and bounded by `MAX_NESTED_FRAME_DEPTH` because the declaration graph
    can be cyclic (`struct A: var b: B` / `struct B: var a: A`) and an
    unbounded block size is an emitter that hangs rather than one that refuses.

    Running out of depth with a typed-nested field STILL under this struct is a
    REFUSAL and not a truncated block, which is what it used to be: the
    reservation came back short by exactly the frames the cut dropped, every
    blob above it landed on one of those frames, and the program took a
    SIGSEGV with no diagnostic — measured at six nested levels (five hops) on
    both backends, where the same source built and ran correctly at five. A
    bound whose whole purpose is "a cyclic graph refuses instead of hanging"
    cannot be honoured by silently allocating less than the layout walks.
    """
    depth = MAX_NESTED_FRAME_DEPTH if depth is None else depth
    total = struct_frame_bytes(struct_def)
    if depth <= 0:
        past = struct_nested_frame_fields(struct_def, decls, 1)
        if past:
            raise CodegenError(
                struct_frame_depth_exceeded(struct_def, decls, past))
        return total
    for _name, _slot, nested in struct_nested_frame_fields(struct_def, decls,
                                                          depth):
        total += struct_frame_block_bytes(nested, decls, depth - 1)
    return total


def struct_frame_depth_exceeded(struct_def, decls: dict, past) -> str:
    """The chain outran `MAX_NESTED_FRAME_DEPTH`, named in the user's words.

    `past` is what `struct_nested_frame_fields` still found at the level the
    recursion ran out on, so the sentence names a field the file actually
    declares rather than a depth counter.  A declaration CYCLE arrives here
    too and is the case the bound was written for; it gets the same message
    because the two need the same answer from the user — a chain this path
    cannot size is a chain this path must not lay out — and because the
    sentence already says a cycle lands here, so a reader with one is not sent
    looking for a different error.
    """
    name = next((k for k, v in decls.items() if v is struct_def), "this struct")
    spelled = ", ".join(repr(f) for f, _s, _n in past)
    return (
        f"{name} nests a typed struct field past the "
        f"{MAX_NESTED_FRAME_DEPTH} levels this path lays out ({spelled} is "
        f"below that cut), so the block this construction needs has no size "
        f"this path can state. Refused rather than laid out short: a truncated "
        f"block puts every frame above the cut inside the caller's own "
        f"expression scratch, which faults with no diagnostic naming the file. "
        f"A struct that nests itself through a cycle reaches here too, and is "
        f"the case the bound was written for."
    )


# How deep a chain of typed-nested fields this path will place.  One is the
# real answer for every struct in this repository and the bound exists so that
# a chain the layout cannot size — a cyclic declaration graph above all —
# produces a refusal rather than a hang or a short block; it is enforced in
# `struct_frame_block_bytes`, which is where the reservation is computed and so
# the one place a truncation could become a fault.
MAX_NESTED_FRAME_DEPTH = 4
