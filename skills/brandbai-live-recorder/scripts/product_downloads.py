"""Explicit, bounded downloads of observed public product assets, not page crawling."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import struct
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from product_evidence import public_url, validate_snapshot
from material_contract import validate_catalog
from product_identity import build_identity, validate_identity, identity_note
from export_naming import export_info, asset_name, create_export_folder

MAX_IMAGES = 200
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 180
MAX_OBSERVATIONS = 1000


class DownloadError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_remote(url):
    public_url(url, 'image')
    addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise DownloadError('non_public_destination')


def image_extension(data):
    # Match the download skill: trust bytes, never a URL suffix or HTTP 200.
    if len(data) >= 24 and data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16] == b'IHDR':
        width, height = struct.unpack('>II', data[16:24])
        if width > 0 and height > 0 and data[-8:] == b'IEND\xaeB`\x82': return '.png'
    if len(data) >= 4 and data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'): return '.jpg'
    if len(data) >= 20 and data[:4] == b'RIFF' and data[8:12] == b'WEBP' and struct.unpack('<I', data[4:8])[0] + 8 == len(data): return '.webp'
    raise DownloadError('unsupported_or_incomplete_image')


def fetch_image(url, *, stop, deadline, byte_limit=MAX_IMAGE_BYTES):
    opener = build_opener(NoRedirect())  # Retains normal host proxy settings.
    for hop in range(4):
        if stop.is_set() or time.monotonic() >= deadline: raise DownloadError('canceled_or_time_limit')
        validate_remote(url)
        request = Request(url, headers={'User-Agent': 'BrandBAI-LiveRecorder', 'Accept': 'image/png,image/jpeg,image/webp'})
        try:
            response = opener.open(request, timeout=min(10, max(.1, deadline - time.monotonic())))
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308} and exc.headers.get('Location') and hop < 3:
                next_url = urljoin(url, exc.headers['Location'])
                exc.close()
                public_url(next_url, 'image')  # Validate before requesting the next host.
                url = next_url
                continue
            exc.close()
            raise DownloadError('image_access_unavailable') from None
        with response:
            if response.status != 200: raise DownloadError('image_access_unavailable')
            length = response.headers.get('Content-Length')
            if length and int(length) > byte_limit: raise DownloadError('image_size_limit')
            if response.headers.get_content_type() not in {'image/png', 'image/jpeg', 'image/webp', 'application/octet-stream'}:
                raise DownloadError('response_not_image')
            data = bytearray()
            while True:
                if stop.is_set() or time.monotonic() >= deadline: raise DownloadError('canceled_or_time_limit')
                block = response.read(min(65536, byte_limit + 1 - len(data)))
                if not block: break
                data.extend(block)
                if len(data) > byte_limit: raise DownloadError('image_size_limit')
            if length and len(data) != int(length): raise DownloadError('incomplete_response')
            image_extension(data)
            return bytes(data)
    raise DownloadError('redirect_limit')


def observed_products(events):
    result = []
    for event in events:
        kind = event.get('event_type')
        if kind not in {'product_state', 'product_detail', 'product_list_item', 'product_material'}: continue
        p = event.get('payload') or {}
        if kind == 'product_state' and (not p.get('visible') or not p.get('card_observation_id')): continue
        try:
            data = validate_snapshot(p, detail=kind == 'product_detail', listing=kind == 'product_list_item', standalone=kind == 'product_material')
            if kind == 'product_material':
                data['product_identity'] = validate_identity(data['product_identity'], room_url=event['room_url']) if 'product_identity' in data else build_identity(
                    room_url=event['room_url'], observed_at=datetime.fromisoformat(event['observed_at']).timestamp()*1000,
                    product_url=data['product_url'], shop_name=data['shop_name'],
                    product_ref=('douyin:observation:' + event['material_observation_id'])
                        if not data['product_url'] and event.get('material_observation_id') else None)
        except ValueError:
            continue
        # No comments or raw input dictionaries enter the product package.
        keys = ('material_observation_id', 'event_type', 'room_url', 'observed_at') if kind == 'product_material' else ('collector_session_id', 'sequence', 'event_type', 'room_url', 'observed_at', 'recording_offset_seconds', 'within_recording_window')
        result.append({key: event.get(key) for key in keys} | {'payload': data})
    return result


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def build_product_package(root, events, *, stop, progress=lambda state: None, fetcher=fetch_image):
    root = Path(root).resolve(strict=True)
    catalog_event = events[0] if len(events) == 1 and events[0].get('event_type') == 'product_catalog_material' else None
    catalog = validate_catalog(catalog_event['payload']) if catalog_event else None
    standalone = bool(events) and all(e.get('event_type') == 'product_material' for e in events)
    parent = root / ('商品目录' if catalog else '商品资料' if standalone else '05_商品资料下载')
    if parent.is_symlink() or not parent.resolve().is_relative_to(root): raise DownloadError('unsafe_output_location')
    parent.mkdir(exist_ok=True)
    products = observed_products(events)
    if standalone and len(products) != len(events): raise DownloadError('invalid_material_snapshot')
    first = products[0]['payload'] if standalone and len(products) == 1 else {}
    names = {r.get('product_identity', {}).get('shop_name') for r in catalog['rows']} - {None, ''} if catalog else set()
    source = catalog_event if catalog else products[0] if products else {}
    info = export_info('catalog' if catalog else 'product', identity=first.get('product_identity'),
        title=first.get('product_title'), shop=first.get('shop_name') or (next(iter(names)) if len(names) == 1 else None),
        room_url=source.get('room_url'), observed_at=source.get('observed_at'),
        batch_id=source.get('material_observation_id'))
    if not standalone and not catalog:
        info = export_info('catalog', title='本场已观察商品', room_url=source.get('room_url'), observed_at=source.get('observed_at'))
        info['material_type']='recorded_product_observations'
        info['package_name']=info['package_name'].replace('商品目录', '本场商品资料')
    folder = create_export_folder(parent, info)
    image_dir = folder / '图片'
    image_dir.mkdir()
    write_json(folder / '导出信息.json', info)
    observation_limited = len(products) > MAX_OBSERVATIONS
    products = products[:MAX_OBSERVATIONS]
    references = [{'url':r['thumbnail'], 'kind':'list_image'} for r in catalog['rows'] if r['thumbnail']] if catalog else [img for event in products for img in event['payload'].get('images', [])]
    urls = list(dict.fromkeys(img['url'] for img in references))
    coverage = products[0]['payload'].get('image_coverage') if standalone and products else None
    skus = products[0]['payload'].get('sku_materials') if standalone and products else None
    parameters = products[0]['payload'].get('parameter_materials') if standalone and products else None
    state = dict(state='running', image_total=len(urls), image_saved=0, image_failed=0, image_skipped=0,
                 observation_count=len(catalog['rows']) if catalog else len(products), observation_limited=observation_limited, downloaded_bytes=0,
                 phase='downloading', material_kind='catalog' if catalog else 'product')
    if coverage: state['image_coverage'] = coverage
    if skus: state['sku_materials'] = skus
    if parameters: state['parameter_materials'] = parameters
    if catalog: state.update(catalog_complete=catalog['complete'], catalog_stop_reason=catalog['stop_reason'])
    progress(dict(state))
    media = []
    deadline = time.monotonic() + MAX_SECONDS
    started = datetime.now(timezone.utc).isoformat()
    for index, url in enumerate(urls):
        reason = None
        if stop.is_set(): reason = 'canceled'
        elif index >= (1000 if catalog else MAX_IMAGES): reason = 'image_count_limit'
        elif time.monotonic() >= deadline: reason = 'time_limit'
        elif state['downloaded_bytes'] >= MAX_TOTAL_BYTES: reason = 'total_size_limit'
        if reason:
            media.append(dict(url=url, status='skipped', reason=reason, file=None))
            state['image_skipped'] += 1
            progress(dict(state))
            write_json(folder / '下载清单.json', dict(state, started_at=started, assets=media))
            continue
        try:
            data = fetcher(url, stop=stop, deadline=deadline, byte_limit=min(MAX_IMAGE_BYTES, MAX_TOTAL_BYTES - state['downloaded_bytes']))
            if not data or len(data) > min(MAX_IMAGE_BYTES, MAX_TOTAL_BYTES - state['downloaded_bytes']): raise DownloadError('image_size_limit')
            suffix = image_extension(data)
            kinds = sorted({i['kind'] for i in references if i['url'] == url})
            subdir = '主图' if 'product_main' in kinds else '详情图' if 'product_detail' in kinds else '规格图' if 'product_sku' in kinds else '图片'
            name = asset_name(info, {'主图':'主图','详情图':'详情','规格图':'规格'}.get(subdir,'缩略图' if catalog else '图片'), index + 1, suffix)
            destination = folder / subdir
            destination.mkdir(exist_ok=True)
            target = destination / name
            with target.open('xb') as handle: handle.write(data)
            media.append(dict(url=url, kinds=kinds, status='downloaded', file=subdir + '/' + name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
            state['image_saved'] += 1
            state['downloaded_bytes'] += len(data)
        except Exception:
            # Network exceptions can include proxy credentials or signed URLs.
            media.append(dict(url=url, status='failed', reason='image_unavailable_or_invalid', file=None))
            state['image_failed'] += 1
        progress(dict(state))
        write_json(folder / '下载清单.json', dict(state, started_at=started, assets=media))
    incomplete = coverage and (not coverage['main_complete'] or not coverage['detail_complete'] or coverage['stop_reason']) or catalog and not catalog['complete']
    sku_incomplete = skus and skus['status'] != 'complete_all_visible_skus'
    parameter_incomplete = parameters and parameters['status'] != 'complete_visible_options'
    state['state'] = 'partial' if incomplete or sku_incomplete or parameter_incomplete or observation_limited or any(e['payload'].get('fields_limited') for e in products) or state['image_failed'] or state['image_skipped'] else 'complete_observed'
    if stop.is_set(): state['state'] = 'partial'
    state['image_total'] = len(urls)
    state['phase'] = 'packaging'
    progress(dict(state, state='running'))
    manifest = dict(state, export_info=info, started_at=started, completed_at=datetime.now(timezone.utc).isoformat(),
                    scope='observed_public_product_material_only', image_validation='signature_and_length_not_full_decode', assets=media)
    write_json(folder / '下载清单.json', manifest)
    if catalog:
        return finish_catalog(folder, catalog_event, catalog, media, state, info)
    # Public source statements are inputs for later product-value work, not verified claims.
    material = dict(schema='brandbai.product-material.v1', material_version=folder.name,
        collected_at=started, collection_mode='independent_product' if standalone else 'recorded_observations',
        observations=products, assets=media, export_info=info, completeness='observed_materials_only',
        evidence_status='page_statement_not_independently_verified',
        identity_policy='public_product_link_or_observation_only_never_title_merge',
        analysis_status='not_requested',
        coverage=dict(images='observed_links_only', sku='visible_options_not_sellable_combinations',
                      full_page='not_verified', product_video='not_collected', reviews='not_collected',
                      usage_and_claim_boundaries='source_images_or_parameters_only'),
        transaction_snapshots=[dict(observation_index=i, observed_at=e.get('observed_at'),
            price_texts=e['payload'].get('price_texts', [e['payload']['display_price']] if e['payload'].get('display_price') else []),
            offer_texts=e['payload'].get('offer_texts', []), sku_groups=e['payload'].get('sku_groups', [])) for i, e in enumerate(products)])
    identity = products[0]['payload'].get('product_identity') if standalone and len(products)==1 else None
    if identity:
        material['product_identity']=identity
        manifest['product_identity']=identity
        write_json(folder / '商品身份.json', identity)
        write_json(folder / '下载清单.json', manifest)
    if coverage:
        material['image_coverage'] = coverage
        material['coverage']['images'] = 'bounded_gallery_and_detail_capture'
        material['coverage']['full_page'] = 'image_sections_observed' if not incomplete else 'image_sections_incomplete'
    if skus:
        material['sku_materials']=skus
        material['coverage']['sku']=skus['status']
        material['sku_image_mapping']=[dict(selection=r['selection'],state=r['state'],reason=r['reason'],sku_id=r.get('sku_id'),sku_id_source=r.get('sku_id_source','not_observed'),
            product_id=identity['product_id'] if identity else None,product_ref=identity['product_ref'] if identity else None,
            price_texts=r['price_texts'],observed_at_epoch_ms=r['observed_at_epoch_ms'],
            images=[dict(url=u,file=next((a.get('file') for a in media if a['url']==u),None),
                         status=next((a['status'] for a in media if a['url']==u),'missing')) for u in r['image_urls']]) for r in skus['variants']]
    if parameters:
        material['parameter_materials']=parameters
        material['coverage']['parameter_options']=parameters['status']
    write_json(folder / '商品资料.json', material)
    def shown(value):
        return str(value or '暂未取得').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')
    by_url = {row['url']: row for row in media}
    lines = ['# 商品资料' if standalone else '# 本场商品资料下载', '', f"已保存 {state['image_saved']} 张图片；失败 {state['image_failed']} 张；未下载 {state['image_skipped']} 张。", '',
             ('已读取同一商品的公开图片与规格信息；实际取得范围、缺口及恢复状态见下方。未购买、领券或参与抽奖。' if skus else '已在用户选定的同一商品中读取主图与详情图；范围和缺失情况见下方。未切换规格、商品或遍历 SKU。' if coverage else '图片是页面实际提供且成功取得的文件，不保证原始分辨率或商品全量。没有自动翻页、补齐未打开的详情或遍历 SKU。') + '价格和规格按各自观察时间保存，不代表成交事实。', '']
    if identity: lines += [identity_note(identity)]
    if skus and not skus['variants']:
        lines += ['## 规格与图片对应', '', ('套餐参数已单独记录在下方；未取得可核验的购买规格、各档价格和专属图片，不用商品统一展示价或主图替代。' if parameters else '未识别到可遍历的规格选项，不能据此判断只有一个 SKU；没有逐项读取或切换规格。'), '']
    elif skus:
        lines += ['## 规格与图片对应', '', '规格读取：' + ('全部页面可选规格已确认。' if not sku_incomplete else '部分规格未确认，见各项说明。'), '',
            '原选择：'+' / '.join(shown(r['value']) for r in skus['initial_selection'])+'；恢复：'+('已确认' if skus['selection_restored'] else '未确认')+'。', '',
            '页面通用参数不自动视为每个规格的参数。没有公开 SKU ID 时，只按本次可见规格组合对应；不推算 ID。', '']
        for row in material['sku_image_mapping']:
            state_label={'observed':'已读取','unavailable':'不可选，未点击','failed':'未确认'}[row['state']]
            lines += ['### '+' / '.join(shown(s['value']) for s in row['selection']), '', state_label+'；价格：'+shown(' / '.join(row['price_texts']))+'。', '']
            if row['reason']: lines += ['该项未完全确认：'+shown(row['reason'])+'。', '']
            lines += [f"[对应图片]({i['file']})" if i['file'] else '对应图片未下载成功。' for i in row['images']]+['']
    if parameters:
        lines += ['## 套餐内容与参数', '',
            f"已读取 {sum(r['state']=='observed' for r in parameters['variants'])} / {parameters['option_count']} 个页面套餐选项。"+
            ('原选择已恢复。' if parameters['selection_restored'] else '原选择未确认恢复，请检查页面。'), '',
            '以下是产品参数区逐项展示的套餐组成，不等于已核实可购买 SKU；不推算价格、专属图片或规格 ID。', '']
        reason_labels={'selection_unconfirmed':'未确认选中','content_unconfirmed':'切换后的内容未确认','content_limit':'内容超过本次保存上限','option_disabled':'页面不可选，未点击'}
        for row in parameters['variants']:
            lines += ['### '+shown(row['label']), '']
            if row['reason']:lines += [reason_labels[row['reason']]+'。','']
            for component in row['components']:
                lines += [shown(component['name'])+' · '+shown(component['quantity_text']), '']
                lines += ['- '+shown(p['name'])+'：'+shown(p['value']) for p in component['parameters']]+['']
    if coverage:
        if coverage.get('main_video_observed'):
            lines += [f"另识别到 {coverage['main_video_observed']} 个商品视频位置；视频文件未下载，不计入主图缺失。轮播位置数不等于图片张数。", '']
        lines += [f"主图：已识别 {coverage['main_observed']} / {coverage['main_expected'] or '总数未知'}；详情图：已识别 {coverage['detail_observed']} 张。", '',
            '图片覆盖：' + ('已核对主图数量和详情末端；下载失败项另见清单。' if not incomplete else '尚未确认收齐；已保留取得的图片，请勿按整页完整资料使用。'), '',
            f"商品字段观察时间（毫秒）：{coverage['fields_observed_at_epoch_ms']}。图片采集发生在其后的同一商品观察窗口。", '']
    for i, event in enumerate(products, 1):
        p = event['payload']
        label = {'product_state':'直播弹窗', 'product_list_item':'商品列表（不是弹窗）', 'product_detail':'打开后的商品详情', 'product_material':'用户选择的当前商品详情（独立下载，不是弹窗事件）'}[event['event_type']]
        timing = '' if standalone else f"录制偏移：{shown(event.get('recording_offset_seconds'))} 秒；"
        lines += [f"## {i}. {shown(p.get('product_title'))}", '', f"来源：{label}；{timing}观察时间：{shown(event.get('observed_at'))}。", '',
                  f"展示价：{shown(' / '.join(p.get('price_texts', [])) or p.get('display_price'))}", '', f"店铺：{shown(p.get('shop_name'))}", '', f"权益：{shown(' / '.join(p.get('offer_texts', [])))}", '']
        for group in p.get('sku_groups', []):
            lines += [shown(group['name']) + '：' + ' / '.join(shown(o['value']) + ('（明确选中）' if o['selected'] else '') for o in group['options']), '']
        if p.get('parameter_texts'): lines += ['参数：' + ' / '.join(map(shown, p['parameter_texts'])), '']
        for img in p.get('images', []):
            saved = by_url[img['url']]
            lines += [f"[查看本地商品图]({saved['file']})" if saved.get('file') else '该图片未下载成功，详见下载清单。', '']
    lines += ['## 供后续使用', '', '本包可直接作为商品资料输入，无需先录屏。页面文字属于来源陈述，不等于已核实功效或商品价值结论。图片内的用法、卖点及限制尚未转成文字，应先阅读图片再分析。', '',
              '价格、优惠和当前规格保留在各自时点，不能回填为之前直播的权益。未提供稳定商品链接时仅保留本次观察，不按相似名称自动合并。', '',
              '复盘主播回复或商品弹窗配合时，还需要对应录屏、核验过的转写及互动时间记录；本包不自动生成这些内容，也不代表场控弹窗时间。', '',
              ('图片范围见上方覆盖状态。' if coverage else '覆盖范围：仅当前识别资料；未验证整页、全部主图／详情图。') + ('规格范围见逐项记录；' if skus else '未验证全部可成交 SKU；')+'未采集商品视频和评价。缺失资料不推断补齐。', '']
    (folder / '商品资料.md').write_text('\n'.join(lines), encoding='utf-8')
    (folder / '00_资料说明.md').write_text('请先阅读「商品资料.md」，按「商品身份.json」关联同商品资料；不要通过文件名或列表编号猜配。\n\n实际保存和缺失范围见「下载清单.json」。\n', encoding='utf-8')
    return finish_archive(folder, state)


def finish_catalog(folder, event, catalog, media, state, info):
    from catalog_numbers import number_hints
    catalog = json.loads(json.dumps(catalog))
    hints = number_hints(catalog['rows'], catalog['complete'] and not catalog['stop_reason'])
    for index, hint in hints.items():
        catalog['rows'][index]['number_inference'] = hint
    for row in catalog['rows']:
        identity=validate_identity(row['product_identity'],room_url=event['room_url']) if 'product_identity' in row else build_identity(
            room_url=event['room_url'], observed_at=row['observed_at_epoch_ms'], product_url=row['product_url'],
            catalog_position=row['list_position'], catalog_observed_at=row.get('number_verification', {}).get('confirmed_at_epoch_ms',row['observed_at_epoch_ms']) if row['list_position'] else None)
        row.update(product_identity=identity,product_id=identity['product_id'],product_ref=identity['product_ref'])
    by_url = {row['url']: row.get('file') for row in media}
    missing_numbers = sum(row['list_position'] is None for row in catalog['rows'])
    number_coverage = dict(observed=len(catalog['rows'])-missing_numbers, missing=missing_numbers,
                          inferred=len(hints), complete=missing_numbers==0,
                          reverified=sum('number_verification' in row for row in catalog['rows']))
    state['number_coverage'] = number_coverage
    if missing_numbers and state['state'] == 'complete_observed': state['state'] = 'partial'
    material = dict(schema='brandbai.live-product-catalog.v1', version=folder.name,
        room_url=event['room_url'], collected_at=event['observed_at'], **catalog,
        assets=media, export_info=info, analysis_status='not_requested', identity_policy='visible_number_is_not_product_id',
        event_policy='explicit_catalog_capture_not_controller_popup',
        number_coverage=number_coverage)
    write_json(folder / '商品编号目录.json', material)
    def shown(value):
        return str(value if value is not None else '暂未取得').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('|','\\|').replace('\n',' ').replace('[','\\[').replace(']','\\]')
    lines = ['# 商品编号目录', '', f"观察直播间：{event['room_url']}；快照时间：{event['observed_at']}。", '',
        f"记录 {len(catalog['rows'])} 条；" + ('已读取至列表末端。' if catalog['complete'] else '尚未收齐，可在原商品列表继续读取。'), '',
        f"其中 {missing_numbers} 件的链接编号未取得。" if missing_numbers else '本次各条目的页面编号均已取得。', '',
        '确认编号来自页面；推测编号单独标记，仅供核验，不能作为已确认编号或商品 ID。讲解商品可能被置顶，位置不等于编号。价格保留“券后／起”等原文。此目录不是场控弹窗记录，也不能回填为更早的商品编排。', '',
        '| 编号 | 商品名称 | 类型 | 展示价格 | 讲解标注 | 观察时间（毫秒） | 缩略图 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for row in catalog['rows']:
        file = by_url.get(row['thumbnail'])
        image = f'[查看]({file})' if file else '未取得'
        number = f"推测 {row['number_inference']['candidate']} 号·待核验" if 'number_inference' in row else shown(row['list_position'])
        if 'number_verification' in row: number += '（复核确认）'
        lines.append('| ' + ' | '.join([number, shown(row['product_title']), {'product':'商品','lottery':'福袋／抽奖（仅记录）','unavailable':'售罄／下架'}.get(row.get('entry_type'),'商品'), shown(row['display_price']),
            '讲解中' if row['explaining'] else '未显示', shown(row['observed_at_epoch_ms']), image]) + ' |')
    lines += ['', '公开商品链接和来源时间保留在同目录 JSON 中。未打开各商品详情，未收集全套主图、详情图、规格或买家信息。每次保存生成新版本，不覆盖历史编号对应关系。', '']
    (folder / '商品编号目录.md').write_text('\n'.join(lines), encoding='utf-8')
    manifest = json.loads((folder / '下载清单.json').read_text(encoding='utf-8'))
    manifest.update(number_coverage=number_coverage, state=state['state'])
    write_json(folder / '下载清单.json', manifest)
    (folder / '00_资料说明.md').write_text('请先阅读「商品编号目录.md」。编号只属于本次直播间快照；商品关联请使用 JSON 中的商品身份和观察时间，不按编号跨场合并。\n', encoding='utf-8')
    return finish_archive(folder, state)


def finish_archive(folder, state):
    archive = folder.with_name(folder.name + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED) as zf:
        for file in sorted(folder.rglob('*')):
            if file.is_file() and not file.name.endswith('.tmp'): zf.write(file, file.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as zf:
        if zf.testzip() is not None: raise DownloadError('archive_verification_failed')
    return dict(state, phase='finished', output_dir=str(folder), archive=str(archive))


class ProductDownloadJobs:
    """One bounded worker, independent from FFmpeg and live event ingestion."""
    def __init__(self, runner=build_product_package):
        self.runner, self.lock, self.jobs = runner, threading.RLock(), {}
        self.stop = threading.Event()
        self.thread = None

    def status(self, key):
        with self.lock: return dict(self.jobs.get(key, {'state':'idle'}))

    def start(self, key, root, events, on_finish=None):
        with self.lock:
            existing = self.jobs.get(key)
            if existing and existing['state'] in {'running', 'complete_observed'}: return dict(existing)
            if self.thread and self.thread.is_alive(): raise DownloadError('another_product_download_running')
            if self.stop.is_set(): raise DownloadError('service_stopping')
            self.jobs[key] = dict(state='running', image_saved=0, image_total=0)
            def update(value):
                with self.lock: self.jobs[key] = dict(value)
            def work():
                try: update(self.runner(root, events, stop=self.stop, progress=update))
                except Exception: update(dict(state='failed', reason='product_package_failed'))
                if on_finish:
                    try: on_finish(self.status(key))
                    except Exception: update(dict(self.status(key), delivery_error='package_registration_failed'))
            self.thread = threading.Thread(target=work, daemon=True, name='product-material-download')
            self.thread.start()
            return dict(self.jobs[key])


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Download product materials already observed in one live recording session.')
    parser.add_argument('--session-dir', required=True)
    parser.add_argument('--download-public-images', action='store_true', help='Explicitly download observed public images; otherwise only report the plan.')
    args = parser.parse_args()
    root = Path(args.session_dir).expanduser().resolve(strict=True)
    with (root / 'data/product_observations.jsonl').open(encoding='utf-8') as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    if not args.download_public_images:
        products = observed_products(events)
        print(json.dumps(dict(mode='dry_run', observations=len(products), images=len({i['url'] for e in products for i in e['payload'].get('images', [])}), max_images=MAX_IMAGES), ensure_ascii=False))
        return 0
    result = build_product_package(root, events, stop=threading.Event())
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['state'] == 'complete_observed' else 3


if __name__ == '__main__':
    raise SystemExit(main())
