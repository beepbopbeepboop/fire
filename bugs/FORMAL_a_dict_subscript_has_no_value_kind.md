# FORMAL_a_dict_subscript_has_no_value_kind: a dict SUBSCRIPT now has a value kind, gated on the key; the filed program needs `bytearray`, which has no representation at all

**Status: the capability this document is about has LANDED and is measured; the
program this document was filed with still does not build, for a reason that is
not this one, and the field spelling the sweep found stays refused on purpose.
Both of those are separate capabilities, and the second is filed.**

Found as the top row of `bugs/FORMAL_sweep_work_map_2026-10-02_repo-c.md` §4.1
(3 of 15 answerable files, one construct) and filed on 2026-10-02.

## What it was, and what it is now

`len(d[k])` was refused with "the source does not say what this operand holds"
for every `d`, and the refusal was TRUE: a dict's element word is written by a
STORE — the literal's own pair, or a subscript assignment — and nothing else
writes it. `ValueKinds.kind_of`'s `SubscriptExpr` arm read
`list_elem_kind(kind_of(base))`, which asks the dict for ONE element kind for the
whole table, so `{"a": 10, "b": "text"}` claimed nothing and every subscript of
it was unclassified.

**What landed** is the per-key answer, and the gate is the whole of it:

| | before | after |
|---|---|---|
| `d = {"text": [1,2,3]}; len(d["text"])` | refused | `3`, both architectures |
| `d = {"a": 10, "b": "text"}; print(d["a"])` | refused | `10`, both architectures |
| `d = {"s": "hi"}; printf("%s", d["s"])` | `hi` | `hi` (unchanged) |
| `d = {"a": [1]}; len(d["b"])` — key absent | refused | **refused** (the gate) |
| `d = {"a": [1]}; len(d[k])` — key is a name | refused | **refused** |
| `d = {"a": 1, "a": [2]}` — one key, two kinds | refused | **refused** |
| `d = {"a": [1]}` … then `d = 5` | refused | **refused** (tombstone) |
| `{str(i): [i] for i in range(3)}["1"]` | refused | **refused** |

Three pieces, in `formal/model.py`:

1. `dict_literal_key_value_kind(node, index)` — the shared reader. It answers
   only when `node` is a dict **literal**, `index` is a string or integer
   literal, and **the literal contains that key**; unanimity is over the pairs
   under that key, because a subscript is a key scan and its answer is one
   element word. That last clause is the gate: a missing key is CPython's
   `KeyError`, which this path cannot raise, and the word a key scan leaves
   behind is whatever the pair blob held — for a container value, address 0, so
   `len` of it is `LDR X0, [X0]` with X0 zero. That is the SIGSEGV
   `struct_field_kind`'s docstring records for the field spelling, and this
   document's next-step section demanded the gate be designed before the
   capability was written. It was, and it is the third row of the table above.
2. `ValueKinds._note_dict_init` — the evidence, recorded per name with
   `_ctor_calls`' tombstone discipline, because this map is flow-INsensitive and
   a name bound to a dict literal and then to something else has two homes.
   Identity (`is`), not equality: the scan runs twice over the same statements.
3. `_pair_value_kind` — a nested container literal is a blob, so
   `{"c": [1,2,3]}` says its value is a counted region. It is deliberately NOT
   an arm of `_kind_of_simple`, and the docstring says why: that function is also
   read by the module-global path (`global_slot_kind`), where a dict's values
   are classified WITHOUT any check that the key being subscripted is one of
   them. Widening it there would extend a plausible-wrong-number into a
   plausible-wrong-number-that-is-also-a-null-dereference across every dict
   global in the tree. Confined here, the nesting is available only where the
   write is evidenced.

**The `next step` this document listed was three pieces and two of them were
the wrong shape.** It asked for `declared_type_kind` to answer `dict[K, V]`
with `V`'s kind, and for `BLOB_TYPE_CTORS` to carry `bytearray`. Neither is
needed for the capability and neither would have been sound: the annotation
says what the TYPE is, and a dict element's word is written by a store — the
same premise-versus-value split `struct_field_kind` exists to keep apart, and
the same SIGSEGV it measured on both architectures when the annotation alone was
believed. The per-key literal reader is a narrower question with evidence behind
it, and the annotation route is still refused for the same reason it was before.

## What still does not build, and is not this capability

**`bytearray` has no representation on this path at all.** Measured:

```
$ cat .tmp/w/ba3.py
def main():
    var b = bytearray()
    printf("built %d\n", 1)
    return 0
$ python3 fire.py build --formal --no-prove -o ba3.bin .tmp/w/ba3.py
build: the image would bind 1 symbol(s) that nothing provides, so it could not
be loaded: bytearray. …  (Provider check: asked the C library (dlsym).)
```

So the program this document was filed with — `d: dict[str, bytearray] =
{"text": bytearray()}` — is TWO gaps, and this fix closes the one about the
subscript. The other is filed as
`bugs/FORMAL_bytearray_and_bytes_have_no_representation.md`.

## The field spelling, and why it stays refused

The sweep's three files are `len(self.sections["text"])` where
`self.sections: dict[str, bytearray]` is a **declared field**. That is refused,
and correctly: `S()` does not run `__init__` on this path (premise B2), so a
fresh instance's slot holds the class-level default, and a field with no default
is a word of zeros — so `len` of that subscript is a count read from address 0.
The refusal is unchanged, byte for byte, which is the assertion that the gate is
the gate.

Answering it soundly would need one more hook — the field's own default
initializer, so the key can be checked the way the local's is — and it would buy
**nothing for the corpus**, because the field in all three files has no default.
A dict field with a literal default (`var d: dict[str, List[Int]] = {"a": [1]}`)
is the shape that hook would serve and no file in the sweep spells it. The
missing thing there is not the kind: it is a dict FIELD with a value at all,
which is the module-global storage question
(`bugs/FORMAL_module_state_no_storage.md`).

## Tests

`test_formal_value_model.py`, which is the oracle suite for this area — its
expectations are derived by running the SAME text through CPython:

* `a_dict_subscript_is_the_kind_of_the_pair_under_that_key` **replaces**
  `a_dict_whose_values_disagree_is_refused`, and it is the interesting one: the
  old refusal was true about the old rule and FALSE about the program. A
  subscript is one element word, so `{"a": 10, "b": "text"}` says `d["a"]` is the
  10 and CPython agrees. Both architectures, checked against CPython.
* `a_dict_whose_one_key_holds_two_kinds_is_refused` — the gate, on the one shape
  where unanimity over a single key's pairs actually fails.
* `a_dict_subscript_of_a_key_the_literal_lacks_is_refused` and
  `a_dict_subscript_of_a_name_key_is_refused` — the other two rows of the gate,
  each refused identically on both backends (`run_refusal` requires the same
  message from each, which is the only instrument that can see a defect both
  backends share: they read one kind table).

`test_formal_run.py` needed two rows changed rather than added, and the reason is
this document's other bug: `comptime LIMIT = 3 + 4` was pinned as a REFUSAL and
is now materialized as 7, because `literal_default_word` folded with
`fold_literal_expr` instead of being a second, narrower classifier
(`bugs/FORMAL_a_negative_class_constant_is_not_a_literal.md`, deleted by the
commit that fixed it). Both rows now use `N + 4` with `N` a module-level
constant, which is the shape that is still refused — a value with a FREE NAME in
it, which the class body cannot resolve.