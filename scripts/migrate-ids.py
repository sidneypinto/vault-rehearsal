#!/usr/bin/env python3
# ============================================================
# migrate-ids.py — rebuild song ids to the naming convention
#   <song name>-<album>-<original key>-<bpm>
#
# For every row in the `songs` table whose id doesn't already match,
# this moves all its storage objects from songs/<old-id>/... to
# songs/<new-id>/..., inserts the row under the new id, deletes the
# old row, and renames the matching local chunk folder in OUT_ROOT
# (so a future `upload-song.py all` doesn't recreate the old id).
#
# Rows missing album, original key, or bpm are skipped and reported —
# fill them in (Supabase dashboard → Table Editor → songs) and rerun.
# Safe to rerun: already-migrated songs are skipped.
#
# Usage:
#   python3 migrate-ids.py --dry-run    show what would happen
#   python3 migrate-ids.py              migrate for real
# ============================================================
import json, os, sys, urllib.request, urllib.error, urllib.parse, concurrent.futures, threading, time

SUPABASE_URL = "https://faaxtwjlrxnlotojfcqw.supabase.co"
BUCKET = "songs"
OUT_ROOT = "/Users/sidneypinto/Documents/WEBAPP CHUNKS/chuncked songs/songs"

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
DRY = "--dry-run" in sys.argv

def api(path, method="GET", body=None, extra_headers=None):
    headers = {"Authorization": f"Bearer {KEY}", "apikey": KEY,
               "Content-Type": "application/json"}
    if extra_headers: headers.update(extra_headers)
    req = urllib.request.Request(SUPABASE_URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=60) as res:
        raw = res.read()
    return json.loads(raw) if raw else None

def list_objects(prefix):
    """All object keys in the bucket under prefix (recursive)."""
    keys, folders = [], [prefix]
    while folders:
        folder = folders.pop()
        offset = 0
        while True:
            page = api(f"/storage/v1/object/list/{BUCKET}", "POST",
                       {"prefix": folder, "limit": 100, "offset": offset,
                        "sortBy": {"column": "name", "order": "asc"}})
            for item in page:
                # folders come back with id=None
                if item.get("id") is None:
                    folders.append(f"{folder}/{item['name']}")
                else:
                    keys.append(f"{folder}/{item['name']}")
            if len(page) < 100: break
            offset += 100
    return keys

def new_id_for(row):
    title = (row.get("title") or "").strip()
    album = (row.get("album") or "").strip()
    key = (row.get("original_key") or "").strip()
    bpm = row.get("bpm")
    if not title or not album or not key or not bpm:
        return None
    return f"{title}-{album}-{key}-{int(bpm)}"

rows = api("/rest/v1/songs?select=*&order=title.asc")
print(f"{len(rows)} songs in the table" + (" (dry run)" if DRY else ""))

migrated, skipped_ok, needs_data = [], [], []
for row in rows:
    old_id, new_id = row["id"], new_id_for(row)
    if new_id is None:
        needs_data.append(row)
        continue
    if new_id == old_id:
        skipped_ok.append(old_id)
        continue

    objects = list_objects(f"songs/{old_id}")
    print(f"\n{old_id}\n  -> {new_id}\n  storage objects to move: {len(objects)}")
    if DRY:
        migrated.append((old_id, new_id))
        continue

    done = {"n": 0}
    lock = threading.Lock()
    def move(src, retries=4):
        dst = f"songs/{new_id}/" + src[len(f"songs/{old_id}/"):]
        for attempt in range(retries):
            try:
                api("/storage/v1/object/move", "POST",
                    {"bucketId": BUCKET, "sourceKey": src, "destinationKey": dst})
                break
            except Exception:
                if attempt == retries - 1: raise
                time.sleep(2 ** attempt)
        with lock:
            done["n"] += 1
            if done["n"] % 500 == 0: print(f"  {done['n']}/{len(objects)} moved", flush=True)
    with concurrent.futures.ThreadPoolExecutor(12) as ex:
        list(ex.map(move, objects))
    print(f"  moved {len(objects)} objects")

    new_row = dict(row); new_row["id"] = new_id
    api("/rest/v1/songs?on_conflict=id", "POST", [new_row],
        {"Prefer": "resolution=merge-duplicates"})
    api(f"/rest/v1/songs?id=eq.{urllib.parse.quote(old_id)}", "DELETE")
    print("  table row rewritten")

    old_local = os.path.join(OUT_ROOT, old_id)
    if os.path.isdir(old_local):
        new_local = os.path.join(OUT_ROOT, new_id)
        if os.path.exists(new_local):
            print(f"  WARNING: local folder {new_local} already exists, left {old_local} alone")
        else:
            os.rename(old_local, new_local)
            print(f"  local chunk folder renamed")
    migrated.append((old_id, new_id))

print(f"\n==== summary {'(dry run — nothing changed)' if DRY else ''} ====")
print(f"migrated: {len(migrated)}")
for old, new in migrated: print(f"   {old}  ->  {new}")
print(f"already matching: {len(skipped_ok)}")
if needs_data:
    print(f"SKIPPED — missing album/original key/bpm (fill in the dashboard, rerun):")
    for r in needs_data: print(f"   - {r['id']} (title={r.get('title')!r}, album={r.get('album')!r}, key={r.get('original_key')!r}, bpm={r.get('bpm')!r})")
