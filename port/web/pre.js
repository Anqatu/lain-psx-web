(() => {
  const cardPath = '/persist/memcard1.mcd';
  const cardSize = 128 * 1024;
  let restored = false;
  let restoreError = '';
  let saveError = '';
  let snapshot = null;
  let lastTimestamp = 0;
  let pendingWrites = 0;
  let importing = false;
  let importAck = null;
  let writeQueue = Promise.resolve();

  Module['lainGameLaunched'] = false;

  function publishSaveState() {
    const info = {
      ready: restored,
      hasCard: snapshot !== null,
      saving: pendingWrites > 0,
      importing,
      error: restoreError || saveError
    };
    Module['lainSaveInfo'] = info;
    Module['lainSaveStateChanged']?.(info);
  }

  function copyCard(bytes) {
    if (!(bytes instanceof Uint8Array) || bytes.byteLength !== cardSize)
      throw Module['lainError']('save.cardSize');
    // Do not pass SharedArrayBuffer or mutable Wasm memory directly to Blob/IndexedDB.
    return new Uint8Array(bytes);
  }

  Module['preRun'] = Module['preRun'] || [];
  Module['preRun'].push(function () {
    addRunDependency('lain-idbfs');
    const finish = error => {
      try {
        if (error) throw error;
        if (FS.analyzePath(cardPath).exists) {
          snapshot = copyCard(FS.readFile(cardPath));
          lastTimestamp = Number(FS.stat(cardPath).mtime);
        }
        restored = true;
      } catch (error) {
        restoreError = Module['lainError']('save.restoreFailed', { detail: error });
        console.error(restoreError, error);
      } finally {
        publishSaveState();
        removeRunDependency('lain-idbfs');
      }
    };
    try {
      FS.mkdirTree('/persist');
      // Preserve existing database paths and avoid races with automatic synchronization.
      FS.mount(IDBFS, { autoPersist: false }, '/persist');
      FS.syncfs(true, finish);
    } catch (error) { finish(error); }
  });

  Module['lainStoreCard'] = function (bytes) {
    if (!restored) return Promise.reject(restoreError || Module['lainError']('save.restoring'));
    const next = copyCard(bytes);
    pendingWrites++;
    publishSaveState();
    const result = writeQueue.then(async () => {
      // Export a complete card snapshot rather than a partially written filesystem file.
      snapshot = next;
      saveError = '';
      publishSaveState();
      try {
        FS.writeFile(cardPath, next);
        // IDBFS compares only mtime; distinguish consecutive saves within the same millisecond.
        lastTimestamp = Math.max(Date.now(), lastTimestamp + 1);
        FS.utime(cardPath, lastTimestamp, lastTimestamp);
        await new Promise((resolve, reject) => {
          FS.syncfs(false, error => error ? reject(error) : resolve());
        });
      } catch (error) {
        saveError = Module['lainError']('save.persistFailed', { detail: error });
        throw saveError;
      } finally {
        pendingWrites--;
        publishSaveState();
      }
    });
    // Report failure to the caller without blocking later save requests.
    writeQueue = result.catch(() => {});
    return result;
  };

  Module['lainExportSave'] = function () {
    if (!snapshot) throw Module['lainError']('save.none');
    const blob = new Blob([copyCard(snapshot)], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'memcard1.mcd';
    link.hidden = true;
    document.body.appendChild(link);
    try {
      // Start the download during the user's click without awaiting persistence.
      link.click();
    } finally {
      setTimeout(() => {
        link.remove();
        URL.revokeObjectURL(url);
      }, 60000);
    }
  };

  Module['lainImportComplete'] = function (success) {
    const pending = importAck;
    importAck = null;
    if (!pending) return;
    if (success) pending.resolve();
    else pending.reject(saveError || Module['lainError']('save.importFailed'));
  };

  Module['lainCancelSaveOperations'] = function () {
    if (importAck) {
      importAck.reject(Module['lainError']('save.importStopped'));
      importAck = null;
    }
  };

  Module['lainImportSave'] = async function (bytes) {
    if (!restored) throw restoreError || Module['lainError']('save.restoring');
    if (importing || pendingWrites) throw Module['lainError']('save.busy');
    const next = copyCard(bytes);
    importing = true;
    publishSaveState();
    try {
      if (!Module['lainGameLaunched']) {
        // Before launch there is no native card cache, so write directly to the restored FS.
        await Module['lainStoreCard'](next);
        return;
      }
      await new Promise((resolve, reject) => {
        importAck = { resolve, reject };
        let ptr = 0;
        try {
          ptr = Module['_malloc'](next.byteLength);
          if (!ptr) throw Module['lainError']('save.importMemory');
          HEAPU8.set(next, ptr);
          if (!Module['_lain_web_queue_import'](ptr, next.byteLength))
            throw Module['lainError']('save.importPending');
        } catch (error) {
          importAck = null;
          reject(error);
        } finally {
          if (ptr) Module['_free'](ptr);
        }
      });
    } finally {
      importing = false;
      publishSaveState();
    }
  };

  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', event => {
      if (pendingWrites || importing || (saveError && snapshot)) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
  }
  publishSaveState();
})();

Module['lainApplySettings'] = function (settings) {
  if (!settings || !Array.isArray(settings.keys) || settings.keys.length !== 16)
    return false;
  const keys = new Int32Array(settings.keys);
  const ptr = Module['_malloc'](keys.byteLength);
  if (!ptr) return false;
  try {
    HEAP32.set(keys, ptr >> 2);
    return !!Module['_lain_web_queue_settings'](
      settings.width,
      settings.height,
      settings.renderScale,
      settings.bilinear ? 1 : 0,
      settings.interpolate ? 1 : 0,
      settings.volume,
      ptr,
      keys.length
    );
  } finally {
    Module['_free'](ptr);
  }
};

Module['lainPrepare'] = function (settings) {
  if (!Module['_lain_web_prepare'](settings.width, settings.height))
    throw Module['lainError']('boot.sdlFailed');
};

Module['lainResumeAudio'] = function () {
  const context = Module['SDL2']?.audioContext;
  if (context && context.state === 'suspended') {
    try {
      const resumed = context.resume();
      resumed?.catch(error => console.warn('Audio resume failed; tap the game controls to retry', error));
    } catch (error) { console.warn('Audio resume failed', error); }
  }
};

Module['lainStart'] = function () {
  const saveInfo = Module['lainSaveInfo'];
  if (!saveInfo?.ready) throw saveInfo?.error || Module['lainError']('save.restoring');
  if (saveInfo.saving || saveInfo.importing) throw Module['lainError']('save.wait');
  if (Module['lainGameLaunched']) throw Module['lainError']('boot.alreadyRunning');
  const config = Module['lainConfig'];
  if (!config) throw Module['lainError']('boot.missingConfig');
  const encoded1 = new TextEncoder().encode(config.roms[0] + '\0');
  const encoded2 = new TextEncoder().encode(config.roms[1] + '\0');
  const url1 = Module['_malloc'](encoded1.length);
  const url2 = Module['_malloc'](encoded2.length);
  if (!url1 || !url2) {
    if (url1) Module['_free'](url1);
    if (url2) Module['_free'](url2);
    throw Module['lainError']('boot.configMemory');
  }
  HEAPU8.set(encoded1, url1);
  HEAPU8.set(encoded2, url2);
  const configured = Module['_lain_web_configure'](
    url1, config.sizes[0], url2, config.sizes[1]
  );
  Module['_free'](url1);
  Module['_free'](url2);
  if (!configured) throw Module['lainError']('boot.invalidConfig');
  const settings = Module['lainSettings'];
  if (!Module['lainApplySettings'](settings)) throw Module['lainError']('boot.invalidSettings');
  const canvasWrap = document.getElementById('canvas-wrap');
  if (canvasWrap) canvasWrap.classList.add('preparing');
  Module['lainPrepare'](settings);
  Module['lainGameLaunched'] = true;
  Module['callMain']([]);
};
