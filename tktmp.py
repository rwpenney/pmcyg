#!/usr/bin/python
# Tk GUI experiments for pmcyg
# RW Penney, April 2009

import sys
import Tkinter as Tk


def main():
    root = Tk.Tk()
    root.minsize(200,150)

    parampanel = Tk.Frame(root)
    for r in range(0,4):
        lbl = Tk.Label(parampanel, text='row-%d'%r)
        lbl.grid(row=r, column=0)
    parampanel.pack(fill=Tk.NONE, side=Tk.TOP)

    pkgpane = Tk.PanedWindow(root, orient=Tk.HORIZONTAL)
    pkgpanel = Tk.Frame(pkgpane)
    lstset = Tk.Listbox(pkgpanel)
    scrlset = Tk.Scrollbar(pkgpanel)
    lstset.pack(expand=True, fill=Tk.BOTH, side=Tk.LEFT)
    scrlset.pack(fill=Tk.Y, side=Tk.LEFT)
    scrlset.config(command=lstset.yview)
    lstset.config(yscrollcommand=scrlset.set)
    pkgpane.add(pkgpanel)
    pkgpanel = Tk.Frame(pkgpane)
    lstset = Tk.Listbox(pkgpanel)
    scrlset = Tk.Scrollbar(pkgpanel)
    lstset.pack(expand=True, fill=Tk.BOTH, side=Tk.LEFT)
    scrlset.pack(fill=Tk.Y, side=Tk.LEFT)
    scrlset.config(command=lstset.yview)
    lstset.config(yscrollcommand=scrlset.set)
    pkgpane.add(pkgpanel)
    pkgpane.pack(expand=True, fill=Tk.BOTH, side=Tk.TOP)


    infopanel = Tk.Frame(root)
    infopanel.pack(fill=Tk.X, side=Tk.TOP)

    btnpanel = Tk.Frame(root)
    btnpanel.pack(fill=Tk.X, side=Tk.TOP)

    Tk.mainloop()

if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
