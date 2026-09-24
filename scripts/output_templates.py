#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出模板模块（v2.1.0 免费模式）：完整档案直出
render_free_layer（历史付费墙模板）保留仅作文档参考，主流程不再调用。
合规组件：免责声明固定尾注
"""
from datetime import datetime

# 数据版本号
DATA_VERSION = "2026.09.22-v1"
DATA_VERIFY_DATE = "2026-09-22"

# 购买参考区块（合规：明示推广属性；无凭证时降级公开搜索链接）
try:
    from buy_link_helper import render_buy_section as _render_buy_section
    from buy_link_helper import render_otc_inline as _render_otc_inline
except ImportError:
    def _render_buy_section(drug_name, backend_raw=None):
        return ""
    def _render_otc_inline(drug_name):
        return ""

# ============================================================
# 免责声明模板
# ============================================================
DISCLAIMER_FULL = """
---
⚠️ **免责声明**
本信息仅供健康科普参考，**不构成诊断、治疗建议或处方**，不能替代执业医师/药师的专业判断。
- 处方药请凭医师处方使用，切勿自行用药或调整剂量。
- 如症状持续、加重或出现新的不适，请及时就医。
- 药品信息来源于国家药品监督管理局（NMPA）、国家医保药品目录（2025版）、《中华人民共和国药典》（2025年版）、小荷医典用药科普，数据核验日期：{verify_date}，数据版本：{version}。
- 药品标准与医保政策可能更新，请以最新官方信息和药品说明书为准。
""".strip()

DISCLAIMER_BRIEF = "⚠️ 仅供科普参考，不替代医嘱；处方药请遵医嘱。数据来源：NMPA/医保目录2025/中国药典2025/小荷医典，核验日期：{date}".format(date=DATA_VERIFY_DATE)


# ============================================================
# 处方药拦截话术（合规，按药监综药管函〔2023〕333号）
# 处方审核通过前不得向公众展示/发送处方药说明书、适应症、用法用量等信息，
# 因此对未命中 OTC 白名单的药品一律只返回此提示，不返回完整档案/购药入口。
# ============================================================
PRESCRIPTION_INTERCEPT = (
    "## 处方药提示\n\n"
    "本品为处方药，用药需要医生面诊开具处方，"
    "相关用药信息请咨询您的医师或执业药师，本工具不提供处方药用药资料与用药建议。\n\n"
    "如需用药指导，请携带病历与处方前往正规医疗机构或实体药店，由执业药师提供专业建议。\n"
)


def render_prescription_intercept(drug_name: str = "") -> str:
    """处方药拦截输出（不包含任何适应症/用法用量/禁忌/购药入口）"""
    lines = []
    if drug_name:
        lines.append(f"### {drug_name}")
        lines.append("")
    lines.append(PRESCRIPTION_INTERCEPT.strip())
    lines.append("")
    lines.append(DISCLAIMER_BRIEF)
    return "\n".join(lines)


# ============================================================
# 付费墙（免费次数用尽）输出 —— 历史模板（v2.1.0 免费化后不再使用，
# 保留仅供 PAYMENT_LOGIC.md 文档参考；主流程统一走 render_paid_layer）
# ============================================================
def render_free_layer(archive, match_type="exact"):
    """
    历史付费墙模板（v2.0.x）：仅显示药名 + 购药入口 + 付费引导 + 免责声明。
    v2.1.0 免费化后不再被主流程调用，保留作历史方案参考。
    """
    name = archive.get("药品通用名称", "未知药品")

    lines = []
    lines.append(f"## {name}")
    if match_type != "exact":
        lines.append(f"*匹配方式：{match_type}*")
    lines.append("")

    # 购药入口（全量版：所有药品均渲染；转链失败降级公开搜索）
    otc_inline = _render_otc_inline(name)
    if otc_inline:
        lines.append(otc_inline)
        lines.append("")

    # 付费墙引导
    lines.append("---")
    lines.append("🔒 **免费次数已用尽**：完整档案（功能主治/适应症、用法用量、禁忌、不良反应、"
                 "药物相互作用、就医指引等）需付费解锁。")
    lines.append(f"   按次 ¥0.01（测试价，支付宝 AI 按量付费）")
    lines.append("")

    # 免责声明
    lines.append(DISCLAIMER_BRIEF)

    return "\n".join(lines)


# ============================================================
# 完整档案输出（v2.1.0 免费模式主渲染）
# ============================================================
def render_paid_layer(archive, match_type="exact", buy_links_raw=None):
    """
    完整档案渲染（v2.1.0 免费直出）：基本信息 + 临床信息 + 就医指引 + 购药入口 + 来源标注 + 免责声明。
    方法名保留历史命名，语义即"完整档案渲染"。
    buy_links_raw: 可选，FC 后端 /api/buy-links 返回的原始 JSON（含转链结果）；
                   为 None 时降级为公开搜索链接（合规：明示推广属性）。
    """
    name = archive.get("药品通用名称", "未知药品")
    variants = archive.get("剂型变体", [])
    dosage_forms = archive.get("剂型", [])
    specs = archive.get("规格", [])
    approval_nums = archive.get("批准文号", [])
    holders = archive.get("上市许可持有人", [])
    yibao_category = archive.get("医保类别", "")
    yibao_note = archive.get("医保备注", "")

    # 药典字段
    func_indication = archive.get("药典功能主治", "") or archive.get("功能主治", "")
    indication = archive.get("适应症", "")
    usage = archive.get("药典用法用量", "") or archive.get("用法用量", "")
    contraindication = archive.get("药典禁忌", "") or archive.get("禁忌", "")
    adverse = archive.get("药典不良反应", "") or archive.get("不良反应", "")
    yd_category = archive.get("类别", "")
    yd_book = archive.get("药典部", "")

    sources = archive.get("来源", {})

    lines = []
    lines.append(f"## {name}")
    if match_type != "exact":
        lines.append(f"*匹配方式：{match_type}*")
    lines.append("")

    # 基本信息
    lines.append("### 基本信息")
    lines.append("")
    if variants and len(variants) > 1:
        lines.append(f"- **剂型变体**：{', '.join(variants[:8])}{'...' if len(variants) > 8 else ''}")
    if dosage_forms:
        lines.append(f"- **剂型**：{', '.join(dosage_forms[:5])}")
    if specs:
        lines.append(f"- **规格**：{', '.join(specs[:3])}")
    if approval_nums:
        lines.append(f"- **批准文号**：{', '.join(approval_nums[:3])}{'等' if len(approval_nums) > 3 else ''}（共{len(approval_nums)}个）")
    if holders:
        lines.append(f"- **上市许可持有人**：{', '.join(holders[:3])}{'等' if len(holders) > 3 else ''}")
    if yibao_category:
        yb_text = yibao_category
        if yibao_category in ["甲", "乙"]:
            yb_text = f"医保{yibao_category}类"
        lines.append(f"- **医保类别**：{yb_text}")
        if yibao_note:
            lines.append(f"- **医保备注**：{yibao_note}")
    if yd_category:
        lines.append(f"- **药典分类**：{yd_category}")
    lines.append("")

    # 临床信息：优先小荷医典增强内容，其次药典字段
    xiaohe_sections = archive.get("小荷sections") or {}
    xiaohe_meta = archive.get("小荷meta") or {}
    has_clinical = False
    lines.append("### 临床信息")
    lines.append("")

    if xiaohe_sections:
        # 小荷医典章节（新数据增强，36 节中的核心节按序展示）
        has_clinical = True
        if xiaohe_meta.get("英文名"):
            lines.append(f"*英文名：{xiaohe_meta['英文名']}*")
            lines.append("")
        xh_order = ["适应证", "用法", "剂型规格", "慎用情况", "禁用情况",
                    "相互作用", "不良反应", "儿童", "孕妇", "老年人", "药物贮存"]
        for xk in xh_order:
            xv = xiaohe_sections.get(xk)
            if not xv:
                continue
            xv = str(xv).strip()
            if xv:
                lines.append(f"**{xk}**：{xv}")
                lines.append("")

    if func_indication:
        has_clinical = True
        lines.append(f"**功能与主治**：{func_indication}")
        lines.append("")
    if indication:
        has_clinical = True
        lines.append(f"**适应症**：{indication}")
        lines.append("")
    if usage:
        has_clinical = True
        lines.append(f"**用法与用量**：{usage}")
        lines.append("")
    if contraindication:
        has_clinical = True
        lines.append(f"**禁忌与注意**：{contraindication}")
        lines.append("")
    if adverse:
        has_clinical = True
        lines.append(f"**不良反应**：{adverse}")
        lines.append("")

    if not has_clinical:
        lines.append("*该药品的临床用药信息（适应症/用法用量/禁忌/不良反应）在当前数据源中未收录。化学药品的临床信息请以药品说明书为准。*")
        lines.append("")

    # 药物相互作用（如有）
    interaction = archive.get("相互作用", "")
    if interaction:
        lines.append("### 药物相互作用")
        lines.append("")
        lines.append(interaction)
        lines.append("")

    # 就医指引
    lines.append("### 就医指引")
    lines.append("")
    lines.append("- 用药前请仔细阅读药品说明书，或咨询执业医师/药师。")
    lines.append("- 处方药必须凭医师处方购买和使用。")
    lines.append("- 如出现过敏反应、严重不良反应或症状无改善，请立即停药并就医。")
    lines.append("- 特殊人群（孕妇、哺乳期妇女、儿童、老年人、肝肾功能不全者）用药请遵医嘱。")
    lines.append("")

    # 购买参考（合规：明示推广；后端未配置时降级为公开搜索链接）
    buy_section = _render_buy_section(name, buy_links_raw)
    if buy_section:
        lines.append(buy_section)

    # 来源标注
    source_details = []
    if sources.get("NMPA"):
        source_details.append("国家药品监督管理局（NMPA）药品批准信息")
    if sources.get("医保"):
        source_details.append("国家基本医疗保险、工伤保险和生育保险药品目录（2025年版）")
    if sources.get("药典"):
        source_details.append("《中华人民共和国药典》（2025年版）")
    if xiaohe_sections:
        source_details.append("小荷医典（用药科普）")
    if source_details:
        lines.append("### 数据来源与核验")
        lines.append("")
        for s in source_details:
            lines.append(f"- {s}")
        lines.append(f"- 数据版本：{DATA_VERSION}")
        lines.append(f"- 核验日期：{DATA_VERIFY_DATE}")
        lines.append("")

    # 完整免责声明
    lines.append(DISCLAIMER_FULL.format(verify_date=DATA_VERIFY_DATE, version=DATA_VERSION))

    return "\n".join(lines)


# ============================================================
# 未命中兜底输出
# ============================================================
def render_not_found(query, suggestions=None):
    """未命中时的兜底输出"""
    lines = []
    lines.append(f"## 未找到「{query}」的药品档案")
    lines.append("")
    lines.append("可能的原因：")
    lines.append("- 药品名称输入有误（请检查错别字）")
    lines.append("- 该药品为医院制剂/罕见病用药，未收录在公开数据源中")
    lines.append("- 该名称为商品名，请尝试使用通用名查询")
    lines.append("")

    if suggestions:
        lines.append("**您可能想查询**：")
        for s in suggestions[:5]:
            lines.append(f"- {s}")
        lines.append("")

    lines.append("### 就医指引")
    lines.append("")
    lines.append("- 如您有具体的用药问题，请咨询执业医师或药师。")
    lines.append("- 如出现身体不适，请及时就医，切勿自行用药。")
    lines.append("")
    lines.append(DISCLAIMER_BRIEF)

    return "\n".join(lines)


# ============================================================
# 副路由输出（浅层科普）
# ============================================================
SUBROUTINE_CONTENT = {
    "emotion": """
## 情绪调节小技巧（浅层科普，非心理诊断）

当你感到情绪波动时，可以尝试：

1. **呼吸调节**：缓慢吸气4秒→屏息4秒→缓慢呼气6秒，重复3-5次
2. **着陆练习（Grounding）**：说出你能看到的5样东西、听到的4种声音、触摸到的3种质感
3. **认知调整**：问自己"这个想法有证据吗？有没有其他可能的解释？"
4. **适度运动**：散步10-15分钟，帮助释放紧张情绪

⚠️ **重要提示**：如果你持续两周以上情绪低落、兴趣减退，或出现自伤/自杀念头，请立即寻求专业帮助：
- 全国心理援助热线：**400-161-9995**
- 北京心理危机研究与干预中心：**010-82951332**
- 或前往当地精神卫生中心/医院心理科就诊

*本内容为情绪管理科普，不构成心理诊断或治疗。*
""".strip(),

    "sleep": """
## 睡眠卫生建议（浅层科普，非医疗干预）

帮助改善睡眠的日常习惯：

1. **规律作息**：每天固定时间上床和起床，包括周末
2. **睡前环境**：卧室保持安静、黑暗、凉爽（18-22°C）
3. **睡前习惯**：睡前1小时避免使用电子设备，可尝试阅读纸质书或听轻音乐
4. **饮食注意**：睡前避免咖啡因、酒精和大量进食
5. **白天活动**：白天适度运动，但避免睡前3小时剧烈运动

⚠️ 如果您长期失眠（超过1个月）、白天严重影响功能，或伴有打鼾/呼吸暂停，请及时就医（睡眠门诊或神经内科）。

*本内容为睡眠卫生科普，不构成医疗诊断或治疗。*
""".strip(),

    "stress": """
## 压力管理工具箱（浅层科普）

当感到压力大时，可以尝试：

1. **即时减压**：深呼吸（吸气4秒-屏息4秒-呼气6秒）×5次
2. **身体放松**：渐进式肌肉放松（从脚趾到头顶，逐组肌肉紧张5秒后放松）
3. **时间管理**：列出待办事项，按重要紧急程度排序，一次只做一件事
4. **社会支持**：和信任的朋友/家人聊聊，不要独自承受
5. **边界设定**：学会说"不"，合理分配工作和休息时间

⚠️ 如果压力持续导致头痛、失眠、食欲改变、情绪失控等，请及时寻求专业帮助。

*本内容为压力管理科普，不构成医疗诊断或治疗。*
""".strip(),

    "tcm_health": """
## 中医养生科普（浅层，非诊疗）

### 四季养生原则
- **春**：养肝为主，宜早睡早起，适当舒展运动，饮食清淡
- **夏**：养心为主，宜晚睡早起，避免贪凉，适当吃苦味食物
- **秋**：养肺为主，宜早睡早起，注意润燥，适当吃润肺食物（梨、百合、银耳）
- **冬**：养肾为主，宜早睡晚起，注意保暖，适当进补（但不宜过度）

### 药食同源小常识
- 山药：健脾益胃，适合脾胃虚弱者
- 枸杞：滋补肝肾，适合用眼过度者
- 红枣：补中益气，适合气血不足者
- 薏米：健脾利湿，适合湿气重者

⚠️ **中医讲究辨证论治，个体差异大。** 以上为通用科普，具体体质调理请咨询中医师。切勿自行服用中药或中成药治疗疾病。

*本内容为中医科普，不构成诊疗建议。*
""".strip(),

    "mindfulness": """
## 正念冥想入门引导（放松练习，非医疗干预）

### 呼吸冥想（5分钟）
1. 找一个安静的地方，舒适地坐下，背部挺直
2. 闭上眼睛，将注意力集中在呼吸上
3. 感受空气进入鼻孔、充满腹部、再缓缓呼出
4. 当思绪飘走时，不用评判，轻轻将注意力带回到呼吸上
5. 持续5分钟，慢慢睁开眼睛

### 身体扫描（10分钟）
1. 仰卧或舒适坐下，闭上眼睛
2. 从脚趾开始，逐部位感受身体的感觉（紧张/放松/温暖/麻木）
3. 不需要改变什么，只是觉察
4. 逐步向上：脚→小腿→大腿→腹部→胸部→手臂→肩膀→颈部→面部→头顶
5. 最后感受整个身体作为一个整体

### 小贴士
- 初学者可以从3-5分钟开始，逐渐延长
- 不需要"清空大脑"，思绪飘走是正常的，轻轻拉回来即可
- 每天固定时间练习效果更好

*本内容为放松练习引导，非医疗干预，不用于治疗任何疾病。*
""".strip(),

    "subhealth": """
## 亚健康与营养保健科普（浅层）

### 常见亚健康状态与日常调理
- **眼干/眼疲劳**：每用眼40分钟休息5-10分钟，远眺放松；适当补充维生素A（胡萝卜、菠菜）
- **疲劳乏力**：保证7-8小时睡眠，规律运动，均衡饮食；如持续疲劳建议体检
- **免疫力下降**：均衡饮食（蛋白质+蔬菜水果）、规律作息、适度运动、保持心情愉悦
- **维生素补充**：优先通过食物获取；如考虑补充剂，请咨询医生或营养师，避免过量

### 营养小贴士
- 维生素C：新鲜蔬果（橙子、猕猴桃、青椒）
- 维生素D：适度晒太阳（每天15-20分钟）、深海鱼
- 钙：奶制品、豆制品、绿叶蔬菜
- 铁：红肉、动物肝脏（适量）、菠菜

⚠️ 以上为通用健康科普。如症状持续或加重，请及时就医体检，明确原因后再针对性调理，切勿盲目服用保健品。

*本内容为健康科普，不构成医疗诊断或治疗建议。*
""".strip(),
}


def render_subroutine(route_name):
    """副路由输出"""
    content = SUBROUTINE_CONTENT.get(route_name, "")
    if not content:
        return "该模块内容正在建设中。"
    return content + "\n\n" + DISCLAIMER_BRIEF
