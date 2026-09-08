# Low-latency subtitles: paint model, no-change samples, and unclipped documents

Design notes for delivering subtitles at low latency inside long segments without
paying a complete document per chunk. This is the full version; `DESIGN.md` is the short
one. Companion to `RESEARCH.md`, which surveys *size* reduction (approaches A–H).

**The proposal.**

1. **Paint model: signal changes when they happen.** A document is sent when a cue
   appears, changes, or is cleared — never to restate what is already on screen. The
   packager never waits for, guesses, or invents an end time (§0.2).
2. **Allow frequent no-update signalling.** Keep the regular part or chunk cadence the
   player needs — sparse tracks are the wrong answer over HTTP (§1) — and when nothing
   has changed say so in 8 bytes rather than repeating the document (§2).
3. **Make TTML intervals in `stpp` open-ended.** A cue keeps its true `begin` and has no
   `end` until it is cleared, and a document stays active until the next one supersedes
   it. The first is already permitted — packagers only have to stop clipping (§3) — and
   the second is the one change to 14496-30, a port of ETSI EN 303 560 §5.2.3.3 (§4).
4. **New no-change signalling for `stpp` and `wvtt`.** An empty 8-byte box (`ttmn`,
   `vttn`) as the sample, under a new sample entry (§2.1, §5).

Two findings shape the rest. Bytes are not the binding cost on a TV system on chip
(SoC); XML parses per second are, and no-change signalling makes the parse rate a
function of content changes rather than chunk rate (§9.1). And over MoQ (Media over
QUIC) with LOCMAF (Low Overhead CMAF, §11) the per-object floor drops from ~100 B to ~10
B, so the subtitle cadence can match the video frame rate (§11).

## 0. Goal

In low-latency (LL) CMAF, video is chunked at frame granularity (20–40 ms) inside a 2 s
segment. Subtitles today force a choice: chunk them too (a complete TTML document per
chunk — ~300–500 kbps and 25 XML parses/second), or don't chunk them (the DASH-IF LL
recommendation), in which case subtitles lag video by up to a segment. There is nothing
in between today. The design makes the cadence a continuum: the subtitle track can
follow the video down to individual frame fragments at 8 bytes per unchanged fragment,
and over MoQ with LOCMAF, where the chunk header itself shrinks to a few bytes, a
frame-level subtitle update costs ~10 B (§11).

Target: **the receiver never waits, and "nothing changed" is nearly free.** This is
the paint model of teletext / DVB subtitles / CTA-608, where state persists until
updated.

### 0.1 Scope: when is the future unknown?

If the packager **knows the segment's subtitles when the segment opens** — file-based
subtitles played out against a live programme — there is **no low-latency subtitle
problem at all**. It writes one document describing the whole segment, the segment is
complete and available at segment start, and the client has everything for the next 2 s
the moment it fetches it. Subtitle latency is zero and today's packaging is already
optimal on the sample-count axis.

The design below targets the cases where the packager *cannot* describe the future:

1. **Paint-based source formats** — MPEG-2 TS carrying teletext, DVB subtitles, or
   CTA-608/708. This is the big one, and §0.2 is about it.
2. **Real-time text production** — stenographer, ASR (automatic speech recognition), or
   an upstream EBU-TT Live feed.

§3's compression argument applies to all three.

### 0.2 Paint-based ingest is the primary case

A segmenter transcoding an MPEG-2 TS contribution or distribution feed into
`stpp`/`wvtt` **does not know a cue's duration when the cue starts**, because the source
format has no such concept. A teletext page is displayed until it is replaced or erased;
a DVB subtitle page likewise; CTA-608 roll-up and paint-on modes update continuously.
The end time simply does not exist yet.

Today's carriage demands one anyway, so the packager must fabricate it. Its options:

- **Wait** for the next update, so the end is known — adds latency equal to the cue's
  own duration, which is unbounded in principle and seconds in practice. Unusable for LL.
- **Guess** a fixed duration and be wrong.
- **Clip to the current segment or chunk**, and restate the cue in the next one if it is
  still up.

Only the third survives, and in low-latency it is exactly what makes today's packaging
expensive: **a cue that is not changing at all is restated once per chunk**, purely
because §5.9(4) will not let a document outlive its sample. At 40 ms chunks that is 25
restatements per second of identical content. The bitrate problem in `RESEARCH.md` §1 is
not caused by subtitles changing quickly — it is caused by an impedance mismatch between
a paint-model source and an interval-model carriage.

The design removes the conversion. A paint-model source maps 1:1 onto paint-model
carriage, and the packager never has to invent an end time:

| Source event | Carriage |
|---|---|
| New/changed page or caption | **P-sample** — new state, no end time needed |
| Page erased / clear screen | **clear** — a document giving the cue its `end`, an empty TTML document, or `vtte` |
| Unchanged, source repeating for acquisition | **no-change marker** (~8 B) |
| Segment boundary | **I-sample** — restate current state for tune-in |
| Source stops | **MPA** (maximum period of activation, §7) clears the screen |

Two further properties fall out:

- **The source can update far faster than is useful to carry.** CTA-608 paint-on is
  character-by-character, roll-up is line-by-line at speech rate. Today a naive converter
  can emit a document per source update. This needs an explicit cap — see §5.1; it is
  *not* something the fragment cadence handles on its own.
- **Cue identity is not required.** A paint source has no cue id. `wvtt` carries `vsid`;
  for `stpp` the segment-opening restatement is byte-identical (§3), so a receiver skips
  it without having to match cues. Whether a stable `xml:id` is worth carrying anyway is
  weighed in `ALTERNATIVES.md` §2.


### 0.3 What Shaka Packager already does

Shaka Packager's teletext path is a working implementation of the paint model — right up
to the point where it has to write MP4, at which point it throws the model away.

**The open-ended cue is already the internal representation.** `TextSampleRole`
(`packager/media/base/text_sample.h:118`) defines:

```
/// kCueStart is cue with start time but unknown end time
kCueStart,
/// kCueEnd has time to end a kCueStart, if ongoing.
kCueEnd,
```

`EsParserTeletext::SendCueStart` emits `kCueStart` when a page appears, and `SendCueEnd`
closes it when the next page arrives or at flush. That is exactly "open the cue now, add
the end later".

**The invented end time is right there in the source.**
`es_parser_teletext.h:23` — `const int64_t ttx_cue_duration_placeholder = 30 * 90000;`
(30 s), with the comment: *"SendCueStart emits a text sample with body and
ttx_cue_duration_placeholder **since the duration is not yet known**."* This is §0.2's
"guess" option, and the 30 s value is a crude MPA (§7) by another name.

**Restatement per segment is implemented literally.**
`TextChunker::AddOngoingCuesToCurrentSegment` — *"For each ongoing cue (started but no
end time yet), create a **cropped copy that ends at the segment boundary**"* — with the
start likewise cropped to `segment_start_`. So §0.2's third option is what actually
runs, and the cropping is the whole cause of the documents being position-dependent
(§3.1): the same unchanged cue is re-serialized with different begin/end values in every
segment.

**A heartbeat is already necessary, and is driven from the video/audio clock.**
`Mp2tMediaParser::update_biggest_pts` synthesizes an empty `TextSample` with role
`kMediaHeartBeat` into every text PID whenever the video/audio PTS advances by ≥ 100 ms.
The comment is explicit: *"Don't remove heartbeats - they need to be emitted to trigger
segment generation... heartbeats provide timing information for proper segment
boundaries, especially for sparse teletext streams."* An idle teletext stream supplies no
timing of its own, so the text timeline has to be slaved to another track's — which is
also why cross-track alignment (§5) is the natural frame for this design.

That slaving has a cost, exposed as a tuning flag: `--ts_ttx_heartbeat_shift` (default
90000, i.e. 1 s) — *"timing offset between video PTS timestamps and text segment
generation... If the value is too large, heartbeat-triggered text segments are generated
later than video segments. If too small, some text cues may be absent in the output."*
A knob with latency on one side and dropped cues on the other exists purely because the
packager must guess how far ahead of teletext the video pipeline is running.

**What this design changes.** The heartbeat already exists — it is computed, used to
trigger segment generation, and then discarded. §2's no-change marker is simply its
**wire-level counterpart**, so the receiver is told what the packager already knows.
Nothing has to be invented: `kCueStart` becomes a P-sample with no end, `kCueEnd` becomes
either the next P-sample or a clear sample, `kMediaHeartBeat` becomes the no-change
marker, and `ttx_cue_duration_placeholder` disappears because no end time is ever
fabricated. Whether `--ts_ttx_heartbeat_shift`'s "too small → cues absent" failure also
softens — a late cue could be emitted in a later chunk with its own start time rather
than being dropped for want of an open segment — is worth testing rather than assuming.

## 1. Why sparse is the wrong answer over HTTP

### 1.1 LL-HLS mandates the cadence

`draft-pantos-hls-rfc8216bis-15` §4.4.4.9:

> The duration of a Partial Segment MUST be less than or equal to the Part Target
> Duration. **The duration of each Partial Segment MUST be at least 85% of the Part
> Target Duration**, with the exception of Partial Segments with the INDEPENDENT=YES
> or GAP=YES attribute...

and §6.2.1:

> If a Media Playlist without an EXT-X-ENDLIST tag contains Partial Segments, the
> Server **MUST add a new Partial Segment to the Playlist within one Part Target
> Duration after it added the previous Partial Segment.**

A ±15 % band, and an obligation to produce a part every Part Target Duration. `GAP=YES`
is no loophole — it means "not available", i.e. missing media the client must not
fetch. `PART-TARGET` is a Media Playlist attribute, so a subtitle rendition **may**
use a longer one than video; that is the design knob (§5).

### 1.2 Silence is ambiguous

A sparse track over HTTP cannot distinguish "nothing was produced" from "something was
produced and hasn't arrived". Progress then requires a timeout — best-effort by
definition. What breaks the ambiguity is a **watermark**: a receiver-observable
"this track is complete up to T". Over HTTP there isn't a good one. In HLS the playlist
is one, but §6.2.1 makes it advance on a fixed cadence anyway. In DASH with `$Number$`
there is none — availability is *computed*, not observed; `SegmentTimeline` makes the
MPD a watermark but then MPD refresh becomes the latency floor, which LL-DASH exists to
avoid.

Over HTTP, the cheapest available watermark **is the cadence itself**.

### 1.3 The broadcast paint model was never sparse either

Teletext and DVB subtitles run over a constant-rate multiplex: the carrier *is* the
watermark, and magazine rotation / page repetition *is* a cadence. DVB-TTML likewise
only omits data while nothing is on screen, and even then must emit an empty segment
within MPA (EN 303 560 §5.2.3.5). The paint model has always been "regular rhythm,
cheap payload", never "send nothing".

### 1.4 CMAF blocks the container mechanism anyway

14496-12 §8.8.12.1 permits a zero-duration sample extended by the next `tfdt`, but
CMAF §7.3.2.2 c) requires `baseMediaDecodeTime` to **equal** the sum of sample
durations, §7.3.2.3 Table 7/b)/g) require an `mdat`, exactly one `trun`, and no gaps,
and §11.6 explicitly requires padding subtitle tracks with samples. Nor can a brand
help: `cmf2` "further **restricts**" `cmfc` — CMAF brands only narrow, and §7.3.2.x are
general track constraints, not per-media-profile.

## 2. The design: no-change samples on a regular cadence

- Regular part/chunk cadence `C`, chosen for the player's alignment needs and
  independent of the video cadence.
- Every part carries one sample with a real, non-zero duration.
- A **no-change marker** means *"the state established by the last content sample
  persists"*.
- Timeline tiles exactly; `tfdt` = sum of durations exactly. **Every CMAF timing
  invariant holds and LL-HLS's part rules are satisfied.**

Per segment: an **I-sample** first (complete current state, so every segment is
self-contained for random access), **P-samples** on change, no-change markers
otherwise.

### 2.1 Use a small box, not a zero-size sample

ISO/IEC 23001-18:2022 (Event message tracks) §6.2:

> ```
> aligned(8) class EventMessageEmptyBox extends Box('emeb') { }
> ```
> NOTE  **Using zero-size samples** to signal when no event metadata or event is
> active **is avoided because this can cause problems in some devices.**

and §9.3: long idle stretches "can be signalled using **multiple samples** each
carrying this EventMessageEmptyBox."

`draft-einarsson-moq-locmaf` §"Event-Only Tracks" notes that DASH-IF Live Media Ingest
"commonly shapes sparse metadata tracks (`urim`, `stpp`)" with a synthetic per-chunk
**zero-size sample**. That is not a counter-example: DASH-IF Ingest is a **contribution**
interface between encoder and origin, not a distribution format. No client ever parses
those samples, so it says nothing about what a subtitle renderer will accept.

On the distribution side the evidence is one-directional — 14496-30 §4.2 forbids
zero-size samples and 23001-18 avoids them for device-compatibility reasons — so the box
is the unopposed choice, not a judgement call between competing practices.

MPEG's answer for the sparsest track type it has standardized was an 8-byte empty box
in ordinary samples, subdivided to the fragmentation cadence — this design, arrived at
independently, and independent confirmation of §1. It also sidesteps 14496-30 §4.2
("Samples with a size of zero are not used") entirely.

So the marker is a box, and the sample *is* the box: an 8-byte sample whose only content
is an empty box of a new type. That does not make every sample a box. `wvtt` samples are
boxes; `stpp` samples are raw XML documents, and under the new sample entry (§5) they stay
that way — a `stpc` document sample is byte for byte an `stpp` sample, with the same
sub-sample rules for images (14496-30 §5.6). Only the sample kinds that are not documents
are boxes. Placeholder syntax, four-character codes (4CCs) to be registered:

```
aligned(8) class TTMLNoChangeBox extends Box('ttmn') { }   // 8 bytes, empty
aligned(8) class TTMLBodyBox extends Box('ttmb') {         // Layer 2 only, §6
      boxstring body;        // the <body> element; <head> comes from the segment's I-sample
}
```

`ttmb` is an ordinary box: its size field covers the header and the body, so the sample
is 8 bytes plus the body text. `boxstring` is 14496-30 §6's type for UTF-8 bytes that
fill the enclosing box with neither a length prefix nor a trailing null — the type
`wvtt` uses for `payl` — rather than 14496-12's null-terminated `utf8string`.

**Dispatch rule.** A sample whose first eight bytes form a box header with a type of
`ttmn` or `ttmb` and a size equal to the sample size is that box. Any other sample is a
complete TTML document. The test is exact, not a heuristic: IMSC 1.0.1 and IMSC 1.3 both
require UTF-8 for document instances, so a document begins with `<`, a byte-order mark or
whitespace and never with the 0x00 that opens a box size; and no encoding EBU-TT-D permits
can produce one of these two box types at the right size either. The receiver's check for
the common case is eight bytes:

```
sample_size == 8 && bytes == 00 00 00 08 't' 't' 'm' 'n'   →  no change
otherwise                                                    →  a TTML document, as in stpp
```

Size alone would not do — `<tt/>` and three spaces is well-formed 8-byte XML — which is
why the marker is a real box rather than a bare length: the test is exact, generic ISOBMFF
tools show a `ttmn` box instead of eight opaque bytes, and 23001-18's `emeb` is the
precedent for an empty box as a whole sample.

A sample under `wvtc` is one `vtte`, one or more `vttc`, or exactly one `vttn` — an empty
box, the peer of `vtte`.

| Sample | Payload | Meaning | Sync |
|---|---|---|---|
| document (I- or P-sample) | the document, as in `stpp` | a new document supersedes the active one (§4) | yes |
| empty document | ~60 B | **clear** — supersede with nothing | yes |
| `ttmb` (Layer 2 P-sample) | 8 B + body | supersede; `<head>` spliced from this segment's I-sample | no |
| `ttmn` / `vttn` | **8 B** | **the active document continues**; MPA timer reset (§4.3) | no |

No-change and body-only samples are non-sync (`sample_is_non_sync_sample`, depending on
the previous content sample). A segment starts with a sync I-sample, as CMAF requires of a
fragment; later chunks within it need not start with one.

Why not the alternatives:

- **A zero-size sample** — 14496-30 §4.2 forbids it and 23001-18 avoids it (above).
- **The §5.9(3) redundancy flag alone** — it marks a document *that is present* as
  identical to the previous one. The bytes are still sent; the flag lets the receiver skip
  the parse, which is §3's win, not this one.
- **An empty document** — that already means *clear the screen* (§2.2). The third state
  needs a third symbol.
- **Wrapping every sample in a box**, `wvtt`-style — uniform, but it changes the one
  thing about `stpp` that every packager and player already handles, and the receiver's
  test is the same eight bytes either way. `ALTERNATIVES.md` §3.

What is borrowed from `emeb` is the *mechanism*: an 8-byte box in an ordinary sample. The
semantics differ — `emeb` means "nothing is active", closer to our clear; `ttmn` means
"what was active still is".

### 2.2 Three states, only two expressible today

| Meaning | Today | Needed |
|---|---|---|
| Show this | TTML document / `vttc` | — |
| **Clear the screen** | empty TTML doc / `vtte` | — |
| **Leave it alone** | *inexpressible* | new no-change box |

Today "leave it alone" can only be said by retransmitting the document, which is why
every approach in `RESEARCH.md` reduces to compressing a retransmission.

### 2.3 Worked example: a cue across a segment boundary

2 s segments, `C` = 250 ms parts (the LL-HLS video cadence, §5). Nothing is on screen at
10.00. A cue appears at 10.30 with an unknown end; it turns out to be cleared at 13.10.

| Time | Segment | Part | Sample in the part | Payload |
|---|---|---|---|---|
| 10.00 | N | 1 | I-sample: empty document — nothing on screen | ~60 B |
| 10.25 | N | 2 | P-sample: `<p begin="10.3s">…</p>`, **no `end`** — the cue appears 50 ms into the part, placed by its own `begin` | ~2.5 kB |
| 10.50 – 11.75 | N | 3–8 | one `ttmn` each — **the cue is kept open by no-change samples** | 8 B each |
| 12.00 | N+1 | 1 | I-sample: **the same document, byte for byte** — restated for tune-in, may be marked redundant | ~2.5 kB, skippable |
| 12.25 – 12.75 | N+1 | 2–4 | one `ttmn` each | 8 B each |
| 13.00 | N+1 | 5 | P-sample: `<p begin="10.3s" end="13.1s">…</p>` — **the end, now known, is written**; after 13.10 the document shows nothing | ~2.5 kB |
| 13.25 – 13.75 | N+1 | 6–8 | one `ttmn` each | 8 B each |

What to notice:

- **The cue's end is written once it is known, and never guessed.** The part starting at
  13.00 is emitted when it completes at 13.25, by which time the clear at 13.10 has
  happened, so its document carries `end="13.1s"`. The document at 10.25 carries no `end`
  because none was known (§0.2).
- **Open-ended in two senses, and both are needed.** At the TTML level the `<p>` has no
  `end`, so the intermediate synchronic document — the ISD, the presentation state a
  TTML processor computes for each interval in which no element begins or ends — keeps
  the cue. At the container level the document's *active period* runs past its own
  sample's 250 ms until the next document supersedes it (§4); without that change,
  today's §5.9(4) would end the cue at 10.50.
- **One sample per part, as `stpp` today.** The changes at 10.30 and 13.10 are placed by
  the documents' own `begin` and `end`, not by the sample table, so no part needs
  splitting. `tfdt` at 12.00 equals the sum of durations and every part is exactly one
  part target duration. A `wvtt` track, whose timing lives only in the sample table,
  would split the parts at 10.25 and 13.00 into a `vttn` or `vtte` and a `vttc` (§5).
- **Segment N carries the cue to its end with 8-byte samples.** Six no-change samples,
  48 bytes of payload.
- **The I-sample at 12.00 is a begin time outside the fragment** (§3): `begin="10.3s"`
  inside segment N+1. Because the packager did not clip it, the document is identical to
  the one sent at 10.25, so a receiver already holding it skips the parse (§9.1). A
  receiver tuning in at 12.00 parses it and shows the cue, as 14496-30 Figure 1 describes.
  The I-sample at 14.00 is an empty document: the cue is entirely outside that sample, and
  EBU Tech 3381 §6 says such content is omitted.
- **With Layer 2** (§6) the 10.25 and 13.00 samples become `ttmb` bodies of ~150 B, since
  the `<head>` is already in each segment's I-sample. The 12.00 I-sample must stay a full
  document.
- **If the packager stops** after 12.75, no further samples arrive and MPA (§7) clears the
  screen at 12.75 + 5 s. During normal delivery the no-change samples are what keep MPA
  from firing.

Receiver behaviour per sample type: a document — parse (unless identical to the active
document), compute the ISD, render; `ttmb` — splice the segment's `<head>`, then as a
document; `ttmn` — nothing, except reset the MPA timer.

## 3. Stop clipping — position-independent documents

### 3.1 The problem: clipped documents are position-dependent

14496-30 §5.3:

> The top-level internal timing values in the timed text samples based on TTML express
> times on the **track presentation timeline** – that is, the track media time as
> optionally modified by the edit list. For example, the begin and end attributes of
> the `<body>` element, if used, are **relative to the start of the track, not relative
> to the start of the sample**.

So every document's times are on an ever-growing track timeline. That alone is not the
problem — a cue's `begin` is a constant however often the cue is restated. The problem is
what packagers do with it: they **clip** `begin` and `end` to the segment they are
writing, so a cue that is not changing at all is re-serialized with new numbers in every
segment. Shaka's `TextChunker` does exactly this (§0.3: *"a cropped copy that ends at the
segment boundary"*, with the start likewise cropped to `segment_start_`). The same
subtitle shown at 00:10:00 and 00:12:00 then has **different bytes**, and:

- §5.9(3)'s "if a sample contains the identical document to the prior sample, it may
  be marked as redundant" almost never fires in live.
- Each segment's I-sample must be re-serialized, even when nothing changed.
- Shared-dictionary and delta compression (`RESEARCH.md` E–H) fight the timestamps,
  which are the highest-entropy part of an otherwise static document.
- The receiver must re-parse XML it has effectively already seen.

### 3.2 The rule: stop clipping — and no spec forbids it

14496-30 §5.9(1) permits times outside the sample outright: the earliest computed begin
*"can be non-coincident (earlier or later) with the composition time of the containing
sample"*, and likewise the latest end with the sample end. §5.9(3) permits content that
falls *"partially or wholly within the duration of a sample"* to be duplicated in adjacent
samples, and if the document is identical it *"may be marked as redundant"*. Figure 1 of
the same standard shows a receiver handling a document whose times start before the
sample: it presents *"as if the decoder seeked"* into the document. Downstream:

- **CMAF** §11.3 defers to 14496-30 and adds no constraint on document times; §11.6 only
  requires padding samples, which §2 provides.
- **EBU Tech 3381** §6: all content that falls partially or wholly within the sample
  *"shall be present"*; only content *"entirely outside the duration of the sample shall
  be omitted"*.
- **DVB-DASH** (ETSI TS 103 285) §11.7: *"Times do not need to be truncated at the start
  and end of the sample as the Player will carry that out based on the sample's start
  time and duration."* What it discourages is including cues that never display during
  the sample — not unclipped times.

So the rule is simply: **stop clipping — a cue keeps its true `begin`, and its `end` is
omitted while unknown** (or kept, when the future is known, §0.1). Under today's §5.9(4)
the receiver confines presentation to each sample, so an open-ended `<p begin="…">`
restated in every sample is already the paint model emulated by restatement; under §4's
amendment the restatement is no longer needed. Either way every restatement is **byte-
identical**, so §5.9(3)'s redundancy flag fires on each one and a receiver can skip the
parse. That is the parse-rate win of §9.1, with **no spec change** and no new box. The
bytes are still wasted; §2 and §6 fix that.

The "redundant" marking is 14496-12's, not 14496-30's own: §5.9(3) names no field. It is
the sample dependency flags of 14496-12 §8.6.4 — in `sdtp` for a plain file, in the
`sample_flags` of `trun` or the `default_sample_flags` of `tfhd` for fragments — set to
`sample_depends_on = 2` and `sample_has_redundancy = 1`. Every `stpp` sample already has
the first, since §5.6 makes them all sync samples; the second is the only addition. For
tracks that are not video, audio or hint, §8.6.4 then says such a sample *"can be
discarded, and its duration added to the duration of the preceding one"* once a sync
sample has been processed. That is skip-and-extend in the base standard, for the
byte-identical case. The field's own definition is about redundant *coding* within a
sample, the video sense; it is this non-audiovisual rule that turns it into "this sample
repeats the previous one". Whether players act on it is §12 question 8.

Two properties follow that might look like problems and are not. Documents stay tied to
this track's timeline, so a re-origin or DVR re-base that shifts the timeline must either
retime the XML or apply an edit list — exactly as for every `stpp` track today, and EBU
Tech 3381 §6 recommends the edit list. And in a 24/7 stream the absolute values grow
without bound, as they already do in every 24/7 `stpp` stream.

### 3.3 Alternatives considered

Mechanisms that make documents position-independent by construction — times relative to
the sample start, as Smooth Streaming and RFC 8759 do, or an explicit anchor such as
DVB-TTML's `segment_mediatime` or `wvtt`'s `ctim` — are compared in `ALTERNATIVES.md` §1.
Neither is needed once packagers stop clipping.

### 3.4 What it buys

Unclipped documents make a persisting cue's I-sample **byte-identical every segment**.
Then:

- §5.9(3) redundancy marking becomes genuinely usable — the receiver can skip XML
  parsing entirely, addressing `RESEARCH.md` §1's "10× parsing cost on the receiver".
- Compression stops fighting the timestamps: an exact dictionary hit rather than a
  near-miss.
- It composes with Layer 2: invariant `<head>` + invariant body means the entire
  I-sample is a constant.

**Not clipping does not save bytes by itself — it removes the variance that was capping
every other approach.** It is a multiplier on E, F, G and H, not an alternative to them.

### 3.5 Taken to its conclusion: untimed documents

EN 303 560 §5.2.3.7:

> When **only untimed elements** are present in a TTML segment, the segment corresponds
> to an ISD with **unlimited timing boundaries**. The elements are only active for the
> duration of the segment, and hence become active at the activation time of the
> segment (segment mediatime or Ti or Pi) and become **inactive at the activation time
> of the next segment or T_MPA after the activation time (whichever is the earlier)**.

That is the entire paint model, normatively specified: a document with *no timing at
all*, started by the wire, ended by the next document or MPA. Maximally
position-independent — there is no timestamp left to vary, and nothing to clip.

## 4. The §5.9(4) amendment is a port, not an invention

Compare. 14496-30 §5.9(4):

> **Only one sample and document** within a Timed Text Track **can be active at any
> moment** in the presentation. The presentation of every document is constrained in
> time to the period beginning at the composition time of the containing sample **with
> the duration of that sample**.

EN 303 560 §5.2.3.3:

> A TTML segment becomes inactive when a **later TTML segment becomes active** or after
> being active for **T_MPA**, whichever is the earlier... **Only one TTML segment can be
> active at any point in time.** Only the ISDs from the currently active TTML segment
> shall be displayed. Therefore, if there is no active TTML segment, no subtitles shall
> be presented.

Word-for-word parallel on "only one active"; the entire delta is what *terminates* it —
sample duration versus next-document-or-MPA. The amendment is: replace "with the
duration of that sample" with DVB's rule. That is deployed broadcast behaviour being
ported from TS to ISOBMFF, which is a far easier argument to make to MPEG than novel
semantics. RFC 8759 §6 has the same rule for TTML over RTP, independently: *"exactly zero
or one document SHALL be considered active at each moment... processing of D(n-1) MUST be
stopped at E(n) and processing of D(n) MUST begin."* Two deployed carriage formats, one
rule.

DVB also already acknowledges the open-ended interval directly (§5.2.4.3): *"For live
subtitling the endtime of an ISD may be **provisional and change when a new segment is
created**."*

### 4.1 Cue identity across boundaries

DVB-TTML notes the problem and does not solve it. §5.2.3.6: *"a subtitle present in
multiple document chunks may not necessarily have identical timing information in every
document chunk... it is not recommended to use timing information to match subtitles"*,
with only a behavioural request that IRDs (integrated receiver decoders) *"avoid
intermittent removal of the subtitle from the screen at the segment boundaries"*
(§5.2.3.3). `wvtt` has `vsid` for this.

The proposal adds no `stpp` equivalent. Unclipped restatements are byte-identical (§3),
so a receiver skips the whole document rather than matching cues inside it, and a TTML
renderer draws each ISD as a frame — there is no per-cue object to tear down. A stable
`xml:id` remains an optional hint; the case for and against is in `ALTERNATIVES.md` §2.

### 4.2 Long documents with internal timing still work

Today's typical packaging — one 2 s sample whose document carries several `<p>` elements
with their own begin/end times, i.e. several ISDs inside one sample — is **not a separate
case**. It falls out of the same rule set:

1. A sample's document becomes **active** at the sample's composition time, with its
   times on the track timeline as today (§5.3 is untouched).
2. Within its active period the document's **internal timing plays out normally**,
   producing as many ISDs as it describes.
3. Its active period **ends at the next content sample, or MPA, whichever is earlier**.

Rule 2 is today's behaviour untouched. Rule 3 is the only change, and it is what makes
the two styles endpoints of one continuum rather than two designs:

| | Timing lives in | Used when |
|---|---|---|
| One timed document per segment | the document | the future is known |
| One untimed document per state change | the sample table | the future is unknown |
| Predictive document, superseded on change | both | the future is guessed |

The untimed case (EN 303 560 §5.2.3.7) is simply the degenerate one with exactly one ISD.

**Backward compatibility falls out.** For content whose samples tile the timeline — all
existing `stpp` and `wvtt` tracks — the next sample's composition time *is* the current
sample's composition time (CT) plus its duration, so rule 3 gives exactly the interval
§5.9(4) gives today. The new rule is behaviourally identical for every existing stream;
it only differs where delivery actually stops, which today is undefined anyway.

To keep that exact, MPA must be measured from the **last sample of any kind**, and the
active interval bounded by `CT + max(sample_duration, MPA)` so that legitimately long
samples (14496-30 Figure 1 has a 30-minute one) are not truncated by a 5 s failsafe.

### 4.3 What a no-change marker means, precisely

It means **"the active document continues"** — not "freeze the current picture". The
active document keeps advancing on the track timeline, so ISDs scheduled after
the marker still fire.

That distinction is what lets a long timed document coexist with a fine part cadence: a
2 s document emitted at segment start, followed by no-change markers every 500 ms purely
to satisfy LL-HLS's part rules (§1.1), plays out its internal ISDs exactly as authored
while the markers keep the cadence alive at ~120 B each. If the marker meant "freeze",
this combination would break.

A no-change marker also **resets the MPA timer without superseding**, so the cadence
itself keeps the failsafe from firing; MPA then fires only when delivery genuinely stops.

### 4.4 Supersession is a hard cut

If a document describing ISDs out to t0 + 2 s is superseded at t0 + 0.5 s, the rest is
discarded. EN 303 560 §5.2.3.3 is explicit: *"At the activation time of the following
segment (PTS) shall only display the ISDs from newly active segment."*

That is well-defined, and it enables the third row of the table above: a packager may
emit a **predictive** document — "show A now, B at t0 + 1.2 s" — and supersede it if
reality diverges. When the prediction holds, a whole segment costs one document. This is
the natural mode for a live-captioning pipeline that has *some* lookahead, and it
degrades gracefully to the untimed case when it has none.

## 5. A new sample entry, and choosing the cadence

A new 4CC (placeholders `stpc` / `wvtc`) flows into the RFC 6381 `codecs` parameter and
therefore into MPD/playlist selection that already exists, so legacy clients simply do
not select the Representation. It carries the MPA (§7) and, for Layer 2, the `<head>`
template. It does not confer CMAF conformance — but this design
does not need it to, since the timing arithmetic is untouched.

With the paint model the receiver never waits to render; it always holds valid state.
The cadence bounds *update* latency, not *render* latency.

Updates are **not** quantised to the part grid, and for `stpp` nothing new is needed to
avoid it: one document per part, as today, with `begin` and `end` at their true times
inside the part (§2.3). `wvtt` has no internal timing, so there a part may carry more
than one sample — a no-change sample covering `[part_start, t)` and a cue sample
covering `[t, part_end)` — for the cost of one extra `trun` entry (8 B). Either way the
timeline tiles exactly and every invariant of §2 holds. So `C` bounds when the receiver
*learns* of a change (up to `C` late), not when it renders it, which stays exact.

**The cadence should match the video part/chunk cadence, not be chosen independently.**
A subtitle track coarser than video parts lags video by up to the difference, which at
LL latency targets is a large fraction of the budget, and there is no benefit to being
finer. The no-change box is what makes matching affordable; it is not a knob to trade
against bitrate.

The primary reason is **cross-track alignment**, not update latency. A player must hold
data covering the presentation time for every selected track before it can advance, and
a pipeline that gates on `min(buffered_end)` across tracks lets the **coarsest track set
the latency floor for the whole presentation**. Today a subtitle track that produces one
sample per segment drags that minimum down by up to a segment — so subtitles raise the
latency of video and audio too, which is a large part of why LL deployments end up
recommending that subtitles simply not be chunked (§0).

No-change markers at the video part cadence keep the subtitle track's buffered end
advancing in lockstep, so it never becomes the binding constraint. Combined with §2's
persistence — the receiver always holds valid state and so never *waits* on the text
track — subtitles drop out of the critical path entirely. This is also a further
argument against sparsity (§1): an irregular buffered end is worse for a min-across-
tracks scheduler than a merely coarse one, because it is unpredictable.

How much this bites depends on the pipeline. Browsers parse `stpp`/`wvtt` in JS outside
MSE (Media Source Extensions), so text usually has no SourceBuffer and no buffered range
to gate on. Native and device pipelines, where the subtitle track is a real demuxed
track alongside audio and video, are where cross-track buffering actually constrains
latency.

What "affordable" means differs by transport, because per-object cost is not the same
kind of thing in each:

| Transport | Cadence | Per-object cost | Subtitle floor | Added requests/s |
|---|---|---|---|---|
| LL-HLS | match video part; **250 ms** typical | ~120 B | ~3.8 kbps | ~8 — a playlist reload *and* a part fetch per part |
| LL-DASH | match video chunk; 100–500 ms | ~120 B | 3.8–9.6 kbps | ~0.5 — one request per segment |
| MoQ + LOCMAF | match video frame rate; 20–40 ms | ~10 B (§11.1) | ~2–4 kbps | 0 |

LL-HLS is bounded from below by **requests**: every part costs a playlist reload and a
part fetch, so 250 ms parts already add ~8 req/s for the selected rendition and going
finer buys little. LL-DASH and MoQ are bounded by **bytes** only — LL-DASH keeps one
request per segment and streams chunks inside it, so a finer chunk costs a fragment
header plus payload, never a round trip. That is why LL-DASH can chunk finer than
LL-HLS, and MoQ finer still. Nor is the LOCMAF encoding tied to MoQ: carried inside an
LL-DASH segment response it would cut the per-chunk cost toward the MoQ column (§11.2),
leaving only the framing to define.

Per part over HTTP: `moof`(8) + `mfhd`(16) + `traf`(8) + `tfhd`(16) + `tfdt` v0(16) +
`trun`(20) + `mdat`(8) + 8-byte no-change box ≈ **100–120 B**.

### 5.1 Two cadences: fragment rate and update rate

The fragment cadence `C` is not a coalescing filter. It bounds the update rate only when
it is coarse, and the direction of travel is the opposite — LOCMAF at 40 ms would coalesce
CTA-608 paint-on from ~30/s to ~25/s, i.e. not at all. **The finer `C` gets, the more an
explicit cap on the content update rate is needed.** So there are two independent
parameters:

- **`C` — fragment/part cadence.** Set by the transport and matched to video (§5). Governs
  cross-track alignment and the container floor.
- **`U` — maximum content update rate.** Set by receiver CPU budget and fidelity taste.
  Governs how often a document is emitted, and therefore parsed.

**`U` is a cap, not a clock.** Emission stays irregular and content-driven, with only a
floor on the interval between updates: when a change arrives and the last emission was at
least `1/U` ago it goes out immediately, at its true composition time; otherwise it is
held and the state as of the release moment is emitted. There is no update grid anywhere
in this design — neither `C` (see above) nor `U` imposes one.

The receiver correspondingly has no clock and no rate limit of its own. It renders each
sample at its composition time as it arrives and reacts to a change the moment it sees
one. `U` is therefore purely a sender-side policy and needs **no signalling** — unlike
MPA (§7), it is invisible to the format.

`U ≤ 1/C` necessarily, but the point is that `U` should be *much* smaller. Coalescing is
a packager policy, not a format matter: each emitted state is the current full state, so
dropping intermediate states is lossless in outcome — only the intermediate renderings
are lost. Holding an update is also the safe direction: it can delay text relative to
video, never let it lead.

| Source | Native update rate | Sensible `U` |
|---|---|---|
| Teletext page | ~0.3–0.7/s | no coalescing needed |
| DVB subtitle page | ~0.3–0.7/s | no coalescing needed |
| CTA-608 roll-up (per row) | ~1–2/s | 2/s |
| Live word-by-word captioning | ~2–4/s | 2–4/s |
| CTA-608 paint-on (2 bytes/frame) | ~15–30/s | 4/s — the painting animation is lost |

Only the last row loses anything real, and character-by-character painting is reasonably
set aside as a fidelity case that OTT subtitle rendering does not attempt anyway.

### 5.2 High update rates are what make Layer 2 essential

Cost per second at update rate `U`, using §9's document sizes:

| | `U` = 1/s | `U` = 4/s |
|---|---|---|
| Full IMSC document (~2.5 kB) | ~20 kbps | **~80 kbps** |
| Layer 2 body-only (~150 B) | ~1.2 kbps | ~4.8 kbps |

Full-document restatement is comfortable at one update per second and untenable at four.
So the head/body split (§6) is not merely an optimisation for the idle case — **it is what
makes word-by-word captioning affordable at all**, and its value rises linearly with `U`
while the no-change marker's value rises with `1/C`. The two attack different regimes and
neither substitutes for the other.

Structured delta encoding — "append this text to cue N" rather than a fresh document —
would help further at high `U`, and a further box type beside `ttmb` (§2.1) would be the
natural vehicle for it. But it only pays for itself above the rates in §5.1's table, and
it is the one step that would stop samples being ordinary documents. Left out of scope
here: coalescing to `U` ≈ 2–4/s plus Layer 2 covers every case except uncoalesced
paint-on.

## 6. Layer 2 — content prediction for `stpp`

Only worth doing for TTML, where the `<head>` is 1–2 kB and the changing `<body>` is
tens of bytes.

- **I-sample**: complete IMSC document — `<head>` + full current `<body>`.
- **P-sample**: body only, carried in a `ttmb` box (§2.1); the receiver splices in the
  `<head>` from **the I-sample of the same segment**.

Dependency scope is deliberately **one segment — a closed GOP**, so segment-level
random access is untouched. This breaks §5.6 ("Every sample is therefore a sync sample
in this format"); the fragment must signal dependency as video does — `tfhd`
`default_sample_flags` non-sync, `trun` `first_sample_flags` sync. CMAF §7.7.3 already
*requires* these flags, so it fits the existing shape.

For `wvtt`, Layer 2 is **already done** — the header lives in `vttC` in the sample
entry, so a `wvtt` sample is already just the cue payload (~60 B).

## 7. Failsafe: maximum period of activation

EN 303 560 §5.2.3.3 sets T_MPA = 5 s. Carry an MPA in the new sample entry; the receiver
clears if no state has been established within it. With per-segment I-samples the
practical bound is already the segment duration.

## 8. `wvtt` is the cleaner design vehicle

WebVTT's lack of open-ended cue syntax is irrelevant: in `wvtt` cue timing is not in the
payload. §6.1 — *"the textual timestamps one would normally find in a WebVTT file do not
determine presentation timing; **the ISO file structures do**"*, and §6.7.2 removes the
cue timings on import *"as they are now represented in the time to sample mapping of the
file"*. The stored cue is deconstructed into `payl`/`sttg`/`iden` with no timing boxes, so
a `wvtt` payload is **position-independent by construction** — the property §3 has to add
to `stpp`. Persistence is purely a container property.

Of position-independence (§3) and cue identity (§4.1), `wvtt` already has both: its
payloads carry no time, so there is nothing to clip, and `vsid` identifies cues. `ctim` is
present only when a cue carries inline cue timestamps (§6.6, §6.7.2); it appears in §3.3
only as an alternative considered, not as something the `wvtt` variant uses.

Nor does `wvtt` need the no-change box to be paint-model. A cue that spans samples is
restated as a `vttc` in each, and §6.6 makes a `source_ID` match *"diagnostic that the
same cue is still active"* — so a ~70 B `vttc` per part, with the part's duration, is the
paint model today, and no end time is ever known at cue start. For `wvtt` the no-change
box and MPA are refinements (§9); they are the enabler only for `stpp`.

Deployment reality runs the other way (`wvtt`-in-mp4 is rare; HLS ships sidecar `.vtt`,
DVB-DASH/HbbTV ship IMSC in `stpp`), so **prototype on `wvtt`, target `stpp`**: `wvtt` is
the model, `stpp` is the patient.

## 9. Byte budget

2 s segments, 2.5 kB IMSC document, state changing ~every 1.5 s, `C` = 250 ms — the
LL-HLS video part cadence (§5).

| Scheme | Max update delay | Bitrate |
|---|---|---|
| `stpp` chunked at 40 ms (naive LL) | 40 ms | ~330 kbps |
| `stpp` unchunked 1 s segments (DASH-IF advice) | ≥ 1 s | ~21 kbps |
| No-change samples, `stpp`, Layer 1 only | 250 ms | ~27 kbps |
| **No-change samples, `stpp`, Layer 1+2** | 250 ms | **~5.1 kbps** |
| `wvtt`, restated `vttc` per part, as today (no spec change) | 250 ms | ~5.8 kbps (cue on screen) |
| **No-change samples, `wvtt`** | 250 ms | **~4.4 kbps** |
| + unclipped documents (§3) + shared dictionary (`RESEARCH.md` E1) | 250 ms | **~3.8 kbps** (floor-bound) |
| MoQ + LOCMAF, `wvtt`, frame-rate cadence (§11.2) | 40 ms | **~2 kbps** |

Effort ordering over HTTP at video-part cadence:

- no-change box alone: 330 → 27 kbps (**12×**)
- plus Layer 2 head/body split: 27 → 5.1 kbps (**5×**)
- plus unclipped documents and dictionary: 5.1 → 3.8 kbps (**1.3×**, container-floor
  bound)

The two `wvtt` rows are ~1.4 kbps apart. Restating a ~70 B `vttc` (`vttc` + `vsid` +
`payl`) in every part is already cheap against the ~110 B container, so for `wvtt` the
no-change box is a refinement — about a quarter of the bytes at 250 ms, a third at 40 ms
— not the enabler it is for `stpp`, where the same restatement costs a 2.5 kB document.

Payload optimisations hit diminishing returns against the ~120 B container floor — which
is exactly what LOCMAF removes over MoQ (§11.1). At coarser cadences, ordinary 2 s
segments or non-LL delivery, the ratios invert and the document dominates again; that is
the regime where not clipping and the dictionary matter most.

### 9.1 The other budget: XML parses per second

Bytes are not the binding cost on a cheap TV SoC; **document parses are**. High-frequency
fragments mean high-frequency XML parsing plus ISD computation and re-layout, and this is
where the current approaches fare worst: compression reduces bytes while leaving the
parse rate untouched, and adds a decompress step per fragment. `RESEARCH.md` §4 already
carries a "Parser cost" column; the point is that the relevant quantity is a **rate**.

Assumptions as §9: state changing ~every 1.5 s (0.65/s), 2 s segments. Note this is
`U` from §5.1 — the rate holds because the packager *caps* it, not by luck. A word-by-word
source at `U` = 4/s moves the last two rows to ~4.5 and ~4 parses/s, still an order of
magnitude below the fragment rate.

| Scheme | XML parses/s @ 40 ms | @ 250 ms | Decompress ops/s |
|---|---|---|---|
| Naive LL chunking | 25 | 4 | 0 |
| `RESEARCH.md` B/C/D/E — compression | 25 | 4 | one per fragment |
| `RESEARCH.md` H — XML diff/patch | 50 (base + patch) | 8 | 0 |
| `RESEARCH.md` G — template + binary delta | 0 | 0 | 0 |
| **No-change markers (§2)** | **~1.15** | **~1.15** | — |
| **+ unclipped documents (§3), skip identical I-samples** | **~0.65** | **~0.65** | — |

The important property is that the last two rows are **cadence-independent**. Parse rate
stops being a function of the packaging and becomes a function of the content: one parse
per actual subtitle change, whatever the fragment rate. Going from 20 parses per second
to one is a larger practical win than any of the byte reductions.

The `~1.15` is 0.65 content changes plus one segment-boundary I-sample restatement per
2 s. Not clipping (§3.2) removes that residue: the restatement is byte-identical, so the
receiver can recognise it and skip the work. This is the concrete form of §3.4's claim
that its value at LL cadence is CPU rather than bytes, and it is what finally makes
14496-30 §5.9(3)'s "may be marked as redundant" do something useful.

Approach G is the only existing proposal that attacks this axis, and it does so by
abandoning XML samples entirely — a new sample format, incompatible with everything. The
paint model gets most of the same benefit while samples remain ordinary documents.

**Three levels of receiver work avoided**, in decreasing order of savings:

| Signal | Receiver skips |
|---|---|
| No-change marker (§2.1) | everything — no document to look at |
| Byte-identical document + `sdtp` redundancy (§3.4) | parse, ISD computation, render |
| Same cue, different bytes — `vsid` (§4.1) | re-render |

Only the third exists today, and only for `wvtt`.

## 10. What has to change

| Spec | Clause | Current | Needed |
|---|---|---|---|
| 14496-12 | — | — | **nothing** |
| 23000-19 (CMAF) | — | — | **nothing** (timing arithmetic untouched) |
| HLS bis | — | — | **nothing** (cadence preserved) |
| 14496-30 | §5.9(4) | presentation clipped to CT + sample duration | **port EN 303 560 §5.2.3.3**: active until the next document or MPA |
| 14496-30 | §5.3, §5.9(1) | times on the track timeline; begin may precede the sample | **nothing** — packagers must stop clipping (§3.2) |
| 14496-30 | §5.6 | sample "shall consist of an XML document" | under the new entry a sample may instead be a `ttmn` or `ttmb` box (§2.1); documents stay raw |
| 14496-30 | §6.6 | sample is one `vtte` or ≥1 `vttc` | add `vttn` no-change box |
| 14496-30 | §5.6 | "Every sample is therefore a sync sample" | require `trun`/`sdtp` sync signalling (Layer 2 only) |
| RFC 6381 / MP4RA (MP4 registration authority) | — | — | register new sample entry 4CC(s) |
| DASH-IF / DVB-DASH guidance | — | truncation "not needed" (TS 103 285 §11.7) | recommend unclipped, open-ended restatement plus the redundancy flag as the no-spec-change step (§3.2) |

Everything lands in one short standard, and the one semantic change — persistence until
superseded — is a port of deployed behaviour, with EN 303 560 and RFC 8759 as two
independent sources.

## 11. MoQ + LOCMAF — the floor disappears

### 11.1 LOCMAF removes the per-object overhead

`draft-einarsson-moq-locmaf` opens on exactly the problem §5 runs into:

> CMAF chunk headers have a size **starting at around 100 bytes**, which can be as large
> as, or larger than, the coded frame the chunk describes...

Its answer: one MOQT (MoQ Transport) group per CMAF segment, one Object per CMAF chunk;
the first Object of a group carries a full chunk head, subsequent Objects carry only the
differences against the previous chunk in the same group; `mdat` payloads pass through
unchanged and the 8-byte `mdat` header is reconstructed at the receiver rather than
sent. The reference implementation reports "a delta moof as small as **2 bytes**".

For this design the relevant clause is §"Empty delta":

> An empty delta property block (`properties_length == 0`) is valid and means **"no
> field changed since the previous chunk."** This is the steady-state case for
> sample-level fragmented streams. The on-wire object reduces to the delta header
> element plus the `mdat` payload.

A no-change subtitle object is therefore **~2 B delta header + the 8-byte no-change box
= ~10 bytes on the wire**, against ~120 B for the same thing as an HTTP/CMAF part.

### 11.2 Consequence: the cadence/cost tradeoff goes away

| Cadence `C` | HTTP/CMAF (~120 B) | MoQ + LOCMAF (~10 B) |
|---|---|---|
| 40 ms | ~24 kbps | **~2 kbps** |
| 200 ms | ~4.8 kbps | ~0.4 kbps |
| 500 ms | ~1.9 kbps | ~0.16 kbps |

The *finest* cadence over LOCMAF is cheaper than the *coarsest* sensible one over HTTP.
So over MoQ the subtitle track can simply run at video frame rate, and §5's 500 ms
compromise is an HTTP artefact rather than anything fundamental — an LL-HLS artefact,
more precisely. LL-HLS is request-bound (§5) and no chunk encoding changes that. LL-DASH
is byte-bound, and LOCMAF's encoding — tagged fields, delta chunk heads, receiver-side
reconstruction — depends on MoQ objects for nothing but framing. Carried inside an
LL-DASH segment response with per-chunk framing, it would move LL-DASH to the right-hand
column above. Nothing defines that today; it is a natural follow-on to the draft (§12).

It also retires the sparse-track question entirely. §11.4's high-water mark would make
sparsity *possible* over MoQ — but at ~2 kbps for a frame-rate cadence there is nothing
left to buy, and a regular cadence avoids every caveat below. **The answer everywhere is
regular and cheap; only the affordable cadence differs.**

### 11.3 The structure already lines up

Three of this design's rules are things LOCMAF independently requires:

| This design | LOCMAF |
|---|---|
| I-sample first in every segment (§2) | "The first moof-carrying Object of each group MUST be a full LOCMAF chunk so a subscriber tuning in at a group boundary has a complete reference" |
| Layer 2 prediction scoped to one segment — closed GOP (§6) | "Delta chunks reference the preceding chunk in the same group" |
| State recovery after loss | "When a receiver detects that Objects are missing within a group... it MUST NOT apply subsequent delta chunks; it resumes either at the next full LOCMAF chunk... or at the start of the next group" |

LOCMAF also already anticipates the §5 cadence point: *"Sparse tracks, such as subtitle,
event, or metadata tracks, are more likely to have groups that are not aligned with
video"* — the MoQ equivalent of a subtitle rendition running its own `PART-TARGET`.

So Layer 2's head/body split has an exact structural analogue one layer down, and the
same segment/group boundary serves both. Whether that means Layer 2 is redundant over
LOCMAF is worth testing: LOCMAF deltas the *chunk head*, not the `mdat`, so the IMSC
`<head>` boilerplate inside the payload is still sent in full every time. Layer 2 and
§3's unclipped documents remain the levers on payload; LOCMAF is the lever on container.

### 11.4 The high-water mark, if sparsity is ever wanted

MoQ has `TRACK_STATUS` / `TRACK_STATUS_OK` and a per-track `LARGEST_OBJECT`, and the WG
has hardened its trustworthiness — moq-transport PR #1621 *"Forbid relays from lying
about LARGEST_OBJECT"* closed ianswett's #1386. That is the primitive HTTP lacks: a
receiver-observable per-track high-water mark obtainable without receiving media, which
would make silence unambiguous (§1.2).

Given §11.2 this is now a curiosity rather than a requirement. If it is ever pursued,
the caveats stand and need checking against the current draft rather than wiki
summaries: `LARGEST_OBJECT` is a group/object ID rather than a media time; it arrives at
`SUBSCRIBE_OK`/`TRACK_STATUS`, so its use as a *continuous* watermark is unproven; the
bound must hold end-to-end through relays; and content latency is not transport latency
— live captioning runs seconds behind for human reasons, so MPA (§7) is still required.

### 11.5 Limitation

LOCMAF puts `subs` out of scope — *"Sub-sample information for image subtitle profiles
(e.g. `im1i`) is out of scope"*. IMSC **image** profile subtitles therefore do not ride
LOCMAF as specified. Text profiles are unaffected, which is what this design targets.

## 12. Open questions

1. **What does Shaka Packager emit today** from a teletext feed at LL chunk sizes?
   §0.3 establishes the mechanism from source; the missing piece is the measured
   restatement rate and byte cost on a real capture. That is the baseline this design is
   measured against and should be captured before anything else.
2. **What do real receivers do with an unrecognised no-change sample?** dash.js and
   shaka parse `stpp`/`wvtt` in JS, not through MSE, so this is player code. Likely
   benign (skip), but must be measured.
3. **Is a subtitle `PART-TARGET` different from video's deployed anywhere?** The spec
   appears to permit it and no cross-rendition constraint was found in bis-15, but real
   players may assume alignment.
4. **Do deployed renderers handle a begin earlier than the sample** as 14496-30 Figure 1
   describes — presenting as if seeked into the document — or do some treat the sample
   start as document time zero, Smooth Streaming style? The former is conformant; the
   latter would show a cue late or not at all.
5. **What has the ISO BMFF systems group produced** on CMAF Annex F's *"no generally
   supported semantic to represent 'missing' media in a track"* since 2023?
6. **Does a subtitle rendition at video's `PART-TARGET` create playlist-reload
   contention** in real LL-HLS clients? §5 says match the video part cadence; the added
   ~8 req/s is the cost to verify against actual player behaviour.
7. **VOD/DVR rewrite.** The origin could resolve no-change samples into long-duration
   samples once a segment completes, so the stored artifact is conformant today and only
   the live wire form is novel. Unclipped documents need no rewriting; only the sample
   table changes.
8. **Do players honour §5.9(3) redundancy, or detect identical documents?** The
   no-spec-change step of §3.2 depends on one or the other; dash.js and shaka may re-parse
   regardless.
9. **Can LOCMAF's chunk encoding be carried inside an LL-DASH segment response?** It
   depends on MoQ only for framing (§11.2). With per-chunk framing defined, LL-DASH would
   get the ~10 B chunk floor too, and frame-level subtitle updates with it.

## 13. Prototype plan

Moved to [`PROTOTYPE.md`](PROTOTYPE.md): the steps, what to measure, the test
environments (livesim2 for DASH, moqlivemock and warp-player for MoQ), the player fork
points in dash.js and shaka, and which of the questions in §12 each step answers.

## 14. References

Standards cited by clause number. ISO/IEC documents are copyrighted and are not
included in this repository.

- ISO/IEC 14496-12:2022 — ISO base media file format
- ISO/IEC 14496-30:2018 — Timed text and other visual overlays in ISO base media
  file format
- ISO/IEC 23000-19 — Common media application format (CMAF) for segmented media
- ISO/IEC 23001-18:2022 — Event message track format for the ISO base media file
  format
- ETSI EN 303 560 V1.1.1 — DVB-TTML: https://www.etsi.org/deliver/etsi_en/303500_303599/303560/01.01.01_60/en_303560v010101p.pdf
- ETSI TS 103 285 V1.4.1 — DVB-DASH: https://www.etsi.org/deliver/etsi_ts/103200_103299/103285/01.04.01_60/ts_103285v010401p.pdf
- EBU Tech 3381 — Carriage of EBU-TT-D in ISOBMFF: https://tech.ebu.ch/docs/tech/tech3381.pdf
- RFC 8759 — RTP Payload for Timed Text Markup Language (TTML):
  https://www.rfc-editor.org/rfc/rfc8759.html
- W3C TTML2, Annex I (epoch and media time): https://www.w3.org/TR/ttml2/
- Microsoft Smooth Streaming Protocol [MS-SSTR]:
  https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-sstr/ — and dash.js's
  handling of its relative TTML times:
  [`MssParser.js`](https://github.com/Dash-Industry-Forum/dash.js/blob/development/src/mss/parser/MssParser.js),
  [`TextSourceBuffer.js`](https://github.com/Dash-Industry-Forum/dash.js/blob/development/src/streaming/text/TextSourceBuffer.js)
- HTTP Live Streaming 2nd Edition, `draft-pantos-hls-rfc8216bis`:
  https://datatracker.ietf.org/doc/draft-pantos-hls-rfc8216bis/
- LOCMAF, `draft-einarsson-moq-locmaf`:
  https://datatracker.ietf.org/doc/draft-einarsson-moq-locmaf/ —
  reference implementation: https://github.com/Eyevinn/locmaf
- DASH-IF Low-Latency Live Community Review r8:
  https://dashif.org/docs/CR-Low-Latency-Live-r8.pdf
- moq-transport PR #1621 "Forbid relays from lying about LARGEST_OBJECT":
  https://github.com/moq-wg/moq-transport/pull/1621 — closing issue #1386:
  https://github.com/moq-wg/moq-transport/issues/1386
- Shaka Packager sources cited in §0.3:
  [`text_sample.h`](https://github.com/shaka-project/shaka-packager/blob/main/packager/media/base/text_sample.h),
  [`es_parser_teletext.h`](https://github.com/shaka-project/shaka-packager/blob/main/packager/media/formats/mp2t/es_parser_teletext.h),
  [`text_chunker.cc`](https://github.com/shaka-project/shaka-packager/blob/main/packager/media/chunking/text_chunker.cc),
  [`mp2t_media_parser.cc`](https://github.com/shaka-project/shaka-packager/blob/main/packager/media/formats/mp2t/mp2t_media_parser.cc)

