# `std/testing/prop/random.mojo`: what is still between it and a build

**Part 1 of this document — the four `elif` walks — is FIXED (2026-10-02,
`work/formal8-5`).** What landed, and where it is pinned:

| walk | what an `elif` arm cost | pinned by |
|---|---|---|
| `_apply_receiver_writeback` | **a dropped store**: `c.bump(5)` in an arm never became `c = Cell_bump(c, 5)`, so the image answered 10 where the source says 15, on both architectures, with the `if`/`else` twin of the same program answering 15 throughout. **The walk is DELETED** (2026-10-03, `work/formal15-mutator-return-abi` `11558f0d`): a one-field mutator's receiver is now handed over by reference, so there is no store to drop and no `elif` arm to miss — `model.iter_nodes` reaches the arms because nothing rewrites them any more | `test_formal_run.py`'s `one_field_mutator_in_an_elif_arm_stores_back` |
| `_rewrite_self_fields` | a refusal: `self.n` in an arm of a one-field struct's own method | `one_word_field_read_in_an_elif_arm_is_still_the_receiver`, and its `if`/`else` twin |
| `_rewrite_one_word_nested_fields` | **measured not broken** — see the note below | `nested_one_word_chain_as_an_elif_condition` |
| `_apply_imported_constant_sites` | **measured not broken** — see the note below | `test_formal_module_attr.py`'s `test_the_store_value_side_goes_through_the_one_test` |

All four are on `model.rewrite_tree` now, which descends the `(condition, body)`
pair itself. The two that were not broken are worth a line each, because "not
broken" had a cause nobody wrote down: both run AFTER `_fold_target_queries`,
which normalizes every `elif` pair into a **list** as a side effect of its own
tuple handling (`_fold_target_queries_in`'s docstring says why — a tuple has no
assignable slots). So they reached the arms through another pass's traversal,
with the two walks that run *before* that normalization (`_rewrite_self_fields`
at `_prepare_functions`, `_apply_receiver_writeback` a few lines after it) still
holding tuples and still missing every arm. A pass's traversal order is not a
contract; four walks on one primitive is.

**What this document is now: the file.** `random.mojo`'s own body is three
constructs from building, the third of which is a project rather than a patch,
and its closure stops one level further out. Everything below was RE-MEASURED on
this tree, both architectures, with small reproducers in place of the file
itself — the copy the filing used is described at the end.

## 1. A keyword argument in a CALL now parses; what refuses it is a message that is false

The filing said this was a parser gap (`Unexpected COLON(':')` on
`Rng(seed: 7)`). **That is no longer true**: a keyword argument in a call parses,
and the refusal now comes from the construction path:

```
struct Rng:
    var n: Int

    def __init__(out self, *, seed: Int):
        self.n = seed

def main(k: Int) -> Int:
    var r = Rng(seed=7)
    return r.n
```

```
build: constructing Rng with 'seed' — 'seed' is not a field of Rng (n), and a
  keyword construction matches each keyword against the FIELD LIST by name, so a
  keyword that names no field has nowhere to put its value
```

Every clause of that is wrong about the program. `seed` **is** a parameter of
`Rng`'s declared `__init__`; the struct has one; and `construction_keyword_
refusal` has an arm — `why == "init"` — whose whole subject is a keyword
against a **declared constructor**, which names the overloads and says what to
do instead. It is unreachable for this call, because the field-list check runs
first (`model.py`'s construction resolution asks `unmatched = [k for k, _v in
kwargs if k not in slots]` before it reaches the `if shapes:` arm), so a keyword
that names a *parameter* is reported as a keyword that names no *field*.

**Not filed as its own bug here, and that is a decision worth recording**: the
keyword-construction area was `bugs/FORMAL_struct_construction_shapes.md`, which
was another worker's live claim, so this document did not edit it. **That doc was
`git rm`'d on 2026-10-03, when the construction family closed** (its `constr_*`
cases in `test_formal_run.py` are what stands in its place), so this item is now
UNOWNED and the sharp form below is the whole of it. The sharp
form of the finding, for whoever holds it: *a keyword that names no field and
does name a parameter of a declared `__init__` is refused as an unknown keyword
rather than as the keyword construction it is, and the lowerable fix is to bind
it to that parameter — `init_body_stores` already binds an overload's
parameters POSITIONALLY, so the keyword is a reordering of an argument list the
path already has.*

## 2. A no-field struct with a required-arg `__init__` cannot be constructed, and the message denies the constructor exists

```
struct Rng:
    def __init__(out self, seed: Int):
        sink(seed)

def main(k: Int) -> Int:
    var r = Rng(7)
```

```
build: constructing Rng with 1 argument(s) does not match its fields (no fields
  at all), and Rng declares no `__init__` for it to call instead: with no
  user-defined constructor, a struct's fields are filled in DECLARATION ORDER …
```

`Rng` declares one. The same area as item 1 (`struct_init_overloads` /
`shapes` is what decides whether there is a constructor to call, and a
constructor that assigns no field of a struct that has none leaves it empty), so
this is the same hand-off and is not edited here either. The gap itself is
real and is not a diagnostic: with the constructor reduced to `pass` the same
file builds, so the only thing between the two programs is the call the
constructor makes.

## 3. `rebind[Scalar[dtype]]` — generic monomorphization, and it is a project

`rand_scalar`'s first arm is
`return rebind[Scalar[dtype]](Scalar[.bool](self.rand_bool()))`, and the build
stops at:

```
build: rebind[…](…) calls a name this unit does not compile, so the brackets
  cannot be bound … If `rebind` is a generic of another module then its
  instantiation is the boundary symbol, one per set of type arguments
  (doc/ABI.md §Generics), and this path does not monomorphize
```

`bugs/FORMAL_known_limits.md` §1.2 "Stage 5" is this, and the doc that section
lives in says it is a project. Not attempted.

## 4. The closure, which is not the file's business

Measured on the real file, `std/testing/prop/random.mojo`'s build stops one
level out:

```
build: prop_random.mojo imports 'std.random', which cannot be built either:
       time.mojo: _gettime_as_nsec_unix: 'CompilationTarget' is imported from
       'std.sys', and it is a module-level name of another module …
       bugs/FORMAL_module_state_no_storage.md records the design
```

That document is another worker's. **So the honest accounting for this file is:
its own body is three constructs closer to building, and it is behind a
documented value-model limit in a module it only imports.** Reporting
"random.mojo is fixed" would be false; reporting "0 files gained a PASS" would
also be false, because the two constructs the previous worker removed from this
file's path were the ones naming `random.mojo` in the sweep's `other refusal`
row.

## What the reproducer was, and what is still not measured

Items 1 and 2 were measured on ~15-line reproducers built from the file's own
text (`Rng`'s declaration, its `__init__`, and one method call), on both
architectures, and **not** on `random.mojo` itself — the copy described in the
filing, with its two imported functions stubbed. The claims are about
constructs, not about the file: item 3 was not re-measured (it is a documented
limit), and the sweep row this document came from has not been re-run, so "two
constructs closer" is a statement about the constructs and not a count of
passing files.

`bootstrap_test_classes.mojo` (two of the files in that sweep row) was never
reproduced here. Its sweep entry is the returned-frame refusal, which is
`bugs/FORMAL_returned_frame_*.md`.