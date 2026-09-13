#!/usr/bin/env python3
"""Exploratory geography-conditioned partner concentration; read-only source data.
Run: python3 final_plan/analysis/code/spatial_gateways.py
Null preserves every author's cross-boundary degree and every institutional pair's
edge count, hence exact edge-distance multiset under institutional coordinates.
It does NOT preserve paper teams; a two-roster-author-paper sensitivity is included.
"""
from analyze import *

def incidence(edges, inst):
    contacts=collections.defaultdict(set)
    for p,c in edges: contacts[inst[p]].add(c)
    return {i:len(c) for i,c in contacts.items()}

def signature(edges,inst):
    return (collections.Counter(p for p,c in edges),collections.Counter(c for p,c in edges),
            collections.Counter((inst[p],inst[c]) for p,c in edges))

def sample(edges,inst,rng,attempts):
    e=list(sorted(edges)); s=set(e); accepted=0
    if len(e)<2:return s,accepted
    for _ in range(attempts):
        a,b=rng.sample(range(len(e)),2);p,c=e[a];q,d=e[b]
        if p==q or c==d or inst[c]!=inst[d] or (p,d) in s or (q,c) in s:continue
        s.remove((p,c));s.remove((q,d));s.update(((p,d),(q,c)))
        e[a]=(p,d);e[b]=(q,c);accepted+=1
    return s,accepted

def main():
    paths=list(FINAL.rglob('*.csv')); paths=[p for p in paths if BASE not in p.parents]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frames,master,roster,inst,papers=load()
    geo=frames['insts'].set_index('institution_code').to_dict('index')
    configs=[('city_clean',{'臺北市'},True,False),('city_all',{'臺北市'},False,False),
             ('city_two_roster',{'臺北市'},True,True),('metro_clean',{'臺北市','新北市'},True,False)]
    # Match source spelling explicitly; don't silently classify all nodes as peripheral.
    counties=set(frames['insts'].county); print('Counties:',sorted(counties))
    if '台北市' in counties: configs=[(n,{x.replace('臺','台') for x in cs},cl,t) for n,cs,cl,t in configs]
    summaries=[]; rows=[]; draws=[]
    for name,counties,clean_only,two in configs:
        core={n for n in roster if geo[inst[n]]['county'] in counties}
        assert core and len(core)<len(roster)
        ps=[p for p in papers if p['eligible'] and 2015<=p['year']<=2024 and (not clean_only or clean(p))
            and (not two or len(set(p['ids'])&roster)==2)]
        full=projections(ps,roster)[0]
        edges={(a,b) if b in core else (b,a) for a,b in full if (a in core)!=(b in core)}
        obs=incidence(edges,inst); target=signature(edges,inst); rng=random.Random(20270911)
        state,acc=sample(edges,inst,rng,100*len(edges)); sims=[]; accepted=acc
        for rep in range(499):
            state,acc=sample(state,inst,rng,20*len(edges)); accepted+=acc
            assert signature(state,inst)==target
            vals=incidence(state,inst);sims.append(vals)
            draws.append({'config':name,'rep':rep,'institution_core_author_incidences':sum(vals.values())})
        total=[sum(v.values()) for v in sims]
        result=empirical(sum(obs.values()),total,tail='lower')
        summaries.append({'config':name,'core_roster':len(core),'all_roster':len(roster),'papers':len(ps),
            'cross_boundary_author_pairs':len(edges),'outside_institutions_with_core_ties':len(obs),
            'core_authors_with_outside_ties':len({c for p,c in edges}),'accepted_swaps':accepted,**result})
        for i,v in obs.items():
            x=[s.get(i,0) for s in sims]
            rows.append({'config':name,'institution':i,'name':geo[i]['institution_name'],
                'observed_distinct_core_contacts':v,'null_mean':np.mean(x),'null_q025':np.quantile(x,.025),
                'null_q975':np.quantile(x,.975),'cross_boundary_author_pairs':sum(inst[p]==i for p,c in edges)})
    table('spatial_gateway_summary',summaries); table('spatial_gateway_institutions',rows);table('spatial_gateway_null',draws)
    fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    for ax,name,title in zip(axes,['city_clean','city_two_roster'],['Clean papers','Exactly two roster authors per paper']):
        rr=[r for r in rows if r['config']==name]
        for r in rr:
            x=r['null_mean'];y=r['observed_distinct_core_contacts']
            ax.errorbar(x,y,xerr=[[x-r['null_q025']],[r['null_q975']-x]],fmt='o',color=PALETTE[0],alpha=.8)
            
            if y >= 8: ax.annotate(r['institution'],(x,y),xytext=(3,3),textcoords='offset points',fontsize=7)
        lim=max([r['null_q975'] for r in rr]+[r['observed_distinct_core_contacts'] for r in rr])+3
        ax.plot([0,lim],[0,lim],'--',color='#888888',lw=1)
        ax.set(xlabel='Expected distinct Taipei contacts (conditional null)',ylabel='Observed distinct Taipei contacts',title=title,xlim=(0,lim),ylim=(0,lim))
    savefig(fig,'05_spatial_gateways','2015–2024 roster-only network, Taipei City geographical core. Each dot is one outside institution; labels are institution codes. Horizontal intervals: central 95% of 499 dependent MCMC draws, not confidence intervals. Below diagonal = institution shares fewer distinct Taipei researchers than expected from fixed author cross-boundary degrees and fixed institution-pair counts. Exploratory; current affiliations; no paper-team preservation. Two-roster sensitivity can still include non-roster coauthors.')
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    print(json.dumps(summaries,ensure_ascii=False,indent=2));print('Source CSV hashes unchanged:',len(hashes))

if __name__=='__main__':main()
