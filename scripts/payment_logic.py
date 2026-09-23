#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FC 后端客户端（v2.1.0 免费模式）

v2.1.0 起技能改为免费：主流程直接调用 /archive 获取完整档案，无付费墙、无次数限制。
付费相关方法（probe / complete / bind_email / migrate / A2M 协议状态机）**保留但主流程不再使用**，
作为历史方案参考（详见项目根 PAYMENT_LOGIC.md），并兼容已购买断用户的存量调用。

架构：
  技能包（本地壳：检索索引 + FC 客户端）→ FC 后端（完整档案下发）
"""
import json
import os
import re
import time
import uuid
import hashlib
import logging
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


# ============================================================
# 设备指纹（用户唯一标识 · 每次现算，不落盘）
# 约定：买断权益绑定设备指纹；同一设备每次调用 open_id 相同；
#       换设备后指纹不同 → FC 校验不匹配 → 引导「迁移权益」。
# ============================================================
def get_device_fp() -> str:
    """现算本机设备指纹（MachineGuid + C 盘卷序列号 → sha256）。
    优先系统级稳定标识；无权限/非 Windows 环境回退为本地持久化随机号。"""
    parts = []
    # 1. Windows 注册表 MachineGuid（机器级唯一标识，重装系统会变——由邮箱迁移兜底）
    try:
        out = subprocess_run(["reg", "query",
                              r"HKLM\SOFTWARE\Microsoft\Cryptography",
                              "/v", "MachineGuid"])
        m = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", out)
        if m:
            parts.append("guid:" + m.group(0).lower())
    except Exception:
        pass
    # 2. C 盘卷序列号（文件系统级，无需管理员权限）
    try:
        out = subprocess_run(["vol", "C:"])
        m = re.search(r"[0-9A-F]{4}-[0-9A-F]{4}", out)
        if m:
            parts.append("vol:" + m.group(0).lower())
    except Exception:
        pass

    if parts:
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:40]

    # 兜底：随机设备号落盘（非标准环境；复制文件夹到新设备将生成新号 → 权益不转移）
    fallback_dir = os.path.join(os.path.expanduser("~"), ".drug-helper")
    fallback_file = os.path.join(fallback_dir, "device.json")
    try:
        os.makedirs(fallback_dir, exist_ok=True)
        if os.path.exists(fallback_file):
            with open(fallback_file, "r", encoding="utf-8") as f:
                return json.load(f)["device_id"]
        device_id = uuid.uuid4().hex
        with open(fallback_file, "w", encoding="utf-8") as f:
            json.dump({"device_id": device_id}, f)
        return device_id
    except Exception:
        return "dev_" + uuid.uuid4().hex[:16]


def subprocess_run(args: list) -> str:
    """执行系统命令并返回 stdout（超时保护）"""
    import subprocess
    result = subprocess.run(args, capture_output=True, text=True, timeout=5)
    return result.stdout or ""


# ============================================================
# 配置
# ============================================================
PAYMENT_CONFIG = {
    "free_quota": 3,           # 每用户免费完整档案次数（FC 后端控制）
    "per_query_price": 0.01,   # 按次付费价格（元，测试价，验证后改回 0.99）
    "buyout_price": 9.9,       # 买断价格（元，真买断永久权益，无年费）
    "currency": "CNY",
    "pay_channel": "alipay",   # 支付宝 SkillPay / AI 付（唯一收款渠道）
}

# FC 后端地址（已部署到阿里云 FC 3.0，公网 URL）
FC_BACKEND_URL = os.environ.get(
    "FC_BACKEND_URL",
    "https://drug-helper-tciuozgdun.cn-hangzhou.fcapp.run"
)


# ============================================================
# 支付状态枚举
# ============================================================
class PaymentStatus(Enum):
    FREE = "free"                    # 免费额度内
    REQUIRES_PAYMENT = "requires_payment"  # 需要付费（返回402）
    PAID = "paid"                    # 已支付（单次）
    BUYOUT = "buyout"                # 已买断
    ACCESS_DENIED = "access_denied"  # 无权限


# ============================================================
# FC 后端 HTTP 客户端
# ============================================================
class FCBackendClient:
    """FC 后端 HTTP 客户端（调用 /pay/probe, /pay/complete, /archive）"""

    def __init__(self, base_url: str = None, timeout: int = 10):
        self.base_url = (base_url or FC_BACKEND_URL).rstrip("/")
        self.timeout = timeout
        self._device_fp = get_device_fp()  # 每次启动现算设备指纹

    def _post(self, path: str, data: Dict) -> Dict:
        """发送 POST 请求到 FC 后端（带设备指纹头）"""
        try:
            import requests
            url = f"{self.base_url}{path}"
            headers = {"X-Device-Id": self._device_fp}
            resp = requests.post(url, json=data, headers=headers, timeout=self.timeout)
            return resp.json()
        except ImportError:
            logger.error("requests 库未安装，无法调用 FC 后端")
            return {"error": "requests_not_installed"}
        except Exception as e:
            logger.error("FC 后端调用失败 %s", path)
            return {"error": "network_error", "message": str(e)}

    # ---- 公开 API ----
    def probe(self, open_id: str, query_key: str = "") -> Dict:
        """探测用户付费状态"""
        return self._post("/pay/probe", {"open_id": open_id, "query_key": query_key})

    def complete(self, open_id: str, payment_proof_header: str,
                 out_trade_no: str = "", query_key: str = "",
                 buyout: bool = False) -> Dict:
        """支付完成（FC 后端验签+履约+记账）"""
        return self._post("/pay/complete", {
            "open_id": open_id,
            "payment_proof_header": payment_proof_header,
            "out_trade_no": out_trade_no,
            "query_key": query_key,
            "buyout": buyout,
        })

    def get_archive(self, drug_name: str, open_id: str,
                    layer: str = "paid", access_token: str = "") -> Dict:
        """获取药品档案（FC 后端校验权限后下发）"""
        return self._post("/archive", {
            "drug_name": drug_name,
            "open_id": open_id,
            "layer": layer,
            "access_token": access_token,
        })

    def bind_email(self, open_id: str, email: str) -> Dict:
        """绑定邮箱（买断权益迁移的账户锚点）"""
        return self._post("/api/bind-email", {"open_id": open_id, "email": email})

    def migrate(self, email: str, trade_no: str) -> Dict:
        """迁移买断权益到本设备（终身限一次；邮箱 + 支付宝订单号双因子）"""
        return self._post("/api/migrate", {
            "email": email,
            "trade_no": trade_no,
            "device_fp": self._device_fp,
        })


# ============================================================
# 客户端付费逻辑（封装 FC 调用）
# ============================================================
class PaymentClient:
    """
    客户端付费逻辑（本地壳视角）

    流程：
    1. probe() → 检查免费额度/买断/是否需付费
    2. 如需付费 → 返回 402 账单（Payment-Needed header），引导用户支付
    3. 用户支付后 → complete() 提交 Payment-Proof，FC 后端验签+记账
    4. get_archive() → 获取完整档案（FC 后端校验权限后下发）
    """

    def __init__(self, fc_url: str = None):
        self.fc = FCBackendClient(fc_url)

    def probe(self, open_id: str, query_key: str = "") -> Dict:
        """探测用户是否需要付费"""
        result = self.fc.probe(open_id, query_key)
        status = result.get("status", "error")

        if status == "buyout":
            return {"status": PaymentStatus.BUYOUT, "result": result}
        elif status == "free":
            return {"status": PaymentStatus.FREE, "result": result}
        elif status == "paid":
            return {"status": PaymentStatus.PAID, "result": result}
        elif status == "requires_payment":
            return {"status": PaymentStatus.REQUIRES_PAYMENT, "result": result}
        else:
            return {"status": PaymentStatus.ACCESS_DENIED, "result": result}

    def complete_payment(self, open_id: str, payment_proof_header: str,
                         out_trade_no: str = "", query_key: str = "",
                         buyout: bool = False) -> Dict:
        """完成支付（提交 Payment-Proof 给 FC 后端验签）"""
        return self.fc.complete(open_id, payment_proof_header,
                                out_trade_no, query_key, buyout)

    def get_paid_archive(self, drug_name: str, open_id: str,
                         access_token: str = "") -> Optional[Dict]:
        """获取完整档案（v2.1.0 免费模式：直接返回完整档案，无付费墙）。
        方法名保留历史命名，语义即"获取完整档案"。"""
        result = self.fc.get_archive(drug_name, open_id, "paid", access_token)
        if result.get("status") == "ok":
            return result.get("archive")
        _err = result.get("error") if isinstance(result.get("error"), str) else "backend_error"
        logger.warning("获取完整档案失败: %s", _err)
        return None

    def get_buy_links(self, drug_name: str, open_id: str) -> Optional[Dict]:
        """获取购买参考链接（合规：明示推广属性）。

        - FC 后端 /api/buy-links 返回真转链结果（凭证在服务端）；
        - 后端未配置/失败时返回 None → 客户端降级为公开搜索链接（buy_link_helper）。
        """
        try:
            result = self.fc._post("/api/buy-links", {
                "drug_name": drug_name, "open_id": open_id,
            })
        except Exception:
            logger.warning("获取购买链接失败")
            return None
        if result and result.get("ok"):
            return result
        return None

    def get_free_archive(self, drug_name: str, open_id: str) -> Optional[Dict]:
        """获取免费层档案（兼容保留；当前免费层即付费墙引导）"""
        result = self.fc.get_archive(drug_name, open_id, "free")
        if result.get("status") == "ok":
            return result.get("archive")
        return None

    def consume_free(self, open_id: str) -> bool:
        """
        免费额度扣减（在 FC 后端完成，客户端仅记录）
        注意：实际扣减在 FC 后端 /archive 接口或 probe 时完成
        """
        return True  # FC 后端自动管理

    def bind_email(self, open_id: str, email: str) -> Dict:
        """绑定邮箱到当前设备权益"""
        return self.fc.bind_email(open_id, email)

    def migrate(self, email: str, trade_no: str) -> Dict:
        """迁移买断权益到本设备（邮箱 + 支付宝订单号）"""
        return self.fc.migrate(email, trade_no)

    def get_device_fp(self) -> str:
        """当前设备指纹（用户唯一标识）"""
        return self.fc._device_fp

    def get_payment_prompt(self, probe_result: Dict) -> str:
        """生成未付费引导话术"""
        result = probe_result.get("result", probe_result)
        free_remaining = result.get("free_remaining", 0)

        if free_remaining > 0:
            return (
                f"您还有 {free_remaining} 次免费完整档案查询机会。\n"
                f"完整档案（功能主治/用法用量/禁忌/不良反应/就医指引）需付费查看：\n"
                f"  • 按次 ¥{PAYMENT_CONFIG['per_query_price']}"
            )
        else:
            return (
                "免费完整档案额度已用完。\n"
                f"完整档案（功能主治/用法用量/禁忌/不良反应/就医指引）需付费查看：\n"
                f"  • 按次 ¥{PAYMENT_CONFIG['per_query_price']}"
            )


# ============================================================
# A2M 402 协议状态机（客户端视角说明）
# ============================================================
class A2MProtocol:
    """
    支付宝 A2M HTTP 402 协议状态机（客户端视角）

    完整流程（FC 后端执行验签和记账）：
      1. probe     → 客户端调用 FC /pay/probe，检查额度/买断
      2. 402       → FC 返回 Payment-Needed header（Base64URL 账单）
      3. pay       → 官方 alipay-bot 拉起收银，用户完成支付宝支付
      4. complete  → 客户端携带 Payment-Proof 调用 FC /pay/complete
                     FC 后端调用 alipay.aipay.agent.payment.verify 验签
                     → 校验 active/amount/out_trade_no/resource_id
                     → 调用 alipay.aipay.agent.fulfillment.confirm 履约回执
                     → Tablestore 记账（按次/买断）
      5. archive   → 客户端调用 FC /archive 获取完整档案

    参考：https://aipay.alipay.com/docs/ai-receive/MACHINE_PAY.md
    """

    @staticmethod
    def get_flow_description() -> str:
        return """
支付宝 A2M HTTP 402 支付流程（方案② FC+Tablestore）：
1. probe：客户端调用 FC /pay/probe，检查免费额度/买断状态
2. 402：如需付费，FC 返回 HTTP 402 + Payment-Needed header（RSA2 签名账单）
3. pay：官方 alipay-bot 拉起支付宝收银，用户完成支付
4. complete：客户端携带 Payment-Proof 调用 FC /pay/complete
   - FC 后端调用 alipay.aipay.agent.payment.verify 验签
   - 校验 active=true、金额、订单号、资源ID
   - 调用 alipay.aipay.agent.fulfillment.confirm 履约回执
   - Tablestore 记账（按次写 paid_queries，买断写 buyout）
5. archive：客户端调用 FC /archive，FC 校验权限后下发完整档案
"""
