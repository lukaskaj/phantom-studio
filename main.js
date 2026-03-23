const { app, BrowserWindow, ipcMain, dialog, Menu, MenuItem, clipboard, shell } = require("electron");
const { exec, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const setup = require("./setup");

const IS_PACKED = app.isPackaged;
const SCRIPTS_DIR = IS_PACKED ? path.join(process.resourcesPath, "scripts") : __dirname;
const BREW = "/opt/homebrew/bin";
const BREW2 = "/usr/local/bin";
const ENV = { ...process.env, PATH: `${BREW}:${BREW2}:/usr/bin:/bin:/usr/sbin:/sbin:${process.env.PATH || ""}` };

let mainWin = null;
let setupWin = null;

function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 920, height: 700, minWidth: 800, minHeight: 600,
    titleBarStyle: "hiddenInset", show: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false
    },
  });
  const htmlPath = IS_PACKED ? path.join(process.resourcesPath, "index.html") : path.join(__dirname, "index.html");
  mainWin.loadFile(htmlPath);
  mainWin.webContents.on("context-menu", (e, props) => {
    if (!props.isEditable) return;
    const menu = new Menu();
    if (clipboard.readText()) menu.append(new MenuItem({ label: "Paste", click: () => mainWin.webContents.paste() }));
    if (props.selectionText) {
      menu.append(new MenuItem({ label: "Copy", click: () => mainWin.webContents.copy() }));
      menu.append(new MenuItem({ label: "Cut",  click: () => mainWin.webContents.cut() }));
    }
    menu.append(new MenuItem({ label: "Select All", click: () => mainWin.webContents.selectAll() }));
    menu.popup({ window: mainWin });
  });
}

function createSetupWindow() {
  setupWin = new BrowserWindow({
    width: 560, height: 640, resizable: false,
    titleBarStyle: "hiddenInset",
    webPreferences: { nodeIntegration: true, contextIsolation: false },
  });
  const htmlPath = IS_PACKED ? path.join(process.resourcesPath, "setup.html") : path.join(__dirname, "setup.html");
  setupWin.loadFile(htmlPath);
}

app.whenReady().then(() => {
  createMainWindow();
  createSetupWindow();
});
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });

// SETUP IPC
ipcMain.handle("setup-check", async () => {
  const result = await setup.checkAll();
  return { ...result, isWin: setup.IS_WIN, winInstructions: setup.IS_WIN ? setup.getWindowsInstructions() : null };
});

ipcMain.handle("setup-install", async (event, tool) => {
  try {
    const pyPath = setup.findPython() || "python3";
    const result = await setup.installTool(
      tool, pyPath,
      (msg) => event.sender.send("setup-log", msg),
      (pct) => event.sender.send("setup-progress", pct)
    );
    if (result && result.needsManual) return { needsManual: true, url: result.instructions?.url };
    return { success: true };
  } catch (e) { return { success: false, error: e.message }; }
});

ipcMain.handle("setup-install-pip", async (event) => {
  try {
    const pyPath = setup.findPython() || "python3";
    await setup.installPip(pyPath, (msg) => event.sender.send("setup-log", msg));
    return { success: true };
  } catch (e) { return { success: false, error: e.message }; }
});

ipcMain.handle("setup-done", () => {
  if (setupWin) { setupWin.close(); setupWin = null; }
  mainWin.show();
});

ipcMain.handle("open-url", (e, url) => { shell.openExternal(url); });

// FOLDER/FILE PICKERS
ipcMain.handle("select-folder", async () => {
  const r = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  return r.filePaths[0] || null;
});
ipcMain.handle("select-files", async () => {
  const r = await dialog.showOpenDialog({ properties: ["openFile", "multiSelections"] });
  return r.filePaths || [];
});
ipcMain.handle("select-folder-files", async () => {
  const r = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  if (r.canceled || !r.filePaths[0]) return [];
  const folder = r.filePaths[0];
  const files = [];
  try {
    const entries = fs.readdirSync(folder, { withFileTypes: true });
    for (const e of entries) {
      const full = path.join(folder, e.name);
      if (e.isFile()) files.push(full);
      else if (e.isDirectory()) {
        try { fs.readdirSync(full, { withFileTypes: true }).filter(x => x.isFile()).forEach(x => files.push(path.join(full, x.name))); } catch {}
      }
    }
  } catch {}
  return files;
});

// IMAGE PROCESSING
ipcMain.on("start-image", (event, args) => {
  const paths = setup.getPaths();
  const script = path.join(SCRIPTS_DIR, "processor.py");
  const py = spawn(paths.python, [script, JSON.stringify(args)], { env: ENV });
  py.stdout.on("data", d => d.toString().split("\n").filter(Boolean).forEach(l => {
    try { event.sender.send("image-progress", JSON.parse(l)); } catch {}
  }));
  py.stderr.on("data", d => event.sender.send("image-log", d.toString()));
  py.on("close", () => event.sender.send("image-done"));
});

// VIDEO PROCESSING
ipcMain.on("start-video", (event, args) => {
  const paths = setup.getPaths();
  const script = path.join(SCRIPTS_DIR, "video_processor.py");
  const py = spawn(paths.python, [script, JSON.stringify(args)], { env: ENV });
  py.stdout.on("data", d => {
    d.toString().split("\n").filter(Boolean).forEach(l => {
      try {
        const parsed = JSON.parse(l);
        if (parsed.log) event.sender.send("video-log", parsed.log);
        else event.sender.send("video-progress", parsed);
      } catch {}
    });
  });
  py.stderr.on("data", d => event.sender.send("video-log", d.toString().trim()));
  py.on("close", () => event.sender.send("video-done"));
});

// ADB
ipcMain.handle("adb-devices", () => new Promise(resolve => {
  const paths = setup.getPaths();
  exec(`"${paths.adb}" devices`, { env: ENV }, (err, stdout) => {
    if (err) return resolve({ error: true });
    const devices = stdout.trim().split("\n").slice(1)
      .filter(l => l.trim())
      .map(l => { const [id, status] = l.split("\t"); return { id: id?.trim(), status: status?.trim() }; })
      .filter(d => d.id && d.status);
    resolve({ devices });
  });
}));

ipcMain.on("start-transfer", (event, { files, destination }) => {
  const paths = setup.getPaths();
  const dest = destination.endsWith("/") ? destination : destination + "/";
  let done = 0;
  const total = files.length;
  const next = (i) => {
    if (i >= files.length) {
      exec(`"${paths.adb}" shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://${dest}`, { env: ENV }, () => {});
      event.sender.send("transfer-done");
      return;
    }
    const cmd = spawn(paths.adb, ["push", files[i], dest], { env: ENV });
    cmd.stderr.on("data", d => {
      const s = d.toString().trim();
      const m = s.match(/(\d+)%/);
      event.sender.send("transfer-progress", { file: path.basename(files[i]), done, total, pct: m ? parseInt(m[1]) : null });
    });
    cmd.on("close", code => {
      done++;
      event.sender.send("transfer-progress", { file: path.basename(files[i]), done, total, finished: true, success: code === 0 });
      next(i + 1);
    });
  };
  next(0);
});

// SCRCPY
let scrcpyProc = null;
ipcMain.handle("check-scrcpy", () => new Promise(resolve => {
  const p = setup.findBin("scrcpy");
  if (p) return resolve(true);
  // Also try running scrcpy directly from PATH
  const { exec } = require("child_process");
  exec("scrcpy --version", { env: ENV, timeout: 5000 }, (err) => {
    resolve(!err);
  });
}));
ipcMain.handle("launch-scrcpy", (event, opts) => new Promise(resolve => {
  if (scrcpyProc) { scrcpyProc.kill(); scrcpyProc = null; }
  const scrcpy = setup.findBin("scrcpy") || "scrcpy";
  const args = [];
  if (opts.maxFps)     args.push(`--max-fps=${opts.maxFps}`);
  if (opts.bitrate)    args.push(`--video-bit-rate=${opts.bitrate}M`);
  if (opts.noAudio)    args.push("--no-audio");
  if (opts.fullscreen) args.push("--fullscreen");
  if (opts.stayAwake)  args.push("--stay-awake");
  if (opts.record)     args.push("--record", opts.record);
  scrcpyProc = exec(`"${scrcpy}" ${args.join(" ")}`, { env: ENV },
    () => { scrcpyProc = null; event.sender.send("scrcpy-stopped"); }
  );
  scrcpyProc.on("error", err => resolve({ error: err.message }));
  setTimeout(() => resolve({ ok: true }), 800);
}));
ipcMain.handle("stop-scrcpy", () => { if (scrcpyProc) { scrcpyProc.kill(); scrcpyProc = null; } return true; });
