import binascii

from whatsledger.pay.emvco import crc16, payload, tlv
from whatsledger.pay.rails import PLAIN, PayRails
from whatsledger.pay.rails_sg import PayNow

GOLDEN = (
    "00020101021226380009SG.PAYNOW010100211+6581234567030105204000053037025405"
    "10.005802SG5902NA6009Singapore62220118WhatsLedger K7Q2AB6304"
)


# the standard check value for crc16 ccitt false
def test_crc_check_value():
    assert crc16("123456789") == "29B1"


# the checksum matches the one python ships, so it is not checked against itself
def test_crc_matches_stdlib():
    assert crc16(GOLDEN) == f"{binascii.crc_hqx(GOLDEN.encode(), 0xFFFF):04X}"


# tag, two digit length, value
def test_tlv():
    assert tlv("59", "NA") == "5902NA"
    assert payload([("00", "01")]).startswith("0002016304")


# golden paynow payload for 10 dollars to a mobile, fixed amount, bill code as reference
def test_paynow_payload():
    code = PayNow().code("81234567", 1000, "WhatsLedger K7Q2AB")
    assert code == GOLDEN + crc16(GOLDEN)


# paynow needs sgd and a singapore mobile, the qr is a png
def test_paynow_offer():
    rail = PayNow()
    offer = rail.offer("6581234567", 1000, "SGD", "WhatsLedger K7Q2AB")
    assert offer is not None and offer.qr is not None and offer.qr.startswith(b"\x89PNG")
    assert "8123 4567" in offer.text and offer.label == "PayNow to 8123 4567"
    assert rail.offer("6581234567", 1000, "USD", "x") is None
    assert rail.offer("447700900123", 1000, "SGD", "x") is None


# with no pack the core still says how to settle
def test_plain_fallback():
    assert PayRails().offer("6581234567", 1000, "SGD", "x").text == PLAIN
    assert PayRails((PayNow(),)).offer("6581234567", 1000, "EUR", "x").text == PLAIN


# whatsapp drops 1 bit pngs, so the qr is 8 bit rgb with a white border and a dark corner square
def test_qr_is_rgb_png():
    import struct
    import zlib

    from whatsledger.pay.rails_sg import qr_png

    png = qr_png("hello", scale=2, border=1)
    side, _, depth, color = struct.unpack(">IIBB", png[16:26])
    assert (depth, color) == (8, 2)
    start = png.index(b"IDAT") + 4
    raw = zlib.decompress(png[start:png.index(b"IEND") - 8])
    stride = 1 + side * 3
    assert len(raw) == side * stride
    assert raw[1:4] == b"\xff\xff\xff"
    # first dark module of the finder square, after the border
    assert raw[2 * stride + 1 + 6 : 2 * stride + 1 + 9] == b"\x00\x00\x00"
