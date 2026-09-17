"""Synthetic interaction delivery tests; no customer files or browser access."""
import csv
import json
import unittest
from interaction_export import write_interaction_export, csv_cell
from test_local_service import scratch_dir


class InteractionExportTests(unittest.TestCase):
    def event(self, kind='comment_visible', **changes):
        row=dict(event_type=kind,payload=dict(masked_user='测***',text='=合成评论|<img>\n下一行',observation_kind='baseline_visible'),
                 observed_at='2026-01-01T00:00:05+08:00',recording_offset_seconds=5,
                 within_recording_window=True,visible_event_id='synthetic-1',collector_session_id='synthetic-session')
        row.update(changes)
        return row

    def task(self):
        return dict(task_id='synthetic-task',started_at='2026-01-01T00:00:00+08:00',collect_comments=True,
                    collect_product_cards=True,collect_room_metrics=True)

    def test_readable_table_counts_and_raw_unchanged(self):
        with scratch_dir() as root:
            (root/'data').mkdir();raw=root/'data/visible_page_events.jsonl';raw.write_bytes(b'CANONICAL_UNCHANGED\n')
            (root/'02_录屏说明与完整性.md').write_text('# Media summary\nvideo remains here\n',encoding='utf-8')
            events=[self.event(),self.event('product_state',payload={'product_title':'合成商品','change_kind':'baseline_visible','display_price':'¥30起'}),
                    self.event('room_snapshot',payload={'online_viewers':0,'likes_display':None,'hour_rank':'100+'}),
                    self.event('collector_status',payload={'status':'playback_paused',**self.task()},within_recording_window=False)]
            report=write_interaction_export(root,events,self.task());folder=root/'05_直播互动'
            self.assertEqual(report['event_count'],4);self.assertEqual(report['outside_task_window_count'],1)
            self.assertNotIn('collector_status',report['task_window_counts'])
            self.assertEqual(raw.read_bytes(),b'CANONICAL_UNCHANGED\n')
            with (folder/'直播互动记录.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
            self.assertEqual(len(rows),3);self.assertTrue(rows[1][5].startswith("'="))
            self.assertIn('不代表此刻新发',rows[1][6])
            metrics=(root/'07_直播指标/页面指标记录.md').read_text(encoding='utf-8')
            self.assertIn('在线人数：0',metrics);self.assertIn('点赞展示：未知',metrics)
            self.assertTrue(report['classified_sections'])
            md=(folder/'直播互动记录.md').read_text(encoding='utf-8')
            self.assertNotIn('<img>',md);self.assertIn('\\|&lt;img&gt;',md)
            readme=(root/'02_录屏说明与完整性.md').read_text(encoding='utf-8')
            self.assertIn('video remains here',readme);self.assertIn('05_直播互动/直播互动记录.md',readme)

    def test_empty_enabled_is_warning_and_disabled_writes_nothing(self):
        with scratch_dir() as root:
            self.assertIsNone(write_interaction_export(root,[],{}));self.assertFalse((root/'05_直播互动').exists())
            report=write_interaction_export(root,[],self.task())
            self.assertEqual(report['coverage'],'enabled_but_no_events');self.assertIsNone(report['source'])
            self.assertIn('未收到页面事件',(root/'05_直播互动/直播互动记录.md').read_text(encoding='utf-8'))

    def test_late_events_replace_views_not_duplicate_sections(self):
        with scratch_dir() as root:
            write_interaction_export(root,[self.event()],self.task())
            write_interaction_export(root,[self.event(),self.event(visible_event_id='synthetic-2')],self.task())
            summary=json.loads((root/'05_直播互动/完整性.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['event_count'],2)
            self.assertEqual((root/'02_录屏说明与完整性.md').read_text(encoding='utf-8').count('## 直播互动文件'),1)
            self.assertFalse(list(root.rglob('*.tmp')))

    def test_formula_prefixes(self):
        for text in ['=1',' +1','-1','@formula','\ttext','\ntext']:
            self.assertTrue(csv_cell(text).startswith("'"))
        self.assertEqual(csv_cell('正常评论'),'正常评论')

    def test_popup_cover_gap_is_not_no_popup_and_is_exported_separately(self):
        with scratch_dir() as root:
            events=[self.event('collector_status',payload={'status':'popup_observation_paused'}),self.event(),
                self.event('collector_status',payload={'status':'popup_observation_resumed'},observed_at='2026-01-01T00:00:25+08:00'),
                self.event('collector_status',payload={'status':'popup_observation_paused'},observed_at='2026-01-01T00:00:30+08:00')]
            report=write_interaction_export(root,events,self.task())
            self.assertEqual(report['counts']['comment_visible'],1)
            self.assertEqual(len(report['popup_observation_intervals']),2)
            self.assertIsNone(report['popup_observation_intervals'][1]['to'])
            popup=json.loads((root/'06_弹窗商品/弹窗商品记录.json').read_text(encoding='utf-8'))
            self.assertEqual(popup['observation_intervals'],report['popup_observation_intervals'])
            self.assertIn('不代表主播没有弹商品',(root/'06_弹窗商品/弹窗观察空档.md').read_text(encoding='utf-8'))

    def test_comment_silence_is_unknown_not_zero_or_lost_count(self):
        with scratch_dir() as root:
            events = [self.event(), self.event(observed_at='2026-01-01T00:04:05+08:00', visible_event_id='synthetic-2')]
            report = write_interaction_export(root, events, self.task())
            self.assertEqual(report['comment_silence_intervals'][0]['seconds'], 240)
            self.assertEqual(report['comment_continuity'], 'not_guaranteed_visible_page_only')
            self.assertIn('不代表没有人发言', (root/'05_直播互动/直播互动记录.md').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
