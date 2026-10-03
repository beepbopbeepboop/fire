# FORMAL_an_enum_typed_parameters_field_has_no_layout: `base.value` on a `base: Reg` parameter is refused, and 1 file in 668 pays for it

**Status:** open, unowned, found 2026-10-03 while clearing the single-file causes
named in `bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.2 ("method parameter's
field, with no call site to establish it", `formal/x86_64.py`). The refusal is
**correct**; this doc is the measurement and the design, because the design is
small and the sizing is the thing a reader needs before starting.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- \
  python3 tools/formal_sweep.py formal/x86_64.py -j 1 -t 120 --arch x86_64
```

## What was seen

Both architectures, the same sentence:

```
CODEGEN: formal/x86_64.py  (build: _rm_disp: 'base.value' is a field access
through 'base', and this path has no way to say what 'base' holds. A field is
lowered three ways and which one applies is decided by the BINDING of the base,
not by a type … Bind the base from a constructor whose declaration THIS IMAGE can
see (`x = S()`) …)
```

Minimal reproduction, measured on arm64:

```
from enum import Enum

class Reg(Enum):
    RAX = 0
    RBP = 5

def pick(base: Reg) -> Int:
    if base.value == 5:
        return 1
    return 0

def main(n: Int) -> Int:
    printf("%d\n", pick(Reg.RBP))
    return 0
```

CPython prints `1`.

`Reg.RBP.value` — a **class-level** member read — lowers, and has since
`formal/build.py`'s `_enum_member_sites` / `_apply_constant_sites` (that fix is
what stopped `Reg.R15.value` answering `0` where CPython answers `15`, on both
backends). The parameter spelling does not, and the difference is one word in the
site key: the census is keyed on the literal path `Reg.RBP.value`, and a
parameter's path is `base.value`.

## Why it is refused, precisely

`formal/build.py`'s `_frame_receivers` seeds a parameter as a frame holder when
`model.parameter_declared_structs` says its declared type names a struct of this
module **and** that struct is framed or one-field. `Reg` is an enum: its members
are class-level constants and it declares no fields of its own, so it is neither,
and the seed is skipped:

```python
if M.struct_is_framed(pst):
    holders[...].add(pname)
elif not M.struct_is_one_field(pst):
    continue
```

That is right. `base` is not a frame — it holds an enum member, which on this
path is a plain 64-bit word. And `base.value` is therefore not a slot load at
all: **the word an enum member is, on this path, IS its value**, which is exactly
why `Reg.RBP.value` substitutes the literal `5` in the class-constant rewrite.
So `base.value` is `base`.

## The exact next step

A rewrite, in the same place and the same shape as the one that already exists,
gated on the declaration:

1. **A new census, beside `_enum_member_sites`:** `{parameter: (struct, kind)}`
   for every function whose `shape.fixed` parameter is annotated with a name
   `model.struct_is_enum` accepts, published per function the way
   `fn._frame_candidates` is (`build.py`'s `_frame_receivers` is where the
   declaration evidence is read, and `model.parameter_declared_structs` is the
   one reader of it that already answers for a free function as well as a
   method).
2. **The rewrite, in `_apply_constant_sites`'s sibling:** `MemberExpr(IdentExpr(p),
   "value")` where `p` is in that table becomes the bare `IdentExpr(p)`.
   `_enum_member_sites`'s `"name"` accessor must NOT be given the same treatment:
   a member's `name` is the constant's **spelling**, a string that is not
   recoverable from the word, so `base.name` has to be refused by name — a new
   sentence, not the `"value"` one.
3. **The gate that makes it safe:** every member of the enum must have a
   **literal int** value. `_constant_literal` already answers that per member and
   `_enum_member_refusal` already refuses the ones that are computed, because a
   computed member's value is not the word that travels. An enum with one
   computed member must refuse `base.value` for the same reason
   `Reg.<computed>.value` does today.
4. **The `Enum` base has to be visible.** `struct_is_enum` reads the
   `formal/hostmods/enum.mojo` declaration, so a parameter annotated with a
   class deriving from an `Enum` this image does not declare is out of reach —
   the same "bind the base from a declaration this image can see" the refusal
   already says.

## What it is worth, measured

**One file in 668.** `grep -c "is a field access through" bugs/sweeps/sweep-arm-7.txt`
is `1`, and the one is this file's `base`. Nothing else in the corpus — repository
or stdlib, either architecture — reaches this sentence. The design above is
therefore worth landing for its own sake (an enum-typed parameter is ordinary
Python, and the refusal is a reader being told to re-declare a struct their
import already declared) rather than for the coverage number. It is not worth
landing in a hurry, and it is not worth landing as a source change to
`formal/x86_64.py`: passing `.value` at every call site would mean the encoder's
API takes a register NUMBER instead of a register, which is a worse module.
