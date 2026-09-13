#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only temporal roster–external pilot. Run from any working directory."""
from analyze import *
import html
from matplotlib.font_manager import FontProperties
OUT=BASE/'temporal_external'
for d in [OUT,OUT/'figures',OUT/'tables']:d.mkdir(exist_ok=True)
plt.rcParams['font.family']=['DejaVu Sans',FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc').get_name()]
GROUPS=['TW','Overseas','Unknown']
NAMES=['國內非名冊','海外非名冊','國別未知']

def main():
    sources=[p for p in FINAL.rglob('*.csv') if BASE not in p.parents]
    hashes={str(p.relative_to(FINAL)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    _,master,roster,inst,papers=load()
    ps=[p for p in papers if p['eligible'] and clean(p) and 2015<=p['year']<=2024]
    country={n:m['affil_country'].strip().upper() for n,m in master.items() if n not in roster}
    strict={n:(c if master[n]['oa_match_confidence']=='high' and master[n]['oa_needs_review']=='0' else '') for n,c in country.items()}
    def group(n,cc):return 'TW' if cc[n]=='TW' else 'Overseas' if cc[n] else 'Unknown'
    events=[]
    for p in ps:
        rr=sorted(set(p['ids'])&roster);ee=sorted(set(p['ids'])-roster)
        for a in rr:
            for b in ee:events.append(dict(paper_id=p['id'],year=p['year'],roster=a,external=b,country=country[b],group=group(b,country),journal=p['journal']))
    ev=pd.DataFrame(events);ev.to_csv(OUT/'tables/events.csv',index=False)
    # Each publication gets one unit split across all roster authors, never across dyadic expansion.
    credit=[]
    for p in ps:
        rr=set(p['ids'])&roster;ee=set(p['ids'])-roster
        label='海外已辨識' if any(group(n,country)=='Overseas' for n in ee) else '含未知／無已知海外' if any(not country[n] for n in ee) else '僅已知國內非名冊' if ee else '無非名冊作者'
        credit.append(dict(paper_id=p['id'],year=p['year'],category=label,papers=1,roster_authors=len(rr)))
    pd.DataFrame(credit).to_csv(OUT/'tables/paper_categories.csv',index=False)
    sections=[]
    def save(fig,name,title,caption):
        for ext in ['png','svg']:fig.savefig(OUT/'figures'/f'{name}.{ext}',dpi=175,bbox_inches='tight')
        plt.close(fig);sections.append((name,title,caption))
    transitions=[];recurrences=[]
    for sample,ee,cc in [('main',ev,country),('journal',ev[ev.journal],country),('high_OA',ev,strict)]:
        tieyears=ee.groupby(['roster','external']).year.apply(lambda x:sorted(set(x))).to_dict()
        for (a,b),ys in tieyears.items():
            g=group(b,cc)
            for j,y in enumerate(ys):
                state='首次觀察' if j==0 else '連年出現' if ys[j-1]==y-1 else '間隔後再現'
                transitions.append(dict(sample=sample,roster=a,external=b,year=y,group=g,state=state))
            # Same first-observation cohort; three-year follow-up available for all 2017–2021 ties.
            if 2017<=ys[0]<=2021:
                for lag in [1,2,3]:recurrences.append(dict(sample=sample,roster=a,external=b,first=ys[0],group=g,lag=lag,repeated=int(any(ys[0]<y<=ys[0]+lag for y in ys))))
    tr=pd.DataFrame(transitions);tr.to_csv(OUT/'tables/tie_states.csv',index=False)
    rec=pd.DataFrame(recurrences);rec.to_csv(OUT/'tables/recurrence_events.csv',index=False)
    fig,axs=plt.subplots(1,3,figsize=(14,4.7),layout='constrained')
    for ax,g,label in zip(axs,GROUPS,NAMES):
        a=tr[(tr['sample']=='main')&(tr.group==g)].groupby(['year','state']).size().unstack(fill_value=0).reindex(range(2015,2025),fill_value=0)
        states=['首次觀察','連年出現','間隔後再現']
        ax.stackplot(a.index,*[a.get(s,pd.Series(0,index=a.index)) for s in states],labels=states,colors=PALETTE[:3],alpha=.85)
        ax.set(title=label,xlabel='發表年',ylabel='當年不同名冊—非名冊合作對',ylim=(0,300));ax.set_xticks([2015,2018,2021,2024]);ax.legend(fontsize=8,loc='upper left')
    save(fig,'01_tie_dynamics','合作成長是新夥伴、持續關係，還是重新連上？','同一年多篇合著只算一對。首次觀察不是真正首次合作；2015是左截斷邊界。間隔後再現不表示期間曾停止研究。三類國別使用現有彙整標籤，未知獨立保留。')
    fig,axs=plt.subplots(1,2,figsize=(11,4.7),layout='constrained')
    for g,label,col in zip(GROUPS,NAMES,PALETTE):
        for sample,ls in [('main','-'),('journal','--')]:
            x=rec[(rec['sample']==sample)&(rec.group==g)].groupby('lag').repeated.agg(['mean','size'])
            axs[0].plot(x.index,x['mean'],marker='o',ls=ls,color=col,label=label+('：全部' if sample=='main' else '：期刊'))
    axs[0].set(title='A  首次觀察後，累積再次合作比例',xlabel='首次觀察後年數',ylabel='三年追蹤cohort中的比例',xticks=[1,2,3],ylim=(0,1));axs[0].legend(fontsize=7);axs[0].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    states=['海外已辨識','僅已知國內非名冊','含未知／無已知海外','無非名冊作者']
    q=pd.DataFrame(credit).groupby(['year','category']).size().unstack(fill_value=0).reindex(columns=states,fill_value=0)
    shares=q.div(q.sum(axis=1),axis=0)
    axs[1].stackplot(shares.index,*[shares[s] for s in states],labels=states,colors=[PALETTE[1],PALETTE[0],'#b5b9c0',PALETTE[2]])
    axs[1].set(title='B  名冊可見產出的合作組成',xlabel='發表年',ylabel='每篇只計一次的論文比例',ylim=(0,1),xticks=[2015,2018,2021,2024]);axs[1].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1));axs[1].legend(fontsize=7,loc='lower left')
    save(fig,'02_recurrence_output','關係留下來了嗎？它們支撐多少可見產出？','A只追蹤2017–2021首次觀察的合作對，至少有2年回溯、完整3年追蹤；期刊子集會改變cohort。曲線為描述值，未控制作者活躍度或身份辨識偏差。B四類互斥且加總100%，海外類可能同時有國內及未知作者；不是合作的因果產出貢獻。')
    # Country window counts and effective number of roster contributors: (sum w)^2/sum(w^2).
    top=ev[ev.country!=''].groupby('country').size().nlargest(8).index.tolist()
    rows=[]
    for start in [2015,2017,2019,2021,2023]:
        ee=ev[ev.year.between(start,start+1)]
        for c in top:
            e=ee[ee.country==c];counts=e.groupby('roster').size().to_numpy();total=counts.sum()
            rows.append(dict(window=f'{start}–{start+1}',country=c,papers=e.paper_id.nunique(),active_roster=len(counts),effective_roster=total**2/(counts**2).sum() if total else 0,top_ego_share=counts.max()/total if total else np.nan))
    win=pd.DataFrame(rows);win.to_csv(OUT/'tables/country_windows.csv',index=False)
    fig,axs=plt.subplots(1,2,figsize=(12,5),layout='constrained')
    for ax,metric,title in zip(axs,['papers','effective_roster'],['A  含該國非名冊作者的論文數','B  合作是否分散：有效名冊連結人數']):
        a=win.pivot(index='country',columns='window',values=metric).reindex(top);im=ax.imshow(a,cmap='Blues',aspect='auto');ax.set_xticks(range(5),a.columns,rotation=30);ax.set_yticks(range(len(a)),a.index);ax.set_title(title)
        for i in range(len(a)):
            for j in range(5):ax.text(j,i,f'{a.iloc[i,j]:.0f}' if metric=='papers' else f'{a.iloc[i,j]:.1f}',ha='center',va='center',color='white' if a.iloc[i,j]>a.to_numpy().max()*.55 else '#183046')
        fig.colorbar(im,ax=ax,shrink=.75)
    save(fig,'03_country_capacity','合作量增加，是否也有更多人承接？','每兩年一窗。左圖同篇可含多國，因此不能跨國加總。右圖以名冊教師—外部作者—論文事件計算1/HHI；所有事件集中一位教師時等於1。這是連結分散程度，不是國家科研實力；大型團隊可能增加事件權重。TW表示國內非名冊合作。')
    assert len(ev)==len(ev.drop_duplicates(['paper_id','roster','external']))
    assert np.allclose(shares.sum(axis=1),1)
    assert all(hashlib.sha256((FINAL/p).read_bytes()).hexdigest()==v for p,v in hashes.items())
    summary={'papers':len(ps),'external_seen':ev.external.nunique(),'roster_external_pairs':len(ev[['roster','external']].drop_duplicates()),'source_hashes':hashes,'recurrence_3year':rec[rec.lag==3].groupby(['sample','group']).repeated.agg(['mean','size']).reset_index().to_dict('records')}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    blocks=''.join(f'<section><h2>{title}</h2><p>{cap}</p><a href="figures/{name}.svg"><img src="figures/{name}.png"></a></section>' for name,title,cap in sections)
    (OUT/'index.html').write_text('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Temporal external collaboration</title><style>body{font:16px/1.75 system-ui;background:#f3f6f8;color:#203447;margin:0}main{max-width:1200px;margin:auto;padding:24px}section{background:white;padding:20px;margin:24px 0}img{width:100%;height:auto}a{color:#176887}</style><main><h1>非名冊合作的時間結構與可見研究產出</h1><p>第一輪描述性圖表：2015–2024。國別是彙整affiliation標籤，未建立逐年身份；研究能量暫以可見產出、關係重現和連結分散程度拆開描述。</p><p><a href="../code/RESEARCH_PLAN_TEMPORAL_EXTERNAL.md">可修訂研究計畫</a> · <a href="FINDINGS.md">第一輪判讀</a> · <a href="summary.json">數據與來源雜湊</a></p>'+blocks+'</main></html>')
    print(json.dumps({k:v for k,v in summary.items() if k!='source_hashes'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
