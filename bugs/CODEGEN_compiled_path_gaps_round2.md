# CODEGEN: four compiled-path gaps measured on 2026-09-27, none of them refusals

## Status (2026-09-30): TWO OF THE FOUR ARE CLOSED — #2 fixed here, #4 was
## already fixed on 2026-09-27 — and #1 and #3 are still open

Re-measured against the current tree, with CPython alongside, on
2026-09-30 (branch `work/codegen-old-divergences`):

| # | gap | state |
|---|---|---|
| 1 | an inherited `@classmethod`/`@generator` binds the DEFINING class and does not dispatch | **OPEN** — analysis below re-measured and unchanged |
| 2 | `x == None` on a `char *` is False, and `print` of one prints `(null)` | **FIXED** (two commits on this branch) |
| 3 | a heterogeneous `dict \| dict` has no static value type | **OPEN** — deliberately unhandled; the refusal is still the recommended move and is still unmeasured |
| 4 | `__itertools_only_<hash>` vs `_itertools_only_<hash>` | **FIXED on 2026-09-27**, not by this branch — see below |

## #2 — FIXED. `x == None` and `print(None)

Both halves reproduced first, against the current tree:

```python
def main():
    a = {"A": "1"}
    print(a.get("MISSING"))          # CPython None      compiled (null)
    print(a.get("MISSING") == None)  # CPython True      compiled False
main()
```

**Cause.** `d.get(k)` lowers to `mojo_dict_get_str`, which returns `NULL` for
an absent key, and `None` is a singleton with no NULL to point at. The
string-equality lowering sent the `None` side through
`mojo_char_to_str((char)0)` — the one-character string NUL — so the answer was
`strcmp(NULL, "")`, i.e. False. `print` reached `printf("%s", NULL)`, which
glibc and Darwin both render `(null)`.

**Fix.** `x == None` with `x` a `char *` is now a pointer comparison against 0
(`mojo/backend_gimple/emit_exprs.py`, emitted before the string path, in the
same shape as the `is`/`is not` pointer-identity case), and
`mojo_print`/`mojo_print_stderr` print `None` for a NULL string. The polarity
is the operator itself, which is the OPPOSITE of the `mojo_str_eq` idiom above
it (that helper returns 1 for equal, so `==` becomes `!= 0`); the first attempt
inverted it and turned all ten probe lines the other way.

**Verified** on the real binaries: every line of the probe now agrees across
CPython, the interpreter and the compiled path, including `a.get("A") == None`
(False), `"" == None` (False) and `a.get("MISSING") is None` (True, which was
already right). Regression: `dict_get_none_guard` in `test_runtime_diff.py`,
cross-checked against CPython, red without the fix
(`interp='None' jit='(null)'`).

**Still open inside #2, deliberately not fixed:** `None == 0` is True on the
compiled path where CPython says False. The numeric path cannot tell a boxed
null POINTER from the integer 0, and folding it to a constant False would
break every `d.get(k)` guard whose local is untyped (the pointer bits ARE 0 on
a miss). It needs the boxed-any representation item #3 also needs.

The original write-up follows, one item per section, with #2 and #4 marked.

---

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

## 2. FIXED 2026-09-30 — `x == None` is False on the compiled path for a NULL
##    `char *`, and `print()` of one prints `(null)`

(Reproduced against the current tree, root-caused and fixed; see the Status at
the top of this file. The original analysis is kept below.)

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

## 4. FIXED 2026-09-27 (not by this branch) — a cross-module symbol-name
##    mismatch: `__itertools_only_<hash>` vs `_itertools_only_<hash>`

`mojo/middle/module_shared.py`'s `_register_sym` was the only one of the five
module-string -> C-prefix manglers that omitted `lstrip('.')`, so
`from ._itertools import only` gave the call site `__itertools_only_37bd8e`
against a `_itertools_only_37bd8e` definition. One token. Its regression is
`test_module_cache.py`'s `test_underscore_prefixed_sibling_import_symbol`,
which asserts the call site and the definition use ONE spelling — necessary
because in the minimal shape a sibling TU accidentally satisfies the bad name
and a link/exit-code assertion passes on the broken tree. `test_module_cache.py`
83/0 on 2026-09-30. The original write-up follows.

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
