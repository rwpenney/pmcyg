#!/usr/bin/python3
# Installation/setup script for Simple Python Fixed-Point Module
# RW Penney, July 2010

from distutils.core import setup
import distutils.command.build_scripts as DIB
import os, re

pmcyg_scripts = [ 'pmcyg.py' ]


class pmcyg_build_scripts(DIB.build_scripts):
    """Helper class to strip filename suffixes when
    installing Python scripts on POSIX platforms"""
    def copy_scripts(self):
        orig_scripts = self.scripts
        tempfiles = []
        if os.name == 'posix':
            (self.scripts, tempfiles) = self._stripSuffixes(orig_scripts)
        DIB.build_scripts.copy_scripts(self)
        self.scripts = orig_scripts
        for tmp in tempfiles:
            os.remove(tmp)

    def _stripSuffixes(self, orig_scripts):
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



# Extract version number from pmcyg.py script
# NOTE that we cannot just 'from pmcyg import PMCYG_VERSION' because
#   python3.x might reject the syntax of a python2.x script
try:
    PMCYG_VERSION = re.compile(r'^PMCYG_VERSION\s*=\s[\'"](.*)["\']$',
                                re.MULTILINE) \
                        .search(open('pmcyg.py', 'rt').read()).group(1)
except:
    PMCYG_VERSION = '0.x'


setup(
    author = 'RW Penney',
    author_email = 'rwpenney@users.sourceforge.net',
    description = 'Utility for creating offline Cygwin installers',
    fullname = 'pmcyg - Cygwin partial mirror',
    keywords = 'Cygwin',
    license = 'GPL v3',
    long_description = \
        'pmcyg is a tool for creating offline Cygwin(TM) installers ' +
        'containing customized collections of Cygwin packages. ' +
        'This avoids having to download the entirety of a Cygwin release, ' +
        'which might occupy many GB, instead allowing installers that ' +
        'can be as small as 40MB. ' +
        'pmcyg will help build a self-contained CD or DVD installer to setup ' +
        'Cygwin on PCs without any internet access.',
    name = 'pmcyg',
    url = 'https://github.com/rwpenney/pmcyg',
    download_url = 'https://github.com/rwpenney/pmcyg/archive/pmcyg-' \
                + PMCYG_VERSION + '.tar.gz',
    version = PMCYG_VERSION,
    scripts = pmcyg_scripts,
    cmdclass = { 'build_scripts': pmcyg_build_scripts },
    classifiers = [ 'Programming Language :: Python :: 3',
                    'Topic :: Utilities' ]
)
