#ifndef LIM_H
#define LIM_H
#define LIM_MAX 100
int clamp(int v, int lo, int hi);
int in_window(int a, int lo, int hi);
int scale(int x);
int percent(int part, int whole);
int debug_dump(void);
#endif
