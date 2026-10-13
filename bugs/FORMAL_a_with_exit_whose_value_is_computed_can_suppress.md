# A `__exit__` whose RETURN VALUE is computed can still suppress, and the gate
# that catches the foldable half cannot see this one

**Area:** FORMAL, context managers. Claim `project:with-statements`, measured
2026-10-05 on `work/formal56-with-statements`. **OPEN, and deliberately left
open by a fix in the same commit that created it.** The wrong answer this
project found — a suppressing `__exit__` whose value the protocol dropped — is
now REFUSED whenever the build can fold the value. This is the half it cannot
fold, stated rather than hidden, because the alternative was refusing a host
module the corpus depends on.

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
`an_exit_returning_zero_point_zero_still_runs_the_protocol`). **§2's computed
case is untouched and is still the whole of what is left.**



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
   from the SOURCE (`bugs/FORMAL_a_try_handler_arm_is_still_never_emitted.md` §3
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
        an_exit_returning_false_still_runs_the_protocol

§1's two refusals and §3's falsy boundary. The `nullcontext` consumer that §3 is
about is `python3 tools/memslot.py --gb 8 --label t -- python3
test_formal_core_hostmods.py ctx` (three CPython pairs, both backends).