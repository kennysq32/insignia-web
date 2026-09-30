# -*- coding: utf-8 -*-
"""
XTC / XTG / XTH writer for Xteink readers.

Format follows the public specification:
  https://github.com/bigbag/epub-to-xtc-converter/blob/main/docs/xtc-format-spec.md

Layout of an XTC file:
    [header]
    [metadata 256 bytes]   (only in the "spec" layout)
    [page index: 16 bytes per page]
    [page data: XTG or XTH images, back to back]

Two container layouts are written:

  "compat"  what real files off the device look like: a 48 byte header,
            no metadata block, currentPage 0, image md5 filled with 0xFF.
            This is the default, because it is the layout that is known
            to open on the reader.

  "spec"    56 byte header plus a 256 byte metadata block holding title,
            author and language. Readers that honour indexOffset read it
            fine, and it is what the epub converter above writes.

This module needs no image library. It takes plain pixel buffers.
numpy is used when available (much faster), otherwise pure Python.
"""

import struct
import time

try:
    import numpy as _np
except Exception:
    _np = None

MARK_XTG = 0x00475458   # "XTG\0"
MARK_XTH = 0x00485458   # "XTH\0"
MARK_XTC = 0x00435458   # "XTC\0"
MARK_XTCH = 0x48435458  # "XTCH"

HEADER_SIZE_COMPAT = 48
HEADER_SIZE_SPEC = 56
METADATA_SIZE = 256
INDEX_ENTRY_SIZE = 16
IMAGE_HEADER_SIZE = 22

# Brightness step 0..3 (0 = black, 3 = white) -> code the display wants.
# The Xteink LUT swaps the two middle levels.
#   code 0 = white, 1 = dark grey, 2 = light grey, 3 = black
XTH_LUT = (3, 1, 2, 0)


def _image_header(mark, width, height, data_size, md5_fill=b"\xff"):
    h = bytearray()
    h += struct.pack("<I", mark)        # 0x00 mark
    h += struct.pack("<H", width)       # 0x04 width
    h += struct.pack("<H", height)      # 0x06 height
    h += struct.pack("<B", 0)           # 0x08 colorMode  (0 = monochrome)
    h += struct.pack("<B", 0)           # 0x09 compression (0 = none)
    h += struct.pack("<I", data_size)   # 0x0A dataSize
    h += md5_fill * 8                   # 0x0E md5 (not used, filled)
    assert len(h) == IMAGE_HEADER_SIZE
    return bytes(h)


# ----------------------------------------------------------------------
# XTG : 1 bit per pixel, row major, MSB = leftmost pixel, bit 1 = white
# ----------------------------------------------------------------------

def encode_xtg(bits, width, height, md5_fill=b"\xff"):
    """bits: sequence of width*height values, 0 = black, 1 = white."""
    row_bytes = (width + 7) // 8

    if _np is not None:
        a = _np.asarray(bits, dtype=_np.uint8).reshape(height, width)
        data = _np.packbits(a, axis=1).tobytes()
    else:
        out = bytearray(row_bytes * height)
        for y in range(height):
            base = y * width
            rbase = y * row_bytes
            for x in range(width):
                if bits[base + x]:
                    out[rbase + (x >> 3)] |= 1 << (7 - (x & 7))
        data = bytes(out)

    return _image_header(MARK_XTG, width, height, len(data), md5_fill) + data


# ----------------------------------------------------------------------
# XTH : 2 bits per pixel in two planes.
#   Columns run right to left. Inside a column, 8 pixels top to bottom
#   go into one byte, MSB = topmost pixel.
#   First plane holds the high bit, second plane the low bit.
# ----------------------------------------------------------------------

def encode_xth(levels, width, height, md5_fill=b"\xff"):
    """levels: sequence of width*height values 0..3, 0 = black, 3 = white."""
    col_bytes = (height + 7) // 8

    if _np is not None:
        a = _np.asarray(levels, dtype=_np.uint8).reshape(height, width)
        code = _np.asarray(XTH_LUT, dtype=_np.uint8)[a]
        cols = code[:, ::-1].T                      # row c = column (width-1-c)
        hi = _np.packbits((cols >> 1) & 1, axis=1).tobytes()
        lo = _np.packbits(cols & 1, axis=1).tobytes()
    else:
        plane_hi = bytearray(col_bytes * width)
        plane_lo = bytearray(col_bytes * width)
        for c in range(width):
            x = width - 1 - c
            cbase = c * col_bytes
            for y in range(height):
                code = XTH_LUT[levels[y * width + x]]
                if code == 0:
                    continue
                idx = cbase + (y >> 3)
                bit = 1 << (7 - (y & 7))
                if code & 2:
                    plane_hi[idx] |= bit
                if code & 1:
                    plane_lo[idx] |= bit
        hi = bytes(plane_hi)
        lo = bytes(plane_lo)

    data = hi + lo
    return _image_header(MARK_XTH, width, height, len(data), md5_fill) + data


# ----------------------------------------------------------------------
# XTC container
# ----------------------------------------------------------------------

def build_container(pages, width, height, title="", author="",
                    language="ko-KR", high_quality=False,
                    read_direction=0, cover_page=0, layout="compat"):
    """pages: list of encoded XTG (or XTH) images. Returns the XTC bytes."""
    if not pages:
        raise ValueError("페이지가 없습니다")
    if len(pages) > 65535:
        raise ValueError("페이지가 65535개를 넘습니다")

    spec = (layout == "spec")
    mark = MARK_XTCH if high_quality else MARK_XTC
    page_count = len(pages)

    header_size = HEADER_SIZE_SPEC if spec else HEADER_SIZE_COMPAT
    metadata_offset = header_size if spec else 0
    index_offset = header_size + (METADATA_SIZE if spec else 0)
    data_offset = index_offset + INDEX_ENTRY_SIZE * page_count

    out = bytearray()

    # --- header ---
    out += struct.pack("<I", mark)              # 0x00 mark
    out += struct.pack("<H", 1)                 # 0x04 version
    out += struct.pack("<H", page_count)        # 0x06 pageCount
    out += struct.pack("<B", read_direction)    # 0x08 readDirection
    out += struct.pack("<B", 1 if spec else 0)  # 0x09 hasMetadata
    out += struct.pack("<B", 0)                 # 0x0A hasThumbnails
    out += struct.pack("<B", 0)                 # 0x0B hasChapters
    out += struct.pack("<I", 1 if spec else 0)  # 0x0C currentPage
    out += struct.pack("<Q", metadata_offset)   # 0x10 metadataOffset
    out += struct.pack("<Q", index_offset)      # 0x18 indexOffset
    out += struct.pack("<Q", data_offset)       # 0x20 dataOffset
    out += struct.pack("<Q", 0)                 # 0x28 thumbOffset
    if spec:
        out += struct.pack("<Q", 0)             # 0x30 chapterOffset
    assert len(out) == header_size

    # --- metadata, 256 bytes ---
    if spec:
        def fixed(s, size):
            b = s.encode("utf-8")[:size - 1]
            return b + b"\x00" * (size - len(b))

        meta = bytearray()
        meta += fixed(title, 128)                       # 0x00 title
        meta += fixed(author, 64)                       # 0x80 author
        meta += fixed("", 32)                           # 0xC0 publisher
        meta += fixed(language, 16)                     # 0xE0 language
        meta += struct.pack("<I", int(time.time()))     # 0xF0 createTime
        meta += struct.pack("<H", cover_page)           # 0xF4 coverPage
        meta += struct.pack("<H", 0)                    # 0xF6 chapterCount
        meta += b"\x00" * 8                             # 0xF8 reserved
        assert len(meta) == METADATA_SIZE
        out += meta

    # --- page index, 16 bytes per page ---
    pos = data_offset
    for p in pages:
        out += struct.pack("<Q", pos)          # 0x00 offset
        out += struct.pack("<I", len(p))       # 0x08 size
        out += struct.pack("<H", width)        # 0x0C width
        out += struct.pack("<H", height)       # 0x0E height
        pos += len(p)

    # --- page data ---
    for p in pages:
        out += p

    return bytes(out)
