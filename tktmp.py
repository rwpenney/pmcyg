#!/usr/bin/python
# Tk GUI experiments for pmcyg
# RW Penney, April 2009

import sys
import Tkinter as Tk


def main():
    print 'beginning'
    Tk.Label(text='Nothing').pack()
    Tk.Button(text='Exit', command=sys.exit).pack()
    Tk.mainloop()
    print 'ending'

if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
