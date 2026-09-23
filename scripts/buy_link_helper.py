#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
购药链接模块（全量版，技能包内自包含 / 零密钥）

规则（2026-09-22 用户决策）：
  1. 所有药品均提供购药参考链接（不做 OTC 筛选）；平台购买逻辑自动负责合规；
  2. 三平台链接：京东大药房 / 阿里健康 / 拼多多（公开搜索，零依赖）；
     京东优先经统一转链服务 POST {worker}/p/convert 生成短链，失败降级公开搜索；
  3. 美团本地送药：提供链接 + 引导用户提供位置后发本地送药链接；
  4. 本模块不含任何密钥/token；worker 地址与 slug 从 data/union_config.json 读取。

对外统一披露（合规）：本技能推荐的优惠链接来自平台官方合作渠道。
"""
import os
import sys
import json
import urllib.request
import urllib.parse

# ---------------- 路径 ----------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
CONFIG_PATH = os.path.join(DATA_DIR, "union_config.json")
OTC_PATH = os.path.join(DATA_DIR, "otc_whitelist.json")

DEFAULT_WORKER = "https://union-convert-tbxkbskpjy.cn-hangzhou.fcapp.run"
DEFAULT_SLUG = "yongyao"
HTTP_TIMEOUT = 12

# 简单进程内缓存，避免同一进程对同一药品重复请求转链
_LINK_CACHE = {}


# ---------------- 配置加载 ----------------
def _load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _worker_base():
    cfg = _load_config()
    return (cfg.get("worker", {}) or {}).get("url") or DEFAULT_WORKER


def _slug():
    cfg = _load_config()
    return cfg.get("slug") or cfg.get("src") or DEFAULT_SLUG


def _load_otc():
    try:
        with open(OTC_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"chemical": [], "tcm": []}


# ---------------- 名称归一化与匹配 ----------------
# 化学药常见盐型/酸型前缀（匹配核心词时去除）
_SALT_PREFIX = [
    "盐酸", "氢溴酸", "马来酸", "硫酸", "硝酸", "醋酸", "乙酸", "甲磺酸",
    "琥珀酸", "富马酸", "酒石酸", "枸橼酸", "柠檬酸", "乳酸", "葡萄糖酸",
    "苯磺酸", "左旋", "重酒石酸", "磷酸",
]
# 剂型后缀（按长度降序，先匹配长的）
_DOSAGE_SUFFIX = [
    "口服溶液", "鼻腔喷雾", "滴眼液", "滴鼻液", "肠溶片", "缓释片", "分散片",
    "泡腾片", "咀嚼片", "软胶囊", "硬胶囊", "颗粒", "胶囊", "溶液", "凝胶",
    "乳膏", "软膏", "洗剂", "喷雾", "含片", "贴", "片", "丸", "散", "膏",
    "水", "液",
]
# 外用严格词：命中的白名单条目必须完整名称匹配，避免同名口服处方药被误判
_TOPICAL_WORDS = [
    "软膏", "眼膏", "乳膏", "凝胶", "洗剂", "滴眼液", "滴鼻液", "喷雾",
    "贴", "栓", "气雾剂", "烧伤膏", "痔疮膏",
]


def _normalize(text):
    """归一化：去空白/括号内容/常见标点，便于包含匹配"""
    if not text:
        return ""
    s = str(text)
    for ch in "（）()【】[]　 \t\n\r,，、;；:：":
        s = s.replace(ch, "")
    return s.strip().lower()


def _core_name(name):
    """从规范条目名提取核心词：去剂型后缀 + 去盐型前缀"""
    s = name
    changed = True
    while changed:
        changed = False
        for suf in _DOSAGE_SUFFIX:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)]
                changed = True
                break
    for pre in _SALT_PREFIX:
        # 去掉盐型前缀后至少保留 3 个字，避免“琥珀酸亚铁→亚铁”这类过度剥离导致
        # 核心词过短被双向包含误匹配（如硫酸亚铁被琥珀酸亚铁片命中）
        if s.startswith(pre) and len(s) >= len(pre) + 3:
            s = s[len(pre):]
            break
    return s


def _entry_hit(entry, norm_q):
    """判断归一化后的查询名是否命中某白名单条目"""
    name = entry.get("n", "")
    aliases = entry.get("a", []) or []
    is_topical = any(w in name for w in _TOPICAL_WORDS)

    targets = [_normalize(name)]
    if not is_topical:
        core = _core_name(name)
        targets.append(_normalize(core))
    for a in aliases:
        targets.append(_normalize(a))
    targets = [t for t in targets if t]

    if is_topical:
        # 外用药：查询名必须包含完整条目名（含剂型），杜绝口服处方药误匹配
        return any(t and len(t) >= 2 and t in norm_q for t in targets)
    # 口服/通用：双向包含匹配；两边都至少 2 个字，防止单字泛匹配
    return any(
        t and len(t) >= 2 and len(norm_q) >= 2 and (t in norm_q or norm_q in t)
        for t in targets
    )


def classify_otc(drug_name):
    """
    判定药品是否为可售 OTC。
    Returns: (is_otc: bool, entry: dict|None)
    """
    if not drug_name:
        return False, None
    norm_q = _normalize(drug_name)
    if not norm_q:
        return False, None
    # 全局硬规则：注射剂/静脉给药剂型一律按处方药处理（无大众OTC注射剂）
    if "注射" in drug_name or "静脉" in drug_name:
        return False, None
    otc = _load_otc()
    for section in ("chemical", "tcm"):
        for entry in otc.get(section, []) or []:
            if _entry_hit(entry, norm_q):
                return True, entry
    return False, None


# ---------------- 转链（统一 FC 公开端点，零密钥） ----------------
def _post_json(url, payload, timeout=HTTP_TIMEOUT):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_link(obj):
    """从容错的多种返回结构中提取链接"""
    if not isinstance(obj, dict):
        return None
    for key in ("url", "link", "short_url", "shortUrl"):
        v = obj.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    data = obj.get("data")
    if isinstance(data, dict):
        return _extract_link(data)
    if isinstance(data, str) and data.startswith("http"):
        return data
    return None


def get_otc_purchase_link(drug_name):
    """
    获取 OTC 药品的京东大药房购买链接（经统一转链服务生成）。
    处方药/未命中返回 None；转链失败返回 None（由调用方降级公开搜索）。
    """
    is_otc, _entry = classify_otc(drug_name)
    if not is_otc:
        return None
    return get_purchase_link(drug_name)


def get_purchase_link(drug_name):
    """
    获取京东大药房购买链接（经统一转链服务生成）。全量版：所有药品均提供。
    转链失败返回 None（由调用方降级公开搜索）。
    """
    if not drug_name:
        return None
    if drug_name in _LINK_CACHE:
        return _LINK_CACHE[drug_name]

    url = _worker_base().rstrip("/") + "/p/convert"
    payload = {"platform": "jd", "keyword": drug_name, "slug": _slug()}
    link = None
    try:
        res = _post_json(url, payload)
        if isinstance(res, dict) and res.get("ok", True):
            link = _extract_link(res.get("data") if "data" in res else res)
        else:
            link = _extract_link(res)
    except Exception:
        link = None

    _LINK_CACHE[drug_name] = link
    return link


# ---------------- 公开搜索（不计佣，零依赖） ----------------
# 平台搜索 URL 映射：京东 / 阿里健康（淘宝健康频道）/ 拼多多 / 美团买药
SEARCH_URLS = {
    "jd":      "https://search.jd.com/Search?keyword={q}&enc=utf-8",
    "alijk":   "https://s.taobao.com/search?q={q}&style=grid&tab=all",  # 阿里健康大药房在淘宝/天猫
    "pdd":     "https://mobile.yangkeduo.com/search_result.html?search_key={q}",
    "meituan": "https://yao.meituan.com/search?keyword={q}",
}

def build_search(platform, keyword):
    q = urllib.parse.quote(keyword)
    tpl = SEARCH_URLS.get(platform)
    return tpl.format(q=q) if tpl else "#"


# 三平台链接（按平台顺序稳定输出）
PLATFORM_LABELS = [
    ("jd", "京东大药房"),
    ("alijk", "阿里健康"),
    ("pdd", "拼多多"),
]


# ---------------- 渲染：付费层完整购药区块 ----------------
def render_buy_section(drug_name, backend_raw=None):
    """
    付费层“购药参考”区块（三平台：京东/阿里健康/拼多多 + 美团本地送药引导）。
    backend_raw 参数保留以兼容现有调用链（fc-backend 不改动），但不依赖它。
    京东优先尝试转链短链，失败降级公开搜索；其余平台为公开搜索链接。
    """
    if not drug_name:
        return ""

    jd_link = get_purchase_link(drug_name) or build_search("jd", drug_name)

    lines = []
    lines.append("### 购药参考")
    lines.append("")
    lines.append(f"- 京东大药房：[{drug_name}]({jd_link})")
    for plat, label in PLATFORM_LABELS:
        if plat == "jd":
            continue
        lines.append(f"- {label}：[{drug_name}]({build_search(plat, drug_name)})")
    lines.append("")
    lines.append(
        "> 线上购药请选择正规渠道，认准药品批准文号，按药品说明书或在药师指导下购买使用；"
        "处方药须凭医师处方购买；若不确定是否适合自己，请先咨询医生或药师。"
        "药品价格以各平台页面实时显示为准。"
    )
    lines.append("")
    lines.append(
        f"🏥 **本地送药**：如需美团本地送药，请提供您的位置（如：深圳南山区），"
        f"我来给您发美团本地送药链接：[美团买药·{drug_name}]({build_search('meituan', drug_name)})"
    )
    lines.append("")
    lines.append("> 本技能推荐的优惠链接来自平台官方合作渠道。")
    return "\n".join(lines)


# ---------------- 渲染：免费层精简购药入口 ----------------
def render_otc_inline(drug_name):
    """
    免费层（含付费墙）精简购药入口（三平台：京东/阿里健康/拼多多 + 美团引导）。
    """
    if not drug_name:
        return ""
    jd_link = get_purchase_link(drug_name) or build_search("jd", drug_name)
    links = [f"[京东大药房·{drug_name}]({jd_link})"]
    for plat, label in PLATFORM_LABELS:
        if plat == "jd":
            continue
        links.append(f"[{label}·{drug_name}]({build_search(plat, drug_name)})")
    part = "、".join(links)
    return (
        f"需要购药可走正规线上药房：{part}"
        f"（请按说明书或在药师指导下使用；处方药须凭医师处方购买；"
        f"价格以平台实时显示为准；如需美团本地送药，请提供您的位置）\n\n"
        f"> 本技能推荐的优惠链接来自平台官方合作渠道。"
    )


# ---------------- 命令行（运维/测试） ----------------
def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("check",):
        print("用法: python buy_link_helper.py check <药品名称>")
        print("示例: python buy_link_helper.py check 布洛芬缓释胶囊")
        print("      python buy_link_helper.py check 阿莫西林")
        return
    name = sys.argv[2]
    is_otc, entry = classify_otc(name)
    print(f"药品: {name}")
    print(f"是否可售OTC: {'是' if is_otc else '否（处方药/未命中，不提供购买链接）'}")
    if is_otc:
        print(f"命中条目: {entry.get('n')}（{entry.get('c')}类）")
        link = get_otc_purchase_link(name)
        if link:
            print(f"京东大药房链接: {link}")
        else:
            print(f"转链暂不可用，降级公开搜索: {build_search('jd', name)}")


if __name__ == "__main__":
    main()
