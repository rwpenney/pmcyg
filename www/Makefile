# Makefile for pmcyg web-pages
# RW Penney, July 2010

HTMLPAGES =	index.html
IMAGES =	pmcyg-tkgui.png pmcyg-win32.png
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
# 0.3 - 144fd10a05e5037d749c2f491097c8beb2ba4de9
