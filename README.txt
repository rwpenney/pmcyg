        pmcyg - A tool for partially mirroring Cygwin(TM) packages
                        RW Penney, April 2009


This directory contains 'pmcyg', a Python script which allows one to create
a customized collection of Cygwin(TM) packages, without having to download
the entirety of a Cygwin release. For example, a minimal Cygwin installation
can be created within 20MB. pmcyg will take a user-supplied list of
cygwin package names, work out which other packages they depend on,
and only download those packages from a user-selected Cygwin mirror site.
It will then assemble a set of configuration files that all the Cygwin
installer to operate from the locally created repository.

All files are released under the Python PSF License
(see http://www.python.org/psf/license)
and are Copyright 2009 RW Penney.


To run pmcyg, you will need to have a recent version of 'Python' installed
(preferably version 2.2-2.6). This should be available by default on most
GNU/Linux systems, or from http://www.python.org

After installation, to use, try one of the following:

pmcyg --help
pmcyg --mirror http://NearbyMirrorLocation/pub/cygwin --directory MyBuildDirectory packagelist.txt
pmcyg --all


A list of Cygwin mirror sites is available at http://cygwin.com/mirrors.html
You should try to use, with the '--mirror' option, a mirror site close
to your geographical location to avoid overloading the primary Cygwin
distribution site.


Please note:
    "Cygwin" is a trademark of Red Hat Inc.
    There is no official connection between pmcyg and the 'Cygwin' product
    pmcyg is currently in 'alpha' status
    pmcyg is supplied with NO WARRANTY and NO CLAIMS OF FITNESS FOR ANY PURPOSE.

# vim: set ts=4 sw=4 et:
