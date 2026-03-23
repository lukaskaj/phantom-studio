const { exec, spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const https = require("https");
const http = require("http");
const os = require("os");
const { execSync } = require("child_process");

const IS_MAC   = process.platform === "darwin";
const IS_WIN   = process.platform === "win32";
const IS_LINUX = process.platform === "linux";

const TOOLS_DIR = path.join(os.homedir(), ".phantom-studio", "tools");
const DATA_DIR  = path.join(os.homedir(), ".phantom-studio");
const TMP_DIR   = os.tmpdir();

function ensureDirs() {
  [DATA_DIR, TOOLS_DIR].forEach(d => {
    try { fs.mkdirSync(d, { recursive: true }); } catch(e) {
      // Try alternative location if permission denied
      console.error("mkdir failed:", e.message);
    }
  });
}
ensureDirs();

// ── FIND BINARY ───────────────────────────────────────────────────────────────
function findBin(name) {
  const ext = IS_WIN ? ".exe" : "";
  const candidates = [];

  if (IS_WIN) {
    candidates.push(
      path.join(TOOLS_DIR, name + ext),
      path.join(TOOLS_DIR, "platform-tools", name + ext),
      path.join(TOOLS_DIR, "ffmpeg-master-latest-win64-gpl", "bin", name + ext),
      path.join(TOOLS_DIR, "ffmpeg", "bin", name + ext),
      `C:\\ffmpeg\\bin\\${name}${ext}`,
      `C:\\scrcpy\\${name}${ext}`,
      `C:\\Program Files\\scrcpy\\${name}${ext}`,
      path.join(process.env.LOCALAPPDATA || "", "Microsoft", "WinGet", "Packages", `Genymobile.scrcpy_Microsoft.Winget.Source_8wekyb3d8bbwe`, name + ext),
      path.join(process.env.USERPROFILE || "", "scrcpy", name + ext),
      name + ext, // also try PATH
    );
  } else if (IS_MAC) {
    candidates.push(
      `/opt/homebrew/bin/${name}`,
      `/usr/local/bin/${name}`,
      `/usr/bin/${name}`,
      path.join(TOOLS_DIR, name)
    );
  } else {
    candidates.push(
      `/usr/bin/${name}`,
      `/usr/local/bin/${name}`,
      path.join(TOOLS_DIR, name)
    );
  }

  for (const c of candidates) {
    try { if (fs.existsSync(c)) return c; } catch {}
  }
  return null;
}

function findPython() {
  const names = IS_WIN ? ["python", "python3", "py"] : ["python3", "python"];
  for (const n of names) {
    try {
      execSync(`"${n}" --version`, { timeout: 5000, stdio: "pipe" });
      return n;
    } catch {}
  }
  return null;
}

function getPaths() {
  return {
    python:   findPython()        || (IS_WIN ? "python" : "python3"),
    ffmpeg:   findBin("ffmpeg")   || "ffmpeg",
    exiftool: findBin("exiftool") || "exiftool",
    adb:      findBin("adb")      || "adb",
    scrcpy:   findBin("scrcpy")   || "scrcpy",
  };
}

// ── CHECK TOOLS ───────────────────────────────────────────────────────────────
function checkTool(cmd, args, timeout = 8000) {
  return new Promise(resolve => {
    try {
      const p = spawn(cmd, args);
      let done = false;
      p.on("close", code => { done = true; resolve(code === 0 || code === 1); });
      p.on("error", () => { done = true; resolve(false); });
      setTimeout(() => { if (!done) { try { p.kill(); } catch {} resolve(false); } }, timeout);
    } catch { resolve(false); }
  });
}

async function checkPython() { return !!findPython(); }

async function checkPip(py) {
  if (!py) return false;
  return new Promise(resolve => {
    try {
      exec(`"${py}" -c "import PIL, numpy, requests"`, { timeout: 10000 }, err => resolve(!err));
    } catch { resolve(false); }
  });
}

async function checkFfmpeg() {
  const ff = findBin("ffmpeg");
  if (!ff) return false;
  return checkTool(ff, ["-version"]);
}

async function checkExiftool() {
  const et = findBin("exiftool");
  if (!et) return false;
  return checkTool(et, ["-ver"]);
}

async function checkAdb() {
  // First check if file exists
  const adb = findBin("adb");
  if (!adb) return false;
  // Then verify it actually runs
  return checkTool(adb, ["version"]);
}

async function checkAll() {
  const pyPath = findPython() || (IS_WIN ? "python" : "python3");
  const [python, ffmpeg, exiftool, adb, scrcpy] = await Promise.all([
    checkPython(), checkFfmpeg(), checkExiftool(), checkAdb(),
    new Promise(resolve => {
      const p = findBin("scrcpy");
      if (p) return resolve(true);
      const { exec: ex } = require("child_process");
      ex("scrcpy --version", { timeout: 5000 }, err => resolve(!err));
    })
  ]);
  const pip = python ? await checkPip(pyPath) : false;
  return { python, pip, ffmpeg, exiftool, adb, scrcpy, pyPath };
}

// ── DOWNLOAD ──────────────────────────────────────────────────────────────────
function downloadFile(url, dest, onProgress) {
  return new Promise((resolve, reject) => {
    try { if (fs.existsSync(dest)) fs.unlinkSync(dest); } catch {}

    let file;
    try {
      file = fs.createWriteStream(dest);
    } catch(e) {
      return reject(new Error(`Cannot create file ${dest}: ${e.message}`));
    }

    function request(u, redirectCount = 0) {
      if (redirectCount > 10) return reject(new Error("Too many redirects"));
      const isHttps = u.startsWith("https");
      const protocol = isHttps ? https : http;
      const opts = { headers: { "User-Agent": "Mozilla/5.0 Phantom/1.0" } };

      protocol.get(u, opts, res => {
        if ([301, 302, 303, 307, 308].includes(res.statusCode)) {
          res.resume();
          const loc = res.headers.location;
          if (!loc) return reject(new Error("Redirect with no location"));
          const nextUrl = loc.startsWith("http") ? loc : new URL(loc, u).href;
          return request(nextUrl, redirectCount + 1);
        }
        if (res.statusCode !== 200) {
          res.resume();
          file.close();
          return reject(new Error(`HTTP ${res.statusCode}`));
        }
        const total = parseInt(res.headers["content-length"] || "0");
        let downloaded = 0;
        res.on("data", chunk => {
          downloaded += chunk.length;
          if (total && onProgress) onProgress(Math.round(downloaded / total * 100));
        });
        res.pipe(file);
        file.on("finish", () => { file.close(); resolve(); });
        file.on("error", err => { file.close(); reject(err); });
        res.on("error", err => { file.close(); reject(err); });
      }).on("error", err => { file.close(); reject(err); });
    }
    request(url);
  });
}

// ── UNZIP ─────────────────────────────────────────────────────────────────────
function unzip(zipPath, destDir, onLog) {
  return new Promise((resolve, reject) => {
    onLog && onLog("Extracting...");
    if (IS_WIN) {
      const ps = `powershell -NoProfile -NonInteractive -Command "Expand-Archive -LiteralPath '${zipPath}' -DestinationPath '${destDir}' -Force"`;
      exec(ps, { timeout: 300000 }, (err, stdout, stderr) => {
        if (err) reject(new Error(stderr || err.message));
        else resolve();
      });
    } else {
      exec(`unzip -o "${zipPath}" -d "${destDir}"`, { timeout: 300000 }, err => {
        if (err) reject(err); else resolve();
      });
    }
  });
}

// ── FIND FILE RECURSIVELY ─────────────────────────────────────────────────────
function findFileRecursive(dir, filename, maxDepth = 5) {
  if (maxDepth <= 0) return null;
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isFile() && e.name.toLowerCase() === filename.toLowerCase()) return full;
      if (e.isDirectory()) {
        const found = findFileRecursive(full, filename, maxDepth - 1);
        if (found) return found;
      }
    }
  } catch {}
  return null;
}

// ── WINDOWS AUTO-DOWNLOAD ─────────────────────────────────────────────────────
async function winDownloadFfmpeg(onLog, onProgress) {
  onLog("Downloading ffmpeg (~120MB)...");
  // Use tmpdir to avoid permission issues
  const zipPath = path.join(TMP_DIR, "phantom_ffmpeg.zip");
  const url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip";
  try {
    await downloadFile(url, zipPath, p => {
      onProgress && onProgress(p);
      if (p % 10 === 0) onLog(`Downloading ffmpeg... ${p}%`);
    });
  } catch(e) {
    onLog("Trying fallback...");
    const fallback = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
    const zipPath2 = path.join(TMP_DIR, "phantom_ffmpeg2.zip");
    await downloadFile(fallback, zipPath2, p => onProgress && onProgress(p));
    await unzip(zipPath2, TOOLS_DIR, onLog);
    try { fs.unlinkSync(zipPath2); } catch {}
    const ff = findFileRecursive(TOOLS_DIR, "ffmpeg.exe");
    if (ff) { const d = path.join(TOOLS_DIR, "ffmpeg.exe"); if (ff !== d) fs.copyFileSync(ff, d); }
    onLog("✓ ffmpeg installed");
    return;
  }
  await unzip(zipPath, TOOLS_DIR, onLog);
  try { fs.unlinkSync(zipPath); } catch {}

  const ffExe = findFileRecursive(TOOLS_DIR, "ffmpeg.exe");
  if (ffExe) {
    const dest = path.join(TOOLS_DIR, "ffmpeg.exe");
    if (ffExe !== dest) fs.copyFileSync(ffExe, dest);
  } else {
    throw new Error("ffmpeg.exe not found after extraction");
  }
  const ffprobeExe = findFileRecursive(TOOLS_DIR, "ffprobe.exe");
  if (ffprobeExe) {
    const dest = path.join(TOOLS_DIR, "ffprobe.exe");
    if (ffprobeExe !== dest) fs.copyFileSync(ffprobeExe, dest);
  }
  onLog("✓ ffmpeg installed");
}

async function winDownloadExiftool(onLog, onProgress) {
  onLog("Downloading exiftool...");
  const zipPath = path.join(TMP_DIR, "phantom_exiftool.zip");
  const url = "https://instara.s3.us-east-1.amazonaws.com/exiftool-13.44_64.zip";

  await downloadFile(url, zipPath, p => {
    onProgress && onProgress(p);
    if (p % 20 === 0) onLog(`Downloading exiftool... ${p}%`);
  });

  await unzip(zipPath, TOOLS_DIR, onLog);
  try { fs.unlinkSync(zipPath); } catch {}

  // Search for any .exe containing "exiftool" in name
  const dest = path.join(TOOLS_DIR, "exiftool.exe");
  let found = false;

  function searchExiftool(dir, depth = 0) {
    if (depth > 4 || found) return;
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const e of entries) {
        const full = path.join(dir, e.name);
        if (e.isFile() && e.name.toLowerCase().includes("exiftool") && e.name.endsWith(".exe")) {
          fs.copyFileSync(full, dest);
          found = true;
          return;
        }
        if (e.isDirectory()) searchExiftool(full, depth + 1);
      }
    } catch {}
  }

  searchExiftool(TOOLS_DIR);

  if (!found) throw new Error("exiftool.exe not found after extraction");
  onLog("✓ exiftool installed");
}

async function winDownloadAdb(onLog, onProgress) {
  onLog("Downloading ADB...");
  const zipPath = path.join(TMP_DIR, "phantom_adb.zip");
  const url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip";
  await downloadFile(url, zipPath, p => {
    onProgress && onProgress(p);
    if (p % 10 === 0) onLog(`Downloading ADB... ${p}%`);
  });
  await unzip(zipPath, TOOLS_DIR, onLog);
  try { fs.unlinkSync(zipPath); } catch {}

  // Copy ALL files from platform-tools to TOOLS_DIR root
  // adb.exe requires AdbWinApi.dll, AdbWinUsbApi.dll etc
  const ptDir = path.join(TOOLS_DIR, "platform-tools");
  if (fs.existsSync(ptDir)) {
    try {
      const files = fs.readdirSync(ptDir);
      for (const f of files) {
        const src = path.join(ptDir, f);
        const dst = path.join(TOOLS_DIR, f);
        try {
          if (fs.statSync(src).isFile()) fs.copyFileSync(src, dst);
        } catch {}
      }
      onLog(`Copied ${files.length} files from platform-tools`);
    } catch(e) { onLog("Warning: " + e.message); }
  }

  // Verify adb.exe exists
  const adbExe = path.join(TOOLS_DIR, "adb.exe");
  if (!fs.existsSync(adbExe)) throw new Error("adb.exe not found after extraction");
  onLog("✓ ADB installed");
}

// ── INSTALL MAC ───────────────────────────────────────────────────────────────
function installMac(tool, onLog) {
  return new Promise((resolve, reject) => {
    const brewMap = {
      python: "python3", ffmpeg: "ffmpeg",
      exiftool: "exiftool", adb: "android-platform-tools", scrcpy: "scrcpy"
    };
    const pkg = brewMap[tool];
    if (!pkg) return reject(new Error(`Unknown: ${tool}`));
    const brew = fs.existsSync("/opt/homebrew/bin/brew") ? "/opt/homebrew/bin/brew" : "brew";
    onLog(`Installing ${tool} via brew...`);
    const p = spawn(brew, ["install", pkg], {
      env: { ...process.env, PATH: "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" }
    });
    p.stdout.on("data", d => onLog(d.toString().trim()));
    p.stderr.on("data", d => onLog(d.toString().trim()));
    p.on("close", code => code === 0 ? resolve() : reject(new Error(`brew install ${pkg} failed`)));
  });
}

// ── INSTALL LINUX ─────────────────────────────────────────────────────────────
function installLinux(tool, onLog) {
  return new Promise((resolve, reject) => {
    const aptMap = {
      python: "python3 python3-pip", ffmpeg: "ffmpeg",
      exiftool: "libimage-exiftool-perl", adb: "android-tools-adb",
      scrcpy: "scrcpy"
    };
    const pkg = aptMap[tool];
    if (!pkg) return reject(new Error(`Unknown: ${tool}`));
    onLog(`Installing ${tool} via apt...`);
    const p = spawn("sudo", ["apt-get", "install", "-y", ...pkg.split(" ")]);
    p.stdout.on("data", d => onLog(d.toString().trim()));
    p.stderr.on("data", d => onLog(d.toString().trim()));
    p.on("close", code => code === 0 ? resolve() : reject(new Error("apt install failed")));
  });
}

// ── INSTALL SCRCPY WINDOWS ────────────────────────────────────────────────────
function winInstallScrcpy(onLog) {
  return new Promise((resolve, reject) => {
    onLog("Installing scrcpy via winget...");
    const p = spawn("winget", ["install", "Genymobile.scrcpy", "--accept-package-agreements", "--accept-source-agreements"], {
      shell: true
    });
    p.stdout.on("data", d => onLog(d.toString().trim()));
    p.stderr.on("data", d => onLog(d.toString().trim()));
    p.on("close", code => code === 0 ? resolve() : reject(new Error("winget install scrcpy failed — try manually: winget install Genymobile.scrcpy")));
    p.on("error", () => reject(new Error("winget not found — install manually: winget install Genymobile.scrcpy")));
  });
}

// ── INSTALL PIP ───────────────────────────────────────────────────────────────
function installPip(pyPath, onLog) {
  return new Promise((resolve, reject) => {
    onLog("Installing Python packages...");
    const args = ["-m", "pip", "install", "--upgrade", "Pillow", "numpy", "requests"];
    if (IS_LINUX) args.push("--break-system-packages");
    const p = spawn(pyPath, args);
    p.stdout.on("data", d => onLog(d.toString().trim()));
    p.stderr.on("data", d => onLog(d.toString().trim()));
    p.on("close", code => code === 0 ? resolve() : reject(new Error("pip install failed")));
  });
}

// ── MAIN DISPATCHER ───────────────────────────────────────────────────────────
async function installTool(tool, pyPath, onLog, onProgress) {
  if (IS_MAC)   return installMac(tool, onLog);
  if (IS_LINUX) return installLinux(tool, onLog);
  if (tool === "python") return { needsManual: true, instructions: getWindowsInstructions().python };
  if (tool === "ffmpeg")   { await winDownloadFfmpeg(onLog, onProgress);   return; }
  if (tool === "exiftool") { await winDownloadExiftool(onLog, onProgress); return; }
  if (tool === "adb")      { await winDownloadAdb(onLog, onProgress);      return; }
  if (tool === "scrcpy")   { await winInstallScrcpy(onLog);                return; }
}

function getWindowsInstructions() {
  return {
    python: { name: "Python 3", url: "https://www.python.org/downloads/", note: "Check 'Add Python to PATH' during install" }
  };
}

module.exports = {
  checkAll, installTool, installPip,
  getPaths, findBin, findPython,
  IS_MAC, IS_WIN, IS_LINUX,
  getWindowsInstructions, TOOLS_DIR
};
