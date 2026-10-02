# FORMAL_one_field_struct_field_stored_in_a_zero_arg_init_reads_as_zero

**Status: found, NOT fixed, and it is a WRONG ANSWER rather than a refusal.**
Found from the x86-64 sweep slice (`sweep:x86-a`), while writing cases for
`bugs/FORMAL_sweep_work_map_2026-10-02_x86-a.md` and looking for constructs the
two backends answer differently. It is not x86-specific: **both architectures
produce the same wrong number**, which is why it sat here unnoticed rather than
in the parity suite.

## The measurement

Four sources, all of the same shape — a field assigned in `__init__`, read by
another method — built with `--formal --no-prove` on **both** backends and run.
The expected value is what CPython computes for the same text.

| # | source | expected | arm64 | x86-64 |
|---|---|---|---|---|
| 1 | **one** field, `__init__(self)` with no parameters, read in a method | 20 | **0** | **0** |
| 2 | **two** fields, same `__init__`, both read in the method | 203 | 203 | 203 |
| 3 | one field, `__init__(self, k: Int)`, read in a method | 20 | 20 | 20 |
| 4 | one field, zero-arg `__init__`, read from `main` as `c.n` | 20 | **0** | **0** |

```mojo
class C:                                  # row 1
    def __init__(self):
        self.n = 20
    def get(self):
        return self.n

def main(n: Int) -> Int:
    var c = C()
    return c.get()                        # 0, not 20
```

Row 2 is the same class with a second field (`self.m = 3`, read as
`self.n * 10 + self.m`) and it answers 203. Row 3 is the same class with a
parameterised constructor and it answers 20. **Three facts, and together they
localise it: the field store is the problem only when the struct has exactly one
field AND `__init__` takes no arguments.**

Two more rows that separate "the read" from "the arithmetic", both arm64 and
x86-64 identical:

| source | expected | both backends |
|---|---|---|
| `self.n = 20` in `__init__`; method stores `self.n = 7` then `return self.n` | 7 | 7 — correct |
| `self.n = 20` in `__init__`; method reads into a local `t = self.n`, `return t` | 20 | **0** |
| `self.n = 20` in `__init__`; `return self.n + 0` | 20 | **0** |

So a method that STORES the field itself sees its own value (the store path is
fine); only a store made by the inlined zero-argument constructor is lost. The
read side is not at fault — the read is reading a slot that holds 0.

Also measured, and both correct, so they are ruled out as the mechanism:
`__init__(self, k: Int)` with `self.n = k` (row 3), a **tuple** store
`self.p, self.q = 3, 4` in a zero-arg `__init__` read back as 34, and a two-scalar
store `self.n = 20; self.m = 3` read back as 203.

## Why it is worth a document rather than a line in a work map

A wrong number is the outcome this project treats as worst: nothing is refused,
nothing is printed, the exit status is a plausible small integer, and the two
backends AGREE — so no parity suite, no `refuse:` row and no
`test_runtime_diff.py`-style engine diff can see it. `test_formal_run.py` has
`BOTH_ARCH_CASES` rows that read fields stored by a zero-arg `__init__`
(`both_arch_tuple_store_to_fields_in_init` and its two siblings) and they pass —
because those constructors store through a **tuple** assignment, which is the
one spelling that works.

The reason a one-field struct is a special case is already written down in the
tree: `bugs/FORMAL_method_param_field_access.md` quotes the rule that "a field is
lowered three ways and which one applies is decided by the BINDING of the base,
not by a type: **a one-field struct's receiver IS its field**, a multi-field
struct's receiver is the address of a frame, and an ordinary word is an integer",
and `struct_is_framed` is False for one-field structs. So the two working rows
above are the *framed* layout — a frame address plus a slot index — and the two
broken rows are the one where the receiver word IS the value.

## The exact next step

Not yet located, and the next worker should not have to re-derive the narrowing
above. What is known:

1. The loss is in the **zero-argument constructor's inlined body**, not in the
   field store machinery: `formal/model.py`'s `init_body_stores` is what runs a
   `__init__` with no required parameter at the construction site (see
   `bugs/FORMAL_struct_construction_shapes.md` for that inline, and
   `bugs/FORMAL_assigned_type_evidence_unreachable_after_zero_arg_init.md` for
   the evidence half of the same pass). A method that stores the same field
   works, so the difference is the inline.
2. It is specific to the **one-field layout**, where the receiver is the value
   rather than a frame address. The smallest question to answer first: does the
   inlined body write to the ctor temp that the *callee* reads, or does it write
   to a frame slot that only the multi-field layout has? `struct_is_framed`
   returning False for one field is where the two paths must diverge, and a
   store emitted for the framed layout would land nowhere at all in the other.
3. The cheapest confirmation: build row 1 with `--dump-full`-style inspection or
   by reading the emitted stores for `C.__init__` inlined into `main`, and check
   whether a store to the ctor temp is present at all. One build.

Whatever the cause, **the fix has to keep the three working rows working**: the
same pass already refuses a nested-frame construction in a constructor body and
has a zero-argument path for evidence; a change that de-inlines the body to fix
this would trade a wrong answer for a wall of refusals.

## The case that keeps it from coming back

A **positive** case, on both backends, with a constant that is not 0 — the
existing `BOTH_ARCH_CASES` rows cannot catch this because a case whose expected
answer is 0 passes on the broken lowering. `test_formal_x86_64_parity.py` is the
better home still: it compares against CPython's stdout for the same text rather
than a hand-written constant, which is the property that makes the oracle
trustworthy when the answer is 0.

```mojo
class C:
    def __init__(self):
        self.n = 20
    def get(self):
        return self.n
```

with the CPython source returning 20 and the Mojo source returning
`printf("%d", self.n)`. Two fields and a parameterised constructor should be in
the same case, so a fix that special-cases one of them cannot pass.