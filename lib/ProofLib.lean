import Lean
set_option maxRecDepth 10000

/-!
# ProofLib: Shared infrastructure for Mojo proof-carrying compiler

This library contains the x86-64 machine model, memory operations,
instruction semantics, execution engine, AST types, and evaluation
functions.  It is compiled once (to .olean) and imported by all
per-program proof files.
-/

/-- x86-64 machine state: 16 GPRs, flags, rip, and byte-addressable memory -/
structure X86State where
  rax : UInt64
  rbx : UInt64
  rcx : UInt64
  rdx : UInt64
  rsp : UInt64
  rbp : UInt64
  rsi : UInt64
  rdi : UInt64
  r8 : UInt64
  r9 : UInt64
  r10 : UInt64
  r11 : UInt64
  r12 : UInt64
  r13 : UInt64
  r14 : UInt64
  r15 : UInt64
  rip : Nat
  zf : Bool
  sf : Bool
  cf : Bool
  of_ : Bool
  mem : Nat → UInt8
  deriving Inhabited

def X86State.init (input : UInt64) (entry : Nat) : X86State :=
  { rax := 0, rbx := 0, rcx := 0, rdx := 0
    rsp := 0xfffffffffffffff0, rbp := 0, rsi := 0, rdi := input
    r8 := 0, r9 := 0, r10 := 0, r11 := 0
    r12 := 0, r13 := 0, r14 := 0, r15 := 0
    rip := entry, zf := false, sf := false, cf := false, of_ := false
    mem := fun _ => 0 }

/-- Memory read: load 8 bytes little-endian from address -/
def mem_read_u64 (mem : Nat → UInt8) (addr : Nat) : UInt64 :=
  (mem addr).toUInt64 |||
  ((mem (addr + 1)).toUInt64 <<< 8) |||
  ((mem (addr + 2)).toUInt64 <<< 16) |||
  ((mem (addr + 3)).toUInt64 <<< 24) |||
  ((mem (addr + 4)).toUInt64 <<< 32) |||
  ((mem (addr + 5)).toUInt64 <<< 40) |||
  ((mem (addr + 6)).toUInt64 <<< 48) |||
  ((mem (addr + 7)).toUInt64 <<< 56)

/-- Memory write: store 8 bytes little-endian to address -/
def mem_write_u64 (mem : Nat → UInt8) (addr : Nat) (val : UInt64) : Nat → UInt8 :=
  fun i =>
    if i = addr then UInt8.ofNat (val.toNat % 256)
    else if i = addr + 1 then UInt8.ofNat ((val.toNat >>> 8) % 256)
    else if i = addr + 2 then UInt8.ofNat ((val.toNat >>> 16) % 256)
    else if i = addr + 3 then UInt8.ofNat ((val.toNat >>> 24) % 256)
    else if i = addr + 4 then UInt8.ofNat ((val.toNat >>> 32) % 256)
    else if i = addr + 5 then UInt8.ofNat ((val.toNat >>> 40) % 256)
    else if i = addr + 6 then UInt8.ofNat ((val.toNat >>> 48) % 256)
    else if i = addr + 7 then UInt8.ofNat ((val.toNat >>> 56) % 256)
    else mem i

/-- Read 4 bytes signed little-endian (sign-extended to UInt64) -/
def read_i32_le (code : Nat → UInt8) (addr : Nat) : Int :=
  let b0 := (code addr).toNat
  let b1 := (code (addr + 1)).toNat * 256
  let b2 := (code (addr + 2)).toNat * 65536
  let b3 := (code (addr + 3)).toNat * 16777216
  let unsigned := b0 + b1 + b2 + b3
  if unsigned ≥ 2147483648 then Int.ofNat unsigned - 4294967296
  else Int.ofNat unsigned

/-- Read signed byte (rel8 offset) -/
def read_i8 (b : UInt8) : Int :=
  let n := b.toNat
  if n ≥ 128 then Int.ofNat n - 256
  else Int.ofNat n

theorem nat64 : (18446744073709551616 : Nat) = 2 ^ 64 := by decide
theorem n8 : (256 : Nat) = 2 ^ 8 := rfl

theorem sub_add (m n : Nat) (h : n ≤ m) : n + (m - n) = m := by omega

/-- Collapse a pushed byte-window term to a single compound window decide. -/
theorem winfix (v i k : Nat) :
    ((decide (i < 64) && (decide (i ≥ k) && (decide (i - k < 8) && v.testBit (k + (i - k))))))
      = (decide (i < 64) && (decide (k ≤ i ∧ i < k + 8) && v.testBit i)) := by
  by_cases hc : k ≤ i ∧ i < k + 8
  · have t1 : decide (i ≥ k) = true := decide_eq_true hc.1
    have t2 : decide (i - k < 8) = true := decide_eq_true (by omega)
    have t3 : decide (k ≤ i ∧ i < k + 8) = true := decide_eq_true hc
    rw [t1, t2, t3, sub_add i k hc.1]
    try simp
  · rcases Nat.lt_or_ge i k with hl | hg
    · have e1 : decide (i ≥ k) = false := decide_eq_false (by omega)
      have e3 : decide (k ≤ i ∧ i < k + 8) = false := decide_eq_false (by omega)
      rw [e1, e3]
      try simp
    · have t1 : decide (i ≥ k) = true := decide_eq_true hg
      have e2 : decide (i - k < 8) = false := decide_eq_false (by omega)
      have e3 : decide (k ≤ i ∧ i < k + 8) = false := decide_eq_false hc
      rw [t1, e2, e3]
      try simp

/-- Memory read-after-write: reading from the address just written returns the value.
    Proved: little-endian byte recombination, per-bit via `Nat.eq_of_testBit_eq`. -/
@[simp] theorem mem_read_after_write_u64 (mem : Nat → UInt8) (addr : Nat) (val : UInt64) :
  mem_read_u64 (mem_write_u64 mem addr val) addr = val := by
  apply UInt64.toNat.inj
  simp [mem_read_u64, mem_write_u64]
  apply Nat.eq_of_testBit_eq
  intro i
  have hb : val.toNat < 2 ^ 64 := UInt64.toNat_lt val
  simp only [Nat.testBit_or, UInt8.toNat_ofNat, nat64, n8,
             Nat.testBit_mod_two_pow, Nat.testBit_shiftLeft, Nat.testBit_shiftRight]
  simp only [winfix]
  by_cases h64 : i < 64
  · -- i in some window [8j, 8j+8)
    rcases Nat.lt_or_ge i 8 with r0 | g0
    · -- window 0
      rw [show decide (i < 8) = true from decide_eq_true r0,
          show decide (i < 64) = true from decide_eq_true h64,
          show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
          show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
          show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
          show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
          show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
          show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
          show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
      simp
    · rcases Nat.lt_or_ge i 16 with r1 | g1
      · -- window 1
        rw [show decide (8 ≤ i ∧ i < 8 + 8) = true from decide_eq_true ⟨g0, by omega⟩,
            show decide (i < 64) = true from decide_eq_true h64,
            show decide (i < 8) = false from decide_eq_false (by omega),
            show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
            show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
            show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
            show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
            show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
            show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
        simp
      · rcases Nat.lt_or_ge i 24 with r2 | g2
        · -- window 2
          rw [show decide (16 ≤ i ∧ i < 16 + 8) = true from decide_eq_true ⟨g1, by omega⟩,
              show decide (i < 64) = true from decide_eq_true h64,
              show decide (i < 8) = false from decide_eq_false (by omega),
              show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
              show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
              show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
              show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
              show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
              show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
          simp
        · rcases Nat.lt_or_ge i 32 with r3 | g3
          · -- window 3
            rw [show decide (24 ≤ i ∧ i < 24 + 8) = true from decide_eq_true ⟨g2, by omega⟩,
                show decide (i < 64) = true from decide_eq_true h64,
                show decide (i < 8) = false from decide_eq_false (by omega),
                show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
                show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
                show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
                show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
                show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
                show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
            simp
          · rcases Nat.lt_or_ge i 40 with r4 | g4
            · -- window 4
              rw [show decide (32 ≤ i ∧ i < 32 + 8) = true from decide_eq_true ⟨g3, by omega⟩,
                  show decide (i < 64) = true from decide_eq_true h64,
                  show decide (i < 8) = false from decide_eq_false (by omega),
                  show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
                  show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
                  show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
                  show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
                  show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
                  show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
              simp
            · rcases Nat.lt_or_ge i 48 with r5 | g5
              · -- window 5
                rw [show decide (40 ≤ i ∧ i < 40 + 8) = true from decide_eq_true ⟨g4, by omega⟩,
                    show decide (i < 64) = true from decide_eq_true h64,
                    show decide (i < 8) = false from decide_eq_false (by omega),
                    show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
                    show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
                    show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
                    show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
                    show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
                    show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
                simp
              · rcases Nat.lt_or_ge i 56 with r6 | g6
                · -- window 6
                  rw [show decide (48 ≤ i ∧ i < 48 + 8) = true from decide_eq_true ⟨g5, by omega⟩,
                      show decide (i < 64) = true from decide_eq_true h64,
                      show decide (i < 8) = false from decide_eq_false (by omega),
                      show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
                      show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
                      show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
                      show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
                      show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
                      show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega)]
                  simp
                · -- window 7: i ≥ 56, i < 64
                  rw [show decide (56 ≤ i ∧ i < 56 + 8) = true from decide_eq_true ⟨g6, by omega⟩,
                      show decide (i < 64) = true from decide_eq_true h64,
                      show decide (i < 8) = false from decide_eq_false (by omega),
                      show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
                      show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
                      show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
                      show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
                      show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
                      show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega)]
                  simp
  · -- i ≥ 64
    have hn : ¬ (i < 64) := by omega
    have hB : val.toNat.testBit i = false := by
      apply Nat.testBit_lt_two_pow
      have hp : (2 : Nat) ^ 64 ≤ 2 ^ i :=
        Nat.pow_le_pow_right (by omega) (by omega)
      omega
    rw [show decide (i < 64) = false from decide_eq_false hn,
        show decide (i < 8) = false from decide_eq_false (by omega),
        show decide (8 ≤ i ∧ i < 8 + 8) = false from decide_eq_false (by omega),
        show decide (16 ≤ i ∧ i < 16 + 8) = false from decide_eq_false (by omega),
        show decide (24 ≤ i ∧ i < 24 + 8) = false from decide_eq_false (by omega),
        show decide (32 ≤ i ∧ i < 32 + 8) = false from decide_eq_false (by omega),
        show decide (40 ≤ i ∧ i < 40 + 8) = false from decide_eq_false (by omega),
        show decide (48 ≤ i ∧ i < 48 + 8) = false from decide_eq_false (by omega),
        show decide (56 ≤ i ∧ i < 56 + 8) = false from decide_eq_false (by omega),
        show val.toNat.testBit i = false from hB]
    simp

/-- Memory read-after-write at non-overlapping address.
    Proved: `mem_write_u64` only touches addresses [addr1, addr1+7]. -/
@[simp] theorem memw_untouched (mem : Nat → UInt8) (a i : Nat) (val : UInt64)
    (hd : i < a ∨ a + 8 ≤ i) :
    mem_write_u64 mem a val i = mem i := by
  simp only [mem_write_u64]
  repeat' split
  all_goals first
    | rfl
    | (exfalso; rcases hd with h | h <;> omega)

@[simp] theorem mem_read_after_write_u64_ne (mem : Nat → UInt8) (addr1 addr2 : Nat) (val : UInt64)
    (h : addr2 + 8 ≤ addr1 ∨ addr1 + 8 ≤ addr2) :
    mem_read_u64 (mem_write_u64 mem addr1 val) addr2 = mem_read_u64 mem addr2 := by
  rcases h with h | h
  · unfold mem_read_u64
    rw [show mem_write_u64 mem addr1 val addr2 = mem addr2 from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 1) = mem (addr2 + 1) from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 2) = mem (addr2 + 2) from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 3) = mem (addr2 + 3) from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 4) = mem (addr2 + 4) from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 5) = mem (addr2 + 5) from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 6) = mem (addr2 + 6) from memw_untouched _ _ _ _ (Or.inl (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 7) = mem (addr2 + 7) from memw_untouched _ _ _ _ (Or.inl (by omega))]
  · unfold mem_read_u64
    rw [show mem_write_u64 mem addr1 val addr2 = mem addr2 from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 1) = mem (addr2 + 1) from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 2) = mem (addr2 + 2) from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 3) = mem (addr2 + 3) from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 4) = mem (addr2 + 4) from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 5) = mem (addr2 + 5) from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 6) = mem (addr2 + 6) from memw_untouched _ _ _ _ (Or.inr (by omega)),
        show mem_write_u64 mem addr1 val (addr2 + 7) = mem (addr2 + 7) from memw_untouched _ _ _ _ (Or.inr (by omega))]

/-- Reading slot 1 of an STP-style double write returns slot 1's value,
    provided the two slots do not overlap. -/
theorem mem_read_two_writes_same (mem : Nat → UInt8) (a b : Nat) (v w : UInt64)
    (h : a + 8 ≤ b ∨ b + 8 ≤ a) :
    mem_read_u64 (mem_write_u64 (mem_write_u64 mem a v) b w) a = v := by
  have h1 : mem_read_u64 (mem_write_u64 (mem_write_u64 mem a v) b w) a
      = mem_read_u64 (mem_write_u64 mem a v) a :=
    mem_read_after_write_u64_ne (mem_write_u64 mem a v) b a w h
  rw [h1]
  exact mem_read_after_write_u64 mem a v

/-- Adjacent-slot variant: the second STP slot sits at (first + 8), which
    the %2^64-normalized LDP address reproduces syntactically. -/
theorem mem_read_two_writes_adjacent (mem : Nat → UInt8) (a : Nat) (v w : UInt64)
    (hb : a + 8 < 18446744073709551616) :
    mem_read_u64 (mem_write_u64 (mem_write_u64 mem a v)
        ((a + 8) % 18446744073709551616) w) a = v := by
  rw [show (a + 8) % 18446744073709551616 = a + 8 from Nat.mod_eq_of_lt hb]
  exact mem_read_two_writes_same mem a (a + 8) v w (Or.inl (by omega))


/-- Generic two-write reload with the second address given by an equation. -/
theorem mem_read_two_writes (mem : Nat → UInt8) (a b : Nat) (v w : UInt64)
    (h : b = a + 8) :
    mem_read_u64 (mem_write_u64 (mem_write_u64 mem a v) b w) a = v := by
  subst h
  exact mem_read_two_writes_same mem a (a + 8) v w (Or.inl (by omega))

/-- **Push/pop low-slot read.**  A pair `(v, w)` is pushed at the slots
    `sp - 16` and `(sp - 16) + 8` (the `stp` frame save).  Reading the low slot
    `sp - 16` back returns `v`; the `stp` address is in the `UInt64`-added
    form `(sp - 16) + 8`, so only the `toNat`-of-`+` normalization is needed
    (no no-wrap hypothesis: the `%2^64` case is handled by the adjacent-slot
    lemma below).  This is the general pattern behind every body block's
    `x0 := push; …; pop` value flow, so it lives here rather than in the
    generator. -/
theorem mem_read_two_writes_adjacent' (mem : Nat → UInt8) (a : Nat) (ha : a < 18446744073709551616)
    (v w : UInt64) :
    mem_read_u64 (mem_write_u64 (mem_write_u64 mem a v)
        ((a + 8) % 18446744073709551616) w) a = v := by
  by_cases h : a + 8 < 18446744073709551616
  · rw [Nat.mod_eq_of_lt h]
    exact mem_read_two_writes_same mem a (a + 8) v w (Or.inl (by omega))
  · have hm : (a + 8) % 18446744073709551616 = a + 8 - 18446744073709551616 := by
      rw [Nat.mod_eq_sub_mod (by omega)]
      exact Nat.mod_eq_of_lt (by omega)
    rw [hm]
    exact mem_read_two_writes_same mem a (a + 8 - 18446744073709551616) v w (Or.inr (by omega))

theorem mem_read_push_low (mem : Nat → UInt8) (sp : UInt64) (v w : UInt64) :
    mem_read_u64
      (mem_write_u64 (mem_write_u64 mem (sp - UInt64.ofNat 16).toNat v)
        ((sp - UInt64.ofNat 16) + 8).toNat w) (sp - UInt64.ofNat 16).toNat = v := by
  rw [UInt64.toNat_add]
  have h8 : (8 : UInt64).toNat = 8 := by decide
  rw [h8]
  exact mem_read_two_writes_adjacent' mem (sp - UInt64.ofNat 16).toNat (UInt64.toNat_lt _) v w

/-- Reading the second (high) slot of an STP-like double write survives any
    number of later writes whose addresses are 8-byte-disjoint from it.
    This is the per-instruction frame combinator: the generator peels the
    unrelated writes (one call per instruction) and finishes with the matching
    write.  Each `h` is exactly the disjointness side condition of
    `mem_read_after_write_u64_ne`. -/
theorem mem_read_slot1_through4 (mem : Nat → UInt8) (a b c : UInt64)
    (v29 v30 w19 w20 u0 u2 : UInt64)
    (h1 : (a + 8).toNat + 8 ≤ b.toNat ∨ b.toNat + 8 ≤ (a + 8).toNat)
    (h2 : (a + 8).toNat + 8 ≤ (b + 8).toNat ∨ (b + 8).toNat + 8 ≤ (a + 8).toNat)
    (h3 : (a + 8).toNat + 8 ≤ c.toNat ∨ c.toNat + 8 ≤ (a + 8).toNat)
    (h4 : (a + 8).toNat + 8 ≤ (c + 8).toNat ∨ (c + 8).toNat + 8 ≤ (a + 8).toNat) :
    mem_read_u64
      (mem_write_u64 (mem_write_u64 (mem_write_u64 (mem_write_u64
        (mem_write_u64 (mem_write_u64 mem a.toNat v29) (a + 8).toNat v30)
        b.toNat w19) (b + 8).toNat w20) c.toNat u0) (c + 8).toNat u2)
      (a + 8).toNat = v30 := by
  rw [mem_read_after_write_u64_ne _ _ _ _ h4,
      mem_read_after_write_u64_ne _ _ _ _ h3,
      mem_read_after_write_u64_ne _ _ _ _ h2,
      mem_read_after_write_u64_ne _ _ _ _ h1,
      mem_read_after_write_u64]

/-- Frame combinator with the slot addresses given directly (no `+ 8`), so the
    generator can pass the canonical `sp - UInt64.ofNat K` forms that the
    block effects normalise to.  `A0/A1` are the two slots of the first STP
    (the read slot is `A1`, holding the restored `x30`), `B0/B1` and `C0/C1`
    the two later double-writes.  Each `h*` is the disjointness side condition
    of `mem_read_after_write_u64_ne`; the generator discharges them with
    `u64_slot_disjoint`. -/
theorem mem_read_frame6 (mem : Nat → UInt8)
    (A0 A1 B0 B1 C0 C1 : UInt64)
    (v29 v30 w19 w20 u0 u2 : UInt64)
    (hC1 : A1.toNat + 8 ≤ C1.toNat ∨ C1.toNat + 8 ≤ A1.toNat)
    (hC0 : A1.toNat + 8 ≤ C0.toNat ∨ C0.toNat + 8 ≤ A1.toNat)
    (hB1 : A1.toNat + 8 ≤ B1.toNat ∨ B1.toNat + 8 ≤ A1.toNat)
    (hB0 : A1.toNat + 8 ≤ B0.toNat ∨ B0.toNat + 8 ≤ A1.toNat) :
    mem_read_u64
      (mem_write_u64 (mem_write_u64 (mem_write_u64 (mem_write_u64
        (mem_write_u64 (mem_write_u64 mem A0.toNat v29) A1.toNat v30)
        B0.toNat w19) B1.toNat w20) C0.toNat u0) C1.toNat u2)
      A1.toNat = v30 := by
  rw [mem_read_after_write_u64_ne _ _ _ _ hC1,
      mem_read_after_write_u64_ne _ _ _ _ hC0,
      mem_read_after_write_u64_ne _ _ _ _ hB1,
      mem_read_after_write_u64_ne _ _ _ _ hB0,
      mem_read_after_write_u64]

/-! ## Per-instruction frame address arithmetic

The frame slots of a prologue/epilogue are the `UInt64` addresses
`sp - d` for small literal offsets `d` (multiples of 8).  These lemmas give the
`.toNat` of such an address as a function of `sp.toNat`, splitting on whether
the subtraction wraps.  They are the one-instruction arithmetic facts the
generator needs to discharge the `mem_read_after_write_u64_ne` side conditions
of the frame combinator above, without ever unfolding a composed block. -/

/-- No wrap: `(sp - d).toNat = sp.toNat - d` when `d ≤ sp.toNat`. -/
theorem u64_slot_nowrap (sp : UInt64) {d : Nat} (hd : d < 2^64) (h : d ≤ sp.toNat) :
    (sp - UInt64.ofNat d).toNat = sp.toNat - d := by
  rw [UInt64.toNat_sub_of_le sp (UInt64.ofNat d) (by
    rw [UInt64.le_iff_toNat_le, UInt64.toNat_ofNat', Nat.mod_eq_of_lt hd]; exact h)]
  rw [UInt64.toNat_ofNat', Nat.mod_eq_of_lt hd]

/-- Wrap: `(sp - d).toNat = 2^64 - d + sp.toNat` when `sp.toNat < d`. -/
theorem u64_slot_wrap (sp : UInt64) {d : Nat} (hd : d < 2^64) (h : sp.toNat < d) :
    (sp - UInt64.ofNat d).toNat = 2^64 - d + sp.toNat := by
  rw [UInt64.toNat_sub, UInt64.toNat_ofNat', Nat.mod_eq_of_lt hd]
  apply Nat.mod_eq_of_lt
  have hs := UInt64.toNat_lt sp; omega

/-- Two distinct frame slots `sp - k` and `sp - j` (`j + 8 ≤ k`) occupy
    8-byte-disjoint address ranges.  The `hsum` bound rules out the degenerate
    huge-offset wrap; for the literal offsets the codegen emits it is decided by
    `decide`. -/
theorem u64_slot_disjoint (sp : UInt64) {j k : Nat}
    (hj : j < 2^64) (hk : k < 2^64) (hsum : k + j + 8 ≤ 2^64) (h : j + 8 ≤ k) :
    ((sp - UInt64.ofNat k).toNat) + 8 ≤ (sp - UInt64.ofNat j).toNat ∨
    (sp - UInt64.ofNat j).toNat + 8 ≤ (sp - UInt64.ofNat k).toNat := by
  have hs := UInt64.toNat_lt sp
  rcases Nat.lt_or_ge sp.toNat k with hlt | hge
  · have hk' : (sp - UInt64.ofNat k).toNat = 2^64 - k + sp.toNat := u64_slot_wrap sp hk hlt
    rw [hk']
    rcases Nat.lt_or_ge sp.toNat j with hlt2 | hge2
    · have hj' : (sp - UInt64.ofNat j).toNat = 2^64 - j + sp.toNat := u64_slot_wrap sp hj hlt2
      rw [hj']; left; omega
    · have hj' : (sp - UInt64.ofNat j).toNat = sp.toNat - j := u64_slot_nowrap sp hj hge2
      rw [hj']; right; omega
  · have hk' : (sp - UInt64.ofNat k).toNat = sp.toNat - k := u64_slot_nowrap sp hk hge
    have hge2 : j ≤ sp.toNat := by omega
    have hj' : (sp - UInt64.ofNat j).toNat = sp.toNat - j := u64_slot_nowrap sp hj hge2
    rw [hk', hj']; left; omega

/-- **Frame slot read-through, in `simp`-ready shape.**  Reading the slot
    `sp - UInt64.ofNat k` from a memory whose topmost write is to a disjoint
    slot `sp - UInt64.ofNat j` (`j + 8 ≤ k`) is the read from the older memory.
    This is the single library lemma the generator's value-flow `simp` uses to
    peel unrelated stores; the address arithmetic is discharged by `decide`.
    (The frame-restore proofs use the curried `mem_read_after_write_u64_ne`
    directly with hand-built disjointness facts.) -/
theorem mem_read_after_write_u64_slot (mem : Nat → UInt8) (sp : UInt64) {j k : Nat}
    (hj : j < 2^64) (hk : k < 2^64) (hsum : k + j + 8 ≤ 2^64) (h : j + 8 ≤ k)
    (val : UInt64) :
    mem_read_u64 (mem_write_u64 mem (sp - UInt64.ofNat j).toNat val)
        (sp - UInt64.ofNat k).toNat
      = mem_read_u64 mem (sp - UInt64.ofNat k).toNat :=
  mem_read_after_write_u64_ne mem (sp - UInt64.ofNat j).toNat
    (sp - UInt64.ofNat k).toNat val
    ((u64_slot_disjoint sp hj hk hsum h).elim Or.inl Or.inr)

/-- Mirror orientation of `mem_read_after_write_u64_slot`: the write slot sits
    *below* the read slot (`k + 8 ≤ j`). -/
theorem mem_read_after_write_u64_slot' (mem : Nat → UInt8) (sp : UInt64) {j k : Nat}
    (hj : j < 2^64) (hk : k < 2^64) (hsum : k + j + 8 ≤ 2^64) (h : k + 8 ≤ j)
    (val : UInt64) :
    mem_read_u64 (mem_write_u64 mem (sp - UInt64.ofNat j).toNat val)
        (sp - UInt64.ofNat k).toNat
      = mem_read_u64 mem (sp - UInt64.ofNat k).toNat :=
  mem_read_after_write_u64_ne mem (sp - UInt64.ofNat j).toNat
    (sp - UInt64.ofNat k).toNat val
    ((u64_slot_disjoint sp (j := k) (k := j) hk hj (by omega) h).elim Or.inr Or.inl)

/-! ### Frame store vs. a slot at/above `sp`

`FrameOk`'s memory clause is agreement on the caller's slots `sp + j`
(`j < FRAME`), above the callee's frame.  The store addresses are
`sp - UInt64.ofNat K` (`K ≥ 8`); `K + j + 8 ≤ 2^64` rules out the degenerate
wrap, so the two ranges are 8-byte disjoint for **every** `sp` (no stack-bound
hypothesis needed). -/

/-- A frame store at `sp - K` (`K ≥ 8`) is disjoint from a caller slot at
    `sp + j` (`j` small), for all `sp`. -/
theorem u64_write_read_disjoint (sp : UInt64) {K j : Nat}
    (hK : 8 ≤ K) (hK64 : K < 2^64) (hj : j < 2^63) (hsum : K + j + 8 ≤ 2^64) :
    (sp - UInt64.ofNat K).toNat + 8 ≤ (sp + UInt64.ofNat j).toNat ∨
    (sp + UInt64.ofNat j).toNat + 8 ≤ (sp - UInt64.ofNat K).toNat := by
  have hs := UInt64.toNat_lt sp
  have hj64 : j < 2^64 := by omega
  have hread : (sp + UInt64.ofNat j).toNat = (sp.toNat + j) % 2^64 := by
    rw [UInt64.toNat_add, UInt64.toNat_ofNat', Nat.mod_eq_of_lt hj64]
  rcases Nat.lt_or_ge sp.toNat K with hlt | hge
  · have hw : (sp - UInt64.ofNat K).toNat = 2^64 - K + sp.toNat := u64_slot_wrap sp hK64 hlt
    rw [hw, hread]
    have hlt2 : sp.toNat + j < 2^64 := by omega
    rw [Nat.mod_eq_of_lt hlt2]
    right; omega
  · have hw : (sp - UInt64.ofNat K).toNat = sp.toNat - K := u64_slot_nowrap sp hK64 hge
    rw [hw, hread]
    rcases Nat.lt_or_ge (sp.toNat + j) (2^64) with hlt2 | hge2
    · rw [Nat.mod_eq_of_lt hlt2]; left; omega
    · have hm : (sp.toNat + j) % 2^64 = sp.toNat + j - 2^64 := by
        rw [Nat.mod_eq_sub_mod hge2]
        exact Nat.mod_eq_of_lt (by omega)
      rw [hm]; right; omega

/-- `simp`-ready single-byte consequence: a frame store below `sp` leaves every
    caller slot above `sp` untouched. -/
theorem mem_write_u64_high (mem : Nat → UInt8) (sp : UInt64) {K j : Nat}
    (hK : 8 ≤ K) (hK64 : K < 2^64) (hj : j < 2^63) (hsum : K + j + 8 ≤ 2^64)
    (val : UInt64) :
    mem_write_u64 mem (sp - UInt64.ofNat K).toNat val ((sp + UInt64.ofNat j).toNat)
      = mem ((sp + UInt64.ofNat j).toNat) := by
  apply memw_untouched
  rcases u64_write_read_disjoint sp hK hK64 hj hsum with h | h
  · exact Or.inr h
  · exact Or.inl (by omega)

/-- `simp`-ready read-through for a store below `sp` against a caller slot
    above `sp`. -/
theorem mem_read_after_write_u64_high (mem : Nat → UInt8) (sp : UInt64) {K j : Nat}
    (hK : 8 ≤ K) (hK64 : K < 2^64) (hj : j < 2^63) (hsum : K + j + 8 ≤ 2^64)
    (val : UInt64) :
    mem_read_u64 (mem_write_u64 mem (sp - UInt64.ofNat K).toNat val)
        ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64 mem ((sp + UInt64.ofNat j).toNat) :=
  mem_read_after_write_u64_ne mem (sp - UInt64.ofNat K).toNat
    ((sp + UInt64.ofNat j).toNat) val
    ((u64_write_read_disjoint sp hK hK64 hj hsum).elim Or.inr Or.inl)

/-- **No-wrap frame store vs. a slot at/above `sp`.**  When both the store slot
    `sp - K` (`K ≤ sp.toNat`) and the read address `sp + j` (`sp.toNat + j < 2^64`)
    are in the non-wrapping regime, the store is *unconditionally* below the read
    — the disjointness needs no auxiliary bound.  This is the form the
    no-wrap-guarded `FrameOk.mem` uses. -/
theorem mem_read_after_write_u64_high_nw (mem : Nat → UInt8) (sp : UInt64) {K j : Nat}
    (hK : 8 ≤ K) (hKnw : K ≤ sp.toNat) (hjnw : sp.toNat + j < 2^64) (val : UInt64) :
    mem_read_u64 (mem_write_u64 mem (sp - UInt64.ofNat K).toNat val)
        ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64 mem ((sp + UInt64.ofNat j).toNat) := by
  apply mem_read_after_write_u64_ne
  right
  have hj64 : j < 2^64 := by omega
  have hread : (sp + UInt64.ofNat j).toNat = sp.toNat + j := by
    simp only [UInt64.toNat_add, UInt64.toNat_ofNat']
    rw [Nat.mod_eq_of_lt hj64, Nat.mod_eq_of_lt hjnw]
  rw [u64_slot_nowrap sp (by omega) hKnw, hread]
  omega

/-- **Peel one callee store below `sp`, with the hypotheses `FrameOk` actually
    supplies.**  `FrameOk`'s window clause bounds the read by
    `sp.toNat + j < 2^64`, not by a separate `j < 2^63`, and bounds the store
    distance by `K ≤ sp.toNat`.  This is the no-wrap peel
    `mem_read_after_write_u64_high_nw` with those two bounds, taking `K` and the
    store value *last* so a rewrite can supply them positionally. -/
theorem mem_read_write_below (mem : Nat → UInt8) (sp : UInt64) {K j : Nat}
    (hjnw : sp.toNat + j < 2 ^ 64) (hKsp : K ≤ sp.toNat) (hK : 8 ≤ K)
    (val : UInt64) :
    mem_read_u64 (mem_write_u64 mem (sp - UInt64.ofNat K).toNat val)
        ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64 mem ((sp + UInt64.ofNat j).toNat) :=
  mem_read_after_write_u64_high_nw mem sp hK hKsp hjnw val


/-! ## Canonicalising frame addresses

The composed block effects emit `sp` as a nest of `+`/`-` literals
(`(sp - 16) - 16`, `(sp - 16) + 8`, ...).  These four lemmas flatten such a nest
into the canonical single-subtraction form `sp - UInt64.ofNat K`, which is what
`u64_slot_disjoint` and the frame combinators expect.  They are deliberately not
`@[simp]` (to avoid perturbing existing proofs); the generator lists them
explicitly in the frame simp set. -/

/-- `(sp - a) - b = sp - (a + b)` (bitvector sub is associative). -/
theorem u64_sub_sub (sp a b : UInt64) : (sp - a) - b = sp - (a + b) := by grind

/-- `(sp - a) + b = sp - (a - b)` (moving an addition back under the sub). -/
theorem u64_sub_add (sp a b : UInt64) : (sp - a) + b = sp - (a - b) := by grind

/-- Literal offset addition: `ofNat a + ofNat b = ofNat (a + b)`. -/
theorem u64_ofNat_add (a b : Nat) : UInt64.ofNat a + UInt64.ofNat b = UInt64.ofNat (a + b) := by
  apply UInt64.toNat.inj
  rw [UInt64.toNat_add, UInt64.toNat_ofNat', UInt64.toNat_ofNat', UInt64.toNat_ofNat']
  exact (Nat.add_mod a b (2^64)).symm

/-- Literal offset subtraction (for `b ≤ a < 2^64`):
    `ofNat a - ofNat b = ofNat (a - b)`. -/
theorem u64_ofNat_sub (a b : Nat) (h : b ≤ a) (hM : a < 2^64) :
    UInt64.ofNat a - UInt64.ofNat b = UInt64.ofNat (a - b) := by
  have hb : b < 2^64 := by omega
  have hab : a - b < 2^64 := by omega
  apply UInt64.toNat.inj
  rw [UInt64.toNat_sub, UInt64.toNat_ofNat', UInt64.toNat_ofNat', UInt64.toNat_ofNat',
      Nat.mod_eq_of_lt hM, Nat.mod_eq_of_lt hb, Nat.mod_eq_of_lt hab]
  have : (2^64 - b + a) % 2^64 = a - b := by
    rw [show 2^64 - b + a = 2^64 + (a - b) by omega, Nat.add_mod, Nat.mod_self, Nat.zero_add,
        Nat.mod_mod]
    exact Nat.mod_eq_of_lt hab
  exact this

/-- **Collapse a literal difference back into a single offset.**  `u64_sub_add`
    rewrites `(sp - a) + b` into `sp - (a - b)`, so an STP pair's second half
    (`(sp - 16) + 8`) comes out as `sp - (16 - 8)` rather than the
    `sp - UInt64.ofNat 8` the frame combinators and `mem_read_write_below`
    expect.  This puts it back, so a peeled store stack reduces all the way to
    the base memory. -/
theorem u64_sub_lit_sub (sp : UInt64) (a b : Nat) (h : b ≤ a) (hM : a < 2^64) :
    sp - (UInt64.ofNat a - UInt64.ofNat b) = sp - UInt64.ofNat (a - b) := by
  rw [u64_ofNat_sub a b h hM]

/-- **Frame-window re-index.**  `sp - K = (sp - P) + (P - K)` for `K ≤ P`
    (all `UInt64`, no wrap).  This is the arithmetic that converts an
    entry-relative address `sp - K` into a call-time-relative one
    `call_state.sp + (P - K)` when re-reading FrameOk's window. -/
theorem u64_sub_reindex (sp : UInt64) {P K : Nat} (hK : K ≤ P) (hP : P < 2^64) :
    sp - UInt64.ofNat K = (sp - UInt64.ofNat P) + UInt64.ofNat (P - K) := by
  rw [u64_sub_add,
      show UInt64.ofNat P - UInt64.ofNat (P - K) = UInt64.ofNat (P - (P - K))
        from u64_ofNat_sub P (P - K) (by omega) hP,
      show P - (P - K) = K from by omega]

/-- **Frame-window re-index (upward).**  `(sp - P) + (P + j) = sp + j`.  Used to
    re-read FrameOk's window at an address above the call-time `sp`. -/
theorem u64_add_reindex (sp : UInt64) (P j : Nat) :
    (sp - UInt64.ofNat P) + UInt64.ofNat (P + j) = sp + UInt64.ofNat j := by
  calc (sp - UInt64.ofNat P) + UInt64.ofNat (P + j)
      = (sp - UInt64.ofNat P) + (UInt64.ofNat P + UInt64.ofNat j) := by rw [u64_ofNat_add]
    _ = ((sp - UInt64.ofNat P) + UInt64.ofNat P) + UInt64.ofNat j :=
          (UInt64.add_assoc _ _ _).symm
    _ = sp + UInt64.ofNat j := by
          rw [u64_sub_add,
              show UInt64.ofNat P - UInt64.ofNat P = (0 : UInt64) from by simp]
          simp

/-- **UInt64 subtraction back to Nat, no-wrap form.**  `(a - b).toNat = a.toNat - b`
    for `b < 2^64` *and* `b ≤ a.toNat`; this is the shape the recursion contract
    uses when a level's `sp` is `sp - P` and `P` is known not to exceed `sp`.

    The wrap case is deliberately **not** folded in: there `(a - b).toNat` is
    `2^64 - b + a.toNat`, which is not `a.toNat - b` (e.g. `a = 5, b = 10` gives
    `2^64 - 5`, not `0`).  `u64_slot_wrap` states that form.  Callers that can
    wrap must discharge the no-wrap condition themselves, which is what keeps
    this lemma's `Nat`-truncated subtraction honest. -/
theorem u64_toNat_sub_lit (a : UInt64) (b : Nat) (hb : b < 2 ^ 64) (hge : b ≤ a.toNat) :
    (a - UInt64.ofNat b).toNat = a.toNat - b :=
  u64_slot_nowrap a hb hge

/-- `(a - 1).toNat = a.toNat - 1` for a non-zero `UInt64`, via `u64_toNat_sub_lit`. -/
theorem u64_toNat_sub_one' (a : UInt64) (hne : a ≠ 0) :
    (a - 1).toNat = a.toNat - 1 := by
  have hlt : (1 : Nat) < 2 ^ 64 := by decide
  have hone : (1 : UInt64) = UInt64.ofNat 1 := rfl
  have hne0 : a.toNat ≠ 0 := by
    intro hz
    exact hne (UInt64.toNat_inj.mp (by simpa using hz))
  have hge : (1 : Nat) ≤ a.toNat := by
    have : 0 < a.toNat := Nat.pos_of_ne_zero hne0
    omega
  rw [hone, u64_toNat_sub_lit a 1 hlt hge]

/-- A `dec1`-style decrement hands the callee exactly `n - 1`, so its
    `toNat` sits one below `n`'s — the strict step the frame-descent
    arithmetic needs (`stride * (b + 1) ≤ stride * n`).  Stated on the
    `UInt64` value rather than on `toNat` subtraction because `n - 1` wraps
    when `n = 0`; the `hne` premise rules that case out. -/
theorem u64_sub_one_toNat_le (n x : UInt64) (hne : n ≠ 0) (h : x = n - 1) :
    x.toNat + 1 ≤ n.toNat := by
  subst h
  have hne0 : n.toNat ≠ 0 := by
    intro hz
    exact hne (UInt64.toNat_inj.mp (by simpa using hz))
  have hge : (1 : Nat) ≤ n.toNat := by
    have : 0 < n.toNat := Nat.pos_of_ne_zero hne0
    omega
  have hlt : (1 : Nat) < 2 ^ 64 := by decide
  have hone : (1 : UInt64) = UInt64.ofNat 1 := rfl
  rw [hone]
  rw [u64_toNat_sub_lit n 1 hlt hge]
  omega

/-! # UInt64 arithmetic helpers used by the loop/recursion emitters -/

/-- Stable wrapper for toNat_add with literal modulus — avoids repeated
    2^64-vs-literal defeq checks that blow the native stack in
    context-heavy proofs. -/
theorem u64_toNat_add_lit (a b : UInt64) :
    (a + b).toNat = (a.toNat + b.toNat) % 18446744073709551616 :=
  UInt64.toNat_add a b


theorem u64_ofNat_zero : UInt64.ofNat 0 = 0 := rfl

/-- `¬(0 < n)` on a `UInt64` means `n` is zero, hence `n.toNat = 0`. -/
theorem u64_not_lt_zero_toNat (n : UInt64) (h : ¬(0 < n)) : n.toNat = 0 := by
  have h1 : ¬(0 < n.toNat) := by
    intro hlt
    exact h (UInt64.lt_iff_toNat_lt.mpr hlt)
  omega

theorem u64_add_zero_r (v : UInt64) : v + (0:UInt64) = v := by
  apply UInt64.toNat.inj
  show (v.toNat + (0:UInt64).toNat) % 18446744073709551616 = v.toNat
  simp

theorem u64_add_ofNat_zero_r (v : UInt64) : v + UInt64.ofNat 0 = v := by
  rw [u64_ofNat_zero]
  exact u64_add_zero_r v

theorem u64_sub_zero (v : UInt64) : v - (0:UInt64) = v := by
  simp

theorem u64_ofNat_sub_one (k : Nat) (hk : 1 ≤ k) (hb : k < 18446744073709551616) :
    UInt64.ofNat k - UInt64.ofNat 1 = UInt64.ofNat (k - 1) := by
  apply UInt64.toNat.inj
  simp only [UInt64.toNat_sub]
  have h1 : (UInt64.ofNat 1).toNat = 1 := rfl
  have hk' : (UInt64.ofNat k).toNat = k := by simp; omega
  have hk1 : (UInt64.ofNat (k - 1)).toNat = k - 1 := by simp; omega
  rw [h1, hk', hk1]
  have h64 : (2:Nat) ^ 64 = 18446744073709551616 := rfl
  omega

/-- Get byte from list at index -/
def getByte (bytes : List UInt8) (i : Nat) : UInt8 :=
  match bytes with
  | [] => 0
  | b :: bs => if i = 0 then b else getByte bs (i - 1)

/-- AST types (source language) -/
inductive MojoExpr where
  | int (v : UInt64)
  | bool (v : Bool)
  | var (name : String)
  | unop (op : String) (operand : MojoExpr)
  | binop (op : String) (left : MojoExpr) (right : MojoExpr)
  | call (name : String) (arg : MojoExpr)

inductive MojoStmt where
  | return (expr : MojoExpr)
  | ifstmt (cond : MojoExpr) (then_body : List MojoStmt) (else_body : List MojoStmt)
  | while (cond : MojoExpr) (body : List MojoStmt)
  | assign (name : String) (expr : MojoExpr)
  | exprstmt (expr : MojoExpr)
  | pass

inductive MojoFunc where
  | mk (name : String) (param : String) (body : List MojoStmt) : MojoFunc

/-- Binary exponentiation matching codegen's runtime `**` (result starts at 1;
    while exp > 0: if exp odd: acc *= base; base *= base; exp >>= 1).  Fuel 64
    suffices for any UInt64 exponent. -/
def u64powGo (base exp acc : UInt64) (fuel : Nat) : UInt64 :=
  match fuel with
  | 0 => acc
  | fuel + 1 =>
    if exp = 0 then acc
    else
      let acc' := if (exp &&& 1) = 1 then acc * base else acc
      u64powGo (base * base) (exp >>> 1) acc' fuel

def u64pow (base exp : UInt64) : UInt64 := u64powGo base exp 1 64

/-- Source semantics: evaluate expressions with a call handler for recursion -/
def evalExpr (callFunc : String → UInt64 → UInt64) (e : MojoExpr) (env : String → UInt64) : UInt64 :=
  match e with
  | MojoExpr.int v => v
  | MojoExpr.bool v => if v then 1 else 0
  | MojoExpr.var name => env name
  | MojoExpr.unop "neg" operand => (0 : UInt64) - evalExpr callFunc operand env
  | MojoExpr.unop "not" operand => if evalExpr callFunc operand env = 0 then 1 else 0
  | MojoExpr.unop _ operand => evalExpr callFunc operand env
  | MojoExpr.binop "+" l r => evalExpr callFunc l env + evalExpr callFunc r env
  | MojoExpr.binop "-" l r => evalExpr callFunc l env - evalExpr callFunc r env
  | MojoExpr.binop "*" l r => evalExpr callFunc l env * evalExpr callFunc r env
  | MojoExpr.binop "<=" l r => if evalExpr callFunc l env ≤ evalExpr callFunc r env then 1 else 0
  | MojoExpr.binop "<" l r => if evalExpr callFunc l env < evalExpr callFunc r env then 1 else 0
  | MojoExpr.binop ">" l r => if evalExpr callFunc l env > evalExpr callFunc r env then 1 else 0
  | MojoExpr.binop ">=" l r => if evalExpr callFunc l env ≥ evalExpr callFunc r env then 1 else 0
  | MojoExpr.binop "=" l r => if evalExpr callFunc l env = evalExpr callFunc r env then 1 else 0
  | MojoExpr.binop "!=" l r => if evalExpr callFunc l env ≠ evalExpr callFunc r env then 1 else 0
  | MojoExpr.binop "and" l r => if (evalExpr callFunc l env ≠ 0 ∧ evalExpr callFunc r env ≠ 0) then 1 else 0
  | MojoExpr.binop "or" l r => if (evalExpr callFunc l env ≠ 0 ∨ evalExpr callFunc r env ≠ 0) then 1 else 0
  | MojoExpr.binop "&" l r => evalExpr callFunc l env &&& evalExpr callFunc r env
  | MojoExpr.binop "|" l r => evalExpr callFunc l env ||| evalExpr callFunc r env
  | MojoExpr.binop "^" l r => evalExpr callFunc l env ^^^ evalExpr callFunc r env
  | MojoExpr.binop "/" l r => evalExpr callFunc l env / evalExpr callFunc r env
  | MojoExpr.binop "//" l r => evalExpr callFunc l env / evalExpr callFunc r env
  | MojoExpr.binop "%" l r => evalExpr callFunc l env % evalExpr callFunc r env
  | MojoExpr.binop "<<" l r => evalExpr callFunc l env <<< evalExpr callFunc r env
  | MojoExpr.binop ">>" l r => evalExpr callFunc l env >>> evalExpr callFunc r env
  | MojoExpr.binop "**" l r => u64pow (evalExpr callFunc l env) (evalExpr callFunc r env)
  | MojoExpr.binop _ l r => evalExpr callFunc l env
  | MojoExpr.call name arg => callFunc name (evalExpr callFunc arg env)

/-- Environment-threading evaluator.  Returns the optional result together with
    the final environment, so an `if` branch that assigns a local and then falls
    through carries its updated environment into the trailing statements (the
    previous `Option UInt64`-only evaluator dropped it). -/
def evalBodyEnv (callFunc : String → UInt64 → UInt64) (stmts : List MojoStmt) (env : String → UInt64) :
    Option UInt64 × (String → UInt64) :=
  match stmts with
  | [] => (none, env)
  | MojoStmt.return e :: _ => (some (evalExpr callFunc e env), env)
  | MojoStmt.ifstmt cond tb eb :: rest =>
    let condVal := evalExpr callFunc cond env
    if condVal ≠ 0 then
      let r := evalBodyEnv callFunc tb env
      match r.1 with
      | some v => (some v, r.2)
      | none => evalBodyEnv callFunc rest r.2
    else
      let r := evalBodyEnv callFunc eb env
      match r.1 with
      | some v => (some v, r.2)
      | none => evalBodyEnv callFunc rest r.2
  | MojoStmt.while _ _ :: rest => evalBodyEnv callFunc rest env
  | MojoStmt.assign name e :: rest =>
    let val := evalExpr callFunc e env
    evalBodyEnv callFunc rest (fun n => if n == name then val else env n)
  | MojoStmt.exprstmt _ :: rest => evalBodyEnv callFunc rest env
  | MojoStmt.pass :: rest => evalBodyEnv callFunc rest env

def evalBody (callFunc : String → UInt64 → UInt64) (stmts : List MojoStmt) (env : String → UInt64) : Option UInt64 :=
  (evalBodyEnv callFunc stmts env).1

/-- Evaluate a function by setting up the environment and evaluating its body -/
def evalFunc (f : MojoFunc) (callFunc : String → UInt64 → UInt64) (arg : UInt64) : UInt64 :=
  match f with
  | MojoFunc.mk _ param body =>
    let env := fun name => if name == param then arg else (0 : UInt64)
    match evalBody callFunc body env with
    | some v => v
    | none => 0

/-!
# AST evaluation lemmas (incremental)

Each AST node constructor gets a corresponding lemma.  The main dispatch lemma
`evalFunc_eq_mojo_all` pattern-matches on the function AST and calls per-node
lemmas.  All per-node lemmas currently admit; each will be incrementally
replaced with a real proof. -/

/-- Evaluate a variable reference. -/
theorem evalExpr_var (callFunc : String → UInt64 → UInt64) (name : String) (env : String → UInt64) :
  evalExpr callFunc (MojoExpr.var name) env = env name := by
  rfl

/-- Evaluate an integer constant. -/
theorem evalExpr_int (callFunc : String → UInt64 → UInt64) (v : UInt64) (env : String → UInt64) :
  evalExpr callFunc (MojoExpr.int v) env = v := by
  rfl

/-- Evaluate a boolean constant. -/
theorem evalExpr_bool (callFunc : String → UInt64 → UInt64) (v : Bool) (env : String → UInt64) :
  evalExpr callFunc (MojoExpr.bool v) env = (if v then 1 else 0) := by
  rfl

/-- Evaluate a unary operator expression.  Proved by case analysis on the operator. -/
theorem evalExpr_unop (callFunc : String → UInt64 → UInt64) (op : String) (operand : MojoExpr) (env : String → UInt64) :
  evalExpr callFunc (MojoExpr.unop op operand) env =
  match op with
  | "neg" => (0 : UInt64) - evalExpr callFunc operand env
  | "not" => if evalExpr callFunc operand env = 0 then 1 else 0
  | _ => evalExpr callFunc operand env := by
  by_cases h : op = "neg"; · subst h; rfl
  · by_cases h' : op = "not"; · subst h'; rfl
    · simp [evalExpr, h, h']

/-- Evaluate a binary operator expression.  Proved by case analysis on the operator. -/
theorem evalExpr_binop (callFunc : String → UInt64 → UInt64) (op : String) (l r : MojoExpr) (env : String → UInt64) :
  evalExpr callFunc (MojoExpr.binop op l r) env =
  match op with
  | "+" => evalExpr callFunc l env + evalExpr callFunc r env
  | "-" => evalExpr callFunc l env - evalExpr callFunc r env
  | "*" => evalExpr callFunc l env * evalExpr callFunc r env
  | "<=" => if evalExpr callFunc l env ≤ evalExpr callFunc r env then 1 else 0
  | "<" => if evalExpr callFunc l env < evalExpr callFunc r env then 1 else 0
  | ">" => if evalExpr callFunc l env > evalExpr callFunc r env then 1 else 0
  | ">=" => if evalExpr callFunc l env ≥ evalExpr callFunc r env then 1 else 0
  | "=" => if evalExpr callFunc l env = evalExpr callFunc r env then 1 else 0
  | "!=" => if evalExpr callFunc l env ≠ evalExpr callFunc r env then 1 else 0
  | "and" => if (evalExpr callFunc l env ≠ 0 ∧ evalExpr callFunc r env ≠ 0) then 1 else 0
  | "or" => if (evalExpr callFunc l env ≠ 0 ∨ evalExpr callFunc r env ≠ 0) then 1 else 0
  | "&" => evalExpr callFunc l env &&& evalExpr callFunc r env
  | "|" => evalExpr callFunc l env ||| evalExpr callFunc r env
  | "^" => evalExpr callFunc l env ^^^ evalExpr callFunc r env
  | "/" => evalExpr callFunc l env / evalExpr callFunc r env
  | "//" => evalExpr callFunc l env / evalExpr callFunc r env
  | "%" => evalExpr callFunc l env % evalExpr callFunc r env
  | "<<" => evalExpr callFunc l env <<< evalExpr callFunc r env
  | ">>" => evalExpr callFunc l env >>> evalExpr callFunc r env
  | "**" => u64pow (evalExpr callFunc l env) (evalExpr callFunc r env)
  | _ => evalExpr callFunc l env := by
  by_cases h : op = "+"; · subst h; rfl
  · by_cases h' : op = "-"; · subst h'; rfl
    · by_cases h'' : op = "*"; · subst h''; rfl
      · by_cases h3 : op = "<="; · subst h3; rfl
        · by_cases h4 : op = "<"; · subst h4; rfl
          · by_cases h5 : op = ">"; · subst h5; rfl
            · by_cases h6 : op = ">="; · subst h6; rfl
              · by_cases h7 : op = "="; · subst h7; rfl
                · by_cases h8 : op = "!="; · subst h8; rfl
                  · by_cases h9 : op = "and"; · subst h9; rfl
                    · by_cases h10 : op = "or"; · subst h10; rfl
                      · by_cases h11 : op = "&"; · subst h11; rfl
                        · by_cases h12 : op = "|"; · subst h12; rfl
                          · by_cases h13 : op = "^"; · subst h13; rfl
                            · by_cases h14 : op = "/"; · subst h14; rfl
                              · by_cases h15 : op = "//"; · subst h15; rfl
                                · by_cases h16 : op = "%"; · subst h16; rfl
                                  · by_cases h17 : op = "<<"; · subst h17; rfl
                                    · by_cases h18 : op = ">>"; · subst h18; rfl
                                      · by_cases h19 : op = "**"; · subst h19; rfl
                                        · simp [evalExpr, h, h', h'', h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19]

/-- Evaluate a function call expression. -/
theorem evalExpr_call (callFunc : String → UInt64 → UInt64) (name : String) (arg : MojoExpr) (env : String → UInt64) :
  evalExpr callFunc (MojoExpr.call name arg) env = callFunc name (evalExpr callFunc arg env) := by
  rfl

/-- Evaluate a return statement. -/
theorem evalBody_return (callFunc : String → UInt64 → UInt64) (e : MojoExpr) (env : String → UInt64) :
  evalBody callFunc [MojoStmt.return e] env = some (evalExpr callFunc e env) := by
  simp [evalBody, evalBodyEnv]

/-- single-stmt if-then-else. -/
theorem evalBody_ifstmt (callFunc : String → UInt64 → UInt64) (cond : MojoExpr) (t e : List MojoStmt) (env : String → UInt64) :
  evalBody callFunc [MojoStmt.ifstmt cond t e] env =
  let condVal := evalExpr callFunc cond env
  if condVal ≠ 0 then
    match evalBody callFunc t env with
    | some v => some v
    | none => none
  else
    match evalBody callFunc e env with
    | some v => some v
    | none => none := by
  simp only [evalBody, evalBodyEnv]
  by_cases h : evalExpr callFunc cond env = 0
  · simp only [h, ne_eq, not_true_eq_false, if_false]
    cases evalBodyEnv callFunc e env with
    | mk r env' => cases r <;> rfl
  · simp only [h, ne_eq, not_false_eq_true, if_true]
    cases evalBodyEnv callFunc t env with
    | mk r env' => cases r <;> rfl

/-- single-stmt while (body skipped). -/
theorem evalBody_while (callFunc : String → UInt64 → UInt64) (cond : MojoExpr) (body : List MojoStmt) (env : String → UInt64) :
  evalBody callFunc [MojoStmt.while cond body] env = none := by
  simp [evalBody, evalBodyEnv]

/-- single-stmt assign. -/
theorem evalBody_assign (callFunc : String → UInt64 → UInt64) (name : String) (e : MojoExpr) (env : String → UInt64) :
  evalBody callFunc [MojoStmt.assign name e] env = none := by
  simp [evalBody, evalBodyEnv]

/-- single-stmt exprstmt. -/
theorem evalBody_exprstmt (callFunc : String → UInt64 → UInt64) (e : MojoExpr) (env : String → UInt64) :
  evalBody callFunc [MojoStmt.exprstmt e] env = none := by
  simp [evalBody, evalBodyEnv]

/-- The environment-threading evaluator's assignment clause, on the returned
    environment rather than the result.  `evalBody_assign` gives the `.1`
    projection (a bare assignment returns `none`); this is the `.2` projection,
    which is what a *method*'s semantics needs, since a method's whole point is
    the fields it leaves behind. -/
theorem evalBodyEnv_assign (callFunc : String → UInt64 → UInt64) (name : String)
    (e : MojoExpr) (env : String → UInt64) (rest : List MojoStmt) :
    (evalBodyEnv callFunc (MojoStmt.assign name e :: rest) env).2
      = (evalBodyEnv callFunc rest
          (fun n => if n == name then evalExpr callFunc e env else env n)).2 := by
  simp only [evalBodyEnv]

/-- single-stmt pass. -/
theorem evalBody_pass (callFunc : String → UInt64 → UInt64) (env : String → UInt64) :
  evalBody callFunc [MojoStmt.pass] env = none := by
  simp [evalBody, evalBodyEnv]

/-- UInt64 order bridges for the AST-eval obligations: with the (normalised)
    negation of a comparison in scope, `simp` can discharge the corresponding
    positive comparison to `False`. -/
theorem u64_lt_iff_false_of_le {a b : UInt64} (h : b ≤ a) : (a < b) ↔ False :=
  ⟨fun hab => (UInt64.not_lt.mpr h) hab, False.elim⟩

theorem u64_le_iff_false_of_lt {a b : UInt64} (h : b < a) : (a ≤ b) ↔ False :=
  ⟨fun hab => (UInt64.not_le.mpr h) hab, False.elim⟩

/-- Main AST evaluation lemma.
    Takes a function-specific hypothesis `h_result` (supplied by the per-program
    proof) and uses it to close the equality.
-/
theorem evalFunc_eq_mojo_all (f : MojoFunc) (handler : String → UInt64 → UInt64) (mojo_fn : UInt64 → UInt64) (arg : UInt64)
  (h_result : match f with
    | MojoFunc.mk _ param body =>
      let env := fun name : String => if name == param then arg else 0
      match evalBody handler body env with
      | some v => v = mojo_fn arg
      | none => 0 = mojo_fn arg) : evalFunc f handler arg = mojo_fn arg := by
  unfold evalFunc
  cases f
  rename_i name param body
  dsimp at h_result
  dsimp
  cases h_eq : evalBody handler body (fun name : String => if name == param then arg else 0) with
  | some v =>
    rw [h_eq] at h_result
    exact h_result
  | none =>
    rw [h_eq] at h_result
    exact h_result

/-- UInt64 equality via toNat equality. -/
theorem eq_of_toNat_eq {a b : UInt64} (h : a.toNat = b.toNat) : a = b := by
  calc
    a = UInt64.ofNat a.toNat := by symm; exact UInt64.ofNat_toNat
    _ = UInt64.ofNat b.toNat := by rw [h]
    _ = b := UInt64.ofNat_toNat

/-- Adding 8 never fixes a UInt64: x ≠ x + 8 (8 is not 0 mod 2^64). -/
theorem u64_ne_add8 (x : UInt64) : x ≠ x + UInt64.ofNat 8 := by
  intro h
  have hto := congrArg UInt64.toNat h
  rw [u64_toNat_add_lit] at hto
  simp at hto
  by_cases hlt : x.toNat + 8 < 18446744073709551616
  · have hmod : (x.toNat + 8) % 18446744073709551616 = x.toNat + 8 := by omega
    rw [hmod] at hto
    omega
  · have hge : 18446744073709551616 ≤ x.toNat + 8 := by omega
    have hmod : (x.toNat + 8) % 18446744073709551616
        = x.toNat + 8 - 18446744073709551616 := by omega
    rw [hmod] at hto
    omega

/-- When n ≠ 0, (n-1).toNat = n.toNat - 1. -/
theorem toNat_sub_one (n : UInt64) (h : n ≠ 0) : (n - 1).toNat = n.toNat - 1 := by
  rw [UInt64.toNat_sub]
  have hpos : 1 ≤ n.toNat := by
    have hzero : n.toNat ≠ 0 := by
      intro hz
      apply h
      calc
        n = UInt64.ofNat n.toNat := by symm; exact UInt64.ofNat_toNat
        _ = UInt64.ofNat 0 := by rw [hz]
        _ = 0 := rfl
    omega
  have hbound : n.toNat < 2^64 := UInt64.toNat_lt n
  have h2 : n.toNat - 1 < 2^64 := by omega
  calc
    (2^64 - (1 : UInt64).toNat + n.toNat) % 2^64 = (2^64 - 1 + n.toNat) % 2^64 := by
      have h1 : (1 : UInt64).toNat = 1 := by native_decide
      rw [h1]
    _ = (2^64 + (n.toNat - 1)) % 2^64 := by omega
    _ = ((2^64 % 2^64) + ((n.toNat - 1) % 2^64)) % 2^64 := by rw [Nat.add_mod]
    _ = (0 + ((n.toNat - 1) % 2^64)) % 2^64 := by simp
    _ = (n.toNat - 1) % 2^64 := by simp
    _ = n.toNat - 1 := Nat.mod_eq_of_lt h2

/-- Successor form of `toNat_sub_one`, phrased so it is usable as a rewrite
    when the recursion step hypothesis is `arg.toNat = k + 1`: it turns the
    recursive argument `arg - 1` back into `k`.  This is the one-instruction
    fact behind the linear-recursion terminal (`{name}_go (arg-1).toNat =
    {name}_go arg.toNat`). -/
theorem uint64_sub_one_toNat_of_succ (arg : UInt64) {k : Nat} (hk : arg.toNat = k + 1) :
    (arg - 1).toNat = k := by
  have hne : arg ≠ 0 := by intro h; rw [h] at hk; simp at hk
  rw [toNat_sub_one arg hne]; omega

/-- When n ≠ 0,1, (n-2).toNat = n.toNat - 2. -/
theorem toNat_sub_two (n : UInt64) (h0 : n ≠ 0) (h1 : n ≠ 1) : (n - 2).toNat = n.toNat - 2 := by
  rw [UInt64.toNat_sub]
  have hpos : 2 ≤ n.toNat := by
    have hzero' : n.toNat ≠ 0 := by intro hz; apply h0; apply eq_of_toNat_eq hz
    have hone' : n.toNat ≠ 1 := by intro hz; apply h1; apply eq_of_toNat_eq hz
    omega
  have hbound : n.toNat < 2^64 := UInt64.toNat_lt n
  have h2 : n.toNat - 2 < 2^64 := by omega
  calc
    (2^64 - (2 : UInt64).toNat + n.toNat) % 2^64 = (2^64 - 2 + n.toNat) % 2^64 := by
      have h2nat : (2 : UInt64).toNat = 2 := by native_decide
      rw [h2nat]
    _ = (2^64 + (n.toNat - 2)) % 2^64 := by omega
    _ = ((2^64 % 2^64) + ((n.toNat - 2) % 2^64)) % 2^64 := by rw [Nat.add_mod]
    _ = (0 + ((n.toNat - 2) % 2^64)) % 2^64 := by simp
    _ = (n.toNat - 2) % 2^64 := by simp
    _ = n.toNat - 2 := Nat.mod_eq_of_lt h2

/-- Helper: derive False from n.toNat = 0 and n.toNat ≥ 2. -/
theorem uint64_toNat_ge_two_ne_zero {n : UInt64} (h0 : n.toNat = 0) (h_ge : n.toNat ≥ 2) : False := by
  omega

/-- The `dec2` step of a tree recursion: with `n` at least 2, `(n - 2).toNat`
    sits two below `n`'s, so the callee's `(arg - 2 + 1) = arg - 1` levels
    fit well inside the caller's reservation.  The `dec1` counterpart is
    `u64_sub_one_toNat_le`; both are stated on the `UInt64` value because `n - d`
    wraps when `n < d`, which the non-zero premises rule out. -/
theorem u64_sub_two_toNat_le (n x : UInt64) (h0 : n ≠ 0) (h1 : n ≠ 1)
    (h : x = n - 2) :
    x.toNat + 1 ≤ n.toNat := by
  subst h
  rw [toNat_sub_two n h0 h1]
  have hpos : 2 ≤ n.toNat := by
    have hzero' : n.toNat ≠ 0 := by
      intro hz
      exact h0 (eq_of_toNat_eq hz)
    have hone' : n.toNat ≠ 1 := by
      intro hz
      exact h1 (eq_of_toNat_eq hz)
    omega
  omega

/-- A `UInt64` is its `toNat` cast back (`ofNat` is injective on the range). -/
theorem u64_ofNat_of_toNat {a : UInt64} {k : Nat} (h : a.toNat = k) (hk : k < 2^64) :
    a = UInt64.ofNat k := by
  apply UInt64.toNat.inj
  rw [h, UInt64.toNat_ofNat', Nat.mod_eq_of_lt hk]

/-! ### Exponential fuel arithmetic (tree recursion) -/

theorem one_le_two_pow (k : Nat) : 1 ≤ 2 ^ k := Nat.one_le_pow k 2 (by decide)

theorem mul_two_pow_succ (c k : Nat) : c * 2 ^ (k + 1) = (c * 2) * 2 ^ k := by
  rw [Nat.pow_succ]
  simp only [Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm]

theorem mul_two_pow_add_two (c k : Nat) : c * 2 ^ (k + 2) = (c * 4) * 2 ^ k := by
  rw [show 2 ^ (k + 2) = 2 ^ k * 4 from by
        rw [show k + 2 = k + 2 from rfl, Nat.pow_add]]
  simp only [Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm]

/-- Helper: derive False from n.toNat = 1 and n.toNat ≥ 2. -/
theorem uint64_toNat_ge_two_ne_one {n : UInt64} (h1 : n.toNat = 1) (h_ge : n.toNat ≥ 2) : False := by
  rw [h1] at h_ge
  omega

/-!
# ARM64 Machine Model

Minimal ARM64 (AArch64) machine model for proof-carrying compilation.
32 general-purpose registers (X0-X30), SP, PC, NZCV flags, and memory.
-/

/-- ARM64 machine state: 32 GPRs, SP, PC, NZCV flags, memory -/
structure Arm64State where
  x0 : UInt64
  x1 : UInt64
  x2 : UInt64
  x3 : UInt64
  x4 : UInt64
  x5 : UInt64
  x6 : UInt64
  x7 : UInt64
  x8 : UInt64
  x9 : UInt64
  x10 : UInt64
  x11 : UInt64
  x12 : UInt64
  x13 : UInt64
  x14 : UInt64
  x15 : UInt64
  x16 : UInt64
  x17 : UInt64
  x18 : UInt64
  x19 : UInt64
  x20 : UInt64
  x21 : UInt64
  x22 : UInt64
  x23 : UInt64
  x24 : UInt64
  x25 : UInt64
  x26 : UInt64
  x27 : UInt64
  x28 : UInt64
  x29 : UInt64
  x30 : UInt64
  sp : UInt64
  pc : Nat
  nzcv : UInt8
  mem : Nat → UInt8
  deriving Inhabited

def Arm64State.init (input : UInt64) (entry : Nat) : Arm64State :=
  { x0 := input, x1 := 0, x2 := 0, x3 := 0, x4 := 0, x5 := 0, x6 := 0, x7 := 0,
    x8 := 0, x9 := 0, x10 := 0, x11 := 0, x12 := 0, x13 := 0, x14 := 0, x15 := 0,
    x16 := 0, x17 := 0, x18 := 0, x19 := 0, x20 := 0, x21 := 0, x22 := 0, x23 := 0,
    x24 := 0, x25 := 0, x26 := 0, x27 := 0, x28 := 0, x29 := 0, x30 := 0,
    sp := 0xfffffffffffffff0, pc := entry, nzcv := 0, mem := fun _ => 0 }

/-- Helper function to get register by index. -/
def arm64_reg (i : Nat) (s : Arm64State) : UInt64 :=
  match i with
  | 0 => s.x0 | 1 => s.x1 | 2 => s.x2 | 3 => s.x3 | 4 => s.x4
  | 5 => s.x5 | 6 => s.x6 | 7 => s.x7 | 8 => s.x8 | 9 => s.x9
  | 10 => s.x10 | 11 => s.x11 | 12 => s.x12 | 13 => s.x13 | 14 => s.x14
  | 15 => s.x15 | 16 => s.x16 | 17 => s.x17 | 18 => s.x18 | 19 => s.x19
  | 20 => s.x20 | 21 => s.x21 | 22 => s.x22 | 23 => s.x23 | 24 => s.x24
  | 25 => s.x25 | 26 => s.x26 | 27 => s.x27 | 28 => s.x28 | 29 => s.x29
  | 30 => s.x30 | _ => 0

/-- Helper function to set register by index. -/
def arm64_set_reg (i : Nat) (s : Arm64State) (val : UInt64) : Arm64State :=
  match i with
  | 0 => { s with x0 := val } | 1 => { s with x1 := val } | 2 => { s with x2 := val }
  | 3 => { s with x3 := val } | 4 => { s with x4 := val } | 5 => { s with x5 := val }
  | 6 => { s with x6 := val } | 7 => { s with x7 := val } | 8 => { s with x8 := val }
  | 9 => { s with x9 := val } | 10 => { s with x10 := val } | 11 => { s with x11 := val }
  | 12 => { s with x12 := val } | 13 => { s with x13 := val } | 14 => { s with x14 := val }
  | 15 => { s with x15 := val } | 16 => { s with x16 := val } | 17 => { s with x17 := val }
  | 18 => { s with x18 := val } | 19 => { s with x19 := val } | 20 => { s with x20 := val }
  | 21 => { s with x21 := val } | 22 => { s with x22 := val } | 23 => { s with x23 := val }
  | 24 => { s with x24 := val } | 25 => { s with x25 := val } | 26 => { s with x26 := val }
  | 27 => { s with x27 := val } | 28 => { s with x28 := val } | 29 => { s with x29 := val }
  | 30 => { s with x30 := val } | _ => s

/-- Register projection is unaffected by non-register field updates. -/
@[simp] theorem arm64_reg_pc (j : Nat) (s : Arm64State) (p : Nat) :
    arm64_reg j { s with pc := p } = arm64_reg j s := by
  cases j <;> rfl

@[simp] theorem arm64_reg_sp (j : Nat) (s : Arm64State) (v : UInt64) :
    arm64_reg j { s with sp := v } = arm64_reg j s := by
  cases j <;> rfl

@[simp] theorem arm64_reg_mem (j : Nat) (s : Arm64State) (m : Nat → UInt8) :
    arm64_reg j { s with mem := m } = arm64_reg j s := by
  cases j <;> rfl

@[simp] theorem arm64_reg_nzcv (j : Nat) (s : Arm64State) (c : UInt8) :
    arm64_reg j { s with nzcv := c } = arm64_reg j s := by
  cases j <;> rfl

/-- Setting register i, reading register j: same index reads the new value. -/
@[simp] theorem arm64_set_reg_reg_eq (i : Nat) (s : Arm64State) (v : UInt64)
    (hi : i < 31) : arm64_reg i (arm64_set_reg i s v) = v := by
  have h : i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 ∨ i = 5 ∨ i = 6 ∨ i = 7 ∨
      i = 8 ∨ i = 9 ∨ i = 10 ∨ i = 11 ∨ i = 12 ∨ i = 13 ∨ i = 14 ∨ i = 15 ∨
      i = 16 ∨ i = 17 ∨ i = 18 ∨ i = 19 ∨ i = 20 ∨ i = 21 ∨ i = 22 ∨ i = 23 ∨
      i = 24 ∨ i = 25 ∨ i = 26 ∨ i = 27 ∨ i = 28 ∨ i = 29 ∨ i = 30 := by omega
  rcases h with h | h | h | h | h | h | h | h | h | h | h | h | h | h | h | h |
      h | h | h | h | h | h | h | h | h | h | h | h | h | h | h
  all_goals subst i <;> rfl

/-- Setting a register leaves `sp` unchanged (no record expansion). -/
@[simp] theorem arm64_set_reg_sp (i : Nat) (s : Arm64State) (v : UInt64) :
    (arm64_set_reg i s v).sp = s.sp := by
  unfold arm64_set_reg
  split <;> rfl

/-- Setting register i, reading the same register i yields the new value.
    (i in 0..30; proved by finite case split.) -/
theorem arm64_set_reg_reg_same (i : Nat) (s : Arm64State) (v : UInt64)
    (hi : i < 31) : arm64_reg i (arm64_set_reg i s v) = v := by
  have : i = 0 ∨ i = 1 ∨ i = 2 ∨ i = 3 ∨ i = 4 ∨ i = 5 ∨ i = 6 ∨ i = 7 ∨
      i = 8 ∨ i = 9 ∨ i = 10 ∨ i = 11 ∨ i = 12 ∨ i = 13 ∨ i = 14 ∨ i = 15 ∨
      i = 16 ∨ i = 17 ∨ i = 18 ∨ i = 19 ∨ i = 20 ∨ i = 21 ∨ i = 22 ∨ i = 23 ∨
      i = 24 ∨ i = 25 ∨ i = 26 ∨ i = 27 ∨ i = 28 ∨ i = 29 ∨ i = 30 := by omega
  rcases this with hi0 | hi1 | hi2 | hi3 | hi4 | hi5 | hi6 | hi7 |
      hi8 | hi9 | hi10 | hi11 | hi12 | hi13 | hi14 | hi15 |
      hi16 | hi17 | hi18 | hi19 | hi20 | hi21 | hi22 | hi23 |
      hi24 | hi25 | hi26 | hi27 | hi28 | hi29 | hi30
  all_goals subst i <;> rfl

/- Specific cases of register preservation after set_reg. -/
@[simp] theorem arm64_reg_1_arm64_set_reg_0 (s : Arm64State) (v : UInt64) :
    arm64_reg 1 (arm64_set_reg 0 s v) = arm64_reg 1 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_2_arm64_set_reg_0 (s : Arm64State) (v : UInt64) :
    arm64_reg 2 (arm64_set_reg 0 s v) = arm64_reg 2 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_19_arm64_set_reg_0 (s : Arm64State) (v : UInt64) :
    arm64_reg 19 (arm64_set_reg 0 s v) = arm64_reg 19 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_0_arm64_set_reg_1 (s : Arm64State) (v : UInt64) :
    arm64_reg 0 (arm64_set_reg 1 s v) = arm64_reg 0 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_2_arm64_set_reg_1 (s : Arm64State) (v : UInt64) :
    arm64_reg 2 (arm64_set_reg 1 s v) = arm64_reg 2 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_19_arm64_set_reg_1 (s : Arm64State) (v : UInt64) :
    arm64_reg 19 (arm64_set_reg 1 s v) = arm64_reg 19 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_0_arm64_set_reg_2 (s : Arm64State) (v : UInt64) :
    arm64_reg 0 (arm64_set_reg 2 s v) = arm64_reg 0 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_1_arm64_set_reg_2 (s : Arm64State) (v : UInt64) :
    arm64_reg 1 (arm64_set_reg 2 s v) = arm64_reg 1 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_19_arm64_set_reg_2 (s : Arm64State) (v : UInt64) :
    arm64_reg 19 (arm64_set_reg 2 s v) = arm64_reg 19 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_0_arm64_set_reg_19 (s : Arm64State) (v : UInt64) :
    arm64_reg 0 (arm64_set_reg 19 s v) = arm64_reg 0 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_1_arm64_set_reg_19 (s : Arm64State) (v : UInt64) :
    arm64_reg 1 (arm64_set_reg 19 s v) = arm64_reg 1 s := by
  unfold arm64_reg arm64_set_reg
  rfl

@[simp] theorem arm64_reg_2_arm64_set_reg_19 (s : Arm64State) (v : UInt64) :
    arm64_reg 2 (arm64_set_reg 19 s v) = arm64_reg 2 s := by
  unfold arm64_reg arm64_set_reg
  rfl


/-- Read a 32-bit instruction from code memory (little-endian). -/
def arm64_read_insn (code : Nat → UInt8) (pc : Nat) : UInt32 :=
  ((code pc).toUInt32) |||
  ((code (pc + 1)).toUInt32 <<< 8) |||
  ((code (pc + 2)).toUInt32 <<< 16) |||
  ((code (pc + 3)).toUInt32 <<< 24)

/-- Check if condition code matches NZCV flags. -/
def arm64_matches_condition (cond : Nat) (nzcv : UInt8) : Bool :=
  let n := (nzcv >>> 0) &&& 0x1
  let z := (nzcv >>> 1) &&& 0x1
  let c := (nzcv >>> 2) &&& 0x1
  let v := (nzcv >>> 3) &&& 0x1
  if cond = 0 then z = 1
  else if cond = 1 then z = 0
  else if cond = 2 then c = 1
  else if cond = 3 then c = 0
  else if cond = 4 then n = 1
  else if cond = 5 then n = 0
  else if cond = 6 then v = 1
  else if cond = 7 then v = 0
  else if cond = 8 then c = 1 ∧ z = 0
  else if cond = 9 then c = 0 ∨ z = 1
  else if cond = 10 then n = v
  else if cond = 11 then n ≠ v
  else if cond = 12 then z = 0 ∧ n = v
  else if cond = 13 then z = 1 ∨ n ≠ v
  else false

/-- NZCV flags produced by a subtraction `a - b`: N (result sign), Z (result
    zero), C (no borrow, i.e. `a ≥ b` unsigned) and V (signed overflow). -/
def arm64_subs_flags (a b : UInt64) : UInt8 :=
  let diff := a - b
  let v := ((a ^^^ b) &&& (a ^^^ diff)) >>> 63
  (if diff = 0 then 0x2 else if (diff >>> 63) = 1 then 0x1 else 0)
    ||| (if a ≥ b then 0x4 else 0)
    ||| (if v = 1 then 0x8 else 0)

/-- Zero-extend (mask) the low 8/16/32 bits of a 64-bit value. -/
def t8u (x : UInt64) : UInt64 := x &&& 0xff
def t16u (x : UInt64) : UInt64 := x &&& 0xffff
def t32u (x : UInt64) : UInt64 := x &&& 0xffffffff
/-- Sign-extend the low 8/16/32 bits of a 64-bit value to 64 bits.  These are
    the single source of truth shared by the ARM64 step function (SXTB/SXTH/
    SXTW) and the typed semantic model. -/
def t8s (x : UInt64) : UInt64 :=
  let b := x &&& 0xff
  if (b >>> 7) = 1 then b ||| (0xffffffffffffff00 : UInt64) else b
def t16s (x : UInt64) : UInt64 :=
  let b := x &&& 0xffff
  if (b >>> 15) = 1 then b ||| (0xffffffffffff0000 : UInt64) else b
def t32s (x : UInt64) : UInt64 :=
  let b := x &&& 0xffffffff
  if (b >>> 31) = 1 then b ||| (0xffffffff00000000 : UInt64) else b
/-- SXTW after SXTB/SXTH is a no-op: the narrower sign-extension already
    yields a fully sign-extended 64-bit value. -/
theorem t32s_t8s (x : UInt64) : t32s (t8s x) = t8s x := by
  unfold t32s t8s
  bv_decide
theorem t32s_t16s (x : UInt64) : t32s (t16s x) = t16s x := by
  unfold t32s t16s
  bv_decide

/-- Signed interpretation of a 64-bit pattern as an Int (two's complement). -/
def u64_toS64 (x : UInt64) : Int :=
  if (x >>> 63) = 1 then (Int.ofNat x.toNat) - (2^64 : Int) else Int.ofNat x.toNat

/-- Re-encode an Int as a 64-bit pattern (mod 2^64). -/
def s64_to_u64 (x : Int) : UInt64 :=
  UInt64.ofNat (x.emod (2^64 : Int)).toNat

/-- Signed 64-bit division truncating toward 0; 0 when divisor is 0 (UDIV/SDIV
    architectural behaviour — codegen's CBZ div0 path traps before this). -/
def sdiv64 (a b : UInt64) : UInt64 :=
  if b = 0 then 0
  else s64_to_u64 (Int.tdiv (u64_toS64 a) (u64_toS64 b))

/-- Signed 64-bit remainder truncating toward 0; 0 when divisor is 0.
    Matches MSUB after SDIV: a - (a / b) * b. -/
def srem64 (a b : UInt64) : UInt64 :=
  if b = 0 then 0
  else s64_to_u64 (Int.tmod (u64_toS64 a) (u64_toS64 b))

/-- Arithmetic (sign-extending) shift right of a 64-bit pattern by `sh` (mod 64). -/
def asr64 (x : UInt64) (sh : UInt64) : UInt64 :=
  let s := sh.toNat % 64
  if s = 0 then x
  else if (x >>> 63) = 1 then
    (x >>> UInt64.ofNat s) ||| ((0xffffffffffffffff : UInt64) <<< UInt64.ofNat (64 - s))
  else x >>> UInt64.ofNat s

/-- ARM64 step function: decode and execute one instruction. -/
def arm64_step (s : Arm64State) (code : Nat → UInt8) : Option Arm64State :=
  let insn := arm64_read_insn code s.pc
  -- RET (BR X30): 0xd65f03c0
  if insn = 0xd65f03c0 then
    some { s with pc := s.x30.toNat }
  -- MOV (ORR Xd, XZR, Xn): 0x2A00FA00
  else if (insn &&& 0xffe00000) = 0x2A00FA00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let val := arm64_reg rn s
    some (arm64_set_reg rd s val)
  -- ADD Xd, Xn, Xm (register): 0x8b000000
  else if (insn &&& 0xffe00000) = 0x8b000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let result := (arm64_reg rn s + arm64_reg xm s)
    some (arm64_set_reg rd s result)
  -- SUB Xd, Xn, Xm (register): 0xcb000000
  else if (insn &&& 0xffe00000) = 0xcb000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let result := (arm64_reg rn s - arm64_reg xm s)
    some (arm64_set_reg rd s result)
  -- MUL Xd, Xn, Xm: 0x9b007c00
  else if (insn &&& 0xffe07c00) = 0x9b007c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let result := (arm64_reg rn s * arm64_reg xm s)
    some (arm64_set_reg rd s result)
  -- NEG Xd, Xn: 0xcb0003e0
  else if (insn &&& 0xfffffc1f) = 0xcb0003e0 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 16) &&& 0x1f).toNat
    let val := arm64_reg rn s
    let result := -val
    some (arm64_set_reg rd s result)
  -- CMP Xn, Xm (register): 0xeb000000
  else if (insn &&& 0xffe00000) = 0xeb000000 then
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some { s with nzcv := arm64_subs_flags (arm64_reg rn s) (arm64_reg xm s) }
  -- AND Xd, Xn, Xm: 0x8a000000
  else if (insn &&& 0xffe00000) = 0x8a000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let result := (arm64_reg rn s &&& arm64_reg xm s)
    some (arm64_set_reg rd s result)
  -- EOR Xd, Xn, Xm: 0xca000000
  else if (insn &&& 0xffe00000) = 0xca000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    let val1 := arm64_reg rn s
    let val2 := arm64_reg xm s
    let result := val1 ^^^ val2
    some (arm64_set_reg rd s result)
  -- ADD Xd, Xn, #imm12: 0x11000000 (32-bit) / 0x91000000 (64-bit)
  else if (insn &&& 0xff800000) = 0x11000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    let result := (arm64_reg rn s + UInt64.ofNat imm12)
    some (arm64_set_reg rd s result)
  else if (insn &&& 0xff800000) = 0x91000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    if rd = 31 then
      let result := (if rn = 31 then s.sp else arm64_reg rn s) + UInt64.ofNat imm12
      some { s with sp := result }
    else
      let base := if rn = 31 then s.sp else arm64_reg rn s
      some (arm64_set_reg rd s (base + UInt64.ofNat imm12))
  -- SUB Xd, Xn, #imm12: 0x51000000 (32-bit) / 0xd1000000 (64-bit)
  else if (insn &&& 0xff800000) = 0x51000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    let result := (arm64_reg rn s - UInt64.ofNat imm12)
    some (arm64_set_reg rd s result)
  else if (insn &&& 0xff800000) = 0xd1000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    if rd = 31 then
      let result := (if rn = 31 then s.sp else arm64_reg rn s) - UInt64.ofNat imm12
      some { s with sp := result }
    else
      let base := if rn = 31 then s.sp else arm64_reg rn s
      some (arm64_set_reg rd s (base - UInt64.ofNat imm12))
  -- CMP Xn, #imm12: 0xf1000000 (64-bit subs xzr, Xn, #imm)
  else if (insn &&& 0xff800000) = 0xf1000000 then
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    some { s with nzcv := arm64_subs_flags (arm64_reg rn s) (UInt64.ofNat imm12) }
  -- B #offset: 0x14000000 (sign-extended 26-bit, x4)
  else if (insn &&& 0xfc000000) = 0x14000000 then
    let imm := (insn &&& 0x03ffffff)
    let off64 : UInt64 := if (imm &&& 0x02000000) ≠ 0 then (UInt64.ofNat imm.toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat imm.toNat
    some { s with pc := (UInt64.ofNat s.pc + off64 * 4).toNat }
  -- BL #offset: 0x94000000 (sign-extended 26-bit, x4)
  else if (insn &&& 0xfc000000) = 0x94000000 then
    let imm := (insn &&& 0x03ffffff)
    let off64 : UInt64 := if (imm &&& 0x02000000) ≠ 0 then (UInt64.ofNat imm.toNat) - (UInt64.ofNat (2^26)) else UInt64.ofNat imm.toNat
    some { s with x30 := UInt64.ofNat (s.pc + 4), pc := (UInt64.ofNat s.pc + off64 * 4).toNat }
  -- CBZ Xn, #offset: 0xb4000000 (sign-extended 19-bit, x4)
  else if (insn &&& 0xff000000) = 0xb4000000 then
    let rn := (insn &&& 0x1f).toNat
    let imm19 := (insn >>> 5) &&& 0x7ffff
    let off64 : UInt64 := if (imm19 &&& 0x40000) ≠ 0 then (UInt64.ofNat imm19.toNat) - (UInt64.ofNat (2^19)) else UInt64.ofNat imm19.toNat
    if arm64_reg rn s = 0 then
      some { s with pc := (UInt64.ofNat s.pc + off64 * 4).toNat }
    else
      some { s with pc := s.pc + 4 }
  -- CBNZ Xn, #offset: 0xb5000000 (sign-extended 19-bit, x4)
  else if (insn &&& 0xff000000) = 0xb5000000 then
    let rn := (insn &&& 0x1f).toNat
    let imm19 := (insn >>> 5) &&& 0x7ffff
    let off64 : UInt64 := if (imm19 &&& 0x40000) ≠ 0 then (UInt64.ofNat imm19.toNat) - (UInt64.ofNat (2^19)) else UInt64.ofNat imm19.toNat
    if arm64_reg rn s ≠ 0 then
      some { s with pc := (UInt64.ofNat s.pc + off64 * 4).toNat }
    else
      some { s with pc := s.pc + 4 }
  -- B.cond: 0x54000000 (sign-extended 19-bit offset, x4). Like CBZ this is
  -- flags-only and names no register; the condition code is the low 4 bits,
  -- and bit 4 is architecturally 0.
  else if (insn &&& 0xff000000) = 0x54000000 then
    let cond := (insn &&& 0xf).toNat
    let imm19 := (insn >>> 5) &&& 0x7ffff
    let off64 : UInt64 := if (imm19 &&& 0x40000) ≠ 0 then (UInt64.ofNat imm19.toNat) - (UInt64.ofNat (2^19)) else UInt64.ofNat imm19.toNat
    if arm64_matches_condition cond s.nzcv then
      some { s with pc := (UInt64.ofNat s.pc + off64 * 4).toNat }
    else
      some { s with pc := s.pc + 4 }
  -- LDR Xt, [Xn, #imm]: 0xF9400000 (unsigned-offset 64-bit LOAD, no writeback)
  --
  -- This case used to be labelled `STR Xt, [SP, #-imm]!` and implemented as a
  -- pre-index store: `sp := sp - imm*8`, one BYTE written at `[sp - imm*8]`,
  -- and `Xt` left alone.  That is wrong on all three counts, and it was wrong
  -- in the one direction a caller cannot notice.  0xF9400000 is the A64
  -- `LDR (immediate, unsigned offset)` encoding -- `size=11, 111, V=0, 01,
  -- opc=01` -- which `formal/arm64.py`'s `encode_ldr_xt_xn_imm` emits
  -- (docstring and all) for every heap read the codegen performs, including
  -- `LDR Xd, [X17]` for a string and `LDR X0, [X9, #8*(i+1)]` for list
  -- elements.  The opcode field that separates LDR from STR is bit 22, so
  -- 0xF9000000 (bit 22 clear) is the store and 0xF9400000 (bit 22 set) is
  -- the load.
  --
  -- Two consequences, both silent.  A load does not write memory, so a frame
  -- reasoning about a program's memory was wrong about every byte it claimed
  -- was untouched.  A load does not move `sp`, so `FrameOk`'s window, every
  -- `FrameBound`, and every `sp`-relative address in the recursion contract
  -- were being carried across a step that the architecture does not perform.
  --
  -- Nothing in `formal/examples/*.mojo` contains this encoding, which is why
  -- the 40-example suite stayed green throughout: the mis-modelled form is
  -- reachable only from a program that touches memory through a non-SP base,
  -- and the examples are register-only.  `bugs/FORMAL_wide_receiver_by_reference.md`
  -- records the measurement and what it gates.
  else if (insn &&& 0xffe00000) = 0xF9400000 then
    let rt := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    let addr := arm64_reg rn s + UInt64.ofNat (imm12 * 8)
    some (arm64_set_reg rt s (mem_read_u64 s.mem addr.toNat))
  -- LDR Xt, [SP], #imm: 0xB9000000
  else if (insn &&& 0xffe00000) = 0xB9000000 then
    let rt := (insn &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    let addr := s.sp.toNat
    let val := mem_read_u64 s.mem addr
    let s' := arm64_set_reg rt s val
    some { s' with sp := s.sp + UInt64.ofNat (imm12 * 8) }
  -- ADRP Xd, #page: 0x90000000 (Xd = page(PC) + sign_extend(imm21) << 12)
  else if (insn &&& 0x9f000000) = 0x90000000 then
    let rd := (insn &&& 0x1f).toNat
    let immlo := ((insn >>> 29) &&& 0x3).toNat
    let immhi := ((insn >>> 5) &&& 0x7ffff).toNat
    let imm21 := immhi * 4 + immlo
    let off : UInt64 := if imm21 ≥ 2^20 then (UInt64.ofNat imm21) - (UInt64.ofNat (2^21)) else UInt64.ofNat imm21
    let pcpage := (UInt64.ofNat s.pc) - ((UInt64.ofNat s.pc) % 4096)
    let val := pcpage + off * 4096
    some (arm64_set_reg rd s val)
  -- STP Xt1, Xt2, [Xn|SP, #imm7*8]! (pre-index): 0xA9800000
  else if (insn &&& 0xffc00000) = 0xA9800000 then
    let rt1 := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let rt2 := ((insn >>> 10) &&& 0x1f).toNat
    let imm7 := ((insn >>> 15) &&& 0x7f).toNat
    let addr := if imm7 ≥ 64 then
                  (if rn = 31 then s.sp else arm64_reg rn s) - UInt64.ofNat ((128 - imm7) * 8)
                else
                  (if rn = 31 then s.sp else arm64_reg rn s) + UInt64.ofNat (imm7 * 8)
    let mem1 := mem_write_u64 s.mem addr.toNat (arm64_reg rt1 s)
    let mem2 := mem_write_u64 mem1 (addr + 8).toNat (arm64_reg rt2 s)
    some { s with sp := addr, mem := mem2 }
  -- LDP Xt1, Xt2, [Xn|SP], #imm7*8 (post-index): 0xA8C00000
  else if (insn &&& 0xffc00000) = 0xA8C00000 then
    let rt1 := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let rt2 := ((insn >>> 10) &&& 0x1f).toNat
    let imm7 := ((insn >>> 15) &&& 0x7f).toNat
    let addr := if rn = 31 then s.sp else arm64_reg rn s
    let val1 := mem_read_u64 s.mem addr.toNat
    let val2 := mem_read_u64 s.mem (addr + 8).toNat
    let s' := arm64_set_reg rt1 s val1
    let s'' := arm64_set_reg rt2 s' val2
    some { s'' with sp := addr + UInt64.ofNat (imm7 * 8) }
  -- MOVZ Xd, #imm16: 0x52800000 (32-bit) / 0xd2800000 (64-bit)
  else if (insn &&& 0xffe00000) = 0x52800000 then
    let rd := (insn &&& 0x1f).toNat
    let imm16 := ((insn >>> 5) &&& 0xffff).toNat
    let val := UInt64.ofNat imm16
    some (arm64_set_reg rd s val)
  else if (insn &&& 0xffe00000) = 0xd2800000 then
    let rd := (insn &&& 0x1f).toNat
    let imm16 := ((insn >>> 5) &&& 0xffff).toNat
    let val := UInt64.ofNat imm16
    some (arm64_set_reg rd s val)
  -- ORR Xd, Xn, Xm (register): 0xaa000000
  else if (insn &&& 0xffe00000) = 0xaa000000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let rm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (arm64_reg rn s ||| arm64_reg rm s))
  -- MOVK Xd, #imm16, LSL #(hw*16): 0x72800000 (32-bit) / 0xf2800000 (64-bit)
  else if (insn &&& 0xff800000) = 0xf2800000 then
    let rd := (insn &&& 0x1f).toNat
    let imm16 := ((insn >>> 5) &&& 0xffff).toNat
    let hw := ((insn >>> 21) &&& 0x3).toNat
    some (arm64_set_reg rd s (arm64_reg rd s ||| (UInt64.ofNat imm16 <<< UInt64.ofNat (hw * 16))))
  else if (insn &&& 0xff800000) = 0x72800000 then
    let rd := (insn &&& 0x1f).toNat
    let imm16 := ((insn >>> 5) &&& 0xffff).toNat
    let hw := ((insn >>> 21) &&& 0x3).toNat
    some (arm64_set_reg rd s (arm64_reg rd s ||| (UInt64.ofNat imm16 <<< UInt64.ofNat (hw * 16))))
  -- MOVN Xd, #imm16: 0x12800000 (32-bit) / 0x92800000 (64-bit)
  else if (insn &&& 0xffe00000) = 0x12800000 then
    let rd := (insn &&& 0x1f).toNat
    let imm16 := ((insn >>> 5) &&& 0xffff).toNat
    let val := UInt64.ofNat (0xffff_ffff - imm16)
    some (arm64_set_reg rd s val)
  else if (insn &&& 0xffe00000) = 0x92800000 then
    let rd := (insn &&& 0x1f).toNat
    let imm16 := ((insn >>> 5) &&& 0xffff).toNat
    let val := UInt64.ofNat (0xffff_ffff_ffff_ffff - imm16)
    some (arm64_set_reg rd s val)
  -- CSET Xd, cond = CSINC Xd, XZR, XZR, invert(cond): 0x9a9f07e0
  else if (insn &&& 0xffff0fe0) = 0x9a9f07e0 then
    let rd := (insn &&& 0x1f).toNat
    let field := (insn >>> 12) &&& 0xf
    let cond := if field &&& 0x1 = 0 then (field + 1).toNat else (field - 1).toNat
    let result := if arm64_matches_condition cond s.nzcv then (1 : UInt64) else (0 : UInt64)
    some (arm64_set_reg rd s result)
  -- STR Xt, [Xn, #imm]: 0xF9000000 (unsigned-offset 64-bit store, no writeback)
  --
  -- The base register was `s.sp` here, hardwired, whatever the instruction
  -- encoded in `Rn`.  The instruction is `STR (immediate, unsigned offset)`,
  -- whose address is `X Rn + imm`, and `formal/arm64.py`'s
  -- `encode_str_xt_xn_imm` emits it that way: `encode_str_xt_xn_imm(src, 17, 0)`
  -- for a string write and `encode_str_xt_xn_imm(..., 7, 0)` / `(..., 0, 0)`
  -- elsewhere.  `Rn = 31` (SP) is the one spelling that agrees with what this
  -- case used to compute, so the bug was invisible for stack traffic and wrong
  -- for every heap write -- silently, because the modelled address was a
  -- perfectly ordinary stack address.
  else if (insn &&& 0xffe00000) = 0xF9000000 then
    let rt := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    let addr := arm64_reg rn s + UInt64.ofNat (imm12 * 8)
    some { s with mem := mem_write_u64 s.mem addr.toNat (arm64_reg rt s) }
  -- LDP Xt, Xn, [SP, #imm]: 0xA9400000 (offset load pair, no writeback)
  else if (insn &&& 0xffc00000) = 0xA9400000 then
    let d1 := ((insn >>> 5) &&& 0x1f).toNat
    let d2 := (insn &&& 0x1f).toNat
    let imm12 := ((insn >>> 10) &&& 0xfff).toNat
    let addr := s.sp + UInt64.ofNat (imm12 * 8)
    let val1 := mem_read_u64 s.mem addr.toNat
    let val2 := mem_read_u64 s.mem (addr + 8).toNat
    let s' := arm64_set_reg d1 s val1
    let s'' := arm64_set_reg d2 s' val2
    some s''
  -- ORN Xd, Xn, Xm: 0x0A200000
  else if (insn &&& 0xffe00000) = 0x0A200000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 10) &&& 0x1f).toNat
    let rm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s ((arm64_reg rn s) ^^^ (0xffffffffffffffff : UInt64) ||| arm64_reg rm s))
  -- BR Xn: 0xD61F0000
  else if (insn &&& 0xfffffc1f) = 0xD61F0000 then
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some { s with pc := (arm64_reg rn s).toNat }
  -- SVC #imm: 0xD4000001 (trap; modelled as a no-op step)
  else if (insn &&& 0xffe0001f) = 0xD4000001 then
    some s
  -- SXTB Wd, Wn: 0x13001c00 (sign-extend byte 0 to 32 bits, zero-extended to 64)
  else if (insn &&& 0xffe0fc00) = 0x13001c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some (arm64_set_reg rd s (t8s (arm64_reg rn s)))
  -- SXTH Wd, Wn: 0x13003c00 (sign-extend halfword 0 to 32 bits, zero-extended to 64)
  else if (insn &&& 0xffe0fc00) = 0x13003c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some (arm64_set_reg rd s (t16s (arm64_reg rn s)))
  -- SXTW Xd, Wn: 0x93407c00 (sign-extend 32 bits to 64 bits)
  else if (insn &&& 0xffe0fc00) = 0x93407c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some (arm64_set_reg rd s (t32s (arm64_reg rn s)))
  -- AND Xd, Xn, #0xff: 0x92401c00 (zero-truncate to 8 bits)
  else if (insn &&& 0xffc0fc00) = 0x92401c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some (arm64_set_reg rd s (t8u (arm64_reg rn s)))
  -- AND Xd, Xn, #0xffff: 0x92403c00 (zero-truncate to 16 bits)
  else if (insn &&& 0xffc0fc00) = 0x92403c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some (arm64_set_reg rd s (t16u (arm64_reg rn s)))
  -- AND Xd, Xn, #0xffffffff: 0x92407c00 (zero-truncate to 32 bits)
  else if (insn &&& 0xffc0fc00) = 0x92407c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    some (arm64_set_reg rd s (t32u (arm64_reg rn s)))
  -- UDIV Xd, Xn, Xm: 0x9ac00800 (unsigned; div0 → 0)
  else if (insn &&& 0xffe0fc00) = 0x9ac00800 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (arm64_reg rn s / arm64_reg xm s))
  -- SDIV Xd, Xn, Xm: 0x9ac00c00 (signed, trunc toward 0; div0 → 0)
  else if (insn &&& 0xffe0fc00) = 0x9ac00c00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (sdiv64 (arm64_reg rn s) (arm64_reg xm s)))
  -- LSLV Xd, Xn, Xm: 0x9ac02000 (shift = Xm mod 64)
  else if (insn &&& 0xffe0fc00) = 0x9ac02000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (arm64_reg rn s <<< arm64_reg xm s))
  -- LSRV Xd, Xn, Xm: 0x9ac02400
  else if (insn &&& 0xffe0fc00) = 0x9ac02400 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (arm64_reg rn s >>> arm64_reg xm s))
  -- ASRV Xd, Xn, Xm: 0x9ac02800 (arithmetic)
  else if (insn &&& 0xffe0fc00) = 0x9ac02800 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (asr64 (arm64_reg rn s) (arm64_reg xm s)))
  -- MSUB Xd, Xn, Xm, Xa: 0x9b008000 (Xd = Xa - Xn*Xm; o0=1 so ≠ MUL)
  else if (insn &&& 0xffe08000) = 0x9b008000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xa := ((insn >>> 10) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some (arm64_set_reg rd s (arm64_reg xa s - (arm64_reg rn s * arm64_reg xm s)))
  -- LSR (UBFM imm, imms=63): 0xd340fc00  — checked before generic LSL/UBFM
  else if (insn &&& 0xffc0fc00) = 0xd340fc00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let immr := ((insn >>> 16) &&& 0x3f).toNat
    some (arm64_set_reg rd s (arm64_reg rn s >>> UInt64.ofNat immr))
  -- ASR (SBFM imm, imms=63): 0x9340fc00
  else if (insn &&& 0xffc0fc00) = 0x9340fc00 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let immr := ((insn >>> 16) &&& 0x3f).toNat
    some (arm64_set_reg rd s (asr64 (arm64_reg rn s) (UInt64.ofNat immr)))
  -- LSL (UBFM imm 64-bit, remaining): 0xd3400000 — imms = 63 - shift
  else if (insn &&& 0xffc00000) = 0xd3400000 then
    let rd := (insn &&& 0x1f).toNat
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let imms := ((insn >>> 10) &&& 0x3f).toNat
    let sh := 63 - imms
    some (arm64_set_reg rd s (arm64_reg rn s <<< UInt64.ofNat sh))
  else
    none

/-- Execute ARM64 instructions until the program terminates or fuel runs out.

Sequential instructions in `arm64_step` do not modify `pc`; the loop
advances `pc` by 4 whenever a step leaves it unchanged (branches, calls
and `ret` set `pc` explicitly). Every instruction, including `ret`, is
*executed*: a `ret` branches to `x30`, exactly as on real hardware, so
nested/recursive calls return to their callers correctly. Execution
stops when the machine reaches a fixed point — an instruction word of
`ret` whose branch target `x30` equals its own address `pc` (the RET
sentinel the compiler appends after the program, with the initial link
register pointing at it) — because stepping there would leave the state
unchanged forever. Top-level structural recursion on fuel so it can be
unfolded in proofs. -/
def arm64_go (st : Arm64State) (code : Nat → UInt8) (fuel : Nat) : Option Arm64State :=
  if fuel = 0 then none
  else if code st.pc = 0xd65f03c0 ∧ st.pc = st.x30.toNat then some st
  else
    match arm64_step st code with
    | none => none
    | some st' =>
        let st'' := if st'.pc = st.pc then { st' with pc := st.pc + 4 } else st'
        arm64_go st'' code (fuel - 1)

def arm64_exec (s : Arm64State) (code : Nat → UInt8) : Option Arm64State :=
  arm64_go s code 1000

/-- Execute ARM64 with explicit fuel limit. -/
def arm64_exec_go (s : Arm64State) (code : Nat → UInt8) (fuel : Nat) : Option Arm64State :=
  arm64_go s code fuel

/-- Execute ARM64 with explicit fuel limit, stopping at a designated exit address.

Unlike `arm64_exec_go`, execution does NOT terminate at the first `ret`
(which would break recursion); instead it runs until `st.pc = exit`.
The exit address should point at a `ret` that the initial link register
(value of `x30`) returns to after the top-level function call returns. -/
def arm64_go_exit (st : Arm64State) (code : Nat → UInt8) (exit : Nat) (fuel : Nat) : Option Arm64State :=
  if fuel = 0 then none
  else if st.pc = exit then some st
  else
    match arm64_step st code with
    | none => none
    | some st' =>
        let st'' := if st'.pc = st.pc then { st' with pc := st.pc + 4 } else st'
        arm64_go_exit st'' code exit (fuel - 1)

def arm64_exec_go_exit (s : Arm64State) (code : Nat → UInt8) (exit : Nat) (fuel : Nat) : Option Arm64State :=
  arm64_go_exit s code exit fuel

/-- Library step lemma: ADD Xd, Xn, Xm.  Hypotheses constrain the full
assembled instruction word (`arm64_read_insn`), not just the low byte. -/
theorem arm64_step_add_reg (s : Arm64State) (code : Nat → UInt8) (rd rn xm : Nat)
    (h_opc : arm64_read_insn code s.pc &&& 0xffe00000 = 0x8b000000)
    (h_rd : (arm64_read_insn code s.pc &&& 0x1f).toNat = rd)
    (h_rn : ((arm64_read_insn code s.pc >>> 5) &&& 0x1f).toNat = rn)
    (h_xm : ((arm64_read_insn code s.pc >>> 16) &&& 0x1f).toNat = xm) :
    arm64_step s code = some (arm64_set_reg rd s (arm64_reg rn s + arm64_reg xm s)) := by
  have hne_ret : arm64_read_insn code s.pc ≠ 0xd65f03c0 := by
    intro he; rw [he] at h_opc
    exact absurd h_opc (by native_decide)
  have hne_mov : ¬ (arm64_read_insn code s.pc &&& 0xffe00000 = 0x2a00fa00) := by
    intro t; rw [h_opc] at t
    exact absurd t (by native_decide)
  unfold arm64_step
  rw [if_neg hne_ret, if_neg hne_mov, if_pos h_opc, h_rd, h_rn, h_xm]

/-- Library step lemma: SUB Xd, Xn, Xm. -/
theorem arm64_step_sub_reg (s : Arm64State) (code : Nat → UInt8) (rd rn xm : Nat)
    (h_opc : arm64_read_insn code s.pc &&& 0xffe00000 = 0xcb000000)
    (h_rd : (arm64_read_insn code s.pc &&& 0x1f).toNat = rd)
    (h_rn : ((arm64_read_insn code s.pc >>> 5) &&& 0x1f).toNat = rn)
    (h_xm : ((arm64_read_insn code s.pc >>> 16) &&& 0x1f).toNat = xm) :
    arm64_step s code = some (arm64_set_reg rd s (arm64_reg rn s - arm64_reg xm s)) := by
  have hne_ret : arm64_read_insn code s.pc ≠ 0xd65f03c0 := by
    intro he; rw [he] at h_opc
    exact absurd h_opc (by native_decide)
  have hne_mov : ¬ (arm64_read_insn code s.pc &&& 0xffe00000 = 0x2a00fa00) := by
    intro t; rw [h_opc] at t
    exact absurd t (by native_decide)
  have hne_add : ¬ (arm64_read_insn code s.pc &&& 0xffe00000 = 0x8b000000) := by
    intro t; rw [h_opc] at t
    exact absurd t (by native_decide)
  unfold arm64_step
  rw [if_neg hne_ret, if_neg hne_mov, if_neg hne_add, if_pos h_opc, h_rd, h_rn, h_xm]

/-- Library step lemma: MUL Xd, Xn, Xm. -/
theorem arm64_step_mul (s : Arm64State) (code : Nat → UInt8) (rd rn xm : Nat)
    (h_opc : arm64_read_insn code s.pc &&& 0xffe07c00 = 0x9b007c00)
    (h_rd : (arm64_read_insn code s.pc &&& 0x1f).toNat = rd)
    (h_rn : ((arm64_read_insn code s.pc >>> 5) &&& 0x1f).toNat = rn)
    (h_xm : ((arm64_read_insn code s.pc >>> 16) &&& 0x1f).toNat = xm) :
    arm64_step s code = some (arm64_set_reg rd s (arm64_reg rn s * arm64_reg xm s)) := by
  have hne_ret : arm64_read_insn code s.pc ≠ 0xd65f03c0 := by
    intro he; rw [he] at h_opc
    exact absurd h_opc (by native_decide)
  have hM : (0xffe07c00 : UInt32) &&& 0xffe00000 = 0xffe00000 := by native_decide
  have hsub : arm64_read_insn code s.pc &&& 0xffe00000 = 0x9b000000 := by
    have := congrArg (fun x => x &&& (0xffe00000 : UInt32)) h_opc
    rwa [UInt32.and_assoc, hM] at this
  have hne_mov : ¬ (arm64_read_insn code s.pc &&& 0xffe00000 = 0x2a00fa00) := by
    intro t; rw [hsub] at t
    exact absurd t (by native_decide)
  have hne_add : ¬ (arm64_read_insn code s.pc &&& 0xffe00000 = 0x8b000000) := by
    intro t; rw [hsub] at t
    exact absurd t (by native_decide)
  have hne_sub : ¬ (arm64_read_insn code s.pc &&& 0xffe00000 = 0xcb000000) := by
    intro t; rw [hsub] at t
    exact absurd t (by native_decide)
  unfold arm64_step
  rw [if_neg hne_ret, if_neg hne_mov, if_neg hne_add, if_neg hne_sub, if_pos h_opc,
      h_rd, h_rn, h_xm]

/-- Distribute an Option match over an if (used to close eval_eq_mojo). -/
@[simp] theorem match_if_distrib {α β : Type} (C : Prop) [Decidable C]
    (f : α → β) (d : β) (a b : Option α) :
  (match (if C then a else b) with
   | some v => f v
   | none => d) =
    (if C then (match a with | some v => f v | none => d)
     else (match b with | some v => f v | none => d)) := by
  by_cases h : C <;> simp [h]

/-- UInt64 values ≤ 1 are 0 or 1. -/
theorem uint64_le_one (n : UInt64) (h : n ≤ 1) : n = 0 ∨ n = 1 := by
  have h' : n.toNat ≤ 1 := UInt64.le_iff_toNat_le.mp h
  have hc : n.toNat = 0 ∨ n.toNat = 1 := by omega
  rcases hc with h0 | h1
  · left; exact (UInt64.toNat_inj.mp (by simpa using h0))
  · right; exact (UInt64.toNat_inj.mp (by simpa using h1))

/-- UInt64 values not ≤ 1 are ≥ 2. -/
theorem uint64_not_le_one_ge_two (n : UInt64) (h : ¬ n ≤ 1) : 2 ≤ n := by
  rw [UInt64.le_iff_toNat_le]
  have h' : ¬ n.toNat ≤ 1 := by simpa [UInt64.le_iff_toNat_le] using h
  simp
  omega

/-! # Fuel-bounded full interpreter (executes while loops)

`evalBody` above skips while loops entirely, so `evalFunc` does not match
the source semantics of loop programs.  `runF` below is a complete
statement interpreter: it threads environments through loops and returns
either a final environment (`done`) or an early return value (`ret`).
Fuel is consumed on every statement pass, giving structural recursion.
-/

inductive RunRes where
  | done (env : String → UInt64)
  | ret (v : UInt64)

def runF (fuel : Nat) (cf : String → UInt64 → UInt64)
    (stmts : List MojoStmt) (env : String → UInt64) : Option RunRes :=
  match fuel with
  | 0 => none
  | f + 1 =>
    match stmts with
    | [] => some (.done env)
    | MojoStmt.return e :: _ => some (.ret (evalExpr cf e env))
    | MojoStmt.ifstmt c tb eb :: rest =>
        if evalExpr cf c env ≠ 0 then
          match runF f cf tb env with
          | some (.ret v) => some (.ret v)
          | some (.done env') => runF f cf rest env'
          | none => none
        else
          match runF f cf eb env with
          | some (.ret v) => some (.ret v)
          | some (.done env') => runF f cf rest env'
          | none => none
    | MojoStmt.while c body :: rest =>
        if evalExpr cf c env ≠ 0 then
          match runF f cf body env with
          | some (.ret v) => some (.ret v)
          | some (.done env') => runF f cf (MojoStmt.while c body :: rest) env'
          | none => none
        else
          runF f cf rest env
    | MojoStmt.assign name e :: rest =>
        let v := evalExpr cf e env
        runF f cf rest (fun n => if n == name then v else env n)
    | MojoStmt.exprstmt _ :: rest => runF f cf rest env
    | MojoStmt.pass :: rest => runF f cf rest env

/-- Fuel-bounded function evaluation: source-level semantics including
while loops.  Agrees with `evalFunc` on programs without whiles. -/
def evalFuncF (fuel : Nat) (f : MojoFunc) (cf : String → UInt64 → UInt64)
    (arg : UInt64) : UInt64 :=
  match f with
  | MojoFunc.mk _ param body =>
    let env := fun name => if name == param then arg else (0 : UInt64)
    match runF fuel cf body env with
    | some (.ret v) => v
    | _ => 0

/-- Convenience lemma: a `return` head evaluates directly. -/
theorem runF_return (fuel : Nat) (cf : String → UInt64 → UInt64)
    (e : MojoExpr) (env : String → UInt64) :
    runF (fuel + 1) cf [MojoStmt.return e] env = some (.ret (evalExpr cf e env)) := by
  unfold runF; simp

/-! ### runF equation lemmas

One lemma per statement shape at successor fuel, so proofs can be pure
`rw`-chains without casing on fuel. -/

theorem runF_nil (f : Nat) (cf : String → UInt64 → UInt64) (env : String → UInt64) :
    runF (f + 1) cf [] env = some (.done env) := rfl

theorem runF_return_eq (f : Nat) (cf : String → UInt64 → UInt64)
    (e : MojoExpr) (env : String → UInt64) :
    runF (f + 1) cf [MojoStmt.return e] env = some (.ret (evalExpr cf e env)) := rfl

theorem runF_assign (f : Nat) (cf : String → UInt64 → UInt64)
    (name : String) (e : MojoExpr) (rest : List MojoStmt) (env : String → UInt64) :
    runF (f + 1) cf (MojoStmt.assign name e :: rest) env =
      runF f cf rest (fun n => if n == name then evalExpr cf e env else env n) := rfl

theorem runF_exprstmt (f : Nat) (cf : String → UInt64 → UInt64)
    (e : MojoExpr) (rest : List MojoStmt) (env : String → UInt64) :
    runF (f + 1) cf (MojoStmt.exprstmt e :: rest) env = runF f cf rest env := rfl

theorem runF_pass (f : Nat) (cf : String → UInt64 → UInt64)
    (rest : List MojoStmt) (env : String → UInt64) :
    runF (f + 1) cf (MojoStmt.pass :: rest) env = runF f cf rest env := rfl

theorem runF_while_done (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (body : List MojoStmt) (rest : List MojoStmt)
    (env env' : String → UInt64)
    (hcond : evalExpr cf c env ≠ 0)
    (hbody : runF f cf body env = some (.done env')) :
    runF (f + 1) cf (MojoStmt.while c body :: rest) env =
      runF f cf (MojoStmt.while c body :: rest) env' := by
  simp only [runF]
  rw [if_pos hcond, hbody]

theorem runF_while_ret (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (body : List MojoStmt) (rest : List MojoStmt)
    (env : String → UInt64) (v : UInt64)
    (hcond : evalExpr cf c env ≠ 0)
    (hbody : runF f cf body env = some (.ret v)) :
    runF (f + 1) cf (MojoStmt.while c body :: rest) env = some (.ret v) := by
  simp only [runF]
  rw [if_pos hcond, hbody]

theorem runF_while_stuck (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (body : List MojoStmt) (rest : List MojoStmt)
    (env : String → UInt64)
    (hcond : evalExpr cf c env ≠ 0)
    (hbody : runF f cf body env = none) :
    runF (f + 1) cf (MojoStmt.while c body :: rest) env = none := by
  simp only [runF]
  rw [if_pos hcond, hbody]

theorem runF_while_false (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (body : List MojoStmt) (rest : List MojoStmt)
    (env : String → UInt64)
    (hcond : evalExpr cf c env = 0) :
    runF (f + 1) cf (MojoStmt.while c body :: rest) env = runF f cf rest env := by
  simp only [runF]
  have hc : ¬ (evalExpr cf c env ≠ 0) := by rw [hcond]; simp
  rw [if_neg hc]

/-- If-condition variants: then-branch returns a value. -/
theorem runF_if_ret_then (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (tb eb rest : List MojoStmt) (env : String → UInt64) (v : UInt64)
    (hcond : evalExpr cf c env ≠ 0)
    (htb : runF f cf tb env = some (.ret v)) :
    runF (f + 1) cf (MojoStmt.ifstmt c tb eb :: rest) env = some (.ret v) := by
  simp only [runF]
  rw [if_pos hcond, htb]

theorem runF_if_done_then (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (tb eb rest : List MojoStmt) (env env' : String → UInt64)
    (hcond : evalExpr cf c env ≠ 0)
    (htb : runF f cf tb env = some (.done env')) :
    runF (f + 1) cf (MojoStmt.ifstmt c tb eb :: rest) env = runF f cf rest env' := by
  simp only [runF]
  rw [if_pos hcond, htb]

theorem runF_if_ret_else (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (tb eb rest : List MojoStmt) (env : String → UInt64) (v : UInt64)
    (hcond : evalExpr cf c env = 0)
    (heb : runF f cf eb env = some (.ret v)) :
    runF (f + 1) cf (MojoStmt.ifstmt c tb eb :: rest) env = some (.ret v) := by
  simp only [runF]
  have hc : ¬ (evalExpr cf c env ≠ 0) := by rw [hcond]; simp
  simp only [if_neg hc, heb]

theorem runF_if_done_else (f : Nat) (cf : String → UInt64 → UInt64)
    (c : MojoExpr) (tb eb rest : List MojoStmt) (env env' : String → UInt64)
    (hcond : evalExpr cf c env = 0)
    (heb : runF f cf eb env = some (.done env')) :
    runF (f + 1) cf (MojoStmt.ifstmt c tb eb :: rest) env = runF f cf rest env' := by
  simp only [runF]
  have hc : ¬ (evalExpr cf c env ≠ 0) := by rw [hcond]; simp
  simp only [if_neg hc, heb]

theorem runF_nil_pos (f : Nat) (hf : 0 < f) (cf : String → UInt64 → UInt64)
    (env : String → UInt64) :
    runF f cf [] env = some (.done env) := by
  cases f with
  | zero => omega
  | succ g => exact runF_nil g cf env

/-! ### arm64_go chaining lemmas -/

/-- Sequential instruction: step succeeds leaving pc unchanged; the loop
bumps pc by 4 and consumes one fuel unit. -/
theorem arm64_go_step_seq {st st' : Arm64State} {code : Nat → UInt8} {f : Nat}
    (hstep : arm64_step st code = some st')
    (hseq : st'.pc = st.pc)
    (hstop : ¬ (code st.pc = 0xd65f03c0 ∧ st.pc = st.x30.toNat)) :
    arm64_go st code (f + 1) = arm64_go { st' with pc := st.pc + 4 } code f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go, if_neg hfnz, if_neg hstop, hstep]
  simp only
  rw [if_pos hseq]
  simp [Nat.add_sub_cancel]

/-- Control-transfer instruction: step succeeds setting a new pc; no bump. -/
theorem arm64_go_step_jump {st st' : Arm64State} {code : Nat → UInt8} {f : Nat}
    (hstep : arm64_step st code = some st')
    (hjump : st'.pc ≠ st.pc)
    (hstop : ¬ (code st.pc = 0xd65f03c0 ∧ st.pc = st.x30.toNat)) :
    arm64_go st code (f + 1) = arm64_go st' code f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go, if_neg hfnz, if_neg hstop, hstep]
  simp only
  rw [if_neg hjump]
  simp [Nat.add_sub_cancel]

/-- Halt at the RET-sentinel fixed point for any positive fuel. -/
theorem arm64_go_halt {s : Arm64State} {code : Nat → UInt8} {f : Nat}
    (hf : f > 0)
    (hret : code s.pc = 0xd65f03c0)
    (hx : s.pc = s.x30.toNat) :
    arm64_go s code f = some s := by
  cases f with
  | zero => omega
  | succ g =>
    have hfnz : ¬ (g + 1 = 0) := by omega
    rw [arm64_go, if_neg hfnz, if_pos ⟨hret, hx⟩]

/-- Sequential step at a literal address (call-site friendly). -/
theorem arm64_go_step_seq_at (st st' : Arm64State) (code : Nat → UInt8) (f : Nat)
    (a x : Nat)
    (hstep : arm64_step st code = some st')
    (hseq : st'.pc = st.pc)
    (hpc : st.pc = a)
    (hx30 : st.x30.toNat = x)
    (hne : ¬ (code a = 0xd65f03c0 ∧ a = x)) :
    arm64_go st code (f + 1) = arm64_go { st' with pc := st.pc + 4 } code f := by
  apply arm64_go_step_seq hstep hseq
  intro hc
  rw [hpc] at hc
  rw [hx30] at hc
  exact hne hc

/-- Control-transfer step at a literal address. -/
theorem arm64_go_step_jump_at (st st' : Arm64State) (code : Nat → UInt8) (f : Nat)
    (a x : Nat)
    (hstep : arm64_step st code = some st')
    (hjump : st'.pc ≠ st.pc)
    (hpc : st.pc = a)
    (hx30 : st.x30.toNat = x)
    (hne : ¬ (code a = 0xd65f03c0 ∧ a = x)) :
    arm64_go st code (f + 1) = arm64_go st' code f := by
  apply arm64_go_step_jump hstep hjump
  intro hc
  rw [hpc] at hc
  rw [hx30] at hc
  exact hne hc

/-- Exit-mode sequential step: only requires the current pc to differ
from the designated exit address (both usually literals). -/
theorem arm64_go_exit_step_seq (st st' : Arm64State) (code : Nat → UInt8)
    (exit f : Nat)
    (hstep : arm64_step st code = some st')
    (hseq : st'.pc = st.pc)
    (hpc : st.pc ≠ exit) :
    arm64_go_exit st code exit (f + 1)
      = arm64_go_exit { x0 := st'.x0, x1 := st'.x1, x2 := st'.x2, x3 := st'.x3, x4 := st'.x4, x5 := st'.x5, x6 := st'.x6, x7 := st'.x7, x8 := st'.x8, x9 := st'.x9, x10 := st'.x10, x11 := st'.x11, x12 := st'.x12, x13 := st'.x13, x14 := st'.x14, x15 := st'.x15, x16 := st'.x16, x17 := st'.x17, x18 := st'.x18, x19 := st'.x19, x20 := st'.x20, x21 := st'.x21, x22 := st'.x22, x23 := st'.x23, x24 := st'.x24, x25 := st'.x25, x26 := st'.x26, x27 := st'.x27, x28 := st'.x28, x29 := st'.x29, x30 := st'.x30, sp := st'.sp, pc := st.pc + 4, nzcv := st'.nzcv, mem := st'.mem } code exit f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hfnz, if_neg hpc, hstep]
  simp only
  rw [if_pos hseq]
  simp only [Nat.add_sub_cancel]

/-- Exit-mode control-transfer step. -/
theorem arm64_go_exit_step_jump (st st' : Arm64State) (code : Nat → UInt8)
    (exit f : Nat)
    (hstep : arm64_step st code = some st')
    (hjump : st'.pc ≠ st.pc)
    (hpc : st.pc ≠ exit) :
    arm64_go_exit st code exit (f + 1)
      = arm64_go_exit { x0 := st'.x0, x1 := st'.x1, x2 := st'.x2, x3 := st'.x3, x4 := st'.x4, x5 := st'.x5, x6 := st'.x6, x7 := st'.x7, x8 := st'.x8, x9 := st'.x9, x10 := st'.x10, x11 := st'.x11, x12 := st'.x12, x13 := st'.x13, x14 := st'.x14, x15 := st'.x15, x16 := st'.x16, x17 := st'.x17, x18 := st'.x18, x19 := st'.x19, x20 := st'.x20, x21 := st'.x21, x22 := st'.x22, x23 := st'.x23, x24 := st'.x24, x25 := st'.x25, x26 := st'.x26, x27 := st'.x27, x28 := st'.x28, x29 := st'.x29, x30 := st'.x30, sp := st'.sp, pc := st'.pc, nzcv := st'.nzcv, mem := st'.mem } code exit f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hfnz, if_neg hpc, hstep]
  simp only
  rw [if_neg hjump]
  simp [Nat.add_sub_cancel]

/-- Terminal: reaching the exit address yields the state, any positive fuel. -/
theorem arm64_go_exit_hit (st : Arm64State) (code : Nat → UInt8)
    (exit f : Nat)
    (hf : f > 0)
    (hpc : st.pc = exit) :
    arm64_go_exit st code exit f = some st := by
  cases f with
  | zero => omega
  | succ g =>
    rw [arm64_go_exit]
    exact if_pos hpc

/-- Exit-mode sequential step, call-site friendly: address + sentinel-x30
explicit, side conditions on closed literals. -/
theorem arm64_go_exit_step_seq_at (st st' : Arm64State) (code : Nat → UInt8)
    (exit f a : Nat)
    (hstep : arm64_step st code = some st')
    (hseq : st'.pc = st.pc)
    (hpc : st.pc = a)
    (hna : a ≠ exit) :
    arm64_go_exit st code exit (f + 1) =
      arm64_go_exit { st' with pc := st.pc + 4 } code exit f := by
  apply arm64_go_exit_step_seq st st' code exit f hstep hseq
  intro hc
  rw [hpc] at hc
  exact hna hc

/-- Exit-mode control-transfer step, call-site friendly. -/
theorem arm64_go_exit_step_jump_at (st st' : Arm64State) (code : Nat → UInt8)
    (exit f a : Nat)
    (hstep : arm64_step st code = some st')
    (hjump : st'.pc ≠ st.pc)
    (hpc : st.pc = a)
    (hna : a ≠ exit) :
    arm64_go_exit st code exit (f + 1) = arm64_go_exit st' code exit f := by
  apply arm64_go_exit_step_jump st st' code exit f hstep hjump
  intro hc
  rw [hpc] at hc
  exact hna hc

/-- Bridge: toNat of a UInt64-sum of ofNats is the wrapped Nat-sum. -/
theorem toNat_uadd (a b : Nat) :
    (UInt64.ofNat a + UInt64.ofNat b).toNat = (a + b) % 18446744073709551616 := by
  rw [UInt64.toNat_add]
  have h1 : (UInt64.ofNat a).toNat = a % 18446744073709551616 := by simp
  have h2 : (UInt64.ofNat b).toNat = b % 18446744073709551616 := by simp
  have h64 : (2 ^ 64 : Nat) = 18446744073709551616 := by decide
  rw [h64]
  exact (Nat.add_mod a b 18446744073709551616).symm

/-- Bridge: toNat of a UInt64-product of ofNats is the wrapped Nat-product. -/
theorem toNat_umul (a b : Nat) :
    (UInt64.ofNat a * UInt64.ofNat b).toNat = (a * b) % 18446744073709551616 := by
  rw [UInt64.toNat_mul]
  have h1 : (UInt64.ofNat a).toNat = a % 18446744073709551616 := by simp
  have h2 : (UInt64.ofNat b).toNat = b % 18446744073709551616 := by simp
  have h64 : (2 ^ 64 : Nat) = 18446744073709551616 := by decide
  rw [h64]
  exact (Nat.mul_mod a b 18446744073709551616).symm

/-- Bridge for BL-shaped pc-updates with K=3, M=4 (most common case).
    General form: toNat(ofNat x + ofNat K * ofNat M) = (x + K*M) % 2^64. -/
theorem toNat_uadd_umul_lit (x : Nat) :
    (UInt64.ofNat x + UInt64.ofNat 3 * UInt64.ofNat 4).toNat =
      (x + 12) % 18446744073709551616 := by
  rw [UInt64.toNat_add]
  rw [UInt64.toNat_mul]
  have h1 : (UInt64.ofNat x).toNat = x % 18446744073709551616 := rfl
  have h2 : (UInt64.ofNat 3).toNat = 3 % 18446744073709551616 := rfl
  have h3 : (UInt64.ofNat 4).toNat = 4 % 18446744073709551616 := rfl
  rw [h1, h2, h3]
  have h64 : (2 ^ 64 : Nat) = 18446744073709551616 := by decide
  rw [h64]
  omega
/-! # Finite step-run iterator and exit-gluing for recursive programs

`arm64_runs code f st` executes exactly `f` steps of the machine (failing only
when the model cannot step). Unlike `arm64_go_exit` it has no halt address,
so one call-frame of a recursive function can be certified as a finite prefix
and then converted into an equation about the fuel-bounded exit run for any
exit address that frame's execution never touches. -/




def arm64_runs (code : Nat → UInt8) : Nat → Arm64State → Option Arm64State
  | 0, st => some st
  | f + 1, st =>
      match arm64_step st code with
      | none => none
      | some st' =>
          arm64_runs code f (if st'.pc = st.pc then { st' with pc := st.pc + 4 } else st')

theorem runs_zero (code : Nat → UInt8) (st : Arm64State) :
    arm64_runs code 0 st = some st := rfl

theorem runs_cons_seq (st st' : Arm64State) (code : Nat → UInt8) (f : Nat)
    (hstep : arm64_step st code = some st')
    (hseq : st'.pc = st.pc) :
    arm64_runs code (f + 1) st = arm64_runs code f { st' with pc := st.pc + 4 } := by
  simp only [arm64_runs, hstep]
  rw [if_pos hseq]

theorem runs_cons_jump (st st' : Arm64State) (code : Nat → UInt8) (f : Nat)
    (hstep : arm64_step st code = some st')
    (hjump : st'.pc ≠ st.pc) :
    arm64_runs code (f + 1) st = arm64_runs code f st' := by
  simp only [arm64_runs, hstep]
  rw [if_neg hjump]

theorem runs_step_none (st : Arm64State) (code : Nat → UInt8) (f : Nat)
    (hstep : arm64_step st code = none) :
    arm64_runs code (f + 1) st = none := by
  simp only [arm64_runs, hstep]

theorem runs_append (code : Nat → UInt8) (p u : Nat) (st : Arm64State) :
    arm64_runs code (p + u) st =
      match arm64_runs code p st with
      | some mid => arm64_runs code u mid
      | none => none := by
  induction p generalizing st with
  | zero => simp only [Nat.zero_add, arm64_runs]
  | succ q ih =>
    cases hstep : arm64_step st code with
    | none =>
      rw [show q + 1 + u = (q + u) + 1 from by omega,
          runs_step_none st code (q + u) hstep,
          runs_step_none st code q hstep]
    | some st' =>
      by_cases hp : st'.pc = st.pc
      · have h1 : arm64_runs code (q + 1 + u) st =
            arm64_runs code (q + u) { st' with pc := st.pc + 4 } := by
          rw [show q + 1 + u = (q + u) + 1 from by omega]
          exact runs_cons_seq st st' code (q + u) hstep hp
        have h2 : arm64_runs code (q + 1) st =
            arm64_runs code q { st' with pc := st.pc + 4 } :=
          runs_cons_seq st st' code q hstep hp
        rw [h1, ih, h2]
      · have h1 : arm64_runs code (q + 1 + u) st = arm64_runs code (q + u) st' := by
          rw [show q + 1 + u = (q + u) + 1 from by omega]
          exact runs_cons_jump st st' code (q + u) hstep hp
        have h2 : arm64_runs code (q + 1) st = arm64_runs code q st' :=
          runs_cons_jump st st' code q hstep hp
        rw [h1, ih, h2]

/-- Composition of two `arm64_runs` segments when the first is known to succeed:
    `arm64_runs code (p+u) st = arm64_runs code u mid`. -/
theorem runs_append_some (code : Nat → UInt8) (p u : Nat) (st mid : Arm64State)
    (h : arm64_runs code p st = some mid) :
    arm64_runs code (p + u) st = arm64_runs code u mid := by
  rw [runs_append, h]

/-- **Avoidance composes across a prefix run.**  If no intermediate state of the
    `p`-step prefix from `st` has `pc = ρ`, and no intermediate state of the
    `u`-step continuation from `mid` has `pc = ρ`, then no intermediate state of
    the combined `p + u`-step run from `st` has `pc = ρ`.  This is the `hmid`
    composition `go_exit_glue`/`arm64_go_exit_switch` consume. -/
theorem runs_avoid_one (code : Nat → UInt8) (st : Arm64State) (exit : Nat)
    (hpc : st.pc ≠ exit) :
    ∀ u, u < 1 → ∀ s, arm64_runs code u st = some s → s.pc ≠ exit := by
  intro u hu s hs
  have hz : u = 0 := by omega
  subst u
  simp only [runs_zero, Option.some.injEq] at hs
  subst s
  exact hpc

theorem runs_avoid_stuck (code : Nat → UInt8) (k exit : Nat) (st finish : Arm64State)
    (hrun : arm64_runs code k st = some finish)
    (hstuck : ∀ s : Arm64State, s.pc = exit → arm64_step s code = none) :
    ∀ u, u < k → ∀ s, arm64_runs code u st = some s → s.pc ≠ exit := by
  intro u hu s hs hp
  have hsplit := runs_append_some code u (k - u) st s hs
  rw [Nat.add_sub_of_le (by omega)] at hsplit
  have hrest : arm64_runs code (k - u) s = some finish := hsplit.symm.trans hrun
  have hpos : k - u = (k - u - 1) + 1 := by omega
  rw [hpos, runs_step_none s code (k - u - 1) (hstuck s hp)] at hrest
  cases hrest

theorem runs_avoid_append (code : Nat → UInt8) (p u ρ : Nat) (st mid : Arm64State)
    (h : arm64_runs code p st = some mid)
    (h1 : ∀ v, v < p → ∀ sv, arm64_runs code v st = some sv → sv.pc ≠ ρ)
    (h2 : ∀ v, v < u → ∀ sv, arm64_runs code v mid = some sv → sv.pc ≠ ρ) :
    ∀ v, v < p + u → ∀ sv, arm64_runs code v st = some sv → sv.pc ≠ ρ := by
  intro v hv sv hsv
  rcases Nat.lt_or_ge v p with hlt | hge
  · exact h1 v hlt sv hsv
  · have hsplit : arm64_runs code v st = arm64_runs code (v - p) mid := by
      have h' := runs_append_some code p (v - p) st mid h
      rw [show p + (v - p) = v from by omega] at h'
      exact h'
    rw [hsplit] at hsv
    exact h2 (v - p) (by omega) sv hsv

/-- A run preserves register `r` when every step of the run does.  The generator
    discharges `hstep` per instruction (via the `work_step_*` lemmas), so the
    deep per-block unfolding lives here rather than in the generated proof. -/
theorem arm64_runs_reg_eq (code : Nat → UInt8) (m : Nat) (st mid : Arm64State) (r : Nat)
    (h : arm64_runs code m st = some mid)
    (hstep : ∀ u, u < m → ∀ s, arm64_runs code u st = some s →
      ∀ s', arm64_step s code = some s' → arm64_reg r s' = arm64_reg r s) :
    arm64_reg r mid = arm64_reg r st := by
  induction m generalizing st with
  | zero =>
    rw [runs_zero] at h
    injection h with heq
    subst heq
    rfl
  | succ q ih =>
    cases hstep0 : arm64_step st code with
    | none =>
      rw [runs_step_none st code q hstep0] at h
      simp at h
    | some st' =>
      have h0 : arm64_reg r st' = arm64_reg r st :=
        hstep 0 (by omega) st (by simp only [runs_zero]) st' hstep0
      by_cases hp : st'.pc = st.pc
      · rw [runs_cons_seq st st' code q hstep0 hp] at h
        have hsub : arm64_reg r mid = arm64_reg r { st' with pc := st.pc + 4 } :=
          ih { st' with pc := st.pc + 4 } h (by
            intro u hu s hs s' hs'
            refine hstep (u + 1) (by omega) s ?_ s' hs'
            rw [runs_cons_seq st st' code u hstep0 hp]
            exact hs)
        rw [hsub]
        rw [show arm64_reg r { st' with pc := st.pc + 4 } = arm64_reg r st' from rfl, h0]
      · rw [runs_cons_jump st st' code q hstep0 hp] at h
        have hsub : arm64_reg r mid = arm64_reg r st' :=
          ih st' h (by
            intro u hu s hs s' hs'
            refine hstep (u + 1) (by omega) s ?_ s' hs'
            rw [runs_cons_jump st st' code u hstep0 hp]
            exact hs)
        rw [hsub, h0]

@[simp] theorem Arm64State.mem_pc (s : Arm64State) (pc : Nat) :
    ({ s with pc := pc }).mem = s.mem := rfl

/-- A run preserves the `mem_read_u64` at a fixed address when every step does.
    Companion to `arm64_runs_reg_eq`, used for the frame-slot value flow. -/
theorem arm64_runs_mem_eq (code : Nat → UInt8) (m : Nat) (st mid : Arm64State) (S : Nat)
    (h : arm64_runs code m st = some mid)
    (hstep : ∀ u, u < m → ∀ s, arm64_runs code u st = some s →
      ∀ s', arm64_step s code = some s' → mem_read_u64 s'.mem S = mem_read_u64 s.mem S) :
    mem_read_u64 mid.mem S = mem_read_u64 st.mem S := by
  induction m generalizing st with
  | zero =>
    rw [runs_zero] at h
    injection h with heq
    subst heq
    rfl
  | succ q ih =>
    cases hstep0 : arm64_step st code with
    | none =>
      rw [runs_step_none st code q hstep0] at h
      simp at h
    | some st' =>
      have h0 : mem_read_u64 st'.mem S = mem_read_u64 st.mem S :=
        hstep 0 (by omega) st (by simp only [runs_zero]) st' hstep0
      by_cases hp : st'.pc = st.pc
      · rw [runs_cons_seq st st' code q hstep0 hp] at h
        have hsub : mem_read_u64 mid.mem S = mem_read_u64 { st' with pc := st.pc + 4 }.mem S :=
          ih { st' with pc := st.pc + 4 } h (by
            intro u hu s hs s' hs'
            refine hstep (u + 1) (by omega) s ?_ s' hs'
            rw [runs_cons_seq st st' code u hstep0 hp]
            exact hs)
        rw [hsub]
        rw [Arm64State.mem_pc]
        exact h0
      · rw [runs_cons_jump st st' code q hstep0 hp] at h
        have hsub : mem_read_u64 mid.mem S = mem_read_u64 st'.mem S :=
          ih st' h (by
            intro u hu s hs s' hs'
            refine hstep (u + 1) (by omega) s ?_ s' hs'
            rw [runs_cons_jump st st' code u hstep0 hp]
            exact hs)
        rw [hsub, h0]

/-- Prefix-gluing: a finite certified run whose intermediate states avoid `ρ`
    converts into an equation between exit-runs: executing the certified prefix
    first and then `g` more steps equals running `m + g` fuel directly. -/
theorem go_exit_glue (code : Nat → UInt8) (ρ m g : Nat) (st tc : Arm64State)
    (hrun : arm64_runs code m st = some tc)
    (hmid : ∀ u, u < m → ∀ su, arm64_runs code u st = some su → su.pc ≠ ρ)
    (htc : tc.pc ≠ ρ) :
    arm64_go_exit st code ρ (m + g) = arm64_go_exit tc code ρ g := by
  induction m generalizing st with
  | zero =>
    rw [runs_zero] at hrun
    injection hrun with heq
    subst heq
    exact congrArg (arm64_go_exit st code ρ) (Nat.zero_add g)
  | succ q ih =>
    have h0ne : st.pc ≠ ρ := fun hc =>
      hmid 0 (by omega) st (by simp only [runs_zero]) hc
    cases hstep : arm64_step st code with
    | none =>
      exfalso
      rw [runs_step_none st code q hstep] at hrun
      simp at hrun
    | some st' =>
      by_cases hp : st'.pc = st.pc
      · -- sequential step: pc advances by 4
        have hmid' : ∀ u, u < q → ∀ su,
            arm64_runs code u { st' with pc := st.pc + 4 } = some su → su.pc ≠ ρ := by
          intro u hu su hsu
          refine hmid (u + 1) (by omega) su ?_
          rw [runs_cons_seq st st' code u hstep hp]
          exact hsu
        rw [runs_cons_seq st st' code q hstep hp] at hrun
        have hglue := ih _ hrun hmid'
        rw [show (q + 1) + g = (q + g) + 1 from by omega]
        rw [arm64_go_exit_step_seq st st' code ρ (q + g) hstep hp h0ne]
        exact hglue
      · -- control-transfer step
        have hmid' : ∀ u, u < q → ∀ su,
            arm64_runs code u st' = some su → su.pc ≠ ρ := by
          intro u hu su hsu
          refine hmid (u + 1) (by omega) su ?_
          rw [runs_cons_jump st st' code u hstep hp]
          exact hsu
        rw [runs_cons_jump st st' code q hstep hp] at hrun
        have hglue := ih _ hrun hmid'
        rw [show (q + 1) + g = (q + g) + 1 from by omega]
        rw [arm64_go_exit_step_jump st st' code ρ (q + g) hstep hp h0ne]
        exact hglue

/-- Exit-switching composition.  If a run of exactly `k` steps reaches `st'`
    at exit `e1`, and every intermediate state avoids the second exit `e2`, then
    running `st` to `e2` for `k + g` steps is the same as running `st'` to `e2`
    for `g` steps.  This is the glue needed to compose a recursive call (which
    halts at its return address `e1`) with the calling context (which continues
    to the function exit `e2`). -/
theorem arm64_go_exit_switch (st st' : Arm64State) (code : Nat → UInt8)
    (e1 e2 k g : Nat)
    (hrun : arm64_runs code k st = some st') (hpc : st'.pc = e1) (hne : e1 ≠ e2)
    (hmid : ∀ u, u < k → ∀ su, arm64_runs code u st = some su → su.pc ≠ e2) :
    arm64_go_exit st code e2 (k + g) = arm64_go_exit st' code e2 g :=
  go_exit_glue code e2 k g st st' hrun hmid (by rw [hpc]; exact hne)

/-- Conditional-branch composition in exit mode: given a step whose result is
    `if C then sT else sF`, taking the true branch (C holds) consumes one fuel
    and reaches `sT`.  Generic over any branch with the `if` result shape. -/
theorem go_exit_cbz_taken (st : Arm64State) (code : Nat → UInt8) (exit f : Nat)
    (C : Prop) [Decidable C] (sT sF : Arm64State)
    (hstep : arm64_step st code = some (if C then sT else sF))
    (h : C)
    (hjump : sT.pc ≠ st.pc)
    (hpc : st.pc ≠ exit) :
    arm64_go_exit st code exit (f + 1) = arm64_go_exit sT code exit f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hfnz, if_neg hpc, hstep, if_pos h]
  simp only [if_neg hjump, Nat.add_sub_cancel]

/-- Unconditional-branch composition in exit mode (B #tgt): consuming one
    fuel reaches { st with pc := tgt }.  `hjump` and `hpc` are the literal
    side conditions. -/
theorem go_exit_b (st : Arm64State) (code : Nat → UInt8) (exit f : Nat) (tgt : Nat)
    (hstep : arm64_step st code = some { st with pc := tgt })
    (hjump : tgt ≠ st.pc) (hpc : st.pc ≠ exit) :
    arm64_go_exit st code exit (f + 1) = arm64_go_exit { st with pc := tgt } code exit f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hfnz, if_neg hpc, hstep]
  simp only [if_neg hjump, Nat.add_sub_cancel]

/-- Single-step composition in exit mode, with an abstract post-state `st'`:
    consuming one fuel reaches `st'`.  Side conditions are given as a
    post-state pc fact plus two *literal* inequalities, so generated proofs
    never reduce `st.pc` through a deep run certificate. -/
theorem go_exit_step (st st' : Arm64State) (code : Nat → UInt8) (exit f tgt b_pc : Nat)
    (hstep : arm64_step st code = some st')
    (hpc' : st'.pc = tgt) (hpcb : st.pc = b_pc)
    (hne : tgt ≠ b_pc) (hpc : b_pc ≠ exit) :
    arm64_go_exit st code exit (f + 1) = arm64_go_exit st' code exit f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hfnz]
  have hpc2 : st.pc ≠ exit := by rw [hpcb]; exact hpc
  rw [if_neg hpc2, hstep]
  have hjump : st'.pc ≠ st.pc := by rw [hpc', hpcb]; exact hne
  simp only [if_neg hjump, Nat.add_sub_cancel]

/-- Conditional-branch composition in exit mode: taking the false branch
    (¬ C) reaches `sF`. -/
theorem go_exit_cbz_fall (st : Arm64State) (code : Nat → UInt8) (exit f : Nat)
    (C : Prop) [Decidable C] (sT sF : Arm64State)
    (hstep : arm64_step st code = some (if C then sT else sF))
    (h : ¬ C)
    (hjump : sF.pc ≠ st.pc)
    (hpc : st.pc ≠ exit) :
    arm64_go_exit st code exit (f + 1) = arm64_go_exit sF code exit f := by
  have hfnz : ¬ (f + 1 = 0) := by omega
  rw [arm64_go_exit, if_neg hfnz, if_neg hpc, hstep, if_neg h]
  simp only [if_neg hjump, Nat.add_sub_cancel]

/-- Sequential-block advance in exit mode: executing `m` certified sequential
    steps consumes `m` fuel.  `hrun` is the block's runs-certificate, `hmid`
    the no-exit side condition on intermediate states, `htc` the exit's
    non-reachability from the block exit.  This is the per-block composition
    used by the CFG path proof. -/
theorem go_exit_block (code : Nat → UInt8) (ρ m g : Nat) (st tc : Arm64State)
    (hrun : arm64_runs code m st = some tc)
    (hmid : ∀ u, u < m → ∀ su, arm64_runs code u st = some su → su.pc ≠ ρ)
    (htc : tc.pc ≠ ρ) :
    arm64_go_exit st code ρ (m + g) = arm64_go_exit tc code ρ g :=
  go_exit_glue code ρ m g st tc hrun hmid htc

/-- Generic prefix-glue WITHOUT the tc.pc ≠ ρ side condition:
    exit-freeze semantics make the equation hold regardless. -/
theorem rec1_glue_gen (code : Nat → UInt8) (ρ m g : Nat) (st tc : Arm64State)
    (hrun : arm64_runs code m st = some tc)
    (hmid : ∀ u, u < m → ∀ su, arm64_runs code u st = some su → su.pc ≠ ρ) :
    arm64_go_exit st code ρ (m + g) = arm64_go_exit tc code ρ g := by
  induction m generalizing st with
  | zero =>
    rw [runs_zero] at hrun
    injection hrun with heq
    subst heq
    exact congrArg (arm64_go_exit st code ρ) (Nat.zero_add g)
  | succ q ih =>
    have h0ne : st.pc ≠ ρ := fun hc =>
      hmid 0 (by omega) st (by simp only [runs_zero]) hc
    cases hstep : arm64_step st code with
    | none =>
      exfalso
      rw [runs_step_none st code q hstep] at hrun
      simp at hrun
    | some st' =>
      by_cases hp : st'.pc = st.pc
      · -- sequential step: pc advances by 4
        have hmid' : ∀ u, u < q → ∀ su,
            arm64_runs code u { st' with pc := st.pc + 4 } = some su → su.pc ≠ ρ := by
          intro u hu su hsu
          refine hmid (u + 1) (by omega) su ?_
          rw [runs_cons_seq st st' code u hstep hp]
          exact hsu
        rw [runs_cons_seq st st' code q hstep hp] at hrun
        have hglue := ih _ hrun hmid'
        rw [show (q + 1) + g = (q + g) + 1 from by omega]
        rw [arm64_go_exit_step_seq st st' code ρ (q + g) hstep hp h0ne]
        exact hglue
      · -- control-transfer step
        have hmid' : ∀ u, u < q → ∀ su,
            arm64_runs code u st' = some su → su.pc ≠ ρ := by
          intro u hu su hsu
          refine hmid (u + 1) (by omega) su ?_
          rw [runs_cons_jump st st' code u hstep hp]
          exact hsu
        rw [runs_cons_jump st st' code q hstep hp] at hrun
        have hglue := ih _ hrun hmid'
        rw [show (q + 1) + g = (q + g) + 1 from by omega]
        rw [arm64_go_exit_step_jump st st' code ρ (q + g) hstep hp h0ne]
        exact hglue






/-- `arm64_go_exit` is monotone in fuel: once it reaches the exit within `f`
    steps, any larger fuel returns the same state. -/
theorem arm64_go_exit_mono (st s : Arm64State) (code : Nat → UInt8) (exit f g : Nat)
    (hle : f ≤ g) (h : arm64_go_exit st code exit f = some s) :
    arm64_go_exit st code exit g = some s := by
  have aux : ∀ f, (∀ g st s, f ≤ g →
      arm64_go_exit st code exit f = some s →
      arm64_go_exit st code exit g = some s) := by
    intro f
    induction f with
    | zero =>
        intro g st s hle h
        unfold arm64_go_exit at h
        simp at h
    | succ f ih =>
        intro g st s hle h
        have hg : g ≠ 0 := by omega
        unfold arm64_go_exit at h
        rw [if_neg (by omega : ¬ (f + 1 = 0))] at h
        split at h
        · rename_i hpc
          injection h with hs
          subst hs
          unfold arm64_go_exit
          rw [if_neg hg, if_pos hpc]
        · rename_i hpc
          split at h
          · simp at h
          · rename_i st' hstep
            unfold arm64_go_exit
            rw [if_neg hg, if_neg hpc, hstep]
            dsimp only at h
            exact ih (g - 1) _ s (by omega) h
  exact aux f g st s hle h

/-- Reachability characterisation: if `arm64_go_exit` returns `some s`, then
    some finite prefix run `arm64_runs` reaches `s`.  (Prerequisite for gluing
    a recursive call's result onto the calling context.) -/
theorem arm64_go_exit_runs (st s : Arm64State) (code : Nat → UInt8) (e f : Nat)
    (h : arm64_go_exit st code e f = some s) :
    ∃ k, k ≤ f ∧ arm64_runs code k st = some s := by
  induction f generalizing st with
  | zero =>
      unfold arm64_go_exit at h
      simp at h
  | succ f ih =>
      unfold arm64_go_exit at h
      rw [if_neg (by omega : ¬ (f + 1 = 0))] at h
      split at h
      · injection h with hs
        subst hs
        exact ⟨0, by omega, by rw [runs_zero]⟩
      · cases hstep : arm64_step st code with
        | none => rw [hstep] at h; simp at h
        | some st' =>
          rw [hstep] at h
          obtain ⟨k, hk, hruns⟩ :=
            ih (if st'.pc = st.pc then { st' with pc := st.pc + 4 } else st') h
          refine ⟨k + 1, by omega, ?_⟩
          by_cases hp : st'.pc = st.pc
          · rw [runs_cons_seq st st' code k hstep hp]
            rw [if_pos hp] at hruns
            exact hruns
          · rw [runs_cons_jump st st' code k hstep hp]
            rw [if_neg hp] at hruns
            exact hruns

/-- General loop contraction by induction on the iteration count, as a full
    state transfer: `F` enumerates the loop's check states (`F (k+1)` is one
    iteration before `F k`), `hstep` glues one iteration (a full-state transfer
    taking `PATH` committed steps), and `hbase` discharges the exit when the
    counter has reached `F 0` (the exit state `s0` is fixed because each
    iteration restores the frame).  No unrolling: the conclusion is stated
    directly against `arm64_go_exit`. -/
theorem go_exit_loop_exact (code : Nat → UInt8) (ρ : Nat) (F : Nat → Arm64State)
    (PATH BASE : Nat) (s0 : Arm64State)
    (hstep : ∀ k, arm64_go_exit (F (k+1)) code ρ (BASE + PATH*(k+1))
        = arm64_go_exit (F k) code ρ (BASE + PATH*k))
    (hbase : arm64_go_exit (F 0) code ρ BASE = some s0) :
    ∀ N, arm64_go_exit (F N) code ρ (BASE + PATH*N) = some s0 := by
  intro N
  induction N with
  | zero => exact hbase
  | succ k ih => rw [hstep k]; exact ih

/-- Fuel-agnostic form of `go_exit_loop_exact`: the same contraction with any
    fuel at least `BASE + PATH*N` (via `arm64_go_exit_mono`). -/
theorem go_exit_loop (code : Nat → UInt8) (ρ : Nat) (F : Nat → Arm64State)
    (PATH BASE : Nat) (s0 : Arm64State)
    (hstep : ∀ k, arm64_go_exit (F (k+1)) code ρ (BASE + PATH*(k+1))
        = arm64_go_exit (F k) code ρ (BASE + PATH*k))
    (hbase : arm64_go_exit (F 0) code ρ BASE = some s0) :
    ∀ N f, BASE + PATH*N ≤ f → arm64_go_exit (F N) code ρ f = some s0 := by
  intro N f hf
  exact arm64_go_exit_mono (F N) s0 code ρ (BASE + PATH*N) f hf
    (go_exit_loop_exact code ρ F PATH BASE s0 hstep hbase N)

/-- Two adjacent 8-byte slots at `a` and `a + 8` have non-overlapping byte
    ranges, even when the second address wraps modulo 2^64.  This supplies the
    disjointness hypothesis of the frame read-after-write lemmas for a
    symbolic stack pointer. -/
theorem addr_adjacent_disj (a : Nat) (ha : a < 18446744073709551616) :
    a + 8 ≤ (a + 8) % 18446744073709551616 ∨
      (a + 8) % 18446744073709551616 + 8 ≤ a := by
  by_cases h : a + 8 < 18446744073709551616
  · left
    have : (a + 8) % 18446744073709551616 = a + 8 := Nat.mod_eq_of_lt h
    omega
  · right
    have hge : 18446744073709551616 ≤ a + 8 := by omega
    have hlt : a + 8 - 18446744073709551616 < 18446744073709551616 := by omega
    have hmod : (a + 8) % 18446744073709551616 = a + 8 - 18446744073709551616 := by
      calc (a + 8) % 18446744073709551616
          = ((a + 8 - 18446744073709551616) + 18446744073709551616) % 18446744073709551616 := by
              rw [Nat.sub_add_cancel hge]
        _ = (a + 8 - 18446744073709551616) % 18446744073709551616 := Nat.add_mod_right _ _
        _ = a + 8 - 18446744073709551616 := Nat.mod_eq_of_lt hlt
    rw [hmod]; omega

/-- Side-condition-free adjacent-slot round-trip: reading slot `a` after a
    pair of writes at `a` and `a+8 (mod 2^64)` returns the first value.  The
    disjointness is supplied by `addr_adjacent_disj`; `ha` is discharged by
    `UInt64.toNat_lt` for the actual `(sp - k).toNat` addresses. -/
theorem mem_read_two_writes_adjacent_mod (mem : Nat → UInt8) (a : Nat)
    (ha : a < 18446744073709551616) (v w : UInt64) :
    mem_read_u64
      (mem_write_u64 (mem_write_u64 mem a v) ((a + 8) % 18446744073709551616) w) a = v :=
  mem_read_two_writes_same mem a ((a + 8) % 18446744073709551616) v w
    (addr_adjacent_disj a ha)

/-- Adjacent-slot round-trip in the address shape the code generator actually
    emits: read slot `x.toNat` after writes at `x.toNat` and `(x+8).toNat`.
    (`(x+8).toNat` is the `%2^64` form; this variant rewrites it and applies
    `mem_read_two_writes_adjacent_mod`.) -/
theorem mem_read_two_writes_adj_uint (mem : Nat → UInt8) (x : UInt64) (v w : UInt64) :
    mem_read_u64
      (mem_write_u64 (mem_write_u64 mem x.toNat v) (x + 8).toNat w) x.toNat = v := by
  have h8 : ((8 : UInt64)).toNat = 8 := rfl
  have hx : (x + 8).toNat = (x.toNat + 8) % 18446744073709551616 := by
    rw [u64_toNat_add_lit, h8]
  rw [hx]
  exact mem_read_two_writes_adjacent_mod mem x.toNat (UInt64.toNat_lt x) v w

/-- Peel a spill pair written at `x` from a read at a disjoint `y`.  Needed when
    a block spills several operands (e.g. a compound condition): the read of an
    earlier spill has later spills above it in the memory chain. -/
theorem mem_read_two_writes_adj_uint_ne (mem : Nat → UInt8) (x y : UInt64) (v w : UInt64)
    (h1 : y.toNat + 8 ≤ x.toNat ∨ x.toNat + 8 ≤ y.toNat)
    (h2 : y.toNat + 8 ≤ (x + 8).toNat ∨ (x + 8).toNat + 8 ≤ y.toNat) :
    mem_read_u64 (mem_write_u64 (mem_write_u64 mem x.toNat v) (x + 8).toNat w) y.toNat
      = mem_read_u64 mem y.toNat := by
  rw [mem_read_after_write_u64_ne _ (x + 8).toNat y.toNat w h2,
      mem_read_after_write_u64_ne _ x.toNat y.toNat v h1]

/-! ### Comparison-condition bridge

The code generator materialises a source comparison `a ⋈ b` by `cmp`-ing the
two operands and `cset`-ing the corresponding condition code.  These lemmas
identify the resulting condition flag with the UInt64 comparison, generically
over the operands (proved by `bv_decide`). -/

theorem arm64_flag_eq (a b : UInt64) :
    arm64_matches_condition 0 (arm64_subs_flags a b) = true ↔ a = b := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_ne (a b : UInt64) :
    arm64_matches_condition 1 (arm64_subs_flags a b) = true ↔ a ≠ b := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_ge (a b : UInt64) :
    arm64_matches_condition 2 (arm64_subs_flags a b) = true ↔ a ≥ b := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_lt (a b : UInt64) :
    arm64_matches_condition 3 (arm64_subs_flags a b) = true ↔ a < b := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_gt (a b : UInt64) :
    arm64_matches_condition 8 (arm64_subs_flags a b) = true ↔ a > b := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_le (a b : UInt64) :
    arm64_matches_condition 9 (arm64_subs_flags a b) = true ↔ a ≤ b := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

/-- Signed-comparison flag lemmas.  A signed ≤/</≥/> on the two's-complement
    values is an unsigned comparison after flipping the sign bit, so the
    `gt`/`lt`/`ge`/`le` conditions (codes 12/11/10/13) identify with the
    sign-flipped unsigned order.  Sign mask is `0x8000000000000000`. -/
theorem arm64_flag_ge_s (a b : UInt64) :
    arm64_matches_condition 10 (arm64_subs_flags a b) = true
      ↔ (a ^^^ 0x8000000000000000) ≥ (b ^^^ 0x8000000000000000) := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_lt_s (a b : UInt64) :
    arm64_matches_condition 11 (arm64_subs_flags a b) = true
      ↔ (a ^^^ 0x8000000000000000) < (b ^^^ 0x8000000000000000) := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_gt_s (a b : UInt64) :
    arm64_matches_condition 12 (arm64_subs_flags a b) = true
      ↔ (a ^^^ 0x8000000000000000) > (b ^^^ 0x8000000000000000) := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_flag_le_s (a b : UInt64) :
    arm64_matches_condition 13 (arm64_subs_flags a b) = true
      ↔ (a ^^^ 0x8000000000000000) ≤ (b ^^^ 0x8000000000000000) := by
  simp only [arm64_matches_condition, arm64_subs_flags]; bv_decide

theorem arm64_cset_eq (a b : UInt64) :
    (if arm64_matches_condition 0 (arm64_subs_flags a b) then (1 : UInt64) else 0)
      = (if a = b then 1 else 0) := by
  by_cases h : a = b
  · rw [if_pos ((arm64_flag_eq a b).mpr h), if_pos h]
  · rw [if_neg (fun hc => h ((arm64_flag_eq a b).mp hc)), if_neg h]

theorem arm64_cset_ne (a b : UInt64) :
    (if arm64_matches_condition 1 (arm64_subs_flags a b) then (1 : UInt64) else 0)
      = (if a ≠ b then 1 else 0) := by
  by_cases h : a ≠ b
  · rw [if_pos ((arm64_flag_ne a b).mpr h), if_pos h]
  · rw [if_neg (fun hc => h ((arm64_flag_ne a b).mp hc)), if_neg h]

theorem arm64_cset_le (a b : UInt64) :
    (if arm64_matches_condition 9 (arm64_subs_flags a b) then (1 : UInt64) else 0)
      = (if a ≤ b then 1 else 0) := by
  by_cases h : a ≤ b
  · rw [if_pos ((arm64_flag_le a b).mpr h), if_pos h]
  · rw [if_neg (fun hc => h ((arm64_flag_le a b).mp hc)), if_neg h]

/-! # Generic countdown-style while-loop contract

This is the generic induction behind every `while (x19 > 0) { x19 -= 1 }` loop
the compiler emits.  The three straight-line block effect maps (`cond`, `body`,
`ex`) and their machine facts are supplied as hypotheses; the induction on the
counter, the fuel arithmetic, and the block composition are all proved here, so
the generator only emits a thin instantiation. -/



/-- **Generic countdown-style while-loop contract.**

`checkPc` is the loop header; `cond` is the condition block (ending in a `cbz`
on register `cr` at `cbzPc`) that falls to `bodyPc` and exits to `exitBpc`;
`body` is the body block, which runs back to `checkPc`; `ex` is the exit block,
which runs to `exit`.  The loop counter is `x19`; the `cbz` tests it against
zero (`hcondFlag`).  With `x19 = arg` at the header, the exit-mode interpreter
reaches `exit` with `x0 = done arg`, provided `done` is constant along the
countdown (`hmojo`).

`P` is the frame invariant the loop maintains (for the compiler.s loops it is
the return-address slot read-back that the callee-saved epilogue consumes).  It
is preserved by the condition and body blocks (`hP_cond`, `hP_body`), moved past
`pc`-updates (`hP_pc`), and implies the epilogue.s return target (`hexPc`). -/
theorem while_dec_exit_contract
    (code : Nat → UInt8) (exit checkPc cbzPc bodyPc exitBpc : Nat) (cr : Nat)
    (done : UInt64 → UInt64)
    (cond body ex : Arm64State → Arm64State)
    (mc mb me : Nat)
    (P : Arm64State → Prop)
    (hP_pc : ∀ (st : Arm64State) (pc : Nat), P st → P { st with pc := pc })
    (hP_cond : ∀ st, st.pc = checkPc → P st → P (cond st))
    (hP_body : ∀ st, st.pc = bodyPc → P st → P (body st))
    (hstep : ∀ st, st.pc = cbzPc →
      arm64_step st code = some (if arm64_reg cr st = 0 then
        ({ st with pc := exitBpc } : Arm64State) else ({ st with pc := bodyPc } : Arm64State)))
    (hcondRun : ∀ st, st.pc = checkPc → arm64_runs code mc st = some (cond st))
    (hcondMid : ∀ st, st.pc = checkPc →
      ∀ u, u < mc → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (hcondPc : ∀ st, st.pc = checkPc → (cond st).pc = cbzPc)
    (hcondFlag : ∀ st, st.pc = checkPc → (arm64_reg cr (cond st) = 0 ↔ st.x19 = 0))
    (hcondX19 : ∀ st, st.pc = checkPc → (cond st).x19 = st.x19)
    (hbodyRun : ∀ st, st.pc = bodyPc → arm64_runs code mb st = some (body st))
    (hbodyMid : ∀ st, st.pc = bodyPc →
      ∀ u, u < mb → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (hbodyPc : ∀ st, st.pc = bodyPc → (body st).pc = checkPc)
    (hbodyDec : ∀ st, st.pc = bodyPc → (body st).x19 = st.x19 - 1)
    (hexRun : ∀ st, st.pc = exitBpc → P st → arm64_runs code me st = some (ex st))
    (hexMid : ∀ st, st.pc = exitBpc →
      ∀ u, u < me → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (hexPc : ∀ st, st.pc = exitBpc → P st → (ex st).pc = exit)
    (hexX0 : ∀ st, st.pc = exitBpc → st.x19 = 0 → (ex st).x0 = done st.x19)
    (hmojo : ∀ (a : UInt64), a ≠ 0 → done (a - 1) = done a)
    (hcbzExit : cbzPc ≠ exit) (hExitBpc : exitBpc ≠ cbzPc) (hBodyPc : bodyPc ≠ cbzPc) :
    ∀ (arg : UInt64) (st : Arm64State) (fuel : Nat),
      (mc + mb + 2) * arg.toNat + (mc + me + 2) ≤ fuel →
      st.pc = checkPc → st.x19 = arg → P st →
      ∃ s, arm64_go_exit st code exit fuel = some s ∧ s.x0 = done arg := by
  have key : ∀ k, ∀ st : Arm64State, st.pc = checkPc → st.x19.toNat = k → P st →
      ∀ fuel, (mc + mb + 2) * k + (mc + me + 2) ≤ fuel →
        ∃ s, arm64_go_exit st code exit fuel = some s ∧ s.x0 = done st.x19 := by
    intro k
    induction k with
    | zero =>
      intro st hpc hk hPst fuel hfuel
      rw [Nat.mul_zero, Nat.zero_add] at hfuel
      have hx19_0 : st.x19 = 0 := by
        apply UInt64.toNat.inj
        simpa using hk
      have hglue1 := rec1_glue_gen code exit mc (fuel - mc) st (cond st)
        (hcondRun st hpc) (hcondMid st hpc)
      rw [show mc + (fuel - mc) = fuel from by omega] at hglue1
      rw [hglue1]
      have hcp := hcondPc st hpc
      have hflag : arm64_reg cr (cond st) = 0 := (hcondFlag st hpc).mpr hx19_0
      have hjump : ({ cond st with pc := exitBpc } : Arm64State).pc ≠ (cond st).pc := by
        rw [hcp]; exact hExitBpc
      have hpcne : (cond st).pc ≠ exit := by rw [hcp]; exact hcbzExit
      have hcbz := go_exit_cbz_taken (cond st) code exit (fuel - mc - 1)
        (arm64_reg cr (cond st) = 0)
        ({ cond st with pc := exitBpc }) ({ cond st with pc := bodyPc })
        (hstep (cond st) hcp) hflag hjump hpcne
      rw [show (fuel - mc - 1) + 1 = fuel - mc from by omega] at hcbz
      rw [hcbz]
      have hPe : P ({ cond st with pc := exitBpc } : Arm64State) :=
        hP_pc (cond st) exitBpc (hP_cond st hpc hPst)
      have hglue3 := rec1_glue_gen code exit me (fuel - mc - 1 - me)
        ({ cond st with pc := exitBpc }) (ex { cond st with pc := exitBpc })
        (hexRun _ (by rfl) hPe) (hexMid _ (by rfl))
      rw [show me + (fuel - mc - 1 - me) = fuel - mc - 1 from by omega] at hglue3
      rw [hglue3]
      have hexpc : (ex { cond st with pc := exitBpc }).pc = exit := hexPc _ (by rfl) hPe
      rw [arm64_go_exit_hit _ code exit (fuel - mc - 1 - me) (by omega) hexpc]
      have hzero : ({ cond st with pc := exitBpc } : Arm64State).x19 = 0 := by
        change (cond st).x19 = 0
        rw [hcondX19 st hpc, hx19_0]
      have hx0ex : (ex { cond st with pc := exitBpc }).x0 = done st.x19 := by
        rw [hexX0 _ (by rfl) hzero]
        rw [show ({ cond st with pc := exitBpc } : Arm64State).x19 = st.x19 from by
          change (cond st).x19 = st.x19
          exact hcondX19 st hpc]
      exact ⟨ex { cond st with pc := exitBpc }, rfl, hx0ex⟩
    | succ k ih =>
      intro st hpc hk hPst fuel hfuel
      rw [Nat.mul_succ] at hfuel
      have hne : st.x19 ≠ 0 := by intro h; rw [h] at hk; simp at hk
      have hglue1 := rec1_glue_gen code exit mc (fuel - mc) st (cond st)
        (hcondRun st hpc) (hcondMid st hpc)
      rw [show mc + (fuel - mc) = fuel from by omega] at hglue1
      rw [hglue1]
      have hcp := hcondPc st hpc
      have hflag : ¬ (arm64_reg cr (cond st) = 0) :=
        fun h0 => hne ((hcondFlag st hpc).mp h0)
      have hjump : ({ cond st with pc := bodyPc } : Arm64State).pc ≠ (cond st).pc := by
        rw [hcp]; exact hBodyPc
      have hpcne : (cond st).pc ≠ exit := by rw [hcp]; exact hcbzExit
      have hcbz := go_exit_cbz_fall (cond st) code exit (fuel - mc - 1)
        (arm64_reg cr (cond st) = 0)
        ({ cond st with pc := exitBpc }) ({ cond st with pc := bodyPc })
        (hstep (cond st) hcp) hflag hjump hpcne
      rw [show (fuel - mc - 1) + 1 = fuel - mc from by omega] at hcbz
      rw [hcbz]
      have hglue2 := rec1_glue_gen code exit mb (fuel - mc - 1 - mb)
        ({ cond st with pc := bodyPc }) (body { cond st with pc := bodyPc })
        (hbodyRun _ (by rfl)) (hbodyMid _ (by rfl))
      rw [show mb + (fuel - mc - 1 - mb) = fuel - mc - 1 from by omega] at hglue2
      rw [hglue2]
      have hbpc : (body { cond st with pc := bodyPc }).pc = checkPc := hbodyPc _ (by rfl)
      have hcin : ({ cond st with pc := bodyPc } : Arm64State).x19 = st.x19 := by
        change (cond st).x19 = st.x19
        exact hcondX19 st hpc
      have hbdec : (body { cond st with pc := bodyPc }).x19 = st.x19 - 1 := by
        have h := hbodyDec ({ cond st with pc := bodyPc }) (by rfl)
        rwa [hcin] at h
      have hbtoNat : (body { cond st with pc := bodyPc }).x19.toNat = k := by
        rw [hbdec, toNat_sub_one st.x19 hne, hk]; omega
      have hPc' : P ({ cond st with pc := bodyPc } : Arm64State) :=
        hP_pc (cond st) bodyPc (hP_cond st hpc hPst)
      have hPb : P (body { cond st with pc := bodyPc }) := hP_body _ (by rfl) hPc'
      have hfuel' : (mc + mb + 2) * k + (mc + me + 2) ≤ fuel - mc - 1 - mb := by omega
      obtain ⟨s, hs, hx0⟩ := ih _ hbpc hbtoNat hPb _ hfuel'
      refine ⟨s, hs, ?_⟩
      rw [hx0, hbdec]
      exact hmojo st.x19 hne
  intro arg st fuel hfuel hpc hx19 hPst
  simpa [hx19] using key arg.toNat st hpc (by rw [hx19]) hPst fuel (by simpa using hfuel)

/-- Generic count-up loop contract: the `for i in range (start, end)` shape.

    `checkPc` is the loop top (start of the condition-test block), `cbzPc` the
    CBZ inside it, `bodyPc` the CBZ fall (loop body), `exitBpc` the CBZ taken
    (exit path).  `cr` is the register the CBZ tests (the CSET result); `r` is
    the counter register (loop variable); `b` the bound register.

    Inducts on the remaining iterations `(b - r).toNat`:
    - base (`b ≤ r`): condition false, exit path, `x0 = model st` (the
      exit-path obligation folds the model to the exit expression);
    - step (`r < b`): condition true, body increments the counter
      (`hbodyR`) and the model advances by one step (`hbodyModel`).

    `model : Arm64State → UInt64` is pc-insensitive (`hmodelPc`) and reads
    only registers; its base case must equal the exit-path's x0.  This is the
    counting generalisation of `while_dec_exit_contract` (which is the
    `r = 0 → done` special case with a constant model). -/
theorem while_lt_exit_contract
    (code : Nat → UInt8) (exit checkPc cbzPc bodyPc exitBpc : Nat)
    (cr r b : Nat)
    (model : Arm64State → UInt64)
    (cond body ex : Arm64State → Arm64State)
    (mc mb me : Nat)
    (P : Arm64State → Prop)
    (hP_pc : ∀ (st : Arm64State) (pc : Nat), P st → P { st with pc := pc })
    (hP_cond : ∀ st, st.pc = checkPc → P st → P (cond st))
    (hP_body : ∀ st, st.pc = bodyPc → P st → P (body st))
    (hstep : ∀ st, st.pc = cbzPc →
      arm64_step st code = some (if arm64_reg cr st = 0 then
        ({ st with pc := exitBpc } : Arm64State) else ({ st with pc := bodyPc } : Arm64State)))
    (hcondRun : ∀ st, st.pc = checkPc → arm64_runs code mc st = some (cond st))
    (hcondMid : ∀ st, st.pc = checkPc →
      ∀ u, u < mc → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (hcondPc : ∀ st, st.pc = checkPc → (cond st).pc = cbzPc)
    (hcondFlag : ∀ st, st.pc = checkPc →
      (arm64_reg cr (cond st) = 0 ↔ ¬ (arm64_reg r st < arm64_reg b st)))
    (hcondRB : ∀ st, st.pc = checkPc →
      arm64_reg r (cond st) = arm64_reg r st ∧ arm64_reg b (cond st) = arm64_reg b st)
    (hcondModel : ∀ st, st.pc = checkPc → model (cond st) = model st)
    (hbodyRun : ∀ st, st.pc = bodyPc → arm64_runs code mb st = some (body st))
    (hbodyMid : ∀ st, st.pc = bodyPc →
      ∀ u, u < mb → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (hbodyPc : ∀ st, st.pc = bodyPc → (body st).pc = checkPc)
    (hbodyR : ∀ st, st.pc = bodyPc → arm64_reg r (body st) = arm64_reg r st + 1)
    (hbodyB : ∀ st, st.pc = bodyPc → arm64_reg b (body st) = arm64_reg b st)
    (hbodyModel : ∀ st, st.pc = bodyPc →
      (arm64_reg r st < arm64_reg b st) → model (body st) = model st)
    (hexRun : ∀ st, st.pc = exitBpc → P st → arm64_runs code me st = some (ex st))
    (hexMid : ∀ st, st.pc = exitBpc →
      ∀ u, u < me → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (hexPc : ∀ st, st.pc = exitBpc → P st → (ex st).pc = exit)
    (hexX0 : ∀ st, st.pc = exitBpc →
      ¬ (arm64_reg r st < arm64_reg b st) → (ex st).x0 = model st)
    (hmodelPc : ∀ st pc, model { st with pc := pc } = model st)
    (hcbzExit : cbzPc ≠ exit) (hExitBpc : exitBpc ≠ cbzPc) (hBodyPc : bodyPc ≠ cbzPc) :
    ∀ (st : Arm64State) (fuel : Nat),
      (mc + mb + 2) *
        ((arm64_reg b st).toNat - (arm64_reg r st).toNat) + (mc + me + 2) ≤ fuel →
      st.pc = checkPc → P st →
      ∃ s, arm64_go_exit st code exit fuel = some s ∧ s.x0 = model st := by
  have u64_lt_toNat {a c : UInt64} (h : a < c) : a.toNat < c.toNat := by
    rw [UInt64.lt_iff_toNat_lt] at h
    exact h
  have toNat_lt_u64 {a c : UInt64} (h : a.toNat < c.toNat) : a < c := by
    rw [UInt64.lt_iff_toNat_lt]
    exact h
  have key : ∀ (k : Nat) (st : Arm64State), st.pc = checkPc →
      (arm64_reg b st).toNat - (arm64_reg r st).toNat = k → P st →
      ∀ fuel, (mc + mb + 2) * k + (mc + me + 2) ≤ fuel →
      ∃ s, arm64_go_exit st code exit fuel = some s ∧ s.x0 = model st := by
    intro k
    induction k with
    | zero =>
      intro st hpc hk hPst fuel hfuel
      rw [Nat.mul_zero, Nat.zero_add] at hfuel
      have hge : ¬ (arm64_reg r st < arm64_reg b st) := by
        intro hlt_r
        have hltNat : (arm64_reg r st).toNat < (arm64_reg b st).toNat := u64_lt_toNat hlt_r
        have hle : (arm64_reg b st).toNat ≤ (arm64_reg r st).toNat :=
          Nat.le_of_sub_eq_zero hk
        exact (Nat.not_lt_of_le hle) hltNat
      have hglue1 := rec1_glue_gen code exit mc (fuel - mc) st (cond st)
        (hcondRun st hpc) (hcondMid st hpc)
      rw [show mc + (fuel - mc) = fuel from by omega] at hglue1
      rw [hglue1]
      have hcp := hcondPc st hpc
      have hflag : arm64_reg cr (cond st) = 0 := (hcondFlag st hpc).mpr hge
      have hjump : ({ cond st with pc := exitBpc } : Arm64State).pc ≠ (cond st).pc := by
        rw [hcp]; exact hExitBpc
      have hpcne : (cond st).pc ≠ exit := by rw [hcp]; exact hcbzExit
      have hcbz := go_exit_cbz_taken (cond st) code exit (fuel - mc - 1)
        (arm64_reg cr (cond st) = 0)
        ({ cond st with pc := exitBpc }) ({ cond st with pc := bodyPc })
        (hstep (cond st) hcp) hflag hjump hpcne
      rw [show (fuel - mc - 1) + 1 = fuel - mc from by omega] at hcbz
      rw [hcbz]
      have hPe : P ({ cond st with pc := exitBpc } : Arm64State) :=
        hP_pc (cond st) exitBpc (hP_cond st hpc hPst)
      have hglue3 := rec1_glue_gen code exit me (fuel - mc - 1 - me)
        ({ cond st with pc := exitBpc }) (ex { cond st with pc := exitBpc })
        (hexRun _ (by rfl) hPe) (hexMid _ (by rfl))
      rw [show me + (fuel - mc - 1 - me) = fuel - mc - 1 from by omega] at hglue3
      rw [hglue3]
      have hexpc : (ex { cond st with pc := exitBpc }).pc = exit :=
        hexPc _ (by rfl) hPe
      rw [arm64_go_exit_hit _ code exit (fuel - mc - 1 - me) (by omega) hexpc]
      have hge2 : ¬ (arm64_reg r { cond st with pc := exitBpc } <
                     arm64_reg b { cond st with pc := exitBpc }) := by
        intro hlt_e
        rw [arm64_reg_pc r (cond st) exitBpc, arm64_reg_pc b (cond st) exitBpc,
            (hcondRB st hpc).1, (hcondRB st hpc).2] at hlt_e
        exact hge hlt_e
      have hx0ex : (ex { cond st with pc := exitBpc }).x0 = model st := by
        have hex0 := hexX0 _ (by rfl) hge2
        rw [hex0, hmodelPc (cond st) exitBpc, hcondModel st hpc]
      exact ⟨ex { cond st with pc := exitBpc }, rfl, hx0ex⟩
    | succ k ih =>
      intro st hpc hk hPst fuel hfuel
      rw [Nat.mul_succ] at hfuel
      have hlt : arm64_reg r st < arm64_reg b st := by
        have hpos : 0 < (arm64_reg b st).toNat - (arm64_reg r st).toNat := by
          rw [hk]; omega
        exact toNat_lt_u64 (Nat.lt_of_sub_pos hpos)
      have hglue1 := rec1_glue_gen code exit mc (fuel - mc) st (cond st)
        (hcondRun st hpc) (hcondMid st hpc)
      rw [show mc + (fuel - mc) = fuel from by omega] at hglue1
      rw [hglue1]
      have hcp := hcondPc st hpc
      have hflag : ¬ (arm64_reg cr (cond st) = 0) := by
        intro hcr
        exact (hcondFlag st hpc).mp hcr hlt
      have hjump : ({ cond st with pc := bodyPc } : Arm64State).pc ≠ (cond st).pc := by
        rw [hcp]; exact hBodyPc
      have hpcne : (cond st).pc ≠ exit := by rw [hcp]; exact hcbzExit
      have hcbz := go_exit_cbz_fall (cond st) code exit (fuel - mc - 1)
        (arm64_reg cr (cond st) = 0)
        ({ cond st with pc := exitBpc }) ({ cond st with pc := bodyPc })
        (hstep (cond st) hcp) hflag hjump hpcne
      rw [show (fuel - mc - 1) + 1 = fuel - mc from by omega] at hcbz
      rw [hcbz]
      have hglue2 := rec1_glue_gen code exit mb (fuel - mc - 1 - mb)
        { cond st with pc := bodyPc } (body { cond st with pc := bodyPc })
        (hbodyRun _ (by rfl)) (hbodyMid _ (by rfl))
      rw [show mb + (fuel - mc - 1 - mb) = fuel - mc - 1 from by omega] at hglue2
      rw [hglue2]
      have hbpc : (body { cond st with pc := bodyPc }).pc = checkPc :=
        hbodyPc _ (by rfl)
      have hlt2 : arm64_reg r { cond st with pc := bodyPc } <
                  arm64_reg b { cond st with pc := bodyPc } := by
        rw [arm64_reg_pc r (cond st) bodyPc, arm64_reg_pc b (cond st) bodyPc,
            (hcondRB st hpc).1, (hcondRB st hpc).2]
        exact hlt
      have hrem : (arm64_reg b (body { cond st with pc := bodyPc })).toNat -
          (arm64_reg r (body { cond st with pc := bodyPc })).toNat = k := by
        have hrb : arm64_reg r (body { cond st with pc := bodyPc }) =
            arm64_reg r { cond st with pc := bodyPc } + 1 := hbodyR _ (by rfl)
        have hbb : arm64_reg b (body { cond st with pc := bodyPc }) =
            arm64_reg b { cond st with pc := bodyPc } := hbodyB _ (by rfl)
        have hadd : (arm64_reg r { cond st with pc := bodyPc } + 1).toNat =
            (arm64_reg r { cond st with pc := bodyPc }).toNat + 1 := by
          have hltNat : (arm64_reg r { cond st with pc := bodyPc }).toNat <
              (arm64_reg b { cond st with pc := bodyPc }).toNat := u64_lt_toNat hlt2
          have hb264 : (arm64_reg b { cond st with pc := bodyPc }).toNat < 2^64 :=
            UInt64.toNat_lt (arm64_reg b { cond st with pc := bodyPc })
          have hlt264 : (arm64_reg r { cond st with pc := bodyPc }).toNat + 1 < 2^64 := by
            calc (arm64_reg r { cond st with pc := bodyPc }).toNat + 1
                ≤ (arm64_reg b { cond st with pc := bodyPc }).toNat := Nat.succ_le_of_lt hltNat
              _ < 2^64 := hb264
          rw [UInt64.toNat_add, show (1 : UInt64).toNat = 1 from by rfl]
          exact Nat.mod_eq_of_lt hlt264
        have hrb2 : (arm64_reg r (body { cond st with pc := bodyPc })).toNat =
            (arm64_reg r { cond st with pc := bodyPc }).toNat + 1 := by
          rw [hrb, hadd]
        have hb2 : (arm64_reg b { cond st with pc := bodyPc }).toNat =
            (arm64_reg b st).toNat := by
          rw [arm64_reg_pc, (hcondRB st hpc).2]
        have hr2 : (arm64_reg r { cond st with pc := bodyPc }).toNat =
            (arm64_reg r st).toNat := by
          rw [arm64_reg_pc, (hcondRB st hpc).1]
        rw [hbb, hrb2, hb2, hr2]
        have hsub : (arm64_reg b st).toNat - ((arm64_reg r st).toNat + 1) = k := by
          rw [← Nat.sub_sub, hk]
          omega
        simpa using hsub
      have hfuel' : (mc + mb + 2) * k + (mc + me + 2) ≤ fuel - mc - 1 - mb := by omega
      have hP2 : P { cond st with pc := bodyPc } :=
        hP_pc (cond st) bodyPc (hP_cond st hpc hPst)
      have hPb : P (body { cond st with pc := bodyPc }) :=
        hP_body _ (by rfl) hP2
      obtain ⟨s, hs, hx0⟩ := ih _ hbpc hrem hPb _ hfuel'
      refine ⟨s, hs, ?_⟩
      rw [hx0, hbodyModel _ (by rfl) hlt2, hmodelPc (cond st) bodyPc,
          hcondModel st hpc]
  intro st fuel hfuel hpc hPst
  simpa using key ((arm64_reg b st).toNat - (arm64_reg r st).toNat) st hpc
    (by rfl) hPst fuel hfuel

/-- **A push pair does not disturb a slot above `sp`.**  Reading `sp + j`
    (`j < 2^63`) after the two-store push at `sp - 16` and `(sp - 16) + 8`
    returns the value from the old memory.  This is the frame-preservation
    combinator every body block needs: the loop's pushes sit below the
    caller's saved slots. -/
theorem mem_read_push_frame (mem : Nat → UInt8) (sp : UInt64) {j : Nat} (hj : j < 2^63)
    (v w : UInt64) :
    mem_read_u64
      (mem_write_u64 (mem_write_u64 mem (sp - UInt64.ofNat 16).toNat v)
        ((sp - UInt64.ofNat 16) + 8).toNat w) ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64 mem ((sp + UInt64.ofNat j).toNat) := by
  have haddr : (((sp - UInt64.ofNat 16) + 8 : UInt64).toNat) = (sp - UInt64.ofNat 8).toNat := by
    rw [u64_sub_add]
    rfl
  rw [haddr,
      mem_read_after_write_u64_ne _ _ _ _
        ((u64_write_read_disjoint sp (K := 8) (j := j) (by decide) (by decide)
          (by omega) (by omega)).elim Or.inr Or.inl),
      mem_read_after_write_u64_ne _ _ _ _
        ((u64_write_read_disjoint sp (K := 16) (j := j) (by decide) (by decide)
          hj (by omega)).elim Or.inr Or.inl)]


/-- `(sp - d) + d = sp` (bitvector cancellation). -/
theorem u64_sub_add_self (sp d : UInt64) : (sp - d) + d = sp := by grind


/-! ## Routed per-instruction step lemmas and loop-contract helpers

Promoted from the former `lib/work.lean` (now empty): these are proven,
generic, and used by the generator's `{name}_sr_N` routing and the
decrement-while loop contract.  See HARD §0.10/§0.10.1. -/

/-- §8.4(1) body_run: body run + back-edge as one `arm64_runs` certificate. -/
theorem work_body_run (code : Nat → UInt8) (m : Nat) (st mid : Arm64State) (tgt : Nat)
    (h1 : arm64_runs code m st = some mid)
    (h2 : arm64_step mid code = some { mid with pc := tgt })
    (h3 : tgt ≠ mid.pc) :
    arm64_runs code (m + 1) st = some { mid with pc := tgt } := by
  rw [runs_append_some code m 1 st mid h1]
  simp only [arm64_runs, h2]
  rw [if_neg h3]

/-- §8.4(2) body_mid: the composed body+branch avoids the exit pc. -/
theorem work_body_mid (code : Nat → UInt8) (m : Nat) (st mid : Arm64State) (tgt exit : Nat)
    (h1 : arm64_runs code m st = some mid)
    (h2 : arm64_step mid code = some { mid with pc := tgt })
    (h3 : ∀ u, u < m → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit)
    (h4 : tgt ≠ exit)
    (h5 : mid.pc ≠ exit) :
    ∀ u, u < m + 1 → ∀ su, arm64_runs code u st = some su → su.pc ≠ exit := by
  intro u hu su hsu
  rcases Nat.lt_or_eq_of_le (Nat.le_of_lt_succ hu) with hlt | heq
  · exact h3 u hlt su hsu
  · subst u
    have hmid : mid = su := by injection (h1.symm.trans hsu)
    rw [← hmid]
    exact h5

/-- §8.4(3) fuel: the countdown loop fuel bound, in omega-ready form. -/
theorem work_loop_fuel (mc mb me k fuel : Nat)
    (h : (mc + mb + 2) * k + (mc + me + 2) ≤ fuel) :
    (mc + mb + 2) * k + (mc + me + 2) ≤ fuel := by
  exact h

/-- §8.4(4) exit: package `while_dec_exit_contract`'s exit obligations. -/
theorem work_exit_hyps (code : Nat → UInt8) (exitBpc exit : Nat) (ex : Arm64State → Arm64State)
    (hpc : ∀ st, st.pc = exitBpc → (ex st).pc = exit)
    (hrun : ∀ st, st.pc = exitBpc → arm64_runs code 5 st = some (ex st)) :
    (∀ st, st.pc = exitBpc → (ex st).pc = exit) := by
  exact hpc

/-! Per-instruction step lemmas (routed from the generator)

Each `work_step_*` states the `arm64_step` result for one decoded instruction
kind in terms of the word's bit-fields; proved by unfolding `arm64_step` and
reducing the decode chain.  The generator's `{name}_sr_N` is a call to one of
these. -/

/-- Per-instruction step: `work_step_ret`. -/
theorem work_step_ret (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : w = (0xd65f03c0 : UInt32)) :
    arm64_step s code = some { s with pc := s.x30.toNat } := by
  unfold arm64_step
  rw [hpc, hread]
  rw [if_pos h]

/-- Per-instruction step: `work_step_mov`. -/
theorem work_step_mov (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x2a00fa00) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  rw [if_neg hne_ret, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_add_reg`. -/
theorem work_step_add_reg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x8b000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s + arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_sub_reg`. -/
theorem work_step_sub_reg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xcb000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s - arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_mul`. -/
theorem work_step_mul (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe07c00) = 0x9b007c00) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s * arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_neg`. -/
theorem work_step_neg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xfffffc1f) = 0xcb0003e0) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (-(arm64_reg (((w >>> 16) &&& 0x1f).toNat) s))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_cmp_reg`. -/
theorem work_step_cmp_reg (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xeb000000) :
    arm64_step s code = some { s with nzcv := arm64_subs_flags (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) (arm64_reg (((w >>> 16) &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_and`. -/
theorem work_step_and (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x8a000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s &&& arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_eor`. -/
theorem work_step_eor (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xca000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s ^^^ arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_add_imm32`. -/
theorem work_step_add_imm32 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x11000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s + UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_add_imm64`. -/
theorem work_step_add_imm64 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x91000000) :
    arm64_step s code = (if ((w &&& 0x1f).toNat) = 31 then some { s with sp := (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat) } else some (arm64_set_reg ((w &&& 0x1f).toNat) s ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat)))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_sub_imm32`. -/
theorem work_step_sub_imm32 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0x51000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s - UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_sub_imm64`. -/
theorem work_step_sub_imm64 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0xd1000000) :
    arm64_step s code = (if ((w &&& 0x1f).toNat) = 31 then some { s with sp := (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat) } else some (arm64_set_reg ((w &&& 0x1f).toNat) s ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat)))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_cmp_imm`. -/
theorem work_step_cmp_imm (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0xf1000000) :
    arm64_step s code = some { s with nzcv := arm64_subs_flags (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) (UInt64.ofNat (((w >>> 10) &&& 0xfff).toNat)) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_pos h]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_ldr_uoff`.

    `LDR Xt, [Xn, #imm]` (0xF9400000): `Xt := mem64[Xn + imm]`, and NOTHING
    else moves -- in particular `sp` does not, which is the whole point.  The
    base is the instruction's `Rn`, not `SP`.

    Named `_uoff` (unsigned offset) to match the A64 encoding.  The generator
    still asks for this by its historical name `work_step_ldr_pre`, which is
    the alias immediately below; see the note there. -/
theorem work_step_ldr_uoff (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xf9400000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem
      ((arm64_reg ((w >>> 5) &&& 0x1f).toNat) s
        + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_ldr_pre` -- HISTORICAL NAME, see
    `work_step_ldr_uoff` for the statement and the reasoning.

    `formal/arm64_proof_gen.py`'s `_WORK_STEP` table dispatches on this name
    (`(18, "work_step_ldr_pre", [(0xffe00000, 0xf9400000)])`), so the name is
    load-bearing for the generator even though it is wrong: the opcode is a
    plain unsigned-offset load, not a pre-index store.  Renaming the generator
    entry to `work_step_ldr_uoff` and deleting this alias is a one-line change
    in `_WORK_STEP` with no effect on any proof; it is left to a commit that
    owns that file rather than done here, because four other agents are in
    `formal/`. -/
theorem work_step_ldr_pre : ∀ (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xf9400000),
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem
      ((arm64_reg ((w >>> 5) &&& 0x1f).toNat) s
        + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat)) :=
  work_step_ldr_uoff

/-- Per-instruction step: `work_step_ldr_post`. -/
theorem work_step_ldr_post (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xb9000000) :
    arm64_step s code = some { (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem s.sp.toNat)) with sp := s.sp + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_adrp`. -/
theorem work_step_adrp (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0x9f000000) = 0x90000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat pc - (UInt64.ofNat pc) % (4096 : UInt64) + (if ((((w >>> 5) &&& 0x7ffff).toNat) * 4 + ((w >>> 29) &&& 0x3).toNat) ≥ 2^20 then UInt64.ofNat ((((w >>> 5) &&& 0x7ffff).toNat) * 4 + ((w >>> 29) &&& 0x3).toNat) - UInt64.ofNat (2^21) else UInt64.ofNat ((((w >>> 5) &&& 0x7ffff).toNat) * 4 + ((w >>> 29) &&& 0x3).toNat)) * (4096 : UInt64))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_stp`. -/
theorem work_step_stp (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffc00000) = 0xa9800000) :
    arm64_step s code = some { s with sp := (if (((w >>> 15) &&& 0x7f).toNat) ≥ 64 then (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((128 - (((w >>> 15) &&& 0x7f).toNat)) * 8) else (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8)), mem := mem_write_u64 (mem_write_u64 s.mem (if (((w >>> 15) &&& 0x7f).toNat) ≥ 64 then (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((128 - (((w >>> 15) &&& 0x7f).toNat)) * 8) else (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8)).toNat (arm64_reg ((w &&& 0x1f).toNat) s)) ((if (((w >>> 15) &&& 0x7f).toNat) ≥ 64 then (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) - UInt64.ofNat ((128 - (((w >>> 15) &&& 0x7f).toNat)) * 8) else (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8)) + 8).toNat (arm64_reg (((w >>> 10) &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_ldp_post`. -/
theorem work_step_ldp_post (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffc00000) = 0xa8c00000) :
    arm64_step s code = some { (arm64_set_reg (((w >>> 10) &&& 0x1f).toNat) (arm64_set_reg ((w &&& 0x1f).toNat) s (mem_read_u64 s.mem (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s).toNat)) (mem_read_u64 s.mem ((if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + 8).toNat)) with sp := (if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else arm64_reg (((w >>> 5) &&& 0x1f).toNat) s) + UInt64.ofNat ((((w >>> 15) &&& 0x7f).toNat) * 8) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_movz`. -/
theorem work_step_movz (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x52800000 ∨ (w &&& 0xffe00000) = 0xd2800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat (((w >>> 5) &&& 0xffff).toNat))) := by
  rcases h with h | h
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by native_decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by native_decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_orr`. -/
theorem work_step_orr (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xaa000000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s ||| arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_movk`. -/
theorem work_step_movk (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff800000) = 0xf2800000 ∨ (w &&& 0xff800000) = 0x72800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (arm64_reg ((w &&& 0x1f).toNat) s ||| (UInt64.ofNat (((w >>> 5) &&& 0xffff).toNat) <<< UInt64.ofNat ((((w >>> 21) &&& 0x3).toNat) * 16)))) := by
  rcases h with h | h
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by native_decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
    have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
    have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp
  ·
    unfold arm64_step
    rw [hpc, hread]
    have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
      intro t; rw [t] at h; exact absurd h (by native_decide)
    have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
    have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
    have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
    have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
    have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
    have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
    have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
    have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
    have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
    have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
    have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
    have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
    have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
    have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
    have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
    have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
    have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
    have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
    have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
    have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
    have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
    have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
    have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
    have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
    have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
    have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
    have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
    rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_movn32`. -/
theorem work_step_movn32 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x12800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat (0xffff_ffff - (((w >>> 5) &&& 0xffff).toNat)))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_movn64`. -/
theorem work_step_movn64 (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0x92800000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (UInt64.ofNat (0xffff_ffff_ffff_ffff - (((w >>> 5) &&& 0xffff).toNat)))) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_cset`. -/
theorem work_step_cset (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffff0fe0) = 0x9a9f07e0) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s (if arm64_matches_condition (if ((w >>> 12) &&& 0xf) &&& 0x1 = 0 then (((w >>> 12) &&& 0xf) + 1).toNat else (((w >>> 12) &&& 0xf) - 1).toNat) s.nzcv then 1 else 0)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_str_uoff`.

    `STR Xt, [Xn, #imm]` (0xF9000000): `mem64[Xn + imm] := Xt`, nothing else
    moves.  The base is the instruction's `Rn`; this used to be `s.sp`,
    hardwired, which agrees with the architecture only in the `Rn = 31`
    spelling and is silently wrong for every heap write. -/
theorem work_step_str_uoff (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xf9000000) :
    arm64_step s code = some { s with
      mem := mem_write_u64 s.mem
        ((arm64_reg ((w >>> 5) &&& 0x1f).toNat) s
          + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat
        (arm64_reg ((w &&& 0x1f).toNat) s) } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_str_off` -- kept as the name the proof
    generator dispatches on (`_WORK_STEP` entry 31).  The statement is
    `work_step_str_uoff`'s; see that lemma for what changed and why the old
    `s.sp` base was wrong. -/
theorem work_step_str_off : ∀ (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xf9000000),
    arm64_step s code = some { s with
      mem := mem_write_u64 s.mem
        ((arm64_reg ((w >>> 5) &&& 0x1f).toNat) s
          + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat
        (arm64_reg ((w &&& 0x1f).toNat) s) } :=
  work_step_str_uoff

/-- Per-instruction step: `work_step_ldp_off`. -/
theorem work_step_ldp_off (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffc00000) = 0xa9400000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) (arm64_set_reg (((w >>> 5) &&& 0x1f).toNat) s (mem_read_u64 s.mem (s.sp + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)).toNat)) (mem_read_u64 s.mem ((s.sp + UInt64.ofNat ((((w >>> 10) &&& 0xfff).toNat) * 8)) + 8).toNat)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0xf9000000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_orn`. -/
theorem work_step_orn (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe00000) = 0xa200000) :
    arm64_step s code = some (arm64_set_reg ((w &&& 0x1f).toNat) s ((arm64_reg (((w >>> 10) &&& 0x1f).toNat) s) ^^^ (0xffffffffffffffff : UInt64) ||| arm64_reg (((w >>> 16) &&& 0x1f).toNat) s)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0xf9000000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffc00000) = 0xa9400000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_br`. -/
theorem work_step_br (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xfffffc1f) = 0xd61f0000) :
    arm64_step s code = some { s with pc := (arm64_reg (((w >>> 5) &&& 0x1f).toNat) s).toNat } := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0xf9000000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffc00000) = 0xa9400000) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0x0a200000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-- Per-instruction step: `work_step_svc`. -/
theorem work_step_svc (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xffe0001f) = 0xd4000001) :
    arm64_step s code = some s := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0xf9000000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffc00000) = 0xa9400000) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xffe00000) = 0x0a200000) := by intro t; bv_decide
  have hne_35 : ¬ ((w &&& 0xfffffc1f) = 0xd61f0000) := by intro t; bv_decide
  have hne_bcond : ¬ ((w &&& 0xff000000) = 0x54000000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5, if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10, if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15, if_neg hne_16, if_neg hne_17, if_neg hne_18, if_neg hne_19, if_neg hne_20, if_neg hne_21, if_neg hne_22, if_neg hne_23, if_neg hne_24, if_neg hne_25, if_neg hne_26, if_neg hne_27, if_neg hne_28, if_neg hne_29, if_neg hne_30, if_neg hne_31, if_neg hne_32, if_neg hne_33, if_neg hne_34, if_neg hne_35, if_pos h, if_neg hne_bcond]; try dsimp; try rfl; try simp

/-! ### CBZ / CBNZ step lemmas

  The `work_step_*` family above covers every fixed-shape instruction, but the
  conditional branches additionally split on a *runtime* register test, so the
  residual goal after the decode chain is an `if` on `arm64_reg rn s`.  That
  split is stated here once, in the exact guard shape each opcode uses in
  `arm64_step` (CBZ guards on `= 0`, CBNZ on `≠ 0`), so callers never have to
  re-derive it: the negative case of a `= 0` split is `¬ (x ≠ 0)`, which `simp`
  cannot turn back into `x = 0`, so splitting on the opposite guard silently
  leaves a goal open. -/

/-- CBZ's sign-extended 19-bit byte offset, as `arm64_step` computes it. -/
def cbz_off64 (w : UInt32) : UInt64 :=
  let imm19 := (w >>> 5) &&& 0x7ffff
  if (imm19 &&& 0x40000) ≠ 0
    then (UInt64.ofNat imm19.toNat) - (UInt64.ofNat (2^19))
    else UInt64.ofNat imm19.toNat

/-- CBNZ's sign-extended 19-bit byte offset, as `arm64_step` computes it. -/
def cbnz_off64 (w : UInt32) : UInt64 :=
  let imm19 := (w >>> 5) &&& 0x7ffff
  if (imm19 &&& 0x40000) ≠ 0
    then (UInt64.ofNat imm19.toNat) - (UInt64.ofNat (2^19))
    else UInt64.ofNat imm19.toNat

/-- Per-instruction step: `work_step_cbz` (branch if zero, guard `= 0`). -/
theorem work_step_cbz (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff000000) = 0xb4000000) :
    arm64_step s code
      = (if arm64_reg ((w &&& 0x1f).toNat) s = 0
           then (some { s with pc := (UInt64.ofNat s.pc + cbz_off64 w * 4).toNat } : Option Arm64State)
           else (some { s with pc := s.pc + 4 } : Option Arm64State)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_18 : ¬ ((w &&& 0xff000000) = 0xb5000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0xf9000000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffc00000) = 0xa9400000) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xff000000) = 0x0a200000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5,
      if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10,
      if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15,
      if_neg hne_16, if_neg hne_19]
  simp [h, cbz_off64, cbnz_off64]

/-- Per-instruction step: `work_step_cbnz` (branch if non-zero, guard `≠ 0`). -/
theorem work_step_cbnz (s : Arm64State) (code : Nat → UInt8) (pc : Nat) (w : UInt32)
    (hpc : s.pc = pc) (hread : arm64_read_insn code pc = w)
    (h : (w &&& 0xff000000) = 0xb5000000) :
    arm64_step s code
      = (if arm64_reg ((w &&& 0x1f).toNat) s ≠ 0
           then (some { s with pc := (UInt64.ofNat s.pc + cbnz_off64 w * 4).toNat } : Option Arm64State)
           else (some { s with pc := s.pc + 4 } : Option Arm64State)) := by
  unfold arm64_step
  rw [hpc, hread]
  have hne_ret : w ≠ (0xd65f03c0 : UInt32) := by
    intro t; rw [t] at h; exact absurd h (by native_decide)
  have hne_2 : ¬ ((w &&& 0xffe00000) = 0x2a00fa00) := by intro t; bv_decide
  have hne_3 : ¬ ((w &&& 0xffe00000) = 0x8b000000) := by intro t; bv_decide
  have hne_4 : ¬ ((w &&& 0xffe00000) = 0xcb000000) := by intro t; bv_decide
  have hne_5 : ¬ ((w &&& 0xffe07c00) = 0x9b007c00) := by intro t; bv_decide
  have hne_6 : ¬ ((w &&& 0xfffffc1f) = 0xcb0003e0) := by intro t; bv_decide
  have hne_7 : ¬ ((w &&& 0xffe00000) = 0xeb000000) := by intro t; bv_decide
  have hne_8 : ¬ ((w &&& 0xffe00000) = 0x8a000000) := by intro t; bv_decide
  have hne_9 : ¬ ((w &&& 0xffe00000) = 0xca000000) := by intro t; bv_decide
  have hne_10 : ¬ ((w &&& 0xff800000) = 0x11000000) := by intro t; bv_decide
  have hne_11 : ¬ ((w &&& 0xff800000) = 0x91000000) := by intro t; bv_decide
  have hne_12 : ¬ ((w &&& 0xff800000) = 0x51000000) := by intro t; bv_decide
  have hne_13 : ¬ ((w &&& 0xff800000) = 0xd1000000) := by intro t; bv_decide
  have hne_14 : ¬ ((w &&& 0xff800000) = 0xf1000000) := by intro t; bv_decide
  have hne_15 : ¬ ((w &&& 0xfc000000) = 0x14000000) := by intro t; bv_decide
  have hne_16 : ¬ ((w &&& 0xfc000000) = 0x94000000) := by intro t; bv_decide
  have hne_17 : ¬ ((w &&& 0xff000000) = 0xb4000000) := by intro t; bv_decide
  have hne_19 : ¬ ((w &&& 0xffe00000) = 0xf9400000) := by intro t; bv_decide
  have hne_20 : ¬ ((w &&& 0xffe00000) = 0xb9000000) := by intro t; bv_decide
  have hne_21 : ¬ ((w &&& 0x9f000000) = 0x90000000) := by intro t; bv_decide
  have hne_22 : ¬ ((w &&& 0xffc00000) = 0xa9800000) := by intro t; bv_decide
  have hne_23 : ¬ ((w &&& 0xffc00000) = 0xa8c00000) := by intro t; bv_decide
  have hne_24 : ¬ ((w &&& 0xffe00000) = 0x52800000) := by intro t; bv_decide
  have hne_25 : ¬ ((w &&& 0xffe00000) = 0xd2800000) := by intro t; bv_decide
  have hne_26 : ¬ ((w &&& 0xffe00000) = 0xaa000000) := by intro t; bv_decide
  have hne_27 : ¬ ((w &&& 0xff800000) = 0xf2800000) := by intro t; bv_decide
  have hne_28 : ¬ ((w &&& 0xff800000) = 0x72800000) := by intro t; bv_decide
  have hne_29 : ¬ ((w &&& 0xffe00000) = 0x12800000) := by intro t; bv_decide
  have hne_30 : ¬ ((w &&& 0xffe00000) = 0x92800000) := by intro t; bv_decide
  have hne_31 : ¬ ((w &&& 0xffff0fe0) = 0x9a9f07e0) := by intro t; bv_decide
  have hne_32 : ¬ ((w &&& 0xffe00000) = 0xf9000000) := by intro t; bv_decide
  have hne_33 : ¬ ((w &&& 0xffc00000) = 0xa9400000) := by intro t; bv_decide
  have hne_34 : ¬ ((w &&& 0xff000000) = 0x0a200000) := by intro t; bv_decide
  rw [if_neg hne_ret, if_neg hne_2, if_neg hne_3, if_neg hne_4, if_neg hne_5,
      if_neg hne_6, if_neg hne_7, if_neg hne_8, if_neg hne_9, if_neg hne_10,
      if_neg hne_11, if_neg hne_12, if_neg hne_13, if_neg hne_14, if_neg hne_15,
      if_neg hne_16, if_neg hne_17]
  simp [h, cbz_off64, cbnz_off64]

/-- **Peel one STP pair below `sp`.**

    The emitter writes a frame slot pair as two `mem_write_u64`s at
    `(sp - K)` and `(sp - K) + 8`.  Both are strictly below `sp` for `K ≥ 8`,
    so neither can affect a read at `sp + j`, and the pair peels in one step.

    Peeling per-distance instead would have to canonicalise `(sp - K) + 8` into
    `sp - UInt64.ofNat (K - 8)` first — the frame canonicalisation's
    `u64_sub_add` produces that split form, and folding it back needs a rewrite
    whose side conditions `simp` will not discharge on its own.  Matching the
    pair's shape directly keeps the generator from reshaping addresses at all.

    `16 ≤ K` is not decoration: the pair's second half lands at
    `sp - UInt64.ofNat (K - 8)`, so it clears `sp` only when `K - 8 ≥ 8`.  At
    `K = 8` that half sits *at* `sp` and overlaps a read at `sp + 0`, so the
    caller has to use the single-store peel for that distance instead.  The
    emitter's frame slots are all 16-byte aligned, so the pair form is the
    common case and `K = 8` the exception. -/
theorem mem_read_write_pair_below (mem : Nat → UInt8) (sp : UInt64)
    {K j : Nat} (hKlt : K < 2 ^ 64) (hjnw : sp.toNat + j < 2 ^ 64)
    (hKsp : K ≤ sp.toNat) (hK : 16 ≤ K) (v1 v2 : UInt64) :
    mem_read_u64
        (mem_write_u64
          (mem_write_u64 mem ((sp - UInt64.ofNat K).toNat) v1)
          ((sp - UInt64.ofNat K) + UInt64.ofNat 8).toNat v2)
        ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64 mem ((sp + UInt64.ofNat j).toNat) := by
  have hsub : (sp - UInt64.ofNat K).toNat = sp.toNat - K :=
    u64_toNat_sub_lit sp K hKlt hKsp
  have hlt : sp.toNat < 2 ^ 64 := UInt64.toNat_lt sp
  have hlt' : sp.toNat ≤ 18446744073709551615 := by omega
  have h8n : (UInt64.ofNat 8).toNat = 8 := rfl
  -- `8 ≤ K` puts the pair's second half back inside the frame, so the `+ 8`
  -- stays below the stack top and cannot wrap.
  have hplus : ((sp - UInt64.ofNat K) + UInt64.ofNat 8).toNat
      = (sp.toNat - K) + 8 := by
    rw [u64_toNat_add_lit, hsub, h8n]
    apply Nat.mod_eq_of_lt
    have hle : (sp.toNat - K) + 8 ≤ sp.toNat := by omega
    omega
  have hj64 : j < 2 ^ 64 := by omega
  have hjnw' : (sp + UInt64.ofNat j).toNat = sp.toNat + j := by
    rw [u64_toNat_add_lit, UInt64.toNat_ofNat', Nat.mod_eq_of_lt hj64]
    exact Nat.mod_eq_of_lt hjnw
  -- The pair sits below `sp` and the read at or above it, so the write's
  -- 8 bytes must clear the read's: `write + 8 ≤ read`.
  have hwrite8 : ((sp - UInt64.ofNat K) + UInt64.ofNat 8).toNat + 8
      ≤ ((sp + UInt64.ofNat j).toNat) := by
    rw [hplus, hjnw']
    have hge : K ≤ sp.toNat := hKsp
    have h8 : (8 : Nat) ≤ K := by omega
    omega
  -- Stated in the goal's own shape, so no address rewriting is needed on
  -- either side of the `rw`.
  have hne : mem_read_u64
        (mem_write_u64
          (mem_write_u64 mem ((sp - UInt64.ofNat K).toNat) v1)
          ((sp - UInt64.ofNat K) + UInt64.ofNat 8).toNat v2)
        ((sp + UInt64.ofNat j).toNat)
      = mem_read_u64
        (mem_write_u64 mem ((sp - UInt64.ofNat K).toNat) v1)
        ((sp + UInt64.ofNat j).toNat) :=
    mem_read_after_write_u64_ne _ _ _ _ (Or.inr hwrite8)
  rw [hne]
  exact mem_read_write_below mem sp hjnw hKsp (by omega) v1

/-- **Split offset back into an STP pair's shape.**  `u64_sub_add` rewrites an
    address `(sp - K) + 8` into the split form `sp - (K - 8)`, which is what
    the frame canonicalisation wants for the *sp value* but not for a store
    address.  This is the inverse, so a store address that has been through
    `u64_sub_add` can be handed to `mem_read_write_pair_below`, which matches
    the pair's two stores in their natural `(sp - K)` / `(sp - K) + 8` shape.

    `u64_sub_add` is an unconditional bitvector equality, so its inverse is too
    and needs no side conditions. -/
theorem u64_add_sub_lit (sp : UInt64) (a b : Nat) :
    sp - (UInt64.ofNat a - UInt64.ofNat b)
      = (sp - UInt64.ofNat a) + UInt64.ofNat b :=
  (u64_sub_add sp (UInt64.ofNat a) (UInt64.ofNat b)).symm

/-- **Collapse a nested literal offset into a single subtraction.**

    The frame canonicalisation rewrites each address of a store pair,
    `(sp - K) + 8`, into the split `sp - (K - 8)`, and applying it across
    several blocks nests those splits:
    `sp - (K - (K2 - (K2 - 8)))`.  Peeling such a stack needs every address
    back in the single-literal form `sp - UInt64.ofNat K`.

    `u64_sub_add` is an unconditional bitvector equality, so it converts each
    split back without side conditions; only the `ofNat` reduction inside one
    address needs the literals' bounds.  Feeding `u64_sub_lit_sub` and
    `u64_ofNat_sub` to `simp` in sequence instead oscillates, because each
    exposes work for the other. -/
theorem u64_sub_nest_lit (sp : UInt64) (a b c : Nat)
    (h1 : c ≤ b) (h2 : b ≤ a) (hMa : a < 2 ^ 64) (hMb : b < 2 ^ 64)
    (hMc : c < 2 ^ 64) :
    sp - (UInt64.ofNat a - (UInt64.ofNat b - UInt64.ofNat c))
      = sp - UInt64.ofNat (a - (b - c)) := by
  rw [← u64_sub_add, u64_ofNat_sub b c h1 hMb, u64_sub_add,
      u64_ofNat_sub a (b - c) (by omega) hMa]

example (sp : UInt64) (a b c : Nat)
    (h1 : c ≤ b) (h2 : b ≤ a) (hMa : a < 2 ^ 64) (hMb : b < 2 ^ 64)
    (hMc : c < 2 ^ 64) :
    sp - (UInt64.ofNat a - (UInt64.ofNat b - UInt64.ofNat c))
      = sp - UInt64.ofNat (a - (b - c)) :=
  u64_sub_nest_lit sp a b c h1 h2 hMa hMb hMc

structure DylibExport where
  module : String
  symbol : String
  entry : Nat
  arity : Nat

structure DylibImage where
  base : Nat
  codeSize : Nat
  exports : List DylibExport

namespace DylibExport

def offset (image : DylibImage) (export_ : DylibExport) : Nat :=
  export_.entry - image.base

def InImage (image : DylibImage) (export_ : DylibExport) : Prop :=
  export_.entry ≥ image.base ∧ offset image export_ < image.codeSize

def Semantics (image : DylibImage) (export_ : DylibExport)
    (observables : List (UInt64 → UInt64)) : Prop :=
  ∀ observable, observable ∈ observables → True

theorem offset_stub (image : DylibImage) (export_ : DylibExport) :
    offset image export_ = export_.entry - image.base := rfl

theorem in_image_stub (image : DylibImage) (export_ : DylibExport) :
    InImage image export_ := by sorry

theorem semantics_stub (image : DylibImage) (export_ : DylibExport)
    (observables : List (UInt64 → UInt64)) :
    Semantics image export_ observables := by sorry

end DylibExport


/-!
# Receiver frames: a struct with more than one field, by reference

`MojoExpr` has no aggregate constructor, `Arm64State`'s registers are one
`UInt64` each, and `evalFunc` takes one `UInt64`, so a two-field struct has
nothing to *be* as a value.  There is nevertheless a way to give a multi-field
struct a representation **without changing the value model at all**: lower the
receiver **by reference**.  The receiver word is the *address* of an out-of-line
frame of 8-byte slots, and `self.<field>` is a load from `mem[base + 8*k]`.

A pointer is one word, so:

* no value becomes two words -- `Arm64State` is untouched;
* `MojoFunc.mk` keeps its single parameter, because `self` **is** that
  parameter and a pointer is a `UInt64` -- `evalFunc`, `evalBodyEnv` and their
  ~40 per-node lemmas are untouched;
* `Refine.Post`/`contract_sound`/`runProg` are untouched, because they are
  already stated over `UInt64 → UInt64` and the receiver word is the argument.

What the design costs instead is on the *source* side (a method's semantics is
a second environment, `String → UInt64`, alongside the locals -- a new
evaluator, not a change to `evalExpr`) and on the *callee contract* side
(`Refine.FrameOk_except`: a method that mutates its receiver violates
`FrameOk`'s "caller's slots preserved" clause by construction).  Both are
additions beside the existing definitions.

`bugs/FORMAL_wide_receiver_by_reference.md` has the full design, the cost, and
what is not done.
-/

namespace Frame

/-- Byte size of one frame slot.  A field is one 64-bit word on this path, so a
    slot is 8 bytes and the layout adds no padding of its own. -/
abbrev SLOT : Nat := 8

/-- A frame layout: a base address and a slot count.  `slots` is the struct's
    *derived* field count (`formal/model.py`'s `struct_field_count`), so a
    2-field receiver is a 2-slot frame and the 3-to-6 band is a 3-to-6-slot
    frame: the same code, parameterised, which is why the width bands are not
    three separate projects. -/
structure Frame where
  base : UInt64
  slots : Nat
  deriving Inhabited

/-- Byte offset of slot `k` within a frame. -/
def frameOffset (k : Nat) : Nat := SLOT * k

/-- Total byte size of a frame with `n` slots. -/
def frameBytes (n : Nat) : Nat := SLOT * n

/-- Address of slot `k` of the frame based at `base`. -/
def frameAddr (base : UInt64) (k : Nat) : Nat :=
  (base + UInt64.ofNat (frameOffset k)).toNat

/-- Read slot `k` out of `mem`.  This is what `self.<field at slot k>` means. -/
def frameRead (mem : Nat → UInt8) (base : UInt64) (k : Nat) : UInt64 :=
  mem_read_u64 mem (frameAddr base k)

/-- Write slot `k` of `mem`.  This is what `self.<field at slot k> = v` means. -/
def frameWrite (mem : Nat → UInt8) (base : UInt64) (k : Nat) (v : UInt64) : Nat → UInt8 :=
  mem_write_u64 mem (frameAddr base k) v

/-- **No wraparound.**  Every slot address of a frame based at `base` with `n`
    slots is a genuine `base + 8*k` rather than a wrapped one.  The bound is
    stated on the largest slot index in scope, which is what the `+ 1` in each
    use is for.

    This premise is not decoration.  `frameAddr` is a `UInt64`, so without it
    two different slots of a frame that runs off the top of the address space
    can share an address, and every "different slots are independent" lemma
    below would be false. -/
def FrameFits (base : UInt64) (n : Nat) : Prop :=
  base.toNat + frameBytes n < 2 ^ 64

/-- The frame does not reach the stack pointer, so it cannot overlap anything the
    caller is relying on.  This is the premise the callee contract needs, and
    it is why the receiver frame is carved out of the region *below* the callee's
    own `sp` rather than out of the red zone above it: a frame above `sp` would
    sit inside the window `FrameOk` promises the callee will not touch, and a
    method is supposed to touch it. -/
def FrameBelow (base sp : UInt64) (n : Nat) : Prop :=
  base.toNat + frameBytes n ≤ sp.toNat

/-- `FrameFits` is downward closed in the slot count, which is what lets a
    caller discharge it once for a whole frame and then specialise. -/
theorem FrameFits.mono {base : UInt64} {n n' : Nat} (h : FrameFits base n')
    (hle : n ≤ n') : FrameFits base n := by
  simp only [FrameFits, frameBytes, SLOT] at *
  omega

/-- Every slot's offset fits inside the frame's own byte count.  The
    workhorse for turning a `k < n` bound into a byte bound. -/
theorem frameOffset_le_bytes (k : Nat) : frameOffset k ≤ frameBytes (k + 1) := by
  simp only [frameOffset, frameBytes, SLOT]
  omega

/-- Slot offsets are monotone in the slot index. -/
theorem frameOffset_mono {k k' : Nat} (h : k ≤ k') : frameOffset k ≤ frameOffset k' := by
  simp only [frameOffset, SLOT]
  omega

/-- Frame sizes are monotone in the slot count. -/
theorem frameBytes_mono {n n' : Nat} (h : n ≤ n') : frameBytes n ≤ frameBytes n' := by
  simp only [frameBytes, SLOT]
  omega

/-- Advancing one slot advances the offset by exactly one slot size, which is
    also the frame's size for a one-slot-larger frame.  This is the arithmetic
    that makes two *adjacent* slots disjoint. -/
theorem frameOffset_step (k : Nat) : frameOffset k + SLOT = frameBytes (k + 1) := by
  simp only [frameOffset, frameBytes, SLOT]
  omega

/-- `frameAddr` really is `base + 8*k` in `Nat` arithmetic when the frame
    fits.  This is the step that makes every later lemma a `Nat` fact rather
    than a `UInt64` one, and it is why the layout needs a `FrameFits` premise
    at all. -/
theorem frameAddr_eq (base : UInt64) (k : Nat) (h : FrameFits base (k + 1)) :
    frameAddr base k = base.toNat + frameOffset k := by
  have hbytes : frameBytes (k + 1) < 2 ^ 64 := by
    have hh := h
    simp only [FrameFits] at hh
    omega
  have hoff : frameOffset k < 2 ^ 64 := by
    have hle := frameOffset_le_bytes k
    omega
  have hb := UInt64.toNat_lt base
  have hlt : base.toNat + frameOffset k < 2 ^ 64 := by
    have h1 : base.toNat + frameOffset k ≤ base.toNat + frameBytes (k + 1) :=
      Nat.add_le_add_left (frameOffset_le_bytes k) _
    have h2 : base.toNat + frameBytes (k + 1) < 2 ^ 64 := by
      have hh := h
      simp only [FrameFits] at hh
      exact hh
    omega
  have ho : (UInt64.ofNat (frameOffset k)).toNat = frameOffset k :=
    UInt64.toNat_ofNat'.trans (Nat.mod_eq_of_lt hoff)
  unfold frameAddr
  rw [UInt64.toNat_add, ho, Nat.mod_eq_of_lt hlt]

/-- Slot addresses are monotone in the slot index. -/
theorem frameAddr_mono (base : UInt64) {k k' : Nat} (h : FrameFits base (k' + 1))
    (hle : k ≤ k') : frameAddr base k ≤ frameAddr base k' := by
  have h1 : frameAddr base k = base.toNat + frameOffset k :=
    frameAddr_eq base k (h.mono (n := k + 1) (by omega))
  have h2 : frameAddr base k' = base.toNat + frameOffset k' := frameAddr_eq base k' h
  rw [h1, h2]
  exact Nat.add_le_add_left (frameOffset_mono hle) _

/-- Adjacent slots are exactly one slot apart. -/
theorem frameAddr_step (base : UInt64) (k : Nat) (h : FrameFits base (k + 2)) :
    frameAddr base k + SLOT = frameAddr base (k + 1) := by
  have h1 : frameAddr base k = base.toNat + frameOffset k :=
    frameAddr_eq base k (h.mono (n := k + 1) (by omega))
  have h2 : frameAddr base (k + 1) = base.toNat + frameOffset (k + 1) :=
    frameAddr_eq base (k + 1) (h.mono (n := k + 2) (by omega))
  rw [h1, h2]
  simp only [frameOffset, SLOT]
  omega

/-- **Distinct slots have disjoint byte ranges.**  `mem_read_after_write_u64_ne`
    is stated on disjointness rather than on `≠`, so this is the form the rest
    of the section consumes; the `max` in the premise is what lets a caller
    discharge it once for a whole frame rather than per pair. -/
theorem frameAddr_disjoint (base : UInt64) {k k' : Nat} (hne : k ≠ k')
    (h : FrameFits base (max k k' + 1)) :
    frameAddr base k + SLOT ≤ frameAddr base k' ∨ frameAddr base k' + SLOT ≤ frameAddr base k := by
  rcases Nat.lt_trichotomy k k' with hlt | heq | hgt
  · left
    have hfit : FrameFits base (k' + 1) := h.mono (n := k' + 1) (by simp [Nat.max_eq_right (Nat.le_of_lt hlt)])
    have h1 : frameAddr base k = base.toNat + frameOffset k :=
      frameAddr_eq base k (hfit.mono (n := k + 1) (by omega))
    have h2 : frameAddr base k' = base.toNat + frameOffset k' := frameAddr_eq base k' hfit
    rw [h1, h2]
    simp only [frameOffset, SLOT]
    omega
  · exact absurd heq hne
  · right
    have hfit : FrameFits base (k + 1) := h.mono (n := k + 1) (by simp [Nat.max_eq_left (Nat.le_of_lt hgt)])
    have h1 : frameAddr base k' = base.toNat + frameOffset k' :=
      frameAddr_eq base k' (hfit.mono (n := k' + 1) (by omega))
    have h2 : frameAddr base k = base.toNat + frameOffset k := frameAddr_eq base k hfit
    rw [h1, h2]
    simp only [frameOffset, SLOT]
    omega

@[simp] theorem frameRead_frameWrite_same (mem : Nat → UInt8) (base : UInt64)
    (k : Nat) (v : UInt64) :
    frameRead (frameWrite mem base k v) base k = v :=
  mem_read_after_write_u64 mem (frameAddr base k) v

/-- **A write to slot `k` is invisible to a read of a different slot.**  This
    is what makes the frame's slots independent, and therefore what makes a
    per-field source environment (`frameToEnv`/`envToFrame` below) a sound
    model of the frame. -/
theorem frameRead_frameWrite_ne (mem : Nat → UInt8) (base : UInt64) {k k' : Nat}
    (h : FrameFits base (max k k' + 1)) (hne : k ≠ k') (v : UInt64) :
    frameRead (frameWrite mem base k v) base k' = frameRead mem base k' := by
  rcases frameAddr_disjoint base hne h with hd | hd
  · exact mem_read_after_write_u64_ne mem (frameAddr base k) (frameAddr base k') v (Or.inr hd)
  · exact mem_read_after_write_u64_ne mem (frameAddr base k) (frameAddr base k') v (Or.inl hd)

/-- **A frame write leaves every byte outside the frame alone** -- at byte
    granularity, which is the granularity `mem_write_u64` actually works at. -/
theorem frameWrite_byte_untouched (mem : Nat → UInt8) (base : UInt64) (k : Nat)
    (v : UInt64) (a : Nat) (h : a < frameAddr base k ∨ frameAddr base k + SLOT ≤ a) :
    frameWrite mem base k v a = mem a :=
  memw_untouched mem (frameAddr base k) a v h

/-- **A frame write leaves every 8-byte word outside the frame alone.**  This is
    the whole content of "a method only touches its receiver's fields", stated
    once about memory rather than about a proof. -/
theorem frameWrite_read_outside (mem : Nat → UInt8) (base : UInt64) (k : Nat)
    (v : UInt64) (a : Nat)
    (h : a + SLOT ≤ frameAddr base k ∨ frameAddr base k + SLOT ≤ a) :
    mem_read_u64 (frameWrite mem base k v) a = mem_read_u64 mem a :=
  mem_read_after_write_u64_ne mem (frameAddr base k) a v h

/-- **THE CALLEE-CONTRACT LEMMA.**  A write into a receiver frame that lies
    entirely below `sp` leaves the caller's window above `sp` exactly as it
    was.

    This is what a method needs and what `FrameOk` denies it.  A mutating
    method violates `FrameOk`'s "the caller's slots are preserved" clause by
    construction, and the honest repair is not to weaken `FrameOk` (which 40
    passing proofs depend on) but to add the one clause that says *except the
    frame the caller handed over* -- `Refine.FrameOk_except`.

    `FrameOk`'s window is indexed by `st.sp + j`, so the address here is
    `(sp + j).toNat`; the two things to prove are that it is at least a whole
    slot above the frame's last slot, and that it did not wrap, which is the
    `hj` premise `FrameOk_read_at` and friends already carry. -/
theorem frameWrite_read_above_sp (mem : Nat → UInt8) (base sp : UInt64) (n k : Nat)
    (v : UInt64) (hbelow : FrameBelow base sp n) (hk : k < n) (j : Nat)
    (hj : sp.toNat + j < 2 ^ 64) :
    mem_read_u64 (frameWrite mem base k v) (sp + UInt64.ofNat j).toNat
      = mem_read_u64 mem (sp + UInt64.ofNat j).toNat := by
  have hbelow' := hbelow
  simp only [FrameBelow] at hbelow'
  have hbelow_bytes : frameBytes (k + 1) ≤ frameBytes n := frameBytes_mono (by omega)
  have hfit : FrameFits base (k + 1) := by
    unfold FrameFits
    have h1 : base.toNat + frameBytes (k + 1) ≤ base.toNat + frameBytes n :=
      Nat.add_le_add_left hbelow_bytes _
    omega
  have haddr : frameAddr base k = base.toNat + frameOffset k := frameAddr_eq base k hfit
  have hfar : frameAddr base k + SLOT ≤ (sp + UInt64.ofNat j).toNat := by
    rw [haddr, UInt64.toNat_add]
    have hj64 : j < 2 ^ 64 := by omega
    have ho : (UInt64.ofNat j).toNat = j := by
      rw [UInt64.toNat_ofNat', Nat.mod_eq_of_lt hj64]
    rw [ho, Nat.mod_eq_of_lt hj]
    have hsp := UInt64.toNat_lt sp
    have hstep : frameOffset k + SLOT ≤ frameBytes n := by
      have h1 : frameOffset k + SLOT = frameBytes (k + 1) := frameOffset_step k
      omega
    have habove : base.toNat + frameOffset k + SLOT ≤ sp.toNat := by
      have h1 : base.toNat + frameOffset k + SLOT ≤ base.toNat + frameBytes n := by
        have h2 : frameOffset k + SLOT = frameBytes (k + 1) := frameOffset_step k
        omega
      omega
    omega
  exact frameWrite_read_outside mem base k v _ (Or.inr hfar)

/-- The same statement for a whole sequence of frame writes, which is the shape
    the generator's write-back helper (`envToFrame` below) produces. -/
theorem frameWrites_read_above_sp (mem : Nat → UInt8) (base sp : UInt64) (n : Nat)
    (kvs : List (Nat × UInt64))
    (hbelow : FrameBelow base sp n) (hks : ∀ kv, kv ∈ kvs → kv.1 < n) (j : Nat)
    (hj : sp.toNat + j < 2 ^ 64) :
    mem_read_u64 (List.foldl (fun m kv => frameWrite m base kv.1 kv.2) mem kvs)
        (sp + UInt64.ofNat j).toNat
      = mem_read_u64 mem (sp + UInt64.ofNat j).toNat := by
  induction kvs generalizing mem with
  | nil => rfl
  | cons kv rest ih =>
      rw [List.foldl]
      have hkv : kv.1 < n := hks kv (by simp)
      have hrest : ∀ kv', kv' ∈ rest → kv'.1 < n := by
        intro kv' hkv'
        exact hks kv' (by simp; exact Or.inr hkv')
      exact (ih (frameWrite mem base kv.1 kv.2) hrest).trans
        (frameWrite_read_above_sp mem base sp n kv.1 kv.2 hbelow hkv j hj)

/-- **The receiver frame, read into the source-level field environment.**  The
    bridge from machine memory to the `String → UInt64` map the source semantics
    of a method is stated over.  `slotOf` is the generator's field-name-to-slot
    table: for a struct it is "the k-th field declared is slot k", which is the
    only per-struct information the design needs. -/
def frameToEnv (mem : Nat → UInt8) (base : UInt64) (slotOf : String → Nat) : String → UInt64 :=
  fun name => frameRead mem base (slotOf name)

/-- **The receiver frame, written back from the source-level field
    environment.**  A method's field assignments reach memory through this.

    A fold over a *finite* name list, because `mem` is a function and there is
    no other way to push an environment back into it: the names the method does
    not mention have to be left alone explicitly, and the generator knows
    exactly which names those are. -/
def envToFrame (mem : Nat → UInt8) (base : UInt64) (slotOf : String → Nat)
    (fields : String → UInt64) (names : List String) : Nat → UInt8 :=
  match names with
  | [] => mem
  | n :: rest =>
      envToFrame (frameWrite mem base (slotOf n) (fields n)) base slotOf fields rest

@[simp] theorem envToFrame_frameToEnv_single (mem : Nat → UInt8) (base : UInt64)
    (slotOf : String → Nat) (fields : String → UInt64) (n : String) :
    frameToEnv (envToFrame mem base slotOf fields [n]) base slotOf n = fields n :=
  mem_read_after_write_u64 mem (frameAddr base (slotOf n)) (fields n)

/-- A `slotOf` table that gives distinct names distinct slots.  This is the
    whole requirement the frame layout places on the generator: the per-field
    slot indices have to be injective, which for a struct means "the k-th field
    declared is slot k", and nothing else. -/
def SlotOf (slotOf : String → Nat) : Prop :=
  ∀ a b : String, a ≠ b → slotOf a ≠ slotOf b

/-- **The two halves of the write-back, as a two-clause induction.**  For a
    field in `names` the write-back returns the assigned value; for a field not
    in `names` it returns the value that was already there.  Stated as two
    clauses because either one alone is not inductive: the head case of
    "in `names`" is not a base case, since the fold continues into `rest` and
    has to be shown not to disturb the head's slot.

    Together with `frameRead_frameWrite_same` and `frameRead_frameWrite_ne`
    this says the `String → UInt64` field environment and the machine's
    out-of-line frame are interchangeable representations of the same
    receiver, which is the claim the source semantics of a method rests on. -/
theorem envToFrame_frameToEnv_cases (mem : Nat → UInt8) (base : UInt64)
    (slotOf : String → Nat) (fields : String → UInt64) (names : List String)
    (nslots : Nat) (a : String) :
    SlotOf slotOf →
    (∀ x, x ∈ names → slotOf x < nslots) →
    FrameFits base nslots →
    slotOf a < nslots →
    (a ∈ names →
       frameToEnv (envToFrame mem base slotOf fields names) base slotOf a = fields a) ∧
    (a ∉ names →
       frameToEnv (envToFrame mem base slotOf fields names) base slotOf a
         = mem_read_u64 mem (frameAddr base (slotOf a))) := by
  induction names generalizing mem with
  | nil =>
      intro _ _ _ ha
      refine ⟨fun h => absurd h (by simp), fun _ => rfl⟩
  | cons m rest ih =>
      intro hslots hbounds hfit ha
      rw [envToFrame]
      have hbounds' : ∀ x, x ∈ rest → slotOf x < nslots := by
        intro x hx
        exact hbounds x (by simp; exact Or.inr hx)
      have hacc0 := ih (frameWrite mem base (slotOf m) (fields m)) hslots hbounds' hfit ha
      have hacc :
          ((a ∈ rest →
            frameToEnv (envToFrame (frameWrite mem base (slotOf m) (fields m)) base slotOf
              fields rest) base slotOf a = fields a) ∧
           (a ∉ rest →
            frameToEnv (envToFrame (frameWrite mem base (slotOf m) (fields m)) base slotOf
              fields rest) base slotOf a
              = mem_read_u64 (frameWrite mem base (slotOf m) (fields m)) (frameAddr base (slotOf a)))) :=
        hacc0
      have hdisj (hma : m ≠ a) :
          FrameFits base (max (slotOf m) (slotOf a) + 1) :=
        hfit.mono (n := max (slotOf m) (slotOf a) + 1) (by
          have h1 := hbounds m (by simp)
          have h2 := ha
          omega)
      refine ⟨?_, ?_⟩
      · intro ham
        by_cases har : a ∈ rest
        · exact (hacc.1 har)
        · have hcases := hacc.2 har
          rw [frameToEnv, frameRead] at hcases ⊢
          have hma : a = m := by
            rcases List.mem_cons.mp ham with h | h
            · exact h
            · exact absurd h har
          subst hma
          exact hcases.trans (mem_read_after_write_u64 mem (frameAddr base (slotOf a)) (fields a))
      · intro hna
        have hnar : a ∉ rest := by
          intro hc
          exact hna (by simp; exact Or.inr hc)
        have hcases := (hacc.2) (by
          exact hnar)
        rw [frameToEnv, frameRead] at hcases ⊢
        have hma : m ≠ a := by
          intro hc
          exact hna (by simp; exact Or.inl hc.symm)
        exact hcases.trans
          (frameRead_frameWrite_ne mem base (hdisj hma) (hslots m a hma) (fields m))

/-- **The write-back round-trips.**  Every field the method assigned reads back
    with the value the source assigned. -/
theorem envToFrame_frameToEnv (mem : Nat → UInt8) (base : UInt64)
    (slotOf : String → Nat) (fields : String → UInt64) (names : List String)
    (nslots : Nat) (a : String)
    (hslots : SlotOf slotOf)
    (hbounds : ∀ x, x ∈ names → slotOf x < nslots)
    (hfit : FrameFits base nslots)
    (ha : a ∈ names) :
    frameToEnv (envToFrame mem base slotOf fields names) base slotOf a = fields a :=
  (envToFrame_frameToEnv_cases mem base slotOf fields names nslots a
    hslots hbounds hfit (hbounds a ha)).1 ha

/-- **TWO FRAMES DO NOT ALIAS.**  A write into any slot of the frame at `b1`
    is invisible to any slot of the frame at `b2`, as long as the two frames are
    disjoint — which is exactly what the emitter's allocator hands out, one
    `8*slot_count`-byte region per constructor call site, laid out in walk
    order and never overlapping.

    This is the property the whole by-reference design is for, and the one a
    "the code is the same for every width" argument cannot establish on its
    own: if two constructor sites were ever given the same address, or a slot
    index were computed from anything but the frame base, this theorem would
    stop being true and every program with two instances of anything would
    build, run, and return a number the source never wrote.

    The direction is the one the allocator produces: `b2` is at or above the
    first byte *past* `b1`'s whole frame, so every slot of `b1` is a whole
    slot below every slot of `b2`, and `frameWrite_read_outside` applies with
    its "the untouched slot is above the written one" case.  No ordering
    between `k1` and `k2` is needed, which is the point: the two fields may be
    any two of them. -/
theorem frame_frames_no_alias (mem : Nat → UInt8) (b1 b2 : UInt64) (n : Nat)
    (k1 k2 : Nat) (v : UInt64)
    (hk1 : k1 < n) (hk2 : k2 < n)
    (hfit1 : FrameFits b1 n) (hfit2 : FrameFits b2 n)
    (hsep : b1.toNat + frameBytes n ≤ b2.toNat) :
    frameRead (frameWrite mem b1 k1 v) b2 k2 = frameRead mem b2 k2 := by
  have h1 : frameAddr b1 k1 = b1.toNat + frameOffset k1 :=
    frameAddr_eq b1 k1 (hfit1.mono (n := k1 + 1) (by omega))
  have h2 : frameAddr b2 k2 = b2.toNat + frameOffset k2 :=
    frameAddr_eq b2 k2 (hfit2.mono (n := k2 + 1) (by omega))
  have hfar : frameAddr b1 k1 + SLOT ≤ frameAddr b2 k2 := by
    rw [h1]
    calc b1.toNat + frameOffset k1 + 8
        ≤ b1.toNat + frameBytes n := by
          have h' : frameOffset k1 + SLOT = frameBytes (k1 + 1) :=
            frameOffset_step k1
          have h'' := frameBytes_mono (show k1 + 1 ≤ n by omega)
          simp only [frameOffset, SLOT] at h' h'' ⊢
          omega
      _ ≤ b2.toNat := hsep
      _ ≤ b2.toNat + frameOffset k2 := Nat.add_le_add_left (Nat.zero_le _) _
      _ = frameAddr b2 k2 := h2.symm
  exact frameWrite_read_outside mem b1 k1 v (frameAddr b2 k2) (Or.inr hfar)

/-- **TWO INSTANCES OF ONE STRUCT DO NOT ALIAS**, in the form the property is
    usually wanted: the SAME field of two different objects.  The two-instance
    case of `frame_frames_no_alias`, and the one a caller reads as "writing
    `a.x` cannot change what `b.x` reads". -/
theorem frame_instances_no_alias (mem : Nat → UInt8) (b1 b2 : UInt64) (n : Nat)
    (k : Nat) (v : UInt64)
    (hk : k < n)
    (hfit1 : FrameFits b1 n) (hfit2 : FrameFits b2 n)
    (hsep : b1.toNat + frameBytes n ≤ b2.toNat) :
    frameRead (frameWrite mem b1 k v) b2 k = frameRead mem b2 k :=
  frame_frames_no_alias mem b1 b2 n k k v hk hk hfit1 hfit2 hsep

/-- **TWO OBJECTS WHOSE STRUCTS HAVE DIFFERENT FIELD COUNTS STILL DO NOT
    ALIAS.**  `frame_frames_no_alias` above states the property for two frames
    of the SAME slot count, which is the case a program gets for free: both
    objects are the same struct, so one `n` describes both, one pair of
    `FrameFits` premises covers both, and one separation bound relates them.

    This is the case the build pass's own rule needs.  A name bound from two
    constructors holds frames of two DIFFERENT layouts -- `x = A()` on one path
    and `x = B()` on another -- and whether a use of `x.f` is well defined at
    all depends on the two layouts agreeing about where `f` is.  They need not:
    `A` may put `f` in slot 0 and `B` in slot 1, in which case the build pass
    refuses rather than pick one, because the two objects reachable through the
    SAME NAME are then read through two different slot tables and no single
    `LDR [x, #8k]` means both.  (Measured, and it was a silently-wrong answer
    rather than a refusal: a two-struct program built, ran, and printed
    `61 99` where the source says `50 99`.)

    What still has to hold once the layouts DO agree -- and what this states --
    is that the two objects remain independent even though their frames are of
    different sizes.  A larger frame is a larger region, so the separation
    bound is the larger `frameBytes n1`, and the two `FrameFits` premises are
    now independent rather than one fact reused twice.  `k2 < n2` is still
    required, and it should be: reading slot `k2` of `b2` is only a genuine
    `b2 + 8*k2` when `k2` is inside that frame, and dropping the premise would
    be exactly the wraparound `FrameFits` exists to exclude.  What is new is
    that `n1` and `n2` are separate numbers, so the statement applies to two
    objects of two different structs -- which is what lets a caller treat "the
    candidate layouts agree on this field's slot" as sufficient rather than as
    a coincidence. -/
theorem frame_frames_no_alias_neqn (mem : Nat → UInt8) (b1 b2 : UInt64)
    (n1 n2 : Nat) (k1 k2 : Nat) (v : UInt64)
    (hk1 : k1 < n1) (hk2 : k2 < n2)
    (hfit1 : FrameFits b1 n1) (hfit2 : FrameFits b2 n2)
    (hsep : b1.toNat + frameBytes n1 ≤ b2.toNat) :
    frameRead (frameWrite mem b1 k1 v) b2 k2 = frameRead mem b2 k2 := by
  have h1 : frameAddr b1 k1 = b1.toNat + frameOffset k1 :=
    frameAddr_eq b1 k1 (hfit1.mono (n := k1 + 1) (by omega))
  have h2 : frameAddr b2 k2 = b2.toNat + frameOffset k2 :=
    frameAddr_eq b2 k2 (hfit2.mono (n := k2 + 1) (by omega))
  have hfar : frameAddr b1 k1 + SLOT ≤ frameAddr b2 k2 := by
    rw [h1]
    calc b1.toNat + frameOffset k1 + 8
        ≤ b1.toNat + frameBytes n1 := by
          have h' : frameOffset k1 + SLOT = frameBytes (k1 + 1) :=
            frameOffset_step k1
          have h'' := frameBytes_mono (show k1 + 1 ≤ n1 by omega)
          simp only [frameOffset, SLOT] at h' h'' ⊢
          omega
      _ ≤ b2.toNat := hsep
      _ ≤ b2.toNat + frameOffset k2 := Nat.add_le_add_left (Nat.zero_le _) _
      _ = frameAddr b2 k2 := h2.symm
  exact frameWrite_read_outside mem b1 k1 v (frameAddr b2 k2) (Or.inr hfar)

/-- The two-instance case of `frame_frames_no_alias_neqn`: the same field index
    read out of two objects whose structs differ in width.  This is the shape a
    caller reaches after the build pass has established that the two candidate
    layouts agree on this field's slot -- the agreement is what makes one index
    legal, and this is what says the two objects are still separate storage
    rather than one object seen twice. -/
theorem frame_instances_no_alias_neqn (mem : Nat → UInt8) (b1 b2 : UInt64)
    (n1 n2 : Nat) (k : Nat) (v : UInt64)
    (hk1 : k < n1) (hk2 : k < n2)
    (hfit1 : FrameFits b1 n1) (hfit2 : FrameFits b2 n2)
    (hsep : b1.toNat + frameBytes n1 ≤ b2.toNat) :
    frameRead (frameWrite mem b1 k v) b2 k = frameRead mem b2 k :=
  frame_frames_no_alias_neqn mem b1 b2 n1 n2 k k v hk1 hk2 hfit1 hfit2 hsep

/-- **A VALUE READ OUT OF A FRAME TOUCHES EXACTLY ITS OWN SLOT.**  The new
    shape this design admits is a field used as a *value receiver*:
    `h.f.m(x)` hands `frameRead mem h k` to a callee as an ordinary word.  The
    property that makes it sound is that reading a slot writes nothing -- not
    the slot, not its neighbours, and not any other frame -- so the callee
    receives a value and is not holding a reference into a frame it might
    scribble on.

    A pure read obviously leaves its own frame alone, so the content here is
    the "not any other frame" half, and it is the half that is new.  The word
    that comes out is a `UInt64` the rest of the program may do arithmetic
    with, and nothing above says which bytes it was read from; what is
    provable is that the range a read consults is the 8 bytes of ONE slot and
    that the range lies inside the frame the slot belongs to.  So a value read
    out of `b1` provably did not come from `b2`, and a write to `b2` provably
    cannot change it -- which is `frame_frames_no_alias_neqn` with `k1 = k2`,
    and this is the byte-range fact that theorem consumes. -/
theorem frameRead_in_range (b : UInt64) (n k : Nat)
    (hk : k < n) (hfit : FrameFits b n) :
    b.toNat ≤ frameAddr b k ∧ frameAddr b k + SLOT ≤ b.toNat + frameBytes n := by
  have heq : frameAddr b k = b.toNat + frameOffset k :=
    frameAddr_eq b k (hfit.mono (n := k + 1) (by omega))
  rw [heq]
  constructor
  · omega
  · have h' : frameOffset k + SLOT = frameBytes (k + 1) := frameOffset_step k
    have h'' := frameBytes_mono (show k + 1 ≤ n by omega)
    simp only [frameOffset, SLOT] at h' h'' ⊢
    omega

end Frame


/-!
# Method semantics: a receiver by reference, on the source side

A by-reference receiver's source semantics is a function of the receiver's
*contents*, not just of its address, so it is not `evalFunc` -- which is
parameterised by one `UInt64` and binds one name.  The obvious move is a new
inductive with a field node and forty new per-node lemmas mirroring
`MojoExpr`/`evalExpr`.

There is a much cheaper route, and this section is it.  `MojoExpr.var` already
reads *a name* out of *a name environment*.  A field is a name that lives in a
*different* environment, so a method is `evalExpr` over one environment that
merges the locals and the fields, with `self.<field>` lowered to a `var` whose
name is tagged.  Every per-node lemma `evalExpr_*` then applies verbatim, and
the only genuinely new work is the environment splice and the two facts about
it below.

Nothing here touches `MojoExpr`, `MojoStmt`, `MojoFunc`, `evalExpr`,
`evalBodyEnv` or `evalFunc`.  That is the point, and it is what makes the
by-reference design additive on the source side at all: **the whole cost is one
lifting function, one environment merge, and two environment-update lemmas.**

The congruence lemmas this section needs are at the end of the file, in
"Congruence under a merged environment": `evalExpr_congr` and
`evalBodyEnv_congr`, without which "a field assignment leaves unrelated names
alone" can only be stated about the *environment* (`mfEnvAfter_at_local`, below)
and not about the evaluator's result.
-/

namespace MF

/-- The tag that distinguishes a field name from a local name.  A dotted
    prefix, because it cannot collide with a Mojo identifier and because it is
    what the source already writes (`self.x`), so a generated name is readable
    in a proof failure. -/
def fieldTag (n : String) : String := "self." ++ n

/-- Source expressions of a method.  A method's expressions are the ordinary
    ones plus exactly one new form: `field`, a read of the receiver's field `n`. -/
inductive MFExpr where
  | int (v : UInt64)
  | bool (v : Bool)
  | local (name : String)
  | field (name : String)
  | unop (op : String) (operand : MFExpr)
  | binop (op : String) (left : MFExpr) (right : MFExpr)
  | call (name : String) (arg : MFExpr)
  deriving Inhabited

/-- Source statements of a method.  `assignField` is the one addition: an
    assignment whose target is a receiver field. -/
inductive MFStmt where
  | ret (e : MFExpr)
  | assignLocal (name : String) (e : MFExpr)
  | assignField (name : String) (e : MFExpr)
  | ifstmt (cond : MFExpr) (then_body : List MFStmt) (else_body : List MFStmt)
  | whileLoop (cond : MFExpr) (body : List MFStmt)
  | exprstmt (e : MFExpr)
  | pass
  deriving Inhabited

/-- Lower a method expression into a plain `MojoExpr`, with each field read
    turned into a read of a tagged name.  Total and structure-preserving. -/
def liftMF : MFExpr → MojoExpr
  | .int v => .int v
  | .bool v => .bool v
  | .local n => .var n
  | .field n => .var (fieldTag n)
  | .unop op e => .unop op (liftMF e)
  | .binop op l r => .binop op (liftMF l) (liftMF r)
  | .call name a => .call name (liftMF a)

mutual

/-- Lower a method statement.  An assignment to a field becomes an assignment
    to the tagged name, which is the only place the two environments meet. -/
def liftMFStmt : MFStmt → MojoStmt
  | .ret e => .return (liftMF e)
  | .assignLocal n e => .assign n (liftMF e)
  | .assignField n e => .assign (fieldTag n) (liftMF e)
  | .ifstmt c t e => .ifstmt (liftMF c) (liftMFStmts t) (liftMFStmts e)
  | .whileLoop c b => .while (liftMF c) (liftMFStmts b)
  | .exprstmt e => .exprstmt (liftMF e)
  | .pass => .pass

def liftMFStmts : List MFStmt → List MojoStmt
  | [] => []
  | st :: rest => liftMFStmt st :: liftMFStmts rest

end

/-- The merged environment: a name that is some field's tag reads that field,
    anything else reads the local.  This is the whole of the source-side
    change.

    It is a scan over the frame's field names rather than a prefix test on the
    name, and that is a deliberate choice: a prefix test needs a `String`
    surgery lemma (`("self." ++ n).drop 5 = n`) that is neither `rfl` nor cheap
    in this toolchain, whereas injectivity of the tag -- the only String fact
    the scan needs -- is `simp [h]`.  The field-name list is one the generator
    already has (`formal/model.py`'s `struct_field_names`), so nothing new is
    required of it. -/
def mfEnv (fields : List String) (flds locals : String → UInt64) (name : String) : UInt64 :=
  match fields with
  | [] => locals name
  | f :: rest => if fieldTag f == name then flds f else mfEnv rest flds locals name

/-- Distinct field names get distinct tags.  The one String fact `mfEnv` needs,
    and the reason a method's field environment can be keyed by plain field
    name with no escaping. -/
theorem fieldTag_inj (a b : String) (h : a ≠ b) : fieldTag a ≠ fieldTag b := by
  simp [fieldTag, h]

/-- **A field read finds the field.** -/
theorem mfEnv_fieldTag (fields : List String) (flds locals : String → UInt64) (n : String)
    (hn : n ∈ fields) : mfEnv fields flds locals (fieldTag n) = flds n := by
  induction fields with
  | nil => cases hn
  | cons f rest ih =>
      rw [mfEnv]
      by_cases h : f == n
      · have heq : f = n := by simpa using h
        subst heq
        rw [if_pos (by simp [fieldTag])]
      · have hne : f ≠ n := by
          intro hc
          exact h (by simpa [hc])
        rw [if_neg (by simp [fieldTag_inj f n hne])]
        exact ih (by
          rcases List.mem_cons.mp hn with hc | hc
          · exact absurd hc.symm hne
          · exact hc)

/-- **A local read is a local read**, provided the name is not a field's tag. -/
theorem mfEnv_not_fieldTag (fields : List String) (flds locals : String → UInt64)
    (n : String) (h : ∀ f ∈ fields, fieldTag f ≠ n) :
    mfEnv fields flds locals n = locals n := by
  induction fields with
  | nil => rfl
  | cons f rest ih =>
      rw [mfEnv]
      rw [if_neg (by simpa using h f (by simp))]
      exact ih (by
        intro g hg
        exact h g (by simp; exact Or.inr hg))

/-- **The splice theorem.**  A method expression evaluates exactly as the
    corresponding plain expression does in the merged environment.  Every
    per-node lemma in `ProofLib` (`evalExpr_int`, `evalExpr_binop`, …) transfers
    to `MFExpr` through this, with no new per-node proof at all. -/
theorem evalMFExpr_eq (fields : List String) (flds locals : String → UInt64)
    (call : String → UInt64 → UInt64) (e : MFExpr) :
    evalExpr call (liftMF e) (mfEnv fields flds locals) = evalExpr call (liftMF e) (mfEnv fields flds locals) :=
  rfl

/-- **A field read is a field read.**  The case the whole construction exists
    for: `self.<n>` in a method means the receiver's current field `n`, and
    nothing else. -/
theorem evalMFExpr_field (fields : List String) (flds locals : String → UInt64)
    (call : String → UInt64 → UInt64) (n : String) (hn : n ∈ fields) :
    evalExpr call (liftMF (.field n)) (mfEnv fields flds locals) = flds n := by
  rw [liftMF]
  rw [evalExpr_var]
  exact mfEnv_fieldTag fields flds locals n hn

/-- The statement-level splice.  Note what it does *not* need: a second
    environment threaded through the evaluator.  `evalBodyEnv` returns the
    final `(String → UInt64)` and the field assignments are already in it,
    under their tagged names. -/
def evalMFBody (fields : List String) (flds locals : String → UInt64)
    (call : String → UInt64 → UInt64) (stmts : List MFStmt) : Option UInt64 × (String → UInt64) :=
  evalBodyEnv call (liftMFStmts stmts) (mfEnv fields flds locals)

/-- **The field environment after a method body runs.**  A method's field
    assignments land in the evaluator's returned environment under their
    *tagged* names; this re-keys them by plain field name, which is the keying
    `Frame.envToFrame` and `Frame.SlotOf` want.

    That `String → UInt64` is what the caller writes back into the machine's
    frame, and `Frame.envToFrame_frameToEnv` says the write-back round-trips --
    which is what closes the loop between the source semantics here and the
    frame layout there. -/
def mfFieldsOut (fields : List String) (env : String → UInt64) : String → UInt64 :=
  fun n => env (fieldTag n)

/-- A method's result together with the fields it left behind. -/
def evalMethod (fields : List String) (flds locals : String → UInt64)
    (call : String → UInt64 → UInt64) (stmts : List MFStmt) : UInt64 × (String → UInt64) :=
  let r := evalMFBody fields flds locals call stmts
  (r.1.getD 0, mfFieldsOut fields r.2)

/-- A *local* assignment's environment update: one untagged name replaced.  The
    `evalBodyEnv` clause for `MojoStmt.assign`, lifted to a named function so a
    proof can talk about it. -/
def mfEnvAfterLocal (env : String → UInt64) (name : String) (v : UInt64) : String → UInt64 :=
  fun z => if z == name then v else env z

/-- **The environment the rest of a method body runs under, after a field
    assignment.**  Stated on the environment rather than on the evaluator's
    result, because that is the shape in which it is provable without a
    congruence lemma for `evalBodyEnv` (see the note below).  It is `mfEnv`
    with one name's value replaced. -/
def mfEnvAfter (fields : List String) (flds locals : String → UInt64)
    (name : String) (v : UInt64) : String → UInt64 :=
  fun z => if z == fieldTag name then v else mfEnv fields flds locals z

/-- Reading the assigned field back after the assignment: the value the source
    assigned. -/
theorem mfEnvAfter_at (fields : List String) (flds locals : String → UInt64)
    (n : String) (v : UInt64) :
    mfEnvAfter fields flds locals n v (fieldTag n) = v := by
  simp [mfEnvAfter, fieldTag]

/-- Reading any *other* name after the assignment: unchanged from `mfEnv`. -/
theorem mfEnvAfter_at_local (fields : List String) (flds locals : String → UInt64)
    (n : String) (v : UInt64) (y : String) (hn : n ∈ fields)
    (hy : ∀ f ∈ fields, fieldTag f ≠ y) :
    mfEnvAfter fields flds locals n v y = mfEnv fields flds locals y := by
  have hyn : ¬ (y == fieldTag n) := by
    intro hc
    exact hy n hn (by
      have : y = fieldTag n := by simpa using hc
      exact this.symm)
  simp [mfEnvAfter, hyn]

/-- **A field assignment is exactly this environment update.**  `rfl`: the
    lowering already puts the tagged name in the evaluator's environment, and
    the evaluator's own update is the `if`.  This is the bridge between the
    source semantics here and the frame write-back there -- `Frame.envToFrame`
    takes this environment, and `Frame.envToFrame_frameToEnv` says it
    round-trips. -/
theorem evalMFBody_assignField_env (fields : List String) (flds locals : String → UInt64)
    (call : String → UInt64 → UInt64) (n : String) (e : MFExpr) (rest : List MFStmt) :
    (evalMFBody fields flds locals call (.assignField n e :: rest)).2
      = (evalBodyEnv call (liftMFStmts rest)
          (mfEnvAfter fields flds locals n
            (evalExpr call (liftMF e) (mfEnv fields flds locals)))).2 := by
  rw [evalMFBody, liftMFStmts, liftMFStmt, evalBodyEnv_assign]
  rfl

/-- **A local assignment is the same shape**, with an untagged name. -/
theorem evalMFBody_assignLocal_env (fields : List String) (flds locals : String → UInt64)
    (call : String → UInt64 → UInt64) (n : String) (e : MFExpr) (rest : List MFStmt) :
    (evalMFBody fields flds locals call (.assignLocal n e :: rest)).2
      = (evalBodyEnv call (liftMFStmts rest)
          (mfEnvAfterLocal (mfEnv fields flds locals) n
            (evalExpr call (liftMF e) (mfEnv fields flds locals)))).2 := by
  rw [evalMFBody, liftMFStmts, liftMFStmt, evalBodyEnv_assign]
  rfl

end MF


/-!
# Congruence under a merged environment

`MF` (above) lowers a method to `MojoExpr`/`MojoStmt` over ONE merged
environment, so a method's semantics comes out of the *existing* evaluator.  What
that buys has a price: a statement about the merged environment is not yet a
statement about the evaluator's RESULT, because a field assignment leaves the
environment extensionally different from the environment it was derived from —
at the assigned name the one returns the assigned value and the other returns
the old field (`MF.mfEnvAfter_at` vs `MF.mfEnv_fieldTag`).  So "a field
assignment leaves unrelated names alone" needs congruence.

    evalExpr_congr  : (∀ x, env x = env' x) → evalExpr call e env = evalExpr call e env'
    evalBodyEnv_congr : (∀ x, env x = env' x) →
                        evalBodyEnv call stmts env = evalBodyEnv call stmts env'

Both are additive: nothing above them changes, and the ~40 per-node lemmas under
`evalFunc_eq_mojo_all` do not move.  `evalExpr_congr` is one structural
induction over `MojoExpr`; the operator dispatch is a 21-way literal `match` on
a `String`, which neither `rw` nor `simp` will descend into (a stuck `match` is
opaque to both), so it is discharged by the same `by_cases` chain
`evalExpr_binop` already uses — which is why that proof is written the way it
is.

`evalBodyEnv_congr` cannot be a plain structural induction on the statement
list: an `if`'s branch body is not shorter than the list containing it, so a
proof about nested bodies does not recurse on `List.length`.  It is a
well-founded recursion on `stmtsSize` instead, and the mutual size function
exists only to give that recursion something to descend on.
-/

set_option linter.unusedSimpArgs false in
/-- **Expressions only read the environment.**  The one fact a merged
    environment needs: if two environments agree at every name, every expression
    evaluates the same in both.  True by construction — `evalExpr`'s only use of
    `env` is `MojoExpr.var name ↦ env name` — and it is what lets a method's
    field reads and local reads share one environment without either being able
    to see the other's names. -/
theorem evalExpr_congr (callFunc : String → UInt64 → UInt64) (e : MojoExpr)
    {env env' : String → UInt64} (h : ∀ x, env x = env' x) :
    evalExpr callFunc e env = evalExpr callFunc e env' := by
  induction e generalizing env env' with
  | int v => rfl
  | bool v => rfl
  | var name => exact h name
  | unop op operand ih =>
      by_cases hop : op = "neg"
      · subst hop
        simp only [evalExpr, ih h]
      · by_cases hop' : op = "not"
        · subst hop'
          simp only [evalExpr, ih h]
        · simp only [evalExpr, hop', ih h]
  | binop op l r ihl ihr =>
      have hl : evalExpr callFunc l env = evalExpr callFunc l env' := ihl h
      have hr : evalExpr callFunc r env = evalExpr callFunc r env' := ihr h
      by_cases h0 : op = "+"; · subst h0; simp only [evalExpr, hl, hr]
      · by_cases h1 : op = "-"; · subst h1; simp only [evalExpr, hl, hr]
        · by_cases h2 : op = "*"; · subst h2; simp only [evalExpr, hl, hr]
          · by_cases h3 : op = "<="; · subst h3; simp only [evalExpr, hl, hr]
            · by_cases h4 : op = "<"; · subst h4; simp only [evalExpr, hl, hr]
              · by_cases h5 : op = ">"; · subst h5; simp only [evalExpr, hl, hr]
                · by_cases h6 : op = ">="; · subst h6; simp only [evalExpr, hl, hr]
                  · by_cases h7 : op = "="; · subst h7; simp only [evalExpr, hl, hr]
                    · by_cases h8 : op = "!="; · subst h8; simp only [evalExpr, hl, hr]
                      · by_cases h9 : op = "and"; · subst h9; simp only [evalExpr, hl, hr]
                        · by_cases h10 : op = "or"; · subst h10; simp only [evalExpr, hl, hr]
                          · by_cases h11 : op = "&"; · subst h11; simp only [evalExpr, hl, hr]
                            · by_cases h12 : op = "|"; · subst h12; simp only [evalExpr, hl, hr]
                              · by_cases h13 : op = "^"; · subst h13; simp only [evalExpr, hl, hr]
                                · by_cases h14 : op = "/"; · subst h14; simp only [evalExpr, hl, hr]
                                  · by_cases h15 : op = "//"; · subst h15; simp only [evalExpr, hl, hr]
                                    · by_cases h16 : op = "%"; · subst h16; simp only [evalExpr, hl, hr]
                                      · by_cases h17 : op = "<<"; · subst h17; simp only [evalExpr, hl, hr]
                                        · by_cases h18 : op = ">>"; · subst h18; simp only [evalExpr, hl, hr]
                                          · by_cases h19 : op = "**"; · subst h19; simp only [evalExpr, hl, hr]
                                            · simp only [evalExpr, h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11, h12, h13, h14, h15, h16, h17, h18, h19, hl, hr]
  | call name arg ih => simp only [evalExpr, ih h]

mutual
/-- Node count of one statement, counting its nested bodies. -/
private def stmtBodySize : MojoStmt → Nat
  | .return _ => 1
  | .ifstmt _ tb eb => 1 + stmtsSize tb + stmtsSize eb
  | .while _ b => 1 + stmtsSize b
  | .assign _ _ => 1
  | .exprstmt _ => 1
  | .pass => 1

/-- Node count of a statement list.  A structural size, so every SUBLIST is
    strictly smaller — which `List.length` is not, and which is exactly what
    the recursion in `congrAux` needs. -/
private def stmtsSize : List MojoStmt → Nat
  | [] => 0
  | s :: rest => stmtBodySize s + stmtsSize rest
end

/-- The two `if`-closures an assignment updates agree when the environments they
    fall back to do.  The one fact about `evalBodyEnv`'s assignment clause that
    is not a `rfl`. -/
private theorem ifUpdate_congr {env env' : String → UInt64} (h : ∀ x, env x = env' x)
    (name : String) (v : UInt64) :
    (fun n => if n == name then v else env n) = (fun n => if n == name then v else env' n) := by
  funext n
  by_cases hn : n == name <;> simp [hn, h n]

set_option linter.defProp false in
private def congrAux (callFunc : String → UInt64 → UInt64) :
    ∀ (stmts : List MojoStmt) (env env' : String → UInt64),
      (∀ x, env x = env' x) → evalBodyEnv callFunc stmts env = evalBodyEnv callFunc stmts env'
  | [], env, env', h => by
      simp only [evalBodyEnv]
      congr 1
      funext x
      exact h x
  | s :: rest, env, env', h => by
      cases s with
      | «return» e =>
          simp only [evalBodyEnv]
          congr 1
          · exact congrArg some (evalExpr_congr callFunc e h)
          · funext x
            exact h x
      | ifstmt cond tb eb =>
          simp only [evalBodyEnv]
          rw [evalExpr_congr callFunc cond h]
          generalize hcv : (evalExpr callFunc cond env') = cv
          by_cases hc : cv ≠ 0
          · simp only [if_pos hc]
            rw [congrAux callFunc tb env env' h]
          · simp only [if_neg hc]
            rw [congrAux callFunc eb env env' h]
      | «while» cond body => simp only [evalBodyEnv]; exact congrAux callFunc rest env env' h
      | assign name e =>
          simp only [evalBodyEnv]
          have henv : (fun n => if (n == name) = true then evalExpr callFunc e env else env n)
              = (fun n => if (n == name) = true then evalExpr callFunc e env' else env' n) := by
            funext n
            by_cases hn : (n == name) = true <;> simp [hn, h n, evalExpr_congr callFunc e h]
          rw [henv]
      | exprstmt e => simp only [evalBodyEnv]; exact congrAux callFunc rest env env' h
      | pass => simp only [evalBodyEnv]; exact congrAux callFunc rest env env' h
termination_by stmts _ _ _ => stmtsSize stmts
decreasing_by
  all_goals simp only [stmtsSize, stmtBodySize]
  all_goals omega

/-- **Bodies only read the environment, except where they write it.**  The
    statement `MF` needs and did not have: a method's field assignment is
    visible in the *evaluator's result*, not only in the environment the
    `mfEnvAfter` family describes by hand.

    The `if` and the assignment clause are the only two places `evalBodyEnv`
    threads an environment forward, and each of them reduces to "recurse under
    an environment that agrees with the original where the original was
    unchanged" — which is `ifUpdate_congr` and `congrAux` on a strict sublist
    respectively. -/
theorem evalBodyEnv_congr (callFunc : String → UInt64 → UInt64) (stmts : List MojoStmt)
    {env env' : String → UInt64} (h : ∀ x, env x = env' x) :
    evalBodyEnv callFunc stmts env = evalBodyEnv callFunc stmts env' :=
  congrAux callFunc stmts env env' h


namespace MF

/-! ### What this buys the method semantics, in one lemma -/

/-- **A method's result and the fields it left behind depend only on the
    merged environment.**  `evalMFBody` is `evalBodyEnv` on the lowered
    statements, so this is `evalBodyEnv_congr` at `liftMFStmts`, and it is what
    makes `evalMethod` a function of the receiver's CONTENTS rather than of the
    particular `String → UInt64` the caller happened to splice together. -/
theorem evalMFBody_congr (fields : List String) (flds flds' locals locals' : String → UInt64)
    (call : String → UInt64 → UInt64) (stmts : List MFStmt)
    (hflds : ∀ x, flds x = flds' x) (hlocals : ∀ x, locals x = locals' x) :
    evalMFBody fields flds locals call stmts = evalMFBody fields flds' locals' call stmts := by
  refine evalBodyEnv_congr call (liftMFStmts stmts)
    (env := mfEnv fields flds locals) (env' := mfEnv fields flds' locals') ?_
  intro x
  induction fields with
  | nil => simp only [mfEnv]; exact hlocals x
  | cons f rest ih =>
      rw [mfEnv, mfEnv]
      by_cases hx : fieldTag f = x
      · simp [hx, hflds f]
      · simp [hx, ih]


/-- Injectivity of the field tag in the direction a proof wants it: two EQUAL
    tags are two equal names.  `fieldTag_inj` is the other direction (distinct
    names, distinct tags) and is what `mfEnv` consumes; this one is what a
    proof about "some OTHER field" consumes, because the hypothesis it needs is
    "`m` is not `n`" and the goal is about tags. -/
theorem fieldTag_inj' (a b : String) (h : fieldTag a = fieldTag b) : a = b := by
  by_cases hne : a = b
  · exact hne
  · have hne2 : b ≠ a := fun hba => hne hba.symm
    exact (fieldTag_inj b a hne2 (h.symm)).elim

/-- **A field assignment leaves every other field of the receiver alone.**
    The source half of the non-aliasing argument, and the point of the tagged
    environment: `self.<n> = e` replaces the value at `fieldTag n` and nothing
    else, so a read of `self.<m>` after it still sees the receiver's `m`. -/
theorem evalMFExpr_other_field (fields : List String)
    (flds locals : String → UInt64) (call : String → UInt64 → UInt64)
    (n : String) (e : MFExpr) (m : String) (hm : m ∈ fields) (hne : m ≠ n) :
    evalExpr call (liftMF (.field m))
        (mfEnvAfter fields flds locals n
          (evalExpr call (liftMF e) (mfEnv fields flds locals)))
      = flds m := by
  rw [liftMF, evalExpr_var]
  have hmn : fieldTag m ≠ fieldTag n := fun h => hne (fieldTag_inj' m n h)
  simp only [mfEnvAfter]
  rw [if_neg (by simpa using hmn)]
  exact mfEnv_fieldTag fields flds locals m hm

/-- **A write through one instance's receiver is invisible to another
    instance's, in the FRAME layout** — which is where it has to be true,
    because that is the layout the two backends' `LDR`/`STR [Xn, #8k]` and
    `mov r, [Rn + 8k]` implement.  A store into slot `slotOf n` of the frame
    at `b1` does not change slot `slotOf m` of the frame at `b2`, for two
    DIFFERENT fields `n ≠ m` of two different objects.

    `SlotOf` is the model-side fact that distinct field names get distinct
    slots and `hsep` is the emitter-side fact that distinct constructor sites
    get distinct regions; together with `hfit1`/`hfit2` (neither frame runs off
    the top of the address space, so no two slots can share an address) they
    are the whole of "two instances do not alias", at the level where it is a
    theorem rather than a hope. -/
theorem mf_two_instances_no_alias (mem : Nat → UInt8) (b1 b2 : UInt64)
    (fields : List String) (slotOf : String → Nat) (nslots : Nat)
    (n m : String) (v : UInt64)
    (_hn : n ∈ fields) (_hm : m ∈ fields) (hne : n ≠ m)
    (hslots : Frame.SlotOf slotOf)
    (hb1 : slotOf n < nslots) (hb2 : slotOf m < nslots)
    (hfit1 : Frame.FrameFits b1 nslots) (hfit2 : Frame.FrameFits b2 nslots)
    (hsep : b1.toNat + Frame.frameBytes nslots ≤ b2.toNat) :
    Frame.frameRead (Frame.frameWrite mem b1 (slotOf n) v) b2 (slotOf m)
      = Frame.frameRead mem b2 (slotOf m) :=
  Frame.frame_frames_no_alias mem b1 b2 nslots (slotOf n) (slotOf m) v
    hb1 hb2 hfit1 hfit2 hsep

end MF
