"""Regression for bug-codegen-comptime-alias-read-through.
Instance read of a constructor-valued comptime alias must not call the instance."""
from test_gimple_runner import test_gimple_stdout

test_gimple_stdout("comptime_alias_instance_read_through", """\
@fieldwise_init
struct Color:
    var _v: Int
    comptime RED = Self(0)
    def __init__(out self, v: Int):
        self._v = v
    def __eq__(self, rhs: Self) -> Bool:
        return self._v == rhs._v

def main():
    var c = Color(1)
    var red = Color.RED
    var inst_red = c.RED
    # Before fix: c.RED lowers to a call of instance c, producing garbage.
    # After fix: c.RED equals Color.RED (Color(0)).
    if red == inst_red:
        print('equal')
    else:
        print('not_equal')
""", "equal\n")
