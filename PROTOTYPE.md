# Prototype and test plan

How to try the paint-model design and measure it. The design itself is in
[`DESIGN.md`](DESIGN.md); the rationale, budgets and open questions are in
[`DESIGN-ll-paint-model.md`](DESIGN-ll-paint-model.md). Section numbers below refer to
the full notes.

## 1. What to measure

- **Bytes per second** for the subtitle track, against the §9 table: naive chunked
  `stpp`, unchunked 1 s segments, and the design with and without the head/body split.
- **Samples per part** and the `trun` layout, to confirm one document per part for `stpp`
  and the split only for `wvtt` (§2.3, §5).
- **XML parses per second** at the receiver, against §9.1: once per content change, not
  once per chunk, and zero for restated identical documents.
- **Receiver behaviour** on the new sample entries, on `ttmn` and `vttn`, and on a document
  whose `begin` precedes its sample (§12 questions 2, 4, 8).

## 2. Steps

1. **ISOBMFF library.** Add the `stpc` and `wvtc` sample entries and the `ttmn`, `ttmb`
   and `vttn` boxes to mp4ff, write multi-sample fragments (I-sample plus no-change
   samples) and confirm they round-trip with correct sample times.
2. **Generator.** A paint-model subtitle track from a synthetic source whose text changes
   every N seconds: an I-sample per segment, a document per change — for `stpp` one
   document per part with true `begin` and `end`, for `wvtt` a split part — and a
   no-change sample per chunk at cadence `C`. Produce today's packaging from the same
   source as the baseline.
3. **Stop clipping, measured alone.** On the baseline stream, compare the
   identical-document rate and compression with clipped and unclipped `begin`/`end` (§3.2).
   Needs no player change and no new box.
4. **Player fork.** dash.js and shaka: accept the new codecs strings, apply the paint rule
   (a document stays active until the next one or MPA), handle `ttmn` and `vttn`, and
   count parser calls. First probe what the unmodified players do with the new tracks.
5. **Layer 2.** `ttmb` body samples, `<head>` splicing from the segment's I-sample, and
   the non-sync flags (§6).
6. **Real captures.** Teletext, DVB subtitles and CTA-608, not subtitle files: measure
   the real change rate, and the restatement rate today's converters produce from the
   same capture (§12 question 1; §0.3 for Shaka Packager).
7. **MoQ.** Run the same generator through moqlivemock and play it in warp-player; measure
   LOCMAF object sizes at frame-rate cadence against §11.2.
8. **Separately**, evaluate the MoQ sparse variant against §11.4's caveats. It is a
   different design, not a later stage of this one.

Steps 1 to 4 need no spec change to try. Step 3 needs none at all to measure.

## 3. Test environments

**DASH: livesim2** (DASH-Industry-Forum). It already synthesises `stpp` and `wvtt`
time-subtitle tracks on the fly (`timesubsstpp_<langs>`, `timesubswvtt_<langs>`), one
document per segment, and it chunks audio and video for low latency (`chunkdur`). The text
tracks are not chunked today, which is the gap to fill: a `paintsubs` variant of the
generator, with the text track honouring `chunkdur` and chunked transfer. The existing
`timesubs` tracks with the same content are the baseline, so the §9 comparison is two URL
parameters side by side. It is DASH only.

**MoQ: moqlivemock and warp-player** (Eyevinn). moqlivemock's subtitle generator is the
same code lineage as livesim2's and produces time-aligned `stpp` and `wvtt` groups, one
object per group today. Its issue #140, from a Shaka Player maintainer, asks for LOCMAF
subtitles; the paint model is what makes them worthwhile, since no-change objects at
video cadence give LOCMAF's delta heads something to compress. warp-player has an MSE
path for CMAF and LOCMAF and an overlay seam with CTA-608 as its first renderer; its
issue #167 asks to show the seam fits WebVTT and IMSC, which is where a paint-model cue
source would plug in. Both run publicly at https://moqlivemock.demo.osaas.io/ — the live
publisher, LOCMAF, CMAF and LOC streams, and the browser player under `/warp-player/` —
so a reviewer can see the MoQ side without building anything; the page is generated from
the `moq-workspace` repository.

**LL-HLS.** None of the above serves HLS. The request-bound regime and the `PART-TARGET`
questions (§12 questions 3 and 6) need an LL-HLS packager and player later.

**Real captures.** A teletext or DVB-subtitle transport stream through Shaka Packager
gives today's restatement behaviour (§0.3) and the real change statistics for step 6.

## 4. Player fork points

Both players parse text tracks in JavaScript, outside MSE, so the changes are local.

**dash.js**, `src/streaming/text/TextSourceBuffer.js`:

- The TTML path hands the parser each sample's start and end, `sampleStart` and
  `sampleStart + sample.duration`. That is 14496-30 §5.9(4) in code. For `stpc` the end
  must stay open until the next document or MPA.
- The same path adds each sample's range to `buffered`; no-change samples must still
  extend it, so the text track never becomes the gating track.
- The WebVTT path dispatches on `vtte` and `vttc`; `vttn` is a third branch.
- The codec check matches on the string `stpp`; `stpc` and `wvtc` must be accepted.
- Smooth Streaming's sample-relative TTML times are already special-cased there
  (`ttmlTimeIsRelative`), which shows the pipeline can shift document time origins if a
  future profile ever needs it.

**shaka-player**, `lib/text/`:

- `ttml_text_parser.js` clamps cue start and end to the segment (`segmentStart`,
  `segmentEnd`). For `stpc` the end clamp must move to the next document or MPA.
- `mp4_ttml_parser.js` parses one document per sample; unchanged for raw documents,
  and the place to recognise `ttmn` and `ttmb`.
- `mp4_vtt_parser.js` dispatches on `vttc` and `vtte`; `vttn` is a third branch.

## 5. Which open questions each step answers

| §12 question | Step |
|---|---|
| 1. What Shaka Packager emits from teletext at LL chunk sizes | 6 |
| 2. What receivers do with an unrecognised no-change sample | 4 |
| 3, 6. Subtitle `PART-TARGET` and playlist-reload contention in LL-HLS | later, HLS tooling |
| 4. Receivers and a `begin` earlier than the sample | 4 |
| 7. VOD/DVR rewrite of no-change samples | 2 |
| 8. Redundancy flag and identical-document detection | 3, 4 |
| 9. LOCMAF chunk encoding inside an LL-DASH response | 7 |

## Links

- livesim2: https://github.com/Dash-Industry-Forum/livesim2
- moqlivemock: https://github.com/Eyevinn/moqlivemock — hosted demo:
  https://moqlivemock.demo.osaas.io/ — issue #140:
  https://github.com/Eyevinn/moqlivemock/issues/140
- warp-player: https://github.com/Eyevinn/warp-player — issue #167:
  https://github.com/Eyevinn/warp-player/issues/167
- mp4ff: https://github.com/Eyevinn/mp4ff
- dash.js: https://github.com/Dash-Industry-Forum/dash.js
- shaka-player: https://github.com/shaka-project/shaka-player
- Shaka Packager: https://github.com/shaka-project/shaka-packager
- LOCMAF: https://datatracker.ietf.org/doc/draft-einarsson-moq-locmaf/
