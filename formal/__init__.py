"""Formal arm64 codegen + Mach-O path ported from the toy proof compiler
(/Users/mrs/net/chatgpt/claude/formal), re-targeted onto fire_compiler's
AST (fire_compiler.py is the single source of truth — no toy AST, no
AST-to-AST conversion). Proof generation lives in formal/arm64_proof_gen.py
and is emitted by formal/build.py when prove=True (`fire.py build --formal`)."""
