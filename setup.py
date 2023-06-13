#!/usr/bin/python3
# Installation/setup script for Simple Python Fixed-Point Module
# RW Penney, July 2010

from setuptools import setup
import os, re, sys, shutil
base_path = os.path.dirname(__file__)
sys.path.insert(0, base_path)
from pmcyg.version import PMCYG_VERSION


setup(
    author = 'RW Penney',
    author_email = 'rwpenney@users.sourceforge.net',
    description = 'Utility for creating offline Cygwin installers',
    fullname = 'pmcyg - Cygwin partial mirror',
    keywords = 'Cygwin',
    license = 'GPL v3',
    long_description = \
        'pmcyg is a tool for creating an offline Cygwin installer ' +
        'containing customized collections of packages. ' +
        'This avoids having to download the entirety of a Cygwin release, ' +
        'which might occupy many GB, instead allowing installers that ' +
        'can be as small as 40MB. ' +
        'pmcyg enables Cygwin installation from a self-contained ' +
        'CD/DVD image or USB-flash for use on systems ' +
        'without internet access.',
    name = 'pmcyg',
    url = 'https://github.com/rwpenney/pmcyg',
    download_url = 'https://github.com/rwpenney/pmcyg/archive/pmcyg-' \
                + PMCYG_VERSION + '.tar.gz',
    version = PMCYG_VERSION,
    packages = [ 'pmcyg' ],
    entry_points = {
        'console_scripts': [ 'pmcyg=pmcyg.command_line:main' ] },
    classifiers = [ 'Programming Language :: Python :: 3',
                    'Topic :: Utilities' ]
)
