# Prototype and test plan

How to try the paint-model design and measure it. The design itself is in
[`DESIGN.md`](DESIGN.md); the rationale, budgets and open questions are in
[`DESIGN-ll-paint-model.md`](DESIGN-ll-paint-model.md). Section numbers below refer to
the full notes.

**Status.** Steps 1 to 5 and 7 are done, except the maximum period of activation (§7),
which no implementation has yet. Steps 6 and 8 are plan. What exists is marked below.

## 1. What to measure

- **Bytes per second** for the subtitle track, against the §9 table: naive chunked
  `stpp`, unchunked 1 s segments, and the design with and without the head/body split.
- **Samples per chunk** and the `trun` layout, to confirm one document per chunk for
  `stpp` and the split only for `wvtt` (§2.3, §5).
- **XML parses per second** at the receiver, against §9.1: once per content change, not
  once per chunk, and zero for restated identical documents.
- **Receiver behaviour** on the new sample entries, on `ttmn` and `vttn`, and on a document
  whose `begin` precedes its sample (§12 questions 2, 4, 8).

## 2. Steps

1. **ISOBMFF library.** Add the `stpc` and `wvtc` sample entries and the `ttmn`, `ttmb`
   and `vttn` boxes to mp4ff, write multi-sample fragments (I-sample plus no-change
   samples) and confirm they round-trip with correct sample times. **Done**, in
   [mp4ff #590](https://github.com/Eyevinn/mp4ff/pull/590), released in v0.57.0:
   `stpc` and `wvtc` reuse `StppBox` and `WvttBox` with a name field, as the visual
   sample entries already do; `ttmn`, `vttn` and `ttmb` are whole-sample boxes; a sample
   is one of them only if its first eight bytes are that box header with a size equal to
   the sample size; and `mp4ff-subslister` renders them instead of dumping opaque bytes.
   A test writes a four-sample fragment — document, `ttmn`, `ttmb`, `ttmn`, 200 ms each,
   the first a sync sample and the rest depending on it — and reads the sample times
   back. The 4CCs are the design's placeholders and are not registered with MP4RA. mp4ff
   also carries `rsot` (§3.6), which is the other mechanism rather than a step towards
   this one: https://github.com/Eyevinn/mp4ff/pull/589
2. **Generator.** A paint-model subtitle track from a synthetic source whose text changes
   every N seconds: an I-sample per segment, a document per change — for `stpp` one
   document per chunk with true `begin` and `end`, for `wvtt` a split chunk — and a
   no-change sample per chunk at cadence `C`. Produce today's packaging from the same
   source as the baseline. **Done**, in livesim2 v1.14.0
   ([#345](https://github.com/Dash-Industry-Forum/livesim2/pull/345)) and moqlivemock
   v0.16.0. livesim2's `timesubsstpc_` and `timesubswvtc_` generate the same cues on the
   same timeline as `timesubsstpp_` and `timesubswvtt_`; `;nochange=0` is a control that
   differs from `stpp` only in the 4CC. moqlivemock's `-subsstpc` and `-subswvtc` do the
   same over MoQ.
3. **Stop clipping, measured alone.** On the baseline stream, compare the
   identical-document rate and compression with clipped and unclipped `begin`/`end`
   (§3.2). Needs no new box and nothing on the sending side; rendering it correctly on
   shaka needs the fix of §12 question 4. **Done**, in [livesim2
   #337](https://github.com/Dash-Industry-Forum/livesim2/pull/337): the generated `stpp`
   and `wvtt` tracks are chunked at the video chunk cadence, cues keep their true
   `begin`, an `end` appears only in the fragment where the cue ends, and every
   byte-identical restatement is marked `sample_depends_on=2` +
   `sample_has_redundancy=1`. At 2 s segments and 200 ms chunks, eight of ten chunks per
   segment are identical restatements. Bytes per 2 s segment on `testpic_2s`: `stpp`
   1745 B unchunked against 15922 B chunked (~7.0 against ~63.7 kbps), `wvtt` 282 B
   against 1582 B (~1.1 against ~6.3 kbps) — a second data point beside §9's broadcast
   measurements, on a ~1.6 kB synthetic document.
4. **Player fork.** dash.js and shaka: accept the new codecs strings, apply the paint
   rule (a document stays active until the next one or MPA), handle `ttmn` and `vttn`,
   and count parser calls. First probe what the unmodified players do with the new
   tracks. *The probe is done for unclipped chunked tracks*, against livesim2 #337, and
   answers §12 questions 4 and 8: dash.js renders them correctly, one cue per real cue;
   shaka clips to the segment rather than the sample and shows two captions at once;
   neither reads the sample flags, so both re-parse every sample. **The fork is done**,
   except the MPA: a modified dash.js, served by the demo page, and
   [Shaka Player](https://github.com/Eyevinn/shaka-player/tree/feat/paint-model-subtitles)
   play `stpc` and `wvtc`, and only tracks that declare them get the new behaviour. A
   no-change sample restates the cues already parsed and parses nothing, and the pages
   count what each player parses: 20 documents per 2 s segment for `stpp` at 100 ms
   chunks, 2.0 for `stpc` with `ttmb`.
5. **Layer 2.** `ttmb` body samples, `<head>` splicing from the segment's I-sample, and
   the non-sync flags (§6). **Done**: livesim2 sends `ttmb` with `;body=1` and marks
   no-change and body samples `sample_is_non_sync_sample = 1` and `sample_depends_on = 1`;
   moqlivemock sends `ttmb` by default (`-subsstpcbody`); and dash.js, Shaka Player and
   warp-player splice the body into the head of the segment's or group's first document.
6. **Real captures.** Teletext, DVB subtitles and CTA-608, not subtitle files: measure
   the real change rate, and the restatement rate today's converters produce from the
   same capture (§12 question 1; §0.3 for Shaka Packager).
7. **MoQ.** Run the same generator through moqlivemock and play it in warp-player; measure
   LOCMAF object sizes at frame-rate cadence against §11.2. *Publishing and playback are
   done*: moqlivemock serves all four tracks as CMAF and as LOCMAF, one object per video
   object, and warp-player v0.16.0 plays them and measures each track's bitrate and
   parsing cost side by side (§3). **Measured**, in moqlivemock's README, on its 25 fps
   content with 1 s groups and a cue for 900 ms of every second:

   | Track | CMAF | LOCMAF |
   |---|---|---|
   | `stpp` | 317 kbps | 296 kbps |
   | `stpc` | 38 kbps | 17 kbps |
   | `wvtt` | 35 kbps | 14 kbps |
   | `wvtc` | 25 kbps | 4.5 kbps |

   The CMAF figure for `wvtc` matches §11.2's ~24 kbps at 40 ms. The LOCMAF figure is
   above §11.2's ~2 kbps, which is for a track where nothing changes; here a cue starts
   and ends every second, and every 1 s group starts with a full chunk.
8. **Separately**, evaluate the MoQ sparse variant against §11.4's caveats. It is a
   different design, not a later stage of this one.

Steps 1 to 4 need no spec change to try. Step 3 needs none at all to measure.

## 3. Test environments

**DASH: livesim2** (DASH-Industry-Forum). It synthesises `stpp` and `wvtt`
time-subtitle tracks on the fly (`timesubsstpp_<langs>`, `timesubswvtt_<langs>`), and
since #337 chunks them like audio and video when `chunkdur_` is set. Since v1.14.0,
`timesubsstpc_<langs>` and `timesubswvtc_<langs>` generate the paint-model tracks from the
same cues, so the §9 comparison is two URL parameters side by side. It is DASH only.

**MoQ: moqlivemock and warp-player** (Eyevinn). moqlivemock's subtitle generator is the
same code lineage as livesim2's. It publishes `stpp`, `stpc`, `wvtt` and `wvtc`, each as
CMAF and as LOCMAF, eight tracks in all, in the CMSF namespaces but not the MSF one. Every
subtitle track has the video's object rate: a group holds one chunk per video object, 25 a
second, sent when the interval it covers ends. Its issue #140, from a Shaka Player
maintainer, asked for LOCMAF subtitles and was closed on 2026-09-29; the paint model is
what makes them worthwhile, since no-change objects at video cadence give LOCMAF's delta
heads something to compress. warp-player has an MSE path for CMAF and LOCMAF, and from
v0.16.0 renders the subtitle tracks, `stpc` and `wvtc` included: TTML through imscJS, as
dash.js does, and WebVTT with its own renderer. Its issue #167, still open, asks to show
that its overlay seam fits WebVTT, IMSC and ograf. Both run publicly at
https://moqlivemock.demo.osaas.io/ — the live publisher, LOCMAF, CMAF and LOC streams, and
the browser player under `/warp-player/` — so a reviewer can see the MoQ side without
building anything; the page is generated from the `moq-workspace` repository.

**LL-HLS.** None of the above serves HLS. The request-bound regime and the `PART-TARGET`
questions (§12 questions 3 and 6) need an LL-HLS packager and player later.

**Real captures.** A teletext or DVB-subtitle transport stream through Shaka Packager
gives today's restatement behaviour (§0.3) and the real change statistics for step 6.

## 4. Player fork points

Both players parse text tracks in JavaScript, outside MSE, so the changes are local.

**dash.js**, `src/streaming/text/TextSourceBuffer.js`:

- The TTML path hands the parser each sample's start and end, `sampleStart` and
  `sampleStart + sample.duration`. That is 14496-30 §5.9(3) in code. For `stpc` the end
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
| 4. Receivers and a `begin` earlier than the sample | 4 — **partly answered** |
| 7. VOD/DVR rewrite of no-change samples | 2 |
| 8. Redundancy flag and identical-document detection | 3, 4 — **answered** |
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
