#!/usr/bin/python
# Unit-tests for Cygwin Partial Mirror (pmcyg)
# RW Penney, August 2009

import os, string, sys, unittest, urlparse
sys.path.insert(0, '..')
from pmcyg import PMbuilder, MasterPackageList


class ParserTest(unittest.TestCase):
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
            self.fail()

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



if __name__ == "__main__":
    unittest.main()

# vim: set ts=4 sw=4 et:
