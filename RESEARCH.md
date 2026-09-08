# Reducing stpp/IMSC overhead in low-latency fragmented MP4

Research notes on approaches for reducing per-fragment overhead of IMSC1/TTML
subtitle streams carried in ISOBMFF `stpp` tracks when fragments are very short
(e.g. 250 ms or less for low-latency CMAF).

## 1. Problem

ISO/IEC 14496-30 §5.6 requires that each TTML sample is a complete, self-contained
XML document. For IMSC1, this document carries the full `<tt>`/`<head>` (styling,
layout, metadata) plus a `<body>` containing the timed `<p>` elements active in
the sample's interval.

For typical broadcast subtitles, the static layout/styling portion is roughly
1–2 kB while the dynamic body content is often tens of bytes (or empty). At
normal segment durations (1–5 s) this is tolerable. For low-latency CMAF chunks
of 200–500 ms, the bitrate is dominated by repeated boilerplate:

- A 2 s segment split into 10 chunks: ~10 kbps → ~100 kbps, with 10× the XML
  parsing cost on the receiver.

The DASH-IF Low-Latency Live Community Review (CR-Low-Latency-Live-r8)
acknowledges this and recommends **not** chunking subtitles below ~1 s; instead,
deliver them as separate segments at ~1 s cadence. That avoids the bitrate
explosion but caps the achievable subtitle latency.

## 2. What the relevant standards currently provide

### 2.1 ISO/IEC 14496-30:2018 (`stpp`)

- §5.6 — each sample is a complete TTML XML document.
- §5.9 "Document temporal boundaries":
  - §5.9.3: "If a sample contains the identical document to the prior sample,
    it **may be marked as redundant**." The marking is 14496-12 §8.6.4's
    `sample_has_redundancy = 1` together with `sample_depends_on = 2`, in
    `sdtp` or in the fragment sample flags; §8.6.4 lets a receiver of a
    non-audiovisual track discard such a sample and add its duration to the
    previous one. Only helps when the document is byte-identical. In live it
    never fires today only because packagers clip `begin`/`end` to the
    segment; §5.9(1) permits a begin time outside the fragment, and unclipped
    restated documents are identical (see `DESIGN-ll-paint-model.md` §3.2).
- §4.4 "Resources shared by multiple samples" — common items (fonts, images)
  may be stored in a `meta` box and referenced by URI from the XML. This is
  the *only* existing in-spec mechanism for sharing across samples, and it
  only covers binary auxiliary items, not XML content.
- §5.6 Sub-samples — a sample can be split into sub-samples (`subs` box) used
  for images referenced from the XML. The XML doc is always sub-sample 0.

### 2.2 ISO/IEC 14496-12:2022 (ISOBMFF)

- §8.19 **Compressed boxes** (`!cmov`, `!cmof`, `cmfm`, `cmfs`): deflate
  compression applied to whole `moov`, `moof`, `sidx`, `ssix` boxes.
  Standardized but compresses each container independently — no shared state
  across fragments. Does not apply to `mdat` sample payloads.

### 2.3 ISO/IEC 23001-17:2024/Amd 2:2025

"Generic compression for samples and items in ISOBMFF." Newest relevant work.
Applicable to *any* sample type including XML/`stpp`. Worth investigating
whether it permits external/shared dictionaries (the spec was not directly
accessible during this research).

### 2.4 IMSC 1.3 (W3C)

- `ittp:progressivelyDecodable` (status: permitted-deprecated) — structures a
  document so it can be presented before fully received. Requirements: no
  timing in `<head>`, paragraphs in temporal order, no forward references, no
  timing on descendants of `<p>`. Conceptually relevant to streaming but not
  designed for fragment-level delta encoding.
- **Intermediate Synchronic Document (ISD)** — a temporally bounded subset of
  a TTML document during which no element changes active/inactive state. A
  TTML document is conceptually a sequence of ISDs. This is the core concept
  DVB-TTML builds on.

### 2.5 ETSI EN 303 560 (DVB-TTML)

This is the most directly relevant published spec, although it targets MPEG-2
Transport Stream rather than ISOBMFF.

Key concepts (§5.2.3):

- **TTML document chunk**: a self-contained, temporally bounded subset of a
  TTML document. "Self-contained" means all elements needed to render the
  subset are present (except fonts).
- **TTML segment**: the PES payload — an XML serialization of a TTML document
  chunk, optionally gzip-compressed.
- **segment_mediatime** (48-bit, 100 µs units): maps the segment's wire PTS
  onto a point on the original TTML internal timeline. This separates wire
  timing from authored timing, so each chunk can retain the source TTML
  `begin`/`end` values.
- **Segment types** (Table 17):
  - `0x01` uncompressed TTML document,
  - `0x02` **gzip-compressed TTML document** (RFC 1952).
- **Maximum Period of Activation (MPA)** = 5 s — a single segment stays active
  no longer than 5 s without a follow-up.
- **Continuation across boundaries** (§5.2.3.6): if a subtitle spans a chunk
  boundary, the element appears in *every* chunk it overlaps, with possibly
  different (provisional) timing.
- **Empty segment** for "no subtitles right now":
  `<tt xml:lang="" xmlns="http://www.w3.org/ns/ttml" />` — fits a single
  188-byte TS packet.

Critically, DVB-TTML does **not** define a delta/template mechanism. Each chunk
is a standalone XML document; the optimisation comes from (a) only including
the ISDs that overlap the chunk's active period and (b) gzipping the result.

### 2.6 EBU-TT Live (EBU Tech 3370)

A node-to-node production protocol, not a delivery optimization. Documents are
grouped into sequences via `sequenceIdentifier` + `sequenceNumber`, but each
document on the wire is a complete EBU-TT Part 1 document — no deltas, no
templating across documents.

### 2.7 14496-30 WebVTT carriage (§6) — relevant precedent

WebVTT in stpp/wvtt deliberately *deconstructs* cues:

- WebVTT header (everything before the first cue) goes in the `vttC` box
  inside the **sample entry**.
- Each sample contains zero or more `VTTCueBox` (`vttc`) boxes, each carrying
  separate `iden`/`payl`/`sttg`/`ctim` sub-boxes.
- Empty intervals use `vtte`.

This is precisely the "header in sample entry, body in samples" pattern that
could be transplanted to TTML — but no equivalent exists today for `stpp`.

### 2.8 DASH-IF guidance

DASH-IF CR-Low-Latency-Live (current published draft):

- Subtitles should not be chunked at the same fine granularity as audio/video.
- Recommend ≥ 1 s subtitle segments delivered as full segments (no `moof/mdat`
  chunking) to avoid XML overhead amplification.
- No proposal for delta/template encoding.

## 3. Approaches surveyed

In rough order from "off-the-shelf, no spec change" to "needs a new spec."

### A. Mark identical samples redundant

**What:** Use 14496-30 §5.9.3 — when a fragment's document is byte-identical
to the previous one, mark it redundant.

**Pros:** Already standardized; trivial to implement.

**Cons:** Only helps when the document is byte-identical. Today's packagers
clip `begin`/`end` to the segment, so live documents almost never are — but
nothing requires the clipping: 14496-30 §5.9(1) permits a begin time outside
the fragment and DVB-DASH (TS 103 285 §11.7) says truncation is unnecessary.
With unclipped, open-ended documents every restatement is identical, the flag
fires, and the receiver skips the parse. The saving is parses, not bytes: the full XML wire
overhead is still paid per fragment.

### B. Per-sample gzip / deflate of the sample payload

**What:** Compress each `stpp` sample's XML before wrapping it as `mdat`
content. Mirror DVB-TTML's `segment_type` 0x02.

**Pros:** Strong precedent (DVB-TTML); simple decoder change.

**Cons:** Not standardized for `stpp` — would be a private convention. Each
sample is compressed independently, so the dictionary cost is paid in every
fragment. For very short fragments, gzip's window has too little redundancy
to exploit; ratios drop.

### C. ISOBMFF Compressed boxes (14496-12 §8.19)

**What:** Wrap fragments in `cmof`/`cmfs` to apply deflate over the entire
`moof`+`mdat`.

**Pros:** Standardized; orthogonal to sample format.

**Cons:** Still compresses each fragment independently. Same dictionary
problem as B. Decoders that don't implement §8.19 cannot read the stream.

### D. ISO/IEC 23001-17 Amd 2 — Generic sample compression

**What:** Use the new "Generic compression for samples and items in ISOBMFF"
mechanism (2025) to compress sample payloads.

**Pros:** Standardized for arbitrary sample types; future-proof signalling.

**Cons:** Newest spec, limited deployed support. Need to verify whether it
permits external / shared dictionaries.

### E. Shared-dictionary compression across fragments

**What:** Use Brotli or zstd with a shared dictionary that contains the static
parts of the IMSC document (the `<head>` block, repeated `<div>` boilerplate,
common region/style IDs). The dictionary is delivered out-of-band (e.g. as a
URL referenced by the MPD) or carried inside the first fragment / sample entry.

Two delivery models:

1. **Transport-layer** — HTTP Compression Dictionary Transport (RFC 9842,
   Chromium 2024) compresses the segment HTTP responses with a shared
   dictionary. No change to `stpp` bytes on disk; the wire saves dramatically.
   Works with chunked transfer for CMAF.
2. **In-band** — a new ISOBMFF brand/box that carries a per-track Brotli or
   zstd dictionary in the sample entry. Samples are stored compressed and
   reference the dictionary.

**Pros:** Near-template behaviour at the byte level. Model 1 requires no
14496-30 change at all. Compression ratios for repeated IMSC docs against a
matching dictionary are typically > 20:1.

**Cons:** Model 1 needs HTTP-layer support across the CDN; Model 2 needs a new
ISOBMFF brand. Decoders must run a decompressor before XML parsing.

### F. Sample-entry-as-template + body-only samples (WebVTT-style)

**What:** Apply the WebVTT pattern (§2.7) to TTML. Define a new sample entry
variant (e.g. brand `stpi`, new sample-entry box `imsH`) that carries the
static IMSC `<head>` (and optionally an empty `<body>` skeleton with the
common `<div>` structure). Each sample carries only the changing payload — a
sequence of `<p>` elements, or a compact box-based representation of them.

Decoder reconstitutes a full IMSC document by splicing the sample-entry head
with the sample body.

**Pros:** Cleanest "I-fragment + P-fragment" mapping. Reuses an existing
pattern in 14496-30 (WebVTT). Per-sample payload can be tiny (often < 100 B).
Optionally still works as XML if the body is serialised as XML, or can use
a binary box form for parser speed.

**Cons:** Requires a new brand and an extension to 14496-30. Existing `stpp`
decoders cannot read it. Layout changes mid-track require a sample-entry
switch (`stsd` change), which fmp4 already supports via per-fragment
`sample_description_index`.

A pragmatic sub-variant: put the head in the sample entry but keep the
per-sample payload as a normal IMSC document with an *empty* `<head>` (or
referring back to the sample entry by ID). Then a permissive decoder can
process samples as standalone IMSC if it copies the head in.

### G. Template + binary delta

**What:** Define a sample-entry-resident IMSC template with named placeholders
(e.g. `{{p1.text}}`, `{{p1.begin}}`). Each sample carries a compact binary
record of placeholder → value bindings. Decoder substitutes into the template
and feeds the result to the IMSC renderer (or directly to its ISD layer).

**Pros:** No XML parsing per-fragment on the receive path. Very small
per-fragment payloads. Easy to author from a fixed broadcaster style.

**Cons:** Most invasive — needs a new sample format, no existing W3C/MPEG
proposal, breaks compatibility with anything that expects XML samples. Limits
authoring flexibility (must fit the template).

### H. XML diff / patch (XCC, RFC 5261, vcdiff/xdelta)

**What:** First fragment carries full IMSC; subsequent fragments carry an XML
patch.

**Pros:** Conceptually clean.

**Cons:** Patch application still requires XML parsing of both base and patch
on the receive path, undermining the parser-cost argument. Need to define
checkpoint/recovery semantics for join points. No existing standard for this
in subtitle delivery.

## 4. Comparison

| Approach | Spec change | Wire savings | Parser cost | Implementation |
|---|---|---|---|---|
| A. Redundant flag | None | None (signalling only) | Skip parse and render on every restatement, if the packager stops clipping | Trivial |
| B. Per-sample gzip | Convention | Medium (poor on small samples) | Decompress + parse | Easy |
| C. `cmof` compressed moof/mdat | None | Medium | Decompress + parse | Moderate |
| D. 23001-17 Amd 2 generic | None | Medium–High | Decompress + parse | Moderate |
| E1. HTTP shared-dict (Brotli/zstd) | None (transport) | **High** (≫ 10×) | Decompress + parse | Moderate (CDN-side) |
| E2. In-band shared-dict | New brand | **High** | Decompress + parse | Moderate |
| F. Sample-entry head + body samples | New brand/box | **High** | Light XML or box parsing | Moderate (matches WebVTT precedent) |
| G. Template + binary delta | New sample format | **Very high** | No XML parsing | Significant |
| H. XML diff/patch | New convention | Medium–High | Full XML on both ends | Significant |

## 5. Findings on existing publications

There does not appear to be a published proposal that specifically addresses
"I-fragment + delta P-fragments" for `stpp`/IMSC in fragmented MP4. The
landscape:

- DASH-IF: workaround (don't chunk small) rather than solution.
- DVB-TTML: solves the related TS broadcast problem with standalone gzipped
  chunks; not applicable to ISOBMFF directly but its `segment_mediatime`
  pattern is reusable.
- W3C TTWG (Timed Text Working Group): IMSC progressive decoding deprecated;
  no delta encoding work active.
- MPEG SC 29: no public input documents matching this scope found in 2024–2026
  meeting outputs surveyed.

This suggests there's room for a contribution — to MPEG (14496-30 amendment),
DASH-IF (a CMAF/DASH packaging note), or W3C TTWG (an IMSC streaming profile).

## 6. Recommended next steps

For minimum standards work and immediate deployability:

1. **Stop clipping `begin`/`end` to the segment and mark identical samples
   redundant (approach A).** Zero spec change; turns the redundancy flag into a
   real parse-rate reduction. See `DESIGN-ll-paint-model.md` §3.2.

2. **Approach E1 (HTTP shared-dictionary)** for production deployment in
   environments where the CDN supports `compression-dictionary` (modern
   Chromium, growing CDN coverage). No bytes on disk change. Pair the
   dictionary with the IMSC document carried in the first fragment of the
   period (or a separately published representation referenced from the MPD).

3. **Approach B (per-sample gzip)** as a transitional/private convention if E1
   isn't deployable. Signal via a custom brand or sample-entry parameter.

For a standards contribution path:

4. **Approach F (sample-entry head + body samples)** is the natural extension
   because:
   - 14496-30 already does this for WebVTT — clear precedent.
   - DVB-TTML provides the timeline-mapping pattern (`segment_mediatime`).
   - Compatible with the IMSC ISD model.

   A draft would define:
   - A new brand (e.g. `imsc`/`imsf`) signalling fragmented IMSC.
   - A new sample-entry box carrying the static `<head>`. Times stay on the
     track timeline; the packager simply does not clip them to the segment
     (see `DESIGN-ll-paint-model.md` §3.2).
   - Sample format options: (a) IMSC document with empty/elided head;
     (b) box-structured representation of `<p>` elements similar to `vttc`.
   - Continuation semantics across fragments (mirror DVB-TTML §5.2.3.6).

## 7. References

### Standards (not included in this repository)

ISO/IEC documents are copyrighted and must be obtained from ISO. ETSI and W3C
documents are publicly available.

- ISO/IEC 14496-30:2018 — Timed text and other visual overlays in ISO base media
  file format
- ISO/IEC 14496-12:2022 — ISO base media file format
- ISO/IEC 23000-19 — Common media application format (CMAF) for segmented media
- ETSI EN 303 560 V1.1.1 (DVB-TTML): https://www.etsi.org/deliver/etsi_en/303500_303599/303560/01.01.01_60/en_303560v010101p.pdf
- W3C IMSC 1.0.1 (TTML Profiles for Internet Media Subtitles and Captions): https://www.w3.org/TR/ttml-imsc1.0.1/
- DASH-IF Low-Latency Live Community Review r8: https://dashif.org/docs/CR-Low-Latency-Live-r8.pdf

### External
- ETSI TS 103 285 V1.4.1 (DVB-DASH): https://www.etsi.org/deliver/etsi_ts/103200_103299/103285/01.04.01_60/ts_103285v010401p.pdf
- W3C IMSC 1.3 (current): https://w3c.github.io/imsc/imsc1/spec/ttml-ww-profiles.html
- W3C IMSC Hypothetical Render Model: https://www.w3.org/TR/imsc-hrm/
- EBU Tech 3370 (EBU-TT Part 3 Live): https://tech.ebu.ch/publications/tech3370
- EBU Tech 3381 (Carriage of EBU-TT-D in ISOBMFF): https://tech.ebu.ch/publications/tech3381
- ISO/IEC 23001-17:2024/Amd 2:2025 (Generic compression in ISOBMFF): https://www.iso.org/standard/89120.html
- HTTP Compression Dictionary Transport (RFC 9842, 2024): https://www.rfc-editor.org/rfc/rfc9842.html
- RFC 8759 (RTP payload for TTML): https://www.rfc-editor.org/rfc/rfc8759.html
