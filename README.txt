        pmcyg - A tool for partially mirroring Cygwin(TM) packages
                        RW Penney, July 2009


This directory contains 'pmcyg', a tool for creating customized collections
of Cygwin(TM) packages. pmcyg is intended to support construction of
a self-contained CD or DVD that can be used to install or upgrade Cygwin
on machines that do not have network access to a Cygwin mirror site.

pmcyg avoids having to download the entirety of a Cygwin release, and
can allow a minimal Cygwin installation can be created within 20MB.
In general, pmcyg will take a user-supplied list of cygwin package names,
work out which other packages they depend on, and only download those packages
from a user-selected Cygwin mirror site.  It will then assemble a set of
configuration files that allows the Cygwin installer to operate from
the locally created repository.

All files are released under the GNU General Public License (v3)
(see http://www.gnu.org/licenses)
and are Copyright 2009 RW Penney <rwpenney@users.sourceforge.net>.


Installation
============

To run pmcyg, you will need to have a recent version of 'Python' installed
(preferably version 2.2-2.6). This should be available by default on most
GNU/Linux systems, or can be obtained from http://www.python.org

In order to use pmcyg as a graphical (GUI) application, you will need to have
the 'Tkinter' toolkit for Python. This is part of the default distribution of
Python for Windows platforms, but may be part of a separate package
(possibly called python-tk) on Unix/Linux systems.

On Windows platforms, double-clicking on the file 'pmcyg.py' should be
sufficient to run pmcyg in graphical mode.

On Unix/Linux systems, you may prefer to rename 'pmcyg.py'
to '/usr/local/bin/pmcyg'. The accompanying Makefile will do this
automatically if you execute 'make install'.

After installation, to use, try one of the following:

pmcyg --help
pmcyg --nogui --mirror http://NearbyMirrorLocation/pub/cygwin --directory MyBuildDirectory packagelist.txt
pmcyg --nogui --all

If you have the 'Tkinter' package installed, and pmcyg is run without
any command-line options , then mirror-locations and other options
can be controlled through a graphical user interface.



Usage
=====

pmcyg can be used either as an interactive graphical application,
or via a command-line interface suitable for use in scripts or batch processes.

A list of Cygwin mirror sites is available at http://cygwin.com/mirrors.html
You should try to use, with the '--mirror' option, a mirror site close
to your geographical location to avoid overloading the primary Cygwin
distribution site.



Please note
===========
    "Cygwin" is a trademark of Red Hat Inc.
    There is no official connection between pmcyg and the 'Cygwin' product
    pmcyg is currently in 'alpha' status
    pmcyg is supplied with NO WARRANTY and NO CLAIMS OF FITNESS FOR ANY PURPOSE.

# vim: set ts=4 sw=4 et:
