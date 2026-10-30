"""Regression for CODEGEN_sync_generator_struct_param_cpp_shadow.
Before the fix, a generator with a struct-typed parameter named `t`
shadows the emitted C++ local `t`, producing a g++ error.
After renaming the local to `__task`, it builds correctly."""
from test_gimple_generator_runner import test_generator_stdout

def test_struct_param_named_t():
    test_generator_stdout("struct_param_t_no_shadow", """\
struct T:
    var k: Int
    def __init__(out self, k: Int):
        self.k = k

def gen(t: T):
    yield t.k
    yield t.k + 1

def main():
    var t = T(7)
    for v in gen(t):
        print(v)
main()
""", "7\n8\n")

if __name__ == "__main__":
    test_struct_param_named_t()
    print("PASS struct_param_named_t")
