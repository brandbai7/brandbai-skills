"""Collect public Tmall item facts and source-visible reviews in visible Chrome.

The collector uses a normal persistent Playwright Chrome context. It never
exports cookies, headers, browser profiles, signatures, or verification data.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from collector_core import (
    CollectionError,
    RunManifest,
    atomic_write_json,
    canonical_image_asset_key,
    canonical_item_url,
    choose_review_status,
    choose_product_completion_state,
    dedupe_preserve_order,
    derived_answer_id,
    derived_question_id,
    derived_review_id,
    extract_item_id,
    image_is_usable,
    image_content_status,
    is_platform_notice_image_url,
    media_request_url,
    navigation_item_url,
    normalize_price_candidates,
    is_usable_sku_option,
    normalize_item_targets,
    pseudonymize_author,
    pseudonymize_qa_author,
    read_jsonl_ids,
    safe_filename,
    sanitize_media_url,
    sanitize_transient_video_url,
    sku_mapping_status,
    sku_parameter_warnings,
    utc_now,
)


PRODUCT_SCRIPT = r"""
(requestedModules = ['overview']) => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const modules = new Set(requestedModules || ['overview']);
  const includeMainImages = modules.has('overview') || modules.has('main_images');
  const includeDetailImages = modules.has('detail_images');
  const includeVideo = modules.has('overview') || modules.has('video');
  const recommendationLabels = new Set(['看了又看','猜你喜欢','相关推荐','更多推荐','更多宝贝']);
  const pageTop = (element) => element?.getBoundingClientRect ? element.getBoundingClientRect().top + window.scrollY : Number.POSITIVE_INFINITY;
  const leafText = (root = document) => [...root.querySelectorAll('*')]
    .filter((el) => visible(el) && el.children.length === 0 && clean(el.textContent))
    .map((el) => ({el, text: clean(el.textContent)}));
  const exactVisibleText = (label) => [...document.querySelectorAll('*')]
    .filter((element) => visible(element) && clean(element.textContent) === label);
  const headingModuleRoot = (label) => {
    const candidates = exactVisibleText(label).map((element) => element.closest('[class*="tabDetailItem--"],section,[class*="module" i],[class*="detailContent" i]')).filter(Boolean);
    return candidates.sort((left, right) => right.querySelectorAll('img').length - left.querySelectorAll('img').length)[0] || null;
  };
  const moduleRoots = {
    main: document.querySelector('[class*="picGallery--"],[class*="galleryWrap" i],[class*="mainPic" i]'),
    parameters: document.querySelector('[class*="paramsInfoArea"]') || headingModuleRoot('参数信息'),
    detail: headingModuleRoot('图文详情')
  };
  const imageCandidates = (image) => {
    const srcset = clean(image?.getAttribute?.('srcset')).split(',').map((part) => clean(part).split(/\s+/)[0]).filter(Boolean);
    return [...new Set([
      image?.getAttribute?.('data-src'), image?.getAttribute?.('data-original'), image?.getAttribute?.('data-ks-lazyload'),
      image?.getAttribute?.('data-lazyload'), ...srcset.reverse(), image?.currentSrc, image?.src
    ].filter(Boolean))].filter((src) => /^(https?:)?\/\/(?:img|gw)\.alicdn\.com\//i.test(src));
  };
  const collectModuleImages = (root, kind) => root ? [...root.querySelectorAll('img')].map((img, index) => {
    const rect = img.getBoundingClientRect();
    return {
      index, src: imageCandidates(img)[0] || '', kind,
      width: Math.max(Number(img.naturalWidth || 0), Number(img.getAttribute('width') || 0), Math.round(rect.width || 0)),
      height: Math.max(Number(img.naturalHeight || 0), Number(img.getAttribute('height') || 0), Math.round(rect.height || 0)),
      context: clean(root.textContent).slice(0, 120)
    };
  }).filter((row) => row.src) : [];
  const detailStartTop = () => {
    const values = leafText().filter((row) => row.text === '图文详情').map((row) => pageTop(row.el)).filter(Number.isFinite);
    return values.length ? Math.min(...values) : Number.POSITIVE_INFINITY;
  };
  const recommendationBoundaryTop = (afterTop = 0) => {
    const values = leafText().filter((row) => recommendationLabels.has(row.text)).map((row) => pageTop(row.el))
      .filter((top) => Number.isFinite(top) && top > afterTop + 240);
    return values.length ? Math.min(...values) : Number.POSITIVE_INFINITY;
  };
  const isInsideRecommendationSurface = (element) => {
    if (!element?.closest) return false;
    if (element.closest('[class*="recommend" i],[class*="tb-pick" i],[class*="feeds" i],[class*="guess" i],[class*="waterfall" i],[class*="hotSell" i],[data-spm*="recommend" i],[data-spm*="rec" i]')) return true;
    const detailTop = detailStartTop();
    const boundary = recommendationBoundaryTop(Number.isFinite(detailTop) ? detailTop : 0);
    return Number.isFinite(boundary) && pageTop(element) >= boundary;
  };
  const isCurrentProductTradeElement = (element) => {
    if (!element?.closest) return false;
    if (element.closest('a[href*="item.htm"],a[href*="detail.tmall.com"]') || isInsideRecommendationSurface(element)) return false;
    if (element.closest('[class*="rightWrap--"],[class*="ItemHeadFixed--"],[class*="skuContent--"],[class*="buyBtn--"]')) return true;
    if (element.closest('[class*="detail" i],[class*="desc" i]')) return false;
    const top = pageTop(element);
    const detailTop = detailStartTop();
    const recommendationTop = recommendationBoundaryTop(Number.isFinite(detailTop) ? detailTop : 0);
    return top < Math.min(2200, detailTop, recommendationTop);
  };
  const leaves = leafText();
  const titleFromDocument = clean(document.title).replace(/[-_]tmall\.com.*$/i, '').replace(/-天猫.*$/i, '');
  const titleCandidates = [...document.querySelectorAll('h1,[class*="title" i],[class*="Title"]')]
    .filter(visible).map((el) => clean(el.textContent)).filter((text) => text.length >= 8 && text.length <= 220);
  const title = titleFromDocument || titleCandidates.sort((a,b) => b.length - a.length)[0] || '';
  const itemId = new URL(location.href).searchParams.get('id') || document.querySelector('[data-item]')?.getAttribute('data-item') || '';
  const skuId = new URL(location.href).searchParams.get('skuId') || '';

  const shopBoundary = Math.min(detailStartTop(), 2200);
  const shopLinks = leaves.filter((row) => /^.{1,36}(?:旗舰店|专卖店|专营店|企业店|官方店)$/.test(row.text)
    && pageTop(row.el) < shopBoundary && !isInsideRecommendationSurface(row.el)).map((row) => {
    const link = row.el.closest('a[href]');
    const trail = [row.el, row.el.parentElement, row.el.parentElement?.parentElement]
      .map((el) => typeof el?.className === 'string' ? el.className : '').join(' ');
    const href = link?.href ? link.href.split('?')[0].split('#')[0] : '';
    const score = (/(?:shop|store|seller)/i.test(trail) ? 4 : 0) + (/(?:shop|store)/i.test(href) ? 3 : 0)
      + (isCurrentProductTradeElement(row.el) ? 2 : 0) - Math.min(2, pageTop(row.el) / 1000);
    return {text: row.text, href, score};
  }).sort((left, right) => right.score - left.score);

  const labelValue = (label) => {
    const node = leaves.find((row) => row.text === label)?.el;
    if (!node) return '';
    for (const parent of [node.parentElement, node.parentElement?.parentElement, node.parentElement?.parentElement?.parentElement]) {
      if (!parent) continue;
      const parts = leafText(parent).map((row) => row.text).filter((text) => text !== label && text.length <= 160);
      if (parts.length) return parts[0];
    }
    return '';
  };
  const parameterLabels = [
    '品牌','系列','规格','净含量','包装方式','产地','省份','城市','保质期','储藏方法','生产日期',
    '厂名','厂址','厂家联系方式','生产许可证编号','产品标准号','配料表','食品添加剂','适用对象',
    '商品条形码','进口食品','口味','是否含糖','生鲜储存温度','原产国/地区'
  ];
  const parameters = parameterLabels.map((label) => ({name: label, value: labelValue(label)})).filter((row) => row.value);

  const skuRoots = leaves.filter((row) => /^(套餐类型|套餐|颜色分类|颜色|食品口味|口味|香味|商品规格|产品规格|规格|包装规格|净含量|尺寸|款式|型号|版本|数量组合|组合|适用阶段|尺码)$/.test(row.text)
    && row.el.closest('[class*="skuItem" i],[class*="labelWrap" i]'));
  const skuGroups = skuRoots.map(({el, text}) => {
    const root = el.closest('[class*="skuItemClip" i],[class*="skuItem" i]') || el.parentElement?.parentElement;
    const valueNodes = [...(root || el.parentElement).querySelectorAll('[class*="valueItemText--"]')].filter(visible);
    const values = (valueNodes.length ? valueNodes.map((node) => clean(node.textContent)) : leafText(root || el.parentElement).map((row) => row.text))
      .filter((value) => value !== text && value.length <= 80
        && !/^(?:[¥￥]?\d+(?:\.\d{1,2})?|[-+]|数量|有货|无货|已选)$/.test(value)
        && !/(?:点击查看大图|查看大图|查看详情|展开|收起|加入会员|开通会员|会员权益|立即领取|领取优惠|领券|加购|购物车|客服|咨询|分享)/.test(value));
    const selected = valueNodes.find((node) => node.closest('[class*="isSelected--"]'));
    return {name: text, values: [...new Set(values)].slice(0, 40), selected_value: clean(selected?.textContent)};
  }).filter((group) => group.values.length);

  const priceRoots = [...document.querySelectorAll('[class*="price" i],[id*="price" i],[class*="trade" i]')].filter(visible);
  const isProductTradePriceElement = (element) => {
    return isCurrentProductTradeElement(element)
      && Boolean(element.closest('[class*="highlightPrice--"],[class*="normalPrice--"],[class*="beltPrice--"],[class*="priceWrap--"]'));
  };
  const priceLeaves = leaves.filter((item) => {
    const pageTop = item.el.getBoundingClientRect().top + window.scrollY;
    if (pageTop > 2200 && !isProductTradePriceElement(item.el)) return false;
    return /^(?:平台加补后|到手价|券后价|店铺优惠后|补贴后|活动价|促销价|售价|现价|价格|优惠前|原价|划线价)$/.test(item.text)
      || (item.text.length <= 80 && /[¥￥]\s*\d/.test(item.text));
  });
  for (const row of priceLeaves) {
    let current = row.el;
    for (let depth = 0; current && depth < 5; depth += 1, current = current.parentElement) {
      const text = clean(current.textContent);
      if (text.length <= 160 && /\d/.test(text)
        && (/[¥￥]/.test(text) || /(?:平台加补后|到手价|券后价|店铺优惠后|补贴后|活动价|促销价|售价|现价|价格|优惠前|原价|划线价)/.test(text))) {
        priceRoots.push(current);
        break;
      }
    }
  }
  const priceCandidates = [];
  const seenPrices = new Set();
  for (const root of priceRoots) {
    const pageTop = root.getBoundingClientRect().top + window.scrollY;
    const productScope = isProductTradePriceElement(root);
    if (pageTop > 2200 && !productScope) continue;
    const text = clean(root.textContent);
    if (!text || text.length > 160 || !/\d/.test(text)) continue;
    if (!/[¥￥]/.test(text) && !/(?:到手价|券后价|活动价|促销价|售价|现价|价格|优惠前|原价|店铺优惠后|补贴后)/.test(text)) continue;
    const context = clean(root.parentElement?.textContent).slice(0, 160);
    const key = `${text}:${context}`;
    if (seenPrices.has(key)) continue;
    seenPrices.add(key);
    priceCandidates.push({text, context, page_top: Math.round(pageTop), product_scope: productScope});
  }
  const tradeLeaves = leaves.filter((row) => isCurrentProductTradeElement(row.el));
  const salesTexts = tradeLeaves.map((row) => row.text).filter((text) => /(?:已售|月销|付款|销量)\s*[0-9.万+]+/.test(text)).slice(0, 12);
  const stockTexts = tradeLeaves.map((row) => row.text).filter((text) => /^(有货|无货|库存\s*\d+.*)$/.test(text)).slice(0, 10);

  const images = [
    ...(includeMainImages ? collectModuleImages(moduleRoots.main, 'main_image') : []),
    ...(includeDetailImages ? collectModuleImages(moduleRoots.detail, 'detail_image') : [])
  ];

  const directVideoValues = [];
  for (const el of document.querySelectorAll('video,video source,[data-video-url],[data-play-url],[data-video-src],[src*="video.alicdn.com"],[src*="cloud.video.taobao.com"],[src*="tbm-auth.alicdn.com"],[data-src*="video.alicdn.com"],[data-src*="cloud.video.taobao.com"],[data-src*="tbm-auth.alicdn.com"]')) {
    directVideoValues.push(el.currentSrc, el.src);
    for (const name of ['src','data-src','data-url','data-video-url','data-play-url','data-video-src']) directVideoValues.push(el.getAttribute?.(name));
  }
  let scanned = 0;
  const inlinePattern = /https?:\\?\/\\?\/(?:cloud\.video\.taobao\.com|video\.alicdn\.com|tbm-auth\.alicdn\.com)[^"'<>\s\\]+/gi;
  for (const script of document.querySelectorAll('script:not([src])')) {
    const text = String(script.textContent || '');
    if (!text || scanned >= 8000000) break;
    const slice = text.slice(0, Math.max(0, 8000000 - scanned));
    scanned += slice.length;
    for (const match of slice.matchAll(inlinePattern)) directVideoValues.push(match[0].replace(/\\u002[fF]/g, '/').replace(/\\\//g, '/'));
  }
  const videoUrls = includeVideo ? [...new Set(directVideoValues.filter((src) => /^(https:)?\/\/(?:cloud\.video\.taobao\.com|video\.alicdn\.com|tbm-auth\.alicdn\.com)\//i.test(src)
    && !/\.(?:m3u8|ts)(?:$|[?#])/i.test(src)))] : [];
  const players = [...document.querySelectorAll('video')].filter((video) => pageTop(video) < Math.min(detailStartTop(), 2000) && !isInsideRecommendationSurface(video));
  const blobPlayers = players.filter((video) => String(video.currentSrc || video.src || '').startsWith('blob:'));
  const videoProbeStatus = videoUrls.length ? 'direct_candidate_found' : blobPlayers.length ? 'blob_player_without_direct_file'
    : players.length ? 'player_present_no_direct_source' : 'no_player_observed';

  const moduleStates = {};
  if (modules.has('product_data') || modules.has('overview')) moduleStates.product_data = {status: title && (parameters.length || skuGroups.length) ? 'observed' : title ? 'partial' : 'not_observed', count: parameters.length + skuGroups.length};
  if (includeMainImages) moduleStates.main_images = {status: moduleRoots.main && images.some((row) => row.kind === 'main_image') ? 'observed' : moduleRoots.main ? 'partial' : 'not_observed', count: images.filter((row) => row.kind === 'main_image').length};
  if (includeDetailImages) moduleStates.detail_images = {status: moduleRoots.detail && images.some((row) => row.kind === 'detail_image') ? 'observed' : moduleRoots.detail ? 'partial' : 'not_observed', count: images.filter((row) => row.kind === 'detail_image').length};
  if (modules.has('video')) moduleStates.video = {status: videoUrls.length || videoProbeStatus !== 'no_player_observed' ? 'observed' : 'not_observed', count: videoUrls.length};

  return {
    item_id: itemId,
    selected_sku_id: skuId,
    title,
    shop: shopLinks[0] || {text:'',href:''},
    parameters,
    sku_groups: skuGroups,
    snapshot: {
      price_candidates: priceCandidates.slice(0, 24),
      sales_texts: [...new Set(salesTexts)],
      stock_texts: [...new Set(stockTexts)]
    },
    media: {images, videos: videoUrls},
    video_probe: {status: videoProbeStatus, player_count: players.length, blob_player_count: blobPlayers.length, candidate_count: videoUrls.length},
    module_states: moduleStates
  };
}
"""


DETAIL_MODULE_LOAD_SCRIPT = r"""
async () => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (element) => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const pageTop = (element) => element?.getBoundingClientRect
    ? element.getBoundingClientRect().top + window.scrollY
    : Number.POSITIVE_INFINITY;
  const recommendationLabels = new Set(['看了又看','猜你喜欢','相关推荐','更多推荐','更多宝贝']);
  const leafText = (root = document) => [...root.querySelectorAll('*')]
    .filter((element) => visible(element) && element.children.length === 0 && clean(element.textContent))
    .map((element) => ({element, text: clean(element.textContent)}));
  const exactVisibleText = (label) => [...document.querySelectorAll('*')]
    .filter((element) => visible(element) && clean(element.textContent) === label);
  const headingModuleRoot = (label) => {
    const candidates = exactVisibleText(label).map((element) => element.closest(
      '[class*="tabDetailItem--"],section,[class*="module" i],[class*="detailContent" i]'
    )).filter(Boolean);
    return candidates.sort((left, right) => right.querySelectorAll('img').length - left.querySelectorAll('img').length)[0] || null;
  };
  const recommendationBoundaryTop = (afterTop = 0) => {
    const values = leafText().filter((row) => recommendationLabels.has(row.text))
      .map((row) => pageTop(row.element))
      .filter((top) => Number.isFinite(top) && top > afterTop + 240);
    return values.length ? Math.min(...values) : Number.POSITIVE_INFINITY;
  };
  const imageSignature = (root) => [...root.querySelectorAll('img')].map((image) => [
    image.getAttribute('data-src'), image.getAttribute('data-original'), image.getAttribute('data-ks-lazyload'),
    image.getAttribute('data-lazyload'), image.currentSrc, image.src
  ].map(clean).find(Boolean) || '').filter(Boolean).join('|');

  const originalScrollY = window.scrollY;
  let result = {steps: 0, status: 'detail_module_not_observed', position_restored: false};
  try {
    let root = headingModuleRoot('图文详情');
    if (root) {
      let steps = 0;
      let stableRounds = 0;
      let previousSignature = '';
      window.scrollTo({top: Math.max(0, pageTop(root) - 120), behavior: 'instant'});
      await wait(360);

      for (let attempt = 0; attempt < 24; attempt += 1) {
        root = headingModuleRoot('图文详情');
        if (!root) break;
        const signature = imageSignature(root);
        stableRounds = signature && signature === previousSignature ? stableRounds + 1 : 0;
        previousSignature = signature;

        const rootTop = pageTop(root);
        const rootRect = root.getBoundingClientRect();
        const detailRootBottom = rootTop + Math.max(Number(rootRect.height || 0), Number(root.scrollHeight || 0));
        const recommendationTop = recommendationBoundaryTop(rootTop);
        const boundedBottom = Math.min(detailRootBottom, recommendationTop);
        const lastSafeScrollY = Math.max(rootTop, boundedBottom - Math.max(180, window.innerHeight * 0.55));
        if (window.scrollY >= lastSafeScrollY - 32 && stableRounds >= 2) break;

        const nextScrollY = Math.min(lastSafeScrollY, window.scrollY + Math.max(520, window.innerHeight * 0.72));
        if (nextScrollY <= window.scrollY + 8) {
          if (stableRounds >= 2) break;
          await wait(240);
          continue;
        }
        window.scrollTo({top: nextScrollY, behavior: 'instant'});
        steps += 1;
        await wait(320);
      }
      result = {
        steps,
        status: previousSignature ? 'detail_module_observed' : 'partial_detail_images_not_observed',
        position_restored: false
      };
    }
  } finally {
    window.scrollTo({top: originalScrollY, behavior: 'instant'});
    await wait(80);
  }
  result.position_restored = Math.abs(window.scrollY - originalScrollY) <= 8;
  return result;
}
"""


REVIEW_CARD_SCRIPT = r"""
(card) => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const text = clean(card.innerText);
  const lines = (card.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const username = clean(card.querySelector('[class*="userName--"]')?.textContent || lines[0] || '');
  const contentNodes = [...card.querySelectorAll('[class^="content--"],[class*=" content--"]')]
    .filter(visible).map((el) => ({
      text: clean(el.textContent),
      role: el.closest('[class*="append--"]') ? 'followup' : 'review',
      relative_event: clean(el.closest('[class*="append--"]')?.textContent).match(/\d+\s*天后追评|追评/)?.[0] || ''
    })).filter((row) => row.text);
  const seenContent = new Set();
  const contents = contentNodes.filter((row) => {
    const key = row.role + '\u241f' + row.text;
    if (row.text.length < 2 || seenContent.has(key)) return false;
    seenContent.add(key);
    return true;
  });
  const headerLines = (card.querySelector('[class*="header--"]')?.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const purchasedLine = headerLines.find((line) => /已购[：:]/.test(line)) || lines.find((line) => /已购[：:]/.test(line)) || '';
  const purchasedIndex = purchasedLine.search(/已购[：:]/);
  const purchased = purchasedIndex >= 0 ? purchasedLine.slice(purchasedIndex) : purchasedLine;
  const datePrefix = purchasedIndex > 0 ? clean(purchasedLine.slice(0, purchasedIndex).replace(/[|·]+$/, '')) : '';
  const dates = [datePrefix, ...[...text.matchAll(/(?:20\d{2}(?:[-/.年]\d{1,2})?(?:[-/.月]\d{1,2}日?)?|\d{1,2}[-/.]\d{1,2}|\d+\s*(?:天|月|年)前)(?:\s+\d{1,2}:\d{2})?/g)].map((m) => m[0])].filter(Boolean);
  const platformId = card.getAttribute('data-review-id') || card.getAttribute('data-id') || card.id || '';
  const media = [...card.querySelectorAll('img,video,video source')]
    .filter((el) => !el.closest('[class*="userInfo" i],[class*="avatar" i],[class*="header--"]'))
    .map((el) => ({
    kind: el.tagName === 'IMG' ? 'image' : 'video',
    src: el.currentSrc || el.src || el.getAttribute('src') || ''
  })).filter((row) => /^(https?:)?\/\/(img|gw)\.alicdn\.com\//i.test(row.src) || /^(https?:)?\/\/(cloud\.video\.taobao\.com|video\.alicdn\.com)\//i.test(row.src));
  return {username, contents, dates, purchased_sku: purchased, platform_review_id: platformId, media};
}
"""


QA_CARDS_SCRIPT = r"""
(root) => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  return [...root.querySelectorAll('[class*="qaItem--"]')].map((card) => {
    const question = clean(card.querySelector('[class*="questionTitle--"]')?.textContent);
    const cardText = clean(card.innerText || card.textContent);
    const declared = Number((cardText.match(/(?:查看全部|共)\s*(\d+)\s*(?:个|条)?回答/) || [])[1] || 0);
    const answers = [...card.querySelectorAll('[class*="answerItem--"]')].map((answer) => ({
      author: clean(answer.querySelector('[class*="userNick--"]')?.textContent),
      buyer_tag: clean(answer.querySelector('[class*="userTag--"]')?.textContent || answer.querySelector('[class*="timeAgo--"]')?.textContent),
      content: clean(answer.querySelector('[class*="answerContent--"]')?.textContent),
      meta_text: clean(answer.querySelector('[class*="answerMeta--"]')?.textContent)
    })).filter((row) => row.content);
    return {question, declared_answer_count: Math.max(declared, answers.length), answers};
  }).filter((row) => row.question);
}
"""


def find_chrome_executable(explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return str(path)
        raise CollectionError(f"Chrome executable not found: {path}")
    candidates: list[Path] = []
    if sys.platform == "win32":
        for root in [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]:
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise CollectionError("Google Chrome was not found; pass --chrome-path explicitly")


def normalize_assets(value: str) -> list[str]:
    allowed = {"main_images", "detail_images", "video", "review_media", "none"}
    parts = dedupe_preserve_order(part.strip() for part in str(value or "").split(",") if part.strip())
    unknown = [part for part in parts if part not in allowed]
    if unknown:
        raise CollectionError(f"Unknown asset type(s): {', '.join(unknown)}")
    if "none" in parts and len(parts) > 1:
        raise CollectionError("assets=none cannot be combined with other asset types")
    return [] if parts == ["none"] else parts


def _extension_from_response(clean_url: str, content_type: str, kind: str) -> str:
    type_name = (content_type or "").split(";", 1)[0].strip().lower()
    by_type = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
        "image/webp": ".webp", "image/avif": ".avif", "image/gif": ".gif",
        "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    }
    if type_name in by_type:
        return by_type[type_name]
    suffix = Path(urlparse(clean_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(type_name) or ""
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed or (".mp4" if kind == "video" else ".bin")


def download_asset(context: Any, source_url: str, target_base: Path, *, kind: str, max_bytes: int) -> dict[str, Any]:
    try:
        clean_url, redacted = sanitize_media_url(source_url, kind=kind)
        request_url = media_request_url(source_url, kind=kind)
    except CollectionError:
        if kind != "video":
            raise
        clean_url, redacted = sanitize_transient_video_url(source_url)
        request_url = source_url
    response = context.request.get(request_url, timeout=90_000)
    if not response.ok:
        raise CollectionError(f"Asset request returned HTTP {response.status}")
    body = response.body()
    if len(body) > max_bytes:
        raise CollectionError(f"Asset exceeds the configured size limit ({len(body)} bytes)")
    content_type = response.headers.get("content-type", "")
    extension = _extension_from_response(clean_url, content_type, kind)
    target = target_base.with_suffix(extension)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(body)
    partial.replace(target)
    return {
        "file": str(target),
        "source_url": clean_url,
        "source_url_query_redacted": redacted,
        "content_type": content_type,
        "bytes": len(body),
        "status": "downloaded",
    }


def _merge_product_module_raw(base: dict[str, Any], incoming: dict[str, Any], module: str) -> dict[str, Any]:
    """Merge one independently observed product surface without erasing prior surfaces."""
    if not base:
        base = {
            **incoming,
            "media": {"images": [], "videos": []},
            "module_states": {},
        }
    if str(base.get("item_id") or incoming.get("item_id") or "") != str(incoming.get("item_id") or ""):
        raise CollectionError("Product modules cannot be merged across item IDs")
    if module == "product_data":
        preserved_media = base.get("media") or {"images": [], "videos": []}
        preserved_states = base.get("module_states") or {}
        base.update(incoming)
        base["media"] = preserved_media
        base["module_states"] = preserved_states
    images = list((base.get("media") or {}).get("images") or [])
    incoming_images = list((incoming.get("media") or {}).get("images") or [])
    if module == "main_images":
        images = [row for row in images if row.get("kind") != "main_image"] + [row for row in incoming_images if row.get("kind") == "main_image"]
    elif module == "detail_images":
        images = [row for row in images if row.get("kind") != "detail_image"] + [row for row in incoming_images if row.get("kind") == "detail_image"]
    videos = list((base.get("media") or {}).get("videos") or [])
    if module == "video":
        videos = list((incoming.get("media") or {}).get("videos") or [])
        base["video_probe"] = incoming.get("video_probe") or {}
    base["media"] = {"images": images, "videos": videos}
    base.setdefault("module_states", {}).update(incoming.get("module_states") or {})
    return base


def collect_product(page: Any, context: Any, source_url: str, out: Path, assets: list[str], max_asset_bytes: int) -> dict[str, Any]:
    item_id = extract_item_id(source_url)
    canonical_url = canonical_item_url(source_url)
    navigation_url = navigation_item_url(source_url)
    requested_sku_id = (parse_qs(urlparse(navigation_url).query).get("skuId") or [""])[0]
    page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    if any(page.get_by_text(label, exact=False).count() for label in ["滑动验证", "安全验证", "请完成验证"]):
        raise CollectionError("Tmall requires manual verification in the visible Chrome window")
    requested_modules = ["product_data"]
    if "main_images" in assets:
        requested_modules.append("main_images")
    if "detail_images" in assets:
        requested_modules.append("detail_images")
    if "video" in assets:
        requested_modules.append("video")
    raw: dict[str, Any] = {}
    module_failures: list[dict[str, str]] = []
    detail_load: dict[str, Any] = {"steps": 0, "status": "not_requested", "position_restored": True}
    for module in requested_modules:
        try:
            if module == "detail_images":
                detail_load = page.evaluate(DETAIL_MODULE_LOAD_SCRIPT) or {
                    "steps": 0,
                    "status": "partial_detail_images_not_observed",
                    "position_restored": None,
                }
            module_raw = page.evaluate(PRODUCT_SCRIPT, [module])
            raw = _merge_product_module_raw(raw, module_raw, module)
        except Exception as exc:
            module_failures.append({"module": module, "error": type(exc).__name__})
            raw.setdefault("module_states", {})[module] = {"status": "failed", "count": 0}
            if module == "detail_images":
                detail_load = {
                    "steps": int(detail_load.get("steps") or 0),
                    "status": "detail_module_load_failed",
                    "position_restored": None,
                }
    if not str(raw.get("title") or "").strip():
        raise CollectionError("No visible product title was found")

    # Product video sources often appear only after the normal visible tab is selected.
    if "video" in assets and not raw.get("media", {}).get("videos"):
        page.eval_on_selector_all(
            "video", "els => els.forEach(el => { el.muted = true; el.play().catch(() => {}); })"
        )
        page.wait_for_timeout(1_200)
        refreshed = page.evaluate(PRODUCT_SCRIPT, ["video"])
        raw["video_probe"] = refreshed.get("video_probe", raw.get("video_probe", {}))
        raw.setdefault("media", {}).setdefault("videos", []).extend(refreshed.get("media", {}).get("videos", []))
        raw.setdefault("module_states", {}).update(refreshed.get("module_states") or {})
        candidates = page.get_by_text("视频", exact=True)
        for index in (range(min(candidates.count(), 8)) if not raw.get("media", {}).get("videos") else []):
            candidate = candidates.nth(index)
            try:
                box = candidate.bounding_box()
                if box and box["y"] < 1_100 and box["x"] < 1_200:
                    candidate.click(timeout=5_000)
                    page.wait_for_timeout(1_200)
                    page.eval_on_selector_all(
                        "video", "els => els.forEach(el => { el.muted = true; el.play().catch(() => {}); })"
                    )
                    page.wait_for_timeout(900)
                    refreshed = page.evaluate(PRODUCT_SCRIPT, ["video"])
                    raw["video_probe"] = refreshed.get("video_probe", raw.get("video_probe", {}))
                    raw.setdefault("media", {}).setdefault("videos", []).extend(refreshed.get("media", {}).get("videos", []))
                    raw.setdefault("module_states", {}).update(refreshed.get("module_states") or {})
                    break
            except Exception:
                continue
    raw["item_id"] = str(raw.get("item_id") or item_id)
    raw["selected_sku_id"] = str(raw.get("selected_sku_id") or requested_sku_id)
    raw["product_id"] = f"tmall:{raw['item_id']}"
    raw["canonical_url"] = canonical_url
    raw["source_page_type"] = "tmall_item" if "tmall.com" in canonical_url else "taobao_item"
    raw["collected_at"] = utc_now()
    raw.setdefault("snapshot", {})
    raw["snapshot"]["observed_at"] = raw["collected_at"]
    raw["snapshot"]["selected_sku_id"] = raw.get("selected_sku_id") or ""
    price_entries = normalize_price_candidates(raw["snapshot"].pop("price_candidates", []))
    raw["snapshot"]["price_entries"] = price_entries
    raw["snapshot"]["price_texts"] = [row["text"] for row in price_entries if row["role"] != "benefit_amount"]
    raw["snapshot"]["benefit_texts"] = [row["text"] for row in price_entries if row["role"] == "benefit_amount"]
    raw["snapshot"]["price_status"] = (
        "observed_structured" if raw["snapshot"]["price_texts"] else "not_reliably_observed"
    )
    raw["sku_groups"] = [
        {
            **group,
            "values": [value for value in (group.get("values") or []) if is_usable_sku_option(value)],
        }
        for group in (raw.get("sku_groups") or [])
        if isinstance(group, dict)
    ]
    raw["sku_groups"] = [group for group in raw["sku_groups"] if group.get("name") and group.get("values")]
    raw["selected_sku_snapshot"] = [
        {"name": str(group.get("name") or ""), "value": str(group.get("selected_value") or "")}
        for group in raw["sku_groups"] if str(group.get("selected_value") or "").strip()
    ]
    raw["parameter_scope_status"] = (
        "page_level_not_confirmed_for_selected_sku" if raw.get("parameters") else "not_observed"
    )
    raw["parameter_warnings"] = sku_parameter_warnings(raw["selected_sku_snapshot"], raw.get("parameters") or [])
    raw["sku_mapping_status"] = sku_mapping_status(raw.get("selected_sku_id"), raw.get("sku_groups") or [])
    detail_status = str((raw.get("module_states") or {}).get("detail_images", {}).get("status") or "not_requested")
    raw["detail_load_state"] = "detail_module_observed" if detail_status == "observed" else (
        "partial_detail_images_not_observed" if "detail_images" in assets else "not_requested"
    )
    raw["detail_load_steps"] = max(0, int(detail_load.get("steps") or 0))
    raw["detail_scroll_restored"] = detail_load.get("position_restored")
    raw["module_failures"] = module_failures
    raw["media_records"] = []

    media_root = out / "03_商品素材" / safe_filename(raw.get("title") or "", fallback=item_id)
    counters = {"main_image": 0, "detail_image": 0, "video": 0}
    requested_map = {"main_image": "main_images", "detail_image": "detail_images", "video": "video"}
    observed: list[tuple[str, str, dict[str, Any]]] = []
    for image in raw.get("media", {}).get("images", []):
        observed.append((str(image.get("kind") or ""), str(image.get("src") or ""), image))
    for video in raw.get("media", {}).get("videos", []):
        observed.append(("video", str(video or ""), {}))

    seen_urls: set[str] = set()
    excluded_count = 0
    for kind, source, metadata in observed:
        requested = requested_map.get(kind)
        if not source or not requested:
            continue
        page_order = max(1, int(metadata.get("index") or 0) + 1) if kind != "video" else counters[kind] + 1
        try:
            clean_url, redacted = sanitize_media_url(source, kind="video" if kind == "video" else "image")
        except CollectionError:
            if kind != "video":
                continue
            try:
                clean_url, redacted = sanitize_transient_video_url(source)
            except CollectionError:
                continue
        if kind != "video" and not image_is_usable(metadata.get("width"), metadata.get("height"), kind, source):
            excluded_count += 1
            raw["media_records"].append({
                "asset_id": f"tmall:{item_id}:{kind}:excluded-{excluded_count:03d}",
                "item_id": item_id,
                "kind": kind,
                "order": page_order,
                "download_order": 0,
                "source_url": clean_url,
                "source_url_query_redacted": redacted,
                "status": "excluded_not_product_content" if is_platform_notice_image_url(source) else "excluded_quality",
                "reason": "platform_notice_not_product_content" if is_platform_notice_image_url(source) else "image_quality_guard",
                "file": "",
            })
            continue
        media_key = canonical_image_asset_key(source) if kind != "video" else clean_url
        if media_key in seen_urls:
            continue
        seen_urls.add(media_key)
        counters[kind] += 1
        folder = {"main_image": "主图", "detail_image": "详情图", "video": "视频"}[kind]
        record: dict[str, Any] = {
            "asset_id": f"tmall:{item_id}:{kind}:{counters[kind]:03d}",
            "item_id": item_id,
            "kind": kind,
            "order": page_order,
            "download_order": counters[kind],
            "source_url": clean_url,
            "source_url_query_redacted": redacted,
            "status": "observed_not_requested",
            "file": "",
        }
        if requested in assets:
            base = media_root / folder / f"{counters[kind]:03d}_{kind}"
            try:
                downloaded = download_asset(
                    context,
                    source,
                    base,
                    kind="video" if kind == "video" else "image",
                    max_bytes=max_asset_bytes,
                )
                downloaded["file"] = str(Path(downloaded["file"]).relative_to(out))
                record.update(downloaded)
                record["content_status"] = image_content_status(
                    metadata.get("width"), metadata.get("height"), kind, source, downloaded.get("bytes")
                ) if kind != "video" else "video"
            except Exception as exc:  # keep an auditable partial record
                record["status"] = "failed"
                record["error"] = type(exc).__name__
        raw["media_records"].append(record)

    for kind, request_name in requested_map.items():
        if request_name in assets and counters[kind] == 0:
            raw["media_records"].append({
                "asset_id": f"tmall:{item_id}:{kind}:000",
                "item_id": item_id,
                "kind": kind,
                "order": 0,
                "source_url": "",
                "source_url_query_redacted": False,
                "status": "not_observed",
                "file": "",
            })

    requested_records = [row for row in raw["media_records"]
                         if requested_map.get(row["kind"]) in assets and not str(row.get("status") or "").startswith("excluded_")]
    failed_records = [row for row in requested_records if row["status"] != "downloaded"]
    critical_missing = any(row["kind"] == "main_image" and row["status"] == "not_observed" for row in requested_records)
    raw["completion_state"] = choose_product_completion_state(
        sku_status=raw["sku_mapping_status"],
        detail_requested="detail_images" in assets,
        detail_status=detail_status,
        detail_position_restored=raw.get("detail_scroll_restored"),
        failed_asset_records=bool(failed_records),
        critical_asset_missing=critical_missing,
        module_failures=bool(module_failures),
    )
    raw["effective_detail_image_count"] = sum(
        1 for row in raw["media_records"]
        if row.get("kind") == "detail_image" and row.get("status") == "downloaded"
        and row.get("content_status") == "content_image"
    )
    required_material_partial = any(
        state.get("status") != "observed"
        for name, state in (raw.get("module_states") or {}).items()
        if name != "video"
    )
    raw["material_status"] = (
        "partial_observed_material" if required_material_partial or failed_records else "complete_observed_material"
    )
    has_commerce_snapshot = bool(
        raw["snapshot"].get("price_entries") or raw["snapshot"].get("sales_texts")
        or raw["snapshot"].get("stock_texts")
    )
    raw["commerce_snapshot_status"] = "observed_partial_snapshot" if has_commerce_snapshot else "not_observed"
    raw.pop("media", None)
    product_dir = out / "data" / "商品采集" / item_id
    atomic_write_json(product_dir / "product.json", raw)
    atomic_write_json(product_dir / "asset_manifest.json", raw["media_records"])
    return raw


def _folded_count(page: Any) -> int:
    body = page.locator("body").inner_text(timeout=10_000)
    match = re.search(r"已折叠\s*([0-9]+)\s*条", body)
    return int(match.group(1)) if match else 0


def _find_review_root(page: Any) -> Any | None:
    roots = page.locator('div[class*="comments--"]')
    best = None
    best_height = -1
    for index in range(roots.count()):
        candidate = roots.nth(index)
        try:
            if not candidate.is_visible():
                continue
            state = candidate.evaluate("(el) => ({height: el.scrollHeight, client: el.clientHeight})")
            score = int(state.get("height") or 0)
            if score > best_height:
                best, best_height = candidate, score
        except Exception:
            continue
    return best


def _open_review_panel(page: Any, wait_seconds: int = 0) -> Any | None:
    root = _find_review_root(page)
    if root is not None:
        try:
            state = root.evaluate("(el) => ({height: el.scrollHeight, client: el.clientHeight})")
            if int(state.get("height") or 0) > int(state.get("client") or 0) + 100:
                return root
        except Exception:
            pass
    for label in ["查看全部评价", "全部评价"]:
        candidates = page.get_by_text(label, exact=True)
        for index in range(min(candidates.count(), 5)):
            candidate = candidates.nth(index)
            if candidate.is_visible():
                candidate.scroll_into_view_if_needed(timeout=10_000)
                candidate.evaluate("el => { el.style.outline='4px solid #ff7a00'; el.style.outlineOffset='5px'; }")
                print("Please click 查看全部评价 in the visible product page, then return to this task.")
                if wait_seconds > 0:
                    page.wait_for_timeout(wait_seconds * 1_000)
                    root = _find_review_root(page)
                    if root is not None:
                        return root
    return None


def _review_rows_from_raw(raw: dict[str, Any], item_id: str, *, retain_masked_author: bool) -> list[dict[str, Any]]:
    author = str(raw.get("username") or "")
    contents = [value for value in raw.get("contents") or [] if isinstance(value, dict) and str(value.get("text") or "").strip()]
    if not contents:
        return []
    dates = [str(value) for value in raw.get("dates") or []]
    purchased = str(raw.get("purchased_sku") or "")
    platform_id = str(raw.get("platform_review_id") or "")
    media_records: list[dict[str, Any]] = []
    for media in raw.get("media") or []:
        try:
            clean_url, redacted = sanitize_media_url(str(media.get("src") or ""), kind=str(media.get("kind") or "image"))
        except CollectionError:
            continue
        media_records.append({
            "kind": media.get("kind"),
            "source_url": clean_url,
            "source_url_query_redacted": redacted,
            "status": "observed_not_requested",
            "file": "",
            "_transient_source_url": str(media.get("src") or ""),
        })
    rows: list[dict[str, Any]] = []
    for index, content_row in enumerate(contents):
        content = str(content_row.get("text") or "").strip()
        role = str(content_row.get("role") or "review")
        date_text = str(content_row.get("relative_event") or "") if role == "followup" else (dates[min(index, len(dates) - 1)] if dates else "")
        review_id = platform_id if platform_id and index == 0 else derived_review_id(item_id, author, date_text, purchased, content, role)
        row = {
            "review_id": review_id,
            "review_id_type": "platform" if platform_id and index == 0 else "derived",
            "item_id": item_id,
            "product_id": f"tmall:{item_id}",
            "role": role,
            "author_id": pseudonymize_author(author),
            "author_masked": author if retain_masked_author else "",
            "date_text": date_text,
            "purchased_sku_text": purchased,
            "content": content,
            "media": media_records if index == 0 else [],
            "collected_at": utc_now(),
        }
        rows.append(row)
    return rows


def _review_rows_from_card(card: Any, item_id: str, *, retain_masked_author: bool) -> list[dict[str, Any]]:
    return _review_rows_from_raw(
        card.evaluate(REVIEW_CARD_SCRIPT),
        item_id,
        retain_masked_author=retain_masked_author,
    )


def collect_reviews(
    page: Any,
    context: Any,
    source_url: str,
    out: Path,
    *,
    assets: list[str],
    max_asset_bytes: int,
    limit: int,
    max_scroll_actions: int,
    retain_masked_author: bool,
    resume: bool,
    panel_wait: int = 0,
) -> dict[str, Any]:
    item_id = extract_item_id(source_url)
    canonical_url = canonical_item_url(source_url)
    navigation_url = navigation_item_url(source_url)
    if extract_item_id(page.url) != item_id if "item.htm" in page.url else True:
        page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3_500)
    review_dir = out / "data" / "评价采集" / item_id
    review_dir.mkdir(parents=True, exist_ok=True)
    rows_path = review_dir / "reviews.jsonl"
    saved_ids = read_jsonl_ids(rows_path, "review_id") if resume else set()
    if not resume and rows_path.exists():
        rows_path.unlink()
    root = _open_review_panel(page, panel_wait)
    if root is None:
        manifest = {
            "schema_version": "1.0",
            "item_id": item_id,
            "canonical_url": canonical_url,
            "state": "partial_requires_full_review_panel",
            "saved_reviews": len(saved_ids),
            "folded_count": 0,
            "exhausted": False,
            "finished_at": utc_now(),
        }
        atomic_write_json(review_dir / "review_manifest.json", manifest)
        return manifest

    no_growth_rounds = 0
    exhausted = False
    limit_reached = False
    scroll_actions = 0
    with rows_path.open("a", encoding="utf-8", newline="\n") as handle:
        while scroll_actions <= max_scroll_actions:
            before = len(saved_ids)
            cards = root.locator('[class*="Comment--"]')
            # Parse the newest cards in one browser call. Tmall keeps prior cards in the
            # DOM, so re-reading every historical card on every scroll made long review
            # lists progressively slower. A 250-card overlap is deliberately larger than
            # one lazy-load batch; saved_ids still provides exact de-duplication on resume.
            raw_cards = cards.evaluate_all(
                f"(cards) => cards.slice(Math.max(0, cards.length - 250)).map({REVIEW_CARD_SCRIPT})"
            )
            for raw_card in raw_cards:
                for row in _review_rows_from_raw(raw_card, item_id, retain_masked_author=retain_masked_author):
                    if row["review_id"] in saved_ids:
                        continue
                    if limit > 0 and len(saved_ids) >= limit:
                        limit_reached = True
                        break
                    if "review_media" in assets:
                        media_folder = out / "03_商品素材" / item_id / "评价素材"
                        for media_index, media in enumerate(row.get("media") or [], start=1):
                            transient = str(media.pop("_transient_source_url", "") or "")
                            try:
                                downloaded = download_asset(
                                    context,
                                    transient,
                                    media_folder / f"{row['review_id'].replace(':', '_')}_{media_index:02d}",
                                    kind=str(media.get("kind") or "image"),
                                    max_bytes=max_asset_bytes,
                                )
                                downloaded["file"] = str(Path(downloaded["file"]).relative_to(out))
                                media.update(downloaded)
                            except Exception as exc:
                                media["status"] = "failed"
                                media["error"] = type(exc).__name__
                    else:
                        for media in row.get("media") or []:
                            media.pop("_transient_source_url", None)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    saved_ids.add(row["review_id"])
            if limit_reached:
                break
            state = root.evaluate("(el) => ({top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight})")
            at_bottom = state["top"] + state["client"] >= state["height"] - 4
            no_growth_rounds = no_growth_rounds + 1 if len(saved_ids) == before else 0
            if at_bottom and no_growth_rounds >= 3:
                exhausted = True
                break
            root.evaluate("(el) => el.scrollTo({top: Math.min(el.scrollHeight, el.scrollTop + Math.max(500, el.clientHeight * 0.85)), behavior: 'instant'})")
            page.wait_for_timeout(550)
            scroll_actions += 1

    folded_count = _folded_count(page)
    status = choose_review_status(exhausted=exhausted, folded_count=folded_count, limit_reached=limit_reached)
    manifest = {
        "schema_version": "1.0",
        "item_id": item_id,
        "canonical_url": canonical_url,
        "state": status,
        "saved_reviews": len(saved_ids),
        "folded_count": folded_count,
        "exhausted": exhausted,
        "limit": limit,
        "limit_reached": limit_reached,
        "scroll_actions": scroll_actions,
        "privacy_mode": "masked_author_retained" if retain_masked_author else "pseudonymized",
        "finished_at": utc_now(),
    }
    atomic_write_json(review_dir / "review_manifest.json", manifest)
    return manifest


def _find_question_root(page: Any) -> Any | None:
    roots = page.locator('[class*="AskAnswersWrap--"]')
    for index in range(roots.count()):
        candidate = roots.nth(index)
        try:
            if candidate.is_visible() and candidate.locator('[class*="qaItem--"]').count():
                return candidate
        except Exception:
            continue
    return None


def _open_question_panel(page: Any, wait_seconds: int = 0) -> Any | None:
    root = _find_question_root(page)
    if root is not None:
        return root
    candidates = page.get_by_text("查看全部问答", exact=True)
    for index in range(min(candidates.count(), 5)):
        candidate = candidates.nth(index)
        try:
            if not candidate.is_visible():
                continue
            candidate.scroll_into_view_if_needed(timeout=10_000)
            candidate.evaluate("el => { el.style.outline='4px solid #ff7a00'; el.style.outlineOffset='5px'; }")
            print("Please click 查看全部问答 in the visible product page, then return to this task.")
            if wait_seconds > 0:
                page.wait_for_timeout(wait_seconds * 1_000)
                return _find_question_root(page)
        except Exception:
            continue
    return None


def _question_scroll_root(root: Any) -> Any:
    candidates = root.locator("*")
    best = root
    best_gap = 0
    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        try:
            if not candidate.is_visible():
                continue
            state = candidate.evaluate("el => ({height: el.scrollHeight, client: el.clientHeight})")
            gap = int(state.get("height") or 0) - int(state.get("client") or 0)
            if gap > best_gap:
                best, best_gap = candidate, gap
        except Exception:
            continue
    return best


def _append_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()


def collect_questions(
    page: Any,
    source_url: str,
    out: Path,
    *,
    limit: int,
    max_scroll_actions: int,
    retain_masked_author: bool,
    resume: bool,
    panel_wait: int = 0,
) -> dict[str, Any]:
    item_id = extract_item_id(source_url)
    canonical_url = canonical_item_url(source_url)
    navigation_url = navigation_item_url(source_url)
    if extract_item_id(page.url) != item_id if "item.htm" in page.url else True:
        page.goto(navigation_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3_500)
    question_dir = out / "data" / "问答采集" / item_id
    question_dir.mkdir(parents=True, exist_ok=True)
    questions_path = question_dir / "questions.jsonl"
    answers_path = question_dir / "answers.jsonl"
    question_ids = read_jsonl_ids(questions_path, "question_id") if resume else set()
    answer_ids = read_jsonl_ids(answers_path, "answer_id") if resume else set()
    if not resume:
        questions_path.unlink(missing_ok=True)
        answers_path.unlink(missing_ok=True)
    root = _open_question_panel(page, panel_wait)
    if root is None:
        manifest = {
            "schema_version": "1.0", "item_id": item_id, "canonical_url": canonical_url,
            "state": "partial_requires_full_question_panel", "saved_questions": len(question_ids),
            "saved_answers": len(answer_ids), "total_hint": 0, "exhausted": False,
            "limit": limit, "limit_reached": False, "finished_at": utc_now(),
        }
        atomic_write_json(question_dir / "question_manifest.json", manifest)
        return manifest

    scroll_root = _question_scroll_root(root)
    no_growth_rounds = 0
    exhausted = False
    limit_reached = False
    scroll_actions = 0
    while scroll_actions <= max_scroll_actions:
        before = len(question_ids)
        expanders = root.get_by_text(re.compile(r"^查看全部回答$"))
        for index in range(min(expanders.count(), 6)):
            try:
                candidate = expanders.nth(index)
                if candidate.is_visible():
                    candidate.click(timeout=5_000)
                    page.wait_for_timeout(120)
            except Exception:
                continue
        raw_cards = root.evaluate(QA_CARDS_SCRIPT)
        new_questions: list[dict[str, Any]] = []
        new_answers: list[dict[str, Any]] = []
        for raw in raw_cards or []:
            content = str(raw.get("question") or "").strip()
            if not content:
                continue
            question_id = derived_question_id(item_id, content)
            if limit > 0 and len(question_ids) >= limit and question_id not in question_ids:
                limit_reached = True
                break
            if question_id not in question_ids:
                new_questions.append({
                    "question_id": question_id,
                    "item_id": item_id,
                    "product_id": f"tmall:{item_id}",
                    "content": content,
                    "declared_answer_count": int(raw.get("declared_answer_count") or 0),
                    "canonical_url": canonical_url,
                    "collected_at": utc_now(),
                })
                question_ids.add(question_id)
            for answer in raw.get("answers") or []:
                answer_content = str(answer.get("content") or "").strip()
                if not answer_content:
                    continue
                author = str(answer.get("author") or "")
                meta_text = str(answer.get("meta_text") or "")
                answer_id = derived_answer_id(item_id, question_id, author, answer_content, meta_text)
                if answer_id in answer_ids:
                    continue
                new_answers.append({
                    "answer_id": answer_id,
                    "question_id": question_id,
                    "item_id": item_id,
                    "author_id": pseudonymize_qa_author(author),
                    "author_masked": author if retain_masked_author else "",
                    "buyer_tag": str(answer.get("buyer_tag") or ""),
                    "content": answer_content,
                    "meta_text": meta_text,
                    "collected_at": utc_now(),
                })
                answer_ids.add(answer_id)
        _append_jsonl_rows(questions_path, new_questions)
        _append_jsonl_rows(answers_path, new_answers)
        if limit_reached:
            break
        state = scroll_root.evaluate("el => ({top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight})")
        at_bottom = state["top"] + state["client"] >= state["height"] - 4
        no_growth_rounds = no_growth_rounds + 1 if len(question_ids) == before else 0
        if at_bottom and no_growth_rounds >= 3:
            exhausted = True
            break
        scroll_root.evaluate("el => el.scrollTo({top: Math.min(el.scrollHeight, el.scrollTop + Math.max(420, el.clientHeight * .78)), behavior: 'instant'})")
        page.wait_for_timeout(420)
        scroll_actions += 1

    body_text = page.locator("body").inner_text(timeout=10_000)
    total_match = re.search(r"问大家\s*[·・]?\s*(\d+)", body_text)
    total_hint = int(total_match.group(1)) if total_match else 0
    if limit_reached:
        status = "partial_limit_sample"
    elif exhausted and (not total_hint or len(question_ids) >= total_hint):
        status = "complete_visible_qa_exhausted"
    elif exhausted:
        status = "partial_visible_count_below_page_hint"
    else:
        status = "partial_not_exhausted"
    manifest = {
        "schema_version": "1.0", "item_id": item_id, "canonical_url": canonical_url,
        "state": status, "saved_questions": len(question_ids), "saved_answers": len(answer_ids),
        "total_hint": total_hint, "exhausted": exhausted, "limit": limit,
        "limit_reached": limit_reached, "scroll_actions": scroll_actions,
        "privacy_mode": "masked_author_retained" if retain_masked_author else "pseudonymized",
        "finished_at": utc_now(),
    }
    atomic_write_json(question_dir / "question_manifest.json", manifest)
    return manifest


def collect(
    *,
    item_urls: list[str],
    profile_dir: Path,
    out: Path,
    mode: str,
    assets: list[str],
    review_limit: int,
    question_limit: int,
    max_scroll_actions: int,
    login_wait: int,
    retain_masked_author: bool,
    resume: bool,
    chrome_path: str | None,
    max_asset_mb: int,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("Playwright is missing; install requirements-browser.txt first") from exc

    normalized_urls = normalize_item_targets(item_urls)
    item_ids = [extract_item_id(value) for value in normalized_urls]
    out.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(mode=mode, item_ids=item_ids, requested_assets=assets, privacy_mode="masked_author_retained" if retain_masked_author else "pseudonymized")
    manifest_path = out / "data" / "run_manifest.json"
    atomic_write_json(manifest_path, manifest.as_dict())

    executable = find_chrome_executable(chrome_path)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir.resolve()),
            executable_path=executable,
            headless=False,
            viewport=None,
            args=["--start-maximized"],
            accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if login_wait > 0:
                page.goto("https://www.tmall.com/", wait_until="domcontentloaded", timeout=120_000)
                print(f"Visible Chrome is ready. Complete any required login or verification within {login_wait} seconds.")
                page.wait_for_timeout(login_wait * 1_000)
            for url in normalized_urls:
                item_id = extract_item_id(url)
                if mode in {"product", "all"}:
                    try:
                        product = collect_product(page, context, url, out, assets, max_asset_mb * 1024 * 1024)
                        manifest.product_states[item_id] = product["completion_state"]
                    except Exception as exc:
                        manifest.product_states[item_id] = "failed_no_visible_product"
                        manifest.warnings.append(f"{item_id}: product collection failed ({type(exc).__name__})")
                if mode in {"reviews", "all"}:
                    try:
                        review = collect_reviews(
                            page, context, url, out,
                            assets=assets,
                            max_asset_bytes=max_asset_mb * 1024 * 1024,
                            limit=review_limit,
                            max_scroll_actions=max_scroll_actions,
                            retain_masked_author=retain_masked_author,
                            resume=resume,
                            panel_wait=login_wait,
                        )
                        manifest.review_states[item_id] = review["state"]
                    except Exception as exc:
                        manifest.review_states[item_id] = "partial_runtime_error"
                        manifest.warnings.append(f"{item_id}: review collection failed ({type(exc).__name__})")
                if mode in {"questions", "all"}:
                    try:
                        question = collect_questions(
                            page, url, out,
                            limit=question_limit,
                            max_scroll_actions=max_scroll_actions,
                            retain_masked_author=retain_masked_author,
                            resume=resume,
                            panel_wait=login_wait,
                        )
                        manifest.question_states[item_id] = question["state"]
                    except Exception as exc:
                        manifest.question_states[item_id] = "partial_runtime_error"
                        manifest.warnings.append(f"{item_id}: question collection failed ({type(exc).__name__})")
                atomic_write_json(manifest_path, manifest.as_dict())
        finally:
            context.close()

    states = list(manifest.product_states.values()) + list(manifest.review_states.values()) + list(manifest.question_states.values())
    manifest.state = "complete" if states and all(value.startswith("complete") for value in states) else "partial"
    manifest.finished_at = utc_now()
    atomic_write_json(manifest_path, manifest.as_dict())
    return manifest.as_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect visible Tmall product facts and reviews")
    parser.add_argument("mode", choices=["product", "reviews", "questions", "all"])
    parser.add_argument("--item", action="append", required=True, help="Tmall/Taobao item URL or numeric item id")
    parser.add_argument("--profile-dir", required=True, type=Path, help="Private persistent Chrome profile outside the delivery folder")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assets", default="main_images,detail_images", help="main_images,detail_images,video,review_media,none")
    parser.add_argument("--review-limit", type=int, default=0, help="0 means continue until the visible source is exhausted")
    parser.add_argument("--question-limit", type=int, default=0, help="0 means continue until the visible question panel is exhausted")
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--retain-masked-author", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = collect(
            item_urls=args.item,
            profile_dir=args.profile_dir,
            out=args.out,
            mode=args.mode,
            assets=normalize_assets(args.assets),
            review_limit=max(0, args.review_limit),
            question_limit=max(0, args.question_limit),
            max_scroll_actions=max(1, args.max_scroll_actions),
            login_wait=max(0, args.login_wait),
            retain_masked_author=args.retain_masked_author,
            resume=args.resume,
            chrome_path=args.chrome_path,
            max_asset_mb=max(1, args.max_asset_mb),
        )
    except (CollectionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
