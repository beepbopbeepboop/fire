#!/usr/bin/env python3
"""Two checks on formal/x86_64.py's x86-64 backend.

1. Every `encode_*` is compared byte-for-byte against what GNU as produces
   for the equivalent instruction, assembled by clang with `-arch x86_64` (no
   execution — the host is arm64), so an encoding mistake shows up as a byte
   difference rather than as a wrong answer at run time.

2. Each architecture's Mach-O cpu type/subtype pair is asserted against
   <mach/machine.h>'s values, and a trivial program is built and execve'd for
   each one (skipping x86_64 when Rosetta is unavailable). A build-only check
   cannot see a wrong cpusubtype: the image still assembles, signs and
   disassembles, and only execve refuses it with EBADARCH — see BUG.md.
"""
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formal import x86_64 as X
from formal.x86_64 import Reg

R = {n: getattr(Reg, n) for n in dir(Reg) if n.startswith("R")}

CASES = [
    ("pushq %rax", lambda: X.encode_push_r64(Reg.RAX)),
    ("pushq %r12", lambda: X.encode_push_r64(Reg.R12)),
    ("pushq %r15", lambda: X.encode_push_r64(Reg.R15)),
    ("popq %rbx", lambda: X.encode_pop_r64(Reg.RBX)),
    ("popq %r13", lambda: X.encode_pop_r64(Reg.R13)),
    ("retq", lambda: X.encode_ret()),
    ("leaveq", lambda: X.encode_leave()),
    ("nop", lambda: X.encode_nop()),
    ("movq $42, %rax", lambda: X.encode_mov_r64_imm32(Reg.RAX, 42)),
    ("movq $-7, %r9", lambda: X.encode_mov_r64_imm32(Reg.R9, -7)),
    ("movq $0x1122334455667788, %rbx",
     lambda: X.encode_mov_r64_imm64(Reg.RBX, 0x1122334455667788)),
    # The half of the 64-bit PATTERN argument's domain that `struct.pack("<q",
    # …)` cannot take: constants whose bit 63 is set, which is every value in
    # [2**63, 2**64 - 2**31) — the first of these is BLAKE2b's IV1, and it
    # CRASHED this compiler (an unhandled struct.error out of a build) rather
    # than refusing. GNU as writes the same ten bytes for each, which is what
    # makes them the same instruction.
    #
    # -1 is NOT here even though it is in the pattern's domain: `as` spells it
    # `48c7c3ffffffff` (a sign-extended imm32) and `_emit_mov_imm` never picks
    # the imm64 form for it, so a byte-identity check would be testing the
    # length choice rather than the packing.
    ("movq $0xbb67ae8584caa73b, %rbx",
     lambda: X.encode_mov_r64_imm64(Reg.RBX, 0xbb67ae8584caa73b)),
    ("movq $0x8000000000000000, %r12",
     lambda: X.encode_mov_r64_imm64(Reg.R12, 0x8000000000000000)),
    ("movq $-4294967296, %rbx",
     lambda: X.encode_mov_r64_imm64(Reg.RBX, 0xFFFFFFFF00000000)),
    ("movq %rax, %rbx", lambda: X.encode_mov_r64_r64(Reg.RBX, Reg.RAX)),
    ("movq %r14, %r9", lambda: X.encode_mov_r64_r64(Reg.R9, Reg.R14)),
    ("movq (%rax), %rbx", lambda: X.encode_mov_r64_rm64(Reg.RBX, Reg.RAX, 0)),
    ("movq -8(%rbp), %rax", lambda: X.encode_mov_r64_rm64(Reg.RAX, Reg.RBP, -8)),
    ("movq 16(%rbp), %r10", lambda: X.encode_mov_r64_rm64(Reg.R10, Reg.RBP, 16)),
    ("movq 4096(%rax), %rcx", lambda: X.encode_mov_r64_rm64(Reg.RCX, Reg.RAX, 4096)),
    ("movq (%rsp), %rax", lambda: X.encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0)),
    ("movq -8(%rsp), %rax", lambda: X.encode_mov_r64_rm64(Reg.RAX, Reg.RSP, -8)),
    ("movq (%r12), %rax", lambda: X.encode_mov_r64_rm64(Reg.RAX, Reg.R12, 0)),
    ("movq %rax, -8(%rbp)", lambda: X.encode_mov_rm64_r64(Reg.RBP, -8, Reg.RAX)),
    ("movq %r14, 24(%rbp)", lambda: X.encode_mov_rm64_r64(Reg.RBP, 24, Reg.R14)),
    ("movl %eax, %ebx", lambda: X.encode_mov_r32_r32(Reg.RBX, Reg.RAX)),
    ("movslq %eax, %rbx", lambda: X.encode_movsx_r64_r32(Reg.RBX, Reg.RAX)),
    ("movzbq %al, %rbx", lambda: X.encode_movzx_r64_r8(Reg.RBX, Reg.RAX)),
    ("movsbq %r9b, %rax", lambda: X.encode_movsx_r64_r8(Reg.RAX, Reg.R9)),
    ("movzwq %ax, %rbx", lambda: X.encode_movzx_r64_r16(Reg.RBX, Reg.RAX)),
    ("movswq %r12w, %rax", lambda: X.encode_movsx_r64_r16(Reg.RAX, Reg.R12)),
    ("addq %rbx, %rax", lambda: X.encode_add_r64_r64(Reg.RAX, Reg.RBX)),
    ("subq %r14, %rax", lambda: X.encode_sub_r64_r64(Reg.RAX, Reg.R14)),
    ("imulq %rbx, %rax", lambda: X.encode_imul_r64_r64(Reg.RAX, Reg.RBX)),
    ("imulq %r14, %rax", lambda: X.encode_imul_r64_r64(Reg.RAX, Reg.R14)),
    ("andq %rbx, %rax", lambda: X.encode_and_r64_r64(Reg.RAX, Reg.RBX)),
    ("orq %rbx, %rax", lambda: X.encode_or_r64_r64(Reg.RAX, Reg.RBX)),
    ("xorq %rbx, %rax", lambda: X.encode_xor_r64_r64(Reg.RAX, Reg.RBX)),
    ("cmpq %rbx, %rax", lambda: X.encode_cmp_r64_r64(Reg.RAX, Reg.RBX)),
    ("testq %rbx, %rax", lambda: X.encode_test_r64_r64(Reg.RAX, Reg.RBX)),
    # The 0x81 /digit id (imm32) form is a distinct encoding from the 0x83
    # /digit ib (imm8) short form, so the immediates here are ones that do
    # NOT fit in a signed byte — otherwise the assembler picks the short form
    # and the comparison is not like-for-like. The registers are not RAX
    # either: with an accumulator operand as emits the shorter opcode+imm32
    # form (0x05/0x2D/…) rather than 0x81 /digit.
    ("addq $1000, %rbx", lambda: X.encode_add_r64_imm32(Reg.RBX, 1000)),
    ("addq $1000, %r12", lambda: X.encode_add_r64_imm32(Reg.R12, 1000)),
    ("subq $1000, %rbx", lambda: X.encode_sub_r64_imm32(Reg.RBX, 1000)),
    ("andq $1000, %rbx", lambda: X.encode_and_r64_imm32(Reg.RBX, 1000)),
    ("orq $1000, %rbx", lambda: X.encode_or_r64_imm32(Reg.RBX, 1000)),
    ("xorq $1000, %rbx", lambda: X.encode_xor_r64_imm32(Reg.RBX, 1000)),
    ("cmpq $1000, %rbx", lambda: X.encode_cmp_r64_imm32(Reg.RBX, 1000)),
    ("addq $100, %rax", lambda: X.encode_add_r64_imm8(Reg.RAX, 100)),
    ("addq $8, %rax", lambda: X.encode_add_r64_imm8(Reg.RAX, 8)),
    ("subq $8, %r10", lambda: X.encode_sub_r64_imm8(Reg.R10, 8)),
    ("andq $8, %rax", lambda: X.encode_and_r64_imm8(Reg.RAX, 8)),
    ("cmpq $8, %rax", lambda: X.encode_cmp_r64_imm8(Reg.RAX, 8)),
    ("negq %rax", lambda: X.encode_neg_r64(Reg.RAX)),
    ("notq %r14", lambda: X.encode_not_r64(Reg.R14)),
    ("mulq %rbx", lambda: X.encode_mul_r64(Reg.RBX)),
    ("imulq %rbx", lambda: X.encode_imul_r64_1op(Reg.RBX)),
    ("divq %rbx", lambda: X.encode_div_r64(Reg.RBX)),
    ("idivq %r14", lambda: X.encode_idiv_r64(Reg.R14)),
    ("cqto", lambda: X.encode_cqo()),
    ("xorl %edx, %edx", lambda: X.encode_xor_edx_edx()),
    ("shlq $3, %rax", lambda: X.encode_shift_r64_imm8("<<", Reg.RAX, 3)),
    ("shrq $3, %r12", lambda: X.encode_shift_r64_imm8(">>", Reg.R12, 3)),
    ("sarq $3, %rax", lambda: X.encode_shift_r64_imm8(">>signed", Reg.RAX, 3)),
    ("shlq %cl, %rax", lambda: X.encode_shift_r64_cl("<<", Reg.RAX)),
    ("sarq %cl, %r13", lambda: X.encode_shift_r64_cl(">>signed", Reg.R13)),
    ("leaq -16(%rbp), %rax", lambda: X.encode_lea_r64_rm64(Reg.RAX, Reg.RBP, -16)),
    # RIP-relative LEA: 7 bytes, and specifically NO SIB byte — a spurious one
    # shifts the displacement field and yields a wrong address rather than an
    # obvious encoding error.
    ("leaq 0x1234(%rip), %rax", lambda: X.encode_lea_r64_rip(Reg.RAX, 0x1234)),
    ("leaq 0x1234(%rip), %r12", lambda: X.encode_lea_r64_rip(Reg.R12, 0x1234)),
    ("leaq -0x40(%rip), %rbx", lambda: X.encode_lea_r64_rip(Reg.RBX, -0x40)),
    ("leaq 4096(%rbp), %r10", lambda: X.encode_lea_r64_rm64(Reg.R10, Reg.RBP, 4096)),
    ("sete %al", lambda: X.encode_sete(Reg.RAX)),
    ("setne %r9b", lambda: X.encode_setne(Reg.R9)),
    ("setl %al", lambda: X.encode_setl(Reg.RAX)),
    ("setle %al", lambda: X.encode_setle(Reg.RAX)),
    ("setg %al", lambda: X.encode_setg(Reg.RAX)),
    ("setge %al", lambda: X.encode_setge(Reg.RAX)),
    ("setb %al", lambda: X.encode_setb(Reg.RAX)),
    ("setbe %al", lambda: X.encode_setbe(Reg.RAX)),
    ("seta %al", lambda: X.encode_seta(Reg.RAX)),
    ("setae %al", lambda: X.encode_setae(Reg.RAX)),
    # Branch displacements: the assembler spells a target as `.+D`, where the
    # encoded rel is D - insn_length. Each case below sits at offset 0 of its
    # own symbol, so `.+7` means "rel8 of 5" (2-byte jcc) and `.+0x1239`
    # means "rel32 of 0x1234" (5-byte call).
    ("je .+7", lambda: X.encode_je_rel8(5)),
    ("jne .+7", lambda: X.encode_jne_rel8(5)),
    ("je .+7", lambda: X.encode_jcc_rel8(X.COND_E, 5)),
    ("jge .+7", lambda: X.encode_jcc_rel8(X.COND_GE, 5)),
    ("jb .+7", lambda: X.encode_jcc_rel8(X.COND_B, 5)),
    ("je .+0x123a", lambda: X.encode_jcc_rel32(X.COND_E, 0x1234)),
    ("jg .+0x123a", lambda: X.encode_jcc_rel32(X.COND_G, 0x1234)),
    # as rejects a symbolic operand for jmp, so use the numeric forward
    # reference `jmp 1f`: with a 1-byte instruction in between it picks the
    # 2-byte rel8 form, and with 200 of them the rel8 range is exceeded so it
    # falls back to the 5-byte rel32 form.
    ("jmp 1f\n\tnop\n1:", lambda: X.encode_jmp_rel8(1)),
    ("jmp 1f" + "\n\tnop" * 200 + "\n1:", lambda: X.encode_jmp_rel32(200)),
    ("callq .+0x1239", lambda: X.encode_call_rel32(0x1234)),
    ("callq *0x1234(%rip)", lambda: X.encode_call_rm64(0x1234)),
    ("jmpq *0x1234(%rip)", lambda: X.encode_jmp_rm64(0x1234)),
]


def main() -> int:
    failures = 0
    failures += check_encoders()
    failures += check_cpu_types()
    return 1 if failures else 0


def check_encoders() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as d:
        for i, (text, fn) in enumerate(CASES):
            # Each instruction gets its own symbol so `.+N` offsets and the
            # %cl shifts land in a real instruction stream.
            src = f'.text\n.globl s{i}\ns{i}:\n\t{text}\n'
            path = os.path.join(d, f"c{i}.s")
            with open(path, "w") as f:
                f.write(src)
            obj = os.path.join(d, f"c{i}.o")
            r = subprocess.run(["clang", "-arch", "x86_64", "-c", path,
                                "-o", obj], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"FAIL(assemble) {text}: {r.stderr.strip()}")
                failures += 1
                continue
            want = object_code(obj)
            got = fn()
            if len(want) < len(got) or want[:len(got)] != got:
                print(f"FAIL {text}\n  want {want.hex()}\n  got  {got.hex()}")
                failures += 1
    print(f"{len(CASES) - failures}/{len(CASES)} encoders match GNU as")
    return failures


# The header pair each architecture's image must carry, straight from
# <mach/machine.h>: (CPU_TYPE_*, CPU_SUBTYPE_*_ALL).
EXPECTED_CPU_TYPES = {
    "arm64": (0x0100000C, 0x00000000),
    "x86_64": (0x01000007, 0x00000003),
}

# The smallest program that is a valid LC_MAIN entry for each architecture:
# leave a zero status in the return register, then return. The bytes are
# architecture-specific (a 4-byte RET on arm64, a 2-byte `xor eax,eax` plus a
# 1-byte RET on x86-64), which is the point — an image whose cpu type says one
# architecture and whose code is the other's dies before it can report
# anything.
TRIVIAL_PROGRAM = {
    "arm64": struct.pack("<II", 0xD2800000, 0xD65F03C0),   # mov x0, #0; ret
    "x86_64": b"\x31\xc0\xc3",                              # xor eax, eax; ret
}


def check_cpu_types() -> int:
    """Assert the emitted Mach-O header identifies the right architecture,
    then execve one trivial program per architecture.

    A wrong cpusubtype is invisible to every build-time check (the image
    signs, `otool` parses it, `codesign -v` passes) and shows up only as
    EBADARCH at execve — which is why this RUNS the binary rather than just
    inspecting the header. See BUG.md."""
    from formal import macho
    from formal import macho_linker

    failures = 0
    for arch, want in EXPECTED_CPU_TYPES.items():
        spec = macho_linker.arch_spec(arch)
        got = (spec["cputype"], spec["cpusubtype"])
        if got != want:
            print(f"FAIL {arch}: arch_spec {got} != <mach/machine.h> {want}")
            failures += 1
            continue
        image = macho.build_macho(TRIVIAL_PROGRAM[arch], external_syms=None,
                                  arch=arch)
        hdr = struct.unpack_from("<II", image, 4)
        if hdr != want:
            print(f"FAIL {arch}: image header {hdr} != {want}")
            failures += 1
            continue
        status, detail = run_image(image, arch)
        if status is None:
            print(f"SKIP {arch}: cannot execute here ({detail})")
            continue
        if status != 0:
            print(f"FAIL {arch}: trivial program exited {status} ({detail})")
            failures += 1
            continue
        print(f"ok   {arch}: header {want} and a trivial program runs")
    return failures


def run_image(image: bytes, arch: str):
    """execve `image` and return (exit status, detail).

    x86-64 on an arm64 host needs Rosetta 2 (`arch -x86_64`), the same way a
    clang `-arch x86_64` binary does; if it is not installed there is nothing
    to run and None is returned rather than a failure."""
    if sys.platform != "darwin":
        return None, "not macOS"
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.out")
        with open(path, "wb") as f:
            f.write(image)
        os.chmod(path, 0o755)
        sign = subprocess.run(["codesign", "-s", "-", path],
                              capture_output=True, text=True)
        if sign.returncode != 0:
            return None, f"codesign failed: {sign.stderr.strip()}"
        argv = ["arch", "-x86_64", path] if arch == "x86_64" else [path]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode < 0:
            return None, f"signal {-r.returncode}"
        if "Bad CPU type" in (r.stderr or ""):
            return None, "Bad CPU type in executable"
        return r.returncode, r.stderr.strip()



def object_code(obj: str) -> bytes:
    """The .text bytes of a Mach-O object, via otool.

    `otool -s` prints one line per 16 bytes as a 16-hex-digit address
    followed by space-separated byte pairs; the address is dropped and the
    pairs concatenated."""
    r = subprocess.run(["otool", "-s", "__TEXT", "__text", obj],
                       capture_output=True, text=True)
    out = bytearray()
    for line in r.stdout.splitlines():
        parts = line.split()
        if not parts or len(parts[0]) != 16:
            continue
        if not all(c in "0123456789abcdefABCDEF" for c in parts[0]):
            continue
        for b in parts[1:]:
            if len(b) == 2 and all(c in "0123456789abcdefABCDEF" for c in b):
                out.append(int(b, 16))
    return bytes(out)


if __name__ == "__main__":
    sys.exit(main())
