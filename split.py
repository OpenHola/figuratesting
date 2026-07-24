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

	#dunno if you can have opus or are we stuck with vorbis
	#indeed we're stuck with vorbis
    codec = "libopus" if (args.opus or args.codec == "opus") else "libvorbis"

    bitrate, samplerate = args.bitrate, args.samplerate
    if args.opus and args.bitrate == "96k":
        bitrate = "8k"
    elif args.ping:
        bitrate = bitrate if args.bitrate != "96k" else "8k"
        samplerate = samplerate or 8000
    if codec == "libopus":
        samplerate = None

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", args.input,
           "-ac", "1"]
    if samplerate:
        cmd += ["-ar", str(samplerate)]
    cmd += [
        "-c:a", codec,
        "-b:a", bitrate,
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
        "codec": codec,
        "bitrate": bitrate,
        "samplerate": samplerate or "source",
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
    ping_report(900, 200, 9)


PING_HARD_LIMIT = 1024
PACK_EXPANSION = 8.0 / 7.0


def _fmt_time(sec):
    if sec < 90:
        return f"{sec:.0f}s"
    return f"{sec/60:.1f} min"


def ping_report(budget, chunk, overhead):
    eff_wire = budget * (chunk / (chunk + overhead))
    eff_raw = eff_wire / PACK_EXPANSION
    pings_per_sec = budget / (chunk + overhead)
    max_kbps = eff_raw * 8 / 1000.0

    print(f"PING DELIVERY PLAN  (budget {budget} B/s of {PING_HARD_LIMIT}, "
          f"{chunk} packed chars/ping, ~{overhead} B overhead, base127 {PACK_EXPANSION:.3f}x)")
    print(f"  ~{pings_per_sec:.1f} pings/sec (cap 32), "
          f"delivering ~{eff_raw:.0f} B/s of audio")
    print(f"  => real-time ping streaming needs audio <= ~{max_kbps:.1f} kbps mono")

    if not os.path.isdir(TRACKS):
        print("(no tracks yet)")
        return

    for tid in sorted(os.listdir(TRACKS)):
        tdir = os.path.join(TRACKS, tid)
        mpath = os.path.join(tdir, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        with open(mpath) as f:
            m = json.load(f)
        segs = [s for s in os.listdir(tdir) if s.endswith(".ogg")]
        raw = sum(os.path.getsize(os.path.join(tdir, s)) for s in segs)
        wire = raw * PACK_EXPANSION
        play_sec = m["segCount"] * m["segSeconds"]
        send_sec = wire / eff_wire
        factor = send_sec / play_sec if play_sec else float("inf")
        avg_kbps = (raw * 8 / play_sec) / 1000.0 if play_sec else 0

        if factor <= 1.0:
            verdict = "OK: streams live over pings"
        elif factor <= 3.0:
            verdict = f"preload only (~{_fmt_time(send_sec)} before play)"
        else:
            verdict = f"TOO BIG for pings ({factor:.0f}x real-time)"

        print(f"\n  {tid}  ({m.get('title', tid)})")
        print(f"    {m['segCount']} segs x {m['segSeconds']}s = "
              f"{_fmt_time(play_sec)} audio @ ~{avg_kbps:.0f} kbps")
        print(f"    raw {raw/1024:.0f} KiB -> wire {wire/1024:.0f} KiB")
        print(f"    ping send time: {_fmt_time(send_sec)}  "
              f"({factor:.1f}x real-time)  ->  {verdict}")
    print()


def main():
    p = argparse.ArgumentParser(description="quite cool music splitter")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="encode + segment a track")
    a.add_argument("input")
    a.add_argument("--id", required=True, help="url-safe id, e.g. 'cat', 'cool_music'")
    a.add_argument("--title", default=None)
    a.add_argument("--seconds", type=int, default=3, help="segment length")
    a.add_argument("--bitrate", default="96k", help="e.g. 96k, 128k (ping mode: 12k)")
    a.add_argument("--samplerate", type=int, default=None,
                   help="downsample Hz (e.g. 12000)")
    a.add_argument("--ping", action="store_true",
                   help="lowest-fi vorbis preset for ping delivery (8k @ 8000 Hz)")
    a.add_argument("--codec", choices=["vorbis", "opus"], default="vorbis",
                   help="unused for now, left here because in the future Figura may add opus support")
    a.add_argument("--opus", action="store_true",
                   help="shorthand: opus @ 8k — the only path to full songs over pings")
    a.set_defaults(func=add)

    i = sub.add_parser("index", help="rebuild index.json + boombox_tracks.lua")
    i.set_defaults(func=lambda _: build_index())

    c = sub.add_parser("plan", help="ping time-to-send calculator for all tracks")
    c.add_argument("--budget", type=int, default=900,
                   help="bytes/sec to spend on audio pings (<1024, keep margin)")
    c.add_argument("--chunk", type=int, default=200,
                   help="base64 chars per ping (payload size)")
    c.add_argument("--overhead", type=int, default=9,
                   help="estimated per-ping overhead bytes (id+len+type+indices)")
    c.set_defaults(func=lambda a: ping_report(a.budget, a.chunk, a.overhead))

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
