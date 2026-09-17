"""Synthetic recording exports; network is always mocked."""
import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from recording_bundle import card_groups, write_recording_sections, save_popup_thumbnails, recording_filename
from interaction_export import write_interaction_export
from test_local_service import scratch_dir
from test_product_downloads import PNG

URL='https://p3-a.ecombdimg.com/synthetic/card.png'


def event(index, title='合成商品', *, visible=True, url=None, image=URL, kind='product_state', collector='collector-a'):
    return dict(event_type=kind, collector_session_id=collector, visible_event_id=f'evt-{index}',
        observed_at_epoch_ms=1000+index*1000, observed_at=f'2026-01-01T20:50:{index:02d}+08:00',
        recording_offset_seconds=index, within_recording_window=True, room_url='https://live.douyin.com/12345',
        payload=dict(visible=visible, product_title=title, product_url=url, shop_name=None,
            card_observation_id=f'card-{index}', change_kind='baseline_visible' if index==1 else 'restored_visible' if visible else 'temporarily_not_visible',
            display_price='¥10' if index<3 else '¥12', images=[dict(url=image, kind='card_image')] if image else []))


class RecordingBundleTests(unittest.TestCase):
    def test_same_appearance_many_snapshots_one_unconfirmed_group(self):
        groups, rows=card_groups([event(1),event(2,visible=False),event(3),event(4)])
        self.assertEqual(len(groups),1);self.assertEqual(len(rows),4)
        self.assertIsNone(groups[0]['product_id']);self.assertEqual(groups[0]['visible_snapshot_count'],3)
        self.assertEqual(groups[0]['observed_prices'],['¥10','¥12'])
        self.assertEqual(rows[1]['observation_group'],'卡片001')

    def test_different_ids_titles_or_missing_images_do_not_guess_merge(self):
        link='https://haohuo.jinritemai.com/views/product/detail?id='
        groups,_=card_groups([event(1,url=link+'12345'),event(2,url=link+'12346'),
            event(3,title='另一合成商品'),event(4,image=None),event(5,image=None)])
        self.assertEqual(len(groups),5)
        self.assertEqual(groups[0]['product_id'],'12345')
        groups,_=card_groups([event(1,url=link+'12345'),event(2,title='更新标题',url=link+'12345')])
        self.assertEqual(len(groups),1);self.assertEqual(len(groups[0]['observed_titles']),2)

    def test_list_detail_never_counted_and_reload_does_not_guess_hidden_card(self):
        groups,rows=card_groups([event(1),event(2,kind='product_list_item'),event(3,kind='product_detail'),
            event(4,kind='collector_status'),event(5,visible=False)])
        self.assertEqual(len(groups),1);self.assertEqual(len(rows),2)
        self.assertIsNone(rows[-1]['observation_group'])

    def test_classified_views_thumbnail_dedup_failures_and_late_views(self):
        with scratch_dir() as root:
            task=dict(task_id='test',started_at='2026-01-01T20:50:00+08:00',collect_product_cards=True)
            write_interaction_export(root,[event(1),event(2),event(3,title='另一合成商品')],task)
            fetch=Mock(return_value=PNG)
            report=save_popup_thumbnails(root,fetcher=fetch)
            self.assertEqual(fetch.call_count,1);self.assertEqual(report['saved_groups'],2)
            save_popup_thumbnails(root,fetcher=fetch)
            self.assertEqual(fetch.call_count,1)
            write_interaction_export(root,[event(1),event(2),event(3,title='另一合成商品'),event(4,image=URL.replace('card','other'))],task)
            report=save_popup_thumbnails(root,fetcher=fetch,seconds=0,max_images=0)
            self.assertEqual(fetch.call_count,1);self.assertEqual(report['status'],'partial_thumbnails')
            report=save_popup_thumbnails(root,fetcher=Mock(side_effect=ValueError('failed')))
            self.assertEqual(report['items'][-1]['status'],'download_unavailable')
            report=save_popup_thumbnails(root,fetcher=fetch,seconds=0,max_images=0)
            self.assertEqual(report['items'][-1]['status'],'download_unavailable')
            md=(root/'06_弹窗商品/弹窗时间记录.md').read_text(encoding='utf-8')
            self.assertIn('不代表此刻弹出',md)
            self.assertNotIn('合成商品',(root/'05_直播互动/直播互动记录.csv').read_text(encoding='utf-8-sig'))

    def test_name_uses_frozen_room_and_task_start_no_codes(self):
        with scratch_dir() as root:
            (root/'data').mkdir()
            (root/'data/export_ses-test.json').write_text(json.dumps(dict(material_type='recording',shop_name='合成旗舰店',
                observed_at='2026-01-01T20:50:06+08:00')),encoding='utf-8')
            write_interaction_export(root,[],dict(collect_comments=True,started_at='2026-01-01T20:50:00+08:00'))
            self.assertEqual(recording_filename(root),'抖音_合成旗舰店_直播记录_2026-01-01_20-50-00.zip')
            (root/'data/export_ses-other.json').write_text(json.dumps(dict(material_type='recording',shop_name='不同店铺')),encoding='utf-8')
            self.assertEqual(recording_filename(root),'抖音_直播记录_2026-01-01_20-50-00.zip')

    def test_unknown_fields_and_formula_protection(self):
        with scratch_dir() as root:
            e=event(1,title='=合成|<img>');e['within_recording_window']=False
            write_recording_sections(root,[e],{})
            md=(root/'06_弹窗商品/本场弹窗商品概览.md').read_text(encoding='utf-8')
            self.assertNotIn('<img>',md)
            self.assertIn('身份未确认',md)
            csv=(root/'06_弹窗商品/本场弹窗商品概览.csv').read_text(encoding='utf-8-sig')
            self.assertIn("'=合成",csv)
            raw=json.loads((root/'06_弹窗商品/弹窗商品记录.json').read_text(encoding='utf-8'))
            self.assertFalse(raw['timeline'][0]['within_recording_window'])


if __name__=='__main__':unittest.main()
