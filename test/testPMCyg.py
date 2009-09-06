#!/usr/bin/python
# Unit-tests for Cygwin Partial Mirror (pmcyg)
# RW Penney, August 2009

import os, string, sys, unittest, urlparse
sys.path.insert(0, '..')
from pmcyg import *


class testMasterPackageList(unittest.TestCase):
    pkglist = MasterPackageList()

    def setUp(self):
        if os.path.isfile('setup.ini'):
            txdirsep = string.maketrans('\\', '/')
            cwd = os.getcwd()
            self.urlprefix = 'file://' + cwd.translate(txdirsep) + '/'
            iniurl = urlparse.urljoin(self.urlprefix, 'setup.ini')
        else:
            iniurl = 'http://ftp.heanet.ie/pub/cygwin/setup.ini'

        try:
            self.pkglist.SetSourceURL(iniurl)
        except:
            self.fail('Failed to read setup.ini')

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
            ts = int(header['setup-timestamp'])
            self.failUnless(ts > (1 << 30))
            self.failUnless(ts < (1 << 31))
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
        self.failUnless(scores['version_curr'] >= 0.9 * numpkgs)
        self.failUnless(scores['install_curr'] >= 0.9 * numpkgs)
        self.failUnless(scores['source_curr'] >= 0.9 * numpkgs)
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



class testGarbageCollector(unittest.TestCase):
    def testNothing(self):
        self.fail('GarbageCollector test needs writing')



class testGarbageConfirmer(unittest.TestCase):
    class _collector(GarbageCollector):
        def __init__(self):
            GarbageCollector.__init__(self)

        def SetSuspicious(self, flag):
            self._suspicious = flag

    class _confirmer(GarbageConfirmer):
        def __init__(self, default):
            GarbageConfirmer.__init__(self, default)
            self.UserAsked = False
            self.UserResponse = False

        def _askUser(self, garbage):
            self.UserAsked = True
            return self.UserResponse

    def setUp(self):
        self.garbage = testGarbageConfirmer._collector()
        pass

    def tearDown(self):
        pass

    def testNo(self):
        for susp in [False, True]:
            self.garbage.SetSuspicious(susp)
            confirmer = testGarbageConfirmer._confirmer(default=GarbageConfirmer.NO)
            doDelete = confirmer(self.garbage)
            self.assertFalse(doDelete)
            self.assertFalse(confirmer.UserAsked)


    def testYes(self):
        for susp in [False, True] * 2:
            for resp in [False, True]:
                self.garbage.SetSuspicious(susp)
                confirmer = testGarbageConfirmer._confirmer(default=GarbageConfirmer.YES)
                confirmer.UserResponse = resp
                doDelete = confirmer(self.garbage)
                if susp:
                    self.assertEqual(doDelete, resp)
                    self.assertTrue(confirmer.UserAsked)
                else:
                    self.assertTrue(doDelete)
                    self.assertFalse(confirmer.UserAsked)

    def testAsk(self):
        for susp in [False, True]:
            for resp in [False, True]:
                self.garbage.SetSuspicious(susp)
                confirmer = testGarbageConfirmer._confirmer(default=GarbageConfirmer.ASK)
                confirmer.UserResponse = resp
                doDelete = confirmer(self.garbage)
                self.assertEqual(doDelete, resp)
                self.assertTrue(confirmer.UserAsked)



if __name__ == "__main__":
    unittest.main()

# vim: set ts=4 sw=4 et:
