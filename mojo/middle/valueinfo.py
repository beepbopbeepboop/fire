"""The per-function facts about WORDS: which `int64_t` values are not plain ints.

An `int64_t` in this backend is an int, a pointer, a boxed float, a tagged
None/str, or an erased struct pointer, all at once (doc/GIR.md stage 5b). ONE
`ValueInfo` record per temp says which of those it is:

    kind    Int | Erased(T) | DynWord | Box | Plain
    flags   Tagged | SlotKinds | BoxedContainer

`kind` is what the word IS, and only one kind can be true; the flags are facts
that are orthogonal to the kind (`Tagged` is a Box that is a generator word,
`SlotKinds` is a container whose slots carry their own kinds, `BoxedContainer`
is a call result holding a container of unknown kind). The six historical
name-keyed sets (`_boxed_vals`, `_tagged_word_vals`, `_dyn_word_vals`,
`_int_word_vals`, `_maybe_kinds_vals`, `_boxed_container_vals`) are derived
READ-ONLY views over the records (`WordFacts.boxed`, ...). The backend reads and
writes through the predicates and `mark_*` methods below, never through a set.

Why the sets could not express `boxed`: `_boxed_vals` meant both "this word may
be a heap box, render it by kind" (a reader) and, at a bind site, "this word
needs unboxing"; a copy could not keep one without claiming the other, and
`mojo_box_word` UNBOXES a str/None/bool box. The `Box` kind plus the `Tagged`
flag say both, which is what the record is for. A COPY carries the read-side
half (a box becomes a `DynWord`: the runtime decides the kind) but not the
bind-side one (the copy is not claimed to be a heap box that a name must
unbox), and `Tagged` stays with the Box kind it modifies; the measured reason
is in `carry`'s docstring below.

Keys are SSA temp / variable names, which repeat across functions, so a
`WordFacts` is per function body (`_reset_func` makes a fresh one).
"""

# The one kind a temp has. Plain is "nothing is known"; the numeric values are
# opaque (nothing compares them as an order). Which of two conflicting marks
# wins is stated once, on the writers below.
KIND_PLAIN = 0
KIND_INT = 1
KIND_ERASED = 2
KIND_DYN = 3
KIND_BOX = 4

# Facts that are not a kind.
FLAG_TAGGED = 1           # a Box from a kind-mixed generator / tagged return
FLAG_SLOT_KINDS = 2       # a container whose slots carry per-slot kinds
FLAG_BOXED_CONTAINER = 4  # a call result holding a container of unknown kind


class ValueInfo:
    """One temp's value facts (see the module docstring).

    `erased_type` is the C type of the pointer an `Erased` word holds. No
    writer sets it yet: the first one is stage 5c's `None`-in-a-pointer
    decision (`doc/GIR.md`), which needs exactly this split — a plain
    `int64_t` parameter may be an INT (its None is not representable) or an
    ERASED pointer (its None is NULL), and only the kind can say which."""

    def __init__(self):
        self.kind = KIND_PLAIN
        self.flags = 0
        self.erased_type = ''


class WordFacts:
    def __init__(self):
        # name -> ValueInfo. One record per temp, created on the first write.
        self._values: dict[str, ValueInfo] = {}

    # ── records ───────────────────────────────────────────────────────────
    def _info(self, name, create: bool):
        """The record for `name`, or None. Reads do not create one: a temp no
        writer has described is Plain by absence, and the per-function record
        map must not grow with every name a predicate happens to ask about."""
        _rec = self._values.get(name)
        if _rec is None and create:
            _rec = ValueInfo()
            self._values[name] = _rec
        return _rec

    def kind_of(self, name: str) -> int:
        _rec = self._info(name, False)
        return KIND_PLAIN if _rec is None else _rec.kind

    # ── derived read-only views of the six historical sets ────────────────
    # Nothing in the backend reads these (the ratchet in
    # test_type_string_ratchet.py counts the old spelling, now 0); they exist
    # so a reader that still thinks in sets — a debugger, a test, the next
    # migration step — gets the same answer from the ONE storage.
    def _kind_view(self, kind: int) -> set:
        _out = set()
        for _n in self._values:
            if self._info(_n, False).kind == kind:
                _out.add(_n)
        return _out

    def _flag_view(self, flag: int) -> set:
        _out = set()
        for _n in self._values:
            if (self._info(_n, False).flags & flag) != 0:
                _out.add(_n)
        return _out

    @property
    def boxed(self) -> set:
        return self._kind_view(KIND_BOX)

    @property
    def tagged(self) -> set:
        return self._flag_view(FLAG_TAGGED)

    @property
    def dyn(self) -> set:
        return self._kind_view(KIND_DYN)

    @property
    def int_word(self) -> set:
        return self._kind_view(KIND_INT)

    @property
    def maybe_kinds(self) -> set:
        return self._flag_view(FLAG_SLOT_KINDS)

    @property
    def boxed_container(self) -> set:
        return self._flag_view(FLAG_BOXED_CONTAINER)

    # ── carrying a copy ──────────────────────────────────────────────────
    def carry(self, dst: str, src: str) -> None:
        """`dst` now holds the same WORD as `src`: the facts that describe the
        VALUE travel with the copy.

        `carry_value_info` (`emit_infra.py`) calls this for the tables it
        copies, and `gen._copy` calls that, so every name-to-name and
        temp-to-temp move a lowering makes keeps what the backend knows. A
        lost fact is the bug class `carry_value_info`'s own docstring
        documents ("a value whose facts are lost is read back with the int
        accessor"): measured on `tools/pydiff_corpus`, `v = xs[0]` out of a
        kind-mixed list is a boxed double, and `w = v; w + 1` added the box's
        POINTER as an integer (`print(w + 1)` gave 4350185905 for 2.5) until
        the copy kept `dyn` (`test_gimple_runner.py`'s
        `test_copy_of_a_dynamic_word_keeps_it`).

        A fact is only ADDED, never moved: a caller that already knows better
        about `dst` (a declared annotation, a narrowing) wins, which is
        `carry_value_info`'s rule for every other table. A proven integer is
        therefore not promoted to a dynamic word: the proof is the stronger
        fact, and a name that really holds a box after an integer proof was
        rebound, whose next store must re-prove it.

        WHICH facts travel, measured 2026-11-21 (`tools/pydiff_corpus`, the
        C of each program hashed before vs after):

        * `dyn`, `int_word`, `slot_kinds`, `boxed_container`: they travel.
        * A source `Box` travels as `DynWord`, NOT as `Box`. The two halves of
          the old `boxed` predicate are exactly what the record separates: a
          reader needs "this word's kind is a runtime fact" (true of every
          box, and what `DynWord` says), while a BIND site needs "this word is
          a heap box, unbox it with `mojo_box_word`" (`may_be_box`). The copy
          is the same word, so the first half is true of it and must travel;
          the second is a statement about how a NAME should be represented,
          and a pass-through temp is not a name anybody bound. That is also
          why `Tagged` does not travel: it is the Box flag the bind-side
          `_keep_tagged_box` decision reads.
        * Measured with `Box` carried for real (both `Box` and `Tagged`): the
          self-host-closure module `mojo/middle/infra_infer.py` REFUSES to
          compile. `_pn2 = _chosen.get('param_names') or []` lowers the `or`
          merge through `_copy`; the dict-get arm is a tagged box, the tag
          reached the merge temp, and the next statement stores that temp into
          a `MojoList *` local — the "cannot also hold a value of another C
          type" refusal (`emit_stmts._gen_stmt_AssignStmt`). The value fact is
          not wrong (a truthy box could be selected), but the name cannot hold
          it, and the program is one the compiler has always built. Carrying
          `Box` alone builds and is C-identical, but only feeds the
          `may_be_box -> mojo_box_word` unboxing half of the same overloaded
          predicate. So the boundary is: the KIND is carried as far as it is a
          fact about the word, and the bind-side "this name holds a box" waits
          for the next step (splitting `may_be_box`'s two meanings) — the work
          doc is `bugs/GIR_stage5b_box_carry_needs_the_bind_fact_split.md`."""
        if src == dst:
            return
        _s = self._info(src, False)
        if _s is None:
            return
        _d = self._info(dst, False)
        if _d is None:
            _d = ValueInfo()
            self._values[dst] = _d
        if _s.kind == KIND_INT:
            if _d.kind == KIND_PLAIN or _d.kind == KIND_ERASED:
                _d.kind = KIND_INT
        elif _s.kind == KIND_BOX:
            # The READ-side half travels, the BIND-side half does not: the
            # copy is a word whose kind the runtime decides (`DynWord`), but
            # it is not claimed to be a heap box (see the docstring).
            if _d.kind == KIND_PLAIN or _d.kind == KIND_ERASED:
                _d.kind = KIND_DYN
        elif _s.kind == KIND_DYN:
            if _d.kind == KIND_PLAIN or _d.kind == KIND_ERASED:
                _d.kind = KIND_DYN
        elif _s.kind == KIND_ERASED:
            if _d.kind == KIND_PLAIN:
                _d.kind = KIND_ERASED
                _d.erased_type = _s.erased_type
        if (_s.flags & FLAG_SLOT_KINDS) != 0:
            _d.flags = _d.flags | FLAG_SLOT_KINDS
        if (_s.flags & FLAG_BOXED_CONTAINER) != 0:
            _d.flags = _d.flags | FLAG_BOXED_CONTAINER

    # ── save / restore across a nested body ──────────────────────────────
    def snapshot(self) -> dict:
        """A copy of every record, for `FuncState`. A nested body gets a
        fresh `WordFacts` (`_reset_func`), so the restore is the same object
        refilled: the copy is what makes this a snapshot rather than an alias
        of the live map.

        A DICT and not a one-element list: the self-hosted compile types the
        `snap` parameter from the annotation, and a boxed element out of a
        list is an `int64_t` whose keys it would have to find by run-time
        kind dispatch (the list form of this emitted ~1,100 lines of
        container-kind probing for `for _n in <box>`)."""
        _copy = {}
        for _n in self._values:
            _r = self._info(_n, False)
            _c = ValueInfo()
            _c.kind = _r.kind
            _c.flags = _r.flags
            _c.erased_type = _r.erased_type
            _copy[_n] = _c
        return _copy

    def restore_snapshot(self, snap: dict) -> None:
        self._values.clear()
        for _n in snap:
            self._values[_n] = snap[_n]

    # Read predicates: the one spelling a reader should use, so a later step can
    # change what is stored without touching the readers.
    def may_be_box(self, name: str) -> bool:
        return self.kind_of(name) == KIND_BOX

    def is_tagged(self, name: str) -> bool:
        _rec = self._info(name, False)
        return (_rec is not None and _rec.kind == KIND_BOX
                and (_rec.flags & FLAG_TAGGED) != 0)

    def is_dyn(self, name: str) -> bool:
        # A BOX is a word whose kind only the runtime knows too: every reader
        # of a `dyn` word asks the runtime instead of assuming an integer, and
        # that is exactly what a box needs. Measured on tools/pydiff_corpus:
        # every name that is both a box and a dynamic word keeps its old
        # answer, so the collapse changes no reader's decision for those.
        _k = self.kind_of(name)
        return _k == KIND_DYN or _k == KIND_BOX

    def is_int_word(self, name: str) -> bool:
        return self.kind_of(name) == KIND_INT

    def is_erased(self, name: str) -> bool:
        return self.kind_of(name) == KIND_ERASED

    def erased_type_of(self, name: str) -> str:
        _rec = self._info(name, False)
        if _rec is None or _rec.kind != KIND_ERASED:
            return ''
        return _rec.erased_type

    def has_slot_kinds(self, name: str) -> bool:
        _rec = self._info(name, False)
        return _rec is not None and (_rec.flags & FLAG_SLOT_KINDS) != 0

    def is_boxed_container(self, name: str) -> bool:
        _rec = self._info(name, False)
        return _rec is not None and (_rec.flags & FLAG_BOXED_CONTAINER) != 0

    # Writers. Two facts sometimes contradict — a name recorded both as a box
    # and as a proven integer — and one record has to pick. The BOX wins: it
    # is an observation of a heap cell at that temp, while the integer proof
    # is about bits a producer computed, so a rebound name's proof is about an
    # older value and the next store re-proves it. Symmetrically,
    # `mark_dyn` does not demote a box (a box IS a word whose kind only the
    # runtime knows) and an integer mark never demotes a box or a dynamic
    # word.
    def mark_boxed(self, name: str) -> None:
        self._info(name, True).kind = KIND_BOX

    def mark_tagged(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.kind = KIND_BOX
        _rec.flags = _rec.flags | FLAG_TAGGED

    def mark_dyn(self, name: str) -> None:
        _rec = self._info(name, True)
        if _rec.kind != KIND_BOX:
            _rec.kind = KIND_DYN

    def mark_int_word(self, name: str) -> None:
        _rec = self._info(name, True)
        if _rec.kind == KIND_PLAIN or _rec.kind == KIND_ERASED:
            _rec.kind = KIND_INT

    def unmark_int_word(self, name: str) -> None:
        _rec = self._info(name, False)
        if _rec is not None and _rec.kind == KIND_INT:
            _rec.kind = KIND_PLAIN

    def mark_slot_kinds(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.flags = _rec.flags | FLAG_SLOT_KINDS

    def mark_boxed_container(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.flags = _rec.flags | FLAG_BOXED_CONTAINER
