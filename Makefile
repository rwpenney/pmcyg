# Makefile for packaging 'pmcyg'
# RW Penney, April 2009

PREFIX = /usr/local
PKGNAME = pmcyg
PYTHON = python
VERSION = $(shell ${PYTHON} -c 'import pmcyg; print pmcyg.PMCYG_VERSION')
DISTFILES = pmcyg.py example.pkgs \
	Authors.txt ChangeLog.txt LICENSE.txt \
	Makefile README.txt ToDo.txt MANIFEST.in setup.py update \
	test/testPMCyg.py test/setup-awkward.ini $(shell ls test/tree-*)
PY3EXE = pmcyg-2to3.py

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
	sed '1s,python\(2[.0-9]*\)\?\>,python3,' pmcyg.py > ${FQNAME}/${PY3EXE}
	chmod +x ${FQNAME}/${PY3EXE}
	(cd ${FQNAME}; 2to3 -w -n ${PY3EXE} > /dev/null || rm ${PY3EXE})

test:
	test -d test && ( cd test; ${PYTHON} -t testPMCyg.py )

clean:
	rm -f ${FQNAME}.tgz ${FQNAME}.zip
