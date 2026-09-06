# Paint-model subtitles for LL-DASH, LL-HLS, and MoQ

A proposal for carrying text subtitles (`stpp`/IMSC and `wvtt`) at low latency
without sending a complete document per chunk. Published to collect comments
before any standards contribution.

## The proposal

1. **Paint model: signal changes when they happen.** A document is sent when a
   cue appears, changes, or is cleared, and at no other time. The packager never
   waits for, guesses, or invents an end time.
2. **Allow frequent no-update signalling.** Keep the regular part or chunk
   cadence the player needs, and when nothing has changed say so in 8 bytes
   instead of repeating the document.
3. **Make TTML intervals in `stpp` open-ended.** A cue keeps its true `begin`
   and has no `end` until it is cleared, and a document stays active until the
   next one supersedes it. The first is already permitted by ISO/IEC 14496-30;
   the second is the one change to it.
4. **New no-change signalling for `stpp` and `wvtt`.** An empty 8-byte box as
   the sample, under a new sample entry so that legacy players never select the
   track.

The subtitle cadence then becomes a continuum, not a choice between whole
segments and nothing: the track can follow the video down to individual frame
fragments, at 8 bytes per unchanged fragment. What bounds the cadence differs by
transport. LL-HLS is bounded by requests, since every part costs a playlist
reload and a part fetch, so 250 ms parts are the sensible match there. LL-DASH
streams the chunks of a segment in one response and is bounded only by the ~100
B CMAF chunk header, which a LOCMAF-style (Low Overhead CMAF) compact chunk head
could cut to about 10 bytes. Over MoQ with LOCMAF that is the native form: a
frame-level subtitle update costs about 10 bytes, and a track at 25 fps about 2
kbps.

ISOBMFF, CMAF, and HLS need no changes. `DESIGN.md` is the short design; the
full notes hold the rationale and budgets, and `ALTERNATIVES.md` the roads not
taken.

## The problem

Low-latency CMAF chunks video at frame granularity inside a 2 s segment.
Subtitles today must either be chunked the same way, which costs a complete TTML
document per chunk, or not chunked at all, which is the DASH-IF advice and
leaves subtitles lagging video by up to a segment. Today there is nothing in
between. The live sources, teletext, DVB subtitles, CTA-608/708 and live
captioning, are paint-model: state persists until replaced, and a cue's end is
unknown when it starts. ISOBMFF timed text is interval-model: a document lives
exactly as long as its sample. Converting between the two is what makes today's
packaging expensive.

## Documents

| File | What it is |
|---|---|
| [`DESIGN.md`](DESIGN.md) | **The design, short.** Start here. |
| [`DESIGN-ll-paint-model.md`](DESIGN-ll-paint-model.md) | **The design, in full.** Rationale, cadence selection, byte and parse budgets, MoQ/LOCMAF mapping, open questions. |
| [`ALTERNATIVES.md`](ALTERNATIVES.md) | **Roads not taken.** Sample-relative timing and anchor boxes; cue identity via `xml:id`; box-wrapped `stpp` documents. What each would give and cost, and why the proposal does without them. |
| [`RESEARCH.md`](RESEARCH.md) | **Background survey.** What 14496-30, ISOBMFF, IMSC, DVB-TTML, EBU-TT Live and DASH-IF provide today, and eight approaches (A to H) for reducing per-fragment size. |
| [`PROTOTYPE.md`](PROTOTYPE.md) | **Prototype and test plan.** What to measure, steps, test environments, player fork points. |

## Status

Early draft. Nothing here has been submitted to MPEG, DASH-IF, W3C TTWG (Timed
Text Working Group), or the IETF MoQ (Media over QUIC) working group. The 4CCs
used (`stpc`, `wvtc`, `ttmn`, `ttmb`, `vttn`) are placeholders and are
not registered. No prototype exists yet; `PROTOTYPE.md` is the plan.

## How to comment

Comments of every kind are welcome: errors in how existing specs are read,
missing prior art, deployment experience that contradicts an assumption, or
alternative designs.

- **Open an issue** for a comment on a specific section. Quote the section
  number so it can be tracked. An issue template is provided.
- **Open a pull request** for concrete wording changes.
- Player, packager, and device implementers: the open questions in §12 of the
  design are the places where real-world data is most needed.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for conventions.

## Standards referenced

The documents cite ISO/IEC 14496-12, 14496-30, 23000-19 (CMAF), 23001-17 and
23001-18 by clause number. These are copyrighted and are **not** included in
this repository; obtain them from ISO. ETSI EN 303 560, the W3C IMSC
specifications, the DASH-IF low-latency guidance, and the IETF drafts are
publicly available and are linked from the documents' reference sections.

## Related work

- [LOCMAF](https://datatracker.ietf.org/doc/draft-einarsson-moq-locmaf/),
  low-overhead CMAF for Media over QUIC. The MoQ section of the design builds on
  it. Reference implementation: [Eyevinn/locmaf](https://github.com/Eyevinn/locmaf).


## License

The text in this repository is licensed under
[Creative Commons Attribution 4.0 International](LICENSE) (CC BY 4.0).
Prototype code, when added, will live in its own directory under the MIT
license.

## Author

Torbjörn Einarsson, [Eyevinn Technology](https://www.eyevinn.se).
