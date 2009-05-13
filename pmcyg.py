#!/usr/bin/python
# Partially mirror 'cygwin' distribution
# (C)Copyright 2009, RW Penney

#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bz2, md5, optparse, os, os.path, re, time, urllib, urlparse
try: set
except NameError: from sets import Set as set, ImmutableSet as frozenset
try: import Tkinter as Tk; hasgui = True
except: hasgui = False


# Directory into which to assemble local mirror:
TGT_DIR = '.'
# URL of source of Cygwin installation program 'setup.exe':
EXESRC = 'http://sourceware.redhat.com/cygwin/setup.exe'
# URL of Cygwin mirror site, hosting available packages:
MIRROR = 'ftp://cygwin.com/pub/cygwin/'
# URL of Cygwin package database file (derived from MIRROR if 'None'):
INIURL = None
# Set of package age descriptors:
EPOCHS = ['curr']


class PMCygException(Exception):
    """Wrapper for internally generated exceptions"""

    def __init__(self, *args):
        Exception.__init__(self, *args)


def CheckMirrorIni(mirror, iniurl):
    """Basic sanity checks on mirror URL and location or 'setup.ini' file"""

    if not mirror.endswith('/'):
        mirror += '/'

    if not iniurl:
        iniurl = urlparse.urljoin(mirror, 'setup.ini')

    return mirror, iniurl


def mergelines(pkgtxt):
    """Combine list of lines describing single package"""

    if not pkgtxt:
        return ""

    while pkgtxt and pkgtxt[-1].isspace():
        pkgtxt.pop()

    return "".join(pkgtxt)


def prettyfsize(size):
    """Pretty-print file size, autoscaling units"""
    divisors = [ ( 1<<30, 'GB' ), ( 1<<20, 'MB' ), ( 1<<10, 'kB' ), ( 1, 'B' ) ]

    for div, unit in divisors:
        qsize = float(size) / div
        if qsize > 0.8:
            return '%.2g%s' % ( qsize, unit )

    return '%dB' % ( size )


def ParseIniFile(iniurl):
    """Ingest original 'setup.ini' file defining available cygwin packages"""

    re_setup = re.compile(r'^(setup-\S+):\s+(\S+)$')
    re_comment = re.compile(r'#(.*)$')
    re_package = re.compile(r'^@\s+(\S+)$')
    re_epoch = re.compile(r'^\[([a-z]+)\]$')
    re_field = re.compile(r'^([a-z]+):\s+(.*)$')
    re_blank = re.compile(r'^\s*$')
    all_regexps = [ re_setup, re_comment, re_blank,
                    re_package, re_epoch, re_field ]

    header = {}
    packages = {}

    try:
        fp = urllib.urlopen(iniurl)
    except Exception, ex:
        raise PMCygException, "Failed to open %s\n - %s" % ( iniurl, str(ex) )

    lineno = 0
    (pkgname, pkgtxt, pkgdict, epoch) = (None, [], {}, None)
    (fieldname, fieldlines) = (None, None)
    inquote = False
    for line in fp:
        lineno += 1

        if inquote and fieldname:
            trline = line.rstrip()
            if trline.endswith('"'):
                fieldlines.append(trline[0:-1])
                pkgdict[fieldname] = '\n'.join(fieldlines)
                fieldname = None
                inquote = False
            else:
                fieldlines.append(line)
        else:
            # Classify current line as package definition/field etc:
            matches = None
            for regexp in all_regexps:
                matches = regexp.match(line)
                if matches: break
            if not matches:
                raise SyntaxError, "Unrecognized content on line %d" % ( lineno )

            if regexp == re_setup:
                header[matches.group(1)] = matches.group(2)
            elif regexp == re_comment:
                pass
            elif regexp == re_package:
                if pkgname:
                    pkgdict['TEXT'] = mergelines(pkgtxt)
                    packages[pkgname] = pkgdict
                    pkgname = None
                pkgname = matches.group(1)
                pkgtxt = []
                pkgdict = {}
                epoch = 'curr'
                fieldname = None
            elif regexp == re_epoch:
                epoch = matches.group(1)
            elif regexp == re_field:
                fieldname = matches.group(1) + '_' + epoch
                fieldtext = matches.group(2)
                if fieldtext.startswith('"'):
                    if fieldtext[1:].endswith('"'):
                        pkgdict[fieldname] = fieldtext[1:-1]
                    else:
                        fieldlines = [ line[1:] ]
                        inquote = True
                else:
                    pkgdict[fieldname] = fieldtext

        if pkgname:
            pkgtxt.append(line)
    fp.close()

    if pkgname:
        pkgdict['TEXT'] = mergelines(pkgtxt)
        packages[pkgname] = pkgdict

    return (header, packages)


def MakeCategories(pkgdict):
    """Construct lists of packages grouped into categories"""

    allpkgs = []
    catlists = {}

    for pkg, pkginfo in pkgdict.items():
        allpkgs.append(pkg)

        cats = pkginfo.get('category_curr', '').split()
        for ctg in cats:
            catlists.setdefault(ctg, []).append(pkg)

    catlists['All'] = allpkgs
    for cats in catlists.values():
        cats.sort()

    return catlists


def ResolveDependencies(pkgdict, usrpkgs=None, include_all=False):
    """Constuct list of packages, including all their dependencies"""

    if usrpkgs == None:
        # Setup minimalistic set of packages
        usrpkgs = ['bash', 'bzip2', 'coreutils', 'gzip', 'tar', 'unzip', 'zip' ]

    if include_all:
        usrpkgs = [ pkg for pkg in pkgdict.iterkeys()
                            if not pkg.startswith('_') ]

    additions = set(usrpkgs)
    packages = set()
    badpkgnames = []

    while additions:
        pkg = additions.pop()
        packages.add(pkg)

        try:
            pkginfo = pkgdict[pkg]
        except:
            badpkgnames.append(pkg)
            continue

        # Find dependencies of current package & add to stack:
        for epoch in EPOCHS:
            try:
                reqlist = pkginfo['requires' + '_' + epoch].split()
                for r in reqlist:
                    if not r in packages:
                        additions.add(r)
            except:
                print 'Cannot find epoch %s for %s' % (epoch, pkg)

    if badpkgnames:
        badpkgnames.sort()
        raise PMCygException, \
            "The following package names where not recognized:\n\t%s\n" \
            % ( '\n\t'.join(badpkgnames) )

    packages = list(packages)
    packages.sort()

    return packages


def BuildDownload(pkgdict, packages):
    """Convert list of packages into set of files to fetch from Cygwin server"""

    downloads = []
    totsize = 0

    for pkg in packages:
        pkginfo = pkgdict[pkg]

        for epoch in EPOCHS:
            try:
                flds = pkginfo['install' + '_' + epoch].split()
                pkgref = flds[0]
                pkgsize = int(flds[1])
                pkghash = flds[2]
                downloads.append((pkgref, pkgsize, pkghash))
                totsize += pkgsize
            except KeyError:
                print 'Cannot find package filename for %s in epoch %s' % (pkg, epoch)

    return downloads, totsize


def BuildSetupFiles(header, pkgdict, packages):
    """Create top-level configuration files in local mirror"""

    # Split package list into normal + specials:
    spkgs = [pkg for pkg in packages if pkg.startswith('_')]
    packages = [pkg for pkg in packages if not pkg.startswith('_')]
    packages.sort()
    spkgs.sort()
    packages.extend(spkgs)

    # Reconstruct setup.ini file:
    spath = os.path.join(TGT_DIR, 'setup.ini')
    fp = open(spath, 'w+t')
    fp.write('# This file is automatically generated by "pmcyg"\n'
            '# Manual edits will be overwritten\n')
    fp.write('setup-timestamp: %d\n' % (int(time.time())))
    fp.write('setup-version: %s\n' % (header['setup-version']))
    for pkg in packages:
        fp.write('\n')
        fp.write(pkgdict[pkg]['TEXT'])
    fp.seek(0)
    cpsr = bz2.BZ2File(os.path.join(TGT_DIR, 'setup.bz2'), mode='w')
    cpsr.write(fp.read())
    cpsr.close()
    fp.close()

    # Create other top-level artefacts:
    try:
        urllib.urlretrieve(EXESRC, os.path.join(TGT_DIR, 'setup.exe'))
    except Exception, ex:
        raise PMCygException, "Failed to retrieve %s\n - %s" % ( EXESRC, str(ex) )

    hp = open(os.path.join(TGT_DIR, 'md5.sum'), 'wt')
    for fl in ['setup.ini', 'setup.bz2', 'setup.exe']:
        hshr = md5.new()
        fp = open(os.path.join(TGT_DIR, fl), 'rb')
        hshr.update(fp.read())
        fp.close()
        hp.write('%s  %s\n' % ( hshr.hexdigest(), fl ))
    hp.close()


def HashCheck(tgtpath, pkghash):
    """Check md5 hash-code of downloaded package"""
    blksize = 1 << 14

    hasher = md5.new()

    try:
        fp = open(tgtpath, 'rb')
        while True:
            chunk = fp.read(blksize)
            if not chunk:
                break
            hasher.update(chunk)
    except:
        return False

    dlhash = hasher.hexdigest().lower()
    pkghash = pkghash.lower()

    return True


def BuildMirror(header, pkgdict, packages):
    """Download files from Cygwin mirror to create local partial copy"""

    if not os.path.isdir(TGT_DIR):
        os.makedirs(TGT_DIR)

    BuildSetupFiles(header, pkgdict, packages)

    (downloads, totsize) = BuildDownload(pkgdict, packages)
    print 'Download size: %s from %s' % ( prettyfsize(totsize), MIRROR)

    for (pkgfile, pkgsize, pkghash) in downloads:
        if os.path.isabs(pkgfile):
            raise SyntaxError, '%s is an absolute path' % ( pkgfile )
        tgtpath = os.path.join(TGT_DIR, pkgfile)
        tgtdir = os.path.dirname(tgtpath)
        if not os.path.isdir(tgtdir):
            os.makedirs(tgtdir)
        mirpath = urlparse.urljoin(MIRROR, pkgfile)
        if not os.path.isfile(tgtpath) or os.path.getsize(tgtpath) != pkgsize:
            print '  %s (%s)...' % ( os.path.basename(pkgfile),
                                    prettyfsize(pkgsize) ),
            dlsize = 0
            try:
                urllib.urlretrieve(mirpath, tgtpath)
                dlsize = os.path.getsize(tgtpath)
                if dlsize != pkgsize:
                    raise IOError, 'Mismatched package size (deficit=%s)' \
                                    % ( prettyfsize(pkgsize - dlsize) )
                if not HashCheck(tgtpath, pkghash):
                    raise IOError, 'Mismatched checksum'
                print ' done'
            except Exception, ex:
                print ' FAILED\n  -- %s' % ( str(ex) )



def ReadPackageLists(filenames):
    """Read a set of user-supplied package names for local mirroring"""

    usrpkgs = []

    for fn in filenames:
        fp = open(fn, 'rt')

        for line in fp:
            idx = line.find('#')
            if idx >= 0:
                line = line[0:idx]
            line = line.strip()

            if line:
                usrpkgs.append(line)

        fp.close()

    return usrpkgs


def main():
    global INIURL, EPOCHS, EXESRC, MIRROR, TGT_DIR

    # Process command-line options:
    parser = optparse.OptionParser()
    parser.add_option('--directory', '-d', type='string',
            default=os.path.join(os.getcwd(), 'cygwin'),
            help='where to build local mirror')
    parser.add_option('--dummy', '-z', action='store_true', default=False,
            help='avoid actually downloading packages')
    parser.add_option('--exeurl', '-x', type='string', default=EXESRC,
            help='URL of "setup.exe" Cygwin installer')
    parser.add_option('--iniurl', '-i', type='string', default=None,
            help='URL of "setup.ini" Cygwin database')
    parser.add_option('--mirror', '-m', type='string', default=MIRROR,
            help='URL of Cygwin archive or mirror site')
    parser.add_option('--epochs', '-e', type='string', default=','.join(EPOCHS),
            help='comma-separated list of epochs, e.g. "curr,prev"')
    parser.add_option('--all', '-a', action='store_true', default=False,
            help='include all available Cygwin packages')
    opts, remargs = parser.parse_args()

    TGT_DIR = opts.directory
    MIRROR, INIURL = CheckMirrorIni(opts.mirror, opts.iniurl)
    EPOCHS = opts.epochs.split(',')

    usrpkgs = None
    if remargs:
        usrpkgs = ReadPackageLists(remargs)

    try:
        (header, pkgdict) = ParseIniFile(INIURL)
        packages = ResolveDependencies(pkgdict, usrpkgs, include_all=opts.all)

        if opts.dummy:
            (downloads, totsize) = BuildDownload(pkgdict, packages)
            print 'Download size: %s from %s' \
                    % ( prettyfsize(totsize), MIRROR)
            print 'Packages: %s' % ( ', '.join(packages) )
        else:
            BuildMirror(header, pkgdict, packages)
    except Exception, ex:
        print 'Failed to build mirror\n - %s' % ( str(ex) )



if __name__ == "__main__":
    main()

# vim: set ts=4 sw=4 et:
