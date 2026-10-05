# Paint-model subtitles for LL-DASH, LL-HLS, and MoQ

![Seven subtitle parts in a row along a time axis: a complete document of about
1.3 kB is sent only in the parts where the words change, and an 8-byte no-change
sample in the four parts where they do
not.](figures/paint-model-cadence.svg)

Low-latency streaming sends video and audio in CMAF chunks, down to single
frames over LL-DASH and MoQ. Subtitles should be chunked the same way, so that
the text arrives with the picture it belongs to and every track has the same
chunk and segment boundaries. Today that costs a complete IMSC document in every
chunk — ~280 kbps and 25 XML parses a second at frame cadence — so subtitles are
left unchunked and fall up to a segment behind the picture. This proposal makes
an unchanged subtitle chunk an 8-byte "nothing changed" sample. IMSC and WebVTT
are unchanged, a teletext or live-subtitling source reaches the player at video's
own cadence, and a client parses only when the words actually change. Published
to collect comments before any standards contribution.

The changes are small, and they land in one standard. ISO/IEC 14496-30 gains
one rule — a document stays active until the next one supersedes it — and new
sample entries to carry the 8-byte box. ISOBMFF, CMAF and HLS need nothing: the
new track is offered beside an ordinary `stpp` track, which CMAF requires anyway,
so legacy players keep what they have. The
half that removes the latency needs no spec change at all: it is permitted
today, and already serving live streams in
[livesim2](https://github.com/Dash-Industry-Forum/livesim2/pull/337).

## The proposal

1. **Chunk subtitles like video and audio.** Keep the part or chunk cadence of
   the video, down to single frames, and when nothing has changed say so in 8
   bytes instead of repeating the document.
2. **Paint model: signal changes when they happen.** A document is sent when a
   cue appears, changes, or is cleared, and at no other time. The packager never
   waits for, guesses, or invents an end time.
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
and MoQ are alike: LL-DASH streams the chunks of a segment in one response, and
MoQ sends each chunk as an object, so neither needs a request per chunk and both
can run at single frames, bounded only by the ~100 B CMAF chunk header. They
differ in one thing. MoQ with CMSF can carry the chunks as LOCMAF (Low Overhead
CMAF), which cuts that header to a few bytes: a frame-level subtitle update then
costs about 10 bytes, and a track at 25 fps about 2 kbps. Nothing equivalent
exists for LL-DASH yet.

`DESIGN.md` is the short design; the full notes hold the rationale and budgets,
and `ALTERNATIVES.md` the roads not taken.

## The problem

Low-latency CMAF chunks video at frame granularity inside a 2 s segment, and
subtitles should follow. A live subtitle chunk can be written only when the
interval it covers ends, so a subtitle track with one fragment per segment is a
segment late, and players that wait for every track hold video and audio back
with it. Chunked at the video cadence, each interval is complete in every track
at the same time, and over MoQ each subtitle object goes out with its video
object. Subtitles today must either be chunked the same way, which costs a
complete TTML document per chunk, or not chunked at all, which is the DASH-IF
advice and leaves subtitles lagging video by up to a segment. Today there is
nothing in between. The live sources, teletext, DVB subtitles, CTA-608/708 and live
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
not registered.

The half that needs no new signalling — unclipped `begin`, an `end` written only in the
fragment where the cue ends, and the redundancy marking — is implemented and serving
live streams in [livesim2](https://github.com/Dash-Industry-Forum/livesim2/pull/337),
which chunks its generated `stpp` and `wvtt` tracks at the video chunk cadence. The §2
boxes have library support — `stpc`, `wvtc`, `ttmn`, `ttmb` and `vttn` read, written and
listed in mp4ff since v0.57.0
([#590](https://github.com/Eyevinn/mp4ff/pull/590)). livesim2 generates `stpc` and
`wvtc` tracks since v1.14.0
([#345](https://github.com/Dash-Industry-Forum/livesim2/pull/345)), and modified dash.js and
[Shaka Player](https://github.com/Eyevinn/shaka-player/tree/feat/paint-model-subtitles)
play them. moqlivemock publishes all four over MoQ, as CMAF and as LOCMAF, and
warp-player plays them (see [Demo](#demo)). The maximum period of activation (§7) is not
implemented yet. `PROTOTYPE.md` says what is measured and what is not.

## Demo

The tracks are served live over LL-DASH by livesim2, and over MoQ by moqlivemock.

### LL-DASH

Two pages play the same live livesim2 stream in the two players. Each shows the four
subtitle tracks side by side: `stpp`, `stpc`, `wvtt` and `wvtc`. For each track they
count the bytes of every segment, as CMAF and as LOCMAF, and the parsing work in the
player.

- [dash.js](https://192-46-234-23.ip.linodeusercontent.com/vod/dashjs-paint/samples/paint-model-subtitles/)
- [Shaka Player](https://192-46-234-23.ip.linodeusercontent.com/vod/shaka-paint/demo/paint-model-subtitles/)

Both open on `stpc` and on this stream: 2 s segments, 100 ms chunks, and cues of
3.456 s, so that cue changes fall inside chunks.

```
https://192-46-234-23.ip.linodeusercontent.com/livesim2/chunkdur_0.1/utc_head/timesubsdur_3456/timesubssegnr_0/timesubsstpp_en/timesubsstpc_en;body=1/timesubswvtt_en/timesubswvtc_en/testpic_2s/Manifest.mpd
```

Any other livesim2 URL can be pasted into the page's MPD field. The chunk duration
is its `chunkdur_` part, and `track=` in the page URL selects the starting track.

### MoQ

[moqlivemock](https://moqlivemock.demo.osaas.io/) publishes all eight subtitle
variants live: `stpp`, `stpc`, `wvtt` and `wvtc`, each as CMAF and as LOCMAF
(`subs_stpc_en` and `subs_stpc_en_locmaf`, and so on). They are in the CMSF
namespaces, `mlm/cmsf/clear` and the two encrypted ones, and not in the MSF namespace
`mlm/msf/clear`, which carries only LOC video and audio. A subtitle group holds one
chunk per video object, 25 a second, and each chunk is sent when the interval it
covers ends. [warp-player](https://moqlivemock.demo.osaas.io/warp-player/), from
v0.16.0, plays any one of them in step with the picture, and measures the bitrate
and parsing cost of all subtitle tracks side by side.

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
23001-18 by clause number; 14496-30 clauses are those of the 2018 edition as amended
by Amd 1:2022. These are copyrighted and are **not** included in
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
