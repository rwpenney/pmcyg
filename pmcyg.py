#!/usr/bin/python
# -*- coding: iso-8859-15
# Partially mirror 'Cygwin' distribution
# (C)Copyright 2009, RW Penney <rwpenney@users.sourceforge.net>

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

import  bz2, optparse, os, os.path, re, string, \
        StringIO, sys, threading, time, urllib, urlparse
try: set
except NameError: from sets import Set as set, ImmutableSet as frozenset
try: import hashlib; md5hasher = hashlib.md5
except ImportError: import md5; md5hasher = md5.new
try:
    import Tkinter as Tk;
    import Queue, ScrolledText, tkFileDialog;
    HASGUI = True
except:
    HASGUI = False


PMCYG_VERSION = '0.2'


class PMCygException(Exception):
    """Wrapper for internally generated exceptions"""

    def __init__(self, *args):
        Exception.__init__(self, *args)



class PMbuilder(object):
    """Utility class for constructing partial mirror of Cygwin(TM) distribution"""
    def __init__(self):
        # Directory into which to assemble local mirror:
        self._tgtdir = '.'

        # URL of source of Cygwin installation program 'setup.exe':
        self._exeurl = 'http://sourceware.redhat.com/cygwin/setup.exe'

        # URL of Cygwin mirror site, hosting available packages:
        self._mirror = 'ftp://cygwin.com/pub/cygwin/'

        # URL of Cygwin package database file (derived from _mirror if 'None'):
        self._iniurl = None

        # Set of package age descriptors:
        self._epochs = ['curr']

        # URL of official list of Cygwin mirrors:
        self._mirrorlisturl = 'http://cygwin.com/mirrors.lst'

        self._masterlist = MasterPackageList()
        self._cancelling = False
        self._mirrordict = None
        self._optiondict = {
            'AllPackages':      False,
            'DummyDownload':    False,
            'IncludeBase':      True,
            'MakeAutorun':      False,
            'IncludeSources':   False
        }

    def GetTargetDir(self):
        return self._tgtdir

    def SetTargetDir(self, tgtdir):
        self._tgtdir = tgtdir

    def GetExeURL(self):
        return self._exeurl

    def SetExeURL(self, exesrc):
        self._exeurl = exesrc

    def GetMirrorURL(self):
        return self._mirror

    def SetMirrorURL(self, mirror, resetiniurl=True):
        if not mirror.endswith('/'):
            mirror += '/'
        self._mirror = mirror

        if resetiniurl:
            self.SetIniURL(None)

    def GetIniURL(self):
        return self._iniurl

    def SetIniURL(self, iniurl):
        reload = False
        if iniurl:
            self._iniurl = iniurl
        else:
            self._iniurl = urlparse.urljoin(self._mirror, 'setup.ini')
            reload = True
        self._masterlist.SetSourceURL(self._iniurl, reload)

    def GetEpochs(self):
        return self._epochs

    def SetEpochs(self, epochs):
        self._epochs = epochs

    def GetOption(self, optname):
        return self._optiondict.get(optname)

    def SetOption(self, optname, value):
        oldval = None
        try:
            oldval = self._optiondict[optname]
            self._optiondict[optname] = value
        except:
            # Option-name is not valid:
            raise
        return oldval


    def ReadMirrorList(self, reload=False):
        """Construct list of Cygwin mirror sites"""

        if self._mirrordict and not reload:
            return self._mirrordict

        self._mirrordict = {}

        try:
            fp = urllib.urlopen(self._mirrorlisturl)
        except:
            print >>sys.stderr, 'Failed to read list of Cygwin mirrors from %s' % self._mirrorlisturl
            fp = self._makeFallbackMirrorList()

        for line in fp:
            line = line.strip()
            if not line: continue
            (url, ident, region, country) = line.split(';')
            self._mirrordict.setdefault(region,{}).setdefault(country,[]).append((ident, url))

        fp.close()
        return self._mirrordict


    def ReadPackageLists(self, filenames):
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


    def BuildMirror(self, userpackages):
        """Download and configure packages into local directory"""

        self._cancelling = False

        packages = self._resolveDependencies(userpackages)
        (downloads, totsize) = self._buildFetchList(packages)

        print 'Download size: %s from %s' % ( self._prettyfsize(totsize), self._mirror)

        if self._optiondict['DummyDownload']:
            self._doDummyDownloading(downloads)
        else:
            self._doDownloading(packages, downloads)

    def Cancel(self, flag=True):
        """Signal that downloading should be terminated"""
        self._cancelling = flag


    def MakeTemplate(self, stream):
        """Generate template package listing file"""

        (header, pkgdict) = self._getPkgDict()
        catgroups = self._masterlist.GetCategories()
        catlist = [ c for c in catgroups.iterkeys() if c != 'All' ]
        catlist.sort()

        dtable = string.maketrans('\n', ' ')
        def descfix(s):
            return s.translate(dtable, '\r')

        print >>stream, '# Package listing for pmcyg (Cygwin(TM) Partial Mirror)\n# Autogenerated on %s\n# from: %s\n' % ( time.asctime(), self.GetIniURL() )
        print >>stream, '# This file contains listings of cygwin package names, one per line.\n# Lines starting with \'#\' denote comments, with blank lines being ignored.\n# The dependencies of any package listed here should be automatically\n# included in the mirror by pmcyg.'

        for cat in catlist:
            print >>stream, '\n\n##\n## %s\n##' % cat

            for pkg in catgroups[cat]:
                desc = descfix(pkgdict[pkg].get('sdesc_curr', ''))
                print >>stream, '#%-24s  \t# %s' % ( pkg, desc )


    def _prettyfsize(self, size):
        """Pretty-print file size, autoscaling units"""
        divisors = [ ( 1<<30, 'GB' ), ( 1<<20, 'MB' ), ( 1<<10, 'kB' ), ( 1, 'B' ) ]

        for div, unit in divisors:
            qsize = float(size) / div
            if qsize > 0.8:
                return '%.3g%s' % ( qsize, unit )

        return '%dB' % ( size )


    def _getPkgDict(self):
        """Return, possibly cached, package dictionary from setup.ini file"""
        cached = self._masterlist.HasCachedData()
        if not cached:
            print 'Scanning mirror index at %s...' % self._masterlist.GetSourceURL(),
            sys.stdout.flush()

        (hdr, pkgs) = self._masterlist.GetHeaderAndPackages()

        if not cached:
            print ' done'

        return (hdr, pkgs)


    def _makeFallbackMirrorList(self):
            return StringIO.StringIO("""
ftp://mirror.aarnet.edu.au/pub/sourceware/cygwin/;mirror.aarnet.edu.au;Australia;Australia
http://mirror.aarnet.edu.au/pub/sourceware/cygwin/;mirror.aarnet.edu.au;Australia;Australia
ftp://mirror.cpsc.ucalgary.ca/cygwin.com/;mirror.cpsc.ucalgary.ca;Canada;Alberta
http://mirror.cpsc.ucalgary.ca/mirror/cygwin.com/;mirror.cpsc.ucalgary.ca;Canada;Alberta
ftp://mirror.switch.ch/mirror/cygwin/;mirror.switch.ch;Europe;Switzerland
ftp://ftp.iitm.ac.in/cygwin/;ftp.iitm.ac.in;Asia;India
http://ftp.iitm.ac.in/cygwin/;ftp.iitm.ac.in;Asia;India
ftp://mirror.nyi.net/cygwin/;mirror.nyi.net;United States;New York
http://mirror.nyi.net/cygwin/;mirror.nyi.net;United States;New York
ftp://ftp.mirrorservice.org/sites/sourceware.org/pub/cygwin/;ftp.mirrorservice.org;Europe;UK
http://www.mirrorservice.org/sites/sourceware.org/pub/cygwin/;www.mirrorservice.org;Europe;UK
ftp://mirror.mcs.anl.gov/pub/cygwin/;mirror.mcs.anl.gov;United States;Illinois
http://mirror.mcs.anl.gov/cygwin/;mirror.mcs.anl.gov;United States;Illinois
                """)


    def _resolveDependencies(self, usrpkgs=None):
        """Constuct list of packages, including all their dependencies"""

        (hdr, pkgdict) = self._getPkgDict()

        additions = self._extendPkgSelection(usrpkgs)
        packages = set()
        badpkgnames = []

        while additions:
            pkg = additions.pop()
            packages.add(pkg)

            pkginfo = pkgdict.get(pkg, None)
            if not pkginfo:
                badpkgnames.append(pkg)
                continue

            # Find dependencies of current package & add to stack:
            for epoch in self._epochs:
                try:
                    key = 'requires' + '_' + epoch
                    reqlist = pkginfo.get(key, '').split()
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

    def _extendPkgSelection(self, userpkgs=None):
        """Amend list of packages to include base or default packages"""

        pkgset = set()

        (hdr, pkgdict) = self._getPkgDict()
        if not pkgdict:
            return pkgset

        if userpkgs == None:
            # Setup minimalistic set of packages
            userpkgs = ['ash', 'base-files', 'base-passwd',
                        'bash', 'bzip2', 'coreutils', 'gzip',
                        'tar', 'unzip', 'zip']

        if self._optiondict['AllPackages']:
            userpkgs = [ pkg for pkg in pkgdict.iterkeys()
                                if not pkg.startswith('_') ]

        pkgset.update(userpkgs)

        if self._optiondict['IncludeBase']:
            # Include all packages from 'Base' category:
            for pkg, pkginfo in pkgdict.iteritems():
                cats = pkginfo.get('category_curr', '').split()
                if 'Base' in cats:
                    pkgset.add(pkg)

        return pkgset

    def _buildFetchList(self, packages):
        """Convert list of packages into set of files to fetch from Cygwin server"""
        (header, pkgdict) = self._getPkgDict()

        # Construct list of compiled/source/current/previous variants:
        pkgtypes = ['install']
        if self._optiondict['IncludeSources']:
            pkgtypes.append('source')
        variants = [ pfx + '_' + sfx for pfx in pkgtypes
                                        for sfx in self._epochs ]

        downloads = []
        totsize = 0

        for pkg in packages:
            pkginfo = pkgdict[pkg]

            for vrt in variants:
                try:
                    flds = pkginfo[vrt].split()
                    pkgref = flds[0]
                    pkgsize = int(flds[1])
                    pkghash = flds[2]
                    downloads.append((pkgref, pkgsize, pkghash))
                    totsize += pkgsize
                except KeyError:
                    print >>sys.stderr, 'Cannot find package filename for %s in variant \'%s\'' % (pkg, vrt)

        return downloads, totsize


    def _buildSetupFiles(self, packages):
        """Create top-level configuration files in local mirror"""

        (header, pkgdict) = self._getPkgDict()
        hashfiles = []

        (inibase, inipure) = self._urlbasename(self._iniurl)
        inibz2 = inipure + '.bz2'
        (exebase, exepure) = self._urlbasename(self._exeurl)

        # Split package list into normal + specials:
        spkgs = [pkg for pkg in packages if pkg.startswith('_')]
        packages = [pkg for pkg in packages if not pkg.startswith('_')]
        packages.sort()
        spkgs.sort()
        packages.extend(spkgs)

        # Reconstruct setup.ini file:
        spath = os.path.join(self._tgtdir, inibase)
        hashfiles.append(inibase)
        fp = open(spath, 'w+t')
        now = time.localtime()
        msgs = [
                '# This file was automatically generated by',
                ' "pmcyg" (version %s),\n' % ( PMCYG_VERSION ),
                '# %s,\n' % ( time.asctime(now) ),
                '# based on %s\n' % ( self.GetIniURL() ),
                '# Manual edits may be overwritten\n',
                'setup-timestamp: %d\n' % ( int(time.time()) ),
                'setup-version: %s\n' % ( header['setup-version'] )
        ]
        for msg in msgs:
            fp.write(msg)
        for pkg in packages:
            fp.write('\n')
            fp.write(pkgdict[pkg]['TEXT'])
        fp.seek(0)
        hashfiles.append(inibz2)
        cpsr = bz2.BZ2File(os.path.join(self._tgtdir, inibz2), mode='w')
        cpsr.write(fp.read())
        cpsr.close()
        fp.close()

        # Create copy of Cygwin installer program:
        tgtpath = os.path.join(self._tgtdir, exebase)
        hashfiles.append(exebase)
        try:
            print 'Retrieving %s to %s...' % ( self._exeurl, tgtpath ),
            sys.stdout.flush()
            urllib.urlretrieve(self._exeurl, tgtpath)
            print ' done'
        except Exception, ex:
            raise PMCygException, "Failed to retrieve %s\n - %s" % ( self._exeurl, str(ex) )

        # (Optionally) create auto-runner batch file:
        if self._optiondict['MakeAutorun']:
            apath = os.path.join(self._tgtdir, 'autorun.inf')
            hashfiles.append('autorun.inf')
            fp = open(apath, 'w+b')
            fp.write('[autorun]\r\nopen=' + exebase +' --local-install\r\n')
            fp.close()

        # Generate message-digest of top-level files:
        hp = open(os.path.join(self._tgtdir, 'md5.sum'), 'wt')
        for fl in hashfiles:
            hshr = md5hasher()
            fp = open(os.path.join(self._tgtdir, fl), 'rb')
            hshr.update(fp.read())
            fp.close()
            hp.write('%s  %s\n' % ( hshr.hexdigest(), fl ))
        hp.close()


    def _hashCheck(self, tgtpath, pkghash):
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

    def _doDummyDownloading(self, downloads):
        """Rehearsal downloading of files from Cygwin mirror"""

        for (pkgfile, pkgsize, pkghash) in downloads:
            print '  %s (%s)' % ( os.path.basename(pkgfile),
                                self._prettyfsize(pkgsize) )

    def _doDownloading(self, packages, downloads):
        """Download files from Cygwin mirror to create local partial copy"""

        if not os.path.isdir(self._tgtdir):
            os.makedirs(self._tgtdir)

        self._buildSetupFiles(packages)

        successes = 0
        failures = 0
        for (pkgfile, pkgsize, pkghash) in downloads:
            if self._cancelling:
                print '** Downloading cancelled **'
                break

            if os.path.isabs(pkgfile):
                raise SyntaxError, '%s is an absolute path' % ( pkgfile )
            tgtpath = os.path.join(self._tgtdir, pkgfile)
            tgtdir = os.path.dirname(tgtpath)
            if not os.path.isdir(tgtdir):
                os.makedirs(tgtdir)
            mirpath = urlparse.urljoin(self._mirror, pkgfile)

            print '  %s (%s)...' % ( os.path.basename(pkgfile),
                                    self._prettyfsize(pkgsize) ),
            sys.stdout.flush()
            if not os.path.isfile(tgtpath) or os.path.getsize(tgtpath) != pkgsize:
                dlsize = 0
                try:
                    urllib.urlretrieve(mirpath, tgtpath)
                    dlsize = os.path.getsize(tgtpath)
                    if dlsize != pkgsize:
                        raise IOError, 'Mismatched package size (deficit=%s)' \
                                        % ( self._prettyfsize(pkgsize - dlsize) )
                    if not self._hashCheck(tgtpath, pkghash):
                        raise IOError, 'Mismatched checksum'
                    print ' done'
                    successes += 1
                except Exception, ex:
                    print ' FAILED\n  -- %s' % ( str(ex) )
                    failures += 1
            else:
                print '  already present'

        if not failures:
            print 'Downloaded %d package(s) successfully' % ( successes )
        else:
            print '%d/%d packages failed to download' % ( failures, (failures + successes) )


    def _urlbasename(self, url):
        """Split URL into base filename, and suffix-free filename"""
        (scm, loc, basename, query, frag) = urlparse.urlsplit(url)
        pos = basename.rfind('/')
        if pos >= 0:
            basename = basename[(pos+1):]
        pos = basename.rfind('.')
        if pos >= 0:
            pure = basename[0:pos]
        else:
            pure = basename
        return (basename, pure)



"""Database of available Cygwin packages built from 'setup.ini' file"""
class MasterPackageList:
    def __init__(self, iniURL=None):
        self.re_setup = re.compile(r'^(setup-\S+):\s+(\S+)$')
        self.re_comment = re.compile(r'#(.*)$')
        self.re_package = re.compile(r'^@\s+(\S+)$')
        self.re_epoch = re.compile(r'^\[([a-z]+)\]$')
        self.re_field = re.compile(r'^([a-z]+):\s+(.*)$')
        self.re_blank = re.compile(r'^\s*$')
        self.all_regexps = [ self.re_setup, self.re_comment, self.re_blank,
                        self.re_package, self.re_epoch, self.re_field ]

        self._iniURL = None
        self.ClearCache()
        self.SetSourceURL(iniURL)

    def ClearCache(self):
        self._ini_header = None
        self._ini_packages = None

    def GetSourceURL(self):
        return self._iniURL

    def SetSourceURL(self, iniURL=None, reload=False):
        if reload or iniURL != self._iniURL:
            self.ClearCache()
        self._iniURL = iniURL

    def GetHeaderInfo(self):
        self._parseSource()
        return self._ini_header

    def GetPackageDict(self):
        self._parseSource()
        return self._ini_packages

    def GetHeaderAndPackages(self):
        self._parseSource()
        return (self._ini_header, self._ini_packages)

    def HasCachedData(self):
        return (self._ini_header and self._ini_packages)

    def GetCategories(self):
        """Construct lists of packages grouped into categories"""

        pkgdict = self.GetPackageDict()
        allpkgs = []
        catlists = {}

        for pkg, pkginfo in pkgdict.iteritems():
            allpkgs.append(pkg)

            cats = pkginfo.get('category_curr', '').split()
            for ctg in cats:
                catlists.setdefault(ctg, []).append(pkg)

        catlists['All'] = allpkgs
        for cats in catlists.itervalues():
            cats.sort()

        return catlists

    def _parseSource(self):
        # Check if cached result is available
        if self._ini_header and self._ini_packages:
            return

        self._ini_header = {}
        self._ini_packages = {}

        try:
            fp = urllib.urlopen(self._iniURL)
        except Exception, ex:
            raise PMCygException, "Failed to open %s\n - %s" % ( self._iniURL, str(ex) )

        lineno = 0
        self._pkgname = None
        self._pkgtxt = []
        self._pkgdict = {}
        self._epoch = None
        self._fieldname = None
        self._fieldlines = None
        self._inquote = False

        for line in fp:
            lineno += 1

            if self._inquote and self._fieldname:
                self._ingestQuotedLine(line)
            else:
                self._ingestOrdinaryLine(line)

            if self._pkgname:
                self._pkgtxt.append(line)
        fp.close()

        self._finalizePackage()

    def _ingestQuotedLine(self, line):
        trimmed = line.rstrip()
        if trimmed.endswith('"'):
            self._fieldlines.append(trimmed[0:-1])
            self._pkgdict[self._fieldname] = '\n'.join(self._fieldlines)
            self._fieldname = None
            self._inquote = False
        else:
            self._fieldlines.append(trimmed)

    def _ingestOrdinaryLine(self, line):
        # Classify current line as package definition/field etc:
        matches = None
        for regexp in self.all_regexps:
            matches = regexp.match(line)
            if matches: break
        if not matches:
            raise SyntaxError, "Unrecognized content on line %d" % ( lineno )

        if regexp == self.re_setup:
            self._ini_header[matches.group(1)] = matches.group(2)
        elif regexp == self.re_comment:
            pass
        elif regexp == self.re_package:
            self._finalizePackage()

            self._pkgname = matches.group(1)
            self._epoch = 'curr'
            self._fieldname = None
        elif regexp == self.re_epoch:
            self._epoch = matches.group(1)
        elif regexp == self.re_field:
            self._fieldname = matches.group(1) + '_' + self._epoch
            self._fieldtext = matches.group(2)
            if self._fieldtext.startswith('"'):
                if self._fieldtext[1:].endswith('"'):
                    self._pkgdict[self._fieldname] = self._fieldtext[1:-1]
                else:
                    self._fieldlines = [ self._fieldtext[1:] ]
                    self._inquote = True
            else:
                self._pkgdict[self._fieldname] = self._fieldtext

    def _finalizePackage(self):
        """Final assembly of text & field records describing single package"""

        if not self._pkgname:
            return

        pkgtxt = self._pkgtxt
        while pkgtxt and pkgtxt[-1].isspace():
            pkgtxt.pop()
        self._pkgdict['TEXT'] = "".join(pkgtxt)
        self._ini_packages[self._pkgname] = self._pkgdict

        self._pkgname = None
        self._pkgtxt = []
        self._pkgdict = {}



##
## GUI-related classes
##

class TKgui(object):
    """Manage graphical user-interface based on Tk toolkit"""

    def __init__(self, builder=None, pkgfiles=[]):
        if not builder: builder = PMbuilder()
        self.builder = builder
        self.pkgfiles = pkgfiles

        rootwin = Tk.Tk()
        rootwin.minsize(300, 120)
        rootwin.title('pmcyg - Cygwin(TM) partial mirror')
        rootwin.grid_columnconfigure(0, weight=1)
        row = 0

        self.buildthread = None
        self.building = False

        self._boolopts = [
            ( 'dummy_var',   'DummyDownload',  False, 'Dry-run' ),
            ( 'nobase_var',  'IncludeBase',    True,  'Omit base packages' ),
            ( 'allpkgs_var', 'AllPackages',    False, 'Include all packages' ),
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
        parampanel = self.mkParamPanel(rootwin)
        parampanel.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.W)
        row += 1

        self.status_txt = ScrolledText.ScrolledText(rootwin, height=16)
        self.status_txt.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.S+Tk.W, padx=4, pady=8)
        rootwin.grid_rowconfigure(row, weight=1)
        sys.stdout = GUIstream(self)
        sys.stderr = GUIstream(self, highlight=True)
        self.message_queue = Queue.Queue()
        row += 1

    def Run(self):
        self.mirrorthread = GUImirrorthread(self)
        self.mirrorthread.setDaemon(True)
        self.mirrorthread.start()

        def tick():
            # Check if list of mirror sites is available yet:
            if self.mirror_menu and not self.mirrorthread.isAlive():
                self.mirror_btn.config(menu=self.mirror_menu)
                self.mirror_btn.config(state=Tk.NORMAL)

            if self.buildthread and self.buildthread.isAlive() != self.building:
                # Update 'build' button to avoid multiple builder threads:
                state = Tk.NORMAL
                flag = False
                if self.buildthread.isAlive():
                    state = Tk.DISABLED
                    flag = True
                else:
                    self.buildthread = None
                    print '\n'
                self.buildmenu.entryconfig(self.buildmenu.index('Start'),
                                            state=state)
                self.building = flag

            self.processMessages()
            self.status_txt.after(200, tick)

        tick()
        Tk.mainloop()

    def mkMenuBar(self, rootwin):
        """Construct menu-bar for top-level window"""
        menubar = Tk.Menu()

        filemenu = Tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label='Make template', command=self.mkTemplate)
        filemenu.add_separator()
        filemenu.add_command(label='Quit', command=rootwin.quit)
        menubar.add_cascade(label='File', menu=filemenu)

        self.buildmenu = Tk.Menu(menubar, tearoff=0)
        for attr, opt, flip, descr in self._boolopts:
            tkvar = self.__getattribute__(attr)
            self.buildmenu.add_checkbutton(label=descr, variable=tkvar)
        self.buildmenu.add_separator()
        self.buildmenu.add_command(label='Start', command=self.doBuildMirror)
        self.buildmenu.add_command(label='Cancel', command=self.doCancel)
        menubar.add_cascade(label='Build', menu=self.buildmenu)

        helpmenu = Tk.Menu(menubar, tearoff=0, name='help')
        helpmenu.add_command(label='About', command=self.mkAbout)
        menubar.add_cascade(label='Help', menu=helpmenu)

        return menubar

    def mkParamPanel(self, rootwin):
        """Construct GUI components for entering user parameters (e.g. mirror URL)"""
        margin = 4
        entwidth = 30

        parampanel = Tk.Frame(rootwin)
        parampanel.grid_columnconfigure(1, weight=1)
        idx = 0

        Tk.Label(parampanel, text='Package list:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.pkgs_entry = Tk.Entry(parampanel, width=entwidth)
        self.pkgs_entry.config(state='readonly')
        self.pkgs_entry.grid(row=idx, column=1, sticky=Tk.W+Tk.E)
        pkgpanel = Tk.Frame(parampanel)
        pkgs_btn = Tk.Button(pkgpanel, text='Browse', command=self.pkgsSelect)
        pkgs_btn.pack(side=Tk.LEFT)
        pkgpanel.grid(row=idx+1, column=1, stick=Tk.W)
        idx += 2

        Tk.Label(parampanel, text='Installer URL:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.setup_entry = Tk.Entry(parampanel, width=entwidth)
        self.setup_entry.insert(0, self.builder.GetExeURL())
        self.setup_entry.grid(row=idx, column=1, sticky=Tk.W+Tk.E)
        idx += 1

        Tk.Label(parampanel, text='Mirror URL:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.mirror_entry = Tk.Entry(parampanel, width=entwidth)
        self.mirror_entry.insert(0, self.builder.GetMirrorURL())
        self.mirror_entry.grid(row=idx, column=1, sticky=Tk.W+Tk.E)
        self.mirror_btn = Tk.Menubutton(parampanel, text='Mirror list',
                                    relief=Tk.RAISED, state=Tk.DISABLED)
        self.mirror_btn.grid(row=idx+1, column=1, sticky=Tk.W)
        idx += 2

        Tk.Label(parampanel, text='Local cache:').grid(row=idx, column=0, sticky=Tk.W, pady=margin)
        self.cache_entry = Tk.Entry(parampanel, width=entwidth)
        self.cache_entry.insert(0, self.builder.GetTargetDir())
        self.cache_entry.grid(row=idx, column=1, stick=Tk.W+Tk.E)
        cache_btn = Tk.Button(parampanel, text='Browse', command=self.cacheSelect)
        cache_btn.grid(row=idx+1, column=1, stick=Tk.W)
        idx += 2

        return parampanel

    def mkTemplate(self):
        """GUI callback for creating template package-list file"""
        self._txFields()

        tpltname = tkFileDialog.asksaveasfilename(title='Create pmcyg package-listing template')

        if tpltname:
            try:
                fp = open(tpltname, 'wt')
                self.builder.MakeTemplate(fp)
                fp.close()
            except Exception, ex:
                print >>sys.stderr, 'Failed to create "%s" - %s' % ( tpltname, str(ex) )

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
- a tool for creating Cygwin(TM) partial mirrors
Version %s

Copyright © 2009 RW Penney

This program comes with ABSOLUTELY NO WARRANTY.
This is free software, and you are welcome to redistribute it under the terms of the GNU General Public License (v3).""" % ( PMCYG_VERSION ))
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
        pkgfiles = tkFileDialog.askopenfilenames(title='pmcyg user-package lists')
        if pkgfiles:
            self.pkgfiles = pkgfiles
            self.pkgs_entry.config(state=Tk.NORMAL)
            self.pkgs_entry.delete(0, Tk.END)
            self.pkgs_entry.insert(0, '; '.join(pkgfiles))
            self.pkgs_entry.config(state='readonly')

    def cacheSelect(self):
        """Callback for selecting directory into which to download packages"""
        dirname = tkFileDialog.askdirectory(initialdir=self.cache_entry.get(),
                                mustexist=False, title='pmcyg cache directory')
        if dirname:
            self.cache_entry.delete(0, Tk.END)
            self.cache_entry.insert(0, dirname)

    def mkMirrorMenu(self):
        """Build hierarchical menu of Cygwin mirror sites"""
        mirrordict = self.builder.ReadMirrorList()
        menu = Tk.Menu(self.mirror_btn, tearoff=0)

        regions = list(mirrordict.iterkeys())
        regions.sort()
        for region in regions:
            regmenu = Tk.Menu(menu, tearoff=0)

            countries = list(mirrordict[region].iterkeys())
            countries.sort()
            for country in countries:
                cntmenu = Tk.Menu(regmenu, tearoff=0)

                sites = list(mirrordict[region][country])
                sites.sort()
                for site,url in sites:
                    fields = url.split(':', 1)
                    if fields:
                        site = '%s (%s)' % ( site, fields[0] )
                    cntmenu.add_command(label=site,
                                    command=lambda url=url:self.setMirror(url))

                regmenu.add_cascade(label=country, menu=cntmenu)

            menu.add_cascade(label=region, menu=regmenu)

        return menu

    def doBuildMirror(self):
        self._txFields()

        if not self.buildthread:
            self.buildmenu.entryconfigure(self.buildmenu.index('Start'),
                                        state=Tk.DISABLED)
            self.building = True
            self.buildthread = GUIfetchthread(self)
            self.buildthread.setDaemon(True)
            self.buildthread.start()

    def doCancel(self):
        self.builder.Cancel(True)

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
            except Queue.Empty:
                empty = True

    def _txFields(self):
        """Transfer values of GUI controls to PMbuilder object"""

        self.builder.SetTargetDir(self.cache_entry.get())
        self.builder.SetExeURL(self.setup_entry.get())

        newmirror = self.mirror_entry.get()
        if newmirror != self.builder.GetMirrorURL():
            self.builder.SetMirrorURL(newmirror)


class GUIstream:
    """Wrapper for I/O stream for use in GUI"""

    def __init__(self, parent, highlight=False):
        self.parent = parent
        self.highlight = highlight

    def flush(self):
        pass

    def write(self, string):
        self.parent.message_queue.put_nowait((string, self.highlight))


class GUIfetchthread(threading.Thread):
    """Asynchronous downloading for GUI"""
    def __init__(self, parent):
        threading.Thread.__init__(self, target=self.download)
        self.parent = parent

    def download(self):
        builder = self.parent.builder
        usrpkgs = None

        try:
            if self.parent.pkgfiles:
                usrpkgs = builder.ReadPackageLists(self.parent.pkgfiles)

            for attr, opt, flip, descr in self.parent._boolopts:
                tkvar = self.parent.__getattribute__(attr)
                builder.SetOption(opt, flip ^ tkvar.get())

            builder.BuildMirror(usrpkgs)
        except Exception, ex:
            print >>sys.stderr, 'Build failed - %s' % str(ex)


class GUImirrorthread(threading.Thread):
    """Asynchronous construction of list of Cygwin mirrors"""
    def __init__(self, parent):
        threading.Thread.__init__(self, target=self.mklist)
        self.parent = parent

    def mklist(self):
        if self.parent.mirror_menu:
            return

        menu = self.parent.mkMirrorMenu()
        if menu:
            self.parent.mirror_menu = menu



##
## Application entry-points
##

def PlainMain(builder, pkgfiles):
    """Subsidiary program entry-point if used as command-line application"""

    usrpkgs = None
    if pkgfiles:
        usrpkgs = builder.ReadPackageLists(pkgfiles)

    try:
        builder.BuildMirror(usrpkgs)

    except BaseException, ex:
        print >>sys.stderr, 'Fatal error during mirroring [%s]' % ( repr(ex) )



def GUImain(builder, pkgfiles):
    """Subsidiary program entry-point if used as GUI application"""

    gui = TKgui(builder, pkgfiles=pkgfiles)
    gui.Run()



def main():
    builder = PMbuilder()

    # Process command-line options:
    parser = optparse.OptionParser(
                        usage='usage: %prog [options] [package_file...]',
                        description='pmcyg is a tool for generating customized Cygwin(TM) installers',
                        version=PMCYG_VERSION)
    bscopts = optparse.OptionGroup(parser, 'Basic options')
    bscopts.add_option('--all', '-a', action='store_true', default=False,
            help='include all available Cygwin packages')
    bscopts.add_option('--directory', '-d', type='string',
            default=os.path.join(os.getcwd(), 'cygwin'),
            help='where to build local mirror')
    bscopts.add_option('--dry-run', '-z', action='store_true',
            dest='dummy', default=False,
            help='do not actually download packages')
    bscopts.add_option('--mirror', '-m', type='string',
            default=builder.GetMirrorURL(),
            help='URL of Cygwin archive or mirror site')
    bscopts.add_option('--nogui', '-c', action='store_true', default=False,
            help='do not startup graphical user interface (if available)')
    bscopts.add_option('--generate-template', '-g', type='string',
            dest='pkg_file', default=None,
            help='generate template package-listing')
    parser.add_option_group(bscopts)
    advopts = optparse.OptionGroup(parser, 'Advanced options')
    advopts.add_option('--epochs', '-e', type='string',
            default=','.join(builder.GetEpochs()),
            help='comma-separated list of epochs, e.g. "curr,prev"')
    advopts.add_option('--exeurl', '-x', type='string',
            default=builder.GetExeURL(),
            help='URL of "setup.exe" Cygwin installer')
    advopts.add_option('--iniurl', '-i', type='string', default=None,
            help='URL of "setup.ini" Cygwin database')
    advopts.add_option('--nobase', '-B', action='store_true', default=False,
            help='do not automatically include all base packages')
    advopts.add_option('--with-autorun', '-r', action='store_true', default=False,
            help='create autorun.inf file in build directory')
    advopts.add_option('--with-sources', '-s', action='store_true', default=False,
            help='include source-code for of each package')
    parser.add_option_group(advopts)
    opts, remargs = parser.parse_args()

    builder.SetTargetDir(opts.directory)
    builder.SetMirrorURL(opts.mirror)
    builder.SetIniURL(opts.iniurl)
    builder.SetExeURL(opts.exeurl)
    builder.SetEpochs(opts.epochs.split(','))
    builder.SetOption('DummyDownload', opts.dummy)
    builder.SetOption('AllPackages', opts.all)
    builder.SetOption('IncludeBase', not opts.nobase)
    builder.SetOption('MakeAutorun', opts.with_autorun)
    builder.SetOption('IncludeSources', opts.with_sources)

    if opts.pkg_file:
        fp = open(opts.pkg_file, 'wt')
        builder.MakeTemplate(fp)
        fp.close()
        return

    if HASGUI and not opts.nogui:
        GUImain(builder, remargs)
    else:
        PlainMain(builder, remargs)


if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
