"""`enum` — the bases and the member accessors, for the formal backend.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name in
a search root and that wins outright, over the host-module list, so this file is
what `import enum` binds to. It lives in `formal/hostmods/`, the directory that
resolver adds as its last search root and that no other resolver in the tree
lists — see `_HOSTMODS_ROOT` for why these did NOT go at the repository root,
where the first three of them captured `import os` in the compiler's own sources.

WHAT AN ENUM IS ON THIS PATH, AND WHY THE MODULE IS ALMOST EMPTY
---------------------------------------------------------------
CPython's `enum` is a metaclass (`EnumType`) plus a decorator plus a set of
helpers. **None of that machinery is representable here, and none of it is
needed**, because on this path an enum member is not an object at all:

    class Reg(Enum):
        RAX = 0        # a CLASS-LEVEL CONSTANT, and one word

The class body is lowered as what it literally is — a class-level constant — and
a read of `Reg.RAX` materializes the literal `0` at the use site
(`formal/build.py`'s `_rewrite_class_constants`, which is a source-to-source
rewrite in the shared pipeline precisely so the two architectures cannot
disagree). The base class name is what the enum MACHINERY is, and this path never
runs it: measured on this tree, `class Reg(Enum)` builds and reads its members
correctly with **no `enum.mojo` at all** — the base name is erased along with the
annotations, and the members are ordinary class constants either way.

So what this module is FOR is the thing a file cannot do without: **existing**.
`formal/lean.py`, `type_system.py` and `formal/x86_64.py` each `from enum import
Enum` at the top, and with no source for the name the build stops there —

    build: type_system.py imports 'enum', which is a host module (CPython
    standard library), which has no Mojo source for this backend to compile

— a diagnostic whose subject is a standard-library module rather than anything
in the file. Measured on this tree before and after this file, arm64:

| file | with no `enum` source | with this one |
|---|---|---|
| `type_system.py` | refuses on `import enum` | refuses on `Type.origin`'s default, which is `TypeOrigin.DEFAULT` — a real finding about a dataclass default |
| `formal/x86_64.py` | refuses on `import enum` | refuses on `base.value` in `_rm_disp` — a real finding about a parameter's type |

Both move off a fact about the TARGET and onto something about the FILE, which is
the whole value of a module in this directory. What they do NOT do is build, and
the reason is in each refusal rather than here.

THE ONE THING THIS MODULE HAS TO EXPORT, AND WHY IT IS A FUNCTION
-----------------------------------------------------------------
`Enum` itself, and it is a zero-argument FUNCTION returning 0 for the reason
every constant in this directory is one: a module-level name is not exported as a
word (`bugs/FORMAL_module_state_no_storage.md`), so `os.sep` and `io.SEEK_SET`
are functions too. Its VALUE is never read — the base is erased — so what it
returns is not a claim about `Enum`, it is the smallest thing that satisfies the
export rule. `test_formal_enum.py` pins that: the module builds, a program that
derives from `Enum` builds, and its members read as their own literals.

**`.value` AND `.name` ARE NOT IN THIS FILE.** They are the enum's whole reason
for existing, and they are answered in `formal/model.py`
(`enum_member_accessor`) and `formal/build.py` (`_enum_member_sites`), not here —
because `Reg.RAX.value` is not a call into this module, it is an attribute read
on a class constant, and it was silently answering **0** before that fix:

    class Reg(Enum):
        RAX = 0
        R15 = 15
    printf("%d %d\n", Reg.R15.value, Reg.RAX.value)   # was: 0 0

where CPython prints `15 0`. That is a wrong answer rather than a refusal, and it
is why the fix had to land before this module could be honest: `formal/x86_64.py`
does its register-number arithmetic through `.value`, so an image built with the
answer wrong there emits wrong machine code and exits 0.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `auto()` — answers a MEMBER, so its value is 1, 2, 3… in DECLARATION ORDER,
    which is a count of the class body's own statements and not a value the source
    writes down. A formal value is one word with nowhere to keep a non-literal one,
    so `A = auto()` is refused by name at the read (measured, and it is the right
    answer: the alternative would be 0, and `A` would silently be the first
    member's value on every member).
  * `unique`, `verify`, `global_enum`, `show_flag_values` — DECORATORS. Measured
    on this tree, a decorator on a function OR a class is DROPPED, silently, by
    both backends (`bugs/COMPILE_FAIL_decorator_application_dropped.md`), so
    exporting them would make `@unique` build and enforce nothing. That is the
    worst outcome available and it is why none of them is here.
  * `EnumMeta`, `EnumType`, `EnumDict`, `EnumCheck` — TYPES. A type is not a value
    on this path (`formal/hostmods/typing.mojo` says the same about `Optional`).
  * `IntEnum`, `StrEnum`, `Flag`, `IntFlag`, `ReprEnum`, `member`, `nonmember` —
    all TYPES or type-constructing helpers, for the reason above. They are
    RECOGNIZED as bases (`model.ENUM_BASES`) so `class Reg(IntEnum)` gets the same
    `.value` / `.name` answer `class Reg(Enum)` does, which is the half of them
    this path can express; the name itself does not have to be in the export table
    for that, exactly as `Enum` did not have to be before this file existed.
  * `property`, `unique` as used at class scope, and the `_missing_` hook — the
    enum machinery proper.
"""


def Enum() -> int:
    """`enum.Enum`: the base every enum class names, as an erased base.

    CPython's is a class; this is a zero-argument function because a module-level
    name cannot be exported as a word on this path, and its value is never read —
    `class Reg(Enum)` lowers the base away, which is what makes `Reg.RAX` an
    ordinary class constant with an ordinary literal.

    The 0 is not a claim about CPython's `Enum` (which has no integer value). It
    is the smallest answer that satisfies `doc/ABI.md`'s export rule, and
    `test_formal_enum.py` asserts the thing that actually matters — that a class
    deriving from it builds and its members read as their own literals — rather
    than pinning a number whose being wrong would change no program.
    """
    return 0
