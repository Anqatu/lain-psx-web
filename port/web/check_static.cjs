const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Parse syntax without executing the application JavaScript or Wasm.
const root = path.resolve(__dirname, '../..');
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');
const translations = JSON.parse(read('port/web/translations.json'));
const englishKeys = Object.keys(translations.en).sort();
const referencedKeys = new Set();
for (const language of ['en', 'ja', 'ko']) {
  const entries = translations[language];
  if (JSON.stringify(Object.keys(entries).sort()) !== JSON.stringify(englishKeys))
    throw new Error(`${language}: translation keys do not match`);
  for (const key of englishKeys) {
    if (typeof entries[key] !== 'string' || !entries[key].trim()) throw new Error(`${language}/${key}: empty translation`);
    const placeholders = text => JSON.stringify((text.match(/\{\w+\}/g) || []).sort());
    if (placeholders(entries[key]) !== placeholders(translations.en[key]))
      throw new Error(`${language}/${key}: translation placeholders do not match`);
  }
}
for (const relative of ['port/web/shell.html', 'port/web/pre.js', 'port/src/web_main.c']) {
  for (const match of read(relative).matchAll(/['"]((?:boot|save|capture|settings|binding|key|link|error|legal|language)\.[A-Za-z]+)['"]/g))
    referencedKeys.add(match[1]);
}
for (const relative of ['port/web/pre.js', 'port/web/library.js', 'dist/web/index.js']) {
  new vm.Script(read(relative), { filename: relative });
}

for (const relative of ['port/web/shell.html', 'dist/web/index.html']) {
  const html = read(relative);
  const tags = html.match(/<[A-Za-z][^>]*>/g) || [];
  const attribute = (tag, name) => new RegExp('(?:\\s)' + name + '=(?:"([^"]*)"|\'([^\']*)\'|([^\\s>]+))').exec(tag)?.slice(1).find(value => value !== undefined);
  const ids = tags.map(tag => attribute(tag, 'id')).filter(Boolean);
  if (new Set(ids).size !== ids.length) throw new Error(`${relative}: duplicate IDs`);
  for (const tag of tags) {
    for (const name of ['data-i18n', 'data-i18n-aria']) {
      const key = attribute(tag, name);
      if (key) referencedKeys.add(key);
    }
    for (const name of ['for', 'aria-controls', 'aria-labelledby', 'aria-describedby']) {
      const value = attribute(tag, name);
      if (value && value.split(/\s+/).some(id => !ids.includes(id))) throw new Error(`${relative}: missing target ${name}=${value}`);
    }
  }
  let scriptText = '';
  for (const match of html.matchAll(/(<script\b[^>]*>)([\s\S]*?)<\/script>/g)) {
    const code = match[2];
    if (attribute(match[1], 'type') === 'application/json') {
      if (relative.startsWith('dist/') && JSON.stringify(JSON.parse(code)) !== JSON.stringify(translations))
        throw new Error('Embedded translations do not match the source');
      continue;
    }
    new vm.Script(code, { filename: relative });
    scriptText += code + '\n';
    for (const ref of code.matchAll(/\$\(['"]([^'"]+)['"]\)/g)) {
      if (!ids.includes(ref[1])) throw new Error(`${relative}: missing JS target ${ref[1]}`);
    }
  }
  if (relative.startsWith('dist/')) {
    const generated = read('dist/web/index.js');
    new vm.Script(scriptText + '\n' + generated, { filename: 'combined.js' });
    if (!html.includes('index.js?v=') || /__LAIN_(?:BUILD_ID|TRANSLATIONS)__/.test(html)) throw new Error('HTML preprocessing was not applied');
    if (!ids.includes('language-select') || !/<html\s+lang=(?:"en"|en)(?:\s|>)/.test(html)) throw new Error('Language selector or default English is missing');
    if (!/<template\b[^>]*id=(?:"runtime-template"|runtime-template)[^>]*>\s*<script\b[^>]*src=[^>]+>[\s\S]*?<\/script>\s*<\/template>/.test(html))
      throw new Error('Runtime script is not gated in the startup template');
    for (const requirement of ['isSecureContext', 'crossOriginIsolated', 'SharedArrayBuffer']) {
      if (!scriptText.includes(requirement)) throw new Error(`Missing pthread startup requirement: ${requirement}`);
    }
    if (!html.includes('failRuntimeStartup') || !html.includes('loadRuntime()'))
      throw new Error('Pre-runtime error checks are missing');
    for (const name of ['port/psx/src/psx/LIBGPU.C', 'port/psx/src/gpu/font.h']) {
      if (!html.includes(`./sources/${name}`)) throw new Error(`Covered-source link is missing: ${name}`);
    }
    for (const name of ['_lain_web_set_input_active', 'lainPrepare', 'lainResumeAudio', 'lainStoreCard', 'lainImportComplete', 'lainSaveStateChanged', 'lainExportSave']) {
      if (!generated.includes(name)) throw new Error(`Required API is missing: ${name}`);
    }
    for (const name of ['web_mcrd_store', 'web_disc_fetch_range']) {
      const bridge = generated.search(new RegExp(`(?:function\\s+_${name}\\s*\\(|_${name}\\s*=)`));
      if (bridge < 0 || !/ENVIRONMENT_IS_PTHREAD\)\s*return proxyToMainThread\(\d+,0,2,/.test(generated.slice(bridge, bridge + 240)))
        throw new Error(`Missing synchronous pthread proxy with asynchronous completion: ${name}`);
    }
    if (!/},\s*(?:3000|3e3)\)/.test(html)) throw new Error('Pointer Lock hint timer is missing');
  }
  console.log(`${relative}: JS syntax and ${ids.length} ID references OK`);
}
for (const key of referencedKeys) {
  if (!Object.hasOwn(translations.en, key)) throw new Error(`Referenced translation is missing: ${key}`);
}
const unused = englishKeys.filter(key => !referencedKeys.has(key));
if (unused.length) throw new Error(`Unused translations: ${unused.join(', ')}`);
console.log(`3 languages: ${englishKeys.length} keys each / all references and embedded data OK`);

const coveredSources = ['port/psx/src/gpu/font.h', 'port/psx/src/psx/LIBGPU.C'];
for (const relative of ['LICENSE', 'server.config.example.json', ...fs.readdirSync(path.join(root, 'thirdparty')).map(name => `thirdparty/${name}`)]) {
  if (read(relative) !== read(`dist/web/${relative}`)) throw new Error(`Distribution document mismatch: ${relative}`);
}
let distributionReadme = read('README.md').replaceAll('\r\n', '\n');
for (const name of coveredSources) distributionReadme = distributionReadme.replaceAll(`](${name})`, `](sources/${name})`);
if (distributionReadme !== read('dist/web/README.md').replaceAll('\r\n', '\n')) throw new Error('Distribution README source links do not match');
for (const relative of [...coveredSources, 'LICENSE', 'port/psx/LICENSE', 'thirdparty/MPL-2.0.txt', 'thirdparty/PSn00bSDK-NOTICE.txt', 'thirdparty/TOMB5-LICENSE.txt']) {
  if (!fs.readFileSync(path.join(root, relative)).equals(fs.readFileSync(path.join(root, 'dist/web/sources', relative))))
    throw new Error(`Corresponding source/notice mismatch: ${relative}`);
}
const fontArray = /unsigned char dbugfont\[\]\s*=\s*\{([^}]+)\}/.exec(read(coveredSources[0]));
const fontBytes = Buffer.from([...fontArray[1].matchAll(/0x([0-9a-fA-F]{2})/g)].map(match => parseInt(match[1], 16)));
if (!fontBytes.equals(fs.readFileSync(path.join(root, 'dist/web/sources/port/psx/src/gpu/dbugfont.tim'))))
  throw new Error('Editable debug-font data does not match the source array');
const readme = read('README.md');
if (/(?<![A-Za-z])[A-Za-z]:[\\/]|```cue|\bTRACK\s+01|\bINDEX\s+01/.test(readme))
  throw new Error('README contains an absolute drive path or CUE contents');
for (const relative of ['server.config.json', 'certs']) {
  if (fs.existsSync(path.join(root, 'dist/web', relative))) throw new Error(`Private configuration in distribution: ${relative}`);
}
if (read('port/web/serve.py') !== read('dist/web/serve.py')) throw new Error('Distributed server does not match the source');
if (read('port/web/run_local.py') !== read('run_web.py')) throw new Error('Generated launcher does not match the source');
console.log('Distribution: README, licenses, corresponding MPL sources, config example, and server match');
const wasm = fs.readFileSync(path.join(root, 'dist/web/index.wasm'));
if (!WebAssembly.validate(wasm)) throw new Error('Invalid Wasm structure');
let cursor = 8;
const uint = () => {
  let value = 0, shift = 0, byte;
  do {
    byte = wasm[cursor++];
    value += (byte & 127) * 2 ** shift;
    shift += 7;
  } while (byte & 128);
  return value;
};
let memoryCount = 0;
const limits = () => {
  const flags = uint();
  uint();
  if (flags & 1) uint();
  return flags;
};
const memory = () => {
  const flags = limits();
  if (!(flags & 2)) throw new Error('Expected shared Wasm memory for the pthread build');
  memoryCount++;
};
const skipName = () => { const length = uint(); cursor += length; };
while (cursor < wasm.length) {
  const section = wasm[cursor++];
  const length = uint();
  const end = cursor + length;
  if (section === 2) {
    const imports = uint();
    for (let index = 0; index < imports; index++) {
      skipName();
      skipName();
      const kind = wasm[cursor++];
      if (kind === 0) uint();
      else if (kind === 1) { cursor++; limits(); }
      else if (kind === 2) memory();
      else if (kind === 3) cursor += 2;
      else if (kind === 4) { uint(); uint(); }
      else throw new Error(`Unknown Wasm import kind: ${kind}`);
    }
  }
  if (section === 5) {
    const count = uint();
    for (let index = 0; index < count; index++) memory();
  }
  cursor = end;
}
if (memoryCount !== 1) throw new Error('Expected one shared Wasm memory');
console.log(`index.wasm: shared memory and structure OK (${wasm.length} bytes / no execution)`);
