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

${TPLTFILE}:	Makefile
	${PMCYG} --nogui --mirror http://mirrors.kernel.org/sourceware/cygwin/ \
		--generate-template $@

.makefileUUID:	Makefile
	sha256sum Makefile | sed -n 's%^\([0-9a-fA-F]*\).*$$%\1%p' > $@

.PHONY:	clean
clean:
	rm -f index.html ${TPLTFILE} .makefileUUID

# SHA1-IDs:
# 0.6	- 09fba3019dfde84bf98365e12f64ddb635863e02
# 0.7	- dc380fb2a3364dd40d0acb7a657af44ca36c230a
# 0.8	- ab23a7327b5cc66a3de21ee21bed333aab8130cf
