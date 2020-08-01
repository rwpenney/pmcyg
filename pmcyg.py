#!/usr/bin/python3
# Partially mirror 'Cygwin' distribution
# (C)Copyright 2009-2020, RW Penney <rwpenney@users.sourceforge.net>

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


PMCYG_VERSION = '2.4.2'

DEFAULT_INSTALLER_URL = 'http://cygwin.com/setup${_arch}.exe'
#DEFAULT_CYGWIN_MIRROR = 'ftp://cygwin.com/pub/cygwin/'
DEFAULT_CYGWIN_MIRROR = 'http://www.mirrorservice.org/sites/sourceware.org/pub/cygwin'
CYGWIN_MIRROR_LIST_URL = 'http://cygwin.com/mirrors.lst'

# Character encoding used by the setup.ini file.
# This should probably by 'ascii', but occasional unicode characters
# have been observed within official set.ini files.
SI_TEXT_ENCODING = 'utf-8'


import  argparse, bz2, codecs, hashlib, io, os, os.path, re, \
        string, subprocess, sys, threading, time, \
        urllib.request, urllib.parse, urllib.error, urllib.parse
try:
    import tkinter as Tk
    import queue, tkinter.scrolledtext, tkinter.filedialog
    HASGUI = True
except:
    class Tk: Canvas = object; Button = object
    HASGUI = False

HOST_IS_CYGWIN = (sys.platform == 'cygwin')



def ConcatShortDescription(desc):
    """Concatenate multi-line short package description into single line"""
    if desc:
        return desc.replace('\n', ' ').replace('\r', '').rstrip()
        # s.replace is more portable between python-2.x & 3.x than s.translate
    else:
        return '???'
        # A null or empty short-description shouldn't go unnoticed


class PMCygException(Exception):
    """Wrapper for internally generated exceptions"""

    def __init__(self, *args):
        Exception.__init__(self, *args)


class BuildViewer:
    """Conduit for status messages from PMbuilder and related classes,
    roughly corresponding to the Observer pattern."""
    SEV_mask =      0x0f        # Severity levels
    SEV_GOOD =      0x00          # Particularly good news
    SEV_NORMAL =    0x01          # Ordinary news
    SEV_WARNING =   0x02          # Significant news
    SEV_ERROR =     0x03          # Disastrous news

    VRB_mask =      0xf0        # Verbosity levels
    VRB_LOW =       0x00          # Essential messages
    VRB_MEDIUM =    0x10          # Informative messages
    VRB_HIGH =      0x20          # Debugging messages

    def __init__(self, verbosity=VRB_MEDIUM):
        self._operation = None
        self._verbThresh = verbosity

    def __call__(self, text, ctrl=SEV_NORMAL | VRB_MEDIUM):
        self.message(text, ctrl)

    def message(self, text, ctrl=SEV_NORMAL | VRB_MEDIUM):
        if self._operation:
            self._emit('  >>>\n', self._operation[1])
        self._emit('{0}\n'.format(text), ctrl)
        if self._operation:
            self._emit('  >>> {0}...'.format(self._operation[0]),
                       self._operation[1])

    def startOperation(self, text, ctrl=VRB_MEDIUM):
        self._operation = (text, ((ctrl & self.VRB_mask) | self.SEV_NORMAL))
        self._emit('{0}...'.format(text), self.SEV_NORMAL)

    def endOperation(self, text, ctrl=SEV_NORMAL):
        if not self._operation:
            return
        opVerbosity = (self._operation[1] & self.VRB_mask)
        self._emit(' {0}\n'.format(text),
                   ((ctrl & self.SEV_mask) | opVerbosity))
        self._operation = None

    def flushOperation(self):
        if not self._operation:
            return
        self._emit('\n', (self._operation[1] & self.VRB_mask))
        self._operation = None

    def _emit(self, text, ctrl):
        if (ctrl & self.VRB_mask) > self._verbThresh:
            return
        self._output(text, (ctrl & self.SEV_mask))

    def _output(self, text, severity): pass


class SilentBuildViewer(BuildViewer):
    def __init__(self):
        BuildViewer.__init__(self)

    def _output(self, text, severity): pass


class ConsoleBuildViewer(BuildViewer):
    """Status-message observer using stdout/stderr."""
    def __init__(self):
        BuildViewer.__init__(self)

    def _output(self, text, severity):
        stream = sys.stdout
        if severity > self.SEV_NORMAL:
            stream = sys.stderr

        stream.write(text)
        stream.flush()



class BuildReporter:
    """Mixin class for hosting a BuildViewer object."""
    def __init__(self, Viewer=None, Peer=None):
        self._statview = None
        if isinstance(Peer, BuildReporter) and not Viewer:
            Viewer = Peer._statview
        BuildReporter.SetViewer(self, Viewer)

    def SetViewer(self, Viewer):
        if not Viewer:
            Viewer = ConsoleBuildViewer()
        self._statview = Viewer



class SetupIniFetcher:
    """Facade for fetching setup.ini from URL,
    with optional bz2-decompression"""
    MaxIniFileLength = 1 << 24

    def __init__(self, URL):
        self._buffer = None
        with urllib.request.urlopen(URL) as stream:
            expander = lambda x: x
            if URL.endswith('.bz2'):
                expander = bz2.decompress
            rawfile = expander(stream.read(self.MaxIniFileLength))

        self._buffer = io.StringIO(rawfile.decode(SI_TEXT_ENCODING,
                                                        'ignore'))

    def __del__(self):
        if self._buffer:
            self._buffer.close()

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._buffer)

    def close(self):
        self._buffer.close()



class HashChecker:
    """Mechanism for checking md5/sha512 hash-code of downloaded packages.

    This includes heuristics for guessing a suitable hashing algorithm
    based on the length of a supplied hexadecimal hash code.
    """

    len2alg = {}

    def __call__(self, path, tgthash, blksize=1<<14):
        hasher = self._guessHashAlg(tgthash)

        try:
            with open(path, 'rb') as fp:
                while True:
                    chunk = fp.read(blksize)
                    if not chunk:
                        break
                    hasher.update(chunk)
        except:
            return False

        filehash = hasher.hexdigest().lower()

        return (filehash == tgthash.lower())

    @classmethod
    def _guessHashAlg(cls, tgthash):
        """Construct a digest object based length of given hex hash string."""
        if not cls.len2alg:
            algs = [ 'md5', 'sha1', 'sha256', 'sha512' ]
            try:
                algs.extend(hashlib.algorithms_guaranteed)
                algs.extend(hashlib.algorithms_available)
            except AttributeError:
                pass
            for alg in algs:
                hashlen = 2 * hashlib.new(alg).digest_size
                cls.len2alg.setdefault(hashlen, alg)

        hashlen = len(tgthash)
        try:
            alg = cls.len2alg[hashlen]
            return hashlib.new(alg)
        except:
            raise PMCygException('Unrecognized hash length {}'.format(hashlen))



class PMbuilder(BuildReporter):
    """Utility class for constructing partial mirror
    of Cygwin(TM) distribution"""
    DL_Success =        1
    DL_AlreadyPresent = 2
    DL_SizeError =      3
    DL_HashError =      4
    DL_Failure =        5

    def __init__(self, BuildDirectory='.',
                MirrorSite=DEFAULT_CYGWIN_MIRROR,
                CygwinInstaller=DEFAULT_INSTALLER_URL,
                Viewer=None, **kwargs):

        BuildReporter.__init__(self, Viewer)
        self._hashCheck = HashChecker()

        # Directory into which to assemble local mirror:
        self._tgtdir = BuildDirectory

        # URL of source of Cygwin installation program 'setup.exe':
        self._exeurl = CygwinInstaller

        # URL of Cygwin mirror site, hosting available packages:
        self.mirror_url = MirrorSite

        # URL of Cygwin package database file (derived from _mirror if 'None'):
        self._iniurl = None

        # System architecture that Cygwin should target
        self._cygarch = 'x86'

        # Set of package age descriptors:
        self._epochs = ['curr']

        self._masterList = MasterPackageList(Viewer=Viewer)
        self._pkgProc = PkgSetProcessor(self._masterList)
        self._garbage = GarbageCollector(Viewer=Viewer)
        self._cancelling = False
        self._mirrordict = None
        self._optiondict = {
            'AllPackages':      False,
            'DummyDownload':    False,
            'IncludeBase':      True,
            'MakeAutorun':      False,
            'IncludeSources':   False,
            'RemoveOutdated':   'no',
            'ISOfilename':      None
        }

        self._fetchStats = FetchStats()
        self._cygcheck_list = []
        for (opt, val) in kwargs.items():
            self.SetOption(opt, val)

    def SetViewer(self, Viewer):
        BuildReporter.SetViewer(self, Viewer)
        self._masterList.SetViewer(self._statview)
        self._pkgProc.SetViewer(self._statview)
        self._garbage.SetViewer(self._statview)

    def GetTargetDir(self):
        return self._tgtdir

    def SetTargetDir(self, tgtdir):
        """Set the root directory beneath which packages will be downloaded"""
        self._tgtdir = tgtdir

    @property
    def setup_exe_url(self):
        """The URL of the setup.exe Cygwin installer"""
        keywords = { 'arch': self._cygarch,
                     '_arch': '-' + self._cygarch }
        exe_expr = self._exeurl
        if not exe_expr:
            exe_expr = DEFAULT_INSTALLER_URL
        exe_template = string.Template(exe_expr)
        return exe_template.substitute(keywords)

    @setup_exe_url.setter
    def setup_exe_url(self, URL):
        self._exeurl = URL

    @property
    def mirror_url(self):
        """The URL of the mirror site from which to download Cygwin packages"""
        return self._mirror

    @mirror_url.setter
    def mirror_url(self, URL):
        if not URL.endswith('/'):
            URL += '/'
        self._mirror = URL

    @property
    def setup_ini_url(self):
        """The (architecture-dependent) URL for the setup.ini package-list."""
        if self._iniurl:
            # Use prescribed URL directly:
            return self._iniurl
        else:
            # Base URL on chosen mirror site, and selected architecture:
            if self._cygarch:
                basename = '{0}/setup.bz2'.format(self._cygarch)
            else:
                basename = 'setup.bz2'
            return urllib.parse.urljoin(self._mirror, basename)

    @setup_ini_url.setter
    def setup_ini_url(self, URL):
        self._iniurl = URL
        self._masterList.SetSourceURL(self.setup_ini_url)

    def GetArch(self):
        return self._cygarch

    def SetArch(self, arch):
        self._cygarch = arch

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
            raise PMCygException('Invalid configuration option "{0}"' \
                                    ' for PMBuilder'.format(optname))
        return oldval


    def ReadMirrorList(self, reload=False):
        """Construct list of Cygwin mirror sites"""

        if self._mirrordict and not reload:
            return self._mirrordict

        self._mirrordict = {}

        try:
            fp = urllib.request.urlopen(CYGWIN_MIRROR_LIST_URL)
        except:
            self._statview('Failed to read list of Cygwin mirrors' \
                           ' from {0}'.format(CYGWIN_MIRROR_LIST_URL),
                           BuildViewer.SEV_WARNING)
            fp = self._makeFallbackMirrorList()

        for line in fp:
            line = line.decode('ascii', 'ignore').strip()
            if not line: continue
            (url, ident, region, country) = line.split(';')
            regdict = self._mirrordict.setdefault(region, {})
            regdict.setdefault(country, []).append((ident, url))

        fp.close()
        return self._mirrordict


    def ListInstalled(self):
        """Generate list of all packages on existing Cygwin installation"""

        if not HOST_IS_CYGWIN: return []
        if self._cygcheck_list: return self._cygcheck_list

        re_colhdr = re.compile(r'^Package\s+Version')
        re_exclusions = re.compile(r'^ _ .* (?:rebase|update)', re.VERBOSE)
        pkgs = []

        try:
            proc = subprocess.Popen(['/bin/cygcheck.exe', '-cd'],
                                    shell=False, stdout=subprocess.PIPE,
                                    close_fds=True)
            inHeader = True
            for line in proc.stdout:
                line = line.decode('ascii', 'ignore').strip()
                if inHeader and re_colhdr.match(line):
                    inHeader = False
                    continue
                if not inHeader:
                    pkgname = line.split()[0]
                    if not re_exclusions.match(pkgname):
                        pkgs.append(pkgname)
            proc.wait()
        except Exception as ex:
            self._statview('Listing installed packages failed - {}' \
                                .format(str(ex)),
                           BuildViewer.SEV_ERROR)
        self._cygcheck_list = pkgs
        return pkgs


    def UpdatePackageLists(self, filenames, bckp=".orig"):
        self._masterList.SetSourceURL(self.setup_ini_url)
        self._pkgProc.UpdatePackageLists(filenames, bckp)


    def BuildMirror(self, pkgset):
        """Download and configure packages into local directory

        Resolved the dependencies of the supplied PackageSet,
        and trigger downloading of all Cygwin packages
        together with installer artefacts."""

        self._cancelling = False
        self._masterList.SetSourceURL(self.setup_ini_url)

        userpackages = []
        if pkgset:
            userpackages = pkgset.extract(arch=self._cygarch)
        packages = self._resolveDependencies(userpackages)
        downloads = self._buildFetchList(packages)

        self._fetchStats = FetchStats(downloads)
        sizestr = self._prettyfsize(self._fetchStats.TotalSize())
        self._statview('Download size: {0} from {1}'.format(sizestr,
                                                            self._mirror))

        archdir = self._getArchDir()
        noarchdir = os.path.join(archdir, '..', 'noarch')
        self._garbage.IndexCurrentFiles([archdir, noarchdir], mindepth=1)

        if self._optiondict['DummyDownload']:
            self._doDummyDownloading(downloads)
        else:
            self._doDownloading(packages, downloads)

    def BuildISO(self, isoname):
        """Convert local downloads into an ISO image for burning to CD"""

        argv = [ 'genisoimage', '-o', isoname, '-quiet',
                '-V', 'Cygwin(pmcyg)-' + time.strftime('%d%b%y'),
                '-r', '-J', self._tgtdir ]

        self._statview.startOperation('Generating ISO image in ' + isoname)
        if self._optiondict['DummyDownload']:
            self._statview.endOperation(' (dummy)')
            return

        retcode = subprocess.call(argv, shell=False)
        if not retcode:
            self._statview.endOperation('done')
        else:
            self._statview.endOperation('FAILED (errno={0:d})'.format(retcode),
                                        BuildViewer.SEV_ERROR)

    def GetGarbage(self):
        if self._optiondict['DummyDownload']:
            return None
        else:
            return self._garbage

    def Cancel(self, flag=True):
        """Signal that downloading should be terminated"""
        self._cancelling = flag

    def TemplateFromLists(self, outfile, pkgfiles, cygwinReplica=False):
        """Wrapper for PkgSetProcessor.MakeTemplate(),
        taking collection of package files"""
        self._masterList.SetSourceURL(self.setup_ini_url)

        pkgset = PackageSet(pkgfiles)
        if cygwinReplica:
            pkgset.extend(self.ListInstalled())

        with codecs.open(outfile, 'w', SI_TEXT_ENCODING) as fp:
            self._pkgProc.MakeTemplate(fp, pkgset, terse=cygwinReplica)

    @staticmethod
    def _makeFallbackMirrorList():
        """Supply a static list of official Cygwin mirror sites,
        as a fall-back in case the live listing of mirrors cannot
        be downloaded."""
        return io.BytesIO(b'''
ftp://ucmirror.canterbury.ac.nz/pub/cygwin/;ucmirror.canterbury.ac.nz;Australasia;New Zealand
http://ucmirror.canterbury.ac.nz/cygwin/;ucmirror.canterbury.ac.nz;Australasia;New Zealand
ftp://mirror.csclub.uwaterloo.ca/cygwin/;mirror.csclub.uwaterloo.ca;Canada;Ontario
http://mirror.csclub.uwaterloo.ca/cygwin/;mirror.csclub.uwaterloo.ca;Canada;Ontario
ftp://ftp.fsn.hu/pub/cygwin/;ftp.fsn.hu;Europe;Hungary
ftp://ftp.iij.ad.jp/pub/cygwin/;ftp.iij.ad.jp;Asia;Japan
http://ftp.iij.ad.jp/pub/cygwin/;ftp.iij.ad.jp;Asia;Japan
ftp://cygwin.osuosl.org/pub/cygwin/;cygwin.osuosl.org;United States;Oregon
http://cygwin.osuosl.org/;cygwin.osuosl.org;United States;Oregon
http://mirrors.dotsrc.org/cygwin/;mirrors.dotsrc.org;Europe;Denmark
http://www.mirrorservice.org/sites/sourceware.org/pub/cygwin/;www.mirrorservice.org;Europe;UK
                ''')

    def _resolveDependencies(self, usrpkgs=None):
        """Constuct list of packages, including all their dependencies"""

        selected = self._extendPkgSelection(usrpkgs)
        return self._pkgProc.ExpandDependencies(selected, self._epochs)

    def _extendPkgSelection(self, userpkgs=None):
        """Amend list of packages to include base or default packages"""

        pkgset = set()

        pkgdict = self._masterList.GetPackageDict()
        if not pkgdict:
            return pkgset

        if userpkgs == None:
            # Setup minimalistic set of packages
            userpkgs = ['base-cygwin', 'base-files', 'bash',
                        'bzip2', 'coreutils', 'dash', 'gzip',
                        'tar', 'unzip', 'zip']

        if self._optiondict['AllPackages']:
            userpkgs = []
            for pkg, pkginfo in pkgdict.items():
                if pkg.startswith('_'): continue
                cats = pkginfo.GetAny('category').split()
                if '_obsolete' in cats: continue
                userpkgs.append(pkg)

        pkgset.update(userpkgs)

        if self._optiondict['IncludeBase']:
            # Include all packages from 'Base' category:
            for pkg, pkginfo in pkgdict.items():
                cats = pkginfo.GetAny('category').split()
                if 'Base' in cats:
                    pkgset.add(pkg)

        return pkgset

    def _buildFetchList(self, packages):
        """Convert list of packages into set of files to fetch from Cygwin server"""
        pkgdict = self._masterList.GetPackageDict()

        # Construct list of compiled/source/current/previous variants:
        downloads = []

        for pkg in packages:
            pkginfo = pkgdict[pkg]

            hasDependencies = pkginfo.HasDependencies()

            pkgtypes = set([pkginfo.GetDefaultFile()])
            if self._optiondict['IncludeSources']:
                pkgtypes.add('source')
            variants = [ (pt, ep) for pt in pkgtypes
                                        for ep in self._epochs ]

            for (ptype, epoch) in variants:
                installs = pkginfo.GetAny(ptype, [epoch])
                if not installs and hasDependencies: continue
                try:
                    flds = installs.split()
                    pkgref = flds[0]
                    pkgsize = int(flds[1])
                    pkghash = flds[2]
                    downloads.append((pkgref, pkgsize, pkghash))
                except:
                    self._statview('Cannot find package filename ' \
                                   'for {0} in variant \'{1}:{2}\'' \
                                    .format(pkg, ptype, epoch),
                                   BuildViewer.SEV_WARNING)

        return downloads


    def _buildSetupFiles(self, packages):
        """Create top-level configuration files in local mirror"""

        (header, pkgdict) = self._masterList.GetHeaderAndPackages()
        hashfiles = []

        archdir = self._getArchDir(create=True)
        exeURL = self.setup_exe_url

        # Cygwin installer requires fixed filenames for package lists:
        inibase, inibz2 = 'setup.ini', 'setup.bz2'

        (exebase, exepure) = self._urlbasename(exeURL)

        # Split package list into normal + specials:
        spkgs = [pkg for pkg in packages if pkg.startswith('_')]
        packages = [pkg for pkg in packages if not pkg.startswith('_')]
        packages.sort()
        spkgs.sort()
        packages.extend(spkgs)

        # Reconstruct setup.ini file:
        spath = os.path.join(archdir, inibase)
        hashfiles.append(inibase)
        with codecs.open(spath, 'w', SI_TEXT_ENCODING) as fp:
            now = time.localtime()
            msgs = [
                    '# This file was automatically generated by' \
                        ' "pmcyg" (version {0}),'.format(PMCYG_VERSION),
                    '# {0},'.format(time.asctime(now)),
                    '# based on {0}'.format(self.setup_ini_url),
                    '# Manual edits may be overwritten',
                    'release: {0}'.format(header['release']),
                    'arch: {0}'.format(header['arch']),
                    'setup-timestamp: {0:d}'.format(int(time.time())),
                    'setup-version: {0}'.format(header['setup-version']),
                    ''
            ]
            fp.write('\n'.join(msgs))
            for pkg in packages:
                fp.write('\n')
                fp.write(pkgdict[pkg].GetAny('TEXT'))
        with open(spath, 'rb') as fp:
            hashfiles.append(inibz2)
            cpsr = bz2.BZ2File(os.path.join(archdir, inibz2), mode='w')
            cpsr.write(fp.read())
            cpsr.close()

        # Create copy of Cygwin installer program:
        tgtpath = os.path.join(self._tgtdir, exebase)
        try:
            self._statview.startOperation('Retrieving {0} to {1}' \
                                                .format(exeURL, tgtpath))
            urllib.request.urlretrieve(exeURL, tgtpath)
            self._statview.endOperation('done')
        except Exception as ex:
            self._statview.flushOperation()
            raise PMCygException("Failed to retrieve {0}\n - {1}" \
                                    .format(exeURL, str(ex)))

        # (Optionally) create auto-runner batch file:
        if self._optiondict['MakeAutorun']:
            apath = os.path.join(self._tgtdir, 'autorun.inf')
            with open(apath, 'w+b') as fp:
                fp.write(bytes('[autorun]\r\nopen=' + exebase
                                +' --local-install\r\n', 'ascii'))

        # Generate message-digest of top-level files:
        for algo in ["md5", "sha256", "sha512"]:
            sumfile = os.path.join(archdir, '{0}.sum'.format(algo))
            with open(sumfile, 'wt') as hp:
                for fl in hashfiles:
                    hshr = hashlib.new(algo)
                    with open(os.path.join(archdir, fl), 'rb') as fp:
                        hshr.update(fp.read())
                    hp.write('{0}  {1}\n'.format(hshr.hexdigest(), fl))

    def _doDummyDownloading(self, downloads):
        """Rehearse downloading of files from Cygwin mirror"""

        for (pkgfile, pkgsize, pkghash) in downloads:
            basefile = os.path.basename(pkgfile)
            fsize = self._prettyfsize(pkgsize)
            self._statview('  {0} ({1})'.format(basefile, fsize))

    def _doDownloading(self, packages, downloads):
        """Download files from Cygwin mirror to create local partial copy"""

        archdir = self._getArchDir(create=True)

        self._buildSetupFiles(packages)

        augdownloads = self._preparePaths(downloads)

        retries = 3     # FIXME make this tunable
        while augdownloads and retries > 0:
            retrydownloads = []
            retries -= 1

            for DLsummary in augdownloads:
                (pkgfile, pkgsize, pkghash, tgtpath) = DLsummary
                if self._cancelling:
                    self._statview('** Downloading cancelled **')
                    break

                mirpath = urllib.parse.urljoin(self._mirror, pkgfile)

                self._statview.startOperation('  {0} ({1})'.format(
                                                os.path.basename(pkgfile),
                                                self._prettyfsize(pkgsize)))

                (outcome, errmsg) = self._downloadSingle(mirpath, pkgsize,
                                                        pkghash, tgtpath)

                if outcome == self.DL_Success:
                    self._statview.endOperation('done')
                    self._fetchStats.AddNew(pkgfile, pkgsize)
                elif outcome == self.DL_AlreadyPresent:
                    self._statview.endOperation('already present')
                    self._fetchStats.AddAlready(pkgfile, pkgsize)
                else:
                    self._statview.endOperation(' FAILED ({0})'.format(errmsg),
                                                BuildViewer.SEV_WARNING)
                    if os.path.isfile(tgtpath):
                        os.remove(tgtpath)
                    if retries > 0:
                        retrydownloads.append(DLsummary)
                    else:
                        self._fetchStats.AddFail(pkgfile, pkgsize)

            if retries > 0 and retrydownloads:
                self._statview('\n** Retrying {0:d} download(s) **' \
                                .format(len(retrydownloads)))
                time.sleep(10)
            augdownloads = retrydownloads

        counts = self._fetchStats.Counts()
        if not counts['Fail']:
            self._statview('{0:d} package(s) mirrored, {1:d} new' \
                            .format(counts['Total'], counts['New']))
        else:
            self._statview('{0:d}/{1:d} package(s) failed to download' \
                            .format(counts['Fail'], counts['Total']),
                           BuildViewer.SEV_WARNING)

    def _downloadSingle(self, mirpath, pkgsize, pkghash, tgtpath):
        """Attempt to download and validate a single package from the mirror"""
        outcome = self.DL_Failure
        errmsg = None

        if os.path.isfile(tgtpath) and os.path.getsize(tgtpath) == pkgsize:
            outcome = self.DL_AlreadyPresent
        else:
            try:
                dlsize = 0
                urllib.request.urlretrieve(mirpath, tgtpath)
                dlsize = os.path.getsize(tgtpath)
                if dlsize == pkgsize:
                    outcome = self.DL_Success
                else:
                    outcome = self.DL_SizeError
                    errmsg = 'mismatched size: {0} vs {1}' \
                                .format(self._prettyfsize(dlsize),
                                        self._prettyfsize(pkgsize))
            except Exception as ex:
                errmsg = str(ex)

        if outcome == self.DL_AlreadyPresent or outcome == self.DL_Success:
            if not self._hashCheck(tgtpath, pkghash):
                outcome = self.DL_HashError
                errmsg = 'mismatched checksum'

        return (outcome, errmsg)

    def _preparePaths(self, downloads):
        """Setup directories for packages due to be downloaded"""
        augdownloads = []

        for (pkgfile, pkgsize, pkghash) in downloads:
            if os.path.isabs(pkgfile):
                raise SyntaxError('{0} is an absolute path'.format(pkgfile))

            tgtpath = os.path.join(self._tgtdir, pkgfile)
            tgtdir = os.path.dirname(tgtpath)
            if not os.path.isdir(tgtdir):
                os.makedirs(tgtdir)

            self._garbage.RescueFile(tgtpath)
            augdownloads.append((pkgfile, pkgsize, pkghash, tgtpath))

        return augdownloads

    def _urlbasename(self, url):
        """Split URL into base filename, and suffix-free filename"""
        (scm, loc, basename, query, frag) = urllib.parse.urlsplit(url)
        pos = basename.rfind('/')
        if pos >= 0:
            basename = basename[(pos+1):]
        pos = basename.rfind('.')
        if pos >= 0:
            pure = basename[0:pos]
        else:
            pure = basename
        return (basename, pure)

    def _getArchDir(self, create=False):
        """Get the local directory in which architecture-dependent
        Cygwin packages will be assembled"""
        archdir = os.path.join(self._tgtdir, self._cygarch)
        if create and not os.path.isdir(archdir):
            os.makedirs(archdir)
        return archdir

    def _prettyfsize(self, size):
        """Pretty-print file size, autoscaling units"""
        divisors = [ ( 1<<30, 'GB' ), ( 1<<20, 'MB' ), ( 1<<10, 'kB' ), ( 1, 'B' ) ]

        for div, unit in divisors:
            qsize = float(size) / div
            if qsize > 0.8:
                return '{0:.3g}{1}'.format(qsize, unit)

        return '{0:d}B'.format(size)



class PackageSet:
    """Collection of Cygwin package names, with optional
    architectural constraints, typically associated with
    a manual selection of packages of interest."""

    WILDCARD = '*'
    re_pkg = re.compile(r'''
          ((?P<pkgname>^[A-Za-z0-9]\S*)
                \s* (?P<constraints>\[[^\#]*\])?
                \s* (?P<annot>\# .* $)?)
        | (^\# (?P<deselected>[A-Za-z0-9]\S*)
                (?P<misc>\[[^\#]*\])?
                \s* (?P<desannot>\# .* $))
        | (?P<comment>^\s* (\#.*)? $)
        ''', re.VERBOSE)
    re_constr = re.compile(r'''
            \s* \[ (?P<key>\S+?) = (?P<value>\S*?) \]
        ''', re.VERBOSE)

    def __init__(self, files=[]):
        self._pkgs = {}
        if files:
            for fname in files:
                with codecs.open(fname, 'r', SI_TEXT_ENCODING) as fp:
                    self._ingestStream(fp, fname)

    def __len__(self):
        return len(self._pkgs)

    def __contains__(self, pkg):
        try:
            meta = self._pkgs[pkg]
            return True
        except KeyError:
            return False

    def extend(self, pkgs):
        if isinstance(pkgs, PackageSet):
            for (p, cnstr) in pkgs._pkgs.items():
                self._mergeEntry(p, cnstr)
        else:
            for p in pkgs:
                self._mergeEntry(p)

    def extract(self, **kwargs):
        """Generate a sorted list of names of all user-selected packages
        which the supplied architectural constraints."""
        extr = []
        for (pkg, cnstr) in self._pkgs.items():
            isAllowed = True
            for (key, possible) in cnstr.items():
                if self.WILDCARD in possible:
                    continue
                actual = kwargs.get(key)
                if not actual:
                    continue
                if not actual in possible:
                    isAllowed = False
                    break
            if isAllowed:
                extr.append(pkg)
        extr.sort()
        return extr

    def _ingestStream(self, fp, fname='<stream>'):
        """Parse a text stream containing a list of Cygwin package names,
        one per line."""

        lineno = 0
        for line in fp:
            lineno += 1
            matches = self.re_pkg.match(line)
            if not matches:
                raise SyntaxError('Package-list parse failure at {0:s}:{1:d}' \
                                    .format(fname, lineno))

            if matches.group('pkgname'):
                pkgname = matches.group('pkgname')
                cnstr = self._parseConstraints(matches.group('constraints'))
                self._mergeEntry(pkgname, cnstr)
            elif matches.group('comment'):
                continue

    def _parseConstraints(self, expr):
        """Parse package constraints of the form [arch=x86]"""
        cnstr = {}
        if expr:
            for m in self.re_constr.finditer(expr):
                cnstr[m.group('key')] = set(m.group('value').split(','))
        return cnstr

    def _mergeEntry(self, pkg, cnstr={}):
        """Merge architectural constraints for a single package name"""
        if not pkg in self._pkgs:
            self._pkgs[pkg] = cnstr
        else:
            pkgcnstr = self._pkgs[pkg]
            newkeys = set(cnstr.keys())
            oldkeys = set(pkgcnstr.keys())

            for key in (newkeys & oldkeys):
                pkgcnstr[key].update(cnstr[key])

            for key in (oldkeys - newkeys):
                pkgcnstr[key] = set([self.WILDCARD])



class PkgSetProcessor(BuildReporter):
    """Utilities for computing package dependencies,
    given user-supplied selections of Cygwin package names,
    using a parsed setup.ini supplied via a MasterPackageList"""

    def __init__(self, masterList):
        BuildReporter.__init__(self, Peer=masterList)
        self._masterList = masterList

    def ExpandDependencies(self, selected, epochs=['curr']):
        """Expand list of packages to include all their dependencies"""
        pkgdict = self._masterList.GetPackageDict()

        additions = set(selected)
        packages = set()
        badpkgnames = []
        badrequires = set()

        while additions:
            pkg = additions.pop()
            packages.add(pkg)

            pkginfo = pkgdict.get(pkg, None)
            if not pkginfo:
                badpkgnames.append(pkg)
                continue

            # Find dependencies of current package & add to stack:
            for epoch in epochs:
                try:
                    reqlist = pkginfo.GetDependencies([epoch])
                    for r in reqlist:
                        if not pkgdict.get(r):
                            badrequires.add((pkg, r))
                            continue
                        if not r in packages:
                            additions.add(r)
                except:
                    if not pkginfo.HasFileContent():
                        self._statview('Cannot find epoch \'{0}\' for {1}' \
                                        .format(epoch, pkg),
                                       BuildViewer.SEV_WARNING)

        if badpkgnames:
            badpkgnames.sort()
            self._statview("The following package names"
                           " were not recognized:\n\t{0}"
                            .format('\n\t'.join(badpkgnames)),
                            BuildViewer.SEV_ERROR)
            raise PMCygException("Invalid package names"
                                 " in ExpandDependencies()")
        if badrequires:
            links = [ '{0}->{1}'.format(pkg, dep)
                        for (pkg, dep) in badrequires ]
            self._statview("Master package list contains spurious"
                           " dependencies: {0}".format(', '.join(links)),
                           BuildViewer.SEV_WARNING)

        packages = list(packages)
        packages.sort()

        return packages

    def ContractDependencies(self, pkglist, minvotes=6):
        """Remove (most) automatically installed packages from list,
        such that an initial selection of packages can be reduced to
        a minimal subset that has the same effect after dependency expansion."""
        dependencies = self._buildDependencies()
        votes = dict([(p, 0) for p in pkglist])

        # Find number of times each package is cited as a dependency:
        for pkg in pkglist:
            reqs = dependencies.get(pkg, [])
            for req in reqs:
                votes[req] = votes.get(req, 0) + 1

        # Finding zero-vote packages would be sufficient if the graph of
        # dependencies did not contain loops (e.g. gcc-mingw-g++ <-> gcc-g++).
        # We add packages with many votes because they are probably worth
        # listing explicitly, even if they would be installed as dependencies
        # of zero-vote packages.
        primaries = [pkg for pkg, n in votes.items()
                            if n == 0 or n >= minvotes]

        # Preserve any packages not covered by the tree grown from
        # the zero-vote packages, to handle segments of the dependency graph
        # containing loops:
        coverage = self.ExpandDependencies(primaries)
        contracted = set(pkglist).difference(coverage)

        packages = list(contracted.union(primaries))
        packages.sort()

        return packages

    def MakeTemplate(self, stream, pkgset=None, terse=False):
        """Generate template package-listing file,
        emitting this via the supplied output stream.
        Note that this stream may need to be able to support
        UTF-8 multi-byte characters."""

        pkgdict = self._masterList.GetPackageDict()
        catgroups = self._masterList.GetCategories()
        catlist = [ c for c in catgroups.keys() if c != 'All' ]
        catlist.sort()

        if pkgset:
            userpkgs = set(pkgset.extract())
        else:
            userpkgs = None

        lines = [ \
            '# Package listing for pmcyg (Cygwin(TM) Partial Mirror)',
            '# Autogenerated on ' + time.asctime(),
            '# from: ' + self._masterList.GetSourceURL(),
            '',
            '# This file contains listings of cygwin package names,' \
                ' one per line.',
            '# Lines starting with \'#\' denote comments,' \
                ' with blank lines being ignored.',
            '# The dependencies of any package listed here should be' \
                ' automatically',
            '# included in the mirror by pmcyg.'
        ]
        print('\n'.join(lines), file=stream)

        for cat in catlist:
            if terse and not set(catgroups[cat]).intersection(userpkgs):
                continue

            print('\n\n##\n## {0:s}\n##'.format(cat), file=stream)

            for pkg in catgroups[cat]:
                desc = ConcatShortDescription(pkgdict[pkg].GetAny('sdesc'))
                if pkgset and pkg in pkgset:
                    prefix = ('', ' ')
                else:
                    if terse: continue
                    prefix = ('#', '')
                stream.write('{0:s}{1:<28s}   {2:s}# {3:s}\n' \
                                .format(prefix[0], pkg, prefix[1], desc))

    def UpdatePackageLists(self, filenames, bckp=".orig"):
        """Rewrite a set of package lists, updating package-descriptions.
        The layout of the supplied files is assumed to be the same
        as that generated by MakeTemplate()."""

        pkgdict = self._masterList.GetPackageDict()

        for fn in filenames:
            newfn = fn + ".new"

            with codecs.open(fn, 'r', SI_TEXT_ENCODING) as fin, \
                    codecs.open(newfn, 'w', SI_TEXT_ENCODING) as fout:
                for line in fin:
                    line = line.rstrip()
                    matches = PackageSet.re_pkg.match(line)
                    if not matches:
                        continue

                    (pkgname, cutpos) = (None, -1)
                    pkgdesc = None
                    for key, annot in [ ('pkgname', 'annot'),
                                        ('deselected', 'desannot') ]:
                        pkgname = matches.group(key)
                        cutpos = matches.start(annot)
                        if pkgname:
                            try:
                                pkgdesc = pkgdict[pkgname].GetAny('sdesc')
                            except:
                                pass
                            break
                    if pkgdesc and cutpos > 0:
                        line = '{0:s}# {1:s}' \
                                    .format(line[0:cutpos],
                                            ConcatShortDescription(pkgdesc))
                    print(line, file=fout)

            if bckp:
                oldfn = fn + bckp
                if os.path.exists(oldfn):
                    os.remove(oldfn)
                os.rename(fn, oldfn)
            else:
                os.remove(fn)
            os.rename(newfn, fn)


    def _buildDependencies(self, epoch='curr'):
        """Build lookup table of dependencies of each available package"""
        pkgdict = self._masterList.GetPackageDict()
        dependencies = {}
        for pkg, pkginfo in pkgdict.items():
            try:
                dependencies[pkg] = pkginfo.GetDependencies([epoch])
            except:
                pass
        return dependencies



class MasterPackageList(BuildReporter):
    """Database of available Cygwin packages built from 'setup.ini' file"""

    RE_DBline = re.compile(r'''
          ((?P<relinfo>^(release|arch|setup-\S+)) :
                                \s+ (?P<relParam>\S+) $)
        | (?P<comment>\# .* $)
        | (?P<package>^@ \s+ (?P<pkgName>\S+) $)
        | (?P<epoch>^\[ (?P<epochName>[a-z]+) \] $)
        | ((?P<field>^[a-zA-Z][-a-zA-Z0-9]+) : \s+ (?P<fieldVal>.*) $)
        | (?P<blank>^\s* $)
        ''', re.VERBOSE)

    def __init__(self, iniURL=None, Viewer=None):
        BuildReporter.__init__(self, Viewer)

        self._pkgLock = threading.Lock()
        self._iniURL = None
        self.ClearCache()
        self.SetSourceURL(iniURL)

    def ClearCache(self):
        try:
            self._pkgLock.acquire()
            self._ini_header = None
            self._ini_packages = None
        finally:
            self._pkgLock.release()

    def GetSourceURL(self):
        return self._iniURL

    def SetSourceURL(self, iniURL=None, reload=False):
        if reload or iniURL != self._iniURL:
            self.ClearCache()
        self._iniURL = iniURL

    def GetHeaderInfo(self):
        self._ingest()
        return self._ini_header

    def GetPackageDict(self):
        self._ingest()
        return self._ini_packages

    def GetHeaderAndPackages(self):
        self._ingest()
        return (self._ini_header, self._ini_packages)

    def HasCachedData(self):
        return (self._ini_header and self._ini_packages)

    def GetCategories(self):
        """Construct lists of packages grouped into categories"""

        pkgdict = self.GetPackageDict()
        allpkgs = []
        catlists = {}

        for pkg, pkginfo in pkgdict.items():
            allpkgs.append(pkg)

            cats = pkginfo.GetAny('category').split()
            for ctg in cats:
                catlists.setdefault(ctg, []).append(pkg)

        catlists['All'] = allpkgs
        for cats in catlists.values():
            cats.sort()

        return catlists

    def _ingest(self):
        try:
            self._pkgLock.acquire()
            if self._ini_header and self._ini_packages:
                return
            self._statview.startOperation('Scanning mirror index at {0:s}' \
                                            .format(self._iniURL))
            self._parseSource()
            self._statview.endOperation('done')
        finally:
            self._statview.flushOperation()
            self._pkgLock.release()

    def _parseSource(self):
        """Acquire setup.ini file from supplied URL and parse package info"""
        self._ini_header = {}
        self._ini_packages = {}

        try:
            fp = SetupIniFetcher(self._iniURL)
        except Exception as ex:
            raise PMCygException("Failed to open {0:s} - {1:s}" \
                                    .format(self._iniURL, str(ex)))

        lineno = 0
        self._pkgname = None
        self._pkgtxt = []
        self._pkgdict = PackageSummary()
        self._epoch = None
        self._fieldname = None
        self._fieldlines = None
        self._inquote = False

        for line in fp:
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
            self._pkgdict.Set(self._fieldname,
                                '\n'.join(self._fieldlines), self._epoch)
            self._fieldname = None
            self._inquote = False
        else:
            self._fieldlines.append(trimmed)

    def _ingestOrdinaryLine(self, line, lineno=None):
        """Classify current line as package definition/field etc"""
        matches = self.RE_DBline.match(line)
        if not matches:
            raise SyntaxError("Unrecognized content on line {0:d}" \
                                .format(lineno))

        if matches.group('relinfo'):
            self._ini_header[matches.group('relinfo')] = matches.group('relParam')
        elif matches.group('comment'):
            pass
        elif matches.group('package'):
            self._finalizePackage()

            self._pkgname = matches.group('pkgName')
            self._epoch = 'curr'
            self._fieldname = None
        elif matches.group('epoch'):
            self._epoch = matches.group('epochName')
        elif matches.group('field'):
            self._fieldname = matches.group('field')
            self._fieldtext = matches.group('fieldVal')
            quotepos = self._fieldtext.find('"')
            if quotepos < 0:
                # Field value appears without quotation marks on single line:
                self._pkgdict.Set(self._fieldname,
                                    self._fieldtext, self._epoch)
            if quotepos >= 0:
                if quotepos > 0:
                    # Field value contains additional metadata prefix:
                    prefix = self._fieldtext[0:quotepos].strip()
                    self._fieldname += '_' + prefix
                    self._fieldtext = self._fieldtext[(quotepos+1):]
                if self._fieldtext[1:].endswith('"'):
                    # Quoted string starts and ends on current line:
                    self._pkgdict.Set(self._fieldname,
                                        self._fieldtext[1:-1], self._epoch)
                else:
                    # Quoted string starts on current line, presumably ending later:
                    self._fieldlines = [ self._fieldtext[1:] ]
                    self._inquote = True

            if self._fieldtext.startswith('"'):
                if self._fieldtext[1:].endswith('"'):
                    self._pkgdict.Set(self._fieldname,
                                        self._fieldtext[1:-1], self._epoch)
                else:
                    self._fieldlines = [ self._fieldtext[1:] ]
                    self._inquote = True
            else:
                self._pkgdict.Set(self._fieldname,
                                    self._fieldtext, self._epoch)

    def _finalizePackage(self):
        """Final assembly of text & field records describing single package"""

        if not self._pkgname:
            return

        pkgtxt = self._pkgtxt
        while pkgtxt and pkgtxt[-1].isspace():
            pkgtxt.pop()
        self._pkgdict.Set('TEXT', "".join(pkgtxt))
        self._ini_packages[self._pkgname] = self._pkgdict

        self._pkgname = None
        self._pkgtxt = []
        self._pkgdict = PackageSummary()



class PackageSummary:
    """Dictionary-like container of package information,
    specialized to cope with multiple epochs"""

    def __init__(self):
        self._pkginfo = {}
        self._epochs = set()

    def GetAny(self, field, epochset=[]):
        """Lookup the value of a particular field for a set of possible epochs.

        An empty set of allowed epochs matches current or default epoch
        """

        value = None
        if not epochset:
            epochset = ( None, 'curr' )
        if not None in epochset:
            epochset = list(epochset)
            epochset.append(None)
        for epoch in epochset:
            value = self._pkginfo.get((field, epoch), None)
            if value: break
        return value

    def GetAll(self, field, epochset=[]):
        """Lookup the values of a particular field,
        across all possible epochs in the supplied list."""
        values = []
        if not epochset:
            epochset = self._epochs
        for epoch in epochset:
            val = self._pkginfo.get((field, epoch), None)
            if val: values.append(val)
        return values

    def HasFileContent(self):
        """Determine whether package has non-empty binary or source file"""
        for variant in ('install', 'source'):
            if self.GetAny(variant, self._epochs):
                return True
        return False

    def GetDefaultFile(self):
        """Find the default binary or source file that should
        be installed when this package is selected."""
        for variant in ('install', 'source'):
            if self.GetAny(variant):
                return variant
        return None

    def HasDependencies(self):
        """Determine whether the package depends on any other packages."""
        if self.GetAny('depends2') or self.GetAny('requires'):
            return True
        return False

    def GetDependencies(self, epochset=[]):
        """Return a list of other packages on which this package depends."""
        return sorted(
            { x.strip() for x in self.GetAny('depends2', epochset).split(',') }
            | set(self.GetAny('requires', epochset).split()) )

    def Set(self, field, value, epoch=None):
        """Record field=value for a particular epoch (e.g. curr/prev/None)"""
        self._pkginfo[(field, epoch)] = value
        self._epochs.add(epoch)


##
## Download statistics
##

class FetchStats:
    """Mechanism for accumulating statistics of the progress
    of package downloads."""

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
        """Find the total number of bytes downloaded"""
        return self._totalSize

    def Counts(self):
        """Find the number of packages downloaded,
        as a tuple of total/new/pre-existing/failed."""
        return { 'Total': self._totalCount,
                'New': self._newCount,
                'Already': self._alreadyCount,
                'Fail': self._failCount }

    def Failures(self):
        return self._failCount

    def AddNew(self, pkg, size):
        """Mark the named package as being newly downloaded"""
        self._newSize += size
        self._newCount += 1

    def AddAlready(self, pkg, size):
        """Mark the named package as having previously been
        successfully downloaded."""
        self._alreadySize += size
        self._alreadyCount += 1

    def AddFail(self, pkg, size):
        """Mark the named package as having failed
        to download successfully"""
        self._failSize += size
        self._failCount += 1



##
## Garbage-collection mechanisms
##

class GarbageCollector(BuildReporter):
    """Mechanism for pruning previous versions of packages
    during an incremental mirror."""

    def __init__(self, topdirs=list(), Viewer=None):
        BuildReporter.__init__(self, Viewer)

        self._topdirs = None
        self._topdepth = {}
        self._suspicious = True

        # Lists of file and directory names that indicate that the user's
        # top-level download directory contains important files
        # unconnected with Cygwin or pmcyg.
        self._susDirnames = [ 'bin', 'etc', 'sbin', 'home',
                            'My Documents', 'WINNT', 'system32' ]
        self._susFilenames = [ 'initrd.img', 'vmlinuz',
                                '.bashrc', '.bash_profile',
                                '.login', '.tcshrc']

        if topdirs:
            self.IndexCurrentFiles(topdirs)

    def IndexCurrentFiles(self, topdirs, mindepth=0):
        """Build list of files and directories likely to be deleted"""
        if isinstance(topdirs, str):
            self._topdirs = [ topdirs ]
        else:
            self._topdirs = list(topdirs)
        self._directories = []
        self._files = []

        self._suspicious = False
        for topdir in self._topdirs:
            topdir = os.path.normpath(topdir)

            if os.path.isdir(topdir):
                self._suspicious |= self._checkTopSuspiciousness(topdir)

            topdepth = self._calcDepth(topdir)
            self._topdepth[topdir] = topdepth

            for dirpath, dirnames, filenames in os.walk(topdir, topdown=False):
                self._suspicious |= self._checkNodeSuspiciousness(dirnames,
                                                                  filenames)

                dirdepth = self._calcDepth(dirpath)
                if (dirdepth - topdepth) < mindepth:
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
        for depth in range(maxdepth, 0, -1):
            pardir = self._canonPath(os.sep.join(dirsegs[0:depth]))
            if pardir in self._directories:
                self._directories.remove(pardir)

    def GetNfiles(self):
        return len(self._files)

    def GetFileList(self):
        return self._files

    def GetDirectoryList(self):
        return self._directories

    def GetNeatList(self):
        """Return a human-readable list of files that are considered
        good candidates for deletion, with each entry being
        abbreviated based on the common root directory."""
        if not self._topdirs: return []

        dirprefix = os.path.commonpath(self._topdirs)
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
        """Delect all files and directories that have not been marked
        as wanted by calling RescueFile()."""
        try:
            for fl in self._files:
                os.remove(fl)
            rdirs = self._directories

            # Use reverse-alphabetic sort to approximate depth-first dirsearch:
            rdirs.sort()
            rdirs.reverse()
            for dr in rdirs:
                os.rmdir(dr)
        except Exception as ex:
            self._statview('Failed to remove outdated files - ' + str(ex),
                           BuildViewer.SEV_WARNING)

    def _checkTopSuspiciousness(self, topdir):
        """Try to protect user from accidentally deleting
        anything other than an old Cygwin repository"""
        toplist = os.listdir(topdir)
        releasedirs = 0
        subdirs = 0
        topfiles = 0
        for entry in toplist:
            fullname = os.path.join(topdir, entry)
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



class GarbageConfirmer(BuildReporter):
    """Mechanism for inviting user to confirm disposal of outdated files"""

    def __init__(self, garbage, default='no'):
        BuildReporter.__init__(self, Peer=garbage)
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
        """Proceed to act on the user's decision about whether
        to delete or preserve outdated packages."""
        if not self.HasResponded():
            self._awaitResponse()
        if self._userresponse == 'yes':
            self._statview('Deleting {0:d} files' \
                            .format(self._garbage.GetNfiles()))
            self._garbage.PurgeFiles()

    def _askUser(self, allfiles):
        print('\nThe following files are outdated:')
        for fl in allfiles:
            print('  {0:s}'.format(fl))

        try:
            response = input('Delete outdated files [yes/NO]: ').lower()
            if response == 'yes':
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
        self.status_txt.grid(row=row, column=0, sticky=Tk.N+Tk.E+Tk.S+Tk.W, padx=4, pady=(6,2))
        rootwin.grid_rowconfigure(row, weight=1)
        self.message_queue = queue.Queue()
        row += 1

        self.progress_bar = GUIprogressBar(rootwin)
        self.progress_bar.grid(row=row, column=0, sticky=Tk.E+Tk.W+Tk.S, padx=4, pady=2)
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
            if self._renewMirrorMenu and not self.mirrorthread.isAlive():
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
        combo = Tk.OptionMenu(parampanel, self.arch_var, 'x86', 'x86_64')
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

\N{COPYRIGHT SIGN}Copyright 2009-2020 RW Penney

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



class GUIimagery:
    """Generator of Tkinter PhotoImage objects for embedded icon imagery"""

    @classmethod
    def GetImage(cls, ident):
        base64data = cls.__getattribute__(cls, ident)
        photo = Tk.PhotoImage(data=base64data)
        return photo

    download = """
R0lGODlhIAAgAPUAACDAICHAISLAIiPAIyXAJSrAKizALC3ALTPAMzTANDvAO0fAR0/AT1XAVV/A
X2DAYGbAZm3AbW7AbnnAeXrAev/gAIHAgYLAgoTAhInAiYrAipbAlqLAoqbApqzArLPAs7XAtbbA
trrAur7AvsDAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAACQALAAAAAAgACAAAAaoQJJw
SBQCjshjcclcJpPNKPOJlFqHVOXVmgVsudmvtCuOksskTGO97rLXmKuH0O0SPNtIPRv5ihB7SQki
YhmBSBpoC4cLaCQchxyOJA97D5MkHwddBR+YJBRdFJ8kIwpUCiOkJBtUG6tCDEkMsEIdSAQdtUIQ
RxC7QiEFB4RiFccVURcXUcjJQ85RI6pN0dDImNZC2mjczt/g4eBE4uXmz9vn6t7r7UJBADs=
"""

    cancel = """
R0lGODlhIAAgAPZMAP8AAP8BAf4CAv8CAv4DA/0FBf4EBP4FBf8sLP8vL+FdXf9TU/9bW/9cXN9h
Yd9jY95kZN5lZd1mZt1padtsbNtubtpvb9tvb9xsbNpxcdlzc9pycth1ddh3d9d5edd7e9Z8fNZ9
fdV/f9Z+fuBgYP9paf9xcf9ycv9zc9WCgtSDg9OHh9SEhP+MjP+Njf+Ojsimpsinp8epqcerq8as
rMatrcWvr8aursavr8ipqcWwsMWxscWyssSzs8O1tcO2tsS0tMK4uMO4uMK6usK7u8G8vMG9vcC+
vsC/v//6+v/8/P/+/v///8DAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5
BAEAAE0ALAAAAAAgACAAAAf+gE2Cg4SFhoeIhjQwjDQ9QEBHiZODIQGXmJmXE5SGFZqgmA+dg5+h
pxCkpqenF5QQmAmssZgaiQ+YLUwlsyVMLbWHuJe6TLunvsbAlx+FCpgIScZMSQygDNLGSQiYIYNH
mgvZxryYydoLmQc0gkWg4tPHAefU6Zo57aHw0yX0SfaaZgj6cWpfPHSn2DUhWHDctH+sFPaYZbDe
LCCCJrKiR25WD0E0Nh7kx+oHSGTxkjgsB6qIoBmh/C2oyDKTyyYwQMm8ZDBJzUuSmtA4kGknJpqa
gjZJAS2lNU0MUsq6pKAQC0wmEOrLZgITJ0NML5mAyEpc10u2EH2gNSvA1AAnaRN1aBuKgyq6mbyR
anIBb4AUewcNY3VgRWBCPRIrZsRY4eHHhwIBADs=
"""

    folder = """
R0lGODlhGAAXAPUAAAAAAAYGAQkJAgoKAgsLAgsLAwwMAw8PBBMTBBUVBR8fByMjCDExCzMzDDQ0
DTc3DTw8Dj8/DkFBD0JCD0ZGEFBQEllZFVpaFWFhFmhoGG9vGoKCHoeHH5KSIpOTIqurKK6uKMHB
LcTELcXFLcbGLs/PMNDQMMDAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAACcALAAAAAAYABcAAAaewJNw
SCwaj8hkEsAEKJODi0ZzGTyPC5PWtLgWB55tyWP1MhWlrVbRbDuJgIfmo9Z+pvjp4y0EZLQgGIKD
hIMNbSd+WhAVeY6PGgmJfyQGJHWYaiQBkyYbE5mhngadEByidSUlD30ZIQOXqGIhnJOfsmKeCK2m
uFqqrH0YsL5atEMAE6DFngfIC6fMDXDExcfICIXahRRlyG7g4F7jJ0EAOw==
"""

    allpkgs = """
R0lGODlhIAAgAPcAAACAgAGAgAKAgAOAgAKBgQOBgQSBgQWBgQaBgQWCggaCggeCggiCggiDgwmD
gwqDgwuDgwqEhAuEhAyEhA2EhA6EhA6FhQ+FhRCFhRGFhRCGhhGGhhKGhhOGhhKHhxOHhxSGhhSH
hxWHhxeHhxaIiBeIiBiIiBmIiBqIiBqJiRuJiRyJiR2JiR6Kih+KiiCKiiCLiyKLiyOLiyGMjCSM
jCWMjCWNjSaMjCaNjSeNjSiNjSmOjiyOjiyPjy2Pjy6Pjy+Pjy6QkC+QkDGQkDGRkTKQkDKRkTOR
kTOSkjWRkTSSkjaSkjeSkjeTkziSkjiTkzmTkzqTkz2UlD6UlD6VlT+VlUCVlUGWlkKWlkSWlkSX
l0WXl0aXl0WYmEaYmEeYmEiYmEmYmEuZmUyZmU2amk6bm1Cbm1Gbm1Kbm1CcnFGcnFadnVednVid
nVmdnVmenluenlyfn12fn16fn1+goGCgoGKhoWOhoWShoWWiomaiomeiomijo2mjo2ykpG+lpXCl
pXCmpnGmpnKmpnOmpnSmpnSnp3anp3WoqHaoqHeoqHioqHmoqHipqXmpqXqpqXupqX6qqn+qqn6r
q3+rq4Crq4Grq4OsrISsrIWsrIWtrYatrYetrYitrYiuromurouvr4yvr42vr4+wsJCwsJGwsJKx
sZOxsZSyspWyspezs5mzs5m0tJq0tJu0tJy0tJ21tZ61taC1taC2tqO2tqO3t6S3t6W3t6a3t6a4
uKe4uKi4uKu5uay5ua26uq66uq+6uq+7u7C7u7G7u7K7u7K8vLO8vLS8vLS9vbW9vbe9vbi9vbi+
vrm+vru+vrq/v7u/v7y/v76/v77AwL/AwMDAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAANUALAAAAAAgACAA
AAj+AKsJHEiwoMGDCA/SwrOkxYWHS/DQSkhRWiWHFzw0UVMC44UWlahRLEipgoEAAQxIcZTLgTNn
lUp80aED1UiBbgJI8STClzFHQQw4KOGgQgUAOZYEcDMyTgBH1eLEcYYHQ44TJ2LYEshmi5sLSxN6
MpBIoB0kGL7EqoZhVyAMlaqxsVPNWZCnB31dOCGQVo4AmQT6wiCwFYavuwRSA5vLoJgnYqp5qhCo
EgY8xi5FEWiMTYAxBMWcWFKQFoZAWxxVECVw15cLGE4gcSiGVInAArEEurB1IBs6uTBgWEuQGpI4
o2KJrIaqbbVpHnLFYSpQ2gVXuwyANhjDlcFAOqj+2ZFSzdWFgagMVFtCRwTU4i4NGt8iIjG1AKoE
JjLgqYW0WCeMIcxAg+UlRQDeCWTAe4EYEAQlAiXjBgZjkOIMKTwQ5MwoYhy2BR2cGRCIQHicEB+B
eORgwAkljDGGFCrmgEcw1ZgmTTV+xICHQIGo6MtByaDxhCGJUIKKMwUhkclgUoxYTSYoLKGDMQex
0QdFfmChQx9PeCJQLBcw4kYLCYb2HkKULEVNCxMpqEY1iVzAxo8DLeFlXl85IMwohA0kggiCsXEB
FpUMmEMrBQlDCRZyCtOCLUHkQJAjALAmkDCMLPGRA1K4KMYSJ1SwhCHJCBSDIQFYOpCJZSpmGh6W
gRgSiCdtEoSBA0gYZAtsgSznJ50HUdMHABX0VlAmIsjAgyc3CoQBsMVlwsOtdx5kRw49loDGks8S
tEsmaJyQgx0GoDGSHyL0QctZYImrA0ZI2EFLHwZ8cVM1hhiAAYTV8OCIK63QQiclGOB1bzXJKOVA
DjN8IYooYqpoQBSlHjyQM37wAFYAABhwAQ9+IGnxyCSXfFBAADs=
"""

    userpkgs = """
R0lGODlhIAAgAPcAAAMDAwMEBAsLCwkPDw0NDQ4ODg4PDw8PDw4QEA8QEAwTEw0TEw4TEw0VFQ8X
FwwZGQ8ZGQ8fHxAQEBERERETExISEhEUFBIUFBQUFBYWFhcXFxIbGxYfHxkZGRoaGhwcHB0dHR0e
Hh4fHwgtLQssLBQkJBcmJhcnJxMpKRQsLBQtLRopKQkzMws9PQk/PxsxMR83Nx49PSAgICMjIyUl
JSYmJicnJygoKCoqKisrKywsLCM3NyU0NCI/PzIyMjMzMzQ0NDU1NTY2Njg4ODw8PD09PT4+Pj8/
PwpHRxdCQgdSUhJbWyBBQSlHRyVKSiNNTSlLSypLSylMTCNRUSJSUiNSUiRSUipRUStUVCZZWSNc
XClYWChcXC5eXjJTUw1iYgtwcAh1dQN/fwV/fwd+fgZ/fwh4eAl5eQt7ewh+fjNlZTFnZzNmZjJn
ZzZlZTVmZjNtbTVvbzltbTlubipycitycixxcSp1dSN5eSd6ejFycjN3dzd1dTB5eTB+fjN+fjp6
ekBAQEFBQUJCQkNDQ0BFRUREREVFRUdHR0hISElJSUtLS0lMTExMTE1NTU5OTklQUFZWVldXV11d
XV9fX2BgYGNjY2ZmZmlpaWpqamtra2xsbG1tbXR0dHl5eXt7e3x8fH19fX5+fn9/fwCAgAGAgAKA
gAKBgQaAgAaBgQeBgQeCggiCgg6EhA6FhRKFhRKGhhKHhxSFhRWHhxaHhxeHhx+HhyOFhSCHhyKH
hyeGhieHhy2Dgy+FhSCJiSKIiCOJiSWIiCeIiCaKijGCgjaAgICAgIODg4iIiI+Pj5OTk5SUlJWV
lZaWlpeXl5iYmJqampycnJ2dnZ6enp+fn6CgoKOjo6Wlpaenp6ioqKmpqaqqqqysrK6urq+vr7Cw
sLGxsbOzs7S0tLW1tbe3t7i4uLm5ubu7u7y8vL29vb6+vsDAwAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAAOsALAAAAAAgACAA
AAj+ANcJHEiwoMGDCBMqXKgwXTNQmDaBapaOocJoggrQEHRjyZkvLApFs1jQ2yENm7wJnJSmVKlV
ZZAwUkkSmgZJ5AhaKuPS5aozKEYyjFYAFMFvoIKAEbOq50sSQhN602BUYDMfBTgy0eIiTFOXrFR8
U0jE0UBMEjpVnBSn1CxALniKKXVGUMJmBSRYOoeJxraBltq6/JWEaRkSBaAhPITJmyMJAv4KdBbE
iS6XYn6NUALJG6ZDB88VoHnDA41m5ASFuMFjBZVZumKc0CFwW4GKBZXdEOhNwjljGjQIOldpTiwv
JUoUg9Vg7LrTBj+BXgeKiEBlBQpUmgSHDgIEvVz+YjEmUNAng5gkCUy/vo0wKgACSPnVBo/LN5gE
SspfkP06/5i4Bx8AUeBS33387WcQKHZRZ906yAgggSfbfSIBAry4dAV56whSFUHN0MBbAedcgoAK
iBC31yAmRHDHLA/QNINiBaUjgWQ0SCCFMK9wEQIOOIRgyDjWDGGBiOtcIwFuBTFmzQ8eSCBMKWKI
gcsTP9C4jm0n+GANJoogRI0ABey1yQu/9ERHJQNdE0IfrtiBgADXJETEIgNt8gAfs5RChyXr8GVB
Hj2p8SBC3njwITVCSLDFDjgEcgAVtvTkhwfOJRSNBB+u8w0yQzRBzCxzuUSMBFFd5AFOOunRkxg7
s7TxQaoLkaOIBCkJVNxgfGywSE4kDRTNYzc0gQMPWcAggSK0BitQOs6MsolE0DDp7LXYZqvtttwS
FBAAOw==
"""

    replace_never = """
R0lGODlhIAAgAPUAACUAACgoP0QAAFBQf2BgYGZmZoAAAAD/AAH/AQL/AgT+BAX+BQf9Bwn8CQv8
Cw37DRH5ERD6EBb4Fhv2GyL0Ii3wLS7wLjLuMjPuM0HqQU3lTU3mTVjiWFriWmbdZmbeZmzbbG3b
bXrXenzWfJCQkJeXl4XUhYjSiInSiZPPk5TOlJ7LnqbIpqnHqbDFsLfDt7TEtLXEtb3Bvb7Bvr/A
v6Cg/8DAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAADYALAAAAAAgACAAAAb+QJtw
SCwaj0USYclsLknIqI0QGFiv2ABBiiQMauCweLDlGr3idI1s+7g/I9VLilaH2Ye8noFJdb92YGQy
eoV5HUd1gYMdjR0ZFIUiZ4CLZUUtF3kTMkWKdmxGLSsOeSYsLkOfaqFFKA0NeQ8NKKqVoJdFFoUW
RKtprUUsEHkQLL5VWMpaURoHDBpJTtMEUEgxEhIxZtxEISHd4TYznUUlBejp6uglnktT70xCBQAC
9vf4AAVEJFdrVv+s2CggwIDBgwgF7LMVSNDAgggjKvR1i9XDiBIXCvmV5iLGgxOJNHRI8CNIjVMq
AvNoMuRGlWNYfnSZcmQNmRhp2rA5AGciRooje5Y0aYAmxzsD6+Fbqo+iv6cCz62b2o6fvKvvxIUL
AgA7
"""

    replace_ask = """
R0lGODlhIAAgAPcAAAAAAAEBAQICAQUDAwYDAwUFBQcHBwwGBgsLCw4JCQ4KChELCxcKChMODhQP
DxkJCRsMDBUbAxYWFhkUFCoAACQLCyoICDQAADwAAD0AADwEBDAICDEJCTMICDQKCiAZGSMdHSYf
Hy8vLygoPzIyMjk5OUEBAUQAAEgBAUoAAFMBAV4AAGQAAG0AAHAAAHIAAHsAAHwAAH8AAEA6OkU/
P0xlAVl2AEJCQkhERFFRUVlXV11bW15bW1BQf2BgYGJiYmZmZmdnZ25tbW9vb3V1dYAAAGqKCG+T
ALztJ8D/AMD/AcD+AsD+BMD9B8D7C8D8CMD9CMD8CcD8CsD6EMD5E8D4FsD4F8D3GsD1HcD1H8D0
IMDyJ8DyKcDxKsDwLcDwL8DvMMDtNcDsOsDsO8DrPL3WccDqQcDmS8DnS8DmTMDlT8DkU8DfYsDd
ZsDeZsDbbcDbbsDWfoWFhYaGhoiIiI6OjpCQkJWVlZaWlpeXl5ubm6GhobCwsLGxsbKysrW1tbi4
uLm5ubu7u76+vr+/v8DUgsDTiMDSicDSi8DQjsDRjsDOlMDOlcDNmcDLncDLn8DQkcDKoMDKocDJ
pMDJpcDHq8DGrMDGrsDIqMDEs8DDt8DDuMDBvcDAv6Cg/8DAwAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAAJ8ALAAAAAAgACAA
AAj+AD8JHEiwoMGDBe34WMiw4UI7CCN+8jGih8WLGEf4kIjQRw9PIEOK7LGRo0GPIlN6IvkJEaWB
c0QYQHDDz8mPKkOypJLECppFJOb88ZOjxM2cOn1gSsKUKRdFAgEZOIp0pQ9JZng2TRLGUhAJVJGy
/NRpUZooTY0EABI259iBltI0ORKgRpm2Kt8SbBTBBtO7BFFW1UswABKmT14OFCy2pMEAmbAwBdNp
cUWMmDVKdNSEKaKBCh2KhngwgMA1TMeYXG36EyWmTSqvnn2FqSOCeYbkETTbIBimUAXuWcABgoEJ
OITkAdSbC9NFUSeoKFIEBgsUHiAM+IBDD8dNaJOsVBK4wwL18+dlsMAAYhBCOIjaMNUicFCCF+jR
yygi40Gdg2w08UVTcAhERwX5JVgECjQYtEZ4TG0hWxAaKJhfCw0Q1MlZW2FhyUA6nGChfgYwJ5Bc
W5GhCUE7mDAiegfYRJYkbWxhBVppFEQEBy9SJ0MA7hWkSSFjhFGQHg/0WMQKIfRG1gIv7JeelNRZ
IISTn5RAAQZcdunlBQ6Y2FseQZRp5pll5oHlmrMFBAA7
"""

    replace_kill = """
R0lGODlhIAAgAPcAAAUDAwYDAwwGBg4JCQ4KChELCxcKChMODhQPDxkJCRsMDBkUFCoAACQLCyoI
CDQAADwAAD0AADwEBDAICDEJCTMICDQKCiAZGSMdHSYfHygoP0EBAUQAAEgBAUoAAFMBAV4AAGQA
AG0AAHAAAHIAAHsAAHwAAH8AAEA6OkU/P0hERFlXV11bW15bW1BQf2BgYGZmZm5tbW9vb3V1dYAA
AP8AAP8CAv4DA/0FBf4EBP4FBf0HB/wICPwJCfsMDPsNDfoPD/cXF/kREfoQEPkSEvkTE/cZGfYa
GvcaGvUeHvMjI/MlJfMmJvAtLe8xMe01Ne40NOw7O+pBQehFRehHR+ZLS+ZMTOVPT+ZOTuRTU+NV
Vd5mZtxqatpxcdlyctl0dNl1ddh2dtV+foiIiI6OjpCQkJWVlZaWlpeXl5ubm6GhobCwsLi4uLm5
ubu7u76+vr+/v9WCgtOHh9GLi9GMjNGNjc+Tk82Xl86Wls2YmMycnMqhocqiosmlpcepqceqqser
q8Wvr8avr8WxscWyssSzs8O1tcO4uMG7u8K6usK7u8G8vMC+vsG+vsC/v6Cg/8DAwAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACH5BAEAAJAALAAAAAAgACAA
AAj+ACEJHEiwoMGDBcu8WMiw4cIyCCNCeqHBhcWLGDW8kIjwhYtHIEOKdLGRo0GPIlM+IgkJTBw9
hkxO/KgyJMseNXIqwQKmUESUNUGSLJSzaNEmXhCdpBmUpCAsUJDgMJoziJiCQJuWFNjoDhcoVKs0
Gpi1JsuDhbYIKYqFLFOzWw8imlK0jsCyKs9GbCQlZ5S7b/PGRbgnp5C7FTEq1mjSUM4eAhU6nAyR
Y52cSWRqhgS2hpbNJr0U7UMQjQw0bDYrhSRnao0sBNUUoKAAwAUVMVBHvDOlpeslqyGxWfCBBo0S
ITxYqH0bTUFESH50roEEEEEWDoxr124iBIQMYweGYqG6xPrANwNIbF9Pw0QCMgPtrGV7qOCYBuzZ
e0ghELpRJwfBIEF+64mAgEBe9CDEgkL08IdBK3BA4HYmBJAaV4X0kUcdDxbEwgYTbifAGpvNYEGI
xpkAwBubpZEAijSAkAFocKSHogMxgAYJCgxA4OOPQD6AwIWboQHDkUgmeaRzOjYpU0AAOw==
"""



##
## Application entry-points
##

def ProcessPackageFiles(builder, pkgfiles):
    """Subsidiary program entry-point if used as command-line application"""

    pkgset = PackageSet(pkgfiles)

    try:
        builder.BuildMirror(pkgset)
        garbage = builder.GetGarbage()
        confirmer = GarbageConfirmer(garbage,
                                default=builder.GetOption('RemoveOutdated'))
        confirmer.ActionResponse()

        isofile = builder.GetOption('ISOfilename')
        if isofile:
            builder.BuildISO(isofile)
    except Exception as ex:   # Treat separately for compatibility with Python-2.4
        print('Fatal error during mirroring [{0}]'.format(str(ex)),
              file=sys.stderr)
        #import traceback; traceback.print_exc()
    except BaseException as ex:
        print('Fatal error during mirroring [{0}]'.format(str(ex)),
              file=sys.stderr)


def TemplateMain(builder, outfile, pkgfiles, cygwinReplica=False):
    """Subsidiary program entry-point for command-line list generation"""

    builder.TemplateFromLists(outfile, pkgfiles, cygwinReplica)


def GUImain(builder, pkgfiles):
    """Subsidiary program entry-point if used as GUI application"""

    gui = TKgui(builder, pkgfiles=pkgfiles)
    gui.Run()



def main():
    builder = PMbuilder()

    # Process command-line options:
    parser = argparse.ArgumentParser(
                usage='%(prog)s [options] [package_file...]',
                description='pmcyg is a tool for generating'
                            ' customized Cygwin(TM) installers')
    parser.add_argument('--version', action='version',
            version=PMCYG_VERSION)

    bscopts = parser.add_argument_group('Basic options')
    bscopts.add_argument('-a', '--all', action='store_true',
            help='Include all available Cygwin packages'
                 ' (default=%(default)s)')
    bscopts.add_argument('-d', '--directory', type=str,
            default=os.path.join(os.getcwd(), 'cygwin'),
            help='Where to build local mirror (default=%(default)s)')
    bscopts.add_argument('-z', '--dry-run', action='store_true', dest='dummy',
            help='Do not actually download packages')
    bscopts.add_argument('-m', '--mirror', type=str,
            default=builder.mirror_url,
            help='URL of Cygwin archive or mirror site'
                 ' (default=%(default)s)')
    bscopts.add_argument('-c', '--nogui', action='store_true',
            help='Do not startup graphical user interface')
    bscopts.add_argument('-g', '--generate-template', type=str,
            dest='pkg_file', default=None,
            help='Generate template package-listing')
    bscopts.add_argument('-R', '--generate-replica', type=str,
            dest='cyg_list', default=None,
            help='Generate copy of existing Cygwin installation')
    bscopts.add_argument('package_files', nargs='*',
            help='Files containins list of Cygwin packages')

    advopts = parser.add_argument_group('Advanced options')
    advopts.add_argument('-A', '--cygwin-arch', type=str,
            default=builder.GetArch(),
            help='Target system architecture (default=%(default)s)')
    advopts.add_argument('-e', '--epochs', type=str,
            default=','.join(builder.GetEpochs()),
            help='Comma-separated list of epochs, e.g. "curr,prev"'
                ' (default=%(default)s)')
    advopts.add_argument('-x', '--exeurl', type=str,
            default=DEFAULT_INSTALLER_URL,
            help='URL of "setup.exe" Cygwin installer (default=%(default)s)')
    advopts.add_argument('-i', '--iniurl', type=str, default=None,
            help='URL of "setup.ini" Cygwin database (default=%(default)s)')
    advopts.add_argument('-B', '--nobase', action='store_true', default=False,
            help='Do not automatically include all base packages'
                ' (default=%(default)s)')
    advopts.add_argument('-r', '--with-autorun', action='store_true',
            help='Create autorun.inf file in build directory'
                ' (default=%(default)s)')
    advopts.add_argument('-s', '--with-sources',
            action='store_true', default=False,
            help='Include source-code for of each package'
                 ' (default=%(default)s)')
    advopts.add_argument('-o', '--remove-outdated', type=str,
            choices=('no', 'yes', 'ask'), default='no',
            help='Remove old versions of packages (default=%(default)s)')
    advopts.add_argument('-I', '--iso-filename', type=str, default=None,
            help='Filename for generating ISO image for burning to CD/DVD'
                ' (default=%(default)s)')

    args = parser.parse_args()

    builder.SetArch(args.cygwin_arch)
    builder.SetTargetDir(args.directory)
    builder.mirror_url = args.mirror
    builder.setup_ini_url = args.iniurl
    builder.setup_exe_url = args.exeurl
    builder.SetEpochs(args.epochs.split(','))
    builder.SetOption('DummyDownload', args.dummy)
    builder.SetOption('AllPackages', args.all)
    builder.SetOption('IncludeBase', not args.nobase)
    builder.SetOption('MakeAutorun', args.with_autorun)
    builder.SetOption('IncludeSources', args.with_sources)
    builder.SetOption('RemoveOutdated', args.remove_outdated)
    builder.SetOption('ISOfilename', args.iso_filename)

    if args.pkg_file:
        TemplateMain(builder, args.pkg_file, args.package_files)
    elif args.cyg_list:
        if not HOST_IS_CYGWIN:
            print('WARNING: pmcyg attempting to create replica of non-Cygwin host', file=sys.stderr)
        TemplateMain(builder, args.cyg_list,
                     args.package_files, cygwinReplica=True)
    elif HASGUI and not args.nogui:
        GUImain(builder, args.package_files)
    else:
        ProcessPackageFiles(builder, args.package_files)


if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
