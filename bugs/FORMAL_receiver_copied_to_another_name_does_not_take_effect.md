# FORMAL_receiver_copied_to_another_name_does_not_take_effect: `self = other` builds, runs, and the copy never reaches the caller

**Status: OPEN, pre-existing, and found while fixing
`bugs/FORMAL_receiver_rebound_to_a_word.md` (2026-10-01), whose fix has to
DECIDE about this shape and this doc is why the decision is narrow.** It is
deliberately *allowed* by that fix — correctly, because a same-type copy is not
the dropped store that doc is about — and what is left is a different wrong
answer that the same source line produces.

This is a **wrong answer, not a refusal**, and it is silent on both
architectures.

## What I ran

```mojo
struct R:
    var a: Int
    var b: Int
    def copy_from(out self, other: Self):
        self = other

def main(n):
    var r = R()
    var q = R()
    r.a = 1
    q.a = 2
    r.copy_from(q)
    printf("a=%d b=%d", r.a, q.a)
    return 0
```

## What I saw

| | |
|---|---|
| CPython | `a=2 b=2` |
| arm64 | `a=1 b=2` |
| x86-64 | `a=1 b=2` |

`r` still holds what it held before the call. Measured identical with the
receiver-rebind fix reverse-applied, so it is pre-existing and not something
that fix introduced.

## Why it is NOT the same bug, and why they are one document's worth of work

`FORMAL_receiver_rebound_to_a_word.md` is about `self = <a word>`: a rebinding
that points the method at a **different** word, so the write misses the caller
outright and every later field read is a load at `base + 8·slot` with `base`
being that word. That is now refused, by name, from
`model.receiver_rebound_from_a_word_refusal`.

`self = other` is a rebinding to a word of the **same** layout — the parameter's
own frame address — so the arithmetic in every later read is correct and the
load lands in the right place. It is refused by nothing, and the caller's
`r` is never updated. The difference is exactly the one the message in the
fixed doc draws: a copy leaves the address alone and drops the update; a
repoint moves the address and corrupts the reads. One is a dropped store and
the other is a load from a word.

**So the two want different answers, and this doc is the second one.** Refusing
`self = other` would be refusing a construct that is correct in a real and
frequent shape — the idiomatic `self = other` in a copy constructor, which
stdlib has — over a defect that has a narrower fix. That is why the fix for
the first doc allows this shape and this doc exists to say what is still wrong
about it.

## Why it is not fixed by writing the caller's word back

The obvious fix is the same shape as
`FORMAL_one_field_struct_mutating_method_is_a_no_op`'s: have the method return
the new receiver and have the call site store it. That is a real ABI change
for every method, and it is the wrong move **here** for a reason that is worth
stating because the two bugs look alike from a distance:

* That doc is about a **one-field** struct, where the receiver IS the field and
  so there is exactly one word to write back.
* This is a **multi-field** struct, where the receiver is an ADDRESS of a frame
  the CALLER owns. The method does not own that frame and cannot return "the
  new receiver" for it — there is no new one. The correct lowering is to have
  the call site COPY the callee's frame contents into the caller's frame after
  the call, which is a different thing from returning a word and is a
  statement-copy ABI rather than a return-value one.

So the two need two different lowerings, and that is the reason they are two
docs rather than one fix with two test rows.

## The next step

**Decide the direction before writing anything**, because both are real work
and they differ in what they cost:

1. **A frame-copy after the call.** The call site already knows the receiver is
   a frame of `R`; after the call it copies each slot of the callee's frame
   into its own. This is faithful, it needs no return-value convention, and it
   composes with the `out self` convention the rest of this path already uses
   for field stores. It is the right answer for a multi-field struct.
2. **Refuse it, naming the copy.** Cheap, honest, and it costs real coverage:
   `self = other` is idiomatic and appears in stdlib.

Recommendation: (1), and the reason is that the by-reference receiver
(`bugs/FORMAL_wide_receiver_by_reference.md`) is already a statement that "the
caller owns the frame", and a copy that does not propagate is that design
incomplete rather than a new problem. (2) is the fallback if (1) turns out to
need a frame-copy ABI that is larger than the shape is worth — and the
measurement that decides it is how many stdlib files use the shape, which is a
sweep and therefore not a worker's.

**What must be measured first either way:** whether any file in the corpus
actually relies on `self = other` taking effect, or only on it compiling. The
second needs no fix at all if nothing depends on it — and "compiles" is the only
thing this path currently promises, so it is a real possibility that the honest
answer is (2) plus a doc saying the shape is compile-only.

## Verified, and what is not

* Reproduced on this tree, arm64 and x86-64, `a=1 b=2` where CPython says
  `a=2 b=2`.
* Reproduced **identically on the base** with the receiver-rebind fix
  reverse-applied, so it is pre-existing.
* Confirmed the receiver-rebind fix ALLOWS this shape (it builds and runs),
  which is the intended scope of that fix and the reason this is a separate
  question rather than a regression from it.
* **NOT measured: how many stdlib files use `self = other` inside a method.**
  That is the number that decides (1) against (2), and it needs a sweep.
