#!/usr/bin/python
# Unit-tests for Cygwin Partial Mirror (pmcyg)
# RW Penney, August 2009

import os, random, re, shutil, string, sys, tempfile, unittest, urlparse
sys.path.insert(0, '..')
from pmcyg import *


def getSetupURL():
    if os.path.isfile('setup.ini'):
        txdirsep = string.maketrans('\\', '/')
        cwd = os.getcwd()
        urlprefix = 'file://' + cwd.translate(txdirsep) + '/'
        return urlparse.urljoin(urlprefix, 'setup.ini')
    else:
        return 'http://ftp.heanet.ie/pub/cygwin/setup.ini'



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
        fp = open(tmpfile, 'wt')
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

    def _generate(self, handle, state, count):
        for p in xrange(0, count):
            handle.write('%8x\n' % state)
            state = self._step(state)

    def _step(self, state):
        """Take step in linear congruential series (a la Park-Miller)"""
        scale = 69632
        dvsor = (1 << 31) - 1
        return (state * scale) % dvsor



class testMasterPackageList(unittest.TestCase):
    pkglist = MasterPackageList()

    def setUp(self):
        iniurl = getSetupURL()
        try:
            self.pkglist.SetSourceURL(iniurl)
        except:
            self.fail('Failed to read setup.ini (%s)' % iniurl)

    def tearDown(self):
        pass

    def testBadURL(self):
        sublist = MasterPackageList()
        try:
            sublist.SetSourceURL('http://nowhere/badurl.txt')
            (hdr, pkgs) = sublistGetHeaderAndPackages()
            self.fail()
        except:
            pass

    def testIngestion(self):
        (header, packages) = self.pkglist.GetHeaderAndPackages()

        self.failIf(header.get('setup-version') == None)
        try:
            ts = long(header['setup-timestamp'])
            self.failUnless(ts > (1L << 30))
            self.failUnless(ts < (1L << 31))
        except:
            self.fail()

        self.failIf(packages == None)
        self.failUnless(len(packages) >= 1000)

    def testFieldPresence(self):
        fields = ['sdesc_curr', 'category_curr', 'version_curr',
                'install_curr', 'source_curr', 'install_prev']
        scores = {}
        for field in fields:
            scores[field] = 0

        (header, packages) = self.pkglist.GetHeaderAndPackages()

        numpkgs = 0
        for pkgname, pkgdict in packages.iteritems():
            numpkgs += 1
            for field in fields:
                try:
                    fieldval = pkgdict[field]
                    scores[field] += 1
                except:
                    pass

        self.failUnless(scores['sdesc_curr'] == numpkgs)
        self.failUnless(scores['category_curr'] == numpkgs)
        self.failUnless(scores['version_curr'] >= 0.8 * numpkgs)
        self.failUnless(scores['install_curr'] >= 0.8 * numpkgs)
        self.failUnless(scores['source_curr'] >= 0.75 * numpkgs)
        self.failUnless(scores['install_prev'] >= 0.3 * numpkgs)

    def testLongDescriptions(self):
        (header, packages) = self.pkglist.GetHeaderAndPackages()

        numpkgs = 0
        numldesc = 0
        totlines = 0
        for pkgname, pkgdict in packages.iteritems():
            numpkgs += 1
            try:
                ldesc = pkgdict['ldesc_curr']
                numldesc += 1
            except:
                ldesc = ""
                pass

            lines = ldesc.split('\n')
            desclen = len(lines)
            totlines += desclen
            blanks = 0
            for line in lines:
                if not line.strip():
                    blanks += 1

            self.failIf(blanks > (desclen + 2) / 3)

        self.failUnless(numldesc >= 0.7 * numpkgs)
        self.failUnless(totlines > 2 * numldesc)

    def testCategories(self):
        packages = self.pkglist.GetPackageDict()
        categories = self.pkglist.GetCategories()

        if not categories.get('All'):
            self.fail()

        for cat, members in categories.iteritems():
            if cat != 'All':
                for pkgname in members:
                    try:
                        pkginfo = packages[pkgname]
                        cats = pkginfo['category_curr'].split()
                    except:
                        cats = None
                    self.failUnless(cat in cats)
            else:
                self.assertEqual(len(members), len(packages))

                for pkgname in members:
                    self.failUnless(pkgname in packages.iterkeys())



class testPackageDatabase(unittest.TestCase):
    def setUp(self):
        self.masterList = MasterPackageList()
        self.masterList.SetSourceURL(getSetupURL())

    def testExpand(self):
        pkgDB = PackageDatabase(self.masterList)

        explist = pkgDB.ExpandDependencies([])
        self.assertEqual(len(explist), 0)

        explist = pkgDB.ExpandDependencies(['make'])
        self.assertTrue(len(explist) > 6)
        self.checkSubset(explist, ['make', 'bash', 'coreutils', 'cygwin',
                                    'libgcc1', 'tzcode'])

        explist = pkgDB.ExpandDependencies(['bash', 'boost', 'bvi'])
        self.assertTrue(len(explist) > 20)
        self.checkSubset(explist, ['bash', 'boost', 'bvi',
                                    'boost-devel', 'cygwin', 'libboost',
                                    'libexpat1', 'libgcc1', 'libncurses8',
                                    'libreadline7', 'python', 'zlib'])

    def testInverse(self):
        """Check that contraction can be inverted by expansion"""
        pkgdict = self.masterList.GetPackageDict()
        pkglist = [p for p in pkgdict.iterkeys()]

        for iterations in range(0, 100):
            pkgDB = PackageDatabase(self.masterList)

            selected = random.sample(pkglist, random.randint(1, 20))

            full = pkgDB.ExpandDependencies(selected)
            contracted = pkgDB.ContractDependencies(full)
            expanded = pkgDB.ExpandDependencies(contracted)

            self.assertEqual(full, expanded)

    def checkSubset(self, entire, sub):
        for p in sub:
            self.assertTrue(p in entire)



class testGarbageCollector(unittest.TestCase):
    def testAbsentTopdir(self):
        topdir = tempfile.mkdtemp()
        try:
            subdir = os.path.join(topdir, 'non-existent')

            try:
                collector = GarbageCollector(subdir)
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
                collector = GarbageCollector(topdir)

                rescuedfiles = []
                deletedfiles = []
                for file in treedict['files']:
                    if random.randint(0,1):
                        collector.RescueFile(file)
                        rescuedfiles.append(file)
                    else:
                        deletedfiles.append(file)

                collector.PurgeFiles()
                self.assertEqual(collector.IsSuspicious(), False)

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
            fp = open(fname, 'wb')
            flen = random.randint(0, 512)
            fp.write(chr(0xaa) * flen)
            fp.close()
            treedict['files'].append(fname)
        else:
            pass

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


# Ensure support for older versions of unittest (e.g. Python-2.3):
try:
    fn = unittest.TestCase.assertTrue
    fn = unittest.TestCase.assertFalse
except AttributeError:
    def assTrue(obj, arg):
        obj.assertEqual(arg, True)
    def assFalse(obj, arg):
        obj.assertEqual(arg, False)
    unittest.TestCase.assertTrue = assTrue
    unittest.TestCase.assertFalse = assFalse


if __name__ == "__main__":
    unittest.main()

# vim: set ts=4 sw=4 et:
