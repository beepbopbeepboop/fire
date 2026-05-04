.PHONY: run demo check check-gimple clean stdlib

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

clean:
	rm -f mojo_compiler.py
	rm -f $(DYLIB)
	rm -f $(STDLIB_DYLIB)
	rm -f $(MOJO_CLI)
