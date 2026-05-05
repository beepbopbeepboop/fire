.PHONY: run demo check check-gimple clean stdlib bootstrap \
        preflight stage1 stage2 stage3 verify

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
MOJO_MAIN       = mojo.mojo

# Source files to validate through bootstrap
MOJO_SRCS       = \
	bootstrap-validate.mojo \
	bootstrap_test_advanced.mojo \
	bootstrap_test_classes.mojo \
	bootstrap_test_conditionals.mojo \
	bootstrap_test_edge_cases.mojo \
	bootstrap_test_empty.mojo \
	bootstrap_test_expressions.mojo \
	bootstrap_test_input.mojo \
	bootstrap_test_loops.mojo \
	bootstrap_test_single_expr.mojo \
	bootstrap_test_stress.mojo \
	example_imports.mojo \
	mojo/ast_nodes.mojo \
	mojo/codegen.mojo \
	mojo/generated_dispatch.mojo \
	mojo/gimple_codegen.mojo \
	mojo/module_loader.mojo \
	mojo/mojo_compiler.mojo \
	mojo/mojo_main.mojo \
	mojo/myinterpreter.apex.mojo \
	mojo/myinterpreter.mojo \
	mojo/parser.mojo \
	mojo/simple_compiler.mojo \
	mojo/tokenizer.mojo \
	runtime/stdlib_wrapper.mojo \
	runtime/test_helper.mojo \
	scripts/stage2_mojo_interpreter.mojo \
	test_cli.mojo

run:
	python run.py

demo:
	echo "3 + 42 + 0xFF" | python mojo_compiler.py

check:
	python test_mds.py

check-gimple: gimple_codegen.py $(DYLIB) $(STDLIB_DYLIB)
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

# Build the Mojo system executable from GIMPLE-generated C code
mojo.ci: $(MOJO_MAIN)
	./mojo.py --dump $(MOJO_MAIN) 2> /dev/null

build/system.o: mojo.ci
	@mkdir -p build
	$(BOOTSTRAP_CC) -I runtime -c -o $@ mojo.ci

build/mojo_runtime.o: $(RUNTIME_SRC) $(RUNTIME_HDR)
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $(RUNTIME_SRC)

build/mojo: build/system.o build/mojo_runtime.o
	@mkdir -p build
	gcc-mp-15 -o $@ build/system.o build/mojo_runtime.o
	@chmod +x $@
	@echo "build/mojo linked successfully"

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

# Bootstrap: Three-stage self-hosting verification
# Stage 1: mojo.py --dump-all mojo.mojo (Python interpreter)
# Stage 2: mojo.py mojo.mojo --dump-all mojo.mojo (Mojo interpreter on itself)
# Stage 3: mojo.py mojo.mojo mojo.mojo --dump-all mojo.mojo (Verify determinism)
# Success: all three stages produce identical output (silent exit 0)
# Failure: show diff and name failing dump file, exit 1

stage1:
	@mkdir -p build/verify build/dump build/validate
	./mojo.py --dump-all mojo.mojo > build/verify/stage1.c 2> build/dump/stage1.log
	@for f in $(MOJO_SRCS); do \
		base=$$(echo $$f | sed 's/\.mojo$$//;s|^./||;s|/|_|g'); \
		./mojo.py --dump-all $$f > build/validate/$$base.stage1.c 2>/dev/null || true; \
	done

stage2: stage1
	./mojo.py mojo.mojo --dump-all mojo.mojo > build/verify/stage2.c 2> build/dump/stage2.log
	@for f in $(MOJO_SRCS); do \
		base=$$(echo $$f | sed 's/\.mojo$$//;s|^./||;s|/|_|g'); \
		./mojo.py mojo.mojo --dump-all $$f > build/validate/$$base.stage2.c 2>/dev/null || true; \
	done

stage3: stage2
	./mojo.py mojo.mojo mojo.mojo --dump-all mojo.mojo > build/verify/stage3.c 2> build/dump/stage3.log
	@for f in $(MOJO_SRCS); do \
		base=$$(echo $$f | sed 's/\.mojo$$//;s|^./||;s|/|_|g'); \
		./mojo.py mojo.mojo mojo.mojo --dump-all $$f > build/validate/$$base.stage3.c 2>/dev/null || true; \
	done

verify: stage3
	@if ! diff -q build/verify/stage1.c build/verify/stage2.c > /dev/null 2>&1; then \
		echo "FAIL: build/dump/stage2.log"; \
		exit 1; \
	fi
	@if ! diff -q build/verify/stage2.c build/verify/stage3.c > /dev/null 2>&1; then \
		echo "FAIL: build/dump/stage3.log"; \
		exit 1; \
	fi

validate-all:
	./mojo.py bootstrap-validate.mojo

bootstrap: verify validate-all
# Stage 0: preflight checks
preflight: $(MOJO_CLI)
	@test -f ../apex/.venv/bin/python3 || \
	    { echo "FAIL preflight: ../apex/.venv not found — run 'make install' in ../apex"; exit 1; }
	@test -f mojo_compiler.py || \
	    { echo "FAIL preflight: mojo_compiler.py missing — run 'python run.py'"; exit 1; }
	@$(MOJO_CLI) --version >/dev/null 2>&1 || \
	    { echo "FAIL preflight: build/mojo not working"; exit 1; }

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

build/mojo_logic.c: $(MOJO_CLI) $(MOJO_MAIN)
	@echo "  stage1: dumping GIMPLE from mojo_main.mojo..."
	@$(MOJO_CLI) --dump-gimple $(MOJO_MAIN) > $@ || \
	    { echo "FAIL stage1: --dump-gimple mojo.mojo failed"; rm -f $@; exit 1; }

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

build/mojo_logic2.c: $(STAGE1_BIN) $(MOJO_MAIN)
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
	rm -rf build

clean-bootstrap:
	rm -f build/mojo_logic.c build/mojo_logic2.c
	rm -rf stage1 stage2 build/verify
	@echo "Note: all mojo/*.mojo files are preserved (hand-edited source files)"
