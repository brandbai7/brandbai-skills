"""Portable display names; identity and timestamps remain authoritative in JSON."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit

VERSION = 'brandbai.export.v1'
KINDS = {'product': '商品资料', 'catalog': '商品目录', 'reviews': '商品评价', 'recording': '直播录制'}


def label(value, fallback, limit=20):
    value = unicodedata.normalize('NFC', str(value or ''))
    value = ''.join(c for c in value if unicodedata.category(c) not in {'Cc', 'Cf', 'Cs'})
    value = re.sub(r'[<>:"/\\|?*.\s]+', '_', value).strip(' _')
    value = value[:limit].rstrip(' _') or fallback
    if re.fullmatch(r'(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', value): value = '_' + value
    return value


def identity_label(identity, *, fallback):
    identity = identity or {}
    product_id = identity.get('product_id')
    if isinstance(product_id, str) and re.fullmatch(r'\d{5,30}', product_id): return 'P' + product_id
    # This is explicitly an observation display code, not a fabricated platform ID.
    ref = identity.get('product_ref') or fallback
    return '待核ID-' + hashlib.sha256(str(ref).encode()).hexdigest()[:12]


def display_label(value, *, limit=32):
    """Omit unknown/technical values; never manufacture a public identity."""
    raw = str(value or '').strip()
    if not raw or re.fullmatch(r'(?:店铺|商品|直播间|房间)?(?:待核|待确认|未知|未识别)',raw) or re.search(r'https?://|live\.douyin\.com', raw, re.I):
        return ''
    if re.fullmatch(r'(?:R|P)?\d+|待核ID-.+', raw):
        return ''
    return label(raw, '', limit)


def create_export_folder(parent, info):
    """Allocate a readable name atomically without replacing prior downloads."""
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    base = info['package_name']
    for index in range(1, 10001):
        name = base if index == 1 else f'{base} ({index})'
        path = parent / name
        if path.with_suffix('.zip').exists() and not path.exists():
            continue
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            # The same request after a helper restart must not become another
            # download. Different requests with the same display name may coexist.
            metadata = path / '导出信息.json'
            if not path.is_symlink() and metadata.is_file() and metadata.stat().st_size < 65536:
                try:
                    previous = json.loads(metadata.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    previous = {}
                if previous.get('export_id') == info['export_id']:
                    raise FileExistsError('export request already exists')
            continue
        info['package_name'] = name
        (path / '导出信息.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        return path
    raise FileExistsError('too many exports with the same display name')


def export_info(kind, *, observed_at=None, identity=None, title=None, shop=None, room_url=None, batch_id=None):
    if kind not in KINDS: raise ValueError('invalid export kind')
    batch = str(uuid.UUID(str(batch_id))) if batch_id else str(uuid.uuid4())
    when = datetime.fromisoformat(observed_at) if isinstance(observed_at, str) else observed_at
    when = when or datetime.now().astimezone()
    if when.tzinfo is None: when = when.astimezone()
    stamp = when.strftime('%Y%m%d-%H%M%S')
    room = urlsplit(room_url or '').path.strip('/')
    room_key = 'R' + room if re.fullmatch(r'\d{1,30}', room) else '房间待核'
    entity = identity_label(identity, fallback=batch) if kind in {'product', 'reviews'} else room_key
    parts = ['抖音', label(shop, '直播间待核' if kind == 'recording' else '店铺待核', 14)]
    if kind in {'product', 'reviews'}: parts.append(label(title, '商品待核', 22))
    parts += ([KINDS[kind], entity] if kind == 'catalog' else [entity, KINDS[kind]])
    parts += [stamp, 'B' + batch.replace('-', '')[:12]]
    if kind != 'recording':
        # Public commerce names are readable. IDs remain only in metadata;
        # recording's private media/ledger naming is deliberately unchanged.
        parts = ['抖音', display_label(shop) or '直播间']
        product_title = display_label(title, limit=32) if kind in {'product', 'reviews'} else ''
        if product_title:
            parts.append(product_title)
        parts += [KINDS[kind], when.strftime('%Y-%m-%d_%H-%M-%S')]
    return dict(schema=VERSION, export_id=batch, material_type=kind, package_name='_'.join(parts),
                observed_at=when.isoformat(), exported_at=datetime.now(timezone.utc).isoformat(),
                timezone_policy='source_observation_offset_preserved', product_identity=identity,
                product_title=title, shop_name=shop, source_room_url=room_url,
                entity_label=entity, naming_policy='display_only_never_join_by_filename')


def asset_name(info, kind, index, suffix, *, gallery_position=None):
    if kind not in {'主图', '详情', '规格', '缩略图', '图片', '视频', '直播录制'}:
        raise ValueError('invalid asset kind')
    if type(index) is not int or index < 1 or not re.fullmatch(r'\.[a-z0-9]{2,5}', suffix):
        raise ValueError('invalid asset filename')
    if gallery_position is not None and (type(gallery_position) is not int or gallery_position < 1):
        raise ValueError('invalid gallery position')
    order = f'轮播{gallery_position:03d}_{kind}' if gallery_position else f'{kind}{index:03d}'
    return f"{order}{suffix}"
