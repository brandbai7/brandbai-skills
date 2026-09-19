"""Bounded public product snapshots; no requests, inferred IDs or analysis."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

PRIVATE = re.compile(r"收货|配送至|送至|收件|联系人|订单|手机|电话|地址|cookie|bearer|token|signature|[\w.+-]+@[\w.-]+\.[a-z]{2,}|1[3-9]\d{9}", re.I)
ID = re.compile(r"card-[A-Za-z0-9_-]{1,64}\Z")
LIST_ID = re.compile(r"list-[A-Za-z0-9_-]{1,70}\Z")


def public_url(value, kind="product"):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\x00-\x1f<>"\\]', value):
        raise ValueError("invalid product URL")
    u = urlsplit(value)
    if u.scheme != "https" or u.username or u.password or u.port or u.fragment:
        raise ValueError("invalid product URL")
    if kind == "image":
        if not re.search(r"(^|\.)(ecombdimg\.com|detailpage\.byteimg\.com|douyinpic\.com)\Z", u.hostname or "") or re.search(r"avatar|qrcode|qr[-_]?code|girdle|second_page|priority|/common/|shop_", u.path, re.I) or u.query:
            raise ValueError("unsupported public product image")
    else:
        if u.hostname not in {"haohuo.jinritemai.com", "e.ghaohuo.com", "haohuo.snssdk.com"} or not re.fullmatch(r"/(views/product/(detail|item2)|ecommerce/trade/detail/index\.html)/?", u.path):
            raise ValueError("unsupported public product URL")
        query = parse_qs(u.query, keep_blank_values=True)
        if set(query) != {"id"} or len(query["id"]) != 1 or not re.fullmatch(r"\d{5,30}", query["id"][0]):
            raise ValueError("product URL may contain only a public item id")
    return value


def clean_text(value, limit=300):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or re.search(r"[\x00-\x1f]|https?://", value, re.I) or PRIVATE.search(value):
        raise ValueError("invalid public product text")
    return value.strip() or None


def text_list(value, count, length):
    if not isinstance(value, list) or len(value) > count:
        raise ValueError("product text list exceeds limit")
    return [v for v in (clean_text(item, length) for item in value) if v]


def card_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("invalid card observation id")
    return value


def validate_snapshot(value, *, detail=False, listing=False, standalone=False):
    if standalone:
        detail = True
    shared = {"product_title", "product_url", "shop_name", "offer_texts", "images", "identity_status", "source", "fields_limited"}
    allowed = shared | ({"price_texts", "sku_groups", "parameter_texts", "completeness", "image_coverage", "sku_materials", "parameter_materials", "product_identity"} if standalone else
                       {"card_observation_id", "list_observation_id", "price_texts", "sku_groups", "parameter_texts", "association", "clicked_at_epoch_ms", "completeness"} if detail else
                        {"list_observation_id", "list_position", "explaining", "display_price"} if listing else {"card_observation_id", "visible", "display_price", "change_kind"})
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("unsupported product snapshot fields")
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > (480000 if standalone else 48000):
        raise ValueError("product snapshot exceeds byte limit")
    out = {key: value[key] for key in ("visible", "change_kind", "display_price") if key in value and not detail}
    from_list = listing or detail and "list_observation_id" in value
    if standalone:
        pass  # Explicit current-product selection, never a synthetic live event.
    elif from_list:
        ident = value.get("list_observation_id")
        if "card_observation_id" in value or not isinstance(ident, str) or not LIST_ID.fullmatch(ident):
            raise ValueError("invalid list observation id")
        out["list_observation_id"] = ident
    else:
        out["card_observation_id"] = card_id(value.get("card_observation_id"))
    out.update(product_title=clean_text(value.get("product_title")),
               product_url=public_url(value.get("product_url")),
               shop_name=clean_text(value.get("shop_name"), 80),
               offer_texts=text_list(value.get("offer_texts", []), 12, 300))
    if not out["product_title"] and (detail or listing):
        raise ValueError("detail title required")
    if listing:
        position, explaining = value.get("list_position"), value.get("explaining")
        if position is not None and (isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= 9999):
            raise ValueError("invalid visible list position")
        if explaining is not None and explaining is not True:
            raise ValueError("absence of explaining label must remain unknown")
        out.update(list_position=position, explaining=explaining)
    expected_identity = "public_product_link" if out["product_url"] else "unconfirmed"
    if value.get("identity_status") != expected_identity:
        raise ValueError("product identity must reflect public link availability")
    out["identity_status"] = expected_identity
    if standalone and 'product_identity' in value:
        from product_identity import validate_identity
        out['product_identity'] = validate_identity(value['product_identity'], product_url=out['product_url'], shop_name=out['shop_name'])
    source = "user_selected_current_product_panel" if standalone else "user_opened_live_product_panel" if detail else "live_visible_product_list" if listing else "live_visible_product_card"
    if value.get("source") != source:
        raise ValueError("unsupported product source")
    out["source"] = source
    if "fields_limited" in value:
        if not isinstance(value["fields_limited"], bool): raise ValueError("fields_limited must be a boolean")
        out["fields_limited"] = value["fields_limited"]
    images = value.get("images", [])
    full = standalone and 'image_coverage' in value
    if not isinstance(images, list) or len(images) > (200 if full else 40):
        raise ValueError("too many product images")
    out["images"] = []
    for image in images:
        kind = "unclassified_product_image" if detail else "list_image" if listing else "card_image"
        if not isinstance(image, dict) or set(image) != {"url", "kind"} or image['kind'] not in ({'product_main', 'product_detail', 'product_sku'} if full else {kind}) or not image["url"]:
            raise ValueError("invalid product image reference")
        out["images"].append({"url": public_url(image["url"], "image"), "kind": image['kind']})
    if full:
        from material_contract import validate_coverage
        out['image_coverage'] = validate_coverage(value['image_coverage'], out['images'])
    if standalone and 'sku_materials' in value:
        if not full: raise ValueError('SKU materials require full capture')
        from material_contract import validate_sku_materials
        out['sku_materials']=validate_sku_materials(value['sku_materials'],out['images'])
    if standalone and 'parameter_materials' in value:
        if not full: raise ValueError('parameter materials require full capture')
        from material_contract import validate_parameter_materials
        out['parameter_materials']=validate_parameter_materials(value['parameter_materials'])
    if not detail:
        out["display_price"] = clean_text(value.get("display_price"), 80)
        return out
    association = "fresh_panel_after_list_click" if from_list else "fresh_panel_after_card_click"
    if (not standalone and value.get("association") != association) or value.get("completeness") != "visible_snapshot_only":
        raise ValueError("unsupported detail association")
    if not standalone:
        clicked = value.get("clicked_at_epoch_ms")
        if isinstance(clicked, bool) or not isinstance(clicked, (int, float)) or not 0 < clicked < 1e15:
            raise ValueError("invalid product click time")
        out.update(association=value["association"], clicked_at_epoch_ms=clicked)
    out.update(completeness=value["completeness"],
               price_texts=text_list(value.get("price_texts", []), 12, 80),
               parameter_texts=text_list(value.get("parameter_texts", []), 40, 280))
    groups = value.get("sku_groups", [])
    if not isinstance(groups, list) or len(groups) > 12:
        raise ValueError("too many visible specification groups")
    out["sku_groups"] = []
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"name", "options"} or not isinstance(group["options"], list) or len(group["options"]) > 40:
            raise ValueError("invalid visible specification group")
        name = clean_text(group["name"], 80)
        options = []
        for option in group["options"]:
            if not isinstance(option, dict) or set(option) != {"value", "selected"} or not isinstance(option["selected"], bool):
                raise ValueError("invalid visible specification option")
            val = clean_text(option["value"], 280)
            if not val:
                raise ValueError("empty specification option")
            options.append({"value": val, "selected": option["selected"]})
        if not name or not options:
            raise ValueError("empty specification group")
        out["sku_groups"].append({"name": name, "options": options})
    return out


def check_detail_binding(events):
    """Validate same collector/card and temporal provenance, not SKU identity."""
    cards = {}
    for event in sorted(events, key=lambda e: (e["observed_at_epoch_ms"], e["sequence"])):
        data = event["payload"]
        ident = data.get("card_observation_id") or data.get("list_observation_id")
        key = (event["collector_session_id"], ident)
        if ident and (event["event_type"] == "product_state" and data.get("visible") or event["event_type"] == "product_list_item"):
            cards[key] = event
        if event["event_type"] != "product_detail":
            continue
        card = cards.get(key)
        if not card or card["room_url"] != event["room_url"] or not card["observed_at_epoch_ms"] <= data["clicked_at_epoch_ms"] <= event["observed_at_epoch_ms"] <= data["clicked_at_epoch_ms"] + 10000:
            raise ValueError("product detail has no matching recent card observation")
        if (card["event_type"] == "product_list_item") != ("list_observation_id" in data):
            raise ValueError("product detail source kind mismatch")
        source = card["payload"]
        for field in ("product_url", "shop_name"):
            if source.get(field) and data.get(field) and source[field] != data[field]:
                raise ValueError("product detail identity conflict")
        prefix = re.sub(r"(?:…+|\.{3})\s*$", "", source.get("product_title") or "").strip()
        full = data.get("product_title") or ""
        if len(prefix) < 8 or not (full == prefix or (source.get("product_title") != prefix and full.startswith(prefix))):
            raise ValueError("product detail title conflict")


def write_product_evidence(root: Path, events):
    products = [e for e in events if e["event_type"] in {"product_state", "product_detail", "product_list_item"}]
    if not products:
        return
    products.sort(key=lambda e: (e["observed_at_epoch_ms"], e["collector_session_id"], e["sequence"]))
    lines = ["# 商品页面原始观察（不是完整商品资料）", "", "此文件保留按浏览器观察时间排列的兼容视图。弹窗商品请优先看 06_弹窗商品 中的概览与时间记录；这里的商品列表和手动打开的详情不能视为弹窗。商品详情是稍后打开时的快照，不代表弹窗当时的 SKU、价格或权益；未取得的资料保持未知。这里的图片只是公开链接；随录制包保存的卡片缩略图以 06_弹窗商品/缩略图下载清单.json 为准。", ""]
    def shown(v):
        return str(v or "暂未取得").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]").replace("`", "\\`")
    for e in products:
        p = e["payload"]
        detail = e["event_type"] == "product_detail"
        listing = e["event_type"] == "product_list_item"
        label = ("从商品列表打开的详情" if p.get("list_observation_id") else "从弹窗打开的商品详情") if detail else "商品列表可见快照（不是弹窗事件）" if listing else {"baseline_visible": "首次看到商品卡", "restored_visible": "商品卡再次可见", "temporarily_not_visible": "商品卡暂时不可见", "visible_info_changed": "商品卡展示信息变化", "visible_product_changed": "商品卡可见标识变化"}.get(p.get("change_kind"), "商品卡状态")
        offset = e.get("recording_offset_seconds")
        lines += [f"## {offset if offset is not None else '未知'} 秒 · {label}", "", f"观察时间：{e['observed_at']}；录制窗口内：{'是' if e['within_recording_window'] else '否'}。", "", f"商品：{shown(p.get('product_title'))}", "", f"展示价：{shown(' / '.join(p.get('price_texts', [])) if detail else p.get('display_price'))}", "", f"店铺：{shown(p.get('shop_name'))}", "", f"权益原文：{shown(' / '.join(p.get('offer_texts', [])))}", ""]
        if p.get("product_url"):
            lines += [f"[公开商品链接](<{p['product_url']}>)", ""]
        if listing:
            lines += [f"列表序号：{p.get('list_position') or '暂未取得'}；讲解标注：{'页面显示讲解中' if p.get('explaining') else '未看到明确标注，不推断讲解状态'}。列表序号不是商品 ID，也不证明上架、弹窗或主播口播。", ""]
        if p.get("fields_limited"):
            lines += ["页面资料较多，本次仅保留受限快照，未收齐全部可见字段。", ""]
        for group in p.get("sku_groups", []):
            lines += [f"{shown(group['name'])}：" + " / ".join(shown(o['value']) + ("（页面明确选中）" if o["selected"] else "") for o in group["options"]), ""]
        if p.get("parameter_texts"):
            lines += ["参数原文：" + " / ".join(shown(v) for v in p["parameter_texts"]), ""]
        for i, image in enumerate(p.get("images", []), 1):
            lines += [f"[图片链接 {i}](<{image['url']}>)", ""]
        lines += [f"资料关联：{p.get('card_observation_id') or p.get('list_observation_id') or '旧版未记录'}；商品身份：{'公开链接可核对' if p.get('product_url') else '尚未取得稳定标识，不跨商品合并'}。", ""]
    files = {root / "data" / "product_observations.jsonl": "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in products),
             root / "04_商品资料.md": "\n".join(lines)}
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
