.PHONY: check test clean help

help:
	@echo "Formal English Transpiler - Available targets:"
	@echo "  make check       - Run test suite and generate test.log"
	@echo "  make test        - Alias for 'make check'"
	@echo "  make clean       - Remove generated files"
	@echo "  make help        - Show this help message"

check: test.log
	@echo "Test suite completed. Results written to test.log"
	@tail -n 10 test.log

test: check

test.log:
	@echo "Running test suite..."
	python test_suite.py > test.log.tmp
	@mv test.log.tmp test.log
	@cat test.log

clean:
	@rm -f test.log test.log.tmp
	@rm -f example.py test_features.py
	@rm -f *.pyc __pycache__
	@echo "Cleaned up generated files"
