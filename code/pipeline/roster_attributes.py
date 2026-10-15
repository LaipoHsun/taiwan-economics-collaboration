"""名冊教師的補充屬性：PhD 學歷、JEL 研究領域。

    python3 code/pipeline/roster_attributes.py

讀：
  input/professor_demo/authors_master.csv          名冊教師（node_type == roster）
  input/project/projects_all.csv                   國科會計畫的學門代碼
  前置data處理/faculty_identity/cache/              之前爬過的系所頁／個人網站（不連網）
  decisions/roster_phd_manual.csv  人工修正（有就覆蓋自動結果）
  前置data處理/faculty_identity/cache/ 裡的國科會「基本資料」頁（initBasic）有性別欄
  decisions/roster_gender_manual.csv 性別標註表單匯出的人工結果（有就優先）
寫：
  input/professor_demo/roster_gender.csv
  input/professor_demo/roster_phd.csv
  input/professor_demo/roster_field_jel.csv
  output/manual_review/08_PhD學歷查核.xlsx         （已存在就不覆蓋）

PhD 是從網頁文字抽的，規則：每一頁只取「這個人的名字之後第一行同時有『博士／Ph.D.』和校名」的那一行。
系所列表頁上一頁有很多人，名字之後往下抓太遠就會抓到下一個人，所以列表頁只接受距離名字 400 字以內的，
個人頁 1500 字以內。國科會研究人才頁的「主要學歷」分頁幾乎都是［不公開］，不能用。
"""
import collections, csv, glob, html, json, os, re, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
FINAL = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(FINAL)
INPUT = os.path.join(FINAL, 'input')
DEC_DIR = os.path.join(FINAL, 'decisions')
REVIEW_DIR = os.path.join(FINAL, 'output', 'manual_review')
PAGE_CACHE = os.path.join(ROOT, '前置data處理', 'faculty_identity', 'cache')


def rd(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def wr(path, rows, fields):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f'  {len(rows)} 列 → {os.path.relpath(path, FINAL)}')


# ═══════════════════════════════════════════════════════════════
# PhD 學歷
# ═══════════════════════════════════════════════════════════════
SCHOOL_WORD = re.compile(r'(大學|大学|學院|University|College|Institute|School|Universit[äéà]|Université|研究所|Polytechnic|LSE|MIT|UCLA)', re.I)
PHD_WORD = re.compile(r'(博\s*士|Ph\.?\s?D|Doctor of Philosophy|D\.?Phil|Doctorate)', re.I)
NOT_A_DEGREE = re.compile(r'博士(班|生|後|學位學程|候選)|博士級|指導')
GARBAGE = re.compile(r'公告|宗旨|具備國內外|I am an economist')
MAX_DIST = {'profile': 1500, 'personal': 1500, 'host_title': 1500, 'list': 400}
SOURCE_RANK = {'profile': 0, 'personal': 1, 'host_title': 2, 'list': 3}

# 校名 → (英文正式名, 國別)；越具體的放越前面（密西根州立要排在密西根前面）
SCHOOLS=[
 (r'威斯康辛.*麥迪遜|Wisconsin[- ]Madison|UW-Madison|University of Wisconsin|威斯康辛','University of Wisconsin–Madison','US'),
 (r'密西根州立|Michigan State','Michigan State University','US'),
 (r'密西根大學|University of Michigan','University of Michigan','US'),
 (r'聖路易.*華盛頓|華盛頓大學.*聖路易|Washington University in St\.? Louis','Washington University in St. Louis','US'),
 (r'西雅圖華盛頓|University of Washington','University of Washington','US'),
 (r'賓州州立|Penn(sylvania)? State','Pennsylvania State University','US'),
 (r'賓夕凡尼亞大學|賓州大學|University of Pennsylvania','University of Pennsylvania','US'),
 (r'德州農工|Texas A&M','Texas A&M University','US'),
 (r'Texas at Austin|德州大學奧斯汀','University of Texas at Austin','US'),
 (r'伊利諾|Illinois at Urbana|Urbana-Champaign','University of Illinois Urbana-Champaign','US'),
 (r'紐約州立大學石溪|Stony Brook','Stony Brook University (SUNY)','US'),
 (r'Binghamton','Binghamton University (SUNY)','US'),
 (r'Buffalo|水牛城','University at Buffalo (SUNY)','US'),
 (r'紐約市立','City University of New York','US'),
 (r'福特罕|Fordham','Fordham University','US'),
 (r'明尼蘇達|Minnesota','University of Minnesota','US'),
 (r'北卡州立|North Carolina State','North Carolina State University','US'),
 (r'北卡羅萊納|North Carolina','University of North Carolina at Chapel Hill','US'),
 (r'加州大學爾灣|Irvine','University of California, Irvine','US'),
 (r'加州大學戴維斯|Davis','University of California, Davis','US'),
 (r'加州大學柏克萊|Berkeley','University of California, Berkeley','US'),
 (r'加州大學聖塔克魯茲|Santa Cruz','University of California, Santa Cruz','US'),
 (r'Los Angeles|UCLA|洛杉磯','University of California, Los Angeles','US'),
 (r'南加州大學|Southern California','University of Southern California','US'),
 (r'范德堡|范登保|Vanderbilt','Vanderbilt University','US'),
 (r'任色列|Rensselaer','Rensselaer Polytechnic Institute','US'),
 (r'杜克|Duke','Duke University','US'),
 (r'布朗大學|Brown University','Brown University','US'),
 (r'波士頓大學|Boston University','Boston University','US'),
 (r'休士頓|Houston','University of Houston','US'),
 (r'喬治城|Georgetown','Georgetown University','US'),
 (r'喬治亞大學|University of Georgia','University of Georgia','US'),
 (r'奧勒岡|Oregon','University of Oregon','US'),
 (r'阿拉巴馬|Alabama','University of Alabama','US'),
 (r'密西西比|Mississippi','University of Mississippi','US'),
 (r'肯塔基|Kentucky','University of Kentucky','US'),
 (r'俄亥俄州立|Ohio State','The Ohio State University','US'),
 (r'愛荷華州立|Iowa State','Iowa State University','US'),
 (r'康乃爾|Cornell','Cornell University','US'),
 (r'克萊蒙|Claremont','Claremont Graduate University','US'),
 (r'夏威夷|Hawaii','University of Hawaii at Manoa','US'),
 (r'印第安那|Indiana University','Indiana University Bloomington','US'),
 (r'Syracuse|雪城','Syracuse University','US'),
 (r'Missouri|密蘇里','University of Missouri','US'),
 (r'Johns Hopkins|約翰霍普金斯','Johns Hopkins University','US'),
 (r'羅徹斯特|Rochester','University of Rochester','US'),
 (r'Virginia Polytechnic|維吉尼亞理工','Virginia Tech','US'),
 (r'Columbia University|哥倫比亞大學','Columbia University','US'),
 (r'Yale|耶魯','Yale University','US'),
 (r'倫敦政經|London School of Economics','London School of Economics','GB'),
 (r'University College London|倫敦大學學院','University College London','GB'),
 (r'牛津|Oxford','University of Oxford','GB'),
 (r'劍橋|Cambridge','University of Cambridge','GB'),
 (r'約克大學|University of York','University of York','GB'),
 (r'伯明罕|Birmingham','University of Birmingham','GB'),
 (r'利物浦|Liverpool','University of Liverpool','GB'),
 (r'艾賽克斯|Essex','University of Essex','GB'),
 (r'里茲|Leeds','University of Leeds','GB'),
 (r'愛丁堡|Edinburgh','University of Edinburgh','GB'),
 (r'Nottingham|諾丁漢','University of Nottingham','GB'),
 (r'澳洲國立新堡|新堡|Newcastle','University of Newcastle','AU'),
 (r'澳洲國家大學|澳洲國立大學|Australian National','Australian National University','AU'),
 (r'筑波|Tsukuba','University of Tsukuba','JP'),
 (r'蒂爾堡|Tilburg','Tilburg University','NL'),
 (r'土魯斯|Toulouse','Toulouse School of Economics','FR'),
 (r'魯汶|Leuven','KU Leuven','BE'),
 (r'Mannheim|曼海姆','University of Mannheim','DE'),
 (r'Stockholm|斯德哥爾摩','Stockholm University','SE'),
 (r'British Columbia|英屬哥倫比亞','University of British Columbia','CA'),
 (r'McMaster','McMaster University','CA'),
 (r'香港科技','Hong Kong University of Science and Technology','HK'),
 (r'臺灣 ?大學|台灣 ?大學|臺 灣大學|台大|National Taiwan University','National Taiwan University','TW'),
 (r'政治大學|政治 大學|National Chengchi','National Chengchi University','TW'),
 (r'中央大學|National Central','National Central University','TW'),
 (r'清華大學|Tsing Hua','National Tsing Hua University','TW'),
 (r'中正 ?大學|Chung Cheng','National Chung Cheng University','TW'),
 (r'東華大學|Dong Hwa','National Dong Hwa University','TW'),
 (r'中山大學|Sun Yat-sen','National Sun Yat-sen University','TW'),
 (r'臺北大學|台北大學|National Taipei University','National Taipei University','TW'),
 (r'交通大學|陽明交通','National Yang Ming Chiao Tung University','TW'),
 (r'逢甲','Feng Chia University','TW'),
]

PHD_FIELD = [(r'農業?經|Agricultur|農業、環境', 'Agricultural/applied economics'),
             (r'應用經濟|Applied Econ', 'Agricultural/applied economics'),
             (r'財務|財金|Finance', 'Finance'),
             (r'經濟|Econom|財政', 'Economics'),
             (r'商學|企業|經營管理|管理|公共行政|公共治理|國際貿易', 'Business/management'),
             (r'.', 'Other')]


def load_pages():
    idx = {}
    for f in glob.glob(os.path.join(PAGE_CACHE, '*', '*.json')):
        d = json.load(open(f, encoding='utf-8'))
        if str(d.get('status')) == '200' and d.get('text'):
            idx[d['url']] = f
    return idx


def page_text(path):
    h = json.load(open(path, encoding='utf-8'))['text']
    h = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', h)
    h = re.sub(r'(?i)<br\s*/?>|</(p|div|li|tr|td|th|h\d|dd|dt)>', '\n', h)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', h))
    lines = [re.sub(r'[ \t　\xa0]+', ' ', l).strip() for l in t.split('\n')]
    return '\n'.join(l for l in lines if l)


def page_title(path):
    m = re.search(r'(?is)<title>(.*?)</title>', json.load(open(path, encoding='utf-8'))['text'])
    return html.unescape(m.group(1)).strip() if m else ''


def degree_lines(text):
    return [l for l in text.split('\n')
            if PHD_WORD.search(l) and SCHOOL_WORD.search(l) and len(l) < 300 and not NOT_A_DEGREE.search(l)]


def table_degree_lines(text):
    """表格版型（政大等）：「博士」自成一格，校名在前面幾格，例如
    國別/學校名稱 / 系所 / 教育程度 / 美國 /美國紐約大學 / 經濟學系 / 博士"""
    lines = text.split('\n')
    out = []
    for i, l in enumerate(lines):
        if re.fullmatch(r'(博\s*士|Ph\.?\s?D\.?|Doctor(ate)?)', l.strip(), re.I):
            back = lines[max(0, i - 3):i]
            k = next((j for j in range(len(back) - 1, -1, -1) if SCHOOL_WORD.search(back[j])), None)
            if k is not None:
                out.append(' '.join(x.strip() for x in back[k:]) + ' 博士')
    return out


def find_candidates(roster, idx):
    """每位教師的候選學歷行，依來源可信度排序。"""
    by_host = collections.defaultdict(list)
    for u in idx:
        by_host[urllib.parse.urlparse(u).netloc].append(u)
    names = [r['name_zh'] for r in roster]
    titles = {}
    out = {}
    for r in roster:
        prof, web, name = r['official_profile_url'], r['personal_website'], r['name_zh']
        pages = []
        if prof in idx:
            pages.append(('profile' if int(r['profile_url_shared_by'] or 1) == 1 else 'list', prof))
        if web in idx:
            pages.append(('personal', web))
        for u in by_host.get(urllib.parse.urlparse(prof or '').netloc, []):
            if u == prof:
                continue
            if u not in titles:
                titles[u] = page_title(idx[u])
            if name in titles[u]:
                pages.append(('host_title', u))
        cands = []
        for src, u in pages:
            t = page_text(idx[u])
            i = t.find(name)
            if i < 0 and src != 'personal':
                continue
            tail = t[max(i, 0):]
            ls = [l for l in degree_lines(tail) if not GARBAGE.search(l)] or table_degree_lines(tail)
            if not ls or tail.find(ls[0]) >= MAX_DIST[src]:
                continue
            others = sum(1 for n in names if n != name and len(n) >= 2 and n in t)
            cands.append(dict(src=src, url=u, line=re.sub(r'\s+', ' ', ls[0]).strip(),
                              n_lines_after=len(set(ls)), other_roster_names=others,
                              rank=SOURCE_RANK[src] + (0.5 if others >= 3 else 0)))
        out[r['teacher_id']] = sorted(cands, key=lambda c: c['rank'])
    return out


def parse_degree(line):
    hits = sorted((m.start(), name, cc) for pat, name, cc in SCHOOLS
                  for m in [re.search(pat, line, re.I)] if m)
    school, country = (hits[0][1], hits[0][2]) if hits else ('', '')
    note = ('一行裡有多個學位：' + '；'.join(sorted({h[1] for h in hits}))) if len({h[1] for h in hits}) > 1 else ''
    field = next(f for p, f in PHD_FIELD if re.search(p, line, re.I))
    years = re.findall(r'(19[6-9]\d|20[0-2]\d)', line)
    year = (years[-1] if '-' in line else years[0]) if years else ''
    return school, country, field, year, note


PHD_FIELDS = ['teacher_id', 'name_zh', 'institution_zh', 'phd_school', 'phd_country', 'phd_field', 'phd_year',
              'phd_confidence', 'phd_source', 'phd_raw', 'phd_evidence_url', 'phd_note']


def build_phd(roster):
    idx = load_pages()
    print(f'快取網頁 {len(idx)} 頁')
    cands = find_candidates(roster, idx)
    manual = {m['teacher_id']: m for m in rd(os.path.join(DEC_DIR, 'roster_phd_manual.csv'))} \
        if os.path.exists(os.path.join(DEC_DIR, 'roster_phd_manual.csv')) else {}
    rows = []
    for r in roster:
        row = dict.fromkeys(PHD_FIELDS, '')
        row.update(teacher_id=r['teacher_id'], name_zh=r['name_zh'], institution_zh=r['institution_zh'])
        v = cands[r['teacher_id']]
        if v:
            c = v[0]
            school, country, field, year, note = parse_degree(c['line'])
            conf = 'high' if c['src'] in ('profile', 'personal') and c['other_roster_names'] < 3 else 'medium'
            if c['n_lines_after'] > 3 and c['src'] != 'list':
                conf = 'low'
                note = '；'.join(x for x in (note, '頁面上還有多個其他博士學歷，可能抓錯人') if x)
            if not school:
                conf = 'low'
            row.update(phd_school=school, phd_country=country, phd_field=field, phd_year=year,
                       phd_confidence=conf, phd_source=c['src'], phd_raw=c['line'],
                       phd_evidence_url=c['url'], phd_note=note)
        m = manual.get(r['teacher_id'])
        if m and (m.get('phd_school') or m.get('confidence') == 'no_phd'):
            # 人工／上網查證的結果整列取代自動抽取（自動抽到的欄位不混用，避免張冠李戴）
            row.update({k: m.get(k, '') for k in ('phd_school', 'phd_country', 'phd_field', 'phd_year')})
            row.update(phd_confidence=m.get('confidence') or 'manual', phd_source='manual',
                       phd_evidence_url=m.get('evidence_url', ''), phd_note=m.get('note', ''))
        rows.append(row)
    return rows


# ═══════════════════════════════════════════════════════════════
# 性別
# ═══════════════════════════════════════════════════════════════
# 國科會研究人才「基本資料」頁有性別欄，名冊建身分時就爬過但當時沒存這一欄。
# 約兩成填［不公開］，那些靠人工標註（Artifact 表單）補；人工標註與國科會重疊的 105 位全部一致。
GENDER_FIELDS = ['teacher_id', 'name_zh', 'gender', 'gender_source', 'gender_nstc', 'gender_manual', 'gender_basis']


def nstc_basic_fields(h):
    t = html.unescape(re.sub(r'<[^>]+>', '|', re.sub(r'(?is)<(script|style).*?</\1>', ' ', h)))
    cells = [c.strip() for c in t.split('|') if c.strip()]
    return {k: cells[cells.index(k) + 1] for k in ('中文姓名', '性別') if k in cells[:-1]}


def build_gender(roster):
    rsno = lambda u: urllib.parse.parse_qs(urllib.parse.urlsplit(u or '').query).get('rsNo', [''])[0]
    basic = {}
    for f in glob.glob(os.path.join(PAGE_CACHE, '*', '*.json')):
        d = json.load(open(f, encoding='utf-8'))
        if 'initBasic' in d['url'] and str(d.get('status')) == '200':
            basic[rsno(d['url'])] = d['text']
    mpath = os.path.join(DEC_DIR, 'roster_gender_manual.csv')
    manual = {m['teacher_id']: m for m in rd(mpath)} if os.path.exists(mpath) else {}
    rows = []
    for r in roster:
        b = nstc_basic_fields(basic.get(rsno(r['nstc_url']), '')) if r['nstc_url'] else {}
        g_nstc = {'男': 'M', '女': 'F'}.get(b.get('性別', ''), '') if b.get('中文姓名') == r['name_zh'] else ''
        m = manual.get(r['teacher_id'], {})
        g_man = m.get('gender', '') if m.get('gender') in ('M', 'F') else ''
        gender, src = (g_man, 'manual') if g_man else ((g_nstc, 'nstc_basic') if g_nstc else ('', ''))
        rows.append(dict(teacher_id=r['teacher_id'], name_zh=r['name_zh'], gender=gender, gender_source=src,
                         gender_nstc=g_nstc, gender_manual=g_man, gender_basis=m.get('basis', '')))
    both = [x for x in rows if x['gender_nstc'] and x['gender_manual']]
    print(f'  國科會有性別 {sum(1 for x in rows if x["gender_nstc"])} 位；人工 {len(manual)} 位；'
          f'兩者重疊 {len(both)} 位，不一致 {sum(1 for x in both if x["gender_nstc"] != x["gender_manual"])} 位')
    return rows


# ═══════════════════════════════════════════════════════════════
# 研究領域 → JEL 大類
# ═══════════════════════════════════════════════════════════════
# 主類取「專長文字」裡第一個對得到經濟學 JEL 的項目（老師自己寫的順序）；
# 專長對不到才退回國科會計畫學門最多的那一類。X = 非經濟學領域。
JEL_NAME={'A':'General Economics and Teaching','B':'History of Economic Thought and Methodology','C':'Mathematical and Quantitative Methods',
 'D':'Microeconomics','E':'Macroeconomics and Monetary Economics','F':'International Economics','G':'Financial Economics',
 'H':'Public Economics','I':'Health, Education, and Welfare','J':'Labor and Demographic Economics','K':'Law and Economics',
 'L':'Industrial Organization','M':'Business Administration and Marketing','N':'Economic History',
 'O':'Economic Development, Innovation, Technological Change, and Growth','P':'Political Economy and Comparative Economic Systems',
 'Q':'Agricultural and Natural Resource Economics; Environmental and Ecological Economics','R':'Urban, Rural, Regional, Real Estate, and Transportation Economics',
 'Z':'Other Special Topics','X':'Non-economics'}
# expertise keyword -> JEL (first match wins; order matters)
KW=[(r'人力資本','J'),(r'Economics of education|^教育$','I'),(r'Economics of Innovation','O'),(r'時間數列|面板|數值分析|一般均衡|經濟數學|經濟學之數學|研究方法|衝擊評估','C'),(r'旅遊經濟','Z'),(r'^資源|資源經濟|海洋經濟|漁','Q'),(r'所得分配|市場設計|訊息設計|風險經濟|經濟理論|生產與需求','D'),(r'永續','Q'),(r'經濟史|經濟思想史|Economic History','N'),(r'思想史|方法論','B'),(r'經濟學教育|經濟學通論|經濟學概論|^經濟學$','A'),
 (r'法律經濟|法與經濟|Law and Econ','K'),(r'政治經濟|Political Econ|比較經濟制度|經濟制度','P'),
 (r'計量|統計|時間序列|數量方法|數理經濟|賽局|博弈|Game|Econometric|機器學習|資料科學|大數據|人工智慧|計算經濟|實驗經濟|模擬|作業研究','C'),
 (r'行為經濟|神經經濟|個體|微觀|消費者|決策|資訊經濟|契約|拍賣|機制設計|Micro','D'),
 (r'總體|貨幣|景氣|經濟預測|動態隨機|DSGE|Macro|通貨','E'),
 (r'國際貿易|國際金融|國際經濟|匯率|貿易|開放經濟|International','F'),
 (r'財務|金融|銀行|資產定價|公司理財|風險管理|衍生性|投資|證券|保險|Financ','G'),
 (r'公共經濟|財政|租稅|賦稅|公共選擇|Public','H'),
 (r'健康|醫療|衛生|教育經濟|福利|社會安全|營養|Health','I'),
 (r'勞動|人口|人力資源|家庭經濟|移民|性別|Labor','J'),
 (r'產業|廠商|競爭|管制|反托拉斯|網路經濟|數位經濟|創新經濟|媒體經濟|運動經濟|Industrial','L'),
 (r'管理|行銷|企業|會計|策略|組織行為','M'),
 (r'發展|成長|技術|創新|生產力|中國經濟|轉型|Develop','O'),
 (r'農業|農產|糧食|食品|自然資源|環境|能源|生態|氣候|永續|漁業|林業|水資源|Agricult|Environment|Energy','Q'),
 (r'都市|區域|土地|不動產|房地產|住宅|交通|運輸|空間|地理|城鄉|Urban|Regional','R'),
 (r'文化|觀光|休閒|宗教|藝術','Z'),
 (r'社會學|政治學|國際關係|比較政治|語言|東南亞|投票|選舉|政黨','X')]
NSTC={'總體經濟學與貨幣經濟學':'E','個體經濟學':'D','產業組織與政策':'L','國際經濟學':'F','數理與數量方法':'C',
 '經濟發展、技術變動與成長':'O','農業與自然資源經濟學':'Q','健康、教育與福利':'I','人力資源':'J','公共經濟學':'H',
 '財務':'G','財務經濟學':'G','城鄉與區域經濟學':'R','都市及區域':'R','環境與資源管理':'Q','經濟史':'N','法律與經濟學':'K',
 '醫務管理':'I','企業經濟學':'M','方法論與經濟思想史':'B','經濟制度':'P','經濟學':'A','經濟學概論與教學':'A','交通運輸':'R',
 '地政':'R','公共行政':'X','比較政治':'X','國際關係':'X','政治理論':'X','策略管理':'M','行銷':'M','科技管理':'M','作業研究／數量方法':'C',
 '商事財經法':'K','人文地理':'R','休閒遊憩':'Z','公衛及環境醫學':'I','社會變遷與發展':'X','社會學方法論與研究法':'X'}


def expertise_items(text):
    return [x.strip() for x in re.split(r'[、,，;；/／\n]|及(?=[^\s]{2,})', text or '') if x.strip()]


JEL_FIELDS = ['teacher_id', 'name_zh', 'expertise_text', 'jel_primary', 'jel_primary_name', 'jel_all',
              'jel_projects_top', 'jel_projects_counts', 'jel_source', 'jel_agree_projects']


def build_jel(roster):
    proj = collections.defaultdict(collections.Counter)
    for p in rd(os.path.join(INPUT, 'project', 'projects_all.csv')):
        j = NSTC.get(p['discipline_code'])
        if j:
            for t in json.loads(p['member_teacher_ids_json']):
                proj[t][j] += 1
    rows, unmapped = [], collections.Counter()
    for r in roster:
        codes = []
        for it in expertise_items(r['expertise_text']):
            c = next((j for pat, j in KW if re.search(pat, it, re.I)), None)
            if c is None:
                unmapped[it] += 1
            elif c not in codes:
                codes.append(c)
        econ = [c for c in codes if c != 'X']
        pc = proj.get(r['teacher_id'], collections.Counter())
        ptop = pc.most_common(1)[0][0] if pc else ''
        primary = econ[0] if econ else (ptop or (codes[0] if codes else ''))
        rows.append(dict(
            teacher_id=r['teacher_id'], name_zh=r['name_zh'], expertise_text=r['expertise_text'],
            jel_primary=primary, jel_primary_name=JEL_NAME.get(primary, ''), jel_all=';'.join(codes),
            jel_projects_top=ptop, jel_projects_counts=json.dumps(dict(pc), ensure_ascii=False) if pc else '',
            jel_source='expertise' if econ else ('nstc_projects' if ptop else ('expertise' if codes else '')),
            jel_agree_projects='' if not ptop or not econ else int(ptop in econ)))
    print(f'  專長項目對不到 JEL 的 {sum(unmapped.values())} 個（例：{"、".join(k for k, _ in unmapped.most_common(8))}）')
    return rows


# ═══════════════════════════════════════════════════════════════
# 人工查核表
# ═══════════════════════════════════════════════════════════════
def write_review_sheet(phd_rows, roster):
    path = os.path.join(REVIEW_DIR, '08_PhD學歷查核.xlsx')
    if os.path.exists(path):
        print(f'  跳過（已存在，不覆蓋）：{os.path.basename(path)}')
        return
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    links = {r['teacher_id']: r for r in roster}
    order = {'': 0, 'low': 1, 'web_inferred': 2, 'medium': 3, 'no_phd': 4, 'high': 5, 'web_verified': 6, 'manual': 7}
    wb = Workbook()
    ws = wb.active
    ws.title = 'PhD'
    ws.append(['自動抽取的 PhD 學歷。沒抓到的與 low 排最前面。確認無誤就不用動；要修正或補上，填右邊「人工」欄位'
               '（學校用英文正式名，國別用兩碼），存好後跟 Claude 說一聲，會整理成 decisions/roster_phd_manual.csv。'])
    hdr = ['teacher_id', '姓名', '機構', '自動：學校', '自動：國別', '自動：領域', '自動：年份', '可信度', '原文', '證據網址',
           '系所頁', '個人網站', '人工：學校', '人工：國別', '人工：年份', '人工：依據網址', '備註']
    ws.append(hdr)
    for c in ws[2]:
        c.font = Font(bold=True)
    for p in sorted(phd_rows, key=lambda x: (order[x['phd_confidence']], x['institution_zh'], x['teacher_id'])):
        r = links[p['teacher_id']]
        ws.append([p['teacher_id'], p['name_zh'], p['institution_zh'], p['phd_school'], p['phd_country'], p['phd_field'],
                   p['phd_year'], p['phd_confidence'] or '沒抓到', p['phd_raw'], p['phd_evidence_url'],
                   r['official_profile_url'], r['personal_website'], '', '', '', '', p['phd_note']])
    fill = PatternFill('solid', fgColor='FFF2CC')
    for row in ws.iter_rows(min_row=3, min_col=13, max_col=16):
        for c in row:
            c.fill = fill
    for col, w in zip('ABCDEFGHIJKLMNOPQ', [9, 9, 16, 30, 6, 16, 7, 8, 40, 30, 30, 20, 30, 8, 8, 30, 30]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'C3'
    os.makedirs(REVIEW_DIR, exist_ok=True)
    wb.save(path)
    print(f'  人工查核表 → {os.path.relpath(path, FINAL)}')


def main():
    roster = [r for r in rd(os.path.join(INPUT, 'professor_demo', 'authors_master.csv')) if r['node_type'] == 'roster']
    print(f'名冊教師 {len(roster)} 位')

    print('\n性別')
    gender = build_gender(roster)
    wr(os.path.join(INPUT, 'professor_demo', 'roster_gender.csv'), gender, GENDER_FIELDS)
    print('  ', dict(collections.Counter(g['gender'] or '缺' for g in gender)))

    print('\nPhD 學歷')
    phd = build_phd(roster)
    wr(os.path.join(INPUT, 'professor_demo', 'roster_phd.csv'), phd, PHD_FIELDS)
    conf = collections.Counter(p['phd_confidence'] or 'none' for p in phd)
    print('  可信度：', dict(conf))
    print('  國別：', collections.Counter(p['phd_country'] for p in phd if p['phd_country']).most_common(8))
    write_review_sheet(phd, roster)

    print('\n研究領域（JEL）')
    jel = build_jel(roster)
    wr(os.path.join(INPUT, 'professor_demo', 'roster_field_jel.csv'), jel, JEL_FIELDS)
    print('  主類：', collections.Counter(j['jel_primary'] for j in jel).most_common())
    ag = [j['jel_agree_projects'] for j in jel if j['jel_agree_projects'] != '']
    print(f'  專長與計畫學門一致：{sum(ag)}/{len(ag)}')


if __name__ == '__main__':
    main()
