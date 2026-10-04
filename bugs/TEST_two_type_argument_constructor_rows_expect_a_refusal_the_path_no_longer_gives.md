# Two `refuse:` rows for a bracketed type-argument CONSTRUCT are stale: the backend answers it correctly now

**Area:** `test_formal_run.py`'s `type_argument_list_without_any_frame` and
`TYPE_ARGUMENT_LIST_ABSENT_CASES`'s `no_tuple_index_sentence_about_a_type_argument_list`.
NOT fixed here — the construct belongs to another claim's doc (see "Whose") and
this is a stale-TEST report, not a backend gap. **Status: OPEN, measured
2026-10-05 on `work/formal27-2` at `ccb157ed`, pre-existing on this tree.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py
...
  FAIL  type_argument_list_without_any_frame: --backend=arm64 BUILT a construct
        that has no representation (expected a refusal naming 'compile-time
        explicit-parameter list'); the binary is the real answer here
  FAIL  no_tuple_index_sentence_about_a_type_argument_list: --backend=arm64
        BUILT a construct that has no representation (expected a refusal that
        no longer says ['whose index is a tuple']); the binary is the real
        answer here

formal run: PASS=998 FAIL=4
```

Two of the four failures in that run are mine and are fixed in the same commit
(`constr_refuse_an_undeclared_base_by_name` and
`constr_an_exception_carries_its_message`, both of which carried a `try` around
a `raise` and now meet a refusal that fires earlier). **These two are not, and
they are not caused by anything I changed** — neither program contains a `try`,
a `raise` inside a `try`, or an f-string.

## What the program does now

Both rows are the same source, and it is a GENERIC STRUCT constructed with an
explicit type argument list:

```python
struct Box[T: AnyType, U: AnyType]:
    var v: Int

def main(n: Int) -> Int:
    var m = Box[Int, Int](7)
    return m.v
```

```console
$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=$A -o .tmp/box.$A \
      .tmp/box.mojo; ./.tmp/box.$A; echo "  exit=$?"; done
Built: .tmp/box.arm64  [arm64/macho]
  exit=7
Built: .tmp/box.x86_64  [x86_64/macho]
  exit=7
```

**7 is CPython's answer** for that program (`m.v` is 7), so what the rows are
refusing is a construct this path now computes correctly on BOTH machines. The
refusal they pin ("compile-time explicit-parameter list") landed with the work
that made a bracketed type application distinguishable from a container
subscript, when `Box[Int, Int](7)` was read as a two-dimensional index into
something. That reading is gone.

The second row is the ANTI-ROT half of the same idea and is stale for the same
reason: `refuse_without:compile-time explicit-parameter list:whose index is a
tuple` asserts the build FAILS and does not say "whose index is a tuple". With
the construct answered, there is nothing to be stale about the sentence — the
program builds and the case fails on the missing refusal.

## Why the rows cannot simply be deleted, and what they should become

The surrounding comment block is explicit that these two rows are load-bearing
in a way their neighbours are not: `no_tuple_index_sentence_about_a_type_
argument_list` is one of two sentences pinned as "false about this construct",
and the block above them says a fix that appends a correct clause beside an
incorrect one leaves every `refuse:` green while the reader is still misdirected.
Deleting the pair removes that coverage silently.

So the repair is to re-point them at what the construct is now, in the same
spirit as the sibling rows they were written beside:

* `type_argument_list_without_any_frame` becomes a differential case —
  `Box[Int, Int](7)` returning 7 against CPython — because the interesting
  property is now "a type application is not a container subscript", which a
  refusal can no longer demonstrate;
* `no_tuple_index_sentence_about_a_type_argument_list` keeps its
  `refuse_without:` shape pointed at a program that IS still refused, or is
  deleted together with its neighbour above it
  (`no_container_store_sentence_about_a_type_argument_list`, which passes and
  covers the same two sentences for the `Pointer[Int, s]` spelling).

## Whose

`bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
is claimed (`formal27-1`) and is the doc that describes the change which made
these rows stale — it is where the "a bare template call's type arguments are
inferrable now" measurement belongs, and this report is the same measurement
seen from the test side. `bugs/FORMAL_a_value_typed_bracket_argument_is_refused_
as_a_subscript.md` (also `formal27-1`) is the classification this tree now
applies. Neither is mine to edit.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      type_argument_list_without_any_frame no_tuple_index_sentence_about_a_type_argument_list
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/box.bin <the program above> && ./.tmp/box.bin
$ echo $?     # 7, on both backends
```
