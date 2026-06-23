'use strict'
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('app', { platform: process.platform })
contextBridge.exposeInMainWorld('electron', {
  toggleDashboard: (open) => ipcRenderer.send('toggle-dashboard', open),
})
