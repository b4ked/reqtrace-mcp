#include "lim.h"

/* implements: LIM-001 */
int clamp(int v, int lo, int hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

// implements: LIM-002
int in_window(int a, int lo, int hi) {
  return a >= lo && a <= hi;
}

// implements: LIM-003
int scale(int x) {
  return x * 2;
}

// implements: LIM-004
int percent(int part, int whole) {
  return part * 100 / whole;
}

int debug_dump(void) { return 42; }
