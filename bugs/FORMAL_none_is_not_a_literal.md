# FORMAL_none_is_not_a_literal: `x: T = None` is a NAME on this parser, so a class-level `None` default cannot be materialized

**Status: OPEN, pre-existing, one line, and it is what two of the six files that
were blocked on `dataclasses` now stop on.** Found while writing the
`dataclasses` transform for the formal backend (2026-09-29, the
`module:dataclasses` claim), where it is the first thing the transform meets
that it did not introduce.

---

## What I ran

Not dataclass-specific — a plain class:

```python
class Plain:
    a: int
    b: int = None

def main(n):
    p = Plain(1)
    printf("a=%d b=%d", p.a, p.b)
    return 0
```

```console
$ python3 fire.py build --formal --no-prove -o nulldef nulldef.py
build: Plain.b is a class-level constant, and a formal value is one 64-bit
word with nowhere to keep a non-literal one: this path has no module-global
storage, so reading Plain.b can only be answered by the value it is written
with, and that value is not a literal.
```

CPython prints `a=1 b=None`. Here the class is refused at build time.

## Why

`None` does not parse to a literal node on this parser:

```python
>>> F.Parser(F.py_tokenize("b: int = None")).with_filename("x").parse_module()
AssignStmt(target=IdentExpr(name='b'), value=IdentExpr(name='None'), type_ann='int')
```

So `None` is a bare **identifier**, and
`formal/model.py`'s `fold_literal_expr` — the one function that decides "can
the build KNOW this value", asked by the module-constant substitution and by
`formal/build.py`'s `_rewrite_class_constants` — has no arm for it. It folds
`IntLiteral`, `BoolLiteral`, `StringLiteral`, unary `+`/`-`, and `+`/`-`/`*`
between integers, and returns None for everything else. `None` is a value
this target represents perfectly well: it is the word 0, which is what an
unwritten frame slot already is.

## Why it is worth a line of code

`x: T = None` is the default for an optional field, and it is the single most
common class-level default in this repository's own dataclasses:

| file | field |
|---|---|
| `type_system.py` | `Type.bit_width: Optional[int] = None` — **and nine more on the same class** |
| `fault_tolerance.py` | `SideResult.harness_error: str \| None = None`, `FaultTolerantResult.artifacts_path` |

Both files are refused on it. `type_system.py` is one of the five the
`module:dataclasses` claim was about, and after the `dataclasses` import
stopped being its terminal cause this is what it stops on instead — so the
file moved from "cannot be built here at all" to "one line away", and that one
line is here.

`formal/dataclass_transform.py` names the case specifically rather than
reporting it as "not a literal", because "not a literal" sends a reader looking
for a call and there is no call: `None` is a name, and the message says so.

## What would close it

**One arm in `fold_literal_expr`.** `None` is a formal value — the word 0 — so
folding `IdentExpr('None')` to `0` is not an approximation, it is the
representation. It belongs in `formal/model.py` beside the other arms, and
because both backends and `formal/build.py` read that one function, the fix is
one edit rather than three.

The two things to be careful about, and both are small:

* **It is not the same as the integer 0 at every use.** `None` is falsy and `0`
  is falsy, and `None == 0` is False in Python while `0 == 0` is True. If any
  comparison site can see a folded class-level constant as an operand, the
  two must not be conflated. Measured: `fold_literal_expr` already folds
  `BoolLiteral` to `1`/`0`, so the distinction is already load-bearing in that
  direction; the safe shape is to fold `None` to the word 0 AND have the
  refusal site (`module_global_refusal`) say so, rather than to introduce a
  distinguishable null that the one-word model cannot carry.
* **A module-level `G = None` becomes answerable at the same time**, which is
  the same change and the same argument: `G` is a word and `None` is a word.
  That is a behaviour change beyond class-level defaults and should be measured
  rather than assumed — `formal_sweep.py` before/after is the measurement.

**Cost: minutes.** One function, one arm, plus a `test_formal_run.py` case and
a row in `test_dataclasses_formal.py` (`type_system.py`'s `Type` becomes the
corpus case, if the rest of that class lowers).

## What would NOT close it

Making `None` a distinct value. The model is one 64-bit word with no tag, so a
"null that is not zero" has nowhere to live — and the places that would need to
distinguish them (`is None` on a folded constant) are exactly the places where
this backend has no representation either. So the honest closure is the fold,
and the honest limit is stated above.
