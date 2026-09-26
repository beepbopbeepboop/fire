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

  ret42 is proved end to end.  Of the other 42 examples, none is covered yet,
  and the forms that block them, most-blocking first, are:

      42  mov_r64_rm64     26  setcc          8  imul_r64_r64
      28  jcc_rel32        21  jmp_rel32       7  call_rel32
      27  alu_rr:test      17  alu_rr:add      3  movsx_r64_r8
      27  alu_rr:cmp       11  alu_rr:sub      1  each of the rest

  `mov_r64_rm64` alone unblocks 42 of 43, and it is one lemma: the model
  already has the rax/rbx instance of it, just not the general register and
  not the memory-source shape.  `alu_rr:test`/`alu_rr:cmp` and `setcc` are one
  family each -- a compare that only sets flags, and a condition code turned
  into 0 or 1 -- and between them they unblock 27.

  Note the coverage is not the same as the model's coverage: `X86.lean` has
  step lemmas for several of these in one register pair only (`mov_rax_rbx`,
  `add_rax_imm32`, `jz_rel32`, `setne_al`), which is why a form shows up as
  missing here while a lemma with a similar name exists.  Generalising those
  is most of the remaining work, and it is mechanical rather than hard.

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
    missing = sorted({i.form for i in insns} - set(_FORMS))
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
    for insn in insns:
        form = insn.form
        lemma, takes_imm, conds = _FORMS[form]
        addr = base + insn.offset
        raw = code[insn.offset:insn.next_offset]
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
            else:
                raise ValueError("bad condition " + c)
        nxt = "s%d" % (k + 1)
        call = "%s %s rc %d" % (lemma, prev, addr)
        if takes_imm:
            call += " %d" % imm
        call += " " + " ".join(sc)
        a("  obtain \u27e8%s, h%d\u27e9 : \u2203 t, x86_step %s rc = some t :="
          % (nxt, k, prev))
        a("    \u27e8_, %s\u27e9" % call)
        succ = _SUCCS[form].replace("$s", prev)
        succ = succ.replace("$m", str(addr))
        succ = succ.replace("$imm", str(imm) if imm is not None else "0")
        a("  have hs%d : %s = %s := by" % (k + 1, nxt, succ))
        a("    have he := %s" % call)
        a("    rw [h%d] at he" % k)
        a("    exact Option.some.inj he")
        chain.append((k, nxt))
        prev, k = nxt, k + 1

    # the two facts the goal is about
    a("  have hrax : %s.rax = %d := by" % (prev, expected))
    a("    simp [%s, i0]" % ", ".join("hs%d" % (j + 1) for j, _ in chain))
    a("  have hrip : %s.rip = 0 := by" % prev)
    a("    have key : \u2200 (m : Nat \u2192 UInt8) (a : Nat) (v : UInt64) (b : Nat),")
    a("        a + 8 \u2264 b \u2192 mem_read_bytes (mem_write_bytes m a v 8) b 8")
    a("          = mem_read_bytes m b 8 :=")
    a("      fun m a v b h => mem_read_bytes_write_above m a v 8 8 b h")
    a("    simp only [%s, i0, X86State.init, x86_flags_sub, x86_flags_add]"
      % ", ".join("hs%d" % (j + 1) for j, _ in chain))
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
        else:
            print("  [FAIL]  %-16s %s" % (name, msg))
            ok += 1
    print("\nend-to-end: %d proved with no sorry, %d failing, of %d attempted"
          % (covered, ok, len(targets)))
    return 1 if ok else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
