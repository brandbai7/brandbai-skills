"""Common public identity envelope. Unknown IDs stay null; titles never join packages."""
from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, urlsplit

FIELDS = {'platform', 'product_id', 'product_url', 'shop_id', 'shop_name', 'product_ref',
          'identity_status', 'product_id_source', 'shop_id_source', 'source_room_id',
          'source_room_url', 'catalog_position', 'catalog_observed_at_epoch_ms', 'observed_at_epoch_ms'}
ID = re.compile(r'\d{5,30}\Z')
OBSERVATION = re.compile(r'douyin:observation:[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\Z')


def public_id(value):
    if value is None or value == '': return None
    if not isinstance(value, str) or not ID.fullmatch(value): raise ValueError('invalid public identity')
    return value


def build_identity(*, room_url, observed_at, product_url=None, product_id=None, shop_name=None,
                   shop_id=None, product_ref=None, scope='unconfirmed', catalog_position=None,
                   catalog_observed_at=None, id_source=None, shop_id_source=None):
    from product_evidence import public_url as clean_url, clean_text
    from material_contract import timestamp
    if not isinstance(room_url, str) or not re.fullmatch(r'https://live\.douyin\.com/\d{1,30}', room_url):
        raise ValueError('invalid identity room')
    product_url = clean_url(product_url)
    product_id, shop_id = public_id(product_id), public_id(shop_id)
    linked = parse_qs(urlsplit(product_url).query)['id'][0] if product_url else None
    if linked and product_id and linked != product_id: raise ValueError('conflicting product identity')
    product_id = product_id or linked
    if product_id:
        expected = 'douyin:product:' + product_id
        if product_ref and product_ref != expected: raise ValueError('product reference mismatch')
        product_ref, scope = expected, 'verified'
        id_source = id_source or ('public_product_link' if linked else 'visible_dom_attribute')
        if id_source not in {'public_product_link', 'visible_dom_attribute'}: raise ValueError('unproven product identity')
        if id_source == 'public_product_link' and not linked: raise ValueError('missing product link evidence')
    else:
        product_ref = product_ref or 'douyin:observation:' + str(uuid.uuid4())
        if not OBSERVATION.fullmatch(product_ref): raise ValueError('unconfirmed reference must be an observation')
        if scope not in {'panel_bound', 'unconfirmed'}: raise ValueError('unproven product identity')
        id_source = 'not_observed'
    if catalog_position is not None and (type(catalog_position) is not int or not 1 <= catalog_position <= 9999):
        raise ValueError('invalid catalog position')
    if (catalog_position is None) != (catalog_observed_at is None): raise ValueError('catalog provenance required')
    return dict(platform='douyin', product_id=product_id, product_url=product_url, shop_id=shop_id,
                shop_name=clean_text(shop_name, 80), product_ref=product_ref, identity_status=scope,
                product_id_source=id_source, shop_id_source='visible_dom_attribute' if shop_id else 'not_observed',
                source_room_id=room_url.rsplit('/', 1)[-1], source_room_url=room_url,
                catalog_position=catalog_position, catalog_observed_at_epoch_ms=timestamp(catalog_observed_at) if catalog_observed_at else None,
                observed_at_epoch_ms=timestamp(observed_at))


def validate_identity(value, *, room_url=None, product_url=None, shop_name=None):
    if not isinstance(value, dict) or set(value) != FIELDS or value['platform'] != 'douyin':
        raise ValueError('invalid product identity fields')
    result = build_identity(room_url=value['source_room_url'], observed_at=value['observed_at_epoch_ms'],
        product_url=value['product_url'], product_id=value['product_id'], shop_name=value['shop_name'],
        shop_id=value['shop_id'], product_ref=value['product_ref'], scope=value['identity_status'],
        catalog_position=value['catalog_position'], catalog_observed_at=value['catalog_observed_at_epoch_ms'],
        id_source=value['product_id_source'], shop_id_source=value['shop_id_source'])
    if result != value: raise ValueError('product identity evidence mismatch')
    if room_url and result['source_room_url'] != room_url: raise ValueError('product identity room mismatch')
    if product_url and result['product_url'] != product_url: raise ValueError('product identity URL mismatch')
    if shop_name and result['shop_name'] and shop_name != result['shop_name']: raise ValueError('product identity shop mismatch')
    return result


def same_product(left, right):
    """Stable IDs may join later downloads; observations only join the same live panel lease."""
    if not left or not right: return False
    if left['shop_id'] and right['shop_id'] and left['shop_id'] != right['shop_id']: return False
    if left['product_id'] or right['product_id']:
        return bool(left['product_id'] and left['product_id'] == right['product_id'])
    return (left['identity_status'] == right['identity_status'] == 'panel_bound'
            and left['product_ref'] == right['product_ref'] and left['source_room_url'] == right['source_room_url'])


def identity_note(identity):
    return ('商品 ID：' + (identity['product_id'] or '未取得，不能凭同名跨页面自动关联') + '。\n\n'
            + '关联标识：' + identity['product_ref'] + '。本地观察标识不是平台商品 ID。\n\n')
