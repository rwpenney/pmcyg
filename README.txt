        pmcyg - A tool for partially mirroring Cygwin(TM) packages
                        RW Penney, July 2009


Introduction
============

This directory contains 'pmcyg', a tool for creating customized collections
of Cygwin(TM) packages. pmcyg is intended to support construction of
a self-contained CD or DVD that can be used to install or upgrade Cygwin
on machines that do not have network access to a Cygwin mirror site.

pmcyg avoids having to download the entirety of a Cygwin release
(about 4GB or more), and can create a minimal Cygwin installation within 20MB.
In general, pmcyg will take a user-supplied list of cygwin package names,
work out which other packages they depend on, and only download those packages
from a user-selected Cygwin mirror site.  It will then assemble a set of
configuration files that allows the Cygwin installer to operate from
the locally created repository.


Licensing
=========

All files forming part of pmcyg are released under
the GNU General Public License (v3) (see http://www.gnu.org/licenses)
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
automatically if you execute 'make install'. Running pmcyg without any
command-line options will automatically start the GUI if the 'Tkinter'
package is available.


Usage
=====

pmcyg can be used either as an interactive graphical application,
or via a command-line interface suitable for use in scripts or batch processes.

In both cases, you may want to create a text file containing a list of names
of Cygwin packages that you would like to have available. An official list
of packages is provided at http://cygwin.com/packages, or you can use pmcyg
to generate a template text-file that you can manually edit. In order to use
this facility, you need to point pmcyg at a Cygwin mirror site. In the GUI
this is done by using the 'Mirror list' button on the main panel to select
a mirror from a menu. The command-line option '--mirror' requires an
explicit URL of a Cygwin mirror site. Thereafter, within the GUI,
the 'File' menu contains an option 'Make template' for generating
a prototype package listing. A command-line version might resemble:

    pmcyg --nogui --mirror http://NearbyMirrorLocation/pub/cygwin --generate-template mypackages.txt

This, and the equivalent GUI operation, will generate a text-file
with every available Cygwin package listed, but commented-out with
a '#' symbol at the start of each line. Removing the '#' at the start
of any package's entry will prompt pmcyg to download that package when
processing your file. If you simply want to download all the available
Cygwin packages, you do not need to create this file, but can instead use
the 'Include all packages' option within the GUI 'Build' menu or the
'--all' command-line option.

To build your local Cygwin mirror within the GUI, you will need to select
your package-listing file using the 'Browse button' immediately below the
'Package list' field. Thereafter, the 'Build' menu contains the 'Start' option
to initiate downloading. When used from the command-line, you might try
something like:

    pmcyg --nogui --mirror http://NearbyMirroLocation/pub/cygwin mypackages.txt


Other options that may be useful are the 'dry-run' option, which can be used
to check your package list, and estimate how much space it would require
to download all the selected packages. If you want to download to a directory
other than the default location you can choose a different area for the
local cache with the command-line option '--directory'.

Further information about the available command-line options can be found
by running:

    pmcyg --help


A list of Cygwin mirror sites is available at http://cygwin.com/mirrors.html
You should try to use a mirror site close to your geographical location
to avoid overloading the primary Cygwin distribution site. The GUI will
automatically try to download the latest list of mirrors to construct
the 'Mirror list' menu, which may take a few seconds when the GUI first starts.


Please note
===========
    "Cygwin" is a trademark of Red Hat Inc.
    There is no official connection between pmcyg and the 'Cygwin' product
    pmcyg is currently in 'beta' testing
    pmcyg is supplied with NO WARRANTY and NO CLAIMS OF FITNESS FOR ANY PURPOSE.

# vim: set ts=4 sw=4 et:
