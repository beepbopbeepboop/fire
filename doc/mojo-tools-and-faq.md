# Mojo Tools and FAQ

Source: https://docs.modular.com/mojo/tools/testing/
        https://docs.modular.com/mojo/tools/compilation/
        https://docs.modular.com/mojo/faq/

---

## Testing

Source: https://docs.modular.com/mojo/tools/testing/

**Note**: `mojo test` was deprecated October 31, 2025. Use `TestSuite` instead.

### Quick Start

```mojo
# test_quickstart.mojo
from std.testing import assert_equal, TestSuite

def inc(n: Int) -> Int:
    return n + 1

def test_inc_zero() raises:
    assert_equal(inc(0), 0)  # intentional failure example

def test_inc_one() raises:
    assert_equal(inc(1), 2)

def main() raises:
    TestSuite.discover_tests[__functions_in_module()]().run()
```

Run with:
```bash
mojo run test_quickstart.mojo
```

### Test Function Requirements

- Name starts with `test_`
- Accepts no arguments
- Returns `None`
- Raises errors to indicate failure
- Defined at module scope (not as struct methods)

When an assertion raises, the function exits immediately (remaining assertions skipped).

### Assertion Functions

| Function | Description |
|----------|-------------|
| `assert_true(val)` | Validates `True` |
| `assert_false(val)` | Validates `False` |
| `assert_equal(a, b)` | Validates `a == b` |
| `assert_not_equal(a, b)` | Validates `a != b` |
| `assert_almost_equal(a, b, atol=...)` | Floating-point equality within tolerance |

All accept optional `msg` parameter.

**Floating-point example**:
```mojo
result = 10 / 3
assert_almost_equal(result, 3.33, atol=0.001, msg="close but no cigar")
```

**Error assertion**:
```mojo
def inc(n: Int) raises -> Int:
    if n == Int.MAX:
        raise Error("inc overflow")
    return n + 1

with assert_raises():
    _ = inc(Int.MAX)

with assert_raises(contains="required"):
    raise Error("missing required argument")
```

### Full Test File Structure

```mojo
# test_my_module.mojo
from my_target_module import convert_input, validate_input
from std.testing import assert_equal, assert_false, assert_raises, assert_true, TestSuite

def test_validate_input() raises:
    assert_true(validate_input("good"), msg="'good' should be valid input")
    assert_false(validate_input("bad"), msg="'bad' should be invalid input")

def test_convert_input() raises:
    assert_equal(convert_input("input1"), "output1")
    assert_equal(convert_input("input2"), "output2")

def test_convert_input_error() raises:
    with assert_raises():
        _ = convert_input("garbage")

def main() raises:
    TestSuite.discover_tests[__functions_in_module()]().run()
```

`__functions_in_module()` is a compiler intrinsic that provides all module functions; `discover_tests()` filters for `test_` prefixed functions.

---

## Compilation Targets

Source: https://docs.modular.com/mojo/tools/compilation/

Mojo compiles for a range of targets: local machine, other CPUs, operating systems, and GPUs.

### Query System and Targets

```bash
mojo build --print-effective-target       # full target config for your system
mojo build --print-supported-targets      # architectures the compiler can target
mojo build --print-supported-cpus --target-triple=aarch64-apple-macosx
mojo build --print-supported-accelerators # GPU and accelerator architectures
```

### Target Description

Four key details:
- **Architecture**: base instruction set (x86-64, AArch64)
- **CPU model**: processor-specific behavior and instruction extensions
- **Feature set**: individual hardware capabilities (AVX-512, Neon)
- **Accelerator**: GPU or other accelerator for device code

**Target triple** format: `arch-vendor-os` (e.g., `x86_64-unknown-linux-gnu`, `aarch64-apple-macosx`)

### Mojo Target Flags

| Flag | Purpose |
|------|---------|
| `--target-triple` | Platform (arch + vendor + OS) |
| `--target-cpu` | Specific processor model |
| `--target-features` | Individual feature toggles |
| `--target-accelerator` | GPU or accelerator architecture |

```bash
mojo build --target-triple aarch64-unknown-linux-gnu \
           --target-cpu cortex-a72 \
           --emit object -o myapp.o myapp.mojo

mojo build --target-triple x86_64-unknown-linux-gnu \
           --target-cpu x86-64-v3 \
           --target-features "+avx512f" \
           --emit object -o myapp.o myapp.mojo
```

### GCC/Clang-Compatible Flags

| Flag | Purpose |
|------|---------|
| `--march` | Architecture or CPU subtype |
| `--mcpu` | CPU model (sets architecture and tuning) |
| `--mtune` | Optimization hint for specific processor |

```bash
mojo build --target-triple x86_64-unknown-linux-gnu \
           --mcpu=haswell \
           --emit object -o myapp.o myapp.mojo
```

**Do NOT mix flag families** — using `--target-cpu` with `--march` produces an error.

Shared flags that work with both families: `--target-triple`, `--target-accelerator`

### GPU and Accelerator Targets

```bash
mojo build --target-accelerator=sm_90 myapp.mojo          # NVIDIA H100
mojo build --target-accelerator=nvidia:sm_90 myapp.mojo
mojo build --target-accelerator=amdgpu:gfx942 myapp.mojo  # AMD MI300X
```

`--emit asm` with GPU targets produces separate files: `.ptx` (NVIDIA), `.amdgcn` (AMD), `.ll` (Metal).

### Emit Options

| Value | Output | Notes |
|-------|--------|-------|
| `exe` (default) | Executable binary | Native only |
| `shared-lib` | Shared library | Native only |
| `object` | Object file | Cross-compilation supported |
| `llvm` | Unoptimized LLVM IR | Cross-compilation supported |
| `llvm-bitcode` | Unoptimized LLVM IR bitcode | Cross-compilation supported |
| `asm` | Assembly (+ GPU sidecars) | Cross-compilation supported |

**Note**: `--emit exe` and `--emit shared-lib` fail at link step when cross-compiling. Generate an object file and link with a target-platform toolchain instead.

**Cross-compiled binaries do not include Python packages, C libraries, or Modular runtime libraries** — these must exist in the target environment.

---

## Frequently Asked Questions

Source: https://docs.modular.com/mojo/faq/

### Motivation

**Why did Modular build Mojo?**  
Internal challenges with the Modular Platform required a flexible, scalable programming model targeting CPUs, GPUs, AI accelerators, and heterogeneous systems.

**What problems does Mojo solve?**  
Merges Python's accessibility with systems programming capabilities. MLIR foundation enables scaling to exotic hardware. Caching and distributed compilation are core features. Aims to unify hybrid packages in the Python ecosystem.

**Why build on Python?**  
Python dominates AI research. Clean syntax and massive library ecosystem. Meets developers where they already work.

**Why not enhance CPython?**  
Python lacks systems programming features. Hybrid libraries (NumPy, PyTorch) require deep CPython expertise and C/C++. Mojo's architecture fundamentally differs from what CPython can support.

### Functionality

**Is Mojo interpreted or compiled?**  
Compiled. `mojo build` performs ahead-of-time compilation. `mojo run` performs just-in-time compilation.

**What are the benefits of MLIR?**  
Flexible compiler infrastructure with progressive hardware lowering. Excels at domain-specific compilers for unconventional hardware — quantum, FPGAs, AI ASICs, custom silicon. Mojo is the world's first language built from the ground up with MLIR design principles.

**Is Mojo only for AI?**  
No. While initially focused on AI, it aims to be general-purpose. Current applications include HPC, data transformations, pre/post processing.

**Does Mojo support distributed execution?**  
Not independently. Operates within the Modular Platform for runtime and graph-level transformations.

**C/C++ interoperability?**  
On the roadmap, leveraging Mojo's similarity to C/C++ type systems.

### Performance

**AI benchmarks?**  
Mojo is general-purpose; AI benchmarks depend on framework components. See the matrix multiplication blog post and MAX GPU performance measurement blog at modular.com.

### Mojo SDK

**What's included in the `mojo` package?**
- Mojo CLI with compiler
- Standard library
- Python package
- Language server (LSP)
- Debugger (LLDB)
- Code formatter
- REPL

**`mojo-compiler` package** (production environments):
- Mojo CLI with compiler
- Standard library
- Python package

**Supported operating systems**: Mac and Linux.

**IDE Integration**: Official VS Code extension via VS Code Marketplace and Open VSX Registry. Supports syntax highlighting, code completion, formatting, hover. Includes remote-ssh and dev container support.

**Telemetry**: Limited. Only crash reports (OS + version) and LSP latency metrics. No source code, keystrokes, or user data collected.

### Versioning

**Is Mojo stable?**  
Pre-1.0, early development. Source stability not guaranteed. Check roadmap at docs.modular.com/mojo/roadmap/.

**How often are releases?**  
Regular updates with nightly builds almost daily. Join Mojo Discord (discord.gg/modular) for notifications.

### Open Source

**Will Mojo be open-sourced?**  
Yes, planned for 2026. Internal architecture maturation continues first.

**Why not develop in the open from the start?**  
Complexity requires focused engineering. Follows practices of LLVM, Clang, Swift, MLIR — all eventually open-sourced.
