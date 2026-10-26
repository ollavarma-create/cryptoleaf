# Cryptomosaic — Preparatory Research Document

**Project:** Cryptomosaic — Distributed Steganographic Secret Sharing  
**Author:** Jari Hiltunen (hiltsu @ Codeberg)  
**Date:** 2026-03-14  
**Revision:** 7 (external security review: per-fragment CT randomization, AES-256, HMAC header, VSS)  
**Status:** Pre-development research  
**Relation:** Builds on Cryptoleaf (codeberg.org/hiltsu/cryptoleaf) DWT/spread-spectrum core


Decision: this project will not go forward.
Rationale: file splitting with Shamir's Secret Sharing is already well-served by existing open-source tools:

Rememory — age encryption + Shamir SSS, self-contained browser-based recovery bundles, time-lock support, designed for estate/testament use case (Go/JS, Apache 2.0, 2026)
horcrux — file splitting with Shamir threshold encryption (Go, MIT, 2020)
horcrux by Laharah — AES-256 + Shamir with block-level data distribution across fragments (Python, libsodium)
go-shamirsplit — Shamir key splitting + Reed-Solomon erasure coding + EC signatures, PEM-formatted shards (Go)
ssss — the original Unix Shamir secret sharing tool (C, GPL, 2006)

Steganographic embedding of individual fragments can be done separately with Cryptoleaf if needed.
The following iteration process is preserved as an example of why preparatory research matters — seven revisions of architecture and security analysis revealed that the core problem was already solved.

---

## 1. Concept Summary

Cryptomosaic is a standalone tool that combines **steganographic embedding** (inherited from Cryptoleaf) with **Shamir's Secret Sharing** and **media fragmentation** to enable distributed, trust-decentralized message hiding.

A secret message (UTF-8 text) is first embedded into a whole media file (image or audio) using DWT spread-spectrum steganography. The carrier is then **fragmented** into numbered pieces — like a mosaic or puzzle. Each fragment carries a **Shamir share** of the encryption key, a copy of the **AES-encrypted ciphertext**, and a **TCP-inspired header** for reassembly. Only when a sufficient number of fragments (meeting a configurable threshold k/n) are reunited can the hidden message be decrypted.

**Three encode modes:**
- **Standard mode** — `.cmf` fragment files with full stego media (default, most capable)
- **Lightweight mode** — `.cmf` fragment files without media tiles (Path B only, smaller files)
- **Wrapped mode** — each fragment embedded into an innocent-looking image/audio via Cryptoleaf (maximum forensic stealth)

**Key use cases:**
- Estate planning / testaments (cold storage on USB sticks, decades-long preservation)
- Shared custody of sensitive business documents
- Whistleblower scenarios requiring collective agreement
- Any situation where no single party should have unilateral access

**Design philosophy — the "time capsule" principle:**
- Zero external dependencies at decode time (no servers, no blockchain, no APIs)
- Fragment + Cryptomosaic application = sufficient for decoding
- All metadata needed for reassembly is self-contained in each fragment's header
- Every distribution set includes: fragments + SPECIFICATION.txt + AppImage + source archive

---

## 2. Architecture Overview

### 2.1 Dual Decode Paths

A critical architectural decision is the **dual decode path** design. The system supports two decoding modes depending on how many fragments are available:

**Path A — Full reconstruction (all n fragments available):**
Fragments are reassembled into the complete stego media, then DWT extraction recovers the message from the carrier. This is the "pure steganographic" path where the stego layer provides plausible deniability.

**Path B — Header-only decryption (≥ k fragments available, k ≤ n):**
Each fragment's header contains a copy of the AES-encrypted ciphertext (typically ≤ 4 KB). When ≥ k Shamir shares are combined, the encryption key is reconstructed and the ciphertext is decrypted directly — without needing media reassembly. This makes the (k,n) threshold genuinely functional from day one.

Path B is the **MVP decode path**. Path A adds the steganographic cover layer and will be enhanced with Reed-Solomon erasure coding in a future version, allowing media reconstruction from fewer than n fragments.

### 2.2 Encoding Pipeline

```
┌──────────────────────────────────────────────────────────┐
│                     ENCODING PIPELINE                     │
│                                                          │
│  Secret message                                          │
│       ↓                                                  │
│  AES-256-GCM encryption (random key K) → ciphertext C    │
│  (authenticated encryption: detects wrong key on decode)  │
│       ↓                                                  │
│  DWT spread-spectrum embedding of C into carrier media   │
│  (Cryptoleaf core: DWT + Reed-Solomon + adaptive α)      │
│       ↓                                                  │
│  Stego media (complete, with embedded ciphertext)        │
│       ↓                                                  │
│  Shamir's Secret Sharing: split K into n shares          │
│  (threshold k, where k ≤ n)                              │
│       ↓                                                  │
│  Media fragmentation (tile grid / time segments)         │
│  + Header injection per fragment (includes ciphertext C) │
│  + Per-fragment Reed-Solomon FEC (10% overhead)          │
│  + Merkle tree construction for integrity                │
│       ↓                                                  │
│  n fragment files (.cmf = CryptoMosaic Fragment)         │
│  Each contains: header + ciphertext + SSS share          │
│                 + media fragment + RS parity              │
└──────────────────────────────────────────────────────────┘
```

### 2.3 Decoding Pipeline

```
┌──────────────────────────────────────────────────────────┐
│                 DECODING PIPELINE (dual path)             │
│                                                          │
│  Collect ≥ k fragment files                              │
│       ↓                                                  │
│  Parse headers → validate session ID match               │
│       ↓                                                  │
│  Verify per-fragment integrity (RS FEC + SHA-256)        │
│       ↓                                                  │
│  Verify Merkle proofs across fragments                   │
│       ↓                                                  │
│  Reconstruct key K from ≥ k Shamir shares                │
│       ↓                                                  │
│  ┌─────────────────────┬───────────────────────────┐     │
│  │  PATH A (n of n)    │  PATH B (k of n)          │     │
│  │                     │                           │     │
│  │  Reassemble media   │  Extract ciphertext C     │     │
│  │  (TCP-style reorder)│  from any fragment header  │     │
│  │       ↓             │       ↓                   │     │
│  │  DWT extraction     │  AES-256-GCM decrypt      │     │
│  │       ↓             │  (auth tag verifies key)   │     │
│  │  AES-256-GCM decrypt│       ↓                   │     │
│  │       ↓             │  Original message         │     │
│  │  Original message   │                           │     │
│  └─────────────────────┴───────────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

**Critical design decision:** Steganographic embedding happens **before** fragmentation. DWT extraction happens **after** reassembly. This means the DWT domain is never disturbed by fragmentation — fragments carry raw pixel/sample data that reconstructs bit-perfectly.

### 2.4 Payload Philosophy: UTF-8 Text Only (MVP)

The secret payload is restricted to **UTF-8 text** in the MVP. This is a deliberate design choice rooted in the time capsule principle:

**Why text, not binary:**
- **Universality:** UTF-8 is self-describing and will remain readable as long as computers process text. No application dependency.
- **Compactness:** A 4K PNG carrier can reliably embed ~10–50 KB via spread-spectrum DWT. In UTF-8, this is 5,000–25,000 words — enough for a complete testament, contract, or sensitive document.
- **Format immortality:** Binary formats (Excel, PDF, DOCX) are ZIP archives of XML/binary blobs that require specific software to interpret. Excel may not exist in 50 years. UTF-8 will.
- **Robustness:** Smaller payloads mean stronger DWT embedding (lower alpha, less detectable) and greater tolerance for partial signal loss.

**What about binary payloads?** Optional binary mode may be added as a future enhancement with explicit warnings: (1) capacity is severely limited by carrier size, (2) the binary format may become unreadable over decades, (3) the user bears responsibility for format longevity. This is a conscious trade-off, not a missing feature.

**What about semantic encodings (word vectors, embeddings)?** Rejected. Vector representations are model-dependent — a Word2Vec or BERT embedding is useless without the exact same model and version. This violates the time capsule principle fundamentally. Plain text is always superior to any encoded representation for long-term storage.

### 2.5 Three Encode Modes

Cryptomosaic supports three encode modes, each optimizing for a different trade-off:

```
┌──────────────────────────────────────────────────────────────────┐
│                      THREE ENCODE MODES                          │
│                                                                  │
│  STANDARD MODE (default)                                         │
│  ┌──────────┐                                                    │
│  │ .cmf file │ = header + ciphertext + SSS share + media tile    │
│  └──────────┘                                                    │
│  Supports: Path A (full stego) + Path B (header-only decrypt)    │
│  Output: fragment_01_of_09.cmf                                   │
│  Size: large (media data included)                               │
│  Forensics: identifiable (.cmf magic bytes)                      │
│                                                                  │
│  LIGHTWEIGHT MODE                                                │
│  ┌──────────┐                                                    │
│  │ .cmf file │ = header + ciphertext + SSS share (no media tile) │
│  └──────────┘                                                    │
│  Supports: Path B only                                           │
│  Output: fragment_01_of_09.cmf                                   │
│  Size: tiny (~5 KB per fragment)                                 │
│  Forensics: identifiable (.cmf magic bytes)                      │
│                                                                  │
│  WRAPPED MODE (--wrapped)                                        │
│  ┌──────────────────────┐                                        │
│  │ voice_memo_03.wav     │ = audio with Cryptoleaf-embedded      │
│  │                       │   lightweight fragment inside          │
│  └──────────────────────┘                                        │
│  Supports: Path B only                                           │
│  Output: voice_memo_03.wav (indistinguishable from normal audio) │
│  Size: carrier audio size (~10–60 MB per fragment)               │
│  Forensics: appears as standard WAV/FLAC (or PNG if image used)  │
│  Requires: Cryptoleaf + carrier audio/image per fragment         │
│  Default: audio carrier (superior capacity + psychoacoustic      │
│           masking); image carrier also supported                  │
└──────────────────────────────────────────────────────────────────┘
```

**Wrapped mode pipeline:**
```
  Secret text → AES-256-GCM encrypt → ciphertext C
  Key K → Shamir split into n shares
  
  Carrier preparation (audio, default):
    User provides one long audio file (e.g. 1-hour voice recording)
    Cryptomosaic auto-segments it into n carrier segments
    Each segment: ~60/n minutes of unique audio
  
  For each share i (1..n):
    Build lightweight fragment: header + C + share_i  (~5 KB)
    Serialize fragment to bytes
    Embed fragment bytes into carrier_segment_i.wav via Cryptoleaf DWT
    Output: voice_memo_0i.wav
    
  Decode:
    For each received audio file:
      Extract embedded data via Cryptoleaf DWT
      Parse as lightweight .cmf fragment
    Collect ≥ k fragments → SSS reconstruct key → AES-GCM decrypt
```

**Why audio is the ideal wrapped mode carrier:**

| Property | Audio (WAV/FLAC) | Image (PNG) |
|----------|-----------------|-------------|
| Raw capacity (1 carrier) | ~635 MB (1h stereo WAV) | ~24 MB (4K PNG) |
| DWT embed capacity (1–5%) | 6–30 MB | 240 KB–1.2 MB |
| Fragment size (~5 KB) fits | ~1000× over | ~50–250× over |
| Embedding alpha needed | Extremely low → undetectable | Low → hard to detect |
| Psychoacoustic masking | Built into Cryptoleaf | N/A (visual masking weaker) |
| Natural cover story | Voice memos, recordings, meetings | Photos (also good) |
| Steganalysis resistance | Very high (speech has natural entropy) | High |
| Correlation risk | Low if each segment is different audio | Low if different images |

**Audio carrier auto-segmentation:** The user provides one long recording (recommended: ≥ 10 minutes per fragment, so ≥ n×10 minutes total). Cryptomosaic splits it into n non-overlapping segments, each becoming a carrier for one fragment. This solves the "n different carrier files" problem — the user records one conversation or voice memo, and the tool handles the rest.

**Important:** Each carrier segment must be **different audio content** — not copies of the same segment. Identical carriers would be a correlation signal (red-team attack 2). The auto-segmentation from a single long recording naturally ensures uniqueness.

**Image carriers remain supported** via `--carrier-type image --carrier-dir ./photos/`. This is useful when audio is impractical (e.g., text-only communication channels). Each image must be a different photograph for the same anti-correlation reason.

**Why wrapped mode works:** A lightweight fragment (~5 KB) in a 10-minute audio segment (~100 MB WAV) means the embedding uses approximately 0.005% of the carrier capacity. At this ratio, the DWT signal is so faint that even advanced CNN-based steganalysis classifiers cannot distinguish it from natural audio noise. This is orders of magnitude more covert than embedding in a photograph.

**Why wrapped mode is superior to the original stealth mode concept (v3):**

| Aspect | Stealth mode (v3) | Wrapped mode (v4) |
|--------|-------------------|-------------------|
| Approach | Make .cmf itself a valid PNG/WAV | Embed .cmf inside a PNG/WAV via Cryptoleaf |
| Complexity | Two stego layers in one file | Clean separation: Cryptomosaic + Cryptoleaf |
| Fragility | High — dual metadata embedding | Low — Cryptoleaf is battle-tested |
| Implementation | New steganographic code needed | Reuses existing Cryptoleaf as-is |
| Debugging | Hard — no visible headers | Easy — extract with Cryptoleaf, then parse .cmf |
| Integrity | No CRC protection for metadata | Full .cmf header CRC preserved inside carrier |

---

## 3. Fragment Binary Format (.cmf)

Inspired by IPv4 fragmentation headers and general binary file format best practices.

```
CryptoMosaic Fragment Format v1
================================

All multi-byte values: little-endian

HEADER (fixed, 208 bytes)
Offset  Size    Field                   Description
------  ----    -----                   -----------
+00     4B      Magic number            0x434D4F53 ("CMOS")
+04     1B      Format version          Currently 0x01
+05     1B      Media type              0x01=image, 0x02=audio
+06     1B      Compression flag        0x00=raw, 0x01=zlib
+07     1B      Encode mode             0x01=standard, 0x02=lightweight, 0x03=wrapped
+08     16B     Session ID              UUID v4 (unique per encode session)
+24     2B      Fragment index          This fragment's sequence number (0-based)
+26     2B      Total fragments (n)     Total number of fragments in session
+28     1B      Threshold (k)           Minimum fragments needed for key recovery
+29     1B      SSS share length        Length of embedded Shamir share (bytes)
+30     2B      Ciphertext length       Length of embedded (randomized) ciphertext (bytes)
+32     32B     Fragment hash           SHA-256 of this fragment's media data
+64     32B     Merkle root             Root hash of all fragment hashes
+96     32B     Previous fragment hash  H(fragment N-1), 0x00×32 for fragment 0
+128    8B      Timestamp               Unix timestamp (creation time, ±30 day tolerance)
+136    8B      Nonce                   Random nonce (replay protection)
+144    4B      Media data offset       Offset to start of media data
+148    4B      Media data length       Length of media data section (bytes)
+152    4B      Uncompressed length     Original size before compression (0 if raw)
+156    1B      Grid cols / audio flag  Image: number of tile columns; Audio: 0xFF
+157    1B      Grid rows               Image: number of tile rows; Audio: segment count
+158    2B      Reserved (grid)         0x0000 (future use)
+160    2B      Original width          Image: original image width in pixels
+162    2B      Original height         Image: original image height in pixels
+164    1B      Bit depth               Original media bit depth (8/16/24/32)
+165    1B      Channels                1=mono/grayscale, 2=stereo, 3=RGB, 4=RGBA
+166    1B      Original format         0x01=PNG, 0x02=WAV, 0x03=FLAC
+167    1B      RS FEC overhead %       Reed-Solomon overhead (default 10)
+168    32B     Assembly checksum       SHA-256 of complete reassembled media
+200    8B      Header HMAC             HMAC-SHA256 truncated to 8 bytes (key = session ID)
------  ----    -----                   -----------

PAYLOAD (variable)
+208    var     Ciphertext              Per-fragment randomized: Ci = C ⊕ ChaCha20(KDF(K,i))
+208+c  var     Shamir share data       SSS share for this fragment (2 × 16B for AES-256)
+208+c+s var    Media data              Raw (or zlib-compressed) pixel/sample data
+...    var     RS parity data          Reed-Solomon FEC parity bytes
```

**Design notes:**
- Magic number "CMOS" identifies files unambiguously (see Section 11.4 for wrapped mode alternative)
- Session ID links fragments belonging to the same encode operation
- Fragment hash + Merkle root enable per-fragment integrity verification
- Previous fragment hash adds chained (blockchain-like) sequential tamper detection
- Assembly checksum verifies the final reconstructed media before DWT extraction
- **Per-fragment ciphertext randomization:** Each fragment stores `Ci = C ⊕ ChaCha20(KDF(K, i))` — identical base ciphertext XORed with a fragment-specific deterministic stream. Eliminates cross-fragment correlation (mitigates Attack 2). On decode, de-randomize with the same KDF before AES-GCM decrypt.
- AES-256-GCM includes authentication tag — wrong key is detected per mode-dependent policy (Section 11.7)
- **Header HMAC** replaces CRC-32: HMAC-SHA256 truncated to 8 bytes, keyed with session ID. Provides cryptographic integrity for header fields — an attacker cannot modify timestamp/index/threshold without knowing the session ID. Still fast to verify but resistant to forgery unlike CRC-32.
- **Grid/segment field** explicitly typed: Image uses `cols (uint8) | rows (uint8) | reserved (uint16)`. Audio uses `0xFF | segment_count (uint8) | reserved (uint16)`. The `0xFF` marker distinguishes audio from image.
- Encode mode field records which of the three modes (standard/lightweight/wrapped) produced this fragment
- Nonce + timestamp prevent replay of fragments from old sessions
- Compression flag + uncompressed length support optional zlib compression
- Original format + bit depth + channels enable decode-time input validation warnings
- RS FEC parity appended to media data corrects NAND bit-rot over long-term storage
- **Shamir share for AES-256:** Two 16-byte halves split separately via PyCryptodome, stored sequentially (32 bytes total per share)

---

## 4. Integrity Verification: Merkle Tree + Chain (Blockchain-without-blockchain)

Each fragment's media data is hashed (SHA-256). These hashes form the leaves of a Merkle tree. The root hash is stored in every fragment's header.

```
                    Merkle Root
                   (in all headers)
                    /          \
               H(01+02)      H(03+04)
               /     \       /     \
           H(frag0) H(frag1) H(frag2) H(frag3)
```

**Verification at reassembly time:**
1. Each fragment's RS FEC is applied to correct any bit errors
2. Each fragment's media data is re-hashed
3. The hash is compared against the fragment's own `fragment_hash` field
4. The chain is verified: each fragment's `previous_fragment_hash` matches H(N-1)
5. The Merkle tree is reconstructed from all available fragment hashes
6. The computed root is compared against the `merkle_root` stored in headers
7. If any mismatch → clear error: "Fragment X is corrupted or tampered"

**Dual integrity model:**
- **Merkle tree** provides global integrity — detects any modification across all fragments simultaneously
- **Chained hashing** (previous fragment hash) provides sequential integrity — detects missing or reordered fragments in a linear scan without building the full tree

**Advantages over actual blockchain:**
- No external infrastructure required
- No validators, miners, or network connectivity
- Fully self-contained — works decades later from USB sticks
- No transaction fees or gas costs
- No privacy concerns from on-chain storage

---

## 5. Shamir's Secret Sharing — Library Decision

### Selected: PyCryptodome `Crypto.Protocol.SecretSharing.Shamir`

```python
from Crypto.Protocol.SecretSharing import Shamir
from Crypto.Random import get_random_bytes

# Generate a random 128-bit AES key
key = get_random_bytes(16)

# Split into 5 shares, threshold 3
shares = Shamir.split(k=3, n=5, secret=key)
# Returns: [(1, b'...16 bytes...'), (2, b'...'), ...]

# Reconstruct from any 3 shares
reconstructed_key = Shamir.combine(shares[:3])
assert reconstructed_key == key
```

**Rationale:**
- Part of PyCryptodome, already a dependency for AES encryption
- Well-tested, production-grade, actively maintained
- Clean API: `split(k, n, secret)` → list of (index, bytes) tuples
- Operates over GF(2^128), mathematically sound
- Compatible with `ssss` utility via `ssss=True` flag

**AES key size decision: AES-256-GCM (32 bytes) — default from MVP**

PyCryptodome's Shamir module handles 16-byte secrets natively. For AES-256 (32-byte key), the key is split into two 16-byte halves, each processed through Shamir independently. On reconstruction, the halves are combined via HKDF to produce the final 256-bit key:

```python
from Crypto.Protocol.SecretSharing import Shamir
from Crypto.Protocol.KDF import HKDF
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes

def split_aes256_key(key: bytes, k: int, n: int) -> list[tuple[int, bytes, bytes]]:
    """Split a 32-byte AES-256 key into n Shamir shares (threshold k)."""
    assert len(key) == 32
    shares_lo = Shamir.split(k, n, key[:16])  # first half
    shares_hi = Shamir.split(k, n, key[16:])  # second half
    return [(i, lo, hi) for (i, lo), (_, hi) in zip(shares_lo, shares_hi)]

def reconstruct_aes256_key(shares: list[tuple[int, bytes, bytes]]) -> bytes:
    """Reconstruct AES-256 key from ≥ k Shamir shares."""
    shares_lo = [(i, lo) for i, lo, hi in shares]
    shares_hi = [(i, hi) for i, lo, hi in shares]
    key_lo = Shamir.combine(shares_lo)
    key_hi = Shamir.combine(shares_hi)
    return key_lo + key_hi  # 32 bytes
```

**Rationale for AES-256 as MVP default:** Grover's algorithm halves the effective key length — AES-128 becomes 64-bit equivalent security on a quantum computer. For estate/testament use cases spanning 20–30+ years, this is insufficient. The two-half Shamir split adds minimal complexity (one extra `split`/`combine` call) while providing 128-bit post-quantum security. The performance cost is negligible.

**Share validation before combine:** Before calling `Shamir.combine()`, the decoder must validate:
- No duplicate share indices (reject: "Duplicate fragment index detected")
- All indices in range 1–n (reject: "Invalid share index")
- At least k shares present (reject: "Insufficient shares")
- UUID v4 version/variant bits valid on session ID (reject: "Malformed session ID")

AES-GCM's authentication tag provides final verification — if any share was corrupted or falsified, the reconstructed key is wrong and GCM auth fails. How this failure is reported depends on the encode mode (see Section 11.7).

### Evaluated alternatives

| Library | Pros | Cons | Decision |
|---------|------|------|----------|
| python-sslib | Arbitrary-length secrets, Base64/hex built-in | Less adopted, extra dependency | Not needed — two-half PyCryptodome split handles AES-256 |
| sssa-python | Simple API, MIT licensed | Unmaintained since 2015 | Rejected |
| Custom implementation | Zero dependencies | Security risk in DIY crypto | Rejected |

---

## 6. Merkle Tree — Implementation Decision

### Selected: Custom implementation (~50 lines, hashlib-based)

For Cryptomosaic's use case, the fragment count is small (typically 4–16 fragments). A full Merkle tree library is unnecessary overhead.

```python
import hashlib

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

def merkle_root(hashes: list[bytes]) -> bytes:
    """Compute Merkle root from a list of leaf hashes."""
    if len(hashes) == 0:
        return b'\x00' * 32
    if len(hashes) == 1:
        return hashes[0]
    # Pad to even number by duplicating last hash
    if len(hashes) % 2 == 1:
        hashes = hashes + [hashes[-1]]
    # Pairwise hashing up the tree
    while len(hashes) > 1:
        next_level = []
        for i in range(0, len(hashes), 2):
            combined = hashes[i] + hashes[i + 1]
            next_level.append(sha256(combined))
        hashes = next_level
    return hashes[0]

def verify_fragment(fragment_data: bytes, expected_hash: bytes) -> bool:
    """Verify a single fragment's integrity."""
    return sha256(fragment_data) == expected_hash
```

**Rationale:**
- 4–16 leaves = trivial computation, no optimization needed
- No external dependency for a simple hash tree
- Full control over serialization and verification logic
- If needs grow (e.g., inclusion proofs for partial verification), migrate to `pymerkle`

---

## 7. Media Fragmentation Strategy

### 7.1 Input Requirements

**Lossless input required for DWT embedding.** Lossy formats (JPEG, MP3) corrupt DWT embedding reliability. By default, the encoder **automatically converts** lossy input to lossless (JPEG→PNG, MP3→WAV) with a warning: "Converted from lossy format — DWT embedding quality may be reduced compared to native lossless input." Use `--strict` to reject lossy input outright.

| Media | Accepted formats | Auto-convert from | NumPy dtype | Header field |
|-------|-----------------|-------------------|-------------|--------------|
| Image | PNG (24/32-bit) | JPEG, BMP, TIFF | `uint8` | `format=0x01` |
| Audio | WAV (16/24-bit PCM) | MP3, OGG, AAC | `int16` | `format=0x02` |
| Audio | FLAC (16/24-bit) | MP3, OGG, AAC | `int16` | `format=0x03` |

Auto-conversion uses Pillow (image) and ffmpeg/soundfile (audio). The header's `original_format` field records the native lossless format used after conversion. The `--strict` flag disables auto-conversion and rejects lossy input outright.

**Bit-perfect roundtrip assertion:** Before DWT embedding, the encoder must verify that `load → save → reload` produces identical data. This is a critical validation step inserted as an assert at the very start of the encode pipeline.

### 7.2 Grid/Segment Defaults and Constraints

**One media type per session.** The header's `media_type` field enforces this — mixed media complicates reassembly for no real benefit.

**Maximum fragment count: n ≤ 16.** Shamir supports arbitrary n, but cold storage logistics (distributing USB sticks) make n > 16 impractical. A 4×4 grid is the visual upper bound for images.

**User-controlled with sensible defaults:**

| n     | Image default | Audio default |
|-------|--------------|---------------|
| 2–4   | 2×2 grid     | Equal segments |
| 5–9   | 3×3 grid     | Equal segments |
| 10–16 | 4×4 grid     | Equal segments |

CLI: `--grid 3x3` or `--segments 8`  
GUI: Dropdown with visual grid preview

**Minimum fragment sizes:**
- Image: 64×64 pixels per tile (smaller tiles look suspicious, DWT quality degrades)
- Audio: 441,000 samples per segment (~10 seconds at 44.1 kHz; enables future per-fragment watermarking)

### 7.3 Images: Tile Grid

Split the stego image into a regular grid of rectangular tiles.

```
┌─────┬─────┬─────┬─────┐
│ 0,0 │ 1,0 │ 2,0 │ 3,0 │
├─────┼─────┼─────┼─────┤
│ 0,1 │ 1,1 │ 2,1 │ 3,1 │
├─────┼─────┼─────┼─────┤
│ 0,2 │ 1,2 │ 2,2 │ 3,2 │
├─────┼─────┼─────┼─────┤
│ 0,3 │ 1,3 │ 2,3 │ 3,3 │
└─────┴─────┴─────┴─────┘
        4×4 grid = 16 fragments
```

**Implementation:**
```python
import numpy as np
from PIL import Image

def fragment_image(img_array: np.ndarray, cols: int, rows: int) -> list[np.ndarray]:
    """Split image array into cols x rows tiles. Row-major ordering."""
    h, w = img_array.shape[:2]
    tile_h = h // rows
    tile_w = w // cols
    
    assert tile_h >= 64 and tile_w >= 64, \
        f"Tile size {tile_w}x{tile_h} below minimum 64x64"
    
    fragments = []
    for row in range(rows):
        for col in range(cols):
            y1, y2 = row * tile_h, (row + 1) * tile_h
            x1, x2 = col * tile_w, (col + 1) * tile_w
            if row == rows - 1: y2 = h  # last row absorbs remainder
            if col == cols - 1: x2 = w  # last col absorbs remainder
            fragments.append(img_array[y1:y2, x1:x2].copy())
    return fragments

def reassemble_image(fragments: list[np.ndarray], cols: int, rows: int,
                     original_shape: tuple) -> np.ndarray:
    """Reassemble fragments back into complete image. Bit-perfect."""
    result = np.zeros(original_shape, dtype=fragments[0].dtype)
    h, w = original_shape[:2]
    tile_h = h // rows
    tile_w = w // cols
    for idx, frag in enumerate(fragments):
        row, col = divmod(idx, cols)
        y1 = row * tile_h
        x1 = col * tile_w
        y2 = y1 + frag.shape[0]
        x2 = x1 + frag.shape[1]
        result[y1:y2, x1:x2] = frag
    return result
```

**Key points:**
- Rectangular tiles preserve pixel data bit-perfectly (no interpolation, no loss)
- Last row/column absorbs remainder pixels for non-evenly-divisible dimensions (e.g. 1920×1081)
- Fragment ordering: row-major (left to right, top to bottom)
- dtype always `uint8` for images

### 7.4 Audio: Time Segments

```python
import numpy as np

def fragment_audio(samples: np.ndarray, n_fragments: int) -> list[np.ndarray]:
    """Split audio samples into n equal-length segments. Sample-accurate."""
    min_samples = 441000  # ~10 seconds at 44.1 kHz
    segment_len = len(samples) // n_fragments
    
    assert segment_len >= min_samples, \
        f"Segment length {segment_len} below minimum {min_samples} samples"
    
    fragments = []
    for i in range(n_fragments):
        start = i * segment_len
        end = start + segment_len if i < n_fragments - 1 else len(samples)
        fragments.append(samples[start:end].copy())
    return fragments
```

**Key points:**
- Sample-accurate cuts (no fractional samples)
- Last segment absorbs remainder samples
- For stereo/multi-channel: cut along time axis, preserve channel structure
- No crossfade or overlap — the reassembled audio must be bit-identical
- dtype always `int16` for audio

---

## 8. Compression Strategy

**Default: raw (no compression).** This maximizes longevity and simplicity.

**Optional: zlib compression** (enabled via CLI `--compress` or GUI checkbox).

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Algorithm | zlib (deflate) | RFC 1951, Python stdlib, universally available since 1996 |
| Not lz4 | — | Faster but less universal for decades-long cold storage |
| Savings | 30–60% on raw pixel data | 4K PNG tiles compress well |
| Header fields | `compression=0x01` + `uncompressed_length` | Self-describing, transparent decode |

```python
import zlib

def compress_fragment(data: bytes) -> tuple[bytes, int]:
    """Compress fragment media data. Returns (compressed, original_length)."""
    compressed = zlib.compress(data, level=6)
    if len(compressed) >= len(data):
        return data, 0  # compression didn't help, store raw
    return compressed, len(data)

def decompress_fragment(data: bytes, original_length: int) -> bytes:
    """Decompress fragment media data."""
    if original_length == 0:
        return data  # was stored raw
    return zlib.decompress(data)
```

---

## 9. Forward Error Correction (FEC)

**Per-fragment Reed-Solomon parity** protects against NAND bit-rot during long-term USB cold storage.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Overhead | 10% of media data size | Corrects 1–2 bit errors per fragment |
| Library | `reedsolo` (already used by Cryptoleaf) | No new dependency |
| Header field | `rs_fec_overhead` (1 byte, percentage) | Self-describing |

The RS parity bytes are appended after the media data section in the `.cmf` file. On decode, RS correction is applied **before** hash verification — this way, correctable bit-rot does not trigger a false integrity alarm.

**Future enhancement:** Reed-Solomon erasure coding at the **session level** (across fragments) would enable full media reconstruction from fewer than n fragments, making Path A truly (k,n). This reuses the same `reedsolo` library with different parameters and is planned for a post-MVP version.

---

## 10. Deterministic PRNG: Long-Term Portability

### 10.1 The Problem: RNG Drift Across Time and Platforms

Cryptoleaf's spread-spectrum embedding uses a seeded pseudo-random number generator (PRNG) to determine the DWT coefficient positions where data is hidden. The decoder must reproduce the **exact same sequence** to find the data. If the PRNG implementation changes — due to a Python version update, a language migration, or a platform difference — Path A decoding silently fails.

This is not hypothetical. Real-world examples:
- **Python's `random` module** uses Mersenne Twister. The algorithm has been stable since Python 2.3 (2003), but the internal state seeding changed between Python 2 and 3, and there is no guarantee it won't change in Python 4+.
- **Java's `java.util.Random`** uses a different Linear Congruential Generator (multiplier `0x5DEECE66DL`, addend `0xB`, 48-bit mask). Identical seeds produce completely different sequences than Python's MT.
- **NumPy's `numpy.random`** changed its default generator from MT19937 to PCG64 in NumPy 1.17 (2019). Code using `np.random.seed()` produces different sequences on different NumPy versions.

For a system designed to be decoded 30+ years later, relying on any language's built-in PRNG is a **critical design flaw**.

### 10.2 Where Cryptomosaic Uses Randomness

| Usage | Type | Reproducibility required? | Risk |
|-------|------|--------------------------|------|
| AES key generation | CSPRNG | No — key is stored in Shamir shares | NONE |
| GCM nonce | CSPRNG | No — nonce stored with ciphertext | NONE |
| UUID session ID | CSPRNG | No — stored in fragment headers | NONE |
| Shamir polynomial coefficients | CSPRNG | No — shares computed and stored | NONE |
| DWT spread-spectrum sequence | Seeded PRNG | **YES — must match at decode time** | **CRITICAL** |
| Fragment tile shuffling (future) | Seeded PRNG | **YES — order must be reconstructed** | **HIGH** |

The first four uses are one-shot: the random output is generated once and stored. No one ever needs to regenerate the same values. Standard CSPRNG (`Crypto.Random.get_random_bytes`) is correct and safe for these.

The last two uses are **deterministic**: the encoder and decoder must produce identical sequences from the same seed. These require a fixed, documented PRNG that is immune to platform and version changes.

### 10.3 Solution: ChaCha20-Based Deterministic PRNG

ChaCha20 (RFC 7539 / RFC 8439) is a stream cipher that, given a fixed key and nonce, produces a deterministic byte stream. Using it as a PRNG means encrypting a stream of zeros — the keystream itself is the pseudo-random output.

```python
from Crypto.Cipher import ChaCha20

class DeterministicPRNG:
    """Platform-independent PRNG for spread-spectrum sequences.
    
    Algorithm: ChaCha20 stream cipher keystream (RFC 7539).
    Given the same 32-byte seed, produces identical output on any
    platform, any language, any year. The algorithm is a cryptographic
    standard that will not change — like AES, it is frozen by RFC.
    
    This class MUST be documented in SPECIFICATION.txt with test vectors
    so it can be reimplemented in any language decades from now.
    """
    
    def __init__(self, seed: bytes):
        assert len(seed) == 32, "Seed must be 32 bytes"
        # ChaCha20 with zero nonce — pure deterministic stream from seed
        self.cipher = ChaCha20.new(key=seed, nonce=b'\x00' * 8)
    
    def random_bytes(self, n: int) -> bytes:
        """Generate n deterministic pseudo-random bytes."""
        return self.cipher.encrypt(b'\x00' * n)
    
    def random_int(self, bound: int) -> int:
        """Uniform random integer in [0, bound). Rejection sampling."""
        byte_count = (bound.bit_length() + 7) // 8 + 1
        while True:
            raw = int.from_bytes(self.random_bytes(byte_count), 'little')
            result = raw % bound
            # Rejection sampling eliminates modulo bias
            if raw - result + (bound - 1) >= 0:
                return result
    
    def random_float(self) -> float:
        """Uniform float in [0.0, 1.0). For DWT alpha calculations."""
        raw = int.from_bytes(self.random_bytes(8), 'little')
        return (raw >> 11) / (1 << 53)  # IEEE 754 double precision
```

**Why ChaCha20:**
- RFC-standardized — the algorithm is frozen and will not change, ever
- Cryptographically secure — the sequence is indistinguishable from true randomness
- Universally implemented — C, Rust, Java, Go, JavaScript, even hardware accelerated
- Already a PyCryptodome dependency — no new imports needed
- Simple to reimplement — ~80 lines of pure code in any language, no lookup tables
- Deterministic — same key + nonce = identical byte stream, guaranteed

**Why NOT Mersenne Twister, PCG, xorshift, or any language-built-in PRNG:**
- Not standardized by any RFC or NIST document
- Implementations differ across languages and versions (proven by Java vs. Python)
- Not cryptographically secure (MT is predictable from 624 outputs)
- No guarantee of long-term stability in any language runtime

### 10.4 Test Vectors (for SPECIFICATION.txt)

The SPECIFICATION.txt must include test vectors so that any future reimplementation can be verified:

```
ChaCha20 PRNG Test Vectors
===========================
Seed (hex): 0000000000000000000000000000000000000000000000000000000000000001
Nonce:      0000000000000000

First 16 output bytes (hex): [computed at implementation time]
random_int(1000) calls 1-5:  [computed at implementation time]
random_float() calls 1-5:    [computed at implementation time]

Seed (hex): 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
Nonce:      0000000000000000

First 16 output bytes (hex): [computed at implementation time]
random_int(1000) calls 1-5:  [computed at implementation time]
random_float() calls 1-5:    [computed at implementation time]
```

These vectors ensure that a Rust or C reimplementation in 2056 can verify correctness before attempting to decode 30-year-old fragments.

### 10.5 Seed Derivation and Creative Uses

**Where the PRNG seed comes from:** The spread-spectrum seed is derived from the AES encryption key K and the session ID using HKDF:

```python
from Crypto.Protocol.KDF import HKDF
from Crypto.Hash import SHA256

def derive_prng_seed(key: bytes, session_id: bytes) -> bytes:
    """Derive a 32-byte PRNG seed from the encryption key and session."""
    return HKDF(master=key, key_len=32, salt=session_id,
                hashmod=SHA256, context=b'cryptomosaic-spread-spectrum-v1')
```

This means: if you can reconstruct the AES key (via Shamir), you can derive the PRNG seed and decode the spread-spectrum sequence. The seed does not need to be stored separately.

**Additional seed applications:**

**Deterministic fragment ordering:** The PRNG seed can shuffle tile ordering — instead of row-major (0,1,2,...,15), fragments are distributed in a seeded permutation. This does not add meaningful cryptographic security (it is obscurity, not encryption), but makes visual reconstruction from partial fragments harder for a casual adversary. The permutation is deterministic and reproducible from the seed.

**Reproducible encode (verification mode):** Same message + same carrier + same key = bitwise identical fragments. Two parties can independently verify they hold the same fragment set by comparing hashes, without revealing the message. Useful for non-repudiation in contract scenarios.

**Passphrase-derived key (future enhancement):** Instead of a random AES key, derive it from a memorizable passphrase: `K = Argon2id(passphrase, salt=session_id, t=3, m=65536)`. The key lives in the user's memory — no USB stick needed for the key itself, only for the fragments. Shamir would then split the derived key normally. Argon2id (RFC 9106) is the correct KDF here because it is memory-hard, resistant to GPU/ASIC brute-force, and standardized. This is NOT the same as using a simple hash of a password.

### 10.6 Impact on cryptoleaf-core

**Critical action item:** Before Cryptomosaic development begins, Cryptoleaf's spread-spectrum code must be audited for PRNG usage. If it uses `random.seed()`, `random.random()`, `np.random.seed()`, or any language-built-in PRNG for the spreading sequence, it must be replaced with `DeterministicPRNG` (ChaCha20-based) in the `cryptoleaf-core` extraction.

This change benefits both projects:
- Cryptoleaf gains long-term decode portability
- Cryptomosaic inherits a proven, standardized PRNG from day one

The replacement is backwards-compatible if done carefully: existing Cryptoleaf-encoded files can be decoded with the old PRNG (MT), and a version flag in the header indicates which PRNG to use. New encodes use ChaCha20 exclusively.

---

## 11. Security Analysis (Red-Team)

This section presents a comprehensive adversarial analysis of Cryptomosaic. Three attacker profiles are considered, followed by a systematic evaluation of each attack vector, its impact, and mitigations.

### 11.1 Attacker Profiles

| Profile | Access | Capability |
|---------|--------|-----------|
| **A. Single fragment holder** | One fragment (USB seizure, email intercept, theft) | Forensic analysis, steganalysis, entropy analysis |
| **B. Partial coalition** | < k fragments from different sources | Correlation analysis, partial reconstruction attempts |
| **C. Full forensic attacker** | ≥ k fragments, professional forensic tools | Full cryptanalysis, steganalysis, format reverse engineering |

### 11.2 Attack Vector Analysis

#### Attack 1: Container Fingerprinting

**Vector:** The `.cmf` header begins with magic bytes `0x434D4F53` ("CMOS"). Any forensic pipeline scanning for known signatures will immediately identify the file as a Cryptomosaic fragment.

**Impact:** Does not break cryptography, but **destroys plausible deniability**. The adversary immediately knows the tool used, fragment count, threshold, media type, and creation timestamp.

**Risk level:** HIGH for scenarios requiring covert use. LOW for scenarios where the existence of encrypted material is acceptable (e.g., estate planning with known trustees).

**Mitigation:** Wrapped mode (see Section 11.4) — fragments embedded inside innocent-looking audio/image files via Cryptoleaf. Planned as post-MVP enhancement.

#### Attack 2: Ciphertext Artifact / Fragment Correlation

**Vector:** If all fragments contained identical ciphertext, an adversary with two fragments from different sources could use entropy analysis to detect identical high-entropy blocks — proving the fragments are related.

**Impact:** Would enable **fragment correlation attack** — linking fragments across holders without breaking cryptography.

**Risk level:** ~~MEDIUM~~ → **MITIGATED** (rev 7).

**Mitigation (implemented):** Per-fragment ciphertext randomization. Each fragment stores `Ci = C ⊕ ChaCha20(HKDF(K, i))` where C is the base AES-GCM ciphertext, K is the encryption key, and i is the fragment index. Every fragment's ciphertext block appears as unique random data — byte-level comparison reveals no correlation. On decode, the same KDF+XOR de-randomizes before AES-GCM decrypt. This adds negligible computational cost (~1 ms) and does not break Path B: any k fragments can still reconstruct K via Shamir, then de-randomize any fragment's Ci to recover C.

#### Attack 3: Partial Coalition Steganalysis

**Vector:** An adversary with < k fragments cannot recover the key, but can analyze individual media fragments for steganographic artifacts using modern CNN-based classifiers (SRNet, SCA-SRNet).

**Impact:** Cannot reveal message content. Can potentially confirm that **steganography was used** — but this is limited because spread-spectrum DWT embeds across the full carrier before fragmentation, so each fragment contains only a portion of the spread signal. Blind steganalysis (without original carrier) is significantly harder than known-cover analysis. Current state-of-art CNN classifiers achieve ~65% accuracy at 0.25 bpp — barely above random guess.

**Risk level:** LOW-MEDIUM. CNN-based steganalysis is improving but not decisive at low payloads.

**Mitigation:** Cryptoleaf's adaptive alpha minimizes statistical detectability. Larger minimum tile sizes (64×64) help. **Pre-release requirement:** empirical steganalysis testing with Aletheia and StegExpose against actual Cryptomosaic fragments to validate DWT parameter choices and establish carrier-quality-dependent embedding rate limits.

#### Attack 4: Small Fragment Steganalysis

**Vector:** Small media fragments (e.g., 64×64 pixel tiles) may show more visible statistical anomalies from DWT embedding than larger images.

**Impact:** Potential detection that hidden data exists. However, because the DWT embedding is applied to the **full carrier** before fragmentation, each small tile carries only a fraction of the spread-spectrum signal. This actually **reduces** per-fragment detectability compared to analyzing the complete stego image — the signal-to-noise ratio of the embedding is lower in any single tile.

**Risk level:** LOW. Fragmentation inadvertently improves steganographic stealth per-fragment.

**Mitigation:** Enforce minimum tile sizes. Consider larger default grids (3×3 instead of 4×4) for maximum stealth.

#### Attack 5: Chosen Carrier Attack

**Vector:** Adversary provides a specifically crafted image to the user, who unknowingly uses it as a carrier. The crafted image is designed to make DWT embedding artifacts easily detectable.

**Impact:** Steganography robustness is compromised for that specific carrier.

**Risk level:** LOW. Requires active social engineering; narrow attack window.

**Mitigation:** Documentation: "Always use your own original photographs as carriers. Never use images provided by untrusted sources." This is an operational guideline, not a code-level defense.

#### Attack 6: Fragment Destruction (Availability Attack)

**Vector:** Adversary does not try to read fragments but destroys them to prevent threshold from being reached. Targets USB sticks, physical storage, or network transfer.

**Impact:** **Denial of access** — legitimate holders cannot reconstruct the message.

**Risk level:** MEDIUM-HIGH for physical cold storage scenarios.

**Mitigation:** Multiple copies per fragment (3×, different manufacturers, geographically separated). RS FEC corrects minor damage. Threshold k < n provides tolerance for some fragment loss (key recovery still works). Session-level erasure coding (future) would extend tolerance to media reconstruction.

#### Attack 7: Long-Term Cryptanalysis (Quantum Threat)

**Vector:** Adversary stores captured ciphertext and waits for advances in cryptanalysis, specifically quantum computing. Grover's algorithm halves the effective key length of symmetric ciphers: AES-128 → 64-bit equivalent security.

**Impact:** For cold storage spanning 20–30+ years, AES-128 would be insufficient against future quantum computers. AES-256 provides 128-bit post-quantum security — adequate for foreseeable threats.

**Risk level:** ~~MEDIUM-HIGH~~ → **LOW** (rev 7, AES-256 is now default).

**Mitigation (implemented):** AES-256-GCM is the default from MVP. Provides 128-bit security even against Grover's algorithm. The `.cmf` format version field allows future cipher migration if needed. Post-quantum KEMs (Kyber/ML-KEM) documented as future research topic.

#### Attack 8: Fragment Poisoning (Fake Share Injection)

**Vector:** Adversary provides a fabricated fragment with a valid-looking header but a corrupted Shamir share. PyCryptodome's `Shamir.combine()` does not validate the result — it produces a wrong key silently.

**Impact:** **Denial of service** — AES decryption fails or produces garbage, and the user may not understand why.

**Risk level:** MEDIUM. Requires ability to inject a fragment into the reconstruction ceremony.

**Mitigation (implemented):** AES-256-**GCM** authenticated encryption. The GCM authentication tag verification fails immediately if the reconstructed key is wrong, producing a clear error: "Key reconstruction failed — one or more fragments may be corrupted or falsified." This is a direct result of choosing GCM over CBC mode.

#### Attack 9: Metadata Correlation

**Vector:** Header fields (timestamp, session ID, fragment count) are plaintext. An adversary with fragments from different sources can correlate them by matching session IDs and timestamps.

**Impact:** Confirms which fragments belong together and when they were created.

**Risk level:** LOW-MEDIUM. This is metadata, not content. Accepted as a design trade-off (fragments need to identify their session for reassembly).

**Mitigation:** Wrapped mode (Section 11.4) hides metadata inside Cryptoleaf-embedded carrier audio/images. For MVP, this is an accepted limitation.

#### Attack 10: Implementation Bugs

**Vector:** Python-specific risks: RNG misuse, nonce reuse, serialization bugs, endianness errors, padding errors. These are more realistic threats than breaking the underlying mathematics.

**Impact:** Potentially catastrophic — can compromise the entire system.

**Risk level:** HIGH. This is the most probable attack surface in practice.

**Mitigation:** Use PyCryptodome's secure RNG (`get_random_bytes()`), never custom RNG. Unit test all serialization roundtrips. Use `struct.pack`/`unpack` with explicit format strings. Test on both little-endian and big-endian (if available). Fuzz the `.cmf` parser with malformed inputs. Code review checklist before release.

#### Attack 11: Human Factor / Operational Misuse

**Vector:** Users store all fragments in the same location, send fragments via email, lose fragments, share the threshold configuration publicly, or fail to maintain USB media.

**Impact:** Defeats the entire secret sharing model.

**Risk level:** HIGH. The most common failure mode in any distributed security system.

**Mitigation:** Cannot be solved in code. Clear documentation, GUI warnings ("You are about to save all fragments to the same directory — this defeats the purpose of secret sharing"), and operational best practices in the README.

#### Attack 12: Traffic Analysis

**Vector:** If fragments are transferred over a network, their similar sizes and timing can reveal that a distributed steganographic operation is underway.

**Risk level:** LOW. Cryptomosaic is designed for physical (USB) distribution, not network transfer. If network transfer is needed, standard encrypted channels (HTTPS, Signal, etc.) should be used.

#### Attack 13: Fragment Harvesting

**Vector:** If Cryptomosaic becomes popular, adversaries may systematically harvest `.cmf` files from the internet, storage services, or compromised devices, building a database for future correlation and analysis.

**Risk level:** LOW-MEDIUM. Depends on tool popularity and fragment distribution methods.

**Mitigation:** Wrapped mode (Section 11.4) makes fragments indistinguishable from normal media files. For MVP, operational guidance: do not store fragments on cloud services or transmit them over unencrypted channels.

#### Attack 14: Reconstruction Without Application

**Vector:** An adversary with all n fragments and knowledge of the `.cmf` format (which is documented) can reconstruct the media and apply standard steganalysis tools. Security depends entirely on AES encryption, not on obscurity.

**Impact:** None beyond normal cryptanalysis — this is by design (Kerckhoffs's principle).

**Risk level:** N/A. The system's security does not depend on algorithm secrecy.

#### Attack 15: Malicious Fragment Injection (Parser Exploit)

**Vector:** A crafted `.cmf` file with malicious header values (e.g., extreme `media_data_length`, negative offsets, oversized `ciphertext_length`) could trigger buffer overflows, memory exhaustion, or other parser vulnerabilities.

**Impact:** Application crash, potential code execution (less likely in Python, but memory exhaustion is real).

**Risk level:** MEDIUM. Relevant whenever fragments are received from untrusted sources.

**Mitigation (implemented):** Defensive parsing requirements for the `.cmf` reader:
- Validate all length fields before memory allocation (max 100 MB per fragment)
- Verify magic bytes before parsing any further
- Check that `fragment_index < total_fragments`
- Verify `threshold <= total_fragments`
- Ensure `media_data_offset + media_data_length` does not exceed file size
- Reject any header with CRC-32 mismatch before processing payload
- Wrap all parsing in try/except with graceful error messages

#### Attack 16: PRNG Drift (Long-Term Decode Failure)

**Vector:** Path A decoding relies on a deterministic PRNG to regenerate the spread-spectrum sequence used during DWT embedding. If the PRNG implementation changes (Python version update, language migration, NumPy default generator change), the decoder generates a different sequence and cannot find the embedded data. The message is lost despite having the correct key and all fragments.

**Impact:** **Silent data loss** — Path A decoding fails with no clear error. The decoder extracts garbage from wrong DWT positions and AES-GCM authentication fails with a generic "decryption error."

**Risk level:** HIGH on a 30-year horizon. Proven real-world: Java's LCG and Python's Mersenne Twister produce different sequences from the same seed. NumPy changed its default from MT19937 to PCG64 in 2019.

**Mitigation (implemented):** ChaCha20-based deterministic PRNG (Section 10) replaces all language-built-in PRNGs for spread-spectrum sequences. ChaCha20 is RFC-standardized and will not change. Test vectors in SPECIFICATION.txt enable reimplementation in any language. Path B (header-only decrypt) is immune to this attack because it does not use DWT.

### 11.3 What is NOT Hidden (MVP Mode)

The `.cmf` header is plaintext metadata. An adversary who obtains a single fragment can learn:
- That Cryptomosaic was used (magic bytes "CMOS")
- The session ID, fragment index, total fragment count, and threshold
- The timestamp of creation
- The media type and dimensions

This is acceptable for use cases where the **existence** of encrypted material is not a secret (estate planning with known trustees, business document custody). For use cases requiring **covert operation**, wrapped mode (Section 11.4) embeds fragments inside innocent-looking media files via Cryptoleaf.

### 11.4 Wrapped Mode: Forensic Stealth via Cryptoleaf (Post-MVP Enhancement)

The single most impactful security improvement identified by the red-team analysis: **make fragments indistinguishable from normal media files.**

**Solution: Wrapped mode** (see Section 2.5 for full architecture). Instead of storing `.cmf` files on USB sticks, each lightweight fragment is embedded into an innocent-looking audio file or photograph using Cryptoleaf's existing DWT spread-spectrum engine. The USB stick contains only standard media files — `voice_memo_03.wav`, `meeting_recording.wav` — that pass forensic inspection as normal files.

**Audio as default carrier:** A ~5 KB lightweight fragment embedded in a 10-minute audio segment (~100 MB WAV) occupies approximately 0.005% of the carrier capacity. The DWT signal is so faint that advanced steganalysis cannot distinguish it from natural audio noise. Combined with Cryptoleaf's psychoacoustic masking, audio carriers provide the strongest forensic stealth of any medium. The user provides one long recording; Cryptomosaic auto-segments it into n carriers.

**Why this is better than the original stealth mode concept (v3):** The original stealth mode attempted to make the `.cmf` file itself a valid PNG/WAV by embedding metadata in the media format's own structures. This required a second steganographic layer inside the fragment, creating fragility and complexity. Wrapped mode takes the opposite approach: keep the `.cmf` format intact and hide the entire fragment inside a separate carrier image using a proven tool. Clean separation of concerns, no new steganographic code needed.

**Effect on attack surface:**
- Attack 1 (container fingerprinting): **eliminated** — `file` command shows "PNG image data"; no "CMOS" magic bytes visible
- Attack 2 (ciphertext artifact): **eliminated** — ciphertext hidden inside DWT domain of carrier image, not visible as a plaintext block
- Attack 9 (metadata correlation): **eliminated** — session ID, timestamps, all metadata buried in steganographic layer
- Attack 12 (traffic analysis): **reduced** — fragment files are different sizes (different carrier images), breaking size correlation
- Attack 13 (fragment harvesting): **eliminated** — fragments are indistinguishable from any other image/audio file

**Trade-offs:**
- Fragment file size increases from ~5 KB to carrier size (~60–100 MB per audio segment, ~2–10 MB per image)
- Adds Cryptoleaf as a decode-time dependency (but it's already in the distribution set)
- Path A (full media reconstruction with stego mosaic) is not available in wrapped mode
- Additional encode/decode step increases processing time slightly
- User must provide a recording of sufficient length (≥ n × 10 minutes recommended)

**Implementation plan:** CLI flag `--wrapped` activates wrapped mode. `--carrier source_audio.wav` provides the audio to auto-segment (default). `--carrier-type image --carrier-dir ./photos/` for image carriers. Default mode remains standard `.cmf` for simplicity. Wrapped mode is Phase 3–4.

### 11.5 Attacks That Do NOT Work

The following attacks are computationally infeasible:

| Attack | Why it fails |
|--------|-------------|
| AES brute force | 2^128 key space (2^256 with upgrade) — no known practical shortcut |
| Shamir share reconstruction with < k shares | Information-theoretically impossible — SSS provides perfect secrecy |
| Merkle integrity bypass | Would require SHA-256 collision — computationally infeasible |
| GCM authentication tag forgery | Probability 2^-128 per attempt |

### 11.6 Red-Team Summary

**What Cryptomosaic handles well:**
- Cryptanalysis (AES + SSS provide strong mathematical guarantees)
- Key extraction from individual fragments (information-theoretically impossible)
- Fragment tampering (Merkle + chain + GCM authentication detect all modifications)
- NAND bit-rot (RS FEC provides resilience)
- Long-term PRNG portability (ChaCha20 replaces platform-dependent PRNGs)

**Where Cryptomosaic is weaker (MVP):**
- Forensic stealth (`.cmf` container is immediately identifiable)
- Ciphertext correlation across fragments (identical ciphertext in all headers)
- Metadata leakage (plaintext header fields)
- Operational misuse (cannot be solved in code)

**Priority improvements:**
1. **AES-256-GCM** — 128-bit post-quantum security for cold storage (implemented in rev 7)
2. **AES-GCM** — mitigates fragment poisoning (implemented in rev 3)
3. **Per-fragment CT randomization** — eliminates cross-fragment correlation (implemented in rev 7)
4. **Header HMAC** — cryptographic header integrity replacing CRC-32 (implemented in rev 7)
5. **Defensive parsing** — mitigates malicious fragment injection (implemented in rev 3)
6. **ChaCha20 PRNG** — mitigates long-term PRNG drift (implemented in rev 5)
7. **Wrapped mode** — mitigates forensic detection via Cryptoleaf embedding (planned Phase 3–4)
8. **Feldman VSS** — prevents dealer cheating (planned post-MVP)
9. **Empirical steganalysis** — validate DWT parameters against CNN classifiers (pre-release requirement)

### 11.7 Error Message Philosophy: Mode-Dependent Failure Behavior

A subtle but critical design decision: **should decryption failure produce a clear error or silent garbage?**

Clear error messages (e.g., "wrong key", "authentication failed") help legitimate users debug problems. But they also serve as **oracle attacks** — an adversary can distinguish "wrong key" from "no data found", confirming the existence of hidden content and enabling brute-force termination detection.

**The answer depends on the encode mode:**

**Standard/Lightweight mode (.cmf files):**
The `.cmf` header is plaintext — an adversary already knows the file is a Cryptomosaic fragment. Error messages reveal no additional information. Clear, helpful errors are appropriate:
- "You need at least {k} fragments. Currently have {have}."
- "Fragment {idx} failed integrity check."
- "Key reconstruction failed — one or more fragments may be corrupted or falsified."

**Wrapped mode (fragments hidden in audio/images):**
The entire point is that no one knows the file contains hidden data. If decryption fails and the application reports "GCM authentication failed", it confirms that hidden data exists and was found. This breaks deniability completely.

Correct behavior in wrapped mode: **silent failure**. The application behaves identically regardless of whether hidden data was found, whether the key is wrong, or whether the file contains no hidden data at all. On success, the message is returned. On failure — for any reason — the application returns nothing and gives no indication of what happened. No error, no garbage, no distinction.

**Passphrase mode (future, Argon2id):**
This is the most sensitive case. If the application says "wrong password", an attacker has a brute-force oracle: try passwords until the error disappears. Correct behavior: **always produce output**. A wrong passphrase should derive a wrong key, which should produce deterministic garbage that looks like a plausible decrypted message (or at minimum, undistinguishable random bytes). The user knows the message is correct by recognizing its content, not by the absence of an error. This is the same principle behind VeraCrypt's hidden volumes — the system never confirms or denies what it found.

**Summary:**

| Mode | On failure | Rationale |
|------|-----------|-----------|
| Standard/Lightweight | Clear error message | Header already reveals everything; errors help users |
| Wrapped | Silent — no output, no error | Deniability: attacker cannot confirm data exists |
| Passphrase (future) | Deterministic garbage output | Anti-oracle: attacker cannot distinguish right from wrong passphrase |

---

## 12. Time-Lock Considerations

A planned future feature allows encrypted messages that can only be decrypted after a specified date.

### 12.1 Software Time-Lock (MVP Approach)

A simple `unlock_after` timestamp in the `.cmf` header. Cryptomosaic refuses to decrypt before this date.

**Limitation:** This is an "honest party" protection only — the local system clock can be manipulated. However, combined with k-of-n threshold (multiple parties must agree to decrypt), it adds a meaningful layer: you need both enough people AND the right time.

### 12.2 Cryptographic Time-Lock (Future Research)

For stronger guarantees without trusting the local clock:

**RSA Time-Lock Puzzles** (Rivest, Shamir, Wagner 1996): Construct a puzzle that requires a fixed amount of sequential computation to solve — parallelization does not help. The decryption key is hidden behind the puzzle. The time to solve depends on the CPU speed of the decoder.

**Pros:** No trusted third party needed — truly self-contained, fits the time capsule principle.  
**Cons:** Requires careful calibration of computation time vs. future hardware speed. A puzzle designed for "10 years" on 2026 hardware might be solvable in months on 2036 hardware.

**Verdict:** Software time-lock for MVP (simple, useful when combined with human trust). Cryptographic time-lock as a research topic for future versions.

---

## 13. Prior Art Analysis

### 13.1 Academic Research

The combination of steganography and secret sharing is well-studied in academia:

- **Lin & Tsai (2004):** Pioneered secret image sharing with steganography and authentication. Used (k,n)-threshold schemes to split secret images into shares hidden in camouflage images.
- **Springer 2022 (Stego-SS):** "Steganographic secret sharing via AI-generated photorealistic images" — uses CNNs to embed shares in generated images with authentication mechanisms.
- **Al-Shaarani et al. (2021):** Combined counting-based secret sharing with DWT steganography and XOR encryption in images.
- **MDPI 2020:** Distributed steganography in PDF files using secret splitting algorithms.

### 13.2 Existing Tools

- **Coldwallet OS** (codeberg.org/coldwalletos/os): Uses Shamir's Secret Sharing for Bitcoin cold wallet key distribution on USB sticks. Validates the SSS + USB cold storage approach but targets cryptocurrency keys only, not steganographic media.

### 13.3 Cryptomosaic's Unique Contribution

Existing work typically:
- Embeds shares INTO separate cover images (each share gets its own cover)
- Focuses on visual secret sharing (overlaying transparencies)
- Requires online infrastructure or specific software environments
- Targets short-term secure transmission, not long-term cold storage

**Cryptomosaic is differentiated by:**
- Embedding the message in ONE carrier, THEN fragmenting the carrier itself
- Each fragment is a piece of the actual carrier, not a separate cover
- Three encode modes: standard (full stego), lightweight (compact), wrapped (forensic stealth)
- Wrapped mode: fragments hidden inside audio/images via Cryptoleaf — zero forensic fingerprint
- UTF-8 text payload optimized for decades-long format immortality
- Designed for offline cold storage spanning decades (time capsule principle)
- Self-contained binary format with complete self-describing headers
- Blockchain-style integrity (Merkle tree + chain) without any blockchain
- Per-fragment FEC for long-term storage resilience
- Authenticated encryption (AES-GCM) prevents silent decryption failures
- Dual-layer security: media fragmentation AND key splitting (SSS)

---

## 14. Cold Storage Best Practices (for README)

### 14.1 USB Stick Selection and Storage

- NAND flash retains data 5–10 years without power; SLC NAND is more durable than TLC
- **Recommended: 3 copies of each fragment** on USB sticks from different manufacturers
- Store in airtight containers with silica gel desiccant packets
- Store in cool, dry, dark environment (avoid temperature fluctuations)
- Refresh media every 5 years: copy to fresh USB sticks and verify checksums

### 14.2 Distribution Set Contents

Every distribution set (per recipient) should contain:

```
USB stick contents (standard/lightweight mode):
├── fragment_03_of_09.cmf          The recipient's fragment
├── SPECIFICATION.txt              Complete .cmf format specification
├── cryptomosaic-1.0.AppImage      Standalone application (Linux)
├── cryptomosaic-1.0-win.exe       Standalone application (Windows, Nuitka)
├── source-1.0.tar.gz              Complete source code archive
└── README.txt                     Quick-start instructions

USB stick contents (wrapped mode):
├── voice_memo_03.wav              Audio file with embedded fragment (looks normal)
├── SPECIFICATION.txt              Complete .cmf format specification
├── cryptomosaic-1.0.AppImage      Cryptomosaic application (Linux)
├── cryptoleaf-0.2.AppImage        Cryptoleaf application for extraction (Linux)
├── source-cryptomosaic-1.0.tar.gz Cryptomosaic source code archive
├── source-cryptoleaf-0.2.tar.gz   Cryptoleaf source code archive
└── README.txt                     Quick-start instructions
```

This ensures that a fragment set remains decodable decades later, even if Codeberg, PyPI, or any online service no longer exists.

### 14.3 Application Packaging

| Format | Target | Toolchain |
|--------|--------|-----------|
| AppImage | Linux (Ubuntu 22.04 LTS+, Debian 12+) | Nuitka static compilation |
| .exe | Windows 10+ | Nuitka standalone |
| Source archive | Any platform with Python 3.10+ | Fallback |

Build against older base systems (Ubuntu 22.04 LTS / Debian 12) for maximum glibc compatibility — following the same approach used for Cryptoleaf.

---

## 15. Shared Library Strategy: cryptoleaf-core

To avoid code duplication, the DWT/spread-spectrum embedding core should be extracted from Cryptoleaf into a shared library.

```
cryptoleaf-core/         (shared library, PyPI package)
├── dwt_engine.py        DWT embedding/extraction
├── spread_spectrum.py   Spread-spectrum encoding
├── prng.py              ChaCha20-based deterministic PRNG (RFC 7539)
├── reed_solomon.py      Error correction
├── psychoacoustic.py    Audio masking
└── adaptive_alpha.py    Adaptive embedding strength

cryptoleaf/              (1:1 steganography tool)
├── depends on cryptoleaf-core
└── GUI, CLI, file I/O

cryptomosaic/            (distributed secret sharing tool)
├── depends on cryptoleaf-core
├── sss/                 Shamir's Secret Sharing wrapper
├── fragmentation/       Media splitting/reassembly
├── merkle/              Merkle tree + chain verification
├── fragment_format/     .cmf binary format I/O
├── fec/                 Reed-Solomon per-fragment FEC
├── compression/         Optional zlib compression
└── GUI, CLI
```

**Approach:** Copy relevant Cryptoleaf modules first for the MVP, then extract into a shared package. Do not refactor Cryptoleaf v0.2.x until Cryptomosaic's pipeline is stable.

**Critical pre-requisite: PRNG audit and migration** (see Section 10.6). Cryptoleaf's spread-spectrum PRNG must be migrated from language-built-in (likely Mersenne Twister) to ChaCha20-based `DeterministicPRNG` before or during the core extraction. This is essential for long-term decode portability.

---

## 16. Edge Cases and Validation

### 16.1 Input Validation

| Check | Action |
|-------|--------|
| Lossy input (JPEG, MP3) | Auto-convert to lossless with warning (MVP); reject if `--strict` |
| Image too small for grid | Reject if any tile < 64×64 px |
| Audio too short for segments | Reject if any segment < 441,000 samples (~10 s) |
| n = 1 | Allow with warning: "Single fragment offers no secret sharing benefit" |
| Empty fragment (0 bytes media) | Reject — minimum 1 KB media data per fragment |
| Timestamp in future | Accept within ±30 day tolerance (clock skew) |
| Bit-perfect roundtrip | Assert `load → save → reload == original` before DWT embedding |

### 16.2 Defensive Parsing (.cmf Reader)

All `.cmf` parsing must be defensive against malformed or malicious input:

| Check | Action |
|-------|--------|
| Magic bytes ≠ "CMOS" | Reject immediately: "Not a CryptoMosaic fragment" |
| Header CRC-32 mismatch | Reject: "Fragment header is corrupted" |
| `fragment_index >= total_fragments` | Reject: "Invalid fragment index" |
| `threshold > total_fragments` | Reject: "Invalid threshold configuration" |
| `media_data_length > 100 MB` | Reject: "Fragment exceeds maximum size" |
| `media_data_offset + media_data_length > file_size` | Reject: "Fragment is truncated" |
| `ciphertext_length > 65536` | Reject: "Ciphertext exceeds maximum size" |
| `sss_share_length > 1024` | Reject: "Shamir share exceeds maximum size" |
| Any parsing exception | Catch and report gracefully, never crash |

### 16.3 Decode Error Messages

**Standard/Lightweight mode** — clear errors help the user:

| Condition | User-facing message |
|-----------|-------------------|
| Fewer than k fragments | "You need at least {k} fragments. Currently have {have}, need {k - have} more." |
| Session ID mismatch | "Fragment {name} belongs to a different session. Remove it and try again." |
| Merkle root mismatch | "Fragment {idx} failed integrity check — it may be corrupted or tampered." |
| RS FEC correction applied | "Fragment {idx}: corrected {n} bit errors (NAND aging). Consider refreshing USB media." |
| RS FEC exceeded capacity | "Fragment {idx} is too corrupted to repair. A backup copy is needed." |
| GCM authentication failure | "Key reconstruction failed — one or more fragments may be corrupted or falsified." |
| Path A: missing fragments | "Full media reconstruction requires all {n} fragments. Have {have}. Using header-only decryption (Path B)." |
| Time-lock not yet reached | "This message is time-locked until {date}. Decryption is not yet available." |

**Wrapped mode** — silent failure, no error oracle (see Section 11.7):

| Condition | Behavior |
|-----------|---------|
| Decryption succeeds | Return decrypted message |
| Any failure (wrong key, no data, corrupt fragment, etc.) | Return nothing — no error, no output, no distinction between failure modes |

**Passphrase mode (future)** — deterministic garbage, no oracle (see Section 11.7):

| Condition | Behavior |
|-----------|---------|
| Correct passphrase | Return decrypted message |
| Wrong passphrase | Return deterministic garbage derived from the wrong key (indistinguishable from a valid message to an attacker without context) |

### 16.4 Performance Expectations

| Operation | Estimated time | Notes |
|-----------|---------------|-------|
| 4K image → 16 tiles | < 1 s | NumPy vectorized slicing |
| 1 hour audio → 8 segments | < 1 s | Array slicing, no resampling |
| DWT embedding (4K image) | 2–5 s | Bottleneck — from Cryptoleaf |
| Shamir split (16 shares) | < 10 ms | Trivial polynomial math |
| Merkle tree (16 leaves) | < 1 ms | 16 SHA-256 hashes |
| RS FEC encode (10% overhead) | < 500 ms | Per-fragment, parallelizable |
| zlib compression (one tile) | < 100 ms | Optional |
| AES-256-GCM encrypt | < 1 ms | Negligible for ≤ 4 KB messages |

### 16.5 Fuzz Testing Strategy

The `.cmf` parser is the primary attack surface for malicious input (see Attack 15). Automated fuzz testing is mandatory before release.

**Primary tool: Hypothesis (property-based testing)**

Hypothesis integrates directly with pytest, generates intelligent edge cases, and minimizes failing examples automatically. It is the best fit for Cryptomosaic's Python codebase.

```python
from hypothesis import given, strategies as st, settings

@given(data=st.binary(min_size=0, max_size=500))
@settings(max_examples=50000)
def test_cmf_parser_never_crashes(data):
    """Parser must handle ANY binary input without crashing."""
    try:
        fragment = parse_cmf(data)
    except CmfValidationError:
        pass  # Expected — invalid input correctly rejected
    # Must never raise any other exception, hang, or allocate >100 MB

@given(data=st.binary(min_size=204, max_size=1000))
def test_cmf_parser_with_magic_bytes(data):
    """Deeper parsing paths: inject valid magic to exercise header parsing."""
    modified = b'CMOS' + data[4:]
    try:
        parse_cmf(modified)
    except CmfValidationError:
        pass

@given(
    index=st.integers(min_value=0, max_value=65535),
    total=st.integers(min_value=0, max_value=65535),
    threshold=st.integers(min_value=0, max_value=255),
    media_len=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_cmf_header_field_boundaries(index, total, threshold, media_len):
    """Boundary values in header fields must be validated, not blindly trusted."""
    header = build_test_header(index=index, total=total,
                               threshold=threshold, media_len=media_len)
    try:
        parse_cmf(header)
    except CmfValidationError:
        pass
```

**Secondary tools (CI/CD pipeline):**

| Tool | Purpose | When |
|------|---------|------|
| Hypothesis | Property-based testing, smart edge cases | Every commit (pytest integration) |
| python-afl | Mutation fuzzing, coverage-guided | Nightly CI, pre-release |
| tracemalloc | Memory leak detection during fuzz runs | Paired with Hypothesis tests |

**Fuzz targets (in priority order):**
1. `.cmf` binary parser — primary attack surface
2. Merkle tree verification — hash manipulation edge cases
3. Shamir combine — invalid/corrupted shares
4. zlib decompression — decompression bombs (limit output size)
5. RS FEC decode — corrupted parity data
6. Audio carrier quality analysis — edge case waveforms

### 16.6 Audio Carrier Quality Analysis (Wrapped Mode)

In wrapped mode, audio segments serve as carriers for Cryptoleaf DWT embedding. Silent or low-entropy audio segments provide poor steganographic cover — DWT modifications stand out in near-zero signal regions.

**Pre-embedding carrier quality checks:**

```python
import struct, math

def analyze_carrier_quality(samples: list[int], sample_rate: int = 44100,
                           silence_threshold: float = 0.01) -> dict:
    """Analyze audio segment suitability as a steganographic carrier.
    Pure Python — no NumPy required.
    """
    n = len(samples)
    if n == 0:
        return {'suitable': False, 'reason': 'Empty audio segment'}
    
    # RMS energy (root mean square)
    rms = math.sqrt(sum(s * s for s in samples) / n) / 32768.0  # normalize int16
    
    # Silent sample ratio (below threshold)
    silent = sum(1 for s in samples if abs(s) / 32768.0 < silence_threshold)
    silence_ratio = silent / n
    
    # Zero-crossing rate (proxy for spectral variation)
    crossings = sum(1 for i in range(1, n) if (samples[i] >= 0) != (samples[i-1] >= 0))
    zcr = crossings / n
    
    # Segment duration
    duration_s = n / sample_rate
    
    warnings = []
    if rms < 0.005:
        warnings.append(f'Very low energy (RMS={rms:.4f}) — near-silent audio')
    if silence_ratio > 0.3:
        warnings.append(f'{silence_ratio:.0%} of samples are silent')
    if zcr < 0.01:
        warnings.append(f'Low spectral variation (ZCR={zcr:.4f}) — monotonic signal')
    if duration_s < 10:
        warnings.append(f'Short segment ({duration_s:.1f}s) — minimum 10s recommended')
    
    return {
        'suitable': len(warnings) == 0,
        'rms': rms,
        'silence_ratio': silence_ratio,
        'zcr': zcr,
        'duration_s': duration_s,
        'warnings': warnings,
    }
```

**User-facing behavior:**
- If all segments pass: proceed silently
- If any segment has warnings: display warnings, ask for confirmation or suggest re-recording
- If any segment is critically unsuitable (>50% silence, RMS < 0.001): reject and explain why

**Ideal carrier audio:** Conversational speech, ambient recordings, music, radio — anything with natural variation and background noise. **Worst carriers:** Studio silence, pure tones, heavily compressed low-bitrate recordings.

---

## 17. Operational Security: Memory Hygiene and Temp Files

### 17.1 Zero Temp Files Policy

Cryptomosaic must **never** write intermediate data to disk. Temp files are a critical forensic attack surface: deleted files are recoverable, journaling filesystems log writes, and swap files capture memory contents.

**Policy:** The entire encode and decode pipeline operates in-memory. The only disk operations are: (1) reading the source input, (2) writing the final output fragments. No `/tmp` files, no `tempfile.NamedTemporaryFile()`, no intermediate writes.

```python
# WRONG — creates forensic evidence on disk
with tempfile.NamedTemporaryFile() as tmp:
    tmp.write(plaintext)
    process(tmp.name)

# CORRECT — everything stays in RAM
plaintext_buffer = bytearray(encrypt_and_process(message))
write_final_output(output_path, plaintext_buffer)
secure_zero(plaintext_buffer)
```

### 17.2 Sensitive Data Handling in Python

Python's immutable `bytes` and `str` types cannot be overwritten — the garbage collector frees them at an unpredictable time, and the memory is not zeroed. All sensitive data must use `bytearray` which supports in-place overwriting.

```python
def secure_zero(data: bytearray) -> None:
    """Overwrite bytearray contents with zeros in-place."""
    for i in range(len(data)):
        data[i] = 0

# CRITICAL: Use bytearray for all sensitive material
key = bytearray(get_random_bytes(16))          # AES key
plaintext = bytearray(message.encode('utf-8'))  # Secret text
shares = [bytearray(s) for s in share_bytes]    # Shamir shares

try:
    ciphertext = encrypt(key, plaintext)
    # ... produce fragments ...
finally:
    secure_zero(key)
    secure_zero(plaintext)
    for s in shares:
        secure_zero(s)
```

**Limitations of Python memory security:**
- The Python interpreter may internally copy data during operations (string formatting, concatenation)
- The OS may swap memory pages to disk (`mlock()` via `ctypes` can prevent this on Linux, but requires root or `CAP_IPC_LOCK`)
- GC finalizers run at unpredictable times

These limitations are inherent to Python and acceptable for the threat model. For military-grade memory security, a C/Rust implementation would be needed — but this conflicts with the "readable source that anyone can audit and run in 30 years" principle. The pragmatic trade-off: `bytearray` + `secure_zero()` + no temp files is the best achievable in Python.

### 17.3 Sensitive Data Lifecycle

```
Encode:
  message (bytearray) → [ZERO after AES encrypt]
  key (bytearray)     → [ZERO after Shamir split]
  shares (bytearray)  → [ZERO after writing to .cmf fragments]
  ciphertext (bytes)   → [immutable, but not sensitive — it's encrypted]

Decode:
  shares (bytearray)  → [ZERO after Shamir combine]
  key (bytearray)     → [ZERO after AES decrypt]
  message (bytearray) → [ZERO after displaying to user or writing output]
```

**GUI-specific concerns:**
- Text widgets (QTextEdit) cache displayed text in memory — clear widget content explicitly on window close
- Clipboard: if user copies decrypted text, clear clipboard after a configurable timeout (default: 60 seconds)
- Window title / taskbar must never show message content or fragment details

### 17.4 Audit Checklist (Pre-Release)

| Check | Method |
|-------|--------|
| No temp files created | `strace -e trace=open,openat,creat` during full encode/decode cycle |
| No sensitive data in coredumps | Disable coredumps: `resource.setrlimit(resource.RLIMIT_CORE, (0, 0))` |
| Keys zeroed after use | Unit test: verify `bytearray` contains only zeros after `secure_zero()` |
| No secrets in log output | Grep all log/print statements for key/plaintext variable names |
| No secrets in exception tracebacks | Catch exceptions before they propagate sensitive variable values |
| Clipboard auto-clear | GUI test: verify clipboard is empty after timeout |

---

## 18. Dependency Strategy: Layered Resilience

### 18.1 Philosophy: Defense in Depth Against Dependency Rot

Over 30+ years, any external library may become unavailable, incompatible, or unmaintained. Cryptomosaic uses a **layered dependency model** to ensure decodability under any conditions:

**Layer 1 — Pure Python fallback (zero dependencies):**
Critical components implemented in pure Python using only the standard library. Slower but guaranteed to work on any Python 3.10+ interpreter without pip, without internet, without any external packages.

**Layer 2 — Production mode (optimized libraries):**
PyCryptodome, NumPy, PyWavelets for performance. Used by the AppImage and normal installation. 10–100× faster than pure Python fallbacks.

**Layer 3 — Source archive:**
Complete source code including vendored copies of all dependencies. The `source-1.0.tar.gz` in every distribution set contains everything needed to run the application.

### 18.2 Pure Python Feasibility by Component

| Component | Pure Python feasible? | Complexity | Performance impact | Decision |
|-----------|----------------------|------------|-------------------|----------|
| Shamir SSS | **Yes** | ~60 lines, Lagrange interpolation over GF(p) | Negligible | Implement pure Python as primary |
| ChaCha20 PRNG | **Yes** | ~80 lines, quarter-round operations | Negligible for PRNG use | Implement pure Python as primary |
| AES-256-GCM | **Yes, but risky** | ~400 lines, S-box + Galois field | 50–100× slower | Pure Python fallback, PyCryptodome primary |
| Merkle tree | **Already pure** | ~50 lines, hashlib (stdlib) | N/A | Already pure Python |
| Reed-Solomon | **Yes** (reedsolo is pure Python) | Vendor the ~1000 line reedsolo.py | Negligible | Vendor copy in source archive |
| DWT (wavelets) | **Partially** | Haar: ~30 lines. Daubechies: complex | 100–1000× slower | Pure Python Haar fallback; PyWavelets primary |
| zlib | **Already stdlib** | `import zlib` | N/A | Already pure Python |
| Image I/O | **Limited** | PPM/PGM: ~20 lines. PNG: needs zlib | Only basic formats | PPM fallback; Pillow primary |
| Audio I/O | **Partially** | WAV header: ~50 lines. FLAC: complex | Only WAV supported | WAV reader fallback; soundfile primary |

### 18.3 Implementation Strategy

```
cryptomosaic/
├── core/                    Pure Python implementations (Layer 1)
│   ├── sss_pure.py          Shamir SSS — Lagrange over GF(p), ~60 lines
│   ├── chacha20_pure.py     ChaCha20 PRNG — quarter-round, ~80 lines
│   ├── aes_gcm_pure.py      AES-256-GCM fallback — ~400 lines
│   ├── merkle.py            Already pure Python (hashlib)
│   ├── wav_io.py            WAV read/write — struct-based, ~50 lines
│   └── dwt_haar.py          Haar wavelet DWT — basic but functional, ~30 lines
│
├── fast/                    Optimized wrappers (Layer 2)
│   ├── sss_fast.py          PyCryptodome Shamir (delegates to core/ if unavailable)
│   ├── chacha20_fast.py     PyCryptodome ChaCha20 (delegates to core/)
│   ├── aes_gcm_fast.py      PyCryptodome AES-GCM (delegates to core/)
│   └── dwt_fast.py          PyWavelets DWT (delegates to core/dwt_haar.py)
│
├── vendor/                  Vendored dependencies (Layer 3)
│   └── reedsolo.py          Reed-Solomon, MIT licensed, ~1000 lines
│
└── compat.py                Auto-detection: try fast/, fall back to core/
```

```python
# compat.py — transparent fallback
try:
    from cryptomosaic.fast.aes_gcm_fast import encrypt, decrypt
except ImportError:
    from cryptomosaic.core.aes_gcm_pure import encrypt, decrypt
    import warnings
    warnings.warn("Using pure Python AES-GCM (slower). Install PyCryptodome for better performance.")
```

**CLI flag:** `--pure-python` forces Layer 1 even when Layer 2 is available. Useful for testing and verification.

---

## 19. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] Create Codeberg repository `hiltsu/cryptomosaic`
- [ ] Write README with concept description (bilingual FI/EN)
- [ ] Audit Cryptoleaf spread-spectrum PRNG usage (identify MT/PCG dependencies)
- [ ] Implement pure Python core: ChaCha20 PRNG, Shamir SSS (two-half AES-256 split), Merkle tree
- [ ] Implement `.cmf` binary format v1 (read/write with struct module, HMAC-SHA256 header)
- [ ] Implement defensive `.cmf` parser with all validation checks (share index validation)
- [ ] Implement AES-256-GCM wrapper with per-fragment ciphertext randomization
- [ ] Implement image tile fragmentation and reassembly
- [ ] Implement audio segment fragmentation and reassembly
- [ ] Input validation: lossy auto-convert, minimum sizes, bit-perfect roundtrip assert
- [ ] `compat.py` auto-detection layer (fast/ vs. core/ fallback)

### Phase 2: Core Pipeline (Week 2–3)
- [ ] Integrate Cryptoleaf DWT engine (copy modules initially)
- [ ] Full encode pipeline: message → AES-256-GCM → DWT embed → fragment → .cmf files
- [ ] Full decode pipeline Path B: .cmf files → SSS reconstruct → de-randomize CT → AES-GCM decrypt
- [ ] Full decode pipeline Path A: .cmf files → reassemble → DWT extract → AES-GCM decrypt → message
- [ ] Per-fragment Reed-Solomon FEC (encode + decode + correction before hash verify)
- [ ] Optional zlib compression (encode + transparent decode)
- [ ] CLI interface: `cryptomosaic encode` / `cryptomosaic decode`
- [ ] Empirical steganalysis testing: validate DWT parameters with Aletheia/StegExpose

### Phase 3: Verification & UX (Week 3–4)
- [ ] Fragment integrity verification (per-fragment hash + Merkle + chain)
- [ ] Session validation (matching session IDs, threshold checks)
- [ ] All edge case handling and user-facing error messages (mode-dependent: Section 11.7)
- [ ] Memory hygiene: bytearray everywhere, secure_zero(), no temp files (Section 17)
- [ ] Operational security audit: strace verification, no secrets in logs/tracebacks
- [ ] Fuzz testing: Hypothesis property-based tests for .cmf parser (Section 16.5)
- [ ] Audio carrier quality analysis for wrapped mode (Section 16.6)
- [ ] Basic Qt6 GUI (drag-and-drop fragment collection, grid preview)
- [ ] GUI: clipboard auto-clear, widget content zeroing on close
- [ ] GUI warning when saving all fragments to same directory
- [ ] Test suite (pytest + Hypothesis): roundtrip tests, edge cases, corruption simulation

### Phase 4: Packaging & Release (Week 4+)
- [ ] AppImage build (Nuitka, Ubuntu 22.04 LTS base)
- [ ] Windows .exe build (Nuitka standalone)
- [ ] SPECIFICATION.txt for .cmf format (standalone, included in distribution sets)
- [ ] Distribution set template (fragment + spec + AppImage + source archive)
- [ ] Cryptoleaf-core extraction planning (shared library refactor, post-MVP)

### Future Enhancements (post-release)
- [ ] Wrapped mode: fragments embedded in audio/images via Cryptoleaf (`--wrapped`)
- [ ] Wrapped mode audio auto-segmentation from single long recording
- [ ] Feldman Verifiable Secret Sharing (VSS) — prevents dealer cheating
- [ ] Session-level Reed-Solomon erasure coding (Path A becomes truly k-of-n)
- [ ] Time-lock: `unlock_after` timestamp with software enforcement
- [ ] Fragment expiration: `expires_at` timestamp ("do not decrypt after")
- [ ] Passphrase-derived key mode (Argon2id KDF, key lives in user's memory)
- [ ] Deterministic fragment ordering via seeded permutation
- [ ] Optional binary payload mode (with format longevity warnings)
- [ ] Post-quantum hybrid encryption: AES-GCM + ML-KEM (Kyber) (research)
- [ ] Per-fragment watermarking for provenance tracking
- [ ] GUI: visual mosaic preview showing which fragments are present/missing
- [ ] Cryptographic time-lock puzzles (research)

---

## 20. Dependencies

### Layer 2 — Production (optimized, in AppImage)

| Package | Version | Purpose | Pure Python fallback? |
|---------|---------|---------|----------------------|
| Python | ≥ 3.10 | Runtime | — |
| PyCryptodome | ≥ 3.20 | AES-256-GCM, Shamir SSS (two-half), ChaCha20 | Yes (`core/aes_gcm_pure.py`, `core/chacha20_pure.py`) |
| NumPy | ≥ 1.24 | Array operations, media data | Partial (basic list operations, much slower) |
| Pillow | ≥ 10.0 | Image I/O, format validation | Partial (PPM/PGM only via `core/wav_io.py`) |
| PyWavelets | ≥ 1.4 | DWT embedding (from Cryptoleaf core) | Partial (Haar wavelet only via `core/dwt_haar.py`) |
| reedsolo | ≥ 1.7 | Reed-Solomon FEC | Vendored (`vendor/reedsolo.py`, pure Python) |
| PySide6 | ≥ 6.5 | GUI (optional) | No — CLI mode does not require GUI |
| Nuitka | ≥ 2.0 | AppImage / .exe packaging | No — build-time only |

### Layer 1 — Pure Python core (zero external dependencies)

| Module | Lines | Purpose |
|--------|-------|---------|
| `core/sss_pure.py` | ~60 | Shamir SSS, Lagrange interpolation over GF(p) |
| `core/chacha20_pure.py` | ~80 | ChaCha20 PRNG, RFC 7539 quarter-rounds |
| `core/aes_gcm_pure.py` | ~400 | AES-256-GCM fallback (S-box + Galois field) |
| `core/merkle.py` | ~50 | Merkle tree + chain (hashlib stdlib) |
| `core/wav_io.py` | ~50 | WAV read/write (struct stdlib) |
| `core/dwt_haar.py` | ~30 | Haar wavelet DWT (basic, no NumPy) |
| `vendor/reedsolo.py` | ~1000 | Reed-Solomon FEC (vendored, MIT license) |

### Standard library (always available)

`zlib`, `hashlib`, `struct`, `uuid`, `math`, `os`, `tracemalloc`

### Development / testing dependencies

| Package | Purpose |
|---------|---------|
| pytest | Test runner |
| hypothesis | Property-based fuzz testing |
| python-afl | Mutation fuzzing (CI/CD) |
| tracemalloc | Memory leak detection |

**Note:** `--pure-python` CLI flag forces Layer 1 even when Layer 2 is available. In pure Python mode, Path B decoding (header-only) works with full AES-GCM security. Path A (DWT extraction) is limited to Haar wavelet and basic image formats.

---

## 21. Design Decisions Log

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| Q1 | Grid dimensions | User-controlled with defaults (2×2 / 3×3 / 4×4) | Avoid overengineering; sensible defaults cover 90% of use cases |
| Q2 | Threshold independence | Resolved via dual decode paths (A + B) | Path B makes (k,n) functional immediately; Path A requires all n |
| Q3 | Partial media reconstruction | Path B: ciphertext in every header | MVP solution; session-level RS erasure coding for Path A planned post-release |
| Q4 | Mixed media | One media type per session | Mixed media complicates reassembly for no practical benefit |
| Q5 | Compression | Raw default, optional zlib | zlib chosen over lz4 for decades-long format universality (RFC 1951) |
| Q6 | Max fragment count | n ≤ 16 | Cold storage logistics; 16 USB sticks is already a significant distribution effort |
| Q7 | AES key size | AES-256-GCM default (two-half Shamir split) | 128-bit post-quantum security; two-half split adds minimal complexity; cold storage demands it |
| Q8 | Merkle tree library | Custom (~50 lines) | Fragment count too small (4–16) to justify external dependency |
| Q9 | Header encryption | Not implemented | Header is metadata, not secret; Shamir shares are useless individually |
| Q10 | FEC strategy | Per-fragment RS (10% overhead) | Protects against NAND bit-rot; uses existing reedsolo dependency |
| Q11 | AES mode | GCM (authenticated) over CBC | Red-team: poisoned fragments cause silent wrong-key decrypt with CBC; GCM detects immediately |
| Q12 | Forensic stealth | Wrapped mode via Cryptoleaf (replaces v3 stealth mode) | Embeds .cmf inside carrier audio/image; cleaner than dual-stego-layer approach |
| Q13 | Parser security | Defensive parsing with all field validation | Red-team: malicious fragments could exploit parser; validate before allocating |
| Q14 | Time-lock | Software timestamp (MVP future); crypto puzzles (research) | Software lock is "honest party" only but useful with k-of-n; crypto lock is complex |
| Q15 | Lossy input | Auto-convert with warning (MVP); reject if `--strict` | Lossy→lossless conversion (JPG→PNG) is trivial and improves UX |
| Q16 | Payload type | UTF-8 text only (MVP); optional binary (future) | Text is universal, compact, format-immortal; binary risks format obsolescence |
| Q17 | Semantic encodings | Rejected (word vectors, embeddings) | Model-dependent representations violate time capsule principle |
| Q18 | Wrapped mode carrier | Audio default (WAV), image optional | Audio has 26× more DWT capacity, psychoacoustic masking, natural cover story |
| Q19 | Carrier sourcing | Auto-segment from one long recording | Solves "n different carriers" problem; natural uniqueness prevents correlation |
| Q20 | Three encode modes | Standard + Lightweight + Wrapped | Each optimizes for different trade-off (capability vs. size vs. stealth) |
| Q21 | Deterministic PRNG | ChaCha20 keystream (RFC 7539) | Language-built-in PRNGs (MT, PCG) differ across platforms/versions; ChaCha20 is RFC-frozen, universally implemented |
| Q22 | PRNG seed derivation | HKDF(key, session_id) | Seed derived from AES key — no separate storage needed; deterministic from Shamir-reconstructed key |
| Q23 | Test vectors | Required in SPECIFICATION.txt | Enables reimplementation in any language 30+ years from now; verified correctness |
| Q24 | Passphrase mode | Argon2id KDF (future) | Memory-hard, RFC 9106 standardized; key lives in user's memory, not on media |
| Q25 | Error behavior | Mode-dependent: clear errors (standard), silent fail (wrapped), deterministic garbage (passphrase) | Prevents error oracle attacks; deniability in wrapped mode; anti-brute-force in passphrase mode |
| Q26 | Lossy input handling | Auto-convert to lossless (JPEG→PNG, MP3→WAV) with warning | Improves UX; conversion is trivial via Pillow/ffmpeg; `--strict` rejects lossy outright |
| Q27 | Fuzz testing | Hypothesis (primary), python-afl (CI/CD) | Property-based testing finds edge cases smarter than random mutation; pytest integration |
| Q28 | Pure Python fallbacks | Layered: core/ (pure) + fast/ (optimized) + vendor/ (reedsolo) | 30-year decodability requires zero-dependency fallback; `--pure-python` CLI flag |
| Q29 | Temp files | Zero temp files — entire pipeline in-memory | Temp files are forensic evidence; no `/tmp` usage, no intermediate disk writes |
| Q30 | Memory hygiene | bytearray + secure_zero() for all sensitive data | Python limitation: immutable bytes/str cannot be zeroed; bytearray is best achievable |
| Q31 | Audio carrier quality | Pre-embedding RMS/silence/ZCR analysis with warnings | Silent audio segments provide poor DWT cover; warn user before embedding |
| Q32 | Ciphertext correlation | Per-fragment randomization: Ci = C ⊕ ChaCha20(KDF(K,i)) | Eliminates cross-fragment byte correlation; negligible cost; does not break Path B |
| Q33 | Header integrity | HMAC-SHA256 truncated to 8 bytes (keyed with session ID) | CRC-32 is trivially forgeable; HMAC prevents header tampering by adversary without session ID |
| Q34 | Verifiable Secret Sharing | Share index validation (MVP); Feldman VSS (post-MVP) | GCM auth tag catches wrong keys; Feldman adds dealer-cheating protection but increases complexity |
| Q35 | Steganalysis validation | Empirical testing with Aletheia/StegExpose pre-release | CNN steganalysis is improving; must validate DWT parameters against real classifiers |
| Q36 | Wrapped mode versioning | Cryptoleaf version + DWT params in SPECIFICATION.txt + self-test fragment | Wrapped mode depends on Cryptoleaf; version drift could make fragments unextractable |
| Q37 | Security guarantees | Computational (AES) + information-theoretic (SSS) + heuristic (DWT stego) | Steganographic security is not formally provable; document explicitly |

---

*This document serves as the preparatory research foundation for Cryptomosaic development. All major design decisions have been resolved (37 logged). External security review integrated: AES-256-GCM default, per-fragment ciphertext randomization, HMAC header integrity, share validation, empirical steganalysis requirement. Combined with ChaCha20 PRNG, layered pure-Python fallbacks, memory hygiene, and fuzz testing strategy. Implementation can begin with Phase 1.*
