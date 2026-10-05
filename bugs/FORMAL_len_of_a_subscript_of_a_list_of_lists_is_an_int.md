# `len()` of a SUBSCRIPT of a list of lists is refused as "classified as 'int'"

**Status: NOT FIXED.** A kind-inference gap, not a lowering: the stride is right
(`model.walk_stride` reads the pair-ness of the container and a list of lists is
a list), and the ELEMENT read through the same subscript lowers correctly. Only
`len()` of the subscript is refused, and the message is false about the reader's
own source. **Pinned** as nothing yet — the corpus deliberately does not generate
it (§ "Why the corpus does not generate it" below), so this doc is the queue
entry.

## What was run, what was seen, what was expected

`python3 .tmp/probe.py`, both backends:

    def main() -> Int32:
        rows = [[1, 2], [3, 4]]
        inner = rows[0]
        print(len(inner))
        return 0

| | answer |
|---|---|
| CPython | `2`, exit 0 |
| arm64 | REFUSED: `len(inner) is len() of a value classified as 'int', and an integer has no length: there is no count to read at offset 0, and the word there is the integer itself.` |
| x86-64 | the same sentence |

**The element read is fine**, which is what makes this a kind question and not a
layout one — same subscript, same program shape:

    rows = [[1, 2], [3, 4]]
    inner = rows[0]
    v = inner[1]
    print(v)          # 2 on CPython, arm64 and x86-64

and `len(rows)` — the OUTER list — answers 2 on all three. So the table's own
count word is reachable and the subscript's result is a usable blob; what is
missing is the KIND of that blob, which `len()` is the only reader that insists
on.

## The exact next step

`formal/model.py`'s subscript element-kind rule. The analogous rule already
exists and is already used for dicts: a subscript's kind is "the kind of the
pair under that key", which is why `d["a"]` in a table whose values disagree
still has an answer (`test_formal_value_model.py`'s
`a_dict_subscript_is_the_kind_of_the_pair_under_that_key`). For a LIST there is
no pair under the index — the elements are the list's elements — so the rule that
is missing is "a list's element kind is ITSELF a container when the literal's
elements are containers", i.e. the list-of-lists case the blob layout nests and
the kind table flattens.

Concretely: find where a `SubscriptExpr` over a `ListExpr` gets its element kind
(`ValueKinds.is_list_value` and the `_expr_str_kind` chain it belongs to), and
give the LIST case the same "read the kind off the element" treatment the dict
case has. Both emitters ask the same question afterwards, so the fix lands on
both machines at once — which is the property `test_formal_value_model.py`
checks, and the reason this row belongs in that file rather than in
`test_formal_run.py`'s fixed-expectation table.

## Why the corpus does not generate it

`tools/formal_fuzz.py`'s `comp_nested` family builds exactly this shape — a list
of lists, a comprehension over it, a subscript of a row — and reads each row's
LENGTH through a local. It does not, deliberately:

- `print(len(row))` where `row = R[i]` is refused on both backends, so a family
  that emitted it would be a third refusals out of four statements and would
  measure the refusal rather than the construct;
- `print(R[i][j])` — the nested subscript straight into `print` — is refused too
  ("cannot tell whether SubscriptExpr is a string or a number"), which is why the
  family reads the element through a second local.

So the corpus produces the SHAPE and reads it through the two spellings that
answer, and this gap stays invisible to it by construction. That is the right
trade while the shape is genuinely answerable two other ways, and it is the wrong
trade the day it is not — which is what this doc is for.
