"""Collect source-visible Weibo accounts, posts, comments, reposts and media.

The collector uses a user-selected persistent Chrome profile. It never exports
cookies, request headers, browser profiles, passwords, verification data or
signed query parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from collector_core import (
    CollectionError,
    atomic_write_json,
    canonical_hotlist_url,
    canonical_post_id,
    canonical_post_parts,
    canonical_post_url,
    canonical_profile_id,
    canonical_profile_url,
    canonical_search_url,
    canonical_supertopic_id,
    canonical_supertopic_url,
    comment_completion_state,
    derived_id,
    freeze_hotlist_snapshot,
    freeze_search_results,
    normalize_post_targets,
    normalize_hotlist_category,
    normalize_supertopic_tab,
    normalize_topic_query,
    repost_completion_state,
    sanitize_media_url,
    select_profile_posts,
    stable_pseudonym,
    utc_now,
)


POST_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const pathParts = location.pathname.split('/').filter(Boolean);
  let uid = '';
  let postId = '';
  if (/^\d+$/.test(pathParts[0] || '') && pathParts[1]) {
    uid = pathParts[0]; postId = pathParts[1];
  } else if (pathParts[0] === 'u' && /^\d+$/.test(pathParts[1] || '') && pathParts[2]) {
    uid = pathParts[1]; postId = pathParts[2];
  } else if (['detail', 'status'].includes(pathParts[0]) && pathParts[1]) {
    postId = pathParts[1];
  }
  const articles = [...document.querySelectorAll('article')];
  const article = articles.find((node) => {
    const links = [...node.querySelectorAll('a[href]')];
    return links.some((link) => {
      const href = link.href || link.getAttribute('href') || '';
      return postId && new RegExp('/' + postId + '(?:[?#/]|$)').test(href);
    });
  }) || articles[0] || document.querySelector('main');
  if (!article || !postId) return null;

  const links = [...article.querySelectorAll('a[href]')];
  const authorLink = links.find((link) => {
      const href = link.href || link.getAttribute('href') || '';
      return uid && new RegExp('(?:/u/|weibo\\.com/)' + uid + '(?:[/?#]|$)').test(href) && clean(link.textContent);
    })
    || links.find((link) => /\/u\/\d+/.test(link.getAttribute('href') || link.href || '') && clean(link.textContent))
    || links.find((link) => /\/u\/\d+/.test(link.getAttribute('href') || link.href || ''))
    || links.find((link) => /weibo\.com\/\d+(?:[/?#]|$)/.test(link.href || '') && clean(link.textContent));
  const authorHref = authorLink?.href || authorLink?.getAttribute('href') || '';
  const uidMatch = authorHref.match(/(?:\/u\/|weibo\.com\/)(\d+)/);
  uid = uid || uidMatch?.[1] || '';

  const preferred = [
    '.wbpro-feed-ogText [class*="wbtext"]', '[class*="detail_wbtext"]', '[class*="Feed_body"]', '[class*="wbtext"]',
    '[node-type="feed_list_content_full"]', '[node-type="feed_list_content"]'
  ];
  let body = '';
  for (const selector of preferred) {
    const values = [...article.querySelectorAll(selector)].map((node) => clean(node.innerText || node.textContent));
    const candidate = values.find(Boolean) || '';
    if (candidate) { body = candidate; break; }
  }
  if (!body) {
    const ignored = /^(?:公开|关注|转发|评论|赞|分享这条博文|播放视频|投诉|\d+(?:\.\d+)?[万亿wW+]?次观看)$/;
    const lines = String(article.innerText || '').split(/\n+/).map(clean).filter(Boolean);
    body = lines.filter((line) => !ignored.test(line) && line !== clean(authorLink?.textContent))
      .filter((line) => !/^\d{2,4}[-年]\d{1,2}/.test(line) && !/^来自\s/.test(line) && !/^发布于\s/.test(line))
      .filter((line) => !/(?:字幕区域背景|字体边缘样式|关闭弹窗|结束对话窗口|播放速度)/.test(line))
      .sort((a, b) => b.length - a.length)[0] || '';
  }

  const topics = [];
  const mentions = [];
  for (const link of links) {
    const text = clean(link.textContent);
    const href = link.href || link.getAttribute('href') || '';
    if ((/^#.+#$/.test(text) || /s\.weibo\.com\/weibo\?q=/.test(href)) && text.startsWith('#')) topics.push(text);
    if ((/\/n\//.test(href) || text.startsWith('@')) && text.startsWith('@')) mentions.push(text);
  }
  const unique = (values) => [...new Set(values.filter(Boolean))];
  const articleText = clean(article.innerText || article.textContent);
  const lines = String(article.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const postLinks = links.filter((link) => postId && new RegExp('/' + postId + '(?:[?#/]|$)').test(link.href || ''));
  const timeLink = postLinks.find((link) => /(?:^|\s)_time_/.test(String(link.className || '')))
    || postLinks.find((link) => /\d{2,4}[-年]\d{1,2}|\d+分钟前|\d+小时前|昨天|刚刚/.test(clean(link.getAttribute('title') || link.textContent)))
    || postLinks[0];
  const sourceLine = lines.find((line) => /^来自\s+/.test(line)) || '';
  const regionLine = lines.find((line) => /^发布于\s+/.test(line)) || '';
  const views = (articleText.match(/([0-9.万亿wW+]+)\s*次观看/) || [])[1] || '';

  const metric = (label) => {
    const icon = article.querySelector(`[title="${label}"]`);
    const item = icon?.closest('[class*="_item_"][class*="_cursor_"]');
    const itemText = clean(item?.textContent);
    if (/^[0-9.万亿wW+]+$/.test(itemText)) return itemText;
    const nodes = [...article.querySelectorAll('button,span,div')].filter((node) => clean(node.textContent) === label);
    for (const node of nodes) {
      const parentText = clean(node.parentElement?.innerText || node.parentElement?.textContent);
      const match = parentText.match(new RegExp(label + '\\s*([0-9.万亿wW+]+)'))
        || parentText.match(new RegExp('([0-9.万亿wW+]+)\\s*' + label));
      if (match) return match[1];
    }
    return '';
  };

  const posterNode = article.querySelector('video[poster]');
  const videoCoverNode = [...article.querySelectorAll('[class*="feedVideo"] img, [class*="video"] img')].find((image) => {
    const source = image.currentSrc || image.src || '';
    const width = image.naturalWidth || image.clientWidth || 0;
    const height = image.naturalHeight || image.clientHeight || 0;
    return /^https?:\/\//i.test(source) && /sinaimg|weibocdn/i.test(source) && width >= 180 && height >= 120;
  });
  const poster = posterNode?.poster || videoCoverNode?.currentSrc || videoCoverNode?.src || '';
  const posterKey = poster.split('?')[0];
  const images = [];
  const imageSeen = new Set();
  for (const image of [...article.querySelectorAll('img')]) {
    const source = image.currentSrc || image.src || '';
    const width = image.naturalWidth || image.clientWidth || 0;
    const height = image.naturalHeight || image.clientHeight || 0;
    if (!/^https?:\/\//i.test(source) || /avatar|icon|emoji|face|head/i.test(source)) continue;
    if (image.closest('header, [class*="avatar"], [class*="Avatar"]')) continue;
    if (!/(sinaimg|weibocdn|weibo\.com)/i.test(source) || (width && width < 180) || (height && height < 120)) continue;
    const key = source.split('?')[0];
    if (posterKey && key === posterKey) continue;
    if (imageSeen.has(key)) continue;
    imageSeen.add(key);
    images.push({src: source, width, height});
  }
  const videos = [];
  const videoSeen = new Set();
  let hasBlobVideo = false;
  for (const node of [...article.querySelectorAll('video,video source')]) {
    const source = node.currentSrc || node.src || node.getAttribute('src') || '';
    if (source.startsWith('blob:')) hasBlobVideo = true;
    if (!/^https?:\/\//i.test(source)) continue;
    const key = source.split('?')[0];
    if (videoSeen.has(key)) continue;
    videoSeen.add(key);
    videos.push({src: source, width: node.videoWidth || node.clientWidth || 0, height: node.videoHeight || node.clientHeight || 0});
  }
  const originalLink = links.find((link) => {
    const href = link.href || '';
    const match = href.match(/weibo\.com\/(\d+)\/([A-Za-z0-9]+)/);
    return match && match[2] !== postId;
  });
  const originalMatch = (originalLink?.href || '').match(/weibo\.com\/(\d+)\/([A-Za-z0-9]+)/);
  return {
    post_id: postId,
    author_uid: uid,
    author_name: clean(authorLink?.textContent),
    body,
    topics: unique(topics),
    mentions: unique(mentions),
    published_at_text: clean(timeLink?.getAttribute('title') || timeLink?.textContent),
    region_text: regionLine.replace(/^发布于\s*/, ''),
    source_text: sourceLine.replace(/^来自\s*/, ''),
    visibility_text: lines.find((line) => /^(?:公开|仅自己可见|好友圈)$/.test(line)) || '',
    metrics: {views, reposts: metric('转发'), comments: metric('评论'), likes: metric('赞')},
    original_post_id: originalMatch?.[2] || '',
    original_author_uid: originalMatch?.[1] || '',
    images,
    videos,
    cover: poster ? {src: poster, width: 0, height: 0} : null,
    has_blob_video: hasBlobVideo,
  };
}
"""


PROFILE_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const pathParts = location.pathname.split('/').filter(Boolean);
  const uid = pathParts[0] === 'u' ? (pathParts[1] || '') : (pathParts[0] || '');
  if (!/^\d+$/.test(uid)) return {account: {}, posts: []};
  const main = document.querySelector('main') || document.body;
  const mainText = String(main.innerText || '');
  const lines = mainText.split(/\n+/).map(clean).filter(Boolean);
  const stat = (label) => {
    const link = [...main.querySelectorAll('a')].find((node) => clean(node.textContent).endsWith(label));
    const text = clean(link?.textContent);
    return text.replace(new RegExp('\\s*' + label + '$'), '') || '';
  };
  const titleName = clean(document.title).replace(/的微博.*$/, '').replace(/[-–—]\s*微博.*$/, '').replace(/^@/, '').replace(/\s*的个人主页$/, '');
  const heading = main.querySelector('h1') || main.querySelector('h2');
  const headingName = clean(heading?.textContent).replace(/^@/, '').replace(/\s*的个人主页$/, '');
  const profileName = titleName && !/^(?:微博|首页)$/.test(titleName) ? titleName : headingName;
  let headerRoot = heading?.parentElement || null;
  let bestHeaderRoot = headerRoot;
  for (let step = 0; headerRoot && step < 7; step += 1, headerRoot = headerRoot.parentElement) {
    const text = clean(headerRoot.innerText || headerRoot.textContent);
    if (text.length >= profileName.length && text.length <= 700) bestHeaderRoot = headerRoot;
    if (text.length > 700) break;
  }
  const headerLines = String(bestHeaderRoot?.innerText || '').split(/\n+/).map(clean).filter(Boolean);
  const verification = headerLines.find((line) =>
    line !== profileName && line.length <= 100
      && /(?:个人认证|微博认证|官方微博|官方账号|工作室官方微博|品牌官方微博|演员|歌手|主持人|博主)/.test(line)
      && !/(?:转发|评论|点赞|发布|来自|超话|\d{1,2}:\d{2})/.test(line)
  ) || '';
  const descriptionLine = headerLines.find((line) => /^(?:简介|简介：|简介:)/.test(line)) || '';
  const description = descriptionLine.replace(/^(?:简介|简介：|简介:)\s*/, '');

  const posts = [];
  const seen = new Set();
  for (const article of [...main.querySelectorAll('article')]) {
    const links = [...article.querySelectorAll('a[href]')];
    let postLink = null;
    let match = null;
    for (const link of links) {
      const href = link.href || link.getAttribute('href') || '';
      const current = href.match(/weibo\.com\/(\d+)\/([A-Za-z0-9]{5,32})/);
      if (current) { postLink = link; match = current; break; }
    }
    if (!match || seen.has(match[2])) continue;
    seen.add(match[2]);
    const text = clean(article.innerText || article.textContent);
    const candidateNodes = [...article.querySelectorAll('[class*="wbtext"], [class*="Feed_body"], [node-type*="feed_list_content"]')];
    const body = candidateNodes.map((node) => clean(node.innerText || node.textContent)).sort((a, b) => b.length - a.length)[0] || text.slice(0, 500);
    const cover = [...article.querySelectorAll('img')].find((image) => {
      const source = image.currentSrc || image.src || '';
      return /sinaimg|weibocdn/i.test(source) && (image.naturalWidth || 0) >= 180;
    });
    posts.push({
      post_id: match[2],
      author_uid: match[1],
      rank: posts.length + 1,
      is_pinned: /(?:^|\s)置顶(?:\s|$)/.test(text),
      body_preview: body.slice(0, 500),
      published_at_text: clean(postLink?.textContent),
      navigation_url: postLink?.href || `https://weibo.com/${match[1]}/${match[2]}`,
      cover_url: cover?.currentSrc || cover?.src || '',
    });
  }
  return {
    account: {
      uid,
      display_name: profileName,
      verification_text: verification,
      description,
      following_text: stat('关注'),
      followers_text: stat('粉丝'),
      posts_text: stat('微博'),
    },
    posts,
  };
}
"""


SEARCH_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const roots = [...document.querySelectorAll('[action-type="feed_list_item"], .card-wrap, article')];
  const results = [];
  const seen = new Set();
  for (const root of roots) {
    const links = [...root.querySelectorAll('a[href]')];
    let postLink = null;
    let match = null;
    for (const link of links) {
      const href = link.href || link.getAttribute('href') || '';
      const current = href.match(/weibo\.com\/(?:u\/)?(\d+)\/([A-Za-z0-9]{5,32})/);
      if (current) { postLink = link; match = current; break; }
    }
    if (!match || seen.has(match[2])) continue;
    seen.add(match[2]);
    const authorLink = links.find((link) => /(?:\/u\/|weibo\.com\/u\/)(\d+)/.test(link.href || link.getAttribute('href') || ''));
    const rootText = clean(root.innerText || root.textContent);
    const bodyNodes = [...root.querySelectorAll('[node-type*="feed_list_content"], [class*="content"], [class*="wbtext"]')];
    const body = bodyNodes.map((node) => clean(node.innerText || node.textContent)).sort((a, b) => b.length - a.length)[0] || rootText.slice(0, 500);
    const image = [...root.querySelectorAll('img')].find((node) => {
      const source = node.currentSrc || node.src || '';
      return /sinaimg|weibocdn/i.test(source) && (node.naturalWidth || 0) >= 180;
    });
    results.push({
      post_id: match[2],
      author_uid: match[1],
      author_name: clean(authorLink?.textContent),
      rank: results.length + 1,
      body_preview: body.slice(0, 500),
      published_at_text: clean(postLink?.textContent),
      promoted_state: /(?:广告|推广|赞助)/.test(rootText) ? 'observed_visible_mark' : 'not_observed',
      cover_url: image?.currentSrc || image?.src || '',
      navigation_url: postLink?.href || `https://weibo.com/${match[1]}/${match[2]}`,
    });
  }
  const pageText = clean(document.body?.innerText || document.documentElement?.innerText || '');
  const topicContext = {};
  const readMatch = pageText.match(/(?:阅读|阅读量)\s*([0-9.万亿wW+]+)/);
  const discussMatch = pageText.match(/(?:讨论|讨论量)\s*([0-9.万亿wW+]+)/);
  if (readMatch) topicContext.read_text = readMatch[1];
  if (discussMatch) topicContext.discuss_text = discussMatch[1];
  return {
    query: clean(document.querySelector('input[name="q"], input[type="search"], input[placeholder*="搜索"]')?.value),
    sort: clean(document.querySelector('.searchbox .cur, .m-main-nav .cur, [class*="active"]')?.textContent) || '综合',
    results,
    topic_context: topicContext,
  };
}
"""


SUPERTOPIC_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const pageText = clean(document.body.innerText || '');
  const pathParts = location.pathname.split('/').filter(Boolean);
  const supertopicId = pathParts.find((part) => /^100808[A-Za-z0-9]{8,80}$/.test(part)) || '';
  const titleName = clean(document.title).replace(/超话.*$/, '');
  const tabs = [...document.querySelectorAll('.wbpro-tab2 .wbpro-textcut')].map((node) => clean(node.textContent)).filter(Boolean);
  const activeTabNode = document.querySelector('.wbpro-tab2 .woo-box-item-inlineBlock.cur .wbpro-textcut');
  const postCount = (pageText.match(/([0-9.万亿wW+]+)\s*帖子/) || [])[1] || '';
  const memberMatch = pageText.match(/帖子\s*([0-9.万亿wW+]+)\s*([^\s]{1,12})\s*(?:发帖|关注)/);
  const checkinMatch = pageText.match(/今日签到\s*([0-9.万亿wW+]+)(?:人)?(?:\s*(No\.\s*\d+))?/i);
  const categoryMatch = pageText.match(/(?:明星|影视|综艺|音乐|体育|游戏|动漫|兴趣|社会|公益|品牌|企业)超话/);
  const results = [];
  const seen = new Set();
  for (const article of [...document.querySelectorAll('article')]) {
    const links = [...article.querySelectorAll('a[href]')];
    let postLink = null;
    let match = null;
    for (const link of links) {
      const href = link.href || link.getAttribute('href') || '';
      const current = href.match(/weibo\.com\/(?:u\/)?(\d+)\/([A-Za-z0-9]{5,32})/);
      if (current) { postLink = link; match = current; break; }
    }
    if (!match || seen.has(match[2])) continue;
    seen.add(match[2]);
    const authorLink = links.find((link) => /(?:\/u\/|weibo\.com\/u\/)(\d+)/.test(link.href || link.getAttribute('href') || '') && clean(link.textContent));
    const rootText = clean(article.innerText || article.textContent);
    const bodyNode = article.querySelector('.wbpro-feed-content [class*="wbtext"], .wbpro-feed-content .wbpro-feed-ogText, [node-type*="feed_list_content"]');
    const body = clean(bodyNode?.innerText || bodyNode?.textContent) || rootText.slice(0, 800);
    const image = [...article.querySelectorAll('.picture img, .wbpro-feed-content .woo-picture-img, .wbpro-feed-content video[poster]')].find((node) => {
      const source = node.currentSrc || node.src || '';
      return /sinaimg|weibocdn/i.test(source) && !/avatar|face|expression|timeline_card|small_super_default/i.test(source);
    });
    results.push({
      post_id: match[2],
      author_uid: match[1],
      author_name: clean(authorLink?.textContent),
      rank: results.length + 1,
      body_preview: body.slice(0, 800),
      published_at_text: clean(postLink?.textContent),
      is_pinned: /(?:^|\s)置顶(?:\s|$)/.test(rootText),
      promoted_state: /(?:广告|推广|赞助)/.test(rootText) ? 'observed_visible_mark' : 'not_observed',
      cover_url: image?.currentSrc || image?.src || image?.poster || '',
      navigation_url: postLink?.href || `https://weibo.com/${match[1]}/${match[2]}`,
    });
  }
  return {
    results,
    supertopic_context: {
      supertopic_id: supertopicId,
      name: titleName,
      canonical_url: location.origin + '/p/' + supertopicId + '/super_index?mod=TAB',
      category_text: categoryMatch?.[0] || '',
      post_count_text: postCount,
      member_count_text: memberMatch?.[1] || '',
      member_label_text: memberMatch?.[2] || '',
      checkin_text: checkinMatch?.[1] || '',
      rank_text: clean(checkinMatch?.[2] || ''),
      visible_tabs: [...new Set(tabs)],
      selected_tab: clean(activeTabNode?.textContent),
    },
  };
}
"""


HOTLIST_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const entries = [];
  const rows = [...document.querySelectorAll('table tbody tr')];
  for (const row of rows) {
    const rankCell = row.querySelector('td.td-01, td[class*="td-01"]');
    const termCell = row.querySelector('td.td-02, td[class*="td-02"]');
    const labelCell = row.querySelector('td.td-03, td[class*="td-03"]');
    if (!termCell) continue;
    const link = termCell.querySelector('a');
    const keyword = clean(link?.textContent || termCell.querySelector('span')?.textContent);
    if (!keyword) continue;
    const rankText = clean(rankCell?.innerText || rankCell?.textContent);
    const rankMatch = rankText.match(/^([0-9]+)$/);
    const rankNumeric = Number(rankMatch?.[1] || 0);
    const fullText = clean(termCell.innerText || termCell.textContent);
    let remainder = fullText.startsWith(keyword) ? clean(fullText.slice(keyword.length)) : fullText;
    const heatMatch = remainder.match(/([0-9]+(?:\.[0-9]+)?[万亿wW+]?)$/);
    const heatText = clean(heatMatch?.[1] || '');
    if (heatMatch) remainder = clean(remainder.slice(0, heatMatch.index));
    const rawHref = link?.getAttribute('href') || '';
    let queryUrl = '';
    if (rawHref && !/^javascript:/i.test(rawHref)) {
      try { queryUrl = new URL(rawHref, location.origin).href; } catch (_) {}
    }
    const labelText = clean(labelCell?.innerText || labelCell?.textContent);
    const hasPinIcon = Boolean(rankCell?.querySelector('i[class*="icon-top"], img[alt*="置顶"], [title*="置顶"]'));
    const isPinned = hasPinIcon || (!rankText && entries.length === 0);
    const isSpecial = !rankNumeric && !isPinned;
    entries.push({
      observed_position: entries.length + 1,
      rank_text: rankText,
      rank_numeric: rankNumeric,
      keyword,
      heat_text: heatText,
      topic_category_text: remainder,
      label_text: labelText,
      is_pinned: isPinned,
      is_special: isSpecial,
      query_url: queryUrl,
    });
  }
  const nav = [...document.querySelectorAll('a[href*="/top/summary"]')].map((node) => ({
    name: clean(node.textContent), href: node.href || node.getAttribute('href') || ''
  })).filter((item) => item.name);
  return {
    page_title: clean(document.title),
    visible_categories: nav,
    entries,
  };
}
"""


COMMENTS_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const main = document.querySelector('main') || document.body;
  const rows = [];
  const parseCard = (card, level, declaredReplyCount = 0) => {
    const textNode = card.querySelector('.text') || card.querySelector('[class*="text"]') || card;
    const authorLink = textNode.querySelector('a[href*="/u/"]') || card.querySelector('a[href*="/u/"]');
    if (!authorLink) return null;
    const href = authorLink.href || authorLink.getAttribute('href') || '';
    const uid = (href.match(/\/u\/(\d+)/) || [])[1] || '';
    const infoText = clean(card.querySelector('.info')?.innerText || card.querySelector('.info')?.textContent || card.innerText || card.textContent);
    const timeMatch = infoText.match(/(\d+分钟前|\d+小时前|昨天\s*\d{1,2}:\d{2}|\d{2,4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?|\d{2,4}-\d{1,2}(?:\s+\d{1,2}:\d{2})?|\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?)/);
    const regionMatch = infoText.match(/来自\s+([^\s]+)/);
    const authorName = clean(authorLink.textContent);
    let content = clean(textNode.innerText || textNode.textContent);
    if (authorName && content.startsWith(authorName)) content = content.slice(authorName.length).replace(/^\s*:\s*/, '').trim();
    const commentId = card.getAttribute('data-comment-id') || card.getAttribute('commentid') || card.dataset?.id || '';
    const parentId = card.getAttribute('data-parent-id') || card.dataset?.parentId || '';
    const rootId = card.getAttribute('data-root-id') || card.dataset?.rootId || '';
    const likeText = clean(card.querySelector('.woo-like-count')?.textContent);
    return {
      platform_comment_id: commentId,
      parent_platform_id: parentId,
      root_platform_id: rootId,
      level,
      author_name: authorName,
      author_platform_id: uid,
      content,
      time_text: timeMatch?.[1] || '',
      region_text: regionMatch?.[1] || '',
      like_count_text: /^[0-9.万亿wW+]+$/.test(likeText) ? likeText : '',
      declared_reply_count: level === 1 ? Number(declaredReplyCount || 0) : 0,
    };
  };
  const roots = [...main.querySelectorAll('.item1')];
  for (const root of roots) {
    const rootCard = root.querySelector(':scope > .item1in');
    if (!rootCard) continue;
    const replyLabel = [...root.querySelectorAll(':scope > .list2 a')]
      .map((node) => clean(node.textContent)).find((value) => /(?:共|展开)\s*\d+\s*条回复/.test(value)) || '';
    const declaredReplyCount = Number((replyLabel.match(/(\d+)/) || [])[1] || 0);
    const rootRow = parseCard(rootCard, 1, declaredReplyCount);
    if (rootRow) rows.push(rootRow);
    for (const replyCard of [...root.querySelectorAll(':scope > .list2 > .item2')]) {
      if (!replyCard.querySelector('a[href*="/u/"]')) continue;
      const replyRow = parseCard(replyCard, 2, 0);
      if (replyRow) rows.push(replyRow);
    }
  }
  const text = clean(main.innerText || main.textContent);
  const declared = (text.match(/([0-9.万亿wW+]+)\s*条评论/)
    || text.match(/评论\s*([0-9.万亿wW+]+)/) || [])[1] || '';
  const exhausted = /(?:已显示全部评论|没有更多评论|暂无更多评论|THE END)/i.test(text);
  const loginLimited = /(?:请登录后查看更多精彩内容|登录后查看更多评论|登录后查看更多)/.test(text);
  const sortNodes = [...document.querySelectorAll('button,a,[role="tab"],li,span,div')];
  const selectedSort = ['按热度', '按时间'].find((label) => sortNodes.some((node) => {
    if (clean(node.textContent) !== label) return false;
    const target = node.closest('button,a,[role="tab"],li') || node;
    const marker = `${target.className || ''} ${target.getAttribute('aria-selected') || ''}`;
    return /(?:curr|active|selected|true)/i.test(marker);
  })) || '';
  return {rows, declared, exhausted, login_limited: loginLimited, selected_sort: selectedSort};
}
"""


COMMENT_SORT_DISCOVERY_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (node) => {
    const style = window.getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden';
  };
  const nodes = [...document.querySelectorAll('button,a,[role="tab"],li,span,div')];
  return ['按热度', '按时间'].filter((label) => nodes.some((node) =>
    visible(node) && clean(node.textContent) === label
  ));
}
"""


COMMENT_SORT_ACTIVATE_SCRIPT = r"""
(label) => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const visible = (node) => {
    const style = window.getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden';
  };
  const nodes = [...document.querySelectorAll('button,a,[role="tab"],li,span,div')]
    .filter((node) => visible(node) && clean(node.textContent) === label);
  if (!nodes.length) return {available: false, selected_before: false};
  const node = nodes[0];
  const target = node.closest('button,a,[role="tab"],li,div') || node;
  const marker = `${target.className || ''} ${target.getAttribute('aria-selected') || ''}`;
  const selected = /(?:curr|active|selected|true)/i.test(marker);
  if (!selected) target.click();
  return {available: true, selected_before: selected};
}
"""


COMMENT_SCROLL_STATE_SCRIPT = r"""
() => {
  const root = document.scrollingElement || document.documentElement;
  const top = Number(root.scrollTop || window.scrollY || 0);
  const height = Number(root.scrollHeight || document.documentElement.scrollHeight || 0);
  const viewport = Number(window.innerHeight || document.documentElement.clientHeight || 0);
  return {
    top,
    height,
    viewport,
    at_bottom: top + viewport >= height - 24,
  };
}
"""


COMMENT_SCROLL_STEP_SCRIPT = r"""
() => {
  const root = document.scrollingElement || document.documentElement;
  const top = Number(root.scrollTop || window.scrollY || 0);
  const height = Number(root.scrollHeight || document.documentElement.scrollHeight || 0);
  const viewport = Number(window.innerHeight || document.documentElement.clientHeight || 0);
  const atBottom = top + viewport >= height - 24;
  const next = atBottom ? height : top + Math.max(700, viewport * 0.85);
  root.scrollTop = next;
  window.dispatchEvent(new Event('scroll'));
  return {top, height, viewport, at_bottom: atBottom, next_top: next};
}
"""


COMMENT_SCROLL_TOP_SCRIPT = r"""
() => {
  const root = document.scrollingElement || document.documentElement;
  root.scrollTop = 0;
  window.dispatchEvent(new Event('scroll'));
  return true;
}
"""


REPOSTS_SCRIPT = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const main = document.querySelector('main') || document.body;
  const repostControl = main.querySelector('article i[title="转发"]')
    ?.closest('[class*="_retweet_"][class*="_wrap_"]');
  const active = Boolean(repostControl && /(?:^|\s)_cur_[^\s]*/.test(String(repostControl.className || '')));
  if (!active) return {rows: [], available: false, exhausted: false, active: false};
  const cards = [...main.querySelectorAll('.item1')].filter((card) =>
    card.querySelector(':scope > .item1in .text a[href*="/u/"]')
  );
  const rows = [];
  for (const card of cards) {
    const root = card.querySelector(':scope > .item1in');
    const textNode = root?.querySelector('.text');
    const authorLink = textNode?.querySelector('a[href*="/u/"]');
    if (!authorLink) continue;
    const href = authorLink.href || authorLink.getAttribute('href') || '';
    const uid = (href.match(/\/u\/(\d+)/) || [])[1] || '';
    const info = root.querySelector('.info');
    const infoText = clean(info?.innerText || info?.textContent);
    const timeMatch = infoText.match(/(\d+分钟前|\d+小时前|昨天\s*\d{1,2}:\d{2}|\d{2,4}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?|\d{2,4}-\d{1,2}(?:\s+\d{1,2}:\d{2})?|\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2})?)/);
    const regionMatch = infoText.match(/来自\s+([^\s]+)/);
    const postLink = info?.querySelector('a[href]');
    const postHref = postLink?.href || postLink?.getAttribute('href') || '';
    const repostId = (postHref.match(/weibo\.com\/(?:u\/)?\d+\/([A-Za-z0-9]{5,32})/) || [])[1] || '';
    const authorName = clean(authorLink.textContent);
    let content = clean(textNode.innerText || textNode.textContent);
    if (authorName && content.startsWith(authorName)) content = content.slice(authorName.length).replace(/^\s*:\s*/, '').trim();
    rows.push({
      platform_repost_id: repostId,
      upstream_platform_id: '',
      author_name: authorName,
      author_platform_id: uid,
      content,
      time_text: timeMatch?.[1] || '',
      region_text: regionMatch?.[1] || '',
      metrics: {},
    });
  }
  const pageText = clean(main.innerText || main.textContent);
  return {
    rows,
    available: active,
    exhausted: /(?:已显示全部转发|没有更多转发|暂无更多转发|THE END)/i.test(pageText),
    active,
  };
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
    allowed = {"images", "video", "cover", "none"}
    parts: list[str] = []
    for raw in str(value or "").split(","):
        part = raw.strip()
        if part and part not in parts:
            parts.append(part)
    unknown = [part for part in parts if part not in allowed]
    if unknown:
        raise CollectionError(f"Unknown asset type(s): {', '.join(unknown)}")
    if "none" in parts and len(parts) > 1:
        raise CollectionError("assets=none cannot be combined with other asset types")
    return [] if parts == ["none"] else parts


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _read_jsonl_ids(path: Path, field: str) -> set[str]:
    return {str(row.get(field) or "") for row in _read_jsonl_rows(path) if row.get(field)}


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    values = list(rows)
    if not values:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for row in values:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Replace a JSONL file without exposing a partially written union."""
    values = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            for row in values:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt >= 5:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink()


def _new_unique_rows(
    rows: Iterable[dict[str, Any]], id_field: str, saved: set[str], remaining: int = 0,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen = set(saved)
    for row in rows:
        record_id = str(row.get(id_field) or "")
        if not record_id or record_id in seen:
            continue
        seen.add(record_id)
        output.append(row)
        if remaining > 0 and len(output) >= remaining:
            break
    return output


def _profile_pinned_ids_from_payload(payload: Any) -> set[str]:
    """Keep only public post ids carrying Weibo's own pinned marker."""
    if not isinstance(payload, dict):
        return set()
    data = payload.get("data")
    if not isinstance(data, dict):
        return set()
    rows = data.get("list")
    if not isinstance(rows, list):
        return set()
    output: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        marker = row.get("isTop")
        if marker not in (1, True, "1", "true", "True"):
            continue
        post_id = str(row.get("mblogid") or "").strip()
        if post_id:
            output.add(post_id)
    return output


def _extension(clean_url: str, content_type: str, kind: str) -> str:
    suffix = Path(clean_url).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v"}:
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) if content_type else None
    return guessed or (".mp4" if kind == "video" else ".jpg")


def _download_asset(context: Any, source: str, target_base: Path, *, kind: str, max_bytes: int) -> dict[str, Any]:
    clean_url, redacted = sanitize_media_url(source)
    response = context.request.get(source, headers={"Referer": "https://weibo.com/"}, timeout=90_000)
    if not response.ok:
        raise CollectionError(f"Asset request returned HTTP {response.status}")
    body = response.body()
    if len(body) > max_bytes:
        raise CollectionError("Asset exceeds configured size limit")
    content_type = response.headers.get("content-type", "")
    target = target_base.with_suffix(_extension(clean_url, content_type, kind))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {
        "status": "downloaded",
        "local_file": str(target),
        "source_url": clean_url,
        "source_url_query_redacted": redacted,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _page_blocker(page: Any) -> str:
    url = str(page.url or "")
    if "passport.weibo.com" in url or "login" in url:
        return "login"
    if page.locator("main article").count():
        return ""
    login_labels = {"扫码登录", "账号登录", "请登录后使用"}
    for label in ["安全验证", "访问频繁", "请输入验证码", *login_labels]:
        if page.get_by_text(label, exact=False).count():
            return "login" if label in login_labels else "verification"
    return ""


def _goto_visible(page: Any, url: str, login_wait: int) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(2_500)
    blocker = _page_blocker(page)
    if blocker and login_wait > 0:
        print(f"Visible Chrome is ready. Complete Weibo login or confirmation within {login_wait} seconds.")
        for _ in range(login_wait):
            page.wait_for_timeout(1_000)
            blocker = _page_blocker(page)
            if not blocker:
                break
        if blocker:
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(2_500)
            blocker = _page_blocker(page)
    if blocker:
        raise CollectionError("Weibo requires manual login or verification in the visible Chrome window")


def _public_profile_selection(selection: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in selection.items() if key != "selected"}
    public_rows: list[dict[str, Any]] = []
    for record in selection.get("selected") or []:
        post_id = str(record.get("post_id") or "")
        cover_url = ""
        if record.get("cover_url"):
            try:
                cover_url, _ = sanitize_media_url(str(record["cover_url"]))
            except CollectionError:
                pass
        public_rows.append({
            "post_id": post_id,
            "author_uid": str(record.get("author_uid") or selection.get("profile_id") or ""),
            "rank": int(record.get("rank") or 0),
            "is_pinned": bool(record.get("is_pinned")),
            "selection_reason": str(record.get("selection_reason") or ""),
            "body_preview": str(record.get("body_preview") or ""),
            "published_at_text": str(record.get("published_at_text") or ""),
            "cover_url": cover_url,
            "canonical_url": canonical_post_url(post_id, str(record.get("author_uid") or selection.get("profile_id") or "")),
        })
    public["selected"] = public_rows
    return public


def _public_search_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in snapshot.items() if key != "results"}
    public_rows: list[dict[str, Any]] = []
    for record in snapshot.get("results") or []:
        post_id = str(record.get("post_id") or "")
        uid = str(record.get("author_uid") or "")
        cover_url = ""
        if record.get("cover_url"):
            try:
                cover_url, _ = sanitize_media_url(str(record["cover_url"]))
            except CollectionError:
                pass
        public_rows.append({
            "search_snapshot_id": str(record.get("search_snapshot_id") or snapshot.get("search_snapshot_id") or ""),
            "post_id": post_id,
            "author_uid": uid,
            "author_name": str(record.get("author_name") or ""),
            "rank": int(record.get("rank") or 0),
            "body_preview": str(record.get("body_preview") or ""),
            "published_at_text": str(record.get("published_at_text") or ""),
            "promoted_state": str(record.get("promoted_state") or "not_observed"),
            "cover_url": cover_url,
            "canonical_url": canonical_post_url(post_id, uid),
        })
    public["results"] = public_rows
    return public


def _public_hotlist_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in snapshot.items() if key != "entries"}
    public["entries"] = [{
        "hotlist_snapshot_id": str(row.get("hotlist_snapshot_id") or snapshot.get("hotlist_snapshot_id") or ""),
        "category_code": str(row.get("category_code") or snapshot.get("category_code") or ""),
        "category_name": str(row.get("category_name") or snapshot.get("category_name") or ""),
        "observed_position": int(row.get("observed_position") or 0),
        "rank_text": str(row.get("rank_text") or ""),
        "rank_numeric": int(row.get("rank_numeric") or 0),
        "keyword": str(row.get("keyword") or ""),
        "heat_text": str(row.get("heat_text") or ""),
        "topic_category_text": str(row.get("topic_category_text") or ""),
        "label_text": str(row.get("label_text") or ""),
        "is_pinned": bool(row.get("is_pinned")),
        "is_special": bool(row.get("is_special")),
        "query_url": str(row.get("query_url") or ""),
        "captured_at": str(row.get("captured_at") or snapshot.get("captured_at") or ""),
    } for row in snapshot.get("entries") or []]
    return public


def _discover_profile_posts(page: Any, target: str, *, recent: int, max_scroll_actions: int, login_wait: int) -> dict[str, Any]:
    profile_id = canonical_profile_id(target)
    url = canonical_profile_url(profile_id)
    pinned_by_id: set[str] = set()

    def observe_profile_response(response: Any) -> None:
        if "/ajax/statuses/mymblog" not in str(getattr(response, "url", "")):
            return
        try:
            pinned_by_id.update(_profile_pinned_ids_from_payload(response.json()))
        except Exception:
            return

    page.on("response", observe_profile_response)
    try:
        _goto_visible(page, url, login_wait)
    finally:
        page.remove_listener("response", observe_profile_response)
    records_by_id: dict[str, dict[str, Any]] = {}
    account: dict[str, Any] = {}
    no_growth = 0
    scroll_actions = 0
    while scroll_actions <= max_scroll_actions:
        raw = page.evaluate(PROFILE_SCRIPT) or {}
        account = dict(raw.get("account") or account)
        before = len(records_by_id)
        for record in raw.get("posts") or []:
            post_id = str(record.get("post_id") or "").strip()
            if post_id and post_id not in records_by_id:
                row = dict(record)
                row["rank"] = len(records_by_id) + 1
                row["is_pinned"] = bool(row.get("is_pinned") or post_id in pinned_by_id)
                records_by_id[post_id] = row
        selected = select_profile_posts(records_by_id.values(), recent)
        if selected["state"].startswith("complete"):
            break
        no_growth = no_growth + 1 if len(records_by_id) == before else 0
        if no_growth >= 3 or scroll_actions >= max_scroll_actions:
            break
        page.evaluate("window.scrollBy({top: Math.max(700, window.innerHeight * 0.8), behavior: 'instant'})")
        page.wait_for_timeout(900)
        scroll_actions += 1
    if not records_by_id:
        raise CollectionError("No visible Weibo profile posts were found")
    selected = select_profile_posts(records_by_id.values(), recent)
    captured_at = utc_now()
    account.update({
        "uid": profile_id,
        "canonical_url": canonical_profile_url(profile_id),
        "collected_at": captured_at,
        "completion_state": "complete_visible_account",
    })
    return {
        "schema_version": "1.0",
        "profile_selection_id": derived_id("profile-selection", profile_id, recent, captured_at),
        "profile_id": profile_id,
        "canonical_url": canonical_profile_url(profile_id),
        "account": account,
        "captured_at": captured_at,
        "discovered_count": len(records_by_id),
        "scroll_actions": scroll_actions,
        **selected,
    }


def _discover_search_results(
    page: Any, query: str, *, query_kind: str, limit: int,
    max_scroll_actions: int, login_wait: int,
) -> dict[str, Any]:
    value = normalize_topic_query(query) if query_kind == "topic" else str(query or "").strip()
    if not value:
        raise CollectionError("Search query must not be empty")
    _goto_visible(page, canonical_search_url(value, topic=query_kind == "topic"), login_wait)
    records_by_id: dict[str, dict[str, Any]] = {}
    topic_context: dict[str, Any] = {}
    no_growth = 0
    scroll_actions = 0
    observed_sort = "综合"
    while scroll_actions <= max_scroll_actions:
        raw = page.evaluate(SEARCH_SCRIPT) or {}
        observed_sort = str(raw.get("sort") or observed_sort)
        topic_context.update(dict(raw.get("topic_context") or {}))
        before = len(records_by_id)
        for record in raw.get("results") or []:
            post_id = str(record.get("post_id") or "").strip()
            if post_id and post_id not in records_by_id:
                row = dict(record)
                row["rank"] = len(records_by_id) + 1
                records_by_id[post_id] = row
        if len(records_by_id) >= limit:
            break
        no_growth = no_growth + 1 if len(records_by_id) == before else 0
        if no_growth >= 3 or scroll_actions >= max_scroll_actions:
            break
        page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})")
        page.wait_for_timeout(900)
        scroll_actions += 1
    if not records_by_id:
        raise CollectionError("No visible Weibo search-result posts were found")
    snapshot = freeze_search_results(
        records_by_id.values(), query=value, query_kind=query_kind, sort=observed_sort,
        filters=[], limit=limit, captured_at=utc_now(), topic_context=topic_context,
    )
    snapshot.update({
        "schema_version": "1.0",
        "discovered_count": len(records_by_id),
        "scroll_actions": scroll_actions,
        "completion_basis": "requested_first_n_visible_results" if snapshot["state"].startswith("complete") else "scroll_or_growth_budget_exhausted",
    })
    return snapshot


def _discover_supertopic_results(
    page: Any, target: str, *, tab: str, limit: int,
    max_scroll_actions: int, login_wait: int,
) -> dict[str, Any]:
    supertopic_id = canonical_supertopic_id(target)
    url = canonical_supertopic_url(target)
    selected_tab = normalize_supertopic_tab(tab)
    _goto_visible(page, url, login_wait)

    tab_nodes = page.locator(".wbpro-tab2 .wbpro-textcut")
    matching_index = -1
    for index in range(tab_nodes.count()):
        if str(tab_nodes.nth(index).inner_text() or "").strip() == selected_tab:
            matching_index = index
            break
    if matching_index < 0:
        raise CollectionError(f"The visible supertopic tab was not found: {selected_tab}")
    tab_nodes.nth(matching_index).click()
    page.wait_for_timeout(1_800)

    records_by_id: dict[str, dict[str, Any]] = {}
    supertopic_context: dict[str, Any] = {}
    no_growth = 0
    scroll_actions = 0
    while scroll_actions <= max_scroll_actions:
        raw = page.evaluate(SUPERTOPIC_SCRIPT) or {}
        supertopic_context.update(dict(raw.get("supertopic_context") or {}))
        before = len(records_by_id)
        for record in raw.get("results") or []:
            post_id = str(record.get("post_id") or "").strip()
            if post_id and post_id not in records_by_id:
                row = dict(record)
                row["rank"] = len(records_by_id) + 1
                records_by_id[post_id] = row
        if len(records_by_id) >= limit:
            break
        no_growth = no_growth + 1 if len(records_by_id) == before else 0
        if no_growth >= 3 or scroll_actions >= max_scroll_actions:
            break
        page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'})")
        page.wait_for_timeout(900)
        scroll_actions += 1
    if not records_by_id:
        raise CollectionError("No visible Weibo supertopic posts were found")

    name = str(supertopic_context.get("name") or supertopic_id)
    snapshot = freeze_search_results(
        records_by_id.values(), query=name, query_kind="supertopic", sort=selected_tab,
        filters=[f"supertopic_id:{supertopic_id}"], limit=limit, captured_at=utc_now(),
    )
    snapshot.update({
        "schema_version": "1.0",
        "supertopic_context": supertopic_context,
        "discovered_count": len(records_by_id),
        "scroll_actions": scroll_actions,
        "completion_basis": "requested_first_n_visible_supertopic_posts" if len(snapshot["results"]) >= limit else "scroll_or_growth_budget_exhausted",
        "state": "complete_first_n_visible_supertopic_posts" if len(snapshot["results"]) >= limit else "partial_supertopic_shortfall",
    })
    return snapshot


def _collect_hotlist_snapshot(
    page: Any, category: str, *, ranked_limit: int, login_wait: int,
) -> dict[str, Any]:
    code, name = normalize_hotlist_category(category)
    _goto_visible(page, canonical_hotlist_url(code), login_wait)
    raw = page.evaluate(HOTLIST_SCRIPT) or {}
    entries = list(raw.get("entries") or [])
    if not entries:
        raise CollectionError("No visible Weibo hotlist rows were found")
    snapshot = freeze_hotlist_snapshot(
        entries, category=code, ranked_limit=max(1, ranked_limit), captured_at=utc_now(),
    )
    snapshot.update({
        "page_title": str(raw.get("page_title") or ""),
        "visible_categories": list(raw.get("visible_categories") or []),
        "discovered_total": len(entries),
        "completion_basis": "ranked_rows_reached_requested_limit" if snapshot["state"].startswith("complete") else "visible_table_exhausted_before_requested_rank",
        "category_name": name,
    })
    return snapshot


def _load_post(page: Any, target: str, login_wait: int) -> dict[str, Any]:
    uid, post_id = canonical_post_parts(target)
    navigation = canonical_post_url(target, uid)
    _goto_visible(page, navigation, login_wait)
    raw = page.evaluate(POST_SCRIPT)
    if not raw:
        raise CollectionError("The target Weibo post is not visible")
    if str(raw.get("post_id") or post_id) != post_id:
        raise CollectionError("The visible Weibo post ID does not match the target")
    raw["post_id"] = post_id
    raw["author_uid"] = str(raw.get("author_uid") or uid)
    return raw


def _normalize_comment_rows(
    rows: Iterable[dict[str, Any]], post_id: str, retain_author_display: bool,
    include_replies: bool,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    last_root = ""
    for row in rows:
        content = str(row.get("content") or "").strip()
        author_key = str(row.get("author_platform_id") or row.get("author_name") or content)
        level = 2 if int(row.get("level") or 1) > 1 else 1
        platform_id = str(row.get("platform_comment_id") or "").strip()
        comment_id = platform_id or derived_id(
            "comment", post_id, level, author_key, content,
            row.get("root_platform_id"), row.get("parent_platform_id"),
        )
        if level == 1:
            last_root = comment_id
        root_id = str(row.get("root_platform_id") or "").strip() or last_root or comment_id
        parent_id = str(row.get("parent_platform_id") or "").strip() or (root_id if level == 2 else "")
        declared = max(0, int(row.get("declared_reply_count") or 0)) if level == 1 else 0
        saved_replies = 0
        if level == 1:
            if not include_replies and declared:
                reply_status = "not_requested"
            elif include_replies and declared:
                reply_status = "partial_reply_not_expanded"
            else:
                reply_status = "not_applicable"
        else:
            reply_status = "not_applicable"
        output.append({
            "comment_id": comment_id,
            "comment_id_type": "platform" if platform_id else "derived",
            "post_id": post_id,
            "parent_comment_id": parent_id,
            "root_comment_id": root_id,
            "level": level,
            "author_id": stable_pseudonym(author_key),
            "author_display": str(row.get("author_name") or "") if retain_author_display else "",
            "content": content,
            "time_text": str(row.get("time_text") or ""),
            "region_text": str(row.get("region_text") or ""),
            "like_count_text": str(row.get("like_count_text") or ""),
            "declared_reply_count": declared,
            "saved_reply_count": saved_replies,
            "reply_expansion_status": reply_status,
            "collected_at": utc_now(),
        })
    saved_by_root: dict[str, int] = {}
    for record in output:
        if int(record.get("level") or 1) > 1:
            root_id = str(record.get("root_comment_id") or "")
            saved_by_root[root_id] = saved_by_root.get(root_id, 0) + 1
    for record in output:
        if int(record.get("level") or 1) != 1:
            continue
        saved_count = saved_by_root.get(str(record.get("comment_id") or ""), 0)
        record["saved_reply_count"] = saved_count
        declared_count = int(record.get("declared_reply_count") or 0)
        if not include_replies and declared_count:
            record["reply_expansion_status"] = "not_requested"
        elif declared_count and saved_count < declared_count:
            record["reply_expansion_status"] = "partial_reply_not_expanded"
        elif declared_count:
            record["reply_expansion_status"] = "complete_visible_replies"
    return output


def _normalize_repost_rows(
    rows: Iterable[dict[str, Any]], post_id: str, retain_author_display: bool,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        content = str(row.get("content") or "").strip()
        author_key = str(row.get("author_platform_id") or row.get("author_name") or content)
        platform_id = str(row.get("platform_repost_id") or "").strip()
        repost_id = platform_id or derived_id(
            "repost", post_id, author_key, content, row.get("upstream_platform_id")
        )
        output.append({
            "repost_id": repost_id,
            "repost_id_type": "platform" if platform_id else "derived",
            "source_post_id": post_id,
            "upstream_repost_id": str(row.get("upstream_platform_id") or ""),
            "author_id": stable_pseudonym(author_key),
            "author_display": str(row.get("author_name") or "") if retain_author_display else "",
            "content": content,
            "time_text": str(row.get("time_text") or ""),
            "region_text": str(row.get("region_text") or ""),
            "metrics": dict(row.get("metrics") or {}),
            "chain_status": "visible_record_chain_unverified",
            "collected_at": utc_now(),
        })
    return output


def _visible_comment_sort_modes(page: Any) -> list[str]:
    modes = page.evaluate(COMMENT_SORT_DISCOVERY_SCRIPT) or []
    selected = [label for label in ["按热度", "按时间"] if label in modes]
    return selected or ["默认排序"]


def _activate_comment_sort(page: Any, sort_mode: str) -> bool:
    if sort_mode == "默认排序":
        return True
    result = page.evaluate(COMMENT_SORT_ACTIVATE_SCRIPT, sort_mode) or {}
    if not result.get("available"):
        return False
    page.wait_for_timeout(900 if not result.get("selected_before") else 250)
    page.evaluate(COMMENT_SCROLL_TOP_SCRIPT)
    page.wait_for_timeout(500)
    return True


def _comment_scroll_state(page: Any) -> dict[str, Any]:
    return dict(page.evaluate(COMMENT_SCROLL_STATE_SCRIPT) or {})


def _prepare_comment_sort_modes(page: Any, max_probe_actions: int) -> tuple[list[str], int]:
    """Mount the lazy comment toolbar before deciding which sorts exist."""
    actions = 0
    while True:
        modes = _visible_comment_sort_modes(page)
        if modes != ["默认排序"]:
            return modes, actions
        state = _comment_scroll_state(page)
        if bool(state.get("at_bottom")) or actions >= max_probe_actions:
            page.evaluate(COMMENT_SCROLL_TOP_SCRIPT)
            page.wait_for_timeout(400)
            return ["默认排序"], actions
        page.evaluate(COMMENT_SCROLL_STEP_SCRIPT)
        page.wait_for_timeout(500)
        actions += 1


def _next_bottom_stability(
    previous: int, *, at_bottom: bool, ids_grew: bool, height_changed: bool,
) -> int:
    """Only count no-growth cycles after the real document bottom is reached."""
    if not at_bottom or ids_grew or height_changed:
        return 0
    return previous + 1


def _annotate_comment_sort(
    rows: Iterable[dict[str, Any]], sort_mode: str, root_ranks: dict[str, int],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        root_id = str(record.get("root_comment_id") or record.get("comment_id") or "")
        if int(record.get("level") or 1) == 1 and root_id not in root_ranks:
            root_ranks[root_id] = len(root_ranks) + 1
        record["observed_sort_modes"] = [sort_mode]
        record["sort_rank_by_mode"] = {
            sort_mode: int(root_ranks.get(root_id) or 0)
        }
        output.append(record)
    return output


def _merge_comment_record(previous: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return dict(observed)
    merged = dict(previous)
    for key, value in observed.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    merged["declared_reply_count"] = max(
        int(previous.get("declared_reply_count") or 0),
        int(observed.get("declared_reply_count") or 0),
    )
    modes = list(previous.get("observed_sort_modes") or [])
    for mode in observed.get("observed_sort_modes") or []:
        if mode not in modes:
            modes.append(mode)
    merged["observed_sort_modes"] = modes
    ranks = dict(previous.get("sort_rank_by_mode") or {})
    ranks.update(dict(observed.get("sort_rank_by_mode") or {}))
    merged["sort_rank_by_mode"] = ranks
    merged["collected_at"] = str(previous.get("collected_at") or observed.get("collected_at") or "")
    merged["last_observed_at"] = str(observed.get("collected_at") or utc_now())
    return merged


def _expand_comment_replies(page: Any, remaining_actions: int) -> int:
    if remaining_actions <= 0:
        return 0
    actions = 0
    # Click each currently visible control at most once per pass. Re-querying
    # the first control in a tight loop can repeatedly click one unchanged
    # "查看更多回复" button and stall large comment pages.
    candidates = page.get_by_text(re.compile(
        r"(?:共|展开)\s*\d+\s*条回复|查看更多回复|加载更多回复|展开更多回复"
    ))
    count = min(candidates.count(), remaining_actions, 8)
    for index in range(count):
        try:
            candidate = candidates.nth(index)
            candidate.scroll_into_view_if_needed(timeout=2_000)
            candidate.click(timeout=2_000)
            page.wait_for_timeout(450)
            actions += 1
        except Exception:
            continue
    return actions


def _collect_comments(
    page: Any, post_id: str, path: Path, *, limit: int, max_scroll_actions: int,
    include_replies: bool, retain_author_display: bool, resume: bool,
) -> dict[str, Any]:
    existing = _read_jsonl_rows(path) if resume else []
    if not resume and path.exists():
        path.unlink()
    ordered_ids: list[str] = []
    records_by_id: dict[str, dict[str, Any]] = {}
    for row in existing:
        comment_id = str(row.get("comment_id") or "")
        if not comment_id:
            continue
        if comment_id not in records_by_id:
            ordered_ids.append(comment_id)
        records_by_id[comment_id] = dict(row)
    current = {
        comment_id for comment_id, row in records_by_id.items()
        if str(row.get("post_id") or "") == post_id
    }
    observed_ids: set[str] = set()
    sort_runs: list[dict[str, Any]] = []
    exhausted_sorts: set[str] = set()
    limit_reached = False
    login_limited = False
    sort_activation_failed = False
    scroll_budget_exhausted = False
    sort_modes, probe_scroll_actions = _prepare_comment_sort_modes(
        page, min(12, max(1, max_scroll_actions // 4))
    )
    scroll_actions = probe_scroll_actions
    reply_actions = 0
    max_reply_actions = max_scroll_actions * 2
    for sort_mode in sort_modes:
        if limit_reached:
            break
        if not _activate_comment_sort(page, sort_mode):
            sort_activation_failed = True
            sort_runs.append({
                "sort_mode": sort_mode, "state": "partial_sort_not_available",
                "observed_records": 0, "scroll_actions": 0,
                "termination_reason": "visible_sort_control_not_activated",
            })
            continue
        sort_observed: set[str] = set()
        root_ranks: dict[str, int] = {}
        bottom_stability = 0
        previous_height: int | None = None
        sort_scroll_start = scroll_actions
        declared_text = ""
        sort_exhausted = False
        termination_reason = ""
        while True:
            if include_replies and reply_actions < max_reply_actions:
                reply_actions += _expand_comment_replies(
                    page, max_reply_actions - reply_actions
                )
            raw = page.evaluate(COMMENTS_SCRIPT) or {}
            declared_text = str(raw.get("declared") or declared_text)
            login_limited = login_limited or bool(raw.get("login_limited"))
            normalized = _normalize_comment_rows(
                raw.get("rows") or [], post_id, retain_author_display, include_replies
            )
            normalized = _annotate_comment_sort(normalized, sort_mode, root_ranks)
            before = len(sort_observed)
            for row in normalized:
                comment_id = str(row.get("comment_id") or "")
                if not comment_id:
                    continue
                if comment_id not in current and limit > 0 and len(current) >= limit:
                    continue
                if comment_id not in records_by_id:
                    ordered_ids.append(comment_id)
                records_by_id[comment_id] = _merge_comment_record(
                    records_by_id.get(comment_id, {}), row
                )
                current.add(comment_id)
                sort_observed.add(comment_id)
                observed_ids.add(comment_id)
            ids_grew = len(sort_observed) > before
            if ids_grew:
                _write_jsonl(path, [records_by_id[comment_id] for comment_id in ordered_ids])
            if limit > 0 and len(current) >= limit:
                limit_reached = True
                termination_reason = "requested_comment_limit_reached"
                break
            if login_limited:
                termination_reason = "login_required_for_more_comments"
                break
            if bool(raw.get("exhausted")):
                sort_exhausted = True
                termination_reason = "explicit_page_exhausted_marker"
                break
            scroll_state = _comment_scroll_state(page)
            height = int(scroll_state.get("height") or 0)
            height_changed = previous_height is not None and height != previous_height
            bottom_stability = _next_bottom_stability(
                bottom_stability,
                at_bottom=bool(scroll_state.get("at_bottom")),
                ids_grew=ids_grew,
                height_changed=height_changed,
            )
            previous_height = height
            if bottom_stability >= 3:
                sort_exhausted = True
                termination_reason = "document_bottom_and_comment_ids_stable"
                break
            if scroll_actions >= max_scroll_actions:
                scroll_budget_exhausted = True
                termination_reason = "scroll_action_budget_exhausted"
                break
            page.evaluate(COMMENT_SCROLL_STEP_SCRIPT)
            page.wait_for_timeout(1_000 if scroll_state.get("at_bottom") else 750)
            scroll_actions += 1
        if sort_exhausted:
            exhausted_sorts.add(sort_mode)
        sort_runs.append({
            "sort_mode": sort_mode,
            "state": "complete_visible_sort_exhausted" if sort_exhausted else (
                "partial_limit_sample" if limit_reached else "partial_visible_sort"
            ),
            "observed_records": len(sort_observed),
            "declared_comment_count_text": declared_text,
            "scroll_actions": scroll_actions - sort_scroll_start,
            "bottom_stable_cycles": bottom_stability,
            "termination_reason": termination_reason or "unknown",
        })

    # Recalculate reply coverage from the persisted union. Weibo recycles
    # virtual comment nodes, so the latest DOM snapshot is never the source of
    # truth for saved reply totals.
    persisted = [
        records_by_id[comment_id] for comment_id in ordered_ids
        if str(records_by_id[comment_id].get("post_id") or "") == post_id
    ]
    saved_by_root: dict[str, int] = {}
    for row in persisted:
        if int(row.get("level") or 1) > 1:
            root_id = str(row.get("root_comment_id") or "")
            saved_by_root[root_id] = saved_by_root.get(root_id, 0) + 1
    for row in persisted:
        if int(row.get("level") or 1) != 1:
            continue
        saved_count = saved_by_root.get(str(row.get("comment_id") or ""), 0)
        row["saved_reply_count"] = saved_count
        declared_count = int(row.get("declared_reply_count") or 0)
        if not include_replies and declared_count:
            row["reply_expansion_status"] = "not_requested"
        elif include_replies and declared_count > saved_count:
            row["reply_expansion_status"] = "partial_reply_not_expanded"
        elif declared_count:
            row["reply_expansion_status"] = "complete_visible_replies"
        else:
            row["reply_expansion_status"] = "not_applicable"
        records_by_id[str(row["comment_id"])] = row
    _write_jsonl(path, [records_by_id[comment_id] for comment_id in ordered_ids])

    declared_replies = sum(
        int(row.get("declared_reply_count") or 0)
        for row in persisted if int(row.get("level") or 1) == 1
    )
    saved_replies = sum(1 for row in persisted if int(row.get("level") or 1) == 2)
    all_sorts_exhausted = bool(sort_modes) and set(sort_modes).issubset(exhausted_sorts)
    state = comment_completion_state(
        exhausted=all_sorts_exhausted, limit_reached=limit_reached,
        declared_reply_count=declared_replies, saved_reply_count=saved_replies,
        replies_requested=include_replies, login_limited=login_limited,
        scroll_budget_exhausted=scroll_budget_exhausted,
        sort_activation_failed=sort_activation_failed,
        sort_modes_available=sort_modes, sort_modes_exhausted=exhausted_sorts,
    )
    return {
        "state": state,
        "saved_comments": len(current),
        "observed_comment_records": len(observed_ids),
        "include_replies": include_replies,
        "scroll_actions": scroll_actions,
        "reply_expand_actions": reply_actions,
        "sort_probe_scroll_actions": probe_scroll_actions,
        "sort_modes_available": sort_modes,
        "sort_modes_exhausted": sorted(exhausted_sorts),
        "sort_runs": sort_runs,
        "login_limited": login_limited,
        "scroll_budget_exhausted": scroll_budget_exhausted,
        "finished_at": utc_now(),
    }


def _activate_reposts(page: Any) -> bool:
    article = page.locator("article").first
    if not article.count():
        return False
    icon = article.locator('i[title="转发"]').first
    if not icon.count():
        return False
    try:
        clicked = icon.evaluate("""
            node => {
              const target = node.closest('[class*="_retweet_"][class*="_wrap_"]');
              if (!target) return false;
              target.click();
              return true;
            }
        """)
        if not clicked:
            return False
        page.wait_for_timeout(800)
        return bool(icon.evaluate(r"""
            node => /(?:^|\s)_cur_[^\s]*/.test(String(
              node.closest('[class*="_retweet_"][class*="_wrap_"]')?.className || ''
            ))
        """))
    except Exception:
        return False


def _collect_reposts(
    page: Any, post_id: str, path: Path, *, limit: int, max_scroll_actions: int,
    retain_author_display: bool, resume: bool,
) -> dict[str, Any]:
    existing = _read_jsonl_rows(path) if resume else []
    if not resume and path.exists():
        path.unlink()
    saved = {str(row.get("repost_id") or "") for row in existing if row.get("repost_id")}
    current = {str(row.get("repost_id") or "") for row in existing if str(row.get("source_post_id") or "") == post_id}
    available = _activate_reposts(page)
    observed: dict[str, dict[str, Any]] = {}
    exhausted = False
    limit_reached = False
    no_growth = 0
    scroll_actions = 0
    while available and scroll_actions <= max_scroll_actions:
        raw = page.evaluate(REPOSTS_SCRIPT) or {}
        available = bool(raw.get("available"))
        normalized = _normalize_repost_rows(raw.get("rows") or [], post_id, retain_author_display)
        before = len(observed)
        for row in normalized:
            observed[row["repost_id"]] = row
        remaining = max(0, limit - len(current)) if limit > 0 else 0
        pending = [] if limit > 0 and remaining == 0 else _new_unique_rows(
            normalized, "repost_id", saved, remaining
        )
        _append_jsonl(path, pending)
        for row in pending:
            saved.add(row["repost_id"])
            current.add(row["repost_id"])
        if limit > 0 and len(current) >= limit:
            limit_reached = True
            break
        exhausted = bool(raw.get("exhausted"))
        if exhausted:
            break
        no_growth = no_growth + 1 if len(observed) == before else 0
        if no_growth >= 3 or scroll_actions >= max_scroll_actions:
            exhausted = bool(page.evaluate(
                "() => { const root = document.scrollingElement || document.documentElement; return root.scrollTop + window.innerHeight >= root.scrollHeight - 12; }"
            ))
            break
        page.evaluate("window.scrollBy({top: Math.max(700, window.innerHeight * 0.8), behavior: 'instant'})")
        page.wait_for_timeout(700)
        scroll_actions += 1
    state = repost_completion_state(exhausted=exhausted, limit_reached=limit_reached, available=available)
    return {
        "state": state,
        "saved_reposts": len(current),
        "observed_repost_records": len(observed),
        "scroll_actions": scroll_actions,
        "finished_at": utc_now(),
    }


def _collect_one_post(
    page: Any, context: Any, target: str, out: Path, *, mode: str,
    assets: list[str], comment_limit: int, repost_limit: int,
    max_scroll_actions: int, include_replies: bool, retain_author_display: bool,
    login_wait: int, max_asset_bytes: int, resume: bool,
    selection_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    post_id = canonical_post_id(target)
    raw = _load_post(page, target, login_wait)
    uid = str(raw.get("author_uid") or (selection_context or {}).get("author_uid") or "")
    post_type = "video" if raw.get("videos") or raw.get("has_blob_video") else (
        "image" if raw.get("images") else "text"
    )
    post = {
        "post_id": post_id,
        "author_uid": uid,
        "author_name": str(raw.get("author_name") or ""),
        "body": str(raw.get("body") or ""),
        "topics": list(raw.get("topics") or []),
        "mentions": list(raw.get("mentions") or []),
        "published_at_text": str(raw.get("published_at_text") or ""),
        "region_text": str(raw.get("region_text") or ""),
        "source_text": str(raw.get("source_text") or ""),
        "visibility_text": str(raw.get("visibility_text") or ""),
        "post_type": post_type,
        "metrics": dict(raw.get("metrics") or {}),
        "original_post_id": str(raw.get("original_post_id") or ""),
        "original_author_uid": str(raw.get("original_author_uid") or ""),
        "profile_id": str((selection_context or {}).get("profile_id") or ""),
        "profile_rank": int((selection_context or {}).get("rank") or 0) if (selection_context or {}).get("profile_id") else 0,
        "search_snapshot_id": str((selection_context or {}).get("search_snapshot_id") or ""),
        "search_rank": int((selection_context or {}).get("rank") or 0) if (selection_context or {}).get("search_snapshot_id") else 0,
        "search_query": str((selection_context or {}).get("query") or ""),
        "selection_reason": str((selection_context or {}).get("selection_reason") or "direct_post"),
        "is_pinned": bool((selection_context or {}).get("is_pinned")),
        "canonical_url": canonical_post_url(post_id, uid),
        "collected_at": utc_now(),
        "completion_state": "complete_visible_post",
        "completion_note": "页面可见微博正文、作者与互动快照已保存",
    }
    media_specs: list[tuple[str, dict[str, Any]]] = []
    media_specs.extend(("image", item) for item in raw.get("images") or [])
    media_specs.extend(("video", item) for item in raw.get("videos") or [])
    if raw.get("cover"):
        media_specs.append(("cover", dict(raw["cover"])))
    counters = {"image": 0, "video": 0, "cover": 0}
    asset_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, item in media_specs:
        source = str(item.get("src") or "")
        try:
            clean_url, redacted = sanitize_media_url(source)
        except CollectionError:
            continue
        key = (kind, clean_url)
        if key in seen:
            continue
        seen.add(key)
        counters[kind] += 1
        order = counters[kind]
        requested = (kind == "image" and "images" in assets) or (kind == "video" and "video" in assets) or (kind == "cover" and "cover" in assets)
        row: dict[str, Any] = {
            "asset_id": f"weibo:{post_id}:{kind}:{order:03d}",
            "post_id": post_id,
            "kind": kind,
            "order": order,
            "status": "observed_not_requested",
            "local_file": "",
            "source_url": clean_url,
            "source_url_query_redacted": redacted,
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "bytes": 0,
            "sha256": "",
            "error_reason": "",
            "requested": requested,
        }
        if requested:
            try:
                downloaded = _download_asset(
                    context, source, out / "06_微博素材" / post_id / f"{order:03d}_{kind}",
                    kind=kind, max_bytes=max_asset_bytes,
                )
                downloaded["local_file"] = str(Path(downloaded["local_file"]).relative_to(out))
                row.update(downloaded)
            except Exception as exc:
                row["status"] = "failed"
                row["error_reason"] = type(exc).__name__
        asset_rows.append(row)
    if raw.get("has_blob_video") and not raw.get("videos"):
        asset_rows.append({
            "asset_id": f"weibo:{post_id}:video:000", "post_id": post_id, "kind": "video", "order": 0,
            "status": "not_observed" if "video" in assets else "observed_not_requested", "local_file": "",
            "source_url": "", "source_url_query_redacted": False, "width": 0, "height": 0, "bytes": 0,
            "sha256": "", "error_reason": "页面只暴露 blob 播放地址，未观察到可保存的源文件地址",
            "requested": "video" in assets,
        })
    if any(row.get("requested") and row.get("status") != "downloaded" for row in asset_rows):
        post["completion_state"] = "partial_asset_failure"
        post["completion_note"] = "微博字段已保存，但至少一项请求素材未能从可见页面保存"

    posts_path = out / "data" / "posts.jsonl"
    assets_path = out / "data" / "assets.jsonl"
    known_posts = _read_jsonl_ids(posts_path, "post_id") if resume else set()
    known_assets = _read_jsonl_ids(assets_path, "asset_id") if resume else set()
    if not resume:
        for path in [posts_path, assets_path]:
            if path.exists():
                path.unlink()
    if post_id not in known_posts:
        _append_jsonl(posts_path, [post])
    _append_jsonl(assets_path, [row for row in asset_rows if row["asset_id"] not in known_assets])

    comment_manifest = None
    repost_manifest = None
    if mode in {"comments", "all"}:
        comment_manifest = _collect_comments(
            page, post_id, out / "data" / "comments.jsonl", limit=comment_limit,
            max_scroll_actions=max_scroll_actions, include_replies=include_replies,
            retain_author_display=retain_author_display, resume=resume,
        )
    if mode in {"reposts", "all"}:
        if comment_manifest:
            page.goto(post["canonical_url"], wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(1_500)
        repost_manifest = _collect_reposts(
            page, post_id, out / "data" / "reposts.jsonl", limit=repost_limit,
            max_scroll_actions=max_scroll_actions, retain_author_display=retain_author_display,
            resume=resume,
        )
    return post, comment_manifest, repost_manifest


def collect(
    *, post_targets: list[str] | None = None, profile_target: str | None = None,
    search_query: str | None = None, topic_query: str | None = None,
    supertopic_target: str | None = None, supertopic_tab: str = "热门",
    hotlist_category: str | None = None, hotlist_limit: int = 50,
    recent: int = 5, max_profile_scroll_actions: int = 80,
    search_limit: int = 10, max_search_scroll_actions: int = 80,
    profile_dir: Path, out: Path, mode: str, assets: list[str],
    comment_limit: int, repost_limit: int, max_scroll_actions: int,
    include_replies: bool, retain_author_display: bool, login_wait: int,
    resume: bool, chrome_path: str | None, max_asset_mb: int,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectionError("Playwright is missing; install requirements-browser.txt first") from exc
    if mode not in {"posts", "comments", "reposts", "all"}:
        raise CollectionError("Unknown collection mode")
    if sum(bool(value) for value in [post_targets, profile_target, search_query, topic_query, supertopic_target, hotlist_category]) != 1:
        raise CollectionError("Choose exactly one source: posts, profile, search, topic, supertopic or hotlist")
    if hotlist_category and mode != "posts":
        raise CollectionError("Hotlist snapshot collection currently supports mode=posts only")
    targets = normalize_post_targets(post_targets or []) if post_targets else []
    out.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "collector": "brandbai-weibo-download",
        "collector_version": "0.1.2",
        "mode": mode,
        "target_kind": "hotlist" if hotlist_category else ("supertopic" if supertopic_target else ("topic" if topic_query else ("search" if search_query else ("profile" if profile_target else "posts")))),
        "requested_post_ids": [canonical_post_id(value) for value in targets],
        "profile_selection_state": "not_applicable",
        "search_selection_state": "not_applicable",
        "supertopic_selection_state": "not_applicable",
        "hotlist_selection_state": "not_applicable",
        "requested_assets": assets,
        "privacy_mode": "interaction_display_authors_retained" if retain_author_display else "interaction_authors_pseudonymized",
        "post_states": {}, "comment_states": {}, "comment_details": {},
        "repost_states": {}, "warnings": [],
        "state": "running", "started_at": utc_now(), "finished_at": "",
    }
    manifest_path = out / "data" / "run_manifest.json"
    atomic_write_json(manifest_path, manifest)
    executable = find_chrome_executable(chrome_path)
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir.resolve()), executable_path=executable, headless=False,
                viewport=None, args=["--start-maximized"], accept_downloads=True,
            )
        except Exception as exc:
            manifest["state"] = "partial"
            manifest["finished_at"] = utc_now()
            manifest["warnings"].append(
                f"browser launch failed ({type(exc).__name__}); close any Chrome window using the dedicated profile"
            )
            atomic_write_json(manifest_path, manifest)
            raise CollectionError(
                "The dedicated Weibo Chrome profile is already open or Chrome closed during startup"
            ) from exc
        page = context.pages[0] if context.pages else context.new_page()
        try:
            selection_by_id: dict[str, dict[str, Any]] = {}
            if hotlist_category:
                snapshot = _collect_hotlist_snapshot(
                    page, hotlist_category, ranked_limit=max(1, hotlist_limit), login_wait=max(0, login_wait),
                )
                hotlist_path = out / "data" / "hotlist_snapshots.jsonl"
                if not resume and hotlist_path.exists():
                    hotlist_path.unlink()
                _append_jsonl(hotlist_path, [_public_hotlist_snapshot(snapshot)])
                manifest["hotlist_selection_state"] = snapshot["state"]
                manifest["hotlist_selection"] = {
                    "hotlist_snapshot_id": snapshot["hotlist_snapshot_id"],
                    "category_code": snapshot["category_code"],
                    "category_name": snapshot["category_name"],
                    "canonical_url": snapshot["canonical_url"],
                    "requested_ranked": snapshot["requested_ranked"],
                    "saved_ranked": snapshot["saved_ranked"],
                    "saved_extras": snapshot["saved_extras"],
                    "saved_total": snapshot["saved_total"],
                    "captured_at": snapshot["captured_at"],
                }
                atomic_write_json(manifest_path, manifest)
            elif profile_target:
                selection = _discover_profile_posts(
                    page, profile_target, recent=max(0, recent),
                    max_scroll_actions=max(0, max_profile_scroll_actions), login_wait=max(0, login_wait),
                )
                atomic_write_json(out / "data" / "profile_selection.json", _public_profile_selection(selection))
                _append_jsonl(out / "data" / "accounts.jsonl", [selection["account"]])
                manifest["profile_selection_state"] = selection["state"]
                manifest["profile_selection"] = {
                    "profile_selection_id": selection["profile_selection_id"], "profile_id": selection["profile_id"],
                    "canonical_url": selection["canonical_url"], "pinned_count": selection["pinned_count"],
                    "recent_requested": selection["recent_requested"], "recent_selected": selection["recent_selected"],
                    "selected_count": len(selection["selected"]), "captured_at": selection["captured_at"],
                }
                targets = [str(record.get("navigation_url") or canonical_post_url(str(record["post_id"]), selection["profile_id"])) for record in selection["selected"]]
                manifest["requested_post_ids"] = [str(record["post_id"]) for record in selection["selected"]]
                selection_by_id = {str(record["post_id"]): {**record, "profile_id": selection["profile_id"]} for record in selection["selected"]}
                atomic_write_json(manifest_path, manifest)
            elif supertopic_target:
                snapshot = _discover_supertopic_results(
                    page, supertopic_target, tab=supertopic_tab, limit=max(1, search_limit),
                    max_scroll_actions=max(0, max_search_scroll_actions), login_wait=max(0, login_wait),
                )
                search_path = out / "data" / "search_snapshots.jsonl"
                if not resume and search_path.exists():
                    search_path.unlink()
                _append_jsonl(search_path, [_public_search_snapshot(snapshot)])
                manifest["supertopic_selection_state"] = snapshot["state"]
                manifest["supertopic_selection"] = {
                    "search_snapshot_id": snapshot["search_snapshot_id"],
                    "supertopic_id": (snapshot.get("supertopic_context") or {}).get("supertopic_id"),
                    "canonical_url": (snapshot.get("supertopic_context") or {}).get("canonical_url"),
                    "name": snapshot["query"], "selected_tab": snapshot["sort"],
                    "requested": snapshot["requested"], "saved": snapshot["saved"], "captured_at": snapshot["captured_at"],
                }
                targets = [str(record.get("navigation_url") or canonical_post_url(str(record["post_id"]), str(record.get("author_uid") or ""))) for record in snapshot["results"]]
                manifest["requested_post_ids"] = [str(record["post_id"]) for record in snapshot["results"]]
                selection_by_id = {
                    str(record["post_id"]): {
                        **record, "selection_reason": "supertopic_result",
                        "search_snapshot_id": snapshot["search_snapshot_id"], "query": snapshot["query"],
                    }
                    for record in snapshot["results"]
                }
                atomic_write_json(manifest_path, manifest)
            elif search_query or topic_query:
                query_kind = "topic" if topic_query else "keyword"
                query = str(topic_query or search_query or "")
                snapshot = _discover_search_results(
                    page, query, query_kind=query_kind, limit=max(1, search_limit),
                    max_scroll_actions=max(0, max_search_scroll_actions), login_wait=max(0, login_wait),
                )
                search_path = out / "data" / "search_snapshots.jsonl"
                if not resume and search_path.exists():
                    search_path.unlink()
                _append_jsonl(search_path, [_public_search_snapshot(snapshot)])
                manifest["search_selection_state"] = snapshot["state"]
                manifest["search_selection"] = {
                    "search_snapshot_id": snapshot["search_snapshot_id"], "query": snapshot["query"],
                    "query_kind": snapshot["query_kind"], "sort": snapshot["sort"],
                    "requested": snapshot["requested"], "saved": snapshot["saved"], "captured_at": snapshot["captured_at"],
                }
                targets = [str(record.get("navigation_url") or canonical_post_url(str(record["post_id"]), str(record.get("author_uid") or ""))) for record in snapshot["results"]]
                manifest["requested_post_ids"] = [str(record["post_id"]) for record in snapshot["results"]]
                selection_by_id = {
                    str(record["post_id"]): {**record, "selection_reason": "search_result", "search_snapshot_id": snapshot["search_snapshot_id"], "query": snapshot["query"]}
                    for record in snapshot["results"]
                }
                atomic_write_json(manifest_path, manifest)

            for index, target in enumerate(targets):
                post_id = canonical_post_id(target)
                try:
                    post, comments, reposts = _collect_one_post(
                        page, context, target, out, mode=mode, assets=assets,
                        comment_limit=max(0, comment_limit), repost_limit=max(0, repost_limit),
                        max_scroll_actions=max(1, max_scroll_actions), include_replies=include_replies,
                        retain_author_display=retain_author_display, login_wait=max(0, login_wait),
                        max_asset_bytes=max(1, max_asset_mb) * 1024 * 1024,
                        resume=resume or index > 0, selection_context=selection_by_id.get(post_id),
                    )
                    manifest["post_states"][post_id] = post["completion_state"]
                    if comments:
                        comment_state = comments["state"]
                        manifest["comment_states"][post_id] = comment_state
                        manifest["comment_details"][post_id] = comments
                        if not str(comment_state).startswith("complete"):
                            manifest["warnings"].append(
                                f"{post_id}: comment collection state {comment_state}"
                            )
                    if reposts:
                        repost_state = reposts["state"]
                        manifest["repost_states"][post_id] = repost_state
                        if not str(repost_state).startswith("complete"):
                            manifest["warnings"].append(
                                f"{post_id}: repost collection state {repost_state}"
                            )
                except Exception as exc:
                    manifest["post_states"][post_id] = "failed_no_visible_post"
                    if mode in {"comments", "all"}:
                        manifest["comment_states"][post_id] = "partial_runtime_error"
                    if mode in {"reposts", "all"}:
                        manifest["repost_states"][post_id] = "partial_runtime_error"
                    manifest["warnings"].append(f"{post_id}: collection failed ({type(exc).__name__})")
                atomic_write_json(manifest_path, manifest)
        finally:
            context.close()
    states = list(manifest["post_states"].values())
    if profile_target:
        states.insert(0, manifest["profile_selection_state"])
    if search_query or topic_query:
        states.insert(0, manifest["search_selection_state"])
    if supertopic_target:
        states.insert(0, manifest["supertopic_selection_state"])
    if hotlist_category:
        states.insert(0, manifest["hotlist_selection_state"])
    if mode in {"comments", "all"}:
        states.extend(manifest["comment_states"].values())
    if mode in {"reposts", "all"}:
        states.extend(manifest["repost_states"].values())
    manifest["state"] = "complete" if states and all(str(value).startswith("complete") for value in states) else "partial"
    manifest["finished_at"] = utc_now()
    atomic_write_json(manifest_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect visible Weibo accounts, posts, comments, reposts and media")
    parser.add_argument("mode", choices=["posts", "comments", "reposts", "all"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--post", action="append", help="Repeat for more Weibo post URLs or ids")
    source.add_argument("--profile", help="One Weibo account URL or UID")
    source.add_argument("--search", help="One Weibo keyword query")
    source.add_argument("--topic", help="One Weibo hashtag topic")
    source.add_argument("--supertopic", help="One Weibo supertopic /p/100808... URL or ID")
    source.add_argument("--hotlist", help="One Weibo hotlist category, such as 热搜 or 文娱")
    parser.add_argument("--supertopic-tab", default="热门", help="Visible supertopic tab, such as 热门, 最新 or 精华")
    parser.add_argument("--hotlist-limit", type=int, default=50, help="Ranked rows to retain; pinned and special visible rows are additional")
    parser.add_argument("--recent", type=int, default=5)
    parser.add_argument("--max-profile-scroll-actions", type=int, default=80)
    parser.add_argument("--search-limit", type=int, default=10)
    parser.add_argument("--max-search-scroll-actions", type=int, default=80)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--assets", default="images,cover")
    parser.add_argument("--comment-limit", type=int, default=0)
    parser.add_argument("--repost-limit", type=int, default=0)
    parser.add_argument("--max-scroll-actions", type=int, default=800)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--retain-author-display", action="store_true")
    parser.add_argument("--login-wait", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--chrome-path")
    parser.add_argument("--max-asset-mb", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = collect(
            post_targets=args.post, profile_target=args.profile, search_query=args.search, topic_query=args.topic,
            supertopic_target=args.supertopic, supertopic_tab=args.supertopic_tab,
            hotlist_category=args.hotlist, hotlist_limit=max(1, args.hotlist_limit),
            recent=max(0, args.recent), max_profile_scroll_actions=max(0, args.max_profile_scroll_actions),
            search_limit=max(1, args.search_limit), max_search_scroll_actions=max(0, args.max_search_scroll_actions),
            profile_dir=args.profile_dir, out=args.out, mode=args.mode, assets=normalize_assets(args.assets),
            comment_limit=max(0, args.comment_limit), repost_limit=max(0, args.repost_limit),
            max_scroll_actions=max(1, args.max_scroll_actions), include_replies=args.include_replies,
            retain_author_display=args.retain_author_display, login_wait=max(0, args.login_wait),
            resume=args.resume, chrome_path=args.chrome_path, max_asset_mb=max(1, args.max_asset_mb),
        )
    except (CollectionError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("state") == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
