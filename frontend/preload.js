const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('smartDrafting', {
  selectFile: () => ipcRenderer.invoke('select-file'),
  extractDocument: (opts) => ipcRenderer.invoke('extract-document', opts),
  checkBackend: () => ipcRenderer.invoke('check-backend'),
  checkInternet: () => ipcRenderer.invoke('check-internet'),
  checkOllama: (model) => ipcRenderer.invoke('check-ollama', model),
  downloadModel: (model) => ipcRenderer.invoke('download-model', model),
  cancelDownload: () => ipcRenderer.invoke('cancel-download'),
  getOllamaPort: () => ipcRenderer.invoke('get-ollama-port'),
  onDownloadProgress: (callback) => {
    ipcRenderer.on('download-progress', (event, data) => callback(data));
  },
  removeDownloadProgressListener: () => {
    ipcRenderer.removeAllListeners('download-progress');
  }
});
