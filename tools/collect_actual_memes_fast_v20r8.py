#!/usr/bin/env python3
import collect_actual_memes_v20r8 as c

# Fast, guaranteed-first pass: verified direct meme files, actual Niconico thumbnails,
# Wikimedia actual AA/media, and official video thumbnails. No generated cards.
c.discover_kym = lambda: []
c.MAX_ASSETS = 120
c.main()
