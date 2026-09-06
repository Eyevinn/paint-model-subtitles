# Paint-model subtitles: the design

Low-latency carriage of text subtitles (`stpp`/IMSC and `wvtt`) in CMAF over LL-DASH,
LL-HLS and MoQ (Media over QUIC). This is the short version. The full notes, with
rationale, budgets and open questions, are in
[`DESIGN-ll-paint-model.md`](DESIGN-ll-paint-model.md); mechanisms considered and left
out are in [`ALTERNATIVES.md`](ALTERNATIVES.md); the prototype and test plan is in
[`PROTOTYPE.md`](PROTOTYPE.md).

**In four points**

1. **Paint model: signal changes when they happen.** A document is sent when a cue
   appears, changes, or is cleared, and at no other time. The packager never waits for,
   guesses, or invents an end time.
2. **Allow frequent no-update signalling.** Keep the regular part or chunk cadence the
   player needs, and when nothing has changed say so in 8 bytes instead of repeating the
   document.
3. **Make TTML intervals in `stpp` open-ended.** A cue keeps its true `begin` and has no
   `end` until it is cleared, and a document stays active until the next one supersedes
   it. The first is already permitted by ISO/IEC 14496-30; the second is the one change
   to it.
4. **New no-change signalling for `stpp` and `wvtt`.** An empty 8-byte box as the sample,
   under a new sample entry so that legacy players never select the track.

The cadence is then a continuum, not a choice between whole segments and a document per
frame: the subtitle track follows the video down to individual frame fragments, at 8
bytes per unchanged fragment. What bounds the cadence differs by transport (§2.1, §7).
LL-HLS is bounded by requests — a playlist reload and a part fetch per part — so 250 ms
parts are the sensible match there. LL-DASH streams the chunks of a segment in one
response and is bounded only by the ~100 B CMAF chunk header, which a LOCMAF-style (Low
Overhead CMAF) compact chunk head could cut to ~10 B. Over MoQ with LOCMAF that is the
native form: a frame-level subtitle update costs ~10 B and a track at 25 fps ~2 kbps.

## 1. The problem

Low-latency CMAF delivers video in 20–40 ms chunks inside 2 s segments. ISO/IEC 14496-30
requires every `stpp` sample to be a complete TTML document, so chunking subtitles the
same way costs ~2.5 kB and one XML parse per chunk: ~330 kbps and 25 parses per second
for content that changes about once a second. Not chunking them, the DASH-IF advice,
leaves subtitles up to a segment behind video, and in players that gate on the slowest
track it holds video and audio back too. Today there is nothing in between: a whole
segment, or a full document per frame.

The live sources — teletext, DVB subtitles, CTA-608/708, live captioning — are
paint-model: a cue is shown until replaced or erased, and its end is unknown when it
starts. ISOBMFF timed text is interval-model: a document lives exactly as long as its
sample. Converting between the two forces the packager to invent an end time, and in
practice to restate an unchanged cue in every chunk. That restatement is the cost.

## 2. The design

### 2.1 Four kinds of sample

| Sample | Sent when | Payload | Meaning |
|---|---|---|---|
| **I-sample** | first in every segment | complete document | current state, for tune-in |
| **P-sample** | a cue appears or changes | complete document, or body only (§5) | new state supersedes the old |
| **Clear** | a cue is erased | a document giving the cue its `end`, or an empty document / `vtte` | nothing on screen |
| **No-change** | every other part or chunk | 8-byte box | the active document continues |

The cadence is regular and matched to the video part or chunk cadence, whatever that is:
250 ms LL-HLS parts, 100 ms LL-DASH chunks, or individual frames over MoQ (§7). LL-HLS
requires a part every part target duration, and over HTTP the cadence is the only signal
that the track is still alive; a subtitle track coarser than video also becomes the
latency floor for players that wait for every track. Every part carries at least one
sample with a real, non-zero duration, so the timeline tiles exactly and every CMAF
timing rule holds.

A change lands at its true time, not quantised to the part grid, and `stpp` needs
nothing new for that: one document per part, as today, with the cue's `begin` or `end`
at the exact time inside the part. `wvtt` has no internal timing, so there the part is
split into a no-change sample up to the change and a cue sample from it, for the cost of
one extra `trun` entry. The packager may cap the content update rate — 2 to 4 documents
per second is plenty for word-by-word captioning — by holding a change until the cap
allows. That is policy and needs no signalling.

### 2.2 Worked example

2 s segments, 250 ms parts. Nothing is on screen at 10.00. A cue appears at 10.30 with an
unknown end and is cleared at 13.10.

| Part at | Content |
|---|---|
| 10.00 | I-sample: empty document |
| 10.25 | P-sample: `<p begin="10.3s">…</p>`, no `end` — the cue appears 50 ms into the part, placed by its own `begin` |
| 10.50 – 11.75 | six no-change samples, 8 B each — the cue stays up |
| 12.00 | I-sample: the same document, byte for byte; may be marked redundant |
| 12.25 – 12.75 | no-change |
| 13.00 | P-sample: `<p begin="10.3s" end="13.1s">…</p>` — the end is known when the part is written, so it is written; after 13.10 the document shows nothing |
| 13.25 – 13.75 | no-change |

Every part carries exactly one sample, as `stpp` does today; the changes at 10.30 and
13.10 are placed by the documents' own timing. The cue's `end` is written only once it
is known: absent at 10.25, present at 13.00. The I-sample at 12.00 has a begin time
outside its own segment, which §3 shows is permitted, and the same bytes as the sample
at 10.25, so a receiver already holding it skips the parse. A receiver tuning in at
12.00 parses it and shows the cue. A `wvtt` track would instead split the parts at 10.25
and 13.00 into a no-change or empty sample and a cue sample, since its timing lives only
in the sample table.

## 3. Open-ended intervals in `stpp`

Two rules. One is already permitted; the other is the change.

**Keep the true `begin`, and omit `end` while it is unknown.** 14496-30 §5.9(1) permits
a begin time outside the fragment. §5.9(3) permits the same content in adjacent samples
and lets an identical document be marked redundant. EBU Tech 3381 §6 requires content
overlapping the sample to be present; DVB-DASH (TS 103 285) §11.7 says times need not be
truncated; CMAF adds nothing. Only packager habit clips `begin` and `end` to the segment,
and that clipping is what makes consecutive payloads differ. Unclipped, a restated cue is
byte-identical, the redundancy flag fires, and the receiver skips the parse.

**A document stays active until the next document, or until the maximum period of
activation (MPA) expires.** Today §5.9(4) confines a document to its sample's duration.
The change: the active period ends at the composition time of the next content sample,
or T_MPA after the last sample of any kind, whichever is earlier. T_MPA is carried in
the sample entry, 5 s as in DVB-TTML. No-change samples reset the MPA timer without
superseding. This is ETSI EN 303 560 §5.2.3.3 ported from MPEG-2 TS to ISOBMFF, and RFC
8759 §6 has the same rule for TTML over RTP. For every existing track, where samples
tile the timeline, the rule gives exactly today's behaviour.

A document with internal timing still plays out its own intermediate synchronic
documents — ISDs, the successive presentation states a TTML processor computes as
elements begin and end — within its active period, so today's one-timed-document-per-
segment packaging is the same rule applied to a known future. A superseded document is
cut at the supersession time.

## 4. Sample format

New sample entries — placeholders `stpc` and `wvtc` — flow into the `codecs` parameter,
so legacy players never select the track.

A `stpc` document sample is a raw TTML document, byte for byte what an `stpp` sample is
today, with the same sub-sample rules for images. Only the two sample kinds that are not
documents are boxes:

```
aligned(8) class TTMLNoChangeBox extends Box('ttmn') { }                    // 8 bytes
aligned(8) class TTMLBodyBox     extends Box('ttmb') { boxstring body; }    // §5
```

`ttmb` is an ordinary box: its size field covers the header and the body, so the sample
is 8 bytes plus the body text, and `boxstring` is 14496-30's type for UTF-8 bytes that
fill the box with no terminator, as in `wvtt`'s `payl`.

A sample whose first eight bytes are a box header of type `ttmn` or `ttmb`, with a size
equal to the sample size, is that box; any other sample is a document. The test is exact:
IMSC requires UTF-8, so a document begins with `<`, a byte-order mark or whitespace, never
the 0x00 that opens a box size. A `wvtc` sample is one `vtte`, one or more `vttc`, or one
`vttn`, an empty box beside `vtte` — `wvtt` samples are boxes already. `ttmn`, `vttn` and
`ttmb` are non-sync samples; every segment starts with a sync I-sample.

The box is the only option for the marker. A zero-size sample is forbidden by 14496-30
§4.2 and avoided by 23001-18 for device reasons; the redundancy flag alone still requires
the document to be sent; and an empty document already means clear. The third state needs
a third symbol, and an 8-byte box header is one that no XML document can begin with.

## 5. Head/body split, `stpp` only

An IMSC `<head>` is 1–2 kB; the changing `<body>` is tens of bytes. Within a segment,
P-samples may carry the body only, in a `ttmb`, and the receiver splices in the `<head>`
of the segment's I-sample. Dependencies never cross a segment, so random access is
unchanged. `wvtt` already has this: its header lives in the sample entry.

## 6. What changes

| Where | Change |
|---|---|
| ISO/IEC 14496-12, CMAF, HLS | nothing |
| 14496-30 §5.9(4) | a document is active until the next document or MPA |
| 14496-30 §5.6, §6.6 | new sample entries: documents raw as today, plus `ttmn` and `ttmb` boxes for `stpp` and `vttn` for `wvtt` |
| 14496-30 §5.6 | non-sync signalling for `ttmn`, `ttmb` |
| MP4RA, the MP4 registration authority | register the four-character codes (4CCs) |
| Packagers, no spec change | stop clipping `begin` and `end` to the segment |

## 7. What it costs and saves

2 s segments, a 2.5 kB IMSC document, a state change every ~1.5 s, 250 ms parts.

| Scheme | Update delay | Bitrate | XML parses/s |
|---|---|---|---|
| `stpp` chunked at 40 ms | 40 ms | ~330 kbps | 25 |
| `stpp` in 1 s segments (DASH-IF advice) | ≥ 1 s | ~21 kbps | ~1 |
| This design, `stpp`, full documents | 250 ms | ~27 kbps | ~0.65 |
| This design, `stpp`, head/body split | 250 ms | ~5 kbps | ~0.65 |
| This design, `wvtt` | 250 ms | ~4.4 kbps | — |

The container costs ~110 B per part, so ~3.8 kbps is the floor at this cadence over
HTTP. The two HTTP transports are bounded differently: LL-HLS by requests — a playlist
reload and a part fetch per part, ~8 per second at 250 ms — and LL-DASH by bytes only,
since the chunks of a segment stream in one response. Parses per second, not bytes, are
the binding cost on a TV system on chip (SoC), and no-change signalling makes that rate
a function of content changes rather than chunk rate.

Over MoQ with LOCMAF (`draft-einarsson-moq-locmaf`) the per-object overhead falls from
~100 B to ~10 B, so a no-change object costs ~10 B and the subtitle track can run at
video frame rate for ~2 kbps. The same compact chunk head would do the same inside an
LL-DASH segment response, where only the header stands between a 100 ms chunk and a
frame-level one; the framing would need defining. The structures line up: LOCMAF
requires a full chunk first in every group, as this design requires an I-sample first in
every segment.
