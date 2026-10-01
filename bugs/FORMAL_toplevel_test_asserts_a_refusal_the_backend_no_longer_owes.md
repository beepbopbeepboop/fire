# FORMAL_toplevel_test_asserts_a_refusal_the_backend_no_longer_owes: `test_formal_toplevel.py::body_construction_refusal` is stale, and the binary is right

**Status: OPEN, and it is a stale TEST rather than a gap in the backend. Found
while verifying module attribute access (2026-09-30), on both the current tree
and its parent — 68 PASS / 2 FAIL before and after, the two failures being these
two rows. Not fixed here: `test_formal_toplevel.py` and the `__init__` inlining
are not the `construct:module-attribute-access` claim's area.**

**Second row, same family, found 2026-09-30 while running the regression floor
for `construct:method-param-field-access`: the run is now 66 PASS / 4 FAIL, so
`name_in_function` (both backends) has joined `body_construction_refusal`. It is
the same defect class with a different spelling — the backend still refuses,
and refuses correctly, but not in the words the row pins.** Appended below with
its own reproducer; the exact next step for it is step 4.

A test that asserts a refusal for a construct the backend now lowers CORRECTLY
is not a known failure to be forgiven — it is a hole in coverage pointed the
wrong way. It says "this has no representation" about a construct that has one,
and a reader who believes the test will not go and look for the coverage the
inlining actually has.

---

## What I ran

```
$ cat > .tmp/initt/p.mojo
struct Point:
    x: Int
    y: Int
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(1, 2)
printf("%d\n", p.x)
$ python3 fire.py build --formal --no-prove -o p.aout p.mojo
Built: p.aout  [arm64/macho]
$ ./p.aout
1
```

The test row (both backends) is:

```python
    return case_refused(
        "body_construction_refusal",
        "struct Point:\n    x: Int\n    y: Int\n    def __init__(self, x, y):\n"
        "        self.x = x\n        self.y = y\n\n"
        "p = Point(1, 2)\nprintf(\"%d\\n\", p.x)\n",
        "is a call to a user-defined `__init__`", tmpdir, verbose)
```

and it reports `body_construction_refusal [arm64] refused: it BUILT a construct
with no representation; the binary is the real answer here` (and the same for
x86-64). Which is the test's own message being wrong: the binary IS the right
answer, and the check is what is stale.

## Why the binary is right, measured

Not "it built" — the answer is right, which is the only thing that makes this
worth filing rather than shrugging at.

| program | formal | Mojo/Python semantics |
|---|---|---|
| `Point(1, 2)` with `__init__` assigning both fields, then `p.x` | `1` | `1` |
| `P(3)` with `__init__` assigning ONLY `x`, then `p.x, p.y` | `3 0` | `3 0` (`y` keeps its class default) |
| the same, a second instance `q = P(7)` | `7 0` | `7 0` |

The unassigned field keeping its class default is the part worth having: the
inlining is not "fill the fields from the arguments", it is "store each of the
constructor's `self.<field> = …` assignments into the fresh block at the
construction site", and a field the constructor does not mention is never
written. `formal/model.py`'s construction refusal says so in its own words
(`This path lowers that call by storing each of the constructor's
self.<field> = … assignments into the fresh block at the construction site, so
what it needs from the body is that it IS a sequence of those`).

**And the inlining is DELIBERATE, which settles that this row is stale rather
than a regression.** `formal/model.py`'s `construction_init_body_refusal` says
it outright, under the heading "What is NOT refused, and the reason it is worth
stating": *"A body that is a straight line of `self.<field> = <expr>` stores is
the same program as the construction followed by those stores, which is the
shape this path has always emitted, so it is inlined rather than refused. That
is what makes `Slice(6, len(lst))` — a call to a two-parameter constructor that
assigns `self.step = None` itself — the answer it is instead of a refusal."*
The test row asserts the opposite of the rule the refusal message documents, so
it was written before that decision and never revisited.

## And the refusal is still there for the bodies that have no representation

This is the half that must not be lost when the test is fixed, because it is the
only reason the row was ever right:

```
$ cat > .tmp/initt/q.mojo
struct P:
    x: Int
    def __init__(self, x):
        self.x = x * 10

p = P(3)
printf("%d\n", p.x)

$ python3 fire.py build --formal --no-prove -o q.aout q.mojo
build: constructing P with arguments is a call to a user-defined `__init__`
whose body this path does not inline: a read of 'x' in the right-hand side — a
name the `__init__` binds or takes, which this body does not substitute for a
construction argument. Only a bare parameter can be …
```

`x * 10` is refused; `self.x = x` is lowered. A test that keeps only the first
row would have stopped pinning the second, which is the one that would be a
silent wrong answer if it regressed (`P(3)` would print `3` where the source
says `30`).

## The second row: `name_in_function`, a REWORDING rather than a lifted refusal

```
$ cat > .tmp/nif/nif.mojo
def f():
    if __name__ == "__main__":
        return 1
    return 0

f()
$ python3 fire.py build --formal --no-prove nif.mojo
build: `__name__ == '__main__'` compares a NUMBER with a string, and the string
comparison this would lower to is `strcmp`, which DEREFERENCES both operands …
```

The row pins `'__name__' has no home`, and the program is still refused on both
backends — by the operand-kind check that fires first, which says something
MORE specific (the right-hand side is a string and the left-hand side is a
number) rather than something less. `test_formal_run.py` already has the mode
for this direction: `refuse_without:`, "the anti-rot direction for a
REWORDING", and its docstring explains why a needle-only `refuse:` is not
enough ("a fix that satisfies it by APPENDING the true sentence and leaving the
false one in place").

Verified pre-existing, not caused by the change that surfaced it: the same
source, built with the tree's own `formal/build.py` at `HEAD` restored from git
into a scratch package copy, refuses identically.

4. **Add a `refuse_without:` mode to `test_formal_toplevel.py`** (or reuse
   `test_formal_run.py`'s, which is a helper in that file rather than a shared
   one) and convert this row to it: the needle becomes `compares a NUMBER with
   a string`, and the row keeps pinning what it is FOR — that `__name__` in a
   FUNCTION is not substituted — which is still true and is the half that must
   not be lost when the words move again.

## The exact next step

1. **Split the row.** Keep a refusal case for a `__init__` whose body is NOT a
   sequence of bare-parameter field assignments (the `q.mojo` shape above —
   the refusal names the read and says why a bare parameter is the only thing it
   can substitute), and turn the current row into a RUNNING case: build it on
   both backends, run it, and require `1` — the `case_refused` helper's
   counterpart for "this now lowers", which `test_formal_toplevel.py` already
   has for the entry-point shape (`ENTRY_POINT_SHAPE`).
2. **Assert the class-default half too**, because it is the part of the
   inlining a field-filling implementation would get wrong: a constructor that
   assigns one of two fields must leave the other at its class default
   (`3 0`, not `3 3`).
3. **Then check whether the inlining has coverage elsewhere.** If
   `test_formal_run.py`'s construction family already pins
   `__init__`-with-a-sequence-of-bare-parameter-assignments inside a FUNCTION,
   then this row is redundant rather than stale, and deleting it is the whole
   fix. Measured either way it must not be left asserting a refusal.

**Checked and NOT this**: not
`bugs/FORMAL_module_state_no_storage.md` (a module-level STORE, which is
refused by name — and is a different question from a construction at a
module-level binding), and not `bugs/FORMAL_wide_receiver_by_reference.md`'s
`__init__` census entry, which is about a container field assigned in an
`__init__` (`self.items = List[Self.T]()`), where the slot cannot hold a list
built by another function. That one is still open; this row is about an `Int`
field assigned from a bare parameter, which is the shape the inlining does
handle.
