#!/usr/bin/env python3
"""Module-global state: build the image, RUN it, and check the answer.

`test_formal_run.py` covers expressions; this covers state that lives in the
module rather than in a frame, and it exists because of a specific way that goes
wrong. Before module-global storage existed, `GlobalStmt` was a no-op in both
backends, so

    G = 5
    def bump():
        global G
        G = G + 1

compiled, linked, and PRINTED 5 — the write landed in a dead register and the
read was folded to the module's constant. Nothing failed. The proof obligations
were discharged; the binary was wrong. So every case here is executed, and the
number it produces is the assertion.

THREE ENGINES PER CASE. A module global is the one feature in this backend whose
correctness depends on a second module agreeing about where a slot lives — the
codegen computes an address, the linker maps a segment, and nothing in between
checks them. That is exactly the class of defect where one architecture can be
right and the other wrong with both green elsewhere, and it was not
hypothetical: an x86-64 image whose `__DATA` was addressed RIP-relative ran
correctly under lldb and died of SIGSEGV standalone, because the loader slides
the image and `GLOBALS_VM` is a fixed address.

So each case runs the same source three ways and requires all three to agree:

  * `fire.py run` — the Mojo interpreter, which is the reference SEMANTICS. It
    shares no code with the formal backend below the parser, so agreement is
    evidence rather than a tautology.
  * the arm64 image, natively.
  * the x86-64 image, under Rosetta.

Requiring the backends to agree with each other is not redundant with the
interpreter comparison: the interpreter has no `__DATA`, no slot index and no
image, so a whole class of bug (address arithmetic, segment placement, lazy
initialization ordering) is invisible to it and can only be caught by two
independent codegens landing on the same number.

`FRAME_CASES` and `FRAME_REFUSALS` are the module-level STRUCT group, and they
are the sharpest use of that three-way agreement in the file. Every other case
stores an int or a container into eight bytes of static image; a module-level
`X = Struct(...)` is the one binding whose value does not fit in a word, and it
used to be the address of a block the module BODY had already returned from —
a lifetime defect rather than a gap, which no printed number can distinguish from
a correct frame and which the interpreter could never have caught (it stores a
real object). So those rows are the ones where the two architectures and the
interpreter are all necessary and none is sufficient.

    python3 test_formal_globals.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

# (name, source, expected stdout)
#
# `print` rather than `printf`, because `printf` is not in the interpreter's
# namespace and a case that only ran on the images would have no reference to
# compare against. The formal arm64 path also refuses to `print` a bare
# `IdentExpr` — it cannot tell a string from a number and guessing would print
# an address as if it were text — so each case binds the global to an annotated
# local first. That annotation is not incidental: it is the ordinary Mojo way to
# say what a name holds, and every case below uses it.
#
# The expected answer may be a callable of (tmpdir, name) instead of a string;
# `run_case` calls it, and `__file___is_the_source_the_build_was_handed` is the
# one case that needs it, for the reason its own comment gives.
def __file__case(tmpdir, name):
    """`<__file__>`, `<dirname(__file__)>`, `<dirname(dirname(__file__))>`.

    The three lines `tools/bootstrap_verify.py:31` computes and this file's
    last case prints, with the path the RUNNER chose for the source.  Not
    written down as a literal because it is not the same path twice: it is
    `<tmpdir>/<case name>.mojo`, and `tmpdir` is a fresh `TemporaryDirectory`
    per run.
    """
    path = os.path.join(tmpdir, name + ".mojo")
    here = os.path.dirname(path)
    return f"{path}\n{here}\n{os.path.dirname(here)}"


CASES = [
    # ── the case this whole capability exists for ──
    # The measured wrong answer before module-global storage was 5. The write
    # reached a dead register, the read was constant-folded to the module
    # initializer, and the image exited 0 the whole time.
    ("write_int_through_global",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    global G\n"
     "    G = G + 1\n"
     "\n"
     "def main(n):\n"
     "    bump()\n"
     "    bump()\n"
     "    g: Int = G\n"
     "    print(g)\n"
     "    return 0\n", "7\n"),

    # A function that TOUCHES the global but does not write it still has to see
    # the current value, which is the lazy initializer's other half: the check
    # has to run before the read, not only before a write.
    ("read_int_through_global",
     "G = 41\n"
     "\n"
     "def get():\n"
     "    global G\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    bump: Int = get()\n"
     "    print(bump)\n"
     "    return 0\n", "41\n"),

    # THE CONTROL for the row above, and the one that would catch an
    # over-correction: a name assigned WITHOUT `global` binds a local, so the
    # module's value must survive it. This is not a restatement — before the
    # gate in `_module_global` was drawn at the function's local set rather than
    # at "does the name have a slot", `bump_local`'s store went to `__DATA` and
    # this case printed 99-then-5 where CPython says the module is untouched.
    # A function silently writing a variable it never declared is the failure
    # mode, and nothing else in the suite would catch it.
    #
    # `bump_local` never READS `G`, which is deliberate and is the limit of what
    # is asserted. `G = G + 1` with no `global` is a different question, and the
    # row below answers it.
    #
    # `set_it` exists so the name does have a slot at all: with no `global`
    # write anywhere in the module, `G` is a read-only module constant and this
    # case would be testing the folding path instead of what it is for.
    ("assign_without_global_is_local",
     "G = 5\n"
     "\n"
     "def bump_local():\n"
     "    var G = 99\n"
     "\n"
     "def set_it():\n"
     "    global G\n"
     "    G = 100\n"
     "\n"
     "def main(n):\n"
     "    bump_local()\n"
     "    g: Int = G\n"
     "    print(g)\n"
     "    set_it()\n"
     "    h: Int = G\n"
     "    print(h)\n"
     "    return 0\n", "5\n100\n"),

    # Two globals, both written, in an interleaved order that matters: if the
    # slots were assigned in the order the WRITES appear rather than in
    # declaration order, one of these would land in the other's slot and the
    # two numbers would come out swapped.
    ("two_globals_interleaved",
     "A = 1\n"
     "B = 10\n"
     "\n"
     "def bump_a():\n"
     "    global A\n"
     "    A = A + 1\n"
     "\n"
     "def bump_b():\n"
     "    global B\n"
     "    B = B + 1\n"
     "\n"
     "def main(n):\n"
     "    bump_b()\n"
     "    bump_a()\n"
     "    bump_a()\n"
     "    a: Int = A\n"
     "    b: Int = B\n"
     "    print(a)\n"
     "    print(b)\n"
     "    return 0\n", "3\n11\n"),

    # ── where the substitution is READ from ──
    #
    # Every case above reads a module-level name in a position the substitution
    # already covered — as a return value, as an argument, on the right of a
    # binop. These two read it from the one position it did NOT cover, and the
    # gap was live on master: `_apply_module_constant_sites` rewrote in place,
    # so a bare `IdentExpr` — which has no child slots, its fields being `name`,
    # `line` and `col` — was walked straight through and left alone. Every
    # other position reached the replacement through a list element or through
    # `_rewrite_child`, which is why the substitution looked complete and was
    # not: `G = 7` then `x = G` inside a function was refused with
    # "'G' has no home" on BOTH architectures, for a construct the build
    # answers. Fixed in `formal/build.py` (the AssignStmt/VarDecl/AugAssign
    # value side goes through `_rewrite_child`, which returns a replacement).
    #
    # `read_global_as_an_assignment_value` is the plain shape;
    # `read_global_into_a_field_store` is the one that matters, because a
    # `MemberExpr` store target is the shape this backend uses for every struct
    # field write, so the uncovered position was reached by ordinary code
    # rather than by an assignment to a bare local.
    ("read_global_as_an_assignment_value",
     "G = 7\n"
     "\n"
     "def main(n):\n"
     "    x = G\n"
     "    y: Int = G\n"
     "    print(x)\n"
     "    print(y)\n"
     "    return 0\n", "7\n7\n"),

    # EVERY position a scalar module constant can be read in, in one case, and
    # it is here because `read_global_as_an_assignment_value` covers only the
    # two flat ones. The four added here are the ones a module of this tree
    # actually wants to write, and each was a REFUSAL once: a module-level
    # `A = 34` bound to a local inside a function was refused with "'A' has no
    # home: the register allocator collected no home for it", on both
    # architectures, while `return A` and `f(A)` in the same module built. The
    # refusal named the allocator when the real disagreement was between
    # two walks — one collected homes for the names a function BINDS, the other
    # expected a home for a name it only READS — and the reader was sent to the
    # register allocator for a fact about the constant substitution.
    #
    # All five spellings are in one case because three of them working is not
    # the claim: a fix that reached `var y = A` and left `y = A` alone would pass
    # any one of them separately. And the `if` arm is the shape that turned the
    # fix on — a read whose RESULT is assigned, in a body the constant walk had
    # to reach through the branch.
    ("scalar_module_constant_in_every_read_position",
     "A = 34\n"
     "\n"
     "def k1(x) -> Int:\n"
     "    var y = 0\n"
     "    if x == A:\n"
     "        y = A\n"
     "    return y\n"
     "\n"
     "def k2() -> Int:\n"
     "    var y = 0\n"
     "    y = A\n"
     "    return y\n"
     "\n"
     "def k3() -> Int:\n"
     "    var y = A\n"
     "    return y\n"
     "\n"
     "def k4() -> Int:\n"
     "    return A\n"
     "\n"
     "def k5(n: Int) -> Int:\n"
     "    return A + n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    a: Int = k1(34)\n"
     "    b: Int = k1(0)\n"
     "    c: Int = k2()\n"
     "    d: Int = k3()\n"
     "    e: Int = k4()\n"
     "    f: Int = k5(8)\n"
     "    print(a)\n"
     "    print(b)\n"
     "    print(c)\n"
     "    print(d)\n"
     "    print(e)\n"
     "    print(f)\n"
     "    return 0\n",
     "34\n0\n34\n34\n34\n42\n"),

    ("read_global_into_a_field_store",
     "struct Wrap:\n"
     "    v: Int\n"
     "\n"
     "G = 7\n"
     "\n"
     "def main(n):\n"
     "    w = Wrap()\n"
     "    w.v = G\n"
     "    x: Int = w.v\n"
     "    print(x)\n"
     "    return 0\n", "7\n"),

    # The THIRD position where a name is a READ and the walk that folds module
    # constants treated the enclosing node as a store, after `x = G` and the
    # `elif` arm above. `out[K] = v` stores into `out` and READS both `out` and
    # `K`, and the walk skipped the whole target — so `K` reached the emitter as a
    # bare `IdentExpr` and the build refused "'K' has no home" on BOTH
    # architectures, blaming the register allocator for a disagreement between
    # two walks. Measured on `tools/memslot.py:held_env`
    # (`bugs/FORMAL_proof_coverage_census_2026-10-03.md` §0.6's round-2
    # census), whose `out[POOL] = str(pool)` is this shape exactly.
    #
    # Four shapes in one case, because "the index of a store target is a read"
    # is one rule and the four are the four places it can be written: a bare
    # subscript store, an AUGMENTED one (whose target walk is a separate
    # statement type), a MULTI-assign, and a constant read in a body the walk
    # has to reach through a branch. The dict subscript is the one that RUNS —
    # a list indexed by a string has no meaning, so it is a refusal rather than
    # a number, and the refusal it earns now names the SUBSCRIPT (`xs['k']`)
    # instead of the constant.
    # A module constant whose initializer is an OPERATOR, which is how this
    # repository's own source spells one: `1 << 20` is a bit mask,
    # `2 ** 62 - 1` is `MAX64`, `MASK & n` is the third of a family. Only four
    # arithmetic operators were folded (`+ - * //`) and no bitwise or shift among
    # them, so a constant written any other way read as `rebound` rather than
    # `assigned`, reached the emitter as a bare `IdentExpr`, and was refused —
    # with a message about PRINT's materialization, for a name the build had read
    # and simply could not fold. Measured on `test_formal_math.py:isqrt_source`
    # by the proof-breadth census, where it also made the two backends report
    # different subjects for one function.
    #
    # All thirteen in one case, and the numbers are the assertion: a fold that
    # got three of the six operators right would build and print wrong ones.
    # Three of the thirteen are there because of WHERE the range check lives:
    # `BIG` and `MINV` are the word's own top and bottom values, and their
    # intermediates (`2 ** 63`) are not words, so a folder that checked each
    # operator as it went would refuse exactly the two constants that are
    # representable. `REF` reads an EARLIER module-level binding through `>>`,
    # which is the one operator here whose answer is not a function of the low
    # 64 bits and so is the one whose operands are checked.
    ("module_constant_folded_through_its_operators",
     "POW = 2 ** 3 - 1\n"
     "SHL = 1 << 20\n"
     "SHR = 100 >> 2\n"
     "REF = SHL >> 4\n"
     "AND = 7 & 3\n"
     "OR = 7 | 8\n"
     "XOR = 7 ^ 3\n"
     "MIX = 3 * 4 + (1 << 5)\n"
     "NEG = -8 >> 2\n"
     "BIG = 2 ** 62 - 1\n"
     "MINV = -(2 ** 63)\n"
     "NOTV = ~(1 << 3)\n"
     "TOP = (1 << 62) | 7\n"
     "\n"
     "def main(n):\n"
     "    print(POW)\n"
     "    print(SHL)\n"
     "    print(SHR)\n"
     "    print(REF)\n"
     "    print(AND)\n"
     "    print(OR)\n"
     "    print(XOR)\n"
     "    print(MIX)\n"
     "    print(NEG)\n"
     "    print(BIG)\n"
     "    print(MINV)\n"
     "    print(NOTV)\n"
     "    print(TOP)\n"
     "    return 0\n",
     "7\n1048576\n25\n65536\n3\n15\n4\n44\n-2\n4611686018427387903\n"
     "-9223372036854775808\n-9\n4611686018427387911\n"),

    ("read_global_as_a_subscript_index_in_a_store",
     "KEY = 'k'\n"
     "IDX = 1\n"
     "\n"
     "def store() -> Int:\n"
     "    d = {'a': 1}\n"
     "    d[KEY] = 7\n"
     "    return d[KEY]\n"
     "\n"
     "def aug() -> Int:\n"
     "    xs = [1, 2, 3]\n"
     "    xs[IDX] += 10\n"
     "    xs[0], xs[2] = 7, 9\n"
     "    return xs[0] + xs[1] + xs[2]\n"
     "\n"
     "def branchy() -> Int:\n"
     "    xs = [4, 5]\n"
     "    if 2 > 0:\n"
     "        xs[IDX - 1] = 6\n"
     "    return xs[0] * 10 + xs[1]\n"
     "\n"
     "def main(n):\n"
     "    print(store())\n"
     "    print(aug())\n"
     "    print(branchy())\n"
     "    return 0\n", "7\n28\n65\n"),

    # ── containers ──
    # A module-level list is an address-valued slot: the slot holds a POINTER to
    # the blob, so it is the case that exercises the initializer at all — an
    # int global is fully described by the bytes in its slot, so a broken
    # initializer still leaves a readable number behind.
    #
    # The trailing `main(0)` is not decoration, and every container case below
    # carries it for the same reason. `NUMS = [10, 20, 30]` is a module-level
    # binding whose value does NOT fold to a literal, so it is module BODY
    # (`model.module_body`'s own classification, and the only exemption from it
    # is a binding that folds). The module body is therefore the entry, and
    # `main` runs only if the body calls it — which is what CPython does with
    # this file, and which `bugs/FORMAL_toplevel_statements_dropped.md`'s own
    # case 3 pins ("a body that never calls `main` exits 0, and so does this").
    # Without the call these three cases print nothing and both backends are
    # right; they were written before the body existed, when a module-level
    # statement was dropped and `main` was the entry by default.
    ("read_list_elements",
     "NUMS = [10, 20, 30]\n"
     "\n"
     "def main(n):\n"
     "    first: Int = NUMS[0]\n"
     "    last: Int = NUMS[2]\n"
     "    print(first)\n"
     "    print(last)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "10\n30\n"),

    # Subscripting a global from inside a FUNCTION, so the function's prologue
    # has to run the lazy initializer before the load rather than relying on
    # `main` having done it already.
    ("read_list_from_function",
     "NUMS = [10, 20, 30]\n"
     "\n"
     "def total():\n"
     "    return NUMS[0] + NUMS[1] + NUMS[2]\n"
     "\n"
     "def main(n):\n"
     "    t: Int = total()\n"
     "    print(t)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "60\n"),

    # TWO module-level stores of one container name. `collect_global_slots` keeps
    # the LAST binding as the slot's initializer, so this pins that the earlier
    # store is not what the reads see — and, just as much, that NEITHER store is
    # a top-level statement the module body has to run.
    #
    # The second half is the reason this case exists rather than a one-line
    # variant of the one above. A module-level store of a container is realized
    # as the `__DATA` slot's initializer, so it is not body; but the entry point
    # IS the module body when there is one (`entry_function` rule 1), and the
    # whole body here is the two stores. Left in, the image materialised the
    # second list on its own stack, discarded it, never called `main` and exited
    # 0 — printing nothing, on both architectures, with a green build. A test
    # that only asked "is the right number printed" would have caught it; what
    # this row adds is the second store, so the case is about WHICH store is the
    # initializer as well as about the entry.
    ("rebound_list_global",
     "NUMS = [1, 2]\n"
     "NUMS = [30, 40, 50]\n"
     "\n"
     "def main(n):\n"
     "    first: Int = NUMS[0]\n"
     "    last: Int = NUMS[2]\n"
     "    print(first)\n"
     "    print(last)\n"
     "    return 0\n", "30\n50\n"),

    # Bound to a local first. This is the shape that most exposed the lazy
    # initializer: the load of the slot happens once, in the prologue's shadow,
    # and every later use goes through the register — so a slot filled after
    # the load reads stale, and a slot never filled reads the zero an unwritten
    # slot gives.
    ("alias_list_then_index",
     "NUMS = [10, 20, 30]\n"
     "\n"
     "def main(n):\n"
     "    p = NUMS\n"
     "    v: Int = p[1]\n"
     "    print(v)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "20\n"),

    # ── strings ──
    # `printf` rather than `print` for strings, and the reason is worth stating
    # because it is not a style preference: a string global's slot holds an
    # ADDRESS, and `print` on an `Int`-rendered value of one prints the address
    # — measured, "bye" printed as the decimal for its own bytes. `printf("%s")`
    # is the idiom the rest of the formal suite uses for a string and is the
    # one that distinguishes the two.
    #
    # These two cases therefore opt out of the interpreter comparison (see
    # `run_case`), because `printf` is not in the interpreter's namespace; the
    # expected value is the literal below, which is what CPython's semantics say
    # the program computes.
    ("read_string_global",
     "NAME = \"hi\"\n"
     "\n"
     "def setname():\n"
     "    global NAME\n"
     "    NAME = NAME\n"
     "\n"
     "def main(n):\n"
     "    setname()\n"
     "    printf(\"%s\", NAME)\n"
     "    return 0\n", "hi\n"),

    # Reassigning a string global is the case where the slot's old contents are
    # the wrong answer rather than a plausible one, so it is worth its own row.
    ("write_string_global",
     "NAME = \"hi\"\n"
     "\n"
     "def setname():\n"
     "    global NAME\n"
     "    NAME = \"bye\"\n"
     "\n"
     "def main(n):\n"
     "    setname()\n"
     "    printf(\"%s\", NAME)\n"
     "    return 0\n", "bye\n"),

    # A string ELEMENT inside a container global. The word is a `char *` and the
    # only `char *` to those bytes on this path is the INTERNED literal — so the
    # initializer stores the address a `"a"` written anywhere in the program
    # already has, rather than a copy of the bytes into `__DATA`. A copy would
    # satisfy this row and be wrong: `printf("%s")` cannot tell two copies of
    # the same text apart, which is exactly why a row that only checks output is
    # not enough here, and why the dict row below is in the file.
    ("read_list_of_strings",
     "L = [\"a\", \"b\"]\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%s\", L[0])\n"
     "    printf(\"%s\", L[1])\n"
     "    return 0\n", "ab"),

    # The same shape as a DICT, and the row that would fail if the elements
    # were copied rather than interned. A dict subscript is a raw 64-bit compare
    # of the key against each pair's key word (`_emit_dict_lookup_addr`), so a
    # `__DATA` copy of "a" is not the key the lookup is looking for: the image
    # exits 1 on a missing key, where CPython answers 1. This is also the only
    # row here that needs `global_slot_is_dict` — without it a dict global's
    # `D["a"]` is emitted as a SEQUENCE subscript and the key's address becomes
    # an element offset, which is a load from a nonsense address.
    # `None` as a container ELEMENT, and the row that was refused before
    # 2026-10-04 with **"one of its elements is computed by a call"** — about a
    # literal, with no call in it. `_static_word` had no arm for a `None`, in
    # either spelling (it arrives as `IdentExpr("None")`, not `NoneLiteral`),
    # even though both emitters lower a `None` to the word 0 and every other
    # reader of the same value accepts the two spellings as one.
    #
    # The nested shape is `formal/arm64_proof_gen.py`'s `_STEP_CONDS`, whose
    # first entry is `(None, 0xd65f03c0)` and which
    # `tools/formal_proof_breadth.py`'s census records under exactly that
    # misdiagnosis. `mask is None` reading a blob element is the other half: it
    # is the test that says the word is 0 rather than a marker nothing wrote,
    # and a layout that stored a sentinel other than 0 would answer every row
    # "not None".
    ("read_nested_container_with_none_elements",
     "TBL = [(None, 7), (3, 1), (None, 11), (6, 2)]\n"
     "\n"
     "def pick(w: Int) -> Int:\n"
     "    var i = 0\n"
     "    while i < len(TBL):\n"
     "        var pair = TBL[i]\n"
     "        var mask = pair[0]\n"
     "        var base = pair[1]\n"
     "        if mask is None:\n"
     "            if w == base:\n"
     "                return i\n"
     "        else:\n"
     "            if (w & mask) == base:\n"
     "                return i\n"
     "        i = i + 1\n"
     "    return -1\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%d %d %d %d\", pick(7), pick(5), pick(11), pick(4))\n"
     "    return 0\n",
     "0 1 2 -1"),

    # The same word in the two simpler shapes: a list element and a dict VALUE,
    # so the fix is not only about a nested container laying out.
    ("read_none_in_a_list_and_a_dict",
     "ITEMS = [1, None, 3]\n"
     "MAP = {\"a\": None, \"b\": 2}\n"
     "\n"
     "def first_none() -> Int:\n"
     "    var i = 0\n"
     "    while i < len(ITEMS):\n"
     "        if ITEMS[i] is None:\n"
     "            return i\n"
     "        i = i + 1\n"
     "    return -1\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%d %d\", first_none(), 1 if MAP[\"a\"] is None else 0)\n"
     "    return 0\n",
     "1 1"),

    ("read_dict_of_strings_by_key",
     "D = {\"a\": 1, \"b\": 2}\n"
     "\n"
     "def main(n):\n"
     "    x: Int = D[\"a\"]\n"
     "    printf(\"%d\", x)\n"
     "    y: Int = D[\"b\"]\n"
     "    printf(\"%d\", y)\n"
     "    return 0\n", "12"),

    # A dict whose VALUES are strings, so both halves of a pair are pointers and
    # the interleave in the blob is two string cells per pair.
    ("read_dict_string_values",
     "M = {\"k\": \"v\", \"j\": \"w\"}\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%s\", M[\"k\"])\n"
     "    printf(\"%s\", M[\"j\"])\n"
     "    return 0\n", "vw"),

    # A NESTED container global, which used to be refused with "a container
    # element is itself a container … only the SECOND level of fixups is
    # missing". The element of a nested literal IS a word on this path — a
    # pointer to a blob — so what was missing was never a word to put there but
    # the blob it points at, and `build_data_image` now lays one out per nested
    # element and adds it to the same `fixups` list the flat case already used.
    #
    # EVERY index of both levels is read, and that is the row's real subject.
    # Element `i` of a blob is the word at `8 * (i + 1)`, so a blob's own words
    # have to be CONTIGUOUS: laying an inner blob out as its element word is
    # reached interleaves it, and then `X[1][0]` reads the FIRST inner blob's
    # count (2) where element 1's pointer belongs, indexes 0 into it, and answers
    # 2 — which is what the first version of this fix did, on both architectures,
    # from a green build. `X[0][*]` was right in that version and `X[1][*]` was
    # wrong, so a row that read only the first element would have passed on it.
    ("nested_container_global",
     "X = [[1, 2], [3, 4]]\n"
     "\n"
     "def main(n):\n"
     "    a: Int = X[0][0]\n"
     "    b: Int = X[0][1]\n"
     "    c: Int = X[1][0]\n"
     "    d: Int = X[1][1]\n"
     "    print(a)\n"
     "    print(b)\n"
     "    print(c)\n"
     "    print(d)\n"
     "    print(len(X))\n"
     "    return 0\n", "1\n2\n3\n4\n2\n"),

    # The same layout with a THIRD level, and the third level is where a
    # worklist stops being an optimisation: each pass has to finish a whole
    # blob before the next one starts, or the deepest blob lands inside the
    # middle one. `DEEP[0][1][0]` and `DEEP[1][0][0]` together are the two
    # directions through the queue.
    ("three_level_nested_container_global",
     "DEEP = [[[1, 2], [3]], [[4]]]\n"
     "\n"
     "def main(n):\n"
     "    a: Int = DEEP[0][1][0]\n"
     "    b: Int = DEEP[1][0][0]\n"
     "    print(a)\n"
     "    print(b)\n"
     "    return 0\n", "3\n4\n"),

    # STRINGS inside the nested blob, which is the other word kind and the one
    # that cannot be laid out as bytes: a string word is a pointer to the
    # INTERNED literal in `__TEXT`, which is not in this image, so it is eight
    # zero bytes plus a `string_cells` entry and only the CODE can name the
    # target. A nested blob therefore needs the fixup for its own words AND a
    # string cell per string inside it, and the shape is `tools/wave1_move_shared.py`'s
    # `MOVES` and `tools/wave2_extract_shared.py`'s `EXTRACT` verbatim — the two
    # module globals this capability exists for. Compared against the
    # interpreter, so the expected answer is not a second copy of the words.
    ("nested_container_of_strings_global",
     "MOVES = [\n"
     "    (\"gimple_solvers\", \"mojo/middle/solvers.py\", \"mojo.middle.solvers\"),\n"
     "    (\"gimple_ctypes\", \"mojo/middle/types.py\", \"mojo.middle.types\"),\n"
     "]\n"
     "\n"
     "EXTRACT = {\n"
     "    \"gimple_gen_infra.py\": (\"infra_infer\", [\"_infer_param_types\"]),\n"
     "    \"gimple_mod.py\": (\"mod\", [\"one\"]),\n"
     "}\n"
     "\n"
     "def main(n):\n"
     "    a: String = MOVES[0][1]\n"
     "    b: String = MOVES[1][0]\n"
     "    print(a)\n"
     "    print(b)\n"
     "    c: String = EXTRACT[\"gimple_mod.py\"][0]\n"
     "    d: String = EXTRACT[\"gimple_gen_infra.py\"][1][0]\n"
     "    print(c)\n"
     "    print(d)\n"
     "    print(len(MOVES))\n"
     "    return 0\n",
     "mojo/middle/solvers.py\ngimple_ctypes\nmod\n_infer_param_types\n2\n"),

    # THE CONTROL for the interning claim, and the reason the two rows above are
    # worth having: a string global and a string LITERAL are the same string, so
    # the comparison is true. Before, the global's bytes were a COPY in
    # `__DATA` and the literal's were the interned one in `__TEXT`; this row
    # passed anyway, because a name bound to a string literal classifies as a
    # string and its `==` lowers to a content compare. So it pins the address
    # identity that the dict row needs without pinning it by proxy.
    ("string_global_is_the_interned_literal",
     "NAME = \"hi\"\n"
     "\n"
     "def main(n):\n"
     "    c: Int = 0\n"
     "    if NAME == \"hi\":\n"
     "        c = 1\n"
     "    printf(\"%d\", c)\n"
     "    return 0\n", "1"),

    # ── the MODULE BODY as the writer ──
    # `G = compute()` at file level is a STORE, not a value the linker can lay
    # out: the call is not known before the program runs. Before this row the
    # build refused it with "this path has no module-global storage for it",
    # which by then was false in every clause — there IS a `__DATA` slot per
    # name — and the real blocker was that nothing wrote the slot. What writes
    # it is the module's own top level, which this path already compiles into
    # the synthetic function the startup stub ENTERS.
    #
    # The trailing `main(0)` is not decoration and never has been on this file:
    # the module body IS the entry, so it runs its own statements first and
    # calls `main` only because the source says so — CPython's rule for a
    # module-level call. Every container row above carries the same call for the
    # same reason.
    #
    # Both spellings of the read are here — the bare name in `main` and a
    # function's own read of it — because they reach the slot by different
    # paths: the first through `main`'s prologue, the second through a frame the
    # caller built. A slot that was filled but not re-checked on the second path
    # would answer the zero an unwritten slot gives.
    ("module_body_computes_the_global",
     "def compute() -> Int:\n"
     "    return 40 + 2\n"
     "\n"
     "G = compute()\n"
     "\n"
     "def read_g() -> Int:\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    a: Int = G\n"
     "    b: Int = read_g()\n"
     "    print(a)\n"
     "    print(b)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "42\n42\n"),

    # The interaction with the OTHER writer of the same slot. `G` now has two
    # writers — the module body and `bump` — and one home, which is the whole
    # of the single-home argument the storage capability rests on. 42 / 43 / 43
    # and not 42 / 42 / 42 is what says the body's store is not overwritten by
    # the prologue's lazy initializer when `bump` runs, and 42 first says the
    # body's store survived into `main`.
    ("module_body_then_a_function_writes_it",
     "def compute() -> Int:\n"
     "    return 40 + 2\n"
     "\n"
     "G = compute()\n"
     "\n"
     "def bump() -> Int:\n"
     "    global G\n"
     "    G = G + 1\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    a: Int = G\n"
     "    b: Int = bump()\n"
     "    c: Int = G\n"
     "    print(a)\n"
     "    print(b)\n"
     "    print(c)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "42\n43\n43\n"),

    # The KIND of a body-filled slot, which is the third source of a value's
    # kind beside a folded literal and a container literal. `len(G)` is the
    # consumer that needs it and the one that was refused: `("unknown", …)`
    # states no kind, and a slot whose kind is nothing is an unclassified word,
    # so `len` said "the source does not say what this operand holds" about an
    # operand the source annotates on the CALLEE's `-> List[Int]`.
    #
    # The two halves are here because they are two different questions and the
    # fix answers both from one declaration: `len` needs to know the slot holds a
    # blob, and `G == "hi"` needs to know it holds a `char *` — a word read as an
    # int64 would make the second one compare two addresses, which is the
    # documented failure of `global_slot_is_string`'s own row.
    #
    # `List[Int]` yields the BARE list prefix rather than `list:int`, because the
    # annotation says what the container is and not what its elements are. That is
    # the same answer a container literal of non-word elements gets, so the two
    # spellings cannot disagree — and `print(G)` (the container itself) is still
    # refused on this path, for a local exactly as for a global.
    ("a_body_filled_slot_carries_the_callee_s_kind",
     "def make() -> List[Int]:\n"
     "    return [3, 14, 0]\n"
     "\n"
     "def greet() -> String:\n"
     "    return \"hi\"\n"
     "\n"
     "NUMS = make()\n"
     "NAME = greet()\n"
     "\n"
     "def main(n):\n"
     "    c: Int = 0\n"
     "    if NAME == \"hi\":\n"
     "        c = 1\n"
     "    print(len(NUMS))\n"
     "    print(c)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "3\n1\n"),

    # The DICT half of the same rule, and the one that is a fault rather than a
    # refusal. A `ValueKinds` kind cannot carry it — `List[Int]`,
    # `Tuple[Int, Int]`, `Set[Int]` and `Dict[String, Int]` are all one word here
    # and all classify as the bare list prefix — so the dict-ness is a separate
    # answer from the same annotation, and `global_slot_is_dict` asks it. Before
    # this row `D["a"]` was emitted as a SEQUENCE subscript, so the interned
    # address of `"a"` became an element offset, the bounds check failed and the
    # image exited 1 with a green build, on BOTH architectures, where CPython
    # answers 1. `read_dict_of_strings_by_key` above is the same question asked of
    # a dict LITERAL, whose shape the initializer states; this one is asked of the
    # only spelling the initializer says nothing about.
    #
    # `printf` and not `print` because `print()` of a subscript still cannot
    # classify the element on this path (an unannotated dict comprehension's
    # element kind is the separate row in `test_formal_value_model.py`), and a row
    # that only checks the BUILD would not notice the fault — which is why this
    # one executes.
    ("a_body_filled_dict_global_subscripts_as_a_dict",
     "def make() -> Dict[String, Int]:\n"
     "    var d: Dict[String, Int] = {\"a\": 1, \"b\": 2}\n"
     "    return d\n"
     "\n"
     "D = make()\n"
     "\n"
     "def main(n):\n"
     "    x: Int = D[\"a\"]\n"
     "    y: Int = D[\"b\"]\n"
     "    printf(\"%d\", x)\n"
     "    printf(\"%d\", y)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "12"),

    # THE CONTROL for the row above, and it is the half that makes the row mean
    # something: the same CALLEE shape that says "dict" must not also say "dict"
    # for a list. `L[1]` is 14 through an address computation over a
    # `[count][e0][e1]…` blob; read as a pair blob it is a key SCAN that walks
    # `[npairs][k0][v0]…` looking for the integer 14 as a key word, finds it in
    # no pair, and exits 1. So one row marked "sequence" and one marked "dict" and
    # one callee annotation each is the whole of the distinction — a fix that
    # answered "container" for both would pass the first and fail this one.
    ("a_body_filled_list_global_subscripts_as_a_sequence",
     "def make() -> List[Int]:\n"
     "    return [3, 14, 0]\n"
     "\n"
     "L = make()\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%d\", L[0])\n"
     "    printf(\"%d\", L[1])\n"
     "    printf(\"%d\", L[2])\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "3140"),

    # A string global printed, not compared — the OTHER reader of the slot's
    # shape. A `char *` classified as a plain word is an INT on this path, so a
    # row that lost the shape would print a decimal ADDRESS rather than `hi`,
    # which is why the expected value is text and why this uses `print` (the
    # interpreter runs it, so the row has a reference answer and not only a
    # hand-written one).
    #
    # This one PASSED before the dict fix: `print` classifies through
    # `_expr_str_kind`, which falls back to the whole-function `ValueKinds` and
    # so already reached `global_slot_kind`. It is here to pin the interaction —
    # `global_slot_is_string` now asks that same function instead of
    # re-deciding from the initializer, and the two spellings have to keep
    # agreeing — rather than as the row that shows the fault. The row that shows
    # the fault is the dict one above, because `_is_dict_subscript` reads the
    # slot directly and has no such fallback.
    ("a_body_filled_string_global_prints_as_text",
     "def greet() -> String:\n"
     "    return \"hi\"\n"
     "\n"
     "NAME = greet()\n"
     "\n"
     "def main(n):\n"
     "    print(NAME)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "hi\n"),

    # The ELEMENT kind of a body-filled blob, and the third row of the same
    # argument: `declared_type_kind` maps a blob annotation to a blob without
    # reading its element, so `L = make()` was `list` with no element and
    # `print(L[0])` was refused — while `l = make()` inside a function has always
    # been `list:int` on this path, because both backends' `_callee_kind` reads
    # the RETURN STATEMENTS for a blob annotation and `[3, 14, 0]` states its
    # elements. Two spellings of one expression, one answer and one refusal, and
    # which one you got depended on whether the binding was at file level.
    #
    # `print`, not `printf`, so the interpreter is the reference for the value
    # rather than the row's own expectation: an address where `3` belongs is a
    # decimal in the tens of trillions, and this row is about which of two kinds
    # the subscript yields.
    ("a_body_filled_slot_carries_the_callee_s_element_kind",
     "def make() -> List[Int]:\n"
     "    return [3, 14, 0]\n"
     "\n"
     "L = make()\n"
     "\n"
     "def main(n):\n"
     "    print(L[0])\n"
     "    print(L[2])\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "3\n0\n"),

    # ── module boundaries ──
    # A dylib's `__DATA` is emitted with `emit_startup=False`, so there is no
    # startup stub to run an initializer from: the lazy per-function check is
    # the ONLY thing that can fill it. This case is the whole argument for that
    # design, and it is the one case here that needs two files.
    ("cross_module_counter",
     {"state.mojo": "HITS = 0\n"
                    "\n"
                    "def hit():\n"
                    "    global HITS\n"
                    "    HITS = HITS + 1\n"
                    "\n"
                    "def get_hits():\n"
                    "    return HITS\n",
      "prog.mojo": "from state import hit\n"
                   "from state import get_hits\n"
                   "\n"
                   "def main(n):\n"
                   "    hit()\n"
                   "    hit()\n"
                   "    hit()\n"
                   "    h: Int = get_hits()\n"
                   "    print(h)\n"
                   "    return 0\n"}, "3\n"),

    # ── module-level `comptime` constants ──
    # A MODULE-level `comptime` binding has no `__DATA` slot and is not meant
    # to: it is a compile-time constant, so the build substitutes its value at
    # every read site in the unit (`build.py:_substitute_module_constants`) and
    # the slot question never arises. `collect_module_symbols` decides which
    # names are in that category by asking whether the initialiser FOLDS.
    #
    # It used to fold only a literal, so a constant written over another one was
    # refused — and refused with a message telling the reader to do exactly
    # that. `comptime_fold_refusal`'s text says: "Make the initializer a literal
    # (or an expression of literals and other `comptime` names)". The second
    # half did not work at module level; it does at function scope
    # (`mojo/middle/comptime.py:eval_const` resolves operand names out of the
    # bindings recorded so far for that function), so one half of the language's
    # own promise was implemented and the other was not.
    #
    # The source is `std/utils/_serialize.mojo`'s, verbatim in shape and in
    # spelling, because that is where the sweep found it:
    #
    #     comptime _kCompactMaxElemsToPrint = 7
    #     comptime _kCompactElemPerSide = _kCompactMaxElemsToPrint // 2
    #
    # Two operators in one line, and they needed two separate repairs in two
    # different folders: the reference to the earlier name is
    # `collect_module_symbols` walking its own table in source order, and `//`
    # is in neither folder's operator table. Before, the file was refused on
    # arm64 and on x86-64 alike with "'_kCompactElemPerSide' is a `comptime`
    # binding declared at module level, and it does not fold to a compile-time
    # constant".
    #
    # The interpreter is a third engine here for free: `fire.py run` handles
    # `comptime` at module level, so this row needs no keyword-stripped copy of
    # itself to have a reference answer, and 3 is what CPython would print for
    # `7 // 2` too.
    ("module_comptime_constant_over_another_module_constant",
     "comptime _kCompactMaxElemsToPrint = 7\n"
     "comptime _kCompactElemPerSide = _kCompactMaxElemsToPrint // 2\n"
     "\n"
     "def main(n):\n"
     "    per_side: Int = _kCompactElemPerSide\n"
     "    print(per_side)\n"
     "    return 0\n", "3\n"),

    # The same shape with `+ - *` instead of `//`, so a reader can tell which
    # half of the two repairs this file's row above needed. It also pins the
    # value being the SUBSTITUTED one rather than the name: 7 + 7 + 7 = 21, and
    # a read that came back as the address of a slot would not be 21.
    ("module_comptime_constant_arithmetic_chain",
     "comptime _A = 7\n"
     "comptime _B = _A * 2\n"
     "comptime _C = _B + _A\n"
     "\n"
     "def main(n):\n"
     "    v: Int = _C\n"
     "    print(v)\n"
     "    return 0\n", "21\n"),

    # THE CONTROL FOR THE REFUSAL BELOW, and it is the half that makes that
    # refusal correct rather than merely cautious. `bump` assigns `G` and
    # declares NOTHING, so per CPython's scope rule (decided at compile time
    # from the whole body — see `local_shadow_of_global_read_before_store_...`
    # above) `G` inside `bump` is a LOCAL. The module's `G` is therefore
    # read-only at module level, `bump()` cannot have changed it, and `_B` is
    # exactly 5 + 1. The interpreter, CPython and both images agree on 6.
    #
    # This is the direction a too-broad gate gets wrong: refusing here would be
    # safe and would also refuse a program whose answer this build can state,
    # which is the same mistake the `+ - *` row above would hide if `//` were
    # the only operator tested.
    #
    # `bump` is a METHOD, and that is half of what this row is for. A gate that
    # read only the module's top-level statements would not see a `global G`
    # inside a `class`, and `model.collect_module_symbols` walks with
    # `iter_nodes` precisely so it does not. The method's `self` receiver has
    # nothing to do with which NAME is written: the module is the scope either
    # way.
    ("module_comptime_constant_over_a_locally_shadowed_name",
     "G = 5\n"
     "\n"
     "class C:\n"
     "    def bump(self):\n"
     "        G = 100\n"
     "\n"
     "comptime _B = G + 1\n"
     "\n"
     "def main(n):\n"
     "    c = C()\n"
     "    c.bump()\n"
     "    v: Int = _B\n"
     "    print(v)\n"
     "    return 0\n", "6\n"),

    # ── a COMPREHENSION is its own scope, and the shadowing rule has to know it ──
    #
    # Two rows, because they are two programs and the difference between them is
    # one identifier — the comprehension's TARGET. Both are `G` read inside a
    # comprehension over a module global of the same name, and CPython's answer
    # differs: with the target spelled `G` the read is the loop variable, and
    # without it the read is the module's 5.
    #
    #     G = 5
    #     def f(rows):
    #         var out = [G for G in rows]     # the comprehension's own G
    #         return G + out[0]               # the MODULE's G: 5 + 1 = 6
    #
    # This path REFUSED the trailing `G` on both architectures — "is read at line
    # 5 before anything in this function stores it, and CPython raises
    # UnboundLocalError for that program" — and CPython answers **6**. The
    # message is false in the strongest available way: the program runs. The
    # cause is that the register allocator's `bound_names_in_order` reports a
    # comprehension's target (correctly — the emitter gives it a home), and the
    # reader of "does this name shadow a module binding" was the same set.
    #
    # The row above is the control and the reason this could not be fixed by
    # deleting the name from one table: `bump`'s `G = 100` really is a local of
    # `bump`, and the module's `G` must keep its value. So there are two readers
    # now — `build.py::_names_bound_in` (what the body writes, which placement
    # needs) and `_function_locals` (what shadows a module binding) — and the
    # comprehension's target is in the first and not the second.
    #
    # `printf`, and the reason is this file's own rule rather than a style
    # choice: a case spelled with `printf` has no interpreter reference, because
    # `printf` is not a name the interpreter resolves — and for THIS construct
    # the interpreter has no correct answer to give. It evaluates a list/set/dict
    # comprehension in the ENCLOSING scope, so the comprehension's target leaks
    # out and the trailing `G` reads 2 rather than the module's 5:
    #
    #     $ python3 fire.py run .tmp/w/ci.py     # 3
    #     $ python3 -c "…same text…"             # 6
    #
    # `myinterpreter.py::eval_Comprehension`'s own docstring calls this "a known
    # minor fidelity gap", and the fix is filed as
    # `bugs/INTERP_comprehension_has_no_scope_of_its_own.md`. Until then the two
    # images are checked against CPython's 6 and the interpreter is not asked,
    # which is strictly MORE than the three-engine contract usually gets here —
    # an interpreter that disagreed would have been reported as a semantics bug,
    # and one did.
    ("a_comprehension_target_does_not_shadow_a_module_constant",
     "G = 5\n"
     "\n"
     "def f(rows):\n"
     "    var out = [G for G in rows]\n"
     "    return G + out[0]\n"
     "\n"
     "def main() -> int:\n"
     "    printf(\"%d\", f([1, 2]))\n"
     "    return 0\n", "6"),
    # The same read with a DIFFERENT target, which is the control for the row
    # above in the direction that matters: nothing shadows `G` here, so the
    # comprehension's `G` is the module's 5. A "fix" that simply stopped
    # substituting inside comprehensions would answer 1 here.
    ("a_comprehension_read_of_a_module_constant_is_the_constant",
     "G = 5\n"
     "\n"
     "def f(rows):\n"
     "    return [G for x in rows][0]\n"
     "\n"
     "def main() -> int:\n"
     "    printf(\"%d\", f([1, 2]))\n"
     "    return 0\n", "5"),

    # ── `__file__`, the one module-level name the BUILD can answer ──
    #
    # It was refused by name (`'__file__' has no home`) on the reasoning that
    # module attributes "are strings by the language and identical in every
    # program this path can compile" — which is true of the eleven other names on
    # that list and false of this one, because `__file__` is a different string
    # in every file. What the build was HANDED is the path of the file it is
    # compiling, so the value is a build-time fact and it lives in the table a
    # folded module constant already lives in.
    #
    # The expected value is not written down beside the case: it is computed
    # from the source path the runner handed `fire.py`, which is the only honest
    # way to pin it — a hand-written absolute path would go stale the moment the
    # tree moved, and would be wrong for every reader but this one. The
    # `os.path.dirname(os.path.abspath(__file__))` shape is
    # `tools/bootstrap_verify.py:31` and `tools/audit_selfhost_struct_fields.py`
    # verbatim, and `REPO = dirname(HERE)` is `bootstrap_verify.py`'s next line:
    # the whole point is that a name bound to a CALL is a slot the body fills,
    # and this row is what says the value in it is the build's and not zero's.
    #
    # The trailing `main(0)` is the same thing every container row above carries
    # and for the same reason: the module body IS the entry, so `main` runs
    # because the source says so.
    ("__file___is_the_source_the_build_was_handed",
     "from os.path import dirname, abspath\n"
     "\n"
     "HERE = dirname(abspath(__file__))\n"
     "REPO = dirname(HERE)\n"
     "\n"
     "def main(n):\n"
     "    s: String = __file__\n"
     "    d: String = HERE\n"
     "    r: String = REPO\n"
     "    print(s)\n"
     "    print(d)\n"
     "    print(r)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", __file__case),

    # The half of the row above that is about the ANNOTATION rather than about
    # `__file__`, isolated so it cannot be read as "the case passes because
    # `__file__` works".  `HERE`'s initializer is a call into another module's
    # dylib, so `_body_store_shape` claims nothing about the slot's KIND (it
    # asks only of a bare-name callee, deliberately), `global_slot_kind` is
    # therefore None, and `kind_of(HERE)` is None — which `_value_kind` turns
    # into this model's DEFAULT for a word.  Measured before the annotation was
    # read, on BOTH architectures:
    #
    #     print(d)   ->   105553157226576
    #
    # An interned `char *` printed as a decimal, from a green build, with an
    # exit status of 0.  `printf("%s", HERE)` in the same program printed `/a/b`
    # throughout, so the value was never wrong — only the RENDERING was, and
    # only because the one piece of evidence in the source (`d: String`) was not
    # being read.
    #
    # The control is in the same program: `e = dirname(HERE)` has no annotation
    # and is still classified from the call, so the row says the annotation
    # IMPROVES an unknown rather than replacing a classification.
    ("an_annotated_local_takes_its_type_from_the_annotation",
     "from os.path import dirname, abspath\n"
     "\n"
     "HERE = dirname(abspath(\"/a/b/c.py\"))\n"
     "\n"
     "def main(n):\n"
     "    d: String = HERE\n"
     "    e: String = dirname(HERE)\n"
     "    print(d)\n"
     "    print(e)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "/a/b\n/a\n"),
]

# Cases that must be REFUSED, and why each one is a refusal rather than a wrong
# number.
#
# The distinction is the point. A module global's value has to be known before
# the program runs, because its storage is eight bytes of static image. An
# initializer this backend cannot materialise leaves those bytes zero, and zero
# is a plausible value: a list would read as length 0 and a string as an empty
# one, so the program would produce an answer rather than an error. Refusing is
# the only honest option, and these rows pin that it still does.
REFUSALS = [
    # A string ELEMENT inside a container global is NOT a refusal any more —
    # `read_list_of_strings` above runs it. What is still refused is a container
    # element that is neither an int, a string, nor a NESTED container of those,
    # and the pin is here because the refusal machinery is what stops a slot with
    # no initializer from reading as the zero an unwritten slot gives: a list
    # would report length 0 and print an answer.
    #
    # The element is a CALL here rather than a literal, which is the one word kind
    # `_static_word` still cannot compute — its result is not known before the
    # program runs, and no amount of laying out `__DATA` changes that. The
    # nested-container half of the old message is gone with
    # `nested_container_global` above; what is left is this.
    ("call_computed_container_element_refused",
     "L = [len(\"ab\"), 3]\n"
     "\n"
     "def main(n):\n"
     "    v: Int = L[0]\n"
     "    print(v)\n"
     "    return 0\n",
     "no initializer"),
    # …and WHY the name has a slot, which is the second half of that row's
    # sentence and was false of every container global. `GlobalSlot.mutable`'s
    # own comment records this sentence being fixed once already — in the
    # MANIFEST, where `write_dylib_manifest` split `variables` from `containers`
    # for exactly this reason — while the refusal kept it, so a name nothing
    # writes was reported as one a function writes through `global`. The `absent`
    # is the false clause and this row is what keeps it out: `L` above is a
    # CONSTANT with a home, and a reader sent looking for the writer that does
    # not exist stops reading the sentence that names the real problem, which is
    # the element of the literal that is not a word.
    ("a_container_global_says_it_is_a_constant_not_a_variable",
     "L = [len(\"ab\"), 3]\n"
     "\n"
     "def main(n):\n"
     "    v: Int = L[0]\n"
     "    print(v)\n"
     "    return 0\n",
     "is a CONSTANT with a home and not a variable",
     "a function writes it through `global L`"),

    # A local that SHADOWS a module global, read before the local is stored. The
    # refusal is the point of the row, and the reason is a fact about CPython
    # that is easy to get backwards:
    #
    #     G = 5
    #     def bump():
    #         G = G + 1
    #
    # Python decides a name's scope at COMPILE time, from the whole function
    # body — `G` is assigned here, so `G` is local throughout `bump` — and the
    # right-hand read therefore raises `UnboundLocalError`. It does NOT read the
    # module's 5. Verified:
    #
    #     $ python3 -c 'G = 5
    #     > def bump():
    #     >     G = G + 1
    #     > bump()'
    #     UnboundLocalError: cannot access local variable 'G' where it is not
    #     associated with a value
    #
    # So the two homes are not a missed feature here; there is no answer to
    # compute, and a backend that resolved the read against the module slot
    # would print 6 for a program CPython refuses. `model.read_before_store`
    # refuses it, and this row pins that it still does on BOTH architectures —
    # the shape specific to this construct, because the read name is a real
    # module global here and so the alternative was a live `__DATA` load rather
    # than a dead register. The general read-before-store rule is pinned by
    # `test_formal_run.py`'s three refusal rows, none of which has a
    # module-level binding for the name it reads.
    #
    # The Mojo interpreter disagrees with CPython here (`fire.py run` prints 6),
    # which is worth knowing and is NOT what this row asserts: the test
    # contract for the images is CPython's semantics, and a program CPython
    # raises on has no reference answer to be lowered to.
    ("local_shadow_of_global_read_before_store_refused",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    G = G + 1\n"
     "    return G\n"
     "\n"
     "def main(n):\n"
     "    v: Int = bump()\n"
     "    print(v)\n"
     "    return 0\n",
     # The EXPECTED WORDS are `model.shadowed_module_global_read_refusal`'s,
     # and the refusal is the SAME one this row was written for — a read of a
     # local before its first assignment, which CPython raises on — now reached
     # through the module-global check rather than the general read-before-store
     # one, because the name is also a module binding and that check is the one
     # scoped to that case (measured: the general form is 233 sites in 57 files
     # of this repository, this one is 0 in 319). The new text names the
     # collision, quotes CPython's error and gives the two measured wrong
     # answers; the old sentence named neither.
     "is read in bump() at `G + 1`, before anything in that function has "
     "assigned it"),

    # THE SAME REFUSAL, and the row above is what makes this one legible: both
    # messages are `model.shadowed_module_global_read_refusal`, so they differ
    # only in what they QUOTE, and what they quote is the value spelled by the
    # one `_expr_spelling` the build pass is supposed to have.
    #
    # It had two. `formal/build.py` carried `_expr_spelling = M.expr_spelling`
    # and then, three lines below, a `def _expr_spelling` that shadowed it —
    # the older of the two, whose `CallExpr` arm required a BARE `IdentExpr`
    # callee. So this row's value, `G.h[0]()`, came out as the literal text
    # `CallExpr`: a true statement, an obvious placeholder, and useless in the
    # one job the sentence has, which is naming the read so a reader can find it
    # in their own file. The row above, `G + 1`, is spelled by the arm that copy
    # alone carried for `BinaryOp` — which is why deleting it is only correct
    # with that arm ported, and why the two rows are adjacent rather than one
    # being a comment on the other.
    #
    # `TypeList.reduce[Self._mapper]()` and `Intrinsics.read[0]()` are the real
    # shape behind it: the new-modular stdlib is full of comptime
    # specializations, and a comptime specialization's callee is a SUBSCRIPT.
    # (Deliberately a subscripted MEMBER call rather than a real specialization:
    # the question here is what the spelling function does with the node shape,
    # and a program that reaches a genuine `TypeList` would be testing the
    # stdlib rather than the spelling.)
    ("local_shadow_of_global_quotes_a_subscripted_callee",
     "G = 5\n"
     "\n"
     "def main(n):\n"
     "    y = G.h[0]()\n"
     "    G = 1\n"
     "    return y\n",
     "is read in main() at `G.h[0]()`, before anything in that function has "
     "assigned it"),

    # THE HALF THAT KEEPS THE TWO ROWS ABOVE HONEST. Resolving a module-level
    # initializer's operand names against the names bound SO FAR is what makes
    # `comptime _B = _A // 2` fold, and the question a reader has to be able to
    # answer is which names it resolves. Three of the four ways a name can fail
    # to be resolvable are pinned by the rows below; the fourth (a name bound
    # LATER) is this one, and it is the one that is easy to get wrong in the
    # direction that fabricates.
    #
    # `comptime _B = _A + 1` appears BEFORE `comptime _A = 7`. The module-level
    # sequence runs top to bottom, so at the point `_B` is initialised `_A` has
    # no value yet — CPython raises `NameError: name '_A' is not defined`, and
    # the interpreter agrees. A folder that consulted the WHOLE module instead
    # of the part before this statement would fold `_B` to 8 and print a number
    # for a program that has none.
    #
    # It is here rather than in the cases above because the answer is not a
    # number: it is the refusal that says the build does not know, which is the
    # only correct one.
    ("module_comptime_constant_over_a_later_name_refused",
     "comptime _B = _A + 1\n"
     "comptime _A = 7\n"
     "\n"
     "def main(n):\n"
     "    v: Int = _B\n"
     "    print(v)\n"
     "    return 0\n",
     "does not fold to a compile-time constant"),

    # THE ORDERING THE ROW ABOVE CANNOT SEE, and the one that would FABRICATE.
    # `_B` is still reading an EARLIER name, so the "bound so far" rule alone
    # admits it — and `known[G]` is 5, so the fold would be 6. It is wrong,
    # because a module body may CALL a function:
    #
    #     G = 5
    #     def bump():
    #         global G
    #         G = 100
    #     bump()                       # runs before _B's initializer
    #     comptime _B = G + 1          # CPython: 101
    #
    # "Bound so far" is a statement about the module-level SEQUENCE, and the
    # sequence is not the only thing that runs before the read: `bump()` is, and
    # its write lands first. So a name any function declares `global` is not
    # resolvable here, whatever the table holds for it — which is what
    # `model.collect_module_symbols`'s `functions_writing_globals` gate decides,
    # and the same reader `collect_global_slots` uses for the same reason.
    #
    # Refusing is not the cautious choice here, it is the only correct one: 6 is
    # a number no source wrote and nothing would catch it.
    ("module_comptime_constant_over_a_function_written_name_refused",
     "G = 5\n"
     "\n"
     "def bump():\n"
     "    global G\n"
     "    G = 100\n"
     "\n"
     "comptime _B = G + 1\n"
     "\n"
     "def main(n):\n"
     "    v: Int = _B\n"
     "    print(v)\n"
     "    return 0\n",
     "does not fold to a compile-time constant"),

    # THE SAME QUESTION ASKED ABOUT A METHOD, and the reason it is a separate
    # row rather than a comment on the one above. `global_names_bound_in` and
    # `collect_global_slots` both read the module's top-level `FunctionDef`
    # list, and `collect_module_symbols` does not: it walks with `iter_nodes`,
    # so a `global G` inside a `class` counts. Measured before that walk was in
    # place — `class C: def bump(self): global G; G = 100` left `G` resolvable
    # and `comptime _B = G + 1` folded to 6, where a module body that called
    # `c.bump()` first would make the true value 101.
    #
    # The receiver is the point: `self` has no bearing on which NAME is
    # written, and a reader who assumes the gate is about "functions" will miss
    # that a method is one.
    ("module_comptime_constant_over_a_method_written_name_refused",
     "G = 5\n"
     "\n"
     "class C:\n"
     "    def bump(self):\n"
     "        global G\n"
     "        G = 100\n"
     "\n"
     "comptime _B = G + 1\n"
     "\n"
     "def main(n):\n"
     "    v: Int = _B\n"
     "    print(v)\n"
     "    return 0\n",
     "does not fold to a compile-time constant"),

    # ── a body-filled slot read BEFORE the body writes it ──
    # These two rows are the other half of
    # `module_body_computes_the_global`, and they exist because the capability
    # that row tests opens a way to compute a plausible wrong number: the slot
    # is eight bytes of zeros until the module's top level stores into it, and
    # zero is an answer a program can print. `model.module_slot_readable_in` is
    # what refuses, and these pin that it still does — identically on both
    # architectures, because a value model the two disagree about is not one
    # value model.
    #
    # The module body is the ENTRY, so no function runs before its first
    # statement, and a read from another function is therefore only premature
    # when a CALL above the store puts one there. Here the store is below
    # `read_g()`.
    ("body_global_read_before_the_body_stores_it_refused",
     "def compute() -> Int:\n"
     "    return 5\n"
     "\n"
     "def read_g() -> Int:\n"
     "    return G\n"
     "\n"
     "read_g()\n"
     "G = compute()\n",
     "module body calls first is a path to it, and that call runs before the "
     "store"),

    # The store's OWN value runs before the store completes, so `G = compute()`
    # reads as "compute has not been called yet" for the duration of the call.
    # This row is transitive on purpose — `read_g` is reached through
    # `compute`, not called by it — because the direct case is the one a
    # one-level check gets and the indirect one is the one it misses. Without
    # the closure `read_g`'s load would read the zero and print 0.
    ("body_global_read_from_the_computation_that_fills_it_refused",
     "def read_g() -> Int:\n"
     "    return G\n"
     "\n"
     "def compute() -> Int:\n"
     "    return read_g() + 1\n"
     "\n"
     "G = compute()\n",
     "is reachable from the store of 'G' itself"),

    # THE GATE on the element kind, and the direction it has to fail in. A callee
    # whose return statement is a CALL is a word here, because reading it
    # precisely means recursing into that callee — which is what both backends'
    # `_callee_kind` hook does and what the model's reading deliberately does not,
    # because the answer this path must not give is a confident wrong one. So the
    # slot falls back to the bare `LIST_PREFIX` and the subscript stays refused.
    #
    # `inner()` here returns a list of STRINGS and the outer annotation says
    # `[Int]`, so a reading that trusted the annotation instead of the returns
    # would print the interned address of `"a"` as a decimal. The row exists to
    # keep that refusal: `len(L)` lowers on the same slot (the annotation is
    # enough to say it is a container) while the element is refused, and those
    # two answers are about two different questions.
    ("body_filled_slot_with_an_unfollowable_element_kind_is_refused",
     "def inner() -> List[String]:\n"
     "    return [\"a\", \"b\"]\n"
     "\n"
     "def make() -> List[Int]:\n"
     "    return inner()\n"
     "\n"
     "L = make()\n"
     "\n"
     "def main(n):\n"
     "    print(L[0])\n"
     "    return 0\n"
     "\n"
     "main(0)\n",
     "print() cannot tell whether SubscriptExpr is a string or a number"),
]

# ── a module-level STRUCT: the frame is in the IMAGE ─────────────────────
#
# Every case above stores an INT or a container into eight bytes of static
# image. A module-level `X = Struct(...)` is the one binding whose value does not
# fit in a word, and it had no storage at all until now — which was a LIFETIME
# defect rather than a gap. The body compiles to `__module_body__`, a function,
# so `X = Struct()` reserved a block in THAT activation and left its address in
# the slot; the block dies with the body, so every later read dereferenced
# reclaimed stack. The refusal the two call sites produced
# (`ModuleLoader_load_module(self, …)` beside
# `ModuleLoader_load_module(_module_loader, …)`) was right about the program and
# could not be lifted without moving the storage, because lifting it alone turns
# the refusal into a SIGSEGV.
#
# What moved the storage is `model.module_frame_slot_initializer`: the frame is
# laid out in `__DATA` beside the container blobs and the slot holds its link-time
# address like any other. These cases are the evidence that the frame is not
# stack the body has left, which is the only property the fix is about — a
# `fire.py run` comparison alone could not tell, because the interpreter stores a
# real object and the images store eight bytes in a segment.
#
# The trailing `main(0)` is what every container row above carries and is load
# bearing here for a second reason: it keeps the module body non-empty, so
# `entry_function`'s rule 1 makes the BODY the entry in both engines and the two
# agree on what ran. Without it the body is emptied by the fix, `main` becomes the
# entry in the image and is never called under `fire.py run`.
FRAME_CASES = [
    # The base shape: read through a method from a function, mutate the field
    # from a function, read it back. `_g.first()` is the disagreement the fix
    # exists for — `p.first()` hands a LIVE frame and `_g.first()` hands the
    # image's — and it is also the only thing here that would print a wrong
    # number if the frame were the body's: `read_from_module()` would read
    # whatever the second call to `bump` left in the body's reclaimed block.
    #
    # `__init__` is declared and assigns BOTH fields, and that is not
    # decoration: `fire.py run` answers `None` for a field read of a fresh
    # instance of a struct that declares no `__init__`
    # (`bugs/INTERPRETER_a_fresh_instance_of_a_struct_with_no_init_reads_none.md`),
    # so without it this row's interpreter comparison would be comparing against
    # a known-wrong reference. `y = 0` is what makes `e` a real zero rather than
    # a missing value on both sides.
    ("frame_global_read_and_mutated_from_functions",
     "struct Pair:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n"
     "\n"
     "    def first(self) -> Int:\n"
     "        return self.x\n"
     "\n"
     "_g = Pair()\n"
     "\n"
     "def read_from_module() -> Int:\n"
     "    return _g.first()\n"
     "\n"
     "def bump() -> Int:\n"
     "    _g.x = 41\n"
     "    return _g.first()\n"
     "\n"
     "def main(n):\n"
     "    var p = Pair()\n"
     "    p.x = 1\n"
     "    a: Int = p.first()\n"
     "    print(a)\n"
     "    b: Int = read_from_module()\n"
     "    print(b)\n"
     "    c: Int = bump()\n"
     "    print(c)\n"
     "    d: Int = read_from_module()\n"
     "    print(d)\n"
     "    e: Int = _g.y\n"
     "    print(e)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "1\n0\n41\n41\n0\n"),

    # A field whose value comes from `__init__`, which is the `ModuleLoader`
    # shape and the one the whole row is about: a struct that DECLARES nothing and
    # gets its whole value from its constructor. `_g.n` reads 7 rather than 0,
    # and it is the only thing here that distinguishes "the image laid the field
    # out" from "the image laid zeros out and the program got lucky".
    #
    # `_bump` is a free function rather than a method on purpose: it is the
    # `ModuleLoader_load_module(_module_loader, …)` call site — a name that
    # holds the frame reaching a callee that wants one — and the row above only
    # reaches the callee through a method.
    ("frame_global_with_an_init_assigned_field",
     "struct Named:\n"
     "    var tag: String\n"
     "    var n: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.tag = \"hello\"\n"
     "        self.n = 7\n"
     "\n"
     "    def show(self) -> String:\n"
     "        return self.tag\n"
     "\n"
     "_named = Named()\n"
     "\n"
     "def _bump() -> Int:\n"
     "    return _named.n + 1\n"
     "\n"
     "def read() -> String:\n"
     "    return _named.show()\n"
     "\n"
     "def main(n):\n"
     "    s: String = read()\n"
     "    print(s)\n"
     "    k: Int = _bump()\n"
     "    print(k)\n"
     "    m: Int = _named.n\n"
     "    print(m)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "hello\n8\n7\n"),

    # A CONTAINER field, and the strongest of the three: the frame's word for it
    # is a pointer to a second-level blob laid out beside the frame, so reading
    # `items[2]` exercises the nested fixup rather than a number that happened to
    # be in the image. `read_at(0)`/`read_at(2)` reach the slot through a method
    # on `_b` — the frame address going to a callee — and the `1` is the first
    # element of a blob whose address was in a word of a frame whose address was
    # in a slot.
    ("frame_global_with_a_container_field",
     "struct Boxy:\n"
     "    var items: List[Int]\n"
     "    var n: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.items = [1, 2, 3]\n"
     "        self.n = 7\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        return self.items[i]\n"
     "\n"
     "_b = Boxy()\n"
     "\n"
     "def read_at(i: Int) -> Int:\n"
     "    return _b.get(i)\n"
     "\n"
     "def main(n):\n"
     "    a: Int = read_at(0)\n"
     "    print(a)\n"
     "    b: Int = read_at(2)\n"
     "    print(b)\n"
     "    c: Int = _b.n\n"
     "    print(c)\n"
     "    return 0\n"
     "\n"
     "main(0)\n", "1\n3\n7\n"),

    # THE CROSS-IMAGE ROW, and the one that would be impossible without the
    # fix. `helper.mojo` declares the struct and the module-level value; it is
    # compiled into a DYLIB, and `prog.mojo` links it. A frame in the executable's
    # own `__DATA` would say nothing about a dylib's, and a dylib has no entry
    # point at all — its body runs from `__TEXT,__init_offsets`, so the store the
    # old path emitted happened at LOAD time and the block died with it. So `4` on
    # the third line is the frame surviving the body of a library that has already
    # returned, in a segment the loader mapped at a slide.
    ("frame_global_mutated_across_a_dylib_boundary",
     {"helper.mojo":
      "struct Cfg:\n"
      "    var n: Int\n"
      "    var tag: String\n"
      "\n"
      "    def __init__(self):\n"
      "        self.n = 3\n"
      "        self.tag = \"cfg\"\n"
      "\n"
      "    def bump(self) -> Int:\n"
      "        self.n = self.n + 1\n"
      "        return self.n\n"
      "\n"
      "    def read(self) -> Int:\n"
      "        return self.n\n"
      "\n"
      "cfg = Cfg()\n"
      "\n"
      "def bump_cfg() -> Int:\n"
      "    return cfg.bump()\n"
      "\n"
      "def read_cfg() -> Int:\n"
      "    return cfg.read()\n",
      "prog.mojo":
      "from helper import bump_cfg, read_cfg\n"
      "\n"
      "def main(n):\n"
      "    a: Int = read_cfg()\n"
      "    print(a)\n"
      "    b: Int = bump_cfg()\n"
      "    print(b)\n"
      "    c: Int = read_cfg()\n"
      "    print(c)\n"
      "    return 0\n"
      "\n"
      "main(0)\n"}, "3\n4\n4\n"),
]

# The refusals the fix must NOT have lifted. Each one is a shape where the frame
# cannot be written into the image, and the point of pinning them is that
# "lifted" and "correctly refused" look identical from the outside: a build that
# said yes to any of these would lay out a frame whose words are not the value the
# source means, which is a plausible wrong answer rather than a diagnostic.
FRAME_REFUSALS = [
    # A frame whose field is computed by a CALL. There is no word for it before
    # the program runs, so there is no frame to write into `__DATA`, so the slot
    # stays the one the body fills — and the disagreement refusal is STILL what
    # says so. It has to be a METHOD as the holder-holding callee rather than a
    # free function taking the struct: `def get(s: S)` reaches
    # `_check_declared_parameter` first, which is a different refusal about a
    # declared type, so a free-function spelling of this row would pass for the
    # wrong reason.
    ("a_frame_field_computed_by_a_call_is_still_refused",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(self, k: Int):\n"
     "        self.a = k\n"
     "        self.b = 1\n"
     "\n"
     "    def first(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "_s = S(3)\n"
     "\n"
     "def get() -> Int:\n"
     "    return _s.first()\n"
     "\n"
     "def main(n):\n"
     "    var p = S(1)\n"
     "    a: Int = p.first()\n"
     "    print(a)\n"
     "    b: Int = get()\n"
     "    print(b)\n"
     "    return 0\n"
     "\n"
     "main(0)\n",
     "One parameter, two kinds of value"),

    # A module global a FUNCTION assigns. The image does not hold the value for
    # the whole run — `reset()`'s store would put a fresh block address into a
    # word every reader dereferences as the struct's fields, which is the very
    # lifetime defect the fix exists to remove — so the lift is withheld and the
    # old path stands. Pinned because it is the one input the
    # `functions_writing_globals` gate in `prepare_module_frame_slots` exists
    # for, and a build that ignored the gate would build this and SIGSEGV.
    ("a_frame_global_a_function_writes_through_global_is_still_refused",
     "struct Pair:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n"
     "\n"
     "    def first(self) -> Int:\n"
     "        return self.x\n"
     "\n"
     "_g = Pair()\n"
     "\n"
     "def reset() -> None:\n"
     "    global _g\n"
     "    _g = Pair()\n"
     "\n"
     "def main(n):\n"
     "    reset()\n"
     "    var p = Pair()\n"
     "    p.x = 9\n"
     "    a: Int = p.first()\n"
     "    print(a)\n"
     "    b: Int = _g.first()\n"
     "    print(b)\n"
     "    return 0\n"
     "\n"
     "main(0)\n",
     "One parameter, two kinds of value"),
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=kw.pop("timeout", BUILD_TIMEOUT), cwd=HERE, **kw)


def interpreter_stdout(tmpdir, name, files):
    """`fire.py run` on the entry file — the reference SEMANTICS.

    The interpreter has no `__DATA`, no slot index and no image, so it cannot
    catch an addressing bug; it is here to catch a SEMANTIC one, and it shares
    no code with either backend below the parser.

    The interpreter reads the SAME path the images are built from
    (`<tmpdir>/<name>.mojo`, `write_sources`), not a `.interp.mojo` copy of it.
    That was a `.interp.mojo` and it was invisible until a case's answer was the
    source's own path: `__file__` is a fact about the file, so two spellings of
    the same file are two different answers, and the harness was the thing that
    made them differ. One path per case now, which is also what "the same
    program" means.
    """
    entry = files["prog.mojo"] if isinstance(files, dict) else files
    src, _paths = write_sources(tmpdir, name, files)
    p = run([sys.executable, FIRE, "run", src], timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


def write_sources(tmpdir, name, files):
    """Write a case's files and return (entry_path, {basename: path})."""
    if not isinstance(files, dict):
        path = os.path.join(tmpdir, name + ".mojo")
        with open(path, "w") as f:
            f.write(files)
        return path, {name + ".mojo": path}
    paths = {}
    for base, text in files.items():
        p = os.path.join(tmpdir, f"{name}.{base}")
        with open(p, "w") as f:
            f.write(text)
        paths[base] = p
    return paths["prog.mojo"], paths


def image_stdout(tmpdir, name, backend, files):
    """Build and RUN the case as an image on one backend."""
    entry, paths = write_sources(tmpdir, name, files)
    if isinstance(files, dict):
        # A second module has to be importable by name, so both files sit in
        # the same directory under the names they are imported by.
        for base, p in paths.items():
            os.replace(p, os.path.join(tmpdir, base))
        for base in files:
            paths[base] = os.path.join(tmpdir, base)
        entry = os.path.join(tmpdir, "prog.mojo")
    out = os.path.join(tmpdir, f"{name}.{backend}")
    p = run([sys.executable, FIRE, "build", "--formal", "--no-prove",
             f"--backend={backend}", "-o", out, entry])
    if p.returncode != 0:
        return None, f"build failed on {backend}: {(p.stderr or p.stdout).strip()[-300:]}"
    q = run([out], timeout=RUN_TIMEOUT)
    return (q.returncode, q.stdout), None


def run_case(name, files, want_stdout, tmpdir, verbose):
    # A case's expected answer may be a CALLABLE of (tmpdir, name) instead of
    # a string, and one case needs that: `__file__` is the path of the source
    # the build was handed, which is `<tmpdir>/<name>.mojo` — a path that is
    # different in every run of this file, in every checkout, and on every
    # machine. Writing it down beside the case would be a second answer to the
    # same question and would go stale the moment the tree moved; computing it
    # from the argument the runner itself passed to `fire.py` is the only way
    # to pin the value rather than a value.
    want = want_stdout(tmpdir, name) if callable(want_stdout) else want_stdout
    got = {}
    for backend in BACKENDS:
        result, err = image_stdout(tmpdir, name, backend, files)
        if err:
            return False, err
        got[backend] = result

    # A case written with `printf` has no interpreter reference: `printf` is
    # not a name the interpreter resolves, so the case's expected value stands
    # on its own. Everything else is checked against the interpreter, because
    # that comparison is the one that catches a SEMANTIC divergence rather than
    # an addressing one.
    entry = files["prog.mojo"] if isinstance(files, dict) else files
    if "printf(" not in entry:
        rc, text = interpreter_stdout(tmpdir, name, files)
        if rc != 0:
            return False, (f"the interpreter refused the case, so there is no "
                           f"reference answer to compare the images against: "
                           f"{text.strip()[-300:]}")
        if text.strip() != want.strip():
            return False, (f"the interpreter disagrees with the case's "
                           f"expected answer: got {text.strip()!r}, want "
                           f"{want.strip()!r}")

    arm, x86 = got["arm64"], got["x86_64"]
    for backend, (rc2, out) in got.items():
        if rc2 != 0:
            return False, f"{backend} image exited {rc2}"
        if out.strip() != want.strip():
            return False, (f"{backend} image printed {out.strip()!r}, "
                           f"want {want.strip()!r}")
    if arm != x86:
        return False, (f"the two architectures disagree: arm64 {arm!r} vs "
                       f"x86_64 {x86!r}. They are one language implementation, "
                       f"so this is a bug in whichever of the two is wrong, not "
                       f"a platform difference.")
    if verbose:
        via = "the interpreter" if "printf(" not in entry else "the expected value"
        print(f"      arm64, x86_64 and {via} agree: {want.strip()!r}")
    return True, ""


def run_refusal(name, source, needle, absent, tmpdir, verbose):
    """Both backends must refuse, naming `needle` and NOT naming `absent`.

    `absent` is the sentence the refusal must not contain, and it exists
    because a diagnostic that names the wrong thing about the name it names is
    this file's subject: one row asserts the reason a name HAS a `__DATA` slot,
    and that reason is not the same for every slot (`a_container_global_says_it_
    is_a_constant_not_a_variable`). It is optional so the rows that only care
    about the missing initializer stay one tuple long.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        p = run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                 f"--backend={backend}", "-o", out, src])
        if p.returncode == 0:
            return False, (f"--backend={backend} BUILT a module global whose "
                           f"initializer it cannot materialise. The image would "
                           f"run and read the zeros in an unwritten slot, which "
                           f"is a plausible wrong answer rather than an error.")
        text = (p.stderr or p.stdout)
        if needle not in text:
            return False, (f"--backend={backend} refused, but not naming the "
                           f"missing initializer ({needle!r}): "
                           f"{text.strip()[-300:]}")
        if absent is not None and absent in text:
            return False, (f"--backend={backend} refused with {absent!r}, which "
                           f"is the sentence this row says must not appear here: "
                           f"{text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on both backends: {needle!r}")
    return True, ""


# ── the LAYOUT cases: what the segment holds, read out of the image ────────
#
# Every case above asks what the program PRINTS. These two ask what the image
# CONTAINS, and they are here for the same reason the rest of this file is: the
# data segment is an agreement between a codegen that computes an address, a
# linker that maps it, and a loader that slides it, and nothing about a printed
# number can tell you the segment is there at all.
#
# `LAYOUT_CASES` is `(name, source, checker)`, and the checker is handed the
# bytes of the `__DATA` segment plus the image's own segment table.

LAYOUT_CASES = []


def _segments(data):
    """`[(name, vmaddr, vmsize, fileoff, filesize)]` from a Mach-O load command
    list, with a reader written here rather than imported.

    `formal/macho_linker.py` writes these images; asking the writer whether it
    emitted a segment is how a writer's bug becomes invisible. Sixteen bytes of
    header and the `LC_SEGMENT_64` layout, nothing else."""
    import struct
    ncmds = struct.unpack_from("<I", data, 16)[0]
    out, pos = [], 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, pos)
        if cmd == 0x19:            # LC_SEGMENT_64
            name = data[pos + 8:pos + 24].split(b"\0")[0].decode("ascii")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from(
                "<QQQQ", data, pos + 24)
            out.append((name, vmaddr, vmsize, fileoff, filesize))
        pos += cmdsize
    return out


def _reserved_words_are_there_and_unwritten(tmpdir, name, verbose):
    """An image with NO module global still has a `__DATA`, and its two
    reserved words are the ones the model says they are.

    Every other case in this file declares a `global`, so every other case would
    pass with the segment emitted for the globals alone. The program that
    motivates the word is three lines with no globals at all:

        def deep(n: Int) -> Int:
            if n <= 0: return 0
            return deep(n - 1) + 1

    and `deep(62)` used to be a SIGSEGV on arm64, so the guard that fixed it
    needed a word in an image exactly like this one — an image with nothing
    else in its `__DATA` (`model.STACK_FLOOR_BUDGET_BYTES`,
    `model.stack_floor_guarded_names`).

    What is asserted, per backend:

      * the image HAS a `__DATA` segment, and it is the one `globals_base`
        declares — a segment at the wrong address would be a segment the code's
        ADRP/ADD never reaches;
      * the image carries BOTH reserved words, at the offsets
        `GlobalDataImage.init_flag_offset` and `.stack_floor_offset`, computed by
        the model rather than written here, so this case cannot pin a layout the
        model has moved;
      * both read as ZERO, which is the state that says "the globals have not
        been filled in" and "no floor has been stored yet". A floor word that
        arrived non-zero would be a lie about a floor nobody computed.

    The last of those is the one a reader should not skip: the guard this word
    exists for must treat zero as UNKNOWN rather than as a floor, because a zero
    floor compares as "nothing is below the stack pointer" and so never fires.
    That is the safe direction — the guard is silent, exactly as it is today —
    and it is why an unwritten word is not a bug.
    """
    from formal import model as M
    from formal.build import globals_base
    for backend in BACKENDS:
        entry, _paths = write_sources(tmpdir, name,
                                      "def deep(n: Int) -> Int:\n"
                                      "    if n <= 0:\n"
                                      "        return 0\n"
                                      "    return deep(n - 1) + 1\n"
                                      "\n"
                                      "def main(n: Int) -> Int:\n"
                                      "    printf(\"%d\\n\", deep(3))\n"
                                      "    return 0\n")
        out = os.path.join(tmpdir, f"{name}.{backend}")
        p = run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                 f"--backend={backend}", "-o", out, entry])
        if p.returncode != 0:
            return False, (f"build failed on {backend}: "
                           f"{(p.stderr or p.stdout).strip()[-300:]}")
        with open(out, "rb") as f:
            data = f.read()
        segs = dict((s[0], s) for s in _segments(data))
        if "__DATA" not in segs:
            return False, (f"{backend}: the image has no __DATA segment at all, "
                           f"so the word the stack guard needs is not there. "
                           f"Segments: {sorted(segs)}")
        _n, vmaddr, _vmsize, fileoff, filesize = segs["__DATA"]
        if vmaddr != globals_base("macho"):
            return False, (f"{backend}: __DATA is mapped at {vmaddr:#x} but the "
                           f"codegen computes slot addresses against "
                           f"{globals_base('macho'):#x}; the two are the same "
                           f"constant read twice and they disagree")
        image = M.build_data_image({}, globals_base("macho"))
        need = max(image.init_flag_offset,
                   image.stack_floor_offset) + M.GLOBAL_SLOT_BYTES
        if filesize < need:
            return False, (f"{backend}: __DATA is {filesize} bytes and the two "
                           f"reserved words end at {need}, so the segment is "
                           f"smaller than the bookkeeping in it")
        for what, at in (("initializer flag", image.init_flag_offset),
                         ("stack floor", image.stack_floor_offset)):
            word = int.from_bytes(data[fileoff + at:fileoff + at + 8], "little")
            if word != 0:
                return False, (f"{backend}: the {what} word at __DATA+{at} "
                               f"reads {word:#x}, not 0 — nothing writes it "
                               f"yet, and a non-zero word here would be a "
                               f"claim about state that does not exist")
        if verbose:
            print(f"      {backend}: __DATA at {vmaddr:#x}, flag at "
                  f"+{image.init_flag_offset}, floor at "
                  f"+{image.stack_floor_offset}, both zero")
    return True, ""


LAYOUT_CASES.append(("reserved_words_exist_in_an_image_with_no_globals",
                     _reserved_words_are_there_and_unwritten))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the images are arm64, host is {platform.machine()}")
        return 0

    # The refusal tables may carry a FOURTH element — a sentence the message
    # must NOT contain — so they are widened to four here rather than indexed,
    # and every other table stays three.
    everything = ([(c[0], c[1], c[2], None) for c in CASES]
                  + [(c[0], c[1], c[2], None) for c in FRAME_CASES]
                  + [(c[0], c[1], c[2], c[3] if len(c) > 3 else None)
                     for c in REFUSALS]
                  + [(c[0], c[1], c[2], c[3] if len(c) > 3 else None)
                     for c in FRAME_REFUSALS]
                  + [(c[0], None, c[1], None) for c in LAYOUT_CASES])
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    known = {c[0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2
    refusal_names = {c[0] for c in REFUSALS} | {c[0] for c in FRAME_REFUSALS}
    layout_names = {c[0] for c in LAYOUT_CASES}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, files, want, absent in selected:
            try:
                if name in refusal_names:
                    ok, detail = run_refusal(name, files, want, absent, tmpdir,
                                             args.verbose)
                elif name in layout_names:
                    ok, detail = want(tmpdir, name, args.verbose)
                else:
                    ok, detail = run_case(name, files, want, tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                if args.verbose:
                    print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    total = passed + failed
    print(f"\nformal globals: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
