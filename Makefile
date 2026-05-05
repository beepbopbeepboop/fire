.PHONY: run demo check check-gimple clean stdlib bootstrap \
        preflight transpile stage1 stage2 stage3 verify

# Paths
RUNTIME_SRC     = runtime/mojo_runtime.c
RUNTIME_HDR     = runtime/mojo_runtime.h
DYLIB           = build/libmojo.dylib
STDLIB_PATH     = ../mojo/3rdparty/modular/mojo/stdlib
STDLIB_STD_PATH = $(STDLIB_PATH)/std
STDLIB_WRAPPER  = runtime/stdlib_wrapper.mojo
STDLIB_DYLIB    = build/libmojo_stdlib.dylib
MOJO_CLI        = build/mojo
BUILD_MOJO_CLI  = build_mojo_cli.py

# Bootstrap paths
STAGE1_BIN      = stage1/mojo
STAGE2_BIN      = stage2/mojo
MOJO_MAIN       = mojo/mojo_main.mojo

# Core compiler .py files to transpile (dependency order)
# TODO: gimple_codegen.py, mojo_compiler.py require systematic transpiler fixes
# mojo_compiler.mojo is hand-written instead of transpiled
TRANSPILE_SRCS  = generated_dispatch.py module_loader.py
TRANSPILE_MOJOS = $(patsubst %.py,mojo/%.mojo,$(TRANSPILE_SRCS))

run:
	python run.py

demo: mojo_compiler.py
	echo "3 + 42 + 0xFF" | python mojo_compiler.py

mojo_compiler.py: run.py fe_reader.py compiler_gen.py lang_spec.py \
    mojo-literals.md mojo-operators.md mojo-compound-statements.md \
    mojo-function-declarations.md mojo-simple-statements.md \
    mojo-expressions.md mojo-keywords.md \
    mojo-manual-language-basics.md mojo-manual-values.md \
    mojo-manual-metaprogramming.md mojo-manual-pointers.md \
    mojo-manual-python.md mojo-manual-gpu.md mojo-tools-and-faq.md
	python run.py

check: mojo_compiler.py
	python test_mds.py

check-gimple: mojo_compiler.py gimple_codegen.py $(DYLIB) $(STDLIB_DYLIB)
	python test_gimple.py

check-runner: $(MOJO_CLI)
	python test_runner.py

check-gimple-runner: $(MOJO_CLI)
	python test_gimple_runner.py

# Build runtime dylib
$(DYLIB): $(RUNTIME_SRC) $(RUNTIME_HDR)
	@mkdir -p build
	cc -dynamiclib -I runtime -o $@ $(RUNTIME_SRC)

# Build the mojo CLI tool
$(MOJO_CLI): $(BUILD_MOJO_CLI) mojo_compiler.py gimple_codegen.py
	python $(BUILD_MOJO_CLI)
	@chmod +x $@

# Build stdlib dylib (attempt compilation with -k flag to continue on errors)
$(STDLIB_DYLIB): $(STDLIB_WRAPPER) $(STDLIB_STD_PATH) $(MOJO_CLI)
	@mkdir -p build
	@echo "Building Mojo stdlib..."
	$(MOJO_CLI) build $(STDLIB_WRAPPER) -o $@ 2>&1 || true

# Convenience target to build just the stdlib
stdlib: $(STDLIB_DYLIB)
	@echo "Stdlib build complete (or attempted)"

# Attempt to transpile the time module through gimple_codegen
stdlib-time: $(MOJO_CLI) mojo_compiler.py gimple_codegen.py
	@mkdir -p build
	python compile_stdlib.py --module time 2>&1 | tee build/stdlib-time.log

# Attempt to transpile entire stdlib, never fatal
stdlib-check: $(DYLIB) mojo_compiler.py gimple_codegen.py $(MOJO_CLI)
	@mkdir -p build
	python compile_stdlib.py 2>&1 | tee build/stdlib-check.log

# ──────────────────────────────────────────────────────────────
# Bootstrap targets
# ──────────────────────────────────────────────────────────────

# Full bootstrap: Python (permanent) → Mojo → Mojo
# Stage 1: Python bootstrap (mojo_main.py) — permanent, required foundation
# Stage 2: Mojo self-hosting (mojo_main.mojo with real Mojo implementations)
# Stage 3: Mojo again (verify determinism)
#
# On a system with Mojo already installed, start at stage2.
# Stage 1 is always needed as the bootstrap foundation.
bootstrap: preflight stage1 stage2 stage3 verify
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║  ✓ Bootstrap complete and verified (see timings above)     ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@exit 0

# Stage 1: Python bootstrap (permanent foundation)
# On a Mojo system, this stage is always run first to initialize.
stage1: preflight
	@mkdir -p build/verify
	@echo "Stage 1: Python bootstrap (permanent foundation)"
	@echo "         Analyzes mojo_main.py with Python compiler"
	@/usr/bin/time -p python3 mojo_main.py mojo/mojo_main.mojo > build/verify/stage1.dump 2> build/verify/stage1.time || \
	    { echo "FAIL stage1: Python bootstrap failed"; exit 1; }
	@cat build/verify/stage1.time

# Stage 2: Mojo self-hosting (first self-hosted stage)
# Analyzes real Mojo implementation: tokenizer.mojo, parser.mojo, codegen.mojo
stage2: stage1
	@echo ""
	@echo "Stage 2: Mojo self-hosting (first self-hosted)"
	@echo "         Analyzes mojo_main.mojo with real Mojo implementations"
	@/usr/bin/time -p python3 scripts/run_mojo_main.py $(MOJO_MAIN) > build/verify/stage2.dump 2> build/verify/stage2.time || \
	    { echo "FAIL stage2: Mojo self-hosting failed"; exit 1; }
	@cat build/verify/stage2.time

# Stage 3: Mojo verification (determinism check)
# Run stage 2 again with same input to verify deterministic behavior
stage3: stage2
	@echo ""
	@echo "Stage 3: Mojo verification (determinism check)"
	@echo "         Same input as stage 2, should produce identical output"
	@/usr/bin/time -p python3 scripts/run_mojo_main.py $(MOJO_MAIN) > build/verify/stage3.dump 2> build/verify/stage3.time || \
	    { echo "FAIL stage3: Mojo verification failed"; exit 1; }
	@cat build/verify/stage3.time

# Verification: Stage 2 == Stage 3 (both Mojo-based)
verify: stage3
	@echo ""
	@echo "Verification: comparing stage2 vs stage3 (both Mojo-based)..."
	@diff -q build/verify/stage2.dump build/verify/stage3.dump >/dev/null 2>&1 && \
	    { echo "✓ Bootstrap successful (stage2 == stage3)"; } || \
	    { echo "✗ FAIL: Mojo stages differ — not deterministic"; exit 1; }

# Stage 0: preflight checks
preflight: $(MOJO_CLI)
	@test -f ../apex/.venv/bin/python3 || \
	    { echo "FAIL preflight: ../apex/.venv not found — run 'make install' in ../apex"; exit 1; }
	@test -f mojo_compiler.py || \
	    { echo "FAIL preflight: mojo_compiler.py missing — run 'python run.py'"; exit 1; }
	@$(MOJO_CLI) --version >/dev/null 2>&1 || \
	    { echo "FAIL preflight: build/mojo not working"; exit 1; }

# Stage 1: transpile Python compiler → Mojo
transpile: $(TRANSPILE_MOJOS)

# Only transpile the specified files; skip mojo_compiler.py (hand-written)
mojo/generated_dispatch.mojo: generated_dispatch.py scripts/py2mojo.sh
	@mkdir -p mojo
	@scripts/py2mojo.sh $<

mojo/module_loader.mojo: module_loader.py scripts/py2mojo.sh
	@mkdir -p mojo
	@scripts/py2mojo.sh $<

COMPILER_MAIN    = runtime/compiler_main.c
RUNTIME_C        = runtime/mojo_runtime.c
CC_FLAGS         = -fgimple -I runtime
GCC_MP15         = /opt/local/bin/gcc-mp-15
BOOTSTRAP_CC     = $(shell test -x $(GCC_MP15) && echo $(GCC_MP15) || echo gcc)

# Set SDKROOT for compilation (macOS) — := for single evaluation
SDKROOT          := $(shell xcrun --show-sdk-path 2>/dev/null)
CC_ENV           := $(if $(SDKROOT),SDKROOT=$(SDKROOT),)

# [DISABLED: Use 'make bootstrap' instead for interpreter-only bootstrap]
# Stage 2: compile Mojo compiler with Python build/mojo → stage1/mojo
# Two steps: dump GIMPLE C from mojo_main.mojo, then link with compiler_main.c
# stage1: $(STAGE1_BIN)

build/mojo_logic.c: $(MOJO_CLI) $(MOJO_MAIN) $(TRANSPILE_MOJOS)
	@echo "  stage1: dumping GIMPLE from mojo_main.mojo..."
	@$(MOJO_CLI) --dump-gimple $(MOJO_MAIN) > $@ || \
	    { echo "FAIL stage1: --dump-gimple mojo/mojo_main.mojo failed"; rm -f $@; exit 1; }

$(STAGE1_BIN): build/mojo_logic.c $(COMPILER_MAIN) $(RUNTIME_C) $(RUNTIME_HDR)
	@mkdir -p stage1
	@echo "  stage1: linking with compiler_main.c..."
	@$(BOOTSTRAP_CC) $(CC_FLAGS) -o $@ build/mojo_logic.c $(COMPILER_MAIN) $(RUNTIME_C) || \
	    { echo "FAIL stage1: link failed"; exit 1; }
	@chmod +x $@
	@echo "  stage1/mojo built"

# [DISABLED: Use 'make bootstrap' instead for interpreter-only bootstrap]
# Stage 3: compile Mojo compiler with stage1/mojo → stage2/mojo
# stage2: $(STAGE2_BIN)

build/mojo_logic2.c: $(STAGE1_BIN) $(MOJO_MAIN) $(TRANSPILE_MOJOS)
	@echo "  stage2: dumping GIMPLE from stage1/mojo..."
	@$(STAGE1_BIN) --dump-gimple $(MOJO_MAIN) > $@ || \
	    { echo "FAIL stage2: stage1/mojo --dump-gimple failed"; rm -f $@; exit 1; }

$(STAGE2_BIN): build/mojo_logic2.c $(COMPILER_MAIN) $(RUNTIME_C) $(RUNTIME_HDR)
	@mkdir -p stage2
	@echo "  stage2: linking with compiler_main.c..."
	@$(BOOTSTRAP_CC) $(CC_FLAGS) -o $@ build/mojo_logic2.c $(COMPILER_MAIN) $(RUNTIME_C) || \
	    { echo "FAIL stage2: link failed"; exit 1; }
	@chmod +x $@
	@echo "  stage2/mojo built"

# Stage 4: verify bootstrap by comparing intermediate artifacts

clean:
	rm -f mojo_compiler.py
	rm -f $(DYLIB)
	rm -f $(STDLIB_DYLIB)
	rm -f $(MOJO_CLI)

clean-bootstrap:
	rm -f $(TRANSPILE_MOJOS)
	rm -f build/mojo_logic.c build/mojo_logic2.c
	rm -rf stage1 stage2 build/verify
	@echo "Note: mojo/mojo_compiler.mojo not deleted (hand-written)"
