# MAME software-list board evidence

`softlist.json` is extracted from MAME's [`hash/sms.xml` and `hash/gamegear.xml`](https://github.com/mamedev/mame/tree/master/hash)
software lists, which are CC0-1.0 (each file says so), by `tools/sms_softlist.py`. It keeps only what identifies a
dump and describes its board: the SHA-1 of each single-ROM cartridge or card, its list, MAME's `slot` board
(empty for the default Sega-compatible device), and the `pin_42` Master System mode and `battery` features.
Titles, descriptions and publishers are left out. `list_sha256` records the exact list files it was made from.

decomp.wtf shows a match under **Inspect mapper evidence** (rom/sms_mapper_db.py). A match is catalog evidence for
a known dump; it never declares the cartridge model, and absence from the lists says nothing about a board.
