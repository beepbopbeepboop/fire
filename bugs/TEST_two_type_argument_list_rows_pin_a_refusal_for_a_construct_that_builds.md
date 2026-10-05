# Two `test_formal_run.py` rows pin a REFUSAL for `Box[Int, Int](7)`, which now builds — and the construct is ordinary Mojo

**Area:** TEST (`test_formal_run.py`'s type-argument-list rows) · **Status: OPEN,
pre-existing on `master`, measured on `work/formal27-1` 2026-10-04. Not fixed
here: it is outside that worker's claims.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
…
  FAIL  type_argument_list_without_any_frame: --backend=arm64 BUILT a construct
        that has no representation (expected a refusal naming 'compile-time
        explicit-parameter list'); the binary is the real answer here
  FAIL  no_tuple_index_sentence_about_a_type_argument_list: --backend=arm64 BUILT
        a construct that has no representation (expected a refusal that no longer
        says ['whose index is a tuple']); the binary is the real answer here
formal run: PASS=996 FAIL=2
```

and, to establish that the red is not the change under test rather than a
property of the branch, the same two rows on the branch's own base:

```console
$ git show HEAD:formal/build.py > formal/build.py     # (cp, not checkout)
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      type_argument_list_without_any_frame no_tuple_index_sentence_about_a_type_argument_list
  FAIL  type_argument_list_without_any_frame: --backend=arm64 BUILT a construct …
  FAIL  no_tuple_index_sentence_about_a_type_argument_list: --backend=arm64 BUILT …
formal run: PASS=36 FAIL=2
```

Both red on `HEAD:formal/build.py`, i.e. before anything on this branch.

## What the rows are

`test_formal_run.py:17815` (`type_argument_list_without_any_frame`) and
`:17895` (`no_tuple_index_sentence_about_a_type_argument_list`) both spell

```mojo
struct Box[T: AnyType, U: AnyType]:
    var v: Int

def main(n: Int) -> Int:
    var m = Box[Int, Int](7)
    return m.v
```

and pin the REFUSAL `"compile-time explicit-parameter list"` — the second with
`refuse_without:`, so it also pins that the old `"…whose index is a tuple"`
sentence stays gone. The program now BUILDS on both backends.

**And building it is the right answer**, which is what makes these rows stale
rather than the subject broken: `Box[Int, Int](7)` is a bracketed
SPECIALISATION of a struct this module declares, with two literal type
arguments and one positional value argument. That is ordinary Mojo, it is
`formal/monomorph.py`'s subject
(`bug:FORMAL_generic_monomorph_scope.md`), and it is the same shape
`formal/examples/` and the stdlib write. A refusal here would be
`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`'s
mirror image — a correct caller told the source is wrong.

**The rows immediately above them are still right**, and that is what says the
distinction is real rather than the refusal having gone away entirely:
`type_argument_list_on_a_struct_this_unit_declares` spells
`Triple[Int, s, False](5)` — a RUNTIME VALUE (`s`) in the bracket — and still
refuses, correctly, because a value cannot be a type argument. Two rows, two
answers, one construct.

## Why it is a defect rather than bookkeeping

`CLAUDE.md`'s `expect=` / stale-marker discipline is about a KNOWN failure
being recorded. This is the other half: **a test that asserts a property the
code deliberately stopped having**, which is a hole in the coverage dressed as
a check. It reports on every run, it is not declared anywhere, and a reader of
the log sees "BUILT a construct that has no representation" — a sentence about
a construct that has one. That is the false-diagnostic failure mode this
repository treats as worse than a crash.

## The exact next step

Re-point the two rows at what they were actually for. Their intent is legible
from their neighbours and is still worth pinning: **a type argument list must
not be read as a container subscript**, which is what
`no_tuple_index_sentence_about_a_type_argument_list`'s
`refuse_without:…:whose index is a tuple` half says and what
`TYPE_ARGUMENT_LIST_ABSENT_CASES`'s dict/list counter-cases
(`a_dict_key_tuple_holding_a_frame_is_still_a_store` and its three siblings)
already cover for containers. So:

1. drop the `refuse:` expectation from both rows and give each a
   build-and-RUN expectation against CPython instead — `Box[Int, Int](7).v`
   is `7`, which is the answer the specialised construction owes;
2. keep the `refuse_without:` half of the second row as a `refuse_without` on a
   case that IS still refused, or move it onto the
   `type_argument_list_on_a_struct_this_unit_declares` program, where a value
   in the bracket is still a refusal;
3. if the specialisation of a module-declared struct is genuinely meant to stay
   unsupported for a reason nobody has written down, then the fix is a REFUSAL
   in `formal/monomorph.py` and these rows are correct — but then
   `formal/examples/`'s corpus and the stdlib's `[…]` spellings have to agree
   with it, and nothing in `bugs/` claims that.

`test_formal_run.py` is a registered gate test, so this red is in the gate's
tally today and is not declared by any `expect=`.