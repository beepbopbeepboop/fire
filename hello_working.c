/* Working GIMPLE from gcc compilation */
#include <Python.h>
#include <stdio.h>
#include "runtime/mojo_runtime.h"

void mojo_print(const char *str);

int _gimple_main ()
{
  int D.13058;

  # DEBUG BEGIN_STMT
  mojo_print ("Hello, World!");
  # DEBUG BEGIN_STMT
  mojo_print ("\n");
  # DEBUG BEGIN_STMT
  D.13058 = 0;
  return D.13058;
}


int main ()
{
  int D.13060;

  {
    int result;

    # DEBUG BEGIN_STMT
    Py_Initialize ();
    # DEBUG BEGIN_STMT
    result = _gimple_main ();
    # DEBUG BEGIN_STMT
    Py_Finalize ();
    # DEBUG BEGIN_STMT
    D.13060 = result;
    return D.13060;
  }
  D.13060 = 0;
  return D.13060;
}
