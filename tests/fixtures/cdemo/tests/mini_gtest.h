/* A tiny stand-in for GoogleTest's macros (see README). */
#ifndef MINI_GTEST_H
#define MINI_GTEST_H
#include <stdio.h>
extern int mg_failed;
extern char mg_msg[512];
#define EXPECT(c)                                                           \
  do {                                                                      \
    if (!(c)) {                                                             \
      snprintf(mg_msg, sizeof mg_msg, "%s:%d: Failure: %s", __FILE__,      \
               __LINE__, #c);                                               \
      mg_failed = 1;                                                        \
    }                                                                       \
  } while (0)
#define TEST(s, n) void s##_##n(void)
#define TYPED_TEST_P(s, n) void s##_##n(void)
#endif
