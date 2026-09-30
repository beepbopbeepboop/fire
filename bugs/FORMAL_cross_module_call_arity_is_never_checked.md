# FORMAL_cross_module_call_arity_is_never_checked: a call into a dylib drops extra arguments and invents missing ones

**Status: OPEN, and it is a wrong answer on both architectures that DISAGREE
with each other. Found while lowering module attribute access (the
`construct:module-attribute-access` claim, 2026-09-30); the fix is in the
cross-module call path, which is the `construct:cross-module-link` claim, so
it is filed rather than applied.**

This is the one failure mode the whole formal backend is built to refuse: a
program that **builds, links, passes every static check, runs, and prints a
number the source never wrote** — and prints a *different* wrong number on each
architecture.

---

## What I ran

```
$ cat > .tmp/mods/aritylib.mojo
def two(a, b):
    return a * 10 + b

$ cat > .tmp/mods/p_arity3.mojo
from aritylib import two

def main(n):
    printf("%d\n", two(1, 2, 3))
    return 0

$ cat > .tmp/mods/p_arity4.mojo
from aritylib import two

def main(n):
    printf("%d\n", two(1))
    return 0

$ for a in arm64 x86_64; do
    python3 fire.py build --formal --no-prove --backend=$a -o out.$a p_arity3.mojo
    ./out.$a
  done
12
12                      # CPython: TypeError: two() takes 2 positional arguments but 3 were given

$ … the same with two(1)
1795896298              # arm64
82359266                # x86-64
                        # CPython: TypeError: two() missing 1 required positional argument: 'b'
```

**Too many arguments: the extras are dropped and the call returns an answer.**
`two(1, 2, 3)` prints `12` — the correct answer to `two(1, 2)`, for a call that
names three arguments. With `os.path.join` it is worse, because the dropped
argument is the one that carries the meaning:

```
$ cat > p_arity.mojo
from os.path import join
def main(n):
    printf("[%s]\n", join("a", "b", "c"))
$ python3 fire.py build --formal --no-prove -o p_arity p_arity.mojo && ./p_arity
[a/b]                   # CPython: a/b/c
```

**Too few arguments: the callee reads an uninitialized register, and the two
architectures read different ones.** `1795896298` on arm64, `82359266` on
x86-64 — both printed as ordinary decimal integers, neither is 12, and nothing
in the build said anything. That is the `X19`-fall-through family of defect
(`bugs/FORMAL_module_state_no_storage.md` and the register-fall-through notes
in `formal/model.py`) arriving through a different door: the argument register
is never written because the caller never set it.

## Why the local call is checked and this one is not

The check exists, and it is the right check. `formal/arm64_codegen.py`'s
`_emit_call` calls `_bind_call_args(name, e)` for a callee in this image, and
that is where the message comes from:

```
$ cat > .tmp/mods/p_extra.mojo
def two(a, b):
    return a + b
def main(n):
    printf("%d\n", two(1, 2, 3))
$ python3 fire.py build --formal --no-prove -o p_extra .tmp/mods/p_extra.mojo
build: call two(): too many positional arguments (3 for 2 parameter(s); the parameters are ['a', 'b']
```

`is_extern = name not in self._functions` splits the two paths, and the arity
check lives on the `not is_extern` side. An extern has no `FunctionDef` in this
image — `_functions` is this module's — so there is no parameter list to
compare against, and nothing compares against anything.

**The information is not missing, though. It is in the manifest, and it is
already read.** Every export entry carries an `arity`, written by
`write_dylib_manifest` from `reflect.collect_exports_src`:

```json
{"arity": 2, "kind": 0, "module": "aritylib", "name": "two",
 "signature": "void two (int64_t, int64_t)", "symbol": "aritylib_two_2dbb98"}
```

and both emitters already index those entries —
`model.dylib_export_tables`' `by_name` / `by_module` / `forwarded` are built
from exactly this list, and `dylib_export_lookup` is already asked, in
`_callee_kind`, what such a call RETURNS. So the call site's own machinery
knows the callee's name, module, symbol and return kind, and not its arity.

## The exact next step

1. **In `_emit_call`'s extern branch, in BOTH backends, compare the call's
   positional count against the manifest entry's `arity` and refuse a
   mismatch.** The comparison is `model.dylib_export_lookup(...)[arity]`,
   which is the same lookup already used one line below for the return kind, so
   it adds no new plumbing and no new table. `None` (no entry, or an entry with
   no arity — a re-export whose defining module did not record one) must NOT be
   treated as a mismatch: a name with no declared arity keeps today's
   behaviour, because a refusal that fires on an unknown is a refusal that
   fires on every `*args` call and on every library whose manifest predates the
   field.

2. **The message must name the arity, the count and the callee**, in the shape
   the local check already uses (`too many positional arguments (3 for 2
   parameter(s))`), plus the module — because a cross-module call has no
   parameter list to print, and `doc/ABI.md`'s `signature` string is the
   declaration a reader can check the count against. The manifest carries it
   (`"void two (int64_t, int64_t)"`), so the message can quote the very
   signature the library was built from.

3. **A test in `test_formal_imports.py`** (it owns the manifest contract and
   already has the two-tree harness): a module with a two-parameter function,
   called with three and with one, asserting the BUILD FAILS with the arity in
   the message — not a runtime assertion, because the whole point is that today
   it builds and prints a number. Covering the too-few case matters as much as
   the too-many one: it is the one that reads uninitialized memory, and it is
   the one that differs between the two architectures.

4. **Then decide what an arity a manifest cannot express should do.**
   `doc/ABI.md` records that an OVERLOAD is excluded from the export set
   because no one symbol denotes it (`bugs/FORMAL_module_exports_nothing.md`),
   and `formal/imports.py` has the same rule on the producer side — so a call
   to an overloaded name has no `arity` to check against and keeps binding the
   first instantiation, which is the pre-existing name-based-dispatch limit
   rather than a new hole. Worth stating in the message rather than leaving a
   reader to assume it was checked.

## Checked and NOT these, so nobody re-derives it

- **`bugs/FORMAL_arm64_ninth_argument_is_silently_dropped.md`** is the
  neighbouring case and a different one: that is the AAPCS register-file limit
  (X0–X7 on arm64, six on x86-64), where the *callee* cannot receive a ninth
  parameter at all and the fix is to refuse. This document is about a call
  whose count is 2 or 3 — well inside every register file — where the callee
  has a perfectly good parameter list and the caller simply does not match it.
  Its step 1 would not catch this, and this step 1 does not catch it.
- **`bugs/FORMAL_variadic_call_has_no_abi`** is about `*args` on the callee
  side; the calls here pass fixed positional arguments to a fixed-parameter
  function.
- **`bugs/FORMAL_default_argument_not_applied_across_a_dylib.md`** is about an
  argument the caller does not supply because the callee declares a default.
  That is a real defect with the same symptom as this document's too-few case —
  a missing argument arriving as whatever was in the register — and the arity
  check proposed here would refuse the call rather than fix the default, so
  the two must be landed in that order (defaults first, or the arity check has
  to exempt a callee that declares defaults, which is a fact the manifest does
  not currently record).
