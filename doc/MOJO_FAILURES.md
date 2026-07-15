# Mojo Compiler Failures
# Tests that fail with the real Mojo compiler (tools/mojo)
# These work in our from-scratch Mojo implementation but fail with Modular's Mojo

# ============================================================================
# SYNTAX ISSUES
# ============================================================================

# 1. fn keyword removed (use 'def' instead)
fn test_fn_removed():
    pass
# Error: 'fn' has been removed; use 'def' instead

# 2. String formatting with % operator not supported
def test_string_formatting():
    var s: String = "Hello"
    var name: String = "World"
    print("%s %s" % (s, name))
# Error: 'StringLiteral' does not implement the '__mod__' method

# 3. int() type conversion not available
def test_int_conversion():
    var f = 42.0
    var i: Int = int(f)
# Error: use of unknown declaration 'int'

# 4. String slicing syntax different
def test_string_slicing():
    var s: String = "hello"
    if "hello"[1:4] == "ell":
        pass
# Error: String does not support direct positional slicing like `s[a:b]`
# Use: s[byte=a:b] or s[codepoint=a:b]

# 5. Empty dict literal needs type annotation
def test_empty_dict():
    var d = {}
# Error: cannot emit initializer list without a contextual type
# Fix: var d: Dict[String, Int] = {}

# 6. Variable redefinition not allowed
def test_variable_redefinition():
    var s: String = "hello"
    var s = {1, 2, 3}  # redefinition of 's'
# Error: invalid redefinition of 's'

# ============================================================================
# TYPE ISSUES
# ============================================================================

# 7. Float type not available (use Float64 or infer)
def test_float_type():
    var f: Float = 42.0
# Error: use of unknown declaration 'Float'

# 8. Tuple return type annotation needed
def test_tuple_return():
    def swap(a: Int, b: Int):
        return (b, a)  # Missing return type annotation
    var r = swap(10, 20)
# Error: cannot implicitly convert 'Tuple[Int, Int]' value to 'None' in return value
# Fix: def swap(a: Int, b: Int) -> (Int, Int):

# 9. Struct instantiation syntax different
def test_struct_instantiation():
    struct Point:
        var x: Int
        var y: Int
    var p = Point(10, 20)  # Invalid syntax
# Error: invalid call to '__init__': no candidates found
# Fix: Use default values and separate assignment

# 10. Struct cannot be defined inside function
def test_nested_struct():
    def inner():
        struct Point:
            var x: Int
# Error: struct inside a function not supported here

# 11. None doesn't support 'is' or 'is not'
def test_none_identity():
    var r = None is None
# Error: 'None' does not implement the '__is__' method

# 12. Subscript on None not supported
def test_none_subscript():
    var r = None[0]
# Error: 'None' does not implement the '__getitem__' method

# ============================================================================
# CONTROL FLOW ISSUES
# ============================================================================

# 13. Constant if conditions not allowed
def test_constant_if_true():
    if True:
        pass
# Error: 'if' condition always evaluates to 'True'
# Fix: Use variable instead of literal

def test_constant_if_false():
    if False:
        pass
    else:
        pass
# Error: 'if' condition always evaluates to 'False'

# 14. Pass statement not supported
def test_pass_statement():
    if False:
        pass
# Error: unexpected token in expression

# 15. global keyword not supported
def test_global():
    var x: Int = 0
    def set_x():
        global x
        x = 1
# Error: unexpected token in expression

# 16. nonlocal keyword not supported
def test_nonlocal():
    def outer():
        var x: Int = 10
        def inner():
            nonlocal x
            x = x + 5
# Error: unexpected token in expression

# 17. Exception class not available
def test_raise_exception():
    try:
        raise Exception("test")
    except:
        pass
# Error: use of unknown declaration 'Exception'

# 18. sys module not available
def test_import_sys():
    import sys
    var len_argv = len(sys.argv)
# Error: unable to locate module 'sys'

# ============================================================================
# RUNTIME ISSUES
# ============================================================================

# 19. Segfault with complex hash computation
def test_xorshift_hash():
    # Complex hash computation with xorshift64star can cause segfault
    var hash: Int = 1
    for i in range(100):
        hash = xorshift64star(hash) ^ i
    print(hash)
# Runtime: Segmentation fault

# 20. Dict iteration with aliasing issues
def test_dict_iteration():
    var d = {"a": 1, "b": 2, "c": 3}
    var sum_vals: Int = 0
    for k in d:
        sum_vals += d[k]  # Aliasing issue
# Error: argument of '__getitem__' call allows reading a memory location 
# previously writable through another aliased argument

# 21. List comprehension may not work in all contexts
def test_list_comprehension():
    var lst = [x * 2 for x in [1, 2, 3]]
# May fail depending on context

# 22. Lambda expressions not supported
def test_lambda():
    var square = lambda x: x * x
# Error: lambda expressions are not supported; define a nested function with 'def'

# ============================================================================
# OPERATOR ISSUES
# ============================================================================

# 23. ^ operator ambiguous (XOR vs ownership transfer)
def test_xor_operator():
    var x: Int = 42
    var y: Int = x ^ (x >> 12)  # Parser may treat ^ as postfix
# Parser bug: ^ followed by ( is treated as postfix operator
# Fix: Avoid ^ followed by ( in expressions

# 24. Boolean short-circuit side effects don't work
def test_boolean_shortcircuit():
    var r: Int = 0
    def set_r():
        r = 1
        return True
    if False or set_r():
        pass
    # r may not be set to 1 due to short-circuit evaluation issues
# Runtime: Side effects may not occur as expected

# ============================================================================
# WORKAROUNDS
# ============================================================================

# Workaround 1: Use variables instead of constants in if conditions
def good_if_condition():
    var cond: Bool = True
    if cond:  # Good: using variable
        pass

# Workaround 2: Use print with multiple arguments instead of % formatting
def good_string_formatting():
    var name: String = "World"
    print("Hello", name)  # Good: using multiple print arguments

# Workaround 3: Use type annotations for empty collections
def good_empty_collections():
    var lst: List[Int] = []  # Good: with type annotation
    var d: Dict[String, Int] = {}  # Good: with type annotation

# Workaround 4: Use byte= or codepoint= for string slicing
def good_string_slicing():
    var s: String = "hello"
    if s[byte=1:4] == "ell":  # Good: using byte= keyword
        pass

# Workaround 5: Mark functions as raises if they use try-except
def good_error_handling() raises:  # Good: marked as raises
    try:
        var x: Int = 10 / 0
    except:
        pass

# Workaround 6: Use nested functions instead of lambda
def good_closure():
    def make_adder(x: Int) -> Int:
        return x + 10  # Good: using nested function
    return make_adder(5)

# Workaround 7: Use explicit return type for tuple returns
def good_tuple_return() -> (Int, Int):
    var a: Int = 10
    var b: Int = 20
    return (b, a)  # Good: with return type annotation

# Workaround 8: Use default values for struct fields
struct GoodPoint:
    var x: Int = 0
    var y: Int = 0

def good_struct_instantiation():
    var p: GoodPoint = GoodPoint()
    p.x = 10
    p.y = 20  # Good: separate assignment
