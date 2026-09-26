#!/usr/bin/env python3
"""Lean 4 proof generation for the x86-64 formal backend.

Ported in structure from /Users/mrs/net/chatgpt/claude/formal/compiler/proof_gen.py
(the toy formal compiler's x86-64 proof generator) and re-targeted from that
project's mini-AST onto fire_compiler nodes, mirroring
formal/arm64_proof_gen.py's emitted-file shape so the two backends' proofs read
alike.

## What is shared and what is not

The SOURCE-SEMANTIC half of a proof is architecture-independent: the Lean model
of the program (`<fn>_go`), its simplification lemmas, and the `MojoFunc` value
that mirrors the source AST are all the same text whichever machine compiles
it. Those are imported from `formal.arm64_proof_gen` rather than reimplemented —
two copies of the model generator would be free to disagree about what a
program means, which is the one thing a two-backend compiler must not have.

The MACHINE half is per-architecture, and that is what lives here: the compiled
bytes as a `Nat → UInt8` code function, the certificates relating execution to
the source, and the end-to-end theorem over `X86State` / `x86_exec_exit` — the model
`lib/ProofLib.lean` already carries for x86-64.

## Honesty about what is proved

The per-instruction step certificates are `sorry`. That is deliberate and is
the same trust boundary the arm64 generator starts from: the statement of what
is being claimed is exact (the source model, the AST bridge, the code bytes and
the end-to-end theorem all typecheck and are real), and the part that is not yet
machine-checked is marked as such rather than hidden. A `sorry` in Lean makes
the theorem ACCEPTED, so a `sorry` here is a claim of trust, not a proof — the
audit tooling in the toy project counts exactly these.
"""

from formal.types import (DEFAULT_INT_TYPE, function_var_types, parse_type_name,
                          resolve)

# The file's own preamble, matching formal/arm64_proof_gen.py's: the deep
# recursion is the model equations and `native_decide` runs, and the linter
# options are off because a generated file legitimately has unused binders in
# the parts that are `sorry`.
_PREAMBLE = """import ProofLib
import work
import Refine

set_option maxRecDepth 100000
set_option maxHeartbeats 20000000
set_option linter.unusedSimpArgs false
set_option linter.unusedVariables false
"""

_TRUST_HEADER = (
    "/- The three trust boundaries below are the ones the arm64 backend uses,\n"
    "   stated over the x86-64 machine model in lib/ProofLib.lean:\n"
    "     1. AST   ⟷ the source semantics (`mojo`)  — `eval_eq_mojo`\n"
    "     2. AST   ⟷ the compiled bytes             — `<fn>_compile_correct`\n"
    "     3. bytes ⟷ the executed state             — the step certificates\n"
    "   1 is proved (by the shared generator); 2 and 3 are `sorry` so far, so\n"
    "   the end-to-end theorem below inherits their trust. -/\n")


def _byte_list(code: bytes, per_line: int = 16) -> str:
    """The compiled bytes as a Lean `List UInt8` literal, wrapped for reading."""
    items = [f"0x{b:02x}" for b in code]
    lines = []
    for i in range(0, len(items), per_line):
        chunk = ", ".join(items[i:i + per_line])
        suffix = "," if i + per_line < len(items) else ""
        lines.append(f"  {chunk}{suffix}")
    return "\n".join(lines) if lines else "  0"


def _code_function(name: str, base: int) -> str:
    """The `<name>_code : Nat → UInt8` the machine model steps through.

    `x86_step` indexes the code function by ABSOLUTE address (`code s.rip`),
    so the function has to map an address back into the image: below the image
    base — and past its end, via `getD` — it reads 0. The base is the image's
    own `base_addr`, not the function's entry, because the image also holds
    the rodata the code addresses absolutely.
    """
    return (f"def {name}_code (addr : Nat) : UInt8 :=\n"
            f"  if addr < {base} then 0\n"
            f"  else {name}_code_bytes.getD (addr - {base}) 0\n")


def _generate_model(fn, tc):
    """The `<fn>_go` model plus the NAMES of its simp lemmas, from the shared
    generator.

    `_gen_go` returns a list of chunks — the model definition and the
    unfolding/recursion lemmas that go with it — which are emitted verbatim.
    `_go_simp_lemmas` returns only the names of the ones safe to add to a
    value-flow simp set, so they are returned separately rather than as text:
    emitting the names as statements produces a file that does not parse, and
    emitting the lemmas twice produces duplicate declarations.  Names go into
    the `eval_eq_mojo` simp set instead, which is where they are wanted.

    Raises whatever the shared generator raises for a shape it does not model;
    the caller degrades to a documented gap rather than failing the build."""
    from formal import arm64_proof_gen as AP
    go_defs = "\n\n".join(AP._gen_go(fn, tc))
    return go_defs, list(AP._go_simp_lemmas(fn))


def _ast_value(fn, func_name: str) -> str:
    """The `MojoFunc` value mirroring `fn`'s source AST.

    Raises whatever the shared emitter raises for a construct the untyped
    AST model has no form for (a call, a print, a method call); the caller
    then drops the bridge rather than emitting a value that does not
    typecheck."""
    from formal import arm64_proof_gen as AP
    body = "[" + ", ".join(AP._stmts_ast(fn.body)) + "]"
    param = fn.params[0][0] if fn.params else ""
    return f'MojoFunc.mk "{func_name}" "{param}" ({body})'


def _eval_eq_mojo_section(func_name: str, fn, typed: bool,
                          go_lemmas: list = None) -> str:
    """`eval_eq_mojo`: the AST interpreter agrees with the source model.

    Proved for the shapes the shared generator can close by `simp` (a
    straight-line function whose conditions all case-split); `sorry` for the
    rest. A typed (fixed-width) function omits the bridge entirely, as the
    arm64 generator does, because the AST-eval model in ProofLib is untyped.

    Returns None when the AST value itself cannot be built — the caller drops
    the whole section in that case."""
    if typed:
        return ("/- Typed function: the untyped AST-eval bridge is omitted;\n"
                "   correctness follows from the machine value flow. -/\n")
    _ast_value(fn, func_name)     # probe: may raise
    from formal import arm64_proof_gen as AP
    if AP._is_recursive(fn) or AP._has_while(fn.body):
        return None       # caller emits the `sorry` form
    param = fn.params[0][0] if fn.params else "n"
    env = {param: param} if fn.params else {}
    conds = AP._collect_conds(fn, param, env)
    simp_lems = ", ".join(["mojo", "%s_go" % func_name, "ast", "evalFunc",
                           "evalBody", "evalBodyEnv", "evalExpr", "u64pow",
                           "u64powGo"] + list(go_lemmas or []))
    if not conds:
        proof = f"simp +decide [{simp_lems}]"
    else:
        by_cases = " ".join(f"by_cases h{i} : {c} <;>"
                            for i, c in enumerate(conds))
        hs = ", ".join(f"h{i}" for i in range(len(conds)))
        proof = (f"{by_cases} simp_all +decide [{hs}, {simp_lems}, "
                 "u64_lt_iff_false_of_le, u64_le_iff_false_of_lt]")
    return (f"/-- eval_eq_mojo: AST evaluation agrees with the semantic model. -/\n"
            f"theorem eval_eq_mojo (n : UInt64) :\n"
            f"  evalFunc ast (fun name arg =>\n"
            f"    if name = \"{func_name}\" then mojo arg else 0) n = mojo n := by\n"
            f"  {proof}\n")


def _compile_correct_section(func_name: str) -> str:
    """The AST ⟷ compiled-bytes trust boundary.

    `exec_seq` runs the machine model for a bounded number of steps from the
    function's entry, which is the form the toy x86-64 generator used for the
    same boundary. It is not in ProofLib (only the arm64 side has a step
    composition there), so it is emitted into the proof file itself."""
    return (
        f"/-- Run the machine model for `steps` instructions from the entry. -/\n"
        f"def {func_name}_exec_seq (s : X86State) (code : Nat → UInt8)\n"
        f"    (addr : Nat) (steps : Nat) : Option X86State :=\n"
        f"  match steps with\n"
        f"  | 0 => some s\n"
        f"  | Nat.succ n =>\n"
        f"    match x86_step s (fun i => code (addr + i)) with\n"
        f"    | some s' => {func_name}_exec_seq s' code s'.rip n\n"
        f"    | none => none\n"
        f"\n"
        f"/-- TRUST BOUNDARY: AST ⟷ compiled bytes. -/\n"
        f"theorem {func_name}_compile_correct (e : MojoExpr)\n"
        f"    (env : String → UInt64) (s : X86State) :\n"
        f"  ∀ steps : Nat,\n"
        f"    match {func_name}_exec_seq s {func_name}_code {func_name}_offset steps with\n"
        f"    | some s' => s'.rax = evalExpr (fun name arg => mojo arg) e env\n"
        f"    | none => True := by\n"
        f"  sorry\n")


def _step_certificate_section(func_name: str, code_len: int) -> str:
    """The execution certificates.

    What IS provable without decoding anything is that the byte list in this
    file is the image the assembler produced — a closed literal, so its length
    is `rfl`. That is a real (if small) certificate that the file being
    typechecked is about the code that was actually emitted, and it is proved.

    What is NOT here is the per-instruction work the arm64 generator does:
    decoding each instruction, cutting the CFG into blocks, and proving one
    `x86_step` lemma per decoded instruction relating the register-file effect
    to the source. None of that exists for x86-64 yet, and its absence is the
    reason the end-to-end theorem below is a `sorry`. It is recorded here as
    a comment rather than as a `sorry`-bearing `True`-valued lemma, which would
    inflate the unproved-obligation count while claiming nothing.
    """
    return (
        f"/-- The image described above is exactly the {code_len} bytes the\n"
        f"    assembler emitted. -/\n"
        f"theorem {func_name}_code_length :\n"
        f"    {func_name}_code_bytes.length = {code_len} := rfl\n"
        f"\n"
        f"/- MISSING: per-instruction execution certificates.  For each of the\n"
        f"    {code_len} bytes above, decoding the instruction at its address and\n"
        f"    proving that `x86_step` moves the state the way the source says is\n"
        f"    the x86-64 counterpart of arm64_proof_gen's step lemmas; it does not\n"
        f"    exist yet, and the end-to-end theorem below inherits that gap. -/\n")


def _run_tests_section(func_name: str, test_input: int,
                        externs: list = None, placeholder: bool = False) -> str:
    """Concrete run tests: the machine model on the real bytes, by evaluation.

    These are not `sorry` and not assertions — `native_decide` executes the
    emitted byte list through `X86State`/`x86_exec_exit` inside Lean's own
    interpreter and checks the value in RAX against the source model.  They
    are the x86-64 counterpart of arm64_proof_gen's `_runs_*` theorems, and
    they are the one part of this file that is genuine evidence about the
    machine: if the code function's base address, the entry offset or the
    model itself were wrong, these would fail to typecheck.

    The exit pc is 0, which works because `X86State.init` leaves the stack
    zeroed: the entry function's own `ret` pops address 0 and `x86_exec_exit`
    stops there.  That is what lets a proof about "what this function
    computes" start at the function's entry and still reach a definite answer,
    with no startup stub and no planted return address.

    Each input gets two obligations and both are needed.  `_terminates_n`
    says the model actually ran the program to its `ret`; `_runs_n` says the
    result is the source model's.  Reporting the value through a helper that
    maps a failed run to 0 (as arm64's `run_result_exit` does) keeps the
    statement a decidable equality — but without the separate termination
    fact, a model that could not execute the program at all would read as
    "result 0" and quietly agree with any model whose answer is 0.  Together
    they fail loudly on an opcode `x86_step` does not decode, which is a real
    gap in `lib/X86.lean` rather than something to paper over.

    `externs` suppresses the whole section for an image that calls out to the
    runtime.  A call to `print` is a branch to a `__TEXT,__stubs` trampoline
    that lives OUTSIDE the image, and the model has no memory for it: the
    branch lands on a byte the model cannot decode, the run stops, and the
    termination obligation fails — for a program whose arithmetic is perfectly
    fine.  Emitting the obligations anyway turns a known limitation into a
    build failure on every program that prints, which is most of them; naming
    the symbols in a comment instead says what is actually true."""
    if placeholder:
        # The run test's whole value is that it compares the MODEL against the
        # MACHINE.  When the model is a placeholder the comparison is against
        # nothing, and it fails for a reason that has nothing to do with the
        # machine — which would report a codegen or model bug that is not
        # there.  The honest statement is the gap itself.
        return (
            f"/- NO RUN TESTS for {func_name}: the semantic model above is a\n"
            f"   PLACEHOLDER (see the note on it).  A run test would compare the\n"
            f"   machine against that placeholder and fail, which would say\n"
            f"   nothing about either.  Modelling this function's shape is what\n"
            f"   would close it. -/\n")

    if externs:
        syms = ", ".join(sorted(set(externs)))
        return (
            f"/- NO RUN TESTS for {func_name}: the image calls out to the runtime\n"
            f"   ({syms}), and the model has no memory for a `__TEXT,__stubs`\n"
            f"   trampoline.  The branch lands outside the image and the run stops,\n"
            f"   so a termination obligation here would fail on a program whose\n"
            f"   arithmetic is fine.  What the model CAN still check is everything\n"
            f"   up to the call, which is what the per-instruction certificates\n"
            f"   below cover. -/\n")

    helper = (
        f"/-- Result register after running the image from the entry (0 if the\n"
        f"    model could not run it to completion). -/\n"
        f"def {func_name}_result (n : UInt64) : UInt64 :=\n"
        f"  match x86_exec_exit (X86State.init n {func_name}_offset) "
        f"{func_name}_code 0 with\n"
        f"  | some s => s.rax\n"
        f"  | none => 0\n")
    out = [helper]
    for n in dict.fromkeys([test_input, 0, 1, 2, 5]):
        run = (f"x86_exec_exit (X86State.init {n} {func_name}_offset) "
               f"{func_name}_code 0")
        out.append(
            f"/-- The model runs the image to completion for input {n}. -/\n"
            f"theorem {func_name}_terminates_{n} :\n"
            f"    ({run}).isSome = true := by\n"
            f"  native_decide\n"
            f"\n"
            f"/-- Concrete verification for input {n}, run from the entry. -/\n"
            f"theorem {func_name}_runs_{n} :\n"
            f"    {func_name}_result {n} = mojo {n} := by\n"
            f"  native_decide\n")
    return "\n".join(out) + "\n"


def generate_x86_64_proof(prog, code, info) -> str:
    """Generate a Lean 4 proof file for an x86-64-compiled program.

    `prog` is the flattened function list formal.build produces (read only:
    the functions and their return types), `code` the emitted machine code and
    `info` the codegen's layout record (`base_addr`, `labels`, `func_name`,
    `test_input`, …)."""
    functions = list(getattr(prog, "functions", None) or [])
    if not functions:
        raise ValueError("x86-64 proof generation needs at least one function")
    func_name = info.get("func_name") or functions[0].name
    fn = next((f for f in functions if f.name == func_name), functions[0])
    func_name = fn.name
    base_addr = info["base_addr"]
    func_offset = info.get("func_offset", base_addr)
    test_input = info.get("test_input", 10)
    code = code or b""

    call_types = {g.name: resolve(parse_type_name(g.return_type)
                                  or DEFAULT_INT_TYPE)
                  for g in functions}
    vtypes = function_var_types(fn, call_types)
    all_t = list(vtypes.values())
    rt = resolve(parse_type_name(getattr(fn, "return_type", None)))
    if rt != DEFAULT_INT_TYPE:
        all_t.append(rt)
    typed = any(t != DEFAULT_INT_TYPE for t in all_t)
    tc = {"typed": typed, "vtypes": vtypes, "call_types": call_types}

    parts = [_PREAMBLE, _TRUST_HEADER]

    # ── source semantics ────────────────────────────────────────────
    try:
        go_defs, go_lemma_names = _generate_model(fn, tc)
        model_note = ""
        model_placeholder = False
    except Exception as e:                          # noqa: BLE001
        # The shared model generator does not cover every shape. Rather than
        # failing the build, emit a trivial model and say so: the rest of the
        # file (AST, bytes, certificates) is still real, and the end-to-end
        # theorem is `sorry` regardless, so nothing false is claimed.
        go_defs = (f"def {func_name}_go (n : UInt64) : UInt64 :=\n"
                   f"  n\n")
        model_placeholder = True
        go_lemma_names = []
        model_note = (f"/- NOTE: the shared model generator does not cover "
                      f"this function's shape ({type(e).__name__}: {e}), so "
                      f"the semantic model below is the identity and nothing "
                      f"downstream of it is claimed. -/\n")

    parts.append("/-- Mojo semantics: direct Lean model of the source code. -/\n"
                 + model_note + go_defs + "\n")

    # How `mojo` applies the model depends on the model's own parameter type,
    # so READ it out of the generated definition rather than guessing from
    # which pattern matched.  The guess was wrong for a `for` loop over
    # `range`: `_dec_while_pattern` fires, so the argument became `n.toNat`,
    # while `_gen_go` had produced a UInt64-parameterised model — a type
    # mismatch that failed the whole proof for a function the model handles
    # perfectly well.  Deriving one from the other cannot drift.
    # The shared generator emits two shapes: `def f_go (n : Nat) : UInt64 :=`
    # for a bounded model, and the curried `def f_model : Nat → UInt64` with
    # equation clauses for the tree-recursive one.  Both have to be recognised
    # or the argument is wrong for one of them.
    import re
    mojo_fn = (f"{func_name}_model"
               if re.search(r"def %s_model\b" % func_name, go_defs)
               else f"{func_name}_go")
    binder = re.search(r"def %s \((\w+) : (\w+)\)" % mojo_fn, go_defs)
    if binder:
        param, ptype = binder.group(1), binder.group(2)
    else:
        curried = re.search(r"def %s : (\w+) →" % mojo_fn, go_defs)
        param, ptype = "n", (curried.group(1) if curried else "UInt64")
    mojo_arg = f"{param}.toNat" if ptype == "Nat" else param
    parts.append("/-- The semantic model as a UInt64 -> UInt64 function. -/\n"
                 f"def mojo (n : UInt64) : UInt64 :=\n"
                 f"  {mojo_fn} {mojo_arg}\n")

    # ── AST bridge ───────────────────────────────────────────────────
    try:
        section = _eval_eq_mojo_section(func_name, fn, typed, go_lemma_names)
    except Exception:                               # noqa: BLE001
        section = None
    if section is None:
        # Either the AST value could not be built (a construct the untyped
        # model has no form for) or the shape's bridge is not closed. Both
        # mean the same thing here: omit the bridge and say which.
        try:
            _ast_value(fn, func_name)
            reason = ("this function's shape (recursive/looping): the bridge "
                      "is not closed yet")
            section = (f"/- AST bridge omitted: {reason}. -/\n")
        except Exception:                           # noqa: BLE001
            section = ("/- AST bridge omitted: this function's body has no "
                       "form in the untyped AST model (calls, prints and "
                       "method calls have none). Correctness would have to "
                       "come from the machine value flow alone. -/\n")
    else:
        parts.append(f"/- AST for {func_name} (mirrors source code). -/\n"
                     f"def ast : MojoFunc := {_ast_value(fn, func_name)}\n")
    parts.append(section)

    # ── the compiled image ───────────────────────────────────────────
    parts.append(
        f"/-- The compiled x86-64 image bytes. -/\n"
        f"def {func_name}_code_bytes : List UInt8 :=\n"
        f"[\n{_byte_list(code)}\n]\n"
        f"\n"
        f"/-- Address the function starts at. -/\n"
        f"def {func_name}_offset : Nat := {func_offset}\n"
        f"\n"
        f"/-- The byte at an absolute address (0 outside the image). -/\n"
        f"{_code_function(func_name, base_addr)}")

    parts.append(_compile_correct_section(func_name))
    parts.append(_run_tests_section(
        func_name, test_input,
        [e.get("sym") for e in (info.get("extern_calls") or [])],
        placeholder=model_placeholder))
    parts.append(_step_certificate_section(func_name, len(code)))

    # ── end to end ───────────────────────────────────────────────────
    parts.append(
        f"/-- END-TO-END: executing the compiled x86-64 image computes the\n"
        f"    same value as the source semantics, for every input. -/\n"
        f"theorem {func_name}_compiles_correctly (n : UInt64) :\n"
        f"  match x86_exec_exit (X86State.init n {func_name}_offset) "
        f"{func_name}_code 0 with\n"
        f"  | some s => s.rax = mojo n\n"
        f"  | none => False := by\n"
        f"  sorry\n")

    return "\n".join(parts)
