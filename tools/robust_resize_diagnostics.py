#!/usr/bin/env python3
"""Inspect Robust DWT bit errors after image resizing, without modifying the codec.

Read existing pilot-sweep PNG outputs. For each, downscale then upsample to the
true original size (the same operation used by decode_at_size). Compare raw
repeated QIM parity, majority-voted packet bits, and header/codeword bytes with
the exact expected RS8 packet. This separates search failure from data damage.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
import pywt

from src import robust_image as robust
from src.robust_packet import HEADER_BYTES, MAX_CODEWORD, pack, unpack


def bit_errors(image: Image.Image, packet: bytes) -> dict[str, int]:
    """Measure errors in the known-size QIM reader, before RS correction."""
    ll = pywt.wavedec2(
        robust._ycc(image)[:, :, 0], "haar", level=2, mode="periodization"
    )[0].ravel()
    expected_bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
    count = len(expected_bits) * robust.REPEAT
    if count > ll.size:
        raise ValueError("Packet exceeds image LL2 capacity")
    positions = np.random.default_rng(robust.SEED).permutation(ll.size)[:count]
    parity = np.rint(ll[positions] / robust.DELTA).astype(np.int64) & 1
    repeated_expected = np.repeat(expected_bits, robust.REPEAT)
    votes = parity.reshape(-1, robust.REPEAT).sum(axis=1)
    recovered_bits = (votes > robust.REPEAT // 2).astype(np.uint8)
    recovered_packet = np.packbits(recovered_bits).tobytes()

    return {
        "repeated_qim_errors": int(np.count_nonzero(parity != repeated_expected)),
        "majority_bit_errors": int(np.count_nonzero(recovered_bits != expected_bits)),
        "header_bit_errors": int(np.count_nonzero(
            recovered_bits[:HEADER_BYTES * 8] != expected_bits[:HEADER_BYTES * 8]
        )),
        "header_byte_errors": sum(
            x != y for x, y in zip(recovered_packet[:HEADER_BYTES], packet[:HEADER_BYTES])
        ),
        "codeword_byte_errors": sum(
            x != y for x, y in zip(recovered_packet[HEADER_BYTES:], packet[HEADER_BYTES:])
        ),
        "near_tie_votes": int(np.count_nonzero(
            (votes == robust.REPEAT // 2) | (votes == robust.REPEAT // 2 + 1)
        )),
    }


def probe_one_bit_length_repair(
    image: Image.Image, original_size: tuple[int, int], expected: bytes
) -> str:
    """Diagnostic only: flip one decoded length bit, then verify RS8 and CRC32.

    This does not change the production decoder or the CLR1 wire format.
    The original size must be supplied by the caller (oracle), so a PASS
    does not demonstrate blind scale synchronization.
    """
    if image.size != original_size:
        image = image.resize(original_size, Image.Resampling.LANCZOS)
    ll = pywt.wavedec2(
        robust._ycc(image)[:, :, 0], "haar", level=2, mode="periodization"
    )[0].ravel()
    positions = np.random.default_rng(robust.SEED).permutation(ll.size)
    header = robust._read_from_ll(ll, HEADER_BYTES, positions)
    if header[:4] != b"CLR1":
        return "NOT_APPLICABLE:magic_corrupt"
    observed_length = int.from_bytes(header[4:6], "big")
    for bit in range(16):
        corrected_length = observed_length ^ (1 << bit)
        count = (HEADER_BYTES + corrected_length) * 8 * robust.REPEAT
        if not 12 <= corrected_length <= MAX_CODEWORD or count > ll.size:
            continue
        raw = robust._read_from_ll(
            ll, HEADER_BYTES + corrected_length, positions
        )
        repaired = b"CLR1" + corrected_length.to_bytes(2, "big") + raw[HEADER_BYTES:]
        try:
            recovered = unpack(repaired)
        except ValueError:
            continue
        if recovered == expected:
            return f"PASS:len={corrected_length},bit={bit}"
        return "FAIL:unexpected_valid_payload"
    return "FAIL:no_valid_one_bit_repair"


def inspect_file(path: Path, packet: bytes, scale: float) -> dict:
    with Image.open(path) as opened:
        original = opened.convert("RGB")
    scaled_size = tuple(max(32, round(d * scale)) for d in original.size)
    down = original.resize(scaled_size, Image.Resampling.LANCZOS)
    restored = down.resize(original.size, Image.Resampling.LANCZOS)
    before = bit_errors(original, packet)
    after = bit_errors(restored, packet)
    try:
        decoded = robust.decode_at_size(down, original.size)
        oracle = "PASS" if decoded == packet_payload(packet) else "FAIL:payload_mismatch"
    except ValueError as exc:
        oracle = "FAIL:" + str(exc)
    repair = (
        "NOT_NEEDED" if oracle == "PASS"
        else probe_one_bit_length_repair(down, original.size, packet_payload(packet))
    )
    return {
        "file": path.name,
        "original_size": f"{original.width}x{original.height}",
        "scaled_size": f"{down.width}x{down.height}",
        "oracle": oracle,
        "one_bit_length_repair_probe": repair,
        **{"before_" + key: value for key, value in before.items()},
        **{"after_" + key: value for key, value in after.items()},
    }


def packet_payload(packet: bytes) -> bytes:
    """Recover the expected payload from the pristine known packet."""
    from src.robust_packet import unpack
    return unpack(packet)


def encoded_strength_files(directory: Path) -> list[Path]:
    """Exclude 12x-amplified difference maps; they carry no encoded packet."""
    return sorted(
        path for path in directory.glob("s*-strength-*.png")
        if not path.name.endswith("-vs-zero-diff.png")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory with s*-strength-*.png")
    parser.add_argument("--scale", type=float, default=0.75)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--message", default="CryptoLeaf v0.4 fixed-packet pilot sweep")
    args = parser.parse_args()
    if not np.isfinite(args.scale) or not 0.2 <= args.scale <= 2.0:
        parser.error("--scale must be between 0.2 and 2.0")
    if args.csv and args.csv.exists():
        parser.error("CSV already exists; refusing overwrite: " + str(args.csv))
    files = encoded_strength_files(args.directory)
    if not files:
        parser.error("No encoded strength PNG files in " + str(args.directory))
    packet = pack(args.message.encode("utf-8"))
    rows = [inspect_file(path, packet, args.scale) for path in files]
    for row in rows:
        print(
            f"{row['file']} oracle={row['oracle']} "
            f"length_repair={row['one_bit_length_repair_probe']} "
            f"QIM errors={row['after_repeated_qim_errors']} "
            f"majority bit errors={row['after_majority_bit_errors']} "
            f"header bit errors={row['after_header_bit_errors']} "
            f"RS codeword byte errors={row['after_codeword_byte_errors']} "
            f"near-tie votes={row['after_near_tie_votes']}",
            flush=True,
        )
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print("CSV:", args.csv)
    print("RS8 can correct at most four erroneous codeword bytes, provided the header is intact.")
    print("One-bit length repair is an oracle-size diagnostic, NOT a production decoder change.")


if __name__ == "__main__":
    main()
