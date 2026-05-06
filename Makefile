.PHONY: run demo check check-gimple check-runner check-gimple-runner \
        clean stdlib bootstrap preflight stage1 stage2 stage3 verify validate-all

# Paths
RUNTIME_SRC  = runtime/mojo_runtime.c
RUNTIME_HDR  = runtime/mojo_runtime.h
DYLIB        = build/libmojo.dylib
MOJO_CLI     = build/mojo
MOJO_MAIN    = mojo.mojo

GCC_MP15     = /opt/local/bin/gcc-mp-15
BOOTSTRAP_CC = $(shell test -x $(GCC_MP15) && echo $(GCC_MP15) || echo gcc)

# MacPorts GCC can't find SDK headers without this; export puts it in every recipe's env
SDKROOT := $(shell xcrun --show-sdk-path 2>/dev/null)
export SDKROOT

run:
	python run.py

demo:
	echo "3 + 42 + 0xFF" | python mojo_compiler.py

check:
	python test_mds.py

check-gimple: gimple_codegen.py $(DYLIB)
	python test_gimple.py

check-runner: $(MOJO_CLI)
	python test_runner.py

check-gimple-runner: $(MOJO_CLI)
	python test_gimple_runner.py

# Build runtime dylib
$(DYLIB): $(RUNTIME_SRC) $(RUNTIME_HDR)
	@mkdir -p build
	cc -dynamiclib -I runtime -o $@ $(RUNTIME_SRC)

# Parse and validate entire stdlib (all .mojo files)
stdlib:
	python3 compile_stdlib.py

# Build the Mojo system executable from GIMPLE-generated C code
mojo.ci: $(MOJO_MAIN)
	./mojo.py --dump $(MOJO_MAIN) 2> /dev/null

build/system.o: mojo.ci
	@mkdir -p build
	$(BOOTSTRAP_CC) -fgimple -I runtime -c -o $@ -x c mojo.ci

build/mojo_runtime.o: $(RUNTIME_SRC) $(RUNTIME_HDR)
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $(RUNTIME_SRC)

build/mojo: build/system.o build/mojo_runtime.o
	@mkdir -p build
	gcc-mp-15 -o $@ build/system.o build/mojo_runtime.o
	@chmod +x $@
	@echo "build/mojo linked successfully"

# ──────────────────────────────────────────────────────────────
# Bootstrap targets
# ──────────────────────────────────────────────────────────────

# Three-stage self-hosting verification:
#   Stage 1: Python interpreter parses mojo.mojo → stage1/mojo.ci
#   Stage 2: Mojo interpreter (via stage1) parses mojo.mojo → stage2/mojo.ci
#   Stage 3: Mojo interpreter (via stage2) parses mojo.mojo → stage3/mojo.ci
# verify: all three stages produce identical output

stage1:
	mkdir -p stage1
	cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump ../mojo.mojo

stage2: stage1
	mkdir -p stage2
	cd stage2 && PYTHONPATH=.. python3 ../mojo.py ../mojo.mojo --dump ../mojo.mojo

stage3: stage2
	mkdir -p stage3
	cd stage3 && PYTHONPATH=.. python3 ../mojo.py ../mojo.mojo ../mojo.mojo --dump ../mojo.mojo

verify: stage3
	@if ! diff -q stage1/mojo.ci stage2/mojo.ci > /dev/null 2>&1; then \
		echo "FAIL: stage2 differs from stage1"; \
		exit 1; \
	fi
	@if ! diff -q stage2/mojo.ci stage3/mojo.ci > /dev/null 2>&1; then \
		echo "FAIL: stage3 differs from stage2"; \
		exit 1; \
	fi

validate-all:
	./mojo.py bootstrap-validate.mojo

stage2/mojo: stage2/mojo.ci runtime/mojo_runtime.c runtime/mojo_runtime.h
	@mkdir -p stage2
	$(BOOTSTRAP_CC) -fgimple -I runtime -x c -o $@ $< $(word 2,$^)

bootstrap: stage3 validate-all stage2/mojo
	@echo "✓ Bootstrap complete"

# Stage 0: preflight checks
preflight: $(MOJO_CLI)
	@test -f ../apex/.venv/bin/python3 || \
	    { echo "FAIL preflight: ../apex/.venv not found — run 'make install' in ../apex"; exit 1; }
	@test -f mojo_compiler.py || \
	    { echo "FAIL preflight: mojo_compiler.py missing — run 'python run.py'"; exit 1; }
	@$(MOJO_CLI) --version >/dev/null 2>&1 || \
	    { echo "FAIL preflight: build/mojo not working"; exit 1; }

clean:
	rm -rf build stage1 stage2 stage3 *.ci *.tok *.pyi *.ast *.o

clean-bootstrap:
	rm -rf stage1 stage2 stage3
	@echo "Note: all mojo/*.mojo files are preserved (hand-edited source files)"
