# A `__exit__` whose RETURN VALUE is computed can still suppress, and the gate
# that catches the foldable half cannot see this one

**Area:** FORMAL, context managers. Claim `project:with-statements`, measured
2026-10-05 on `work/formal56-with-statements`. **OPEN, and deliberately left
open by a fix in the same commit that created it.** The wrong answer this
project found — a suppressing `__exit__` whose value the protocol dropped — is
now REFUSED whenever the build can fold the value. This is the half it cannot
fold, stated rather than hidden, because the alternative was refusing a host
module the corpus depends on.

**Update 2026-10-13 (`work/formal392-docs`): the FOLDABLE half was STILL
incomplete two shapes further out, and is now complete for the kinds the build
can fold.** Both are measured on both architectures and both produced the
identical wrong answer as `return True` (built, printed `enter / body 7 /
exit`, exited 1 where CPython prints `after` and exits 0):

* **`len(<string literal>)`** — a foldable CALL rather than a literal, so
  `fold_literal_expr`'s `len` arm (which is over a DISPLAY, and is the WORD
  reader shared with the struct-field and class-constant readers) did not reach
  it. It is now decided from the literal's own text (a non-empty string is
  truthy under `len` exactly as under the string itself, and a non-empty source
  cannot decode to an empty string, so the raw value answers the truthiness),
  with `is_interpolated_literal` and `is_bytes` excluded because the first's
  value is its SOURCE TOKEN and the second is not a `str`.
* **the value-selecting and BOOLEAN shapes** — a comparison, `a if c else b`,
  `and`/`or` and `not` over constants, which `fold_literal_expr` deliberately
  does not hold and `fold_module_select_expr` does (`return 1 < 2`,
  `return 9 if 1 else 0` and `return not 0` are all foldably true). The folder
  is reached only where `fold_literal_expr` answered None, so this function's
  float-truthiness rule is not weakened.

Falsy siblings `return len("")`, `return ""`, `return 0.0` and `return 1 < 0`
all still lower. Pinned by `test_formal_with.py`'s
`an_exit_returning_len_of_a_nonempty_string_is_refused`,
`an_exit_returning_len_of_an_empty_string_still_runs_the_protocol`,
`an_exit_returning_a_true_comparison_is_refused` and
`an_exit_returning_a_false_comparison_still_runs_the_protocol`. **§2's
computed case is untouched and is still the whole of what is left.**

**Update 2026-10-13 (`work/formal408-docs`): the FOLDABLE half was STILL
incomplete after 2026-10-07, and the gap was measured and closed.** The
2026-10-07 note below widened the gate from `isinstance(value, int)` to the
folded value's truthiness, but `_literal_return_truthiness` still consulted only
`fold_literal_expr`, which folds literals and four arithmetic operators. A truthy
`__exit__` return built from a COMPARISON, a boolean (`and`/`or`/`not`), a select
(`a if c else b`), a bitwise op, `len(<string literal>)` or `a % b` / `a / b`
therefore was not read as truthy, and the suppression it names was dropped —
the SAME wrong answer as `return True`, reached through a constant the build
could read perfectly well. Measured on **both** architectures (`return 1 < 2`,
`return 1 and 2`, `return 1 if 1 else 0`, `return 1 | 2`, `return len("abc")`,
`return 7 % 3`): each BUILT, printed `enter / body / exit` and exited 1 where
CPython prints `after` and exits 0.

The fix composes the three constant folders `fold_module_value` already trusts —
`fold_literal_expr`, `fold_module_select_expr` (a comparison, `and`/`or`/`not`,
`a if c else b`) and `fold_module_int_expr` (bitwise and shift) — and adds the two
things no folder carries: `len(<string literal>)` (whose truthiness is "the text
is non-empty", encoding-free) and the two arithmetic operators `/` and `%`
(folded for TRUTHINESS only, which is one-sided in the safe direction: a constant
the fold reads as truthy is one CPython suppresses, and `a % b` is zero exactly
when `b` divides `a` under either floor). Three shapes the int/str folders
decline for a WORD reason rather than a truthiness one are also read, by
recursing on the operand that decides the result: a CONTAINER display (truthy iff
non-empty, and only when its arity is static — a `[*a]` or `{**a}` spread is left
undecided), a `not`/`and`/`or`/`a if c else b` whose operand is a FLOAT or a
STRING (the module-level folder is deliberately int-only in a condition, because
the empty string is a non-null `char *` on the machine), a CHAINED comparison
(`a < b < c`, its own node, read through a value reader that adds the float the
word folders lack), and a constant display element (`(1, 2)[0]`). Asking more of
the folders can only move a constant from "undecided" to "decided as truthy",
never the reverse, so the gate stays one-sided rather than becoming a refusal of
every computed return (which would refuse `nullcontext`). Pinned by ten REFUSAL
rows and four falsy ANSWERED siblings in `test_formal_with.py`
(`an_exit_returning_a_comparison_is_refused_for_the_same_reason`,
`…a_boolean_operator…`, `…a_select…`, `…a_bitwise_operator…`,
`…len_of_a_literal…`, `…a_constant_remainder…`,
`…a_non_empty_display…`, `…a_chained_comparison…`, `…a_float_select…`,
`…a_boolean_over_a_float…`, and
`an_exit_returning_a_false_comparison_still_runs_the_protocol`,
`an_exit_returning_len_of_the_empty_string_still_runs_the_protocol`,
`an_exit_returning_an_empty_display_still_runs_the_protocol`,
`an_exit_returning_a_false_chained_comparison_still_runs_the_protocol`) — 471/0,
up from 387. **§2's computed case — a return that depends on a RUN-TIME value,
which is cross-field flow — is untouched and is still the whole of what is
left.**

**Update 2026-10-07 (`work/formal121-docs`): the FOLDABLE half was itself
incomplete, and is now complete.** The gate's own docstring said the test was the
returned value's truthiness, but the code tested `isinstance(value, int)` over
`fold_literal_expr`'s answer, so two whole literal kinds were let through:

* a non-empty STRING — `fold_literal_expr` folds it to a `str` and the gate then
  discarded it for being the wrong type; and
* a non-zero FLOAT — `fold_literal_expr` has no float arm at all (it is the word
  reader, and a float is not an integer word), so a float never reached the test.

Both are the same wrong answer as `return True`, measured on both architectures:
`return "yes"` and `return 0.5` each built, printed `enter / body 7 / exit` and
exited 1 where CPython prints `after` and exits 0. The decision now goes through
`model._literal_return_truthiness`, which decides an int/bool/string from its
folded value and a float (and a `+`/`-` over one) from its own — NOT through
`fold_module_value`, whose `int(0.5)` is 0 and would answer the truthiness the
wrong way. `return ""`, `return 0.0`, `return 0`, `return False` and `return
None` all still lower. Pinned by `test_formal_with.py`'s truthy-string and
truthy-float REFUSAL rows and their falsy siblings
(`an_exit_returning_an_empty_string_still_runs_the_protocol`,
`an_exit_returning_zero_point_zero_still_runs_the_protocol`).

**Update 2026-10-13 (`work/formal335-docs`): the FOLDABLE half had a SECOND
incomplete edge, and it is now closed.** The 2026-10-07 update below was right
that the gate tests the returned value's TRUTHINESS and fixed the string and
float arms, but `_literal_return_truthiness` still answered `None` for a whole
class of compile-time constants — so a `__exit__` ending in one SUPPRESSED in
CPython while this path ran the cleanup and exited 1, the same wrong answer as
`return True`. Measured on both architectures, each of

    return not 0     return 1 < 2     return 1 == 1     return 1 != 2
    return 1 and 2   return 0 or 3    return not ""     return not 0 and 1
    return 1 if 1 else 0              return "a" == "a"  return None == None
    return len("ab")

built, printed `enter / body 7 / exit`, never printed `after` and exited 1 where
CPython prints `after` and exits 0. `_literal_return_truthiness` now decides
three more arms: a `not` from its OPERAND's truthiness (so `not 1` is falsy and
still lowers — the word reader would have got that backwards), the
`a if c else b` / `and` / `or` / six-comparison shapes via
`fold_module_select_expr`, and `==`/`!=` over two literals plus
`len(<string literal>)` itself (`fold_module_select_expr` refuses a string
comparison operand and has no `len`-of-a-string arm). `fold_module_select_expr`
is safe to delegate to here because it cannot return a truncated float — its
only float arm is `fold_module_value`'s top-level `FloatLiteral`, which this
reader decides from its own value first. Pinned in `test_formal_with.py` by
seven refusal rows and their five falsy siblings (450 checks, up from 378).
**§2's computed case is untouched and is still the whole of what is left**:
`return self.quiet` depends on a constructor argument, which is cross-FIELD flow
rather than a fold.


Measured, both architectures, on §2's own program with `Suppressor(1)`: it used
to BUILD, print `body 7`, never print `after` and exit 1 where CPython exits 0.
It is now refused, naming the field and the construction. Pinned by
`test_formal_with.py`:
`a_computed_exit_the_site_makes_truthy_is_refused_by_name`,
`a_computed_exit_made_truthy_by_a_keyword_is_refused_the_same_way`, and the two
ANSWERED boundaries the refusal must not cross —
`a_computed_exit_the_site_makes_falsy_still_runs_the_protocol` (`Quiet(0)`, so
CPython does not suppress and the exception still propagates) and
`a_computed_truthy_exit_still_lowers_when_the_body_cannot_raise`.

**What is STILL open, and it is the true root cause rather than a wider fold.**
The reader only decides a field whose slot THIS construction fills with a
FOLDABLE value, and it reads the construction INLINE (`with Quiet(1) as v:`): a
manager whose `__exit__` returns a field bound from a CALL, from a parameter,
from a default, from another field, or from a `q = Quiet(1)` binding the `with`
only names still builds and still suppresses silently, and a struct that
declares `__init__` is not read at all —
binding a parameter to a field in a body the reader does not follow is how a
plausible constant gets invented, which is the fabrication this tree refuses
everywhere. Honouring the suppression rather than refusing the decidable case is
still §4's status word plus resume edge, and it is still the last step. §2's
computed case is therefore decided one increment further out and is not closed.

**Read this before planning the work.** This is a limit of the EVIDENCE, not of
the gate: `model.context_exit_returns_truthy` asks "does some `return` in
`__exit__` fold to a truthy value", and `fold_literal_expr` answers None for
anything computed. Closing it needs cross-FIELD flow, which is the same question
`arm64_codegen.py::_expr_is_fd` declines for a descriptor held in a field — and
`formal/hostmods/contextlib.mojo`'s own `nullcontext` is the case that says why
that question is not cheap.

## 1. What was measured, and what is now refused

Before this branch, on both architectures:

    class Suppressor:
        def __enter__(self): print('enter'); return self.tag
        def __exit__(self):  print('exit'); return True
    def main(n):
        with Suppressor() as v:
            print('body', v)
            raise ValueError('m')
        print('after')
        return 0

CPython prints `enter / body 7 / exit / after` and exits 0. This path printed
`enter / body 7 / exit` and exited **1**: the cleanup ran, so every visible line
matched, and the divergence sat in the status and in the statements after the
block. `__exit__`'s return value was dropped on the floor.

`model.struct_is_context_manager` now refuses a struct whose `__exit__` returns a
foldably truthy value, and `model.with_context_manager_defect` says so with a
sentence that names SUPPRESSION. `return True` and `return 1` are both refused —
the gate reads the folded VALUE, not the token, because in CPython `1` suppresses
exactly as `True` does.

## 2. What is still wrong, precisely

A **computed** return. The shape is the corpus's own:

    class Suppressor:
        var quiet: Int
        var tag: Int = 7
        var log: Int = 0
        def __enter__(self) -> Int: return self.tag
        def __exit__(self) -> Int: return self.quiet          # truthy?

This is `formal/hostmods/contextlib.mojo`'s `nullcontext` exactly: CPython's
`nullcontext(exit_result)` returns `exit_result`, and a truthy one suppresses.
Whether `self.quiet` is truthy depends on a CONSTRUCTOR ARGUMENT, so answering it
is constant propagation through a field across a call boundary — not a fold, and
not anything `_constructor_bindings` (which reads BINDINGS, not values) carries.

So this program still builds, still runs the cleanup, and still exits 1 where
CPython exits 0 when the manager was constructed with a truthy `exit_result`.

## 3. Why the obvious fix is the wrong one

Refusing every computed return would refuse `nullcontext` itself, whose three
CPython pairs are `test_formal_core_hostmods.py`'s `ctx` group and which 224 sites
of this repository's corpus reach through `tempfile`. That trades a wrong answer
in a case the corpus does not write for a refusal in every case it does — and a
refusal is not free either: it is a file that will not compile.

The narrower gate that IS in place keeps both: the falsy literal returns
(`return 0`, `return False`, `return None`, a bare `return`) and no return at all
still lower, so `formal/hostmods/tempfile.mojo`'s `TemporaryDirectory`
(`__exit__` returning `rmtree`'s entry count — a computed value, and a falsy one
in every case that matters) and `nullcontext` are untouched. That is why the gate
tests FOLDABILITY and not the spelling, and why this document exists: the honest
statement is "a foldably truthy return is refused; a computed return is not
decided", not "suppression is handled".

## 4. The exact next step

Three steps, in this order, and none of them is a signature change:

1. **the status word.** Suppression needs exactly one bit of runtime — "is an
   exception in flight" — and nothing else. It is also what
   `formal/build.py::_refuse_try_handlers`'s raiser set is approximating today
   from the SOURCE (`bugs/formal/FORMAL_a_try_handler_arm_is_still_never_emitted.md` §3
   measures that approximation as worth zero files, which is why the word has to
   be real rather than inferred).
2. **the resume edge.** `_flush_pending_finally` currently runs the clause and
   truncates the stack, with no value and no successor, in BOTH emitters. For a
   `with` it must instead leave the clause's value where the raise site can read
   it and branch to the statement after the block when it says "suppress". Both
   architectures change together, and the CFG's `_leaves_early` gains one
   successor — which is a fact the Lean side can then prove rather than assume.
3. **only then** does this document's case get decided, as a CONSEQUENCE: with a
   resume edge in place, a computed `__exit__` return is no longer a wrong answer
   (it is honoured), so the gate can be widened to accept everything rather than
   narrowed to fold it. Widening the gate is the last step and not the first, and
   doing it first is what would break `nullcontext`.

Steps 1 and 2 are the same work as
`FORMAL_a_context_manager_exit_cannot_take_cpythons_three_exception_words.md` §3,
which is the other half of the missing unwinder: that one needs an exception
VALUE to pass the three words, this one needs only the status and the resume, so
this one is the smaller of the two and is the one to build first.

## 5. The reproduce line

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_with.py \
        an_exit_returning_true_is_refused_as_a_suppression_it_cannot_perform \
        an_exit_returning_one_is_refused_for_the_same_reason \
        an_exit_returning_a_truthy_string_is_refused_for_the_same_reason \
        an_exit_returning_a_truthy_float_is_refused_for_the_same_reason \
        an_exit_returning_a_comparison_is_refused_for_the_same_reason \
        an_exit_returning_a_boolean_operator_is_refused_for_the_same_reason \
        an_exit_returning_a_select_is_refused_for_the_same_reason \
        an_exit_returning_a_bitwise_operator_is_refused_for_the_same_reason \
        an_exit_returning_len_of_a_literal_is_refused_for_the_same_reason \
        an_exit_returning_a_constant_remainder_is_refused_for_the_same_reason \
        an_exit_returning_a_non_empty_display_is_refused_for_the_same_reason \
        an_exit_returning_a_chained_comparison_is_refused_for_the_same_reason \
        an_exit_returning_a_float_select_is_refused_for_the_same_reason \
        an_exit_returning_a_boolean_over_a_float_is_refused_for_the_same_reason \
        an_exit_returning_false_still_runs_the_protocol \
        an_exit_returning_an_empty_string_still_runs_the_protocol \
        an_exit_returning_zero_point_zero_still_runs_the_protocol \
        an_exit_returning_len_of_the_empty_string_still_runs_the_protocol \
        an_exit_returning_a_false_comparison_still_runs_the_protocol \
        an_exit_returning_an_empty_display_still_runs_the_protocol \
        an_exit_returning_a_false_chained_comparison_still_runs_the_protocol

Every row name above is checked against `test_formal_with.py` before it was put
here (the 2026-10-18 merge of `work/formal408-docs` replaced six of them, which
had been named in prose by a spelling no test ever carried). §1's two refusals,
the two truthiness arms the 2026-10-07 update added, the fourteen expression arms
the three 2026-10-13 updates added, and §3's falsy boundary. The `nullcontext`
consumer that §3 is
about is `python3 tools/memslot.py --gb 8 --label t -- python3
test_formal_core_hostmods.py ctx` (three CPython pairs, both backends).