#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the visual report from completed spatial-concentration runs (no simulations)."""
from analyze import *
from matplotlib.font_manager import FontProperties
from scipy.stats import hypergeom
import html
OUT=BASE/'spatial_concentration';T=OUT/'tables';F=OUT/'figures'
plt.rcParams['font.family']=['DejaVu Sans',FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc').get_name()]
plt.rcParams['font.size']=10
NAMES={'0001':'政大','0002':'清華','0003':'台大','0005':'成功','0006':'中興','0008':'中央','0009':'中山','0012':'海洋','0013':'中正','0017':'台北大','0018':'嘉義','0019':'高雄','0020':'東華','0021':'暨南','0031':'宜蘭','1001':'東海','1002':'輔仁','1003':'東吳','1005':'淡江','1006':'文化','1007':'逢甲','1015':'世新','1016':'銘傳','1021':'真理','1050':'佛光','AS':'中研院'}
CASES={'main':'主分析：同機構合併／原始座標','units_display':'27單位／顯示座標','units_raw':'27單位／原始座標','parent_display':'26機構／顯示座標','journal':'只看期刊','active':'現役名冊','publishing':'有發表的名冊','two_roster':'每篇恰有2位名冊作者','early':'2015–2019','late':'2020–2024','through2025':'延伸至2025'}
sections=[]
def save(fig,name,title,caption,reading):
    for ext in ['png','svg']:fig.savefig(F/f'{name}.{ext}',dpi=175,bbox_inches='tight')
    plt.close(fig);sections.append(dict(name=name,title=title,caption=caption,reading=reading))
def histline(ax,data,observed,label):
    ax.hist(data,bins=25,color=PALETTE[0],alpha=.75);ax.axvline(observed,color=PALETTE[1],lw=2,label=label);ax.legend(fontsize=9)

def main():
    cases=pd.read_csv(T/'cases.csv');c=cases.set_index('case');base=c.loc['main'];drop=c.loc['drop_AS'];matched=cases[cases.kind=='matched']
    audit=pd.read_csv(T/'organization_audit.csv',dtype={'unit':str,'parent':str});nodes=pd.read_csv(T/'nodes.csv',dtype={'unit':str,'parent':str,'node_id':str})
    near=pd.read_csv(T/'near_organization_pairs.csv',dtype={'parent_a':str,'parent_b':str}).sort_values('edges',ascending=False)
    edges=pd.read_csv(T/'edge_provenance.csv',dtype={'parent_a':str,'parent_b':str,'unit_a':str,'unit_b':str})
    profiles=pd.read_csv(T/'distance_profiles.csv');diag=pd.read_csv(T/'chain_diagnostics.csv');manifest=json.loads((OUT/'run_manifest.json').read_text())
    # 1. Actual geography and the institution pairs that account for the short-distance peak.
    parentgeo=nodes.groupby('parent').agg(lat=('lat','mean'),lon=('lon','mean'),roster=('node_id','size'),stubs=('degree','sum'))
    pair_edges=edges.groupby(['parent_a','parent_b']).size()
    fig,axs=plt.subplots(1,3,figsize=(14,5.8),gridspec_kw={'width_ratios':[.85,1,1.3]},layout='constrained')
    geojson=json.loads((FINAL/'basemap copy/tw_county.geojson').read_text())
    for feature in geojson['features']:
        geom=feature['geometry'];polys=geom['coordinates'] if geom['type']=='MultiPolygon' else [geom['coordinates']]
        for rings in polys:
            a=np.array(rings[0]);axs[0].plot(a[:,0],a[:,1],color='#c8d0d5',lw=.45,zorder=0)
    for ax in axs[:2]:
        for (a,b),w in pair_edges.items():
            ga,gb=parentgeo.loc[a],parentgeo.loc[b];isnear=(edges[(edges.parent_a==a)&(edges.parent_b==b)].distance_km.iloc[0]<10)
            ax.plot([ga.lon,gb.lon],[ga.lat,gb.lat],color=PALETTE[1] if isnear else '#869bb0',alpha=.65 if isnear else .2,lw=.4+math.log1p(w)*.45,zorder=1)
        for p,r in parentgeo.iterrows():ax.scatter(r.lon,r.lat,s=25+2.3*r.roster,color=PALETTE[1] if p=='AS' else PALETTE[0],edgecolors='white',lw=.6,zorder=3)
    axs[0].set(xlim=(119.9,122),ylim=(21.8,25.5),xlabel='Longitude',ylabel='Latitude',title='A  研究者與合作的空間配置')
    for p in ['0002','0005','0009','0020']:
        r=parentgeo.loc[p];axs[0].annotate(NAMES[p],(r.lon,r.lat),xytext=(5,4),textcoords='offset points',fontsize=9)
    axs[1].set(xlim=(121.50,121.655),ylim=(24.955,25.155),xlabel='Longitude',ylabel='Latitude',title='B  台北近距離連線（橘色）')
    axs[1].set_xticks([121.50,121.55,121.60,121.65])
    offsets={'AS':(5,5),'0003':(-24,-14),'0001':(3,-14),'1003':(5,4),'1015':(-24,7),'1006':(5,4)}
    for p,off in offsets.items():r=parentgeo.loc[p];axs[1].annotate(NAMES[p],(r.lon,r.lat),xytext=off,textcoords='offset points',fontsize=9)
    q=near[near.edges>0].copy();y=np.arange(len(q));axs[2].barh(y,q.edges,color=[PALETTE[1] if 'AS' in (r.parent_a,r.parent_b) else PALETTE[0] for r in q.itertuples()]);axs[2].set_yticks(y,[NAMES[r.parent_a]+'—'+NAMES[r.parent_b] for r in q.itertuples()]);axs[2].invert_yaxis();axs[2].set(xlabel='不同作者合作對',title='C  哪些機構對組成 <10 km 高峰？',xlim=(0,24))
    for j,r in enumerate(q.itertuples()):axs[2].text(r.edges+.3,j,str(r.edges),va='center')
    share=near[(near.parent_a=='AS')|(near.parent_b=='AS')].edges.sum()/near.edges.sum()
    save(fig,'01_geographic_structure','先看高峰是哪些連線組成','每個點是一個parent organization，大小表示名冊人數；連線依不同共同作者對數加粗。主分析將AS01／AS02合併，使用底圖來源未jitter座標。地圖為現有機構位置，不是歷史任職地點。',f'<10公里的{int(base.obs_0)}條邊中，有{share:.1%}連到中研院；主要集中於中研院與台大、政大、東吳三組關係。這是組成描述，不是機構因果效果。')
    # 2. Main hypothesis: same observed graph, two explicitly different baselines.
    p=profiles[profiles.case=='main'].iloc[:6];xx=np.arange(6);fig,axs=plt.subplots(1,2,figsize=(12,4.7),layout='constrained')
    axs[0].fill_between(xx,p.q025,p.q975,color=PALETTE[0],alpha=.17,label='M1中央95%模擬區間')
    axs[0].plot(xx,p.observed,'D-',color=PALETTE[1],label='觀察值',lw=2);axs[0].plot(xx,p.m1,'o-',color=PALETTE[0],label='M1：保留每人degree');axs[0].plot(xx,p.m0,'s--',color=PALETTE[2],label='M0：均勻配對機會')
    axs[0].set_xticks(xx,p['bin']);axs[0].set(xlabel='距離區間（km）',ylabel='不同跨機構作者對',title='A  近距離高峰需要額外距離偏好嗎？');axs[0].legend(fontsize=8)
    draws=pd.read_csv(OUT/'diagnostics/main_samples.csv').b0;support=np.arange(0,85);pmf=hypergeom.pmf(support,int(base.possible_pairs),int(base.opp_0),int(base.edges))
    axs[1].plot(support,pmf,color=PALETTE[2],lw=2,label='M0：精確超幾何分布');axs[1].hist(draws,bins=np.arange(draws.min()-.5,draws.max()+1.5),density=True,alpha=.6,color=PALETTE[0],label='M1：4鏈 × 499次')
    axs[1].axvline(base.obs_0,color=PALETTE[1],lw=2,label=f'觀察 {int(base.obs_0)}條');axs[1].set(xlabel='<10 km合作邊數',ylabel='機率／相對頻率',title='B  53條邊在兩種基準下的位置');axs[1].legend(fontsize=8)
    save(fig,'02_null_comparison','H1：近距離優勢在控制degree後減弱','M0保留節點、位置、跨機構允許配對與總邊數；M1再保留每人的跨機構degree，重排合作夥伴。M1不保留距離分布。區間是null分布，非母體效果信賴區間。',f'觀察／預期由M0的{base.ratio0_0:.2f}倍變成M1的{base.ratio1_0:.2f}倍。M1預期{base.m1_0:.1f}條，中央95%為{base.null_q025_0:.0f}–{base.null_q975_0:.0f}條，觀察{base.obs_0:.0f}條。這支持結構解釋，不能推論距離沒有因果影響。')
    # 3. Boundary audit + sensitivity across samples and distance cutoffs.
    selected=['main','units_display','units_raw','parent_display','journal','active','publishing','two_roster','early','late','through2025'];rr=c.loc[selected];fig,axs=plt.subplots(1,2,figsize=(13,6.3),gridspec_kw={'width_ratios':[1.4,1]},layout='constrained');yy=np.arange(len(rr))
    for j,(_,r) in enumerate(rr.iterrows()):
        axs[0].plot([r.ratio1_0,r.ratio0_0],[j,j],color='#b7c5ce',lw=2)
        axs[0].plot([r.null_q025_0/r.m1_0,r.null_q975_0/r.m1_0],[j,j],color=PALETTE[0],alpha=.2,lw=9)
    axs[0].scatter(rr.ratio0_0,yy,color=PALETTE[2],s=32,label='觀察／M0預期',zorder=4);axs[0].scatter(rr.ratio1_0,yy,color=PALETTE[1],s=32,label='觀察／M1預期',zorder=4);axs[0].axvline(1,color='#777',ls='--',lw=1)
    axs[0].set_yticks(yy,[CASES[k] for k in selected]);axs[0].invert_yaxis();axs[0].set(xlabel='<10 km 觀察／預期',title='A  各項敏感度的基準比較',xlim=(.5,2.5));axs[0].legend(fontsize=8,loc='lower right')
    mat=rr[[f'ratio1_{j}' for j in range(3)]].to_numpy();im=axs[1].imshow(mat,cmap='RdBu_r',vmin=.6,vmax=1.4,aspect='auto')
    axs[1].set_xticks(range(3),['<10 km','<25 km','<50 km']);axs[1].set_yticks(yy,[]);axs[1].set(title='B  改變近距離定義（觀察／M1）')
    for j in range(len(rr)):
        for k in range(3):axs[1].text(k,j,f'{mat[j,k]:.2f}',ha='center',va='center',fontsize=9)
    fig.colorbar(im,ax=axs[1],label='1 = M1預期')
    save(fig,'03_sensitivity','短距離超額是否依賴樣本或定義？','左圖淡藍水平帶是各案例M1抽樣邊數除以其均值後的中央95%範圍，不是橘點估計的信賴區間。所有案例重算分母及degree。單位合併排除5條院內邊；改回未jitter座標未改變這些分箱的觀察邊數。',f'主分析及必要敏感度中，<10公里的觀察／M1約{rr.ratio1_0.min():.2f}–{rr.ratio1_0.max():.2f}倍。沒有穩定的大幅短距離超額；早期樣本反而稍低於基準。')
    # 4. LOO decomposition: raw probability and degree-corrected residual side-by-side.
    loo=cases[cases.kind=='leave_organization_out'].copy();loo['parent']=loo['case'].str.replace('drop_','',regex=False);loo['delta_pp']=(loo.rate_0-base.rate_0)*100;loo=loo.sort_values('delta_pp')
    fig,axs=plt.subplots(1,2,figsize=(12,8),layout='constrained');yy=np.arange(len(loo));colors=[PALETTE[1] if k=='AS' else PALETTE[0] for k in loo.parent]
    axs[0].barh(yy,loo.delta_pp,color=colors);axs[0].axvline(0,color='#888',lw=1);axs[0].set_yticks(yy,[NAMES[k] for k in loo.parent]);axs[0].invert_yaxis();axs[0].set(xlabel='移除後 − 主分析（百分點）',title='A  刪除哪個機構改變近距離機率？')
    axs[1].scatter(loo.ratio1_0,yy,c=colors,s=40);axs[1].axvline(1,color='#888',ls='--',label='新網路的M1基準');axs[1].set_yticks(yy,[]);axs[1].invert_yaxis();axs[1].set(xlabel='移除後：觀察／重新估計的M1',title='B  刪除後degree也重新計算');axs[1].legend(fontsize=8)
    save(fig,'04_organization_removal','逐一排除所有機構，而非只挑中研院','每次刪除一個parent及相連邊，其餘論文內合作保留；重新計算機會分母、degree與M1。這是資料結構的影響診斷，不是預測真實組織消失後的行為。',f'排除中研院後，<10公里從{base.rate_0:.3%}降至{drop.rate_0:.3%}，僅剩{drop.obs_0:.0f}條；觀察／M1降至{drop.ratio1_0:.2f}倍。它對圖形的影響最突出，但地理位置也一起被刪除。')
    # 5. Matched deletion: raw and degree corrected; exact matching impossibility visible.
    fig,axs=plt.subplots(1,3,figsize=(14,4.8),layout='constrained')
    histline(axs[0],matched.rate_0*100,drop.rate_0*100,'排除中研院');axs[0].set(xlabel='刪除後 <10 km合作機率（%）',ylabel='匹配刪除組數',title='A  499組全台degree匹配刪除')
    histline(axs[1],matched.ratio1_0,drop.ratio1_0,'排除中研院');axs[1].set(xlabel='刪除後：觀察／M1預期',ylabel='匹配刪除組數',title='B  每組另估degree保留基準')
    feas=pd.read_csv(T/'matching_feasibility.csv');tf=feas[feas.pool=='taipei'];xx=np.arange(6)
    axs[2].bar(xx-.18,tf.needed,.36,color=PALETTE[1],label='AS需匹配人數');axs[2].bar(xx+.18,tf.available,.36,color=PALETTE[0],label='台北非AS可用人數');axs[2].set_xticks(xx,['0','1','2–3','4–7','8–15','16+']);axs[2].set(xlabel='刪除前跨機構degree',ylabel='研究者數',title='C  台北市內匹配不可行');axs[2].legend(fontsize=8)
    for j,r in enumerate(tf.itertuples()):
        if not r.feasible:axs[2].annotate('不足',(j,r.needed),xytext=(0,8),textcoords='offset points',ha='center',color=PALETTE[1],fontsize=9)
    save(fig,'05_matched_removal','H2：全台匹配有差異，但地理對照缺乏重疊','每組刪42人，degree分箱人數與AS相同，總degree在±5%內；不依結果挑樣本。每組M1為2鏈×99次，均值精度較主分析低。台北市內8–15及16+degree層人數不足，不放寬條件硬做地理匹配。',f'全台匹配刪除後的機率中央95%為{matched.rate_0.quantile(.025):.3%}–{matched.rate_0.quantile(.975):.3%}，AS為{drop.rate_0:.3%}。但匹配集合平均只刪{matched.removed_taipei.mean():.1f}位台北教師，AS的42位全在台北；不能把差異全歸於機構身份。')
    # 6. Numeric matching limitations: spatial imbalance and reused high-degree controls.
    removed=pd.read_csv(T/'matched_removed_nodes.csv');inclusions=removed.groupby('node_id').rep.nunique().sort_values(ascending=False)/len(matched)
    fig,axs=plt.subplots(1,2,figsize=(12,4.7),layout='constrained')
    histline(axs[0],matched.removed_taipei,42,'AS：42人都在台北');axs[0].set(xlabel='每組被刪除的台北市研究者',ylabel='匹配組數',title='A  匹配degree沒有匹配地理')
    axs[1].bar(np.arange(15),inclusions.iloc[:15],color=PALETTE[0]);axs[1].set_xticks(np.arange(15),inclusions.index[:15],rotation=65,fontsize=8);axs[1].set(ylabel='出現在499組匹配中的比例',title='B  少數高degree對照被反覆使用',ylim=(0,1.08));axs[1].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1))
    save(fig,'06_matching_limits','把匹配限制畫出來，避免把「有差異」當成因果','499組集合可能重疊，不是499個獨立機構；高degree候選稀少會被反覆抽中。這些圖是對照品質檢查，不是額外研究假說。',f'最高被選中比例為{inclusions.max():.0%}。H2可保留「AS比全台degree匹配集合更影響短距離結構」，但「超過地理聚集本身的AS特殊性」目前不可辨識。')
    # 7. Diagnostics visible, independent chains and edge-overlap trace.
    sim=pd.read_csv(OUT/'diagnostics/main_samples.csv');fig,axs=plt.subplots(2,2,figsize=(12,6.5),layout='constrained')
    for chain,g in sim.groupby('chain'):
        axs[0,0].plot(g.draw,g.b0,lw=.5,alpha=.55,color=PALETTE[int(chain)],label=f'Chain {chain+1}')
        axs[0,1].plot(g.draw,g.original_edge_overlap,lw=.5,alpha=.6,color=PALETTE[int(chain)])
    axs[0,0].axhline(base.obs_0,color='black',ls='--',lw=1);axs[0,0].set(title='A  主分析：近距離邊數trace',xlabel='保存樣本',ylabel='<10 km邊數');axs[0,0].legend(fontsize=8,ncol=4)
    axs[0,1].set(title='B  觀察原始邊是否被充分更換',xlabel='保存樣本',ylabel='與原始272條邊的重疊數')
    major=diag[~diag.case.str.startswith('match_')];axs[1,0].hist(major.split_rhat,bins=20,color=PALETTE[0]);axs[1,0].axvline(1.05,color=PALETTE[1],ls='--',label='診斷參考線1.05');axs[1,0].set(xlabel='Basic split-Rhat',ylabel='案例 × 距離切點',title='C  主分析／敏感度／逐機構刪除');axs[1,0].legend(fontsize=8)
    axs[1,1].hist(major.ess,bins=20,color=PALETTE[2]);axs[1,1].set(xlabel='簡化自相關有效樣本數',ylabel='案例 × 距離切點',title='D  估計精度診斷（每案例1996 draws）')
    save(fig,'07_chain_diagnostics','隨機化結果是否穩定？','每個主要案例4個獨立seed、200×邊數burn-in attempts、每20×邊數attempts保存一次，共499次／鏈。每次保存驗證degree、邊數與禁止邊。Rhat／ESS是基本診斷，不是不可約性或全狀態空間探索的證明。',f'37個主要／敏感度／逐機構案例，三切點的最大split-Rhat={major.split_rhat.max():.4f}，最小ESS={major.ess.min():.0f}。未看到明顯鏈間不一致；499組匹配另用较短鏈，診斷與全部樣本均保留。')
    # Concise results, automatically derived numbers, with explicit scope and failed matching.
    results=f'''# Spatial concentration：執行結果

2026-09-12；plan v0.2（修正顯示jitter座標）。來源40份CSV雜湊全部未變。主樣本4058篇、520位名冊、26個parent organizations、272條跨機構邊。報告圖表見index.html。

## H1：支持有限的結構解釋

<10公里觀察{base.obs_0:.0f}條；M0預期{base.m0_0:.2f}，觀察／預期{base.ratio0_0:.2f}倍；M1預期{base.m1_0:.2f}，觀察／預期{base.ratio1_0:.2f}倍，中央95%null區間{base.null_q025_0:.0f}–{base.null_q975_0:.0f}。控制各人degree後，表面短距離超額明顯減弱。期刊、active、發表者、兩位名冊作者、前後期與延伸2025下大致相同；這不是無距離效果的等效性檢驗。Degree本身可能是地理過程的結果。

## H2：僅支持與全台degree匹配集合的比較

短距離53條中47條涉及AS。刪AS後剩6條、機率{drop.rate_0:.3%}、觀察／M1={drop.ratio1_0:.2f}。499組匹配刪除每組42人，degree-bin counts精確相同、總degree±5%，相應機率中央95%為{matched.rate_0.quantile(.025):.3%}–{matched.rate_0.quantile(.975):.3%}。然而匹配組平均只有{matched.removed_taipei.mean():.1f}位台北教師，AS有42位。台北市內高degree候選不足，無法完成地理匹配，不宣稱AS身份有超出地理位置的效應。

## 修正與資料限制

來源basemap copy/institutions copy.csv明確標記AS座標jitter；分析改用其原始lat/lon。機構合併排除AS01-AS02的5條邊。各版座標的分箱邊數相同，但仍應使用原始位置。其餘25個單位對應不同具名大學；未發現其他相同parent的名冊單位。地點仍是現有主校區proxy，可能有多校區或歷史任職誤差。沒有逐年在職risk set。

## 計算與診斷

37個主要／敏感度／逐機構案例各4×499個M1樣本；499個匹配案例各2×99。共536案例、172654個保存的隨機圖，每張均驗證degree及允許邊條件。37個主要案例的最大基本split-Rhat={major.split_rhat.max():.4f}、最小簡化ESS={major.ess.min():.0f}。匹配的短鏈用來估均值，不把所有模擬當母體獨立觀察。受限switch chain的不可約性沒有形式證明，不把診斷當證明。

M0使用超幾何分布的精確期望與分布，非另擬合參數。未用配對獨立標準誤、未追求最小p值、未把無顯著超額當等效證明。每篇恰有兩位名冊作者的敏感度保留主要方向，未觸發計畫中「若大團隊驅動才加入二部圖null」的擴充。尚未控制主題；不將殘餘或AS影響解釋成因果。

## 文獻定位與建議

[Pan et al. 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3509350/)已討論合作距離與研究規模；[Expert et al. 2011](https://pmc.ncbi.nlm.nih.gov/articles/PMC3093492/)說明空間網路的基準應依問題設計（其方法研究空間校正社群，並非本分析同一演算法）。最新直接相鄰研究[van der Pol & Frenken 2025](https://link.springer.com/article/10.1007/s11192-025-05310-5)以荷蘭國內機構合作，控制規模與旅行距離後研究殘差與組織整合；本題不宜宣稱第一次分開地理與規模。

目前成果適合當可重現的結構分解案例。若投稿，應精確呈現「聚合的近距離峰值可由個人degree空間配置重現」和組織定義敏感度；還不能保證原創增量。要進一步辨識AS特殊性，需要可行的地理對照或更完整資料，而非增加模型複雜度。

AS parent歸屬核對：[中研院研究單位官方清單](https://www.sinica.edu.tw/en/cl/15)。不得將本名冊結論外推為台灣全學科。

## 重現

`python3 final_plan/analysis/code/research_spatial_concentration.py`

`python3 final_plan/analysis/code/report_spatial_concentration.py`

`python3 final_plan/analysis/code/test_research_spatial_concentration.py`

主流程為Python；隨機圖交換使用隨附C++小型加速器，執行時本地編譯，無額外Python依賴。設定見code/spatial_concentration_config.json；run_manifest記錄來源、設定、程式SHA256與環境。
'''
    (OUT/'RESULTS.md').write_text(results)
    summary={'H1':'支持結構解釋，非因果／等效性結論','H2':'全台degree匹配不同；AS身份超出地理的特殊性不可辨識','near_AS_share':share,'M0_ratio':base.ratio0_0,'M1_ratio':base.ratio1_0,'max_major_rhat':major.split_rhat.max(),'min_major_ess':major.ess.min(),'matched_rate_interval':[matched.rate_0.quantile(.025),matched.rate_0.quantile(.975)]}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    blocks=[]
    for z in sections:blocks.append(f'<section id="{z["name"]}"><h2>{z["title"]}</h2><p class="reading">{z["reading"]}</p><a href="figures/{z["name"]}.svg"><img loading="lazy" src="figures/{z["name"]}.png" alt="{z["title"]}"></a><p class="caption">{z["caption"]}</p><a href="figures/{z["name"]}.png">PNG</a> · <a href="figures/{z["name"]}.svg">SVG</a></section>')
    tables=''.join(f'<details><summary>{name}</summary><a href="tables/{name}.csv">下載CSV</a><div class="table">'+pd.read_csv(T/f'{name}.csv',dtype={'parent_a':str,'parent_b':str,'unit':str,'parent':str}).head(100).to_html(index=False,float_format=lambda v:f'{v:.4f}')+'</div></details>' for name in ['organization_audit','near_organization_pairs','cases','matching_feasibility','chain_diagnostics'])
    nav=''.join(f'<a href="#{z["name"]}">{j+1}. {z["title"]}</a>' for j,z in enumerate(sections))
    page='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>近距離合作：研究中心與空間配置</title><style>body{margin:0;background:#f2f5f7;color:#1e3446;font:16px/1.75 system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:30px}h1{font-size:32px;line-height:1.35}h2{font-size:23px}section{background:white;border-radius:12px;padding:26px;margin:26px 0}img{width:100%;height:auto}nav{display:flex;flex-wrap:wrap;gap:10px 20px}a{color:#176887}.reading{font-size:18px;border-left:4px solid #d76b45;padding-left:16px}.caption{color:#566879;font-size:14px}.table{overflow:auto}th,td{padding:6px;border-bottom:1px solid #ddd;white-space:nowrap;font-size:12px}summary{cursor:pointer}.cards{display:grid;grid-template-columns:1fr 1fr;gap:15px}.card{background:#eaf1f5;padding:20px;border-radius:8px}.card b{display:block;font-size:20px}details{margin:15px 0}@media(max-width:600px){main{padding:16px}section{padding:16px}.cards{grid-template-columns:1fr}}</style><main><h1>近距離合作的高峰，來自距離還是研究中心的空間配置？</h1><p>2015–2024；4058篇清理後紀錄；520位名冊研究者；26個parent organizations。這是一輪依研究計畫執行的探索性結構分析。</p><div class="cards"><div class="card"><b>H1：支持有限的結構解釋</b>53條近距離邊，均勻機會預期約27條，保留個人degree後約53條。短距離的表面超額明顯減弱。</div><div class="card"><b>H2：機構身份的特殊性仍無法判定</b>中研院比全台degree匹配集合更影響圖形，但台北市內缺乏足夠高degree對照，無法排除地理配置。</div></div><p>先看圖2理解主要結果，再看圖5、6理解匹配限制。<a href="RESULTS.md">完整結果備忘錄</a> · <a href="run_manifest.json">執行與來源紀錄</a> · <a href="../code/RESEARCH_PLAN_SPATIAL_CONCENTRATION.md">研究計畫</a></p><nav>'''+nav+'</nav>'+''.join(blocks)+'''<section><h2>結果如何使用</h2><p>所有來源CSV均未修改。分析修正AS繪圖jitter並合併parent；現有機構座標仍不是歷史任職位置。Degree可能已包含地理過程的結果，因此「null能重現」不是「距離沒有因果影響」。國別與國際作者未納入這個主題。</p><p>已執行機構核對、M0／M1、26次逐機構排除、499組degree匹配刪除、樣本／時間／距離切點敏感度與抽樣診斷。地理匹配不可行已保留；沒有放寬條件改做漂亮結果。</p><p>相鄰文獻：<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC3509350/">Pan et al. 2012</a>、<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC3093492/">Expert et al. 2011</a>、<a href="https://link.springer.com/article/10.1007/s11192-025-05310-5">van der Pol & Frenken 2025：荷蘭機構合作的規模／距離基準</a>。本結果尚不能宣稱新的普遍定律。</p></section><section><h2>核對表（圖為主，數值供追溯）</h2>'''+tables+'</section></main></html>'
    (OUT/'index.html').write_text(page);print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
