"""Synthetic export naming and cross-package association checks."""
from pathlib import Path
import unittest
import uuid
import zipfile

from export_naming import asset_name, create_export_folder, export_info, identity_label, label
from recorder_core import create_session_output_root
from product_downloads import finish_archive
from test_local_service import scratch_dir


class ExportNamingTests(unittest.TestCase):
    def info(self, kind='product', **kw):
        args=dict(observed_at='2026-09-15T23:00:00+08:00', identity={'product_id':'123456789', 'product_ref':'douyin:product:123456789'},
                  shop='合成旗舰店', title='合成商品 Pro4.0', room_url='https://live.douyin.com/123456',
                  batch_id='12345678-1234-4234-8234-123456789012')
        args.update(kw)
        return export_info(kind, **args)

    def test_identity_shared_between_materials_and_reviews(self):
        a=self.info(); b=self.info('reviews', batch_id=str(uuid.uuid4()))
        self.assertEqual(a['product_identity'], b['product_identity'])
        self.assertEqual(a['entity_label'], b['entity_label'])
        self.assertNotEqual(a['package_name'], b['package_name'])
        self.assertNotIn('P123456789', a['package_name'])
        self.assertIn('2026-09-15_23-00-00', a['package_name'])
        self.assertTrue(a['observed_at'].endswith('+08:00'))

    def test_unknown_id_does_not_use_room_number_or_title(self):
        a=self.info(identity={'product_id':None,'product_ref':'douyin:observation:one'})
        b=self.info(identity={'product_id':None,'product_ref':'douyin:observation:two'})
        self.assertNotEqual(a['entity_label'],b['entity_label'])
        self.assertTrue(a['entity_label'].startswith('待核ID-'))
        self.assertNotIn('R123456',a['package_name'])
        self.assertNotIn('待核',a['package_name'])
        self.assertNotEqual(identity_label({},fallback='one'),identity_label({},fallback='two'))

    def test_names_are_safe_and_original_titles_remain(self):
        title='合成 Pro4.0 / : * ? < > | \\ \u202e'+'很长标题'*60
        a=self.info(title=title,shop='NUL')
        self.assertEqual(a['product_title'],title)
        self.assertEqual(label('CON','fallback'),'_CON')
        self.assertLess(len(a['package_name']),130)
        self.assertNotRegex(a['package_name'],r'[<>:"/\\|?*.\x00-\x1f\u202e]')

    def test_new_batches_same_second_are_distinct_without_codes(self):
        with scratch_dir() as scratch:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as pool:
                names=list(pool.map(lambda _: create_export_folder(scratch,self.info(batch_id=str(uuid.uuid4()))).name,range(100)))
            self.assertEqual(len(set(names)),100)
            self.assertTrue(any(name.endswith(' (2)') for name in names))
            self.assertTrue(all('待核' not in name and 'R123456' not in name for name in names))

    def test_missing_labels_are_omitted_and_room_fallback_is_neutral(self):
        for kind in ('product','catalog','reviews'):
            for missing in (None,'','店铺待核','商品待核','直播间待核','待核ID-123abc'):
                info=self.info(kind,shop=missing,title=missing,identity=None)
                self.assertEqual(info['package_name'],f"抖音_直播间_{ {'product':'商品资料','catalog':'商品目录','reviews':'商品评价'}[kind]}_2026-09-15_23-00-00")
        self.assertEqual(self.info(title=None)['package_name'],'抖音_合成旗舰店_商品资料_2026-09-15_23-00-00')

    def test_existing_archive_is_not_replaced_when_folder_was_removed(self):
        with scratch_dir() as scratch:
            info=self.info()
            archive=Path(scratch)/(info['package_name']+'.zip')
            archive.write_bytes(b'previous export')
            folder=create_export_folder(scratch,info)
            self.assertTrue(folder.name.endswith(' (2)'))
            self.assertEqual(folder.name,info['package_name'])
            self.assertEqual(archive.read_bytes(),b'previous export')

    def test_completed_request_does_not_become_a_new_copy_after_restart(self):
        with scratch_dir() as scratch:
            folder=create_export_folder(scratch,self.info())
            folder.with_suffix('.zip').write_bytes(b'previous export')
            with self.assertRaises(FileExistsError):
                create_export_folder(scratch,self.info())

    def test_asset_types_and_gallery_order(self):
        self.assertEqual(asset_name(self.info(),'视频',1,'.mp4',gallery_position=1),'轮播001_视频.mp4')
        self.assertEqual(asset_name(self.info(),'主图',1,'.jpg',gallery_position=2),'轮播002_主图.jpg')
        for bad in (0,-1,True,'1'):
            with self.assertRaises(ValueError): asset_name(self.info(),'主图',1,'.jpg',gallery_position=bad)

    def test_zip_has_exact_folder_basename_and_never_overwrites(self):
        with scratch_dir() as scratch:
            root=Path(scratch)/self.info()['package_name'];root.mkdir()
            (root/'00_资料说明.md').write_text('synthetic',encoding='utf8')
            result=finish_archive(root,{})
            self.assertEqual(Path(result['archive']).name,root.name+'.zip')
            with zipfile.ZipFile(result['archive']) as archive:self.assertIsNone(archive.testzip())
            with self.assertRaises(FileExistsError):finish_archive(root,{})

    def test_recording_folders_frozen_and_unique(self):
        with scratch_dir() as scratch:
            a=create_session_output_root(Path(scratch),'123456',run_token='one')
            b=create_session_output_root(Path(scratch),'123456',run_token='two')
            self.assertNotEqual(a,b)
            self.assertIn('直播录制',a.name)
            self.assertIn('R123456',a.name)
            self.assertTrue(a.is_relative_to(Path(scratch)))


if __name__ == '__main__': unittest.main()
