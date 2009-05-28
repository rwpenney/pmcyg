#!/usr/bin/python
# Partially mirror 'cygwin' distribution
# (C)Copyright 2009, RW Penney

#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bz2, optparse, os, os.path, re, sys, time, urllib, urlparse
try: set
except NameError: from sets import Set as set, ImmutableSet as frozenset
try: import hashlib; md5hasher = hashlib.md5
except ImportError: import md5; md5hasher = md5.new
try:
    import Tkinter as Tk;
    import Queue, ScrolledText, threading, tkFileDialog;
    HASGUI = True
except:
    HASGUI = False


# Directory into which to assemble local mirror:
TGT_DIR = '.'
# URL of source of Cygwin installation program 'setup.exe':
EXESRC = 'http://sourceware.redhat.com/cygwin/setup.exe'
# URL of Cygwin mirror site, hosting available packages:
MIRROR = 'ftp://cygwin.com/pub/cygwin/'
# URL of Cygwin package database file (derived from MIRROR if 'None'):
INIURL = None
# Set of package age descriptors:
EPOCHS = ['curr']


class PMCygException(Exception):
    """Wrapper for internally generated exceptions"""

    def __init__(self, *args):
        Exception.__init__(self, *args)


def CheckMirrorIni(mirror, iniurl):
    """Basic sanity checks on mirror URL and location or 'setup.ini' file"""

    if not mirror.endswith('/'):
        mirror += '/'

    if not iniurl:
        iniurl = urlparse.urljoin(mirror, 'setup.ini')

    return mirror, iniurl


def mergelines(pkgtxt):
    """Combine list of lines describing single package"""

    if not pkgtxt:
        return ""

    while pkgtxt and pkgtxt[-1].isspace():
        pkgtxt.pop()

    return "".join(pkgtxt)


def prettyfsize(size):
    """Pretty-print file size, autoscaling units"""
    divisors = [ ( 1<<30, 'GB' ), ( 1<<20, 'MB' ), ( 1<<10, 'kB' ), ( 1, 'B' ) ]

    for div, unit in divisors:
        qsize = float(size) / div
        if qsize > 0.8:
            return '%.2g%s' % ( qsize, unit )

    return '%dB' % ( size )


def ParseIniFile(iniurl):
    """Ingest original 'setup.ini' file defining available cygwin packages"""

    re_setup = re.compile(r'^(setup-\S+):\s+(\S+)$')
    re_comment = re.compile(r'#(.*)$')
    re_package = re.compile(r'^@\s+(\S+)$')
    re_epoch = re.compile(r'^\[([a-z]+)\]$')
    re_field = re.compile(r'^([a-z]+):\s+(.*)$')
    re_blank = re.compile(r'^\s*$')
    all_regexps = [ re_setup, re_comment, re_blank,
                    re_package, re_epoch, re_field ]

    header = {}
    packages = {}

    try:
        fp = urllib.urlopen(iniurl)
    except Exception, ex:
        raise PMCygException, "Failed to open %s\n - %s" % ( iniurl, str(ex) )

    lineno = 0
    (pkgname, pkgtxt, pkgdict, epoch) = (None, [], {}, None)
    (fieldname, fieldlines) = (None, None)
    inquote = False
    for line in fp:
        lineno += 1

        if inquote and fieldname:
            trline = line.rstrip()
            if trline.endswith('"'):
                fieldlines.append(trline[0:-1])
                pkgdict[fieldname] = '\n'.join(fieldlines)
                fieldname = None
                inquote = False
            else:
                fieldlines.append(line)
        else:
            # Classify current line as package definition/field etc:
            matches = None
            for regexp in all_regexps:
                matches = regexp.match(line)
                if matches: break
            if not matches:
                raise SyntaxError, "Unrecognized content on line %d" % ( lineno )

            if regexp == re_setup:
                header[matches.group(1)] = matches.group(2)
            elif regexp == re_comment:
                pass
            elif regexp == re_package:
                if pkgname:
                    pkgdict['TEXT'] = mergelines(pkgtxt)
                    packages[pkgname] = pkgdict
                    pkgname = None
                pkgname = matches.group(1)
                pkgtxt = []
                pkgdict = {}
                epoch = 'curr'
                fieldname = None
            elif regexp == re_epoch:
                epoch = matches.group(1)
            elif regexp == re_field:
                fieldname = matches.group(1) + '_' + epoch
                fieldtext = matches.group(2)
                if fieldtext.startswith('"'):
                    if fieldtext[1:].endswith('"'):
                        pkgdict[fieldname] = fieldtext[1:-1]
                    else:
                        fieldlines = [ line[1:] ]
                        inquote = True
                else:
                    pkgdict[fieldname] = fieldtext

        if pkgname:
            pkgtxt.append(line)
    fp.close()

    if pkgname:
        pkgdict['TEXT'] = mergelines(pkgtxt)
        packages[pkgname] = pkgdict

    return (header, packages)


def MakeCategories(pkgdict):
    """Construct lists of packages grouped into categories"""

    allpkgs = []
    catlists = {}

    for pkg, pkginfo in pkgdict.items():
        allpkgs.append(pkg)

        cats = pkginfo.get('category_curr', '').split()
        for ctg in cats:
            catlists.setdefault(ctg, []).append(pkg)

    catlists['All'] = allpkgs
    for cats in catlists.values():
        cats.sort()

    return catlists


def ResolveDependencies(pkgdict, usrpkgs=None, include_all=False):
    """Constuct list of packages, including all their dependencies"""

    if usrpkgs == None:
        # Setup minimalistic set of packages
        usrpkgs = ['bash', 'bzip2', 'coreutils', 'gzip', 'tar', 'unzip', 'zip' ]

    if include_all:
        usrpkgs = [ pkg for pkg in pkgdict.iterkeys()
                            if not pkg.startswith('_') ]

    additions = set(usrpkgs)
    packages = set()
    badpkgnames = []

    while additions:
        pkg = additions.pop()
        packages.add(pkg)

        try:
            pkginfo = pkgdict[pkg]
        except:
            badpkgnames.append(pkg)
            continue

        # Find dependencies of current package & add to stack:
        for epoch in EPOCHS:
            try:
                reqlist = pkginfo['requires' + '_' + epoch].split()
                for r in reqlist:
                    if not r in packages:
                        additions.add(r)
            except:
                print >>sys.stderr, 'Cannot find epoch \'%s\' for %s' % (epoch, pkg)

    if badpkgnames:
        badpkgnames.sort()
        raise PMCygException, \
            "The following package names where not recognized:\n\t%s\n" \
            % ( '\n\t'.join(badpkgnames) )

    packages = list(packages)
    packages.sort()

    return packages


def BuildDownload(pkgdict, packages):
    """Convert list of packages into set of files to fetch from Cygwin server"""

    downloads = []
    totsize = 0

    for pkg in packages:
        pkginfo = pkgdict[pkg]

        for epoch in EPOCHS:
            try:
                flds = pkginfo['install' + '_' + epoch].split()
                pkgref = flds[0]
                pkgsize = int(flds[1])
                pkghash = flds[2]
                downloads.append((pkgref, pkgsize, pkghash))
                totsize += pkgsize
            except KeyError:
                print >>sys.stderr, 'Cannot find package filename for %s in epoch \'%s\'' % (pkg, epoch)

    return downloads, totsize


def BuildSetupFiles(header, pkgdict, packages):
    """Create top-level configuration files in local mirror"""

    # Split package list into normal + specials:
    spkgs = [pkg for pkg in packages if pkg.startswith('_')]
    packages = [pkg for pkg in packages if not pkg.startswith('_')]
    packages.sort()
    spkgs.sort()
    packages.extend(spkgs)

    # Reconstruct setup.ini file:
    spath = os.path.join(TGT_DIR, 'setup.ini')
    fp = open(spath, 'w+t')
    fp.write('# This file is automatically generated by "pmcyg"\n'
            '# Manual edits will be overwritten\n')
    fp.write('setup-timestamp: %d\n' % (int(time.time())))
    fp.write('setup-version: %s\n' % (header['setup-version']))
    for pkg in packages:
        fp.write('\n')
        fp.write(pkgdict[pkg]['TEXT'])
    fp.seek(0)
    cpsr = bz2.BZ2File(os.path.join(TGT_DIR, 'setup.bz2'), mode='w')
    cpsr.write(fp.read())
    cpsr.close()
    fp.close()

    # Create other top-level artefacts:
    try:
        urllib.urlretrieve(EXESRC, os.path.join(TGT_DIR, 'setup.exe'))
    except Exception, ex:
        raise PMCygException, "Failed to retrieve %s\n - %s" % ( EXESRC, str(ex) )

    hp = open(os.path.join(TGT_DIR, 'md5.sum'), 'wt')
    for fl in ['setup.ini', 'setup.bz2', 'setup.exe']:
        hshr = md5hasher()
        fp = open(os.path.join(TGT_DIR, fl), 'rb')
        hshr.update(fp.read())
        fp.close()
        hp.write('%s  %s\n' % ( hshr.hexdigest(), fl ))
    hp.close()


def HashCheck(tgtpath, pkghash):
    """Check md5 hash-code of downloaded package"""
    blksize = 1 << 14

    hasher = md5hasher()

    try:
        fp = open(tgtpath, 'rb')
        while True:
            chunk = fp.read(blksize)
            if not chunk:
                break
            hasher.update(chunk)
    except:
        return False

    dlhash = hasher.hexdigest().lower()
    pkghash = pkghash.lower()

    return True


def BuildMirror(header, pkgdict, packages):
    """Download files from Cygwin mirror to create local partial copy"""

    if not os.path.isdir(TGT_DIR):
        os.makedirs(TGT_DIR)

    BuildSetupFiles(header, pkgdict, packages)

    (downloads, totsize) = BuildDownload(pkgdict, packages)
    print 'Download size: %s from %s' % ( prettyfsize(totsize), MIRROR)

    for (pkgfile, pkgsize, pkghash) in downloads:
        if os.path.isabs(pkgfile):
            raise SyntaxError, '%s is an absolute path' % ( pkgfile )
        tgtpath = os.path.join(TGT_DIR, pkgfile)
        tgtdir = os.path.dirname(tgtpath)
        if not os.path.isdir(tgtdir):
            os.makedirs(tgtdir)
        mirpath = urlparse.urljoin(MIRROR, pkgfile)
        if not os.path.isfile(tgtpath) or os.path.getsize(tgtpath) != pkgsize:
            print '  %s (%s)...' % ( os.path.basename(pkgfile),
                                    prettyfsize(pkgsize) ),
            dlsize = 0
            try:
                urllib.urlretrieve(mirpath, tgtpath)
                dlsize = os.path.getsize(tgtpath)
                if dlsize != pkgsize:
                    raise IOError, 'Mismatched package size (deficit=%s)' \
                                    % ( prettyfsize(pkgsize - dlsize) )
                if not HashCheck(tgtpath, pkghash):
                    raise IOError, 'Mismatched checksum'
                print ' done'
            except Exception, ex:
                print ' FAILED\n  -- %s' % ( str(ex) )



def ReadPackageLists(filenames):
    """Read a set of user-supplied package names for local mirroring"""

    usrpkgs = []

    for fn in filenames:
        fp = open(fn, 'rt')

        for line in fp:
            idx = line.find('#')
            if idx >= 0:
                line = line[0:idx]
            line = line.strip()

            if line:
                usrpkgs.append(line)

        fp.close()

    return usrpkgs



##
## GUI-related classes
##

class TKgui(object):
    """Manage graphical user-interface based on Tk toolkit"""

    urllist = [
        'file:/var/tmp',
        'ftp://mirror.aarnet.edu.au/pub/sourceware/cygwin',
        'ftp://mirror.cpsc.ucalgary.ca/cygwin.com',
        'ftp://mirror.switch.ch/mirror/cygwin',
        'ftp://ftp.iitm.ac.in/cygwin',
        'ftp://mirror.nyi.net/cygwin',
        'ftp://ftp.mirrorservice.org/sites/sourceware.org/pub/cygwin'
        'http://mirror.aarnet.edu.au/pub/sourceware/cygwin',
        'http://mirror.cpsc.ucalgary.ca/mirror/cygwin.com',
        'http://mirror.mcs.anl.gov/cygwin',
        'http://ftp.iitm.ac.in/cygwin',
        'http://mirror.nyi.net/cygwin',
        'http://www.mirrorservice.org/sites/sourceware.org/pub/cygwin'
    ]

    def __init__(self, pkgfiles=[]):
        self.pkgfiles = pkgfiles

        rootwin = Tk.Tk()
        rootwin.minsize(300, 120)
        rootwin.title('pmcyg - Cygwin(TM) partial mirror')

        parampanel = self.mkParamPanel(rootwin)
        parampanel.pack(expand=True, fill=Tk.X, side=Tk.TOP)

        self.status_txt = ScrolledText.ScrolledText(rootwin)
        self.status_txt.pack(expand=True, fill=Tk.BOTH, padx=4, pady=8, side=Tk.TOP)
        self.status_pos = '1.0'
        sys.stdout = GUIstream(self)
        sys.stderr = GUIstream(self, highlight=True)
        self.message_queue = Queue.Queue()

        btnpanel = Tk.Frame(rootwin)
        build_btn = Tk.Button(btnpanel, text='Build',
                        command=self.doBuildMirror)
        build_btn.pack(side=Tk.RIGHT)
        btnpanel.pack(expand=True, fill=Tk.X, side=Tk.TOP)

    def Run(self):
        def tick():
            #print >> sys.__stdout__, '.'
            self.processMessages()
            self.status_txt.after(200, tick)
        tick()
        Tk.mainloop()

    def mkParamPanel(self, rootwin):
        """Construct GUI components for entering user parameters (e.g. mirror URL)"""
        global TGT_DIR, EXESRC, MIRROR
        margin = 4
        entwidth = 30

        parampanel = Tk.Frame(rootwin)
        parampanel.grid_columnconfigure(1, weight=1)
        idx = 0

        Tk.Label(parampanel, text='Package list:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.pkgs_entry = Tk.Entry(parampanel, width=entwidth)
        self.pkgs_entry.grid(row=idx, column=1, sticky=Tk.W+Tk.E)
        pkgs_btn = Tk.Button(parampanel, text='Browse', command=self.pkgsSelect)
        pkgs_btn.grid(row=idx+1, column=1, stick=Tk.W)
        idx += 2

        Tk.Label(parampanel, text='Installer URL:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.setup_entry = Tk.Entry(parampanel, width=entwidth)
        self.setup_entry.insert(0, EXESRC)
        self.setup_entry.grid(row=idx, column=1, sticky=Tk.W+Tk.E)
        idx += 1

        Tk.Label(parampanel, text='Mirror URL:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.mirror_entry = Tk.Entry(parampanel, width=entwidth)
        self.mirror_entry.insert(0, MIRROR)
        self.mirror_entry.grid(row=idx, column=1, sticky=Tk.W+Tk.E)
        mirror_btn = Tk.Menubutton(parampanel, text='Mirror list', relief=Tk.RAISED)
        mirror_menu = self.mkMirrorMenu(mirror_btn)
        mirror_btn['menu'] = mirror_menu
        mirror_btn.grid(row=idx+1, column=1, sticky=Tk.W)
        idx += 2

        Tk.Label(parampanel, text='Local cache:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.cache_entry = Tk.Entry(parampanel, width=entwidth)
        self.cache_entry.insert(0, TGT_DIR)
        self.cache_entry.grid(row=idx, column=1, stick=Tk.W+Tk.E)
        cache_btn = Tk.Button(parampanel, text='Browse', command=self.cacheSelect)
        cache_btn.grid(row=idx+1, column=1, stick=Tk.W)
        idx += 2

        return parampanel

    def setMirror(self, mirror):
        self.mirror_entry.delete(0, Tk.END)
        self.mirror_entry.insert(0, mirror)

    def pkgsSelect(self):
        """Callback for selecting set of user-supplied listing of packages"""
        pkgfiles = tkFileDialog.askopenfilenames(title='pmcyg user-package lists')
        if pkgfiles:
            self.pkgfiles = pkgfiles
            self.pkgs_entry.delete(0, Tk.END)
            self.pkgs_entry.insert(0, '; '.join(pkgfiles))

    def cacheSelect(self):
        """Callback for selecting directory into which to download packages"""
        dirname = tkFileDialog.askdirectory(initialdir=self.cache_entry.get(),
                                mustexist=False, title='pmcyg cache directory')
        if dirname:
            self.cache_entry.delete(0, Tk.END)
            self.cache_entry.insert(0, dirname)

    def mkMirrorMenu(self, parent):
        menu = Tk.Menu(parent, tearoff=0)
        for url in self.urllist:
            menu.add_command(label=url,
                            command=lambda url=url:self.setMirror(url))
        return menu

    def doBuildMirror(self):
        global TGT_DIR, EXESRC, MIRROR

        TGT_DIR = self.cache_entry.get()
        EXESRC = self.setup_entry.get()
        MIRROR = self.mirror_entry.get()

        builder = GUIthread(self)
        builder.setDaemon(True)
        builder.start()

    def processMessages(self):
        """Ingest messages from queue and add to status window"""
        empty = False
        while not empty:
            try:
                msg, hlt = self.message_queue.get_nowait()
                oldpos = self.status_pos
                self.status_txt.config(state=Tk.NORMAL)
                self.status_txt.insert(oldpos, msg)
                newpos = self.status_txt.index(Tk.INSERT)
                #print >>sys.__stdout__, oldpos, newpos, hlt, msg
                if hlt and oldpos != newpos:
                    self.status_txt.tag_add('_highlight_', oldpos, newpos)
                    self.status_txt.tag_config('_highlight_',
                                    background='grey75', foreground='red')
                self.status_pos = newpos
                self.status_txt.config(state=Tk.DISABLED)
            except Queue.Empty:
                empty = True


class GUIstream:
    """Wrapper for I/O stream for use in GUI"""

    def __init__(self, parent, highlight=False):
        self.parent = parent
        self.highlight = highlight

    def write(self, string):
        self.parent.message_queue.put_nowait((string, self.highlight))


class GUIthread(threading.Thread):
    """Asynchronous downloading for GUI"""
    def __init__(self, parent):
        threading.Thread.__init__(self, target=self.download)
        self.parent = parent

    def download(self):
        usrpkgs = None
        if self.parent.pkgfiles:
            usrpkgs = ReadPackageLists(self.parent.pkgfiles)
        mirror, iniurl = CheckMirrorIni(self.parent.mirror_entry.get(), None)
        print 'Building mirror from %s...' % iniurl
        (header, pkgdict) = ParseIniFile(iniurl)
        packages = ResolveDependencies(pkgdict, usrpkgs)
        BuildMirror(header, pkgdict, packages)
        #print 'Packages: %s' % ( ', '.join(packages) )



##
## Application entry-points
##

def PlainMain(pkgfiles, allpkgs=False, dummy=False):
    """Subsidiary program entry-point if used as command-line application"""

    global INIURL, EPOCHS, EXESRC, MIRROR, TGT_DIR

    usrpkgs = None
    if pkgfiles:
        usrpkgs = ReadPackageLists(pkgfiles)

    try:
        (header, pkgdict) = ParseIniFile(INIURL)
        packages = ResolveDependencies(pkgdict, usrpkgs, include_all=allpkgs)

        if dummy:
            (downloads, totsize) = BuildDownload(pkgdict, packages)
            print 'Download size: %s from %s' \
                    % ( prettyfsize(totsize), MIRROR)
            print 'Packages: %s' % ( ', '.join(packages) )
        else:
            BuildMirror(header, pkgdict, packages)
    except Exception, ex:
        print >>sys.stderr, 'Failed to build mirror\n - %s' % ( str(ex) )



def GUImain(pkgfiles):
    """Subsidiary program entry-point if used as GUI application"""

    gui = TKgui(pkgfiles=pkgfiles)
    gui.Run()



def main():
    global INIURL, EPOCHS, EXESRC, MIRROR, TGT_DIR, HASGUI

    # Process command-line options:
    parser = optparse.OptionParser()
    parser.add_option('--directory', '-d', type='string',
            default=os.path.join(os.getcwd(), 'cygwin'),
            help='where to build local mirror')
    parser.add_option('--dummy', '-z', action='store_true', default=False,
            help='do not actually download packages')
    parser.add_option('--exeurl', '-x', type='string', default=EXESRC,
            help='URL of "setup.exe" Cygwin installer')
    parser.add_option('--iniurl', '-i', type='string', default=None,
            help='URL of "setup.ini" Cygwin database')
    parser.add_option('--mirror', '-m', type='string', default=MIRROR,
            help='URL of Cygwin archive or mirror site')
    parser.add_option('--epochs', '-e', type='string', default=','.join(EPOCHS),
            help='comma-separated list of epochs, e.g. "curr,prev"')
    parser.add_option('--all', '-a', action='store_true', default=False,
            help='include all available Cygwin packages')
    parser.add_option('--nogui', '-c', action='store_true', default=False,
            help='do not startup graphical user interface (if available)')
    opts, remargs = parser.parse_args()

    TGT_DIR = opts.directory
    MIRROR, INIURL = CheckMirrorIni(opts.mirror, opts.iniurl)
    EPOCHS = opts.epochs.split(',')

    if HASGUI and not opts.nogui:
        GUImain(remargs)
    else:
        PlainMain(remargs, opts.all, opts.dummy)


if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
