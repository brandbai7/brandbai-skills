"""Bounded, independent review delivery. Only explicit page observations; no network."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from product_identity import build_identity, validate_identity, identity_note
from export_naming import export_info, create_export_folder

UUID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')
LEASE = ('documentToken', 'contextKey', 'generation', 'sourceWorkId', 'sourceSurfaceInstance',
         'productPanelInstanceId', 'reviewSurfaceInstanceId', 'filterKey')
RESUMABLE = {'time_limit', 'scroll_limit', 'run_budget', 'user_paused', 'no_growth', 'loading_stalled', 'page_hidden'}

def time_budget(limit):
    return min(600, max(180, limit * 3))

def bounded(value, limit=8000):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError('invalid review text')
    return re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[手机号已脱敏]', value)

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def atomic(path, data):
    temporary = path.with_name(path.name + '.pending')
    with temporary.open('wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)

def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')

def validate_row(row):
    fields = {'review_id', 'reviewer', 'date_text', 'purchased_sku', 'content', 'content_status',
              'image_count', 'helpful_count', 'followups', 'followup_status', 'merchant_reply'}
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError('invalid review fields')
    result = {k: bounded(row[k]) for k in ('date_text', 'purchased_sku', 'content', 'merchant_reply')}
    if not re.fullmatch(r'[a-f0-9]{64}', row['review_id']) or not re.fullmatch(r'买家_[a-f0-9]{12}', row['reviewer']):
        raise ValueError('pseudonymous review identity required')
    for field in ('image_count', 'helpful_count'):
        value = row[field]
        if value is not None and (type(value) is not int or not 0 <= value <= 100000000):
            raise ValueError('invalid review count')
    if row['content_status'] not in ('text_observed', 'media_only') or row['followup_status'] not in ('observed', 'unparsed', 'not_observed'):
        raise ValueError('invalid review evidence state')
    if not isinstance(row['followups'], list) or len(row['followups']) > 20:
        raise ValueError('invalid followups')
    followups = []
    for item in row['followups']:
        if not isinstance(item, dict) or set(item) != {'content', 'date_text', 'image_count'} or type(item['image_count']) is not int or not 0 <= item['image_count'] <= 100:
            raise ValueError('invalid followup')
        followups.append(dict(content=bounded(item['content']), date_text=bounded(item['date_text'], 200), image_count=item['image_count']))
    if not result['content'] and not row['image_count']:
        raise ValueError('review has no observed payload')
    return dict(row, **result, followups=followups)

class ProductReviewJobs:
    """Checkpoints precede count acknowledgement; source lease never enters delivery."""
    def __init__(self, now=time.time, auto_expire=False, on_finish=None):
        self.jobs = {}; self.lock = threading.RLock(); self.now = now
        self.on_finish = on_finish
        self.stop_event = threading.Event()
        if auto_expire:
            threading.Thread(target=self._watch, name='product-review-checkpoints', daemon=True).start()

    def _watch(self):
        while not self.stop_event.wait(10):
            with self.lock:
                for ident in list(self.jobs):
                    try: self.status(ident)
                    except OSError: pass  # A later tick retries; no false saved acknowledgement.

    def validate_start(self, body):
        required = {'request_id', 'room_url', 'observed_at_epoch_ms', 'lease', 'product', 'filter_label', 'declared_count_text', 'limit'}
        if not isinstance(body, dict) or not required <= set(body) or set(body)-required-{'product_identity','resume_from'} or not UUID.fullmatch(str(body.get('request_id', ''))):
            raise ValueError('invalid review request')
        if 'resume_from' in body and not UUID.fullmatch(str(body['resume_from'])):
            raise ValueError('invalid review continuation')
        ident = body['request_id']
        if not re.fullmatch(r'https://live\.douyin\.com/\d{1,30}', str(body['room_url'])):
            raise ValueError('invalid review room')
        at = body['observed_at_epoch_ms']
        if type(at) not in (float, int) or not abs(self.now()*1000-at) <= 120000:
            raise ValueError('stale review observation')
        if type(body['limit']) is not int or not 1 <= body['limit'] <= 500:
            raise ValueError('invalid review limit')
        lease = body['lease']
        if not isinstance(lease, dict) or set(lease) != set(LEASE) or any(not bounded(lease[k], 500) for k in LEASE):
            raise ValueError('invalid review lease')
        if lease['contextKey'] != body['room_url'] or lease['sourceWorkId'] != body['room_url']:
            raise ValueError('review room lease mismatch')
        product = body['product']
        if not isinstance(product, dict) or set(product) != {'title', 'shop_name', 'product_id'}:
            raise ValueError('invalid product header')
        product = {k: bounded(v, 300) for k,v in product.items()}
        if not product['title'] or product['product_id'] and not re.fullmatch(r'\d{5,30}', product['product_id']):
            raise ValueError('unconfirmed product')
        identity = validate_identity(body['product_identity'], room_url=body['room_url'], shop_name=product['shop_name']) if 'product_identity' in body else build_identity(
            room_url=body['room_url'], observed_at=at, product_id=product['product_id'], shop_name=product['shop_name'],
            product_ref=None if product['product_id'] else 'douyin:observation:' + ident)
        if identity['product_id'] != (product['product_id'] or None): raise ValueError('review product identity mismatch')
        filter_label = bounded(body['filter_label'], 200)
        declared = bounded(body['declared_count_text'], 80)
        return ident, at, lease, product, identity, filter_label, declared

    def start(self, body, output_root):
        ident, at, lease, product, identity, filter_label, declared = self.validate_start(body)
        with self.lock:
            if ident in self.jobs:
                if self.jobs[ident]['fingerprint'] != digest(body): raise ValueError('review request changed')
                return self.status(ident)
            if len(self.jobs) >= 100: raise ValueError('review job capacity reached')
            parent = self.jobs.get(body.get('resume_from'))
            if 'resume_from' in body:
                if not parent or parent['state'] != 'saved' or parent['doneReason'] not in RESUMABLE:
                    raise ValueError('review continuation unavailable')
                if (parent['lease'] != lease or parent['room_url'] != body['room_url'] or parent['product'] != product
                        or parent['product_identity'] != identity or parent['filter_label'] != filter_label
                        or parent['limit'] != body['limit'] or parent['reviewCount'] >= body['limit']):
                    raise ValueError('review continuation source changed')
                # One child per checkpoint prevents accidental branching/repeated clicks.
                if parent.get('continued_by'): raise ValueError('review checkpoint already continued')
            inherited = dict(parent['rows']) if parent else {}
            namespace = parent['anonymization_id'] if parent else ident
            info = export_info('reviews', observed_at=datetime.fromtimestamp(at/1000).astimezone(), identity=identity,
                title=product['title'], shop=product['shop_name'], room_url=body['room_url'], batch_id=ident)
            folder = Path(output_root).resolve() / '商品评价'
            if folder.is_symlink() or not folder.resolve().is_relative_to(Path(output_root).resolve()):
                raise ValueError('unsafe review output location')
            root = create_export_folder(folder, info)
            job = dict(id=ident, runId=ident, room_url=body['room_url'], product=product, product_identity=identity, filter_label=filter_label,
                       declared_count_text=declared, limit=body['limit'], state='collecting', reviewCount=len(inherited),
                       completeness='partial_current_loaded', doneReason='in_progress', phase='reading', waiting_since=None, root=root, lease=dict(lease),
                       fingerprint=digest(body), rows=inherited, last_seen=self.now(), started_at=self.now(), ended_at=None,
                       sequences={}, export_info=info, anonymization_id=namespace, resume_from=body.get('resume_from'),
                       baseline_count=len(inherited), time_limit_seconds=time_budget(body['limit']))
            self.jobs[ident] = job
            try: self._checkpoint(job)
            except OSError:
                self.jobs.pop(ident, None)
                raise
            if parent: parent['continued_by'] = ident
            return self.status(ident)

    def accept(self, ident, body):
        with self.lock:
            job = self.jobs.get(ident)
            if job is None: raise ValueError('review job not found')
            required = {'lease', 'sequence', 'action', 'rows', 'done_reason', 'exhausted', 'empty_confirmed'}
            if not isinstance(body, dict) or not required <= set(body) or set(body)-required-{'phase'}:
                raise ValueError('invalid review batch')
            if 'phase' in body and (body['action'] != 'progress' or body['phase'] not in ('reading', 'waiting_page')):
                raise ValueError('invalid review phase')
            if body['lease'] != job['lease']: raise ValueError('review lease changed')
            if job['state'] == 'collecting' and job.get('phase') == 'waiting_page': self.status(ident)
            seq = body['sequence']
            if type(seq) is not int or seq < 1 or seq > 2000: raise ValueError('invalid review sequence')
            fingerprint = digest(body)
            if seq in job['sequences']:
                if job['sequences'][seq] != fingerprint: raise ValueError('review batch changed')
                return self.status(ident)
            if job['state'] != 'collecting':
                if (body['action'] == 'progress' and body['rows'] == [] and body['done_reason'] == ''
                        and body['exhausted'] is False and body['empty_confirmed'] is False):
                    return self.status(ident)  # A sleeping page may wake after the watchdog saved its data.
                raise ValueError('review job has ended')
            if seq != len(job['sequences'])+1: raise ValueError('review sequence gap')
            action = body['action']
            if action not in ('progress', 'batch', 'finish') or not isinstance(body['rows'], list) or len(body['rows']) > 100:
                raise ValueError('invalid review action')
            if action != 'batch' and body['rows']: raise ValueError('unexpected review rows')
            if action == 'progress':
                if body['done_reason'] or body['exhausted'] is not False or body['empty_confirmed'] is not False:
                    raise ValueError('invalid review heartbeat')
                # Heartbeats have no new material. Never rewrite all CSV/JSON files here.
                phase = body.get('phase', 'reading')
                if phase == 'waiting_page' and job['phase'] != phase: job['waiting_since'] = self.now()
                if phase != 'waiting_page': job['waiting_since'] = None
                job['phase'] = phase
                job['last_seen'] = self.now(); job['sequences'][seq] = fingerprint
                return self.status(ident)
            rows = [validate_row(row) for row in body['rows']]
            staged = dict(job['rows'])
            for row in rows: staged[row['review_id']] = dict(row,captured_at_epoch_ms=staged.get(row['review_id'],{}).get('captured_at_epoch_ms',int(self.now()*1000)))
            if len(staged) > job['limit']: raise ValueError('review limit exceeded')
            reason = bounded(body['done_reason'], 80)
            if not re.fullmatch(r'[a-z_]*', reason) or type(body['exhausted']) is not bool or type(body['empty_confirmed']) is not bool:
                raise ValueError('invalid review outcome')
            if reason == 'target_reached' and (action != 'finish' or len(staged) != job['limit']):
                raise ValueError('review target not reached')
            before = {key:job[key] for key in ('rows','reviewCount','last_seen','state','doneReason','completeness','ended_at')}
            job['rows'] = staged; job['reviewCount'] = len(staged); job['last_seen'] = self.now()
            if action == 'finish':
                complete = reason == 'source_exhausted' and body['exhausted'] and (bool(staged) or body['empty_confirmed'])
                # A list begun after scrolling cannot prove the whole filter was read.
                job.update(state='saved', doneReason=reason or 'interrupted', ended_at=self.now(),
                           completeness='complete_visible_panel_exhausted' if complete else 'partial_'+(reason or 'interrupted'))
            try:
                self._checkpoint(job, package=action == 'finish')
            except OSError:
                job.update(before)
                raise
            job['sequences'][seq] = fingerprint
            return self.status(ident)

    def stop(self, ident, body):
        """Authenticated, idempotent finalization of this job's durable batches only."""
        with self.lock:
            job = self.jobs.get(ident)
            if job is None: raise ValueError('review job not found')
            if not isinstance(body, dict) or set(body) != {'room_url'} or body['room_url'] != job['room_url']:
                raise ValueError('review stop source mismatch')
            if job['state'] == 'saved': return self.status(ident)
            before = (job['state'], job['doneReason'], job['completeness'], job['ended_at'])
            job.update(state='saved', doneReason='user_paused', completeness='partial_user_paused', ended_at=self.now())
            try: self._checkpoint(job, package=True)
            except OSError:
                job['state'],job['doneReason'],job['completeness'],job['ended_at'] = before
                raise
            return self.status(ident)

    def status(self, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if job is None: raise ValueError('review job not found')
            waiting = job.get('phase') == 'waiting_page'
            wait_expired = waiting and (self.now() - job['waiting_since'] >= 300 or self.now() - job['started_at'] >= job['time_limit_seconds'])
            if job['state'] == 'collecting' and (wait_expired or not waiting and self.now()-job['last_seen'] > 45):
                previous = (job['state'], job['doneReason'], job['completeness'], job['ended_at'])
                reason = 'time_limit' if waiting and self.now()-job['started_at'] >= job['time_limit_seconds'] else 'page_hidden' if waiting else 'page_disconnected'
                job.update(state='saved', doneReason=reason, completeness='partial_'+reason, ended_at=self.now())
                try: self._checkpoint(job, package=True)
                except OSError:
                    job['state'],job['doneReason'],job['completeness'],job['ended_at']=previous
                    raise
            return {k: job[k] for k in ('id', 'runId', 'room_url', 'product', 'product_identity', 'filter_label', 'declared_count_text',
                                      'limit', 'state', 'reviewCount', 'completeness', 'doneReason', 'phase')} | {
                'elapsed_seconds': round((job['ended_at'] or self.now())-job['started_at']), 'output_dir': str(job['root']),
                'time_limit_seconds': job['time_limit_seconds'], 'baseline_count': job['baseline_count'],
                'anonymization_id': job['anonymization_id'], 'resume_from': job['resume_from'],
                'can_continue': job['state']=='saved' and job['doneReason'] in RESUMABLE and not job.get('continued_by') and job['reviewCount']<job['limit'],
                'zip_path': str(job['root'].with_name(job['root'].name + '.zip')) if job['state'] == 'saved' else None}

    def _checkpoint(self, job, package=False):
        root = job['root']; rows = list(job['rows'].values())
        identity=job['product_identity']
        manifest = {k: job[k] for k in ('room_url', 'product', 'product_identity', 'filter_label', 'declared_count_text', 'limit', 'reviewCount', 'completeness', 'doneReason')}
        manifest.update(schema_version='1.1', export_info=job['export_info'], observed_at=datetime.fromtimestamp(job['started_at']).astimezone().isoformat(),
                        scope='current_product_current_filter_observed_reviews', media_downloaded=False,
                        review_identity='continuation_series_pseudonymous_observation_key_not_global_identity',
                        identity_status='platform_product_id' if job['product']['product_id'] else 'current_panel_only')
        manifest.update(target_count=job['limit'], time_limit_seconds=job['time_limit_seconds'],
                        elapsed_seconds=round((job['ended_at'] or self.now())-job['started_at']),
                        continuation={'source_export_id':job['resume_from'], 'series_id':job['anonymization_id'],
                                      'inherited_count':job['baseline_count'], 'new_count':len(rows)-job['baseline_count'],
                                      'package_scope':'cumulative_snapshot'})
        exported=[dict(r, product_identity=identity, product_id=identity['product_id'], product_ref=identity['product_ref'],
            platform='douyin',sku_id=None,sku_id_source='not_observed',
            sku_relation='historical_purchased_text_not_current_selection') for r in rows]
        atomic(root/'商品评价.jsonl', ''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in exported).encode())
        atomic(root/'商品身份.json', json_bytes(identity))
        atomic(root/'导出信息.json', json_bytes(job['export_info']))
        output = io.StringIO(newline=''); writer = csv.writer(output)
        identity_columns=['platform','product_id','product_ref','product_url','shop_id','shop_name','source_room_id','source_room_url','catalog_position','catalog_observed_at_epoch_ms','identity_status']
        writer.writerow(['评价标识','买家','评价时间原文','所购规格原文','评价正文','有用数','附图数量','追评','商家回复']+identity_columns+['sku_id','captured_at_epoch_ms'])
        def cell(value):
            value = '' if value is None else str(value)
            return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        for row in rows:
            writer.writerow([cell(row[k]) for k in ('review_id','reviewer','date_text','purchased_sku','content','helpful_count','image_count')]
                            +[cell('\n'.join(f['date_text']+' '+f['content'] for f in row['followups'])), cell(row['merchant_reply'])]
                            +[cell(identity[k]) for k in identity_columns]+['',row['captured_at_epoch_ms']])
        atomic(root/'商品评价.csv', output.getvalue().encode('utf-8-sig'))
        atomic(root/'完整性.json', json_bytes(manifest))
        complete = job['completeness'] == 'complete_visible_panel_exhausted'
        note = f"# 商品评价\n\n{job['product']['title']}\n\n已保存 {len(rows)} 条；本次上限 {job['limit']} 条。\n\n筛选：{job['filter_label']}。平台展示评价总数：{job['declared_count_text'] or '未取得'}（不是本次下载量）。\n\n{'已读到当前评价列表末尾；不保证覆盖平台全部历史评价。' if complete else '本次仅保存已取得的评价，不是全部历史评价。'}\n\n评价中的所购规格按页面原文保存，可能是历史款，不代表当前所选规格。买家采用本包化名；图片仅计数，未下载附图或视频。\n\n请把 CSV 或 JSONL 交给后续分析。未分析、未代替用户进行筛选、点赞、回复或购买。\n"
        reason_labels={'time_limit':'达到本轮时间上限，未必达到目标条数','scroll_limit':'达到本轮滚动上限',
                       'target_reached':'已达到目标条数（不是平台全量）','run_budget':'旧版数量或时间上限',
                       'user_paused':'使用者停止并保存','no_growth':'页面未继续加载','loading_stalled':'页面加载停滞',
                       'page_hidden':'商品评价页长时间未返回，已保存读到的评价','page_disconnected':'商品评价页连接中断'}
        note += f"\n结束原因：{reason_labels.get(job['doneReason'],job['doneReason'])}。本轮最多 {job['time_limit_seconds']} 秒，实际运行 {manifest['elapsed_seconds']} 秒。\n"
        if job['resume_from']:
            note += f"\n这是继续采集后的累计版本，包含之前 {job['baseline_count']} 条和本轮新增 {len(rows)-job['baseline_count']} 条；不要把新旧包直接相加。旧包未覆盖。同一续采系列保留买家化名及评价标识，不用于其他页面或系列的买家身份关联。\n"
        atomic(root/'阅读说明.md', (note+'\n'+identity_note(identity)).encode())
        atomic(root/'00_资料说明.md', (note+'\n'+identity_note(identity)).encode())
        if package:
            target = root.with_name(root.name + '.zip'); temporary = target.with_suffix('.zip.pending')
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name in ('商品评价.jsonl','商品评价.csv','完整性.json','阅读说明.md','商品身份.json','导出信息.json','00_资料说明.md'):
                    archive.write(root/name, name)
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None: raise OSError('review archive verification failed')
            temporary.replace(target)
            if self.on_finish:
                self.on_finish(job['id'], {'zip_path': str(target), 'output_dir': str(root),
                                           'completeness': job['completeness']})

    def shutdown(self):
        self.stop_event.set()
        with self.lock:
            for job in self.jobs.values():
                if job['state'] == 'collecting':
                    job.update(state='saved', doneReason='service_stopped', completeness='partial_service_stopped', ended_at=self.now())
                    self._checkpoint(job, package=True)
