#!/usr/bin/env python3
"""Genera los iconos PWA (PNG) de Likida AI Enterprise sin dependencias externas.

Escribe icon-192.png, icon-512.png y maskable-512.png en landing/icons/.
Usa solo stdlib (zlib + struct) para empaquetar un PNG válido.
"""
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "landing", "icons")

# "B" como bitmap 7x8 (1 = trazo) para estampar encima del gradiente.
B_BITMAP = [
    "1111100",
    "1000010",
    "1000010",
    "1111100",
    "1000010",
    "1000010",
    "1111100",
    "0000000",
]
B_ROWS = len(B_BITMAP)
B_COLS = len(B_BITMAP[0])


def lerp(a, b, t):
    return int(a + (b - a) * t)


def make_png(size, maskable=False):
    """Devuelve bytes PNG de un icono cuadrado con gradiente y 'B' central."""
    # Tamaño del glifo: ~45% del lado (cabrá dentro del safe zone si maskable).
    glyph = int(size * 0.42)
    cell = glyph / max(B_ROWS, B_COLS)
    off = (size - glyph) / 2

    rows = []
    for y in range(size):
        row = bytearray([0])  # filtro: None
        for x in range(size):
            # Gradiente diagonal azul -> violeta (coincide con --grad del CSS).
            t = (x + y) / (2 * (size - 1))
            r = lerp(0x4F, 0x7C, t)
            g = lerp(0x8C, 0x5C, t)
            b = lerp(0xFF, 0xFF, t)

            # Borde redondeado (radio ~22%).
            rad = size * 0.22
            cx = size / 2
            cy = size / 2
            edge = max(abs(x - cx) - (cx - rad), 0) ** 2 + \
                   max(abs(y - cy) - (cy - rad), 0) ** 2
            if edge > rad * rad:
                # Fuera del rounded-rect: transparente.
                row += bytes([0, 0, 0, 0])
                continue

            # Estampa la "B" en blanco con leve transparencia.
            bx = (x - off) / cell
            by = (y - off) / cell
            gi = int(by)
            if 0 <= gi < B_ROWS:
                ci = int(bx)
                if 0 <= ci < B_COLS and B_BITMAP[gi][ci] == "1":
                    row += bytes([255, 255, 255, 255])
                    continue

            row += bytes([r, g, b, 255])
        rows.append(bytes(row))

    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    return png


def main():
    os.makedirs(OUT, exist_ok=True)
    targets = {
        "icon-192.png": make_png(192),
        "icon-512.png": make_png(512),
        "maskable-512.png": make_png(512, maskable=True),
    }
    for name, data in targets.items():
        path = os.path.join(OUT, name)
        with open(path, "wb") as f:
            f.write(data)
        print(f"escribi {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
