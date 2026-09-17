"""Synthetic cross-package identity contract; never uses customer output."""
import copy
import json
import threading
import unittest
import uuid
import zipfile
from datetime import datetime, timezone
from product_identity import build_identity, validate_identity, same_product
from product_downloads import build_product_package
from product_reviews import ProductReviewJobs
from test_product_reviews import request, row
from test_material_contract import full_request, catalog
from test_product_downloads import PNG
from test_local_service import scratch_dir
from local_service import TaskManager, TaskStore, ServiceInputError

ROOM='https://live.douyin.com/123456'
AT=1789460000000
def identity(**kw):
    return build_identity(**(dict(room_url=ROOM,observed_at=AT,product_id='123456789012345',shop_name='合成店')|kw))

class IdentityTests(unittest.TestCase):
    def test_stable_id_joins_later_download_not_title_or_number(self):
        a=identity(catalog_position=1,catalog_observed_at=AT)
        b=identity(catalog_position=2,catalog_observed_at=AT+10000,observed_at=AT+10000)
        self.assertTrue(same_product(a,b));self.assertEqual(validate_identity(a),a)
        self.assertFalse(same_product(a,identity(product_id='987654321012345')))
        self.assertFalse(same_product(identity(shop_id='111111'),identity(shop_id='222222')))

    def test_unknown_id_only_same_panel_observation_can_join(self):
        a=identity(product_id=None,scope='panel_bound')
        self.assertIsNone(a['product_id']);self.assertTrue(same_product(a,copy.deepcopy(a)))
        self.assertFalse(same_product(a,identity(product_id=None,scope='panel_bound')))
        self.assertFalse(same_product(a,identity()))
        with self.assertRaises(ValueError):identity(product_id='1号链接')
        with self.assertRaises(ValueError):identity(product_id=123456789012345)

    def test_conflicting_link_and_forged_provenance_rejected(self):
        with self.assertRaises(ValueError):identity(product_url='https://haohuo.jinritemai.com/views/product/detail?id=99999999')
        for patch in ({'identity_status':'panel_bound'},{'source_room_id':'999999'},{'product_id_source':'title'},
                      {'shop_id_source':'hidden_api'},{'address':'private'},{'product_ref':'douyin:product:999999'}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate_identity(identity()|patch)
        with self.assertRaises(ValueError):validate_identity(identity(),room_url='https://live.douyin.com/999999')

    def test_material_review_catalog_packages_share_real_id(self):
        req=full_request();p=req['snapshot'];p['shop_name']='合成店';p['product_identity']=identity()
        observation=dict(event_type='product_material',room_url=ROOM,observed_at=datetime.fromtimestamp(AT/1000,timezone.utc).isoformat(),payload=p)
        with scratch_dir() as root:
            material=build_product_package(root,[observation],stop=threading.Event(),fetcher=lambda *a,**kw:PNG)
            reviews=ProductReviewJobs(now=lambda:AT/1000)
            r=request();r['product'].update(product_id='123456789012345');r['product_identity']=identity()
            status=reviews.start(r,root)
            base=dict(lease=r['lease'],sequence=1,action='batch',rows=[row()],done_reason='',exhausted=False,empty_confirmed=False)
            reviews.accept(r['request_id'],base)
            status=reviews.accept(r['request_id'],base|dict(sequence=2,action='finish',rows=[],done_reason='run_budget'))
            c=catalog();c['rows'][0]['product_identity']=identity(catalog_position=35,catalog_observed_at=AT)
            directory=build_product_package(root,[observation|dict(event_type='product_catalog_material',payload=c)],stop=threading.Event(),fetcher=lambda *a,**kw:PNG)
            with zipfile.ZipFile(material['archive']) as a,zipfile.ZipFile(status['zip_path']) as b,zipfile.ZipFile(directory['archive']) as d:
                self.assertTrue(same_product(json.loads(a.read('商品身份.json')),json.loads(b.read('商品身份.json'))))
                review=json.loads(b.read('商品评价.jsonl'))
                self.assertEqual(review['product_id'],'123456789012345');self.assertIsNone(review['sku_id'])
                self.assertEqual(review['purchased_sku'],'历史款规格')
                self.assertEqual(json.loads(d.read('商品编号目录.json'))['rows'][0]['product_id'],review['product_id'])
            reviews.shutdown()

    def test_service_rejects_cross_room_identity_before_job(self):
        req=full_request();req['snapshot']['shop_name']='合成店';req['snapshot']['product_identity']=identity(room_url='https://live.douyin.com/999999')
        with scratch_dir() as root:
            manager=TaskManager(store=TaskStore(root/'db.sqlite3'),output_root=root/'out')
            with self.assertRaises(ServiceInputError):manager.download_current_product(req)
            self.assertFalse(manager._independent_products)

    def test_review_header_cannot_disagree_with_common_identity(self):
        r=request();r['product_identity']=identity()
        with scratch_dir() as root,self.assertRaises(ValueError):ProductReviewJobs(now=lambda:AT/1000).start(r,root)

if __name__=='__main__':unittest.main()
