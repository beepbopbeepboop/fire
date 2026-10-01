# FORMAL_dataclass_partial_construction: `C(7)` on a dataclass with defaults fills every field here, and CPython fills the rest from their defaults

**Status: OPEN. The refusal is TRUE and the message is CORRECT; what is missing
is the capability.** Found while writing the `dataclasses` transform for the
formal backend (2026-09-29, the `module:dataclasses` claim), where it is one of
the four ways CPython's generated `__init__` and this path's field-filling
construction differ.

---

## What I ran

```python
from dataclasses import dataclass, field

@dataclass
class Config:
    width: int = field(default=80)
    height: int = 24

def main(n):
    c = Config(7)          # CPython: width=7, height=24
    return 0
```

```console
$ python3 fire.py build --formal --no-prove -o cfg cfg.py
build: constructing Config with 1 argument(s) does not match its fields
(2 field(s): width, height), and Config declares no `__init__` for it to call
instead: with no user-defined constructor, a struct's fields are filled in
DECLARATION ORDER from positional arguments and there is no other form, so
this path can only place a word in a slot it can name. Give the fields
explicitly (`Config()` then `obj.<field> = …`), which is the same program with
a representation
```

Under CPython, `Config(7)` is `width=7, height=24`.

## Why it is a real difference and not a spelling

CPython's generated `__init__` has a signature per field —
`def __init__(self, width=80, height=24)` — so a call may supply a PREFIX of
the fields and the rest take their defaults. This path's construction is not a
call to a signature at all: `S(a, b)` FILLS the struct's slots, and the slot
count is the field count, so a call that supplies fewer values than there are
slots has no meaning. `formal/build.py`'s `check_construction_shapes` refuses
it, and the refusal is right about this path: there is no `__init__` to call,
so there is nothing whose parameters could have defaults.

The keyword spelling is refused too, and separately, for the same underlying
reason — `Config(width=7)` is refused by the construction check with a message
about keywords not being a shape this path lowers. So there is no spelling of
"supply some of the fields" that works here, and that is the gap.

## What it costs to close

**Match each keyword against the field list.** This is the repair the existing
refusal message already names for the keyword case, and it is the same work for
the positional case: `Config(width=7)` becomes a fill in which slot 0 takes the
argument and slot 1 takes the class-level default, and `Config(7)` is the same
thing with the positionals taken in order and the defaults filling the rest.

Concretely, in `formal/model.py`'s `struct_construction_plan` (the one
decision both backends call, so a fix there is one fix rather than two):

* a positional argument past the last field is still a refusal — unchanged;
* a positional argument count that is ≤ the field count becomes LEGAL, and the
  unfilled slots take the field's class-level default, which is already
  materialized by `formal/build.py`'s `_rewrite_class_constants`;
* a keyword naming a field is matched against the field list rather than read
  as positional, and the two together must cover every field exactly once —
  the rule the existing keyword refusal already states.

**The risk is a wrong answer, not a refused one**, and it is the same risk
`bugs/FORMAL_known_limits.md` §1.3 records for the construction rules: a slot
index computed from the wrong argument lands a value in the wrong field, and
the program runs and prints numbers the source never wrote. So the fix needs
the agree-or-refuse discipline the rest of that area uses — every argument
placed, no field written twice, no field left unaccounted for.

**Cost: small-to-medium, self-contained, and it is not a dataclasses
question.** Nothing about it mentions `dataclasses`; it is the construction
shape, and it would equally unblock hand-written structs that want defaults.
That is why it is filed here rather than fixed: `formal/model.py` and
`formal/arm64_codegen.py`'s construction emitter are outside the
`module:dataclasses` claim.

## Next bounded action

`struct_construction_plan` in `formal/model.py`, plus the emitter that reads
it, plus `test_formal_run.py`'s existing keyword-construction refusal case
turned into a pass. Nothing in the dataclasses transform has to change, and
`test_dataclasses_formal.py`'s `field_default_is_lowered_to_its_literal` is
where a `Config(7)` row would go once it is closed — that case documents the
gap in a comment rather than silently omitting it, which is the same
distinction.
