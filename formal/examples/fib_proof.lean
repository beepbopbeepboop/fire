import ProofLib
import work
import Refine

set_option maxRecDepth 100000
set_option maxHeartbeats 20000000
set_option linter.unusedSimpArgs false
set_option linter.unusedVariables false


/-- Mojo semantics: direct Lean model of the source code. -/
def fib_model : Nat → UInt64
  | 0 => UInt64.ofNat 0
  | 1 => UInt64.ofNat 1
  | n + 2 => fib_model n + fib_model (n + 1)

theorem fib_model_lt2 {n : Nat} (h : n < 2) :
    fib_model n = UInt64.ofNat n := by
  have hc : n = 0 ∨ n = 1 := by omega
  rcases hc with rfl | rfl <;> rfl

theorem fib_model_ge2 {n : Nat} (h : 2 ≤ n) :
    fib_model n = fib_model (n - 2) + fib_model (n - 1) := by
  rw [show n = (n - 2) + 2 from by omega, fib_model,
      show (n - 2) + 2 - 2 = n - 2 from by omega,
      show (n - 2) + 1 = n - 1 from by omega,
      show (n - 2) + 2 - 1 = n - 1 from by omega]

/-- The semantic model as a UInt64 -> UInt64 function. -/
def mojo (n : UInt64) : UInt64 :=
  fib_model n.toNat

/- AST for fib (mirrors source code). -/
def ast : MojoFunc := MojoFunc.mk "fib" ["n"] ([MojoStmt.ifstmt ((MojoExpr.binop "<=" (MojoExpr.var "n") (MojoExpr.int (UInt64.ofNat 1)))) ([MojoStmt.return (MojoExpr.var "n")]) ([MojoStmt.return ((MojoExpr.binop "+" ((MojoExpr.call "fib" [(MojoExpr.binop "-" (MojoExpr.var "n") (MojoExpr.int (UInt64.ofNat 1)))])) ((MojoExpr.call "fib" [(MojoExpr.binop "-" (MojoExpr.var "n") (MojoExpr.int (UInt64.ofNat 2)))]))))])])

/-- eval_eq_mojo: AST evaluation agrees with the semantic model. -/
theorem eval_eq_mojo (n : UInt64) :
  evalFunc ast (fun name arg =>
    if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [n] = mojo n := by
  have hunf : evalFunc ast (fun name arg => if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [n] =
      (if n ≤ (1 : UInt64) then n else mojo (n - 1) + mojo (n - 2)) := by
    simp only [ast, evalFunc, MojoEnv, evalBody, evalBodyEnv, evalExpr]
    by_cases h : n ≤ (1 : UInt64) <;> simp [h]
  rw [hunf]
  by_cases hle : n ≤ (1 : UInt64)
  · have hlt : n.toNat < 2 := by rw [UInt64.le_iff_toNat_le] at hle; simp at hle; omega
    rw [if_pos hle, mojo, fib_model_lt2 hlt, UInt64.ofNat_toNat]
  · have hge : 2 ≤ n.toNat := by rw [UInt64.le_iff_toNat_le] at hle; simp at hle; omega
    have hne0 : n ≠ 0 := by intro h; rw [h] at hge; simp at hge
    have hne1 : n ≠ 1 := by intro h; rw [h] at hge; simp at hge
    rw [if_neg hle, mojo, mojo, mojo, fib_model_ge2 hge,
        toNat_sub_one n hne0, toNat_sub_two n hne0 hne1, UInt64.add_comm]

/-- Concrete instances of eval_eq_mojo, checked by native execution. -/
theorem eval_eq_mojo_0 :
  evalFunc ast (fun name arg =>
    if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [(UInt64.ofNat 0)] = mojo (UInt64.ofNat 0) := by
  native_decide

theorem eval_eq_mojo_1 :
  evalFunc ast (fun name arg =>
    if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [(UInt64.ofNat 1)] = mojo (UInt64.ofNat 1) := by
  native_decide

theorem eval_eq_mojo_2 :
  evalFunc ast (fun name arg =>
    if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [(UInt64.ofNat 2)] = mojo (UInt64.ofNat 2) := by
  native_decide

theorem eval_eq_mojo_5 :
  evalFunc ast (fun name arg =>
    if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [(UInt64.ofNat 5)] = mojo (UInt64.ofNat 5) := by
  native_decide

theorem eval_eq_mojo_test :
  evalFunc ast (fun name arg =>
    if name = "fib" then mojo arg else if name = "len" then strlen arg else if name = "str_len" then strlen arg else if name = "strlen" then strlen arg else 0) [(UInt64.ofNat 10)] = mojo (UInt64.ofNat 10) := by
  native_decide

/- Code memory: maps absolute addresses to instruction bytes
   (a RET sentinel is appended after the emitted code). -/
def fib_code_list : List UInt8 :=
  [0xfd, 0x7b, 0xbf, 0xa9, 0x10, 0x20, 0x00, 0x90, 0x10, 0x42, 0x00, 0x91, 0x10, 0x02, 0x40, 0xf9, 0xb0, 0x03, 0x00, 0xb5, 0x60, 0x00, 0x80, 0xd2, 0x01, 0x20, 0x00, 0x90, 0x21, 0x60, 0x00, 0x91, 0x56, 0x02, 0x00, 0x94, 0x10, 0x20, 0x00, 0x90, 0x10, 0x62, 0x00, 0x91, 0x10, 0x02, 0x40, 0xf9, 0x11, 0x20, 0x00, 0x90, 0x31, 0x42, 0x00, 0x91, 0x30, 0x02, 0x00, 0xf9, 0x0f, 0x82, 0x41, 0xd1, 0x0e, 0x00, 0x80, 0x52, 0x8e, 0x00, 0xa0, 0xf2, 0xff, 0x01, 0x0e, 0xeb, 0x62, 0x00, 0x00, 0x54, 0x0f, 0x00, 0x80, 0x52, 0x8f, 0x00, 0xa0, 0xf2, 0x0e, 0x00, 0x80, 0x52, 0x0e, 0x0f, 0xa0, 0xf2, 0xff, 0x01, 0x0e, 0xeb, 0x63, 0x00, 0x00, 0x54, 0x0f, 0x00, 0x80, 0x52, 0x0f, 0x0f, 0xa0, 0xf2, 0xf0, 0x03, 0x00, 0x91, 0x10, 0x02, 0x0f, 0xcb, 0x11, 0x20, 0x00, 0x90, 0x31, 0x22, 0x00, 0x91, 0x30, 0x02, 0x00, 0xf9, 0x40, 0x01, 0x80, 0x52, 0x03, 0x00, 0x00, 0x94, 0xfd, 0x7b, 0xc1, 0xa8, 0xc0, 0x03, 0x5f, 0xd6, 0xfd, 0x7b, 0xbf, 0xa9, 0xfd, 0x03, 0x00, 0x91, 0xf3, 0x53, 0xbf, 0xa9, 0x13, 0x00, 0x00, 0x91, 0x11, 0x20, 0x00, 0x90, 0x31, 0x22, 0x00, 0x91, 0x30, 0x02, 0x40, 0xf9, 0xf1, 0x03, 0x00, 0x91, 0x3f, 0x02, 0x10, 0xeb, 0x82, 0x01, 0x00, 0x54, 0xff, 0x43, 0x00, 0xd1, 0x01, 0x00, 0x00, 0x90, 0x21, 0x50, 0x27, 0x91, 0x40, 0x00, 0x80, 0xd2, 0xa2, 0x68, 0x80, 0xd2, 0x90, 0x00, 0x80, 0xd2, 0x01, 0x10, 0x00, 0xd4, 0xff, 0x43, 0x00, 0x91, 0x40, 0x00, 0x80, 0xd2, 0x30, 0x00, 0x80, 0xd2, 0x01, 0x10, 0x00, 0xd4, 0xff, 0x83, 0x40, 0xd1, 0x60, 0x02, 0x00, 0x91, 0xe0, 0x0b, 0xbf, 0xa9, 0x20, 0x00, 0x80, 0x52, 0x01, 0x00, 0x00, 0x91, 0xe0, 0x0b, 0xc1, 0xa8, 0x1f, 0x00, 0x01, 0xeb, 0xec, 0x00, 0x00, 0x54, 0x60, 0x02, 0x00, 0x91, 0xff, 0x83, 0x40, 0x91, 0xf3, 0x53, 0xc1, 0xa8, 0xfd, 0x7b, 0xc1, 0xa8, 0xc0, 0x03, 0x5f, 0xd6, 0x1b, 0x00, 0x00, 0x14, 0x60, 0x02, 0x00, 0x91, 0xe0, 0x0b, 0xbf, 0xa9, 0x20, 0x00, 0x80, 0x52, 0x01, 0x00, 0x00, 0x91, 0xe0, 0x0b, 0xc1, 0xa8, 0x00, 0x00, 0x01, 0xcb, 0xe0, 0x7f, 0xbf, 0xa9, 0xe0, 0x7f, 0xc1, 0xa8, 0xd5, 0xff, 0xff, 0x97, 0xe0, 0x0b, 0xbf, 0xa9, 0x60, 0x02, 0x00, 0x91, 0xe0, 0x0b, 0xbf, 0xa9, 0x40, 0x00, 0x80, 0x52, 0x01, 0x00, 0x00, 0x91, 0xe0, 0x0b, 0xc1, 0xa8, 0x00, 0x00, 0x01, 0xcb, 0xe0, 0x7f, 0xbf, 0xa9, 0xe0, 0x7f, 0xc1, 0xa8, 0xcb, 0xff, 0xff, 0x97, 0x01, 0x00, 0x00, 0x91, 0xe0, 0x0b, 0xc1, 0xa8, 0x00, 0x00, 0x01, 0x8b, 0xff, 0x83, 0x40, 0x91, 0xf3, 0x53, 0xc1, 0xa8, 0xfd, 0x7b, 0xc1, 0xa8, 0xc0, 0x03, 0x5f, 0xd6, 0xfd, 0x7b, 0xb9, 0xa9, 0xe0, 0x2f, 0x00, 0xf9, 0xe1, 0x2b, 0x00, 0xf9, 0x0c, 0xfc, 0x7f, 0xd3, 0x8d, 0x01, 0x41, 0xd3, 0x0b, 0x00, 0x0d, 0xcb, 0xeb, 0x27, 0x00, 0xf9, 0xec, 0x33, 0x00, 0xf9, 0x6e, 0xfd, 0x74, 0xd3, 0xdf, 0xfd, 0x1f, 0xf1, 0xe3, 0x00, 0x00, 0x54, 0xcf, 0x2d, 0x4c, 0xd3, 0x6f, 0x01, 0x0f, 0xcb, 0xef, 0x00, 0x00, 0xb4, 0x10, 0x00, 0x00, 0x90, 0x10, 0x72, 0x34, 0x91, 0x12, 0x00, 0x00, 0x14, 0x7f, 0x01, 0x00, 0xf1, 0x20, 0x01, 0x00, 0x54, 0x1b, 0x00, 0x00, 0x14, 0x8c, 0x00, 0x00, 0xb4, 0x10, 0x00, 0x00, 0x90, 0x10, 0x82, 0x34, 0x91, 0x0b, 0x00, 0x00, 0x14, 0x10, 0x00, 0x00, 0x90, 0x10, 0x96, 0x34, 0x91, 0x08, 0x00, 0x00, 0x14, 0x8c, 0x00, 0x00, 0xb4, 0x10, 0x00, 0x00, 0x90, 0x10, 0xa6, 0x34, 0x91, 0x04, 0x00, 0x00, 0x14, 0x10, 0x00, 0x00, 0x90, 0x10, 0xba, 0x34, 0x91, 0x01, 0x00, 0x00, 0x14, 0xe9, 0x2b, 0x40, 0xf9, 0x2f, 0x01, 0x00, 0x91, 0x08, 0x02, 0x40, 0xf9, 0x08, 0x1d, 0x00, 0x13, 0xe8, 0x01, 0x00, 0x39, 0x88, 0x00, 0x00, 0xb4, 0xef, 0x05, 0x00, 0x91, 0x10, 0x06, 0x00, 0x91, 0xfa, 0xff, 0xff, 0x17, 0xe0, 0x2b, 0x40, 0xf9, 0xfd, 0x7b, 0xc7, 0xa8, 0xc0, 0x03, 0x5f, 0xd6, 0x2d, 0x00, 0x80, 0xd2, 0xe0, 0x43, 0x00, 0x91, 0x01, 0x04, 0x80, 0xd2, 0x02, 0x00, 0x00, 0x90, 0x42, 0xc8, 0x34, 0x91, 0xed, 0x37, 0x00, 0xf9, 0xff, 0x03, 0x01, 0xd1, 0xed, 0x03, 0x00, 0xf9, 0xeb, 0x47, 0x40, 0xf9, 0xeb, 0x07, 0x00, 0xf9, 0xc7, 0x01, 0x00, 0x94, 0xff, 0x03, 0x01, 0x91, 0xe0, 0x43, 0x00, 0x91, 0xe1, 0x03, 0x01, 0x91, 0xc6, 0x01, 0x00, 0x94, 0x0e, 0x00, 0x66, 0x9e, 0xeb, 0x27, 0x40, 0xf9, 0xdf, 0x01, 0x0b, 0xeb, 0xa0, 0x00, 0x00, 0x54, 0xed, 0x37, 0x40, 0xf9, 0xad, 0x05, 0x00, 0x91, 0xbf, 0x49, 0x00, 0xf1, 0x61, 0xfd, 0xff, 0x54, 0xf1, 0xc3, 0x00, 0x91, 0xf0, 0x43, 0x00, 0x91, 0x0a, 0x02, 0x00, 0x91, 0x0d, 0x00, 0x80, 0xd2, 0x0e, 0x00, 0x80, 0xd2, 0x0f, 0x00, 0x80, 0xd2, 0x03, 0x00, 0x80, 0xd2, 0x04, 0x00, 0x80, 0xd2, 0x05, 0x00, 0x80, 0xd2, 0x06, 0x00, 0x80, 0xd2, 0x12, 0x00, 0x80, 0xd2, 0x47, 0x01, 0x80, 0xd2, 0x48, 0x01, 0x40, 0xf9, 0x08, 0x1d, 0x00, 0x13, 0x1f, 0x01, 0x00, 0xf1, 0x80, 0x05, 0x00, 0x54, 0xce, 0x03, 0x00, 0xb5, 0x1f, 0x95, 0x01, 0xf1, 0xa0, 0x02, 0x00, 0x54, 0x1f, 0xb9, 0x00, 0xf1, 0xa0, 0x02, 0x00, 0x54, 0x1f, 0xc1, 0x00, 0xf1, 0x63, 0x04, 0x00, 0x54, 0x1f, 0xe5, 0x00, 0xf1, 0x28, 0x04, 0x00, 0x54, 0x44, 0x00, 0x00, 0xb4, 0x02, 0x00, 0x00, 0x14, 0x52, 0x06, 0x00, 0x91, 0x1f, 0xc1, 0x00, 0xf1, 0x41, 0x00, 0x00, 0x54, 0x63, 0x03, 0x00, 0xb4, 0x63, 0x00, 0x00, 0xb4, 0x28, 0x6a, 0x23, 0x38, 0x04, 0x00, 0x00, 0x14, 0x4d, 0x01, 0x10, 0xcb, 0xa5, 0x01, 0x00, 0x91, 0x28, 0x6a, 0x23, 0x38, 0x63, 0x04, 0x00, 0x91, 0x13, 0x00, 0x00, 0x14, 0x2e, 0x00, 0x80, 0xd2, 0x11, 0x00, 0x00, 0x14, 0x44, 0x00, 0x00, 0xb4, 0x0f, 0x00, 0x00, 0x14, 0x4d, 0x01, 0x10, 0xcb, 0xa4, 0x01, 0x00, 0x91, 0x0c, 0x00, 0x00, 0x14, 0x1f, 0xad, 0x00, 0xf1, 0x61, 0x00, 0x00, 0x54, 0x26, 0x00, 0x80, 0xd2, 0x08, 0x00, 0x00, 0x14, 0x1f, 0xb5, 0x00, 0xf1, 0x61, 0x00, 0x00, 0x54, 0x46, 0x00, 0x80, 0xd2, 0x04, 0x00, 0x00, 0x14, 0x08, 0xc1, 0x00, 0xd1, 0xef, 0x7d, 0x07, 0x9b, 0xef, 0x01, 0x08, 0x8b, 0x4a, 0x05, 0x00, 0x91, 0xd2, 0xff, 0xff, 0x17, 0xf0, 0x2b, 0x40, 0xf9, 0xec, 0x33, 0x40, 0xf9, 0xae, 0x00, 0x00, 0xb4, 0xdf, 0x08, 0x00, 0xf1, 0x41, 0x00, 0x00, 0x54, 0xef, 0x03, 0x0f, 0xcb, 0x07, 0x00, 0x00, 0x14, 0x64, 0x00, 0x00, 0xb4, 0xbf, 0x00, 0x04, 0xeb, 0x62, 0x00, 0x00, 0x54, 0x4f, 0x06, 0x00, 0xd1, 0x02, 0x00, 0x00, 0x14, 0x8f, 0x00, 0x05, 0xcb, 0xff, 0x41, 0x00, 0xf1, 0xaa, 0x00, 0x00, 0x54, 0xe8, 0x03, 0x0f, 0xcb, 0x1f, 0x15, 0x00, 0xf1, 0x4a, 0x00, 0x00, 0x54, 0x01, 0x00, 0x00, 0x14, 0x8c, 0x00, 0x00, 0xb4, 0xa8, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0xff, 0x41, 0x00, 0xf1, 0x4a, 0x00, 0x00, 0x54, 0x41, 0x00, 0x00, 0x14, 0x2b, 0x02, 0x40, 0xf9, 0x6b, 0x1d, 0x00, 0x13, 0x0b, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x7f, 0x04, 0x00, 0xf1, 0xa0, 0x01, 0x00, 0x54, 0xc8, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x2a, 0x00, 0x80, 0xd2, 0x5f, 0x01, 0x03, 0xeb, 0xea, 0x00, 0x00, 0x54, 0x2b, 0x6a, 0x6a, 0xf8, 0x6b, 0x1d, 0x00, 0x13, 0x0b, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x05, 0x00, 0x91, 0xf9, 0xff, 0xff, 0x17, 0xa8, 0x0c, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0xff, 0x01, 0x00, 0xf1, 0xa4, 0x00, 0x00, 0x54, 0x68, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x04, 0x00, 0x00, 0x14, 0xa8, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0xff, 0x01, 0x00, 0xf1, 0x4a, 0x00, 0x00, 0x54, 0xef, 0x03, 0x0f, 0xcb, 0xff, 0x91, 0x01, 0xf1, 0x4b, 0x02, 0x00, 0x54, 0x92, 0x0c, 0x80, 0xd2, 0xea, 0x09, 0xd2, 0x9a, 0x4b, 0x7d, 0x12, 0x9b, 0xeb, 0x01, 0x0b, 0xcb, 0x4a, 0xc1, 0x00, 0x91, 0x0a, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x52, 0x01, 0x80, 0xd2, 0x6a, 0x09, 0xd2, 0x9a, 0x49, 0x7d, 0x12, 0x9b, 0x69, 0x01, 0x09, 0xcb, 0x4a, 0xc1, 0x00, 0x91, 0x0a, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x29, 0xc1, 0x00, 0x91, 0x09, 0x02, 0x00, 0x39, 0x0a, 0x00, 0x00, 0x14, 0x52, 0x01, 0x80, 0xd2, 0xea, 0x09, 0xd2, 0x9a, 0x49, 0x7d, 0x12, 0x9b, 0xe9, 0x01, 0x09, 0xcb, 0x4a, 0xc1, 0x00, 0x91, 0x0a, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x29, 0xc1, 0x00, 0x91, 0x09, 0x02, 0x00, 0x39, 0x08, 0x00, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x52, 0xff, 0xff, 0x17, 0xff, 0x01, 0x00, 0xf1, 0x0a, 0x03, 0x00, 0x54, 0x08, 0x06, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0xc8, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0xea, 0x03, 0x0f, 0xcb, 0x4a, 0x05, 0x00, 0xd1, 0xca, 0x00, 0x00, 0xb4, 0x08, 0x06, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x05, 0x00, 0xd1, 0xfb, 0xff, 0xff, 0x17, 0x0a, 0x00, 0x80, 0xd2, 0x5f, 0x01, 0x03, 0xeb, 0x6a, 0xfd, 0xff, 0x54, 0x2b, 0x6a, 0x6a, 0xf8, 0x6b, 0x1d, 0x00, 0x13, 0x0b, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x05, 0x00, 0x91, 0xf9, 0xff, 0xff, 0x17, 0xf2, 0x05, 0x00, 0x91, 0x7f, 0x00, 0x12, 0xeb, 0xcd, 0x02, 0x00, 0x54, 0x0a, 0x00, 0x80, 0xd2, 0x5f, 0x01, 0x12, 0xeb, 0xea, 0x00, 0x00, 0x54, 0x2b, 0x6a, 0x6a, 0xf8, 0x6b, 0x1d, 0x00, 0x13, 0x0b, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x05, 0x00, 0x91, 0xf9, 0xff, 0xff, 0x17, 0xc8, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x02, 0x00, 0x91, 0x5f, 0x01, 0x03, 0xeb, 0x6a, 0xfa, 0xff, 0x54, 0x2b, 0x6a, 0x6a, 0xf8, 0x6b, 0x1d, 0x00, 0x13, 0x0b, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x05, 0x00, 0x91, 0xf9, 0xff, 0xff, 0x17, 0x0a, 0x00, 0x80, 0xd2, 0x5f, 0x01, 0x03, 0xeb, 0xea, 0x00, 0x00, 0x54, 0x2b, 0x6a, 0x6a, 0xf8, 0x6b, 0x1d, 0x00, 0x13, 0x0b, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x4a, 0x05, 0x00, 0x91, 0xf9, 0xff, 0xff, 0x17, 0x4b, 0x02, 0x00, 0x91, 0x6b, 0x01, 0x03, 0xcb, 0xcb, 0x00, 0x00, 0xb4, 0x08, 0x06, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x6b, 0x05, 0x00, 0xd1, 0xfb, 0xff, 0xff, 0x17, 0xc8, 0x05, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0x08, 0x06, 0x80, 0xd2, 0x08, 0x02, 0x00, 0x39, 0x10, 0x06, 0x00, 0x91, 0xb5, 0xff, 0xff, 0x17, 0x52, 0x65, 0x63, 0x75, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x45, 0x72, 0x72, 0x6f, 0x72, 0x3a, 0x20, 0x74, 0x68, 0x69, 0x73, 0x20, 0x70, 0x72, 0x6f, 0x67, 0x72, 0x61, 0x6d, 0x27, 0x73, 0x20, 0x63, 0x61, 0x6c, 0x6c, 0x20, 0x73, 0x74, 0x61, 0x63, 0x6b, 0x20, 0x77, 0x65, 0x6e, 0x74, 0x20, 0x70, 0x61, 0x73, 0x74, 0x20, 0x74, 0x68, 0x65, 0x20, 0x73, 0x74, 0x61, 0x63, 0x6b, 0x20, 0x62, 0x75, 0x64, 0x67, 0x65, 0x74, 0x20, 0x6f, 0x66, 0x20, 0x37, 0x38, 0x36, 0x34, 0x33, 0x32, 0x30, 0x20, 0x62, 0x79, 0x74, 0x65, 0x73, 0x2c, 0x20, 0x77, 0x68, 0x69, 0x63, 0x68, 0x20, 0x69, 0x73, 0x20, 0x74, 0x68, 0x65, 0x20, 0x73, 0x6d, 0x61, 0x6c, 0x6c, 0x65, 0x72, 0x20, 0x6f, 0x66, 0x20, 0x74, 0x68, 0x61, 0x74, 0x20, 0x6e, 0x75, 0x6d, 0x62, 0x65, 0x72, 0x20, 0x61, 0x6e, 0x64, 0x20, 0x74, 0x68, 0x69, 0x73, 0x20, 0x70, 0x72, 0x6f, 0x63, 0x65, 0x73, 0x73, 0x27, 0x73, 0x20, 0x6f, 0x77, 0x6e, 0x20, 0x73, 0x74, 0x61, 0x63, 0x6b, 0x20, 0x6c, 0x69, 0x6d, 0x69, 0x74, 0x20, 0x6c, 0x65, 0x73, 0x73, 0x20, 0x32, 0x36, 0x32, 0x31, 0x34, 0x34, 0x20, 0x62, 0x79, 0x74, 0x65, 0x73, 0x20, 0x6f, 0x66, 0x20, 0x72, 0x65, 0x73, 0x65, 0x72, 0x76, 0x65, 0x20, 0xe2, 0x80, 0x94, 0x20, 0x73, 0x6f, 0x20, 0x61, 0x20, 0x70, 0x72, 0x6f, 0x63, 0x65, 0x73, 0x73, 0x20, 0x77, 0x69, 0x74, 0x68, 0x20, 0x61, 0x20, 0x73, 0x6d, 0x61, 0x6c, 0x6c, 0x65, 0x72, 0x20, 0x73, 0x74, 0x61, 0x63, 0x6b, 0x20, 0x72, 0x65, 0x66, 0x75, 0x73, 0x65, 0x73, 0x20, 0x53, 0x4f, 0x4f, 0x4e, 0x45, 0x52, 0x2c, 0x20, 0x61, 0x6e, 0x64, 0x20, 0x6e, 0x65, 0x76, 0x65, 0x72, 0x20, 0x6c, 0x61, 0x74, 0x65, 0x72, 0x20, 0x74, 0x68, 0x61, 0x6e, 0x20, 0x74, 0x68, 0x69, 0x73, 0x2e, 0x20, 0x43, 0x50, 0x79, 0x74, 0x68, 0x6f, 0x6e, 0x20, 0x72, 0x61, 0x69, 0x73, 0x65, 0x73, 0x20, 0x52, 0x65, 0x63, 0x75, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x45, 0x72, 0x72, 0x6f, 0x72, 0x20, 0x66, 0x6f, 0x72, 0x20, 0x61, 0x20, 0x72, 0x65, 0x63, 0x75, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x20, 0x74, 0x68, 0x69, 0x73, 0x20, 0x64, 0x65, 0x65, 0x70, 0x2c, 0x20, 0x61, 0x6e, 0x64, 0x20, 0x73, 0x79, 0x73, 0x2e, 0x73, 0x65, 0x74, 0x72, 0x65, 0x63, 0x75, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x6c, 0x69, 0x6d, 0x69, 0x74, 0x20, 0x63, 0x61, 0x6e, 0x6e, 0x6f, 0x74, 0x20, 0x68, 0x65, 0x6c, 0x70, 0x20, 0x68, 0x65, 0x72, 0x65, 0x3a, 0x20, 0x74, 0x68, 0x69, 0x73, 0x20, 0x74, 0x61, 0x72, 0x67, 0x65, 0x74, 0x20, 0x68, 0x61, 0x73, 0x20, 0x6e, 0x6f, 0x20, 0x69, 0x6e, 0x74, 0x65, 0x72, 0x70, 0x72, 0x65, 0x74, 0x65, 0x72, 0x20, 0x73, 0x74, 0x61, 0x63, 0x6b, 0x20, 0x74, 0x6f, 0x20, 0x72, 0x61, 0x69, 0x73, 0x65, 0x20, 0x61, 0x20, 0x6c, 0x69, 0x6d, 0x69, 0x74, 0x20, 0x6f, 0x6e, 0x2c, 0x20, 0x61, 0x6e, 0x64, 0x20, 0x69, 0x74, 0x20, 0x63, 0x6f, 0x6d, 0x70, 0x69, 0x6c, 0x65, 0x73, 0x20, 0x74, 0x68, 0x65, 0x20, 0x6c, 0x69, 0x6d, 0x69, 0x74, 0x20, 0x79, 0x6f, 0x75, 0x20, 0x61, 0x73, 0x6b, 0x20, 0x66, 0x6f, 0x72, 0x20, 0x77, 0x69, 0x74, 0x68, 0x6f, 0x75, 0x74, 0x20, 0x63, 0x68, 0x61, 0x6e, 0x67, 0x69, 0x6e, 0x67, 0x20, 0x61, 0x6e, 0x79, 0x74, 0x68, 0x69, 0x6e, 0x67, 0x2e, 0x20, 0x54, 0x68, 0x65, 0x20, 0x64, 0x65, 0x70, 0x74, 0x68, 0x20, 0x74, 0x68, 0x61, 0x74, 0x20, 0x66, 0x69, 0x74, 0x73, 0x20, 0x69, 0x73, 0x20, 0x74, 0x68, 0x65, 0x20, 0x62, 0x75, 0x64, 0x67, 0x65, 0x74, 0x20, 0x64, 0x69, 0x76, 0x69, 0x64, 0x65, 0x64, 0x20, 0x62, 0x79, 0x20, 0x6f, 0x6e, 0x65, 0x20, 0x63, 0x61, 0x6c, 0x6c, 0x20, 0x66, 0x72, 0x61, 0x6d, 0x65, 0x3b, 0x20, 0x61, 0x20, 0x66, 0x72, 0x61, 0x6d, 0x65, 0x20, 0x69, 0x73, 0x20, 0x31, 0x33, 0x31, 0x30, 0x37, 0x32, 0x20, 0x62, 0x79, 0x74, 0x65, 0x73, 0x20, 0x6f, 0x6e, 0x20, 0x61, 0x72, 0x6d, 0x36, 0x34, 0x20, 0x61, 0x6e, 0x64, 0x20, 0x31, 0x36, 0x33, 0x38, 0x34, 0x20, 0x6f, 0x6e, 0x20, 0x78, 0x38, 0x36, 0x2d, 0x36, 0x34, 0x20, 0x70, 0x6c, 0x75, 0x73, 0x20, 0x77, 0x68, 0x61, 0x74, 0x65, 0x76, 0x65, 0x72, 0x20, 0x74, 0x68, 0x65, 0x20, 0x66, 0x75, 0x6e, 0x63, 0x74, 0x69, 0x6f, 0x6e, 0x20, 0x73, 0x70, 0x69, 0x6c, 0x6c, 0x73, 0x2c, 0x20, 0x73, 0x6f, 0x20, 0x74, 0x68, 0x65, 0x20, 0x73, 0x61, 0x6d, 0x65, 0x20, 0x72, 0x65, 0x63, 0x75, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x20, 0x69, 0x73, 0x20, 0x72, 0x65, 0x66, 0x75, 0x73, 0x65, 0x64, 0x20, 0x61, 0x74, 0x20, 0x61, 0x20, 0x64, 0x69, 0x66, 0x66, 0x65, 0x72, 0x65, 0x6e, 0x74, 0x20, 0x64, 0x65, 0x70, 0x74, 0x68, 0x20, 0x6f, 0x6e, 0x20, 0x65, 0x61, 0x63, 0x68, 0x20, 0x61, 0x6e, 0x64, 0x20, 0x61, 0x20, 0x66, 0x75, 0x6e, 0x63, 0x74, 0x69, 0x6f, 0x6e, 0x20, 0x77, 0x69, 0x74, 0x68, 0x20, 0x6d, 0x61, 0x6e, 0x79, 0x20, 0x6c, 0x6f, 0x63, 0x61, 0x6c, 0x73, 0x20, 0x69, 0x73, 0x20, 0x72, 0x65, 0x66, 0x75, 0x73, 0x65, 0x64, 0x20, 0x73, 0x6f, 0x6f, 0x6e, 0x65, 0x72, 0x2e, 0x20, 0x52, 0x65, 0x77, 0x72, 0x69, 0x74, 0x65, 0x20, 0x74, 0x68, 0x65, 0x20, 0x72, 0x65, 0x63, 0x75, 0x72, 0x73, 0x69, 0x6f, 0x6e, 0x20, 0x61, 0x73, 0x20, 0x61, 0x20, 0x6c, 0x6f, 0x6f, 0x70, 0x2c, 0x20, 0x6f, 0x72, 0x20, 0x73, 0x70, 0x6c, 0x69, 0x74, 0x20, 0x69, 0x74, 0x20, 0x73, 0x6f, 0x20, 0x74, 0x68, 0x61, 0x74, 0x20, 0x6e, 0x6f, 0x20, 0x63, 0x68, 0x61, 0x69, 0x6e, 0x20, 0x6f, 0x66, 0x20, 0x63, 0x61, 0x6c, 0x6c, 0x73, 0x20, 0x69, 0x73, 0x20, 0x74, 0x68, 0x69, 0x73, 0x20, 0x64, 0x65, 0x65, 0x70, 0x2e, 0x0a, 0x00, 0x6e, 0x61, 0x6e, 0x00, 0x2d, 0x69, 0x6e, 0x66, 0x00, 0x69, 0x6e, 0x66, 0x00, 0x2d, 0x30, 0x2e, 0x30, 0x00, 0x30, 0x2e, 0x30, 0x00, 0x25, 0x2e, 0x2a, 0x67, 0x00, 0xc0, 0x03, 0x5f, 0xd6]

def fib_code (addr : Nat) : UInt8 :=
  if addr < 4294968256 then 0
  else fib_code_list.getD (addr - 4294968256) 0

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

/-- Concrete verification: running the compiled binary on input 10 leaves mojo 10 in x0. -/
theorem fib_runs_test :
  run_result_exit { (Arm64State.init 10 4294968404) with x30 := UInt64.ofNat 4294970679 } fib_code 4294970679 200000 = mojo 10 := by
  native_decide

/-- Concrete verification for input 0, run from the function entry. -/
theorem fib_runs_0 :
  run_result_exit { (Arm64State.init 0 4294968404) with x30 := UInt64.ofNat 4294970679 } fib_code 4294970679 200000 = mojo 0 := by
  native_decide

/-- Concrete verification for input 1, run from the function entry. -/
theorem fib_runs_1 :
  run_result_exit { (Arm64State.init 1 4294968404) with x30 := UInt64.ofNat 4294970679 } fib_code 4294970679 200000 = mojo 1 := by
  native_decide

/-- Concrete verification for input 2, run from the function entry. -/
theorem fib_runs_2 :
  run_result_exit { (Arm64State.init 2 4294968404) with x30 := UInt64.ofNat 4294970679 } fib_code 4294970679 200000 = mojo 2 := by
  native_decide

/-- Concrete verification for input 5, run from the function entry. -/
theorem fib_runs_5 :
  run_result_exit { (Arm64State.init 5 4294968404) with x30 := UInt64.ofNat 4294970679 } fib_code 4294970679 200000 = mojo 5 := by
  native_decide

/-- Per-instruction decode lemmas: each address decodes to the emitted word. -/
theorem fib_insn_0 :
  arm64_read_insn fib_code 4294968256 = 0xa9bf7bfd := by
  rfl

theorem fib_insn_1 :
  arm64_read_insn fib_code 4294968260 = 0x90002010 := by
  rfl

theorem fib_insn_2 :
  arm64_read_insn fib_code 4294968264 = 0x91004210 := by
  rfl

theorem fib_insn_3 :
  arm64_read_insn fib_code 4294968268 = 0xf9400210 := by
  rfl

theorem fib_insn_4 :
  arm64_read_insn fib_code 4294968272 = 0xb50003b0 := by
  rfl

theorem fib_insn_5 :
  arm64_read_insn fib_code 4294968276 = 0xd2800060 := by
  rfl

theorem fib_insn_6 :
  arm64_read_insn fib_code 4294968280 = 0x90002001 := by
  rfl

theorem fib_insn_7 :
  arm64_read_insn fib_code 4294968284 = 0x91006021 := by
  rfl

theorem fib_insn_8 :
  arm64_read_insn fib_code 4294968288 = 0x94000256 := by
  rfl

theorem fib_insn_9 :
  arm64_read_insn fib_code 4294968292 = 0x90002010 := by
  rfl

theorem fib_insn_10 :
  arm64_read_insn fib_code 4294968296 = 0x91006210 := by
  rfl

theorem fib_insn_11 :
  arm64_read_insn fib_code 4294968300 = 0xf9400210 := by
  rfl

theorem fib_insn_12 :
  arm64_read_insn fib_code 4294968304 = 0x90002011 := by
  rfl

theorem fib_insn_13 :
  arm64_read_insn fib_code 4294968308 = 0x91004231 := by
  rfl

theorem fib_insn_14 :
  arm64_read_insn fib_code 4294968312 = 0xf9000230 := by
  rfl

theorem fib_insn_15 :
  arm64_read_insn fib_code 4294968316 = 0xd141820f := by
  rfl

theorem fib_insn_16 :
  arm64_read_insn fib_code 4294968320 = 0x5280000e := by
  rfl

theorem fib_insn_17 :
  arm64_read_insn fib_code 4294968324 = 0xf2a0008e := by
  rfl

theorem fib_insn_18 :
  arm64_read_insn fib_code 4294968328 = 0xeb0e01ff := by
  rfl

theorem fib_insn_19 :
  arm64_read_insn fib_code 4294968332 = 0x54000062 := by
  rfl

theorem fib_insn_20 :
  arm64_read_insn fib_code 4294968336 = 0x5280000f := by
  rfl

theorem fib_insn_21 :
  arm64_read_insn fib_code 4294968340 = 0xf2a0008f := by
  rfl

theorem fib_insn_22 :
  arm64_read_insn fib_code 4294968344 = 0x5280000e := by
  rfl

theorem fib_insn_23 :
  arm64_read_insn fib_code 4294968348 = 0xf2a00f0e := by
  rfl

theorem fib_insn_24 :
  arm64_read_insn fib_code 4294968352 = 0xeb0e01ff := by
  rfl

theorem fib_insn_25 :
  arm64_read_insn fib_code 4294968356 = 0x54000063 := by
  rfl

theorem fib_insn_26 :
  arm64_read_insn fib_code 4294968360 = 0x5280000f := by
  rfl

theorem fib_insn_27 :
  arm64_read_insn fib_code 4294968364 = 0xf2a00f0f := by
  rfl

theorem fib_insn_28 :
  arm64_read_insn fib_code 4294968368 = 0x910003f0 := by
  rfl

theorem fib_insn_29 :
  arm64_read_insn fib_code 4294968372 = 0xcb0f0210 := by
  rfl

theorem fib_insn_30 :
  arm64_read_insn fib_code 4294968376 = 0x90002011 := by
  rfl

theorem fib_insn_31 :
  arm64_read_insn fib_code 4294968380 = 0x91002231 := by
  rfl

theorem fib_insn_32 :
  arm64_read_insn fib_code 4294968384 = 0xf9000230 := by
  rfl

theorem fib_insn_33 :
  arm64_read_insn fib_code 4294968388 = 0x52800140 := by
  rfl

theorem fib_insn_34 :
  arm64_read_insn fib_code 4294968392 = 0x94000003 := by
  rfl

theorem fib_insn_35 :
  arm64_read_insn fib_code 4294968396 = 0xa8c17bfd := by
  rfl

theorem fib_insn_36 :
  arm64_read_insn fib_code 4294968400 = 0xd65f03c0 := by
  rfl

theorem fib_insn_37 :
  arm64_read_insn fib_code 4294968404 = 0xa9bf7bfd := by
  rfl

theorem fib_insn_38 :
  arm64_read_insn fib_code 4294968408 = 0x910003fd := by
  rfl

theorem fib_insn_39 :
  arm64_read_insn fib_code 4294968412 = 0xa9bf53f3 := by
  rfl

theorem fib_insn_40 :
  arm64_read_insn fib_code 4294968416 = 0x91000013 := by
  rfl

theorem fib_insn_41 :
  arm64_read_insn fib_code 4294968420 = 0x90002011 := by
  rfl

theorem fib_insn_42 :
  arm64_read_insn fib_code 4294968424 = 0x91002231 := by
  rfl

theorem fib_insn_43 :
  arm64_read_insn fib_code 4294968428 = 0xf9400230 := by
  rfl

theorem fib_insn_44 :
  arm64_read_insn fib_code 4294968432 = 0x910003f1 := by
  rfl

theorem fib_insn_45 :
  arm64_read_insn fib_code 4294968436 = 0xeb10023f := by
  rfl

theorem fib_insn_46 :
  arm64_read_insn fib_code 4294968440 = 0x54000182 := by
  rfl

theorem fib_insn_47 :
  arm64_read_insn fib_code 4294968444 = 0xd10043ff := by
  rfl

theorem fib_insn_48 :
  arm64_read_insn fib_code 4294968448 = 0x90000001 := by
  rfl

theorem fib_insn_49 :
  arm64_read_insn fib_code 4294968452 = 0x91275021 := by
  rfl

theorem fib_insn_50 :
  arm64_read_insn fib_code 4294968456 = 0xd2800040 := by
  rfl

theorem fib_insn_51 :
  arm64_read_insn fib_code 4294968460 = 0xd28068a2 := by
  rfl

theorem fib_insn_52 :
  arm64_read_insn fib_code 4294968464 = 0xd2800090 := by
  rfl

theorem fib_insn_53 :
  arm64_read_insn fib_code 4294968468 = 0xd4001001 := by
  rfl

theorem fib_insn_54 :
  arm64_read_insn fib_code 4294968472 = 0x910043ff := by
  rfl

theorem fib_insn_55 :
  arm64_read_insn fib_code 4294968476 = 0xd2800040 := by
  rfl

theorem fib_insn_56 :
  arm64_read_insn fib_code 4294968480 = 0xd2800030 := by
  rfl

theorem fib_insn_57 :
  arm64_read_insn fib_code 4294968484 = 0xd4001001 := by
  rfl

theorem fib_insn_58 :
  arm64_read_insn fib_code 4294968488 = 0xd14083ff := by
  rfl

theorem fib_insn_59 :
  arm64_read_insn fib_code 4294968492 = 0x91000260 := by
  rfl

theorem fib_insn_60 :
  arm64_read_insn fib_code 4294968496 = 0xa9bf0be0 := by
  rfl

theorem fib_insn_61 :
  arm64_read_insn fib_code 4294968500 = 0x52800020 := by
  rfl

theorem fib_insn_62 :
  arm64_read_insn fib_code 4294968504 = 0x91000001 := by
  rfl

theorem fib_insn_63 :
  arm64_read_insn fib_code 4294968508 = 0xa8c10be0 := by
  rfl

theorem fib_insn_64 :
  arm64_read_insn fib_code 4294968512 = 0xeb01001f := by
  rfl

theorem fib_insn_65 :
  arm64_read_insn fib_code 4294968516 = 0x540000ec := by
  rfl

theorem fib_insn_66 :
  arm64_read_insn fib_code 4294968520 = 0x91000260 := by
  rfl

theorem fib_insn_67 :
  arm64_read_insn fib_code 4294968524 = 0x914083ff := by
  rfl

theorem fib_insn_68 :
  arm64_read_insn fib_code 4294968528 = 0xa8c153f3 := by
  rfl

theorem fib_insn_69 :
  arm64_read_insn fib_code 4294968532 = 0xa8c17bfd := by
  rfl

theorem fib_insn_70 :
  arm64_read_insn fib_code 4294968536 = 0xd65f03c0 := by
  rfl

theorem fib_insn_71 :
  arm64_read_insn fib_code 4294968540 = 0x1400001b := by
  rfl

theorem fib_insn_72 :
  arm64_read_insn fib_code 4294968544 = 0x91000260 := by
  rfl

theorem fib_insn_73 :
  arm64_read_insn fib_code 4294968548 = 0xa9bf0be0 := by
  rfl

theorem fib_insn_74 :
  arm64_read_insn fib_code 4294968552 = 0x52800020 := by
  rfl

theorem fib_insn_75 :
  arm64_read_insn fib_code 4294968556 = 0x91000001 := by
  rfl

theorem fib_insn_76 :
  arm64_read_insn fib_code 4294968560 = 0xa8c10be0 := by
  rfl

theorem fib_insn_77 :
  arm64_read_insn fib_code 4294968564 = 0xcb010000 := by
  rfl

theorem fib_insn_78 :
  arm64_read_insn fib_code 4294968568 = 0xa9bf7fe0 := by
  rfl

theorem fib_insn_79 :
  arm64_read_insn fib_code 4294968572 = 0xa8c17fe0 := by
  rfl

theorem fib_insn_80 :
  arm64_read_insn fib_code 4294968576 = 0x97ffffd5 := by
  rfl

theorem fib_insn_81 :
  arm64_read_insn fib_code 4294968580 = 0xa9bf0be0 := by
  rfl

theorem fib_insn_82 :
  arm64_read_insn fib_code 4294968584 = 0x91000260 := by
  rfl

theorem fib_insn_83 :
  arm64_read_insn fib_code 4294968588 = 0xa9bf0be0 := by
  rfl

theorem fib_insn_84 :
  arm64_read_insn fib_code 4294968592 = 0x52800040 := by
  rfl

theorem fib_insn_85 :
  arm64_read_insn fib_code 4294968596 = 0x91000001 := by
  rfl

theorem fib_insn_86 :
  arm64_read_insn fib_code 4294968600 = 0xa8c10be0 := by
  rfl

theorem fib_insn_87 :
  arm64_read_insn fib_code 4294968604 = 0xcb010000 := by
  rfl

theorem fib_insn_88 :
  arm64_read_insn fib_code 4294968608 = 0xa9bf7fe0 := by
  rfl

theorem fib_insn_89 :
  arm64_read_insn fib_code 4294968612 = 0xa8c17fe0 := by
  rfl

theorem fib_insn_90 :
  arm64_read_insn fib_code 4294968616 = 0x97ffffcb := by
  rfl

theorem fib_insn_91 :
  arm64_read_insn fib_code 4294968620 = 0x91000001 := by
  rfl

theorem fib_insn_92 :
  arm64_read_insn fib_code 4294968624 = 0xa8c10be0 := by
  rfl

theorem fib_insn_93 :
  arm64_read_insn fib_code 4294968628 = 0x8b010000 := by
  rfl

theorem fib_insn_94 :
  arm64_read_insn fib_code 4294968632 = 0x914083ff := by
  rfl

theorem fib_insn_95 :
  arm64_read_insn fib_code 4294968636 = 0xa8c153f3 := by
  rfl

theorem fib_insn_96 :
  arm64_read_insn fib_code 4294968640 = 0xa8c17bfd := by
  rfl

theorem fib_insn_97 :
  arm64_read_insn fib_code 4294968644 = 0xd65f03c0 := by
  rfl

theorem fib_insn_98 :
  arm64_read_insn fib_code 4294968648 = 0xa9b97bfd := by
  rfl

theorem fib_insn_99 :
  arm64_read_insn fib_code 4294968652 = 0xf9002fe0 := by
  rfl

theorem fib_insn_100 :
  arm64_read_insn fib_code 4294968656 = 0xf9002be1 := by
  rfl

theorem fib_insn_101 :
  arm64_read_insn fib_code 4294968660 = 0xd37ffc0c := by
  rfl

theorem fib_insn_102 :
  arm64_read_insn fib_code 4294968664 = 0xd341018d := by
  rfl

theorem fib_insn_103 :
  arm64_read_insn fib_code 4294968668 = 0xcb0d000b := by
  rfl

theorem fib_insn_104 :
  arm64_read_insn fib_code 4294968672 = 0xf90027eb := by
  rfl

theorem fib_insn_105 :
  arm64_read_insn fib_code 4294968676 = 0xf90033ec := by
  rfl

theorem fib_insn_106 :
  arm64_read_insn fib_code 4294968680 = 0xd374fd6e := by
  rfl

theorem fib_insn_107 :
  arm64_read_insn fib_code 4294968684 = 0xf11ffddf := by
  rfl

theorem fib_insn_108 :
  arm64_read_insn fib_code 4294968688 = 0x540000e3 := by
  rfl

theorem fib_insn_109 :
  arm64_read_insn fib_code 4294968692 = 0xd34c2dcf := by
  rfl

theorem fib_insn_110 :
  arm64_read_insn fib_code 4294968696 = 0xcb0f016f := by
  rfl

theorem fib_insn_111 :
  arm64_read_insn fib_code 4294968700 = 0xb40000ef := by
  rfl

theorem fib_insn_112 :
  arm64_read_insn fib_code 4294968704 = 0x90000010 := by
  rfl

theorem fib_insn_113 :
  arm64_read_insn fib_code 4294968708 = 0x91347210 := by
  rfl

theorem fib_insn_114 :
  arm64_read_insn fib_code 4294968712 = 0x14000012 := by
  rfl

theorem fib_insn_115 :
  arm64_read_insn fib_code 4294968716 = 0xf100017f := by
  rfl

theorem fib_insn_116 :
  arm64_read_insn fib_code 4294968720 = 0x54000120 := by
  rfl

theorem fib_insn_117 :
  arm64_read_insn fib_code 4294968724 = 0x1400001b := by
  rfl

theorem fib_insn_118 :
  arm64_read_insn fib_code 4294968728 = 0xb400008c := by
  rfl

theorem fib_insn_119 :
  arm64_read_insn fib_code 4294968732 = 0x90000010 := by
  rfl

theorem fib_insn_120 :
  arm64_read_insn fib_code 4294968736 = 0x91348210 := by
  rfl

theorem fib_insn_121 :
  arm64_read_insn fib_code 4294968740 = 0x1400000b := by
  rfl

theorem fib_insn_122 :
  arm64_read_insn fib_code 4294968744 = 0x90000010 := by
  rfl

theorem fib_insn_123 :
  arm64_read_insn fib_code 4294968748 = 0x91349610 := by
  rfl

theorem fib_insn_124 :
  arm64_read_insn fib_code 4294968752 = 0x14000008 := by
  rfl

theorem fib_insn_125 :
  arm64_read_insn fib_code 4294968756 = 0xb400008c := by
  rfl

theorem fib_insn_126 :
  arm64_read_insn fib_code 4294968760 = 0x90000010 := by
  rfl

theorem fib_insn_127 :
  arm64_read_insn fib_code 4294968764 = 0x9134a610 := by
  rfl

theorem fib_insn_128 :
  arm64_read_insn fib_code 4294968768 = 0x14000004 := by
  rfl

theorem fib_insn_129 :
  arm64_read_insn fib_code 4294968772 = 0x90000010 := by
  rfl

theorem fib_insn_130 :
  arm64_read_insn fib_code 4294968776 = 0x9134ba10 := by
  rfl

theorem fib_insn_131 :
  arm64_read_insn fib_code 4294968780 = 0x14000001 := by
  rfl

theorem fib_insn_132 :
  arm64_read_insn fib_code 4294968784 = 0xf9402be9 := by
  rfl

theorem fib_insn_133 :
  arm64_read_insn fib_code 4294968788 = 0x9100012f := by
  rfl

theorem fib_insn_134 :
  arm64_read_insn fib_code 4294968792 = 0xf9400208 := by
  rfl

theorem fib_insn_135 :
  arm64_read_insn fib_code 4294968796 = 0x13001d08 := by
  rfl

theorem fib_insn_136 :
  arm64_read_insn fib_code 4294968800 = 0x390001e8 := by
  rfl

theorem fib_insn_137 :
  arm64_read_insn fib_code 4294968804 = 0xb4000088 := by
  rfl

theorem fib_insn_138 :
  arm64_read_insn fib_code 4294968808 = 0x910005ef := by
  rfl

theorem fib_insn_139 :
  arm64_read_insn fib_code 4294968812 = 0x91000610 := by
  rfl

theorem fib_insn_140 :
  arm64_read_insn fib_code 4294968816 = 0x17fffffa := by
  rfl

theorem fib_insn_141 :
  arm64_read_insn fib_code 4294968820 = 0xf9402be0 := by
  rfl

theorem fib_insn_142 :
  arm64_read_insn fib_code 4294968824 = 0xa8c77bfd := by
  rfl

theorem fib_insn_143 :
  arm64_read_insn fib_code 4294968828 = 0xd65f03c0 := by
  rfl

theorem fib_insn_144 :
  arm64_read_insn fib_code 4294968832 = 0xd280002d := by
  rfl

theorem fib_insn_145 :
  arm64_read_insn fib_code 4294968836 = 0x910043e0 := by
  rfl

theorem fib_insn_146 :
  arm64_read_insn fib_code 4294968840 = 0xd2800401 := by
  rfl

theorem fib_insn_147 :
  arm64_read_insn fib_code 4294968844 = 0x90000002 := by
  rfl

theorem fib_insn_148 :
  arm64_read_insn fib_code 4294968848 = 0x9134c842 := by
  rfl

theorem fib_insn_149 :
  arm64_read_insn fib_code 4294968852 = 0xf90037ed := by
  rfl

theorem fib_insn_150 :
  arm64_read_insn fib_code 4294968856 = 0xd10103ff := by
  rfl

theorem fib_insn_151 :
  arm64_read_insn fib_code 4294968860 = 0xf90003ed := by
  rfl

theorem fib_insn_152 :
  arm64_read_insn fib_code 4294968864 = 0xf94047eb := by
  rfl

theorem fib_insn_153 :
  arm64_read_insn fib_code 4294968868 = 0xf90007eb := by
  rfl

theorem fib_insn_154 :
  arm64_read_insn fib_code 4294968872 = 0x940001c7 := by
  rfl

theorem fib_insn_155 :
  arm64_read_insn fib_code 4294968876 = 0x910103ff := by
  rfl

theorem fib_insn_156 :
  arm64_read_insn fib_code 4294968880 = 0x910043e0 := by
  rfl

theorem fib_insn_157 :
  arm64_read_insn fib_code 4294968884 = 0x910103e1 := by
  rfl

theorem fib_insn_158 :
  arm64_read_insn fib_code 4294968888 = 0x940001c6 := by
  rfl

theorem fib_insn_159 :
  arm64_read_insn fib_code 4294968892 = 0x9e66000e := by
  rfl

theorem fib_insn_160 :
  arm64_read_insn fib_code 4294968896 = 0xf94027eb := by
  rfl

theorem fib_insn_161 :
  arm64_read_insn fib_code 4294968900 = 0xeb0b01df := by
  rfl

theorem fib_insn_162 :
  arm64_read_insn fib_code 4294968904 = 0x540000a0 := by
  rfl

theorem fib_insn_163 :
  arm64_read_insn fib_code 4294968908 = 0xf94037ed := by
  rfl

theorem fib_insn_164 :
  arm64_read_insn fib_code 4294968912 = 0x910005ad := by
  rfl

theorem fib_insn_165 :
  arm64_read_insn fib_code 4294968916 = 0xf10049bf := by
  rfl

theorem fib_insn_166 :
  arm64_read_insn fib_code 4294968920 = 0x54fffd61 := by
  rfl

theorem fib_insn_167 :
  arm64_read_insn fib_code 4294968924 = 0x9100c3f1 := by
  rfl

theorem fib_insn_168 :
  arm64_read_insn fib_code 4294968928 = 0x910043f0 := by
  rfl

theorem fib_insn_169 :
  arm64_read_insn fib_code 4294968932 = 0x9100020a := by
  rfl

theorem fib_insn_170 :
  arm64_read_insn fib_code 4294968936 = 0xd280000d := by
  rfl

theorem fib_insn_171 :
  arm64_read_insn fib_code 4294968940 = 0xd280000e := by
  rfl

theorem fib_insn_172 :
  arm64_read_insn fib_code 4294968944 = 0xd280000f := by
  rfl

theorem fib_insn_173 :
  arm64_read_insn fib_code 4294968948 = 0xd2800003 := by
  rfl

theorem fib_insn_174 :
  arm64_read_insn fib_code 4294968952 = 0xd2800004 := by
  rfl

theorem fib_insn_175 :
  arm64_read_insn fib_code 4294968956 = 0xd2800005 := by
  rfl

theorem fib_insn_176 :
  arm64_read_insn fib_code 4294968960 = 0xd2800006 := by
  rfl

theorem fib_insn_177 :
  arm64_read_insn fib_code 4294968964 = 0xd2800012 := by
  rfl

theorem fib_insn_178 :
  arm64_read_insn fib_code 4294968968 = 0xd2800147 := by
  rfl

theorem fib_insn_179 :
  arm64_read_insn fib_code 4294968972 = 0xf9400148 := by
  rfl

theorem fib_insn_180 :
  arm64_read_insn fib_code 4294968976 = 0x13001d08 := by
  rfl

theorem fib_insn_181 :
  arm64_read_insn fib_code 4294968980 = 0xf100011f := by
  rfl

theorem fib_insn_182 :
  arm64_read_insn fib_code 4294968984 = 0x54000580 := by
  rfl

theorem fib_insn_183 :
  arm64_read_insn fib_code 4294968988 = 0xb50003ce := by
  rfl

theorem fib_insn_184 :
  arm64_read_insn fib_code 4294968992 = 0xf101951f := by
  rfl

theorem fib_insn_185 :
  arm64_read_insn fib_code 4294968996 = 0x540002a0 := by
  rfl

theorem fib_insn_186 :
  arm64_read_insn fib_code 4294969000 = 0xf100b91f := by
  rfl

theorem fib_insn_187 :
  arm64_read_insn fib_code 4294969004 = 0x540002a0 := by
  rfl

theorem fib_insn_188 :
  arm64_read_insn fib_code 4294969008 = 0xf100c11f := by
  rfl

theorem fib_insn_189 :
  arm64_read_insn fib_code 4294969012 = 0x54000463 := by
  rfl

theorem fib_insn_190 :
  arm64_read_insn fib_code 4294969016 = 0xf100e51f := by
  rfl

theorem fib_insn_191 :
  arm64_read_insn fib_code 4294969020 = 0x54000428 := by
  rfl

theorem fib_insn_192 :
  arm64_read_insn fib_code 4294969024 = 0xb4000044 := by
  rfl

theorem fib_insn_193 :
  arm64_read_insn fib_code 4294969028 = 0x14000002 := by
  rfl

theorem fib_insn_194 :
  arm64_read_insn fib_code 4294969032 = 0x91000652 := by
  rfl

theorem fib_insn_195 :
  arm64_read_insn fib_code 4294969036 = 0xf100c11f := by
  rfl

theorem fib_insn_196 :
  arm64_read_insn fib_code 4294969040 = 0x54000041 := by
  rfl

theorem fib_insn_197 :
  arm64_read_insn fib_code 4294969044 = 0xb4000363 := by
  rfl

theorem fib_insn_198 :
  arm64_read_insn fib_code 4294969048 = 0xb4000063 := by
  rfl

theorem fib_insn_199 :
  arm64_read_insn fib_code 4294969052 = 0x38236a28 := by
  rfl

theorem fib_insn_200 :
  arm64_read_insn fib_code 4294969056 = 0x14000004 := by
  rfl

theorem fib_insn_201 :
  arm64_read_insn fib_code 4294969060 = 0xcb10014d := by
  rfl

theorem fib_insn_202 :
  arm64_read_insn fib_code 4294969064 = 0x910001a5 := by
  rfl

theorem fib_insn_203 :
  arm64_read_insn fib_code 4294969068 = 0x38236a28 := by
  rfl

theorem fib_insn_204 :
  arm64_read_insn fib_code 4294969072 = 0x91000463 := by
  rfl

theorem fib_insn_205 :
  arm64_read_insn fib_code 4294969076 = 0x14000013 := by
  rfl

theorem fib_insn_206 :
  arm64_read_insn fib_code 4294969080 = 0xd280002e := by
  rfl

theorem fib_insn_207 :
  arm64_read_insn fib_code 4294969084 = 0x14000011 := by
  rfl

theorem fib_insn_208 :
  arm64_read_insn fib_code 4294969088 = 0xb4000044 := by
  rfl

theorem fib_insn_209 :
  arm64_read_insn fib_code 4294969092 = 0x1400000f := by
  rfl

theorem fib_insn_210 :
  arm64_read_insn fib_code 4294969096 = 0xcb10014d := by
  rfl

theorem fib_insn_211 :
  arm64_read_insn fib_code 4294969100 = 0x910001a4 := by
  rfl

theorem fib_insn_212 :
  arm64_read_insn fib_code 4294969104 = 0x1400000c := by
  rfl

theorem fib_insn_213 :
  arm64_read_insn fib_code 4294969108 = 0xf100ad1f := by
  rfl

theorem fib_insn_214 :
  arm64_read_insn fib_code 4294969112 = 0x54000061 := by
  rfl

theorem fib_insn_215 :
  arm64_read_insn fib_code 4294969116 = 0xd2800026 := by
  rfl

theorem fib_insn_216 :
  arm64_read_insn fib_code 4294969120 = 0x14000008 := by
  rfl

theorem fib_insn_217 :
  arm64_read_insn fib_code 4294969124 = 0xf100b51f := by
  rfl

theorem fib_insn_218 :
  arm64_read_insn fib_code 4294969128 = 0x54000061 := by
  rfl

theorem fib_insn_219 :
  arm64_read_insn fib_code 4294969132 = 0xd2800046 := by
  rfl

theorem fib_insn_220 :
  arm64_read_insn fib_code 4294969136 = 0x14000004 := by
  rfl

theorem fib_insn_221 :
  arm64_read_insn fib_code 4294969140 = 0xd100c108 := by
  rfl

theorem fib_insn_222 :
  arm64_read_insn fib_code 4294969144 = 0x9b077def := by
  rfl

theorem fib_insn_223 :
  arm64_read_insn fib_code 4294969148 = 0x8b0801ef := by
  rfl

theorem fib_insn_224 :
  arm64_read_insn fib_code 4294969152 = 0x9100054a := by
  rfl

theorem fib_insn_225 :
  arm64_read_insn fib_code 4294969156 = 0x17ffffd2 := by
  rfl

theorem fib_insn_226 :
  arm64_read_insn fib_code 4294969160 = 0xf9402bf0 := by
  rfl

theorem fib_insn_227 :
  arm64_read_insn fib_code 4294969164 = 0xf94033ec := by
  rfl

theorem fib_insn_228 :
  arm64_read_insn fib_code 4294969168 = 0xb40000ae := by
  rfl

theorem fib_insn_229 :
  arm64_read_insn fib_code 4294969172 = 0xf10008df := by
  rfl

theorem fib_insn_230 :
  arm64_read_insn fib_code 4294969176 = 0x54000041 := by
  rfl

theorem fib_insn_231 :
  arm64_read_insn fib_code 4294969180 = 0xcb0f03ef := by
  rfl

theorem fib_insn_232 :
  arm64_read_insn fib_code 4294969184 = 0x14000007 := by
  rfl

theorem fib_insn_233 :
  arm64_read_insn fib_code 4294969188 = 0xb4000064 := by
  rfl

theorem fib_insn_234 :
  arm64_read_insn fib_code 4294969192 = 0xeb0400bf := by
  rfl

theorem fib_insn_235 :
  arm64_read_insn fib_code 4294969196 = 0x54000062 := by
  rfl

theorem fib_insn_236 :
  arm64_read_insn fib_code 4294969200 = 0xd100064f := by
  rfl

theorem fib_insn_237 :
  arm64_read_insn fib_code 4294969204 = 0x14000002 := by
  rfl

theorem fib_insn_238 :
  arm64_read_insn fib_code 4294969208 = 0xcb05008f := by
  rfl

theorem fib_insn_239 :
  arm64_read_insn fib_code 4294969212 = 0xf10041ff := by
  rfl

theorem fib_insn_240 :
  arm64_read_insn fib_code 4294969216 = 0x540000aa := by
  rfl

theorem fib_insn_241 :
  arm64_read_insn fib_code 4294969220 = 0xcb0f03e8 := by
  rfl

theorem fib_insn_242 :
  arm64_read_insn fib_code 4294969224 = 0xf100151f := by
  rfl

theorem fib_insn_243 :
  arm64_read_insn fib_code 4294969228 = 0x5400004a := by
  rfl

theorem fib_insn_244 :
  arm64_read_insn fib_code 4294969232 = 0x14000001 := by
  rfl

theorem fib_insn_245 :
  arm64_read_insn fib_code 4294969236 = 0xb400008c := by
  rfl

theorem fib_insn_246 :
  arm64_read_insn fib_code 4294969240 = 0xd28005a8 := by
  rfl

theorem fib_insn_247 :
  arm64_read_insn fib_code 4294969244 = 0x39000208 := by
  rfl

theorem fib_insn_248 :
  arm64_read_insn fib_code 4294969248 = 0x91000610 := by
  rfl

theorem fib_insn_249 :
  arm64_read_insn fib_code 4294969252 = 0xf10041ff := by
  rfl

theorem fib_insn_250 :
  arm64_read_insn fib_code 4294969256 = 0x5400004a := by
  rfl

theorem fib_insn_251 :
  arm64_read_insn fib_code 4294969260 = 0x14000041 := by
  rfl

theorem fib_insn_252 :
  arm64_read_insn fib_code 4294969264 = 0xf940022b := by
  rfl

theorem fib_insn_253 :
  arm64_read_insn fib_code 4294969268 = 0x13001d6b := by
  rfl

theorem fib_insn_254 :
  arm64_read_insn fib_code 4294969272 = 0x3900020b := by
  rfl

theorem fib_insn_255 :
  arm64_read_insn fib_code 4294969276 = 0x91000610 := by
  rfl

theorem fib_insn_256 :
  arm64_read_insn fib_code 4294969280 = 0xf100047f := by
  rfl

theorem fib_insn_257 :
  arm64_read_insn fib_code 4294969284 = 0x540001a0 := by
  rfl

theorem fib_insn_258 :
  arm64_read_insn fib_code 4294969288 = 0xd28005c8 := by
  rfl

theorem fib_insn_259 :
  arm64_read_insn fib_code 4294969292 = 0x39000208 := by
  rfl

theorem fib_insn_260 :
  arm64_read_insn fib_code 4294969296 = 0x91000610 := by
  rfl

theorem fib_insn_261 :
  arm64_read_insn fib_code 4294969300 = 0xd280002a := by
  rfl

theorem fib_insn_262 :
  arm64_read_insn fib_code 4294969304 = 0xeb03015f := by
  rfl

theorem fib_insn_263 :
  arm64_read_insn fib_code 4294969308 = 0x540000ea := by
  rfl

theorem fib_insn_264 :
  arm64_read_insn fib_code 4294969312 = 0xf86a6a2b := by
  rfl

theorem fib_insn_265 :
  arm64_read_insn fib_code 4294969316 = 0x13001d6b := by
  rfl

theorem fib_insn_266 :
  arm64_read_insn fib_code 4294969320 = 0x3900020b := by
  rfl

theorem fib_insn_267 :
  arm64_read_insn fib_code 4294969324 = 0x91000610 := by
  rfl

theorem fib_insn_268 :
  arm64_read_insn fib_code 4294969328 = 0x9100054a := by
  rfl

theorem fib_insn_269 :
  arm64_read_insn fib_code 4294969332 = 0x17fffff9 := by
  rfl

theorem fib_insn_270 :
  arm64_read_insn fib_code 4294969336 = 0xd2800ca8 := by
  rfl

theorem fib_insn_271 :
  arm64_read_insn fib_code 4294969340 = 0x39000208 := by
  rfl

theorem fib_insn_272 :
  arm64_read_insn fib_code 4294969344 = 0x91000610 := by
  rfl

theorem fib_insn_273 :
  arm64_read_insn fib_code 4294969348 = 0xf10001ff := by
  rfl

theorem fib_insn_274 :
  arm64_read_insn fib_code 4294969352 = 0x540000a4 := by
  rfl

theorem fib_insn_275 :
  arm64_read_insn fib_code 4294969356 = 0xd2800568 := by
  rfl

theorem fib_insn_276 :
  arm64_read_insn fib_code 4294969360 = 0x39000208 := by
  rfl

theorem fib_insn_277 :
  arm64_read_insn fib_code 4294969364 = 0x91000610 := by
  rfl

theorem fib_insn_278 :
  arm64_read_insn fib_code 4294969368 = 0x14000004 := by
  rfl

theorem fib_insn_279 :
  arm64_read_insn fib_code 4294969372 = 0xd28005a8 := by
  rfl

theorem fib_insn_280 :
  arm64_read_insn fib_code 4294969376 = 0x39000208 := by
  rfl

theorem fib_insn_281 :
  arm64_read_insn fib_code 4294969380 = 0x91000610 := by
  rfl

theorem fib_insn_282 :
  arm64_read_insn fib_code 4294969384 = 0xf10001ff := by
  rfl

theorem fib_insn_283 :
  arm64_read_insn fib_code 4294969388 = 0x5400004a := by
  rfl

theorem fib_insn_284 :
  arm64_read_insn fib_code 4294969392 = 0xcb0f03ef := by
  rfl

theorem fib_insn_285 :
  arm64_read_insn fib_code 4294969396 = 0xf10191ff := by
  rfl

theorem fib_insn_286 :
  arm64_read_insn fib_code 4294969400 = 0x5400024b := by
  rfl

theorem fib_insn_287 :
  arm64_read_insn fib_code 4294969404 = 0xd2800c92 := by
  rfl

theorem fib_insn_288 :
  arm64_read_insn fib_code 4294969408 = 0x9ad209ea := by
  rfl

theorem fib_insn_289 :
  arm64_read_insn fib_code 4294969412 = 0x9b127d4b := by
  rfl

theorem fib_insn_290 :
  arm64_read_insn fib_code 4294969416 = 0xcb0b01eb := by
  rfl

theorem fib_insn_291 :
  arm64_read_insn fib_code 4294969420 = 0x9100c14a := by
  rfl

theorem fib_insn_292 :
  arm64_read_insn fib_code 4294969424 = 0x3900020a := by
  rfl

theorem fib_insn_293 :
  arm64_read_insn fib_code 4294969428 = 0x91000610 := by
  rfl

theorem fib_insn_294 :
  arm64_read_insn fib_code 4294969432 = 0xd2800152 := by
  rfl

theorem fib_insn_295 :
  arm64_read_insn fib_code 4294969436 = 0x9ad2096a := by
  rfl

theorem fib_insn_296 :
  arm64_read_insn fib_code 4294969440 = 0x9b127d49 := by
  rfl

theorem fib_insn_297 :
  arm64_read_insn fib_code 4294969444 = 0xcb090169 := by
  rfl

theorem fib_insn_298 :
  arm64_read_insn fib_code 4294969448 = 0x9100c14a := by
  rfl

theorem fib_insn_299 :
  arm64_read_insn fib_code 4294969452 = 0x3900020a := by
  rfl

theorem fib_insn_300 :
  arm64_read_insn fib_code 4294969456 = 0x91000610 := by
  rfl

theorem fib_insn_301 :
  arm64_read_insn fib_code 4294969460 = 0x9100c129 := by
  rfl

theorem fib_insn_302 :
  arm64_read_insn fib_code 4294969464 = 0x39000209 := by
  rfl

theorem fib_insn_303 :
  arm64_read_insn fib_code 4294969468 = 0x1400000a := by
  rfl

theorem fib_insn_304 :
  arm64_read_insn fib_code 4294969472 = 0xd2800152 := by
  rfl

theorem fib_insn_305 :
  arm64_read_insn fib_code 4294969476 = 0x9ad209ea := by
  rfl

theorem fib_insn_306 :
  arm64_read_insn fib_code 4294969480 = 0x9b127d49 := by
  rfl

theorem fib_insn_307 :
  arm64_read_insn fib_code 4294969484 = 0xcb0901e9 := by
  rfl

theorem fib_insn_308 :
  arm64_read_insn fib_code 4294969488 = 0x9100c14a := by
  rfl

theorem fib_insn_309 :
  arm64_read_insn fib_code 4294969492 = 0x3900020a := by
  rfl

theorem fib_insn_310 :
  arm64_read_insn fib_code 4294969496 = 0x91000610 := by
  rfl

theorem fib_insn_311 :
  arm64_read_insn fib_code 4294969500 = 0x9100c129 := by
  rfl

theorem fib_insn_312 :
  arm64_read_insn fib_code 4294969504 = 0x39000209 := by
  rfl

theorem fib_insn_313 :
  arm64_read_insn fib_code 4294969508 = 0xd2800008 := by
  rfl

theorem fib_insn_314 :
  arm64_read_insn fib_code 4294969512 = 0x39000208 := by
  rfl

theorem fib_insn_315 :
  arm64_read_insn fib_code 4294969516 = 0x17ffff52 := by
  rfl

theorem fib_insn_316 :
  arm64_read_insn fib_code 4294969520 = 0xf10001ff := by
  rfl

theorem fib_insn_317 :
  arm64_read_insn fib_code 4294969524 = 0x5400030a := by
  rfl

theorem fib_insn_318 :
  arm64_read_insn fib_code 4294969528 = 0xd2800608 := by
  rfl

theorem fib_insn_319 :
  arm64_read_insn fib_code 4294969532 = 0x39000208 := by
  rfl

theorem fib_insn_320 :
  arm64_read_insn fib_code 4294969536 = 0x91000610 := by
  rfl

theorem fib_insn_321 :
  arm64_read_insn fib_code 4294969540 = 0xd28005c8 := by
  rfl

theorem fib_insn_322 :
  arm64_read_insn fib_code 4294969544 = 0x39000208 := by
  rfl

theorem fib_insn_323 :
  arm64_read_insn fib_code 4294969548 = 0x91000610 := by
  rfl

theorem fib_insn_324 :
  arm64_read_insn fib_code 4294969552 = 0xcb0f03ea := by
  rfl

theorem fib_insn_325 :
  arm64_read_insn fib_code 4294969556 = 0xd100054a := by
  rfl

theorem fib_insn_326 :
  arm64_read_insn fib_code 4294969560 = 0xb40000ca := by
  rfl

theorem fib_insn_327 :
  arm64_read_insn fib_code 4294969564 = 0xd2800608 := by
  rfl

theorem fib_insn_328 :
  arm64_read_insn fib_code 4294969568 = 0x39000208 := by
  rfl

theorem fib_insn_329 :
  arm64_read_insn fib_code 4294969572 = 0x91000610 := by
  rfl

theorem fib_insn_330 :
  arm64_read_insn fib_code 4294969576 = 0xd100054a := by
  rfl

theorem fib_insn_331 :
  arm64_read_insn fib_code 4294969580 = 0x17fffffb := by
  rfl

theorem fib_insn_332 :
  arm64_read_insn fib_code 4294969584 = 0xd280000a := by
  rfl

theorem fib_insn_333 :
  arm64_read_insn fib_code 4294969588 = 0xeb03015f := by
  rfl

theorem fib_insn_334 :
  arm64_read_insn fib_code 4294969592 = 0x54fffd6a := by
  rfl

theorem fib_insn_335 :
  arm64_read_insn fib_code 4294969596 = 0xf86a6a2b := by
  rfl

theorem fib_insn_336 :
  arm64_read_insn fib_code 4294969600 = 0x13001d6b := by
  rfl

theorem fib_insn_337 :
  arm64_read_insn fib_code 4294969604 = 0x3900020b := by
  rfl

theorem fib_insn_338 :
  arm64_read_insn fib_code 4294969608 = 0x91000610 := by
  rfl

theorem fib_insn_339 :
  arm64_read_insn fib_code 4294969612 = 0x9100054a := by
  rfl

theorem fib_insn_340 :
  arm64_read_insn fib_code 4294969616 = 0x17fffff9 := by
  rfl

theorem fib_insn_341 :
  arm64_read_insn fib_code 4294969620 = 0x910005f2 := by
  rfl

theorem fib_insn_342 :
  arm64_read_insn fib_code 4294969624 = 0xeb12007f := by
  rfl

theorem fib_insn_343 :
  arm64_read_insn fib_code 4294969628 = 0x540002cd := by
  rfl

theorem fib_insn_344 :
  arm64_read_insn fib_code 4294969632 = 0xd280000a := by
  rfl

theorem fib_insn_345 :
  arm64_read_insn fib_code 4294969636 = 0xeb12015f := by
  rfl

theorem fib_insn_346 :
  arm64_read_insn fib_code 4294969640 = 0x540000ea := by
  rfl

theorem fib_insn_347 :
  arm64_read_insn fib_code 4294969644 = 0xf86a6a2b := by
  rfl

theorem fib_insn_348 :
  arm64_read_insn fib_code 4294969648 = 0x13001d6b := by
  rfl

theorem fib_insn_349 :
  arm64_read_insn fib_code 4294969652 = 0x3900020b := by
  rfl

theorem fib_insn_350 :
  arm64_read_insn fib_code 4294969656 = 0x91000610 := by
  rfl

theorem fib_insn_351 :
  arm64_read_insn fib_code 4294969660 = 0x9100054a := by
  rfl

theorem fib_insn_352 :
  arm64_read_insn fib_code 4294969664 = 0x17fffff9 := by
  rfl

theorem fib_insn_353 :
  arm64_read_insn fib_code 4294969668 = 0xd28005c8 := by
  rfl

theorem fib_insn_354 :
  arm64_read_insn fib_code 4294969672 = 0x39000208 := by
  rfl

theorem fib_insn_355 :
  arm64_read_insn fib_code 4294969676 = 0x91000610 := by
  rfl

theorem fib_insn_356 :
  arm64_read_insn fib_code 4294969680 = 0x9100024a := by
  rfl

theorem fib_insn_357 :
  arm64_read_insn fib_code 4294969684 = 0xeb03015f := by
  rfl

theorem fib_insn_358 :
  arm64_read_insn fib_code 4294969688 = 0x54fffa6a := by
  rfl

theorem fib_insn_359 :
  arm64_read_insn fib_code 4294969692 = 0xf86a6a2b := by
  rfl

theorem fib_insn_360 :
  arm64_read_insn fib_code 4294969696 = 0x13001d6b := by
  rfl

theorem fib_insn_361 :
  arm64_read_insn fib_code 4294969700 = 0x3900020b := by
  rfl

theorem fib_insn_362 :
  arm64_read_insn fib_code 4294969704 = 0x91000610 := by
  rfl

theorem fib_insn_363 :
  arm64_read_insn fib_code 4294969708 = 0x9100054a := by
  rfl

theorem fib_insn_364 :
  arm64_read_insn fib_code 4294969712 = 0x17fffff9 := by
  rfl

theorem fib_insn_365 :
  arm64_read_insn fib_code 4294969716 = 0xd280000a := by
  rfl

theorem fib_insn_366 :
  arm64_read_insn fib_code 4294969720 = 0xeb03015f := by
  rfl

theorem fib_insn_367 :
  arm64_read_insn fib_code 4294969724 = 0x540000ea := by
  rfl

theorem fib_insn_368 :
  arm64_read_insn fib_code 4294969728 = 0xf86a6a2b := by
  rfl

theorem fib_insn_369 :
  arm64_read_insn fib_code 4294969732 = 0x13001d6b := by
  rfl

theorem fib_insn_370 :
  arm64_read_insn fib_code 4294969736 = 0x3900020b := by
  rfl

theorem fib_insn_371 :
  arm64_read_insn fib_code 4294969740 = 0x91000610 := by
  rfl

theorem fib_insn_372 :
  arm64_read_insn fib_code 4294969744 = 0x9100054a := by
  rfl

theorem fib_insn_373 :
  arm64_read_insn fib_code 4294969748 = 0x17fffff9 := by
  rfl

theorem fib_insn_374 :
  arm64_read_insn fib_code 4294969752 = 0x9100024b := by
  rfl

theorem fib_insn_375 :
  arm64_read_insn fib_code 4294969756 = 0xcb03016b := by
  rfl

theorem fib_insn_376 :
  arm64_read_insn fib_code 4294969760 = 0xb40000cb := by
  rfl

theorem fib_insn_377 :
  arm64_read_insn fib_code 4294969764 = 0xd2800608 := by
  rfl

theorem fib_insn_378 :
  arm64_read_insn fib_code 4294969768 = 0x39000208 := by
  rfl

theorem fib_insn_379 :
  arm64_read_insn fib_code 4294969772 = 0x91000610 := by
  rfl

theorem fib_insn_380 :
  arm64_read_insn fib_code 4294969776 = 0xd100056b := by
  rfl

theorem fib_insn_381 :
  arm64_read_insn fib_code 4294969780 = 0x17fffffb := by
  rfl

theorem fib_insn_382 :
  arm64_read_insn fib_code 4294969784 = 0xd28005c8 := by
  rfl

theorem fib_insn_383 :
  arm64_read_insn fib_code 4294969788 = 0x39000208 := by
  rfl

theorem fib_insn_384 :
  arm64_read_insn fib_code 4294969792 = 0x91000610 := by
  rfl

theorem fib_insn_385 :
  arm64_read_insn fib_code 4294969796 = 0xd2800608 := by
  rfl

theorem fib_insn_386 :
  arm64_read_insn fib_code 4294969800 = 0x39000208 := by
  rfl

theorem fib_insn_387 :
  arm64_read_insn fib_code 4294969804 = 0x91000610 := by
  rfl

theorem fib_insn_388 :
  arm64_read_insn fib_code 4294969808 = 0x17ffffb5 := by
  rfl

theorem fib_insn_389 :
  arm64_read_insn fib_code 4294969812 = 0x75636552 := by
  rfl

theorem fib_insn_390 :
  arm64_read_insn fib_code 4294969816 = 0x6f697372 := by
  rfl

theorem fib_insn_391 :
  arm64_read_insn fib_code 4294969820 = 0x7272456e := by
  rfl

theorem fib_insn_392 :
  arm64_read_insn fib_code 4294969824 = 0x203a726f := by
  rfl

theorem fib_insn_393 :
  arm64_read_insn fib_code 4294969828 = 0x73696874 := by
  rfl

theorem fib_insn_394 :
  arm64_read_insn fib_code 4294969832 = 0x6f727020 := by
  rfl

theorem fib_insn_395 :
  arm64_read_insn fib_code 4294969836 = 0x6d617267 := by
  rfl

theorem fib_insn_396 :
  arm64_read_insn fib_code 4294969840 = 0x63207327 := by
  rfl

theorem fib_insn_397 :
  arm64_read_insn fib_code 4294969844 = 0x206c6c61 := by
  rfl

theorem fib_insn_398 :
  arm64_read_insn fib_code 4294969848 = 0x63617473 := by
  rfl

theorem fib_insn_399 :
  arm64_read_insn fib_code 4294969852 = 0x6577206b := by
  rfl

theorem fib_insn_400 :
  arm64_read_insn fib_code 4294969856 = 0x7020746e := by
  rfl

theorem fib_insn_401 :
  arm64_read_insn fib_code 4294969860 = 0x20747361 := by
  rfl

theorem fib_insn_402 :
  arm64_read_insn fib_code 4294969864 = 0x20656874 := by
  rfl

theorem fib_insn_403 :
  arm64_read_insn fib_code 4294969868 = 0x63617473 := by
  rfl

theorem fib_insn_404 :
  arm64_read_insn fib_code 4294969872 = 0x7562206b := by
  rfl

theorem fib_insn_405 :
  arm64_read_insn fib_code 4294969876 = 0x74656764 := by
  rfl

theorem fib_insn_406 :
  arm64_read_insn fib_code 4294969880 = 0x20666f20 := by
  rfl

theorem fib_insn_407 :
  arm64_read_insn fib_code 4294969884 = 0x34363837 := by
  rfl

theorem fib_insn_408 :
  arm64_read_insn fib_code 4294969888 = 0x20303233 := by
  rfl

theorem fib_insn_409 :
  arm64_read_insn fib_code 4294969892 = 0x65747962 := by
  rfl

theorem fib_insn_410 :
  arm64_read_insn fib_code 4294969896 = 0x77202c73 := by
  rfl

theorem fib_insn_411 :
  arm64_read_insn fib_code 4294969900 = 0x68636968 := by
  rfl

theorem fib_insn_412 :
  arm64_read_insn fib_code 4294969904 = 0x20736920 := by
  rfl

theorem fib_insn_413 :
  arm64_read_insn fib_code 4294969908 = 0x20656874 := by
  rfl

theorem fib_insn_414 :
  arm64_read_insn fib_code 4294969912 = 0x6c616d73 := by
  rfl

theorem fib_insn_415 :
  arm64_read_insn fib_code 4294969916 = 0x2072656c := by
  rfl

theorem fib_insn_416 :
  arm64_read_insn fib_code 4294969920 = 0x7420666f := by
  rfl

theorem fib_insn_417 :
  arm64_read_insn fib_code 4294969924 = 0x20746168 := by
  rfl

theorem fib_insn_418 :
  arm64_read_insn fib_code 4294969928 = 0x626d756e := by
  rfl

theorem fib_insn_419 :
  arm64_read_insn fib_code 4294969932 = 0x61207265 := by
  rfl

theorem fib_insn_420 :
  arm64_read_insn fib_code 4294969936 = 0x7420646e := by
  rfl

theorem fib_insn_421 :
  arm64_read_insn fib_code 4294969940 = 0x20736968 := by
  rfl

theorem fib_insn_422 :
  arm64_read_insn fib_code 4294969944 = 0x636f7270 := by
  rfl

theorem fib_insn_423 :
  arm64_read_insn fib_code 4294969948 = 0x27737365 := by
  rfl

theorem fib_insn_424 :
  arm64_read_insn fib_code 4294969952 = 0x776f2073 := by
  rfl

theorem fib_insn_425 :
  arm64_read_insn fib_code 4294969956 = 0x7473206e := by
  rfl

theorem fib_insn_426 :
  arm64_read_insn fib_code 4294969960 = 0x206b6361 := by
  rfl

theorem fib_insn_427 :
  arm64_read_insn fib_code 4294969964 = 0x696d696c := by
  rfl

theorem fib_insn_428 :
  arm64_read_insn fib_code 4294969968 = 0x656c2074 := by
  rfl

theorem fib_insn_429 :
  arm64_read_insn fib_code 4294969972 = 0x32207373 := by
  rfl

theorem fib_insn_430 :
  arm64_read_insn fib_code 4294969976 = 0x34313236 := by
  rfl

theorem fib_insn_431 :
  arm64_read_insn fib_code 4294969980 = 0x79622034 := by
  rfl

theorem fib_insn_432 :
  arm64_read_insn fib_code 4294969984 = 0x20736574 := by
  rfl

theorem fib_insn_433 :
  arm64_read_insn fib_code 4294969988 = 0x7220666f := by
  rfl

theorem fib_insn_434 :
  arm64_read_insn fib_code 4294969992 = 0x72657365 := by
  rfl

theorem fib_insn_435 :
  arm64_read_insn fib_code 4294969996 = 0xe2206576 := by
  rfl

theorem fib_insn_436 :
  arm64_read_insn fib_code 4294970000 = 0x73209480 := by
  rfl

theorem fib_insn_437 :
  arm64_read_insn fib_code 4294970004 = 0x2061206f := by
  rfl

theorem fib_insn_438 :
  arm64_read_insn fib_code 4294970008 = 0x636f7270 := by
  rfl

theorem fib_insn_439 :
  arm64_read_insn fib_code 4294970012 = 0x20737365 := by
  rfl

theorem fib_insn_440 :
  arm64_read_insn fib_code 4294970016 = 0x68746977 := by
  rfl

theorem fib_insn_441 :
  arm64_read_insn fib_code 4294970020 = 0x73206120 := by
  rfl

theorem fib_insn_442 :
  arm64_read_insn fib_code 4294970024 = 0x6c6c616d := by
  rfl

theorem fib_insn_443 :
  arm64_read_insn fib_code 4294970028 = 0x73207265 := by
  rfl

theorem fib_insn_444 :
  arm64_read_insn fib_code 4294970032 = 0x6b636174 := by
  rfl

theorem fib_insn_445 :
  arm64_read_insn fib_code 4294970036 = 0x66657220 := by
  rfl

theorem fib_insn_446 :
  arm64_read_insn fib_code 4294970040 = 0x73657375 := by
  rfl

theorem fib_insn_447 :
  arm64_read_insn fib_code 4294970044 = 0x4f4f5320 := by
  rfl

theorem fib_insn_448 :
  arm64_read_insn fib_code 4294970048 = 0x2c52454e := by
  rfl

theorem fib_insn_449 :
  arm64_read_insn fib_code 4294970052 = 0x646e6120 := by
  rfl

theorem fib_insn_450 :
  arm64_read_insn fib_code 4294970056 = 0x76656e20 := by
  rfl

theorem fib_insn_451 :
  arm64_read_insn fib_code 4294970060 = 0x6c207265 := by
  rfl

theorem fib_insn_452 :
  arm64_read_insn fib_code 4294970064 = 0x72657461 := by
  rfl

theorem fib_insn_453 :
  arm64_read_insn fib_code 4294970068 = 0x61687420 := by
  rfl

theorem fib_insn_454 :
  arm64_read_insn fib_code 4294970072 = 0x6874206e := by
  rfl

theorem fib_insn_455 :
  arm64_read_insn fib_code 4294970076 = 0x202e7369 := by
  rfl

theorem fib_insn_456 :
  arm64_read_insn fib_code 4294970080 = 0x74795043 := by
  rfl

theorem fib_insn_457 :
  arm64_read_insn fib_code 4294970084 = 0x206e6f68 := by
  rfl

theorem fib_insn_458 :
  arm64_read_insn fib_code 4294970088 = 0x73696172 := by
  rfl

theorem fib_insn_459 :
  arm64_read_insn fib_code 4294970092 = 0x52207365 := by
  rfl

theorem fib_insn_460 :
  arm64_read_insn fib_code 4294970096 = 0x72756365 := by
  rfl

theorem fib_insn_461 :
  arm64_read_insn fib_code 4294970100 = 0x6e6f6973 := by
  rfl

theorem fib_insn_462 :
  arm64_read_insn fib_code 4294970104 = 0x6f727245 := by
  rfl

theorem fib_insn_463 :
  arm64_read_insn fib_code 4294970108 = 0x6f662072 := by
  rfl

theorem fib_insn_464 :
  arm64_read_insn fib_code 4294970112 = 0x20612072 := by
  rfl

theorem fib_insn_465 :
  arm64_read_insn fib_code 4294970116 = 0x75636572 := by
  rfl

theorem fib_insn_466 :
  arm64_read_insn fib_code 4294970120 = 0x6f697372 := by
  rfl

theorem fib_insn_467 :
  arm64_read_insn fib_code 4294970124 = 0x6874206e := by
  rfl

theorem fib_insn_468 :
  arm64_read_insn fib_code 4294970128 = 0x64207369 := by
  rfl

theorem fib_insn_469 :
  arm64_read_insn fib_code 4294970132 = 0x2c706565 := by
  rfl

theorem fib_insn_470 :
  arm64_read_insn fib_code 4294970136 = 0x646e6120 := by
  rfl

theorem fib_insn_471 :
  arm64_read_insn fib_code 4294970140 = 0x73797320 := by
  rfl

theorem fib_insn_472 :
  arm64_read_insn fib_code 4294970144 = 0x7465732e := by
  rfl

theorem fib_insn_473 :
  arm64_read_insn fib_code 4294970148 = 0x75636572 := by
  rfl

theorem fib_insn_474 :
  arm64_read_insn fib_code 4294970152 = 0x6f697372 := by
  rfl

theorem fib_insn_475 :
  arm64_read_insn fib_code 4294970156 = 0x6d696c6e := by
  rfl

theorem fib_insn_476 :
  arm64_read_insn fib_code 4294970160 = 0x63207469 := by
  rfl

theorem fib_insn_477 :
  arm64_read_insn fib_code 4294970164 = 0x6f6e6e61 := by
  rfl

theorem fib_insn_478 :
  arm64_read_insn fib_code 4294970168 = 0x65682074 := by
  rfl

theorem fib_insn_479 :
  arm64_read_insn fib_code 4294970172 = 0x6820706c := by
  rfl

theorem fib_insn_480 :
  arm64_read_insn fib_code 4294970176 = 0x3a657265 := by
  rfl

theorem fib_insn_481 :
  arm64_read_insn fib_code 4294970180 = 0x69687420 := by
  rfl

theorem fib_insn_482 :
  arm64_read_insn fib_code 4294970184 = 0x61742073 := by
  rfl

theorem fib_insn_483 :
  arm64_read_insn fib_code 4294970188 = 0x74656772 := by
  rfl

theorem fib_insn_484 :
  arm64_read_insn fib_code 4294970192 = 0x73616820 := by
  rfl

theorem fib_insn_485 :
  arm64_read_insn fib_code 4294970196 = 0x206f6e20 := by
  rfl

theorem fib_insn_486 :
  arm64_read_insn fib_code 4294970200 = 0x65746e69 := by
  rfl

theorem fib_insn_487 :
  arm64_read_insn fib_code 4294970204 = 0x65727072 := by
  rfl

theorem fib_insn_488 :
  arm64_read_insn fib_code 4294970208 = 0x20726574 := by
  rfl

theorem fib_insn_489 :
  arm64_read_insn fib_code 4294970212 = 0x63617473 := by
  rfl

theorem fib_insn_490 :
  arm64_read_insn fib_code 4294970216 = 0x6f74206b := by
  rfl

theorem fib_insn_491 :
  arm64_read_insn fib_code 4294970220 = 0x69617220 := by
  rfl

theorem fib_insn_492 :
  arm64_read_insn fib_code 4294970224 = 0x61206573 := by
  rfl

theorem fib_insn_493 :
  arm64_read_insn fib_code 4294970228 = 0x6d696c20 := by
  rfl

theorem fib_insn_494 :
  arm64_read_insn fib_code 4294970232 = 0x6f207469 := by
  rfl

theorem fib_insn_495 :
  arm64_read_insn fib_code 4294970236 = 0x61202c6e := by
  rfl

theorem fib_insn_496 :
  arm64_read_insn fib_code 4294970240 = 0x6920646e := by
  rfl

theorem fib_insn_497 :
  arm64_read_insn fib_code 4294970244 = 0x6f632074 := by
  rfl

theorem fib_insn_498 :
  arm64_read_insn fib_code 4294970248 = 0x6c69706d := by
  rfl

theorem fib_insn_499 :
  arm64_read_insn fib_code 4294970252 = 0x74207365 := by
  rfl

theorem fib_insn_500 :
  arm64_read_insn fib_code 4294970256 = 0x6c206568 := by
  rfl

theorem fib_insn_501 :
  arm64_read_insn fib_code 4294970260 = 0x74696d69 := by
  rfl

theorem fib_insn_502 :
  arm64_read_insn fib_code 4294970264 = 0x756f7920 := by
  rfl

theorem fib_insn_503 :
  arm64_read_insn fib_code 4294970268 = 0x6b736120 := by
  rfl

theorem fib_insn_504 :
  arm64_read_insn fib_code 4294970272 = 0x726f6620 := by
  rfl

theorem fib_insn_505 :
  arm64_read_insn fib_code 4294970276 = 0x74697720 := by
  rfl

theorem fib_insn_506 :
  arm64_read_insn fib_code 4294970280 = 0x74756f68 := by
  rfl

theorem fib_insn_507 :
  arm64_read_insn fib_code 4294970284 = 0x61686320 := by
  rfl

theorem fib_insn_508 :
  arm64_read_insn fib_code 4294970288 = 0x6e69676e := by
  rfl

theorem fib_insn_509 :
  arm64_read_insn fib_code 4294970292 = 0x6e612067 := by
  rfl

theorem fib_insn_510 :
  arm64_read_insn fib_code 4294970296 = 0x69687479 := by
  rfl

theorem fib_insn_511 :
  arm64_read_insn fib_code 4294970300 = 0x202e676e := by
  rfl

theorem fib_insn_512 :
  arm64_read_insn fib_code 4294970304 = 0x20656854 := by
  rfl

theorem fib_insn_513 :
  arm64_read_insn fib_code 4294970308 = 0x74706564 := by
  rfl

theorem fib_insn_514 :
  arm64_read_insn fib_code 4294970312 = 0x68742068 := by
  rfl

theorem fib_insn_515 :
  arm64_read_insn fib_code 4294970316 = 0x66207461 := by
  rfl

theorem fib_insn_516 :
  arm64_read_insn fib_code 4294970320 = 0x20737469 := by
  rfl

theorem fib_insn_517 :
  arm64_read_insn fib_code 4294970324 = 0x74207369 := by
  rfl

theorem fib_insn_518 :
  arm64_read_insn fib_code 4294970328 = 0x62206568 := by
  rfl

theorem fib_insn_519 :
  arm64_read_insn fib_code 4294970332 = 0x65676475 := by
  rfl

theorem fib_insn_520 :
  arm64_read_insn fib_code 4294970336 = 0x69642074 := by
  rfl

theorem fib_insn_521 :
  arm64_read_insn fib_code 4294970340 = 0x65646976 := by
  rfl

theorem fib_insn_522 :
  arm64_read_insn fib_code 4294970344 = 0x79622064 := by
  rfl

theorem fib_insn_523 :
  arm64_read_insn fib_code 4294970348 = 0x656e6f20 := by
  rfl

theorem fib_insn_524 :
  arm64_read_insn fib_code 4294970352 = 0x6c616320 := by
  rfl

theorem fib_insn_525 :
  arm64_read_insn fib_code 4294970356 = 0x7266206c := by
  rfl

theorem fib_insn_526 :
  arm64_read_insn fib_code 4294970360 = 0x3b656d61 := by
  rfl

theorem fib_insn_527 :
  arm64_read_insn fib_code 4294970364 = 0x66206120 := by
  rfl

theorem fib_insn_528 :
  arm64_read_insn fib_code 4294970368 = 0x656d6172 := by
  rfl

theorem fib_insn_529 :
  arm64_read_insn fib_code 4294970372 = 0x20736920 := by
  rfl

theorem fib_insn_530 :
  arm64_read_insn fib_code 4294970376 = 0x30313331 := by
  rfl

theorem fib_insn_531 :
  arm64_read_insn fib_code 4294970380 = 0x62203237 := by
  rfl

theorem fib_insn_532 :
  arm64_read_insn fib_code 4294970384 = 0x73657479 := by
  rfl

theorem fib_insn_533 :
  arm64_read_insn fib_code 4294970388 = 0x206e6f20 := by
  rfl

theorem fib_insn_534 :
  arm64_read_insn fib_code 4294970392 = 0x366d7261 := by
  rfl

theorem fib_insn_535 :
  arm64_read_insn fib_code 4294970396 = 0x6e612034 := by
  rfl

theorem fib_insn_536 :
  arm64_read_insn fib_code 4294970400 = 0x36312064 := by
  rfl

theorem fib_insn_537 :
  arm64_read_insn fib_code 4294970404 = 0x20343833 := by
  rfl

theorem fib_insn_538 :
  arm64_read_insn fib_code 4294970408 = 0x78206e6f := by
  rfl

theorem fib_insn_539 :
  arm64_read_insn fib_code 4294970412 = 0x362d3638 := by
  rfl

theorem fib_insn_540 :
  arm64_read_insn fib_code 4294970416 = 0x6c702034 := by
  rfl

theorem fib_insn_541 :
  arm64_read_insn fib_code 4294970420 = 0x77207375 := by
  rfl

theorem fib_insn_542 :
  arm64_read_insn fib_code 4294970424 = 0x65746168 := by
  rfl

theorem fib_insn_543 :
  arm64_read_insn fib_code 4294970428 = 0x20726576 := by
  rfl

theorem fib_insn_544 :
  arm64_read_insn fib_code 4294970432 = 0x20656874 := by
  rfl

theorem fib_insn_545 :
  arm64_read_insn fib_code 4294970436 = 0x636e7566 := by
  rfl

theorem fib_insn_546 :
  arm64_read_insn fib_code 4294970440 = 0x6e6f6974 := by
  rfl

theorem fib_insn_547 :
  arm64_read_insn fib_code 4294970444 = 0x69707320 := by
  rfl

theorem fib_insn_548 :
  arm64_read_insn fib_code 4294970448 = 0x2c736c6c := by
  rfl

theorem fib_insn_549 :
  arm64_read_insn fib_code 4294970452 = 0x206f7320 := by
  rfl

theorem fib_insn_550 :
  arm64_read_insn fib_code 4294970456 = 0x20656874 := by
  rfl

theorem fib_insn_551 :
  arm64_read_insn fib_code 4294970460 = 0x656d6173 := by
  rfl

theorem fib_insn_552 :
  arm64_read_insn fib_code 4294970464 = 0x63657220 := by
  rfl

theorem fib_insn_553 :
  arm64_read_insn fib_code 4294970468 = 0x69737275 := by
  rfl

theorem fib_insn_554 :
  arm64_read_insn fib_code 4294970472 = 0x69206e6f := by
  rfl

theorem fib_insn_555 :
  arm64_read_insn fib_code 4294970476 = 0x65722073 := by
  rfl

theorem fib_insn_556 :
  arm64_read_insn fib_code 4294970480 = 0x65737566 := by
  rfl

theorem fib_insn_557 :
  arm64_read_insn fib_code 4294970484 = 0x74612064 := by
  rfl

theorem fib_insn_558 :
  arm64_read_insn fib_code 4294970488 = 0x64206120 := by
  rfl

theorem fib_insn_559 :
  arm64_read_insn fib_code 4294970492 = 0x65666669 := by
  rfl

theorem fib_insn_560 :
  arm64_read_insn fib_code 4294970496 = 0x746e6572 := by
  rfl

theorem fib_insn_561 :
  arm64_read_insn fib_code 4294970500 = 0x70656420 := by
  rfl

theorem fib_insn_562 :
  arm64_read_insn fib_code 4294970504 = 0x6f206874 := by
  rfl

theorem fib_insn_563 :
  arm64_read_insn fib_code 4294970508 = 0x6165206e := by
  rfl

theorem fib_insn_564 :
  arm64_read_insn fib_code 4294970512 = 0x61206863 := by
  rfl

theorem fib_insn_565 :
  arm64_read_insn fib_code 4294970516 = 0x6120646e := by
  rfl

theorem fib_insn_566 :
  arm64_read_insn fib_code 4294970520 = 0x6e756620 := by
  rfl

theorem fib_insn_567 :
  arm64_read_insn fib_code 4294970524 = 0x6f697463 := by
  rfl

theorem fib_insn_568 :
  arm64_read_insn fib_code 4294970528 = 0x6977206e := by
  rfl

theorem fib_insn_569 :
  arm64_read_insn fib_code 4294970532 = 0x6d206874 := by
  rfl

theorem fib_insn_570 :
  arm64_read_insn fib_code 4294970536 = 0x20796e61 := by
  rfl

theorem fib_insn_571 :
  arm64_read_insn fib_code 4294970540 = 0x61636f6c := by
  rfl

theorem fib_insn_572 :
  arm64_read_insn fib_code 4294970544 = 0x6920736c := by
  rfl

theorem fib_insn_573 :
  arm64_read_insn fib_code 4294970548 = 0x65722073 := by
  rfl

theorem fib_insn_574 :
  arm64_read_insn fib_code 4294970552 = 0x65737566 := by
  rfl

theorem fib_insn_575 :
  arm64_read_insn fib_code 4294970556 = 0x6f732064 := by
  rfl

theorem fib_insn_576 :
  arm64_read_insn fib_code 4294970560 = 0x72656e6f := by
  rfl

theorem fib_insn_577 :
  arm64_read_insn fib_code 4294970564 = 0x6552202e := by
  rfl

theorem fib_insn_578 :
  arm64_read_insn fib_code 4294970568 = 0x74697277 := by
  rfl

theorem fib_insn_579 :
  arm64_read_insn fib_code 4294970572 = 0x68742065 := by
  rfl

theorem fib_insn_580 :
  arm64_read_insn fib_code 4294970576 = 0x65722065 := by
  rfl

theorem fib_insn_581 :
  arm64_read_insn fib_code 4294970580 = 0x73727563 := by
  rfl

theorem fib_insn_582 :
  arm64_read_insn fib_code 4294970584 = 0x206e6f69 := by
  rfl

theorem fib_insn_583 :
  arm64_read_insn fib_code 4294970588 = 0x61207361 := by
  rfl

theorem fib_insn_584 :
  arm64_read_insn fib_code 4294970592 = 0x6f6f6c20 := by
  rfl

theorem fib_insn_585 :
  arm64_read_insn fib_code 4294970596 = 0x6f202c70 := by
  rfl

theorem fib_insn_586 :
  arm64_read_insn fib_code 4294970600 = 0x70732072 := by
  rfl

theorem fib_insn_587 :
  arm64_read_insn fib_code 4294970604 = 0x2074696c := by
  rfl

theorem fib_insn_588 :
  arm64_read_insn fib_code 4294970608 = 0x73207469 := by
  rfl

theorem fib_insn_589 :
  arm64_read_insn fib_code 4294970612 = 0x6874206f := by
  rfl

theorem fib_insn_590 :
  arm64_read_insn fib_code 4294970616 = 0x6e207461 := by
  rfl

theorem fib_insn_591 :
  arm64_read_insn fib_code 4294970620 = 0x6863206f := by
  rfl

theorem fib_insn_592 :
  arm64_read_insn fib_code 4294970624 = 0x206e6961 := by
  rfl

theorem fib_insn_593 :
  arm64_read_insn fib_code 4294970628 = 0x6320666f := by
  rfl

theorem fib_insn_594 :
  arm64_read_insn fib_code 4294970632 = 0x736c6c61 := by
  rfl

theorem fib_insn_595 :
  arm64_read_insn fib_code 4294970636 = 0x20736920 := by
  rfl

theorem fib_insn_596 :
  arm64_read_insn fib_code 4294970640 = 0x73696874 := by
  rfl

theorem fib_insn_597 :
  arm64_read_insn fib_code 4294970644 = 0x65656420 := by
  rfl

theorem fib_insn_598 :
  arm64_read_insn fib_code 4294970648 = 0x000a2e70 := by
  rfl

theorem fib_insn_599 :
  arm64_read_insn fib_code 4294970652 = 0x006e616e := by
  rfl

theorem fib_insn_600 :
  arm64_read_insn fib_code 4294970656 = 0x666e692d := by
  rfl

theorem fib_insn_601 :
  arm64_read_insn fib_code 4294970660 = 0x666e6900 := by
  rfl

theorem fib_insn_602 :
  arm64_read_insn fib_code 4294970664 = 0x2e302d00 := by
  rfl

theorem fib_insn_603 :
  arm64_read_insn fib_code 4294970668 = 0x2e300030 := by
  rfl

theorem fib_insn_604 :
  arm64_read_insn fib_code 4294970672 = 0x2e250030 := by
  rfl

/-- Per-instruction step lemmas (scaffolding for the end-to-end proof). -/
theorem fib_sr_0 (s : Arm64State) (h : s.pc = 4294968256) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 29 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 30 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968256 = (2847898621 : UInt32) := by native_decide
  have hw : ((2847898621 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968256 (2847898621 : UInt32) h hinsn hw

theorem fib_sr_1 (s : Arm64State) (h : s.pc = 4294968260) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968260 = (2415927312 : UInt32) := by native_decide
  have hw : ((2415927312 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968260 (2415927312 : UInt32) h hinsn hw)

theorem fib_sr_2 (s : Arm64State) (h : s.pc = 4294968264) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 16)) := by
  have hinsn : arm64_read_insn fib_code 4294968264 = (2432713232 : UInt32) := by native_decide
  have hw : ((2432713232 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968264 (2432713232 : UInt32) h hinsn hw

theorem fib_sr_3 (s : Arm64State) (h : s.pc = 4294968268) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (mem_read_u64 s.mem (arm64_reg 16 s + UInt64.ofNat 0).toNat)) := by
  have hinsn : arm64_read_insn fib_code 4294968268 = (4181721616 : UInt32) := by native_decide
  have hw : ((4181721616 : UInt32) &&& 0xffe00000) = 0xf9400000 := by native_decide
  exact work_step_ldr_uoff s fib_code 4294968268 (4181721616 : UInt32) h hinsn hw

theorem fib_sr_4 (s : Arm64State) (h : s.pc = 4294968272) :
  arm64_step s fib_code = (if arm64_reg 16 s ≠ 0 then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 116).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968272 = (3036677040 : UInt32) := by native_decide
  have h0 : ¬ ((3036677040 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3036677040 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3036677040 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3036677040 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3036677040 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3036677040 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ((3036677040 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3036677040 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3036677040 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3036677040 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3036677040 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3036677040 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3036677040 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3036677040 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3036677040 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3036677040 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3036677040 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3036677040 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3036677040 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3036677040 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3036677040 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3036677040 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3036677040 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3036677040 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3036677040 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3036677040 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3036677040 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3036677040 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3036677040 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3036677040 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3036677040 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3036677040 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((3036677040 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  by_cases hp : s.x16 = 0
  all_goals simp [hp, arm64_reg, arm64_set_reg]

theorem fib_sr_5 (s : Arm64State) (h : s.pc = 4294968276) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 3)) := by
  have hinsn : arm64_read_insn fib_code 4294968276 = (3531604064 : UInt32) := by native_decide
  have hw : ((3531604064 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((3531604064 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inr (by native_decide)
  exact work_step_movz s fib_code 4294968276 (3531604064 : UInt32) h hinsn hw

theorem fib_sr_6 (s : Arm64State) (h : s.pc = 4294968280) :
  arm64_step s fib_code = some (arm64_set_reg 1 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968280 = (2415927297 : UInt32) := by native_decide
  have hw : ((2415927297 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968280 (2415927297 : UInt32) h hinsn hw)

theorem fib_sr_7 (s : Arm64State) (h : s.pc = 4294968284) :
  arm64_step s fib_code = some (arm64_set_reg 1 s (arm64_reg 1 s + UInt64.ofNat 24)) := by
  have hinsn : arm64_read_insn fib_code 4294968284 = (2432720929 : UInt32) := by native_decide
  have hw : ((2432720929 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968284 (2432720929 : UInt32) h hinsn hw

theorem fib_sr_8 (s : Arm64State) (h : s.pc = 4294968288) :
  arm64_step s fib_code = some { s with x30 := UInt64.ofNat (s.pc + 4), pc := (UInt64.ofNat s.pc + (UInt64.ofNat 598) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968288 = (2483028566 : UInt32) := by native_decide
  have h0 : ¬ ((2483028566 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2483028566 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2483028566 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2483028566 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ((2483028566 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2483028566 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2483028566 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2483028566 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2483028566 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2483028566 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2483028566 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2483028566 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2483028566 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((2483028566 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2483028566 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2483028566 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2483028566 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2483028566 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2483028566 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2483028566 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2483028566 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2483028566 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2483028566 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((2483028566 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((2483028566 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((2483028566 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((2483028566 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((2483028566 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((2483028566 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((2483028566 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((2483028566 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((2483028566 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : ((2483028566 : UInt32) &&& (67108863 : UInt32) &&& (33554432 : UInt32)) = (0 : UInt32) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_9 (s : Arm64State) (h : s.pc = 4294968292) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968292 = (2415927312 : UInt32) := by native_decide
  have hw : ((2415927312 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968292 (2415927312 : UInt32) h hinsn hw)

theorem fib_sr_10 (s : Arm64State) (h : s.pc = 4294968296) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 24)) := by
  have hinsn : arm64_read_insn fib_code 4294968296 = (2432721424 : UInt32) := by native_decide
  have hw : ((2432721424 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968296 (2432721424 : UInt32) h hinsn hw

theorem fib_sr_11 (s : Arm64State) (h : s.pc = 4294968300) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (mem_read_u64 s.mem (arm64_reg 16 s + UInt64.ofNat 0).toNat)) := by
  have hinsn : arm64_read_insn fib_code 4294968300 = (4181721616 : UInt32) := by native_decide
  have hw : ((4181721616 : UInt32) &&& 0xffe00000) = 0xf9400000 := by native_decide
  exact work_step_ldr_uoff s fib_code 4294968300 (4181721616 : UInt32) h hinsn hw

theorem fib_sr_12 (s : Arm64State) (h : s.pc = 4294968304) :
  arm64_step s fib_code = some (arm64_set_reg 17 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968304 = (2415927313 : UInt32) := by native_decide
  have hw : ((2415927313 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968304 (2415927313 : UInt32) h hinsn hw)

theorem fib_sr_13 (s : Arm64State) (h : s.pc = 4294968308) :
  arm64_step s fib_code = some (arm64_set_reg 17 s (arm64_reg 17 s + UInt64.ofNat 16)) := by
  have hinsn : arm64_read_insn fib_code 4294968308 = (2432713265 : UInt32) := by native_decide
  have hw : ((2432713265 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968308 (2432713265 : UInt32) h hinsn hw

theorem fib_sr_14 (s : Arm64State) (h : s.pc = 4294968312) :
  arm64_step s fib_code = some { s with mem := mem_write_u64 s.mem (arm64_reg 17 s + UInt64.ofNat 0).toNat (arm64_reg 16 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968312 = (4177527344 : UInt32) := by native_decide
  have hw : ((4177527344 : UInt32) &&& 0xffe00000) = 0xf9000000 := by native_decide
  exact work_step_str_uoff s fib_code 4294968312 (4177527344 : UInt32) h hinsn hw

theorem fib_sr_15 (s : Arm64State) (h : s.pc = 4294968316) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (arm64_reg 16 s - UInt64.ofNat 393216)) := by
  have hinsn : arm64_read_insn fib_code 4294968316 = (3510731279 : UInt32) := by native_decide
  have hw : ((3510731279 : UInt32) &&& 0xff800000) = 0xd1000000 := by native_decide
  exact work_step_sub_imm64 s fib_code 4294968316 (3510731279 : UInt32) h hinsn hw

theorem fib_sr_16 (s : Arm64State) (h : s.pc = 4294968320) :
  arm64_step s fib_code = some (arm64_set_reg 14 s (UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968320 = (1384120334 : UInt32) := by native_decide
  have hw : ((1384120334 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120334 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968320 (1384120334 : UInt32) h hinsn hw

theorem fib_sr_17 (s : Arm64State) (h : s.pc = 4294968324) :
  arm64_step s fib_code = some (arm64_set_reg 14 s (movk_insert (arm64_reg 14 s) (UInt64.ofNat 4) (UInt64.ofNat 16))) := by
  have hinsn : arm64_read_insn fib_code 4294968324 = (4070572174 : UInt32) := by native_decide
  have hw : ((4070572174 : UInt32) &&& 0xff800000) = 0xf2800000 ∨ ((4070572174 : UInt32) &&& 0xff800000) = 0x72800000 := Or.inl (by native_decide)
  exact work_step_movk s fib_code 4294968324 (4070572174 : UInt32) h hinsn hw

theorem fib_sr_18 (s : Arm64State) (h : s.pc = 4294968328) :
  arm64_step s fib_code = some { (arm64_set_reg 31 s (arm64_reg 15 s - arm64_reg 14 s)) with nzcv := arm64_subs_flags (arm64_reg 15 s) (arm64_reg 14 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968328 = (3943563775 : UInt32) := by native_decide
  have hw : ((3943563775 : UInt32) &&& 0xffe00000) = 0xeb000000 := by native_decide
  exact work_step_cmp_reg s fib_code 4294968328 (3943563775 : UInt32) h hinsn hw

theorem fib_sr_19 (s : Arm64State) (h : s.pc = 4294968332) :
  arm64_step s fib_code = (if arm64_matches_condition 2 s.nzcv = true then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 12).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968332 = (1409286242 : UInt32) := by native_decide
  have h0 : ¬ ((1409286242 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1409286242 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1409286242 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1409286242 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1409286242 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1409286242 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1409286242 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1409286242 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1409286242 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1409286242 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1409286242 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1409286242 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1409286242 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((1409286242 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1409286242 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1409286242 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1409286242 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1409286242 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1409286242 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1409286242 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1409286242 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1409286242 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ((1409286242 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((1409286242 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((1409286242 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((1409286242 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((1409286242 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((1409286242 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((1409286242 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((1409286242 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((1409286242 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((1409286242 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1409286242 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  all_goals (by_cases hp : arm64_matches_condition 2 s.nzcv = true <;> simp [hp])

theorem fib_sr_20 (s : Arm64State) (h : s.pc = 4294968336) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968336 = (1384120335 : UInt32) := by native_decide
  have hw : ((1384120335 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120335 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968336 (1384120335 : UInt32) h hinsn hw

theorem fib_sr_21 (s : Arm64State) (h : s.pc = 4294968340) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (movk_insert (arm64_reg 15 s) (UInt64.ofNat 4) (UInt64.ofNat 16))) := by
  have hinsn : arm64_read_insn fib_code 4294968340 = (4070572175 : UInt32) := by native_decide
  have hw : ((4070572175 : UInt32) &&& 0xff800000) = 0xf2800000 ∨ ((4070572175 : UInt32) &&& 0xff800000) = 0x72800000 := Or.inl (by native_decide)
  exact work_step_movk s fib_code 4294968340 (4070572175 : UInt32) h hinsn hw

theorem fib_sr_22 (s : Arm64State) (h : s.pc = 4294968344) :
  arm64_step s fib_code = some (arm64_set_reg 14 s (UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968344 = (1384120334 : UInt32) := by native_decide
  have hw : ((1384120334 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120334 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968344 (1384120334 : UInt32) h hinsn hw

theorem fib_sr_23 (s : Arm64State) (h : s.pc = 4294968348) :
  arm64_step s fib_code = some (arm64_set_reg 14 s (movk_insert (arm64_reg 14 s) (UInt64.ofNat 120) (UInt64.ofNat 16))) := by
  have hinsn : arm64_read_insn fib_code 4294968348 = (4070575886 : UInt32) := by native_decide
  have hw : ((4070575886 : UInt32) &&& 0xff800000) = 0xf2800000 ∨ ((4070575886 : UInt32) &&& 0xff800000) = 0x72800000 := Or.inl (by native_decide)
  exact work_step_movk s fib_code 4294968348 (4070575886 : UInt32) h hinsn hw

theorem fib_sr_24 (s : Arm64State) (h : s.pc = 4294968352) :
  arm64_step s fib_code = some { (arm64_set_reg 31 s (arm64_reg 15 s - arm64_reg 14 s)) with nzcv := arm64_subs_flags (arm64_reg 15 s) (arm64_reg 14 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968352 = (3943563775 : UInt32) := by native_decide
  have hw : ((3943563775 : UInt32) &&& 0xffe00000) = 0xeb000000 := by native_decide
  exact work_step_cmp_reg s fib_code 4294968352 (3943563775 : UInt32) h hinsn hw

theorem fib_sr_25 (s : Arm64State) (h : s.pc = 4294968356) :
  arm64_step s fib_code = (if arm64_matches_condition 3 s.nzcv = true then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 12).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968356 = (1409286243 : UInt32) := by native_decide
  have h0 : ¬ ((1409286243 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1409286243 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1409286243 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1409286243 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1409286243 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1409286243 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1409286243 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1409286243 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1409286243 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1409286243 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1409286243 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1409286243 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1409286243 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((1409286243 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1409286243 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1409286243 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1409286243 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1409286243 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1409286243 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1409286243 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1409286243 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1409286243 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ((1409286243 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((1409286243 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((1409286243 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((1409286243 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((1409286243 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((1409286243 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((1409286243 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((1409286243 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((1409286243 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((1409286243 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1409286243 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  all_goals (by_cases hp : arm64_matches_condition 3 s.nzcv = true <;> simp [hp])

theorem fib_sr_26 (s : Arm64State) (h : s.pc = 4294968360) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968360 = (1384120335 : UInt32) := by native_decide
  have hw : ((1384120335 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120335 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968360 (1384120335 : UInt32) h hinsn hw

theorem fib_sr_27 (s : Arm64State) (h : s.pc = 4294968364) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (movk_insert (arm64_reg 15 s) (UInt64.ofNat 120) (UInt64.ofNat 16))) := by
  have hinsn : arm64_read_insn fib_code 4294968364 = (4070575887 : UInt32) := by native_decide
  have hw : ((4070575887 : UInt32) &&& 0xff800000) = 0xf2800000 ∨ ((4070575887 : UInt32) &&& 0xff800000) = 0x72800000 := Or.inl (by native_decide)
  exact work_step_movk s fib_code 4294968364 (4070575887 : UInt32) h hinsn hw

theorem fib_sr_28 (s : Arm64State) (h : s.pc = 4294968368) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (s.sp + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968368 = (2432697328 : UInt32) := by native_decide
  have hw : ((2432697328 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968368 (2432697328 : UInt32) h hinsn hw

theorem fib_sr_29 (s : Arm64State) (h : s.pc = 4294968372) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s - (arm64_reg 15 s <<< UInt64.ofNat 0))) := by
  have hinsn : arm64_read_insn fib_code 4294968372 = (3406758416 : UInt32) := by native_decide
  have hw : ((3406758416 : UInt32) &&& 0xffe00000) = 0xcb000000 := by native_decide
  exact work_step_sub_reg s fib_code 4294968372 (3406758416 : UInt32) h hinsn hw

theorem fib_sr_30 (s : Arm64State) (h : s.pc = 4294968376) :
  arm64_step s fib_code = some (arm64_set_reg 17 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968376 = (2415927313 : UInt32) := by native_decide
  have hw : ((2415927313 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968376 (2415927313 : UInt32) h hinsn hw)

theorem fib_sr_31 (s : Arm64State) (h : s.pc = 4294968380) :
  arm64_step s fib_code = some (arm64_set_reg 17 s (arm64_reg 17 s + UInt64.ofNat 8)) := by
  have hinsn : arm64_read_insn fib_code 4294968380 = (2432705073 : UInt32) := by native_decide
  have hw : ((2432705073 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968380 (2432705073 : UInt32) h hinsn hw

theorem fib_sr_32 (s : Arm64State) (h : s.pc = 4294968384) :
  arm64_step s fib_code = some { s with mem := mem_write_u64 s.mem (arm64_reg 17 s + UInt64.ofNat 0).toNat (arm64_reg 16 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968384 = (4177527344 : UInt32) := by native_decide
  have hw : ((4177527344 : UInt32) &&& 0xffe00000) = 0xf9000000 := by native_decide
  exact work_step_str_uoff s fib_code 4294968384 (4177527344 : UInt32) h hinsn hw

theorem fib_sr_33 (s : Arm64State) (h : s.pc = 4294968388) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 10)) := by
  have hinsn : arm64_read_insn fib_code 4294968388 = (1384120640 : UInt32) := by native_decide
  have hw : ((1384120640 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120640 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968388 (1384120640 : UInt32) h hinsn hw

theorem fib_sr_34 (s : Arm64State) (h : s.pc = 4294968392) :
  arm64_step s fib_code = some { s with x30 := UInt64.ofNat (s.pc + 4), pc := (UInt64.ofNat s.pc + (UInt64.ofNat 3) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968392 = (2483027971 : UInt32) := by native_decide
  have h0 : ¬ ((2483027971 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2483027971 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2483027971 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2483027971 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ((2483027971 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2483027971 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2483027971 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2483027971 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2483027971 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2483027971 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2483027971 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2483027971 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2483027971 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((2483027971 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2483027971 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2483027971 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2483027971 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2483027971 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2483027971 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2483027971 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2483027971 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2483027971 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2483027971 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((2483027971 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((2483027971 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((2483027971 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((2483027971 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((2483027971 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((2483027971 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((2483027971 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((2483027971 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((2483027971 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : ((2483027971 : UInt32) &&& (67108863 : UInt32) &&& (33554432 : UInt32)) = (0 : UInt32) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_35 (s : Arm64State) (h : s.pc = 4294968396) :
  arm64_step s fib_code = some { (arm64_set_reg 30 (arm64_set_reg 29 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968396 = (2831252477 : UInt32) := by native_decide
  have hw : ((2831252477 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968396 (2831252477 : UInt32) h hinsn hw

theorem fib_sr_36 (s : Arm64State) (h : s.pc = 4294968400) :
  arm64_step s fib_code = some { s with pc := s.x30.toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968400 = (3596551104 : UInt32) := by native_decide
  have hw : (3596551104 : UInt32) = (0xd65f03c0 : UInt32) := by native_decide
  exact work_step_ret s fib_code 4294968400 (3596551104 : UInt32) h hinsn hw

theorem fib_sr_37 (s : Arm64State) (h : s.pc = 4294968404) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 29 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 30 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968404 = (2847898621 : UInt32) := by native_decide
  have hw : ((2847898621 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968404 (2847898621 : UInt32) h hinsn hw

theorem fib_sr_38 (s : Arm64State) (h : s.pc = 4294968408) :
  arm64_step s fib_code = some (arm64_set_reg 29 s (s.sp + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968408 = (2432697341 : UInt32) := by native_decide
  have hw : ((2432697341 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968408 (2432697341 : UInt32) h hinsn hw

theorem fib_sr_39 (s : Arm64State) (h : s.pc = 4294968412) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 19 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 20 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968412 = (2847888371 : UInt32) := by native_decide
  have hw : ((2847888371 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968412 (2847888371 : UInt32) h hinsn hw

theorem fib_sr_40 (s : Arm64State) (h : s.pc = 4294968416) :
  arm64_step s fib_code = some (arm64_set_reg 19 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968416 = (2432696339 : UInt32) := by native_decide
  have hw : ((2432696339 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968416 (2432696339 : UInt32) h hinsn hw

theorem fib_sr_41 (s : Arm64State) (h : s.pc = 4294968420) :
  arm64_step s fib_code = some (arm64_set_reg 17 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968420 = (2415927313 : UInt32) := by native_decide
  have hw : ((2415927313 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968420 (2415927313 : UInt32) h hinsn hw)

theorem fib_sr_42 (s : Arm64State) (h : s.pc = 4294968424) :
  arm64_step s fib_code = some (arm64_set_reg 17 s (arm64_reg 17 s + UInt64.ofNat 8)) := by
  have hinsn : arm64_read_insn fib_code 4294968424 = (2432705073 : UInt32) := by native_decide
  have hw : ((2432705073 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968424 (2432705073 : UInt32) h hinsn hw

theorem fib_sr_43 (s : Arm64State) (h : s.pc = 4294968428) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (mem_read_u64 s.mem (arm64_reg 17 s + UInt64.ofNat 0).toNat)) := by
  have hinsn : arm64_read_insn fib_code 4294968428 = (4181721648 : UInt32) := by native_decide
  have hw : ((4181721648 : UInt32) &&& 0xffe00000) = 0xf9400000 := by native_decide
  exact work_step_ldr_uoff s fib_code 4294968428 (4181721648 : UInt32) h hinsn hw

theorem fib_sr_44 (s : Arm64State) (h : s.pc = 4294968432) :
  arm64_step s fib_code = some (arm64_set_reg 17 s (s.sp + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968432 = (2432697329 : UInt32) := by native_decide
  have hw : ((2432697329 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968432 (2432697329 : UInt32) h hinsn hw

theorem fib_sr_45 (s : Arm64State) (h : s.pc = 4294968436) :
  arm64_step s fib_code = some { (arm64_set_reg 31 s (arm64_reg 17 s - arm64_reg 16 s)) with nzcv := arm64_subs_flags (arm64_reg 17 s) (arm64_reg 16 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968436 = (3943694911 : UInt32) := by native_decide
  have hw : ((3943694911 : UInt32) &&& 0xffe00000) = 0xeb000000 := by native_decide
  exact work_step_cmp_reg s fib_code 4294968436 (3943694911 : UInt32) h hinsn hw

theorem fib_sr_46 (s : Arm64State) (h : s.pc = 4294968440) :
  arm64_step s fib_code = (if arm64_matches_condition 2 s.nzcv = true then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 48).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968440 = (1409286530 : UInt32) := by native_decide
  have h0 : ¬ ((1409286530 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1409286530 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1409286530 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1409286530 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1409286530 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1409286530 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1409286530 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1409286530 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1409286530 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1409286530 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1409286530 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1409286530 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1409286530 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((1409286530 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1409286530 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1409286530 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1409286530 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1409286530 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1409286530 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1409286530 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1409286530 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1409286530 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ((1409286530 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((1409286530 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((1409286530 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((1409286530 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((1409286530 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((1409286530 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((1409286530 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((1409286530 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((1409286530 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((1409286530 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1409286530 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  all_goals (by_cases hp : arm64_matches_condition 2 s.nzcv = true <;> simp [hp])

theorem fib_sr_47 (s : Arm64State) (h : s.pc = 4294968444) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16) } := by
  have hinsn : arm64_read_insn fib_code 4294968444 = (3506455551 : UInt32) := by native_decide
  have hw : ((3506455551 : UInt32) &&& 0xff800000) = 0xd1000000 := by native_decide
  exact work_step_sub_imm64 s fib_code 4294968444 (3506455551 : UInt32) h hinsn hw

theorem fib_sr_48 (s : Arm64State) (h : s.pc = 4294968448) :
  arm64_step s fib_code = some (arm64_set_reg 1 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968448 = (2415919105 : UInt32) := by native_decide
  have hw : ((2415919105 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968448 (2415919105 : UInt32) h hinsn hw)

theorem fib_sr_49 (s : Arm64State) (h : s.pc = 4294968452) :
  arm64_step s fib_code = some (arm64_set_reg 1 s (arm64_reg 1 s + UInt64.ofNat 2516)) := by
  have hinsn : arm64_read_insn fib_code 4294968452 = (2435272737 : UInt32) := by native_decide
  have hw : ((2435272737 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968452 (2435272737 : UInt32) h hinsn hw

theorem fib_sr_50 (s : Arm64State) (h : s.pc = 4294968456) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 2)) := by
  have hinsn : arm64_read_insn fib_code 4294968456 = (3531604032 : UInt32) := by native_decide
  have hw : ((3531604032 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((3531604032 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inr (by native_decide)
  exact work_step_movz s fib_code 4294968456 (3531604032 : UInt32) h hinsn hw

theorem fib_sr_51 (s : Arm64State) (h : s.pc = 4294968460) :
  arm64_step s fib_code = some (arm64_set_reg 2 s (UInt64.ofNat 837)) := by
  have hinsn : arm64_read_insn fib_code 4294968460 = (3531630754 : UInt32) := by native_decide
  have hw : ((3531630754 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((3531630754 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inr (by native_decide)
  exact work_step_movz s fib_code 4294968460 (3531630754 : UInt32) h hinsn hw

theorem fib_sr_52 (s : Arm64State) (h : s.pc = 4294968464) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (UInt64.ofNat 4)) := by
  have hinsn : arm64_read_insn fib_code 4294968464 = (3531604112 : UInt32) := by native_decide
  have hw : ((3531604112 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((3531604112 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inr (by native_decide)
  exact work_step_movz s fib_code 4294968464 (3531604112 : UInt32) h hinsn hw

theorem fib_sr_53 (s : Arm64State) (h : s.pc = 4294968468) :
  arm64_step s fib_code = some s := by
  have hinsn : arm64_read_insn fib_code 4294968468 = (3556773889 : UInt32) := by native_decide
  have hw : ((3556773889 : UInt32) &&& 0xffe0001f) = 0xd4000001 := by native_decide
  exact work_step_svc s fib_code 4294968468 (3556773889 : UInt32) h hinsn hw

theorem fib_sr_54 (s : Arm64State) (h : s.pc = 4294968472) :
  arm64_step s fib_code = some { s with sp := (s.sp + UInt64.ofNat 16) } := by
  have hinsn : arm64_read_insn fib_code 4294968472 = (2432713727 : UInt32) := by native_decide
  have hw : ((2432713727 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968472 (2432713727 : UInt32) h hinsn hw

theorem fib_sr_55 (s : Arm64State) (h : s.pc = 4294968476) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 2)) := by
  have hinsn : arm64_read_insn fib_code 4294968476 = (3531604032 : UInt32) := by native_decide
  have hw : ((3531604032 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((3531604032 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inr (by native_decide)
  exact work_step_movz s fib_code 4294968476 (3531604032 : UInt32) h hinsn hw

theorem fib_sr_56 (s : Arm64State) (h : s.pc = 4294968480) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (UInt64.ofNat 1)) := by
  have hinsn : arm64_read_insn fib_code 4294968480 = (3531604016 : UInt32) := by native_decide
  have hw : ((3531604016 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((3531604016 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inr (by native_decide)
  exact work_step_movz s fib_code 4294968480 (3531604016 : UInt32) h hinsn hw

theorem fib_sr_57 (s : Arm64State) (h : s.pc = 4294968484) :
  arm64_step s fib_code = some s := by
  have hinsn : arm64_read_insn fib_code 4294968484 = (3556773889 : UInt32) := by native_decide
  have hw : ((3556773889 : UInt32) &&& 0xffe0001f) = 0xd4000001 := by native_decide
  exact work_step_svc s fib_code 4294968484 (3556773889 : UInt32) h hinsn hw

theorem fib_sr_58 (s : Arm64State) (h : s.pc = 4294968488) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 131072) } := by
  have hinsn : arm64_read_insn fib_code 4294968488 = (3510666239 : UInt32) := by native_decide
  have hw : ((3510666239 : UInt32) &&& 0xff800000) = 0xd1000000 := by native_decide
  exact work_step_sub_imm64 s fib_code 4294968488 (3510666239 : UInt32) h hinsn hw

theorem fib_sr_59 (s : Arm64State) (h : s.pc = 4294968492) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 19 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968492 = (2432696928 : UInt32) := by native_decide
  have hw : ((2432696928 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968492 (2432696928 : UInt32) h hinsn hw

theorem fib_sr_60 (s : Arm64State) (h : s.pc = 4294968496) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968496 = (2847869920 : UInt32) := by native_decide
  have hw : ((2847869920 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968496 (2847869920 : UInt32) h hinsn hw

theorem fib_sr_61 (s : Arm64State) (h : s.pc = 4294968500) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 1)) := by
  have hinsn : arm64_read_insn fib_code 4294968500 = (1384120352 : UInt32) := by native_decide
  have hw : ((1384120352 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120352 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968500 (1384120352 : UInt32) h hinsn hw

theorem fib_sr_62 (s : Arm64State) (h : s.pc = 4294968504) :
  arm64_step s fib_code = some (arm64_set_reg 1 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968504 = (2432696321 : UInt32) := by native_decide
  have hw : ((2432696321 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968504 (2432696321 : UInt32) h hinsn hw

theorem fib_sr_63 (s : Arm64State) (h : s.pc = 4294968508) :
  arm64_step s fib_code = some { (arm64_set_reg 2 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968508 = (2831223776 : UInt32) := by native_decide
  have hw : ((2831223776 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968508 (2831223776 : UInt32) h hinsn hw

theorem fib_sr_64 (s : Arm64State) (h : s.pc = 4294968512) :
  arm64_step s fib_code = some { (arm64_set_reg 31 s (arm64_reg 0 s - arm64_reg 1 s)) with nzcv := arm64_subs_flags (arm64_reg 0 s) (arm64_reg 1 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968512 = (3942711327 : UInt32) := by native_decide
  have hw : ((3942711327 : UInt32) &&& 0xffe00000) = 0xeb000000 := by native_decide
  exact work_step_cmp_reg s fib_code 4294968512 (3942711327 : UInt32) h hinsn hw

theorem fib_sr_65 (s : Arm64State) (h : s.pc = 4294968516) :
  arm64_step s fib_code = (if arm64_matches_condition 12 s.nzcv = true then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 28).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968516 = (1409286380 : UInt32) := by native_decide
  have h0 : ¬ ((1409286380 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1409286380 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1409286380 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1409286380 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1409286380 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1409286380 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1409286380 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1409286380 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1409286380 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1409286380 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1409286380 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1409286380 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1409286380 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((1409286380 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1409286380 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1409286380 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1409286380 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1409286380 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1409286380 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1409286380 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1409286380 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1409286380 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ((1409286380 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((1409286380 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((1409286380 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((1409286380 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((1409286380 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((1409286380 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((1409286380 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((1409286380 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((1409286380 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((1409286380 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1409286380 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  all_goals (by_cases hp : arm64_matches_condition 12 s.nzcv = true <;> simp [hp])

theorem fib_sr_66 (s : Arm64State) (h : s.pc = 4294968520) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 19 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968520 = (2432696928 : UInt32) := by native_decide
  have hw : ((2432696928 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968520 (2432696928 : UInt32) h hinsn hw

theorem fib_sr_67 (s : Arm64State) (h : s.pc = 4294968524) :
  arm64_step s fib_code = some { s with sp := (s.sp + UInt64.ofNat 131072) } := by
  have hinsn : arm64_read_insn fib_code 4294968524 = (2436924415 : UInt32) := by native_decide
  have hw : ((2436924415 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968524 (2436924415 : UInt32) h hinsn hw

theorem fib_sr_68 (s : Arm64State) (h : s.pc = 4294968528) :
  arm64_step s fib_code = some { (arm64_set_reg 20 (arm64_set_reg 19 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968528 = (2831242227 : UInt32) := by native_decide
  have hw : ((2831242227 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968528 (2831242227 : UInt32) h hinsn hw

theorem fib_sr_69 (s : Arm64State) (h : s.pc = 4294968532) :
  arm64_step s fib_code = some { (arm64_set_reg 30 (arm64_set_reg 29 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968532 = (2831252477 : UInt32) := by native_decide
  have hw : ((2831252477 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968532 (2831252477 : UInt32) h hinsn hw

theorem fib_sr_70 (s : Arm64State) (h : s.pc = 4294968536) :
  arm64_step s fib_code = some { s with pc := s.x30.toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968536 = (3596551104 : UInt32) := by native_decide
  have hw : (3596551104 : UInt32) = (0xd65f03c0 : UInt32) := by native_decide
  exact work_step_ret s fib_code 4294968536 (3596551104 : UInt32) h hinsn hw

theorem fib_sr_71 (s : Arm64State) (h : s.pc = 4294968540) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((27 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (27 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (27 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968540 = (335544347 : UInt32) := by native_decide
  have h0 : ¬ ((335544347 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544347 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544347 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544347 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544347 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544347 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544347 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544347 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544347 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544347 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544347 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544347 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544347 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544347 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((27 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_72 (s : Arm64State) (h : s.pc = 4294968544) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 19 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968544 = (2432696928 : UInt32) := by native_decide
  have hw : ((2432696928 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968544 (2432696928 : UInt32) h hinsn hw

theorem fib_sr_73 (s : Arm64State) (h : s.pc = 4294968548) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968548 = (2847869920 : UInt32) := by native_decide
  have hw : ((2847869920 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968548 (2847869920 : UInt32) h hinsn hw

theorem fib_sr_74 (s : Arm64State) (h : s.pc = 4294968552) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 1)) := by
  have hinsn : arm64_read_insn fib_code 4294968552 = (1384120352 : UInt32) := by native_decide
  have hw : ((1384120352 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120352 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968552 (1384120352 : UInt32) h hinsn hw

theorem fib_sr_75 (s : Arm64State) (h : s.pc = 4294968556) :
  arm64_step s fib_code = some (arm64_set_reg 1 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968556 = (2432696321 : UInt32) := by native_decide
  have hw : ((2432696321 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968556 (2432696321 : UInt32) h hinsn hw

theorem fib_sr_76 (s : Arm64State) (h : s.pc = 4294968560) :
  arm64_step s fib_code = some { (arm64_set_reg 2 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968560 = (2831223776 : UInt32) := by native_decide
  have hw : ((2831223776 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968560 (2831223776 : UInt32) h hinsn hw

theorem fib_sr_77 (s : Arm64State) (h : s.pc = 4294968564) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 0 s - (arm64_reg 1 s <<< UInt64.ofNat 0))) := by
  have hinsn : arm64_read_insn fib_code 4294968564 = (3405840384 : UInt32) := by native_decide
  have hw : ((3405840384 : UInt32) &&& 0xffe00000) = 0xcb000000 := by native_decide
  exact work_step_sub_reg s fib_code 4294968564 (3405840384 : UInt32) h hinsn hw

theorem fib_sr_78 (s : Arm64State) (h : s.pc = 4294968568) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 31 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968568 = (2847899616 : UInt32) := by native_decide
  have hw : ((2847899616 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968568 (2847899616 : UInt32) h hinsn hw

theorem fib_sr_79 (s : Arm64State) (h : s.pc = 4294968572) :
  arm64_step s fib_code = some { (arm64_set_reg 31 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968572 = (2831253472 : UInt32) := by native_decide
  have hw : ((2831253472 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968572 (2831253472 : UInt32) h hinsn hw

theorem fib_sr_80 (s : Arm64State) (h : s.pc = 4294968576) :
  arm64_step s fib_code = some { s with x30 := UInt64.ofNat (s.pc + 4), pc := (UInt64.ofNat s.pc + ((UInt64.ofNat 67108821) - (UInt64.ofNat (2^26))) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968576 = (2550136789 : UInt32) := by native_decide
  have h0 : ¬ ((2550136789 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2550136789 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2550136789 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2550136789 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ((2550136789 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2550136789 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2550136789 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2550136789 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2550136789 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2550136789 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2550136789 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2550136789 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2550136789 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((2550136789 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2550136789 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2550136789 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2550136789 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2550136789 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2550136789 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2550136789 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2550136789 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2550136789 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2550136789 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((2550136789 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((2550136789 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((2550136789 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((2550136789 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((2550136789 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((2550136789 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((2550136789 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((2550136789 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((2550136789 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : ¬ (((2550136789 : UInt32) &&& (67108863 : UInt32) &&& (33554432 : UInt32)) = (0 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_81 (s : Arm64State) (h : s.pc = 4294968580) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968580 = (2847869920 : UInt32) := by native_decide
  have hw : ((2847869920 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968580 (2847869920 : UInt32) h hinsn hw

theorem fib_sr_82 (s : Arm64State) (h : s.pc = 4294968584) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 19 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968584 = (2432696928 : UInt32) := by native_decide
  have hw : ((2432696928 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968584 (2432696928 : UInt32) h hinsn hw

theorem fib_sr_83 (s : Arm64State) (h : s.pc = 4294968588) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968588 = (2847869920 : UInt32) := by native_decide
  have hw : ((2847869920 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968588 (2847869920 : UInt32) h hinsn hw

theorem fib_sr_84 (s : Arm64State) (h : s.pc = 4294968592) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (UInt64.ofNat 2)) := by
  have hinsn : arm64_read_insn fib_code 4294968592 = (1384120384 : UInt32) := by native_decide
  have hw : ((1384120384 : UInt32) &&& 0xffe00000) = 0x52800000 ∨ ((1384120384 : UInt32) &&& 0xffe00000) = 0xd2800000 := Or.inl (by native_decide)
  exact work_step_movz s fib_code 4294968592 (1384120384 : UInt32) h hinsn hw

theorem fib_sr_85 (s : Arm64State) (h : s.pc = 4294968596) :
  arm64_step s fib_code = some (arm64_set_reg 1 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968596 = (2432696321 : UInt32) := by native_decide
  have hw : ((2432696321 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968596 (2432696321 : UInt32) h hinsn hw

theorem fib_sr_86 (s : Arm64State) (h : s.pc = 4294968600) :
  arm64_step s fib_code = some { (arm64_set_reg 2 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968600 = (2831223776 : UInt32) := by native_decide
  have hw : ((2831223776 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968600 (2831223776 : UInt32) h hinsn hw

theorem fib_sr_87 (s : Arm64State) (h : s.pc = 4294968604) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 0 s - (arm64_reg 1 s <<< UInt64.ofNat 0))) := by
  have hinsn : arm64_read_insn fib_code 4294968604 = (3405840384 : UInt32) := by native_decide
  have hw : ((3405840384 : UInt32) &&& 0xffe00000) = 0xcb000000 := by native_decide
  exact work_step_sub_reg s fib_code 4294968604 (3405840384 : UInt32) h hinsn hw

theorem fib_sr_88 (s : Arm64State) (h : s.pc = 4294968608) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 16).toNat (arm64_reg 0 s)) ((s.sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 31 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968608 = (2847899616 : UInt32) := by native_decide
  have hw : ((2847899616 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968608 (2847899616 : UInt32) h hinsn hw

theorem fib_sr_89 (s : Arm64State) (h : s.pc = 4294968612) :
  arm64_step s fib_code = some { (arm64_set_reg 31 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968612 = (2831253472 : UInt32) := by native_decide
  have hw : ((2831253472 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968612 (2831253472 : UInt32) h hinsn hw

theorem fib_sr_90 (s : Arm64State) (h : s.pc = 4294968616) :
  arm64_step s fib_code = some { s with x30 := UInt64.ofNat (s.pc + 4), pc := (UInt64.ofNat s.pc + ((UInt64.ofNat 67108811) - (UInt64.ofNat (2^26))) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968616 = (2550136779 : UInt32) := by native_decide
  have h0 : ¬ ((2550136779 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((2550136779 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((2550136779 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((2550136779 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ((2550136779 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((2550136779 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((2550136779 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((2550136779 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((2550136779 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((2550136779 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((2550136779 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((2550136779 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((2550136779 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((2550136779 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((2550136779 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((2550136779 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((2550136779 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((2550136779 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((2550136779 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((2550136779 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((2550136779 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((2550136779 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((2550136779 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((2550136779 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((2550136779 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((2550136779 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((2550136779 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((2550136779 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((2550136779 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((2550136779 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((2550136779 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((2550136779 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : ¬ (((2550136779 : UInt32) &&& (67108863 : UInt32) &&& (33554432 : UInt32)) = (0 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_91 (s : Arm64State) (h : s.pc = 4294968620) :
  arm64_step s fib_code = some (arm64_set_reg 1 s (arm64_reg 0 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968620 = (2432696321 : UInt32) := by native_decide
  have hw : ((2432696321 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968620 (2432696321 : UInt32) h hinsn hw

theorem fib_sr_92 (s : Arm64State) (h : s.pc = 4294968624) :
  arm64_step s fib_code = some { (arm64_set_reg 2 (arm64_set_reg 0 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968624 = (2831223776 : UInt32) := by native_decide
  have hw : ((2831223776 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968624 (2831223776 : UInt32) h hinsn hw

theorem fib_sr_93 (s : Arm64State) (h : s.pc = 4294968628) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (arm64_reg 0 s + (arm64_reg 1 s <<< UInt64.ofNat 0))) := by
  have hinsn : arm64_read_insn fib_code 4294968628 = (2332098560 : UInt32) := by native_decide
  have hw : ((2332098560 : UInt32) &&& 0xffe00000) = 0x8b000000 := by native_decide
  exact work_step_add_reg s fib_code 4294968628 (2332098560 : UInt32) h hinsn hw

theorem fib_sr_94 (s : Arm64State) (h : s.pc = 4294968632) :
  arm64_step s fib_code = some { s with sp := (s.sp + UInt64.ofNat 131072) } := by
  have hinsn : arm64_read_insn fib_code 4294968632 = (2436924415 : UInt32) := by native_decide
  have hw : ((2436924415 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968632 (2436924415 : UInt32) h hinsn hw

theorem fib_sr_95 (s : Arm64State) (h : s.pc = 4294968636) :
  arm64_step s fib_code = some { (arm64_set_reg 20 (arm64_set_reg 19 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968636 = (2831242227 : UInt32) := by native_decide
  have hw : ((2831242227 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968636 (2831242227 : UInt32) h hinsn hw

theorem fib_sr_96 (s : Arm64State) (h : s.pc = 4294968640) :
  arm64_step s fib_code = some { (arm64_set_reg 30 (arm64_set_reg 29 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 16 } := by
  have hinsn : arm64_read_insn fib_code 4294968640 = (2831252477 : UInt32) := by native_decide
  have hw : ((2831252477 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968640 (2831252477 : UInt32) h hinsn hw

theorem fib_sr_97 (s : Arm64State) (h : s.pc = 4294968644) :
  arm64_step s fib_code = some { s with pc := s.x30.toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968644 = (3596551104 : UInt32) := by native_decide
  have hw : (3596551104 : UInt32) = (0xd65f03c0 : UInt32) := by native_decide
  exact work_step_ret s fib_code 4294968644 (3596551104 : UInt32) h hinsn hw

theorem fib_sr_98 (s : Arm64State) (h : s.pc = 4294968648) :
  arm64_step s fib_code = some { s with sp := (s.sp - UInt64.ofNat 112), mem := mem_write_u64 (mem_write_u64 s.mem (s.sp - UInt64.ofNat 112).toNat (arm64_reg 29 s)) ((s.sp - UInt64.ofNat 112) + 8).toNat (arm64_reg 30 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968648 = (2847505405 : UInt32) := by native_decide
  have hw : ((2847505405 : UInt32) &&& 0xffc00000) = 0xa9800000 := by native_decide
  exact work_step_stp s fib_code 4294968648 (2847505405 : UInt32) h hinsn hw

theorem fib_sr_99 (s : Arm64State) (h : s.pc = 4294968652) :
  arm64_step s fib_code = some { s with mem := mem_write_u64 s.mem (s.sp + UInt64.ofNat 88).toNat (arm64_reg 0 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968652 = (4177539040 : UInt32) := by native_decide
  have hw : ((4177539040 : UInt32) &&& 0xffe00000) = 0xf9000000 := by native_decide
  exact work_step_str_uoff s fib_code 4294968652 (4177539040 : UInt32) h hinsn hw

theorem fib_sr_100 (s : Arm64State) (h : s.pc = 4294968656) :
  arm64_step s fib_code = some { s with mem := mem_write_u64 s.mem (s.sp + UInt64.ofNat 80).toNat (arm64_reg 1 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968656 = (4177538017 : UInt32) := by native_decide
  have hw : ((4177538017 : UInt32) &&& 0xffe00000) = 0xf9000000 := by native_decide
  exact work_step_str_uoff s fib_code 4294968656 (4177538017 : UInt32) h hinsn hw

theorem fib_sr_101 (s : Arm64State) (h : s.pc = 4294968660) :
  arm64_step s fib_code = some (arm64_set_reg 12 s (arm64_reg 0 s >>> UInt64.ofNat 63)) := by
  have hinsn : arm64_read_insn fib_code 4294968660 = (3548380172 : UInt32) := by native_decide
  have h0 : ¬ ((3548380172 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3548380172 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3548380172 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3548380172 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3548380172 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3548380172 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3548380172 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3548380172 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3548380172 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3548380172 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3548380172 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3548380172 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3548380172 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3548380172 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3548380172 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3548380172 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3548380172 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3548380172 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3548380172 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ((3548380172 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3548380172 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h51 : ¬ ((3548380172 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3548380172 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3548380172 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3548380172 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3548380172 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3548380172 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3548380172 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3548380172 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3548380172 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3548380172 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_102 (s : Arm64State) (h : s.pc = 4294968664) :
  arm64_step s fib_code = some (arm64_set_reg 13 s (arm64_reg 12 s <<< UInt64.ofNat 63)) := by
  have hinsn : arm64_read_insn fib_code 4294968664 = (3544252813 : UInt32) := by native_decide
  have h0 : ¬ ((3544252813 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3544252813 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3544252813 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3544252813 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3544252813 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3544252813 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3544252813 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3544252813 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3544252813 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3544252813 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3544252813 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3544252813 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3544252813 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3544252813 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3544252813 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3544252813 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3544252813 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3544252813 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3544252813 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3544252813 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3544252813 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ((3544252813 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3544252813 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3544252813 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3544252813 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3544252813 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3544252813 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3544252813 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3544252813 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3544252813 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3544252813 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3544252813 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_103 (s : Arm64State) (h : s.pc = 4294968668) :
  arm64_step s fib_code = some (arm64_set_reg 11 s (arm64_reg 0 s - (arm64_reg 13 s <<< UInt64.ofNat 0))) := by
  have hinsn : arm64_read_insn fib_code 4294968668 = (3406626827 : UInt32) := by native_decide
  have hw : ((3406626827 : UInt32) &&& 0xffe00000) = 0xcb000000 := by native_decide
  exact work_step_sub_reg s fib_code 4294968668 (3406626827 : UInt32) h hinsn hw

theorem fib_sr_104 (s : Arm64State) (h : s.pc = 4294968672) :
  arm64_step s fib_code = some { s with mem := mem_write_u64 s.mem (s.sp + UInt64.ofNat 72).toNat (arm64_reg 11 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968672 = (4177537003 : UInt32) := by native_decide
  have hw : ((4177537003 : UInt32) &&& 0xffe00000) = 0xf9000000 := by native_decide
  exact work_step_str_uoff s fib_code 4294968672 (4177537003 : UInt32) h hinsn hw

theorem fib_sr_105 (s : Arm64State) (h : s.pc = 4294968676) :
  arm64_step s fib_code = some { s with mem := mem_write_u64 s.mem (s.sp + UInt64.ofNat 96).toNat (arm64_reg 12 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968676 = (4177540076 : UInt32) := by native_decide
  have hw : ((4177540076 : UInt32) &&& 0xffe00000) = 0xf9000000 := by native_decide
  exact work_step_str_uoff s fib_code 4294968676 (4177540076 : UInt32) h hinsn hw

theorem fib_sr_106 (s : Arm64State) (h : s.pc = 4294968680) :
  arm64_step s fib_code = some (arm64_set_reg 14 s (arm64_reg 11 s >>> UInt64.ofNat 52)) := by
  have hinsn : arm64_read_insn fib_code 4294968680 = (3547659630 : UInt32) := by native_decide
  have h0 : ¬ ((3547659630 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3547659630 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3547659630 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3547659630 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3547659630 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3547659630 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3547659630 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3547659630 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3547659630 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3547659630 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3547659630 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3547659630 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3547659630 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3547659630 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3547659630 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3547659630 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3547659630 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3547659630 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3547659630 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ((3547659630 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3547659630 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h51 : ¬ ((3547659630 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3547659630 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3547659630 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3547659630 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3547659630 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3547659630 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3547659630 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3547659630 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3547659630 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3547659630 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_107 (s : Arm64State) (h : s.pc = 4294968684) :
  arm64_step s fib_code = some { s with nzcv := arm64_subs_flags (arm64_reg 14 s) (UInt64.ofNat 2047) } := by
  have hinsn : arm64_read_insn fib_code 4294968684 = (4045405663 : UInt32) := by native_decide
  have hw : ((4045405663 : UInt32) &&& 0xff800000) = 0xf1000000 := by native_decide
  exact work_step_cmp_imm s fib_code 4294968684 (4045405663 : UInt32) h hinsn hw

theorem fib_sr_108 (s : Arm64State) (h : s.pc = 4294968688) :
  arm64_step s fib_code = (if arm64_matches_condition 3 s.nzcv = true then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 28).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968688 = (1409286371 : UInt32) := by native_decide
  have h0 : ¬ ((1409286371 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1409286371 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1409286371 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1409286371 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1409286371 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1409286371 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1409286371 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1409286371 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1409286371 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1409286371 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1409286371 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1409286371 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1409286371 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((1409286371 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1409286371 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1409286371 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1409286371 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1409286371 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1409286371 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1409286371 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1409286371 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1409286371 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ((1409286371 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((1409286371 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((1409286371 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((1409286371 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((1409286371 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((1409286371 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((1409286371 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((1409286371 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((1409286371 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((1409286371 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1409286371 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  all_goals (by_cases hp : arm64_matches_condition 3 s.nzcv = true <;> simp [hp])

theorem fib_sr_109 (s : Arm64State) (h : s.pc = 4294968692) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (arm64_reg 14 s <<< UInt64.ofNat 52)) := by
  have hinsn : arm64_read_insn fib_code 4294968692 = (3544985039 : UInt32) := by native_decide
  have h0 : ¬ ((3544985039 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3544985039 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3544985039 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3544985039 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3544985039 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((3544985039 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3544985039 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3544985039 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3544985039 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3544985039 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3544985039 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3544985039 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3544985039 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3544985039 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3544985039 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3544985039 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3544985039 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3544985039 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3544985039 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3544985039 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3544985039 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ((3544985039 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3544985039 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3544985039 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3544985039 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3544985039 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3544985039 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3544985039 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3544985039 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3544985039 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3544985039 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3544985039 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_110 (s : Arm64State) (h : s.pc = 4294968696) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (arm64_reg 11 s - (arm64_reg 15 s <<< UInt64.ofNat 0))) := by
  have hinsn : arm64_read_insn fib_code 4294968696 = (3406758255 : UInt32) := by native_decide
  have hw : ((3406758255 : UInt32) &&& 0xffe00000) = 0xcb000000 := by native_decide
  exact work_step_sub_reg s fib_code 4294968696 (3406758255 : UInt32) h hinsn hw

theorem fib_sr_111 (s : Arm64State) (h : s.pc = 4294968700) :
  arm64_step s fib_code = (if arm64_reg 15 s = 0 then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 28).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968700 = (3019899119 : UInt32) := by native_decide
  have h0 : ¬ ((3019899119 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3019899119 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3019899119 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3019899119 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3019899119 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ((3019899119 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3019899119 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3019899119 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3019899119 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3019899119 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3019899119 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3019899119 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3019899119 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3019899119 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3019899119 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3019899119 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3019899119 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3019899119 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3019899119 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3019899119 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3019899119 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3019899119 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3019899119 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3019899119 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3019899119 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3019899119 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3019899119 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3019899119 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3019899119 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3019899119 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3019899119 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3019899119 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((3019899119 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  by_cases hp : s.x15 = 0
  all_goals simp [hp, arm64_reg, arm64_set_reg]

theorem fib_sr_112 (s : Arm64State) (h : s.pc = 4294968704) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968704 = (2415919120 : UInt32) := by native_decide
  have hw : ((2415919120 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968704 (2415919120 : UInt32) h hinsn hw)

theorem fib_sr_113 (s : Arm64State) (h : s.pc = 4294968708) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 3356)) := by
  have hinsn : arm64_read_insn fib_code 4294968708 = (2436133392 : UInt32) := by native_decide
  have hw : ((2436133392 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968708 (2436133392 : UInt32) h hinsn hw

theorem fib_sr_114 (s : Arm64State) (h : s.pc = 4294968712) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((18 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (18 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (18 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968712 = (335544338 : UInt32) := by native_decide
  have h0 : ¬ ((335544338 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544338 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544338 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544338 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544338 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544338 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544338 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544338 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544338 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544338 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544338 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544338 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544338 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544338 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544338 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544338 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544338 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544338 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544338 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544338 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544338 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544338 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544338 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544338 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544338 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544338 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544338 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544338 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544338 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544338 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544338 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544338 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((18 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_115 (s : Arm64State) (h : s.pc = 4294968716) :
  arm64_step s fib_code = some { s with nzcv := arm64_subs_flags (arm64_reg 11 s) (UInt64.ofNat 0) } := by
  have hinsn : arm64_read_insn fib_code 4294968716 = (4043309439 : UInt32) := by native_decide
  have hw : ((4043309439 : UInt32) &&& 0xff800000) = 0xf1000000 := by native_decide
  exact work_step_cmp_imm s fib_code 4294968716 (4043309439 : UInt32) h hinsn hw

theorem fib_sr_116 (s : Arm64State) (h : s.pc = 4294968720) :
  arm64_step s fib_code = (if arm64_matches_condition 0 s.nzcv = true then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 36).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968720 = (1409286432 : UInt32) := by native_decide
  have h0 : ¬ ((1409286432 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((1409286432 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((1409286432 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((1409286432 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((1409286432 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((1409286432 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((1409286432 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((1409286432 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((1409286432 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((1409286432 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((1409286432 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((1409286432 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((1409286432 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((1409286432 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((1409286432 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((1409286432 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((1409286432 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((1409286432 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((1409286432 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((1409286432 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((1409286432 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((1409286432 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ((1409286432 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((1409286432 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((1409286432 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((1409286432 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((1409286432 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((1409286432 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((1409286432 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((1409286432 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((1409286432 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((1409286432 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1409286432 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  all_goals (by_cases hp : arm64_matches_condition 0 s.nzcv = true <;> simp [hp])

theorem fib_sr_117 (s : Arm64State) (h : s.pc = 4294968724) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((27 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (27 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (27 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968724 = (335544347 : UInt32) := by native_decide
  have h0 : ¬ ((335544347 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544347 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544347 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544347 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544347 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544347 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544347 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544347 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544347 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544347 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544347 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544347 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544347 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544347 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544347 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544347 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544347 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544347 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544347 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544347 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544347 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((27 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_118 (s : Arm64State) (h : s.pc = 4294968728) :
  arm64_step s fib_code = (if arm64_reg 12 s = 0 then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 16).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968728 = (3019899020 : UInt32) := by native_decide
  have h0 : ¬ ((3019899020 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3019899020 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3019899020 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3019899020 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3019899020 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3019899020 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3019899020 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3019899020 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3019899020 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3019899020 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3019899020 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3019899020 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3019899020 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3019899020 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((3019899020 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  by_cases hp : s.x12 = 0
  all_goals simp [hp, arm64_reg, arm64_set_reg]

theorem fib_sr_119 (s : Arm64State) (h : s.pc = 4294968732) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968732 = (2415919120 : UInt32) := by native_decide
  have hw : ((2415919120 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968732 (2415919120 : UInt32) h hinsn hw)

theorem fib_sr_120 (s : Arm64State) (h : s.pc = 4294968736) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 3360)) := by
  have hinsn : arm64_read_insn fib_code 4294968736 = (2436137488 : UInt32) := by native_decide
  have hw : ((2436137488 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968736 (2436137488 : UInt32) h hinsn hw

theorem fib_sr_121 (s : Arm64State) (h : s.pc = 4294968740) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((11 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (11 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (11 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968740 = (335544331 : UInt32) := by native_decide
  have h0 : ¬ ((335544331 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544331 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544331 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544331 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544331 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544331 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544331 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544331 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544331 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544331 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544331 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544331 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544331 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544331 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544331 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544331 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544331 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544331 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544331 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544331 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544331 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544331 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544331 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544331 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544331 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544331 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544331 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544331 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544331 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544331 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544331 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544331 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((11 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_122 (s : Arm64State) (h : s.pc = 4294968744) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968744 = (2415919120 : UInt32) := by native_decide
  have hw : ((2415919120 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968744 (2415919120 : UInt32) h hinsn hw)

theorem fib_sr_123 (s : Arm64State) (h : s.pc = 4294968748) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 3365)) := by
  have hinsn : arm64_read_insn fib_code 4294968748 = (2436142608 : UInt32) := by native_decide
  have hw : ((2436142608 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968748 (2436142608 : UInt32) h hinsn hw

theorem fib_sr_124 (s : Arm64State) (h : s.pc = 4294968752) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((8 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (8 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (8 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968752 = (335544328 : UInt32) := by native_decide
  have h0 : ¬ ((335544328 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544328 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544328 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544328 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544328 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544328 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544328 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544328 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544328 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544328 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544328 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544328 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544328 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544328 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544328 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544328 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544328 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544328 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544328 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544328 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544328 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544328 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544328 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544328 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544328 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544328 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544328 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544328 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544328 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544328 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544328 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544328 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((8 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_125 (s : Arm64State) (h : s.pc = 4294968756) :
  arm64_step s fib_code = (if arm64_reg 12 s = 0 then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 16).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968756 = (3019899020 : UInt32) := by native_decide
  have h0 : ¬ ((3019899020 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3019899020 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3019899020 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3019899020 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3019899020 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3019899020 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3019899020 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3019899020 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3019899020 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3019899020 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3019899020 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3019899020 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3019899020 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3019899020 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3019899020 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3019899020 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3019899020 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3019899020 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3019899020 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3019899020 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3019899020 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((3019899020 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  by_cases hp : s.x12 = 0
  all_goals simp [hp, arm64_reg, arm64_set_reg]

theorem fib_sr_126 (s : Arm64State) (h : s.pc = 4294968760) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968760 = (2415919120 : UInt32) := by native_decide
  have hw : ((2415919120 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968760 (2415919120 : UInt32) h hinsn hw)

theorem fib_sr_127 (s : Arm64State) (h : s.pc = 4294968764) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 3369)) := by
  have hinsn : arm64_read_insn fib_code 4294968764 = (2436146704 : UInt32) := by native_decide
  have hw : ((2436146704 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968764 (2436146704 : UInt32) h hinsn hw

theorem fib_sr_128 (s : Arm64State) (h : s.pc = 4294968768) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((4 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (4 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (4 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968768 = (335544324 : UInt32) := by native_decide
  have h0 : ¬ ((335544324 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544324 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544324 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544324 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544324 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544324 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544324 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544324 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544324 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544324 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544324 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544324 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544324 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544324 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544324 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544324 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544324 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544324 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544324 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544324 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544324 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544324 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544324 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544324 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544324 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544324 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544324 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544324 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544324 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544324 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544324 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544324 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((4 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_129 (s : Arm64State) (h : s.pc = 4294968772) :
  arm64_step s fib_code = some (arm64_set_reg 16 s ((UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096)) := by
  have hinsn : arm64_read_insn fib_code 4294968772 = (2415919120 : UInt32) := by native_decide
  have hw : ((2415919120 : UInt32) &&& 0x9f000000) = 0x90000000 := by native_decide
  simpa [h] using (work_step_adrp s fib_code 4294968772 (2415919120 : UInt32) h hinsn hw)

theorem fib_sr_130 (s : Arm64State) (h : s.pc = 4294968776) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 3374)) := by
  have hinsn : arm64_read_insn fib_code 4294968776 = (2436151824 : UInt32) := by native_decide
  have hw : ((2436151824 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968776 (2436151824 : UInt32) h hinsn hw

theorem fib_sr_131 (s : Arm64State) (h : s.pc = 4294968780) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((1 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (1 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (1 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968780 = (335544321 : UInt32) := by native_decide
  have h0 : ¬ ((335544321 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((335544321 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((335544321 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((335544321 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((335544321 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((335544321 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((335544321 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((335544321 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((335544321 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((335544321 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((335544321 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((335544321 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((335544321 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((335544321 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((335544321 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((335544321 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((335544321 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((335544321 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((335544321 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((335544321 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((335544321 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((335544321 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((335544321 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((335544321 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((335544321 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((335544321 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((335544321 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((335544321 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((335544321 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((335544321 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((335544321 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((335544321 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((1 : UInt32) &&& (33554432 : UInt32))) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_132 (s : Arm64State) (h : s.pc = 4294968784) :
  arm64_step s fib_code = some (arm64_set_reg 9 s (mem_read_u64 s.mem (s.sp + UInt64.ofNat 80).toNat)) := by
  have hinsn : arm64_read_insn fib_code 4294968784 = (4181732329 : UInt32) := by native_decide
  have hw : ((4181732329 : UInt32) &&& 0xffe00000) = 0xf9400000 := by native_decide
  exact work_step_ldr_uoff s fib_code 4294968784 (4181732329 : UInt32) h hinsn hw

theorem fib_sr_133 (s : Arm64State) (h : s.pc = 4294968788) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (arm64_reg 9 s + UInt64.ofNat 0)) := by
  have hinsn : arm64_read_insn fib_code 4294968788 = (2432696623 : UInt32) := by native_decide
  have hw : ((2432696623 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968788 (2432696623 : UInt32) h hinsn hw

theorem fib_sr_134 (s : Arm64State) (h : s.pc = 4294968792) :
  arm64_step s fib_code = some (arm64_set_reg 8 s (mem_read_u64 s.mem (arm64_reg 16 s + UInt64.ofNat 0).toNat)) := by
  have hinsn : arm64_read_insn fib_code 4294968792 = (4181721608 : UInt32) := by native_decide
  have hw : ((4181721608 : UInt32) &&& 0xffe00000) = 0xf9400000 := by native_decide
  exact work_step_ldr_uoff s fib_code 4294968792 (4181721608 : UInt32) h hinsn hw

theorem fib_sr_135 (s : Arm64State) (h : s.pc = 4294968796) :
  arm64_step s fib_code = some (arm64_set_reg 8 s (t32u (t8s (arm64_reg 8 s)))) := by
  have hinsn : arm64_read_insn fib_code 4294968796 = (318774536 : UInt32) := by native_decide
  have h0 : ¬ ((318774536 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((318774536 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((318774536 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((318774536 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((318774536 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((318774536 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((318774536 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((318774536 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((318774536 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((318774536 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((318774536 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((318774536 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((318774536 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((318774536 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((318774536 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ((318774536 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((318774536 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((318774536 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((318774536 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((318774536 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((318774536 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((318774536 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((318774536 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((318774536 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((318774536 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((318774536 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((318774536 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((318774536 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((318774536 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((318774536 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((318774536 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((318774536 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((318774536 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, t32u, t8s, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]

theorem fib_sr_136 (s : Arm64State) (h : s.pc = 4294968800) :
  arm64_step s fib_code = some { s with mem := mem_write_u8 s.mem (arm64_reg 15 s + UInt64.ofNat 0).toNat (arm64_reg 8 s) } := by
  have hinsn : arm64_read_insn fib_code 4294968800 = (956301800 : UInt32) := by native_decide
  have hw : ((956301800 : UInt32) &&& 0xffd00000) = 0x39000000 := by native_decide
  exact work_step_strb s fib_code 4294968800 (956301800 : UInt32) h hinsn hw

theorem fib_sr_137 (s : Arm64State) (h : s.pc = 4294968804) :
  arm64_step s fib_code = (if arm64_reg 8 s = 0 then ({ s with pc := (UInt64.ofNat s.pc + UInt64.ofNat 16).toNat } : Arm64State) else ({ s with pc := s.pc + 4 } : Arm64State)) := by
  have hinsn : arm64_read_insn fib_code 4294968804 = (3019899016 : UInt32) := by native_decide
  have h0 : ¬ ((3019899016 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((3019899016 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((3019899016 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ¬ ((3019899016 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((3019899016 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ((3019899016 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((3019899016 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((3019899016 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((3019899016 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((3019899016 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((3019899016 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((3019899016 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((3019899016 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((3019899016 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((3019899016 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((3019899016 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((3019899016 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((3019899016 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((3019899016 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((3019899016 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((3019899016 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((3019899016 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((3019899016 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((3019899016 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((3019899016 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((3019899016 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((3019899016 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((3019899016 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((3019899016 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((3019899016 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((3019899016 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((3019899016 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : (((3019899016 : UInt32) >>> 5 &&& 524287 &&& 262144)) = 0 := by native_decide
  unfold arm64_step
  simp [h, hinsn, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb]
  by_cases hp : s.x8 = 0
  all_goals simp [hp, arm64_reg, arm64_set_reg]

theorem fib_sr_138 (s : Arm64State) (h : s.pc = 4294968808) :
  arm64_step s fib_code = some (arm64_set_reg 15 s (arm64_reg 15 s + UInt64.ofNat 1)) := by
  have hinsn : arm64_read_insn fib_code 4294968808 = (2432697839 : UInt32) := by native_decide
  have hw : ((2432697839 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968808 (2432697839 : UInt32) h hinsn hw

theorem fib_sr_139 (s : Arm64State) (h : s.pc = 4294968812) :
  arm64_step s fib_code = some (arm64_set_reg 16 s (arm64_reg 16 s + UInt64.ofNat 1)) := by
  have hinsn : arm64_read_insn fib_code 4294968812 = (2432697872 : UInt32) := by native_decide
  have hw : ((2432697872 : UInt32) &&& 0xff800000) = 0x91000000 := by native_decide
  exact work_step_add_imm64 s fib_code 4294968812 (2432697872 : UInt32) h hinsn hw

theorem fib_sr_140 (s : Arm64State) (h : s.pc = 4294968816) :
  arm64_step s fib_code = some { s with pc := (UInt64.ofNat s.pc + (if ((67108858 : UInt32) &&& 0x02000000) ≠ 0 then (UInt64.ofNat (67108858 : UInt32).toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat (67108858 : UInt32).toNat) * 4).toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968816 = (402653178 : UInt32) := by native_decide
  have h0 : ¬ ((402653178 : UInt32) = (3596551104 : UInt32)) := by native_decide
  have h1 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (704707072 : UInt32)) := by native_decide
  have h2 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (2332033024 : UInt32)) := by native_decide
  have h3 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (3405774848 : UInt32)) := by native_decide
  have h4 : ¬ ((402653178 : UInt32) &&& (4292901888 : UInt32) = (2600500224 : UInt32)) := by native_decide
  have h5 : ¬ ((402653178 : UInt32) &&& (4294966303 : UInt32) = (3405775840 : UInt32)) := by native_decide
  have h6 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (3942645760 : UInt32)) := by native_decide
  have h7 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (2315255808 : UInt32)) := by native_decide
  have h8 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (3388997632 : UInt32)) := by native_decide
  have h9 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (285212672 : UInt32)) := by native_decide
  have h10 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (2432696320 : UInt32)) := by native_decide
  have h11 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (1358954496 : UInt32)) := by native_decide
  have h12 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (3506438144 : UInt32)) := by native_decide
  have h13 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (4043309056 : UInt32)) := by native_decide
  have h14 : ((402653178 : UInt32) &&& (4227858432 : UInt32) = (335544320 : UInt32)) := by native_decide
  have h15 : ¬ ((402653178 : UInt32) &&& (4227858432 : UInt32) = (2483027968 : UInt32)) := by native_decide
  have h16 : ¬ ((402653178 : UInt32) &&& (4278190080 : UInt32) = (3019898880 : UInt32)) := by native_decide
  have h17 : ¬ ((402653178 : UInt32) &&& (4278190080 : UInt32) = (3036676096 : UInt32)) := by native_decide
  have h18 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (4181721088 : UInt32)) := by native_decide
  have h19 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (3103784960 : UInt32)) := by native_decide
  have h20 : ¬ ((402653178 : UInt32) &&& (2667577344 : UInt32) = (2415919104 : UInt32)) := by native_decide
  have h21 : ¬ ((402653178 : UInt32) &&& (4290772992 : UInt32) = (2843738112 : UInt32)) := by native_decide
  have h22 : ¬ ((402653178 : UInt32) &&& (4290772992 : UInt32) = (2831155200 : UInt32)) := by native_decide
  have h23 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (1384120320 : UInt32)) := by native_decide
  have h24 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (3531603968 : UInt32)) := by native_decide
  have h25 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (2852126720 : UInt32)) := by native_decide
  have h26 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (4068474880 : UInt32)) := by native_decide
  have h27 : ¬ ((402653178 : UInt32) &&& (4286578688 : UInt32) = (1920991232 : UInt32)) := by native_decide
  have h28 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (310378496 : UInt32)) := by native_decide
  have h29 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (2457862144 : UInt32)) := by native_decide
  have h30 : ¬ ((402653178 : UInt32) &&& (4294905824 : UInt32) = (2594113504 : UInt32)) := by native_decide
  have h31 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (4177526784 : UInt32)) := by native_decide
  have h32 : ¬ ((402653178 : UInt32) &&& (4290772992 : UInt32) = (2839543808 : UInt32)) := by native_decide
  have h33 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2854223872 : UInt32)) := by native_decide
  have h34 : ¬ ((402653178 : UInt32) &&& (4294966303 : UInt32) = (3592355840 : UInt32)) := by native_decide
  have h35 : ¬ ((402653178 : UInt32) &&& (4292870175 : UInt32) = (3556769793 : UInt32)) := by native_decide
  have h36 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (318774272 : UInt32)) := by native_decide
  have h37 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (318782464 : UInt32)) := by native_decide
  have h38 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2470476800 : UInt32)) := by native_decide
  have h39 : ¬ ((402653178 : UInt32) &&& (4290837504 : UInt32) = (2453675008 : UInt32)) := by native_decide
  have h40 : ¬ ((402653178 : UInt32) &&& (4290837504 : UInt32) = (2453683200 : UInt32)) := by native_decide
  have h41 : ¬ ((402653178 : UInt32) &&& (4290837504 : UInt32) = (2453699584 : UInt32)) := by native_decide
  have h42 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2596276224 : UInt32)) := by native_decide
  have h43 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2596277248 : UInt32)) := by native_decide
  have h44 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2596282368 : UInt32)) := by native_decide
  have h45 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2596283392 : UInt32)) := by native_decide
  have h46 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (2596284416 : UInt32)) := by native_decide
  have h47 : ¬ ((402653178 : UInt32) &&& (4292902912 : UInt32) = (2600501248 : UInt32)) := by native_decide
  have h48 : ¬ ((402653178 : UInt32) &&& (4290837504 : UInt32) = (3544251392 : UInt32)) := by native_decide
  have h49 : ¬ ((402653178 : UInt32) &&& (4290837504 : UInt32) = (2470509568 : UInt32)) := by native_decide
  have h50 : ¬ ((402653178 : UInt32) &&& (4290772992 : UInt32) = (3544186880 : UInt32)) := by native_decide
  have h51 : ¬ ((402653178 : UInt32) &&& (4278190080 : UInt32) = (1409286144 : UInt32)) := by native_decide
  have h52 : ¬ ((402653178 : UInt32) &&& (4278190080 : UInt32) = (905969664 : UInt32)) := by native_decide
  have h53 : ¬ ((402653178 : UInt32) &&& (4278190080 : UInt32) = (922746880 : UInt32)) := by native_decide
  have h54 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (960495616 : UInt32)) := by native_decide
  have h55 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (956301312 : UInt32)) := by native_decide
  have h56 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (2034237440 : UInt32)) := by native_decide
  have h57 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (2030043136 : UInt32)) := by native_decide
  have h58 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (964689920 : UInt32)) := by native_decide
  have h59 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (2038431744 : UInt32)) := by native_decide
  have h60 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (3112173568 : UInt32)) := by native_decide
  have h61 : ¬ ((402653178 : UInt32) &&& (4291821568 : UInt32) = (3107979264 : UInt32)) := by native_decide
  have h62 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (4167067648 : UInt32)) := by native_decide
  have h63 : ¬ ((402653178 : UInt32) &&& (4292934656 : UInt32) = (4162873344 : UInt32)) := by native_decide
  have h64 : ¬ ((402653178 : UInt32) &&& (4292873216 : UInt32) = (4164943872 : UInt32)) := by native_decide
  have h65 : ¬ ((402653178 : UInt32) &&& (4292873216 : UInt32) = (4160749568 : UInt32)) := by native_decide
  have h66 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (2868903936 : UInt32)) := by native_decide
  have h67 : ¬ ((402653178 : UInt32) &&& (4292870144 : UInt32) = (3925868544 : UInt32)) := by native_decide
  have h68 : ¬ ((402653178 : UInt32) &&& (4292901888 : UInt32) = (2604694528 : UInt32)) := by native_decide
  have h69 : ¬ ((402653178 : UInt32) &&& (4292873216 : UInt32) = (2592079872 : UInt32)) := by native_decide
  have hb : ¬ (((67108858 : UInt32) &&& (33554432 : UInt32)) = 0) := by native_decide
  unfold arm64_step
  simp [h, hinsn]
  all_goals simp [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, h20, h21, h22, h23, h24, h25, h26, h27, h28, h29, h30, h31, h32, h33, h34, h35, h36, h37, h38, h39, h40, h41, h42, h43, h44, h45, h46, h47, h48, h49, h50, h51, h52, h53, h54, h55, h56, h57, h58, h59, h60, h61, h62, h63, h64, h65, h66, h67, h68, h69, hb, arm64_reg, arm64_set_reg, mem_write_u64, mem_read_u64]
  all_goals native_decide

theorem fib_sr_141 (s : Arm64State) (h : s.pc = 4294968820) :
  arm64_step s fib_code = some (arm64_set_reg 0 s (mem_read_u64 s.mem (s.sp + UInt64.ofNat 80).toNat)) := by
  have hinsn : arm64_read_insn fib_code 4294968820 = (4181732320 : UInt32) := by native_decide
  have hw : ((4181732320 : UInt32) &&& 0xffe00000) = 0xf9400000 := by native_decide
  exact work_step_ldr_uoff s fib_code 4294968820 (4181732320 : UInt32) h hinsn hw

theorem fib_sr_142 (s : Arm64State) (h : s.pc = 4294968824) :
  arm64_step s fib_code = some { (arm64_set_reg 30 (arm64_set_reg 29 s (mem_read_u64 s.mem s.sp.toNat)) (mem_read_u64 s.mem (s.sp + 8).toNat)) with sp := s.sp + UInt64.ofNat 112 } := by
  have hinsn : arm64_read_insn fib_code 4294968824 = (2831645693 : UInt32) := by native_decide
  have hw : ((2831645693 : UInt32) &&& 0xffc00000) = 0xa8c00000 := by native_decide
  exact work_step_ldp_post s fib_code 4294968824 (2831645693 : UInt32) h hinsn hw

theorem fib_sr_143 (s : Arm64State) (h : s.pc = 4294968828) :
  arm64_step s fib_code = some { s with pc := s.x30.toNat } := by
  have hinsn : arm64_read_insn fib_code 4294968828 = (3596551104 : UInt32) := by native_decide
  have hw : (3596551104 : UInt32) = (0xd65f03c0 : UInt32) := by native_decide
  exact work_step_ret s fib_code 4294968828 (3596551104 : UInt32) h hinsn hw

theorem fib_step_ok_0 (s : Arm64State) (h : s.pc = 4294968256) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_0 s h]
  simp

theorem fib_step_ok_1 (s : Arm64State) (h : s.pc = 4294968260) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_1 s h]
  simp

theorem fib_step_ok_2 (s : Arm64State) (h : s.pc = 4294968264) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_2 s h]
  simp

theorem fib_step_ok_3 (s : Arm64State) (h : s.pc = 4294968268) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_3 s h]
  simp

theorem fib_step_ok_4 (s : Arm64State) (h : s.pc = 4294968272) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_4 s h]
  simp

theorem fib_step_ok_5 (s : Arm64State) (h : s.pc = 4294968276) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_5 s h]
  simp

theorem fib_step_ok_6 (s : Arm64State) (h : s.pc = 4294968280) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_6 s h]
  simp

theorem fib_step_ok_7 (s : Arm64State) (h : s.pc = 4294968284) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_7 s h]
  simp

theorem fib_step_ok_8 (s : Arm64State) (h : s.pc = 4294968288) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_8 s h]
  simp

theorem fib_step_ok_9 (s : Arm64State) (h : s.pc = 4294968292) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_9 s h]
  simp

theorem fib_step_ok_10 (s : Arm64State) (h : s.pc = 4294968296) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_10 s h]
  simp

theorem fib_step_ok_11 (s : Arm64State) (h : s.pc = 4294968300) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_11 s h]
  simp

theorem fib_step_ok_12 (s : Arm64State) (h : s.pc = 4294968304) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_12 s h]
  simp

theorem fib_step_ok_13 (s : Arm64State) (h : s.pc = 4294968308) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_13 s h]
  simp

theorem fib_step_ok_14 (s : Arm64State) (h : s.pc = 4294968312) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_14 s h]
  simp

theorem fib_step_ok_15 (s : Arm64State) (h : s.pc = 4294968316) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_15 s h]
  simp

theorem fib_step_ok_16 (s : Arm64State) (h : s.pc = 4294968320) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_16 s h]
  simp

theorem fib_step_ok_17 (s : Arm64State) (h : s.pc = 4294968324) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_17 s h]
  simp

theorem fib_step_ok_18 (s : Arm64State) (h : s.pc = 4294968328) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_18 s h]
  simp

theorem fib_step_ok_19 (s : Arm64State) (h : s.pc = 4294968332) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_19 s h]
  simp

theorem fib_step_ok_20 (s : Arm64State) (h : s.pc = 4294968336) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_20 s h]
  simp

theorem fib_step_ok_21 (s : Arm64State) (h : s.pc = 4294968340) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_21 s h]
  simp

theorem fib_step_ok_22 (s : Arm64State) (h : s.pc = 4294968344) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_22 s h]
  simp

theorem fib_step_ok_23 (s : Arm64State) (h : s.pc = 4294968348) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_23 s h]
  simp

theorem fib_step_ok_24 (s : Arm64State) (h : s.pc = 4294968352) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_24 s h]
  simp

theorem fib_step_ok_25 (s : Arm64State) (h : s.pc = 4294968356) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_25 s h]
  simp

theorem fib_step_ok_26 (s : Arm64State) (h : s.pc = 4294968360) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_26 s h]
  simp

theorem fib_step_ok_27 (s : Arm64State) (h : s.pc = 4294968364) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_27 s h]
  simp

theorem fib_step_ok_28 (s : Arm64State) (h : s.pc = 4294968368) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_28 s h]
  simp

theorem fib_step_ok_29 (s : Arm64State) (h : s.pc = 4294968372) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_29 s h]
  simp

theorem fib_step_ok_30 (s : Arm64State) (h : s.pc = 4294968376) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_30 s h]
  simp

theorem fib_step_ok_31 (s : Arm64State) (h : s.pc = 4294968380) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_31 s h]
  simp

theorem fib_step_ok_32 (s : Arm64State) (h : s.pc = 4294968384) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_32 s h]
  simp

theorem fib_step_ok_33 (s : Arm64State) (h : s.pc = 4294968388) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_33 s h]
  simp

theorem fib_step_ok_34 (s : Arm64State) (h : s.pc = 4294968392) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_34 s h]
  simp

theorem fib_step_ok_35 (s : Arm64State) (h : s.pc = 4294968396) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_35 s h]
  simp

theorem fib_step_ok_36 (s : Arm64State) (h : s.pc = 4294968400) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_36 s h]
  simp

theorem fib_step_ok_37 (s : Arm64State) (h : s.pc = 4294968404) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_37 s h]
  simp

theorem fib_step_ok_38 (s : Arm64State) (h : s.pc = 4294968408) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_38 s h]
  simp

theorem fib_step_ok_39 (s : Arm64State) (h : s.pc = 4294968412) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_39 s h]
  simp

theorem fib_step_ok_40 (s : Arm64State) (h : s.pc = 4294968416) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_40 s h]
  simp

theorem fib_step_ok_41 (s : Arm64State) (h : s.pc = 4294968420) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_41 s h]
  simp

theorem fib_step_ok_42 (s : Arm64State) (h : s.pc = 4294968424) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_42 s h]
  simp

theorem fib_step_ok_43 (s : Arm64State) (h : s.pc = 4294968428) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_43 s h]
  simp

theorem fib_step_ok_44 (s : Arm64State) (h : s.pc = 4294968432) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_44 s h]
  simp

theorem fib_step_ok_45 (s : Arm64State) (h : s.pc = 4294968436) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_45 s h]
  simp

theorem fib_step_ok_46 (s : Arm64State) (h : s.pc = 4294968440) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_46 s h]
  simp

theorem fib_step_ok_47 (s : Arm64State) (h : s.pc = 4294968444) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_47 s h]
  simp

theorem fib_step_ok_48 (s : Arm64State) (h : s.pc = 4294968448) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_48 s h]
  simp

theorem fib_step_ok_49 (s : Arm64State) (h : s.pc = 4294968452) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_49 s h]
  simp

theorem fib_step_ok_50 (s : Arm64State) (h : s.pc = 4294968456) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_50 s h]
  simp

theorem fib_step_ok_51 (s : Arm64State) (h : s.pc = 4294968460) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_51 s h]
  simp

theorem fib_step_ok_52 (s : Arm64State) (h : s.pc = 4294968464) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_52 s h]
  simp

theorem fib_step_ok_53 (s : Arm64State) (h : s.pc = 4294968468) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_53 s h]
  simp

theorem fib_step_ok_54 (s : Arm64State) (h : s.pc = 4294968472) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_54 s h]
  simp

theorem fib_step_ok_55 (s : Arm64State) (h : s.pc = 4294968476) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_55 s h]
  simp

theorem fib_step_ok_56 (s : Arm64State) (h : s.pc = 4294968480) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_56 s h]
  simp

theorem fib_step_ok_57 (s : Arm64State) (h : s.pc = 4294968484) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_57 s h]
  simp

theorem fib_step_ok_58 (s : Arm64State) (h : s.pc = 4294968488) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_58 s h]
  simp

theorem fib_step_ok_59 (s : Arm64State) (h : s.pc = 4294968492) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_59 s h]
  simp

theorem fib_step_ok_60 (s : Arm64State) (h : s.pc = 4294968496) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_60 s h]
  simp

theorem fib_step_ok_61 (s : Arm64State) (h : s.pc = 4294968500) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_61 s h]
  simp

theorem fib_step_ok_62 (s : Arm64State) (h : s.pc = 4294968504) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_62 s h]
  simp

theorem fib_step_ok_63 (s : Arm64State) (h : s.pc = 4294968508) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_63 s h]
  simp

theorem fib_step_ok_64 (s : Arm64State) (h : s.pc = 4294968512) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_64 s h]
  simp

theorem fib_step_ok_65 (s : Arm64State) (h : s.pc = 4294968516) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_65 s h]
  simp

theorem fib_step_ok_66 (s : Arm64State) (h : s.pc = 4294968520) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_66 s h]
  simp

theorem fib_step_ok_67 (s : Arm64State) (h : s.pc = 4294968524) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_67 s h]
  simp

theorem fib_step_ok_68 (s : Arm64State) (h : s.pc = 4294968528) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_68 s h]
  simp

theorem fib_step_ok_69 (s : Arm64State) (h : s.pc = 4294968532) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_69 s h]
  simp

theorem fib_step_ok_70 (s : Arm64State) (h : s.pc = 4294968536) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_70 s h]
  simp

theorem fib_step_ok_71 (s : Arm64State) (h : s.pc = 4294968540) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_71 s h]
  simp

theorem fib_step_ok_72 (s : Arm64State) (h : s.pc = 4294968544) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_72 s h]
  simp

theorem fib_step_ok_73 (s : Arm64State) (h : s.pc = 4294968548) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_73 s h]
  simp

theorem fib_step_ok_74 (s : Arm64State) (h : s.pc = 4294968552) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_74 s h]
  simp

theorem fib_step_ok_75 (s : Arm64State) (h : s.pc = 4294968556) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_75 s h]
  simp

theorem fib_step_ok_76 (s : Arm64State) (h : s.pc = 4294968560) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_76 s h]
  simp

theorem fib_step_ok_77 (s : Arm64State) (h : s.pc = 4294968564) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_77 s h]
  simp

theorem fib_step_ok_78 (s : Arm64State) (h : s.pc = 4294968568) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_78 s h]
  simp

theorem fib_step_ok_79 (s : Arm64State) (h : s.pc = 4294968572) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_79 s h]
  simp

theorem fib_step_ok_80 (s : Arm64State) (h : s.pc = 4294968576) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_80 s h]
  simp

theorem fib_step_ok_81 (s : Arm64State) (h : s.pc = 4294968580) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_81 s h]
  simp

theorem fib_step_ok_82 (s : Arm64State) (h : s.pc = 4294968584) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_82 s h]
  simp

theorem fib_step_ok_83 (s : Arm64State) (h : s.pc = 4294968588) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_83 s h]
  simp

theorem fib_step_ok_84 (s : Arm64State) (h : s.pc = 4294968592) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_84 s h]
  simp

theorem fib_step_ok_85 (s : Arm64State) (h : s.pc = 4294968596) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_85 s h]
  simp

theorem fib_step_ok_86 (s : Arm64State) (h : s.pc = 4294968600) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_86 s h]
  simp

theorem fib_step_ok_87 (s : Arm64State) (h : s.pc = 4294968604) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_87 s h]
  simp

theorem fib_step_ok_88 (s : Arm64State) (h : s.pc = 4294968608) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_88 s h]
  simp

theorem fib_step_ok_89 (s : Arm64State) (h : s.pc = 4294968612) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_89 s h]
  simp

theorem fib_step_ok_90 (s : Arm64State) (h : s.pc = 4294968616) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_90 s h]
  simp

theorem fib_step_ok_91 (s : Arm64State) (h : s.pc = 4294968620) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_91 s h]
  simp

theorem fib_step_ok_92 (s : Arm64State) (h : s.pc = 4294968624) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_92 s h]
  simp

theorem fib_step_ok_93 (s : Arm64State) (h : s.pc = 4294968628) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_93 s h]
  simp

theorem fib_step_ok_94 (s : Arm64State) (h : s.pc = 4294968632) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_94 s h]
  simp

theorem fib_step_ok_95 (s : Arm64State) (h : s.pc = 4294968636) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_95 s h]
  simp

theorem fib_step_ok_96 (s : Arm64State) (h : s.pc = 4294968640) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_96 s h]
  simp

theorem fib_step_ok_97 (s : Arm64State) (h : s.pc = 4294968644) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_97 s h]
  simp

theorem fib_step_ok_98 (s : Arm64State) (h : s.pc = 4294968648) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_98 s h]
  simp

theorem fib_step_ok_99 (s : Arm64State) (h : s.pc = 4294968652) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_99 s h]
  simp

theorem fib_step_ok_100 (s : Arm64State) (h : s.pc = 4294968656) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_100 s h]
  simp

theorem fib_step_ok_101 (s : Arm64State) (h : s.pc = 4294968660) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_101 s h]
  simp

theorem fib_step_ok_102 (s : Arm64State) (h : s.pc = 4294968664) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_102 s h]
  simp

theorem fib_step_ok_103 (s : Arm64State) (h : s.pc = 4294968668) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_103 s h]
  simp

theorem fib_step_ok_104 (s : Arm64State) (h : s.pc = 4294968672) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_104 s h]
  simp

theorem fib_step_ok_105 (s : Arm64State) (h : s.pc = 4294968676) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_105 s h]
  simp

theorem fib_step_ok_106 (s : Arm64State) (h : s.pc = 4294968680) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_106 s h]
  simp

theorem fib_step_ok_107 (s : Arm64State) (h : s.pc = 4294968684) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_107 s h]
  simp

theorem fib_step_ok_108 (s : Arm64State) (h : s.pc = 4294968688) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_108 s h]
  simp

theorem fib_step_ok_109 (s : Arm64State) (h : s.pc = 4294968692) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_109 s h]
  simp

theorem fib_step_ok_110 (s : Arm64State) (h : s.pc = 4294968696) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_110 s h]
  simp

theorem fib_step_ok_111 (s : Arm64State) (h : s.pc = 4294968700) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_111 s h]
  simp

theorem fib_step_ok_112 (s : Arm64State) (h : s.pc = 4294968704) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_112 s h]
  simp

theorem fib_step_ok_113 (s : Arm64State) (h : s.pc = 4294968708) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_113 s h]
  simp

theorem fib_step_ok_114 (s : Arm64State) (h : s.pc = 4294968712) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_114 s h]
  simp

theorem fib_step_ok_115 (s : Arm64State) (h : s.pc = 4294968716) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_115 s h]
  simp

theorem fib_step_ok_116 (s : Arm64State) (h : s.pc = 4294968720) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_116 s h]
  simp

theorem fib_step_ok_117 (s : Arm64State) (h : s.pc = 4294968724) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_117 s h]
  simp

theorem fib_step_ok_118 (s : Arm64State) (h : s.pc = 4294968728) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_118 s h]
  simp

theorem fib_step_ok_119 (s : Arm64State) (h : s.pc = 4294968732) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_119 s h]
  simp

theorem fib_step_ok_120 (s : Arm64State) (h : s.pc = 4294968736) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_120 s h]
  simp

theorem fib_step_ok_121 (s : Arm64State) (h : s.pc = 4294968740) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_121 s h]
  simp

theorem fib_step_ok_122 (s : Arm64State) (h : s.pc = 4294968744) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_122 s h]
  simp

theorem fib_step_ok_123 (s : Arm64State) (h : s.pc = 4294968748) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_123 s h]
  simp

theorem fib_step_ok_124 (s : Arm64State) (h : s.pc = 4294968752) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_124 s h]
  simp

theorem fib_step_ok_125 (s : Arm64State) (h : s.pc = 4294968756) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_125 s h]
  simp

theorem fib_step_ok_126 (s : Arm64State) (h : s.pc = 4294968760) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_126 s h]
  simp

theorem fib_step_ok_127 (s : Arm64State) (h : s.pc = 4294968764) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_127 s h]
  simp

theorem fib_step_ok_128 (s : Arm64State) (h : s.pc = 4294968768) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_128 s h]
  simp

theorem fib_step_ok_129 (s : Arm64State) (h : s.pc = 4294968772) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_129 s h]
  simp

theorem fib_step_ok_130 (s : Arm64State) (h : s.pc = 4294968776) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_130 s h]
  simp

theorem fib_step_ok_131 (s : Arm64State) (h : s.pc = 4294968780) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_131 s h]
  simp

theorem fib_step_ok_132 (s : Arm64State) (h : s.pc = 4294968784) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_132 s h]
  simp

theorem fib_step_ok_133 (s : Arm64State) (h : s.pc = 4294968788) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_133 s h]
  simp

theorem fib_step_ok_134 (s : Arm64State) (h : s.pc = 4294968792) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_134 s h]
  simp

theorem fib_step_ok_135 (s : Arm64State) (h : s.pc = 4294968796) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_135 s h]
  simp

theorem fib_step_ok_136 (s : Arm64State) (h : s.pc = 4294968800) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_136 s h]
  simp

theorem fib_step_ok_137 (s : Arm64State) (h : s.pc = 4294968804) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_137 s h]
  simp

theorem fib_step_ok_138 (s : Arm64State) (h : s.pc = 4294968808) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_138 s h]
  simp

theorem fib_step_ok_139 (s : Arm64State) (h : s.pc = 4294968812) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_139 s h]
  simp

theorem fib_step_ok_140 (s : Arm64State) (h : s.pc = 4294968816) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_140 s h]
  simp

theorem fib_step_ok_141 (s : Arm64State) (h : s.pc = 4294968820) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_141 s h]
  simp

theorem fib_step_ok_142 (s : Arm64State) (h : s.pc = 4294968824) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_142 s h]
  simp

theorem fib_step_ok_143 (s : Arm64State) (h : s.pc = 4294968828) :
  arm64_step s fib_code ≠ none := by
  rw [fib_sr_143 s h]
  simp

/-- End-to-end correctness (concrete): the compiled binary hardcodes its input
    (10), so it is a closed computation. The run starts with x30 at
    the RET sentinel, and the machine halts once the program has returned to
    it. Proved by native_decide, which scales to any program size. -/
theorem fib_compiles_correctly :
  (match arm64_exec_go { (Arm64State.init 10 4294968404)
      with x30 := UInt64.ofNat 4294970679 } fib_code 1211500 with
   | some s => s.x0
   | none => 0) = mojo 10 := by
  native_decide

    /-- Block 0: start=0x100000454 kind=cbz (10 instructions, run=9) -/
def fib_b0_qS0 (st : Arm64State) : Arm64State := st
def fib_b0_qT0 (st : Arm64State) : Arm64State :=
  { (fib_b0_qS0 st) with sp := ((fib_b0_qS0 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b0_qS0 st).mem ((fib_b0_qS0 st).sp - UInt64.ofNat 16).toNat (arm64_reg 29 (fib_b0_qS0 st))) (((fib_b0_qS0 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 30 (fib_b0_qS0 st)) }
def fib_b0_qS1 (st : Arm64State) : Arm64State := { fib_b0_qT0 st with pc := 4294968408 }
def fib_b0_qT1 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 29 (fib_b0_qS1 st) ((fib_b0_qS1 st).sp + UInt64.ofNat 0))
def fib_b0_qS2 (st : Arm64State) : Arm64State := { fib_b0_qT1 st with pc := 4294968412 }
def fib_b0_qT2 (st : Arm64State) : Arm64State :=
  { (fib_b0_qS2 st) with sp := ((fib_b0_qS2 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b0_qS2 st).mem ((fib_b0_qS2 st).sp - UInt64.ofNat 16).toNat (arm64_reg 19 (fib_b0_qS2 st))) (((fib_b0_qS2 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 20 (fib_b0_qS2 st)) }
def fib_b0_qS3 (st : Arm64State) : Arm64State := { fib_b0_qT2 st with pc := 4294968416 }
def fib_b0_qT3 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 19 (fib_b0_qS3 st) (arm64_reg 0 (fib_b0_qS3 st) + UInt64.ofNat 0))
def fib_b0_qS4 (st : Arm64State) : Arm64State := { fib_b0_qT3 st with pc := 4294968420 }
def fib_b0_qT4 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 17 (fib_b0_qS4 st) ((UInt64.ofNat (fib_b0_qS4 st).pc) - ((UInt64.ofNat (fib_b0_qS4 st).pc) % 4096) + (if 1024 ≥ 2^20 then (UInt64.ofNat 1024) - (UInt64.ofNat (2^21)) else UInt64.ofNat 1024) * 4096))
def fib_b0_qS5 (st : Arm64State) : Arm64State := { fib_b0_qT4 st with pc := 4294968424 }
def fib_b0_qT5 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 17 (fib_b0_qS5 st) (arm64_reg 17 (fib_b0_qS5 st) + UInt64.ofNat 8))
def fib_b0_qS6 (st : Arm64State) : Arm64State := { fib_b0_qT5 st with pc := 4294968428 }
def fib_b0_qT6 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 16 (fib_b0_qS6 st) (mem_read_u64 (fib_b0_qS6 st).mem (arm64_reg 17 (fib_b0_qS6 st) + UInt64.ofNat 0).toNat))
def fib_b0_qS7 (st : Arm64State) : Arm64State := { fib_b0_qT6 st with pc := 4294968432 }
def fib_b0_qT7 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 17 (fib_b0_qS7 st) ((fib_b0_qS7 st).sp + UInt64.ofNat 0))
def fib_b0_qS8 (st : Arm64State) : Arm64State := { fib_b0_qT7 st with pc := 4294968436 }
def fib_b0_qT8 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 31 (fib_b0_qS8 st) (arm64_reg 17 (fib_b0_qS8 st) - arm64_reg 16 (fib_b0_qS8 st))) with nzcv := arm64_subs_flags (arm64_reg 17 (fib_b0_qS8 st)) (arm64_reg 16 (fib_b0_qS8 st)) }
theorem fib_b0_self1 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 1 st = some (fib_b0_qS1 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b0_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b0_qT0, fib_b0_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968408 from by rw [hpc]]
  exact runs_zero fib_code (fib_b0_qS1 st)

theorem fib_b0_self2 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 2 st = some (fib_b0_qS2 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b0_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS1 st) (fib_b0_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]),
      show (fib_b0_qS1 st).pc + 4 = 4294968412 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b0_qS2 st)

theorem fib_b0_self3 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 3 st = some (fib_b0_qS3 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b0_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS2 st) (fib_b0_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]),
      show (fib_b0_qS2 st).pc + 4 = 4294968416 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b0_qS3 st)

theorem fib_b0_self4 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 4 st = some (fib_b0_qS4 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hpc3 : (fib_b0_qS3 st).pc = 4294968416 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b0_qS3 st) fib_code = some (fib_b0_qT3 st) :=
      fib_sr_40 (fib_b0_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b0_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS3 st) (fib_b0_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]),
      show (fib_b0_qS3 st).pc + 4 = 4294968420 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b0_qS4 st)

theorem fib_b0_self5 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 5 st = some (fib_b0_qS5 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hpc3 : (fib_b0_qS3 st).pc = 4294968416 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]
  have hpc4 : (fib_b0_qS4 st).pc = 4294968420 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b0_qS3 st) fib_code = some (fib_b0_qT3 st) :=
      fib_sr_40 (fib_b0_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b0_qS4 st) fib_code = some (fib_b0_qT4 st) :=
      fib_sr_41 (fib_b0_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b0_self4 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS4 st) (fib_b0_qT4 st) fib_code 0 hs4 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4]),
      show (fib_b0_qS4 st).pc + 4 = 4294968424 from by rw [hpc4]]
  exact runs_zero fib_code (fib_b0_qS5 st)

theorem fib_b0_self6 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 6 st = some (fib_b0_qS6 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hpc3 : (fib_b0_qS3 st).pc = 4294968416 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]
  have hpc4 : (fib_b0_qS4 st).pc = 4294968420 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4]
  have hpc5 : (fib_b0_qS5 st).pc = 4294968424 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b0_qS3 st) fib_code = some (fib_b0_qT3 st) :=
      fib_sr_40 (fib_b0_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b0_qS4 st) fib_code = some (fib_b0_qT4 st) :=
      fib_sr_41 (fib_b0_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b0_qS5 st) fib_code = some (fib_b0_qT5 st) :=
      fib_sr_42 (fib_b0_qS5 st) (hpc5)
  rw [runs_append fib_code 5 1 st, fib_b0_self5 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS5 st) (fib_b0_qT5 st) fib_code 0 hs5 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5]),
      show (fib_b0_qS5 st).pc + 4 = 4294968428 from by rw [hpc5]]
  exact runs_zero fib_code (fib_b0_qS6 st)

theorem fib_b0_self7 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 7 st = some (fib_b0_qS7 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hpc3 : (fib_b0_qS3 st).pc = 4294968416 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]
  have hpc4 : (fib_b0_qS4 st).pc = 4294968420 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4]
  have hpc5 : (fib_b0_qS5 st).pc = 4294968424 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5]
  have hpc6 : (fib_b0_qS6 st).pc = 4294968428 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b0_qS3 st) fib_code = some (fib_b0_qT3 st) :=
      fib_sr_40 (fib_b0_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b0_qS4 st) fib_code = some (fib_b0_qT4 st) :=
      fib_sr_41 (fib_b0_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b0_qS5 st) fib_code = some (fib_b0_qT5 st) :=
      fib_sr_42 (fib_b0_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b0_qS6 st) fib_code = some (fib_b0_qT6 st) :=
      fib_sr_43 (fib_b0_qS6 st) (hpc6)
  rw [runs_append fib_code 6 1 st, fib_b0_self6 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS6 st) (fib_b0_qT6 st) fib_code 0 hs6 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6]),
      show (fib_b0_qS6 st).pc + 4 = 4294968432 from by rw [hpc6]]
  exact runs_zero fib_code (fib_b0_qS7 st)

theorem fib_b0_self8 (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 8 st = some (fib_b0_qS8 st) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hpc3 : (fib_b0_qS3 st).pc = 4294968416 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]
  have hpc4 : (fib_b0_qS4 st).pc = 4294968420 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4]
  have hpc5 : (fib_b0_qS5 st).pc = 4294968424 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5]
  have hpc6 : (fib_b0_qS6 st).pc = 4294968428 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6]
  have hpc7 : (fib_b0_qS7 st).pc = 4294968432 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b0_qS3 st) fib_code = some (fib_b0_qT3 st) :=
      fib_sr_40 (fib_b0_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b0_qS4 st) fib_code = some (fib_b0_qT4 st) :=
      fib_sr_41 (fib_b0_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b0_qS5 st) fib_code = some (fib_b0_qT5 st) :=
      fib_sr_42 (fib_b0_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b0_qS6 st) fib_code = some (fib_b0_qT6 st) :=
      fib_sr_43 (fib_b0_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b0_qS7 st) fib_code = some (fib_b0_qT7 st) :=
      fib_sr_44 (fib_b0_qS7 st) (hpc7)
  rw [runs_append fib_code 7 1 st, fib_b0_self7 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS7 st) (fib_b0_qT7 st) fib_code 0 hs7 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7]),
      show (fib_b0_qS7 st).pc + 4 = 4294968436 from by rw [hpc7]]
  exact runs_zero fib_code (fib_b0_qS8 st)

theorem fib_b0_runs (st : Arm64State) (hpc : st.pc = 4294968404) :
    arm64_runs fib_code 9 st = some ({ fib_b0_qT8 st with pc := 4294968440 }) := by
  have hpc0 : (fib_b0_qS0 st).pc = 4294968404 := by
    simp [fib_b0_qS0, hpc]
  have hpc1 : (fib_b0_qS1 st).pc = 4294968408 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qT0, fib_b0_qT1]
  have hpc2 : (fib_b0_qS2 st).pc = 4294968412 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2]
  have hpc3 : (fib_b0_qS3 st).pc = 4294968416 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3]
  have hpc4 : (fib_b0_qS4 st).pc = 4294968420 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4]
  have hpc5 : (fib_b0_qS5 st).pc = 4294968424 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5]
  have hpc6 : (fib_b0_qS6 st).pc = 4294968428 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6]
  have hpc7 : (fib_b0_qS7 st).pc = 4294968432 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7]
  have hpc8 : (fib_b0_qS8 st).pc = 4294968436 := by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8]
  have hs0 : arm64_step (fib_b0_qS0 st) fib_code = some (fib_b0_qT0 st) :=
      fib_sr_37 (fib_b0_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b0_qS1 st) fib_code = some (fib_b0_qT1 st) :=
      fib_sr_38 (fib_b0_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b0_qS2 st) fib_code = some (fib_b0_qT2 st) :=
      fib_sr_39 (fib_b0_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b0_qS3 st) fib_code = some (fib_b0_qT3 st) :=
      fib_sr_40 (fib_b0_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b0_qS4 st) fib_code = some (fib_b0_qT4 st) :=
      fib_sr_41 (fib_b0_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b0_qS5 st) fib_code = some (fib_b0_qT5 st) :=
      fib_sr_42 (fib_b0_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b0_qS6 st) fib_code = some (fib_b0_qT6 st) :=
      fib_sr_43 (fib_b0_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b0_qS7 st) fib_code = some (fib_b0_qT7 st) :=
      fib_sr_44 (fib_b0_qS7 st) (hpc7)
  have hs8 : arm64_step (fib_b0_qS8 st) fib_code = some (fib_b0_qT8 st) :=
      fib_sr_45 (fib_b0_qS8 st) (hpc8)
  rw [runs_append fib_code 8 1 st, fib_b0_self8 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b0_qS8 st) (fib_b0_qT8 st) fib_code 0 hs8 (by simp only [arm64_reg, arm64_set_reg, fib_b0_qS0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT0, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8]),
      show (fib_b0_qS8 st).pc + 4 = 4294968440 from by rw [hpc8]]
  exact runs_zero fib_code ({ fib_b0_qT8 st with pc := 4294968440 })

theorem fib_b0_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968404)
    (hexit : ∀ p ∈ [4294968404, 4294968408, 4294968412, 4294968416, 4294968420, 4294968424, 4294968428, 4294968432, 4294968436], p ≠ exit) :
    ∀ u < 9, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 ∨ u = 5 ∨ u = 6 ∨ u = 7 ∨ u = 8 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968404 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968408 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b0_qS1 st) :=
      fib_b0_self1 st hpc
    have heq : some (fib_b0_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968408 ≠ exit
    exact hk
  · have hk : 4294968412 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b0_qS2 st) :=
      fib_b0_self2 st hpc
    have heq : some (fib_b0_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968412 ≠ exit
    exact hk
  · have hk : 4294968416 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b0_qS3 st) :=
      fib_b0_self3 st hpc
    have heq : some (fib_b0_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968416 ≠ exit
    exact hk
  · have hk : 4294968420 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b0_qS4 st) :=
      fib_b0_self4 st hpc
    have heq : some (fib_b0_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968420 ≠ exit
    exact hk
  · have hk : 4294968424 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 5 st = some (fib_b0_qS5 st) :=
      fib_b0_self5 st hpc
    have heq : some (fib_b0_qS5 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968424 ≠ exit
    exact hk
  · have hk : 4294968428 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 6 st = some (fib_b0_qS6 st) :=
      fib_b0_self6 st hpc
    have heq : some (fib_b0_qS6 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968428 ≠ exit
    exact hk
  · have hk : 4294968432 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 7 st = some (fib_b0_qS7 st) :=
      fib_b0_self7 st hpc
    have heq : some (fib_b0_qS7 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968432 ≠ exit
    exact hk
  · have hk : 4294968436 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 8 st = some (fib_b0_qS8 st) :=
      fib_b0_self8 st hpc
    have heq : some (fib_b0_qS8 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968436 ≠ exit
    exact hk

/-- Block 1: start=0x10000047c kind=seq (11 instructions, run=11) -/
def fib_b1_qS0 (st : Arm64State) : Arm64State := st
def fib_b1_qT0 (st : Arm64State) : Arm64State :=
  { (fib_b1_qS0 st) with sp := ((fib_b1_qS0 st).sp - UInt64.ofNat 16) }
def fib_b1_qS1 (st : Arm64State) : Arm64State := { fib_b1_qT0 st with pc := 4294968448 }
def fib_b1_qT1 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 1 (fib_b1_qS1 st) ((UInt64.ofNat (fib_b1_qS1 st).pc) - ((UInt64.ofNat (fib_b1_qS1 st).pc) % 4096) + (if 0 ≥ 2^20 then (UInt64.ofNat 0) - (UInt64.ofNat (2^21)) else UInt64.ofNat 0) * 4096))
def fib_b1_qS2 (st : Arm64State) : Arm64State := { fib_b1_qT1 st with pc := 4294968452 }
def fib_b1_qT2 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 1 (fib_b1_qS2 st) (arm64_reg 1 (fib_b1_qS2 st) + UInt64.ofNat 2516))
def fib_b1_qS3 (st : Arm64State) : Arm64State := { fib_b1_qT2 st with pc := 4294968456 }
def fib_b1_qT3 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b1_qS3 st) (UInt64.ofNat 2))
def fib_b1_qS4 (st : Arm64State) : Arm64State := { fib_b1_qT3 st with pc := 4294968460 }
def fib_b1_qT4 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 2 (fib_b1_qS4 st) (UInt64.ofNat 837))
def fib_b1_qS5 (st : Arm64State) : Arm64State := { fib_b1_qT4 st with pc := 4294968464 }
def fib_b1_qT5 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 16 (fib_b1_qS5 st) (UInt64.ofNat 4))
def fib_b1_qS6 (st : Arm64State) : Arm64State := { fib_b1_qT5 st with pc := 4294968468 }
def fib_b1_qT6 (st : Arm64State) : Arm64State :=
  (fib_b1_qS6 st)
def fib_b1_qS7 (st : Arm64State) : Arm64State := { fib_b1_qT6 st with pc := 4294968472 }
def fib_b1_qT7 (st : Arm64State) : Arm64State :=
  { (fib_b1_qS7 st) with sp := ((fib_b1_qS7 st).sp + UInt64.ofNat 16) }
def fib_b1_qS8 (st : Arm64State) : Arm64State := { fib_b1_qT7 st with pc := 4294968476 }
def fib_b1_qT8 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b1_qS8 st) (UInt64.ofNat 2))
def fib_b1_qS9 (st : Arm64State) : Arm64State := { fib_b1_qT8 st with pc := 4294968480 }
def fib_b1_qT9 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 16 (fib_b1_qS9 st) (UInt64.ofNat 1))
def fib_b1_qS10 (st : Arm64State) : Arm64State := { fib_b1_qT9 st with pc := 4294968484 }
def fib_b1_qT10 (st : Arm64State) : Arm64State :=
  (fib_b1_qS10 st)
theorem fib_b1_self1 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 1 st = some (fib_b1_qS1 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b1_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b1_qT0, fib_b1_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968448 from by rw [hpc]]
  exact runs_zero fib_code (fib_b1_qS1 st)

theorem fib_b1_self2 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 2 st = some (fib_b1_qS2 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b1_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS1 st) (fib_b1_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]),
      show (fib_b1_qS1 st).pc + 4 = 4294968452 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b1_qS2 st)

theorem fib_b1_self3 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 3 st = some (fib_b1_qS3 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b1_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS2 st) (fib_b1_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]),
      show (fib_b1_qS2 st).pc + 4 = 4294968456 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b1_qS3 st)

theorem fib_b1_self4 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 4 st = some (fib_b1_qS4 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b1_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS3 st) (fib_b1_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]),
      show (fib_b1_qS3 st).pc + 4 = 4294968460 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b1_qS4 st)

theorem fib_b1_self5 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 5 st = some (fib_b1_qS5 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b1_self4 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS4 st) (fib_b1_qT4 st) fib_code 0 hs4 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]),
      show (fib_b1_qS4 st).pc + 4 = 4294968464 from by rw [hpc4]]
  exact runs_zero fib_code (fib_b1_qS5 st)

theorem fib_b1_self6 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 6 st = some (fib_b1_qS6 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hpc5 : (fib_b1_qS5 st).pc = 4294968464 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b1_qS5 st) fib_code = some (fib_b1_qT5 st) :=
      fib_sr_52 (fib_b1_qS5 st) (hpc5)
  rw [runs_append fib_code 5 1 st, fib_b1_self5 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS5 st) (fib_b1_qT5 st) fib_code 0 hs5 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]),
      show (fib_b1_qS5 st).pc + 4 = 4294968468 from by rw [hpc5]]
  exact runs_zero fib_code (fib_b1_qS6 st)

theorem fib_b1_self7 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 7 st = some (fib_b1_qS7 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hpc5 : (fib_b1_qS5 st).pc = 4294968464 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]
  have hpc6 : (fib_b1_qS6 st).pc = 4294968468 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b1_qS5 st) fib_code = some (fib_b1_qT5 st) :=
      fib_sr_52 (fib_b1_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b1_qS6 st) fib_code = some (fib_b1_qT6 st) :=
      fib_sr_53 (fib_b1_qS6 st) (hpc6)
  rw [runs_append fib_code 6 1 st, fib_b1_self6 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS6 st) (fib_b1_qT6 st) fib_code 0 hs6 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6]),
      show (fib_b1_qS6 st).pc + 4 = 4294968472 from by rw [hpc6]]
  exact runs_zero fib_code (fib_b1_qS7 st)

theorem fib_b1_self8 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 8 st = some (fib_b1_qS8 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hpc5 : (fib_b1_qS5 st).pc = 4294968464 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]
  have hpc6 : (fib_b1_qS6 st).pc = 4294968468 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6]
  have hpc7 : (fib_b1_qS7 st).pc = 4294968472 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b1_qS5 st) fib_code = some (fib_b1_qT5 st) :=
      fib_sr_52 (fib_b1_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b1_qS6 st) fib_code = some (fib_b1_qT6 st) :=
      fib_sr_53 (fib_b1_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b1_qS7 st) fib_code = some (fib_b1_qT7 st) :=
      fib_sr_54 (fib_b1_qS7 st) (hpc7)
  rw [runs_append fib_code 7 1 st, fib_b1_self7 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS7 st) (fib_b1_qT7 st) fib_code 0 hs7 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7]),
      show (fib_b1_qS7 st).pc + 4 = 4294968476 from by rw [hpc7]]
  exact runs_zero fib_code (fib_b1_qS8 st)

theorem fib_b1_self9 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 9 st = some (fib_b1_qS9 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hpc5 : (fib_b1_qS5 st).pc = 4294968464 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]
  have hpc6 : (fib_b1_qS6 st).pc = 4294968468 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6]
  have hpc7 : (fib_b1_qS7 st).pc = 4294968472 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7]
  have hpc8 : (fib_b1_qS8 st).pc = 4294968476 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b1_qS5 st) fib_code = some (fib_b1_qT5 st) :=
      fib_sr_52 (fib_b1_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b1_qS6 st) fib_code = some (fib_b1_qT6 st) :=
      fib_sr_53 (fib_b1_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b1_qS7 st) fib_code = some (fib_b1_qT7 st) :=
      fib_sr_54 (fib_b1_qS7 st) (hpc7)
  have hs8 : arm64_step (fib_b1_qS8 st) fib_code = some (fib_b1_qT8 st) :=
      fib_sr_55 (fib_b1_qS8 st) (hpc8)
  rw [runs_append fib_code 8 1 st, fib_b1_self8 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS8 st) (fib_b1_qT8 st) fib_code 0 hs8 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8]),
      show (fib_b1_qS8 st).pc + 4 = 4294968480 from by rw [hpc8]]
  exact runs_zero fib_code (fib_b1_qS9 st)

theorem fib_b1_self10 (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 10 st = some (fib_b1_qS10 st) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hpc5 : (fib_b1_qS5 st).pc = 4294968464 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]
  have hpc6 : (fib_b1_qS6 st).pc = 4294968468 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6]
  have hpc7 : (fib_b1_qS7 st).pc = 4294968472 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7]
  have hpc8 : (fib_b1_qS8 st).pc = 4294968476 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8]
  have hpc9 : (fib_b1_qS9 st).pc = 4294968480 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b1_qS5 st) fib_code = some (fib_b1_qT5 st) :=
      fib_sr_52 (fib_b1_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b1_qS6 st) fib_code = some (fib_b1_qT6 st) :=
      fib_sr_53 (fib_b1_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b1_qS7 st) fib_code = some (fib_b1_qT7 st) :=
      fib_sr_54 (fib_b1_qS7 st) (hpc7)
  have hs8 : arm64_step (fib_b1_qS8 st) fib_code = some (fib_b1_qT8 st) :=
      fib_sr_55 (fib_b1_qS8 st) (hpc8)
  have hs9 : arm64_step (fib_b1_qS9 st) fib_code = some (fib_b1_qT9 st) :=
      fib_sr_56 (fib_b1_qS9 st) (hpc9)
  rw [runs_append fib_code 9 1 st, fib_b1_self9 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS9 st) (fib_b1_qT9 st) fib_code 0 hs9 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9]),
      show (fib_b1_qS9 st).pc + 4 = 4294968484 from by rw [hpc9]]
  exact runs_zero fib_code (fib_b1_qS10 st)

theorem fib_b1_runs (st : Arm64State) (hpc : st.pc = 4294968444) :
    arm64_runs fib_code 11 st = some ({ fib_b1_qT10 st with pc := 4294968488 }) := by
  have hpc0 : (fib_b1_qS0 st).pc = 4294968444 := by
    simp [fib_b1_qS0, hpc]
  have hpc1 : (fib_b1_qS1 st).pc = 4294968448 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qT0, fib_b1_qT1]
  have hpc2 : (fib_b1_qS2 st).pc = 4294968452 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2]
  have hpc3 : (fib_b1_qS3 st).pc = 4294968456 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3]
  have hpc4 : (fib_b1_qS4 st).pc = 4294968460 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4]
  have hpc5 : (fib_b1_qS5 st).pc = 4294968464 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5]
  have hpc6 : (fib_b1_qS6 st).pc = 4294968468 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6]
  have hpc7 : (fib_b1_qS7 st).pc = 4294968472 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7]
  have hpc8 : (fib_b1_qS8 st).pc = 4294968476 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8]
  have hpc9 : (fib_b1_qS9 st).pc = 4294968480 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9]
  have hpc10 : (fib_b1_qS10 st).pc = 4294968484 := by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10]
  have hs0 : arm64_step (fib_b1_qS0 st) fib_code = some (fib_b1_qT0 st) :=
      fib_sr_47 (fib_b1_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b1_qS1 st) fib_code = some (fib_b1_qT1 st) :=
      fib_sr_48 (fib_b1_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b1_qS2 st) fib_code = some (fib_b1_qT2 st) :=
      fib_sr_49 (fib_b1_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b1_qS3 st) fib_code = some (fib_b1_qT3 st) :=
      fib_sr_50 (fib_b1_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b1_qS4 st) fib_code = some (fib_b1_qT4 st) :=
      fib_sr_51 (fib_b1_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b1_qS5 st) fib_code = some (fib_b1_qT5 st) :=
      fib_sr_52 (fib_b1_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b1_qS6 st) fib_code = some (fib_b1_qT6 st) :=
      fib_sr_53 (fib_b1_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b1_qS7 st) fib_code = some (fib_b1_qT7 st) :=
      fib_sr_54 (fib_b1_qS7 st) (hpc7)
  have hs8 : arm64_step (fib_b1_qS8 st) fib_code = some (fib_b1_qT8 st) :=
      fib_sr_55 (fib_b1_qS8 st) (hpc8)
  have hs9 : arm64_step (fib_b1_qS9 st) fib_code = some (fib_b1_qT9 st) :=
      fib_sr_56 (fib_b1_qS9 st) (hpc9)
  have hs10 : arm64_step (fib_b1_qS10 st) fib_code = some (fib_b1_qT10 st) :=
      fib_sr_57 (fib_b1_qS10 st) (hpc10)
  rw [runs_append fib_code 10 1 st, fib_b1_self10 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b1_qS10 st) (fib_b1_qT10 st) fib_code 0 hs10 (by simp only [arm64_reg, arm64_set_reg, fib_b1_qS0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT0, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10]),
      show (fib_b1_qS10 st).pc + 4 = 4294968488 from by rw [hpc10]]
  exact runs_zero fib_code ({ fib_b1_qT10 st with pc := 4294968488 })

theorem fib_b1_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968444)
    (hexit : ∀ p ∈ [4294968444, 4294968448, 4294968452, 4294968456, 4294968460, 4294968464, 4294968468, 4294968472, 4294968476, 4294968480, 4294968484], p ≠ exit) :
    ∀ u < 11, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 ∨ u = 5 ∨ u = 6 ∨ u = 7 ∨ u = 8 ∨ u = 9 ∨ u = 10 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968444 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968448 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b1_qS1 st) :=
      fib_b1_self1 st hpc
    have heq : some (fib_b1_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968448 ≠ exit
    exact hk
  · have hk : 4294968452 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b1_qS2 st) :=
      fib_b1_self2 st hpc
    have heq : some (fib_b1_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968452 ≠ exit
    exact hk
  · have hk : 4294968456 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b1_qS3 st) :=
      fib_b1_self3 st hpc
    have heq : some (fib_b1_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968456 ≠ exit
    exact hk
  · have hk : 4294968460 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b1_qS4 st) :=
      fib_b1_self4 st hpc
    have heq : some (fib_b1_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968460 ≠ exit
    exact hk
  · have hk : 4294968464 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 5 st = some (fib_b1_qS5 st) :=
      fib_b1_self5 st hpc
    have heq : some (fib_b1_qS5 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968464 ≠ exit
    exact hk
  · have hk : 4294968468 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 6 st = some (fib_b1_qS6 st) :=
      fib_b1_self6 st hpc
    have heq : some (fib_b1_qS6 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968468 ≠ exit
    exact hk
  · have hk : 4294968472 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 7 st = some (fib_b1_qS7 st) :=
      fib_b1_self7 st hpc
    have heq : some (fib_b1_qS7 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968472 ≠ exit
    exact hk
  · have hk : 4294968476 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 8 st = some (fib_b1_qS8 st) :=
      fib_b1_self8 st hpc
    have heq : some (fib_b1_qS8 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968476 ≠ exit
    exact hk
  · have hk : 4294968480 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 9 st = some (fib_b1_qS9 st) :=
      fib_b1_self9 st hpc
    have heq : some (fib_b1_qS9 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968480 ≠ exit
    exact hk
  · have hk : 4294968484 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 10 st = some (fib_b1_qS10 st) :=
      fib_b1_self10 st hpc
    have heq : some (fib_b1_qS10 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968484 ≠ exit
    exact hk

/-- Block 2: start=0x1000004a8 kind=cbz (8 instructions, run=7) -/
def fib_b2_qS0 (st : Arm64State) : Arm64State := st
def fib_b2_qT0 (st : Arm64State) : Arm64State :=
  { (fib_b2_qS0 st) with sp := ((fib_b2_qS0 st).sp - UInt64.ofNat 131072) }
def fib_b2_qS1 (st : Arm64State) : Arm64State := { fib_b2_qT0 st with pc := 4294968492 }
def fib_b2_qT1 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b2_qS1 st) (arm64_reg 19 (fib_b2_qS1 st) + UInt64.ofNat 0))
def fib_b2_qS2 (st : Arm64State) : Arm64State := { fib_b2_qT1 st with pc := 4294968496 }
def fib_b2_qT2 (st : Arm64State) : Arm64State :=
  { (fib_b2_qS2 st) with sp := ((fib_b2_qS2 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b2_qS2 st).mem ((fib_b2_qS2 st).sp - UInt64.ofNat 16).toNat (arm64_reg 0 (fib_b2_qS2 st))) (((fib_b2_qS2 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 (fib_b2_qS2 st)) }
def fib_b2_qS3 (st : Arm64State) : Arm64State := { fib_b2_qT2 st with pc := 4294968500 }
def fib_b2_qT3 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b2_qS3 st) (UInt64.ofNat 1))
def fib_b2_qS4 (st : Arm64State) : Arm64State := { fib_b2_qT3 st with pc := 4294968504 }
def fib_b2_qT4 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 1 (fib_b2_qS4 st) (arm64_reg 0 (fib_b2_qS4 st) + UInt64.ofNat 0))
def fib_b2_qS5 (st : Arm64State) : Arm64State := { fib_b2_qT4 st with pc := 4294968508 }
def fib_b2_qT5 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 2 (arm64_set_reg 0 (fib_b2_qS5 st) (mem_read_u64 (fib_b2_qS5 st).mem (fib_b2_qS5 st).sp.toNat)) (mem_read_u64 (fib_b2_qS5 st).mem ((fib_b2_qS5 st).sp + 8).toNat)) with sp := (fib_b2_qS5 st).sp + UInt64.ofNat 16 }
def fib_b2_qS6 (st : Arm64State) : Arm64State := { fib_b2_qT5 st with pc := 4294968512 }
def fib_b2_qT6 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 31 (fib_b2_qS6 st) (arm64_reg 0 (fib_b2_qS6 st) - arm64_reg 1 (fib_b2_qS6 st))) with nzcv := arm64_subs_flags (arm64_reg 0 (fib_b2_qS6 st)) (arm64_reg 1 (fib_b2_qS6 st)) }
theorem fib_b2_self1 (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 1 st = some (fib_b2_qS1 st) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b2_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b2_qT0, fib_b2_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968492 from by rw [hpc]]
  exact runs_zero fib_code (fib_b2_qS1 st)

theorem fib_b2_self2 (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 2 st = some (fib_b2_qS2 st) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hpc1 : (fib_b2_qS1 st).pc = 4294968492 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b2_qS1 st) fib_code = some (fib_b2_qT1 st) :=
      fib_sr_59 (fib_b2_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b2_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b2_qS1 st) (fib_b2_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]),
      show (fib_b2_qS1 st).pc + 4 = 4294968496 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b2_qS2 st)

theorem fib_b2_self3 (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 3 st = some (fib_b2_qS3 st) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hpc1 : (fib_b2_qS1 st).pc = 4294968492 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]
  have hpc2 : (fib_b2_qS2 st).pc = 4294968496 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b2_qS1 st) fib_code = some (fib_b2_qT1 st) :=
      fib_sr_59 (fib_b2_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b2_qS2 st) fib_code = some (fib_b2_qT2 st) :=
      fib_sr_60 (fib_b2_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b2_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b2_qS2 st) (fib_b2_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2]),
      show (fib_b2_qS2 st).pc + 4 = 4294968500 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b2_qS3 st)

theorem fib_b2_self4 (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 4 st = some (fib_b2_qS4 st) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hpc1 : (fib_b2_qS1 st).pc = 4294968492 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]
  have hpc2 : (fib_b2_qS2 st).pc = 4294968496 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2]
  have hpc3 : (fib_b2_qS3 st).pc = 4294968500 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b2_qS1 st) fib_code = some (fib_b2_qT1 st) :=
      fib_sr_59 (fib_b2_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b2_qS2 st) fib_code = some (fib_b2_qT2 st) :=
      fib_sr_60 (fib_b2_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b2_qS3 st) fib_code = some (fib_b2_qT3 st) :=
      fib_sr_61 (fib_b2_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b2_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b2_qS3 st) (fib_b2_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3]),
      show (fib_b2_qS3 st).pc + 4 = 4294968504 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b2_qS4 st)

theorem fib_b2_self5 (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 5 st = some (fib_b2_qS5 st) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hpc1 : (fib_b2_qS1 st).pc = 4294968492 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]
  have hpc2 : (fib_b2_qS2 st).pc = 4294968496 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2]
  have hpc3 : (fib_b2_qS3 st).pc = 4294968500 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3]
  have hpc4 : (fib_b2_qS4 st).pc = 4294968504 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b2_qS1 st) fib_code = some (fib_b2_qT1 st) :=
      fib_sr_59 (fib_b2_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b2_qS2 st) fib_code = some (fib_b2_qT2 st) :=
      fib_sr_60 (fib_b2_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b2_qS3 st) fib_code = some (fib_b2_qT3 st) :=
      fib_sr_61 (fib_b2_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b2_qS4 st) fib_code = some (fib_b2_qT4 st) :=
      fib_sr_62 (fib_b2_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b2_self4 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b2_qS4 st) (fib_b2_qT4 st) fib_code 0 hs4 (by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4]),
      show (fib_b2_qS4 st).pc + 4 = 4294968508 from by rw [hpc4]]
  exact runs_zero fib_code (fib_b2_qS5 st)

theorem fib_b2_self6 (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 6 st = some (fib_b2_qS6 st) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hpc1 : (fib_b2_qS1 st).pc = 4294968492 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]
  have hpc2 : (fib_b2_qS2 st).pc = 4294968496 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2]
  have hpc3 : (fib_b2_qS3 st).pc = 4294968500 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3]
  have hpc4 : (fib_b2_qS4 st).pc = 4294968504 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4]
  have hpc5 : (fib_b2_qS5 st).pc = 4294968508 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b2_qS1 st) fib_code = some (fib_b2_qT1 st) :=
      fib_sr_59 (fib_b2_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b2_qS2 st) fib_code = some (fib_b2_qT2 st) :=
      fib_sr_60 (fib_b2_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b2_qS3 st) fib_code = some (fib_b2_qT3 st) :=
      fib_sr_61 (fib_b2_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b2_qS4 st) fib_code = some (fib_b2_qT4 st) :=
      fib_sr_62 (fib_b2_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b2_qS5 st) fib_code = some (fib_b2_qT5 st) :=
      fib_sr_63 (fib_b2_qS5 st) (hpc5)
  rw [runs_append fib_code 5 1 st, fib_b2_self5 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b2_qS5 st) (fib_b2_qT5 st) fib_code 0 hs5 (by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5]),
      show (fib_b2_qS5 st).pc + 4 = 4294968512 from by rw [hpc5]]
  exact runs_zero fib_code (fib_b2_qS6 st)

theorem fib_b2_runs (st : Arm64State) (hpc : st.pc = 4294968488) :
    arm64_runs fib_code 7 st = some ({ fib_b2_qT6 st with pc := 4294968516 }) := by
  have hpc0 : (fib_b2_qS0 st).pc = 4294968488 := by
    simp [fib_b2_qS0, hpc]
  have hpc1 : (fib_b2_qS1 st).pc = 4294968492 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qT0, fib_b2_qT1]
  have hpc2 : (fib_b2_qS2 st).pc = 4294968496 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2]
  have hpc3 : (fib_b2_qS3 st).pc = 4294968500 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3]
  have hpc4 : (fib_b2_qS4 st).pc = 4294968504 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4]
  have hpc5 : (fib_b2_qS5 st).pc = 4294968508 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5]
  have hpc6 : (fib_b2_qS6 st).pc = 4294968512 := by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6]
  have hs0 : arm64_step (fib_b2_qS0 st) fib_code = some (fib_b2_qT0 st) :=
      fib_sr_58 (fib_b2_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b2_qS1 st) fib_code = some (fib_b2_qT1 st) :=
      fib_sr_59 (fib_b2_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b2_qS2 st) fib_code = some (fib_b2_qT2 st) :=
      fib_sr_60 (fib_b2_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b2_qS3 st) fib_code = some (fib_b2_qT3 st) :=
      fib_sr_61 (fib_b2_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b2_qS4 st) fib_code = some (fib_b2_qT4 st) :=
      fib_sr_62 (fib_b2_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b2_qS5 st) fib_code = some (fib_b2_qT5 st) :=
      fib_sr_63 (fib_b2_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b2_qS6 st) fib_code = some (fib_b2_qT6 st) :=
      fib_sr_64 (fib_b2_qS6 st) (hpc6)
  rw [runs_append fib_code 6 1 st, fib_b2_self6 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b2_qS6 st) (fib_b2_qT6 st) fib_code 0 hs6 (by simp only [arm64_reg, arm64_set_reg, fib_b2_qS0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT0, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6]),
      show (fib_b2_qS6 st).pc + 4 = 4294968516 from by rw [hpc6]]
  exact runs_zero fib_code ({ fib_b2_qT6 st with pc := 4294968516 })

theorem fib_b2_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968488)
    (hexit : ∀ p ∈ [4294968488, 4294968492, 4294968496, 4294968500, 4294968504, 4294968508, 4294968512], p ≠ exit) :
    ∀ u < 7, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 ∨ u = 5 ∨ u = 6 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968488 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968492 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b2_qS1 st) :=
      fib_b2_self1 st hpc
    have heq : some (fib_b2_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968492 ≠ exit
    exact hk
  · have hk : 4294968496 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b2_qS2 st) :=
      fib_b2_self2 st hpc
    have heq : some (fib_b2_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968496 ≠ exit
    exact hk
  · have hk : 4294968500 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b2_qS3 st) :=
      fib_b2_self3 st hpc
    have heq : some (fib_b2_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968500 ≠ exit
    exact hk
  · have hk : 4294968504 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b2_qS4 st) :=
      fib_b2_self4 st hpc
    have heq : some (fib_b2_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968504 ≠ exit
    exact hk
  · have hk : 4294968508 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 5 st = some (fib_b2_qS5 st) :=
      fib_b2_self5 st hpc
    have heq : some (fib_b2_qS5 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968508 ≠ exit
    exact hk
  · have hk : 4294968512 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 6 st = some (fib_b2_qS6 st) :=
      fib_b2_self6 st hpc
    have heq : some (fib_b2_qS6 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968512 ≠ exit
    exact hk

/-- Block 3: start=0x1000004c8 kind=ret (5 instructions, run=5) -/
def fib_b3_qS0 (st : Arm64State) : Arm64State := st
def fib_b3_qT0 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b3_qS0 st) (arm64_reg 19 (fib_b3_qS0 st) + UInt64.ofNat 0))
def fib_b3_qS1 (st : Arm64State) : Arm64State := { fib_b3_qT0 st with pc := 4294968524 }
def fib_b3_qT1 (st : Arm64State) : Arm64State :=
  { (fib_b3_qS1 st) with sp := ((fib_b3_qS1 st).sp + UInt64.ofNat 131072) }
def fib_b3_qS2 (st : Arm64State) : Arm64State := { fib_b3_qT1 st with pc := 4294968528 }
def fib_b3_qT2 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 20 (arm64_set_reg 19 (fib_b3_qS2 st) (mem_read_u64 (fib_b3_qS2 st).mem (fib_b3_qS2 st).sp.toNat)) (mem_read_u64 (fib_b3_qS2 st).mem ((fib_b3_qS2 st).sp + 8).toNat)) with sp := (fib_b3_qS2 st).sp + UInt64.ofNat 16 }
def fib_b3_qS3 (st : Arm64State) : Arm64State := { fib_b3_qT2 st with pc := 4294968532 }
def fib_b3_qT3 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 30 (arm64_set_reg 29 (fib_b3_qS3 st) (mem_read_u64 (fib_b3_qS3 st).mem (fib_b3_qS3 st).sp.toNat)) (mem_read_u64 (fib_b3_qS3 st).mem ((fib_b3_qS3 st).sp + 8).toNat)) with sp := (fib_b3_qS3 st).sp + UInt64.ofNat 16 }
def fib_b3_qS4 (st : Arm64State) : Arm64State := { fib_b3_qT3 st with pc := 4294968536 }
def fib_b3_qT4 (st : Arm64State) : Arm64State :=
  { (fib_b3_qS4 st) with pc := (fib_b3_qS4 st).x30.toNat }
theorem fib_b3_self1 (st : Arm64State) (hpc : st.pc = 4294968520) :
    arm64_runs fib_code 1 st = some (fib_b3_qS1 st) := by
  have hpc0 : (fib_b3_qS0 st).pc = 4294968520 := by
    simp [fib_b3_qS0, hpc]
  have hs0 : arm64_step (fib_b3_qS0 st) fib_code = some (fib_b3_qT0 st) :=
      fib_sr_66 (fib_b3_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b3_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b3_qT0, fib_b3_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968524 from by rw [hpc]]
  exact runs_zero fib_code (fib_b3_qS1 st)

theorem fib_b3_self2 (st : Arm64State) (hpc : st.pc = 4294968520) :
    arm64_runs fib_code 2 st = some (fib_b3_qS2 st) := by
  have hpc0 : (fib_b3_qS0 st).pc = 4294968520 := by
    simp [fib_b3_qS0, hpc]
  have hpc1 : (fib_b3_qS1 st).pc = 4294968524 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qT0, fib_b3_qT1]
  have hs0 : arm64_step (fib_b3_qS0 st) fib_code = some (fib_b3_qT0 st) :=
      fib_sr_66 (fib_b3_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b3_qS1 st) fib_code = some (fib_b3_qT1 st) :=
      fib_sr_67 (fib_b3_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b3_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b3_qS1 st) (fib_b3_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qT0, fib_b3_qT1]),
      show (fib_b3_qS1 st).pc + 4 = 4294968528 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b3_qS2 st)

theorem fib_b3_self3 (st : Arm64State) (hpc : st.pc = 4294968520) :
    arm64_runs fib_code 3 st = some (fib_b3_qS3 st) := by
  have hpc0 : (fib_b3_qS0 st).pc = 4294968520 := by
    simp [fib_b3_qS0, hpc]
  have hpc1 : (fib_b3_qS1 st).pc = 4294968524 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qT0, fib_b3_qT1]
  have hpc2 : (fib_b3_qS2 st).pc = 4294968528 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2]
  have hs0 : arm64_step (fib_b3_qS0 st) fib_code = some (fib_b3_qT0 st) :=
      fib_sr_66 (fib_b3_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b3_qS1 st) fib_code = some (fib_b3_qT1 st) :=
      fib_sr_67 (fib_b3_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b3_qS2 st) fib_code = some (fib_b3_qT2 st) :=
      fib_sr_68 (fib_b3_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b3_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b3_qS2 st) (fib_b3_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2]),
      show (fib_b3_qS2 st).pc + 4 = 4294968532 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b3_qS3 st)

theorem fib_b3_self4 (st : Arm64State) (hpc : st.pc = 4294968520) :
    arm64_runs fib_code 4 st = some (fib_b3_qS4 st) := by
  have hpc0 : (fib_b3_qS0 st).pc = 4294968520 := by
    simp [fib_b3_qS0, hpc]
  have hpc1 : (fib_b3_qS1 st).pc = 4294968524 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qT0, fib_b3_qT1]
  have hpc2 : (fib_b3_qS2 st).pc = 4294968528 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2]
  have hpc3 : (fib_b3_qS3 st).pc = 4294968532 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3]
  have hs0 : arm64_step (fib_b3_qS0 st) fib_code = some (fib_b3_qT0 st) :=
      fib_sr_66 (fib_b3_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b3_qS1 st) fib_code = some (fib_b3_qT1 st) :=
      fib_sr_67 (fib_b3_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b3_qS2 st) fib_code = some (fib_b3_qT2 st) :=
      fib_sr_68 (fib_b3_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b3_qS3 st) fib_code = some (fib_b3_qT3 st) :=
      fib_sr_69 (fib_b3_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b3_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b3_qS3 st) (fib_b3_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3]),
      show (fib_b3_qS3 st).pc + 4 = 4294968536 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b3_qS4 st)

theorem fib_b3_runs (st : Arm64State) (hpc : st.pc = 4294968520)
    (hjump : (fib_b3_qS4 st).x30.toNat ≠ 4294968536) :
    arm64_runs fib_code 5 st = some (fib_b3_qT4 st) := by
  have hpc0 : (fib_b3_qS0 st).pc = 4294968520 := by
    simp [fib_b3_qS0, hpc]
  have hpc1 : (fib_b3_qS1 st).pc = 4294968524 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qT0, fib_b3_qT1]
  have hpc2 : (fib_b3_qS2 st).pc = 4294968528 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2]
  have hpc3 : (fib_b3_qS3 st).pc = 4294968532 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3]
  have hpc4 : (fib_b3_qS4 st).pc = 4294968536 := by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qS4, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3, fib_b3_qT4]
  have hs0 : arm64_step (fib_b3_qS0 st) fib_code = some (fib_b3_qT0 st) :=
      fib_sr_66 (fib_b3_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b3_qS1 st) fib_code = some (fib_b3_qT1 st) :=
      fib_sr_67 (fib_b3_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b3_qS2 st) fib_code = some (fib_b3_qT2 st) :=
      fib_sr_68 (fib_b3_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b3_qS3 st) fib_code = some (fib_b3_qT3 st) :=
      fib_sr_69 (fib_b3_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b3_qS4 st) fib_code = some (fib_b3_qT4 st) :=
      fib_sr_70 (fib_b3_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b3_self4 st hpc]
  simp only []
  rw [runs_cons_jump (fib_b3_qS4 st) (fib_b3_qT4 st) fib_code 0 hs4
      (by rw [show (fib_b3_qT4 st).pc = (fib_b3_qS4 st).x30.toNat from by simp only [arm64_reg, arm64_set_reg, fib_b3_qS0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qS4, fib_b3_qT0, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3, fib_b3_qT4]]; exact hjump)]
  exact runs_zero fib_code (fib_b3_qT4 st)

theorem fib_b3_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968520)
    (hexit : ∀ p ∈ [4294968520, 4294968524, 4294968528, 4294968532, 4294968536], p ≠ exit) :
    ∀ u < 5, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968520 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968524 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b3_qS1 st) :=
      fib_b3_self1 st hpc
    have heq : some (fib_b3_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968524 ≠ exit
    exact hk
  · have hk : 4294968528 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b3_qS2 st) :=
      fib_b3_self2 st hpc
    have heq : some (fib_b3_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968528 ≠ exit
    exact hk
  · have hk : 4294968532 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b3_qS3 st) :=
      fib_b3_self3 st hpc
    have heq : some (fib_b3_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968532 ≠ exit
    exact hk
  · have hk : 4294968536 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b3_qS4 st) :=
      fib_b3_self4 st hpc
    have heq : some (fib_b3_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968536 ≠ exit
    exact hk

/-- Block 4: start=0x1000004e0 kind=bl (9 instructions, run=8) -/
def fib_b4_qS0 (st : Arm64State) : Arm64State := st
def fib_b4_qT0 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b4_qS0 st) (arm64_reg 19 (fib_b4_qS0 st) + UInt64.ofNat 0))
def fib_b4_qS1 (st : Arm64State) : Arm64State := { fib_b4_qT0 st with pc := 4294968548 }
def fib_b4_qT1 (st : Arm64State) : Arm64State :=
  { (fib_b4_qS1 st) with sp := ((fib_b4_qS1 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b4_qS1 st).mem ((fib_b4_qS1 st).sp - UInt64.ofNat 16).toNat (arm64_reg 0 (fib_b4_qS1 st))) (((fib_b4_qS1 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 (fib_b4_qS1 st)) }
def fib_b4_qS2 (st : Arm64State) : Arm64State := { fib_b4_qT1 st with pc := 4294968552 }
def fib_b4_qT2 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b4_qS2 st) (UInt64.ofNat 1))
def fib_b4_qS3 (st : Arm64State) : Arm64State := { fib_b4_qT2 st with pc := 4294968556 }
def fib_b4_qT3 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 1 (fib_b4_qS3 st) (arm64_reg 0 (fib_b4_qS3 st) + UInt64.ofNat 0))
def fib_b4_qS4 (st : Arm64State) : Arm64State := { fib_b4_qT3 st with pc := 4294968560 }
def fib_b4_qT4 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 2 (arm64_set_reg 0 (fib_b4_qS4 st) (mem_read_u64 (fib_b4_qS4 st).mem (fib_b4_qS4 st).sp.toNat)) (mem_read_u64 (fib_b4_qS4 st).mem ((fib_b4_qS4 st).sp + 8).toNat)) with sp := (fib_b4_qS4 st).sp + UInt64.ofNat 16 }
def fib_b4_qS5 (st : Arm64State) : Arm64State := { fib_b4_qT4 st with pc := 4294968564 }
def fib_b4_qT5 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b4_qS5 st) (arm64_reg 0 (fib_b4_qS5 st) - (arm64_reg 1 (fib_b4_qS5 st) <<< UInt64.ofNat 0)))
def fib_b4_qS6 (st : Arm64State) : Arm64State := { fib_b4_qT5 st with pc := 4294968568 }
def fib_b4_qT6 (st : Arm64State) : Arm64State :=
  { (fib_b4_qS6 st) with sp := ((fib_b4_qS6 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b4_qS6 st).mem ((fib_b4_qS6 st).sp - UInt64.ofNat 16).toNat (arm64_reg 0 (fib_b4_qS6 st))) (((fib_b4_qS6 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 31 (fib_b4_qS6 st)) }
def fib_b4_qS7 (st : Arm64State) : Arm64State := { fib_b4_qT6 st with pc := 4294968572 }
def fib_b4_qT7 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 31 (arm64_set_reg 0 (fib_b4_qS7 st) (mem_read_u64 (fib_b4_qS7 st).mem (fib_b4_qS7 st).sp.toNat)) (mem_read_u64 (fib_b4_qS7 st).mem ((fib_b4_qS7 st).sp + 8).toNat)) with sp := (fib_b4_qS7 st).sp + UInt64.ofNat 16 }
theorem fib_b4_self1 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 1 st = some (fib_b4_qS1 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b4_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b4_qT0, fib_b4_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968548 from by rw [hpc]]
  exact runs_zero fib_code (fib_b4_qS1 st)

theorem fib_b4_self2 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 2 st = some (fib_b4_qS2 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b4_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS1 st) (fib_b4_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]),
      show (fib_b4_qS1 st).pc + 4 = 4294968552 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b4_qS2 st)

theorem fib_b4_self3 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 3 st = some (fib_b4_qS3 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hpc2 : (fib_b4_qS2 st).pc = 4294968552 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b4_qS2 st) fib_code = some (fib_b4_qT2 st) :=
      fib_sr_74 (fib_b4_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b4_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS2 st) (fib_b4_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]),
      show (fib_b4_qS2 st).pc + 4 = 4294968556 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b4_qS3 st)

theorem fib_b4_self4 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 4 st = some (fib_b4_qS4 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hpc2 : (fib_b4_qS2 st).pc = 4294968552 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]
  have hpc3 : (fib_b4_qS3 st).pc = 4294968556 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b4_qS2 st) fib_code = some (fib_b4_qT2 st) :=
      fib_sr_74 (fib_b4_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b4_qS3 st) fib_code = some (fib_b4_qT3 st) :=
      fib_sr_75 (fib_b4_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b4_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS3 st) (fib_b4_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3]),
      show (fib_b4_qS3 st).pc + 4 = 4294968560 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b4_qS4 st)

theorem fib_b4_self5 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 5 st = some (fib_b4_qS5 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hpc2 : (fib_b4_qS2 st).pc = 4294968552 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]
  have hpc3 : (fib_b4_qS3 st).pc = 4294968556 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3]
  have hpc4 : (fib_b4_qS4 st).pc = 4294968560 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b4_qS2 st) fib_code = some (fib_b4_qT2 st) :=
      fib_sr_74 (fib_b4_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b4_qS3 st) fib_code = some (fib_b4_qT3 st) :=
      fib_sr_75 (fib_b4_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b4_qS4 st) fib_code = some (fib_b4_qT4 st) :=
      fib_sr_76 (fib_b4_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b4_self4 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS4 st) (fib_b4_qT4 st) fib_code 0 hs4 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4]),
      show (fib_b4_qS4 st).pc + 4 = 4294968564 from by rw [hpc4]]
  exact runs_zero fib_code (fib_b4_qS5 st)

theorem fib_b4_self6 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 6 st = some (fib_b4_qS6 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hpc2 : (fib_b4_qS2 st).pc = 4294968552 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]
  have hpc3 : (fib_b4_qS3 st).pc = 4294968556 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3]
  have hpc4 : (fib_b4_qS4 st).pc = 4294968560 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4]
  have hpc5 : (fib_b4_qS5 st).pc = 4294968564 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b4_qS2 st) fib_code = some (fib_b4_qT2 st) :=
      fib_sr_74 (fib_b4_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b4_qS3 st) fib_code = some (fib_b4_qT3 st) :=
      fib_sr_75 (fib_b4_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b4_qS4 st) fib_code = some (fib_b4_qT4 st) :=
      fib_sr_76 (fib_b4_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b4_qS5 st) fib_code = some (fib_b4_qT5 st) :=
      fib_sr_77 (fib_b4_qS5 st) (hpc5)
  rw [runs_append fib_code 5 1 st, fib_b4_self5 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS5 st) (fib_b4_qT5 st) fib_code 0 hs5 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5]),
      show (fib_b4_qS5 st).pc + 4 = 4294968568 from by rw [hpc5]]
  exact runs_zero fib_code (fib_b4_qS6 st)

theorem fib_b4_self7 (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 7 st = some (fib_b4_qS7 st) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hpc2 : (fib_b4_qS2 st).pc = 4294968552 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]
  have hpc3 : (fib_b4_qS3 st).pc = 4294968556 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3]
  have hpc4 : (fib_b4_qS4 st).pc = 4294968560 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4]
  have hpc5 : (fib_b4_qS5 st).pc = 4294968564 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5]
  have hpc6 : (fib_b4_qS6 st).pc = 4294968568 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b4_qS2 st) fib_code = some (fib_b4_qT2 st) :=
      fib_sr_74 (fib_b4_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b4_qS3 st) fib_code = some (fib_b4_qT3 st) :=
      fib_sr_75 (fib_b4_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b4_qS4 st) fib_code = some (fib_b4_qT4 st) :=
      fib_sr_76 (fib_b4_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b4_qS5 st) fib_code = some (fib_b4_qT5 st) :=
      fib_sr_77 (fib_b4_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b4_qS6 st) fib_code = some (fib_b4_qT6 st) :=
      fib_sr_78 (fib_b4_qS6 st) (hpc6)
  rw [runs_append fib_code 6 1 st, fib_b4_self6 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS6 st) (fib_b4_qT6 st) fib_code 0 hs6 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6]),
      show (fib_b4_qS6 st).pc + 4 = 4294968572 from by rw [hpc6]]
  exact runs_zero fib_code (fib_b4_qS7 st)

theorem fib_b4_runs (st : Arm64State) (hpc : st.pc = 4294968544) :
    arm64_runs fib_code 8 st = some ({ fib_b4_qT7 st with pc := 4294968576 }) := by
  have hpc0 : (fib_b4_qS0 st).pc = 4294968544 := by
    simp [fib_b4_qS0, hpc]
  have hpc1 : (fib_b4_qS1 st).pc = 4294968548 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qT0, fib_b4_qT1]
  have hpc2 : (fib_b4_qS2 st).pc = 4294968552 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2]
  have hpc3 : (fib_b4_qS3 st).pc = 4294968556 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3]
  have hpc4 : (fib_b4_qS4 st).pc = 4294968560 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4]
  have hpc5 : (fib_b4_qS5 st).pc = 4294968564 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5]
  have hpc6 : (fib_b4_qS6 st).pc = 4294968568 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6]
  have hpc7 : (fib_b4_qS7 st).pc = 4294968572 := by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7]
  have hs0 : arm64_step (fib_b4_qS0 st) fib_code = some (fib_b4_qT0 st) :=
      fib_sr_72 (fib_b4_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b4_qS1 st) fib_code = some (fib_b4_qT1 st) :=
      fib_sr_73 (fib_b4_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b4_qS2 st) fib_code = some (fib_b4_qT2 st) :=
      fib_sr_74 (fib_b4_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b4_qS3 st) fib_code = some (fib_b4_qT3 st) :=
      fib_sr_75 (fib_b4_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b4_qS4 st) fib_code = some (fib_b4_qT4 st) :=
      fib_sr_76 (fib_b4_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b4_qS5 st) fib_code = some (fib_b4_qT5 st) :=
      fib_sr_77 (fib_b4_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b4_qS6 st) fib_code = some (fib_b4_qT6 st) :=
      fib_sr_78 (fib_b4_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b4_qS7 st) fib_code = some (fib_b4_qT7 st) :=
      fib_sr_79 (fib_b4_qS7 st) (hpc7)
  rw [runs_append fib_code 7 1 st, fib_b4_self7 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b4_qS7 st) (fib_b4_qT7 st) fib_code 0 hs7 (by simp only [arm64_reg, arm64_set_reg, fib_b4_qS0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT0, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7]),
      show (fib_b4_qS7 st).pc + 4 = 4294968576 from by rw [hpc7]]
  exact runs_zero fib_code ({ fib_b4_qT7 st with pc := 4294968576 })

theorem fib_b4_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968544)
    (hexit : ∀ p ∈ [4294968544, 4294968548, 4294968552, 4294968556, 4294968560, 4294968564, 4294968568, 4294968572], p ≠ exit) :
    ∀ u < 8, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 ∨ u = 5 ∨ u = 6 ∨ u = 7 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968544 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968548 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b4_qS1 st) :=
      fib_b4_self1 st hpc
    have heq : some (fib_b4_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968548 ≠ exit
    exact hk
  · have hk : 4294968552 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b4_qS2 st) :=
      fib_b4_self2 st hpc
    have heq : some (fib_b4_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968552 ≠ exit
    exact hk
  · have hk : 4294968556 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b4_qS3 st) :=
      fib_b4_self3 st hpc
    have heq : some (fib_b4_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968556 ≠ exit
    exact hk
  · have hk : 4294968560 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b4_qS4 st) :=
      fib_b4_self4 st hpc
    have heq : some (fib_b4_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968560 ≠ exit
    exact hk
  · have hk : 4294968564 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 5 st = some (fib_b4_qS5 st) :=
      fib_b4_self5 st hpc
    have heq : some (fib_b4_qS5 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968564 ≠ exit
    exact hk
  · have hk : 4294968568 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 6 st = some (fib_b4_qS6 st) :=
      fib_b4_self6 st hpc
    have heq : some (fib_b4_qS6 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968568 ≠ exit
    exact hk
  · have hk : 4294968572 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 7 st = some (fib_b4_qS7 st) :=
      fib_b4_self7 st hpc
    have heq : some (fib_b4_qS7 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968572 ≠ exit
    exact hk

/-- Block 5: start=0x100000504 kind=bl (10 instructions, run=9) -/
def fib_b5_qS0 (st : Arm64State) : Arm64State := st
def fib_b5_qT0 (st : Arm64State) : Arm64State :=
  { (fib_b5_qS0 st) with sp := ((fib_b5_qS0 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b5_qS0 st).mem ((fib_b5_qS0 st).sp - UInt64.ofNat 16).toNat (arm64_reg 0 (fib_b5_qS0 st))) (((fib_b5_qS0 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 (fib_b5_qS0 st)) }
def fib_b5_qS1 (st : Arm64State) : Arm64State := { fib_b5_qT0 st with pc := 4294968584 }
def fib_b5_qT1 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b5_qS1 st) (arm64_reg 19 (fib_b5_qS1 st) + UInt64.ofNat 0))
def fib_b5_qS2 (st : Arm64State) : Arm64State := { fib_b5_qT1 st with pc := 4294968588 }
def fib_b5_qT2 (st : Arm64State) : Arm64State :=
  { (fib_b5_qS2 st) with sp := ((fib_b5_qS2 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b5_qS2 st).mem ((fib_b5_qS2 st).sp - UInt64.ofNat 16).toNat (arm64_reg 0 (fib_b5_qS2 st))) (((fib_b5_qS2 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 2 (fib_b5_qS2 st)) }
def fib_b5_qS3 (st : Arm64State) : Arm64State := { fib_b5_qT2 st with pc := 4294968592 }
def fib_b5_qT3 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b5_qS3 st) (UInt64.ofNat 2))
def fib_b5_qS4 (st : Arm64State) : Arm64State := { fib_b5_qT3 st with pc := 4294968596 }
def fib_b5_qT4 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 1 (fib_b5_qS4 st) (arm64_reg 0 (fib_b5_qS4 st) + UInt64.ofNat 0))
def fib_b5_qS5 (st : Arm64State) : Arm64State := { fib_b5_qT4 st with pc := 4294968600 }
def fib_b5_qT5 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 2 (arm64_set_reg 0 (fib_b5_qS5 st) (mem_read_u64 (fib_b5_qS5 st).mem (fib_b5_qS5 st).sp.toNat)) (mem_read_u64 (fib_b5_qS5 st).mem ((fib_b5_qS5 st).sp + 8).toNat)) with sp := (fib_b5_qS5 st).sp + UInt64.ofNat 16 }
def fib_b5_qS6 (st : Arm64State) : Arm64State := { fib_b5_qT5 st with pc := 4294968604 }
def fib_b5_qT6 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b5_qS6 st) (arm64_reg 0 (fib_b5_qS6 st) - (arm64_reg 1 (fib_b5_qS6 st) <<< UInt64.ofNat 0)))
def fib_b5_qS7 (st : Arm64State) : Arm64State := { fib_b5_qT6 st with pc := 4294968608 }
def fib_b5_qT7 (st : Arm64State) : Arm64State :=
  { (fib_b5_qS7 st) with sp := ((fib_b5_qS7 st).sp - UInt64.ofNat 16), mem := mem_write_u64 (mem_write_u64 (fib_b5_qS7 st).mem ((fib_b5_qS7 st).sp - UInt64.ofNat 16).toNat (arm64_reg 0 (fib_b5_qS7 st))) (((fib_b5_qS7 st).sp - UInt64.ofNat 16) + 8).toNat (arm64_reg 31 (fib_b5_qS7 st)) }
def fib_b5_qS8 (st : Arm64State) : Arm64State := { fib_b5_qT7 st with pc := 4294968612 }
def fib_b5_qT8 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 31 (arm64_set_reg 0 (fib_b5_qS8 st) (mem_read_u64 (fib_b5_qS8 st).mem (fib_b5_qS8 st).sp.toNat)) (mem_read_u64 (fib_b5_qS8 st).mem ((fib_b5_qS8 st).sp + 8).toNat)) with sp := (fib_b5_qS8 st).sp + UInt64.ofNat 16 }
theorem fib_b5_self1 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 1 st = some (fib_b5_qS1 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b5_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b5_qT0, fib_b5_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968584 from by rw [hpc]]
  exact runs_zero fib_code (fib_b5_qS1 st)

theorem fib_b5_self2 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 2 st = some (fib_b5_qS2 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b5_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS1 st) (fib_b5_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]),
      show (fib_b5_qS1 st).pc + 4 = 4294968588 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b5_qS2 st)

theorem fib_b5_self3 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 3 st = some (fib_b5_qS3 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b5_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS2 st) (fib_b5_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]),
      show (fib_b5_qS2 st).pc + 4 = 4294968592 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b5_qS3 st)

theorem fib_b5_self4 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 4 st = some (fib_b5_qS4 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hpc3 : (fib_b5_qS3 st).pc = 4294968592 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b5_qS3 st) fib_code = some (fib_b5_qT3 st) :=
      fib_sr_84 (fib_b5_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b5_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS3 st) (fib_b5_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]),
      show (fib_b5_qS3 st).pc + 4 = 4294968596 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b5_qS4 st)

theorem fib_b5_self5 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 5 st = some (fib_b5_qS5 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hpc3 : (fib_b5_qS3 st).pc = 4294968592 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]
  have hpc4 : (fib_b5_qS4 st).pc = 4294968596 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b5_qS3 st) fib_code = some (fib_b5_qT3 st) :=
      fib_sr_84 (fib_b5_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b5_qS4 st) fib_code = some (fib_b5_qT4 st) :=
      fib_sr_85 (fib_b5_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b5_self4 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS4 st) (fib_b5_qT4 st) fib_code 0 hs4 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4]),
      show (fib_b5_qS4 st).pc + 4 = 4294968600 from by rw [hpc4]]
  exact runs_zero fib_code (fib_b5_qS5 st)

theorem fib_b5_self6 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 6 st = some (fib_b5_qS6 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hpc3 : (fib_b5_qS3 st).pc = 4294968592 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]
  have hpc4 : (fib_b5_qS4 st).pc = 4294968596 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4]
  have hpc5 : (fib_b5_qS5 st).pc = 4294968600 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b5_qS3 st) fib_code = some (fib_b5_qT3 st) :=
      fib_sr_84 (fib_b5_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b5_qS4 st) fib_code = some (fib_b5_qT4 st) :=
      fib_sr_85 (fib_b5_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b5_qS5 st) fib_code = some (fib_b5_qT5 st) :=
      fib_sr_86 (fib_b5_qS5 st) (hpc5)
  rw [runs_append fib_code 5 1 st, fib_b5_self5 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS5 st) (fib_b5_qT5 st) fib_code 0 hs5 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5]),
      show (fib_b5_qS5 st).pc + 4 = 4294968604 from by rw [hpc5]]
  exact runs_zero fib_code (fib_b5_qS6 st)

theorem fib_b5_self7 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 7 st = some (fib_b5_qS7 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hpc3 : (fib_b5_qS3 st).pc = 4294968592 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]
  have hpc4 : (fib_b5_qS4 st).pc = 4294968596 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4]
  have hpc5 : (fib_b5_qS5 st).pc = 4294968600 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5]
  have hpc6 : (fib_b5_qS6 st).pc = 4294968604 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b5_qS3 st) fib_code = some (fib_b5_qT3 st) :=
      fib_sr_84 (fib_b5_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b5_qS4 st) fib_code = some (fib_b5_qT4 st) :=
      fib_sr_85 (fib_b5_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b5_qS5 st) fib_code = some (fib_b5_qT5 st) :=
      fib_sr_86 (fib_b5_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b5_qS6 st) fib_code = some (fib_b5_qT6 st) :=
      fib_sr_87 (fib_b5_qS6 st) (hpc6)
  rw [runs_append fib_code 6 1 st, fib_b5_self6 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS6 st) (fib_b5_qT6 st) fib_code 0 hs6 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6]),
      show (fib_b5_qS6 st).pc + 4 = 4294968608 from by rw [hpc6]]
  exact runs_zero fib_code (fib_b5_qS7 st)

theorem fib_b5_self8 (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 8 st = some (fib_b5_qS8 st) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hpc3 : (fib_b5_qS3 st).pc = 4294968592 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]
  have hpc4 : (fib_b5_qS4 st).pc = 4294968596 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4]
  have hpc5 : (fib_b5_qS5 st).pc = 4294968600 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5]
  have hpc6 : (fib_b5_qS6 st).pc = 4294968604 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6]
  have hpc7 : (fib_b5_qS7 st).pc = 4294968608 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b5_qS3 st) fib_code = some (fib_b5_qT3 st) :=
      fib_sr_84 (fib_b5_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b5_qS4 st) fib_code = some (fib_b5_qT4 st) :=
      fib_sr_85 (fib_b5_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b5_qS5 st) fib_code = some (fib_b5_qT5 st) :=
      fib_sr_86 (fib_b5_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b5_qS6 st) fib_code = some (fib_b5_qT6 st) :=
      fib_sr_87 (fib_b5_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b5_qS7 st) fib_code = some (fib_b5_qT7 st) :=
      fib_sr_88 (fib_b5_qS7 st) (hpc7)
  rw [runs_append fib_code 7 1 st, fib_b5_self7 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS7 st) (fib_b5_qT7 st) fib_code 0 hs7 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7]),
      show (fib_b5_qS7 st).pc + 4 = 4294968612 from by rw [hpc7]]
  exact runs_zero fib_code (fib_b5_qS8 st)

theorem fib_b5_runs (st : Arm64State) (hpc : st.pc = 4294968580) :
    arm64_runs fib_code 9 st = some ({ fib_b5_qT8 st with pc := 4294968616 }) := by
  have hpc0 : (fib_b5_qS0 st).pc = 4294968580 := by
    simp [fib_b5_qS0, hpc]
  have hpc1 : (fib_b5_qS1 st).pc = 4294968584 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qT0, fib_b5_qT1]
  have hpc2 : (fib_b5_qS2 st).pc = 4294968588 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2]
  have hpc3 : (fib_b5_qS3 st).pc = 4294968592 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3]
  have hpc4 : (fib_b5_qS4 st).pc = 4294968596 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4]
  have hpc5 : (fib_b5_qS5 st).pc = 4294968600 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5]
  have hpc6 : (fib_b5_qS6 st).pc = 4294968604 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6]
  have hpc7 : (fib_b5_qS7 st).pc = 4294968608 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7]
  have hpc8 : (fib_b5_qS8 st).pc = 4294968612 := by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8]
  have hs0 : arm64_step (fib_b5_qS0 st) fib_code = some (fib_b5_qT0 st) :=
      fib_sr_81 (fib_b5_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b5_qS1 st) fib_code = some (fib_b5_qT1 st) :=
      fib_sr_82 (fib_b5_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b5_qS2 st) fib_code = some (fib_b5_qT2 st) :=
      fib_sr_83 (fib_b5_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b5_qS3 st) fib_code = some (fib_b5_qT3 st) :=
      fib_sr_84 (fib_b5_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b5_qS4 st) fib_code = some (fib_b5_qT4 st) :=
      fib_sr_85 (fib_b5_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b5_qS5 st) fib_code = some (fib_b5_qT5 st) :=
      fib_sr_86 (fib_b5_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b5_qS6 st) fib_code = some (fib_b5_qT6 st) :=
      fib_sr_87 (fib_b5_qS6 st) (hpc6)
  have hs7 : arm64_step (fib_b5_qS7 st) fib_code = some (fib_b5_qT7 st) :=
      fib_sr_88 (fib_b5_qS7 st) (hpc7)
  have hs8 : arm64_step (fib_b5_qS8 st) fib_code = some (fib_b5_qT8 st) :=
      fib_sr_89 (fib_b5_qS8 st) (hpc8)
  rw [runs_append fib_code 8 1 st, fib_b5_self8 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b5_qS8 st) (fib_b5_qT8 st) fib_code 0 hs8 (by simp only [arm64_reg, arm64_set_reg, fib_b5_qS0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT0, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8]),
      show (fib_b5_qS8 st).pc + 4 = 4294968616 from by rw [hpc8]]
  exact runs_zero fib_code ({ fib_b5_qT8 st with pc := 4294968616 })

theorem fib_b5_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968580)
    (hexit : ∀ p ∈ [4294968580, 4294968584, 4294968588, 4294968592, 4294968596, 4294968600, 4294968604, 4294968608, 4294968612], p ≠ exit) :
    ∀ u < 9, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 ∨ u = 5 ∨ u = 6 ∨ u = 7 ∨ u = 8 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968580 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968584 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b5_qS1 st) :=
      fib_b5_self1 st hpc
    have heq : some (fib_b5_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968584 ≠ exit
    exact hk
  · have hk : 4294968588 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b5_qS2 st) :=
      fib_b5_self2 st hpc
    have heq : some (fib_b5_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968588 ≠ exit
    exact hk
  · have hk : 4294968592 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b5_qS3 st) :=
      fib_b5_self3 st hpc
    have heq : some (fib_b5_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968592 ≠ exit
    exact hk
  · have hk : 4294968596 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b5_qS4 st) :=
      fib_b5_self4 st hpc
    have heq : some (fib_b5_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968596 ≠ exit
    exact hk
  · have hk : 4294968600 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 5 st = some (fib_b5_qS5 st) :=
      fib_b5_self5 st hpc
    have heq : some (fib_b5_qS5 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968600 ≠ exit
    exact hk
  · have hk : 4294968604 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 6 st = some (fib_b5_qS6 st) :=
      fib_b5_self6 st hpc
    have heq : some (fib_b5_qS6 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968604 ≠ exit
    exact hk
  · have hk : 4294968608 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 7 st = some (fib_b5_qS7 st) :=
      fib_b5_self7 st hpc
    have heq : some (fib_b5_qS7 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968608 ≠ exit
    exact hk
  · have hk : 4294968612 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 8 st = some (fib_b5_qS8 st) :=
      fib_b5_self8 st hpc
    have heq : some (fib_b5_qS8 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968612 ≠ exit
    exact hk

/-- Block 6: start=0x10000052c kind=ret (7 instructions, run=7) -/
def fib_b6_qS0 (st : Arm64State) : Arm64State := st
def fib_b6_qT0 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 1 (fib_b6_qS0 st) (arm64_reg 0 (fib_b6_qS0 st) + UInt64.ofNat 0))
def fib_b6_qS1 (st : Arm64State) : Arm64State := { fib_b6_qT0 st with pc := 4294968624 }
def fib_b6_qT1 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 2 (arm64_set_reg 0 (fib_b6_qS1 st) (mem_read_u64 (fib_b6_qS1 st).mem (fib_b6_qS1 st).sp.toNat)) (mem_read_u64 (fib_b6_qS1 st).mem ((fib_b6_qS1 st).sp + 8).toNat)) with sp := (fib_b6_qS1 st).sp + UInt64.ofNat 16 }
def fib_b6_qS2 (st : Arm64State) : Arm64State := { fib_b6_qT1 st with pc := 4294968628 }
def fib_b6_qT2 (st : Arm64State) : Arm64State :=
  (arm64_set_reg 0 (fib_b6_qS2 st) (arm64_reg 0 (fib_b6_qS2 st) + (arm64_reg 1 (fib_b6_qS2 st) <<< UInt64.ofNat 0)))
def fib_b6_qS3 (st : Arm64State) : Arm64State := { fib_b6_qT2 st with pc := 4294968632 }
def fib_b6_qT3 (st : Arm64State) : Arm64State :=
  { (fib_b6_qS3 st) with sp := ((fib_b6_qS3 st).sp + UInt64.ofNat 131072) }
def fib_b6_qS4 (st : Arm64State) : Arm64State := { fib_b6_qT3 st with pc := 4294968636 }
def fib_b6_qT4 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 20 (arm64_set_reg 19 (fib_b6_qS4 st) (mem_read_u64 (fib_b6_qS4 st).mem (fib_b6_qS4 st).sp.toNat)) (mem_read_u64 (fib_b6_qS4 st).mem ((fib_b6_qS4 st).sp + 8).toNat)) with sp := (fib_b6_qS4 st).sp + UInt64.ofNat 16 }
def fib_b6_qS5 (st : Arm64State) : Arm64State := { fib_b6_qT4 st with pc := 4294968640 }
def fib_b6_qT5 (st : Arm64State) : Arm64State :=
  { (arm64_set_reg 30 (arm64_set_reg 29 (fib_b6_qS5 st) (mem_read_u64 (fib_b6_qS5 st).mem (fib_b6_qS5 st).sp.toNat)) (mem_read_u64 (fib_b6_qS5 st).mem ((fib_b6_qS5 st).sp + 8).toNat)) with sp := (fib_b6_qS5 st).sp + UInt64.ofNat 16 }
def fib_b6_qS6 (st : Arm64State) : Arm64State := { fib_b6_qT5 st with pc := 4294968644 }
def fib_b6_qT6 (st : Arm64State) : Arm64State :=
  { (fib_b6_qS6 st) with pc := (fib_b6_qS6 st).x30.toNat }
theorem fib_b6_self1 (st : Arm64State) (hpc : st.pc = 4294968620) :
    arm64_runs fib_code 1 st = some (fib_b6_qS1 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  rw [runs_cons_seq st (fib_b6_qT0 st) fib_code 0 hs0 (by first | (simp only [fib_b6_qT0, fib_b6_qS0] <;> done) | rfl),
      show st.pc + 4 = 4294968624 from by rw [hpc]]
  exact runs_zero fib_code (fib_b6_qS1 st)

theorem fib_b6_self2 (st : Arm64State) (hpc : st.pc = 4294968620) :
    arm64_runs fib_code 2 st = some (fib_b6_qS2 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hpc1 : (fib_b6_qS1 st).pc = 4294968624 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b6_qS1 st) fib_code = some (fib_b6_qT1 st) :=
      fib_sr_92 (fib_b6_qS1 st) (hpc1)
  rw [runs_append fib_code 1 1 st, fib_b6_self1 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b6_qS1 st) (fib_b6_qT1 st) fib_code 0 hs1 (by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]),
      show (fib_b6_qS1 st).pc + 4 = 4294968628 from by rw [hpc1]]
  exact runs_zero fib_code (fib_b6_qS2 st)

theorem fib_b6_self3 (st : Arm64State) (hpc : st.pc = 4294968620) :
    arm64_runs fib_code 3 st = some (fib_b6_qS3 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hpc1 : (fib_b6_qS1 st).pc = 4294968624 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]
  have hpc2 : (fib_b6_qS2 st).pc = 4294968628 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b6_qS1 st) fib_code = some (fib_b6_qT1 st) :=
      fib_sr_92 (fib_b6_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b6_qS2 st) fib_code = some (fib_b6_qT2 st) :=
      fib_sr_93 (fib_b6_qS2 st) (hpc2)
  rw [runs_append fib_code 2 1 st, fib_b6_self2 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b6_qS2 st) (fib_b6_qT2 st) fib_code 0 hs2 (by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2]),
      show (fib_b6_qS2 st).pc + 4 = 4294968632 from by rw [hpc2]]
  exact runs_zero fib_code (fib_b6_qS3 st)

theorem fib_b6_self4 (st : Arm64State) (hpc : st.pc = 4294968620) :
    arm64_runs fib_code 4 st = some (fib_b6_qS4 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hpc1 : (fib_b6_qS1 st).pc = 4294968624 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]
  have hpc2 : (fib_b6_qS2 st).pc = 4294968628 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2]
  have hpc3 : (fib_b6_qS3 st).pc = 4294968632 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b6_qS1 st) fib_code = some (fib_b6_qT1 st) :=
      fib_sr_92 (fib_b6_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b6_qS2 st) fib_code = some (fib_b6_qT2 st) :=
      fib_sr_93 (fib_b6_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b6_qS3 st) fib_code = some (fib_b6_qT3 st) :=
      fib_sr_94 (fib_b6_qS3 st) (hpc3)
  rw [runs_append fib_code 3 1 st, fib_b6_self3 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b6_qS3 st) (fib_b6_qT3 st) fib_code 0 hs3 (by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3]),
      show (fib_b6_qS3 st).pc + 4 = 4294968636 from by rw [hpc3]]
  exact runs_zero fib_code (fib_b6_qS4 st)

theorem fib_b6_self5 (st : Arm64State) (hpc : st.pc = 4294968620) :
    arm64_runs fib_code 5 st = some (fib_b6_qS5 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hpc1 : (fib_b6_qS1 st).pc = 4294968624 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]
  have hpc2 : (fib_b6_qS2 st).pc = 4294968628 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2]
  have hpc3 : (fib_b6_qS3 st).pc = 4294968632 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3]
  have hpc4 : (fib_b6_qS4 st).pc = 4294968636 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b6_qS1 st) fib_code = some (fib_b6_qT1 st) :=
      fib_sr_92 (fib_b6_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b6_qS2 st) fib_code = some (fib_b6_qT2 st) :=
      fib_sr_93 (fib_b6_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b6_qS3 st) fib_code = some (fib_b6_qT3 st) :=
      fib_sr_94 (fib_b6_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b6_qS4 st) fib_code = some (fib_b6_qT4 st) :=
      fib_sr_95 (fib_b6_qS4 st) (hpc4)
  rw [runs_append fib_code 4 1 st, fib_b6_self4 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b6_qS4 st) (fib_b6_qT4 st) fib_code 0 hs4 (by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4]),
      show (fib_b6_qS4 st).pc + 4 = 4294968640 from by rw [hpc4]]
  exact runs_zero fib_code (fib_b6_qS5 st)

theorem fib_b6_self6 (st : Arm64State) (hpc : st.pc = 4294968620) :
    arm64_runs fib_code 6 st = some (fib_b6_qS6 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hpc1 : (fib_b6_qS1 st).pc = 4294968624 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]
  have hpc2 : (fib_b6_qS2 st).pc = 4294968628 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2]
  have hpc3 : (fib_b6_qS3 st).pc = 4294968632 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3]
  have hpc4 : (fib_b6_qS4 st).pc = 4294968636 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4]
  have hpc5 : (fib_b6_qS5 st).pc = 4294968640 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b6_qS1 st) fib_code = some (fib_b6_qT1 st) :=
      fib_sr_92 (fib_b6_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b6_qS2 st) fib_code = some (fib_b6_qT2 st) :=
      fib_sr_93 (fib_b6_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b6_qS3 st) fib_code = some (fib_b6_qT3 st) :=
      fib_sr_94 (fib_b6_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b6_qS4 st) fib_code = some (fib_b6_qT4 st) :=
      fib_sr_95 (fib_b6_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b6_qS5 st) fib_code = some (fib_b6_qT5 st) :=
      fib_sr_96 (fib_b6_qS5 st) (hpc5)
  rw [runs_append fib_code 5 1 st, fib_b6_self5 st hpc]
  simp only []
  rw [runs_cons_seq (fib_b6_qS5 st) (fib_b6_qT5 st) fib_code 0 hs5 (by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5]),
      show (fib_b6_qS5 st).pc + 4 = 4294968644 from by rw [hpc5]]
  exact runs_zero fib_code (fib_b6_qS6 st)

theorem fib_b6_runs (st : Arm64State) (hpc : st.pc = 4294968620)
    (hjump : (fib_b6_qS6 st).x30.toNat ≠ 4294968644) :
    arm64_runs fib_code 7 st = some (fib_b6_qT6 st) := by
  have hpc0 : (fib_b6_qS0 st).pc = 4294968620 := by
    simp [fib_b6_qS0, hpc]
  have hpc1 : (fib_b6_qS1 st).pc = 4294968624 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qT0, fib_b6_qT1]
  have hpc2 : (fib_b6_qS2 st).pc = 4294968628 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2]
  have hpc3 : (fib_b6_qS3 st).pc = 4294968632 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3]
  have hpc4 : (fib_b6_qS4 st).pc = 4294968636 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4]
  have hpc5 : (fib_b6_qS5 st).pc = 4294968640 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5]
  have hpc6 : (fib_b6_qS6 st).pc = 4294968644 := by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6]
  have hs0 : arm64_step (fib_b6_qS0 st) fib_code = some (fib_b6_qT0 st) :=
      fib_sr_91 (fib_b6_qS0 st) (hpc0)
  have hs1 : arm64_step (fib_b6_qS1 st) fib_code = some (fib_b6_qT1 st) :=
      fib_sr_92 (fib_b6_qS1 st) (hpc1)
  have hs2 : arm64_step (fib_b6_qS2 st) fib_code = some (fib_b6_qT2 st) :=
      fib_sr_93 (fib_b6_qS2 st) (hpc2)
  have hs3 : arm64_step (fib_b6_qS3 st) fib_code = some (fib_b6_qT3 st) :=
      fib_sr_94 (fib_b6_qS3 st) (hpc3)
  have hs4 : arm64_step (fib_b6_qS4 st) fib_code = some (fib_b6_qT4 st) :=
      fib_sr_95 (fib_b6_qS4 st) (hpc4)
  have hs5 : arm64_step (fib_b6_qS5 st) fib_code = some (fib_b6_qT5 st) :=
      fib_sr_96 (fib_b6_qS5 st) (hpc5)
  have hs6 : arm64_step (fib_b6_qS6 st) fib_code = some (fib_b6_qT6 st) :=
      fib_sr_97 (fib_b6_qS6 st) (hpc6)
  rw [runs_append fib_code 6 1 st, fib_b6_self6 st hpc]
  simp only []
  rw [runs_cons_jump (fib_b6_qS6 st) (fib_b6_qT6 st) fib_code 0 hs6
      (by rw [show (fib_b6_qT6 st).pc = (fib_b6_qS6 st).x30.toNat from by simp only [arm64_reg, arm64_set_reg, fib_b6_qS0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT0, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6]]; exact hjump)]
  exact runs_zero fib_code (fib_b6_qT6 st)

theorem fib_b6_mid (exit : Nat) (st : Arm64State) (hpc : st.pc = 4294968620)
    (hexit : ∀ p ∈ [4294968620, 4294968624, 4294968628, 4294968632, 4294968636, 4294968640, 4294968644], p ≠ exit) :
    ∀ u < 7, ∀ su, arm64_runs fib_code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  have hcases : u = 0 ∨ u = 1 ∨ u = 2 ∨ u = 3 ∨ u = 4 ∨ u = 5 ∨ u = 6 := by omega
  rcases hcases with rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · have hk : 4294968620 ≠ exit := work_mid_hk hexit (by simp)
    simp [runs_zero] at hsu
    subst su
    rw [hpc]
    exact hk
  · have hk : 4294968624 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 1 st = some (fib_b6_qS1 st) :=
      fib_b6_self1 st hpc
    have heq : some (fib_b6_qS1 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968624 ≠ exit
    exact hk
  · have hk : 4294968628 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 2 st = some (fib_b6_qS2 st) :=
      fib_b6_self2 st hpc
    have heq : some (fib_b6_qS2 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968628 ≠ exit
    exact hk
  · have hk : 4294968632 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 3 st = some (fib_b6_qS3 st) :=
      fib_b6_self3 st hpc
    have heq : some (fib_b6_qS3 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968632 ≠ exit
    exact hk
  · have hk : 4294968636 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 4 st = some (fib_b6_qS4 st) :=
      fib_b6_self4 st hpc
    have heq : some (fib_b6_qS4 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968636 ≠ exit
    exact hk
  · have hk : 4294968640 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 5 st = some (fib_b6_qS5 st) :=
      fib_b6_self5 st hpc
    have heq : some (fib_b6_qS5 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968640 ≠ exit
    exact hk
  · have hk : 4294968644 ≠ exit := work_mid_hk hexit (by simp)
    have hself : arm64_runs fib_code 6 st = some (fib_b6_qS6 st) :=
      fib_b6_self6 st hpc
    have heq : some (fib_b6_qS6 st) = some su := hself.symm.trans hsu
    injection heq with hq
    subst hq
    change 4294968644 ≠ exit
    exact hk


open Refine

def fib_blk_0 : Block :=
  { entry_pc := 4294968404, pcs := [4294968404, 4294968408, 4294968412, 4294968416, 4294968420, 4294968424, 4294968428, 4294968432, 4294968436], step := fun st => ({ fib_b0_qT8 st with pc := 4294968440 }) }
theorem fib_blk_0_cert : BlockCert fib_code fib_blk_0 := by
  refine ⟨?_⟩
  intro st hpc
  exact fib_b0_runs st hpc

def fib_blk_1 : Block :=
  { entry_pc := 4294968444, pcs := [4294968444, 4294968448, 4294968452, 4294968456, 4294968460, 4294968464, 4294968468, 4294968472, 4294968476, 4294968480, 4294968484], step := fun st => ({ fib_b1_qT10 st with pc := 4294968488 }) }
theorem fib_blk_1_cert : BlockCert fib_code fib_blk_1 := by
  refine ⟨?_⟩
  intro st hpc
  exact fib_b1_runs st hpc

def fib_blk_2 : Block :=
  { entry_pc := 4294968488, pcs := [4294968488, 4294968492, 4294968496, 4294968500, 4294968504, 4294968508, 4294968512], step := fun st => ({ fib_b2_qT6 st with pc := 4294968516 }) }
theorem fib_blk_2_cert : BlockCert fib_code fib_blk_2 := by
  refine ⟨?_⟩
  intro st hpc
  exact fib_b2_runs st hpc

def fib_blk_4 : Block :=
  { entry_pc := 4294968544, pcs := [4294968544, 4294968548, 4294968552, 4294968556, 4294968560, 4294968564, 4294968568, 4294968572], step := fun st => ({ fib_b4_qT7 st with pc := 4294968576 }) }
theorem fib_blk_4_cert : BlockCert fib_code fib_blk_4 := by
  refine ⟨?_⟩
  intro st hpc
  exact fib_b4_runs st hpc

def fib_blk_5 : Block :=
  { entry_pc := 4294968580, pcs := [4294968580, 4294968584, 4294968588, 4294968592, 4294968596, 4294968600, 4294968604, 4294968608, 4294968612], step := fun st => ({ fib_b5_qT8 st with pc := 4294968616 }) }
theorem fib_blk_5_cert : BlockCert fib_code fib_blk_5 := by
  refine ⟨?_⟩
  intro st hpc
  exact fib_b5_runs st hpc

def fib_prog : Prog :=
  { fname := "fib", code := fib_code, base := 4294968256, entry := 4294968404,
    exit := 4294970679, fuel := fun n => (200000 + 1000 * 2 ^ n.toNat), blocks := [fib_blk_0, fib_blk_1, fib_blk_2, fib_blk_4, fib_blk_5],
    rets := [4294968536, 4294968644, 4294968828] }

set_option maxHeartbeats 2000000 in
theorem fib_contract (fuel : Nat) (arg : UInt64) (st : Arm64State)
    (hfuel : 106 + 512 * 2 ^ arg.toNat ≤ fuel)
    (hpc : st.pc = 4294968404) (hx0 : st.x0 = arg)
    (hbnd : FrameBound 131216 st arg)
    (hx30ret : ∀ pc, pc ∈ fib_prog.rets → pc ≠ st.x30.toNat) :
    Post fib_prog fuel (mojo arg) st arg := by
  refine contract_sound_tree fib_prog mojo 106 512 131216 ?_ ?_ arg st fuel hfuel hpc hx0 hbnd hx30ret
  · intro fuel st hb hpc hlt2 hbnd hx30ret
    have hacc0 : arm64_runs fib_code 0 st = some st := runs_zero fib_code st
    have hcert_0 : arm64_runs fib_code 9 (st) = some (({ fib_b0_qT8 (st) with pc := 4294968440 })) := fib_b0_runs (st) hpc
    have hrun_ex_0 : ∃ s : Arm64State, arm64_runs fib_code 9 (st) = some s := ⟨(({ fib_b0_qT8 (st) with pc := 4294968440 })), hcert_0⟩
    rcases hrun_ex_0 with ⟨s_0, hrun_0⟩
    have hsid_0 : s_0 = (({ fib_b0_qT8 (st) with pc := 4294968440 })) := by injection hrun_0.symm.trans hcert_0
    have ha_0 : arm64_runs fib_code (0 + 9) st = some s_0 := by
      rw [runs_append_some fib_code (0) 9 st (st) hacc0]
      exact hrun_0
    have hmd_0_block := runs_avoid_append fib_code (0) (9) 4294970679 st (st) hacc0 (by intro u hu; omega) (fib_b0_mid 4294970679 (st) hpc (by simp))
    have hpc_0 : (s_0).pc = 4294968440 := by rw [hsid_0]
    have hs_0 : arm64_step (s_0) fib_code = some ({ s_0 with pc := 4294968444 }) := by
      have hsr := fib_sr_46 (s_0) hpc_0
      rw [hsr]
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      all_goals try (simp +decide only [h8, hsid_0, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, u64_sub_zero, arm64_flag_ge, hx0])
      all_goals try rfl
      all_goals try (simp only [fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, arm64_reg, arm64_set_reg, arm64_subs_flags, arm64_matches_condition, Arm64State.init])
      all_goals try rfl
      all_goals try grind
      all_goals try (simp (disch := decide) [mem_read_after_write_u64, mem_read_after_write_u64_ne, mem_read_two_writes_same])
      all_goals try native_decide
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-cbz-condition
    have hr_0 : arm64_runs fib_code 1 (s_0) = some ({ s_0 with pc := 4294968444 }) := by
      rw [runs_cons_jump (s_0) ({ s_0 with pc := 4294968444 }) fib_code 0 hs_0 (by dsimp only; rw [hpc_0]; decide)]
      exact runs_zero fib_code _
    have ha_0b : arm64_runs fib_code ((0 + 9) + 1) st = some ({ s_0 with pc := 4294968444 }) := by
      rw [runs_append_some fib_code ((0 + 9)) 1 st (s_0) ha_0]
      exact hr_0
    have hmd_0_cbz := runs_avoid_append fib_code ((0 + 9)) (1) 4294970679 st (s_0) ha_0 hmd_0_block (runs_avoid_one fib_code (s_0) 4294970679 (by rw [hpc_0]; decide))
    have hcert_1 : arm64_runs fib_code 11 (({ s_0 with pc := 4294968444 })) = some (({ fib_b1_qT10 (({ s_0 with pc := 4294968444 })) with pc := 4294968488 })) := fib_b1_runs (({ s_0 with pc := 4294968444 })) (by rfl)
    have hrun_ex_1 : ∃ s : Arm64State, arm64_runs fib_code 11 (({ s_0 with pc := 4294968444 })) = some s := ⟨(({ fib_b1_qT10 (({ s_0 with pc := 4294968444 })) with pc := 4294968488 })), hcert_1⟩
    rcases hrun_ex_1 with ⟨s_1, hrun_1⟩
    have hsid_1 : s_1 = (({ fib_b1_qT10 (({ s_0 with pc := 4294968444 })) with pc := 4294968488 })) := by injection hrun_1.symm.trans hcert_1
    have ha_1 : arm64_runs fib_code (((0 + 9) + 1) + 11) st = some s_1 := by
      rw [runs_append_some fib_code (((0 + 9) + 1)) 11 st (({ s_0 with pc := 4294968444 })) ha_0b]
      exact hrun_1
    have hmd_1_block := runs_avoid_append fib_code (((0 + 9) + 1)) (11) 4294970679 st (({ s_0 with pc := 4294968444 })) ha_0b hmd_0_cbz (fib_b1_mid 4294970679 (({ s_0 with pc := 4294968444 })) (by rfl) (by simp))
    have hpc_1 : (s_1).pc = 4294968488 := by rw [hsid_1]
    have hcert_2 : arm64_runs fib_code 7 (s_1) = some (({ fib_b2_qT6 (s_1) with pc := 4294968516 })) := fib_b2_runs (s_1) hpc_1
    have hrun_ex_2 : ∃ s : Arm64State, arm64_runs fib_code 7 (s_1) = some s := ⟨(({ fib_b2_qT6 (s_1) with pc := 4294968516 })), hcert_2⟩
    rcases hrun_ex_2 with ⟨s_2, hrun_2⟩
    have hsid_2 : s_2 = (({ fib_b2_qT6 (s_1) with pc := 4294968516 })) := by injection hrun_2.symm.trans hcert_2
    have ha_2 : arm64_runs fib_code ((((0 + 9) + 1) + 11) + 7) st = some s_2 := by
      rw [runs_append_some fib_code ((((0 + 9) + 1) + 11)) 7 st (s_1) ha_1]
      exact hrun_2
    have hmd_2_block := runs_avoid_append fib_code ((((0 + 9) + 1) + 11)) (7) 4294970679 st (s_1) ha_1 hmd_1_block (fib_b2_mid 4294970679 (s_1) hpc_1 (by simp))
    have hpc_2 : (s_2).pc = 4294968516 := by rw [hsid_2]
    have hs_2 : arm64_step (s_2) fib_code = some ({ s_2 with pc := 4294968520 }) := by
      have hsr := fib_sr_65 (s_2) hpc_2
      rw [hsr]
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      all_goals try (simp +decide only [h8, hsid_0, hsid_1, hsid_2, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b1_qS0, fib_b1_qT0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, u64_sub_zero, arm64_flag_gt_s, hx0])
      all_goals try rfl
      all_goals try (simp only [fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b1_qS0, fib_b1_qT0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, arm64_reg, arm64_set_reg, arm64_subs_flags, arm64_matches_condition, Arm64State.init])
      all_goals try rfl
      all_goals try grind
      all_goals try (simp (disch := decide) [mem_read_after_write_u64, mem_read_after_write_u64_ne, mem_read_two_writes_same])
      all_goals try native_decide
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-cbz-condition
    have hr_2 : arm64_runs fib_code 1 (s_2) = some ({ s_2 with pc := 4294968520 }) := by
      rw [runs_cons_jump (s_2) ({ s_2 with pc := 4294968520 }) fib_code 0 hs_2 (by dsimp only; rw [hpc_2]; decide)]
      exact runs_zero fib_code _
    have ha_2b : arm64_runs fib_code (((((0 + 9) + 1) + 11) + 7) + 1) st = some ({ s_2 with pc := 4294968520 }) := by
      rw [runs_append_some fib_code (((((0 + 9) + 1) + 11) + 7)) 1 st (s_2) ha_2]
      exact hr_2
    have hmd_2_cbz := runs_avoid_append fib_code (((((0 + 9) + 1) + 11) + 7)) (1) 4294970679 st (s_2) ha_2 hmd_2_block (runs_avoid_one fib_code (s_2) 4294970679 (by rw [hpc_2]; decide))
    have hx30fr_3 : (fib_b3_qS4 (({ s_2 with pc := 4294968520 }))).x30 = (st).x30 := by
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, hsid_0, hsid_1, hsid_2, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b1_qS0, fib_b1_qT0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b3_qS0, fib_b3_qT0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qS4, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3, fib_b3_qT4, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat]
      all_goals rfl
    have hj_3 : (fib_b3_qS4 (({ s_2 with pc := 4294968520 }))).x30.toNat ≠ 4294968536 := by
      rw [hx30fr_3]
      exact fun h => hx30ret 4294968536 (by decide) h.symm
    have hcert_3 : arm64_runs fib_code 5 (({ s_2 with pc := 4294968520 })) = some ((fib_b3_qT4 (({ s_2 with pc := 4294968520 })))) := fib_b3_runs (({ s_2 with pc := 4294968520 })) (by rfl) hj_3
    have hrun_ex_3 : ∃ s : Arm64State, arm64_runs fib_code 5 (({ s_2 with pc := 4294968520 })) = some s := ⟨((fib_b3_qT4 (({ s_2 with pc := 4294968520 })))), hcert_3⟩
    rcases hrun_ex_3 with ⟨s_3, hrun_3⟩
    have hsid_3 : s_3 = ((fib_b3_qT4 (({ s_2 with pc := 4294968520 })))) := by injection hrun_3.symm.trans hcert_3
    have ha_3 : arm64_runs fib_code ((((((0 + 9) + 1) + 11) + 7) + 1) + 5) st = some s_3 := by
      rw [runs_append_some fib_code ((((((0 + 9) + 1) + 11) + 7) + 1)) 5 st (({ s_2 with pc := 4294968520 })) ha_2b]
      exact hrun_3
    have hmd_3_block := runs_avoid_append fib_code ((((((0 + 9) + 1) + 11) + 7) + 1)) (5) 4294970679 st (({ s_2 with pc := 4294968520 })) ha_2b hmd_2_cbz (fib_b3_mid 4294970679 (({ s_2 with pc := 4294968520 })) (by rfl) (by simp))
    -- runs terminal: build the step-counted Post
    change ∃ (k : Nat) (st' : Arm64State), k ≤ fuel ∧ arm64_runs fib_code k st = some st'
      ∧ st'.x0 = mojo (st.x0) ∧ st'.pc = st.x30.toNat ∧ FrameOk st st' ∧
      (∀ u, u < k → ∀ s, arm64_runs fib_code u st = some s → s.pc ≠ 4294970679)
    refine ⟨((((((0 + 9) + 1) + 11) + 7) + 1) + 5), s_3, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · omega
    · exact ha_3
    · have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, mojo, fib_model_lt2, fib_model_ge2, hlt2, hsid_0, hsid_1, hsid_2, hsid_3, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b1_qS0, fib_b1_qT0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b3_qS0, fib_b3_qT0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qS4, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3, fib_b3_qT4, arm64_reg, arm64_set_reg, Arm64State.init, hx0, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat]
      all_goals try rfl
      all_goals try omega
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-ret-x0
    · simp only [hsid_3, fib_b3_qT4, hx30fr_3]
      all_goals try rfl
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-ret-x30
    · clear hmd_0_block hmd_0_cbz hmd_1_block hmd_2_block hmd_2_cbz hmd_3_block
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      have hf : 131216 ≤ st.sp.toNat := by
        have := hbnd; simp only [FrameBound] at this; omega
      refine ⟨?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_⟩ <;> (simp +decide only [h8, hsid_0, hsid_1, hsid_2, hsid_3, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b1_qS0, fib_b1_qT0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b3_qS0, fib_b3_qT0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qS4, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3, fib_b3_qT4, arm64_reg, arm64_set_reg, Arm64State.init, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, u64_sub_zero] <;> all_goals try rfl)
      all_goals intro j hj
      all_goals try simp +decide only [h8, hsid_0, hsid_1, hsid_2, hsid_3, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b1_qS0, fib_b1_qT0, fib_b1_qS1, fib_b1_qS2, fib_b1_qS3, fib_b1_qS4, fib_b1_qS5, fib_b1_qS6, fib_b1_qS7, fib_b1_qS8, fib_b1_qS9, fib_b1_qS10, fib_b1_qT1, fib_b1_qT2, fib_b1_qT3, fib_b1_qT4, fib_b1_qT5, fib_b1_qT6, fib_b1_qT7, fib_b1_qT8, fib_b1_qT9, fib_b1_qT10, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b3_qS0, fib_b3_qT0, fib_b3_qS1, fib_b3_qS2, fib_b3_qS3, fib_b3_qS4, fib_b3_qT1, fib_b3_qT2, fib_b3_qT3, fib_b3_qT4, arm64_reg, arm64_set_reg, Arm64State.init, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, mem_read_after_write_u64_high_fb, hf, hj]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 24) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 24 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 24 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 32) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 32 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 32 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 16) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 16 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 16 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 24) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 24 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 24 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 32) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 32 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 32 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 8) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 8 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 8 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 16) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 16 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 16 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try simp +decide only [arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      all_goals try omega
      all_goals try rfl
      all_goals rfl
    · exact hmd_3_block
    all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-ret-frame-ok-window
  · intro k arg st fuel hk hb hpc hx0 hbnd hx30ret ih1 ih2
    have hacc0 : arm64_runs fib_code 0 st = some st := runs_zero fib_code st
    have hne0 : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
    have hne1 : arg ≠ 1 := by intro h; rw [h] at hk; simp at hk
    have hargsub : (arg - 1).toNat = k + 1 := by rw [toNat_sub_one arg hne0]; try omega
    have hargsub2 : (arg - 2).toNat = k := by rw [toNat_sub_two arg hne0 hne1]; try omega
    have hge2 : 2 ≤ arg.toNat := by omega
    have hcert_4 : arm64_runs fib_code 9 (st) = some (({ fib_b0_qT8 (st) with pc := 4294968440 })) := fib_b0_runs (st) hpc
    have hrun_ex_4 : ∃ s : Arm64State, arm64_runs fib_code 9 (st) = some s := ⟨(({ fib_b0_qT8 (st) with pc := 4294968440 })), hcert_4⟩
    rcases hrun_ex_4 with ⟨s_4, hrun_4⟩
    have hsid_4 : s_4 = (({ fib_b0_qT8 (st) with pc := 4294968440 })) := by injection hrun_4.symm.trans hcert_4
    have ha_4 : arm64_runs fib_code (0 + 9) st = some s_4 := by
      rw [runs_append_some fib_code (0) 9 st (st) hacc0]
      exact hrun_4
    have hmd_4_block := runs_avoid_append fib_code (0) (9) 4294970679 st (st) hacc0 (by intro u hu; omega) (fib_b0_mid 4294970679 (st) hpc (by simp))
    have hpc_4 : (s_4).pc = 4294968440 := by rw [hsid_4]
    have hs_4 : arm64_step (s_4) fib_code = some ({ s_4 with pc := 4294968488 }) := by
      have hsr := fib_sr_46 (s_4) hpc_4
      rw [hsr]
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      have hne_4 : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
      all_goals try (simp +decide only [h8, hsid_4, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, u64_sub_zero, arm64_flag_ge, hx0, hne_4])
      all_goals try rw [if_pos hne_4]
      all_goals try rfl
      all_goals try (simp only [fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, arm64_reg, arm64_set_reg, arm64_subs_flags, arm64_matches_condition, Arm64State.init])
      all_goals try rfl
      all_goals try grind
      all_goals try (simp (disch := decide) [mem_read_after_write_u64, mem_read_after_write_u64_ne, mem_read_two_writes_same])
      all_goals try native_decide
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-cbz-condition
    have hr_4 : arm64_runs fib_code 1 (s_4) = some ({ s_4 with pc := 4294968488 }) := by
      rw [runs_cons_jump (s_4) ({ s_4 with pc := 4294968488 }) fib_code 0 hs_4 (by dsimp only; rw [hpc_4]; decide)]
      exact runs_zero fib_code _
    have ha_4b : arm64_runs fib_code ((0 + 9) + 1) st = some ({ s_4 with pc := 4294968488 }) := by
      rw [runs_append_some fib_code ((0 + 9)) 1 st (s_4) ha_4]
      exact hr_4
    have hmd_4_cbz := runs_avoid_append fib_code ((0 + 9)) (1) 4294970679 st (s_4) ha_4 hmd_4_block (runs_avoid_one fib_code (s_4) 4294970679 (by rw [hpc_4]; decide))
    have hcert_5 : arm64_runs fib_code 7 (({ s_4 with pc := 4294968488 })) = some (({ fib_b2_qT6 (({ s_4 with pc := 4294968488 })) with pc := 4294968516 })) := fib_b2_runs (({ s_4 with pc := 4294968488 })) (by rfl)
    have hrun_ex_5 : ∃ s : Arm64State, arm64_runs fib_code 7 (({ s_4 with pc := 4294968488 })) = some s := ⟨(({ fib_b2_qT6 (({ s_4 with pc := 4294968488 })) with pc := 4294968516 })), hcert_5⟩
    rcases hrun_ex_5 with ⟨s_5, hrun_5⟩
    have hsid_5 : s_5 = (({ fib_b2_qT6 (({ s_4 with pc := 4294968488 })) with pc := 4294968516 })) := by injection hrun_5.symm.trans hcert_5
    have ha_5 : arm64_runs fib_code (((0 + 9) + 1) + 7) st = some s_5 := by
      rw [runs_append_some fib_code (((0 + 9) + 1)) 7 st (({ s_4 with pc := 4294968488 })) ha_4b]
      exact hrun_5
    have hmd_5_block := runs_avoid_append fib_code (((0 + 9) + 1)) (7) 4294970679 st (({ s_4 with pc := 4294968488 })) ha_4b hmd_4_cbz (fib_b2_mid 4294970679 (({ s_4 with pc := 4294968488 })) (by rfl) (by simp))
    have hpc_5 : (s_5).pc = 4294968516 := by rw [hsid_5]
    have hs_5 : arm64_step (s_5) fib_code = some ({ s_5 with pc := 4294968544 }) := by
      have hsr := fib_sr_65 (s_5) hpc_5
      rw [hsr]
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      have hne_5 : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
      all_goals try (simp +decide only [h8, hsid_4, hsid_5, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, u64_sub_zero, arm64_flag_gt_s, hx0, hne_5])
      all_goals try rw [if_pos hne_5]
      all_goals try rfl
      all_goals try (simp only [fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, arm64_reg, arm64_set_reg, arm64_subs_flags, arm64_matches_condition, Arm64State.init])
      all_goals try rfl
      all_goals try grind
      all_goals try (simp (disch := decide) [mem_read_after_write_u64, mem_read_after_write_u64_ne, mem_read_two_writes_same])
      all_goals try native_decide
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-cbz-condition
    have hr_5 : arm64_runs fib_code 1 (s_5) = some ({ s_5 with pc := 4294968544 }) := by
      rw [runs_cons_jump (s_5) ({ s_5 with pc := 4294968544 }) fib_code 0 hs_5 (by dsimp only; rw [hpc_5]; decide)]
      exact runs_zero fib_code _
    have ha_5b : arm64_runs fib_code ((((0 + 9) + 1) + 7) + 1) st = some ({ s_5 with pc := 4294968544 }) := by
      rw [runs_append_some fib_code ((((0 + 9) + 1) + 7)) 1 st (s_5) ha_5]
      exact hr_5
    have hmd_5_cbz := runs_avoid_append fib_code ((((0 + 9) + 1) + 7)) (1) 4294970679 st (s_5) ha_5 hmd_5_block (runs_avoid_one fib_code (s_5) 4294970679 (by rw [hpc_5]; decide))
    have hcert_6 : arm64_runs fib_code 8 (({ s_5 with pc := 4294968544 })) = some (({ fib_b4_qT7 (({ s_5 with pc := 4294968544 })) with pc := 4294968576 })) := fib_b4_runs (({ s_5 with pc := 4294968544 })) (by rfl)
    have hrun_ex_6 : ∃ s : Arm64State, arm64_runs fib_code 8 (({ s_5 with pc := 4294968544 })) = some s := ⟨(({ fib_b4_qT7 (({ s_5 with pc := 4294968544 })) with pc := 4294968576 })), hcert_6⟩
    rcases hrun_ex_6 with ⟨s_6, hrun_6⟩
    have hsid_6 : s_6 = (({ fib_b4_qT7 (({ s_5 with pc := 4294968544 })) with pc := 4294968576 })) := by injection hrun_6.symm.trans hcert_6
    have ha_6 : arm64_runs fib_code (((((0 + 9) + 1) + 7) + 1) + 8) st = some s_6 := by
      rw [runs_append_some fib_code (((((0 + 9) + 1) + 7) + 1)) 8 st (({ s_5 with pc := 4294968544 })) ha_5b]
      exact hrun_6
    have hmd_6_block := runs_avoid_append fib_code (((((0 + 9) + 1) + 7) + 1)) (8) 4294970679 st (({ s_5 with pc := 4294968544 })) ha_5b hmd_5_cbz (fib_b4_mid 4294970679 (({ s_5 with pc := 4294968544 })) (by rfl) (by simp))
    have hpc_6 : (s_6).pc = 4294968576 := by rw [hsid_6]
    have hs_6 : arm64_step (s_6) fib_code = some ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) := by
      have hsr := fib_sr_80 (s_6) hpc_6
      rw [hsr]
      rw [hpc_6]
      all_goals try rfl
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-bl-step
    have hr_6 : arm64_runs fib_code 1 (s_6) = some ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) := by
      rw [runs_cons_jump (s_6) ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) fib_code 0 hs_6 (by dsimp only; rw [hpc_6]; decide)]
      exact runs_zero fib_code _
    have ha_6entry : arm64_runs fib_code ((((((0 + 9) + 1) + 7) + 1) + 8) + 1) st = some ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) := by
      rw [runs_append_some fib_code ((((((0 + 9) + 1) + 7) + 1) + 8)) 1 st (s_6) ha_6]
      exact hr_6
    have hmd_6_bl := runs_avoid_append fib_code ((((((0 + 9) + 1) + 7) + 1) + 8)) (1) 4294970679 st (s_6) ha_6 hmd_6_block (runs_avoid_one fib_code (s_6) 4294970679 (by rw [hpc_6]; decide))
    have hx30ret_6 : ∀ pc, pc ∈ [4294968536, 4294968644, 4294968828] → pc ≠ 4294968580 := (by intro pc hmem; simp only [List.mem_cons, List.not_mem_nil, or_false] at hmem; rcases hmem with h | h <;> (rw [h]; native_decide))
    have hx0sub_6 : (({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 })).x0 = arg - 1 := by
        have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
        simp +decide only [h8, hsid_4, hsid_5, hsid_6, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, hx0]
        all_goals rfl
    have hsp_6 : ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }).sp = (st).sp - UInt64.ofNat 131104 := by
      show (s_6).sp = (st).sp - UInt64.ofNat 131104
      have ea0 : (({ s_4 with pc := 4294968488 })).sp = (fib_b0_qT8 (st)).sp := by rw [hsid_4]
      have eb0 : (fib_b0_qT8 (st)).sp = (st).sp - UInt64.ofNat 32 := by
        simp only [fib_b0_qT8, arm64_set_reg_sp]
        simp +decide only [fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      have ea1 : (({ s_5 with pc := 4294968544 })).sp = (fib_b2_qT6 (({ s_4 with pc := 4294968488 }))).sp := by rw [hsid_5]
      have eb1 : (fib_b2_qT6 (({ s_4 with pc := 4294968488 }))).sp = (({ s_4 with pc := 4294968488 })).sp - UInt64.ofNat 131072 := by
        simp only [fib_b2_qT6, arm64_set_reg_sp]
        simp +decide only [fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      have ea2 : (s_6).sp = (fib_b4_qT7 (({ s_5 with pc := 4294968544 }))).sp := by rw [hsid_6]
      have eb2 : (fib_b4_qT7 (({ s_5 with pc := 4294968544 }))).sp = (({ s_5 with pc := 4294968544 })).sp := by
        simp only [fib_b4_qT7, arm64_set_reg_sp]
        simp +decide only [fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      rw [ea2, eb2, ea1, eb1, ea0, eb0]
      try simp only [arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
    have hbndsub_6 : FrameBound 131216 (({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 })) (arg - 1) := by
      have hargne0 : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
      have hargrel : (arg - 1).toNat + 1 ≤ arg.toNat := u64_sub_one_toNat_le arg (arg - 1) hargne0 (by rfl)
      have hcur : (s_6).sp = (st).sp - UInt64.ofNat 131104 := by
        rw [hsp_6]
      have hPge : 131104 ≤ (st).sp.toNat := by
        have hbn := hbnd; simp only [FrameBound] at hbn
        have hlt := UInt64.toNat_lt (st).sp
        omega
      have h := frameBound_descend_le 131216 131104 (st) arg (arg - 1) (by omega) (by decide) hargrel hPge hbnd
      simp only [FrameBound] at h ⊢
      rw [hcur]
      exact h
    have hsub_6 := ih1 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) ((106 + 512 * 2 ^ (k + 1))) (by omega) (by rfl) hx0sub_6 hbndsub_6 hx30ret_6
    obtain ⟨k_6, s_ret_6, hk_6, hrun_6, hx0_6, hpc_6, hfr_6, hmidcall_6⟩ := hsub_6
    have ha_6b : arm64_runs fib_code (((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) st = some s_ret_6 := by
      rw [runs_append_some fib_code ((((((0 + 9) + 1) + 7) + 1) + 8) + 1) k_6 st ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) ha_6entry]
      exact hrun_6
    have hmd_6_call := runs_avoid_append fib_code ((((((0 + 9) + 1) + 7) + 1) + 8) + 1) (k_6) 4294970679 st (({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 })) ha_6entry hmd_6_bl hmidcall_6
    obtain ⟨hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hfrsp_6, hfrwin_6⟩ := hfr_6
    have hfrf_6_8 : mem_read_u64 s_ret_6.mem ((st).sp - UInt64.ofNat 8).toNat = mem_read_u64 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 8).toNat := FrameOk_window_reindex s_ret_6 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) (st).sp (P := 131104) (K := 8) hsp_6 hfrwin_6 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_6_16 : mem_read_u64 s_ret_6.mem ((st).sp - UInt64.ofNat 16).toNat = mem_read_u64 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 16).toNat := FrameOk_window_reindex s_ret_6 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) (st).sp (P := 131104) (K := 16) hsp_6 hfrwin_6 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_6_24 : mem_read_u64 s_ret_6.mem ((st).sp - UInt64.ofNat 24).toNat = mem_read_u64 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 24).toNat := FrameOk_window_reindex s_ret_6 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) (st).sp (P := 131104) (K := 24) hsp_6 hfrwin_6 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_6_32 : mem_read_u64 s_ret_6.mem ((st).sp - UInt64.ofNat 32).toNat = mem_read_u64 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 32).toNat := FrameOk_window_reindex s_ret_6 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) (st).sp (P := 131104) (K := 32) hsp_6 hfrwin_6 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrwinup_6 : ∀ j, (st).sp.toNat + j < 2^64 → mem_read_u64 s_ret_6.mem ((st).sp + UInt64.ofNat j).toNat = mem_read_u64 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }).mem ((st).sp + UInt64.ofNat j).toNat := FrameOk_window_reindex_up s_ret_6 ({ s_6 with x30 := UInt64.ofNat 4294968580, pc := 4294968404 }) (st).sp (P := 131104) hsp_6 hfrwin_6 (by have := hbnd; simp only [FrameBound] at this; omega)
    have hcert_7 : arm64_runs fib_code 9 (s_ret_6) = some (({ fib_b5_qT8 (s_ret_6) with pc := 4294968616 })) := fib_b5_runs (s_ret_6) hpc_6
    have hrun_ex_7 : ∃ s : Arm64State, arm64_runs fib_code 9 (s_ret_6) = some s := ⟨(({ fib_b5_qT8 (s_ret_6) with pc := 4294968616 })), hcert_7⟩
    rcases hrun_ex_7 with ⟨s_7, hrun_7⟩
    have hsid_7 : s_7 = (({ fib_b5_qT8 (s_ret_6) with pc := 4294968616 })) := by injection hrun_7.symm.trans hcert_7
    have ha_7 : arm64_runs fib_code ((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) st = some s_7 := by
      rw [runs_append_some fib_code ((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6)) 9 st (s_ret_6) ha_6b]
      exact hrun_7
    have hmd_7_block := runs_avoid_append fib_code ((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6)) (9) 4294970679 st (s_ret_6) ha_6b hmd_6_call (fib_b5_mid 4294970679 (s_ret_6) hpc_6 (by simp))
    have hpc_7 : (s_7).pc = 4294968616 := by rw [hsid_7]
    have hs_7 : arm64_step (s_7) fib_code = some ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) := by
      have hsr := fib_sr_90 (s_7) hpc_7
      rw [hsr]
      rw [hpc_7]
      all_goals try rfl
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-bl-step
    have hr_7 : arm64_runs fib_code 1 (s_7) = some ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) := by
      rw [runs_cons_jump (s_7) ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) fib_code 0 hs_7 (by dsimp only; rw [hpc_7]; decide)]
      exact runs_zero fib_code _
    have ha_7entry : arm64_runs fib_code (((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) st = some ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) := by
      rw [runs_append_some fib_code (((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9)) 1 st (s_7) ha_7]
      exact hr_7
    have hmd_7_bl := runs_avoid_append fib_code (((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9)) (1) 4294970679 st (s_7) ha_7 hmd_7_block (runs_avoid_one fib_code (s_7) 4294970679 (by rw [hpc_7]; decide))
    have hx30ret_7 : ∀ pc, pc ∈ [4294968536, 4294968644, 4294968828] → pc ≠ 4294968620 := (by intro pc hmem; simp only [List.mem_cons, List.not_mem_nil, or_false] at hmem; rcases hmem with h | h <;> (rw [h]; native_decide))
    have hx0sub_7 : (({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 })).x0 = arg - 2 := by
        have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
        simp +decide only [h8, hsid_4, hsid_5, hsid_6, hsid_7, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, hfrf_6_8, hfrf_6_16, hfrf_6_24, hfrf_6_32, hfrwinup_6, hfrsp_6, hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hx0_6, fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, hx0]
        all_goals rfl
    have hsp_7 : ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).sp = (st).sp - UInt64.ofNat 131120 := by
      show (s_7).sp = (st).sp - UInt64.ofNat 131120
      have ea0 : (({ s_4 with pc := 4294968488 })).sp = (fib_b0_qT8 (st)).sp := by rw [hsid_4]
      have eb0 : (fib_b0_qT8 (st)).sp = (st).sp - UInt64.ofNat 32 := by
        simp only [fib_b0_qT8, arm64_set_reg_sp]
        simp +decide only [fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      have ea1 : (({ s_5 with pc := 4294968544 })).sp = (fib_b2_qT6 (({ s_4 with pc := 4294968488 }))).sp := by rw [hsid_5]
      have eb1 : (fib_b2_qT6 (({ s_4 with pc := 4294968488 }))).sp = (({ s_4 with pc := 4294968488 })).sp - UInt64.ofNat 131072 := by
        simp only [fib_b2_qT6, arm64_set_reg_sp]
        simp +decide only [fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      have ea2 : (s_ret_6).sp = (fib_b4_qT7 (({ s_5 with pc := 4294968544 }))).sp := by rw [hfrsp_6, hsid_6]
      have eb2 : (fib_b4_qT7 (({ s_5 with pc := 4294968544 }))).sp = (({ s_5 with pc := 4294968544 })).sp := by
        simp only [fib_b4_qT7, arm64_set_reg_sp]
        simp +decide only [fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      have ea3 : (s_7).sp = (fib_b5_qT8 (s_ret_6)).sp := by rw [hsid_7]
      have eb3 : (fib_b5_qT8 (s_ret_6)).sp = (s_ret_6).sp - UInt64.ofNat 16 := by
        simp only [fib_b5_qT8, arm64_set_reg_sp]
        simp +decide only [fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      rw [ea3, eb3, ea2, eb2, ea1, eb1, ea0, eb0]
      try simp only [arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
    have hbndsub_7 : FrameBound 131216 (({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 })) (arg - 2) := by
      have hargne0 : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
      have hargne_one : arg ≠ 1 := by intro h; rw [h] at hk; simp at hk
      have hargrel : (arg - 2).toNat + 1 ≤ arg.toNat := u64_sub_two_toNat_le arg (arg - 2) hargne0 hargne_one (by rfl)
      have hcur : (s_7).sp = (st).sp - UInt64.ofNat 131120 := by
        rw [hsp_7]
      have hPge : 131120 ≤ (st).sp.toNat := by
        have hbn := hbnd; simp only [FrameBound] at hbn
        have hlt := UInt64.toNat_lt (st).sp
        omega
      have h := frameBound_descend_le 131216 131120 (st) arg (arg - 2) (by omega) (by decide) hargrel hPge hbnd
      simp only [FrameBound] at h ⊢
      rw [hcur]
      exact h
    have hsub_7 := ih2 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) ((106 + 512 * 2 ^ k)) (by omega) (by rfl) hx0sub_7 hbndsub_7 hx30ret_7
    obtain ⟨k_7, s_ret_7, hk_7, hrun_7, hx0_7, hpc_7, hfr_7, hmidcall_7⟩ := hsub_7
    have ha_7b : arm64_runs fib_code ((((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) + k_7) st = some s_ret_7 := by
      rw [runs_append_some fib_code (((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) k_7 st ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) ha_7entry]
      exact hrun_7
    have hmd_7_call := runs_avoid_append fib_code (((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) (k_7) 4294970679 st (({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 })) ha_7entry hmd_7_bl hmidcall_7
    obtain ⟨hfr19_7, hfr20_7, hfr21_7, hfr22_7, hfr23_7, hfr24_7, hfr25_7, hfr26_7, hfr27_7, hfr28_7, hfr29_7, hfr30_7, hfrsp_7, hfrwin_7⟩ := hfr_7
    have hfrf_7_8 : mem_read_u64 s_ret_7.mem ((st).sp - UInt64.ofNat 8).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 8).toNat := FrameOk_window_reindex s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) (K := 8) hsp_7 hfrwin_7 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_7_16 : mem_read_u64 s_ret_7.mem ((st).sp - UInt64.ofNat 16).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 16).toNat := FrameOk_window_reindex s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) (K := 16) hsp_7 hfrwin_7 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_7_24 : mem_read_u64 s_ret_7.mem ((st).sp - UInt64.ofNat 24).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 24).toNat := FrameOk_window_reindex s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) (K := 24) hsp_7 hfrwin_7 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_7_32 : mem_read_u64 s_ret_7.mem ((st).sp - UInt64.ofNat 32).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 32).toNat := FrameOk_window_reindex s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) (K := 32) hsp_7 hfrwin_7 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_7_131112 : mem_read_u64 s_ret_7.mem ((st).sp - UInt64.ofNat 131112).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 131112).toNat := FrameOk_window_reindex s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) (K := 131112) hsp_7 hfrwin_7 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrf_7_131120 : mem_read_u64 s_ret_7.mem ((st).sp - UInt64.ofNat 131120).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp - UInt64.ofNat 131120).toNat := FrameOk_window_reindex s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) (K := 131120) hsp_7 hfrwin_7 (by omega) (by decide) (by have := hbnd; simp only [FrameBound] at this; omega)
    have hfrwinup_7 : ∀ j, (st).sp.toNat + j < 2^64 → mem_read_u64 s_ret_7.mem ((st).sp + UInt64.ofNat j).toNat = mem_read_u64 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }).mem ((st).sp + UInt64.ofNat j).toNat := FrameOk_window_reindex_up s_ret_7 ({ s_7 with x30 := UInt64.ofNat 4294968620, pc := 4294968404 }) (st).sp (P := 131120) hsp_7 hfrwin_7 (by have := hbnd; simp only [FrameBound] at this; omega)
    have hx30fr_8 : (fib_b6_qS6 (s_ret_7)).x30 = (st).x30 := by
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      simp +decide only [h8, hsid_4, hsid_5, hsid_6, hsid_7, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, hfrf_6_8, hfrf_6_16, hfrf_6_24, hfrf_6_32, hfrwinup_6, hfrsp_6, hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hx0_6, fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, hfrf_7_8, hfrf_7_16, hfrf_7_24, hfrf_7_32, hfrf_7_131112, hfrf_7_131120, hfrwinup_7, hfrsp_7, hfr19_7, hfr20_7, hfr21_7, hfr22_7, hfr23_7, hfr24_7, hfr25_7, hfr26_7, hfr27_7, hfr28_7, hfr29_7, hfr30_7, hx0_7, fib_b6_qS0, fib_b6_qT0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6, arm64_reg, arm64_set_reg, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat]
      all_goals rfl
    have hj_8 : (fib_b6_qS6 (s_ret_7)).x30.toNat ≠ 4294968644 := by
      rw [hx30fr_8]
      exact fun h => hx30ret 4294968644 (by decide) h.symm
    have hcert_8 : arm64_runs fib_code 7 (s_ret_7) = some ((fib_b6_qT6 (s_ret_7))) := fib_b6_runs (s_ret_7) hpc_7 hj_8
    have hrun_ex_8 : ∃ s : Arm64State, arm64_runs fib_code 7 (s_ret_7) = some s := ⟨((fib_b6_qT6 (s_ret_7))), hcert_8⟩
    rcases hrun_ex_8 with ⟨s_8, hrun_8⟩
    have hsid_8 : s_8 = ((fib_b6_qT6 (s_ret_7))) := by injection hrun_8.symm.trans hcert_8
    have ha_8 : arm64_runs fib_code (((((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) + k_7) + 7) st = some s_8 := by
      rw [runs_append_some fib_code (((((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) + k_7)) 7 st (s_ret_7) ha_7b]
      exact hrun_8
    have hmd_8_block := runs_avoid_append fib_code (((((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) + k_7)) (7) 4294970679 st (s_ret_7) ha_7b hmd_7_call (fib_b6_mid 4294970679 (s_ret_7) hpc_7 (by simp))
    -- runs terminal: build the step-counted Post
    change ∃ (k : Nat) (st' : Arm64State), k ≤ fuel ∧ arm64_runs fib_code k st = some st'
      ∧ st'.x0 = mojo (arg) ∧ st'.pc = st.x30.toNat ∧ FrameOk st st' ∧
      (∀ u, u < k → ∀ s, arm64_runs fib_code u st = some s → s.pc ≠ 4294970679)
    refine ⟨(((((((((((0 + 9) + 1) + 7) + 1) + 8) + 1) + k_6) + 9) + 1) + k_7) + 7), s_8, ?_, ?_, ?_, ?_, ?_, ?_⟩
    · rw [mul_two_pow_succ 512 k] at hk_6
      rw [mul_two_pow_add_two 512 k] at hb
      have hX := one_le_two_pow k
      omega
    · exact ha_8
    · have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      have hfib : fib_model (k + 1) + fib_model k = fib_model (k + 2) := by
        rw [show fib_model (k + 2) = fib_model k + fib_model (k + 1) from by
          simpa using fib_model_ge2 (n := k + 2) (by omega), UInt64.add_comm]
      simp +decide only [h8, mojo, hfib, fib_model_lt2, fib_model_ge2, hargsub, hargsub2, hge2, hk, hsid_4, hsid_5, hsid_6, hsid_7, hsid_8, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, hfrf_6_8, hfrf_6_16, hfrf_6_24, hfrf_6_32, hfrwinup_6, hfrsp_6, hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hx0_6, fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, hfrf_7_8, hfrf_7_16, hfrf_7_24, hfrf_7_32, hfrf_7_131112, hfrf_7_131120, hfrwinup_7, hfrsp_7, hfr19_7, hfr20_7, hfr21_7, hfr22_7, hfr23_7, hfr24_7, hfr25_7, hfr26_7, hfr27_7, hfr28_7, hfr29_7, hfr30_7, hx0_7, fib_b6_qS0, fib_b6_qT0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6, arm64_reg, arm64_set_reg, Arm64State.init, hx0, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat]
      all_goals try rfl
      all_goals try omega
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-ret-x0
    · simp only [hsid_8, fib_b6_qT6, hx30fr_8]
      all_goals try rfl
      all_goals try grind
      all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-ret-x30
    · clear hmd_4_block hmd_4_cbz hmd_5_block hmd_5_cbz hmd_6_block hmd_6_bl hmd_6_call hmd_7_block hmd_7_bl hmd_7_call hmd_8_block
      have h8 : (8 : UInt64) = UInt64.ofNat 8 := rfl
      have hf : 131216 ≤ st.sp.toNat := by
        have := hbnd; simp only [FrameBound] at this; omega
      refine ⟨?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_,?_⟩ <;> (simp +decide only [h8, hsid_4, hsid_5, hsid_6, hsid_7, hsid_8, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, hfrf_6_8, hfrf_6_16, hfrf_6_24, hfrf_6_32, hfrwinup_6, hfrsp_6, hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hx0_6, fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, hfrf_7_8, hfrf_7_16, hfrf_7_24, hfrf_7_32, hfrf_7_131112, hfrf_7_131120, hfrwinup_7, hfrsp_7, hfr19_7, hfr20_7, hfr21_7, hfr22_7, hfr23_7, hfr24_7, hfr25_7, hfr26_7, hfr27_7, hfr28_7, hfr29_7, hfr30_7, hx0_7, fib_b6_qS0, fib_b6_qT0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6, arm64_reg, arm64_set_reg, Arm64State.init, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, u64_sub_zero] <;> all_goals try rfl)
      all_goals intro j hj
      all_goals try simp +decide only [h8, hsid_4, hsid_5, hsid_6, hsid_7, hsid_8, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, hfrf_6_8, hfrf_6_16, hfrf_6_24, hfrf_6_32, hfrwinup_6, hfrsp_6, hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hx0_6, fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, hfrf_7_8, hfrf_7_16, hfrf_7_24, hfrf_7_32, hfrf_7_131112, hfrf_7_131120, hfrwinup_7, hfrsp_7, hfr19_7, hfr20_7, hfr21_7, hfr22_7, hfr23_7, hfr24_7, hfr25_7, hfr26_7, hfr27_7, hfr28_7, hfr29_7, hfr30_7, hx0_7, fib_b6_qS0, fib_b6_qT0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6, arm64_reg, arm64_set_reg, Arm64State.init, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat, mem_read_after_write_u64_high_fb, hf, hj]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131128) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131136) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131128) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131136) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 24) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 24 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 24 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 32) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 32 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 32 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 16) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 16 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 16 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131128) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131136) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131128) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131136) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 24) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 24 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 24 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 32) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 32 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 32 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 8) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 8 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 8 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 16) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 16 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 16 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try simp +decide only [arm64_set_reg_sp, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, u64_sub_lit_sub, Nat.reduceAdd, Nat.reduceSub, u64_ofNat_zero, u64_sub_zero]
      all_goals try omega
      all_goals first | (refine (hfrwinup_6 j hj).trans ?_) | (refine (hfrwinup_7 j hj).trans ?_) | skip
      all_goals try simp only [hsid_4, hsid_5, hsid_6, hsid_7, hsid_8, fib_b0_qS0, fib_b0_qT0, fib_b0_qS1, fib_b0_qS2, fib_b0_qS3, fib_b0_qS4, fib_b0_qS5, fib_b0_qS6, fib_b0_qS7, fib_b0_qS8, fib_b0_qT1, fib_b0_qT2, fib_b0_qT3, fib_b0_qT4, fib_b0_qT5, fib_b0_qT6, fib_b0_qT7, fib_b0_qT8, fib_b2_qS0, fib_b2_qT0, fib_b2_qS1, fib_b2_qS2, fib_b2_qS3, fib_b2_qS4, fib_b2_qS5, fib_b2_qS6, fib_b2_qT1, fib_b2_qT2, fib_b2_qT3, fib_b2_qT4, fib_b2_qT5, fib_b2_qT6, fib_b4_qS0, fib_b4_qT0, fib_b4_qS1, fib_b4_qS2, fib_b4_qS3, fib_b4_qS4, fib_b4_qS5, fib_b4_qS6, fib_b4_qS7, fib_b4_qT1, fib_b4_qT2, fib_b4_qT3, fib_b4_qT4, fib_b4_qT5, fib_b4_qT6, fib_b4_qT7, hfrf_6_8, hfrf_6_16, hfrf_6_24, hfrf_6_32, hfrwinup_6, hfrsp_6, hfr19_6, hfr20_6, hfr21_6, hfr22_6, hfr23_6, hfr24_6, hfr25_6, hfr26_6, hfr27_6, hfr28_6, hfr29_6, hfr30_6, hx0_6, fib_b5_qS0, fib_b5_qT0, fib_b5_qS1, fib_b5_qS2, fib_b5_qS3, fib_b5_qS4, fib_b5_qS5, fib_b5_qS6, fib_b5_qS7, fib_b5_qS8, fib_b5_qT1, fib_b5_qT2, fib_b5_qT3, fib_b5_qT4, fib_b5_qT5, fib_b5_qT6, fib_b5_qT7, fib_b5_qT8, hfrf_7_8, hfrf_7_16, hfrf_7_24, hfrf_7_32, hfrf_7_131112, hfrf_7_131120, hfrwinup_7, hfrsp_7, hfr19_7, hfr20_7, hfr21_7, hfr22_7, hfr23_7, hfr24_7, hfr25_7, hfr26_7, hfr27_7, hfr28_7, hfr29_7, hfr30_7, hx0_7, fib_b6_qS0, fib_b6_qT0, fib_b6_qS1, fib_b6_qS2, fib_b6_qS3, fib_b6_qS4, fib_b6_qS5, fib_b6_qS6, fib_b6_qT1, fib_b6_qT2, fib_b6_qT3, fib_b6_qT4, fib_b6_qT5, fib_b6_qT6, arm64_reg, arm64_set_reg, Arm64State.init, Nat.reduceAdd, Nat.reduceSub, Nat.reduceMul, u64_sub_sub, u64_sub_add, u64_ofNat_add, u64_ofNat_sub, mem_read_after_write_u64_slot, mem_read_after_write_u64_slot', mem_read_after_write_u64, arm64_cset_eq, arm64_cset_ne, arm64_cset_lt_s, fdiv_correction, fdiv64, frem64, UInt64.add_zero, u64_ofNat_zero, UInt64.ofNat_toNat]
      all_goals try simp only [u64_sub_lit_sub, u64_ofNat_sub, u64_ofNat_add, Nat.reduceSub, Nat.reduceAdd]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131128) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131136) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131128) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131136) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131112) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 131120) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 24) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 24 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 24 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 32) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 32 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 32 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below _ st.sp (K := 16) (j := j) (by decide) hj (by omega) (by decide) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 16 + 8) (b := 8) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_pair_below_split _ st.sp (a := 16 + 16) (b := 16) (j := j) (by omega) (by decide) (by decide) hj (by omega) (by omega) _ _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131128) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131136) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131128) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131128 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131136) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131136 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131112) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131112 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 131120) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 131120 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 24) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 24 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 24 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 32) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 32 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 32 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 8) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 8 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 8 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below _ st.sp (K := 16) (j := j) hj (by omega) (by decide) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 16 + 8) (b := 8) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rw [mem_read_write_below_split _ st.sp (a := 16 + 16) (b := 16) (j := j) (by omega) (by decide) hj (by omega) (by omega) _]
      all_goals try rfl
      all_goals rfl
    · exact hmd_8_block
    all_goals (first | done | sorry)  -- arm64-cfg-leaf: runs-ret-frame-ok-window

theorem fib_compiles_correctly_universal (n : UInt64)
    (hn : 131216 * (n.toNat + 1) + 131216 ≤ 18446744073709551600) :
    (match runProg fib_prog n with
     | some s => s.x0 = mojo n
     | none => False) := by
  have hbnd : FrameBound 131216 ({ Arm64State.init n 4294968256 with pc := 4294968404, x30 := UInt64.ofNat 4294970679 }) n := by
    change 131216 * (n.toNat + 1) ≤ 18446744073709551600
    omega
  have hret : ∀ pc, pc ∈ fib_prog.rets → pc ≠ 4294970679 := by
    simp [fib_prog]
  have hc := fib_contract (106 + 512 * 2 ^ n.toNat) n
    ({ Arm64State.init n 4294968256 with pc := 4294968404, x30 := UInt64.ofNat 4294970679 }) (by omega) rfl rfl hbnd hret
  change (match arm64_go_exit ({ Arm64State.init n 4294968256 with pc := 4294968404, x30 := UInt64.ofNat 4294970679 }) fib_code 4294970679 ((200000 + 1000 * 2 ^ n.toNat)) with
    | some s => s.x0 = mojo n | none => False)
  exact Post.exit_correct fib_prog _ _ (mojo n) _ n hc rfl (by omega)
    