#include <Python.h>

// Simple C function
static int add_numbers(int a, int b) {
    return a + b;
}

// Wrapper for Python
static PyObject *py_add(PyObject *self, PyObject *args) {
    int a, b;
    if (!PyArg_ParseTuple(args, "ii", &a, &b)) {
        return NULL;
    }
    return PyLong_FromLong(add_numbers(a, b));
}

// Method table
static PyMethodDef Methods[] = {
    {"add", py_add, METH_VARARGS, "Add two integers"},
    {NULL, NULL, 0, NULL}
};

// Module definition
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "c_ext",
    "Simple C extension",
    -1,
    Methods
};

// Module initialization
PyMODINIT_FUNC PyInit_c_ext(void) {
    return PyModule_Create(&module);
}
