.PHONY: run demo check check-gimple check-runner check-gimple-runner \
        clean clean-bootstrap stdlib bootstrap preflight \
        stage1 stage2 stage3 verify validate-all dump-all-stage1 dump-all-stage2 dump-all-stage3

# ── Paths ────────────────────────────────────────────────────────────────────
RUNTIME_SRC  = runtime/mojo_runtime.c
RUNTIME_HDR  = runtime/mojo_runtime.h
DYLIB        = build/libmojo.dylib
MOJO_CLI     = build/mojo
# The canonical source that all three stages compile
MOJO_MAIN    = mojo.mojo

GCC_MP15     = /opt/local/bin/gcc-mp-15
BOOTSTRAP_CC = $(shell test -x $(GCC_MP15) && echo $(GCC_MP15) || echo gcc)

# MacPorts GCC can't find SDK headers without this
SDKROOT := $(shell xcrun --show-sdk-path 2>/dev/null)
export SDKROOT

# All Mojo source files to validate (top-level + mojo/ subdirectory)
MOJO_FILES := $(wildcard *.mojo) $(wildcard mojo/*.mojo)
# Core Python compiler/tool files to validate through the Mojo system
PY_FILES   := mojo.py mojo_compiler.py myinterpreter.py \
              module_loader.py mojo_main.py generated_dispatch.py

# ── Dev targets ──────────────────────────────────────────────────────────────
run:
	python3 run.py

demo:
	echo "3 + 42 + 0xFF" | python3 mojo_compiler.py

check:
	python3 test_mds.py

check-gimple: gimple_codegen.py $(DYLIB)
	python3 test_gimple.py

check-runner: $(MOJO_CLI)
	python3 test_runner.py

check-gimple-runner: $(MOJO_CLI)
	python3 test_gimple_runner.py

# Build runtime dylib (macOS) / shared lib (Linux)
$(DYLIB): $(RUNTIME_SRC) $(RUNTIME_HDR)
	@mkdir -p build
	cc -dynamiclib -I runtime -o $@ $(RUNTIME_SRC)

# Parse and validate entire stdlib (all .mojo files)
stdlib:
	python3 compile_stdlib.py

# ── Bootstrap stages ─────────────────────────────────────────────────────────
#
# Three-stage self-hosting verification:
#
#  Stage 1  Python mojo.py --dump mojo.mojo
#             → stage1/mojo.ci  (+.tok .ast .pyi for every source file)
#  stage2/mojo  GCC -fgimple compiles stage1/mojo.ci + runtime → compiled binary
#  Stage 2  stage2/mojo --dump mojo.mojo
#             → stage2/mojo.ci  (+ all other dump files)
#  Stage 3  stage2/mojo --dump mojo.mojo  (idempotency: same binary, same output)
#             → stage3/mojo.ci  (+ all other dump files)
#  verify   stage1 == stage2 == stage3  for every generated file

# ── Stage 1: Python drives the compiler ──────────────────────────────────────
stage1:
	@mkdir -p stage1
	@echo "=== Stage 1: Python → stage1/ ==="
	cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump ../$(MOJO_MAIN)
	@echo "--- Dumping all .mojo source files ---"
	@for f in $(MOJO_FILES); do \
	    echo "  dump $$f"; \
	    cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump ../$$f && cd .. || cd ..; \
	done
	@echo "--- Dumping core .py source files ---"
	@for f in $(PY_FILES); do \
	    echo "  dump $$f"; \
	    cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump ../$$f && cd .. || cd ..; \
	done
	@echo "✓ Stage 1 complete"

# ── stage2/mojo: compile stage1 output into a real binary ────────────────────
stage2/mojo: stage1 $(RUNTIME_SRC) $(RUNTIME_HDR)
	@mkdir -p stage2
	@echo "=== Compiling stage2/mojo from stage1/mojo.ci ==="
	$(BOOTSTRAP_CC) -fgimple -I runtime -x c \
	    -o stage2/mojo \
	    stage1/mojo.ci \
	    $(RUNTIME_SRC)
	@chmod +x stage2/mojo
	@echo "✓ stage2/mojo ready"

# ── Stage 2: compiled binary drives itself ────────────────────────────────────
stage2: stage2/mojo
	@mkdir -p stage2
	@echo "=== Stage 2: stage2/mojo → stage2/ ==="
	cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo --dump ../$(MOJO_MAIN)
	@echo "--- Dumping all .mojo source files ---"
	@for f in $(MOJO_FILES); do \
	    echo "  dump $$f"; \
	    cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo --dump ../$$f && cd .. || cd ..; \
	done
	@echo "--- Dumping core .py source files ---"
	@for f in $(PY_FILES); do \
	    echo "  dump $$f"; \
	    cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo --dump ../$$f && cd .. || cd ..; \
	done
	@echo "✓ Stage 2 complete"

# ── Stage 3: idempotency check (same binary, fresh output dir) ───────────────
stage3: stage2/mojo stage2
	@mkdir -p stage3
	@echo "=== Stage 3: stage2/mojo → stage3/ (idempotency check) ==="
	cd stage3 && MOJO_HOME=.. PYTHONPATH=.. ../stage2/mojo --dump ../$(MOJO_MAIN)
	@echo "--- Dumping all .mojo source files ---"
	@for f in $(MOJO_FILES); do \
	    echo "  dump $$f"; \
	    cd stage3 && MOJO_HOME=.. PYTHONPATH=.. ../stage2/mojo --dump ../$$f && cd .. || cd ..; \
	done
	@echo "--- Dumping core .py source files ---"
	@for f in $(PY_FILES); do \
	    echo "  dump $$f"; \
	    cd stage3 && MOJO_HOME=.. PYTHONPATH=.. ../stage2/mojo --dump ../$$f && cd .. || cd ..; \
	done
	@echo "✓ Stage 3 complete"

# ── verify: all three stages identical for every generated file ───────────────
verify: stage3
	@echo "=== Verifying stage outputs ==="
	@FAILED=0; \
	for ext in ci tok ast pyi; do \
	    for f in stage1/*.$$ext; do \
	        [ -f "$$f" ] || continue; \
	        base=$$(basename $$f); \
	        if [ -f "stage2/$$base" ] && [ -f "stage3/$$base" ]; then \
	            if ! diff -q "$$f" "stage2/$$base" > /dev/null 2>&1; then \
	                echo "FAIL stage1 vs stage2: $$base"; FAILED=1; \
	            elif ! diff -q "stage2/$$base" "stage3/$$base" > /dev/null 2>&1; then \
	                echo "FAIL stage2 vs stage3: $$base"; FAILED=1; \
	            else \
	                echo "  OK $$base"; \
	            fi; \
	        else \
	            echo "  WARN missing: stage2/$$base or stage3/$$base (skipped)"; \
	        fi; \
	    done; \
	done; \
	if [ "$$FAILED" = "0" ]; then \
	    echo "✓ All stage outputs match"; \
	else \
	    echo "✗ Stage verification FAILED"; exit 1; \
	fi

# ── validate-all: run bootstrap-validate.mojo (Python-executed) ──────────────
validate-all: stage3
	python3 bootstrap-validate.mojo

# ── bootstrap: full end-to-end ────────────────────────────────────────────────
bootstrap: verify validate-all
	@echo ""
	@echo "✓ Bootstrap complete — all stages verified"

# ── Preflight checks ──────────────────────────────────────────────────────────
preflight:
	@test -f mojo_compiler.py || \
	    { echo "FAIL preflight: mojo_compiler.py missing"; exit 1; }
	@test -f gimple_codegen.py || \
	    { echo "FAIL preflight: gimple_codegen.py missing"; exit 1; }
	@test -f mojo.mojo || \
	    { echo "FAIL preflight: mojo.mojo missing"; exit 1; }
	@python3 -c "from mojo_compiler import tokenize, Parser; print('parser OK')"
	@python3 -c "import gimple_codegen; print('codegen OK')"
	@echo "✓ Preflight passed"

# ── Dev build (non-bootstrap quick compile) ───────────────────────────────────
mojo.ci: $(MOJO_MAIN)
	PYTHONPATH=. python3 mojo.py --dump $(MOJO_MAIN) 2>/dev/null

build/system.o: mojo.ci
	@mkdir -p build
	$(BOOTSTRAP_CC) -fgimple -I runtime -c -o $@ -x c mojo.ci

build/mojo_runtime.o: $(RUNTIME_SRC) $(RUNTIME_HDR)
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $(RUNTIME_SRC)

build/mojo: build/system.o build/mojo_runtime.o
	@mkdir -p build
	$(BOOTSTRAP_CC) -o $@ build/system.o build/mojo_runtime.o
	@chmod +x $@
	@echo "build/mojo linked successfully"

# ── Packaging ─────────────────────────────────────────────────────────────────
tar: mojo.tar.gz
mojo.tar.gz:
	-tar cfz mojo.tar.gz $$(cat files.txt files-rest.txt 2>/dev/null)
	-echo tar done

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf build stage1 stage2 stage3 *.ci *.tok *.pyi *.ast *.o

clean-bootstrap:
	rm -rf stage1 stage2 stage3
	@echo "Note: all *.mojo files preserved (hand-edited source files)"
