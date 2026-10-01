# FORMAL_zero_arg_init_not_inlined: `S()` on a struct whose `__init__` takes none

**Status: NOT FIXED, and deliberately left out of the declared-`__init__` inline
(`bugs/FORMAL_struct_construction_shapes.md`). This is the one remaining way
this path disagrees with the language about a constructor, and it is a SILENT
disagreement, which is the kind this project treats as the worst outcome
available. The next step is named here; it is not taken because the blast radius
is the whole stdlib and no test could tell a correct fix from a lucky one.**

## The disagreement

`formal/model.py`'s `struct_construction_plan` returns `CONSTRUCTION_DEFAULT` for
a construction with NO arguments, before it looks at `__init__` at all. So

```mojo
struct Z:
    var a: Int
    var b: Int

    def __init__(out self, a: Int = 8, b: Int = 9):
        self.a = a
        self.b = b

    def get(self, i: Int) -> Int:
        if i == 0:
            return self.a
        return self.b

def main(n: Int) -> Int:
    var z = Z()
    if z.get(0) == 8 and z.get(1) == 9:
        return 1
    return 0
```

builds, runs, and returns 0. **Measured: exit 0 on arm64 and on x86-64, where
the same program as a Python class returns 1 under `python3`.** Nothing is
refused, nothing is printed, and the program is the shape nearly every container
in the corpus is written in — so this is not a corner, it is the common case of
a construct that is silently mis-lowered, on both architectures.

The behaviour is deliberately PINNED rather than left to drift, by
`constr_init_a_zero_argument_construction_still_ignores_the_body` in
`test_formal_run.py` (which asserts the current 0, and says why in its comment)
and `constr_zero_arg_still_ignores_a_declared_init` (the same fact for a
constructor that takes arguments). Pinning a known-wrong answer is not the same
as accepting it silently: the answer is written down here, the test names the
doc, and the arbiter for lifting it is below.

It is premise (B2) in its last remaining form, and the constant now says so:
`FRAME_FIELD_BLOB_PREMISE_B2` is `"a zero-argument S() does not run __init__"`,
where before the `__init__` inline it read `"S() does not run __init__"` and was
a claim about every construction.

## Why it is not the same fix, one clause further

`S(args)` is a call, and the argument COUNT selects the overload. `S()` is a
call with no arguments, so the count selects nothing: an overload with zero
required parameters would match, and in the stdlib there are **102**
`def __init__(out self):` spellings — so 102 constructors whose bodies this path
would have to decide what to do with, and no count to select them by if two of
them existed.

Which is the honest reason the change was scoped out, and it is a *decision*
rather than a difficulty: lifting it would mean either

* running the body whenever a zero-required overload exists — a behaviour change
  across the whole corpus, unmeasurable from here, because **no existing test
  distinguishes a correct zero-arg lowering from the current zeros**; or
* refusing `S()` on such a struct — the honest direction, and it would turn 102
  currently-building constructors into refusals, which is a large regression in
  coverage in exchange for removing a wrongness that is, for every one of those
  102, invisible in the output.

Neither is a decision one construct's owner should make unilaterally, which is
why the gap is a document rather than a branch.

## The next step, precisely

1. **A test that can tell the two apart, before any lowering.** Two cases on the
   same program, and the second is the one that is missing:
   * `S()` with a **required**-parameter `__init__` — still premise (B2), still
     the class defaults. This exists and passes
     (`constr_zero_arg_still_ignores_a_declared_init`).
   * `S()` with a **zero-required** `__init__` whose body stores a literal — the
     language's answer is that literal, this path's is 0, and the expected exit
     status has to be the language's. This does not exist, and adding it FAILS on
     the current tree, which is what makes it the right first commit: it turns
     the gap from a note into a red.
2. **Then choose (a) or (b) above, with the red test as the arbiter.** (b) is
   the direction the rest of this backend takes — an honest refusal beats a wrong
   image — and (a) is the one that closes it.
3. **Watch the three doors.** Running a constructor that this path previously did
   not run puts a container in a slot for the first time in a `S()` where the
   argument list is empty. Premise (B1) is about EXECUTED method bodies and does
   not cover it, and `frame_field_premise_note` now names both reasons for an
   `__init__` container write (confinement, or the constructor not running at
   all) — a third reason would have to be added here rather than argued around.
   `self.items = List[Self.T]()` is in a large share of those 102, so the blast
   radius is not hypothetical.
