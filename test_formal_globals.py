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


def run_refusal(name, source, needle, tmpdir, verbose):
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
    if verbose:
        print(f"      refused identically on both backends: {needle!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: the images are arm64, host is {platform.machine()}")
        return 0

    everything = ([(c[0], c[1], c[2]) for c in CASES]
                  + [(c[0], c[1], c[2]) for c in REFUSALS])
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    known = {c[0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): {sorted(set(args.cases) - known)}",
              file=sys.stderr)
        return 2
    refusal_names = {c[0] for c in REFUSALS}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, files, want in selected:
            try:
                if name in refusal_names:
                    ok, detail = run_refusal(name, files, want, tmpdir,
                                             args.verbose)
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
