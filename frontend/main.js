const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');

// ============================================================
// MAIN PROCESS - Electron
// ============================================================

let mainWindow;
let backendProcess = null;
let ollamaProcess = null;

const OLLAMA_PORT = 11435;
const DEFAULT_OLLAMA_MODEL = 'qwen2.5:3b';
const SUPPORTED_OLLAMA_MODELS = ['qwen2.5:1.5b', 'gemma2:2b', 'qwen2.5:3b', 'phi3.5:3.8b', 'qwen2.5:7b'];

// ============================================================
// BACKEND SPAWN
// ============================================================

function getBackendPaths() {
  const isPackaged = app.isPackaged;

  if (isPackaged) {
    const resourcesPath = process.resourcesPath;
    const backendDist = path.join(resourcesPath, 'backend-dist');

    if (process.platform === 'win32') {
      return {
        executable: path.join(backendDist, 'smart_drafting_backend.exe'),
        cwd: backendDist,
        useExecutable: true
      };
    } else {
      return {
        executable: path.join(backendDist, 'smart_drafting_backend'),
        cwd: backendDist,
        useExecutable: true
      };
    }
  } else {
    const projectRoot = path.join(__dirname, '..');
    const venvPython = process.platform === 'win32'
      ? path.join(projectRoot, 'venv', 'Scripts', 'python.exe')
      : path.join(projectRoot, 'venv', 'bin', 'python3');

    const pythonBin = fs.existsSync(venvPython) ? venvPython : 'python3';

    return {
      executable: pythonBin,
      args: [path.join(projectRoot, 'run_web.py')],
      cwd: projectRoot,
      useExecutable: false
    };
  }
}

function startBackend() {
  const { executable, args, cwd, useExecutable } = getBackendPaths();

  const spawnArgs = useExecutable ? [] : (args || []);
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    OLLAMA_PORT: String(OLLAMA_PORT)
  };

  backendProcess = spawn(executable, spawnArgs, {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  backendProcess.stdout.on('data', (data) => {
    console.log('[backend]', data.toString().trim());
  });

  backendProcess.stderr.on('data', (data) => {
    console.error('[backend:err]', data.toString().trim());
  });

  backendProcess.on('exit', (code) => {
    console.log('[backend] exited with code', code);
    backendProcess = null;
  });
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

function waitForBackend(retries = 20, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      const req = http.request(
        { hostname: '127.0.0.1', port: 8500, path: '/health', method: 'GET', family: 4 },
        (res) => { resolve(true); }
      );
      req.on('error', () => {
        attempts++;
        if (attempts >= retries) {
          reject(new Error('Backend failed to start'));
        } else {
          setTimeout(check, interval);
        }
      });
      req.setTimeout(1000, () => { req.destroy(); });
      req.end();
    };
    check();
  });
}

// ============================================================
// OLLAMA MANAGEMENT
// ============================================================

function getOllamaBinPath() {
  if (app.isPackaged) {
    const ext = process.platform === 'win32' ? '.exe' : '';
    return path.join(process.resourcesPath, 'ollama', `ollama${ext}`);
  }
  // Dev mode: pakai dari ollama-bin/ di project root
  const projectRoot = path.join(__dirname, '..');
  if (process.platform === 'win32') {
    return path.join(projectRoot, 'ollama-bin', 'win', 'ollama.exe');
  }
  return path.join(projectRoot, 'ollama-bin', 'mac', 'ollama');
}

function getOllamaModelsDir() {
  return path.join(app.getPath('userData'), 'ollama-models');
}

function startOllama() {
  const ollamaBin = getOllamaBinPath();
  const modelsDir = getOllamaModelsDir();

  if (!fs.existsSync(modelsDir)) {
    fs.mkdirSync(modelsDir, { recursive: true });
  }

  if (!fs.existsSync(ollamaBin)) {
    console.log('[ollama] binary not found at', ollamaBin, '— skipping');
    return;
  }

  const env = {
    ...process.env,
    OLLAMA_MODELS: modelsDir,
    OLLAMA_HOST: `127.0.0.1:${OLLAMA_PORT}`,
    OLLAMA_ORIGINS: '*'
  };

  ollamaProcess = spawn(ollamaBin, ['serve'], {
    env,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  ollamaProcess.stdout.on('data', (d) => console.log('[ollama]', d.toString().trim()));
  ollamaProcess.stderr.on('data', (d) => console.log('[ollama:err]', d.toString().trim()));
  ollamaProcess.on('exit', (code) => {
    console.log('[ollama] exited with code', code);
    ollamaProcess = null;
  });

  console.log('[ollama] started on port', OLLAMA_PORT);
}

function stopOllama() {
  if (ollamaProcess) {
    ollamaProcess.kill();
    ollamaProcess = null;
  }
}

function pingOllama() {
  return new Promise((resolve) => {
    const req = http.request(
      { hostname: '127.0.0.1', port: OLLAMA_PORT, path: '/api/tags', method: 'GET', family: 4 },
      (res) => {
        let data = '';
        res.on('data', (c) => { data += c; });
        res.on('end', () => {
          try { resolve({ online: true, data: JSON.parse(data) }); }
          catch (e) { resolve({ online: false }); }
        });
      }
    );
    req.on('error', () => resolve({ online: false }));
    req.setTimeout(2000, () => { req.destroy(); resolve({ online: false }); });
    req.end();
  });
}

// ============================================================
// WINDOW
// ============================================================

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1024,
    minHeight: 700,
    title: 'SINSW Smart Drafting Engine - POC Demo',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      enableRemoteModule: false
    },
    icon: path.join(__dirname, 'public', 'icon.png')
  });

  mainWindow.loadFile(path.join(__dirname, 'public', 'index.html'));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  startBackend();
  startOllama();
  try {
    await waitForBackend();
  } catch (e) {
    console.error('Backend did not start in time:', e.message);
  }
  createWindow();
});

app.on('window-all-closed', () => {
  stopBackend();
  stopOllama();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackend();
  stopOllama();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// ============================================================
// IPC HANDLERS
// ============================================================

ipcMain.handle('select-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Pilih Dokumen untuk OCR Extraction',
    filters: [
      { name: 'Documents', extensions: ['pdf', 'png', 'jpg', 'jpeg', 'tiff', 'bmp'] },
      { name: 'PDF Files', extensions: ['pdf'] },
      { name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'tiff', 'bmp'] },
      { name: 'All Files', extensions: ['*'] }
    ],
    properties: ['openFile']
  });

  if (result.canceled || result.filePaths.length === 0) return null;

  const filePath = result.filePaths[0];
  const stats = fs.statSync(filePath);
  return {
    path: filePath,
    name: path.basename(filePath),
    size: stats.size,
    extension: path.extname(filePath).toLowerCase()
  };
});

ipcMain.handle('extract-document', async (event, { filePath, aiMode, apiKey, ollamaModel }) => {
  return new Promise((resolve, reject) => {
    const fileBuffer = fs.readFileSync(filePath);
    const fileName = path.basename(filePath);
    const boundary = '----FormBoundary' + Math.random().toString(36).substr(2);

    const header = `------FormBoundary${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${fileName}"\r\nContent-Type: application/octet-stream\r\n\r\n`;
    const footer = `\r\n------FormBoundary${boundary}--\r\n`;
    const bodyBuffer = Buffer.concat([Buffer.from(header), fileBuffer, Buffer.from(footer)]);

    const reqHeaders = {
      'Content-Type': `multipart/form-data; boundary=----FormBoundary${boundary}`,
      'Content-Length': bodyBuffer.length,
      'X-AI-Mode': aiMode || 'auto',
      'X-Ollama-Port': String(OLLAMA_PORT),
      'X-Ollama-Model': ollamaModel || DEFAULT_OLLAMA_MODEL
    };
    if (apiKey) reqHeaders['X-Groq-API-Key'] = apiKey;

    const options = {
      hostname: '127.0.0.1',
      port: 8500,
      path: '/extract',
      method: 'POST',
      family: 4,
      headers: reqHeaders
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error('Failed to parse response: ' + data)); }
      });
    });

    req.setTimeout(180000, () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    req.on('error', (e) => {
      reject(new Error('Backend not running: ' + e.message));
    });

    req.write(bodyBuffer);
    req.end();
  });
});

ipcMain.handle('check-backend', async () => {
  return new Promise((resolve) => {
    const options = {
      hostname: '127.0.0.1',
      port: 8500,
      path: '/health',
      method: 'GET',
      family: 4
    };
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { resolve({ status: 'error' }); }
      });
    });
    req.on('error', () => resolve({ status: 'offline' }));
    req.setTimeout(3000, () => { req.destroy(); resolve({ status: 'timeout' }); });
    req.end();
  });
});

ipcMain.handle('check-internet', async () => {
  return new Promise((resolve) => {
    const req = https.request(
      { hostname: '1.1.1.1', port: 443, path: '/', method: 'HEAD', timeout: 3000 },
      () => { resolve({ online: true }); }
    );
    req.on('error', () => resolve({ online: false }));
    req.on('timeout', () => { req.destroy(); resolve({ online: false }); });
    req.end();
  });
});

ipcMain.handle('check-ollama', async (event, model = DEFAULT_OLLAMA_MODEL) => {
  const selectedModel = SUPPORTED_OLLAMA_MODELS.includes(model) ? model : DEFAULT_OLLAMA_MODEL;
  const result = await pingOllama();
  if (!result.online) return { online: false, modelReady: false, selectedModel, supportedModels: SUPPORTED_OLLAMA_MODELS };
  const models = (result.data?.models || []).map(m => m.name || '');
  const modelReady = models.some(m => m === selectedModel || m.startsWith(selectedModel + ':') || m.includes(selectedModel));
  return { online: true, modelReady, models, selectedModel, supportedModels: SUPPORTED_OLLAMA_MODELS };
});

let downloadProcess = null;

ipcMain.handle('download-model', async (event, model = DEFAULT_OLLAMA_MODEL) => {
  return new Promise((resolve, reject) => {
    const selectedModel = SUPPORTED_OLLAMA_MODELS.includes(model) ? model : DEFAULT_OLLAMA_MODEL;
    const ollamaBin = getOllamaBinPath();
    const modelsDir = getOllamaModelsDir();

    const binExists = fs.existsSync(ollamaBin);

    if (!binExists) {
      reject(new Error(
        'Ollama tidak ditemukan.\n\n' +
        'Install Ollama terlebih dahulu:\n' +
        '  macOS: brew install ollama\n' +
        '  Windows: download dari https://ollama.com/download\n\n' +
        'Setelah install, restart aplikasi.'
      ));
      return;
    }

    const env = {
      ...process.env,
      OLLAMA_MODELS: modelsDir,
      OLLAMA_HOST: `127.0.0.1:${OLLAMA_PORT}`
    };

    downloadProcess = spawn(ollamaBin, ['pull', selectedModel], {
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    downloadProcess.on('error', (err) => {
      downloadProcess = null;
      reject(new Error('Gagal menjalankan Ollama: ' + err.message));
    });

    downloadProcess.stdout.on('data', (data) => {
      const line = data.toString().trim();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('download-progress', { line });
      }
    });

    downloadProcess.stderr.on('data', (data) => {
      const line = data.toString().trim();
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('download-progress', { line });
      }
    });

    downloadProcess.on('exit', (code) => {
      downloadProcess = null;
      if (code === 0) {
        resolve({ success: true });
      } else {
        reject(new Error(`Download gagal (exit code ${code})`));
      }
    });
  });
});

ipcMain.handle('cancel-download', async () => {
  if (downloadProcess) {
    downloadProcess.kill();
    downloadProcess = null;
  }
  return { cancelled: true };
});

ipcMain.handle('get-ollama-port', async () => ({ port: OLLAMA_PORT }));
