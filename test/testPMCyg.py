#!/usr/bin/python
# Unit-tests for Cygwin Partial Mirror (pmcyg)
# RW Penney, August 2009

import os, string, sys, unittest, urlparse
sys.path.insert(0, '..')
from pmcyg import PMbuilder, PackageListParser


class ParserTest(unittest.TestCase):
    def setUp(self):
        txdirsep = string.maketrans('\\', '/')
        cwd = os.getcwd()
        self.urlprefix = 'file://' + cwd.translate(txdirsep) + '/'

        try:
            parser = PackageListParser()
            iniurl = urlparse.urljoin(self.urlprefix, 'setup.ini')
            self.header, self.packages = parser.Parse(iniurl)
        except:
            self.fail()

    def tearDown(self):
        self.parser = None

    def testBadURL(self):
        parser = PackageListParser()
        try:
            parser.Parse('http://nowhere/badurl.txt')
            self.fail()
        except:
            pass

    def testIngestion(self):

        self.failIf(self.header.get('setup-version') == None)
        try:
            ts = int(self.header['setup-timestamp'])
            self.failUnless(ts > (1 << 30))
            self.failUnless(ts < (1 << 31))
        except:
            self.fail()

        self.failIf(self.packages == None)
        self.failUnless(len(self.packages) >= 1000)

    def testFieldPresence(self):
        fields = ['sdesc_curr', 'category_curr', 'version_curr',
                'install_curr', 'source_curr', 'install_prev']
        scores = {}
        for field in fields:
            scores[field] = 0

        numpkgs = 0
        for pkgname, pkgdict in self.packages.iteritems():
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
        numpkgs = 0
        numldesc = 0
        totlines = 0
        for pkgname, pkgdict in self.packages.iteritems():
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



if __name__ == "__main__":
    unittest.main()

# vim: set ts=4 sw=4 et:
