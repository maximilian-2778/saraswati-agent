"""Generate the fixed synthetic narrative benchmark used by run_benchmark.py."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "evals" / "benchmark" / "cases.json"


STORIES = [
    ("s01", "雾港", "莉娜", "银铃", "钟楼", "洛克", "38", "结盟"),
    ("s02", "赤沙城", "米娅", "铜钥匙", "旧水塔", "凯恩", "47", "停战"),
    ("s03", "月影镇", "艾琳", "蓝宝石", "北门", "诺亚", "56", "合作"),
    ("s04", "白松谷", "薇拉", "黑色信封", "猎人小屋", "伊森", "64", "和解"),
    ("s05", "潮汐岛", "赛拉", "航海图", "灯塔", "奥文", "73", "互助"),
    ("s06", "灰烬堡", "娜迪亚", "断剑", "议事厅", "雷蒙", "82", "效忠"),
    ("s07", "翡翠林", "露西亚", "月桂冠", "古树祭坛", "菲恩", "91", "信任"),
    ("s08", "霜河城", "伊芙", "白羽徽章", "南岸码头", "托马", "29", "休战"),
    ("s09", "星落原", "安雅", "观星盘", "废弃神殿", "西奥", "35", "协作"),
    ("s10", "琥珀湾", "卡拉", "珊瑚戒指", "海关仓库", "布兰", "44", "谅解"),
    ("s11", "黑石城", "芙蕾雅", "王室印章", "地下档案室", "加文", "52", "同盟"),
    ("s12", "风歌村", "诺拉", "风笛", "西坡风车", "亚瑟", "67", "合作"),
]


def story_cases(row: tuple[str, ...]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sid, place, person, item, location, npc, gold, relation = row
    old_owner = f"{npc}"
    old_gold = str(max(int(gold) - 17, 1))
    facts = [
        ("item_owner", f"{item}现在由谁保管？", f"{person}", old_owner,
         f"在{place}的争执结束后，{person}接过{item}并成为当前保管人。",
         f"更早以前，{item}曾由{old_owner}暂时保管。"),
        ("location", f"{person}目前停留在哪里？", location, "中央广场",
         f"入夜后，{person}已经抵达{location}并决定暂时留在那里。",
         f"上午时，{person}曾在中央广场打听消息。"),
        ("promise", f"{person}答应与谁在日落前会合？", npc, "守门人",
         f"{person}最后承诺在日落前与{npc}会合。",
         f"最初的计划是与守门人会面，但该安排已经取消。"),
        ("gold", "队伍当前还剩多少金币？", gold, old_gold,
         f"完成补给结算后，队伍当前余额为{gold}金币。",
         f"购买药品之前，账本曾记录队伍只有{old_gold}金币。"),
        ("quest", "寻找失踪信使的任务现在是什么状态？", "已完成", "进行中",
         f"失踪信使已经在{location}获救，因此寻找信使的任务当前状态为已完成。",
         "前一天的公告仍写着寻找信使任务进行中。"),
        ("relation", f"{person}与{npc}目前是什么关系？", relation, "敌对",
         f"双方交换证据后，{person}与{npc}的当前关系变为{relation}。",
         f"冲突刚发生时，{person}与{npc}一度处于敌对状态。"),
        ("time", "商队最终决定什么时候离开？", "第三天清晨", "第二天午夜",
         "综合天气与道路情况后，商队最终决定第三天清晨离开。",
         "早先草案写的是第二天午夜离开，但已经作废。"),
        ("faction", f"{place}旧议会现在是否仍然存在？", "已经解散", "仍在执政",
         f"表决结束后，{place}旧议会已经解散，其印章被封存。",
         f"一个月前的记录显示，{place}旧议会仍在执政。"),
        ("clue", f"刻有三道波纹的标记最终指向哪里？", location, "东城门",
         f"比对航海日志后，三道波纹标记最终被确认指向{location}。",
         "调查初期，众人误以为三道波纹标记指向东城门。"),
        ("condition", f"{npc}当前的伤势如何？", "已经稳定", "仍在恶化",
         f"接受治疗后，{npc}的伤势已经稳定，可以正常交谈。",
         f"治疗开始前，医师曾判断{npc}的伤势仍在恶化。"),
    ]
    documents = []
    for index, (_, _, _, _, current, old) in enumerate(facts, 1):
        documents.append({"id": f"{sid}-f{index:02d}", "text": current, "age_days": index % 3})
        documents.append({"id": f"{sid}-d{index:02d}", "text": old, "age_days": 45 + index})

    retrieval: list[dict[str, object]] = []
    consistency: list[dict[str, object]] = []
    for index, (kind, query, expected, forbidden, _, _) in enumerate(facts, 1):
        case = {
            "case_id": f"{sid}-q{index:02d}",
            "story_id": sid,
            "category": kind,
            "query": query,
            "relevant_ids": [f"{sid}-f{index:02d}"],
            "documents": documents,
        }
        retrieval.append(case)
        if int(sid[1:]) <= 6:
            consistency.append({
                **case,
                "expected_phrases": [expected],
                "forbidden_phrases": [forbidden],
            })
    return retrieval, consistency


def state_cases() -> list[dict[str, object]]:
    names = ["阿岚", "白芷", "苍术", "丹砂", "青禾", "若木", "闻溪", "照夜", "云岫", "南星"]
    result: list[dict[str, object]] = []
    for index in range(40):
        name = names[index % len(names)]
        group = index % 8
        suffix = index + 1
        if group == 0:
            user = "玩家购买补给后询问剩余资金。"
            assistant = f"结算完成，{name}小队的金币余额明确变为{30 + suffix}。"
            gold = [{"entity": f"队伍:{name}", "key": "金币", "new_value": 30 + suffix}]
        elif group == 1:
            user = "玩家接受治疗并要求记录结果。"
            assistant = f"治疗结束后，{name}的生命值明确恢复到{60 + suffix}。"
            gold = [{"entity": f"角色:{name}", "key": "生命值", "new_value": 60 + suffix}]
        elif group == 2:
            user = "玩家交付信件。"
            assistant = f"收件人确认无误，任务“密信-{suffix}”的状态明确更新为已完成。"
            gold = [{"entity": f"任务:密信-{suffix}", "key": "状态", "new_value": "已完成"}]
        elif group == 3:
            user = "玩家在谈判后查看阵营声望。"
            assistant = f"谈判结果已经确认，{name}在商会的声望明确变为{10 + suffix}。"
            gold = [{"entity": f"角色:{name}", "key": "商会声望", "new_value": 10 + suffix}]
        elif group == 4:
            user = "玩家完成训练并记录两项属性。"
            assistant = f"训练完成，{name}的力量明确变为{8 + suffix}，敏捷明确变为{11 + suffix}。"
            gold = [
                {"entity": f"角色:{name}", "key": "力量", "new_value": 8 + suffix},
                {"entity": f"角色:{name}", "key": "敏捷", "new_value": 11 + suffix},
            ]
        elif group == 5:
            user = "玩家只是回忆旧传闻，没有发生新事件。"
            assistant = f"{name}想起有人声称宝库里可能有一百枚金币，但没有确认，也没有任何状态发生变化。"
            gold = []
        elif group == 6:
            user = "玩家查看天气，没有进行交易。"
            assistant = f"{name}望着阴云，猜测明天也许会下雨；队伍资金和属性都没有变化。"
            gold = []
        else:
            user = "玩家完成两项明确的任务进展。"
            assistant = f"任务“遗迹-{suffix}”明确进入已完成状态；{name}的探索积分明确变为{100 + suffix}。"
            gold = [
                {"entity": f"任务:遗迹-{suffix}", "key": "状态", "new_value": "已完成"},
                {"entity": f"角色:{name}", "key": "探索积分", "new_value": 100 + suffix},
            ]
        result.append({
            "case_id": f"state-{suffix:03d}",
            "user_text": user,
            "assistant_text": assistant,
            "expected_state_changes": gold,
        })
    return result


def main() -> None:
    retrieval: list[dict[str, object]] = []
    consistency: list[dict[str, object]] = []
    for story in STORIES:
        story_retrieval, story_consistency = story_cases(story)
        retrieval.extend(story_retrieval)
        consistency.extend(story_consistency)
    payload = {
        "metadata": {
            "name": "Saraswati Synthetic Narrative Benchmark v1",
            "seed": 20260813,
            "retrieval_cases": len(retrieval),
            "consistency_cases": len(consistency),
            "state_cases": 40,
            "notice": "Synthetic, template-generated and deterministically labelled; not real-user data.",
        },
        "retrieval_cases": retrieval,
        "consistency_cases": consistency,
        "state_cases": state_cases(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
