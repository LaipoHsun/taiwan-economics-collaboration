#!/usr/bin/env python3
"""final_plan 全流程 —— 從上游資料一路產生到現在這份資料集的**唯一一支程式**。

    python3 final_plan/code/pipeline.py              # 全跑（不含 Crossref，見下）
    python3 final_plan/code/pipeline.py --stage 2 3  # 只跑某幾個階段
    python3 final_plan/code/pipeline.py --with-crossref
    python3 final_plan/code/pipeline.py --offline     # 完全不連網（用快取）

七個階段，順序有相依性：

| # | 階段 | 做什麼 | 產出 |
|---|---|---|---|
| 1 | `fix_author_lists`  | 修復壞掉的作者名單（切錯的、碎片、名單不完整的 7 篇） | `manual_review/decisions/author_list_fixes.csv` |
| 2 | `build`             | 主建置：論文／計畫／名冊／兩層網路／地圖 | `paper/` `project/` `professor_demo/` `network/` `map/` |
| 3 | `enrich`            | OpenAlex：總發表量、總被引數、領域 | `professor_demo/` 加欄 |
| 4 | `journal_pdf`       | 三份中文期刊 PDF ＋ 上網查證結果 → 外部作者機構 | `decisions/external_affiliations_journal.csv` |
| 5 | `crossref`          | Crossref metadata → 外部作者機構（收穫少，預設不跑） | `cache/crossref_affiliations.json` |
| 6 | `external_affil`    | 彙整所有機構來源、正規化，寫回 CSV | `professor_demo/authors_master.csv` |
| 7 | `review_sheets`     | 產生人工查核用的 Excel（不覆蓋既有檔） | `manual_review/*.xlsx` |

**階段 2 會重新產生 `professor_demo/`，所以 3、4、6 一定要排在它後面。**
這支程式一路跑完就會是現在的狀態；API 回應與 PDF 都有快取，重跑不花額度也不重抓。

上游資料夾（`collab_network/`、`collab_pubs/`、`faculty_identity/`、`faculty_and_map/`、
`claude_openalex_match/`）**只讀不寫**，這支程式不會動它們，也不 import 它們的程式。
"""
import argparse, collections, csv, difflib, hashlib, itertools, json, math, os, re, sys
import time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FINAL = os.path.dirname(HERE)
ROOT = os.path.dirname(FINAL)
DEC_DIR = os.path.join(FINAL, 'manual_review', 'decisions')
MAILTO = 'stone930801@gmail.com'
HTTP_UA = {'User-Agent': f'NetSciX2027-collab-network/0.1 (mailto:{MAILTO})'}
OFFLINE = False          # --offline 會把它設成 True，所有連網動作直接跳過


# ═══════════════════════════════════════════════════════════════
# 共用工具
# ═══════════════════════════════════════════════════════════════
def rd(*p):
    """讀專案裡的 CSV（路徑相對專案根目錄），順手剝掉 UTF-8 BOM。"""
    with open(os.path.join(ROOT, *p), newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def wr(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    return len(rows)


class BudgetExhausted(RuntimeError):
    """OpenAlex 每日額度用盡。"""


class _OpenAlexAPI:
    """OpenAlex 請求層。原本 import 自 `claude_openalex_match/code/oa_api.py`，
    為了讓這支程式自成一體而內建一份（那邊的檔案沒有被修改）。

    計費：純 filter 的 list query 每頁 1 credit，帶 search 的查詢 10 credits，
    免費金鑰每天 10,000 credits。所以能用 filter 就不要用 search。
    金鑰讀 `~/.openalex_key` 或環境變數，不會被寫進任何輸出。
    """
    BASE = 'https://api.openalex.org/'
    BudgetExhausted = BudgetExhausted

    def __init__(self):
        self.remaining = None

    def _key(self):
        k = os.environ.get('OPENALEX_API_KEY')
        f = os.path.expanduser('~/.openalex_key')
        if not k and os.path.exists(f):
            k = open(f, encoding='utf-8').read().strip()
        return k or None

    def get(self, endpoint, params):
        if OFFLINE:
            return {'meta': {'count': 0}, 'results': []}
        p = dict(params, mailto=MAILTO)
        key = self._key()
        if key:
            p['api_key'] = key
        url = self.BASE + endpoint + '?' + urllib.parse.urlencode(p)
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers=HTTP_UA)
                with urllib.request.urlopen(req, timeout=90) as r:
                    self.remaining = r.headers.get('X-RateLimit-Remaining')
                    return json.load(r)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode('utf-8', 'replace')[:300]
                if exc.code == 429:
                    raise BudgetExhausted(f'每日額度用盡，UTC 午夜重置。{body}') from None
                if exc.code in (401, 403):
                    raise RuntimeError(f'HTTP {exc.code}: 金鑰或權限問題。{body}') from None
                if exc.code < 500:
                    return {'error': exc.code, 'meta': {'count': 0}, 'results': []}
            except Exception:
                pass
            time.sleep(2 ** attempt)
        return {'error': 'network', 'meta': {'count': 0}, 'results': []}


_oa = _OpenAlexAPI()

# ── professor_demo 只放四個檔 ────────────────────────────────
#   authors_master.csv       主檔：名冊 active 教師 ＋ 全部外部共同作者，一行一個節點
#   professors_inactive.csv  名冊裡這 12 年沒有任何發表或計畫的教師
#   openalex_not_found.xlsx  找不到 OpenAlex 數字的人，附原因與被擋下的候選
#   external_not_found.xlsx  連機構都查不到的外部共同作者，附原因與代表作
MASTER = os.path.join(FINAL, 'professor_demo', 'authors_master.csv')
INACTIVE = os.path.join(FINAL, 'professor_demo', 'professors_inactive.csv')
OA_NOT_FOUND = os.path.join(FINAL, 'professor_demo', 'openalex_not_found.xlsx')
EXT_NOT_FOUND = os.path.join(FINAL, 'professor_demo', 'external_not_found.xlsx')


def read_master():
    """回傳 (全部節點, 名冊 active 教師, 外部共同作者)。三者共用同一批 dict 物件，
    所以改了 active/ext 裡的欄位，寫回 master 時會一起帶出去。"""
    if not os.path.exists(MASTER):
        return [], [], []
    with open(MASTER, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    return (rows,
            [r for r in rows if r.get('node_type') == 'roster'],
            [r for r in rows if r.get('node_type') == 'external'])


def write_master(rows, fields):
    return wr(MASTER, rows, fields)


def master_fields(prof_fields, ext_fields, extra=()):
    """主檔欄位＝節點欄 ＋ 教師欄 ＋ 外部作者特有欄 ＋ 後面幾個階段加上去的欄。"""
    fs = ['node_id', 'node_type'] + list(prof_fields)
    for f in list(ext_fields) + list(extra):
        if f not in fs:
            fs.append(f)
    return fs


def excel(path, title, fields, rows, widths=None, note=''):
    """寫一份單頁 Excel。沒有 openpyxl 就退回寫 CSV。"""
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill
    except ImportError:
        return wr(path.replace('.xlsx', '.csv'), rows, fields)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    top = 1
    if note:
        ws['A1'] = note
        ws['A1'].font = Font(bold=True)
        ws.append([])
        top = 3
    ws.append(list(fields))
    for c in ws[top]:
        c.font = Font(bold=True)
        c.fill = PatternFill('solid', fgColor='EEEEEE')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for r in rows:
        ws.append([r.get(f, '') for f in fields])
    ws.freeze_panes = f'A{top + 1}'
    for i, f in enumerate(fields, 1):
        L = openpyxl.utils.get_column_letter(i)
        ws.column_dimensions[L].width = (widths or {}).get(f, max(12, min(38, len(f) * 2 + 8)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb.save(path)
    return len(rows)


# ═══════════════════════════════════════════════════════════════
# 階段 1：修復壞掉的作者名單
# ═══════════════════════════════════════════════════════════════
CJK = re.compile(r'[一-鿿]')
FIX_FIELDS = ['paper_id', 'rule', 'n_before', 'n_after', 'author_node_ids_json',
          'author_names_json', 'new_node_ids_json', 'original_author_list',
          'resplit_author_list', 'evidence', 'note']

# C：7 篇 incomplete_author_list 的逐篇查證結果（2026-09-10）
# names = 論文實際的作者順序（>10 位者只登錄前 10 位）。
WEB_LOOKUP = {
    'P-R-31711d25a010e999b46c': {
        'names': ['Eric B. French', 'Jeremy McCauley', 'Maria Aragon', 'Pieter Bakx',
                  'Martin Chalkley', 'Stacey H. Chen', 'Bent J. Christensen',
                  'Hongwei Chuang', 'Aurelie Cote-Sergent', 'Mariacristina De Nardi'],
        'evidence': 'Crossref 10.1377/hlthaff.2017.0174 Health Affairs，共 28 位作者，取前 10 位',
    },
    'P-R-c66addc8586b00cf1505': {
        'names': ['Jay Joseph Van Bavel', 'Aleksandra Cichocka', 'Valerio Capraro',
                  'Hallgeir Sjastad', 'John B. Nezlek', 'Tomislav Pavlovic', 'Mark Alfano',
                  'Michele J. Gelfand', 'Flavio Azevedo', 'Michele D. Birtel'],
        'evidence': 'OpenAlex title search，Nature Communications 2022，100 位作者，取前 10 位',
    },
    'P-R-087cc28577e686f30a13': {
        'names': ['Abel Brodeur', 'Derek Mikola', 'Nikolai Cook', 'Lenka Fiala',
                  'Thomas James Brailey', 'Ryan C. Briggs', 'Alexandra de Gendre',
                  'Yannick Dupraz', 'Jacopo Gabani', 'Romain Gauriot'],
        'evidence': 'OpenAlex title search，Nature 2026，100 位作者，取前 10 位',
    },
    'P-R-a378f67b8af5245ca837': {
        'names': ['Cyrus Chu', 'Chien-Yu Chen', 'Ming-Jen Lin', 'Hsuan-Li Su'],
        'evidence': '不需上網：同一篇的另一筆填報 NSTC-P-001752 就有完整名單（4 位）',
    },
    'P-R-c3cb8b75e71cae0f7670': {
        'names': [], 'evidence': 'Crossref 與 OpenAlex 都查不到（中文專書論文）。'
                                 '原名單「吳中書|陳馨蕙|葉長城|鄭睿合等」的「等」無法還原，'
                                 '採用已列名的 4 位建邊',
    },
    'P-R-ad1aac82fd4cfce8c419': {
        'names': [], 'evidence': 'Crossref 與 OpenAlex 都查不到（中文技術報告）。'
                                 '採用已列名的 3 位建邊',
    },
    'P-R-7dd13058a65dd1b9dfc2': {
        'names': [], 'evidence': 'Crossref 與 OpenAlex 都查不到（2015 研討會論文）。'
                                 '「Ji-Ping Lin et al.」的其他作者無法還原，維持 1 人、不建邊',
    },
}



def nkey(s):
    """姓名正規化鍵：去重音、小寫、只留字母與漢字。"""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^0-9a-z一-鿿]', '', s.lower())


def surname_key(s):
    """`姓 + 名的首字母` 的鍵，用來把 `Ming-Jen Lin` 和 `Lin, M.-J.` 對起來。"""
    toks = [t for t in re.split(r'[^A-Za-z]+', s or '') if t]
    if len(toks) < 2:
        return ''
    if ',' in (s or ''):                       # `Lin, Ming-Jen` 姓在前
        sur, given = toks[0], toks[1:]
    else:
        sur, given = toks[-1], toks[:-1]
    return (sur + '|' + ''.join(g[0] for g in given)).lower()


def is_bare_latin_surname(t):
    """單獨出現的拉丁姓氏，例如 `Huang`、`Chou`、`Li`。

    **不含連字號**是關鍵：`Hao-ChunLu` 看起來也是「沒有空白沒有點」，
    但它是漏了空白的完整姓名（Hao-Chun Lu），接上下一段會把兩個人併成一個。
    中文名的名字部分幾乎都有連字號，姓氏則沒有。
    """
    t = t.strip().rstrip('*＊')
    return (bool(t) and not CJK.search(t) and ' ' not in t and '.' not in t
            and ',' not in t and '-' not in t and t.isalpha() and 2 <= len(t) <= 12)


def looks_like_given(t):
    """看起來是「名」而不是另一個人：含點（縮寫）、含空白（名 + 中間名），
    或是有連字號的中文名（`Chien-Lung`）。"""
    t = (t or '').strip()
    return bool(t) and not CJK.search(t) and ('.' in t or ' ' in t or '-' in t) \
        and not is_bare_latin_surname(t)


def is_fragment(name):
    """這個名字有沒有辦法指認一個人。只有姓＋縮寫（`Chen, H.-J.`、`Wu, S. H`）算碎片。"""
    n = (name or '').strip()
    if not n or CJK.search(n):
        return not n
    toks = [t for t in re.split(r'[^A-Za-z]+', n) if t]
    if len(toks) < 2:
        return True
    if ',' in n:
        given = toks[1:]
    else:
        given = toks[:-1]
    return not any(len(g) >= 2 for g in given)


def resplit(raw):
    """把被切錯的名單接回去。"""
    parts = [x.strip().rstrip('*＊') for x in (raw or '').split('|')]
    parts = [x for x in parts if x]
    out = []
    i = 0
    while i < len(parts):
        cur = parts[i]
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        cur = re.sub(r'^(and|與|及)\s+', '', cur, flags=re.I)
        if nxt and is_bare_latin_surname(cur) and looks_like_given(nxt):
            out.append(f'{cur}, {nxt}')
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def build_resolver():
    nodes = rd('collab_network', 'output', 'author_teacher_id_by_gpt.csv')
    exact, bysur = {}, collections.defaultdict(set)
    for n in nodes:
        names = [n['name_zh'], n['name_en']] + json.loads(n['aliases_json'] or '[]')
        for nm in names:
            if not nm:
                continue
            k = nkey(nm)
            if k:
                exact.setdefault(k, n['node_id'])
            sk = surname_key(nm)
            if sk:
                bysur[sk].add(n['node_id'])

    created = {}

    def resolve(name):
        """回傳 (node_id, 是否新建)。指認不出來的碎片回傳 (None, False)。

        對到既有的 `EXT-U-` 節點**不算對到** —— 那是上游放棄指認時留下的佔位節點，
        沿用它等於把這個人丟回未解析狀態。名字只要看得出是誰（有完整的名，不是只有
        縮寫），就給它一個自己的節點。
        """
        k = nkey(name)
        hit = exact.get(k)
        if hit and not hit.startswith('EXT-U-'):
            return hit, False
        sk = surname_key(name)
        cands = {x for x in bysur.get(sk, ()) if not x.startswith('EXT-U-')} if sk else set()
        if len(cands) == 1:
            return next(iter(cands)), False
        if is_fragment(name):
            return None, False
        if k in created:
            return created[k], False
        nid = 'EXT-N-' + hashlib.sha1(k.encode()).hexdigest()[:16]
        created[k] = nid
        exact[k] = nid
        return nid, True

    return resolve, created


def stage1_fix_author_lists():
    # 讀**上游未修復**的論文表，不是 final_plan/paper/（那份已經套用過修復，
    # 再讀一次會看不到原始的 edge_hold_reason，變成自我抵消）。
    papers = {}
    for r in rd('collab_network', 'output', 'papers.csv'):
        papers[r['paper_id']] = {
            'paper_id': r['paper_id'], 'title': r['title'],
            'n_authors': r['n_authors'], 'edge_hold_reason': r['edge_hold_reason'],
            'author_node_ids_json': r['author_ids_json'],
        }
    srcs = collections.defaultdict(list)
    for r in rd('collab_network', 'output', 'paper_sources.csv'):
        srcs[r['paper_id']].append(r)
    node_name = {n['node_id']: (n['name_zh'] or n['name_en'])
                 for n in rd('collab_network', 'output', 'author_teacher_id_by_gpt.csv')}
    resolve, created = build_resolver()

    rows = []
    for pid, p in papers.items():
        reasons = {x for x in p['edge_hold_reason'].split('|') if x}
        ids = json.loads(p['author_node_ids_json'])
        rule = note = ev = ''
        newids = []

        if 'incomplete_author_list' in reasons:
            rule = 'C_incomplete_web_lookup'
            info = WEB_LOOKUP.get(pid, {'names': [], 'evidence': '未查證'})
            ev = info['evidence']
            ids = [i for i in ids if not i.startswith('EXT-U-')]
            for nm in info['names']:
                nid, isnew = resolve(nm)
                if nid and nid not in ids:
                    ids.append(nid)
                    if isnew:
                        newids.append(nid)
                        node_name[nid] = nm
        elif 'published_author_list_conflict' in reasons:
            rule = 'A_resplit_author_list'
            best = max(srcs[pid], key=lambda s: len(s['original_author_list'] or ''))
            names = resplit(best['original_author_list'])
            ids = []
            dropped = []
            for nm in names:
                nid, isnew = resolve(nm)
                if not nid:
                    dropped.append(nm)
                    continue
                if nid not in ids:
                    ids.append(nid)
                    if isnew:
                        newids.append(nid)
                        node_name[nid] = nm
            ev = 'resplit:' + best['record_id']
            note = ('只有姓＋縮寫、指認不出而移除：' + ' / '.join(dropped)) if dropped else ''
        elif 'unresolved_author_identity_or_fragment' in reasons:
            rule = 'B_drop_unidentifiable'
            drop = [i for i in ids if i.startswith('EXT-U-')]
            ids = [i for i in ids if not i.startswith('EXT-U-')]
            ev = '移除無法辨識的縮寫／碎片 %d 個' % len(drop)
            note = ';'.join(node_name.get(d, d) for d in drop)
        else:
            continue

        # 任何規則都不留 EXT-U-。**保留原始作者順序**——下游的「只取前 10 位」要靠它。
        seen = set()
        ids = [i for i in ids if not i.startswith('EXT-U-')
               and not (i in seen or seen.add(i))]
        raw = srcs[pid][0]['original_author_list'] if srcs[pid] else ''
        rows.append({
            'paper_id': pid, 'rule': rule,
            'n_before': p['n_authors'], 'n_after': len(ids),
            'author_node_ids_json': json.dumps(ids, ensure_ascii=False),
            'author_names_json': json.dumps([node_name.get(i, i) for i in ids], ensure_ascii=False),
            'new_node_ids_json': json.dumps(newids, ensure_ascii=False),
            'original_author_list': raw,
            'resplit_author_list': ' | '.join(resplit(raw)) if rule.startswith('A') else '',
            'evidence': ev, 'note': note,
        })

    os.makedirs(DEC_DIR, exist_ok=True)
    path = os.path.join(DEC_DIR, 'author_list_fixes.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIX_FIELDS)
        w.writeheader()
        w.writerows(rows)

    # 新節點的姓名，build.py 要用來補 external_coauthors
    with open(os.path.join(DEC_DIR, 'new_external_nodes.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['node_id', 'name'])
        for k, nid in sorted(created.items(), key=lambda kv: kv[1]):
            w.writerow([nid, node_name.get(nid, '')])

    c = collections.Counter(r['rule'] for r in rows)
    print('decisions/author_list_fixes.csv：%d 篇' % len(rows))
    for k, v in c.most_common():
        print(f'  {k}: {v}')
    print('  新建的外部節點:', len(created))
    print('  作者數變化：變多 %d、不變 %d、變少 %d' % (
        sum(1 for r in rows if r['n_after'] > int(r['n_before'])),
        sum(1 for r in rows if r['n_after'] == int(r['n_before'])),
        sum(1 for r in rows if r['n_after'] < int(r['n_before']))))
    print('  套用後可建邊（>=2 位作者）:', sum(1 for r in rows if r['n_after'] >= 2))


# ═══════════════════════════════════════════════════════════════
# 階段 2：主建置
# ═══════════════════════════════════════════════════════════════
YEAR_MIN, YEAR_MAX = 2015, 2026
YEARS = list(range(YEAR_MIN, YEAR_MAX + 1))


def up(*p):   return os.path.join(ROOT, *p)
def out(*p):  return os.path.join(FINAL, *p)

# 上游（唯讀）
SRC_PAPERS        = up('collab_network', 'output', 'papers.csv')
SRC_PAPER_AUTHORS = up('collab_network', 'output', 'paper_authors.csv')
SRC_PAPER_SOURCES = up('collab_network', 'output', 'paper_sources.csv')
SRC_NODES         = up('collab_network', 'output', 'author_teacher_id_by_gpt.csv')
SRC_EDGES         = up('collab_network', 'output', 'edges_by_paper.csv')
SRC_NSTC_PUB      = up('collab_network', 'raw_data', 'nstc_publications_2015_2026.csv')
SRC_PROJECTS      = up('collab_pubs', 'raw_data', 'nstc_projects.csv')
SRC_MASTER        = up('faculty_identity', 'faculty_identity_master.csv')
SRC_MAP_ROSTER    = up('faculty_and_map', 'output', 'main_result', 'faculty_roster_final.csv')
SRC_MAP_INST      = up('faculty_and_map', 'output', 'main_result', 'institutions.csv')
SRC_IDENTITY_BY_RECORD = up('collab_network', 'notes_ambiguity', 'review',
                            'identity_changes_by_record.csv')
DEC_AUTHOR_FIXES = out('manual_review', 'decisions', 'author_list_fixes.csv')
DEC_NEW_NODES    = out('manual_review', 'decisions', 'new_external_nodes.csv')


def read(path):
    """讀 CSV，順手把 UTF-8 BOM 從第一個欄名剝掉。"""
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def j(x):
    return json.dumps(x, ensure_ascii=False)


def norm_title(s):
    """計畫名稱正規化：全形轉半形、去空白、去標點。同一個計畫被兩位教師
    各自登錄時，寫法只差在標點與空白的情況很常見。"""
    s = unicodedata.normalize('NFKC', s or '').lower()
    s = re.sub(r'[\s　]+', '', s)
    s = re.sub(r'[^\w一-鿿]', '', s)
    return s


# ─────────────────────────────────────────────────────────────
# 1. 論文層
# ─────────────────────────────────────────────────────────────
def build_papers():
    papers = read(SRC_PAPERS)
    pauthors = read(SRC_PAPER_AUTHORS)
    psources = read(SRC_PAPER_SOURCES)
    nodes = {n['node_id']: n for n in read(SRC_NODES)}

    authors_of = collections.defaultdict(list)
    for r in pauthors:
        authors_of[r['paper_id']].append(r)
    owners_of = collections.defaultdict(list)
    for r in psources:
        owners_of[r['paper_id']].append(r)

    rows = []
    for p in papers:
        dates = json.loads(p['publication_dates_json'])
        years = sorted({d[:4] for d in dates if d[:4].isdigit()})
        if not years:
            raise SystemExit(f'論文沒有可用年份: {p["paper_id"]}')
        year = int(years[0])                      # 取最早年：跨版本時以最早出現為準
        aus = sorted(authors_of[p['paper_id']], key=lambda r: (r['teacher_id'] == '', r['node_id']))
        node_ids = [a['node_id'] for a in aus]
        tids = [a['teacher_id'] for a in aus if a['teacher_id']]
        names = [nodes[n]['name_zh'] or nodes[n]['name_en'] for n in node_ids if n in nodes]
        owners = sorted({o['owner_teacher_id'] for o in owners_of[p['paper_id']] if o['owner_teacher_id']})
        rows.append({
            'paper_id': p['paper_id'],
            'year': year,
            'year_ambiguous': int(len(years) > 1),
            'year_candidates_json': j(years),
            'title': p['title'],
            'doi': p['doi'],
            'pub_category': p['pub_category'],
            'venue': p['venue'],
            'n_authors': p['n_authors'],
            'n_roster_authors': len(tids),
            'author_node_ids_json': j(node_ids),
            'author_names_json': j(names),
            'teacher_ids_json': j(sorted(tids)),
            'edge_eligible': p['edge_eligible'],
            'edge_hold_reason': p['edge_hold_reason'],
            'author_list_complete': p['author_list_complete'],
            'dedup_basis': p['dedup_basis'],
            'owner_teacher_ids_json': j(owners),
            'canonical_record_id': p['canonical_record_id'],
            'source_record_ids_json': p['source_record_ids_json'],
            'source_record_count': p['source_record_count'],
        })
    rows.sort(key=lambda r: (r['year'], r['paper_id']))
    return rows


# ── 1b. 人工裁定（2026-09-10）────────────────────────────────
# 這一節把使用者查核完的規則寫進流程。每一條都標明是哪一條裁定。
BLOCKING_REASONS = {'unresolved_author_identity_or_fragment',
                    'published_author_list_conflict',
                    'publication_version_uncertain',
                    'incomplete_author_list'}


def record_author_sets():
    """record_id → 這一筆填報實際解析出來的作者節點集合。
    空值與 `EXT-U-`（未解析的縮寫／碎片）不算在內。"""
    g = collections.defaultdict(set)
    for r in read(SRC_IDENTITY_BY_RECORD):
        nid = r['new_node_id'].strip()
        if nid and not nid.startswith('EXT-U-'):
            g[r['record_id']].add(nid)
    return g


MAX_AUTHORS = 10


def _name_keys(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^0-9a-z一-鿿]', '', s.lower())


def truncate_large_papers(papers):
    """作者超過 MAX_AUTHORS 位的論文只留前 MAX_AUTHORS 位。

    順序取自原始填報的作者欄；在名單裡找不到對應的節點排在最後（順序不明者最後砍）。
    """
    log = collections.Counter()
    nodes = {n['node_id']: n for n in read(SRC_NODES)}
    key2node = {}
    for n in nodes.values():
        for nm in [n['name_zh'], n['name_en']] + json.loads(n['aliases_json'] or '[]'):
            k = _name_keys(nm)
            if k:
                key2node.setdefault(k, n['node_id'])
    order_src = collections.defaultdict(list)
    for r in read(SRC_PAPER_SOURCES):
        order_src[r['paper_id']].append(r)

    for p in papers:
        ids = json.loads(p['author_node_ids_json'])
        if len(ids) <= MAX_AUTHORS:
            continue
        pos = {}
        for src in sorted(order_src.get(p['paper_id'], []),
                          key=lambda r: r['is_representative'] != '1'):
            for i, nm in enumerate((src['original_author_list'] or '').split('|')):
                nid = key2node.get(_name_keys(nm.strip().rstrip('*＊')))
                if nid and nid not in pos:
                    pos[nid] = i
            if pos:
                break
        cur = {x: i for i, x in enumerate(ids)}      # 現有順序當次要依據（修復過的論文是對的）
        ordered = sorted(ids, key=lambda x: (pos.get(x, 10 ** 6), cur[x]))
        kept = ordered[:MAX_AUTHORS]
        p['author_node_ids_json'] = j(kept)
        p['n_authors'] = len(kept)
        p['decision_notes'] = ((p.get('decision_notes', '') + ';') if p.get('decision_notes') else '') \
            + f'作者 {len(ids)} 位，只取前 {MAX_AUTHORS} 位'
        log['作者 >10 位截斷'] += 1
    return log


def apply_paper_decisions(papers):
    """裁定 3：同標題**且同作者**的算同一篇。
       裁定 6a：`possible_publication_version_duplicate` 因此解除。
       裁定 6b：`conflicting_author_sets` 取最大的那一組作者集合。

    同標題但作者集合不同的**不合併**（使用者的裁定明確加了「且同作者」），
    它們維持分開、維持旗標。
    """
    rec_sets = record_author_sets()
    log = collections.Counter()

    # 6b：先把 conflicting_author_sets 的作者集合換成最大的一組
    for r in papers:
        if 'conflicting_author_sets' not in r['edge_hold_reason']:
            continue
        rids = json.loads(r['source_record_ids_json'])
        best = max((rec_sets.get(x, set()) for x in rids), key=len, default=set())
        if len(best) >= 2:
            r['author_node_ids_json'] = j(sorted(best))
            r['n_authors'] = len(best)
            r['edge_hold_reason'] = '|'.join(x for x in r['edge_hold_reason'].split('|')
                                             if x and x != 'conflicting_author_sets')
            r['decision_notes'] = 'conflicting_author_sets→取最大集合(%d人)' % len(best)
            log['取最大作者集合'] += 1

    # 3 + 6a：同標題同作者合併
    groups = collections.defaultdict(list)
    for r in papers:
        k = norm_title(r['title'])
        if k:
            groups[k].append(r)

    merged_away = set()
    for k, v in groups.items():
        if len(v) < 2:
            continue
        by_authors = collections.defaultdict(list)
        for r in v:
            by_authors[tuple(sorted(json.loads(r['author_node_ids_json'])))].append(r)
        for aset, rs in by_authors.items():
            if len(rs) < 2:
                continue
            # 保留有 DOI 的、來源列最多的、年份最早的那一篇當代表
            keep = sorted(rs, key=lambda r: (bool(r['doi']), int(r['source_record_count']),
                                             -r['year']), reverse=True)[0]
            others = [r for r in rs if r is not keep]
            rids = sorted({x for r in rs for x in json.loads(r['source_record_ids_json'])})
            years = sorted({y for r in rs for y in json.loads(r['year_candidates_json'])})
            keep['source_record_ids_json'] = j(rids)
            keep['source_record_count'] = len(rids)
            keep['year'] = int(years[0])
            keep['year_candidates_json'] = j(years)
            keep['year_ambiguous'] = int(len(years) > 1)
            keep['merged_paper_ids_json'] = j(sorted(r['paper_id'] for r in others))
            keep['doi'] = keep['doi'] or next((r['doi'] for r in others if r['doi']), '')
            keep['venue'] = keep['venue'] or next((r['venue'] for r in others if r['venue']), '')
            keep['decision_notes'] = ((keep.get('decision_notes', '') + ';') if keep.get('decision_notes') else '') \
                + '同標題同作者合併%d篇' % len(rs)
            # 6a：重複版本的疑慮因此解除
            keep['edge_hold_reason'] = '|'.join(
                x for x in keep['edge_hold_reason'].split('|')
                if x and x != 'possible_publication_version_duplicate')
            merged_away.update(r['paper_id'] for r in others)
            log['同標題同作者合併'] += len(others)

    papers = [r for r in papers if r['paper_id'] not in merged_away]

    # 裁定 1/2/3（2026-09-10）：作者名單修復
    # （`code/fix_author_lists.py` 產生，內容可逐列檢查）
    fixes = {}
    if os.path.exists(DEC_AUTHOR_FIXES):
        with open(DEC_AUTHOR_FIXES, newline='', encoding='utf-8-sig') as f:
            fixes = {r['paper_id']: r for r in csv.DictReader(f)}
    by_id = {r['paper_id']: r for r in papers}
    for pid, fx in fixes.items():
        r = by_id.get(pid)
        if r is None:                     # 已被合併掉的論文
            continue
        ids = json.loads(fx['author_node_ids_json'])
        r['author_node_ids_json'] = j(ids)
        r['n_authors'] = len(ids)
        r['edge_hold_reason'] = '|'.join(
            x for x in r['edge_hold_reason'].split('|')
            if x and x not in ('published_author_list_conflict',
                               'unresolved_author_identity_or_fragment',
                               'incomplete_author_list'))
        r['decision_notes'] = ((r.get('decision_notes', '') + ';') if r.get('decision_notes') else '') \
            + fx['rule'] + ('(' + fx['note'][:60] + ')' if fx['note'] else '')
        log['作者名單修復:' + fx['rule'][:1]] += 1

    # 裁定（2026-09-10 第三輪）：**任何論文只要作者超過 10 位，就只取前 10 位**。
    # 巨型合著論文會用 C(n,2) 把邊數炸開——修復前 23 篇 >10 位的論文就佔了全部邊的 26%，
    # 其中一篇 72 位作者的論文一篇就 2,556 條。截到 10 位之後上限是 45 條。
    # 「前 10 位」看的是**原始填報的作者順序**，不是節點 id 的字典序。
    log.update(truncate_large_papers(papers))

    # 解除旗標後重新判定能不能建邊
    for r in papers:
        left = {x for x in r['edge_hold_reason'].split('|') if x} & BLOCKING_REASONS
        was = r['edge_eligible']
        r['edge_eligible'] = '0' if left else '1'
        if was == '0' and r['edge_eligible'] == '1':
            log['解除封鎖、恢復建邊'] += 1
        r.setdefault('merged_paper_ids_json', '[]')
        r.setdefault('decision_notes', '')
    return papers, log


PAPER_FIELDS = ['paper_id', 'year', 'year_ambiguous', 'year_candidates_json', 'title', 'doi',
                'pub_category', 'venue', 'n_authors', 'n_roster_authors',
                'author_node_ids_json', 'author_names_json', 'teacher_ids_json',
                'edge_eligible', 'edge_hold_reason', 'author_list_complete', 'dedup_basis',
                'owner_teacher_ids_json', 'canonical_record_id',
                'source_record_ids_json', 'source_record_count',
                'merged_paper_ids_json', 'decision_notes']


# ─────────────────────────────────────────────────────────────
# 2. 計畫層
# ─────────────────────────────────────────────────────────────
def build_projects():
    """計畫沒有 project id。同一個計畫由參與的每位教師各自登錄成一列，
    只能用「正規化標題 + 民國年度」把它們認回同一個計畫。"""
    raw = read(SRC_PROJECTS)
    sub = []
    for r in raw:
        y = r['roc_year'].strip()
        if not y.isdigit():
            continue
        yr = int(y) + 1911
        if YEAR_MIN <= yr <= YEAR_MAX:
            r['_year'] = yr
            r['_key'] = norm_title(r['project_title'])
            sub.append(r)

    groups = collections.defaultdict(list)
    for r in sub:
        groups[(r['_key'], r['_year'])].append(r)

    # 裁定 1（2026-09-10）：**同名就是同一個計畫，即使登錄年度不同**。
    # 所以合作關係看的是「家族」（同標題的所有年度合起來），不是單一年度的群組。
    # 年度列仍然保留一年一列，因為多年期計畫本來就是逐年核定、逐年填報。
    fam = collections.defaultdict(lambda: {'teachers': set(), 'years': set(),
                                           'records': set(), 'title': ''})
    for r in sub:
        f = fam[r['_key']]
        f['teachers'].add(r['teacher_id'])
        f['years'].add(r['_year'])
        f['records'].add(r['record_id'])
        if len(r['project_title']) > len(f['title']):
            f['title'] = r['project_title']
    fam_year_members = collections.defaultdict(set)
    for r in sub:
        fam_year_members[(r['_key'], r['_year'])].add(r['teacher_id'])

    rows = []
    for (key, yr), recs in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        pk = 'J-%s-%s' % (yr, hashlib.sha1(key.encode()).hexdigest()[:12])
        members, roles, names, rids, cats, discs = [], [], [], [], [], []
        for r in sorted(recs, key=lambda r: r['teacher_id']):
            members.append(r['teacher_id'])
            roles.append(r['role'])
            names.append(r['name_zh'])
            rids.append(r['record_id'])
            cats.append(r['grant_category'])
            discs.append(r['discipline_code'])
        uniq_members = sorted(set(members))
        f = fam[key]
        rows.append({
            'project_key': pk,
            'project_family_key': 'JF-' + hashlib.sha1(key.encode()).hexdigest()[:12],
            'family_years': ';'.join(str(y) for y in sorted(f['years'])),
            'family_n_members': len(f['teachers']),
            'family_member_teacher_ids_json': j(sorted(f['teachers'])),
            'year': yr,
            'roc_year': recs[0]['roc_year'],
            'project_title': max((r['project_title'] for r in recs), key=len),
            'project_title_normalized': key,
            'grant_category': collections.Counter(c for c in cats if c).most_common(1)[0][0] if any(cats) else '',
            'discipline_code': collections.Counter(d for d in discs if d).most_common(1)[0][0] if any(discs) else '',
            'n_roster_members': len(uniq_members),
            'is_multi_teacher': int(len(uniq_members) > 1),
            'member_teacher_ids_json': j(uniq_members),
            'member_names_json': j(sorted(set(names))),
            'member_roles_json': j(sorted({f'{m}:{ro}' for m, ro in zip(members, roles)})),
            'source_record_ids_json': j(sorted(rids)),
            'source_record_count': len(rids),
        })
    return rows, fam, fam_year_members


PROJECT_FIELDS = ['project_key', 'project_family_key', 'family_years', 'family_n_members',
                  'family_member_teacher_ids_json', 'year', 'roc_year', 'project_title', 'project_title_normalized',
                  'grant_category', 'discipline_code', 'n_roster_members', 'is_multi_teacher',
                  'member_teacher_ids_json', 'member_names_json', 'member_roles_json',
                  'source_record_ids_json', 'source_record_count']


# ─────────────────────────────────────────────────────────────
# 3. 兩層的邊
# ─────────────────────────────────────────────────────────────
def build_paper_edges(papers):
    """由論文表直接生成邊。人工裁定會合併論文、也會解除封鎖，
    所以不能再沿用上游凍結的邊表；改成每次從作者名單重算。
    （未套用裁定前，這個算法與上游 `edges_by_paper.csv` 的 13,794 列逐列相同。）"""
    rows = []
    for p in papers:
        if p['edge_eligible'] != '1':
            continue
        a = sorted(json.loads(p['author_node_ids_json']))
        n = len(a)
        if n < 2:
            continue
        for x, y in itertools.combinations(a, 2):
            rows.append({
                'edge_id': 'E-' + hashlib.sha1(f'{p["paper_id"]}|{x}|{y}'.encode()).hexdigest()[:20],
                'year': p['year'],
                'paper_id': p['paper_id'],
                'record_id': p['canonical_record_id'],
                'source_node_id': x, 'target_node_id': y,
                'source_teacher_id': x if not x.startswith('EXT') else '',
                'target_teacher_id': y if not y.startswith('EXT') else '',
                'both_roster': int(not x.startswith('EXT') and not y.startswith('EXT')),
                'n_authors': n,
                'weight_1n': round(1.0 / n, 8),                   # 每位作者 1/n
                'weight_pair': round(2.0 / (n * (n - 1)), 8),     # 每篇論文總權重 = 1
                'source_record_ids_json': p['source_record_ids_json'],
            })
    rows.sort(key=lambda r: (r['year'], r['edge_id']))
    return rows


PAPER_EDGE_FIELDS = ['edge_id', 'year', 'paper_id', 'record_id', 'source_node_id', 'target_node_id',
                     'source_teacher_id', 'target_teacher_id', 'both_roster', 'n_authors',
                     'weight_1n', 'weight_pair', 'source_record_ids_json']


def build_project_edges(projects, fam, fam_year_members):
    """裁定 1：同名即同一個計畫，跨年度也算。所以邊建在「家族」上。

    多年期計畫逐年填報，一條合作關係會在該家族活躍的每一年各出一列，
    `both_recorded_this_year` 標明那一年是不是兩個人都自己登錄了這筆計畫。
    要嚴格一點就篩 `both_recorded_this_year == 1`。
    """
    title_of = {}
    meta = {}
    for p in projects:
        title_of[p['project_family_key']] = p['project_title']
        meta.setdefault(p['project_family_key'], (p['grant_category'], p['discipline_code']))
    key_of = {'JF-' + hashlib.sha1(k.encode()).hexdigest()[:12]: k for k in fam}

    rows = []
    for fk, k in key_of.items():
        f = fam[k]
        members = sorted(f['teachers'])
        if len(members) < 2:
            continue
        n = len(members)
        cat, disc = meta.get(fk, ('', ''))
        for yr in sorted(f['years']):
            here = fam_year_members.get((k, yr), set())
            for x, y in itertools.combinations(members, 2):
                rows.append({
                    'edge_id': 'JE-' + hashlib.sha1(f'{fk}|{yr}|{x}|{y}'.encode()).hexdigest()[:16],
                    'year': yr,
                    'project_family_key': fk,
                    'project_title': title_of.get(fk, ''),
                    'family_years': ';'.join(str(z) for z in sorted(f['years'])),
                    'grant_category': cat, 'discipline_code': disc,
                    'source_node_id': x, 'target_node_id': y,
                    'source_teacher_id': x, 'target_teacher_id': y,
                    'both_roster': 1,
                    'n_members': n,
                    'both_recorded_this_year': int(x in here and y in here),
                    'weight_1n': round(1.0 / n, 8),
                    'weight_pair': round(2.0 / (n * (n - 1)), 8),
                    'source_record_ids_json': j(sorted(f['records'])),
                })
    rows.sort(key=lambda r: (r['year'], r['edge_id']))
    return rows


PROJECT_EDGE_FIELDS = ['edge_id', 'year', 'project_family_key', 'project_title', 'family_years',
                       'grant_category', 'discipline_code', 'source_node_id', 'target_node_id',
                       'source_teacher_id', 'target_teacher_id', 'both_roster', 'n_members',
                       'both_recorded_this_year', 'weight_1n', 'weight_pair',
                       'source_record_ids_json']


# ─────────────────────────────────────────────────────────────
# 4. 名冊
# ─────────────────────────────────────────────────────────────
PROF_FIELDS = ['teacher_id', 'name_zh', 'name_en_canonical', 'activity_status',
               'institution_code', 'institution_zh', 'department_zh', 'unit_name',
               'program', 'appointment', 'rank', 'expertise_text', 'field_label',
               'county', 'campus', 'lat', 'lon', 'has_geo',
               'main_discipline_2015_2026', 'n_disciplines_2015_2026',
               'n_papers', 'n_papers_edge_eligible', 'first_pub_year', 'last_pub_year',
               'papers_by_year_json', 'n_projects', 'n_projects_as_pi', 'n_projects_as_copi',
               'first_proj_year', 'last_proj_year', 'projects_by_year_json',
               'pub_degree_all', 'pub_degree_teacher', 'pub_strength_1n', 'pub_paper_count',
               'proj_degree', 'proj_project_count',
               'official_email', 'orcid', 'nstc_url', 'official_profile_url',
               'personal_website', 'cv_url', 'profile_url_shared_by',
               'identity_status', 'identity_confidence']


def build_professors(papers, projects, paper_edges, project_edges):
    master = {r['teacher_id']: r for r in read(SRC_MASTER)}
    mp = {r['教師ID']: r for r in read(SRC_MAP_ROSTER)}
    # 名冊裡的系所頁網址有 32 個被 2 人以上共用（那是系所師資列表，不是個人頁），
    # 記下共用人數，前端才不會把整個系的列表當成某個人的個人頁。
    share = collections.Counter((m.get('official_profile_url') or '').strip()
                                for m in master.values()
                                if (m.get('official_profile_url') or '').strip())

    # 論文活動
    pap_years = collections.defaultdict(collections.Counter)
    pap_elig = collections.Counter()
    for p in papers:
        for t in json.loads(p['teacher_ids_json']):
            pap_years[t][p['year']] += 1
            if p['edge_eligible'] == '1':
                pap_elig[t] += 1

    # 計畫活動（逐筆原始紀錄，不是去重後的計畫，因為多年期本來就逐年一筆）
    proj_years = collections.defaultdict(collections.Counter)
    proj_role = collections.defaultdict(collections.Counter)
    disc = collections.defaultdict(collections.Counter)
    for r in read(SRC_PROJECTS):
        y = r['roc_year'].strip()
        if not y.isdigit():
            continue
        yr = int(y) + 1911
        if not (YEAR_MIN <= yr <= YEAR_MAX):
            continue
        proj_years[r['teacher_id']][yr] += 1
        proj_role[r['teacher_id']][r['role']] += 1
        if r['discipline_code'].strip():
            disc[r['teacher_id']][r['discipline_code'].strip()] += 1

    # 度數
    deg_all, deg_teacher, strength, pcount = (collections.defaultdict(set), collections.defaultdict(set),
                                              collections.Counter(), collections.defaultdict(set))
    for e in paper_edges:
        for me, other, otid in ((e['source_teacher_id'], e['target_node_id'], e['target_teacher_id']),
                                (e['target_teacher_id'], e['source_node_id'], e['source_teacher_id'])):
            if not me:
                continue
            deg_all[me].add(other)
            if otid:
                deg_teacher[me].add(otid)
            strength[me] += e['weight_1n']
            pcount[me].add(e['paper_id'])
    jdeg, jcount = collections.defaultdict(set), collections.defaultdict(set)
    for e in project_edges:
        jdeg[e['source_teacher_id']].add(e['target_teacher_id'])
        jdeg[e['target_teacher_id']].add(e['source_teacher_id'])
        jcount[e['source_teacher_id']].add(e['project_family_key'])
        jcount[e['target_teacher_id']].add(e['project_family_key'])

    active, inactive = [], []
    for tid, m in sorted(master.items()):
        g = mp.get(tid, {})
        py, jy = pap_years.get(tid, {}), proj_years.get(tid, {})
        has_p, has_j = bool(py), bool(jy)
        status = ('both' if has_p and has_j else
                  'paper_only' if has_p else
                  'project_only' if has_j else 'none')
        lat, lon = g.get('緯度lat', ''), g.get('經度lon', '')
        row = {
            'teacher_id': tid,
            'name_zh': m['name_zh'],
            'name_en_canonical': m['name_en_canonical'],
            'activity_status': status,
            'institution_code': g.get('機構代碼', ''),
            'institution_zh': m['institution_zh'] or g.get('機構名稱', ''),
            'department_zh': m['department_zh'],
            'unit_name': g.get('資料單位名稱', ''),
            'program': g.get('所屬學程', ''),
            'appointment': g.get('專兼任', ''),
            'rank': g.get('聘書職級', ''),
            'expertise_text': g.get('學術專長及研究', ''),
            'field_label': g.get('領域分類', ''),
            'county': g.get('縣市', ''),
            'campus': g.get('校區', ''),
            'lat': lat, 'lon': lon,
            'has_geo': int(bool(lat and lon)),
            'main_discipline_2015_2026': disc[tid].most_common(1)[0][0] if disc.get(tid) else '',
            'n_disciplines_2015_2026': len(disc.get(tid, {})),
            'n_papers': sum(py.values()),
            'n_papers_edge_eligible': pap_elig.get(tid, 0),
            'first_pub_year': min(py) if py else '',
            'last_pub_year': max(py) if py else '',
            'papers_by_year_json': j({str(y): py.get(y, 0) for y in YEARS}),
            'n_projects': sum(jy.values()),
            'n_projects_as_pi': proj_role[tid].get('計畫主持人', 0),
            'n_projects_as_copi': proj_role[tid].get('共同主持人', 0),
            'first_proj_year': min(jy) if jy else '',
            'last_proj_year': max(jy) if jy else '',
            'projects_by_year_json': j({str(y): jy.get(y, 0) for y in YEARS}),
            'pub_degree_all': len(deg_all.get(tid, ())),
            'pub_degree_teacher': len(deg_teacher.get(tid, ())),
            'pub_strength_1n': round(strength.get(tid, 0.0), 6),
            'pub_paper_count': len(pcount.get(tid, ())),
            'proj_degree': len(jdeg.get(tid, ())),
            'proj_project_count': len(jcount.get(tid, ())),
            'official_email': m['official_email'],
            'orcid': m['orcid'],
            'nstc_url': m['nstc_url'],
            'official_profile_url': m.get('official_profile_url', ''),
            'personal_website': m.get('personal_website', ''),
            'cv_url': m.get('cv_url', ''),
            'profile_url_shared_by': share.get((m.get('official_profile_url') or '').strip(), 0),
            'identity_status': m['identity_status'],
            'identity_confidence': m['identity_confidence'],
        }
        (active if status != 'none' else inactive).append(row)
    return active, inactive


EXT_FIELDS = ['node_id', 'name_zh', 'name_en', 'identity_status', 'identity_name_quality',
              'institutions_json', 'orcid_json', 'openalex_author_ids_json', 'aliases_json',
              'in_edge_network', 'n_papers', 'degree_all', 'degree_teacher', 'strength_1n',
              'first_pub_year', 'last_pub_year', 'papers_by_year_json',
              'same_name_candidate_node_ids_json', 'source_record_ids_json']


def build_externals(papers, paper_edges):
    nodes = [n for n in read(SRC_NODES) if n['node_type'] == 'external']
    # 作者名單修復時新建的節點（`EXT-N-`）：名字讀得出來、但上游沒有替它開節點
    if os.path.exists(DEC_NEW_NODES):
        with open(DEC_NEW_NODES, newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                nm = r['name']
                nodes.append({
                    'node_id': r['node_id'], 'node_type': 'external',
                    'name_zh': nm if re.search(r'[一-鿿]', nm) else '',
                    'name_en': '' if re.search(r'[一-鿿]', nm) else nm,
                    'identity_status': 'from_author_list_repair',
                    'identity_name_quality': 'full',
                    'institutions_json': '[]', 'orcid_json': '[]',
                    'openalex_author_ids_json': '[]', 'aliases_json': j([nm]),
                    'in_edge_network': '1', 'same_name_candidate_node_ids_json': '[]',
                    'source_record_ids_json': '[]',
                })
    years = collections.defaultdict(collections.Counter)
    for p in papers:
        for nid in json.loads(p['author_node_ids_json']):
            years[nid][p['year']] += 1
    deg_all, deg_t, stre = collections.defaultdict(set), collections.defaultdict(set), collections.Counter()
    for e in paper_edges:
        for me, other, otid in ((e['source_node_id'], e['target_node_id'], e['target_teacher_id']),
                                (e['target_node_id'], e['source_node_id'], e['source_teacher_id'])):
            deg_all[me].add(other)
            if otid:
                deg_t[me].add(otid)
            stre[me] += e['weight_1n']
    rows = []
    for n in nodes:
        y = years.get(n['node_id'], {})
        rows.append({
            'node_id': n['node_id'],
            'name_zh': n['name_zh'], 'name_en': n['name_en'],
            'identity_status': n['identity_status'],
            'identity_name_quality': n['identity_name_quality'],
            'institutions_json': n['institutions_json'],
            'orcid_json': n['orcid_json'],
            'openalex_author_ids_json': n['openalex_author_ids_json'],
            'aliases_json': n['aliases_json'],
            'in_edge_network': n['in_edge_network'],
            'n_papers': sum(y.values()),
            'degree_all': len(deg_all.get(n['node_id'], ())),
            'degree_teacher': len(deg_t.get(n['node_id'], ())),
            'strength_1n': round(stre.get(n['node_id'], 0.0), 6),
            'first_pub_year': min(y) if y else '',
            'last_pub_year': max(y) if y else '',
            'papers_by_year_json': j({str(yy): y.get(yy, 0) for yy in YEARS}),
            'same_name_candidate_node_ids_json': n['same_name_candidate_node_ids_json'],
            'source_record_ids_json': n['source_record_ids_json'],
        })
    rows.sort(key=lambda r: (-r['n_papers'], r['node_id']))
    return rows


# ─────────────────────────────────────────────────────────────
# 5. 地圖
# ─────────────────────────────────────────────────────────────
GEO_FIELDS = ['teacher_id', 'name_zh', 'activity_status', 'institution_code', 'institution_name',
              'unit_name', 'campus', 'county', 'lat', 'lon', 'has_geo']
INST_FIELDS = ['institution_code', 'institution_name', 'institution_en', 'county', 'lat', 'lon',
               'n_roster', 'n_active', 'n_papers', 'n_projects',
               'n_internal_pub_edges', 'n_external_pub_edges']


def build_map(active, inactive, paper_edges, project_edges):
    inst_src = {r['機構代碼']: r for r in read(SRC_MAP_INST)}
    geo = [{'teacher_id': r['teacher_id'], 'name_zh': r['name_zh'],
            'activity_status': r['activity_status'],
            'institution_code': r['institution_code'], 'institution_name': r['institution_zh'],
            'unit_name': r['unit_name'], 'campus': r['campus'], 'county': r['county'],
            'lat': r['lat'], 'lon': r['lon'], 'has_geo': r['has_geo']}
           for r in active]

    inst_of = {r['teacher_id']: r['institution_code'] for r in active + inactive}
    n_roster, n_active = collections.Counter(), collections.Counter()
    n_pap, n_proj = collections.Counter(), collections.Counter()
    for r in active + inactive:
        n_roster[r['institution_code']] += 1
    for r in active:
        n_active[r['institution_code']] += 1
        n_pap[r['institution_code']] += r['n_papers']
        n_proj[r['institution_code']] += r['n_projects']
    internal, external = collections.Counter(), collections.Counter()
    for e in paper_edges:
        a, b = e['source_teacher_id'], e['target_teacher_id']
        if not (a and b):
            continue
        ia, ib = inst_of.get(a), inst_of.get(b)
        if ia and ia == ib:
            internal[ia] += 1
        else:
            for i in (ia, ib):
                if i:
                    external[i] += 1
    rows = []
    for code in sorted({r['institution_code'] for r in active + inactive if r['institution_code']}):
        s = inst_src.get(code, {})
        rows.append({
            'institution_code': code,
            'institution_name': s.get('機構名稱', ''),
            'institution_en': s.get('英文名稱', ''),
            'county': s.get('縣市', ''),
            'lat': s.get('緯度lat', ''), 'lon': s.get('經度lon', ''),
            'n_roster': n_roster[code], 'n_active': n_active[code],
            'n_papers': n_pap[code], 'n_projects': n_proj[code],
            'n_internal_pub_edges': internal[code], 'n_external_pub_edges': external[code],
        })
    return geo, rows


# ─────────────────────────────────────────────────────────────
def stage2_build():
    papers = build_papers()
    papers, decisions_log = apply_paper_decisions(papers)
    projects, fam, fam_year_members = build_projects()
    paper_edges = build_paper_edges(papers)
    project_edges = build_project_edges(projects, fam, fam_year_members)
    active, inactive = build_professors(papers, projects, paper_edges, project_edges)
    externals = build_externals(papers, paper_edges)
    geo, insts = build_map(active, inactive, paper_edges, project_edges)

    # ── 驗收（不通過就中止，不留半套輸出）
    checks = []
    by_year_p = collections.Counter(p['year'] for p in papers)
    by_year_j = collections.Counter(p['year'] for p in projects)
    assert sum(by_year_p.values()) == len(papers)
    assert len({p['paper_id'] for p in papers}) == len(papers), 'paper_id 重複'
    assert all(YEAR_MIN <= p['year'] <= YEAR_MAX for p in papers), '有論文年份落在區間外'
    checks.append(('論文年份全在 %d–%d' % (YEAR_MIN, YEAR_MAX), len(papers)))

    ids_a = {r['teacher_id'] for r in active}
    ids_i = {r['teacher_id'] for r in inactive}
    assert not (ids_a & ids_i) and len(ids_a) + len(ids_i) == 520, '名冊拆分不完整'
    checks.append(('active + inactive = 名冊 520 且無交集', f'{len(ids_a)} + {len(ids_i)}'))

    et = {t for e in paper_edges for t in (e['source_teacher_id'], e['target_teacher_id']) if t}
    et |= {t for e in project_edges for t in (e['source_teacher_id'], e['target_teacher_id'])}
    assert et <= ids_a, '邊上有不在 active 名冊的 teacher_id: %s' % sorted(et - ids_a)[:5]
    checks.append(('邊上的 teacher_id 都在 active 名冊', len(et)))

    known = ids_a | {r['node_id'] for r in externals}
    en = {n for e in paper_edges for n in (e['source_node_id'], e['target_node_id'])}
    assert en <= known, '邊上有無主的 node_id'
    checks.append(('邊上的 node_id 都有節點資料', len(en)))

    valid_rec = {r['record_id'] for r in read(SRC_NSTC_PUB)}
    bad = {e['record_id'] for e in paper_edges} - valid_rec
    assert not bad, '邊指向不存在的 NSTC record_id: %s' % sorted(bad)[:5]
    checks.append(('邊的 record_id 都回得到 NSTC 原始填報', len(valid_rec)))

    nogeo = [r['teacher_id'] for r in active if not r['has_geo']]
    checks.append(('active 教師缺座標', f'{len(nogeo)} 人' + (f' → {nogeo[:5]}' if nogeo else '')))

    # ── 寫出
    n = {}
    n['paper/papers_all.csv'] = write(out('paper', 'papers_all.csv'), papers, PAPER_FIELDS)
    for y in YEARS:
        rows = [p for p in papers if p['year'] == y]
        n[f'paper/papers_{y}.csv'] = write(out('paper', f'papers_{y}.csv'), rows, PAPER_FIELDS)
    assert sum(v for k, v in n.items() if k.startswith('paper/papers_2')) == len(papers)

    n['project/projects_all.csv'] = write(out('project', 'projects_all.csv'), projects, PROJECT_FIELDS)
    for y in YEARS:
        rows = [p for p in projects if p['year'] == y]
        n[f'project/projects_{y}.csv'] = write(out('project', f'projects_{y}.csv'), rows, PROJECT_FIELDS)

    # 主檔：名冊 active 教師與外部共同作者放同一張表，用 node_type 分。
    # 兩層網路的節點都在這裡，做分析只要開這一個檔。
    for r in active:
        r['node_id'], r['node_type'] = r['teacher_id'], 'roster'
    for r in externals:
        r['node_type'] = 'external'
    MF = master_fields(PROF_FIELDS, EXT_FIELDS)
    n['professor_demo/authors_master.csv'] = write_master(active + externals, MF)
    n['professor_demo/professors_inactive.csv'] = write(INACTIVE, inactive, PROF_FIELDS)
    n['network/paper_network_edges.csv'] = write(out('network', 'paper_network_edges.csv'), paper_edges, PAPER_EDGE_FIELDS)
    n['network/project_network_edges.csv'] = write(out('network', 'project_network_edges.csv'), project_edges, PROJECT_EDGE_FIELDS)
    n['map/professor_geo.csv'] = write(out('map', 'professor_geo.csv'), geo, GEO_FIELDS)
    n['map/institutions.csv'] = write(out('map', 'institutions.csv'), insts, INST_FIELDS)

    print('=== 驗收 ===')
    for k, v in checks:
        print(f'  OK  {k}: {v}')
    print('\n=== 產出 ===')
    for k in sorted(n):
        print(f'  {n[k]:>6}  {k}')
    print('\n=== 逐年 ===')
    print('  年份   論文   計畫   共著邊  計畫邊')
    ep = collections.Counter(e['year'] for e in paper_edges)
    ej = collections.Counter(e['year'] for e in project_edges)
    for y in YEARS:
        print(f'  {y}  {by_year_p[y]:5}  {by_year_j[y]:5}  {ep[y]:6}  {ej[y]:5}')
    print(f'\n  active {len(active)} / inactive {len(inactive)} / external {len(externals)}')
    up_ = len({tuple(sorted((e['source_teacher_id'], e['target_teacher_id']))) for e in project_edges})
    print(f'  計畫邊：{len(project_edges)} 列 → {up_} 組教師配對'
          f'（其中該年度兩人都自己登錄的 {sum(1 for e in project_edges if e["both_recorded_this_year"])} 列）')
    print('\n=== 人工裁定套用結果 ===')
    for k, v in decisions_log.most_common():
        print(f'  {k}: {v}')


# ═══════════════════════════════════════════════════════════════
# 階段 3：OpenAlex 補值
# ═══════════════════════════════════════════════════════════════
OA_CACHE = os.path.join(FINAL, 'cache')
OA_BATCH = 50            # openalex_id filter 一次帶幾個 id（URL 長度限制）





def name_tokens(s):
    """姓名 → 小寫拉丁字母 token；去掉重音與各種連字號（OpenAlex 用 U+2010）。"""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.replace('‐', '-').replace('’', "'").lower()
    return [t for t in re.split(r'[^a-z]+', s) if t]


def split_name(toks):
    """回傳 (姓, [名...])。OpenAlex 與名冊的英文名都是「名 … 姓」的順序。"""
    if not toks:
        return None, []
    return toks[-1], toks[:-1]


def compatible(a, b):
    """兩個姓名是否可能是同一人。

    這裡刻意嚴格：**姓必須相同，名要逐位相符**（允許其中一邊只有縮寫）。
    早期版本只比對 token 集合，結果把 `Wei-Wei Lee` 配到 `Jyh-Wei Lee`
    ——因為集合把重複的 `wei` 併成一個，`{wei,lee}` 就變成 `{jyh,wei,lee}` 的子集。
    同名誤配在下游看不出來，所以寧可漏配。
    """
    sa, ga = split_name(a)
    sb, gb = split_name(b)
    if not sa or not sb or sa != sb:
        return False
    if not ga or not gb:
        return False
    if len(ga) != len(gb):
        # 允許一邊多一個 middle name，但多出來的那個不能與已有的位置衝突
        short, long_ = (ga, gb) if len(ga) < len(gb) else (gb, ga)
        return all(any(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))
                       for y in long_) for x in short) and len(short) >= 1 and abs(len(ga) - len(gb)) <= 1
    return all(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y))
               for x, y in zip(ga, gb))


# OpenAlex 的 field 名稱。經濟學者確實會發在醫學／環境／工程期刊，
# 所以這個集合只用來替**弱證據**把關，不用來否決 ORCID 或多篇共現的強證據。
PLAUSIBLE_FIELDS = {
    'Economics, Econometrics and Finance', 'Business, Management and Accounting',
    'Social Sciences', 'Decision Sciences', 'Mathematics', 'Psychology',
    'Arts and Humanities', 'Environmental Science', 'Energy',
}


def top_field(obj):
    ts = (obj or {}).get('topics') or []
    return ts[0].get('field', {}).get('display_name', '') if ts else ''


def top_country(obj):
    insts = (obj or {}).get('last_known_institutions') or []
    return insts[0].get('country_code', '') if insts else ''


# ── 1. 候選解析 ────────────────────────────────────────────────
# 每個候選帶一個 strength，決定它要不要被採信（見 decide()）
#   4 ORCID 完全相同          —— 唯一的硬證據
#   3 同篇共現 ≥2 篇          —— 兩人同掛的論文已對到 OpenAlex work，在該 work 的作者列裡對回來
#   2 同篇共現 1 篇 / 前一輪查證 / 上一輪教師表
#   1 只有姓名查詢            —— 最弱
STRENGTH = {'orcid_roster': 4, 'coappearance': 3, 'coappearance_single': 2, 'orcid_node': 2,
            'node_table': 2, 'teacher_table': 2, 'name_search': 1}


def resolve_offline(nodes, master):
    cand = collections.defaultdict(dict)      # node_id -> {method: (author_id, evidence)}
    orcid_want = {}                           # node_id -> orcid

    for n in nodes.values():
        ids = json.loads(n['openalex_author_ids_json'] or '[]')
        if ids:
            cand[n['node_id']]['node_table'] = (ids[0], 'prior_web_verification')
        orc = json.loads(n['orcid_json'] or '[]')
        if orc:
            orcid_want[n['node_id']] = ('orcid_node', orc[0])
    # 名冊主檔的 ORCID 是人工維護的，才是硬證據；節點表上的 ORCID 是前一輪從網頁
    # 證據撿回來的，會出錯——`陳韻旻` 就是被掛上浙江科技大學一位岩土工程學者的 ORCID。
    for tid, m in master.items():
        if m['orcid'].strip():
            orcid_want[tid] = ('orcid_roster', m['orcid'].strip())

    for r in rd('claude_openalex_match', 'output', 'teacher_openalex_authors.csv'):
        if r['is_primary'] == '1':
            cand[r['teacher_id']]['teacher_table'] = (r['openalex_author_id'],
                                                      f'matched_works={r["n_matched_works"]}')

    rec2paper = {r['record_id']: r['paper_id'] for r in rd('collab_network', 'output', 'paper_sources.csv')}
    paper_nodes = collections.defaultdict(list)
    for r in rd('collab_network', 'output', 'paper_authors.csv'):
        paper_nodes[r['paper_id']].append(r['node_id'])

    work_auth = collections.defaultdict(list)
    for r in rd('claude_openalex_match', 'output', 'matched_work_authorships.csv'):
        work_auth[r['openalex_work_id']].append(r)

    votes = collections.defaultdict(collections.Counter)
    for w, rows in work_auth.items():
        oa = [(r['openalex_author_id'], name_tokens(r['author_display_name'])) for r in rows]
        papers = {rec2paper[x.strip()] for x in rows[0]['nstc_record_ids'].split(' ; ')
                  if x.strip() in rec2paper}
        for p in papers:
            for nid in paper_nodes.get(p, []):
                n = nodes.get(nid)
                if not n:
                    continue
                names = [name_tokens(n['name_en'])] + [name_tokens(a) for a in json.loads(n['aliases_json'] or '[]')]
                names = [c for c in names if len(c) >= 2]
                for aid, ak in oa:
                    if any(compatible(ak, c) for c in names):
                        votes[nid][aid] += 1

    for nid, c in votes.items():
        aid, k = c.most_common(1)[0]
        method = 'coappearance' if k >= 2 else 'coappearance_single'
        cand[nid][method] = (aid, f'shared_works={k};candidates={len(c)}')

    # own_ids[node_id][author_id] = 這個人的論文對到的 OpenAlex work 裡，該 author id 出現幾次。
    # 這是驗證候選的關鍵：不管候選是從哪裡來的，只要它出現在「本人自己那幾篇論文」的
    # 作者列裡，就是同一個人；出現不了，就只是同名。
    own = collections.defaultdict(collections.Counter)
    for w, rows in work_auth.items():
        ids = [r['openalex_author_id'] for r in rows]
        papers = {rec2paper[x.strip()] for x in rows[0]['nstc_record_ids'].split(' ; ')
                  if x.strip() in rec2paper}
        for p in papers:
            for nid in paper_nodes.get(p, []):
                for aid in ids:
                    own[nid][aid] += 1
    return cand, orcid_want, own


def decide(cands, objs, own, is_roster):
    """從候選裡挑一個並判定可信度。回傳 (author_id, method, evidence, confidence) 或 None。

    最可靠的驗證不是「領域像不像經濟學」——健康經濟學者本來就發在醫學期刊
    （劉錦添的 field 就是 Health Professions，那是對的）——而是
    **這個 author id 有沒有出現在他自己那幾篇論文的作者列裡**（`own`）。
    出現得愈多次愈可信；完全沒出現，就只是一個同名的人。

    領域／國別的合理性檢查只在完全無法驗證時當最後一道防線。
    """
    scored = []
    for method, (aid, ev) in cands.items():
        scored.append((own.get(aid, 0), STRENGTH[method], method, aid, ev))
    scored.sort(reverse=True)
    for hits, st, method, aid, ev in scored:
        obj = objs.get(aid)
        if hits >= 2:
            return aid, method, f'{ev};own_works={hits}', 'high'
        if st == 4:                                   # 名冊人工維護的 ORCID
            return aid, method, ev, 'high'
        if hits == 1:
            return aid, method, f'{ev};own_works=1', 'medium'
        if obj is None:
            continue
        ok = top_field(obj) in PLAUSIBLE_FIELDS
        if st >= 2 and ok and (not is_roster or top_country(obj) == 'TW'):
            return aid, method, ev + ';unverified_by_own_works', 'low'
        if st == 1 and ok and top_country(obj) == 'TW':
            return aid, method, ev + ';name_only', 'low'
    return None


# ── 2. 連網 ────────────────────────────────────────────────────
def fetch_authors_by_filter(kind, values, per_call=50):
    """kind: 'openalex_id' 或 'orcid'。1 credit / 次，很便宜。"""
    os.makedirs(OA_CACHE, exist_ok=True)
    cpath = os.path.join(OA_CACHE, f'openalex_{kind}.json')
    got = json.load(open(cpath, encoding='utf-8')) if os.path.exists(cpath) else {}
    todo = [v for v in values if v not in got]
    if todo:
        print(f'  {kind}：快取 {len(got)}，待抓 {len(todo)}')
    for i in range(0, len(todo), per_call):
        chunk = todo[i:i + per_call]
        key = '|'.join(c.rsplit('/', 1)[-1] for c in chunk)
        d = _oa.get('authors', {'filter': f'{kind}:{key}', 'per_page': per_call})
        found = {}
        for a in d.get('results', []):
            found[a['id']] = a
            if kind == 'orcid' and a.get('orcid'):
                got[a['orcid']] = a
        if kind == 'openalex_id':
            got.update(found)
        for c in chunk:
            got.setdefault(c, None)          # 記下「查過但沒有」，避免重複花額度
        if (i // per_call) % 10 == 0:
            print(f'    {min(i + per_call, len(todo))}/{len(todo)}  剩餘額度 {_oa.remaining}', flush=True)
        json.dump(got, open(cpath, 'w', encoding='utf-8'), ensure_ascii=False)
    return got


_SEARCH_CACHE = None


def search_teacher(name_en):
    """姓名查詢（10 credits，最貴的一種）。只回傳姓名嚴格相容的候選。結果會快取，
    重跑不會重複計費。"""
    global _SEARCH_CACHE
    if not name_en.strip():
        return None
    cpath = os.path.join(OA_CACHE, 'openalex_name_search.json')
    if _SEARCH_CACHE is None:
        os.makedirs(OA_CACHE, exist_ok=True)
        _SEARCH_CACHE = json.load(open(cpath, encoding='utf-8')) if os.path.exists(cpath) else {}
    if name_en in _SEARCH_CACHE:
        d = _SEARCH_CACHE[name_en]
    else:
        d = _oa.get('authors', {'search': name_en, 'per_page': 25})
        _SEARCH_CACHE[name_en] = d
        json.dump(_SEARCH_CACHE, open(cpath, 'w', encoding='utf-8'), ensure_ascii=False)
    want = name_tokens(name_en)
    best = None
    for a in d.get('results', []):
        if not compatible(name_tokens(a.get('display_name', '')), want):
            continue
        insts = a.get('last_known_institutions') or []
        tw = any(i.get('country_code') == 'TW' for i in insts)
        score = (2 if tw else 0, a.get('works_count', 0))
        if best is None or score > best[0]:
            best = (score, a)
    return best[1] if best else None


# ── 3. 主流程 ──────────────────────────────────────────────────
OA_FIELDS = ['openalex_author_id', 'openalex_display_name', 'openalex_orcid',
             'oa_match_method', 'oa_match_confidence', 'oa_match_evidence',
             'n_pubs_total', 'n_citations_total', 'h_index', 'i10_index',
             'oa_primary_topic', 'oa_primary_field', 'oa_topics_json',
             'oa_last_institution', 'oa_country', 'oa_first_pub_year',
             'oa_quality_flags', 'oa_needs_review', 'oa_decision_rule', 'oa_retrieved_utc']
NOTFOUND_FIELDS = ['kind', 'node_id', 'teacher_id', 'name_zh', 'name_en', 'institution',
                   'n_papers_2015_2026', 'degree_all', 'identity_status',
                   'reason', 'rejected_candidate', 'rejected_candidate_field']


def quality_flags(obj, is_roster, n_local_papers):
    """OpenAlex 自己的作者消歧也會出錯，而且錯了在數字上看不出來——
    `陳韻旻`（中央經濟）的 8 篇經濟學論文被 OpenAlex 併進浙江科技大學一位岩土工程
    學者的 profile（1,032 篇、18,904 次引用）。這種錯誤我們修不了，
    但可以標出來讓人看得見。"""
    f = []
    if is_roster and top_country(obj) not in ('TW', ''):
        f.append('country_mismatch')
    if top_field(obj) not in PLAUSIBLE_FIELDS:
        f.append('field_atypical')
    wc = obj.get('works_count') or 0
    if wc >= 250 and (not n_local_papers or wc > 8 * n_local_papers):
        f.append('works_count_outlier')
    return f


_INST_STOP = {'national', 'university', 'of', 'the', 'college', 'institute', 'and',
              'taiwan', 'academy', 'school', 'center', 'centre', 'department'}


def inst_tokens(s):
    return {t for t in re.split(r'[^a-z]+', (s or '').lower()) if t and t not in _INST_STOP}


def same_institution(ours, theirs):
    """兩個機構字串是不是同一間。名冊寫中文、OpenAlex 寫英文，
    所以名冊的中文名要先透過 faculty_and_map 的機構表換成英文。"""
    a, b = inst_tokens(ours), inst_tokens(theirs)
    if not a or not b:
        return False
    return bool(a & b) and len(a & b) / min(len(a), len(b)) >= 0.5


def flag_gate(flags, ours, obj, ):
    """使用者裁定（2026-09-10）中旗標時要怎麼處理：

      1 只中 country_mismatch 或 works_count_outlier → 人本來就配對正確，採用 OpenAlex
      2 中 field_atypical，但 OpenAlex 的機構與我們知道的機構對得上 → 採用 OpenAlex
      3 我們原本就沒有記錄他的機構 → 直接採用 OpenAlex
      4 其餘 → 不採用 OpenAlex 的數字，只留我們知道的機構當判斷依據

    回傳 (是否採用, 規則代號)。
    """
    if not flags:
        return True, 'no_flag'
    if not (set(flags) - {'country_mismatch', 'works_count_outlier'}):
        return True, 'rule1_country_or_volume_only'
    if not (ours or '').strip():
        return True, 'rule3_no_institution_on_record'
    if same_institution(ours, (obj or {}).get('_inst_name', '')):
        return True, 'rule2_institution_matches'
    return False, 'rule4_keep_our_institution_only'


def author_cols(dec, obj, stamp, is_roster=False, n_local_papers=0):
    if not dec or not obj:
        return {k: '' for k in OA_FIELDS} | {'oa_match_method': 'none'}
    aid, method, ev, conf = dec
    st = obj.get('summary_stats') or {}
    flags = quality_flags(obj, is_roster, n_local_papers)
    topics = [t.get('display_name', '') for t in (obj.get('topics') or [])[:5]]
    insts = obj.get('last_known_institutions') or []
    counts = obj.get('counts_by_year') or []
    return {
        'openalex_author_id': obj['id'],
        'openalex_display_name': obj.get('display_name', ''),
        'openalex_orcid': obj.get('orcid') or '',
        'oa_match_method': method,
        'oa_match_confidence': conf,
        'oa_match_evidence': ev,
        'n_pubs_total': obj.get('works_count', ''),
        'n_citations_total': obj.get('cited_by_count', ''),
        'h_index': st.get('h_index', ''),
        'i10_index': st.get('i10_index', ''),
        'oa_primary_topic': topics[0] if topics else '',
        'oa_primary_field': top_field(obj),
        'oa_topics_json': j(topics),
        'oa_last_institution': insts[0].get('display_name', '') if insts else '',
        'oa_country': top_country(obj),
        'oa_first_pub_year': min((c['year'] for c in counts), default=''),
        'oa_quality_flags': ';'.join(flags),
        'oa_needs_review': int(bool(flags)),
        'oa_retrieved_utc': stamp,
    }


_INST_ZH2EN = None


def inst_of_ours(r, is_roster):
    """我們自己記錄的機構，換成可以跟 OpenAlex 比對的英文字串。"""
    global _INST_ZH2EN
    if is_roster:
        if _INST_ZH2EN is None:
            _INST_ZH2EN = {x['機構名稱']: x['英文名稱'] for x in
                           rd('faculty_and_map', 'output', 'main_result', 'institutions.csv')}
        zh = r.get('institution_zh', '')
        return _INST_ZH2EN.get(zh, zh)
    insts = json.loads(r.get('institutions_json') or '[]')
    return insts[0] if insts else ''


def stage3_enrich(fetch=True, search_teachers=True):
    """fetch：連 OpenAlex 抓 ORCID 與 author 物件（1 credit / 50 人，很便宜）。
    search_teachers：對仍無候選的名冊教師做姓名查詢（10 credits / 人，貴；有快取）。"""
    args = argparse.Namespace(fetch=fetch and not OFFLINE,
                              search_teachers=search_teachers and not OFFLINE)
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')

    nodes = {n['node_id']: n for n in rd('collab_network', 'output', 'author_teacher_id_by_gpt.csv')}
    master = {m['teacher_id']: m for m in rd('faculty_identity', 'faculty_identity_master.csv')}
    all_rows, active, ext = read_master()
    inactive = rd('final_plan', 'professor_demo', 'professors_inactive.csv')

    cand, orcid_want, own = resolve_offline(nodes, master)

    objs = {}
    if args.fetch:
        by_orcid = fetch_authors_by_filter('orcid', sorted({o for _, o in orcid_want.values()}))
        for nid, (src, orc) in orcid_want.items():
            a = by_orcid.get(orc)
            if a:
                cand[nid][src] = (a['id'], 'orcid=' + orc)
                objs[a['id']] = a
        objs.update({k: v for k, v in fetch_authors_by_filter(
            'openalex_id', sorted({c[0] for d in cand.values() for c in d.values()})).items() if v})

        if args.search_teachers:
            miss = [r for r in active + inactive
                    if not decide(cand.get(r['teacher_id'], {}), objs, own.get(r['teacher_id'], {}), True)]
            print(f'姓名查詢：{len(miss)} 位教師 × 10 credits ≈ {len(miss) * 10} credits')
            for i, r in enumerate(miss, 1):
                try:
                    a = search_teacher(r['name_en_canonical'])
                except _oa.BudgetExhausted as e:
                    print('  額度用盡，停在第 %d 位：%s' % (i, e))
                    break
                if a:
                    cand[r['teacher_id']]['name_search'] = (a['id'], 'display_name=' + a.get('display_name', ''))
                    objs[a['id']] = a
                if i % 25 == 0:
                    print(f'    {i}/{len(miss)}  剩餘額度 {_oa.remaining}', flush=True)

    notfound = []

    def enrich(rows, kind, idkey, is_roster):
        n_ok = 0
        for r in rows:
            cs = cand.get(r[idkey], {})
            ow = own.get(r[idkey], {})
            dec = decide(cs, objs, ow, is_roster)
            obj = objs.get(dec[0]) if dec else None
            rule = ''
            if obj:
                flags = quality_flags(obj, is_roster, int(r.get('n_papers') or 0))
                ours = inst_of_ours(r, is_roster)
                o2 = dict(obj)
                o2['_inst_name'] = ((obj.get('last_known_institutions') or [{}])[0]
                                    .get('display_name', ''))
                keep, rule = flag_gate(flags, ours, o2)
                if not keep:
                    obj, dec = None, None
            r.update(author_cols(dec, obj, stamp, is_roster,
                                 int(r.get('n_papers') or 0)))
            r['oa_decision_rule'] = rule
            if obj:
                n_ok += 1
                continue
            rejected = rejected_field = ''
            if cs:
                best = sorted(cs, key=lambda m: (own.get(r[idkey], {}).get(cs[m][0], 0), STRENGTH[m]))[-1]
                o = objs.get(cs[best][0])
                rejected = (o or {}).get('display_name', cs[best][0])
                rejected_field = top_field(o)
                reason = ('未通過旗標規則（%s）' % rule if rule.startswith('rule4') else
                          '有候選但證據不足（%s）' % best if o else '解析到 id 但抓不到 author 物件')
            elif not (r.get('name_en_canonical') or r.get('name_en', '')).strip():
                reason = '沒有英文姓名，無法查詢'
            else:
                reason = '查不到姓名相容的 OpenAlex author'
            notfound.append({
                'kind': kind, 'node_id': r.get('node_id', r.get('teacher_id', '')),
                'teacher_id': r.get('teacher_id', ''), 'name_zh': r.get('name_zh', ''),
                'name_en': r.get('name_en_canonical', r.get('name_en', '')),
                'institution': r.get('institution_zh', ''),
                'n_papers_2015_2026': r.get('n_papers', ''),
                'degree_all': r.get('pub_degree_all', r.get('degree_all', '')),
                'identity_status': r.get('identity_status', ''),
                'reason': reason, 'rejected_candidate': rejected,
                'rejected_candidate_field': rejected_field,
            })
        return n_ok

    n1 = enrich(active, '名冊教師(active)', 'teacher_id', True)
    n2 = enrich(inactive, '名冊教師(inactive)', 'teacher_id', True)
    n3 = enrich(ext, '外部共同作者', 'node_id', False)

    with open(MASTER, encoding='utf-8-sig') as f:
        keep = [c for c in csv.DictReader(f).fieldnames if c not in OA_FIELDS]
    write_master(all_rows, keep + OA_FIELDS)
    with open(INACTIVE, encoding='utf-8-sig') as f:
        keepi = [c for c in csv.DictReader(f).fieldnames if c not in OA_FIELDS]
    wr(INACTIVE, inactive, keepi + OA_FIELDS)

    notfound.sort(key=lambda r: (r['kind'], -int(r['degree_all'] or 0)))
    excel(OA_NOT_FOUND, '找不到OpenAlex', NOTFOUND_FIELDS, notfound,
          {'name_en': 22, 'institution': 20, 'reason': 30, 'rejected_candidate': 24},
          note='找不到 OpenAlex 數字的人。reason 說明原因；'
               'rejected_candidate 是被規則擋下的候選，可以直接看要不要採信。')

    print('\n=== 補齊結果 ===')
    print(f'  active   {n1}/{len(active)}')
    print(f'  inactive {n2}/{len(inactive)}')
    print(f'  external {n3}/{len(ext)}')
    print(f'  找不到／證據不足 {len(notfound)} 人 → professor_demo/openalex_not_found.xlsx')
    allr = active + inactive + ext
    print('  認定方式:', dict(collections.Counter(r['oa_match_method'] for r in allr)))
    print('  可信度  :', dict(collections.Counter(r['oa_match_confidence'] for r in allr if r['oa_match_confidence'])))
    print('  未通過合理性檢查而被擋下:',
          collections.Counter(r['reason'] for r in notfound).most_common())


# ═══════════════════════════════════════════════════════════════
# 階段 4：期刊 PDF ＋ 上網查證 → 外部作者機構
# ═══════════════════════════════════════════════════════════════
PDFDIR = os.path.join(FINAL, 'cache', 'journal_pdf')
JOURNAL_OUT = os.path.join(FINAL, 'manual_review', 'decisions', 'external_affiliations_journal.csv')
WEB_IN = os.path.join(FINAL, 'manual_review', 'decisions', 'external_affiliations_web.csv')
WEB_QUEUE = os.path.join(FINAL, 'manual_review', 'decisions', 'web_lookup_queue.csv')
HTTP_UA = {'User-Agent': 'NetSciX2027-collab-network/0.1 (mailto:stone930801@gmail.com)'}

TER_SEASON = 'https://econ.ntu.edu.tw/ter/new/js/season-data.js'
TER_BASE = 'https://econ.ntu.edu.tw/ter/new/'
SINICA = 'https://www.econ.sinica.edu.tw'
AEP_INDEX = SINICA + '/4d49b1b1-d551-4956-84a5-6bbf392d8417/pages/64'
TEFP_INDEX = SINICA + '/4d49b1b1-d551-4956-84a5-6bbf392d8417/pages/81'

JOURNAL_FIELDS = ['node_id', 'name', 'institution', 'country', 'evidence', 'evidence_url',
          'checked_utc', 'journal', 'method', 'confidence']

# email 網域 → 機構。只列出這份資料實際出現過的；沒對到的就留原網域，不猜。
DOMAIN2INST = {
    'ntu.edu.tw': '國立臺灣大學', 'nccu.edu.tw': '國立政治大學', 'nthu.edu.tw': '國立清華大學',
    'nycu.edu.tw': '國立陽明交通大學', 'nctu.edu.tw': '國立交通大學', 'ncu.edu.tw': '國立中央大學',
    'nchu.edu.tw': '國立中興大學', 'ncku.edu.tw': '國立成功大學', 'nsysu.edu.tw': '國立中山大學',
    'ccu.edu.tw': '國立中正大學', 'ntpu.edu.tw': '國立臺北大學', 'ntnu.edu.tw': '國立臺灣師範大學',
    'nutn.edu.tw': '國立臺南大學', 'ndhu.edu.tw': '國立東華大學', 'nknu.edu.tw': '國立高雄師範大學',
    'nuk.edu.tw': '國立高雄大學', 'nqu.edu.tw': '國立金門大學', 'ntou.edu.tw': '國立臺灣海洋大學',
    'niu.edu.tw': '國立宜蘭大學', 'nptu.edu.tw': '國立屏東大學', 'nfu.edu.tw': '國立虎尾科技大學',
    'ntust.edu.tw': '國立臺灣科技大學', 'ntut.edu.tw': '國立臺北科技大學',
    'fcu.edu.tw': '逢甲大學', 'thu.edu.tw': '東海大學', 'scu.edu.tw': '東吳大學',
    'fju.edu.tw': '輔仁大學', 'tku.edu.tw': '淡江大學', 'cycu.edu.tw': '中原大學',
    'cjcu.edu.tw': '長榮大學', 'cgu.edu.tw': '長庚大學', 'mcu.edu.tw': '銘傳大學',
    'shu.edu.tw': '世新大學', 'pccu.edu.tw': '中國文化大學', 'ntcu.edu.tw': '國立臺中教育大學',
    'yuntech.edu.tw': '國立雲林科技大學', 'nkust.edu.tw': '國立高雄科技大學',
    'sinica.edu.tw': '中央研究院', 'cier.edu.tw': '中華經濟研究院', 'tier.org.tw': '台灣經濟研究院',
    'chihlee.edu.tw': '致理科技大學', 'takming.edu.tw': '德明財經科技大學',
}

TITLES = ('特聘教授', '講座教授', '名譽教授', '副教授', '助理教授', '教授', '研究員',
          '副研究員', '助研究員', '博士後研究', '博士候選人', '博士生', '碩士生',
          '兼任', '專任', '主任', '所長', '院長', '系主任')



def nt_title(s):
    """題名正規化鍵：全形轉半形、去空白標點，中文保留。"""
    s = unicodedata.normalize('NFKC', s or '').lower()
    s = re.sub(r'[\s　]+', '', s)
    return re.sub(r'[^0-9a-z一-鿿]', '', s)


def nname(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^0-9a-z一-鿿]', '', s.lower())


def fetch(url, binary=False, tries=3):
    """抓網頁或 PDF，落地快取；同一個 URL 只抓一次。"""
    os.makedirs(PDFDIR, exist_ok=True)
    ext = '.pdf' if binary else '.html'
    path = os.path.join(PDFDIR, hashlib.sha1(url.encode()).hexdigest() + ext)
    if os.path.exists(path):
        return path if os.path.getsize(path) > 0 else None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HTTP_UA), timeout=90) as r:
                data = r.read()
            if binary and not data[:5].startswith(b'%PDF'):
                open(path, 'wb').close()          # 記下「抓過但不是 PDF」
                return None
            with open(path, 'wb') as f:
                f.write(data)
            time.sleep(0.4)
            return path
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(path, 'wb').close()
                return None
            time.sleep(2 ** a)
        except Exception:
            time.sleep(2 ** a)
    return None


def pdf_first_page(path, pages=1):
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        return '\n'.join(r.pages[i].extract_text() or '' for i in range(min(pages, len(r.pages))))
    except Exception:
        return ''


# ── TER：解析 season-data.js 拿到題名 → PDF 網址 ────────────────
def ter_catalog():
    path = fetch(TER_SEASON)
    if not path:
        return []
    src = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for m in re.finditer(r'\{([^{}]*?title_c:.*?pdfFile:\s*"([^"]+)"[^{}]*?)\}', src, re.S):
        blk, pdf = m.group(1), m.group(2)
        def g(k):
            mm = re.search(k + r':\s*"((?:[^"\\]|\\.)*)"', blk, re.S)
            return re.sub(r'\s+', ' ', mm.group(1)).strip() if mm else ''
        folder = g('folder')
        if not folder:
            continue
        out.append({
            'journal': 'TER 經濟論文叢刊',
            'title_c': g('title_c'), 'title_en': g('title_en'),
            'authors_c': g('authors_c'), 'authors_en': g('authors_en'),
            'url': f'{TER_BASE}data/new/{folder}/{pdf}',
        })
    return out


# ── 中研院兩份期刊：從卷期目次爬到每篇的 PDF ────────────────────
def sinica_catalog(index_url, journal):
    path = fetch(index_url)
    if not path:
        return []
    idx = open(path, encoding='utf-8', errors='replace').read()
    posts = sorted(set(re.findall(r'href="(/4d49b1b1[^"]*/posts/\d+)"', idx)))
    out = []
    for post in posts:
        p = fetch(SINICA + post)
        if not p:
            continue
        html = open(p, encoding='utf-8', errors='replace').read()
        # 一篇文章是一個 `journal-card` 區塊：標題在 card-title，
        # 作者在後面的 <span>| …</span>，全文在標示「PDF下載」的那個連結。
        for blk in re.findall(r'<div class="journal-card.*?(?=<div class="journal-card|</stage4_journal|</body)',
                              html, re.S):
            tm = re.search(r'card-title[^>]*>(.*?)</div>', blk, re.S)
            if not tm:
                continue
            title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tm.group(1))).strip()
            am = re.search(r'<span>\s*\|(.*?)</span>', blk, re.S)
            authors = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', am.group(1))).strip() if am else ''
            # 全文連結的標籤兩份期刊不一樣：經濟論文寫「PDF下載」，
            # 臺灣經濟預測與政策寫「全文下載」。
            fm = re.search(r'href="[^"]*file=(/1/archives/[0-9a-f]+)[^"]*"[^>]*>\s*'
                           r'(?:PDF|全文)', blk)
            if not (title and fm):
                continue
            out.append({'journal': journal, 'title_c': title, 'title_en': title,
                        'authors_c': authors, 'authors_en': authors,
                        'url': SINICA + fm.group(1)})
    return out


# ── 從 PDF 首頁抽機構 ──────────────────────────────────────────
FOOTNOTE = re.compile(r'作者(?:分別)?為(.{4,400}?)(?:。|\n\n)', re.S)


def clean_inst(seg):
    """「國立政治大學財政系教授」→「國立政治大學」。"""
    seg = re.sub(r'\s+', '', seg)
    for t in TITLES:
        seg = seg.replace(t, '')
    m = re.search(r'^(.*?(?:大學|學院|研究院|研究所|中心|銀行|公司|署|部|會))', seg)
    inst = (m.group(1) if m else '').strip()
    # 剝掉職稱後如果只剩「研究生」「博士生」這種，那不是機構，寧可不要
    if len(inst) < 3 or re.fullmatch(r'(研究生|學生|博士生|碩士生|本人|作者)', inst):
        return ''
    return inst


def parse_footnote(text, n_authors):
    """回傳 (每位作者的機構, 可信度)；對不上就回 ([], '')。

    分隔符有兩種：作者之間用「、」，但**最後兩位之間慣用「與」**
    （`A、B與C`）。麻煩的是「與」也會出現在同一個人的兩個職務之間
    （`財政系教授與政大台灣研究中心主任`），所以不能無條件切。

    規則：先只用「、」切。
      * 段數 == 作者數        → 直接採用，high
      * 段數 == 作者數 − 1 且全文只有一個「與」 → 這一刀是被逼出來的，切，medium
      * 其他                  → 放棄。**寧可少補一筆，也不要把機構安到別人頭上。**
    """
    m = FOOTNOTE.search(text or '')
    if not m:
        return [], ''
    body = re.sub(r'\s+', '', m.group(1))
    segs = [x for x in re.split(r'[、;；]', body) if x.strip()]
    conf = ''
    if len(segs) == n_authors:
        conf = 'high'
    else:
        # 最後兩位之間慣用「與 / 以及 / 及」。這些字也會出現在同一個人的兩個職務之間
        # （`財政系教授與台灣研究中心主任`）或機構名裡（`工業工程與經營資訊學系`），
        # 所以只在**前面剛好是一個職稱**的位置切——那才是換人的位置。
        cut = re.compile(r'(' + '|'.join(TITLES) + r')(?:以及|與|及)')
        resplit = []
        for x in segs:
            marked = cut.sub(lambda m: m.group(1) + '\x01', x)
            resplit += [y for y in marked.split('\x01') if y.strip()]
        if len(resplit) == n_authors:
            segs, conf = resplit, 'medium'
        else:
            return [], ''
    insts = [clean_inst(x) for x in segs]
    if not all(i and re.search(r'[一-鿿]', i) for i in insts):
        return [], ''
    return insts, conf


def parse_name_lines(text, authors):
    """另一種版型：作者姓名與機構直接印在首頁，一行姓名、下一行機構。

        簡妗庭
        國立清華大學經濟學系
        吳世英
        ∗
        國立清華大學經濟學系

    臺灣經濟預測與政策整份都是這個樣子。這比解析註腳可靠，因為它是
    **用姓名對到機構**，不是靠順序推的。
    """
    lines = [re.sub(r'\s+', '', l) for l in (text or '').split('\n')]
    out = {}
    for a in authors:
        key = re.sub(r'\s+', '', a)
        for i, l in enumerate(lines):
            if l != key:
                continue
            for j in range(i + 1, min(i + 4, len(lines))):
                cand = lines[j]
                if not cand or len(cand) < 3 or re.fullmatch(r'[∗*†‡§0-9,.、]+', cand):
                    continue          # 註腳記號那一行跳過
                if re.search(r'大學|學院|研究院|研究所|中心|銀行|公司|署|部|會', cand):
                    inst = clean_inst(cand)
                    if inst:
                        out[a] = inst
                break
            if a in out:
                break
    return out


def split_authors(s):
    """目次的作者欄：`孫嘉宏.林瑞益` / `王韋能．謝智源` / `陳妍蒨．劉錦添．王齡懋`。"""
    return [x.strip() for x in re.split(r'[.．·•、,，]', s or '') if x.strip()]


EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})')


def emails_to_inst(text):
    out = []
    for m in EMAIL.finditer(text or ''):
        d = m.group(1).lower()
        for suffix, inst in DOMAIN2INST.items():
            if d == suffix or d.endswith('.' + suffix):
                out.append((m.group(0), inst))
                break
        else:
            out.append((m.group(0), ''))
    return out


def emit_web_queue(ext, papers, done):
    """輸出待查清單：每一位缺機構的外部作者一列，附代表作與現成的搜尋字串。

    這條路沒辦法自動化——Google 沒有免費 API，程式化抓取也違反它的服務條款。
    所以這裡只把「要查什麼、拿什麼去查」整理好，查完的結果照
    `external_affiliations_web.csv` 的欄位填回去，再跑一次本程式就會併進輸出。
    """
    bynode = collections.defaultdict(list)
    for r in papers:
        for i in json.loads(r['author_node_ids_json']):
            bynode[i].append(r)
    rows = []
    for r in ext:
        if r.get('affil_source', 'none') != 'none' or r['node_id'] in done:
            continue
        ps = bynode.get(r['node_id'], [])
        rep = sorted(ps, key=lambda x: (not x['venue'], not x['doi'],
                                        x['pub_category'] != '期刊論文',
                                        -int(x['year'])))[0] if ps else {}
        name = r['name_zh'] or r['name_en']
        co = [x for x in json.loads(rep.get('author_names_json', '[]')) if x != name]
        rows.append({
            'priority': int(r['degree_teacher'] or 0) * 100 + min(int(r['n_papers'] or 0), 99),
            'node_id': r['node_id'], '姓名': name,
            '連到幾位名冊教師': r['degree_teacher'], '論文數': r['n_papers'],
            '代表作年': rep.get('year', ''), '代表作類別': rep.get('pub_category', ''),
            '代表作出處': rep.get('venue', ''), '代表作標題': rep.get('title', ''),
            '代表作DOI': rep.get('doi', ''), '共同作者': ' / '.join(co)[:120],
            '搜尋字串': f'"{rep.get("title", "")}" {name} {rep.get("venue", "")}'.strip(),
        })
    rows.sort(key=lambda r: -r['priority'])
    F = ['node_id', '姓名', '連到幾位名冊教師', '論文數', '代表作年', '代表作類別',
         '代表作出處', '代表作標題', '代表作DOI', '共同作者', '搜尋字串']
    os.makedirs(os.path.dirname(WEB_QUEUE), exist_ok=True)
    with open(WEB_QUEUE, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=F, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f'待查清單 {len(rows)} 列 → {os.path.relpath(WEB_QUEUE, ROOT)}')
    print('  其中 degree_teacher >= 2 的:',
          sum(1 for r in rows if int(r['連到幾位名冊教師'] or 0) >= 2))
    return rows


def read_web_verified():
    """讀已經上網查證完、逐列附證據網址的結果。"""
    if not os.path.exists(WEB_IN):
        return []
    with open(WEB_IN, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def stage4_journal(limit=0, journal=None):
    """limit：只處理前 N 篇（試跑用）。journal：只跑其中一份。"""
    args = argparse.Namespace(limit=limit, journal=journal)
    stamp = time.strftime('%Y-%m-%d')

    _, _, ext = read_master()
    # 「還缺機構的人」= 目前沒有機構的，**加上這支程式自己上一輪補的那些**。
    # 不加後者的話，重跑時它們已經有 journal_pdf 來源、會被當成不缺，
    # 於是輸出檔只剩新找到的幾筆，上一輪的結果就掉了。
    own = set()
    if os.path.exists(JOURNAL_OUT):
        with open(JOURNAL_OUT, newline='', encoding='utf-8-sig') as f:
            own = {r['node_id'] for r in csv.DictReader(f)}
    # 階段 6 還沒跑過時，主檔還沒有 affil_* 欄位，一律當成「缺」。
    missing = {r['node_id']: r for r in ext
               if r.get('affil_source', 'none') in ('none', 'journal_pdf')
               or r['node_id'] in own}
    name2node = {}
    for r in ext:
        for nm in (r['name_zh'], r['name_en']):
            if nm:
                name2node.setdefault(nname(nm), r['node_id'])

    papers = rd('final_plan', 'paper', 'papers_all.csv')
    target = {}
    for p in papers:
        if not (set(json.loads(p['author_node_ids_json'])) & set(missing)):
            continue
        v = p['venue'] or ''
        jr = ('TER 經濟論文叢刊' if ('經濟論文叢刊' in v or 'Taiwan Economic Review' in v) else
              'TEFP 臺灣經濟預測與政策' if ('經濟預測與政策' in v) else
              'AEP 經濟論文' if (re.match(r'^經濟論文', v) or 'Academia Economic Papers' in v)
              else None)
        if jr:
            target.setdefault(nt_title(p['title']), []).append((jr, p))
    print('目標論文（缺機構的作者掛名、且屬於這三份期刊）:',
          sum(len(v) for v in target.values()))

    cat = []
    if args.journal in (None, 'TER'):
        cat += ter_catalog()
    if args.journal in (None, 'AEP'):
        cat += sinica_catalog(AEP_INDEX, 'AEP 經濟論文')
    if args.journal in (None, 'TEFP'):
        cat += sinica_catalog(TEFP_INDEX, 'TEFP 臺灣經濟預測與政策')
    print('期刊目次抓到的文章數:', collections.Counter(c['journal'] for c in cat))

    by_title = {}
    for c in cat:
        for t in (c['title_c'], c['title_en']):
            if t:
                by_title.setdefault(nt_title(t), c)

    hits = [(k, by_title[k], v) for k, v in target.items() if k in by_title]
    print('題名對得上的:', len(hits))
    if args.limit:
        hits = hits[:args.limit]

    rows, stat = [], collections.Counter()
    for k, c, ps in hits:
        path = fetch(c['url'], binary=True)
        if not path:
            stat['PDF 抓不到'] += 1
            continue
        text = pdf_first_page(path, pages=2)
        if not text.strip():
            stat['PDF 沒有文字層'] += 1
            continue
        cjk = sum(1 for ch in text if '一' <= ch <= '鿿')
        paper = ps[0][1]
        # 作者順序以**期刊目次**為準（我們的節點清單是排序過的，順序不可信）
        authors = split_authors(c['authors_c']) or json.loads(paper['author_names_json'])
        by_lines = False
        insts, conf = parse_footnote(text, len(authors)) if cjk >= 20 else ([], '')
        if not insts and cjk >= 20:
            # 換第二種版型試試：姓名一行、機構一行
            byname = parse_name_lines(text, authors)
            if byname:
                insts = [byname.get(a, '') for a in authors]
                conf, by_lines = 'high', True

        if insts:
            stat['姓名逐行對應成功' if by_lines else '註腳逐位對應成功（%s）' % conf] += 1
            for i, (nm, inst) in enumerate(zip(authors, insts), 1):
                if not inst:
                    continue
                nid = name2node.get(nname(nm))
                if nid and nid in missing:
                    rows.append({
                        'node_id': nid, 'name': nm, 'institution': inst,
                        'country': 'TW' if re.search(r'大學|學院|研究院|研究所', inst) else '',
                        'evidence': (f'{c["journal"]} 論文首頁姓名下方標示的機構：{inst}'
                                     if by_lines else
                                     f'{c["journal"]} 論文首頁作者註腳，第 {i} 位（共 '
                                     f'{len(authors)} 位）：{inst}'),
                        'evidence_url': c['url'],
                        'checked_utc': stamp, 'journal': c['journal'],
                        'method': 'name_line' if by_lines else 'footnote_positional',
                        'confidence': conf,
                    })
        else:
            stat['註腳對不上（改用 email）' if cjk >= 20 else '中文抽不出來（改用 email）'] += 1
            all_authors = json.loads(paper['author_node_ids_json'])
            for mail, inst in emails_to_inst(text):
                if not inst:
                    continue
                # PDF 上的 email 通常是**通訊作者**的，沒有標明是第幾位。
                # 所以只有在「這篇論文從頭到尾就一位作者」時才敢把它算到那個人頭上；
                # 只要有第二位作者，這個 email 就可能是別人的——寧可不補。
                cands = [n for n in all_authors if n in missing]
                if len(all_authors) != 1 or len(cands) != 1:
                    stat['email 有但不確定是哪一位作者的，不採用'] += 1
                    break
                r = missing[cands[0]]
                rows.append({
                    'node_id': cands[0], 'name': r['name_zh'] or r['name_en'],
                    'institution': inst, 'country': 'TW',
                    'evidence': f'{c["journal"]} 論文首頁 email {mail} 的網域；'
                                f'本篇只有這一位作者缺機構',
                    'evidence_url': c['url'], 'checked_utc': stamp,
                    'journal': c['journal'], 'method': 'email_domain',
                    'confidence': 'medium',
                })
                break

    # 同一個節點可能被多篇論文寫到，保留最高可信度的那一列
    # 上網查證的結果併進來。這些是**論文原件／發布單位頁面上寫的機構**，
    # 逐列有 evidence_url 可以回查，可信度不低於 PDF 抽出來的。
    for w in read_web_verified():
        rows.append({
            'node_id': w['node_id'], 'name': w['name'],
            'institution': w['institution'], 'country': w['country'],
            'evidence': w['evidence'], 'evidence_url': w['evidence_url'],
            'checked_utc': w['checked_utc'], 'journal': '(上網查證)',
            'method': 'web_verified', 'confidence': w.get('confidence', 'medium'),
        })

    RANK = {'high': 3, 'medium': 2, '': 0}
    best = {}
    for r in rows:
        cur = best.get(r['node_id'])
        if cur is None or RANK[cur['confidence']] < RANK[r['confidence']]:
            best[r['node_id']] = r
    rows = sorted(best.values(), key=lambda r: (r['journal'], r['name']))

    os.makedirs(os.path.dirname(JOURNAL_OUT), exist_ok=True)
    with open(JOURNAL_OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        w.writeheader()
        w.writerows(rows)

    print('\n=== 處理結果 ===')
    for k, v in stat.most_common():
        print(f'  {k}: {v}')
    print(f'\n補到機構的外部作者：{len(rows)} 位 → {os.path.relpath(JOURNAL_OUT, ROOT)}')
    print('  方法:', dict(collections.Counter(r['method'] for r in rows)))
    print('  （階段 6 會把它套進 professor_demo/authors_master.csv）')


# ═══════════════════════════════════════════════════════════════
# 階段 5：Crossref → 外部作者機構
# ═══════════════════════════════════════════════════════════════
CROSSREF_CACHE = os.path.join(FINAL, 'cache', 'crossref')
MAILTO = 'stone930801@gmail.com'
HTTP_UA = {'User-Agent': f'NetSciX2027-collab-network/0.1 (mailto:{MAILTO})'}



def cr_norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^0-9a-z一-鿿]', '', s.lower())


def cr_get(path, params):
    url = 'https://api.crossref.org/' + path + '?' + urllib.parse.urlencode(params)
    key = hashlib.sha1(url.encode()).hexdigest()
    os.makedirs(CROSSREF_CACHE, exist_ok=True)
    cp = os.path.join(CROSSREF_CACHE, key + '.json')
    if os.path.exists(cp):
        return json.load(open(cp, encoding='utf-8'))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HTTP_UA), timeout=60) as r:
                d = json.load(r)
            json.dump(d, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
            time.sleep(0.35)              # 對 polite pool 客氣一點
            return d
        except urllib.error.HTTPError as e:
            if e.code == 404:
                json.dump({'message': None}, open(cp, 'w', encoding='utf-8'))
                return {'message': None}
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return {'message': None}


def crossref_item(paper):
    """回傳這篇論文在 Crossref 上的紀錄，找不到回 None。"""
    if paper['doi']:
        d = cr_get('works/' + urllib.parse.quote(paper['doi'], safe=''), {'mailto': MAILTO})
        if d.cr_get('message'):
            return d['message']
    title = (paper['title'] or '').strip()
    if not title or re.search(r'[一-鿿]', title):     # 中文題名 Crossref 幾乎沒有
        return None
    d = cr_get('works', {'query.bibliographic': title[:250], 'rows': 3, 'mailto': MAILTO,
                      'select': 'DOI,title,author,container-title,issued'})
    for it in (d.cr_get('message') or {}).cr_get('items', []):
        t = (it.cr_get('title') or [''])[0]
        if difflib.SequenceMatcher(None, cr_norm(t), cr_norm(title)).ratio() >= 0.90:
            return it
    return None


def stage5_crossref(limit=0):
    args = argparse.Namespace(limit=limit)

    _, _, ext = read_master()
    missing = {r['node_id']: r for r in ext if r.get('affil_source', 'none') == 'none'}
    papers = rd('final_plan', 'paper', 'papers_all.csv')

    # 這些人的姓名鍵 → node_id
    key2node = {}
    for r in missing.values():
        for nm in (r['name_en'], r['name_zh']):
            if nm:
                key2node.setdefault(cr_norm(nm), r['node_id'])

    targets = [p for p in papers if set(json.loads(p['author_node_ids_json'])) & set(missing)]
    targets.sort(key=lambda p: (not p['doi'], p['pub_category'] != '期刊論文'))
    if args.limit:
        targets = targets[:args.limit]

    found = collections.defaultdict(collections.Counter)
    stat = collections.Counter()
    for i, p in enumerate(targets, 1):
        it = crossref_item(p)
        if not it:
            stat['crossref 查不到這篇'] += 1
        else:
            stat['crossref 有這篇'] += 1
            n_aff = 0
            for a in it.cr_get('author', []):
                nm = (a.cr_get('given', '') + ' ' + a.cr_get('family', '')).strip()
                affs = [x.cr_get('name', '') for x in (a.cr_get('affiliation') or []) if x.cr_get('name')]
                if not affs:
                    continue
                n_aff += 1
                nid = key2node.cr_get(cr_norm(nm))
                if nid:
                    for x in affs:
                        found[nid][x] += 1
            stat['這篇有 affiliation 的作者數>0' if n_aff else '這篇完全沒存 affiliation'] += 1
        if i % 100 == 0:
            print(f'  {i}/{len(targets)}  已對到 {len(found)} 位作者', flush=True)

    # 結果存成快取，讓 `external_affiliations.py` 去套用與正規化。
    # 這樣階段 2 重跑、主檔重生也不會掉。
    cp = os.path.join(FINAL, 'cache', 'crossref_affiliations.json')
    prev = json.load(open(cp, encoding='utf-8')) if os.path.exists(cp) else {}
    for nid, c in found.items():
        prev.setdefault(nid, {})
        for k, v in c.items():
            prev[nid][k] = prev[nid].cr_get(k, 0) + v
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    json.dump(prev, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'  寫入 cache/crossref_affiliations.json：累計 {len(prev)} 位作者')

    print('\n查了 %d 篇論文' % len(targets))
    for k, v in stat.most_common():
        print(f'  {k}: {v}')
    print(f'\n這一輪新補到機構的外部作者：{len(found)} 位')
    print('  （階段 6 會把它套進 professor_demo/authors_master.csv）')


# ═══════════════════════════════════════════════════════════════
# 階段 6：彙整機構來源並正規化
# ═══════════════════════════════════════════════════════════════
AFFIL_FIELDS = ['affil_primary', 'affil_institution_norm', 'affil_country',
                'affil_all_json', 'affil_n_works', 'affil_years', 'affil_source']

# 第 4 步：機構字串正規化。
# `matched_works` / `openalex_last` 來的已經是 OpenAlex 的機構名稱，本來就乾淨；
# Crossref 來的是自由文字（`Department of Economics, National Taiwan University, Taipei`），
# 要把機構那一段挑出來，並猜國別。
_INST_HINT = ('universit', 'college', 'institute', 'academy', 'school', 'bank',
              'ministry', 'laborator', 'center', 'centre', 'research', 'hospital',
              'foundation', 'department of economics')
_ZH_HINT = ('大學', '學院', '研究院', '研究所', '中心', '銀行', '部', '署')
_COUNTRY = {
    'taiwan': 'TW', 'r.o.c': 'TW', 'roc': 'TW', 'taipei': 'TW', 'chinese taipei': 'TW',
    'china': 'CN', 'hong kong': 'HK', 'macau': 'MO', 'japan': 'JP', 'korea': 'KR',
    'singapore': 'SG', 'usa': 'US', 'u.s.a': 'US', 'united states': 'US', 'us': 'US',
    'uk': 'GB', 'united kingdom': 'GB', 'england': 'GB', 'scotland': 'GB',
    'canada': 'CA', 'australia': 'AU', 'new zealand': 'NZ', 'germany': 'DE',
    'france': 'FR', 'italy': 'IT', 'spain': 'ES', 'netherlands': 'NL', 'belgium': 'BE',
    'switzerland': 'CH', 'austria': 'AT', 'sweden': 'SE', 'norway': 'NO',
    'denmark': 'DK', 'finland': 'FI', 'ireland': 'IE', 'portugal': 'PT',
    'poland': 'PL', 'czech': 'CZ', 'greece': 'GR', 'turkey': 'TR', 'israel': 'IL',
    'india': 'IN', 'thailand': 'TH', 'vietnam': 'VN', 'malaysia': 'MY',
    'indonesia': 'ID', 'philippines': 'PH', 'brazil': 'BR', 'mexico': 'MX',
    'chile': 'CL', 'argentina': 'AR', 'south africa': 'ZA', 'russia': 'RU',
}


def normalize_affiliation(raw):
    """自由文字的機構字串 → (機構名稱, 國別代碼)。挑不出來就回原字串。"""
    if not raw:
        return '', ''
    parts = [x.strip() for x in re.split(r'[,;]', raw) if x.strip()]
    country = ''
    for x in reversed(parts):
        c = _COUNTRY.get(x.lower().strip('.'))
        if c:
            country = c
            break
    if not country:
        low = raw.lower()
        for k, v in _COUNTRY.items():
            if len(k) > 3 and k in low:
                country = v
                break
    inst = ''
    for x in parts:
        low = x.lower()
        if any(h in low for h in _INST_HINT) or any(h in x for h in _ZH_HINT):
            # 「系所」層級的段落先跳過，優先取「大學」層級
            if 'universit' in low or 'academy' in low or any(h in x for h in ('大學', '研究院')):
                inst = x
                break
            inst = inst or x
    return (inst or parts[0] if parts else raw), country
MISS_FIELDS = ['node_id', 'name_zh', 'name_en', 'identity_status', 'n_papers',
               'degree_all', 'degree_teacher', 'openalex_author_id', '缺的原因']




def stage6_external():
    all_rows, _, ext = read_master()
    mwa = rd('claude_openalex_match', 'output', 'matched_work_authorships.csv')
    man_path = os.path.join(FINAL, 'manual_review', 'decisions', 'external_affiliations_manual.csv')
    manual = {}
    if os.path.exists(man_path):
        with open(man_path, newline='', encoding='utf-8-sig') as f:
            manual = {r['node_id']: r for r in csv.DictReader(f)}
    jr_path = os.path.join(FINAL, 'manual_review', 'decisions', 'external_affiliations_journal.csv')
    journal = {}
    if os.path.exists(jr_path):
        with open(jr_path, newline='', encoding='utf-8-sig') as f:
            journal = {r['node_id']: r for r in csv.DictReader(f)}
    cr_path = os.path.join(FINAL, 'cache', 'crossref_affiliations.json')
    crossref = json.load(open(cr_path, encoding='utf-8')) if os.path.exists(cr_path) else {}
    cache_path = os.path.join(FINAL, 'cache', 'openalex_openalex_id.json')
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}

    # 來源 1：本人論文上寫的機構
    by_author = collections.defaultdict(lambda: {'inst': collections.Counter(),
                                                 'country': collections.Counter(),
                                                 'years': set(), 'n': 0})
    for r in mwa:
        aid = r['openalex_author_id'].strip()
        if not aid:
            continue
        d = by_author[aid]
        d['n'] += 1
        if r['oa_year'].strip():
            d['years'].add(r['oa_year'].strip())
        for x in r['institutions'].split(';'):
            if x.strip():
                d['inst'][x.strip()] += 1
        for x in r['countries'].split(';'):
            if x.strip():
                d['country'][x.strip()] += 1

    n_src = collections.Counter()
    missing = []
    for r in ext:
        aid = r.get('openalex_author_id', '').strip()
        d = by_author.get(aid) if aid else None
        m = manual.get(r['node_id'])
        if m:
            # 人工查證優先於一切自動來源，`evidence_url` 逐列可回查
            r['affil_primary'] = m['institution']
            r['affil_institution_norm'] = m['institution']
            r['affil_country'] = m['country']
            r['affil_all_json'] = json.dumps([m['institution']], ensure_ascii=False)
            r['affil_n_works'] = ''
            r['affil_years'] = ''
            r['affil_source'] = 'manual_verified'
        elif journal.get(r['node_id']):
            # 期刊 PDF 首頁直接印的機構：就是這篇論文發表當時的服務單位
            g = journal[r['node_id']]
            r['affil_primary'] = g['institution']
            r['affil_institution_norm'] = g['institution']
            r['affil_country'] = g['country']
            r['affil_all_json'] = json.dumps([g['institution']], ensure_ascii=False)
            r['affil_n_works'] = ''
            r['affil_years'] = ''
            r['affil_source'] = 'journal_pdf'
        elif d and d['inst']:
            r['affil_primary'] = d['inst'].most_common(1)[0][0]
            r['affil_country'] = d['country'].most_common(1)[0][0] if d['country'] else ''
            r['affil_all_json'] = json.dumps([k for k, _ in d['inst'].most_common()], ensure_ascii=False)
            r['affil_n_works'] = d['n']
            r['affil_years'] = ';'.join(sorted(d['years']))
            r['affil_institution_norm'] = r['affil_primary']   # 已是 OpenAlex 的機構名稱
            r['affil_source'] = 'matched_works'
        elif aid and (cache.get(aid) or {}).get('last_known_institutions'):
            insts = cache[aid]['last_known_institutions']
            r['affil_primary'] = insts[0].get('display_name', '')
            r['affil_country'] = insts[0].get('country_code', '')
            r['affil_all_json'] = json.dumps([i.get('display_name', '') for i in insts], ensure_ascii=False)
            r['affil_n_works'] = ''
            r['affil_years'] = ''
            r['affil_institution_norm'] = r['affil_primary']
            r['affil_source'] = 'openalex_last'
        elif crossref.get(r['node_id']):
            c = collections.Counter(crossref[r['node_id']])
            raw = c.most_common(1)[0][0]
            inst, ctry = normalize_affiliation(raw)
            r['affil_primary'] = raw
            r['affil_institution_norm'] = inst
            r['affil_country'] = ctry
            r['affil_all_json'] = json.dumps([k for k, _ in c.most_common()], ensure_ascii=False)
            r['affil_n_works'] = sum(c.values())
            r['affil_years'] = ''
            r['affil_source'] = 'crossref_paper'
        elif json.loads(r.get('institutions_json') or '[]'):
            ins = json.loads(r['institutions_json'])
            r['affil_primary'] = ins[0]
            r['affil_country'] = ''
            r['affil_all_json'] = json.dumps(ins, ensure_ascii=False)
            r['affil_n_works'] = ''
            r['affil_years'] = ''
            inst, ctry = normalize_affiliation(r['affil_primary'])
            r['affil_institution_norm'] = inst
            r['affil_country'] = ctry
            r['affil_source'] = 'prior_evidence'
        else:
            for k in AFFIL_FIELDS:
                r[k] = ''
            r['affil_source'] = 'none'
            missing.append({
                'node_id': r['node_id'], 'name_zh': r['name_zh'], 'name_en': r['name_en'],
                'identity_status': r['identity_status'], 'n_papers': r['n_papers'],
                'degree_all': r['degree_all'], 'degree_teacher': r['degree_teacher'],
                'openalex_author_id': aid,
                '缺的原因': ('沒有解析出 OpenAlex id（多半只有中文姓名）' if not aid
                          else 'OpenAlex 上這個人沒有機構資訊'),
            })
        n_src[r['affil_source']] += 1

    with open(MASTER, encoding='utf-8-sig') as f:
        keep = [c for c in csv.DictReader(f).fieldnames if c not in AFFIL_FIELDS]
    write_master(all_rows, keep + AFFIL_FIELDS)

    missing.sort(key=lambda r: -int(r['degree_teacher'] or 0))
    excel(EXT_NOT_FOUND, '缺機構的外部作者', MISS_FIELDS, missing,
          {'name_en': 22, 'identity_status': 22, '缺的原因': 34},
          note='連機構都查不到的外部共同作者，依「連到幾位名冊教師」排序。'
               '待查清單（附代表作與現成的搜尋字串）在 '
               'manual_review/decisions/web_lookup_queue.csv。')

    print('外部共同作者 %d 人，機構來源分布：' % len(ext))
    for k, v in n_src.most_common():
        print(f'  {k:<15} {v}')
    print(f'\n缺機構 {len(missing)} 人 → professor_demo/external_not_found.xlsx')
    got = [r for r in ext if r['affil_source'] != 'none']
    print('國別前十：', collections.Counter(r['affil_country'] for r in got if r['affil_country']).most_common(10))

    # 待查清單要在這裡才產得對——階段 4 跑的時候還不知道誰真的缺機構
    emit_web_queue(ext, rd('final_plan', 'paper', 'papers_all.csv'), set())


# ═══════════════════════════════════════════════════════════════
# 階段 7：人工查核工作表
# ═══════════════════════════════════════════════════════════════
SHEETS_OUT = os.path.join(FINAL, 'manual_review')



def sheet(name, title, note, fields, rows, widths=None):
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill
    path = os.path.join(SHEETS_OUT, name)
    if os.path.exists(path):
        print(f'  跳過（已存在，不覆蓋）：{name}')
        return
    os.makedirs(SHEETS_OUT, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws['A1'] = note
    ws['A1'].font = Font(bold=True)
    ws.append([])
    ws.append(fields)
    for c in ws[3]:
        c.font = Font(bold=True)
        c.fill = PatternFill('solid', fgColor='EEEEEE')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for r in rows:
        ws.append([r.get(f, '') for f in fields])
    ws.freeze_panes = 'A4'
    for i, f in enumerate(fields, 1):
        L = openpyxl.utils.get_column_letter(i)
        ws.column_dimensions[L].width = (widths or {}).get(f, max(10, min(40, len(f) * 2 + 6)))
    wb.save(path)
    print(f'  {len(rows):>5} 列  manual_review/{name}')



def s1():
    _, act, ext = read_master()
    ina = rd('final_plan', 'professor_demo', 'professors_inactive.csv')
    rows = []
    for r in act + ina:
        if r['oa_needs_review'] == '1':
            rows.append({
                'priority': 1000 + int(r['pub_degree_teacher'] or 0),
                '類別': '名冊教師', 'id': r['teacher_id'], '姓名': r['name_zh'],
                '英文名': r['name_en_canonical'], '我們知道的機構': r['institution_zh'],
                'NSTC頁': r['nstc_url'],
                '本人2015-2026篇數': r['n_papers'], '教師度數': r['pub_degree_teacher'],
                'OA姓名': r['openalex_display_name'], 'OA機構': r['oa_last_institution'],
                'OA國別': r['oa_country'], 'OA領域': r['oa_primary_field'],
                'OA總篇數': r['n_pubs_total'], 'OA總引用': r['n_citations_total'],
                'OA網址': r['openalex_author_id'],
                '認定方式': r['oa_match_method'], '可信度': r['oa_match_confidence'],
                '旗標': r['oa_quality_flags'],
            })
    for r in ext:
        if r['oa_needs_review'] == '1':
            rows.append({
                'priority': int(r['degree_teacher'] or 0) * 10 + min(int(r['degree_all'] or 0), 9),
                '類別': '外部作者', 'id': r['node_id'],
                '姓名': r['name_zh'], '英文名': r['name_en'],
                '我們知道的機構': (json.loads(r['institutions_json'] or '[]') or [''])[0],
                'NSTC頁': '',
                '本人2015-2026篇數': r['n_papers'], '教師度數': r['degree_teacher'],
                'OA姓名': r['openalex_display_name'], 'OA機構': r['oa_last_institution'],
                'OA國別': r['oa_country'], 'OA領域': r['oa_primary_field'],
                'OA總篇數': r['n_pubs_total'], 'OA總引用': r['n_citations_total'],
                'OA網址': r['openalex_author_id'],
                '認定方式': r['oa_match_method'], '可信度': r['oa_match_confidence'],
                '旗標': r['oa_quality_flags'],
            })
    rows.sort(key=lambda r: -r['priority'])
    F = ['類別', 'id', '姓名', '英文名', '我們知道的機構', 'NSTC頁', '本人2015-2026篇數',
         '教師度數', 'OA姓名', 'OA機構', 'OA國別', 'OA領域', 'OA總篇數', 'OA總引用', 'OA網址',
         '認定方式', '可信度', '旗標', '判定', '正確的OA網址', '備註']
    sheet('01_openalex身分查核.xlsx', 'OA身分查核',
          '判定欄填：正確 / 錯誤 / 不確定。填「錯誤」時請在「正確的OA網址」貼上正確的 '
          'OpenAlex author 頁網址；查不到就留空（會被當成沒有這個人的數字）。'
          '已依重要性排序：名冊教師在前，外部作者依「連到幾位名冊教師」排。',
          F, rows, {'OA網址': 42, 'NSTC頁': 30, 'OA機構': 30, '我們知道的機構': 22, '備註': 30})


# ── 2. 完全找不到 OpenAlex 的名冊教師 ──────────────────────────
def s2():
    """02 已經由階段 3 直接產生成 `professor_demo/openalex_not_found.xlsx`，
    內容一樣（附原因與被擋下的候選），這裡不再重複產一份。"""
    print('  跳過 02（改由 professor_demo/openalex_not_found.xlsx 提供）')


# ── 3. 同標題的論文群組 ────────────────────────────────────────
def s3():
    p = rd('final_plan', 'paper', 'papers_all.csv')
    g = collections.defaultdict(list)
    for r in p:
        k = norm_title(r['title'])
        if k:
            g[k].append(r)
    rows = []
    gid = 0
    for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
        if len(v) < 2:
            continue
        gid += 1
        for r in sorted(v, key=lambda r: r['year']):
            rows.append({
                '群組': f'G{gid:03d}', '群組篇數': len(v),
                'paper_id': r['paper_id'], '年': r['year'], '著作類別': r['pub_category'],
                'DOI': r['doi'], '出處': r['venue'], '標題': r['title'],
                '作者數': r['n_authors'], '名冊作者數': r['n_roster_authors'],
                '作者': ' | '.join(json.loads(r['author_names_json'])),
                '目前有無建邊': r['edge_eligible'], '未建邊原因': r['edge_hold_reason'],
                'NSTC來源': r['source_record_ids_json'].strip('[]').replace('"', ''),
            })
    F = ['群組', '群組篇數', 'paper_id', '年', '著作類別', 'DOI', '出處', '標題',
         '作者數', '名冊作者數', '作者', '目前有無建邊', '未建邊原因', 'NSTC來源',
         '同一篇嗎', '保留哪個paper_id', '備註']
    sheet('03_同標題論文群組.xlsx', '同標題論文',
          '一個群組一組同標題論文。「同一篇嗎」填 是 / 否；填「是」時在'
          '「保留哪個paper_id」指定要留下的那一篇（其餘併入它，作者取聯集）。'
          '目前這 431 篇裡有 430 篇沒有建邊，合併後會回到網路裡。',
          F, rows, {'標題': 60, '作者': 50, 'DOI': 26, '出處': 26, 'NSTC來源': 26})


# ── 4. 計畫的同一性 ────────────────────────────────────────────
def s4():
    """計畫同一性：2026-09-10 已裁定「同名即同一個計畫，跨年度也是」，
    這份表只留作紀錄，不再需要逐組判定。"""
    print('  跳過 04（計畫同一性已於 2026-09-10 裁定，不需再查核）')


# ── 5. 性別 ────────────────────────────────────────────────────
def s5():
    _, act, _ = read_master()
    rows = [{
        'teacher_id': r['teacher_id'], '姓名': r['name_zh'], '英文名': r['name_en_canonical'],
        '機構': r['institution_zh'], '系所': r['department_zh'], '職級': r['rank'],
        '系所頁': '', 'NSTC頁': r['nstc_url'],
        '2015-2026篇數': r['n_papers'], '教師度數': r['pub_degree_teacher'],
    } for r in sorted(act, key=lambda r: (r['institution_zh'], r['name_zh']))]
    master = {m['teacher_id']: m for m in rd('faculty_identity', 'faculty_identity_master.csv')}
    for r in rows:
        r['系所頁'] = master.get(r['teacher_id'], {}).get('official_profile_url', '')
    F = ['teacher_id', '姓名', '英文名', '機構', '系所', '職級', '系所頁', 'NSTC頁',
         '2015-2026篇數', '教師度數', '性別', '依據', '備註']
    sheet('05_性別標註.xlsx', '性別',
          '「性別」填 M / F / unknown。「依據」填 系所頁照片 / 稱謂 / 認識本人 / 推測。'
          'OpenAlex 與 Google Scholar 都沒有性別欄位，這一份只能人工做。'
          '依機構排序，同一個系的人可以一起開系所頁一次標完。',
          F, rows, {'系所頁': 40, 'NSTC頁': 30})


# ── 6. 未建邊的論文 ────────────────────────────────────────────
def s6():
    p = [r for r in rd('final_plan', 'paper', 'papers_all.csv') if r['edge_eligible'] == '0']
    rows = []
    for r in sorted(p, key=lambda r: (-int(r['n_roster_authors']), -int(r['n_authors']))):
        rows.append({
            'paper_id': r['paper_id'], '年': r['year'], '著作類別': r['pub_category'],
            '標題': r['title'], 'DOI': r['doi'], '出處': r['venue'],
            '作者數': r['n_authors'], '名冊作者數': r['n_roster_authors'],
            '作者': ' | '.join(json.loads(r['author_names_json'])),
            '未建邊原因': r['edge_hold_reason'],
            'NSTC來源': r['source_record_ids_json'].strip('[]').replace('"', ''),
        })
    F = ['paper_id', '年', '著作類別', '標題', 'DOI', '出處', '作者數', '名冊作者數',
         '作者', '未建邊原因', 'NSTC來源', '正確的作者名單', '可以建邊嗎', '備註']
    sheet('06_未建邊論文.xlsx', '未建邊論文',
          '790 篇因為作者身分不確定而沒有進網路的論文，依「名冊作者數」由多到少排——'
          '排在前面的最值得處理，因為它們才會長出教師之間的邊。'
          '「可以建邊嗎」填 是 / 否；填「是」時請在「正確的作者名單」用 | 分隔寫出正確作者。',
          F, rows, {'標題': 60, '作者': 50, '正確的作者名單': 50, 'DOI': 26, '出處': 24})


# ── 7. 外部作者的機構 ──────────────────────────────────────────
def s7():
    """自動來源都走不通的外部作者，逐人查機構。"""
    _, _, ext = read_master()
    papers = rd('final_plan', 'paper', 'papers_all.csv')
    bynode = collections.defaultdict(list)
    for r in papers:
        for i in json.loads(r['author_node_ids_json']):
            bynode[i].append(r)

    rows = []
    for r in ext:
        if r.get('affil_source', 'none') != 'none':
            continue
        ps = bynode.get(r['node_id'], [])
        rep = sorted(ps, key=lambda x: (not x['doi'], x['pub_category'] != '期刊論文',
                                        -int(x['year'])))[0] if ps else {}
        name = r['name_zh'] or r['name_en']
        rows.append({
            'priority': int(r['degree_teacher'] or 0) * 100 + min(int(r['n_papers'] or 0), 99),
            'node_id': r['node_id'], '姓名': name,
            '中文名': r['name_zh'], '英文名': r['name_en'],
            '連到幾位名冊教師': r['degree_teacher'], '論文數': r['n_papers'],
            '代表作年': rep.get('year', ''), '代表作類別': rep.get('pub_category', ''),
            '代表作出處': rep.get('venue', ''), '代表作標題': rep.get('title', ''),
            '代表作DOI': rep.get('doi', ''),
            '共同作者': ' / '.join(json.loads(rep.get('author_names_json', '[]')))[:120],
            '建議查法': ('華藝／期刊 PDF 首頁註腳' if re.search(r'[一-鿿]', rep.get('title', ''))
                     else 'Google／出版社頁面'),
        })
    rows.sort(key=lambda r: -r['priority'])
    F = ['node_id', '姓名', '中文名', '英文名', '連到幾位名冊教師', '論文數',
         '代表作年', '代表作類別', '代表作出處', '代表作標題', '代表作DOI', '共同作者',
         '建議查法', '機構', '國別', '證據網址', '查不到']
    sheet('07_外部作者機構.xlsx', '外部作者機構',
          '自動來源（OpenAlex／Crossref）都查不到機構的外部作者，依「連到幾位名冊教師」排序。'
          '填「機構」「國別」「證據網址」三欄；確認查不到就在「查不到」填 1。'
          '填好的內容請整理成 decisions/external_affiliations_manual.csv 的格式'
          '（node_id, name, institution, country, evidence, evidence_url, checked_utc）。'
          '中文論文的機構通常印在期刊 PDF 首頁的作者註腳（「作者分別為…」），'
          '華藝的書目頁只有姓名、沒有機構。',
          F, rows, {'代表作標題': 50, '共同作者': 45, '證據網址': 40, '機構': 26,
                    '代表作出處': 22})


def stage7_sheets():
    print('產生人工查核工作表 →', SHEETS_OUT)
    for f in (s1, s2, s3, s4, s5, s6, s7):
        f()
    os.makedirs(os.path.join(SHEETS_OUT, 'decisions'), exist_ok=True)
    print('填完的檔案請放到 manual_review/decisions/')


# ═══════════════════════════════════════════════════════════════
# 階段 8：把網路畫在地圖上
# ═══════════════════════════════════════════════════════════════
# 設計上的三個取捨，先講清楚免得誤讀圖：
#
# 1. **名冊教師畫在他機構的真實經緯度上**，同一間學校的人依「系所」分成扇形群集，
#    顏色＝系所。這是唯一有真實座標的一群。
# 2. **外部作者如果任職於名冊裡的 27 所機構**，畫在同一個機構的**外圈**、用三角形標記、
#    不進系所群集——他在那間學校，但不是名冊裡的經濟學家。
# 3. **其他外部作者沒有座標**，所以依「地區」分群放在台灣周圍的環上。
#    **方位是真的**（依該國中心相對台灣的方位角），**距離是示意的**（一律放在同一個環上）。
#    找不到機構的另外放一群，預設不畫。
TW_CENTER = (23.7, 121.0)
RING_R = 2.35          # 海外群集所在的環半徑（度）
RING_R2 = 3.25         # 放不下時往外挪的第二層環
TW_OTHER = (23.30, 118.55)   # 「臺灣其他機構」放在本島西邊的海上

# 各國中心的粗略經緯度，只用來算「相對台灣的方位」，不是精確座標。
COUNTRY_LATLON = {
    'TW': (23.7, 121.0), 'CN': (35.0, 105.0), 'HK': (22.3, 114.2), 'MO': (22.2, 113.5),
    'JP': (36.2, 138.3), 'KR': (36.5, 127.9), 'SG': (1.35, 103.8), 'MY': (4.2, 101.9),
    'TH': (15.9, 101.0), 'VN': (14.1, 108.3), 'ID': (-2.5, 118.0), 'PH': (12.9, 121.8),
    'IN': (21.0, 78.0), 'PK': (30.4, 69.3), 'KZ': (48.0, 66.9), 'IR': (32.4, 53.7),
    'AE': (23.4, 53.8), 'YE': (15.6, 48.5), 'RU': (61.5, 105.3), 'AU': (-25.3, 133.8),
    'NZ': (-40.9, 174.9), 'US': (39.8, -98.6), 'CA': (56.1, -106.3), 'MX': (23.6, -102.6),
    'BR': (-14.2, -51.9), 'CL': (-35.7, -71.5), 'CO': (4.6, -74.3), 'UY': (-32.5, -55.8),
    'BO': (-16.3, -63.6), 'GB': (55.4, -3.4), 'IE': (53.4, -8.2), 'FR': (46.2, 2.2),
    'DE': (51.2, 10.5), 'NL': (52.1, 5.3), 'BE': (50.5, 4.5), 'LU': (49.8, 6.1),
    'CH': (46.8, 8.2), 'AT': (47.5, 14.6), 'IT': (41.9, 12.6), 'ES': (40.5, -3.7),
    'PT': (39.4, -8.2), 'SE': (60.1, 18.6), 'NO': (60.5, 8.5), 'DK': (56.3, 9.5),
    'IS': (64.9, -19.0), 'PL': (51.9, 19.1), 'CZ': (49.8, 15.5), 'HU': (47.2, 19.5),
    'MK': (41.6, 21.7), 'ME': (42.7, 19.4), 'SL': (8.5, -11.8), 'ZA': (-30.6, 22.9),
    'KE': (-0.02, 37.9), 'EG': (26.8, 30.8), 'SN': (14.5, -14.5),
}

# 外部作者的機構字串對回名冊 27 校時，這幾個寫法要特別接。
INST_ALIAS = {
    'instituteofeconomicsacademiasinica': '中央研究院經濟研究所',
    'academiasinica': '中央研究院經濟研究所',
    'researchcenterforhumanitiesandsocialsciences': '中央研究院人文社會科學研究中心',
}


def _norm_inst(s):
    return re.sub(r'[^a-z0-9一-鿿]', '', (s or '').lower())


def _bearing_xy(country):
    """該國相對台灣的方位角 → 單位向量（x=東, y=北）。查不到就回 None。"""
    ll = COUNTRY_LATLON.get(country)
    if not ll:
        return None
    dy = ll[0] - TW_CENTER[0]
    dx = (ll[1] - TW_CENTER[1]) * math.cos(math.radians(TW_CENTER[0]))
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return None
    return dx / n, dy / n


def _pack(cx, cy, n, r0, dr=0.055, per=8):
    """把 n 個點排成同心圈，回傳座標 list。點少時就排成一小圈。"""
    pts = []
    k, ring = 0, 0
    while len(pts) < n:
        cap = max(1, int(per * (1 + ring)))
        r = r0 + dr * ring
        m = min(cap, n - len(pts))
        for i in range(m):
            a = 2 * math.pi * i / max(m, 3) + 0.6 * ring
            pts.append((cx + r * math.cos(a) * 1.08, cy + r * math.sin(a)))
        ring += 1
        k += 1
        if k > 40:
            break
    return pts[:n]


def load_geojson_counties(max_pts=1200):
    """讀縣市界，順便抽稀（原檔 8MB，畫圖用不到那個精度）。"""
    path = os.path.join(ROOT, 'faculty_and_map', 'output', 'basemap', 'tw_county.geojson')
    if not os.path.exists(path):
        return []
    gj = json.load(open(path, encoding='utf-8'))
    polys = []
    for feat in gj.get('features', []):
        geom = feat.get('geometry') or {}
        chunks = ([geom.get('coordinates')] if geom.get('type') == 'Polygon'
                  else geom.get('coordinates') or [])
        for poly in chunks:
            for ring in poly:
                if len(ring) < 4:
                    continue
                step = max(1, len(ring) // max_pts)
                polys.append([(p[0], p[1]) for p in ring[::step]])
    return polys


def build_map_positions(show_external, show_unknown):
    """算出每個節點要畫在哪裡，回傳 (pos, meta, clusters)。"""
    insts = rd('final_plan', 'map', 'institutions.csv')
    geo = {r['teacher_id']: r for r in rd('final_plan', 'map', 'professor_geo.csv')}
    all_rows, roster, ext = read_master()

    inst_by_key, inst_by_code = {}, {}
    for r in insts:
        if not (r['lat'] and r['lon']):
            continue
        inst_by_code[r['institution_code']] = r
        for nm in (r['institution_name'], r['institution_en']):
            if nm:
                inst_by_key[_norm_inst(nm)] = r

    pos, meta = {}, {}

    # ── 1. 名冊教師：真實機構座標，同校內依系所分扇形
    by_inst = collections.defaultdict(list)
    for r in roster:
        g = geo.get(r['teacher_id'])
        if g and g['lat'] and g['lon']:
            by_inst[g['institution_code']].append(r)
    for code, members in by_inst.items():
        ii = inst_by_code.get(code)
        if not ii:
            continue
        cx, cy = float(ii['lon']), float(ii['lat'])
        depts = collections.defaultdict(list)
        for r in members:
            depts[r['department_zh'] or '（未填系所）'].append(r)
        d_names = sorted(depts, key=lambda d: -len(depts[d]))
        for di, d in enumerate(d_names):
            frac = (di + 0.5) / len(d_names)
            ang = 2 * math.pi * frac
            k = len(depts[d])
            spread = 0.020 + 0.012 * math.sqrt(k)
            dx, dy = math.cos(ang) * spread, math.sin(ang) * spread
            for (x, y), r in zip(_pack(cx + dx * 1.4, cy + dy, k, 0.012, 0.013, 6), depts[d]):
                pos[r['node_id']] = (x, y)
                meta[r['node_id']] = {'kind': 'roster', 'dept': d,
                                      'inst': ii['institution_name'], 'name': r['name_zh']}

    clusters = []
    if not show_external:
        return pos, meta, clusters

    # ── 2. 外部作者：先分成「在名冊機構」與「其他地區」
    at_inst = collections.defaultdict(list)
    by_region = collections.defaultdict(list)
    unknown = []
    for r in ext:
        a = r.get('affil_institution_norm') or ''
        k = _norm_inst(a)
        hit = inst_by_key.get(k) or inst_by_key.get(_norm_inst(INST_ALIAS.get(k, '')))
        if hit:
            at_inst[hit['institution_code']].append(r)
        elif a:
            by_region[r.get('affil_country') or '??'].append(r)
        else:
            unknown.append(r)

    # 2a. 在名冊機構的：畫在同一間學校的外圈，三角形，不進系所群集
    for code, members in at_inst.items():
        ii = inst_by_code.get(code)
        if not ii:
            continue
        cx, cy = float(ii['lon']), float(ii['lat'])
        for (x, y), r in zip(_pack(cx, cy, len(members), 0.072, 0.016, 14), members):
            pos[r['node_id']] = (x, y)
            meta[r['node_id']] = {'kind': 'ext_at_roster', 'inst': ii['institution_name'],
                                  'name': r['name_zh'] or r['name_en']}

    # 2b. 其他地區：方位取真實方位角，距離是示意的
    order = sorted(by_region.items(), key=lambda kv: -len(kv[1]))
    ring1 = [(c, v) for c, v in order if c != 'TW' and _bearing_xy(c)]
    other = [(c, v) for c, v in order if c != 'TW' and not _bearing_xy(c)]

    # 臺灣但不在名冊 27 校的機構（中經院、台經院、其他大學…）：放本島西邊的海上，
    # 不放進海外環，免得跟國外混在一起。
    tw_other = by_region.get('TW', [])
    if tw_other:
        cx, cy = TW_OTHER[1], TW_OTHER[0]
        for (x, y), m in zip(_pack(cx, cy, len(tw_other), 0.05, 0.026, 16), tw_other):
            pos[m['node_id']] = (x, y)
            meta[m['node_id']] = {'kind': 'ext_region', 'region': 'TW（非名冊機構）',
                                  'inst': m.get('affil_institution_norm', ''),
                                  'name': m['name_zh'] or m['name_en']}
        clusters.append((cx, cy, f'臺灣其他機構（{len(tw_other)}）', 'region'))
    used = []
    for idx, (c, members) in enumerate(ring1):
        ux, uy = _bearing_xy(c)
        r = RING_R if c != 'TW' else 1.75
        # 方位太接近的往外挪一層，免得疊在一起
        while any(abs(ux * r - x) < 0.55 and abs(uy * r - y) < 0.55 for x, y in used):
            r += 0.62
        cx, cy = TW_CENTER[1] + ux * r, TW_CENTER[0] + uy * r
        used.append((cx - TW_CENTER[1], cy - TW_CENTER[0]))
        for (x, y), m in zip(_pack(cx, cy, len(members), 0.05, 0.035, 12), members):
            pos[m['node_id']] = (x, y)
            meta[m['node_id']] = {'kind': 'ext_region', 'region': c,
                                  'inst': m.get('affil_institution_norm', ''),
                                  'name': m['name_zh'] or m['name_en']}
        clusters.append((cx, cy, f'{c}（{len(members)}）', 'region'))
    for i, (c, members) in enumerate(other):
        cx, cy = TW_CENTER[1] - RING_R2, TW_CENTER[0] - RING_R2 + i * 0.5
        for (x, y), m in zip(_pack(cx, cy, len(members), 0.05, 0.035, 12), members):
            pos[m['node_id']] = (x, y)
            meta[m['node_id']] = {'kind': 'ext_region', 'region': '國別不明',
                                  'inst': m.get('affil_institution_norm', ''),
                                  'name': m['name_zh'] or m['name_en']}
        clusters.append((cx, cy, f'有機構但國別不明（{len(members)}）', 'region'))

    # 2c. 連機構都找不到的
    if show_unknown and unknown:
        cx, cy = TW_CENTER[1] + 0.1, TW_CENTER[0] - RING_R2 - 0.35
        for (x, y), m in zip(_pack(cx, cy, len(unknown), 0.08, 0.03, 30), unknown):
            pos[m['node_id']] = (x, y)
            meta[m['node_id']] = {'kind': 'ext_unknown', 'region': '機構不明',
                                  'inst': '', 'name': m['name_zh'] or m['name_en']}
        clusters.append((cx, cy, f'機構不明（{len(unknown)}）', 'unknown'))

    return pos, meta, clusters


def stage8_map(layer='pub', show_external=False, show_unknown=False,
               year_from=YEAR_MIN, year_to=YEAR_MAX, min_weight=0.0, outfile=None):
    """把某一層網路畫在台灣地圖上。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.collections import LineCollection, PolyCollection

    for f in ('PingFang TC', 'Heiti TC', 'Arial Unicode MS', 'Noto Sans CJK TC',
              'Microsoft JhengHei'):
        if any(f == x.name for x in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams['font.sans-serif'] = [f]
            break
    else:
        print('  ⚠ 找不到中文字型，圖上的中文會變成方框')
    plt.rcParams['axes.unicode_minus'] = False

    pos, meta, clusters = build_map_positions(show_external, show_unknown)

    files = {'pub': 'paper_network_edges.csv', 'proj': 'project_network_edges.csv'}
    layers = ['pub', 'proj'] if layer == 'both' else [layer]
    edges = []
    for lay in layers:
        for e in rd('final_plan', 'network', files[lay]):
            y = int(e['year'])
            if not (year_from <= y <= year_to):
                continue
            a, b = e['source_node_id'], e['target_node_id']
            if a not in pos or b not in pos:
                continue
            edges.append((a, b, float(e['weight_1n']), lay))
    agg = collections.defaultdict(float)
    kind = {}
    for a, b, w, lay in edges:
        k = (a, b) if a < b else (b, a)
        agg[k] += w
        kind[k] = lay
    agg = {k: v for k, v in agg.items() if v >= min_weight}
    drawn = {n for k in agg for n in k}

    fig, ax = plt.subplots(figsize=(15.5 if show_external else 12.5, 13), dpi=170)
    ax.set_facecolor('#fbfbfd')

    polys = load_geojson_counties()
    if polys:
        ax.add_collection(PolyCollection(polys, facecolors='#e9edf1',
                                         edgecolors='#ffffff', linewidths=0.6, zorder=0))

    # 邊
    for lay, col, alpha in (('pub', '#4c78a8', 0.16), ('proj', '#e4572e', 0.5)):
        segs = [[pos[a], pos[b]] for (a, b), w in agg.items() if kind[(a, b)] == lay]
        wid = [min(2.6, 0.28 + 1.5 * w) for (a, b), w in agg.items() if kind[(a, b)] == lay]
        if segs:
            ax.add_collection(LineCollection(segs, colors=col, linewidths=wid,
                                             alpha=alpha, zorder=1))

    # 節點
    dcount = collections.Counter(m['dept'] for m in meta.values() if m['kind'] == 'roster')
    depts = [d for d, _ in dcount.most_common()]        # 大的排前面，圖例才有用
    cmap = plt.get_cmap('tab20')
    dcol = {d: cmap(i % 20) for i, d in enumerate(depts)}
    groups = {'roster': ([], [], []), 'ext_at_roster': ([], []),
              'ext_region': ([], []), 'ext_unknown': ([], [])}
    for nid, m in meta.items():
        if nid not in pos or (drawn and nid not in drawn):
            continue
        x, y = pos[nid]
        if m['kind'] == 'roster':
            groups['roster'][0].append(x)
            groups['roster'][1].append(y)
            groups['roster'][2].append(dcol[m['dept']])
        else:
            groups[m['kind']][0].append(x)
            groups[m['kind']][1].append(y)
    # 外部作者畫在名冊教師底下，免得紅三角把整座島蓋掉
    ax.scatter(*groups['ext_at_roster'], s=13, marker='^', facecolors='none',
               edgecolors='#c1121f', linewidths=0.6, alpha=0.8, zorder=2.5)
    ax.scatter(groups['roster'][0], groups['roster'][1], s=24,
               c=groups['roster'][2], edgecolors='#2b2b2b', linewidths=0.35, zorder=5)
    ax.scatter(*groups['ext_region'], s=7, marker='s', c='#6f7480',
               alpha=0.7, linewidths=0, zorder=2)
    ax.scatter(*groups['ext_unknown'], s=7, marker='x', c='#b7bcc4',
               alpha=0.65, linewidths=0.45, zorder=2)

    for cx, cy, label, typ in clusters:
        ax.annotate(label, (cx, cy), xytext=(0, -30), textcoords='offset points',
                    ha='center', fontsize=8.6, zorder=6,
                    color='#3b3b3b' if typ == 'region' else '#8a8a8a',
                    path_effects=[__import__('matplotlib.patheffects', fromlist=['x'])
                                  .withStroke(linewidth=2.2, foreground='white')])
    import matplotlib.patheffects as pe
    thr = 6 if show_external else 4
    for r in rd('final_plan', 'map', 'institutions.csv'):
        if r['lat'] and int(r['n_active']) >= thr:
            ax.annotate(r['institution_name'].replace('國立', '').replace('學校財團法人', ''),
                        (float(r['lon']), float(r['lat'])),
                        xytext=(0, 13), textcoords='offset points', ha='center',
                        fontsize=7.4, color='#12314f', zorder=6,
                        path_effects=[pe.withStroke(linewidth=2.4, foreground='white')])

    handles = [Line2D([], [], marker='o', ls='', mfc=dcol[d], mec='#333', ms=7,
                      label=f'{d}（{dcount[d]}）') for d in depts[:10]]
    handles += [
        Line2D([], [], marker='^', ls='', mfc='none', mec='#c1121f', ms=9,
               label='外部作者（在名冊機構，但不是名冊經濟學家）'),
        Line2D([], [], marker='s', ls='', mfc='#7a7a7a', mec='none', ms=7,
               label='外部作者（依地區分群，方位真實、距離示意）'),
        Line2D([], [], marker='x', ls='', mec='#b0b0b0', ms=8, label='外部作者（機構不明）'),
        Line2D([], [], color='#4c78a8', lw=2, label='共著邊'),
        Line2D([], [], color='#e4572e', lw=2, label='共同計畫邊'),
    ]
    ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.005, 1.0),
              fontsize=7.8, framealpha=1.0, borderpad=0.7,
              title='系所（前 10 大）與節點類型', title_fontsize=8.6)

    name = {'pub': '共著網路', 'proj': '計畫網路', 'both': '共著＋計畫網路'}[layer]
    ax.set_title(f'台灣經濟學者{name}　{year_from}–{year_to}\n'
                 f'節點 {len(drawn)}　邊 {len(agg)}　'
                 f'{"含" if show_external else "不含"}非名冊共同作者'
                 f'{"（含機構不明者）" if show_unknown else ""}',
                 fontsize=13.5, pad=14)
    xs = [p[0] for n, p in pos.items() if not drawn or n in drawn]
    ys = [p[1] for n, p in pos.items() if not drawn or n in drawn]
    xs += [c[0] for c in clusters] + [119.3, 122.1]      # 至少框住本島
    ys += [c[1] for c in clusters] + [21.85, 25.35]
    padx = (max(xs) - min(xs)) * 0.06 + 0.12
    pady = (max(ys) - min(ys)) * 0.06 + 0.12
    ax.set_xlim(min(xs) - padx, max(xs) + padx)
    ax.set_ylim(min(ys) - pady, max(ys) + pady)
    ax.set_aspect(1 / math.cos(math.radians(TW_CENTER[0])))
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.text(0.5, -0.02,
            '名冊教師畫在機構的真實經緯度，同校內依系所分群、顏色＝系所；'
            '海外與非名冊機構沒有座標，依地區分群，方位依該國相對台灣的方位角，距離是示意的。',
            transform=ax.transAxes, ha='center', va='top', fontsize=8.2, color='#666')

    outdir = os.path.join(FINAL, 'figures')
    os.makedirs(outdir, exist_ok=True)
    if not outfile:
        outfile = os.path.join(outdir, 'map_%s%s%s_%d_%d.png' % (
            layer, '_ext' if show_external else '', '_unk' if show_unknown else '',
            year_from, year_to))
    elif not os.path.isabs(outfile):
        outfile = os.path.join(outdir, outfile)
    fig.savefig(outfile, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  節點 {len(drawn)}、邊 {len(agg)} → {os.path.relpath(outfile, ROOT)}')
    return outfile


# ═══════════════════════════════════════════════════════════════
# 階段 9：互動式 HTML 地圖（單一檔案，離線可開）
# ═══════════════════════════════════════════════════════════════
# 保留個別作者與連線；地圖才彙總機構／地區，網路模式顯示個人。
# 海外使用大圓方位與單調壓縮距離，台灣保持中央與本地比例。
BUBBLE_MIN, BUBBLE_MAX = 0.07, 0.42      # 泡泡半徑（度）


def _svg_paths(polys, lat0, lon0):
    """把經緯度多邊形轉成 SVG path，順便做等距圓柱投影的長寬校正。"""
    k = math.cos(math.radians(lat0))
    out = []
    for ring in polys:
        pts = ['%.4f,%.4f' % ((x - lon0) * k, -(y - lat0)) for x, y in ring]
        if len(pts) > 3:
            out.append('M' + 'L'.join(pts) + 'Z')
    return out


def _county_key(s):
    return (s or '').replace('台', '臺').strip()


def _rdp(pts, eps):
    """Ramer–Douglas–Peucker。照 `faculty_and_map/code/cleaning/make_html.py` 的作法：
    每隔 N 點抽稀會把海岸線抽歪，RDP 只丟掉「對形狀沒貢獻」的點，圖才不會走樣。"""
    if len(pts) < 3:
        return pts

    def d(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** .5
        t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        return ((x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2) ** .5

    stack, keep = [(0, len(pts) - 1)], [False] * len(pts)
    keep[0] = keep[-1] = True
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        dm, idx = 0, i
        for k in range(i + 1, j):
            dd = d(pts[k], pts[i], pts[j])
            if dd > dm:
                dm, idx = dd, k
        if dm > eps:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def load_counties(lat0, lon0, eps=0.0018, min_pts=6):
    """縣市界，一縣一組 SVG path。地圖底圖固定用 `faculty_and_map/output/basemap/`
    那一份（與原本的 map_explorer 同源），簡化方式也照它的 RDP。"""
    path = os.path.join(ROOT, 'faculty_and_map', 'output', 'basemap', 'tw_county.geojson')
    if not os.path.exists(path):
        path = os.path.join(FINAL, 'basemap copy', 'tw_county.geojson')
    if not os.path.exists(path):
        raise FileNotFoundError('找不到 tw_county.geojson；無法產生台灣底圖')
    gj = json.load(open(path, encoding='utf-8'))
    out = []
    for feat in gj.get('features', []):
        pr = feat.get('properties') or {}
        name = _county_key(pr.get('COUNTYNAME') or pr.get('name') or '')
        geom = feat.get('geometry') or {}
        chunks = ([geom.get('coordinates')] if geom.get('type') == 'Polygon'
                  else geom.get('coordinates') or [])
        rings = []
        for poly in chunks:
            for ring in poly:
                r = _rdp([(round(p[0], 4), round(p[1], 4)) for p in ring], eps)
                if len(r) >= min_pts:
                    rings.append(r)
        if rings:
            out.append({'n': name, 'd': _svg_paths(rings, lat0, lon0)})
    return out


def build_html_payload():
    """算出 HTML 要用的全部東西：縣市、機構、節點、泡泡、邊、論文、計畫。"""
    pos, meta, _ = build_map_positions(show_external=True, show_unknown=True)
    _, roster, ext = read_master()
    info = {r['node_id']: r for r in roster + ext}
    geo = {r['teacher_id']: r for r in rd('final_plan', 'map', 'professor_geo.csv')}

    # ── 地區泡泡
    reg = collections.defaultdict(list)
    for nid, m in meta.items():
        if m['kind'] in ('ext_region', 'ext_unknown'):
            reg[m['region']].append(nid)
    bubbles, in_bubble = [], {}
    mx = max((len(v) for v in reg.values()), default=1)
    for name, ids in sorted(reg.items(), key=lambda kv: -len(kv[1])):
        cx = sum(pos[i][0] for i in ids) / len(ids)
        cy = sum(pos[i][1] for i in ids) / len(ids)
        r = BUBBLE_MIN + (BUBBLE_MAX - BUBBLE_MIN) * math.sqrt(len(ids) / mx)
        bid = 'B:' + name
        insts = collections.Counter(
            (info[i].get('affil_institution_norm') or '（不明）') for i in ids)
        bubbles.append({'id': bid, 'label': name, 'n': len(ids), 'x': cx, 'y': cy, 'r': r,
                        'unknown': int(meta[ids[0]]['kind'] == 'ext_unknown'),
                        'top': [[k, v] for k, v in insts.most_common(8)]})
        for i in ids:
            in_bubble[i] = bid

    # ── 論文與計畫（給個人檔案與「這條邊合作了哪幾篇」用）
    papers = rd('final_plan', 'paper', 'papers_all.csv')
    pidx, plist = {}, []
    node_papers = collections.defaultdict(list)
    for p in papers:
        ids = json.loads(p['author_node_ids_json'])
        if not ids:
            continue
        pidx[p['paper_id']] = len(plist)
        plist.append([p['title'][:180], int(p['year']), p['pub_category'],
                      (p['venue'] or '')[:80]])
        for i in ids:
            node_papers[i].append(pidx[p['paper_id']])

    jlist, node_projs = [], collections.defaultdict(list)
    for pj in rd('final_plan', 'project', 'projects_all.csv'):
        k = len(jlist)
        jlist.append([pj['project_title'][:160], int(pj['year']), pj['grant_category'][:24]])
        for t in json.loads(pj['member_teacher_ids_json']):
            node_projs[t].append(k)

    # ── 節點
    nodes = []
    for nid, m in meta.items():
        r = info.get(nid, {})
        g = geo.get(nid, {})
        nodes.append({
            'id': nid, 'k': 0 if m['kind'] == 'roster' else 1,
            'x': pos[nid][0], 'y': pos[nid][1],
            'name': m.get('name') or nid, 'inst': m.get('inst', ''),
            'ic': g.get('institution_code', ''),
            'bi': next((j for j, b in enumerate(bubbles) if b['id'] == in_bubble.get(nid)), None),
            'country': r.get('affil_country', '') or ('TW' if m['kind'] == 'roster' else ''),
            'cty': _county_key(g.get('county', '')),
            'dept': m.get('dept', ''),
            'cite': r.get('n_citations_total', ''), 'oapub': r.get('n_pubs_total', ''),
            'np': r.get('n_papers', ''), 'nj': r.get('n_projects', ''),
            'pi': node_papers.get(nid, []), 'ji': node_projs.get(nid, []),
            'em': r.get('official_email', ''),
            'or': (r.get('orcid') or r.get('openalex_orcid')
                   or (json.loads(r.get('orcid_json') or '[]') or [''])[0]),
            'pf': r.get('official_profile_url', ''),
            'pfs': int(r.get('profile_url_shared_by') or 0),
            'pw': r.get('personal_website', ''),
            'ns': r.get('nstc_url', ''), 'cv': r.get('cv_url', ''),
            'oa': r.get('openalex_author_id', ''),
            'oaconf': r.get('oa_match_confidence', ''),
        })
    idx = {n['id']: i for i, n in enumerate(nodes)}

    # 外部作者掛在名冊機構時，補上機構代碼，讓「機構→人」清單也看得到他
    code_by_name = {r['institution_name']: r['institution_code']
                    for r in rd('final_plan', 'map', 'institutions.csv')}
    cty_by_code = {r['institution_code']: _county_key(r['county'])
                   for r in rd('final_plan', 'map', 'institutions.csv')}
    for n in nodes:
        if n['k'] == 1 and not n['ic']:
            n['ic'] = code_by_name.get(n['inst'], '')
            n['cty'] = cty_by_code.get(n['ic'], '')

    def slot(nid):
        return idx.get(nid)

    edges = []
    for lay, fn in ((0, 'paper_network_edges.csv'), (1, 'project_network_edges.csv')):
        for e in rd('final_plan', 'network', fn):
            a, b = slot(e['source_node_id']), slot(e['target_node_id'])
            if a is None or b is None or a == b:
                continue
            edges.append([min(a, b), max(a, b), int(e['year']),
                          round(float(e['weight_1n']), 4), lay,
                          1 if (e['source_teacher_id'] and e['target_teacher_id']) else 0,
                          e.get('paper_id') or (e.get('project_family_key', '') + ':' + e['year'] if lay else e.get('edge_id'))])

    lat0, lon0 = TW_CENTER
    k = math.cos(math.radians(lat0))
    for n in nodes + bubbles:
        n['x'], n['y'] = round((n['x'] - lon0) * k, 4), round(-(n['y'] - lat0), 4)
        if 'r' in n:
            n['r'] = round(n['r'] * k, 4)
    # Azimuthal equidistant bearing with a monotone compressed distance.
    # Taiwan keeps its local map scale; foreign anchors are explicitly schematic.
    for b in bubbles:
        country = b['label']
        ll = COUNTRY_LATLON.get(country)
        b['members'] = [idx[i] for i in reg[country] if i in idx]
        b['km'] = None
        if ll and country != 'TW':
            la1, lo1 = map(math.radians, TW_CENTER)
            la2, lo2 = map(math.radians, ll)
            dl = (lo2 - lo1 + math.pi) % (2 * math.pi) - math.pi
            angle = math.atan2(math.sin(dl) * math.cos(la2),
                               math.cos(la1) * math.sin(la2) -
                               math.sin(la1) * math.cos(la2) * math.cos(dl))
            arc = math.acos(max(-1, min(1, math.sin(la1)*math.sin(la2) +
                         math.cos(la1)*math.cos(la2)*math.cos(dl))))
            b['km'] = round(6371 * arc)
            radius = 2.25 + 2.0 * math.log1p(b['km']/1000) / math.log1p(20000/1000)
            b['x'], b['y'] = radius * math.sin(angle), -radius * math.cos(angle)
        elif country.startswith('TW'):
            b['x'], b['y'] = -1.9, .45
        else:
            b['unknown'] = 1
            b['x'], b['y'] = (2.6 if country == '機構不明' else -2.6), 3.1
    insts = []
    for r in rd('final_plan', 'map', 'institutions.csv'):
        if not r['lat']:
            continue
        insts.append({'c': r['institution_code'],
                      'n': r['institution_name'].replace('學校財團法人', ''),
                      'cty': _county_key(r['county']),
                      'x': round((float(r['lon']) - lon0) * k, 4),
                      'y': round(-(float(r['lat']) - lat0), 4),
                      'na': int(r['n_active']), 'nr': int(r['n_roster']),
                      'np': int(r['n_papers']), 'nj': int(r['n_projects'])})

    return {
        'nodes': nodes, 'bubbles': bubbles, 'edges': edges, 'insts': insts,
        'counties': load_counties(lat0, lon0),
        'papers': plist, 'projects': jlist,
        'depts': [d for d, _ in collections.Counter(
            n['dept'] for n in nodes if n['k'] == 0 and n['dept']).most_common()],
        'years': [YEAR_MIN, YEAR_MAX],
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台灣經濟學者合作網路 · 地圖</title>
<style>
:root{color-scheme:light only;--bg:#f6f7f8;--fg:#16181b;--mut:#6e7278;--line:#e3e5e8;
 --sea:#eaeef2;--land:#fff;--hl:#fdf6e6;--panel:#fff;--acc:#2f6f9f;--acc2:#d1583a}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;height:100vh;display:flex;flex-direction:column;color:var(--fg);background:var(--bg);
 font:13.5px/1.65 -apple-system,"PingFang TC","Noto Sans TC",system-ui,sans-serif}
header{padding:9px 16px;border-bottom:1px solid var(--line);background:var(--panel);
 display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:14.5px;margin:0;font-weight:660;letter-spacing:.01em;white-space:nowrap}
#crumb{font-size:12px;color:var(--mut)}#crumb b{color:var(--fg)}
.ctl{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut);white-space:nowrap}
select{font:inherit;font-size:12px;color:var(--fg);background:var(--panel);
 border:1px solid var(--line);border-radius:6px;padding:2px 6px}
input[type=range]{accent-color:var(--acc);width:82px}
label.sw{display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;font-size:12px;color:var(--mut)}
button{font:inherit;font-size:12px;border:1px solid var(--line);background:var(--panel);
 border-radius:6px;padding:2px 9px;cursor:pointer;color:var(--fg)}
button:hover{background:var(--hl)}
button[aria-pressed=true]{background:var(--acc);color:#fff;border-color:var(--acc)}
.grow{margin-left:auto}
#wrap{display:grid;grid-template-columns:minmax(0,1fr) 350px;flex:1;min-height:0}
@media(max-width:940px){body{height:auto}#wrap{grid-template-columns:1fr}#mapbox{height:64vh}}
#mapbox{position:relative;background:var(--sea);overflow:hidden}
svg{width:100%;height:100%;display:block;touch-action:none}
#svg{cursor:grab}#svg.drag{cursor:grabbing}
path.cty{fill:var(--land);stroke:#ccd0d5;stroke-width:.7px;vector-effect:non-scaling-stroke;
 cursor:pointer;transition:fill .15s}
path.cty:hover{fill:var(--hl)}
path.cty.on{fill:#fdf3dd;stroke:#8a7a55;stroke-width:1.4px}
path.cty.dim{fill:#f2f3f4;opacity:.75}
.edge{fill:none;stroke-linecap:round;cursor:pointer}
.edge:hover,.edge.on{stroke-opacity:.95!important;stroke:#b3651f!important}
.nd{stroke:#2b2b2b;stroke-width:.6px;vector-effect:non-scaling-stroke;cursor:pointer}
.nd.ext{fill:#fff;fill-opacity:.55;stroke:#c1121f;stroke-width:1.1px}
.nd.sel{stroke:#b3651f;stroke-width:2.4px}
.inst{fill:#3b6ea5;fill-opacity:.5;stroke:#22506f;stroke-width:1px;vector-effect:non-scaling-stroke;cursor:pointer}
.inst.sel{stroke:#b3651f;stroke-width:2.4px}
.inst.dimc{fill-opacity:.16;stroke-opacity:.35}
.inst:hover{stroke:#111;stroke-width:1.8px}
.bub{fill:#8a9099;fill-opacity:.3;stroke:#6c727a;stroke-width:1px;vector-effect:non-scaling-stroke;cursor:pointer}
.bub.unk{fill:#c5c9ce;stroke:#b0b4b9;stroke-dasharray:3 3}
.bub:hover,.nd:hover{stroke:#111;stroke-width:1.8px}
text{pointer-events:none;font-family:-apple-system,"PingFang TC","Noto Sans TC",sans-serif}
text.instlb{font-weight:600;fill:#12314f;paint-order:stroke;stroke:#fff;stroke-linejoin:round}
text.bl{font-weight:650;fill:#3a3f46;paint-order:stroke;stroke:#fff;stroke-linejoin:round}
text.bn{fill:#70737a;paint-order:stroke;stroke:#fff}
#side{border-left:1px solid var(--line);background:var(--panel);padding:14px 16px;overflow:auto}
#side h2{font-size:13.5px;margin:0 0 4px;font-weight:660}
#side h3{font-size:12px;margin:14px 0 6px;font-weight:660;color:var(--mut)}
.k{color:var(--mut);font-size:12px}
.row{display:flex;justify-content:space-between;gap:10px;padding:3px 0;border-bottom:1px dotted #eee;font-size:12.5px}
.row b{font-weight:600;font-variant-numeric:tabular-nums}
.lst{margin:0;padding:0;list-style:none}
.lst li{padding:5px 2px;border-bottom:1px solid #f1f1f1;font-size:12.5px;cursor:pointer}
.lst li:hover{background:var(--hl)}
.lst .m{color:var(--mut);font-size:11.5px}
.pl{margin:0;padding:0;list-style:none;font-size:12px}
.pl li{padding:3px 0;border-bottom:1px dotted #f0f0f0;color:#33363a}
.pl .m{color:var(--mut)}
.back{font-size:12px;color:var(--acc);cursor:pointer;display:inline-block;margin-bottom:8px}
.legend{margin-top:14px;font-size:11.5px;color:var(--mut)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.note{margin-top:14px;font-size:11.5px;color:var(--mut);line-height:1.7;border-top:1px solid var(--line);padding-top:10px}
.pill{display:inline-block;padding:1px 7px;border-radius:10px;background:#eef2f6;color:#2f6f9f;font-size:11px}
.pill.ext{background:#fdeceb;color:#c1121f}
#side a{color:var(--acc);text-decoration:none}#side a:hover{text-decoration:underline}
.warn{display:block;color:#b45309;font-weight:400;font-size:11px;line-height:1.5;margin-top:2px}
#chart rect{fill:var(--acc)}#chart text{font-size:8px;fill:var(--mut)}
#netbox{position:absolute;inset:0;background:#fcfcfd}
#nsvg{cursor:grab}.rail{pointer-events:auto;cursor:pointer}.hoverlabel{display:none}.netperson:hover .hoverlabel{display:block}
#focusinfo button{margin:6px 0}#netnote{pointer-events:none;background:#ffffffde;max-width:90%;padding:5px 8px;border-radius:5px}
.netnote{position:absolute;top:8px;left:12px;font-size:11.5px;color:var(--mut);z-index:2}
</style></head><body>
<header>
  <h1>台灣經濟學者合作網路</h1>
  <span id="crumb"></span>
  <div class="ctl">檢視
    <select id="view"><option value="map">地圖</option><option value="net">合作網路</option></select>
  </div>
  <div class="ctl">網路
    <select id="layer"><option value="0">共著（論文）</option><option value="1">共同計畫</option><option value="2">兩層一起看</option></select>
  </div>
  <label class="sw"><input type="checkbox" id="ext" checked> 非名冊共同作者</label>
  <label class="sw"><input type="checkbox" id="peers"> 含非名冊彼此合作</label>
  <label class="sw"><input type="checkbox" id="names"> 所有姓名</label>
  <label class="sw"><input type="checkbox" id="unk" disabled> 含機構不明</label>
  <div class="ctl">年份 <input type="range" id="y0" min="__Y0__" max="__Y1__" value="__Y0__">
    <span id="ylab" style="font-variant-numeric:tabular-nums"></span>
    <input type="range" id="y1" min="__Y0__" max="__Y1__" value="__Y1__"></div>
  <div class="ctl">連線
    <select id="scope"><option value="all">全部</option><option value="cross">只看跨機構</option><option value="within">只看校內</option></select>
    <select id="minp"><option value="1">≥1 筆</option><option value="2">≥2 筆</option><option value="3">≥3 筆</option><option value="5">≥5 筆</option></select>
  </div>
  <div class="ctl" id="netctl" hidden>排列
    <select id="netlay"><option value="force">力導向 · 機構分色</option><option value="ring">環狀 · 依機構排序</option></select>
  </div>
  <div class="ctl">找人 <input id="search" list="people" placeholder="姓名／機構" style="width:145px"><datalist id="people"></datalist></div>
  <button id="global">全台總覽</button><span class="grow"></span>
  <button id="back" hidden>← 回全台</button>
  <button id="reset">重設視野</button>
  <span class="k" id="stat"></span>
</header>
<div id="wrap">
  <div id="mapbox">
    <svg id="svg"><g id="root"><g id="gmap"></g><g id="gedge"></g><g id="gnode"></g><g id="glab"></g></g></svg>
    <div id="netbox" hidden><div class="netnote" id="netnote"></div><svg id="nsvg"></svg></div>
  </div>
  <aside id="side"><div id="focusinfo"></div><div id="details"></div></aside>
</div>
<script>
const D=__DATA__, NODES=D.nodes, BUB=D.bubbles, N=NODES.length;
const regionNames=new Intl.DisplayNames(['zh-Hant'],{type:'region'});
BUB.forEach(b=>{if(/^[A-Z]{2}$/.test(b.label))b.label=regionNames.of(b.label)+' '+b.label});
const PAL=["#3b6ea5","#a8c5e2","#e08a1e","#f3c583","#2d8a4e","#9dd6a8","#b8323c","#f0a3a8",
 "#7a5aa8","#c3b3dd","#4f8f8f","#a9cfcf","#8a6d3b","#d9c39a","#777","#bbb"];
const dcol={}; D.depts.forEach((d,i)=>dcol[d]=PAL[i%PAL.length]);
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const svg=$("#svg"), nsvg=$("#nsvg");
let VB={x:0,y:0,w:1,h:1}, HOME=null, SHOW_EXT=false, SHOW_UNK=false;
let SEL={county:null, inst:null, node:null, edge:null};
let VIS=[], EDG=[];              // 目前畫出來的節點索引與邊

// ── 狀態存取（重整後設定還在）
const KEY="netsci-map-v3";
function saveState(){try{localStorage.setItem(KEY,JSON.stringify({
  layer:$("#layer").value,ext:$("#ext").checked,unk:$("#unk").checked,peers:$("#peers").checked,names:$("#names").checked,
  y0:$("#y0").value,y1:$("#y1").value,scope:$("#scope").value,minp:$("#minp").value,
  view:$("#view").value,netlay:$("#netlay").value}))}catch(e){}}
function loadState(){try{const o=JSON.parse(localStorage.getItem(KEY)||"{}");
  for(const k in o){const el=$("#"+k); if(!el)continue;
    if(el.type==="checkbox")el.checked=o[k];else el.value=o[k]}}catch(e){}}
function writeHash(){const p=[];
  if(SEL.county)p.push("c="+encodeURIComponent(SEL.county));
  if(SEL.inst)p.push("i="+SEL.inst);
  if(SEL.node!=null)p.push("n="+SEL.node);
  history.replaceState(null,"","#"+p.join("&"))}
function applyHash(){const h=new URLSearchParams(location.hash.slice(1));
  const c=h.get("c"), i=h.get("i"), n=h.get("n");
  if(n!=null&&NODES[+n]) selectNode(+n,true);
  else if(i) selectInst(i,true);
  else if(c) selectCounty(c,true);}

// ── 視野
function computeHome(){
  // Symmetric about Taiwan, including offshore islands and the foreign anchors.
  let rx=2.0,ry=2.25;
  for(const g of GRP.values()){rx=Math.max(rx,Math.abs(g.x)+.7);ry=Math.max(ry,Math.abs(g.y)+.6)}
  HOME={x:-rx,y:-ry,w:rx*2,h:ry*2};
}
function fitTo(box,anim){const r=svg.getBoundingClientRect();
  if(!r.width||!r.height)return;
  const ar=r.width/r.height;
  let w=box.w,h=box.h; if(w/h<ar){w=h*ar}else{h=w/ar}
  const v={x:box.x+(box.w-w)/2,y:box.y+(box.h-h)/2,w,h};
  anim?animateTo(v):setVB(v)}
function home(anim){if($("#view").value==="net"){renderNet();return}computeHome();fitTo(HOME,anim)}
let animId=null;
function animateTo(t){cancelAnimationFrame(animId);const s={...VB},t0=performance.now();
  (function step(now){const k=Math.min(1,(now-t0)/380),e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;
    setVB({x:s.x+(t.x-s.x)*e,y:s.y+(t.y-s.y)*e,w:s.w+(t.w-s.w)*e,h:s.h+(t.h-s.h)*e});
    if(k<1)animId=requestAnimationFrame(step)})(t0)}
function setVB(v){ if(![v.x,v.y,v.w,v.h].every(Number.isFinite)||v.w<=0||v.h<=0)return;
  VB=v;svg.setAttribute("viewBox",`${v.x} ${v.y} ${v.w} ${v.h}`);rescale();relabel()}
function rescale(){const r=svg.getBoundingClientRect(); if(!r.width)return;
  const u=VB.w/r.width;
  $("#gnode").querySelectorAll("circle").forEach(c=>{
    const g=GRP.get(c.dataset.k);
    const px=g?g.rp:(c.classList.contains("ext")?3.0:3.8);
    c.setAttribute("r",px*u)});
  $("#gedge").querySelectorAll("line").forEach(l=>l.setAttribute("stroke-width",l.dataset.w*u));}
const P=i=>i<N?NODES[i]:BUB[i-N];

// ── 地圖底圖
$("#gmap").innerHTML=D.counties.map(c=>c.d.map(p=>
  `<path class="cty" data-c="${esc(c.n)}" d="${p}"></path>`).join("")).join("");
$("#gmap").addEventListener("click",e=>{const p=e.target.closest("path.cty");
  if(p)selectCounty(p.dataset.c)});

svg.addEventListener("wheel",e=>{e.preventDefault();
  const r=svg.getBoundingClientRect(),f=Math.exp(e.deltaY*0.0016);
  const mx=VB.x+(e.clientX-r.left)/r.width*VB.w,my=VB.y+(e.clientY-r.top)/r.height*VB.h;
  setVB({x:mx-(mx-VB.x)*f,y:my-(my-VB.y)*f,w:VB.w*f,h:VB.h*f})},{passive:false});
let drag=null;
svg.addEventListener("pointerdown",e=>{drag={x:e.clientX,y:e.clientY,vb:{...VB},moved:0};
  svg.classList.add("drag");if(e.target===svg)svg.setPointerCapture(e.pointerId)});
svg.addEventListener("pointermove",e=>{if(!drag)return;
  drag.moved+=Math.abs(e.movementX)+Math.abs(e.movementY);
  const r=svg.getBoundingClientRect();
  setVB({...drag.vb,x:drag.vb.x-(e.clientX-drag.x)/r.width*VB.w,
                    y:drag.vb.y-(e.clientY-drag.y)/r.height*VB.h})});
addEventListener("pointerup",()=>{drag=null;svg.classList.remove("drag")});
$("#reset").onclick=()=>home(true);
$("#back").onclick=()=>{ if(SEL.node!=null){SEL.node=null; SEL.inst?selectInst(SEL.inst):(SEL.county?selectCounty(SEL.county):overview())}
  else if(SEL.inst){SEL.inst=null; SEL.county?selectCounty(SEL.county):overview()}
  else {SEL.county=null; overview()} };

// ── 標籤（重疊就不畫）
function relabel(){
 const r=svg.getBoundingClientRect(),sc=r.width/VB.w;if(!r.width)return;
 const used=[],out=[];
 // Foreign labels occupy separate rails; their leaders end at the geographic anchor.
 for(const side of [-1,1]){
   const bs=[...GRP.values()].filter(g=>g.type==='B'&&(g.x<0?-1:1)===side).sort((a,b)=>a.y-b.y);
   const step=Math.min(34,(r.height-70)/Math.max(1,bs.length)),start=Math.max(35,(r.height-step*bs.length)/2);
   bs.forEach((g,i)=>{const xx=side<0?14:r.width-14,yy=start+i*step,x=VB.x+xx/sc,y=VB.y+yy/sc;
     out.push(`<line x1="${g.x}" y1="${g.y}" x2="${x}" y2="${y}" stroke="#8c9ba8" stroke-opacity=".55" stroke-width="${.65/sc}"/>`);
     out.push(`<text data-mapkey="${g.k}" class="bl rail" x="${x}" y="${y}" text-anchor="${side<0?'start':'end'}" style="font-size:${11/sc}px;stroke-width:${3/sc}px">${esc(g.label)} · ${g.n} 人${step<22&&g.km!=null?" · "+g.km+" km":""}</text><text class="bn" x="${x}" y="${y+12/sc}" text-anchor="${side<0?'start':'end'}" style="font-size:${(step<22?0:9)/sc}px;stroke-width:${3/sc}px">${g.km!=null?'約 '+g.km.toLocaleString()+' km':'位置示意，非海外座標'}</text>`);
   });
 }
 for(const g of [...GRP.values()].filter(g=>g.type!=='B').sort((a,b)=>b.n-a.n)){
   const label=(g.label||'').replace('國立',''),w=Math.max(50,label.length*11),px=(g.x-VB.x)*sc,py=(g.y-VB.y)*sc;
   let yy=py-g.rp-8,ok=false;
   for(const offset of [0,-18,18,-36,36,-54,54]){yy=py-g.rp-8+offset;if(!used.some(b=>Math.abs(px-b.x)<(w+b.w)/2&&Math.abs(yy-b.y)<15)){ok=true;break}}
   if(!ok)continue;used.push({x:px,y:yy,w});const y=VB.y+yy/sc;
   out.push(`<text data-mapkey="${g.k}" class="instlb rail" x="${g.x}" y="${y}" text-anchor="middle" style="font-size:${11/sc}px;stroke-width:${3/sc}px">${esc(label)}</text>`);
 }
 $("#glab").innerHTML=out.join('');
}

// ── 篩選與繪圖
function edgeOK(e){
  const [a,b,y,w,l,rr]=e, y0=+$("#y0").value, y1=+$("#y1").value, lay=+$("#layer").value;
  if(y<Math.min(y0,y1)||y>Math.max(y0,y1))return false;
  if(lay<2&&l!==lay)return false;
  if(!nodeOK(a)||!nodeOK(b))return false;
  if(!$("#peers").checked&&P(a).k&&P(b).k&&SEL.node==null)return false;
  if(SEL.node!=null){if(a!==SEL.node&&b!==SEL.node)return false}
  else if(SEL.inst){
    const aa=P(a).ic===SEL.inst,bb=P(b).ic===SEL.inst;
    if($("#scope").value==="within"?!(aa&&bb):!(aa||bb))return false;
  }else if(SEL.county&&P(a).cty!==SEL.county&&P(b).cty!==SEL.county)return false;
  const sc=$("#scope").value;
  if(sc!=="all"){const ia=P(a).ic||P(a).inst, ib=P(b).ic||P(b).inst;
    const same=(a<N&&b<N&&ia&&ia===ib);
    if(sc==="within"&&!same)return false; if(sc==="cross"&&same)return false}
  return true;
}
function nodeOK(i){const n=NODES[i];return n&&(!n.k||(SHOW_EXT&&(n.bi==null||!BUB[n.bi].unknown||SHOW_UNK)))}
function build(){
  SHOW_EXT=$("#ext").checked; SHOW_UNK=SHOW_EXT&&$("#unk").checked; $("#unk").disabled=!SHOW_EXT;
  const y0=+$("#y0").value,y1=+$("#y1").value;
  $("#ylab").textContent=y0===y1?y0:`${Math.min(y0,y1)}–${Math.max(y0,y1)}`;
  const minp=+$("#minp").value, agg=new Map();
  for(const e of D.edges){ if(!edgeOK(e))continue;
    const k=e[0]+"_"+e[1]+"_"+e[4], v=agg.get(k);
    if(v){v[2]+=e[3];v[5].add(e[6]);v[3]=v[5].size}else agg.set(k,[e[0],e[1],e[3],1,e[4],new Set([e[6]])])}
  EDG=[...agg.values()].filter(e=>e[3]>=minp).sort((p,q)=>p[2]-q[2]);
  const seen=new Set(); EDG.forEach(e=>{seen.add(e[0]);seen.add(e[1])});
  if(SEL.node!=null&&nodeOK(SEL.node))seen.add(SEL.node);
  if(SEL.inst&&SEL.node==null)NODES.forEach((n,i)=>{if(n.ic===SEL.inst&&!n.k&&nodeOK(i))seen.add(i)});
  VIS=[...seen];
  $("#stat").textContent=`作者 ${VIS.length}　合作關係 ${EDG.length}`;
  ($("#view").value==="net")?renderNet():renderMap();
  updateFocusInfo();saveState();
}
// 地圖彙總可見作者，機構與個人深入檢視使用獨立的網路畫布。
let GRP=new Map(), GEDG=[];
function keyOf(i){
  const n=NODES[i];
  if(i===SEL.node)return "P"+i;
  if(n.bi!=null)return "B"+n.bi;
  return n.ic?"I"+n.ic:"P"+i;
}
function buildGroups(){
  GRP=new Map();
  const add=(k,i)=>{ let g=GRP.get(k);
    if(!g){ const o=P(i); g={k,members:[],type:k[0],x:0,y:0,n:0};
      if(k[0]==="B"){const b=BUB[+k.slice(1)];g.x=b.x;g.y=b.y;g.label=b.label;g.unknown=b.unknown;g.km=b.km}
      else if(k[0]==="I"){const t=D.insts.find(t=>t.c===k.slice(1))||o;g.x=t.x;g.y=t.y;g.label=t.n;g.inst=t}
      else {const t=D.insts.find(t=>t.c===o.ic)||(o.bi!=null?BUB[o.bi]:o);g.x=t.x;g.y=t.y;g.label=o.name;g.node=i}
      GRP.set(k,g)}
    g.members.push(i); g.n++;}
  VIS.forEach(i=>add(keyOf(i),i));
  // 機構與海外圓依目前可見人數縮放，保留最小可點擊尺寸
  // 半徑用「螢幕像素」定義，rescale() 再換算成世界座標——
  // 這樣放大時圓不會跟著脹成一大片色塊（舊版的 .pt 也是這樣做的）。
  const mx=Math.max(1,...[...GRP.values()].filter(g=>g.type==="I").map(g=>g.n));
  const mb=Math.max(1,...[...GRP.values()].filter(g=>g.type==="B").map(g=>g.n));
  GRP.forEach(g=>{ if(g.type==="I")g.rp=Math.max(3,20*Math.sqrt(g.n/mx));
                   else if(g.type==="B")g.rp=Math.max(3,28*Math.sqrt(g.n/mb));
                   else g.rp=3.8});
  const agg=new Map();
  EDG.forEach(([a,b,w,c,l])=>{const ka=keyOf(a),kb=keyOf(b); if(ka===kb)return;
    const k=(ka<kb?ka+"|"+kb:kb+"|"+ka)+"|"+l, v=agg.get(k);
    if(v){v.w+=w;v.c+=c;v.pairs.push([a,b])}else agg.set(k,{a:ka<kb?ka:kb,b:ka<kb?kb:ka,w,c,l,pairs:[[a,b]]})});
  GEDG=[...agg.values()].sort((p,q)=>p.w-q.w);
}
function renderMap(){
  $("#netbox").hidden=true; svg.style.display=""; $("#netctl").hidden=true;
  buildGroups();
  $("#gmap").querySelectorAll("path.cty").forEach(p=>{
    p.classList.toggle("on",SEL.county&&p.dataset.c===SEL.county);
    p.classList.toggle("dim",!!SEL.county&&p.dataset.c!==SEL.county)});
  $("#gedge").innerHTML=GEDG.map((e,i)=>{const p=GRP.get(e.a),q=GRP.get(e.b);
    if(!p||!q)return "";
    const col=e.l?"#d1583a":"#3b6ea5",op=e.l?.5:.24,lw=Math.min(3.5,.4+.5*Math.sqrt(e.c));
    return `<line class="edge" data-e="${i}" data-w="${lw}" x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" stroke="${col}" stroke-opacity="${op}"/>`}).join("");
  const gs=[...GRP.values()].sort((a,b)=>(b.rp||0)-(a.rp||0));
  $("#gnode").innerHTML=gs.map(g=>{
    if(g.type==="B")return `<circle class="bub${g.unknown?" unk":""}" data-k="${g.k}" cx="${g.x}" cy="${g.y}"><title>${esc(g.label)}：${g.n} 位共同作者</title></circle>`;
    if(g.type==="I"){const dim=SEL.county&&g.inst&&g.inst.cty!==SEL.county;
      return `<circle class="inst${SEL.inst===g.k.slice(1)?" sel":""}${dim?" dimc":""}" data-k="${g.k}" cx="${g.x}" cy="${g.y}"><title>${esc(g.label)}：${g.n} 位</title></circle>`}
    if(false)return `<circle data-k="${g.k}" cx="${g.x}" cy="${g.y}" r="${g.r}"><title>${esc(g.label)}：${g.n} 位</title></circle>`;
    const n=NODES[g.node];
    return `<circle class="nd${n.k?" ext":""}${SEL.node===g.node?" sel":""}" data-k="${g.k}" cx="${g.x}" cy="${g.y}"${n.k?"":` fill="${dcol[n.dept]||"#888"}"`}><title>${esc(n.name)}${n.k?"（非名冊）":""}　${esc(n.inst)}${n.dept?" · "+esc(n.dept):""}</title></circle>`}).join("");
  rescale(); relabel();
  $("#gnode").onpointerover=e=>{const c=e.target.closest('[data-k]');if(!c)return;const k=c.dataset.k;$("#gedge").querySelectorAll('line').forEach(l=>{const e=GEDG[+l.dataset.e];l.style.opacity=e.a===k||e.b===k?1:.035;if(e.a===k||e.b===k)l.setAttribute('stroke-opacity','.85')})};
  $("#gnode").onpointerout=()=>{$("#gedge").querySelectorAll('line').forEach(l=>{l.style.opacity=1;l.setAttribute('stroke-opacity',GEDG[+l.dataset.e].l?'.5':'.24')})};
}
$("#glab").addEventListener("click",e=>{const t=e.target.closest("[data-mapkey]");if(t){const k=t.dataset.mapkey;if(k[0]==="B")showBubble(N+ +k.slice(1));else if(k[0]==="I")selectInst(k.slice(1));else selectNode(+k.slice(1))}});
$("#gnode").addEventListener("click",e=>{const c=e.target.closest("circle"); if(!c)return;
  const k=c.dataset.k;
  if(k[0]==="I")selectInst(k.slice(1));
  else if(k[0]==="B")showBubble(N+ +k.slice(1));
  else selectNode(+k.slice(1))});
$("#gedge").addEventListener("click",e=>{const l=e.target.closest("line"); if(l)showMapEdge(+l.dataset.e)});

// ── Network layouts use a separate SVG, never a geographic background.
let netVB=null;
function renderNet(){
 cancelAnimationFrame(animId);
 $("#netbox").hidden=false;svg.style.display="none";$("#netctl").hidden=false;
 const grouped=SEL.node==null&&!SEL.inst;
 let keys,links,objects;
 if(grouped){buildGroups();keys=[...GRP.keys()];objects=GRP;
   links=GEDG.map((e,i)=>({a:e.a,b:e.b,w:e.w,c:e.c,l:e.l,index:i}));
 }else{keys=VIS.slice();objects=new Map(keys.map(i=>[i,{label:NODES[i].name,inst:NODES[i].inst,dept:NODES[i].dept,k:NODES[i].k,node:i,n:1}]));
   links=EDG.map((e,i)=>({a:e[0],b:e[1],w:e[2],c:e[3],l:e[4],index:i}));}
 const degree=new Map(keys.map(k=>[k,0]));links.forEach(e=>{degree.set(e.a,degree.get(e.a)+1);degree.set(e.b,degree.get(e.b)+1)});
 const internal=SEL.inst&&SEL.node==null&&$("#scope").value==='within';
 const category=k=>internal?(objects.get(k).dept||'非名冊／系所未提供'):(objects.get(k).inst?.n||objects.get(k).inst||objects.get(k).label);
 const names=[...new Set(keys.map(category))].sort();
 const color=k=>PAL[names.indexOf(category(k))%PAL.length];
 keys.sort((a,b)=>String(objects.get(a).inst||"").localeCompare(String(objects.get(b).inst||""))||String(a).localeCompare(String(b)));
 const pos=new Map(),count=keys.length,rad=Math.max(180,Math.sqrt(count)*40);
 keys.forEach((k,i)=>{const t=2*Math.PI*i/Math.max(1,count);pos.set(k,[Math.cos(t)*rad,Math.sin(t)*rad])});
 const focal=SEL.node;
 if(focal!=null&&pos.has(focal))pos.set(focal,[0,0]);
 if($("#netlay").value==="force"){
   for(let it=0;it<180;it++){
     const f=new Map(keys.map(k=>[k,[0,0]])),cool=1-it/210;
     // Spatial buckets keep repulsion bounded for large institution ego networks.
     const cells=new Map(),cell=110;
     for(const k of keys){const p=pos.get(k),tag=Math.floor(p[0]/cell)+","+Math.floor(p[1]/cell);if(!cells.has(tag))cells.set(tag,[]);cells.get(tag).push(k)}
     for(const k of keys){const p=pos.get(k),v=f.get(k),cx=Math.floor(p[0]/cell),cy=Math.floor(p[1]/cell);
       for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(const j of cells.get((cx+dx)+","+(cy+dy))||[]){
         if(j===k)continue;const q=pos.get(j);let x=p[0]-q[0],y=p[1]-q[1],d=Math.hypot(x,y);
         if(d<.01){x=1;y=.5;d=1}const rep=Math.min(12,1700/(d*d));v[0]+=x/d*rep;v[1]+=y/d*rep;
       }
       v[0]-=p[0]*.003;v[1]-=p[1]*.003;
     }
     for(const e of links){const p=pos.get(e.a),q=pos.get(e.b),x=q[0]-p[0],y=q[1]-p[1],d=Math.hypot(x,y)||1;
       const pull=(d-(focal!=null?150:100))*.018;f.get(e.a)[0]+=x/d*pull;f.get(e.a)[1]+=y/d*pull;f.get(e.b)[0]-=x/d*pull;f.get(e.b)[1]-=y/d*pull;}
     for(const k of keys){if(k===focal){pos.set(k,[0,0]);continue}const p=pos.get(k),v=f.get(k);p[0]+=Math.max(-12,Math.min(12,v[0]))*cool;p[1]+=Math.max(-12,Math.min(12,v[1]))*cool}
   }
 }
 // Resolve remaining node collisions without using geography as a layout constraint.
 const radius=k=>k===focal?12:grouped?Math.min(22,5+Math.sqrt(objects.get(k).n)*2):Math.min(10,4+Math.sqrt(degree.get(k)||0));
 for(let t=0;t<20;t++)for(let i=0;i<count;i++)for(let j=i+1;j<count;j++){
   const a=keys[i],b=keys[j],p=pos.get(a),q=pos.get(b),dx=q[0]-p[0],dy=q[1]-p[1],d=Math.hypot(dx,dy)||.01,min=radius(a)+radius(b)+12;
   if(d<min){const x=(dx||.01)/d*(min-d)*.5,y=dy/d*(min-d)*.5;if(a!==focal){p[0]-=x;p[1]-=y}if(b!==focal){q[0]+=x;q[1]+=y}}
 }
 const xs=keys.map(k=>pos.get(k)[0]),ys=keys.map(k=>pos.get(k)[1]);
 const x=count?Math.min(...xs)-110:-300,y=count?Math.min(...ys)-65:-200;
 netVB={x,y,w:count?Math.max(...xs)-x+110:600,h:count?Math.max(...ys)-y+80:400};setNetVB(netVB);
 nsvg.innerHTML=links.map((e,i)=>{const p=pos.get(e.a),q=pos.get(e.b);return `<line data-link="${i}" x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}" stroke="${e.l?'#d1583a':'#527fa8'}" stroke-opacity=".55" stroke-width="${Math.min(5,.8+Math.sqrt(e.c))}" vector-effect="non-scaling-stroke" class="edge"><title>${esc(objects.get(e.a).label)} — ${esc(objects.get(e.b).label)}：${e.c} 筆</title></line>`}).join("")+
 keys.map((k,j)=>{const p=pos.get(k),o=objects.get(k),rr=radius(k),full=o.label+(grouped?'':` · ${o.inst||'機構不明'}${o.dept?' · '+o.dept:''}`);
 return `<g data-key="${j}" class="netperson"><circle class="nd${!grouped&&o.k?' ext':''}${k===focal?' sel':''}" style="fill:${color(k)};fill-opacity:${!grouped&&o.k?.25:1}" cx="${p[0]}" cy="${p[1]}" r="${rr}" fill="${color(k)}"><title>${esc(full)} · ${degree.get(k)} 條關係</title></circle><text x="${p[0]+rr+4}" y="${p[1]+4}" style="font-size:12px;paint-order:stroke;stroke:#fcfcfd;stroke-width:3px;fill:#263c51" ${!$("#names").checked&&count>65&&k!==focal&&(grouped?false:o.k||degree.get(k)<2)?'class="hoverlabel"':''}>${esc(o.label)}</text></g>`}).join("");
 $("#netnote").textContent=(grouped?'機構／國家彙總':SEL.node!=null?'個人與直接合作對象':'機構成員與合作對象')+` · ${count} 節點 / ${links.length} 關係 · 顏色＝${internal?"系所":"機構"}，紅框＝非名冊 · 懸停顯示姓名／凸顯連線 · 滾輪縮放、空白處拖曳`;
 nsvg.onclick=e=>{if(netMoved)return;const nd=e.target.closest('[data-key]'),ln=e.target.closest('[data-link]');
 if(nd){const k=keys[+nd.dataset.key];if(grouped){if(k[0]==='I')selectInst(k.slice(1));else if(k[0]==='B')showBubble(N+ +k.slice(1));else selectNode(+k.slice(1))}else selectNode(k)}
 else if(ln){const link=links[+ln.dataset.link];grouped?showMapEdge(link.index):showEdge(link.index)}};
 nsvg.onpointerover=e=>{const nd=e.target.closest('[data-key]');if(!nd)return;const k=keys[+nd.dataset.key],adj=new Set([k]);links.forEach(l=>{if(l.a===k)adj.add(l.b);if(l.b===k)adj.add(l.a)});
 nsvg.querySelectorAll('[data-key]').forEach(g=>g.style.opacity=adj.has(keys[+g.dataset.key])?1:.15);
 nsvg.querySelectorAll('[data-link]').forEach(l=>{const q=links[+l.dataset.link];l.style.opacity=q.a===k||q.b===k?1:.08})};
 nsvg.onpointerout=e=>{if(e.target.closest('[data-key]'))nsvg.querySelectorAll('[data-key],[data-link]').forEach(g=>g.style.opacity=1)};
}
function setNetVB(v){netVB=v;nsvg.setAttribute('viewBox',`${v.x} ${v.y} ${v.w} ${v.h}`)}
let netDrag=null,netMoved=false;
nsvg.addEventListener('wheel',e=>{e.preventDefault();if(!netVB)return;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(nsvg.getScreenCTM().inverse()),f=Math.exp(Math.max(-1,Math.min(1,e.deltaY*.0015)));setNetVB({x:p.x-(p.x-netVB.x)*f,y:p.y-(p.y-netVB.y)*f,w:netVB.w*f,h:netVB.h*f})},{passive:false});
nsvg.addEventListener('pointerdown',e=>{netMoved=false;if(e.target!==nsvg)return;netDrag={x:e.clientX,y:e.clientY,v:{...netVB}};nsvg.setPointerCapture(e.pointerId)});
nsvg.addEventListener('pointermove',e=>{if(!netDrag)return;const m=nsvg.getScreenCTM(),dx=(e.clientX-netDrag.x)/m.a,dy=(e.clientY-netDrag.y)/m.d;netMoved=Math.abs(dx)+Math.abs(dy)>3;setNetVB({...netDrag.v,x:netDrag.v.x-dx,y:netDrag.v.y-dy})});
nsvg.addEventListener('pointerup',()=>netDrag=null);

// ── 側欄
function crumb(){const p=['<b>全台</b>'];
  if(SEL.county)p.push(esc(SEL.county));
  if(SEL.inst)p.push(esc((D.insts.find(i=>i.c===SEL.inst)||{}).n||""));
  if(SEL.node!=null)p.push(esc(NODES[SEL.node].name));
  $("#crumb").innerHTML=p.join(" › ");
  $("#back").hidden=!(SEL.county||SEL.inst||SEL.node!=null);
  writeHash()}
function rows(o){return o.filter(r=>r[1]!==""&&r[1]!=null)
  .map(r=>`<div class="row"><span class="k">${r[0]}</span><b>${esc(r[1])}</b></div>`).join("")}
function chart(years){const y0=D.years[0],y1=D.years[1],n=y1-y0+1;
  const c=new Array(n).fill(0); years.forEach(y=>{if(y>=y0&&y<=y1)c[y-y0]++});
  const m=Math.max(1,...c), W=300,H=52,bw=W/n;
  return `<svg id="chart" viewBox="0 0 ${W} ${H+12}" style="width:100%;height:64px">`+
    c.map((v,i)=>`<rect x="${i*bw+1}" y="${H-v/m*H}" width="${bw-2}" height="${v/m*H}"><title>${y0+i}：${v}</title></rect>`).join("")+
    `<text x="0" y="${H+10}">${y0}</text><text x="${W}" y="${H+10}" text-anchor="end">${y1}</text></svg>`}
function overview(){$("#view").value="map";$("#scope").value="all";SEL={county:null,inst:null,node:null,edge:null};crumb();
  const byC={}; D.insts.forEach(i=>{(byC[i.cty]=byC[i.cty]||[]).push(i)});
  $("#details").innerHTML=`<h2>全台</h2>
    <div class="k">名冊 520 位教師中，這 12 年有發表或計畫的 ${NODES.filter(n=>n.k===0).length} 位畫在機構的真實座標上。點縣市、機構或任何一個節點往下看。</div>
    <h3>縣市（${Object.keys(byC).length}）</h3><ul class="lst">`+
    Object.entries(byC).sort((a,b)=>b[1].reduce((s,x)=>s+x.na,0)-a[1].reduce((s,x)=>s+x.na,0))
     .map(([c,v])=>`<li data-c="${esc(c)}">${esc(c)}<span class="m"> · ${v.length} 個機構 · ${v.reduce((s,x)=>s+x.na,0)} 位教師</span></li>`).join("")+
    `</ul>`;
  build(); home(true);}
function selectCounty(c,quiet){$("#view").value="map";$("#scope").value="all";SEL={county:c,inst:null,node:null,edge:null};crumb();
  const list=D.insts.filter(i=>i.cty===c).sort((a,b)=>b.na-a.na);
  $("#details").innerHTML=`<span class="back" data-up="1">← 回全台</span><h2>${esc(c)}</h2>
    <div class="k">${list.length} 個機構 · ${list.reduce((s,x)=>s+x.na,0)} 位名冊教師</div>
    <h3>機構</h3><ul class="lst">`+list.map(i=>
      `<li data-i="${i.c}">${esc(i.n)}<span class="m"> · ${i.na} 位 · 論文 ${i.np} · 計畫 ${i.nj}</span></li>`).join("")+`</ul>`;
  build(); if(!quiet){const pts=D.insts.filter(i=>i.cty===c);
    if(pts.length){const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y);
      fitTo({x:Math.min(...xs)-.35,y:Math.min(...ys)-.35,w:Math.max(...xs)-Math.min(...xs)+.7,h:Math.max(...ys)-Math.min(...ys)+.7},true)}}}
function selectInst(code,quiet){const inst=D.insts.find(i=>i.c===code); if(!inst)return;
  $("#view").value="net";$("#scope").value="within";
  SEL={county:inst.cty,inst:code,node:null,edge:null};crumb();
  const mem=NODES.map((n,i)=>[n,i]).filter(([n])=>n.ic===code);
  const ros=mem.filter(([n])=>n.k===0), ex=mem.filter(([n])=>n.k===1);
  $("#details").innerHTML=`<span class="back" data-up="1">← 回 ${esc(inst.cty)}</span><h2>${esc(inst.n)}</h2>`+
    rows([["縣市",inst.cty],["名冊教師（active）",inst.na],["名冊全部",inst.nr],
          ["2015–2026 論文",inst.np],["2015–2026 計畫",inst.nj],["非名冊共同作者",ex.length]])+
    `<h3>名冊教師（${ros.length}）</h3><ul class="lst">`+ros.sort((a,b)=>(+b[0].np||0)-(+a[0].np||0))
      .map(([n,i])=>`<li data-n="${i}">${esc(n.name)}<span class="m"> · ${esc(n.dept)} · 論文 ${n.np}</span></li>`).join("")+`</ul>`+
    (ex.length?`<h3>非名冊共同作者（${ex.length}）<span class="pill ext">不是名冊經濟學家</span></h3><ul class="lst">`+
      ex.slice(0,60).map(([n,i])=>`<li data-n="${i}">${esc(n.name)}</li>`).join("")+`</ul>`:"");
  build();}
function linkRow(label,url,note){ if(!url)return "";
  const short=url.replace(/^https?:\/\//,"").replace(/\/$/,"");
  return `<div class="row"><span class="k">${label}</span><b><a href="${esc(url)}" target="_blank" rel="noopener">${esc(short.length>34?short.slice(0,34)+"…":short)}</a>${note?` <span class="warn">${note}</span>`:""}</b></div>`}
function selectNode(i,quiet){const n=NODES[i];if(!n)return;
  $("#view").value="net";$("#scope").value="all";$("#ext").checked=true;
  if(n.bi!=null&&BUB[n.bi].unknown)$("#unk").checked=true;
  SEL={county:n.cty||null,inst:n.ic||null,node:i,edge:null};crumb();
  const ps=n.pi.map(k=>D.papers[k]).sort((a,b)=>b[1]-a[1]);
  const js=(n.ji||[]).map(k=>D.projects[k]).sort((a,b)=>b[1]-a[1]);
  $("#details").innerHTML=`<span class="back" data-up="1">← 回 ${esc((D.insts.find(x=>x.c===n.ic)||{}).n||"上一層")}</span>
    <h2>${esc(n.name)} ${n.k?'<span class="pill ext">非名冊</span>':'<span class="pill">名冊教師</span>'}</h2>`+
    rows([["機構",n.inst],["系所",n.dept],["2015–2026 論文",n.np],["2015–2026 計畫",n.nj],
          ["OpenAlex 總發表",n.oapub],["OpenAlex 總被引",n.cite]])+
    (n.em||n.or||n.pf||n.pw||n.ns||n.cv||n.oa?`<h3>聯絡與連結</h3>`+
      (n.em?`<div class="row"><span class="k">Email</span><b><a href="mailto:${esc(n.em)}">${esc(n.em)}</a></b></div>`:"")+
      (n.or?linkRow("ORCID",n.or.startsWith("http")?n.or:"https://orcid.org/"+n.or):"")+
      linkRow("系所頁",n.pf,n.pfs>1?`⚠ 這個網址被 ${n.pfs} 位教師共用，多半是系所師資列表、不是個人頁`:"")+
      linkRow("個人網站",n.pw)+
      linkRow("NSTC 學術人才網",n.ns)+
      linkRow("CV",n.cv)+
      linkRow("OpenAlex",n.oa,n.oaconf&&n.oaconf!=="high"?`比對可信度 ${n.oaconf}`:"")
    :"")+
    `<h3>逐年發表（${ps.length} 篇）</h3>`+chart(ps.map(p=>p[1]))+
    `<ul class="pl">`+ps.slice(0,80).map(p=>`<li>${esc(p[0])}<div class="m">${p[1]} · ${esc(p[2])}${p[3]?" · "+esc(p[3]):""}</div></li>`).join("")+`</ul>`+
    (js.length?`<h3>計畫（${js.length}）</h3><ul class="pl">`+js.slice(0,60)
      .map(p=>`<li>${esc(p[0])}<div class="m">${p[1]} · ${esc(p[2])}</div></li>`).join("")+`</ul>`:"");
  build();}
function showBubble(i){const b=BUB[i-N];
  $("#details").innerHTML=`<span class="back" data-up="0">← 回全台</span>
    <h2>${esc(b.label)} <span class="pill">${b.n} 位共同作者</span></h2>
    <div class="k">國家中心的大圓方位，距離採單調壓縮；國家位置不是個別機構的精確地址。</div>
    <h3>距離與位置</h3>`+rows([["相對台灣約略距離",b.km!=null?b.km.toLocaleString()+" km":"無可用座標"],["定位依據",b.km!=null?"國家中心／大圓方位":"獨立示意群組"]])+`<h3>最常出現的機構（完整資料）</h3>`+rows(b.top.map(t=>[t[0],t[1]+" 人"]))+`<h3>目前可見作者</h3><ul class="lst">`+b.members.filter(i=>VIS.includes(i)).map(i=>`<li data-n="${i}">${esc(NODES[i].name)}<div class="m">${esc(NODES[i].inst)}</div></li>`).join("")+`</ul>`}
function showMapEdge(k){const e=GEDG[k];if(!e)return;const a=GRP.get(e.a),b=GRP.get(e.b);
 const pairs=e.pairs.map(([a,b])=>EDG.findIndex(x=>x[0]===a&&x[1]===b&&x[4]===e.l)).filter(i=>i>=0);
 const records=new Set(pairs.flatMap(i=>[...EDG[i][5]]));
 $("#details").innerHTML=`<h2>${esc(a.label)} — ${esc(b.label)}</h2>`+rows([["網路層",e.l?"共同計畫":"共著"],["不同合作成果",records.size],["作者配對合作筆數",e.c],["作者配對",pairs.length]])+
 `<ul class="lst">`+pairs.map(i=>`<li data-edge="${i}">${esc(P(EDG[i][0]).name)} — ${esc(P(EDG[i][1]).name)}<div class="m">${EDG[i][3]} 筆 · 點擊看合作成果</div></li>`).join("")+`</ul>`;
}
function showEdge(k){const e=EDG[k];if(!e)return;const [a,b,w,c,l]=e,pa=P(a),pb=P(b);
 const field=l?'ji':'pi',data=l?D.projects:D.papers,A=new Set(pa[field]||[]);
 const y0=Math.min(+$("#y0").value,+$("#y1").value),y1=Math.max(+$("#y0").value,+$("#y1").value);
 const shared=(pb[field]||[]).filter(i=>A.has(i)).map(i=>data[i]).filter(p=>p[1]>=y0&&p[1]<=y1).sort((a,b)=>b[1]-a[1]);
 $("#details").innerHTML=`<h2>${esc(pa.name)} — ${esc(pb.name)}</h2>`+rows([["網路層",l?"共同計畫":"共著"],["合作成果筆數",c],["權重合計",w.toFixed(3)]])+`<h3>目前年份內的${l?'共同計畫':'共著論文'}（${shared.length}）</h3><ul class="pl">`+shared.map(p=>`<li>${esc(p[0])}<div class="m">${p[1]} · ${esc(p[2])}</div></li>`).join("")+`</ul>`;
}
$("#side").addEventListener("click",e=>{const li=e.target.closest("li,.back"); if(!li)return;
  if(li.classList.contains("back")){$("#back").click();return}
  if(li.dataset.edge!=null)showEdge(+li.dataset.edge);
  else if(li.dataset.c)selectCounty(li.dataset.c);
  else if(li.dataset.i)selectInst(li.dataset.i);
  else if(li.dataset.n)selectNode(+li.dataset.n)});
function legendHTML(){if($("#view").value==='net')return `<div class="note">藍線＝共著，橘線＝計畫；線寬依合作成果筆數。個人節點越大，合作關係越多；彙總節點依作者人數縮放。校內顏色＝系所，跨機構顏色＝機構；紅框＝非名冊作者。單點代表目前條件下無合作連線。懸停顯示姓名並凸顯直接合作，可勾「所有姓名」。<br>位置是網路排列，沒有地理意義。預設只顯示涉及名冊作者的合作，可勾「含非名冊彼此合作」展開其他連線。</div>`;return `<div class="note"><b>閱讀方式</b><br>地圖：節點面積隨目前篩選下的作者人數縮放（小點有最小可點擊尺寸）；藍線＝共著，橘線＝計畫，線寬＝作者配對合作筆數。點機構看校內網路，點作者看直接合作對象。<br>台灣維持地理座標與中央位置；海外是國家中心的大圓方位，半徑依距離單調壓縮，並非同一地圖比例尺。兩側標籤以引線指回位置，顯示約略公里數；懸停節點凸顯合作連線。臺灣其他機構與未知位置為獨立示意群組。</div>`}
function updateFocusInfo(){
 const title=SEL.node!=null?"個人合作網路":SEL.inst?"機構合作網路":SEL.county?"縣市合作":"全台合作";
 const partners=SEL.node!=null?[...new Set(EDG.flatMap(e=>e.slice(0,2)).filter(i=>i!==SEL.node))]:[];
 $("#focusinfo").innerHTML=`<h2>${title}</h2><div class="k">${VIS.length} 位作者 · ${EDG.length} 組合作關係 · ${$("#ylab").textContent}</div>`+
 (SEL.node!=null?`<button data-scope="cross">只看此人的跨機構合作</button> <button data-scope="all">所有直接合作</button>`:SEL.inst?`<button data-scope="within">校內合作</button> <button data-scope="cross">跨機構合作</button> <button data-scope="all">全部合作</button>`:"")+
 (!EDG.length?`<p class="warn">目前條件沒有合作連線。可調整年份、網路層、非名冊作者或最低合作筆數；顯示的單點代表在此條件下沒有連線。</p>`:"")+
 (partners.length?`<details open><summary>合作對象（${partners.length}）</summary><ul class="lst" style="max-height:240px;overflow:auto">`+partners.sort((a,b)=>NODES[a].inst.localeCompare(NODES[b].inst)).map(i=>`<li data-n="${i}">${esc(NODES[i].name)}<div class="m">${esc(NODES[i].inst||"機構不明")} · ${esc(NODES[i].country||"國別不明")}</div></li>`).join("")+`</ul></details>`:"")+legendHTML()+`<hr style="border:0;border-top:1px solid #e3e5e8;margin:18px 0">`;
}
$("#focusinfo").addEventListener("click",e=>{const b=e.target.closest("[data-scope]");if(b){$("#scope").value=b.dataset.scope;build()}});
$("#people").innerHTML=NODES.map((n,i)=>`<option value="${esc(n.name+' · '+n.inst+' ['+i+']')}"></option>`).join("");
$("#search").onchange=()=>{const q=$("#search").value,m=q.match(/\[(\d+)\]$/);const i=m?+m[1]:NODES.findIndex(n=>n.name===q);if(i>=0){selectNode(i);$("#search").value=""}};
$("#global").onclick=overview;

["layer","y0","y1","scope","minp","peers","names"].forEach(id=>$("#"+id).addEventListener("input",build));
["ext","unk"].forEach(id=>$("#"+id).addEventListener("input",()=>{build();home(true)}));
$("#view").addEventListener("input",()=>{build();home()});
$("#netlay").addEventListener("input",build);
addEventListener("resize",()=>{if($("#view").value==="map")home();else build()});
addEventListener("hashchange",applyHash);
const initialHash=location.hash;loadState(); overview();if(initialHash){history.replaceState(null,"",initialHash);applyHash()}
</script></body></html>
"""


def stage9_html(outfile=None):
    """產生單一檔案的互動式地圖網路圖。"""
    data = build_html_payload()
    html = (HTML_TEMPLATE
            .replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c'))
            .replace('__Y0__', str(YEAR_MIN)).replace('__Y1__', str(YEAR_MAX)))
    outdir = os.path.join(FINAL, 'figures')
    os.makedirs(outdir, exist_ok=True)
    out = outfile or os.path.join(outdir, 'map_explorer.html')
    if not os.path.isabs(out):
        out = os.path.join(outdir, out)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  節點 {len(data["nodes"])}、泡泡 {len(data["bubbles"])}、'
          f'邊 {len(data["edges"])}　{os.path.getsize(out) // 1024} KB'
          f' → {os.path.relpath(out, ROOT)}')
    return out


# ═══════════════════════════════════════════════════════════════
# 進入點
# ═══════════════════════════════════════════════════════════════
STAGES = [
    (1, 'fix_author_lists', lambda a: stage1_fix_author_lists()),
    (2, 'build',            lambda a: stage2_build()),
    (3, 'enrich',           lambda a: stage3_enrich(fetch=not a.offline,
                                                    search_teachers=not a.offline)),
    (4, 'journal_pdf',      lambda a: stage4_journal()),
    (5, 'crossref',         lambda a: stage5_crossref()),
    (6, 'external_affil',   lambda a: stage6_external()),
    (7, 'review_sheets',    lambda a: stage7_sheets()),
]


def main():
    global OFFLINE
    ap = argparse.ArgumentParser(
        description='final_plan 全流程；加 --map 則改成畫地圖網路圖')
    ap.add_argument('--stage', nargs='*', type=int,
                    help='只跑指定階段（預設 1 2 3 4 6 7；第 5 階段要自己指定）')
    g = ap.add_argument_group('畫地圖（--map）')
    g.add_argument('--map', action='store_true', help='畫地圖網路圖，不跑其他階段')
    g.add_argument('--layer', choices=['pub', 'proj', 'both'], default='pub',
                   help='要看哪一層：pub 共著（預設）／proj 共同計畫／both 兩層疊')
    g.add_argument('--external', action='store_true',
                   help='把不在名冊的共同作者也畫出來')
    g.add_argument('--unknown-affil', action='store_true',
                   help='連機構都查不到的共同作者也畫（要搭配 --external）')
    g.add_argument('--year-from', type=int, default=YEAR_MIN)
    g.add_argument('--year-to', type=int, default=YEAR_MAX)
    g.add_argument('--min-weight', type=float, default=0.0,
                   help='邊的權重下限，用來把圖畫疏一點')
    g.add_argument('--out', help='輸出檔名（預設放在 final_plan/figures/）')
    g.add_argument('--all', action='store_true',
                   help='把常用的幾種組合一次全畫出來')
    g.add_argument('--html', action='store_true',
                   help='產生單一檔案的互動式地圖（figures/map_explorer.html）')
    ap.add_argument('--with-crossref', action='store_true',
                    help='把第 5 階段（Crossref）也納入。它要跑約 30 分鐘、收穫很少')
    ap.add_argument('--offline', action='store_true',
                    help='完全不連網，只用 cache/ 裡已經抓好的東西')
    a = ap.parse_args()
    OFFLINE = a.offline

    if a.html:
        print('產生互動式地圖 …', flush=True)
        stage9_html(a.out)
        return

    if a.map or a.all:
        combos = ([('pub', False, False), ('pub', True, False), ('pub', True, True),
                   ('proj', False, False), ('both', True, False)] if a.all else
                  [(a.layer, a.external, a.unknown_affil)])
        for lay, ext, unk in combos:
            print(f'\n畫圖：layer={lay} external={ext} unknown={unk}', flush=True)
            stage8_map(layer=lay, show_external=ext, show_unknown=unk,
                       year_from=a.year_from, year_to=a.year_to,
                       min_weight=a.min_weight, outfile=a.out if not a.all else None)
        return

    want = set(a.stage) if a.stage else ({1, 2, 3, 4, 6, 7} | ({5} if a.with_crossref else set()))
    for n, name, fn in STAGES:
        if n not in want:
            continue
        print(f'\n{"═" * 62}\n階段 {n} — {name}\n{"═" * 62}', flush=True)
        fn(a)
    print('\n全部完成。')


if __name__ == '__main__':
    main()
