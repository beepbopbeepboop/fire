#!/usr/bin/env python3
"""The model-fuzz harness's ENTRY path, which nothing else reads back.

`formal/x86_64_model_fuzz.py` is not a gate job — it is a tool, and its two
`HARNESS` verdict rows (`mul`/`imul` flags, `setcc` into `rbp`/`rsi`/`rdi`) are
the ones a reader must NOT go looking for in `lib/X86.lean`. Deciding them needs
the one step of the harness that nothing reads: the entry stub installs the
register file out of `init_block` with real `mov` instructions, and if those
loads did not land every field of every program would be a false disagreement.
`--entry-probe` is that read-back, and these are its pins.

**Not registered in `tools/suite.py`** (this session's rules forbid registering
without being asked), so run it directly:

    python3 tools/memslot.py --gb 8 --label t -- python3 test_x86_64_model_fuzz.py

The three text cases are Lean-free and take no native run. The fourth compiles
the harness `clang -arch x86_64` and runs it `arch -x86_64`, and SKIPS where
that is not available rather than passing quietly — on a host that cannot run
x86-64 code there is no entry register file to check.
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


if __name__ == "__main__":
    unittest.main()
