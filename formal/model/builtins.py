from . import *

# ── the builtins this path does NOT lower ───────────────────────────────────
#
# `EMITTER_BUILTINS` above is three names and `BUILTIN_FUNCTIONS` is two, and
# between them they are the whole of what a bare-name call to a CPython builtin
# lowers to on this path. The rest of CPython's builtin namespace is NOT
# lowered, and until this table existed that fact lived in three places that
# could disagree: the link audit's refusal (a name nothing provides), a
# construct refusal further back, and — for the names the C library happens to
# define — NOTHING AT ALL.
#
# So the table is a MEASUREMENT with one sentence per name, and the sentences
# say what lowering each one would take, because "the census cannot say which
# builtin is missing" is the complaint this answers: the finding was that of the
# 33 names `tools/formal_proof_breadth.py` lets a candidate read, the path
# lowers 11 and refuses 22, and nothing said which was which (fixed in
# c8d877e9 + af313965; the doc is deleted with its fix). Every row was measured
# on BOTH architectures on 2026-10-04 with
# `def main(n): return <call>` and CPython as the arbiter, and the measurement
# is pinned by `test_formal_value_model.py`'s builtin group — one differential
# case per name that lowers, one refusal case per name that does not, on both
# backends, which is also what makes a row's removal a test failure rather than
# a stale sentence.
#
# `int`, `len`, `print`, `range` and `str`-of-text are NOT here because they
# lower (`EMITTER_BUILTINS`, `INT_TYPE_CTORS`, `IDENTITY_TYPE_CTORS`); `abs`,
# `pow` and `round` ARE here and are called out again below, because for those
# three the absence was silent.
#
# **A ROW IS A NAME AND A SHAPE, and for two of the names the SHAPE is most of
# the row.** `max` and `min` called with two or more POSITIONAL arguments and no
# keyword are a compare and a select, and they are lowered —
# `formal/build.py::_lower_builtin_extremum` rewrites them to the
# `TernaryExpr` both emitters already have, and it runs in `_prepare_functions`
# before `check_module_symbols` asks the question below, so a rewritten call is
# never seen here. What this table therefore records for those two names is the
# THREE shapes that survive it: one argument (a run-time sequence to fold), a
# `key=` (a call through a value per element) and a `default=`. That is why
# their rows were rewritten rather than deleted — a name deleted from here while
# `max(xs)` still refuses would put a name in `LOWERED_BUILTINS` and
# `NOT_LOWERED_BUILTINS` at once, which is the partition
# `test_formal_proof_breadth.py`'s `test_every_allowed_name_is_either_lowered_
# or_named_as_missing` exists to catch, and would move a measurable name out of
# `tools/formal_proof_breadth.py`'s frontier for the sake of a shorter sentence.
#
# The rewrite is guarded by the SAME three questions this pre-pass asks — a name
# the unit compiles, binds or imports is not the builtin — and it asks them
# through the same readers (`callee_is_a_bound_value` and the module symbol
# table), so a program that defines its own `max` still builds and the two
# readers cannot disagree about which program that is.
NOT_LOWERED_BUILTINS = {
    "abs": "a compare against zero and a select of the operand or its "
           "negation — and the C library's `abs` is NOT it, see "
           "FOREIGN_ABI_BUILTINS",
    "all": "a fold over a sequence with a short circuit, which is a run-time "
           "sequence this one-word value model cannot carry",
    "any": "a fold over a sequence with a short circuit, the same shape as "
           "`all`",
    "bin": "a base-2 rendering into a buffer: a digit table and a loop, and "
           "the ANSWER is a run-time string, which is "
           "`bugs/FORMAL_string_value_model.md`",
    "bool": "a compare against zero and a normalize — but the name is also in "
            "`FRAME_VALUE_ONLY_CALLS`, so the frame-address half of the answer "
            "is settled and the value half is not",
    "chr": "a code point to a one-character string: an integer-to-text "
           "conversion this path does not have",
    "divmod": "a division and a remainder returning a PAIR, and a pair is more "
             "than one word (`FORMAL_the_value_model_is_one_word`)",
    "enumerate": "a generator of pairs; both halves are out of reach "
                 "(`FORMAL_listdir_no_run_time_sequence`)",
"float": "a double, and every value on this path is one 64-bit INTEGER "
           "word",
    "filter": "a call THROUGH A VALUE per element, and a value is one 64-bit "
              "word with no code address in it — the same wall as `sorted`'s "
              "comparison call, and the same one `map` is against",
    "hex": "a base-16 rendering, the same shape as `bin`",
    "list": "a counted blob this path CAN lay out (`BLOB_TYPE_CTORS`) but "
            "cannot COPY from another blob at run time — a copy is the tagged-"
            "value work `FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_"
            "time.md` is about",
    "map": "a call THROUGH A VALUE per element, and calling through a value "
           "is not a thing this path can express — `sorted` needs a "
           "comparison call per element for the same reason",
    "max": "TWO OR MORE POSITIONAL ARGUMENTS ARE A COMPARE AND A SELECT and are "
           "lowered (`formal/build.py`'s `_lower_builtin_extremum` rewrites them "
           "to the `TernaryExpr` both emitters already have); what is left here "
           "is the OTHER three shapes — one argument (a run-time sequence to "
           "fold, `FORMAL_listdir_no_run_time_sequence`), a `key=` (a call "
           "through a value per element) and a `default=` (a value the empty "
           "sequence takes) — none of which is a select",
    "min": "the same three shapes as `max`, and the two-argument form lowers "
           "the same way with `<`",
    "oct": "a base-8 rendering, the same shape as `bin`",
    "ord": "a one-character string to a code point — the inverse of `chr`, and "
           "the string half is the same gap",
    "pow": "integer exponentiation — a loop, or a libm call whose result is a "
           "double (see FOREIGN_ABI_BUILTINS)",
    "reversed": "a reversed copy of a sequence, so the same two gaps as "
                "`list`",
    "round": "a compare-and-select for an integer operand and a rounding rule "
             "for a real one; the C library's `round` is a double (see "
             "FOREIGN_ABI_BUILTINS)",
    "sentinel": "a fresh, unique sentinel value per call, and a unique runtime "
                "identity is not a value this one-word model can produce — the "
                "same wall as `object()`",
    "frozendict": "an immutable dict variant; a fresh unique mapping value per "
                  "call is not a thing this one-word model can produce",
    "sorted": "a sort — a comparison call per element, and a call through a "
              "value is not a thing this path can express",
    "sum": "a fold over a sequence, the same shape as `all`",
    "tuple": "a counted blob, the same gap as `list`, and a two-element tuple "
             "is a list blob this path cannot copy at run time either",
}

# The three names whose absence was SILENT, and the only reason this table has
# to be read as a safety property rather than a census.
#
# A bare-name call to a name nothing provides is refused by the bind audit with
# a sentence that names the builtin (`ee704916`). These three are different: the
# C library DEFINES all of them, so the audit's provider check — "asked the C
# library (dlsym)" — finds a provider and the image links. What it binds is a
# different function:
#
#     double pow(double, double)      two doubles in, one double out, and this
#                                     path's ABI reads the result from the
#                                     INTEGER return register
#     double round(double)             the same, and x86-64's SysV varargs area
#                                     is not even the same memory arm64 leaves
#                                     the result in
#     int    abs(int)                  a 32-BIT argument, so the low half of the
#                                     word this path passes is all it sees
#
# Measured, both architectures, 2026-10-04, against CPython's own answers:
#
#     def main(n): return pow(n, 2)     n=10 -> 0     (CPython 100)
#                                         n=3  -> 0     (CPython 27)
#     def main(n): return round(n)      n=7  -> 7 arm64, 0 x86-64 (CPython 7)
#     def main(n): return abs(n)        n=2**40+5 -> 5 on BOTH (CPython
#                                         1099511627781); n=-(2**40+5) -> 5 on
#                                         both (CPython 1099511627781)
#
# An image that answers a different number is the failure this project treats
# as worse than a refusal everywhere else, so these three are refused BY NAME at
# the same chokepoint the other builtin intercepts use
# (`builtin_binding_refusal`), which is what turns a wrong answer into a
# sentence a reader can act on. Nothing in the corpus loses: no `.mojo` file in
# `formal/` or `std/` spells any of them outside a docstring, and the PROOF
# layer already refuses all three by name — "model: call to `abs` has no model
# in this image" — so no generated proof changes either. What a census row over
# a function that reads `pow` now reports is the truth: the code generator does
# not lower it, and here is what lowering it would take.
FOREIGN_ABI_BUILTINS = frozenset({"abs", "pow", "round"})


# The names in `NOT_LOWERED_BUILTINS` whose CALL SHAPE the emitters DO lower,
# and which this pre-pass must therefore not refuse. Asked through TWO readers
# rather than one table, because there are two ways a name can be lowered and a
# single hand-listed set is how they came to disagree:
#
# * `emitter_lowers(name)` is the emitters' own question. `ord`, `chr` and `hash`
#   are in `EMITTER_BUILTINS` because `_emit_text_builtin` answers one of them
#   (a literal's single character folds to its code point) and words a refusal
#   for the other two that is specific to each, so they are answered through
#   that table rather than by being listed here a second time.
# * `float` is the other kind: it is NOT in `EMITTER_BUILTINS` — the emitters
#   reach it through the type-conversion path rather than a named builtin
#   intercept — so it is the one name this set holds. **Its exclusion is what
#   this set is FOR**: `float(x)` is an integer-to-double CONVERSION and both
#   emitters build it, measured on this tree in all three argument positions —
#   `printf("%.17g\n", float(9007199254740995))`, `printf("%s\n", float(7))`, and
#   a `float(7)` bound to a `var` first — and `test_formal_run.py`'s three float
#   rows depend on it, answering `9007199254740996` where the source says
#   `9007199254740995` and CPython says the same.
#
# **Neither reader was here when the pre-pass landed on 2026-10-05, which is why
# both are consulted rather than the second replacing the first.** Without
# `emitter_lowers`, every `ord("A")` and every `chr(233)` is refused by NAME
# before an emitter runs, with the generic "write the operation out in the
# source" sentence, where the emitter answers the first with the right NUMBER
# and refuses the second with the reason that is about it ("a NEW one-character
# object … this representation has nowhere to put one"). Measured on `master`
# before that change: `test_formal_unicode.py` 141/9, the nine being exactly the
# four `ord`-folds and the five `ord`/`chr`-refusals, and that file's own comment
# on the `ord`/`chr`/`hash` block recording the folded answer as landed.
#
# **The table row is not wrong, and this is why all of the above can be true**:
# `float` is in `NOT_LOWERED_BUILTINS` because a `Double` is not a VALUE on this
# path — every value is one 64-bit integer word — and the row is about the value
# model. The call shape is a separate fact, and it is answered.
#
# `abs`, `pow` and `round` are excluded by `FOREIGN_ABI_BUILTINS` instead, for
# the same reason and with a different message: those ARE refused at the
# emitter, by `builtin_binding_refusal`, and its sentence names the C function
# whose namesake would be bound — which says more than this table's one-liner.
# Between them these two exclusions and this pre-pass account for every name in
# `NOT_LOWERED_BUILTINS`, so the set of names this pre-pass may refuse is stated
# here rather than left as "the ones nobody has tried yet": the other twenty
# were each probed at HEAD and every one refuses.
LOWERED_CALL_SHAPED_BUILTINS = frozenset({"float"})


def builtin_binding_refusal(name: str):
    """Why a bare-name call to `name` must not bind to a C symbol, or None.

    The one question `FOREIGN_ABI_BUILTINS` exists to be asked at, and it is
    asked at the same point in both emitters as `emitter_lowers` and
    `builtin_function` — beside the intercepts that DO lower a name, because a
    name this path compiles itself and a name it must refuse are the same
    decision read from two sides, and reading them in two places is how
    `FRAME_VARIADIC_BUILTIN_CALLS` came to disagree with the emitters about
    `debug_assert`.
    """
    if name not in FOREIGN_ABI_BUILTINS:
        return None
    table = {
        "abs": "`int abs(int)` — a 32-BIT argument, so it sees the low half of "
               "the 64-bit word this path passes and answers a different "
               "number: `abs(n)` with n = 2**40+5 returned 5 where CPython "
               "returns 1099511627781, on both architectures. A compare "
               "against zero and a select of the operand or its negation is "
               "the whole of what CPython's `abs` is, and both emitters "
               "already have the select",
        "pow": "`double pow(double, double)` — two doubles in and one double "
               "out, and this path's ABI reads an integer result out of the "
               "return register, so `pow(n, 2)` with n = 10 answered 0 where "
               "CPython answers 100 (both architectures). CPython's `pow` on "
               "two integers is INTEGER exponentiation, which is a loop",
        "round": "`double round(double)` — a double in and a double out, read "
                 "here as an integer, so `round(n)` with n = 7 answered 7 on "
                 "arm64 and 0 on x86-64 where CPython answers 7: the two "
                 "architectures did not even agree with each other. On an "
                 "integer operand CPython's `round` is the identity",
    }
    return (
        f"{name}(...) is refused on this path rather than bound to the C "
        f"library's function of that name: {table[name]}. Write the operation "
        f"out, or reach a library that provides it — that is the same advice "
        f"the bind audit gives for a name nothing provides, and the reason it "
        f"is the same advice is that the outcome is the same class of thing: "
        f"an answer about a program this path did not compile."
    )


def not_lowered_builtin_refusal(functions, module_names=()) -> str | None:
    """Why a call to a builtin in `NOT_LOWERED_BUILTINS` is not in the image.

    **Asked BEFORE any emitter**, and that is the whole of what this adds.
    `NOT_LOWERED_BUILTINS` already carried the reason for every one of these
    names and nothing in the build read it: the emitters treated `sorted`,
    `map`, `filter` and `sum` as ordinary extern calls, emitted `BL sorted`, and
    the LINK AUDIT refused four stages later from a message about SYMBOLS whose
    advice ("bind the name from a library that provides it") is about the link
    line rather than about the fact that no library on any line provides a
    Python builtin's semantics. Everything downstream of emission has already run
    by then — the whole closure allocated, every other function emitted — and a
    pre-pass refusal is free.

    The sentence quotes the table's own reason VERBATIM, because the table is
    what says what lowering each name would take and a second wording would be a
    second answer. `tools/formal_proof_breadth.py::builtin_refusal_detail` builds
    a ledger row from the same strings in the same `` `name`: reason `` shape,
    and `_refusal_class`'s `UNLOWERED_CALLEE_MARKS` includes this refusal's
    marker — so a census row and this message agree about which builtin stopped a
    proof. Those are three readers of one table, and the marker below is a
    contract with all of them rather than prose that happens to read well.

    **A name this unit compiles, binds or imports is not the builtin**, and each
    of those is asked by its own reader: a module-level `def sorted` is in
    `functions`, a parameter or local is `callee_is_a_bound_value` (the
    allocator's own walk, so it cannot disagree with what a register was cut
    for), and a module-level binding of any kind — an import, a constant, a
    class-level name — is `module_names`. Refusing a program that defines its
    own `sum` would be the false refusal this table's own header says a missing
    name must not be, and the emitter already asks exactly the first two
    questions before it takes the extern path.

    **`FOREIGN_ABI_BUILTINS` is excluded on purpose**, because those three are
    already refused at the emitter by `builtin_binding_refusal` with a strictly
    better sentence — the one naming the C function whose namesake would be
    bound — and this pass is asked before any emitter.

    **`EMITTER_BUILTINS` is excluded for the same reason and with a sharper
    consequence**, because a name there is not merely better refused downstream —
    it is LOWERED. `ord` and `chr` are in both tables, and they got there in
    opposite orders on 2026-10-04: `c8d877e9` measured them into
    `NOT_LOWERED_BUILTINS` (true of that tree), then `800472c1` gave the emitter
    an arm for both — `ord_fold` folds a literal's code point, and
    `text_builtin_refusal` refuses `chr` and `hash` by name — and this pre-pass,
    asked from `_prepare_functions` since `27bd1f5d`, then pre-empted it.
    Measured, both architectures, on that tree:

        ord("A")     refused "`ord` is not lowered on this path … a one-character
                     string to a code point"   where CPython answers 65 and this
                                                path's own emitter answers 65
        chr(233)     refused with a sentence about `int` — the `NOT_LOWERED_BUILTINS`
                     row for `ord`'s inverse, quoted for the WRONG NAME — where the
                     emitter's own message is the one that says where the answer
                     would have to live ("a NEW one-character string … nowhere to
                     put one")

    Nine rows of `test_formal_unicode.py`, all of which were green when
    `800472c1` landed them.

    **The table's `ord` row STAYS, and the reason is what it is for.** `ord` of a
    NAME is still refused, and refused correctly: the build cannot see what
    character a name holds, so there is nothing to fold and
    `text_builtin_refusal` says so. That is a fact about the value model — the
    same shape as `float`'s row, which is why `LOWERED_CALL_SHAPED_BUILTINS`
    exists — so removing the row would lose a true statement about the frontier
    and would also move the proof census's own partition, which reads this table.
    What was wrong was never the table; it was a pre-pass claiming a name the
    emitter already owns.
    """
    compiled = {f.name for f in (functions or [])}
    at_module = set(module_names or ())
    for fn in functions or []:
        for node in iter_nodes(getattr(fn, "body", None)):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr):
                continue
            name = node.func.name
            if name not in NOT_LOWERED_BUILTINS or name in compiled \
                    or name in at_module or callee_is_a_bound_value(fn, name):
                continue
            if name in LOWERED_CALL_SHAPED_BUILTINS or emitter_lowers(name):
                # A name one of the emitters LOWERS is answered downstream —
                # `ord("A")` folds to 65 and `chr(233)` is refused by the
                # sentence that is about a NEW one-character object — and this
                # pass would pre-empt both with a weaker, generic one. Asked
                # through `emitter_lowers` rather than by listing the names, so
                # the question is the emitters' own and the two cannot drift.
                # `float` is in the list because it is lowered through the
                # conversion path rather than a named builtin intercept, so
                # `emitter_lowers` does not see it.
                continue
            if name in EMITTER_BUILTINS:
                # THE EMITTER'S OWN TABLE, and the one exclusion that is not
                # about a better sentence: a name here is LOWERED by the backend
                # itself, so this pre-pass claiming it refuses a program the
                # backend can build. `ord` and `chr` are the two names in both
                # tables, and both were refused with a sentence about a
                # DIFFERENT name or a construct that is not the problem — see
                # this function's docstring for the two orders they arrived in
                # and the measurement.
                #
                # Read from the table rather than from a name list of its own,
                # because this is the THIRD place that would otherwise have to
                # know which builtins an emitter compiles: `EMITTER_BUILTINS`'s
                # own header says the set of names a backend compiles itself is a
                # fact three places have to agree on, and `800472c1`'s arm plus
                # this pre-pass is two of them plus a disagreement.
                continue
            if name in FOREIGN_ABI_BUILTINS:
                # `abs`, `pow` and `round` are in the table AND refused at the
                # emitter by `builtin_binding_refusal`, whose sentence is
                # strictly better: it names the C function whose namesake is
                # bound (`double pow(double, double)`) and the measured wrong
                # answer, which is what a reader has to act on and is more than
                # "a loop" is. This pre-pass is asked BEFORE any emitter, so
                # without the exclusion it would pre-empt that message with a
                # weaker one — the same mistake as a broad taxonomy marker
                # placed above a narrow one, and the reason the exclusion is
                # here rather than folded into the loop above.
                continue
            return (
                f"`{name}(...)` is not lowered on this path, and the reason "
                f"is a property of the NAME rather than of the link line: "
                f"`{name}`: {NOT_LOWERED_BUILTINS[name]}. Write the operation "
                f"out in the source — the emitter treated it as an ordinary "
                f"call to a C symbol and the link audit then refused the "
                f"image for binding a symbol nothing provides, which is true "
                f"and says nothing about what you wrote. Nothing on any link "
                f"line provides this function's semantics, so binding the name "
                f"is not a way to get it.")
    return None




# ── `debug_assert` ──────────────────────────────────────────────────────────
#
# A builtin of the LANGUAGE, in `myinterpreter.py:3010` in six lines, with no
# lowering at all on either backend. Both spellings failed, for two unrelated
# reasons, and neither of them was about the brackets:
#
#   * `debug_assert(cond, msg)` fell through every check and emitted a
#     `BL debug_assert` — an extern nothing defines. The link audit caught the
#     dangling symbol, so it was a refusal rather than a wrong image, but it
#     caught it by ordering accident, and 33 of the call sites in the new-modular
#     stdlib are spelled this way.
#   * `debug_assert[assert_mode="safe"](cond, msg)` was refused by
#     `specialization_call_refusal`, which is TRUE in general (a bracket needs a
#     declaration to bind to, and there is none) and FALSE here: `debug_assert`
#     is a builtin, so its declaration is a fact of the language rather than
#     something this image has to compile.
#
# WHAT IT MEANS, and it is small: evaluate the condition; on falsy, report and
# exit non-zero. The interpreter's version raises `AssertionError`, so the
# observable contract is the exit status and a message on stderr — and this
# backend has one output stream, so the status is the whole of what it can
# carry, exactly as it is for `AssertStmt` (whose arm says the same thing about
# its own message: "the nonzero exit status is the signal").
#
# WHAT IS NOT HERE, and each omission is a decision rather than a gap:
#
#   * `assert_mode`. The real `debug_assert` runs only when the ASSERT mode
#     matches, so `assert_mode="none"` (the DEFAULT) means the check is COMPILED
#     OUT and `assert_mode="safe"` means it is on. This path has no `ASSERT`
#     build setting to resolve that against, so the bracket cannot select
#     between them. It is read as the comptime argument it is and the check is
#     emitted either way: a lowered `debug_assert` that fires is the interpreter's
#     answer for every program written for this engine, and one that is silently
#     DROPPED is the `specialization_call_refusal` failure mode this section
#     exists to end. Refusing the bracket instead would have bought the same
#     refusal as before with a longer message.
#   * the variadic messages. `*messages: *Ts` with `write_to` on each element is
#     a variadic of values and belongs to `FORMAL_string_value_model.md`. The
#     arguments are still EVALUATED (they are ordinary Python argument
#     expressions, and evaluating them is what keeps a side effect from being
#     dropped), but nothing is formatted from them. `bugs/FORMAL_ast_module_
#     subset.md` and `FORMAL_known_limits.md` §1.1 are that neighbourhood.
#
# The two spellings are ONE construct with one predicate, because two private
# copies of "is this a debug_assert call" is how two architectures come to
# disagree about one call — which has happened on this backend more than once
# (see `run_cpython_pair_case`'s docstring).

# The bracket parameters `debug_assert` declares, as `std/builtin/debug_assert.mojo`
# declares them. Named because the bracket has to BIND against a declaration, and
# an unknown parameter name is a different call than the one this lowers: it is
# the refusal below rather than a silent accept of whatever the source wrote.
DEBUG_ASSERT_COMPTIME_PARAMS = ("assert_mode", "cpu_only", "_use_compiler_assume")


def debug_assert_callee(func) -> bool:
    """Whether `func`, a call's CALLEE, is `debug_assert` in either spelling.

    `debug_assert(cond, m)` and `debug_assert[assert_mode="safe"](cond, m)` are
    one construct: the bracket binds the builtin's comptime parameters and does
    not change what the call does on this path.

    Split out from `debug_assert_is_call` because `build.py`'s bracketed-callee
    scan holds the SUBSCRIPT and has no parent to find the call through, so it
    cannot ask the call-level question — and a reader who found only the
    call-level one would re-derive this rule beside it, which is how two
    architectures come to disagree about one construct.
    """
    if isinstance(func, F.IdentExpr):
        return func.name == "debug_assert"
    if isinstance(func, F.SubscriptExpr):
        base = func.obj
        return isinstance(base, F.IdentExpr) and base.name == "debug_assert"
    return False


def debug_assert_is_call(call) -> bool:
    """Whether `call` is a call to `debug_assert`, in EITHER spelling.

    The one entry point for a caller that holds the CALL. Keyed on the call
    rather than on a callee name because `iter_nodes` has no parent, and a
    name-based test would also match `len(debug_assert)`, which is not this
    construct.
    """
    func = getattr(call, "func", None)
    if func is None:
        return False
    return debug_assert_callee(func)


def debug_assert_bracket_refusal(func) -> str | None:
    """Why `debug_assert[…]` cannot bind its brackets, or None when they can.

    Asked by BOTH backends and by `build.py`'s bracketed-callee scan, and it is
    the one place that decides, because the failure it prevents is the exact one
    `specialization_call_refusal` was written for: a bracket the build cannot
    account for would otherwise be dropped, and `debug_assert[assert_mode="safe"]`
    dropping its bracket is the same silently-wrong image as `plain[3](5)`
    emitted as `plain(5)`.

    A bracket is refused when it binds a parameter `debug_assert` does not
    declare, or when it is a POSITIONAL bracket — `debug_assert[Int](c, m)`.
    Positional is refused rather than read as `assert_mode` because the
    declaration puts `Cond` first and a type is not a value; accepting it would
    mean inventing a binding the language does not have.
    """
    if not isinstance(func, F.SubscriptExpr):
        return None
    base = func.obj
    if not (isinstance(base, F.IdentExpr) and base.name == "debug_assert"):
        return None
    attrs = getattr(func, "attrs", None)
    if attrs is None:
        return (f"debug_assert[…] binds its brackets positionally, and this "
                f"path cannot bind them: `assert_mode`, `cpu_only` and "
                f"`_use_compiler_assume` are the parameters `debug_assert` "
                f"declares, and a positional bracket has no declaration to "
                f"bind against here. Write the bracket by name "
                f"(`debug_assert[assert_mode=\"safe\"](…)`), which is the "
                f"spelling every call site in the stdlib uses")
    for name, _value in attrs:
        if name not in DEBUG_ASSERT_COMPTIME_PARAMS:
            return (f"debug_assert[…] binds {name!r}, which is not a parameter "
                    f"of `debug_assert`: the builtin declares "
                    f"{', '.join(DEBUG_ASSERT_COMPTIME_PARAMS)}. Refused rather "
                    f"than ignored, because a bracket this path cannot account "
                    f"for is dropped silently and a dropped bracket is a call "
                    f"that returns an answer the source never wrote")
    return None




# ── Where a frame ADDRESS may be handed off, and why not ───────────────────
#
# A frame address is a word, so it can be passed anywhere a word can. Whether
# that is CORRECT is a question about the callee, and the two answers are
# different enough that one message cannot cover both — which is what the single
# "which this module does not compile" diagnostic did. It is not merely
# imprecise; for the larger of the two groups it named a cause that is not
# operating, and a reader who believed it would go looking for the callee's
# field list instead of at the thing that is actually wrong.
#
#   * a BUILTIN or a C library function. It is compiled, and it is compiled as
#     an operation on a VALUE: `len(x)` reads a length out of the object, a C
#     function takes the struct's BYTES. A frame address is neither. Handing one
#     over is not a missing layout, it is a category error, and it would be a
#     wrong answer even if the callee were handed the whole struct.
#   * a function this translation unit does not compile. Here the call has
#     nowhere to go AT ALL, whatever it is passed: the image contains one file's
#     functions, so the symbol is unbound before the receiver's type is even a
#     question. Saying so first is the honest order — the layout is a real
#     second question, but it is not the one that stops this program.
#
# A third possibility was not in that list and is the reason the default branch
# used to fire on 23 of this repository's 25 hand-off sites: **a name the
# analysis already has, classified as one it does not.** `Pointer` sat in the
# value-only set, and its text says the callee "wants the object itself … so
# what would arrive is the address `Pointer()` would then dereference as one" —
# but `Pointer` is an IDENTITY type constructor (`IDENTITY_TYPE_CTORS`), so what
# arrives is the answer, not the mistake, and `Pointer(to=stat)` over a frame is
# the one hand-off in this family that is simply correct. See
# `FRAME_ADDRESS_CTORS`.
#
# `origin_of` is the second member of that set, and it was the same mistake
# twice: it is not a callee that reads a value either, it is a compile-time
# intrinsic with no body here at all, so the dereference its sentence described
# was one nothing performs. See `FRAME_IDENTITY_CALLS` below, which is where it
# went.

# Calls by bare name that ASK FOR THE ADDRESS of what they are handed.
#
# DEFINED BELOW, next to `IDENTITY_TYPE_CTORS` and `STRING_TYPE_CTORS`, which
# it is derived from — see the note there. `frame_receiver_escape_refusal` is
# the only reader, and it reads the name at call time.
#
# What this does NOT make safe is a DEREFERENCE through the result, and that is
# already refused by name and for its own reasons: `DEREFERENCE_METHODS` covers
# `value`/`unsafe_value`, and it says why in terms a reader can act on (an
# 8-byte load over-reads a `UInt8` pointee, and for a struct pointee there is
# nothing at the address to load, because a struct's value on this path IS a
# frame address). So the word that escapes here is one nothing on this path
# dereferences.

# Calls by bare name that are COMPILE-TIME intrinsics with no runtime body, and
# which lower as the IDENTITY on their first argument: `origin_of(x)` names the
# storage `x` already lives in, and that is the whole of what it does.
#
# `origin_of` was in `FRAME_VALUE_ONLY_CALLS` until this table existed, and the
# sentence it was refused with is false in its central claim about 7 stdlib
# files. It said the callee "wants the object itself … so what would arrive is
# the address `origin_of()` would then dereference as one" — but `origin_of` has
# no body here to dereference anything: there is no call to emit, and nothing
# reads the address it names. So the hand-off was refused for a dereference that
# does not exist, and a reader who followed the advice ("give it a field,
# `origin_of(self.n)`") was sent to rewrite a program that is already correct.
#
# The identity is not a convenience, it is what the language means, and there is
# an oracle for it in the tree rather than a judgement call: `myinterpreter.py`
# defines `origin_of` as `lambda x, *args, **kwargs: x`. So the compiler that
# is this project's reference for the language already answers it this way, and
# a lowering that disagreed with it would be the one that is wrong.
#
# It is the IDENTITY rather than a fresh "origin" word, and the reason is the
# by-reference design: a frame address is already the address of the storage a
# multi-field struct occupies, which is exactly what an origin of that struct
# names. `origin_of(t).f` and `t.f` are therefore the same slot read, and
# `origin_of(t).f = v` is the same write — which is what the idiom in the corpus
# is FOR (`UnsafePointer(to=self._data).unsafe_origin_cast[origin_of(self)]()` is
# retargeting a pointer's origin from one object to its container). Erasing the
# call to the operand keeps every existing refusal load-bearing: the operand is
# then a bare frame holder in whatever position the call was in, so the escape
# walk, the holder fixpoint and the position rules all see it, and a name the
# analysis could not settle is still refused by them.
#
# The consumers are `frame_receiver_escape_refusal` (whose FIRST branch is this
# table, beside `FRAME_ADDRESS_CTORS`'s, because a hand-off to one of these
# names is not a refusal at all) and `identity_call_operand` below, which
# `formal/build.py`'s rewrite asks for the operand.
FRAME_IDENTITY_CALLS = frozenset({"origin_of"})


def identity_call_operand(callee: str, call):
    """The expression `call` lowers as ITSELF, or None if it is not one.

    `origin_of(x)` is the identity on its first argument.

    The one consumer is the REWRITE in `formal/build.py`, and that it is a
    rewrite rather than a lowering in the emitters is a measured decision rather
    than a preference — see `_rewrite_identity_intrinsic_calls` there for the
    two programs that are the reason. Briefly, because the escape analysis reads
    the AST: erasing the call in the emitter leaves `origin_of(s)` in the tree
    the build pass has already walked, so a frame address reaches the return
    statement, the variadic C call and the container without any of them being
    able to see it.

    A call with NO positional argument is not an identity call — there is no
    operand to be the identity of — and falls through to whatever refused it
    before, rather than reaching into an empty argument list. Keyword arguments
    are the same: the formal ABI has no keyword slots, and an `origin_of` that
    needed one is not the construct this table describes."""
    if callee not in FRAME_IDENTITY_CALLS:
        return None
    if getattr(call, "kwargs", None):
        return None
    args = getattr(call, "args", None) or ()
    return args[0] if args else None


# Calls by bare name that the model lowers as an operation on a value, and so
# take the VALUE rather than a pointer to it. `len` is here because it is the
# commonest one by an order of magnitude; the others are the value and type
# constructors, which all ask what the object IS.
#
# `origin_of` is NOT here and its being gone is a measured correction, not a
# tidy-up: it was refused as "lowered as an operation on a VALUE" for 7 stdlib
# files, and there is no such operation — see `FRAME_IDENTITY_CALLS` above, which
# is where the construct went and why the sentence it was refused with was false.
#
# The identity ADDRESS constructors are not here either — see
# `FRAME_ADDRESS_CTORS` above for the measurement — and the string-producing
# identity ones (`String`, `str`, `StringLiteral`, `StringSlice`) stay, because
# they are the opposite case: the word they are handed becomes a `char *` that
# every `%s` and every string method DEREFERENCES, so handing one a frame
# address is handing printf an address to read as text.
FRAME_VALUE_ONLY_CALLS = {
    "len", "isinstance", "issubclass", "repr", "str", "int",
    "float", "bool", "hash", "id", "type", "String",
    "StringRef", "PointerType",
    # The container and scalar CONSTRUCTORS, and the folds over them.  They are
    # here for the same reason `len` is: each is lowered as an operation on the
    # value it is handed, and each is a bare name the model compiles rather than
    # a function, so without this row they fell into "this module does not
    # compile" — which for `list(x)` is false in a way a reader would have to
    # go and check.
    "list", "dict", "set", "tuple", "slice", "range", "enumerate", "zip",
    "sorted", "reversed", "sum", "min", "max", "abs", "round", "divmod",
    "chr", "ord", "hex", "oct", "bin", "any", "all",
    # `debug_assert` is here rather than in `FRAME_VARIADIC_BUILTIN_CALLS`
    # beside `print`, and the two rows answer DIFFERENT questions about it, so
    # the placement is worth stating. It is a builtin that reads the VALUE it is
    # handed — the CONDITION's truthiness, via `_emit_truthy_word` — so a frame
    # address is a category error for the first argument exactly as it is for
    # `len`: what would be tested is the ADDRESS. Its MESSAGE arguments are the
    # variadic half, but this path does not format them yet (see
    # `debug_assert_is_call`), so a frame there is not yet rendering as a
    # decimal address, and putting the name in the variadic set would refuse a
    # shape on the strength of a formatting that does not exist yet.
    #
    # Measured: without this row `std/collections/interval.mojo`'s
    # `debug_assert(self.overlaps(other), "…'", self, "' and '", other, "'")`
    # was refused as "`debug_assert()` … is a name with no definition in hand in
    # this image", which is false — it is a builtin this path compiles, and the
    # refusal sent the reader looking for a missing callee.
    "debug_assert",
}

# Calls by bare name that reach the C library and take the struct's STORAGE —
# that is, whose own prototype names a POINTER TO THE STRUCT and reads or
# writes through it.  Four members, and each is there because of its prototype
# rather than because of what it feels like:
#
#     size_t memcpy(void *, const void *, size_t)
#     int    memcmp(const void *, const void *, size_t)
#     void   qsort(void *, size_t, size_t, int (*)(const void *, const void *))
#     int    stat(const char *, struct stat *)   / lstat / fstat
#
# The other nine names this set used to hold take VALUES and never mention the
# struct's layout: `open(const char *, int, ...)`, `close(int)`,
# `read`/`write(int, void *, size_t)`, `readv`/`writev(int, const struct iovec
# *, int)`, `ioctl(int, unsigned long, ...)`, `fcntl(int, int, ...)`,
# `mmap(void *, size_t, int, int, int, off_t)`.  A frame address handed to any
# of them is a number where a descriptor, a flag word or a length belongs —
# which is the OTHER reason, and telling a reader it "reads the struct's BYTES"
# sends them to go and compare a field list against the C headers' padding for a
# struct the callee does not have.  They are in `FRAME_C_VALUE_CALLS` now, which
# is not a tidiness change: the two sets are what the two sentences mean, and a
# name in the wrong one gets a reason that is not true of it.
FRAME_C_LIBRARY_CALLS = {
    "memcpy", "memcmp", "qsort", "stat", "lstat", "fstat",
}

# Calls by bare name that reach the C library and take a VALUE of a type their
# own prototype names — a `char *`, an `int`, a count.  A separate set from the
# one above because the reason is different and both are worth saying: these do
# not read the struct's bytes, they want one of its fields, and they are
# VARIADIC in the formatting cases, so a frame address is not merely the wrong
# category — it is read by whatever conversion the format string names, and the
# program prints a number nobody wrote and exits 0.
#
# `printf` was the measured one and it is the reason this set exists: it was
# falling through to the "no definition in hand" branch, which is false (it is
# libSystem's, and it binds) in a way that would send a reader looking for a
# missing export.
#
# `memcmp` and `qsort` are in BOTH sets, and that is not an oversight: read
# through a `void *` they want bytes, and read through the frame-address
# argument convention this file uses they want a word.  `FRAME_C_LIBRARY_CALLS`
# is consulted first, so they get the storage reading, which is the one that is
# true of the prototype.  `abs` and `labs` are here and in
# `FRAME_VALUE_ONLY_CALLS` for the same kind of reason: one name, two
# implementations in this compiler (a builtin lowered as an ALU sequence, and
# libSystem's), and the C one is named because a reader who is looking at `abs`
# is looking at the C library.
FRAME_C_VALUE_CALLS = {
    "open", "close", "read", "write", "readv", "writev", "ioctl", "fcntl",
    "mmap",
    "printf", "sprintf", "snprintf", "fprintf", "vprintf", "vsnprintf",
    "vfprintf", "fputs", "puts", "putchar", "putc", "strlen", "strnlen",
    "strcmp", "strncmp", "memcmp", "atoi", "atol", "atoll", "exit", "abort",
    "malloc", "calloc", "realloc", "free", "memset", "qsort", "abs", "labs",
}

# Builtins of the LANGUAGE that this backend compiles, and that are VARIADIC over
# conversions — so what they are handed is FORMATTED, and a word is a perfectly
# good thing to format.
#
# `print` is here and NOT in `FRAME_C_VALUE_CALLS`, and the reason is the same
# one that put `abs` in two sets: the sentence for that set says "a C library
# entry point", and `print` is Mojo's builtin lowered through `_emit_print` in
# each backend's call emitter, not a C symbol.  A reader sent to `printf`'s
# prototype would be looking for a function this program never names.  The
# CONSEQUENCE is the one measured on `printf`, and it is the reason this set
# exists rather than a comment: with the refusal lifted, `print(p)` builds,
# runs, exits 0, and prints the frame's ADDRESS as a decimal — 6102330608 on
# arm64 and 13027830976 on x86-64 for the same source, and a different number
# on every run because the address moves.  A silently wrong answer, which is
# the outcome this whole family exists to prevent.
#
# THE MESSAGE SAYS "frame address is passed to" — lowercase, and not "receiver
# is passed to" — and that is load-bearing in the same way the fifth branch's
# opening clause is.  Those two are the sweep's markers for row 7 and for the
# position family, and this refusal is about the argument's CATEGORY (row 7),
# not about there being no callee.  Written as "receiver", the one stdlib file
# that reaches it (`test/builtin/test_default_writable_compile_fail.mojo`) was
# counted in the position family; written as "frame ADDRESS", it fell into
# `other refusal`, which is the bucket this taxonomy exists to empty.  Both were
# numbers in the wrong column, with no test failing either time, so the marker is
# quoted in the comment above rather than left to be rediscovered.
#
# ONE name, and deliberately a set rather than a general rule: a builtin the
# backend does not compile must NOT be answered from here, and the only honest
# test for "the backend compiles this" is no longer a name someone wrote down
# after measuring it — it is `EMITTER_BUILTINS` above, which both emitters' own
# `if name == …` chains read, so the three places that have to agree now do.
#
# DERIVED from that table rather than written out, because a set written out
# beside the table it is a subset of is the second place the fact lives wearing
# a third name. It is also NARROWER than `EMITTER_BUILTINS` on purpose: `len` and
# `range` take a container and an integer, so handing one a frame address is a
# LAYOUT question with its own refusal, while what is left here is the set whose
# members FORMAT whatever they are handed. `emitter_lowers` is the wider
# question; this is the variadic-over-conversions half of it.
FRAME_VARIADIC_BUILTIN_CALLS = {
    name for name in EMITTER_BUILTINS
    if name in ("print",)
}


def frame_receiver_escape_refusal(callee: str, struct_names,
                                  imported_from: str = None,
                                  comptime_param_of: str = None,
                                  star_imported_from: str = None) -> str | None:
    """Why handing a frame ADDRESS to `callee()` is wrong, or None if it is not.

    `struct_names` is what the receiver's frame could be — one name, or several
    where the holder's type was not settled (see
    `struct_frame_slot_candidates`). The text names the struct because a
    refusal that does not is one the reader has to re-derive.

    Returns None for a callee that is one of this module's own functions: those
    take the receiver as their first parameter, which is the whole of the
    by-reference design, and their frame layout is settled at compile time. The
    CALLER decides which callees those are — it is the only side that knows
    what it compiled — so this function is about the cases where the answer
    does not depend on that.

    SIX answers, and the order is the order the question is actually decided
    in, because the first four are the ones that were being answered wrongly:

    1. an ADDRESS constructor, and a compile-time IDENTITY intrinsic — **not a
       refusal at all**, and for the first of the two that is the measurement
       rather than a hope (see `FRAME_ADDRESS_CTORS` and
       `FRAME_IDENTITY_CALLS`);
    2. a C library entry point, which reads the struct's BYTES;
    3. a type constructor the model knows about but cannot represent, which is a
       different thing again from "a function this module does not compile" and
       used to be reported as it;
    4. a name lowered as an operation on a VALUE;
    5. everything else, which is a name this build compiles nowhere — and which
       is `frame_undefined_callee_refusal`, FOUR sentences rather than one,
       because "no definition in hand" is a true statement about only one of
       the four things a callee can be when it is not a function of this image
       (an imported one IS compiled, elsewhere; a compile-time parameter never
       will be).

    `imported_from` and `comptime_param_of` are the two facts that pick between
    those four, and both are the CALLER's to supply — an import table and an
    enclosing `def[…]`'s parameter list, neither of which this module has. They
    default to None, which is the generic fifth-branch text: the other caller
    (`_callee_wants_a_value`'s, and `_check_frame_escapes`'s
    `_callee_wants_a_value` path) reaches case 5 for a callee it has already
    classified as wanting a value, so case 5 is unreachable from there."""
    who = ", ".join(struct_names) if struct_names else "this struct"
    if callee in FRAME_ADDRESS_CTORS:
        # Measured, not assumed: see FRAME_ADDRESS_CTORS. Returning None here
        # is the whole of the fix for the `_c_stat`/`Pointer(to=stat)` shape.
        return None
    if callee in FRAME_IDENTITY_CALLS:
        # `origin_of(x)` names the storage `x` lives in, and a frame address IS
        # the address of the storage a multi-field struct occupies, so there is
        # no hand-off here to refuse: the operand arrives as itself, and every
        # channel out of the frame is checked on the operand from there. Before
        # this branch the call fell through to the value-only set and was
        # refused for a dereference `origin_of()` does not perform.
        return None

    if callee in FRAME_VARIADIC_BUILTIN_CALLS:
        # Between the ADDRESS constructor and the C entry points, because it is
        # neither: this name IS compiled, so it cannot fall through to case 5
        # ("no definition in hand"), and it is not a C symbol, so the C
        # sentences are false of it.  Measured consequence in the set's comment.
        return (f"a {who} frame address is passed to {callee}(), which is a "
                f"builtin of the language rather than a C entry point, and it is "
                f"VARIADIC over conversions: whatever it is handed, it formats. "
                f"A frame address is a word, so what it formats is the ADDRESS, "
                f"and a decimal rendering of it is indistinguishable from a "
                f"number the program meant to print. Measured with this refusal "
                f"lifted, on both architectures: the image builds, runs, exits "
                f"0, and prints the frame's address — 6102330608 on arm64 and "
                f"13027830976 on x86-64 for the same source, and a different "
                f"number on every run, because the address moves. Not a missing "
                f"layout and not a missing callee: a wrong CATEGORY of "
                f"argument, the one {callee} shares with `printf` in a "
                f"different wrapper. Read a field out first "
                f"(`{callee}(p.a)`)")
    if callee in FRAME_C_LIBRARY_CALLS:
        return (f"a {who} frame address is passed to {callee}(), which is a C "
                f"library entry point and reads the struct's BYTES, and the "
                f"frame is a block of 8-byte slots at `base + 8k` in DECLARATION "
                f"order. That is the C layout of a struct whose every field is 8 "
                f"bytes wide and 8-aligned, so the two coincide exactly in that "
                f"case — but the struct {callee}() knows about is the C "
                f"library's own declaration of it, with the widths and padding "
                f"from the C headers rather than from the Mojo declaration "
                f"here, and nothing on this path compares the two. So the "
                f"coincidence is per-struct and unestablished, and a mismatch "
                f"reads the wrong words and returns a number the source never "
                f"wrote")
    if callee in FRAME_C_VALUE_CALLS:
        return (f"a {who} frame address is passed to {callee}(), which is a C "
                f"library entry point and takes a VALUE of a type its own "
                f"prototype names — a `char *`, an `int`, a count — not the "
                f"struct's storage. A frame address is an address, and in the "
                f"formatting cases the argument is VARIADIC, so whatever "
                f"conversion the format string names is applied to it: "
                f"measured, `printf(\"val=%d\\n\", r)` builds, runs, prints the "
                f"frame's address as a decimal, and exits 0. Read a field out "
                f"first (`{callee}(…, r.n)`)")
    tkind = type_constructor_kind(callee)
    if tkind is not None and tkind[0] == "unsupported":
        return (f"a {who} frame address is passed to {callee}(), and {callee} is "
                f"a real type this path has no representation for at all: one "
                f"formal value is one 64-bit word, and {callee} is not one "
                f"word. That is a different fact from the frame layout, and it "
                f"is the one that stops this program — there is no argument to "
                f"give it, frame or otherwise")
    if callee in FRAME_VALUE_ONLY_CALLS or (tkind is not None
                                            and tkind[0] == "identity"):
        # The `identity` half of the disjunction is the STRING-producing
        # identity constructors — `StringSlice` and `StringLiteral`, which are
        # in neither this set nor `FRAME_ADDRESS_CTORS` and would otherwise
        # fall through to the "no definition in hand" branch, which is the
        # same misclassification one layer down: `StringSlice` is a name this
        # model compiles. What makes it a refusal is the same thing that makes
        # `String` one: the word becomes a `char *` that callers dereference.
        return (f"a {who} frame address is passed to {callee}(), which is "
                f"lowered as an operation on a VALUE: it wants the object "
                f"itself, and on this path a multi-field struct has no value "
                f"form — its receiver is a pointer to a frame of 8-byte slots, "
                f"so what would arrive is the address {callee}() would then "
                f"dereference as one. Not a missing layout: a wrong category "
                f"of argument. Give it a field (`{callee}(self.n)`) or copy "
                f"the value out first")
    return frame_undefined_callee_refusal(callee, struct_names,
                                          imported_from, comptime_param_of,
                                          star_imported_from)


# Names that are not functions at all, and the one that reaches this branch from
# the standard library five times over.
#
# `__get_mvalue_as_litref` is a compile-time REFLECTION INTRINSIC of the
# compiler: it is handed a value and hands back an MLIR reference to it, so
# there is nothing at all for a receiver to be handed TO — the reference it
# would produce does not exist on a path with no MLIR. Named here rather than
# left to the generic sentence because the generic sentence sends the reader
# looking for a missing export, and this name has never been an export of
# anything: it is 5 of the 12 files the sweep reports under "callee has no
# definition on this path", and 48 of its 50 spellings in the standard library
# are the operand of an `__mlir_op.…` build, which is the construct this path
# refuses one level up (the `__mlir_*` family, `mlir_dialect_refusal`).
#
# A SET and not a prefix rule, deliberately: `MLIR_DIALECT_PREFIX` is a
# different construct with its own refusal and its own owner, and a `__mlir_`
# prefix test here would swallow names this path already answers elsewhere.
COMPTIME_REFLECTION_INTRINSICS = frozenset((
    "__get_mvalue_as_litref",
))


# PYTHON BUILTINS THIS PATH DOES NOT IMPLEMENT, and why each one has no answer
# here. The values are the second half of the sentence they appear in.
#
# This is the table the `getattr`/`setattr` finding was waiting for — "a program that reaches one
# of them is a program with a Python builtin this backend does not implement,
# which is a fact about the backend's surface rather than about the image, and
# naming it needs a table of what the backend DOES implement" — which is the
# table immediately below. `std/memory/unsafe_pointer.mojo` is the file that
# asked for it: it is refused with "a Pointer receiver is passed to type_of()",
# and the honest reading of that sentence is "`type_of` is a missing builtin, on
# any receiver".
#
# **Why the existing sentence is wrong for these and only these.** The last arm
# of `frame_undefined_callee_refusal` says "this module defines no FUNCTION of
# that name … and no `from … import …` in it binds the name either", which sends
# the reader to look for a missing `def` or a missing import. For a builtin both
# of those are impossible: the name comes from the LANGUAGE, so there is
# nothing to define and nothing to import. Every other callee in this branch is
# a name somebody might have meant to define, which is exactly why the sentence
# is right for them.
#
# `type_of` is here on the measurement in that doc; the four attribute builtins
# are here on the `getattr`/`setattr` finding in the hand-off doc, which names
# them as reaching this same branch. Neither list is exhaustive and this is the
# one place to add to — a name added here changes a diagnostic, never a verdict:
# the hand-off is unsound either way, because none of these has a compiled body
# to hand an address to.
#
# **A name here is a name THIS IMAGE has no function of, not a spelling.** The
# arm is inside `frame_undefined_callee_refusal`, and the refusal it is reached
# from returns None for a callee that is one of this module's own functions
# (`frame_receiver_escape_refusal`'s docstring, case by case). So a module that
# defines its own `getattr` never arrives here and keeps being an ordinary
# function that takes a frame receiver by reference — which is the one thing a
# name-keyed table can get wrong silently, and which
# `test_formal_run.py`'s `byref_a_local_getattr_is_not_the_builtin` pins.
UNIMPLEMENTED_BUILTINS = {
    "type_of": (
        "its answer is a TYPE, and this path has no value that denotes a type: "
        "every value is one 64-bit word (`pointer_value_model`), a struct "
        "crosses a boundary as a LAYOUT rather than as something that is 'of' "
        "its class, and a type name read as a value has no home at all — so "
        "there is no answer to hand back whatever the receiver is, and the "
        "receiver's layout is not the question here"),
    "getattr": (
        "the attribute it names is a run-time STRING — the name is an "
        "argument, so the build does not know which field is being asked for "
        "until the program runs, and a field read on this path is a load from "
        "`[base, #8k]` with a slot index computed from the struct's own field "
        "list; a frame has no element width and no length, so a run-time-indexed "
        "read of one is not an address arithmetic question this backend can "
        "answer. **A LITERAL name is not this case and is not refused**: "
        "`getattr(p, \"a\")` is `p.a`, and `LITERAL_ATTRIBUTE_READ_CALLS` below "
        "erases it to that before any of this is asked — so the sentence you are "
        "reading applies to `getattr(p, f.name)` and to `getattr(p, k)`, which "
        "are the shapes this build cannot answer"),
    "setattr": (
        "the same run-time string, and a store rather than a load — which also "
        "means the write's target is not a slot the build established, so "
        "there is nowhere proved to write to"),
    "hasattr": (
        "its answer is whether the attribute is there, and on this path a field "
        "read has no absent case to report: a frame's slots are its whole "
        "layout, so the question has no representation to be answered in"),
    "delattr": (
        "its effect is to remove a field from an object, and an object here is "
        "a frame block with a fixed layout and no storage to give up — the "
        "field list the build compiled against is not something a call can "
        "change"),
}


#: Calls whose answer is an attribute read the build can compute, because the
#: SOURCE wrote the name.  `getattr(o, "a")` is `o.a`: the name is a literal, so
#: the slot index comes from the struct's own field list exactly as it does for
#: the `MemberExpr` spelling, and there is nothing run-time about it.
#:
#: **The refusal in `UNIMPLEMENTED_BUILTINS` above says the name is "a STRING at
#: run time", and for this spelling that is FALSE** — which is the whole reason
#: this table exists, and the failure mode is the one the wide-receiver family
#: documents itself as existing to prevent: a reader with a two-word program
#: that this path could answer is told the question is unanswerable in principle.
#: Measured, before the rewrite existed:
#:
#:     struct Pt:  a, b
#:     var v = getattr(p, "a")
#:
#: refused with that paragraph, on both architectures, naming four things that
#: are none of them the problem.
#:
#: `getattr` only, and the three siblings stay refused for the reasons their own
#: entries give: `hasattr` asks whether the attribute is THERE (a frame's slots
#: are its whole layout, so there is no absent case), `setattr` is a store whose
#: target is not a slot the build established, and `delattr` removes one.
LITERAL_ATTRIBUTE_READ_CALLS = frozenset({"getattr"})


def literal_attribute_read(call):
    """`(receiver, member)` for `getattr(o, "name")` with a LITERAL name, or
    None.

    The one consumer is the REWRITE in `formal/build.py`, beside
    `_rewrite_identity_intrinsic_calls`, and it is a rewrite for the same
    measured reason that one is: every check downstream of this point reads the
    AST, so lowering the call in an emitter would leave `getattr(p, "a")` in the
    tree the field-read analysis has already classified, and a name nothing
    classifies is what the frame walk then walks straight through.

    **Only a bare string literal.** A concatenation, an f-string, a `+`, a
    constant read, a `String()` construction or anything with a keyword
    argument is a name the build cannot fold, and each of those keeps the
    refusal — which is the right answer, so the rewrite must not widen the set
    of programs that build past the analysis to keep the table small.

    `hasattr`/`setattr`/`delattr` are not asked here at all; see
    `LITERAL_ATTRIBUTE_READ_CALLS`.
    """
    func = getattr(call, "func", None)
    if not isinstance(func, F.IdentExpr):
        return None
    if func.name not in LITERAL_ATTRIBUTE_READ_CALLS:
        return None
    if getattr(call, "kwargs", None):
        return None
    args = getattr(call, "args", None) or ()
    if len(args) != 2:
        return None
    name = args[1]
    if not isinstance(name, F.StringLiteral) or not name.value:
        return None
    return args[0], name.value


def frame_undefined_callee_refusal(callee: str, struct_names,
                                   imported_from: str = None,
                                   comptime_param_of: str = None,
                                   star_imported_from: str = None) -> str:
    """Why a callee no image in this build COMPILES cannot take a frame address.

    This is `frame_receiver_escape_refusal`'s fifth case, split — it was one
    sentence over five different facts, and four of the five were false of the
    program in front of the reader.  Measured on the 12 files the sweep files
    under it (the `2026-09-30` round of `bugs/FORMAL_sweep_work_map.md` row 8), and on the 41
    over all roots — the population and the per-arm classification are both in
    `test_refusal_taxonomy.py::_no_def_callee_arm_checks`, one callee per arm:

      * `_b64encode`, `discover_closures` — the callee is IMPORTED, so it IS
        compiled, into another module's library.  "this module's own functions
        are the only ones in this image" and "there is no such callee here to be
        compiled" are both false of those two, and a reader who believed either
        went looking for a missing export that is not missing.
      * `ElementFn`, `Fn` — the callee is a COMPILE-TIME PARAMETER of the
        enclosing `def`, so there is no callee to compile and never will be
        until something instantiates it.  Nothing is missing.
      * `__get_mvalue_as_litref` — a compiler intrinsic that yields MLIR.
      * a name reachable only through `from M import *` — the star import binds
        whatever M EXPORTS, so "nothing binds it" is only true once the link
        line has been asked and does not publish the name (22 files of the
        standard library write a star import).
      * the rest — genuinely unbound, which is what the old sentence said and
        is the only one of the five it was true of.

    **The two imported arms are now REACHABLE ONLY WHEN THE LINK LINE DID NOT
    ANSWER**, and that is the whole of what changed for them. A frame address
    handed to a function compiled in another module was refused here because
    this pass could not know whether that compilation made the parameter a frame
    holder; it can now, because each export carries the per-parameter
    frame-holder contract in its manifest (`frame_params`) and
    `check_imported_frame_handoffs` decides the hand-off from it — following the
    address when the callee's struct is the one this image has, and refusing
    with a named disagreement when it is not. So these arms describe what is
    left after that comparison has been made and has come out with nothing to
    compare, not the shape of the construct.

    The order is the order the question is decided in: a name that is not a
    function, then a name that is a parameter, then a name from another module
    by name, then a name that could only come from a star import, then nothing.
    Each returns a refusal, because the hand-off is unsound in all five: what
    differs is only WHICH fact makes it unsound, and a message that names the
    wrong one is a message that sends the reader after a non-bug — which is the
    defect this family exists to stop.  The cross-module METHOD case already
    answered the second question (see `frame_opaque_position_refusal`'s `why=`
    for `cross_module`), and this is the FREE-FUNCTION half of it: `owners` is
    the imported-METHOD table, so a plain imported function was never in it and
    fell through to here.

    `imported_from` is the module the name is imported from, as the source
    spells it (`._b64encode`); `comptime_param_of` is the name of the function
    whose `def[…]` declares the callee; `star_imported_from` is the module of a
    `from … import *` in this file.  All three are facts the CALLER has:
    `formal.imports.imported_bound_names` and `star_imported_modules` read the
    import statements without resolving them (this pass runs before
    `_resolve_imports`), and `FunctionDef.comptime_params` is the declaration
    itself.

    **EVERY arm opens with the clause `which is a name with no definition in
    hand`, and that is load-bearing rather than a courtesy.**  Two taxonomies key
    on that exact substring — `tools/formal_sweep.py`'s `_FRAME_ESCAPES` and
    `tools/formal_sweep_causes.py`'s `callee has no definition on this path` —
    and it is what keeps this family out of the `receiver passed as an argument`
    bucket that its own message begins with.  An arm that reworded the opening
    would not fail here: it would drop every file it names out of the family
    they are counted in, into whichever family matches next, with no test
    failing and a wrong number in a table a planner acts on.  Measured after
    this split: 41 files, all 41 still classified `callee has no definition on
    this path` by both tools, 41 messages changed and nothing else did."""
    who = ", ".join(struct_names) if struct_names else "this struct"
    if callee in COMPTIME_REFLECTION_INTRINSICS:
        return (
            f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand in this image, and the reason is not a missing "
            f"export: {callee} is not a function at all. It is a compile-time "
            f"REFLECTION INTRINSIC of the compiler, which is handed a value and "
            f"hands back an MLIR reference to it. There is no MLIR on this path "
            f"— an attribute, a type or an operation has no representation in a "
            f"model whose every value is one 64-bit word — so the reference it "
            f"would produce does not exist here at any stage of the compilation "
            f"and there is nothing compiled to hand an address to. In the "
            f"standard library it is the operand of an `__mlir_op.…` build (48 "
            f"of its 50 spellings), and that construct is what this path "
            f"refuses; this name is its operand rather than a call of its own. "
            f"Nothing about the receiver's layout is at fault here")
    if callee in UNIMPLEMENTED_BUILTINS:
        return (
            f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand in this image, and the reason is not that "
            f"anything is MISSING and not that this file forgot to declare it: "
            f"`{callee}` is a Python BUILTIN, a name the language provides, so "
            f"there is no `def` to find here and no import that could bind it. "
            f"No part of this path implements it, and there is no answer for it "
            f"to give: {UNIMPLEMENTED_BUILTINS[callee]}. That is a fact about "
            f"what this backend does, not about the receiver — so nothing about "
            f"{who}'s layout is at fault, and no declaration of {callee} in "
            f"this file would change it. `UNIMPLEMENTED_BUILTINS` is the one "
            f"table of what this path does not implement, and adding a name to "
            f"it is all it takes to name the next one")
    if comptime_param_of:
        return (
            f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand in this image, and none of the kind that could "
            f"be added to it: {callee} is a compile-time PARAMETER of "
            f"{comptime_param_of}, declared in its "
            f"`def {comptime_param_of}[… {callee} …]`, and calling one means "
            f"MONOMORPHISING it. The body comes from the argument at each call "
            f"site and is instantiated against that argument's own struct, so "
            f"the callee's field list is a property of the call rather than of "
            f"any declaration in hand. This path does not instantiate type "
            f"parameters, so there is nothing here that was compiled against a "
            f"field list, and an address handed to it would point at a layout "
            f"the callee never learned. Measured: `def drive[Fn: def(mut W)]` "
            f"calling `Fn(w)` on a `W` frame reaches here and the image cannot "
            f"be built. Nothing is missing — the callee does not exist until a "
            f"call site creates it, and nothing here creates one")
    if imported_from:
        return (
            f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand IN THIS IMAGE and not because this module "
            f"lacks one: it imports {callee} (`from {imported_from} import "
            f"{callee}`), so {callee} IS compiled — by {imported_from}, into a "
            f"library of its own, when that module builds at all. That is "
            f"not by itself a reason to refuse — a frame address is exactly "
            f"what a method of the receiver's own struct wants, and the "
            f"cross-module METHOD case is followed across the boundary. It used "
            f"to be a reason, and this sentence is what it said: the fact that "
            f"decides the hand-off is whether THAT compilation made the "
            f"parameter this argument lands in a frame holder, and a module is "
            f"compiled with its own call sites, so this pass could not know. "
            f"That module now PUBLISHES it — the per-parameter frame-holder "
            f"contract each export carries in its manifest (`frame_params`, "
            f"written by `formal/build.py`'s `_export_frame_contract`) — and "
            f"`check_imported_frame_handoffs` compares that against the struct "
            f"this image has, so the hand-off is followed when the two agree and "
            f"refused with the disagreement when they do not. This arm is now "
            f"only reached when the callee is NOT resolved through the link "
            f"line, and the message says so. "
            f"test_refusal_taxonomy.py::_no_def_callee_arm_checks classifies "
            f"this arm in both tables, with a callee that reaches it")
    if star_imported_from:
        return (
            f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand in this image, and this module neither defines "
            f"{callee} nor names it in any `from … import …`. The one "
            f"thing that can bind a name like that here is a "
            f"`from {star_imported_from} import *`, and what such a statement "
            f"binds is {star_imported_from}'s EXPORT SET — which is not a fact "
            f"about this file at all. Both of the questions this used to call "
            f"unanswerable are now answered, from the link line rather than "
            f"from the statements: whether {star_imported_from} exports "
            f"{callee} is what its manifest's export table says, and whether "
            f"its compilation made the parameter this argument lands in a frame "
            f"holder is the `frame_params` contract that table now carries. "
            f"This arm is reached when the link line settles NEITHER — so "
            f"{callee} is not among the names any library on it publishes, and "
            f"there is no contract to compare. "
            f"test_refusal_taxonomy.py::_no_def_callee_arm_checks classifies "
            f"this arm in both tables, with a callee that reaches it")
    return (f"a {who} receiver is passed to {callee}(), which is a name with no "
            f"definition in hand in this image: this module defines no FUNCTION "
            f"of that name — a method declared here is reached as "
            f"`recv.{callee}(…)` or under its lifted `<Struct>_<method>` name, "
            f"and a bare `{callee}(recv)` is a spelling this path does not "
            f"lower — and no `from … import …` in it binds the name either. So "
            f"the symbol is unbound before the receiver's layout is a question. "
            f"A frame address would be meaningful to a callee compiled against "
            f"the same field list, but there is no such callee here to be "
            f"compiled. "
            f"FORMAL_wide_receiver_by_reference.md (deleted; fixed) records the design and "
            f"what is still open about it")




# ── The three hand-off shapes the escape check refused as one ───────────────
#
# `_check_frame_escapes` used to spell all of these with the same sentence, and
# two of the three said something that is not true of the program in front of
# the reader. They are separate functions, in this file, so the two backends
# cannot answer them differently and a reader gets the one that operates.
#
# The third of those shapes — a struct CONSTRUCTOR reached with a frame address
# — is no longer here at all, and its REMOVAL is the content. It was reported
# as "a X receiver is passed to R(), which this module does not compile", false
# twice over (`structs_by_name` holds `R`, which is the only reason the argument
# is a frame address, and a struct has no body to compile), and its real
# content was one level down: a copy construction had no lowering. It has one
# now, so the diagnostic moved from "this is not a call" to "here is which of
# the three shapes this is, and here is why this one is not representable" —
# `struct_construction_plan` below, which is the one place both backends and
# the build pass read it from.


def _who(struct_names) -> str:
    return ", ".join(struct_names) if struct_names else "this struct"


def _where(position, total, kwname: str = None) -> str:
    """`in argument position 1 of 3`, or the keyword's own name.

    A keyword argument has no position to quote, and printing the index it
    happens to occupy in the concatenated `args + kwargs` list is a statement
    about the ANALYSIS's list rather than about the call — the word lands
    wherever the parameter list says it does, and a reader sent to position 2
    of a call that wrote `take(x=1, y=r)` goes looking in the wrong place."""
    if kwname:
        return f"as the keyword argument {kwname!r}"
    return (f"in argument position {position}"
            + (f" of {total}" if total and total > 1 else ""))


def frame_opaque_position_refusal(where_the: str, callee: str, position,
                                  total, struct_names, method: str = None,
                                  kwname: str = None, why: str = None,
                                  callee_shape: str = None) -> str:
    """A frame address in a position THIS PASS cannot establish.  Case 3.

    The honest remainder, and it is marked as a statement about the ANALYSIS
    because that is what it is: there is no declaration in hand for the
    parameter this argument lands in, so nothing here can say whether the
    callee treats that word as a frame address.  Every shape that CAN be
    established is established instead — see `frame_holder_disagreement_refusal`
    for the one where the declaration is in hand and the two call sites
    disagree, which is a different thing and a commoner one.

    `why` names which of the ways the declaration is missing, because "this
    pass cannot see it" without the reason is the sentence this whole family
    was written to stop saying.

    `method` is the source's spelling of a callee that IS a method call
    (`recv.m`), and `callee_shape` the short name of a callee that is NOT — a
    computed callee, say.  They are two different sentences because the method
    one is about NAME dispatch, which is a real fact about the language, and
    the other is about there being no name at all.  **One message covering both
    was a refusal for a reason that was not operating**: a `f[comptime](x)`
    call — a generic specialization, resolved by `call_callee_name` and
    followed like any other callee — used to be reported as "a method call on a
    value receiver is dispatched by NAME", which mentions a receiver, a method
    and a dispatch that the source does not contain.  Measured on the corpus,
    6 of the 25 files whose terminal finding this message produced had a
    comptime specialization here and none of them has a method call."""
    who = _who(struct_names)
    head = (f"a {who} receiver is passed to {where_the} "
            f"{_where(position, total, kwname)}, and {why or 'the callee is a shape this pass cannot name'}. ")
    if callee_shape:
        return (head +
                f"The callee of this call is {callee_shape}, which names no "
                f"function this pass has a parameter list for, so nothing here "
                f"can say whether the callee treats that word as a frame "
                f"address. This is a limit of the ANALYSIS and not a fact "
                f"about the program: the frame belongs to the function that "
                f"created it, that function is an ancestor of the callee — the "
                f"address reached the callee through an active call — so a "
                f"read or a write through this parameter would be in the right "
                f"place. What is NOT the case is the shape this message used to "
                f"be given for: a frame address in `f(x)` and in "
                f"`f[comptime](x)` is followed into `f`'s parameter at that "
                f"position, in every position and not only the first, because "
                f"both spellings name `f` and its parameter list is in hand")
    if method:
        return (head +
                f"This is not a question about the position: a METHOD call on a "
                f"value receiver is dispatched by NAME, so `recv.m(x)` carries no "
                f"type and the parameter list belongs to a declaration this walk "
                f"has not read — and the method-call rewriting runs before any "
                f"frame analysis exists, so a method it could not rewrite "
                f"arrives still spelled `{method}` with no lifted name to look a "
                f"parameter list up by. A frame address in a bare-name call IS "
                f"followed into the callee's parameter at that position, in "
                f"every position and not only the first. Measured on the shape "
                f"that IS rewritten, which shows the rule is right: `w.emit(s)` "
                f"becomes `W_emit(w, s)`, whose FIRST parameter is the receiver, "
                f"so `s` is the method's second parameter — and it is followed "
                f"there too. What closes this is the method's declaration "
                f"reaching the analysis: a receiver whose type names the struct, "
                f"so the call can be rewritten and the parameter list read")
    return (head +
            f"This is a limit of the ANALYSIS and not a fact about the program: "
            f"the frame belongs to the function that created it, that function "
            f"is an ancestor of the callee — the address reached the callee "
            f"through an active call — so a read or a write through this "
            f"parameter would be in the right place, and the missing thing is "
            f"the declaration that says so. Nothing in this image is compiled "
            f"wrong without it: the word is refused rather than followed, so "
            f"the alternative is a program that builds, runs, and returns a "
            f"number the source never wrote")


def frame_holder_disagreement_refusal(callee: str, position, param,
                                      holder_structs, holder_spellings,
                                      plain_spellings) -> str:
    """One parameter reached with a frame address at one call site and with
    something else at another.  The measured wrong answer this replaces.

    The holder fixpoint makes a parameter a holder when a call site hands it a
    frame address, and it used to do that at the FIRST position with nothing
    said about the other call sites.  So `f` below compiles `x.a` as a frame
    read, and the call `f(2, 3)` arrives with `x = 2`:

    ```
    struct R: var a: Int; var b: Int
    def f(x: Int, y: Int) -> Int: return x.a
    def main(n: Int) -> Int:
        var r = R(); r.a = 7; r.b = 8
        return f(r, 1) + f(2, 3)
    ```

    **Measured on both architectures, with nothing lifted: it builds, runs, and
    dies with SIGSEGV (exit 139)** — the word 2 is not a frame address and
    `x.a` loads eight bytes from wherever 2 points.  This is a use-after-free's
    sibling, and it is in the shipped tree, at the FIRST position, before this
    change existed: the rule the family was written for was never the thing
    that was wrong.

    So a parameter's being a holder is a property of the WHOLE IMAGE, not of
    one call site, and this refusal is what makes that visible.

    Phrased from BOTH sides and naming both, because either call site can be
    the one the reader is standing at, and a message that names the wrong one of
    the pair is the same defect as a message that names the wrong reason: it
    sends the reader to a call that is fine.  The spellings are the source's
    own, so the pair is visible without re-running anything.
    """
    who = _who(holder_structs)
    return (f"{callee}() takes a {who} receiver at argument {position} — "
            f"{param!r} — at {' and '.join(holder_spellings)} here, and "
            f"something that is not a frame address at "
            f"{' and '.join(plain_spellings)}. One parameter, two kinds of "
            f"value: {callee}() is compiled with {param!r} as a frame holder, "
            f"so a field read through it is a load at `base + 8k` — and at the "
            f"other call site there is no frame there at all. Measured on both "
            f"architectures with nothing lifted: the two-call-site shape builds, "
f"runs, and dies with SIGSEGV (exit 139). Give {param!r} one kind "
             f"of value at every call site — pass the frame address everywhere, "
             f"or nowhere")




# ── The cross-image half: a frame address handed to an IMPORTED function ─────
#
# `frame_holder_disagreement_refusal` above is the same disagreement decided
# from ONE image: every call site of the parameter is visible, so "one kind of
# value at every call site" is a checkable rule. Across a module boundary the
# other side's call sites are not in this image at all — they are in a dylib
# this build linked and then cannot read — so the same question needs a
# different piece of evidence, and that is what the dylib MANIFEST now carries.
#
# `_dylib_frame_contracts` publishes, for every exported function, which of its
# parameters its own compilation made frame holders and of which struct. That
# is a fact about a compilation this process did not perform, so it cannot be
# re-derived here; publishing it is the only honest way for a consumer to ask.
# The three refusals below are the answers that can come back, and they are
# three because "the contract says no" is not one fact:
#
#   * the contract says the parameter IS a frame holder, of a DIFFERENT struct
#     than the argument here — a real disagreement, and the worst of the three,
#     because both sides are now certain and they differ;
#   * the contract says the parameter is NOT a frame holder — a real
#     disagreement of the other kind, and the one that used to be invisible;
#   * the contract says nothing — a limit of the ANALYSIS again, and the only
#     one of the three that is not a statement about the program.
#
# All three keep the clause `which is a name with no definition in hand`, for
# the reason `frame_undefined_callee_refusal`'s docstring gives: two taxonomies
# key on that substring, and it is what keeps this family counted as one.


def cross_image_frame_disagreement_refusal(
        callee: str, position, contract_struct, argument_structs,
        argument_spelling) -> str:
    """The callee's own manifest says the parameter in `position` is a frame
    holder — of a struct other than the one handed to it here.

    Both sides are now certain and they disagree, which is what makes this the
    worst of the three cross-image answers: nothing here is missing, and the
    program is wrong rather than unknown.  `base + 8k` means slot 0 for one
    struct and some other field for the other, so the callee would read — or
    write — the caller's object through ITS OWN field list.

    Measured on this tree, with the contract published and the name comparison
    REMOVED — `resolve_frame_parameter_contract` returning `(True, None)` with no
    lookup, which is the one line of this construct that has to be right for
    this refusal to be worth anything.  The two modules differ only in the order
    their structs declare their fields (`Q(v, pad)` against `P(pad, v)`), which
    is exactly the disagreement `model.struct_frame_slot_candidates` documents
    and the reason layouts are compared by NAME rather than by count: the
    program builds, runs, exits 0, and returns **213** where CPython says 312,
    because `Q.v` is slot 0 and the caller's slot 0 is `P.pad`.
    """
    return (
        f"a {contract_struct} receiver is passed to {callee}() at argument "
        f"position {position}, and {callee}'s own manifest says the parameter "
        f"in that position is a frame holder of {contract_struct}: the module that "
        f"defines {callee}() compiled it that way, so a field read through it "
        f"is a load at `base + 8k` for {contract_struct}'s field list. This "
        f"call hands it {argument_spelling}, whose frame is "
        f"{_who(argument_structs)}. One struct's address read as another's "
        f"fields is a wrong answer rather than a failure, and it is why the "
        f"contract is compared rather than believed. Give the parameter the "
        f"struct the frame actually has, or pass {contract_struct} here")


def cross_image_plain_parameter_refusal(
        callee: str, position, argument_structs,
        argument_spelling) -> str:
    """The callee's own manifest says the parameter in `position` is an
    ordinary word.

    The inverse of the refusal above, and the one that was invisible before the
    manifest carried the contract: nothing in this image says the parameter is
    a holder, `known` and `all_holders` both lack the callee, and the old
    answer was "this pass cannot know".  Now it can — and what it finds is that
    the parameter is compiled as a plain word, so a frame address arriving in
    it is a number the callee will read as a value and then dereference.

    This is `frame_holder_disagreement_refusal` across an image boundary, and
    the same consequence, MEASURED on this tree rather than inherited: the
    identical program with the call in ONE file builds and runs, and returns
    the FRAME'S OWN ADDRESS added to the callee's other operand — 42 and 58 on
    two consecutive runs of the same binary on arm64, 250 on x86-64, because
    the low byte of a stack address is not a constant. So the single-file shape
    is not a crash either; it is a wrong answer that MOVES, which is the harder
    of the two to notice and the reason the word has to be refused rather than
    followed.

    (CPython rejects the shape outright — `P + int` is a `TypeError` — so
    there is no "right answer" to compare against here, and the claim being
    made is only that the backend must not invent a number at all.)
    """
    who = _who(argument_structs)
    return (
        f"a {who} receiver is passed to {callee}() at argument position "
        f"{position}, and {callee}'s own manifest says the parameter in that "
        f"position is an ordinary word, NOT a frame holder: nothing in "
        f"{callee}'s module ever hands it an address, so it was compiled to "
        f"read the word as a value. Handing it {argument_spelling} puts a frame "
        f"address where {callee}() expects a value, so {callee}() computes on "
        f"the ADDRESS — measured on this tree, the same program with the call "
        f"in ONE file builds, runs, and returns the frame's own address added "
        f"to the other operand: 42 and 58 on two consecutive runs of the same "
        f"arm64 binary, 250 on x86-64, where CPython rejects the shape "
        f"outright. A wrong answer that moves between runs is why the word is "
        f"refused rather than followed. Pass the field the callee reads "
        f"({argument_spelling}.a), or give the parameter a declared struct type "
        f"so both sides agree it is a frame")


def cross_image_contract_absent_refusal(callee: str, position,
                                        argument_structs,
                                        argument_spelling, why_absent) -> str:
    """No contract for this callee in any manifest on the link line.

    A limit of the ANALYSIS, and the only cross-image answer that is not a
    statement about the program — so it says so, and names the reason the
    contract is missing rather than asserting a mechanism that is not
    operating.  `why_absent` is which of the four it is:

      * `not-exported` — the callee is in the export table but the contract is
        shorter than the argument index, so this argument lands on no
        parameter.  Usually an arity or a naming disagreement, which the link
        audit will say about separately.
      * `not-a-callee` — the library carries no per-parameter contract (built
        before the field existed, or written by something that does not), or has
        a contract with no entry for this position.
      * `no-manifest` — no manifest on this image's link line mentions the
        callee at all, so the question cannot even be asked of it.

    `why_absent` is one of `CONTRACT_ABSENT_REASONS`' sentences, and that
    constant is the enumeration of them; there is no fourth and none is
    unreachable, which is why the list lives in one place rather than at three
    call sites.
    """
    return (
        f"a {_who(argument_structs)} receiver is passed to {callee}() at "
        f"argument position {position}, and {callee} is compiled into another "
        f"module, so whether ITS analysis made the parameter in that position "
        f"a frame holder is a "
        f"fact about that module's compilation. Nothing on this image's link "
        f"line settles it: {why_absent}. This is a limit of the ANALYSIS and "
        f"not a fact about the program — the frame belongs to the function "
        f"that created it, that function is an ancestor of the callee, so a "
        f"read or a write through the parameter would be in the right place. "
        f"The word is refused rather than followed, because following it "
        f"without the contract is a program that builds, runs, and returns a "
        f"number the source never wrote. "
        f"test_refusal_taxonomy.py::_no_def_callee_arm_checks records the "
        f"per-arm measurement")


# The THREE reasons a contract can be missing, as SENTENCES. A named constant
# each rather than a bare string at the one call site, so the three are
# enumerable — a reader can see the whole set of "why not" answers at once —
# and every one of them is emitted by `resolve_frame_parameter_contract` below.
#
# Three and not four. A fourth — "two libraries on the line publish a contract
# for it and they disagree" — was drafted here and deleted, because it is not a
# thing that can happen: `dylib_export_lookup` resolves a bare callee through
# the flat `by_name` table with `setdefault` in LINK ORDER, so two libraries
# exporting the same name is decided, and it is decided the same way the emitted
# call binds. Publishing a reason nothing can reach would be a fourth "why not"
# a reader could look for and never find, which is the defect this whole family
# of messages exists to stop.
CONTRACT_ABSENT_REASONS = {
    "not-exported": (
        f"the manifest for the module it came from does not list it as an "
        f"export, so its compilation never published a contract for it"),
    "not-a-callee": (
        f"the library it resolves to carries no per-parameter contract — "
        f"either built before the manifest carried one, written by something "
        f"that does not, or holding a contract with no entry for this "
        f"argument's position"),
    "no-manifest": (
        f"no manifest on this image's link line mentions it, so the question "
        f"cannot be asked of anything"),
}


def resolve_frame_parameter_contract(candidates, position, argument_structs,
                                    argument_spelling, callee: str):
    """`(follow, refusal)` for a frame address reaching an imported callee.

    THE decision, and it is in this file beside the three refusal texts it
    prints, because it is a question about the LANGUAGE — what a frame address
    means to a callee compiled in another module — and because both the build
    pass and anything else that has to answer it must get one answer. The
    three refusal builders are its only outputs; there is no fourth path and no
    flag that says "decided but unsure".

    `candidates` is what the link line offers for this callee, and it is a LIST
    rather than a single entry so that "which library does this bind to" is
    visibly a question this function does NOT answer: the caller passes what
    the resolver that binds the CALL found, in link order, and this function
    reads element 0 — the same first-wins precedence `load_dylib_manifests`'
    `map` and `dylib_syms` use. Taking one here would be a second resolution
    that could pick a different library's `f` from the one the emitted call
    binds, which is the silently-wrong binding the module-identity mechanism
    exists to prevent. An empty list is `no-manifest`.

    The list is a list and not a single entry for the same reason, and it is why
    there is no "ambiguous" answer in `CONTRACT_ABSENT_REASONS`: the ambiguity
    is settled by that precedence before this function is called, which is why it
    is not a state this function can be in.

    `argument_structs` is the SET of struct NAMES the caller's own argument is
    a frame of, and it is compared against the contract's names rather than
    against a struct object: the two sides of the boundary are different
    compilations of different `StructDef` trees, so the only thing they can be
    compared on is the name the layout was derived from. That is enough, and it
    is what makes following the address sound — `base + 8k` means the same thing
    on both sides only because both computed it from the same field list, and
    the importer read that struct from the module's OWN source
    (`formal.imports.imported_struct_defs`), so it is the same
    `struct_field_names` over the same class body.

    `position` is the argument index. Out of range of the contract — a
    variadic tail, or a call whose arity the callee's export disagrees with —
    is `not-exported`, because "this argument lands on no parameter" is a fact
    about the export rather than about the contract.

    **Follow is only ever `True` when the contract says the parameter is a
    holder of one of the structs this image actually has.** That is the whole
    safety argument: a struct of the right NAME in a different module with a
    different field list is a real possibility on this path — nothing stops two
    modules each declaring a `Pair` — and comparing counts instead of names
    would follow it silently.

    An EMPTY `argument_structs` does not follow, and cannot: the caller cannot
    say what its own argument is a frame OF, so it cannot show the layouts
    agree, and following on no evidence is the outcome the contract exists to
    prevent.
    """
    if not candidates:
        return (False, cross_image_contract_absent_refusal(
            callee, position, argument_structs,
            argument_spelling, CONTRACT_ABSENT_REASONS["no-manifest"]))
    entry = candidates[0]
    contract = entry.get("frame_params")
    if contract is None:
        return (False, cross_image_contract_absent_refusal(
            callee, position, argument_structs,
            argument_spelling, CONTRACT_ABSENT_REASONS["not-a-callee"]))
    if position >= len(contract):
        return (False, cross_image_contract_absent_refusal(
            callee, position, argument_structs,
            argument_spelling, CONTRACT_ABSENT_REASONS["not-exported"]))
    holders = contract[position]
    if not holders or holders == ["one-word"]:
        # `None` is an ordinary word: the callee was compiled to read the slot
        # as a value, so a frame address arriving there is the disagreement
        # `frame_holder_disagreement_refusal` reports within one image, with the
        # same consequence. `["one-word"]` is a one-field struct, whose
        # receiver IS its field — the wrong CATEGORY rather than the wrong
        # layout, and the same refusal rather than a fourth sentence.
        return (False, cross_image_plain_parameter_refusal(
            callee, position, argument_structs,
            argument_spelling))
    mine = set(argument_structs or ())
    if not mine:
        return (False, cross_image_contract_absent_refusal(
            callee, position, argument_structs,
            argument_spelling, CONTRACT_ABSENT_REASONS["not-a-callee"]))
    if mine & set(holders):
        return (True, None)
    # Both sides are certain and they differ: the worst of the three, because
    # nothing is missing and the answer is wrong rather than unknown.
    return (False, cross_image_frame_disagreement_refusal(
        callee, position, ", ".join(holders),
        argument_structs, argument_spelling))


def exported_owned_blob(entry) -> dict:
    """The MODULE-OWNED BLOB contract one manifest export entry publishes.

    `{}` for an entry that publishes none, which is every export of every
    module that has no such convention — and that is the answer that has to be
    cheap and total, because this is asked about every call in the image.

    The second per-parameter contract a manifest can carry, beside
    `frame_params`: where that one says "parameter *i* is the ADDRESS of a frame
    of this struct", this one says "the value on this side of the boundary is a
    block whose words the EXPORTING module owns", and it names the layout (which
    word is the count, which is the first pointer) because the layout is what a
    refusal has to tell the reader and what makes the store unsafe.

    The declaration itself lives in `formal/imports.py`'s `HOST_OWNED_BLOBS`,
    and the reason it is declared rather than derived is that table's own
    comment: `str_alloc` returns a `malloc`'d block too, and the caller owns
    every word of THAT one.  What separates the two is who frees the words, and
    a callee's own body does not say — `listdir` fills its block in a helper
    and the release that walks it is a different export.
    """
    if not isinstance(entry, dict):
        return {}
    contract = entry.get("owned_blob")
    return contract if isinstance(contract, dict) else {}


def owned_blob_store_refusal(spelling: str, name: str, callee: str,
                             owner: str, contract: dict) -> str:
    """Why writing into a word of a module-owned blob is refused.

    ARCH-FREE, asked from the shared pass (`formal/build.py`'s
    `check_imported_blob_stores`) because both backends lower the same store and
    a store one architecture refuses and the other performs is the outcome the
    contract mechanism exists to prevent.

    **The refusal is at the STORE and not at the release**, and the measured
    reason is the order the program runs in: `names[1] = 5` then
    `listdir_free(names)`.  Built silently on both architectures, and the abort
    is in the module's own `free` — exit 134, SIGABRT, with `before=2` printed
    and `freed` never printed.  So the store is accepted, the program runs, and
    the damage is done by a function the caller believes it is calling correctly.

    **The type cannot carry this**, which is why the contract exists at all: the
    blob's type is `Pointer[Int64]`, and a pointer permits any store.  That is
    also why the message does not stop at "read-only": it says WHICH word is the
    header and which are the pointers, names the release that walks them, and
    gives the two routes that do work — the module's accessors for reading, and
    `os._syscalls.str_alloc` for a buffer the caller does own.  A refusal that
    only said "that is not yours" sends the reader to the module's source, and
    the one fact they need is in a comment there.
    """
    count = contract.get("count_word", 0)
    base = contract.get("entry_base", 1)
    release = contract.get("release") or callee
    return (
        f"`{spelling}` writes into a blob {owner} OWNS rather than one you do: "
        f"word {count} of this blob is its entry COUNT and word `{base} + i` is "
        f"entry `i`'s `malloc`'d name, which `{release}` releases by "
        f"calling `free` on each of them. Overwriting one leaves that release "
        f"freeing a small integer — measured on both architectures, the build "
        f"is silent, the program prints its own answers and then dies in `free` "
        f"with SIGABRT (exit 134), after the release has already been handed a "
        f"blob whose count word still says how many entries there were. The type "
        f"cannot say any of this: the blob is a `Pointer[Int64]`, which permits "
        f"any store. Read it through the module's own accessors — "
        f"`{owner}.listdir_len` for the count, `{owner}.listdir_get` for entry "
        f"`i` — and if you need a buffer you can WRITE, that is a different "
        f"call: `os._syscalls.str_alloc(n)` returns raw `malloc`'d memory "
        f"with no header and no owner but you, which is the route to pre-size "
        f"and fill."
    )


def dylib_export_pointer_pointee(entry) -> str:
    """The pointee type a manifest export's `T *` result declares, or `''`.

    `''` for a result that is not a pointer, and `''` for the one pointer
    result this path ALREADY classifies from the signature — `char *`, whose
    subscript is a byte of the string it names. That exclusion is
    `dylib_export_return_kind` asked directly, rather than a second copy of its
    rule, so the two cannot answer differently about one export; it is what makes
    `os._syscalls.str_alloc`'s unannotated `var p = str_alloc(64)` subscriptable
    while `re.escape`'s is not.

    A `MojoList *` result is NOT excluded, and the reason is worth stating
    because it looks like an oversight: a container blob is classified from an
    ANNOTATION (`List[T]` and friends, `BLOB_TYPE_CTORS`), so an unannotated
    binding of one has no container kind either, and a subscript through a word
    with no kind is the case this refusal is about. No host module in this tree
    declares one today, so the answer is a choice made from the model rather than
    from a measurement — the conservative one, and the one a reader can undo with
    an annotation.

    `uint8_t *` is the case that reaches it, and it is reached because
    `re.escape` is declared `-> Pointer[UInt8]`, `re.sub` likewise, and
    `hashlib.sigma_table` returns a byte table. Nothing was reading that: a
    subscript through the unannotated binding of one read the LOCAL's own
    storage and printed 0 where the buffer held 65 (`re.escape`), and
    `hashlib.sigma_table()[0]` printed 185207048 — a number assembled out of
    whatever the slot held. See `unclassified_import_pointer_refusal`.
    """
    if not entry or dylib_export_return_kind(entry) is not None:
        return ""
    ret = signature_return_type(entry.get("signature") or "")
    base = ret.replace("const", "").strip()
    return base[:-1].strip() if base.endswith("*") else ""


def unclassified_import_pointer_refusal(spelling: str, name: str, callee: str,
                                         module: str, pointee: str) -> str:
    """Why a subscript through an untyped cross-image pointer is refused.

    ARCH-FREE, asked from the shared pass (`formal/build.py`'s
    `check_subscript_through_an_unclassified_import`) beside
    `owned_blob_store_refusal` and for the same reason: both backends lower the
    same subscript, and a value one architecture refuses and the other computes
    is the outcome this tree treats as worse than either answer.

    **A number that looks plausible and is not the program's is the outcome
    this exists to prevent**, and the measurement is what makes it a refusal
    rather than a limitation: `re.escape` is declared `-> Pointer[UInt8]`, so its
    manifest signature says `uint8_t *`, and with an unannotated local
    `r[0]` read the LOCAL's own storage — 0 where the buffer holds 65, while
    `printf("%s", r)` printed `AB` correctly in the same program, so the reader
    has one answer that looks right and one that does not. `r[0] = 90` was worse
    still: it built, ran, exited 0, and wrote to a slot nothing reads, so a
    program that fills a caller-owned buffer through an untyped binding appears
    to work and computes nothing. `hashlib.sigma_table()[0]` printed 185207048.

    The repair is named and it is one line: say what the name holds. That is the
    same answer as for an unclassified parameter, and for the same reason — an
    absent answer IS the answer, and this path has no inference that reads a
    pointee out of another image's signature (it has no allocation model, so a
    width it guessed would be a guess about the callee's own locals).
    """
    hint = f"Pointer[{pointee}]" if pointee else "Pointer[Int64]"
    return (
        f"{spelling} subscripts `{name}`, whose value came from `{callee}` in "
        f"{module} \u2014 and that export\u0027s own declaration is a POINTER "
        f"(`{pointee} *`), which this path does not carry into an unannotated "
        f"local. A cross-image result is classified from its manifest signature "
        f"only when that says `char *` (a string, whose subscript is a byte of "
        f"it) or a container blob; every other pointer arrives as a plain WORD "
        f"with no layout, and a subscript through a plain word computes "
        f"`[word + 8i]` from the local\u0027s own storage \u2014 measured, both "
        f"architectures: `re.escape(\"AB\")` bound without a type gave `r[0]` = "
        f"0 where the buffer holds 65, `r[0] = 90` wrote to a slot nothing reads, "
        f"and `hashlib.sigma_table()[0]` printed 185207048. Say what the name "
        f"holds \u2014 `var {name}: {hint} = ...` \u2014 which is the same program "
        f"with an answer: a subscript through an annotated `Pointer` reads the "
        f"buffer, and one through a word cannot."
    )


def frame_declared_parameter_refusal(callee, position, param, struct_name,
                                    shape, sites) -> str:
    """A parameter classified from its DECLARED type, reached with the wrong
    shape at a call site.

    The sibling of `frame_holder_disagreement_refusal`, and it exists because
    that one cannot say this.  Its rule is "the call sites must agree with each
    other", which is enough while a parameter is a holder only because some
    call site handed it a frame: there is then at least one frame-side site to
    compare the others against.  A parameter classified by its DECLARED TYPE
    has no such site — that is the whole construct, `Slice.__eq__(self, other:
    Self)` in a module where nothing calls it — so a program that does call it
    with a plain word leaves the frame-side list empty, and "empty" read as
    agreement compiles a field read into `ldr [word, #8k]`.

    So the rule here is "every call site agrees with the DECLARATION", and the
    declaration is named because it is the evidence being contradicted: the
    reader is looking at a call site, and what tells them what the callee was
    compiled to expect is the parameter's own annotation.  `shape` says what the
    declaration compiled it to, in the words of the two cases, so the reader
    does not have to know which of the two rules applied to see the mismatch.

    Each site is spelled as the source spells it and paired with what this image
    can see it is, because "the wrong shape" is true of `f(g())` and of `f(r2)`
    where `r2` is some other struct's frame, and those want different repairs.
    The repair for both is the same shape — pass a value of the declared type at
    every call site — and the message says so last, after the reader can see
    which sites are the ones to look at.
    """
    pairs = "; ".join(f"{spelling} passes {why}" for spelling, why in sites)
    return (f"{callee}() declares {param!r} as {struct_name}, so it is compiled "
            f"with {param!r} as {shape} — and every call site in this image hands "
            f"it something else: {pairs}. Reading a field through a word that is "
            f"not the thing the declaration promised is a load from wherever that "
            f"word points, which is a wrong answer rather than a failure, so it "
            f"is refused rather than emitted. Call {callee}() on a "
            f"{struct_name} value at every call site — a local built from "
            f"{struct_name}(), or a field declared as {struct_name} — which is "
            f"the same program with a value this path can place")


def frame_return_refusal(owner, received: bool, struct_names) -> str:
    """A frame address RETURNED, in a function the convention does not cover.

    **The convention covers the ordinary case and this is what is left of it.**
    `formal/build.py`'s `_frame_return_status` decides, for the whole image,
    whether a function returns a frame; when it does, the callee copies the
    block into one the caller reserved (`struct_returned_frame_sites`,
    `returned_frame_convention_refusal`) and this message is not reached. The
    residual is a return of a name the analysis holds as a frame but could not
    decide the width of — a candidate set with no struct in it, so the copy has
    no `n` — and it is kept rather than deleted because that is a
    representation the guard should refuse and not compute, and because the
    sweep's family classifier (`tools/formal_sweep.py`) and
    `test_refusal_taxonomy.py` both key on this text.

    `owner` is the struct whose method the returning function is, or None for a
    plain function; `received` says the frame was NOT built here.

    "Returned from the function that created it" is true for a frame a function
    built and false for one that arrived as a PARAMETER, and the second is the
    larger half of this family: the holder fixpoint makes a callee's parameter a
    holder — in every position since the position rule was split out of this
    one — so `def fwd(r): return r` in a program whose object was made by `main`
    was reported as a return from the creator. The refusal was right, the
    sentence named the wrong function, and it sent the reader to look at `fwd`
    for a construction that is in `main`.

    Which is why nothing here says "first parameter" any more.  It said that
    because the fixpoint only followed index 0, and it became false the moment
    the fixpoint followed every position: `def stash(x, y): return y` receives
    the frame as its SECOND parameter, and a message naming the first one
    points the reader at a parameter the source does not use.

    The hazard is measured, not asserted, and it is a use-after-free rather
    than a wrong number in the shape that matters: with the creator one frame
    deeper, `def stash(x, y): return y` called as `outer(1)`, the program built,
    ran, and returned **10 on arm64 and 0 on x86-64** where the source says 7 —
    the bytes the address names had been reused, and the two architectures
    disagreed about what was in them."""

    who = ", ".join(struct_names) if struct_names else "this struct"
    tail = (f" Returning the address hands the caller a pointer into a frame "
            f"whose lifetime this pass cannot follow, and the failure is a "
            f"wrong number rather than a crash: the bytes get reused and the "
            f"read returns whatever is in them now. Measured with this check "
            f"removed: the same shape returns 10 on arm64 and 0 on x86-64 "
            f"where the source says 7 — a use-after-free, and a two-backend "
            f"disagreement about what the reused bytes held. "
            f"Return a field (`return self.n`) or a copy of the value, which "
            f"is the same program with a lifetime this analysis can see")
    if received and owner:
        return (f"a {who} receiver is returned from a method of {owner}, which "
                f"did not create the frame — it received the address as its "
                f"receiver, so the function that DID create it is "
                f"somewhere up the call chain and nothing here establishes that "
                f"its frame is still there." + tail)
    if received:
        return (f"a {who} receiver is returned from a function that did not "
                f"create it: the address arrived as one of its parameters, so "
                f"the function that built the frame is this function's CALLER "
                f"or an ancestor of it, and "
                f"nothing here establishes that the caller's frame is still "
                f"there when the caller reads the value this return produces." +
                tail)
    return (f"a {who} receiver is returned from the function that created it "
            f"on this path: the receiver of a multi-field struct is the ADDRESS "
            f"of a frame of 8-byte slots that belongs to the function which "
            f"created it, and that frame is reclaimed when the function "
            f"returns, so the address the caller would dereference names "
            f"reclaimed stack." + tail + ". "
            f"FORMAL_wide_receiver_by_reference.md (deleted; fixed) records the design and "
            f"what is still open about it")




# ── The gimple backend's C runtime, by name ────────────────────────────────
#
# The OTHER backend in this repository — the one that generates GIMPLE for clang
# — has a C runtime: runtime/fire_runtime.c, embedded by every image it builds,
# with a header (runtime/fire_runtime.h, runtime/fire_sqlite3.h) that spells its
# ABI. That ABI has a naming convention of its own: every entry point is
# `mojo_<thing>`, so a program written against it calls `mojo_sqlite3_open(...)`,
# `mojo_list_len(xs)` and `mojo_print(s)` by those bare names, and
# gimple_codegen.py maps the source's own `print` onto `mojo_print` (line 617).
#
# None of that exists on a formal target. A formal image is freestanding: it
# embeds no interpreter, and its values are one 64-bit word proved by a Lean
# model. So a call to one of these names is not an external dependency to be
# satisfied — it is a call into a library that is not part of THIS target, and
# the default lowering of an unknown bare name is a BL against a symbol spelled
# the way the source spelled it. That is the worst failure a compiler has: the
# build reports success and the program dies in the loader with "Symbol not
# found".
#
# The library is no longer simply absent. `runtime_dylib()`
# (build_stdlib_dylib.py) builds a per-architecture `-dynamiclib` exporting the
# whole `mojo_*` namespace, and `formal/build.py`'s `runtime_library` puts it on
# a formal link line when the program names an entry point of it that a formal
# image could make. So the second half of the rule below — the symbol has to be
# on the link line — is now a fact about the image rather than a standing
# impossibility, and the namespace is refused only for what genuinely cannot be
# answered: a call whose types are not all one word, and a name no library here
# can bind.
#
# So the namespace is REFUSED here, before the extern path can reach it. The
# refusal is no longer a test of the NAME. It was one because the shape was not
# available: this module is deliberately leaf-most (`os` and `fire_compiler` and
# nothing else, so the two formal architectures cannot drift), and the only
# thing that could have told a `mojo_list_len` from a `mojo_print` was the
# header, which is not something this module reads. It reads it now, through a
# lazy import of the one scanner that already owns it
# (`reflect.collect_runtime_exports_h`, which FORMAL.md phase 0 built), and the
# decision is made on the TYPES that header declares. What is left of the prefix
# is the conservative fallback for a name no header declares, and a name that no
# header declares has no signature here to check.
#
# The repository also has ordinary Mojo functions and ordinary local variables
# whose names begin `mojo_` (scripts/stage2_mojo_interpreter.mojo defines
# `mojo_to_python` and takes a parameter called `mojo_file`), so a rule keyed on
# the spelling still had to be reached only after the caller established that
# the name is NOT a function of this module and NOT an export of a dylib the
# program explicitly linked. That precondition is unchanged and is still the
# caller's to establish.
GIMPLE_RUNTIME_PREFIX = "mojo_"



# ── The runtime ABI, and what a formal image can do with it ───────────────
#
# What "answerable on a formal image" means, and why it is not the RETURN type
# alone. A formal image is freestanding: it links libSystem and nothing else, it
# embeds no C runtime, and its values are ONE 64-bit word (see the aggregate
# layout note at the top of this file). So a call to a real runtime entry point
# is answerable exactly when every value that crosses the call boundary is a
# single word — the return value AND every argument. The two positions are not
# symmetric, and reading only the return type is the trap this rule exists to
# avoid: `mojo_list_get_int(MojoList *, int64_t) -> int64_t` returns a word and
# is still not callable, because the box is in the ARGUMENT. The runtime's
# `MojoList` is `{data, len, cap}` on the heap (runtime/fire_runtime.h:257) and
# a list here is a frame blob whose first word IS its count (BLOB_HEADER_BYTES,
# above). Reading offset 0 of one as the other is a plausible-looking wrong
# number rather than a crash, which is exactly why no amount of linking answers
# it.
#
# A POINTER is one word as an ADDRESS, and that is the whole of what makes a
# `void *` a legitimate argument: this path can carry the handle as a word and
# hand it straight back to the library that made it, never interpreting it. It
# is not one word as a RETURN value, because there the CALLER is handed the
# address and may read what is behind it — and the header does not say what is
# behind it. `void *mojo_sqlite3_open` and `void *mojo_sqlite3_query` have the
# SAME declaration type; one is a database handle the program passes on to
# `mojo_sqlite3_close`, the other is a `MojoList *` of rows it iterates. Nothing
# in the declaration distinguishes them, so the conservative reading is the only
# one available and it is also the safe one: a caller of `mojo_sqlite3_query`
# that treated the result as a word would read offset 0 of a box as a count.
# `char *` is the one pointer that IS a value on this path, because a string is
# an interned `char *` with no header (the aggregate layout note again), so a
# `char *` return is a word like any other and `mojo_c_getenv` is callable.
#
# This is the generalisation of the `GIMPLE_LIST_PREFIX` special case that
# stood here before, and that constant is gone: a hand-kept list of prefixes is
# a list that rots, and the shape answers the same question for all 897 entry
# points the headers declare rather than for the 40-odd names one prefix
# happened to cover.

def _runtime_header_dir() -> str:
    # This file lives at formal/model/__init__.py since the package split, so
    # the repo root is three levels up, not two. Two levels named formal/runtime,
    # which does not exist, and runtime_abi() silently returned an empty table.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "runtime")


_RUNTIME_ABI = None      # name -> entry; built once, see runtime_abi()


def runtime_abi() -> dict:
    """Every entry point the runtime headers declare, with its types.

    One table, and it is read out of the headers rather than written down here:
    `reflect.collect_runtime_exports_h` is the scanner that already exists (and
    that FORMAL.md phase 0's link audit made complete), so a second hand-kept
    list of names or signatures is exactly the rot this replaces. Every `.h` in
    runtime/ is scanned, sorted, so a header added later is picked up without
    editing anything.

    `reflect` is imported LAZILY and inside the function, deliberately. It
    imports `gimple_codegen` — the other backend — and this module is
    leaf-most on purpose so the two formal architectures cannot drift; a
    module-level edge would put the compiled backend in this module's import
    closure and undo that. `formal/build.py` takes the same lazy edge to the
    same module for the same reason (`_abi_symbol`, `_export_entries`).

    Each entry is a dict:
        name        the C symbol
        signature   display form, as the header spells it
        ret         return type, pointer stars included
        params      the parameter list, as written
        word        True when every type crossing the boundary is one word
        boxes       [(where, spelling, base, depth)] for the types that are not
    """
    global _RUNTIME_ABI
    if _RUNTIME_ABI is not None:
        return _RUNTIME_ABI
    import reflect          # lazy — see the docstring
    table = {}
    hdr_dir = _runtime_header_dir()
    try:
        headers = sorted(h for h in os.listdir(hdr_dir) if h.endswith('.h'))
    except OSError:
        headers = []
    for h in headers:
        for e in reflect.collect_runtime_exports_h(os.path.join(hdr_dir, h)):
            # First header wins, so the order is decided by a sorted list and
            # not by which file the scanner happened to reach first.
            table.setdefault(e['name'], _runtime_abi_entry(e))
    _RUNTIME_ABI = table
    return table


def _runtime_abi_entry(scan: dict) -> dict:
    """One scanned prototype, plus the word/box verdict its types imply."""
    boxes = []
    rbase, rdepth = _parse_ctype(scan['ret'])
    if not _ctype_is_word(rbase, rdepth, in_return=True):
        boxes.append(('its return value', scan['ret'], rbase, rdepth))
    params = _split_params(scan['params'])
    if params is None:
        # A `...`, or a function-pointer parameter: the arity or the shape of
        # an argument is not in the declaration, so nothing can be decided.
        boxes.append(('its argument list', scan['params'], '', 0))
    else:
        for i, p in enumerate(params, 1):
            base, depth = _parse_ctype(p, is_param=True)
            if not _ctype_is_word(base, depth, in_return=False):
                ordinal = ('its first argument' if i == 1 else
                           f"its argument {i}")
                boxes.append((ordinal, p, base, depth))
    return {'name': scan['name'], 'signature': scan['signature'],
            'ret': scan['ret'], 'params': scan['params'],
            'word': not boxes, 'boxes': boxes,
            # A `void` RETURN is a different fact from an un-word-shaped one, and
            # it is recorded beside `word` rather than inside it because the two
            # rules answer different questions. `word` asks "can a formal image
            # make this CALL at all", and a `void` call can be made — the effects
            # happen and nothing is read back. `returns_void` asks "does this call
            # produce a value to bind", and the answer is no.
            #
            # `'void'` is in `_WORD_SCALARS`, and it is there for a POINTER's
            # sake: `MojoFileHandle` and `mojo_coro_handle` are both `typedef
            # void*`, and reading either as the bare spelling `void` is what made
            # nine entry points look like by-value aggregates. Carrying `void`
            # into `_WORD_SCALARS` therefore also made a `void`-RETURNING entry
            # point word-shaped, which is right for the call and wrong for the
            # result, and the 68 such names could each be bound to whatever
            # happened to be in the return register. Measured, both
            # architectures, `a = mojo_async_init(); b = mojo_async_schedule_
            # ready(0); c = mojo_async_shutdown(); printf("%d %d %d", a, b, c)`:
            #
            #     arm64   a=-1          b=13582400   c=-1
            #     x86-64  a=0           b=20463624   c=0
            #
            # and neither run crashed, so nothing downstream could tell. See
            # `gimple_runtime_void_result_refusal` and `check_runtime_void_results`.
            'returns_void': scan['ret'].strip() == 'void'}


# C's own scalar vocabulary — NOT this runtime's entry points, and not a list of
# types this backend has been asked about. It is the set of type spellings a
# value IS on this path, and everything outside it is treated as a box. That
# direction is the point: a type this rule has never heard of is refused,
# because treating an unknown spelling as a word is the over-approximation that
# miscompiles, while refusing one that would have worked only costs a call.
#
# The set is deliberately NOT "one machine word" in C's sense. The question
# `_ctype_is_word` answers is "can a formal value be this", and a formal value
# is a 64-bit word holding an INTEGER, so the floating-point scalars are not
# values here at all: a float literal is truncated toward zero on the way in
# (formal/types.py), which is the right answer for arithmetic on this path and
# exactly the wrong one for handing a word to a callee that will read it as a
# `double`.
#
# That distinction was latent while every `mojo_*` call was refused, and became
# a real silent wrong answer the moment the runtime library reached a formal
# link line (formal/build.py's `runtime_library`). Measured, on
# `x = 2.5; return mojo_div_double(x, x)`: the image built, ran, and returned
# 2 — the integer 2.5 truncated, in X0, read by the callee as the bit pattern of
# a double — where the answer is 1. `mojo_div_double` and 8 other float-typed
# entry points are refused for this and named as floats by `_box_why`.
#
# Note what is NOT here either: `long double`, which is 16 bytes on x86-64 and
# is the one C scalar that is not even a word.
_WORD_SCALARS = frozenset({
    'void', 'bool', '_Bool', 'char', 'short', 'int', 'long', 'long long',
    'char16_t', 'char32_t', 'wchar_t',
    'size_t', 'ptrdiff_t', 'intptr_t', 'uintptr_t', 'intmax_t', 'uintmax_t',
    'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
    'int_least8_t', 'int_least16_t', 'int_least32_t', 'int_least64_t',
    'uint_least8_t', 'uint_least16_t', 'uint_least32_t', 'uint_least64_t',
    'int_fast8_t', 'int_fast16_t', 'int_fast32_t', 'int_fast64_t',
    'uint_fast8_t', 'uint_fast16_t', 'uint_fast32_t', 'uint_fast64_t',
})

# The floating-point scalars, kept as their own set rather than being absent,
# because the refusal for one has to NAME the mismatch. A generic "not a value
# on this path" would be true and useless; `mojo_div_double` is refused because
# the word this path can hand it is not a `double`, and that is the sentence a
# reader needs. Same membership discipline as `_WORD_SCALARS`: an unrecognised
# spelling is not in here either, so it falls to the aggregate message, which
# is the conservative one.
_FLOAT_SCALARS = frozenset({'float', 'double', 'long double'})

# Leading type keywords, dropped before the base type is read. `signed` and
# `unsigned` are here because signedness does not change the size, and this
# function is only asked "is this one word".
_CTYPE_QUALIFIERS = ('const ', 'volatile ', 'restrict ', 'struct ', 'union ',
                     'enum ', 'signed ', 'unsigned ')


def _parse_ctype(decl: str, is_param: bool = False) -> tuple:
    """(base, pointer depth) for a C type spelling, with whitespace collapsed,
    with the headers' own `typedef` ALIASES resolved.

    Two steps, and they are separate functions because they answer different
    questions: `_ctype_words` reads the spelling, this one asks what the type
    IS. An alias is a second spelling of a type the rule already knows, so a
    prototype written through one is a prototype the rule must be able to read
    — see `_runtime_typedefs` for what was measured when it could not.

    `is_param` says whether the spelling still carries its DECLARATOR NAME,
    because it does in a parameter list and does not in a return type:
    `void *db` is a `void *` with a name, `void *` is not. Getting that backwards
    makes every parameter a type called `void db`, which nothing recognises as a
    scalar — and a rule that refuses all 897 entry points for that reason looks
    exactly like a rule that has measured them all and found none reachable.

    The result is the RESOLVED type, which is what every reader of it wants:
    `_ctype_is_word` asks whether a value can be this, `_box_why` names the
    mismatch, and `test_formal_runtime_link.py`'s ceiling-3 count asks whether
    this entry point takes a `void *`. A resolved base answers all three; a
    spelling answers none of them, because an alias is a word, not a type."""
    return _resolve_typedef(*_ctype_words(decl, is_param))


def _ctype_words(decl: str, is_param: bool = False) -> tuple:
    """(base, pointer depth) for a C type SPELLING, aliases NOT resolved.

    Deliberately not a regex: this module imports `os` and `fire_compiler` and
    nothing else, and a type declaration is not worth a third import. The
    grammar is a base type and a run of `*`, which is all a prototype's types
    are.

    The base type is then the LAST word: everything before it is a qualifier
    (`const`), a sign, or a width modifier, none of which changes the size.
    `const char *` is a `char`, `unsigned int` is an `int`, `long long` is a
    `long`."""
    s = ' '.join(decl.split())
    depth = s.count('*')
    s = ' '.join(s.replace('*', ' ').split())
    if is_param:
        head, _, last = s.rpartition(' ')
        s = head or ''
    changed = True
    while changed:
        changed = False
        for q in _CTYPE_QUALIFIERS:
            if s.startswith(q):
                s = s[len(q):]
                changed = True
    return s.rpartition(' ')[2], depth


_RUNTIME_TYPEDEFS = None    # alias -> (base, extra depth); see runtime_typedefs()


def _runtime_typedefs() -> dict:
    """The runtime headers' scalar and pointer `typedef` ALIASES, resolved once.

    **This is the fix for a refusal whose stated reason was false.** The
    headers alias a handful of their types — `typedef void* MojoFileHandle;`,
    `typedef void *mojo_coro_handle;`, `typedef char* mojo_string;` — and a
    prototype written through an alias says nothing about the type. Read
    without this table, `mojo_write(MojoFileHandle fh, char *data, int64_t
    len)` had a first argument of base type `MojoFileHandle`, which is in no
    scalar set, so `_ctype_is_word` refused the entry point and `_box_why` said
    its first argument "is a `MojoFileHandle`, which is a by-value aggregate,
    which is a struct in memory rather than a word". **It is a `void *`.** The
    same sentence was printed for `mojo_async_schedule_ready(mojo_coro_handle)`
    and four of its siblings, and it was false nine times over.

    Read the headers, do not remember them: `reflect`'s scanner is the one that
    already reads these files for the export table, and an alias list written
    out here would rot the moment a header renamed one — which is exactly what
    `_WORD_SCALARS` is for, a list of type SPELLINGS and not of names.

    Aliases to a struct/union/enum are deliberately absent (the scanner drops
    them): an aggregate is a box under every rule that reads these prototypes,
    so an unresolved aggregate spelling is already the right answer.
    """
    global _RUNTIME_TYPEDEFS
    if _RUNTIME_TYPEDEFS is not None:
        return _RUNTIME_TYPEDEFS
    import reflect          # lazy — see runtime_abi()'s docstring for why
    out = {}
    hdr_dir = _runtime_header_dir()
    try:
        headers = sorted(h for h in os.listdir(hdr_dir) if h.endswith('.h'))
    except OSError:
        headers = []
    for h in headers:
        for name, target in reflect.collect_runtime_typedefs_h(
                os.path.join(hdr_dir, h)).items():
            # First header wins, for the reason `runtime_abi` gives: the order
            # is decided by a sorted list and not by which file the scanner
            # reached first.
            if name not in out:
                out[name] = _ctype_words(target)
    _RUNTIME_TYPEDEFS = out
    return out


def _resolve_typedef(base: str, depth: int, _seen=frozenset()) -> tuple:
    """`base`, with the headers' aliases followed to the type they stand for.

    Depth ACCUMULATES rather than being replaced, which is the half that
    matters: `MojoFileHandle` is `void *`, so `MojoFileHandle *` is `void **` —
    a pointer to a pointer, which `_ctype_is_word` refuses in every position
    because the callee dereferences twice. Reading the alias as a word would
    have turned that refusal into a miscompile.

    `_seen` is C's own cycle rule (an alias cannot name itself) implemented
    defensively: a header is text, and this walk is cheap enough that being
    wrong about that costs a hang rather than a wrong answer.
    """
    table = _RUNTIME_TYPEDEFS if _RUNTIME_TYPEDEFS is not None \
        else _runtime_typedefs()
    while base in table and base not in _seen:
        target_base, target_depth = table[base]
        base, depth = target_base, depth + target_depth
        _seen = _seen | {base}
    return base, depth


def _ctype_is_word(base: str, depth: int, in_return: bool) -> bool:
    """True when a value of this type is one 64-bit word on a formal image.

    The two positions differ, and the difference is the whole rule — see the
    note above. A `MojoList *` is a perfectly good ARGUMENT to carry and an
    impossible thing to be HANDED, and no test of the type alone can tell those
    apart without this.

    The pointer cases are all depth-EXACT, and that is the third thing this
    rule has to get right. At depth 1 the callee is handed an address it may
    read; at depth 2 and above it is handed an address it will *dereference*,
    and this path has no way to name one: the only storage a formal image has
    is a frame blob, reclaimed when the frame returns, and there is no
    allocator. `char **` (an out-parameter, which the callee writes a string
    pointer through) and `int64_t *` are therefore refused, where before
    anything non-`void` at depth 1 was admitted because its base type happened
    to be a word. That admitted 3 entry points whose first act inside the
    callee is to scribble over a word the caller believes is a pointer.
    """
    if depth == 0:
        return base in _WORD_SCALARS
    if in_return:
        # The caller is handed this address and may read it. Only a string is
        # something this path has a value for.
        return depth == 1 and base == 'char'
    # An argument: the callee may read it, so the pointee has to be something
    # both sides agree on — a string, which is a value here because it is an
    # interned `char *` with no header, or `void`, an opaque handle handed
    # straight back to whoever made it.
    return depth == 1 and base in ('char', 'void')


def _split_params(params: str):
    """The parameter declarations of a prototype, or None if they are not all
    plain C types.

    None means "cannot be decided" — a `...` (the header does not say the arity)
    or a function-pointer parameter (a declaration in its own right, which no
    rule here reads). Both are refused rather than guessed at; `mojo_type(...)`
    and `mojo_re_sub_fn`'s callback are the live examples."""
    p = ' '.join(params.split())
    if not p or p == 'void':
        return []
    out, cur, depth = [], '', 0
    for ch in p:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur)
            cur = ''
        else:
            cur += ch
    out.append(cur)
    got = []
    for d in out:
        d = ' '.join(d.split())
        if d == '...':
            return None
        if not d or d == 'void':
            continue
        if '(' in d or ')' in d:
            return None
        got.append(d)
    return got


def runtime_abi_entry(name: str):
    """The header's declaration of `name`, or None if no header declares it."""
    return runtime_abi().get(name) if isinstance(name, str) else None


def is_gimple_runtime_builtin(name: str) -> bool:
    """True when `name` belongs to the gimple backend's C runtime.

    True for a call this target cannot bind, ASSUMING the caller has already
    established that the name is not a function of the module being compiled and
    not an export of a dylib the program linked. See the note above: a header
    that declares it is the first test, and the `mojo_` namespace is the
    conservative fallback for one that does not — a name with no declaration
    anywhere has no signature here to check, and is therefore not callable
    either."""
    if not isinstance(name, str):
        return False
    return name in runtime_abi() or name.startswith(GIMPLE_RUNTIME_PREFIX)


def gimple_runtime_callable(name: str, provided: bool = False) -> bool:
    """True when a formal image can make this call at all.

    FORMAL.md phase 2's rule, whole: every type crossing the call boundary is
    one word, AND the symbol is on the link line. The first half is this
    module's own decision from the header; the second is the caller's, because
    only the caller knows what the image links — hence the argument rather than
    a second guess at it here.

    A backend can ask this unconditionally for any extern call, and a name
    OUTSIDE the `mojo_*` namespace is always answered True, which is what the
    old `startswith` test amounted to. The namespace check is not redundant
    beside the table lookup: the headers also declare `input`,
    `string_strip`, `int64_t_basename` and `py_tokenize`, which are the C
    library and the compiler's own shims rather than the runtime's ABI, and
    refusing those would be this rule refusing code it never claimed to cover.
    """
    if not isinstance(name, str) or not name.startswith(GIMPLE_RUNTIME_PREFIX):
        return True
    entry = runtime_abi_entry(name)
    if entry is None:
        return False        # no declaration anywhere: no shape, so not callable
    return entry['word'] and provided


def gimple_runtime_void_result_refusal(name: str, signature: str = "") -> str:
    """Why a `void`-RETURNING runtime entry point cannot be a value.

    **A `void` call is a legal call and an illegal VALUE, and the two are
    different questions, which is why this is beside
    `gimple_runtime_callable` rather than inside it.** `gimple_runtime_callable`
    asks whether a formal image can make the call at all, and it must keep
    answering YES for these: `mojo_async_init()` as a statement of its own does
    the work the source wrote and reads nothing back, so refusing it would
    refuse a program that is correct. What cannot be right is `x =
    mojo_async_init()` — the callee writes nothing to the return register, so
    the read is whatever was there, and on this path that is a number the source
    never wrote.

    **The direction this moves is the same one the float rule moved and for the
    same reason.** `'float'`/`'double'` are not in `_WORD_SCALARS` because a
    value here holds an INTEGER and a callee would read an integer's bit pattern
    as a `double` (`_box_why`'s float arm quotes the measurement: `2.5` returned
    `2`). `void` is a member of `_WORD_SCALARS` for a POINTER's sake —
    `MojoFileHandle` and `mojo_coro_handle` are `typedef void*` — and carrying
    that membership into RETURN position is the same mistake one step further
    out: the word is real, the value behind it is not.

    `formal/imports.py`'s own `HOST_UNREACHABLE` row records the same reasoning
    about a neighbouring shape ("a name LEAVES this set by being WRITTEN"), and
    the difference in direction is what makes this a refusal rather than a
    deletion: taking `void` out of `_WORD_SCALARS` outright would break the
    `void *` spellings that section 0.3 of
    `bugs/FORMAL_runtime_library_on_the_link_line.md` landed, so the membership
    stays and this rule reads `returns_void` instead.

    **It is asked about the POSITION, not the callee**, so the negative is
    pinned by `test_formal_runtime_link.py`: a `void` call whose result is
    discarded builds, runs, and its effects happen.
    """
    entry = runtime_abi_entry(name)
    sig = signature or (entry['signature'] if entry else "")
    return (
        f"{name} returns nothing — `{sig}` — and its result is used as a value "
        f"here. That is not a shape this path can give one: the callee writes "
        f"nothing to the return register, so what a read of it returns is "
        f"whatever the call sequence happened to leave there, and on this path "
        f"that is a number the source never wrote. Measured on both "
        f"architectures, `a = mojo_async_init(); b = mojo_async_schedule_"
        f"ready(0); c = mojo_async_shutdown()` printed `-1 13582400 -1` on "
        f"arm64 and `0 20463624 0` on x86-64, and both runs exited 0 — which "
        f"is the class this backend's refusals exist for. This is not the "
        f"word rule and it is not ceiling 3: every argument and the return of "
        f"this call is a single word, so the CALL is right and only the READ "
        f"is not. Call {name} as a statement of its own, which is where a "
        f"`void` call belongs.")


def check_runtime_void_results(functions) -> None:
    """Refuse a `void`-returning runtime entry point whose RESULT is used.

    The late check, asked once per function over both architectures from
    `formal/build.py::_run_late_checks` — the one place the two front ends agree,
    so this cannot be a per-emitter copy that answers differently about one
    source file.

    **`statement_call_ids` is the predicate and the reason it is not a search
    for "a call with an unused result".** An `ExprStmt` is a statement, so the
    call it owns has nowhere to put a result and the return register is
    genuinely unobserved; a call inside an expression (`x = f()`, `sink(f())`)
    is a value position and the read is the defect. That distinction is the
    same one `mutating_receiver_value_refusal` is built on, for the same
    reason, and it is why this check is about POSITION rather than about the
    callee.

    The names are read from `runtime_abi()` rather than from a list, so a
    header that adds a `void` entry point is covered without editing anything,
    and a name no header declares is left to `gimple_runtime_refusal` — which
    is the refusal that is true of it.
    """
    for fn in functions or ():
        discarded = statement_call_ids(fn)
        for node in iter_nodes(getattr(fn, "body", None)):
            if not isinstance(node, F.CallExpr):
                continue
            callee = node.func
            name = getattr(callee, "name", None) or getattr(callee, "id", None)
            if not isinstance(name, str) or id(node) in discarded:
                continue
            entry = runtime_abi_entry(name)
            if entry is not None and entry.get('returns_void'):
                raise CodegenError(gimple_runtime_void_result_refusal(name))


def _box_why(where: str, spelling: str, base: str, depth: int) -> str:
    """What one un-word-shaped type costs, in the words the refusal must use.

    Ordered most-specific first, and the two branches above the old pair are
    the ones this change added. Each names the mismatch it is about, because
    "not a value on this path" is true of all three and useful for none: a
    reader who is told a `MojoList *` is a heap box and a `double` is not a
    value is told two different things about what would have to change."""
    if depth and base == 'MojoList':
        return (
            f"{where} is a `MojoList *`, a heap box the gimple runtime owns, "
            f"where a list on this path is a blob in the frame whose first word "
            f"is its count — so the operand and the answer are of different "
            f"types, and reading offset 0 of the box would be a plausible-looking "
            f"wrong number")
    if depth >= 2 or (depth and base not in ('char', 'void')):
        # A pointer this path cannot carry in EITHER position: the callee
        # dereferences it, and there is nothing on this target to point at.
        # `char **` is the plainest case — an out-parameter the callee writes a
        # string pointer through — and it is a different defect from the
        # `MojoList *` one above, because no allocator would fix it: the problem
        # is having no addressable storage at all, not having the wrong box.
        return (
            f"{where} is `{spelling}`, which the callee DEREFERENCES rather "
            f"than carries. This path can hand over a string, because a `char *` "
            f"is a value on it (a string is an interned `char *` with no header), "
            f"and an opaque `void *` handle, passed straight back to whoever made "
            f"it. It cannot name a location the callee may read or write "
            f"through: the only storage a formal image has is a blob in the "
            f"frame, that frame is reclaimed when the function returns, and "
            f"there is no allocator here to make one that outlives it")
    if base in _FLOAT_SCALARS:
        # The one that is a *plausible-looking wrong number* rather than a
        # refusal the compiler owes the reader, and therefore the one worth
        # naming most precisely. `mojo_div_double` is the measured case.
        return (
            f"{where} is `{spelling}`, a floating-point value, and a value on "
            f"this path is one 64-bit word holding an INTEGER — a float literal "
            f"is truncated toward zero on the way in, which is the right answer "
            f"for arithmetic here and exactly the wrong one here. The callee "
            f"would read the bit pattern of an integer as a floating-point "
            f"number and answer one back, and nothing downstream could tell")
    if depth:
        return (
            f"{where} is `{spelling}`, and that is an address rather than a "
            f"value. An ARGUMENT can be one: this path carries the word and "
            f"hands it straight back to the library that made it, never looking "
            f"at what is behind it. A return is the other way round — the caller "
            f"is the one who would have to read it, and the declaration does not "
            f"say what is there. `void *` is spelled the same for a handle a "
            f"program only passes on and for a container it reads elements out "
            f"of, and a `MojoStr *` is a struct in the C heap, which a "
            f"freestanding image has no allocator for. Either way the answer is "
            f"a box, and it is not a box this path can produce")
    return (
        f"{where} is `{spelling}`, a by-value aggregate, which is a struct in "
        f"memory rather than a word")


def gimple_runtime_refusal(name: str) -> str:
    """The refusal for a call to `name`, in the words BOTH backends must use.

    One function rather than the sentence written out in each backend, because
    the two architectures are one language implementation and a refusal that
    differed between them would be the same class of divergence as an answer
    that did (test_formal_run.py's `refuse:` cases assert the agreement).

    Callers reach this only having established that the symbol is NOT on the
    image's link line, which is what the first case below reports. The second is
    the one this whole change is for: a call no link line can answer, named by
    the TYPE rather than by a prefix. The third is a name in the namespace that
    no header declares, where the only honest thing to say is that there is no
    signature to check — the old wording claimed it was a known entry point,
    which for those names is a thing the compiler had not looked at."""
    entry = runtime_abi_entry(name)
    lead = (
        f"{name} is an entry point of the gimple backend's C runtime (the "
        f"`{GIMPLE_RUNTIME_PREFIX}*` ABI declared in runtime/*.h), and a formal "
        f"image is freestanding: it links libSystem, whatever modules it "
        f"imports, and nothing of runtime/ unless it names an entry point "
        f"here — in which case `formal/build.py` puts the per-architecture "
        f"`{GIMPLE_RUNTIME_PREFIX}*` library on the link line for it. Its values "
        f"are one 64-bit word.")
    tail = (
        " Refused rather than emitted as a call to a symbol nothing defines, "
        "which is what this used to do — the image built and then died in the "
        "loader with \"Symbol not found\".")
    if entry is None:
        return (
            f"{name} is an entry point of the gimple backend's C runtime only "
            f"in name: it carries the `{GIMPLE_RUNTIME_PREFIX}*` prefix those "
            f"headers give that ABI, and no header in runtime/ declares it, so "
            f"there is no signature here to check and nothing this path can "
            f"bind.{tail}")
    if entry['word']:
        # Reached only when the library is NOT on this image's link line, which
        # is now a much narrower condition than it was: the linker puts the
        # runtime library on the line for exactly this case. So the two reasons
        # left are both facts about the LINK LINE rather than about the call,
        # and the sentence below used to name a third one that does not exist:
        # "an image that cannot carry a library at all (an ELF target —
        # `build_elf` has one `lib_name` and no dependency list)". `build_elf`
        # has taken a `deps` list and written one `DT_NEEDED` per entry since
        # the ELF emitter landed — that is how an ELF image imports a module
        # library today — so a reader sent looking for the link line's capacity
        # was sent to look for a parameter that has been there all along. What
        # is actually true for a non-Mach-O image is the CONTAINER:
        # `build_stdlib_dylib.runtime_dylib` builds a Mach-O dylib and there is
        # no ELF build of `runtime/` beside it, and
        # `formal/build.py::_audit_link_line_containers` is what refuses to
        # write a line whose libraries are in the wrong one. The other real
        # reason is a name the library does not export, of which `py_tokenize`
        # is the standing example: fire_runtime.h declares it, the dylib does
        # not define it, and `build_stdlib_dylib.runtime_export_entries` already
        # reports that as UNDEFINED. Both are named, and neither pretends the
        # mechanism is broken, because on this tree it is not.
        return (
            f"{lead} This one is the reachable half: every argument and the "
            f"return value is a single word — `{entry['signature']}` — and a "
            f"single word is exactly what a value is on this path, so a formal "
            f"image could make the call. Nothing about the CALL stops it. What "
            f"is missing is the library, and only that: nothing on this image's "
            f"link line defines {name}. There are two ways that is so and "
            f"neither is a fact about the call. The library "
            f"`formal/build.py` puts on the line for exactly this case is a "
            f"Mach-O dylib, one per architecture, and an image in the other "
            f"container cannot be given it at all — "
            f"`formal/build.py::_audit_link_line_containers` is what refuses to "
            f"write such a line, from four bytes of magic per file, because "
            f"the loader would be told to open a file it cannot open. Or the "
            f"library is on the line and does not export this name, which is a "
            f"different fact: fire_runtime.h declares `py_tokenize` and the "
            f"dylib does not define it, and "
            f"`build_stdlib_dylib.runtime_export_entries` reports that as "
            f"UNDEFINED.{tail}")
    why = ' and '.join(_box_why(*b) for b in entry['boxes'])
    return (
        f"{lead} It could not be answered by linking that library either: "
        f"{why}.{tail}")


# Python's text mode -> the C library's open(2) flag word. A formal string is a
# bare `char *`, so the mode cannot be parsed at run time; it is a decision made
# from the source, which is also the only place the information exists.
#
# The flag values are DARWIN's, and they are spelled out rather than written as
# octal literals because they are nothing like POSIX's: O_CREAT is 0x200 here
# and 0x40 on Linux, O_TRUNC is 0x400 and 0x200, O_APPEND is 0x8 and 0x400.
# Using the POSIX numbers produces calls that succeed and open the wrong thing
# (O_APPEND as O_TRUNC, O_CREAT as O_EXCL), which is worse than not compiling.
O_RDONLY = 0x0000
O_WRONLY = 0x0001
O_RDWR = 0x0002
O_APPEND = 0x0008
O_CREAT = 0x0200
O_TRUNC = 0x0400
O_EXCL = 0x0800

OPEN_WRITE = O_WRONLY | O_CREAT | O_TRUNC
OPEN_APPEND = O_WRONLY | O_CREAT | O_APPEND
OPEN_EXCLUSIVE = O_WRONLY | O_CREAT | O_EXCL

OPEN_FLAGS = {}
for _mode in ("r", "rt", "tr", "br", "rb"):
    OPEN_FLAGS[_mode] = O_RDONLY
for _mode in ("w", "wt", "tw", "bw", "wb"):
    OPEN_FLAGS[_mode] = OPEN_WRITE
for _mode in ("a", "at", "ta", "ab", "ba"):
    OPEN_FLAGS[_mode] = OPEN_APPEND
for _mode in ("x", "xt", "tx", "xb", "bx"):
    OPEN_FLAGS[_mode] = OPEN_EXCLUSIVE
# The `+` modes are the read/write ones: O_RDWR in place of O_RDONLY/O_WRONLY.
OPEN_READ_WRITE = O_RDWR
# What the file is created with when it does not exist. Python passes 0o666 and
# lets the umask take the rest; so does this.
OPEN_CRE_MODE = 0o666


def builtin_value_method(method: str):
    """How a call `recv.method(...)` lowers, or None.

    None means `method` is not a method this model represents. The caller
    distinguishes "not a value's method at all" (the receiver is a module, so
    the dotted name really is an extern) from "a method with no lowering here"
    (a refusal) by asking whether the receiver is a local value first; see
    BUILTIN_VALUE_METHODS for why the second case must not be guessed."""
    return BUILTIN_VALUE_METHODS.get(method)




# ── Calling into the C library ────────────────────────────────────────────
#
# The C library's own functions are reached as ordinary externs, bound by dyld
# through a GOT slot (see macho_linker). One of their calling conventions is not
# visible in the symbol name and has to be said here, because getting it wrong
# is a silently wrong ANSWER rather than a crash.
#
# Apple's arm64 ABI does NOT pass a variadic function's unnamed arguments in
# the argument registers. The caller builds a stack area and the i-th unnamed
# argument goes at offset 8*(i-1) from the stack pointer as it stands at the
# call; X1..X7 are ignored. A caller that does the AAPCS64-generic thing and
# puts them in registers gets a callee that reads whatever was at [sp] — which
# is how `printf("%d", 7)` on this path printed the bytes of its own format
# string. (The other half of the generic convention, AL carrying the vector
# count, does not apply here at all: clang on this target does not set it, and
# setting it corrupts X0, which on a printf call is the format pointer.)
#
# So the table records BOTH facts a call site needs: that the function is
# variadic, and how many of its arguments are NAMED (everything after them is
# `...`). Getting the second from a table rather than assuming "the first one"
# is what keeps a two-named-argument function like `fprintf(stream, fmt, ...)`
# from having its stream pointer written into the unnamed area.
#


# ── IT IS A TABLE, SO THE TABLE HAS TO BE RIGHT, AND BEING WRONG IS THE WORST


# ── OUTCOME ON THIS PATH: a callee that reads its third argument out of the


# ── unnamed area and is called without one reads `[sp]` — whatever the caller


# ── had there — and answers from it. No crash, no refusal, a plausible number.
#
# Every entry below was measured against clang's own codegen for this target
# rather than read off a prototype, because a prototype says how many arguments
# are NAMED and clang says where the third one GOES, and those are the two
# facts that have to agree. The probe is one line of C per symbol, compiled with
# `clang -O1 -S`, and the measurement is the same shape every time:
#
#     $ cat > /tmp/va3.c <<'EOF'
#     #include <fcntl.h>
#     int f(int a, int b) { return fcntl(a, b, 3); }
#     EOF
#     $ clang -O1 -S -o - /tmp/va3.c | sed -n '/_f:/,/ret/p'
#             mov w8, #3
#             str x8, [sp]            ← the third argument is in the AREA
#             mov w0, #1
#             mov w1, #2
#             bl _fcntl
#
# Three entries were wrong or missing before this was checked, and each was a
# live wrong answer rather than a missing feature:
#
#   * `fcntl` was ABSENT, so `fcntl(fd, cmd, flags)` was called with the flags
#     in X2 and nothing in the area. The syscall then applied whatever was at
#     `[sp]` — measured, `fcntl(fd, F_SETFD, 1)` returned 0 (success) and
#     changed nothing, and `fcntl(fd, F_SETFL, O_NONBLOCK)` left `F_GETFL`
#     reporting a number CPython does not report. That is
#     `“FORMAL_a_variadic_call_drops_its_third_argument: `fcntl(fd, F_SETFD”`, whose title
#     says "drops" and whose measurement is really "puts it in the wrong
#     place": the third argument was emitted, positionally, into X2.
#   * `ioctl` was ABSENT for the same reason, and it is a name this path
#     already reaches (`FRAME_C_VALUE_CALLS` lists it beside `fcntl`), so the
#     same silence applied to `ioctl(fd, request, arg)`.
#   * `asprintf` said 1 named argument and has 2 (`char **strp, const char
#     *format, ...`), which made the emitter write the FORMAT POINTER into
#     `[sp+0]` — the slot the first variadic value is read from — while the
#     value itself sat in X2 and was ignored. An entry that is present and
#     wrong is worse than one that is absent, because an absent one at least
#     fails the same way.
#
# C gives a variadic function at least one named parameter (`...` may not be the
# only one in the list), so 1 is the floor and no entry below it can exist.
#
# **The `v*` family is DELIBERATELY ABSENT** — `vprintf`, `vfprintf`, `vsprintf`,
# `vsnprintf`, `vdprintf` were here, and they are not `...`-variadic at all: each
# one takes a `va_list` as its LAST NAMED parameter
# (`int vprintf(const char *, va_list)` in this SDK's `stdio.h`, read out of
# clang's own preprocessed output rather than from memory). There is no unnamed
# argument, so an entry claiming one reserved an area and copied the `va_list`
# pointer into a slot nothing reads. Harmless today — this path cannot BUILD a
# `va_list`, so no program here calls one — and false, which is the state this
# table must not be in: it is consulted to decide a calling convention, and an
# entry that misstates one is how `asprintf: 1` came to copy a FORMAT POINTER
# into the slot the first variadic value is read from. They stay in
# `FRAME_C_VALUE_CALLS`, which answers a different question (is this name a C
# library entry point).
VARIADIC_LIBC = {
    "printf": 1,
    "fprintf": 2,
    "sprintf": 2,
    "snprintf": 3,
    "asprintf": 2, "dprintf": 2,
    # `err(status, format, ...)` and `errx(status, format, ...)` have TWO named
    # arguments — the status and the format — and were recorded with one, which
    # is the `asprintf` bug again: the emitter would have written the FORMAT
    # POINTER into `[sp+0]` and left the value in X2. Found by the direction of
    # `test_formal_external_call.py`'s `variadic_table_*` cases that reads this
    # table back out of clang's own preprocessed headers, which is the point of
    # that check being in the suite rather than in this comment.
    "syslog": 2, "err": 2, "errx": 2, "warn": 1, "warnx": 1,
    # open(2) is declared `open(const char *, int, ...)`, and Apple's build of
    # it reads the permission word from the variadic area like any other
    # variadic callee — measured, not assumed: with the word in X2 the file
    # came out with a mode made of the low bits of whatever was in that
    # register, and with it in the area the mode was 0666 & ~umask as it
    # should be.
    "open": 2,
    # `int fcntl(int, int, ...)` and `int ioctl(int, unsigned long, ...)` — the
    # two the descriptor-control commands go through, and both TWO named
    # arguments, so the third (`flags` / `arg`) is the first unnamed one and is
    # the first thing in the area. `sys/fcntl.h:624` and `sys/ioctl.h:97` in this
    # SDK; the placement is clang's, as above.
    "fcntl": 2, "ioctl": 2,
}

# Slots the caller reserves for the unnamed arguments. The area is 8-byte
# slots like everything else on this path, and 8 of them is both the area
# Apple's own code reserves in practice and every argument register an AAPCS
# call has; a call with more is refused rather than truncated.
VARIADIC_SLOTS = 8


def variadic_named_args(symbol: str):
    """How many leading arguments of `symbol` are named, or None if it is not
    a variadic C-library function.

    Compared with the underscore stripped, because the name reaches this from
    two spellings (the source's, and the Mach-O one) and a mismatch here is
    indistinguishable from "not variadic"."""
    return VARIADIC_LIBC.get(symbol.lstrip("_"))




# ── The symbol a C name binds to on THIS TARGET ───────────────────────────
#
# One call to `readdir(3)` is two different functions, and which one the source
# means is decided by the TARGET and not by the source at all. macOS's C library
# exports the whole directory-and-stat entry-point family TWICE: once for a
# 32-bit `ino_t` (`readdir`) and once for a 64-bit one (`readdir$INODE64`), with
# a `struct dirent` / `struct stat` laid out to match. `<sys/dirent.h>` picks
# between them with `#if __DARWIN_64_BIT_INO_T`, so a C program compiled for a
# 64-bit target — which is every program clang builds for arm64 AND for
# x86_64 — calls the `$INODE64` one and never sees the other. A Mojo source
# spells the bare name and there is no header to redirect it, so the BINDING is
# this backend's job, and getting it wrong is a silent wrong answer rather than
# a link error: both symbols exist on x86_64, so the image loads and runs.
#
# Measured, on this tree, for `readdir` on a directory holding three files:
#
#     x86_64, `_readdir`         38bf3e03 0c00 0401 2e000000 37bf3e03 ...
#     x86_64, `_readdir$INODE64` 38bf3e03 0000 0000 00000000 2000 0100 042e ...
#
# which is `struct dirent`'s two layouts exactly: 4-byte `d_ino`, `d_reclen` at
# 4, `d_type` at 6, `d_namlen` at 7, `d_name` at 8 for the first, and 8-byte
# `d_ino`, `d_seekoff`, `d_reclen` at 16, `d_namlen` at 18, `d_type` at 20 and
# `d_name` at 21 for the second (the `__DARWIN_STRUCT_DIRENTRY` spelling in the
# same header). `os.listdir` read `d_name` at 21 and got `.` for the 12th byte
# of the other layout, so it returned `cc.txt` where CPython returns `ccc.txt`
# and a count one too high — `bugs/FORMAL_x86_64_byte_read_of_a_libc_returned_
# pointer_reads_the_wrong_bytes.md`, whose first three candidate causes (the
# byte read, the element read, the copy) were all measured and all wrong.
#
# WHY IT IS x86_64-ONLY and why the table is not applied on arm64: arm64 has no
# 32-bit `ino_t`, so libsystem_c exports no `$INODE64` twin there and the bare
# name IS the 64-bit-inode function — measured by the linker, which refuses
# `_readdir$INODE64` for `arm64-macos` ("Undefined symbols for architecture
# arm64"), and by every arm64 stat case agreeing with CPython. Emitting the
# `$INODE64` spelling there would trade a silent wrong answer for a link
# failure. `libsystem_kernel` is the exception that proves the rule by
# exporting both for arm64 — the bare `stat` there is an alias of the
# `$INODE64` one — which is why this is a table of names rather than a rule.
#
# The set is what `libSystem.B.tbd` exports with a `$INODE64` twin for the
# `x86_64-macos` target, both libraries' lists together, so it cannot go stale
# for a host module that starts calling one of them:
#
#     SDK/usr/lib/libSystem.B.tbd, every `- targets: [ … x86_64-macos … ]`
#     block whose `symbols:` list holds a `$INODE64` name
#
# The `_b` spellings are libsystemc's Block-walking internals and no Mojo source
# can name them; they are here because the table is the platform's fact and a
# partial copy of a fact is how the next one goes wrong.
INODE64_DUAL_LIBC = frozenset({
    # libsystem_c.dylib
    "opendir", "opendir2", "readdir", "readdir_r", "readdir_unlocked",
    "rewinddir", "seekdir", "telldir", "fdopendir", "scandir", "scandirat",
    "scandir_b", "scandirat_b", "alphasort", "fdscandir", "fdscandir_b",
    "fts_open", "fts_open_b", "fts_read", "fts_close", "fts_children",
    "fts_set", "glob", "glob_b", "ftw", "nftw", "getmntinfo",
    "getmntinfo_r_np", "fstatx_np", "lstatx_np", "statx_np",
    # libsystem_kernel.dylib
    "stat", "lstat", "fstat", "fstatat", "statfs", "fstatfs",
})

INODE64_SUFFIX = "$INODE64"


def target_libc_symbol(name: str, arch: str, fmt: str) -> str:
    """The symbol an unbound C callee spelled `name` binds to on this target.

    `name` arrives as the SOURCE spells it (a bare C identifier), `arch` and
    `fmt` as `formal.build._make_codegen` was called with. The answer is `name`
    unchanged except where the platform spells the same function two ways — see
    `INODE64_DUAL_LIBC` above, which is the whole of that.

    `fmt` is a parameter rather than an `os.uname()` test because the ELF image
    this backend also emits targets a C library with no such duality (glibc has
    one `readdir` and one `stat`, both 64-bit-ino), and a `sys.platform` probe
    would silently disable the fix on the machine that needed it most.

    A name this does not recognise is returned untouched, which is the right
    answer for every C function outside the table: only the names listed have a
    second spelling to choose between."""
    if fmt != "macho" or arch != "x86_64":
        return name
    return name + INODE64_SUFFIX if name in INODE64_DUAL_LIBC else name


def libc_source_name(symbol: str) -> str:
    """The name the SOURCE spells for a symbol this tree may have re-spelled.

    The inverse direction of `target_libc_symbol`, and needed because the two
    questions "is this symbol one the C library provides?" and "which function
    did the source mean?" are asked by DIFFERENT processes about the same
    string: the linker audit asks a host `dlsym`, which can only answer for the
    host's architecture. Asked about `readdir$INODE64` on an arm64 host — where
    that symbol does not exist, because arm64 has no 32-bit `ino_t` — the
    answer is "nothing provides this", which is false about the machine the
    image will run on. So the audit strips the suffix and asks about the name
    the source used, which every macOS host does provide under one spelling or
    the other.

    **A C IDENTIFIER MAY BEGIN WITH AN UNDERSCORE, and this function used to
    strip it unconditionally** (`symbol.lstrip("_")`), which is the wrong
    inverse in both directions at once. It asks `dlsym` about a DIFFERENT
    function than the image will call — libSystem's running-image-path function
    is `_NSGetExecutablePath`, and the leading underscore is part of the NAME,
    so the audit asked about `NSGetExecutablePath` and answered "nothing
    provides this" for a symbol libSystem exports:

        >>> import formal.build as B
        >>> B._is_libsystem('_NSGetExecutablePath')       # was False
        True

    The hazard is not the wrong answer but WHERE the wrong answer is safe:
    `dlsym` and dyld disagree about these names. The shared cache answers
    `dlsym('_NSGetExecutablePath')`, and the loader does not look that name up
    at all — the bind stream carries the bare C name and dyld prepends the
    Mach-O underscore, so an audit that asks `dlsym` about a name the loader
    would reject is exactly the check that cannot catch this.

    So the underscore is stripped only when there is an `$INODE64` to remove
    after it, which is the only case the strip exists for (`_readdir$INODE64` →
    `readdir`): a Mach-O-spelled symbol reaches this function only together with
    the suffix `target_libc_symbol` added.

        readdir$INODE64        → readdir
        _readdir$INODE64       → readdir
        _NSGetExecutablePath   → itself
        _exit                  → itself
    """
    bare = symbol
    if bare.startswith("_") and bare.endswith(INODE64_SUFFIX):
        bare = bare[1:]
    if bare.endswith(INODE64_SUFFIX):
        return bare[:-len(INODE64_SUFFIX)]
    return bare




# ── "does the C library this image will load define this name?" ────────────
#
# ONE oracle, and it moved here for a reason rather than for tidiness. It used
# to be `formal/build.py::_is_libsystem`, which the link audit asks, and the
# bare-C-return table needed the SAME question for a different purpose — "is
# this callee a C library entry point at all?" — and a second dlsym with a
# second memo and a second 19-name fallback list is two implementations of one
# fact that can disagree, which is the exact shape every consolidation note in
# this tree is about.
#
# Deliberately NOT `ctypes.CDLL(None)`. The global namespace holds everything the
# BUILDING process has loaded, so it answers questions about the compiler rather
# than about the target; measured on this machine, same symbol, two handles:
#
#     CDLL('/usr/lib/libSystem.B.dylib')   sqlite3_open -> False   correct
#     CDLL(None)                           sqlite3_open -> True    WRONG
#
# because the python running the build has libsqlite3 in its own namespace. A
# build-time question about the target that inherits the builder's namespace
# waves through exactly the symbols it exists to catch, so the handle is the one
# the image's own load command names (`macho_linker.LIBSYSTEM_PATH`,
# `elf.DEFAULT_LIBC`) — the same library the emitted image declares.

_LIBC_HANDLE = None

# The 19 names the fallback below hardcodes, for a host that will not let us
# dlopen its own C library. They are a GUESS at names rather than a check of
# anything, which is the whole reason the real oracle exists; on such a host the
# guess is no worse than having no question at all, and
# `libc_probe_status()` says which of the two a build actually used so a
# diagnostic that depends on it cannot claim a check it did not make.
LIBC_LEGACY_NAMES = frozenset((
    "printf", "puts", "putchar", "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "strlen", "strcmp", "strncmp", "abort", "exit",
    "atoi", "qsort", "fmod", "pow", "sqrt",
))

# memo: bare name -> bool. One dlsym per distinct name per process, because a
# large program has hundreds of externs and a syscall per extern is a storm.
_LIBC_MEMO: dict = {}


def libc_handle():
    """A dlopen-able handle on the C library this image's load command names.

    `None` until the first call, then a handle or `False` for "this host will
    not let us ask". The three-valued answer is load-bearing: `False` is not
    "the library defines nothing", it is "we cannot find out", and every caller
    has to be able to tell those apart — `libc_probe_status()` exists so a
    refusal or a diagnostic can say which one it is standing on.
    """
    global _LIBC_HANDLE
    if _LIBC_HANDLE is None:
        _LIBC_HANDLE = False
        try:
            import ctypes
            import platform
            if platform.system() == "Darwin":
                from formal.macho_linker import LIBSYSTEM_PATH
                name = LIBSYSTEM_PATH.decode().rstrip("\0")
            else:
                from formal.elf import DEFAULT_LIBC
                name = DEFAULT_LIBC
            _LIBC_HANDLE = ctypes.CDLL(name)
        except Exception:
            _LIBC_HANDLE = False
    return _LIBC_HANDLE


def libc_probe_status() -> str:
    """How `libc_defines` reached its answer, for a diagnostic that needs it."""
    return ("asked the C library (dlsym)"
            if libc_handle() is not False else
            "FALLBACK: this host would not let the build open its C library, "
            "so a 19-name list was used instead")


def libc_defines(symbol) -> bool:
    """True for a symbol the C library this image will load actually provides.

    The name asked about is `libc_source_name`'s, not the symbol's own
    spelling, and the difference is a whole architecture's worth: a
    `readdir$INODE64` in the symbol list is the 64-bit-inode `readdir(3)`, and
    this dlsym runs in the BUILDING python, so it can only answer for the host —
    where that spelling may not exist at all. Asking about the suffix-bearing
    spelling on an arm64 host reports an x86-64 image's correct binding as a
    symbol nothing provides.

    False is a real answer — "nothing here defines it", which is what makes the
    link audit's missing-provider report true — but it is NOT the same answer as
    `libc_probe_status()`'s fallback, so a caller that turns a False into a
    refusal has to be asking a question a guess can still answer.
    """
    if not isinstance(symbol, str) or not symbol:
        return False
    bare = libc_source_name(symbol)
    if not bare:
        return False
    hit = _LIBC_MEMO.get(bare)
    if hit is not None:
        return hit
    handle = libc_handle()
    if handle is False:
        answer = bare in LIBC_LEGACY_NAMES
    else:
        try:
            answer = hasattr(handle, bare)
        except Exception:
            answer = bare in LIBC_LEGACY_NAMES
    _LIBC_MEMO[bare] = answer
    return answer




# ── print() ───────────────────────────────────────────────────────────────
#
# `print` writes to stdout, which is the one piece of observable behaviour a
# program cannot be said to have skipped. It is lowered, not stubbed: the
# backend builds the C format string for the call out of what each operand
# statically IS and emits a real call to the C library's `printf`, so
# `print("hello world")` puts `hello world` on stdout and the program's
# return value is still its exit status.
#
# That only works if "is this operand a string or a number" is decided before
# anything is emitted, which is the question the next section answers.


def comptime_val_kind(vals: dict, name: str):
    """What the `comptime` binding `name` holds — `STR_KIND`, `INT_KIND`, or
    None when this says nothing.

    ONE reader, asked by both backends from the two places that must decide
    what a read holds: the read itself (`print`, truthiness, `len`, a string
    `==`) and the store that COPIES it into a local (`var t = OS`). Two copies
    of this is two chances for one of them to keep treating a word as something
    it is not, which is the shape of the bug this closes:

        def main():
            comptime OS = "darwin"
            var t = OS
            print("t=", t)

    printed a NUMBER — a different one on each architecture (measured 4378772376
    on arm64, 4308386740 on x86-64) — because `_emit_comptime_read` materializes
    the interned literal (so the WORD in the register really is a `char *`) and
    every kind-deciding path then classified the read as an integer.

    It is not a guess, and the reason is what is absent from the table rather
    than what is in it. `_comptime_vals` holds a name ONLY when
    `comptime_eval.resolve_var` folded its initializer, so every entry here is a
    compile-time constant, and the materialization for it is already written:
    a `str` becomes the interned literal and anything else becomes an immediate
    (`_emit_comptime_read`). Classifying the folded value IS classifying the
    word. Nothing here widens "unclassified" into a guess — a `comptime` LIST
    binding is kept in `_comptime_list_asts` instead, a subscript of it stays
    unclassified, and a name that is in neither table answers None and reaches
    the refusal that exists for it.

    The integer half matters as much as the string half and for a different
    reason: it is what makes the two routes to the same value agree. A
    MODULE-level `comptime` is substituted at its read as a literal AST node
    (`_substitute_module_constants`), so `print(PW)` classifies; a
    FUNCTION-LOCAL one is not, so `print(PW)` used to refuse while
    `var t = PW; print(t)` answered — the same value, two verdicts, decided by
    which route reached it."""
    val = (vals or {}).get(name)
    if isinstance(val, str):
        return STR_KIND
    if isinstance(val, bool):
        return INT_KIND
    if isinstance(val, int):
        return INT_KIND
    return None


def print_literal(lit) -> str:
    """A string LITERAL as a fragment of a `print` format string.

    Only `%` is transformed, and only because a format string is not a string:
    `print("100% done")` has to reach printf as `100%% done` or the `%` starts a
    conversion specification and the output is whatever that specification
    happened to produce.

    Everything else — newlines, tabs, quotes, backslashes — passes through
    verbatim, because the format string is not built as C SOURCE. It is a
    string-table entry: the backends append a NUL and store the bytes, and a
    literal newline byte in the table is the newline printf writes. Escaping
    here would put a backslash and an `n` on stdout instead.

    THE TEXT IS DECODED FIRST, and the order is the whole of it. A literal
    reaches here as raw source text (`"a\\nb"` is four characters with a
    backslash), and the decode is `fire_compiler.decode_c_escapes` — the one
    decoder, which the backends' `_intern_string` calls for the same reason.
    Decoding has to precede the `%` doubling because a `%` can ARRIVE from an
    escape: `print("\\x25")` is one percent sign, and escaping the raw
    two-character text `\\x25` finds nothing to double, so printf is handed a
    bare `%` and consumes whatever is next in the varargs. Measured on this
    tree: `print("\\x25")` printed an empty line while `print("100% done")` in
    the same program printed correctly, which is exactly the signature of the
    escaping having run on the wrong text.

    THE BACKSLASHES ARE THEN DOUBLED, and that is not tidiness — it is what
    makes the decode compose with the ONE that happens downstream. This
    function's result becomes a `StringLiteral` that both backends intern, and
    interning decodes (see `arm64_codegen._intern_string`). A second decode of
    already-decoded text is not a no-op: a source `"a\\nb"` decodes once to
    `a` NEWLINE `b`, which is right, but a source `"a\\\\nb"` decodes once to a
    literal BACKSLASH followed by `n` and would decode a second time to a
    newline — the wrong answer, and one that only shows on a string holding a
    backslash. Doubling every backslash after the decode makes the second pass
    an exact inverse: `\\\\` decodes back to a single backslash, and a real
    newline byte is not a backslash and passes through untouched. So the format
    string reaches the image as the text this function decoded, which is the
    only order in which `%` and `\\n` can both be right.

    **A `bytes` LITERAL is not a string literal and does not go through this
    path**, which is the fix `bytes_repr_body` documents: CPython prints
    `repr(b)` for one, so `b"ab"` is the five characters `b'ab'` and not the two
    `ab` this used to write. The escaping below would then be wrong TWICE over —
    the `b` and the quotes are characters the source did not write — so the
    `repr` is built first and this function's own transformation is applied to
    it as a whole.

    **A `bytes` literal's text is `lit.value` and NOT `decoded_literal(lit)`**,
    and that is the whole of the `bytes` half: the parser has already decoded it,
    to one character per byte, so decoding again turns the two characters
    `\\` and `t` of `b"a\\tb"` into a TAB and the line prints `b'a\tb'` where
    CPython prints `b'a\\tb'`. The section above has the citation
    (`fire_compiler.Parser._decode_bytes_literal`) and the measurement."""
    if getattr(lit, "is_bytes", False):
        return print_literal_text("b" + bytes_repr_body(lit.value))
    return print_literal_text(F.decoded_literal(lit))


def print_literal_text(text: str) -> str:
    """Already-decoded text as a fragment of a `print` format string.

    The transformation `print_literal` applies once it has decided WHAT the text
    is, and it is a separate function so the two steps can be composed: a
    `bytes` literal's `repr`, `print_constant_text`'s `True`/`False`/`None`, and
    a plain `str` literal all end here, and none of them may skip the `%`
    doubling — a synthesized `StringLiteral` is interned by the same
    `_intern_string` and decoded by it, so an un-doubled `%` in one of these
    would start a conversion specification with no argument behind it.

    **A NUL in the text is refused here, and this is the one place that can
    see it.** Every one of these fragments becomes a byte in a string table and
    then a C string handed to `printf`, and C strings end at the first NUL, so a
    literal holding one prints only up to it: `print("a\\x00b")` printed `a`
    where CPython prints all three characters (measured on both architectures).
    There is no spelling that works — the terminator and the data are the same
    byte in the same buffer — so it is refused by name. Every caller comes
    through this function, which is why one check covers a `str` operand, a
    `sep=`, an `end=` and a synthesized `True`.
    """
    if "\x00" in text:
        raise CodegenError(nul_in_print_text_refusal(text))
    return text.replace("\\", "\\\\").replace("%", "%%")


def nul_in_print_text_refusal(text: str) -> str:
    """Why a `print` of text holding a NUL byte is refused rather than cut short.

    The wording discipline is the rest of this section's: name what CPython
    writes, name what this path's output is, and name the alternative. The
    important half is the SECOND sentence — a reader who is told only "cannot
    print this" reasonably concludes the character is unsupported, and will go
    looking for an encoding to change; the absence here is structural (a C
    string has no interior NUL) and no encoding fixes it.
    """
    at = text.index("\x00")
    return (
        f"print() of text holding a NUL byte is refused: CPython writes every "
        f"character of the value, and this path's output is a C string — the "
        f"literal is interned into a NUL-terminated table entry and printf's "
        f"%s stops at the first NUL, so the line would be silently cut short "
        f"at offset {at} of {len(text)} characters (measured on BOTH "
        f"architectures: `print(\"a\\x00b\")` printed `a`). Refused rather than "
        f"truncated, because a missing tail is a wrong answer that looks like "
        f"the right length. Print the parts around it as separate calls, or "
        f"build the text with an escape the image does not hold"
    )


def print_format(fragments: list, sep=" ", end="\n") -> str:
    """The format string for a `print` of `fragments`, in order.

    A fragment is either a conversion (`%s`, `%lld`, `%llu`) or literal text
    that has already been through `print_literal`. `sep` goes BETWEEN operands
    (never before the first, and never after the last — Python's rule, and the
    one that makes `print("a", "b")` read `a b` rather than ` a b`), and `end`
    closes the line.

    `sep` and `end` are whatever `print_literal` accepts: a literal NODE when
    the caller wrote `print(sep=…)`, and the plain already-decoded default
    otherwise. Both spellings go through the same function so a raw `sep` and a
    decoded one cannot be answered by two different rules."""
    parts = []
    for i, frag in enumerate(fragments):
        if i and sep:
            parts.append(print_literal(sep))
        parts.append(frag)
    if end:
        parts.append(print_literal(end))
    return "".join(parts)


# The keywords `print` accepts on this path. `backend` is the word the refusal
# messages quote ("the formal arm64 path"), because the messages have always
# named the machine and a message that named neither would be a third answer.
PRINT_KWARG_NAMES = ("sep", "end", "file", "flush")


def print_kwargs(e, backend: str):
    """`print`'s `sep=` / `end=` / `file=` / `flush=`, as `(sep, end, flush)`.

    **THE ONE COPY, and it is here because the two emitters had one each.**
    `_print_kwargs` was a private method in `arm64_codegen.py` and the same
    method again in `x86_64_codegen.py`, differing only in the backend word
    three messages quote — which is the shape that lets two architectures come
    to disagree about what a `print` means, and this file already says so about
    the sibling decision (`printf_format_refusal`: "two emitters that each had
    to remember both is exactly how arm64 and x86-64 come to disagree"). It is
    the same argument with a worse ratio: the sibling was at least a refusal.

    **THE KEYWORD IS DISPATCHED BEFORE ITS VALUE IS INSPECTED, and that order
    is the whole of the `flush=` fix.** The private copies asked "is this value a
    string literal?" FIRST and only then looked at the name, so a keyword whose
    value is not text at all was refused with a sentence about the two keywords
    that do want text:

        print(..., flush=True)
          ->  print(flush=...) must be a string literal on the formal arm64
              path (got Constant): the separator and the line ending are baked
              into the format string, which is built before the call is emitted

    Every clause of that is about `sep` and `end`, and `flush` is neither: it is
    a bool that asks whether to flush the stream, it is not baked into anything,
    and it is the single most common keyword in this repository's own source —
    nine of the sixty items `tools/formal_proof_breadth.py` measures reach this
    refusal on arm64, and every one of the nine is the same `print(…, flush=True)`
    in a test's `check` helper
    (the largest
    `codegen-refused` family there).

    `flush` is answered as a LITERAL bool only, and `False` is the default so it
    costs nothing: the emitters ask for the answer and emit `fflush(NULL)` after
    the `printf` when it is true. `fflush(NULL)` rather than
    `fflush(stdout)` because this model has exactly one stream, which is the same
    fact `file=`'s refusal below is stated on; stderr is unbuffered by default,
    so the extra stream it also flushes is one nothing writes to.

    `sep` and `end` come back as the literal NODES and not as `.value`, which is
    the whole reason this signature is unchanged while its body is not:
    `print(sep=r"\\t")` must print a backslash and a `t`, and `print_literal`
    can only know that from the node. The defaults are plain strings, which
    `print_literal` takes at face value — they are already-decoded text."""
    sep, end, flush = " ", "\n", False
    for k, v in e.kwargs:
        if k in ("sep", "end"):
            if not isinstance(v, F.StringLiteral):
                raise CodegenError(
                    f"print({k}=...) must be a string literal on the formal "
                    f"{backend} path (got {type(v).__name__}): the separator "
                    f"and the line ending are baked into the format string, "
                    f"which is built before the call is emitted")
            if k == "sep":
                sep = v
            else:
                end = v
        elif k == "file":
            if not (isinstance(v, F.MemberExpr) and v.member == "stdout"):
                raise CodegenError(
                    f"print(file=...) other than sys.stdout is not lowered "
                    f"on the formal {backend} path: this model has one output "
                    f"stream")
        elif k == "flush":
            if not isinstance(v, F.BoolLiteral):
                raise CodegenError(
                    f"print(flush=...) must be True or False on the formal "
                    f"{backend} path (got {type(v).__name__}): it becomes an "
                    f"`fflush` the emitter writes after the `printf`, and a "
                    f"value it cannot read at build time is a flush this path "
                    f"cannot express")
            flush = v.value
        else:
            raise CodegenError(
                f"print() has no keyword argument {k!r} on the formal "
                f"{backend} path (supports {', '.join(PRINT_KWARG_NAMES)})")
    return sep, end, flush




# ── What CPython's `print` writes for a value, and which of it is decided ──
#
# CPython renders a value through `str()`, and `str()` of a `bool` is `True` or
# `False`, `str()` of `None` is `None`, and `str()` of a `bytes` is its
# `repr()`.  NONE of those three is a number, and every one of them used to be
# rendered as one on this path, in the worst possible direction — a green
# build, an exit status of 0, and a plausible number where the source wrote a
# word:
#
#     print(True)                     →  1        (CPython: True)
#     print(a > b)                    →  0        (CPython: False)
#     print(b)   for `b: Bool = True` →  1        (CPython: True)
#     n = None; print(n)              →  0        (CPython: None)
#     print(b"ab")                    →  ab       (CPython: b'ab')
#
# measured on BOTH architectures, and the reason it survived is structural
# rather than accidental: a `Bool` on this path is a word holding 0 or 1, so its
# KIND is `INT_KIND` (`declared_type_kind`), and `is_number_kind` — the one
# predicate that decides how a value PRINTS — says an `INT_KIND` prints as a
# decimal.  The spelling a value PRINTS with is therefore not a kind, and a
# kind is the wrong place to put it: every arithmetic site, every `len` and
# every comparison asks for a kind, and all of them are right about a `Bool`
# being a word holding 0 or 1.  So this is the narrow reader instead, in the
# shape `annotation_is_bool` already has for `pop.select` — one question, asked
# at the one site that renders, and read from the same evidence.
#
# The three texts are named constants rather than literals at the use sites for
# the reason every other table in this file is: two emitters that each have to
# remember both of a bool's spellings is how arm64 and x86-64 come to disagree.
BOOL_TRUE_TEXT = "True"
BOOL_FALSE_TEXT = "False"
NONE_TEXT = "None"
# CPython's element separator, at every nesting. `print`'s OWN sep never
# enters a container's brackets — `print([1, 2], sep="")` still writes
# `[1, 2]` — so the loop's separator is this constant rather than the call's
# keyword, and one spelling is the loop's, the plan's and the tests' shared
# reader of it.
CONTAINER_ELEM_SEP = ", "


def is_none_expression(e) -> bool:
    """Whether `e` spells the `None` singleton.

    Both spellings the parser produces, and it produces BOTH: `None` in an
    expression is a `KW` token, and `_parse_atom` has no arm for it, so it comes
    out as `IdentExpr(name='None')` — measured, on this tree, by printing the
    parse of `n = None` (an `AssignStmt` whose value is `IdentExpr(name=
    'None')`).  `NoneLiteral` is the other shape and is what the rest of this
    file's `isinstance` lists already name, so asking about both is what keeps a
    parser change from turning one of them into a wrong answer again.
    """
    if isinstance(e, F.NoneLiteral):
        return True
    return isinstance(e, F.IdentExpr) and e.name == NONE_TEXT


def print_constant_text(e) -> str | None:
    """The exact text `print(e)` writes, when THIS BUILD decides it.

    `None` for the operand whose text is only known at run time, which is every
    real value; the three shapes answered here are the ones whose rendering is a
    compile-time constant:

      * `None` — CPython's `str(None)` is the three characters `None`.
      * `True` / `False` — a `BoolLiteral`'s value, which is what the WORD it
        was materialised from (0 or 1) renders as on this path too.

    The important property is that this is a FRAGMENT and not an operand: the
    text is in the format string, so there is nothing to evaluate and nothing
    that could read a register the source never wrote.  That is also why these
    are the *literal* spellings only — a NAME bound to one of them needs the
    binding, and that is `ValueKinds.is_none_value`'s question, asked by the same
    predicate through `print_constant_text` at the use site.

    Not asked for a `str` literal: those go through `print_literal` already, and
    they are not constants of THIS function — they are text that has to be
    escaped for the format string, which is a different job with a different
    answer.
    """
    if isinstance(e, F.BoolLiteral):
        return BOOL_TRUE_TEXT if e.value else BOOL_FALSE_TEXT
    if is_none_expression(e):
        return NONE_TEXT
    return None


def bool_valued_shape(e) -> bool:
    """Whether `e` IS a bool by its own shape, with no declaration consulted.

    Three shapes, and every one of them is a FACT about the expression rather
    than an inference from it — which is what makes them safe to render as
    `True`/`False` without a declaration to back them:

      * a `BoolLiteral`, whose value is already `print_constant_text`'s;
      * a COMPARISON — `<`, `>`, `<=`, `>=`, `==`, `!=`, `is`, `is not`, `in`,
        `not in` — which is a `BinaryOp` on this path and is the largest of the
        three by a wide margin (`print(x == y)` is the shape every diagnostic
        and every `check` helper in this repository's own source writes);
      * `not x`, whose operand is anything and whose result is a bool.

    A `CompareChain` is the fourth, and it is here because a chained comparison
    is one value: `0 < x < 10` evaluates to a bool, not to the `int` the middle
    operand is.

    What is deliberately NOT here: an arithmetic result (`a & b`, `x + y`),
    `and`/`or` (which yield one of their OPERANDS, so `a or b` is not a bool
    unless both operands are), and any NAME. A name is `ValueKinds`' question,
    because the evidence for it is a declaration and this function has none.
    """
    if isinstance(e, F.BoolLiteral):
        return True
    if isinstance(e, F.BinaryOp):
        return getattr(e, "op", None) in _COMPARISON_OPS
    if isinstance(e, F.CompareChain):
        return True
    if isinstance(e, F.UnaryOp):
        return getattr(e, "op", None) == "not"
    return False


def bool_print_operand(e):
    """A `%s` operand that renders the bool `e` as `True`/`False`.

    A CONDITIONAL EXPRESSION and not a branch at the call site, and the reason
    is `print`'s own shape: `print("ok:", flag, "!")` is ONE `printf` with three
    conversions, so selecting between two texts means selecting between two
    POINTERS inside that one call's varargs.  `a if c else b` is lowered to
    exactly that — a `CSEL` of two materialised addresses on arm64 when the arms
    are pure, and the same branch shape both backends already use for a
    conditional in a value position otherwise — and it leaves its value in the
    register a vararg wants.  Measured on both architectures, in a vararg, with
    a runtime condition, before this existed:

        print("r=", "yes" if t else "no")     →  `r= no` / `r= yes`

    The two arms are `StringLiteral`s rather than `char *` expressions so that
    each is interned exactly the way every other literal in an image is, and so
    that the same expression has one lowering whether it is read at build time
    (a folded `BoolLiteral` condition, `print_constant_text`'s case) or at run
    time (this one).
    """
    return F.TernaryExpr(condition=e,
                         then_val=F.StringLiteral(BOOL_TRUE_TEXT),
                         else_val=F.StringLiteral(BOOL_FALSE_TEXT),
                         line=getattr(e, "line", 0),
                         col=getattr(e, "col", 0))


# The label of the one helper function each backend appends to its image:
# CPython's shortest-round-trip `repr()` of the `double` whose bit pattern it is
# handed, written into the caller's buffer. It is a label and not a C symbol on
# purpose: the image links only the C library, and the whole point of the helper
# is that the conversion CPython prints is NOT any of that library's, so it has
# to live in the image's own `__text`. `print` of a float is the only caller,
# and the name is published here rather than spelled in each backend because the
# two must emit the same label the same way, and a second spelling is how the
# call lands on a label nothing defines.
FLOAT_REPR_SYMBOL = "__fire_float_repr"


class FloatPrintOperand:
    """A `print` operand that is a `double`, rendered by the float helper.

    Not an expression the emitter dispatches on its own: it is a marker the
    operand slot of `print_call_spelling`'s answer carries, and the emitter's
    one arm for it evaluates `expr` (the double's bit pattern into the value
    register) and branches to `FLOAT_REPR_SYMBOL` with a buffer, so the slot
    the printf's `%s` reads holds the address of CPython's spelling of the
    value rather than the value's own word. The wrapper exists so that both
    halves of the decision — which operand is a fragment and which is a value,
    and that this value is a double whose text is computed, not interned — are
    made in `print_call_spelling` once, and each backend supplies only the
    branch and the buffer it can spell on its own machine.

    `index` is the ordinal of this float AMONG THE FLOATS of one print, and
    `position` its index in the print's OPERAND list (the literals are
    fragments and not operands, so the two counts differ). They are the
    machine half of the address of the helper's buffer, which each backend
    computes from them: the block of buffers is one reservation per print
    call, `index` picks the 64-byte slot in it, and `position` says how far
    the call machinery's own argument spills have carried the stack when
    this operand is evaluated. Both are made here, in the one place that
    sees the whole operand list, so the two backends cannot number the
    buffers differently.
    """

    def __init__(self, expr, index, position):
        self.expr = expr
        self.index = index
        self.position = position




# ── `bytes`: the one kind whose CPython rendering is a QUOTED, ESCAPED word ──
#
# `print(b)` writes `repr(b)` for a `bytes`, never its text: `b'ab'`, not `ab`,
# and with CPython's own escaping and quote choice inside. Handing the text to
# `%s` (what this path did, and what `string_operand_is_string` still admits for
# FOREIGN_BYTES) prints the bytes WITHOUT the wrapper, so the line reads as an
# ordinary string and a reader cannot tell a `bytes` from a `str` — measured on
# both architectures, `print(b"ab")` printed `ab` where CPython prints `b'ab'`.
#
# **THE VALUE IS THE BYTES, one character per byte.** This is the fact the whole
# rendering rests on and it is the parser's, not this file's:
# `fire_compiler.Parser._decode_bytes_literal` "decode[s] its escape sequences to
# a latin-1 string carrying one character per output byte (codepoints 0-255)",
# and it is what `StringLiteral(is_bytes=True)` therefore holds. So a byte is
# `ord(ch)` and every byte is recoverable — `b"\xff"` is the one character
# U+00FF, and `b"\xc3\xa9"` is two — which is why nothing here is refused and
# why `bytes_repr_body` can escape a non-printable byte instead of declining to.
#
# Two consequences worth stating, because both were measured the other way round
# before this reader was written:
#
#   * **the value must not be decoded again.** `decoded_literal` would apply
#     `decode_c_escapes` to already-decoded text, and a second decode is not a
#     no-op: `b"a\\tb"` (a backslash and a `t` in the bytes) is stored as those
#     two characters and would decode to a real TAB, so the line would print
#     `b'a\tb'` where CPython prints `b'a\\tb'`. `print_literal` reads
#     `lit.value` for a `bytes` and `decoded_literal` for a `str`, which is the
#     same rule its own docstring already states for a `str`.
#   * **a RAW bytes literal needs no special case either.** `_decode_bytes_literal`
#     returns the body untouched for an `r` prefix, so `lit.value` holds the
#     backslashes the source wrote and escaping them below is what turns
#     `rb"a\nb"` into `b'a\\nb'` — CPython's answer for the same source.
#
# CPython's rules for the wrapper, all of which `bytes_repr_body` implements:
#
#   * the PREFIX is `b` (added by `print_literal`), and the QUOTE is `'` unless
#     the bytes contain `'` and do not contain `"`, in which case it is `"` — so
#     `b"a'b"` needs no escaping of its apostrophe;
#   * `\\`, `\t`, `\n` and `\r` are the named escapes CPython uses; every other
#     byte outside 0x20..0x7e is `\xNN` with two lowercase hex digits, which
#     includes `\a\b\f\v` (0x07, 0x08, 0x0c, 0x0b — NOT named by CPython's
#     `repr`, which writes them as `\xNN`), NUL and DEL;
#   * a `"` inside single quotes is NOT escaped, and neither is a `'`.
BYTES_REPR_ESCAPES = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}


def bytes_repr_body(value: str) -> str:
    """CPython's `repr()` body for the bytes a `bytes` literal's value holds.

    `value` is the literal's `value` — the latin-1 image `print_literal` names in
    the section above — and NOT `decoded_literal(lit)`, which is the mistake this
    function's own comment records. One character is one byte, so the rule is
    per CHARACTER and there is no shape of literal this cannot render: the
    `\\xNN` arm is a byte outside printable ASCII, and a byte outside printable
    ASCII is exactly what CPython escapes that way.

    The four named escapes are CPython's and only CPython's: `repr(bytes)` writes
    `\\`, `\\t`, `\\n` and `\\r` by name and everything else numerically, so
    `b"a\\x07b"` is `b'a\\x07b'` in both. The quote choice is CPython's too: `'`
    unless the bytes hold `'` and not `"`.
    """
    quote = '"' if ("'" in value and '"' not in value) else "'"
    out = []
    for ch in value:
        esc = BYTES_REPR_ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif " " <= ch <= "~":
            out.append(ch)
        else:
            out.append("\\x%02x" % ord(ch))
    return quote + "".join(out) + quote




# ── what a `print` of a FLOAT and of a CONTAINER now gets ──────────────────
#
# The FLOAT is RENDERED. Its old refusal ("print() of a float is refused …")
# was a sentence whose reason was still right — CPython's `str()` of a float is
# `repr()` of it, the SHORTEST decimal that parses back to the same 64 bits, and
# no libc conversion is that function: `%g` drops the `.0` CPython writes
# (`100000` where CPython writes `100000.0`), `%f` is six digits after the
# point (`1.500000`), `%e` is a fixed scientific spelling CPython uses only
# outside `[1e-4, 1e16)`, `%.17g` round-trips without being what CPython
# PRINTS (`0.10000000000000001` where CPython writes `0.1`), and `-0.0` survives
# only through the round-trip rule's own spelling. The rendering that replaced
# the refusal is each backend's `FLOAT_REPR_SYMBOL` helper, which computes that
# shortest decimal over the value's own bits — `%.*g` at the smallest precision
# that parses back, laid out in CPython's notation, with `inf`/`-inf`/`nan` and
# `-0.0` from the same reader — and `print_call_spelling`'s `FLOAT_KIND` arm
# hands the value to it through `FloatPrintOperand`.
#
# The CONTAINER is RENDERED, and its rendering is a loop that emits text —
# the open bracket, a `printf` per element, the close bracket — because the
# count is a run-time fact and no format string can hold it. The decision of
# WHAT the loop writes (which brackets, which separator, which element
# conversion, and the shapes it still refuses with a sentence that says what
# CPython prints) is `container_print_plan`, made in `print_arg_parts` once
# so the two backends cannot disagree about a bracket. What stays refused are
# the shapes the loop cannot render: a frame (a struct is a nested frame, not
# a blob — `container_print_refusal`), a byte blob (CPython wraps it in
# `bytearray(b'…')`, a text composition — `bytearray_print_refusal`), and the
# element shapes whose text is not a conversion of the element's own word
# (strings quote, floats round-trip, bytes wrap — see the plan's refusals).


def container_print_refusal(backend: str, kind, node_name: str) -> str:
    """Why `print` of a container is refused rather than rendered.

    `kind` is the value's kind as `ValueKinds` classified it (`list:int`, a
    frame address, a byte blob …) and `node_name` the syntax the source used, so
    the message can say both what the value IS and how it was spelled.
    """
    return (
        f"print() of a container is refused on the formal {backend} path "
        f"(this operand is a {node_name}, of kind {kind!r}): the value is a "
        f"blob this path CAN read — a count and then the elements — but `print` "
        f"builds ONE format string before the call is emitted, and rendering a "
        f"container means writing `[`, a separator and `]` around a COUNT this "
        f"build does not know, which is a loop emitting text rather than a "
        f"conversion of a word. It used to be refused by the generic message "
        f"instead — \"print() cannot tell whether {node_name} is a string or a "
        f"number\" — which was FALSE about it in the same way the float one "
        f"was: `{kind!r}` is this operand's kind, the model classified it, and "
        f"a container is neither a string nor a number. Refused rather than "
        f"emitted as the blob's address, which is what `%s` on that word would "
        f"print. Index it and print the elements, or `len()` it"
    )


def container_shape_refusal(backend: str, kind, node_name: str) -> str:
    """Why a `print` of a container whose brackets this build cannot name is
    refused.

    The kind says the word is a blob (`list:…`), and a list, a tuple, a set
    and a dict all carry the same prefix — but CPython writes different
    brackets for each, and for a dict a `key: value` pair instead of an
    element, so the brackets have to come from the SOURCE: the literal that
    spells the container, or the binding that named it. A call result, a `+`
    of blobs and the like spell none of the four, and picking is guessing the
    brackets of a value the source did not state — the same class of mistake
    the whole section exists to stop, with a bracket instead of a digit.
    """
    return (
        f"print() of a {node_name} is refused on the formal {backend} path "
        f"(of kind {kind!r}): the value is a blob this path CAN read — a count "
        f"and then the elements — and its rendering is a loop that emits its "
        f"open bracket, one printf per element and its close bracket. But a "
        f"list, a tuple, a set and a dict all classify as {kind!r}, and "
        f"CPython writes different brackets for each (and for a dict a "
        f"`key: value` pair), so the brackets have to come from the source "
        f"and this expression spells none of the four. Print the container "
        f"under the name that bound it, or index it and print the elements"
    )


def bytearray_print_refusal(backend: str, node_name: str) -> str:
    """Why a `print` of a byte blob (`bytearray`) is refused.

    CPython writes a WRAPPER — `bytearray(b'ab')`, not `ab` — and building
    that wrapper around a run-time blob is a text composition: the element
    bytes have to be read, escaped and put between `b'` and `'` with a count
    this build does not know. That is exactly the buffer
    `bugs/FORMAL_string_composition_has_no_buffer.md` is about, and
    the loop this path has emits fixed text around a conversion of a word —
    it cannot compose one. The `bytes` LITERAL spelling of the same answer is
    not refused (its bytes are a compile-time constant, so the whole wrapper
    goes in the format string), which is what makes the two spellings differ:
    the literal is decided, the name is not.
    """
    return (
        f"print() of a {node_name} is refused on the formal {backend} path: "
        f"CPython writes `bytearray(b'…')` for a byte blob — the bytes between "
        f"a wrapper — and composing that wrapper around a run-time blob is a "
        f"TEXT COMPOSITION, reading the elements, escaping them and joining "
        f"them into text with a count this build does not know. The loop this "
        f"path emits writes fixed text around a conversion of a word; it "
        f"cannot compose one. Print the `bytes` LITERAL instead (its wrapper "
        f"is a constant this path writes exactly), or `len()` the blob"
    )


def container_str_elem_refusal(backend: str, where: str) -> str:
    """Why a string element of a printed container is refused.

    CPython writes each string element QUOTED, with its own escape and quote
    choice (`['a', 'b']`, and `["it's"]` where the apostrophe turns the quote
    around), and the loop body is ONE block of code shared by every element:
    it can hand the element's `char *` to `%s` — which writes `ab`, not
    `'ab'` — or it would have to compose the quotes around each element's
    run-time text, which is the buffer this path does not have. The two
    renderings of one element differ, and the wrong one is the plausible one,
    which is what this section refuses everywhere it appears.
    """
    return (
        f"print() of a container is refused on the formal {backend} path "
        f"because {where} hold(s) a string: CPython writes each string element "
        f"QUOTED, with CPython's own escape and quote choice — `['a', 'b']`, "
        f"and `\"it's\"` where the apostrophe turns the quote around — and "
        f"the loop this path emits is one block of code shared by every "
        f"element: it can hand each element to `%s`, which writes the bare "
        f"text and no quotes (a plausible wrong line), or it would have to "
        f"compose the quotes around each element's run-time text, and that "
        f"is a text buffer this path does not have. Index it and print the "
        f"elements, which print exactly"
    )


def container_float_elem_refusal(backend: str, where: str) -> str:
    """Why a float element of a printed container is refused.

    A float's text is computed — CPython's shortest-round-trip `repr`, by the
    backend's `FLOAT_REPR_SYMBOL` helper into a 64-byte buffer (the float
    half of this section) — and a loop element is evaluated for a COUNT this
    build does not know, per element, inside a loop body that also owns its
    own printf's argument slots. Buffer slots are reserved per print call
    and numbered by the operand list the call machinery sees; a per-element
    float inside a loop would need a slot the reservation cannot number. The
    same float OUTSIDE the container is printed, by the helper, in the same
    call — the refusal is the composition of the two, not the float.
    """
    return (
        f"print() of a container is refused on the formal {backend} path "
        f"because {where} hold(s) a float: a float prints by its shortest-"
        f"round-trip `repr`, computed at run time by the backend's helper "
        f"into a 64-byte buffer whose slot is reserved PER PRINT CALL and "
        f"numbered by the call's own operand list — and a loop element is "
        f"evaluated per element, for a count the call list cannot see, so "
        f"its buffer would have no slot the reservation knows about. The "
        f"same float outside the container prints in the same call; print "
        f"the elements separately"
    )


def container_byte_elem_refusal(backend: str, where: str) -> str:
    """Why a bytes element of a printed container is refused.

    CPython writes a bytes element as its `repr` — `b'ab'`, a wrapper around
    the escaped bytes — and the loop body is the one shared block of
    `container_str_elem_refusal`: it can hand the element's `char *` to `%s`
    (bare text, no wrapper) or it would have to compose the wrapper, which
    is the buffer this path does not have. Same shape as the string element,
    one wrapper instead of a pair of quotes.
    """
    return (
        f"print() of a container is refused on the formal {backend} path "
        f"because {where} hold(s) a `bytes` value: CPython writes a bytes "
        f"element as its `repr` — `b'ab'`, the bytes between a wrapper — and "
        f"the loop this path emits is one block of code shared by every "
        f"element: it can hand the element to `%s`, which writes the bare "
        f"bytes with no wrapper, or it would have to compose the wrapper "
        f"around each element's run-time text, which is a text buffer this "
        f"path does not have. Index it and print the elements"
    )


def container_mixed_refusal(backend: str, where: str, first: str, second: str) -> str:
    """Why a container whose elements are of two render classes is refused.

    The loop body is ONE block of code that runs for every element, so it
    can render one class — a `%lld` of a word, a `True`/`False` select, a
    nested loop of one bracket pair — and two classes are two bodies.
    `[True, 1]` is the measured shape: CPython writes `[True, 1]`, and the
    two uniform bodies this path could emit each get one of the two wrong
    (`[1, 1]` for the int body, `[True, True]` for the bool body). Picking
    per element would need a branch per element index in a body that runs
    for a count this build does not know.
    """
    return (
        f"print() of a container is refused on the formal {backend} path: "
        f"{where} mix {first} and {second}, and the loop this path emits is "
        f"ONE block of code that runs for every element, so it renders one "
        f"kind of element — a conversion of the word, a `True`/`False` "
        f"select, or a nested loop of one bracket pair — and two kinds are "
        f"two bodies. Picking per element would branch on the element's "
        f"INDEX inside a body that runs for a count this build does not "
        f"know. Print the parts separately"
    )


def container_elem_refusal(backend: str, where: str, node_name: str) -> str:
    """Why an element whose render class this build cannot name is refused.

    The element is a value this build cannot classify — no kind from the
    source, or a kind this file has no rendering for (a type TAG prints a
    decimal where CPython writes `<class 'int'>`, which is
    `test_formal_run.py`'s pinned divergence for a whole value, and it is
    the same divergence inside a container). The alternative — the `%s` that
    hands a word to a conversion of a different class — is the plausible
    wrong line this section refuses everywhere.
    """
    return (
        f"print() of a container is refused on the formal {backend} path: "
        f"{where} include(s) a {node_name} whose kind this build cannot "
        f"classify, and the loop this path emits renders one class of "
        f"element per container — a conversion of the word, a `True`/"
        f"`False` select, or a nested loop — so an element it cannot "
        f"classify has no body. Annotate the element's name, or index it "
        f"and print the elements"
    )


def container_elem_kind_refusal(backend: str, where: str) -> str:
    """Why a container reached through a name whose element KIND the source
    does not state is refused.

    A bare `list` kind is "a container, and nothing here says what is in
    it" — the honest answer `global_slot_kind` gives a blob a function fills
    — and the loop body needs the element's class to choose its conversion.
    Refused rather than defaulted to `%lld`, because a container of strings
    printed as addresses is the measurement this section opened with.
    """
    return (
        f"print() of a container is refused on the formal {backend} path: "
        f"{where} have no element kind the source states — the container's "
        f"kind is a bare `list`, which is a blob whose contents nothing "
        f"declares — and the loop this path emits needs the element's class "
        f"to choose its conversion. Bind the container to a literal of known "
        f"elements, or index it and print the elements"
    )


def container_nested_refusal(backend: str, where: str, node_name: str) -> str:
    """Why a container element reached through a `node_name` is refused.

    The element is a blob — the kind says so — but a list, a tuple, a set
    and a dict all carry the same kind, and the element here is a RUN-TIME
    WORD loaded from the outer blob: there is no literal spelling its
    brackets and no binding naming it, so the four cannot be told apart.
    The top-level spellings are not refused for this reason precisely
    because the source names them; the nested one the source left unnamed,
    and guessing its brackets is the mistake this section refuses.
    """
    return (
        f"print() of a container is refused on the formal {backend} path: "
        f"{where} include(s) a container reached through a {node_name}, and "
        f"that element is a run-time word the outer blob hands over — a "
        f"list, a tuple, a set and a dict all classify the same way, so "
        f"this build cannot tell which brackets CPython writes for it, and "
        f"guessing would print one container's brackets around another's "
        f"elements. Bind the inner container to a name of its own and "
        f"print it, or print the outer's elements separately"
    )


def container_depth_refusal(backend: str, depth: int) -> str:
    """Why a container nested past `PRINT_LOOP_MAX_DEPTH` is refused.

    The loop is a nest of loops, one per bracket level, and the backend
    reserves one pair of loop temporaries per level at allocation time — so
    the depth is both the cap and the reservation's size, and a plan deeper
    than the reservation would emit a loop whose temporaries have no home.
    Refused at the plan with the number named rather than silently
    truncated, which would drop the tail of the line.
    """
    return (
        f"print() of a container is refused on the formal {backend} path: "
        f"its nesting reaches depth {depth} and the loop this path emits is "
        f"a nest of loops — one per bracket level — with one pair of loop "
        f"temporaries reserved per level, of which {PRINT_LOOP_MAX_DEPTH} "
        f"is all this path reserves. Flatten the nesting, or print the "
        f"levels separately"
    )


def dict_comprehension_print_refusal(backend: str) -> str:
    """Why a `print` of a dict COMPREHENSION is refused.

    A dict comprehension's kind carries its KEY's kind — the value is built
    at run time and states no kind of its own (`kind_of`'s dict arm says so
    — the plan cannot read the values' class off the kind, and the
    comprehension has no initializer literal the keys could be read from
    either: its pairs are built in a loop, not written by a literal. Both
    halves of the pair walk would be guessed. The LIST spelling of the same
    comprehension is not refused — its element is the one expression the
    source spells, and its kind is read from it.
    """
    return (
        f"print() of a dict comprehension is refused on the formal {backend} "
        f"path: its pairs are built in a loop rather than written by a "
        f"literal, so neither half of the pair has a kind the source states "
        f"— the comprehension's kind carries only its KEY's kind, and the "
        f"value is computed per iteration — and the loop this path emits "
        f"needs both to choose its conversions. Bind the comprehension to a "
        f"name and print a literal of the same shape, or iterate and print "
        f"the pairs"
    )


def container_dict_pair_refusal(backend: str, where: str) -> str:
    """Why a dict whose keys or values are themselves containers is refused.

    The pair walk can render a key and a value each with ONE conversion of
    the pair's word (plus the `: ` between them); a container key or value
    would need a nested loop INSIDE the pair body, around a word the pair
    walk loaded as a scalar, and the pair stride (16 bytes, key then value)
    is not the element stride the nested walk would assume. The scope of
    the first landing of this fix is scalar keys and values, and the
    refusal names the alternative rather than emitting a plausible line.
    """
    return (
        f"print() of a dict is refused on the formal {backend} path because "
        f"{where} hold(s) a container: the pair walk this path emits renders "
        f"a key and a value each with one conversion of the pair's own word, "
        f"and a container under a key (or a key that is one) needs a nested "
        f"loop where the walk reads a scalar. Print the value under the key "
        f"separately — `d[<key>]` prints exactly"
    )


# ── `print` of a container: the plan the loop emits ─────────────────────
#
# The DOC the measurement that opened this came from said the next step is
# a loop emitting text and does NOT need a buffer: the emitters can already
# emit a loop and a `printf` per element, so `print(xs)` over a blob lowers
# to the open bracket, a per-element printf and the close bracket. That is
# this section, and the one decision the two backends must not make twice —
# which brackets, which separator, which element conversion, and the shapes
# it refuses — is made here, once, into a PLAN the backends walk.
#
# A plan is a tree with two nodes:
#
#   ("cont", shape, open, close, key_plan, elem_plan)
#       a container: `shape` is `list`/`tuple`/`set`/`dict`, the brackets are
#       CPython's pair for it, `key_plan` is the key's plan for a dict and
#       None for the other three, and `elem_plan` the plan of one element —
#       ONE plan, because the loop body is one block of code shared by every
#       element, which is what the uniformity below enforces;
#   ("leaf", conv, is_bool)
#       an element the body renders with one printf: `conv` is the
#       conversion (`%lld`, `%s`) and `is_bool` says the word is a 0/1 that
#       CPython spells `True`/`False` — the render is a select between the
#       two texts, not a number.
#
# The UNIFORMITY is the safety rule, and it is over the WHOLE element tree,
# brackets included: the body runs for a count this build does not know, so
# it can render one class of element and two are two bodies (`[True, 1]` is
# the shape — `container_mixed_refusal`), and a mixed bracket in one level
# (`[[1], (2,)]`) is the same mismatch one level down. A level whose
# elements are all containers recurses, and the recursion's plans have to
# agree with each other the same way — `[[1], [2]]` is one plan twice.
#
# WHAT IS REFUSED is the one element or container whose text is not a
# conversion of its own word: strings (quoted), floats (computed), bytes
# (wrapped) — `container_{str,float,byte}_elem_refusal` — a nested
# container reached through a name (no brackets to name it —
# `container_nested_refusal`), a dict comprehension (no initializer to read
# the pairs from — `dict_comprehension_print_refusal`) and a container
# nested past the reservation (`container_depth_refusal`). Each refusal
# names what CPython writes and what this path would write instead, because
# the alternative to refusing a shape is printing a plausible line that is
# not CPython's.
PRINT_LOOP_MAX_DEPTH = 8


class ContainerPrintOperand:
    """A `print` operand that is a CONTAINER, rendered by a loop of `printf`s.

    The marker the operand slot of `print_arg_parts`'s answer carries, the
    twin of `FloatPrintOperand` for the third answer: not a fragment (its
    text is a count long) and not a conversion of one word (it is a loop),
    so the backends each supply the machine half — the loop's instructions,
    its labels, the printf per element — while the PLAN is made here once,
    in `container_print_plan`, and both backends walk the same tree rather
    than each inventing its own brackets. `expr` is the expression whose
    blob address the loop walks (materialized under container context, the
    `_emit_for_list` way), `plan` its plan tree and `kind` what `ValueKinds`
    classified it as, so a site that still refuses can name both.
    """

    def __init__(self, expr, plan, kind):
        self.expr = expr
        self.plan = plan
        self.kind = kind


# The element's render class, or the refusal: asked of one element of a
# container being planned, and the answer is what the uniformity below
# unifies over.
def _container_elem_class(node, where: str, *, kind_of, container_shape=None,
                          backend: str) -> str:
    if isinstance(node, F.BoolLiteral):
        return "bool"
    if isinstance(node, F.IntLiteral):
        return "int"
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return "cont:" + {"ListExpr": "list", "TupleExpr": "tuple",
                          "SetExpr": "set"}[type(node).__name__]
    if isinstance(node, F.DictExpr):
        return "cont:dict"
    if isinstance(node, F.Comprehension):
        return ("cont:dict" if getattr(node, "kind", "list") == "dict"
                else "cont:list")
    if isinstance(node, F.StringLiteral):
        if getattr(node, "is_bytes", False):
            raise CodegenError(container_byte_elem_refusal(backend, where))
        raise CodegenError(container_str_elem_refusal(backend, where))
    if isinstance(node, F.FloatLiteral):
        raise CodegenError(container_float_elem_refusal(backend, where))
    kind = kind_of(node) if kind_of else None
    if kind == FLOAT_KIND:
        raise CodegenError(container_float_elem_refusal(backend, where))
    if string_operand_is_string(kind):
        raise CodegenError(container_str_elem_refusal(backend, where))
    if kind is not None and is_byte_blob_kind(kind):
        raise CodegenError(container_byte_elem_refusal(backend, where))
    if kind == TYPE_KIND:
        # A type TAG is a word that prints as a decimal where CPython writes
        # `<class 'int'>` — the pinned `type_value` divergence for a whole
        # value, and the same divergence one element in.
        raise CodegenError(
            container_elem_refusal(backend, where, type(node).__name__))
    if is_number_kind(kind):
        return "int"
    if is_container_kind(kind):
        if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr,
                             F.Comprehension)):
            # A LITERAL spelling names its own brackets, and the nested plan
            # walks it — the only element this arm answers with a loop.
            shape = container_shape(node) if container_shape else None
            if shape is None:
                raise CodegenError(container_nested_refusal(
                    backend, where, type(node).__name__))
            return "cont:" + shape
        # A NAME or a call RESULT of container kind is a run-time word the
        # outer blob hands over, with no literal spelling its brackets here:
        # the nested loop would have to find the element's own plan and
        # brackets from a second lookup, and a mismatch between that lookup
        # and the binding is a plausible wrong answer — the shape the
        # refusal exists for, so the element is refused on the same terms.
        node_name = ("name" if isinstance(node, F.IdentExpr)
                     else type(node).__name__)
        raise CodegenError(container_nested_refusal(backend, where, node_name))
    raise CodegenError(
        container_elem_refusal(backend, where, type(node).__name__))


def _container_elem_plan(elems: list, where: str, depth: int, *, kind_of,
                         container_shape=None, backend: str):
    """The UNIFORM plan of `elems`, one element plan they all share.

    The classes are collected over every element — nested containers
    included, and an empty container literal contributes no class because
    its body never runs, so `[[1], []]` is the int plan twice rather than
    a mismatch — and two classes is the mixed refusal. The int conversion
    is `%lld`, the SIGNED default: a loop element is a word the blob hands
    over and this path's word prints signed (a bare `print(x)` for an
    unannotated `x` is `%lld` on the same evidence), so the element takes
    the same default rather than a per-element signedness it cannot have —
    the element is a load, not an expression the type table can be asked of.
    """
    classes = []
    for el in elems:
        c = _container_elem_class(el, where, kind_of=kind_of,
                                  container_shape=container_shape,
                                  backend=backend)
        if c.startswith("cont:") and _container_elem_count(el) == 0:
            continue  # an empty container's body never runs
        if not classes:
            classes.append(c)
        elif c != classes[0]:
            raise CodegenError(container_mixed_refusal(
                backend, where, classes[0].replace("cont:", "a container"),
                c.replace("cont:", "a container")))
    if not classes:
        # Nothing constrains the body (no elements, or empty containers
        # only): a leaf that never runs, under the outer brackets' loop.
        return ("leaf", "%lld", False)
    cls = classes[0]
    if cls == "bool":
        # The word is a 0/1 CPython spells True/False — a select of the two
        # texts, not a number. A name-bound list of bools does not get this:
        # its kind is `list:int` (a Bool's kind IS int) and the element is a
        # load with no declaration naming it, so it prints 0/1 — the
        # documented residual, the declaration being the evidence the top
        # level renders on and a loop element's load has none.
        return ("leaf", "%s", True)
    if cls == "int":
        return ("leaf", "%lld", False)
    # cont:<shape> — the elements are all containers of one shape, and the
    # nested plan has to agree across them the same way: the body's nested
    # loop is one loop, and `[[1], ["a"]]` is a nested mismatch the element
    # classes alone would miss (both are containers, of one shape each).
    if depth + 1 > PRINT_LOOP_MAX_DEPTH:
        raise CodegenError(container_depth_refusal(backend, depth + 1))
    inner_shape = cls.split(":", 1)[1]
    plans = []
    for el in elems:
        if _container_elem_count(el) == 0:
            continue  # it takes whatever plan the non-empty ones choose
        plans.append(_container_node_plan(
            el, inner_shape, depth + 1, kind_of=kind_of,
            container_shape=container_shape, backend=backend))
    if not plans:
        return ("cont", inner_shape) + _container_brackets(inner_shape) + (None,
                                                                           ("leaf", "%lld", False))
    first = plans[0]
    if any(p != first for p in plans):
        raise CodegenError(container_mixed_refusal(
            backend, where, "one shape of nested container",
            "another shape of nested container"))
    return first


def _container_elem_count(node) -> int:
    """The number of elements a container literal node spells.

    Only literals count — the class that reaches this is `cont:` from a
    node the plan walks, and a node the source spells is a literal (a name
    element of container kind is the nested refusal, not a count). A dict
    literal's count is its pairs; the rest their `elements`.
    """
    if isinstance(node, F.DictExpr):
        return len(node.pairs or [])
    return len(node.elements or [])


def _container_brackets(shape: str):
    """CPython's bracket pair for a container shape — the one table the plan
    and the refusal messages read, so a new shape joins by naming its pair
    here and nowhere else."""
    return {"list": ("[", "]"), "tuple": ("(", ")"),
            "set": ("{", "}"), "dict": ("{", "}")}[shape]


def _container_node_plan(node, shape: str, depth: int, *, kind_of,
                         container_shape=None, backend: str):
    """The plan of one container LITERAL `node` known to be of `shape`."""
    open_b, close_b = _container_brackets(shape)
    if shape == "dict":
        keys = [p[0] for p in (node.pairs or []) if len(p) >= 2]
        vals = [p[1] for p in (node.pairs or []) if len(p) >= 2]
        key_plan = _dict_scalar_plan(keys, "its keys", depth, kind_of=kind_of,
                                     container_shape=container_shape,
                                     backend=backend)
        val_plan = _dict_scalar_plan(vals, "its values", depth, kind_of=kind_of,
                                     container_shape=container_shape,
                                     backend=backend)
        return ("cont", "dict", open_b, close_b, key_plan, val_plan)
    elem_plan = _container_elem_plan(
        node.elements or [], "its elements", depth, kind_of=kind_of,
        container_shape=container_shape, backend=backend)
    return ("cont", shape, open_b, close_b, None, elem_plan)


def _dict_scalar_plan(nodes: list, where: str, depth: int, *, kind_of,
                      container_shape=None, backend: str):
    """The UNIFORM SCALAR plan of a dict's keys or values.

    A dict's pair walk renders each half with one conversion of the pair's
    word — `key: value` — so a container under either half is the nested
    loop the pair body is not built for (`container_dict_pair_refusal`),
    and a string or float or bytes under it is the element refusal of this
    section asked of the pair's half rather than a list's element.
    """
    classes = []
    for node in nodes:
        c = _container_elem_class(node, where, kind_of=kind_of,
                                  container_shape=container_shape,
                                  backend=backend)
        if c.startswith("cont:"):
            raise CodegenError(container_dict_pair_refusal(backend, where))
        if not classes:
            classes.append(c)
        elif c != classes[0]:
            raise CodegenError(container_mixed_refusal(
                backend, where, classes[0], c))
    if not classes:
        return ("leaf", "%lld", False)
    return {"bool": ("leaf", "%s", True), "int": ("leaf", "%lld", False)}[
        classes[0]]


def _name_kind_elem_plan(kind, where: str, depth: int, *, kind_of,
                         container_shape=None, backend: str):
    """The plan of the ELEMENTS of a container reached through a KIND.

    The kind chain, asked of a name (or a comprehension) rather than a
    literal the plan can walk: the element's class comes off the kind, and
    every shape the literal walk refuses is refused here on the same terms —
    a string's kind quotes, a float's is computed, a byte blob's is wrapped,
    a container's kind has no brackets to name it (`container_nested_
    refusal`: a list, a tuple, a set and a dict are one kind, and the
    element is a run-time word no binding names), and a bare `list` is a
    blob whose contents nothing declares.
    """
    if kind is None:
        raise CodegenError(container_elem_kind_refusal(backend, where))
    if kind == FLOAT_KIND:
        raise CodegenError(container_float_elem_refusal(backend, where))
    if string_operand_is_string(kind):
        raise CodegenError(container_str_elem_refusal(backend, where))
    if is_byte_blob_kind(kind):
        raise CodegenError(container_byte_elem_refusal(backend, where))
    if kind == TYPE_KIND:
        raise CodegenError(container_elem_refusal(backend, where, "a name"))
    if is_number_kind(kind):
        # The SIGNED default, on the evidence `_container_elem_plan` states
        # for a literal element: a word this path prints as a number is
        # printed signed, and a `List[UInt64]` is a bare `list` kind on this
        # path (`declared_type_kind` reads no element off the brackets), so
        # a name-bound list of unsigned words is the elem-kind refusal
        # above, not a silent `%llu`.
        return ("leaf", "%lld", False)
    if is_container_kind(kind):
        raise CodegenError(container_nested_refusal(
            backend, where, "name"))
    raise CodegenError(container_elem_kind_refusal(backend, where))


def container_print_plan(e, kind, *, kind_of, container_shape=None,
                         dict_init_of=None, dict_key_kind=None,
                         backend: str = "this path"):
    """The rendering plan of a container `print` operand, or the refusal.

    Called from `print_arg_parts` for an operand `kind_of` classifies as a
    container — the arm the generic message used to refuse — and the answer
    is the plan tree the backends' loops walk. The SHAPE is the emitter's
    fact, asked through `container_shape`: the literal's own AST (the four
    spellings name their own brackets), the name tables for a name (a dict,
    a set, a tuple, a list, in that precedence — one name is one shape and
    the tables are mutually exclusive marks), the module slot's initializer
    for a global the function does not bind, and None for a shape the
    source does not name — which is the `container_shape_refusal`.

    A dict asks its KEYS separately, because a pair blob's two halves are
    two different words (`dict_literal_key_value_kind`'s opening): the keys
    off the initializer literal the binding wrote (a literal is its own
    initializer), or off `dict_key_kind` for a name — the same question the
    for-walk asks of the same name, through the one method — and the values
    off the kind, which is the value's kind. The pair walk renders each
    half with one conversion, so both must be scalar.
    """
    shape = container_shape(e) if container_shape else None
    if shape is None:
        if kind == FRAME_KIND:
            # A struct is a nested FRAME, not a blob: the loop would walk a
            # frame's fields as elements, and that is the shape the original
            # refusal names — kept for it.
            raise CodegenError(
                container_print_refusal(backend, kind, type(e).__name__))
        if is_byte_blob_kind(kind):
            raise CodegenError(
                bytearray_print_refusal(backend, type(e).__name__))
        raise CodegenError(
            container_shape_refusal(backend, kind, type(e).__name__))
    if shape == "dict" and isinstance(e, F.Comprehension):
        raise CodegenError(dict_comprehension_print_refusal(backend))
    if shape == "dict":
        init = (e if isinstance(e, F.DictExpr)
                else dict_init_of(e) if dict_init_of else None)
        if init is not None:
            return _container_node_plan(init, "dict", 0, kind_of=kind_of,
                                        container_shape=container_shape,
                                        backend=backend)
        key_plan = _name_kind_elem_plan(
            dict_key_kind(e) if dict_key_kind else None,
            "its keys", 0, kind_of=kind_of, container_shape=container_shape,
            backend=backend)
        val_plan = _name_kind_elem_plan(
            list_elem_kind(kind), "its values", 0, kind_of=kind_of,
            container_shape=container_shape, backend=backend)
        return ("cont", "dict", "{", "}", key_plan, val_plan)
    if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return _container_node_plan(e, shape, 0, kind_of=kind_of,
                                    container_shape=container_shape,
                                    backend=backend)
    elem_plan = _name_kind_elem_plan(
        list_elem_kind(kind) if kind else None, "its elements", 0,
        kind_of=kind_of, container_shape=container_shape, backend=backend)
    open_b, close_b = _container_brackets(shape)
    return ("cont", shape, open_b, close_b, None, elem_plan)


def print_container_loop_flags(fn) -> bool:
    """Whether `fn` prints anything that is not a value literal.

    THE GATE for the `_ppb{i}`/`_ppi{i}` loop temporaries the backends
    reserve in `_collect_var_names`, and it is a SUPERSET of what emits: a
    loop is only emitted for an operand a container, and a container is
    only ever a non-literal (a name, a comprehension, a call — the value
    literals classify as words and never reach the container arm), so a
    `print` of nothing but `Int`/`Float`/`Bool`/`String`/`None` literals
    emits no loop and needs no temporary, while any other argument MIGHT
    be a container and reserves. `None` spelled as the name it parses to
    (an `IdentExpr`) also reserves, which is the permissive direction: an
    unused reserved temporary is a spare local, and a missing one is a loop
    whose index has no home.

    Asked of the whole function with `iter_nodes` — the shared walker —
    because a `print` in any position of the body (a statement, a condition,
    a default) emits in the same function, and the module-level spelling
    prints in the wrapped module body, which is a function the same way.
    """
    for node in iter_nodes(getattr(fn, "body", None) or []):
        if not (isinstance(node, F.CallExpr)
                and isinstance(node.func, F.IdentExpr)
                and node.func.name == "print"):
            continue
        for a in node.args or []:
            if not isinstance(a, (F.IntLiteral, F.FloatLiteral,
                                  F.BoolLiteral, F.StringLiteral,
                                  F.NoneLiteral)):
                return True
    return False




# ── `print`'s operand spelling: THE ONE COPY ────────────────────────────────
#
# This was `_print_call` in `arm64_codegen.py` and the same method again in
# `x86_64_codegen.py`, differing only in the word three refusals quote — which
# is the shape `print_kwargs` above was moved here to kill, and the same lesson
# the other shared tables in this file exist for.  Two copies of a decision is
# how the two architectures come to answer one construct differently, and here
# the decision was WRONG on both: every operand below used to be rendered as a
# decimal or as bare text, and `True`, `False`, `None` and `b'ab'` are four of
# the five spellings CPython's `str()` produces for a value that is not a
# number.
#
# `no_value_callee`, `kind_of` and `is_signed` are the emitter's facts, asked
# per operand and nowhere else:
#
#   * `no_value_callee(expr)` — the callee whose value this path cannot carry
#     (`ValueKinds.no_value_callee_of`), so `print(g(1))` is refused rather than
#     rendering whatever `g`'s epilogue left behind;
#   * `kind_of(expr)` — the emitter's FLOW-SENSITIVE kind (`_expr_str_kind`),
#     which is strictly better informed than the whole-function `ValueKinds`
#     because it tracks what the emission of this very function has bound;
#   * `is_signed(expr)` — whether the operand's own type is a SIGNED integer,
#     because the model's default integer is UNSIGNED and `%lld` on a `UInt64`
#     whose top bit is set prints a negative number;
#   * `is_bool(expr)` / `is_none(expr)` / `is_bytes(expr)` — the three
#     declaration questions the shape readers cannot answer for themselves,
#     because the evidence for each is a DECLARATION or a BINDING and those
#     tables are the emitter's (`ValueKinds`' recorded annotations, the function
#     table's return types).
#
# Every hook is OPTIONAL and `None` is the permissive direction: a build that
# passes no `is_bool` prints a bool the way it always did, which is what an
# operand whose boolness this build cannot see should do.
#
# THE ORDER of the arms is the order of how much is DECIDED, cheapest and most
# certain first, and it is load-bearing in one place: a `bool` must be asked
# about BEFORE the kind switch, because its kind is `INT_KIND` and the kind
# switch would answer `%lld` for it — the wrong number this whole section
# exists to stop.  For the same reason a value this build knows holds `None` is
# asked before it too: `n = None; print(n)` classifies as an integer and used
# to print `0`.
def print_arg_parts(args, *, no_value_callee=None, kind_of=None,
                    is_signed=None, is_bool=None, is_none=None,
                    is_bytes=None, container_shape=None, dict_init_of=None,
                    dict_key_kind=None, backend="this path"):
    """One PART per `print(*args)` argument, in order — the shared loop.

    `print_call_spelling`'s loop, factored into parts so that the projection
    to ONE format string (the old answer) and the loop emission (the
    container's answer) read the same decision: which operand is a fragment
    and which is a value, that a `bool` is `True`/`False` rather than the
    word's own `1`/`0`, that `None` is the four characters rather than a
    `0`, that a `bytes` literal is CPython's `repr()` of it, and — new — that
    a container is a LOOP, planned once here by `container_print_plan`
    rather than refused. A part is one of:

      ("text", escaped)          — a fragment, already through `print_literal`
      ("value", conv, operand)   — a conversion and the expression it converts
      ("float", FloatPrintOperand) — a double the helper renders
      ("container", ContainerPrintOperand) — the loop, and its plan

    The ORDER of the arms is the order of how much is DECIDED, cheapest and
    most certain first, and it is load-bearing in one place: a `bool` must be
    asked about BEFORE the kind switch, because its kind is `INT_KIND` and the
    kind switch would answer `%lld` for it — the wrong number this whole
    section exists to stop.  For the same reason a value this build knows
    holds `None` is asked before it too: `n = None; print(n)` classifies as an
    integer and used to print `0`.

    The hooks are the same ones `print_call_spelling` took, OPTIONAL and
    `None` the permissive direction, plus the three the container plan asks:
    `container_shape` (the brackets, the emitter's tables), `dict_init_of`
    (the dict literal a name bound) and `dict_key_kind` (a dict name's keys,
    the for-walk's own reader).
    """
    parts = []
    # The ordinal of a float AMONG THE FLOATS of this print — `index` on the
    # `FloatPrintOperand` — and the operand count so far, which is its
    # `position`. Both are needed by the backends' buffer arithmetic (see the
    # class's docstring), and the parts list is the one this loop builds, so
    # this loop is the one place both are known together.
    float_index = 0
    n_values = 0
    for a in args:
        if isinstance(a, F.StringLiteral):
            # `print_literal` renders a `str` literal's text and a `bytes`
            # literal's CPython `repr()`, and refuses the one `bytes` literal
            # whose bytes this path does not hold.
            parts.append(("text", print_literal(a)))
            continue
        callee = no_value_callee(a) if no_value_callee else None
        if callee is not None:
            raise CodegenError(returnless_value_refusal(callee))
        # A value whose CPython text is a COMPILE-TIME CONSTANT: `None`,
        # `True`, `False`, and a NAME this build's bindings say holds one of
        # them. It becomes literal text in the format string, so there is
        # nothing to evaluate and nothing that can read a register the source
        # never wrote.
        const = print_constant_text(a)
        if const is None and is_none is not None and is_none(a):
            const = NONE_TEXT
        if const is not None:
            parts.append(("text", print_literal_text(const)))
            continue
        # A bool that is a VALUE and not a constant — a comparison, a `not`, a
        # name a declaration says is one, a call whose callee is declared
        # `-> Bool`, a field a struct declares `Bool`. The render is a `%s`
        # whose operand is a conditional expression over the two texts.
        #
        # `bool_valued_shape` FIRST and the hook second, and the order is the
        # cheap one: the shapes need no table and the hook's answer for them is
        # the same True. The hook is asked for EVERY other operand rather than
        # for names only, because a CALL and a FIELD READ are both bools this
        # build can decide and both are decided in the emitter's tables.
        if is_bool is not None and (bool_valued_shape(a) or is_bool(a)):
            parts.append(("value", "%s", bool_print_operand(a)))
            n_values += 1
            continue
        # A `bytes`, which is `STR_KIND` and would print its bare text through
        # the arm below. Asked here, after the bool arm and before the kind
        # switch, for the same reason that arm is where it is: the kind answers
        # `ab` where CPython answers `b'ab'`. A LITERAL is rendered (its bytes
        # are a compile-time constant, so the text goes in the format string),
        # and a NAME is refused — see `bytes_name_print_refusal` for why the
        # second is not simply rendered the same way.
        if is_bytes is not None and is_bytes(a):
            lit = bytes_literal_of(a)
            if lit is None:
                raise CodegenError(bytes_name_print_refusal(backend, a))
            parts.append(("text", print_literal_text(
                "b" + bytes_repr_body(lit.value))))
            continue
        kind = kind_of(a) if kind_of else None
        if string_operand_is_string(kind):
            parts.append(("value", "%s", a))
            n_values += 1
            continue
        if kind == FLOAT_KIND:
            # Its own arm, and it comes BEFORE the generic refusal below for
            # the reason that refusal was FALSE about a float: the model
            # classifies one as `FLOAT_KIND` and `is_number_kind` says no. The
            # answer is CPython's `repr()` of the value, computed at run time
            # by the backend's `FLOAT_REPR_SYMBOL` helper — the shortest
            # decimal that parses back to the same 64 bits, in CPython's
            # own notation — and the slot the `%s` reads is that helper's
            # buffer, not the double's own word.
            parts.append(("float", FloatPrintOperand(a, float_index, n_values)))
            float_index += 1
            n_values += 1
            continue
        if is_number_kind(kind):
            # `is_number_kind` and not `== INT_KIND`: a type TAG is a word, so
            # `print(t)` for `t = bool` prints the tag, which is what it
            # printed before `TYPE_KIND` existed (`t` was then an `int` by
            # `_value_kind`'s default).
            parts.append(("value",
                          "%lld" if (is_signed and is_signed(a)) else "%llu",
                          a))
            n_values += 1
            continue
        if is_container_kind(kind):
            # THE ARM the refusal used to be: a container is a count this
            # build does not know, so its rendering is a loop — planned here,
            # once, into the marker the backends' loops walk, with the plan's
            # own refusals for the shapes it does not render (the messages
            # name what CPython writes for each).
            plan = container_print_plan(
                a, kind, kind_of=kind_of, container_shape=container_shape,
                dict_init_of=dict_init_of, dict_key_kind=dict_key_kind,
                backend=backend)
            parts.append(("container", ContainerPrintOperand(a, plan, kind)))
            continue
        raise CodegenError(
            f"print() cannot tell whether {type(a).__name__} is a "
            f"string or a number on the formal {backend} path, and "
            f"guessing would print an address as if it were text (or "
            f"a number as if it were text). Annotate the name, or "
            f"print a literal, or bind it to a literal first")
    return parts


def print_call_spelling(args, *, no_value_callee=None, kind_of=None,
                        is_signed=None, is_bool=None, is_none=None,
                        is_bytes=None, container_shape=None,
                        dict_init_of=None, dict_key_kind=None,
                        backend="this path"):
    """`(fragments, operands)` for `print(*args)` — see the section above.

    A fragment is a conversion (`%s`, `%lld`, `%llu`) or literal text that has
    already been through `print_literal`; `print_format` interleaves `sep`
    between them.  The two lists keep the relation the language has: a literal
    operand contributes a fragment and NO operand, a value contributes a
    conversion and ONE operand — because passing the literals as well would ask
    printf for fewer arguments than it was handed and everything after the first
    literal would be read one slot late.

    THE PROJECTION of `print_arg_parts` onto that one call: the decision is
    made in the parts loop (the container included — its plan is made there),
    and this function is the answer for the caller that renders a `print` as
    ONE `printf`, which is every caller but the loop. A container part in that
    projection is refused, because one format string cannot hold a count —
    the shape `container_print_refusal` names — and the loop is the answer,
    which the emitter's `print_arg_parts` call makes directly. The function
    keeps its name and signature for the callers that read it that way, and
    the container arm is defensive: no in-tree caller passes a container here.

    Raises `CodegenError` for the shapes this path cannot render, each with
    a message that says what CPython prints and what is missing here.
    """
    parts = print_arg_parts(
        args, no_value_callee=no_value_callee, kind_of=kind_of,
        is_signed=is_signed, is_bool=is_bool, is_none=is_none,
        is_bytes=is_bytes, container_shape=container_shape,
        dict_init_of=dict_init_of, dict_key_kind=dict_key_kind,
        backend=backend)
    frags, operands = [], []
    for part in parts:
        tag = part[0]
        if tag == "text":
            frags.append(part[1])
        elif tag == "value":
            frags.append(part[1])
            operands.append(part[2])
        elif tag == "float":
            frags.append("%s")
            operands.append(part[1])
        else:  # "container" — one format string cannot hold a count
            op = part[1]
            raise CodegenError(container_print_refusal(
                backend, op.kind, type(op.expr).__name__))
    return frags, operands


def bytes_name_print_refusal(backend: str, e) -> str:
    """Why a `print` of a NAME holding `bytes` is refused rather than rendered.

    The literal's own spelling is a compile-time constant of the LITERAL, which
    is why `print(b"ab")` is answered exactly. A NAME's is a constant of the
    BINDING, and this path does not track which literal a name was last bound
    to — `ValueKinds.is_bytes_value` is flow-INsensitive, as every map in that
    class is, so for `b = b"ab"` then `b = b"cd"` it can say "this name holds
    bytes" and cannot say WHICH bytes, and printing the first binding's text
    would be a plausible wrong answer in the worst place.

    So it is refused, and the alternative is named: CPython agrees with the bare
    text on every OTHER question about a `bytes` (`len`, `==`, `in`,
    `startswith`), so a program that only measures or compares is already right
    and only the rendering needs the literal at the use site.
    """
    name = e.name if isinstance(e, F.IdentExpr) else type(e).__name__
    return (
        f"print() of a `bytes` value is refused on the formal {backend} path "
        f"when the value is the NAME {name} rather than a literal: CPython "
        f"writes `repr(b)` for a `bytes` — `b'ab'`, never `ab` — and this "
        f"path's `%s` writes the bytes, which is a plausible wrong answer "
        f"rather than a missing one. The spelling is a compile-time constant "
        f"of the LITERAL, and this build does not track which literal a name "
        f"was last bound to, so it cannot say which bytes to write. Print the "
        f"literal where you mean it; note that every other question about a "
        f"`bytes` — `len`, `==`, `in`, `startswith` — is already CPython's "
        f"answer on this path"
    )


def bytes_literal_of(e):
    """The `bytes` LITERAL a `print` operand holds, or None.

    Only the one shape whose bytes are a compile-time constant: the operand IS
    the literal. A NAME bound to one is answered by the emitter's hook — it holds
    the binding, not the literal — and the text it renders is that literal's, so
    the two spellings cannot disagree: this returns the node and
    `print_call_spelling` renders it with `bytes_repr_body`, which is the same
    function the literal arm renders it with.
    """
    if isinstance(e, F.StringLiteral) and getattr(e, "is_bytes", False):
        return e
    return None


def is_container_kind(kind) -> bool:
    """Whether `kind` names a value this path holds as a BLOB.

    The families, and the shared prefix is the reason it is a predicate and not
    three comparisons at the call site: a list, a dict, a set and a `bytearray`
    are all `LIST_PREFIX` or `LIST_PREFIX + ":" + element` (the byte blob is
    `list_kind(BYTE_BLOB_ELEM_KIND)`, so the prefix covers it), and a frame
    address is `FRAME_KIND`.  `print_call_spelling` asks the question once, so
    a new blob kind joins by being named in `formal/types.py`.
    """
    if not isinstance(kind, str):
        return False
    return (kind == LIST_PREFIX or kind.startswith(LIST_PREFIX + ":")
            or kind == FRAME_KIND)




# ── What a value is ────────────────────────────────────────────────────────
#
# A formal value is one 64-bit word. A string is a bare `char *` with no header
# and no length, so "a number" and "a string" are the SAME shape in a register
# and only the binding says which — which is why print() cannot simply format
# every operand as an integer, and why getting it wrong is invisible until the
# output is read. Deciding it must not come out differently on the two
# architectures, so the rules are here and only the register shuffling is not.
#
# Kinds:
#   "int"      an integer. On this int-only path a bool and a float are also
#              just words by the time they are values (a float literal
#              truncates toward zero on emit, per types.infer_expr), so they
#              are integers here too and print as the word they hold.
#   "str"      a `char *`.
#   "list"     a list/tuple/set blob whose element kind is not known.
#   "list:K"   such a blob known to hold only "int" or only "str" elements.
#   None       the source does not say.
#
# None is not the same as "an integer", and the difference is the whole point
# of the exercise. A NAME the source never gives an annotation or a literal
# for is a word, and a word on this path is an integer — that is the same
# default types.function_var_types already takes when it seeds every local with
# DEFAULT_INT_TYPE, and it is what makes `def f(x): print(x)` work at all,
# since almost no Mojo in the tree annotates anything. What None IS refused for
# is a CONTAINER: `print(some_list)` must not print a frame address as though
# it were the list, and a blob is the one thing a word cannot honestly stand
# for. A `char *` reaching print through an unannotated parameter is the
# remaining gap, and it is the gap the annotation exists to close; the
# diagnostic says so.
#
# Subscripting gets the string/binary distinction a different way
# (`_note_binding` tracks it per function, flow sensitively); ValueKinds is the
# same question asked of a whole function at once, for the callers that have to
# decide before any statement is emitted.
#
# AN ENUM MEMBER IS ITS VALUE, and its identity is not in the word.  That is a
# decision about this section and not about the enum machinery, so it is
# recorded here with the rest of "what a value is": there is no representation
# for an enum member as a distinct object (it is one 64-bit word, and nothing in
# it says WHICH member), so every position that materializes a value treats a
# member read as the value the member holds — `enum_member_literal` for a
# class-level DEFAULT, and `enum_member_accessor` for a `.value` / `.name` read,
# which is why `Reg.A` and `Reg.A.value` are the same word and a bare `Reg.A`
# prints 7 for `A = 7`.
#
# The consequence has to be paid for in the same place, and it is the reason the
# decision was worth writing down rather than leaving to each caller:
# `enum_member_comparison_refusal`, asked by `build.refuse_enum_member_
# comparisons`, refuses `==` between two MEMBER READS, because two distinct
# members with equal values are one word and would compare equal where CPython
# says False (measured, both architectures, `A = 1` and `B = 1`). Everything else
# about enums is unaffected and stays answerable: a slot of an enum type is a
# word, so `x.kind == y.kind` and `x.kind == Kind.A` are comparisons of values
# and answer themselves.

def list_kind(elem_kind):
    """The kind of a list blob whose elements are all of `elem_kind`."""
    return LIST_PREFIX if elem_kind is None else f"{LIST_PREFIX}:{elem_kind}"


def list_elem_kind(kind):
    """The element kind of a list kind, or None when it is not pinned down."""
    if not is_list_kind(kind):
        return None
    return kind.split(":", 1)[1] if ":" in kind else None


# The element kind that says "this blob's elements are one BYTE each". A name
# rather than a boolean because a blob's element kind is where every other
# element fact already lives (`list_kind`/`list_elem_kind` carry it, and
# `subscript_element_kind` reads it), and a second axis spelled as a flag is a
# second thing to keep in step with the first.
#
# It is a LIST kind on purpose: a byte blob is `[count][byte 0]…` and every
# operation that reads a blob reads the same header, so it goes down every blob
# path on this path (`len` off the count field, the bounds check against the
# count, a walk bounded by the count) rather than a parallel set of them. What
# makes it a byte blob is the STRIDE (`blob_elem_stride`) and the fact that its
# elements are numbers, which is all `subscript_element_kind` has to say.
BYTE_BLOB_ELEM_KIND = "byte"


def byte_blob_kind():
    """The kind of a `bytearray` value: a counted blob of one-byte elements."""
    return list_kind(BYTE_BLOB_ELEM_KIND)


def is_byte_blob_kind(kind) -> bool:
    """True when `kind` names a blob whose elements are bytes.

    One predicate for both backends and for the value model, and it reads the
    ELEMENT kind rather than a type name: the question "is this blob a byte
    blob" is a property of the slot's contents, and a `var b: bytearray`
    annotation, a `bytearray()` construction and a `List[UInt8]`-looking
    subscript all have to agree about it without three spellings.
    """
    return list_elem_kind(kind) == BYTE_BLOB_ELEM_KIND


def blob_ctor_elem_stride(ctor_name: str) -> int:
    """The element stride a blob CONSTRUCTOR reserves slots at.

    The constructor's own question, and it is not the same one as
    `blob_elem_stride`: a constructor knows the TYPE it is building, not the
    kind of a value that does not exist yet. So it is asked of the name, and it
    answers the same number `blob_elem_stride` would for the kind that name
    produces — which is why the two read `BYTE_BLOB_ELEM_KIND` rather than
    each keeping a list.
    """
    if ctor_name in BYTE_BLOB_CTORS:
        return BYTE_ELEM_STRIDE
    return ELEM_STRIDE


def subscript_element_kind(base_kind):
    """What `base[i]` yields, given what `base` is: a blob's element, or a BYTE.

    The one place that question is answered, because the blob case and the
    `char *` case are the same subscript with two different answers and the
    kind table used to answer only the first: `list_elem_kind` asks
    `is_list_kind`, a string is not a blob, so `s[0]` classified as NOTHING —
    the permissive direction everywhere it was read — and one refusal built on
    that nothing never fired.  Measured, BOTH architectures, from a GREEN build:
    `printf("[%s]", s[0])` printed nothing and died of SIGSEGV, exit 139,
    because `%s` is the one conversion that dereferences and it walked bytes at
    address 97 looking for a NUL.  So the value kind of a subscript of a
    `char *` is an INTEGER, and that is not a guess about the representation: a
    string on this path IS a bare `char *` and both emitters load one byte
    (`arm64_codegen._emit_subscript_load`'s `LDRB` at width 1), which is why
    `printf("%d", s[0])` has always printed 97 and `s[0] == 46` has always been
    true.  `printf_arg_text_evidence`'s last row now sees the truth and refuses,
    and `len(s[0])` gets the honest "an integer has no length" instead of "the
    source does not say".

    NOT the SLICE: `s[1:3]` is a new string, not a byte, and the slice arm of
    `kind_of` answers it separately (`FORMAL_string_value_model.md`).

    **`FOREIGN_BYTES_KIND` is answered HERE by the same predicate and for the
    same reason, and the reason is stronger than for `str`.** A byte of a
    kernel-supplied name is a byte — that is what `readdir(3)` wrote and what
    `os.fsencode` would give — so the integer IS CPython's answer for
    `os.fsencode(name)[i]` and is NOT an answer at all for `name[i]`. The
    character reading is refused separately by `string_element_refusal`, which
    is the block that owns that question; this function's job is only to say
    that the load is ONE BYTE, which is what both emitters already emit.

    **A BYTE BLOB yields an integer for the same reason a `char *` does**, and
    it is the other half of the decision the width axis rests on: `b[i]` off a
    `bytearray` loads one byte (`LDRB`, `MOVZX`) and a byte IS the integer
    `0..255`, so claiming the element kind `byte` verbatim would leave every
    `%s`/`%d` and every arithmetic reader of the answer holding a kind nothing
    in this file has heard of. The element kind stays `byte` — it is what makes
    the blob a byte blob and what `blob_elem_stride` reads — and the VALUE kind
    is the integer. Measured on both architectures: `printf("%d %d", b[0],
    b[1])` over `bytearray(2)` with `b[0] = 65` prints `65 0`.
    """
    if string_operand_is_string(base_kind):
        return INT_KIND
    if is_byte_blob_kind(base_kind):
        return INT_KIND
    return list_elem_kind(base_kind)


def is_list_kind(kind) -> bool:
    """True when `kind` names a list/tuple/set blob of any element kind."""
    return isinstance(kind, str) and kind.startswith(LIST_PREFIX)


def is_dict_expr(e) -> bool:
    """True when `e` builds a dict PAIR blob: a dict literal or a dict
    COMPREHENSION.

    One predicate, because the two backends each had this question twice and
    each spelled it `isinstance(e, F.DictExpr)` — which the comprehension
    half silently fails: `{k: v for ...}` parses as a `Comprehension` with
    `kind == "dict"`, not a `DictExpr`. So a name bound to one was recorded
    as holding a plain blob, its subscript took the INDEX path, and
    `{i: 100 + i for i in range(3)}[2]` read the second KEY as if it were
    the value under it: right key count, right keys, wrong answers, exit 0.

    The emitters are NOT routed through here — `_emit_dict` takes a literal's
    `pairs` and there is nothing to hand a comprehension instead, so a
    comprehension still goes through `_emit_expr`'s own dispatch. This is the
    DICT-NESS question (does a subscript mean "look this key up"), not the
    "which emitter" one.
    """
    import fire_compiler as F
    if isinstance(e, F.DictExpr):
        return True
    return (isinstance(e, F.Comprehension)
            and getattr(e, "kind", "list") == "dict")


def _unify(a, b, op=None):
    """The kind an expression has when its two operands have kinds `a` and `b`.

    None (undecidable) wins over a kind, and two different kinds have no
    unification at all: `x + y` is not an int because one side looks like one.

    **A blob of ANY element kind makes the whole expression a blob**, and it
    used to be the bare `LIST_PREFIX` alone that did — false about every
    list whose elements have a kind, because `list_kind` spells that kind INTO
    the kind string. `[1, 2] * 3` therefore had `list:int` on its left and `int`
    on its right, the two did not unify, `kind_of` answered None, and the
    "unclassified non-container value is a word, and a word is an integer"
    default bound the name to an integer. Measured on both architectures before
    this line: `C = [7] * 4` then `for x in C` built, ran, and died with
    SIGSEGV (exit 139) — `C` was the integer 12, so the loop walked a count at
    address 12 — and `len(C)` was refused as "len() of a value classified as
    'int', and an integer has no length", which is a true statement about the
    wrong word.

    `op` is the operator where it changes the answer, and `*` is the one:
    `xs * n` is REPETITION, so the result's elements are the left operand's own
    and there is nothing to unify — `2 * xs` is the same repetition with the
    operands the other way round. `+`/`|` on two lists of DIFFERENT element
    kinds has no element kind of its own, and says so by answering the bare
    `LIST_PREFIX` rather than by inventing one.
    """
    if a is None or b is None:
        return None
    if a == b:
        return a
    if op == "*":
        # REPETITION, both spellings. Two blobs is a TypeError in Python, so
        # there is no honest kind to answer and None (undecidable) is it.
        if is_list_kind(a) and not is_list_kind(b):
            return a
        if is_list_kind(b) and not is_list_kind(a):
            return b
        return None
    if is_list_kind(a) and is_list_kind(b):
        return list_kind(_unify(list_elem_kind(a), list_elem_kind(b)))
    if is_list_kind(a) or is_list_kind(b):
        # `+`/`|` on a blob is list concat/set union, so a list side makes the
        # whole thing a blob whatever the other side is.
        return LIST_PREFIX
    return None


def _kind_of_call(callee: str, kind_int_call) -> str | None:
    """The kind a call to `callee` produces, or None if that is not known.

    `kind_int_call` is the hook the backend uses for its own functions (a
    callee whose declared return type is an integer yields an integer); the
    builtins whose result this model fixes are decided here."""
    if callee == "len":
        return INT_KIND      # a blob's count field; len of a string is refused
    if callee == "ord":
        return INT_KIND
    tkind = type_constructor_kind(callee)
    if tkind is not None:
        what = tkind[0]
        if what == "int":
            return INT_KIND
        if what == "identity":
            # `String(s)` is already a char *; `Pointer(p)` is a word, which
            # is not the same claim as "it is a number", so only the string
            # constructors get to say so here.
            return STR_KIND if callee in STRING_TYPE_CTORS else None
        return None
    return kind_int_call


def _kind_of_elements(elems, resolve=None) -> str | None:
    """The kind every element of a container literal has, or None.

    `resolve` is an OPTIONAL second reader, asked only about an element that is
    a bare NAME — which `_kind_of_simple` cannot classify because a name has no
    shape. It is what makes `[a, b]` with `a`/`b` locals of known kind answer at
    all, and the case that needs it is `FLOAT_KIND`: `rows = [zero, one, nan]`
    classifies as a blob of UNKNOWN element, so `rows[0] > 1.0` compared two bit
    patterns as unsigned integers and answered `nan > 1.0` TRUE, measured on
    both architectures. The same hole was there for a list of strings and is why
    this is a reader and not a `FLOAT` special case.
    """
    kinds = set()
    for el in elems:
        k = _kind_of_simple(el)
        if k is None and resolve is not None and isinstance(el, F.IdentExpr):
            k = resolve(el.name)
        if k is not None:
            kinds.add(k)
    kinds.discard(None)
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else None


# A sentinel for "this subscript's key is not a literal I can compare", so a
# missing answer is not spelled as a key that happens to equal nothing.
_NOT_A_LITERAL_KEY = object()


def _literal_dict_key(node):
    """The Python value a dict subscript's key literal denotes, or the sentinel.

    Deliberately narrow — a string or an integer literal, and nothing else —
    because the whole point of the question is that the answer can be COMPARED
    with the keys the initializer wrote. A name, a call or an arithmetic form
    could be the right key and this path cannot know it, and a key it cannot
    check is a key whose element word may never have been written.
    """
    if isinstance(node, F.StringLiteral) and not getattr(node, "is_bytes", 0) \
            and isinstance(node.value, str):
        return node.value
    if isinstance(node, F.IntLiteral):
        try:
            return int(node.value)
        except (TypeError, ValueError):
            return _NOT_A_LITERAL_KEY
    return _NOT_A_LITERAL_KEY


def _pair_value_kind(node):
    """The kind a dict literal's VALUE carries as a subscript yields it.

    `_kind_of_simple` with one addition, and the addition is the whole of why
    this function exists rather than a call: **a nested container literal is a
    blob**, so `{"a": [1, 2, 3]}` says its value is a counted region, and
    `_kind_of_simple` has no arm for a `ListExpr` because it classifies a
    literal and a list literal's kind is its ELEMENT's kind — which is
    `_kind_of_elements`' question, one level down.

    It is NOT put into `_kind_of_simple` itself, and that is deliberate. That
    function is read by every container classification in the file, including
    the module-global one (`global_slot_kind`), where the dict's VALUES are read
    out of a slot's initializer WITHOUT a check that the key being subscripted
    is one of them: the kind is claimed for the dict, and `list_elem_kind` then
    hands it to any subscript. Widening it there would extend a
    plausible-wrong-number into a plausible-wrong-number-that-is-also-a-null
    dereference, over every dict global in the tree. Confined here, the only
    reader is `dict_literal_key_value_kind`, which checks the key first — so
    the nesting this adds is available only where the write is evidenced.

    **The LIST arm is the one that recurses, and why that is safe where the
    DICT arm above is not.** `{"a": [1, 2]}` has to check that `"a"` is a key
    the literal wrote before it can claim anything about the word under it; a
    list has no such gate, because a list literal writes EVERY element it
    spells — the count field is the length of the literal and each element word
    is a store the initializer performed. So `rows = [[1, 2], [3, 4]]` says
    the word at `rows[i]` is a blob for every `i` in range, and an index out of
    range is caught by the emitter's bounds check rather than read: which is why
    the element kind can be taken off the literal without a key comparison and
    why this arm calls `_kind_of_nested_elements` (which asks `_pair_value_kind`
    per element) rather than the flat reader.

    That is the rule the whole `len()`-of-a-subscript-of-a-list-of-lists family
    needed and did not have: `formal/model.py`'s kind table FLATTENED a blob
    layout it nests, so `rows` classified as a bare `list`, `rows[0]`'s kind was
    `list_elem_kind("list")` = None, and the name it was bound to fell to
    "a word is an integer" — refused as `len(inner) is len() of a value
    classified as 'int'` about a blob whose count field was sitting at offset 0
    of a perfectly good heap address. Measured before this change, both
    architectures, on `formal/model.py`'s own element-kind rule. (The
    document that recorded that measurement,
    `FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md`, was deleted
    with its fix; the measurement is here and `_list_literal_elem_kind` is the
    fix.)
    """
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return list_kind(_list_literal_elem_kind(node.elements or []))
    if isinstance(node, F.DictExpr):
        return list_kind(container_literal_elem_kind(node))
    return _kind_of_simple(node)


def _list_literal_elem_kind(elems, resolve=None) -> str | None:
    """What the ELEMENTS of a list/tuple/set LITERAL hold: nested first, then flat.

    One function because three readers ask this exact question about the same
    node and must not answer it three ways — `ValueKinds.kind_of`'s container
    arm (`_element_kind_in_flow`), `container_literal_elem_kind`'s list branch
    (the module-global spelling of the same literal), and `_pair_value_kind`'s
    list arm (a list under a dict key, and a nested list inside a list).

    **The order is the widening, and it is deliberately one-directional: the
    nested answer when there is one, the flat answer otherwise.** Every kind the
    flat reader produced is still produced — a literal whose elements MIX a
    container with a scalar (`(1, (2, 3))`) has no single element kind under
    either rule, and the flat reader's answer there is what the whole tree has
    always answered, so taking it second keeps every existing claim intact
    rather than trading it for a refusal. What the nested reader adds is the
    case the flat one cannot see at all: `[[1, 2], [3, 4]]`, where the flat
    reader classifies every element as nothing and the container as a bare
    `list`, so `rows[0]`'s kind was `list_elem_kind("list")` = None and the
    name it was bound to fell to "a word is an integer" — refused as
    `len(inner) is len() of a value classified as 'int'` about a blob whose
    count field was at offset 0 of a live heap address. Measured on both
    architectures before this change — recorded in the deleted
    `FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md`, whose fix is
    the nested arm below.

    The flat reader is a FALLBACK and never a widening, which is the whole
    safety argument: a kind this returns is either one the flat reader already
    returned (so nothing downstream changes) or one the nested reader derived
    from a literal that WRITES every element word it classified — the property
    `_kind_of_nested_elements`' docstring gives and the reason the same nesting
    is refused for a dict's values (`_pair_value_kind`'s).
    """
    nested = _kind_of_nested_elements(elems, resolve)
    if nested is not None:
        return nested
    return _kind_of_elements(elems, resolve)


def _kind_of_nested_elements(elems, resolve=None) -> str | None:
    """`_kind_of_elements` with the nested-container arm, so an ELEMENT WORD
    is classified one level deeper than a flat literal is.

    The same question and the same evidence as `_pair_value_kind`, from the
    readers that need it: a container literal's element word holds a container
    when the element written there is one, and both a loop variable's word and
    a subscript's answer are exactly such an element word — written by the
    literal and by nothing else, which is the evidence `_pair_value_kind`'s
    docstring requires before it claims the nesting. It is kept beside that
    function rather than folded into `_kind_of_elements` for the reason that
    docstring gives: the flat reader is read by the module-global
    classification, where the dict's VALUES are taken out of a slot's
    initializer with no check that a subscripted key is one of them.

    **`resolve` is `_kind_of_elements`' second reader, and it is asked here for
    the same reason it is asked there** — a bare NAME element has no shape, so
    `[a, b]` with `a`/`b` locals of known kind is answerable only through this
    function's own flow. Its two callers with names are `ValueKinds`'s list
    arm (`kind_of`) and `_iterable_own_shape`, and they are the same question.

    **The list arm this now serves is what makes a NESTED subscript's kind
    right.** `rows = [[1, 2], [3, 4]]` bound to a local, then `inner = rows[0]`
    and `len(inner)`: `kind_of` classifies the literal as
    `list_kind(<this function's answer>)`, and with the flat reader that answer
    was None because `_kind_of_simple` has no arm for a `ListExpr` — so `rows`
    was a bare `list`, `subscript_element_kind` handed back None, `inner` fell
    to the word default, and `len` refused a blob as "classified as 'int'".
    With the nested arm, `rows` is `list:list:int` and every reader downstream
    (`len` off the count field, a subscript off the element kind, a walk's
    target) asks the same question and gets the same answer. Measured before
    the change on both architectures; the document that recorded it
    (`FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md`) was deleted
    with its fix, which is this arm.

    Measured, both architectures, before this existed — and it is the
    comprehension row of `bugs/FORMAL_string_value_model.md`, found with the
    `for` row beside it: a `for` target over `["p", "", "q"]` classified as
    `list:str` and the empty string was TRUTHY, because the count-field load
    reads the eight bytes of `__TEXT` that follow the terminating NUL. The kind
    was the list's, not the element's; see `_iterable_own_shape`.
    """
    kinds = set()
    for el in (elems or []):
        k = _pair_value_kind(el)
        if k is None and resolve is not None and isinstance(el, F.IdentExpr):
            k = resolve(el.name)
        if k is not None:
            kinds.add(k)
    kinds.discard(None)
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else None


def dict_literal_key_value_kind(node, index):
    """What `node[<index>]` yields for a LITERAL key, or None when it cannot say.

    **THE GATE, and it is the whole of what makes this safe.** A dict's element
    word is written by a STORE — the literal's own pair, or a subscript
    assignment — and not by anything that declares the dict's type. So a kind
    read off a declaration is a claim about a slot that may still be zero, and
    `len` of zero is `LDR X0, [X0]` with X0 zero: a SIGSEGV on both
    architectures, measured and recorded in `struct_field_kind`'s docstring for
    the field spelling of this. So this answers only when the initializer ITSELF
    wrote the key:

      * `node` is a dict LITERAL (a comprehension is a dict too, and is not one
        of these — `{k: v for …}` builds its pairs at run time, so there is no
        initializer here to check a key against);
      * `index` is a string or integer literal, so it can be compared with the
        keys the literal wrote rather than guessed at;
      * the literal CONTAINS that key. A missing key is CPython's `KeyError`,
        which this path cannot raise, and the word the key scan leaves behind is
        whatever the pair blob had — which for a container value is address 0.

    That last clause is why this is a function and not a `list_elem_kind` of the
    dict's kind: the refusal it produces for a key the literal does not contain
    is CORRECT, and it is the same refusal the pre-existing unclassified row
    produces, so a program that reads a missing key is no worse off than before.

    Unanimity over every pair that carries the key, because a dict literal may
    repeat one (`{"a": 1, "a": [2]}` keeps the last), and this map is
    flow-insensitive: two values of two kinds under one key claim nothing.
    """
    if not isinstance(node, F.DictExpr):
        return None
    key = _literal_dict_key(index)
    if key is _NOT_A_LITERAL_KEY:
        return None
    values = [p[1] for p in (node.pairs or [])
              if len(p) >= 2 and _literal_dict_key(p[0]) == key]
    if not values:
        return None
    kinds = {_pair_value_kind(v) for v in values}
    kinds.discard(None)
    if len(kinds) != 1:
        return None
    return kinds.pop()


def dict_literal_key_kind(node) -> str | None:
    """What walking a dict LITERAL `node` yields — the kind of its KEYS.

    The KEY half of `dict_literal_key_value_kind`, which answers the VALUE
    under one subscripted key: a pair blob is `[count][k0][v0]…`, so a walk
    over one (`for k in d`) yields `k0, k1, …` and a subscript yields the
    value under a key it scanned for. Two different words of the same blob, and
    asking for one with the other's rule is how a loop target over string keys
    came to be classified as an integer and printed as an address.

    Same gate as its twin: only a LITERAL states which words were written, so
    a comprehension (whose pairs are built at run time) answers nothing. Keys
    rather than pairs, and unanimity over all of them — every key is walked, so
    a table mixing string and integer keys claims nothing and the caller keeps
    its conservative fallback.
    """
    if not isinstance(node, F.DictExpr):
        return None
    return _kind_of_elements([p[0] for p in (node.pairs or []) if p])


def container_literal_elem_kind(node) -> str | None:
    """What a subscript of the container LITERAL `node` yields, or None.

    The one reader of "what do this container's elements hold", asked of the
    initializer that states it, and it is asked in two places that used to
    disagree — which is why it is one function rather than two rules:

      * a dict literal bound to a LOCAL (`d = {"a": 10}`), through
        `ValueKinds.kind_of`, and
      * a container literal bound at MODULE level (`D = {"a": 10}`), through
        `global_slot_kind`, whose slot records the same initializer.

    Only a DICT is a new answer. A list/tuple/set literal already classified by
    element (`list_kind(_kind_of_elements(...))`), and a dict did not — it
    classified as a bare `LIST_PREFIX`, so `list_elem_kind` had nothing to hand
    back and every use site that must decide before emitting refused. `print()`
    is the one those programs meet first:

        d = {"a": 10, "b": 20}
        print("Value of a:", d["a"])   # -> print() cannot tell whether
                                       #    SubscriptExpr is a string or a number

    The VALUES and not the keys, because a dict blob is `[npairs][k0][v0]…` and
    a subscript of it is a key SCAN that leaves the value in hand
    (`arm64_codegen._emit_dict_lookup_addr`); the kind asked for is therefore the
    value's, and `_kind_of_elements` over the keys would claim a string element
    where the word read out is a number.

    `_kind_of_simple` underwrites on purpose: it classifies a LITERAL, so
    `{i: 100 + i for i in range(3)}[2]` stays undecided rather than guessing
    from the first operand of an arithmetic form. Unanimity is the other half
    of the safety argument — a dict whose values disagree claims nothing, which
    is what keeps this from being a way to print one of two kinds as the other.

    **The LIST branch reads the nesting and the DICT branch does not, and the
    asymmetry is the evidence rather than an oversight.** This function is read
    by `global_slot_kind`, which takes a module-level literal's element kind and
    hands it to ANY subscript of that name — so for a DICT the word under a key
    the literal never wrote is a claim about a slot nothing initialised, and
    `_pair_value_kind`'s docstring is the long form of that argument (the fix is
    a key check there, and the key check is why the nesting is confined to that
    function). A LIST has no such word: `L = [[1, 2], [3, 4]]` writes a count and
    then one store per element, so `L[i]` for every `i` in range reads a word the
    initializer wrote, and an index out of range is caught by the emitter's
    bounds check rather than read. So the list branch asks
    `_kind_of_nested_elements` and gets `list:int` for that literal, which is
    what makes `len(L[0])` a count-field read at both the local and the module
    level. Measured on both architectures before this change, where the module
    spelling refused exactly as the local one did — the measurement the
    deleted `FORMAL_len_of_a_subscript_of_a_list_of_lists_is_an_int.md`
    carried, and the reason this arm exists.
    """
    repeated = _repeated_container(node)
    if repeated is not None:
        # `[e0, e1] * N` writes every element of its left operand, N times, so
        # the element-kind question is the same one the written-out literal
        # answers — asked of that operand's own elements.
        return _list_literal_elem_kind(list(repeated[0].elements or []))
    if isinstance(node, F.DictExpr):
        values = [p[1] for p in (node.pairs or []) if len(p) >= 2]
        return _kind_of_elements(values)
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return _list_literal_elem_kind(node.elements or [])
    return None


def _kind_of_simple(e) -> str | None:
    """The kind of an expression that needs nothing but itself to classify."""
    if isinstance(e, F.StringLiteral):
        return STR_KIND
    if isinstance(e, F.FloatLiteral):
        # A float literal is the ONE expression whose kind is its own syntax:
        # there is no declaration to read and no name to trace, so the literal
        # is the only evidence there is.  It was `INT_KIND`, which is what made
        # `1.5 + 2.25` an `ADD` of two truncated zeros — a green build
        # answering `0` where CPython answers `3.75`.
        return FLOAT_KIND
    if isinstance(e, (F.IntLiteral, F.BoolLiteral)):
        return INT_KIND
    if isinstance(e, F.UnaryOp):
        if e.op == "not":
            return INT_KIND
        return _kind_of_simple(e.operand)
    if isinstance(e, F.MemberExpr) and type_value_tag(e) is not None:
        # `DType.int32` — a type named as a VALUE, which is one 63-bit TAG and
        # so `TYPE_KIND`. Asked with `type_value_tag`, the ONE reader both
        # backends' member arms use for exactly this expression, so a third
        # answer cannot appear here.
        #
        # It was missing, and the consequence was a downstream one rather than a
        # cosmetic one: `declared_type_kind` classifies a field DECLARED `DType`
        # as a tag, so `struct S { var d: DType }` knows the slot holds a tag —
        # but `S(DType.int32)` puts the tag there through `__init__`, and
        # `ValueKinds._constructed_field_kind` requires the constructor
        # argument's own kind to be EVIDENCE ("a bare name is asked of
        # `own_shape_kind` and a call result is refused by `_own_shape_of`'s
        # filter"). The argument is this expression, it classified as None, and
        # so the slot's kind was unestablished. Measured on both backends,
        # `struct S { var d: DType; var t: Int }` with
        # `def __init__(out self, v: DType): self.d = v`, called as
        # `S(DType.int32)`, and `printf("%d", s.d[0])` then built, ran and died
        # of SIGSEGV (exit 139) — the container lowering reading a count out of
        # the tag. Same class as the `DTYPE_TYPE_NAMES` row's own note ("one
        # value, two kinds, decided by where the name is written"), one level
        # further in: there the field and the local disagreed, here the field
        # and the CONSTRUCTOR ARGUMENT do.
        # commit f0df70b2's row 3.
        return TYPE_KIND
    return None
