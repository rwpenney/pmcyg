# Makefile for pmcyg GUI imagery
# RW Penney, October 2012

SOURCES =	download.svg cancel.svg allpkgs.svg userpkgs.svg \
		replace_never.svg replace_ask.svg replace_kill.svg
IMAGES =	$(SOURCES:%.svg=%.gif)
ENCODED =	$(IMAGES:%.gif=%.enc64)

%.gif:	%.svg
	convert -transparent "#c0c0c0" -transparent-color "#c0c0c0" $< $@

%.enc64:	%.gif
	base64 $< > $@

all:	${IMAGES} ${ENCODED}

patch:	${ENCODED} Makefile
	rm -f $@
	for img in ${ENCODED}; do \
		base=`echo $$img | sed 's/\.enc64//'`; \
		echo "    $$base = \"\"\"" >> $@; \
		cat $$img >> $@; \
		echo "\"\"\"\n" >> $@; \
	done

.PHONY:	clean
clean:
	rm -f ${IMAGES} ${ENCODED} patch
