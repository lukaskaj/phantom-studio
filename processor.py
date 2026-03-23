import os
import sys
import random
import json
import time
import subprocess
import requests
from io import BytesIO
from PIL import Image, ImageFilter, ImageDraw
import numpy as np

# ── API ENDPOINTS ─────────────────────────────────────────────────────────────
UPLOAD_URL      = "https://kieai.redpandaai.co/api/file-stream-upload"
CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
POLL_URL        = "https://api.kie.ai/api/v1/jobs/recordInfo"

# ── POSE PROMPT GENERATOR ─────────────────────────────────────────────────────
_HEAD_TILTS = [
    "very slightly tilts their head to the right",
    "very slightly tilts their head to the left",
    "tilts their head just a tiny bit forward",
    "tilts their head back ever so slightly",
    "has a subtle diagonal head tilt to the right",
    "has a subtle diagonal head tilt to the left",
    "keeps their head perfectly level and centered",
    "turns their head just a few degrees to the right",
    "turns their head just a few degrees to the left",
    "rotates their head very slightly clockwise",
    "rotates their head very slightly counterclockwise",
]
_CHIN = [
    "lowers their chin slightly",
    "raises their chin very slightly upward",
    "tucks their chin in just a little",
    "lifts their chin with a subtle confident tilt",
    "keeps their chin at a natural relaxed angle",
    "drops their chin just a touch toward their chest",
    "juts their chin forward ever so slightly",
]
_GAZE = [
    "gazes directly forward with a relaxed expression",
    "shifts their gaze very slightly to the right",
    "shifts their gaze very slightly to the left",
    "glances subtly upward",
    "looks slightly downward with a soft expression",
    "looks off into the middle distance",
    "has a soft unfocused gaze",
    "looks directly into the camera with a calm expression",
    "has eyes very slightly narrowed in a natural squint",
]
_SHOULDERS = [
    "keeps shoulders relaxed and even",
    "drops their right shoulder very slightly",
    "drops their left shoulder very slightly",
    "rolls their shoulders back just a touch",
    "has one shoulder slightly higher than the other",
    "relaxes their shoulders downward naturally",
    "pulls shoulders back subtly for a confident posture",
    "has slightly rounded relaxed shoulders",
]
_BODY = [
    "stands with weight evenly distributed",
    "shifts their weight subtly to the right leg",
    "shifts their weight subtly to the left leg",
    "has a very slight lean to the right",
    "has a very slight lean to the left",
    "stands slightly more upright",
    "has a very subtle forward lean",
    "turns their torso just a few degrees to the right",
    "turns their torso just a few degrees to the left",
]
_HANDS = [
    "lets arms hang naturally at their sides",
    "rests one hand lightly on their hip",
    "has both hands resting at their sides",
    "gently touches their collarbone with one hand",
    "crosses arms very loosely and casually",
    "holds one arm with the opposite hand loosely",
    "has fingers lightly interlaced in front",
    "rests one hand lightly against their thigh",
]
_EXPRESSION = [
    "with a soft natural smile",
    "with a relaxed neutral expression",
    "with a subtle confident expression",
    "with a calm serene expression",
    "with a gentle approachable expression",
    "with a natural candid expression",
    "with a thoughtful expression",
    "with a warm friendly expression",
    "with a composed professional expression",
    "with eyes slightly brightened",
]
_PRESERVE = [
    "keep all clothing, background, lighting and style completely identical, minimal pose change only",
    "preserve all background, outfit, lighting and setting exactly, only adjust the pose minimally",
    "maintain identical background, clothing, colors and lighting, change only the pose slightly",
    "keep the scene, outfit and lighting exactly the same, only the pose changes minimally",
    "do not change background, clothing or lighting, apply only a minimal subtle pose adjustment",
]

def generate_pose_prompt():
    core = random.choice([
        random.choice(_HEAD_TILTS),
        f"{random.choice(_HEAD_TILTS)} and {random.choice(_CHIN)}",
        f"{random.choice(_HEAD_TILTS)} and {random.choice(_GAZE)}",
        random.choice(_CHIN),
        random.choice(_GAZE),
    ])
    extras = []
    if random.random() < 0.6: extras.append(random.choice(_SHOULDERS))
    if random.random() < 0.4: extras.append(random.choice(_BODY))
    if random.random() < 0.4: extras.append(random.choice(_HANDS))
    prompt = f"The person {core}"
    if extras: prompt += ", " + ", ".join(extras)
    prompt += f", {random.choice(_EXPRESSION)}. {random.choice(_PRESERVE)}"
    return prompt

# ── LOGGING ───────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[LOG] {msg}", file=sys.stderr, flush=True)

def emit(data):
    print(json.dumps(data), flush=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def random_img_name(folder):
    while True:
        name = f"IMG_{random.randint(1000,9999)}.jpg"
        if not os.path.exists(os.path.join(folder, name)):
            return name

def strip_metadata(path):
    try:
        subprocess.run(["exiftool", "-all=", "-overwrite_original", "-q", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

# ── ASPECT RATIO ──────────────────────────────────────────────────────────────
def apply_aspect_ratio(img, ratio):
    """
    ratio: 'ig' = 3:4 (1080x1440)
           'tiktok' = 9:16 (1080x1920)
           'original' = no change
    Smart center crop to fit ratio.
    """
    if ratio == "original":
        return img

    w, h = img.size

    if ratio == "ig":
        target_w, target_h = 3, 4
    else:  # tiktok
        target_w, target_h = 9, 16

    # Calculate target dimensions
    if w / h > target_w / target_h:
        # Image is wider — crop width
        new_w = int(h * target_w / target_h)
        new_h = h
    else:
        # Image is taller — crop height
        new_w = w
        new_h = int(w * target_h / target_w)

    # Center crop
    left = (w - new_w) // 2
    top  = (h - new_h) // 2
    img = img.crop((left, top, left + new_w, top + new_h))

    # Resize to standard resolution
    if ratio == "ig":
        img = img.resize((1080, 1440), Image.LANCZOS)
    else:
        img = img.resize((1080, 1920), Image.LANCZOS)

    return img

# ── INVISIBLE TWEAKS ──────────────────────────────────────────────────────────
def apply_invisible(img):
    """Core invisible pixel-level changes"""
    w, h = img.size

    # Micro crop 3-8%
    crop_pct = random.uniform(0.92, 0.97)
    cw, ch = int(w * crop_pct), int(h * crop_pct)
    left = random.randint(0, w - cw)
    top  = random.randint(0, h - ch)
    img = img.crop((left, top, left + cw, top + ch))
    img = img.resize((w, h), Image.LANCZOS)

    # Sub-pixel noise ±3
    arr = np.array(img, dtype=np.int16)
    arr = np.clip(arr + np.random.randint(-3, 4, arr.shape, dtype=np.int16), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # RGB channel shift ±4
    r, g, b = img.split()
    def sc(ch, a):
        return Image.fromarray(np.clip(np.array(ch, dtype=np.int16) + a, 0, 255).astype(np.uint8))
    img = Image.merge("RGB", (
        sc(r, random.randint(-4, 4)),
        sc(g, random.randint(-4, 4)),
        sc(b, random.randint(-4, 4)),
    ))

    # Resize trick
    scale = random.uniform(0.996, 0.999)
    img = img.resize((max(1, int(w*scale)), max(1, int(h*scale))), Image.LANCZOS)
    img = img.resize((w, h), Image.LANCZOS)

    return img

# ── COLOR GRADING ─────────────────────────────────────────────────────────────
def apply_color_grade(img):
    """Subtle but effective color grading"""
    style = random.choice(["warm", "cool", "fade", "vivid", "neutral"])
    arr = np.array(img, dtype=np.float32)

    if style == "warm":
        arr[:,:,0] = np.clip(arr[:,:,0] * random.uniform(1.04, 1.08), 0, 255)  # +red
        arr[:,:,2] = np.clip(arr[:,:,2] * random.uniform(0.92, 0.96), 0, 255)  # -blue
    elif style == "cool":
        arr[:,:,0] = np.clip(arr[:,:,0] * random.uniform(0.92, 0.96), 0, 255)  # -red
        arr[:,:,2] = np.clip(arr[:,:,2] * random.uniform(1.04, 1.08), 0, 255)  # +blue
    elif style == "fade":
        arr = arr * random.uniform(0.88, 0.94) + random.uniform(15, 25)
        arr = np.clip(arr, 0, 255)
    elif style == "vivid":
        mean = arr.mean(axis=(0,1), keepdims=True)
        arr = np.clip(mean + (arr - mean) * random.uniform(1.08, 1.14), 0, 255)
    # neutral = no change

    # Brightness ±5%
    brightness = random.uniform(0.95, 1.05)
    arr = np.clip(arr * brightness, 0, 255)

    # Contrast ±5%
    contrast = random.uniform(0.95, 1.05)
    arr = np.clip(128 + (arr - 128) * contrast, 0, 255)

    return Image.fromarray(arr.astype(np.uint8))

# ── OVERLAYS ──────────────────────────────────────────────────────────────────
def apply_overlays(img):
    """Truly invisible overlays — change hash but undetectable to human eye"""
    w, h = img.size
    arr = np.array(img, dtype=np.float32)

    # 1. Noise grain — very subtle ±3
    grain = np.random.normal(0, random.uniform(2, 4), arr.shape)
    arr = np.clip(arr + grain, 0, 255)

    # 2. Micro vignette — extremely subtle, max 4% darkening at edges
    if random.random() < 0.7:
        strength = random.uniform(0.02, 0.04)
        Y, X = np.ogrid[:h, :w]
        cx, cy = w / 2, h / 2
        dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
        vignette = 1 - strength * (dist ** 2)
        vignette = np.clip(vignette, 0, 1)
        arr = arr * vignette[:, :, np.newaxis]

    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # 3. Micro dot — 1px, random color, random position
    if random.random() < 0.6:
        draw = ImageDraw.Draw(img)
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        draw.point((x, y), fill=(random.randint(0,255), random.randint(0,255), random.randint(0,255)))

    # 4. Subtle single channel tint ±3
    if random.random() < 0.5:
        arr2 = np.array(img, dtype=np.float32)
        ch = random.randint(0, 2)
        arr2[:,:,ch] = np.clip(arr2[:,:,ch] + random.uniform(-3, 3), 0, 255)
        img = Image.fromarray(arr2.astype(np.uint8))

    return img

def square_crop(img):
    w, h = img.size
    s = min(w, h)
    return img.crop(((w-s)//2, (h-s)//2, (w+s)//2, (h+s)//2))

def save_img(img, folder):
    quality = random.randint(91, 96)
    name = random_img_name(folder)
    path = os.path.join(folder, name)
    img.save(path, "JPEG", quality=quality, optimize=True)
    strip_metadata(path)
    return name

# ── PROCESSING MODES ──────────────────────────────────────────────────────────
def process_normal(image_path, folder, do_square, ratio):
    img = Image.open(image_path).convert("RGB")
    if do_square:
        img = square_crop(img)
    img = apply_aspect_ratio(img, ratio)
    img = apply_invisible(img)
    img = apply_color_grade(img)
    return save_img(img, folder)

def process_pose(image_path, folder, do_square, ratio, api_key):
    file_url = upload_image(image_path, api_key)
    task_id  = create_task(file_url, api_key)
    result_url = poll_task(task_id, api_key)
    img = download_image(result_url)
    if do_square:
        img = square_crop(img)
    img = apply_aspect_ratio(img, ratio)
    img = apply_invisible(img)
    img = apply_color_grade(img)
    return save_img(img, folder)

# ── KIE AI API ────────────────────────────────────────────────────────────────
def upload_image(image_path, api_key):
    log(f"Uploading {os.path.basename(image_path)}...")
    headers = {"Authorization": f"Bearer {api_key}"}
    with open(image_path, "rb") as f:
        files = {"file": (os.path.basename(image_path), f, "image/jpeg"), "uploadPath": (None, "images")}
        resp = requests.post(UPLOAD_URL, headers=headers, files=files, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    log(f"Upload response: {json.dumps(data)}")
    if not data.get("success") and data.get("code") != 200:
        raise Exception(f"Upload failed: {data.get('msg')}")
    url = data["data"]["downloadUrl"]
    log(f"File URL: {url}")
    return url

def create_task(file_url, api_key):
    prompt = generate_pose_prompt()
    log(f"Pose prompt: {prompt[:60]}...")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "bytedance/seedream-v4-edit",
        "input": {
            "prompt": prompt,
            "image_urls": [file_url],
            "image_size": "square_hd",
            "image_resolution": "1K",
            "max_images": 1,
            "seed": random.randint(1, 999999),
            "nsfw_checker": True
        }
    }
    resp = requests.post(CREATE_TASK_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    log(f"Task ID: {data['data']['taskId']}")
    return data["data"]["taskId"]

def poll_task(task_id, api_key, max_wait=180):
    log(f"Polling task {task_id}...")
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + max_wait
    while time.time() < deadline:
        resp = requests.get(POLL_URL, headers=headers, params={"taskId": task_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()["data"]
        state = data.get("state", "")
        log(f"State: {state}")
        if state == "success":
            log(f"Full data: {json.dumps(data)}")
            result_json = {}
            raw = data.get("resultJson")
            if raw and isinstance(raw, str):
                try: result_json = json.loads(raw)
                except: pass
            elif raw and isinstance(raw, dict):
                result_json = raw
            urls = (result_json.get("resultUrls") or result_json.get("images") or
                    result_json.get("output", {}).get("images") or data.get("resultUrls") or [])
            if not urls:
                raise Exception(f"No image URL in result: {json.dumps(data)}")
            first = urls[0]
            img_url = first if isinstance(first, str) else first.get("url", "")
            log(f"Result URL: {img_url}")
            return img_url
        elif state in ("fail", "failed", "error"):
            raise Exception(f"Task failed: {data.get('failMsg') or data.get('failCode')}")
        time.sleep(4)
    raise Exception(f"Timeout after {max_wait}s")

def download_image(url):
    log("Downloading result...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGB")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    args        = json.loads(sys.argv[1])
    images      = args["images"]
    out_folder  = args["outputFolder"]
    copies      = int(args["copies"])
    api_key     = args.get("apiKey", "").strip()
    ratio       = args.get("ratio", "original")  # 'ig', 'tiktok', 'original'

    os.makedirs(out_folder, exist_ok=True)
    total = len(images) * copies
    done  = 0

    for idx, img_info in enumerate(images):
        path      = img_info["path"]
        do_square = img_info.get("squareCrop", False)
        do_pose   = img_info.get("poseEdit", False) and bool(api_key)

        subfolder = f"photo_{idx+1}"
        sub_path  = os.path.join(out_folder, subfolder)
        os.makedirs(sub_path, exist_ok=True)

        log(f"\n=== photo_{idx+1}: {os.path.basename(path)} | pose={do_pose} | ratio={ratio} ===")

        for _ in range(copies):
            try:
                if do_pose:
                    out_name = process_pose(path, sub_path, do_square, ratio, api_key)
                else:
                    out_name = process_normal(path, sub_path, do_square, ratio)
                done += 1
                emit({"done": done, "total": total, "file": out_name, "subfolder": subfolder, "photo_index": idx+1})
            except Exception as e:
                log(f"ERROR: {e}")
                done += 1
                emit({"done": done, "total": total, "error": str(e), "file": os.path.basename(path), "subfolder": subfolder, "photo_index": idx+1})

if __name__ == "__main__":
    main()
