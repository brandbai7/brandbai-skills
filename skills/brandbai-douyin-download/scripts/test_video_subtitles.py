"""Offline subtitle contract tests; no platform access or OCR execution."""
import json
from pathlib import Path
import uuid
import shutil
from contextlib import contextmanager
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from extract_video_subtitles import parse_region, local_asset, observed_time, observed_segment
from run_foundation import build_parser, validate_subtitle_args, subtitle_video_input, run_subtitle_stage, run_all, FoundationError

@contextmanager
def temporary():
    parent = Path(__file__).resolve().parent
    target = parent / ('_subtitle_test_' + uuid.uuid4().hex)
    target.mkdir()
    try:
        yield target
    finally:
        if target.resolve().parent == parent and target.name.startswith('_subtitle_test_'):
            shutil.rmtree(target)

class SubtitleTests(unittest.TestCase):
    def test_observed_times_are_not_invented_or_extended(self):
        self.assertEqual(observed_segment({'text': '合成字幕', 'firstObserved': 24.05, 'lastObserved': 26.05}), '[00:24.05–00:26.05] 合成字幕')
        self.assertEqual(observed_segment({'text': '缺失时间'}), '[时间待确认] 缺失时间')
        self.assertEqual(observed_segment({'text': '倒置时间', 'firstObserved': 2, 'lastObserved': 1}), '[时间待确认] 倒置时间')
        self.assertEqual(observed_time(61.2), '01:01.20')
        self.assertIsNone(observed_time(float('nan')))
        self.assertIsNone(observed_time(True))

    def args(self, *extra):
        return build_parser().parse_args(['all', '--video', 'https://www.douyin.com/video/7000000000000000001', '--profile-dir', 'private-profile', '--out', 'delivery', *extra])

    def test_off_by_default_and_no_cross_batch_or_implicit_crop(self):
        self.assertIsNone(validate_subtitle_args(self.args()))
        for extra in [('--subtitles',), ('--subtitle-region','0,.7,1,.8'),
                      ('--subtitles','--subtitle-region','0,.7,1,.8','--assets','none'),
                      ('--subtitles','--subtitle-region','0,.7,1,.8','--resume'),
                      ('--subtitles','--subtitle-region','0,.7,1,.8','--video','https://www.douyin.com/video/7000000000000000002')]:
            with self.assertRaises(FoundationError): validate_subtitle_args(self.args(*extra))
        self.assertEqual(validate_subtitle_args(self.args('--subtitles','--subtitle-region','0,.7,1,.8'))['top'],.7)

    def test_crop_and_local_serving_boundary(self):
        for text in ['0,nan,1,.8','0,.8,1,.5','0,0,1,2','anything']:
            with self.assertRaises(ValueError): parse_region(text)
        self.assertIsNone(local_asset('/../../SKILL.md'))
        self.assertIsNone(local_asset('/%2e%2e/%2e%2e/SKILL.md'))

    def test_input_is_exact_work_and_exact_local_download(self):
        with temporary() as tmp:
            root=Path(tmp); folder=root/'03_作品素材'/'one'; folder.mkdir(parents=True)
            video=folder/'video.mp4'; video.write_bytes(b'fake')
            work={'aweme_id':'7000000000000000001','type':'视频','local_folder':'03_作品素材/one','downloads':{'video':{'status':'downloaded','file':'video.mp4'}}}
            data=root/'works.json'; data.write_text(json.dumps([work]),encoding='utf-8')
            self.assertEqual(subtitle_video_input(data,root,work['aweme_id']),video)
            with self.assertRaises(ValueError):subtitle_video_input(data,root,'7000000000000000002')
            work['downloads']['video']['file']='../../video.mp4'; data.write_text(json.dumps([work]),encoding='utf-8')
            with self.assertRaises(ValueError):subtitle_video_input(data,root,work['aweme_id'])

    def test_failure_is_partial_and_never_deletes_primary(self):
        args=self.args('--subtitles','--subtitle-region','0,.7,1,.8')
        with patch('run_foundation.subtitle_video_input',side_effect=ValueError('private URL')):
            result=run_subtitle_stage(args,Path('works.json'),Path('delivery'))
        self.assertEqual(result['exit_code'],3); self.assertEqual(result['state'],'failed')
        self.assertNotIn('private URL',json.dumps(result))

    def test_all_keeps_primary_and_packages_partial_when_ocr_fails(self):
        with temporary() as tmp:
            delivery=tmp/'delivery'; preview=tmp/'preview'; source=tmp/'scripts'; source.mkdir()
            (source/'build_foundation_workbooks.py').write_text('# synthetic',encoding='utf-8')
            args=self.args('--subtitles','--subtitle-region','0,.7,1,.8','--skip-comments','--zip')
            args.out=str(delivery);args.profile_dir=str(tmp/'profile');args.preview_dir=str(preview)
            def browser_stage(works, comments, trace, **options):
                Path(works.out).mkdir(parents=True)
                (Path(works.out)/'works.json').write_text('[]',encoding='utf-8')
                (delivery/'03_作品素材').mkdir();(delivery/'03_作品素材'/'kept.mp4').write_bytes(b'synthetic media')
                return 0,0
            def builder(*unused,**kwargs):
                for name in ['01_作品清单.xlsx','02_评论明细.xlsx','04_采集说明.md']:(delivery/name).write_text('synthetic',encoding='utf-8')
                (preview/'workbook_qa.json').write_text('{}',encoding='utf-8')
                return SimpleNamespace(returncode=0)
            with patch('run_foundation.package_directory',return_value={'zip':'synthetic.zip'}) as package:
                self.assertEqual(run_all(args,source,runner=builder,browser_stage_runner=browser_stage),3)
                package.assert_called_once()
            self.assertEqual((delivery/'03_作品素材'/'kept.mp4').read_bytes(),b'synthetic media')
            manifest=json.loads((delivery/'data'/'foundation_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['works_exit_code'],0);self.assertEqual(manifest['subtitles']['state'],'failed')
            self.assertEqual(manifest['status'],'partial')

if __name__=='__main__': unittest.main()
