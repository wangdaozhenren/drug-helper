#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用药助手（drug-helper）- 主入口
架构：本地壳（检索索引+免费层+FC客户端）→ FC 后端（验签+状态+完整档案）
整合：检索匹配 + 输出模板 + 付费客户端 + 副路由
"""
import os
import re
import sys
import json
import time

# 模块路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from drug_index import DrugIndex, normalize_drug_name, detect_subroutine
from output_templates import (
    render_paid_layer, render_not_found,
    render_subroutine, DISCLAIMER_BRIEF, DATA_VERSION, DATA_VERIFY_DATE,
)
from payment_logic import PaymentClient, FC_BACKEND_URL


# ============================================================
# 技能配置
# ============================================================
SKILL_CONFIG = {
    "name": "drug-helper",
    "display_name": "用药助手",
    "version": "2.1.0",
    "architecture": "client-shell + fc-backend",
    "data_version": DATA_VERSION,
    "data_verify_date": DATA_VERIFY_DATE,
    "description": "用药助手：整合国家药品监督管理局（NMPA）批准信息、国家医保药品目录（2025版）、《中华人民共和国药典》（2025年版）三源权威数据，提供15,898种药品档案查询与用药科普。覆盖阿司匹林、布洛芬、阿莫西林、头孢、高血压、糖尿病、感冒、咳嗽、胃痛、失眠等常见药品与症状。免费提供完整档案（功能主治/适应症、用法用量、禁忌、不良反应、就医指引、购药入口）。架构为本地壳+FC后端。",
}


class DrugHelperSkill:
    """用药助手技能主类（客户端壳）"""

    def __init__(self, data_file: str = None, fc_url: str = None):
        self.index = DrugIndex()
        self.payment = PaymentClient(fc_url)
        self.data_file = data_file or os.path.join(
            os.path.dirname(SCRIPT_DIR), "data", "drug_archive_index.json"
        )
        self._loaded = False

    def load_data(self):
        """加载药品检索索引（本地，用于路由判断和免费层）"""
        if os.path.exists(self.data_file):
            count = self.index.load(self.data_file)
            self._loaded = True
            return count
        return 0

    def query(self, user_query: str, open_id: str = None,
              force_paid: bool = False) -> dict:
        """
        主查询入口

        Args:
            user_query: 用户查询（药名/病名/症状/账户指令等）
            open_id: 用户唯一标识（默认取当前设备指纹；FC 后端存储）
            force_paid: 是否强制返回付费层内容（测试用）

        Returns:
            dict: {route, layer, content, payment}
        """
        query = user_query.strip()
        if not query:
            return {
                "route": "empty",
                "layer": "none",
                "content": "请输入药品名称、症状描述，或账户指令（绑定邮箱 / 迁移权益）。",
                "payment": None,
            }

        # 0. 账户指令识别（绑定邮箱 / 迁移权益）
        handled, account_content = self.handle_account_command(query)
        if handled:
            return {
                "route": "account",
                "layer": "none",
                "content": account_content,
                "payment": None,
            }
        if self.handle_account_command_hint(query):
            return {
                "route": "account",
                "layer": "none",
                "content": (
                    "账户指令格式：\n"
                    "  • 绑定邮箱：发送「绑定邮箱 你的邮箱@xxx.com」\n"
                    "  • 迁移权益：在新设备发送「迁移权益 邮箱 你的邮箱@xxx.com 订单号 <支付宝订单号>」（终身限一次）\n"
                    "订单号可在支付宝 App → 账单 → 对应交易详情中查询。"
                ),
                "payment": None,
            }

        # 默认用户标识 = 当前设备指纹（每次现算，不落盘）
        if open_id is None:
            open_id = self.payment.get_device_fp()

        # 1. 副路由检测（心理/养生/正念等浅层科普，免费）
        route_name, matched_kw = detect_subroutine(query)
        if route_name:
            content = render_subroutine(route_name)
            return {
                "route": "subroutine",
                "subroute": route_name,
                "matched_keyword": matched_kw,
                "layer": "free",
                "content": content,
                "payment": None,
            }

        # 2. 药品检索（本地索引）
        archive, match_type, confidence = self.index.search(query)

        if archive is None:
            suggestions = self.index.get_suggestions(query)
            content = render_not_found(query, suggestions)
            return {
                "route": "not_found",
                "layer": "none",
                "content": content,
                "payment": None,
            }

        # 3. 获取完整档案（v2.1.0 免费模式：直接请求 FC 后端，无付费墙/无次数限制）
        drug_name = archive.get("药品通用名称", "")
        full_archive = self.payment.get_paid_archive(drug_name, open_id)
        buy_links = self.payment.get_buy_links(drug_name, open_id)
        if full_archive:
            content = render_paid_layer(full_archive, match_type, buy_links_raw=buy_links)
            layer = "free"
        else:
            # FC 获取失败，降级用本地索引渲染（标注可能不完整）
            content = render_paid_layer(archive, match_type, buy_links_raw=buy_links)
            content += "\n\n*⚠️ 服务端档案获取失败，以上为本地索引数据，可能不完整。请稍后重试。*"
            layer = "free_local_fallback"
        return {
            "route": "drug",
            "layer": layer,
            "match_type": match_type,
            "confidence": confidence,
            "drug_name": drug_name,
            "content": content,
            "payment": {
                "status": "free",
                "message": "免费使用（完整档案）",
            },
        }

    def handle_account_command(self, query: str) -> tuple:
        """
        账户指令识别与执行：
          「绑定邮箱 xxx@yyy.com」→ 绑定邮箱到当前设备权益（买断迁移锚点）
          「迁移权益 邮箱 xxx@yyy.com 订单号 <支付宝订单号>」→ 终身一次迁移

        Returns: (handled: bool, content: str)
        """
        q = query.lower()
        open_id = self.payment.get_device_fp()

        # ---- 绑定邮箱 ----
        m = re.search(r"绑定邮箱[^\w@]*([\w.+-]+@[\w-]+\.[\w.]+)", q)
        if m:
            email = m.group(1).lower()
            result = self.payment.bind_email(open_id, email)
            if result.get("status") == "ok":
                return True, (
                    f"邮箱绑定成功：{email}\n\n"
                    f"说明：买断权益绑定在当前设备。如需更换设备，请在新设备发送"
                    f"「迁移权益 邮箱 {email} 订单号 <支付宝订单号>」完成迁移（终身限一次）。\n"
                    f"订单号可在支付宝 App → 账单 → 对应交易详情中查询。"
                )
            return True, f"邮箱绑定失败：{result.get('error', '未知错误')}"

        # ---- 迁移权益 ----
        m = re.search(r"迁移权益.*?([\w.+-]+@[\w-]+\.[\w.]+)", q)
        if m:
            email = m.group(1).lower()
            rest = q[m.end():]
            # 支付宝订单号为 12+ 位数字/字母混合串
            tokens = re.findall(r"[a-z0-9]{12,}", rest)
            if not tokens:
                return True, (
                    f"未识别到支付宝订单号。请按格式发送：\n"
                    f"迁移权益 邮箱 {email} 订单号 <支付宝账单中的订单号>\n"
                    f"（订单号在支付宝 App → 账单 → 该笔交易详情中，一长串数字）"
                )
            trade_no = tokens[-1]
            result = self.payment.migrate(email, trade_no)
            if result.get("status") == "ok":
                return True, (
                    f"买断权益迁移成功！\n新设备已生效，权益永久有效。\n"
                    f"原设备权益已失效（终身仅限一次迁移）。"
                )
            return True, f"迁移失败：{result.get('error', '未知错误')}"

        return False, ""

    def handle_account_command_hint(self, query: str) -> bool:
        """检测账户指令关键词但格式不完整时返回 True（给引导）"""
        q = query.lower()
        return ("绑定邮箱" in q) or ("迁移权益" in q)


# ============================================================
# 命令行入口（测试用）
# ============================================================
def main():
    """命令行测试入口"""
    if len(sys.argv) < 2:
        print("用法: python skill_main.py <药品名或查询> [open_id]")
        print("示例: python skill_main.py 阿司匹林")
        print("      python skill_main.py 布洛芬 demo_user")
        return

    query = sys.argv[1]
    open_id = sys.argv[2] if len(sys.argv) > 2 else None

    skill = DrugHelperSkill()
    count = skill.load_data()
    if count == 0:
        print(f"警告：未加载到数据（{skill.data_file}），请先运行 build_index.py")
    else:
        print(f"已加载 {count} 条药品索引\n")

    result = skill.query(query, open_id)
    if result.get("route") == "account":
        print(result["content"])
        return

    print(f"路由: {result['route']}")
    print(f"层级: {result['layer']}")
    if result.get("match_type"):
        print(f"匹配方式: {result['match_type']}")
    print("-" * 60)
    print(result["content"])
    print("-" * 60)
    if result.get("payment"):
        print(f"付费状态: {result['payment'].get('status')}")
        if result["payment"].get("payment_prompt"):
            print(result["payment"]["payment_prompt"])


if __name__ == "__main__":
    main()
