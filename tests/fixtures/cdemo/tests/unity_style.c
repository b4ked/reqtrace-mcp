/* Unity/CMocka style: several test_* functions in one executable. They share its result. */
#include "../src/lim.h"

// verifies: LIM-001
static int test_clamp_low(void) { return clamp(-5, 0, 10) == 0; }

// verifies: LIM-001
static int test_clamp_high(void) { return clamp(15, 0, 10) == 10; }

int main(void) { return test_clamp_low() && test_clamp_high() ? 0 : 1; }
