#!/usr/bin/env python3
"""The model-fuzz harness's two UNREAD steps: its ENTRY path, and its VERDICTS.

`formal/x86_64_model_fuzz.py` is not a gate job — it is a tool, and its
`HARNESS` verdict rows (`mul`/`imul` flags, `setcc` into `rbp`/`rsi`/`rdi`) are
the ones a reader must NOT go looking for in `lib/X86.lean`. Two of the harness's
own steps decide that, and nothing reads either of them back.

**The entry path.** The entry stub installs the register file out of
`init_block` with real `mov` instructions, and if those loads did not land every
field of every program would be a false disagreement — which is what the
`HARNESS` rows would then have been. `--entry-probe` is that read-back, and the
first class here is its pins.

**The verdicts.** A row is `WRONG` (a model bug), `HARNESS` (a disagreement no
x86-64 CPU can produce) or `FAULT`, and which one a row gets is decided in
Python from the program's bytes and the list of differing fields. Both rules
were wrong, and both were silent in the worst way: a random program containing
one anomalous `setcc` was reported as a `WRONG` model bug and made the tool exit
1, and `minimise` handed back a prefix that agreed when run on its own. The
second class here is Lean-free and native-free on purpose — it is about which
verdict a row gets, so it can be asked without either half.

**Not registered in `tools/suite.py`** (this session's rules forbid registering
without being asked), so run it directly:

    python3 tools/memslot.py --gb 8 --label t -- python3 test_x86_64_model_fuzz.py

The text cases are Lean-free and take no native run. One compiles the harness
`clang -arch x86_64` and runs it `arch -x86_64`, and SKIPS where that is not
available rather than passing quietly — on a host that cannot run x86-64 code
there is no entry register file to check.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import formal.x86_64_model_fuzz as F                          # noqa: E402


def _one(reg, items):
    """One `Program` whose registers are all distinguishable, for `reg` alone."""
    regs = [0x1111111111111111 * (j + 1) for j in range(16)]
    regs[F.R.RSP.value] = F.STACK_TOP_ABS
    regs[F.R.R13.value] = F.MEMBASE_ABS
    regs[F.R.R14.value] = F.MEMBASE_ABS
    return F.Program(0, [(items[0], items[1])], regs,
                     [0x2222222222222222] * 8,
                     {"cf": True, "zf": False, "sf": False, "of_": False},
                     [0] * F.DATA_N)


class TestEntryProbe(unittest.TestCase):
    def test_the_probe_is_installed_where_the_register_file_is(self):
        """The seventeen stores go between the last `movq` and the `jmp`.

        Anywhere else and the probe reads a register file that is not the one the
        program starts with: before the loads it would dump the CALLER's
        registers (which is what `setcontext` left, and the reason this file's
        whole subject exists), and after the `jmp` it would read the program's
        own — i.e. the dump stub's job, already done.
        """
        src = F.harness_source([_one(F.R.RAX, ("nop", F.X.encode_nop()))],
                               probe=True)
        last_load = src.index('"  movq 24(%rbx), %rbx')
        jump = src.index('"  jmp *_enter_target(%rip)')
        probe = src.index("_probe_area+0(%rip)")
        self.assertLess(last_load, probe,
                        "the probe must read the file the loads installed")
        self.assertLess(probe, jump,
                        "…and before the jump into the emulated code, or it "
                        "reads the program's registers rather than its entry "
                        "state")
        self.assertTrue(src.startswith("#define PROBE_ON 1\n"),
                        "the macro has to come FIRST: both guarded regions — the "
                        "`probe_area` declaration and `resume`'s print — are "
                        "above the generated tables, and a `#define` below them "
                        "is one the preprocessor has already passed. Measured: "
                        "`use of undeclared identifier 'probe_area'`.")

    def test_the_probe_uses_the_dump_areas_offsets(self):
        """One layout, not two conventions that can drift.

        `dump_area` and `probe_area` are both the sixteen GPRs at 8-byte
        offsets, then EFLAGS at 128, then the eight XMM at 136. If they ever
        diverged, a word-for-word comparison of the two dumps would compare
        register 3 against register 4 and find nothing wrong with anything.
        """
        offsets = [int(m) for m in
                   __import__("re").findall(r"_probe_area\+(\d+)\(%rip\)",
                                             F._ENTRY_PROBE_ASM)]
        self.assertEqual(offsets, list(range(0, 128, 8)) + [128]
                         + list(range(136, 200, 8)))
        dump = F.HARNESS_C
        self.assertEqual(
            sorted(int(m) for m in
                   __import__("re").findall(r"_dump_area\+(\d+)\(%rip\)", dump)),
            offsets,
            "the two dumps are one layout: a difference between them has to "
            "mean a register moved, not that the tables drifted")

    def test_a_default_build_is_the_harness_it_was(self):
        """`probe=False` changes nothing: no stores, no output, no macro.

        Seventeen stores on a path that runs once per program is not a cost
        worth paying for a measurement nobody reads, and the harness is the
        oracle the rest of this tree trusts, so the default build has to be
        byte for byte what it was.
        """
        prog = _one(F.R.RAX, ("nop", F.X.encode_nop()))
        plain = F.harness_source([prog])
        self.assertNotIn("_probe_area+", plain,
                         "a default harness must not store the entry file")
        self.assertNotIn("#define PROBE_ON", plain,
                         "…and must not define the macro that guards it, or the "
                         "declaration, the stores and the print all come back")
        self.assertNotIn("__PROBE_ASM__", plain,
                         "the placeholder expands to an empty string, it is "
                         "not left as literal text")
        # With every `#ifdef PROBE_ON … #endif` region taken out — which is what
        # the preprocessor does for a default build — nothing of the probe is
        # left. Checking the needles one at a time would instead have to
        # rediscover that a `printf` inside a false `#ifdef` is harmless.
        import re as _re
        unguarded = _re.sub(r"#ifdef PROBE_ON\n.*?#endif\n", "", plain,
                            flags=_re.S)
        for needle in ("_probe_area", "PROBE_ON", 'printf("E '):
            self.assertNotIn(needle, unguarded,
                             "…and with the guarded regions removed nothing "
                             "of the probe is left: %r" % needle)
        asm_start = plain.index("__asm__(")
        asm_end = plain.index("_dump_stub_end:")
        before = F.HARNESS_C[F.HARNESS_C.index("__asm__("):
                             F.HARNESS_C.index("_dump_stub_end:")]
        self.assertEqual(
            plain[asm_start:asm_end].count("\n"),
            before.replace('"__PROBE_ASM__"', '""').count("\n"),
            "the default `__asm__` block is line for line what it was: the "
            "placeholder became an empty string and nothing else moved")

    def test_the_flags_word_compares_the_bits_pushfq_cannot_lose(self):
        """`pushfq` reads IF as 1 whatever the program asked for, and bit 1 is
        reserved-and-one; `eflags()` sets the second and not the first.

        A plain `==` therefore differs by exactly `0x200` on every program,
        which is how the first version of this reported 204 rows and no
        information. The comparison has to name the two bits that cannot agree
        and still require every OTHER bit to agree on its own — a bit nobody
        compares is allowed to disagree, which is what makes the narrowed mask
        a measurement rather than a way of making the check pass.
        """
        prog = _one(F.R.RAX, ("nop", F.X.encode_nop()))
        want = prog.regs[0:16] + [F.eflags(prog.flags)] + list(prog.xmm)

        def fake(got_words):
            """A `run_native` that reports one program as having run.

            `got_words=None` is the "ran and left no dump" case, which is a
            different failure from a register that is wrong and gets its own
            row rather than twenty-five of them.
            """
            rows = [("ran", {})]
            probes = {} if got_words is None else {0: got_words}

            def _run(programs, workdir, verbose=False, probe=False):
                return rows, 0, probes
            return _run

        real = F.run_native
        try:
            # IF alone, and on the FLAGS word only: not a row.
            with_if = list(want)
            with_if[16] |= 0x200
            F.run_native = fake(with_if)
            self.assertEqual(F.entry_probe_report([prog], "x")[0], [],
                             "the interrupt-enable bit is read as 1 by "
                             "`pushfq` whatever the program asked for, so "
                             "differing in it alone is not a disagreement")
            # CF alone: a row, and it names the flags word. This program's
            # flags already have CF set, so the flip is an XOR.
            bad = [w for w in want]
            bad[16] ^= F.EF_CF
            F.run_native = fake(bad)
            rows, n_fault = F.entry_probe_report([prog], "x")
            self.assertEqual([(r[0], r[1]) for r in rows], [(0, 16)],
                             "a carried flag that differs IS a disagreement")
            # A register alone: a row, naming the register's index.
            bad = [w for w in want]
            bad[3] ^= 0xff
            F.run_native = fake(bad)
            rows, _ = F.entry_probe_report([prog], "x")
            self.assertEqual([(r[0], r[1]) for r in rows], [(0, 3)])
            # An XMM alone: a row, naming the XMM's index.
            bad = [w for w in want]
            bad[17 + 5] ^= 0x1
            F.run_native = fake(bad)
            rows, _ = F.entry_probe_report([prog], "x")
            self.assertEqual([(r[0], r[1]) for r in rows], [(0, 22)])
            # No dump for a program that ran: a row, and the interesting one.
            F.run_native = fake(None)
            rows, _ = F.entry_probe_report([prog], "x")
            self.assertEqual([(r[0], r[1]) for r in rows], [(0, -1)],
                             "a program that ran and left no entry dump means "
                             "the stub never reached its own store, which is a "
                             "different failure from a register that is wrong")
        finally:
            F.run_native = real

    def test_the_entry_register_file_is_what_the_fuzzer_asked_for(self):
        """THE ACCEPTANCE CASE: the harness's one unread step, on real hardware.

        Five runs of the module's own census and random generators on this host
        (Apple silicon, `arch -x86_64`): 740 programs, 14 of which faulted, and
        **0 disagreeing words** — every one of the sixteen GPRs, the flags word
        and all eight XMM registers came back exactly as `init_block` asked. So
        the `HARNESS` rows cannot be this path, and what is left is the CPU's
        decode; `formal/x86_64_model_fuzz.py`'s module docstring says which
        encodings, and `HARNESS_SETCC_DESTS` says why those three.

        Two census cases per pool entry here rather than the three the recorded
        run used, because the test's job is to be runnable, not to reproduce a
        number — a form with no entry disagreement at two states has no reason
        to have one at a third.
        """
        if not shutil_which("clang"):
            self.skipTest("clang is not on PATH")
        try:
            with F.L.scratch_dir("x86_entry_probe_test") as workdir:
                cases = F.census_cases(random.Random(11), 2)
                bad, n_fault = F.entry_probe_report([p for _f, _l, p in cases],
                                                    workdir)
        except (RuntimeError, OSError) as exc:
            # No Rosetta, no `arch -x86_64`, no `MAP_FIXED` at the fixed address:
            # none of that is a verdict about the probe.
            self.skipTest("the native half did not run here: %s" % exc)
        self.assertEqual(
            [(pos, k) for pos, k, _w, _g in bad], [],
            "the entry register file must be what `init_block` said; "
            "%d program(s) faulted, which is their own doing and not a row"
            % n_fault)


def shutil_which(name):
    import shutil
    return shutil.which(name)


class TestTheVerdictIsAboutTheModel(unittest.TestCase):
    """The reporter's two rules, because each was WRONG and both were silent.

    Neither needs Lean and neither needs a native run: both are about which
    verdict a row gets, which is decided in Python from the program's bytes and
    the list of differing fields.
    """

    # ── minimisation ────────────────────────────────────────────────────
    def test_a_prefix_is_not_the_same_program_as_its_parent(self):
        """`minimise` hands back a PREFIX, and a prefix needs its own NAME.

        The name is the `index`, which is what the generated Lean file declares
        (`code_N`, `init_N`) and what `run_model` keys its answers by. Sharing
        it does not merge two programs politely: Lean rejects the second
        `def code_N` and still evaluates every `#eval!` against the FIRST, so
        `run_model` returns N copies of one program's answer and `evaluate`
        pairs each prefix's hardware dump with the FULL program's model result.

        Measured on the pre-fix tree (`-n 16 --ninstr 6 --seed 5`): six `WRONG`
        rows, every one minimised to a two-instruction prefix that AGREES when
        it is run on its own. The pin is on the generated text, because that is
        the whole of the mechanism and it is what a reader has to trust.
        """
        prog = _program([("nop", F.X.encode_nop()),
                         ("mov RAX, 1", F.X.encode_mov_r64_imm32(F.R.RAX, 1)),
                         ("add RAX, RCX", F.X.encode_add_r64_r64(F.R.RAX,
                                                                 F.R.RCX))])
        cands = [prog.prefix(k) for k in (1, 2, 3)]
        self.assertEqual(len(set(c.index for c in cands)), 3,
                         "three prefixes of one program are three programs, "
                         "and each needs its own index")
        src = F.lean_source(cands, 0x7FFF00000000)
        import re as _re
        decls = _re.findall(r"^def (\w+)", src, _re.M)
        self.assertEqual(len(decls), len(set(decls)),
                         "the generated Lean file declares a name twice, which "
                         "Lean rejects while still answering every `#eval!` "
                         "against the first: %s"
                         % sorted(n for n in set(decls)
                                  if decls.count(n) > 1))
        self.assertEqual([n for n in decls if n.startswith("code_")],
                         ["code_%d" % c.index for c in cands])

    def test_lean_source_refuses_two_programs_with_one_index(self):
        """The generator raises rather than emitting a file that half
        elaborates.

        A warning would be the wrong shape: the failure this prevents is not
        visible in the file (it elaborates and prints), it is visible only in
        the ANSWERS, which is the thing nobody reads.
        """
        prog = _program([("nop", F.X.encode_nop())])
        twin = F.Program(prog.index, [("mov RAX, 2",
                                       F.X.encode_mov_r64_imm32(F.R.RAX, 2))],
                         prog.regs, prog.xmm, prog.flags, prog.mem)
        with self.assertRaises(ValueError) as cm:
            F.lean_source([prog, twin], 0x7FFF00000000)
        self.assertIn(str(prog.index), str(cm.exception))

    def test_a_prefix_keeps_the_initial_state_and_the_bytes(self):
        """Everything else about a prefix is unchanged — only the name moves."""
        prog = _program([("nop", F.X.encode_nop()),
                         ("mov RAX, 1", F.X.encode_mov_r64_imm32(F.R.RAX, 1))])
        one = prog.prefix(1)
        self.assertEqual(one.code, prog.items[0][1])
        self.assertIs(one.regs, prog.regs)
        self.assertIs(one.mem, prog.mem)
        self.assertEqual(one.flags, prog.flags)

    # ── the HARNESS classes ──────────────────────────────────────────────
    def test_a_setcc_anomaly_is_a_harness_row_in_a_larger_program_too(self):
        """The documented `setcc` anomaly, wherever it appears in the program.

        The old rule required EVERY instruction to be a `setcc`, which is true of
        a one-instruction census case and false of every random program — so
        `-n 16 --ninstr 6 --seed 5` reported six `WRONG` rows and exited 1, all
        six of them the anomaly the module docstring says must be excluded. The
        rule now reads the bytes (`0f 9x c5`-`c7`) and asks whether the
        disagreement is exactly what that instruction's misbehaviour explains.
        """
        prog = _program([("mov RCX, 7", F.X.encode_mov_r64_imm32(F.R.RCX, 7)),
                         ("add RAX, RCX", F.X.encode_add_r64_r64(F.R.RAX,
                                                                 F.R.RCX)),
                         ("setbe RSI", F.X.encode_setbe(F.R.RSI))])
        # what the CPU does: leaves RSI alone, and sets byte 1 of RDX
        fields = [("rsi", 0x1111111111111111, 0x1111111111111110),
                  ("rdx", 0x2222222222222200, 0x2222222222220000)]
        why = F._impossible_on_hardware(prog, fields)
        self.assertIsNotNone(why,
                             "a program whose only difference is one byte of "
                             "RSI and one byte of RDX, and which contains "
                             "`setbe rsi`, is the documented anomaly")
        self.assertIn("rsi", why)

    def test_a_real_model_bug_is_still_a_model_bug(self):
        """The counter-direction, and the one that matters: what the new rule
        must NOT absorb.

        Four rows, each a shape the anomaly cannot produce: a whole register
        differing (a 32-bit operation differs in four bytes), a flag differing,
        a memory word differing, and a one-byte difference in a register with no
        anomalous `setcc` in the program at all.
        """
        setcc = F.X.encode_setbe(F.R.RSI)
        prog = _program([("mov RCX, 7", F.X.encode_mov_r64_imm32(F.R.RCX, 7)),
                         ("setbe RSI", setcc)])
        for label, fields in (
                ("a whole register", [("rax", 0x1111111111111111,
                                       0x2222222222222222)]),
                ("a flag", [("rsi", 0x1111111111111111, 0x1111111111111110),
                            ("zf", 1, 0)]),
                ("memory", [("mem[0]", 1, 0)]),
                ("a fourth register", [("rcx", 0x1111111111111111,
                                        0x1111111111111110)])):
            self.assertIsNone(F._impossible_on_hardware(prog, fields),
                              "%s differing is not the setcc anomaly and must "
                              "stay a model verdict" % label)

    def test_one_byte_of_a_register_with_no_anomalous_setcc_is_a_model_bug(self):
        """The shape, without the encoding: one byte of RSI and nothing else.

        This is the case the byte-pattern requirement exists for. A `setcc` into
        a destination that behaves (`0f 9x c4` is `rm` = `rsp`, which takes a
        SIB byte) is not this class, and neither is a model bug that happens to
        move one byte.
        """
        prog = _program([("setbe R9", F.X.encode_setbe(F.R.R9))])
        fields = [("r9", 0x1111111111111111, 0x1111111111111110)]
        self.assertIsNone(F._impossible_on_hardware(prog, fields))

    def test_the_modrm_bytes_are_the_definition_and_the_names_agree(self):
        """`HARNESS_SETCC_DESTS` is the reader-facing list; the ModRM byte is
        what the CPU decodes. Two tables that can disagree is one table too
        many, so this checks they have not."""
        self.assertEqual(sorted(F.HARNESS_SETCC_DESTS),
                         sorted(F.HARNESS_SETCC_MODRM))
        for reg in F.HARNESS_SETCC_DESTS:
            modrm = F.HARNESS_SETCC_MODRM[reg][0]
            idx = F.R[reg.upper()].value
            self.assertEqual(
                F._anomalous_setcc_dests(F.X.encode_setbe(F.R[reg.upper()])),
                {reg},
                "`setbe %s` must be %s and the byte must be the one the "
                "doc's measurement names" % (reg, hex(modrm)))
            self.assertEqual(modrm & 7, idx & 7,
                             "the ModRM byte's `rm` field IS the destination")


def _program(items, regs=None):
    """One `Program` with a distinguishable initial register file."""
    if regs is None:
        regs = [0x1111111111111111 * (j + 1) for j in range(16)]
        regs[F.R.RSP.value] = F.STACK_TOP_ABS
        regs[F.R.R13.value] = F.MEMBASE_ABS
        regs[F.R.R14.value] = F.MEMBASE_ABS
    return F.Program(0, items, regs, [0x2222222222222222] * 8,
                     {"cf": True, "zf": False, "sf": False, "of_": False},
                     [0] * F.DATA_N)


if __name__ == "__main__":
    unittest.main()
