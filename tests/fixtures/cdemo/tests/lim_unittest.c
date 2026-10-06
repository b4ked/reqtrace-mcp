#include "../src/lim.h"
#include "mini_gtest.h"

// verifies: LIM-001
TEST(LimTest, Clamp) {
  EXPECT(clamp(5, 0, 10) == 5);
  EXPECT(clamp(-1, 0, 10) == 0);
  EXPECT(clamp(11, 0, 10) == 10);
}

// verifies: LIM-002
TYPED_TEST_P(WinTest, Bounds) {
  EXPECT(in_window(0, 0, 45));
  EXPECT(!in_window(46, 0, 45));
}

// verifies: LIM-003
TEST(LimTest, Smoke) {
  EXPECT(LIM_MAX == 100);  /* never calls scale(): weakly verified */
}

// verifies: LIM-004
TEST(LimTest, Percent) {
  EXPECT(percent(1, 4) == 20);  /* wrong expectation: fails */
}
