# Makefile for packaging 'pmcyg'
# RW Penney, April 2009

PREFIX = /usr/local
PKGNAME = pmcyg
PYTHON = python
VERSION = $(shell ${PYTHON} -c 'import pmcyg; print pmcyg.PMCYG_VERSION')
DISTFILES = pmcyg.py example.pkgs \
	Authors.txt ChangeLog.txt LICENSE.txt \
	Makefile README.txt ToDo.txt MANIFEST.in setup.py \
	test/testPMCyg.py $(shell ls test/tree-*)
PY3EXE = pmcyg-2to3.py

FQNAME = ${PKGNAME}-${VERSION}

.PHONY:	install
install:	pmcyg.py
	install -m 755 pmcyg.py ${PREFIX}/bin/pmcyg

.PHONY:
dist-gzip:	dist-dir
	tar -zcf ${FQNAME}.tgz ./${FQNAME}
	rm -rf ${FQNAME}

.PHONY:
dist-zip:	dist-dir
	zip -r ${FQNAME}.zip ./${FQNAME}
	rm -rf ${FQNAME}

.PHONY:
dist-dir:
	test -d ${FQNAME} || mkdir ${FQNAME}
	tar -cf - ${DISTFILES} | tar -C ${FQNAME}/ -xpf -
	sed '1s,python\(2[.0-9]*\)\?\>,python3,' pmcyg.py > ${FQNAME}/${PY3EXE}
	chmod +x ${FQNAME}/${PY3EXE}
	(cd ${FQNAME}; 2to3 -w -n ${PY3EXE} > /dev/null || rm ${PY3EXE})

.PHONY:	test
test:
	test -d test && ( cd test; ${PYTHON} -t testPMCyg.py )

.PHONY:
clean:
	rm -f ${FQNAME}.tgz ${FQNAME}.zip
