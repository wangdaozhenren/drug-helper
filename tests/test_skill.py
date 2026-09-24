#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用药助手（drug-helper）本地测试脚本（离线）
验证：路由正确、输出合规、免费模式（v2.1.0 无付费墙）、归一化规则
说明：不调用真实 FC 后端；免费模式用内存 stub 客户端（非生产代码）
"""
import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))

from skill_main import DrugHelperSkill
from drug_index import normalize_drug_name, detect_subroutine
from payment_logic import PaymentClient, PaymentStatus, FC_BACKEND_URL


# ============================================================
# 内存 stub FC 客户端（仅测试用；不进入生产技能包路径）
# ============================================================
class StubFCClient:
    """内存状态 stub：模拟 FC 后端免费模式（v2.1.0：所有查询直接返回完整档案）"""
    def __init__(self):
        self._store = {}
        self._device_fp = "stub_device_fp"

    def _get(self, open_id):
        if open_id not in self._store:
            self._store[open_id] = {"free_used": 0, "paid_queries": []}
        return self._store[open_id]

    def probe(self, open_id, query_key=""):
        # 免费模式下 probe 保留兼容，直接返回 free（主流程不再调用）
        return {"status": "free", "free_remaining": 999,
                "message": "免费使用（完整档案）"}

    def complete(self, open_id, payment_proof_header="", out_trade_no="",
                 query_key="", buyout=False):
        return {"status": "error", "error": "stub 不支持真实支付"}  # 测试不触发支付

    def get_archive(self, drug_name, open_id, layer="paid", access_token=""):
        # 从本地索引文件读取（离线）；免费模式：直接返回完整档案
        index_file = os.path.join(SKILL_DIR, "data", "drug_archive_index.json")
        if not os.path.exists(index_file):
            return {"error": "index_not_found"}
        with open(index_file, "r", encoding="utf-8") as f:
            archives = json.load(f)
        for arch in archives:
            if arch.get("药品通用名称") == drug_name:
                return {"status": "ok", "layer": "paid", "drug_name": drug_name,
                        "archive": arch, "data_version": "2026.09.21-v1",
                        "access_reason": "free"}
        return {"error": "not_found", "drug_name": drug_name}

    def get_buy_links(self, drug_name, open_id):
        return None  # 客户端降级公开搜索

    def get_device_fp(self):
        return self._device_fp

    def bind_email(self, open_id, email):
        return {"status": "ok", "message": "绑定成功"}

    def migrate(self, email, trade_no):
        return {"status": "error", "error": "stub 不支持迁移"}


# ============================================================
# 测试用例
# ============================================================
TEST_CASES = [
    {
        "id": 1,
        "name": "药名精确匹配（阿司匹林）",
        "query": "阿司匹林",
        "expect_route": "drug",
        "expect_match_type": "exact",
    },
    {
        "id": 2,
        "name": "剂型变体匹配（布洛芬分散片）",
        "query": "布洛芬分散片",
        "expect_route": "drug",
        "expect_match_type_any": ["alias", "normalized"],
        "expect_drug_name": "布洛芬",
    },
    {
        "id": 3,
        "name": "注射用前缀匹配（注射用阿奇霉素）",
        "query": "注射用阿奇霉素",
        "expect_route": "drug",
        "expect_match_type_any": ["normalized", "alias", "exact"],
        "expect_drug_name_contains": "阿奇霉素",
    },
    {
        "id": 4,
        "name": "盐类前缀保留（盐酸氨溴索）",
        "query": "盐酸氨溴索",
        "expect_route": "drug",
        "expect_drug_name_contains": "氨溴索",
        "expect_normalized_contains": "盐酸",
    },
    {
        "id": 5,
        "name": "中成药匹配（板蓝根颗粒）",
        "query": "板蓝根颗粒",
        "expect_route": "drug",
        "expect_drug_name_contains": "板蓝根",
    },
    {
        "id": 6,
        "name": "未命中兜底（不存在的药名）",
        "query": "不存在的药品XYZ123",
        "expect_route": "not_found",
    },
    {
        "id": 7,
        "name": "副路由-情绪词（心情不好）",
        "query": "最近心情不好，很焦虑",
        "expect_route": "subroutine",
        "expect_subroute": "emotion",
    },
    {
        "id": 8,
        "name": "副路由-睡眠词（失眠）",
        "query": "晚上总是失眠怎么办",
        "expect_route": "subroutine",
        "expect_subroute": "sleep",
    },
    {
        "id": 9,
        "name": "副路由-正念词（冥想引导）",
        "query": "想做正念冥想，求引导",
        "expect_route": "subroutine",
        "expect_subroute": "mindfulness",
    },
]


def run_tests():
    """运行所有测试用例（离线，不调用真实 FC）"""
    print("=" * 70)
    print("用药助手（drug-helper）- 离线本地测试")
    print(f"FC_BACKEND_URL: {FC_BACKEND_URL}")
    print("=" * 70)

    skill = DrugHelperSkill()
    count = skill.load_data()
    print(f"\n已加载药品索引: {count} 条")
    print(f"数据文件: {skill.data_file}")
    print()

    passed = 0
    failed = 0
    results = []

    for case in TEST_CASES:
        print(f"--- 用例 {case['id']}: {case['name']} ---")
        print(f"  查询: {case['query']}")

        open_id = f"test_user_{case['id']}"
        result = skill.query(case["query"], open_id)

        route = result.get("route", "")
        layer = result.get("layer", "")
        match_type = result.get("match_type", "")
        drug_name = result.get("drug_name", "")
        subroute = result.get("subroute", "")
        content = result.get("content", "")

        print(f"  路由: {route}, 层级: {layer}, 匹配: {match_type}")
        if drug_name:
            print(f"  药品: {drug_name}")
        if subroute:
            print(f"  副路由: {subroute}")

        case_passed = True
        errors = []

        # 路由验证
        if "expect_route" in case:
            if route != case["expect_route"]:
                case_passed = False
                errors.append(f"路由期望 {case['expect_route']}, 实际 {route}")

        # 匹配类型验证
        if "expect_match_type" in case:
            if match_type != case["expect_match_type"]:
                case_passed = False
                errors.append(f"匹配类型期望 {case['expect_match_type']}, 实际 {match_type}")

        if "expect_match_type_any" in case:
            if match_type not in case["expect_match_type_any"]:
                case_passed = False
                errors.append(f"匹配类型期望任一 {case['expect_match_type_any']}, 实际 {match_type}")

        # 药品名验证
        if "expect_drug_name" in case:
            if drug_name != case["expect_drug_name"]:
                case_passed = False
                errors.append(f"药品名期望 {case['expect_drug_name']}, 实际 {drug_name}")

        if "expect_drug_name_contains" in case:
            if case["expect_drug_name_contains"] not in drug_name:
                case_passed = False
                errors.append(f"药品名应包含 {case['expect_drug_name_contains']}, 实际 {drug_name}")

        # 副路由验证
        if "expect_subroute" in case:
            if subroute != case["expect_subroute"]:
                case_passed = False
                errors.append(f"副路由期望 {case['expect_subroute']}, 实际 {subroute}")

        # 归一化验证
        if "expect_normalized_contains" in case:
            norm, _, _ = normalize_drug_name(case["query"])
            if case["expect_normalized_contains"] not in norm:
                case_passed = False
                errors.append(f"归一化后应包含 {case['expect_normalized_contains']}, 实际 {norm}")

        # 合规验证
        if content and route != "empty":
            if "免责" not in content and "仅供" not in content and "科普" not in content:
                case_passed = False
                errors.append("输出缺少免责声明/科普提示")

        content_preview = content[:150].replace("\n", " ")
        print(f"  内容预览: {content_preview}...")

        if case_passed:
            print(f"  ✅ 通过")
            passed += 1
        else:
            print(f"  ❌ 失败: {'; '.join(errors)}")
            failed += 1

        results.append({"id": case["id"], "name": case["name"], "passed": case_passed, "errors": errors})
        print()

    # ============================================================
    # 免费模式测试（v2.1.0：无付费墙，所有查询直接返回完整档案）
    # ============================================================
    print("=" * 70)
    print("免费模式测试（v2.1.0 无付费墙，stub FC，不触发真实支付）")
    print("=" * 70)

    skill2 = DrugHelperSkill()
    skill2.load_data()
    skill2.payment = PaymentClient()
    skill2.payment.fc = StubFCClient()  # 替换为内存 stub

    # 多次连续查询（超过旧版 3 次免费额度）仍全部返回完整档案
    layer_seq = []
    for i in range(1, 6):
        r = skill2.query("布洛芬", "free_test_user")
        layer_seq.append(r["layer"])
        c = r.get("content", "")
        has_clinical = "临床信息" in c
        print(f"  第{i}次: 层级={r['layer']}, 状态={r.get('payment',{}).get('status')}, 含临床信息={has_clinical}")
    ok_free = all(l == "free" for l in layer_seq)
    print(f"  {'✅' if ok_free else '❌'} 连续5次均为 free（完整档案，无付费墙）: {layer_seq}")
    passed += 1 if ok_free else 0
    failed += 0 if ok_free else 1

    # 换药同样免费完整档案
    r_other = skill2.query("阿莫西林", "free_test_user")
    c_other = r_other.get("content", "")
    ok_other = (r_other["layer"] == "free" and "临床信息" in c_other)
    print(f"  {'✅' if ok_other else '❌'} 其他药同样免费完整档案: 层级={r_other['layer']}")
    passed += 1 if ok_other else 0
    failed += 0 if ok_other else 1

    # 无付费墙字样（不含"付费解锁/免费次数已用尽"）
    c_all = " ".join(layer_seq)
    ok_nopaywall = "付费" not in (skill2.query("布洛芬", "free_test_user").get("content", "") +
                                  skill2.query("阿莫西林", "free_test_user").get("content", ""))
    print(f"  {'✅' if ok_nopaywall else '❌'} 输出中不含付费墙引导文案")
    passed += 1 if ok_nopaywall else 0
    failed += 0 if ok_nopaywall else 1

    # 购药链接存在
    r_fresh = skill2.query("布洛芬", "fresh_free_user")
    has_link = "京东大药房" in r_fresh.get("content", "")
    print(f"  {'✅' if has_link else '❌'} 含购药链接（京东）")
    passed += 1 if has_link else 0
    failed += 0 if has_link else 1

    print()

    # ============================================================
    # 归一化规则测试
    # ============================================================
    print("=" * 70)
    print("归一化规则测试")
    print("=" * 70)
    norm_cases = [
        ("布洛芬分散片", "布洛芬", True),
        ("注射用阿奇霉素", "阿奇霉素", True),
        ("盐酸氨溴索", "盐酸氨溴索", True),
        ("硫酸庆大霉素注射液", "硫酸庆大霉素", True),
        ("阿司匹林", "阿司匹林", False),
    ]
    for query, expected_norm, expected_conf in norm_cases:
        norm, high_conf, _ = normalize_drug_name(query)
        status = "✅" if norm == expected_norm else "❌"
        print(f"  {status} {query} → {norm} (高置信度={high_conf}, 期望={expected_conf})")
        if norm == expected_norm:
            passed += 1
        else:
            failed += 1
    print()

    # ============================================================
    # 总结
    # ============================================================
    print("=" * 70)
    print(f"测试总结: {passed} 通过, {failed} 失败, 共 {passed+failed} 项")
    print("=" * 70)

    # 输出样例
    print("\n=== 输出样例 ===")
    print("\n【样例1：阿司匹林】")
    sample1 = skill.query("阿司匹林", "sample_user_1")
    print(sample1["content"][:400])
    print("\n...\n")

    print("\n【样例2：心情不好（副路由-情绪调节）】")
    sample2 = skill.query("最近心情不好，很焦虑", "sample_user_2")
    print(sample2["content"][:400])
    print("\n...\n")

    print("\n【样例3：不存在的药品（未命中兜底）】")
    sample3 = skill.query("不存在的药品XYZ123", "sample_user_3")
    print(sample3["content"][:400])

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
