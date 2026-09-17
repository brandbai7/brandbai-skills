"""Readable views of validated, current-session events. No collection or analysis."""
from collections import Counter
import csv
import html
import io
import json
import os
from pathlib import Path
from datetime import datetime

LABELS = {'comment_visible': '可见评论', 'product_state': '商品卡状态',
          'room_snapshot': '页面指标', 'collector_status': '采集状态',
          'product_list_item': '商品列表观察', 'product_detail': '商品详情观察'}
FLAGS = ('collect_comments', 'collect_product_cards', 'collect_room_metrics')
STATUS = {'started': '开始采集', 'stopped': '停止采集', 'page_reloaded': '页面接入／重接',
          'options_changed': '采集选项变化', 'playback_paused': '页面暂停',
          'playback_resume_requested': '尝试恢复播放', 'playback_resumed': '页面恢复播放',
          'playback_resume_failed': '恢复播放未成功', 'failed': '采集异常',
          'interaction_interrupted': '互动采集受到阻断', 'interaction_resumed': '页面或连接恢复（以新评论为准）',
          'comment_stream_stale': '长时间未观察到新评论（不代表无评论）', 'comment_stream_resumed': '重新观察到新评论',
          'popup_observation_paused':'商品面板覆盖，暂停观察直播弹窗', 'popup_observation_resumed':'商品面板关闭，恢复观察直播弹窗'}
CHANGES = {'baseline_visible': '首次看到商品卡', 'visible_product_changed': '可见商品变化',
           'visible_info_changed': '商品信息变化', 'temporarily_not_visible': '商品卡暂时不可见',
           'restored_visible': '商品卡恢复可见'}


def atomic_text(path, text, encoding='utf-8'):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding=encoding, newline='')
    os.replace(temporary, path)


def csv_cell(value):
    text = '' if value is None else str(value)
    # Spreadsheet formula protection; canonical JSONL stays byte-for-byte intact.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


def md_cell(value):
    text = html.escape('' if value is None else str(value), quote=False)
    for char in ('\\', '`', '[', ']', '*', '_', '|'):
        text = text.replace(char, '\\' + char)
    return text.replace('\r', ' ').replace('\n', ' ')


def public_cells(event):
    p = event.get('payload') or {}
    kind = event.get('event_type')
    who, content, note = '', '', ''
    if kind == 'comment_visible':
        who, content = p.get('masked_user'), p.get('text')
        note = {'baseline_visible':'开始时已可见（不代表此刻新发）','new_visible':'新观察到的评论'}.get(p.get('observation_kind'), '观察类型未确认')
    elif kind == 'product_state':
        content = p.get('product_title') or '未显示商品'
        note = '；'.join(str(v) for v in (CHANGES.get(p.get('change_kind'), ''), p.get('display_price')) if v)
    elif kind == 'room_snapshot':
        content = '；'.join(f'{label}：{p.get(key) if p.get(key) is not None else "未知"}' for key, label in
                           (('online_viewers', '在线人数'), ('likes_display', '点赞展示'), ('hour_rank', '榜单展示')))
    elif kind == 'collector_status':
        content = STATUS.get(p.get('status'), '采集状态')
        note = '；'.join(f'{label}：{"开启" if p.get(key) else "关闭"}' for key, label in
                        zip(FLAGS, ('评论', '商品卡', '页面指标')))
        if p.get('reason'): note += '；原因：' + str(p['reason'])
    elif kind in {'product_list_item', 'product_detail'}:
        content = p.get('product_title') or ''
        note = '详细字段见同场次 04_商品资料.md；不是场控弹窗事件'
    return [event.get('observed_at'), event.get('recording_offset_seconds'),
            {True: '窗口内', False: '窗口外'}.get(event.get('within_recording_window'), '未确认'),
            LABELS.get(kind, '其他观察'), who, content, note,
            event.get('visible_event_id'), event.get('collector_session_id')]


def write_interaction_export(root, events, task):
    """Caller holds the session export lock; events are already validated and scoped."""
    root = Path(root)
    requested = {key: bool(task.get(key)) for key in FLAGS}
    if not events and not any(requested.values()):
        return None
    folder = root / '05_直播互动'
    folder.mkdir(parents=True, exist_ok=True)
    counts = Counter(e['event_type'] for e in events)
    window_counts = Counter(e['event_type'] for e in events if e.get('within_recording_window') is True)
    outside = sum(e.get('within_recording_window') is False for e in events)
    unknown = sum(e.get('within_recording_window') is None for e in events)
    comment_times = sorted({e['observed_at'] for e in events if e.get('event_type') == 'comment_visible'
                            and e.get('within_recording_window') is True and e.get('observed_at')})
    quiet_intervals = []
    popup_intervals, pending = [], {}
    for e in sorted(events, key=lambda e:e.get('observed_at') or ''):
        if e.get('event_type')!='collector_status': continue
        status=e.get('payload',{}).get('status'); session=e.get('collector_session_id')
        if status=='popup_observation_paused': pending.setdefault(session,e.get('observed_at'))
        elif status in {'popup_observation_resumed','stopped'} and session in pending:
            popup_intervals.append({'from':pending.pop(session),'to':e.get('observed_at'),
                'end_status':'resumed' if status=='popup_observation_resumed' else 'collector_stopped',
                'status':'popup_not_observable_not_proof_of_no_popup'})
    popup_intervals += [{'from':at,'to':None,'end_status':'not_observed',
                         'status':'popup_not_observable_not_proof_of_no_popup'} for at in pending.values()]
    for earlier, later in zip(comment_times, comment_times[1:]):
        duration = (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds()
        if duration >= 180:
            quiet_intervals.append({'from': earlier, 'to': later, 'seconds': round(duration, 3),
                                    'status': 'no_new_comment_observed_not_proof_of_zero_comments'})
    from recording_bundle import write_recording_sections
    popup = write_recording_sections(root, events, task, observation_intervals=popup_intervals)
    summary = dict(schema='brandbai.live-interaction-export.v2', task_id=task.get('task_id'),
                   task_started_at=task.get('started_at'), selected_options_at_export=requested,
                   event_count=len(events), counts=dict(counts), task_window_counts=dict(window_counts),
                   outside_task_window_count=outside, unknown_window_count=unknown,
                   coverage='visible_observations_only' if events else 'enabled_but_no_events',
                   source='../data/visible_page_events.jsonl' if events else None,
                   time_alignment='task_wall_clock_not_frame_accurate', analysis_status='not_requested',
                   classified_sections=True, popup_observation_group_count=popup['observation_group_count'],
                   confirmed_popup_product_id_count=popup['confirmed_product_id_count'],
                   comment_silence_intervals=quiet_intervals,
                   popup_observation_intervals=popup_intervals,
                   comment_continuity='not_guaranteed_visible_page_only')
    headers = ['观察时间', '任务开始后秒数（未校准）', '任务窗口', '类型', '脱敏昵称', '内容', '说明', '事件编号', '采集会话']
    lines = ['# 评论与互动记录', '',
             f'已保存可见评论 {counts["comment_visible"]} 条。下表仅包含评论及采集状态。', '',
             '[弹窗商品单独查看](../06_弹窗商品/本场弹窗商品概览.md) · [直播指标单独查看](../07_直播指标/页面指标记录.md)。它们不属于观众互动。仅记录浏览器实际观察到的内容，不代表全量评论。', '',
             '时间按任务开始的本机时钟计算，包含准备时间，未与视频逐帧校准；不要直接当作播放器精确秒数。', '',
             f'窗口外记录 {outside} 条、窗口归属未确认 {unknown} 条；下表保留标记，不混作窗口内互动。', '',
             '[表格版](直播互动记录.csv)' + (' · [原始结构化记录](../data/visible_page_events.jsonl)' if events else ''), '']
    if not events:
        lines += ['**本次开启了互动记录，但未收到页面事件。视频保存不代表互动采集成功；无法据此补出历史评论。**', '']
    if quiet_intervals:
        lines += ['## 评论连续性提醒', '',
                  '以下时段未观察到新评论，不代表没有人发言，也不能由此确定丢失条数。视频保存成功与评论连续性是两回事。', '']
        for interval in quiet_intervals:
            lines += [f'- {interval["from"]} 至 {interval["to"]}：{interval["seconds"]:g} 秒没有新评论记录。']
        lines += ['', '不能从这份资料包补回当时未采到的评论。', '']
    if popup_intervals:
        lines += ['## 商品弹窗观察空档', '', '以下时段商品面板覆盖了直播弹窗观察。不是主播没有弹商品，不代表评论或视频同时停止。', '']
        lines += [f'- {i["from"]} 至 {i["to"] or "尚未观察到恢复"}。' for i in popup_intervals]
        lines += ['']
    lines += ['| ' + ' | '.join(headers[:7]) + ' |', '| ' + ' | '.join(['---'] * 7) + ' |']
    table = io.StringIO(newline='')
    writer = csv.writer(table)
    writer.writerow(headers)
    for event in events:
        if event.get('event_type') not in {'comment_visible', 'collector_status'}:
            continue
        cells = public_cells(event)
        writer.writerow([csv_cell(v) for v in cells])
        lines.append('| ' + ' | '.join(md_cell(v) for v in cells[:7]) + ' |')
    atomic_text(folder / '直播互动记录.csv', table.getvalue(), 'utf-8-sig')
    atomic_text(folder / '直播互动记录.md', '\n'.join(lines) + '\n')
    atomic_text(folder / '完整性.json', json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    # Update one generated section only, preserving the media summary and late batches.
    readme = root / '02_录屏说明与完整性.md'
    original = readme.read_text(encoding='utf-8') if readme.is_file() else '# 录屏说明与完整性\n'
    marker = '\n## 直播互动文件\n'
    original = original.split(marker)[0].rstrip()
    note = (f'评论 {counts["comment_visible"]} 条 · 弹窗卡片 {popup["observation_group_count"]} 个观察组（{counts["product_state"]} 条状态）· 页面指标 {counts["room_snapshot"]} 次。'
            if events else '已开启互动记录，但本次没有收到页面事件；请勿按互动完整使用。')
    atomic_text(readme, original + marker + '\n' + note + '\n\n'
        '[评论与互动](05_直播互动/直播互动记录.md) · [弹窗商品概览](06_弹窗商品/本场弹窗商品概览.md) · '
        '[弹窗时间记录](06_弹窗商品/弹窗时间记录.md) · [直播指标](07_直播指标/页面指标记录.md)\n\n'
        '以上分区随同直播视频放在一个 ZIP 内，不需要另下商品资料包。弹窗仅是页面观察，不是完整商品资料；完整详情、SKU 和评价仍通过独立商品下载取得。\n\n'
        '仅为可见观察；窗口、暂停及时间边界见记录说明。\n')
    return summary
