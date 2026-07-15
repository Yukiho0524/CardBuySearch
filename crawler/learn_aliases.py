"""從既有譯名資料自動學習遊戲王「系列名」同義詞，擴增 ygo_aliases.json。

原理：百鴿匯出檔每張卡最多有四種譯名（社群 cn_name、NWBBS nwbbs_n、
台版官方 cnocg_n、Master Duel 官方 md_name）。對「系列·人名」型卡名，
比對各譯名的系列段：同一組系列段對照若出現在 ≥ MIN_COUNT 張卡上，
就視為可靠的系列同義詞，寫入字典——這能泛化到沒有官方譯名的新卡。

整名差異（如 石像怪↔石像鬼）不進字典：那些由 ygo_cards 的
name_cnocg / name_md 欄位直接涵蓋。

用法：
  python crawler/learn_aliases.py --file <cards.json>   # 檢視將新增的內容
  python crawler/learn_aliases.py --file <cards.json> --write
"""
import argparse
import io
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import requests
from opencc import OpenCC

sys.path.insert(0, str(Path(__file__).parent.parent))

DUMP_URL = "https://ygocdb.com/api/v0/cards.zip"
ALIAS_PATH = Path(__file__).parent.parent / "ygo_aliases.json"
MIN_COUNT = 2          # 系列對照至少出現在幾張卡上才採信
SEG_SPLIT = re.compile(r"[·・\s]+")
CJK = re.compile(r"[一-鿿]")


def load_dump(path=None):
    if path:
        p = Path(path)
        if p.suffix == ".zip":
            data = p.read_bytes()
        else:
            return json.loads(p.read_text(encoding="utf-8"))
    else:
        print(f"下載 {DUMP_URL} …")
        r = requests.get(DUMP_URL, timeout=120)
        r.raise_for_status()
        data = r.content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.endswith(".json"))
        return json.loads(z.read(name).decode("utf-8"))


def first_segment(name):
    """取「系列·人名」型卡名的系列段；非多段卡名回傳 None。"""
    parts = [p for p in SEG_SPLIT.split(name.strip()) if p]
    if len(parts) < 2:
        return None
    seg = parts[0]
    if not (2 <= len(seg) <= 8) or not CJK.search(seg):
        return None
    return seg


def learn_pairs(dump):
    """回傳 Counter{(系列段A, 系列段B): 出現張數}（A<B 排序去向）。"""
    cc = OpenCC("s2twp")
    pairs = Counter()
    for entry in dump.values():
        forms = set()
        for key in ("cn_name", "nwbbs_n", "cnocg_n", "md_name"):
            v = entry.get(key)
            if v:
                forms.add(cc.convert(v))
        segs = {first_segment(f) for f in forms}
        segs.discard(None)
        segs = sorted(segs)
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                pairs[(segs[i], segs[j])] += 1
    return pairs


def merge_groups(existing, pairs):
    """把學到的系列對照（頻次達標者）與現有字典做聯集分組（union-find）。"""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for key, alts in existing.items():
        for a in alts:
            union(key, a)
    learned = [(p, n) for p, n in pairs.items() if n >= MIN_COUNT]
    for (a, b), _ in learned:
        union(a, b)

    groups = {}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)

    # 每組選 key：優先沿用現有字典的 key，否則取組內最短的詞
    result = {}
    old_keys = set(existing)
    for members in groups.values():
        if len(members) < 2:
            continue
        keys = sorted(members & old_keys) or sorted(members, key=lambda s: (len(s), s))
        key = keys[0]
        result[key] = sorted(members - {key})
    return result, learned


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="本地 cards.json 或 cards.zip")
    ap.add_argument("--write", action="store_true", help="寫回 ygo_aliases.json")
    args = ap.parse_args()

    doc = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    existing = doc.get("aliases", {})
    pairs = learn_pairs(load_dump(args.file))
    merged, learned = merge_groups(existing, pairs)

    new_terms = set()
    for k, v in merged.items():
        new_terms.update({k, *v})
    old_terms = set(existing)
    for v in existing.values():
        old_terms.update(v)
    print(f"學到 {len(learned)} 組系列對照（門檻 ≥{MIN_COUNT} 張卡），"
          f"字典 {len(old_terms)} 詞 → {len(new_terms)} 詞、{len(merged)} 組")
    for (a, b), n in sorted(learned, key=lambda x: -x[1])[:20]:
        print(f"  {n:3d} 張卡  {a} ↔ {b}")

    if args.write:
        doc["aliases"] = dict(sorted(merged.items()))
        ALIAS_PATH.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已寫入 {ALIAS_PATH}")
    else:
        print("（預覽模式，加 --write 寫回）")
