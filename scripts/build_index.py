#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
索引构建脚本：从全量药品档案生成技能包内嵌的精简索引
数据打包方案：
- 全量档案 25.6MB（15,898条）过大，不适合直接内嵌
- 方案：生成精简索引（每条仅保留检索必需字段+免费层字段），约3-5MB
- 付费层的完整临床信息（功能主治/用法用量等）按需从全量数据加载
- 高频Top 500药品的完整档案内嵌，其余药品完整信息可选加载
"""
import os
import json
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

# 全量数据路径（默认相对技能目录，可用环境变量 DRUG_FULL_DATA 覆盖）
FULL_DATA = os.environ.get("DRUG_FULL_DATA", os.path.join(SKILL_DIR, "data", "drug_archive_full.json"))

# 输出路径
INDEX_OUTPUT = os.path.join(SKILL_DIR, "data", "drug_archive_index.json")
HIGH_FREQ_OUTPUT = os.path.join(SKILL_DIR, "data", "high_freq_drugs.json")

# 高频药品词表（基于竞品336词表下载量高的部分 + 常见药）
HIGH_FREQ_NAMES = [
    # 解热镇痛
    "阿司匹林", "布洛芬", "对乙酰氨基酚", "双氯芬酸钠", "萘普生", "吲哚美辛",
    # 抗生素
    "阿莫西林", "头孢克肟", "头孢呋辛", "头孢地尼", "阿奇霉素", "罗红霉素",
    "左氧氟沙星", "莫西沙星", "甲硝唑", "克拉霉素",
    # 心血管
    "氨氯地平", "硝苯地平", "缬沙坦", "厄贝沙坦", "氯沙坦", "美托洛尔",
    "比索洛尔", "阿托伐他汀", "瑞舒伐他汀", "辛伐他汀", "硝酸甘油",
    "单硝酸异山梨酯", "氢氯噻嗪", "螺内酯", "呋塞米",
    # 消化
    "奥美拉唑", "兰索拉唑", "雷贝拉唑", "泮托拉唑", "埃索美拉唑",
    "铝碳酸镁", "枸橼酸莫沙必利", "多潘立酮", "蒙脱石散", "双歧杆菌",
    # 呼吸
    "氨溴索", "乙酰半胱氨酸", "孟鲁司特钠", "布地奈德", "沙丁胺醇",
    "特布他林", "复方甘草", "右美沙芬",
    # 内分泌
    "二甲双胍", "格列美脲", "阿卡波糖", "达格列净", "恩格列净",
    "左甲状腺素钠", "甲巯咪唑",
    # 神经/精神
    "艾司唑仑", "阿普唑仑", "舍曲林", "氟西汀", "帕罗西汀",
    "文拉法辛", "度洛西汀", "喹硫平", "奥氮平",
    # 抗过敏
    "氯雷他定", "西替利嗪", "依巴斯汀", "扑尔敏", "酮替芬",
    # 皮肤
    "氢化可的松", "地奈德", "糠酸莫米松", "他克莫司", "红霉素软膏",
    "莫匹罗星", "阿昔洛韦乳膏", "特比萘芬",
    # 维生素/营养
    "维生素C", "维生素D", "维生素B族", "钙尔奇", "葡萄糖酸钙",
    "铁剂", "叶酸",
    # 中成药常见
    "板蓝根", "双黄连", "感冒灵", "连花清瘟", "藿香正气",
    "云南白药", "六味地黄丸", "逍遥丸", "乌鸡白凤丸", "血塞通",
    "复方丹参", "速效救心丸", "安宫牛黄丸",
    # 其他
    "二甲硅油", "开塞露", "马应龙麝香痔疮膏", "滴眼液", "玻璃酸钠滴眼液",
]


def build_index():
    """构建精简索引"""
    print("加载全量数据...")
    with open(FULL_DATA, "r", encoding="utf-8") as f:
        full_data = json.load(f)
    print(f"全量记录: {len(full_data)} 条")

    # 精简索引：仅保留检索+免费层必需字段
    index_data = []
    for arch in full_data:
        slim = {
            "药品通用名称": arch.get("药品通用名称", ""),
            "归一化通用名": arch.get("归一化通用名", ""),
            "剂型变体": arch.get("剂型变体", []),
            "剂型": arch.get("剂型", [])[:5],
            "规格": arch.get("规格", [])[:3],
            "批准文号": arch.get("批准文号", [])[:3],
            "批准文号数": len(arch.get("批准文号", [])),
            "上市许可持有人": arch.get("上市许可持有人", [])[:3],
            "医保类别": arch.get("医保类别", ""),
            "医保备注": arch.get("医保备注", ""),
            "药典部": arch.get("药典部", ""),
            "类别": arch.get("类别", ""),
            "来源": arch.get("来源", {}),
        }
        index_data.append(slim)

    # 保存索引
    os.makedirs(os.path.dirname(INDEX_OUTPUT), exist_ok=True)
    with open(INDEX_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, separators=(",", ":"))
    index_size = os.path.getsize(INDEX_OUTPUT)
    print(f"精简索引: {len(index_data)} 条, {index_size/1024/1024:.2f} MB")

    return index_data


def build_high_freq(full_data):
    """构建高频药品完整档案（Top 500）"""
    # 按高频词表匹配
    high_freq = []
    matched_names = set()

    for name in HIGH_FREQ_NAMES:
        for arch in full_data:
            drug_name = arch.get("药品通用名称", "")
            variants = arch.get("剂型变体", [])
            if name == drug_name or name in variants:
                if drug_name not in matched_names:
                    high_freq.append(arch)
                    matched_names.add(drug_name)
                break

    # 如果不足500，按批准文号数补充
    if len(high_freq) < 500:
        sorted_by_approvals = sorted(
            full_data,
            key=lambda x: len(x.get("批准文号", [])),
            reverse=True
        )
        for arch in sorted_by_approvals:
            name = arch.get("药品通用名称", "")
            if name not in matched_names:
                high_freq.append(arch)
                matched_names.add(name)
                if len(high_freq) >= 500:
                    break

    # 保存高频完整档案
    with open(HIGH_FREQ_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(high_freq, f, ensure_ascii=False, separators=(",", ":"))
    hf_size = os.path.getsize(HIGH_FREQ_OUTPUT)
    print(f"高频完整档案: {len(high_freq)} 条, {hf_size/1024/1024:.2f} MB")

    return high_freq


def main():
    print("=" * 60)
    print("药品索引构建")
    print("=" * 60)

    # 构建精简索引
    index_data = build_index()

    # 构建高频完整档案
    print("\n加载全量数据用于高频子集...")
    with open(FULL_DATA, "r", encoding="utf-8") as f:
        full_data = json.load(f)
    high_freq = build_high_freq(full_data)

    # 数据打包方案总结
    total_size = os.path.getsize(INDEX_OUTPUT) + os.path.getsize(HIGH_FREQ_OUTPUT)
    print("\n" + "=" * 60)
    print("数据打包方案总结")
    print("=" * 60)
    print(f"全量档案: 69.9 MB (17,800条) - 可选外部加载")
    print(f"精简索引: {os.path.getsize(INDEX_OUTPUT)/1024/1024:.2f} MB ({len(index_data)}条) - 内嵌，用于检索+免费层")
    print(f"高频完整档案: {os.path.getsize(HIGH_FREQ_OUTPUT)/1024/1024:.2f} MB ({len(high_freq)}条) - 内嵌，付费层高频药直接返回")
    print(f"内嵌数据总计: {total_size/1024/1024:.2f} MB")
    print(f"\n加载策略:")
    print(f"  1. 启动时加载精简索引（检索+免费层）")
    print(f"  2. 付费查询时优先从高频完整档案返回")
    print(f"  3. 非高频药品的完整临床信息从全量数据按需加载（可选）")
    print(f"  4. 数据版本水印: 2026.09.22-v1, 核验日期 2026-09-22")


if __name__ == "__main__":
    main()
