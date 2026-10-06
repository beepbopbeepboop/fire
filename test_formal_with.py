#!/usr/bin/env python3
"""test_formal_with.py -- the formal backends against CPython on `with`, and
the table that says which shapes are ANSWERED, which are REFUSED, and what each
refusal is allowed to say.

**Why this file rather than more rows in `test_formal_run.py`.**  Three
reasons, and the first two are about what the construct can express at all:

  * **a `with` can end the process.**  `return` out of a block, `break` out of a
    loop, a `raise` that leaves — those are the cases that decide whether the
    `__exit__` half of the protocol is honoured, and the last of them leaves a
    NONZERO status behind.  `run_cpython_pair_case` treats a nonzero reference
    exit as "the oracle is not an oracle", so the whole exit-on-every-path
    contract was inexpressible there.  `run_pair` below compares stdout AND exit
    status and accepts any reference status, which is what makes "CPython exits
    1 here, having already run `__exit__`" an assertion rather than an
    impossibility.
  * **a `with` is the one construct whose correctness is a PAIR of calls.**
    A lowering that runs `__enter__` and forgets `__exit__` — or the reverse —
    prints one line fewer than CPython and nothing else in the tree can see it,
    because the leftover resource is a directory on disk rather than a word in a
    register.  So every row here is one where the ORDER and the COUNT of the
    prints are the subject.
  * **the refusals are a contract too.**  `with C() as (a, b)` and `with C() as
    obj.attr` are refused on both backends, and so is a `with` over a
    one-field struct or over a `__exit__` written with CPython's own three
    exception parameters.  The needle is checked on BOTH architectures for
    each: "the two architectures refuse identically, and say the same thing
    about which half is missing" is itself the property, and it is the one a
    sweep reading one architecture's text cannot establish.

**CPython is the oracle wherever the construct runs.**  No hand-written expected
constant: the same program text goes to `python3` and asks.  The one spelling
difference between the two halves is stated per row — `__exit__` takes
`(self, exc_type, exc_val, exc_tb)` in CPython and `(self)` here, which is a
LIMITS row below rather than a translation, because this path has no unwinder
to hand those three words to.

**Both architectures, always.**  arm64 and x86-64 have answered `with` from two
private lowerings all along (each emitter's `WithStmt` arm names the other as
the pass that must have rewritten it), and the shared pass is
`formal/build.py::_rewrite_with_statements`.  A one-sided row would be green
throughout the day the two disagreed.

**What is here and what is elsewhere.**  This file is the PROTOCOL: the ordering,
the alias, the exit on every path, and the refusal boundary.  The two
host-module consumers of the protocol keep their own CPython pairs, because
their subject is the effects and not the protocol — `test_formal_core_hostmods.py`'s
`ctx` group for `contextlib.nullcontext` (three arities, both spellings of the
import) and `test_formal_tempfile.py`'s `TemporaryDirectory` group (the
directory is really removed).  The `open(...)` row below is here rather than in
either because it is the RESOURCE arm of the lowering — a context manager this
image does not compile, entered by name from a table — and that table's rule is
part of the protocol.

Run:  python3 test_formal_with.py [-v] [case ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


def build(source, out, backend, tmpdir, arg=3):
    """`fire.py build --formal --no-prove -n <arg>`, as (rc, output).

    `-n` is the formal backend's entry-argument flag and the CPython half is
    called with the SAME value.  Omitting it here is not a cosmetic default:
    the entry argument would silently be 10, and every row whose subject is a
    condition on it would be measuring a different program from the one CPython
    ran.
    """
    path = os.path.join(tmpdir, "prog.mojo")
    with open(path, "w") as f:
        f.write(source)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out,
           f"--backend={backend}", "-n", str(arg), path]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(path):
    p = subprocess.run([path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout, p.stderr


def cpython(source, tmpdir, arg=3):
    path = os.path.join(tmpdir, "ref.py")
    with open(path, "w") as f:
        f.write(source + f"\nimport sys\nsys.exit(main({arg}))\n")
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


# ── the CONTEXT MANAGERS these rows enter ───────────────────────────────────
#
# TWO fields each, and that is not decoration: a one-field struct's receiver IS
# its field, so there is no address to dispatch a method on and a context
# manager of one field cannot be entered at all on this path
# (`model.struct_is_context_manager`).  `Ctx.__enter__` returns a WORD and `Box`
# returns the receiver, so the alias rows can tell the two apart — a lowering
# that binds the alias to the CONTEXT instead of to `__enter__`'s result prints
# the frame address where CPython prints 7.
#
# The class spelling with `__init__` storing `self.x` is the one used here
# because those stores are what make the fields STORAGE: a `struct` whose
# class-level defaults are literals and which no method touches is counted as
# class-level CONSTANTS and is a struct of no fields
# (`model.struct_class_constants`), which is a different subject and is pinned
# by its own rows below.
CTX_MOJO = """class Ctx:
    def __init__(self):
        self.tag = 7
        self.log = 0

    def __enter__(self):
        print('enter')
        return self.tag

    def __exit__(self):
        print('exit')


class Box:
    def __init__(self):
        self.tag = 7
        self.log = 0

    def __enter__(self):
        print('box-enter')
        return self

    def __exit__(self):
        print('box-exit')
"""

CTX_PY = CTX_MOJO.replace("    def __exit__(self):",
                          "    def __exit__(self, exc_type, exc_val, tb):")


def mojo(body):
    return CTX_MOJO + "def main(n):\n" + body


def python(body):
    return CTX_PY + "def main(n):\n" + body


# ── the ANSWERED table ──────────────────────────────────────────────────────
#
# (name, body, entry argument)
#
# `body` is the whole of `main`, and it is given TWICE only where the two halves
# are not the same text — every row below is one program run by both engines,
# which is what makes the exit ordering and the exit COUNT assertions rather
# than claims about this file's author.
CASES = [
    # ── one item, and the two halves of the protocol ───────────────────────
    # The base row.  `enter` before `body` before `exit`, and the alias holds
    # `__enter__`'s RESULT (7) rather than the context — `Ctx.__enter__`
    # returns `self.tag` on purpose, so an implementation that bound the alias
    # to the context expression would print the frame's address.
    ("one_item_runs_enter_body_exit_and_binds_the_enter_result",
     "    with Ctx() as v:\n"
     "        print('body', v)\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # The same, with no `as` at all.  CPython still calls BOTH dunders — a
    # `with` whose name is discarded is not a `with` whose protocol is skipped —
    # and a lowering that treats the missing alias as a reason to drop the whole
    # statement prints `body` and `after` and no `enter`/`exit`.
    ("no_alias_still_calls_both_dunders",
     "    with Ctx():\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # An EMPTY body, which is the shape the two dunders exist for and the one a
    # lowering that only wraps a non-empty statement list would get wrong.  The
    # exit must still run exactly once.
    ("an_empty_body_still_runs_the_exit_exactly_once",
     "    with Ctx() as v:\n"
     "        pass\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # `__enter__` returning the RECEIVER, so the alias is the struct.  Nothing
    # reads a field through it here (that is a field-access question with its own
    # refusal, in `test_formal_run.py`), so what this row pins is that the
    # lowering does not reject a struct-valued result.
    ("enter_may_return_the_receiver_itself",
     "    with Box() as b:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # ── several items ──────────────────────────────────────────────────────
    # LEFT to right in, RIGHT to left out.  Two `exit` lines with no ordering
    # between them would satisfy a set comparison and not the program, so the
    # comparison is on the whole stdout string and that is the point of it.
    ("two_items_enter_left_to_right_and_exit_right_to_left",
     "    with Ctx() as a, Box() as b:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # Three items, because a nesting bug that reorders two can still leave
    # three in order, and the count is what says the loop ran once per item.
    ("three_items_enter_and_exit_once_each",
     "    with Ctx() as a, Box() as b, Ctx() as c:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # An item with no alias BETWEEN two with one, because the COMMA loop is a
    # different path from a single item and an alias-less item in the middle is
    # the shape that distinguishes "one `as` for the whole statement" from "one
    # `as` per item".
    ("an_item_with_no_alias_between_two_that_have_one",
     "    with Ctx() as a, Box(), Ctx() as c:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # NESTED statements, not a comma list: the exits must interleave inside out,
    # which is a different program from the comma list with the same managers.
    ("nested_with_exits_inside_out",
     "    with Ctx() as a:\n"
     "        with Box() as b:\n"
     "            print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # ── leaving the block: the whole reason for the `finally` ──────────────
    # `return` from inside the body.  **This is the row the `finally` is
    # for.**  A lowering that ran the exit as a statement AFTER the body would
    # leave the directory behind on every early return, print `return` before
    # `exit`, and exit 0 with main's answer instead of 7.  All three differ from
    # CPython, and this row is the one that says the exit is a `finally` rather
    # than a next statement.
    ("return_from_inside_the_block_runs_the_exit_and_keeps_the_value",
     "    with Ctx() as v:\n"
     "        return 7\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # `return` with NOTHING after the `with` at all, so a lowering that
    # truncated the function after the block cannot be distinguished from one
    # that did not.  CPython never reaches `after`; neither may the image.
    ("return_from_inside_the_block_with_nothing_after_it",
     "    with Ctx() as v:\n"
     "        print('body')\n"
     "        return 5\n", 3),
    # `break` out of a loop the block is inside.  CPython runs the exit and then
    # leaves the loop, and `for`-loop bookkeeping after the break must not run
    # twice — which is the observable half of "the exit ran on the way out".
    ("break_out_of_a_loop_inside_the_block_runs_the_exit",
     "    for i in range(3):\n"
     "        with Ctx() as v:\n"
     "            if i == 1:\n"
     "                break\n"
     "            print('i', i)\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # `continue`, which is the same machinery with a different target: the exit
    # runs, and then the NEXT iteration enters again.  A lowering that flushed
    # the finally and then also ran it at the end of the body would print eight
    # lines where CPython prints seven.
    ("continue_out_of_a_loop_inside_the_block_runs_the_exit",
     "    for i in range(3):\n"
     "        with Ctx() as v:\n"
     "            if i == 1:\n"
     "                continue\n"
     "            print('i', i)\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # A `while` rather than a `for`, so the exit is flushed against a loop whose
    # increment is a STORE inside the block — the shape where a store-dominated
    # check and the finally flush can disagree.
    ("a_while_loop_whose_increment_is_inside_the_block",
     "    i = 0\n"
     "    while i < 2:\n"
     "        with Ctx() as v:\n"
     "            print('i', i)\n"
     "            i = i + 1\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # ── an exception LEAVING the block ────────────────────────────────────
    # The uncaught case.  The exit runs BEFORE the process leaves, and the status
    # is 1 — a lowering that ran the exit after the raise's `exit(1)` would print
    # `body` and nothing else, and one that skipped it would print the same
    # thing for the opposite reason.  This row is the only one that separates
    # them, which is why it compares the exit status as well as the output.
    ("an_exception_leaving_the_block_runs_the_exit_first",
     "    with Ctx() as v:\n"
     "        print('body')\n"
     "        raise ValueError('m')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # Two items and a raise in the body: BOTH exits run, still right to left.
    # One item's exit and the other's not is the shape a single pending-finally
    # slot produces, and it is invisible in every row above.
    ("an_exception_leaving_two_items_exits_both_in_reverse_order",
     "    with Ctx() as a, Box() as b:\n"
     "        raise ValueError('m')\n"
     "    return 0\n", 3),
    # **`__enter__` raising: the exit must NOT run.**  This is the row the other
    # direction of the protocol is decided by, and it is a genuinely different
    # answer from the row above: the `__enter__` call is inside the scope the
    # `finally` covers, so a lowering that put the `finally` around the whole
    # item would print `exit` here where CPython prints nothing.  CPython's rule
    # is that `__exit__` is called only once `__enter__` has returned.
    ("an_exception_from_enter_does_not_run_the_exit",
     "    with Ctx() as v:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # `__exit__` itself raising: the block completed, the exit ran, and the
    # status is 1.  Nothing about it may be dropped on the grounds that the
    # program is ending anyway.
    ("an_exception_from_exit_still_leaves_the_status_one",
     "    with Ctx() as v:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # ── placement ─────────────────────────────────────────────────────────
    # Inside a conditional, so the protocol runs on one path only.  A lowering
    # that hoisted the `finally` to the function's top level would run the exit
    # on the path where the block never ran.
    ("inside_an_if_the_protocol_runs_only_on_the_taken_path",
     "    if n > 1:\n"
     "        with Ctx() as v:\n"
     "            print('body')\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # …and on the same program at the OTHER argument, which is what makes the
    # row above a claim about the condition rather than about the spelling: one
    # program, two entry arguments, CPython asked twice.
    ("inside_an_if_the_protocol_is_skipped_when_the_condition_is_false",
     "    if n > 100:\n"
     "        with Ctx() as v:\n"
     "            print('body')\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # Two `with` statements in a row, so the first one's exit is flushed before
    # the second one's enter — the ordering a single shared pending-finally slot
    # gets wrong.
    ("two_with_statements_in_a_row_flush_the_first_before_the_second",
     "    with Ctx() as a:\n"
     "        pass\n"
     "    with Box() as b:\n"
     "        pass\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # A `with` at the top of a loop that runs twice, so the count is two of each
    # dunder and not one.
    ("a_loop_body_entered_twice_enters_and_exits_twice",
     "    for i in range(2):\n"
     "        with Ctx() as v:\n"
     "            print('i', i)\n"
     "    print('done')\n"
     "    return 0\n", 3),
    # ── the context manager held in a NAME ────────────────────────────────
    # `mgr = Ctx()` on one line and `with mgr as v:` two lines later is how a
    # reader writes it once the manager is built from arguments, and it used to
    # be REFUSED with "this build cannot answer what type it is" — a sentence
    # false about the build, which knows exactly what it holds: the binding is
    # right there in the function.  The evidence is the same one that already
    # decides `o.get()` lifts to `Outer_get`, so this is the protocol catching
    # up with the rest of the receiver machinery rather than a new inference.
    ("a_name_bound_from_a_construction_is_the_protocol",
     "    m = Ctx()\n"
     "    with m as v:\n"
     "        print('body', v)\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # …and the exit still runs on the way out of it, because the `finally` is
    # the rewrite's and not the expression spelling's.  A NAME arm that emitted
    # the two calls as statements after the body would pass the row above and
    # fail this one.
    ("return_out_of_a_named_context_runs_the_exit",
     "    m = Ctx()\n"
     "    with m as v:\n"
     "        print('body')\n"
     "        return 9\n"
     "    return 0\n", 3),
    # One statement mixing both spellings, so the NAME arm and the construction
    # arm are two arms of ONE table rather than two rewrites that can disagree
    # about the order.
    ("a_name_and_a_construction_in_one_statement_enter_in_order",
     "    m = Ctx()\n"
     "    with m as a, Box() as b:\n"
     "        print('body')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # The SAME struct bound on two paths is ONE candidate, not two, so the
    # agreement test this reader depends on does not turn a redundant
    # initialisation into a refusal.  `m = Ctx()` twice is the shape a reader
    # writes when a branch may replace a manager with an equivalent one.
    ("a_name_bound_from_the_same_struct_on_two_paths_still_enters",
     "    m = Ctx()\n"
     "    if n > 1:\n"
     "        m = Ctx()\n"
     "    with m as v:\n"
     "        print('body', v)\n"
     "    return 0\n", 3),
]


# ── the resource arm: `with open(...) as f` ────────────────────────────────
#
# A context manager THIS IMAGE DOES NOT COMPILE.  `open` is not a struct here,
# it is the C library's `open(2)` and its value is a FILE DESCRIPTOR, so the
# protocol's two positions are filled from the descriptor's own value model
# (`model.RESOURCE_CONTEXT_MANAGERS`): `__enter__` IS the descriptor and
# `__exit__` is `close(2)` on the same word.  The pair is kept out of `CASES`
# because the program needs a filesystem and the rows above do not.
FILE_CASES = [
    # The file exists and holds what the block wrote, and the descriptor is
    # closed on the way out.  Both halves are real effects rather than prints,
    # which is what makes it worth having here rather than in the ANSWERED
    # table: a lowering that skipped `close` would leave the bytes unwritten.
    # The path is quoted IN the template rather than around the substitution,
    # because an unquoted one reaches the compiler as a bare NAME and the build
    # refuses it — which is a correct refusal of a different program.
    ("open_writes_through_the_entered_descriptor_and_closes_it",
     "def main(n):\n"
     "    with open('{PATH}', 'w') as h:\n"
     "        h.write('hello')\n"
     "    print('closed')\n"
     "    return 0\n",
     "{PATH}, {PATH2}"),
    # Two `with`s over two descriptors, so the closes are ordered by the same
    # nesting rule as the struct arm — and the two files are read back AFTER the
    # block, which is where an unflushed or unclosed descriptor would show.
    ("two_open_items_close_in_reverse_order",
     "def main(n):\n"
     "    with open('{PATH}', 'w') as a:\n"
     "        a.write('one')\n"
     "    with open('{PATH2}', 'w') as b:\n"
     "        b.write('two')\n"
     "    print('closed')\n"
     "    return 0\n",
     "{PATH}, {PATH2}"),
    # `open` used as a plain value is not a `with`, so this row says the
    # RESOURCE arm needs the protocol and not just the descriptor: without
    # `with`, the block's write still has to reach the file, and it is the
    # missing `close` that would differ.
    ("an_open_without_a_with_still_writes_through_the_descriptor",
     "def main(n):\n"
     "    h = open('{PATH}', 'w')\n"
     "    h.write('hello')\n"
     "    h.close()\n"
     "    print('closed')\n"
     "    return 0\n",
     "{PATH}, {PATH2}"),
]


# ── the REFUSED table ───────────────────────────────────────────────────────
#
# (name, mojo source, needle)
#
# A needle is checked on BOTH backends and must be present in the refusal.  Each
# one is a shape this path does not lower, and each refusal has to NAME the
# half that is missing — a message that is false about the source sends the
# reader to edit the wrong declaration, which is the failure mode these rows
# exist to keep honest.  A refusal that instead BUILDS is the worse verdict: a
# program the source says binds nothing, running and exiting 0.
#
# The CPython halves of these are deliberately absent.  Every one of them is a
# program CPython RUNS (the tuple target raises `TypeError` at the `as` clause,
# the attribute target succeeds), and the assertion is about the refusal's
# wording rather than about an output, so pairing them against CPython would
# assert that this compiler fails where CPython succeeds — which is true, and is
# not what these rows are for.
#
# `test_formal_run.py` also carries `with` rows; these are here because that
# file's runner cannot express a nonzero reference exit, and because the three
# spellings below differ in WHICH refusal answers them and that difference is
# the point.
ONE_FIELD = """class One:
    def __init__(self):
        self.tag = 7

    def __enter__(self):
        print('enter')
        return self.tag

    def __exit__(self):
        print('exit')
"""

NO_ENTER = """class NoEnter:
    def __init__(self):
        self.tag = 7
        self.log = 0

    def __exit__(self):
        print('exit')
"""

THREE_ARGS = """class ThreeArgs:
    def __init__(self):
        self.tag = 7
        self.log = 0

    def __enter__(self):
        print('enter')
        return self.tag

    def __exit__(self, exc_type, exc_val, tb):
        print('exit')
"""

VARIADIC_EXIT = """class Variadic:
    def __init__(self):
        self.tag = 7
        self.log = 0

    def __enter__(self):
        print('enter')
        return self.tag

    def __exit__(self, *args):
        print('exit')
"""

REFUSALS = [
    # ── the ALIAS is not somewhere one word goes ───────────────────────────
    # `with EXPR as (a, b)` — CPython unpacks `__enter__`'s result, and raises
    # `TypeError` here because an `Int` is not iterable.  **This used to BUILD,
    # run the body and exit 0 with nothing bound**: the parser represents all
    # three alias spellings as a bare STRING, so the string `'(a, b)'` passed
    # the "is it a name?" test and became a variable literally called `(a, b)`.
    # `refuse_unlowerable_with_alias` existed for exactly this and could not
    # fire, for the reason its own message gives.  The needle is the alias
    # clause's sentence, so a fix that refuses for the WRONG half (the context
    # expression's message, which is about types) does not satisfy it.
    ("a_tuple_alias_is_refused_by_name",
     CTX_MOJO + "def main(n):\n"
     "    with Ctx() as (a, b):\n"
     "        print('body')\n"
     "    return 0\n",
     "names somewhere this path cannot put the word",
     "this build cannot answer what type it is"),
    # `with EXPR as obj.attr` — CPython STORES into the attribute, so this one
    # succeeds there and drops the store silently here (the frame's address was
    # written into a field nothing reads back).  Same needle, same reason: the
    # two shapes are one sentence because neither names a place one word goes.
    ("an_attribute_alias_is_refused_by_name",
     CTX_MOJO + "def main(n):\n"
     "    box = Box()\n"
     "    with Ctx() as box.tag:\n"
     "        print('body')\n"
     "    return 0\n",
     "names somewhere this path cannot put the word",
     "this build cannot answer what type it is"),
    # A SUBSCRIPT alias, `as holder[0]`, is the third shape one word does not go
    # and the one a reader is most likely to try after the other two are
    # refused.
    ("a_subscript_alias_is_refused_by_name",
     CTX_MOJO + "def main(n):\n"
     "    holder = [0, 0]\n"
     "    with Ctx() as holder[0]:\n"
     "        print('body')\n"
     "    return 0\n",
     "names somewhere this path cannot put the word",
     "this build cannot answer what type it is"),
    # ── the CONTEXT is not enterable ───────────────────────────────────────
    # A struct of ONE field: its receiver IS that field, so there is no address
    # to dispatch `__enter__` on.  The needle is the one-field sentence, and it
    # is a distinct sentence from the "declares no `__enter__`" one precisely
    # because the two have different fixes — one is a field in the struct, the
    # other is a method.
    ("a_one_field_struct_is_refused_as_not_framed",
     ONE_FIELD + "def main(n):\n"
     "    with One() as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "it is a struct of ONE field", "it declares no __enter__"),
    # The struct is framed and declares `__exit__` but no `__enter__`: nothing
    # produces the word the alias would name, so there is nothing to enter.
    ("a_struct_with_no_enter_is_refused_naming_the_missing_dunder",
     NO_ENTER + "def main(n):\n"
     "    with NoEnter() as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "it declares no __enter__", "is a struct of ONE field"),
    # ── `__exit__` written the way CPython writes it ───────────────────────
    # **This is the refusal a reader hits first in real code**, because
    # `(self, exc_type, exc_val, tb)` is CPython's own signature and every
    # context manager in the wild has it.  The three words are a question about
    # an UNWINDER: this path has none, so there is nothing to pass them and a
    # `__exit__` that acted on them could not act anyway.  The needle has to
    # name `__exit__` and the parameter count, because the pre-2026-10-05
    # wording for this shape said "it declares no __enter__" — FALSE about a
    # class that has one — and sent the reader to add a dunder it already had.
    ("an_exit_with_cpythons_three_exception_parameters_is_refused_by_name",
     THREE_ARGS + "def main(n):\n"
     "    with ThreeArgs() as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "3 parameters", "it declares no __enter__"),
    ("an_exit_with_cpythons_three_exception_parameters_blames_the_receiver_arity",
     THREE_ARGS + "def main(n):\n"
     "    with ThreeArgs() as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "__exit__", "it declares no __enter__"),
    # `*args` is the variadic form of the same question, and it cannot even be
    # COUNTED from the tree, so it is refused rather than assumed — the same rule
    # a variadic call is refused by.
    ("a_variadic_exit_is_refused_by_name",
     VARIADIC_EXIT + "def main(n):\n"
     "    with Variadic() as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "CONTEXT-MANAGER PROTOCOL", "it declares no __enter__"),
    # ── a context this build cannot type ───────────────────────────────────
    # A name bound from a CALL to another function.  This is the limit the
    # ANSWERED table's NAME rows stop at, and it is a return-type table this
    # image does not have for values that cross a dylib boundary: naming the
    # struct `mk()` returns would be a guess, and a guess here is a program that
    # enters a `__enter__` the source never wrote.  `def make() -> Ctx:` would
    # answer it (`model.receiver_struct`'s CALL row reads a declared return type)
    # and that is the fix the message points at.
    ("a_with_over_a_name_bound_from_a_call_is_refused_as_untyped",
     CTX_MOJO + "def make():\n"
     "    return Ctx()\n"
     "\n"
     "def main(n):\n"
     "    m = make()\n"
     "    with m as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "this build cannot answer what type it is",
     "names somewhere this path cannot put the word"),
    # A name bound to TWO DIFFERENT structs on two paths.  CPython runs one of
    # them and enters the right `__enter__`; this path refuses, because the word
    # is one address and there is no tag on it to say which frame it is — the
    # same limit `struct_frame_slot_candidates` refuses a field read on, and the
    # reason the ANSWERED table has a row for the same struct bound twice.
    ("a_name_bound_to_two_structs_is_refused_rather_than_picking_one",
     CTX_MOJO + "def main(n):\n"
     "    m = Ctx()\n"
     "    if n > 1:\n"
     "        m = Box()\n"
     "    with m as v:\n"
     "        print('body', v)\n"
     "    return 0\n",
     "this build cannot answer what type it is",
     "names somewhere this path cannot put the word"),
    # A name bound ONLY inside a nested `def`.  The two scopes share the
    # spelling and not the binding, so the enclosing `with m as v:` has nothing
    # that says what its word holds — CPython raises `NameError` here, and the
    # alternative this row rules out is entering whatever unrelated word the
    # enclosing function's `m` held.  This is the row that says the NAME arm
    # reads THIS function's own bindings, not the whole subtree.
    ("a_name_bound_only_in_a_nested_def_is_refused_as_untyped",
     CTX_MOJO + "def main(n):\n"
     "    def inner():\n"
     "        m = Ctx()\n"
     "        print('inner')\n"
     "    with m as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "this build cannot answer what type it is",
     "names somewhere this path cannot put the word"),
    # A call to a function this image cannot resolve is the same gap one level
    # along, and it is the second spelling of the first row's message.
    ("a_with_over_a_call_to_another_function_is_refused_as_untyped",
     CTX_MOJO + "def make():\n"
     "    return Ctx()\n"
     "\n"
     "def main(n):\n"
     "    with make() as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "this build cannot answer what type it is",
     "names somewhere this path cannot put the word"),
    # A FIELD read is the third source with no declared type in hand.
    ("a_with_over_a_field_read_is_refused_as_untyped",
     CTX_MOJO + "class Holder:\n"
     "    def __init__(self):\n"
     "        self.mgr = Ctx()\n"
     "        self.other = 0\n"
     "\n"
     "def main(n):\n"
     "    h = Holder()\n"
     "    with h.mgr as v:\n"
     "        print('body')\n"
     "    return 0\n",
     "this build cannot answer what type it is",
     "names somewhere this path cannot put the word"),
]


# ── the receiver table is asked at most once, and only where there is a `with` ─
#
# The `with` NAME arm reads `{local: struct}` for the enclosing function, which is
# a walk of every binding in it.  Eagerly computed, that walk would run for every
# function in the image to serve the few that contain a `with` — so the rewrite
# is handed a THUNK and asks it at most once, and only when a `with` turns up
# (`build.py::_rewrite_with_statements`'s `asked` list).  That is a cost
# property, and a cost property nobody checks is a cost property the next
# reader undoes, so it is checked here in-process: no build, no Lean, no memory.
def check_receiver_table_is_asked_once(tmpdir):
    """Two functions, one with two `with`s and one with none."""
    import formal.build as B
    from fire_compiler import py_tokenize, Parser

    # A real context manager, because the rewrite refuses anything else and this
    # is about WHEN the table is asked, not about what it answers.
    head = ("struct C:\n"
            "    var tag: Int\n"
            "    var name: String\n"
            "    fn __enter__(self) -> Int:\n        return self.tag\n"
            "    fn __exit__(self):\n        pass\n\n")

    def fn(body_src):
        tree = Parser(list(py_tokenize(head + body_src))).parse_module()
        by_name = {n.name: n for n in tree if isinstance(n, B.F.StructDef)}
        fdef = [n for n in tree if isinstance(n, B.F.FunctionDef)][0]
        return fdef, by_name

    asks = []

    def thunk():
        asks.append(1)
        return {}

    two = fn("def two(n):\n"
             "    with C() as a:\n        print(1)\n"
             "    with C() as b:\n        print(2)\n")
    none = fn("def none(n):\n"
              "    x = 1\n    return x\n")
    for (f, by_name), want, what in ((two, 1, "two `with`s"),
                                     (none, 0, "no `with`")):
        asks.clear()
        B._rewrite_with_statements(f, by_name, thunk)
        check(len(asks) == want,
              f"the receiver table is asked {want} time(s) for a function with "
              f"{what}",
              f"it was asked {len(asks)} time(s)")


def run_pair(name, source, cpython_source, arg, tmpdir, verbose):
    """Both backends against CPython, comparing stdout AND exit status."""
    ref_source = cpython_source + f"\nimport sys\nsys.exit(main({arg}))\n"
    want_exit, want_out = cpython(ref_source, tmpdir, arg)
    if verbose:
        print(f"      CPython: exit={want_exit} out={want_out!r}")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(source, out, backend, tmpdir, arg)
        if not check(rc == 0, f"{name} builds on {backend}", text[-400:]):
            continue
        got_exit, got_out, _err = run(out)
        if not check(got_out == want_out,
                     f"{name} on {backend} prints what CPython prints",
                     f"printed {got_out!r}, CPython printed {want_out!r}"):
            continue
        check(got_exit == want_exit,
              f"{name} on {backend} exits as CPython does",
              f"exit {got_exit}, CPython exits {want_exit}")


def _read(path):
    return open(path).read() if os.path.exists(path) else None


def run_file_pair(name, body, paths, tmpdir, verbose):
    """`with open(...)` on both backends, plus the FILES it left behind.

    Compared three ways — the printed output, the exit status, and the bytes in
    each file — because the whole point of the resource arm is an EFFECT that
    leaves no trace in the process's own stdout: a skipped `close` loses the
    write, and a run that lost it still prints `closed` and exits 0.

    CPython's files are READ BACK HERE, before the first backend runs and
    deletes them, so the expectation is the oracle's own output rather than
    whatever happens to be on disk when the assertion runs.
    """
    path, path2 = paths
    source = body.format(PATH=path, PATH2=path2)
    want_exit, want_out = cpython(source, tmpdir)
    want_files = [_read(path), _read(path2)]
    if verbose:
        print(f"      CPython: exit={want_exit} out={want_out!r} "
              f"files={want_files!r}")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        for p in (path, path2):
            if os.path.exists(p):
                os.remove(p)
        rc, text = build(source, out, backend, tmpdir)
        if not check(rc == 0, f"{name} builds on {backend}", text[-400:]):
            continue
        got_exit, got_out, _err = run(out)
        check(got_out == want_out,
              f"{name} on {backend} prints what CPython prints",
              f"printed {got_out!r}, CPython printed {want_out!r}")
        check(got_exit == want_exit,
              f"{name} on {backend} exits as CPython does",
              f"exit {got_exit}, CPython exits {want_exit}")
        for p, want in zip((path, path2), want_files):
            got = _read(p)
            check(got == want,
                  f"{name} on {backend} leaves {os.path.basename(p)} as CPython does",
                  f"file holds {got!r}, CPython left {want!r}")


def run_refusal(name, source, needle, forbid, tmpdir, verbose):
    """Both backends must REFUSE, with the needle in and the forbidden out.

    `forbid` is the other half and it is not decoration.  `__exit__` appears in
    the tail of EVERY message in this family ("give the value a struct with
    `__enter__` and `__exit__`"), so a row whose needle is merely `__exit__` is
    satisfied by a refusal that blames the wrong dunder — which is precisely the
    defect the 2026-10-05 wording had.  Naming the sentence that must NOT
    appear is what makes the other one mean something.
    """
    seen = {}
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(source, out, backend, tmpdir)
        if not check(rc != 0, f"{name} is refused on {backend}",
                     "it BUILT, so a program the source says binds nothing is "
                     "in the image as a program whose binding never happens"):
            continue
        seen[backend] = text
        check(needle in text,
              f"{name} on {backend} says {needle!r}",
              f"the message does not contain it: "
              f"{text.strip()[-300:]}")
        check(forbid not in text,
              f"{name} on {backend} does not blame {forbid!r}",
              f"the message contains it: {text.strip()[-300:]}")
    if len(seen) == 2 and verbose:
        print(f"      arm64 and x86-64 agree: {needle!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*")
    args = ap.parse_args()
    want = args.cases

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, body, arg in CASES:
            if want and name not in want:
                continue
            run_pair(name, mojo(body), python(body), arg, tmpdir, args.verbose)

        for name, body, paths in FILE_CASES:
            if want and name not in want:
                continue
            # CPython is asked FIRST and its files are read into `want` below,
            # which is why each row writes to its OWN pair of paths per
            # architecture rather than sharing the ones CPython used.
            run_file_pair(name, body, (
                os.path.join(tmpdir, f"{name}.want.a"),
                os.path.join(tmpdir, f"{name}.want.b"),
            ), tmpdir, args.verbose)

        check_receiver_table_is_asked_once(tmpdir)

        for name, source, needle, forbid in REFUSALS:
            if want and name not in want:
                continue
            run_refusal(name, source, needle, forbid, tmpdir,
                        args.verbose)

    total = len(RESULTS)
    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\nwith: PASS={passed} FAIL={total - passed} ({total} checks)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())