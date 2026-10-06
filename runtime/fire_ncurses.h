#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Screen initialisation and teardown */
void *mojo_ncurses_init(void);
void  mojo_ncurses_end(void *win);

/* Refresh */
void mojo_ncurses_refresh(void *win);

/* Move cursor */
void mojo_ncurses_move(void *win, int64_t y, int64_t x);

/* Add string at current position */
void mojo_ncurses_addstr(void *win, const char *str);

/* Add string at position */
void mojo_ncurses_mvaddstr(void *win, int64_t y, int64_t x, const char *str);

/* Clear screen */
void mojo_ncurses_clear(void *win);

/* Get character input */
int64_t mojo_ncurses_getch(void *win);

/* Attributes */
void mojo_ncurses_attron(void *win, int64_t attr);
void mojo_ncurses_attroff(void *win, int64_t attr);

/* Colour */
int64_t mojo_ncurses_has_colors(void);
int64_t mojo_ncurses_start_color(void);
int64_t mojo_ncurses_init_pair(int64_t pair, int64_t fg, int64_t bg);
void mojo_ncurses_color_set(void *win, int64_t pair);

/* Get terminal dimensions */
int64_t mojo_ncurses_getmaxy(void *win);
int64_t mojo_ncurses_getmaxx(void *win);

/* Create/destroy sub-windows */
void *mojo_ncurses_subwin(void *parent, int64_t nlines, int64_t ncols, int64_t y, int64_t x);
void  mojo_ncurses_delwin(void *win);

/* Attribute constants */
#define MOJO_NCURSES_A_BOLD       (1<<14)
#define MOJO_NCURSES_A_DIM        (1<<13)
#define MOJO_NCURSES_A_REVERSE    (1<<12)
#define MOJO_NCURSES_A_UNDERLINE  (1<<11)
#define MOJO_NCURSES_A_BLINK      (1<<10)

/* Colour constants */
#define MOJO_NCURSES_COLOR_BLACK   0
#define MOJO_NCURSES_COLOR_RED     1
#define MOJO_NCURSES_COLOR_GREEN   2
#define MOJO_NCURSES_COLOR_YELLOW  3
#define MOJO_NCURSES_COLOR_BLUE    4
#define MOJO_NCURSES_COLOR_MAGENTA 5
#define MOJO_NCURSES_COLOR_CYAN    6
#define MOJO_NCURSES_COLOR_WHITE   7

#ifdef __cplusplus
}
#endif
