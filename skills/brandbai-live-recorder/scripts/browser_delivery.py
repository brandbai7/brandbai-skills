"""Durable, task-scoped local ZIP delivery. Never serves arbitrary filesystem paths."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

ID = re.compile(r'[a-f0-9]{32}')
CLIENT = re.compile(r'[a-p]{32}')
KINDS = {'recording', 'product', 'catalog', 'reviews', 'recorded_products'}
TRANSFER = {'starting', 'downloading', 'paused'}


class DeliveryError(ValueError):
    pass


class BrowserDeliveries:
    """Only this registry's dedicated cache is mutable; historical exports are excluded."""
    def __init__(self, root: Path, *, now=time.time, reserve_bytes=256 * 1024**2):
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise DeliveryError('unsafe_delivery_cache')
        self.now, self.reserve_bytes = now, reserve_bytes
        self.lock = threading.RLock()
        self.jobs = {}
        self.workers = set()
        if self.root.exists():
            for path in self.root.glob('*/delivery.json'):
                if not ID.fullmatch(path.parent.name) or path.parent.is_symlink():
                    continue
                try:
                    row = json.loads(path.read_text(encoding='utf-8'))
                    if row.get('id') != path.parent.name or row.get('kind') not in KINDS:
                        continue
                    self.jobs[row['id']] = row
                    if row['state'] in {'collecting', 'packing'}:
                        row.update(state='interrupted', reason='assistant_restarted', recoverable=True)
                        self._save(row)
                except (OSError, ValueError, KeyError):
                    continue

    def _dir(self, ident):
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            raise DeliveryError('invalid_delivery')
        path = self.root / ident
        if path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise DeliveryError('unsafe_delivery_cache')
        return path

    def _file(self, ident, relative):
        base = self._dir(ident)
        if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise DeliveryError('unsafe_delivery_file')
        path = base / relative
        if not path.resolve().is_relative_to(base.resolve()):
            raise DeliveryError('unsafe_delivery_file')
        for parent in (path, *path.parents):
            if parent == base.parent:
                break
            if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
                raise DeliveryError('unsafe_delivery_file')
        return path

    def _save(self, row):
        folder = self._dir(row['id'])
        folder.mkdir(parents=True, exist_ok=True)
        pending = folder / 'delivery.pending'
        pending.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True), encoding='utf-8')
        pending.replace(folder / 'delivery.json')

    def _row(self, ident):
        if ident not in self.jobs:
            raise DeliveryError('delivery_not_found')
        self._dir(ident)
        return self.jobs[ident]

    def public(self, ident):
        with self.lock:
            row = self._row(ident)
            fields = ('id', 'kind', 'source_id', 'state', 'created_at', 'filename', 'bytes_total',
                      'bytes_packed', 'bytes_received', 'reason', 'material_status', 'download_id',
                      'attempt_id', 'attempt_created_at', 'completed_at', 'recoverable', 'late_data_available')
            return {key: row.get(key) for key in fields}

    def find(self, source_id):
        with self.lock:
            return next((self.public(r['id']) for r in self.jobs.values() if r['source_id'] == source_id), None)

    def list(self):
        with self.lock:
            return [self.public(r['id']) for r in sorted(self.jobs.values(), key=lambda x: x['created_at'], reverse=True)]

    def create(self, kind, source_id, *, fingerprint=None):
        if kind not in KINDS or not isinstance(source_id, str) or not 1 <= len(source_id) <= 500:
            raise DeliveryError('invalid_delivery_source')
        with self.lock:
            previous = self.find(source_id)
            if previous:
                if fingerprint and self._row(previous['id']).get('fingerprint') != fingerprint:
                    raise DeliveryError('delivery_request_changed')
                return previous
            self.root.mkdir(parents=True, exist_ok=True)
            # Reclaim only owned copies whose browser delivery was confirmed at least a day ago.
            try:
                self.cleanup_completed()
            except OSError:
                pass  # A locked cache is retained; a new request still gets a real space check.
            if shutil.disk_usage(self.root).free < self.reserve_bytes:
                raise DeliveryError('delivery_storage_low')
            if len(self.jobs) >= 2000:
                raise DeliveryError('delivery_cache_capacity')
            ident = uuid.uuid4().hex
            row = dict(id=ident, kind=kind, source_id=source_id, created_at=self.now(), state='collecting',
                       recoverable=True, bytes_received=0, bytes_packed=0, fingerprint=fingerprint)
            self.jobs[ident] = row
            self._save(row)
            self.work_root(ident).mkdir()
            return self.public(ident)

    def work_root(self, ident):
        return self._file(ident, 'work')

    def source(self, ident, path):
        with self.lock:
            row = self._row(ident)
            path = Path(path).resolve()
            if not path.is_relative_to(self.work_root(ident).resolve()):
                raise DeliveryError('source_not_owned')
            relative = path.relative_to(self._dir(ident)).as_posix()
            self._file(ident, relative)
            row['source_folder'] = relative
            self._save(row)

    def finish_existing(self, ident, result):
        """The product/review writer has already verified its archive."""
        with self.lock:
            row = self._row(ident)
            archive = result.get('archive') or result.get('zip_path')
            if not archive:
                row.update(state='interrupted', reason='package_not_ready', recoverable=True)
            else:
                path = Path(archive).resolve()
                if not path.is_relative_to(self.work_root(ident).resolve()):
                    raise DeliveryError('archive_not_owned')
                relative = path.relative_to(self._dir(ident)).as_posix()
                self._file(ident, relative)
                if not path.is_file() or path.suffix != '.zip':
                    raise DeliveryError('archive_not_ready')
                row.update(state='ready', archive=relative, filename=path.name, bytes_total=path.stat().st_size,
                           material_status=result.get('completeness') or result.get('state'), reason=None)
                if result.get('output_dir'):
                    self.source(ident, result['output_dir'])
            self._save(row)
            return self.public(ident)

    def fail(self, ident, reason='package_failed'):
        with self.lock:
            row = self._row(ident)
            row.update(state='interrupted', reason=reason, recoverable=True)
            self._save(row)

    def mark_late_data(self, ident):
        with self.lock:
            row = self._row(ident)
            if row['state'] != 'collecting':
                row['late_data_available'] = True
                self._save(row)

    def pack(self, ident, *, material_status='partial_recovered', text_lock=None, delay=0):
        """Snapshot small ledgers; copy media as stored ZIP64 entries, never recompress video."""
        with self.lock:
            row = self._row(ident)
            if ident in self.workers:
                return self.public(ident)
            if row['state'] in TRANSFER:
                raise DeliveryError('download_in_progress')
            source = row.get('source_folder')
            if not source:
                # Recovery of an interrupted product writer only considers this task's work area.
                candidates = [p.parent for p in self.work_root(ident).rglob('导出信息.json') if not p.is_symlink()]
                if len(candidates) != 1:
                    raise DeliveryError('recovery_source_unconfirmed')
                self.source(ident, candidates[0]); source = row['source_folder']
            row.update(state='packing', reason=None, bytes_packed=0, material_status=material_status,
                       late_data_available=False)
            self._save(row); self.workers.add(ident)

        def worker():
            try:
                if delay:
                    time.sleep(delay)
                folder = self._file(ident, source)
                if row['kind'] == 'recording':
                    # Validate before any bundle helper reads or writes inside the owned source.
                    for candidate in folder.rglob('*'):
                        self._file(ident, candidate.relative_to(self._dir(ident)).as_posix())
                    from recording_bundle import save_popup_thumbnails, recording_filename, write_bundle_guide
                    save_popup_thumbnails(folder)
                files, total = [], 0
                with text_lock or threading.RLock():
                    if row['kind'] == 'recording':
                        # Reconcile late append-only views with the fetched URL cache; no network here.
                        save_popup_thumbnails(folder, seconds=0, max_images=0)
                        filename = recording_filename(folder, created_at=row['created_at'])
                        write_bundle_guide(folder, filename)
                    else:
                        filename = folder.name + '.zip'
                    with self.lock:
                        row['late_data_available'] = False
                    for path in sorted(folder.rglob('*')):
                        relative = path.relative_to(self._dir(ident)).as_posix()
                        path = self._file(ident, relative)
                        if not path.is_file() or path.suffix in {'.tmp', '.pending', '.zip'}:
                            continue
                        size = path.stat().st_size
                        # Snapshot mutable readable/structured records before packing large media.
                        data = path.read_bytes() if path.suffix in {'.json', '.jsonl', '.md', '.csv', '.log'} else None
                        files.append((path, path.relative_to(folder).as_posix(), data, size)); total += size
                if not files:
                    raise DeliveryError('no_material_to_package')
                if shutil.disk_usage(self.root).free < total + self.reserve_bytes:
                    raise DeliveryError('delivery_storage_low')
                archive = self._dir(ident) / (uuid.uuid4().hex + '.zip')
                pending = archive.with_suffix('.pending')
                with self.lock:
                    row['bytes_total'] = total; self._save(row)
                packed = 0
                with zipfile.ZipFile(pending, 'x', zipfile.ZIP_STORED, allowZip64=True) as zf:
                    for path, name, data, size in files:
                        with zf.open(name, 'w', force_zip64=True) as output:
                            if data is not None:
                                output.write(data); packed += len(data)
                            else:
                                with path.open('rb') as incoming:
                                    while block := incoming.read(1024 * 1024):
                                        output.write(block); packed += len(block)
                                        with self.lock:
                                            row['bytes_packed'] = packed
                        with self.lock:
                            row['bytes_packed'] = packed
                    zf.writestr('交付状态.json', json.dumps(dict(material_status=material_status,
                        source_id=row['source_id'], delivery_id=ident,
                        note='资料完整性与浏览器下载状态分别记录；原始媒体和已取得文件均保留。'), ensure_ascii=False))
                with zipfile.ZipFile(pending) as zf:
                    if zf.testzip() is not None:
                        raise DeliveryError('archive_verification_failed')
                pending.replace(archive)
                with self.lock:
                    row.update(archive=archive.name, filename=filename, state='ready',
                               bytes_total=archive.stat().st_size, bytes_packed=packed)
                    self._save(row)
            except Exception as exc:
                self.fail(ident, str(exc) if isinstance(exc, DeliveryError) else 'package_failed')
            finally:
                with self.lock:
                    self.workers.discard(ident)
        threading.Thread(target=worker, daemon=True, name='browser-zip-package').start()
        return self.public(ident)

    def claim(self, ident, client, *, retry=False):
        if not CLIENT.fullmatch(client):
            raise DeliveryError('extension_client_required')
        with self.lock:
            row = self._row(ident)
            if row['state'] in TRANSFER:
                return self.public(ident)  # Ambiguous dispatch must be reconciled, never duplicated.
            if row['state'] != 'ready' and not (retry and row['state'] in {'interrupted', 'canceled', 'completed'}):
                raise DeliveryError('delivery_not_ready')
            path = self._file(ident, row.get('archive', ''))
            if not path.is_file() or path.suffix != '.zip':
                raise DeliveryError('package_not_ready')
            ticket, attempt = secrets.token_urlsafe(36), uuid.uuid4().hex
            row.update(state='starting', attempt_id=attempt, client=client, ticket_hash=hashlib.sha256(ticket.encode()).hexdigest(),
                       ticket_expires=self.now() + 86400, attempt_created_at=self.now(), download_id=None,
                       bytes_received=0, completed_at=None, reason=None)
            self._save(row)
            return dict(self.public(ident), ticket=ticket, file_route=f'/v1/deliveries/{ident}/file/{attempt}')

    def open_archive(self, ident, attempt, ticket, client):
        with self.lock:
            row = self._row(ident)
            if (row.get('attempt_id') != attempt or row.get('client') != client or self.now() >= row.get('ticket_expires', 0)
                or not hmac.compare_digest(hashlib.sha256(ticket.encode()).hexdigest(), row.get('ticket_hash', ''))):
                raise DeliveryError('invalid_file_ticket')
            if row['state'] not in TRANSFER | {'interrupted'}:
                raise DeliveryError('file_ticket_inactive')
            return self._file(ident, row['archive']).open('rb')

    def report(self, ident, body, client):
        allowed = {'attempt_id', 'download_id', 'state', 'bytes_received', 'reason'}
        if not isinstance(body, dict) or set(body) != allowed or body['state'] not in TRANSFER | {'completed', 'interrupted', 'canceled'}:
            raise DeliveryError('invalid_download_report')
        if type(body['download_id']) is not int or body['download_id'] < 0 or type(body['bytes_received']) is not int or body['bytes_received'] < 0:
            raise DeliveryError('invalid_download_count')
        if body['reason'] is not None and (not isinstance(body['reason'], str) or not re.fullmatch('[A-Z_]{1,80}', body['reason'])):
            raise DeliveryError('invalid_download_reason')
        with self.lock:
            row = self._row(ident)
            if row.get('attempt_id') != body['attempt_id'] or row.get('client') != client:
                raise DeliveryError('download_attempt_changed')
            if row.get('download_id') is not None and row['download_id'] != body['download_id']:
                raise DeliveryError('download_id_changed')
            if row['state'] == 'completed':
                return self.public(ident)
            if body['state'] == 'completed' and body['bytes_received'] != row['bytes_total']:
                raise DeliveryError('download_size_unconfirmed')
            row.update(body)
            if body['state'] == 'completed':
                row['completed_at'] = self.now()
            self._save(row)
            return self.public(ident)

    def reconcile_missing(self, ident, client):
        with self.lock:
            row = self._row(ident)
            if row.get('client') != client or row['state'] not in TRANSFER:
                raise DeliveryError('download_attempt_changed')
            row.update(state='interrupted', reason='BROWSER_RECORD_NOT_FOUND')
            self._save(row)
            return self.public(ident)

    def cleanup_completed(self):
        """24h grace after confirmed browser completion, never clean pending or historical files."""
        with self.lock:
            for row in self.jobs.values():
                if (row['state'] != 'completed' or not row.get('completed_at') or row.get('late_data_available')
                    or self.now() - row['completed_at'] < 86400 or row['id'] in self.workers):
                    continue
                folder = self._dir(row['id'])
                # Validate the entire owned subtree before any recursive removal (junctions included).
                targets = [p for p in folder.iterdir() if p.name != 'delivery.json']
                for target in targets:
                    self._file(row['id'], target.relative_to(folder).as_posix())
                    if target.is_dir():
                        for child in target.rglob('*'):
                            self._file(row['id'], child.relative_to(folder).as_posix())
                for target in targets:
                    if target.is_dir(): shutil.rmtree(target)
                    else: target.unlink()
                row['recoverable'] = False; row.pop('archive', None); self._save(row)
