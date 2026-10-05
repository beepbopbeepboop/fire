#!/usr/bin/env python3
"""Which emitted instruction forms are actually CHECKED, on both backends.

`bugs/FORMAL_arm64_instruction_coverage.md` is a survey with a number in it, and
the number answers one question: *what can this backend not emit?* This tool
answers the other four, for every instruction form the code generators CAN emit:

    LEAN   does the machine model give this form semantics?
    FUZZ   does the model-vs-hardware fuzzer run it against the CPU?
    AS     is there a byte-for-byte differential against the platform assembler?
    EX     does it appear in at least one proved example?

The unit is the EMITTED FORM, and "emitted" means a call site: an `encode_*`
that some emitter (a backend's `codegen.py`, or the Mach-O linker's stub)
references. That is the same distinction the survey's 2026-10-03 method change
made and it is the reason this tool exists at all — an encoder nothing calls is
byte-exact, has a Lean arm, and cannot occur in an image, so counting it in any
of the four columns would over-report all of them at once.

**Each column names the thing it reads, because a column that cannot say where
its answer came from is not a measurement.**

  LEAN, arm64   `formal/arm64_proof_gen.py`'s `_STEP_CONDS` — the generator's
                table of `arm64_step` branches. It is the right table to read
                because `check_step_conds()` re-derives it from
                `lib/ProofLib.lean`'s if-chain and raises if the two disagree,
                and this tool CALLS that check before reading it, so a drifted
                mirror cannot answer the question here. The answer is whether
                the encoder's canonical word matches any branch.
  LEAN, x86-64  `formal/x86_64_model_coverage_test.py::samples()`: a form is
                `asked` when that file has a sample of it, because that test's
                whole job is to hand every sample to `x86_step` and ask. The
                VERDICT is the registered `formal-x86-model` job, which is a
                Lean run this tool does not duplicate; what is asserted here is
                the weaker and still-useful fact that the question is asked of
                every emitted form rather than of the ones a corpus happens to
                use. The decoder is asked too (`formal/x86_64_decode.py`), and a
                sample that does not decode is reported as `NO DECODE`, because
                a form the decoder refuses is a form nothing downstream can
                name.
  FUZZ         an AST walk of the fuzzer's POOL (`tools/formal_model_fuzz.py`,
                `formal/x86_64_model_fuzz.py`) for `A.encode_*` / `X.encode_*`
                attribute references, counted separately for the random pool
                and the per-form census. AST rather than grep because a
                docstring mentioning an encoder is not coverage.
  AS           the same AST walk, restricted to the encoder test's CASE TABLE
                (`test_arm64_encoders.py::cases` plus its `equivalent_cases`,
                `test_x86_64_encoders.py::CASES` and the two lists its table is
                generated from), which is the part that compares against `as`.
                restriction matters: both files also call encoders to assert
                that they REFUSE out-of-range arguments, which is a real check
                and not a differential.
  EX           not measured by default. `--examples` compiles the proved corpus
                for both backends and records the forms each image contains
                into `tools/formal_isa_census_examples.json`; without that file
                the column prints `?` rather than a false `no`.

**A canonical word per encoder is what makes LEAN askable at all**, so the
sampler is part of the tool rather than a table copied out of a test: encoder
arguments come from `ARM64_ARGS` / `X86_ARGS` (names -> operand classes) with an
override table for the handful that do not fit a rule. A form the sampler cannot
instantiate prints `sample?` with the exception, because "the census cannot even
call this encoder" is a finding and not something to hide behind a default.

`EXCLUSIONS` is the list of forms that cannot satisfy a column, each with the
reason it is a decision rather than a gap, and the reasons are printed. It is
duplicated nowhere: `test_formal_isa_census.py` imports it from here, so the
matrix and the test cannot disagree about what is exempt.

Usage:
    python3 tools/formal_isa_census.py                    # both backends
    python3 tools/formal_isa_census.py --arch arm64
    python3 tools/formal_isa_census.py --json             # machine-readable
    python3 tools/formal_isa_census.py --examples         # builds the corpus
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

EXAMPLES_CACHE = os.path.join(HERE, "formal_isa_census_examples.json")


def _read(path):
    """A file's text, closed — this tool opens eleven of them per run and a
    bare `open(...).read()` leaves the warning behind on every one."""
    with open(path, encoding="utf-8") as f:
        return f.read()

# ── the four columns, and what each one reads ──────────────────────────────

LEVER_ROOTS = {
    "arm64": ("formal/arm64_codegen.py", "formal/macho_linker.py"),
    "x86_64": ("formal/x86_64_codegen.py", "formal/macho_linker.py"),
}
"""The files whose `encode_*` references make a form EMITTED.

A backend's `codegen.py` is the emitter proper; `macho_linker.py` emits the
three-instruction entry stub (`adrp`/`ldr`/`br` on arm64, a `jmp` on x86-64),
which lands in the same images, so a form only it uses is still a form an image
can contain. Nothing else counts: the proof generators, the model-coverage
test and the fuzz harnesses all NAME encoders, and treating those references as
emission is how an encoder nothing calls reads as an instruction.
"""


# ── canonical words: the samplers ──────────────────────────────────────────
#
# Register numbers 3..6 and immediates chosen to be legal for the field they go
# in, deliberately NOT 31 for a destination (register 31 is XZR in `Rd`, which
# several encoders must refuse) and 31 for a memory BASE, which is SP: the fuzz
# harnesses anchor their comparison window at SP, so an access through SP is the
# one address the CPU and the model can be made to agree about.
_ARM64_MEMORY = re.compile(r"^(encode_(?:ld|str)[a-z]*_|encode_ldur|"
                           r"encode_stur|encode_ldp|encode_stp)")

#: `encoder -> args`, overriding the name rules below. One line per encoder
#: whose operands are not `(a register, a register, an immediate)`-shaped.
_ARM64_OVERRIDES = {
    "encode_adrp": (0, 0x1000),
    "encode_br_xn": (3,),
    "encode_blr_xn": (16,),
    "encode_svc": (0,),
    "encode_b": (8,),
    "encode_bl": (8,),
    "encode_cbz_xn": (8, 3),
    "encode_cbnz_xn": (8, 3),
    "encode_stp_sp_pre": (0, 1, 16),
    "encode_ldp_sp_post": (0, 1, 16),
    "encode_ret": (),
    "encode_cset_xd_cond": (0, "eq"),
    "encode_b_cond": ("eq", 8),
    "encode_csel_xd_xm_cond": (0, 3, 4, "eq"),
    "encode_tbz_xn_bit": (3, 4, 8),
    "encode_tbnz_xn_bit": (3, 4, 8),
    "encode_and_xd_xn_imm": (0, 3, 8),
    "encode_movk_xd_imm": (0, 0x1234, 16),
    "encode_movz_xd_imm": (0, 0x1234),
    "encode_movz_wd_imm": (0, 0x1234),
    "encode_sub_xd_xn_imm_sh": (0, 3, 32, 1),
    "encode_add_xd_xn_imm_sh": (0, 3, 32, 1),
    "encode_msub_xd_xn_xm_xa": (0, 3, 4, 5),
    "encode_fcmp_dn_dm": (0, 1),
    "encode_fneg_dd_dn": (0, 1),
    "encode_fmov_gpr_to_v": (0, 3),
    "encode_fmov_v_to_gpr": (0, 1),
    "encode_scvtf_dn_xn": (0, 1),
    "encode_fcvtzs_xn_dn": (0, 1),
}
_ARM64_REG_ARGS = {
    "xd": 0, "wd": 0, "xt": 0, "wt": 0, "rd": 0, "dd": 0,
    "xn": 3, "wn": 3, "xm": 4, "rm": 4, "rt1": 0, "rt2": 1, "xa": 5,
    "dn": 1, "dm": 2,
}
_ARM64_IMM_ARGS = {
    "imm16": 0x1234, "imm12": 8, "imm9": -8, "imm8": 0, "imm": 8,
    "offset": 8, "bit": 3, "shift": 5, "sh": 1, "pos": 16, "width": 8,
    "b": 16, "page_offset": 0x1000,
}

#: x86-64: `Reg` arguments by parameter name, and immediates by encoder name
#: (the name is the only thing that says whether an `imm` goes in an imm8 or an
#: imm32 field, and getting that wrong is an encoder-range error, not a sample).
_X86_REGS = {"base": "R13", "src": "R11", "dst": "R10", "r1": "R10", "r2": "R11",
             "reg": "R10"}
_X86_IMM = {
    "encode_mov_r64_imm32": 1000, "encode_imul_r64_r64_imm": 7,
    "encode_add_r64_imm32": 1000, "encode_and_r64_imm32": 1000,
    "encode_sub_r64_imm32": 1000, "encode_cmp_r64_imm32": 1000,
    "encode_add_r64_imm8": 8, "encode_and_r64_imm8": 8,
    "encode_sub_r64_imm8": 8, "encode_cmp_r64_imm8": 8,
    "encode_shift_r64_imm8": 5,
    "encode_mov_r64_imm64": 0x1122334455667788,
    "encode_movabs_r64": 0x1122334455667788,
    "encode_je_rel8": 8, "encode_jne_rel8": 8, "encode_jmp_rel8": 8,
    "encode_jmp_rel32": 8, "encode_jne_rel32": 8, "encode_call_rel32": 8,
    "encode_jmp_rm64": 8, "encode_lea_r64_rip": 8,
}
_X86_IMM32 = (1000, -7, 8, 64, 4096, 0x410)


def _x86_args(name, params):
    """Operands for one x86-64 encoder, from `(name, annotation)` pairs.

    The annotation is what separates the two argument kinds in this module: a
    `Reg` parameter wants a `Reg` and an `int` parameter wants an integer, and
    passing the wrong one is a `struct.error` from inside the encoder rather
    than anything that names the mistake.
    """
    import formal.x86_64 as X
    args = []
    imm = _X86_IMM.get(name, 0)
    for pname, ann in params:
        if "Reg" in ann:
            args.append(getattr(X.Reg, _X86_REGS.get(pname, "R10")))
        elif pname == "op":
            args.append("<<")
        elif pname == "cc":
            args.append(1)
        elif pname == "xmm":
            args.append(1)
        else:
            args.append(imm)
    return args


def sample_args(arch, name, func):
    """The canonical operand tuple for one encoder, or None if there is none."""
    import inspect
    params = [(p.name, str(p.annotation))
              for p in inspect.signature(func).parameters.values()]
    names = [p for p, _a in params]
    if arch == "arm64":
        if name in _ARM64_OVERRIDES:
            args = list(_ARM64_OVERRIDES[name])
            assert len(args) == len(names), (name, names, args)
            return args
        memory = bool(_ARM64_MEMORY.match(name))
        out = []
        for p in names:
            if p in _ARM64_REG_ARGS:
                out.append(31 if (memory and p in ("xn", "wn"))
                           else _ARM64_REG_ARGS[p])
            elif p in _ARM64_IMM_ARGS:
                out.append(_ARM64_IMM_ARGS[p])
            else:
                return None
        return out
    return _x86_args(name, params)


# ── encoders, emitters, and the AST reads ──────────────────────────────────

def encoder_names(arch):
    """Every `encode_*` defined in the backend's encoder module, in file order."""
    src = _read(os.path.join(ROOT, "formal", "%s.py" % arch))
    return re.findall(r"^def (encode_[A-Za-z0-9_]+)", src, re.M)


def call_sites(arch):
    """{encoder: [(file, count)]} over the emitter files only."""
    for rel in LEVER_ROOTS[arch]:
        blob = _read(os.path.join(ROOT, rel))
    out = {}
    for name in encoder_names(arch):
        hits = []
        for rel in LEVER_ROOTS[arch]:
            n = len(re.findall(r"\b%s\b" % re.escape(name),
                               _read(os.path.join(ROOT, rel))))
            if n:
                hits.append((os.path.basename(rel), n))
        out[name] = hits
    return out


#: The names whose VALUES are the encoder test's byte-differential table.
#:
#: `test_arm64_encoders.py` builds its table in one function; the x86 file
#: assembles the same table from three module-level names (the generated SSE
#: rows come from `_FP_OPS` x `_FP_PAIRS`), so restricting the walk to one of
#: them reports the whole generated block as uncovered. Naming the three is
#: more precise than walking the file, which would also pick up the range and
#: XZR assertions — real checks, but not byte comparisons.
AS_TABLES = {"arm64": ["cases", "equivalent_cases"],
             "x86_64": ["CASES", "REX_VARIANT_CASES", "_FP_PAIRS", "_FP_OPS"]}


def _ast_encoder_refs(path, tables=None):
    """`{encoder}` referenced as `X.encode_*` inside the named scopes, by AST.

    `tables` is a list of names — functions (`cases`) or module-level
    assignments (`CASES`, `_FP_OPS`) — and restricting the walk to them is what
    keeps "this encoder has a byte-for-byte differential against `as`" separate
    from "this encoder is called somewhere in the file", which in both encoder
    tests is also true of the range checks that assert an encoder REFUSES its
    out-of-range arguments. AST rather than grep because a docstring mentioning
    an encoder is not coverage.

    A `getattr(MOD, "encode_set" + nm)` is resolved too, because
    `formal/x86_64_model_fuzz.py` builds its ten `setcc` entries that way
    (`_SETCC = tuple((nm, getattr(X, "encode_set" + nm)) for nm in (...))`) and
    a walk that only saw attribute reads reported every one of them as a gap the
    pool does not draw. The resolution is by the string literals that feed the
    comprehension, so the ten names come from the tuple and not from a prefix
    match — `setnp`/`setp` are deliberately NOT in that tuple (the model does
    not evaluate parity) and a prefix rule would have claimed them.
    """
    tree = ast.parse(_read(path))
    scopes = []
    wanted = set(tables or ())
    for node in ast.walk(tree):
        if not wanted:
            scopes.append(node)
            continue
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            scopes.extend(ast.walk(node))
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in wanted for t in node.targets):
            scopes.append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(
                node.target, ast.Name) and node.target.id in wanted:
            # `CASES += [...]` is half of `test_x86_64_encoders.py`'s table (the
            # generated SSE and byte-ALU rows), so a walk that only read the
            # first assignment reported the whole generated block as uncovered.
            scopes.append(node.value)
    found = set()
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.Attribute) and node.attr.startswith("encode_"):
                found.add(node.attr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "getattr" and len(node.args) == 2:
                found |= _resolve_getattr(node, scope)
    return found


def _resolve_getattr(call, scope):
    """The encoder names a `getattr(MOD, "encode_" + name)` call can produce.

    Only the comprehension that binds `name` counts, and only when its iterable
    is a literal tuple/list of strings — which is the shape both harnesses use
    and the only one that can be resolved without guessing.
    """
    expr = call.args[1]
    if not (isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add)
            and isinstance(expr.left, ast.Constant)
            and isinstance(expr.left.value, str)
            and isinstance(expr.right, ast.Name)):
        return set()
    prefix, var = expr.left.value, expr.right.id
    out = set()
    for node in ast.walk(scope):
        if not isinstance(node, (ast.ListComp, ast.GeneratorExp)):
            continue
        targets = [t.id for gen in node.generators for t in ast.walk(gen.target)
                   if isinstance(t, ast.Name)]
        if var not in targets or not isinstance(node.generators[0].iter,
                                                (ast.Tuple, ast.List)):
            continue
        for elt in node.generators[0].iter.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.add(prefix + elt.value)
    return out


def _arm64_fuzz_refs():
    path = os.path.join(HERE, "formal_model_fuzz.py")
    return _ast_encoder_refs(path)


def _x86_fuzz_refs():
    path = os.path.join(ROOT, "formal", "x86_64_model_fuzz.py")
    return _ast_encoder_refs(path)


def _delegating_encoders(arch):
    """`{encoder: {encoders that build the same instruction}}`.

    A one-line encoder whose body is a single call is the SAME instruction as
    whatever it calls, up to a constant argument: `encode_je_rel8(offset)` is
    `encode_jcc_rel8(COND_E, offset)`, and both of those bottom out in the
    private `_jcc_rel8`. So a pool that draws `jcc` over all fourteen condition
    codes already runs the instruction `encode_je_rel8` emits, and counting that
    as uncovered would make the FUZZ column report a gap where the fuzzer is
    covering the form — a column that cries wolf is a column nobody reads.

    Both relations are in the one map, because the private helper is the join:
    an encoder's dependencies are the `encode_*` it calls plus every other
    encoder that calls the same private helper. Only a body that is ONE call
    counts; an encoder with arithmetic of its own computes something else and is
    left to answer for itself.
    """
    src = _read(os.path.join(ROOT, "formal", "%s.py" % arch))
    tree = ast.parse(src)

    def callee(node):
        body = [n for n in node.body
                if not (isinstance(n, ast.Expr)
                        and isinstance(n.value, ast.Constant))]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            return None
        call = body[0].value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            return call.func.id
        return None

    deps = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith(
                "encode_"):
            continue
        target = callee(node)
        if target:
            deps.setdefault(target, set()).add(node.name)
    out = {name: set() for name in
           (n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("encode_"))}
    for target, users in deps.items():
        for name in users:
            out[name] |= users - {name}
        if target.startswith("encode_"):
            for name in users:
                out[name].add(target)
    return out


def _as_refs(arch):
    test = {"arm64": "test_arm64_encoders.py", "x86_64": "test_x86_64_encoders.py"}[arch]
    return _ast_encoder_refs(os.path.join(ROOT, test), AS_TABLES[arch])


# ── the LEAN column ────────────────────────────────────────────────────────

def _arm64_step_index(word):
    """The `arm64_step` branch that matches `word`, or None."""
    import formal.arm64_proof_gen as G
    return G._step_branch_index(word)


def _arm64_step_branches():
    """`[(index, name)]` for every `_STEP_CONDS` entry, so a gap can be NAMED.

    The name comes from the entry's own comment — the table annotates every row
    with the instruction it is (`# 18 STR`), and naming the branch a word lands
    in is what turns "LEAN: no" into "LEAN: no, and the branches that exist are
    …". A comment ABOVE the tuple (the appended rows have one, the older ones
    have theirs on the line) is read as the nearest preceding comment line,
    which is why this walks the block rather than regexing per row.
    """
    src = _read(os.path.join(ROOT, "formal", "arm64_proof_gen.py"))
    block = re.search(r"^_STEP_CONDS = \[(.*?)^\]", src, re.M | re.S).group(1)
    entry = re.compile(r"^\s*\((?:None|0x[0-9a-fA-F]+),\s*(?:None|0x[0-9a-fA-F]+)\)")
    out, index, last_comment = [], -1, ""
    for line in block.splitlines():
        if line.lstrip().startswith("#"):
            last_comment = line.split("#", 1)[1].strip()
            continue
        if not entry.match(line):
            continue
        index += 1
        name = ""
        if "#" in line:
            name = line.split("#", 1)[1].strip()
        elif last_comment:
            name = last_comment
        out.append((index, name))
    return out


def _x86_coverage_forms():
    """{form} for every sample `formal/x86_64_model_coverage_test.py` asks about."""
    import formal.x86_64_decode as D
    import formal.x86_64_model_coverage_test as C
    forms = set()
    for _form, _label, enc in C.samples():
        try:
            forms.add(D.decode_one(bytes(enc), 0).form)
        except D.DecodeError:
            pass
    return forms


def _x86_form(sample):
    import formal.x86_64_decode as D
    try:
        return D.decode_one(bytes(sample), 0).form
    except D.DecodeError as e:
        return "NO DECODE: %s" % e


# ── the two kinds of form that cannot have a column ────────────────────────
#
# `HARNESS_LIMITS` is a permanent answer: the form cannot be run by this
# harness, or cannot be compared across two engines that disagree about an
# address, for a reason that is a property of the HARNESS rather than of work
# nobody has done. `BACKLOG` is the other kind — a real gap, tracked by a bug
# doc, which is what a reader wants to know when a column says `NO`.
#
# Both are printed with the matrix, because an exclusion nobody can see is not
# one, and both are imported by `test_formal_isa_census.py`, so the matrix and
# the test cannot disagree about what is exempt. The test additionally requires
# every `BACKLOG` doc to exist AND requires every entry to still name a form the
# census reports as missing, so an entry cannot outlive the gap it describes.

HARNESS_LIMITS = {
    # ── arm64: the harness cannot run the form, or cannot compare it ──────
    "encode_adrp": "the two engines' PCs differ by the load slide, so a "
                   "pc-relative RESULT cannot be compared; the harness "
                   "compares pc DELTAS only",
    "encode_bl": "X30 is `pc + 4` — a pc-RELATIVE value the two engines "
                 "cannot share — and the harness dumps X30. `BL` itself is "
                 "in the pool (`tools/formal_model_fuzz.py`'s `branch` mix)",
    "encode_svc": "SVC traps in EL0 on this platform: the case is a FAULT "
                  "before the state can be compared. The model does have an "
                  "arm (a no-op), and the encoder-vs-`as` check is what "
                  "covers it",
    "encode_blr_xn": "a branch through a REGISTER has no target either "
                     "engine can be given, so a case would leave the harness's "
                     "stub rather than fall through",
    "encode_br_xn": "as `encode_blr_xn`: the target is a register",
    "encode_ret": "as `encode_blr_xn`: `ret` jumps to X30, which the harness "
                  "installs as a case value",
    "encode_stp_sp_pre": "the write-back pairs move SP, which is the anchor of "
                         "the harness's comparison window (measured: 28 "
                         "SIGBUS in a 297-case sweep, every one the harness's "
                         "fault). `arm64_step` has an arm for each",
    "encode_ldp_sp_post": "as `encode_stp_sp_pre`: an SP write-back moves the "
                          "window",
    # The IEEE-754 forms are BOTH kinds at once and are listed under BACKLOG
    # for the model half; the harness half is this: it installs and dumps
    # X0-X30, NZCV and memory, and has no V register file at all.
    "encode_leave": "`x86_step` steps it and `as` checks it; the fuzzer's "
                    "harness cannot run it because `leave` reads the frame "
                    "pointer, which the harness does not install",
    "encode_movabs_r64": "the backend never selects the imm64 form for an "
                         "immediate that `mov rm64, imm32` can express, and "
                         "`as` spells some of its values the other way; the "
                         "byte check is `test_x86_64_encoders.py`'s own",
    "encode_jne_rel32": "a second spelling of `jcc_rel32`'s instruction "
                        "(cc = 1); the fuzz pool draws every condition code "
                        "through `encode_jcc_rel32`, and the census's wrapper "
                        "rule does not follow a body that is not one call",
    "encode_jmp_rm64": "`jmpq *[rip+disp32]` jumps to an ABSOLUTE address the "
                       "harness cannot install, so a case leaves the "
                       "generated stub — the same reason as arm64's "
                       "`encode_br_xn`",
}

#: `encoder -> (bug doc, what the gap is)`. Every doc named here must exist:
#: the test checks, which is what makes a fixed gap delete its entry rather
#: than leave a stale "known problem" behind.
BACKLOG = {
    # ── arm64: emitted, and `arm64_step` has no arm for it ────────────────
    "encode_smulh_xd_xn_xm": (
        "bugs/FORMAL_arm64_smulh_has_no_model_arm.md",
        "the high half of a signed multiply; emitted for the overflow check "
        "(`formal/model.py::int_overflow_traps`) and modelled nowhere. The "
        "fuzz pool DOES draw it, so a case that does is a NOSTEP"),
    "encode_csel_xd_xm_cond": (
        "bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md",
        "six call sites emit it and `arm64_step` has no branch; the blocked "
        "reason is measured in that doc (the certificate size, not the "
        "instruction)"),
    "encode_fadd_dd_dn_dm": (
        "bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
        "IEEE-754 binary64, scalar: ten encoders the emitter calls, no arm in "
        "`arm64_step`, and no V register file in the harness"),
    "encode_fsub_dd_dn_dm": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                             "as `encode_fadd_dd_dn_dm`"),
    "encode_fmul_dd_dn_dm": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                             "as `encode_fadd_dd_dn_dm`"),
    "encode_fdiv_dd_dn_dm": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                             "as `encode_fadd_dd_dn_dm`"),
    "encode_fneg_dd_dn": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                          "as `encode_fadd_dd_dn_dm`"),
    "encode_fcmp_dn_dm": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                         "as `encode_fadd_dd_dn_dm`; the one whose FLAGS the "
                         "floating comparison is decided from"),
    "encode_fmov_gpr_to_v": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                             "as `encode_fadd_dd_dn_dm`"),
    "encode_fmov_v_to_gpr": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                             "as `encode_fadd_dd_dn_dm`"),
    "encode_scvtf_dn_xn": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                           "as `encode_fadd_dd_dn_dm`"),
    "encode_fcvtzs_xn_dn": ("bugs/FORMAL_arm64_ieee754_has_no_step_arms.md",
                            "as `encode_fadd_dd_dn_dm`"),
    # ── x86-64: the forms the harness cannot even NAME ───────────────────
    "encode_movq_xmm_rm64": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "the GPR-to-XMM move the floating `printf` path needs; `x86_step` "
        "steps it but `formal/x86_64_model_coverage_test.py` has no sample, "
        "so the model is never asked"),
    "encode_imul_r64_r64_imm": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "`69 /r id`: no decoder arm (only `0F AF` is decoded) and no pool or "
        "coverage entry"),
    "encode_call_r64": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "`FF /2` with mod=11, the call through a function VALUE; the decoder "
        "maps `FF` only to `FF 15`/`FF 25`"),
    "encode_and_r8_r8": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "the byte-wise `and` the floating compare needs (no REX.W, so the "
        "decoder's REX.W-only ALU arm does not reach it)"),
    "encode_or_r8_r8": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "as `encode_and_r8_r8`"),
    "encode_addsd_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                         "SSE2 scalar binary64: nine encoders the emitter "
                         "calls, with no decoder arm, no model sample and no "
                         "pool entry"),
    "encode_subsd_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                         "as `encode_addsd_xmm`"),
    "encode_mulsd_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                         "as `encode_addsd_xmm`"),
    "encode_divsd_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                         "as `encode_addsd_xmm`"),
    "encode_ucomisd_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                           "as `encode_addsd_xmm`; the compare whose unordered "
                           "case has its own flags"),
    "encode_xorpd_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                         "as `encode_addsd_xmm`"),
    "encode_movq_r64_xmm": ("bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
                            "as `encode_addsd_xmm`"),
    "encode_cvtsi2sd_xmm_r64": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "as `encode_addsd_xmm`"),
    "encode_cvttsd2si_r64_xmm": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "as `encode_addsd_xmm`"),
    # ── x86-64: runnable, and the pool does not draw them ────────────────
    "encode_lea_r64_rip": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "RIP-relative `lea`: the two engines' RIPs differ by the load slide, so "
        "it belongs beside `encode_adrp` in HARNESS_LIMITS rather than in the "
        "pool until the harness translates it"),
    "encode_jcc_rel32": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "the pool draws only the rel8 branch; the rel32 spelling is what "
        "`formal/x86_64_codegen.py` emits past a 128-byte reach"),
    "encode_jmp_rel32": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "as `encode_jcc_rel32`"),
    "encode_call_rel32": (
        "bugs/FORMAL_x86_64_instruction_coverage_backlog.md",
        "a call cannot run in the harness's straight-line stub without leaving "
        "it; the model-vs-hardware comparison needs a form the harness can "
        "keep control of"),
}


def exclusion_reason(name):
    """The reason a form is exempt, and which KIND of exemption it is."""
    if name in HARNESS_LIMITS:
        return HARNESS_LIMITS[name], "harness"
    if name in BACKLOG:
        doc, why = BACKLOG[name]
        return "%s — tracked in %s" % (why, doc), "backlog"
    return None, None


# ── the census ─────────────────────────────────────────────────────────────

class Row(object):
    """One emitted form and its four columns."""

    __slots__ = ("arch", "encoder", "emitted_in", "sample", "sample_error",
                 "lean", "lean_detail", "fuzz", "as_check", "example")

    def __init__(self, arch, encoder, emitted_in):
        self.arch = arch
        self.encoder = encoder
        self.emitted_in = emitted_in
        self.sample = None
        self.sample_error = ""
        self.lean = False
        self.lean_detail = ""
        self.fuzz = False
        self.as_check = False
        self.example = None

    @property
    def excluded(self):
        return self.encoder in HARNESS_LIMITS or self.encoder in BACKLOG

    @property
    def exclusion(self):
        return exclusion_reason(self.encoder)

    def missing(self):
        return [c for c in ("lean", "fuzz", "as_check")
                if not getattr(self, c)]

    def as_dict(self):
        return {"arch": self.arch, "encoder": self.encoder,
                "emitted_in": [f for f, _n in self.emitted_in],
                "lean": self.lean, "lean_detail": self.lean_detail,
                "fuzz": self.fuzz, "as_check": self.as_check,
                "example": self.example, "excluded": self.excluded}


def census(arch, examples_cache=None):
    """`[Row]` for every EMITTED form, in encoder-table order.

    `examples_cache` is the parsed `formal_isa_census_examples.json`, or None;
    without it the EX column stays unmeasured, which is what `?` in the report
    means.
    """
    if arch == "arm64":
        import formal.arm64 as mod
        # The mirror table is only worth reading if it still matches the Lean
        # model, and `check_step_conds` is the function that knows. Raising here
        # is the point: a drifted `_STEP_CONDS` would answer LEAN from a table
        # the model no longer has.
        import formal.arm64_proof_gen as G
        G.check_step_conds()
        fuzz_refs = _arm64_fuzz_refs()
        branch_names = dict(_arm64_step_branches())
    else:
        import formal.x86_64 as mod
        fuzz_refs = _x86_fuzz_refs()
        coverage = _x86_coverage_forms()
    as_refs = _as_refs(arch)
    # An encoder the pool reaches THROUGH a wrapper it does draw is covered:
    # `encode_je_rel8` builds what `encode_jcc_rel8` builds at cc = 0, and the
    # pool draws every condition code. Two rounds, because the relation is not
    # transitive in one step (`encode_je_rel8` shares the private `_jcc_rel8`
    # with `encode_jcc_rel8`, and only the latter is named in the pool).
    delegating = _delegating_encoders(arch)
    for _round in (0, 1):
        fuzz_refs = fuzz_refs | {name for name, deps in delegating.items()
                                 if deps & fuzz_refs}
    sites = call_sites(arch)
    ex_forms = (examples_cache or {}).get(arch, {})

    rows = []
    for name in encoder_names(arch):
        sites_here = sites.get(name) or []
        if not sites_here:
            continue                      # not emitted: not an instruction
        row = Row(arch, name, sites_here)
        try:
            args = sample_args(arch, name, getattr(mod, name))
            row.sample = bytes(getattr(mod, name)(*args))
        except Exception as e:                        # noqa: BLE001
            row.sample_error = "%s: %s" % (type(e).__name__, e)
        word = None
        if row.sample is not None and len(row.sample) == 4:
            word = int.from_bytes(row.sample, "little")
        if arch == "arm64":
            idx = _arm64_step_index(word) if word is not None else None
            row.lean = idx is not None
            row.lean_detail = ("arm64_step branch %d (%s)"
                               % (idx, branch_names.get(idx, "?"))) if idx is not None \
                else ("no arm64_step branch matches" if word is not None
                      else "no sample")
        else:
            form = _x86_form(row.sample) if row.sample is not None else "NO SAMPLE"
            row.lean = form in coverage
            row.lean_detail = "%s; %s" % (
                form, "asked by formal/x86_64_model_coverage_test"
                if row.lean else "NOT asked by formal/x86_64_model_coverage_test")
        row.fuzz = name in fuzz_refs
        row.as_check = name in as_refs
        row.example = ex_forms.get(name)
        rows.append(row)
    return rows


# ── the EX column, measured ────────────────────────────────────────────────

def measure_examples(arch, out_path=EXAMPLES_CACHE, limit=None):
    """Build the proved corpus for `arch` and record the forms in each image.

    Writes `formal_isa_census_examples.json` (merged, so one arch at a time
    accumulates). A compile of a `formal/examples/*.mojo` is small — the proof
    census measures 0.06 GB for the compile half — and it is the only way to
    answer "does any PROVED example contain this form", since the answer is a
    property of the images and not of any table.
    """
    import formal.build as FB
    import formal.lean as L

    cache = _load_examples(out_path)
    cache.setdefault(arch, {})
    examples = sorted(f[:-5] for f in os.listdir(
        os.path.join(ROOT, "formal", "examples")) if f.endswith(".mojo"))
    if limit:
        examples = examples[:limit]
    built = 0
    with L.scratch_dir("isa-census-table") as table_dir:
        table = _encoder_mnemonics(arch, table_dir)
        if not table:
            sys.stderr.write("  no canonical encodings could be assembled for "
                             "%s; the EX column stays unmeasured\n" % arch)
            return 0, cache
    for stem in examples:
        source = os.path.join(ROOT, "formal", "examples", stem + ".mojo")
        try:
            with L.scratch_dir("isa-census") as work:
                out = os.path.join(work, stem + ".aout")
                result = FB.compile_formal(source, output=out, prove=False,
                                           check=False, arch=arch)
                built += 1
                for _mn, encoder in _forms_in_image(arch, result["path"],
                                                     work, table):
                    cache[arch].setdefault(encoder, []).append(stem)
        except Exception as e:                        # noqa: BLE001
            sys.stderr.write("  %s: %s\n" % (stem, e))
    cache[arch] = {k: sorted(set(v)) for k, v in cache[arch].items()}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    return built, cache


def _load_examples(path=EXAMPLES_CACHE):
    """The EX cache, or `{}` when it has never been measured."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _image_mnemonics(path):
    """`{mnemonic}` for every instruction `otool` finds in an image.

    The platform's own disassembler, for the same reason `tools/
    arm64_insn_audit.py` uses one: it names the INSTRUCTION, where an encoder
    comparison names the WORD, and the two are not the same thing on this
    backend (`encode_mov_zr_xn` emits `add x0, x1, #0` for a `mov`). Reading the
    mnemonic out of the disassembly is also the only way to answer "is this form
    in this image" without a mask per encoder: a mask would have to be derived
    from the very bit layout under test, so an encoder with a field in the wrong
    place would produce a mask describing the wrong place and agree with itself.
    """
    out = subprocess.run(["otool", "-tv", path], capture_output=True,
                         text=True).stdout
    found = set()
    for line in out.splitlines():
        m = re.match(r"^[0-9a-f]{8,16}\s+(\S+)", line)
        if m:
            found.add(m.group(1))
    return found


def _encoder_mnemonics(arch, workdir):
    """`{encoder: mnemonic}`, from the assembler, one batch for every encoder.

    The mnemonic is the FIRST TOKEN of the disassembly, with the condition code
    kept (`b.eq` stays `b.eq`, because `cset`/`b.cond` are different forms of one
    mnemonic and merging them would make the census claim a `CSET` image covers
    a `B.cond` gap).
    """
    import formal.arm64 as A
    import formal.x86_64 as X
    mod = A if arch == "arm64" else X
    words, names = [], []
    for name in encoder_names(arch):
        try:
            args = sample_args(arch, name, getattr(mod, name))
            raw = bytes(getattr(mod, name)(*args))
        except Exception:                             # noqa: BLE001
            continue
        if len(raw) != 4:
            continue
        words.append(int.from_bytes(raw, "little"))
        names.append(name)
    if not words:
        return {}
    src = os.path.join(workdir, "canon.s")
    obj = os.path.join(workdir, "canon.o")
    # `.inst 0x…` is arm64 assembler syntax; x86-64 wants the bytes. Emitting the
    # arm64 spelling into the x86 file makes clang reject the whole batch, which
    # is how the x86 EX column read as "no canonical encodings could be
    # assembled" — a pool of zero rows rather than a measurement.
    body = ("".join("\t.inst 0x%08x\n" % w for w in words) if arch == "arm64"
            else "".join("\t.byte " + ", ".join("%d" % b for b in
                                               w.to_bytes(4, "little")) + "\n"
                         for w in words))
    with open(src, "w", encoding="utf-8") as f:
        f.write(".text\n" + body)
    # `as -arch x86_64` is not a thing on this toolchain; clang's integrated
    # assembler is, and it is what `test_x86_64_encoders.py` uses for the same
    # comparison, so the oracle is the same one on both sides.
    argv = (["clang", "-arch", "x86_64", "-c", src, "-o", obj]
            if arch == "x86_64" else ["as", "-arch", arch, "-o", obj, src])
    if subprocess.run(argv, capture_output=True).returncode != 0:
        return {}
    got = subprocess.run(["otool", "-tv", obj], capture_output=True,
                         text=True).stdout
    mnemonics = re.findall(r"^[0-9a-f]{8,16}\s+(\S+)", got, re.M)
    if len(mnemonics) != len(words):
        return {}
    return dict(zip(names, mnemonics))


def _forms_in_image(arch, image_path, workdir, table):
    """`[(mnemonic, encoder)]` for every encoder whose instruction is in `image`.

    The image's own mnemonic set is intersected with the encoders', so the
    answer is "this form occurs in this image" — which is what (d) asks — and
    not "some word of this image has these bits", which a pool-load or a string
    would also satisfy.
    """
    have = _image_mnemonics(image_path)
    return [(mn, name) for name, mn in sorted(table.items()) if mn in have]


# ── the report ─────────────────────────────────────────────────────────────

def _cell(value):
    """One matrix cell. A list is the EX column's example names, summarised.

    Fifty-two names in one cell would wrap every row of the report and bury the
    three columns that are booleans, so the cell carries the COUNT and the first
    few names; `--json` has the whole list for anything that wants it.
    """
    if value is None:
        return "?"
    if value is True:
        return "yes"
    if value is False:
        return "NO"
    if isinstance(value, list):
        return "%d ex: %s" % (len(value), ", ".join(value[:3])
                              + ("…" if len(value) > 3 else ""))
    return str(value)


def report(arch, rows):
    print("== %s: %d emitted form(s), %d encoder(s) in the table"
          % (arch, len(rows), len(encoder_names(arch))))
    print("   %-30s %-4s %-4s %-4s %-4s  %s"
          % ("encoder", "LEAN", "FUZZ", "AS", "EX", "emitted by / note"))
    for row in rows:
        note = ", ".join("%s x%d" % (f, n) for f, n in row.emitted_in)
        if row.sample_error:
            note = "sample?: " + row.sample_error + ("  [" + note + "]"
                                                     if note else "")
        elif row.excluded:
            reason, kind = row.exclusion
            note = (note + "  |  %s: %s" % (kind.upper(), reason)).strip()
        print("   %-30s %-4s %-4s %-4s %-4s  %s"
              % (row.encoder, _cell(row.lean), _cell(row.fuzz),
                 _cell(row.as_check), _cell(row.example), note))
        if row.lean_detail:
            print("   %-30s      %s" % ("", row.lean_detail))
    gaps = [r for r in rows if r.missing() and not r.excluded]
    print("   -- %d form(s) with no LEAN/FUZZ/AS and no exemption; "
          "%d exempt (%d harness, %d backlog)"
          % (len(gaps), sum(1 for r in rows if r.excluded),
             sum(1 for r in rows if r.exclusion[1] == "harness"),
             sum(1 for r in rows if r.exclusion[1] == "backlog")))
    for r in gaps:
        print("      %-30s missing %s" % (r.encoder, ", ".join(r.missing())))
    return gaps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arch", action="append", choices=["arm64", "x86_64"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--examples", action="store_true",
                    help="build the proved corpus and record the EX column")
    ap.add_argument("--limit", type=int, default=None,
                    help="with --examples, only the first N examples")
    args = ap.parse_args(argv)
    arches = args.arch or ["arm64", "x86_64"]

    if args.examples:
        for arch in arches:
            built, _cache = measure_examples(arch, limit=args.limit)
            print("%s: built %d example(s); wrote %s"
                  % (arch, built, os.path.relpath(EXAMPLES_CACHE, ROOT)))
        return 0

    cache = _load_examples() or None

    out, bad = {}, 0
    for arch in arches:
        rows = census(arch, cache)
        out[arch] = [r.as_dict() for r in rows]
        if args.json:
            continue
        bad += len(report(arch, rows))
    if args.json:
        print(json.dumps(out, indent=1, sort_keys=True))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())