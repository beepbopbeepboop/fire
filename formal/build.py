"""formalbuild — formal arm64 codegen + Mach-O emission, selected by
`./fire.py formalbuild <file.mojo>`.

Pipeline:
    source → fire_compiler.py tokenize/parse (the real AST)
           → formal.arm64_codegen.ARM64Codegen (machine code)
           → formal.macho.build_macho (MH_EXECUTE Mach-O64 / ARM64)
           → formal.arm64_proof_gen.generate_arm64_proof (Lean 4, opt-in)

Unlike the toy formal tree (which had its own parser and mini-AST), this
path parses with fire_compiler — fire_compiler.py is the single source of
truth for the AST in this project. Proof generation consumes the same
fire AST via aliases (no AST-to-AST translation).
"""

import os
from types import SimpleNamespace

import fire_compiler as F
from formal.arm64_codegen import ARM64Codegen, CodegenError
from formal.macho import build_macho, compute_macho_got_addrs
from formal.macho_linker import EXTERN_ENTRYOFF, TEXT_BASE


class FormalBuildError(Exception):
    pass


def parse_module(source: str, filename: str = "<input>") -> list:
    from fire_compiler import py_tokenize, Parser
    return Parser(py_tokenize(source)).with_filename(filename).parse_module()


def _extract_functions(stmts: list) -> list:
    """Extract top-level FunctionDefs from a full module statement list.

    Imports, module-level assignments, structs, control flow, etc. are
    accepted and ignored here — the arm64 codegen only lowers FunctionDefs
    (ARM64Codegen.compile filters them). This lets Mojo's Python-superset
    surface (import os, from math import sqrt, x = 1, if __name__ == ...)
    parse and compile structurally without a hard toplevel gate.
    Returns the FunctionDef list with `main` first when present (the
    startup stub BLs functions[0])."""
    functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
    if not functions:
        raise FormalBuildError("no function definitions found")
    main = [f for f in functions if f.name == "main"]
    rest = [f for f in functions if f.name != "main"]
    return main + rest


def compile_formal(source_path: str, output: str = None,
                   test_input: int = 10, prove: bool = False) -> dict:
    """Compile `source_path` via the formal arm64 path to a Mach-O binary.

    output: destination path; defaults to <stem>.aout next to the source.
    test_input: value placed in X0 before the startup stub calls the entry
    function (formal's `-n`; forwarded as the entry's first argument).
    prove: also emit <stem>_proof.lean next to the binary (Lean 4 static
    typecheck target; does not execute the binary).
    """
    try:
        with open(source_path) as f:
            source = f.read()
    except OSError as e:
        raise FormalBuildError(f"cannot read {source_path}: {e}")

    try:
        stmts = parse_module(source, filename=source_path)
    except SyntaxError as e:
        raise FormalBuildError(f"parse error: {e}")

    try:
        # Structural acceptance: only FunctionDefs matter for codegen;
        # imports / module-level stmts are fine (filtered here + in codegen).
        functions = _extract_functions(stmts)
    except FormalBuildError:
        raise

    # Rebuild a statement list with main-first ordering for the codegen.
    ordered = functions

    codegen = ARM64Codegen(test_input=test_input)
    try:
        has_extern_hint = True  # base chosen after we know external_syms
        # First pass: emit with the extern-capable base so relative branches
        # and string ADRP relocations are computed against the address the
        # code will actually live at once we know whether stubs are needed.
        # We don't know external_syms until after compile(), so compile once
        # at the extern base if anything turns out external and re-emit.
        base_extern = TEXT_BASE + EXTERN_ENTRYOFF
        base_noextern = TEXT_BASE + 480  # 32-byte header + 448 sizeofcmds
        code, info = codegen.compile(ordered, base_addr=base_noextern)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # Re-emit at the extern entry base (layout differs).
            codegen = ARM64Codegen(test_input=test_input)
            code, info = codegen.compile(ordered, base_addr=base_extern)
            external_syms = info.get("external_syms") or []
            stub_addrs = compute_macho_got_addrs(
                len(code), external_syms, vaddr=info["base_addr"])
            codegen.asm.resolve_extern(stub_addrs)
            code = bytes(codegen.asm.sections["text"])
    except CodegenError as e:
        raise FormalBuildError(str(e))

    binary = build_macho(code, entry=info["base_addr"],
                         external_syms=external_syms)

    if output is None:
        stem = os.path.splitext(os.path.basename(source_path))[0] or "a.out"
        output = os.path.join(os.path.dirname(os.path.abspath(source_path)),
                              stem + ".aout")
    with open(output, "wb") as f:
        f.write(binary)
    os.chmod(output, 0o755)

    result = {
        "path": output,
        "code": code,
        "binary": binary,
        "info": info,
        "backend": "arm64/macho",
    }

    if prove:
        # prog is only ever read (functions + externs); proofgen never
        # constructs a Program. fire has no ExternFunction nodes on this
        # path — pass [] and let _gen_extern_test's `ret_type_of.get`
        # default handle any recorded extern_calls.
        from formal.arm64_proof_gen import generate_arm64_proof
        prog = SimpleNamespace(functions=ordered, externs=[])
        proof = generate_arm64_proof(prog, code, info)
        proof_path = os.path.splitext(output)[0] + "_proof.lean"
        if os.path.exists(proof_path):
            os.chmod(proof_path, 0o644)  # u+w so overwrite works
        with open(proof_path, "w") as f:
            f.write(proof)
        os.chmod(proof_path, 0o444)  # a-w, same as formal's Makefile
        result["proof_path"] = proof_path

    return result
