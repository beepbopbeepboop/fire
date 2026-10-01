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

3. **A count that reads like a gap and is not one.** The cause table in
   `tools/formal_sweep_causes.py` ranks by what a fix would have to CHANGE, and
   prints `FILES BLOCKED` with an explicit warning that it is an upper bound.
   For a cause whose refusal is about a MODULE's boundary rather than a
   construct in the swept file, the bound is loose enough to invert the
   decision: `module exports no public functions` was 38 files, 35 of them
   behind `std/collections/binary_heap.mojo`, and 34 of those 35 contain no
   occurrence of `BinaryHeap` at all — the formal backend builds a dylib for
   every module in a file's EAGER import closure, so a module with no boundary
   symbol refuses importers that bind nothing in it. That is why the table also
   prints `uses:` (how many of a module's blocked files name anything it
   declares), and the section below pins it: a `uses` column that is always 0,
   that matches substrings, or that reports "I could not find the module" as a
   measured 0, is worse than no column. Measured ceilings, both 0 files:
   `bugs/FORMAL_dylib_export_gate_ceiling.md`.

Run:  python3 test_refusal_taxonomy.py
"""
import os
import sys
import tempfile

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
     "gen.type_checker cannot be placed: this name holds a frame address in "
     "more than one shape, and the shapes do not agree"),
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
    checks = len(SAMPLES) + 3

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
    checks += _uses_column_checks(failures)
    print(f"\nrefusal taxonomy: {'PASS' if not failures else 'FAIL'} "
          f"({checks - len(failures)}/{checks} checks, "
          f"{len(set(names))} families)")
    return 1 if failures else 0


# ── the `uses:` column of the CAUSE table, and the audit it rests on ─────────
#
# The same discipline the family table above is held to, applied to the number
# the cause table ranks by. `FILES BLOCKED` is an upper bound; for a cause about
# a module's boundary the question "how many of these files would a fix to THAT
# MODULE actually reach" has a cheap exact answer when the files name none of
# its declarations, and it is not the count.
#
# The cause table is reached as `formal_sweep_causes`, whose source index is a
# module global built by walking both trees; the tests below pin it to four
# fixture files, because "the number is 0 because it could not look" and "the
# number is 0 because it looked and found nothing" have to be told apart.

# The real wording `no_public_api_reason` emits for a generic struct template.
_MODULE_REFUSAL = ("template.mojo: formal dylib has no public functions: "
                   "template.mojo exports nothing under doc/ABI.md's rules: it "
                   "declares only the generic struct template(s) Thing, and a "
                   "parametric type has no single boundary layout either.")


def _uses_column_checks(failures):
    import formal_sweep_causes as C
    n = [0]

    def check(ok, message):
        n[0] += 1
        if not ok:
            failures.append(message)

    tmp = tempfile.mkdtemp(prefix="uses_column_")

    def write(name, text):
        path = os.path.join(tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    module = write("template.mojo",
                   "struct Thing[T: Copyable]:\n  var x: Int\n")
    uses_it = write("uses_it.mojo",
                    "from template import Thing\nvar h = Thing[Int]()\n")
    does_not = write("does_not.mojo",
                     "from something_else import Widget\nvar w = Widget()\n")
    # Its only `Thing` is inside `ThingHelper`, so a substring match counts it.
    longer = write("longer_name.mojo",
                   "from template import ThingHelper\nvar q = ThingHelper()\n")

    def line(path, refuser):
        return (f"CODEGEN/DEPENDENCY: {path}  (build: a.mojo imports 'x', which "
                f"cannot be built either: {refuser}: {_MODULE_REFUSAL})")

    def rank(log, index):
        saved = C._index
        C._index = index
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".log",
                                             delete=False) as f:
                f.write(log)
                logpath = f.name
            try:
                return C.rank(logpath)[0]
            finally:
                os.unlink(logpath)
        finally:
            C._index = saved

    def row_of(table, cause):
        for r in table:
            if r["cause"] == cause:
                return r
        return None

    table = rank("\n".join([line(uses_it, "template.mojo"),
                            line(does_not, "template.mojo"),
                            line(longer, "template.mojo")]) + "\n",
                 {"template.mojo": [module]})
    row = row_of(table, C.CAUSE_NO_BOUNDARY_SYMBOL)
    check(row is not None,
          "a real `module exports no public functions` message was not "
          "classified as one, so the cause table no longer recognises the "
          f"wording it was written for. Labels seen: "
          f"{[r['cause'] for r in table]}")
    if row is None or len(row["uses"]) != 1:
        check(False,
              f"three findings from one refusing module produced "
              f"{0 if row is None else len(row['uses'])} `uses:` entries")
        return n[0]
    refuser, src, blocks, uses, declared = row["uses"][0]
    check(blocks == 3, f"expected 3 blocked files, got {blocks}")
    check(src == module,
          f"the refusing module resolved to {src!r}, not the fixture "
          f"{module!r} — the index lookup is not returning the file it was "
          f"handed")
    check(declared == ["Thing"],
          f"the declared names are {declared}, expected ['Thing'] — the column "
          f"is searching for the wrong population")
    # One use, and `longer.mojo` is not one: a plain substring match would
    # report 2, and 0 would make every row read as closure.
    check(uses == 1,
          f"`uses` counted {uses} of 3. It must count `uses_it.mojo` alone — "
          f"0 makes every row read as closure, and a substring match also "
          f"counts `longer_name.mojo`, whose only `Thing` is inside "
          f"`ThingHelper`")

    gone = row_of(rank(line(does_not, "gone.mojo") + "\n", {}),
                  C.CAUSE_NO_BOUNDARY_SYMBOL)
    check(gone is not None and len(gone["uses"]) == 1,
          "a refusal from a module that is not on disk produced no `uses:` "
          "entry, so there is nowhere for the not-measured note to live")
    if gone is not None and gone["uses"]:
        check(gone["uses"][0][1] is None,
              f"a refusing module absent from the tree resolved to "
              f"{gone['uses'][0][1]!r} instead of None, so its 0 would be "
              f"printed as a measurement")

    def resolve(basename, index):
        saved = C._index
        C._index = index
        try:
            return C._resolve_refuser(basename, does_not)
        finally:
            C._index = saved

    one = write("dup_a/__init__.mojo", "struct Other:\n  var y: Int\n")
    two = write("dup_b/__init__.mojo", "struct Other:\n  var y: Int\n")
    got = resolve("__init__.mojo", {"__init__.mojo": [one, two]})
    check(got is None,
          f"an ambiguous basename resolved to {got!r}; a count computed from "
          f"the wrong one of two files is a number nobody can check")
    solo = resolve("template.mojo", {"template.mojo": [module]})
    check(solo == module,
          f"an unambiguous basename resolved to {solo!r}, so the ambiguity "
          f"guard would pass for the wrong reason")

    # The audit the whole 38-file row rests on, which nothing pinned before.
    heap = None
    try:
        import module_loader
        cand = os.path.join(module_loader.STDLIB_PATH,
                            "std", "collections", "binary_heap.mojo")
        heap = cand if os.path.isfile(cand) else None
    except Exception:                                    # noqa: BLE001
        heap = None
    if heap is None:
        print("  SKIP  the stdlib is not reachable from here, so the "
              "binary_heap.mojo export audit is not checked")
    else:
        import reflect
        with open(heap, encoding="utf-8", errors="replace") as f:
            excl = reflect.export_exclusions(f.read())
        check(excl == {"BinaryHeap": "generic-template"},
              f"std/collections/binary_heap.mojo's export exclusions are "
              f"{excl}, not {{'BinaryHeap': 'generic-template'}}. "
              f"FORMAL_known_limits.md §1.1a and the 38-file row both rest on "
              f"that being the whole story: if it changed, the row is a "
              f"different finding and the doc is wrong, and both need "
              f"re-auditing rather than a stale number standing in for them")
    return n[0]


if __name__ == "__main__":
    sys.exit(main())
