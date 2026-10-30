"""`typing` — the one name of CPython's `typing` this target can answer.

`formal/imports.py`'s FIRST resolution pass finds a `.mojo` source for a name
in a search root and that wins outright, over the host-module list, so this
file is what `import typing` binds to. It lives in `formal/hostmods/`, the
directory that resolver adds as its last search root and that no other
resolver in the tree lists — see `_HOSTMODS_ROOT` for why these did NOT go at
the repository root, where the first three of them captured `import os` in the
compiler's own sources.

THIS MODULE HAS ONE EXPORT, AND THE MEASUREMENT BEHIND THAT IS THE INTERESTING
PART
--------------------------------------------------------------------------
A `typing` module in this tree is one function long because **the formal
backends ERASE ANNOTATIONS**, so every other name in CPython's `typing` is a
spelling in a position this path does not evaluate. Measured, same source
either way:

    # with NO formal/hostmods/typing.mojo at all:
    #   build: user.mojo imports 'typing', which is a host module (CPython
    #   standard library), which has no Mojo source for this backend to compile

    # with this file, which exports ONLY TYPE_CHECKING:
    from typing import Optional
    def f(a: Optional = None) -> int:
        return 7
    def main() -> int:
        return f()
    #   builds, RUNS, and prints 7

The import resolves because the module EXISTS; `Optional` is not in its export
table and nothing checks, because the annotation is erased before the name is
ever read. A program whose `from typing import ...` names this module can
therefore say `Optional[int]` in an annotation and in a DEFAULT, which is
where all of this tree's uses put it, and it will run.

That is a fact about the BACKEND and not a promise this module makes, so it is
stated here rather than left as a trap: a name used as a VALUE is a different
question. `x = Optional[int]` is a subscript of a module-level name, and
`bugs/FORMAL_module_state_no_storage.md` is why a module-level name is not
exported as a word — so that program is refused, which is correct and is not
something this file could fix by declaring `Optional`.

WHAT IS NOT HERE, AND WHY
-------------------------
  * `Optional`, `Union`, `Any`, `List`, `Dict`, `Set`, `Tuple`, `Callable`,
    `Iterable`, `Type`, `ClassVar`, `Final`, `Annotated`, `Literal`,
    `Protocol`, `Generic`, `TypeVar`, `TypedDict`, `NamedTuple`, `NoReturn`,
    `Never`, `Self`, `LiteralString`, `TypeAlias`, `Concatenate`,
    `ParamSpec`, `Unpack`, `Required`, `NotRequired`, `ReadOnly`,
    `runtime_checkable`, `assert_never`, `cast`, `overload`, `final`,
    `get_args`, `get_origin`, `get_type_hints`, `reveal_type`,
    `TYPE_CHECKING` as a subscript — TYPES. A type is not a value on this path
    and cannot be returned from a module function, let alone stored in a
    module-level name (`bugs/FORMAL_module_state_no_storage.md`).
    `formal/elf.py:25` imports `Optional` and `type_system.py:13` imports
    `Optional, Dict, Set, Tuple, Any` — six imported names across the two
    files, five of them distinct, and every one of the six appears in an
    annotation (`formal/elf.py:194` puts `Optional` on a parameter that also
    has a default), which is why this module is one function long and why
    those two files are unblocked by its EXISTENCE. The counts are stated with
    the file and line they are read from, because a count that is only in a
    docstring is a count that rots: `test_formal_small_hosts.py` checks the two
    SHAPES, which is the part that matters, and re-reading the two import
    lines is a two-second check that keeps the sentence true.
  * the submodules `typing_extensions`, and the `collections.abc`-backed
    `io`, `re`, `os` protocol names — each is a module or a protocol class, and
    a protocol class is a type.

WHAT IS HERE
------------
  * `TYPE_CHECKING()` — the one name whose answer is a VALUE and is checkable.
    It is False at run time in CPython, so every `if TYPE_CHECKING:` block in
    a program is skipped here, and skipping it is the correct answer rather
    than an approximation: such a block exists to hold annotations and
    TYPE_CHECKING-only imports, and this path erases annotations. It is a
    FUNCTION for the reason every constant in this directory is: a
    module-level name is not exported as a word
    (`bugs/FORMAL_module_state_no_storage.md`).
"""

def TYPE_CHECKING() -> int:
    """`typing.TYPE_CHECKING`: 0, i.e. False.

    False at run time in CPython, and False here. Checked against CPython's
    own `typing.TYPE_CHECKING` by `test_formal_small_hosts.py`, which also pins
    the two things this module's existence buys — a `from typing import
    Optional` in a DEFAULT, and one in an ANNOTATION — because those are the
    shapes `formal/elf.py` and `type_system.py` use and neither is exercised by
    anything else in the tree.
    """
    return 0
