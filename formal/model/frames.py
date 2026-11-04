from . import *

# ── A frame that OUTLIVES the function that built it ─────────────────────
#
# `struct_constructor_sites` above is the whole of a frame's placement today,
# and it is the whole of the problem: every block belongs to the function that
# reserved it, and that function's scratch is reclaimed when the function
# returns. So `return <frame>` hands the caller a pointer into dead memory, and
# the 18 arm64 findings that name it are all one shape.
#
# The fix is a COPY, and the copy has to land somewhere the CALLER owns. The
# destination is a block in the CALLER's own scratch, laid out by exactly the
# same rules as a local constructor site — per CALL SITE, in walk order, in the
# prologue, so a call in a loop reuses its site and the stack cannot grow
# without bound.
#
# WHERE the block goes, and the argument is one line: a returned block has
# exactly the LIFETIME a local constructor block has, and nothing else. Both
# live in the creating function's scratch, both die with it, and both are
# written only by the function that owns them (the callee writes the returned
# one only during the call, while the caller's own frame is still live). So the
# returned blocks sit in the same region as the constructor frames, at the
# BOTTOM of the reserved scratch, and the blob cursor starts above the lot. The
# alternative considered — a separate region between the blobs and the spill
# slots — buys nothing that this does not already have, and costs a fourth
# region in a layout that has to be computed twice. The one thing that does
# have to be true is that the two never overlap, and that is a property of the
# cursor, not of the choice of region.
#
# It is in the shared model rather than written twice in the backends because a
# scratch laid out one way by arm64 and another by x86-64 is a returned frame
# that is correct on one machine and a use-after-free on the other.
#
# The other half of the fix — telling the CALLEE where the caller's block is —
# is a calling-convention question, and the decision is in
# `returned_frame_convention_refusal`: the caller passes the block's address
# as one hidden TRAILING argument, the callee copies into it and returns it.


def struct_returned_frame_sites(fn, structs_by_name, returns_frame) -> dict:
    """`{id(call): (struct, block_offset, total_bytes)}` — where a frame
    this function RECEIVES from a callee has to be put.

    The caller's half of `struct_constructor_sites`, and the reason a returned
    frame has a lifetime this analysis can follow: the block reserved here is
    in THIS function's scratch, so it lives exactly as long as the holder does.

    `returns_frame` is a predicate over a callee NAME — "this callee returns a
    frame address" — supplied by the caller rather than recomputed here. The
    build pass already knows it (it is the fixpoint that decides which
    functions return a frame, and it runs to a fixed point across the module),
    and two answers to "does callee F return a frame" is precisely the
    disagreement that produces a wrong number rather than a refusal: a caller
    that reserved a block and a callee that did not copy into it builds, runs,
    and returns whatever the caller's uninitialised scratch held.

    EVERY call site of such a callee gets a block, not only the ones that bind
    the result to a name.  The landed version walked assignments, which left
    three ordinary shapes without a block: `return make()`, `make().size()`,
    and `f(make())` — and each of them is a frame the CALLER dereferences
    immediately, which is exactly the lifetime this block is sound for.  The
    cost of covering them is reserved scratch for a result nobody keeps, and
    the cost of not covering them is a callee that copies into a register it
    was handed by accident.  `q: Point = make()` and `q = make()` are the same
    binding — an annotated target is still an `AssignStmt`, with the annotation
    in `node.annotation` (fire_compiler.py:474) — and a `MultiAssignStmt`
    target is deliberately not followed, because it binds a tuple and a frame
    holder in a tuple position is a different question (and a refusal)."""
    if not returns_frame:
        return {}
    out, offset = {}, 0
    for node in iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr):
            continue
        # `call_callee_name`, NOT `node.func.name`, and the two spellings are
        # ONE call: a comptime specialization `f[T](r)` names the same function
        # `f` does and contributes no call-time argument of its own, so it lands
        # the frame on `f`'s parameter at exactly the position the bare spelling
        # would. Reading only the bare one is what made a specialized call
        # reserve NO block: the callee is the side that COPIES, it copied into
        # the word it was handed — an ordinary argument register — and the
        # caller's `f[T](0, r).a` then read eight bytes from wherever that
        # register pointed. Measured on arm64 beside its bare twin, same source:
        # the twin answers 7, the specialization built and exited 0.
        callee = call_callee_name(node.func)
        if callee is None:
            continue
        # `q = make()`, `var q = make()` and the annotated `q: Point = make()`
        # are the same binding: an annotated target is still an AssignStmt
        # (fire_compiler.py:474) and `var q = …` is a VarDecl — see
        # `frame_binding_target`, which is the one reader of that question.
        #
        # The bound NAME is handed to the predicate where there is one and
        # `None` where there is not, because a call in a position that binds no
        # name still needs a block (`return make()`, `make().size()`,
        # `f(make())` — all three dereference the frame immediately, which is
        # exactly the lifetime this block is sound for) and
        # `frame_returning_predicate`'s contract is two arguments.
        name = frame_binding_target(node)
        st = returns_frame(callee, name)
        if st is None:
            continue
        block = struct_frame_block_bytes(st, structs_by_name)
        out[id(node)] = (st, offset, block)
        offset += block
    return out


def returns_on_every_path(stmts) -> bool:
    """Whether every path through `stmts` ends in a `return`.

    Deliberately the STRICT answer — the last statement of the list must be a
    return, and an `if` counts only when every branch ends in one — because the
    question it decides is "may a caller treat this function's result as a
    frame?".  A function that returns a frame on one path and falls off the end
    on another leaves the caller's block holding whatever the scratch had, and
    the honest answer to that is a refusal rather than a default-constructed
    struct.  Both backends already have a `_always_returns` for the unrelated
    question "does this body need an implicit `return 0`", and the two are not
    the same function and do not agree (x86-64's returns True for a return
    ANYWHERE in the list, arm64's walks to the end); this one is the only one
    consulted for the returned-frame decision, and it is the stricter of the
    two on purpose.

    Iterative over the sibling stream and recursive only into an `if`'s
    branches, for the reason `formal/arm64_codegen.py`'s `_always_returns`
    now carries: a walk that recursed once per sibling needed one Python
    frame per statement, and this one is asked about every function in the
    module — so a long straight-line body died with a `RecursionError` from
    the frame-return fixpoint, which is a worse place to be told about it
    than from the emitter."""
    cur = stmts or []
    i, n = 0, len(cur)
    while i < n:
        st = cur[i]
        i += 1
        if isinstance(st, (F.ReturnStmt, F.RaiseStmt)):
            return True
        if isinstance(st, F.IfStmt):
            if not returns_on_every_path(st.then_body):
                return False
            for _cond, body in (st.elifs or []):
                if not returns_on_every_path(body):
                    return False
            if st.else_body is None:
                return False
            return returns_on_every_path(st.else_body)
    return False


def frame_binding_target(node):
    """The plain NAME a `VarDecl` / `AssignStmt` binds, or None.

    The one reader of "is this statement a binding of a single name", and it is
    one function because four readers needed it and three of them had grown
    their own version: `struct_constructor_bindings` (which locals hold a
    frame), `struct_returned_frame_sites` (which call sites reserve a block for
    a frame a callee hands back), and the returned-frame fixpoint that reads
    the same table out of `_frame_receivers`.  A
    version that answered for `AssignStmt` but not for `VarDecl` is exactly the
    gap that let `var q = make()` reserve no block while `q = make()` did — a
    caller and a callee disagreeing about the same binding.

    `MultiAssignStmt` (`a, b = f()`) and any non-`IdentExpr` target answer None:
    they bind a tuple, and a frame holder in a tuple position is a different
    question — and a refusal — rather than a block to reserve.
    """
    if isinstance(node, F.VarDecl):
        return node.name
    if isinstance(node, F.AssignStmt) and isinstance(node.target, F.IdentExpr):
        return node.target.name
    return None


def frame_binding_value(node):
    """The value a `VarDecl` / `AssignStmt` binds, or None for anything else.

    The companion to `frame_binding_target` and for the same reason: the two
    have to agree about which statements are bindings, or a caller reserves a
    block for a statement the callee does not treat as one.
    """
    if isinstance(node, (F.VarDecl, F.AssignStmt, F.MultiAssignStmt)):
        return getattr(node, "value", None)
    return None


def struct_constructor_bindings(fn, framed, functions=()) -> dict:
    """`{name: [struct, …]}` for locals bound from a framed struct's constructor.

    A LIST per name, and that is the fix for a miscompile rather than a
    refinement: `x = A()` on one path and `x = B()` on another is one name with
    two frame layouts, and a dict that kept the last binding computed a slot
    index from that one alone — so on the `A` path `x.v` read `A`'s idea of
    where `v` is, which is generally not where `A` puts it. Every candidate is
    kept and `struct_frame_slot_candidates` decides whether they agree.

    The empty list is meaningful and not an oversight: a name bound from a
    constructor this path does NOT frame holds a plain word, and remembering
    that is what stops a later `x.f` from being read as a frame slot.

    In the model rather than in `formal/build.py` because four readers need it
    and they must not be able to disagree: the holder fixpoint asks "which names
    in this function hold a frame", `formal/build.py`'s `_constructor_bindings`
    is a delegate, the returned-frame fixpoint asks "which of them does this
    function build and hand back", and `frame_binding_target`/
    `frame_binding_value` are the one reader of which STATEMENT binds.  A second
    copy of this walk would be a caller reserving a block for one struct and a
    callee building another.

    **`call_lowers_as_framed_construction`, and that is the guard that makes
    this list agree with the emitters.** Being in `framed` is necessary and not
    sufficient: a call to a name the emitters route to a type CONVERSION before
    they reach `_emit_struct_constructor` produces a plain word, and recording
    it as a construction binding would make the name a three-slot frame HOLDER
    anyway — so `x.f = v` becomes a store at `[word + 8·slot]`. Measured, both
    architectures, from a green build:

    ```
    struct String:                        # three fields, exactly as the stdlib has it
        var _ptr_or_data: Pointer[UInt8]
        var _len_or_data: Int
        var _capacity_or_data: Int
        def size(self) -> Int: return self._len_or_data
    def main(n: Int) -> Int:
        var a = String()
        a._len_or_data = 5
        return a.size()
    ```

    → SIGBUS, exit 138, in read-only `__TEXT`, because the store's base is the
    address of an interned `""`.  With the guard the name is a plain word, and
    `a._len_or_data = 5` is `field_access_refusal` — a build error naming the
    field and the name, which is the answer this backend owes rather than a
    fault at an address it did not mean to touch.

    `functions` is the image's compiled function names, which the predicate reads
    for the one case where a name is both a function and a struct: the emitters
    skip the type-constructor interception for a name they compiled, so the call
    IS a construction there, and a pass that disagreed on that would refuse a
    program that builds. Empty means "every name in `framed` is a struct", which
    is the answer for a reader that has no image — the guard can only be too
    strict then, never too permissive."""
    out = {}
    for node in iter_nodes(getattr(fn, "body", None)):
        target = frame_binding_target(node)
        value = frame_binding_value(node)
        if not target or not isinstance(value, F.CallExpr):
            continue
        if isinstance(value.func, F.IdentExpr) and value.func.name in framed:
            if not call_lowers_as_framed_construction(
                    value.func.name, framed,
                    len(value.args or []) + len(value.kwargs or []),
                    functions):
                continue
            # De-duplicated, order kept: `x = A()` twice on two paths is ONE
            # candidate, and a refusal that printed "a A, A receiver" because it
            # counted a binding twice would be reporting the walk rather than
            # the program.
            got = out.setdefault(target, [])
            st = framed[value.func.name]
            if st not in got:
                got.append(st)
    return out


def frame_returning_predicate(table):
    """`(callee, bound_name) -> struct or None` over a `{callee: struct}` table.

    **`struct_returned_frame_sites` takes a TWO-argument predicate, and
    `dict.get` is not one.**  `dict.get` takes `(key, default)`, so handing it
    over as the predicate makes a MISSING callee answer with the second
    argument — which is the bound NAME — and every call in a module that
    declares a multi-field struct is then treated as returning a frame.  The
    consequence is five extra instructions per call (a zero-byte block whose
    address is pushed as a ninth argument into a register the callee never
    reads), so the program's ANSWERS are unchanged and the image is not: and in
    a module that also has an eight-argument call the ninth push crosses the ABI
    limit and the program is refused for an argument it never had.  Measured,
    both:

        # `dict.get` as the predicate
        call wide(): 9 arguments exceeds the 8 the formal arm64 ABI passes in
        registers (one of which is the block this callee returns a frame in)

    — for `def wide(a, b, c, d, e, f, g, h)` bound with `var r = wide(...)` in a
    module that also declares a two-field struct.  The landed
    `test_returned_frame_layout.py` did not catch it because its `_returns`
    helper is a real two-argument closure.

    So the predicate is built here, by the function whose contract states the
    arity, rather than at each of the two call sites that supply one.
    """
    def _predicate(callee, _bound_name):
        return table.get(callee)
    return _predicate




def returned_frame_container_writes(fn, holder) -> list:
    """`[(field, why)]` — containers this function writes into the block it
    RETURNS.

    The one hole the returned-frame convention opens that the by-reference
    receiver does not.  Premise (B1) says a frame slot never holds a blob,
    because a blob is bump-allocated in the function that made it, and it is
    enforced for METHODS (`check_frame_field_blob_premises`).  A returned block
    outlives the function that made it, so the same reasoning applies with the
    sign flipped: a blob written into that block names scratch the caller is
    already using, and the first `q.items.append(1)` after the return writes into
    the callee's reclaimed stack.

    `holder` is the returned NAME, so this reads the body the same way
    `struct_field_container_writes` reads a method — one hop of name propagation
    (`tmp = [1]; p.items = tmp`) and the same three decidable shapes, so a
    program this cannot decide about is not refused here.
    """
    body = getattr(fn, "body", None)
    containers: set = set()
    found: list = []
    _container_binding_names(body, {holder}, containers)
    _container_write(body, {holder}, found, containers)
    return found






# How many source arguments a frame-returning callee may take. Six, and the
# reason is the HIDDEN WORD rather than the arity: it is one more argument, and
# both backends read it out of an argument REGISTER
# (`formal/arm64_codegen.py` and `formal/x86_64_codegen.py` move it home by the
# register path, with no stack convention for it), so the budget is the smaller
# of the two REGISTER FILES — six on x86-64, eight on arm64.
#
# **It is not the limit on how many arguments a function may take.**  Both ABIs
# put the arguments past their register file in the caller's frame and both
# backends implement that now (`_MAX_INCOMING_ARGS`, 24, in each), so a
# frame-returning callee could be handed its hidden word in that area and this
# number would become twenty-three on both machines.  It has not moved, and the
# reason it did not is worth stating rather than leaving to be inferred from the
# digit: the hidden word travels by a DIFFERENT path from every source argument,
# and widening the source path is not the same change as widening this one.  A
# callee's block address also has to survive being read out of the frame rather
# than a register, which is a second question from whether the offset is right.
# The filing that asked for this number to be decided BEFORE the register
# ceiling was lifted (`FORMAL_x86_64_argument_registers`, deleted
# 2026-10-02 with the emitters half landed) is the reason it is written down
# here rather than left implicit: this is the decision.
#
# Named rather than written at each use because the two backends have to apply
# the same number: a build that answers "8 is fine" on arm64 and "8 is not fine"
# on x86-64 is a two-backend disagreement about one program.
RETURNED_FRAME_MAX_ARGS = 6


def returned_frame_convention_refusal(callee, n_source_args: int,
                                      arg_regs: int = RETURNED_FRAME_MAX_ARGS
                                      ) -> str:
    """The returned-frame convention cannot be applied to this callee.

    The copy needs ONE word: the address of the caller's block. Getting it to
    the callee is the whole of the remaining design question, and the three
    candidates were costed rather than guessed.

    1. **An argument register past the ones there are.** Ruled out by
       measurement, not taste. arm64 has X0..X7 and X16/X17 are IP0/IP1, which
       `BL` destroys; x86-64 has only SIX (`RDI, RSI, RDX, RCX, R8, R9`).
       A variadic argument count is already refused by name on this path for
       the same reason (`model.variadic_call_refusal`).
    2. **The callee computes the caller's block itself.** This is the
       attractive one and it is arithmetically possible: the prologue's
       `SUB SP, SP, #_SCRATCH` and the epilogue's matching `ADD` are
       symmetric, so a callee's scratch begins exactly `_SCRATCH` below the
       caller's, and the callee can address the caller's whole scratch from
       its own `SP` with nothing but a compile-time constant. What it cannot
       do is know WHICH of the caller's blocks to copy into: the offsets are
       assigned per call site in the caller's own walk order
       (`struct_returned_frame_sites`), and the callee has not read the
       caller's body. A single fixed slot would work for `a = f(); b = f()` —
       the same block, reused — and would collide for the one shape that
       matters, `f(g())`, where the inner and outer results must be live at
       once.
    3. **A trailing argument on the returning function** (chosen). The
       returning function gains one hidden word, and `return <frame>` becomes
       "build the object in the block that word names, and return that word".
       This reuses the by-reference receiver convention that already exists — a
       frame address is one word and the receiver is already passed as one — so
       it needs no new register, no new calling-convention section, and it
       leaves the value model, `MojoFunc`, `evalFunc`, `evalBodyEnv` and the
       machine model untouched. That is the same property the by-reference
       design was chosen for, and it is why this is a codegen change rather
       than an ABI one.

       The cost is a limit this has to refuse rather than approximate: the
       hidden word is an argument REGISTER — both backends move it home by
       the register path and neither has a stack convention for it — and this
       path has a fixed number of those, eight on arm64 and six on x86-64,
       which is why `arg_regs` is a parameter and the message quotes the number
       it was given. A callee that already takes that many arguments cannot be
       given the word, and a program that does that is refused HERE, by name,
       instead of being handed a dropped argument and a frame written into
       scratch nobody reserved.

       **THE DEFAULT IS THE SMALLER REGISTER FILE, and that is a decision
       rather than an oversight.** The build pass raises this refusal from a
       DECLARED parameter list (`_check_returned_frame_budget`), before any
       backend has been chosen, so it cannot quote a per-architecture budget. A
       build that answered "8 is fine" there and then refused at emission on
       x86-64 would be a two-backend disagreement about one source file, which
       is the one thing this pair is not allowed to do — so the shared default
       is `RETURNED_FRAME_MAX_ARGS` (six), each backend passes its own `arg_regs`
       when it is the one asking, and the message says which budget it quoted.

       **Six is NOT the limit on a function's arity, and that is the half of
       this that is easy to misread now that both ABIs have a stack area.**
       Arguments past the register file travel in the caller's frame on both
       backends (`_MAX_INCOMING_ARGS`, 24, in each), so a frame-returning callee
       could be handed its hidden word there and this budget would become
       twenty-three on both machines at once. It has not moved, because the
       hidden word takes a DIFFERENT path from every source argument and
       widening the source path is not the same change: the callee would be
       reading the CALLER's block address out of memory rather than out of a
       register, which is a question about that address's lifetime and not about
       the offset arithmetic both ends would otherwise share. `RETURNED_FRAME_MAX_
       ARGS`'s own comment carries the decision in full; it was asked for by
       step 3 of the filing that is now fixed, and answering it is half of what
       that filing needed.

       **The block is COPIED into the caller's, not built in place**, and the
       copy is what a frame that arrived as a PARAMETER needs: `def fwd(r):
       return r` has no object of its own to build, and the only sound thing it
       can hand back is a copy taken while its caller's frame is still live. A
       build-in-place convention is cheaper — it never re-bases a nested
       frame's ADDRESS into the new block — and it is the right answer for every
       frame the callee BUILDS. It cannot answer for one it RECEIVED, which is
       why this tree copies.  `formal-frame-escape` built the build-in-place
       convention and recorded the shape it cannot cover in
       `FORMAL_returned_frame_received_is_still_refused`; that doc is
       deleted because on this tree the received half computes —
       `test_formal_returned_frame.py`'s `a_received_frame_handed_on` is 7 on
       both architectures — and the copy is what makes that possible.
    """
    if n_source_args >= arg_regs:
        return (
            f"{callee} returns a frame address, so it needs one hidden word "
            f"for the caller's block — and it already takes "
            f"{_count_word(n_source_args)} argument"
            f"{'' if n_source_args == 1 else 's'}, which is this path's whole "
            f"argument budget: this ABI passes values in "
            f"{_count_word(arg_regs)} argument registers, and this backend "
            f"already drops arguments past that for compile-only fidelity. "
            f"Copy the struct's fields out instead of returning the object, "
            f"which is the same program with a lifetime this analysis can "
            f"follow, or reduce the callee's parameter count")
    return ''


def frame_return_mixed_refusal(owner, frame_spelling, word_spelling,
                               falls_off_end) -> str:
    """A function that returns a frame on one path and not on another.

    Which is NOT a missing lowering but a program the convention cannot
    describe, and the reason is the CALLER rather than the callee: the caller
    has to reserve a block for this function's result before it calls, and to
    read the result out of that block afterwards, so "what does this function
    return" has to be ONE answer for the whole image.  A function that returns
    a frame and a word on different paths has two, and either choice is a wrong
    answer rather than a rough edge:

      * treated as frame-returning, the word a caller receives is the ADDRESS
        of a block the callee never wrote — a stack address where the source
        says a value;
      * treated as word-returning, a frame address is handed to callers that
        read fields through it, and the read lands in whatever the callee's
        reclaimed scratch held.

    `falls_off_end` names the other half of the same question: a body that
    returns a frame on one path and simply ends on another.  The caller's
    block is uninitialised on that path, and the one thing this path must never
    invent is a struct's contents.
    """
    if falls_off_end:
        return (f"{owner} returns a frame address on one path and falls off "
                f"the end of its body on another, so a caller that reserved a "
                f"block for the result would read a block nobody wrote: the "
                f"bytes are whatever the scratch held. Every path that leaves "
                f"the function must return a frame address, so that the "
                f"caller's one reservation is the right one — give the last "
                f"branch a `return {frame_spelling}` as well, or copy a field "
                f"out instead of returning the object")
    return (f"{owner} returns {frame_spelling} on one path and "
            f"{word_spelling} on another, and one function cannot have two "
            f"return conventions in one image: a caller has to decide BEFORE "
            f"the call whether to reserve a block for the result, and it can "
            f"only decide that if the answer is the same on every path. "
            f"Treating this function as frame-returning hands callers the "
            f"ADDRESS of a block the callee never wrote where the source says "
            f"a value; treating it as word-returning hands them a frame "
            f"address to read fields through, out of scratch that has already "
            f"been reclaimed. Return a field on both paths, or build the "
            f"object and return a copy of one of its fields")


def frame_return_candidates_refusal(owner, rows) -> str:
    """`return <frame>` where the name's candidate layouts disagree.

    The copy is `n` slots wide and it has to be the same `n` the CALLER
    reserved, or the caller reads past the end of a block sized for the other
    struct — a wrong number on one machine and a segfault on the other
    depending on which side got the wider count.  The one name, two layouts
    shape is already refused at every field access by
    `struct_frame_slot_candidates`; this is the same disagreement arriving
    through the RETURN, where there is no field access to catch it, and every
    candidate is spelled so the reader can see which one wanted which count."""
    parts = []
    for sn, slots in rows:
        parts.append(f"{sn} has {slots} slot(s)" if slots is not None
                     else f"{sn} is not a frame of this module")
    return (f"returning this name copies out a frame, and the copy's width is "
            f"the number of slots — but the name holds a frame address in more "
            f"than one shape here: {'; '.join(parts)}. Which one applies "
            f"depends on the path taken and this analysis has none, so the "
            f"caller would reserve a block sized for the other struct. Bind "
            f"the two constructions to two names, which is the same program "
            f"with one width per name")


def frame_return_overloads_disagree_refusal(name, rows) -> str:
    """An OVERLOADED name whose definitions disagree about returning a frame.

    The same question `frame_return_mixed_refusal` asks, one level out: there the
    two answers were two paths of ONE body, and here they are two definitions of
    ONE name — which is what a Mojo overload is, and it is ordinary (`reversed`
    is declared eight times in `std/builtin/reversed.mojo`). A call site carries
    a name and nothing else, so "does `f(...)` hand back a frame address, and
    whose" has to be one answer for the whole image, and here it is not one.

    Both wrong answers are silent, which is why this is a refusal and not a
    choice:

      * answer "frame" for every call, and the definition that returns a word
        leaves the caller's reserved block unwritten — the caller then reads
        whatever the scratch held;
      * answer "word", and the definition that returns a frame writes through a
        block address its caller never reserved.

    Every row is spelled out, because the reader's next question is which
    definition to change and the file's own text is the only thing that can
    answer it.
    """
    parts = []
    for spelling, answer in rows:
        parts.append(f"`{spelling}` returns {answer}")
    return (f"{name} is declared more than once in this module and its "
            f"definitions disagree about whether they return a frame address: "
            f"{'; '.join(parts)}. A call `{name}(...)` names both, so this "
            f"path cannot tell whether to reserve a block for the result — "
            f"reserve one and the word-returning definition leaves it "
            f"unwritten, do not and the frame-returning one copies through a "
            f"block address its caller never passed. Give the overloads one "
            f"return convention (return a field from both, or the frame from "
            f"both), or give the disagreeing ones different names")


def entry_frame_return_refusal(entry) -> str:
    """The ENTRY function returning a frame.

    The convention is "the caller reserves a block and passes its address", and
    the entry function's caller is the C runtime, which passes nothing.  So
    there is no block to copy into, and the only word this function could
    return would be an address into a frame that dies with it — which is the
    use-after-free this whole convention exists to remove, one level up.  Named
    as its own message because "a String receiver is returned from the function
    that created it" is a statement about a lifetime rule the reader would
    spend time re-deriving, when the fact here is simpler: there is no caller to
    hand a block to."""
    return (f"{entry} returns a frame address, and the returned-frame "
            f"convention needs a caller to reserve a block and pass its "
            f"address — and {entry} is this image's ENTRY, so its caller is the "
            f"C runtime, which passes no such word. There is nowhere for the "
            f"copy to land, and the address it would return names a frame that "
            f"dies with this function. Return a field, or a copy of one, which "
            f"is the same program with a lifetime this analysis can follow")


def dylib_frame_return_refusal(module, names) -> str:
    """A frame-returning function offered at a module boundary.

    The hidden word is part of THIS image's calling convention, and a module
    boundary is where that convention stops being knowable: the importer
    compiled the module's source with a different `_frame_receivers` pass, has
    no table saying which of the library's functions take the extra word, and
    passes arguments the way the SOURCE spells them.  So exporting one hands
    the importer a function that copies its caller's block into whatever the
    seventh argument register happened to hold.

    Refused rather than dropped from the export table, and the reason is a
    measured one: `formal/build.py`'s `_method_exports` used to filter wide
    receivers out of the export set, the importer's call had nothing to bind
    to, and the symptom was reported as a layout problem (see
    `byref_cross_module_wide_receiver_reads` in `test_formal_run.py`).
    # Silently changing a module's
    public API is the same defect with a different spelling."""
    return (f"module {module} exports {' and '.join(names)}, which "
            f"{'return' if len(names) == 1 else 'return'} a frame address, and "
            f"the returned-frame convention is a property of ONE image: the "
            f"hidden word that names the caller's block is part of this "
            f"image's calling convention, and an importer has no way to know a "
            f"particular export takes one. Exporting it would hand the "
            f"importer a function that copies into whatever its seventh "
            f"argument register held. Return a field, or a copy of one; that "
            f"is the same program across a boundary with a lifetime both ends "
            f"can see")



_COUNT_WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count_word(n: int) -> str:
    """`n` as a word, because a diagnostic is read rather than parsed.

    Falls back to the digits for anything outside the table rather than
    inventing a word: an argument count above ten is already a refusal about
    the count, and spelling it wrongly would be a second thing to be wrong
    about.
    """
    return _COUNT_WORDS.get(n, str(n))



def returned_frame_library_refusal(name: str) -> str:
    """A dylib cannot export a function that returns a frame.

    The convention needs the CALLER to reserve the block, and the caller is a
    compilation this build does not perform: an importer gets the symbol and
    nothing else, so it would have to reserve a block for a callee whose
    returned width it cannot see. Refusing here is the honest answer rather
    than emitting a function whose every importer gets wrong."""
    return (f"{name} returns a frame address, so it cannot be compiled into a "
            f"dylib: the returned-frame convention needs the CALLER to reserve "
            f"the block the object is built in, and an importer of this library "
            f"is a compilation this build does not perform — it binds the "
            f"symbol and has no way to learn the width of the block it must "
            f"reserve. Build it into the program image instead, where the "
            f"caller and the callee are compiled together")


def receiver_writeback_frame_library_refusal(name: str, owner: str, member: str,
                                             target: str, spelling: str,
                                             frame: str) -> str:
    """A dylib cannot export a one-word mutator that hands its caller a frame
    ADDRESS it built itself.

    `returned_frame_library_refusal`'s hazard reached through the OTHER
    convention, and the sentence it opens with is deliberately the same one,
    because it is the same fact seen from outside: what the importer is handed
    is a symbol after a call which leaves a frame address in storage the
    importer owns. What is different is the register it travels in — there is
    no returned-frame convention here and no trailing hidden word; the value
    goes out through the receiver cell the caller passed in
    (`receiver_writeback_name`), which is why this shape needs its own message
    rather than being reported as the frame return it resembles.

    **Why the write-back is sound for one of the two spellings and not the
    other.** A one-field struct whose sole field holds a FRAME has no object:
    its value IS the nested frame's address, so its receiver is the address of a
    one-word CELL and the cell holds an address. Storing THROUGH that frame
    writes the caller's own bytes — the caller reserved them — and that is
    what the write-back is for. Storing a frame the CALLEE built does not: that
    block is reserved in this function's own prologue scratch
    (`struct_constructor_sites`), and the callee hands the caller the address of
    bytes that stop being its own the moment it returns.

    Measured on the emitted arm64 code, on the two constructors that differ in
    exactly this one store (`self.inner.a = a` against `self.inner = Inner(a,
    b)`, both `def __init__(out self, a: Int, b: Int)` of a struct whose only
    field is a two-slot frame). Both publish the same
    `frame_params: [["Inner", "Inner"], …]`. The write-through one emits
    `ldr x19, [x0]` then `str x0, [x19]` / `str x0, [x19, #8]` — it writes both
    slots of the block the CALLER reserved, which is what the contract says. The
    assigning one emits the two stores into its OWN scratch and then
    `str <that address>, [x0]`: one word into the caller's cell, pointing at a
    frame in a dead activation. A contract that describes the first and is
    published for the second is the wrong answer this path treats as the worst
    outcome available, and the only sound fixes are to refuse the export or to
    stop publishing a block the callee does not write.

    **Refused rather than dropped**, for the reason
    `returned_frame_library_refusal` gives: silently changing a module's public
    API is the same defect with a different spelling. The advice names the
    spelling that has a lifetime both ends can see, because that is what the
    reader has to write instead.

    `owner`/`member` are the class and the method, because the export's name is
    a mangling of both (`Box1___init__`) and a reader who wrote
    `self.inner = Inner(a, b)` needs to be told which of a class's methods the
    boundary is publishing, not handed a symbol to search for. `target` and
    `spelling` are the source's own two halves of the offending statement, in
    the order the source wrote them. `frame` names what the address points at —
    the struct whose frame this function built, or the callee it took one from —
    because "a frame" alone does not tell the reader whether the block is one
    they can see.
    """
    through = (f"Store THROUGH the field instead (`{target}.a = a`), which is the "
               f"same program with a lifetime both ends can see"
               if "." in target else
               f"Store THROUGH the field instead, which is the same program with "
               f"a lifetime both ends can see")
    return (f"{name} returns a frame address, so it cannot be compiled into a "
            f"dylib: `{target} = {spelling}` in {owner}.{member} binds the "
            f"receiver to a frame built in this function's own scratch ({frame}), "
            f"and {owner} has exactly one field, so its receiver IS that field "
            f"and comes back through the caller's own storage — the address "
            f"therefore outlives the frame it names, and an importer of this "
            f"library has no way to learn the width of the block it must "
            f"reserve. {through}")



def returned_frame_blob_refusal(fn_name: str, holder: str, field: str,
                                spelling: str) -> str:
    """A CONTAINER written into the block this function hands back.

    The one hole the convention opens that the by-reference receiver does not:
    premise (B1) says a frame slot never holds a blob, and it is enforced for
    METHODS (`check_frame_field_blob_premises`) because a blob is bump-allocated
    in the function that made it. A returned block outlives the function that
    made it, so a blob in one would be an address into scratch the caller is
    already using for its own frames — and a later `q.items.append(1)` would
    write into the callee's reclaimed stack. The program builds, runs, and
    returns a number nobody wrote."""
    return (f"{fn_name} returns {holder!r}, whose block outlives this "
            f"function, and it assigns {spelling} to {holder}.{field} — a list "
            f"or a dict on this path is a bump-allocated region of the "
            f"function's OWN scratch, so the slot would name bytes this "
            f"function is about to give back and a later append through it "
            f"would write into reclaimed stack. Copy the elements out into the "
            f"returned block's own fields, which is the same program with a "
            f"lifetime this analysis can follow")



# What a FRESH one-word value has to hold, and whether this path can produce it.
#
# `S()` is not a call; it brings every field up at its default. For a struct of
# zero or one field that default is the whole value, so a constructor that
# always emitted 0 was quietly throwing it away — `struct Counter: count = 7`
# with a `get()` that only READS the field returned 0. It built, it ran, and it
# was wrong, which is the one outcome a formal backend may not produce.
#
# Only LITERAL defaults are materialized, deliberately. A default written as a
# name (`count = TABLE_SIZE`) or an expression cannot be evaluated at the
# constructor's call site without knowing what is in scope there, and a
# constructor that guessed would be the same bug wearing a hat. A literal has no
# free names, so there is nothing to resolve and the answer is the same at every
# call site in every function.
DEFAULT_NONE = "none"          # no default to speak of: zero is correct
DEFAULT_INT = "int"
DEFAULT_STRING = "string"      # a formal string is a bare `char *`: one word
DEFAULT_OPAQUE = "opaque"      # a real default this path cannot bring up
# The sole field of a ONE-FIELD struct holds a NESTED FRAME of this module, so
# the word `S()` must leave is that frame's ADDRESS and a word of zeros is a null
# pointer wearing a value's clothes. `one_word_sole_field_frame` is the reader of
# the question and `struct_default_word` is its only caller; `("nested_frame",
# (field_name, nested_struct))` is the answer, and the reservation the address
# names is `struct_constructor_sites`' job (see `struct_constructor_site_bytes`
# for why that is one reader of the size as well).
DEFAULT_NESTED_FRAME = "nested_frame"



# ── `None`, and the word it is ──────────────────────────────────────────────
#
# `None` is a NAME on this front end, not a literal:
#
#     Parser(py_tokenize("b: int = None")).parse_module()[0]
#     AssignStmt(target=IdentExpr(name='b'), value=IdentExpr(name='None'), …)
#
# so neither `fold_literal_expr` nor `literal_default_word` had an arm for it,
# and the single most common class-level default in this repository's own
# dataclasses (`Type.bit_width: Optional[int] = None`, and nine more on the same
# class) was refused as "not a literal" — a message that sends a reader looking
# for a call, where there is no call.
#
# It is a value this target represents exactly: the word 0, which is what an
# unwritten frame slot already is. Folding it is the representation, not an
# approximation, and because both backends and `formal/build.py` read these two
# functions it is one edit rather than three.
#
# What it is NOT is the integer 0, and the one-word model cannot tell them
# apart. `None == 0` is False in Python and True here. So the fold is confined
# to MATERIALIZING a value, and the one construct that can observe the
# difference — a comparison against a folded `None` — is refused by name in
# `refuse_none_comparisons` rather than answered. A distinguishable null is not
# available and is not attempted: the model is one untagged word, so there is
# nowhere for a second bit of "this zero is a None" to live.
NONE_NAME = "None"
NONE_WORD = 0


def is_none_expr(node) -> bool:
    """True when `node` is the NAME `None` (see the note above)."""
    return isinstance(node, F.IdentExpr) and node.name == NONE_NAME




# ── `Optional[T]`: the word `None` IS, per payload type ────────────────────
#
# The paragraph above is the WHOLE of what this target knew about `None`, and
# its last sentence — "A distinguishable null is not available and is not
# attempted" — is the sentence `UNWRAP_METHODS` has been refusing with, on both
# architectures, for the 43-file row the sweep map names.  It is wrong, and the
# measurement that says so is one line long:
#
#     var z: Optional[Int] = 0
#     if z is None: print("WRONG")     # arm64 and x86-64 both print it
#
# Both images built, ran, and reported a `Some(0)` as EMPTY, because the word
# `0` is `None` and the word `0` is also the integer 0.  So the null was not
# merely unavailable, it was AMBIGUOUS, and an ambiguous null answers one of the
# two questions wrongly with no diagnostic — the one outcome this backend's own
# rule ("a wrong answer is the one outcome it may not produce",
# `refuse_none_comparisons`) exists to prevent.
#
# ## The representation, stated once
#
# An `Optional[T]` value is ONE 64-bit word, and that word is the PAYLOAD.
# `None` is a word the payload's type cannot produce — a NICHE — and which
# niche is a fact about `T`, not about `Optional`.  So:
#
#     Optional[T]  ==  the word `niche(T)`, for `None`
#     Some(v)       ==  the word `v`, for a payload `v`
#     x is None     ==  x == niche(T)
#     x == None     ==  x == niche(T)      (a payload cannot BE niche(T))
#     x.or_else(d)  ==  x == niche(T) ? d : x
#     x.unsafe_value() == x
#
# Every one of those is a compare and a conditional on the value word, so the
# PROOF side needs nothing new: `lib/ProofLib.lean` already models a compare
# against an immediate and a conditional branch, and `NONE_WORD` is already the
# immediate it would carry.  That is the whole reason this is a niche and not a
# two-word (tagged) value — see `OPTIONAL_TWO_WORD` for the alternative and for
# what it would cost.
#
# ## Why a niche is SOUND, and when there is not one
#
# It is sound exactly when `niche(T)` is outside `T`'s domain, and the table
# below is the argument for each row rather than a preference:
#
#   * a POINTER-LIKE payload (`String`, `Pointer[T]`, a container, a frame
#     address, any struct of this module) — the word is an ADDRESS, and no
#     address a program can hold is 0.  This is also the word `x is None` has
#     ALREADY meant for a reference on this path, so choosing it makes the
#     Optional answer and the reference answer the same answer.
#   * a `Bool` — a Bool is a word holding 0 or 1 (`formal.types`' own note),
#     so 2 is outside its domain.
#   * a NARROW integer (`Int8`/`Int16`/`Int32`, `UInt8`/`UInt16`/`UInt32`) — the
#     word `1 << w` IS the value `2^w`, and a `w`-bit type's values live in a
#     64-bit register sign-extended (`formal/types.py`), so the set of words it
#     can hold is the value range `[-2^(w-1), 2^(w-1)-1]` and `2^w` is outside
#     every one of them.
#
# And there are types where there is NO such word, and the honest answer for
# them is a REFUSAL rather than the 0 the fold produces today:
#
#   * `Int`, `Int64`, `UInt`, `UInt64` — every one of the 2^64 words is a value
#     of the type (`formal.types`: values live in 64-bit registers, signed
#     types sign-extended), so there is no word left over.
#   * `Float64` — every 64-bit pattern is a double, NaNs included.
#   * `DType` — a type TAG is an index and 0 is a legal one.
#   * `Float32` — measured: `Float32(1.5)` does not lower at all on this target
#     (it becomes a call against a symbol nothing provides), so what word a
#     `Float32` occupies is not established and there is nothing to have a
#     niche FOR.
#   * a payload whose type the source does not state, and a payload that is a
#     struct of another module (whose layout this image cannot see).
#
# `optional_none_word` returns None for exactly those, and every caller turns
# that None into a refusal that NAMES the alternative.  A program that used to
# build and compute the wrong answer now refuses; that is the direction this
# rule moves, and the measurement above is why.
#
# ## `OPTIONAL_TWO_WORD`: what the no-niche row needs, and why it is not here
#
# The other sound answer is a TAGGED TWO-WORD value: a pair `{tag, payload}`,
# where `Optional[T]` is a pointer to it.  It covers every `T` including
# `Int`, and this target already has the machinery for a multi-word value — a
# struct of two fields IS a frame, and `struct_is_framed` /
# `struct_constructor_sites` / `receiver_writeback_name` are the whole of it.
# It is NOT done here for three measured reasons, each of which a later
# session should check rather than take on trust:
#
#   1. `Optional` is a stdlib struct this image does NOT compile, so its frame
#     is not in any module's `structs_by_name` — and `struct_frame_block_bytes`
#     sizes a construction site's reservation out of `decls`, so nothing is
#     reserved for a block whose struct the table does not know.
#   2. `x is None` where `x` is a LOCAL holding the pair's address is a frame
#     slot read through a word that is not a receiver.  Measured: every frame
#     read this path has lowers from a RECEIVER (`self.f`) or from a name whose
#     candidate struct is known, and a name declared `Optional[…]` has no
#     candidate struct here.  See `bugs/formal/FORMAL_a_subscript_on_a_frame_slot_is_a_
#     pointer_dereference_and_the_two_backends_disagree.md` for the shape.
#   3. `x = None` is then a store of a FRAME into a slot, which is
#     `_refuse_holder_use`'s case ("it outlives the frame it names"), and that
#     refusal is `formal13-5`'s claim to answer.
#
# The niche row is what this target can do SOUNDLY today, and it is what makes
# the two-word row decidable rather than guessed at: one table says which `T`
# the two-word form is needed for, so that work is a list and not a project.
#
# ## Why `OptionalReg` is NOT in `OPTIONAL_TYPE_NAMES`
#
# It WAS, and the reason it was given here ("a reader who annotates it must get
# the same answer as one who annotates `Optional[T]`") was the one this section
# exists to refute: the two types do not have the same representation, so giving
# them the same answer gives one of them a wrong one.
#
# `std/collections/optional.mojo:1150` declares
# `struct OptionalReg[T: TrivialRegisterPassable]` with a single field
# `var _value: Self._Storage`, and `_OptionalRegStorageFor[T]`
# (`std/collections/optional.mojo:1144`) picks between TWO storages:
#
#   * `_NicheableOptionalRegStorage[T]`, for a `T` that conforms to
#     `UnsafeNicheable` — `var storage: Self.StorageType`, which is `StaticTuple[
#     T, 1]` unless `T` has an `UnsafeCustomNicheStorage`.  A payload plus a
#     capacity-1 index: **two words**.
#   * `_DefaultOptionalRegStorage[T]` — `var _value: !kgen.variant<T, i1>`, a
#     TAGGED value: **two words**, and the tag is `kgen.variant.is[…]`'s input.
#
# So `OptionalReg[T]` is a pair for every `T` this build cannot read the
# conformance of, where `Optional[T]` here is ONE word holding the payload (the
# table above).  Reading `OptionalReg[Int]` as that one word makes
# `x is None` compare against a niche the pair does not have: for a `Bool`
# payload it would compare against 2, for a `String` against 0, and in both cases
# the answer is about a word that is only half the value.  `Some(0)` and `None`
# being the same word is the ambiguity `bugs/formal/FORMAL_optional_needs_a_niche.md`
# opened this representation to remove, and admitting the two-word sibling under
# the one-word name puts it back for a reader who annotated `OptionalReg`.
#
# The missing fact is NAMED rather than guessed: which of the two storages
# `_OptionalRegStorageFor[T]` selects is a TRAIT CONFORMANCE
# (`conforms_to(T, UnsafeNicheable)`) evaluated at compile time in the stdlib
# module, and this build reads declarations from the unit it is compiling, not
# trait resolution.  So `optional_reg_refusal` says that, and the two-word
# alternative is `OPTIONAL_TWO_WORD`'s — the same project this section already
# prices for `Optional[Int]`.
OPTIONAL_TYPE_NAMES = frozenset({"Optional"})

#: The register-passable sibling, kept as its own name because it is REFUSED
#: rather than answered and the refusal has to be able to say which name it is
#: refusing.  A caller that wants "is this annotation optional-shaped at all"
#: asks `optional_reg_payload_annotation` as well as `optional_payload_annotation`.
OPTIONAL_REG_TYPE_NAMES = frozenset({"OptionalReg"})

# The lowerings this section provides, as names.  `or_else` covers `value_or`
# and `or` because they are the same question with two spellings — a
# conditional between the payload and a default — and spelling them apart would
# be three lowerings to keep in step rather than one.
OPTIONAL_UNWRAP_DEFAULT = "optional_or_else"
OPTIONAL_UNWRAP_PAYLOAD = "optional_payload"

# The Optional methods this target answers, mapped to the lowering.  One table,
# read by both backends, so the two architectures cannot answer `or_else` and
# refuse `value_or` for the same receiver.
OPTIONAL_METHOD_LOWERINGS = {
    "or_else": OPTIONAL_UNWRAP_DEFAULT,
    "value_or": OPTIONAL_UNWRAP_DEFAULT,
    "or": OPTIONAL_UNWRAP_DEFAULT,
    "unsafe_value": OPTIONAL_UNWRAP_PAYLOAD,
}


def optional_payload_annotation(ann) -> str | None:
    """`Optional[Int]` -> `'Int'`; anything that is not an `Optional` -> None.

    The one reader of "is this annotation an `Optional`, and of what", and it is
    a reader of the ANNOTATION TEXT because the value model's one-word
    representation of an `Optional` is exactly why the argument matters: the
    base name says the slot can be empty and the argument says what the word
    holds when it is not, and the argument is the only thing that decides
    whether a `None` word exists at all (see the section note above).

    `Some[F]` — the spelling the stdlib uses for a function-valued optional —
    is NOT here.  It is a different type constructor with its own
    representation question, and treating it as this one would make
    `Some[def() -> Int]` answer with an `Int` niche.  `OptionalReg[T]` is the
    same argument for a different reason and gets its own reader below: it is a
    PAIR, not a word, so answering it as one is a wrong answer rather than a
    missing one.
    """
    if not isinstance(ann, str) or not ann.strip():
        return None
    text = _strip_type_decorations(ann.strip(), None)
    if text is None:
        return None
    base = _strip_type_args(text)
    if base not in OPTIONAL_TYPE_NAMES:
        return None
    args = _split_type_args(text)
    if not args:
        return None
    payload = args[0].strip()
    return payload or None


def optional_reg_base_name(ann) -> str | None:
    """`'OptionalReg'` for `OptionalReg` and for `OptionalReg[Int]`; else None.

    The sibling of `optional_payload_annotation` and deliberately NOT a member of
    it: this one exists so a caller can REFUSE the annotation by name, and a
    reader that answered for both would make the refusal unreachable and put the
    two-word type back under the one-word name. It answers the BASE rather than
    the payload, which is what makes the bare spelling (`var z: OptionalReg`)
    refusable — a type with no argument is still a pair, and a reader that asked
    for the payload would report "not one of those" about it.

    It returns the name rather than a bool so the caller can print what it
    matched, which is the same reason `annotation_base_name` does.
    """
    if not isinstance(ann, str) or not ann.strip():
        return None
    text = _strip_type_decorations(ann.strip(), None)
    if text is None:
        return None
    base = _strip_type_args(text)
    return base if base in OPTIONAL_REG_TYPE_NAMES else None


def optional_reg_refusal(annotation, where: str = None) -> str:
    """Why an `OptionalReg[…]` annotation has no answer on this target.

    `where` names the site (`a parameter of f`, `field S.x`) so a reader is sent
    to the declaration rather than to the type; it is a phrase with no trailing
    punctuation, because the sentence below supplies the rest.
    """
    spelled = annotation if isinstance(annotation, str) and annotation.strip() \
        else "an `OptionalReg`"
    site = f" {where}" if where else ""
    return (
        f"`{spelled}`{site} is the REGISTER-PASSABLE optional, and its storage "
        f"is a PAIR of words rather than one: "
        f"`std/collections/optional.mojo`'s `_OptionalRegStorageFor[T]` is "
        f"`_NicheableOptionalRegStorage[T]` — a `StaticTuple[T, 1]`, the payload "
        f"plus a capacity-1 index — for a `T` that conforms to "
        f"`UnsafeNicheable`, and `_DefaultOptionalRegStorage[T]` — a "
        f"`!kgen.variant<T, i1>`, a tagged value — otherwise. An `Optional[T]` on "
        f"this path is ONE word holding the payload, with `None` a word `T` "
        f"cannot produce (`formal/model.py`'s `optional_none_word` is the one "
        f"table that says which `T` those are), so substituting that niche here "
        f"would compare against a word the value does not have. Which of the two "
        f"storages applies is a TRAIT CONFORMANCE "
        f"(`conforms_to(T, UnsafeNicheable)`) decided inside the stdlib module, "
        f"and this build reads declarations rather than resolving conformances — "
        f"so the fact that decides the layout is not one it has. Annotate the "
        f"receiver `Optional[T]` with a `T` that table answers and `x is None`, "
        f"`x == None`, `x.or_else(…)`, `x.value_or(…)`, `x.or(…)` and "
        f"`x.unsafe_value()` all lower from the one representation")


# A scalar type name -> `(width in BITS, signed)`, or None for a name that is
# not one.  The ONE width table this section reads, and it is here rather than
# taken from `formal.types.TYPE_NAMES` for the reason `STRING_TYPE_CTORS` above
# names its own list "so this module does not have to import types to say it":
# a representation is a fact about the TARGET, and the target's machine word is
# not a property of whichever module happens to have loaded.
#
# It has to agree with `formal.types.TYPE_NAMES` entry for entry, and
# `test_formal_optional.py::the_niche_table_and_the_scalar_types_agree` is what
# keeps it there — the same "one reader plus a test that the second table has
# not drifted" discipline `POINTEE_WIDTHS` above states.  Two tables of widths
# with no test between them is how a `Int32` niche becomes an `Int64` one.
SCALAR_TYPE_WIDTHS = {
    # A Bool is a word holding 0 or 1 (`formal.types`' own note), so its width
    # is 1 and `signed` is carried as None because there is no signedness to
    # get wrong about at one bit. BOTH spellings: `Bool` is Mojo's and `bool`
    # is the unannotated Python one, and a reader who annotates either must get
    # the same niche.
    "Bool": (1, None), "bool": (1, None),
    "Int8": (8, True), "Int16": (16, True), "Int32": (32, True),
    "Int64": (64, True),
    "UInt8": (8, False), "UInt16": (16, False), "UInt32": (32, False),
    "UInt64": (64, False),
    "Float64": (64, True),
    # The UNANNOTATED `int` and Mojo `Int` are `Int64` (formal.types'
    # `DEFAULT_INT_TYPE`), so they are the full-width row and the branch below
    # refuses a 64-bit width precisely because there is no word left.
    "int": (64, True), "Int": (64, True), "UInt": (64, False),
    # **`Float32` is DELIBERATELY ABSENT, and the reason is a measurement
    # rather than a preference.**  It has no width row here because what word a
    # `Float32` occupies on this target is not established: `Float32(1.5)` does
    # not lower at all — it is emitted as a call against the symbol `Float32`,
    # which nothing on the link line provides, and the build is refused with
    # "the image would bind 2 symbol(s) that nothing provides" (measured on both
    # architectures, alongside `Float64`).  So a `Float32` payload has no
    # representation here to have a niche FOR, and answering `Optional[Float32]`
    # would be a claim about a type this backend cannot hold.
}


# The two payload types that are refused for a reason NEITHER the scalar row
# above nor "a struct of another module" states, kept as names rather than
# inferred.  `optional_none_word` used to end in `if base[:1].isupper()`, which
# is a SPELLING test standing in for a fact about the type, and it sent both of
# these down the struct-of-another-module branch: the refusal a user got for
# `Optional[Float32]` and for `Optional[DType]` claimed this build had not read
# a layout, which is a claim about a C struct and neither name is one.  The
# verdict was right in both cases and the EXPLANATION was wrong, which is the
# expensive kind: `doc/ABI.md`'s niche table and `bugs/formal/FORMAL_optional_needs_a_niche.md`
# both list these two as refused, so nothing went red.
#
# So there are THREE reasons a payload leaves no word for `None`, and each is
# now stated by name rather than guessed from a capital letter:
#
#   * FULL WORD — every one of the 2^64 patterns is a value of the type, so
#     there is nothing left over.  `Int`/`Int64`/`UInt`/`UInt64`/`Float64` are
#     answered by `SCALAR_TYPE_WIDTHS`' width-64 row; `DType` is here because a
#     type TAG is an index and 0 is a legal one, and there is no width to put
#     in a table for an index.
#   * NO REPRESENTATION — the target cannot hold the type at all, so there is
#     no word for the payload to occupy and therefore none for `None` to be
#     spelled as.  `Float32` is the only member, and it is a measurement (the
#     comment above).
#   * A STRUCT OF ANOTHER MODULE — the layout that would prove it is in a
#     library this build does not compile.  Unchanged, and now reachable only
#     by a name that is neither of the above.
FULL_WORD_TYPE_NAMES = frozenset({'DType'})
UNREPRESENTED_TYPE_NAMES = frozenset({'Float32'})


def optional_none_word(payload, decls: dict = None):
    """`(niche_word, None)`, or `(None, why)` when `T` has no word left over.

    `payload` is the annotation TEXT `optional_payload_annotation` returns.  The
    order is the argument, and it is the argument `declared_type_kind` makes for
    the same question, so a reader comparing the two functions sees one rule
    rather than two:

      1. a STRING (`STRING_TYPE_CTORS`) — an interned `char *`, never NULL;
      2. a POINTER (`POINTER_TYPE_CTORS`) — an address, never 0;
      3. a CONTAINER (`BLOB_TYPE_CTORS`) — a pointer to a blob with an 8-byte
         count header, never 0;
      4. a STRUCT OF THIS MODULE (`decls`) — a frame address or a one-word
         cell, never 0, and this row is why the function takes `decls`;
      5. a SCALAR (`SCALAR_TYPE_WIDTHS`) — the word `1 << width`, or 2 for a
         `Bool`, and nothing at all at width 64.  A `w`-bit integer's value
         lives in a 64-bit register SIGN-EXTENDED (`formal/types.py`), so the
         set of WORDS it can hold is its own value range and `1 << w` — the
         value `2^w` — is outside every one of them.  `Float32` is absent from
         the table, and that table's own comment is the reason why.

    Everything else returns `(None, why)`.  `why` is a refusal TEXT and not a
    category, because every caller raises it verbatim: two callers spelling "no
    niche" differently is two messages describing the same gap, and a reader who
    has read one has read the other.

    NO VOCABULARIES ARE PASSED IN, and that is a change from the way most of
    this file's tables are parameterised.  Every one of those exists because a
    NAME is a string and two architectures must not each decide what a string
    means — but the four tables consulted here (`STRING_TYPE_CTORS`,
    `POINTER_TYPE_CTORS`, `BLOB_TYPE_CTORS`, `SCALAR_TYPE_WIDTHS`) are all
    already owned by this module, so passing a vocabulary for them would let a
    caller narrow a fact the model has already stated.  `decls` is the only
    argument that is per-image, and it is per-image because it is a fact about
    the declarations rather than about the language.
    """
    if not isinstance(payload, str) or not payload.strip():
        return (None, optional_no_niche_refusal("<unstated>"))
    text = _strip_type_decorations(payload.strip(), None)
    if text is None:
        return (None, optional_no_niche_refusal(payload))
    base = _strip_type_args(text)
    if not base:
        return (None, optional_no_niche_refusal(payload))
    if base in STRING_TYPE_CTORS:
        return (NONE_WORD, None)
    if base in POINTER_TYPE_CTORS:
        return (NONE_WORD, None)
    if base in BLOB_TYPE_CTORS:
        return (NONE_WORD, None)
    if decls is not None and structs_declared(base, decls) is not None:
        # A struct of this module is a frame address or a one-word cell.  Both
        # are addresses, so both are outside the payload's domain for the same
        # reason a `Pointer[T]` is.  Asked BEFORE the scalar row because a
        # struct of this module can be NAMED `Int` in a test fixture, and the
        # representation that decides the niche is the struct's, not the
        # spelling's.
        return (NONE_WORD, None)
    scalar = SCALAR_TYPE_WIDTHS.get(base)
    if scalar is not None:
        width = scalar[0]
        if width == 1:
            return (2, None)                       # a Bool: 0 or 1, so 2 is out
        if width < 64:
            return (1 << width, None)              # 2^w is not a w-bit value
        return (None, optional_no_niche_refusal(payload))
    # A base that is not one of this module's structs, not a scalar this target
    # has a representation for, and not one of the two named rows below is, in
    # every case that reaches here, a STRUCT OF ANOTHER MODULE — and that is a
    # different obstacle from a type that provably has no spare word, because
    # the layout that would prove it is in a library this build does not
    # compile. Said as such rather than as "every word is a value of it", which
    # is a claim about a type this function has not read.
    #
    # The `isupper()` test that used to stand here is a SPELLING test standing in
    # for a fact about the type, and it caught the two rows as well — so a user
    # who wrote a float was told this build had not read a C struct's layout.
    # The verdict was never affected; only the sentence, which is user-facing.
    # See `FULL_WORD_TYPE_NAMES` / `UNREPRESENTED_TYPE_NAMES` for the three
    # reasons and why each is now named.
    if base in UNREPRESENTED_TYPE_NAMES:
        return (None, optional_no_niche_refusal(
            payload, "this target has no representation for it at all — "
                     "`Float32(1.5)` does not lower here — so there is no word "
                     "for the payload to occupy, and therefore none for `None` "
                     "to be spelled as"))
    if base in FULL_WORD_TYPE_NAMES:
        # The default sentence is the right one for this row and is the same
        # one `Int` gets: every 64-bit word is a value of the type. A type TAG
        # is an index, and 0 is a legal index.
        return (None, optional_no_niche_refusal(payload))
    if decls is not None and base[:1].isupper():
        return (None, optional_no_niche_refusal(
            payload, "it is a struct whose fields this build does not compile, "
                     "so the words it can hold are not known here"))
    return (None, optional_no_niche_refusal(payload))


def optional_no_niche_refusal(payload: str, extra: str = None) -> str:
    """Why this `Optional`'s payload leaves no word for `None`, as a refusal.

    Stated as the SHAPE OF THE MISSING THING rather than as "unsupported",
    because the whole point of naming the payload type is that the reader can
    act on it: a `Bool`, a `String` or an `Int32` payload is answered by this
    target today, and the ones that are not are the ones whose every word is a
    value.  `extra` carries the one distinction the table above cannot put in
    the payload spelling alone — a struct of ANOTHER module, whose layout this
    image cannot see, is a different obstacle from a type that provably has no
    spare word, and a reader who is told "every word is a value of it" about a
    struct has been told something this build cannot know.
    """
    because = extra or ("every 64-bit word is a value of it"
                        if not isinstance(payload, str) or not payload.strip()
                        else f"every word is a value of `{payload}`")
    return (
        f"is an `Optional[{payload}]`, and this target has no word to spell "
        f"`None` as for it: {because}. An `Optional` here is ONE 64-bit word "
        f"holding the payload, so `None` has to be a word the payload cannot "
        f"produce (`formal/model.py`'s `optional_none_word`, which is what "
        f"answers `Optional[Bool]`, `Optional[String]`, `Optional[Int32]` and "
        f"every reference-shaped payload from this same table). Answered "
        f"anyway it would have to treat the integer 0 as the empty one, which "
        f"is WRONG about `Some(0)` — measured on both architectures: "
        f"`var z: Optional[Int] = 0; if z is None:` prints the empty branch. So "
        f"this is refused rather than answered. What closes it is the OTHER "
        f"representation: a tagged TWO-WORD value, `{{tag, payload}}`, where "
        f"`Optional[T]` is the address of the pair — which is what "
        f"`formal/model.py`'s `OPTIONAL_TWO_WORD` records, with the three "
        f"measured reasons it is not a one-line change, and which covers every "
        f"payload type including this one")


def optional_unwrap_lowering(method, annotation, decls: dict = None):
    """`(how, niche_word)` for an Optional method call, or `(None, why)` to refuse.

    `annotation` is the RECEIVER's declared type — the `Optional[…]` itself, not
    its payload — because that is the only evidence this function accepts.  A
    receiver whose type the source does not state gets None here, and every
    caller raises the message, which is the difference between "this path
    cannot answer it" and "this path answered it about the wrong type".

    The two lowerings are in the section note above and both are ONE-WORD
    operations on the value:
      * `OPTIONAL_UNWRAP_DEFAULT` — `x == niche ? d : x`, a conditional;
      * `OPTIONAL_UNWRAP_PAYLOAD` — `x`, the identity.  `unsafe_value` is spelled
        "unsafe" in the stdlib for exactly this: Mojo says the value must be
        present, and this target's answer for an absent one is the niche word
        rather than a trap, which is the same thing every other unchecked read
        of a payload does on this path.

    The niche comes back with the lowering rather than being asked for twice,
    because a caller that lowered `x == niche ? d : x` from a DIFFERENT niche
    than the one it materialized `None` as is a program that is right about
    every value and wrong about the empty one, which is the failure this whole
    section is about.
    """
    how = OPTIONAL_METHOD_LOWERINGS.get(method)
    if how is None:
        return (None, None)
    payload = optional_payload_annotation(annotation)
    if payload is None:
        return (None, optional_unwrap_refusal(method, annotation))
    word, why = optional_none_word(payload, decls)
    if word is None:
        return (None, why)
    return (how, word)


def optional_unwrap_refusal(method: str, annotation) -> str:
    """The refusal for an Optional method whose receiver's type is not usable.

    Two sentences and a name each, because the reader's next action is one of
    exactly two: state the receiver's type if the source has one and this build
    cannot see it, or read the two-word note if it does.
    """
    spelled = annotation if isinstance(annotation, str) and annotation.strip() \
        else None
    declared = (f"its declared type is `{spelled}`" if spelled
                else "the source states no type for it")
    return (
        f"`{method}()` is an `Optional` unwrap and {declared}, so this target "
        f"cannot say which word of it is the empty one. An `Optional[T]` here "
        f"is one 64-bit word holding the payload, and `None` is a word `T` "
        f"cannot produce — `formal/model.py`'s `optional_none_word` is the one "
        f"table that says which `T` those are, and this receiver is not one of "
        f"them. Annotate the receiver `Optional[T]` with a `T` this table "
        f"answers, and `x is None`, `x == None`, `x.or_else(…)`, `x.`"
        f"value_or(…)`, `x.or(…)` and `x.unsafe_value()` all lower from the one "
        f"representation")


# The ATTRIBUTE NAME of the per-function table `formal/build.py`'s
# `apply_optional_none_representation` publishes for a name whose type comes
# from a CALL's return type rather than from a declaration, and which both
# backends read. It is a NAME rather than a string spelled at each site because
# the publisher and the two readers are three places, and an attribute that two
# of them spell `getattr(fn, "_optional_receiver_types")` is a third spelling
# waiting to happen. `formal/build.py` cannot be imported from a backend (it
# imports both of them), so the shared name lives here with the rest of the
# representation.
OPTIONAL_RECEIVER_TYPES = "_optional_receiver_types"


def optional_local_declared_annotation(fn, name: str) -> str | None:
    """The annotation `fn` gives the LOCAL `name`, or None.

    The one reader of "what did this function's own `var` say", and it is
    separate from `param_annotation` because a local's declaration is a
    statement in the body rather than an entry in the signature, and because
    the two are read at different places: a parameter is bound before the body
    runs and a local only at its `VarDecl`.

    The LAST binding wins, which is the flow-insensitive choice this file makes
    everywhere else (`ValueKinds` records a name bound to two kinds as
    undecidable; here a name re-declared with a different annotation is a
    re-declaration the source does not make, and taking the first would answer
    about a binding that is not the one in force).  `AssignStmt` is read as well
    as `VarDecl` because the lowered program keeps both and `x: Optional[Int] = 5`
    arrives as the former on some paths.
    """
    found = None
    for node in iter_nodes(getattr(fn, "body", None)):
        if isinstance(node, F.VarDecl) and node.name == name:
            found = node.type_ann
        elif isinstance(node, F.AssignStmt) \
                and isinstance(node.target, F.IdentExpr) \
                and node.target.name == name:
            ann = getattr(node, "annotation", None)
            if isinstance(ann, str) and ann.strip():
                found = ann
    return found if isinstance(found, str) and found.strip() else None


def struct_default_word(struct_def, decls: dict = None) -> tuple:
    """`(kind, payload)` — what `S()` must leave in the word for this struct.

    ("none", None) when there is no class-level initializer to honour, which
    includes every field with no value (`x: Int`) and every zero-field marker:
    a fresh word of zeros is right for both, and is what the constructor emitted
    before this existed.

    ("int", n) / ("string", s) when the sole field's default is that literal,
    which both backends can materialize exactly (a string is its own address).

    ("opaque", field_name) when there IS a default and it is not a literal —
    a container, a name, a computation. The caller must refuse rather than
    substitute 0, because substituting 0 is precisely the wrong answer this
    function exists to prevent.

    **("nested_frame", (field_name, nested_struct)) when the sole field holds a
    FRAME**, which is the case ("none", None) used to answer and must not. A
    one-field struct's receiver IS its field, so that word is an address;
    "no initializer, so a fresh word of zeros is right" is true of every other
    field and false of this one, and the two answers together are a null pointer.
    Measured on both architectures: `struct Box1: var inner: Inner` with
    `bx = Box1(); bx.inner.a = 1` built, ran, and died with SIGSEGV (exit 139)
    on the first field read, with no diagnostic anywhere
    (fixed 2026-10-03 in 4af77b16, where a one-field struct whose
        sole field holds a frame brings that frame up instead of a null
        word).

    `decls` is what makes the question answerable at all — it is the module's
    struct table, which is how the field's declared type is read — so it is a
    parameter rather than a global, and a caller that has none keeps the old
    answer. `one_word_sole_field_frame` is the ONE reader of "does this sole
    field hold a frame", because two copies of that question would eventually
    disagree about which structs are addresses and the disagreement is a
    segfault rather than a message. Only a field with NO default reaches the new
    kind: a non-literal default on a frame-valued field is still `opaque`, which
    is the honest refusal, and a literal one is a different bug.

    Only meaningful for a struct of at most one field; a wider one brings each
    of its fields up separately, through `struct_frame_defaults`.

    **("int", niche) for an `Optional[...]` field is the one row added by the
    `Optional` representation, and it is asked FIRST because the default of an
    empty `Optional` is `None` — which is a word chosen by the representation
    and not always the word 0.** `var flags: Optional[Bool]` with no
    initializer leaves a fresh instance's slot holding `None`, and `None` for a
    `Bool` payload is 2, so leaving 0 there would make `h.flags is None` (which
    compares against 2) answer "set" about an instance nobody had set. The
    reader is `optional_field_none_word`, shared with `struct_field_default`, so
    the one-field and the many-field readers cannot disagree about what an
    absent `Optional` is."""
    if struct_field_count(struct_def) != 1:
        return (DEFAULT_NONE, None)
    field_name = struct_sole_field_name(struct_def)
    default = None
    for field in struct_fields(struct_def):
        if struct_field_name(field) == field_name:
            default = getattr(field, "value", None)
            break
    kind, payload = literal_default_word(default)
    if kind == DEFAULT_NONE:
        niche = optional_field_none_word(struct_def, field_name, decls)
        if niche is not None:
            return (DEFAULT_INT, niche)
    if kind == DEFAULT_NONE and decls:
        nested = one_word_sole_field_frame(struct_def, decls)
        if nested is not None:
            return (DEFAULT_NESTED_FRAME, (field_name, nested))
    return (kind, field_name if kind == DEFAULT_OPAQUE else payload)


def optional_field_none_word(struct_def, name, decls: dict = None):
    """The `None` word for an `Optional[...]` FIELD, or None if it is not one.

    `None` here is the DEFAULT of the field: `var step: Optional[Int]` declares
    no initializer, so a fresh `Slice()` leaves that slot empty, and "empty" is
    a word the representation chooses (`optional_none_word`'s table).  The
    function returns None for a field that is not an `Optional`, and also for an
    `Optional` whose payload has no niche — the second is not a refusal AT THIS
    POINT because a field that is never read as an `Optional` is harmless, and
    raising here would refuse a struct whose `Optional` field is only ever
    written.  The read is where the obligation is real, and that is
    `optional_unwrap_lowering` / `formal/build.py`'s
    `apply_optional_none_representation`.

    `decls` is the module's struct table for the same reason it is an argument
    everywhere else in this file: whether the payload is a struct of THIS module
    decides the niche, and that is a fact about the image rather than about the
    language.
    """
    base, ann, _why, is_declared = struct_field_declared_type(struct_def, name)
    if not is_declared or not isinstance(ann, str):
        return None
    payload = optional_payload_annotation(ann)
    if payload is None:
        return None
    word, _why = optional_none_word(payload, decls)
    return word


def literal_default_word(value, bound=()) -> tuple:
    """`(kind, payload)` for a class-body initializer — the ONE reading of it.

    A literal has no free names, so its value is the same at every read site in
    every function and either backend can materialize it exactly. Anything else
    — a name, a call, a container display — needs a scope this path does not
    have at a use site, and is (DEFAULT_OPAQUE, None) so each caller can name
    what it could not bring up.

    Shared by `struct_default_word` (a field's default, materialized by the
    constructor) and `class_constant_word` (a class-level constant, materialized
    at each read of it) because they are the same question asked of the same
    node, and two copies of this decision would eventually disagree about which
    defaults are representable.

    **The fold is `fold_literal_expr`'s, not a second one.**  This used to
    spell out its own arms for `None` / `IntLiteral` / `BoolLiteral` /
    `StringLiteral`, so it was the same classifier as `fold_literal_expr` with
    the unary and binary arms missing — and a class-level constant is exactly
    where a signed literal appears. `class C: A = -3` parses to
    `UnaryOp('-', IntLiteral(3))`, the one token wider than `3` and exactly
    representable in the word `3` already is, and it was REFUSED with a message
    claiming the value "is not a value this build can materialize" — false, and
    actively misleading, because there is nothing non-literal in the reader's own
    source to go and look at. Measured:

        $ python3 fire.py build --formal --no-prove t.py    # class C: A = -3
        build: C.A reads a class-level constant of C, whose value is `-3` — and a
        formal value is one 64-bit word with nowhere to keep a non-literal one…

    `enum` is where it was first reached, because an enum member's `.value` IS
    the class constant (`enum_member_accessor`), and a negative member is
    ordinary. Every fold that folder can do is therefore exact here too, and
    `None` keeps its own answer by being distinguished BEFORE the fold: no
    default at all is (DEFAULT_NONE, None) and a default that does not fold is
    (DEFAULT_OPAQUE, None), which are two different facts about the slot."""
    if value is None:
        return (DEFAULT_NONE, None)
    folded = fold_literal_expr(value, None, bound)
    if isinstance(folded, bool):
        return (DEFAULT_INT, int(folded))
    if isinstance(folded, int):
        return (DEFAULT_INT, folded)
    if isinstance(folded, str):
        return (DEFAULT_STRING, folded)
    return (DEFAULT_OPAQUE, None)


# The accessors CPython's `enum` puts on a MEMBER, and the bases that make a
# class one. A class deriving from any of these has members whose `.value` is the
# class constant itself and whose `.name` is the constant's own spelling — which is
# the whole of what `enum` asks of this path, and the reason `enum.mojo` can be
# written at all.
#
# Transitive through `struct_derived_names`, so `class Reg(MyEnumBase)` is
# recognised as well as `class Reg(Enum)`.
ENUM_BASES = frozenset(("Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
                        "ReprEnum"))


def struct_is_enum(struct_defs, struct_name: str) -> bool:
    """True when `struct_name` derives from one of CPython's `enum` bases.

    The gate on `enum_member_accessor`, and the reason it is a question about the
    CLASS rather than about the member access. `S.NAME.value` is only an enum
    member's value when `S` IS an enum: on a plain class CPython raises
    `AttributeError` (`'int' object has no attribute 'value'`, measured), so
    answering it there would be inventing an attribute the class does not have.

    `struct_derived_names` already answers "which structs derive from THIS name"
    for one name, so this asks it once per enum base and ORs — the transitive walk
    is that function's, not a second copy of its fixed point. It takes a LIST of
    StructDefs (it reads `name`/`bases` off each), so a caller holding the usual
    `{name: struct}` mapping passes `list(...values())`; `_values` below does it so
    no caller has to remember.

    The base is matched by NAME because that is all this path has: `class
    Reg(Enum)` records `bases == ['Enum']` and the enum machinery behind the name
    is never run, so the names above ARE the rule. A program that defines its own
    class called `Enum` is indistinguishable here from CPython's — which is the
    same answer this path already gives for any other erased base, and the same
    direction it takes when it cannot see a derivation (see
    `struct_is_derived_from`)."""
    if not struct_name:
        return False
    if struct_name in ENUM_BASES:
        return True
    return any(struct_name in struct_derived_names(_struct_def_values(struct_defs),
                                                  base)
               for base in ENUM_BASES)


def _struct_def_values(struct_defs) -> list:
    """The StructDefs in `struct_defs`, whether it is a list or a name mapping.

    `struct_derived_names` and `struct_is_derived_from` both read `name`/`bases`
    off what they are given, so they want a LIST — and every caller of the
    derivation helpers in `formal/build.py` holds a `{name: struct}` mapping,
    because that is what the constant census is keyed by. Normalizing here is what
    lets both take either, which is the alternative to every call site remembering
    (and `struct_is_enum` was wrong for exactly that reason when first written)."""
    if isinstance(struct_defs, dict):
        return list(struct_defs.values())
    return list(struct_defs or [])


def enum_member_accessor(struct_defs, struct_name: str, member: str):
    """`'value'` / `'name'` when `S.member` is an enum member's accessor, else None.

    The two attributes CPython gives every `enum` member, and the two that carry
    an answer this path can produce exactly:

      * `S.NAME.value` is the class constant `NAME` holds — the SAME literal
        `S.NAME` itself materializes to (`class_constant_word`), because on this
        path a member is not an object and so the member and its value are one
        word. Verified against CPython: for `Reg.RAX = 0`, `Reg.RAX.value` is 0.
      * `S.NAME.name` is the constant's own spelling as a string, which is the
        member's `name` in CPython and needs nothing but the declaration site.

    Gated on `struct_is_enum` because that is what makes the read an enum
    accessor's rather than an arbitrary attribute: `S.NAME.foo` is still an
    `AttributeError` in CPython, and so is `S.NAME.value` on a class that is not
    an enum. Returning None for those keeps this from inventing an attribute."""
    if member not in ("value", "name"):
        return None
    return member if struct_is_enum(struct_defs, struct_name) else None


def class_constant_word(name: str, default, bound=()) -> tuple:
    """`(kind, payload)` — what a read of the class constant `name` yields.

    The same contract as `struct_default_word`, for the other kind of class-body
    initializer: a class-level constant is not brought up by `S()` (there is no
    constructor to bring it up in — a constant has one value for every instance,
    so it is not part of the value), it is materialized where it is READ.

    Which is why a constant that is not a literal has to be refused rather than
    read as the zero an unwritten slot would give: there is no module-global
    storage on this path (see the backends' handling of `global NAME`), so a
    bare `S.NAME` read has nothing to bind to, and 0 would be a plausible-
    looking wrong number rather than a crash."""
    kind, payload = literal_default_word(default, bound)
    return (kind, name if kind == DEFAULT_OPAQUE else payload)


def class_constant_reference(node) -> tuple | None:
    """`(struct name, constant name)` when `node` is `S.NAME`, else None.

    The narrowest possible recogniser, and deliberately so: the two-node path
    with a BARE name for the base, which is the spelling a class body uses for
    another class's constant (`origin: TypeOrigin = TypeOrigin.DEFAULT`,
    `KIND = Flags.DEBUG`). A dotted base (`mod.Klass.NAME`) would be a
    cross-module read with a dylib boundary in it, and a base this image binds
    to something else is not the class it is spelled like — so both stay out
    rather than being resolved by a guess.

    It exists because the class-constant rewrite already knows how to answer a
    read of `S.NAME` (it substitutes the literal the constant holds, measured
    on both architectures: `return Origin.B` in a method builds, runs and
    prints 2), and what it could not do was answer one from INSIDE another
    constant's initializer — the outer site consumes the whole node, so the
    inner reference was never reached. That is this repository's
    `type_system.py`, whose `Type.origin` defaults to `TypeOrigin.DEFAULT`
    (an enum member, which is the ordinary way to write this) and which is the
    sweep's `codegen` row for "a class-level default that is not a value this
    build can materialize".
    """
    import fire_compiler as F
    if not isinstance(node, F.MemberExpr) or node.member in ("value", "name"):
        return None
    base = node.obj
    if not isinstance(base, F.IdentExpr) or not isinstance(base.name, str):
        return None
    return (base.name, node.member)


def class_constant_word_in(structs_by_name: dict, node,
                           seen=frozenset(), bound=()) -> tuple:
    """`(kind, payload)` for a class-body initializer that may NAME a constant.

    `class_constant_word` first — a literal answers there and the reference
    machinery is never reached. Past that, the one shape this adds is a
    reference to another class-level constant of a struct THIS IMAGE DECLARES
    (`class_constant_reference`), resolved through that constant's own
    initializer and no further: a chain is followed because each link is a
    declaration this build can read, and it stops at the first initializer that
    is not.

    `seen` is the set of `(struct, constant)` pairs already being resolved on
    this path, and it is what makes `A.X = B.Y` / `B.Y = A.X` answer
    `(DEFAULT_OPAQUE, ...)` instead of recursing until Python's stack gives up:
    a cyclic definition has no value, and the honest answer for it is the same
    refusal a call gets.

    The payload for a cycle or an unresolvable initializer is the SPELLING of
    the constant the read started at, not `None`, so a caller that refuses can
    name the thing a reader would have to change — `class_constant_word`'s own
    convention, which `_constant_literal` carries through to its message.

    This is the CLASS-BODY position, and `enum_member_literal` below is the
    FIELD-DEFAULT one; both answer "what does `S.NAME` hold" and neither can be
    moved into the other, because the two are asked at different moments and of
    different nodes. A dataclass field's default is materialized BEFORE anything
    reads it (`formal/build.py`'s rewrite, one pass over the fields, so every
    later reader sees a literal), which needs the LITERAL NODE to put in place of
    the member read; a class constant's initializer is materialized where the
    read is, which needs a `(kind, payload)` this function already returns. They
    agree by construction rather than by two rules that happen to match: the
    field rewrite has already replaced the node by the time a constant is asked
    about it, and this function's `literal_default_word` short-circuit answers
    first when it is not.
    """
    kind, payload = literal_default_word(node, bound)
    if kind != DEFAULT_OPAQUE or not isinstance(structs_by_name, dict):
        return (kind, payload)
    ref = class_constant_reference(node)
    if ref is None:
        return (kind, payload)
    owner, const_name = ref
    if (owner, const_name) in seen:
        return (DEFAULT_OPAQUE, f"{owner}.{const_name}")
    st = structs_by_name.get(owner)
    if st is None:
        return (kind, payload)
    for name, default in struct_class_constants(st):
        if name != const_name:
            continue
        return class_constant_word_in(structs_by_name, default,
                                      seen | {(owner, const_name)}, bound)
    return (kind, payload)


def enum_member_read(struct_defs, expr):
    """`"S.NAME"` when `expr` reads an ENUM MEMBER, else `None`.

    The one shape `refuse_enum_member_comparisons` asks about, and it is
    deliberately narrow: `Reg.NAME` and nothing else. A `.value` read
    (`Reg.NAME.value`) is a read of the VALUE, which is a word this path can
    compare, and a read through a slot (`t.origin`) is a read of whatever the
    slot holds — also a word. Only the bare member is the construct with no
    representation, and widening this to the other two would refuse
    `x.kind == y.kind`, which is a comparison of two values and answers itself.

    Gated on `struct_is_enum` for the reason `enum_member_accessor` states: on a
    class that is not an enum, `S.NAME` is a class constant and its value is a
    word, so there is nothing to refuse. `NAME` must be one of the class's own
    constants, which is what keeps `Reg.__name__` and a method reference out.
    """
    if not isinstance(expr, F.MemberExpr) or not isinstance(expr.obj, F.IdentExpr):
        return None
    st = (struct_defs or {}).get(expr.obj.name)
    if st is None or not struct_is_enum(struct_defs, expr.obj.name):
        return None
    if expr.member not in {name for name, _default in struct_class_constants(st)}:
        return None
    return f"{expr.obj.name}.{expr.member}"


def enum_member_comparison_refusal(left: str, right: str, op: str,
                                   enum_name: str) -> str:
    """Why `Reg.A == Reg.B` is refused: two MEMBERS are not two words.

    ARCH-FREE, asked from the shared pass beside `refuse_none_comparisons`
    (`formal/build.py`), and for the same reason: the fold that makes a member
    materializable is lossy in exactly one direction — two DISTINCT members with
    the same value are one word — so the one construct that can observe the
    difference is refused by name.

    **The measured wrong answer this closes**, both architectures:

        class Reg(Enum):
            A = 1
            B = 1

        if Reg.A == Reg.B:  →  prints ‘same’; CPython says False

    `Reg.A == Reg.A` answers True for the wrong reason too, and that one is
    invisible — which is why the rule refuses the shape rather than trying to
    distinguish the two cases: there is nowhere in one untagged word to record
    WHICH member a word holds, so the question "are these the same member" has
    no answer here and only the reader can say.

    The repairs are named because ‘an absent answer is the answer’ is only
    useful with a next step: compare the VALUES (`Reg.A.value == Reg.B.value`),
    which is what the source usually means when it is asking about two members of
    the same enum, or branch on a value the model can tell apart. The cost of the
    rule is stated here rather than left to be discovered: a field of an enum
    type is a WORD on this path, so `x.kind == y.kind` and `x.kind == Kind.A`
    both still work, and only a comparison of two bare member reads is refused.
    """
    return (
        f"`{left}` and `{right}` are both reads of MEMBERS of the enum "
        f"`{enum_name}`, and `{op}` between two members asks whether they are the "
        f"SAME member. This path has no representation for that: a member and "
        f"its value are one 64-bit word (`model.enum_member_accessor` says so, "
        f"and a member read materializes to its value), so two distinct members "
        f"whose values are equal are one word and compare equal — measured, both "
        f"architectures, `A = 1` and `B = 1` answered `Reg.A == Reg.B` True where "
        f"CPython says False. Compare the VALUES when that is what you mean "
        f"(`{left}.value == {right}.value`), or branch on something the model can "
        f"tell apart. A field of an enum type is a word too, so `x.kind == y.kind` "
        f"and `x.kind == Kind.A` are both still answered — only two bare member "
        f"reads are refused."
    )


def enum_member_literal(struct_defs, expr):
    """The LITERAL an enum member read holds, or `None`.

    `Reg.DEFAULT` → the `StringLiteral` `"default"` that is `Reg`'s constant
    `DEFAULT`, because on this path a member and its value are one word
    (`enum_member_accessor` states it and a bare `Reg.A` materializes to its
    value — measured, `printf("%d", Reg.A)` prints 7 for `A = 7`). A member whose
    constant does not itself fold to a literal answers `None`, which is the
    honest refusal rather than a guess: the member is then a word holding
    something this path cannot name, and every position that materializes a
    value has to say so.

    **This is the value-model question the enum machinery was asking, answered
    once here.** The aggregate note at the top of this file (“what a value
    is”) records the answer — a member IS its value, and the member's IDENTITY
    is not in the word — and this is the reading of it that the default
    positions use, while `enum_member_comparison_refusal` is the consequence
    that follows from the same answer: if a member is its value, two members
    with equal values are one word, so a comparison between two member reads is
    refused rather than answered. The two must not be able to disagree, which is
    why both live here and neither in a caller.

    `struct_is_enum` gates it for the reason `enum_member_accessor` states: on
    a class that is not an enum, `S.NAME` is a class constant whose value is a
    word in its own right, and materializing it is `class_constant_word`'s job
    with no question left to ask.
    """
    st = (struct_defs or {}).get(getattr(getattr(expr, "obj", None), "name", "")
                                 or "") if isinstance(expr, F.MemberExpr) else None
    if st is None or not struct_is_enum(struct_defs, st.name):
        return None
    for name, default in struct_class_constants(st):
        if name != expr.member:
            continue
        folded = fold_literal_expr(default)
        if isinstance(folded, bool):
            return F.IntLiteral(value=int(folded))
        if isinstance(folded, int):
            return F.IntLiteral(value=folded)
        if isinstance(folded, str):
            return F.StringLiteral(value=folded)
    return None


def struct_fits_one_word(struct_def) -> bool:
    """True when the struct's whole state is a single word.

    Zero fields (a marker) and one scalar field are both exactly one word: for
    the single-field case the receiver IS the field, so `self.n` is `self` and
    no indirection is needed anywhere. The count is the DERIVED one, so a class
    that assigns its field in `__init__` gets the same treatment as one that
    declares it — which is what makes `self.n` and `c.n` the same storage
    instead of two unrelated words that happen to share a spelling.

    A `False` here no longer means "cannot be lowered" once
    `wide_receiver_by_reference()` is on: it means "not a one-word value", and
    `struct_is_framed` is the question that decides which of the two
    representations the receiver gets."""
    return struct_field_count(struct_def) <= 1


def method_function_name(struct_name: str, method_name: str) -> str:
    """The internal symbol a struct's method compiles to.

    Flat and module-agnostic, because it has to be callable from a direct BL
    within one image; the module-qualified ABI spelling is applied at the
    export boundary (see abi_method_symbol) where it is actually needed."""
    return f"{struct_name}_{method_name}"


def abi_method_symbol(module_prefix: str, struct_name: str,
                      method_name: str) -> str:
    """The boundary symbol for a struct method, per doc/ABI.md.

    Module-qualified, so two modules' same-named structs never collide in one
    library — the same reason a free function's export is qualified."""
    return f"{module_prefix}_{struct_name}_{method_name}"


def struct_methods(struct_def) -> list:
    return list(getattr(struct_def, "methods", None) or [])


def find_method_owner(structs: dict, method_name: str):
    """The struct that declares `method_name`, or None.

    Dispatch here is by name alone because that is all a `recv.m()` call site
    carries: the receiver's type is not inferred on this path. A method name
    declared by two structs in one module is therefore ambiguous, and the
    caller is expected to refuse it rather than pick one."""
    owners = [st for st in structs.values()
              if any(m.name == method_name for m in struct_methods(st))]
    if len(owners) == 1:
        return owners[0]
    return None


def structs_declaring_method(structs, method_name) -> list:
    """The candidate structs that declare a METHOD called `method_name`.

    The question a field read has to ask before it can say "this struct has no
    such field", and the reason the answer changes what the refusal says: a
    member access `recv.m` in a VALUE position is not a field access when `m` is
    one of the receiver's own methods — it is the bound method, and a bound
    method is not a word, so there is no slot to read it out of and nothing to
    store it in.  `find_method_owner` answers this over the WHOLE module's dict;
    this one is over the candidate list the caller already holds, because the
    diagnostic has to name the struct the RECEIVER is rather than the one that
    happens to declare the name.

    Every declaring struct is returned rather than one, for the reason
    `find_method_owner` returns None for two: a name two structs declare is
    ambiguous, and the caller's business is to say so, not to pick.
    """
    return [st for st in (structs or ())
            if any(m.name == method_name for m in struct_methods(st))]


def _slot_rows(candidates, name):
    """`[(struct_name, slot_or_None), …]` — the disagreement table, for a message.

    `struct_frame_slot_candidates` computes exactly this and returns it inside
    its second element; this recomputes it for the one caller that is building a
    message rather than making a decision, and the recomputation cannot disagree
    because both read the same `struct_frame_slots` list.  It exists so that
    `member_read_without_a_field` needs only the candidate list.
    """
    return [(st.name, struct_frame_slot(st, name)) for st in (candidates or ())]


def ambiguous_method_specialization_refusal(chain, member, owners) -> str:
    """`recv.m[T](x)` where two structs in this image declare `m`.

    A refusal whose stated reason was **entirely false**, which is the defect
    class `test_refusal_taxonomy.py` exists to hold this path to.
    It was refused as `b.run names 'run', which is a METHOD of Box … a
    value-position method reference is a bound method`, which is a claim about a
    program that has no such reference in it: `b.run[3](4)` is a CALL, the
    brackets bind `run`'s comptime parameter, and the sentence told the reader to
    add parentheses to a program that already had them.

    The reason it cannot be lifted is narrower than any of the sentences that
    replaced it, and it is a fact about THIS MODULE'S DECLARATIONS rather than
    about the backend's capabilities:

      * `_rewrite_method_calls` dispatches by NAME, because a receiver's type is
        not inferred on this path, so `run` has no single owner to lift to;
      * and `Box` and `Other` both declare it, so picking either would compile
        the callee against one struct's field list and call it with a receiver
        that may be the other — a wrong answer with exit 0.

    So the reader's next step is in their own source, and this says which of the
    two things they can do about it.  `formal/model.py`'s own
    §18 measured the shape across the corpus: it is what still refuses
    `std/runtime/_asyncrt.mojo` and `std/utils/index.mojo` of the eight files the
    sweep reported as value-position method references.

    **`owners` is every struct that declares `member`, and the message names all
    of them rather than the receiver's own** — deliberately.  Nothing here
    establishes which struct `{chain.split('.')[0]}` holds: a receiver's type is
    not inferred on this path, which is the premise of the whole refusal. So a
    version that said "whose type is Box — the receiver's OWN struct" would be
    asserting the very thing it cannot know, and it would be asserting it in the
    clause that decides the verdict.

    **The advice is a RENAME and nothing else, and that is measured rather than
    guessed.**  Qualifying the call with the owning struct — `Box.run[...](...)` —
    reads as the obvious fix and does not work: a specialization of a DOTTED
    callee is not `recv.m(x)`, so `_rewrite_method_calls` has no receiver to
    prepend and no parameter list to read, and it lands on
    `frame_opaque_position_refusal`'s `callee_shape` arm instead.  Measured on
    this very program with the qualification added: refused with "The callee of
    this call is Box.run[3], which names no function this pass has a parameter
    list for".  That is the fifth shape the deleted
    `FORMAL_method_call_on_a_subscripted_receiver` recorded, and offering
    it here would send the reader into a second refusal with the first one
    closed.  A rename is enough: with one `run` in the image the name
    dispatches, and the lift is the ordinary one.
    """
    names = ", ".join(st.name for st in owners)
    holder = chain.split(".")[0]
    return (
        f"{chain}[…](…) is a method CALL — the brackets bind a generic's "
        f"comptime parameters, so this is `{chain}(...)` and not a subscript of "
        f"a value — and {member!r} is declared by {names}. It cannot be lifted "
        f"because all of them declare it: dispatch on this path is by NAME, "
        f"since a receiver's type is not inferred, so there is no one function "
        f"to lift this call to, and binding any of them would compile the "
        f"callee against that struct's field list and call it with a receiver "
        f"that may be a different one — a wrong answer rather than a failure. "
        f"Rename one of them, so that the name dispatches to a single "
        f"declaration; writing the call out (`{holder}.{member}[...]` becomes "
        f"`{owners[0].name}_{member}[...]({holder}, ...)`) also works"
    )


def member_read_without_a_field(chain, holder, name, candidates) -> str:
    """Why `holder.<name>` has no slot: a message, for the three real shapes.

    `struct_frame_slot_candidates` reports DISAGREEMENT and nothing else, and its
    one caller printed every disagreement as "this name holds a frame address in
    more than one shape" — which is false for the two shapes that actually
    occur most, and both of them say something a reader can act on:

      * ONE candidate, and it does not have the field.  There is nothing to
        disagree with, so "more than one shape" describes a disagreement that
        does not exist.  What the reader needs is that the struct simply has no
        such field — which in Python is an `AttributeError` at run time, and so
        is usually a program that raises on the first run rather than one that
        needs an annotation.
      * The name is a METHOD of the receiver's own struct.  `self.helper` (no
        parentheses) is not a field read at all: it is a bound method, and this
        path has no bound-method values.  Reading slot `k` for it would read
        whichever field happens to be at `k`, and `k` is not even determined —
        which is why this is a refusal and not a slot lookup.  Measured, on
        `formal/arm64_codegen.py`'s own `self._untyped_callee`: the previous
        message told the reader two layouts disagreed when there was one layout
        and one candidate.
      * TWO OR MORE candidates, which is the disagreement the original message
        was written for.  Kept, because there it is true.

    Shared because both backends' frame passes raise from this shape and one
    message is what keeps the two architectures from drifting on it.

    The FIRST two shapes are refusals of shapes this path has no representation
    for, and that is the whole of what changed: the class of program that
    refuses is identical and the sentence about why is no longer a description
    of a disagreement that did not happen.

    **What is deliberately NOT a fourth shape here**, and its absence is a
    measurement rather than an oversight.  A METHOD CALL this pass could not lift
    — `b.run[3](4)` with `Box` and `Other` both declaring `run` — used to arrive
    at this function and be reported by the second bullet above, which is false
    about it in every clause: it is a call and not a value-position reference,
    and `run` is a method of the receiver's OWN struct, which is the hand-off
    cross-module hand-off measures to be sound (`test_formal_run.py`'s
    # `byref_cross_module_wide_receiver_writes`).  It has its
    own message, `ambiguous_method_specialization_refusal`, reached from
    `formal/build.py`'s `check_module_symbols` instead — which is where the
    BRACKET is examined, and therefore the only place the ambiguity is knowable
    (`iter_nodes` has no parent, so nothing here can tell a call's subscript from
    a subscript of a value).  A flag on this function carrying that fact would
    have been an argument the caller does not have.
    """
    owners = structs_declaring_method(candidates, name)
    if owners:
        return (
            f"{chain} names {name!r}, which is a METHOD of "
            f"{', '.join(st.name for st in owners)} rather than one of its "
            f"fields: a value-position method reference is a bound method, and "
            f"a method is not a word — there is no slot to read it out of and "
            f"nothing to store it in, so this path has no representation for it. "
            f"Call it (`{holder}.{name}(...)`), which is a receiver and a call "
            f"and lowers, or write the operation out where it was used"
        )
    # NO candidate has the field, as against SOME having it and some not. Both
    # reach here as `disagree`, because `struct_frame_slot_candidates` reports
    # "these candidates do not agree on a slot for `name`" and "no candidate has
    # one" with the same `(None, (True, rows))` — the second is a special case of
    # the first, and its docstring says so. The single-candidate case below
    # already reads correctly ("`W1` has no field `x`"), so this branch is only
    # for TWO OR MORE candidates, and it exists because with several the old
    # sentence claimed a conflict that does not exist.
    #
    # Measured on `std/io/io.mojo`, whose `buffer.unsafe_mut_cast` produced
    # "_FlushingWriteBuffer has no such field; _FixedWriteBuffer has no such
    # field" and then "the shapes do not agree on where 'unsafe_mut_cast'
    # lives". They agree perfectly — neither has it, and `unsafe_mut_cast` is a
    # method of `Pointer` — so the reader was sent to two structs' layouts
    # instead of to the receiver's type. The method branch above cannot catch
    # it, because that searches the CANDIDATE structs and `Pointer` is not one:
    # the candidates are what `buffer`'s own bindings are, not the types its
    # members come from.
    rows = _slot_rows(candidates, name)
    if len(candidates) > 1 and all(sl is None for _sn, sl in rows):
        return (
            f"{chain} is a field of {holder}, and NO candidate has field "
            f"{name!r} — "
            + "; ".join(f"{sn}: {struct_field_summary(cand)}"
                        for (sn, _sl), cand in zip(rows, candidates))
            + ". So this is not a disagreement between layouts, which is what "
              "the candidates-not-agreeing case would say: there is nothing to "
              "disagree about, and no slot index is being chosen between them. "
              f"{name!r} is something the receiver's own structs do not spell "
              f"out at all — a method of the receiver's type rather than one of "
              f"its fields, or a field reached through a base this path does not "
              f"flatten — or the program raises at run time, since in Python a "
              f"missing attribute is an AttributeError. Refused rather than read "
              f"a word it cannot place: a frame slot holds one 64-bit word and "
              f"there is no `k` to read"
        )
    if len(candidates) == 1:
        st = candidates[0]
        # A base this unit does not declare makes the sentence below FALSE, and
        # a false sentence sends the reader to the wrong line. `Sub(Base)` where
        # `Base` is a trait, a builtin, or a class from a module this image
        # cannot read inherits whatever fields that base has, so `s.x` is a
        # field read in CPython too and the program is NOT raising here. What is
        # missing is the base's DECLARATION, which is a different repair
        # entirely — and the merge (`attach_inherited_fields`) is what turned
        # this from a fact about every subclass into a fact about the bases this
        # image cannot read.
        undeclared = struct_unresolved_bases(st)
        if undeclared:
            return (
                f"{chain} is a field of {holder}, and {st.name} has no field "
                f"{name!r}: its {struct_field_summary(st)}. It derives from "
                f"{', '.join(repr(b) for b in undeclared)}, which this image "
                f"does not declare, so the fields it inherits are not in the "
                f"layout this path can see — and it is NOT an AttributeError "
                f"in the program, because CPython inherits them. Declare "
                f"{undeclared[0]} in this module, or declare {name!r} on "
                f"{st.name} itself. Refused rather than read a word it cannot "
                f"place: a frame slot holds one 64-bit word and there is no "
                f"`k` to read"
            )
        return (
            f"{chain} is a field of {holder}, and {st.name} has no field "
            f"{name!r}: its {struct_field_summary(st)}. In Python this is an "
            f"AttributeError at run time, so the program is very likely already "
            f"raising here — but this path refuses rather than read a word it "
            f"cannot place, because a frame slot holds one 64-bit word and "
            f"there is no `k` to read: the name is not in the layout at all"
        )
    return (
        f"{holder}.{name} cannot be placed: this name holds a frame address in "
        f"more than one shape, and the shapes do not agree on where {name!r} "
        f"lives — " + "; ".join(
            f"{sn} puts it at slot {sl}" if sl is not None
            else f"{sn} has no such field" for sn, sl in _slot_rows(candidates,
                                                                   name))
        + ". Which one applies depends on the path taken, and this analysis has "
          "none, so a slot index computed from either would read the wrong word "
          "on the other: the program would build, run, and return a number the "
          "source never wrote"
    )


def method_owner_names(structs: list) -> dict:
    """{`<Struct>_<method>` function name: struct} for every declared method.

    The reverse of find_method_owner, for the compiler side: after a method is
    lifted to a function, this is what identifies which struct's layout the
    body is written against."""
    out = {}
    for st in structs:
        for m in struct_methods(st):
            out[method_function_name(st.name, m.name)] = st
    return out




# ── NAMES: where a binding lives, module-level and otherwise ───────────────
#
# `G = 5` at module level, read from inside a function, returned **10 on arm64
# and 0 on x86-64** where the source says 5 — the same program, two answers.
# That is not a language fact and it is not an arithmetic fact; it is a
# register-allocation accident, and the two architectures disagreed about it
# precisely because each was reading whatever its own allocation happened to
# leave behind. Measured, on the pre-change tree:
#
#   arm64  read_g():  add x0, x19, #0      ; `_load_var`'s fall-through
#   x86-64 read_g():  movq $0x0, %rax      ; the same fall-through, reading 0
#
# and the reason the arm64 answer is *10* is that X19 is callee-saved and its
# caller had left the program's `test_input` in it. `_store_var` has the same
# fall-through on arm64 (`mov x19, src`), so a write to a name the analysis does
# not know is a silent store into whatever the next function will read as its
# first parameter. Wave 5's rule — on x86-64 a *missing* branch is a dropped
# store, not a wrong value — is the same defect with the other symptom.
#
# The fix is not a wider guard. It is that "is this name a local of THIS
# function" is a question with a table behind it, and the table was missing:
# a module-level binding is a statement in the module, and the module's
# statement list is the one place a name's home is stated outright. Everything
# below is that statement list, read once, published, and consulted by both
# backends' local collection.
#
# WHY A GLOBAL IS FOLDED RATHER THAN STORED, AND WHEN IT IS STORED. A global
# that is only ever READ needs no storage, because nothing ever stores it:
#
#   * a function body that assigns the name binds a LOCAL `G` (in Python and in
#     Mojo), and a local shadows the module's — so a function that writes `G`
#     never writes the global, and one that does not is reading the one value
#     the module-level sequence gave it;
#   * the module-level sequence is the only writer, and the build walks it in
#     order, so the build knows the final value;
#   * a folded value has no free names, so it is the same at every read site in
#     every function, which is exactly the premise
#     `literal_default_word`/`class_constant_word` already rely on for a
#     class-level constant on this path.
#
# So a READ-ONLY module constant is SUBSTITUTED at every read site — not
# cached, not materialized, substituted.
#
# THE OTHER HALF, WHICH THE ORIGINAL NOTE SAID DID NOT EXIST: `global NAME`
# inside a function body is a statement this path used to treat as a no-op, so
# the following `NAME = ...` bound a LOCAL and the write was lost. That is a
# SILENT WRONG ANSWER, and it is measurable: `G = 5` at module level with
# `def bump(): global G; G = G + 1` printed `G=5` where CPython prints `G=7`
# (measured on this tree, 2026-09-29) — the read was the substituted 5 and the
# write went into a register nothing else names.
#
# A name that a function WRITES needs storage with STATIC STORAGE DURATION — a
# location that outlives every frame, because the writer and the reader are
# different functions and only one of them is on the stack at a time. So the
# image carries a `__DATA` segment with one 8-byte slot per such name, the
# module-level sequence's final value is the slot's static initializer, a read
# is a load from the slot and a write is a store to it. That is the same
# two-way answer as before, with the second half stated: FOLD when the name is
# read-only, STORE when some function writes it.
#
# What storage does NOT buy, and this is the boundary the rest of this section
# is about: a frame address still outlives nothing, so a global may not hold a
# pointer into a frame. A module-level CONTAINER is fine (its blob is built
# once, before any function runs, and goes in `__DATA` beside the slots); a
# container BUILT INSIDE A FUNCTION and stored into a global is a use-after-free
# and is refused by `global_value_refusal` below.


class GlobalSymbol:
    """One module-level binding: its name, and what the build knows about it.

    `literal` is the folded value — an `F.IntLiteral` / `F.StringLiteral` /
    `F.BoolLiteral` node — or None when the name is not foldable. `site` is the
    spelling for a diagnostic ("assigned at module level", "re-bound at module
    level", "declared at module level with no value", "imported from `m`"),
    because the four are different mistakes with different repairs and one
    generic message sends the reader to the wrong line.

    `none_valued` says the folded word is the word `None` is spelled as, which
    `literal` cannot: the fold represents `None` as `IntLiteral(0)` (NONE_WORD),
    so the fact that this zero is a `None` and not the integer 0 is gone by the
    time the node exists. It is kept here rather than re-derived at each use
    site because the one construct that can observe the difference is a
    comparison, and a comparison that answered "0 == 0 is True" for a `None`
    would be a wrong answer rather than a refusal.

    `defining` is the name the DEFINING module spells this one, and it is
    different from `name` exactly when the import has an `as`. Both are needed
    and neither is derivable from the other: every read and every call site in
    this unit spells the LOCAL name, while the export table of the linked
    library is keyed by the DEFINING one — so a reader that asks "does this
    module publish that name" with the local spelling answers about a name
    nobody publishes. `import_bindings` has reported both since it was written
    ("the DEFINING name, which is only ever different from the local one when
    there is an `as`, and which is the name the export table is keyed by"), and
    this is the field that keeps that promise load-bearing for a diagnostic
    rather than only for a call."""

    __slots__ = ("name", "literal", "site", "module", "line", "none_valued",
                 "defining")

    def __init__(self, name, literal=None, site="assigned", module=None,
                 line=0, none_valued=False, defining=None):
        self.name = name
        self.literal = literal
        self.site = site
        self.module = module
        self.line = line
        self.none_valued = none_valued
        self.defining = defining

    def __repr__(self):
        return (f"GlobalSymbol({self.name!r}, literal="
                f"{self.literal is not None}, site={self.site!r})")


# Published by `publish_module_symbols`, for the same reason and with the same
# shape as `attach_placed_frame_callees`: the consumer that needs it is a
# node walk inside a backend with no unit in hand, and a module-level dict
# threaded through every signature would be a second, driftable copy of the
# same fact.
_MODULE_SYMBOLS: dict = {}


def publish_module_symbols(table: dict) -> None:
    """Install `table` as the current unit's module-level symbol table.

    Replaces, never merges: two units compiled in one process (a dylib and its
    dependent, an import chain) must not accumulate each other's globals, and a
    merge would be indistinguishable from a union that is never right."""
    global _MODULE_SYMBOLS
    _MODULE_SYMBOLS = dict(table or {})


def module_symbols() -> dict:
    """The published `{name: GlobalSymbol}` table. Empty before a publish."""
    return _MODULE_SYMBOLS


def module_symbol(name: str):
    """The `GlobalSymbol` for a module-level `name`, or None."""
    return _MODULE_SYMBOLS.get(name)


def module_constant_literal(name: str):
    """The folded literal a module-level `name` has, or None.

    The read side both backends and `build.py`'s substitution ask, and the one
    that decides whether a read of this name is ANSWERABLE rather than merely
    refused."""
    sym = _MODULE_SYMBOLS.get(name)
    return sym.literal if sym is not None else None


# The literal-only expression folder. Deliberately tiny and deliberately
# literal-only: its whole job is to decide "can the build KNOW this value", and
# every operator added here is one more way for a fold to be wrong. `-`, `+` and
# `~` on integers and `+ - * //` between integers is the closure that covers the
# module-level constants in this repository (`_PASS = 0`, `_CMP_OPS = 6`,
# `_BIN_OPS = 8`, `CASE_TIMEOUT = 30 * 2`, and `std/utils/_serialize.mojo`'s
# `_kCompactElemPerSide = _kCompactMaxElemsToPrint // 2`).
#
# `~` was the one operator here that every RUNTIME already lowered and no
# compile-time folder folded, which is the same hole `//` was and with the same
# repair: `comptime c = ~3` was refused by `mojo/middle/comptime.py:eval_const`
# while both formal backends emit MVN/NOT for it (`arm64_codegen`'s `~` arm and
# `x86_64_codegen`'s, each with the comment saying which of the two was missing),
# so the compiled value and the emitted code disagreed about whether the program
# was knowable at all. It is in all three folders now — `eval_const`,
# `eval_const_int` and this one — because a folder that declines an operator
# another folder in the same build folds is answering a different question from
# the one it is asked, and `~n` is exact for every integer (CPython agrees:
# `~3` is `-4`, and the word it is computed in is the word it is stored in).
#
# `//` is the same operator `mojo/middle/comptime.py:fold_arith` gained, and
# for the same reason, and the two must not drift: that folder decides what a
# FUNCTION's own `comptime NAME = …` binds, this one decides what a
# MODULE-level one binds, and `comptime_fold_refusal`'s text tells the reader
# to write "an expression of literals and other `comptime` names" — which is
# one folder's rule spoken for both. Python's `//` is floor division and the
# backends' runtime division is truncation toward zero (`_emit_div_shift_pow`
# says so), so for a NEGATIVE literal the two disagree by design; a compile-time
# fold has to answer the SOURCE's question, and this is the source's operator.
# A literal-zero divisor raises out of the lambda and is caught one line below,
# the same shape `fold_arith` uses, so a module constant divided by zero lands
# in the refusal rather than in a `ZeroDivisionError` traceback.
_FOLD_BINOPS = {"+": lambda a, b: a + b,
                "-": lambda a, b: a - b,
                "*": lambda a, b: a * b,
                "//": lambda a, b: a // b}

# The unary sign operators this folder folds, and what each one DOES to the
# folded word. Kept as a table rather than an `if` chain so the third folder
# (`mojo/middle/comptime.py:eval_const`) spells the same rule and the two can be
# compared by reading, which is the whole of the "must not drift" note above.
_FOLD_UNARY = {"-": lambda v: -v,
               "+": lambda v: v,
               "~": lambda v: ~v}


def fold_literal_expr(node, names=None, bound=()):
    """The value of `node` when it is literal-only, else None.

    None means "the build does not know this", which is a refusal and not a
    zero — the distinction `literal_default_word` already draws, and the reason
    this returns None rather than 0 for an opaque expression.

    `None` folds to the word 0, which is the representation rather than an
    approximation (see NONE_WORD), and it is the one folded value that is not
    interchangeable with the integer 0 it is spelled as —
    `refuse_none_comparisons` is what keeps the two apart.

    `names` is the ONE caller-supplied thing, and it exists for
    `fold_module_value` alone: a `{name: already-folded value}` a module-level
    initializer may read. Every other caller passes nothing and gets exactly
    the previous behaviour, because a name is a value only where the build has
    already decided what that name's value is — and one place does: the
    module-level table `collect_module_symbols` builds in source order. A
    literal folder with a free name in it is the thing that produced a
    fabricated word, so the parameter is deliberately narrow rather than a
    general "resolve names" hook.

    **`bound` is the second, and it exists for the one arm that reads a NAME.**
    `len(<display>)` is the only shape below whose value is a function of the
    expression rather than of the expression itself, and it is here because the
    value the corpus's class bodies compute is `len(<the literal an
    instantiation supplied>)` — a closed-form function of a constant, and the
    one thing `the variadic bracket arity and the `len(<display>)` fold (landed in e72a5f93)` §5
    item 2 measured as missing. `bound` is the names the ENCLOSING SCOPE binds,
    so a `len` that is a field, a bracket parameter or a module symbol refuses
    rather than being read as the builtin; a reader with a scope passes it and a
    reader without one passes nothing, which is the same default the rest of
    this function has always had."""
    if isinstance(node, F.IdentExpr) and names:
        known = names.get(node.name)
        if isinstance(known, (int, str)) and not isinstance(known, bool):
            return known
        return None
    if isinstance(node, F.IntLiteral):
        try:
            return int(node.value)
        except (TypeError, ValueError):
            return None
    if is_none_expr(node):
        return NONE_WORD
    if isinstance(node, F.BoolLiteral):
        return 1 if node.value else 0
    if isinstance(node, F.StringLiteral) and not getattr(node, "is_bytes", 0) \
            and isinstance(node.value, str):
        return node.value
    if isinstance(node, F.UnaryOp) and node.op in _FOLD_UNARY:
        v = fold_literal_expr(node.operand, names, bound)
        if isinstance(v, int) and not isinstance(v, bool):
            return _FOLD_UNARY[node.op](v)
        return None
    if isinstance(node, F.BinaryOp) and node.op in _FOLD_BINOPS:
        a = fold_literal_expr(node.left, names, bound)
        b = fold_literal_expr(node.right, names, bound)
        if isinstance(a, int) and isinstance(b, int) \
                and not isinstance(a, bool) and not isinstance(b, bool):
            try:
                return _FOLD_BINOPS[node.op](a, b)
            except (TypeError, ValueError, ZeroDivisionError):
                return None
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.IdentExpr) \
            and node.func.name == "len" and node.func.name not in bound \
            and not (node.kwargs or []):
        # `len(<a display>)`, and ONLY over a display: a name's length is not
        # knowable here and a starred element's is not knowable at all, so both
        # refuse. The elements' own values do not matter — `len([x, y])` is 2
        # whatever `x` and `y` are — which is why the count is over the
        # ELEMENTS and not over a fold of them.
        arg = node.args[0] if len(node.args or []) == 1 else None
        if isinstance(arg, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            elements = list(getattr(arg, "elements", None) or ())
            if not any(isinstance(e, F.UnaryOp) and e.op == "*" for e in elements):
                return len(elements)
    return None


def fold_module_value(node, names=None):
    """The value of a module-level INITIALIZER this build knows, or None.

    Four folders, deliberately separate and deliberately in this order.
    `fold_literal_expr` stays literal-only — its own comment is right that every
    operator added there is one more way for a fold to be wrong, and it is
    shared with the struct-field, class-constant and default-parameter readers,
    which have no target to consult and are not asking the same question. This
    one answers the initializer shapes that are not a value the source wrote
    plainly:

    * a `#kgen.param.expr<…>` template about the target this build is emitting
      (`std/sys/info.mojo`'s `_TargetType` machinery, and the `_PLUGIN_COUNT`
      arithmetic beside it);
    * a `FloatLiteral`, truncated toward zero;
    * the VALUE-SELECTING and BOOLEAN shapes — `a if c else b`, `and`, `or`,
      `not`, and a comparison — whose operands are themselves constants, in
      `fold_module_select_expr`. That one is the third bullet for a reason worth
      stating here rather than only there: **deciding these is what keeps a
      module-level store out of the module BODY, and a store in the body is what
      makes the body the entry**, so a folder that declines a decidable value
      does not merely miss a substitution — it changes which function the image
      runs. Measured, both architectures, no `max` anywhere in the program:

          TOP = 3 + 9         ; def main(): return TOP   -> 12
          TOP = 9 if 1 else 3 ; def main(): return TOP   ->  0
          TOP = 9 if 0 else 3 ; def main(): return TOP   ->  0

      and the 0 is not a dropped value (the store lands, and reading it back
      answers CPython) but a body that outranked `main`. Its docstring is the
      argument; this is the caller.

    **The float arm is the module-level one, and where it sits is the whole
    argument for it.**  `formal/arm64_codegen.py` and `formal/x86_64_codegen.py`
    each lower a `FloatLiteral` with `int(expr.value)` — "formal is int-only;
    truncate toward zero (matches a C cast)" — and `formal/types.py` types it as
    `DEFAULT_INT_TYPE` for the same reason, so a module-level float constant was
    the ONE literal whose value both backends already knew and neither folder
    answered.  The consequence was not a missing capability but a wrong
    classification: `collect_module_symbols` got `None`, so the name was recorded
    `rebound` rather than `assigned`, `module_body`'s `_is_folded_constant`
    declined it, and a store the image holds became "code that has to run" — a
    dylib was then refused for having a body at all, and told the reader that
    "this module's API is its top-level statements", which is a statement about
    the module's API and not about the one fact that matters (`96.0` is a
    constant, and four of the six body statements of this repository's own
    `tools/memslot.py` are float constants).

    Substituting the truncated word at a read is exactly what the same literal
    written at that read site would produce — the folder answers a question about
    the CONSTANT, and the emitters answer the same question the same way about a
    literal.  That is the test this arm has to pass to live in this folder rather
    than in `fold_literal_expr`: for `x = 2.5; return x` the image is 2 on both
    sides of the substitution, so folding decides nothing about the value and
    only about whether the store is redundant.  A float that is NOT a literal
    (`X = 2.5 * other`) is still not folded, so its name stays `rebound` and a
    read of it is refused by name rather than guessed.

    The result is not a guess because the target is not a guess: it is the
    `arch`/`fmt` pair `compile_formal` was called with, which the linker is
    about to act on. What the build cannot state — a CPU feature, the target's
    own triple spelling — comes back as None, which is the same "does not know"
    the literal folder returns, so the caller keeps one code path and a
    non-folding binding keeps its existing refusal.

    `names` is passed straight through to `fold_literal_expr` and is the
    module-level table's own already-folded values, so an initializer may read
    a name an EARLIER module-level statement bound. That is not a second
    resolution rule: it is the same rule `mojo/middle/comptime.py:eval_const`
    applies to a function-local `comptime` binding, which resolves its operand
    names out of the bindings already recorded for the same function — and the
    module level is the same fact about the same source shape, at the same
    point in the same order. Before, one of the two halves existed and the other
    did not, and the message told the reader to write exactly the half that was
    missing."""
    folded = fold_literal_expr(node, names)
    if folded is not None:
        return folded
    folded = fold_module_int_expr(node, names)
    if folded is None:
        # The VALUE-SELECTING and BOOLEAN forms, in the same folder and for the
        # same reason — see `fold_module_select_expr`'s own docstring, which is
        # the argument for why this is not "just add TernaryExpr to the folder".
        folded = fold_module_select_expr(node, names)
    if folded is not None:
        # ONE range check, here, on the value that would be substituted: a
        # module-level slot is a word in `__DATA` and a read of this name is
        # replaced by this value, so a value outside the word is not folded and
        # the read keeps the refusal it already had. Inside the folder nothing
        # is range-checked, because every operator there is exact on Python ints
        # and what the machine computes is decided once, at the end.
        if isinstance(folded, int) and not isinstance(folded, bool) \
                and _FOLD_INT_MIN <= folded <= _FOLD_INT_MAX:
            return folded
    got = target_template(node)
    if got is not None and got[0] == "value":
        return got[1]
    # `int()`, not `round()` and not a bit pattern: it is the expression both
    # emitters evaluate for a `FloatLiteral` and `formal/types.py`'s
    # `DEFAULT_INT_TYPE` already means, so this arm and the emitters cannot
    # disagree about the word a float constant is. A `bool` cannot arrive here
    # (`fold_literal_expr` returns one for a `BoolLiteral` and returned above),
    # and a `nan`/`inf` spelling has no literal node to reach this.
    if isinstance(node, F.FloatLiteral):
        try:
            return int(node.value)
        except (TypeError, ValueError, OverflowError):
            return None
    return None


# The integer binary operators a MODULE-LEVEL initializer may be folded with,
# and what each one does to the folded word. A separate table from
# `_FOLD_BINOPS` for the reason `fold_module_value`'s own docstring gives for
# keeping its arms out of the shared literal folder: `fold_literal_expr` is also
# the struct-field, class-constant and default-parameter reader, and those have
# no target to consult. This one does, so this is where an operator whose
# machine answer is worth being exact about belongs.
#
# **Six of these are RING operations, which is what makes folding them safe
# without checking their operands.** Each of `+ - * & | ^ << **` (with a
# non-negative exponent) is a homomorphism modulo 2**64: the machine computes
# every intermediate in a 64-bit word and wraps, Python computes it exactly, and
# the two agree on the low 64 bits however large the intermediate was. So a
# final value that FITS a signed word is the machine's value, and
# `MAX64 = 2 ** 63 - 1` is answerable even though its `2 ** 63` does not fit on
# its own. What must be checked is the RESULT, and only the result.
#
# `>>` is not in that set and is why it is handled apart: a right shift of a
# wrapped intermediate is not the shift of the exact one, so both of its
# operands have to be words before it is applied.
#
# `%` is deliberately NOT here. Python's `%` floors (it answers `-7 % 3 == 2`)
# and both machines' `sdiv`/`idiv` truncate (`-1`), so folding it would put a
# number in the constant that no image on either architecture computes. It is
# the one operator that would be a wrong answer rather than a missing one, and
# the formal path's own integer semantics live in `mojo/middle/comptime.py`.
_FOLD_MODULE_BINOPS = {
    "**": lambda a, b: a ** b,
    "<<": lambda a, b: a << b,
    ">>": lambda a, b: a >> b,
    "&": lambda a, b: a & b,
    "|": lambda a, b: a | b,
    "^": lambda a, b: a ^ b,
}

# `>>` alone, for the reason `_FOLD_MODULE_BINOPS` gives: it is the one
# operator here whose answer depends on the operand being a word rather than on
# its low bits, so both of its operands are range-checked before it is applied.
_FOLD_WORD_OPERANDS = frozenset({">>"})

# The signed 64-bit range a folded module constant has to land in. The formal
# path's word is 64 bits wide (`formal/arm64_proof_gen.py`'s `UInt64` model, and
# `formal/types.py`'s `DEFAULT_INT_TYPE`), and a module-level slot is a word in
# `__DATA`: an initializer whose value does not fit one has no representation
# here, so it is not folded and its read keeps the refusal it already had.
_FOLD_INT_MIN = -(1 << 63)
_FOLD_INT_MAX = (1 << 63) - 1


def fold_module_int_expr(node, names=None):
    """The EXACT value of an int-only `BinaryOp`/`UnaryOp` initializer, or None.

    **No range check happens here** — `fold_module_value` makes that one, once,
    on the value it is about to substitute. That is what lets the folder answer
    `MAX64 = 2 ** 63 - 1` and `MIN64 = -(2 ** 63)`, whose own intermediates are
    a word outside the word: the machine computes every intermediate in a 64-bit
    word and wraps, and each operator here is a homomorphism modulo 2**64, so
    the low 64 bits of the exact result are the machine's word whatever the
    intermediates were. Whether that word is a value the SOURCE has is the
    caller's question and not this function's.

    **The one gap this closes is a refusal whose stated reason was false.**
    `A = 1 << 20`, `A = 2 ** 62` and `A = MASK & n` are how this repository's
    own source spells a constant, and none of them folded, because
    `_FOLD_BINOPS` had four arithmetic operators and no bitwise or shift among
    them. The name then read as `rebound` rather than `assigned`, so the read
    reached the emitter as a bare `IdentExpr` and the build refused
    "print() cannot tell whether IdentExpr is a string or a number" — a message
    about print's materialization for a name the build had read and simply could
    not fold. Measured on `test_formal_math.py:isqrt_source`
    (`MAX64 = 2 ** 63 - 1`, `bugs/formal/FORMAL_proof_coverage_census_2026-10-03.md`
    §0.6), where it also made the two backends report DIFFERENT subjects for one
    function: arm64 stopped at the constant, x86-64 got as far as the string
    operand two lines later.

    Both operands must be ints — a string operand makes the whole expression a
    format or a concatenation, which is `FORMAL_string_value_model.md`'s subject
    and not this table's — and every operator is one whose Python answer is the
    machine's.
    """
    def operand(child):
        value = fold_literal_expr(child, names)
        if value is None:
            value = fold_module_int_expr(child, names)
        if value is None:
            # The third folder, so a CONDITIONAL nested inside arithmetic is
            # decided rather than refused: `(9 if 1 else 3) + 1` is 10 and CPython
            # says 10. Asked here as well as from `fold_module_value` because
            # these two folders recurse into each other — without this arm the
            # nesting depended on which folder happened to be asked first, which
            # is the one kind of asymmetry a reader cannot see.
            value = fold_module_select_expr(child, names)
        return value

    def as_int(value):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None

    if isinstance(node, F.UnaryOp) and node.op in _FOLD_UNARY:
        value = as_int(operand(node.operand))
        return None if value is None else _FOLD_UNARY[node.op](value)
    if not isinstance(node, F.BinaryOp):
        return None
    a = as_int(operand(node.left))
    b = as_int(operand(node.right))
    if a is None or b is None:
        return None
    if node.op in _FOLD_MODULE_BINOPS:
        # `>>` is the one operator here whose answer is not a function of the low
        # 64 bits: a shift of a wrapped intermediate is not the shift of the
        # exact one, so both of its operands have to be WORDS before it is
        # applied. Every other operator in the table is exact whatever the
        # intermediates were, which is why this check is not the general one.
        if node.op in _FOLD_WORD_OPERANDS and not (
                _FOLD_INT_MIN <= a <= _FOLD_INT_MAX
                and _FOLD_INT_MIN <= b <= _FOLD_INT_MAX):
            return None
        try:
            return _FOLD_MODULE_BINOPS[node.op](a, b)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None
    if node.op in _FOLD_BINOPS:
        # The four operators that were already here, unchanged: a constant too
        # big for a word has been getting a truncated one since before this
        # table existed, and tightening that is a separate change with its own
        # blast radius (every module-level integer in the tree).
        try:
            return _FOLD_BINOPS[node.op](a, b)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


# The COMPARISONS a module-level initializer may be folded with, and what each
# one decides. A separate table from `mojo/middle/comptime.py::compare_op` on
# purpose rather than by accident: that one answers for a function's own
# `comptime` binding and is a member of the self-hosted tier (a dict of
# lambdas cannot link there, which is why it is an if/elif chain), while this
# one is asked at build time by CPython. Same rule, two tiers — the arrangement
# `fold_unary_sign` documents for `_FOLD_UNARY`, and for the same reason.
_FOLD_COMPARE = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

# `and` / `or`, as the two short-circuit selects they are. NOT lambdas over
# both operands: Python evaluates `a and b` as `b if a else a`, so the LEFT
# alone decides the result whenever it is falsy, and `a or b` as `a if a else
# b` — the mirror. A table entry would have to evaluate `b` to answer, which is
# both wrong for a `b` the build cannot fold and a way to turn a short circuit
# into an eager one; `fold_module_select_expr` reads the left operand itself.
_FOLD_SELECT_OPS = ("and", "or")


def fold_module_select_expr(node, names=None):
    """The value of a module-level CONDITIONAL initializer, or None.

    `a if c else b`, `a and b`, `a or b`, `not a`, and a comparison — the five
    shapes whose value CPython decides from operands that are themselves
    constants. They are here, in the MODULE-level folder, rather than in
    `fold_literal_expr`, for the reason that function's own comment gives for
    keeping its arms out: it is also the struct-field, class-constant and
    default-parameter reader, and none of those asks this question.

    **AND THE REASON THIS IS A FIX RATHER THAN A NEW OPERATOR is the entry
    point, which is where the wrong answer actually came from.** A module-level
    initializer that this folder cannot decide is recorded `rebound` rather
    than `assigned`, and `module_body`'s `_is_folded_constant` therefore KEEPS
    the store as a top-level statement. A non-empty module body is the image's
    entry (`entry_function` rule 1), so `main` is displaced: a program whose
    whole point is `def main(): return TOP` stops running `main` and answers the
    body's own trailing `return 0`. Measured on both architectures, with the
    condition a LITERAL and no `max` anywhere:

        TOP = 3 + 9        ; def main(): return TOP   -> 12   (folds)
        TOP = 9 if 1 else 3; def main(): return TOP   ->  0   (did not fold)
        TOP = 9 if 0 else 3; def main(): return TOP   ->  0   (did not fold)

    So the value was never dropped — the STORE is correct, and reading it back
    from a function answers CPython on both architectures — and the sentence
    "a module-level store of a conditional expression is zero" was a wrong
    description of an ENTRY-POINTER selection. The fix is the one this folder
    was missing: decide the value, so the store is recognised as already-in-the-
    image and `main` is the entry as the source plainly intends.

    **Python's short circuit is preserved, and that is what keeps this from
    evaluating something the machine would not.** Only the operand that decides
    the result has to fold: `f() if 1 else 3` is 3 (CPython never calls `f`),
    while `3 if f() else 9` is not foldable at all because the CONDITION has to
    be known to choose the arm. The same rule gives `a and b` → `a` when `a` is
    falsy without looking at `b` at all.

    **Truthiness is CPython's, and only over an int.** `0` is false and any
    other int is true, which is also what both machines' `cset`/`jnz` compute
    over a word, so a `TernaryExpr` condition folded to an int decides the same
    arm the emitter would. A STRING is deliberately not a condition: a `char *`
    here points at interned `__TEXT` bytes and an EMPTY literal is still a
    non-null pointer, so `"a" if "" else "b"` would be `1` on the machine and
    `"b"` in CPython — a fold that would put a wrong value in the image rather
    than leave one out. That is the same reason `refuse_none_comparisons`
    exists, and the refusal direction here is the safe one.

    A `None` anywhere in the shape does not fold, for the reason
    `collect_module_symbols`'s `remember` gives: `NONE_WORD` is `0` wearing
    `None`'s spelling, so folding `3 if 1 else None` to a value a later
    initializer could add to `7 + <that>` is exactly the conflation that
    function refuses."""
    def operand(child):
        value = fold_literal_expr(child, names)
        if value is None:
            value = fold_module_int_expr(child, names)
        if value is None:
            value = fold_module_select_expr(child, names)
        return value

    def as_int(value):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None

    def part(child):
        """The folded value of an OPERAND, refusing one this cannot decide.

        `None` — the NAME — is refused here rather than folded to `NONE_WORD`,
        for the reason the docstring gives; a `str` is kept, because a string
        constant is a real folded value (`folded_literal_node` builds a
        `StringLiteral` for it) and only its TRUTHINESS is undecidable."""
        if child is not None and is_none_expr(child):
            return None, False
        return operand(child), True

    if isinstance(node, F.TernaryExpr):
        cond, ok = part(node.condition)
        if not ok:
            return None
        truth = as_int(cond)
        if truth is None:
            return None
        taken = node.then_val if truth != 0 else node.else_val
        value, ok = part(taken)
        return value if ok else None
    if isinstance(node, F.BinaryOp) and node.op in _FOLD_SELECT_OPS:
        left, ok = part(node.left)
        if not ok:
            return None
        truth = as_int(left)
        if truth is None:
            return None
        # `a and b` is `b` when `a` is truthy and `a` otherwise; `a or b` is the
        # mirror. Decided by the LEFT alone where the left decides, so an
        # undecidable right operand costs nothing — which is CPython's own
        # short circuit and not a relaxation of it.
        if (truth != 0) == (node.op == "and"):
            right, ok = part(node.right)
            return right if ok else None
        return left
    if isinstance(node, F.UnaryOp) and node.op == "not":
        value, ok = part(node.operand)
        if not ok:
            return None
        truth = as_int(value)
        if truth is None:
            return None
        return 0 if truth != 0 else 1
    if isinstance(node, F.BinaryOp) and node.op in _FOLD_COMPARE:
        a, ok = part(node.left)
        if not ok:
            return None
        b, ok = part(node.right)
        if not ok:
            return None
        a = as_int(a)
        b = as_int(b)
        if a is None or b is None:
            return None
        try:
            return 1 if _FOLD_COMPARE[node.op](a, b) else 0
        except TypeError:
            return None
    return None


def _module_binding_name(stmt):
    """The single name a module-level binding statement binds, else None.

    One name or nothing: `a = b = 1` and `a, b = 1, 2` are refused rather than
    half-recognised, because a table with one of two names in it answers a
    question about the other with silence."""
    if isinstance(stmt, F.AssignStmt):
        t = stmt.target
        return t.name if isinstance(t, F.IdentExpr) else None
    if isinstance(stmt, F.AugAssignStmt):
        t = getattr(stmt, "target", None)
        return t.name if isinstance(t, F.IdentExpr) else None
    if isinstance(stmt, F.VarDecl):
        return stmt.name if isinstance(stmt.name, str) else None
    if isinstance(stmt, F.ComptimeVarStmt):
        t = getattr(stmt, "target", None)
        return t if isinstance(t, str) else (
            t.name if isinstance(t, F.IdentExpr) else None)
    return None


def _comptime_statement(stmt) -> bool:
    return type(stmt).__name__ == "ComptimeVarStmt"


def builtin_module_constants(source_path: str) -> dict:
    """`{name: value}` for the module-level names the BUILD can answer.

    One name today, and the list is short on purpose: a name belongs here only
    because the build was HANDED the fact, not because the source wrote it.

    `__file__` is the path of the file being compiled.  It was refused by name
    before this — `'__file__' has no home` — on the reasoning recorded in
    `_UNRESOLVED_NAME_ALLOWED` ("module attributes, which are strings by the
    language and **identical in every program this path can compile**"), which
    is false of this one and only this one: every other name on that list has
    the same value whatever file reads it, and `__file__` is a different string
    in every file.  So it belongs here rather than there, and the honest way to
    hold a value that differs per unit is the table a per-unit constant already
    lives in: `collect_module_symbols` seeds it, the module-constant
    substitution puts the literal at every read, and a dylib publishes it the
    way it publishes every other folded constant.

    Two properties make the value right rather than merely plausible:

      * it is `abspath`, not the spelling the caller used.  CPython has made
        `__file__` absolute for the entry script and for imported modules since
        3.9, and the target here is 3.14, so a relative path would be a
        well-formed wrong answer for `os.path.dirname(os.path.abspath(__file__))`
        — the exact spelling `tools/bootstrap_verify.py` and
        `tools/audit_selfhost_struct_fields.py` use;
      * it is the SOURCE's path, which is the file the build was handed.  Mojo is
        a Python superset and this path compiles `.py` directly, so for a `.py`
        file it is that file's own path — the same value CPython would report for
        the same file.  It is NOT resolved through symlinks, because CPython does
        not do that either and a `realpath` would invent a difference.

    A source binding of the same name WINS: the table is seeded before the
    statement loop and the loop's own `table[name] = …` overwrites it, so
    `__file__ = "x"` at file level is an ordinary module-level constant rather
    than a conflict between the language and the build.

    **What this is not:** it is not `sys.argv`.  `argv` is the process's command
    line, which arrives in registers the entry stub overwrites before the first
    statement runs, so there is nothing for the build to hold —
    `FORMAL_module_state_no_storage.md (deleted) (deleted)` §(4) is right about that one and
    this doc's author grouped `__file__` with it by shape rather than by cause.
    A source the BUILD was handed is not a source that is gone.
    """
    if not source_path:
        return {}
    return {"__file__": os.path.abspath(source_path)}


def collect_module_symbols(stmts: list, source_path: str = None) -> dict:
    """`{name: GlobalSymbol}` for every module-level binding in `stmts`.

    Walks the module's OWN statement list, in order, which is the only place a
    name's home is stated. Four kinds of name come out, and the difference
    matters because it decides whether a read is answerable:

      * `assigned` — bound once, by an assignment, and the value FOLDS to a
        literal. Readable everywhere, and the value is the folded one.
      * `rebound` — bound more than once at module level, or by an augmented
        assignment, or by a statement inside a module-level `if`/`for`/`try`
        whose value the build cannot fold. The build still knows the name is
        module-level, so a read is refused BY NAME — the previous answer was a
        register.
      * `declared` — `K: Int` with no value. No value at any point.
      * `imported` — `from m import x` / `import m`. The name lives in the
        dylib `m` compiles to, and a dylib's module-level storage is not
        exported as a word, so a read is refused by name and the message names
        the module.

    A module-level `if`/`for`/`try` is NOT descended into for bindings: the
    build cannot know which arm ran, so a name bound in one is `rebound` unless
    it was already bound. That is a refusal rather than a fold, and it is the
    honest one — a fold from a conditional is a guess.

    ONE MORE THING IS WALKED IN, and it is the order of this loop that makes it
    safe: `known` accumulates the folded value of every name bound SO FAR, and
    an initializer may read one. The module-level sequence runs top to bottom,
    so at the point a later statement executes, an earlier binding's value is
    exactly the value that name has — the same premise `mojo/middle/comptime.py`
    relies on for a function's own `comptime` bindings, where `eval_const`
    resolves operand names out of the table recorded so far for that function.
    Before this, the module level had the folder and not the resolution, so

        comptime _kCompactMaxElemsToPrint = 7
        comptime _kCompactElemPerSide = _kCompactMaxElemsToPrint // 2

    was refused as "does not fold to a compile-time constant" — for
    `std/utils/_serialize.mojo`, and while `comptime_fold_refusal`'s own text
    told the reader to write "an expression of literals and other `comptime`
    names". Only names already in `known` resolve, and only ones with a folded
    non-`None` value: a `rebound` name whose last binding did not fold, an
    `imported` name (its value lives in another image) and a `declared` name
    are all absent, which is the honest answer for each. A `None`-valued
    binding is excluded too, because its folded word is `NONE_WORD` — the
    integer 0 wearing `None`'s spelling — and `7 + <that>` folding to 7 is
    exactly the conflation `refuse_none_comparisons` exists to prevent.

    AND ONE MORE IS DELIBERATELY LEFT OUT, which is what makes the "so far"
    above sound rather than merely plausible: a name some FUNCTION writes through
    `global` never enters `known`, however it was bound at module level.

        G = 5
        def bump():
            global G
            G = 100
        bump()
        comptime B = G + 1        # CPython: 101

    `known[G]` is 5, and 5 + 1 is 6. The module-level sequence is not the only
    thing that runs before that initializer: a module body may CALL a function,
    and the caller's write lands before the read. So a name that `bump` writes
    is excluded from resolution and `B` is refused, which is the honest answer
    for a program this build cannot order. `functions_writing_globals` is the
    reader, and it is the same one `collect_global_slots` uses for the same
    reason — the value is stated at module level and the writes are stated
    inside the bodies, so the question needs both lists — which is also why the
    gate keys on the `global` DECLARATION and not on the assignment targets: a
    function that assigns `G` without declaring it global binds a local that
    shadows the module's, and such a name really is read-only at module level."""
    table: dict = {}
    known: dict = {}
    # The names the BUILD can answer, seeded FIRST so a source binding of the
    # same name overwrites one rather than conflicting with it
    # (`builtin_module_constants`). They are in `table` and not in `known`,
    # deliberately: `known` is the resolution scope for a module-level
    # initializer, and a name no statement in this file bound is not something
    # an initializer here may read to fold against. The seeding is what makes
    # them readable, and `_substitute_module_constants` is the reader.
    for name, value in (builtin_module_constants(source_path) or {}).items():
        # `site="builtin"` and not `"assigned"`: no statement in this file bound
        # the name, and the two consumers that want to tell a source-declared
        # module-level name from one the build supplied cannot answer that
        # question from `site` if both spell it the same way. It is named in
        # `_why_unplaced`'s "the table is empty" test, which is the consumer
        # that broke: a module that declares nothing used to say so.
        table[name] = GlobalSymbol(name, folded_literal_node(value, None),
                                   "builtin", None, 0)
    # EVERY FunctionDef at any depth, not the top-level ones. A `global G`
    # inside a method is a write to the module's `G` exactly as one inside a
    # free function is — the module is the scope either way, and the method's
    # `self` receiver has nothing to do with which name is written — so a gate
    # that read only the top-level list would let `class C: def bump(self):
    # global G` through and fold a later initializer against a value that
    # method can change. `iter_nodes` reaches a nested def and a def inside a
    # `StructDef`'s body, which is the whole of what "any depth" has to mean
    # here.
    written = set(functions_writing_globals(
        [n for n in iter_nodes(stmts or []) if isinstance(n, F.FunctionDef)]))

    def remember(name, folded, value) -> None:
        """`known[name] = folded`, unless the name is one of the four cases.

        A name a FUNCTION writes through `global` is never resolvable (see the
        section note); a `None`-valued binding is not, because its folded word
        is `NONE_WORD` rather than the integer it is spelled as. Both are
        absences rather than values, so this is the one place the rule is
        written and `pop` is what says "not known"."""
        if name in written or is_none_expr(value):
            known.pop(name, None)
        else:
            known[name] = folded

    for stmt in (stmts or []):
        kind = type(stmt).__name__
        if kind in ("ImportStmt", "FromImportStmt"):
            for name, module, defining in _imported_names(stmt):
                table.setdefault(name, GlobalSymbol(
                    name, None, "imported", module,
                    getattr(stmt, "line", 0) or 0, defining=defining))
            continue
        name = _module_binding_name(stmt)
        if name is None:
            continue
        value = getattr(stmt, "value", None)
        if value is None and isinstance(stmt, F.VarDecl):
            table[name] = GlobalSymbol(name, None, "declared", None,
                                       getattr(stmt, "line", 0) or 0)
            known.pop(name, None)
            continue
        if isinstance(stmt, F.AugAssignStmt):
            table[name] = GlobalSymbol(name, None, "rebound", None,
                                       getattr(stmt, "line", 0) or 0)
            known.pop(name, None)
            continue
        folded = fold_module_value(value, known)
        if folded is None:
            table[name] = GlobalSymbol(
                name, None,
                "comptime" if _comptime_statement(stmt) else "rebound",
                None, getattr(stmt, "line", 0) or 0)
            known.pop(name, None)
            continue
        prior = table.get(name)
        if prior is not None and prior.site not in ("imported", "declared"):
            # A second module-level binding: the LAST one is the value, and
            # folding the last one is exact, so this is still answerable — but
            # only when both fold. `site` stays `rebound` so a read that
            # somehow has no folded value is refused rather than guessed.
            table[name] = GlobalSymbol(
                name, module_binding_literal(folded, value), "rebound", None,
                getattr(stmt, "line", 0) or 0)
            remember(name, folded, value)
            continue
        table[name] = GlobalSymbol(name, module_binding_literal(folded, value),
                                   "assigned", None,
                                   getattr(stmt, "line", 0) or 0,
                                   is_none_expr(value))
        remember(name, folded, value)
    return table


def module_binding_literal(folded, value):
    """The literal node a module-level binding's READ is replaced with.

    `folded_literal_node`, plus the one case where the folded WORD is not the
    whole of the value: **a `BoolLiteral` initializer.**

    The literal folder returns `1`/`0` for `True`/`False` — it is shared with
    the struct-field, class-constant and default-parameter readers, which all
    want a word — so a module-level `FLAG = True` was substituted at every read
    as `IntLiteral(1)`, and the `bool` the source wrote was gone before any
    backend saw the read. Measured on both architectures:

        FLAG = True
        print(FLAG)          ->  1        (CPython: True)

    and the same through a linked library's manifest, where `_module_constants`
    publishes `str` and `int` only. The fix is at the substitution rather than
    at the printer because the printer CANNOT fix it: by the time a `print` is
    lowered the read has already become an `IntLiteral`, so the one place that
    still knows the source wrote a bool is the one place that built the node.

    **The folded VALUE is untouched**, which is the property that makes this
    safe rather than a second spelling of the folder: `fold_literal_expr` still
    returns 1/0, so `known` still holds an integer and a later module-level
    initializer that reads this name still folds (`B + 1` is 2 in CPython and
    stays 2 here). Only the NODE at the read site changes shape, and only from
    `IntLiteral(1)` to `BoolLiteral(True)` — a node both backends already lower
    (the `BoolLiteral` arms of `_emit_expr`) and `eval_const_bool` already reads
    as True/False rather than as a number, which is the reason
    `folded_literal_node` builds one at all.

    A `TernaryExpr` of two `BoolLiteral`s is NOT handled here and deliberately
    so: `fold_module_value` does not fold one, so it cannot reach this, and a
    reader that wanted the general case would be guessing about which arm the
    folder had already chosen.
    """
    if isinstance(value, F.BoolLiteral):
        return F.BoolLiteral(value=bool(value.value),
                             line=getattr(value, "line", 0) or 0,
                             col=getattr(value, "col", 0) or 0)
    if is_none_expr(value):
        # The SECOND shape the folded word does not carry, and the reader is the
        # `None` SPELLING rather than the word: `N = None; print(N)` substituted
        # `IntLiteral(0)` at the read, so a program whose value CPython prints as
        # `None` printed `0` (measured, both architectures). Substituting the
        # name `None` keeps the fact and hands it to the readers that already
        # exist for it — `is_none_expr` at a use site, `refuse_none_comparisons`
        # for `N == None`, `print_constant_text` for a `print` — which is both
        # the right answer for the one and a refusal for the other, where the
        # word 0 was a SILENT answer to both (`x = N + 1` computed 1 where
        # CPython raises TypeError). `NONE_WORD` is unchanged and still the
        # representation of a `None` inside an image; what changes is that a
        # read of a module-level `None` no longer arrives wearing its clothes.
        return F.IdentExpr(name=NONE_NAME,
                           line=getattr(value, "line", 0) or 0,
                           col=getattr(value, "col", 0) or 0)
    return folded_literal_node(folded, value)
