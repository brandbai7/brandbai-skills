"""Validate a BrandBAI Product Value delivery before formal handoff."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from build_source_audit_cards import DISPLAY_WIDTH, image_dimensions
from build_product_value_report import build_report_01, build_report_02, load_delivery
from product_value_common import (
    ANALYSIS_STATUSES,
    DELIVERY_STATUSES,
    FACT_TYPES,
    FC_LEVELS,
    GAP_PRIORITIES,
    INPUT_MODES,
    P0_STATUSES,
    PKG_LEVELS,
    READINESS_LEVELS,
    SCHEMA_VERSION,
    SC_LEVELS,
    SKILL_VERSION,
    SKU_STATUSES,
    VALUE_LAYERS,
    delivery_paths,
    read_json,
    read_jsonl,
)


MANIFEST_FIELDS = {
    "schema_version",
    "skill_version",
    "product_value_id",
    "brand",
    "product",
    "category",
    "sku",
    "sku_status",
    "sku_basis",
    "identity_id",
    "input_mode",
    "package_version",
    "output_version",
    "fc",
    "sc",
    "pkg_level",
    "analysis_status",
    "delivery_status",
    "limitations",
    "created_at",
    "updated_at",
}
SOURCE_INVENTORY_FIELDS = {
    "source_file_id",
    "filename",
    "relative_path",
    "media_type",
    "size_bytes",
    "sha256",
    "status",
}
AUDIT_CARD_FIELDS = {
    "source_file_id",
    "relative_path",
    "source_sha256",
    "media_type",
    "audit_card_path",
    "audit_card_sha256",
    "status",
}
SOURCE_OBSERVATION_FIELDS = {
    "observation_id",
    "source_file_id",
    "relative_path",
    "content_type",
    "title",
    "visible_heading",
    "visible_text_excerpt",
    "inspection_method",
    "inspection_status",
    "inspected_at",
    "audit_card_sha256",
    "first_pass_sequence",
    "second_pass_sequence",
    "second_pass_heading",
    "second_pass_excerpt",
    "second_pass_status",
    "second_pass_at",
    "text_density",
    "content_flags",
}
SOURCE_CLAIM_FIELDS = {
    "claim_id",
    "source_file_id",
    "observation_id",
    "claim_type",
    "label",
    "verbatim_text",
    "normalized_value",
    "unit",
    "visual_locator",
    "critical",
    "claim_status",
    "claimed_at",
    "rechecked_at",
}
SOURCE_FIELDS = {
    "source_id",
    "source_file_id",
    "observation_id",
    "source_type",
    "title",
    "locator",
    "captured_at",
    "sku_scope",
    "status",
    "notes",
}
FACT_FIELDS = {
    "fact_id",
    "fact_type",
    "statement",
    "source_id",
    "claim_ids",
    "source_quotes",
    "locator",
    "sku_scope",
    "time_scope",
    "status",
    "boundary",
}
EVIDENCE_FACT_FIELDS = {"evidence_detail_confidence", "exact_fields_verified", "verification_locator"}
FABE_FIELDS = {
    "fabe_id",
    "value_id",
    "feature",
    "feature_fact_ids",
    "advantage",
    "benefit",
    "evidence",
    "evidence_fact_ids",
    "reference_frame",
    "reference_fact_ids",
    "user_language",
    "derivation_status",
    "boundary",
}
ANCHOR_FIELDS = {"anchor_id", "anchor_type", "statement", "fact_ids", "status", "boundary"}
VALUE_FIELDS = {
    "value_id",
    "layer",
    "p0_candidate",
    "p0_status",
    "user_task",
    "value_statement",
    "supporting_fact_ids",
    "strategic_potential",
    "execution_maturity",
    "user_perception_goal",
    "sku_scope",
    "scope",
    "cannot_prove",
    "downstream_readiness",
}
DECISION_FIELDS = {
    "decision_id",
    "candidate_value_ids",
    "recommended_value_id",
    "status",
    "rationale",
    "public_rationale",
    "current_execution_axis",
    "current_execution_value_ids",
    "cannot_prove",
    "validation_questions",
    "decided_at",
    "valid_until",
    "supersedes",
}
GAP_FIELDS = {"gap_id", "category", "missing", "impact", "minimum_needed", "priority", "state"}

RISKY_INFERENCE_RULES = (
    (re.compile(r"SGS.{0,8}(?:安全)?认证|安全认证", re.IGNORECASE), "检测报告不能自动改写为安全认证"),
    (re.compile(r"(?:确保|保证).{0,12}(?:原料)?品质"), "检测或选材信号不能写成确保品质"),
    (re.compile(r"敏感人群.{0,8}(?:安心|适合|友好)"), "不得从无硫熏或配料信息推导敏感人群适用性"),
    (re.compile(r"控脂人群.{0,8}(?:安心|适合|友好)"), "零脂肪标示不能自动推导控脂人群适用性"),
    (re.compile(r"(?:滋养|滋补)(?:收益|功效|效果)"), "食品商品价值不得预设未经资料支持的滋养收益或功效"),
    (re.compile(r"第三方(?:安全)?检测背书"), "页面展示的检测报告应写成支持该页面主张，不写成笼统背书"),
    (re.compile(r"无刺激"), "不得把页面中的入口温和或去麻描述扩大为无刺激"),
    (re.compile(r"安全(?:底线|指标)"), "检测结果应写具体项目和页面主张，不能扩大为笼统安全结论"),
    (re.compile(r"(?:健康的食物|健康的食品|健康的零食|送健康)"), "不得把食品价值笼统改写为健康承诺"),
    (re.compile(r"不产生咀嚼噪音|没有咀嚼噪音|无强烈气味"), "资料未证明咀嚼噪音或气味体验"),
    (re.compile(r"不需(?:要)?冰箱|无需特殊(?:保存|贮存)条件|常温放一年都没事|长期存放和食用"), "不得扩大或冲突于页面储存条件"),
    (re.compile(r"非根茎"), "不得把加工后形态误写成原料并非根茎"),
    (re.compile(r"出现次数最多|覆盖(?:的)?页面最广|页面篇幅(?:最多|最大)|出现频次(?:最高|最多)"), "页面出现次数、覆盖页数或篇幅不能决定 P0"),
    (re.compile(r"坚持食用|长期坚持"), "没有用户或使用研究时，不得把页面事实扩大为持续使用结论"),
    (re.compile(r"(?:食品)?加工过程安全性|吃得放心|放心吃"), "单项检测或页面安心文案不得扩大为整体食品安全判断"),
    (re.compile(r"全部强制标注项目"), "仅凭商品页成分表不能判断其已完整覆盖全部法定强制项目"),
    (re.compile(r"(?:不用|无需|不必)(?:再)?担心"), "用户利益不得写成绝对化的“不用担心”；应改为减少顾虑或明确适用条件"),
    (re.compile(r"二次硫(?:熏制|处理|工艺)?"), "“二次硫”属于把二氧化硫误写成工艺次数的错词，必须回到原文改正"),
)
EXPIRY_WORDS_RE = re.compile(r"已过期|已经过期|时效性过期")
DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
INTERNAL_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:PV-[0-9a-f]{12}|(?:SF|SRC|ID|ANCHOR|FABE|CLM|V|F|H|EX|U|DYN|STRAT|GAP|P0D)-\d{3,})(?![A-Za-z0-9])"
)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
USER_HABIT_REFERENCE_RE = re.compile(
    r"(?:用户|消费者|人们|大家)?.{0,16}(?:旧习惯|原有习惯|日常习惯|习惯做法)"
)
ALL_SKU_RE = re.compile(r"(?:全\s*SKU|所有\s*SKU|all[_\s-]*skus?)", re.IGNORECASE)
QUANTIFIED_STEAM_DRY_RE = re.compile(
    r"(?:九|[一二三四五六七八九十两0-9]+)\s*蒸\s*(?:九|[一二三四五六七八九十两0-9]+)\s*晒"
)
REPORT_VALUE_RE = re.compile(
    r"(?:报告(?:编号|号)|证书编号|批次号|生产批号)\s*[:：]?\s*([A-Z0-9][A-Z0-9._/-]{5,})",
    re.IGNORECASE,
)
DATE_VALUE_RE = re.compile(
    r"(?:发布日期|签发日期|报告日期|检测日期|证书日期)\s*[:：]?\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})",
    re.IGNORECASE,
)
METHOD_VALUE_RE = re.compile(
    r"检测方法\s*[:：]?\s*([A-Z]{1,8}\s*\d[A-Z0-9 ._/-]{3,})",
    re.IGNORECASE,
)
METHOD_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])((?:GB(?:/T)?|GBZ(?:/T)?|SN/T|NY/T|DB\d+(?:/T)?|ISO|IEC|EN|ASTM)"
    r"\s*[A-Z]?\s*\d[\d.:-]*(?:[-:]\d{2,4})?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
NO_ADDITIVE_RE = re.compile(r"无(?:其他|额外)?添加(?:成分|物)?|无防腐剂|不含防腐剂")
ABSOLUTE_COMPETITION_RE = re.compile(r"差异化最强|竞品多停留|行业唯一|同类唯一|独有|领先")
PUBLIC_JARGON_RE = re.compile(
    r"\bP0-(?:HYPOTHESIS|SELECTED|VALIDATING|BOUNDARY-VALIDATED|REOPEN|REPLACED|STOPPED)\b|"
    r"(?<!P0-)\b(?:HYPOTHESIS|SELECTED|VALIDATING)\b|evidence_detail_confidence|exact_fields_verified|current_listing|reference_frame|source_inventory\.jsonl|source_claim_ledger\.jsonl|"
    r"sku_status\s*=\s*(?:confirmed|partial|unverified)|证据细节可信度\s*=\s*(?:high|medium|low)|"
    r"\b(?:high|medium|low) confidence\b|(?:high|medium|low)\s*置信度|exact fields unverified|"
    r"\b(?:FC[0-3]|SC[0-3]|PKG-L[0-4])\b|\bmedium\b|"
    r"\b(?:dietary|page_supported|reasoned|to_validate|snapshot_only|active_at_snapshot|cannot_prove|user_task|user_perception_goal|read)\b|"
    r"证据细节可信度|精确字段已核验|\.\s*压缩包|"
    r"`(?:active|expired|verified|unverified|template|deferred|blocked|conditional|ready|stale)`|"
    r"(?<![A-Za-z0-9_])(?:F-EVIDENCE|STRAT|DYN|U|H|ZIP|updated_at|partial)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
OBSERVATION_METHODS = {"visual_stamped_card", "document_text", "official_url", "unsupported_archive"}
OBSERVATION_STATUSES = {"inspected", "unreadable", "not_applicable"}
TEXT_DENSITIES = {"none", "low", "medium", "high"}
CONTENT_FLAGS = {
    "identity",
    "sku",
    "ingredient",
    "nutrition_table",
    "storage",
    "warning",
    "faq",
    "usage",
    "comparison",
    "process",
    "sensory",
    "packaging",
    "origin",
    "evidence",
    "transaction",
    "audience",
    "other",
}
CLAIM_TYPES = {
    "identity",
    "sku",
    "ingredient",
    "nutrition",
    "storage",
    "warning",
    "faq",
    "usage",
    "comparison",
    "process",
    "sensory",
    "packaging",
    "origin",
    "evidence",
    "transaction",
    "audience",
    "other",
}
CRITICAL_CLAIM_TYPES = {"sku", "ingredient", "nutrition", "storage", "warning"}
FLAG_CLAIM_REQUIREMENTS = {
    "sku": ("sku", 1),
    "ingredient": ("ingredient", 1),
    "nutrition_table": ("nutrition", 3),
    "storage": ("storage", 1),
    "warning": ("warning", 1),
    "faq": ("faq", 1),
    "usage": ("usage", 1),
    "comparison": ("comparison", 2),
}
COMPETITOR_SOURCE_TYPES = {"competitor_page", "industry_report", "competitor_dataset"}
AGGREGATE_USER_RE = re.compile(
    r"(?:很多|大多数|多数|普遍).{0,8}(?:人|用户|消费者)|"
    r"最常见.{0,12}(?:购买|任务|需求|问题|场景)|"
    r"(?:主流|普遍存在|最主要).{0,12}(?:购买|任务|需求|问题|场景)|"
    r"用户(?:对)?.{0,36}(?:核心|主要|关键)(?:顾虑|需求|问题|关注)|"
    r"(?:直接对应|击中|反映).{0,18}用户.{0,36}(?:核心|主要|关键)(?:顾虑|需求|问题|关注)"
)
NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?%?(?![A-Za-z0-9])")
DIRECT_QUOTE_TERMS_RE = re.compile(
    r"好吸收|道地(?:品种|药材|产区)?|无添加|无防腐剂|适合.{0,8}(?:小白|老人|长辈|儿童|孕妇|人群)|"
    r"哪些人(?:适合|不宜)|禁止食用|不宜食用|遵医嘱|建议冷藏|无需熬煮|"
    r"(?:生黄精|生精|黄精)多糖|国家标准|推荐量|通过.{0,4}检测|安心好携带|"
    r"无需反复调配|可追溯"
)
ATOMIC_CLAIM_TERMS_RE = re.compile(
    r"每\s*100\s*克|饱和脂肪|碳水化合物|蛋白质|生产日期|保质期|贮存条件|储存条件|"
    r"总净含量|单包净含量|单袋净含量|净含量|配料表|配料|能量|脂肪|糖|钠|"
    r"如有胀袋|胀袋|过敏者|孕妇|哺乳期|婴幼儿|特殊人群|"
    r"禁止食用|请勿食用|不宜食用|不可食用|不能食用|勿食用|遵医嘱"
)
SENSORY_LITERAL_RE = re.compile(
    r"软糯甘甜|软韧回甜|软韧回甘|微甜软糯|草本香|无纤维感|入口温和|口感软糯"
)
WARNING_TEXT_RE = re.compile(
    r"禁止食用|请勿食用|不宜食用|不可食用|不能食用|勿食用|遵医嘱|谨遵医嘱|过敏.{0,8}(?:禁用|禁止|勿食)"
)
COMPARISON_PREFIX = r"(?:相对|相比|相较于?|对比|较之|优于|高于|低于|不同于|而非)"
MISLEADING_COMPARATOR_RE = re.compile(
    rf"{COMPARISON_PREFIX}(?:仅达到|普通(?:产地|原料|产品)?|添加多种|未明示|传统(?:产品|工艺)?)"
)
UNSUPPORTED_PRODUCT_COMPARATOR_RE = re.compile(
    rf"{COMPARISON_PREFIX}(?:(?![，。；;]).){{0,30}}(?:"
    r"无法确认加工工艺|多配料(?:的)?(?:加工|复合)?食品|单一食用方式(?:的)?产品|"
    r"(?:散装|整袋)(?:或)?大包装|无检测引用(?:的)?产品|一般(?:产区|产品|原料)|"
    r"部分(?:使用|采用)?硫熏(?:工艺)?(?:保色保鲜)?(?:的)?(?:加工方式|产品)?|"
    r"需要煎煮或加工(?:的)?黄精原料|"
    r"原料形态不可见或被打碎(?:的)?冲泡饮品|"
    r"(?:一包一次|量小需频繁补配)(?:的)?速溶茶|"
    r"仅写单一冲泡方式(?:的)?茶|"
    r"未公开(?:同类)?检测(?:与|和)?(?:体系)?认证(?:的)?茶饮)"
)
MARKET_COMPARATOR_RE = re.compile(
    rf"{COMPARISON_PREFIX}.{{0,60}}(?:同类(?:食品|商品|产品)?|竞品|行业|国家标准|普通产品|其他产品|添加多种|未明示)|"
    r"(?:同类(?:食品|商品|产品)?|竞品|普通产品|其他普通[\u4e00-\u9fff]{0,10}).{0,18}(?:相比|对比|更(?:容易|方便|清楚|适合))|"
    r"区分.{0,16}(?:其他|普通|同类|竞品)|"
    r"(?:可|能够|可以)?与同类.{0,24}(?:形成|构成).{0,12}(?:差异|差异点|区别)"
)
UNSUPPORTED_PRODUCT_TARGET_RE = re.compile(
    r"多配料(?:的)?(?:加工|复合)?食品|配料(?:未公开|不透明|多元).{0,12}同类(?:加工)?食品|"
    r"配料(?:多栏|较多|复杂)(?:的)?(?:同类)?产品|"
    r"仅支持单一食用方式(?:的)?产品|单一食用方式(?:的)?产品|"
    r"另购(?:不同|其他|别的)?形态(?:的)?产品|"
    r"(?:不需要|无需|不用|不必).{0,16}(?:另购|购买|准备|配备).{0,16}(?:不同|其他|别的)?形态(?:的)?产品|"
    r"(?:不需要|无需|不用|不必)(?:再|为)?(?:不同形态|多种形态).{0,10}(?:单独)?(?:准备|购买|配备)|"
    r"原料形态不可见或被打碎(?:的)?冲泡饮品|"
    r"(?:一包一次|量小需频繁补配)(?:的)?速溶茶|"
    r"仅写单一冲泡方式(?:的)?茶|"
    r"未公开(?:同类)?检测(?:与|和)?(?:体系)?认证(?:的)?茶饮|"
    r"(?:不需要|无需|不用|不必).{0,20}(?:为不同场景)?(?:准备|购买|配备).{0,12}不同形态(?:的)?(?:茶饮|产品|商品)|"
    r"(?:本品|本商品|当前商品).{0,10}与未公开(?:认证|营养表|营养成分表).{0,10}(?:差异|区别)"
    r"|(?:需要额外(?:分装|称量|处理)的)?(?:碎料|碎片|粉末|散料)(?:形态|产品|原料)?"
)
COMPARISON_LANGUAGE_RE = re.compile(rf"{COMPARISON_PREFIX}|{UNSUPPORTED_PRODUCT_TARGET_RE.pattern}")
COMPARISON_DENIAL_SPAN_RE = re.compile(
    r"(?:(?:不|未)(?:与|引用|视为|作为|外推为?|扩大为?|证明)|不得|不能|不可|不应)"
    r"[^，。；;]{0,40}(?:竞品|同类|其他品牌|其他产品|普通产品|比较|对比)"
)
ARCHIVE_MEDIA_RE = re.compile(r"(?:zip|rar|7z|tar|gzip|x-compressed|x-zip)", re.IGNORECASE)
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
PUBLIC_CONTRADICTION_RE = re.compile(r"转为难入口温和|难入口温和")
PUBLIC_ID_RESIDUE_RE = re.compile(
    r"/(?:\d{3,})(?:/\d{3,})+|//\s*(?:reference_frame|参照系)|对应的?回答已登记为\s*[。.]|"
    r"(?:/\s*){2,}(?:等候选)?|(?:^|[；;。])\s*在\s+(?:包装|页面|来源|资料)",
    re.IGNORECASE,
)
UNSUPPORTED_RESTRICTION_RE = re.compile(
    r"仅适合泡水|只能泡水|(?:需要|必须).{0,6}长时间(?:炖煮|熬煮)"
)
SULFUR_RESIDUE_RISK_RE = re.compile(
    r"(?:不引入|避免|没有|不存在|无).{0,6}二氧化硫.{0,6}(?:残留)?风险|二氧化硫.{0,6}(?:零残留|无残留)"
)
PROMOTION_STACKING_RE = re.compile(
    r"(?:优惠|活动|折扣|赠品|券|权益)?.{0,8}(?:可以|(?<!不)可|能够)叠加(?:使用|享受)?|"
    r"(?:叠加(?:使用|享受)?|可叠加的).{0,8}(?:优惠|活动|折扣|赠品|券|权益)|"
    r"(?:同时|一并)享受.{0,10}(?:优惠|活动|折扣|赠品|券|权益)"
)
PROMOTION_STACKING_DENIAL_RE = re.compile(
    r"(?:原文|资料|页面).{0,10}(?:未明确|未说明|没有说明).{0,14}叠加|"
    r"(?:不得|不能|不可|不应).{0,10}(?:写|声称|表述)?.{0,6}(?:可叠加|叠加优惠|优惠叠加)"
)
ACTIVE_DENIAL_RE = re.compile(
    r"(?:不得|不能|不可|不应).{0,16}(?:写|标记|表述|称为)?.{0,8}(?:当前有效|仍然有效|仍有效|活动中)"
)
EATING_RESTRICTION_RE = re.compile(r"(?:不宜|不可|不能|禁止|请勿|勿|不适合)(?:直接)?食用")
TITLE_EVIDENCE_RE = re.compile(r"(?:商品|页面|下载文件|文件)?标题|文件名|OCR", re.IGNORECASE)
FILENAME_METADATA_RE = re.compile(r"(?:本地|来源|原始|下载)?(?:文件名|档名|filename|relative_path|文件路径)", re.IGNORECASE)
HIGHER_PRIORITY_SKU_RE = re.compile(r"SKU\s*选择|包装|规格(?:栏|表|选择)|商品信息|成交单元|订单", re.IGNORECASE)
SKU_CONFLICT_RE = re.compile(r"不一致|冲突|无法确认|待核对|待确认")
SULFUR_SAFETY_BENEFIT_RE = re.compile(
    r"(?:担心|顾虑|影响|减少|避免).{0,20}(?:硫熏|二氧化硫).{0,20}(?:安全|健康|危害|风险)|"
    r"(?:硫熏|二氧化硫).{0,20}(?:安全|健康|危害|风险).{0,20}(?:担心|顾虑|影响|减少|避免)"
)
SULFUR_SAFETY_ASSOCIATION_RE = re.compile(
    r"(?:硫熏|二氧化硫).{0,20}(?:安全|健康|危害|风险)|"
    r"(?:安全|健康|危害|风险).{0,20}(?:硫熏|二氧化硫)"
)
DERIVED_PAGE_FILENAME_RE = re.compile(r"^page[_-]?(\d{1,5})\.(?:png|jpe?g|webp)$", re.IGNORECASE)
NON_VERBATIM_SUMMARY_RE = re.compile(
    r"^\s*[（(]?(?:页面|商品页|详情页|平台|淘宝平台)?[^。；]{0,24}"
    r"(?:公开(?:展示|主张)|通用文本|非本商品专属|图片内容|页面内容)"
    r"[^。；]{0,24}[）)]?\s*$"
)
CAUSAL_LINK_RE = re.compile(
    r"(?:由|得益于|归因于|因为|基于).{1,48}?(?:共同)?(?:实现|带来|形成|决定|让|使(?!用)(?:得)?)|"
    r"(?:原料|配料|工艺|厚切|整料|烘干|包装).{0,24}(?:让|使(?!用)(?:得)?|带来|实现|形成).{1,48}"
)
STRICT_FABE_SOURCE_TERMS = (
    "天然",
    "科学配比",
    "甜腻",
    "刺激",
    "甜品",
    "免熬煮",
    "免称量",
    "洗器具",
    "不打开包装",
    "完整的成分表",
    "称量",
    "熬煮",
    "器具",
    "完整",
    "额外操作",
)
TRACEABILITY_RE = re.compile(r"可追溯|追溯(?:到|至)")
AUDIT_DOWNGRADE_ACTION_RE = re.compile(
    r"(?:移除|删除).{0,30}(?:标记|flag)|"
    r"(?:text_density|文字密度).{0,30}(?:降为|降级)|"
    r"(?:降为|降级).{0,30}(?:text_density|文字密度)",
    re.IGNORECASE,
)
AUDIT_DOWNGRADE_REASON_RE = re.compile(
    r"时间戳|原文主张|claim|四遍读取|observation|OBS-",
    re.IGNORECASE,
)
ABSENCE_ASSERTION_RE = re.compile(r"未(?:标示|标注|说明|提供|公开|列出|披露|显示)")
SELF_COMPARISON_REFERENCE_RE = re.compile(
    r"(?:页面内对比\s*[:：]?\s*)?(?:相对|相比|对比).{0,32}(?:当前|本)(?:商品|产品)(?:内|自身)|"
    r"页面内对比\s*[:：]?\s*(?:当前|本)(?:商品|产品)(?:内|自身)"
)
REFERENCE_BOILERPLATE_RE = re.compile(
    r"本条参照|页面内对比|当前页面|当前商品|本商品|当前产品|本产品|内生任务|内生推导|内生假设|"
    r"参照系|操作任务|页面主张|页面展示|页面公开|公开标示|具体产品事实|这一当前操作任务|"
    r"这一具体事实|不能证明|无法证明|尚未证明|不得证明|未验证|待验证|当前未|"
    r"相对|相比|对比|自身|五项"
)
REFERENCE_COMMON_BIGRAMS = {
    "当前", "商品", "产品", "页面", "用户", "任务", "操作", "使用", "信息", "选择",
    "方式", "支持", "直接", "明确", "公开", "展示", "提供", "体验", "问题", "假设",
}
FIELD_SEGMENT_SPLIT_RE = re.compile(r"[+＋，,；;。]|以及|同时|并且|并展示|并采用")
QUOTED_SPAN_RE = re.compile(r"'([^']{2,})'|\"([^\"]{2,})\"|“([^”]{2,})”|‘([^’]{2,})’")
FIELD_CONCEPT_PATTERNS = {
    "origin": re.compile(r"产地|产区|来源地"),
    "ingredient": re.compile(r"原料|配料|食材"),
    "packaging": re.compile(r"包装|袋装|小袋|密封"),
    "portioning": re.compile(r"分装|分量|定量"),
    "weighing": re.compile(r"称量|称重"),
    "shape": re.compile(r"形态|整料|大片|厚切|打碎|碎料|粉末"),
    "visibility": re.compile(r"可见|看见|看到|展示|披露"),
    "brewing": re.compile(r"冲泡|泡水|饮用方式"),
    "boiling": re.compile(r"煮沸|煎煮|煮制"),
    "steeping": re.compile(r"闷泡|浸泡"),
    "refill": re.compile(r"续杯|耐泡"),
    "sensory": re.compile(r"口感|口味|风味|清甘|清甜|醇厚"),
    "aroma": re.compile(r"香度|果香|花香|草本香"),
    "water_color": re.compile(r"水色|清澈|明亮|鲜艳"),
    "process": re.compile(r"工艺|烘干|蒸晒|加工"),
    "duration": re.compile(r"时长|分钟|小时|\d+(?:\.\d+)?h"),
    "certification": re.compile(r"认证|认可|标准"),
    "testing": re.compile(r"检测|检验"),
    "report": re.compile(r"报告"),
    "spec": re.compile(r"规格|净含量|克重"),
    "nutrition": re.compile(r"营养|能量|蛋白质|脂肪|碳水|钠"),
    "warning": re.compile(r"警示|禁用|禁止|不宜|遵医嘱|过敏"),
    "production_date": re.compile(r"生产日期"),
    "shelf_life": re.compile(r"保质期"),
    "storage": re.compile(r"储存|贮存|冷藏"),
    "price": re.compile(r"价格|售价|成交价|优惠|赠品"),
}
HARD_FIELD_CONCEPTS = {
    "origin",
    "report",
    "nutrition",
    "warning",
    "production_date",
    "shelf_life",
    "storage",
    "price",
}
DUPLICATED_CLIENT_WORD_RE = re.compile(r"页面\s*页面|(?:用户原声\s*){2,}")
PACKAGE_COUNT_RE = re.compile(
    r"(?P<start>\d{1,3})(?:\s*(?:~|～|-|—|–|至|到)\s*(?P<end>\d{1,3}))?\s*"
    r"(?P<label>独立装|小包|袋装|袋|包)"
)
TOTAL_WEIGHT_RE = re.compile(
    r"(?:总?净含量|规格)\s*[:：]?\s*(?P<weight>\d+(?:\.\d+)?)\s*(?:g|克)(?:\s*/\s*盒)?|"
    r"(?P<boxed>\d+(?:\.\d+)?)\s*(?:g|克)\s*/\s*盒",
    re.IGNORECASE,
)
PER_UNIT_WEIGHT_RE = re.compile(
    r"(?P<weight>\d+(?:\.\d+)?)\s*(?:g|克)\s*/\s*(?:包|袋)|"
    r"(?:每包|每袋|单包|单袋)[^\d]{0,6}(?P<labeled>\d+(?:\.\d+)?)\s*(?:g|克)",
    re.IGNORECASE,
)
WEIGHT_MENTION_RE = re.compile(
    r"(?<![\d.])(?P<weight>\d+(?:\.\d+)?)\s*(?:g|克)(?![A-Za-z])",
    re.IGNORECASE,
)
MALFORMED_OCR_RE = re.compile(
    r"\boneBag\b|\b\d+\s*[gG]?\s*/\s*[A-Za-z]{3,}\s*/\s*\d+\s*[gG]?\b",
    re.IGNORECASE,
)
PUBLIC_FRAGMENT_RE = re.compile(
    r"仅在\s+出现|与\s*等(?:工艺|页面|信息|主张|口径)?|"
    r"在中(?:以|被|为|记录|说明)|"
    r"列入(?:\s+|\s*(?:PV|SF|SRC|ID|ANCHOR|FABE|CLM|V|F|H|EX|U|DYN|STRAT|GAP|P0D)-\d{3,}\s+)(?:待复核|待确认)(?:项)?|"
    r"(?:相关规格|冲突)在(?:\s+|\s*(?:PV|SF|SRC|ID|ANCHOR|FABE|CLM|V|F|H|EX|U|DYN|STRAT|GAP|P0D)-\d{3,}\s+)留档|"
    r"[；;]\s*详(?:见)?\s*$|"
    r"(?:不同|冲突|差异|不一致)[^。！？\n|]{0,30}[，,；;：:]\s*$|"
    r"独立\s+(?:U|用户原声)\s+用户资料|独立\s+用户原声|用户原声\s+资料|继承\s*P0\s*状态"
)
EMPTY_PARENS_RE = re.compile(r"[（(]\s*[)）]")
DANGLING_ANALYSIS_RE = re.compile(
    r"(?:不扩大(?:到|为)|不自动等于|不等同于|不直接推导(?:为|成)?|"
    r"不推导(?:为|成)?|不能推导(?:为|成)?|不得扩大(?:到|为)|"
    r"不得等同于|易越界为|不预设)\s*(?:[/／]\s*)?"
    r"(?=(?:[)）]\s*)?(?:[，,；;。.!！?？]|$))|"
    r"不能证明\s+是"
)
SKU_SPEC_IN_NAME_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:kg|g|千克|克|ml|毫升|升|袋|包|片)(?:\s*[×xX*]\s*\d+\s*(?:袋|包|片))?",
    re.IGNORECASE,
)
SKU_GAP_PROHIBITION_RE = re.compile(r"(?:相关|该|这些)?规格不得进入\s*SKU\s*名称字段", re.IGNORECASE)
GENERIC_ADVANTAGE_RE = re.compile(
    r"^\s*(?:(?:本品|本商品|当前商品)\s*)?(?:[（(]\s*)?"
    r"基于(?:页面内|当前页面|页面)?(?:对比信息|对比|资料|信息)(?:\s*[)）])?\s*[。.]?\s*$|"
    r"^\s*(?:本品|本商品|当前商品)\s*[。.]?\s*$"
)
UNESTABLISHED_ADVANTAGE_RE = re.compile(
    r"(?:(?:相对|比较)?优势.{0,18}|A\s*层.{0,12})(?:暂不成立|尚未成立|待验证)",
    re.IGNORECASE,
)
CAFFEINE_NEGATIVE_RE = re.compile(r"(?:无|不含|不靠|不依赖|无需依赖)\s*咖啡因|咖啡因\s*(?:为零|零添加|未添加)")
P0_VALUE_AXIS_PATTERNS = {
    "hydration": re.compile(r"补水|多喝水|日常饮水"),
    "sensory": re.compile(r"口感|味道|风味|清甜|清甘|回甘|甜润|温和|香气"),
    "caffeine": re.compile(r"咖啡因|咖啡|提神|睡眠|好眠"),
    "preparation": re.compile(r"额外(?:加料|配料)|调配|熬煮|炖煮|准备|分装|称量"),
    "duration": re.compile(r"整天|全天|续杯|耐泡|持续饮用"),
    "portability": re.compile(r"外出|携带|随身|旅行|出门"),
    "versatility": re.compile(r"冷热|煮沸|闷泡|多种方式|两种方式|不同场景"),
    "visibility": re.compile(r"看得见|可见|透明|产地明确"),
    "trust": re.compile(r"认证|检测|安心|安全|品质"),
    "nutrition": re.compile(r"营养|能量|脂肪|蛋白质|碳水|钠"),
}
INFERRED_DYNAMIC_YEAR_RE = re.compile(
    r"年份.{0,12}(?:根据|依据|按).{0,20}(?:抓取|采集|截图|下载|访问|页面保存).{0,12}(?:推定|推断|补全|确定)"
)
TIME_OF_DAY_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")
TZ_DATETIME_RE = re.compile(r"T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})")
DISALLOWED_TOP_LEVEL_SCRIPT_SUFFIXES = {".py", ".pyw", ".ps1", ".bat", ".cmd", ".exe", ".js", ".vbs"}


def exact_evidence_values(value: Any) -> set[str]:
    text = str(value or "")
    matches = set(REPORT_VALUE_RE.findall(text))
    matches.update(DATE_VALUE_RE.findall(text))
    matches.update(item.strip() for item in METHOD_VALUE_RE.findall(text))
    matches.update(item.strip() for item in METHOD_CODE_RE.findall(text))
    return {item for item in matches if item}


def record_text(record: dict[str, Any]) -> str:
    values: list[str] = []
    for value in record.values():
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif isinstance(value, (str, int, float)):
            values.append(str(value))
    return " ".join(values)


def is_archive_source(record: dict[str, Any]) -> bool:
    """Return whether an inventory record is a container, not directly readable evidence."""

    media_type = str(record.get("media_type", ""))
    relative_path = str(record.get("relative_path", ""))
    return bool(ARCHIVE_MEDIA_RE.search(media_type)) or Path(relative_path).suffix.lower() in ARCHIVE_SUFFIXES


def package_count_ranges_from_text(value: Any) -> list[tuple[int, int, str]]:
    """Return explicit package-count ranges from one text surface."""

    text = INTERNAL_ID_RE.sub("", str(value or ""))
    values: list[tuple[int, int, str]] = []
    for match in PACKAGE_COUNT_RE.finditer(text):
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        values.append((min(start, end), max(start, end), match.group(0)))
    return values


def package_count_ranges(claim: dict[str, Any]) -> list[tuple[int, int, str]]:
    """Return package-count ranges explicit in any original claim."""

    return package_count_ranges_from_text(claim.get("verbatim_text", ""))


def gram_values_from_text(value: Any) -> set[float]:
    """Return explicit gram values from one text surface."""

    return {
        round(float(match.group("weight")), 6)
        for match in WEIGHT_MENTION_RE.finditer(INTERNAL_ID_RE.sub("", str(value or "")))
    }


def normalized_spec_phrase(value: Any) -> str:
    """Normalize spacing and range punctuation for conflict propagation."""

    text = re.sub(r"\s+", "", str(value or ""))
    return text.translate(str.maketrans({"～": "~", "-": "~", "—": "~", "–": "~", "至": "~", "到": "~"}))


def contains_spec_phrase(text: Any, phrase: Any) -> bool:
    normalized_phrase = normalized_spec_phrase(phrase)
    return bool(normalized_phrase) and normalized_phrase in normalized_spec_phrase(text)


def normalized_literal_text(value: Any) -> str:
    """Normalize presentation-only separators for direct-copy comparisons."""

    return re.sub(r"[\s,，。；;、:：!?！？（）()\[\]【】\"'“”‘’]+", "", str(value or ""))


def semantic_reference_units(value: Any) -> set[str]:
    """Return small lexical anchors for checking a reference frame against its facts."""

    text = REFERENCE_BOILERPLATE_RE.sub("", str(value or ""))
    units: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        units.update(
            run[index : index + 2]
            for index in range(len(run) - 1)
            if run[index : index + 2] not in REFERENCE_COMMON_BIGRAMS
        )
    units.update(token.lower() for token in re.findall(r"[A-Za-z0-9]{3,}", text))
    return units


def semantic_field_concepts(value: Any) -> set[str]:
    text = str(value or "")
    return {
        concept
        for concept, pattern in FIELD_CONCEPT_PATTERNS.items()
        if pattern.search(text)
    }


def fact_support_text(
    facts: list[dict[str, Any]],
    claims_by_id: dict[str, dict[str, Any]],
) -> str:
    """Combine the actual fact, quote, and bound-claim text for one field."""

    return " ".join(
        [str(fact.get("statement", "")) for fact in facts]
        + [
            str(quote)
            for fact in facts
            for quote in (fact.get("source_quotes") or [])
        ]
        + [
            str(claims_by_id[claim_id].get("verbatim_text", ""))
            for fact in facts
            for claim_id in (fact.get("claim_ids") or [])
            if claim_id in claims_by_id
        ]
    )


def field_grounding_issues(field_text: Any, support_text: Any) -> list[str]:
    """Return concrete unsupported elements in one factual FABE field."""

    rendered = INTERNAL_ID_RE.sub("", str(field_text or ""))
    support = str(support_text or "")
    issues: list[str] = []

    unsupported_numbers = sorted(
        set(NUMBER_TOKEN_RE.findall(rendered)).difference(NUMBER_TOKEN_RE.findall(support))
    )
    if unsupported_numbers:
        issues.append("数字 " + "/".join(unsupported_numbers))

    normalized_support = normalized_literal_text(support)
    for match in QUOTED_SPAN_RE.finditer(rendered):
        quote = next(group for group in match.groups() if group is not None)
        if normalized_literal_text(quote) not in normalized_support:
            issues.append(f"引号原文“{quote}”")

    segment_source = QUOTED_SPAN_RE.sub("", rendered)
    support_units = semantic_reference_units(support)
    support_concepts = semantic_field_concepts(support)
    for raw_segment in FIELD_SEGMENT_SPLIT_RE.split(segment_source):
        segment = raw_segment.strip(" ：:（）()[]【】")
        if re.fullmatch(r"(?:页面|原文)?(?:写|标示|列出|展示)?(?:与|和|及)?", segment):
            continue
        units = semantic_reference_units(segment)
        if not units:
            continue
        concepts = semantic_field_concepts(segment)
        missing_hard = sorted(concepts.intersection(HARD_FIELD_CONCEPTS).difference(support_concepts))
        concept_required = max(1, int(len(concepts) * 0.5 + 0.999)) if concepts else 0
        concept_overlap = len(concepts.intersection(support_concepts))
        if missing_hard or (concepts and concept_overlap < concept_required) or (
            not concepts and not units.intersection(support_units)
        ):
            compact = re.sub(r"\s+", "", segment)
            issues.append(f"语义分段“{compact[:32]}”")
    return list(dict.fromkeys(issues))


def claim_total_weights(claim: dict[str, Any]) -> list[float]:
    text = str(claim.get("verbatim_text", ""))
    if re.search(r"每包|每袋|单包|单袋", f"{claim.get('label', '')} {text}"):
        return []
    values: list[float] = []
    for match in TOTAL_WEIGHT_RE.finditer(text):
        raw = match.group("weight") or match.group("boxed")
        if raw:
            values.append(float(raw))
    return values


def claim_per_unit_weights(claim: dict[str, Any]) -> list[float]:
    text = str(claim.get("verbatim_text", ""))
    values: list[float] = []
    for match in PER_UNIT_WEIGHT_RE.finditer(text):
        raw = match.group("weight") or match.group("labeled")
        if raw:
            values.append(float(raw))
    if not values and re.search(r"每包|每袋|单包|单袋", str(claim.get("label", ""))):
        simple = re.search(r"净含量\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:g|克)", text, re.IGNORECASE)
        if simple:
            values.append(float(simple.group(1)))
    return values


def markdown_public_cells(text: str) -> list[str]:
    cells: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        parts = [part.strip() for part in stripped[1:-1].split("|")]
        if parts and all(re.fullmatch(r":?-{3,}:?", part) for part in parts):
            continue
        cells.extend(part for part in parts if part)
    return cells


def parse_reference_date(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def timestamp_after_file(timestamp: datetime | None, path: Path, tolerance_seconds: float = 5.0) -> bool:
    """Return true when a recorded event occurs after the ledger was written."""

    if timestamp is None or not path.is_file():
        return False
    return timestamp.timestamp() > path.stat().st_mtime + tolerance_seconds


def file_written_long_after(path: Path, anchor_path: Path, tolerance_seconds: float = 300.0) -> bool:
    """Return true when a final artifact was written long after the manifest."""

    if not path.is_file() or not anchor_path.is_file():
        return False
    return path.stat().st_mtime > anchor_path.stat().st_mtime + tolerance_seconds


def file_written_long_after_timestamp(
    path: Path,
    timestamp: datetime | None,
    tolerance_seconds: float = 300.0,
) -> bool:
    """Return true when an artifact was finalized long after logical updated_at."""

    if timestamp is None or not path.is_file():
        return False
    return path.stat().st_mtime > timestamp.timestamp() + tolerance_seconds


def suspicious_fixed_cadence(timestamps: list[datetime]) -> bool:
    """Detect dominant machine-generated intervals without rejecting short runs."""

    if len(timestamps) < 5:
        return False
    deltas = [
        round((current - previous).total_seconds(), 3)
        for previous, current in zip(timestamps, timestamps[1:])
    ]
    positive = [delta for delta in deltas if delta > 0]
    if len(positive) != len(deltas):
        return True
    dominant_count = Counter(positive).most_common(1)[0][1]
    return dominant_count >= max(4, int(len(deltas) * 0.8 + 0.999))


def suspicious_dense_cadence(timestamps: list[datetime]) -> bool:
    """Detect implausibly dense long runs that vary by only a few seconds."""

    if len(timestamps) < 10:
        return False
    ordered = sorted(timestamps)
    deltas = [
        (current - previous).total_seconds()
        for previous, current in zip(ordered, ordered[1:])
    ]
    if any(delta <= 0 for delta in deltas):
        return True
    ranked = sorted(deltas)
    median = ranked[len(ranked) // 2]
    percentile_90 = ranked[min(len(ranked) - 1, int(len(ranked) * 0.9))]
    total_span = (ordered[-1] - ordered[0]).total_seconds()
    return median <= 3.0 and percentile_90 <= 5.0 and total_span <= len(ordered) * 5.0


def suspicious_bounded_micro_cadence(timestamps: list[datetime]) -> bool:
    """Detect long timestamp runs manufactured from a tiny 1-7 second integer set."""

    if len(timestamps) < 30:
        return False
    ordered = sorted(timestamps)
    deltas = [
        (current - previous).total_seconds()
        for previous, current in zip(ordered, ordered[1:])
    ]
    if any(delta <= 0 for delta in deltas):
        return True
    integer_like = [abs(delta - round(delta)) <= 0.05 for delta in deltas]
    rounded = {round(delta) for delta in deltas}
    return (
        sum(integer_like) >= int(len(deltas) * 0.95 + 0.999)
        and min(deltas) >= 1.0
        and max(deltas) <= 7.0
        and len(rounded) <= 5
    )


def suspicious_bounded_audit_cadence(timestamps: list[datetime]) -> bool:
    """Detect long audit runs filled from a bounded alternating integer schedule."""

    if len(timestamps) < 25:
        return False
    ordered = sorted(timestamps)
    deltas = [
        (current - previous).total_seconds()
        for previous, current in zip(ordered, ordered[1:])
    ]
    if any(delta <= 0 for delta in deltas):
        return True
    integer_ratio = sum(abs(delta - round(delta)) <= 0.05 for delta in deltas) / len(deltas)
    directions = [
        1 if current > previous else -1 if current < previous else 0
        for previous, current in zip(deltas, deltas[1:])
    ]
    nonzero = [direction for direction in directions if direction]
    alternations = sum(
        current != previous
        for previous, current in zip(nonzero, nonzero[1:])
    )
    alternation_ratio = alternations / max(1, len(nonzero) - 1)
    rounded_values = {round(delta) for delta in deltas}
    return (
        integer_ratio >= 0.95
        and min(deltas) >= 8.0
        and max(deltas) <= 45.0
        and len(rounded_values) <= max(12, int(len(deltas) * 0.65))
        and alternation_ratio >= 0.82
    )


def suspicious_repeating_cadence(timestamps: list[datetime]) -> bool:
    """Detect short interval cycles repeated through a long audit sequence."""

    if len(timestamps) < 12:
        return False
    ordered = sorted(timestamps)
    deltas = [
        round((current - previous).total_seconds(), 3)
        for previous, current in zip(ordered, ordered[1:])
    ]
    if any(delta <= 0 for delta in deltas):
        return True
    for period in range(2, min(8, len(deltas) // 3) + 1):
        matches = sum(
            abs(delta - deltas[index % period]) <= 0.001
            for index, delta in enumerate(deltas)
        )
        if matches >= max(period * 3, int(len(deltas) * 0.9 + 0.999)):
            return True
    return False


def suspicious_parallel_audit_timing(
    first_pass: list[datetime],
    second_pass: list[datetime],
) -> bool:
    """Detect a copied audit schedule shifted by one constant offset."""

    if len(first_pass) < 8 or len(first_pass) != len(second_pass):
        return False
    first_deltas = [
        round((current - previous).total_seconds(), 3)
        for previous, current in zip(first_pass, first_pass[1:])
    ]
    second_deltas = [
        round((current - previous).total_seconds(), 3)
        for previous, current in zip(second_pass, second_pass[1:])
    ]
    offsets = [
        round((second - first).total_seconds(), 3)
        for first, second in zip(first_pass, second_pass)
    ]
    return (
        all(offset > 0 for offset in offsets)
        and len(set(offsets)) == 1
        and first_deltas == second_deltas
    )


def normalized_content_signature(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    """Build a whitespace-insensitive signature for semantic duplicate checks."""

    parts: list[str] = []
    for field in fields:
        value = record.get(field)
        if isinstance(value, list):
            rendered = "|".join(str(item).strip() for item in value)
        else:
            rendered = str(value or "").strip()
        parts.append(re.sub(r"\s+", "", rendered))
    return "\u241f".join(parts)


def expected_execution_axis(
    value_ids: list[Any],
    values_by_id: dict[Any, dict[str, Any]],
) -> str:
    """Build the only accepted public axis from the explicitly selected values."""

    statements = [
        str(values_by_id.get(value_id, {}).get("value_statement", "")).strip()
        for value_id in value_ids
        if str(values_by_id.get(value_id, {}).get("value_statement", "")).strip()
    ]
    return "当前执行主轴调用：" + "；".join(statements) if statements else ""


def without_comparison_denials(value: Any) -> str:
    """Remove explicit comparison prohibitions before testing positive claims."""

    return COMPARISON_DENIAL_SPAN_RE.sub("", str(value or ""))


def classify_time_scope(value: Any, reference: date | None) -> str | None:
    """Classify a fully dated DYN scope at the delivery snapshot date."""

    if reference is None:
        return None
    dates: list[date] = []
    for year, month, day in DATE_RE.findall(str(value)):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            return None
    if not dates:
        return None
    start = dates[0]
    end = dates[-1]
    if reference < start:
        return "upcoming"
    if reference > end:
        return "expired"
    return "active"


def iter_analysis_texts(
    facts: list[dict[str, Any]],
    fabe: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    values: list[dict[str, Any]],
    decision: dict[str, Any],
) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for item in facts:
        if item.get("fact_type") == "H":
            texts.extend((f"{item.get('fact_id')}.{key}", str(item.get(key, ""))) for key in ("statement", "boundary"))
    for item in fabe:
        texts.extend(
            (f"{item.get('fabe_id')}.{key}", str(item.get(key, "")))
            for key in ("advantage", "benefit", "user_language", "boundary")
        )
    for item in anchors:
        texts.append((f"{item.get('anchor_id')}.statement", str(item.get("statement", ""))))
    for item in values:
        texts.extend(
            (f"{item.get('value_id')}.{key}", str(item.get(key, "")))
            for key in ("user_task", "value_statement", "user_perception_goal")
        )
    texts.extend(
        (f"p0_decision.{key}", str(decision.get(key, "")))
        for key in ("rationale", "public_rationale", "current_execution_axis")
    )
    return texts


def iter_client_narrative_texts(
    manifest: dict[str, Any],
    facts: list[dict[str, Any]],
    fabe: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    values: list[dict[str, Any]],
    decision: dict[str, Any],
    gaps: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Return authored narrative fields that may reach clients or downstream Skills."""

    texts: list[tuple[str, str]] = [
        ("product_manifest.sku_basis", str(manifest.get("sku_basis", ""))),
    ]
    texts.extend(
        (f"product_manifest.limitations[{index}]", str(value))
        for index, value in enumerate(manifest.get("limitations") or [])
    )
    for item in facts:
        texts.extend(
            (f"{item.get('fact_id')}.{key}", str(item.get(key, "")))
            for key in ("statement", "boundary")
        )
    for item in fabe:
        texts.extend(
            (f"{item.get('fabe_id')}.{key}", str(item.get(key, "")))
            for key in (
                "feature",
                "advantage",
                "benefit",
                "evidence",
                "reference_frame",
                "user_language",
                "boundary",
            )
        )
    for item in anchors:
        texts.extend(
            (f"{item.get('anchor_id')}.{key}", str(item.get(key, "")))
            for key in ("statement", "boundary")
        )
    for item in values:
        texts.extend(
            (f"{item.get('value_id')}.{key}", str(item.get(key, "")))
            for key in ("user_task", "value_statement", "user_perception_goal", "scope")
        )
        texts.extend(
            (f"{item.get('value_id')}.cannot_prove[{index}]", str(value))
            for index, value in enumerate(item.get("cannot_prove") or [])
        )
    texts.extend(
        (f"p0_decision.{key}", str(decision.get(key, "")))
        for key in ("rationale", "public_rationale", "current_execution_axis")
    )
    for key in ("cannot_prove", "validation_questions"):
        texts.extend(
            (f"p0_decision.{key}[{index}]", str(value))
            for index, value in enumerate(decision.get(key) or [])
        )
    for item in gaps:
        texts.extend(
            (f"{item.get('gap_id')}.{key}", str(item.get(key, "")))
            for key in ("missing", "impact", "minimum_needed")
        )
    return texts


def missing_fields(record: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(required.difference(record))


def duplicate_ids(records: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in records:
        value = str(record.get(key, ""))
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_delivery(delivery: Path) -> dict[str, Any]:
    delivery = delivery.resolve()
    paths = delivery_paths(delivery)
    errors: list[str] = []
    warnings: list[str] = []
    missing_required = False

    for name, path in paths.items():
        if name == "audit_cards_dir":
            if not path.is_dir():
                errors.append(f"缺少必需目录 {name}: {path}")
                missing_required = True
        elif not path.is_file():
            errors.append(f"缺少必需文件 {name}: {path}")
            missing_required = True
    if delivery.is_dir():
        for entry in delivery.iterdir():
            if entry.is_file() and entry.suffix.lower() in DISALLOWED_TOP_LEVEL_SCRIPT_SUFFIXES:
                errors.append(f"正式交付根目录不得包含修正脚本或可执行文件: {entry.name}")
    if missing_required:
        return {
            "status": "failed",
            "delivery": str(delivery),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    try:
        manifest = read_json(paths["manifest"])
        source_inventory = read_jsonl(paths["source_inventory"])
        audit_card_ledger = read_jsonl(paths["audit_card_ledger"])
        source_observations = read_jsonl(paths["source_observations"])
        source_claims = read_jsonl(paths["source_claims"])
        sources = read_jsonl(paths["sources"])
        facts = read_jsonl(paths["facts"])
        fabe = read_jsonl(paths["fabe"])
        anchors = read_jsonl(paths["anchors"])
        values = read_jsonl(paths["values"])
        decision = read_json(paths["decision"])
        gaps = read_jsonl(paths["gaps"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return {
            "status": "failed",
            "delivery": str(delivery),
            "errors": errors,
            "warnings": warnings,
            "counts": {},
        }

    counts = {
        "source_files": len(source_inventory),
        "audit_cards": sum(1 for item in audit_card_ledger if item.get("status") == "ready"),
        "source_observations": len(source_observations),
        "source_claims": len(source_claims),
        "sources": len(sources),
        "facts": len(facts),
        "fabe": len(fabe),
        "anchors": len(anchors),
        "values": len(values),
        "gaps": len(gaps),
    }

    missing = missing_fields(manifest, MANIFEST_FIELDS)
    if missing:
        errors.append(f"product_manifest.json 缺少字段: {', '.join(missing)}")
    if not re.fullmatch(r"PV-[0-9a-f]{12}", str(manifest.get("product_value_id", ""))):
        errors.append("product_value_id 必须使用 PV- 加 12 位小写十六进制")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须是 {SCHEMA_VERSION}")
    if manifest.get("skill_version") != SKILL_VERSION:
        errors.append(f"skill_version 必须是 {SKILL_VERSION}")
    if not re.fullmatch(r"ID-\d{3,}", str(manifest.get("identity_id", ""))):
        errors.append("identity_id 格式无效")
    if manifest.get("input_mode") not in INPUT_MODES:
        errors.append("input_mode 不在允许范围")
    if manifest.get("fc") not in FC_LEVELS:
        errors.append("fc 不在 FC0—FC3 范围")
    if manifest.get("sc") not in SC_LEVELS:
        errors.append("sc 不在 SC0—SC3 范围")
    if manifest.get("pkg_level") not in PKG_LEVELS:
        errors.append("pkg_level 不在 PKG-L0—PKG-L4 范围")
    if manifest.get("analysis_status") not in ANALYSIS_STATUSES:
        errors.append("analysis_status 不在允许范围")
    if manifest.get("delivery_status") not in DELIVERY_STATUSES:
        errors.append("delivery_status 不在允许范围")
    if manifest.get("sku_status") not in SKU_STATUSES:
        errors.append("sku_status 必须是 confirmed/partial/unverified")
    if not str(manifest.get("sku_basis", "")).strip():
        errors.append("sku_basis 不得为空；标题片段不能单独作为 SKU 确认依据")
    if FILENAME_METADATA_RE.search(str(manifest.get("sku_basis", ""))):
        errors.append("sku_basis 不得把文件名或文件路径当作商品规格依据，也不得据此制造 SKU 事实冲突")
    if manifest.get("sku_status") == "confirmed":
        sku_basis = str(manifest.get("sku_basis", ""))
        if not re.search(r"SKU\s*选择|规格(?:栏|表|选择)|包装|商品信息|成交单元|订单", sku_basis, re.IGNORECASE):
            errors.append("sku_status=confirmed 时，sku_basis 必须来自 SKU 选择器、包装、规格表、商品信息区或订单成交单元")
    sku_basis = str(manifest.get("sku_basis", ""))
    sku_text = str(manifest.get("sku", "")).strip()
    if (
        sku_text
        and manifest.get("sku_status") in {"partial", "unverified"}
        and TITLE_EVIDENCE_RE.search(sku_basis)
        and HIGHER_PRIORITY_SKU_RE.search(sku_basis)
        and SKU_CONFLICT_RE.search(sku_basis)
        and sku_text in sku_basis
    ):
        errors.append("标题或文件名与包装、规格表或商品信息区冲突时，不得继续把标题片段写成当前 SKU；应改用可确认的标准成交单元或明确待确认")
    if manifest.get("analysis_status") == "draft":
        errors.append("analysis_status=draft，不得作为正式交付")
    if not isinstance(manifest.get("limitations"), list):
        errors.append("limitations 必须是数组")
    manifest_created_at = parse_datetime(manifest.get("created_at"))
    manifest_updated_at = parse_datetime(manifest.get("updated_at"))
    if manifest_created_at is None:
        errors.append("product_manifest.created_at 必须是带时区的完整 ISO 时间")
    if manifest_updated_at is None:
        errors.append("product_manifest.updated_at 必须是带时区的完整 ISO 时间")
    if (
        manifest_created_at is not None
        and manifest_updated_at is not None
        and manifest_updated_at < manifest_created_at
    ):
        errors.append("product_manifest.updated_at 不得早于 created_at")
    if timestamp_after_file(manifest_updated_at, paths["manifest"]):
        errors.append("product_manifest.updated_at 晚于 manifest 文件实际写入时间，存在事后生成或未来时间")
    if manifest_updated_at is not None:
        for report_key in ("report_01", "report_02"):
            if timestamp_after_file(manifest_updated_at, paths[report_key]):
                errors.append(f"product_manifest.updated_at 晚于 {paths[report_key].name} 实际生成时间")
    late_artifacts: list[str] = []
    for artifact_key in (
        "source_observations",
        "source_claims",
        "sources",
        "facts",
        "fabe",
        "anchors",
        "values",
        "decision",
        "gaps",
        "report_01",
        "report_02",
    ):
        if file_written_long_after(paths[artifact_key], paths["manifest"]):
            late_artifacts.append(paths[artifact_key].name)
    if late_artifacts:
        errors.append(
            "以下正式账本或报告在 product_manifest.json 之后超过 5 分钟仍被修改："
            f"{', '.join(late_artifacts)}；完成最终建账和报告生成后必须刷新 updated_at 并重写 manifest"
        )
    logically_late_artifacts: list[str] = []
    for artifact_key in (
        "source_observations",
        "source_claims",
        "sources",
        "facts",
        "fabe",
        "anchors",
        "values",
        "decision",
        "gaps",
        "report_01",
        "report_02",
    ):
        if file_written_long_after_timestamp(paths[artifact_key], manifest_updated_at):
            logically_late_artifacts.append(paths[artifact_key].name)
    if logically_late_artifacts:
        errors.append(
            "以下正式账本或报告在 product_manifest.updated_at 之后超过 5 分钟才生成或修改："
            f"{', '.join(logically_late_artifacts)}；updated_at 必须覆盖最终账本与报告收口时间"
        )

    ledger_specs = (
        ("source_inventory", source_inventory, "source_file_id", SOURCE_INVENTORY_FIELDS, r"SF-\d{3,}"),
        ("source_audit_card_ledger", audit_card_ledger, "source_file_id", AUDIT_CARD_FIELDS, r"SF-\d{3,}"),
        ("source_observation", source_observations, "observation_id", SOURCE_OBSERVATION_FIELDS, r"OBS-\d{3,}"),
        ("source_claim_ledger", source_claims, "claim_id", SOURCE_CLAIM_FIELDS, r"CLM-\d{3,}"),
        ("source_ledger", sources, "source_id", SOURCE_FIELDS, r"SRC-\d{3,}"),
        ("fact_ledger", facts, "fact_id", FACT_FIELDS, r"(?:F|STRAT|DYN|U|EX|H)-\d{3,}"),
        ("fabe_ledger", fabe, "fabe_id", FABE_FIELDS, r"FABE-\d{3,}"),
        ("anchor_ledger", anchors, "anchor_id", ANCHOR_FIELDS, r"ANCHOR-\d{3,}"),
        ("value_ledger", values, "value_id", VALUE_FIELDS, r"V-\d{3,}"),
        ("gap_ledger", gaps, "gap_id", GAP_FIELDS, r"GAP-\d{3,}"),
    )
    for ledger_name, records, id_key, fields, pattern in ledger_specs:
        for index, record in enumerate(records, start=1):
            record_missing = missing_fields(record, fields)
            if record_missing:
                errors.append(f"{ledger_name} 第 {index} 条缺少字段: {', '.join(record_missing)}")
            if not re.fullmatch(pattern, str(record.get(id_key, ""))):
                errors.append(f"{ledger_name} 第 {index} 条 {id_key} 格式无效")
        duplicates = duplicate_ids(records, id_key)
        if duplicates:
            errors.append(f"{ledger_name} 存在重复 ID: {', '.join(duplicates)}")

    source_files_by_id = {item.get("source_file_id"): item for item in source_inventory}
    derived_page_images = []
    original_document_sources = []
    for item in source_inventory:
        source_file_id = str(item.get("source_file_id", ""))
        relative_path = str(item.get("relative_path", ""))
        filename = str(item.get("filename", ""))
        if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            errors.append(f"{source_file_id} 的 relative_path 必须是输入目录内的相对路径")
        if Path(relative_path).name != filename:
            errors.append(f"{source_file_id} 的 filename 与 relative_path 不一致")
        if not isinstance(item.get("size_bytes"), int) or item.get("size_bytes", -1) < 0:
            errors.append(f"{source_file_id} 的 size_bytes 必须是非负整数")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            errors.append(f"{source_file_id} 的 sha256 必须是 64 位小写十六进制")
        if item.get("status") != "indexed":
            errors.append(f"{source_file_id} 的 status 必须是 indexed")
        if DERIVED_PAGE_FILENAME_RE.fullmatch(filename):
            derived_page_images.append(item)
        if str(item.get("media_type", "")).lower() == "application/pdf" or Path(filename).suffix.lower() == ".pdf":
            original_document_sources.append(item)

    derived_page_numbers = sorted(
        int(DERIVED_PAGE_FILENAME_RE.fullmatch(str(item.get("filename", ""))).group(1))
        for item in derived_page_images
        if DERIVED_PAGE_FILENAME_RE.fullmatch(str(item.get("filename", "")))
    )
    looks_like_rendered_document = (
        len(derived_page_numbers) >= 10
        and derived_page_numbers == list(range(1, len(derived_page_numbers) + 1))
    )
    if looks_like_rendered_document and not original_document_sources:
        errors.append(
            "来源清单包含连续 page_XXX 派生页图，但没有保留原始 PDF 来源身份与 SHA-256；"
            "PDF 应作为父来源进入 source_inventory，并用 document_text 记录来源身份，派生页图仅承担逐页视觉核对"
        )
    if looks_like_rendered_document and original_document_sources:
        original_document_ids = {
            str(item.get("source_file_id", "")) for item in original_document_sources
        }
        for item in derived_page_images:
            parent_id = str(item.get("parent_source_file_id", "")).strip()
            if parent_id not in original_document_ids:
                errors.append(
                    f"{item.get('source_file_id')} 是 PDF 派生页图，但 parent_source_file_id 未绑定清单中的原始 PDF；"
                    "派生页必须保留到父来源的可回溯关系"
                )
    if looks_like_rendered_document and len(original_document_sources) == 1 and manifest.get("input_mode") == "mixed" and not any(
        item
        for item in source_inventory
        if item not in derived_page_images and item not in original_document_sources
    ):
        errors.append("输入仅来自一个 PDF 的派生页图时，input_mode 应为 document，不得标为 mixed")

    audit_cards_by_file_id = {item.get("source_file_id"): item for item in audit_card_ledger}
    data_dir = paths["manifest"].parent.resolve()
    for card in audit_card_ledger:
        source_file_id = str(card.get("source_file_id", ""))
        if source_file_id not in source_files_by_id:
            errors.append(f"审计卡台账引用了不存在的 source_file_id: {source_file_id}")
    for source_file_id, indexed in source_files_by_id.items():
        card = audit_cards_by_file_id.get(source_file_id)
        if card is None:
            errors.append(f"{source_file_id} 缺少来源审计卡台账记录")
            continue
        for key in ("relative_path", "media_type"):
            if card.get(key) != indexed.get(key):
                errors.append(f"{source_file_id} 的审计卡台账 {key} 与来源清单不一致")
        if card.get("source_sha256") != indexed.get("sha256"):
            errors.append(f"{source_file_id} 的审计卡台账 source_sha256 与来源清单不一致")
        media_type = str(indexed.get("media_type", ""))
        if media_type.startswith("image/"):
            if card.get("status") != "ready":
                errors.append(f"{source_file_id} 是图片来源，审计卡状态必须是 ready")
                continue
            relative_card = str(card.get("audit_card_path", ""))
            candidate = (data_dir / Path(relative_card)).resolve()
            if not relative_card or candidate == data_dir or data_dir not in candidate.parents:
                errors.append(f"{source_file_id} 的 audit_card_path 必须位于交付 data 目录内")
                continue
            if not candidate.is_file():
                errors.append(f"{source_file_id} 的审计卡文件不存在: {relative_card}")
                continue
            card_bytes = candidate.read_bytes()
            card_sha256 = hashlib.sha256(card_bytes).hexdigest()
            if card_sha256 != card.get("audit_card_sha256"):
                errors.append(f"{source_file_id} 的审计卡 SHA-256 与台账不一致")
            try:
                card_text = card_bytes.decode("utf-8")
                metadata_match = re.search(
                    r'<metadata id="brandbai-source-audit">(.*?)</metadata>',
                    card_text,
                    re.DOTALL,
                )
                if not metadata_match:
                    raise ValueError("缺少审计元数据")
                metadata = json.loads(html.unescape(metadata_match.group(1)))
                payload_match = re.search(r'href="data:[^;\"]+;base64,([^\"]+)"', card_text)
                if not payload_match:
                    raise ValueError("缺少内嵌原图")
                embedded = base64.b64decode(payload_match.group(1), validate=True)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{source_file_id} 的审计卡无法复核: {exc}")
            else:
                for key, expected in (
                    ("source_file_id", source_file_id),
                    ("relative_path", indexed.get("relative_path")),
                    ("source_sha256", indexed.get("sha256")),
                    ("media_type", indexed.get("media_type")),
                ):
                    if metadata.get(key) != expected:
                        errors.append(f"{source_file_id} 的审计卡元数据 {key} 与来源清单不一致")
                if hashlib.sha256(embedded).hexdigest() != indexed.get("sha256"):
                    errors.append(f"{source_file_id} 审计卡内嵌图片与来源文件 SHA-256 不一致")
                source_width, source_height = image_dimensions(media_type, embedded)
                expected_display_height = (source_height * DISPLAY_WIDTH + source_width - 1) // source_width
                expected_dimensions = {
                    "source_width": source_width,
                    "source_height": source_height,
                    "display_width": DISPLAY_WIDTH,
                    "display_height": expected_display_height,
                    "card_height": 460 + expected_display_height,
                }
                for key, expected in expected_dimensions.items():
                    if metadata.get(key) != expected:
                        errors.append(f"{source_file_id} 的审计卡尺寸元数据 {key} 与内嵌原图不一致")
                root_match = re.search(
                    r'<svg[^>]*\bheight="(\d+)"[^>]*\bviewBox="0 0 1400 (\d+)"',
                    card_text,
                )
                if not root_match or any(int(item) != expected_dimensions["card_height"] for item in root_match.groups()):
                    errors.append(f"{source_file_id} 的审计卡画布高度未按原图比例生成")
        else:
            if card.get("status") != "not_applicable":
                errors.append(f"{source_file_id} 不是图片来源，审计卡状态应为 not_applicable")
            if card.get("audit_card_path") or card.get("audit_card_sha256"):
                errors.append(f"{source_file_id} 不是图片来源，不应生成视觉审计卡")

    observations_by_id = {item.get("observation_id"): item for item in source_observations}
    observations_by_file_id: dict[str, list[dict[str, Any]]] = {}
    image_observations: list[dict[str, Any]] = []
    for observation in source_observations:
        observation_id = str(observation.get("observation_id", ""))
        source_file_id = str(observation.get("source_file_id", ""))
        indexed = source_files_by_id.get(source_file_id)
        if indexed is None:
            if not (not source_file_id and observation.get("inspection_method") == "official_url"):
                errors.append(f"{observation_id} 引用了不存在的 source_file_id: {source_file_id}")
        else:
            if observation.get("relative_path") != indexed.get("relative_path"):
                errors.append(f"{observation_id} 的 relative_path 与 {source_file_id} 不一致")
        # Local source files must map one-to-one to an observation. Official URLs
        # intentionally have no source_file_id, so grouping them under an empty
        # key would incorrectly make multiple independent URLs look duplicated.
        if source_file_id:
            observations_by_file_id.setdefault(source_file_id, []).append(observation)
        if observation.get("inspection_method") not in OBSERVATION_METHODS:
            errors.append(f"{observation_id} 的 inspection_method 不在允许范围")
        if observation.get("inspection_status") not in OBSERVATION_STATUSES:
            errors.append(f"{observation_id} 的 inspection_status 不在允许范围")
        if (
            indexed
            and (
                str(indexed.get("media_type", "")).lower() == "application/pdf"
                or Path(str(indexed.get("filename", ""))).suffix.lower() == ".pdf"
            )
            and observation.get("inspection_method") != "document_text"
        ):
            errors.append(f"{observation_id} 对应原始 PDF，inspection_method 必须是 document_text")
        text_density = observation.get("text_density")
        if text_density not in TEXT_DENSITIES:
            errors.append(f"{observation_id} 的 text_density 必须是 none/low/medium/high")
        content_flags = observation.get("content_flags")
        if not isinstance(content_flags, list):
            errors.append(f"{observation_id} 的 content_flags 必须是数组")
            content_flags = []
        else:
            unknown_flags = sorted(set(str(item) for item in content_flags).difference(CONTENT_FLAGS))
            if unknown_flags:
                errors.append(f"{observation_id} 的 content_flags 含未知类型: {', '.join(unknown_flags)}")
            if len(content_flags) != len(set(str(item) for item in content_flags)):
                errors.append(f"{observation_id} 的 content_flags 不得重复")
        if text_density == "none" and content_flags:
            errors.append(f"{observation_id} 标记无文字时不应填写 content_flags")
        if text_density in {"medium", "high"} and not content_flags:
            errors.append(f"{observation_id} 是中高文字密度来源，必须标记可见内容类型")
        if observation.get("inspection_status") == "inspected":
            for key in ("content_type", "title", "visible_heading", "visible_text_excerpt", "inspected_at"):
                if not str(observation.get(key, "")).strip():
                    errors.append(f"{observation_id} 已标记 inspected，但 {key} 为空")
        if indexed and is_archive_source(indexed):
            if observation.get("inspection_method") != "unsupported_archive":
                errors.append(f"{observation_id} 是压缩包或归档文件，inspection_method 必须是 unsupported_archive")
            if observation.get("inspection_status") != "unreadable":
                errors.append(f"{observation_id} 是压缩包或归档文件，必须明确标记 unreadable，不能当作已读取页面")
            if not str(observation.get("title", "")).strip() or not str(observation.get("inspected_at", "")).strip():
                errors.append(f"{observation_id} 是压缩包或归档文件，仍须记录文件标题和实际检查时间")
            if text_density != "none" or content_flags:
                errors.append(f"{observation_id} 是未解压归档文件，不得登记正文密度或页面内容类型")
        if indexed and str(indexed.get("media_type", "")).startswith("image/"):
            image_observations.append(observation)
            card = audit_cards_by_file_id.get(source_file_id, {})
            if observation.get("inspection_status") != "inspected":
                errors.append(f"{observation_id} 是图片来源，必须完成带身份审计卡的逐图核对")
            if observation.get("inspection_method") != "visual_stamped_card":
                errors.append(f"{observation_id} 是图片来源，必须打开带文件名与哈希的审计卡并使用 visual_stamped_card")
            if not observation.get("audit_card_sha256") or observation.get("audit_card_sha256") != card.get("audit_card_sha256"):
                errors.append(f"{observation_id} 的 audit_card_sha256 与 {source_file_id} 审计卡不一致")
            first_sequence = observation.get("first_pass_sequence")
            second_sequence = observation.get("second_pass_sequence")
            if not isinstance(first_sequence, int) or isinstance(first_sequence, bool) or first_sequence < 1:
                errors.append(f"{observation_id} 的 first_pass_sequence 必须是正整数")
            if not isinstance(second_sequence, int) or isinstance(second_sequence, bool) or second_sequence < 1:
                errors.append(f"{observation_id} 的 second_pass_sequence 必须是正整数")
            if observation.get("second_pass_status") != "match":
                errors.append(f"{observation_id} 的逆序复核必须标记 second_pass_status=match")
            for key in ("second_pass_heading", "second_pass_excerpt", "second_pass_at"):
                if not str(observation.get(key, "")).strip():
                    errors.append(f"{observation_id} 已完成图片初检，但 {key} 为空")
            if str(observation.get("second_pass_heading", "")).strip() != str(observation.get("visible_heading", "")).strip():
                errors.append(f"{observation_id} 的正序与逆序标题核对不一致")
            if str(observation.get("second_pass_excerpt", "")).strip() != str(observation.get("visible_text_excerpt", "")).strip():
                errors.append(f"{observation_id} 的正序与逆序摘录核对不一致")
            first_at = parse_datetime(observation.get("inspected_at"))
            second_at = parse_datetime(observation.get("second_pass_at"))
            if first_at is None or second_at is None:
                errors.append(f"{observation_id} 的两次核对时间必须是完整 ISO 时间")
            elif second_at <= first_at:
                errors.append(f"{observation_id} 的逆序复核时间必须晚于正序初检")
            if exact_evidence_values(
                f"{observation.get('visible_heading', '')} {observation.get('visible_text_excerpt', '')} "
                f"{observation.get('second_pass_heading', '')} {observation.get('second_pass_excerpt', '')}"
            ):
                errors.append(f"{observation_id} 是页面图片，不得在逐图观察中抄录报告编号、日期或检测方法等精确小字")
        elif indexed:
            if observation.get("audit_card_sha256"):
                errors.append(f"{observation_id} 不是图片来源，audit_card_sha256 应为空")
            if observation.get("first_pass_sequence") != 0 or observation.get("second_pass_sequence") != 0:
                errors.append(f"{observation_id} 不是图片来源，两次图片核对序号都应为 0")
            if observation.get("second_pass_status") != "not_applicable":
                errors.append(f"{observation_id} 不是图片来源，second_pass_status 应为 not_applicable")
            if any(str(observation.get(key, "")).strip() for key in ("second_pass_heading", "second_pass_excerpt", "second_pass_at")):
                errors.append(f"{observation_id} 不是图片来源，不应填写图片逆序复核内容")
    for source_file_id, records in observations_by_file_id.items():
        if len(records) > 1:
            errors.append(f"{source_file_id} 存在多条逐文件核对记录；每个原文件只能保留一条当前记录")
    for source_file_id in source_files_by_id:
        if source_file_id not in observations_by_file_id:
            errors.append(f"{source_file_id} 尚无逐文件核对记录；清单中的每个文件都必须先检查或明确标记不可读")

    if image_observations:
        expected_sequences = list(range(1, len(image_observations) + 1))
        first_sequences = sorted(
            item.get("first_pass_sequence")
            for item in image_observations
            if isinstance(item.get("first_pass_sequence"), int) and not isinstance(item.get("first_pass_sequence"), bool)
        )
        second_sequences = sorted(
            item.get("second_pass_sequence")
            for item in image_observations
            if isinstance(item.get("second_pass_sequence"), int) and not isinstance(item.get("second_pass_sequence"), bool)
        )
        if first_sequences != expected_sequences:
            errors.append("图片正序初检序号必须从 1 连续编号，且每张图片只出现一次")
        if second_sequences != expected_sequences:
            errors.append("图片逆序复核序号必须从 1 连续编号，且每张图片只出现一次")
        for observation in image_observations:
            first_sequence = observation.get("first_pass_sequence")
            second_sequence = observation.get("second_pass_sequence")
            if isinstance(first_sequence, int) and isinstance(second_sequence, int):
                expected_reverse = len(image_observations) + 1 - first_sequence
                if second_sequence != expected_reverse:
                    errors.append(f"{observation.get('observation_id')} 未按正序的反向顺序完成第二遍复核")
        first_times = [parse_datetime(item.get("inspected_at")) for item in image_observations]
        second_times = [parse_datetime(item.get("second_pass_at")) for item in image_observations]
        valid_first_times = [item for item in first_times if item is not None]
        valid_second_times = [item for item in second_times if item is not None]
        if len(set(valid_first_times)) != len(image_observations):
            errors.append("每张图片的正序初检时间必须独立记录，不能批量填入同一时间")
        if len(set(valid_second_times)) != len(image_observations):
            errors.append("每张图片的逆序复核时间必须独立记录，不能批量填入同一时间")
        sequence_values_valid = all(
            isinstance(item.get(key), int) and not isinstance(item.get(key), bool)
            for item in image_observations
            for key in ("first_pass_sequence", "second_pass_sequence")
        )
        if (
            len(valid_first_times) == len(image_observations)
            and len(valid_second_times) == len(image_observations)
            and sequence_values_valid
        ):
            if min(valid_second_times) <= max(valid_first_times):
                errors.append("必须先完成全部图片的正序初检，再开始逆序复核")
            first_time_order = [
                int(item.get("first_pass_sequence"))
                for item in sorted(image_observations, key=lambda record: parse_datetime(record.get("inspected_at")))
            ]
            if first_time_order != expected_sequences:
                errors.append("图片正序初检时间必须按 first_pass_sequence=1..N 真实递进")
            second_time_order = [
                int(item.get("second_pass_sequence"))
                for item in sorted(image_observations, key=lambda record: parse_datetime(record.get("second_pass_at")))
            ]
            if second_time_order != expected_sequences:
                errors.append("图片逆序复核时间必须按 second_pass_sequence=1..N 真实递进；不得事后批量回填序号与时间")
            ordered_first_times = [
                parse_datetime(item.get("inspected_at"))
                for item in sorted(image_observations, key=lambda record: int(record.get("first_pass_sequence")))
            ]
            ordered_second_times = [
                parse_datetime(item.get("second_pass_at"))
                for item in sorted(image_observations, key=lambda record: int(record.get("second_pass_sequence")))
            ]
            if suspicious_fixed_cadence([item for item in ordered_first_times if item is not None]):
                errors.append("图片正序初检时间呈固定间隔批量生成，不能作为真实逐张视觉检查记录")
            if suspicious_fixed_cadence([item for item in ordered_second_times if item is not None]):
                errors.append("图片逆序复核时间呈固定间隔批量生成，不能作为真实逐张视觉复核记录")
            if suspicious_repeating_cadence([item for item in ordered_first_times if item is not None]):
                errors.append("图片正序初检时间呈重复循环节奏，不能作为真实逐张视觉检查记录")
            if suspicious_repeating_cadence([item for item in ordered_second_times if item is not None]):
                errors.append("图片逆序复核时间呈重复循环节奏，不能作为真实逐张视觉复核记录")
            if suspicious_bounded_audit_cadence([item for item in ordered_first_times if item is not None]):
                errors.append("图片正序初检时间呈受限整数区间内持续交替的机械节奏，不能作为真实逐张视觉检查记录")
            if suspicious_bounded_audit_cadence([item for item in ordered_second_times if item is not None]):
                errors.append("图片逆序复核时间呈受限整数区间内持续交替的机械节奏，不能作为真实逐张视觉复核记录")
        all_image_times = [item for item in first_times + second_times if item is not None]
        if any(timestamp_after_file(item, paths["source_observations"]) for item in all_image_times):
            errors.append("图片核对时间晚于 source_observation.jsonl 实际写入时间，存在未来时间或事后批量回填")

    claims_by_id = {item.get("claim_id"): item for item in source_claims}
    claims_by_observation_id: dict[str, list[dict[str, Any]]] = {}
    for claim in source_claims:
        claim_id = str(claim.get("claim_id", ""))
        source_file_id = str(claim.get("source_file_id", ""))
        observation_id = str(claim.get("observation_id", ""))
        indexed = source_files_by_id.get(source_file_id)
        observation = observations_by_id.get(observation_id)
        claims_by_observation_id.setdefault(observation_id, []).append(claim)
        if indexed is None:
            official_url_claim = (
                not source_file_id
                and observation is not None
                and observation.get("inspection_method") == "official_url"
            )
            if not official_url_claim:
                errors.append(f"{claim_id} 引用了不存在的 source_file_id: {source_file_id}")
        elif is_archive_source(indexed):
            errors.append(f"{claim_id} 来自未解压的压缩包或归档文件；不得摘录原文主张")
        if observation is None:
            errors.append(f"{claim_id} 引用了不存在的 observation_id: {observation_id}")
        elif observation.get("source_file_id") != source_file_id:
            errors.append(f"{claim_id} 的 observation_id 与 source_file_id 不一致")
        claim_type = claim.get("claim_type")
        if claim_type not in CLAIM_TYPES:
            errors.append(f"{claim_id} 的 claim_type 不在允许范围")
        if not str(claim.get("label", "")).strip():
            errors.append(f"{claim_id} 的 label 为空")
        verbatim_text = str(claim.get("verbatim_text", "")).strip()
        if not verbatim_text:
            errors.append(f"{claim_id} 的 verbatim_text 为空；原文主张不得写成摘要")
        elif NON_VERBATIM_SUMMARY_RE.fullmatch(verbatim_text):
            errors.append(
                f"{claim_id} 的 verbatim_text 使用了“公开展示/通用文本”等摘要占位；"
                "原文主张必须逐字抄录可见文字，不能由分析者概括"
            )
        if WARNING_TEXT_RE.search(verbatim_text):
            if claim_type != "warning":
                errors.append(f"{claim_id} 含禁止食用、请勿食用或遵医嘱等警示语义，claim_type 必须是 warning")
            if claim.get("critical") is not True:
                errors.append(f"{claim_id} 含警示语义，critical 必须为 true")
            if observation is not None and "warning" not in (observation.get("content_flags") or []):
                errors.append(f"{claim_id} 含警示语义，其观察记录必须保留 warning 内容标记")
        if not str(claim.get("visual_locator", "")).strip():
            errors.append(f"{claim_id} 的 visual_locator 为空")
        if not isinstance(claim.get("critical"), bool):
            errors.append(f"{claim_id} 的 critical 必须是布尔值")
        if claim_type in CRITICAL_CLAIM_TYPES and claim.get("critical") is not True:
            errors.append(f"{claim_id} 属于关键字段，critical 必须为 true")
        if claim.get("claim_status") != "match":
            errors.append(f"{claim_id} 的原文复核必须标记 claim_status=match")
        normalized_value = str(claim.get("normalized_value", "")).strip()
        if normalized_value and normalized_value not in verbatim_text:
            errors.append(f"{claim_id} 的 normalized_value 必须能在 verbatim_text 中原样找到")
        claimed_at = parse_datetime(claim.get("claimed_at"))
        rechecked_at = parse_datetime(claim.get("rechecked_at"))
        if claimed_at is None or rechecked_at is None:
            errors.append(f"{claim_id} 的原文摘录与复核时间必须是带时区的完整 ISO 时间")
        elif rechecked_at <= claimed_at:
            errors.append(f"{claim_id} 的 rechecked_at 必须晚于 claimed_at")
        if observation and claimed_at is not None:
            prior_at = parse_datetime(
                observation.get("second_pass_at")
                if indexed and str(indexed.get("media_type", "")).startswith("image/")
                else observation.get("inspected_at")
            )
            if prior_at is not None and claimed_at <= prior_at:
                errors.append(f"{claim_id} 必须在逐文件观察完成后重新打开来源并摘录原文")
        if indexed and str(indexed.get("media_type", "")).startswith("image/"):
            if exact_evidence_values(record_text(claim)):
                errors.append(f"{claim_id} 来自页面图片，不得在原文主张账本抄录报告编号、日期或检测方法等精确小字")

    malformed_spec_claim_ids: set[str] = set()
    for claim in source_claims:
        if claim.get("claim_type") not in {"sku", "packaging"}:
            continue
        claim_id = str(claim.get("claim_id", ""))
        if MALFORMED_OCR_RE.search(str(claim.get("verbatim_text", ""))):
            malformed_spec_claim_ids.add(claim_id)
            errors.append(
                f"{claim_id} 的 SKU/包装原文含 oneBag 或斜杠拼接等疑似 OCR 残片；"
                "重复核对不能替代清晰可读性，必须回看原图并降为待确认"
            )

    count_entries: list[tuple[str, int, int, str]] = []
    for claim in source_claims:
        claim_id = str(claim.get("claim_id", ""))
        if claim.get("critical") is not True:
            continue
        count_entries.extend((claim_id, low, high, phrase) for low, high, phrase in package_count_ranges(claim))
    conflicted_claim_ids: set[str] = set()
    conflicted_spec_phrases: set[str] = set()
    count_conflicts: list[str] = []
    count_conflict_keys: set[tuple[str, str]] = set()
    for index, (left_id, left_low, left_high, left_phrase) in enumerate(count_entries):
        for right_id, right_low, right_high, right_phrase in count_entries[index + 1 :]:
            if left_id == right_id or not (left_high < right_low or right_high < left_low):
                continue
            conflicted_claim_ids.update({left_id, right_id})
            conflicted_spec_phrases.update({left_phrase, right_phrase})
            pair_key = tuple(sorted((normalized_spec_phrase(left_phrase), normalized_spec_phrase(right_phrase))))
            if pair_key not in count_conflict_keys:
                count_conflict_keys.add(pair_key)
                count_conflicts.append(f"{left_id}={left_phrase} vs {right_id}={right_phrase}")

    declared_conflict_surfaces: list[tuple[str, str]] = [
        ("product_manifest.sku_basis", str(manifest.get("sku_basis", ""))),
        *[
            (f"product_manifest.limitations[{index}]", str(value))
            for index, value in enumerate(manifest.get("limitations") or [])
        ],
        *[
            (f"{fact.get('fact_id')}.boundary", str(fact.get("boundary", "")))
            for fact in facts
        ],
        *[
            (f"{gap.get('gap_id')}.narrative", record_text(gap))
            for gap in gaps
        ],
    ]
    declared_conflict_by_phrase: dict[str, tuple[str, int, int, str]] = {}
    for location, text in declared_conflict_surfaces:
        if not SKU_CONFLICT_RE.search(text):
            continue
        for low, high, phrase in package_count_ranges_from_text(text):
            declared_conflict_by_phrase.setdefault(
                normalized_spec_phrase(phrase),
                (location, low, high, phrase),
            )
    declared_conflict_entries = list(declared_conflict_by_phrase.values())
    for index, (left_location, left_low, left_high, left_phrase) in enumerate(declared_conflict_entries):
        for right_location, right_low, right_high, right_phrase in declared_conflict_entries[index + 1 :]:
            if not (left_high < right_low or right_high < left_low):
                continue
            conflicted_spec_phrases.update({left_phrase, right_phrase})
            pair_key = tuple(sorted((normalized_spec_phrase(left_phrase), normalized_spec_phrase(right_phrase))))
            if pair_key not in count_conflict_keys:
                count_conflict_keys.add(pair_key)
                count_conflicts.append(
                    f"{left_location}={left_phrase} vs {right_location}={right_phrase}"
                )

    claimed_count_phrases = {
        normalized_spec_phrase(phrase)
        for _claim_id, _low, _high, phrase in count_entries
    }
    undeclared_claim_phrases = sorted(
        {
            phrase
            for _location, _low, _high, phrase in declared_conflict_entries
            if normalized_spec_phrase(phrase) not in claimed_count_phrases
        }
    )
    if undeclared_claim_phrases:
        errors.append(
            "资料边界已声明包数冲突，但以下冲突规格没有完整进入 source_claim_ledger.jsonl："
            + "、".join(undeclared_claim_phrases)
            + "；不得只在事实边界或缺口中补写来源原文"
        )
    claimed_gram_values = {
        value
        for claim in source_claims
        for value in gram_values_from_text(claim.get("verbatim_text", ""))
    }
    undeclared_conflict_grams = sorted(
        {
            value
            for _location, text in declared_conflict_surfaces
            if SKU_CONFLICT_RE.search(text)
            for value in gram_values_from_text(text)
            if value not in claimed_gram_values
        }
    )
    if undeclared_conflict_grams:
        errors.append(
            "资料边界已声明克重冲突，但以下冲突规格没有完整进入 source_claim_ledger.jsonl："
            + "、".join(f"{value:g}g" for value in undeclared_conflict_grams)
            + "；观察摘要、事实边界或缺口不能替代可定位、经复核的原文主张"
        )
    if count_conflicts:
        errors.append(
            "SKU/包装原文存在互不相容的小包数量："
            + "；".join(count_conflicts)
            + "；四遍读取结果一致也不能把冲突规格标为已确认"
        )

    total_entries = [
        (str(claim.get("claim_id", "")), value)
        for claim in source_claims
        if claim.get("critical") is True
        for value in claim_total_weights(claim)
    ]
    per_unit_entries = [
        (str(claim.get("claim_id", "")), value)
        for claim in source_claims
        if claim.get("critical") is True
        for value in claim_per_unit_weights(claim)
    ]
    exact_count_entries = [(claim_id, low, phrase) for claim_id, low, high, phrase in count_entries if low == high]
    arithmetic_conflicts: list[str] = []
    for total_id, total in total_entries:
        for unit_id, per_unit in per_unit_entries:
            for count_id, count, count_phrase in exact_count_entries:
                if abs(total - per_unit * count) <= 0.05:
                    continue
                # The arithmetic only disproves the exact per-unit/count combination.
                # A consistently displayed total net weight may remain confirmed.
                conflicted_claim_ids.update({unit_id, count_id})
                conflicted_spec_phrases.add(count_phrase)
                arithmetic_conflicts.append(
                    f"{total:g}g ≠ {per_unit:g}g×{count}（{total_id}/{unit_id}/{count_id}）"
                )
    if arithmetic_conflicts:
        errors.append(
            "SKU/包装规格存在总净含量、单包克重与包数的算术冲突："
            + "；".join(arithmetic_conflicts)
            + "；必须以清晰实物或 SKU 选择器复核后再进入商品价值"
        )

    blocked_spec_claim_ids = conflicted_claim_ids | malformed_spec_claim_ids
    if conflicted_claim_ids and manifest.get("sku_status") == "confirmed":
        errors.append("存在互相冲突的 SKU/包装原文时，sku_status 不得为 confirmed")
    manifest_sku_text = str(manifest.get("sku", ""))
    for phrase in conflicted_spec_phrases:
        if contains_spec_phrase(manifest_sku_text, phrase):
            errors.append(f"当前 SKU 名称继续使用冲突规格“{phrase}”；应只保留已确认的标准成交单元并注明待确认")
    if MALFORMED_OCR_RE.search(manifest_sku_text):
        errors.append("当前 SKU 名称含疑似 OCR 残片，不得作为正式商品身份")

    for observation in source_observations:
        observation_id = str(observation.get("observation_id", ""))
        source_file_id = str(observation.get("source_file_id", ""))
        claims = claims_by_observation_id.get(observation_id, [])
        text_density = observation.get("text_density")
        content_flags = observation.get("content_flags") if isinstance(observation.get("content_flags"), list) else []
        if observation.get("inspection_status") == "inspected" and text_density in {"medium", "high"} and not claims:
            errors.append(f"{observation_id} 是中高文字密度来源，必须完成原文主张摘录与复核")
        if text_density == "none" and claims:
            errors.append(f"{observation_id} 标记无文字，但 source_claim_ledger 中存在原文主张")
        claim_type_counts: dict[str, int] = {}
        for claim in claims:
            claim_type = str(claim.get("claim_type", ""))
            claim_type_counts[claim_type] = claim_type_counts.get(claim_type, 0) + 1
        for flag in content_flags:
            requirement = FLAG_CLAIM_REQUIREMENTS.get(str(flag))
            if requirement is None:
                continue
            claim_type, minimum = requirement
            if claim_type_counts.get(claim_type, 0) < minimum:
                errors.append(
                    f"{observation_id} 标记 {flag}，至少需要 {minimum} 条 {claim_type} 原文主张"
                )

    claim_check_times = [parse_datetime(item.get("claimed_at")) for item in source_claims]
    claim_recheck_times = [parse_datetime(item.get("rechecked_at")) for item in source_claims]
    valid_claim_check_times = [item for item in claim_check_times if item is not None]
    valid_claim_recheck_times = [item for item in claim_recheck_times if item is not None]
    if len(set(valid_claim_check_times)) != len(valid_claim_check_times):
        errors.append("每条原文主张的第三遍摘录时间必须独立记录，不得复用同一时间")
    if len(set(valid_claim_recheck_times)) != len(valid_claim_recheck_times):
        errors.append("每条原文主张的第四遍复核时间必须独立记录，不得复用同一时间")
    if suspicious_fixed_cadence(sorted(valid_claim_check_times)):
        errors.append("原文主张摘录时间呈固定间隔批量生成，不能作为真实逐条摘录记录")
    if suspicious_fixed_cadence(sorted(valid_claim_recheck_times)):
        errors.append("原文主张复核时间呈固定间隔批量生成，不能作为真实逐条复核记录")
    if suspicious_dense_cadence(valid_claim_check_times):
        errors.append("原文主张摘录时间在长序列中持续仅相隔 1–5 秒，密度不符合逐条重新打开、阅读和摘录的真实操作")
    if suspicious_dense_cadence(valid_claim_recheck_times):
        errors.append("原文主张复核时间在长序列中持续仅相隔 1–5 秒，密度不符合逐条重新打开、阅读和复核的真实操作")
    if suspicious_bounded_micro_cadence(valid_claim_check_times):
        errors.append("原文主张摘录时间在长序列中全部落入 1–7 秒的少量整数间隔，属于机械生成节奏，不能作为真实逐条阅读记录")
    if suspicious_bounded_micro_cadence(valid_claim_recheck_times):
        errors.append("原文主张复核时间在长序列中全部落入 1–7 秒的少量整数间隔，属于机械生成节奏，不能作为真实逐条复核记录")
    if suspicious_repeating_cadence(valid_claim_check_times):
        errors.append("原文主张摘录时间呈重复循环节奏，不能作为真实逐条摘录记录")
    if suspicious_repeating_cadence(valid_claim_recheck_times):
        errors.append("原文主张复核时间呈重复循环节奏，不能作为真实逐条复核记录")
    if suspicious_bounded_audit_cadence(valid_claim_check_times):
        errors.append("原文主张摘录时间呈受限整数区间内持续交替的机械节奏，不能作为真实逐条摘录记录")
    if suspicious_bounded_audit_cadence(valid_claim_recheck_times):
        errors.append("原文主张复核时间呈受限整数区间内持续交替的机械节奏，不能作为真实逐条复核记录")
    if suspicious_parallel_audit_timing(valid_claim_check_times, valid_claim_recheck_times):
        errors.append(
            "原文主张摘录与复核的时间间隔序列完全同构，且每条记录仅整体平移同一秒数；"
            "这不能作为两次独立重新打开与逐条核对的真实记录"
        )
    if (
        valid_claim_check_times
        and valid_claim_recheck_times
        and min(valid_claim_recheck_times) <= max(valid_claim_check_times)
    ):
        errors.append("必须先完成全部原文主张的第三遍摘录，再开始第四遍复核")
    if any(
        timestamp_after_file(item, paths["source_claims"])
        for item in valid_claim_check_times + valid_claim_recheck_times
    ):
        errors.append("原文主张摘录或复核时间晚于 source_claim_ledger.jsonl 实际写入时间，存在未来时间或事后批量回填")

    observation_event_times = [
        parsed
        for observation in source_observations
        for parsed in (
            parse_datetime(observation.get("inspected_at")),
            parse_datetime(observation.get("second_pass_at")),
        )
        if parsed is not None
    ]
    workflow_event_times = observation_event_times + valid_claim_check_times + valid_claim_recheck_times
    if (
        manifest_created_at is not None
        and workflow_event_times
        and min(workflow_event_times) < manifest_created_at
    ):
        errors.append(
            "逐文件核验、原文摘录或复核时间早于 product_manifest.created_at；"
            "请检查 UTC/本地时区标注，不能把 UTC 时钟直接标成 +08:00"
        )
    if (
        manifest_updated_at is not None
        and workflow_event_times
        and max(workflow_event_times) > manifest_updated_at
    ):
        errors.append("product_manifest.updated_at 必须晚于全部逐文件核验、原文摘录与复核事件")

    for source in sources:
        source_id = str(source.get("source_id", ""))
        source_file_id = str(source.get("source_file_id", "")).strip()
        observation_id = str(source.get("observation_id", "")).strip()
        locator = str(source.get("locator", "")).strip()
        if source_file_id:
            indexed = source_files_by_id.get(source_file_id)
            if indexed is None:
                errors.append(f"{source_id} 引用了不存在的 source_file_id: {source_file_id}")
            elif str(indexed.get("relative_path", "")) not in locator:
                errors.append(f"{source_id} 的 locator 必须保留 {source_file_id} 的真实 relative_path")
            if indexed is not None and is_archive_source(indexed):
                errors.append(
                    f"{source_id} 把压缩包或归档文件当成了可调用来源；"
                    "归档文件只能保留在清单并标记不可读，解压后须在全新交付中逐文件重新索引"
                )
            observation = observations_by_id.get(observation_id)
            if observation is None:
                errors.append(f"{source_id} 必须绑定该原文件的 observation_id")
            else:
                if observation.get("source_file_id") != source_file_id:
                    errors.append(f"{source_id} 的 observation_id 与 source_file_id 不一致")
                if observation.get("inspection_status") != "inspected":
                    errors.append(f"{source_id} 绑定的 {observation_id} 尚未完成逐文件核对")
                if str(source.get("title", "")).strip() != str(observation.get("title", "")).strip():
                    errors.append(f"{source_id} 的 title 必须与 {observation_id} 的逐文件核对标题完全一致")
            if indexed and str(indexed.get("media_type", "")).startswith("image/"):
                if exact_evidence_values(record_text(source)):
                    errors.append(f"{source_id} 是页面图片，不得在来源台账中抄录报告编号、日期、批次或检测方法等精确字段")
        elif not URL_RE.match(locator):
            errors.append(f"{source_id} 是本地来源时必须绑定 source_file_id；仅 URL 来源可留空")
        elif observation_id:
            observation = observations_by_id.get(observation_id)
            if observation is None or observation.get("inspection_method") != "official_url":
                errors.append(f"{source_id} 的 URL observation_id 必须绑定 official_url 核对记录")

    source_ids = {item.get("source_id") for item in sources}
    sources_by_id = {item.get("source_id"): item for item in sources}
    fact_ids = {item.get("fact_id") for item in facts}
    facts_by_id = {item.get("fact_id"): item for item in facts}
    value_ids = {item.get("value_id") for item in values}
    values_by_id = {item.get("value_id"): item for item in values}
    fabe_by_value: dict[str, list[dict[str, Any]]] = {}
    snapshot_date = parse_reference_date(manifest.get("updated_at"))
    dyn_expected_states: dict[str, str] = {}
    allowed_exact_values: set[str] = set()
    referenced_claim_ids: set[str] = set()
    blocked_spec_fact_ids: set[str] = set()

    for fact in facts:
        fact_id = str(fact.get("fact_id", ""))
        fact_type = fact.get("fact_type")
        if fact_type not in FACT_TYPES:
            errors.append(f"{fact_id} 的 fact_type 不在允许范围")
        expected_prefix = "F" if fact_type in {"F-PAGE", "F-EVIDENCE"} else fact_type
        if expected_prefix and not fact_id.startswith(f"{expected_prefix}-"):
            errors.append(f"{fact_id} 与 fact_type={fact_type} 的前缀不一致")
        source_id = fact.get("source_id")
        if source_id not in source_ids:
            if fact_type == "H" and not source_id and str(fact.get("boundary", "")).strip():
                warnings.append(f"{fact_id} 是无直接来源的分析推导，已依赖 boundary 限定")
            else:
                errors.append(f"{fact_id} 引用了不存在的 source_id: {source_id}")
        claim_ids = fact.get("claim_ids")
        source_quotes = fact.get("source_quotes")
        if not isinstance(claim_ids, list):
            errors.append(f"{fact_id} 的 claim_ids 必须是数组")
            claim_ids = []
        if not isinstance(source_quotes, list):
            errors.append(f"{fact_id} 的 source_quotes 必须是数组")
            source_quotes = []
        direct_source_required = fact_type != "H"
        if direct_source_required and not claim_ids:
            errors.append(f"{fact_id} 是直接来源事实，必须引用至少一条原文主张")
        if direct_source_required and not source_quotes:
            errors.append(f"{fact_id} 是直接来源事实，必须保留对应原文摘录")
        source = sources_by_id.get(source_id, {})
        selected_claims: list[dict[str, Any]] = []
        for claim_id in claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is None:
                errors.append(f"{fact_id} 引用了不存在的 claim_id: {claim_id}")
                continue
            selected_claims.append(claim)
            referenced_claim_ids.add(str(claim_id))
            if source:
                if claim.get("source_file_id") != source.get("source_file_id"):
                    errors.append(f"{fact_id} 的 {claim_id} 与 source_id 不是同一原文件")
                if claim.get("observation_id") != source.get("observation_id"):
                    errors.append(f"{fact_id} 的 {claim_id} 与 source_id 不是同一观察记录")
        selected_verbatim = {str(item.get("verbatim_text", "")).strip() for item in selected_claims}
        statement = str(fact.get("statement", ""))
        selected_claim_id_set = set(str(item) for item in claim_ids)
        blocked_claims_used = selected_claim_id_set.intersection(malformed_spec_claim_ids)
        if any(contains_spec_phrase(statement, phrase) for phrase in conflicted_spec_phrases):
            blocked_claims_used.update(selected_claim_id_set.intersection(conflicted_claim_ids))
        if blocked_claims_used:
            blocked_spec_fact_ids.add(fact_id)
            if str(fact.get("status", "")).lower() in {"confirmed", "active", "current", "ready"}:
                errors.append(
                    f"{fact_id} 引用了冲突或不可清晰读取的 SKU/包装原文 "
                    f"{', '.join(sorted(blocked_claims_used))}，不得标记为已确认"
                )
        quote_values = {str(item).strip() for item in source_quotes if str(item).strip()}
        missing_quotes = selected_verbatim.difference(quote_values)
        if missing_quotes:
            errors.append(f"{fact_id} 的 source_quotes 必须逐条原样复制所引用 claim 的 verbatim_text")
        unbound_quotes = quote_values.difference(selected_verbatim)
        if unbound_quotes:
            errors.append(f"{fact_id} 的 source_quotes 含未绑定 claim_id 的文字")
        claim_text = " ".join(selected_verbatim)
        if fact_type in {"F-PAGE", "F-EVIDENCE"}:
            for absence_phrase in sorted(set(ABSENCE_ASSERTION_RE.findall(statement))):
                if absence_phrase not in claim_text:
                    errors.append(
                        f"{fact_id} 将“{absence_phrase}”写成直接来源事实，但所引原文没有这项缺席声明；"
                        "页面未展示或未取得的内容只能进入 boundary/gap，不能冒充页面原文"
                    )
        missing_numbers = sorted(set(NUMBER_TOKEN_RE.findall(statement)).difference(NUMBER_TOKEN_RE.findall(claim_text)))
        if missing_numbers:
            errors.append(f"{fact_id} 的数字未在所引原文主张中出现: {', '.join(missing_numbers)}")
        for term in DIRECT_QUOTE_TERMS_RE.findall(statement):
            if term not in claim_text:
                errors.append(f"{fact_id} 的高风险词“{term}”未在所引原文主张中原样出现")
        for term in sorted(set(ATOMIC_CLAIM_TERMS_RE.findall(statement))):
            compact_term = re.sub(r"\s+", "", term)
            compact_claim_text = re.sub(r"\s+", "", claim_text)
            if compact_term not in compact_claim_text:
                errors.append(
                    f"{fact_id} 的关键字段或警示“{compact_term}”未在所引原文主张中出现；"
                    "复合事实必须逐字段绑定 claim_id 和 source_quotes"
                )
        for term in SENSORY_LITERAL_RE.findall(statement):
            if term not in claim_text:
                errors.append(f"{fact_id} 的口感或感官词“{term}”未在所引原文主张中原样出现；回甜、回甘等近义词不得互换")
        if fact_type == "F-EVIDENCE":
            evidence_missing = missing_fields(fact, EVIDENCE_FACT_FIELDS)
            if evidence_missing:
                errors.append(f"{fact_id} 是证据事实，缺少字段: {', '.join(evidence_missing)}")
            confidence = fact.get("evidence_detail_confidence")
            exact_fields_verified = fact.get("exact_fields_verified")
            verification_locator = str(fact.get("verification_locator", "")).strip()
            if confidence not in {"high", "medium", "low"}:
                errors.append(f"{fact_id} 的 evidence_detail_confidence 必须是 high/medium/low")
            if not isinstance(exact_fields_verified, bool):
                errors.append(f"{fact_id} 的 exact_fields_verified 必须是布尔值")
            source = sources_by_id.get(source_id, {})
            source_file = source_files_by_id.get(source.get("source_file_id"), {})
            observation = observations_by_id.get(source.get("observation_id"), {})
            media_type = str(source_file.get("media_type", ""))
            inspection_method = observation.get("inspection_method")
            page_image = media_type.startswith("image/")
            if page_image:
                if exact_fields_verified is True:
                    errors.append(f"{fact_id} 来自页面图片，不得设置 exact_fields_verified=true")
                if confidence == "high":
                    errors.append(f"{fact_id} 来自页面图片，证据细节可信度最高只能是 medium")
            if exact_fields_verified is True:
                source_is_official_url = URL_RE.match(str(source.get("locator", ""))) is not None
                if inspection_method != "document_text" and not source_is_official_url:
                    errors.append(f"{fact_id} 的精确字段只有报告原件/PDF或官方验证页可以核验")
                if not verification_locator:
                    errors.append(f"{fact_id} 设置 exact_fields_verified=true 时必须填写 verification_locator")
                elif source_is_official_url and not URL_RE.match(verification_locator):
                    errors.append(f"{fact_id} 来自官方验证页时 verification_locator 必须是完整 URL")
            exact_values = exact_evidence_values(record_text(fact))
            if exact_values:
                if page_image:
                    errors.append(f"{fact_id} 来自页面图片，不得在任何字段抄录报告编号、日期、批次或检测方法等精确小字")
                elif not (confidence == "high" and exact_fields_verified is True and verification_locator):
                    errors.append(f"{fact_id} 含精确证据值，必须有原件或官方验证页定位")
                else:
                    allowed_exact_values.update(exact_values)
        elif exact_evidence_values(record_text(fact)):
            errors.append(f"{fact_id} 含报告编号、报告日期或检测方法等精确证据值，必须改为原件级 F-EVIDENCE 并完成核验")
        if QUANTIFIED_STEAM_DRY_RE.search(str(fact.get("statement", ""))):
            source = sources_by_id.get(source_id, {})
            source_text = " ".join(
                str(source.get(key, "")) for key in ("title", "locator", "notes")
            )
            if not QUANTIFIED_STEAM_DRY_RE.search(source_text):
                errors.append(f"{fact_id} 把反复蒸晒扩大成具体次数；来源标题、定位或摘录未支持该次数")
        if fact_type == "DYN" and not str(fact.get("time_scope", "")).strip():
            errors.append(f"{fact_id} 是动态交易事实，必须填写 time_scope")
        if fact_type == "DYN":
            dyn_claim_text = " ".join(str(item.get("verbatim_text", "")) for item in selected_claims)
            time_scope_text = str(fact.get("time_scope", ""))
            scope_years = {item[0] for item in DATE_RE.findall(time_scope_text)}
            claim_years = {item[0] for item in DATE_RE.findall(dyn_claim_text)}
            inferred_years = scope_years.difference(claim_years)
            if inferred_years:
                captured = parse_datetime(source.get("captured_at"))
                if captured is None or str(captured.year) not in inferred_years:
                    errors.append(f"{fact_id} 补全的年份与来源 captured_at 不一致，不能据此判断活动状态")
                if not INFERRED_DYNAMIC_YEAR_RE.search(str(fact.get("boundary", ""))):
                    errors.append(f"{fact_id} 的年份未出现在所引活动原文中；如按采集时间推定，必须在 boundary 明确披露推定依据")
            if TIME_OF_DAY_RE.search(dyn_claim_text) and not TZ_DATETIME_RE.search(time_scope_text):
                errors.append(f"{fact_id} 的活动原文包含具体时刻，time_scope 必须保留完整日期、时刻和时区")
            expected = classify_time_scope(fact.get("time_scope"), snapshot_date)
            if expected is None:
                status = str(fact.get("status", "")).strip().lower()
                if status in {"active", "confirmed", "current", "upcoming", "expired"}:
                    errors.append(f"{fact_id} 的 time_scope 缺少可核验的完整年份，status 不得标记为 {status}")
                if not re.search(r"年份.{0,8}(?:未显示|缺失|待确认)|时区.{0,8}(?:未显示|缺失|待确认)", str(fact.get("boundary", ""))):
                    errors.append(f"{fact_id} 的 time_scope 无法自动核验时，boundary 必须明确年份或时区缺口")
            else:
                dyn_expected_states[fact_id] = expected
                status = str(fact.get("status", "")).strip().lower()
                if expected == "active" and status in {"expired", "stale", "inactive"}:
                    errors.append(f"{fact_id} 在交付更新时间仍处活动期，但 status={status}")
                if expected == "expired" and status in {"active", "confirmed", "current"}:
                    errors.append(f"{fact_id} 在交付更新时间已经结束，但 status={status}")
                if expected == "upcoming" and status in {"active", "confirmed", "current", "expired", "stale"}:
                    errors.append(f"{fact_id} 在交付更新时间尚未开始，但 status={status}")
                if expected == "active" and EXPIRY_WORDS_RE.search(str(fact.get("boundary", ""))):
                    errors.append(f"{fact_id} 在交付更新时间仍处活动期，但 boundary 写成已过期")
        if not str(fact.get("statement", "")).strip():
            errors.append(f"{fact_id} 的 statement 为空")
        if not str(fact.get("boundary", "")).strip():
            errors.append(f"{fact_id} 的 boundary 为空")

    for claim in source_claims:
        claim_id = str(claim.get("claim_id", ""))
        if claim.get("critical") is True and claim_id not in referenced_claim_ids:
            errors.append(f"{claim_id} 是关键原文字段，但没有进入任何事实记录")

    for anchor in anchors:
        anchor_id = str(anchor.get("anchor_id", ""))
        if anchor.get("anchor_type") not in {"main", "supporting"}:
            errors.append(f"{anchor_id} 的 anchor_type 必须是 main 或 supporting")
        references = anchor.get("fact_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{anchor_id} 必须引用至少一个 fact_id")
        else:
            for fact_id in references:
                if fact_id not in fact_ids:
                    errors.append(f"{anchor_id} 引用了不存在的 fact_id: {fact_id}")
            blocked = set(str(item) for item in references).intersection(blocked_spec_fact_ids)
            if blocked:
                errors.append(
                    f"{anchor_id} 使用了冲突或不可清晰读取的 SKU/包装事实 "
                    f"{', '.join(sorted(blocked))}；识别锚只能保留已确认规格"
                )

    allowed_derivation_statuses = {"page_supported", "reasoned", "to_validate"}
    fabe_content_ids: dict[str, str] = {}
    for item in fabe:
        fabe_id = str(item.get("fabe_id", ""))
        value_id = str(item.get("value_id", ""))
        if value_id not in value_ids:
            errors.append(f"{fabe_id} 引用了不存在的 value_id: {value_id}")
        else:
            fabe_by_value.setdefault(value_id, []).append(item)
        fabe_signature = normalized_content_signature(
            item,
            (
                "value_id",
                "feature",
                "feature_fact_ids",
                "advantage",
                "benefit",
                "evidence",
                "evidence_fact_ids",
                "reference_frame",
                "reference_fact_ids",
                "user_language",
                "derivation_status",
                "boundary",
            ),
        )
        if fabe_signature in fabe_content_ids:
            errors.append(
                f"{fabe_id} 与 {fabe_content_ids[fabe_signature]} 的 FABE 内容完全重复；"
                "相同证据链必须去重，不能用不同 ID 重复计数或重复展示"
            )
        else:
            fabe_content_ids[fabe_signature] = fabe_id
        for key in ("feature_fact_ids", "evidence_fact_ids", "reference_fact_ids"):
            references = item.get(key)
            if not isinstance(references, list) or not references:
                errors.append(f"{fabe_id} 的 {key} 必须引用至少一个 fact_id")
            else:
                for fact_id in references:
                    if fact_id not in fact_ids:
                        errors.append(f"{fabe_id} 的 {key} 引用了不存在的 fact_id: {fact_id}")
        for key in ("feature", "advantage", "benefit", "evidence", "reference_frame", "user_language", "boundary"):
            if not str(item.get(key, "")).strip():
                errors.append(f"{fabe_id} 的 {key} 为空")
        advantage_text = str(item.get("advantage", "")).strip()
        if GENERIC_ADVANTAGE_RE.fullmatch(advantage_text):
            errors.append(
                f"{fabe_id}.advantage 使用了占位式 Advantage；必须写明具体任务差异，"
                "或明确写相对优势暂不成立"
            )
        if UNESTABLISHED_ADVANTAGE_RE.search(advantage_text) and item.get("derivation_status") != "to_validate":
            errors.append(f"{fabe_id}.advantage 明确写暂不成立或待验证时，derivation_status 必须是 to_validate")
        if UNESTABLISHED_ADVANTAGE_RE.search(advantage_text):
            other_comparison_text = " ".join(
                str(item.get(key, ""))
                for key in ("benefit", "reference_frame", "user_language", "boundary")
            )
            if COMPARISON_LANGUAGE_RE.search(other_comparison_text):
                errors.append(
                    f"{fabe_id}.advantage 已声明 A 层暂不成立，Benefit、参照系和用户语言不得继续使用产品替代对象或比较结论"
                )
        if item.get("derivation_status") not in allowed_derivation_statuses:
            errors.append(f"{fabe_id} 的 derivation_status 必须是 page_supported/reasoned/to_validate")
        if item.get("derivation_status") == "page_supported":
            feature_ids = set(item.get("feature_fact_ids") or [])
            evidence_ids = set(item.get("evidence_fact_ids") or [])
            if not feature_ids.intersection(evidence_ids):
                errors.append(f"{fabe_id} 标记页面直接支持时，Evidence 必须至少包含一条 Feature 的直接事实")
        referenced_fact_ids = (
            set(item.get("feature_fact_ids") or [])
            | set(item.get("evidence_fact_ids") or [])
            | set(item.get("reference_fact_ids") or [])
        )
        blocked = referenced_fact_ids.intersection(blocked_spec_fact_ids)
        if blocked:
            errors.append(
                f"{fabe_id} 使用了冲突或不可清晰读取的 SKU/包装事实 "
                f"{', '.join(sorted(blocked))}；不得进入 FABE 推导"
            )
        referenced_facts = [facts_by_id[fact_id] for fact_id in referenced_fact_ids if fact_id in facts_by_id]
        reference_fact_ids = set(item.get("reference_fact_ids") or [])
        reference_facts = [facts_by_id[fact_id] for fact_id in reference_fact_ids if fact_id in facts_by_id]
        field_fact_keys = {
            "feature": "feature_fact_ids",
            "evidence": "evidence_fact_ids",
            "reference_frame": "reference_fact_ids",
        }
        for field_name, fact_key in field_fact_keys.items():
            field_facts = [
                facts_by_id[fact_id]
                for fact_id in (item.get(fact_key) or [])
                if fact_id in facts_by_id
            ]
            grounding_issues = field_grounding_issues(
                item.get(field_name, ""),
                fact_support_text(field_facts, claims_by_id),
            )
            if grounding_issues:
                errors.append(
                    f"{fabe_id}.{field_name} 含未由 {fact_key} 支持的字段元素: "
                    f"{'；'.join(grounding_issues)}"
                )
        referenced_claims = [
            claims_by_id[claim_id]
            for fact in referenced_facts
            for claim_id in (fact.get("claim_ids") or [])
            if claim_id in claims_by_id
        ]
        referenced_claim_text = " ".join(str(claim.get("verbatim_text", "")) for claim in referenced_claims)
        referenced_user_text = " ".join(
            " ".join(
                [str(fact.get("statement", ""))]
                + [str(quote) for quote in (fact.get("source_quotes") or [])]
            )
            for fact in referenced_facts
            if fact.get("fact_type") == "U"
        )
        referenced_source_types = {
            str(sources_by_id.get(fact.get("source_id"), {}).get("source_type", ""))
            for fact in referenced_facts
        }
        if item.get("derivation_status") == "page_supported":
            direct_claim_text = normalized_literal_text(referenced_claim_text)
            for key in ("advantage", "benefit"):
                field_text = str(item.get(key, "")).strip()
                if normalized_literal_text(field_text) not in direct_claim_text:
                    errors.append(
                        f"{fabe_id} 标记 page_supported，但 {key} 的完整表述未在所引页面原文中逐字出现；"
                        "应改为 reasoned 并保留事实边界，"
                        "或补充直接支持该表述的原文事实"
                    )
        if SELF_COMPARISON_REFERENCE_RE.search(str(item.get("reference_frame", ""))):
            errors.append(
                f"{fabe_id}.reference_frame 把当前商品自身写成比较对象；"
                "应改写为当前操作任务，或引用真实页面对比、用户证据、竞品或行业对照"
            )
        if USER_HABIT_REFERENCE_RE.search(str(item.get("reference_frame", ""))) and not any(
            fact.get("fact_type") == "U" for fact in reference_facts
        ):
            errors.append(
                f"{fabe_id} 把用户旧习惯写成参照系，但未引用 U 用户证据；"
                "应改为页面内具体对比、内生任务假设，或补充用户原声"
            )
        analysis_text = " ".join(
            str(item.get(key, ""))
            for key in ("feature", "advantage", "benefit", "evidence", "reference_frame", "user_language", "boundary")
        )
        source_bounded_text = " ".join(
            str(item.get(key, ""))
            for key in ("feature", "advantage", "benefit", "reference_frame", "user_language")
        )
        for term in STRICT_FABE_SOURCE_TERMS:
            if term in source_bounded_text and term not in referenced_claim_text and term not in referenced_user_text:
                errors.append(
                    f"{fabe_id} 使用了限定词“{term}”，但本条 FABE 所引原文或用户资料未直接出现该词；"
                    "应删除扩写、补充对应事实，或降为明确待验证问题"
                )
        comparison_text = without_comparison_denials(analysis_text)
        causal_claim = CAUSAL_LINK_RE.search(
            " ".join(str(item.get(key, "")) for key in ("feature", "advantage", "benefit"))
        )
        if (
            causal_claim
            and causal_claim.group(0) not in referenced_claim_text
            and item.get("derivation_status") != "to_validate"
        ):
            errors.append(
                f"{fabe_id}.feature 新增了“{causal_claim.group(0)}”因果关系，但所引页面原文未直接建立该因果；"
                "应把工艺事实与耐泡、口感等结果分别保留为页面主张，或将因果降为待验证推导"
            )
        if MISLEADING_COMPARATOR_RE.search(comparison_text):
            errors.append(
                f"{fabe_id} 使用了“相对普通/仅达到/添加多种/未明示”等替代性比较；必须改写为页面明确展示的具体对比，或补充真实对照来源"
            )
        elif UNSUPPORTED_PRODUCT_COMPARATOR_RE.search(comparison_text) or UNSUPPORTED_PRODUCT_TARGET_RE.search(comparison_text):
            has_comparison_claim = any(claim.get("claim_type") == "comparison" for claim in referenced_claims)
            has_comparator_source = bool(referenced_source_types.intersection(COMPETITOR_SOURCE_TYPES))
            if not has_comparison_claim and not has_comparator_source:
                errors.append(f"{fabe_id} 使用了无来源的产品替代对象；必须改写为内生任务假设，或补充页面对比、竞品页或行业对照")
        elif MARKET_COMPARATOR_RE.search(comparison_text):
            has_comparison_claim = any(claim.get("claim_type") == "comparison" for claim in referenced_claims)
            has_comparator_source = bool(referenced_source_types.intersection(COMPETITOR_SOURCE_TYPES))
            if not has_comparison_claim and not has_comparator_source:
                errors.append(f"{fabe_id} 使用市场或产品比较语言，但未引用页面对比原文、竞品页或行业对照")
        restriction = UNSUPPORTED_RESTRICTION_RE.search(analysis_text)
        if restriction and restriction.group(0) not in referenced_claim_text:
            errors.append(f"{fabe_id} 将使用方式扩大为“{restriction.group(0)}”，但所引原文未作该限制")
        if SULFUR_RESIDUE_RISK_RE.search(analysis_text):
            errors.append(f"{fabe_id} 不得把“未经二氧化硫熏制工艺”扩大为没有残留风险或零残留")
        if SULFUR_SAFETY_BENEFIT_RE.search(analysis_text) and not SULFUR_SAFETY_ASSOCIATION_RE.search(referenced_claim_text):
            errors.append(f"{fabe_id} 把无硫熏主张扩写为安全、健康、危害或风险利益，但本 FABE 所引原文没有直接依据")
        stacking = PROMOTION_STACKING_RE.search(analysis_text)
        if stacking and not PROMOTION_STACKING_RE.search(referenced_claim_text):
            errors.append(f"{fabe_id} 声称优惠或权益可以叠加，但所引原文没有明确叠加规则")

    allowed_axis = {"high", "medium", "low", "unknown"}
    value_context_units: dict[str, set[str]] = {}
    value_cannot_prove: dict[str, list[str]] = {}
    for value in values:
        value_id = str(value.get("value_id", ""))
        if value.get("layer") not in VALUE_LAYERS:
            errors.append(f"{value_id} 的 layer 不在允许范围")
        if not isinstance(value.get("p0_candidate"), bool):
            errors.append(f"{value_id} 的 p0_candidate 必须是布尔值")
        if value.get("p0_status") not in P0_STATUSES | {"", "not_applicable"}:
            errors.append(f"{value_id} 的 p0_status 不在允许范围")
        references = value.get("supporting_fact_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{value_id} 必须引用至少一个事实或推导")
        else:
            for fact_id in references:
                if fact_id not in fact_ids:
                    errors.append(f"{value_id} 引用了不存在的 fact_id: {fact_id}")
            blocked = set(str(item) for item in references).intersection(blocked_spec_fact_ids)
            if blocked:
                errors.append(
                    f"{value_id} 使用了冲突或不可清晰读取的 SKU/包装事实 "
                    f"{', '.join(sorted(blocked))}；不得进入价值分层或 P0 候选"
                )
        scope_text = f"{value.get('sku_scope', '')} {value.get('scope', '')}"
        if ALL_SKU_RE.search(scope_text):
            unsupported = [
                str(fact_id)
                for fact_id in (references or [])
                if not ALL_SKU_RE.search(str(facts_by_id.get(fact_id, {}).get("sku_scope", "")))
            ]
            if unsupported:
                errors.append(
                    f"{value_id} 声称适用于全 SKU，但支撑事实未逐条覆盖全 SKU: {', '.join(unsupported)}"
                )
        for key in ("strategic_potential", "execution_maturity"):
            if value.get(key) not in allowed_axis:
                errors.append(f"{value_id} 的 {key} 必须是 high/medium/low/unknown")
        if value.get("downstream_readiness") not in READINESS_LEVELS:
            errors.append(f"{value_id} 的 downstream_readiness 不在允许范围")
        if manifest.get("sku_status") in {"partial", "unverified"} and value.get("downstream_readiness") == "ready":
            errors.append(f"{value_id} 在 SKU 未完全确认时 downstream_readiness 不得为 ready")
        if not isinstance(value.get("cannot_prove"), list):
            errors.append(f"{value_id} 的 cannot_prove 必须是数组")
        if not str(value.get("value_statement", "")).strip():
            errors.append(f"{value_id} 的 value_statement 为空")
        value_statement = str(value.get("value_statement", "")).strip()
        p0_axes = {
            name for name, pattern in P0_VALUE_AXIS_PATTERNS.items() if pattern.search(value_statement)
        }
        if value.get("layer") == "P0" and len(p0_axes) >= 4:
            errors.append(
                f"{value_id} 的核心价值同时包含多个独立收益轴，共 {len(p0_axes)} 个"
                f"（{', '.join(sorted(p0_axes))}）；P0 必须只保留一个核心用户变化，"
                "口感、成分/刺激物、准备方式、持续时长和信任证据等其余内容下沉到 P1、P2 或 FABE"
            )
        if (
            value.get("layer") == "P0"
            and len(value_statement) > 60
            and len(re.findall(r"[,，;；]", value_statement)) >= 3
            and re.search(r"并|同时|以及|加上", value_statement)
        ):
            errors.append(
                f"{value_id} 的核心价值同时串联过多商品事实、场景与使用方式；"
                "P0 必须压缩成一个不可拆的用户价值，其余内容下沉到 P1、FABE 或证据说明"
            )
        if (value.get("layer") != "deferred" or value.get("p0_candidate") is True) and not fabe_by_value.get(value_id):
            errors.append(f"{value_id} 缺少 FABE 完整推导链")
        if value.get("p0_candidate") is True and value.get("layer") == "P2":
            errors.append(
                f"{value_id} 属于 P2 信任或买前确认信息，不能直接作为 P0 候选；"
                "如确有战略潜力，应另建一条以用户任务和结果表达的 P0/P1/deferred 价值候选"
            )
        value_positive_text = " ".join(
            str(value.get(key, ""))
            for key in ("user_task", "value_statement", "user_perception_goal", "scope")
        )
        associated_fabe_text = " ".join(
            str(chain.get(key, ""))
            for chain in fabe_by_value.get(value_id, [])
            for key in (
                "feature",
                "advantage",
                "benefit",
                "evidence",
                "reference_frame",
                "user_language",
                "boundary",
            )
        )
        value_context_text = f"{value_positive_text} {associated_fabe_text}"
        value_context_units[value_id] = semantic_reference_units(value_context_text)
        value_cannot_prove[value_id] = [str(item) for item in (value.get("cannot_prove") or [])]
        value_denial_text = " ".join(str(item) for item in (value.get("cannot_prove") or []))
        value_facts = [
            facts_by_id[fact_id]
            for fact_id in (value.get("supporting_fact_ids") or [])
            if fact_id in facts_by_id
        ]
        for fact in value_facts:
            fact_units = semantic_reference_units(fact_support_text([fact], claims_by_id))
            if fact_units and not fact_units.intersection(value_context_units[value_id]):
                errors.append(
                    f"{value_id}.supporting_fact_ids 含与本价值及其 FABE 无可核对语义关联的事实 "
                    f"{fact.get('fact_id')}；应删除错挂事实或补全它实际支撑的价值表达"
                )
        value_claims = [
            claims_by_id[claim_id]
            for fact in value_facts
            for claim_id in (fact.get("claim_ids") or [])
            if claim_id in claims_by_id
        ]
        value_claim_text = " ".join(str(claim.get("verbatim_text", "")) for claim in value_claims)
        value_user_text = " ".join(
            " ".join(
                [str(fact.get("statement", ""))]
                + [str(quote) for quote in (fact.get("source_quotes") or [])]
            )
            for fact in value_facts
            if fact.get("fact_type") == "U"
        )
        value_source_types = {
            str(sources_by_id.get(fact.get("source_id"), {}).get("source_type", ""))
            for fact in value_facts
        }
        value_has_comparison_support = any(
            claim.get("claim_type") == "comparison" for claim in value_claims
        ) or bool(value_source_types.intersection(COMPETITOR_SOURCE_TYPES))
        value_comparison_text = without_comparison_denials(value_positive_text)
        for term in STRICT_FABE_SOURCE_TERMS:
            if term in value_positive_text and term not in value_claim_text and term not in value_user_text:
                errors.append(
                    f"{value_id} 使用了限定词“{term}”，但本价值所引原文或用户资料未直接出现该词；"
                    "不得把页面口感或配料事实扩写为新的用户任务或替代关系"
                )
        if (
            UNSUPPORTED_PRODUCT_COMPARATOR_RE.search(value_comparison_text)
            or UNSUPPORTED_PRODUCT_TARGET_RE.search(value_comparison_text)
            or MARKET_COMPARATOR_RE.search(value_comparison_text)
        ) and not value_has_comparison_support:
            errors.append(
                f"{value_id} 使用了无来源的产品替代对象或比较语言；"
                "必须由该价值自身引用页面对比、竞品页或行业对照，不能借用其他价值的比较资料"
            )
        if SULFUR_SAFETY_BENEFIT_RE.search(value_positive_text) and not SULFUR_SAFETY_ASSOCIATION_RE.search(value_claim_text):
            errors.append(f"{value_id} 把无硫熏主张扩写为安全、健康、危害或风险利益，但本价值所引原文没有直接依据")
        if PROMOTION_STACKING_RE.search(value_positive_text) and not PROMOTION_STACKING_RE.search(value_claim_text):
            errors.append(f"{value_id} 声称优惠或权益可以叠加，但支撑事实所引原文没有明确叠加规则")
        if PROMOTION_STACKING_RE.search(value_positive_text) and PROMOTION_STACKING_DENIAL_RE.search(value_denial_text):
            errors.append(f"{value_id} 一方面声称优惠可叠加，另一方面又在 cannot_prove 中否定叠加依据，结构化结论自相矛盾")

    for value_id, statements in value_cannot_prove.items():
        own_units = value_context_units.get(value_id, set())
        for statement in statements:
            statement_units = semantic_reference_units(statement)
            if not statement_units or statement_units.intersection(own_units):
                continue
            other_overlaps = {
                other_id: len(statement_units.intersection(other_units))
                for other_id, other_units in value_context_units.items()
                if other_id != value_id
            }
            if other_overlaps and max(other_overlaps.values()) >= 2:
                matched_id = max(other_overlaps, key=other_overlaps.get)
                errors.append(
                    f"{value_id}.cannot_prove 的“{statement}”与本价值无语义关联，"
                    f"却更接近 {matched_id}；不得把其他价值的未验证理由错挂到当前候选"
                )

    usable_value_ids = {
        str(value.get("value_id", ""))
        for value in values
        if value.get("layer") != "deferred" and value.get("downstream_readiness") != "blocked"
    }
    usable_fabe = [item for item in fabe if str(item.get("value_id", "")) in usable_value_ids]
    if usable_fabe and all(UNESTABLISHED_ADVANTAGE_RE.search(str(item.get("advantage", ""))) for item in usable_fabe):
        errors.append(
            "全部可用价值的 Advantage 都被写成 A 层暂不成立；"
            "应区分需要竞品证据的市场领先结论，与可由页面事实有边界推导的内生任务优势"
        )

    for gap in gaps:
        gap_id = str(gap.get("gap_id", ""))
        if gap.get("priority") not in GAP_PRIORITIES:
            errors.append(f"{gap_id} 的 priority 必须是 P0/P1/P2/P3")
        combined = " ".join(str(gap.get(key, "")) for key in ("missing", "impact", "minimum_needed"))
        if SKU_GAP_PROHIBITION_RE.search(combined) and SKU_SPEC_IN_NAME_RE.search(manifest_sku_text):
            errors.append(
                f"{gap_id} 声明相关规格不得进入 SKU 名称字段，但 product_manifest.sku 已包含规格；"
                "应将 SKU 改为待确认名称，或把缺口改写为当前页面规格仅作暂定、仍需实物或 SKU 选择器复核"
            )
        for fact_id, expected in dyn_expected_states.items():
            if expected == "active" and fact_id in combined and EXPIRY_WORDS_RE.search(combined):
                errors.append(f"{gap_id} 把仍处活动期的 {fact_id} 写成已过期")

    limitation_text = " ".join(str(item) for item in (manifest.get("limitations") or []))
    for fact_id, expected in dyn_expected_states.items():
        if expected == "active" and (fact_id in limitation_text or "DYN" in limitation_text) and EXPIRY_WORDS_RE.search(limitation_text):
            errors.append(f"limitations 把仍处活动期的 {fact_id} 写成已过期")

    active_dynamic_ids = {fact_id for fact_id, expected in dyn_expected_states.items() if expected == "active"}
    if active_dynamic_ids:
        dynamic_surfaces: list[tuple[str, str, bool]] = [
            ("product_manifest.limitations", limitation_text, "DYN" in limitation_text),
            ("p0_decision.rationale", str(decision.get("rationale", "")), "DYN" in str(decision.get("rationale", ""))),
            ("p0_decision.public_rationale", str(decision.get("public_rationale", "")), "DYN" in str(decision.get("public_rationale", ""))),
            ("p0_decision.current_execution_axis", str(decision.get("current_execution_axis", "")), "DYN" in str(decision.get("current_execution_axis", ""))),
            (
                "p0_decision.cannot_prove",
                " ".join(str(item) for item in (decision.get("cannot_prove") or [])),
                "DYN" in " ".join(str(item) for item in (decision.get("cannot_prove") or [])),
            ),
        ]
        dynamic_surfaces.extend(
            (
                f"{value.get('value_id')}.narrative",
                record_text(value),
                bool(active_dynamic_ids.intersection(str(item) for item in (value.get("supporting_fact_ids") or []))),
            )
            for value in values
        )
        dynamic_surfaces.extend(
            (
                f"{gap.get('gap_id')}.narrative",
                record_text(gap),
                "DYN" in record_text(gap) or any(fact_id in record_text(gap) for fact_id in active_dynamic_ids),
            )
            for gap in gaps
        )
        for location, text, explicitly_linked in dynamic_surfaces:
            refers_to_active_dynamic = (
                explicitly_linked
                or "DYN" in text
                or any(fact_id in text for fact_id in active_dynamic_ids)
            )
            if refers_to_active_dynamic and ACTIVE_DENIAL_RE.search(text):
                errors.append(
                    f"{location} 否定了快照时仍处活动期的动态权益；"
                    "允许在明确快照时间和截止日期的前提下写当前有效，不得与活动状态自相矛盾"
                )

    all_claim_text = " ".join(str(item.get("verbatim_text", "")) for item in source_claims)
    has_any_comparison_support = any(claim.get("claim_type") == "comparison" for claim in source_claims) or any(
        source.get("source_type") in COMPETITOR_SOURCE_TYPES for source in sources
    )
    for location, text in iter_analysis_texts(facts, fabe, anchors, values, decision):
        comparison_text = without_comparison_denials(text)
        for pattern, explanation in RISKY_INFERENCE_RULES:
            if pattern.search(text):
                errors.append(f"{location} 存在越界表达：{explanation}")
        if NO_ADDITIVE_RE.search(text):
            has_direct_claim = any(
                fact.get("fact_type") == "F-PAGE" and NO_ADDITIVE_RE.search(str(fact.get("statement", "")))
                for fact in facts
            )
            if not has_direct_claim:
                errors.append(f"{location} 存在越界表达：配料表只有一种原料不自动等于无添加或无防腐剂")
        if ABSOLUTE_COMPETITION_RE.search(text):
            if not any(source.get("source_type") in COMPETITOR_SOURCE_TYPES for source in sources):
                errors.append(f"{location} 存在越界表达：缺少竞品或行业对照，不能写最强、唯一、独有或领先")
        if AGGREGATE_USER_RE.search(text) and not any(fact.get("fact_type") == "U" for fact in facts):
            errors.append(
                f"{location} 存在越界表达：没有用户原声或研究资料，"
                "不能声称最常见、主流、普遍或多数用户存在该问题，也不能把某项问题写成用户的核心、主要或关键顾虑"
            )
        if CAFFEINE_NEGATIVE_RE.search(text) and not CAFFEINE_NEGATIVE_RE.search(all_claim_text):
            errors.append(
                f"{location} 将商品写成无咖啡因或不依赖咖啡因，但逐字原文没有该主张；"
                "页面对咖啡或睡眠的场景描述不能替代商品的咖啡因事实"
            )
        if SULFUR_SAFETY_BENEFIT_RE.search(text) and not SULFUR_SAFETY_ASSOCIATION_RE.search(all_claim_text):
            errors.append(f"{location} 存在越界表达：页面无直接依据时，不能把无硫熏主张扩写为对安全、健康、危害或风险的用户利益")
        if TRACEABILITY_RE.search(text) and not TRACEABILITY_RE.search(all_claim_text):
            errors.append(
                f"{location} 存在越界表达：页面列出产地不自动等于可追溯；"
                "必须有逐字可追溯主张或追溯系统证据"
            )
        if UNSUPPORTED_PRODUCT_COMPARATOR_RE.search(comparison_text) and not has_any_comparison_support:
            errors.append(f"{location} 存在越界表达：无来源的产品替代对象不得进入价值、识别锚或 P0 结论")
        elif UNSUPPORTED_PRODUCT_TARGET_RE.search(comparison_text) and not has_any_comparison_support:
            errors.append(f"{location} 存在越界表达：无来源的产品替代对象不得进入价值、识别锚或 P0 结论")
        elif MARKET_COMPARATOR_RE.search(comparison_text) and not has_any_comparison_support:
            errors.append(f"{location} 存在越界表达：市场或同类比较语言未绑定页面对比原文、竞品页或行业对照")
        for restriction in set(EATING_RESTRICTION_RE.findall(text)):
            if restriction not in all_claim_text:
                errors.append(f"{location} 新增了原文没有的限制性结论“{restriction}”")

    for location, text in iter_client_narrative_texts(manifest, facts, fabe, anchors, values, decision, gaps):
        if AUDIT_DOWNGRADE_ACTION_RE.search(text) and AUDIT_DOWNGRADE_REASON_RE.search(text):
            errors.append(
                f"{location} 记录了为绕过原文摘录而移除观察标记或降低文字密度；"
                "必须重新检查来源、恢复真实观察属性并补齐可见原文，不能修改证据分类来通过门禁"
            )
        if DUPLICATED_CLIENT_WORD_RE.search(text):
            errors.append(f"{location} 含重复词或内部拼接残片，需改写为自然客户中文")
        if (
            (location == "product_manifest.sku_basis" or not location.startswith(("GAP-", "product_manifest.limitations")))
            and FILENAME_METADATA_RE.search(text)
        ):
            errors.append(f"{location} 把文件名或路径当成了商品证据；文件元数据只能用于来源定位")
        if location.startswith("GAP-") and FILENAME_METADATA_RE.search(text) and SKU_CONFLICT_RE.search(text):
            errors.append(f"{location} 用文件名或路径制造了 SKU 事实冲突；商品冲突必须来自可见商品证据")
        if re.search(r"二次硫(?:熏制|处理|工艺)?", text):
            errors.append(f"{location} 含“二次硫”错词；必须回到原文核对二氧化硫相关表述")
        if EMPTY_PARENS_RE.search(text):
            errors.append(f"{location} 含空括号，属于未完成的客户文本")
        if DANGLING_ANALYSIS_RE.search(text):
            errors.append(f"{location} 含缺少结论对象的不完整客户文本：{text}")
        if PUBLIC_CONTRADICTION_RE.search(text):
            errors.append(f"{location} 含“难入口温和”等语义矛盾残句，必须回到原文重新表述")
        if PUBLIC_ID_RESIDUE_RE.search(text):
            errors.append(f"{location} 含内部 ID 删减后的残余片段，必须重写完整客户句")
        if PUBLIC_FRAGMENT_RE.search(text):
            errors.append(f"{location} 含隐藏内部字段后形成的客户残句，必须回到账本重写完整句子：{text}")

    conflict_blocked_surfaces = (
        ("anchor_ledger", anchors),
        ("fabe_ledger", fabe),
        ("value_ledger", values),
    )
    for surface_name, records in conflict_blocked_surfaces:
        for record in records:
            surface_text = record_text(record)
            for phrase in conflicted_spec_phrases:
                if contains_spec_phrase(surface_text, phrase):
                    record_id = next(
                        (
                            str(record.get(key))
                            for key in ("anchor_id", "fabe_id", "value_id")
                            if record.get(key)
                        ),
                        "未知记录",
                    )
                    errors.append(
                        f"{surface_name} 的 {record_id} 继续使用冲突规格“{phrase}”；"
                        "冲突字段只能保留在来源、事实边界和资料缺口，不得进入识别锚、FABE 或价值结论"
                    )
                    break

    exact_value_surfaces = (
        ("fabe_ledger", fabe),
        ("anchor_ledger", anchors),
        ("value_ledger", values),
        ("gap_ledger", gaps),
    )
    for surface_name, records in exact_value_surfaces:
        for record in records:
            unexpected = exact_evidence_values(record_text(record)).difference(allowed_exact_values)
            if unexpected:
                errors.append(
                    f"{surface_name} 的 {next(iter(unexpected))} 未由原件级 F-EVIDENCE 事实核验，不得进入结构化结论"
                )
    decision_unexpected = exact_evidence_values(record_text(decision)).difference(allowed_exact_values)
    if decision_unexpected:
        errors.append(f"p0_decision.json 的 {next(iter(decision_unexpected))} 未由原件级 F-EVIDENCE 事实核验")
    decision_text = record_text(decision)
    for phrase in conflicted_spec_phrases:
        if contains_spec_phrase(decision_text, phrase):
            errors.append(f"p0_decision.json 继续使用冲突规格“{phrase}”；冲突规格不得进入推荐理由或执行主轴")
    if MALFORMED_OCR_RE.search(decision_text):
        errors.append("p0_decision.json 含疑似 OCR 残片，不得进入正式 P0 决策")
    limitation_unexpected = exact_evidence_values(" ".join(str(item) for item in (manifest.get("limitations") or []))).difference(
        allowed_exact_values
    )
    if limitation_unexpected:
        errors.append(f"limitations 的 {next(iter(limitation_unexpected))} 未由原件级 F-EVIDENCE 事实核验")

    p0_values = [item for item in values if item.get("layer") == "P0"]
    if len(p0_values) > 1:
        errors.append("当前 layer=P0 的价值超过一个；未推荐候选应保留在其他层或 deferred")
    for layer in ("P1", "P2"):
        count = sum(1 for item in values if item.get("layer") == layer)
        if count > 3:
            errors.append(f"普通版 {layer} 超过 3 个，需合并或降为暂缓")

    decision_missing = missing_fields(decision, DECISION_FIELDS)
    if decision_missing:
        errors.append(f"p0_decision.json 缺少字段: {', '.join(decision_missing)}")
    if not re.fullmatch(r"P0D-\d{3,}", str(decision.get("decision_id", ""))):
        errors.append("decision_id 格式无效")
    if decision.get("status") not in P0_STATUSES:
        errors.append("P0 决策状态不在允许范围")
    execution_value_ids = decision.get("current_execution_value_ids")
    if not isinstance(execution_value_ids, list):
        errors.append("current_execution_value_ids 必须是数组")
        execution_value_ids = []
    if len(execution_value_ids) != len(set(execution_value_ids)):
        errors.append("current_execution_value_ids 不得重复")
    if str(decision.get("current_execution_axis", "")).strip() and decision.get("recommended_value_id") and not execution_value_ids:
        errors.append("已有当前执行主轴时，current_execution_value_ids 不得为空")
    for value_id in execution_value_ids:
        if value_id not in values_by_id:
            errors.append(f"当前执行主轴引用了不存在的 value_id: {value_id}")
            continue
        value = values_by_id[value_id]
        if value.get("layer") == "deferred" or value.get("downstream_readiness") == "blocked":
            errors.append(f"当前执行主轴不得引用暂缓或禁止调用的价值: {value_id}")
    if decision.get("recommended_value_id") and execution_value_ids and decision.get("recommended_value_id") not in execution_value_ids:
        errors.append("current_execution_value_ids 必须包含当前推荐 P0")
    expected_axis = expected_execution_axis(execution_value_ids, values_by_id)
    if execution_value_ids and str(decision.get("current_execution_axis", "")).strip() != expected_axis:
        errors.append(
            "current_execution_axis 必须由 current_execution_value_ids 对应的 value_statement 按顺序自动拼接；"
            "不得额外调用未列出的价值，也不得用自由改写掩盖实际执行范围"
        )
    has_external_comparison_support = any(
        source.get("source_type") in COMPETITOR_SOURCE_TYPES for source in sources
    )
    low_strategy_without_comparison = manifest.get("sc") in {"SC0", "SC1"} and not has_external_comparison_support
    if (
        low_strategy_without_comparison
        and decision.get("recommended_value_id")
        and decision.get("status") != "P0-HYPOTHESIS"
    ):
        errors.append(
            "战略信息仅为 SC0/SC1 且没有竞品页或行业对照时，P0 决策只能标记为 P0-HYPOTHESIS；商品页自有对比不足以证明战略优先级"
        )
    if not str(decision.get("public_rationale", "")).strip() and decision.get("recommended_value_id"):
        errors.append("已有推荐 P0 时 public_rationale 不得为空")
    if INTERNAL_ID_RE.search(str(decision.get("public_rationale", ""))):
        errors.append("public_rationale 不得包含内部资产 ID")
    if PUBLIC_JARGON_RE.search(str(decision.get("public_rationale", ""))):
        errors.append("public_rationale 不得包含内部英文字段或技术状态")
    decided_at = parse_datetime(decision.get("decided_at"))
    if timestamp_after_file(decided_at, paths["decision"]):
        errors.append("p0_decision.decided_at 晚于决策文件实际写入时间，存在未来时间")
    candidate_ids = decision.get("candidate_value_ids")
    if not isinstance(candidate_ids, list):
        errors.append("candidate_value_ids 必须是数组")
        candidate_ids = []
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate_value_ids 不得重复")
    if decision.get("recommended_value_id") and len(candidate_ids) < 2:
        errors.append(
            "已有推荐 P0 时，candidate_value_ids 至少需要两个不同的用户价值候选；"
            "不得用单一价值与 P2 检测、认证或参数信息形成伪候选比较"
        )
    declared_candidate_ids = {value_id for value_id, value in values_by_id.items() if value.get("p0_candidate") is True}
    if set(candidate_ids) != declared_candidate_ids:
        missing_from_decision = sorted(declared_candidate_ids.difference(candidate_ids))
        extra_in_decision = sorted(set(candidate_ids).difference(declared_candidate_ids))
        details = []
        if missing_from_decision:
            details.append(f"未进入决策池: {', '.join(missing_from_decision)}")
        if extra_in_decision:
            details.append(f"非候选却进入决策池: {', '.join(extra_in_decision)}")
        errors.append(f"P0 候选标记必须与 candidate_value_ids 完全一致（{'；'.join(details)}）")
    for value_id in candidate_ids:
        if value_id not in value_ids:
            errors.append(f"P0 候选池引用了不存在的 value_id: {value_id}")
        elif values_by_id[value_id].get("p0_candidate") is not True:
            errors.append(f"{value_id} 在 P0 候选池中，但 p0_candidate 不是 true")
    candidate_statements: dict[str, str] = {}
    for value_id in candidate_ids:
        statement = re.sub(r"[\s，,。；;：:]", "", str(values_by_id.get(value_id, {}).get("value_statement", "")))
        if not statement:
            continue
        if statement in candidate_statements:
            errors.append(
                f"P0 候选 {value_id} 与 {candidate_statements[statement]} 的价值说明相同；"
                "候选池必须比较不同用户价值轴，不能用同义重复充数"
            )
        else:
            candidate_statements[statement] = value_id
    recommended_id = decision.get("recommended_value_id")
    if recommended_id:
        if recommended_id not in value_ids:
            errors.append(f"P0 推荐引用了不存在的 value_id: {recommended_id}")
        else:
            if recommended_id not in candidate_ids:
                errors.append("P0 推荐值不在 candidate_value_ids 中")
            if values_by_id[recommended_id].get("layer") != "P0":
                errors.append("P0 推荐值的 layer 必须是 P0")
            if values_by_id[recommended_id].get("downstream_readiness") == "blocked":
                errors.append("P0 推荐值不得是 downstream_readiness=blocked")
            if low_strategy_without_comparison and values_by_id[recommended_id].get("p0_status") != "P0-HYPOTHESIS":
                errors.append(
                    f"{recommended_id} 在低战略信息且无竞争对照时，p0_status 必须是 P0-HYPOTHESIS"
                )
    for value_id in candidate_ids:
        if value_id == recommended_id or value_id not in values_by_id:
            continue
        if not any(str(item).strip() for item in (values_by_id[value_id].get("cannot_prove") or [])):
            errors.append(f"{value_id} 是未入选的 P0 候选，必须在 cannot_prove 中说明当前未入选原因")

    analysis_status = manifest.get("analysis_status")
    delivery_status = manifest.get("delivery_status")
    if analysis_status in {"complete", "partial"}:
        for key in ("brand", "product", "sku"):
            if not str(manifest.get(key, "")).strip():
                errors.append(f"analysis_status={analysis_status} 时 {key} 不得为空")
        if not sources:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个来源")
        if not facts:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个事实或推导")
        if not values:
            errors.append(f"analysis_status={analysis_status} 时至少需要一个可用价值")
        if manifest.get("sku_status") in {"partial", "unverified"}:
            has_open_sku_gap = any(
                gap.get("state") == "open"
                and re.search(r"SKU|规格|成交单元|商品身份", f"{gap.get('category', '')} {gap.get('missing', '')}", re.IGNORECASE)
                for gap in gaps
            )
            if not has_open_sku_gap:
                errors.append("SKU 未完全确认时，必须登记一个开放的 SKU/规格资料缺口")
            if delivery_status == "ready":
                errors.append("SKU 未完全确认时 delivery_status 不得为 ready")
    if analysis_status == "complete":
        if not recommended_id:
            errors.append("analysis_status=complete 时必须有当前推荐 P0")
        if decision.get("status") in {"P0-CANDIDATE", "P0-REOPEN", "P0-REPLACED", "P0-STOPPED"}:
            errors.append("analysis_status=complete 与当前 P0 决策状态不一致")
        if delivery_status not in {"ready", "conditional"}:
            errors.append("analysis_status=complete 时 delivery_status 应为 ready 或 conditional")
    elif analysis_status == "partial":
        if delivery_status != "conditional":
            errors.append("analysis_status=partial 时 delivery_status 必须是 conditional")
    elif analysis_status == "insufficient":
        if not gaps:
            errors.append("analysis_status=insufficient 时至少需要一个资料缺口")
        if delivery_status != "blocked":
            errors.append("analysis_status=insufficient 时 delivery_status 必须是 blocked")
    elif analysis_status == "stale":
        if delivery_status != "stale":
            errors.append("analysis_status=stale 时 delivery_status 必须是 stale")

    report_data = load_delivery(delivery)
    expected_reports = {
        "report_01": build_report_01(report_data).rstrip() + "\n",
        "report_02": build_report_02(report_data).rstrip() + "\n",
    }
    for report_key in ("report_01", "report_02"):
        text = paths[report_key].read_text(encoding="utf-8")
        if text != expected_reports[report_key]:
            errors.append(
                f"{paths[report_key].name} 与当前结构化账本不一致；禁止手工改报告，必须修正账本后重新生成"
            )
        if "{{" in text or "}}" in text:
            errors.append(f"{paths[report_key].name} 仍包含模板占位符")
        if re.search(r"[A-Za-z]:\\(?:Users|Documents|Desktop)\\", text, re.IGNORECASE):
            errors.append(f"{paths[report_key].name} 暴露了本地绝对路径")
        if INTERNAL_ID_RE.search(text):
            errors.append(f"{paths[report_key].name} 暴露了内部资产 ID")
        if re.search(r"[（(]\s*[,/;+、，;；:：]+|[,/;+、，;；:：]+\s*[)）]", text):
            errors.append(f"{paths[report_key].name} 含隐藏内部 ID 后遗留的异常标点")
        if re.search(r"\|\s*>[^|\r\n]*\|", text):
            errors.append(f"{paths[report_key].name} 的表格单元格含多余的 > 符号")
        if re.search(r"→\s*→|[（(]\s*(?:→\s*)+[)）]", text):
            errors.append(f"{paths[report_key].name} 含删除内部 ID 后残留的箭头或空括号")
        if EMPTY_PARENS_RE.search(text):
            errors.append(f"{paths[report_key].name} 含空括号，属于未完成的客户文本")
        if DANGLING_ANALYSIS_RE.search(text):
            errors.append(f"{paths[report_key].name} 含缺少结论对象的不完整客户文本")
        if PUBLIC_JARGON_RE.search(text):
            errors.append(f"{paths[report_key].name} 暴露了客户无需理解的内部字段或英文状态")
        if PUBLIC_ID_RESIDUE_RE.search(text):
            errors.append(f"{paths[report_key].name} 含 /005/006、//reference_frame 或空回答等内部删减残片")
        if PUBLIC_CONTRADICTION_RE.search(text):
            errors.append(f"{paths[report_key].name} 含“难入口温和”等语义矛盾残句")
        if MALFORMED_OCR_RE.search(text):
            errors.append(f"{paths[report_key].name} 含 oneBag 或斜杠拼接等疑似 OCR 残片，不能作为客户稿")
        if (
            UNSUPPORTED_PRODUCT_COMPARATOR_RE.search(text) or UNSUPPORTED_PRODUCT_TARGET_RE.search(text)
        ) and not has_any_comparison_support:
            errors.append(f"{paths[report_key].name} 含无来源的产品替代对象，不能作为客户结论")
        for cell in markdown_public_cells(text):
            clean_cell = cell.strip("`*_ ")
            if re.search(r"[，,；;：:]$", clean_cell):
                errors.append(f"{paths[report_key].name} 的表格单元格以逗号、分号或冒号结尾，疑似客户残句：{clean_cell}")
            if PUBLIC_FRAGMENT_RE.search(clean_cell):
                errors.append(f"{paths[report_key].name} 的表格单元格含缺失主语或对象的客户残句：{clean_cell}")
        for restriction in set(EATING_RESTRICTION_RE.findall(text)):
            if restriction not in all_claim_text:
                errors.append(f"{paths[report_key].name} 新增了原文没有的限制性结论“{restriction}”")
        if report_key == "report_01":
            for value_id in candidate_ids:
                statement = str(values_by_id.get(value_id, {}).get("value_statement", "")).strip()
                if statement and statement not in text:
                    errors.append(f"01_商品价值底座.md 未展示 P0 候选 {value_id} 的候选价值说明")
        unexpected = exact_evidence_values(text).difference(allowed_exact_values)
        if unexpected:
            errors.append(
                f"{paths[report_key].name} 含未由原件级 F-EVIDENCE 核验的精确证据值: {next(iter(unexpected))}"
            )

    return {
        "status": "passed" if not errors else "failed",
        "delivery": str(delivery),
        "analysis_status": analysis_status,
        "delivery_status": delivery_status,
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_delivery(args.delivery)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
