#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
药品名称归一化匹配模块
复用三源模糊合并的归一化规则：
a) 去掉剂型后缀（片/胶囊/注射液/注射剂/颗粒等80+种）
b) 去掉"注射用"前缀
c) 保留盐类前缀（盐酸/甲磺酸/硫酸等不剥除）
d) 高置信度匹配，拿不准的不并
"""
import re
import json
import os

# ============================================================
# 剂型后缀列表（按长度降序排列，优先匹配长的）
# ============================================================
DOSAGE_SUFFIXES = [
    "口服混悬液", "口服溶液剂", "口服溶液", "口服乳剂", "口服散剂",
    "肠溶胶囊", "缓释胶囊", "控释胶囊", "软胶囊", "硬胶囊", "胶囊剂", "胶囊",
    "肠溶片剂", "肠溶衣片", "缓释片剂", "控释片剂", "缓释片", "控释片",
    "分散片", "咀嚼片", "泡腾片", "含片", "口腔贴片", "口腔崩解片",
    "片剂", "片",
    "颗粒剂", "颗粒",
    "注射剂", "注射液", "粉针剂", "冻干粉针剂", "冻干粉针",
    "注射用无菌粉末", "注射用浓溶液",
    "滴眼剂", "滴眼液", "眼膏剂", "眼膏", "滴耳剂", "滴鼻剂",
    "喷雾剂", "气雾剂", "吸入剂", "粉雾剂", "雾化剂",
    "软膏剂", "乳膏剂", "凝胶剂", "糊剂", "外用膏剂", "外用液体剂",
    "外用散剂", "外用贴剂", "贴膏剂", "贴剂", "膏药",
    "栓剂", "肛用栓", "阴道栓",
    "膜剂", "涂膜剂",
    "酊剂", "酒剂", "露剂", "糖浆剂", "合剂", "茶剂", "锭剂",
    "丸剂", "滴丸", "浓缩丸", "水丸", "蜜丸", "水蜜丸", "大蜜丸", "小蜜丸",
    "散剂", "粉剂",
    "搽剂", "洗剂", "涂剂", "含漱剂", "灌肠剂",
    "植入剂", "埋植剂",
    "耳用制剂", "鼻用制剂", "眼用制剂",
    "干混悬剂", "混悬剂", "混悬液", "乳剂", "乳胶剂",
    "海绵剂", "条剂", "线剂", "糕剂", "丹剂",
    "口服液", "口服乳", "口服混悬",
]

# 盐类前缀（保留，不剥除）
SALT_PREFIXES = [
    "盐酸", "硫酸", "硝酸", "磷酸", "醋酸", "枸橼酸", "柠檬酸",
    "甲磺酸", "苯磺酸", "对氨基水杨酸", "乳酸", "葡萄糖酸",
    "马来酸", "富马酸", "酒石酸", "琥珀酸", "泛酸",
    "氢溴酸", "氢氯酸", "水杨酸", "双羟萘酸", "丙酸",
    "丁酸", "戊酸", "己酸", "庚酸", "棕榈酸", "硬脂酸",
    "苯甲酸", "萘甲酸", "依托酸",
]

INJECTION_PREFIX = "注射用"


def normalize_drug_name(name):
    """
    保守的通用名归一化
    返回 (normalized_name, is_high_confidence, original_name)
    """
    if not name:
        return "", False, ""

    original = name.strip()
    normalized = original

    # 去掉"注射用"前缀
    had_injection_prefix = normalized.startswith(INJECTION_PREFIX)
    if had_injection_prefix:
        normalized = normalized[len(INJECTION_PREFIX):]

    # 去掉剂型后缀（从最长的开始匹配）
    removed_dosage = False
    for suffix in sorted(DOSAGE_SUFFIXES, key=len, reverse=True):
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
            normalized = normalized[:-len(suffix)]
            removed_dosage = True
            break

    # 去掉括号及内容
    normalized = re.sub(r'[（(].*?[）)]', '', normalized).strip()

    # 置信度判断
    is_high_conf = (removed_dosage or had_injection_prefix) and len(normalized) >= 2

    return normalized, is_high_conf, original


# ============================================================
# 药品索引类
# ============================================================
class DrugIndex:
    """药品检索索引：精确匹配 + 归一化匹配 + 模糊匹配"""

    def __init__(self, data_file=None):
        self.archives = []  # 全部档案
        self.exact_index = {}  # 精确药名 -> 档案
        self.normalized_index = {}  # 归一化名 -> 档案列表
        self.alias_index = {}  # 别名 -> 档案

    def load(self, data_file):
        """从JSON加载药品档案"""
        with open(data_file, "r", encoding="utf-8") as f:
            self.archives = json.load(f)
        self._build_index()
        return len(self.archives)

    def _build_index(self):
        """构建索引"""
        for arch in self.archives:
            name = arch.get("药品通用名称", "")
            if not name:
                continue

            # 精确索引
            self.exact_index[name] = arch

            # 归一化索引
            norm, high_conf, _ = normalize_drug_name(name)
            if norm and high_conf:
                if norm not in self.normalized_index:
                    self.normalized_index[norm] = []
                self.normalized_index[norm].append(arch)

            # 剂型变体索引（多剂型合并档案的所有变体名）
            variants = arch.get("剂型变体", [])
            for v in variants:
                if v and v != name:
                    self.alias_index[v] = arch

    def search(self, query):
        """
        检索药品
        返回 (archive, match_type, confidence)
        match_type: exact / normalized / alias / not_found
        """
        query = query.strip()
        if not query:
            return None, "empty", 0

        # 1. 精确匹配
        if query in self.exact_index:
            return self.exact_index[query], "exact", 1.0

        # 2. 别名匹配（剂型变体）
        if query in self.alias_index:
            return self.alias_index[query], "alias", 0.95

        # 3. 归一化匹配
        norm, high_conf, _ = normalize_drug_name(query)
        if norm and high_conf and norm in self.normalized_index:
            candidates = self.normalized_index[norm]
            # 优先选择含查询词的档案
            for c in candidates:
                if query in c.get("药品通用名称", ""):
                    return c, "normalized", 0.9
            return candidates[0], "normalized", 0.85

        # 4. 归一化精确名匹配（查询本身就是通用名）
        if norm and norm in self.exact_index:
            return self.exact_index[norm], "normalized_exact", 0.8

        # 5. 未命中
        return None, "not_found", 0

    def get_suggestions(self, query, limit=5):
        """未命中时给出可能的别名建议"""
        norm, _, _ = normalize_drug_name(query)
        suggestions = []

        # 从归一化索引中找包含查询词的
        if norm:
            for key, archives in self.normalized_index.items():
                if norm in key or key in norm:
                    for a in archives[:2]:
                        name = a.get("药品通用名称", "")
                        if name not in suggestions:
                            suggestions.append(name)
                            if len(suggestions) >= limit:
                                return suggestions

        # 从精确索引中找包含查询词的
        for name in self.exact_index:
            if query in name or name in query:
                if name not in suggestions:
                    suggestions.append(name)
                    if len(suggestions) >= limit:
                        break

        return suggestions


# ============================================================
# 副路由触发词
# ============================================================
SUBROUTINE_TRIGGERS = {
    "emotion": {
        "keywords": ["情绪", "心情不好", "不开心", "焦虑", "紧张", "压力大", "烦躁",
                     "抑郁", "情绪低落", "心烦", "生气", "愤怒", "委屈", "孤独"],
        "description": "情绪识别与调节技巧（浅层，非心理诊断）",
    },
    "sleep": {
        "keywords": ["失眠", "睡不着", "睡眠差", "入睡困难", "多梦", "易醒",
                     "睡眠卫生", "作息不规律"],
        "description": "睡眠卫生与作息调整建议（浅层，非医疗干预）",
    },
    "stress": {
        "keywords": ["压力", "减压", "放松", " burnout", "疲惫", "心累",
                     "工作压力", "学习压力"],
        "description": "压力管理与减压工具箱（浅层）",
    },
    "tcm_health": {
        "keywords": ["养生", "食疗", "体质", "中医养生", "四季养生", "药食同源",
                     "调理", "补气血", "祛湿", "上火", "脾胃"],
        "description": "中医科普与食疗常识（浅层，非诊疗）",
    },
    "mindfulness": {
        "keywords": ["正念", "冥想", "呼吸练习", "身体扫描", "静心", "放空",
                     "冥想引导", "正念练习"],
        "description": "正念/冥想入门引导（放松练习，非医疗干预）",
    },
    "subhealth": {
        "keywords": ["亚健康", "疲劳", "没精神", "乏力", "头晕", "眼干", "眼疲劳",
                     "维生素", "营养补充", "免疫力"],
        "description": "亚健康与营养保健科普（浅层）",
    },
}


def detect_subroutine(query):
    """检测副路由触发词，返回 (route_name, matched_keyword) 或 None"""
    query_lower = query.lower()
    for route_name, config in SUBROUTINE_TRIGGERS.items():
        for kw in config["keywords"]:
            if kw in query_lower:
                return route_name, kw
    return None, None
