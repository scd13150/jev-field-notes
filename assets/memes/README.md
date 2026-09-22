# Memes

One image, and it is load-bearing.

![anyone got spare tokens?](spare_tokens.jpg)

**anyone got spare tokens?**

The template is the Sage-glasses stock meme, captioned with the line from the source: *who has spare
funds?* The caption here is the same question asked of whoever holds the API budget.

It is here because of a specific number reported in
[`../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md):
the study ran **8,000 calls and 17.2 M input tokens for $0.72**, at the published rate of **$42 per
billion input tokens with output unbilled**. That is a genuinely unusual price for this kind of work,
and it is the reason a pipeline like this is affordable to run at all — but it does mean the honest
answer to "why did you stop measuring?" is sometimes this meme.

Shared at the suggestion of the TypeSafe team, who asked for memes when the trial was granted.

## Why the caption is in English

The audience for this repository is an English-speaking engineering team. A Chinese-only caption is a
joke they cannot read, which defeats the point of including it — it would be a picture with no punch
line. The Chinese original (谁还有多余token) is the same joke, but only lands for a reader who reads
Chinese, so it is not what ships.

## Why two lines

The full question on a single line tops out around **76 px** at this image width, which is far too
small to carry a meme — it reads as a subtitle, not a caption. Splitting it over two lines allows
**142 px**, which is the treatment the original used. `make_meme.py` computes the largest size at
which every line still fits and refuses to render rather than shrinking silently.

## Provenance

The base image is a third-party meme template and **is not redistributed here** — only the captioned
result is. `make_meme.py` regenerates this exact file and takes the base as an argument, so the
treatment is reproducible without shipping someone else's artwork:

```bash
python make_meme.py path/to/base.jpg
```

The committed JPEG is byte-reproducible from that command.

The treatment was picked by comparing candidates on the real image rather than guessing:
white-on-black, black-on-white and gold-on-black were all rendered and inspected. Gold won because it
repeats the chain and watch accents already in the frame and keeps contrast against the navy suit,
where black text merged into the shirt on the left edge.
