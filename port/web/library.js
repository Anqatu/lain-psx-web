addToLibrary({
  web_mcrd_store__sig: 'ippi',
  web_mcrd_store__proxy: 'sync',
  web_mcrd_store__async: 'auto',
  web_mcrd_store: function(path, data, size) {
    try {
      if (UTF8ToString(path) !== '/persist/memcard1.mcd' || size !== 128 * 1024)
        return 0;
      const bytes = new Uint8Array(HEAPU8.subarray(data, data + size));
      // Keep the outer function synchronous so the pthread receives the resolved numeric result.
      return Module['lainStoreCard'](bytes).then(() => 1, error => {
        console.error('Memory card persistence failed', error);
        return 0;
      });
    } catch (error) {
      console.error('Memory card save failed', error);
      return 0;
    }
  },

  web_mcrd_import_complete__sig: 'vi',
  web_mcrd_import_complete__proxy: 'sync',
  web_mcrd_import_complete: function(success) {
    Module['lainImportComplete'](success !== 0);
  },

  web_disc_fetch_range__sig: 'ipiipi',
  web_disc_fetch_range__proxy: 'sync',
  web_disc_fetch_range__async: 'auto',
  web_disc_fetch_range: function(url, start, end, out, capacity) {
    return (async () => {
      const target = UTF8ToString(url);
      if (!target) return -2;

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(target, {
          headers: { Range: `bytes=${start}-${end}` },
          cache: 'no-store',
          signal: controller.signal
        });
        if (response.status !== 206) return -response.status || -4;
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length > capacity) return -5;
        HEAPU8.set(bytes, out);
        return bytes.length;
      } catch (error) {
        console.error(`ROM Range fetch failed: ${target} bytes=${start}-${end}`, error);
        return error?.name === 'AbortError' ? -6 : -3;
      } finally {
        clearTimeout(timer);
      }
    })();
  }
});
