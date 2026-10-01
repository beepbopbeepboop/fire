#!/usr/bin/env python3
"""A `#kgen.param.expr<…>` target query, answered at build time and EXECUTED.

What is under test. `formal/model.py` refuses every MLIR attribute template on
the ground that "there is no MLIR on this path for the template to become". That
ground is right about a DIALECT ATTRIBUTE — `#kgen.simd<1>`,
`#pop.float_literal<nan>`, `#lit.struct<{…}>` — and wrong about the family
whose meaning is not an MLIR object at all: a QUESTION the build can answer.

`std/sys/info.mojo` is built out of them, and 35 of the 46 files in that family
are blocked behind it:

    comptime _TargetType = __mlir_type.`!kgen.target`
    def __arch() -> __mlir_type.`!kgen.string`:
        return __mlir_attr[
            `#kgen.param.expr<target_get_field,`, Self.value,
            `, "arch" : !kgen.string`, `> : !kgen.string`]

A formal image is compiled for ONE target and that target is stated by the build
itself, so "what is the current target's arch" has exactly one correct answer,
and answering it at build time is not a guess. Every case in EXECUTED below
therefore BUILDS the arm64 image, EXECUTES it, and compares what it printed
against a value this file states independently of the code under test.

THE ORACLE, and why it is not the implementation restated. A target query has
no CPython meaning — `__mlir_attr` is not a thing CPython can run — so the
"compare with CPython" discipline is honoured where CPython really is an oracle
and replaced by a stated literal, with its provenance in a comment, where it is
not:

  * `pointer_width` is compared with `struct.calcsize("P") * 8`, `endianness`
    with `sys.byteorder`, `os` with `sys.platform`, and `cross_compilation`
    with `platform.machine()`. Four independent measurements of the same facts;
    a wrong constant in `Target` cannot agree with all of them.
  * `simd_bit_width` (128) and `arch` ("aarch64") have no CPython oracle. The
    128 is the vector register width of both architectures the backend emits,
    and the spelling is `std/sys/info.mojo`'s own — its `__arch` docstring says
    the architecture string is "x86_64" or "aarch64".

REFUSED below is the half that keeps the first half honest: a per-CPU question,
a target field this build has no source for, the target itself read as a value,
a `__mlir_type` template, a dialect attribute, an operand the build cannot fold,
and a declared result type that is not lowerable are all still refused, each
naming the missing fact, and identically on both architectures. A hand-kept
CPU-feature table would have made the first of those pass, and would have been a
wrong answer no test could see the rot of.

Run:  python3 test_formal_target_queries.py [-v] [case ...]
"""
import argparse
import os
import platform
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 60

sys.path.insert(0, HERE)
import formal.model as M  # noqa: E402


def query(field, ftype, rtype, indent=""):
    """A whole `__mlir_attr[…]`, spelled the way `std/sys/info.mojo` spells it.

    Dotted for the nested `current_target` and a bracketed comma list for the
    outer query, because both spellings are in the stdlib and a parser that
    read only one of them would pass a test written in the other.
    """
    return ("__mlir_attr[\n"
            + f"{indent}    `#kgen.param.expr<target_get_field,`,\n"
            + f"{indent}    __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
            + f'{indent}    `, "{field}" : {ftype}`,\n'
            + f"{indent}    `> : {rtype}`]")


# The CPython-derivable facts about the host, evaluated once. Four independent
# measurements, each of which the implementation had to agree with.
HOST_POINTER_BITS = struct.calcsize("P") * 8
HOST_IS_LITTLE = 1 if sys.byteorder == "little" else 0
HOST_OS = {"darwin": "darwin", "linux": "linux"}.get(sys.platform, sys.platform)
HOST_IS_ARM = platform.machine() in ("arm64", "aarch64")
NATIVE_XCOMP = 0 if HOST_IS_ARM else 1
HOST_ARCH_FIELD = "aarch64" if HOST_IS_ARM else "x86_64"

# (name, source, expected stdout fragment) — or an int, meaning the expected
# EXIT STATUS and no output assertion. The comment on each case says where the
# expected value comes from.
EXECUTED = [
    # `arch`. No CPython oracle exists for the LLVM spelling, so this is a
    # stated literal — and the literal is `std/sys/info.mojo`'s own: the
    # `__arch` docstring says the architecture string is "x86_64" or
    # "aarch64", and this is the architecture the backend emits on an arm64
    # host (which `main` above has already established, or skipped).
    ("arch_is_the_architecture_the_image_is_for",
     "def main():\n"
     "    var a = " + query("arch", "!kgen.string", "!kgen.string", "    ") + "\n"
     "    print(\"arch=\", a)\n",
     "arch= " + HOST_ARCH_FIELD),
    # `pointer_width`, against `struct.calcsize("P") * 8`. A formal value is one
    # 64-bit word, so this query could only be right by accident if the
    # implementation and this test both said 64 out of the same belief — and
    # here the test measures the host pointer width instead.
    ("pointer_width_matches_the_host_pointer",
     "def main():\n"
     "    var p = " + query("pointer_width", "index", "index", "    ") + "\n"
     "    print(\"pw=\", p)\n",
     "pw= %d" % HOST_POINTER_BITS),
    # `endianness`, against `sys.byteorder`, read through the `eq` the stdlib
    # itself writes (`is_little_endian` is `eq(endianness, "little")`). The
    # two-level fold is the point: the outer query is answerable only because
    # its operand is a query the build already answered.
    ("little_endian_read_through_eq",
     "def main():\n"
     "    var e = __mlir_attr[\n"
     "        `#kgen.param.expr<eq,`,\n"
     "        " + query("endianness", "!kgen.string", "!kgen.string", "        ") + ",\n"
     "        `,`,\n"
     "        `\"little\" : !kgen.string`,\n"
     "        `> : !kgen.scalar<bool>`,\n"
     "    ]\n"
     "    print(\"little=\", e)\n",
     "little= %d" % HOST_IS_LITTLE),
    # `simd_bit_width`, declared `: index` exactly as `info.mojo`'s
    # `simd_bit_width` declares it. No CPython oracle: 128 is the vector
    # register width of both architectures this backend emits (NEON on
    # AArch64, the baseline XMM/YMM pair on x86-64), and that is a property
    # of the ARCHITECTURE rather than of the machine doing the compiling,
    # which is what makes it safe to state.
    ("simd_bit_width_is_128",
     "def main():\n"
     "    var s = " + query("simd_bit_width", "index", "index", "    ") + "\n"
     "    print(\"simd=\", s)\n",
     "simd= 128"),
    # `cross_compilation`, against `platform.machine()`. This is the query a
    # constant would get BACKWARDS on half the backend's own configurations: it
    # is false for the default arm64 build on an arm64 Mac and true for
    # `--arch=x86_64` on that same Mac, so no single constant is right. This
    # case runs the native build; `the_other_architecture_is_a_cross_build`
    # below is the other half of the claim, and it is the one that would catch
    # a hardcoded answer.
    ("cross_compilation_is_false_for_the_native_build",
     "def main():\n"
     "    var x = __mlir_attr.`#kgen.param.expr<cross_compilation> : i1`\n"
     "    print(\"xc=\", x)\n",
     "xc= %d" % NATIVE_XCOMP),
    # `accelerator_arch`, which `info.mojo`'s own docstring pins: "If there is
    # no accelerator on the system, this function returns an empty string." A
    # formal image links the platform C library and nothing else, so the empty
    # string is a fact about the link line rather than a guess.
    ("accelerator_arch_is_empty",
     "def main():\n"
     "    var a = __mlir_attr.`#kgen.param.expr<accelerator_arch> : !kgen.string`\n"
     "    print(\"acc=[\", a, \"]\")\n",
     "acc=[  ]"),
    # The MODULE-LEVEL `comptime` BINDING this suite is named for, with all
    # three of its routes in one program: the binding's own initializer (folded
    # by `model.fold_module_value` through `collect_module_symbols`), the read
    # in `main` (substituted by `_substitute_module_constants`), and the two
    # query SHAPES — a dotted `current_target` inside a comma list, and a
    # one-token dotted query with no list at all. A module-level name has no
    # storage on this path (every value lives in a function's own stack
    # scratch), so each read can only be satisfied by the substituted literal:
    # an unfolded one is refused by name, and a fabricated one would print
    # whatever the allocator left behind.
    ("module_level_comptime_bindings_of_queries_are_folded",
     "comptime ARCH = " + query("arch", "!kgen.string", "!kgen.string") + "\n"
     "comptime OS = " + query("os", "!kgen.string", "!kgen.string") + "\n"
     "comptime PW = " + query("pointer_width", "index", "index") + "\n"
     "comptime XCOMP = __mlir_attr.`#kgen.param.expr<cross_compilation> : i1`\n"
     "def main():\n"
     "    print(\"arch=\", ARCH, \"os=\", OS, \"pw=\", PW, \"xc=\", XCOMP)\n",
     "arch= %s os= %s pw= %d xc= %d" % (HOST_ARCH_FIELD, HOST_OS,
                                       HOST_POINTER_BITS, NATIVE_XCOMP)),
    # The same binding as a FUNCTION-LOCAL `comptime`, which takes the other
    # route: `formal/build.py:_fold_target_queries` rewrites the query in the
    # body to the literal it denotes, and the backend's own comptime folder then
    # binds the name to that. Two mechanisms, one answer — and if either were
    # missing, this case is the one that notices.
    #
    # Asserted through the EXIT STATUS rather than through `print`, and that is
    # not a stylistic choice: `print` of a `comptime`-bound STRING is refused on
    # this path, and routing around it one `var` further prints a NUMBER
    # instead (`t= 4296786840` on arm64, `t= 4300370841` on x86-64, for
    # `comptime OS = "darwin"; var t = OS; print(t)`). That is a pre-existing
    # wrong-answer bug in the `print` materialization, recorded in
    # bugs/FORMAL_comptime_string_print.md; a case for this construct must not
    # be built on top of it.
    ("function_local_comptime_of_a_query_is_folded",
     "def main():\n"
     "    comptime PW = "
     + query("pointer_width", "index", "index", "    ") + "\n"
     "    return PW\n",
     HOST_POINTER_BITS % 256),
    # A query NESTED inside a call's argument, which is the shape
    # `std/builtin/type_aliases.mojo` puts its templates in (two levels down,
    # under `Origin[0, _mlir_origin=__mlir_attr[…]]()`). The walk has to
    # recurse past the call to reach it: a refusal that only looked at the
    # initializer's top node would miss it entirely, which is how that file was
    # a false PASS in the sweep baseline.
    ("query_nested_in_a_call_argument",
     "def main():\n"
     "    var n = Int("
     + query("pointer_width", "index", "index", "    ") + ")\n"
     "    print(\"n=\", n)\n",
     "n= %d" % HOST_POINTER_BITS),
    # `eq` over two operands the build already folded, and `add` over an
    # integer and a query's value. Neither is a target query: they are the
    # arithmetic `eq` and `add` are written in, and they are here because a
    # program COMPOSES queries, and a template whose inner query folded is
    # useless if the outer one cannot.
    ("eq_and_add_over_folded_operands",
     "def main():\n"
     "    var e = __mlir_attr[\n"
     "        `#kgen.param.expr<eq,`, 2, `, 2> : i1`]\n"
     "    var a = __mlir_attr[\n"
     "        `#kgen.param.expr<add,`,\n"
     "        " + query("pointer_width", "index", "index", "        ") + ",\n"
     "        `, 2> : index`]\n"
     "    print(\"e=\", e, \"a=\", a)\n",
     "e= 1 a= %d" % (HOST_POINTER_BITS + 2)),
    # The EXIT STATUS, not just the output. `main`'s return value is the process
    # exit status, so a folded boolean that came out false when the source says
    # true fails here even if a `print` were dropped from the case.
    ("the_folded_value_reaches_the_exit_status",
     "def main():\n"
     "    var e = __mlir_attr[\n"
     "        `#kgen.param.expr<eq,`,\n"
     "        " + query("arch", "!kgen.string", "!kgen.string", "        ") + ",\n"
     + f'        `, "{HOST_ARCH_FIELD}" : !kgen.string`,\n'
     "        `> : !kgen.scalar<bool>`,\n"
     "    ]\n"
     "    if e:\n"
     "        return 7\n"
     "    return 3\n", 7),
]

# (name, source, needle) — every one must be REFUSED, and identically on both
# architectures. The needle is the part that names the missing fact, so a
# message that went back to "there is no MLIR on this path" fails here.
REFUSED = [
    # A CPU feature. There is no feature database on a path that links
    # libSystem and nothing else, and the build names the architecture it emits
    # and never a CPU — which is why the two rules that COULD answer it
    # without a database ("impossible for this architecture", "mandatory for
    # it") would still leave every optional extension undecided, and why a
    # table pretending to be a derivation is the wrong answer.
    ("has_feature_is_a_per_cpu_question",
     "def main():\n"
     "    var f = __mlir_attr[\n"
     "        `#kgen.param.expr<target_has_feature,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"neon\"`,\n"
     "        `> : i1`]\n"
     "    return 0\n",
     "target_has_feature('neon') is a per-CPU question"),
    # A field this build has no source for. `triple` is the real one in the
    # stdlib (`_triple_attr` queries it), and the message names the field and
    # says which of the two facts the build does have would be needed.
    ("the_target_triple_is_not_stated",
     "def main():\n"
     "    var t = " + query("triple", "!kgen.string", "!kgen.string", "    ") + "\n"
     "    return 0\n",
     "has no 'triple' for this build to state"),
    # The target itself as a VALUE. Deliberately a different message from the
    # dialect attributes, and the reason is the useful one: the same target's
    # fields DO answer, so "there is no MLIR on this path" here would send the
    # reader looking for a missing MLIR instead of for a value with no
    # representation, and every `target_get_field` in the same file would look
    # like a contradiction.
    ("the_target_itself_is_not_a_value",
     "def main():\n"
     "    var t = __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`\n"
     "    return 0\n",
     "asks for the current TARGET itself, which is not a value"),
    # A `__mlir_type` template. It names a TYPE, and calling that an attribute
    # is a claim about the file that is false — `std/sys/info.mojo`'s
    # `_TargetType` is the one the whole family hangs on.
    ("an_mlir_type_template_is_a_type_not_an_attribute",
     "def main():\n"
     "    var t = __mlir_type.`!kgen.target`\n"
     "    return 0\n",
     "names an MLIR TYPE, not a value"),
    # A DIALECT attribute, which is the half of the family that was always a
    # true refusal and stays one. Kept in this file so the two halves cannot
    # drift into one rule: a QUESTION is answered, an attribute is not, and the
    # two need different repairs.
    ("a_dialect_attribute_is_still_refused",
     "def main():\n"
     "    var v = __mlir_attr.`#kgen.simd<1> : !kgen.scalar<ui8>`\n"
     "    return 0\n",
     "assembles an MLIR attribute from a template"),
    # An operand the build cannot fold: a RUNTIME parameter. The message quotes
    # the whole query with the hole spelled the way the author wrote it, rather
    # than the evaluator's internal `{0}` placeholder, because a diagnostic
    # about a source construct has to be findable in the source.
    ("an_operand_over_a_runtime_parameter",
     "def main(n: Int) -> Int:\n"
     "    var e = __mlir_attr[`#kgen.param.expr<eq,`, n, `, 2> : i1`]\n"
     "    return n\n",
     "an argument of the 'eq' query is neither a literal"),
    # A declared result type this path cannot lower. Refused rather than
    # materialized as something the source did not declare — which is what
    # makes "correct values" mean anything, since the declared type is the only
    # statement in the source of what the value IS.
    ("a_declared_result_type_is_not_lowered",
     "def main():\n"
     "    var v = __mlir_attr[\n"
     "        `#kgen.param.expr<target_get_field,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"pointer_width\" : index`,\n"
     "        `> : !kgen.scalar<2x2>`]\n"
     "    return 0\n",
     "this path has no type to lower that to"),
    # …and one the path CAN lower but that disagrees with the value, which is
    # the other half of the same cross-check: an `index` where the source
    # declared `!kgen.string` is a word in the wrong shape, not a small mistake.
    ("a_declared_result_type_that_disagrees_with_the_value",
     "def main():\n"
     "    var v = " + query("pointer_width", "index", "!kgen.string", "    ") + "\n"
     "    return 0\n",
     "declares a result of !kgen.string but evaluates to int"),
]

# The `Target` derivation itself, as unit checks over every (arch, fmt) the
# backend supports. Separate from the executed cases because an ELF image
# cannot be EXECUTED on a Mac, and "the OS follows the container format" is a
# claim about both formats. The expected values are stated here rather than read
# off the class under test, which is the whole point of the check — and `arch`
# is the one field that differs between the two rows, so these four together are
# what stops a hardcoded "aarch64".
DERIVATION = [
    ("target_arm64_macho", "arm64", "macho", "aarch64", "darwin"),
    ("target_x86_64_macho", "x86_64", "macho", "x86_64", "darwin"),
    ("target_arm64_elf", "arm64", "elf", "aarch64", "linux"),
    ("target_x86_64_elf", "x86_64", "elf", "x86_64", "linux"),
]

# A query under a call's KEYWORD argument — the exact shape
# `std/builtin/type_aliases.mojo` uses, `Origin[0, _mlir_origin=__mlir_attr[…]]()`
# — cannot be EXECUTED, and not because of this construct: a call with keyword
# arguments is refused earlier and separately, by the argument-matching rule
# (`constructing W with keyword argument(s) … is not a shape this path
# lowers`). So the walk is checked where it lives instead, in BOTH directions,
# because a tree walk that knows about lists but not tuples is wrong twice over:
# the REWRITE misses the query and the backend then refuses a construct the
# build answers, and the REFUSAL walk misses it and reports the module clean.
#
# (name, source of the whole module, want-replaced-in-a-kwarg)
KEYWORD_WALK = [
    ("a_folded_query_under_a_keyword_argument_is_replaced",
     "struct W:\n    var a: Int\n    var b: Int\n"
     "comptime Alias = W(0, b=" + query("pointer_width", "index", "index") + ")\n"
     "def main(n: Int) -> Int:\n    return n\n",
     "rewrite_left=0 refusal_walk_saw=0 module_refusal=none"),
    ("an_unanswerable_query_under_a_keyword_argument_is_still_reported",
     "struct W:\n    var a: Int\n    var b: Int\n"
     "comptime Alias = W(0, b="
     + query("triple", "!kgen.string", "!kgen.string") + ")\n"
     "def main(n: Int) -> Int:\n    return n\n",
     "rewrite_left=-1 refusal_walk_saw=-1 module_refusal=raised"),
]


def derivation_detail(arch, fmt, arch_field, os_field):
    t = M.target_for(arch, fmt)
    return (f"arch={t.field('arch')!r} os={t.field('os')!r} "
            f"endianness={t.field('endianness')!r} "
            f"pointer_width={t.numeric_field('pointer_width')!r} "
            f"simd_bit_width={t.numeric_field('simd_bit_width')!r} "
            f"cross={t.is_cross_compilation()}")


def derivation_want(arch, fmt, arch_field, os_field):
    # `cross` is stated as the comparison it IS rather than as a literal, so
    # this row is a check of the rule and not of a second hand-written table.
    cross = "False" if arch == platform.machine() else "True"
    return (f"arch={arch_field!r} os={os_field!r} endianness='little' "
            f"pointer_width=64 simd_bit_width=128 cross={cross}")


def keyword_walk_detail(source):
    """Apply both walks to a query under a keyword argument; report the outcome.

    Run in this process rather than through a build because the enclosing keyword
    call is refused earlier and for an unrelated reason; what is under test is
    the WALK, and a walk is a function of a tree. The report has three parts,
    one per way the walk can be wrong: it can leave an answerable query in the
    tree (`rewrite_left`), fail to reach an unanswerable one so the module is
    reported clean (`refusal_walk_saw`), or raise for an answerable one
    (`module_refusal`).
    """
    import formal.build as B
    M.publish_target(M.target_for("arm64", "macho"))
    stmts = B.parse_module(source, filename="kw.mojo")
    try:
        M.refuse_module_level_mlir_templates(stmts)
        refused = "none"
    except M.CodegenError:
        refused = "raised"
    # `_prepare_functions` asks the same question again, so it is reached only
    # when the answer was "no refusal" — which is itself the assertion: the
    # answerable case must get here, and the unanswerable one must not.
    if refused == "raised":
        left = seen = -1          # not reached; the refusal was the result
    else:
        # The fourth value is the unit's module-global slot table, which
        # `_prepare_functions` returns as well as publishes (a nested call for
        # an import publishes its own over ours). This pre-pass wants none of
        # them and says so by name.
        fns, _structs, _syms, _slots = B._prepare_functions(
            stmts, synthetic=False)
        left = sum(1 for fn in fns
                   for n in M.iter_nodes(getattr(fn, "body", None) or [])
                   if M.is_mlir_template(n))
        seen = 0
        for st in stmts:
            value = getattr(st, "value", None)
            if value is None or type(st).__name__ != "ComptimeVarStmt":
                continue
            seen += sum(1 for _n in M.iter_templates_preorder(value))
    return (f"rewrite_left={left} refusal_walk_saw={seen} "
            f"module_refusal={refused}")


def build(src, out, backend=None):
    """`fire.py build --formal --no-prove`, as a (returncode, output) pair."""
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(src)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_executed(name, source, want, tmpdir, verbose):
    """Build the arm64 image, EXECUTE it, and compare what it printed.

    arm64 only, for the reason `test_formal_run.py` is arm64-only: a formal
    x86-64 Mach-O needs Rosetta to launch on an arm64 Mac, and a suite that
    silently depended on that would be green on one machine and unrunnable on
    the next. The x86-64 half of the claim — that the two architectures get
    DIFFERENT answers — is the refused-with cases below, which build for both,
    plus the derivation rows, which state both.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, name)
    rc, text = build(src, out)
    if rc != 0:
        return False, text.strip()[-300:]
    if not os.path.isfile(out):
        return False, "build reported success but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if isinstance(want, str):
        if run.returncode != 0:
            return False, (f"exit status {run.returncode}, expected 0; stderr: "
                           f"{run.stderr.strip()[:160]}")
        if want not in run.stdout:
            return False, f"stdout {run.stdout[:160]!r} does not contain {want!r}"
    elif run.returncode != want:
        return False, f"exit status {run.returncode}, expected {want}"
    if verbose:
        print(f"      stdout={run.stdout.strip()!r} exit={run.returncode}")
    return True, ""


def run_refused(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        rc, text = build(src, os.path.join(tmpdir, f"{name}.{backend}"),
                         backend=backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct with no "
                           f"answer (expected a refusal naming {needle!r}); the "
                           f"binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-220:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    known = ({c[0] for c in EXECUTED} | {c[0] for c in REFUSED}
             | {c[0] for c in DERIVATION} | {c[0] for c in KEYWORD_WALK})
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2

    checks = []
    for name, source, want in KEYWORD_WALK:
        if args.cases and name not in args.cases:
            continue
        got = keyword_walk_detail(source)
        checks.append((name, got == want, f"{got} != {want}"))

    for name, arch, fmt, arch_field, os_field in DERIVATION:
        if args.cases and name not in args.cases:
            continue
        got = derivation_detail(arch, fmt, arch_field, os_field)
        want = derivation_want(arch, fmt, arch_field, os_field)
        checks.append((name, got == want, f"{got} != {want}"))

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, want in EXECUTED:
            if args.cases and name not in args.cases:
                continue
            try:
                ok, detail = run_executed(name, source, want, tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            checks.append((name, ok, detail))
        for name, source, needle in REFUSED:
            if args.cases and name not in args.cases:
                continue
            try:
                ok, detail = run_refused(name, source, needle, tmpdir,
                                         args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            checks.append((name, ok, detail))

    passed = failed = 0
    for name, ok, detail in checks:
        if ok:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}: {detail}")

    print(f"\ntarget queries: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
