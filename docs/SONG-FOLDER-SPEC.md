# Vault Rehearsal — Song Folder Spec (upload-ready structure)

This is the exact on-disk layout the helper tool must produce for one song. The
whole folder is uploaded verbatim into the public Supabase Storage bucket
**`songs`**, under the object-path prefix `songs/`. Nothing is renamed on upload —
**the folder name on disk becomes the song id, the storage path, and the primary
key of the `songs` table.**

Source of truth: `scripts/batch-chunk.sh` (produces this), `scripts/upload-song.py`
(uploads it + writes the table row), `scripts/seed-sections.py` (sections.json),
and `webapp/index.html` (the player that reads it back).

---

## 1. Top-level folder = the song id

```
<song name>-<album>-<original key>-<bpm>/
```

Rules (enforced by the catalog parser in `batch-chunk.sh`):

- **`<song name>`** — must **not** contain a hyphen `-` (the parser splits on `-`).
- **`<album>`** — may contain hyphens.
- **`<original key>`** — a musical key token, copied through exactly, capitals kept
  (`D`, `E`, `C`, `A`, `Bb`, `F#`, …). Must match one of the key sub-folders (below);
  if it doesn't, the first key folder is used instead.
- **`<bpm>`** — integer, the **last** `-`-separated token, digits only.
- Parser logic: split on `-`; last token = bpm (must be all digits), second-to-last =
  original key, first = title, everything in between = album.

Example:
```
What A Beautiful Name-let there be light-D-68/
```
→ title `What A Beautiful Name`, album `let there be light`, originalKey `D`, bpm `68`.

The folder name is used raw as a storage path segment and URL-encoded when fetched,
so keep it filesystem- and URL-safe: **no slashes**, avoid characters that need
heavy escaping. It must be unique (it's the table primary key).

> If a folder name does **not** match this `<song>-<album>-<key>-<bpm>` pattern, the
> upload still works but the title/album/bpm/key must be filled in by hand in the
> catalog draft (see §6). Matching the pattern is what makes the tool zero-touch.

---

## 2. One sub-folder per key

```
<song-id>/
  <key>/            e.g.  D/   E/   C/   A/
```

- Key folder names are copied through **exactly**, capitals included.
- A song has one or more keys. Adding a new key later = just add another `<key>/`
  folder; the uploader skips files already in the bucket, so re-uploading is cheap.
- Each key folder is a fully self-contained, time-aligned mix of the same song.

---

## 3. Inside each key folder: manifest + per-stem chunk folders

```
<song-id>/<key>/
  manifest.json
  <stem-slug>/            one folder per stem/track
    0001.mp3
    0002.mp3
    0003.mp3
    ...
  <stem-slug-2>/
    0001.mp3
    ...
```

### Stem chunk folders
- **One folder per stem** (Click, Drums, Bass, Electric Gtr, Keys, BGV, …).
- Folder name is a **slug** of the stem's display name:
  lowercase → replace every char not in `[a-z0-9]` with `-` → collapse repeated `-`
  → trim leading/trailing `-`.
  - `"Electric Gtr 2.wav"` → `electric-gtr-2`
  - `"Click"` → `click`
- Chunk files: `0001.mp3`, `0002.mp3`, … — **4-digit zero-padded, sequential
  starting at `0001`**, no gaps.
- **Every stem in a key must have the same number of chunks** (they play together,
  sample-aligned). `chunkCount` in the manifest is taken from the first stem and the
  player assumes all stems match.

### Chunking parameters (must match manifest values)
- Chunk length: **10 s** of song per chunk (`chunkSeconds`).
- Each chunk is encoded with **0.25 s of extra tail** (`overlap`) → each file is
  ~10.25 s long. This tail is used for a gapless crossfade between chunks; chunk *n*
  still represents song seconds `[(n-1)*10, n*10)`.
- Audio format: **MP3**, 44.1 kHz, stereo, 160 kbps (`ext:"mp3"`, `sampleRate:44100`).
- Number of chunks = `ceil(duration_seconds / 10)`, minimum 1.

### manifest.json
Written once per key folder:

```json
{
  "chunkSeconds": 10,
  "overlap": 0.25,
  "sampleRate": 44100,
  "ext": "mp3",
  "chunkCount": 39,
  "tracks":  ["Click", "Drums", "Bass", "Electric Gtr 2"],
  "folders": ["click", "drums", "bass", "electric-gtr-2"]
}
```

- `tracks` and `folders` are **parallel arrays** (same length, same order).
  `tracks[i]` = human display name (original stem filename without extension),
  `folders[i]` = its chunk sub-folder slug.
- `chunkCount` = number of `NNNN.mp3` files in each stem folder.
- Total song duration the player shows = `chunkCount * chunkSeconds`.

### Stem naming (affects mixer grouping — informational)
The player auto-groups/sorts channels by keywords in the **track display name**, so
name stems descriptively:
- `click` → pinned "Click" strip; `guide` → pinned "Guide" strip.
- `bgv` / `choir` / `alto` / `tenor` / `soprano` / `vox` / `voice` / `vocal` → vocals.
- `drum`; `perc` / `loop` / `fx`; `bass` (`synth bass` ranks after); `acoustic` or
  `acg`/`ag`; `electric` or `eg`; `piano`; `keys` / `synth` / `pad` / `organ`.
Anything unmatched still works — it just sorts to the end.

---

## 4. Song-root files (NOT per key): sections + chart

These live at the **song root**, shared across all keys:

```
<song-id>/
  sections.json     (optional but recommended)
  chart.pdf         (optional)
```

### sections.json
Song arrangement markers (Intro, Verse, Chorus, …), used for the section circles /
"now playing" label. Read from `songs/<id>/sections.json`.

```json
{
  "version": 1,
  "sections": [
    { "label": "Count Off", "ms": 0 },
    { "label": "Intro",     "ms": 8000 },
    { "label": "Verse 1",   "ms": 22000 },
    { "label": "Chorus 1",  "ms": 41000 }
  ]
}
```

Requirements (from the player's parser):
- `version` must equal **`1`**.
- `sections` is an array of `{ "label": <string>, "ms": <integer ≥ 0> }`.
  `ms` = offset from the start of the song in **milliseconds**.
- Sort ascending by `ms`; first entry should be `0`; values strictly increasing.
- Need **at least 2** valid entries or the player ignores the file.
- Every `ms` must be **< total duration** (`chunkCount * chunkSeconds * 1000`);
  entries past the end are dropped.

### chart.pdf
The chord chart / lead sheet, one per song, read from `songs/<id>/chart.pdf` and
rendered with pdf.js. Its mere presence sets `chart: true` on the table row.

---

## 5. Full example tree

```
What A Beautiful Name-let there be light-D-68/
├── sections.json
├── chart.pdf
├── D/
│   ├── manifest.json
│   ├── click/            0001.mp3 … 0039.mp3
│   ├── drums/            0001.mp3 … 0039.mp3
│   ├── bass/             0001.mp3 … 0039.mp3
│   ├── electric-gtr-2/   0001.mp3 … 0039.mp3
│   └── bgv/              0001.mp3 … 0039.mp3
└── E/
    ├── manifest.json
    ├── click/           0001.mp3 …
    ├── drums/           0001.mp3 …
    └── ...
```

Uploaded to the bucket as:
```
songs/What A Beautiful Name-let there be light-D-68/sections.json
songs/What A Beautiful Name-let there be light-D-68/chart.pdf
songs/What A Beautiful Name-let there be light-D-68/D/manifest.json
songs/What A Beautiful Name-let there be light-D-68/D/drums/0001.mp3
...
```
(The uploader walks the folder, skips dotfiles and `*.tmp`, and prefixes every
relative path with `songs/`.)

---

## 6. Metadata / catalog draft (staging, not uploaded to the bucket)

The `songs` **table** row is derived from the folder + a catalog draft. `batch-chunk.sh`
writes `songs.generated.json` next to the song folders (at the OUT_ROOT root, a
sibling of the `<song-id>/` folders — **not** inside any song folder, not in the bucket):

```json
{
  "songs": [
    {
      "id":         "What A Beautiful Name-let there be light-D-68",
      "title":      "What A Beautiful Name",
      "album":      "let there be light",
      "bpm":        68,
      "timeSig":    "4/4",
      "originalKey":"D",
      "keys":       ["D", "E"]
    }
  ]
}
```

`upload-song.py` reads this draft and upserts the table row:

| table column   | source                                             |
|----------------|----------------------------------------------------|
| `id`           | folder name (primary key)                          |
| `title`        | draft `title` (parsed from folder name)            |
| `album`        | draft `album`                                      |
| `bpm`          | draft `bpm`                                         |
| `time_sig`     | draft `timeSig` (default `"4/4"`)                  |
| `original_key` | draft `originalKey`                                |
| `keys`         | actual key sub-folders that contain a manifest     |
| `chart`        | `true` if `chart.pdf` exists at the song root       |

`keys` may be plain strings (the key folder names) or `{ "name": ..., "folder": ... }`
objects if the display label should differ from the folder name.

---

## 7. Checklist for the helper tool (per song)

1. Determine `song-id` = `<song name>-<album>-<original key>-<bpm>` (song name has no `-`).
2. For each key version, render/export the aligned stems from the Ableton session.
3. Slug each stem name; chunk each stem into `0001.mp3…` (10 s + 0.25 s tail, MP3
   44.1 kHz/stereo/160 kbps); all stems in a key get the same chunk count.
4. Write `<key>/manifest.json` with parallel `tracks`/`folders` arrays and `chunkCount`.
5. Write song-root `sections.json` (version 1, `{label, ms}`, sorted, ≥2, ms < total).
6. Copy the chord chart to song-root `chart.pdf` (optional).
7. Add/refresh the entry in `songs.generated.json` (title/album/bpm/timeSig/originalKey/keys).
8. Hand off to `upload-song.py <song-id>` (uploads new files + upserts the row).
