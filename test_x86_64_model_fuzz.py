#!/usr/bin/env python3
"""The model-fuzz harness's two UNREAD steps: its ENTRY path, and its VERDICTS.

`formal/x86_64_model_fuzz.py` is not a gate job — it is a tool. Until
2026-10-07 it carried a `HARNESS` verdict for a disagreement "no x86-64 CPU can
produce", for `mul`/`imul` flags and `setcc` into `rbp`/`rsi`/`rdi`. **Both were
wrong**: the `setcc` bytes were an encoder that omitted a REX prefix (so the CPU
was right to read `setbe ch`), and the flags were SF/ZF, which the SDM leaves
UNDEFINED after a multiply. The verdict is gone; what decides a row is now
`WRONG` (a model bug) or `AGREE`, with undefined flags skipped.

**The entry path.** The entry stub installs the register file out of
`init_block` with real `mov` instructions, and if those loads did not land every
field of every program would be a false disagreement. `--entry-probe` is that
read-back, and the first class here is its pins.

**The verdicts.** A row is `WRONG` (a model bug), `AGREE`, `NORUN` or `FAULT`,
and which one it gets is decided in Python from the program's bytes and the
list of differing fields. The rules were wrong, and silent in the worst way: a
random program containing one `setcc` into RBP was reported as a `WRONG` model
bug (the encoder's fault, not the model's), and `minimise` handed back a prefix
that agreed when run on its own. The second class here is Lean-free and
native-free on purpose — it is about which verdict a row gets, so it can be
asked without either half.

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
    """The reporter's rules, which decide a row's verdict from the program's
    bytes and the differing fields alone — no Lean, no native run.

    The `HARNESS` verdict is gone (see the module docstring): the `setcc` class
    was an encoder bug — the CPU was right about `0f 96 c5` — and the
    `mul`/`imul` class was undefined flags. What is left to pin is
    `undefined_flags`, because a flag it names must NOT be compared and a flag
    it does not name must be.
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

    # ── which flags are undefined ────────────────────────────────────────
    def test_a_multiply_leaves_sf_and_zf_undefined(self):
        """`MUL`/`IMUL` define CF/OF (does the product fit) and leave SF, ZF, AF
        and PF undefined, so a program whose LAST flag-writer is a multiply must
        skip exactly SF and ZF.

        This is the whole of what the old `HARNESS` "this host mislabels SF" row
        was: the model sets SF from the low word and Rosetta leaves it clear, and
        neither is wrong — the architecture promises nothing about it.
        """
        for text, enc in (
                ("imul RAX, RCX",
                 F.X.encode_imul_r64_r64(F.R.RAX, F.R.RCX)),
                ("imul RAX", F.X.encode_imul_r64_1op(F.R.RAX)),
                ("imul RAX, RCX, 4",
                 F.X.encode_imul_r64_r64_imm(F.R.RAX, F.R.RCX, 4)),
                ("mul RAX", F.X.encode_mul_r64(F.R.RAX))):
            self.assertEqual(F.undefined_flags(_program([(text, enc)])),
                             {"zf", "sf"}, text)

    def test_a_divide_leaves_all_four_undefined(self):
        """Intel SDM: "CF, OF, SF, ZF, AF, and PF are undefined" after DIV."""
        p = _program([("mov RCX, 7", F.X.encode_mov_r64_imm32(F.R.RCX, 7)),
                      ("cqo", F.X.encode_cqo()),
                      ("idiv RCX", F.X.encode_idiv_r64(F.R.RCX))])
        self.assertEqual(F.undefined_flags(p), {"zf", "sf", "cf", "of_"})

    def test_a_shift_leaves_of_undefined_unless_the_count_is_one(self):
        """`OF` is undefined for a shift count that is neither 0 nor 1, and a
        count of 0 moves NO flag at all — so with nothing undefined before it,
        a count of 0 leaves nothing undefined either."""
        for count, want in ((1, set()), (3, {"of_"}), (0, set()),
                            (64, {"of_"})):
            p = _program([("<< RAX, %d" % count,
                           F.X.encode_shift_r64_imm8("<<", F.R.RAX, count))])
            self.assertEqual(F.undefined_flags(p), want, "count %d" % count)

    def test_only_the_last_flag_writer_decides(self):
        """An earlier undefined-flag instruction does not taint a later defined
        one, and vice versa: the flags a run ends with are its last writer's."""
        p = _program([("idiv RCX", F.X.encode_idiv_r64(F.R.RCX)),
                      ("add RAX, RCX",
                       F.X.encode_add_r64_r64(F.R.RAX, F.R.RCX))])
        self.assertEqual(F.undefined_flags(p), set(),
                         "the `add` redefines all four flags")
        p2 = _program([("add RAX, RCX",
                        F.X.encode_add_r64_r64(F.R.RAX, F.R.RCX)),
                       ("mul RCX", F.X.encode_mul_r64(F.R.RCX))])
        self.assertEqual(F.undefined_flags(p2), {"zf", "sf"},
                         "the multiply is last and leaves SF/ZF undefined")

    def test_a_shift_by_zero_does_not_redefine_an_undefined_flag(self):
        """The measured seed-3 row: `... ; idiv rcx ; >>signed R9, 0` ends with
        the divide's undefined CF/SF/ZF, because a count of 0 moves no flag and
        the divide left all four undefined."""
        p = _program([("idiv RCX", F.X.encode_idiv_r64(F.R.RCX)),
                      (">>signed R9, 0",
                       F.X.encode_shift_r64_imm8(">>signed", F.R.R9, 0))])
        self.assertEqual(F.undefined_flags(p), {"zf", "sf", "cf", "of_"})

    def test_an_undefined_flag_reaches_the_setcc_destination_and_beyond(self):
        """A `setcc` after a multiply reads an undefined SF, so its result is
        undefined, and a later copy of it is undefined too.

        This is why `undefined_fields` is a dataflow pass and not a flag set:
        the measured `imul R10, RBP, 4 ; setge R11` differs in R11 alone, and a
        `mov` of that R11 into another register would differ there too.
        """
        p = _program([("imul RAX, RCX",
                       F.X.encode_imul_r64_r64(F.R.RAX, F.R.RCX)),
                      ("setge R11", F.X.encode_setge(F.R.R11)),
                      ("mov RSI, R11",
                       F.X.encode_mov_r64_r64(F.R.RSI, F.R.R11))])
        uf = F.undefined_fields(p)
        for field in ("sf", "r11", "rsi"):
            self.assertIn(field, uf)
        # …and a `setge` after an `add` is NOT undefined: the `add` defines SF.
        p2 = _program([("add RAX, RCX",
                        F.X.encode_add_r64_r64(F.R.RAX, F.R.RCX)),
                       ("setge R11", F.X.encode_setge(F.R.R11))])
        self.assertEqual(F.undefined_fields(p2), set())

    def test_not_does_not_write_flags(self):
        """`NOT` writes no flag, so a program whose only flag-shaped instruction
        is a `not` has no flag-writer and nothing undefined."""
        self.assertEqual(
            F.undefined_flags(_program([("not RAX",
                                         F.X.encode_not_r64(F.R.RAX))])),
            set())

    def test_a_differing_undefined_flag_is_not_compared(self):
        """`diff` with `undefined_flags` drops exactly the flags it names, and
        the counter-direction is the one that matters: a flag the program DID
        define is still compared and a difference there is still a model bug."""
        p = _program([("mul RAX", F.X.encode_mul_r64(F.R.RAX))])
        hw = {"regs": [0] * 16, "xmm": [0] * 8,
              "memq": [0] * (F.DATA_N // 8),
              "flags": {"zf": False, "sf": False, "cf": True, "of_": True}}
        mdl = {"regs": [0] * 16, "xmm": [0] * 8,
               "memq": [0] * (F.DATA_N // 8),
               "flags": {"zf": True, "sf": True, "cf": True, "of_": True}}
        self.assertEqual(F.diff(hw, mdl, F.undefined_flags(p)), [],
                         "SF and ZF are undefined after a multiply")
        mdl["flags"]["cf"] = False
        d = F.diff(hw, mdl, F.undefined_flags(p))
        self.assertEqual([f for f, _a, _b in d], ["cf"],
                         "CF is defined by the multiply and a difference IS a "
                         "model bug")


class TestThePoolDrawsABasePlusIndex(unittest.TestCase):
    """The two SIB-indexed forms are DRAWN, and drawn as an ADDRESS SUM.

    `test_formal_isa_census.py` decides a form has a fuzz draw by reading this
    module's source for the encoder reference, which is the right ratchet for
    "there is a draw". It cannot see whether the draw is the indexing form: a
    builder that emitted a `[base + disp]` access while naming
    `encode_mov_rm8_r8_idx` somewhere would satisfy the census and compare the
    wrong instruction. These pin the draw itself — the index register is
    LOADED from an in-window immediate before the access, that register and the
    base are the SIB's index and base with the REX bits that extend them, no
    displacement is present, and the resulting address is inside the one window
    both halves share.

    This is the claim the bug doc's `Done when` makes ("the harness actually
    comparing a `base + index` effective address rather than the forms being
    exempted"), asked of the generator instead of the census's text match.
    """

    INDEXED = ("mov_rm8_r8_idx", "movzx_r64_rm8_idx")

    def _builder(self, name):
        for bound, _weight, fn in F.POOL:
            if bound == name:
                return fn
        self.fail("%r is not a pool entry: the census's FUZZ row would then be "
                  "scored from a name nothing draws" % name)

    def test_the_index_value_keeps_the_address_in_the_compared_window(self):
        """Both registers and the offset come from the pools' own bounds.

        `_index_off` is the whole offset from MEMBASE (the SIB forms carry no
        displacement), and it is drawn over the whole window including the
        NEGATIVE half.  A negative offset is a register holding `2^64 + off`,
        so the `base + index` sum WRAPS through the top of the address space —
        that is the wrap `x86_eff_addr` states, and the address it lands on is
        still a window offset.  `GENERAL` is what excludes RSP, which SIB's
        index field encodes as "no index at all", and R13/R14, which are the
        bases.
        """
        rng = random.Random(3)
        wrapped = 0
        for _ in range(200):
            for size in (1, 2, 4, 8):
                base, index, off = F._mem_idx(rng, size)
                self.assertIn(base, F.MEM_BASES)
                self.assertIn(index, F.GENERAL)
                self.assertNotEqual(base, index)
                if off < 0:
                    wrapped += 1
                addr = (F.MEMBASE_ABS + off) % (1 << 64)
                self.assertGreaterEqual(
                    addr, F.REGION_BASE + F.DATA_OFF,
                    "an access at window offset %d leaves the compared window"
                    % off)
                self.assertLessEqual(
                    addr + size, F.REGION_BASE + F.DATA_OFF + F.DATA_N,
                    "an access of %d byte(s) at %d leaves the compared window"
                    % (size, off))
        self.assertGreater(
            wrapped, 0,
            "the draw never produced a negative offset, so the pool never "
            "compares a `base + index` sum that wraps — the case "
            "`x86_eff_addr` exists for")

    def test_the_access_is_sib_indexed_with_the_loaded_register(self):
        """The bytes, not just the text: ModRM names SIB, and the SIB names
        the index the preceding `mov` loaded. A disp form here would compare
        `[base + disp]`, which the pool already has, and would leave the new
        census rows covered by a draw that never adds a register."""
        import re as _re
        store = _re.compile(r"^mov \[(\w+)\+(\w+)\], (\w+)$")
        load = _re.compile(r"^movzx (\w+), \[(\w+)\+(\w+)\]$")

        for name in self.INDEXED:
            fn = self._builder(name)
            for seed in range(50):
                drawn = fn(random.Random(seed))
                self.assertEqual(len(drawn), 2,
                                 "the index has to be loaded first")
                (load_text, load_bytes), (access_text, access_bytes) = drawn
                m = _re.fullmatch(r"mov (\w+), (-?\d+)", load_text)
                self.assertIsNotNone(m, load_text)
                index = F.R[m.group(1)]
                off = int(m.group(2))
                self.assertEqual(load_bytes,
                                 F.X.encode_mov_r64_imm32(index, off),
                                 "the index's value must be the immediate the "
                                 "model and CPU both start from")

                if name == "mov_rm8_r8_idx":
                    mm = store.match(access_text)
                    self.assertIsNotNone(mm, access_text)
                    base, index_name, other = (F.R[mm.group(1)],
                                               F.R[mm.group(2)],
                                               F.R[mm.group(3)])
                else:
                    mm = load.match(access_text)
                    self.assertIsNotNone(mm, access_text)
                    other, base, index_name = (F.R[mm.group(1)],
                                               F.R[mm.group(2)],
                                               F.R[mm.group(3)])
                self.assertEqual(index_name, index,
                                 "the access must use the register just loaded")
                self.assertIn(base, F.MEM_BASES)

                body = access_bytes
                rex = None
                if 0x40 <= body[0] <= 0x4F:
                    rex = body[0]
                    body = body[1:]
                if name == "mov_rm8_r8_idx":
                    self.assertEqual(body[0], 0x88,
                                     "not the byte store opcode")
                    body = body[1:]
                else:
                    self.assertEqual(body[:2], b"\x0f\xb6",
                                     "not the byte load opcode")
                    body = body[2:]
                modrm = body[0]
                mod = modrm >> 6
                self.assertEqual((modrm & 7), 4,
                                 "r/m must select a SIB byte, or this is the "
                                 "base+disp form the pool already draws")
                sib = body[1]
                self.assertEqual(sib & 7, base.value & 7)
                self.assertEqual((sib >> 3) & 7, index.value & 7)
                self.assertEqual(sib >> 6, 0, "scale must be 1")
                if mod == 0:
                    self.assertNotIn(base, (F.R.RBP, F.R.R13),
                                     "mod=00 base=101 is the no-base form")
                    self.assertEqual(len(body), 2)
                else:
                    self.assertEqual(mod, 1)
                    self.assertIn(base, (F.R.RBP, F.R.R13))
                    self.assertEqual(body[2], 0, "a disp8 of 0 is required")
                    self.assertEqual(len(body), 3)

                # REX: the two register fields that are not in the ModRM byte
                # are extended here, and REX.W is clear on both forms.
                if name == "mov_rm8_r8_idx":
                    needs_rex = (base.value >= 8 or index.value >= 8
                                 or other.value >= 8 or other.value in (4, 5, 6, 7))
                else:
                    needs_rex = True
                self.assertEqual(rex is not None, needs_rex,
                                 "REX present iff a bit is set (or an 8-bit "
                                 "operand needs one): %s %s" %
                                 (name, access_text))
                if rex is not None:
                    self.assertEqual((rex >> 2) & 1, 1 if other.value >= 8 else 0)
                    self.assertEqual((rex >> 1) & 1, 1 if index.value >= 8 else 0)
                    self.assertEqual(rex & 1, 1 if base.value >= 8 else 0)
                    self.assertFalse((rex >> 3) & 1, "REX.W must be clear")

                addr = (F.MEMBASE_ABS + off) % (1 << 64)
                self.assertGreaterEqual(addr, F.REGION_BASE + F.DATA_OFF)
                self.assertLessEqual(addr + 1,
                                     F.REGION_BASE + F.DATA_OFF + F.DATA_N,
                                     "the compared byte is outside the window")


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


class TestTheEffectiveAddressWraps(unittest.TestCase):
    """`base + index*scale + disp` is computed modulo 2^64, like the hardware.

    The measured defect — `base + index*scale + disp` was added as a `Nat`, so a
    sum above 2^64 was not truncated and a negative one clamped at 0 — is one
    `movzx rax, [r13+r14]` at `r14 = 2^64 - 1`: R13 is `MEMBASE_ABS`, so
    `r13 + r14` wraps on the CPU to `MEMBASE_ABS - 1`, window offset 63, and the
    hardware loads the `0x13` parked there.  The model used to add the index as
    a `Nat` with no truncation, land at `MEMBASE_ABS + 2^64 - 1`, read `0` from
    outside `[dataLo, dataLo+dataN)`, and report `rax = 0`.

    The program is constructed directly rather than drawn from the pool so the
    regression is this exact address and not a seed; the pool's own draw of the
    same case is pinned by `TestThePoolDrawsABasePlusIndex`.
    """

    WINDOW_OFFSET = F.DATA_N // 2 - 1
    """Where `MEMBASE_ABS - 1` lands in the compared window: `MEMBASE` is the
    window's centre, so one byte below it is `DATA_N//2 - 1`."""

    def _wrapping_program(self):
        regs = [0] * 16
        regs[F.R.RSP.value] = F.STACK_TOP_ABS
        regs[F.R.R13.value] = F.MEMBASE_ABS
        regs[F.R.R14.value] = (1 << 64) - 1
        mem = [0] * F.DATA_N
        mem[self.WINDOW_OFFSET] = 0x13
        return F.Program(
            0,
            [("movzx RAX, [R13+R14]",
              F.X.encode_movzx_r64_rm8_idx(F.R.RAX, F.R.R13, F.R.R14))],
            regs, [0] * 8,
            {"cf": False, "zf": False, "sf": False, "of_": False}, mem)

    def _lean_and_lib(self):
        root = F.L._default_root()
        lean = F.L.find_lean(root)
        if not lean:
            self.skipTest("no `lean` binary found")
        lib = os.path.join(root, "lib")
        F.L.ensure_library(lean, lib)
        return lean, lib

    def test_the_model_loads_the_wrapped_address(self):
        """The model-only half: `rax` is the byte at `MEMBASE_ABS - 1`.

        This is the assertion that fails on the pre-fix tree — the address it
        computed was outside the window `mem_N` answers, so it read 0 — and it
        needs no CPU, so the regression is checked wherever Lean runs.
        """
        prog = self._wrapping_program()
        lean, lib = self._lean_and_lib()
        exit_pc = F.REGION_BASE + F.CODE_OFF + len(prog.code)
        with F.L.scratch_dir("x86_eff_addr_model_test") as workdir:
            got = F.run_model(lean, [prog], exit_pc, lib, workdir)
        self.assertIn(0, got, "the model reported nothing for the program")
        self.assertIsNotNone(got[0], "x86_step returned none")
        self.assertEqual(
            got[0]["regs"][0], 0x13,
            "the effective address must wrap: `r13 + (2^64 - 1)` is "
            "`MEMBASE_ABS - 1`, window offset %d, where the `0x13` is; the "
            "model read %#x" % (self.WINDOW_OFFSET, got[0]["regs"][0]))

    def test_the_documented_program_reports_AGREE(self):
        """The `Done when`'s acceptance: the CPU and the model agree.

        A model-only assertion cannot tell a correct wrap from a second wrong
        answer that happens to land in the window; the hardware dump can.
        """
        if not shutil_which("clang"):
            self.skipTest("clang is not on PATH")
        prog = self._wrapping_program()
        lean, lib = self._lean_and_lib()
        with F.L.scratch_dir("x86_eff_addr_agree_test") as workdir:
            try:
                res, _stub = F.evaluate(lean, [prog], lib, workdir)
            except (RuntimeError, OSError) as exc:
                self.skipTest("the native half did not run here: %s" % exc)
        status, detail = res[0][1], res[0][2]
        self.assertEqual(status, "AGREE",
                         "`movzx rax, [r13+r14]` at r14 = 2^64 - 1: %s %s"
                         % (status, detail))


if __name__ == "__main__":
    unittest.main()
