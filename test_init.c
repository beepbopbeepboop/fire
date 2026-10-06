#include <Python.h>
#include <stdio.h>

int main() {
    printf("Before init\n");
    Py_Initialize();
    printf("After init\n");
    Py_Finalize();
    printf("After finalize\n");
    return 0;
}
