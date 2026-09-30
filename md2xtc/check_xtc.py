# -*- coding: utf-8 -*-
"""
Reads an .xtc / .xtch back and says whether it is sound.

    python3 check_xtc.py book.xtc
    python3 check_xtc.py book.xtc --png out/     # look at every page

It checks the marks, the offsets, the page index and every image header,
and it can turn the pages back into PNG so you can see what the reader
will show without walking over to the reader.
"""

import os
import struct
import sys

MARKS = {0x00435458: "XTC", 0x48435458: "XTCH"}
IMG_MARKS = {0x00475458: "XTG", 0x00485458: "XTH"}
XTH_LUT = (3, 1, 2, 0)                 # level -> code, as written


def _u(fmt, buf, off):
    return struct.unpack_from(fmt, buf, off)


def read(path):
    d = open(path, "rb").read()
    if len(d) < 48:
        raise ValueError("파일이 너무 짧습니다")
    mark, ver, count = _u("<IHH", d, 0)
    if mark not in MARKS:
        raise ValueError("XTC 표시가 아닙니다: %08x" % mark)
    rd, has_meta, has_thumb, has_chap = _u("<BBBB", d, 8)
    cur, = _u("<I", d, 0x0C)
    meta_off, index_off, data_off, thumb_off = _u("<QQQQ", d, 0x10)
    info = {
        "path": path, "size": len(d), "kind": MARKS[mark], "version": ver,
        "pages": count, "read_direction": rd, "has_metadata": has_meta,
        "current": cur, "metadata_offset": meta_off,
        "index_offset": index_off, "data_offset": data_off,
        "thumb_offset": thumb_off, "title": "", "author": "", "language": "",
        "layout": "spec" if has_meta else "compat", "problems": [],
    }
    bad = info["problems"]

    if has_meta and meta_off:
        def s(off, size):
            return d[off:off + size].split(b"\0")[0].decode("utf-8", "replace")
        info["title"] = s(meta_off, 128)
        info["author"] = s(meta_off + 128, 64)
        info["language"] = s(meta_off + 0xE0, 16)

    if index_off + 16 * count > len(d):
        bad.append("쪽 목록이 파일 밖을 가리킵니다")
        return info, d, []

    entries = []
    for i in range(count):
        off, size, w, h = _u("<QIHH", d, index_off + 16 * i)
        entries.append((off, size, w, h))
        if off + size > len(d):
            bad.append("%d번째 쪽이 파일 밖입니다" % (i + 1))
            continue
        imark, iw, ih, cmode, comp, dsize = _u("<IHHBBI", d, off)
        name = IMG_MARKS.get(imark)
        if name is None:
            bad.append("%d번째 쪽 그림 표시가 이상합니다" % (i + 1))
            continue
        if (iw, ih) != (w, h):
            bad.append("%d번째 쪽 크기가 목록과 다릅니다" % (i + 1))
        want = ((w + 7) // 8) * h if name == "XTG" else \
            ((h + 7) // 8) * w * 2
        if dsize != want:
            bad.append("%d번째 쪽 자료 크기가 %d이어야 하는데 %d입니다"
                       % (i + 1, want, dsize))
        if 22 + dsize != size:
            bad.append("%d번째 쪽 길이가 목록과 안 맞습니다" % (i + 1))
        if name == "XTH" and info["kind"] != "XTCH":
            bad.append("%d번째 쪽이 XTH인데 파일은 XTC입니다" % (i + 1))
        if comp:
            bad.append("%d번째 쪽에 눌림(compression)이 있습니다" % (i + 1))
        del cmode
    if entries and entries[0][0] != data_off:
        bad.append("첫 쪽 위치가 dataOffset과 다릅니다")
    return info, d, entries


def page_image(d, entry):
    """One page back into a PIL picture."""
    import numpy as np
    from PIL import Image
    off, _size, w, h = entry
    imark, iw, ih, _cm, _comp, dsize = _u("<IHHBBI", d, off)
    body = d[off + 22:off + 22 + dsize]
    if IMG_MARKS.get(imark) == "XTG":
        rb = (iw + 7) // 8
        a = np.unpackbits(np.frombuffer(body, dtype=np.uint8).reshape(ih, rb),
                          axis=1)[:, :iw]
        return Image.fromarray((a * 255).astype("uint8"), "L")
    cb = (ih + 7) // 8
    half = cb * iw
    hi = np.unpackbits(np.frombuffer(body[:half], dtype=np.uint8)
                       .reshape(iw, cb), axis=1)[:, :ih]
    lo = np.unpackbits(np.frombuffer(body[half:half * 2], dtype=np.uint8)
                       .reshape(iw, cb), axis=1)[:, :ih]
    code = (hi << 1) | lo                       # row = column, right to left
    inv = np.zeros(4, dtype=np.uint8)
    for level, c in enumerate(XTH_LUT):
        inv[c] = level
    lv = inv[code].T[:, ::-1]
    return Image.fromarray((lv * 85).astype("uint8"), "L")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    png = None
    if "--png" in argv:
        i = argv.index("--png")
        png = argv[i + 1] if i + 1 < len(argv) else "pages"
        args = [a for a in args if a != png]
    if not args:
        print(__doc__)
        return 1

    rc = 0
    for path in args:
        try:
            info, d, entries = read(path)
        except Exception as e:
            print("[실패] %s: %s" % (path, e))
            rc = 1
            continue
        print("%s" % os.path.basename(path))
        print("  형식 %s v%d / %d쪽 / %.2f MB / 머리말 %s"
              % (info["kind"], info["version"], info["pages"],
                 info["size"] / 1048576.0, info["layout"]))
        if entries:
            print("  화면 %dx%d / 쪽 하나 %d바이트"
                  % (entries[0][2], entries[0][3], entries[0][1]))
        if info["title"] or info["author"]:
            print("  제목 %s / 글쓴이 %s" % (info["title"], info["author"]))
        if info["problems"]:
            rc = 1
            for p in info["problems"][:20]:
                print("  [!] %s" % p)
        else:
            print("  이상 없습니다.")
        if png and entries:
            if not os.path.isdir(png):
                os.makedirs(png)
            for i, e in enumerate(entries):
                page_image(d, e).save(os.path.join(png, "page%04d.png"
                                                  % (i + 1)))
            print("  PNG %d장 -> %s" % (len(entries), png))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
