# Makefile for packaging 'pmcyg'
# RW Penney, April 2009

PKGNAME = pmcyg
VERSION = 0.0.2
DISTFILES = pmcyg.py example.pkgs \
	LICENSE README.txt ToDo.txt

FQNAME = ${PKGNAME}-${VERSION}


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
	cp -p ${DISTFILES} ${FQNAME}/

.PHONY:
clean:
	rm -f ${FQNAME}.tgz ${FQNAME}.zip
