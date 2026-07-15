#!/usr/bin/env python3
"""
Test suite for Formal English Transpiler.
Runs test cases and generates test.log with detailed results.
"""
import sys
import subprocess
import tempfile
import re
from pathlib import Path
from formal_english import transpile
from formal_english.errors import FormalEnglishError


class TestResult:
    def __init__(self, name, passed, error_msg=None):
        self.name = name
        self.passed = passed
        self.error_msg = error_msg

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        msg = f"[{status}] {self.name}"
        if self.error_msg:
            msg += f"\n  Error: {self.error_msg}"
        return msg


def test_case(name, formal_english_code, should_pass=True, check_syntax=True):
    """Run a single test case."""
    try:
        python_code = transpile(formal_english_code)

        # Try to compile the Python code if requested
        if check_syntax:
            compile(python_code, "<generated>", "exec")

        if should_pass:
            return TestResult(name, True)
        else:
            return TestResult(name, False, "Expected error but transpilation succeeded")
    except Exception as e:
        if not should_pass:
            return TestResult(name, True)
        else:
            return TestResult(name, False, str(e))


def extract_formal_english_blocks(markdown_path):
    """Extract formal english code blocks from a markdown file."""
    blocks = []
    try:
        with open(markdown_path, 'r') as f:
            content = f.read()

        # Match code blocks marked with ```formal-english or ```fe
        pattern = r'```(?:formal-english|fe)\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)

        for match in matches:
            # Clean up the code block
            code = match.strip()
            if code:
                blocks.append(code)
    except FileNotFoundError:
        pass

    return blocks


def run_tests():
    """Run all test cases."""
    results = []

    # Test 1: Simple import
    results.append(test_case(
        "Import statement",
        "Import math",
    ))

    # Test 2: From import
    results.append(test_case(
        "From import statement",
        "From math import sqrt and pi",
    ))

    # Test 3: Variable declaration with type
    results.append(test_case(
        "Variable declaration with type",
        "Declare variable x of type integer with value 42",
    ))

    # Test 4: Variable declaration without type
    results.append(test_case(
        "Variable declaration without type",
        "Declare variable x with value 42",
    ))

    # Test 5: Assignment
    results.append(test_case(
        "Assignment statement",
        "Declare variable x with value 0\nSet x to 10",
    ))

    # Test 6: Augmented assignment
    results.append(test_case(
        "Augmented assignment",
        "Declare variable x with value 0\nIncrease x by 5",
    ))

    # Test 7: If statement
    results.append(test_case(
        "If/else statement",
        """Declare variable x with value 5
If x is greater than 0:
    Pass
Otherwise:
    Pass""",
    ))

    # Test 8: While loop
    results.append(test_case(
        "While loop",
        """Declare variable x with value 0
While x is less than 10:
    Increase x by 1""",
    ))

    # Test 9: For loop
    results.append(test_case(
        "For loop",
        """Declare variable items with value [1, 2, 3]
For each item in items:
    Pass""",
    ))

    # Test 10: Function definition
    results.append(test_case(
        "Function definition",
        """Define function add(a of type integer, b of type integer) returning integer:
    Return a plus b""",
    ))

    # Test 11: Function with no return type
    results.append(test_case(
        "Function with no return type",
        """Define function greet(name of type string):
    Pass""",
    ))

    # Test 12: Function returning nothing
    results.append(test_case(
        "Function returning nothing",
        """Define function do_something() returning nothing:
    Pass""",
    ))

    # Test 13: Struct with fields and method
    results.append(test_case(
        "Struct definition",
        """Define struct Point:
    Field x of type float
    Field y of type float

    Define method __init__(self, x of type float, y of type float):
        Set self's x to x
        Set self's y to y""",
    ))

    # Test 14: List comprehension
    results.append(test_case(
        "List comprehension",
        """Declare variable items with value [1, 2, 3, 4, 5]
Declare variable squared with value [i times i for i in items if i is greater than 2]""",
    ))

    # Test 15: Print statement
    results.append(test_case(
        "Print statement",
        """Declare variable x with value 42
Print "Value:" and x""",
    ))

    # Test 16: Try/except/finally
    results.append(test_case(
        "Try/except/finally",
        """Try:
    Pass
Except ValueError as e:
    Pass
Finally:
    Pass""",
    ))

    # Test 17: With statement
    results.append(test_case(
        "With statement",
        """With open("file.txt") as f:
    Pass""",
    ))

    # Test 18: Member access with possessive
    results.append(test_case(
        "Member access with possessive",
        """Define struct Obj:
    Field value of type integer

Declare variable obj with value Obj()
Declare variable v with value obj's value""",
    ))

    # Test 19: Method call
    results.append(test_case(
        "Method call",
        """Declare variable text with value "hello"
Declare variable length with value call text.upper""",
    ))

    # Test 20: Expressions with English operators
    results.append(test_case(
        "Expressions with English operators",
        """Declare variable a with value 5
Declare variable b with value 3
Declare variable c with value a plus b times a minus b""",
    ))

    # Test 21: Comparison chaining
    results.append(test_case(
        "Comparison operators",
        """Declare variable x with value 5
If x is greater than 0 and x is less than 10:
    Pass""",
    ))

    # Test 22: Return statement
    results.append(test_case(
        "Return statement",
        """Define function get_value() returning integer:
    Return 42""",
    ))

    # Test 23: Break and continue
    results.append(test_case(
        "Break and continue",
        """Declare variable items with value [1, 2, 3]
For each item in items:
    If item equals 2:
        Break
    Otherwise:
        Continue""",
    ))

    # Test 24: Raise statement
    results.append(test_case(
        "Raise statement",
        """Define function check(x of type integer):
    If x is less than 0:
        Raise ValueError("negative value")""",
    ))

    # Test 25: Call statement
    results.append(test_case(
        "Call statement",
        """Define function greet(name of type string):
    Print name

Call greet with "World\"""",
    ))

    # Test 26: Dict literal
    results.append(test_case(
        "Dict literal",
        """Declare variable mapping with value {"a": 1, "b": 2}""",
    ))

    # Test 27: Set literal
    results.append(test_case(
        "Set literal",
        """Declare variable unique with value {1, 2, 3}""",
    ))

    # Test 28: Ternary expression
    results.append(test_case(
        "Ternary expression",
        """Declare variable x with value 5
Declare variable msg with value "positive" if x is greater than 0 else "negative\"""",
    ))

    # Test 29: Tuple
    results.append(test_case(
        "Tuple literal",
        """Declare variable pair with value (1, 2)""",
    ))

    # Test 30: Type annotations in different contexts
    results.append(test_case(
        "Complex type annotations",
        """Declare variable items of type list of integer with value [1, 2, 3]
Declare variable mapping of type dict of string to integer""",
    ))

    # Test 31: Multiple parameters
    results.append(test_case(
        "Multiple function parameters",
        """Define function add(a of type integer, b of type integer, c of type integer) returning integer:
    Return a plus b plus c""",
    ))

    # Test 32: Elif chain
    results.append(test_case(
        "If/elif/else chain",
        """Declare variable x with value 5
If x is less than 0:
    Pass
Otherwise if x equals 0:
    Pass
Otherwise if x is less than 10:
    Pass
Otherwise:
    Pass""",
    ))

    # Test 33: Nested loops
    results.append(test_case(
        "Nested loops",
        """Declare variable matrix with value [[1, 2], [3, 4]]
For each row in matrix:
    For each cell in row:
        Pass""",
    ))

    # Test 34: Power operator
    results.append(test_case(
        "Power operator",
        """Declare variable x with value 2 to the power of 3""",
    ))

    # Test 35: String literals
    results.append(test_case(
        "String literals",
        """Declare variable s1 with value "double quotes"
Declare variable s2 with value 'single quotes'""",
    ))

    # Tests 36+: Extract and test examples from EXAMPLES.md
    examples_file = Path("EXAMPLES.md")
    if examples_file.exists():
        blocks = extract_formal_english_blocks(examples_file)
        for i, block in enumerate(blocks, start=36):
            results.append(test_case(
                f"Markdown Example {i - 35}: {block[:40]}...",
                block,
            ))

    return results


def main():
    """Run all tests and generate report."""
    print("Running Formal English Transpiler Test Suite...")
    print("=" * 70)

    results = run_tests()

    # Calculate statistics
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    # Print results to stdout
    for result in results:
        print(result)

    # Print summary
    print("=" * 70)
    print(f"Total Tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {100 * passed / total:.1f}%")
    print("=" * 70)

    # Write to test.log
    with open("test.log", "w") as log:
        log.write("Formal English Transpiler - Test Report\n")
        log.write("=" * 70 + "\n")
        log.write(f"Timestamp: {__import__('datetime').datetime.now().isoformat()}\n")
        log.write("=" * 70 + "\n\n")

        log.write("Detailed Test Results:\n")
        log.write("-" * 70 + "\n")
        for i, result in enumerate(results, 1):
            log.write(f"\nTest {i}: {result.name}\n")
            log.write(f"Status: {'PASS' if result.passed else 'FAIL'}\n")
            if result.error_msg:
                log.write(f"Error: {result.error_msg}\n")

        log.write("\n" + "=" * 70 + "\n")
        log.write("SUMMARY\n")
        log.write("=" * 70 + "\n")
        log.write(f"Total Tests: {total}\n")
        log.write(f"Passed: {passed}\n")
        log.write(f"Failed: {failed}\n")
        log.write(f"Success Rate: {100 * passed / total:.1f}%\n")
        log.write("=" * 70 + "\n")

    print(f"\nTest log written to test.log")

    # Exit with appropriate code
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
