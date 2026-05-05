# Bootstrap Architecture

## Three Stages

**Stage 1: Python Interpreter**
- Foundation: Python
- Command: `mojo.py --dump-all mojo.mojo`

**Stage 2: Mojo Interpreter (Self-Hosting)**
- Foundation: Stage 1
- Command: `mojo.py mojo.mojo --dump-all mojo.mojo`

**Stage 3: Verification (Determinism)**
- Foundation: Stage 2
- Command: `mojo.py mojo.mojo mojo.mojo --dump-all mojo.mojo`

## Success Criteria

- Stage1 output ≡ Stage2 output
- Stage2 output ≡ Stage3 output
- All three stages produce identical bytes
