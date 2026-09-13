#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descriptive science-of-science geography atlas. Source CSVs are read-only.
Run: python3 final_plan/analysis/code/geography_atlas.py
No historical nationality or affiliation is inferred; country means observed affiliation.
"""
from analyze import *
import html
from scipy.stats import spearmanr
OUT=BASE/'geography_atlas'
for d in [OUT,OUT/'figures',OUT/'tables']:d.mkdir(exist_ok=True)
PCT=matplotlib.ticker.PercentFormatter(1)
sections=[]; facts={}

def tab(name,rows):
    df=pd.DataFrame(rows);df.to_csv(OUT/'tables'/f'{name}.csv',index=False);return df

def figsave(fig,name,title,caption,table_names):
    for ext in ['png','svg']:fig.savefig(OUT/'figures'/f'{name}.{ext}',dpi=170,bbox_inches='tight')
    plt.close(fig); sections.append((name,title,caption,table_names))

def dist(a,b):
    x,y,z,w=map(math.radians,[float(a['lat']),float(a['lon']),float(b['lat']),float(b['lon'])])
    return 6371*2*math.asin(min(1,math.sqrt(math.sin((z-x)/2)**2+math.cos(x)*math.cos(z)*math.sin((w-y)/2)**2)))

def frac_summary(ps,country):
    f=u=0
    for p in ps:
        cs=[country[n] for n in p['ids']]
        foreign=any(c not in ('','TW') for c in cs)
        f+=foreign;u+=not foreign and '' in cs
    return len(ps),f,u

def rarefied(counts,k=5):
    n=sum(counts)
    if n<k:return float('nan')
    den=math.comb(n,k)
    return sum(1-(math.comb(n-v,k)/den if n-v>=k else 0) for v in counts)

def main():
    files=[x for x in FINAL.rglob('*.csv') if BASE not in x.parents]
    hashes={str(x.relative_to(FINAL)):hashlib.sha256(x.read_bytes()).hexdigest() for x in files}
    frames,master,roster,inst,papers=load();geo=frames['insts'].set_index('institution_code').to_dict('index')
    countries={n:('TW' if n in roster else m['affil_country'].strip().upper()) for n,m in master.items()}
    countries.update({n:'TW' for n in roster})
    strict={n:(c if n in roster or (master[n]['oa_match_confidence']=='high' and master[n]['oa_needs_review']=='0') else '') for n,c in countries.items()}
    sets={'clean':[p for p in papers if p['eligible'] and clean(p) and 2015<=p['year']<=2024],
          'all_eligible':[p for p in papers if p['eligible'] and 2015<=p['year']<=2024],
          'journal_clean':[p for p in papers if p['eligible'] and clean(p) and p['journal'] and 2015<=p['year']<=2024]}
    ps=sets['clean']; edges=projections(ps,roster)[0]; all_edges=projections(ps)[0]
    domestic=[e for e in edges if inst[e[0]]!=inst[e[1]]]
    facts.update(clean_papers=len(ps),roster=len(roster),institutions=len(geo),roster_edges=len(edges),cross_institution_edges=len(domestic))
    # 1: Missingness is visible in every international trend and size comparison.
    yearrows=[];sizerows=[];sensitivity=[]
    for mode,cc in [('affiliation',countries),('high_OA_only',strict)]:
        for key,ss in sets.items():
            n,f,u=frac_summary(ss,cc);sensitivity.append(dict(mode=mode,sample=key,n=n,foreign=f,unresolved_without_foreign=u,lower=f/n,upper=(f+u)/n))
        for y in range(2015,2025):
            ss=[p for p in ps if p['year']==y];n,f,u=frac_summary(ss,cc)
            yearrows.append(dict(mode=mode,year=y,n=n,foreign=f,unresolved_without_foreign=u,lower=f/n,upper=(f+u)/n))
        for size in [1,2,3,4,5]:
            ss=[p for p in ps if min(len(p['ids']),5)==size];n,f,u=frac_summary(ss,cc)
            if n:sizerows.append(dict(mode=mode,size='5+' if size==5 else str(size),n=n,foreign=f,unresolved_without_foreign=u,lower=f/n,upper=(f+u)/n))
    tab('country_sensitivity',sensitivity);tab('country_by_year',yearrows);tab('country_by_team_size',sizerows)
    fig,axs=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
    for ax,rr,xcol in [(axs[0],yearrows,'year'),(axs[1],sizerows,'size')]:
        a=[x for x in rr if x['mode']=='affiliation'];b=[x for x in rr if x['mode']=='high_OA_only'];x=np.arange(len(a))
        ax.fill_between(x,[v['lower'] for v in a],[v['upper'] for v in a],alpha=.2,color=PALETTE[0],label='Unresolved-country range')
        ax.plot(x,[v['lower'] for v in a],'o-',color=PALETTE[0],label='Known overseas affiliation')
        ax.plot(x,[v['lower'] for v in b],'s--',color=PALETTE[1],label='High OA match, no review flag')
        ax.set_xticks(x,[v[xcol] for v in a],rotation=30 if xcol=='year' else 0);ax.set_ylim(0,1);ax.yaxis.set_major_formatter(PCT)
        for j,v in enumerate(a):ax.text(j,.96,str(v['n']),ha='center',fontsize=8)
        ax.set(ylabel='Share of papers',xlabel='Publication year' if xcol=='year' else 'Authors per paper',title='A  International participation by year' if xcol=='year' else 'B  International participation by team size')
    axs[0].legend(fontsize=8,loc='upper left',bbox_to_anchor=(0,.88))
    figsave(fig,'01_country_coverage','跨國合作與時間、團隊大小','主樣本為完整且年份明確的論文。藍線：至少一名作者現有affiliation為TW以外；陰影上緣再加入尚無已知海外作者、但至少一名國別未知作者的論文。不是信賴區間，也不能修正錯配或歷史任職。橘線是較嚴格OA辨識子集，非真值。頂端數字為論文數。2025、2026不納入主分析。',['country_by_year','country_by_team_size','country_sensitivity'])
    # 2: Domestic opportunity normalization includes zero-edge pairs.
    bins=np.array([0,10,25,50,100,200,400,1000]); labels=['<10','10–25','25–50','50–100','100–200','200–400','400+']
    distances={(a,b):dist(geo[a],geo[b]) for a,b in itertools.combinations(sorted(geo),2)}
    d=lambda a,b: distances[pair(inst[a],inst[b])]
    opp=np.histogram([d(a,b) for a,b in itertools.combinations(sorted(roster),2) if inst[a]!=inst[b]],bins)[0]
    obs=np.histogram([d(a,b) for a,b in domestic],bins)[0]
    rate=np.divide(obs,opp,out=np.zeros(len(obs),float),where=opp>0)
    rng=random.Random(20270912);state=set(domestic);null=[];accepted=0
    # Degree-preserving swaps restricted to cross-institution graph.
    e=list(sorted(state))
    for rep in range(249+1):
        for _ in range((100 if rep==0 else 20)*len(e)):
            ii,jj=rng.sample(range(len(e)),2);a,b=e[ii];c,dn=e[jj]
            if rng.random()<.5:a,b=b,a
            if rng.random()<.5:c,dn=dn,c
            ad,cb=pair(a,dn),pair(c,b)
            if len({a,b,c,dn})<4 or inst[a]==inst[dn] or inst[c]==inst[b] or ad in state or cb in state:continue
            state.remove(e[ii]);state.remove(e[jj]);state.update([ad,cb]);e[ii],e[jj]=ad,cb;accepted+=1
        assert collections.Counter(itertools.chain.from_iterable(state))==collections.Counter(itertools.chain.from_iterable(domestic))
        if rep:null.append(np.histogram([d(a,b) for a,b in state],bins)[0])
    null=np.array(null);rr=[]
    for j,l in enumerate(labels):rr.append(dict(distance_km=l,possible_pairs=int(opp[j]),observed_pairs=int(obs[j]),edge_probability=rate[j] if opp[j] else np.nan,null_mean=float(null[:,j].mean()),null_q025=float(np.quantile(null[:,j],.025)),null_q975=float(np.quantile(null[:,j],.975))))
    tab('domestic_distance',rr);facts['distance_null_accepted_swaps']=accepted
    same=sum(inst[a]==inst[b] for a,b in edges);sameopp=sum(v*(v-1)//2 for v in collections.Counter(inst.values()).values())
    facts['same_institution_probability']=same/sameopp;facts['cross_institution_probability']=len(domestic)/sum(opp)
    fig,axs=plt.subplots(1,2,figsize=(12,4.6),layout='constrained');xx=np.arange(7)
    axs[0].bar(xx-.18,obs,.36,color=PALETTE[0],label='Observed');axs[0].bar(xx+.18,null.mean(0),.36,color=PALETTE[1],label='Degree-preserving null')
    axs[0].set(ylabel='Distinct roster coauthor pairs',title='A  Distance counts and degree baseline');axs[0].legend(fontsize=8)
    axs[1].plot(xx,np.where(opp>0,rate,np.nan),'o-',color=PALETTE[0]);axs[1].yaxis.set_major_formatter(PCT)
    axs[1].set(ylabel='Coauthor pairs / possible pairs',title='B  Distance-specific collaboration probability',ylim=(0,.0053))
    for j in range(7):
        if opp[j]:axs[1].annotate(f'{obs[j]}/{opp[j]}',(j,rate[j]),xytext=(0,7),textcoords='offset points',ha='center',fontsize=7)
    for ax in axs:ax.set_xticks(xx,labels);ax.set_xlabel('Institution separation (km)');ax.set_ylim(bottom=0)
    figsave(fig,'02_domestic_distance','距離衰減：線的數量與合作機會','名冊內跨機構無向不同作者配對；同機構另列summary，不混入零公里。分母包括未合作的名冊配對。null固定每人跨機構degree且禁止同機構邊，不固定距離，249次抽樣只作描述基準。位置為現有校址，直線距離不是旅行時間。零機會區間不畫機率；不擬合或宣稱power law。',['domestic_distance'])
    # 3: Geographic concentration in people vs fractional publications.
    count=collections.Counter(inst.values());credit=collections.Counter();foreigncredit=collections.Counter();unknowncredit=collections.Counter()
    for p in ps:
        ii={inst[n] for n in p['ids'] if n in roster};assert ii
        foreign=any(countries[n] not in ('','TW') for n in p['ids']);unc=not foreign and any(not countries[n] for n in p['ids'])
        for i in ii:
            credit[i]+=1/len(ii);foreigncredit[i]+=foreign/len(ii);unknowncredit[i]+=unc/len(ii)
    assert abs(sum(credit.values())-len(ps))<1e-6
    ir=[]
    for i in geo:
        ir.append(dict(institution=i,name=geo[i]['institution_name'],county=geo[i]['county'],roster=count[i],fractional_papers=credit[i],papers_per_roster=credit[i]/count[i],known_foreign_fraction=foreigncredit[i]/credit[i] if credit[i] else np.nan,unresolved_upper=(foreigncredit[i]+unknowncredit[i])/credit[i] if credit[i] else np.nan))
    tab('institution_activity',ir)
    cr=[]
    for county in sorted({g['county'] for g in geo.values()}):
        ix=[i for i in geo if geo[i]['county']==county];cr.append(dict(county=county,roster=sum(count[i] for i in ix),fractional_papers=sum(credit[i] for i in ix)))
    tab('county_activity',cr)
    groups={'Taipei City':{'臺北市'},'New Taipei':{'新北市'},'Other locations':{g['county'] for g in geo.values()}-{'臺北市','新北市'}}
    vals=[[sum(count[i] for i in geo if geo[i]['county'] in cs)/len(roster),sum(credit[i] for i in geo if geo[i]['county'] in cs)/len(ps)] for cs in groups.values()]
    facts['regional_shares']={k:dict(roster_share=v[0],fractional_paper_share=v[1]) for k,v in zip(groups,vals)}
    fig,axs=plt.subplots(1,2,figsize=(12,4.8),layout='constrained');x=np.arange(3)
    axs[0].bar(x-.18,[v[0] for v in vals],.36,label='Roster researchers',color=PALETTE[0]);axs[0].bar(x+.18,[v[1] for v in vals],.36,label='Fractional papers',color=PALETTE[1]);axs[0].set_xticks(x,list(groups));axs[0].yaxis.set_major_formatter(PCT);axs[0].legend(fontsize=8);axs[0].set(title='A  Geographic concentration',ylabel='Share of this dataset')
    for z in ir:
        axs[1].scatter(z['roster'],z['fractional_papers'],color=PALETTE[1] if z['county']=='臺北市' else PALETTE[0],s=40)
        if z['fractional_papers']>180:axs[1].annotate(z['institution'],(z['roster'],z['fractional_papers']),xytext=(4,3),textcoords='offset points',fontsize=8)
    lim=max(count.values())+3;axs[1].plot([0,lim],[0,lim*len(ps)/len(roster)],'--',color='#888',label='Equal output per roster researcher')
    axs[1].set(xlabel='Roster researchers',ylabel='Fractional papers',title='B  Institution size and observed output');axs[1].legend(fontsize=8)
    figsave(fig,'03_concentration','人數集中與論文活動集中','每篇論文的1單位在出現的不同名冊機構間均分，所有機構合計等於主樣本論文數；不是全體作者分數貢獻，也不是全國學科產量。分母使用520人現有名冊，未調整研究年資、任職年數、退休或資料蒐集完整度；每人產量是描述比例。橘色點為臺北市。',['institution_activity','county_activity'])
    # 4: Overseas partner concentration in both distinct people and paper incidences.
    foreignnodes={n for p in ps for n in p['ids'] if countries[n] not in ('','TW')};cn=collections.Counter(countries[n] for n in foreignnodes)
    fc=collections.Counter();full=collections.Counter()
    for p in ps:
        cc={countries[n] for n in p['ids']}-{ '','TW'}
        for c in cc:fc[c]+=1/len(cc);full[c]+=1
    top=[c for c,_ in cn.most_common(12)];countryrows=[dict(country=c,distinct_overseas_authors=cn[c],paper_presence=full[c],fractional_international_papers=fc[c]) for c in sorted(cn,key=cn.get,reverse=True)]
    tab('overseas_countries',countryrows);facts['top_countries']=countryrows[:5]
    fig,axs=plt.subplots(1,2,figsize=(12,4.8),layout='constrained');y=np.arange(len(top))
    axs[0].barh(y,[cn[c] for c in top],color=PALETTE[0]);axs[0].set_yticks(y,top);axs[0].invert_yaxis();axs[0].set(xlabel='Distinct observed overseas collaborators',title='A  Partner-country concentration')
    axs[1].barh(y,[fc[c] for c in top],color=PALETTE[1]);axs[1].set_yticks(y,top);axs[1].invert_yaxis();axs[1].set(xlabel='Fractional international papers',title='B  Country participation in papers')
    figsave(fig,'04_country_partners','國外夥伴集中在哪些國家／地區','僅顯示已辨識的TW以外affiliation。右圖每篇有已知海外作者的論文在其不同海外國別間均分。未調整各國全球研究規模，不能稱為超額國別偏好；未知國別保留於其他圖，不算台灣。外部作者缺乏可靠經緯度，因此不拿國家首都當作者位置來估國際distance decay。',['overseas_countries'])
    # 5: local/global degree and rarefaction by institution.
    adj=adjacency(all_edges);ar=[]
    for n in sorted(roster):
        ns=adj[n];dom=sum(countries[x]=='TW' for x in ns);fo=[x for x in ns if countries[x] not in ('','TW')];un=sum(not countries[x] for x in ns);c=collections.Counter(countries[x] for x in fo)
        ar.append(dict(node_id=n,institution=inst[n],domestic_partners=dom,foreign_partners=len(fo),unknown_partners=un,total_partners=len(ns),foreign_countries=len(c),rarefied_countries_5=rarefied(list(c.values())),paper_count=sum(n in p['ids'] for p in ps)))
    adf=tab('author_geography',ar);valid=adf[adf.total_partners>0];corr=spearmanr(valid.domestic_partners,valid.foreign_partners)
    facts['domestic_foreign_degree_spearman']=float(corr.statistic)
    dr=[]
    for i in geo:
        aa=adf[adf.institution==i];vv=aa[aa.foreign_partners>=5]
        dr.append(dict(institution=i,name=geo[i]['institution_name'],eligible_authors=len(vv),roster_authors=len(aa),median_rarefied_countries_5=float(vv.rarefied_countries_5.median()) if len(vv) else np.nan,median_foreign_partners=float(aa.foreign_partners.median())))
    tab('institution_diversity',dr)
    fig,axs=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
    sc=axs[0].scatter(valid.domestic_partners+1,valid.foreign_partners+1,c=valid.unknown_partners/valid.total_partners,cmap='viridis',vmin=0,vmax=1,s=25,alpha=.7)
    axs[0].set(xscale='log',yscale='log',xlabel='Domestic partners + 1',ylabel='Known overseas partners + 1',title='A  Local and international collaboration breadth');fig.colorbar(sc,ax=axs[0],label='Unknown-country partner fraction')
    vv=adf[adf.foreign_partners>=5];axs[1].scatter(vv.foreign_partners,vv.foreign_countries,s=22,alpha=.6,label='Observed countries',color=PALETTE[0]);axs[1].scatter(vv.foreign_partners,vv.rarefied_countries_5,s=22,alpha=.6,label='Expected countries among 5 partners',color=PALETTE[1]);axs[1].set(xscale='log',xlabel='Known overseas partners (at least 5)',ylabel='Country count',title='B  Diversity adjusted for partner count');axs[1].legend(fontsize=8)
    figsave(fig,'05_local_global','國內合作廣度與海外合作廣度','每位名冊教師以不同共同作者計degree；國內含名冊與TW外部作者。相關性未控制產量、學科、年資和身份辨識，不是互補／替代的因果檢驗。右圖的rarefaction是從某人的已知海外夥伴均勻不放回抽5人之預期不同國別數，避免夥伴多就必然國別多；它不能補回未知作者。',['author_geography','institution_diversity'])
    # 6: Institution international share, display unresolved range rather than rankings as fact.
    ordered=sorted(ir,key=lambda z:z['known_foreign_fraction']);fig,ax=plt.subplots(figsize=(10,8),layout='constrained')
    for j,z in enumerate(ordered):
        ax.plot([z['known_foreign_fraction'],z['unresolved_upper']],[j,j],color='#aebbc7',lw=5,alpha=.65)
        ax.scatter(z['known_foreign_fraction'],j,color=PALETTE[1] if z['county']=='臺北市' else PALETTE[0],s=35,zorder=3)
    
    from matplotlib.font_manager import FontProperties
    cjk=FontProperties(fname='/System/Library/Fonts/STHeiti Medium.ttc',size=9)
    ax.set_yticks(range(len(ordered)),[z['institution']+' '+z['name'] for z in ordered],fontproperties=cjk);ax.set(xlim=(0,1),xlabel='Fractional paper share: known overseas to unresolved upper bound',ylabel='Institution code (names in linked table)',title='International participation by institution');ax.xaxis.set_major_formatter(PCT)
    figsave(fig,'06_institution_international','各機構的國際合作比例：缺漏會不會改變排序？','沿用圖3的機構分數計數；點為已知海外合作，灰線延伸至把未定論文都算海外的上界。不是誤差棒。臺北市橘色，其餘藍色。小機構、資料缺漏多者不可用點估計做名次；中文名稱與論文分母請見表格。',['institution_activity'])
    # 7: tie recurrence, each dyad given equal 5-year follow-up. Only ties incident to roster.
    def recurrence(ss,cc):
        years=collections.defaultdict(set)
        for p in ss:
            for a,b in itertools.combinations(sorted(p['ids']),2):
                if a in roster or b in roster:years[(a,b)].add(p['year'])
        rr=[]
        for (a,b),ys in years.items():
            first=min(ys)
            if not 2015<=first<=2019:continue
            if a in roster and b in roster:kind='Same institution' if inst[a]==inst[b] else 'Other roster institution'
            else:
                ext=b if a in roster else a;kind='External TW' if cc[ext]=='TW' else 'Overseas' if cc[ext] else 'Unknown country'
            rr.append(dict(a=a,b=b,group=kind,first_observed_year=first,repeat_within_5_years=int(any(first<y<=first+5 for y in ys))))
        return rr
    tie=recurrence(ps,countries);tab('tie_followup',tie);repeat=[]
    kinds=['Same institution','Other roster institution','External TW','Overseas','Unknown country']
    for key,ss in [('clean',ps),('journal_clean',sets['journal_clean'])]:
        rr=recurrence(ss,countries)
        for g in kinds:
            a=[x for x in rr if x['group']==g];repeat.append(dict(sample=key,group=g,pairs=len(a),repeated=sum(x['repeat_within_5_years'] for x in a),repeat_fraction=np.mean([x['repeat_within_5_years'] for x in a]) if a else np.nan))
    tab('tie_recurrence',repeat);fig,ax=plt.subplots(figsize=(11,4.8),layout='constrained');x=np.arange(5)
    for off,key,col in [(-.18,'clean',PALETTE[0]),(.18,'journal_clean',PALETTE[1])]:
        rr=[z for z in repeat if z['sample']==key];ax.bar(x+off,[z['repeat_fraction'] for z in rr],.36,color=col,label=key)
        for j,z in enumerate(rr):ax.text(j+off,z['repeat_fraction']+.008,f"{z['repeated']}/{z['pairs']}",ha='center',fontsize=7)
    ax.set_xticks(x,['Same\ninstitution','Other roster\ninstitution','External\nTW','Overseas','Unknown\ncountry']);ax.yaxis.set_major_formatter(PCT);ax.set(ylabel='Pair observed again in a later year',title='Five-year recurrence after first observation in 2015–2019',ylim=(0,.65));ax.legend(fontsize=8)
    figsave(fig,'07_tie_recurrence','不同地理合作關係的重複出現','以2015–2019首次觀察到的不同作者對為cohort，給每對相同5年追蹤；同年多篇不算跨年重現。只分析至少一端為名冊的邊。首次觀察不是首次合作，未重現不是合作終止；未知國別／身份拆分可能人為降低重現率。期刊子集重新定義首次觀察，屬樣本敏感度。計數不是獨立樣本，因此不畫天真的binomial信賴區間。',['tie_recurrence','tie_followup'])
    # 8: distance sensitivity; separate opportunity geometry from institutional composition.
    variants=[('Clean / full roster',ps,set(roster)),('Journal only',sets['journal_clean'],set(roster)),
        ('Without NTU',ps,{n for n in roster if inst[n]!='0003'}),
        ('Without Academia Sinica',ps,{n for n in roster if not inst[n].startswith('AS')}),
        ('Active roster only',ps,{n for n in roster if n in master and master[n]['node_type']=='roster'})]
    ds=[];fig,ax=plt.subplots(figsize=(10,4.9),layout='constrained')
    for k,(label,ss,ns) in enumerate(variants):
        es=projections(ss,ns)[0];oo=np.histogram([d(a,b) for a,b in itertools.combinations(sorted(ns),2) if inst[a]!=inst[b]],bins)[0]
        ee=np.histogram([d(a,b) for a,b in es if inst[a]!=inst[b]],bins)[0]
        yy=np.divide(ee,oo,out=np.full(7,np.nan),where=oo>0)
        ax.plot(range(6),yy[:6],'o-',label=label,color=PALETTE[k],alpha=.8)
        for j in range(7):ds.append(dict(sample=label,distance_km=labels[j],pairs=int(ee[j]),possible_pairs=int(oo[j]),probability=yy[j]))
    tab('distance_sensitivity',ds);ax.set_xticks(range(6),labels[:6]);ax.yaxis.set_major_formatter(PCT);ax.set(xlabel='Institution separation (km)',ylabel='Coauthor pairs / possible pairs',title='Distance pattern under alternative samples',ylim=(0,None));ax.legend(fontsize=8)
    figsave(fig,'08_distance_sensitivity','距離曲線對樣本與大機構有多敏感？','各曲線重新計算相應名冊的可能跨機構配對分母。排除機構是刪除其作者端點，不刪掉含其作者之論文裡其他人的合作。Active依現有名冊狀態，不是歷史年度在職。若200–400公里回升只靠某一大機構，曲線應明顯改變；即使曲線穩定也不是距離本身的因果效果。',['distance_sensitivity'])
    # 9: country-specific persistence with ascertainment and journal sensitivities.
    variants2=[('Clean',ps,countries),('Journal only',sets['journal_clean'],countries),('High OA only',ps,strict)]
    crr=[];fig,axs=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
    for k,(label,ss,cc) in enumerate(variants2):
        ties=recurrence(ss,cc)
        for country in ['CN','US','GB','JP']:
            tt=[t for t in ties if (cc[t['b']] if t['a'] in roster else cc[t['a']])==country and not(t['a'] in roster and t['b'] in roster)]
            crr.append(dict(sample=label,country=country,pairs=len(tt),repeated=sum(t['repeat_within_5_years'] for t in tt),repeat_fraction=np.mean([t['repeat_within_5_years'] for t in tt]) if tt else np.nan))
    tab('country_recurrence',crr)
    for k,label in enumerate(['Clean','Journal only','High OA only']):
        rr=[z for z in crr if z['sample']==label];x=np.arange(4)+(k-1)*.24
        axs[0].bar(x,[z['repeat_fraction'] for z in rr],.23,label=label,color=PALETTE[k])
        for j,z in enumerate(rr):axs[0].text(x[j],z['repeat_fraction']+.01,str(z['pairs']),ha='center',fontsize=8)
    axs[0].set_xticks(range(4),['CN','US','GB','JP']);axs[0].yaxis.set_major_formatter(PCT);axs[0].set(ylabel='Five-year recurrence fraction',title='A  Country-specific recurrence; numbers = pairs',ylim=(0,.86));axs[0].legend(fontsize=8)
    # Concentration: count distinct partners by faculty to check a country dominated by a few egos.
    rr=[]
    for n in sorted(roster):
        for c in ['CN','US']:
            vv=sum(countries[v]==c for v in adj[n]);rr.append(dict(node_id=n,country=c,distinct_partners=vv))
    tab('country_partner_concentration',rr)
    for j,c in enumerate(['CN','US']):
        counts=sorted([v['distinct_partners'] for v in rr if v['country']==c],reverse=True);cum=np.cumsum(counts)/sum(counts)
        axs[1].plot(np.arange(0,len(counts)+1)/len(counts),np.r_[0,cum],label=c,color=PALETTE[j])
    axs[1].plot([0,1],[0,1],'--',color='#999');axs[1].set(xlabel='Fraction of roster researchers (most connected first)',ylabel='Cumulative share of roster-country partner ties',title='B  Is the country link spread across researchers?');axs[1].xaxis.set_major_formatter(PCT);axs[1].yaxis.set_major_formatter(PCT);axs[1].legend()
    figsave(fig,'09_country_persistence','國別差異：接觸廣度、關係重現與少數人的影響','左圖同圖7的五年追蹤，依海外國別分開；數字為配對數，小樣本不作排序推論。High OA只保留高信心且無review flag者的國別，其餘轉未知。右圖CN／US各自把520位教師依該國夥伴數排序；每位教師—外部作者配對算一次，同一外部作者可連多位教師。集中曲線不是全國研究者分布。',['country_recurrence','country_partner_concentration','country_ranking_sensitivity'])
    cn_counts={n:sum(countries[v]=='CN' for v in adj[n]) for n in roster}
    top_cn=max(cn_counts,key=cn_counts.get);country_audit=[]
    for label,removed,cc in [('All observed',set(),countries),('Exclude largest CN ego',{top_cn},countries),('High OA only',set(),strict)]:
        nodes=collections.defaultdict(set)
        for n in roster-removed:
            for v in adj[n]:
                if cc[v] not in ('','TW'):nodes[cc[v]].add(v)
        for c in ['CN','US']:country_audit.append(dict(sample=label,country=c,distinct_partners=len(nodes[c])))
    tab('country_ranking_sensitivity',country_audit)
    facts['country_ranking_sensitivity']=country_audit
    facts['largest_CN_ego']=dict(node_id=top_cn,distinct_CN_partners=cn_counts[top_cn],share_of_roster_CN_pairs=cn_counts[top_cn]/sum(cn_counts.values()))

    facts['country_recurrence']=crr

    facts['international_sensitivity']=sensitivity;facts['recurrence']=repeat
    (OUT/'summary.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2))
    assert all(hashlib.sha256((FINAL/path).read_bytes()).hexdigest()==h for path,h in hashes.items())
    (OUT/'source_hashes.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2))
    # Standalone report with local scientific figures and numerical tables.
    blocks=[]
    for name,title,caption,tables in sections:
        ts=''.join(f'<details><summary>{html.escape(t)}</summary><a href="tables/{t}.csv">CSV</a><div class="table">'+pd.read_csv(OUT/'tables'/f'{t}.csv').head(100).to_html(index=False,float_format=lambda x:f'{x:.3f}')+'</div></details>' for t in tables if t not in ['tie_followup','author_geography'])
        blocks.append(f'<section id="{name}"><h2>{html.escape(title)}</h2><a href="figures/{name}.svg"><img src="figures/{name}.png" alt="{html.escape(title)}"></a><p>{html.escape(caption)}</p>{ts}</section>')
    links=''.join(f'<a href="#{n}">{html.escape(t)}</a>' for n,t,_,_ in sections)
    body='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Geography & collaboration atlas</title><style>body{font:16px/1.7 system-ui,sans-serif;color:#203447;background:#f4f6f8;margin:0}main{max-width:1150px;margin:auto;padding:30px}section{background:white;padding:25px;margin:26px 0;border-radius:10px}h1{font-size:30px}h2{font-size:23px}img{width:100%;height:auto}nav{display:flex;gap:12px;flex-wrap:wrap}a{color:#17668c}.table{overflow:auto}table{border-collapse:collapse;font-size:13px}th,td{padding:7px;border-bottom:1px solid #ddd;white-space:nowrap}details{margin:12px 0}summary{cursor:pointer}p{max-width:95ch}.note{background:#fff0d9;padding:18px}li{margin:8px 0}</style><main><h1>Geography & collaboration：先看已知特徵</h1><p>2015–2024；520位名冊研究者；27個機構單位。主樣本4058篇，排除作者名單不完整、截斷或年份含糊紀錄。所有結論限於這份名冊及蒐集到的成果。</p><p class="note">「國外」以現有affiliation的TW以外國別／地區碼辨識，不是國籍，也未必是發表當年位置。未知作者不算國內。灰／藍色缺漏範圍不是信賴區間。這份圖集不做新穎性宣稱或因果推論。</p><nav>'''+links+'</nav><section><h2>這輪先保留的觀察</h2><p>國內200–400公里的合作機率高於100–200公里，期刊、現役與排除台大／中研院時仍有回升；但長距離邊量接近degree-preserving基準，不能直接解讀為偏好遠距離。</p><p>中國大陸夥伴的名冊連線36.7%集中在一位教師；排除其ego後，CN／US不同夥伴數從271／252變成171／251。國別總量對少數人的影響敏感。</p><p>美國／中國大陸五年合作重現比例在主樣本約41.6%／32.5%，期刊子集則29.7%／29.8%。高OA辨識子集也大幅改變重現率，可能含辨識選擇性；不保留美國合作較持久的結論。</p><p><a href="FINDINGS.md">完整判讀與限制</a></p></section>'+''.join(blocks)+'''<section><h2>文獻對照與未能測量的特徵</h2><p>這些是文獻常用的描述軸，不表示每個關係都應該在此樣本成立。</p><ul><li><a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC3509350/">Pan, Kaski & Fortunato (2012)</a>：合作地理、距離與規模基準，對應圖2–4。</li><li><a href="https://www.kellogg.northwestern.edu/faculty/uzzi/ftp/081008%20ScienceExpressVersion%20MUCs.pdf">Jones, Wuchty & Uzzi (2008)</a>：跨校合作、團隊大小及機構階層。對應圖1、3；本資料沒有可直接比較的當年機構地位指標。</li><li><a href="https://web.stanford.edu/~fafchamp/netecon.pdf">Fafchamps, Goyal & van der Leij (2010)</a>：區分新合作與重複合作，對應圖7的描述性追蹤；此處未估其動態模型。</li><li><a href="https://doi.org/10.1016/j.respol.2010.01.012">Hoekman, Frenken & Tijssen (2010)</a>：距離、地域邊界與規模應分開考慮。</li></ul><p>尚不能有效量測：國際作者實際公里距離、發表當年跨境移動、paper-level citation advantage、disruption或novelty。不可拿國家首都補作者座標，或拿生涯h-index替代論文影響力。國內的座標也只按現有機構位置解讀。</p><p>完整數值保留在tables。作者與配對表可能超過畫面100列，請讀CSV。主程式：../code/geography_atlas.py；固定random seed，來源雜湊見source_hashes.json。</p></section></main></html>'''
    (OUT/'index.html').write_text(body)
    print(json.dumps(facts,ensure_ascii=False,indent=2));print('Source CSV hashes unchanged:',len(hashes))

if __name__=='__main__':main()
