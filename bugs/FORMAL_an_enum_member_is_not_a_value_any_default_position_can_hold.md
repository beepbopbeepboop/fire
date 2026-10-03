# FORMAL_an_enum_member_is_not_a_value_any_default_position_can_hold: `Type.origin = TypeOrigin.DEFAULT`

**Area:** FORMAL (`formal/model.py`'s `literal_default_word` /
`class_constant_word` / `struct_default_word`, and every caller that materialises
a default; the reader is `formal/dataclass_transform.py`'s `field_refusal` for
the case that names it).

**Status: OPEN, not fixed, and NOT a patch — it is a value-model question whose
answer changes what a program MEANS. Measured on both architectures.**

Found 2026-10-03 on `work/formal12-backend-crash`, while re-measuring the four
`backend-crash` rows of `bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.2. Those
four files now answer properly; this is the terminal cause three of them land on,
and it is one of that map's "16 single-file causes" (`type_system.py`).

## What I ran

```sh
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 tools/formal_sweep.py -j 1 -t 120 type_system.py
CODEGEN: type_system.py  (build: Type.origin: the default for field 'origin' is
not a value this build can materialize, and a class-level default on this path
has to be one: …)
```

`type_system.py:51` is `origin: TypeOrigin = TypeOrigin.DEFAULT`, in a
`@dataclass`. It blocks three files in the 2026-10-02 sweep
(`type_system.py`, `detect_real_type_errors.py`, `run_type_system_tests.py`).

## What I saw

**It is not `@dataclass`-specific, and it is not the one file's own source.**
Two files with no dataclass in them, one a plain struct field and one a
class-level constant, both refused with the same words:

```sh
$ cat .tmp/m/e1.mojo           # a PLAIN struct
from enum import Enum

class Reg(Enum):
    DEFAULT = "default"

struct Plain:
    var origin: Int = Reg.DEFAULT.value
```

```
build: p.origin reads a class-level constant of Plain, whose value is
`Reg.DEFAULT.value` — and a formal value is one 64-bit word with nowhere to keep
a non-literal one …
```

```sh
$ cat .tmp/m/e2.mojo           # a class-level CONSTANT
class Holder:
    ORIGIN = Reg.DEFAULT
```

```
build: Holder.ORIGIN reads a class-level constant of Holder, whose value is
`Reg.DEFAULT` — …
```

`literal_default_word` folds `None`, `IntLiteral`, `StringLiteral`, and whatever
`fold_literal_expr` reaches (`formal/model.py`, the comment there records the
`-3` fix). A **member read** is not in any of those, so every position that
materialises a default refuses it — a struct field default, a class-level
constant, a dataclass field default. That is why the refusal is worth a doc
rather than a one-line fix to `field_refusal`: the reader is shared and three
callers hit it.

**A member read is not the same shape as a member read that works.** This path
already answers `Reg.R15.value` as a class constant of an ENUM
(`_enum_member_sites`, and `test_formal_run.py`'s
`enum_member_read_answers_without_a_none_constant` is the test). The difference
is which class the access hangs off: `Reg.R15.value` is a read of `Reg`'s own
constant, and `Reg` is an enum, so `enum_member_accessor` applies. `Plain.origin`
is a read of `Plain`'s constant whose VALUE happens to mention `Reg`.

## Why this is not a patch

Folding `TypeOrigin.DEFAULT` to its `.value` is the obvious move, and it is
where the value model has to be decided rather than coded:

* `TypeOrigin.DEFAULT.value` is `"default"`, so the field materialises as a
  `char *` to an interned literal — one word, exactly representable.
* **Then `p.origin` reads as the STRING, not as the member.** In CPython
  `p.origin` is the member and `p.origin.value` is the string; on this path the
  member is gone and `p.origin.value` becomes `"default".value`, which is a
  refusal on the next line. `type_system.py` has exactly that read
  (`type_system.py:159-160`, `old_type.origin.value`). So the change trades
  "this file is refused at line 51" for "this file is refused at line 159",
  unless every use drops its `.value` — i.e. it rewrites the SOURCE.
* A member is not a value here in the first place: this path has no
  representation for an enum member as a distinct object (it is one 64-bit word,
  and the member's identity is not in it), so `p.origin == TypeOrigin.DEFAULT`
  folds to a string comparison and compares equal for the wrong reason — the
  same class of wrong answer `refuse_none_comparisons` exists to refuse for
  `None`.

Whoever picks this up has to answer **"is an enum member its `.value`, or is it
an object?"** once, in the value model, and both `literal_default_word` and
`refuse_none_comparisons` follow from that answer. The dataclass field default
is the cheap place to land the result; it is the wrong place to decide it.

## The exact next step

1. Decide the question above and write the answer into the aggregate-layout note
   at the top of `formal/model.py`, beside "what a value is".
2. If the answer is "a member IS its value", the change is additive in
   `literal_default_word`: it needs the structs table (to know `Reg` is an enum
   and what `DEFAULT` holds — `enum_member_accessor` / `struct_is_enum` already
   answer both), which means a new argument on `literal_default_word`,
   `class_constant_word` and `struct_default_word` and therefore on every
   caller. Additive matters: only currently-refused defaults change verdict, so
   no working program moves.
3. If the answer is "a member is an object", then `field_refusal`'s advice is
   already right ("Write a literal") and the work is to make the three callers
   say so for an enum member specifically, because `Write a literal` sends a
   reader to look for a literal in `type_system.py` and there is none.

## Measured, for whoever takes it

With `type_system.py`'s `origin` default replaced by `None` in a scratch copy,
the next refusal is immediate and unrelated:

```
build: a Type frame address is passed to isinstance(), which is lowered as an
operation on a VALUE …
```

So **no file's verdict becomes a build from step 2 alone** — `type_system.py` is
a dataclass-heavy file whose remaining shapes are the frame-receiver question
(`bugs/FORMAL_frame_receiver_handoff.md`), not this one. Fix it for the model,
not for the coverage number.