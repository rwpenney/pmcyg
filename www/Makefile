# Makefile for pmcyg web-pages
# RW Penney, July 2010

HTMLPAGES =	index.html
IMAGES =	pmcyg-tkgui.png pmcyg-win32.png pmcyg-update.png
PMCYG =		../pmcyg.py
TPLTFILE =	pmcyg-template.txt

DATESTR =	$(shell date +"%d %B %Y")


all:	${HTMLPAGES}

upload:	${HTMLPAGES} ${TPLTFILE}
	chmod 644 ${HTMLPAGES} ${IMAGES} ${TPLTFILE}
	scp -p ${HTMLPAGES} ${IMAGES} ${TPLTFILE} \
		rwpenney,pmcyg@frs.sourceforge.net:htdocs/

index.html:	index.html.in .makefileUUID
	sed -e "s%@DATE@%${DATESTR}%" \
	    -e "s%@MAKEFILE_UUID@%`cat .makefileUUID`%" $< > $@

${TPLTFILE}:
	${PMCYG} --nogui --mirror http://ftp.heanet.ie/pub/cygwin/ \
		--generate-template $@

.makefileUUID:	Makefile
	sha256sum Makefile | sed -n 's%^\([0-9a-fA-F]*\).*$$%\1%p' > $@

.PHONY:
clean:
	rm -f index.html ${TPLTFILE} .makefileUUID

# SHA1-IDs:
# 0.3.1 - 6a3045eb52395fcb18e2f769016b6af252e76104
