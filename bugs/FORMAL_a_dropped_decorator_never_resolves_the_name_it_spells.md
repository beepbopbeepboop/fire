# FORMAL_a_dropped_decorator_never_resolves_the_name_it_spells: `@functools.lru_cache(maxsize=1)` BUILDS the moment `functools` becomes a module, and no reader asks whether the name exists

**Area:** FORMAL (decorator handling, shared by both backends). Found 2026-10-05 on
`work/formal23-4`, while trying to land `formal/hostmods/functools.mojo` for
`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md` and finding that the
one thing standing between the two is not the capability the doc names.

**Status: NOT FIXED, and it is the gate on a class of host modules. The
reproduction below is a REAL `formal/hostmods/functools.mojo`, not a stub —
written, measured, and then not landed, because landing it turns a refusal into
a program that runs and skips the work it asked for.**

## What was run

`formal/hostmods/functools.mojo` exporting the one name whose requirements are
all met (`reduce`, a fold through a code address over a counted blob), and
`functools` removed from `formal/imports.py`'s host-module set so the import
resolves to it. Every row is arm64; the refusals are byte-identical on x86-64.

```console
$ cat .tmp/ft/dec.mojo
import functools

def fib(n: int) -> int:
  if n < 2:
    return n
  return fib(n - 1) + fib(n - 2)

@functools.lru_cache(maxsize=1)
def counted(n: int) -> int:
  return fib(n)

def main() -> int:
  printf("%d\n", counted(10))
  return 0

$ python3 fire.py build --formal --no-prove -o .tmp/ft/dec .tmp/ft/dec.mojo
Built: .tmp/ft/dec  [arm64/macho]          # exit 0, prints 89
```

The same program **without** `formal/hostmods/functools.mojo` is refused by the
import, so this is a change of verdict caused by adding a module, not by
changing a decorator. It is exactly the outcome
`test_formal_core_hostmods.py`'s `functools-absent` group exists to prevent, and
that group's own comment names the shape: *"If a functools module ever lands,
THIS is the program that runs and skips the work it asked for, so the group
asserts it is refused rather than trusting the import to be."*

## What was expected, and where the reader is missing

**The bare attribute read refuses, and the DECORATOR spelling does not** — the
same name, two answers, and the difference is that one of them is an expression
this path lowers and the other is an expression this path never looks at:

```console
$ printf 'import functools\n\ndef main() -> int:\n  functools.lru_cache\n  return 0\n' > .tmp/ab.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/ab .tmp/ab.mojo
build: main: functools.lru_cache reads 'lru_cache' out of the imported module
  `functools`, and a module is not a value this path can place: … What
  `functools` publishes: reduce. `formal/hostmods/sys.mojo`'s own module
  docstring says which of those names it deliberately does not declare and why …
```

That message is exactly right, and it is the one a reader wants. So the refusal
machinery is in place and knows the module's export list; **the decorator
expression never reaches it.** `grep -rn "\.decorators" formal/` returns
NOTHING: neither backend nor `formal/build.py` reads a definition's decorator
list at all. `@x` is parsed into the node and dropped on the floor before any
name is resolved, so the question "does this name exist" is never asked of a
decorator — and a decorator is the one place where a name the source wrote is
guaranteed to have no effect if it is wrong.

This is `bugs/COMPILE_FAIL_decorator_application_dropped.md`'s general finding
("a decorator is parsed and never applied") seen from the side that matters for
a module: **not being applied is only safe while every decorator a caller can
spell is already a refusal.** The moment a module publishes a name, a caller can
put that name where nothing checks it.

## What is NOT claimed, and the one row that constrains the fix

The obvious fix — *a decorator naming an imported module's absent export is
refused* — **breaks a pinned, passing row**, which is the whole reason this doc
is not a two-line change:

```python
# test_dataclasses_formal.py, EXEC_CASES
("dotted_dataclasses_decorator_spelling", DOTTED_DECORATOR),   # @dataclasses.dataclass
```

`@dataclasses.dataclass` builds and runs today, and it builds **for the same
reason** `@functools.lru_cache` would: the decorator is dropped and the name is
never resolved. There is no `formal/hostmods/dataclasses.mojo`, so `dataclasses`
publishes nothing either — the two decorators are indistinguishable to any check
that only looks at whether the module exports the name.

It is RIGHT that `@dataclasses.dataclass` works, and for a reason this path can
own: `formal/dataclass_transform.py` desugars the class where the class is
(`decorator_target(d)` matches the TRAILING name, so `@dataclass` and
`@dataclasses.dataclass` are both consumed), and the class it produces is a
genuine dataclass — field-wise `==`, `field(default=…)` folded to its literal,
generated `__init__` argument order. That is premise (2) of
`formal/dataclass_transform.py`'s own docstring ("a decorator applied to a class
is DROPPED, silently, by both backends … so `@dataclass` has to be handled where
the class is"). So the check is not "a dotted decorator must resolve"; it is
**"a decorator this path cannot apply, and has not transformed, must not be
silently ignored"** — and the transform that consumes one has to run first.

## The exact next step

A pre-pass beside `formal/build.py:2286`'s `check_dataclass_constructs` (which
already refuses a `@dataclass` OPTION it cannot lower, so the shape is there),
running AFTER `DC` has consumed the decorators it owns, which for every
definition:

1. takes each decorator expression to its callee (`CallExpr.func` or the name),
2. and if that callee is a MEMBER read of an imported module — the one shape a
   local function or a builtin name cannot produce — asks the SAME export map
   the bare attribute read asks, so `@functools.lru_cache` gets the message
   above and `@os.getcwd` gets whatever that one gives.

The narrowness is the point and it should stay narrow: a bare `@deco`, `@property`,
`@staticmethod` and `@dataclasses.dataclass` must all keep building exactly as
they do today, because the first three are names the image can place and the
fourth is consumed by the transform. The tests to move together are
`test_formal_core_hostmods.py`'s `functools-absent` (whose decorator row starts
passing because of this and not because the import refuses) and
`test_dataclasses_formal.py`'s `dotted_dataclasses_decorator_spelling` (which
must keep passing, and is the row that says the check is a check and not a
blanket refusal).

**Then** `formal/hostmods/functools.mojo` can land its `reduce`, and
`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md` is one step from
closed rather than two.

## What is measured here, precisely

* `@functools.lru_cache(maxsize=1)` builds, exit 0, prints CPython's 89 — with a
  real `functools.mojo` present, arm64.
* `functools.lru_cache` as a plain attribute read is refused, naming the module,
  the missing name, and what the module publishes — arm64 and x86-64.
* `functools.reduce(mul2, [1, 2, 3, 4], 1)` answers 24 where CPython answers
  24, and `reduce(add2, [1, 2, 3, 4], 0)` answers 10, `reduce(add2, [7], 100)`
  answers 107, `reduce(add2, [], 5)` answers 5 — all four on BOTH architectures.
* `functools.reduce(add2, [1, 2, 3, 4])` (CPython's two-argument form) is
  refused with `missing required argument 'initial'` on both, because a default
  is not materialised across a dylib boundary
  (`FORMAL_default_argument_not_applied_across_a_dylib`) and an `initial = 0`
  default would answer 0 where CPython answers 24. Measured with a probe module:
  a defaulted `initial` is a silent wrong answer, not a missing value.
* `@dataclasses.dataclass` builds and prints `p=3,4`, on a tree with no
  `formal/hostmods/dataclasses.mojo` — so the two decorators are the same shape
  to every reader that is not the dataclass transform.
* Nothing here was measured with Lean, and nothing here needs it: every row is a
  build verdict or a program's own output.
