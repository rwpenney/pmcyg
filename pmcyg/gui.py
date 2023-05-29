"""
Graphical user interface components for pmcyg
"""

import os.path, sys, threading
from .core import BuildViewer, GarbageConfirmer, \
                  HOST_IS_CYGWIN, PackageSet, PMbuilder
from .version import PMCYG_VERSION
from . import gui_imgs

try:
    import tkinter as Tk
    import queue, tkinter.scrolledtext, tkinter.filedialog
    HASGUI = True
except:
    class Tk: Canvas = object; Button = object
    HASGUI = False


class TKgui:
    """Manage graphical user-interface based on Tk toolkit"""

    def __init__(self, builder=None, pkgfiles=[]):
        if not builder: builder = PMbuilder()
        self.builder = builder
        self.builder.SetViewer(GUIbuildViewer(self))

        # Prompt PMBuilder to pre-cache outputs of 'cygcheck -cd' so that
        # we don't fork a subprocess after Tkinter has been initialized:
        self.builder.ListInstalled()

        rootwin = Tk.Tk()
        rootwin.minsize(300, 120)
        rootwin.title('pmcyg - Cygwin(TM) partial mirror')
        rootwin.grid_columnconfigure(0, weight=1)
        row = 0

        self.arch_var = Tk.StringVar()
        self.arch_var.set(builder.GetArch())
        self._boolopts = [
            ( 'dummy_var',   'DummyDownload',  False, 'Dry-run' ),
            ( 'nobase_var',  'IncludeBase',    True,  'Omit base packages' ),
            ( 'incsrcs_var', 'IncludeSources', False, 'Include sources'),
            ( 'autorun_var', 'MakeAutorun',    False, 'Create autorun.inf')
        ]
        for attr, opt, flip, descr in self._boolopts:
            tkvar = Tk.IntVar()
            tkvar.set(flip ^ builder.GetOption(opt))
            self.__setattr__(attr, tkvar)

        menubar = self.mkMenuBar(rootwin)
        rootwin.config(menu=menubar)

        self.mirror_menu = None

        frm = Tk.Frame(rootwin)
        parampanel = self.mkParamPanel(frm)
        parampanel.pack(side=Tk.LEFT, expand=True, fill=Tk.X, padx=4)
        btnpanel = self.mkButtonPanel(frm)
        btnpanel.pack(side=Tk.RIGHT, fill=Tk.Y)
        frm.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.W)
        row += 1

        self.status_txt = tkinter.scrolledtext.ScrolledText(rootwin, height=24)
        self.status_txt.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.S+Tk.W,
                             padx=4, pady=(6,2))
        rootwin.grid_rowconfigure(row, weight=1)
        self.message_queue = queue.Queue()
        row += 1

        self.progress_bar = GUIprogressBar(rootwin)
        self.progress_bar.grid(row=row, column=0, sticky=Tk.E+Tk.W+Tk.S,
                               padx=4, pady=2)
        row += 1

        self.updatePkgSelection(pkgfiles)
        self._state = GUIstate(self)
        self._updateState(GUIconfigState(self))

    def Run(self):
        """Enter the main loop of the graphical user interface."""
        self._renewMirrorMenu = False
        self.mirrorthread = GUImirrorThread(self)
        self.mirrorthread.setDaemon(True)
        self.mirrorthread.start()

        def tick():
            # Check if list of mirror sites is available yet:
            if self._renewMirrorMenu and not self.mirrorthread.is_alive():
                self.mirror_menu = self.mkMirrorMenu()
                self.mirror_btn.config(menu=self.mirror_menu)
                self.mirror_btn.config(state=Tk.NORMAL)
                self._renewMirrorMenu = False

            try:
                newstate = self._state.tick()
                self._updateState(newstate)
            except Exception as ex:
                print('Unhandled exception in GUI event loop - %s'% str(ex), file=sys.stderr)

            self.processMessages()

            self.status_txt.after(200, tick)

        tick()
        Tk.mainloop()

    def _updateState(self, newstate):
        if newstate and not self._state is newstate:
            self._state.leave()
            newstate.enter()
            self._state = newstate

    def mkMenuBar(self, rootwin):
        """Construct menu-bar for top-level window"""
        menubar = Tk.Menu()

        # 'File' menu:
        filemenu = Tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label='Clear history', command=self.clearHist)
        filemenu.add_command(label='Make template', command=self.mkTemplate)
        if HOST_IS_CYGWIN:
            filemenu.add_command(label='Make replica', command=self.mkReplica)
        filemenu.add_separator()
        filemenu.add_command(label='Quit', command=rootwin.quit)
        menubar.add_cascade(label='File', menu=filemenu)

        # 'Options' menu:
        optmenu = Tk.Menu(menubar, tearoff=0)
        for attr, opt, flip, descr in self._boolopts:
            tkvar = self.__getattribute__(attr)
            optmenu.add_checkbutton(label=descr, variable=tkvar)
        menubar.add_cascade(label='Options', menu=optmenu)

        # 'Help' menu:
        helpmenu = Tk.Menu(menubar, tearoff=0, name='help')
        helpmenu.add_command(label='About', command=self.mkAbout)
        menubar.add_cascade(label='Help', menu=helpmenu)

        return menubar

    def mkParamPanel(self, parent):
        """Construct GUI components for entering user parameters
        (e.g. mirror URL)"""
        margin = 4
        entwidth = 30

        parampanel = Tk.Frame(parent)
        parampanel.grid_columnconfigure(1, weight=1)
        self._img_folder = GUIimagery.GetImage('folder')
        rownum = 0

        label = Tk.Label(parampanel, text='Architecture:')
        label.grid(row=rownum, column=0, sticky=Tk.W, pady=margin)
        combo = Tk.OptionMenu(parampanel, self.arch_var, 'x86_64', 'x86')
        combo.grid(row=rownum, column=1, sticky=Tk.W)
        rownum += 1

        label = Tk.Label(parampanel, text='Package list:')
        label.grid(row=rownum, column=0, sticky=Tk.W, pady=margin)
        self.pkgs_entry = Tk.Entry(parampanel, width=entwidth)
        self.pkgs_entry.config(state='readonly')
        self.pkgs_entry.grid(row=rownum, column=1, sticky=Tk.W+Tk.E)
        self.pkgs_btn = Tk.Button(parampanel, image=self._img_folder,
                                  text='Browse', command=self.pkgsSelect)
        self.pkgs_btn.grid(row=rownum, column=2, sticky=Tk.E, padx=margin)

        pkgpanel = Tk.Frame(parampanel)
        self.stats_label = Tk.Label(pkgpanel, text='')
        self.stats_label.pack(side=Tk.RIGHT)
        pkgpanel.grid(row=rownum+1, column=1, stick=Tk.E+Tk.W)
        rownum += 2

        label = Tk.Label(parampanel, text='Installer URL:')
        label.grid(row=rownum, column=0, sticky=Tk.W, pady=margin)
        self.setup_entry = Tk.Entry(parampanel, width=entwidth)
        self.setup_entry.insert(0, self.builder._exeurl)
        self.setup_entry.grid(row=rownum, column=1, sticky=Tk.W+Tk.E)
        rownum += 1

        label = Tk.Label(parampanel, text='Mirror URL:')
        label.grid(row=rownum, column=0, sticky=Tk.W, pady=margin)
        self.mirror_entry = Tk.Entry(parampanel, width=entwidth)
        self.mirror_entry.insert(0, self.builder.mirror_url)
        self.mirror_entry.grid(row=rownum, column=1, sticky=Tk.W+Tk.E)
        self.mirror_btn = Tk.Menubutton(parampanel, image=self._img_folder,
                                        text='Mirror list',
                                        relief=Tk.RAISED, state=Tk.DISABLED)
        self.mirror_btn.grid(row=rownum, column=2, sticky=Tk.E, padx=margin)
        rownum += 1

        label = Tk.Label(parampanel, text='Local cache:')
        label.grid(row=rownum, column=0, sticky=Tk.W, pady=margin)
        self.cache_entry = Tk.Entry(parampanel, width=entwidth)
        self.cache_entry.insert(0, self.builder.GetTargetDir())
        self.cache_entry.grid(row=rownum, column=1, stick=Tk.W+Tk.E)
        cache_btn = Tk.Button(parampanel, image=self._img_folder,
                              text='Browse', command=self.cacheSelect)
        cache_btn.grid(row=rownum, column=2, stick=Tk.E)
        rownum += 1

        return parampanel

    def mkButtonPanel(self, parent):
        """Construct GUI buttons for triggering downloads etc"""

        btnpanel = Tk.Frame(parent)
        xmargin = 4
        ymargin = 2

        self._img_download = GUIimagery.GetImage('download')
        self._img_cancel = GUIimagery.GetImage('cancel')
        self.btn_download = Tk.Button(parent, image=self._img_download,
                                        command=self.doBuildMirror)
        self.btn_download.pack(side=Tk.BOTTOM, padx=xmargin, pady=ymargin)

        self._img_allpkgs = GUIimagery.GetImage('allpkgs')
        self._img_userpkgs = GUIimagery.GetImage('userpkgs')
        allstate = self.builder.GetOption('AllPackages')
        self.btn_allpkgs = ImageButton(parent,
                                        { True: self._img_allpkgs,
                                            False: self._img_userpkgs },
                                        [ allstate, not allstate ],
                                        callback=self.onClickAllPkgs)
        self.btn_allpkgs.pack(side=Tk.BOTTOM, padx=xmargin, pady=ymargin)

        self._img_rplc_never = GUIimagery.GetImage('replace_never')
        self._img_rplc_ask = GUIimagery.GetImage('replace_ask')
        self._img_rplc_kill = GUIimagery.GetImage('replace_kill')
        replstate = self.builder.GetOption('RemoveOutdated')
        self._btn_replace = ImageButton(parent,
                                        { 'no': self._img_rplc_never,
                                            'ask': self._img_rplc_ask,
                                            'yes': self._img_rplc_kill },
                                        [ 'no', 'ask', 'yes' ],
                                        callback=self.onClickReplace)
        self._btn_replace.SetState(replstate)
        self._btn_replace.pack(side=Tk.BOTTOM, padx=xmargin, pady=ymargin)

        return btnpanel

    def onClickAllPkgs(self, idx, allstate):
        self.builder.SetOption('AllPackages', allstate)
        if allstate:
            self.pkgs_btn.config(state='disabled')
        else:
            self.pkgs_btn.config(state='normal')

    def onClickReplace(self, idx, replstate):
        self.builder.SetOption('RemoveOutdated', replstate)

    def setupDownloadButton(self, start=True):
        if start:
            self.btn_download.config(image=self._img_cancel)
            self.btn_download.config(command=self.doCancel)
        else:
            self.btn_download.config(image=self._img_download)
            self.btn_download.config(command=self.doBuildMirror)

    def clearHist(self):
        """Clear history window"""
        self.status_txt.config(state=Tk.NORMAL)
        self.status_txt.delete('1.0', Tk.END)
        self.status_txt.config(state=Tk.DISABLED)

    def mkTemplate(self):
        """GUI callback for creating template package-list file"""
        self.mkPackageList()

    def mkReplica(self):
        """GUI callback for creating replica of existing Cygwin package set"""
        self.mkPackageList(cygwinReplica=True)

    def mkPackageList(self, cygwinReplica=False):
        """Callback helper for creating template package-list files"""
        self._txFields()

        if cygwinReplica:
            wintitle = 'Create pmcyg replica list'
            filename = 'pmcyg-replica.pkgs'
        else:
            wintitle = 'Create pmcyg package-listing template'
            filename = 'pmcyg-template.pkgs'

        tpltname = tkinter.filedialog.asksaveasfilename(title=wintitle,
                                                initialfile=filename)
        if not tpltname: return

        thrd = GUItemplateThread(self, tpltname, cygwinReplica)
        thrd.setDaemon(True)
        thrd.start()

    def mkAbout(self):
        try:
            win = self._aboutwin
        except:
            win = None

        if not win or not win.winfo_exists():
            win = Tk.Toplevel()
            win.title('About pmcyg')
            msg = Tk.Message(win, name='pmcyg_about', justify=Tk.CENTER,
                        aspect=300, border=2, relief=Tk.GROOVE, text= \
"""pmcyg
- a tool for creating Cygwin\N{REGISTERED SIGN} partial mirrors
Version {0:s}

\N{COPYRIGHT SIGN}Copyright 2009-2023 RW Penney

This program comes with ABSOLUTELY NO WARRANTY.
This is free software, and you are welcome to redistribute it under
the terms of the GNU General Public License (v3).""".format(PMCYG_VERSION))
            msg.pack(side=Tk.TOP, fill=Tk.X, padx=2, pady=2)
            self._aboutwin = win
        else:
            win.deiconify()
            win.tkraise()

    def setMirror(self, mirror):
        self.mirror_entry.delete(0, Tk.END)
        self.mirror_entry.insert(0, mirror)
        self._txFields()

    def pkgsSelect(self):
        """Callback for selecting set of user-supplied listing of packages"""
        opendlg = tkinter.filedialog.askopenfilenames
        if sys.platform.startswith('win'):
            # Selecting multiple files is broken in various Windows versions
            # of Python (typically by concatenating filenames into a single string,
            # rather than returning a sequence of filenames):
            def opendlg(*args, **kwargs):
                filename = tkinter.filedialog.askopenfilename(*args, **kwargs)
                if filename: return (filename, )
                else: return None
        pkgfiles = opendlg(title='pmcyg user-package lists')
        self.updatePkgSelection(pkgfiles)

    def updatePkgSelection(self, pkgfiles):
        try:
            self.pkgfiles = [ os.path.normpath(pf) for pf in pkgfiles ]
        except Exception:
            self.pkgfiles = []
        self.pkgs_entry.config(state=Tk.NORMAL)
        self.pkgs_entry.delete(0, Tk.END)
        self.pkgs_entry.insert(0, '; '.join(self.pkgfiles))
        self.pkgs_entry.config(state='readonly')

        pkgset = PackageSet(self.pkgfiles)
        self.stats_label.config(text='{0:d} packages selected' \
                                    .format(len(pkgset)))

    def cacheSelect(self):
        """Callback for selecting directory into which to download packages"""
        dirname = tkinter.filedialog.askdirectory(initialdir=self.cache_entry.get(),
                                mustexist=False, title='pmcyg cache directory')
        if dirname:
            self.cache_entry.delete(0, Tk.END)
            self.cache_entry.insert(0, os.path.normpath(dirname))

    def mkMirrorMenu(self):
        """Build hierarchical menu of Cygwin mirror sites"""
        mirrordict = self.builder.ReadMirrorList()
        menu = Tk.Menu(self.mirror_btn, tearoff=0)

        regions = list(mirrordict.keys())
        regions.sort()
        for region in regions:
            regmenu = Tk.Menu(menu, tearoff=0)

            countries = list(mirrordict[region].keys())
            countries.sort()
            for country in countries:
                cntmenu = Tk.Menu(regmenu, tearoff=0)

                sites = list(mirrordict[region][country])
                sites.sort()
                for site, url in sites:
                    fields = url.split(':', 1)
                    if fields:
                        site = '{0} ({1})'.format(site, fields[0])
                    cntmenu.add_command(label=site,
                                    command=lambda url=url:self.setMirror(url))

                regmenu.add_cascade(label=country, menu=cntmenu)

            menu.add_cascade(label=region, menu=regmenu)

        return menu

    def doBuildMirror(self):
        self._txFields()
        self._updateState(GUIbuildState(self))

    def doCancel(self):
        self.builder.Cancel(True)

    def writeMessage(self, text, severity=BuildViewer.SEV_NORMAL):
        self.builder._statview(text, severity)

    def processMessages(self):
        """Ingest messages from queue and add to status window"""
        empty = False
        while not empty:
            try:
                msg, hlt = self.message_queue.get_nowait()

                oldpos = Tk.END
                self.status_txt.config(state=Tk.NORMAL)

                if hlt and msg != '\n':
                    self.status_txt.insert(Tk.END, msg, '_highlight_')
                else:
                    self.status_txt.insert(Tk.END, msg)

                self.status_txt.see(oldpos)
                self.status_txt.tag_config('_highlight_',
                                background='grey75', foreground='red')

                self.status_txt.config(state=Tk.DISABLED)
            except queue.Empty:
                empty = True

    def updateProgress(self):
        self.progress_bar.Update(self.builder._fetchStats)

    def _txFields(self):
        """Transfer values of GUI controls to PMbuilder object"""

        self.builder.SetArch(self.arch_var.get())
        self.builder.SetTargetDir(self.cache_entry.get())
        self.builder.setup_exe_url = self.setup_entry.get()
        self.builder.mirror_url = self.mirror_entry.get()



class GUIstate:
    """Abstract interface defining a node within a state-machine
    representing different modes of operation within the GUI."""
    def __init__(self, parent):
        self._parent = parent

    def tick(self):
        return self

    def enter(self):
        pass

    def leave(self):
        pass


class GUIconfigState(GUIstate):
    """Representation of the package-selection and configuration
    state of the graphical user interface."""
    def __init__(self, parent):
        GUIstate.__init__(self, parent)
        self._buttonConfig = parent.setupDownloadButton

    def tick(self):
        return self

    def enter(self):
        self._buttonConfig(False)

    def leave(self):
        self._buttonConfig(True)


class GUIbuildState(GUIstate):
    """Representation of the package-download state of the GUI."""
    def __init__(self, parent):
        GUIstate.__init__(self, parent)
        self._buildthread = None

    def tick(self):
        self._parent.updateProgress()
        if self._buildthread and not self._buildthread.is_alive():
            return GUItidyState(self._parent)
        return self

    def enter(self):
        buildthread = GUIfetchThread(self._parent)
        buildthread.setDaemon(True)
        buildthread.start()
        self._buildthread = buildthread

    def leave(self):
        self._buildthread = None
        self._parent.writeMessage('\n')


class GUItidyState(GUIstate):
    """Representation of the post-download cleanup state of the GUI."""
    def __init__(self, parent):
        GUIstate.__init__(self, parent)
        self._builder = parent.builder
        self._confirmer = None

    def tick(self):
        if self._confirmer.HasResponded():
            self._confirmer.ActionResponse()
            return GUIconfigState(self._parent)
        return self

    def enter(self):
        policy = self._builder.GetOption('RemoveOutdated')
        self._confirmer = GUIgarbageConfirmer(self._builder.GetGarbage(),
                                              default=policy)

    def leave(self):
        pass


class GUIbuildViewer(BuildViewer):
    def __init__(self, parent):
        BuildViewer.__init__(self)
        self.parent = parent

    def _output(self, text, severity):
        if severity > self.SEV_NORMAL:
            highlight = True
        else:
            highlight = False

        self.parent.message_queue.put_nowait((text, highlight))



class GUIfetchThread(threading.Thread):
    """Asynchronous downloading for GUI"""
    def __init__(self, parent):
        threading.Thread.__init__(self, target=self.download)
        self.parent = parent

    def download(self):
        builder = self.parent.builder
        pkgset = None

        try:
            if self.parent.pkgfiles:
                pkgset = PackageSet(self.parent.pkgfiles)

            for attr, opt, flip, descr in self.parent._boolopts:
                tkvar = self.parent.__getattribute__(attr)
                builder.SetOption(opt, flip ^ tkvar.get())

            builder.BuildMirror(pkgset)
        except Exception as ex:
            self.parent.writeMessage('Build failed - ' + str(ex),
                                     BuildViewer.SEV_WARNING)


class GUItemplateThread(threading.Thread):
    """Asynchronous generation of template list of packages"""
    def __init__(self, parent, filename, cygwinReplica=False):
        threading.Thread.__init__(self, target=self.mktemplate)
        self.parent = parent
        self.filename = filename
        self.cygwinReplica = cygwinReplica

    def mktemplate(self):
        builder = self.parent.builder
        try:
            builder.TemplateFromLists(self.filename, self.parent.pkgfiles,
                                    self.cygwinReplica)
            self.parent.writeMessage('Generated template file "{0}"' \
                                        .format(self.filename))
        except Exception as ex:
            self.parent.writeMessage('Failed to create "{0}" - {1}' \
                                        .format(self.filename, str(ex)),
                                     BuildViewer.SEV_WARNING)


class GUImirrorThread(threading.Thread):
    """Asynchronous construction of list of Cygwin mirrors"""
    def __init__(self, parent):
        threading.Thread.__init__(self, target=self.mklist)
        self.parent = parent

    def mklist(self):
        if self.parent.mirror_menu:
            return

        self.parent.builder.ReadMirrorList(reload=False)
        self.parent._renewMirrorMenu = True



class GUIgarbageConfirmer(GarbageConfirmer):
    """Simple dialog window for confirming that the user
    wishes to delete outdated packages found beneath the download directory."""
    def __init__(self, garbage, default='no'):
        GarbageConfirmer.__init__(self, garbage, default)

    def _askUser(self, allfiles):
        self._proceed = False
        self.root = self._buildWindow(allfiles)

    def _awaitResponse(self):
        self._userresponse = 'no'

    def _buildWindow(self, allfiles):
        topwin = Tk.Toplevel()
        topwin.title('pmcyg - confirm deletion')
        topwin.protocol('WM_DELETE_WINDOW', self._onExit)
        topwin.grid_columnconfigure(0, weight=1)
        row = 0

        lbl = Tk.Label(topwin, text='The following packages are no longer needed\nand will be deleted:')
        lbl.grid(row=row, column=0, sticky=Tk.N)
        row += 1

        # Construct scrolled window containing list of files for deletion:
        txt = tkinter.scrolledtext.ScrolledText(topwin, height=16, width=60)
        for fl in allfiles:
            txt.insert(Tk.END, fl + '\n')
        txt.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.S+Tk.W, padx=2, pady=4)
        topwin.grid_rowconfigure(row, weight=1)
        row += 1

        btnfrm = Tk.Frame(topwin)
        btn = Tk.Button(btnfrm, text='Cancel', command=self._onCancel)
        btn.pack(side=Tk.RIGHT)
        btn = Tk.Button(btnfrm, text='Ok', command=self._onOk)
        btn.pack(side=Tk.RIGHT)
        btnfrm.grid(row=row, column=0, sticky=Tk.S+Tk.E)
        row += 1

        return topwin

    def _onOk(self):
        self._onExit('yes')

    def _onCancel(self):
        self._onExit('no')

    def _onExit(self, response='no'):
        self._userresponse = response
        self.root.destroy()



class GUIprogressBar(Tk.Canvas):
    """GUI widget representing a multi-colour progress bar
    representing the number of packages downloaded."""
    def __init__(self, *args, **kwargs):
        Tk.Canvas.__init__(self, background='grey50', height=8,
                            *args, **kwargs)

        self._rectFail = None
        self._rectAlready = None
        self._rectNew = None

    def Update(self, stats):
        width, height = self.winfo_width(), self.winfo_height()

        totsize = stats.TotalSize()

        configs = [ ('_failSize',    '_rectFail',    'OrangeRed'),
                    ('_alreadySize', '_rectAlready', 'SeaGreen'),
                    ('_newSize',     '_rectNew',     'LimeGreen') ]
        xpos = 0
        for s_attr, b_attr, colour in configs:
            oldrect = getattr(self, b_attr)
            if oldrect:
                self.delete(oldrect)

            if totsize <= 0: continue

            barwidth = (width * getattr(stats, s_attr)) // totsize
            if barwidth <= 0: continue

            newrect = self.create_rectangle(xpos, 1, xpos + barwidth, height - 1, fill=colour, width=0)
            setattr(self, b_attr, newrect)
            xpos += barwidth



class ImageButton(Tk.Button):
    """GUI widget for a multi-state button with overlayed imagery."""
    def __init__(self, parent, images={}, states=[], callback=None):
        Tk.Button.__init__(self, parent, command=self._onClick)

        self._images = images
        self._states = states
        self._onPress = callback

        self._counter = 0
        self._depth = len(images)
        self.SetState(states[self._counter])

    def SetState(self, newstate):
        self.config(image=self._images[newstate])

    def GetState(self):
        return (self._counter, self._states[self._counter])

    def _onClick(self):
        self._counter = (self._counter + 1) % self._depth
        newstate = self._states[self._counter]
        self.SetState(newstate)

        if self._onPress:
            self._onPress(self._counter, newstate)


class GUIimagery(gui_imgs.Base64):
    """Generator of Tkinter PhotoImage objects for embedded icon imagery"""

    @classmethod
    def GetImage(cls, ident):
        base64data = getattr(cls, ident)
        photo = Tk.PhotoImage(data=base64data)
        return photo
