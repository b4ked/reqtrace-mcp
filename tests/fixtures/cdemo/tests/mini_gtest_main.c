/* Command-line driver mimicking GoogleTest (see README). */
#include <stdio.h>
#include <string.h>
#include "mini_gtest.h"

int mg_failed = 0;
char mg_msg[512];
void LimTest_Clamp(void);
void LimTest_Smoke(void);
void LimTest_Percent(void);
void WinTest_Bounds(void);

static const struct { const char *suite, *name; void (*fn)(void); } T[] = {
    {"LimTest", "Clamp", LimTest_Clamp},
    {"LimTest", "Smoke", LimTest_Smoke},
    {"LimTest", "Percent", LimTest_Percent},
    {"Typed/WinTest/0", "Bounds", WinTest_Bounds},
};
#define N (int)(sizeof T / sizeof T[0])

int main(int argc, char** argv) {
  const char *filter = NULL, *out = NULL;
  for (int i = 1; i < argc; ++i) {
    if (!strcmp(argv[i], "--gtest_list_tests")) {
      for (int t = 0; t < N; ++t) {
        if (t == 0 || strcmp(T[t].suite, T[t - 1].suite)) printf("%s.\n", T[t].suite);
        printf("  %s\n", T[t].name);
      }
      return 0;
    }
    if (!strncmp(argv[i], "--gtest_filter=", 15)) filter = argv[i] + 15;
    if (!strncmp(argv[i], "--gtest_output=json:", 20)) out = argv[i] + 20;
  }
  for (int t = 0; t < N; ++t) {
    char full[128];
    snprintf(full, sizeof full, "%s.%s", T[t].suite, T[t].name);
    if (filter && strcmp(filter, full)) continue;
    mg_failed = 0;
    T[t].fn();
    if (out) {
      FILE* f = fopen(out, "w");
      fprintf(f, "{\"testsuites\": [{\"name\": \"%s\", \"testsuite\": [{\"name\": \"%s\", "
                 "\"status\": \"RUN\", \"result\": \"COMPLETED\"", T[t].suite, T[t].name);
      if (mg_failed) fprintf(f, ", \"failures\": [{\"failure\": \"%s\", \"type\": \"\"}]", mg_msg);
      fprintf(f, "}]}]}\n");
      fclose(f);
    }
    return mg_failed;
  }
  return 0;
}
