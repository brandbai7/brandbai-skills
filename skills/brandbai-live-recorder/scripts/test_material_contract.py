import copy
import json
import threading
import unittest
import zipfile
from material_contract import validate_catalog, validate_coverage
from product_evidence import validate_snapshot
from product_downloads import build_product_package
from test_product_downloads import independent_request, PNG
from test_local_service import scratch_dir
from local_service import TaskManager, TaskStore, ServiceConflictError

def full_request():
    request=independent_request();p=request['snapshot']
    p['images']=[dict(url=f'https://p3.ecombdimg.com/{kind}-{i}.webp',kind='product_'+kind) for kind,count in [('main',5),('detail',3)] for i in range(count)]
    p['image_coverage']=dict(mode='single_product_full',main_expected=5,main_observed=5,detail_observed=3,
        main_complete=True,detail_complete=True,detail_end_evidence='explicit_end',stop_reason=None,fields_observed_at_epoch_ms=request['observed_at_epoch_ms'])
    return request

def catalog():
    return dict(rows=[dict(list_position=35,product_title='合成目录商品标题',display_price='券后¥29起',thumbnail='https://p3.ecombdimg.com/catalog.webp',
        product_url=None,explaining=None,observed_at_epoch_ms=1000)],complete=True,stop_reason=None)

class MaterialContractTests(unittest.TestCase):
    def parameter_request(self):
        p=full_request()['snapshot']
        p['sku_materials']=dict(mode='all_visible',status='not_observed',initial_selection=[],selection_restored=True,variants=[],stop_reason='sku_not_observed')
        p['parameter_materials']=dict(source='product_parameter_tabs',status='complete_visible_options',option_count=2,
            initial_selection='套餐一',selection_restored=True,stop_reason=None,variants=[dict(label=f'套餐{label}',state='observed',reason=None,
                components=[dict(name='合成产品',quantity_text=f'x {i}',parameters=[dict(name='容量',value=f'{i*10}ml')])],observed_at_epoch_ms=1000) for i,label in enumerate(['一','二'],1)])
        return p

    def test_parameter_content_has_own_schema_without_transaction_claims(self):
        p=self.parameter_request()
        self.assertEqual(validate_snapshot(p,standalone=True),p)
        for patch in [dict(price_texts=['¥99']),dict(sku_id='123456'),dict(image_urls=[]),dict(address='private')]:
            bad=copy.deepcopy(p);bad['parameter_materials']['variants'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_snapshot(bad,standalone=True)
        for patch in [dict(selection_restored=False),dict(option_count=3),dict(initial_selection=None),dict(stop_reason='options_changed')]:
            bad=copy.deepcopy(p);bad['parameter_materials'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_snapshot(bad,standalone=True)
        bad=copy.deepcopy(p);bad['parameter_materials']['variants'][0]['components'][0]['parameters'][0]['name']='收货地址'
        with self.assertRaises(ValueError):validate_snapshot(bad,standalone=True)
        with self.assertRaises(ValueError):validate_snapshot(p,detail=True)

    def test_parameter_export_preserves_options_without_fake_sku_images_or_prices(self):
        p=self.parameter_request();source=dict(event_type='product_material',payload=p,room_url='https://live.douyin.com/123456',observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertEqual(result['state'],'partial') # Purchasing SKU coverage is still unknown.
            with zipfile.ZipFile(result['archive']) as z:
                material=json.loads(z.read('商品资料.json'));manifest=json.loads(z.read('下载清单.json'));note=z.read('商品资料.md').decode()
                self.assertEqual(material['parameter_materials'],p['parameter_materials'])
                self.assertEqual(manifest['parameter_materials'],p['parameter_materials'])
                self.assertEqual(material['sku_image_mapping'],[])
                self.assertIn('套餐内容与参数',note);self.assertIn('10ml',note);self.assertIn('20ml',note)
                self.assertIn('未取得可核验的购买规格',note)

    def test_parameter_partial_cannot_promote_an_otherwise_complete_sku_package(self):
        p=self.sku_request();p['parameter_materials']=self.parameter_request()['parameter_materials']
        p['parameter_materials'].update(status='partial_visible_options',selection_restored=False,stop_reason='restore_unconfirmed')
        source=dict(event_type='product_material',payload=p,room_url='https://live.douyin.com/123456',observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertEqual(result['state'],'partial')

    def test_video_count_is_separate_and_does_not_claim_a_download(self):
        snapshot=full_request()['snapshot'];snapshot['image_coverage'].update(main_media_expected=6,main_video_observed=1,main_video_downloaded=False)
        self.assertEqual(validate_snapshot(snapshot,standalone=True),snapshot)
        for patch in (dict(main_video_downloaded=True),dict(main_video_observed=-1),dict(main_video_observed=7),dict(main_media_expected=True)):
            invalid=copy.deepcopy(snapshot);invalid['image_coverage'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_snapshot(invalid,standalone=True)
    def test_number_hints_are_not_identity_or_confirmed_numbers(self):
        from catalog_numbers import number_hints
        c=catalog();c['rows']=[dict(c['rows'][0],list_position=i+1 if i else None,
            explaining=None if i else True,product_title=f'合成目录第{i+1}件商品标题',
            thumbnail=f'https://p3.ecombdimg.com/catalog-{i}.webp') for i in range(16)]
        self.assertEqual(number_hints(c['rows'],True)[0]['candidate'],1)
        self.assertEqual(number_hints(c['rows'],False),{})
        for index,field,value in [(1,'list_position',1),(5,'list_position',None),(1,'explaining',True),(0,'explaining',None)]:
            bad=copy.deepcopy(c);bad['rows'][index][field]=value
            self.assertEqual(number_hints(bad['rows'],True),{})
        source=dict(event_type='product_catalog_material',payload=c,room_url='https://live.douyin.com/123456',observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertEqual(result['state'],'partial');self.assertEqual(result['image_saved'],16)
            with zipfile.ZipFile(result['archive']) as z:
                data=json.loads(z.read('商品编号目录.json'));row=data['rows'][0]
                self.assertIsNone(row['list_position']);self.assertIsNone(row['product_identity']['catalog_position']);self.assertIsNone(row['product_id'])
                self.assertEqual(row['number_inference']['candidate'],1)
                self.assertEqual(data['number_coverage'],dict(observed=15,missing=1,inferred=1,complete=False,reverified=0))
                self.assertEqual(json.loads(z.read('下载清单.json'))['number_coverage'],data['number_coverage'])
                self.assertIn('推测 1 号',z.read('商品编号目录.md').decode())
        self.assertNotIn('number_inference',c['rows'][0])

    def test_number_confirmation_requires_separate_observation_proof(self):
        c=catalog();c['rows'][0]['number_verification']=dict(method='same_row_reobserved',initial_position=None,
            initial_observed_at_epoch_ms=1000,confirmed_at_epoch_ms=2000)
        self.assertEqual(validate_catalog(c),c)
        for field,value in [('method','inferred'),('initial_position',1),('initial_observed_at_epoch_ms',999),('confirmed_at_epoch_ms',999)]:
            bad=copy.deepcopy(c);bad['rows'][0]['number_verification'][field]=value
            with self.assertRaises(ValueError):validate_catalog(bad)
        bad=copy.deepcopy(c);bad['rows'][0]['number_inference']={'candidate':35}
        with self.assertRaises(ValueError):validate_catalog(bad)
        source=dict(event_type='product_catalog_material',payload=c,room_url='https://live.douyin.com/123456',observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            with zipfile.ZipFile(result['archive']) as z:
                row=json.loads(z.read('商品编号目录.json'))['rows'][0]
                self.assertEqual(row['product_identity']['catalog_observed_at_epoch_ms'],2000)

    def sku_request(self):
        p=full_request()['snapshot']
        p['images'].append(dict(url='https://p3.ecombdimg.com/sku.png',kind='product_sku'))
        selection=[dict(name='尺寸规格',value='合成规格一')]
        p['sku_materials']=dict(mode='all_visible',status='complete_all_visible_skus',initial_selection=selection,
            selection_restored=True,stop_reason=None,variants=[dict(selection=selection,state='observed',reason=None,price_texts=['¥49.00'],
                image_urls=[i['url'] for i in p['images'] if i['kind']!='product_detail'],main_expected=5,main_complete=True,observed_at_epoch_ms=1000)])
        return p

    def test_sku_mapping_rejects_unowned_images_private_fields_and_false_complete(self):
        good=self.sku_request();good['sku_materials']['variants'][0].update(sku_id=None,sku_id_source='not_observed')
        self.assertEqual(validate_snapshot(good,standalone=True),good)
        for change in ({'selection_restored':False},{'initial_selection':[]},{'address':'private'}):
            bad=copy.deepcopy(good);bad['sku_materials'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError): validate_snapshot(bad,standalone=True)
        for change in ({'image_urls':['https://p3.ecombdimg.com/not-owned.webp']},{'price_texts':[]},{'selection':[dict(name='地址',value='禁止保存')]},{'main_complete':False}):
            bad=copy.deepcopy(good);bad['sku_materials']['variants'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_snapshot(bad,standalone=True)

    def test_sku_package_shared_images_map_to_real_files(self):
        p=self.sku_request();second=copy.deepcopy(p['sku_materials']['variants'][0]);second['selection'][0]['value']='合成规格二';p['sku_materials']['variants'].append(second)
        source=dict(event_type='product_material',payload=p,room_url='https://live.douyin.com/123456',observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertEqual(result['state'],'complete_observed');self.assertEqual(result['image_saved'],9)
            with zipfile.ZipFile(result['archive']) as z:
                data=json.loads(z.read('商品资料.json'));self.assertEqual(len(data['sku_image_mapping']),2)
                for row in data['sku_image_mapping']:
                    for image in row['images']:self.assertIn(image['file'],z.namelist())
                self.assertEqual(len([n for n in z.namelist() if n.startswith('规格图/')]),1)
        p['sku_materials'].update(status='partial_all_visible_skus',selection_restored=False,stop_reason='restore_unconfirmed')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertEqual(result['state'],'partial')

    def test_lottery_catalog_is_public_observation_not_transaction(self):
        c=catalog();c['rows'][0].update(entry_type='lottery',action_label='点击抽奖',display_price=None)
        self.assertEqual(validate_catalog(c),c)
        c['rows'][0]['action_label']='支付'
        with self.assertRaises(ValueError):validate_catalog(c)

    def test_full_snapshot_validates_counts_and_remains_standalone(self):
        p=full_request()['snapshot'];self.assertEqual(validate_snapshot(p,standalone=True),p)
        for change in ({'main_expected':4},{'main_observed':3},{'detail_end_evidence':'not_reached'},{'main_complete':1},{'stop_reason':'raw secret'}):
            bad=copy.deepcopy(p);bad['image_coverage'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_snapshot(bad,standalone=True)
        with self.assertRaises(ValueError):validate_snapshot(p,detail=True)

    def test_catalog_rejects_extra_fields_private_text_and_invented_number(self):
        good=catalog();self.assertEqual(validate_catalog(good),good)
        for change in ({'list_position':0},{'list_position':True},{'explaining':False},{'address':'private'},{'product_title':'收货地址禁止保存'},{'thumbnail':'https://127.0.0.1/a'}):
            bad=copy.deepcopy(good);bad['rows'][0].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_catalog(bad)

    def test_catalog_allows_missing_number_and_preserves_raw_price(self):
        c=catalog();c['rows'][0]['list_position']=None
        self.assertIsNone(validate_catalog(c)['rows'][0]['list_position'])
        self.assertEqual(validate_catalog(c)['rows'][0]['display_price'],'券后¥29起')

    def test_main_detail_files_and_package_counts_match(self):
        request=full_request();updates=[]
        source=dict(event_type='product_material',payload=request['snapshot'],room_url=request['room_url'],observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            result=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG,progress=updates.append)
            self.assertEqual(result['state'],'complete_observed');self.assertEqual(result['image_saved'],8)
            self.assertEqual(updates[0]['image_total'],8);self.assertEqual(updates[-1]['state'],'running');self.assertEqual(updates[-1]['phase'],'packaging')
            with zipfile.ZipFile(result['archive']) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len([n for n in z.namelist() if n.startswith('主图/')]),5)
                self.assertEqual(len([n for n in z.namelist() if n.startswith('详情图/')]),3)

    def test_missing_coverage_stays_partial_even_all_observed_files_downloaded(self):
        request=full_request();request['snapshot']['image_coverage'].update(main_expected=6,main_complete=False,stop_reason='coverage_unconfirmed')
        with scratch_dir() as root:
            result=build_product_package(root,[dict(event_type='product_material',payload=request['snapshot'],room_url=request['room_url'],observed_at='2026-01-01T00:00:00+08:00')],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertEqual(result['image_saved'],8);self.assertEqual(result['state'],'partial')

    def test_catalog_outputs_versions_and_never_product_details(self):
        source=dict(event_type='product_catalog_material',payload=catalog(),room_url='https://live.douyin.com/123456',observed_at='2026-01-01T00:00:00+08:00')
        with scratch_dir() as root:
            a=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            b=build_product_package(root,[source],stop=threading.Event(),fetcher=lambda *a,**k:PNG)
            self.assertNotEqual(a['output_dir'],b['output_dir'])
            with zipfile.ZipFile(a['archive']) as z:
                data=json.loads(z.read('商品编号目录.json'));self.assertEqual(data['rows'][0]['list_position'],35)
                self.assertNotIn('商品资料.json',z.namelist());self.assertNotIn('sku_groups',str(data))

    def test_catalog_endpoint_idempotency_without_recording(self):
        req=independent_request();req.pop('snapshot');req['catalog']=catalog()
        with scratch_dir() as root:
            manager=TaskManager(store=TaskStore(root/'state.sqlite3'),output_root=root/'out');observations=[]
            manager.product_downloads.runner=lambda path,events,**kw:(observations.extend(events) or {'state':'complete_observed'})
            manager.download_current_product(req);manager.product_downloads.thread.join(3);manager.download_current_product(req)
            self.assertEqual(manager.list(),[]);self.assertEqual(len(observations),1)
            self.assertEqual(observations[0]['event_type'],'product_catalog_material')
            req['catalog']['rows'][0]['list_position']=3
            with self.assertRaises(ServiceConflictError):manager.download_current_product(req)

if __name__=='__main__':unittest.main()
