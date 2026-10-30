# Regression for bug:CODEGEN_class_attr_instance_write_is_ignored_on_read
def f(v: int):
    class A():
        x = v
    a = A()
    a.x = 9
    return a.x

def main():
    assert f(4) == 9, f"expected 9 got {f(4)}"
    assert f(10) == 9, f"expected 9 got {f(10)}"
    print("OK")

if __name__ == "__main__":
    main()
