# Memes

One image, and it is load-bearing.

![谁还有多余token](spare_tokens.jpg)

**谁还有多余token** — "anyone got spare tokens?"

The template is the Sage-glasses stock meme, captioned with the line from the source: *who has spare
funds?* The caption here is the same question asked of whoever holds the API budget.

It is here because of a specific number reported in
[`../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md`](../../papers/JEV_EMPIRICAL_BOUNDARY_ANALYSIS.md):
the study ran **8,000 calls and 17.2 M input tokens for $0.72**, at the published rate of **$42 per
billion input tokens with output unbilled**. That is a genuinely unusual price for this kind of work,
and it is the reason a pipeline like this is affordable to run at all — but it does mean the honest
answer to "why did you stop measuring?" is sometimes this meme.

Shared at the suggestion of the TypeSafe team, who asked for memes when the trial was granted.

## Provenance

The base image is a third-party meme template and **is not redistributed here** — only the captioned
result is. `make_meme.py` regenerates this exact file and takes the base as an argument, so the
treatment is reproducible without shipping someone else's artwork:

```bash
python make_meme.py path/to/base.jpg
```

The caption treatment was picked by comparing candidates on the real image rather than guessing:
white-on-black, black-on-white and gold-on-black were all rendered and inspected. Gold won because
it repeats the chain and watch accents already in the frame and keeps contrast against the navy suit,
where black text merged into the shirt on the left edge.
