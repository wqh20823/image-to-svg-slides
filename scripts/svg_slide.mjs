const NS = 'http://www.w3.org/2000/svg';
const INK = 'http://www.inkscape.org/namespaces/inkscape';
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&apos;');
const join = children => Array.isArray(children) ? children.flat(Infinity).join('') : String(children ?? '');
const number = value => {
  if (!Number.isFinite(value)) throw new TypeError(`Expected a finite number: ${value}`);
  return Math.round(value * 10000) / 10000;
};
const positive = value => {
  number(value);
  if (value <= 0) throw new RangeError('Expected a positive dimension');
  return value;
};
const attributes = value => Object.entries(value).filter(([, v]) => v !== undefined && v !== null)
  .map(([k, v]) => {
    if (!/^[A-Za-z_][\w:.-]*$/.test(k)) throw new Error(`Invalid attribute: ${k}`);
    return ` ${k}="${escape(v)}"`;
  }).join('');

export function grid({ x, y, width, height, columns = 1, rows = 1, gapX = 24, gapY = 24 }) {
  for (const v of [x, y, width, height, gapX, gapY]) number(v);
  if (!Number.isInteger(columns) || !Number.isInteger(rows) || columns < 1 || rows < 1 || gapX < 0 || gapY < 0)
    throw new RangeError('Invalid grid');
  const w = positive((width - gapX * (columns - 1)) / columns);
  const h = positive((height - gapY * (rows - 1)) / rows);
  return Array.from({ length: rows * columns }, (_, i) => ({
    x: number(x + (i % columns) * (w + gapX)), y: number(y + Math.floor(i / columns) * (h + gapY)),
    width: number(w), height: number(h)
  }));
}

export class SvgSlide {
  constructor({ width = 1920, height = 1080, title = '', prefix = 'slide',
    fontFamily = 'Microsoft YaHei, Noto Sans CJK SC, Arial, sans-serif' } = {}) {
    this.width = positive(width); this.height = positive(height);
    if (!/^[A-Za-z_][\w.-]*$/.test(prefix)) throw new Error('Invalid ID prefix');
    this.prefix = prefix; this.title = title; this.fontFamily = fontFamily;
    this.counter = 0; this.ids = new Set(); this.defs = [];
  }
  id() { return `${this.prefix}-${++this.counter}`; }
  node(tag, attrs = {}, body = '') {
    const id = attrs.id ?? this.id();
    if (this.ids.has(id)) throw new Error(`Duplicate ID: ${id}`);
    this.ids.add(id);
    return `<${tag}${attributes({ ...attrs, id })}>${body}</${tag}>`;
  }
  group(label, children, { layer = false, ...attrs } = {}) {
    return this.node('g', { ...attrs, 'inkscape:label': label,
      'inkscape:groupmode': layer ? 'layer' : undefined }, `<title>${escape(label)}</title>${join(children)}`);
  }
  rect(x, y, width, height, attrs = {}) {
    return this.node('rect', { x: number(x), y: number(y), width: positive(width), height: positive(height),
      fill: 'none', ...attrs });
  }
  line(x1, y1, x2, y2, attrs = {}) {
    return this.node('line', { x1: number(x1), y1: number(y1), x2: number(x2), y2: number(y2),
      stroke: '#15396D', 'stroke-width': 2, 'stroke-linecap': 'round', ...attrs });
  }
  circle(cx, cy, r, attrs = {}) {
    return this.node('circle', { cx: number(cx), cy: number(cy), r: positive(r), fill: 'none', ...attrs });
  }
  ellipse(cx, cy, rx, ry, attrs = {}) {
    return this.node('ellipse', { cx: number(cx), cy: number(cy), rx: positive(rx), ry: positive(ry), fill: 'none', ...attrs });
  }
  path(d, attrs = {}) {
    return this.node('path', { d, fill: 'none', stroke: '#15396D', 'stroke-width': 2,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...attrs });
  }
  polygon(points, attrs = {}) {
    return this.node('polygon', { points: points.map(p => p.map(number).join(',')).join(' '), ...attrs });
  }
  text(x, y, content, { size = 30, weight = 400, lineHeight = size * 1.3, maxWidth,
    anchor = 'start', fill = '#15396D', fontFamily = this.fontFamily, ...attrs } = {}) {
    number(x); number(y); positive(size); positive(lineHeight);
    if (maxWidth !== undefined) positive(maxWidth);
    if (!['start', 'middle', 'end'].includes(anchor)) throw new Error('Invalid text anchor');
    const lines = Array.isArray(content) ? content : String(content).split('\n');
    const spans = lines.map((value, i) => this.node('tspan', { x: number(x), y: number(y + i * lineHeight),
      'data-max-width': maxWidth }, escape(value))).join('');
    return this.node('text', { x: number(x), y: number(y), 'font-family': fontFamily, 'font-size': size,
      'font-weight': weight, 'text-anchor': anchor, fill, 'data-max-width': maxWidth, ...attrs }, spans);
  }
  linearGradient(stops, { x1 = '0%', y1 = '0%', x2 = '100%', y2 = '0%' } = {}) {
    const id = this.id();
    const body = stops.map(([offset, color, opacity = 1]) => this.node('stop', {
      offset, 'stop-color': color, 'stop-opacity': opacity
    })).join('');
    this.defs.push(this.node('linearGradient', { id, x1, y1, x2, y2 }, body));
    return `url(#${id})`;
  }
  arrow(points, { color = '#0877D5', width = 3, headLength = 14, headWidth = 18, label = '连接箭头' } = {}) {
    if (points.length < 2) throw new Error('An arrow needs two or more points');
    points = points.map(p => p.map(number));
    const a = points.at(-2), b = points.at(-1);
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (!length) throw new Error('Arrow final segment must have positive length');
    const h = Math.min(positive(headLength), length * .8), hw = positive(headWidth) * h / headLength;
    const ux = (b[0] - a[0]) / length, uy = (b[1] - a[1]) / length;
    const base = [b[0] - ux * h, b[1] - uy * h];
    const shaft = this.node('polyline', { points: [...points.slice(0, -1), base].map(p => p.map(number).join(',')).join(' '),
      fill: 'none', stroke: color, 'stroke-width': positive(width), 'stroke-linejoin': 'round', 'stroke-linecap': 'round' });
    const head = this.polygon([b, [base[0] - uy * hw / 2, base[1] + ux * hw / 2],
      [base[0] + uy * hw / 2, base[1] - ux * hw / 2]], { fill: color });
    return this.group(label, [shaft, head]);
  }
  gear(cx, cy, radius, { teeth = 8, rootRatio = .78, holeRatio = .34,
    stroke = '#15396D', strokeWidth = 4, fill = 'none', label = '齿轮' } = {}) {
    number(cx); number(cy); positive(radius);
    if (!Number.isInteger(teeth) || teeth < 4 || teeth > 40 || rootRatio <= 0 || rootRatio >= 1 || holeRatio <= 0 || holeRatio >= rootRatio)
      throw new Error('Invalid gear geometry');
    const pts = [];
    for (let i = 0; i < teeth; i++) for (const [phase, ratio] of [[-.5, rootRatio], [-.31, rootRatio], [-.18, 1], [.18, 1], [.31, rootRatio], [.5, rootRatio]]) {
      const angle = -Math.PI / 2 + (i + phase) * Math.PI * 2 / teeth;
      pts.push([number(cx + Math.cos(angle) * radius * ratio), number(cy + Math.sin(angle) * radius * ratio)]);
    }
    return this.group(label, [this.polygon(pts, { fill, stroke, 'stroke-width': strokeWidth,
      'stroke-linejoin': 'round' }), this.circle(cx, cy, radius * holeRatio, { stroke, 'stroke-width': strokeWidth })]);
  }
  image(x, y, width, height, dataUri, { label, role = 'photo', ...attrs } = {}) {
    if (!label || !/^data:image\/(png|jpeg);base64,/.test(dataUri)) throw new Error('Images need a label and an embedded PNG/JPEG');
    if (!['photo', 'logo', 'complex-background'].includes(role)) throw new Error('Invalid image role');
    return this.group(label, this.node('image', { x: number(x), y: number(y), width: positive(width),
      height: positive(height), href: dataUri, preserveAspectRatio: 'xMidYMid meet',
      'data-asset-role': role, 'data-editability': 'image-object', ...attrs }));
  }
  render(children, { scale = 1 } = {}) {
    positive(scale);
    return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="${NS}" xmlns:inkscape="${INK}"` +
      ` width="${number(this.width * scale)}" height="${number(this.height * scale)}" viewBox="0 0 ${this.width} ${this.height}">` +
      `<title>${escape(this.title)}</title><defs>${this.defs.join('')}</defs>${join(children)}</svg>\n`;
  }
}
