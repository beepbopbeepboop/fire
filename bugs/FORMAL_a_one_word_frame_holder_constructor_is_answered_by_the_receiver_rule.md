# FORMAL: a one-word frame holder's CONSTRUCTOR is refused by the receiver rule, which misreads the source

**Status: NOT FIXED. Both refusals are true, the program builds under neither,
and which of them should answer a constructor's store is an open precedence
question. Found while merging `work/formal10-2` into `work/merge-formal10`
(2026-10-03): formal10-2's `test_formal_method_param_field.py` row for
`bugs/FORMAL_builtin_slice_optional_field_is_a_frame_holder.md` shape 1 went
red against a rule master had landed 77 commits after formal10-2's base.**

This is NOT a coverage hole and NOT a lost refusal: the program is refused, and
it is refused by a rule that has a measured SIGSEGV behind it. It is a
question about which of two true sentences a reader of this source is shown,
and the losing sentence is false about CPython.

## What I ran

Three programs, one per spelling of the store, each a one-field holder whose
sole field is the framed `Opt` — so `Box`'s receiver IS its field's storage
and that storage is an address (`model.one_word_sole_field_frame`, 7632c881):

    struct Opt:  var v: Int;  var has: Int
    struct Box:  var inner: Opt
                 def __init__(out self, o: Opt):  self.inner = o       # a
                 def __init__(out self):  self.inner = Opt()          # b
                 def __init__(out self):  self.inner = mk(41)         # c

    $ python3 fire.py build --formal --no-prove -o out.aout <each>

| case | the store's value | who answers |
|---|---|---|
| a | `o`, an `Opt` parameter | `receiver_rebound_from_a_word_refusal`: "self is assigned o in `Box___init__()`" |
| b | `Opt()`, a frame built HERE | a different rule entirely — `main: 'b.v' is a field access through 'b'`; the receiver rule stands down because `_value_may_be_a_frame` recognises the construction |
| c | `mk(41)`, a frame the callee made | `receiver_rebound_from_a_word_refusal`: "self is assigned mk(41)" |

Case (a) is formal10-2's row. On formal10-2's own base (`e7fbe6ef`,
`formal/build.py:4275`) `_collect_receiver_rebinds` skipped **every** one-field
owner and `one_word_sole_field_frame` did not exist, so the construction-argument
message answered it. Master withdrew the exemption for frame-bearing one-field
owners, measured `self.inner = o` in a method as a dropped store (SIGSEGV, exit
139), and pinned it as
`test_formal_run.py::refuse_a_one_word_holder_of_a_frame_stored_through_its_receiver`
— whose method is `set`, an ordinary method, not a constructor.

## Why the receiver message is the wrong one for this spelling

1. **It states a fact about the source the source does not contain.** The
   reader wrote `self.inner = o`. The message says "`self` is assigned `o` …
   `self` is this method's receiver". That sentence is true of the REWRITTEN
   body (`_rewrite_self_fields` collapses `self.inner` onto `self`) and false
   of the source, and the whole of formal10-2's row is that the source is what
   a reader can act on.
2. **It is false about CPython.** "CPython rejects this shape outright, so the
   source is not a program that computes a different answer, it is one that
   does not mean what it looks like." `def __init__(self, o): self.inner = o`
   is the most ordinary constructor in Python and CPython runs it. The claim is
   carried over from the multi-field `self = 5` shape, where Python silently
   rebinds a local name — which is a DIFFERENT sentence from "does not mean what
   it looks like", and is not this one.
3. **It names a function the reader may not have written.** `Box___init__()` is
   `_fieldwise_ctor_synthesized` on this program: there is no `__init__` in the
   source at all, so the message points at a name that is in no file the reader
   has open.
4. **The sentence the reader can act on is the one being pre-empted.** The
   construction-argument refusal names the call they wrote (`Box(o)`), the
   hazard (`the constructor PLACED an Opt frame in that slot and in the
   object's own block`), and the repair — and the repair is pinned by the pair
   row in the same table (`a_struct_field_assigned_after_construction_is_the_
   same_program`, which builds and prints `v=41 h=1` on both architectures,
   and passes).

Counter-argument, recorded because it is the reason this is open rather than
decided: a constructor's body is INLINED at the construction site
(`init_body_stores`), so `self` there is the object and not a copy — which
means case (a) is arguably not a dropped store at all, and the receiver rule
may be protecting nothing for this spelling.

## Exact next step

Decide the `__init__` case in `_collect_receiver_rebinds` and measure it. The
exemption is small and its blast radius is already known:

* Skip the one-field receiver store when the method IS the struct's
  constructor. Read it as `M.method_member_name(owner, fn) == "__init__"` —
  `method_member_name` exists (formal10-4) precisely so "which method is this"
  cannot drift from the lifted symbol, and `fn.name.endswith("___init__")` is
  the spelling to avoid.
* Then re-run the three cases above. Expected, and each is a different
  question: (a) must be refused by `construction_arg_frame_value`'s clause
  (`_refuse_holder_use`) with `constructing Box with argument 'o' as field
  'inner'` — formal10-2's original needle; (b) is unchanged, another rule
  already answers it; (c) `self.inner = mk(41)` inside a constructor is the one
  that would BUILD, and that is the same store as the documented workaround
  `b.inner = mk(41)` at a call site, so it should be measured for the right
  number (41/1) rather than assumed either way.
* `test_formal_run.py`'s pinned
  `refuse_a_one_word_holder_of_a_frame_stored_through_its_receiver` is a plain
  `set`, so an `__init__`-only exemption leaves it green — which is the reason
  this is a narrow change rather than a withdrawal of the exemption. Its
  SIGSEGV measurement must still hold for a reader who has a METHOD.
* Repoint formal10-2's row back to the construction needle if the exemption
  lands, and re-verify that the pair (`refusal`, `workaround`) still holds.

Suites that must be re-run for that change (they are the ones that read a
one-word receiver): `test_formal_run.py`,
`test_formal_method_param_field.py`, `test_formal_receiver_spelling.py`,
`test_formal_bracketed_method_field_set.py`, `test_struct_formal.py`,
`test_refusal_taxonomy.py`.

## What the merge did about it

`test_formal_method_param_field.py`'s row now pins the refusal that fires
(`self is assigned o in Box___init__`), with the reason in the comment above
it, and this doc is the pointer for the precedence question. Nothing else moved:
both rules are live, the program is refused, and the promise the refusal makes
is still pinned by the second program in the pair.