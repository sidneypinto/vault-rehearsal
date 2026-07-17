#!/usr/bin/env python3
# ============================================================
# seed-sections.py — seed fictitious song sections for testing.
#
# For each song in the Supabase `songs` table: reads one key's
# manifest.json to get the song duration, generates 20-25 plausible
# worship-song sections (Count Off always first at 0 ms), and uploads
# songs/<id>/sections.json to the public `songs` bucket with upsert,
# so the script is safe to re-run. RNG is seeded per song id, so
# re-runs produce identical files.
#
# Usage:
#   python3 seed-sections.py             seed every song
#   python3 seed-sections.py <song-id>   seed one song
# ============================================================
import json, os, sys, time, random, urllib.request, urllib.error, urllib.parse

SUPABASE_URL = "https://faaxtwjlrxnlotojfcqw.supabase.co"
BUCKET = "songs"

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

def fetch_songs():
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/songs?select=id,title,keys",
        headers={"Authorization": f"Bearer {KEY}", "apikey": KEY})
    return json.load(urllib.request.urlopen(req, timeout=60))

def key_folder(k):
    # keys column entries are strings or {name, folder} objects
    return k if isinstance(k, str) else (k.get("folder") or k.get("name"))

def song_duration(sid, keys):
    for k in keys or []:
        folder = key_folder(k)
        if not folder:
            continue
        url = (f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/songs/"
               f"{urllib.parse.quote(sid)}/{urllib.parse.quote(folder)}/manifest.json")
        try:
            m = json.load(urllib.request.urlopen(url, timeout=30))
            # mirrors the app: total = chunkCount * chunkSeconds
            return m["chunkCount"] * m["chunkSeconds"]
        except Exception:
            continue
    return None

# label -> plausible duration range in seconds
DUR = {
    "Count Off": (3, 7), "Intro": (10, 22), "Verse": (18, 32), "Pre-Chorus": (8, 15),
    "Chorus": (18, 32), "Turnaround": (6, 14), "Instrumental": (14, 28),
    "Bridge": (14, 28), "Refrain": (12, 22), "Vamp": (20, 45), "Tag": (6, 14),
    "Outro": (10, 25),
}
BASE_TEMPLATE = [
    "Count Off", "Intro", "Verse 1a", "Verse 1b", "Pre-Chorus", "Chorus 1a",
    "Chorus 1b", "Turnaround", "Verse 2a", "Verse 2b", "Pre-Chorus 2",
    "Chorus 2a", "Chorus 2b", "Instrumental", "Bridge 1", "Bridge 2",
    "Bridge 3", "Chorus 3a", "Chorus 3b", "Vamp", "Tag", "Outro",
]
OPTIONAL = ["Turnaround", "Bridge 3", "Tag"]
EXTRAS = [("Turnaround 2", "Chorus 2b"), ("Bridge 4", "Bridge 3"),
          ("Vamp 2", "Vamp"), ("Instrumental 2", "Instrumental"), ("Refrain", "Chorus 1b")]

def dur_range(label):
    for k, rng in DUR.items():
        if label.startswith(k.split()[0]):
            return rng
    return (10, 25)

def generate_sections(sid, duration_s):
    rng = random.Random(sid)
    labels = list(BASE_TEMPLATE)
    for opt in OPTIONAL:
        if rng.random() < 0.4:
            labels.remove(opt)
    for extra, after in EXTRAS:
        if len(labels) >= 25:
            break
        if rng.random() < 0.5 and after in labels:
            labels.insert(labels.index(after) + 1, extra)
    # short songs get a trimmed template (Count Off always kept)
    max_n = max(4, int(duration_s // 8))
    if len(labels) > max_n:
        labels = ["Count Off"] + labels[1:max_n]
    durs = [rng.uniform(*dur_range(l)) for l in labels]
    scale = duration_s / sum(durs)
    starts, t = [], 0.0
    for d in durs:
        starts.append(int(round(t * 1000)))
        t += d * scale
    sections = [{"label": l, "ms": ms} for l, ms in zip(labels, starts)]
    assert sections[0]["ms"] == 0
    assert all(a["ms"] < b["ms"] for a, b in zip(sections, sections[1:]))
    assert sections[-1]["ms"] < duration_s * 1000
    return sections

def upload_sections(sid, sections, retries=4):
    body = json.dumps({"version": 1, "sections": sections}, indent=1).encode()
    path = urllib.parse.quote(f"songs/{sid}/sections.json")
    for attempt in range(retries):
        req = urllib.request.Request(
            f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
            data=body, method="POST",
            headers={"Authorization": f"Bearer {KEY}", "apikey": KEY,
                     "Content-Type": "application/json", "x-upsert": "true"})
        try:
            with urllib.request.urlopen(req, timeout=60):
                return
        except urllib.error.HTTPError as e:
            if attempt == retries - 1:
                raise RuntimeError(f"{sid}: HTTP {e.code} {e.read()[:200]}")
        except Exception:
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    songs = fetch_songs()
    if target:
        songs = [s for s in songs if s["id"] == target]
        if not songs:
            sys.exit(f"Song not found in table: {target}")
    ok = skipped = 0
    for s in songs:
        sid = s["id"]
        duration_s = song_duration(sid, s.get("keys"))
        if not duration_s:
            print(f"  WARNING {sid}: no readable manifest for any key — skipped")
            skipped += 1
            continue
        sections = generate_sections(sid, duration_s)
        upload_sections(sid, sections)
        m, sec = divmod(int(duration_s), 60)
        print(f"{sid}: {len(sections)} sections over {m}:{sec:02d}")
        ok += 1
    print(f"Done. {ok} seeded, {skipped} skipped.")

if __name__ == "__main__":
    main()
