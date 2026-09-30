# CODEGEN: four compiled-path gaps measured on 2026-09-27, none of them refusals

Found while landing the round-2 fixes for
`COMPILE_FAIL_importlib_resources_readers.md`,
`COMPILE_FAIL_Android_android.md` and
`COMPILE_FAIL_decorator_application_dropped.md`. Grouped in one doc because
each is small, each is a **silent wrong answer or an honest refusal rather
than a build failure**, and each was found by a synthetic probe rather than by
a stdlib file — so nothing tracked them. Every repro below is a complete
program; all four fail at `435cc71` in exactly the way described.

They are separate pieces of work. Nothing here blocks anything else; the
ordering below is by "how likely is this to bite real code".

---

## 1. A generator or classmethod INHERITED from a base class is not a
##    generator call through the subclass, and `cls` binds the DEFINING class

`bugs/COMPILE_FAIL_importlib_resources_readers.md` taught the call site to
resolve `C.<genmethod>(...)` out of `_generator_method_api`, which is keyed
`(struct_name, method_name)`. A subclass that INHERITS the method is not in
that table under its own name, and the compiled `cls` is a compile-time,
name-resolved placeholder rather than a runtime class object, so even when
the call is found the receiver is the class the method was *defined* on.

```python
class Base:
    tag = 7
    @classmethod
    def who(cls):
        return cls.tag
    @classmethod
    def gen(cls, n):
        yield cls.tag
        yield n

class Child(Base):
    tag = 9

def main():
    print(Child.who())          # CPython 9
    for v in Child.gen(4):      # CPython 9, 4
        print(v)
```

| | CPython | `fire.py run` | compiled |
|---|---|---|---|
| `Child.who()` | `9` | `9` | **`7`** |
| `Child.gen(4)` | `9`, `4` | `9`, `4` | **`7`**, then `mojo_unsupported_iter` |

Two independent causes, so two fixes:

- **The lookup.** `(Child, 'gen')` is not in `_generator_method_api`. Either
  register a subclass alias for every inherited generator method, or walk the
  base chain at the call site (the `struct_defs` inheritance information
  `gimple_codegen._merge_struct_inheritance` already builds). The base-chain
  walk is smaller and cannot go stale.
- **The receiver.** Making the *call* resolve is not enough: `cls` is an
  opaque `int64_t` placeholder that the emitted unit resolves purely by NAME
  against the defining `struct_name` (see
  `cpp_async._gen_cpp_generator_unit`'s `cls` handling, and
  `_cls_refs_supported`). So `Child.who()` will keep returning `Base.tag`
  until a class OBJECT exists at runtime, or until the placeholder is made to
  carry the receiver's class id and the `cls.<attr>` read consults it. That
  is feature-sized. **Land the lookup fix and record the `cls` half as its own
  refusal**, rather than leaving `Child.gen(...)` to fail as
  `mojo_unsupported_iter` at run time — a refusal is worth more than a
  mystery.

Real-code relevance: moderate. Class-level constant tables built with a
`@classmethod` accessor and a subclass override is a common Python shape, but
this compiler's own generated code is not built that way.

---

## 2. `x == None` is False on the compiled path for a NULL `char *`, and
##    `print()` of one prints `(null)`

Found by accident, writing a `dict_union_get` regression: the natural
assertion `d.get("MISSING") == None` is wrong on the compiled path.

```python
def main():
    a = {"A": "1"}
    print(a.get("MISSING"))          # CPython None
    print(a.get("MISSING") == None)  # CPython True
```

| | CPython | `fire.py run` | compiled |
|---|---|---|---|
| `print(a.get("MISSING"))` | `None` | `None` | `(null)` |
| `print(a.get("MISSING") == None)` | `True` | `True` | **`False`** |

**This is pre-existing and independent of dict unions** — it reproduces on a
plain dict literal, which is how it was found. `mojo_dict_get_str` returns
`NULL` for a missing key, and `None` does not lower to a value `NULL`
compares equal to; the two are separately represented and never reconciled.
Any `d.get(k) == None` / `is None` guard on the compiled path is silently
taking the wrong branch, which for a lookup usually means a `None` /
missing-key path being entered on a HIT.

**Next bounded action:** find how `None` is represented in a comparison
(`gimple_ctypes`' `_CMP_OPS` handling of `is`/`==` against a `NoneLiteral`)
and make a `char *`-typed NULL compare equal to it. A regression belongs in
`test_runtime_diff.py` — it is exactly the shape that harness exists for, and
it is a one-line program.

---

## 3. A heterogeneous `dict | dict` has no static value type

Round 2 fixed the homogeneous case: `mojo_dict_union`'s lowering now carries
the operands' agreed value type onto the result
(`emit_infra._dict_union_val_type`), so `(a | b).get(k)` reads a `char *`
instead of the stored pointer's bits. The deliberately-unhandled remainder:

```python
def main():
    a = {"x": 1}        # int values
    b = {"y": "s"}      # str values
    c = a | b
    print(c.get("y"))   # CPython "s"
```

`MojoDict` is one `int64_t` slot plus a `kind` tag, so there is genuinely no
single static C type for "either". The join is therefore NOT
`TypeLattice.join` (which resolves int64_t-vs-`char *` to `char *` and would
truncate every integer the union inherited) — a disagreement leaves the
result unrecorded, which is the pre-fix behaviour and a silent wrong answer,
not a regression.

Making it right needs a boxed-any representation plus a consumer that
dispatches on the slot's `kind`, which is a feature. **Until then the
honest move is to REFUSE a heterogeneous union** at compile time rather than
emit a `.get` that returns a pointer: the refusal is one branch in
`_dict_union_val_type`'s caller, and it converts a silent wrong answer into a
build error for every stdlib module that does it. Measure the blast radius
first (`compile_stdlib.py`'s `U` count) — a type-resolution refusal is
exactly the change CLAUDE.md warns regresses dozens of modules quietly.

---

## 4. A cross-module symbol-name mismatch: `__itertools_only_<hash>` vs
##    `_itertools_only_<hash>`

Found by building `Lib/importlib/resources/readers.py`, whose two remaining
errors are this and gap-3-shaped territory:

```
readers.py:118:10: error: implicit declaration of function
  '__itertools_only_37bd8e'; did you mean '_itertools_only_37bd8e'?
```

An imported free function's **definition** and its **call site** disagree by
one leading underscore, for a function reached through
`from itertools import only as <alias>`. So this is not alias-specific: some
naming rule adds `_` at one site and not the other. Two candidates worth
checking first: the sibling-module prefixing in
`gimple_codegen._selfhost_sibling_module_call` /
`_SELFHOST_SIBLING_MODULE_PREFIXES`, and `_func_csym`'s
module-qualifier composition (which is what puts the `<hash>` suffix on).

This one is a real, isolated, small bug with a one-line repro once the
qualifier rule is identified, and it is worth fixing before anything else
here: a wrong-symbol call is not a wrong answer, it is a link error, and it
blocks a whole module.

---

## Not in this doc, deliberately

- **`@decorator` on the compiled path.** Its own doc
  (`COMPILE_FAIL_decorator_application_dropped.md`), whose interpreter half
  landed this round and whose compiled half is unchanged.
- **`re.Match` / the `re` module's source fallback.** Already documented in
  `COMPILE_FAIL_importlib_resources_readers.md`; feature-sized, and not new.
