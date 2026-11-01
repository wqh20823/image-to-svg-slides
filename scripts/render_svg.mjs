import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const args = process.argv.slice(2);
if (args.includes('--help') || args.length < 2) {
  console.log('Usage: node render_svg.mjs INPUT.svg OUTPUT.png [--node-modules PATH] [--width 1920]');
  process.exit(args.includes('--help') ? 0 : 2);
}
const [input, output, ...options] = args;
let modulePath, width = 1920;
for (let i = 0; i < options.length; i += 2) {
  if (!options[i + 1]) throw new Error(`Missing value: ${options[i]}`);
  if (options[i] === '--node-modules') modulePath = options[i + 1];
  else if (options[i] === '--width') width = Number(options[i + 1]);
  else throw new Error(`Unknown option: ${options[i]}`);
}
if (!Number.isInteger(width) || width < 100 || width > 16000) throw new Error('Width must be an integer between 100 and 16000');
if (path.resolve(input) === path.resolve(output)) throw new Error('Input and output must differ');
const require = modulePath ? createRequire(path.join(path.resolve(modulePath), 'package.json')) : createRequire(import.meta.url);
let sharp;
try { sharp = require('sharp'); }
catch { throw new Error('sharp is unavailable; pass the existing runtime node_modules path. No dependency was installed.'); }
const source = await fs.readFile(input);
const metadata = await sharp(source).metadata();
if (metadata.format !== 'svg') throw new Error('Input must be an SVG');
await fs.mkdir(path.dirname(path.resolve(output)), { recursive: true });
const info = await sharp(source).resize({ width }).png().toFile(output);
console.log(JSON.stringify({ input: path.resolve(input), output: path.resolve(output),
  sourceWidth: metadata.width, sourceHeight: metadata.height, previewWidth: info.width, previewHeight: info.height }));
