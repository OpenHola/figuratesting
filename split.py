#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TRACKS = os.path.join(ROOT, "tracks")
ID_RE = re.compile(r"^[a-z0-9_-]+$")


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def need_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        die("ffmpeg/ffprobe not found on PATH")


def add(args):
    need_ffmpeg()
    if not ID_RE.match(args.id):
        die("id must match [a-z0-9_-]+ (it becomes a URL path)")
    if not os.path.isfile(args.input):
        die(f"no such file: {args.input}")

    out_dir = os.path.join(TRACKS, args.id)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

	#mono or everyone gets the music blasted
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", args.input,
        "-ac", "1",
        "-c:a", "libvorbis",
		"-q:a", "1",
        "-b:a", args.bitrate,
        "-f", "segment",
        "-segment_time", str(args.seconds),
        "-reset_timestamps", "1",
        os.path.join(out_dir, "seg_%04d.ogg"),
    ]
    print("encoding:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    segs = sorted(f for f in os.listdir(out_dir) if f.endswith(".ogg"))
    if not segs:
        die("ffmpeg produced no segments")

    manifest = {
        "id": args.id,
        "title": args.title or args.id,
        "segCount": len(segs),
        "segSeconds": args.seconds,
        "bitrate": args.bitrate,
        "channels": 1,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    total = sum(
        os.path.getsize(os.path.join(out_dir, s)) for s in segs
    ) / 1024.0
    print(f"ok: {args.id} -> {len(segs)} segments (~{total:.0f} KiB total)")
    build_index()


def build_index():
    tracks = []
    if os.path.isdir(TRACKS):
        for tid in sorted(os.listdir(TRACKS)):
            mpath = os.path.join(TRACKS, tid, "manifest.json")
            if os.path.isfile(mpath):
                with open(mpath) as f:
                    tracks.append(json.load(f))

    with open(os.path.join(ROOT, "index.json"), "w") as f:
        json.dump(tracks, f, indent=2)

    lines = ["-- paste me in STREAM.tracks in your script.lua",
             "tracks = {"]
    for t in tracks:
        lines.append(
            '    {{ id = "{id}", title = "{title}", segCount = {segCount}, segSeconds = {segSeconds} }},'
            .format(**t)
        )
    lines.append("}")
    with open(os.path.join(ROOT, "boombox_tracks.lua"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"index: {len(tracks)} track(s) -> index.json + boombox_tracks.lua")


def main():
    p = argparse.ArgumentParser(description="quite cool music splitter")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="encode + segment a track")
    a.add_argument("input")
    a.add_argument("--id", required=True, help="url-safe id, e.g. 'cat', 'cool_music'")
    a.add_argument("--title", default=None)
    a.add_argument("--seconds", type=int, default=3, help="segment length")
    a.add_argument("--bitrate", default="96k", help="e.g. 96k, 128k")
    a.set_defaults(func=add)

    i = sub.add_parser("index", help="rebuild index.json + boombox_tracks.lua")
    i.set_defaults(func=lambda _: build_index())

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
