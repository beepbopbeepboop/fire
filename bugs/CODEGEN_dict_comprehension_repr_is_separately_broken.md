# CODEGEN: a dict comprehension's repr is broken three ways, independently of its clause count

**State: defect 2 FIXED 2026-10-02 and defect 3's ADDRESS key removed (it was
ASLR-varied, which is worse than a stable wrong answer); defects 1 and 3's
remaining repr wrongness are both now KNOWN to be one missing per-slot key-kind
discriminator, in `_DictSlot.keykind`. See the Status section at the end — read
it before working on this, because it says the fix is one mechanism and not
three repr patches.** Found 2026-10-01 while fixing
`CODEGEN_set_dict_comprehension_multi_clause_dropped.md`, whose repro used a
tuple key and so tripped these too. Deliberately left as its own doc: all three
are single-clause-reproducible, none is about how many `for` clauses the
comprehension has, and fixing them needs a different mechanism (the dict's
per-slot kind table) than that fix did.

## What I ran and what I saw

Three separate programs, each on its own, all `python3 fire.py --jit`-style
compiled runs against CPython's text.

### 1. An int key is stringified

    def main():
        print({i: 1 for i in range(3)})

| | CPython | compiled |
|---|---|---|
| | `{0: 1, 1: 1, 2: 1}` | `{'0': 1, '1': 1, '2': 1}` |

### 2. A 0 value renders as `None`

    def main():
        print({i: i for i in range(2)})

| | CPython | compiled |
|---|---|---|
| | `{0: 0, 1: 1}` | `{'0': None, '1': 1}` |

This is the generic dict repr's None-sentinel heuristic reading a raw 0 slot —
the same mechanism as `_list_repr_fn`'s, and the reason a dict comprehension
cannot be pinned by its repr: with the key stringified the two bugs share one
line of output, so a repr-based test cannot tell "key wrong" from "value wrong".

### 3. A tuple key prints as a heap address

    def main():
        pairs = [(0, 0), (0, 1), (1, 0), (1, 1)]
        print({k: 1 for k in pairs})

| | CPython | compiled |
|---|---|---|
| | `{(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 1}` | `{'ؙ\x08\x05\x01': 1, '\x18�\x08\x05\x01': 1, ...}` |

The key is the tuple's `MojoList *` printed as a decimal, **different every
run** (ASLR). This is the class `bugs/CODEGEN_noshim_dumpfull_preexisting_
divergence.md` tracks as the "erased `_slit` string pool reference — a raw heap
address baked into the generated C as a decimal literal" symptom, and the
reason it is an ASLR-dependent wrong answer rather than a merely ugly one.

Note this one is not specific to comprehensions: `{k: 1 for k in pairs}` is a
single-clause comprehension, but the underlying cause is the dict KEY path
(`_char_to_cstr` on a non-`char *` key), so a dict literal with a tuple key
is worth checking too before assuming comprehension-specific.

## Why this is not folded into the multi-clause doc

The multi-clause fix is asserted STRUCTURALLY in
`test_runtime_diff.py::set_and_dict_comprehension_two_clauses` — `len`, `in`,
subscript — and that is deliberate. A repr-based assertion here would measure
these three bugs instead of the clause count: the broken output before the
multi-clause fix was a 2-entry dict, and the broken output after it is a
3-entry dict whose keys are stringified, which look almost the same. `len`
separates them cleanly.

## Exact next step

The dict's key and value kinds are known statically at every
`mojo_dict_set_*` call site (the `kt`/`vt` the comprehension arm already
computes and dispatches on). `mojo_repr_list_kinds` +
`_struct_slot_kind_bytes` is the mechanism that already exists for
`struct.unpack` results — a per-slot kind string handed to a kinds-aware repr
— and `mojo_list_get_kinds` / `mojo_mark_dict_bool_values` are the marking
side. So:

1. Extend that marking so a dict comprehension records its key and value
   kinds (there is already a `mojo_mark_dict_bool_values` precedent for a
   per-dict property that only repr reads).
2. Route the dict repr through the kinds-aware helper when those kinds are
   present, as `mojo_repr_list_doubles`/`_ints`/`_bytes` already do via
   `_mojo_repr_defers_to_kinds`.
3. For (3), teach the key coercion a container kind: a `MojoList *` key is
   already a boxed value and must not go through `_char_to_cstr`'s
   `mojo_str_from_int`.

Steps 1-2 and step 3 are separable; step 3 is the one that fixes the ASLR
output and is the more urgent, because it is the only one of the three that is
non-deterministic.
## Status (2026-10-02, `work/bugs4-2`) — defect 2 fixed; defect 3's ADDRESS key removed; defects 1 and 3's remaining wrongness are now ONE missing key-kind discriminator

Re-measured on this tree against CPython 3.14.7 on the same text. All three
programs from the entry reproduce exactly as described, so nothing below is a
new finding; what changed is where each one is answered.

### Defect 1 (int key stringified) — NOT FIXED, and the reason it is not is not the one the entry assumes

`_mojo_repr_dict` — the per-module generated repr in
`mojo/backend_gimple/module_gen.py`, which is a verbatim copy of
`mojo_dict_print` — reads EVERY key with
`mojo_repr_str(mojo_dict_slot_key(d, _i))`, so an integer key prints as its own
quoted decimal (`{1: "a"}` -> `{'1': 'a'}`). The obvious fix is one `if`:
`keykind == 2` means the key is an integer and `ikey` holds it. **That fix was
written, measured, and taken back out**, and the reason is the interesting part:

```
{10: "a"}    compiled {'10': 'a'}   (want {10: 'a'})     <- the one if fixes this
{"10": "a"}  compiled {'10': 'a'}   (want {'10': 'a'})   <- and this is ALREADY RIGHT
```

`keykind == 2` does **not** mean "the source wrote an integer". It means "this
key's text is a canonical decimal", because `_canon_int` canonicalises a STR
key into that slot too — deliberately, and for the reason its own comment gives:
so `d[5]` and `d["5"]` stay the ONE integer slot they have always been. That is
CPython's semantics as well (`d = {"10": 1}; d[10] = 2` is `{10: 2}`), so the
conflation is not the bug; the repr just has to know which spelling survived,
and `_DictSlot` does not record it. CPython's own answer depends on which
spelling was inserted LAST, so the answer a correct repr needs is a per-slot
bit set by the two entry points that know: `mojo_dict_set_int` / `_int_kw` set
it, `mojo_dict_set_str` / `_bytes_*` clear it. That is a one-bit `_DictSlot`
extension threaded through `_dict_set_ik` / `_dict_set_raw_seq_kind_k`, and it
is the same change the float-key and bool-key cases need (below).

What that buys is worth stating, because it is the reason the doc's own framing
is too narrow: with the discriminator,

* `{10: "a"}` -> `{10: 'a'}`  (fixes the reported bug, comprehension or not),
* `{"10": "a"}` -> `{'10': 'a'}` (unchanged, already right),
* `{"10": 1, 10: 2}` -> `{10: 2}` (CPython's answer, because the int was last).

and the same key-kind idea covers the two cases measured below that no doc in
the queue names:

```
print({1.5: "x"})    CPython {1.5: 'x'}    compiled {'1.5': 'x'}
print({True: 1})     CPython {True: 1}     compiled {'True': 1}
```

`_canon_int` cannot read `"1.5"` or `"True"`, so both are `keykind == 0` (str)
slots and the repr quotes them. A float key and a bool key are key KINDS in the
same sense an int key is, and `_DictSlot.keykind` is where that belongs — which
is also where this doc's item 1 (a content key aliasing a string key) wants its
fourth value. See `CODEGEN_dict_content_key_aliases_a_string_key.md`'s Status
section, where the whole set is one change.

### Defect 2 (a 0 value renders as None) — FIXED

The `else` arm of the same function sent every untagged value through
`_mojo_generic_elem_repr`, whose `0 -> "None"` sentinel rule is right for a
genuinely dynamic list and wrong for a slot the runtime TAGGED. `_DictSlot.kind`
is `0` for a plain `int64_t` (see its own comment: `1 = double bit-cast`,
`2 = char *`, `3 = a Python bool`), so the tagged int is `mojo_repr_int(val)`.
A `kind == 1` (double) slot is added in the same commit: its IEEE-754 bits
were handed to `mojo_repr_str` as a `char *`, and that pattern is
pointer-shaped, so it printed garbage or faulted — so that second arm is a
CRASH fix, not a display one.

```
{"k0": 0, "k1": 1} from {"k" + str(i): i for i in range(2)}
                    was {'k0': None, 'k1': 1}      now {'k0': 0, 'k1': 1}
```

One store-side tag is still missing and is NOT part of this fix: a double
stored by SUBSCRIPT (`d["j"] = 1.5; print(d)`) prints `{'j': 1}`, because the
subscript-store lowering does not set `kind = 1` — it is a different site from
the comprehension and literal stores this repr change covers. Same for
`d["m"] = 0.0` (prints `0`), which additionally says the repr cannot
distinguish a `0.0` from a `0` bit pattern on its own. Both are recorded here
rather than pinned in the test below, which is about this repr change only.

Regression: `test_runtime_diff.py::dict_repr_zero_value_is_not_the_none_sentinel`
(CPython-comparable, so it also pins against the shared-oracle case).

### Defect 3 (tuple key) — the ADDRESS is gone; two repr defects remain

The doc's own note is right that this is not comprehension-specific: the
underlying cause was that `{k: 1 for k in pairs}` and `d[k]` disagreed about
what a tuple key is. `d[k]` goes through `_char_to_cstr(..., transient=True,
word_ok=True)`, whose CONTAINER-key branch hands the raw word to the `_kw` twin
so the runtime's `mojo_dict_key_for` renders the tuple's CONTENT. The dict
COMPREHENSION arm did not: `mojo/middle/emit_resolve.py`'s
`_gen_compr_append` dict branch called `_char_to_cstr(kt, kv)` with neither
flag, so a `MojoList *` key fell through to a raw `(char *)value` and the
tuple went into the dict under its HEAP ADDRESS as the key TEXT.

So there were **two** lowerings of one dict-pair store, and they disagreed —
the literal spelling (`_emit_dict_pair_store`, `_repr_value`) and the
comprehension spelling. The comprehension arm now calls
`_emit_dict_pair_store`, which is what that function's docstring already
called itself ("Single source of truth for key coercion + per-type setter
dispatch"); the duplicate is deleted rather than kept in step.

```
pairs = [(0, 0), (0, 1)]
{k: 1 for k in pairs}
was  {'\xef\xac\x99f': 1, '\x8b\x9c$\x05\x01': 1}   (ASLR: different every run)
now  {'(None, None)': 1, '(None, 1)': 1}                  (deterministic)
```

**The remaining wrongness is two things, both outside this doc and both
already filed elsewhere:**

1. the key is QUOTED, because a content key lands in the str key DOMAIN. That
   is item 1 of `CODEGEN_dict_content_key_aliases_a_string_key.md`
   (`_DictSlot.keykind` has room for a fourth value and the `_kw` table already
   has the three-arm shape) — and that same doc is where a FLOAT or bool key
   belongs too: `{1.5: "x"}` prints `{'1.5': 'x'}` and `{True: 1}` prints
   `{'True': 1}`, because `_canon_int` cannot read either, so both are str
   slots. Measured 2026-10-02.
2. the tuple's own slots print `None` for a `0`, because the content key is
   rendered by `_key_slot_str` (the runtime) and by `_repr_value` (the codegen),
   and NEITHER reads a slot's element kind — `_key_slot_str` reads every slot
   as an integer, so a float slot is its IEEE-754 bits and a `0` is the
   None-sentinel. That is item 2 of the same doc, "record element kinds on a
   tuple/list literal", and the codegen half of it already exists
   (`_lower_tuple_literal`'s `mojo_list_set_kinds`).

So this doc stays open, narrowed to those two, and the next step is now the
*domain*, not the repr: one `_DictSlot.keykind` value for "a container's
content text" (and one for a float/bool key) turns both into the same change
to the repr's one `if`.
