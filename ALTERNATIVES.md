# Alternatives considered

Mechanisms weighed for the paint-model design and left out of the proposal. Each entry
says what it would give, what it would cost, and why the proposal does without it.
`RESEARCH.md` covers the size-reduction approaches (A to H) separately.

## 1. Taking the timeline out of the document

Two families of mechanism make documents position-independent by construction rather
than by discipline. Neither is needed here, but both are precedents worth knowing.

**A fixed mapping — document time zero is the sample start.** Microsoft Smooth Streaming
does this: TTML times inside a fragment are relative to the fragment start. It is
deployed at scale and *implicit* — nothing in the file says so, which is why dash.js has
to special-case it (`MssParser` sets `ttmlTimeIsRelative`; `TextSourceBuffer` adds the
sample start to every TTML time only for Smooth content). RFC 8759 does the same
normatively for TTML over RTP, §6: *"Each TTML document becomes active at its epoch E. E
MUST be set to the RTP Timestamp... Computed TTML media times are offset relative to E, in
accordance with Section I.2 of [TTML2]."* TTML2 Annex I defines that epoch as supplied by
the external context, so the hook exists in the W3C model. RFC 8759 §6 also carries the
supersession rule the proposal ports in `DESIGN-ll-paint-model.md` §4.

**A free mapping — the wire says which document time is the sample start.** DVB-TTML's
`segment_mediatime` (EN 303 560 §5.2.4.1: *"TTML documents are authored with their own
timeline... a segment mediatime field... allows the conversion between the TTML and MPEG
timelines"*), and in 14496-30 itself `wvtt`'s `ctim` (§6.6), which appears only when a
cue payload carries inline cue timestamps and gives *"the VTT timestamp associated with
the start time of sample"*.

| | Track timeline, unclipped (`DESIGN-ll-paint-model.md` §3.2) | Fixed: time zero = sample start | Free: anchor field |
|---|---|---|---|
| Spec change | none | §5.3 semantics under the new entry | new box |
| Bytes per document | none | none | ~16 B |
| Restated untimed or open-ended cue byte-identical | yes | yes | yes |
| Restated *timed* document byte-identical | yes | no — must be re-based | yes |
| Document portable across a timeline shift | via edit list, as today | yes | yes |
| Renderer must accept an external time origin | no | yes | yes |
| Precedent | 14496-30 §5.9 as written | Smooth Streaming, RFC 8759, TTML2 Annex I | EN 303 560, `wvtt` `ctim` |

The unclipped track timeline wins on every row that matters. The only thing the others
buy is portability across a timeline shift without an edit list, which `stpp` has never
had and nobody has asked for; the fixed mapping additionally contradicts EBU Tech 3381
§6 and DASH-IF IOP (Interoperability Points) §6.4.5, loses byte-identity for timed
documents, and requires every renderer to accept an epoch — a real deployment risk on
native and TV pipelines. Should a future profile want either, both are precedented; this
design does not need them.

## 2. Cue identity across documents (`xml:id`)

**The concern.** When a cue persists across a segment boundary the next segment's
I-sample restates it. A receiver that treats every document as new content might tear
the cue down and redraw it, or restart an animation. EN 303 560 §5.2.3.6 warns that a
subtitle *"present in multiple document chunks may not necessarily have identical timing
information"* and that *"it is not recommended to use timing information to match
subtitles"*, and §5.2.3.3 asks IRDs (integrated receiver decoders) to *"avoid
intermittent removal of the subtitle from the screen at the segment boundaries"* — but
defines no mechanism. `wvtt` has one: `vsid`, whose `source_ID` match *"is diagnostic
that the same cue is still active"* (14496-30 §6.6). The `stpp` analogue would be a
stable `xml:id` on each `<p>`, made normative under the new sample entry, with packagers
minting ids for paint sources that have none — per teletext page display, per CTA-608
caption.

**Why the proposal does without it.**

- TTML has no cross-document element identity. A renderer draws each intermediate
  synchronic document (ISD) as a frame; a new document with the same text redraws
  identically, exactly as at every ISD boundary inside one document today. There is no
  object to tear down.
- The restatement case is already covered. Unclipped documents are byte-identical
  (`DESIGN-ll-paint-model.md` §3), so the §5.9(3) redundancy flag or identical-document
  detection lets the receiver skip the whole document — stronger than matching one cue
  inside it.
- The `wvtt` analogy is weaker than it looks. WebVTT renders cue objects with enter and
  exit behaviour, so a restated cue without `vsid` would be a new `TextTrackCue` and could
  re-layout. IMSC has no such object model.
- Minting ids from paint sources adds packager complexity and a failure mode: a stale id
  carried across a text change could stop a renderer from updating.

**When it would matter.** Structured deltas — "append this text to cue N" — need cue
identity, and the proposal leaves them out of scope (`DESIGN-ll-paint-model.md` §5.2). So
would a renderer that keeps per-element state across documents. Packagers may carry a
stable `xml:id` and receivers may use it; nothing in the proposal depends on it.

## 3. Wrapping every `stpp` sample in a box (`ttmd`)

**What it would give.** Uniformity with `wvtt` and `evte`: every sample under the new
entry would begin with a box header, and a receiver would dispatch on the box type without
looking at payload bytes. The proposal's first draft did this, with a `TTMLDocumentBox`
(`ttmd`) around each document beside `ttmn` and `ttmb`.

**Why the proposal does without it.**

- It changes the one thing about `stpp` that every packager and player already handles. A
  raw-document sample under the new entry is byte for byte an `stpp` sample; a wrapped one
  is not, and the sub-sample rules for images would have to be restated around the box.
- It buys nothing at the receiver. The test for the no-change marker is the same eight
  bytes either way, and because IMSC mandates UTF-8 a document can never begin with the
  0x00 of a box size, so raw-versus-box is exact without a wrapper.
- Raw XML samples have their own precedent in 14496-12's `metx` metadata tracks, and an
  empty box as a whole sample has `emeb`. Mixing the two in one sample format is new; the
  cost is one normative sentence stating the dispatch rule.

If reviewers prefer uniformity, the wrapper is a one-sentence change to the proposal and
nothing else moves.

## References

- ISO/IEC 14496-30:2018 — Timed text and other visual overlays in ISO base media file
  format
- ETSI EN 303 560 V1.1.1 — DVB-TTML: https://www.etsi.org/deliver/etsi_en/303500_303599/303560/01.01.01_60/en_303560v010101p.pdf
- EBU Tech 3381 — Carriage of EBU-TT-D in ISOBMFF: https://tech.ebu.ch/docs/tech/tech3381.pdf
- RFC 8759 — RTP Payload for TTML: https://www.rfc-editor.org/rfc/rfc8759.html
- W3C TTML2, Annex I (epoch and media time): https://www.w3.org/TR/ttml2/
- Microsoft Smooth Streaming Protocol [MS-SSTR]:
  https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-sstr/ — and dash.js's
  handling of its relative TTML times:
  [`MssParser.js`](https://github.com/Dash-Industry-Forum/dash.js/blob/development/src/mss/parser/MssParser.js),
  [`TextSourceBuffer.js`](https://github.com/Dash-Industry-Forum/dash.js/blob/development/src/streaming/text/TextSourceBuffer.js)
- DASH-IF IOP v4.3 §6.4.5 (TTML timing in segments is on the media timeline)
