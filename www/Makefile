#    Makefile for pmcyg web-pages
#    RW Penney, July 2010

DATESTR=	$(shell date +"%d %B %Y")
HTMLPAGES=	index.html
IMAGES=		pmcyg-tkgui.png pmcyg-win32.png
PMCYG=		../pmcyg.py
TPLTFILE=	pmcyg-template.txt

all:	${HTMLPAGES}

upload:	${HTMLPAGES} ${TPLTFILE}
	chmod 644 ${HTMLPAGES} ${IMAGES}
	scp -p ${HTMLPAGES} ${IMAGES} ${TPLTFILE} \
		rwpenney,pmcyg@frs.sourceforge.net:htdocs/

index.html:	index.html.in
	sed -e "s%@DATE@%${DATESTR}%" $< > $@

${TPLTFILE}:
	${PMCYG} --nogui --mirror http://ftp.heanet.ie/pub/cygwin/ --generate-template $@
	chmod 644 $@

${HTMLPAGES}:	Makefile

.PHONY:
clean:
	rm -f index.html ${TPLTFILE}
