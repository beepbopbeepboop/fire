# TEST_formal_specialization_cross_module_case_is_refused_by_the_export_rule: a gate test whose subject is now refused earlier, for a true reason

**Status:** open, unowned. Found 2026-10-03 while running the formal suites for a
change elsewhere (`sweep12:ctor-self-and-singles-a`). **The test is red on this
tree's base commit and was not caused by that change** — measured below against
`c5ab524d` by building the case out of a `git archive` of it.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_specialization.py
#   FAIL  a cross-module specialization is refused by name
#     a cross-module specialization is refused for something other than the
#     brackets:  name like `exit` or `write` is provided by libSystem. …
# formal specialization: PASS=6 FAIL=1
```

And, to be sure the change under test was not the cause, the same test out of an
archive of the base commit:

```sh
mkdir -p .tmp/basefull && git archive c5ab524d | tar -x -C .tmp/basefull
python3 .tmp/basefull/test_formal_specialization.py     # PASS=6 FAIL=1
```

## What the case is, and what it gets

`test_formal_specialization.py::test_a_cross_module_specialization_is_refused`
builds a two-module tree — `lib.mojo` with a generic `widen[x]` and a concrete
`anchor`, `prog.mojo` with `from lib import widen` and `widen[3](5)` — and
asserts three things about the refusal: it names the callee (`widen`), it says
**"brackets cannot be bound"**, and it says why a cross-module instantiation has
no callee here (`monomorph` / "instantiation is the boundary symbol").

It gets the first and refuses with:

```
build: main: `widen` is called, and it is imported from `lib`, so the call has to
bind a symbol `lib` exports. That module does not export it, and the reason is
`doc/ABI.md`'s export rule rather than anything about this call: a name with a
leading `_` is private, **a generic template is not one symbol but one per
instantiation** (`_get_kgen_string[asm]()` is the measured case — both at once),
an overload has no single symbol, and a C library name like `exit` or `write` is
provided by libSystem. …
```

## Why the case can no longer reach its subject

**A generic has no single symbol on this path, so a call to one is refused by
the export rule before the specialization check is ever asked.** That is the same
fact the case wants to demonstrate — a cross-module instantiation has no callee
here — stated at the BINDING rather than at the brackets, and both wordings are
true. The export rule's measurement is
`bugs/FORMAL_known_limits.md` §1.1 (the exclusions) and §1.2 (the generic case).

The case's own docstring already knew the rule was in the way and defended
against it in one direction only: *"The library also exports a CONCRETE
`anchor`, so it builds as a dylib at all: a module exporting only the generic is
refused earlier, by the export rule … That refusal is real and is not what this
case is about."* That defence covers the LIBRARY's dylib gate. It does not cover
the PROGRAM's call, and the program's call is where `widen` is used — so adding
`anchor` made the library buildable and left the call to the generic refused one
layer earlier than the case expects.

## What is left to decide, and by whom

Two honest ways out, and which one is right is a call about what the case is
FOR:

1. **Re-point the expectation at the refusal that is now first.** The case would
   assert that the program is refused, that the message names `widen` as a
   generic template with no single symbol, and that it says why — dropping the
   `"brackets cannot be bound"` needle. That keeps the case testing a real
   property (a cross-module generic cannot be called here) and costs nothing.
   It also loses the coverage of the specialization refusal's own wording for a
   CROSS-MODULE callee, which is the thing the case was written for.
2. **Find a callee that binds and is still generic.** There is none on this path
   — that is the export rule's content — so this option is closed unless the
   export rule changes, which is `FORMAL_dylib_export_loops_and_frame_bounds`
   (`formal10-2`) and not this test's decision.

Between them, option 1 is the smaller change and the one that keeps a true
assertion; the argument for doing it as anything else is that the lost coverage
(the cross-module specialization wording) should be pinned somewhere, and the
answer to that is a case whose callee is generic AND whose brackets are read —
which option 2 says does not exist.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
mkdir -p .tmp/xm && cd .tmp/xm
cat > lib.mojo <<'EOF'
def widen[x: Int32](v: Int32) -> Int32:
    return v * x


def anchor(v: Int32) -> Int32:
    return v
EOF
cat > prog.mojo <<'EOF'
from lib import widen


def main() -> Int32:
    var b = widen[3](5)
    print(b)
    return 0
EOF
python3 "$OLDPWD/fire.py" build --formal --no-prove -o prog.aout prog.mojo
```
