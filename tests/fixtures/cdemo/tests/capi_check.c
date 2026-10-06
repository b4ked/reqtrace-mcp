#include "../src/lim.h"

/* verifies: LIM-001 */
int main(void) { return clamp(50, 0, 10) == 10 ? 0 : 1; }
