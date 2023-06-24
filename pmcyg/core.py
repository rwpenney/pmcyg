"""
Core downloading and package-list management tools for pmcyg
"""

# (C)Copyright 2009-2023, RW Penney <rwpenney@users.sourceforge.net>

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


import  bz2, codecs, hashlib, io, lzma, os, os.path, re, \
        string, subprocess, sys, threading, time, \
        urllib.request, urllib.parse, urllib.error, urllib.parse
from .version import PMCYG_VERSION


DEFAULT_CYGWIN_ARCH = 'x86_64'
DEFAULT_INSTALLER_URL = 'https://www.cygwin.com/setup${_arch}.exe'
#DEFAULT_CYGWIN_MIRROR = 'ftp://cygwin.com/pub/cygwin/'
DEFAULT_CYGWIN_MIRROR = 'https://www.mirrorservice.org/sites/sourceware.org/pub/cygwin'
CYGWIN_MIRROR_LIST_URL = 'https://www.cygwin.com/mirrors.lst'

# Character encoding used by the setup.ini file.
# This should probably by 'ascii', but occasional unicode characters
# have been observed within official set.ini files.
SI_TEXT_ENCODING = 'utf-8'

HOST_IS_CYGWIN = (sys.platform == 'cygwin')


def ConcatShortDescription(desc: str) -> str:
    """Concatenate multi-line short package description into single line"""
    if desc:
        return desc.replace('\n', ' ').replace('\r', '').rstrip()
        # s.replace is more portable between python-2.x & 3.x than s.translate
    else:
        return '???'
        # A null or empty short-description shouldn't go unnoticed


class PMCygException(Exception):
    """Wrapper for internally generated exceptions"""

    def __init__(self, *args) -> None:
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

    def __init__(self, verbosity: int=VRB_MEDIUM) -> None:
        self._operation = None
        self._verbThresh = verbosity

    def __call__(self, text: str, ctrl: int=SEV_NORMAL | VRB_MEDIUM) -> None:
        self.message(text, ctrl)

    def message(self, text: str, ctrl: int=SEV_NORMAL | VRB_MEDIUM) -> None:
        if self._operation:
            self._emit('  >>>\n', self._operation[1])
        self._emit('{0}\n'.format(text), ctrl)
        if self._operation:
            self._emit('  >>> {0}...'.format(self._operation[0]),
                       self._operation[1])

    def startOperation(self, text: str, ctrl: int=VRB_MEDIUM) -> None:
        self._operation = (text, ((ctrl & self.VRB_mask) | self.SEV_NORMAL))
        self._emit('{0}...'.format(text), self.SEV_NORMAL)

    def endOperation(self, text: str, ctrl: int=SEV_NORMAL) -> None:
        if not self._operation:
            return
        opVerbosity = (self._operation[1] & self.VRB_mask)
        self._emit(' {0}\n'.format(text),
                   ((ctrl & self.SEV_mask) | opVerbosity))
        self._operation = None

    def flushOperation(self) -> None:
        if not self._operation:
            return
        self._emit('\n', (self._operation[1] & self.VRB_mask))
        self._operation = None

    def _emit(self, text: str, ctrl: int) -> None:
        if (ctrl & self.VRB_mask) > self._verbThresh:
            return
        self._output(text, (ctrl & self.SEV_mask))

    def _output(self, text: str, severity: int): pass


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
    def __init__(self, Viewer: BuildViewer=None, Peer=None) -> None:
        self._statview = None
        if isinstance(Peer, BuildReporter) and not Viewer:
            Viewer = Peer._statview
        BuildReporter.SetViewer(self, Viewer)

    def SetViewer(self, Viewer):
        if not Viewer:
            Viewer = ConsoleBuildViewer()
        self._statview = Viewer



class SetupIniFetcher:
    """Facade for fetching setup.ini from URL, with optional decompression"""
    MaxIniFileLength = 1 << 26

    Decompressors = { 'bz2':    bz2.decompress,
                      'xz':     lzma.decompress }

    def __init__(self, URL):
        self._buffer = None
        suffix = URL.rsplit('.', 1)[-1]
        expander = self.Decompressors.get(suffix, (lambda x: x))
        with urllib.request.urlopen(URL) as stream:
            rawfile = expander(stream.read(self.MaxIniFileLength))

        self._buffer = io.StringIO(rawfile.decode(SI_TEXT_ENCODING, 'ignore'))

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

    len2alg: dict = {}

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

    def __init__(self, BuildDirectory: str='.',
                MirrorSite: str=DEFAULT_CYGWIN_MIRROR,
                CygwinInstaller: str=DEFAULT_INSTALLER_URL,
                Viewer: BuildViewer=None, **kwargs) -> None:

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
        self._cygarch = DEFAULT_CYGWIN_ARCH

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
        self._cygcheck_list: list = []
        for (opt, val) in kwargs.items():
            self.SetOption(opt, val)

    def SetViewer(self, Viewer: BuildViewer):
        BuildReporter.SetViewer(self, Viewer)
        self._masterList.SetViewer(self._statview)
        self._pkgProc.SetViewer(self._statview)
        self._garbage.SetViewer(self._statview)

    def GetTargetDir(self) -> str:
        return self._tgtdir

    def SetTargetDir(self, tgtdir: str) -> None:
        """Set the root directory beneath which packages will be downloaded"""
        self._tgtdir = tgtdir

    @property
    def setup_exe_url(self) -> str:
        """The URL of the setup.exe Cygwin installer"""
        keywords = { 'arch': self._cygarch,
                     '_arch': '-' + self._cygarch }
        exe_expr = self._exeurl
        if not exe_expr:
            exe_expr = DEFAULT_INSTALLER_URL
        exe_template = string.Template(exe_expr)
        return exe_template.substitute(keywords)

    @setup_exe_url.setter
    def setup_exe_url(self, URL: str) -> None:
        self._exeurl = URL

    @property
    def mirror_url(self) -> str:
        """The URL of the mirror site from which to download Cygwin packages"""
        return self._mirror

    @mirror_url.setter
    def mirror_url(self, URL: str) -> None:
        if not URL.endswith('/'):
            URL += '/'
        self._mirror = URL

    @property
    def setup_ini_url(self) -> str:
        """The (architecture-dependent) URL for the setup.ini package-list."""
        if self._iniurl:
            # Use prescribed URL directly:
            return self._iniurl
        else:
            # Base URL on chosen mirror site, and selected architecture:
            if self._cygarch:
                basename = '{0}/setup.xz'.format(self._cygarch)
            else:
                basename = 'setup.xz'
            return urllib.parse.urljoin(self._mirror, basename)

    @setup_ini_url.setter
    def setup_ini_url(self, URL: str) -> None:
        self._iniurl = URL
        self._masterList.SetSourceURL(self.setup_ini_url)

    def GetArch(self) -> str:
        return self._cygarch

    def SetArch(self, arch: str) -> None:
        self._cygarch = arch

    def GetEpochs(self) -> list:
        return self._epochs

    def SetEpochs(self, epochs: list) -> None:
        self._epochs = epochs

    def GetOption(self, optname: str):
        return self._optiondict.get(optname)

    def SetOption(self, optname: str, value):
        oldval = None
        try:
            oldval = self._optiondict[optname]
            self._optiondict[optname] = value
        except:
            raise PMCygException('Invalid configuration option "{0}"' \
                                    ' for PMbuilder'.format(optname))
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

            fields = line.split(';')
            n_fields = len(fields)
            if n_fields < 4 or (n_fields > 4 and fields[4] == 'noshow'):
                continue
            else:
                (url, ident, region, country) = fields[:4]

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


    def BuildMirror(self, pkgset) -> None:
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

    def TemplateFromLists(self, outfile: str, pkgfiles: list,
                          cygwinReplica: bool=False) -> None:
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
http://ucmirror.canterbury.ac.nz/cygwin/;ucmirror.canterbury.ac.nz;Australasia;New Zealand
https://mirror.csclub.uwaterloo.ca/cygwin/;mirror.csclub.uwaterloo.ca;North America;Canada
https://ftp.fsn.hu/pub/cygwin/;ftp.fsn.hu;Europe;Hungary
https://ftp.iij.ad.jp/pub/cygwin/;ftp.iij.ad.jp;Asia;Japan
https://mirror.csclub.uwaterloo.ca/cygwin/;mirror.csclub.uwaterloo.ca;North America;Canada
https://mirrors.dotsrc.org/cygwin/;mirrors.dotsrc.org;Europe;Denmark
https://www.mirrorservice.org/sites/sourceware.org/pub/cygwin/;www.mirrorservice.org;Europe;UK
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
        with codecs.open(spath, 'w', encoding=SI_TEXT_ENCODING) as fp:
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
            fp.write('\n')
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
            with open(sumfile, 'wt', encoding='utf-8') as hp:
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

    def ExpandDependencies(self, selected, epochs=['curr'],
                           ignoreUnresolved=False):
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

        if badpkgnames and not ignoreUnresolved:
            badpkgnames.sort()
            nBad, nMax = len(badpkgnames), 6
            truncbad = badpkgnames if nBad <= nMax \
                                   else badpkgnames[:(nMax-1)] + ['...']
            self._statview('The following package {n} names'
                           ' were not recognized:\n\t{p}'
                            .format(n=nBad, p='\n\t'.join(truncbad)),
                            BuildViewer.SEV_ERROR)
            raise PMCygException('Invalid package names {{ {p} }}[{n}]'
                                 ' in ExpandDependencies()'
                                 .format(n=nBad, p=', '.join(truncbad)))
        if badrequires:
            links = [ '{0}->{1}'.format(pkg, dep)
                        for (pkg, dep) in badrequires ]
            self._statview('Master package list contains unresolvable'
                           ' dependencies: {0}'.format(', '.join(links)),
                           BuildViewer.SEV_WARNING)

        packages = list(packages)
        packages.sort()

        return packages

    def ContractDependencies(self, pkglist, minvotes=6):
        """Remove (most) automatically installed packages from list,
        such that an initial selection of packages can be reduced to
        a minimal subset that has the same effect after dependency expansion."""
        dependencies = self._buildDependencies()
        votes = { p: 0 for p in pkglist }

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
        # containing loops, allowing for packages (e.g. zlib0) that might be
        # in the process of being declared obsolete:
        coverage = self.ExpandDependencies(primaries, ignoreUnresolved=True)
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
            userpkgs = set()

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
                if pkgset and pkg in pkgset:
                    prefix = ('', ' ')
                else:
                    if terse: continue
                    prefix = ('#', '')
                desc = ConcatShortDescription(pkgdict[pkg].GetAny('sdesc'))
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
        | (?P<package>^@ \s+ (?P<pkgName> \S+) $)
        | (?P<epoch>^\[ (?P<epochName>[a-z]+) \] $)
        | ((?P<field>^[a-zA-Z][-a-zA-Z0-9]+) : \s+ (?P<fieldVal> .*) $)
        | (?P<blank>^\s* $)
        ''', re.VERBOSE)

    RE_RSTRIP = re.compile(r'\s+$')

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
        """Acquire setup.ini file from supplied URL and parse package info

        The format of Cygwin's "setup.ini" files is described at
        https://sourceware.org/cygwin-apps/setup.ini.html
        """
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

        self._pkgdict.Set('TEXT', self.RE_RSTRIP.sub('', ''.join(self._pkgtxt)))
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
        all_deps = []
        deps, reqs = ( self.GetAny(f) for f in ('depends2', 'requires') )
        if deps:
            all_deps.extend(x.strip() for x in deps.split(','))
        if reqs:
            all_deps.extend(x.split())
        return sorted(set(all_deps))

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
