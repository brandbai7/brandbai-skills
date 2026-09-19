"""Standalone material contracts; never accept arbitrary page/checkout dictionaries."""
import json
import math
import re
from urllib.parse import urlsplit

def complete_crop_tiles(images):
    groups = {}
    for image in images:
        if image['kind'] != 'product_detail': continue
        path = urlsplit(image['url']).path
        size = re.search(r'_www(\d+)-(\d+)', path)
        crop = re.search(r'~tplv-[^/]*?-xy:(\d+):(\d+):(\d+):(\d+)', path)
        if not size or not crop: continue
        width, height = map(int, size.groups()); left, top, right, bottom = map(int, crop.groups())
        if width < 100 or height < 1000: continue
        if left != 0 or right != width or not 0 <= top < bottom <= height: return False
        groups.setdefault(path.split('~tplv-')[0], []).append((top,bottom,height))
    for tiles in groups.values():
        end = 0
        for top,bottom,height in sorted(tiles):
            if top > end: return False
            end = max(end,bottom)
        if end != tiles[0][2]: return False
    return True

STOP_REASONS = {None, 'user_stopped', 'page_hidden', 'time_limit', 'image_limit',
                'coverage_unconfirmed', 'item_limit', 'end_unconfirmed', 'bytes_limit', 'detail_stalled'}


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1e15:
        raise ValueError('invalid observation time')
    return value


def validate_coverage(value, images):
    fields = {'mode', 'main_expected', 'main_observed', 'detail_observed', 'main_complete',
              'detail_complete', 'detail_end_evidence', 'stop_reason', 'fields_observed_at_epoch_ms'}
    media_fields = {'main_media_expected', 'main_video_observed', 'main_video_downloaded'}
    if not isinstance(value, dict) or not fields <= set(value) or set(value)-fields-media_fields or value['mode'] != 'single_product_full':
        raise ValueError('invalid material coverage')
    if media_fields & set(value):
        if not media_fields <= set(value): raise ValueError('incomplete media counts')
        total, videos = value['main_media_expected'], value['main_video_observed']
        if total is not None and (type(total) is not int or not 1 <= total <= 200): raise ValueError('invalid media count')
        if type(videos) is not int or not 0 <= videos <= 200 or total is not None and videos > total:
            raise ValueError('invalid video count')
        if value['main_video_downloaded'] is not False: raise ValueError('video download unsupported')
        if total is not None and value['main_expected'] is not None and value['main_expected'] + videos > total:
            raise ValueError('media coverage mismatch')
    for field in ('main_expected', 'main_observed', 'detail_observed'):
        n = value[field]
        if field == 'main_expected' and n is None: continue
        if type(n) is not int or not (1 if field == 'main_expected' else 0) <= n <= 200:
            raise ValueError('invalid image count')
    for field in ('main_complete', 'detail_complete'):
        if type(value[field]) is not bool: raise ValueError('invalid coverage flag')
    if value['stop_reason'] not in STOP_REASONS or value['detail_end_evidence'] not in {'not_reached', 'explicit_end', 'stable_scroll_boundary'}:
        raise ValueError('invalid collection boundary')
    timestamp(value['fields_observed_at_epoch_ms'])
    for label in ('main', 'detail'):
        count = len({i['url'] for i in images if i['kind'] == 'product_' + label})
        if value[label + '_observed'] != count: raise ValueError('image count mismatch')
    if value['main_complete'] and (not value['main_expected'] or value['main_expected'] != value['main_observed']):
        raise ValueError('main coverage unproven')
    if value['detail_complete'] and value['detail_end_evidence'] == 'not_reached':
        raise ValueError('detail boundary unproven')
    if value['detail_complete'] and not value['detail_observed'] and value['detail_end_evidence'] != 'explicit_end':
        raise ValueError('empty detail coverage unproven')
    result = dict(value)
    if result['detail_complete'] and not complete_crop_tiles(images):
        result.update(detail_complete=False, stop_reason='coverage_unconfirmed')
    return result


def validate_catalog(value):
    from product_evidence import clean_text, public_url
    if not isinstance(value, dict) or set(value) != {'rows', 'complete', 'stop_reason'}:
        raise ValueError('invalid catalog')
    if type(value['complete']) is not bool or value['stop_reason'] not in STOP_REASONS:
        raise ValueError('invalid catalog coverage')
    if value['complete'] != (value['stop_reason'] is None): raise ValueError('catalog coverage mismatch')
    rows = value['rows']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000 or len(json.dumps(value, ensure_ascii=False).encode()) > 850000:
        raise ValueError('catalog size limit')
    result = []
    fields = {'list_position', 'product_title', 'display_price', 'thumbnail', 'product_url', 'explaining', 'observed_at_epoch_ms'}
    for row in rows:
        if not isinstance(row, dict) or set(row) - fields - {'entry_type','action_label','product_identity','number_verification'} or not fields <= set(row): raise ValueError('invalid catalog row')
        n = row['list_position']
        if n is not None and (type(n) is not int or not 1 <= n <= 9999): raise ValueError('invalid product number')
        if row['explaining'] is not None and row['explaining'] is not True: raise ValueError('explaining must remain unknown')
        title = clean_text(row['product_title'])
        if not title: raise ValueError('catalog title missing')
        result.append(dict(list_position=n, product_title=title, display_price=clean_text(row['display_price'],80),
            thumbnail=public_url(row['thumbnail'],'image'), product_url=public_url(row['product_url']),
            explaining=row['explaining'], observed_at_epoch_ms=timestamp(row['observed_at_epoch_ms'])))
        if 'product_identity' in row:
            from product_identity import validate_identity
            identity=validate_identity(row['product_identity'], product_url=result[-1]['product_url'])
            if identity['catalog_position'] != n: raise ValueError('catalog identity position mismatch')
            result[-1]['product_identity']=identity
        if 'number_verification' in row:
            proof = row['number_verification']
            if (not isinstance(proof, dict) or set(proof) != {'method','initial_position','initial_observed_at_epoch_ms','confirmed_at_epoch_ms'}
                    or proof['method'] != 'same_row_reobserved' or proof['initial_position'] is not None or n is None):
                raise ValueError('invalid number verification')
            first, confirmed = timestamp(proof['initial_observed_at_epoch_ms']), timestamp(proof['confirmed_at_epoch_ms'])
            if first != row['observed_at_epoch_ms'] or confirmed < first: raise ValueError('invalid number observation time')
            if 'product_identity' in row and row['product_identity']['catalog_observed_at_epoch_ms'] != confirmed:
                raise ValueError('number identity time mismatch')
            result[-1]['number_verification'] = dict(proof)
        if 'entry_type' in row or 'action_label' in row:
            if row.get('entry_type') not in {'product','lottery','unavailable'}: raise ValueError('invalid catalog entry type')
            action=clean_text(row.get('action_label'),20)
            if action not in {None,'去抢购','领券抢购','立即抢购','点击抽奖','参与抽奖','已售罄','暂时售罄','已下架'}: raise ValueError('invalid catalog action')
            if row['entry_type']=='lottery' and action not in {'点击抽奖','参与抽奖'}: raise ValueError('unproven lottery entry')
            result[-1].update(entry_type=row['entry_type'],action_label=action)
    return dict(rows=result, complete=value['complete'], stop_reason=value['stop_reason'])


def validate_sku_materials(value, images):
    from product_evidence import clean_text, text_list, public_url
    fields={'mode','status','initial_selection','selection_restored','variants','stop_reason'}
    if not isinstance(value,dict) or set(value)!=fields or value['mode']!='all_visible': raise ValueError('invalid SKU collection')
    states={'complete_all_visible_skus','partial_all_visible_skus','not_observed'}
    reasons={None,'sku_not_observed','selection_unconfirmed','sku_limit','restore_unconfirmed','sku_coverage_unconfirmed','sku_inventory_changed'} | STOP_REASONS
    if value['status'] not in states or value['stop_reason'] not in reasons or type(value['selection_restored']) is not bool: raise ValueError('invalid SKU coverage')
    def selection(rows):
        if not isinstance(rows,list) or len(rows)>12: raise ValueError('invalid SKU selection')
        result=[]
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'name','value'}: raise ValueError('invalid SKU option')
            name,val=clean_text(row['name'],80),clean_text(row['value'],280)
            if not name or not val or name in [r['name'] for r in result]: raise ValueError('ambiguous SKU selection')
            result.append(dict(name=name,value=val))
        return result
    initial=selection(value['initial_selection'])
    variants=value['variants']
    if not isinstance(variants,list) or len(variants)>40: raise ValueError('SKU limit exceeded')
    allowed_urls={i['url'] for i in images if i['kind'] in {'product_main','product_sku'}}
    clean=[]; seen=set()
    for row in variants:
        required={'selection','state','reason','price_texts','image_urls','main_expected','main_complete','observed_at_epoch_ms'}
        if not isinstance(row,dict) or not required<=set(row) or set(row)-required-{'sku_id','sku_id_source'}: raise ValueError('invalid SKU material')
        from product_identity import public_id
        sku_id=public_id(row.get('sku_id'))
        if row.get('sku_id_source','not_observed') != ('visible_dom_attribute' if sku_id else 'not_observed') or sku_id and row['state']!='observed': raise ValueError('unproven SKU identity')
        options=selection(row['selection']); key=json.dumps(options,ensure_ascii=False,sort_keys=True)
        if not options or key in seen: raise ValueError('duplicate SKU selection')
        seen.add(key)
        if row['state'] not in {'observed','unavailable','failed'} or row['reason'] not in {None,'option_disabled','selection_unconfirmed','sku_media_unconfirmed','sku_price_unconfirmed'} or type(row['main_complete']) is not bool: raise ValueError('invalid SKU state')
        urls=row['image_urls']
        if not isinstance(urls,list) or len(urls)>200 or len(set(urls))!=len(urls): raise ValueError('invalid SKU image list')
        urls=[public_url(u,'image') for u in urls]
        if set(urls)-allowed_urls: raise ValueError('SKU image missing from assets')
        if row['state']=='observed' and not urls: raise ValueError('SKU images unproven')
        if row['state']!='observed' and (urls or row['main_complete']): raise ValueError('unconfirmed SKU mapping')
        expected=row['main_expected']
        if expected is not None and (type(expected) is not int or not 1<=expected<=200): raise ValueError('invalid SKU main count')
        main_urls={i['url'] for i in images if i['kind']=='product_main'}
        if row['main_complete'] and (not expected or len(set(urls)&main_urls)!=expected): raise ValueError('SKU main coverage unproven')
        clean.append(dict(selection=options,state=row['state'],reason=row['reason'],price_texts=text_list(row['price_texts'],12,80),sku_id=sku_id,sku_id_source='visible_dom_attribute' if sku_id else 'not_observed',
            image_urls=urls,main_expected=expected,main_complete=row['main_complete'],observed_at_epoch_ms=timestamp(row['observed_at_epoch_ms'])))
    if value['status']=='complete_all_visible_skus' and (not clean or not initial or not value['selection_restored'] or value['stop_reason']
        or not any(r['state']=='observed' for r in clean) or any(r['state']!='unavailable' and (r['state']!='observed' or r['reason'] or not r['main_complete'] or not r['price_texts']) for r in clean)):
        raise ValueError('SKU coverage unproven')
    return dict(mode='all_visible',status=value['status'],initial_selection=initial,selection_restored=value['selection_restored'],variants=clean,stop_reason=value['stop_reason'])


def validate_parameter_materials(value):
    """Public bundle composition tabs, deliberately separate from transactional SKUs."""
    from product_evidence import clean_text
    fields={'source','status','option_count','initial_selection','selection_restored','variants','stop_reason'}
    if not isinstance(value,dict) or set(value)!=fields or value['source']!='product_parameter_tabs':
        raise ValueError('invalid parameter collection')
    reasons={None,'selection_unconfirmed','option_limit','options_changed','restore_unconfirmed','content_unconfirmed'}|STOP_REASONS
    if value['status'] not in {'complete_visible_options','partial_visible_options'} or value['stop_reason'] not in reasons:
        raise ValueError('invalid parameter status')
    count=value['option_count']
    if type(count) is not int or not 1<=count<=1000 or type(value['selection_restored']) is not bool:
        raise ValueError('invalid parameter count')
    initial=clean_text(value['initial_selection'],280)
    variants=value['variants']
    if not isinstance(variants,list) or len(variants)>min(40,count):raise ValueError('parameter option limit')
    clean=[];seen=set()
    for row in variants:
        if not isinstance(row,dict) or set(row)!={'label','state','reason','components','observed_at_epoch_ms'}:
            raise ValueError('invalid parameter option')
        label=clean_text(row['label'],280)
        if not label or label in seen:raise ValueError('duplicate parameter option')
        seen.add(label)
        if row['state'] not in {'observed','failed','unavailable'}:raise ValueError('invalid parameter state')
        expected={ 'observed':{None}, 'failed':{'selection_unconfirmed','content_unconfirmed','content_limit'}, 'unavailable':{'option_disabled'} }
        if row['reason'] not in expected[row['state']]:raise ValueError('parameter reason mismatch')
        components=row['components']
        if not isinstance(components,list) or len(components)>20 or bool(components)!=(row['state']=='observed'):
            raise ValueError('unproven parameter content')
        entries=[]
        for component in components:
            if not isinstance(component,dict) or set(component)!={'name','quantity_text','parameters'}:raise ValueError('invalid parameter component')
            name=clean_text(component['name'],300);quantity=clean_text(component['quantity_text'],20)
            if not name or not quantity or not re.fullmatch(r'x\s*\d{1,6}',quantity,re.I):raise ValueError('invalid parameter component label')
            parameters=component['parameters']
            if not isinstance(parameters,list) or len(parameters)>40:raise ValueError('parameter field limit')
            pairs=[]
            for pair in parameters:
                if not isinstance(pair,dict) or set(pair)!={'name','value'}:raise ValueError('invalid parameter field')
                key,val=clean_text(pair['name'],40),clean_text(pair['value'],300)
                if not key or not val:raise ValueError('empty parameter field')
                pairs.append(dict(name=key,value=val))
            entries.append(dict(name=name,quantity_text=quantity,parameters=pairs))
        clean.append(dict(label=label,state=row['state'],reason=row['reason'],components=entries,observed_at_epoch_ms=timestamp(row['observed_at_epoch_ms'])))
    if value['status']=='complete_visible_options' and (not initial or initial not in seen or len(clean)!=count
        or not value['selection_restored'] or value['stop_reason'] or not any(r['state']=='observed' for r in clean)
        or any(r['state']=='failed' for r in clean)):raise ValueError('parameter coverage unproven')
    result=dict(value,initial_selection=initial,variants=clean)
    if len(json.dumps(result,ensure_ascii=False))>85000:raise ValueError('parameter byte limit')
    return result
