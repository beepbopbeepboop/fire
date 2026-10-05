#!/usr/bin/env python3
"""`Optional[T]` on the formal backends: the NICHE, measured against CPython.

**Why this file exists.** A formal value is one 64-bit word, and `None` was the
word 0 — which is also the integer 0. So `Some(0)` and `None` were the same
word, and the two answers disagreed with no diagnostic anywhere:

    var z: Optional[Int] = 0
    if z is None: print("WRONG")

arm64 and x86-64 both built that, ran it, and printed `WRONG`
(`bugs/FORMAL_optional_needs_a_niche.md`). The null was not merely
unavailable; it was ambiguous, and an ambiguous null is the one outcome this
backend's own rule forbids.

**The representation under test** is `formal/model.py`'s: an `Optional[T]` value
is the payload word, and `None` is a word `T` cannot produce — word 0 for every
reference-shaped payload, 2 for a `Bool`, `1 << w` for a narrow integer or a
`Float32`. These cases check the WHOLE of that: the `None` word, the four
comparison spellings, the three unwrap spellings, the payload read, truthiness,
and the places a value has to cross a boundary to be usable at all (a field, a
fresh instance's default, a parameter, a return).

**Two kinds of case, and why.** Most are ORACLE cases: the same text is
translated into CPython and both engines must print byte-identical output. The
translation (`cpython_source`) does not presuppose the representation — an
`Optional` becomes a Python object that knows whether it is empty and says so
through `is_none()` — so a case cannot be pinned to a value that was wrong in
the first place, which is the failure `test_formal_value_model.py` exists to
prevent and which this area had in the worst way.

Two families cannot have an oracle and are pinned instead, each with the reason
in its own row:

  * **TRUTHINESS.** Mojo's `Optional.__bool__` is `not
    self._value.isa[_NoneType]()` — "does this Optional HAVE a value"
    (`std/collections/optional.mojo:449`). CPython's `if opt:` asks whether the
    PAYLOAD is truthy, so for `Optional[Bool](False)` Mojo says true and Python
    says false. There is no oracle for a deliberate disagreement, so these rows
    pin the Mojo answer and say which is which.
  * **THE REFUSAL.** An `Optional` whose payload has no niche — `Int` is the
    corpus's own case — must be REFUSED naming the payload type rather than
    answered as `== 0`. Those are `REFUSALS`, and the refusal-is-a-failure rule
    is theirs: a build that succeeds is the failure.

    python3 test_formal_optional.py [-v] [case ...]
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60

# ── the CPython translation ────────────────────────────────────────────────
#
# Deliberately NOT a representation. `Opt` carries `_empty` and asks about it
# through `is_none()`; the translation of `x is None` is `x.is_none()` and the
# translation of `x = None` / `var x: Optional[T] = None` is `Opt()`. So the
# oracle answers "does this Optional have a value" from ITS OWN state, and a
# case cannot pass by having the wrong word in the same place twice.
#
# `Opt(Opt(x))` is `Opt(x)`, and that is the IMPLICIT CONVERSION this translation
# has to reproduce rather than a convenience: `describe(maybe(0))` wraps a call
# that already returns an `Optional`, and a shim that nested would answer
# `or_else` with a second `Opt` and print an object repr — a translation bug
# that reads as a disagreement about the language. Mojo's own conversion is
# `Optional[T](v: T)`, so it never nests either.
#
# The rules, in order, and each is one regex over the same text:
#   1. `Optional[T]` -> `Opt`, everywhere, including annotations;
#   2. a declaration `var N: Opt = V` -> `N = Opt(V)` (Mojo wraps implicitly
#      and Python does not);
#   3. a `var N: Opt` field with NO initializer -> `N = Opt()` (an absent
#      `Optional` is empty, and the field's default word is the question the
#      `optional_field_none_word` row exists for);
#   4. `return V` inside a function declared `-> Opt` -> `return Opt(V)`, and
#      `return None` there -> `return Opt()`;
#   5. `N is None` / `N == None` -> `N.is_none()`, `is not` / `!=` -> `not
#      N.is_none()`;
#   6. `.or(` -> `.or_(`, because `or` is a Python keyword and the Mojo method
#      is spelled with it;
#   7. the `var` keyword and the annotations, dropped.
_SHIM = (
    "import sys\n"
    "def printf(fmt, *a):\n"
    "    sys.stdout.write(fmt % a)\n"
    "class Opt:\n"
    "    __slots__ = ('_empty', '_v')\n"
    "    def __init__(self, v=None):\n"
    "        if isinstance(v, Opt):\n"
    "            v = None if v._empty else v._v\n"
    "        self._empty = v is None\n"
    "        self._v = v\n"
    "    def is_none(self):\n"
    "        return self._empty\n"
    "    def or_else(self, d):\n"
    "        return d if self._empty else self._v\n"
    "    or_ = or_else\n"
    "    value_or = or_else\n"
    "    def unsafe_value(self):\n"
    "        return self._v\n"
)
_VAR = re.compile(r"^(\s*)var (\w)", re.M)
_OPTIONAL = re.compile(r"Optional\[\w+\]")
_DEF = re.compile(r"^(\s*)def (\w+)\(([^)]*)\)(\s*->\s*[\w\[\]]+)?\s*:",
                  re.M)
_STRUCT = re.compile(r"^struct\s+(\w+)\s*(\([^)]*\))?\s*:", re.M)
_OPT_DECL_INIT = re.compile(r"^(\s*)var (\w+):\s*Optional\[\w+\]\s*=\s*(.+)$",
                            re.M)
_OPT_DECL_BARE = re.compile(r"^(\s*)var (\w+):\s*Optional\[\w+\]\s*$", re.M)
_ANN_FIELD = re.compile(r"^(\s+)(\w+):\s*[\w\[\]]+\s*$", re.M)
_RETURN = re.compile(r"^(\s*)return (.+)$", re.M)
_IS_NONE = re.compile(r"\b(\w+)\s+(is not|is|==|!=)\s+None\b")
_MUT_SELF = re.compile(r"\b(?:mut|out|inout|borrowed|read|var|ref) self\b")
# A fixed-width scalar's constructor is the IDENTITY on this target (a 32-bit
# value is a 32-bit value either way) and CPython has no such type, so the
# translation drops the constructor and keeps the value: `Int32(7)` -> `7`.
# Two alternatives so the closing paren can be left in place.
_SCALAR_CTOR = re.compile(
    r"\b(?:Int8|Int16|Int32|UInt8|UInt16|UInt32|Bool|Float32)\((\w+)\)"
    r"|(\b(?:Int8|Int16|Int32|UInt8|UInt16|UInt32|Bool|Float32)\()")
# What counts as a literal for `_wrap_returns`. A NAME is not one: `return
# FLAG` from `-> Optional[Bool]` is a payload and `return opt` is a whole
# Optional, and wrapping either would build `Opt(Opt(...))` — a second question
# the translation would be answering rather than the one the case asks.
_RETURN_LITERAL = re.compile(
    r"""(?:"[^"]*"|'[^']*'|-?\d+|True|False|[A-Za-z_]\w*\([^()]*\))""")


def _split_top(text: str, sep: str = ",") -> list:
    """`text` split on `sep` at bracket depth zero."""
    depth, cur, out = 0, "", []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _optional_param_index(params: str) -> dict:
    """`{index: True}` for the CALL-SITE index of each `Optional` parameter.

    The index is the CALL-SITE one and not the signature's, which means the
    RECEIVER has to come off the front first: `def put(mut self, s:
    Optional[Bool])` is one call argument, not two, and numbering the
    signature's positions would wrap the second argument of every call to a
    method whose first parameter is a receiver. That is the whole of what this
    function has to get right and the reason it is three lines rather than one.
    """
    names = _split_top(params)
    if names and names[0].split(":")[0].strip().split()[-1] in (
            "self", "cls", "Self", "this"):
        names = names[1:]
    out = {}
    for i, p in enumerate(names):
        if ":" in p and _OPTIONAL.fullmatch(p.split(":", 1)[1].strip()):
            out[i] = True
    return out


def _call_args(text: str, method: str) -> list:
    """Every `method(...)` / `.method(...)` argument list in `text`, as spans.

    The dot is OPTIONAL because a Mojo function taking an `Optional` parameter
    is as often a free function as a method — `def describe(s: Optional[String])`
    called as `describe(maybe(0))` — and requiring the dot would leave the free
    half unwrapped, which is a CPython `AttributeError` at run time rather than a
    translation bug you would read. The DEFINITION is skipped by looking at the
    four characters before the name, because `def put(mut self, s: ...)` is a
    match for `put(` too and wrapping its declared default would be nonsense.
    """
    spans = []
    for m in re.finditer(r"\.?\b" + re.escape(method) + r"\(", text):
        if text[max(0, m.start() - 4):m.start()] == "def ":
            continue
        open_at = m.end() - 1
        depth, i = 0, open_at
        while i < len(text):
            if text[i] in "([{":
                depth += 1
            elif text[i] in ")]}":
                depth -= 1
                if depth == 0:
                    spans.append((open_at + 1, i))
                    break
            i += 1
    return spans


def cpython_source(source: str) -> str:
    """The CPython text for a Mojo `Optional` case. See the module docstring."""
    # 1. Which methods take an `Optional` parameter, and at which position. Read
    #    off the SIGNATURES and applied by name at the call sites; a name
    #    overloaded across two signatures with different `Optional` parameters
    #    would need the receiver's type, and no case in this file does that, so
    #    the limitation is stated rather than pretended away.
    wraps = {}
    for m in _DEF.finditer(source):
        for i in _optional_param_index(m.group(3)):
            wraps.setdefault(m.group(2), set()).add(i)

    # 2. `return None` -> `return Opt()`, `return <literal>` -> `return Opt(…)`,
    #    inside a `-> Optional[…]` function only.
    out, pos = [], 0
    for m in re.finditer(r"^def (\w+)\(([^)]*)\)\s*->\s*Optional\[\w+\]\s*:"
                         r"\s*$", source, re.M):
        # The body runs to the next line that is not indented under this `def`.
        # The offset is ACCUMULATED rather than taken from the line's length,
        # because `len(line)` is the length of that one line and not its
        # distance from the `def` — a version that used it stopped the body at
        # the first line and silently wrapped nothing, which reads as "no case
        # returns a value" rather than as an off-by-N in a test harness.
        end, offset = len(source), 0
        rest = source[m.end():]
        for line in rest.splitlines(keepends=True):
            offset += len(line)
            if line.strip() and not line[0].isspace():
                end = m.end() + offset - len(line)
                break

        def wrap(rm):
            value = rm.group(2).strip()
            if value == "None":
                return f"{rm.group(1)}return Opt()"
            if _RETURN_LITERAL.fullmatch(value):
                return f"{rm.group(1)}return Opt({value})"
            return rm.group(0)

        out.append(source[pos:m.end()])
        out.append(_RETURN.sub(wrap, source[m.end():end]))
        pos = end
    out.append(source[pos:])
    text = "".join(out)
    # 3. The implicit conversion at an `Optional` parameter's call site.
    for method, indices in wraps.items():
        for open_at, close_at in reversed(_call_args(text, method)):
            args = _split_top(text[open_at:close_at])
            for i in indices:
                if i < len(args):
                    args[i] = f"Opt({args[i]})"
            text = text[:open_at] + ", ".join(args) + text[close_at:]
    # An UNANNOTATED binding of an `Optional`-returning call needs NO rule:
    # `var yes = pick(1)` is an `Optional[Bool]` in Mojo because of the RETURN
    # TYPE, and in CPython it is whatever `pick` returned — which is already an
    # `Opt`, because rule 2 wrapped that function's `return`s. A `return` of a
    # NAME from an `Optional`-returning function is left unwrapped for the same
    # reason, and `Opt`'s idempotent constructor makes the two agree.
    #
    # 4. The structural rewrites, in the order each depends on the one before.
    #    The two `Optional` DECLARATION rules come FIRST because they are the
    #    only ones that need to read the type argument, and `_OPTIONAL.sub`
    #    below erases it — which is what made every `var x: Optional[T] = V`
    #    reach CPython as an annotated assignment carrying the bare value.
    text = _OPT_DECL_INIT.sub(
        lambda m: f"{m.group(1)}{m.group(2)} = Opt({m.group(3)})", text)
    text = _OPT_DECL_BARE.sub(
        lambda m: f"{m.group(1)}{m.group(2)} = Opt()", text)
    text = _OPTIONAL.sub("Opt", text)
    text = _SCALAR_CTOR.sub(lambda m: m.group(1) or m.group(3), text)
    text = _STRUCT.sub(lambda m: f"class {m.group(1)}:", text)
    text = _MUT_SELF.sub("self", text)

    def def_line(m):
        params = ", ".join(p.split(":", 1)[0].strip()
                           for p in _split_top(m.group(3)))
        return f"{m.group(1)}def {m.group(2)}({params}):"

    text = _DEF.sub(def_line, text)
    text = _VAR.sub(r"\1\2", text)
    text = _ANN_FIELD.sub(lambda m: f"{m.group(1)}{m.group(2)} = 0", text)
    text = _IS_NONE.sub(
        lambda m: (f"(not {m.group(1)}.is_none())"
                   if m.group(2) in ("is not", "!=")
                   else f"{m.group(1)}.is_none()"), text)
    text = text.replace(".or(", ".or_(")
    return _SHIM + text + "\nsys.exit(main(1))\n"


# ── the cases ──────────────────────────────────────────────────────────────
#
# (name, source, expected stdout)
CASES = [
    # THE FOUR COMPARISON SPELLINGS, on a payload whose `None` word is NOT 0.
    # `Optional[Bool]`'s is 2, so every one of these compares against 2 — and
    # `Some(False)`, whose payload word is 0, is the case that says so. Under
    # the old fold all five of these answers were computed against 0 and
    # `present_false` came out "none".
    ("bool_four_comparisons",
     "def main(n):\n"
     "    var absent: Optional[Bool] = None\n"
     "    var present_false: Optional[Bool] = False\n"
     "    var present_true: Optional[Bool] = True\n"
     "    printf(\"%d%d%d%d\",\n"
     "           1 if absent is None else 0,\n"
     "           1 if absent is not None else 0,\n"
     "           1 if present_false == None else 0,\n"
     "           1 if present_true != None else 0)\n"
     "    return 0\n",
     "1001"),
    ("bool_or_else_both_arms",
     "def main(n):\n"
     "    var absent: Optional[Bool] = None\n"
     "    var present_false: Optional[Bool] = False\n"
     "    printf(\"%d%d%d%d\",\n"
     "           1 if absent.or_else(True) else 0,\n"
     "           1 if present_false.or_else(True) else 0,\n"
     "           1 if absent.value_or(False) else 0,\n"
     "           1 if present_false.value_or(True) else 0)\n"
     "    return 0\n",
     "1000"),
    # `or` is the third spelling of the same question. `.or_(` on the Python
    # side because `or` is a keyword there.
    ("bool_or_default",
     "def main(n):\n"
     "    var absent: Optional[Bool] = None\n"
     "    var present: Optional[Bool] = True\n"
     "    printf(\"%d%d\", 1 if absent.or(True) else 0,\n"
     "           1 if present.or(False) else 0)\n"
     "    return 0\n",
     "11"),
    # `unsafe_value` reads the word, so it is the identity on the value word —
    # and the identity is only observable when the payload word and the `None`
    # word differ, which is why this is a `Bool` case.
    ("bool_unsafe_value_is_the_payload_word",
     "def main(n):\n"
     "    var present_false: Optional[Bool] = False\n"
     "    var present_true: Optional[Bool] = True\n"
     "    printf(\"%d%d\", 1 if present_false.unsafe_value() else 0,\n"
     "           1 if present_true.unsafe_value() else 0)\n"
     "    return 0\n",
     "01"),
    # A `String` payload: its `None` word IS 0, which is the row that makes the
    # reference convention (`x is None` compares a reference against 0) the
    # SAME answer as the Optional one. The empty string is the case that says
    # the payload and the `None` word are different: it is a non-NULL pointer.
    ("string_four_comparisons_and_unwrap",
     "def main(n):\n"
     "    var absent: Optional[String] = None\n"
     "    var empty: Optional[String] = \"\"\n"
     "    var text: Optional[String] = \"hi\"\n"
     "    printf(\"%d%d%d%s|%s|%s\",\n"
     "           1 if absent is None else 0,\n"
     "           1 if empty is None else 0,\n"
     "           1 if text == None else 0,\n"
     "           absent.or_else(\"no\"), empty.or_else(\"no\"),\n"
     "           text.or_else(\"no\"))\n"
     "    return 0\n",
     "100no||hi"),
    # A NICHE THAT IS NOT A SMALL CONSTANT. `Optional[Int32]`'s empty word is
    # `1 << 32`, which is past arm64 `cmp`'s 12-bit immediate and past x86-64
    # `cmp`'s imm32 field — so both emitters materialise it in a register and
    # compare register-to-register, and a truncating compare would be a
    # different word from the one the value carries. `Int32` on the Python side
    # is `int`, and CPython has no such type, so the case is spelled in terms
    # of values both engines agree about.
    ("int32_niche_is_a_register_wide_word",
     "def main(n):\n"
     "    var absent: Optional[Int32] = None\n"
     "    var zero: Optional[Int32] = Int32(0)\n"
     "    var seven: Optional[Int32] = Int32(7)\n"
     "    printf(\"%d%d%d%d\",\n"
     "           1 if absent is None else 0,\n"
     "           1 if zero is None else 0,\n"
     "           1 if seven == None else 0,\n"
     "           1 if absent.or_else(Int32(9)) == 9 else 0)\n"
     "    return 0\n",
     "1001"),
    # AN OPTIONAL FIELD, and the two things a field has that a local does not:
    # its value crosses a frame slot, and a field with no initializer is
    # EMPTY rather than zero. The second is the row `optional_field_none_word`
    # exists for — a fresh instance's `Optional[Bool]` slot must hold 2, or
    # `h.flag is None` (a compare against 2) reports a set flag on an instance
    # nobody has set.
    ("bool_field_fresh_is_empty",
     "struct Holder:\n"
     "    var flag: Optional[Bool]\n"
     "    var pad: Int\n"
     "\n"
     "def main(n):\n"
     "    var h = Holder()\n"
     "    printf(\"%d%d\", 1 if h.flag is None else 0,\n"
     "           1 if h.flag.or_else(True) else 0)\n"
     "    return 0\n",
     "11"),
    # Assigned BOTH WAYS, through a method rather than through `h.flag = …`
    # directly — which is how the stdlib writes it (`Slice.__init__` stores
    # `self.step`), and which is also the only spelling the CPython translation
    # can follow without a second compiler: an assignment to an `Optional` FIELD
    # would need that field's declared type at every store site, while the
    # method form puts the conversion at a PARAMETER, where the signature
    # already says what it is. The store inside the method is then the same
    # store in both texts.
    ("bool_field_assigned_both_ways",
     "struct Holder:\n"
     "    var flag: Optional[Bool]\n"
     "    var pad: Int\n"
     "    def put(mut self, s: Optional[Bool]):\n"
     "        self.flag = s\n"
     "\n"
     "def main(n):\n"
     "    var h = Holder()\n"
     "    h.put(False)\n"
     "    var first = 1 if h.flag is None else 0\n"
     "    h.put(None)\n"
     "    var second = 1 if h.flag is None else 0\n"
     "    printf(\"%d%d\", first, second)\n"
     "    return 0\n",
     "01"),
    # A field READ INSIDE A METHOD, which is the `self.<field>` spelling the
    # stdlib's own `Optional` fields use (`builtin_slice.mojo`'s `self.step`).
    # The build pass's FIRST call site exists for exactly this shape: it runs
    # before `_rewrite_self_fields` collapses a one-field struct's receiver.
    ("bool_field_read_through_the_receiver",
     "struct Holder:\n"
     "    var flag: Optional[Bool]\n"
     "    var pad: Int\n"
     "    def is_set(self) -> Int:\n"
     "        return 0 if self.flag is None else 1\n"
     "    def defaulted(self) -> Int:\n"
     "        return self.flag.or_else(True)\n"
     "    def put(mut self, s: Optional[Bool]):\n"
     "        self.flag = s\n"
     "\n"
     "def main(n):\n"
     "    var h = Holder()\n"
     "    var before = h.is_set()\n"
     "    h.put(True)\n"
     "    printf(\"%d%d%d\", before, h.is_set(),\n"
     "           1 if h.defaulted() else 0)\n"
     "    return 0\n",
     "011"),
    # AN OPTIONAL-RETURNING FUNCTION, both arms, and a caller that asks the
    # question the return value is there to answer. The returned-frame
    # convention is not involved: an `Optional[T]` is ONE word, so it crosses
    # the boundary in the return register like any other value.
    ("bool_returning_function_both_arms",
     "def pick(n: Int) -> Optional[Bool]:\n"
     "    if n > 0:\n"
     "        return True\n"
     "    return None\n"
     "\n"
     "def main(n):\n"
     "    var yes = pick(1)\n"
     "    var no = pick(0)\n"
     "    printf(\"%d%d%d%d\",\n"
     "           1 if yes is None else 0,\n"
     "           1 if no is None else 0,\n"
     "           1 if yes.or_else(False) else 0,\n"
     "           1 if no.or_else(True) else 0)\n"
     "    return 0\n",
     "0111"),
    ("string_returning_function_through_a_parameter",
     "def maybe(n: Int) -> Optional[String]:\n"
     "    if n == 0:\n"
     "        return None\n"
     "    return \"n\"\n"
     "\n"
     "def describe(s: Optional[String]) -> String:\n"
     "    return s.or_else(\"empty\")\n"
     "\n"
     "def main(n):\n"
     "    printf(\"%s/%s\", describe(maybe(0)), describe(maybe(1)))\n"
     "    return 0\n",
     "empty/n"),
    # AN OPTIONAL THROUGH A FRAME, both directions: read out of one struct's
    # field by a method, stored back through a mutator, and unwrapped at the far
    # end. A frame slot is where a one-word value has to survive a store and a
    # load without either of them touching the niche, so this is the case that
    # says the representation is a WORD and not a frame — and the returned
    # `Optional` is in the return register, because an `Optional[T]` is one word
    # and not a frame address.
    ("optional_through_a_frame_both_directions",
     "struct Box:\n"
     "    var inner: Optional[String]\n"
     "    var pad: Int\n"
     "    def take(self) -> Optional[String]:\n"
     "        return self.inner\n"
     "    def put(mut self, s: Optional[String]):\n"
     "        self.inner = s\n"
     "\n"
     "def main(n):\n"
     "    var b = Box()\n"
     "    var t: Optional[String] = b.take()\n"
     "    var first = t.or_else(\"one\")\n"
     "    b.put(\"two\")\n"
     "    var t2: Optional[String] = b.take()\n"
     "    var second = t2.or_else(\"one\")\n"
     "    b.put(None)\n"
     "    var t3: Optional[String] = b.take()\n"
     "    var third = t3.or_else(\"one\")\n"
     "    printf(\"%s%s%s\", first, second, third)\n"
     "    return 0\n",
     "onetwoone"),
]

# Cases whose Mojo answer is deliberately NOT CPython's, pinned with the
# reason. See the module docstring.
FIXED_CASES = [
    # `Optional.__bool__` asks whether the Optional HAS A VALUE
    # (`std/collections/optional.mojo:449`), so `Some(False)` is truthy and
    # `Some("")` is truthy. CPython's `if opt:` would say the opposite for
    # both, which is why these rows are pinned and not oracle rows: the
    # disagreement is the language's, and an oracle run against CPython would
    # be asserting the wrong one.
    ("bool_truthiness_is_has_a_value",
     "def main(n):\n"
     "    var absent: Optional[Bool] = None\n"
     "    var present_false: Optional[Bool] = False\n"
     "    var present_true: Optional[Bool] = True\n"
     "    printf(\"%d%d%d\", 1 if absent else 0, 1 if present_false else 0,\n"
     "           1 if present_true else 0)\n"
     "    return 0\n",
     "011"),
    ("string_truthiness_is_has_a_value",
     "def main(n):\n"
     "    var absent: Optional[String] = None\n"
     "    var empty: Optional[String] = \"\"\n"
     "    printf(\"%d%d\", 1 if absent else 0, 1 if empty else 0)\n"
     "    return 0\n",
     "01"),
    # The short-circuit forms, because `a and not b` puts an `Optional` in the
    # operand of a chain whose lowering recurses through `_emit_truthy_word` —
    # and `not` is where the niche test has to survive a negation.
    ("bool_truthiness_through_and_or_not",
     "def main(n):\n"
     "    var absent: Optional[Bool] = None\n"
     "    var present: Optional[Bool] = True\n"
     "    var a = 0\n"
     "    var b = 0\n"
     "    if present and not absent:\n"
     "        a = 1\n"
     "    if absent or present:\n"
     "        b = 1\n"
     "    printf(\"%d%d\", a, b)\n"
     "    return 0\n",
     "11"),
]

# (name, source, a substring the REFUSAL must name)
#
# Each of these is a program that USED to build and compute the wrong answer,
# so "it builds" is the failure here rather than the outcome.
REFUSALS = [
    ("int_payload_has_no_niche",
     "def main(n):\n"
     "    var z: Optional[Int] = 0\n"
     "    if z is None:\n"
     "        printf(\"WRONG\\n\")\n"
     "    return 0\n",
     "is an `Optional[Int]`"),
    ("int_payload_unwrap_has_no_niche",
     "def main(n):\n"
     "    var z: Optional[Int] = None\n"
     "    printf(\"%d\\n\", z.or_else(1))\n"
     "    return 0\n",
     "is an `Optional[Int]`"),
    ("float64_payload_has_no_niche",
     "def main(n):\n"
     "    var z: Optional[Float64] = None\n"
     "    if z is None:\n"
     "        printf(\"empty\\n\")\n"
     "    return 0\n",
     "is an `Optional[Float64]`"),
    # An UNSTATED payload type is the same refusal, and it is the case that says
    # WHERE the obligation is: `optional_none_word` returns None for a payload
    # the source does not spell, because knowing the payload's domain is the
    # source's job. So the UNWRAP refuses — it needs the receiver's `Optional`
    # type and there is none — while a bare `x is None` on the same unannotated
    # name still folds to `== 0`. That residue is a pre-existing fold
    # (`bugs/FORMAL_optional_needs_a_niche.md` records it) and it is NOT what
    # this case pins: what it pins is that the construct which DEPENDS on the
    # representation refuses rather than answering, so an unannotated Optional
    # can never be unwrapped on a guess.
    ("unstated_payload_cannot_be_unwrapped",
     "def main(n):\n"
     "    var z = None\n"
     "    printf(\"%d\\n\", z.or_else(1))\n"
     "    return 0\n",
     "PAYLOAD'S TYPE cannot produce"),
    # The refusal's ADVICE is a promise to the reader, and a promise nobody
    # checks is how a refusal sends readers after a non-bug: the message says
    # "annotate the receiver `Optional[T]`", so a case that annotates it and
    # then builds is the only thing that keeps the sentence true. It is pinned
    # on the WORD the annotation has to be about, because that is the claim
    # being made — `Optional[Int]` is annotated and still refused, which is a
    # different message (`optional_no_niche_refusal`) and is the row above.
    ("a_non_optional_receiver_is_told_to_annotate",
     "struct S:\n"
     "    var step: Int\n"
     "    var pad: Int\n"
     "\n"
     "def main(n):\n"
     "    var s = S()\n"
     "    s.step = 1\n"
     "    printf(\"%d\\n\", s.step.or_else(1))\n"
     "    return 0\n",
     "Annotate the receiver `Optional[T]`"),
    # A payload that is a STRUCT OF ANOTHER MODULE is the third refusal reason
    # and the only one that is not about a type\'s width: the layout that would
    # prove a niche is in a library this build does not compile. It is spelled
    # here through `Slice`, a builtin this image does not declare, so the
    # message must name the payload and say the fields are not compiled here
    # rather than claim every word is a value of it.
    ("another_module_payload_is_not_measured",
     "def main(n):\n"
     "    var z: Optional[Slice] = None\n"
     "    if z is None:\n"
     "        printf(\"empty\\n\")\n"
     "    return 0\n",
     "is an `Optional[Slice]`"),
    # **`OptionalReg[T]` is a PAIR and this path's `Optional[T]` is a WORD**, so
    # reading it as this one is a wrong answer rather than a missing one. It was
    # in `model.OPTIONAL_TYPE_NAMES` on the strength of the SPELLING alone
    # ("a reader who annotates it must get the same answer"), which made
    # `x is None` compare against the one-word niche — `x == 2` for a `Bool`
    # payload, `x == 0` for a `String` — and both are about half the value:
    # `std/collections/optional.mojo`'s `_OptionalRegStorageFor[T]` is
    # `_NicheableOptionalRegStorage[T]` (a `StaticTuple[T, 1]`) or
    # `_DefaultOptionalRegStorage[T]` (a `!kgen.variant<T, i1>`). Which one
    # applies is a TRAIT CONFORMANCE (`conforms_to(T, UnsafeNicheable)`) this
    # build does not resolve, so the fact that decides the layout is one it has
    # no source for.
    #
    # Dropping the name from the table WITHOUT this refusal would be worse than
    # the bug: nothing would recognise the annotation, the substitution would not
    # fire, and `x is None` would fold to `== 0` — the `Some(0) == None`
    # ambiguity the whole niche representation exists to remove, back through a
    # different door. That is why the case is here and why it pins the WORD: the
    # refusal has to be reachable, and it has to be about the annotation rather
    # than about the arithmetic that happens to follow it.
    ("optional_reg_is_a_pair_and_is_refused",
     "def main(n):\n"
     "    var z: OptionalReg[Bool] = None\n"
     "    if z is None:\n"
     "        printf(\"empty\\n\")\n"
     "    return 0\n",
     "is the REGISTER-PASSABLE optional"),
    # The same refusal for the other two spellings a declaration can take, each
    # of which is a site `apply_optional_none_representation` cannot reach: a
    # FIELD (a field holding a pair is a frame whose layout this path cannot
    # describe — `struct_default_word`'s `("nested_frame", …)` row is the same
    # argument) and a PARAMETER (whose annotation only the callee has). Both
    # name the site, so a reader is sent to the declaration rather than to the
    # type.
    ("optional_reg_field_is_refused",
     "struct Holder:\n"
     "    var slot: OptionalReg[String]\n"
     "\n"
     "def main(n):\n"
     "    var h = Holder()\n"
     "    if h.slot is None:\n"
     "        printf(\"empty\\n\")\n"
     "    return 0\n",
     "declared type of field `Holder.slot`"),
    ("optional_reg_parameter_is_refused",
     "def take(z: OptionalReg[Int32]) -> Int:\n"
     "    return 1\n"
     "\n"
     "def main(n):\n"
     "    return take(0)\n",
     "declared type of parameter `z` of `take`"),
]


def build_formal(src, out, backend):
    proc = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         f"--backend={backend}", "-o", out, src],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    return proc.returncode, (proc.stdout + proc.stderr)


def run_cpython(source, tmpdir, verbose):
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(cpython_source(source))
    proc = subprocess.run([sys.executable, path], capture_output=True,
                          text=True, timeout=RUN_TIMEOUT)
    if verbose:
        print(f"      cpython: {proc.stdout!r} exit={proc.returncode}"
              + (f" stderr={proc.stderr.strip()[:300]}" if proc.stderr else ""))
    return proc.returncode, proc.stdout


def run_case(name, source, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    want_exit, want_out = run_cpython(source, tmpdir, verbose)
    if want_out != want_stdout:
        return False, (f"the case's own expectation ({want_stdout!r}) is not "
                       f"what CPython prints ({want_out!r}); the expectation is "
                       f"the wrong half, not the image")
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc != 0:
            return False, f"--backend={backend} refused: {text.strip()[-400:]}"
        proc = subprocess.run([exe], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT)
        if proc.stdout != want_out or proc.returncode != want_exit:
            return False, (
                f"--backend={backend} answered {proc.stdout!r} exit="
                f"{proc.returncode} where CPython answers {want_out!r} exit="
                f"{want_exit}"
                + (f" (stderr {proc.stderr.strip()[:200]})" if proc.stderr
                   else ""))
        if verbose:
            print(f"      {backend}: {proc.stdout!r} exit={proc.returncode}")
    return True, ""


def run_fixed_case(name, source, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc != 0:
            return False, f"--backend={backend} refused: {text.strip()[-400:]}"
        proc = subprocess.run([exe], capture_output=True, text=True,
                              timeout=RUN_TIMEOUT)
        if proc.stdout != want_stdout:
            return False, (f"--backend={backend} answered {proc.stdout!r} "
                           f"where this case pins {want_stdout!r}")
        if verbose:
            print(f"      {backend}: {proc.stdout!r}")
    return True, ""


def run_refusal(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        exe = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, exe, backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a program whose answer "
                           f"depends on which of two words is the empty one; "
                           f"the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not naming "
                           f"{needle!r}: {text.strip()[-400:]}")
    if verbose:
        print(f"      refused identically on both architectures, naming "
              f"{needle!r}")
    return True, ""


def check_table(tmpdir, verbose):
    """The table's two PROPERTIES, as failures rather than as a comment.

    Both are about the table rather than about any program's output, and both
    are the kind of thing that rots silently: a payload added to
    `SCALAR_TYPE_WIDTHS` with a width that is not a type, or a niche chosen for
    a domain that can produce it, is a wrong answer with a green suite.
    """
    sys.path.insert(0, HERE)
    from formal import model as M
    from formal import types as FT

    failures = []

    # (1) The niche is OUT OF THE PAYLOAD's DOMAIN, for every row that answers.
    #     The proof obligations are per domain and they are the whole argument
    #     the representation rests on, so they are checked rather than asserted
    #     in a comment. `Bool`'s domain is `{0, 1}`; a `w`-bit integer's is the
    #     `w`-bit two's-complement range; a `Float32`'s is its 32-bit PATTERNS,
    #     which is why its row is the one structural obligation and the rest are
    #     numeric.
    if 2 in (0, 1):
        failures.append("Bool: a Bool's domain contains its own niche")
    for payload, width, signed in (("Int8", 8, True), ("Int16", 16, True),
                                   ("Int32", 32, True), ("UInt8", 8, False),
                                   ("UInt16", 16, False),
                                   ("UInt32", 32, False)):
        want = 1 << width
        got, _why = M.optional_none_word(payload, {})
        if got != want:
            failures.append(f"{payload}: niche is {got!r}, expected {want!r}")
            continue
        lo = -(1 << (width - 1)) if signed else 0
        hi = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
        if lo <= _as_value(want) <= hi:
            failures.append(
                f"{payload}: its niche {want!r} holds the value "
                f"{_as_value(want)}, which IS a value of the type - the niche "
                f"has to be outside [{lo}, {hi}]")
    # `Float32` has NO niche and must be refused, and the reason is in the
    # table's own comment: `Float32(1.5)` does not lower on this target at all,
    # so there is no word for a `Float32` to occupy and therefore none for `None`
    # to be. Checked here because a type that gains a lowering later would
    # otherwise silently acquire a niche from a width row nobody re-examined.
    if M.optional_none_word("Float32", {})[0] is not None:
        failures.append("Float32: answered with a niche, but the type has no "
                        "representation on this target to have one")

    # (2) `SCALAR_TYPE_WIDTHS` agrees with `formal.types.TYPE_NAMES` entry for
    #     entry. Two width tables with nothing between them is how a 32-bit
    #     niche becomes a 64-bit one, and the 64-bit row is the one with NO
    #     answer - so the disagreement is not a wrong niche but a REFUSAL where
    #     a program should build, which is the more expensive direction to get
    #     wrong and the harder one to notice.
    for name, it in FT.TYPE_NAMES.items():
        row = M.SCALAR_TYPE_WIDTHS.get(name)
        if row is None:
            failures.append(f"{name}: in formal.types.TYPE_NAMES and not in "
                            f"model.SCALAR_TYPE_WIDTHS")
            continue
        if row[0] != it.width or (row[1] is not None
                                  and bool(row[1]) != bool(it.signed)):
            failures.append(f"{name}: formal.types says width={it.width} "
                            f"signed={it.signed}, model says {row}")
    for name in FT.BOOL_TYPE_NAMES:
        if name not in M.SCALAR_TYPE_WIDTHS:
            failures.append(f"{name}: a Bool on this path and not in "
                            f"model.SCALAR_TYPE_WIDTHS")

    # (3) Every payload with NO niche is refused, and the refusal NAMES the
    #     payload type and the alternative. A refusal that does not is the
    #     failure mode this whole area has: a reader sent looking for a bug that
    #     is not there.
    for payload in ("Int", "Int64", "UInt", "UInt64", "Float64", "Float32"):
        word, why = M.optional_none_word(payload, {})
        if word is not None:
            failures.append(f"{payload}: answered with a niche ({word!r})")
            continue
        for needle in (f"`Optional[{payload}]`", "TWO-WORD", "Some(0)"):
            if needle not in why:
                failures.append(f"{payload}: the refusal does not name "
                                f"{needle!r}")

    # (3b) The refusal says WHY, and there are THREE whys, so a check that
    #      only asserted "it refused" let a float be told it was a struct. The
    #      last branch of `optional_none_word` used to be `base[:1].isupper()`,
    #      a SPELLING test standing in for a fact about the type, and both
    #      `Float32` and `DType` matched it — so a user who wrote a float was
    #      told this build had not read the fields of a struct it has no reason
    #      to read. The verdict was never wrong (`doc/ABI.md`'s niche table and
    #      `bugs/FORMAL_optional_needs_a_niche.md` both list these two as
    #      refused, which is why nothing went red); only the sentence, which is
    #      the part a user reads.
    #
    #      Each row is checked in BOTH directions, and the last one is the
    #      positive control: without it, "never claim a struct" would pass by
    #      deleting the one reason that is true for a real struct of another
    #      module, which is a strictly worse message than a mislabelled one.
    STRUCT_REASON = "struct whose fields this build does not compile"
    for payload in ("Int", "Int64", "UInt", "UInt64", "Float64", "DType"):
        _w, why = M.optional_none_word(payload, {})
        if STRUCT_REASON in why:
            failures.append(
                f"{payload}: every 64-bit word is a value of it, and the "
                f"refusal says {STRUCT_REASON!r} instead")
        if "every word is a value of" not in why:
            failures.append(f"{payload}: the refusal does not say that every "
                            f"word is a value of it")
    _w, why = M.optional_none_word("Float32", {})
    if STRUCT_REASON in why:
        failures.append(f"Float32: refused as a struct, but it is a SCALAR "
                        f"this target cannot represent at all")
    if "no representation" not in why:
        failures.append("Float32: the refusal does not say that this target "
                        "has no representation for it")
    for payload in ("SomeOtherModule", "Widget"):
        _w, why = M.optional_none_word(payload, {})
        if STRUCT_REASON not in why:
            failures.append(f"{payload}: a name this module's declarations do "
                            f"not carry and no scalar table claims, and the "
                            f"refusal does not say {STRUCT_REASON!r}")

    # (4) The four `Optional` method names are all in ONE table, every name in it
    #     has a lowering, and none of them answers a payload with no niche. A
    #     method added here without a lowering is a refusal the emitter never
    #     raises, and one left out of it is a refusal about a construct the
    #     representation answers.
    if set(M.OPTIONAL_METHOD_LOWERINGS) != {"or_else", "value_or", "or",
                                            "unsafe_value"}:
        failures.append("the Optional method table is not the four names the "
                        "stdlib spells")
    for method in M.OPTIONAL_METHOD_LOWERINGS:
        how, word = M.optional_unwrap_lowering(method, "Optional[Bool]", {})
        if how is None or word != 2:
            failures.append(f"{method}: the lowering for Optional[Bool] is "
                            f"{(how, word)!r}, expected a lowering and the "
                            f"niche 2")
        if M.optional_unwrap_lowering(method, "Optional[Int]", {})[0] is not None:
            failures.append(f"{method}: answered for Optional[Int], whose "
                            f"payload has no niche")

    # (5) A reference-shaped payload's niche is `NONE_WORD`, so `x is None` on an
    #     `Optional` is the SAME answer `x is None` already gives for a
    #     reference on this path. Two conventions for one question would be two
    #     answers, and this is the check that they are one.
    if M.optional_none_word("String", {})[0] != M.NONE_WORD:
        failures.append("a reference-shaped payload's niche is not NONE_WORD, "
                        "so `x is None` on an Optional would stop meaning what "
                        "it means on a reference")
    for payload in ("Pointer[Int]", "List[Int]", "Tuple[Int, Int]"):
        if M.optional_none_word(payload, {})[0] != M.NONE_WORD:
            failures.append(f"{payload}: a reference-shaped payload with a "
                            f"niche that is not the reference's null")

    # (6) `lib/ProofLib.lean` states the SAME table, and the two must agree.
    #     Read out of the Lean source rather than by running `lean`: the rule in
    #     this file is never to launch `lean` from a test (`formal/lean.py` is
    #     the one caller), and the facts being checked here are DEFINITIONS —
    #     three `def` arms whose right-hand sides are numerals and a power — so
    #     a source read is the whole of the check and a proof run would add cost
    #     and no information.  What a source read cannot check is that the file
    #     COMPILES, and that is the integrator's `make gate`, which builds the
    #     library through `formal/lean.py`.
    #
    #     The drift this catches is the one that matters: the niche's only trace
    #     in an image is the IMMEDIATE of the compare, so a table that changed on
    #     the Python side alone would leave the proof describing a comparison the
    #     image does not contain.  Same shape as
    #     `test_formal_monomorph.py::a_stated_mangled_spelling_is_the_one_the
    #     mangler_produces`.
    lean = _read_lean_optional_rows()
    if lean is None:
        failures.append("lib/ProofLib.lean states no `optionalNoneWord` arms, "
                        "so the Lean model does not carry the Optional "
                        "representation")
    else:
        # The two arms with a NUMERAL right-hand side, and only those: the
        # narrow row's is the expression `2 ^ w`, checked as text just below.
        for arm, model_word in (("reference", M.NONE_WORD), ("bool", 2)):
            if arm not in lean:
                failures.append(f"ProofLib.lean's optionalNoneWord has no "
                                f"`. {arm}` arm")
            elif lean[arm] != model_word:
                failures.append(
                    f"ProofLib.lean's optionalNoneWord . {arm} = "
                    f"{lean[arm]}, the model says {model_word}")
        if "| .narrow w => 2 ^ w" not in _lean_text():
            failures.append("ProofLib.lean's narrow niche is not `2 ^ w`, which "
                            "is the only expression `optional_none_word`'s "
                            "`1 << width` row evaluates to")

    if verbose:
        for f in failures:
            print(f"      table: {f}")
    return failures


_LEAN = None


def _lean_text() -> str:
    global _LEAN
    if _LEAN is None:
        with open(os.path.join(HERE, "lib", "ProofLib.lean"),
                  encoding="utf-8") as f:
            _LEAN = f.read()
    return _LEAN


def _read_lean_optional_rows() -> dict:
    """`{constructor: the Nat its `optionalNoneWord` arm spells}`, or None."""
    rows, in_def = {}, False
    for line in _lean_text().splitlines():
        if line.startswith("def optionalNoneWord"):
            in_def = True
            continue
        if in_def:
            if line.startswith("  | "):
                parts = line.split("=>")
                if len(parts) == 2:
                    arm = parts[0].strip().lstrip("|").strip().lstrip(".")
                    try:
                        rows[arm] = int(parts[1].strip())
                    except ValueError:
                        rows[arm] = None
                continue
            if line.strip() and not line.startswith(" "):
                in_def = False
    return rows or None


def _as_value(word: int) -> int:
    """The 64-bit SIGNED value a word holds.

    This is what makes the niche check the right check, and getting it wrong is
    what made the first version of it fail: an `Int8` value lives in a 64-bit
    register SIGN-EXTENDED (`formal/types.py`), so the set of WORDS an `Int8` can
    hold is the set of VALUES it can hold — `[-128, 127]` — and NOT the set of
    8-bit patterns. Reading the niche `256` as "an 8-bit pattern" says 0, which
    is a value of the type, and concludes (falsely) that `Optional[Int8]` has no
    niche. Read as the 64-bit signed value it is 256, which is not in the range,
    and the niche is sound. A `w`-bit type's domain on this target is its VALUE
    range, and that is what `check_table` compares against.
    """
    word &= (1 << 64) - 1
    return word - (1 << 64) if word >> 63 else word


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    everything = ([(c, False) for c in CASES]
                  + [(c, "fixed") for c in FIXED_CASES]
                  + [(c, True) for c in REFUSALS])
    selected = [c for c in everything if not args.cases or c[0][0] in args.cases]
    known = {c[0][0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        print(f"ERROR: unknown case(s): "
              f"{sorted(set(args.cases) - known)}", file=sys.stderr)
        return 2

    passed = failed = 0
    for f in check_table(None, args.verbose):
        failed += 1
        print(f"  FAIL  the niche table: {f}")
    passed += 1
    print(f"  PASS  the niche table (properties of "
          f"model.optional_none_word)")

    with tempfile.TemporaryDirectory() as tmpdir:
        for entry, kind in selected:
            try:
                if kind == "fixed":
                    ok, detail = run_fixed_case(entry[0], entry[1], entry[2],
                                                tmpdir, args.verbose)
                elif kind:
                    ok, detail = run_refusal(entry[0], entry[1], entry[2],
                                             tmpdir, args.verbose)
                else:
                    ok, detail = run_case(entry[0], entry[1], entry[2], tmpdir,
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
                print(f"  PASS  {entry[0]}")
            else:
                failed += 1
                print(f"  FAIL  {entry[0]}: {detail}")

    print(f"\nformal Optional: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
