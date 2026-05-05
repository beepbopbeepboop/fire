#include <Python.h>
#include <stdio.h>
#include "runtime/mojo_runtime.h"

int _gimple_main(void) {
    mojo_print("Hello, World!");
    mojo_print("\n");
    return 0;
}

int main(void) {
    Py_Initialize();
    int result = _gimple_main();
    Py_Finalize();
    return result;
}
