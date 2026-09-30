#!/usr/bin/env python3
"""The refusal taxonomy must stay a taxonomy.

Measured 2026-09-28, arm64: 130 in-file codegen findings resolved to 104
distinct message TEXTS, and 123 of the 130 landed in one bucket called "other
refusal". So the sweep could say that 25.9% of the denominator was blocked and
name none of it — which is the specific thing a family table exists to prevent.

It is now 20 families and zero "other". Two things about that are worth
protecting, and they are not the same thing:

1. **Precedence.** `_refusal_family` takes the FIRST marker that matches, so
   position in the tuple is load-bearing. A perfectly good marker placed after
   a broader one is dead code, and it fails silently: the broader family claims
   the message and the count is simply wrong. The real case here was "which is
   a name with no definition in hand", which appears *inside* a message that
   begins "a X receiver is passed to ..." — 11 findings were being counted as
   a receiver problem, which is a number in the wrong column. That is worse than
   having no taxonomy, so it is worth a test rather than a code comment.

2. **Rot.** Every marker is a substring of a message the backend actually
   produced. A marker that stops matching does not fail — the family goes
   quietly unused and its findings fall back into whatever matches next, or
   into "other". The samples below are real messages, abbreviated at clause
   boundaries, and each asserts the family it must land in.

Run:  python3 test_refusal_taxonomy.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_sweep as S  # noqa: E402

# (family, a real message, truncated only at a clause boundary)
SAMPLES = [
    # The frame-address families. All one design defect, five costumes; the
    # distinction is which fix applies.
    ("frame address escapes: returned by its creator",
     "a String receiver is returned from the function that created it on this "
     "path: the receiver of a multi-field struct is the ADDRESS of a frame"),
    ("frame address escapes: aliased out of a method",
     "a Progress receiver is returned from a method of Progress, which did not "
     "create the frame — it received the address as its receiver"),
    ("frame address passed where a value is wanted",
     "a BinaryHeap frame address is passed to len(), which is lowered as an "
     "operation on a VALUE: it wants the object itself"),
    ("receiver passed as an argument",
     "a _WriteBufferStack receiver is passed to ?.write_to in argument "
     "position 0, and a method call on a value receiver is dispatched by NAME"),
    ("field slot holds a frame address",
     "self.asm.org() hands the word in the slot self.asm to Assembler.org(), "
     "whose receiver is the ADDRESS of a frame of 8-byte slots"),
    ("name has two disagreeing shapes",
     "x.y cannot be placed: this name holds a frame address in more than one "
     "shape, and the shapes do not agree"),
    # The two shapes the message above was ALSO matching, before
    # `formal/model.py`'s `member_read_without_a_field` told the two apart: it
    # printed "more than one shape … the shapes do not agree" for a SINGLE
    # candidate with nothing to disagree about, which put 4 files of row 13 in a
    # family about a disagreement that did not exist. They need families of
    # their own or they land in "other refusal" — which is the exact failure this
    # file exists to catch, introduced by fixing a diagnostic.
    ("member read of a method used as a value",
     "self._untyped_callee names '_untyped_callee', which is a METHOD of "
     "ARM64Codegen rather than one of its fields"),
    ("member read of a name the struct does not have",
     "gen.type_checker is a field of gen, and GimpleGen has no field "
     "'type_checker'"),
    # The precedence case. This message contains "receiver is passed to" AND
    # "which is a name with no definition in hand", and must take the second.
    ("callee has no definition on this path",
     "a String receiver is passed to _b64encode(), which is a name with no "
     "definition in hand: this module's own functions are the only ones in "
     "this image"),
    # The one frame family that CRASHES rather than computing a wrong number.
    ("self has two kinds of value across call sites",
     "Random_step() takes a Random receiver at argument 0 — 'self' — at "
     "Random_step(self) here, and something that is not a frame address at "
     "Random_step(self._rng)"),
    # The rest.
    ("MLIR construct",
     "materialize: __mlir_op is an MLIR dialect construct. This path has no "
     "MLIR: it lowers a Mojo program to a Mach-O image"),
    ("MLIR construct",
     "the module-level comptime binding '_PLUGIN_COUNT' is initialized from an "
     "MLIR attribute template: __mlir_attr[`#kgen.param_list.size<:`,"),
    ("nested frame field read",
     "self._handle._get_ctx reads '_get_ctx' out of a nested RaisingCoroutine "
     "frame, and that struct's 2 field(s): origins, _handle has no such"),
    ("comptime does not fold",
     "comptime num_coefficients = ... does not fold to a compile-time constant "
     "on this path, so there is no value to materialize"),
    ("comptime does not fold",
     "_serialize_elements_compact: '_kCompactElemPerSide' is a `comptime` "
     "binding declared at module level, and it does not fold to a compile-time "
     "constant on this path"),
    ("unimplemented intrinsic",
     "a `...` stands where this path needs instructions to emit, and there are "
     "none: a formal image is a compiled program"),
    ("variadic call has no ABI",
     "tile: the body reads 'tile_size_list', its *-parameter, and this path "
     "has no variadic ABI"),
    ("unsupported construct (parse error)",
     "parse error: /x/std/algorithm/reduction.mojo:251:7: `comptime { … }` and "
     "`comptime <expr>` are not supported by this compiler"),
    ("construction with arguments needs __init__",
     "constructing FuncAttribute with 2 argument(s) is a call to a "
     "user-defined `__init__` and none of them takes that count"),
    ("receiver stored in a container",
     "a Optional receiver is stored in a container, which has no layout for a "
     "frame address on this path"),
    ("module-global name has no storage",
     "type_to_c: 'MLIR_TYPES' is bound at module level, and this path has no "
     "module-global storage for it: a formal value lives in a function's own"),
    ("method call on a value",
     "writer.write_string() is a method on a Writer — a multi-field struct, so "
     "on this path the receiver is the ADDRESS of a frame of 8-byte slots"),
]


def main() -> int:
    failures = []

    for family, msg in SAMPLES:
        got = S._refusal_family(msg)
        if got != family:
            failures.append(
                f"expected {family!r}, got {got!r}\n"
                f"    message: {msg[:100]}")

    # The precedence rule, stated independently of the samples above so a
    # future edit cannot satisfy SAMPLES by deleting a marker outright.
    pre = ("a X receiver is passed to foo(), which is a name with no "
           "definition in hand")
    if S._refusal_family(pre) != "callee has no definition on this path":
        failures.append(
            "the 'callee has no definition' marker is being shadowed by a "
            "broader receiver marker; its findings are counted as a receiver "
            f"problem again (got {S._refusal_family(pre)!r})")

    # Every family name is distinct and readable, and none is the catch-all.
    names = [f for _m, f in S._REFUSAL_FAMILIES]
    if S._REFUSAL_OTHER in names:
        failures.append(
            f"{S._REFUSAL_OTHER!r} is in _REFUSAL_FAMILIES, so the catch-all "
            "can match and findings stop being visible as unclassified")

    # A marker that is a GENERIC phrase would swallow the families above it and
    # quietly defeat the whole table. The obvious version is a bare English
    # word. A code token is NOT the same thing: `__mlir_` is one identifier
    # prefix and is about as specific as a marker can be, so markers that look
    # like code are exempt.
    for marker, family in S._REFUSAL_FAMILIES:
        looks_like_code = ("_" in marker or "(" in marker or "." in marker)
        if len(marker.split()) < 3 and " " not in marker and not looks_like_code:
            failures.append(
                f"marker {marker!r} (family {family!r}) is a bare word; a "
                "generic marker placed early would claim messages the more "
                "specific markers below it were written for")

    for f in failures:
        print("  FAIL  " + f)
    print(f"\nrefusal taxonomy: {'PASS' if not failures else 'FAIL'} "
          f"({len(SAMPLES) + 3 - len(failures)}/{len(SAMPLES) + 3} checks, "
          f"{len(set(names))} families)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
