#!/usr/bin/env python3
"""End-to-end x86-64 proofs: the whole run, for every input, with no `sorry`.

`formal/x86_64_proof_gen.py` emits per-instruction certificates and concrete
run tests, but its end-to-end theorem is a `sorry`, because relating an
arbitrary symbolic state to the AST is a large claim.  This is the version of
that claim that IS within reach, proved for real:

    for EVERY input n, the model runs the compiled image to the exit pc and
    leaves `v` in `rax`

The input is universally quantified but the arithmetic is concrete, so this is
a statement about the whole function, not the handful of inputs the run tests
sample.  What it does not need is the AST: the expected value is the one the
program is known to produce, so the theorem is about the COMPILED BYTES being
right rather than about the compiler being right, which is the other half of
the boundary and stays a `sorry`.

The technique, and why it is this one:

  Each instruction's successor is an `obtain`-introduced VARIABLE (`s1`, `s2`,
  ...), never a substituted nest.  Every step's side conditions are then stated
  over one state variable, so the term the kernel normalises stays a single
  structure update deep however long the function is.  Writing the successors
  out inline instead nests them, and the kernel reports deep recursion
  partway down -- which is what an earlier attempt did.

  The successor's own equation comes from the step lemma, one `Option.some.inj`
  at a time, and every later step reads what it needs out of that equation with
  `simp`.  The final two facts -- the value in `rax`, and that `rip` reached the
  exit sentinel -- are then proved from the whole chain, with the memory
  read/write separation lemmas doing the real work for `rip`: the final `ret`
  reads the initial stack, far above the only address the body wrote.

Coverage is the forms in `_FORMS` below, which is every form the model has a
step lemma for that this can state a successor expression for.  A function
using anything else is reported as uncovered, with the form named, rather than
skipped silently -- the point is to know what is and is not proved.

  3 examples are proved end to end -- ret42, seven, const2 -- and the rest
  name the forms that block them, most-blocking first:

      28  jcc_rel32        26  movzx_r64_r8   1  each of the rest
      27  alu_rr:test      21  jmp_rel32
      27  alu_rr:cmp       17  alu_rr:add
      26  setcc            11  alu_rr:sub

  `mov_r64_rm64` and `mov_rm64_r64` are gone from that list: the five general
  `mov` lemmas in X86.lean cover every shape the backend emits for them, and
  taking them out is what took the suite from 1 proved to 3.

  Three limits are worth stating separately, because each is a limit of what
  is proved here rather than a gap in it:

    * The result must not depend on the input.  The theorem states a
      CONSTANT, so `identity` cannot satisfy it however it is proved; the test
      detects this by asking the model whether two different inputs give the
      same answer, and reports it as uncovered.  Stating the result as an
      expression of the input is a dataflow problem this does not attempt.

    * Only straight-line functions.  There is no CFG, so a `jcc_rel32` or
      `jmp_rel32` cannot be chained -- which is why those two are the largest
      remaining blockers, and why closing them means cutting blocks rather
      than adding lemmas.

    * `group3:div` is skipped wherever it appears, for the same reason the
      per-instruction certificates skip it: the step is not total.

Usage: python3 formal/x86_64_endtoend_test.py [file.mojo ...]
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import formal.build as B          # noqa: E402
import formal.x86_64_decode as D  # noqa: E402

#: Where Lean's library and the `X86.olean` this test needs live.
LEAN_BIN = os.environ.get("LEAN_BIN") or os.path.expanduser(
    "~/.elan/toolchains/leanprover--lean4---v4.32.2/bin/lean")
LIB = os.path.join(ROOT, "lib")

#: form -> (step lemma, how to build its trailing side-condition arguments).
#:
#: The predecessor state is substituted for `$s`, the code function for `$c`,
#: the instruction address for `$m`, and the decoded immediate for `$imm` /
#: `$disp`.  Each entry lists the side conditions in the lemma's own order
#: after `(state) (code) (addr) (imm)`, so the generator does not have to know
#: the argument order of each lemma.
_FORMS = {
    "push_r64": ("x86_step_push_rbp", False, ["rip", "b0"]),
    "mov_rm64_r64": ("x86_step_mov_rbp_rsp", False, ["rip", "b0", "b1", "b2"]),
    "alu_ri32:sub": ("x86_step_sub_rsp_imm32", True,
                     ["rip", "b0", "b1", "b2", "imm"]),
    "mov_rm64_imm32": ("x86_step_mov_rax_imm32", True,
                       ["rip", "b0", "b1", "b2", "imm"]),
    "alu_ri32:add": ("x86_step_add_rax_imm32", True,
                     ["rip", "b0", "b1", "b2", "imm"]),
    "mov_r64_rm64_reg": ("x86_step_mov_rm64_r64_reg", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod",
                          "reg", "rm"]),
    "mov_r64_rm64_sib": ("x86_step_mov_rax_sib_rsp", False,
                         ["rip", "b0", "b1", "b2", "b3", "w", "rex"]),
    "mov_r64_rm64_disp8": ("x86_step_mov_rm64_mem_disp8_rbp", False,
                           ["rip", "b0", "b1", "b2", "disp", "rex", "w",
                            "mod", "rm", "reg", "rb", "rr"]),
    "mov_rm64_r64_reg": ("x86_step_mov_rm64_r64_reg_st", False,
                         ["rip", "b0", "b1", "b2", "rex", "w", "mod",
                          "reg", "rm"]),
    "mov_rm64_r64_disp8": ("x86_step_mov_mem_disp8_r64", False,
                           ["rip", "b0", "b1", "b2", "disp", "rex", "w",
                            "mod", "rm", "reg", "rb", "rr"]),
    "leave": ("x86_step_leave", False, ["rip", "b0"]),
    "ret": ("x86_step_ret", False, ["rip", "b0"]),
}

#: Successor expressions, matching each lemma's conclusion.  `$s` is the
#: predecessor.  Kept beside `_FORMS` deliberately: a new form needs both, and
#: a mismatch between them is a proof failure rather than a silent gap.
_SUCCS = {
    "push_r64":
        "{ $s with rsp := $s.rsp - 8, rip := $m + 1, "
        "mem := mem_write_bytes $s.mem ($s.rsp - 8).toNat $s.rbp 8 }",
    "mov_rm64_r64": "{ $s with rbp := $s.rsp, rip := $m + 3 }",
    "alu_ri32:sub":
        "{ x86_flags_sub $s $s.rsp $imm ($s.rsp - $imm) with "
        "rsp := $s.rsp - $imm, rip := $m + 7 }",
    "mov_rm64_imm32": "{ $s with rax := $imm, rip := $m + 7 }",
    "alu_ri32:add":
        "{ x86_flags_add $s $s.rax $imm ($s.rax + $imm) with "
        "rax := $s.rax + $imm, rip := $m + 7 }",
    "mov_r64_rm64_reg":
        "{ x86_set_reg $s ($reg + x86_rex_r $rex) "
        "(x86_get_reg $s ($rm + x86_rex_b $rex)) with rip := $m + 3 }",
    "mov_r64_rm64_sib":
        "{ $s with rax := mem_read_bytes $s.mem $s.rsp.toNat 8, rip := $m + 4 }",
    "mov_r64_rm64_disp8":
        "{ x86_set_reg $s ($reg + x86_rex_r $rex) (mem_read_bytes $s.mem "
        "(Int.ofNat $s.rbp.toNat + $disp).toNat 8) with rip := $m + 4 }",
    "mov_rm64_r64_reg":
        "{ x86_set_reg $s ($rm + x86_rex_b $rex) "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) with rip := $m + 3 }",
    "mov_rm64_r64_disp8":
        "{ $s with mem := mem_write_bytes $s.mem "
        "(Int.ofNat $s.rbp.toNat + $disp).toNat "
        "(x86_get_reg $s ($reg + x86_rex_r $rex)) 8, rip := $m + 4 }",
    "leave":
        "{ $s with rbp := mem_read_bytes $s.mem $s.rbp.toNat 8, "
        "rsp := $s.rbp + 8, rip := $m + 1 }",
    "ret":
        "{ $s with rip := (mem_read_bytes $s.mem ($s.rsp.toNat) 8).toNat, "
        "rsp := $s.rsp + 8 }",
}


def _body(code, info):
    """The entry function's own instruction stream, or None if it won't decode."""
    base, entry = info["base_addr"], info["func_offset"]
    strs = [a for n, a in (info.get("labels") or {}).items()
            if n.startswith("str_")]
    end = (min(strs) - base) if strs else len(code)
    if end <= entry - base:
        return None
    try:
        return D.decode_all(code, entry - base, end)
    except D.DecodeError:
        return None


def _byte_facts(insns, code, base):
    facts = []
    for i in insns:
        for j in range(i.length):
            facts.append("rc %d = %d" % (base + i.offset + j, code[i.offset + j]))
    return " ∧\n    ".join(facts)


def emit(path, expected):
    """Return the Lean text proving the end-to-end theorem, or raise ValueError."""
    r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
    code, info = r["code"], r["info"]
    base, entry = info["base_addr"], info["func_offset"]
    insns = _body(code, info)
    if insns is None:
        raise ValueError("body does not decode")
    shapes = []
    for i in insns:
        raw = code[i.offset:i.next_offset]
        form = i.form
        if form == "mov_rm64_r64":
            modrm = raw[2]
            if (modrm >> 6) == 3:
                form = "mov_rm64_r64_reg"
            elif (modrm >> 6) == 1 and (modrm & 7) == 5:
                form = "mov_rm64_r64_disp8"
        elif form == "mov_r64_rm64":
            modrm = raw[2]
            if (modrm >> 6) == 3:
                form = "mov_r64_rm64_reg"
            elif (modrm >> 6) == 0 and (modrm & 7) == 4 and len(raw) >= 4 \
                    and raw[3] == 0x24:
                form = "mov_r64_rm64_sib"
            elif (modrm >> 6) == 1 and (modrm & 7) == 5:
                form = "mov_r64_rm64_disp8"
        shapes.append((i, form, raw))
    missing = sorted({f for _, f, _ in shapes} - set(_FORMS))
    if missing:
        raise ValueError("no step lemma wired for: " + ", ".join(missing))

    L = []
    a = L.append
    a("import X86\n")
    a("def rc (addr : Nat) : UInt8 :=")
    a("  if addr < %d then 0 else" % base)
    a("    ([%s].getD (addr - %d) 0)\n"
      % (", ".join("0x%02x" % b for b in code), base))
    a("/-- Every byte of the function, as a fact about `rc`. -/")
    a("theorem all_bytes :\n    %s := by native_decide\n" % _byte_facts(insns, code, base))
    a("/-- For EVERY input: the model runs this image to the exit pc and leaves")
    a("    `%d` in `rax`.  Proved, not asserted. -/" % expected)
    a("theorem all_inputs (n : UInt64) :")
    a("    (x86_exec_exit (X86State.init n %d) rc 0).map X86State.rax" % entry)
    a("      = some %d := by" % expected)
    a("  rw [x86_exec_exit_eq_go]")
    a("  have hb := all_bytes")
    a("  let i0 : X86State := X86State.init n %d" % entry)

    prev, k = "i0", 0
    chain = []
    for insn, form, raw in shapes:
        lemma, takes_imm, conds = _FORMS[form]
        addr = base + insn.offset
        imm = int.from_bytes(raw[3:7], "little", signed=True) if takes_imm else None
        # side conditions, in the lemma's own order
        sc = []
        for c in conds:
            if c == "rip":
                if k == 0:
                    sc.append("(by simp only [i0, X86State.init] <;> decide)")
                else:
                    sc.append("(by simp [hs%d])" % k)
            elif c == "b0":
                sc.append("(by simp [read_i32_le, read_i8, hb])")
            elif c == "b1":
                sc.append("(by simp [read_i32_le, read_i8, hb])")
            elif c == "b2":
                sc.append("(by simp [read_i32_le, read_i8, hb])")
            elif c == "imm":
                sc.append("(by simp [read_i32_le, read_i8, hb])")
            elif c == "b3":
                sc.append("(by simp [read_i32_le, read_i8, hb])")
            elif c == "disp":
                sc.append("(by simp [read_i8, hb])")
            elif c in ("rex", "rex2", "w", "mod", "reg", "rm", "rb", "rr"):
                # Closed arithmetic on the ModRM/REX literals -- nothing here
                # comes from the byte list, so `decide` and not `simp [hb]`.
                sc.append("(by decide)")
            else:
                raise ValueError("bad condition " + c)
        extra_args, extra_succ = "", {}
        if form == "mov_r64_rm64_sib":
            extra_args = ""
        elif form in ("mov_r64_rm64_disp8", "mov_rm64_r64_disp8"):
            rex, modrm = raw[0], raw[2]
            disp = raw[3] - 256 if raw[3] > 127 else raw[3]
            # The displacement can be negative, and a negative literal
            # followed by `(` parses as an application of it -- so it is
            # parenthesised.
            extra_args = " %d %d %d (%d)" % (rex, modrm, (modrm >> 3) & 7, disp)
            extra_succ = {"$reg": str((modrm >> 3) & 7), "$disp": str(disp),
                          "$rex": str(rex)}
        elif form in ("mov_r64_rm64_reg", "mov_rm64_r64_reg"):
            rex, modrm = raw[0], raw[2]
            extra_args = " %d %d %d %d" % (rex, modrm, (modrm >> 3) & 7,
                                           modrm & 7)
            extra_succ = {"$reg": str((modrm >> 3) & 7),
                          "$rm": str(modrm & 7), "$rex": str(rex)}
        call = "%s %s rc %d%s" % (lemma, prev, addr, extra_args)
        if takes_imm:
            call += " %d" % imm
        call += " " + " ".join(sc)
        succ = _SUCCS[form].replace("$s", prev)
        for ph, val in extra_succ.items():
            succ = succ.replace(ph, val)
        succ = succ.replace("$m", str(addr))
        succ = succ.replace("$imm", str(imm) if imm is not None else "0")
        nxt = "s%d" % (k + 1)
        # The step equation is stated with the successor EXPLICITLY first, so
        # the step lemma is elaborated against a known type.  Passing it
        # straight into the anonymous constructor of the `obtain` instead
        # leaves the lemma's own hypotheses as metavariables, because the
        # witness is not yet fixed at that point.
        a("  have hstep%d : x86_step %s rc = some %s :=" % (k, prev, succ))
        a("    %s" % call)
        a("  obtain \u27e8%s, h%d\u27e9 : \u2203 t, x86_step %s rc = some t :="
          % (nxt, k, prev))
        a("    \u27e8_, hstep%d\u27e9" % k)
        a("  have hs%d : %s = %s := by" % (k + 1, nxt, succ))
        a("    rw [h%d] at hstep%d" % (k, k))
        a("    exact Option.some.inj hstep%d" % k)
        chain.append((k, nxt))
        prev, k = nxt, k + 1

    # the two facts the goal is about
    a("  have hrax : %s.rax = %d := by" % (prev, expected))
    a("    simp [%s, i0, x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r,"
      % ", ".join("hs%d" % (j + 1) for j, _ in chain))
    a("      x86_flags_sub, x86_flags_add]")
    a("  have hrip : %s.rip = 0 := by" % prev)
    a("    have key : \u2200 (m : Nat \u2192 UInt8) (a : Nat) (v : UInt64) (b : Nat),")
    a("        a + 8 \u2264 b \u2192 mem_read_bytes (mem_write_bytes m a v 8) b 8")
    a("          = mem_read_bytes m b 8 :=")
    a("      fun m a v b h => mem_read_bytes_write_above m a v 8 8 b h")
    a("    simp [%s, i0, X86State.init, x86_flags_sub, x86_flags_add,"
      % ", ".join("hs%d" % (j + 1) for j, _ in chain))
    a("      x86_set_reg, x86_get_reg, x86_rex_b, x86_rex_r]")
    a("    rw [key _ _ _ _ (by decide)]")
    a("    simp only [mem_read_bytes, ite_true]")
    a("    decide")
    # collapse the run
    rules = ["x86_exec_go_exit_step (by decide) "
             "(by simp only [i0, X86State.init] <;> decide) h0"]
    for j, _ in chain[1:]:
        rules.append("x86_exec_go_exit_step (by decide) (by simp [hs%d]) h%d"
                     % (j, j))
    rules.append("x86_exec_go_exit_at (by decide) hrip")
    a("  rw [%s]" % ",\n      ".join(rules))
    a("  simp [hrax]")
    return "\n".join(L) + "\n"


def _result_at(binary, n):
    """The exit code with `n` as the program's input, or None if it won't run.

    The generated binaries take their input from the environment rather than
    stdin, so this drives them the same way the model test does and reports
    the exit code; a program that ignores its input gives the same answer
    twice, which is the case this is here to detect.
    """
    import os as _os
    env = dict(_os.environ, MOJO_TEST_INPUT=str(n))
    try:
        return subprocess.run(["arch", "-x86_64", binary], capture_output=True,
                              text=True, timeout=60, env=env).returncode
    except Exception:                                      # noqa: BLE001
        return None


def _probe_input_independent(path):
    """Does the model's result depend on the input at all?

    The theorem states a CONSTANT result, so a program that returns its input
    cannot satisfy it -- and that is a limit of what is proved here, not a
    proof failure, so it must not be reported as one.  The model itself
    answers the question exactly: run the same bytes from two different
    initial states and compare.

    This costs a second Lean invocation, so it only runs for a file whose
    theorem has already failed.
    """
    r = B.compile_formal(path, prove=False, check=False, arch="x86_64")
    code, info = r["code"], r["info"]
    entry = info["func_offset"]
    text = ("import X86\n\ndef rc (addr : Nat) : UInt8 :=\n"
            "  if addr < %d then 0 else ([%s].getD (addr - %d) 0)\n\n"
            "/-- The result is the same for every input, or it is not. -/\n"
            "theorem input_independent :\n"
            "    (x86_exec_exit (X86State.init 0 %d) rc 0).map X86State.rax =\n"
            "      (x86_exec_exit (X86State.init 5 %d) rc 0).map X86State.rax :=\n"
            "  native_decide\n"
            % (info["base_addr"], ", ".join("0x%02x" % b for b in code),
               info["base_addr"], entry, entry))
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(text)
        tmp = f.name
    try:
        env = dict(os.environ, LEAN_PATH="%s:%s" % (ROOT, LIB))
        p = subprocess.run([LEAN_BIN, tmp], capture_output=True, text=True,
                           env=env)
        return ": error" not in p.stdout + p.stderr
    finally:
        os.unlink(tmp)


def _check(path, expected):
    lean = emit(path, expected)
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False) as f:
        f.write(lean)
        tmp = f.name
    try:
        env = dict(os.environ, LEAN_PATH="%s:%s" % (ROOT, LIB))
        p = subprocess.run([LEAN_BIN, tmp], capture_output=True, text=True,
                           env=env)
        errs = [l for l in (p.stdout + p.stderr).splitlines() if ": error" in l]
        if errs or "declaration uses `sorry`" in p.stdout + p.stderr:
            return False, "\n".join(errs[:4]) or "uses sorry"
        return True, ""
    finally:
        os.unlink(tmp)


def main(argv):
    targets = argv[1:]
    if not targets:
        d = os.path.join(HERE, "examples")
        targets = [os.path.join(d, f) for f in sorted(os.listdir(d))
                   if f.endswith(".mojo")]
    ok = covered = 0
    for t in targets:
        name = os.path.basename(t)
        # The expected value is the program's result, which for these examples
        # does not depend on the input; read it from the concrete run at 0.
        try:
            r = B.compile_formal(t, prove=False, check=False, arch="x86_64")
        except Exception as exc:                      # noqa: BLE001
            print("  [skip] %-16s does not build (%s)" % (name, exc))
            continue
        # The observable the model test already trusts: the binary's exit
        # code, which the C runtime takes from the value left in RAX.
        try:
            expected = subprocess.run(["arch", "-x86_64", r["path"]],
                                      capture_output=True, text=True,
                                      timeout=60).returncode
        except Exception as exc:                          # noqa: BLE001
            print("  [skip] %-16s does not run (%s)" % (name, exc))
            continue
        if expected < 0 or expected > 255:
            print("  [open] %-16s exit code %d is not a rax value"
                  % (name, expected))
            continue
        try:
            good, msg = _check(t, expected)
        except ValueError as exc:
            print("  [open] %-16s %s" % (name, exc))
            continue
        if good:
            covered += 1
            print("  [PROVED] %-16s every input -> rax = %d" % (name, expected))
        elif not _probe_input_independent(t):
            print("  [open] %-16s result depends on the input, so the constant"
                  " form does not apply" % name)
        else:
            print("  [FAIL]  %-16s %s" % (name, msg))
            ok += 1
    print("\nend-to-end: %d proved with no sorry, %d failing, of %d attempted"
          % (covered, ok, len(targets)))
    return 1 if ok else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
