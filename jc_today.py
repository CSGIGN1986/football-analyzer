#!/usr/bin/env python3
"""竞彩足球今日分析脚本"""
import urllib.request, ssl, json
from datetime import datetime, date, timedelta
from collections import defaultdict
import numpy as np
from scipy.stats import poisson

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = False
h = {'User-Agent': 'Mozilla/5.0'}

now = datetime.now()
today = date.today()

CN = {
    'FC St. Pauli': '圣保利', 'SpVgg Greuther Fürth': '菲尔特',
    '1. FC Nürnberg': '纽伦堡', 'SG Dynamo Dresden': '德累斯顿',
    'Dynamo Dresden': '德累斯顿', 'Energie Cottbus': '科特布斯',
    'Hannover 96': '汉诺威', 'TSG 1899 Hoffenheim II': '霍芬海姆II',
    'Hansa Rostock': '罗斯托克', '1. FC Saarbrücken': '萨尔布吕肯',
    'Rot-Weiss Essen': '红白埃森', 'Alemannia Aachen': '亚琛',
    'SC Verl': '费尔', 'VfL Osnabrück': '奥斯纳布吕克',
    'Arminia Bielefeld': '比勒费尔德', 'DSC Arminia Bielefeld': '比勒费尔德',
    'SV Wehen Wiesbaden': '韦恩', 'FC Ingolstadt 04': '因戈尔施塔特',
    'MSV Duisburg': '杜伊斯堡', 'Preußen Münster': '明斯特',
    'SSV Jahn Regensburg': '雷根斯堡', 'Jahn Regensburg': '雷根斯堡',
    'SV Waldhof Mannheim': '曼海姆', 'VfB Stuttgart II': '斯图加特II',
    'VfL Bochum': '波鸿', 'Hertha BSC': '柏林赫塔', 'Holstein Kiel': '基尔',
    'SV Darmstadt 98': '达姆施塔特', '1. FC Kaiserslautern': '凯泽',
    'Eintracht Braunschweig': '不伦瑞克', 'Karlsruher SC': '卡尔斯鲁厄',
    '1. FC Magdeburg': '马格德堡', '1. FC Heidenheim': '海登海姆',
    '1. FC Heidenheim 1846': '海登海姆', 'VfL Wolfsburg': '沃夫斯堡',
    'FC Viktoria Köln': '维多利亚科隆', 'Viktoria Köln': '维多利亚科隆',
    'Würzburger Kickers': '维尔茨堡', 'SV Meppen': '梅彭',
    'TSV Havelse': '哈弗尔泽', 'SG Sonnenhof Großaspach': '大阿斯帕赫',
    'Fortuna Düsseldorf': '杜塞多夫', 'Fortuna Köln': '科隆福图纳',
}
cn = lambda n: CN.get(n, n)

# 1. 加载上赛季数据
team = {}
for code in ['bl2', 'bl3']:
    try:
        url = f'https://api.openligadb.de/getmatchdata/{code}/2025'
        req = urllib.request.Request(url, headers=h)
        resp = urllib.request.urlopen(req, context=ctx, timeout=12)
        for m in json.loads(resp.read()):
            results = m.get('matchResults', [])
            if not any(r.get('resultName') == 'Endergebnis' for r in results):
                continue
            t1 = m.get('team1', {}).get('teamName', '?')
            t2 = m.get('team2', {}).get('teamName', '?')
            goals = m.get('goals', [])
            hg = awg = 0
            for g in goals:
                if g.get('scoreTeam1'): hg = g['scoreTeam1']
                if g.get('scoreTeam2'): awg = g['scoreTeam2']
            for tn, gf, ga, hf in [(t1, hg, awg, True), (t2, awg, hg, False)]:
                if tn not in team:
                    team[tn] = {
                        'gf': 0, 'ga': 0, 'm': 0, 'hm': 0, 'am': 0,
                        'hg': 0, 'ha': 0, 'ag': 0, 'aa': 0,
                        'w': 0, 'd': 0, 'l': 0, 'pt': 0, 'f': [],
                        'hw': 0, 'hd': 0, 'hl': 0, 'aw': 0, 'ad': 0, 'al': 0,
                    }
                s = team[tn]
                s['gf'] += gf; s['ga'] += ga; s['m'] += 1
                if hf:
                    s['hg'] += gf; s['ha'] += ga; s['hm'] += 1
                    if gf > ga:
                        s['w'] += 1; s['hw'] += 1; s['pt'] += 3; s['f'].append('W')
                    elif gf == ga:
                        s['d'] += 1; s['hd'] += 1; s['pt'] += 1; s['f'].append('D')
                    else:
                        s['l'] += 1; s['hl'] += 1; s['f'].append('L')
                else:
                    s['ag'] += gf; s['aa'] += ga; s['am'] += 1
                    if gf > ga:
                        s['w'] += 1; s['aw'] += 1; s['pt'] += 3; s['f'].append('W')
                    elif gf == ga:
                        s['d'] += 1; s['ad'] += 1; s['pt'] += 1; s['f'].append('D')
                    else:
                        s['l'] += 1; s['al'] += 1; s['f'].append('L')
    except Exception as e:
        print(f"Error loading {code}: {e}")

la = sum(s['gf'] for s in team.values()) / max(1, sum(s['m'] for s in team.values()))

# 2. 加载本赛季比赛
all_match = []
for code, lg in [('bl2', '德乙'), ('bl3', '德丙')]:
    try:
        url = f'https://api.openligadb.de/getmatchdata/{code}/2026'
        req = urllib.request.Request(url, headers=h)
        resp = urllib.request.urlopen(req, context=ctx, timeout=12)
        for m in json.loads(resp.read()):
            ds = m.get('matchDateTime', '')
            if not ds:
                continue
            try:
                md = datetime.fromisoformat(ds.replace('Z', '+00:00'))
            except Exception:
                try:
                    md = datetime.strptime(ds[:19], '%Y-%m-%dT%H:%M:%S')
                except Exception:
                    continue
            t1 = m.get('team1', {}).get('teamName', '?')
            t2 = m.get('team2', {}).get('teamName', '?')
            results = m.get('matchResults', [])
            is_done = any(r.get('resultName') == 'Endergebnis' for r in results)
            goals = m.get('goals', [])
            hg = awg = 0
            for g in goals:
                if g.get('scoreTeam1'): hg = g['scoreTeam1']
                if g.get('scoreTeam2'): awg = g['scoreTeam2']
            all_match.append({
                'd': md.date(), 'lg': lg, 'h': t1, 'a': t2,
                't': md.strftime('%H:%M'), 'hg': hg, 'ag': awg, 'ok': is_done,
            })
    except Exception as e:
        print(f"Error loading {code} 2026: {e}")

all_match.sort(key=lambda x: x['d'])
bd = defaultdict(list)
for m in all_match:
    bd[m['d']].append(m)


# 3. 预测函数
def pred(home, away):
    hs = team.get(home)
    aws = team.get(away)
    if not hs or not aws:
        return None

    # 优先用主/客场数据，不够则用整体数据
    if hs['hm'] > 0 and aws['am'] > 0:
        ha = hs['hg'] / hs['hm'] / la
        hd = hs['ha'] / hs['hm'] / la
        aa = aws['ag'] / aws['am'] / la
        ad = aws['aa'] / aws['am'] / la
        home_bonus = 1.15
    elif hs['m'] > 0 and aws['m'] > 0:
        ha = hs['gf'] / hs['m'] / la
        hd = hs['ga'] / hs['m'] / la
        aa = aws['gf'] / aws['m'] / la
        ad = aws['ga'] / aws['m'] / la
        home_bonus = 1.10
    else:
        return None

    hl = la * ha * ad * home_bonus
    al = la * aa * hd
    hl = max(0.3, min(5.0, hl))
    al = max(0.3, min(5.0, al))

    mg = 8
    hp = [poisson.pmf(i, hl) for i in range(mg + 1)]
    ap = [poisson.pmf(i, al) for i in range(mg + 1)]

    hw = sum(hp[i] * sum(ap[:i]) for i in range(1, mg + 1))
    awp = sum(ap[i] * sum(hp[:i]) for i in range(1, mg + 1))
    dr = sum(hp[i] * ap[i] for i in range(mg + 1))
    t = hw + dr + awp
    hw /= t; dr /= t; awp /= t

    o25 = sum(hp[i] * ap[j] for i in range(mg + 1) for j in range(mg + 1) if i + j > 2.5)
    btts = sum(hp[i] * ap[j] for i in range(1, mg + 1) for j in range(1, mg + 1))
    best = max([(hw, '主胜'), (dr, '平局'), (awp, '客胜')], key=lambda x: x[0])

    return {
        'p': best[1], 'c': best[0], 'hl': hl, 'al': al,
        'o25': o25, 'b': btts,
        'hp': hs['pt'] / hs['m'], 'ap': aws['pt'] / aws['m'],
        'hf': ''.join(hs['f'][-5:]), 'af': ''.join(aws['f'][-5:]),
    }


# 4. 输出
print("=" * 65)
print(f"  ⚽ 竞彩足球分析预测 | {now.strftime('%m-%d %H:%M')} 周{'一二三四五六日'[today.weekday()]}")
print("=" * 65)

# 赛果回顾
print(f"\n  📊 第1轮赛果 (8/7-9) | 上赛季{len(team)}队 场均{la:.1f}球")
for d in sorted(bd):
    if d < date(2026, 8, 7) or d > date(2026, 8, 10):
        continue
    ms = bd[d]
    done = [m for m in ms if m['ok']]
    if not done:
        continue
    dc = '一二三四五六日'[d.weekday()]
    hc = sum(1 for m in done if m['hg'] > m['ag'])
    dc2 = sum(1 for m in done if m['hg'] == m['ag'])
    ac = sum(1 for m in done if m['hg'] < m['ag'])
    oc = sum(1 for m in done if m['hg'] + m['ag'] > 2.5)
    print(f"\n  {d} 周{dc} 主{hc}W{dc2}D{ac}W | 大{oc}/{len(done)}")
    for m in done:
        out = '主胜' if m['hg'] > m['ag'] else ('平' if m['hg'] == m['ag'] else '客胜')
        t = m['hg'] + m['ag']
        ov = '大' if t > 2 else '小'
        b = 'BTTS' if m['hg'] > 0 and m['ag'] > 0 else ''
        print(f"  [{m['lg'][:2]}] {cn(m['h'])} {m['hg']}-{m['ag']} {cn(m['a'])} {out} {t}球{ov} {b}")

# 预测
print(f"\n\n  🔮 第2轮预测 (8/14-16)")
ps = []
for d in sorted(bd):
    if d < date(2026, 8, 14) or d > date(2026, 8, 17):
        continue
    up = [m for m in bd[d] if not m['ok']]
    if not up:
        continue
    dc = '一二三四五六日'[d.weekday()]
    print(f"\n  {d} 周{dc} ({len(up)}场)")
    for m in sorted(up, key=lambda x: x['t']):
        p = pred(m['h'], m['a'])
        print(f"  [{m['lg'][:2]}] {m['t']} {cn(m['h']):<12} vs {cn(m['a']):<12}")
        if p:
            bar = '█' * int(p['c'] * 20)
            print(f"  {p['hp']:.1f}PPG {p['hf']:<8} vs {p['ap']:.1f}PPG {p['af']:<8}")
            print(f"  🎯 {p['p']} {p['c']:.0%} {bar}")
            print(f"  ⚽ {p['hl']:.1f}-{p['al']:.1f} | 大2.5:{p['o25']:.0%} | BTTS:{p['b']:.0%}")
            ps.append({
                'h': cn(m['h']), 'a': cn(m['a']), 'p': p['p'], 'c': p['c'],
                'g': f"{p['hl']:.1f}-{p['al']:.1f}", 'o': p['o25'], 'b': p['b'],
            })
        else:
            print(f"  ⚠️ 无历史数据(升班马)")

# 汇总
if ps:
    print(f"\n\n  📋 {len(ps)}场预测汇总")
    print(f"  {'─' * 60}")
    print(f"  {'主队':<12} {'客队':<12} {'推荐':<6} {'胜率':>5} {'进球':>8} {'大2.5':>6} {'BTTS':>6}")
    print(f"  {'─' * 60}")
    for p in ps[:30]:
        print(f"  {p['h']:<12} {p['a']:<12} {p['p']:<6} {p['c']:>4.0%} {p['g']:>8} {p['o']:>5.0%} {p['b']:>5.0%}")

print(f"\n{'=' * 65}")
print(f"  OpenLigaDB API | 泊松模型 | 上赛季+本赛季数据")
print(f"{'=' * 65}")
