"""Nightly mnemosyne backup (runs inside the mnemosyne image, see backup.sh).

Online copy of every database through SQLite's backup API. That is safe
while the server and the sleep loop are writing, and each copy is a single
standalone file (no -wal/-shm). Keeps the real layout
(banks/<name>/mnemosyne.db) so a restore is a plain copy. The Phase 0
snapshot flattened bank names, and a flat restore silently comes up with
empty banks.
"""
import datetime
import hashlib
import os
import pathlib
import shutil
import sqlite3
import sys

DATA = pathlib.Path("/data")
ROOT = pathlib.Path("/backups")
KEEP_DAYS = int(os.environ.get("KEEP_DAYS", "14"))

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
dest = ROOT / stamp
tmp = ROOT / f".{stamp}.partial"
shutil.rmtree(tmp, ignore_errors=True)

if not (DATA / "mnemosyne.db").is_file():
    # sqlite3.connect() would silently create an empty database here.
    sys.exit("no /data/mnemosyne.db: refusing to back up (and to create one)")

dbs = [DATA / "mnemosyne.db"] + sorted(DATA.glob("banks/*/mnemosyne.db"))
sums, report = [], []
for src in dbs:
    rel = src.relative_to(DATA)
    out = tmp / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(src)
    d = sqlite3.connect(out)
    s.backup(d)
    d.execute("PRAGMA journal_mode=DELETE")
    ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    wm = d.execute("SELECT count(*) FROM working_memory").fetchone()[0]
    d.close()
    s.close()
    if ok != "ok":
        sys.exit(f"integrity_check failed on {rel}: {ok}")
    sums.append(f"{hashlib.sha256(out.read_bytes()).hexdigest()}  {rel}")
    report.append(f"{rel}: ok, working_memory={wm}")

if (DATA / "config.yaml").exists():
    shutil.copy2(DATA / "config.yaml", tmp / "config.yaml")
(tmp / "SHA256SUMS").write_text("\n".join(sums) + "\n")
tmp.rename(dest)
print(f"backup {dest.name}:", "; ".join(report), flush=True)

# Prune only directories this script named; never touch anything else.
cutoff = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
for old in ROOT.iterdir():
    if not old.is_dir() or old.name.startswith("."):
        continue
    try:
        when = datetime.datetime.strptime(old.name, "%Y%m%d-%H%M%S")
    except ValueError:
        continue
    if when < cutoff:
        shutil.rmtree(old)
        print("pruned", old.name, flush=True)
