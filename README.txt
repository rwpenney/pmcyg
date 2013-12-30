        pmcyg - A tool for partially mirroring Cygwin(TM) packages
                        RW Penney, December 2013


Introduction
============

This directory contains 'pmcyg', a tool for creating customized collections
of Cygwin(TM) packages. pmcyg is intended to support construction of
a self-contained CDROM or DVD that can be used to install or upgrade Cygwin
on computers that do not have network access to a Cygwin mirror site.

pmcyg avoids having to download the entirety of a Cygwin release
(about 5GB or more), and can create a minimal Cygwin installation within 25MB.
In general, pmcyg will take a user-supplied list of cygwin package names,
work out which other packages they depend on, and only download those packages
from a user-selected Cygwin mirror site.  It will then assemble a set of
configuration files that allows the Cygwin installer to operate from
the locally created repository.

For updated versions of the pmcyg package, please see
http://www.sourceforge.net/projects/pmcyg


Licensing
=========

All files forming part of pmcyg are released under
the GNU General Public License (v3) (see http://www.gnu.org/licenses)
and are Copyright 2009-2014 RW Penney <rwpenney@users.sourceforge.net>.


Installation
============

To run pmcyg, you will need to have a recent version of 'Python' installed
(preferably version 2.5-2.7). This should be available by default on most
GNU/Linux systems, or can be obtained from http://www.python.org

In order to use pmcyg as a graphical (GUI) application, you will need
the 'Tkinter' toolkit for Python. This is part of the default distribution of
Python for Windows platforms, but may be part of a separate package
(possibly called "python-tk") on Unix/Linux systems.

On Windows platforms, double-clicking on the file 'pmcyg.py' should be
sufficient to run pmcyg in graphical mode.

On Unix/Linux systems, you may prefer to rename 'pmcyg.py'
to '/usr/local/bin/pmcyg'. The accompanying Makefile will do this
automatically if you execute 'make install'. Running pmcyg without any
command-line options will automatically start the GUI if the 'Tkinter'
package is available.

If you want to use pmcyg with the 3.x series of Python, you can use the
'pmcyg-2to3.py' executable in place of 'pmcyg.py', or use the standard
'2to3' conversion program available with recent versions of Python.


Usage
=====

pmcyg can be used either as an interactive graphical application,
or via a command-line interface suitable for use in scripts or batch processes.

  Graphical mode
  --------------
The GUI consists of three main sections:
  * Editable fields for specifying the locations of Cygwin sources, etc. (Top)
  * Buttons for controlling the download process (Top right edge)
  * A status window for monitoring the status of the downloads (Bottom).

In the top section of the window, you can optionally select a file containing
a list of Cygwin packages that you want to download, and there is a pull-down
menu of Cygwin mirror sites from which you can select a site that is
geographically close to you. The list of mirror sites is automatically
populated by querying the master Cygwin site, so may take a few seconds
to become fully populated after pmcyg is started.

The three buttons on the top-right edge of the GUI have the following functions:
  * The top button affects how pmcyg treats outdated versions of Cygwin packages
    when updating a previous set of downloads. You can toggle between:
    keeping both old & new versions; being asked whether to delete old versions;
    or having old versions automatically deleted.
  * The middle button allows you to select all available Cygwin packages
    for download (globe icon), or just the subset of packages specified
    in your custom package list (sector icon).
  * The bottom button is used to start the download, or to cancel downloading.

The pull-down menus on the top of the GUI allow additional customization
of the download process (e.g. including package sources), and to generate
a template list of available Cygwin packages that you can customize
to contain only the packages you require.

  Command-line mode
  -----------------
When running in command-line mode (using the '-c' or ''--nogui' options),
pmcyg will use default values for a Cygwin mirror site, and a minimal
list of packages to download. A full list of options can be obtained via

   pmcyg --help

A list of Cygwin mirror sites is available at http://cygwin.com/mirrors.html
You should try to use a mirror site close to your geographical location,
using the '-m' or '--mirror' option, to avoid overloading the primary
Cygwin distribution site.

If you simply want to download all the available Cygwin packages,
you can run with the '-a' or '--all' options. Alternatively, you can
supply one or more files containing lists of packages you would like
to download, e.g.

    pmcyg --nogui --mirror http://NearbyMirroLocation/pub/cygwin mypackages.txt

To create a package-list file, you may want to start with a template
generated by the '-g' or '--generate-template' option.

Other options that may be useful are the '--dry-run' option, which can be used
to check your package list, and estimate how much space it would require
to download all the selected packages. If you want to download to a directory
other than the default location you can choose a different area for the
local cache with the command-line option '--directory'.


  General
  -------
In both GUI and command-line modes, you can create a text file
containing a list of names of Cygwin packages that you would like to
have available. An official list of packages is provided at
http://cygwin.com/packages, or you can use pmcyg to generate a template
text-file that you can manually edit. In order to use this facility,
you need to point pmcyg at a Cygwin mirror site. In the GUI
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
processing your file.



Updating package sets
=====================

After initially downloading a set of Cygwin packages using pmcyg, it is often
useful to be able to perform updates without having to download all packages.
pmcyg will automatically check whether the current version of each
user-selected package is present, and only download files from the mirror site
if they are not up to date.

It is also possible to arrange for pmcyg to delete old versions of packages
that are no longer needed. By default, pmcyg will simply leave older packages
in the local mirror directory tree. This is expected to have little adverse
effect apart from consuming unnecessary storage space.

By using the '--remove-outdated' command-line option (or the corresponding
button near the top-right of the GUI), you can arrange for superseded
versions of packages to be deleted.
Setting this flag to 'yes' will remove all files in the local mirror that
are not needed for the current package list. It is safer to set the flag to
'ask', which will display a list of files that are to be deleted, and ask for
confirmation before deletion.

To reduce the risk of setting 'remove-outdated' to 'yes' and deleting valuable
files that have mistakenly been placed in the local mirror directory,
pmcyg uses some very simple tests to try to identify when automatic deletion
would be dangerous. In these circumstances it will behave as though the user
had selected the 'ask' setting. Naturally, these tests offer no guarantees
that important files will not be deleted, so setting 'remove-outdated' to 'yes'
is to be used with caution.


Cloning and existing Cygwin installation
========================================

If you have an existing Cygwin setup that you would like to reproduce,
pmcyg can construct a package list that can be used to create an off-line
installer for the same set of packages. When pmcyg is run from within
your Cygwin environment, you can use the '--generate-replica' command-line
option or the 'Make replica' within the 'File' menu on the GUI.

Note, that this facility will only create a set of Cygwin packages necessary
to create a similar installation. The actual packages downloaded may be
different (probably later) versions, and any customization of configuration
files will need to be performed manually.

If you get an error message of the form "unable to remap" when using this
facility, you may need to run Cygwin's "rebaseall" utility.


Please note
===========
    "Cygwin" is a trademark of Red Hat Inc.
    There is no official connection between pmcyg and the 'Cygwin' product
    pmcyg is supplied with NO WARRANTY and NO CLAIMS OF FITNESS FOR ANY PURPOSE.

# vim: set ts=4 sw=4 et:
