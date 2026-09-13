# Pick the test book

Type: task
Status: resolved
Blocked by: (none)

## Question

Pick the actual short French public-domain text (or story) this prototype
will be validated against. Needs: multiple named characters with real
dialogue exchanges (to exercise Speaker attribution and the Cast), short
enough to be a quick end-to-end test (a short story or novella, not a full
novel), and a clean legitimately-obtainable source (e.g. Wikisource,
Project Gutenberg) in EPUB or plain text.

This is a HITL task: the agent can propose candidates, but the actual pick
is the user's call. Record the chosen title, source URL, and the file
format obtained (EPUB vs raw text) as the answer.

## Answer

User already had the file: `samples/Les misérables Tome I Fantine.epub`
(Victor Hugo, "Fantine", the first tome of *Les Misérables* — public
domain, EPUB format). Confirmed present at
`/home/jerome/Documents/dev/audio-book-generator/samples/Les misérables Tome I Fantine.epub`.

Note: this is a full tome (hundreds of pages across dozens of chapters),
much larger than the "short story" scale discussed during destination
setting. User has since narrowed the POC scope accordingly (see map
Destination, updated): **only the first chapter of Fantine** is
transcribed/synthesized for this prototype, not the whole tome. This
resolves the runtime-budget pressure this note originally flagged — the
whole-book "Not yet specified" fog item can stay low-priority again.

**Correction (found while resolving the parsing-design ticket)**: chapter
numbering in this book resets per *Livre* (Book/Part) — "Chapitre I"
appears once under *Livre premier* and again, separately, under *Livre
deuxième*. An earlier extraction accidentally grabbed the *Livre deuxième*
occurrence (the well-known Jean Valjean arrival scene, "Le soir d'un jour
de marche," 3,925 words/171 paragraphs/87 em-dashes) instead of the true
first chapter. **The actual "Chapter 1" for this POC is *Livre premier,
Chapitre I: "Monsieur Myriel"*** — 963 words, 16 paragraphs, 2 em-dashes
(confirmed via ebooklib/BeautifulSoup, spine item 0, the h2 "Chapitre I"
at document position immediately following the "Livre premier—Un juste"
heading, up to the next h2 "Chapitre II"). This is the correct target
going forward; ticket 01's runtime estimate has been corrected too.

Status: resolved
