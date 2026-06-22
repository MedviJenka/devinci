'use strict'
// Renderer connects to Python WebSocket directly — nothing to bridge here.
const { contextBridge } = require('electron')
contextBridge.exposeInMainWorld('app', { platform: process.platform })
