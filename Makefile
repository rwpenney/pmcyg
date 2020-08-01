# Makefile for packaging 'pmcyg'
# RW Penney, April 2009

PREFIX = /usr/local
PKGNAME = pmcyg
PYTHON = python3
VERSION = $(shell ${PYTHON} -c 'import pmcyg; print(pmcyg.PMCYG_VERSION)')
DISTFILES = pmcyg.py example.pkgs \
	Authors.txt ChangeLog.txt LICENSE.txt \
	Makefile README.txt ToDo.txt MANIFEST.in setup.py update \
	test/testPMCyg.py test/setup-awkward.ini $(shell ls test/tree-*)

FQNAME = ${PKGNAME}-${VERSION}

.PHONY:	install dist-gzip dist-zip dist-dir test clean

install:	pmcyg.py
	install -m 755 pmcyg.py ${PREFIX}/bin/pmcyg

dist-gzip:	dist-dir
	tar -zcf ${FQNAME}.tgz ./${FQNAME}
	rm -rf ${FQNAME}

dist-zip:	dist-dir
	zip -r ${FQNAME}.zip ./${FQNAME}
	rm -rf ${FQNAME}

dist-dir:
	test -d ${FQNAME} || mkdir ${FQNAME}
	tar -cf - ${DISTFILES} | tar -C ${FQNAME}/ -xpf -

test:
	test -d test && ( cd test; ${PYTHON} -t testPMCyg.py )

clean:
	rm -f ${FQNAME}.tgz ${FQNAME}.zip
