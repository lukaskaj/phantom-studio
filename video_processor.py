import subprocess
import random
import os
import sys
import json

RATIOS = {
    "ig":      (1080, 1440),
    "tiktok":  (1080, 1920),
    "original": None
}

def log(msg):
    print(json.dumps({"log": msg}), flush=True)

def random_name(folder):
    while True:
        name = f"VID_{random.randint(1000,9999)}.mp4"
        if not os.path.exists(os.path.join(folder, name)):
            return name

def strip_metadata(path):
    try:
        subprocess.run(
            ["exiftool", "-all=", "-overwrite_original", "-q", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except:
        pass

def get_duration(video_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except:
        return 0

def build_vf(ratio):
    filters = []

    # 1. Asymmetric crop — trunc to even for yuv420p
    left   = random.uniform(0.01, 0.06)
    right  = random.uniform(0.01, 0.06)
    top    = random.uniform(0.01, 0.06)
    bottom = random.uniform(0.01, 0.06)
    filters.append(
        f"crop=trunc(iw*(1-{left:.4f}-{right:.4f})/2)*2:trunc(ih*(1-{top:.4f}-{bottom:.4f})/2)*2:trunc(iw*{left:.4f}/2)*2:trunc(ih*{top:.4f}/2)*2"
    )

    # 2. Aspect ratio — Lanczos
    if ratio and ratio != "original" and ratio in RATIOS:
        w, h = RATIOS[ratio]
        filters.append(f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos")
        filters.append(f"crop={w}:{h}")

    # 3. Zoom 1.01-1.05
    zoom = random.uniform(1.01, 1.05)
    filters.append(f"scale=trunc(iw*{zoom:.4f}/2)*2:trunc(ih*{zoom:.4f}/2)*2:flags=lanczos")

    # 4. Rotate ±0.5° + crop black corners
    rotate = random.uniform(-0.5, 0.5)
    filters.append(f"rotate={rotate:.4f}*PI/180:fillcolor=black")
    filters.append("crop=trunc(iw*0.99/2)*2:trunc(ih*0.99/2)*2")

    # 5. Color grade via eq gamma channels
    style = random.choice([
        "warm", "warm2", "warm3",
        "cool", "cool2", "cool3",
        "vivid", "vivid2",
        "fade", "fade2",
        "punchy", "punchy2",
        "bright", "dark",
        "green", "purple",
        "golden", "cold_blue",
        "neutral", "cinematic"
    ])

    sat   = random.uniform(1.08, 1.18)
    cont  = random.uniform(1.05, 1.12)
    bri   = random.uniform(-0.04, 0.04)
    gam   = random.uniform(0.88, 1.12)
    gam_r = 1.0
    gam_g = 1.0
    gam_b = 1.0

    if style == "warm":
        gam_r = random.uniform(0.75, 0.85)
        gam_b = random.uniform(1.15, 1.28)
        sat   = random.uniform(1.12, 1.22)
    elif style == "warm2":
        gam_r = random.uniform(0.70, 0.80)
        gam_g = random.uniform(0.88, 0.94)
        gam_b = random.uniform(1.18, 1.30)
        sat   = random.uniform(1.14, 1.24)
    elif style == "warm3":
        gam_r = random.uniform(0.72, 0.82)
        gam_g = random.uniform(0.90, 0.96)
        gam_b = random.uniform(1.20, 1.32)
        sat   = random.uniform(1.10, 1.20)
        bri   = random.uniform(0.02, 0.06)
    elif style == "cool":
        gam_r = random.uniform(1.15, 1.28)
        gam_b = random.uniform(0.75, 0.85)
        sat   = random.uniform(1.08, 1.18)
    elif style == "cool2":
        gam_r = random.uniform(1.18, 1.30)
        gam_g = random.uniform(1.04, 1.08)
        gam_b = random.uniform(0.72, 0.82)
        sat   = random.uniform(1.10, 1.20)
    elif style == "cool3":
        gam_r = random.uniform(1.20, 1.32)
        gam_b = random.uniform(0.70, 0.80)
        sat   = random.uniform(1.06, 1.16)
        bri   = random.uniform(-0.02, 0.02)
    elif style == "vivid":
        sat   = random.uniform(1.28, 1.42)
        cont  = random.uniform(1.10, 1.18)
        gam   = random.uniform(0.90, 0.96)
    elif style == "vivid2":
        sat   = random.uniform(1.32, 1.48)
        cont  = random.uniform(1.12, 1.20)
        gam_r = random.uniform(0.92, 0.97)
        gam_b = random.uniform(0.92, 0.97)
    elif style == "fade":
        sat   = random.uniform(0.72, 0.84)
        cont  = random.uniform(0.82, 0.92)
        bri   = random.uniform(0.04, 0.09)
        gam   = random.uniform(1.08, 1.18)
    elif style == "fade2":
        sat   = random.uniform(0.68, 0.80)
        cont  = random.uniform(0.78, 0.88)
        bri   = random.uniform(0.06, 0.11)
        gam   = random.uniform(1.10, 1.20)
    elif style == "punchy":
        sat   = random.uniform(1.20, 1.32)
        cont  = random.uniform(1.18, 1.28)
        gam   = random.uniform(0.85, 0.92)
    elif style == "punchy2":
        sat   = random.uniform(1.24, 1.36)
        cont  = random.uniform(1.20, 1.30)
        gam   = random.uniform(0.82, 0.90)
        bri   = random.uniform(-0.02, 0.02)
    elif style == "bright":
        bri   = random.uniform(0.06, 0.12)
        sat   = random.uniform(1.06, 1.14)
        gam   = random.uniform(0.84, 0.92)
    elif style == "dark":
        bri   = random.uniform(-0.10, -0.05)
        cont  = random.uniform(1.12, 1.20)
        sat   = random.uniform(0.90, 1.02)
        gam   = random.uniform(1.10, 1.20)
    elif style == "green":
        gam_g = random.uniform(0.78, 0.88)
        gam_r = random.uniform(1.08, 1.16)
        gam_b = random.uniform(1.08, 1.16)
        sat   = random.uniform(1.10, 1.20)
    elif style == "purple":
        gam_r = random.uniform(0.82, 0.90)
        gam_g = random.uniform(1.10, 1.18)
        gam_b = random.uniform(0.82, 0.90)
        sat   = random.uniform(1.10, 1.20)
    elif style == "golden":
        gam_r = random.uniform(0.76, 0.84)
        gam_g = random.uniform(0.84, 0.92)
        gam_b = random.uniform(1.22, 1.34)
        sat   = random.uniform(1.14, 1.24)
        bri   = random.uniform(0.02, 0.06)
    elif style == "cold_blue":
        gam_r = random.uniform(1.22, 1.34)
        gam_g = random.uniform(1.06, 1.12)
        gam_b = random.uniform(0.74, 0.84)
        sat   = random.uniform(1.08, 1.18)
        bri   = random.uniform(-0.03, 0.01)
    elif style == "cinematic":
        sat   = random.uniform(0.88, 0.98)
        cont  = random.uniform(1.14, 1.24)
        gam   = random.uniform(1.04, 1.12)
        bri   = random.uniform(-0.04, -0.01)
    elif style == "neutral":
        sat   = random.uniform(1.02, 1.08)
        cont  = random.uniform(1.01, 1.05)
        bri   = random.uniform(-0.01, 0.01)

    filters.append(
        f"eq=saturation={sat:.4f}:contrast={cont:.4f}:brightness={bri:.4f}:gamma={gam:.4f}:gamma_r={gam_r:.4f}:gamma_g={gam_g:.4f}:gamma_b={gam_b:.4f}"
    )

    # 6. Hue rotation ±5°
    hue = random.uniform(-5, 5)
    filters.append(f"hue=h={hue:.2f}")

    # 7. Sharpen or slight blur — random
    if random.random() < 0.5:
        filters.append("unsharp=3:3:0.4")
    else:
        blur = random.uniform(0.3, 0.8)
        filters.append(f"unsharp=3:3:-{blur:.2f}")

    # 8. Grain — natural film grain
    grain = random.uniform(4, 10)
    filters.append(f"noise=alls={grain:.2f}:allf=t+u")

    # 9. Invisible pixel signature — changes perceptual hash, no external libs needed
    px  = random.randint(0, 15)
    py  = random.randint(0, 15)
    val = random.randint(2, 10)
    filters.append(
        f"geq=r='if(between(X,{px},{px+2})*between(Y,{py},{py+2}),clip(r(X,Y)+{val},0,255),r(X,Y))':g='g(X,Y)':b='b(X,Y)'"
    )

    return ",".join(filters)

def build_af(audio_rate, speed):
    filters = []

    # Pitch shift
    filters.append(f"asetrate=44100*{audio_rate:.4f}")
    filters.append("aresample=44100")

    # Speed/tempo
    filters.append(f"atempo={speed:.4f}")

    # Bass and treble
    bass   = random.uniform(-3, 3)
    treble = random.uniform(-3, 3)
    filters.append(f"bass=g={bass:.2f}")
    filters.append(f"treble=g={treble:.2f}")

    # Volume normalization variation
    vol = random.uniform(0.92, 1.08)
    filters.append(f"volume={vol:.4f}")

    return ",".join(filters)

def process_video(video_path, output_folder, ratio, idx, done, total):
    output_name = random_name(output_folder)
    output_path = os.path.join(output_folder, output_name)

    vf         = build_vf(ratio)
    fps        = random.choice([29.97, 30, 30.03])
    audio_rate = random.uniform(0.97, 1.03)
    speed      = random.uniform(0.97, 1.03)
    speed_vf   = f"setpts={1/speed:.4f}*PTS"
    full_vf    = f"{speed_vf},{vf}"
    af         = build_af(audio_rate, speed)
    duration   = get_duration(video_path)

    # Random CRF 18-22 — quality variation
    crf = random.randint(18, 22)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", full_vf,
        "-r", str(fps),
        "-af", af,
        "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", "fast",
        "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:2",
        output_path
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    eff_dur = max(1, duration)
    stderr_lines = []

    for line in proc.stderr:
        line = line.strip()
        stderr_lines.append(line)
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=")[1])
                file_pct = min(99, int(ms / 1_000_000 / eff_dur * 100))
                print(json.dumps({
                    "done": done, "total": total,
                    "video_index": idx + 1,
                    "file_pct": file_pct,
                    "processing": True
                }), flush=True)
            except:
                pass

    proc.wait()
    if proc.returncode != 0:
        error_lines = [l for l in stderr_lines if any(x in l.lower() for x in ["error","invalid","unknown","failed","no such"])]
        err_msg = "\n".join(error_lines[-3:]) if error_lines else "\n".join(stderr_lines[-3:])
        raise Exception(f"code {proc.returncode}: {err_msg}")

    strip_metadata(output_path)
    return output_name

def main():
    args       = json.loads(sys.argv[1])
    videos     = args["videos"]
    out_folder = args["outputFolder"]
    copies     = int(args["copies"])
    ratio      = args.get("ratio", "original")

    os.makedirs(out_folder, exist_ok=True)
    total = len(videos) * copies
    done  = 0

    for idx, vid_info in enumerate(videos):
        path           = vid_info["path"]
        subfolder_name = f"video_{idx+1}"
        sub_path       = os.path.join(out_folder, subfolder_name)
        os.makedirs(sub_path, exist_ok=True)

        log(f"Processing {os.path.basename(path)} — {copies} copies")

        for copy_i in range(copies):
            log(f"  Copy {copy_i+1}/{copies}...")
            try:
                out_name = process_video(path, sub_path, ratio, idx, done, total)
                done += 1
                print(json.dumps({
                    "done": done, "total": total,
                    "file": out_name, "subfolder": subfolder_name,
                    "video_index": idx + 1
                }), flush=True)
                log(f"  ✓ {out_name}")
            except Exception as e:
                done += 1
                log(f"  ERROR: {e}")
                print(json.dumps({
                    "done": done, "total": total,
                    "error": str(e),
                    "file": os.path.basename(path),
                    "subfolder": subfolder_name,
                    "video_index": idx + 1
                }), flush=True)

if __name__ == "__main__":
    main()
