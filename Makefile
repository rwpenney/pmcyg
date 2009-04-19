# Makefile for packaging 'pmcyg'
# RW Penney, April 2009

PKGNAME = pmcyg
VERSION = 0.0.1
DISTFILES = pmcyg example.pkgs \
	LICENSE README.txt

.PHONY:
dist-gzip:
	mkdir ${PKGNAME}-${VERSION} || true
	cp -p ${DISTFILES} ${PKGNAME}-${VERSION}/
	tar -zcf ${PKGNAME}-${VERSION}.tgz ./${PKGNAME}-${VERSION}
	rm -rf ${PKGNAME}-${VERSION}
