import ProofLib

set_option autoImplicit false

/-!
# x86.lean — the x86-64 machine model

`ProofLib.lean` holds what both backends share: the register files, the memory
primitives, the byte readers, and the source-language AST.  This module holds
the x86-64 half — the decoder, the semantics of every instruction form the
backend emits, and the two runners that step them.

It is a separate module because it is a separate claim.  The arm64 model in
ProofLib is the one the existing proof suite is built on; this one is new, and
keeping it in its own file means its lemmas can be reasoned about (and
replaced) without touching anything an arm64 proof depends on.

`autoImplicit` is OFF here.  A model this size has exactly one kind of
typo-that-compiles: a lemma mentioning a definition that does not exist yet,
which autoImplicit quietly turns into a universally quantified variable, so
the theorem is vacuously true and the run tests it was supposed to justify go
missing without a word.  That is not hypothetical: it is how the first version
of the exit runner got lost in a refactor, and `set_option autoImplicit false`
is what turns that back into an error.

# What is modelled

Every instruction form `formal/x86_64.py` can encode, and nothing else: the
model returns `none` for anything it does not decode, which the run tests'
termination obligations are there to notice.  Two approximations are stated
where they are paid rather than hidden: `x86_cond` fills the parity
conditions in from ZF (there is no PF field, and nothing this backend emits
sets one a program can observe), and the divisors return `none` on zero rather
than modelling the #DE fault.

# How it is checked

Against the hardware, not against itself.  `formal/x86_64_model_test.py`
builds every `formal/examples/*.mojo` for x86-64, runs the binary, runs the
same bytes through this model, and compares the value left in RAX.  All 43
examples agree, which is what pins the parts that are easy to get subtly
wrong: the REX prefix shifting every field one byte along, the SIB and
displacement that a memory operand carries, little-endian access, the
`call`/`ret` stack discipline (the recursive examples), and the 128-bit
group-3 results (the dividing ones).
-/

set_option maxRecDepth 100000

/-! ## The x86-64 machine model

Everything above `x86_get_reg` in this section is the DECODER and its
helpers; `x86_step` is the model proper.  The shape is the one x86 actually
has — a REX prefix shifts every field one byte along, memory operands carry
SIB + displacement, and condition codes are the opcode nibble — because the
previous version of this model was a flat `match` on the first byte that only
handled a handful of REX.W register-to-register forms.  It decoded far enough
to typecheck and no further: the first instruction of every real image
(`push rbp`) stopped it, so no x86-64 program could be executed in the model
at all.

What it costs to be exact is stated where it is paid: `x86_cond` approximates
the parity conditions (there is no PF field, and nothing this backend emits
sets one a program can observe), and `x86_div128`/`x86_idiv128` return `none`
on a zero divisor rather than modelling the #DE fault.

The model is checked against the hardware, not against itself:
`formal/x86_64_model_test.py` builds every formal/examples/*.mojo for x86-64,
runs the binary, runs the same bytes through this model, and compares.  All 43
examples agree, including the recursive ones (which is what pins the
`call`/`ret` stack discipline) and the dividing ones (which is what pins the
128-bit group-3 results). -/

/-! ## Registers -/

def x86_get_reg (s : X86State) (i : Nat) : UInt64 :=
  match i with
  | 0 => s.rax | 1 => s.rcx | 2 => s.rdx | 3 => s.rbx
  | 4 => s.rsp | 5 => s.rbp | 6 => s.rsi | 7 => s.rdi
  | 8 => s.r8 | 9 => s.r9 | 10 => s.r10 | 11 => s.r11
  | 12 => s.r12 | 13 => s.r13 | 14 => s.r14 | 15 => s.r15
  | _ => 0

def x86_set_reg (s : X86State) (i : Nat) (v : UInt64) : X86State :=
  match i with
  | 0 => {s with rax := v} | 1 => {s with rcx := v} | 2 => {s with rdx := v}
  | 3 => {s with rbx := v} | 4 => {s with rsp := v} | 5 => {s with rbp := v}
  | 6 => {s with rsi := v} | 7 => {s with rdi := v}
  | 8 => {s with r8 := v} | 9 => {s with r9 := v} | 10 => {s with r10 := v}
  | 11 => {s with r11 := v} | 12 => {s with r12 := v} | 13 => {s with r13 := v}
  | 14 => {s with r14 := v} | 15 => {s with r15 := v}
  | _ => s

/-! ## REX prefix -/

def x86_is_rex (b : UInt8) : Bool := b.toNat ≥ 64 && b.toNat ≤ 79

/-! The bit tests go through `toNat` rather than masking the `UInt8` directly.
    Same values -- the byte is in range either way -- but `simp` reduces `Nat`
    literal arithmetic and knows no lemmas for `UInt8`'s, so the `UInt8` form
    leaves `if 72 &&& 1 = 0 then ...` unreduced in a proof, which is what a
    symbolic register index turns into. -/

def x86_rex_w (b : UInt8) : Bool := (b.toNat &&& 8) != 0

def x86_rex_r (b : UInt8) : Nat := if (b.toNat &&& 4) != 0 then 8 else 0

def x86_rex_b (b : UInt8) : Nat := if (b.toNat &&& 1) != 0 then 8 else 0

/-! ### REX bit decoding, as `simp` facts

A REX byte is three independent bits, and the model reads them with `&&&`.  On
a LITERAL byte — which is what every instruction lemma has, because the
generator knows the concrete instructions of the program it is proving —
Lean's simplifier does not fold a `UInt8` bitwise-and against a numeral by
itself.  Without these, the flag tests inside the model survive `simp` as
`if 72 &&& 8 = 0 then …`, and each instruction lemma has to be closed by hand
instead of by its own hypotheses.  Stating the sixteen decodings once, as
proved `[simp]` facts, is what makes a generated per-instruction certificate a
one-line `simp` over the bytes it was handed.
-/

-- The no-prefix case, which every instruction lemma for a plain opcode needs.
@[simp] theorem x86_rex_w_zero : x86_rex_w (0 : UInt8) = false := rfl
@[simp] theorem x86_rex_r_zero : x86_rex_r (0 : UInt8) = 0 := rfl
@[simp] theorem x86_rex_b_zero : x86_rex_b (0 : UInt8) = 0 := rfl

@[simp] theorem x86_rex_w_40 : x86_rex_w (0x40 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_40 : x86_rex_r (0x40 : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_40 : x86_rex_b (0x40 : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_41 : x86_rex_w (0x41 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_41 : x86_rex_r (0x41 : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_41 : x86_rex_b (0x41 : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_42 : x86_rex_w (0x42 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_42 : x86_rex_r (0x42 : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_42 : x86_rex_b (0x42 : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_43 : x86_rex_w (0x43 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_43 : x86_rex_r (0x43 : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_43 : x86_rex_b (0x43 : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_44 : x86_rex_w (0x44 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_44 : x86_rex_r (0x44 : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_44 : x86_rex_b (0x44 : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_45 : x86_rex_w (0x45 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_45 : x86_rex_r (0x45 : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_45 : x86_rex_b (0x45 : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_46 : x86_rex_w (0x46 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_46 : x86_rex_r (0x46 : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_46 : x86_rex_b (0x46 : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_47 : x86_rex_w (0x47 : UInt8) = false := by decide
@[simp] theorem x86_rex_r_47 : x86_rex_r (0x47 : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_47 : x86_rex_b (0x47 : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_48 : x86_rex_w (0x48 : UInt8) = true := by decide
@[simp] theorem x86_rex_r_48 : x86_rex_r (0x48 : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_48 : x86_rex_b (0x48 : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_49 : x86_rex_w (0x49 : UInt8) = true := by decide
@[simp] theorem x86_rex_r_49 : x86_rex_r (0x49 : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_49 : x86_rex_b (0x49 : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_4a : x86_rex_w (0x4a : UInt8) = true := by decide
@[simp] theorem x86_rex_r_4a : x86_rex_r (0x4a : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_4a : x86_rex_b (0x4a : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_4b : x86_rex_w (0x4b : UInt8) = true := by decide
@[simp] theorem x86_rex_r_4b : x86_rex_r (0x4b : UInt8) = 0 := by decide
@[simp] theorem x86_rex_b_4b : x86_rex_b (0x4b : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_4c : x86_rex_w (0x4c : UInt8) = true := by decide
@[simp] theorem x86_rex_r_4c : x86_rex_r (0x4c : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_4c : x86_rex_b (0x4c : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_4d : x86_rex_w (0x4d : UInt8) = true := by decide
@[simp] theorem x86_rex_r_4d : x86_rex_r (0x4d : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_4d : x86_rex_b (0x4d : UInt8) = 8 := by decide

@[simp] theorem x86_rex_w_4e : x86_rex_w (0x4e : UInt8) = true := by decide
@[simp] theorem x86_rex_r_4e : x86_rex_r (0x4e : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_4e : x86_rex_b (0x4e : UInt8) = 0 := by decide

@[simp] theorem x86_rex_w_4f : x86_rex_w (0x4f : UInt8) = true := by decide
@[simp] theorem x86_rex_r_4f : x86_rex_r (0x4f : UInt8) = 8 := by decide
@[simp] theorem x86_rex_b_4f : x86_rex_b (0x4f : UInt8) = 8 := by decide

/-! ## Memory -/

/-- Little-endian read of `n` bytes: the byte at `addr` is the LEAST
    significant, and each following byte sits above it. (Getting this backwards
    is silent — a spilled 10 reads back as 0x0A00000000000000 — and every
    program that spills a local disagrees with the hardware.) -/
def mem_read_bytes (mem : Nat → UInt8) (addr n : Nat) : UInt64 :=
  match n with
  | 0 => 0
  | k + 1 => (mem addr).toUInt64 ||| (mem_read_bytes mem (addr + 1) k <<< 8)

/-- Little-endian write of the low `n` bytes of `val`. -/
def mem_write_bytes (mem : Nat → UInt8) (addr : Nat) (val : UInt64) (n : Nat) : Nat → UInt8 :=
  match n with
  | 0 => mem
  | k + 1 =>
    let rest := mem_write_bytes mem (addr + 1) (val >>> 8) k
    fun i => if i = addr then val.toUInt8 else rest i

/-- Truncate to 32 bits, zero-extended: what every 32-bit x86 operation leaves
    in a register. -/
def x86_trunc32 (v : UInt64) : UInt64 := UInt64.ofNat (v.toNat % 4294967296)

-- `setcc` writes one byte, which zero-extends; these two are the only values
-- it ever writes, and every setcc lemma ends in one of them.
@[simp] theorem x86_trunc32_zero : x86_trunc32 0 = 0 := rfl
@[simp] theorem x86_trunc32_one : x86_trunc32 1 = 1 := rfl


/-- The effective address of an r/m memory operand, plus how many bytes follow
    the ModRM byte (SIB, then displacement).

    `atp` is the address of the ModRM byte and `endAddr` the address one past
    the instruction's last byte — a RIP-relative displacement is measured from
    there, not from the ModRM byte. `none` means mod=3 (a register operand). -/
def x86_mem_addr (s : X86State) (code : Nat → UInt8) (rex modrm : UInt8)
    (atp endAddr : Nat) : Option (Nat × Nat) :=
  let m := modrm.toNat
  let mode := m >>> 6
  let rm := m &&& 7
  if mode = 3 then none
  else
    let noSib := rm != 4
    let ripRel := mode = 0 && rm = 5
    let sibExtra := if noSib then 0 else 1
    let dispPos := atp + 1 + sibExtra
    let dispN := if mode = 1 then 1 else if mode = 2 || ripRel then 4 else 0
    let disp : Int :=
      if dispN = 1 then read_i8 (code dispPos)
      else if dispN = 4 then read_i32_le code dispPos
      else 0
    let base : Nat :=
      if ripRel then endAddr
      else if noSib then (x86_get_reg s (rm + x86_rex_b rex)).toNat
      else (x86_get_reg s ((code (atp + 1) &&& 7).toNat + x86_rex_b rex)).toNat
    some ((Int.ofNat base + disp).toNat, sibExtra + dispN)

/-- Read the r/m operand: a register when mod=3, else `sz` bytes of memory. -/
def x86_rm_read (s : X86State) (code : Nat → UInt8) (rex modrm : UInt8)
    (atp endAddr : Nat) (sz : Nat) : Option UInt64 :=
  if (modrm.toNat >>> 6) = 3 then
    some (x86_get_reg s ((modrm.toNat &&& 7) + x86_rex_b rex))
  else
    match x86_mem_addr s code rex modrm atp endAddr with
    | some (addr, _) => some (mem_read_bytes s.mem addr sz)
    | none => none

/-- Write the r/m operand. A 4- or 8-byte write zero-extends into the full
    64-bit register, which is the rule that makes a 32-bit `mov` after a
    64-bit one actually shrink the value. -/
def x86_rm_write (s : X86State) (code : Nat → UInt8) (rex modrm : UInt8)
    (atp endAddr : Nat) (sz : Nat) (v : UInt64) : Option X86State :=
  if (modrm.toNat >>> 6) = 3 then
    some (x86_set_reg s ((modrm.toNat &&& 7) + x86_rex_b rex)
      (if sz = 8 then v else x86_trunc32 v))
  else
    match x86_mem_addr s code rex modrm atp endAddr with
    | some (addr, _) => some { s with mem := mem_write_bytes s.mem addr v sz }
    | none => none

/-! ## Flags and conditions -/

def x86_msb (v : UInt64) : Bool := v ≥ 0x8000000000000000

/-- Flags after a logical operation (and/or/xor/test): ZF and SF from the
    result, CF and OF cleared. -/
def x86_flags_logic (s : X86State) (res : UInt64) : X86State :=
  { s with zf := res = 0, sf := x86_msb res, cf := false, of_ := false }

def x86_flags_add (s : X86State) (a b res : UInt64) : X86State :=
  { s with zf := res = 0, sf := x86_msb res, cf := res < a, of_ := x86_msb a == x86_msb b && (x86_msb res != x86_msb a) }

def x86_flags_sub (s : X86State) (a b res : UInt64) : X86State :=
  { s with zf := res = 0, sf := x86_msb res, cf := a < b, of_ := x86_msb a != x86_msb b && (x86_msb res != x86_msb a) }

/-- Evaluate a condition code against the flags.

    The `cc` argument is the OPCODE NIBBLE, not the backend's `COND_*` constant:
    `jcc rel8` encodes as `0x70 + cc`, `jcc rel32` as `0x0F 0x80 + cc` and
    `setcc` as `0x0F 0x90 + cc`, so the nibble that reaches the decoder is the
    one x86 defines — 2 = B (CF), 3 = AE (¬CF), 4 = E (ZF), 6 = BE, 7 = A,
    0xC = L, 0xD = GE, 0xE = LE, 0xF = G. formal/x86_64.py's COND_* names are
    the Intel manual's numbering, which is a different permutation; reading
    the nibble as if it were COND_* evaluates the wrong condition entirely. -/
def x86_cond (cc : Nat) (s : X86State) : Bool :=
  match cc with
  | 0 => s.of_                  -- o
  | 1 => !s.of_                 -- no
  | 2 => s.cf                   -- b / c / nae
  | 3 => !s.cf                  -- ae / nb / nc
  | 4 => s.zf                   -- e / z
  | 5 => !s.zf                  -- ne / nz
  | 6 => s.cf || s.zf           -- be / na
  | 7 => !s.cf && !s.zf         -- a / nbe
  | 8 => s.sf                   -- s
  | 9 => !s.sf                  -- ns
  | 10 => s.zf                  -- p  (approximated: see below)
  | 11 => !s.zf                 -- np (approximated: see below)
  | 12 => s.sf != s.of_         -- l / nge
  | 13 => s.sf == s.of_         -- ge / nl
  | 14 => s.zf || s.sf != s.of_ -- le / ng
  | _ => !s.zf && s.sf == s.of_ -- g / nle
  -- NOTE: PF (cc 10/11) is a parity bit over the low byte of the result.
  -- X86State has no PF field and no instruction this backend emits sets one a
  -- program can observe, so those two fall back to the ZF test. A program that
  -- branches on them needs a `pf` field in X86State before the model can be
  -- trusted there.

/-- Sign-extend bit 31 of `v` across the top word: what `movsxd` does. -/
def x86_sign_extend32 (v : UInt64) : UInt64 :=
  if x86_msb (x86_trunc32 v) then v ||| 0xffffffff00000000 else v

/-- Sign-extend bit 7 of `v` across the whole word: what `movsx r64, r8`
    does.  The 8- and 16-bit forms were missing, and `movsx` was reaching for
    the 32-bit one, which extends bit 31 and so silently computed a different
    number than the instruction does on hardware. -/
def x86_sign_extend8 (v : UInt64) : UInt64 :=
  if v &&& 0x80 != 0 then v ||| 0xffffffffffffff00 else v

/-- Sign-extend bit 15 of `v` across the whole word: `movsx r64, r16`. -/
def x86_sign_extend16 (v : UInt64) : UInt64 :=
  if v &&& 0x8000 != 0 then v ||| 0xffffffffffff0000 else v


/-- `v` as a signed 64-bit number. -/
def x86_signed (v : UInt64) : Int :=
  if x86_msb v then (v.toNat : Int) - 18446744073709551616 else (v.toNat : Int)

def x86_two64 : Nat := 18446744073709551616

/-- Split an arbitrary-precision product/sum into the RDX:RAX pair a
    multiply or divide produces, discarding everything above 128 bits the way
    the hardware keeps only the low 128. -/
def x86_split128 (p : Int) : UInt64 × UInt64 :=
  let lo := p % (x86_two64 : Int)
  let hi := (p - lo) / (x86_two64 : Int) % (x86_two64 : Int)
  (UInt64.ofNat lo.toNat, UInt64.ofNat hi.toNat)

/-- Unsigned RDX:RAX / divisor, as (quotient, remainder). `none` on a zero
    divisor, which is the divide error the hardware raises. -/
def x86_div128 (hi lo d : Nat) : Option (Nat × Nat) :=
  if d = 0 then none
  else
    let n := hi * x86_two64 + lo
    some (n / d, n % d)

/-- Signed IDIV: the 128-bit dividend is signed, and the quotient truncates
    toward zero (Int.tdiv), not toward -inf as Int.ediv would. -/
def x86_idiv128 (hi lo d : Int) : Option (Int × Int) :=
  if d = 0 then none
  else
    let n := hi * (x86_two64 : Int) + lo
    some (Int.tdiv n d, Int.tmod n d)

/-! ## The step function -/

/-- REX-prefixed instruction forms. `op` is the byte after the prefix.

    The prefix shifts EVERY field one byte along: with a REX byte at `rip`, the
    opcode is at `rip + 1` and the ModRM byte at `rip + 2` — not `rip + 1`,
    which is the trap this function's shape is built to avoid. Each branch
    below therefore takes its ModRM byte from `modrmPos`. -/
def x86_step_rex (s : X86State) (code : Nat → UInt8) (rex op : UInt8) : Option X86State :=
  let rip := s.rip
  let w := x86_rex_w rex
  let opn := op.toNat
  let modrmPos := rip + 2
  if 0x50 ≤ op && op ≤ 0x57 then
    -- push r64 (REX.B extends the register)
    let r := (opn &&& 7) + x86_rex_b rex
    let rsp' := s.rsp - 8
    let mem' := mem_write_bytes s.mem rsp'.toNat (x86_get_reg s r) 8
    some { s with rsp := rsp', mem := mem', rip := rip + 2 }
  else if 0x58 ≤ op && op ≤ 0x5f then
    -- pop r64
    let r := (opn &&& 7) + x86_rex_b rex
    let v := mem_read_bytes s.mem (s.rsp.toNat) 8
    some { x86_set_reg s r v with rsp := s.rsp + 8, rip := rip + 2 }
  else if op = 0x99 && w then
    -- cqo: RDX = the sign extension of RAX
    some { s with rdx := x86_sign_extend32 s.rax, rip := rip + 2 }
  else if 0xb8 ≤ op && op ≤ 0xbf && w then
    -- mov r64, imm64
    let v := mem_read_bytes code (rip + 2) 8
    some { x86_set_reg s ((opn &&& 7) + x86_rex_b rex) v with rip := rip + 10 }
  else if op = 0x89 then
    -- mov r/m, r — REX.W picks the 64-bit form, its absence the zero-extending 32-bit one
    let modrm := code modrmPos
    let sz := if w then 8 else 4
    let extra := match x86_mem_addr s code rex modrm modrmPos (rip + 4) with
      | some (_, n) => n | none => 0
    let endAddr := if w then rip + 3 + extra else rip + 2 + extra
    let raw := x86_get_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex)
    let src := if w then raw else x86_trunc32 raw
    match x86_rm_write s code rex modrm modrmPos endAddr sz src with
    | some s' => some { s' with rip := endAddr }
    | none => none
  else if op = 0x8b then
    -- mov r, r/m
    let modrm := code modrmPos
    let sz := if w then 8 else 4
    let extra := match x86_mem_addr s code rex modrm modrmPos (rip + 4) with
      | some (_, n) => n | none => 0
    let endAddr := if w then rip + 3 + extra else rip + 2 + extra
    match x86_rm_read s code rex modrm modrmPos endAddr sz with
    | some v => some { x86_set_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex) v with rip := endAddr }
    | none => none
  else if op = 0x8d && w then
    -- lea r, m — address arithmetic, no memory access
    let modrm := code modrmPos
    let extra := match x86_mem_addr s code rex modrm modrmPos (rip + 4) with
      | some (_, n) => n | none => 0
    let endAddr := rip + 3 + extra
    match x86_mem_addr s code rex modrm modrmPos endAddr with
    | some (addr, _) =>
      some { x86_set_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex) (UInt64.ofNat (addr % 18446744073709551616)) with rip := endAddr }
    | none => none
  else if op = 0x63 && w then
    -- movsxd r64, r/m32
    let modrm := code modrmPos
    match x86_rm_read s code rex modrm modrmPos (rip + 3) 4 with
    | some v => some { x86_set_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex) (x86_sign_extend32 v) with rip := rip + 3 }
    | none => none
  else if op = 0xc7 && w then
    -- mov r/m64, imm32 (sign-extended)
    let modrm := code modrmPos
    let imm := UInt64.ofInt (read_i32_le code (rip + 3))
    match x86_rm_write s code rex modrm modrmPos (rip + 7) 8 imm with
    | some s' => some { s' with rip := rip + 7 }
    | none => none
  else if w && (op = 0x01 || op = 0x09 || op = 0x21 || op = 0x29 || op = 0x31 || op = 0x39 || op = 0x85) then
    -- ALU r/m64, r64
    let modrm := code modrmPos
    let a := x86_get_reg s ((modrm.toNat &&& 7) + x86_rex_b rex)
    let b := x86_get_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex)
    let endAddr := rip + 3
    if op = 0x01 then
      let res := a + b
      let f := x86_flags_add s a b res
      match x86_rm_write s code rex modrm modrmPos endAddr 8 res with
      | some s' => some { x86_flags_logic s' res with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
      | none => none
    else if op = 0x29 then
      let res := a - b
      let f := x86_flags_sub s a b res
      match x86_rm_write s code rex modrm modrmPos endAddr 8 res with
      | some s' => some { s' with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
      | none => none
    else if op = 0x39 then
      let f := x86_flags_sub s a b (a - b)
      some { s with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
    else
      let res := if op = 0x09 then a ||| b else if op = 0x21 then a &&& b else if op = 0x31 then a ^^^ b else a &&& b
      let f := x86_flags_logic s res
      if op = 0x85 then some { s with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
      else
        match x86_rm_write s code rex modrm modrmPos endAddr 8 res with
        | some s' => some { s' with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
        | none => none
  else if w && (op = 0x81 || op = 0x83) then
    -- ALU r/m64, imm32 (0x81) or imm8 (0x83)
    let modrm := code modrmPos
    let digit := (modrm.toNat >>> 3) &&& 7
    let a := x86_get_reg s ((modrm.toNat &&& 7) + x86_rex_b rex)
    let imm := if op = 0x81 then UInt64.ofInt (read_i32_le code (rip + 3)) else UInt64.ofInt (read_i8 (code (rip + 3)))
    let endAddr := if op = 0x81 then rip + 7 else rip + 4
    let res := if digit = 0 then a + imm else if digit = 1 then a ||| imm else if digit = 4 then a &&& imm else if digit = 5 then a - imm else if digit = 6 then a ^^^ imm else a - imm
    if digit = 7 then
      let f := x86_flags_sub s a imm res
      some { s with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
    else
      let f := if digit = 0 then x86_flags_add s a imm res else if digit = 5 then x86_flags_sub s a imm res else x86_flags_logic s res
      match x86_rm_write s code rex modrm modrmPos endAddr 8 res with
      | some s' => some { s' with rip := endAddr, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
      | none => none
  else if w && (op = 0xc1 || op = 0xd3) then
    -- shl / shr / sar by imm8 (0xc1) or by CL (0xd3)
    let modrm := code modrmPos
    let digit := (modrm.toNat >>> 3) &&& 7
    let a := x86_get_reg s ((modrm.toNat &&& 7) + x86_rex_b rex)
    let n := if op = 0xc1 then (code (rip + 3)).toNat else (x86_get_reg s 1).toNat
    let endAddr := if op = 0xc1 then rip + 4 else rip + 3
    let sh64 := UInt64.ofNat (if n ≥ 64 then 64 else n)
    let res := if digit = 4 then a <<< sh64 else if digit = 5 then a >>> sh64 else (x86_sign_extend32 a) >>> sh64
    let f := x86_flags_logic s res
    match x86_rm_write s code rex modrm modrmPos endAddr 8 res with
    | some s' => some { s' with rip := endAddr, zf := f.zf, sf := f.sf }
    | none => none
  else if w && op = 0xf7 then
    -- group 3: not / neg / mul / imul / div / idiv.  All but not/neg produce
    -- or consume the RDX:RAX pair, so the flags they set are the ones the
    -- HIGH half finally lands in: a multiply sets SF/ZF from RAX.
    let modrm := code modrmPos
    let digit := (modrm.toNat >>> 3) &&& 7
    let r := (modrm.toNat &&& 7) + x86_rex_b rex
    let a := x86_get_reg s r
    if digit = 2 then
      -- not
      some { x86_set_reg s r (a ^^^ 0xffffffffffffffff) with rip := rip + 3 }
    else if digit = 3 then
      -- neg
      let res := (0 : UInt64) - a
      let f := x86_flags_sub s (0 : UInt64) a res
      some { x86_set_reg s r res with rip := rip + 3, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
    else if digit = 4 then
      -- mul r/m64: RDX:RAX = RAX * r/m64, unsigned
      let (lo, hi) := x86_split128 (Int.ofNat s.rax.toNat * Int.ofNat a.toNat)
      let f := x86_flags_logic s lo
      some { s with rax := lo, rdx := hi, rip := rip + 3, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
    else if digit = 5 then
      -- imul r/m64: RDX:RAX = RAX * r/m64, signed
      let (lo, hi) := x86_split128 (x86_signed s.rax * x86_signed a)
      let f := x86_flags_logic s lo
      some { s with rax := lo, rdx := hi, rip := rip + 3, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
    else if digit = 6 then
      -- div r/m64: RAX = RDX:RAX / r/m64, RDX = remainder
      match x86_div128 s.rdx.toNat s.rax.toNat a.toNat with
      | some (q, rem) =>
        let f := x86_flags_logic s (UInt64.ofNat q)
        some { s with rax := UInt64.ofNat q, rdx := UInt64.ofNat rem, rip := rip + 3, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
      | none => none
    else
      -- idiv r/m64: signed, truncating
      match x86_idiv128 (x86_signed s.rdx) (x86_signed s.rax) (x86_signed a) with
      | some (q, rem) =>
        let f := x86_flags_logic s (UInt64.ofNat q.toNat)
        some { s with rax := UInt64.ofNat q.toNat, rdx := UInt64.ofNat rem.toNat, rip := rip + 3, zf := f.zf, sf := f.sf, cf := f.cf, of_ := f.of_ }
      | none => none
  else if op = 0x0f then
    let op2 := code (rip + 2)
    if 0x90 ≤ op2 && op2 ≤ 0x9f then
      -- setcc r/m8
      let modrm := code (rip + 3)
      let v := if x86_cond (op2.toNat - 0x90) s then 1 else 0
      match x86_rm_write s code rex modrm (rip + 3) (rip + 4) 1 v with
      | some s' => some { s' with rip := rip + 4 }
      | none => none
    else if 0x80 ≤ op2 && op2 ≤ 0x8f then
      -- jcc rel32
      let off := read_i32_le code (rip + 3)
      some { s with rip := if x86_cond (op2.toNat - 0x80) s then (Int.ofNat rip + 7 + off).toNat else rip + 7 }
    else if op2 = 0xaf && w then
      -- imul r64, r/m64
      let modrm := code (rip + 3)
      let a := x86_get_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex)
      let b := x86_get_reg s ((modrm.toNat &&& 7) + x86_rex_b rex)
      some { x86_set_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex) (a * b) with rip := rip + 4 }
    else if op2 = 0xb6 || op2 = 0xb7 || op2 = 0xbe || op2 = 0xbf then
      -- movzx / movsx into r64
      --
      -- The operand is `sz` BYTES and the extension starts at bit `8*sz - 1`.
      -- This arm used `x86_sign_extend32` for all four opcodes and took the
      -- read unmodified, which is wrong twice over, and both halves were
      -- silent:
      --
      --   * `x86_rm_read` with mod = 3 returns the whole register (it is used
      --     by 8-byte reads too, where that is right), so a 1-byte `movzx`
      --     left the upper 56 bits of the destination alone. `movzx rbx, bl`
      --     with rbx = 0xff00 gave 0xff00, not 0xff.
      --   * `x86_sign_extend32` extends bit 31, so `movsx rbx, bl` with
      --     bl = 0xff — that is, -1 — gave 0x00000000000000ff, not
      --     0xffffffffffffffff.
      --
      -- Both were CONFIRMED by evaluating the model, not by reading it, and
      -- both were invisible from outside for the same reason: the only three
      -- examples that emit a byte `movsx` (n8, sgt8, sle8) had no step lemma
      -- wired for it, so the value test never reached the comparison. A gap in
      -- a proof chain hid a defect in the thing the chain was proving things
      -- about.
      let modrm := code (rip + 3)
      let sz := if op2 = 0xb6 || op2 = 0xbe then 1 else 2
      let sign := op2 = 0xbe || op2 = 0xbf
      match x86_rm_read s code rex modrm (rip + 3) (rip + 4) sz with
      | some v =>
        let narrowed := v &&& (if sz = 1 then 0xFF else 0xFFFF)
        let ext := if !sign then narrowed
                   else if sz = 1 then x86_sign_extend8 narrowed
                   else x86_sign_extend16 narrowed
        some { x86_set_reg s ((modrm.toNat >>> 3 &&& 7) + x86_rex_r rex) ext with rip := rip + 4 }
      | none => none
    else none
  else none

/-- Instruction forms with no REX prefix. -/
def x86_step_plain (s : X86State) (code : Nat → UInt8) (b0 : UInt8) : Option X86State :=
  let rip := s.rip
  let opn := b0.toNat
  if 0x50 ≤ b0 && b0 ≤ 0x57 then
    let rsp' := s.rsp - 8
    let mem' := mem_write_bytes s.mem rsp'.toNat (x86_get_reg s (opn &&& 7)) 8
    some { s with rsp := rsp', mem := mem', rip := rip + 1 }
  else if 0x58 ≤ b0 && b0 ≤ 0x5f then
    let v := mem_read_bytes s.mem (s.rsp.toNat) 8
    some { x86_set_reg s (opn &&& 7) v with rsp := s.rsp + 8, rip := rip + 1 }
  else if b0 = 0xc3 then
    -- ret
    some { s with rip := (mem_read_bytes s.mem (s.rsp.toNat) 8).toNat, rsp := s.rsp + 8 }
  else if b0 = 0xc9 then
    -- leave: rsp := rbp ; pop rbp
    some { x86_set_reg s 5 (mem_read_bytes s.mem (s.rbp.toNat) 8) with rsp := s.rbp + 8, rip := rip + 1 }
  else if b0 = 0x90 then
    some { s with rip := rip + 1 }
  else if 0x70 ≤ b0 && b0 ≤ 0x7f then
    let off := read_i8 (code (rip + 1))
    some { s with rip := if x86_cond (opn - 0x70) s then (Int.ofNat rip + 2 + off).toNat else rip + 2 }
  else if b0 = 0xeb then
    let off := read_i8 (code (rip + 1))
    some { s with rip := (Int.ofNat rip + 2 + off).toNat }
  else if b0 = 0xe9 then
    some { s with rip := (Int.ofNat rip + 5 + read_i32_le code (rip + 1)).toNat }
  else if b0 = 0xe8 then
    -- call rel32: push the return address, then jump
    let target := (Int.ofNat rip + 5 + read_i32_le code (rip + 1)).toNat
    let rsp' := s.rsp - 8
    let mem' := mem_write_bytes s.mem rsp'.toNat (UInt64.ofNat (rip + 5)) 8
    some { s with rip := target, rsp := rsp', mem := mem' }
  else if b0 = 0xff then
    -- call/jmp through memory (the extern paths)
    let modrm := code (rip + 1)
    let digit := (modrm.toNat >>> 3) &&& 7
    if digit != 2 && digit != 4 then none
    else
      match x86_mem_addr s code 0 modrm (rip + 1) (rip + 6) with
      | some (addr, _) =>
        let target := (mem_read_bytes s.mem addr 8).toNat
        if digit = 2 then
          let rsp' := s.rsp - 8
          let mem' := mem_write_bytes s.mem rsp'.toNat (UInt64.ofNat (rip + 6)) 8
          some { s with rip := target, rsp := rsp', mem := mem' }
        else some { s with rip := target }
      | none => none
  else if b0 = 0x89 then
    -- mov r/m32, r32 (no REX.W): zero-extending
    let modrm := code (rip + 1)
    let extra := match x86_mem_addr s code 0 modrm (rip + 1) (rip + 2) with
      | some (_, n) => n | none => 0
    let endAddr := rip + 2 + extra
    let src := x86_trunc32 (x86_get_reg s ((modrm.toNat >>> 3) &&& 7))
    match x86_rm_write s code 0 modrm (rip + 1) endAddr 4 src with
    | some s' => some { s' with rip := endAddr }
    | none => none
  else if b0 = 0x8b then
    -- mov r32, r/m32
    let modrm := code (rip + 1)
    let extra := match x86_mem_addr s code 0 modrm (rip + 1) (rip + 2) with
      | some (_, n) => n | none => 0
    let endAddr := rip + 2 + extra
    match x86_rm_read s code 0 modrm (rip + 1) endAddr 4 with
    | some v => some { x86_set_reg s ((modrm.toNat >>> 3) &&& 7) v with rip := endAddr }
    | none => none
  else if b0 = 0x31 then
    -- xor r/m32, r32 (the `xor edx, edx` before a div)
    let modrm := code (rip + 1)
    if (modrm.toNat >>> 6) != 3 then none
    else
      let a := x86_get_reg s ((modrm.toNat &&& 7))
      let b := x86_get_reg s ((modrm.toNat >>> 3 &&& 7))
      let res := x86_trunc32 (a ^^^ b)
      some { x86_set_reg s ((modrm.toNat &&& 7)) res with rip := rip + 2, zf := res = 0 }
  else if b0 = 0x0f then
    let op2 := code (rip + 1)
    if 0x90 ≤ op2 && op2 ≤ 0x9f then
      let modrm := code (rip + 2)
      let v := if x86_cond (op2.toNat - 0x90) s then 1 else 0
      match x86_rm_write s code 0 modrm (rip + 2) (rip + 3) 1 v with
      | some s' => some { s' with rip := rip + 3 }
      | none => none
    else if 0x80 ≤ op2 && op2 ≤ 0x8f then
      let off := read_i32_le code (rip + 2)
      some { s with rip := if x86_cond (op2.toNat - 0x80) s then (Int.ofNat rip + 6 + off).toNat else rip + 6 }
    else if op2 = 0xb6 || op2 = 0xb7 || op2 = 0xbe || op2 = 0xbf then
      let modrm := code (rip + 2)
      let sz := if op2 = 0xb6 || op2 = 0xbe then 1 else 2
      match x86_rm_read s code 0 modrm (rip + 2) (rip + 4) sz with
      | some v => some { x86_set_reg s ((modrm.toNat >>> 3) &&& 7) v with rip := rip + 4 }
      | none => none
    else none
  else none

/-- The x86-64 step function: a REX prefix routes to the prefixed forms, and
    everything else to the plain ones. `none` means the model does not decode
    this instruction — the run tests' termination obligations are what notice. -/
def x86_step (s : X86State) (code : Nat → UInt8) : Option X86State :=
  let b0 := code s.rip
  if x86_is_rex b0 then x86_step_rex s code b0 (code (s.rip + 1))
  else x86_step_plain s code b0



/-! ## Instruction lemmas

Each says what `x86_step` does to the state at one specific pc, for one
instruction form.  The proof generator's per-instruction certificates are
stated in terms of these: a straight-line block of decoded instructions steps
from one known state to the next by rewriting with them, so what they have to
give is the WHOLE successor state, not a fact about one field.

They are stated with literal opcodes and registers, not with a register
parameter, and that is deliberate rather than lazy.  A generated certificate is
about the concrete instructions of one program, so a literal is both what it
needs and what `simp` can close: with a symbolic register the model reads
`((0x50 + r).toNat &&& 7)`, and no amount of `omega` gets through a `&&&`.

Two operand-order traps are worth stating once here, because both silently
give a proof about a different instruction than the one in the binary:

  * `89 /r`, `39 /r` and `29 /r` put the SOURCE in the ModRM `reg` field and
    the destination in `rm`.  So `48 89 d8` is `mov rax, rbx`, and `48 39 c3`
    compares RBX against RAX.
  * `setcc` writes ONE byte, and an 8-bit write zero-extends into the full
    64-bit register — so the condition's 0/1 lands in RAX, and the `movzx`
    after it needs no masking.
-/

theorem x86_step_push_rbp (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x55) :
    x86_step s code = some { s with rsp := s.rsp - 8, rip := m + 1, mem := mem_write_bytes s.mem (s.rsp - 8).toNat s.rbp 8 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0]

theorem x86_step_push_rax (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x50) :
    x86_step s code = some { s with rsp := s.rsp - 8, rip := m + 1, mem := mem_write_bytes s.mem (s.rsp - 8).toNat s.rax 8 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0]

theorem x86_step_pop_rbp (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x5d) :
    x86_step s code = some { x86_set_reg s 5 (mem_read_bytes s.mem (s.rsp.toNat) 8) with rsp := s.rsp + 8, rip := m + 1 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0]

theorem x86_step_ret (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0xc3) :
    x86_step s code = some { s with rip := (mem_read_bytes s.mem (s.rsp.toNat) 8).toNat, rsp := s.rsp + 8 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0]

theorem x86_step_nop (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x90) :
    x86_step s code = some { s with rip := m + 1 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0]

theorem x86_step_leave (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0xc9) :
    x86_step s code = some { s with rbp := mem_read_bytes s.mem (s.rbp.toNat) 8, rsp := s.rbp + 8, rip := m + 1 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0]

/-- `call rel32`: push the address after the call, then jump there. -/
theorem x86_step_call_rel32 (s : X86State) (code : Nat → UInt8) (m : Nat) (off : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0xe8) (h_imm : read_i32_le code (m + 1) = off) :
    x86_step s code = some { s with rip := (Int.ofNat m + 5 + off).toNat, rsp := s.rsp - 8, mem := mem_write_bytes s.mem (s.rsp - 8).toNat (UInt64.ofNat (m + 5)) 8 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_imm]

/-- `mov rax, rbx` (REX.W 89 /r, mod=3): the ModRM `reg` field is the SOURCE
    and `rm` the destination, so 0xd8 (reg=3, rm=0) moves RBX into RAX. -/
theorem x86_step_mov_rax_rbx (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x89) (h_b2 : code (m + 2) = 0xd8) :
    x86_step s code = some { x86_set_reg s 0 s.rbx with rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2]

/-- `mov rbx, rax` (REX.W 89 /r, mod=3, 0xc3: reg=rax, rm=rbx). -/
theorem x86_step_mov_rbx_rax (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x89) (h_b2 : code (m + 2) = 0xc3) :
    x86_step s code = some { x86_set_reg s 3 s.rax with rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2]

/-- `mov rax, imm32` sign-extended (REX.W C7 /0 id). -/
theorem x86_step_mov_rax_imm32 (s : X86State) (code : Nat → UInt8) (m : Nat) (imm : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0xc7) (h_b2 : code (m + 2) = 0xc0)
    (h_imm : read_i32_le code (m + 3) = imm) :
    x86_step s code = some { s with rax := UInt64.ofInt imm, rip := m + 7 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2, h_imm]

-- `cmp rax, rbx`: ModRM 0xc3 is reg=rax (source), rm=rbx (destination), so
-- the flags come from RBX - RAX -- i.e. the comparison is `cmp rbx, rax` in
-- AT&T reading order.
/-- `cmp` of RAX against RBX (REX.W 39 /r, mod=3): flags only. -/
theorem x86_step_cmp_rax_rbx (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x39) (h_b2 : code (m + 2) = 0xc3) :
    x86_step s code = some { x86_flags_sub s s.rbx s.rax (s.rbx - s.rax) with rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2]

-- `sub`: reg is the source, rm the destination, so 0x29 /c3 is RBX -= RAX.
/-- `sub rbx, rax` (REX.W 29 /r, mod=3). -/
theorem x86_step_sub_rbx_rax (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x29) (h_b2 : code (m + 2) = 0xc3) :
    x86_step s code = some { x86_flags_sub s s.rbx s.rax (s.rbx - s.rax) with rbx := s.rbx - s.rax, rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2]

/-- `add rax, imm32` (REX.W 81 /0 id). -/
theorem x86_step_add_rax_imm32 (s : X86State) (code : Nat → UInt8) (m : Nat) (imm : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x81) (h_b2 : code (m + 2) = 0xc0)
    (h_imm : read_i32_le code (m + 3) = imm) :
    x86_step s code = some { x86_flags_add s s.rax (UInt64.ofInt imm) (s.rax + UInt64.ofInt imm) with rax := s.rax + UInt64.ofInt imm, rip := m + 7 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2, h_imm]

/-- `setne al` (0F 95 /0): an 8-bit write, so the full register is zero-extended. -/
theorem x86_step_setne_al (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x0f) (h_b1 : code (m + 1) = 0x95) (h_b2 : code (m + 2) = 0xc0) :
    x86_step s code = some { s with rax := if x86_cond 5 s then 1 else 0, rip := m + 3 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, h_rip, h_b0, h_b1, h_b2]
  by_cases h : x86_cond 5 s = true <;> simp [h]

/-- `setle al` (0F 9E /0). -/
theorem x86_step_setle_al (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x0f) (h_b1 : code (m + 1) = 0x9e) (h_b2 : code (m + 2) = 0xc0) :
    x86_step s code = some { s with rax := if x86_cond 14 s then 1 else 0, rip := m + 3 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, h_rip, h_b0, h_b1, h_b2]
  by_cases h : x86_cond 14 s = true <;> simp [h]

/-- `movzx rax, al` (REX.W 0F B6 /r, mod=3).

    **This lemma used to conclude `rax := s.rax`, and that was wrong.** It was
    a theorem about a model that read the whole register and never narrowed it,
    so the lemma and the bug agreed with each other and the suite was green.
    Fixing the model made the two disagree, which is the only reason anyone
    noticed: the proof is still by `simp`, but now of a statement that says
    what the instruction does. -/
theorem x86_step_movzx_rax_al (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x0f) (h_b2 : code (m + 2) = 0xb6)
    (h_b3 : code (m + 3) = 0xc0) :
    x86_step s code = some { s with rax := s.rax &&& 0xFF, rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_b1, h_b2, h_b3]

/-! `movsx r64, r8` (REX.W 0F BE /r, mod=3): the SIGNED twin of the lemma above,
    and the first `movsx` the chain can step at all.  `movsx_r64_r8` was the
    largest single uncovered form left in the end-to-end theorem -- it named the
    missing lemma for 3 of the 45 examples, `n8`, `sgt8` and `sle8`, and those
    three could not have a path tree because of it.

    It is general over both registers, and the corpus is what says so rather
    than taste: it emits two distinct shapes, `48 0f be c0` (`movsx rax, al`)
    and `48 0f be db` (`movsx rbx, bl`), three of the second to one of the
    first.  Two shapes is the point at which a concrete `x86_step_movsx_rax_al`
    becomes a second copy of `x86_step_movzx_rax_al` with one byte changed.

    The destination is a CONCRETE `dst`, with `reg + x86_rex_r rex = dst`
    beside it, for the reason `x86_step_mov_rm64_mem_disp8_rbp` gives: the model
    writes `x86_set_reg s (reg + x86_rex_r rex) ...` and `simp` will not reduce
    a `match` on a non-literal, so the caller reads the destination out of the
    encoding and supplies it.  The caller is `formal/x86_64_endtoend_test.py`.

    Note what that argument does NOT need, because the first attempt carried it
    and it was the wrong thing to reach for: no `dst < 16`.  Reducing the
    `match` was never the goal -- making both sides the SAME unreduced `match`
    is -- so the bound plays no part, and the proof is one `simp` shorter for
    dropping it.

    `x86_sign_extend8` is on bit 7, not bit 31, and the model's 0F BE arm is
    right about that where it used not to be.  The two errors cancelled from
    outside, which is the part worth keeping: the arm applied the 32-bit
    extension, and the only examples that emit a byte `movsx` had no step lemma
    wired for the form, so nothing ever asked the model what it computed.  A
    gap in the proof chain hid a defect in the thing the chain was proving
    things about -- see the arm's own comment.

    The arm also does not consult REX.W, so this lemma states the 64-bit form
    `h_w` pins and the model's no-REX arm (which neither narrows nor extends) is
    a different statement again.  `encode_movsx_r64_r8` always sets W, so the
    third reading is unreachable from this backend and is not modelled. -/
theorem x86_step_movsx_r64_r8 (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm dst : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x0f)
    (h_b2 : code (m + 2) = 0xbe) (h_b3 : code (m + 3) = modrm)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_dst : reg + x86_rex_r rex = dst) :
    x86_step s code = some { x86_set_reg s dst
        (x86_sign_extend8 (x86_get_reg s (rm + x86_rex_b rex) &&& 0xFF)) with
        rip := m + 4 } := by
  -- `x86_set_reg`, `x86_sign_extend8`, `x86_rex_r` and `x86_is_rex` are all
  -- DELIBERATELY absent from this set, and their absence is most of the proof.
  -- Every one of them is there to break a rewrite the simplifier needs to do
  -- first:
  --
  --   * `x86_rex_r` unfolds the model's destination index to
  --     `reg + (if rex.toNat &&& 4 = 0 then 0 else 8)`, so `h_dst` no longer
  --     matches it, the two sides keep different destinations, and `simp`
  --     answers by projecting the record update -- a 1100-line goal that is a
  --     `X86State` literal, naming neither the form nor the field.
  --   * `x86_set_reg` then unfolds the destination into a 16-arm `match` on a
  --     symbolic index that cannot reduce, which is the wall B10 is about.  The
  --     goal survives as two 2000-line structures that differ in a `match`.
  --   * `x86_sign_extend8` is an `if` on bit 7 of a value that is itself a
  --     `match` on the source register, so unfolding it splits the goal.
  --   * `x86_is_rex` turns the `x86_step` dispatch into an `if` on two
  --     comparisons over a symbolic `rex`, and `simp` splits on that `if`,
  --     landing in the `x86_step_plain` branch -- which is a different decoder
  --     with a different length for the 0x0F escape, so the goal becomes about
  --     an instruction the bytes do not encode.
  --
  -- With all four left folded, `h_dst` rewrites the index to `dst` and the two
  -- sides are the same two applications.  `imul` above needs `x86_set_reg` and
  -- this does not, because `imul`'s statement puts `x86_get_reg s dst` on both
  -- sides of the product and the `match` has to come apart for that; this one's
  -- source index never reaches a `match`.
  simp [x86_step, x86_step_rex, x86_get_reg, x86_mem_addr, x86_rm_read,
        h_rip, h_b0, h_b1, h_b2, h_b3, h_rex, h_w, h_mod, h_reg, h_rm, h_dst]


/-- `jz rel32` (0F 84 id): taken lands past the displacement. -/
theorem x86_step_jz_rel32 (s : X86State) (code : Nat → UInt8) (m : Nat) (off : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0x0f) (h_b1 : code (m + 1) = 0x84)
    (h_imm : read_i32_le code (m + 2) = off) :
    x86_step s code = some { s with rip := if s.zf then (Int.ofNat m + 6 + off).toNat else m + 6 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, x86_cond, h_rip, h_b0, h_b1, h_imm]

/-- `jz rel8` (74 ib).  The two short-jump forms the backend emits are
    spelled out rather than parameterized by condition code: `x86_cond` on a
    *variable* cc leaves the simplifier a nested `if` over byte arithmetic it
    will not close, while on a literal it reduces to the flag test, which is
    what a generated certificate wants anyway. -/
theorem x86_step_jz_rel8 (s : X86State) (code : Nat → UInt8) (m : Nat) (off : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0x74) (h_imm : read_i8 (code (m + 1)) = off) :
    x86_step s code = some { s with rip := if s.zf then (Int.ofNat m + 2 + off).toNat else m + 2 } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_cond, h_rip, h_b0, h_imm]

/-- `jnz rel8` (75 ib). -/
theorem x86_step_jnz_rel8 (s : X86State) (code : Nat → UInt8) (m : Nat) (off : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0x75) (h_imm : read_i8 (code (m + 1)) = off) :
    x86_step s code = some { s with rip := if s.zf then m + 2 else (Int.ofNat m + 2 + off).toNat } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_cond, h_rip, h_b0, h_imm]
  cases s.zf <;> rfl

/-- `jmp rel32` (E9 id). -/
theorem x86_step_jmp_rel32 (s : X86State) (code : Nat → UInt8) (m : Nat) (off : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0xe9) (h_imm : read_i32_le code (m + 1) = off) :
    x86_step s code = some { s with rip := (Int.ofNat m + 5 + off).toNat } := by
  simp [x86_step, x86_step_plain, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr, x86_rm_read, x86_rm_write, x86_flags_sub, x86_flags_add, x86_flags_logic, x86_msb, h_rip, h_b0, h_imm]

/-! ## Memory separation

`mem_read_bytes` recurses on the read WIDTH and `mem_write_bytes` on the byte
COUNT, so no single induction sees through both: a one-lemma version leaves
eight unreduced `if i = a` tests in the goal. Splitting it in two makes each
induction single-headed — the write is the identity pointwise outside its
range, and a read through it is then the read of the original memory.

These are what a straight-line body proof needs, and ProofLib has the arm64
equivalents (`mem_read_push_frame`, `mem_read_two_writes_adjacent_mod`,
`mem_read_write_pair_below`) but nothing here until now. -/

/-- Above the written range, the write function IS the identity. -/
theorem mem_write_bytes_above (m : Nat → UInt8) (a : Nat) (v : UInt64)
    (n i : Nat) (h : a + n ≤ i) :
    mem_write_bytes m a v n i = m i := by
  induction n generalizing a v i with
  | zero => rfl
  | succ k ih =>
    simp only [mem_write_bytes]
    rw [if_neg (by omega : ¬(i = a))]
    exact ih (a + 1) (v >>> 8) i (by omega)

/-- Below the written range, likewise. -/
theorem mem_write_bytes_below (m : Nat → UInt8) (a : Nat) (v : UInt64)
    (n i : Nat) (h : i < a) :
    mem_write_bytes m a v n i = m i := by
  induction n generalizing a v i with
  | zero => rfl
  | succ k ih =>
    simp only [mem_write_bytes]
    rw [if_neg (by omega : ¬(i = a))]
    exact ih (a + 1) (v >>> 8) i (by omega)

/-- A read whose whole width lies above a write is unaffected by it. -/
theorem mem_read_bytes_write_above (m : Nat → UInt8) (a : Nat) (v : UInt64)
    (n w b : Nat) (h : a + n ≤ b) :
    mem_read_bytes (mem_write_bytes m a v n) b w = mem_read_bytes m b w := by
  induction w generalizing b with
  | zero => rfl
  | succ k ihw =>
    simp only [mem_read_bytes]
    rw [mem_write_bytes_above m a v n b h]
    rw [ihw (b + 1) (by omega)]

/-- A read whose whole width lies below a write is unaffected by it. -/
theorem mem_read_bytes_write_below (m : Nat → UInt8) (a : Nat) (v : UInt64)
    (n w b : Nat) (h : b + w ≤ a) :
    mem_read_bytes (mem_write_bytes m a v n) b w = mem_read_bytes m b w := by
  induction w generalizing b with
  | zero => rfl
  | succ k ihw =>
    simp only [mem_read_bytes]
    rw [mem_write_bytes_below m a v n b (by omega)]
    rw [ihw (b + 1) (by omega)]

/-! ## The prologue forms, and what closing a body still needs

Every x86-64 function starts `push rbp ; mov rbp, rsp ; sub rsp, <frame>`, so
those three are the forms any per-instruction argument meets first. The two
that were missing are here.

`x86_exec_exit`'s exit sentinel — address 0, reached because a `ret` in a
function entered at its own label pops the zero the initial stack holds — also
needs saying once.

Closing a function's body outright is a further step, and the reason is worth
recording because it is not obvious: chaining the step lemmas builds a state
expression N structure updates deep, and the last `ret` reads
`memReadBytes` of that whole nest at the initial stack pointer. Proving it is
0 means proving that every push and spill in the nest wrote SOMEWHERE ELSE.
The separation lemmas above are the tool for that and they are proved, but the
chain that needs them is still term-bound: six `x86_exec_go_exit_step` rewrites
of a leaf function build a state expression deep enough that the kernel
reports deep recursion, and the last step's side condition is over the whole
nest. The next thing to write is a chaining lemma that keeps the intermediate
state ABSTRACT (a variable per step) rather than accumulating one expression, so
the separation side conditions are discharged one write at a time. Until that
exists, the generated proofs carry run tests (real `native_decide` evaluations,
so the machine IS checked against the source semantics for concrete inputs) and
a `sorry` end-to-end theorem. -/

/-- `mov rbp, rsp` — the frame setup (REX.W 89 /r, ModRM 0xe5: mod=3, reg=4
    RSP as the source, rm=5 RBP as the destination). -/
theorem x86_step_mov_rbp_rsp (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x89)
    (h_b2 : code (m + 2) = 0xe5) :
    x86_step s code = some { s with rbp := s.rsp, rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, h_rip, h_b0, h_b1, h_b2]

/-- `add rsp, imm32` (REX.W 81 /0 id, ModRM c4).  The counterpart of
    `x86_step_sub_rsp_imm32` below, and the reason it exists: EVERY `alu_ri32:add`
    the backend emits targets rsp, so wiring that form to the rax-only
    `x86_step_add_rax_imm32` matches none of them.  A lemma named for one
    register sitting under a general form name is the same failure as the
    `mov_rm64_r64` -> `mov_rbp_rsp` one, and the only symptom is a proof that
    does not apply. -/
theorem x86_step_add_rsp_imm32 (s : X86State) (code : Nat → UInt8) (m : Nat)
    (imm : Int) (h_rip : s.rip = m) (h_b0 : code m = 0x48)
    (h_b1 : code (m + 1) = 0x81) (h_b2 : code (m + 2) = 0xc4)
    (h_imm : read_i32_le code (m + 3) = imm) :
    x86_step s code = some { x86_flags_add s s.rsp (UInt64.ofInt imm) (s.rsp + UInt64.ofInt imm) with rsp := s.rsp + UInt64.ofInt imm, rip := m + 7 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_flags_add, h_rip, h_b0, h_b1, h_b2, h_imm]

/-- `sub rsp, imm32` — the frame allocation (REX.W 81 /5 id, ModRM 0xec). -/
theorem x86_step_sub_rsp_imm32 (s : X86State) (code : Nat → UInt8) (m : Nat)
    (imm : Int) (h_rip : s.rip = m) (h_b0 : code m = 0x48)
    (h_b1 : code (m + 1) = 0x81) (h_b2 : code (m + 2) = 0xec)
    (h_imm : read_i32_le code (m + 3) = imm) :
    x86_step s code = some { x86_flags_sub s s.rsp (UInt64.ofInt imm) (s.rsp - UInt64.ofInt imm) with rsp := s.rsp - UInt64.ofInt imm, rip := m + 7 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_flags_sub, h_rip, h_b0, h_b1, h_b2, h_imm]

/-! The compare family: `cmp` and `test` set flags and leave every register
    alone, which is what makes them pleasant to generalise -- there is no
    successor register to name, only flags.  Both are REX.W 3x /r with mod=3,
    and the operands are the rm field extended by REX.B (as `a`) and the reg
    field extended by REX.R (as `b`), so `cmp %rax, %rbx` reads as
    `flags_sub rbx rax`.  Together with `setcc` below these three lemmas
    unblocked the most examples of anything in this file. -/

/-- `cmp r64, r64` (REX.W 39 /r, mod=3), general over both registers: flags
    only, so nothing in the register file moves. -/
theorem x86_step_cmp_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x39)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { s with
        rip := m + 3,
        zf := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) (x86_get_reg s (rm + x86_rex_b rex) - x86_get_reg s (reg + x86_rex_r rex))).zf,
        sf := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) (x86_get_reg s (rm + x86_rex_b rex) - x86_get_reg s (reg + x86_rex_r rex))).sf,
        cf := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) (x86_get_reg s (rm + x86_rex_b rex) - x86_get_reg s (reg + x86_rex_r rex))).cf,
        of_ := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) (x86_get_reg s (rm + x86_rex_b rex) - x86_get_reg s (reg + x86_rex_r rex))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-- `test r64, r64` (REX.W 85 /r, mod=3), general over both registers: the
    AND is computed and thrown away, and only the flags survive. -/
theorem x86_step_test_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x85)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { s with
        rip := m + 3,
        zf := (x86_flags_logic s (x86_get_reg s (rm + x86_rex_b rex) &&& x86_get_reg s (reg + x86_rex_r rex))).zf,
        sf := (x86_flags_logic s (x86_get_reg s (rm + x86_rex_b rex) &&& x86_get_reg s (reg + x86_rex_r rex))).sf,
        cf := (x86_flags_logic s (x86_get_reg s (rm + x86_rex_b rex) &&& x86_get_reg s (reg + x86_rex_r rex))).cf,
        of_ := (x86_flags_logic s (x86_get_reg s (rm + x86_rex_b rex) &&& x86_get_reg s (reg + x86_rex_r rex))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-! The 0x0F escape, as `x86_step_plain` dispatches it.

    These are the no-REX forms, and the distinction from the REX-prefixed
    dispatch above is not cosmetic: the plain path hardcodes `rex = 0`, and its
    two-byte-prefix instructions are THREE bytes (`0F 9x c0`) where the REX
    path's are four.  A successor stated with the wrong length is not a proof
    that is hard to finish, it is a proof of a different instruction, and it
    fails in a way (`\u22a2 False`) that does not say so.

    Reaching a case means excluding the others, so both lemmas take the range
    and exclusion facts as hypotheses rather than deriving them.  They are
    stated separately -- not as one conjunction -- because the decoder tests
    them as separate `&&`s and `simp` uses a hypothesis as a rewrite rule
    instead of splitting a conjunction.  Every one is closed for a concrete
    opcode byte, so the caller discharges each with `decide`. -/

/-- `setcc r/m8` (0F 90+cc /r), general over the condition nibble and the
    8-bit destination, which is the r/m field.  A one-byte write zero-extends,
    so the only two values are 0 and 1. -/
theorem x86_step_setcc_r8 (s : X86State) (code : Nat → UInt8) (m : Nat)
    (op2 modrm : UInt8) (cc rmv : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x0f) (h_b1 : code (m + 1) = op2)
    (h_b2 : code (m + 2) = modrm) (h_cc : op2.toNat - 0x90 = cc)
    (h_lo : (0x90 : UInt8) ≤ op2) (h_hi : op2 ≤ 0x9f)
    (h_njcc : ¬ (op2 ≤ 0x8f))
    (h_nzx : ¬ (op2 = 0xb6 ∨ op2 = 0xb7 ∨ op2 = 0xbe ∨ op2 = 0xbf))
    (h_notrex : x86_is_rex 0x0f = false) (h_mod : modrm.toNat >>> 6 = 3)
    (h_rm : modrm.toNat &&& 7 = rmv) (h_rb : x86_rex_b 0 = 0) :
    x86_step s code = some
      { x86_set_reg s rmv (if x86_cond cc s then 1 else 0) with rip := m + 3 } := by
  simp [x86_step, x86_step_plain, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_rex_b,
        h_rip, h_b0, h_b1, h_b2, h_cc, h_lo, h_hi, h_njcc,
        h_nzx, h_notrex, h_mod, h_rm, h_rb]
  -- The 1-byte write zero-extends, and the two values `setcc` ever produces
  -- have `[simp]` facts for exactly that.  Splitting on the condition is what
  -- applies them; `simp` alone cannot reduce `x86_trunc32` of an `if`.
  by_cases h : x86_cond cc s = true <;> simp [h]

/-- `jcc rel32` (0F 80+cc id), general over the condition nibble.  The
    successor's `rip` is an `if` on the condition rather than a constant, which
    is exactly what a path tree needs: it forks the chain here. -/
theorem x86_step_jcc_rel32 (s : X86State) (code : Nat → UInt8) (m : Nat)
    (op2 : UInt8) (cc off : Int)
    (h_rip : s.rip = m) (h_b0 : code m = 0x0f) (h_b1 : code (m + 1) = op2)
    (h_cc : op2.toNat - 0x80 = cc.toNat)
    (h_off : read_i32_le code (m + 2) = off)
    (h_lo : (0x80 : UInt8) ≤ op2) (h_hi : op2 ≤ 0x8f)
    (h_nsetcc_lo : ¬ ((0x90 : UInt8) ≤ op2))
    (h_nzx : ¬ (op2 = 0xb6 ∨ op2 = 0xb7 ∨ op2 = 0xbe ∨ op2 = 0xbf))
    (h_notrex : x86_is_rex 0x0f = false) :
    x86_step s code = some
      { s with rip := if x86_cond cc.toNat s
          then (Int.ofNat m + 6 + off).toNat else m + 6 } := by
  simp [x86_step, x86_step_plain,
        h_rip, h_b0, h_b1, h_cc, h_off, h_lo, h_hi, h_nsetcc_lo, h_nzx,
        h_notrex]

/-! The two register-to-register ALU forms the backend emits, general over
    both registers.  The destination is the rm field, as everywhere else; only
    the source is the reg field.  The model computes `add`'s flags through
    `x86_flags_logic` on the written-back state and then overwrites all four
    with the add's own, so the two end up with the same shape -- which is
    worth knowing, because the code does not look like it does. -/

/-- `imul r64, r64` (REX.W 0F AF /r, mod=3).  Unlike the ALU forms the
    destination is the reg field -- the SAME field the first multiplicand is
    read from -- so the operation is `reg := reg * rm` rather than `rm :=
    reg op rm`, and the byte order is 0F AF not 01 /r.

    `imul` sets no flags, so the successor is just the register and the rip.
    It is worth a lemma of its own because the backend emits it for 8 of the 43
    examples, and without one those 8 have no path tree at all.

    `dst` is the CONCRETE destination register, for the same reason the
    `rbp + disp8` load takes one: `x86_set_reg` is a `match` on its index and
    `simp` will not reduce a match on a non-literal. -/
theorem x86_step_imul_r64 (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex op2 modrm : UInt8) (reg rm dst : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x0f)
    (h_b2 : code (m + 2) = op2) (h_b3 : code (m + 3) = modrm)
    (h_op2 : op2 = 0xaf) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm)
    (h_dst : reg + x86_rex_r rex = dst) (h_dst_lt : dst < 16) :
    x86_step s code = some
      { x86_set_reg s dst (x86_get_reg s dst * x86_get_reg s (rm + x86_rex_b rex))
        with rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_flags_logic,
        h_rip, h_b0, h_b1, h_b2, h_b3, h_op2, h_rex, h_w, h_mod, h_reg, h_rm,
        h_dst, h_dst_lt]

/-- `add r64, r64` (REX.W 01 /r, mod=3), general over both registers. -/
theorem x86_step_add_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x01)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { x86_set_reg s (rm + x86_rex_b rex) ((x86_get_reg s (rm + x86_rex_b rex)) + (x86_get_reg s (reg + x86_rex_r rex))) with
        rip := m + 3,
        zf := (x86_flags_add s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) + (x86_get_reg s (reg + x86_rex_r rex)))).zf,
        sf := (x86_flags_add s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) + (x86_get_reg s (reg + x86_rex_r rex)))).sf,
        cf := (x86_flags_add s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) + (x86_get_reg s (reg + x86_rex_r rex)))).cf,
        of_ := (x86_flags_add s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) + (x86_get_reg s (reg + x86_rex_r rex)))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_flags_logic, x86_flags_add,
        x86_flags_sub,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-- `sub r64, r64` (REX.W 29 /r, mod=3), general over both registers. -/
theorem x86_step_sub_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x29)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { x86_set_reg s (rm + x86_rex_b rex) ((x86_get_reg s (rm + x86_rex_b rex)) - (x86_get_reg s (reg + x86_rex_r rex))) with
        rip := m + 3,
        zf := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) - (x86_get_reg s (reg + x86_rex_r rex)))).zf,
        sf := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) - (x86_get_reg s (reg + x86_rex_r rex)))).sf,
        cf := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) - (x86_get_reg s (reg + x86_rex_r rex)))).cf,
        of_ := (x86_flags_sub s (x86_get_reg s (rm + x86_rex_b rex)) (x86_get_reg s (reg + x86_rex_r rex)) ((x86_get_reg s (rm + x86_rex_b rex)) - (x86_get_reg s (reg + x86_rex_r rex)))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_flags_logic, x86_flags_add,
        x86_flags_sub,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-! The three LOGIC ALU forms -- `and` (0x21), `or` (0x09), `xor` (0x31) -- as
    three theorems rather than one.

    One theorem is the obvious thing to reach for and it does not work, which
    is worth stating because the model's own arm IS one arm for all three:
    `res` there is `if op = 0x09 then a ||| b else if op = 0x21 then a &&& b
    else if op = 0x31 then a ^^^ b else a &&& b`, and a single theorem about
    that chain has to either state the chain (so every caller inherits an `if`
    it cannot reduce, and has to prove which arm it is in all over again) or
    take the result as an argument and a hypothesis that it is the right arm
    (so the caller supplies a fact that is false for two of the three opcodes).
    Three theorems over a literal opcode byte is the shape `add_rr`/`sub_rr`
    above already use, and it keeps each successor a plain term.

    What the three have in common is the FLAGS, and that is the reason they are
    siblings rather than six unrelated lemmas: `and`, `or` and `xor` all compute
    ZF and SF from the result and clear CF and OF, so the successor is the same
    four expressions with a different operator on the value.  In the model that
    is literally `x86_flags_logic`, computed once on the pre-write state and
    then re-asserted over the written-back one -- `add` above is the same shape
    and `x86_step_add_rr`'s note says so. -/

/-- `and r64, r64` (REX.W 21 /r, mod=3), general over both registers.

    The DESTINATION is the rm field (+REX.B) and the SOURCE is the reg field
    (+REX.R), which is the opposite sense to `mov` and the reason the parameter
    names here are the encoding's. -/
theorem x86_step_and_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x21)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { x86_set_reg s (rm + x86_rex_b rex) ((x86_get_reg s (rm + x86_rex_b rex)) &&& (x86_get_reg s (reg + x86_rex_r rex))) with
        rip := m + 3,
        zf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) &&& (x86_get_reg s (reg + x86_rex_r rex)))).zf,
        sf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) &&& (x86_get_reg s (reg + x86_rex_r rex)))).sf,
        cf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) &&& (x86_get_reg s (reg + x86_rex_r rex)))).cf,
        of_ := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) &&& (x86_get_reg s (reg + x86_rex_r rex)))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_flags_logic, x86_flags_add,
        x86_flags_sub,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-- `or r64, r64` (REX.W 09 /r, mod=3). -/
theorem x86_step_or_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x09)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { x86_set_reg s (rm + x86_rex_b rex) ((x86_get_reg s (rm + x86_rex_b rex)) ||| (x86_get_reg s (reg + x86_rex_r rex))) with
        rip := m + 3,
        zf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ||| (x86_get_reg s (reg + x86_rex_r rex)))).zf,
        sf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ||| (x86_get_reg s (reg + x86_rex_r rex)))).sf,
        cf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ||| (x86_get_reg s (reg + x86_rex_r rex)))).cf,
        of_ := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ||| (x86_get_reg s (reg + x86_rex_r rex)))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_flags_logic, x86_flags_add,
        x86_flags_sub,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-- `xor r64, r64` (REX.W 31 /r, mod=3). -/
theorem x86_step_xor_rr (s : X86State) (code : Nat → UInt8) (m : Nat)
    (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x31)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some { x86_set_reg s (rm + x86_rex_b rex) ((x86_get_reg s (rm + x86_rex_b rex)) ^^^ (x86_get_reg s (reg + x86_rex_r rex))) with
        rip := m + 3,
        zf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ^^^ (x86_get_reg s (reg + x86_rex_r rex)))).zf,
        sf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ^^^ (x86_get_reg s (reg + x86_rex_r rex)))).sf,
        cf := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ^^^ (x86_get_reg s (reg + x86_rex_r rex)))).cf,
        of_ := (x86_flags_logic s ((x86_get_reg s (rm + x86_rex_b rex)) ^^^ (x86_get_reg s (reg + x86_rex_r rex)))).of_ } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write, x86_trunc32, x86_flags_logic, x86_flags_add,
        x86_flags_sub,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-! `mov r64, r/m64` in its two shapes.  These two cover every instance the
    backend emits -- 170 across the examples, and `mov_r64_rm64` was the single
    form blocking the most end-to-end proofs, so it is worth having the general
    version rather than the one-register-pair instances above. -/

/-- `mov r64, r64` register to register (REX.W 8B /r, mod=3), general over both
    registers and over the REX bits that extend either of them.

    The field names are the encoding's, not intuition's: the DESTINATION is
    the reg field, extended by REX.R, and the SOURCE is the rm field, extended
    by REX.B.  Swapping them typechecks fine as long as both are symbolic --
    `movzx_rax_al` above is the same instruction read the other way round --
    and is the reason this is stated with `reg`/`rm` rather than src/dst. -/
theorem x86_step_mov_rm64_r64_reg (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some
      { x86_set_reg s (reg + x86_rex_r rex) (x86_get_reg s (rm + x86_rex_b rex)) with
        rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-! `mov r64, qword [rbp + disp8]` (REX.W 8B /r, mod=1, rm=5), the other
    half of the two shapes `mov r64, r/m64` has in this corpus: every
    spilled-argument access is one of these or the `[rsp]` one, and there is no
    third.

    The destination register is a CONCRETE argument, with
    `reg + x86_rex_r rex = dst` beside it, and that is what makes this go
    through.  Stated with the symbolic index it does not: the destination is
    `x86_set_reg s (reg + x86_rex_r rex) ...`, `x86_set_reg` is a `match` on
    its index, and `simp` will not reduce a match on a non-literal -- so the
    goal is left as two 20-field structures that differ in a `match`, which
    shows the whole field list and says nothing about what is wrong.  The STORE
    below has the same shape and does normalise, because there the index only
    ever appears inside `x86_get_reg`.  Hence the asymmetry, and hence the extra
    argument: the caller reads the destination out of the encoding. -/
theorem x86_step_mov_rm64_mem_disp8_rbp (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg dst : Nat) (disp : Int)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = modrm) (h_disp : read_i8 (code (m + 3)) = disp)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 1) (h_rm : modrm.toNat &&& 7 = 5)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_dst : reg + x86_rex_r rex = dst) (h_dst_lt : dst < 16) :
    x86_step s code = some { x86_set_reg s dst (mem_read_bytes s.mem (Int.ofNat (x86_get_reg s (5 + x86_rex_b rex)).toNat + disp).toNat 8) with
        rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write,
        h_rip, h_b0, h_b1, h_b2, h_disp, h_rex, h_w, h_mod, h_rm, h_reg, h_dst,
        h_dst_lt]

/-! The two store-direction `mov` shapes (opcode 89), mirroring the load ones
    above.  These are the STORE direction, and the field sense flips: the
    SOURCE is the reg field (+REX.R) and the DESTINATION is the rm field
    (+REX.B).  Reading them the other way round typechecks while both indices
    are symbolic, which is how `mov_rbp_rsp` above came to look general when it
    is one register pair. -/

/-- `mov r64, r64` register to register (REX.W 89 /r, mod=3). -/
theorem x86_step_mov_rm64_r64_reg_st (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg rm : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x89)
    (h_b2 : code (m + 2) = modrm) (h_rex : x86_is_rex rex = true)
    (h_w : x86_rex_w rex = true) (h_mod : modrm.toNat >>> 6 = 3)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rm : modrm.toNat &&& 7 = rm) :
    x86_step s code = some
      { x86_set_reg s (rm + x86_rex_b rex) (x86_get_reg s (reg + x86_rex_r rex)) with
        rip := m + 3 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write,
        h_rip, h_b0, h_b1, h_b2, h_rex, h_w, h_mod, h_reg, h_rm]

/-- `mov qword [rbp + disp8], r64` (REX.W 89 /r, mod=1, rm=5). -/
theorem x86_step_mov_mem_disp8_r64 (s : X86State) (code : Nat → UInt8)
    (m : Nat) (rex modrm : UInt8) (reg : Nat) (disp : Int)
    (h_rip : s.rip = m) (h_b0 : code m = rex) (h_b1 : code (m + 1) = 0x89)
    (h_b2 : code (m + 2) = modrm) (h_disp : read_i8 (code (m + 3)) = disp)
    (h_rex : x86_is_rex rex = true) (h_w : x86_rex_w rex = true)
    (h_mod : modrm.toNat >>> 6 = 1) (h_rm : modrm.toNat &&& 7 = 5)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg) :
    x86_step s code = some { s with
        mem := mem_write_bytes s.mem (Int.ofNat (x86_get_reg s (5 + x86_rex_b rex)).toNat + disp).toNat (x86_get_reg s (reg + x86_rex_r rex)) 8,
        rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write,
        h_rip, h_b0, h_b1, h_b2, h_disp, h_rex, h_w, h_mod, h_rm, h_reg]

/-- `mov qword [rsp + 0], r64` (REX.W 89 /r, ModRM 04, SIB 24: scale 0, index
    none, base rsp) -- the store counterpart of `mov rax, [rsp]` below, and
    general over the source register.  This is the shape a computed value takes
    on its way to the stack frame. -/
theorem x86_step_mov_mem_sib_rsp (s : X86State) (code : Nat → UInt8)
    (m : Nat) (modrm : UInt8) (reg : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x89)
    (h_b2 : code (m + 2) = modrm) (h_b3 : code (m + 3) = 0x24)
    (h_rex : x86_is_rex 0x48 = true) (h_w : x86_rex_w 0x48 = true)
    (h_mod : modrm.toNat >>> 6 = 0) (h_rm : (modrm.toNat &&& 7) = 4)
    (h_reg : (modrm.toNat >>> 3) &&& 7 = reg)
    (h_rb : x86_rex_b 0x48 = 0) (h_rr : x86_rex_r 0x48 = 0) :
    x86_step s code = some { s with
        mem := mem_write_bytes s.mem s.rsp.toNat (x86_get_reg s (reg + x86_rex_r 0x48)) 8,
        rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, x86_rm_write,
        h_rip, h_b0, h_b1, h_b2, h_b3, h_rex, h_w, h_mod, h_rm, h_reg, h_rb,
        h_rr]

/-- `mov rax, qword [rsp + 0]` (REX.W 8B /r, ModRM 04: mod=0 rm=4, SIB 24:
    scale 0, index none, base rsp).  Every SIB operand the backend emits has
    this shape, so the general SIB case would be machinery nothing uses. -/
theorem x86_step_mov_rax_sib_rsp (s : X86State) (code : Nat → UInt8) (m : Nat)
    (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = 0x04) (h_b3 : code (m + 3) = 0x24)
    (h_w : x86_rex_w 0x48 = true) (h_rex : x86_is_rex 0x48 = true) :
    x86_step s code = some
      { s with rax := mem_read_bytes s.mem s.rsp.toNat 8, rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_get_reg, x86_set_reg,
        x86_mem_addr, x86_rm_read,
        h_rip, h_b0, h_b1, h_b2, h_b3, h_w, h_rex]

/-! The two disp8 memory forms every spilled-argument function uses.  These are
the instructions that make a proof about the stack need the separation lemmas
above: the store writes memory and the load reads it back, so a chain that
walks a spilled argument has to relate a read at one state to a write at an
earlier one. -/

/-- `mov qword [rbp + disp8], rdi` (REX.W 89 /r, ModRM 7d: mod=1 disp8,
    reg=rdi, rm=rbp).  A 64-bit store, so the value is written whole. -/
theorem x86_step_mov_mem_disp8_rdi (s : X86State) (code : Nat → UInt8) (m : Nat)
    (disp : Int) (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x89)
    (h_b2 : code (m + 2) = 0x7d) (h_disp : read_i8 (code (m + 3)) = disp) :
    x86_step s code = some { s with
        mem := mem_write_bytes s.mem (Int.ofNat s.rbp.toNat + disp).toNat s.rdi 8,
        rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_mem_addr,
        x86_rm_write, h_rip, h_b0, h_b1, h_b2, h_disp]

/-- `mov rax, qword [rbp + disp8]` (REX.W 8B /r, ModRM 45: mod=1 disp8,
    reg=rax, rm=rbp).  The load of what the store above wrote. -/
theorem x86_step_mov_rax_mem_disp8 (s : X86State) (code : Nat → UInt8) (m : Nat)
    (disp : Int) (h_rip : s.rip = m) (h_b0 : code m = 0x48) (h_b1 : code (m + 1) = 0x8b)
    (h_b2 : code (m + 2) = 0x45) (h_disp : read_i8 (code (m + 3)) = disp) :
    x86_step s code = some { s with
        rax := mem_read_bytes s.mem (Int.ofNat s.rbp.toNat + disp).toNat 8,
        rip := m + 4 } := by
  simp [x86_step, x86_step_rex, x86_is_rex, x86_get_reg, x86_set_reg, x86_mem_addr,
        x86_rm_read, h_rip, h_b0, h_b1, h_b2, h_disp]

/-- The initial state's memory reads as zero everywhere.  This is what makes
    address 0 a usable exit sentinel rather than a lucky guess: the entry
    function's own `ret` pops a zero from the initial stack, so the runner
    stops at 0 with the result in RAX and no planted return address. -/
theorem x86_init_mem_reads_zero (n : UInt64) (entry : Nat) (a : Nat) :
    mem_read_bytes (X86State.init n entry).mem a 8 = 0 := by
  simp [X86State.init, mem_read_bytes]


/-! ### Running the model

Two runners, because there are two questions.  `x86_exec` answers "run until
the function returns": it stops when the next instruction is a `ret`, which is
the right shape when the entry point really is a function.  A proof usually
wants the state at the moment the ENTRY function returns to *its* caller, and
that is `x86_exec_exit`, which stops at a named pc.  `X86State.init` gives a
stack full of zeroes, so a `ret` in a function entered at its own label pops
address 0 — which makes 0 a usable exit sentinel and spares every generated
proof from having to plant a return address. -/

@[irreducible] def x86_exec_go (st : X86State) (fuel : Nat) (code : Nat → UInt8) : Option X86State :=
  match fuel with
  | 0 => none
  | n + 1 =>
    match x86_step st code with
    | none => none
    | some st' =>
      if code st'.rip = 0xc3 then some st'
      else x86_exec_go st' n code

/-- Execute until `ret` (0xc3) is next, the model refuses to decode, or fuel runs out. -/
@[irreducible] def x86_exec (s : X86State) (code : Nat → UInt8) : Option X86State :=
  x86_exec_go s 1000 code

theorem x86_exec_eq_go (s : X86State) (code : Nat → UInt8) :
    x86_exec s code = x86_exec_go s 1000 code := by
  unfold x86_exec; rfl

/-- If a step succeeds and the next instruction is not ret, continue execution. -/
@[simp] theorem x86_exec_go_step_continue {st : X86State} {fuel : Nat} {code : Nat → UInt8} {st' : X86State}
    (h_step : x86_step st code = some st') (h_not_ret : code st'.rip ≠ 0xc3) (h_fuel : 0 < fuel) :
    x86_exec_go st fuel code = x86_exec_go st' (fuel - 1) code := by
  cases fuel with
  | zero => omega
  | succ n => simp [x86_exec_go, h_step, h_not_ret]

/-- If a step succeeds and the next instruction is ret, return that state. -/
@[simp] theorem x86_exec_go_step_ret {st : X86State} {fuel : Nat} {code : Nat → UInt8} {st' : X86State}
    (h_step : x86_step st code = some st') (h_ret : code st'.rip = 0xc3) (h_fuel : 0 < fuel) :
    x86_exec_go st fuel code = some st' := by
  cases fuel with
  | zero => omega
  | succ n => simp [x86_exec_go, h_step, h_ret]

@[irreducible] def x86_exec_go_exit (st : X86State) (code : Nat → UInt8)
    (exit : Nat) (fuel : Nat) : Option X86State :=
  match fuel with
  | 0 => none
  | n + 1 =>
    if st.rip = exit then some st
    else
      match x86_step st code with
      | none => none
      | some st' => x86_exec_go_exit st' code exit n

/-- Run to the exit pc (see the note above on why 0 works), or fail. -/
def x86_exec_exit (s : X86State) (code : Nat → UInt8) (exit : Nat) : Option X86State :=
  x86_exec_go_exit s code exit 100000

/-- The equation behind `x86_exec_exit`, so a proof can unfold one step at a
    time instead of through a definition that is `@[irreducible]`. -/
theorem x86_exec_exit_eq_go (s : X86State) (code : Nat → UInt8) (exit : Nat) :
    x86_exec_exit s code exit = x86_exec_go_exit s code exit 100000 := by
  unfold x86_exec_exit; rfl

/-- Already at the exit pc: the run is over, and the state is the answer. -/
@[simp] theorem x86_exec_go_exit_at {st : X86State} {code : Nat → UInt8} {exit : Nat} {fuel : Nat}
    (h_fuel : 0 < fuel) (h_rip : st.rip = exit) :
    x86_exec_go_exit st code exit fuel = some st := by
  cases fuel with
  | zero => omega
  | succ n => simp [x86_exec_go_exit, h_rip]

/-- One step short of the exit pc, with fuel to spare. -/
@[simp] theorem x86_exec_go_exit_step {st : X86State} {code : Nat → UInt8} {exit : Nat}
    {fuel : Nat} {st' : X86State}
    (h_fuel : 0 < fuel) (h_not_exit : st.rip ≠ exit)
    (h_step : x86_step st code = some st') :
    x86_exec_go_exit st code exit fuel = x86_exec_go_exit st' code exit (fuel - 1) := by
  cases fuel with
  | zero => omega
  | succ n => simp [x86_exec_go_exit, h_not_exit, h_step]

/-- A step the model cannot decode ends the run with nothing. -/
@[simp] theorem x86_exec_go_exit_stuck {st : X86State} {code : Nat → UInt8} {exit : Nat} {fuel : Nat}
    (h_fuel : 0 < fuel) (h_not_exit : st.rip ≠ exit) (h_none : x86_step st code = none) :
    x86_exec_go_exit st code exit fuel = none := by
  cases fuel with
  | zero => omega
  | succ n => simp [x86_exec_go_exit, h_not_exit, h_none]


/-!
## Call and return

The x86-64 half of the call semantics that `ProofLib`'s arm64 section gets from
`Callee`, and deliberately the same shape, so a reader who has one has both.

`x86_step_call_rel32` above already models a call faithfully — it pushes the
return address and jumps.  What was missing is the *pairing*: that the `ret`
which ends the callee pops exactly that word and lands exactly at the
instruction after the call.  Without that, a call is a memory write and a
branch with nothing connecting it to the matching `ret`, which is why
`bugs/OPEN_WORK.md` A1 calls this "real design work, not a wiring change" —
"a call has TWO successors and a memory write".

x86-64 pushes a return address where arm64 keeps it in `x30`, so a call frame is
a real memory object here and not a register.  That is the only structural
difference between the two architectures, and it is why this section has a
memory-separation lemma and the arm64 one has a `CalleeOk` predicate instead.
-/

/-- **The state a `call rel32` at `m` leaves behind when it branches to
    `m + 5 + off`.**  Named once for the same reason as arm64's
    `arm64_call_post`: the theorems below have to agree about "the post-call
    state", and writing the record update out three times is how two of them
    come to disagree. -/
def x86_call_post (s : X86State) (m : Nat) (off : Int) : X86State :=
  { s with
    rip := (Int.ofNat m + 5 + off).toNat,
    rsp := s.rsp - 8,
    mem := mem_write_bytes s.mem (s.rsp - 8).toNat (UInt64.ofNat (m + 5)) 8 }

@[simp] theorem x86_call_post_rsp (s : X86State) (m : Nat) (off : Int) :
    (x86_call_post s m off).rsp = s.rsp - 8 := rfl

@[simp] theorem x86_call_post_rip (s : X86State) (m : Nat) (off : Int) :
    (x86_call_post s m off).rip = (Int.ofNat m + 5 + off).toNat := rfl

/-- **The state the callee is entered in**: the post-call state with `rip` moved
    to the call's target.  Named so the round-trip theorem can name it inside a
    binder type, which a nested record update will not parse as. -/
def x86_at_target (s : X86State) (m : Nat) (off : Int) (target : Nat) : X86State :=
  { x86_call_post s m off with rip := target }

/-- **The state a `ret` leaves behind, given the state it was entered in.** -/
def x86_ret_post (s : X86State) : X86State :=
  { s with rip := (mem_read_bytes s.mem s.rsp.toNat 8).toNat, rsp := s.rsp + 8 }

@[simp] theorem x86_ret_post_rsp (s : X86State) : (x86_ret_post s).rsp = s.rsp + 8 := rfl

/-- **A call and its return are inverses, on the stack pointer.**  A `call
    rel32` at `m` moves `rsp` down by the width of the return address it
    pushed, and the `ret` that ends the callee moves it back up by exactly
    that, so the pair leaves the stack pointer where the call found it.

    The pairing of the push with the pop is the content, and it is what A1 says
    the x86-64 proof work is missing.

    **The `rip` half is deliberately not claimed, and it is worth being exact
    about why**, because a theorem that quietly stops at the register file is
    how the previous `DylibExport.Semantics` came to state `True`.  That the
    `ret` lands on `m + 5` reduces to

        mem_read_bytes (mem_write_bytes m a v 8) a 8 = v

    which is FALSE as a statement about a general width — at width 0 the read
    is 0 whatever `v` is — so it needs a mask to induct on at all, and the
    right statement is

        ∀ n m a v, mem_read_bytes (mem_write_bytes m a v n) a n = v &&& lowMask n

    with `lowMask 0 = 0` and `lowMask (k+1)` extending by one byte.  Its
    induction additionally needs the pointwise byte lemma (`mem_write_bytes m a
    v n i` inside `[a, a+n)` is byte `8*(i-a)` of `v`), because the tail of the
    step compares a `k`-write at `a+1` against a `k+1`-write at `a` and those
    agree everywhere except at `a`.  Neither lemma is in this file.

    That is **one medium induction in `mem`, not a design question**, and it is
    the whole of what stands between this section and a complete x86-64
    call/return round trip.  Nothing here needs it meanwhile: `hret` states what
    the `ret` read, and the separation theorem below is the fact that matters
    for combining a caller's and a callee's stack reasoning. -/
theorem x86_call_ret_balances_stack (s : X86State) (code : Nat → UInt8)
    (m target : Nat) (off : Int)
    (hcall : x86_step s code = some (x86_call_post s m off))
    (htarget : (Int.ofNat m + 5 + off).toNat = target)
    (hret : x86_step (x86_at_target s m off target) code
      = some (x86_ret_post (x86_at_target s m off target))) :
    (x86_ret_post (x86_at_target s m off target)).rsp = s.rsp := by
  simp [x86_ret_post, x86_at_target, x86_call_post, hcall, hret]

/-- **The return address is separated from the callee's frame.**  Any `w` bytes
    at or above `b`, where `b` is at or above the top of the pushed return
    address, are provably unaffected by the call.

    This is the separation fact A1 names, and it is what lets a caller's stack
    reasoning and a callee's stack reasoning be combined: the callee may write
    in its own frame without that being able to disturb the return address, and
    a proof reasoning about memory at or above the caller's `rsp` is reasoning
    about memory the call provably did not touch.

    Both sides are the library's existing `mem_read_bytes_write_above`; the
    content is the address arithmetic that puts the call's write strictly below
    `b`. -/
theorem x86_call_return_slot_separated (s : X86State) (code : Nat → UInt8)
    (m : Nat) (off : Int) (w b : Nat)
    (habove : (s.rsp - 8).toNat + 8 ≤ b) :
    mem_read_bytes (x86_call_post s m off).mem b w = mem_read_bytes s.mem b w := by
  simp only [x86_call_post]
  exact mem_read_bytes_write_above s.mem (s.rsp - 8).toNat (UInt64.ofNat (m + 5)) 8 w b habove

/-!
## The `rip` half of the call/return round trip

Everything above stops at the register file on purpose, and the docstring on
`x86_call_ret_balances_stack` says exactly what was missing: that a `ret` lands
on `m + 5` reduces to reading back what the `call` pushed, and that

    mem_read_bytes (mem_write_bytes m a v n) a n = v &&& lowMask n

is **false as a general-width claim** — at width 0 the read is 0 whatever `v`
is — so it needs a mask to induct on. This section supplies the mask, the
induction, and the theorem the docstring said was not in the file.
-/

/-- **The `n`-byte mask**: the low `8 * n` bits of a word, all ones.  Defined
    here rather than in `ProofLib.lean` because this is the only consumer, and
    the generalisation belongs with the proof that needs it. -/
def lowMask : Nat → UInt64
  | 0 => 0
  | k + 1 => (0xFF : UInt64) ||| (lowMask k <<< 8)

@[simp] theorem lowMask_eight : lowMask 8 = 0xFFFFFFFFFFFFFFFF := by native_decide

/-- **Writing the low byte at `a` disturbs no other address.**  A `k + 1`-byte
    write at `a` is a one-byte write at `a` followed by a `k`-byte write of the
    shifted value at `a + 1`, so every address other than `a` sees only the
    tail.  This is the pointwise lemma the `rip` induction needs, because the
    tail of the step compares a `k`-write at `a + 1` against a `k + 1`-write at
    `a` and the two agree everywhere except at `a`. -/
theorem mem_write_bytes_tail (m : Nat → UInt8) (a k i : Nat) (v : UInt64)
    (h : i ≠ a) :
    (mem_write_bytes m a v (k + 1)) i = (mem_write_bytes m (a + 1) (v >>> 8) k) i := by
  simp [mem_write_bytes, h]

/-- **Reads of `n` bytes depend only on memory over `[a, a + n)`.** -/
theorem mem_read_bytes_congr {m₁ m₂ : Nat → UInt8} {a n : Nat}
    (h : ∀ j, a ≤ j → j < a + n → m₁ j = m₂ j) :
    mem_read_bytes m₁ a n = mem_read_bytes m₂ a n := by
  induction n generalizing a with
  | zero => rfl
  | succ k ih =>
    show (m₁ a).toUInt64 ||| (mem_read_bytes m₁ (a + 1) k <<< 8)
        = (m₂ a).toUInt64 ||| (mem_read_bytes m₂ (a + 1) k <<< 8)
    have ha : m₁ a = m₂ a := h a (Nat.le_refl _) (by omega)
    have htail : mem_read_bytes m₁ (a + 1) k = mem_read_bytes m₂ (a + 1) k :=
      ih (fun j hj1 hj2 => h j (by omega) (by omega))
    rw [ha, htail]

/-- **Reading back an `n`-byte little-endian write returns the value, masked to
    the `n` bytes actually written.**  The masked form is the honest one: at
    `n = 0` nothing is written and nothing reads back, so the unmasked claim
    would be false exactly where the induction starts. -/
theorem mem_read_bytes_write_same (m : Nat → UInt8) (a : Nat) (v : UInt64) :
    ∀ n, mem_read_bytes (mem_write_bytes m a v n) a n = v &&& lowMask n := by
  intro n
  induction n generalizing m a v with
  | zero => simp [mem_read_bytes, lowMask]
  | succ k ih =>
    show (mem_write_bytes m a v (k + 1) a).toUInt64 |||
        (mem_read_bytes (mem_write_bytes m a v (k + 1)) (a + 1) k <<< 8)
        = v &&& lowMask (k + 1)
    have hself : (mem_write_bytes m a v (k + 1)) a = v.toUInt8 := by
      simp [mem_write_bytes]
    have htail : mem_read_bytes (mem_write_bytes m a v (k + 1)) (a + 1) k
                = mem_read_bytes (mem_write_bytes m (a + 1) (v >>> 8) k) (a + 1) k :=
      mem_read_bytes_congr (fun j _ _ => mem_write_bytes_tail m a k j v (by omega))
    rw [hself, htail, ih]
    simp only [lowMask]
    have htrunc : v.toUInt8.toUInt64 = v &&& (0xFF : UInt64) := by bv_decide
    rw [htrunc]
    bv_decide

/-- **A `ret` returns to the instruction after the `call` that pushed the
    address.**  This is the `rip` half, and with it the call/return round trip
    is complete: `x86_call_ret_balances_stack` has the stack pointer, this has
    the program counter.

    The bound on `m` is a hypothesis rather than a fact, deliberately.  A
    return address is a `UInt64`, so `UInt64.ofNat (m + 5)` is truncated and
    the conclusion needs `m + 5` to fit — which is true of every real
    instruction address and unprovable of a bare `Nat`.  Asserting it without
    the hypothesis would be the trap this file's own section warns about, so it
    is stated. -/
theorem x86_call_ret_restores_rip (s : X86State) (m : Nat) (off : Int) (target : Nat)
    (hm : m + 5 < 2 ^ 64) :
    (x86_ret_post (x86_at_target s m off target)).rip = m + 5 := by
  show (mem_read_bytes (x86_call_post s m off).mem
          (x86_call_post s m off).rsp.toNat 8).toNat = m + 5
  show (mem_read_bytes (mem_write_bytes s.mem (s.rsp - 8).toNat (UInt64.ofNat (m + 5)) 8)
          (s.rsp - 8).toNat 8).toNat = m + 5
  rw [mem_read_bytes_write_same, lowMask_eight]
  have hand : ∀ w : UInt64, w &&& 0xFFFFFFFFFFFFFFFF = w := by
    intro w; bv_decide
  rw [hand]
  simp; omega

/-- **Both halves at once**: a `call` and the `ret` that ends its callee leave
    the machine exactly where the call found it.

    It takes the same three step hypotheses as `x86_call_ret_balances_stack`
    rather than inventing them.  The first version of this theorem tried to
    discharge them with `rfl`, which cannot work: they say the `call` and the
    `ret` actually decoded, and that is a fact about the CODE, not a fact this
    section can produce.  Passing a dummy `code` would have made the whole
    statement vacuous -- a theorem about a machine that never ran -- which is
    the same disease as the old `Semantics`, one layer down. -/
theorem x86_call_ret_round_trip (s : X86State) (code : Nat → UInt8)
    (m target : Nat) (off : Int) (hm : m + 5 < 2 ^ 64)
    (hcall : x86_step s code = some (x86_call_post s m off))
    (htarget : (Int.ofNat m + 5 + off).toNat = target)
    (hret : x86_step (x86_at_target s m off target) code
      = some (x86_ret_post (x86_at_target s m off target))) :
    (x86_ret_post (x86_at_target s m off target)).rsp = s.rsp
      ∧ (x86_ret_post (x86_at_target s m off target)).rip = m + 5 :=
  ⟨x86_call_ret_balances_stack s code m target off hcall htarget hret,
   x86_call_ret_restores_rip s m off target hm⟩
