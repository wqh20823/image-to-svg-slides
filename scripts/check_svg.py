"""Inspect authored slide SVGs; visual review remains necessary."""
import argparse
import base64
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

SVG = 'http://www.w3.org/2000/svg'
NUMBER = re.compile(r'^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?:px)?$')


def numeric(value):
    value = str(value).strip()
    parsed = float(value.removesuffix('px')) if NUMBER.fullmatch(value) else None
    return parsed if parsed is not None and math.isfinite(parsed) else None


def local(tag):
    return tag.rsplit('}', 1)[-1]


def check(path, args):
    errors, warnings = [], []
    result = {'file': str(path.resolve()), 'errors': errors, 'warnings': warnings, 'stats': {}}

    def issue(bucket, code, message, node=None):
        bucket.append({'code': code, 'message': message, 'id': node.get('id') if node is not None else None})

    try:
        raw = path.read_text(encoding='utf-8-sig')
        if re.search(r'<!DOCTYPE|<!ENTITY', raw, re.I):
            issue(errors, 'xml_declarations', 'DOCTYPE and entity declarations are not supported.')
            return result
        root = ET.fromstring(raw)
    except (OSError, UnicodeError, ET.ParseError) as exc:
        issue(errors, 'parse', str(exc))
        return result
    if root.tag != f'{{{SVG}}}svg':
        issue(errors, 'root', 'Expected an SVG root with the standard namespace.')
        return result
    nodes = list(root.iter())
    parents = {child: parent for parent in nodes for child in parent}
    ids = Counter(n.get('id') for n in nodes if n.get('id'))
    for key, count in ids.items():
        if count > 1:
            issue(errors, 'duplicate_id', f'{key}: {count} occurrences')
    try:
        view = [float(v) for v in re.split(r'[\s,]+', root.get('viewBox', '').strip())]
        if len(view) != 4 or not all(math.isfinite(v) for v in view) or view[2] <= 0 or view[3] <= 0:
            raise ValueError()
    except ValueError:
        issue(errors, 'viewbox', 'A positive, four-number viewBox is required.')
        view = None
    if view:
        w, h = numeric(root.get('width', '')), numeric(root.get('height', ''))
        if w and h and abs(w / h - view[2] / view[3]) > .001:
            issue(warnings, 'aspect_ratio', 'Root dimensions and viewBox have different aspect ratios.')

    for node in nodes:
        tag = local(node.tag)
        if tag in {'script', 'foreignObject'}:
            issue(errors, 'unsupported_element', f'{tag} is not allowed in a portable slide.', node)
        if tag in {'filter', 'mask', 'use', 'style', 'textPath'}:
            issue(warnings, 'compatibility', f'Review {tag} for independent editing and application compatibility.', node)
        if tag == 'style':
            css = node.text or ''
            urls = re.findall(r'url\(\s*[\"\x27]?([^\)\"\x27]+)[\"\x27]?\s*\)', css)
            if re.search(r'@import', css, re.I) or any(not u.strip().startswith('#') for u in urls):
                issue(errors, 'external_css', 'Styles must not load external resources.', node)
        for key, value in node.attrib.items():
            name = local(key)
            if name.lower().startswith('on'):
                issue(errors, 'event_handler', f'Event handler {name} is not allowed.', node)
            if name == 'href':
                if value.startswith('#') and value[1:] not in ids:
                    issue(errors, 'missing_reference', f'Unresolved {value}', node)
                elif not value.startswith(('#', 'data:')):
                    issue(errors, 'external_reference', 'Use embedded assets or local fragment references.', node)
            for target in re.findall(r'url\(\s*[\"\x27]?([^\)\"\x27]+)[\"\x27]?\s*\)', value):
                target = target.strip()
                if not target.startswith('#'):
                    issue(errors, 'external_url', 'External url() dependency.', node)
                elif target[1:] not in ids:
                    issue(errors, 'missing_reference', f'Unresolved {target}', node)
        if node.get('textLength') is not None or node.get('lengthAdjust') is not None:
            issue(warnings, 'text_stretch', 'Check whether text has been artificially stretched or compressed.', node)
        if node.get('transform') and any(p.get('transform') for p in ancestry(node, parents)):
            issue(warnings, 'nested_transform', 'Nested transforms need visual and editor review.', node)

    images = [n for n in nodes if local(n.tag) == 'image']
    texts = [n for n in nodes if local(n.tag) == 'text']
    if not texts and not args.allow_no_text:
        issue(errors, 'no_editable_text', 'No native text objects; a text-bearing slide must retain editable text.')
    for node in images:
        if args.require_no_raster:
            issue(errors, 'raster_not_allowed', 'This page was requested as pure vector.', node)
        href = node.get('href') or node.get('{http://www.w3.org/1999/xlink}href', '')
        match = re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)', href)
        if not match:
            issue(errors, 'image_format', 'Embed a PNG/JPEG image object; do not nest a whole SVG as an image.', node)
        else:
            try:
                payload = base64.b64decode(re.sub(r'\s', '', match[2]), validate=True)
                valid = payload.startswith(b'\x89PNG\r\n\x1a\n') if match[1] == 'png' else payload.startswith(b'\xff\xd8\xff')
                if not valid:
                    raise ValueError('File signature does not match MIME type')
            except ValueError as exc:
                issue(errors, 'image_encoding', str(exc), node)
        role = node.get('data-asset-role')
        if role not in {'photo', 'logo', 'complex-background'} or node.get('data-editability') != 'image-object':
            issue(errors, 'image_role', 'Identify the image role and its image-object editability.', node)
        else:
            issue(warnings, 'image_object', f'{role}: verify that text/diagrams have not been flattened into it.', node)
        iw, ih = numeric(node.get('width', '')), numeric(node.get('height', ''))
        if view and iw and ih and iw * ih >= .8 * view[2] * view[3]:
            bucket = warnings if role == 'complex-background' else errors
            issue(bucket, 'large_image', 'Image occupies most of the canvas; inspect for a flattened slide.', node)

    fonts, measured = {}, 0
    ImageFont = None
    if args.font:
        try:
            from PIL import ImageFont
        except ImportError:
            issue(errors, 'font_dependency', 'Pillow is needed for requested font measurements.')
        for filename in (args.font, args.bold_font):
            if filename and not Path(filename).is_file():
                issue(errors, 'font_file', f'Font file is missing: {filename}')
                ImageFont = None
    elif texts:
        issue(warnings, 'font_not_measured', 'Pass actual font files to measure declared text widths.')

    unbounded, complex_text, bold_fallback = 0, 0, False
    for text in texts:
        hidden = False
        for ancestor in [text, *ancestry(text, parents)]:
            opacity = numeric(ancestor.get('opacity', '1'))
            if opacity is not None and opacity <= .01:
                hidden = True
        visible_attrs = inherited(text, parents)
        if visible_attrs.get('display') == 'none' or visible_attrs.get('visibility') in {'hidden', 'collapse'}:
            hidden = True
        fill_opacity = numeric(visible_attrs.get('fill-opacity', '1'))
        if fill_opacity is not None and fill_opacity <= .01:
            hidden = True
        if visible_attrs.get('fill') in {'none', 'transparent'}:
            hidden = True
        if hidden:
            issue(errors, 'hidden_text', 'Invisible text cannot substitute for editable visible slide text.', text)
        spans = list(text)
        if any(local(n.tag) not in {'tspan', 'title', 'desc'} for n in spans):
            complex_text += 1
            continue
        spans = [n for n in spans if local(n.tag) == 'tspan']
        if spans and ((text.text or '').strip() or any(list(n) or n.get('x') is None or n.get('y') is None for n in spans)):
            complex_text += 1
            continue
        for line in spans or [text]:
            value = ''.join(line.itertext())
            if not value.strip():
                continue
            attrs = inherited(line, parents)
            limit = numeric(attrs.get('data-max-width', ''))
            if limit is None:
                unbounded += 1
                continue
            if limit <= 0:
                issue(errors, 'text_budget', 'Text width budget must be positive.', line)
                continue
            if not ImageFont:
                continue
            size = numeric(attrs.get('font-size', ''))
            if size is None or size <= 0:
                complex_text += 1
                continue
            if attrs.get('style') or attrs.get('textLength') or attrs.get('writing-mode') or attrs.get('dx') or attrs.get('dy'):
                complex_text += 1
                continue
            weight = attrs.get('font-weight', '400')
            is_bold = weight in {'bold', 'bolder'} or (weight.isdigit() and int(weight) >= 600)
            filename = args.bold_font if is_bold and args.bold_font else args.font
            index = args.bold_font_index if is_bold and args.bold_font else args.font_index
            bold_fallback |= is_bold and not args.bold_font
            key = (filename, index, round(size * 4))
            try:
                if key not in fonts:
                    fonts[key] = ImageFont.truetype(filename, key[2], index=index)
                length = fonts[key].getlength(value) / 4
                spacing = numeric(attrs.get('letter-spacing', '0'))
                if spacing is None:
                    complex_text += 1
                    continue
                length += max(0, len(value) - 1) * spacing
                measured += 1
                if length > limit + max(.5, size * .02):
                    issue(errors, 'text_overflow', f'{value[:45]!r}: width {length:.2f} exceeds {limit:.2f}.', line)
            except (OSError, ValueError) as exc:
                issue(errors, 'font_measurement', str(exc), line)
    if unbounded:
        issue(warnings, 'unbounded_text', f'{unbounded} lines lack data-max-width budgets.')
    if complex_text:
        issue(warnings, 'complex_text', f'{complex_text} text items require manual layout measurement.')
    if bold_fallback:
        issue(warnings, 'bold_font_missing', 'Bold text was measured with the regular font; provide --bold-font.')
    result['stats'] = {'elements': len(nodes), 'text_objects': len(texts), 'groups': sum(local(n.tag) == 'g' for n in nodes),
                       'image_objects': len(images), 'measured_lines': measured}
    return result


def ancestry(node, parents):
    while node in parents:
        node = parents[node]
        yield node


def inherited(node, parents):
    attrs = {}
    for item in [*reversed(list(ancestry(node, parents))), node]:
        attrs.update(item.attrib)
    return attrs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('svg', type=Path)
    parser.add_argument('--font')
    parser.add_argument('--bold-font')
    parser.add_argument('--font-index', type=int, default=0)
    parser.add_argument('--bold-font-index', type=int, default=0)
    parser.add_argument('--require-no-raster', action='store_true')
    parser.add_argument('--allow-no-text', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.report and args.svg.resolve() == args.report.resolve():
        parser.error('The report path must differ from the input SVG.')
    report = check(args.svg, args)
    data = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(data + '\n', encoding='utf-8')
    print(data)
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
