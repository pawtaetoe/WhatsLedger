import re
import struct
import zlib

import segno

from whatsledger.pay.emvco import payload, tlv
from whatsledger.pay.rails import PayOffer

# a singapore mobile on whatsapp, 65 then 8 or 9 and seven digits
MOBILE = re.compile(r"65([89]\d{7})")


# a qr as an 8 bit rgb png, whatsapp drops the 1 bit pngs segno writes
def qr_png(text: str, scale: int = 8, border: int = 4) -> bytes:
    matrix = segno.make_qr(text, error="m").matrix
    size = len(matrix) + 2 * border
    blank = [1] * size
    rows = [blank] * border + [
        [1] * border + [0 if dark else 1 for dark in row] + [1] * border for row in matrix
    ] + [blank] * border
    raw = b"".join(
        b"\x00" + b"".join((b"\xff" if cell else b"\x00") * 3 * scale for cell in row)
        for row in rows for _ in range(scale)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    side = size * scale
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


# paynow to the payer's own mobile, one sgqr that paylah and singapore bank apps scan
class PayNow:
    # the qr payload for a fixed amount the friend cannot edit
    def code(self, mobile: str, cents: int, reference: str) -> str:
        account = (
            tlv("00", "SG.PAYNOW") + tlv("01", "0") + tlv("02", f"+65{mobile}") + tlv("03", "0")
        )
        return payload([
            ("00", "01"), ("01", "12"), ("26", account), ("52", "0000"), ("53", "702"),
            ("54", f"{cents // 100}.{cents % 100:02d}"), ("58", "SG"), ("59", "NA"),
            ("60", "Singapore"), ("62", tlv("01", reference[:25]))
        ])

    # number to type and a qr to scan, only for sgd and singapore mobiles
    def offer(self, payee: str, cents: int, currency: str, reference: str) -> PayOffer | None:
        found = MOBILE.fullmatch(payee.removeprefix("+"))
        if currency != "SGD" or found is None:
            return None
        mobile = found.group(1)
        text = (
            f"*PayNow* to {mobile[:4]} {mobile[4:]}, reference {reference}\n"
            "Or save the QR above and scan it from your gallery in your bank app."
        )
        image = qr_png(self.code(mobile, cents, reference))
        return PayOffer(text, image, f"PayNow to {mobile[:4]} {mobile[4:]}")
