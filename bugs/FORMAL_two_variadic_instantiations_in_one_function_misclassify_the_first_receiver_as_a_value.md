# FORMAL_two_variadic_instantiations_in_one_function_misclassify_the_first_receiver_as_a_value: `p.size()` is refused as a method call on a value once a second `Pair[...]()` joins the function

**Status: open, both backends, and pinned by NO row.** Found 2026-10-13 on
`work/merge-qwen1` while merging `work/formal183-docs` (the bare-literal
comptime value parameter) and fixing forward the row that used to pin the
staged refusal which hid this: `test_formal_run.py`'s
`comptime_binding_reading_a_variadic_parameter_answers_the_true_count` (named
`…_is_unreachable_behind_the_tuple_index_refusal` before the fix).

## What I ran

```mojo
struct Pair[T: AnyType, *values: T]:
    comptime length = len(Self.values)

    def size(self) -> Int:
        return Self.length

def main(n):
    var p = Pair[Int, 1]()
    var q = Pair[Int, 5, 6]()
    printf("len=%d %d", p.size(), q.size())
    return 0
```

```sh
$ for A in arm64 x86_64; do python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove --backend=$A \
    -o .tmp/two.$A .tmp/two.mojo; done
```

CPython computes `1 2` (p's values `(1,)` have length 1, q's `(5, 6)` length
2).

## What was seen

Both backends refuse identically at `p.size()` — the FIRST receiver, not the
second:

```
build: p.size() is a method call on a value, and this backend lowers only
append, clear, close, write (on a file descriptor) and the string methods
count, endswith, find, lstrip, startswith — the receiver is a name on this
path, and 'size' is not one of those methods of those receivers, so adding
it to either table would be a guess about what it means on 'int'. Refused
rather than emitted as a call to a symbol spelled 'p.size', which is what
this used to do: the image built and then died in the loader
```

## The boundary of it

* ONE instantiation of the same shape in one function builds on both
  backends and answers the true count: `var p = Pair[Int, 7, 8, 9]()` alone
  prints `len=3`, and 1 value -> 1, 2 -> 2, 3 -> 3, each CPython's answer.
  That is the fixed row above, which is the whole of what the corpus pins.
* It is NEW as of 2026-10-13, and it arrived with the value-parameter work
  (`work/formal183-docs`, merged into `work/merge-qwen1`): a bare literal is
  a spelling when the declaration says the position is a value, and that work
  lowered the variadic CONSTRUCTION. Measured on `ef6d1c8a` (before that
  merge), ANY program containing such a call was refused at the construction
  itself — `Pair[Int, 1] is a subscript whose index is a tuple` — so this
  defect sat behind that refusal and was never exercised. The 183 merge
  lowered the single-instantiation construction and exposed the
  two-instantiation case with it.

## Where to look

The holder/binding classification of `p` while the same function holds TWO
instantiations of the same template with different variadic tuples. One
instantiation classifies `p` as a struct holder; the second instantiation
`q` makes the walk classify `p` as a plain value, and the method table is
then consulted as if on `int`. The prime suspect is a name -> instantiation
mapping keyed on the BASE name: two mangled instantiations of one `Pair` in
one function, and a walk that answers "which instantiation is this `p`?" by
the base name sees two answers where the declaration needs one.

## Next step

Reproduce with the two commands above; read the holder walk over the two
`VarDecl`s in `main` and check how the mangled-instantiation rewrite names
the two `Pair` calls — the classification must give each `VarDecl` its own
home, not one per base name. When the fix lands, the row to add is the
fixed row's shape with two instantiations (`len=1 2`, both backends).
