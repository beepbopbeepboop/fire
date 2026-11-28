"""The per-function facts about WORDS: which `int64_t` values are not plain ints.

An `int64_t` in this backend is an int, a pointer, a boxed float, a tagged
None/str, or an erased struct pointer, all at once (doc/GIR.md stage 5b). ONE
`ValueInfo` record per temp says which of those it is:

    kind    Int | Erased(T) | DynWord | Box | Plain
    flags   Tagged | SlotKinds | BoxedContainer | BindBox

`kind` is what the word IS, and only one kind can be true; the flags are facts
that are orthogonal to the kind (`Tagged` is a Box that is a generator word,
`SlotKinds` is a container whose slots carry their own kinds, `BoxedContainer`
is a call result holding a container of unknown kind, `BindBox` is a word a
NAME holding it represents as a box). The six historical name-keyed sets
(`_boxed_vals`, `_tagged_word_vals`, `_dyn_word_vals`, `_int_word_vals`,
`_maybe_kinds_vals`, `_boxed_container_vals`) are derived READ-ONLY views over
the records (`WordFacts.boxed`, ...). The backend reads and writes through the
predicates and `mark_*` methods below, never through a set.

Why the sets could not express `boxed`: `_boxed_vals` meant two different
things, and the record gives them a KIND and a FLAG:

* READ side: "this word's kind is a runtime fact; render it by kind"
  (`mojo_repr_boxed`, `mojo_cstr_or_int_str`, `mojo_truthy_word`). That is the
  `Box` kind, plus `Tagged` when the word is a generator's kind-mixed yield.
  It is true of every copy of a box, so `carry` MOVES this half.
* BIND side: "a NAME holding this word keeps the box" -- the representation
  decision `emit_stmts._gen_stmt_AssignStmt` takes for a name (keep the box
  for a tagged name, `mojo_box_word`-unwrap it otherwise). That is `BindBox`,
  which `carry` does NOT move: a pass-through temp is not a name anybody
  bound. `mark_boxed` / `mark_tagged` set it wherever the backend observes a
  box as a value; a copy is not such an observation.

Before the split, a copy could not keep one half without claiming the other,
and `mojo_box_word` UNBOXES a str/None/bool box. The measured cost of the
split is in `carry`'s docstring below.

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
# The BIND half of the old `_boxed_vals`: a NAME holding this word represents it
# as a box (it keeps the box rather than unwrapping it with `mojo_box_word`).
# `carry` deliberately does not move it -- see the module docstring and
# `carry`'s own.
FLAG_BIND_BOX = 8
# A word read from a MIXED struct field (stage 5c, `emit_infra.mixed_field_names`):
# the slot holds a scalar beside `None`, and `None` is the shared box. Orthogonal
# to the kind (the read is a Box); `carry` does not move it, so only the field
# read itself answers an identity test by the box's kind.
FLAG_MIXED_FIELD = 16
# A word read from a REFS-ONLY slot (stage 5c rule 1: its non-None values are
# all references, so the bare 0 IS None). Unlike the mixed field above the word
# keeps its integer C type; only the SPELLING differs (`print`/`str` must say
# `None` for 0). `carry` moves it — every copy of the value is the same word.
FLAG_REFS_NONE = 32


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
        therefore not promoted to a box or a dynamic word: the proof is the
        stronger fact, and a name that really holds a box after an integer
        proof was rebound, whose next store must re-prove it.

        WHICH facts travel (stage 5b, the bind/read split): `dyn`, `int_word`,
        `slot_kinds`, `boxed_container`, and now the `Box` KIND with its
        `Tagged` flag. A copy of a box IS the same box, so every reader of
        "this word's kind is a runtime fact" needs it: `print` renders it by
        kind, arithmetic dispatches on its kind (`+ - *` beside an integer go
        through `emit_exprs._tagged_arith_select`, extended from the tagged
        words for exactly this: coercing the operand to a C `double` asserted
        it was a float box, and an int box then made an ordinary integer local
        a double), `_to_int64` truncates a double box instead of using its
        address, and `is_dyn` (true of a box) keeps the truthiness/`str()`/`==`
        answers.

        `BindBox` does NOT travel, and that is the whole reason the split
        exists. The bind side is a statement about how a NAME is represented
        ("this name keeps the box; a tagged value stored into a pointer-typed
        name is a refusal"), not about the word: a pass-through temp -- an `or`
        merge's result, a coercion temp -- is not a name anybody bound. Moving
        it made the self-host-closure module `mojo/middle/infra_infer.py`
        REFUSE to compile: `_pn2 = _chosen.get('param_names') or []` lowers the
        `or` merge through `_copy`, the dict-get arm is a tagged box, the tag
        reached the merge temp, and the next statement stores that temp into a
        `MojoList *` local -- "a name bound to a container or pointer value
        ... and also to a tagged generator word here cannot also hold a value
        of another C type". The value fact is not wrong (a truthy box could be
        selected) but the name cannot hold it, the program is one the compiler
        has always built, and the bind path's answer must not change because a
        box passed through a copy (`_tagged_bind` / `_keep_tagged_box` read
        `bind_tagged`, which is `BindBox` + the tag, not `is_tagged`)."""
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
            # The READ-side half (the KIND, and the tag that modifies it)
            # travels; the BIND-side flag does not (see the docstring).
            if _d.kind != KIND_INT:
                _d.kind = KIND_BOX
                if (_s.flags & FLAG_TAGGED) != 0:
                    _d.flags = _d.flags | FLAG_TAGGED
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
        if (_s.flags & FLAG_REFS_NONE) != 0:
            _d.flags = _d.flags | FLAG_REFS_NONE

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

    # The BIND side (see the module docstring): a NAME holding this word
    # represents it as a box. Every writer that observes a box sets it, and
    # `carry` does not move it, so a copy answers False here while answering
    # True to `may_be_box` / `is_tagged` -- the two questions the old
    # `_boxed_vals` conflated.
    def bind_box(self, name: str) -> bool:
        _rec = self._info(name, False)
        return _rec is not None and (_rec.flags & FLAG_BIND_BOX) != 0

    def is_mixed_field(self, name: str) -> bool:
        _rec = self._info(name, False)
        return (_rec is not None and _rec.kind == KIND_BOX
                and (_rec.flags & FLAG_MIXED_FIELD) != 0)

    def bind_tagged(self, name: str) -> bool:
        """The tagged-word bind: this word is a TAGGED box AND it is one a
        name keeps (not a copy), which is what `_keep_tagged_box` and the
        tagged-vs-container refusals in `emit_stmts` decide on."""
        _rec = self._info(name, False)
        return (_rec is not None and _rec.kind == KIND_BOX
                and (_rec.flags & FLAG_TAGGED) != 0
                and (_rec.flags & FLAG_BIND_BOX) != 0)

    # Writers. Two facts sometimes contradict — a name recorded both as a box
    # and as a proven integer — and one record has to pick. The BOX wins: it
    # is an observation of a heap cell at that temp, while the integer proof
    # is about bits a producer computed, so a rebound name's proof is about an
    # older value and the next store re-proves it. Symmetrically,
    # `mark_dyn` does not demote a box (a box IS a word whose kind only the
    # runtime knows) and an integer mark never demotes a box or a dynamic
    # word.
    #
    # Both box writers also record the BIND-side fact: the observation is of a
    # value a bind must represent as a box. `carry` is the one place the box
    # kind moves without it, which is exactly the split the module docstring
    # describes.
    def mark_boxed(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.kind = KIND_BOX
        _rec.flags = _rec.flags | FLAG_BIND_BOX

    def mark_mixed_field(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.kind = KIND_BOX
        _rec.flags = _rec.flags | FLAG_MIXED_FIELD

    def mark_refs_none(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.flags = _rec.flags | FLAG_REFS_NONE

    def is_refs_none(self, name: str) -> bool:
        _rec = self._info(name, False)
        return _rec is not None and (_rec.flags & FLAG_REFS_NONE) != 0

    def mark_tagged(self, name: str) -> None:
        _rec = self._info(name, True)
        _rec.kind = KIND_BOX
        _rec.flags = _rec.flags | FLAG_TAGGED | FLAG_BIND_BOX

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
