#!/usr/bin/python
# -*- coding: iso-8859-15
# Partially mirror 'Cygwin' distribution
# (C)Copyright 2009-2010, RW Penney <rwpenney@users.sourceforge.net>

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


PMCYG_VERSION = '0.5'


import  bz2, optparse, os, os.path, re, string, \
        StringIO, sys, threading, time, urllib, urlparse
try: from urllib.request import urlopen as URLopen
except ImportError: from urllib2 import urlopen as URLopen
try: set
except NameError: from sets import Set as set, ImmutableSet as frozenset
try: import hashlib; md5hasher = hashlib.md5
except ImportError: import md5; md5hasher = md5.new
try:
    import Tkinter as Tk
    import Queue, ScrolledText, tkFileDialog
    HASGUI = True
except:
    class Tk: Canvas = object
    HASGUI = False


broken_openfilenames = False
if sys.platform.startswith('win') and sys.version.startswith('2.6.'):
    # Selecting multiple filenames is broken in Windows version of Python-2.6:
    broken_openfilenames = True



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
        self._listLock = threading.Lock()
        self._garbage = GarbageCollector()
        self._cancelling = False
        self._mirrordict = None
        self._optiondict = {
            'AllPackages':      False,
            'DummyDownload':    False,
            'IncludeBase':      True,
            'MakeAutorun':      False,
            'IncludeSources':   False,
            'RemoveOutdated':   'no'
        }

        self._fetchStats = FetchStats()

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
        try:
            self._listLock.acquire()
            self._masterlist.SetSourceURL(self._iniurl, reload)
        finally:
            self._listLock.release()

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
            fp = URLopen(self._mirrorlisturl)
        except:
            print >>sys.stderr, 'Failed to read list of Cygwin mirrors from %s' % self._mirrorlisturl
            fp = self._makeFallbackMirrorList()

        for line in fp:
            line = line.decode('ascii').strip()
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
        downloads = self._buildFetchList(packages)

        self._fetchStats = FetchStats(downloads)
        sizestr = self._prettyfsize(self._fetchStats.TotalSize())
        print 'Download size: %s from %s' % ( sizestr, self._mirror)

        self._garbage.IndexCurrentFiles(self._tgtdir, mindepth=1)

        if self._optiondict['DummyDownload']:
            self._doDummyDownloading(downloads)
        else:
            self._doDownloading(packages, downloads)

    def GetGarbage(self):
        if self._optiondict['DummyDownload']:
            return None
        else:
            return self._garbage

    def Cancel(self, flag=True):
        """Signal that downloading should be terminated"""
        self._cancelling = flag


    def MakeTemplate(self, stream, userpkgs=None):
        """Generate template package listing file"""

        (header, pkgdict) = self._getPkgDict()
        try:
            self._listLock.acquire()
            catgroups = self._masterlist.GetCategories()
        finally:
            self._listLock.release()
        catlist = [ c for c in catgroups.iterkeys() if c != 'All' ]
        catlist.sort()

        def descfix(s):
            return s.replace('\n', ' ').replace('\r', '')
            # s.replace more portable between python-2.x & 3.x than s.translate

        print >>stream, '# Package listing for pmcyg (Cygwin(TM) Partial Mirror)\n# Autogenerated on %s\n# from: %s\n' % ( time.asctime(), self.GetIniURL() )
        print >>stream, '# This file contains listings of cygwin package names, one per line.\n# Lines starting with \'#\' denote comments, with blank lines being ignored.\n# The dependencies of any package listed here should be automatically\n# included in the mirror by pmcyg.'

        for cat in catlist:
            print >>stream, '\n\n##\n## %s\n##' % cat

            for pkg in catgroups[cat]:
                desc = descfix(pkgdict[pkg].get('sdesc_curr', ''))
                prefix = '#'
                if userpkgs and pkg in userpkgs: prefix=''
                print >>stream, '%s%-24s  \t# %s' % ( prefix, pkg, desc )


    def _getPkgDict(self):
        """Return, possibly cached, package dictionary from setup.ini file"""
        (hdr, pkgs) = (None, None)
        try:
            self._listLock.acquire()
            cached = self._masterlist.HasCachedData()
            if not cached:
                print 'Scanning mirror index at %s...' % self._masterlist.GetSourceURL(),
                sys.stdout.flush()

            (hdr, pkgs) = self._masterlist.GetHeaderAndPackages()

            if not cached:
                print ' done'
        finally:
            self._listLock.release()

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
                "The following package names were not recognized:\n\t%s\n" \
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

        for pkg in packages:
            pkginfo = pkgdict[pkg]

            for vrt in variants:
                try:
                    flds = pkginfo[vrt].split()
                    pkgref = flds[0]
                    pkgsize = int(flds[1])
                    pkghash = flds[2]
                    downloads.append((pkgref, pkgsize, pkghash))
                except KeyError:
                    print >>sys.stderr, 'Cannot find package filename for %s in variant \'%s\'' % (pkg, vrt)

        return downloads


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
        fp = open(spath, 'wt')
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
        fp.close()
        fp = open(spath, 'rb')
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


    def _doDummyDownloading(self, downloads):
        """Rehearse downloading of files from Cygwin mirror"""

        for (pkgfile, pkgsize, pkghash) in downloads:
            print '  %s (%s)' % ( os.path.basename(pkgfile),
                                self._prettyfsize(pkgsize) )

    def _doDownloading(self, packages, downloads):
        """Download files from Cygwin mirror to create local partial copy"""

        if not os.path.isdir(self._tgtdir):
            os.makedirs(self._tgtdir)

        self._buildSetupFiles(packages)

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
            self._garbage.RescueFile(tgtpath)
            mirpath = urlparse.urljoin(self._mirror, pkgfile)

            print '  %s (%s)...' % ( os.path.basename(pkgfile),
                                    self._prettyfsize(pkgsize) ),
            sys.stdout.flush()

            try:
                succ_msg = None
                if os.path.isfile(tgtpath) and os.path.getsize(tgtpath) == pkgsize:
                    succ_msg = 'already present'
                    self._fetchStats.AddAlready(pkgfile, pkgsize)
                else:
                    dlsize = 0
                    urllib.urlretrieve(mirpath, tgtpath)
                    dlsize = os.path.getsize(tgtpath)
                    if dlsize != pkgsize:
                        raise IOError, 'Mismatched package size (deficit=%s)' \
                                        % ( self._prettyfsize(pkgsize - dlsize) )
                    succ_msg = 'done'
                    self._fetchStats.AddNew(pkgfile, pkgsize)

                if not self._hashCheck(tgtpath, pkghash):
                    os.remove(tgtpath)
                    raise IOError, 'Mismatched checksum'

                print ' %s' % succ_msg
            except Exception, ex:
                print ' FAILED\n  -- %s' % ( str(ex) )
                self._fetchStats.AddFail(pkgfile, pkgsize)

        counts = self._fetchStats.Counts()
        if not counts['Fail']:
            print '%d package(s) mirrored, %d new' % ( counts['Total'], counts['New'] )
        else:
            print '%d/%d package(s) failed to download' % ( counts['Fail'], counts['Total'] )


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

        return (dlhash == pkghash)

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

    def _prettyfsize(self, size):
        """Pretty-print file size, autoscaling units"""
        divisors = [ ( 1<<30, 'GB' ), ( 1<<20, 'MB' ), ( 1<<10, 'kB' ), ( 1, 'B' ) ]

        for div, unit in divisors:
            qsize = float(size) / div
            if qsize > 0.8:
                return '%.3g%s' % ( qsize, unit )

        return '%dB' % ( size )



"""Database of available Cygwin packages built from 'setup.ini' file"""
class MasterPackageList(object):
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
            fp = URLopen(self._iniURL)
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
            line = line.decode('ascii')
            lineno += 1

            if self._inquote and self._fieldname:
                self._ingestQuotedLine(line)
            else:
                self._ingestOrdinaryLine(line, lineno=lineno)

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

    def _ingestOrdinaryLine(self, line, lineno=None):
        """Classify current line as package definition/field etc"""
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
            quotepos = matches.group(2).find('"')
            if quotepos < 0:
                # Field value appears without quotation marks on single line:
                self._pkgdict[self._fieldname] = self._fieldtext
            if quotepos >= 0:
                if quotepos > 0:
                    # Field value contains additional metadata prefix:
                    prefix = self._fieldtext[0:quotepos].strip()
                    self._fieldname += '_' + prefix
                    self._fieldtext = self._fieldtext[(quotepos+1):]
                if self._fieldtext[1:].endswith('"'):
                    # Quoted string starts and ends on current line:
                    self._pkgdict[self._fieldname] = self._fieldtext[1:-1]
                else:
                    # Quoted string starts on current line, presumably ending later:
                    self._fieldlines = [ self._fieldtext[1:] ]
                    self._inquote = True

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
## Download statistics
##

class FetchStats(object):
    def __init__(self, downloads=None):
        # Record of total bytes downloaded:
        self._newSize = 0
        self._alreadySize = 0
        self._failSize = 0
        self._totalSize = 0

        # Record of total numbers of packages:
        self._newCount = 0
        self._alreadyCount = 0
        self._failCount = 0
        self._totalCount = 0

        if downloads:
            self._totalSize = sum([size for (ref, size, hash) in downloads])
            self._totalCount = len(downloads)

    def TotalSize(self):
        return self._totalSize

    def Counts(self):
        return { 'Total': self._totalCount,
                'New': self._newCount,
                'Already': self._alreadyCount,
                'Fail': self._failCount }

    def Failures(self):
        return self._failCount

    def AddNew(self, pkg, size):
        self._newSize += size
        self._newCount += 1

    def AddAlready(self, pkg, size):
        self._alreadySize += size
        self._alreadyCount += 1

    def AddFail(self, pkg, size):
        self._failSize += size
        self._failCount += 1



##
## Garbage-collection mechanisms
##

class GarbageCollector(object):
    def __init__(self, topdir=None):
        self._topdir = None
        self._topdepth = 0
        self._suspicious = True

        self._susDirnames = [ 'bin', 'sbin', 'home',
                            'My Documents', 'WINNT', 'system32' ]
        self._susFilenames = [ '.bashrc', '.bash_profile', '.login', '.tcshrc']

        if topdir:
            self.IndexCurrentFiles(topdir)

    def IndexCurrentFiles(self, topdir, mindepth=0):
        """Build list of files and directories likely to be deleted"""
        self._topdir = topdir
        self._directories = []
        self._files = []
        if os.path.isdir(topdir):
            self._suspicious = self._checkTopSuspiciousness()
        else:
            self._suspicious = False
            return

        topdir = os.path.normpath(topdir)
        self._topdepth = self._calcDepth(topdir)

        for dirpath, dirnames, filenames in os.walk(topdir, topdown=False):
            self._suspicious |= self._checkNodeSuspiciousness(dirnames, filenames)

            dirdepth = self._calcDepth(dirpath)
            if (dirdepth - self._topdepth) < mindepth:
                continue

            for subdir in dirnames:
                self._directories.append(self._canonPath(dirpath, subdir))
            for fname in filenames:
                fullname = self._canonPath(dirpath, fname)
                self._files.append(fullname)
                if os.path.islink(fullname):
                    self._suspicious = True

    def RescueFile(self, filename):
        """Signal that file should not be included in deletions list"""

        filename = self._canonPath(filename)
        dirname, basename = os.path.split(filename)
        try:
            self._files.remove(filename)
        except:
            pass

        dirsegs = dirname.split(os.sep)
        maxdepth = len(dirsegs)
        mindepth = max((self._topdepth - 1), 0)
        for depth in range(maxdepth, mindepth, -1):
            pardir = self._canonPath(os.sep.join(dirsegs[0:depth]))
            try:
                self._directories.remove(pardir)
            except:
                pass

    def GetNfiles(self):
        return len(self._files)

    def GetFileList(self):
        return self._files

    def GetDirectoryList(self):
        return self._directories

    def GetNeatList(self):
        dirprefix = self._topdir
        if not dirprefix.endswith(os.sep):
            dirprefix += os.sep
        prefixlen = len(dirprefix)

        allfiles = []
        for fl in self._files + self._directories:
            if fl.startswith(dirprefix):
                allfiles.append(os.path.join('[.]', fl[prefixlen:]))
            else:
                allfiles.append(fl)
        allfiles.sort()

        return allfiles

    def IsSuspicious(self):
        return self._suspicious

    def PurgeFiles(self):
        try:
            for fl in self._files:
                os.remove(fl)
            rdirs = self._directories

            # Use reverse-alphabetic sort to approximate depth-first dirsearch:
            rdirs.sort()
            rdirs.reverse()
            for dr in rdirs:
                os.rmdir(dr)
        except Exception, ex:
            print >>sys.stderr, 'Failed to remove outdated files - %s' % str(ex)

    def _checkTopSuspiciousness(self):
        """Try to protect user from accidentally deleting anything other than an old Cygwin repository"""
        toplist = os.listdir(self._topdir)
        releasedirs = 0
        subdirs = 0
        topfiles = 0
        for entry in toplist:
            fullname = os.path.join(self._topdir, entry)
            if os.path.isdir(fullname):
                subdirs += 1
                if entry.startswith('release'):
                    releasedirs += 1
            else:
                topfiles += 1

        return (topfiles > 10) or (subdirs > releasedirs)

    def _checkNodeSuspiciousness(self, dirnames, filenames):
        for dname in dirnames:
            if dname in self._susDirnames:
                return True

        for fname in filenames:
            if fname in self._susFilenames:
                return True

        return False

    def _calcDepth(self, dirname):
        return len(dirname.split(os.sep))

    def _canonPath(self, path, *suffixes):
        """Create canonical form of filename/dirname from path components"""
        return os.path.normpath(os.path.join(path, *suffixes))


class GarbageConfirmer(object):
    """Mechanism for inviting user to confirm disposal of outdated files"""

    def __init__(self, garbage, default='no'):
        self._garbage = garbage
        default = default.lower()
        self._userresponse = None

        if default == 'no' or not garbage:
            self._userresponse = 'no'
        elif default == 'yes' and not garbage.IsSuspicious():
            self._userresponse = 'yes'
        else:
            allfiles = self._garbage.GetNeatList()
            if allfiles:
                self._askUser(allfiles)
            else:
                self._userresponse = 'no'

    def HasResponded(self):
        return self._userresponse

    def ActionResponse(self):
        if not self.HasResponded():
            self._awaitResponse()
        if self._userresponse == 'yes':
            print 'Deleting %d files' % self._garbage.GetNfiles()
            self._garbage.PurgeFiles()

    def _askUser(self, allfiles):
        print '\nThe following files are outdated:'
        for fl in allfiles:
            print '  %s' % fl

        try:
            response = raw_input('Delete outdate files [YES/no]: ')
            if response == 'YES':
                self._userresponse = 'yes'
            else:
                self._userresponse = 'no'
        except:
            pass

    def _awaitResponse(self):
        pass    # assume that _askUser blocks until user responds



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
        self.rmvold_var = Tk.StringVar()
        self.rmvold_var.set(builder.GetOption('RemoveOutdated'))

        menubar = self.mkMenuBar(rootwin)
        rootwin.config(menu=menubar)

        self.mirror_menu = None
        parampanel = self.mkParamPanel(rootwin)
        parampanel.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.W)
        row += 1

        self.status_txt = ScrolledText.ScrolledText(rootwin, height=16)
        self.status_txt.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.S+Tk.W, padx=4, pady=(6,2))
        rootwin.grid_rowconfigure(row, weight=1)
        sys.stdout = GUIstream(self)
        sys.stderr = GUIstream(self, highlight=True)
        self.message_queue = Queue.Queue()
        row += 1

        self.progress_bar = GUIprogressBar(rootwin)
        self.progress_bar.grid(row=row, column=0, sticky=Tk.E+Tk.W+Tk.S, padx=4, pady=2)
        row += 1

        self._state = GUIstate(self)
        self._updateState(GUIconfigState(self))

    def Run(self):
        self._renewMirrorMenu = False
        self.mirrorthread = GUImirrorThread(self)
        self.mirrorthread.setDaemon(True)
        self.mirrorthread.start()

        def tick():
            # Check if list of mirror sites is available yet:
            if self._renewMirrorMenu and not self.mirrorthread.isAlive():
                self.mirror_menu = self.mkMirrorMenu()
                self.mirror_btn.config(menu=self.mirror_menu)
                self.mirror_btn.config(state=Tk.NORMAL)
                self._renewMirrorMenu = False

            try:
                newstate = self._state.tick()
                self._updateState(newstate)
            except Exception, ex:
                print >>sys.stderr, 'Unhandled exception in GUI event loop - %s'% str(ex)

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
        filemenu.add_separator()
        filemenu.add_command(label='Quit', command=rootwin.quit)
        menubar.add_cascade(label='File', menu=filemenu)

        # 'Build' menu:
        self.buildmenu = Tk.Menu(menubar, tearoff=0)
        self.buildmenu.add_command(label='Start', command=self.doBuildMirror)
        self.buildmenu.add_command(label='Cancel', command=self.doCancel)
        menubar.add_cascade(label='Build', menu=self.buildmenu)

        # 'Options' menu:
        optmenu = Tk.Menu(menubar, tearoff=0)
        for attr, opt, flip, descr in self._boolopts:
            tkvar = self.__getattribute__(attr)
            optmenu.add_checkbutton(label=descr, variable=tkvar)
        rmvmenu = Tk.Menu(optmenu, tearoff=0)
        for opt in [ 'no', 'ask', 'yes' ]:
            rmvmenu.add_radiobutton(label=opt, variable=self.rmvold_var,
                                value=opt, command=self.setRemoveOld)
        optmenu.add_cascade(label='Remove outdated', menu=rmvmenu)
        menubar.add_cascade(label='Options', menu=optmenu)

        # 'Help' menu:
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

    def clearHist(self):
        """Clear history window"""
        self.status_txt.config(state=Tk.NORMAL)
        self.status_txt.delete('1.0', Tk.END)
        self.status_txt.config(state=Tk.DISABLED)

    def mkTemplate(self):
        """GUI callback for creating template package-list file"""
        self._txFields()

        tpltname = tkFileDialog.asksaveasfilename(title='Create pmcyg package-listing template', initialfile='pmcyg-template.pkgs')
        if not tpltname: return

        thrd = GUItemplateThread(self, tpltname)
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
- a tool for creating Cygwin(TM) partial mirrors
Version %s

Copyright © 2009-2010 RW Penney

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
        opendlg = tkFileDialog.askopenfilenames
        if broken_openfilenames:
            def opendlg(*args, **kwargs):
                filename = tkFileDialog.askopenfilename(*args, **kwargs)
                if filename: return (filename, )
                else: return None

        pkgfiles = opendlg(title='pmcyg user-package lists')

        if pkgfiles:
            self.pkgfiles = [ os.path.normpath(pf) for pf in pkgfiles ]
            self.pkgs_entry.config(state=Tk.NORMAL)
            self.pkgs_entry.delete(0, Tk.END)
            self.pkgs_entry.insert(0, '; '.join(self.pkgfiles))
            self.pkgs_entry.config(state='readonly')

    def cacheSelect(self):
        """Callback for selecting directory into which to download packages"""
        dirname = tkFileDialog.askdirectory(initialdir=self.cache_entry.get(),
                                mustexist=False, title='pmcyg cache directory')
        if dirname:
            self.cache_entry.delete(0, Tk.END)
            self.cache_entry.insert(0, os.path.normpath(dirname))

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

    def setRemoveOld(self):
        self.builder.SetOption('RemoveOutdated', self.rmvold_var.get())

    def doBuildMirror(self):
        self._txFields()
        self._updateState(GUIbuildState(self))

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

    def updateProgress(self):
        self.progress_bar.Update(self.builder._fetchStats)

    def _txFields(self):
        """Transfer values of GUI controls to PMbuilder object"""

        self.builder.SetTargetDir(self.cache_entry.get())
        self.builder.SetExeURL(self.setup_entry.get())

        newmirror = self.mirror_entry.get()
        if newmirror != self.builder.GetMirrorURL():
            self.builder.SetMirrorURL(newmirror)



class GUIstate(object):
    """Base class for processing state of GUI"""
    def __init__(self, parent):
        self._parent = parent

    def tick(self):
        return self

    def enter(self):
        pass

    def leave(self):
        pass


class GUIconfigState(GUIstate):
    def __init__(self, parent):
        GUIstate.__init__(self, parent)
        def btn(state):
            # Update 'build' button to avoid multiple builder threads:
            buttonId = parent.buildmenu.index('Start')
            parent.buildmenu.entryconfig(buttonId, state=state)
        self._buttonConfig = btn

    def tick(self):
        return self

    def enter(self):
        self._buttonConfig(Tk.NORMAL)

    def leave(self):
        self._buttonConfig(Tk.DISABLED)


class GUIbuildState(GUIstate):
    def __init__(self, parent):
        GUIstate.__init__(self, parent)
        self._buildthread = None

    def tick(self):
        self._parent.updateProgress()
        if self._buildthread and not self._buildthread.isAlive():
            return GUItidyState(self._parent)
        return self

    def enter(self):
        buildthread = GUIfetchThread(self._parent)
        buildthread.setDaemon(True)
        buildthread.start()
        self._buildthread = buildthread

    def leave(self):
        self._buildthread = None
        print '\n'


class GUItidyState(GUIstate):
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
        self._confirmer = GUIgarbageConfirmer(self._builder.GetGarbage(), default=policy)

    def leave(self):
        pass



class GUIstream(object):
    """Wrapper for I/O stream for use in GUI"""

    def __init__(self, parent, highlight=False):
        self.parent = parent
        self.highlight = highlight

    def flush(self):
        pass

    def write(self, string):
        self.parent.message_queue.put_nowait((string, self.highlight))



class GUIfetchThread(threading.Thread):
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


class GUItemplateThread(threading.Thread):
    """Asynchronous generation of template list of packages"""
    def __init__(self, parent, filename):
        threading.Thread.__init__(self, target=self.mktemplate)
        self.parent = parent
        self.filename = filename

    def mktemplate(self):
        builder = self.parent.builder
        usrpkgs = None

        try:
            if self.parent.pkgfiles:
                usrpkgs = builder.ReadPackageLists(self.parent.pkgfiles)
            fp = open(self.filename, 'wt')
            builder.MakeTemplate(fp, usrpkgs)
            fp.close()
            print 'Generated template file "%s"' % ( self.filename )
        except Exception, ex:
            print >>sys.stderr, 'Failed to create "%s" - %s' % ( self.filename, str(ex) )


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
        txt = ScrolledText.ScrolledText(topwin, height=16, width=60)
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
        garbage = builder.GetGarbage()
        confirmer = GarbageConfirmer(garbage,
                                default=builder.GetOption('RemoveOutdated'))
        confirmer.ActionResponse()
    except BaseException, ex:
        print >>sys.stderr, 'Fatal error during mirroring [%s]' % ( repr(ex) )


def TemplateMain(builder, outfile, pkgfiles):
    """Subsidiary program entry-point for command-line list generation"""

    usrpkgs = None
    if pkgfiles:
        usrpkgs = builder.ReadPackageLists(pkgfiles)

    fp = open(outfile, 'wt')
    builder.MakeTemplate(fp, usrpkgs)
    fp.close()


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
    advopts.add_option('--remove-outdated', '-o', type='string', default='no',
            help='remove old versions of packages [no/yes/ask]')
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
    builder.SetOption('RemoveOutdated', opts.remove_outdated)

    if opts.pkg_file:
        TemplateMain(builder, opts.pkg_file, remargs)
    elif HASGUI and not opts.nogui:
        GUImain(builder, remargs)
    else:
        PlainMain(builder, remargs)


if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
