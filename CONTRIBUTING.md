# Contributing

This repository holds design documents, not code. Contributions are comments,
corrections, and proposed wording changes.

## Commenting

- **Issues** are the primary channel. One topic per issue. Name the document
  and section (for example `DESIGN §4.2`) in the title so discussion can be
  tracked back to the text.
- When you disagree with a reading of an existing specification, quote the
  clause you rely on. The documents cite ISO/IEC, ETSI, W3C, and IETF texts by
  clause number, and precision there is what makes a comment actionable.
- Deployment data is especially valuable: what a real packager emits, what a
  real player does with an unknown box, measured bitrates from real teletext or
  CTA-608 captures. Say which product and version.

## Pull requests

- Keep a pull request to one change of substance so it can be discussed on its
  own.
- Markdown, wrapped at about 88 columns to match the existing text.
- Do not renumber sections in a pull request that also changes content; issues
  and earlier comments refer to section numbers.
- If a change resolves an issue, reference it in the description.

## What must not be committed

Standards documents from ISO/IEC, ETSI, and similar bodies are copyrighted.
Never commit them, even to a private fork. The `.gitignore` excludes
`references/` and `*.pdf` for this reason. Cite by document number and clause
instead.

## License

By contributing you agree that your contribution is licensed under the same
terms as the repository, CC BY 4.0 for text. Code contributions, if the
repository grows a prototype, will be under MIT in their own directory.

You also agree that your contribution may be submitted, in whole or in part and
without attribution, to standards bodies such as MPEG (ISO/IEC JTC 1/SC 29),
DASH-IF, W3C, and the IETF, under those bodies' contribution and IPR policies.
Published standards do not credit individual contributors, and this permission
is what lets text from this repository travel into one.
