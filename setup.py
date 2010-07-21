#!/usr/bin/python
# (EXPERIMENTAL) Installation/setup script for Simple Python Fixed-Point Module
# RW Penney, July 2010

from distutils.core import setup
import distutils.command.build_scripts as DIB
import os
from pmcyg import PMCYG_VERSION


class pmcyg_build_scripts(DIB.build_scripts):
    def copy_scripts(self):
        print 'COPY_SCRIPTS: %s' % self.scripts
        orig_scripts = self.scripts
        tempfiles = []
        if os.name == 'posix':
            (self.scripts, tempfiles) = self._purgeSuffixes(orig_scripts)
        print str(orig_scripts) + ' -> ' + str(self.scripts)
        DIB.build_scripts.copy_scripts(self)
        self.scripts = orig_scripts
        for tmp in tempfiles:
            os.remove(tmp)

    def _purgeSuffixes(self, orig_scripts):
        """Remove .py suffix from Python scripts, e.g. for POSIX platforms"""
        newnames = []
        tempfiles = []

        for script in orig_scripts:
            newname = script
            if script.endswith('.py'):
                newname = script[:-3]
                try:
                    if os.path.exists(newname): raise IOError
                    os.symlink(script, newname)
                    tempfiles.append(newname)
                except:
                    newname = script
            newnames.append(newname)

        return (newnames, tempfiles)



setup(
    author = 'RW Penney',
    author_email = 'rwpenney@users.sourceforge.net',
    description = 'Utility for creating self-contained Cygwin installer',
    fullname = 'pmcyg - Cygwin partial mirror',
    keywords = 'Cygwin',
    license = 'GPL v3',
    long_description = 'More here',
    name = 'pmcyg',
    url = 'http://pmcyg.sourceforge.net',
    version = PMCYG_VERSION,
    scripts = [ 'pmcyg.py' ],
    cmdclass = { 'build_scripts': pmcyg_build_scripts }
)
