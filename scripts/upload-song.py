#!/usr/bin/env python3
# ============================================================
# upload-song.py — publish a chunked song to Supabase.
#
# Uploads <OUT_ROOT>/<song-id>/** to the public `songs` storage bucket
# (skipping files that are already there, so adding a new key to an
# existing song just uploads the new key) and upserts the song's row
# (title, album, bpm, time sig, original key, keys, chart) into the
# `songs` table from the catalog draft written by batch-chunk.sh.
#
# Setup (once): put the service key in scripts/.env (never commit it):
#   SUPABASE_SERVICE_KEY=eyJ...
#
# Usage:
#   python3 upload-song.py <song-id>       publish one song
#   python3 upload-song.py all             publish every song in OUT_ROOT
# ============================================================
import json, os, sys, time, urllib.request, urllib.error, urllib.parse, concurrent.futures, threading

SUPABASE_URL = "https://faaxtwjlrxnlotojfcqw.supabase.co"
BUCKET = "songs"
OUT_ROOT = "/Users/sidneypinto/Documents/WEBAPP CHUNKS/chuncked songs/songs"
CATALOG_CANDIDATES = [
    os.path.join(OUT_ROOT, "songs.generated.json"),
    os.path.join(os.path.dirname(OUT_ROOT), "songs.json"),
]

def load_service_key():
    if os.environ.get("SUPABASE_SERVICE_KEY"):
        return os.environ["SUPABASE_SERVICE_KEY"]
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.strip().startswith("SUPABASE_SERVICE_KEY="):
                return line.strip().split("=", 1)[1]
    sys.exit("SUPABASE_SERVICE_KEY not set. Put it in scripts/.env or the environment.")

KEY = load_service_key()

def ctype(path):
    if path.endswith(".mp3"): return "audio/mpeg"
    if path.endswith(".json"): return "application/json"
    if path.endswith(".pdf"): return "application/pdf"
    return "application/octet-stream"

def upload_file(local_path, object_path, retries=4):
    """Returns 'uploaded' or 'skipped' (already in the bucket)."""
    data = open(local_path, "rb").read()
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{urllib.parse.quote(object_path)}",
            data=data, method="POST",
            headers={"Authorization": f"Bearer {KEY}", "apikey": KEY,
                     "Content-Type": ctype(local_path), "x-upsert": "false"})
        try:
            with urllib.request.urlopen(req, timeout=120):
                return "uploaded"
        except urllib.error.HTTPError as e:
            if e.code == 409:
                return "skipped"
            if attempt == retries - 1:
                raise RuntimeError(f"{object_path}: HTTP {e.code} {e.read()[:200]}")
        except Exception:
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)

def upsert_row(entry):
    row = {
        "id": entry["id"], "title": entry.get("title") or entry["id"],
        "album": entry.get("album") or None,
        "bpm": entry.get("bpm") or None,
        "time_sig": entry.get("timeSig") or "4/4",
        "original_key": entry.get("originalKey"),
        "keys": entry.get("keys") or [],
        "chart": bool(entry.get("chart")),
    }
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/songs?on_conflict=id",
        data=json.dumps([row]).encode(), method="POST",
        headers={"Authorization": f"Bearer {KEY}", "apikey": KEY,
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates"})
    urllib.request.urlopen(req).read()

def publish(sid, catalog):
    sdir = os.path.join(OUT_ROOT, sid)
    if not os.path.isdir(sdir):
        sys.exit(f"Song folder not found: {sdir}")
    files = []
    for root, _, names in os.walk(sdir):
        for name in names:
            if name.startswith(".") or name.endswith(".tmp"):
                continue
            local = os.path.join(root, name)
            files.append((local, "songs/" + os.path.relpath(local, OUT_ROOT).replace(os.sep, "/")))
    print(f"{sid}: {len(files)} files")

    counts = {"uploaded": 0, "skipped": 0}
    lock = threading.Lock()
    def one(job):
        result = upload_file(*job)
        with lock:
            counts[result] += 1
            done = counts["uploaded"] + counts["skipped"]
            if done % 250 == 0:
                print(f"  {done}/{len(files)} {counts}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        list(ex.map(one, files))
    print(f"  storage done: {counts}")

    entry = catalog.get(sid)
    if entry:
        # keep the catalog draft's keys honest about what's actually chunked
        entry["keys"] = sorted(d for d in os.listdir(sdir)
                               if os.path.isdir(os.path.join(sdir, d))
                               and os.path.exists(os.path.join(sdir, d, "manifest.json")))
        entry["chart"] = entry.get("chart") or os.path.exists(os.path.join(sdir, "chart.pdf"))
        upsert_row(entry)
        print(f"  songs table upserted: {entry.get('title')} — {entry.get('album') or '(no album)'}")
    else:
        print(f"  WARNING: {sid} not found in the catalog draft — storage uploaded, but no table row written.")

catalog = {}
for path in CATALOG_CANDIDATES:
    if os.path.exists(path):
        data = json.load(open(path))
        arr = data["songs"] if isinstance(data, dict) else data
        catalog = {s["id"]: s for s in arr}
        print(f"catalog: {path} ({len(catalog)} songs)")
        break

if len(sys.argv) < 2:
    sys.exit(__doc__ or "usage: python3 upload-song.py <song-id>|all")
target = sys.argv[1]
ids = sorted(d for d in os.listdir(OUT_ROOT) if os.path.isdir(os.path.join(OUT_ROOT, d))) if target == "all" else [target]
for sid in ids:
    publish(sid, catalog)
print("Done. Edit title/album/bpm any time in the Supabase dashboard (Table Editor → songs).")
