/* Simple GIMPLE test */
#include <stdio.h>

int __GIMPLE test_func (void)
{
bb_2:
  printf ("%s\n", "Test");
  return 0;
}

int main(void)
{
  return test_func();
}
