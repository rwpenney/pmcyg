"""
pmcyg utilities
"""

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

__all__ = [ 'core', 'version' ]

from .core import DEFAULT_INSTALLER_URL, GarbageConfirmer, \
                  HOST_IS_CYGWIN, PackageSet, PMbuilder
from .version import PMCYG_VERSION


def ProcessPackageFiles(builder, pkgfiles):
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
