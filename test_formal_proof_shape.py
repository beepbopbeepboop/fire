#!/usr/bin/env python3
r"""`tools/formal_proof_shape.py`'s text handling, without running Lean.

    python3 test_formal_proof_shape.py [-v]

WHY THIS FILE IS LEAN-FREE, AND WHY IT EXISTS AT ALL
-----------------------------------------------------
`tools/formal_proof_shape.py` answers two questions about a generated proof that
`bugs/FORMAL_the_arm64_proof_time_floor_is_one_composition_theorem.md` needed:
where the seconds go (`--mode profile`) and what the expensive tactic is still
trying to prove (`--mode goal`). Both cost one `lean` run over a 250 KB
generated file — 12-20 s and ~2 GB each — so the instrument itself is far more
expensive to exercise than the text it manipulates.

Everything below is therefore tested WITHOUT Lean, against hand-written
proof text shaped like a real generated one, and the tool's own Lean halves are
left to the doc's "Reproducing" section. **What that split buys is the failure
this file exists to catch: a transformation that silently stops matching.** The
tool finds its work by SPELLING (`TERMINAL_FLOW`, the emitter's own `simp
+decide only [h8, mojo, …` line), so when the emitter's terminal flow changes
shape the tool stops instrumenting and reports `flows 0` — which reads as a
clean run, not as a broken instrument. `test_the_flow_finding_survives_the_emitter`
pins the spelling against the EMITTER ITSELF (`formal/arm64_proof_gen.py`'s
source), so the two cannot drift apart silently, and `test_the_instrumented_text_still_has_one_flow`
pins that instrumenting one flow leaves the others alone.
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_proof_shape as S  # noqa: E402


# A generated proof reduced to what the tool reads: two blocks, four terminal
# value flows, and the closers that follow each.  The shapes here are the ones
# the tool's regexes and rewrites have to survive, and the comment on each says
# which.
PROOF = """import ProofLib
import Init.System.IO

def bitops_b0_qT0 (st : Arm64State) : Arm64State :=
  { st with x0 := st.x0 }

theorem bitops_b0_runs (st : Arm64State) : True := by rfl

theorem bitops_compiles_correctly_universal (n : UInt64) :
    (match runProg bitops_prog n with
     | some s => s.x0 = mojo n
     | none => False) := by
  rw [hhit_0]
  rw [hsid_0]
      -- terminal value flow: (s_0).x0 = mojo n
  have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, mojo, bitops_go, hsid_0, bitops_b0_qT0]
      all_goals try rfl
      all_goals try simp [mem_read_after_write_u64]
      all_goals try bv_decide
      all_goals try omega
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: walk-terminal
  rw [hhit_1]
  rw [hsid_1]
      -- terminal value flow: (s_1).x0 = mojo n
  have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, mojo, bitops_go, hsid_1, bitops_b1_qT0]
      all_goals try rfl
      all_goals try simp [mem_read_after_write_u64]
      all_goals try bv_decide
      all_goals try omega
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: walk-terminal
  rw [hhit_2]
  rw [hsid_2]
      -- terminal value flow: (s_2).x0 = mojo n
  have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, mojo, bitops_go, hsid_2, bitops_b2_qT0]
      all_goals try rfl
      all_goals try simp [mem_read_after_write_u64]
      all_goals try bv_decide
      all_goals try omega
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: walk-terminal
  rw [hhit_3]
  rw [hsid_3]
      -- terminal value flow: (s_3).x0 = mojo n
  have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, mojo, bitops_go, hsid_3, bitops_b3_qT0]
      all_goals try rfl
      all_goals try simp [mem_read_after_write_u64]
      all_goals try bv_decide
      all_goals try omega
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: walk-terminal
"""

PROFILE = """
simp took 144ms
simp took 1.17s
tactic execution of Lean.Parser.Tactic.omega took 168ms
tactic execution of Lean.Parser.Tactic.omega took 12ms
type checking took 7.56s
blocked (unaccounted) took 4526ms
import took 640ms
"""

TRACE = """hc_2 : ¬arm64_matches_condition 2 s_2.nzcv = true
⊢ match arm64_go_exit s_2 bitops_code 4294968180 (200000 + 48 * n.toNat - 11) with
  | some s => s.x0 = mojo n
  | none => False
case pos
hpc_0 : st.pc = 4294967988
⊢ match
    some
      (bitops_b4_qT29
        { x0 := s_2.x0, x1 := s_2.x1, mem := s_2.mem }) with
  | some s => s.x0 = mojo n
  | none => False
"""


class TestProfileParsing(unittest.TestCase):
    def test_milliseconds_and_seconds_are_both_seconds_out(self):
        """The unit is in the LINE, not in the number.

        This is not a style row. The tool's first version captured the number
        without its unit and divided by 1000 only when the captured text ended
        in `ms` — which it never does, because the regex consumed the unit — so
        every `took 168ms` was reported as **168 seconds** and `simp`'s total
        came out at 4526 s against a 19.8 s file. The unit is now a captured
        group and this case is the one that would have caught it.
        """
        ranked = S.parse_profile(PROFILE)
        got = dict(ranked)
        self.assertAlmostEqual(got["simp"], 0.144 + 1.17, places=6)
        self.assertAlmostEqual(got["tactic execution of "
                                    "Lean.Parser.Tactic.omega"], 0.180,
                               places=6)
        self.assertAlmostEqual(got["type checking"], 7.56, places=6)
        self.assertAlmostEqual(got["blocked (unaccounted)"], 4.526, places=6)

    def test_repeats_are_summed_and_the_result_is_ranked(self):
        """Eight `simp took` lines are ONE `simp` row, worst first.

        `formal/examples/bitops.mojo` prints `simp took` once per call, so a
        reader who is handed the lines has to add them up by hand — and that is
        how a 7-second cost gets reported as 0.9. The order is the ranking, so
        it is part of the answer rather than presentation.
        """
        ranked = S.parse_profile(PROFILE)
        self.assertEqual(ranked[0][0], "type checking")
        self.assertEqual([w for w, _ in ranked],
                         sorted((w for w, _ in ranked),
                                key=lambda w: -dict(ranked)[w]))
        self.assertEqual(S.parse_profile(""), [])


class TestFlowFinding(unittest.TestCase):
    def test_flows_are_found_by_spelling_and_in_source_order(self):
        at = S.flow_lines(PROOF)
        self.assertEqual(len(at), 4, f"found {len(at)} flow(s), expected 4")
        self.assertEqual(at, sorted(at))

    def test_the_flow_finding_survives_the_emitter(self):
        """The spelling must still be the EMITTER's, not only the fixture's.

        `formal/arm64_proof_gen.py` writes the terminal flow as an f-string, so
        the tool's literal cannot be pasted from the source; what can be pinned
        is that the pieces the f-string interpolates are still there and still
        in that order around it. A change to the emitter's terminal flow that
        renames `mojo` or moves the `_VSP` tail out of the same call would
        otherwise leave the tool reporting `flows 0` — a clean run of an
        instrument that did nothing.
        """
        src = open(os.path.join(HERE, "formal", "arm64_proof_gen.py")).read()
        i = src.find('A(f"{IND}simp {_sm} [h8, {_mojo}{_goid}{simp_names}, {_VSP}"')
        self.assertNotEqual(i, -1,
                            "the emitter no longer writes the terminal flow as "
                            "`simp [h8, <mojo>, <simp_names>, <VSP>]`; "
                            "tools/formal_proof_shape.py's TERMINAL_FLOW "
                            "spelling has to be updated with it")
        window = src[i:i + 1400]
        for piece in ("all_goals try rfl", "all_goals try omega"):
            self.assertIn(piece, window,
                          f"the emitter no longer emits `{piece}` right after "
                          f"the terminal simp, so the tool's closer-stripping "
                          f"would leave them in and Lean would report 'no "
                          f"goals to be solved' for each")

    def test_instrumenting_one_flow_leaves_the_others_alone(self):
        """Exactly ONE flow stops being a flow, and it is the one asked for.

        The traced flow's `simp +decide only` becomes `trace_state`, so the
        count drops by exactly one and the SURVIVORS are the same lines: if the
        rewriting dropped a line from the middle, every later flow would shift
        up and the report's `--which N` would silently mean a different flow
        from one run to the next.
        """
        before = [l for l in PROOF.split("\n") if l.startswith(S.TERMINAL_FLOW)]
        inst, holes = S.instrument(PROOF, 2)
        after = [l for l in inst.split("\n") if l.startswith(S.TERMINAL_FLOW)]
        self.assertEqual(len(after), len(before) - 1)
        self.assertEqual(after, [l for i, l in enumerate(before) if i != 1],
                         "the surviving flows must be the same LINES: if the "
                         "rewriting dropped a line from the middle, a later "
                         "flow's text would move and --which N would mean a "
                         "different flow from one run to the next")
        self.assertGreaterEqual(holes, 1)
        self.assertEqual(inst.count("trace_state"), 1,
                         "instrumenting one flow must not trace the others, or "
                         "the report's goal count is the number of flows")

    def test_the_flow_closers_are_gone_and_the_leaf_is_readmitted(self):
        """The closers go, and ONE `sorry` comes back.

        The flow's own `all_goals try …` lines are tactics for a goal
        `trace_state` has already printed, and leaving them in makes Lean report
        "no goals to be solved" once per line. The leaf has to be admitted
        explicitly, because the leaf WAS one of the removed lines.
        """
        inst, holes = S.instrument(PROOF, 1)
        tail = inst[inst.find("trace_state"):inst.find("trace_state") + 400]
        self.assertNotIn("all_goals try grind", tail)
        self.assertNotIn("all_goals try bv_decide", tail)
        self.assertIn("first | done | sorry", tail)
        self.assertEqual(holes, inst.count("first | done | sorry") -
                         PROOF.count("first | done | sorry") + 1)

    def test_which_past_the_end_answers_with_the_last_flow(self):
        """"there is only one" beats an index error."""
        inst, holes = S.instrument(PROOF, 99)
        self.assertIn("trace_state", inst)
        self.assertEqual(inst.count("trace_state"), 1)
        self.assertGreaterEqual(holes, 1)
        self.assertEqual(S.instrument("no flows here\n", 1), ("no flows here\n", 0))


class TestGoalReading(unittest.TestCase):
    def test_every_goal_is_returned_not_just_the_last(self):
        """`trace_state` prints one state PER GOAL, and the last one is not
        always the expensive one.

        Measured on `formal/examples/bitops.mojo` with the tool's own
        `--mode goal --which 1`: two goals printed, and the first is 693
        characters while the second is 23856 — the tool's first version
        returned the last `⊢` and so reported the walk's intermediate goal as
        "the residual goal", which understates the thing the doc is about by
        more than an order of magnitude.
        """
        goals = S.residual_goals(TRACE)
        self.assertEqual(len(goals), 2, f"got {len(goals)} goal(s)")
        self.assertTrue(goals[0].startswith("⊢ match arm64_go_exit"))
        self.assertIn("bitops_b4_qT29", goals[1])

    def test_the_size_of_a_goal_counts_what_costs(self):
        """Chars, lines, and the fully-expanded state literals.

        The last of those is the number the doc's next step needs: on
        `bitops` the largest terminal-flow goal carries 33 of them, each a
        31-field structure, and that is what a `simp +decide only` over 107
        names is being asked to traverse. It is counted as `{ x0 := ` because
        that is how Lean PRINTS the expansion; whether the elaborated TERM is
        equally large is a separate measurement the tool does not make, and a
        reader should not read it as one.
        """
        goals = S.residual_goals(TRACE)
        chars, lines, literals = S.goal_size(goals[1])
        self.assertEqual(chars, len(goals[1]))
        self.assertEqual(lines, len(goals[1].split("\n")))
        self.assertEqual(literals, 1)
        chars0, _l, lit0 = S.goal_size(goals[0])
        self.assertEqual(lit0, 0, "a goal with no state literal must count 0")

    def test_no_goals_is_an_empty_list_not_a_crash(self):
        self.assertEqual(S.residual_goals(""), [])
        self.assertEqual(S.goal_size(""), (0, 1, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)