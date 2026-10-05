# A comprehension's TARGET over a string-keyed dict is an integer, so `len(k)` refuses

**Status: NOT FIXED.** The STRIDE over a dict is right (a comprehension
generator asks `model.walk_stride` about its iterable — see
`bugs/FORMAL_fuzz_ledger.md` §3.10); what is missing is that a comprehension's
target does not ask `model.iterable_dict_key_kind`, so the name it binds
classifies as an int and the refusal about `len()` is false about the reader's
own source. **Pinned** as a `REFUSALS` row in `test_formal_value_model.py`
(`a_comprehension_target_over_a_string_keyed_dict_is_an_int`), so the honest
answer stays honest on both architectures until it is fixed.

## What was run, what was seen, what was expected

`python3 .tmp/probe.py` — the probe harness of `tools/formal_fuzz.py`
(`build`/`run`/`cpython_answer`), on both backends:

    def main() -> Int32:
        d = {"ab": 100, "cde": 200}
        ks = [k for k in d]
        for k in ks:
            print("n:", len(k))
        return 0

| | answer |
|---|---|
| CPython | `2` then `3` (the two key lengths), exit 0 |
| arm64 | **REFUSED**: `len(k) is len() of a value classified as 'int', and an integer has no length: there is no count to read at offset 0, and the word there is the integer itself.` |
| x86-64 | the same sentence |

Expected: `2` then `3` on both images, because the table's keys are strings and
the `for`-in walk over the SAME literal already answers it. That row is
`for_in_a_dict_of_strings_binds_a_string_target` in `test_formal_value_model.py`
and it passes on both architectures, so the two walks over one dict disagree
about what the key is.

This is a REFUSAL, so it is not a silent wrong answer — which is the only
reason it is filed separately rather than merged with §3.10's fix. It is filed
at all because the message is a claim about the program and the claim is false,
and §3.5 of the ledger is the class of findings that are about the messages.

## The exact next step

`model.iterable_dict_key_kind` is what binds a string target for `for k in d`.
Find the comprehension generator's target store and ask the same question about
`gen.iterable`:

- arm64: `_emit_compr_gen`, the `self._store_var(tnames[0], 0)` /
  `self._emit_for_unpack(ttree, …)` pair, ~40 lines below the `walk_stride`
  arm this session added;
- x86-64: `_emit_compr_gen`, the `self._store_var(tnames[0], Reg.RAX)` /
  `self._emit_for_unpack(tnames, …)` pair, at the same place.

The KIND is a `ValueKinds` fact rather than an emitter one, so the fix belongs
in whatever computes the comprehension's target kind (`ValueKinds` /
`formal/types.py`) rather than in the two emitters: emit nothing, add the rule
where the `for`-in target's kind is already derived, and the refusal disappears
on both machines at once. Then move the row out of `REFUSALS` into the
`comprehension_over_a_dict_*` group in `CASES` — as an ORACLE row, since
`len(k)` over string keys is a construct CPython can run verbatim.

**Do not fix it by teaching `len()` to guess.** `print()` guessing is what
`bugs/CODEGEN_dynamic_attribute_string_reads_as_pointer.md` and the
`print() cannot tell whether …` family are about, and the refusal exists
because a guess here prints an address as if it were text.

## Not the same bug

`{k: 1 for k in d}` over string keys builds, and `for k in e` over THAT result
also binds an int target — the same missing rule one step later, reached
through a comprehension-built pair blob rather than a literal. Fixing the
literal case will not fix this one; the rule has to be about the ITERABLE, not
about the container's spelling.
