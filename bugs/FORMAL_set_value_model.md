# A set is a LIST here: insertion order, no hashing, and `for x in s` disagrees with CPython

> **Steps 14a-14e landed (2026-11-06).** The set runtime work is done; what remains below
> (hash-order iteration, `print(set)`) is a documented model choice, not a gap.

> **Status 2026-11-05:** the compile-time dedup this file's table calls "fixed"
> had been LOST in the `formal/model/` package split (commit `1d40572ed` landed
> against the old single `formal/model.py`); it is re-landed
> (`model.set_literal_distinct_elements`, both emitters), measured:
> `len({1, 1, 2, 3, 3})` is 3 on arm64 and x86-64. The run-time half (a name, a
> call, a comprehension) is still open (steps 14b-14d).

> 
> **Status 2026-11-05 (step-14a):** the compile-time set-literal dedup for word-canonical elements was lost in the `formal/model/` package split (it lived in the old single `formal/model.py`) and is re-landed in `formal/model/layout.py` (`set_literal_word_key`, `set_literal_distinct_elements`) and wired in both codegens.  
> **Status 2026-11-06 (steps 14c-14e):** `set.add(x)` (`_emit_list_append(distinct=True)`, scan before the capacity guard; `_scan_list_caps` counts `add` sites like `append`) and set COMPREHENSION dedup (`_compr_append_elem(distinct=True)`; container elements refused with `set_comprehension_element_refusal`) are on both backends; `len({x % 2 for x in range(6)})` is 2. A user struct's own `add` still runs (measured: exit 2); `add` on a list is refused. The compile-time literal dedup now carries the append capacity to its replacement list (`_emit_deduped_set`). **Order is pinned as first-occurrence insertion order** and `KNOWN_DIVERGENCES['set_order']` stays: CPython's order for strings is per-process random and for ints needs the full CPython table, a different representation. `--mix sets` now draws literals with a repeat (about 30%).
> **Status 2026-11-05 (step-14b):** runtime dedup added for set literals with non-canonical elements via linear scan on both backends (`_emit_set_literal`, `_emit_set_contains` on x86-64). Elements with unword-equalable kinds (floats, computed/non-literal strings, kind None) are refused with `set_runtime_element_refusal`. Mixed literals and names deduplicate at runtime with first-occurrence order preserved.

## Status 2026-10-12 (`work/formal314-docs`): ONE DISAGREEMENT THIS FILE CALLED "AGREED" WAS REAL, AND THE WORD-CANONICAL HALF IS FIXED

**This file's table said `len(s)` was "the element count" on all three engines
and that `for x in s` was "the one disagreement". The second half of that was
FALSE.** A set's elements are DISTINCT in CPython, and this path lowered a set
literal as a plain list with the repeats KEPT, so the count word was not the
element count. Measured on this tree, before the fix, on BOTH backends:

    s = {1, 1, 2, 3, 3};  len(s)   ->  5 here, 3 in CPython
    s = {x, x, 2} (x = 7); len(s)   ->  3 here, 2 in CPython

and a walk summed 10 where CPython sums 6. The fuzzer could not see it because
`--mix sets` builds its literal with `rng.sample(range(1, 30), n)`, which
cannot draw a repeat, and because the `set_order` row forgives every
divergence in a program that walks a set.

**What is fixed, on both backends:** a set LITERAL whose elements all have a
word the model already treats as canonical (`CANONICAL_ELEM_TYPES`: an
`IntLiteral`, a `BoolLiteral`, a `StringLiteral`) is deduplicated at COMPILE
time by `formal/model.py::set_literal_distinct_elements`, before it is lowered
as a list. A string's word is its interned address, so the comparison is a
WORD comparison and two equal texts dedup. Pinned by three cases in
`test_formal_container_methods.py`'s `set` group, run differentially against
CPython on both architectures: `s_len_dups`, `s_walk_dups`,
`s_len_dups_str`.

**What is NOT fixed, and it needs a set RUNTIME rather than a compile-time
pass:** a set literal with an element whose word the model cannot know here (a
name, a call, a subscript) and a set COMPREHENSION both still lower with their
repeats, so `{x, x, 2}` still reports 3. Establishing distinctness for a
run-time value needs a hash or a scan, and x86-64 has no set emitter at all
(`set_union_refusal`), so the durable fix is a set runtime on both backends —
a "run-time-length container" capability. Until then the honest statement is: a
set literal is a list of the DISTINCT words it was written with.

---

**Status: NOT A BUG — this is the value model, and it is the document
`tools/formal_fuzz.py`'s `KNOWN_DIVERGENCES['set_order']` row names.** The row
was added by the fuzz-5 sweep in the same session that added `--mix sets`,
because a corpus that could not produce a set could not notice the day this
changed — which is the only moment the row is for, and the same argument
`bugs/FORMAL_string_value_model.md` makes for `s[i]`.

## What the model is, in the one line that states it

`formal/model.py`'s blob-layout comment, immediately above `BLOB_HEADER_BYTES`:

    # A list/tuple is a blob:  [count:i64][elem0][elem1]…   (8-byte slots)
    # A set lowers as a list. A dict is a PAIR blob:

That is the whole of it. A set literal is a list literal with distinct words:
no hash, no bucket array, no probe sequence, no load factor, and no resize. So:

| operation | CPython | this path | why |
|---|---|---|---|
| `len(s)` | the element count | the element count | the count word — of the DISTINCT elements: at compile time for word-canonical literals, by a run-time word scan for names, `.add` and set comprehensions (steps 14a-14d) |
| `x in s` | a hash probe | a linear scan | same answer, different cost |
| `s.add(x)` | insert if absent | the same (step 14c) | `BUILTIN_VALUE_METHODS["add"]`: a word scan (`_emit_set_contains`) then the `append` store and its capacity guard; the receiver must be a name/literal known to be a set, else `set_add_receiver_refusal` |
| `for x in s` | HASH order | **INSERTION order** | the one disagreement |
| `print(s)` | `{3, 1, 2}` | refused | a set prints in CPython's hash order, which is not this path's insertion order |

## The measurement

    def main() -> Int32:
        s = {3, 1, 2}
        for x in s:
            print(x)
        return 0

| | answer | exit |
|---|---|---|
| CPython | `1` `2` `3` | 0 |
| arm64 | `3` `1` `2` | 0 |
| x86-64 | `3` `1` `2` | 0 |

The order is insertion order on both backends, which is the blob's order. It is
deterministic, so it is not a miscompile — it is a different value model, and
the corpus's job is to keep it visible rather than to be surprised by it.

**Note what does NOT disagree**, because a set whose model is wrong in three
places would be a much bigger statement than one that is wrong in one:
`len({3, 1, 2})` is `3` on all three, and `1 in s` / `9 in s` are `True` /
`False` on all three. The `set_len` and `set_in` families in `--mix sets` are
there to keep measuring those two, and the `set_iter` family is there to keep
measuring the third.

## What CPython's order actually is, so the row's claim is checkable

CPython iterates a set in the order its table's slots come out, which for a
`set` of small non-negative integers is `hash(v) % table_size` — so it is
ASCENDING for `{1..8}` (table size 8) and scrambled above that. The corpus
draws its elements from `range(1, 30)` and inserts them in the sampled order,
so most generated tables disagree and the `set_order` row fires. A table whose
CPython order happens to equal its insertion order agrees by accident, which is
why a sweep of `sets` reports a mix of `KNOWN:set_order` and `match` rather
than a clean column of one or the other.

## Why the neutraliser rewrites the LITERAL and not the walk

`NEUTRALISERS['set_order']` turns `S = {3, 1, 2}` into `S = [3, 1, 2]` and
leaves `for x in S:` alone. A walk over a list is insertion-ordered on both
engines, so the rewritten program agrees with CPython and the disagreement is
attributed to the set-ness rather than to anything else in the program. Deleting
the walk instead would take the program's control flow with it, and
`tools/formal_fuzz.py`'s docstring is explicit that a neutraliser which changes
the shape teaches nothing.

The regex distinguishes a set literal from a dict literal by the absence of a
`:`, because both are `= {…}` textually and a neutraliser that rewrote a dict
literal into a list would take every dict subscript in the program down with it.

## If this ever stops being true

Delete the `set_order` row in the same commit that changes the model, and say
here what the new order is. A row naming a construct that is now RIGHT forgives
the next disagreement that happens to contain it — that is the whole reason
`KNOWN_DIVERGENCES` is a different table from `MIX_MUST_GENERATE`, and the same
reason `str_subscript`'s row is a claim rather than a suppression.
