#!/bin/bash
# ============================================================
# batch-chunk.sh  (with skip + catalog draft)
#
# Source layout it expects:
#   <SRC_ROOT>/<song-id>/<key>/<stem files>
# Produces:
#   <OUT_ROOT>/<song-id>/<key>/manifest.json + <track>/0001.mp3 ...
#   <OUT_ROOT>/songs.generated.json   (a catalog draft for you to finish)
#
# Song-id and key folder names are copied through EXACTLY, so name your
# source song folders to match songs.json ids and key folders to match the
# keys exactly, capital letters included (D, E, C, A).
#
# Usage:
#   bash batch-chunk.sh                 (uses the paths below, skips done work)
#   bash batch-chunk.sh "/src" "/out"   (override paths)
#   bash batch-chunk.sh "" "" force     (re-chunk everything, even if already done)
# ============================================================

SRC_ROOT="${1:-/Users/sidneypinto/Documents/WEBAPP CHUNKS/original songs}"
OUT_ROOT="${2:-/Users/sidneypinto/Documents/WEBAPP CHUNKS/chuncked songs/songs}"
FORCE=0; [ "$3" = "force" ] && FORCE=1

# Optional: point this at your current songs.json to keep its titles/bpm/etc.
# Leave empty to generate a fresh draft with placeholders.
CURRENT_CATALOG="'/Users/sidneypinto/Documents/WEBAPP CHUNKS/chuncked songs/songs.json'"

CHUNK_SEC=10
OVERLAP=0.25
SAMPLE_RATE=44100
CHANNELS=2
BITRATE=160k

if ! command -v ffmpeg >/dev/null 2>&1; then echo "ffmpeg not found. Install with: brew install ffmpeg"; exit 1; fi
if [ ! -d "$SRC_ROOT" ]; then echo "Source folder not found: $SRC_ROOT"; exit 1; fi
mkdir -p "$OUT_ROOT"

chunk_folder(){
  local SRC="$1" OUT="$2"
  mkdir -p "$OUT"
  local tracks_json="" folders_json="" first_slug="" count=0
  local f base name slug tmp dur nchunks len start i chunkCount esc_name
  shopt -s nullglob
  for f in "$SRC"/*.mp3 "$SRC"/*.wav "$SRC"/*.m4a "$SRC"/*.aif "$SRC"/*.aiff "$SRC"/*.flac; do
    base=$(basename "$f"); name="${base%.*}"
    slug=$(echo "$name" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//')
    mkdir -p "$OUT/$slug"
    [ -z "$first_slug" ] && first_slug="$slug"
    tmp="$OUT/$slug/_tmp.wav"
    ffmpeg -y -i "$f" -ar $SAMPLE_RATE -ac $CHANNELS -c:a pcm_s16le "$tmp" >/dev/null 2>&1
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$tmp")
    nchunks=$(awk -v d="$dur" -v c="$CHUNK_SEC" 'BEGIN{n=int((d+c-1)/c); if(n<1)n=1; print n}')
    len=$(awk -v c="$CHUNK_SEC" -v o="$OVERLAP" 'BEGIN{print c+o}')
    for (( i=1; i<=nchunks; i++ )); do
      start=$(( (i-1)*CHUNK_SEC ))
      ffmpeg -y -ss $start -i "$tmp" -t $len -c:a libmp3lame -b:a $BITRATE "$OUT/$slug/$(printf '%04d' $i).mp3" >/dev/null 2>&1
    done
    rm -f "$tmp"
    esc_name=$(echo "$name" | sed 's/"/\\"/g')
    tracks_json="$tracks_json\"$esc_name\","
    folders_json="$folders_json\"$slug\","
    count=$((count+1))
  done
  shopt -u nullglob
  if [ "$count" -eq 0 ]; then echo "      (no audio files, skipped)"; return; fi
  chunkCount=$(ls "$OUT/$first_slug"/*.mp3 | wc -l | tr -d ' ')
  tracks_json="${tracks_json%,}"; folders_json="${folders_json%,}"
  cat > "$OUT/manifest.json" <<EOF
{
  "chunkSeconds": $CHUNK_SEC,
  "overlap": $OVERLAP,
  "sampleRate": $SAMPLE_RATE,
  "ext": "mp3",
  "chunkCount": $chunkCount,
  "tracks": [$tracks_json],
  "folders": [$folders_json]
}
EOF
  echo "      done: $count tracks, $chunkCount chunks each"
}

songs=0; keys=0; skipped=0
for songdir in "$SRC_ROOT"/*/; do
  [ -d "$songdir" ] || continue
  song=$(basename "$songdir")
  echo "SONG: $song"
  songs=$((songs+1))
  for keydir in "$songdir"*/; do
    [ -d "$keydir" ] || continue
    key=$(basename "$keydir")
    if [ "$FORCE" != "1" ] && [ -f "$OUT_ROOT/$song/$key/manifest.json" ]; then
      echo "    key: $key (already chunked, skipping)"
      skipped=$((skipped+1)); continue
    fi
    echo "    key: $key"
    chunk_folder "$keydir" "$OUT_ROOT/$song/$key"
    keys=$((keys+1))
  done
done

echo ""
echo "Chunking done. $songs songs scanned, $keys key versions chunked, $skipped skipped (already done)."

# ---- catalog draft ----
if command -v python3 >/dev/null 2>&1; then
  python3 - "$OUT_ROOT" "$CURRENT_CATALOG" "$OUT_ROOT/songs.generated.json" <<'PYEOF'
import json, os, sys
out_root, current_path, gen_path = sys.argv[1], sys.argv[2], sys.argv[3]

found = {}
for song in sorted(os.listdir(out_root)):
    sdir = os.path.join(out_root, song)
    if not os.path.isdir(sdir): continue
    keys = []
    for key in sorted(os.listdir(sdir)):
        kdir = os.path.join(sdir, key)
        if os.path.isdir(kdir) and os.path.exists(os.path.join(kdir, "manifest.json")):
            keys.append(key)
    if keys: found[song] = keys

existing = {}
if current_path and os.path.exists(current_path):
    try:
        data = json.load(open(current_path))
        arr = data["songs"] if isinstance(data, dict) else data
        for s in arr: existing[s.get("id")] = s
    except Exception as e:
        print("  (could not read current catalog:", e, ")")

out, new_ids = [], []
for sid, keys in found.items():
    prev = existing.get(sid)
    if prev:
        entry = dict(prev); entry["id"] = sid; entry["keys"] = keys
        if entry.get("originalKey") not in keys: entry["originalKey"] = keys[0]
    else:
        new_ids.append(sid)
        entry = {"id": sid, "title": sid.replace("-", " ").title(),
                 "bpm": 0, "timeSig": "4/4", "originalKey": keys[0], "keys": keys}
    out.append(entry)

json.dump({"songs": out}, open(gen_path, "w"), indent=2)
print("Catalog draft written to:", gen_path)
if new_ids:
    print("New songs that still need a title, bpm, and original key:")
    for n in new_ids: print("   -", n)
else:
    print("No new songs to fill in.")
PYEOF
else
  echo "(python3 not found, skipped the catalog draft. Install with: brew install python)"
fi

echo ""
echo "Output: $OUT_ROOT"
echo "Next: finish songs.generated.json (title, bpm, original key), rename it to songs.json,"
echo "then upload the new song folders and songs.json to your bucket."
