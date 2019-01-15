#!/usr/bin/python3
# Unit-tests for Cygwin Partial Mirror (pmcyg)
# RW Penney, August 2009

import codecs, os, random, re, shutil, string, io, sys, \
        tempfile, unittest, urllib.parse
sys.path.insert(0, '..')
from pmcyg import *


def getSetupURL():
    if os.path.isfile('setup.ini'):
        cwd = os.getcwd()
        urlprefix = 'file://' + cwd.replace('\\', '/') + '/'
        return urllib.parse.urljoin(urlprefix, 'setup.ini')
    else:
        return 'http://www.mirrorservice.org/sites/sourceware.org/pub/cygwin/x86/setup.ini'



class testSetupIniFetcher(unittest.TestCase):
    """Test for opening of optionally compressed setup.ini via URL"""
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir)

    def testPlain(self):
        seed = random.randint(0, 1<<31)
        count = 1 << 16

        tmpfile = os.path.join(self._tmpdir, 'raw.txt')
        fp = open(tmpfile, 'wb')
        self._generate(fp, seed, count)
        fp.close()

        self._validate(tmpfile, seed, count)

    def testCompressed(self):
        seed = random.randint(0, 1<<31)
        count = 1 << 16

        tmpfile = os.path.join(self._tmpdir, 'comp.bz2')
        compressor = bz2.BZ2File(tmpfile, 'w')
        self._generate(compressor, seed, count)
        compressor.close()

        self._validate(tmpfile, seed, count)

    def _validate(self, filename, seed, count):
        fetcher = SetupIniFetcher('file:' + filename)
        nlines = 0
        for q in fetcher:
            val = int(q, 16)
            self.assertEqual(val, seed)
            seed = self._step(seed)
            nlines += 1
        self.assertEqual(nlines, count)
        fetcher.close()

    def _generate(self, handle, state, count):
        for p in range(0, count):
            handle.write(('%8x\n' % state).encode('ascii'))
            state = self._step(state)

    def _step(self, state):
        """Take step in linear congruential series (a la Park-Miller)"""
        scale = 69632
        dvsor = (1 << 31) - 1
        return (state * scale) % dvsor



class testHashChecker(unittest.TestCase):
    def testAlgMatch(self):
        HC = HashChecker()

        self.assertEqual(HC._guessHashAlg('a' * 32).name, 'md5')
        self.assertEqual(HC._guessHashAlg('a' * 64).name, 'sha256')
        self.assertEqual(HC._guessHashAlg('a' * 128).name, 'sha512')



class testMasterPackageList(unittest.TestCase):
    pkglist = MasterPackageList(Viewer=SilentBuildViewer())

    def setUp(self):
        iniurl = getSetupURL()
        try:
            self.pkglist.SetSourceURL(iniurl)
        except:
            self.fail('Failed to read setup.ini (%s)' % iniurl)

    def tearDown(self):
        pass

    def testBadURL(self):
        sublist = MasterPackageList(Viewer=SilentBuildViewer())
        try:
            sublist.SetSourceURL('http://nowhere/badurl.txt')
            (hdr, pkgs) = sublistGetHeaderAndPackages()
            self.fail()
        except:
            pass

    def testIngestion(self):
        (header, packages) = self.pkglist.GetHeaderAndPackages()

        self.assertFalse(header.get('setup-version') == None)
        try:
            ts = int(header['setup-timestamp'])
            self.assertTrue(ts > (1 << 30))
            self.assertTrue(ts < (1 << 31))
        except:
            self.fail()

        self.assertFalse(packages == None)
        self.assertTrue(len(packages) >= 1000)

    def testFieldPresence(self):
        fields = [ ('sdesc', 'curr'), ('category', None),
                    ('version', 'curr'), ('install', 'curr'),
                    ('source', 'curr'), ('install', 'prev') ]
        scores = {}
        for field in fields:
            scores[field] = 0

        (header, packages) = self.pkglist.GetHeaderAndPackages()

        numpkgs = 0
        for pkgname, pkgdict in packages.items():
            numpkgs += 1
            for (field, epoch) in fields:
                try:
                    fieldval = pkgdict.GetAny(field, [epoch])
                    scores[(field, epoch)] += 1
                except:
                    pass

        self.assertTrue(scores[('sdesc', 'curr')] == numpkgs)
        self.assertTrue(scores[('category', None)] == numpkgs)
        self.assertTrue(scores[('version', 'curr')] >= 0.8 * numpkgs)
        self.assertTrue(scores[('install', 'curr')] >= 0.8 * numpkgs)
        self.assertTrue(scores[('source', 'curr')] >= 0.75 * numpkgs)
        self.assertTrue(scores[('install', 'prev')] >= 0.3 * numpkgs)

    def testLongDescriptions(self):
        (header, packages) = self.pkglist.GetHeaderAndPackages()

        numpkgs = 0
        numldesc = 0
        totlines = 0
        for pkgname, pkgdict in packages.items():
            numpkgs += 1
            ldesc = pkgdict.GetAny('ldesc', ['curr'])
            if ldesc:
                numldesc += 1
            else:
                ldesc = ""

            lines = ldesc.split('\n')
            desclen = len(lines)
            totlines += desclen
            blanks = 0
            for line in lines:
                if not line.strip():
                    blanks += 1

            self.assertFalse(blanks > (desclen + 2) / 3)

        self.assertTrue(numldesc >= 0.7 * numpkgs)
        self.assertTrue(totlines > 2 * numldesc)

    def testCategories(self):
        packages = self.pkglist.GetPackageDict()
        categories = self.pkglist.GetCategories()

        if not categories.get('All'):
            self.fail()

        for cat, members in categories.items():
            if cat != 'All':
                for pkgname in members:
                    try:
                        pkginfo = packages[pkgname]
                        cats = pkginfo.GetAny('category').split()
                    except:
                        cats = None
                    self.assertTrue(cat in cats)
            else:
                self.assertEqual(len(members), len(packages))

                for pkgname in members:
                    self.assertTrue(pkgname in iter(packages.keys()))



class testPkgSetProcessor(unittest.TestCase):
    def setUp(self):
        self.masterList = MasterPackageList(Viewer=SilentBuildViewer())
        self.masterList.SetSourceURL(getSetupURL())

    def testExpand(self):
        pkgProc = PkgSetProcessor(self.masterList)

        explist = pkgProc.ExpandDependencies([])
        self.assertEqual(len(explist), 0)

        explist = pkgProc.ExpandDependencies(['make'])
        self.assertTrue(len(explist) > 6)
        self.checkSubset(explist, ['make', 'bash', 'coreutils', 'cygwin',
                                    'libgcc1', 'terminfo'])

        explist = pkgProc.ExpandDependencies(['bash', 'libboost-devel', 'bvi'])
        self.assertTrue(len(explist) > 20)
        self.checkSubset(explist, ['bash', 'bvi', 'libboost-devel', 'cygwin',
                                    'libattr1', 'libgcc1',
                                    'libreadline7', 'pkg-config', 'terminfo'])

    def testInverse(self):
        """Check that contraction can be inverted by expansion"""
        pkgdict = self.masterList.GetPackageDict()
        pkglist = [p for p in pkgdict.keys()]

        for iterations in range(0, 100):
            pkgProc = PkgSetProcessor(self.masterList)

            selected = random.sample(pkglist, random.randint(1, 20))

            full = pkgProc.ExpandDependencies(selected)
            contracted = pkgProc.ContractDependencies(full)
            expanded = pkgProc.ExpandDependencies(contracted)

            self.assertEqual(full, expanded)

    def checkSubset(self, entire, sub):
        missing = set(sub) - set(entire)
        if missing:
            self.fail('Missing packages {{ {} }}'
                        .format(', '.join(sorted(missing))))


class testBuilder(unittest.TestCase):
    def setUp(self):
        self.builder = PMbuilder(Viewer=SilentBuildViewer())
        self.builder.setup_ini_url = getSetupURL()
        self.builder.SetTargetDir(tempfile.mkdtemp())
        self.makeTemplate = self.builder._pkgProc.MakeTemplate

    def tearDown(self):
        shutil.rmtree(self.builder.GetTargetDir())

    def testBuildSetups(self):
        """Check construction of setup.ini & setup.bz2 files"""
        tgtdir = self.builder.GetTargetDir()
        selected = ['bash', 'cmake', 'octave']
        self.builder._buildSetupFiles(selected)

        arch = self.builder.GetArch()
        f_ini = os.path.join(tgtdir, arch, 'setup.ini')
        f_bz2 = os.path.join(tgtdir, arch, 'setup.bz2')
        f_exe = os.path.join(tgtdir, 'setup-%s.exe' % arch)

        self.assertTrue(os.path.isfile(f_ini))
        self.assertTrue(os.path.isfile(f_bz2))
        self.assertTrue(os.path.isfile(f_exe))

        self.assertTrue(os.path.getsize(f_ini) > (1 << 10))
        self.assertTrue(os.path.getsize(f_bz2) > (1 << 9))
        self.assertTrue(os.path.getsize(f_exe) > (1 << 18))

        pkgs = []
        re_pkg = re.compile(r'^@\s+(\S*)$')
        fp = open(f_ini, 'rt')
        for line in fp:
            match = re_pkg.match(line)
            if not match: continue
            pkgs.append(match.group(1))
        fp.close()
        self.assertEqual(len(pkgs), len(selected))
        for pkg in selected:
            self.assertTrue(pkg in pkgs)

    def testDummyDownloads(self):
        for arch in [ 'x86', 'x86_64' ]:
            builder = PMbuilder(Viewer=SilentBuildViewer())
            builder.SetOption('DummyDownload', True)
            builder.SetArch(arch)

            pkgset = PackageSet([ os.path.join('..', 'example.pkgs') ])
            for ident, pset, cfg in [ ( 'basic', None, None ),
                                      ( 'custom', pkgset, None ),
                                      ( 'global', None, 'AllPackages' ),
                                      ( 'source', None, 'IncludeSources' ) ]:

                if cfg:
                    builder.SetOption(cfg, True)
                try:
                    builder.BuildMirror(pset)
                    conf = GarbageConfirmer(builder.GetGarbage(), 'no')
                except Exception as ex:
                    self.fail('Build failed (%s/%s) - %s' \
                                % ( arch, ident, str(ex)))

    def testTemplate(self):
        topdir = tempfile.mkdtemp()
        try:
            tplt = os.path.join(topdir, 'templates.txt')
            fp = codecs.open(tplt, 'w', 'utf-8')
            self.makeTemplate(fp)
            fp.close()

            counts = self.templateCounts(tplt)
            self.assertTrue(counts['categories'] >= 20)
            self.assertTrue(counts['categories'] <= 100)
            self.assertTrue(counts['packages'] >= 1000)

        finally:
            shutil.rmtree(topdir)

    def testTerseTemplate(self):
        topdir = tempfile.mkdtemp()
        try:
            tplt = os.path.join(topdir, 'terse.txt')
            pkgset = PackageSet()
            pkgset.extend(['bash', 'flex', 'tcsh', 'vim', 'zsh'])
            fp = codecs.open(tplt, 'w', 'utf-8')
            self.makeTemplate(fp, pkgset, terse=True)
            fp.close()

            counts = self.templateCounts(tplt)
            self.assertEqual(counts['categories'], 4)
            self.assertEqual(counts['packages'], 6)

        finally:
            shutil.rmtree(topdir)

    def templateCounts(self, tplt):
        """Basic sanity checking on template package listing"""
        re_category = re.compile(r'^## [^#]+$')
        re_package = re.compile(r'^#?[a-zA-Z][^ ]*\s+#[^#]*$')
        counts = { 'categories':0, 'packages':0 }

        fp = open(tplt, 'rt')
        for line in fp:
            if re_category.match(line):
                counts['categories'] += 1
            if re_package.match(line):
                counts['packages'] += 1
        fp.close()

        return counts



class testPackageSets(unittest.TestCase):
    def setUp(self):
        pass

    def testBare(self):
        pkgset = PackageSet()
        self.assertEqual(len(pkgset), 0)
        self.assertFalse('bash' in pkgset)
        self.assertEqual(len(pkgset.extract()), 0)

        pkgset.extend([ 'bash', 'tcsh', 'xorg'])
        self.assertTrue('bash' in pkgset)
        self.assertTrue('xorg' in pkgset)
        self.assertFalse('missing' in pkgset)

        self.assertEqual(len(pkgset.extract()), 3)
        self.assertTrue('tcsh' in pkgset.extract())

    def testIngest(self):
        f0 = io.StringIO('bash\ntcsh\nzsh\n')
        f1 = io.StringIO('emacs\nnedit\nvim\nbash\n')

        pkgset = PackageSet()
        self.assertEqual(len(pkgset), 0)

        pkgset._ingestStream(f0)
        self.assertEqual(len(pkgset), 3)
        pkgset._ingestStream(f1)
        self.assertEqual(len(pkgset), 6)

        self.assertTrue('bash' in pkgset)
        self.assertTrue('nedit' in pkgset)
        self.assertFalse('joe' in pkgset)

        pkgset.extend(['tcsh', 'xorg', 'emacs', 'joe'])
        self.assertEqual(len(pkgset), 8)
        self.assertTrue('joe' in pkgset)
        self.assertTrue('nedit' in pkgset)

        pkgs = pkgset.extract()
        self.assertEqual(pkgs, ['bash', 'emacs', 'joe', 'nedit',
                                'tcsh', 'vim', 'xorg', 'zsh'])

    def testArchIngest(self):
        lines = [   'bash    [arch=x86]      # comment',
                    'dash                    # Debian almquist shell',
                    'sh      [arch=x86,amd64]',
                    'tcsh    [arch=amd64]    # non-standard architecture',
                    'zsh     [arch=x86_64]' ]

        pkgset = PackageSet()
        pkgset._ingestStream(io.StringIO('\n'.join(lines)))
        self.assertEqual(len(pkgset), 5)

        pkgs = pkgset.extract()
        self.assertEqual(pkgs, ['bash', 'dash', 'sh', 'tcsh', 'zsh'])

        pkgs = pkgset.extract(arch='x86')
        self.assertEqual(pkgs, ['bash', 'dash', 'sh'])

        pkgs = pkgset.extract(arch='x86_64')
        self.assertEqual(pkgs, ['dash', 'zsh'])

        pkgs = pkgset.extract(arch='amd64')
        self.assertEqual(pkgs, ['dash', 'sh', 'tcsh'])

    def testArchMerge(self):
        lines0 = [  'bash   [arch=x86]',
                    'dash',
                    'sh     [arch=invalid]',
                    'tcsh   [arch=amd64,x86]',
                    'zsh    [arch=x86_64]' ]
        lines1 = [  'bash   [arch=x86_64]',
                    'dash   [arch=amd64]',
                    'sh',
                    'sox    [arch=x86_64]' ]

        pkgset = PackageSet()
        for defn in [lines0, lines1]:
            pkgset._ingestStream(io.StringIO('\r\n'.join(defn)))
        self.assertEqual(len(pkgset), 6)

        pkgs = pkgset.extract()
        self.assertEqual(pkgs, ['bash', 'dash', 'sh', 'sox', 'tcsh', 'zsh'])

        pkgs = pkgset.extract(arch='x86')
        self.assertEqual(pkgs, ['bash', 'dash', 'sh', 'tcsh'])

        pkgs = pkgset.extract(arch='x86_64')
        self.assertEqual(pkgs, ['bash', 'dash', 'sh', 'sox', 'zsh'])

        pkgs = pkgset.extract(arch='amd64')
        self.assertEqual(pkgs, ['dash', 'sh', 'tcsh'])

    def testCommenting(self):
        lines = [   'bash',
                    '#dash',
                    '# an ordinary comment',
                    'sh     [arch=x86]  # basic shell'
                    '#tcsh      # enhanced C-shell'
                    '#zsh   [arch=x86_64]   # zed shell' ]

        pkgset = PackageSet()
        pkgset._ingestStream(io.StringIO('\n'.join(lines)))
        self.assertEqual(len(pkgset), 2)

        pkgs = pkgset.extract()
        self.assertEqual(pkgs, ['bash', 'sh'])



class testPackageLists(unittest.TestCase):
    def setUp(self):
        re_cfg = re.compile(r'^setup.*\.ini$')
        cwd = os.getcwd()
        dirlist = os.listdir(cwd)
        self._configs = [ f for f in dirlist if re_cfg.match(f)
                                                and os.path.isfile(f) ]
        self._urlprefix = 'file://' + cwd.replace('\\', '/') + '/'

    def testIO(self):
        """Test that setup.ini files of various generations,
        and containing various mixes of ascii/latin-1/utf-8 characters
        can be parsed and rewritten without exceptions or glaring errors"""
        for cfg in self._configs:
            url = urllib.parse.urljoin(self._urlprefix, cfg)
            tmpdir = tempfile.mkdtemp()

            builder = PMbuilder(Viewer=SilentBuildViewer())
            builder.setup_ini_url = url
            builder.SetTargetDir(tmpdir)

            builder._optiondict['AllPackages'] = True
            pkglist = builder._extendPkgSelection()
            self.assertTrue(len(pkglist) > 4)

            arch = builder.GetArch()
            f_ini = os.path.join(tmpdir, arch, os.path.basename(cfg))
            f_ini = os.path.join(tmpdir, arch, 'setup.ini')
            f_tplt = os.path.join(tmpdir, 'tplt.txt')

            self.assertFalse(os.path.isfile(f_ini))
            builder._buildSetupFiles(pkglist)
            self.assertTrue(os.path.isfile(f_ini))

            self.assertFalse(os.path.isfile(f_tplt))
            fp = codecs.open(f_tplt, 'w', 'utf-8')
            builder._pkgProc.MakeTemplate(fp)
            self.assertTrue(fp.tell() > 100)
            fp.close()

            shutil.rmtree(tmpdir)



class testMirrorLists(unittest.TestCase):
    def testHasFallback(self):
        fp = PMbuilder._makeFallbackMirrorList()
        (regionDict, urlDict) = self.mkSets(fp)
        fp.close()
        self.assertTrue(len(regionDict) > 3)
        self.assertTrue(len(urlDict) > 4)
        self.assertTrue(('Asia', 'Japan') in regionDict)
        self.assertTrue(('Europe', 'UK') in regionDict)

    def testValidFallback(self):
        fp0 = PMbuilder._makeFallbackMirrorList()
        (fb_regions, fb_urls) = self.mkSets(fp0)
        fp0.close()
        fp1 = urllib.request.urlopen(CYGWIN_MIRROR_LIST_URL)
        (cyg_regions, cyg_urls) = self.mkSets(fp1)
        fp1.close()

        self.assertTrue(len(cyg_regions) > 8)
        self.assertTrue(len(cyg_urls) > 12)

        for reg in fb_regions:
            if not reg in cyg_regions:
                self.fail('Mirror region %s/%s does not appear'
                          ' in official list' % reg)
        for url in fb_urls:
            if not url in cyg_urls:
                self.fail('Mirror %s does not appear in official list'
                          % url)

    def mkSets(self, fp):
        regionDict = {}
        urlDict = {}

        for line in fp:
            try:
                entry = line.decode('ascii', 'ignore').strip().split(';')
                (url, ident, region, country) = entry
            except:
                continue
            regionDict.setdefault((region, country), []).append((url, ident))
            urlDict[url] = (ident, region, country)

        return (regionDict, urlDict)



class testGarbageCollector(unittest.TestCase):
    def testAbsentTopdir(self):
        topdir = tempfile.mkdtemp()
        try:
            subdir = os.path.join(topdir, 'non-existent')

            try:
                collector = GarbageCollector([ subdir ])
                collector = GarbageCollector(topdir)
            except:
                self.fail('GarbageCollector construction failed')

        finally:
            shutil.rmtree(topdir)

    def testRescuing(self):
        re_tree = re.compile(r'tree-norm-[0-9]*$')
        dirlist = os.listdir('.')
        for item in dirlist:
            if not re_tree.match(item):
                continue

            topdir = tempfile.mkdtemp()
            try:
                treedict = makeGarbageTree(item, topdir)
                collector = GarbageCollector([ topdir ])

                rescuedfiles = []
                deletedfiles = []
                for file in treedict['files']:
                    if random.randint(0, 1):
                        collector.RescueFile(file)
                        rescuedfiles.append(file)
                    else:
                        deletedfiles.append(file)

                self.assertEqual(collector.IsSuspicious(), False)
                if collector.IsSuspicious():
                    break
                collector.PurgeFiles()

                for presence, filelist in [ (True, rescuedfiles),
                                            (False, deletedfiles) ]:
                    for file in filelist:
                        fullname = os.path.join(topdir, file)
                        self.assertEqual(presence, os.path.isfile(fullname))
            finally:
                shutil.rmtree(topdir)

    def testSuspiciousTrees(self):
        re_tree = re.compile(r'^tree-([a-z]*)-([0-9]*)$')
        dirlist = os.listdir('.')
        for item in dirlist:
            matches = re_tree.match(item)
            if not matches or matches.lastindex < 2:
                continue
            if matches.group(1).startswith('susp'):
                verdict = True
            else:
                verdict = False
            index = matches.group(2)

            topdir = tempfile.mkdtemp()
            try:
                makeGarbageTree(item, topdir)
                collector = GarbageCollector(topdir)
                self.assertEqual(collector.IsSuspicious(), verdict,
                                msg='Suspiciousness failure on "%s"' % item)
            finally:
                shutil.rmtree(topdir)



def makeGarbageTree(treefile, topdir='.'):
    """Create outline directory tree for testing GarbageCollector"""

    treedict = { 'directories':[], 'files':[] }

    fp = open(treefile, 'rt')
    for line in fp:
        idx = line.find('#')
        if idx >= 0:
            line = line[0:idx]
        line = line.strip()
        if not line:
            continue

        fields = line.split(None, 1)
        ftype = fields[0].upper()
        fname = fields[1].replace('/', os.sep)
        fname = os.path.join(topdir, fname)

        if ftype == 'D':
            try:
                os.mkdir(fname)
                treedict['directories'].append(fname)
            except OSError:
                pass
        elif ftype == 'F':
            fp2 = open(fname, 'wt')
            flen = random.randint(0, 512)
            print((chr(0x5a) * flen), file=fp2)
            fp2.close()
            treedict['files'].append(fname)
        else:
            pass
    fp.close()

    return treedict



class testGarbageConfirmer(unittest.TestCase):
    class _collector(GarbageCollector):
        def __init__(self):
            GarbageCollector.__init__(self)

        def SetSuspicious(self, flag):
            self._suspicious = flag

        def GetNeatList(self):
            return [ 'nowhere' ]

    class _confirmer(GarbageConfirmer):
        def __init__(self, garbage, default, cannedresponse=None):
            self.UserAsked = False
            self._cannedresponse = cannedresponse

            GarbageConfirmer.__init__(self, garbage, default)

        def _askUser(self, allfiles):
            self.UserAsked = True
            self._userresponse = self._cannedresponse

    def setUp(self):
        self.garbage = testGarbageConfirmer._collector()

    def tearDown(self):
        pass

    def testNo(self):
        for susp in [False, True]:
            self.garbage.SetSuspicious(susp)
            confirmer = testGarbageConfirmer._confirmer(self.garbage, default='no')
            doDelete = confirmer.HasResponded()
            self.assertEqual(doDelete, 'no')
            self.assertFalse(confirmer.UserAsked)


    def testYes(self):
        for susp in [False, True] * 2:
            for resp in ['no', 'yes']:
                self.garbage.SetSuspicious(susp)
                confirmer = testGarbageConfirmer._confirmer(self.garbage, default='yes', cannedresponse=resp)
                doDelete = confirmer.HasResponded()
                if susp:
                    self.assertEqual(doDelete, resp)
                    self.assertTrue(confirmer.UserAsked)
                else:
                    self.assertEqual(doDelete, 'yes')
                    self.assertFalse(confirmer.UserAsked)

    def testAsk(self):
        for susp in [False, True]:
            for resp in ['no', 'yes']:
                self.garbage.SetSuspicious(susp)
                confirmer = testGarbageConfirmer._confirmer(self.garbage, default='ask', cannedresponse=resp)
                doDelete = confirmer.HasResponded()
                self.assertEqual(doDelete, resp)
                self.assertTrue(confirmer.UserAsked)



if __name__ == "__main__":
    unittest.main()

# vim: set ts=4 sw=4 et:
