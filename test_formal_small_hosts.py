#!/usr/bin/env python3
"""Build `io` and `typing` for the formal backend and RUN them against CPython.

    python3 test_formal_small_hosts.py [-v] [group ...]

TWO MODULES IN ONE FILE, and the reason is that both are the same shape: a
handful of names whose answers are numbers, and a file each that wanted one of
them. A test file per four-constant module would be more ceremony than the
module.

  * `formal/hostmods/io.mojo` — CPython's `io` without its streams. The
    streams are gone because a stream is a descriptor, a cursor and a buffer,
    and a value cannot cross a dylib boundary unless it is one 64-bit word;
    `sys.mojo` already says the same about `sys.stdout`, and `io` is those
    streams one level up. What is left is `SEEK_SET` / `SEEK_CUR` / `SEEK_END`
    and `DEFAULT_BUFFER_SIZE`, and every one is checked against CPython's own
    `io`.
  * `formal/hostmods/typing.mojo` — ONE function, `TYPE_CHECKING`, and the
    measurement behind why one is the right number is the interesting part of
    that module: the formal backends ERASE ANNOTATIONS, so a
    `from typing import Optional` resolves as soon as the module EXISTS, and
    `Optional` need not be in its export table at all because nothing ever
    reads the name. `formal/elf.py` imports it and `type_system.py` imports six
    names, and all seven uses are in annotations or in a default — which is why
    the module is one function and why those two files are unblocked by its
    existence rather than by anything it declares.

Groups: `io`, `typing`, `resolve`, `absent`. With no argument, all.
"""
import argparse
import io
import os
import platform
import subprocess
import sys
import tempfile
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

from test_formal_json import Failure, build, check, run  # noqa: E402
import test_formal_json as J  # noqa: E402

TEMP = None

# What each module exports, and the CPython answer for each. `getattr` on the
# live module, so the oracle is the interpreter's own value and not a number
# typed here — which is the whole point of the comparison, and the reason this
# table is a table of NAMES.
IO_ANSWERS = [("SEEK_SET", io.SEEK_SET), ("SEEK_CUR", io.SEEK_CUR),
              ("SEEK_END", io.SEEK_END),
              ("DEFAULT_BUFFER_SIZE", io.DEFAULT_BUFFER_SIZE)]


def group_io(tmpdir, verbose):
    """`io`'s four names, each against CPython's own `io`.

    `%lld` and not `%d` for the same reason every other test in this tree uses
    it: a `%d` conversion is 32 bits wide on this path
    (`bugs/FORMAL_string_value_model.md` §2), and `DEFAULT_BUFFER_SIZE` is
    small enough that it would not have shown — which is worth saying, because
    the first version of this group printed it with `%d` and passed.
    """
    src = ["import io", "", "def main():"]
    for name, _ in IO_ANSWERS:
        src.append(f'    printf("%lld@@", io.{name}())')
    got = run(build("\n".join(src) + "\n", "io_consts"))
    got = [g for g in got.split("@@") if g != ""]
    check(len(got) == len(IO_ANSWERS),
          f"io: image reported {len(got)} of {len(IO_ANSWERS)} answers")
    bad = [(n, g, w) for (n, w), g in zip(IO_ANSWERS, got) if int(g) != w]
    check(not bad, "io: " + (f"{len(bad)} name(s) differ from CPython; "
                            f"first: {bad[0][0]} image {bad[0][1]} CPython "
                            f"{bad[0][2]}" if bad else ""))
    if verbose:
        print(f"    {len(IO_ANSWERS)} names, each against CPython's own io")
    return True, f"{len(IO_ANSWERS)} io names agree with CPython"


def group_typing(tmpdir, verbose):
    """`TYPE_CHECKING`, and the two shapes its EXISTENCE buys.

    The constants half is one comparison. The other half is the measurement
    that makes the module one function long, and it is the reason the group
    exists at all: a `from typing import Optional` resolves when the module
    exists even though `Optional` is in nobody's export table, because the
    annotation is erased before the name is read. That is a fact about the
    BACKEND, so it is pinned here rather than left as a claim in a docstring
    that nobody will re-run.
    """
    # (1) TYPE_CHECKING, against CPython's own.
    got = run(build("import typing\n\ndef main():\n"
                    '    printf("%d@@", typing.TYPE_CHECKING())\n',
                    "typing_tc"))
    got = [g for g in got.split("@@") if g != ""]
    check(len(got) == 1, f"TYPE_CHECKING: image reported {len(got)} answers")
    check(int(got[0]) == int(typing.TYPE_CHECKING),
          f"TYPE_CHECKING: image {got[0]}, CPython "
          f"{int(typing.TYPE_CHECKING)}")

    # (2) the shapes this tree actually uses: an annotation and a default, both
    # naming a module that does not export that name.
    src = """from typing import Optional

def annotated(a: Optional = None) -> int:
    return 7

def annotated_only(a: Optional[list[str]], b: dict[str, int]) -> int:
    return 9

def main() -> int:
    printf("a=%d@@", annotated())
    printf("b=%d@@", annotated_only(None, {}))
"""
    got = run(build(src, "typing_erased"))
    got = [g for g in got.split("@@") if g != ""]
    check(got == ["a=7", "b=9"],
          f"a typing annotation in a default or a signature changed the "
          f"answer: {got!r} (the backend erases annotations, so both must be "
          f"the functions' own bodies)")

    # (3) and the shape that is NOT erased, so a reader knows where the edge
    # is: a subscript in a STATEMENT is a real expression and is refused.
    r = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "-o", os.path.join(TEMP, "typing_value"), _write(
             "typing_value.mojo",
             "from typing import Optional\n\ndef main() -> int:\n"
             "  x = Optional[int]\n  return 0\n")],
        capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode != 0,
          "a typing name used as a VALUE built, but the module's docstring "
          "says the backend erases annotations and this does not — either the "
          "erasure claim is wrong or the backend changed")
    if verbose:
        print("    TYPE_CHECKING against CPython, plus 2 annotation shapes "
              "and the 1 that is not erased")
    return True, "TYPE_CHECKING and the erased-annotation shapes agree"


def _write(name, text):
    p = os.path.join(TEMP, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def group_resolve(tmpdir, verbose):
    """Both modules resolve where `formal/imports.py` says, and left the set.

    The `HOST_MODELLED` half matters for the same reason it does in
    `test_formal_json.py`: that set is a CLAIM that the module could be
    written, and a name leaves it by being written, because an entry left
    behind would refuse a file after the module that answers it is in the tree.
    """
    import formal.imports as I
    for mod, test in (("io", "test_formal_small_hosts.py"),
                      ("typing", "test_formal_small_hosts.py")):
        path = os.path.join(HERE, "formal", "hostmods", mod + ".mojo")
        check(os.path.isfile(path), f"no Mojo source for {mod}")
        got = I.resolve_module_path(mod)
        check(got is not None and os.path.samefile(got, path),
              f"import {mod} resolves to {got!r}, not {path!r}")
        check(I.host_module_tier(mod) == "",
              f"{mod} is still in HOST_MODELLED; its Mojo source exists, so "
              f"the entry is now a false statement about the target")
    if verbose:
        print("    both resolve into formal/hostmods/, both out of the set")
    return True, "io and typing resolve, and both left HOST_MODELLED"


def group_absent(tmpdir, verbose):
    """The absent names of each, asserted as refusals.

    `io`'s are streams and types and `typing`'s are types, and both modules'
    docstrings say which capability each group needs. An omission that is not
    pinned is indistinguishable from an implementation, so each is pinned as a
    build that fails with a message naming the module and the name.
    """
    absent = [("io", n) for n in ("open", "open_code", "StringIO", "BytesIO",
                                  "FileIO", "TextIOWrapper", "IOBase",
                                  "BlockingIOError", "UnsupportedOperation",
                                  "Reader", "Writer", "GenericAlias",
                                  "text_encoding", "DEFAULT_NEWLINE",
                                  "BLOCK_SIZE", "MAX_BUFFER_SIZE")]
    absent += [("typing", n) for n in ("Optional", "Union", "Any", "List",
                                       "Dict", "Set", "Tuple", "Callable",
                                       "get_type_hints", "get_args",
                                       "get_origin", "cast", "overload",
                                       "final", "TypeVar", "Protocol",
                                       "Generic", "NamedTuple",
                                       "TypedDict", "runtime_checkable",
                                       "assert_never", "reveal_type")]
    for mod, name in absent:
        # A CALL, not a bare name. A bare `io.open` is a read of a
        # module-level name, which is refused for a DIFFERENT and vaguer
        # reason ("a module-level name is not exported as a word") and does
        # not name the name being asked for — so the first version of this
        # probe passed the build and failed its own assertion, which is the
        # shape of a test that checks the wrong thing.
        src = (f"import {mod}\n\ndef main() -> int:\n"
               f"  {mod}.{name}(0)\n  return 0\n")
        tmp = _write(f"absent_{mod}_{name}.mojo", src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_{mod}_{name}"), tmp],
            capture_output=True, text=True, timeout=J.BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"{mod}.{name} resolved, but the module documents it as absent "
              f"— either the docstring is wrong or the module grew a name")
        msg = r.stderr or r.stdout
        check(name in msg,
              f"{mod}.{name} failed without naming itself: "
              f"{msg.strip()[-300:]}")
    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


GROUPS = {
    "io": group_io,
    "typing": group_typing,
    "resolve": group_resolve,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        J.TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                import traceback
                if args.verbose:
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
