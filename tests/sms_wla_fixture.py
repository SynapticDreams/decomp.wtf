"""Authored nonuniform WLA geometry; no commercial input or source."""
from decompnet.rom.wla_layout import identity


def bank_zero_layout(image, *, role='code'):
    """Explicit authored 16 KiB source banks with only bank zero's CPU view declared."""
    return {'version': 1, 'input': identity(image),
            'banks': [{'id': n, 'offset': n * 0x4000, 'size': min(0x4000, len(image) - n * 0x4000)}
                      for n in range((len(image) + 0x3FFF) // 0x4000)],
            'slots': [{'id': 0, 'start': 0, 'size': 0x4000, 'space': 'rom'}],
            'views': [{'bank': 0, 'slot': 0, 'offset': 0, 'size': min(0x4000, len(image)), 'role': role}]}


def layout_for(image):
    def view(bank, slot, offset, size, role):
        return dict(bank=bank, slot=slot, offset=offset, size=size, role=role)
    return {'version': 1, 'input': identity(image),
            'banks': [{'id': 0, 'offset': 0, 'size': 0x2000},
                      {'id': 1, 'offset': 0x2000, 'size': 0x6000},
                      {'id': 2, 'offset': 0x8000, 'size': 0x4000}],
            'slots': [{'id': 0, 'start': 0, 'size': 0x2000, 'space': 'rom'},
                      {'id': 1, 'start': 0x2000, 'size': 0x6000, 'space': 'rom'},
                      {'id': 2, 'start': 0x8000, 'size': 0x4000, 'space': 'rom'},
                      {'id': 3, 'start': 0xC000, 'size': 0x2000, 'space': 'ram'},
                      {'id': 4, 'start': 0, 'size': 0x4000, 'space': 'rom'}],
            'views': [view(0, 0, 0, 0x2000, 'code'), view(1, 1, 0, 0x200, 'code'),
                      view(1, 1, 0x200, 0x100, 'data'), view(1, 1, 0x300, 0x200, 'unknown'),
                      view(1, 1, 0x4000, 0x200, 'code'), view(2, 2, 0, 0x200, 'code'),
                      view(2, 4, 0, 0x1200, 'code'), view(0, 3, 0, 0x2000, 'unknown')]}


SOURCE = '''
.EMPTYFILL $FF
.MEMORYMAP
 DEFAULTSLOT 0
 SLOT 0 START $0000 SIZE $2000
 SLOT 1 START $2000 SIZE $6000
 SLOT 2 START $8000 SIZE $4000
 SLOT 3 START $C000 SIZE $2000
 SLOT 4 START $0000 SIZE $4000
.ENDME
.ROMBANKMAP
 BANKSTOTAL 3
 BANKSIZE $2000
 BANKS 1
 BANKSIZE $6000
 BANKS 1
 BANKSIZE $4000
 BANKS 1
.ENDRO
.BANK 0 SLOT 0
.ORGA $0000
Reset: jr Reset
.ORGA $1100
MainAt1100: ld a,4
 ret
.BANK 1 SLOT 1
.ORGA $2100
First:
FirstAlias: ld a,1
 ret
.ORGA $2200
DataRecord: .db $3e,$07,$c9
.ORGA $2300
_LABEL_2300_: ld a,5
 ret
.ORGA $2400
UnknownRecord: ld a,6
 ret
.ORGA $6100
Second: ld a,2
 ret
.BANK 2 SLOT 2
.ORGA $8100
Third: ld a,3
 ret
.BANK 2 SLOT 4
.ORGA $1000
Paged: ld a,7
 ret
.ORGA $1100
OtherAt1100: ld a,8
 ret
.RAMSECTION "Vars" BANK 0 SLOT 3
wState db
.ENDS
'''
