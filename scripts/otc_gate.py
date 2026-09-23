#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTC / 处方药判定门控（合规）

背景：按监管要求（药监综药管函〔2023〕333号 / 《互联网药品信息服务管理办法》），
处方审核通过前不得向公众展示/发送处方药的适应症、用法用量、说明书等信息。
本技能改为：**命中 OTC 白名单 → 正常返回完整档案；未命中 → 视为处方药 → 只返回拦截话术**，
不返回适应症/用法用量/购药入口等。药品数据本身不做任何删除。

判定依据：`data/otc_whitelist.json`（保守版非处方药白名单，含化学药+中成药及别名）。
归一化规则与 drug_index 一致（去剂型后缀、保留盐类前缀），并额外做「含中即算」的
宽松匹配：只要药品通用名或任一别名命中白名单的「通用名/别名」集合即视为 OTC。
"""
import os
import json

# 白名单路径（相对本文件上一级的 data/）
_OTC_WHITELIST_REL = os.path.join("..", "data", "otc_whitelist.json")


def _normalize_for_gate(name: str) -> str:
    """白名单命中的轻量归一化：去空白、去剂型后缀、去括号，保留盐类前缀。"""
    if not name:
        return ""
    n = str(name).strip()
    # 去括号及内容
    import re
    n = re.sub(r"[（(].*?[）)]", "", n).strip()
    # 去常见剂型后缀（复用 drug_index 的规则，但此处独立实现避免循环依赖）
    _dosage = [
        "口服混悬液", "口服溶液剂", "口服溶液", "口服乳剂", "口服散剂",
        "肠溶胶囊", "缓释胶囊", "控释胶囊", "软胶囊", "硬胶囊", "胶囊剂", "胶囊",
        "肠溶片剂", "肠溶衣片", "缓释片剂", "控释片剂", "缓释片", "控释片",
        "分散片", "咀嚼片", "泡腾片", "含片", "口腔贴片", "口腔崩解片", "片剂", "片",
        "颗粒剂", "颗粒", "注射剂", "注射液", "粉针剂", "冻干粉针剂", "冻干粉针",
        "注射用无菌粉末", "注射用浓溶液", "滴眼剂", "滴眼液", "眼膏剂", "眼膏",
        "滴耳剂", "滴鼻剂", "喷雾剂", "气雾剂", "吸入剂", "粉雾剂", "雾化剂",
        "软膏剂", "乳膏剂", "凝胶剂", "糊剂", "外用膏剂", "外用液体剂", "外用散剂",
        "外用贴剂", "贴膏剂", "贴剂", "膏药", "栓剂", "肛用栓", "阴道栓", "膜剂",
        "涂膜剂", "酊剂", "酒剂", "露剂", "糖浆剂", "合剂", "茶剂", "锭剂",
        "丸剂", "滴丸", "浓缩丸", "水丸", "蜜丸", "水蜜丸", "大蜜丸", "小蜜丸",
        "散剂", "粉剂", "搽剂", "洗剂", "涂剂", "含漱剂", "灌肠剂", "植入剂",
        "埋植剂", "耳用制剂", "鼻用制剂", "眼用制剂", "干混悬剂", "混悬剂",
        "混悬液", "乳剂", "乳胶剂", "海绵剂", "条剂", "线剂", "糕剂", "丹剂",
        "口服液", "口服乳", "口服混悬",
    ]
    for suffix in sorted(_dosage, key=len, reverse=True):
        if n.endswith(suffix) and len(n) > len(suffix) + 1:
            n = n[: -len(suffix)]
            break
    return n


class OTCGate:
    """OTC / 处方药判定门控"""

    def __init__(self, whitelist_path: str = None):
        self.path = whitelist_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), _OTC_WHITELIST_REL
        )
        self._names = set()      # 白名单通用名（归一化）
        self._aliases = set()    # 白名单别名（归一化）
        self._loaded = False
        self._meta = {}

    def load(self) -> int:
        """加载 OTC 白名单，返回收录药品数。文件缺失时安全降级（不阻断）。"""
        if not os.path.exists(self.path):
            self._loaded = False
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self._loaded = False
            return 0
        self._meta = data.get("meta", {})
        for item in data.get("chemical", []) + data.get("tcm", []):
            n = _normalize_for_gate(item.get("n", ""))
            if n:
                self._names.add(n)
            for a in item.get("a", []):
                an = _normalize_for_gate(a)
                if an:
                    self._aliases.add(an)
        self._loaded = True
        return len(self._names)

    def is_otc(self, drug_name: str, aliases=None) -> bool:
        """判断某药品是否命中 OTC 白名单。

        drug_name: 药品通用名（或其变体）
        aliases:   可选，该药品的剂型变体/别名列表
        """
        if not self._loaded:
            return False  # 白名单未加载 → 保守按处方药处理
        n = _normalize_for_gate(drug_name)
        if n in self._names or n in self._aliases:
            return True
        if aliases:
            for a in aliases:
                an = _normalize_for_gate(a)
                if an in self._names or an in self._aliases:
                    return True
        return False


# 模块级单例（懒加载）
_gate = None


def get_otc_gate() -> OTCGate:
    global _gate
    if _gate is None:
        _gate = OTCGate()
        _gate.load()
    return _gate


def is_otc(drug_name: str, aliases=None) -> bool:
    """便捷函数：判断是否 OTC（未命中白名单 → False，即按处方药拦截）"""
    return get_otc_gate().is_otc(drug_name, aliases)
