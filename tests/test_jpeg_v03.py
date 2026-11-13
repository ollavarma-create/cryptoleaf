
import pytest

from src.jpeg_v03 import (
    HEADER_SIZE,
    MAGIC,
    VERSION,
    RS_NSYM,
    build_header,
    parse_header,
)


def test_header_roundtrip():
    header = build_header(4096)

    assert len(header) == HEADER_SIZE
    assert header[:4] == MAGIC
    assert header[8] == VERSION
    assert header[9] == RS_NSYM
    assert parse_header(header) == 4096


def test_invalid_magic():
    header = bytearray(build_header(4096))
    header[:4] = b"STGB"

    with pytest.raises(ValueError):
        parse_header(bytes(header))


def test_invalid_length():
    with pytest.raises(ValueError):
        build_header(-1)


def test_invalid_rs_configuration():
    header = bytearray(build_header(4096))
    header[9] = 32

    with pytest.raises(ValueError):
        parse_header(bytes(header))


from src.jpeg_v03 import encode_payload, decode_payload


def test_rs_payload_roundtrip():
    original = bytes(range(256)) * 12
    encoded = encode_payload(original)

    assert len(encoded) > len(original)
    assert decode_payload(encoded) == original


def test_rs_corrects_five_corrupted_bytes():
    original = bytes(range(256)) * 12
    encoded = bytearray(encode_payload(original))

    # Corrupt five bytes in the first RS codeword.
    for pos in (10, 25, 60, 100, 180):
        encoded[pos] ^= 0x55

    assert decode_payload(bytes(encoded)) == original


def test_rs_rejects_excessive_corruption():
    from reedsolo import ReedSolomonError

    original = bytes(range(256)) * 12
    encoded = bytearray(encode_payload(original))

    # 40 corrupted bytes in one codeword exceed RS(255,191).
    for pos in range(40):
        encoded[pos] ^= 0x55

    with pytest.raises(ReedSolomonError):
        decode_payload(bytes(encoded))



from src.jpeg_v03 import prepare_payload, recover_payload


def test_complete_payload_pipeline():
    original = b"Cryptoleaf JPEG v0.3 test message" * 50

    encoded = prepare_payload(original, "qwerty")
    header = build_header(len(encoded))

    assert parse_header(header) == len(encoded)
    assert recover_payload(encoded, "qwerty") == original


def test_pipeline_recovers_corrupted_payload():
    original = b"Cryptoleaf error correction test" * 50

    encoded = bytearray(prepare_payload(original, "qwerty"))

    # Five corrupted RS symbols in the first codeword.
    for pos in (10, 25, 60, 100, 180):
        encoded[pos] ^= 0x55

    assert recover_payload(bytes(encoded), "qwerty") == original


def test_pipeline_rejects_wrong_password():
    encoded = prepare_payload(b"Confidential message", "correct")

    with pytest.raises(ValueError, match="Authentication failed"):
        recover_payload(encoded, "wrong")


def test_header_crc_detects_corruption():
    header = bytearray(build_header(4096))
    header[5] ^= 0x01

    with pytest.raises(ValueError, match="CRC mismatch"):
        parse_header(bytes(header))


def test_header_crc_detects_checksum_corruption():
    header = bytearray(build_header(4096))
    header[10] ^= 0x01

    with pytest.raises(ValueError, match="CRC mismatch"):
        parse_header(bytes(header))


from src.jpeg_v03 import (
    encoded_payload_size,
    required_blocks,
    available_blocks,
    message_fits,
    max_message_size,
)


def test_empty_message_size():
    # 44 AES-GCM bytes + 64 RS parity bytes
    assert encoded_payload_size(0) == 108
    assert required_blocks(0) == (32 + 108) * 42


def test_rs_block_boundary():
    # 191 bytes fit in one RS data block.
    assert encoded_payload_size(147) == 255
    assert encoded_payload_size(148) == 320


def test_skipped_first_block_row():
    assert available_blocks(80, 80) == 90
    assert available_blocks(80, 8) == 0


def test_capacity_boundary():
    width, height = 1024, 1024
    maximum = max_message_size(width, height)

    assert maximum > 0
    assert message_fits(width, height, maximum)
    assert not message_fits(width, height, maximum + 1)


def test_too_small_image():
    assert max_message_size(64, 64) == 0
    assert not message_fits(64, 64, 0)


def test_short_header_rejected():
    with pytest.raises(ValueError, match="header size"):
        parse_header(b"STGC")
