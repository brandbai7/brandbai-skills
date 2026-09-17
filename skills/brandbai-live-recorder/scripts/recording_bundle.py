"""Readable recording bundle: observed cards are not full products or interactions."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from export_naming import label
from product_evidence import public_url

POPUPS = '06_弹窗商品'
METRICS = '07_直播指标'
TIME_NOTE = '时间为任务开始后的本机墙钟偏移，包含准备时间，未与视频逐帧校准；不是平台发布或场控操作时间。'
GROUP_NOTE = '观察组序号不是直播间的几号链接。同一公开商品 ID 可归组；无 ID 时仅按同场同标题、店铺与缩略图整理同外观卡片，不证明商品或 SKU 相同，不能跨包自动关联。'


def read_json(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def recording_filename(root, *, created_at=None):
    """Use this frozen session's export, never the current mutable task/active tab."""
    root = Path(root)
    infos = [read_json(p, {}) for p in sorted((root / 'data').glob('export_*.json'))]
    infos = [v for v in infos if isinstance(v, dict) and v.get('material_type') == 'recording']
    names = {v.get('shop_name') for v in infos if isinstance(v.get('shop_name'), str) and v['shop_name'].strip()}
    name = next(iter(names)) if len(names) == 1 else None
    if name and (name in {'直播间待核', '店铺待核'} or '://' in name or re.fullmatch(r'\d+', name)):
        name = None
    report = read_json(root / '05_直播互动' / '完整性.json', {})
    stamp = report.get('task_started_at') or (datetime.fromtimestamp(created_at, timezone(timedelta(hours=8))).isoformat()
        if created_at is not None else next((v.get('observed_at') for v in infos if v.get('observed_at')), None))
    try:
        when = datetime.fromisoformat(stamp)
    except (ValueError, TypeError):
        when = datetime.fromtimestamp(created_at or time.time(), timezone(timedelta(hours=8)))
    parts = ['抖音'] + ([label(name, '', 32)] if name else [])
    return '_'.join(parts + ['直播记录', when.strftime('%Y-%m-%d_%H-%M-%S')]) + '.zip'


def write_bundle_guide(root, filename):
    from interaction_export import atomic_text
    root = Path(root)
    lines = ['# 直播记录', '', '本包：' + filename, '',
        '先看 [录屏说明与完整性](02_录屏说明与完整性.md)，视频位于 `03_直播录屏`。', '']
    if (root / POPUPS / '弹窗商品记录.json').is_file():
        lines += ['- [评论与互动](05_直播互动/直播互动记录.md)：评论、页面暂停及采集中断记录。',
            '- [弹窗商品概览](06_弹窗商品/本场弹窗商品概览.md) 与 [弹窗时间记录](06_弹窗商品/弹窗时间记录.md)：一场中已观察的多个商品卡片。',
            '- [缩略图保存说明](06_弹窗商品/缩略图保存说明.md)：每组卡片保留一张取得的缩略图，失败和未知单列。',
            '- [直播指标](07_直播指标/页面指标记录.md)：页面人数、点赞和榜单，独立于评论与商品。', '']
    else:
        lines += ['本场没有新版页面信息分区。未开启或未取得的页面信息不能补出；已有旧版原始记录仍保留。', '']
    lines += ['弹窗商品是直播中的可见展示记录，不是完整商品详情包。需要全部主图、详情、SKU 或评价时，请使用独立商品下载；不会自动打开所有商品。', '',
              TIME_NOTE, '', 'data 中保留房间、场次、事件和商品标识。不得按文件名、卡片观察组号或标题猜测商品关联。', '']
    atomic_text(root / '00_直播记录说明.md', '\n'.join(lines))
    data_dir = root / 'data'; data_dir.mkdir(exist_ok=True)
    atomic_text(data_dir / 'recording_bundle.json', json.dumps(dict(schema='brandbai.recording-bundle.v1',
        display_filename=filename, identity_sources=['tasks.jsonl', 'sessions.jsonl', 'export_*.json'],
        popup_source='visible_page_events.jsonl', policy='display_name_not_identity_key'), ensure_ascii=False, indent=2)+'\n')


def table_files(folder, stem, headers, rows, intro):
    from interaction_export import atomic_text, csv_cell, md_cell
    folder.mkdir(parents=True, exist_ok=True)
    table = io.StringIO(newline='')
    writer = csv.writer(table)
    writer.writerow(headers)
    writer.writerows([[csv_cell(v) for v in row] for row in rows])
    atomic_text(folder / (stem + '.csv'), table.getvalue(), 'utf-8-sig')
    lines = [f'# {stem}', '', intro, '', f'[打开表格]({stem}.csv)', '',
             '| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
    lines += ['| ' + ' | '.join(md_cell(v) for v in row) + ' |' for row in rows]
    atomic_text(folder / (stem + '.md'), '\n'.join(lines) + '\n')


def card_groups(events):
    """Deterministic session-local presentation groups. No guessed platform identities."""
    groups, by_key, timeline = [], {}, []
    last_by_collector = {}
    ordered = sorted(enumerate(events), key=lambda x: (x[1].get('observed_at_epoch_ms') or 0, x[0]))
    for index, event in ordered:
        collector = event.get('collector_session_id')
        if event.get('event_type') == 'collector_status':
            # A refreshed/interrupted collector does not establish which card was hidden.
            last_by_collector.pop(collector, None)
            continue
        if event.get('event_type') != 'product_state':
            continue
        p = event.get('payload') or {}
        group = None
        if p.get('visible') is True:
            product_id, url, thumbnail = None, None, None
            try:
                url = public_url(p.get('product_url'))
                if url: product_id = parse_qs(urlsplit(url).query)['id'][0]
            except (ValueError, KeyError):
                pass
            for image in p.get('images') or []:
                if image.get('kind') != 'card_image': continue
                try:
                    thumbnail = public_url(image.get('url'), 'image')
                except ValueError:
                    continue
                if thumbnail: break
            # Missing sufficient visible evidence must not merge different products by title alone.
            key = (event.get('room_url'), 'id', product_id) if product_id else (
                event.get('room_url'), 'appearance', p.get('product_title'), p.get('shop_name'), thumbnail
            ) if p.get('product_title') and thumbnail else ('observation', index)
            if key not in by_key:
                group = dict(observation_group=f'卡片{len(groups)+1:03d}', product_id=product_id,
                    product_url=url, product_title=p.get('product_title'), shop_name=p.get('shop_name'),
                    thumbnail_url=thumbnail, matching_method='public_product_id' if product_id else
                    'session_card_appearance' if thumbnail and p.get('product_title') else 'single_observation',
                    identity_status='public_product_link' if product_id else 'unconfirmed',
                    source_room_url=event.get('room_url'), first_observed_at=event.get('observed_at'),
                    last_observed_at=event.get('observed_at'), first_offset=event.get('recording_offset_seconds'),
                    last_offset=event.get('recording_offset_seconds'), visible_snapshot_count=0,
                    observed_prices=[], observed_titles=[], observed_offers=[])
                groups.append(group); by_key[key] = group
            group = by_key[key]
            group['last_observed_at'] = event.get('observed_at')
            group['last_offset'] = event.get('recording_offset_seconds')
            group['visible_snapshot_count'] += 1
            for field, values in [('observed_prices', [p.get('display_price')]),
                                  ('observed_titles', [p.get('product_title')]),
                                  ('observed_offers', p.get('offer_texts') or [])]:
                for value in values:
                    if value and value not in group[field]: group[field].append(value)
            last_by_collector[collector] = group
        elif p.get('visible') is False:
            group = last_by_collector.get(collector)
        timeline.append(dict(observation_group=group['observation_group'] if group else None,
            product_id=group['product_id'] if group else None, event_type='product_state',
            visible=p.get('visible'), change_kind=p.get('change_kind'),
            product_title=p.get('product_title'), display_price=p.get('display_price'),
            offer_texts=p.get('offer_texts') or [], card_observation_id=p.get('card_observation_id'),
            observed_at=event.get('observed_at'), recording_offset_seconds=event.get('recording_offset_seconds'),
            within_recording_window=event.get('within_recording_window'),
            visible_event_id=event.get('visible_event_id'), collector_session_id=collector))
    return groups, timeline


def write_recording_sections(root, events, task, *, observation_intervals=()):
    from interaction_export import atomic_text, CHANGES, public_cells
    root = Path(root)
    groups, timeline = card_groups(events)
    popup = root / POPUPS
    popup.mkdir(parents=True, exist_ok=True)
    payload = dict(schema='brandbai.live-popup-observations.v1', task_id=task.get('task_id'),
        task_started_at=task.get('started_at'), source='../data/visible_page_events.jsonl',
        scope='observed_popup_cards_only_not_full_product_material', grouping_boundary=GROUP_NOTE,
        time_alignment=TIME_NOTE, observation_group_count=len(groups),
        confirmed_product_id_count=len({g['product_id'] for g in groups if g['product_id']}),
        event_count=len(timeline), groups=groups, timeline=timeline,
        observation_intervals=list(observation_intervals))
    atomic_text(popup / '弹窗商品记录.json', json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    table_files(popup, '弹窗观察空档', ['开始时间','结束时间','恢复状态'],
        [[i['from'],i['to'] or '尚未观察到恢复',{'resumed':'已恢复观察','collector_stopped':'采集已结束','not_observed':'恢复未确认'}[i['end_status']]] for i in observation_intervals],
        '商品面板覆盖期间无法观察直播弹窗，不代表主播没有弹商品，也不证明评论或视频停止。没有记录到空档，不保证始终可观察。')
    overview_rows = [[g['observation_group'], g['product_title'] or '未知', g['product_id'] or '身份未确认',
                     g['shop_name'] or '未知', ' / '.join(g['observed_prices']) or '未知',
                     g['first_offset'], g['last_offset'], g['visible_snapshot_count'],
                     g['product_url'] or '未取得'] for g in groups]
    table_files(popup, '本场弹窗商品概览', ['观察组', '商品标题', '商品ID', '店铺', '观察到的展示价',
        '首次观察秒数', '最后可见秒数', '可见快照数', '公开商品链接'], overview_rows,
        f'本场记录 {len(groups)} 个卡片观察组、{len(timeline)} 条状态。快照数和观察组数都不等于实际弹窗操作次数。\n\n{GROUP_NOTE}\n\n{TIME_NOTE}\n\n[商品面板覆盖期间的观察空档](弹窗观察空档.md) 单独记录，不应当作没有弹窗。\n\n仅含已显示的卡片标题、展示价及缩略图，不含完整主图、详情、SKU 或评价。缩略图是否保存见「缩略图保存说明.md」。')
    timeline_rows = [[r['observed_at'], r['recording_offset_seconds'],
        {True:'窗口内', False:'窗口外'}.get(r['within_recording_window'], '未确认'),
        r['observation_group'] or '未知',
        '开始观察时已可见（不代表此刻弹出）' if r['change_kind']=='baseline_visible' else CHANGES.get(r['change_kind'], '状态未确认'),
        r['product_title'] or '', r['display_price'] or '', ' / '.join(r['offer_texts']),
        r['visible_event_id'], r['collector_session_id']] for r in timeline]
    table_files(popup, '弹窗时间记录', ['观察时间', '任务开始后秒数', '任务窗口', '观察组', '状态',
        '标题', '展示价', '权益原文', '事件编号', '采集会话'], timeline_rows,
        TIME_NOTE + '\n\n隐藏仅指暂时不可见，不代表下架；恢复可见不证明又执行了弹窗操作。列表与手动打开的详情不计入此表。')
    metric_events = [e for e in events if e.get('event_type')=='room_snapshot']
    table_files(root / METRICS, '页面指标记录', ['观察时间','任务开始后秒数','任务窗口','类型','昵称','内容','说明','事件编号','采集会话'],
        [public_cells(e) for e in metric_events], TIME_NOTE + '\n\n页面瞬时人数、点赞与榜单只是观察，不代表成交或因果关系。无浏览器房间轮询另见 data/room_metrics.jsonl；缺失值保持未知。')
    return payload


def save_popup_thumbnails(root, *, fetcher=None, seconds=30, max_images=200):
    """Bounded finalization only, outside the event lock; failures never discard the video."""
    from interaction_export import atomic_text
    from product_downloads import fetch_image, image_extension
    root = Path(root)
    popup = root / POPUPS
    data = read_json(popup / '弹窗商品记录.json', {})
    if not data: return
    images = popup / '商品卡缩略图'; images.mkdir(exist_ok=True)
    cache = read_json(popup / '缩略图下载清单.json', {})
    cached = {r.get('url'): r for r in cache.get('items', [])}
    items, by_url, attempts = [], {}, 0
    deadline = time.monotonic() + seconds
    stop = threading.Event()
    fetcher = fetcher or fetch_image
    for group in data['groups']:
        url = group.get('thumbnail_url')
        item = dict(observation_group=group['observation_group'], product_id=group['product_id'], url=url,
                    status='not_observed', file=None)
        if url:
            key = hashlib.sha256(url.encode()).hexdigest()[:24]
            old = cached.get(url, {})
            old_name = old.get('file') or ''
            # Cache paths are constrained to generated safe basenames, never trusted wholesale.
            valid = re.fullmatch(r'商品卡缩略图/卡片_[a-f0-9]{24}\.(png|jpg|webp)', old_name)
            previous = popup / old_name
            if valid and previous.is_file() and not previous.is_symlink():
                try:
                    image_extension(previous.read_bytes())
                    item.update(status='saved', file=old_name)
                except ValueError:
                    pass
            if item['status'] != 'saved':
                if url in by_url:
                    item.update(by_url[url])
                elif max_images == 0 and old.get('status') in {'download_unavailable', 'limit_reached'}:
                    item['status'] = old['status']
                elif attempts >= max_images or time.monotonic() >= deadline:
                    item['status'] = 'limit_reached'
                else:
                    attempts += 1
                    try:
                        binary = fetcher(public_url(url, 'image'), stop=stop,
                            deadline=min(deadline, time.monotonic()+5), byte_limit=2*1024*1024)
                        suffix = image_extension(binary)
                        name = f'商品卡缩略图/卡片_{key}{suffix}'
                        target = popup / name
                        temporary = target.with_suffix(suffix+'.tmp')
                        temporary.write_bytes(binary); temporary.replace(target)
                        item.update(status='saved', file=name)
                    except Exception:
                        # Do not expose HTTP internals or block the recording ZIP on an image error.
                        item['status'] = 'download_unavailable'
                by_url[url] = dict(status=item['status'], file=item['file'])
        items.append(item)
    saved = sum(r['status']=='saved' for r in items)
    result = dict(schema='brandbai.live-popup-thumbnails.v1', items=items,
        observation_groups=len(items), saved_groups=saved, scope='one_thumbnail_per_observed_group',
        status='saved_observed_thumbnails' if saved==len(items) else 'partial_thumbnails',
        limits=dict(max_requests=max_images, total_seconds=seconds, per_image_bytes=2*1024*1024),
        note='图片失败不影响已保存的视频及文字记录；没有取得的缩略图不会补猜。')
    atomic_text(popup / '缩略图下载清单.json', json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 缩略图保存说明', '', f'已保存 {saved} / {len(items)} 个观察组的缩略图。只保存卡片缩略图，不是完整商品资料。', '']
    for item in items:
        lines.append(f"- {item['observation_group']}：" + (f"[查看缩略图]({item['file']})" if item['file'] else
            {'not_observed':'未观察到可下载图片', 'limit_reached':'达到本次保存上限，文字记录保留',
             'download_unavailable':'图片暂不可下载，文字记录保留'}.get(item['status'],'未保存')))
    atomic_text(popup / '缩略图保存说明.md', '\n'.join(lines)+'\n')
    return result
