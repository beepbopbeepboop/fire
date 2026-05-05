#include <Python.h>
#include <stdio.h>

int main() {
    Py_Initialize();

    // Get the builtins module
    PyObject *builtins = PyImport_ImportModule("builtins");
    if (!builtins) {
        PyErr_Print();
        return 1;
    }

    // Get the print function
    PyObject *print_func = PyObject_GetAttrString(builtins, "print");
    if (!print_func) {
        PyErr_Print();
        Py_DECREF(builtins);
        return 1;
    }

    // Call print("Hello from C via Python!")
    PyObject *args = Py_BuildValue("(s)", "Hello from C via Python!");
    PyObject *result = PyObject_CallObject(print_func, args);

    if (result) {
        Py_DECREF(result);
    } else {
        PyErr_Print();
    }

    Py_DECREF(args);
    Py_DECREF(print_func);
    Py_DECREF(builtins);

    Py_Finalize();
    return 0;
}
