// Original compositions, independent of the OpenMontage composition sources.
// Reuse installed npm packages when available; never import its JSX or skills.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {createRequire} = require('node:module');
const roots = [__dirname, path.resolve(__dirname, '../motion_composer')];
const root = roots.find(p => fs.existsSync(path.join(p, 'node_modules/@remotion/renderer/package.json')));
if (!root) throw new Error('Chưa cài Remotion. Chạy npm ci trong scene_composer.');
const fromRuntime = createRequire(path.join(root, 'package.json'));
const {bundle} = fromRuntime('@remotion/bundler');
const {openBrowser, selectComposition, renderMedia} = fromRuntime('@remotion/renderer');

async function main() {
  const [propsPath, output] = process.argv.slice(2);
  if (!propsPath || !output) throw new Error('Usage: node render.cjs props.json graphics.mov');
  const inputProps = JSON.parse(fs.readFileSync(propsPath, 'utf8'));
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'factory-graphics-'));
  let browser;
  try {
    const serveUrl = await bundle({
      entryPoint: path.join(__dirname, 'src/index.tsx'),
      outDir: temporary, rootDir: root,
      publicDir: path.join(__dirname, 'public'),
      webpackOverride: config => ({...config, resolve: {...config.resolve,
        modules: [path.join(root, 'node_modules'), ...(config.resolve.modules || [])]}}),
    });
    browser = await openBrowser('chrome', {logLevel: 'error'});
    const composition = await selectComposition({serveUrl, id: 'SceneGraphics', inputProps,
      puppeteerInstance: browser, logLevel: 'error'});
    await renderMedia({serveUrl, composition, inputProps, outputLocation: output,
      codec: 'prores', proResProfile: '4444', pixelFormat: 'yuva444p10le', imageFormat: 'png',
      muted: true, concurrency: 2, puppeteerInstance: browser, logLevel: 'error',
    });
  } finally {
    if (browser) await browser.close({silent: true});
    fs.rmSync(temporary, {recursive: true, force: true});
  }
}
main().catch(error => {console.error(error.message); process.exitCode = 1;});
