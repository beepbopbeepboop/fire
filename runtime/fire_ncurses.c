#include "fire_ncurses.h"
#include <ncurses.h>
#include <stdlib.h>

void *mojo_ncurses_init(void)
{
    WINDOW *win = initscr();
    if (win) {
        cbreak();
        noecho();
        keypad(win, TRUE);
    }
    return (void *)win;
}

void mojo_ncurses_end(void *win)
{
    (void)win;
    endwin();
}

void mojo_ncurses_refresh(void *win)
{
    wrefresh((WINDOW *)win);
}

void mojo_ncurses_move(void *win, int64_t y, int64_t x)
{
    wmove((WINDOW *)win, (int)y, (int)x);
}

void mojo_ncurses_addstr(void *win, const char *str)
{
    waddstr((WINDOW *)win, str);
}

void mojo_ncurses_mvaddstr(void *win, int64_t y, int64_t x, const char *str)
{
    mvwaddstr((WINDOW *)win, (int)y, (int)x, str);
}

void mojo_ncurses_clear(void *win)
{
    wclear((WINDOW *)win);
}

int64_t mojo_ncurses_getch(void *win)
{
    return (int64_t)wgetch((WINDOW *)win);
}

void mojo_ncurses_attron(void *win, int64_t attr)
{
    wattron((WINDOW *)win, (int)attr);
}

void mojo_ncurses_attroff(void *win, int64_t attr)
{
    wattroff((WINDOW *)win, (int)attr);
}

int64_t mojo_ncurses_has_colors(void)
{
    return (int64_t)has_colors();
}

int64_t mojo_ncurses_start_color(void)
{
    return (int64_t)start_color();
}

int64_t mojo_ncurses_init_pair(int64_t pair, int64_t fg, int64_t bg)
{
    return (int64_t)init_pair((short)pair, (short)fg, (short)bg);
}

void mojo_ncurses_color_set(void *win, int64_t pair)
{
    wcolor_set((WINDOW *)win, (short)pair, NULL);
}

int64_t mojo_ncurses_getmaxy(void *win)
{
    return (int64_t)getmaxy((WINDOW *)win);
}

int64_t mojo_ncurses_getmaxx(void *win)
{
    return (int64_t)getmaxx((WINDOW *)win);
}

void *mojo_ncurses_subwin(void *parent, int64_t nlines, int64_t ncols, int64_t y, int64_t x)
{
    return (void *)subwin((WINDOW *)parent, (int)nlines, (int)ncols, (int)y, (int)x);
}

void mojo_ncurses_delwin(void *win)
{
    delwin((WINDOW *)win);
}
