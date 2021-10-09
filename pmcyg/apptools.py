"""
pmcyg application-level utilities
"""

import os, os.path, re
from .core import GarbageConfirmer, PackageSet, PMbuilder


def getDefaultCacheDir() -> str:
    """Attempt to find safe location for local cache of Cygwin downloads"""
    re_syspath = re.compile(r'^ ( /usr | [a-z]:\\windows\\system )',
                            re.VERBOSE | re.IGNORECASE)

    topdir = os.getcwd()

    if re_syspath.match(topdir):
        topdir = os.path.expanduser('~')

    return os.path.join(topdir, 'cygwin')


def ProcessPackageFiles(builder: PMbuilder, pkgfiles: list) -> None:
    """Execute downloading and cleaning actions for a set of package-list files"""

    pkgset = PackageSet(pkgfiles)

    builder.BuildMirror(pkgset)
    garbage = builder.GetGarbage()
    confirmer = \
        GarbageConfirmer(garbage, default=builder.GetOption('RemoveOutdated'))
    confirmer.ActionResponse()

    isofile = builder.GetOption('ISOfilename')
    if isofile:
        builder.BuildISO(isofile)
