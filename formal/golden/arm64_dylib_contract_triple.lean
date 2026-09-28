-- GOLDEN ARTIFACT -- NOT HAND-MAINTAINED.  Do not edit; regenerate.
--
-- This is the output of a dylib proof generator run on a REAL dylib, kept as
-- the reference for what a per-export contract is supposed to look like.  Its
-- purpose is to be REPLACED: once `formal/arm64_proof_gen.py` emits the
-- contract, this file is redundant and should be deleted, because two copies
-- of the same proof is one copy too many.
--
-- Subject:  arm64 dylib, export `triple`  (source: def triple(n) { return n * 3 })
-- Proves:   Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n * 3)
--           plus `triple_caller`, a caller discharging against it, and three
--           negative controls that REFUTE the identity spec, a wrong spec, and
--           show the caller's conclusion is a real equation rather than `True`.
-- Holes:    none -- 0 `sorry`, 0 `admit`, 0 `declaration uses sorry`.
-- Verifies: 0 errors against lib/{ProofLib,work,X86,Refine,Contracts}.olean
--           at commit 9c884c7-era ProofLib, i.e. WITH [2]'s step bound and
--           `total_of_halts` already landed.
--
-- Build inputs (sha256 prefix, for provenance):
--   m.mojo            9500e60a6937ce48
--   m.dylib           a0f85796e9399bee
--   m.dylib.manifest  3851785b4db1f464
--
-- The contract's own structure lives in lib/Contracts.lean; the emitter that
-- produces the tail of this file is in IR-3-to-2-dylib-contract-emitter.md.
--
-- NOTE: the byte list and the 30 per-instruction step lemmas below are the
-- generator's, copied verbatim.  That bulk is the cost of making this file
-- self-contained; it is not hand-written and is not the interesting part.

import ProofLib
import work
import Refine

set_option maxRecDepth 100000
set_option maxHeartbeats 20000000
set_option linter.unusedSimpArgs false
set_option linter.unusedVariables false

def dylib_code_list : List UInt8 :=
  [0xfd, 0x7b, 0xbf, 0xa9, 0xfd, 0x03, 0x00, 0x91, 0xf3, 0x53, 0xbf, 0xa9, 0x13, 0x00, 0x00, 0x91, 0xff, 0x83, 0x40, 0xd1, 0x60, 0x02, 0x00, 0x91, 0xe0, 0x0b, 0xbf, 0xa9, 0x60, 0x00, 0x80, 0x52, 0x01, 0x00, 0x00, 0x91, 0xe0, 0x0b, 0xc1, 0xa8, 0x00, 0x7c, 0x01, 0x9b, 0xff, 0x83, 0x40, 0x91, 0xf3, 0x53, 0xc1, 0xa8, 0xfd, 0x7b, 0xc1, 0xa8, 0xc0, 0x03, 0x5f, 0xd6, 0xc0, 0x03, 0x5f, 0xd6]

def dylib_code (addr : Nat) : UInt8 :=
  if addr < 4294967728 then 0
  else dylib_code_list.getD (addr - 4294967728) 0

def run_result_exit (st : Arm64State) (code : Nat → UInt8) (exit : Nat) (fuel : Nat) : UInt64 :=
  match arm64_exec_go_exit st code exit fuel with
  | some s => s.x0
  | none => 0

def run_pc_reached (st : Arm64State) (code : Nat → UInt8) (pc : Nat) (fuel : Nat) : Bool :=
  match arm64_exec_go_exit st code pc fuel with
  | some _ => true
  | none => false

def run_x0 (st : Arm64State) (code : Nat → UInt8) (pc : Nat) (fuel : Nat) : UInt64 :=
  match arm64_exec_go_exit st code pc fuel with
  | some s => s.x0
  | none => 0

theorem dylib_insn_0 :
  arm64_read_insn dylib_code 4294967728 = 0xa9bf7bfd := by
  rfl

theorem dylib_insn_1 :
  arm64_read_insn dylib_code 4294967732 = 0x910003fd := by
  rfl

theorem dylib_insn_2 :
  arm64_read_insn dylib_code 4294967736 = 0xa9bf53f3 := by
  rfl

theorem dylib_insn_3 :
  arm64_read_insn dylib_code 4294967740 = 0x91000013 := by
  rfl

theorem dylib_insn_4 :
  arm64_read_insn dylib_code 4294967744 = 0xd14083ff := by
  rfl

theorem dylib_insn_5 :
  arm64_read_insn dylib_code 4294967748 = 0x91000260 := by
  rfl

theorem dylib_insn_6 :
  arm64_read_insn dylib_code 4294967752 = 0xa9bf0be0 := by
  rfl

theorem dylib_insn_7 :
  arm64_read_insn dylib_code 4294967756 = 0x52800060 := by
  rfl

theorem dylib_insn_8 :
  arm64_read_insn dylib_code 4294967760 = 0x91000001 := by
  rfl

theorem dylib_insn_9 :
  arm64_read_insn dylib_code 4294967764 = 0xa8c10be0 := by
  rfl

theorem dylib_insn_10 :
  arm64_read_insn dylib_code 4294967768 = 0x9b017c00 := by
  rfl

theorem dylib_insn_11 :
  arm64_read_insn dylib_code 4294967772 = 0x914083ff := by
  rfl

theorem dylib_insn_12 :
  arm64_read_insn dylib_code 4294967776 = 0xa8c153f3 := by
  rfl

theorem dylib_insn_13 :
  arm64_read_insn dylib_code 4294967780 = 0xa8c17bfd := by
  rfl

theorem dylib_insn_14 :
  arm64_read_insn dylib_code 4294967784 = 0xd65f03c0 := by
  rfl

theorem dylib_step_ok_0 (s : Arm64State) (h : s.pc = 4294967728) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967728 = (2847898621 : UInt32) := by native_decide
  have h0 : ¬ ((2847898621 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2847898621 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2847898621 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2847898621 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2847898621 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2847898621 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2847898621 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2847898621 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ((2847898621 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2847898621 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2847898621 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2847898621 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2847898621 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2847898621 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2847898621 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2847898621 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2847898621 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2847898621 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2847898621 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2847898621 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2847898621 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2847898621 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2847898621 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2847898621 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2847898621 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_1 (s : Arm64State) (h : s.pc = 4294967732) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967732 = (2432697341 : UInt32) := by native_decide
  have h0 : ¬ ((2432697341 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2432697341 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2432697341 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2432697341 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2432697341 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2432697341 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2432697341 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2432697341 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2432697341 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2432697341 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2432697341 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2432697341 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2432697341 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2432697341 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2432697341 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2432697341 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2432697341 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2432697341 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2432697341 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2432697341 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2432697341 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2432697341 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2432697341 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2432697341 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2432697341 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_2 (s : Arm64State) (h : s.pc = 4294967736) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967736 = (2847888371 : UInt32) := by native_decide
  have h0 : ¬ ((2847888371 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2847888371 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2847888371 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2847888371 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2847888371 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2847888371 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2847888371 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2847888371 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ((2847888371 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2847888371 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2847888371 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2847888371 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2847888371 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2847888371 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2847888371 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2847888371 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2847888371 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2847888371 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2847888371 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2847888371 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2847888371 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2847888371 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2847888371 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2847888371 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2847888371 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_3 (s : Arm64State) (h : s.pc = 4294967740) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967740 = (2432696339 : UInt32) := by native_decide
  have h0 : ¬ ((2432696339 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2432696339 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2432696339 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2432696339 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2432696339 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2432696339 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2432696339 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2432696339 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2432696339 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2432696339 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2432696339 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2432696339 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2432696339 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2432696339 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2432696339 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2432696339 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2432696339 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2432696339 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2432696339 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2432696339 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2432696339 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2432696339 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2432696339 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2432696339 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2432696339 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_4 (s : Arm64State) (h : s.pc = 4294967744) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967744 = (3510666239 : UInt32) := by native_decide
  have h0 : ¬ ((3510666239 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3510666239 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3510666239 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3510666239 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3510666239 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3510666239 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3510666239 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3510666239 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3510666239 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3510666239 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3510666239 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3510666239 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3510666239 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3510666239 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((3510666239 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3510666239 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3510666239 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3510666239 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3510666239 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3510666239 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3510666239 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3510666239 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3510666239 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3510666239 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3510666239 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_5 (s : Arm64State) (h : s.pc = 4294967748) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967748 = (2432696928 : UInt32) := by native_decide
  have h0 : ¬ ((2432696928 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2432696928 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2432696928 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2432696928 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2432696928 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2432696928 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2432696928 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2432696928 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2432696928 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2432696928 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2432696928 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2432696928 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2432696928 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2432696928 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2432696928 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2432696928 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2432696928 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2432696928 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2432696928 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2432696928 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2432696928 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2432696928 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2432696928 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2432696928 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2432696928 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_6 (s : Arm64State) (h : s.pc = 4294967752) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967752 = (2847869920 : UInt32) := by native_decide
  have h0 : ¬ ((2847869920 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2847869920 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2847869920 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2847869920 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2847869920 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2847869920 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2847869920 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2847869920 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ((2847869920 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2847869920 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2847869920 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2847869920 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2847869920 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2847869920 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2847869920 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2847869920 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2847869920 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2847869920 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2847869920 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2847869920 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2847869920 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2847869920 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2847869920 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2847869920 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2847869920 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_7 (s : Arm64State) (h : s.pc = 4294967756) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967756 = (1384120416 : UInt32) := by native_decide
  have h0 : ¬ ((1384120416 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1384120416 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1384120416 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1384120416 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1384120416 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1384120416 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1384120416 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1384120416 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1384120416 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1384120416 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1384120416 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1384120416 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1384120416 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1384120416 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((1384120416 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1384120416 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1384120416 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1384120416 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1384120416 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1384120416 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1384120416 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1384120416 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1384120416 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1384120416 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((1384120416 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_8 (s : Arm64State) (h : s.pc = 4294967760) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967760 = (2432696321 : UInt32) := by native_decide
  have h0 : ¬ ((2432696321 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2432696321 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2432696321 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2432696321 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2432696321 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2432696321 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2432696321 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2432696321 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2432696321 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2432696321 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2432696321 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2432696321 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2432696321 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2432696321 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2432696321 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2432696321 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2432696321 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2432696321 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2432696321 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2432696321 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2432696321 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2432696321 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2432696321 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2432696321 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2432696321 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_9 (s : Arm64State) (h : s.pc = 4294967764) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967764 = (2831223776 : UInt32) := by native_decide
  have h0 : ¬ ((2831223776 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2831223776 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2831223776 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2831223776 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2831223776 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2831223776 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2831223776 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2831223776 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2831223776 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ((2831223776 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2831223776 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2831223776 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2831223776 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2831223776 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2831223776 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2831223776 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2831223776 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2831223776 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2831223776 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2831223776 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2831223776 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2831223776 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2831223776 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2831223776 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2831223776 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_10 (s : Arm64State) (h : s.pc = 4294967768) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967768 = (2600565760 : UInt32) := by native_decide
  have h0 : ¬ ((2600565760 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ((2600565760 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2600565760 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2600565760 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2600565760 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2600565760 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2600565760 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2600565760 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2600565760 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2600565760 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2600565760 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2600565760 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2600565760 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2600565760 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2600565760 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2600565760 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2600565760 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2600565760 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2600565760 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2600565760 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2600565760 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2600565760 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2600565760 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2600565760 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2600565760 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_11 (s : Arm64State) (h : s.pc = 4294967772) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967772 = (2436924415 : UInt32) := by native_decide
  have h0 : ¬ ((2436924415 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2436924415 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2436924415 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2436924415 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2436924415 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2436924415 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2436924415 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2436924415 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2436924415 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2436924415 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2436924415 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2436924415 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2436924415 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2436924415 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2436924415 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2436924415 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2436924415 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2436924415 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2436924415 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2436924415 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2436924415 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2436924415 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2436924415 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2436924415 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2436924415 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_12 (s : Arm64State) (h : s.pc = 4294967776) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967776 = (2831242227 : UInt32) := by native_decide
  have h0 : ¬ ((2831242227 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2831242227 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2831242227 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2831242227 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2831242227 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2831242227 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2831242227 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2831242227 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2831242227 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ((2831242227 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2831242227 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2831242227 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2831242227 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2831242227 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2831242227 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2831242227 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2831242227 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2831242227 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2831242227 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2831242227 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2831242227 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2831242227 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2831242227 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2831242227 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2831242227 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_13 (s : Arm64State) (h : s.pc = 4294967780) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967780 = (2831252477 : UInt32) := by native_decide
  have h0 : ¬ ((2831252477 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2831252477 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2831252477 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2831252477 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((2831252477 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2831252477 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2831252477 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2831252477 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2831252477 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ((2831252477 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2831252477 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2831252477 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2831252477 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2831252477 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((2831252477 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2831252477 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2831252477 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2831252477 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2831252477 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2831252477 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2831252477 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2831252477 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2831252477 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2831252477 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2831252477 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_step_ok_14 (s : Arm64State) (h : s.pc = 4294967784) :
  arm64_step s dylib_code ≠ none := by
  have hinsn : arm64_read_insn dylib_code 4294967784 = (3596551104 : UInt32) := by native_decide
  have h0 : ((3596551104 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3596551104 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3596551104 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3596551104 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3596551104 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3596551104 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3596551104 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3596551104 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3596551104 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3596551104 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3596551104 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3596551104 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3596551104 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3596551104 : UInt32) &&& (4292870144 : UInt32) = (169869312 : UInt32)) := by native_decide
  have h34 : ¬ ((3596551104 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3596551104 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3596551104 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3596551104 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3596551104 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3596551104 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3596551104 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3596551104 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3596551104 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3596551104 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3596551104 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51]

theorem dylib_sr_0 (s : Arm64State) (h : s.pc = 4294967728) :
  arm64_step s dylib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 29 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 30 s) } := by
  have hinsn : arm64_read_insn dylib_code 4294967728 = (2847898621 : UInt32) := by native_decide
  have hw : ((2847898621 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s dylib_code 4294967728 (2847898621 : UInt32) h hinsn hw

theorem dylib_sr_1 (s : Arm64State) (h : s.pc = 4294967732) :
  arm64_step s dylib_code = some (arm64_set_reg 29 s (s.sp + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn dylib_code 4294967732 = (2432697341 : UInt32) := by native_decide
  have hw : ((2432697341 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s dylib_code 4294967732 (2432697341 : UInt32) h hinsn hw

theorem dylib_sr_2 (s : Arm64State) (h : s.pc = 4294967736) :
  arm64_step s dylib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 19 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 20 s) } := by
  have hinsn : arm64_read_insn dylib_code 4294967736 = (2847888371 : UInt32) := by native_decide
  have hw : ((2847888371 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s dylib_code 4294967736 (2847888371 : UInt32) h hinsn hw

theorem dylib_sr_3 (s : Arm64State) (h : s.pc = 4294967740) :
  arm64_step s dylib_code = some (arm64_set_reg 19 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn dylib_code 4294967740 = (2432696339 : UInt32) := by native_decide
  have hw : ((2432696339 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s dylib_code 4294967740 (2432696339 : UInt32) h hinsn hw

theorem dylib_sr_4 (s : Arm64State) (h : s.pc = 4294967744) :
  arm64_step s dylib_code = some { s with sp := (s.sp - UInt64.ofNat 32) } := by
  have hinsn : arm64_read_insn dylib_code 4294967744 = (3510666239 : UInt32) := by native_decide
  have hw : ((3510666239 : UInt32) &&& 0xff800000) = 0xd1000000 := by native_decide
  exact work_step_sub_imm64 s dylib_code 4294967744 (3510666239 : UInt32) h hinsn hw

theorem dylib_sr_5 (s : Arm64State) (h : s.pc = 4294967748) :
  arm64_step s dylib_code = some (arm64_set_reg 0 s (arm64_reg 19 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn dylib_code 4294967748 = (2432696928 : UInt32) := by native_decide
  have hw : ((2432696928 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s dylib_code 4294967748 (2432696928 : UInt32) h hinsn hw

theorem dylib_sr_6 (s : Arm64State) (h : s.pc = 4294967752) :
  arm64_step s dylib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 s) } := by
  have hinsn : arm64_read_insn dylib_code 4294967752 = (2847869920 : UInt32) := by native_decide
  have hw : ((2847869920 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s dylib_code 4294967752 (2847869920 : UInt32) h hinsn hw

theorem dylib_sr_7 (s : Arm64State) (h : s.pc = 4294967756) :
  arm64_step s dylib_code = some (arm64_set_reg 0 s (UInt64.ofNat 3)) := by
  have hinsn : arm64_read_insn dylib_code 4294967756 = (1384120416 : UInt32) := by native_decide
  have hw : ((1384120416 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120416 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s dylib_code 4294967756 (1384120416 : UInt32) h hinsn hw

theorem dylib_sr_8 (s : Arm64State) (h : s.pc = 4294967760) :
  arm64_step s dylib_code = some (arm64_set_reg 1 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn dylib_code 4294967760 = (2432696321 : UInt32) := by native_decide
  have hw : ((2432696321 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s dylib_code 4294967760 (2432696321 : UInt32) h hinsn hw

theorem dylib_sr_9 (s : Arm64State) (h : s.pc = 4294967764) :
  arm64_step s dylib_code = some { (arm64_set_reg 2 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn dylib_code 4294967764 = (2831223776 : UInt32) := by native_decide
  have hw : ((2831223776 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s dylib_code 4294967764 (2831223776 : UInt32) h hinsn hw

theorem dylib_sr_10 (s : Arm64State) (h : s.pc = 4294967768) :
  arm64_step s dylib_code = some (arm64_set_reg 0 s (arm64_reg 0 s * arm64_reg 1 s)) := by
  have hinsn : arm64_read_insn dylib_code 4294967768 = (2600565760 : UInt32) := by native_decide
  have hw : ((2600565760 : UInt32) &&& 0xffe07c00) = 0x9b007c00 := by native_decide
  exact work_step_mul s dylib_code 4294967768 (2600565760 : UInt32) h hinsn hw

theorem dylib_sr_11 (s : Arm64State) (h : s.pc = 4294967772) :
  arm64_step s dylib_code = some { s with sp := (s.sp + UInt64.ofNat 32) } := by
  have hinsn : arm64_read_insn dylib_code 4294967772 = (2436924415 : UInt32) := by native_decide
  have hw : ((2436924415 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s dylib_code 4294967772 (2436924415 : UInt32) h hinsn hw

theorem dylib_sr_12 (s : Arm64State) (h : s.pc = 4294967776) :
  arm64_step s dylib_code = some { (arm64_set_reg 20 (arm64_set_reg 19 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn dylib_code 4294967776 = (2831242227 : UInt32) := by native_decide
  have hw : ((2831242227 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s dylib_code 4294967776 (2831242227 : UInt32) h hinsn hw

theorem dylib_sr_13 (s : Arm64State) (h : s.pc = 4294967780) :
  arm64_step s dylib_code = some { (arm64_set_reg 30 (arm64_set_reg 29 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn dylib_code 4294967780 = (2831252477 : UInt32) := by native_decide
  have hw : ((2831252477 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s dylib_code 4294967780 (2831252477 : UInt32) h hinsn hw

theorem dylib_sr_14 (s : Arm64State) (h : s.pc = 4294967784) :
  arm64_step s dylib_code = some { s with pc := s.x30.toNat } := by
  have hinsn : arm64_read_insn dylib_code 4294967784 = (3596551104 : UInt32) := by native_decide
  have hw : (3596551104 : UInt32) = (0xd65f03c0 : UInt32) := by native_decide
  exact work_step_ret s dylib_code 4294967784 (3596551104 : UInt32) h hinsn hw

/- What a caller can read off a result word.  [3] left this line to me
   explicitly rather than pick it, and it matters more than it looks: the new
   `Functional` quantifies over this list, so an EMPTY list makes the clause
   vacuous again -- vacuously, which is the exact defect the rest of this
   change exists to remove, and `vacuous_declarations` would NOT flag it
   because the definition is no longer the vacuous one.  `id` is the minimum
   that makes the clause bite: `Functional` then says two runs to the same
   result agree on the result word, which is a real fact about a real run.
   More projections can be added here as callers grow. -/
def dylib_observables : List (UInt64 → UInt64) := [id]

def dylib_export_0_triple : DylibExport :=
  { module := "m"
    symbol := "m_triple_9f63a2"
    entry := 4294967728
    arity := 1 }

def dylib_image : DylibImage :=
  { base := 4294967728
    codeSize := 60
    exports := [dylib_export_0_triple]
    code := dylib_code }

def dylib_exports : List DylibExport := dylib_image.exports

theorem dylib_exports_count : dylib_exports.length = 1 := rfl

theorem dylib_export_names_count :
    (work_export_names dylib_exports).length = dylib_exports.length :=
  work_export_names_length dylib_exports

theorem dylib_export_0_triple_in_image : DylibExport.InImage dylib_image dylib_export_0_triple :=
  (DylibExport.in_image_decide dylib_image dylib_export_0_triple).2 (by native_decide)

theorem dylib_export_0_triple_semantics_functional :
    DylibExport.Functional dylib_image dylib_export_0_triple dylib_observables := by
  intro n s1 s2 h1 h2 observable _
  rw [h1] at h2
  injection h2 with h
  simp [h]



import Contracts

namespace Inst

def triEntry : Nat := dylib_export_0_triple.entry
def triExit : Nat := dylib_image.base + dylib_image.codeSize

def triStart (n : UInt64) : Arm64State :=
  Contracts.startState dylib_image dylib_export_0_triple n

def triBody : Refine.Block :=
  { entry_pc := triEntry, pcs := [4294967728,4294967732,4294967736,4294967740,4294967744,4294967748,4294967752,4294967756,4294967760,4294967764,4294967768,4294967772,4294967776,4294967780,4294967784], step := fun s => S15 s }

def st0 (s : Arm64State) : Arm64State :=
  { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 29 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 30 s) }

def st1 (s : Arm64State) : Arm64State :=
  (arm64_set_reg 29 st0 s (st0 s.sp + UInt64.ofNat 0))

def st2 (s : Arm64State) : Arm64State :=
  { st1 s with sp := (st1 s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 st1 s.mem (st1 s.sp - UInt64.ofNat 16).toNat (arm64_reg 19 st1 s)) ((st1 s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 20 st1 s) }

def st3 (s : Arm64State) : Arm64State :=
  (arm64_set_reg 19 st2 s (arm64_reg 0 st2 s + UInt64.ofNat 0))

def st4 (s : Arm64State) : Arm64State :=
  { st3 s with sp := (st3 s.sp - UInt64.ofNat 32) }

def st5 (s : Arm64State) : Arm64State :=
  (arm64_set_reg 0 st4 s (arm64_reg 19 st4 s + UInt64.ofNat 0))

def st6 (s : Arm64State) : Arm64State :=
  { st5 s with sp := (st5 s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 st5 s.mem (st5 s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 st5 s)) ((st5 s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 st5 s) }

def st7 (s : Arm64State) : Arm64State :=
  (arm64_set_reg 0 st6 s (UInt64.ofNat 3))

def st8 (s : Arm64State) : Arm64State :=
  (arm64_set_reg 1 st7 s (arm64_reg 0 st7 s + UInt64.ofNat 0))

def st9 (s : Arm64State) : Arm64State :=
  { (arm64_set_reg 2 (arm64_set_reg 0 st8 s (mem_read_u64 st8 s.mem st8 s.sp.toNat)) (mem_read_u64 st8 s.mem (st8 s.sp + 8).toNat)) with sp := st8 s.sp + UInt64.ofNat 16 }

def st10 (s : Arm64State) : Arm64State :=
  (arm64_set_reg 0 st9 s (arm64_reg 0 st9 s * arm64_reg 1 st9 s))

def st11 (s : Arm64State) : Arm64State :=
  { st10 s with sp := (st10 s.sp + UInt64.ofNat 32) }

def st12 (s : Arm64State) : Arm64State :=
  { (arm64_set_reg 20 (arm64_set_reg 19 st11 s (mem_read_u64 st11 s.mem st11 s.sp.toNat)) (mem_read_u64 st11 s.mem (st11 s.sp + 8).toNat)) with sp := st11 s.sp + UInt64.ofNat 16 }

def st13 (s : Arm64State) : Arm64State :=
  { (arm64_set_reg 30 (arm64_set_reg 29 st12 s (mem_read_u64 st12 s.mem st12 s.sp.toNat)) (mem_read_u64 st12 s.mem (st12 s.sp + 8).toNat)) with sp := st12 s.sp + UInt64.ofNat 16 }

def st14 (s : Arm64State) : Arm64State :=
  { st13 s with pc := st13 s.x30.toNat }

def S1 (s : Arm64State) : Arm64State :=
  let t := st0 s
  if t.pc = (s).pc then { t with pc := (s).pc + 4 } else t

def S2 (s : Arm64State) : Arm64State :=
  let t := st1 S1 s
  if t.pc = (S1 s).pc then { t with pc := (S1 s).pc + 4 } else t

def S3 (s : Arm64State) : Arm64State :=
  let t := st2 S2 s
  if t.pc = (S2 s).pc then { t with pc := (S2 s).pc + 4 } else t

def S4 (s : Arm64State) : Arm64State :=
  let t := st3 S3 s
  if t.pc = (S3 s).pc then { t with pc := (S3 s).pc + 4 } else t

def S5 (s : Arm64State) : Arm64State :=
  let t := st4 S4 s
  if t.pc = (S4 s).pc then { t with pc := (S4 s).pc + 4 } else t

def S6 (s : Arm64State) : Arm64State :=
  let t := st5 S5 s
  if t.pc = (S5 s).pc then { t with pc := (S5 s).pc + 4 } else t

def S7 (s : Arm64State) : Arm64State :=
  let t := st6 S6 s
  if t.pc = (S6 s).pc then { t with pc := (S6 s).pc + 4 } else t

def S8 (s : Arm64State) : Arm64State :=
  let t := st7 S7 s
  if t.pc = (S7 s).pc then { t with pc := (S7 s).pc + 4 } else t

def S9 (s : Arm64State) : Arm64State :=
  let t := st8 S8 s
  if t.pc = (S8 s).pc then { t with pc := (S8 s).pc + 4 } else t

def S10 (s : Arm64State) : Arm64State :=
  let t := st9 S9 s
  if t.pc = (S9 s).pc then { t with pc := (S9 s).pc + 4 } else t

def S11 (s : Arm64State) : Arm64State :=
  let t := st10 S10 s
  if t.pc = (S10 s).pc then { t with pc := (S10 s).pc + 4 } else t

def S12 (s : Arm64State) : Arm64State :=
  let t := st11 S11 s
  if t.pc = (S11 s).pc then { t with pc := (S11 s).pc + 4 } else t

def S13 (s : Arm64State) : Arm64State :=
  let t := st12 S12 s
  if t.pc = (S12 s).pc then { t with pc := (S12 s).pc + 4 } else t

def S14 (s : Arm64State) : Arm64State :=
  let t := st13 S13 s
  if t.pc = (S13 s).pc then { t with pc := (S13 s).pc + 4 } else t

def S15 (s : Arm64State) : Arm64State :=
  let t := st14 S14 s
  if t.pc = (S14 s).pc then { t with pc := (S14 s).pc + 4 } else t

/-- THE SPEC, checked against the machine: the result register is `n * 3`. -/
theorem hreg : ∀ n : UInt64, arm64_reg 0 (S15 (triStart n)) = n * 3 := by
  intro n
  bv_decide

/-- `x30` survives the frame, so the return lands on the exit. -/
theorem hx30 : ∀ n : UInt64,
    arm64_reg 30 (S14 (triStart n)) = UInt64.ofNat triExit := by
  intro n
  bv_decide

theorem S1_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S1 s).pc = triEntry + 4 := by
  simp [S1, st0, S0]; omega

theorem S2_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S2 s).pc = triEntry + 8 := by
  simp [S2, st1, st0, S1]; omega

theorem S3_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S3 s).pc = triEntry + 12 := by
  simp [S3, st2, st1, st0, S2]; omega

theorem S4_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S4 s).pc = triEntry + 16 := by
  simp [S4, st3, st2, st1, st0, S3]; omega

theorem S5_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S5 s).pc = triEntry + 20 := by
  simp [S5, st4, st3, st2, st1, st0, S4]; omega

theorem S6_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S6 s).pc = triEntry + 24 := by
  simp [S6, st5, st4, st3, st2, st1, st0, S5]; omega

theorem S7_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S7 s).pc = triEntry + 28 := by
  simp [S7, st6, st5, st4, st3, st2, st1, st0, S6]; omega

theorem S8_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S8 s).pc = triEntry + 32 := by
  simp [S8, st7, st6, st5, st4, st3, st2, st1, st0, S7]; omega

theorem S9_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S9 s).pc = triEntry + 36 := by
  simp [S9, st8, st7, st6, st5, st4, st3, st2, st1, st0, S8]; omega

theorem S10_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S10 s).pc = triEntry + 40 := by
  simp [S10, st9, st8, st7, st6, st5, st4, st3, st2, st1, st0, S9]; omega

theorem S11_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S11 s).pc = triEntry + 44 := by
  simp [S11, st10, st9, st8, st7, st6, st5, st4, st3, st2, st1, st0, S10]; omega

theorem S12_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S12 s).pc = triEntry + 48 := by
  simp [S12, st11, st10, st9, st8, st7, st6, st5, st4, st3, st2, st1, st0, S11]; omega

theorem S13_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S13 s).pc = triEntry + 52 := by
  simp [S13, st12, st11, st10, st9, st8, st7, st6, st5, st4, st3, st2, st1, st0, S12]; omega

theorem S14_pc (s : Arm64State) (hpc : s.pc = triEntry) :
    (S14 s).pc = triEntry + 56 := by
  simp [S14, st13, st12, st11, st10, st9, st8, st7, st6, st5, st4, st3, st2, st1, st0, S13]; omega

theorem runsTo0 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 0 s = some (S0 s) := by
  rfl

theorem runsTo1 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 1 s = some (S1 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hs0 : arm64_runs dylib_code 1 s = arm64_runs dylib_code 0 (S1 s) := by
    show arm64_runs dylib_code 1 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  rw [hs0]

theorem runsTo2 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 2 s = some (S2 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 2 s = arm64_runs dylib_code 1 (S1 s) := by
    show arm64_runs dylib_code 2 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 1 S1 s = arm64_runs dylib_code 0 (S2 s) := by
    show arm64_runs dylib_code 1 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  rw [hs0, hs1]

theorem runsTo3 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 3 s = some (S3 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 3 s = arm64_runs dylib_code 2 (S1 s) := by
    show arm64_runs dylib_code 3 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 2 S1 s = arm64_runs dylib_code 1 (S2 s) := by
    show arm64_runs dylib_code 2 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 1 S2 s = arm64_runs dylib_code 0 (S3 s) := by
    show arm64_runs dylib_code 1 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  rw [hs0, hs1, hs2]

theorem runsTo4 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 4 s = some (S4 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 4 s = arm64_runs dylib_code 3 (S1 s) := by
    show arm64_runs dylib_code 4 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 3 S1 s = arm64_runs dylib_code 2 (S2 s) := by
    show arm64_runs dylib_code 3 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 2 S2 s = arm64_runs dylib_code 1 (S3 s) := by
    show arm64_runs dylib_code 2 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 1 S3 s = arm64_runs dylib_code 0 (S4 s) := by
    show arm64_runs dylib_code 1 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  rw [hs0, hs1, hs2, hs3]

theorem runsTo5 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 5 s = some (S5 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 5 s = arm64_runs dylib_code 4 (S1 s) := by
    show arm64_runs dylib_code 5 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 4 S1 s = arm64_runs dylib_code 3 (S2 s) := by
    show arm64_runs dylib_code 4 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 3 S2 s = arm64_runs dylib_code 2 (S3 s) := by
    show arm64_runs dylib_code 3 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 2 S3 s = arm64_runs dylib_code 1 (S4 s) := by
    show arm64_runs dylib_code 2 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 1 S4 s = arm64_runs dylib_code 0 (S5 s) := by
    show arm64_runs dylib_code 1 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4]

theorem runsTo6 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 6 s = some (S6 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 6 s = arm64_runs dylib_code 5 (S1 s) := by
    show arm64_runs dylib_code 6 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 5 S1 s = arm64_runs dylib_code 4 (S2 s) := by
    show arm64_runs dylib_code 5 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 4 S2 s = arm64_runs dylib_code 3 (S3 s) := by
    show arm64_runs dylib_code 4 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 3 S3 s = arm64_runs dylib_code 2 (S4 s) := by
    show arm64_runs dylib_code 3 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 2 S4 s = arm64_runs dylib_code 1 (S5 s) := by
    show arm64_runs dylib_code 2 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 1 S5 s = arm64_runs dylib_code 0 (S6 s) := by
    show arm64_runs dylib_code 1 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5]

theorem runsTo7 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 7 s = some (S7 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 7 s = arm64_runs dylib_code 6 (S1 s) := by
    show arm64_runs dylib_code 7 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 6 S1 s = arm64_runs dylib_code 5 (S2 s) := by
    show arm64_runs dylib_code 6 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 5 S2 s = arm64_runs dylib_code 4 (S3 s) := by
    show arm64_runs dylib_code 5 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 4 S3 s = arm64_runs dylib_code 3 (S4 s) := by
    show arm64_runs dylib_code 4 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 3 S4 s = arm64_runs dylib_code 2 (S5 s) := by
    show arm64_runs dylib_code 3 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 2 S5 s = arm64_runs dylib_code 1 (S6 s) := by
    show arm64_runs dylib_code 2 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 1 S6 s = arm64_runs dylib_code 0 (S7 s) := by
    show arm64_runs dylib_code 1 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6]

theorem runsTo8 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 8 s = some (S8 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 8 s = arm64_runs dylib_code 7 (S1 s) := by
    show arm64_runs dylib_code 8 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 7 S1 s = arm64_runs dylib_code 6 (S2 s) := by
    show arm64_runs dylib_code 7 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 6 S2 s = arm64_runs dylib_code 5 (S3 s) := by
    show arm64_runs dylib_code 6 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 5 S3 s = arm64_runs dylib_code 4 (S4 s) := by
    show arm64_runs dylib_code 5 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 4 S4 s = arm64_runs dylib_code 3 (S5 s) := by
    show arm64_runs dylib_code 4 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 3 S5 s = arm64_runs dylib_code 2 (S6 s) := by
    show arm64_runs dylib_code 3 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 2 S6 s = arm64_runs dylib_code 1 (S7 s) := by
    show arm64_runs dylib_code 2 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 1 S7 s = arm64_runs dylib_code 0 (S8 s) := by
    show arm64_runs dylib_code 1 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7]

theorem runsTo9 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 9 s = some (S9 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 9 s = arm64_runs dylib_code 8 (S1 s) := by
    show arm64_runs dylib_code 9 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 8 S1 s = arm64_runs dylib_code 7 (S2 s) := by
    show arm64_runs dylib_code 8 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 7 S2 s = arm64_runs dylib_code 6 (S3 s) := by
    show arm64_runs dylib_code 7 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 6 S3 s = arm64_runs dylib_code 5 (S4 s) := by
    show arm64_runs dylib_code 6 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 5 S4 s = arm64_runs dylib_code 4 (S5 s) := by
    show arm64_runs dylib_code 5 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 4 S5 s = arm64_runs dylib_code 3 (S6 s) := by
    show arm64_runs dylib_code 4 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 3 S6 s = arm64_runs dylib_code 2 (S7 s) := by
    show arm64_runs dylib_code 3 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 2 S7 s = arm64_runs dylib_code 1 (S8 s) := by
    show arm64_runs dylib_code 2 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  have hs8 : arm64_runs dylib_code 1 S8 s = arm64_runs dylib_code 0 (S9 s) := by
    show arm64_runs dylib_code 1 S8 s = _
    rw [dylib_sr_8 S8 s hpc8]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7, hs8]

theorem runsTo10 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 10 s = some (S10 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 10 s = arm64_runs dylib_code 9 (S1 s) := by
    show arm64_runs dylib_code 10 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 9 S1 s = arm64_runs dylib_code 8 (S2 s) := by
    show arm64_runs dylib_code 9 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 8 S2 s = arm64_runs dylib_code 7 (S3 s) := by
    show arm64_runs dylib_code 8 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 7 S3 s = arm64_runs dylib_code 6 (S4 s) := by
    show arm64_runs dylib_code 7 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 6 S4 s = arm64_runs dylib_code 5 (S5 s) := by
    show arm64_runs dylib_code 6 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 5 S5 s = arm64_runs dylib_code 4 (S6 s) := by
    show arm64_runs dylib_code 5 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 4 S6 s = arm64_runs dylib_code 3 (S7 s) := by
    show arm64_runs dylib_code 4 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 3 S7 s = arm64_runs dylib_code 2 (S8 s) := by
    show arm64_runs dylib_code 3 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  have hs8 : arm64_runs dylib_code 2 S8 s = arm64_runs dylib_code 1 (S9 s) := by
    show arm64_runs dylib_code 2 S8 s = _
    rw [dylib_sr_8 S8 s hpc8]
    rfl
  have hs9 : arm64_runs dylib_code 1 S9 s = arm64_runs dylib_code 0 (S10 s) := by
    show arm64_runs dylib_code 1 S9 s = _
    rw [dylib_sr_9 S9 s hpc9]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7, hs8, hs9]

theorem runsTo11 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 11 s = some (S11 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 11 s = arm64_runs dylib_code 10 (S1 s) := by
    show arm64_runs dylib_code 11 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 10 S1 s = arm64_runs dylib_code 9 (S2 s) := by
    show arm64_runs dylib_code 10 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 9 S2 s = arm64_runs dylib_code 8 (S3 s) := by
    show arm64_runs dylib_code 9 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 8 S3 s = arm64_runs dylib_code 7 (S4 s) := by
    show arm64_runs dylib_code 8 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 7 S4 s = arm64_runs dylib_code 6 (S5 s) := by
    show arm64_runs dylib_code 7 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 6 S5 s = arm64_runs dylib_code 5 (S6 s) := by
    show arm64_runs dylib_code 6 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 5 S6 s = arm64_runs dylib_code 4 (S7 s) := by
    show arm64_runs dylib_code 5 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 4 S7 s = arm64_runs dylib_code 3 (S8 s) := by
    show arm64_runs dylib_code 4 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  have hs8 : arm64_runs dylib_code 3 S8 s = arm64_runs dylib_code 2 (S9 s) := by
    show arm64_runs dylib_code 3 S8 s = _
    rw [dylib_sr_8 S8 s hpc8]
    rfl
  have hs9 : arm64_runs dylib_code 2 S9 s = arm64_runs dylib_code 1 (S10 s) := by
    show arm64_runs dylib_code 2 S9 s = _
    rw [dylib_sr_9 S9 s hpc9]
    rfl
  have hs10 : arm64_runs dylib_code 1 S10 s = arm64_runs dylib_code 0 (S11 s) := by
    show arm64_runs dylib_code 1 S10 s = _
    rw [dylib_sr_10 S10 s hpc10]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7, hs8, hs9, hs10]

theorem runsTo12 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 12 s = some (S12 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 12 s = arm64_runs dylib_code 11 (S1 s) := by
    show arm64_runs dylib_code 12 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 11 S1 s = arm64_runs dylib_code 10 (S2 s) := by
    show arm64_runs dylib_code 11 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 10 S2 s = arm64_runs dylib_code 9 (S3 s) := by
    show arm64_runs dylib_code 10 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 9 S3 s = arm64_runs dylib_code 8 (S4 s) := by
    show arm64_runs dylib_code 9 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 8 S4 s = arm64_runs dylib_code 7 (S5 s) := by
    show arm64_runs dylib_code 8 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 7 S5 s = arm64_runs dylib_code 6 (S6 s) := by
    show arm64_runs dylib_code 7 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 6 S6 s = arm64_runs dylib_code 5 (S7 s) := by
    show arm64_runs dylib_code 6 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 5 S7 s = arm64_runs dylib_code 4 (S8 s) := by
    show arm64_runs dylib_code 5 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  have hs8 : arm64_runs dylib_code 4 S8 s = arm64_runs dylib_code 3 (S9 s) := by
    show arm64_runs dylib_code 4 S8 s = _
    rw [dylib_sr_8 S8 s hpc8]
    rfl
  have hs9 : arm64_runs dylib_code 3 S9 s = arm64_runs dylib_code 2 (S10 s) := by
    show arm64_runs dylib_code 3 S9 s = _
    rw [dylib_sr_9 S9 s hpc9]
    rfl
  have hs10 : arm64_runs dylib_code 2 S10 s = arm64_runs dylib_code 1 (S11 s) := by
    show arm64_runs dylib_code 2 S10 s = _
    rw [dylib_sr_10 S10 s hpc10]
    rfl
  have hs11 : arm64_runs dylib_code 1 S11 s = arm64_runs dylib_code 0 (S12 s) := by
    show arm64_runs dylib_code 1 S11 s = _
    rw [dylib_sr_11 S11 s hpc11]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7, hs8, hs9, hs10, hs11]

theorem runsTo13 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 13 s = some (S13 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 13 s = arm64_runs dylib_code 12 (S1 s) := by
    show arm64_runs dylib_code 13 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 12 S1 s = arm64_runs dylib_code 11 (S2 s) := by
    show arm64_runs dylib_code 12 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 11 S2 s = arm64_runs dylib_code 10 (S3 s) := by
    show arm64_runs dylib_code 11 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 10 S3 s = arm64_runs dylib_code 9 (S4 s) := by
    show arm64_runs dylib_code 10 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 9 S4 s = arm64_runs dylib_code 8 (S5 s) := by
    show arm64_runs dylib_code 9 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 8 S5 s = arm64_runs dylib_code 7 (S6 s) := by
    show arm64_runs dylib_code 8 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 7 S6 s = arm64_runs dylib_code 6 (S7 s) := by
    show arm64_runs dylib_code 7 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 6 S7 s = arm64_runs dylib_code 5 (S8 s) := by
    show arm64_runs dylib_code 6 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  have hs8 : arm64_runs dylib_code 5 S8 s = arm64_runs dylib_code 4 (S9 s) := by
    show arm64_runs dylib_code 5 S8 s = _
    rw [dylib_sr_8 S8 s hpc8]
    rfl
  have hs9 : arm64_runs dylib_code 4 S9 s = arm64_runs dylib_code 3 (S10 s) := by
    show arm64_runs dylib_code 4 S9 s = _
    rw [dylib_sr_9 S9 s hpc9]
    rfl
  have hs10 : arm64_runs dylib_code 3 S10 s = arm64_runs dylib_code 2 (S11 s) := by
    show arm64_runs dylib_code 3 S10 s = _
    rw [dylib_sr_10 S10 s hpc10]
    rfl
  have hs11 : arm64_runs dylib_code 2 S11 s = arm64_runs dylib_code 1 (S12 s) := by
    show arm64_runs dylib_code 2 S11 s = _
    rw [dylib_sr_11 S11 s hpc11]
    rfl
  have hs12 : arm64_runs dylib_code 1 S12 s = arm64_runs dylib_code 0 (S13 s) := by
    show arm64_runs dylib_code 1 S12 s = _
    rw [dylib_sr_12 S12 s hpc12]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7, hs8, hs9, hs10, hs11, hs12]

theorem runsTo14 (s : Arm64State) (hpc : s.pc = triEntry) :
    arm64_runs dylib_code 14 s = some (S14 s) := by
  have hpc0 : (S0 s).pc = triEntry := hpc
  have hpc1 : (S1 s).pc = triEntry + 4 := by simp [S1, S0, st0]; omega
  have hs0 : arm64_runs dylib_code 14 s = arm64_runs dylib_code 13 (S1 s) := by
    show arm64_runs dylib_code 14 s = _
    rw [dylib_sr_0 s hpc0]
    rfl
  have hs1 : arm64_runs dylib_code 13 S1 s = arm64_runs dylib_code 12 (S2 s) := by
    show arm64_runs dylib_code 13 S1 s = _
    rw [dylib_sr_1 S1 s hpc1]
    rfl
  have hs2 : arm64_runs dylib_code 12 S2 s = arm64_runs dylib_code 11 (S3 s) := by
    show arm64_runs dylib_code 12 S2 s = _
    rw [dylib_sr_2 S2 s hpc2]
    rfl
  have hs3 : arm64_runs dylib_code 11 S3 s = arm64_runs dylib_code 10 (S4 s) := by
    show arm64_runs dylib_code 11 S3 s = _
    rw [dylib_sr_3 S3 s hpc3]
    rfl
  have hs4 : arm64_runs dylib_code 10 S4 s = arm64_runs dylib_code 9 (S5 s) := by
    show arm64_runs dylib_code 10 S4 s = _
    rw [dylib_sr_4 S4 s hpc4]
    rfl
  have hs5 : arm64_runs dylib_code 9 S5 s = arm64_runs dylib_code 8 (S6 s) := by
    show arm64_runs dylib_code 9 S5 s = _
    rw [dylib_sr_5 S5 s hpc5]
    rfl
  have hs6 : arm64_runs dylib_code 8 S6 s = arm64_runs dylib_code 7 (S7 s) := by
    show arm64_runs dylib_code 8 S6 s = _
    rw [dylib_sr_6 S6 s hpc6]
    rfl
  have hs7 : arm64_runs dylib_code 7 S7 s = arm64_runs dylib_code 6 (S8 s) := by
    show arm64_runs dylib_code 7 S7 s = _
    rw [dylib_sr_7 S7 s hpc7]
    rfl
  have hs8 : arm64_runs dylib_code 6 S8 s = arm64_runs dylib_code 5 (S9 s) := by
    show arm64_runs dylib_code 6 S8 s = _
    rw [dylib_sr_8 S8 s hpc8]
    rfl
  have hs9 : arm64_runs dylib_code 5 S9 s = arm64_runs dylib_code 4 (S10 s) := by
    show arm64_runs dylib_code 5 S9 s = _
    rw [dylib_sr_9 S9 s hpc9]
    rfl
  have hs10 : arm64_runs dylib_code 4 S10 s = arm64_runs dylib_code 3 (S11 s) := by
    show arm64_runs dylib_code 4 S10 s = _
    rw [dylib_sr_10 S10 s hpc10]
    rfl
  have hs11 : arm64_runs dylib_code 3 S11 s = arm64_runs dylib_code 2 (S12 s) := by
    show arm64_runs dylib_code 3 S11 s = _
    rw [dylib_sr_11 S11 s hpc11]
    rfl
  have hs12 : arm64_runs dylib_code 2 S12 s = arm64_runs dylib_code 1 (S13 s) := by
    show arm64_runs dylib_code 2 S12 s = _
    rw [dylib_sr_12 S12 s hpc12]
    rfl
  have hs13 : arm64_runs dylib_code 1 S13 s = arm64_runs dylib_code 0 (S14 s) := by
    show arm64_runs dylib_code 1 S13 s = _
    rw [dylib_sr_13 S13 s hpc13]
    rfl
  rw [hs0, hs1, hs2, hs3, hs4, hs5, hs6, hs7, hs8, hs9, hs10, hs11, hs12, hs13]

instance : Refine.BlockCert dylib_code triBody where
  runs := by
    intro st hpc
    have hlen : triBody.pcs.length = 15 := by rfl
    show arm64_runs dylib_code 15 st = some (triBody.step st)
    rw [triBody, runsTo15 st hpc]

def tripleBody : Contracts.ExportBody dylib_image dylib_export_0_triple where
  block := triBody
  entry := rfl
  cert := inferInstance
  atExit := by
    intro n
    have hx : S14 (triStart n).x30 = UInt64.ofNat triExit := hx30 n
    show (S15 (triStart n)).pc = triExit
    have : (S15 (triStart n)).pc = (S14 (triStart n)).x30.toNat := rfl
    rw [this, UInt64.toNat_ofNat hx]
  noEarly := by
    intro n u hu su hrun
    have hu' : u < 15 := by simpa [triBody] using hu
    interval_cases u
    · rw [runsTo0 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h]
      simp [S0, triStart, Contracts.startState]; omega
    · rw [runsTo1 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S1_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo2 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S2_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo3 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S3_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo4 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S4_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo5 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S5_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo6 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S6_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo7 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S7_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo8 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S8_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo9 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S9_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo10 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S10_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo11 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S11_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo12 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S12_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo13 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S13_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega
    · rw [runsTo14 (triStart n) rfl] at hrun
      injection hrun with h
      rw [h, S14_pc _ rfl]
      simp [triExit, triEntry, dylib_image] at *
      omega

/-- **THE CONTRACT, proved: this export computes `n * 3`.** -/
theorem triple_spec :
    Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n * 3) :=
  Contracts.agrees_of_body dylib_image dylib_export_0_triple tripleBody (fun n => n * 3)
    (by native_decide) hreg

/-- **A CALLER DISCHARGES AGAINST IT.** -/
theorem triple_caller :
    ∀ n : UInt64,
      Refine.DylibExportContract (Refine.dylibExportProg dylib_image dylib_export_0_triple)
        (fun n => n * 3) n :=
  Contracts.caller_uses_contract dylib_image dylib_export_0_triple (fun n => n * 3) triple_spec


/-- NEGATIVE CONTROL 1: the identity spec must NOT be provable for this export. -/
theorem ctl_identity_spec :
    ¬ Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n) := by
  intro h
  have := h 7
  simp [Refine.export_result, Refine.runProg, Refine.dylibExportProg] at this
  native_decide at this ⊢

/-- NEGATIVE CONTROL 2: a wrong closed-form spec must NOT be provable. -/
theorem ctl_wrong_spec :
    ¬ Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n + 1) := by
  intro h
  have := h 7
  simp [Refine.export_result, Refine.runProg, Refine.dylibExportProg] at this
  native_decide at this ⊢

/-- NON-VACUITY: the contract's conclusion is a real equation, not `True`. -/
theorem ctl_contract_is_real (n : UInt64) (s : Arm64State)
    (h : Refine.runProg (Refine.dylibExportProg dylib_image dylib_export_0_triple) n = some s) :
    s.x0 = n * 3 := triple_caller n s h

end Inst
