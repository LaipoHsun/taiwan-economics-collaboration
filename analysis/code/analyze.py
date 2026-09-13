#!/usr/bin/env python3
"""Read-only exploratory network analyses. Outputs stay inside final_plan/analysis.
Run: python3 final_plan/analysis/code/analyze.py --reps 499 --seed 20270910
No network access and no imports/execution of the source-data pipeline.
"""
from pathlib import Path
import argparse, collections, hashlib, itertools, json, math, os, platform, random, sys, time
BASE = Path(__file__).resolve().parents[1]
FINAL = BASE.parent
os.environ.setdefault('MPLCONFIGDIR', str(BASE / '.mplconfig'))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

PALETTE = ['#2878A0', '#D76B45', '#419884', '#8B76AD', '#C8A34E', '#84919C']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':12,
                     'axes.labelsize':10,'axes.spines.top':False,'axes.spines.right':False,
                     'figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white',
                     'svg.fonttype':'none'})

def log(s): print(s, flush=True)
def read(rel): return pd.read_csv(FINAL / rel, dtype=str, keep_default_na=False)
def arr(x): return json.loads(x or '[]')
def pair(a,b): return (a,b) if a<b else (b,a)
def table(name, rows):
    frame=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(BASE/'tables'/f'{name}.csv',index=False)
    return frame

def savefig(fig,name,caption):
    fig.savefig(BASE/'figures'/f'{name}.png',dpi=180,bbox_inches='tight')
    fig.savefig(BASE/'figures'/f'{name}.svg',bbox_inches='tight')
    plt.close(fig)
    (BASE/'figures'/f'{name}.caption.txt').write_text(caption+'\n')

def graph_stats(edges, roster, universe=None, removed=()):
    """Connectivity denominator always all roster nodes, including inactive/isolates."""
    removed=set(removed)
    nodes=set(universe or roster)|set(roster)
    if universe is None:
        nodes.update(itertools.chain.from_iterable(edges))
    nodes-=removed
    order=sorted(nodes); idx={n:i for i,n in enumerate(order)}
    kept=[(idx[a],idx[b]) for a,b in edges if a in idx and b in idx]
    if kept:
        a,b=np.array(kept).T
        g=coo_matrix((np.ones(len(a)*2),(np.r_[a,b],np.r_[b,a])),shape=(len(nodes),len(nodes))).tocsr()
        _,labels=connected_components(g,directed=False)
    else: labels=np.arange(len(nodes))
    c=collections.Counter(labels[idx[n]] for n in roster if n in idx)
    reachable=sum(v*(v-1)//2 for v in c.values())
    return {'roster_lcc':max(c.values(),default=0),'reachable_roster_pairs':reachable,
            'reachable_fraction':reachable/(len(roster)*(len(roster)-1)/2),
            'roster_components':len(c),'visible_nodes':len(nodes),'edges':len(kept)}

def adjacency(edges):
    g=collections.defaultdict(set)
    for a,b in edges:g[a].add(b);g[b].add(a)
    return g

def triangles(edges):
    g=adjacency(edges); out=set()
    for a in sorted(g):
        for b in g[a]:
            if b>a:
                out.update((a,b,c) for c in g[a]&g[b] if c>b)
    return out

def projections(papers,roster_only=None):
    edges=set(); supported=set()
    for p in papers:
        ids=sorted(set(p['ids']) if roster_only is None else set(p['ids'])&roster_only)
        edges.update(itertools.combinations(ids,2));supported.update(itertools.combinations(ids,3))
    return edges,supported

def empirical(observed,samples,tail='upper'):
    x=np.asarray(samples,dtype=float)
    upper=(np.count_nonzero(x>=observed)+1)/(len(x)+1)
    lower=(np.count_nonzero(x<=observed)+1)/(len(x)+1)
    p_value=upper if tail=='upper' else lower if tail=='lower' else min(1.0,2*min(upper,lower))
    return {'observed':float(observed),'null_mean':float(x.mean()),'null_sd':float(x.std(ddof=1)),
            'null_q025':float(np.quantile(x,.025)),'null_q975':float(np.quantile(x,.975)),
            'p_mc':float(p_value),'p_upper':float(upper),'p_lower':float(lower),'p_two_sided':float(min(1.0,2*min(upper,lower))),'n_randomizations':len(x),'tail':tail}

def rewire(edges,rng,nswap,inst=None):
    """Symmetric switch proposals; fixed attempt count avoids accepted-step jump-chain bias."""
    el=list(sorted(edges));es=set(el);accepted=0
    if len(el)<2:return es,0
    for _ in range(nswap):
        i,j=rng.sample(range(len(el)),2);a,b=el[i];c,d=el[j]
        if rng.random()<.5:a,b=b,a
        if rng.random()<.5:c,d=d,c
        if len({a,b,c,d})!=4:continue
        if inst is not None and inst[a]!=inst[c]:continue
        ad,cb=pair(a,d),pair(c,b)
        if ad in es or cb in es:continue
        es.remove(el[i]);es.remove(el[j]);es.add(ad);es.add(cb)
        el[i],el[j]=ad,cb;accepted+=1
    return es,accepted

def clean(p):return p['complete'] and not p['ambiguous'] and not p['truncated']

def load():
    frames={k:read(v) for k,v in {'master':'professor_demo/authors_master.csv',
        'inactive':'professor_demo/professors_inactive.csv','papers':'paper/papers_all.csv',
        'projects':'project/projects_all.csv','pubedges':'network/paper_network_edges.csv',
        'grantedges':'network/project_network_edges.csv','insts':'map/institutions.csv'}.items()}
    master={r['node_id']:r for r in frames['master'].to_dict('records')}
    roster={n for n,r in master.items() if r['node_type']=='roster'}|set(frames['inactive'].teacher_id)
    inst={n:r['institution_code'] for n,r in master.items() if n in roster}
    inst.update(dict(zip(frames['inactive'].teacher_id,frames['inactive'].institution_code)))
    papers=[]
    for r in frames['papers'].to_dict('records'):
        papers.append({'id':r['paper_id'],'year':int(r['year']),'ids':arr(r['author_node_ids_json']),
            'eligible':r['edge_eligible']=='1','complete':r['author_list_complete']=='1',
            'ambiguous':r['year_ambiguous']=='1','truncated':'只取前' in r['decision_notes'],
            'journal':r['pub_category']=='期刊論文'})
    assert len(roster)==len(set(inst))
    assert all(set(p['ids'])<=set(master) for p in papers)
    assert all(len(p['ids'])==len(set(p['ids'])) for p in papers)
    expected={pair(r.source_node_id,r.target_node_id) for r in frames['pubedges'].itertuples()}
    assert projections([p for p in papers if p['eligible']])[0]==expected, 'Paper projection disagrees with source edge table'
    return frames,master,roster,inst,papers


def audit(frames,master,roster,papers):
    rows=[]
    for name,df in frames.items():
        for col in df:
            rows.append({'table':name,'field':col,'rows':len(df),'nonempty':int((df[col]!='').sum()),
                         'coverage':float((df[col]!='').mean()),'distinct_nonempty':df.loc[df[col]!='',col].nunique()})
    table('field_inventory',rows)
    yearly=[]
    for y in range(2015,2027):
        ps=[p for p in papers if p['year']==y];gs=frames['grantedges'];g=gs[gs.year==str(y)]
        yearly.append({'year':y,'papers':len(ps),'eligible_papers':sum(p['eligible'] for p in ps),
            'clean_eligible_papers':sum(p['eligible'] and clean(p) for p in ps),
            'paper_roster_authors':len(set().union(*(set(p['ids'])&roster for p in ps))),
            'project_records':int((frames['projects'].year==str(y)).sum()),
            'project_pair_records_strict':int((g.both_recorded_this_year=='1').sum()),
            'project_pair_records_family':len(g)})
    annual=table('annual_coverage',yearly)
    ext=[r for r in master.values() if r['node_type']=='external']
    summary={'roster':len(roster),'active_roster':sum(r['node_type']=='roster' for r in master.values()),
        'external':len(ext),'papers_all':len(papers),'eligible_all':sum(p['eligible'] for p in papers),
        'incomplete_author_lists':sum(not p['complete'] for p in papers),
        'ambiguous_year':sum(p['ambiguous'] for p in papers),'truncated_papers':sum(p['truncated'] for p in papers),
        'external_country_known':sum(bool(r['affil_country']) for r in ext),
        'external_country_missing':sum(not r['affil_country'] for r in ext),
        'external_OA_high_no_review':sum(r['oa_match_confidence']=='high' and r['oa_needs_review']=='0' for r in ext),
        'institutions':len(frames['insts'])}
    fig,ax=plt.subplots(1,2,figsize=(12,4.4),layout='constrained')
    ax[0].plot(annual.year,annual.papers,'o-',label='All publication records',color=PALETTE[0])
    ax[0].plot(annual.year,annual.clean_eligible_papers,'o-',label='Clean + edge eligible',color=PALETTE[2])
    ax[0].axvspan(2025.5,2026.5,color='#e9e9e9');ax[0].set(xlabel='Year',ylabel='Publication records',title='A  Publication coverage; 2026 is partial')
    ax[0].legend(fontsize=8,loc='lower left');ax[0].set_xticks([2015,2018,2021,2024,2026])
    counts=collections.Counter('Unknown' if not r['affil_country'] else 'Taiwan' if r['affil_country']=='TW' else 'Overseas' for r in ext)
    labs=['Taiwan','Overseas','Unknown'];vals=[counts[x] for x in labs]
    bars=ax[1].bar(labs,vals,color=[PALETTE[0],PALETTE[2],PALETTE[5]]);ax[1].bar_label(bars,padding=4)
    ax[1].set(ylabel='Non-roster author nodes',title='B  Country coverage is incomplete');ax[1].set_ylim(0,max(vals)*1.16)
    savefig(fig,'00_data_coverage','All raw publication records by year and external country coverage. 2026 is a partial publication year. Country is a current/static attribution, not historical affiliation.')
    return summary


def topic_a(frames,master,roster,inst,papers,reps,seed):
    rng=random.Random(seed+1)
    ps=[p for p in papers if p['eligible'] and p['year']<=2024]
    P,_=projections(ps,roster)
    gj=frames['grantedges'].to_dict('records')
    def grants(end,strict):return {pair(r['source_node_id'],r['target_node_id']) for r in gj if int(r['year'])<=end and (not strict or r['both_recorded_this_year']=='1')}
    J=grants(2024,True);O=P&J
    observed={'pub_edges':len(P),'grant_edges':len(J),'overlap':len(O),'jaccard':len(O)/len(P|J),
              'grant_overlap_fraction':len(O)/len(J),'pub_overlap_fraction':len(O)/len(P)}
    rows=[]
    for label,E in [('Publications',P),('Joint grants',J),('Union',P|J)]:
        rows.append({'layer':label,**graph_stats(E,roster)})
    table('a_layer_connectivity',rows)
    # independent restarted chains, each with a fixed 40*m proposals; retain rejection self-loops.
    null=[]
    for typ,constraint in [('Degree preserved',None),('Degree + institution mixing',inst)]:
        for rep in range(reps):
            E,accepted=rewire(J,rng,max(1,40*len(J)),constraint)
            assert collections.Counter(itertools.chain.from_iterable(E))==collections.Counter(itertools.chain.from_iterable(J))
            if constraint:
                assert collections.Counter(pair(inst[a],inst[b]) for a,b in E)==collections.Counter(pair(inst[a],inst[b]) for a,b in J)
            null.append({'null':typ,'replicate':rep,'overlap':len(E&P),'accepted_swaps':accepted,
                         'proposals':40*len(J),'edge_retention':len(E&J)/len(J),
                         'union_roster_lcc':graph_stats(P|E,roster)['roster_lcc']})
        log(f'A: finished {typ} null ({reps})')
    nd=table('a_null_distributions',null)
    nullstats={typ:empirical(len(O),sub.overlap) for typ,sub in nd.groupby('null')}
    sens=[]
    for end in [2024,2025]:
        for strict in [True,False]:
            for quality in ['eligible','clean']:
                es,_=projections([p for p in papers if p['eligible'] and p['year']<=end and (quality=='eligible' or clean(p))],roster)
                js=grants(end,strict)
                sens.append({'end_year':end,'grant_definition':'same_year' if strict else 'family_inferred',
                   'papers':quality,'pub_pairs':len(es),'grant_pairs':len(js),'overlap':len(es&js),
                   'grant_overlap_fraction':len(es&js)/len(js),'jaccard':len(es&js)/len(es|js)})
    table('a_sensitivity',sens)
    firstP={};firstJ={}
    for p in ps:
        if p['ambiguous']:continue
        for e in itertools.combinations(sorted(set(p['ids'])&roster),2):firstP[e]=min(firstP.get(e,9999),p['year'])
    for r in gj:
        if int(r['year'])<=2024 and r['both_recorded_this_year']=='1':
            e=pair(r['source_node_id'],r['target_node_id']);firstJ[e]=min(firstJ.get(e,9999),int(r['year']))
    lag=[]
    for e in sorted(firstP.keys()&firstJ.keys()):
        lag.append({'source':e[0],'target':e[1],'first_pub':firstP[e],'first_grant':firstJ[e],
                    'pub_minus_grant_years':firstP[e]-firstJ[e],
                    'left_boundary':firstP[e]==2015 or firstJ[e]==2015})
    ld=table('a_first_observed_lags',lag)
    fig,ax=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    v=[len(P-J),len(O),len(J-P)];labs=['Publication only','Both layers','Grant only']
    bars=ax[0,0].bar(labs,v,color=[PALETTE[0],PALETTE[2],PALETTE[1]]);ax[0,0].bar_label(bars,padding=3);ax[0,0].set(ylabel='Unique roster pairs',title='A  Multiplex overlap, 2015–2024');ax[0,0].set_ylim(0,max(v)*1.16)
    for i,(typ,sub) in enumerate(nd.groupby('null')):
        ax[0,1].hist(sub.overlap,bins=np.arange(nd.overlap.min()-.5,nd.overlap.max()+1.5),alpha=.6,label=typ,color=PALETTE[i])
    ax[0,1].axvline(len(O),color='#202b35',lw=2,label=f'Observed = {len(O)}');ax[0,1].legend(fontsize=8)
    ax[0,1].set(xlabel='Edges shared with publication layer',ylabel='Randomized graphs',title='B  Coupling beyond degree and institution')
    bars=ax[1,0].bar([r['layer'] for r in rows],[100*r['reachable_fraction'] for r in rows],color=[PALETTE[0],PALETTE[1],PALETTE[2]])
    ax[1,0].bar_label(bars,fmt='%.1f%%',padding=3);ax[1,0].set(ylabel='Reachable roster pairs (%)',title='C  Structural complementarity');ax[1,0].set_ylim(0,100)
    lags=ld.pub_minus_grant_years.to_numpy() if len(ld) else np.array([])
    ax[1,1].hist(lags,bins=np.arange(-10.5,11.5),color=PALETTE[3]);ax[1,1].axvline(0,color='#444',lw=1)
    ax[1,1].set(xlabel='First publication year − first grant year',ylabel='Pairs observed in both layers',title='D  Timing is descriptive, not a funding effect')
    savefig(fig,'01_multiplex','Main window 2015–2024. Grants require both researchers to have recorded the project in the same year. Nulls preserve the grant degree sequence, optionally also institution-pair edge counts. Reachability denominator is all 520 roster researchers. Lags condition on observing both layers, exclude ambiguous paper years, and are left-censored.')
    observed.update({'nulls':nullstats,'connectivity':rows,'timing_pairs':len(lag),
        'grant_first':int((ld.pub_minus_grant_years>0).sum()),'pub_first':int((ld.pub_minus_grant_years<0).sum()),
        'same_year':int((ld.pub_minus_grant_years==0).sum()),'left_boundary_pairs':int(ld.left_boundary.sum()),
        'null_acceptance':{k:float((d.accepted_swaps/d.proposals).mean()) for k,d in nd.groupby('null')},
        'null_edge_retention':{k:float(d.edge_retention.mean()) for k,d in nd.groupby('null')}})
    return observed


def topic_b(master,roster,inst,papers,reps,seed):
    rng=np.random.default_rng(seed+2)
    ps=[p for p in papers if p['eligible'] and p['year']<=2024]
    E,_=projections(ps);g=adjacency(E);external=sorted(set(g)-roster)
    def country(n):return master[n]['affil_country']
    def group(n):return 'Unknown' if not country(n) else 'Taiwan' if country(n)=='TW' else 'Overseas'
    groups={k:{n for n in external if group(n)==k} for k in ['Taiwan','Overseas','Unknown']}
    scenarios=[('Roster only',set(roster)),('+ Taiwan external',roster|groups['Taiwan']),
        ('+ Overseas external',roster|groups['Overseas']),('+ Unknown external',roster|groups['Unknown']),
        ('+ All external',set(g)|roster)]
    sc=table('b_boundary_connectivity',[{'scenario':label,**graph_stats(E,roster,universe=nodes)} for label,nodes in scenarios])
    scores=[]
    for n in external:
        ns=sorted(g[n]&roster)
        cross=[(a,b) for a,b in itertools.combinations(ns,2) if inst[a]!=inst[b] and b not in g[a]]
        scores.append({'node_id':n,'country_group':group(n),'country':country(n),'degree':len(g[n]),
             'roster_degree':len(ns),'roster_institutions':len({inst[x] for x in ns}),
             'cross_institution_open_roster_pairs':len(cross),
             'oa_confidence':master[n]['oa_match_confidence'],'oa_needs_review':master[n]['oa_needs_review']})
    sd=table('b_external_brokerage',sorted(scores,key=lambda r:(-r['cross_institution_open_roster_pairs'],-r['degree'],r['node_id'])))
    targeted=list(sd.node_id);bydegree=list(sd.sort_values(['degree','node_id'],ascending=[False,True]).node_id)
    # Remove fractions of all observed external nodes. Scores are fixed at baseline.
    fractions=np.array([0,.005,.01,.02,.05,.10,.20,.30,.50,1.0]);ks=np.unique(np.rint(fractions*len(external)).astype(int))
    raw=[]
    for strategy,order in [('Brokerage',targeted),('Degree',bydegree)]:
        for k in ks:raw.append({'strategy':strategy,'replicate':0,'removed':int(k),**graph_stats(E,roster,removed=order[:k])})
    for rep in range(reps):
        order=rng.permutation(external)
        for k in ks:raw.append({'strategy':'Random','replicate':rep,'removed':int(k),**graph_stats(E,roster,removed=order[:k])})
        if rep and rep%100==0:log(f'B: random removal {rep}/{reps}')
    curve=table('b_removal_simulations',raw)
    # Fairer benchmark: same count of nodes in each log2(full degree) stratum as top 5% brokers.
    k=int(round(.05*len(external)));selected=set(targeted[:k]);buckets=collections.defaultdict(list)
    for n in external:buckets[int(math.log2(max(1,len(g[n]))))].append(n)
    counts=collections.Counter(int(math.log2(max(1,len(g[n])))) for n in selected)
    matched=[]
    for rep in range(reps):
        removed=[]
        for bucket,count in sorted(counts.items()):removed.extend(rng.choice(buckets[bucket],count,replace=False))
        matched.append({'replicate':rep,'removed':k,**graph_stats(E,roster,removed=removed)})
    md=table('b_degree_matched_removals',matched)
    target_stats=graph_stats(E,roster,removed=selected)
    matchstats=empirical(target_stats['reachable_fraction'],md.reachable_fraction,tail='lower')
    sensitivity=[]
    for name,subset,allowed in [
        ('Main 2015–2024',ps,None),('Clean author lists + years',[p for p in ps if clean(p)],None),
        ('Journals only',[p for p in ps if p['journal']],None),
        ('Through 2025',[p for p in papers if p['eligible'] and p['year']<=2025],None),
        ('High-confidence OA external',ps,{n for n in external if master[n]['oa_match_confidence']=='high' and master[n]['oa_needs_review']=='0'})]:
        es,_=projections(subset)
        full=graph_stats(es,roster,universe=(roster|allowed) if allowed is not None else None)
        inside=graph_stats(es,roster,universe=roster)
        sensitivity.append({'sample':name,'papers':len(subset),'roster_only_reachable_fraction':inside['reachable_fraction'],
            'with_external_reachable_fraction':full['reachable_fraction'],
            'gain_percentage_points':100*(full['reachable_fraction']-inside['reachable_fraction']),
            'roster_only_lcc':inside['roster_lcc'],'with_external_lcc':full['roster_lcc']})
    sensitivity=table('b_sensitivity',sensitivity)
    fig,ax=plt.subplots(2,2,figsize=(12,8.4),layout='constrained')
    ax[0,0].barh(sc.scenario,sc.reachable_fraction*100,color=[PALETTE[5],PALETTE[0],PALETTE[2],PALETTE[3],PALETTE[1]])
    ax[0,0].invert_yaxis();ax[0,0].set(xlabel='Reachable roster pairs (%)',title='A  The observed network boundary matters',xlim=(0,100))
    for i,(strategy,sub) in enumerate(curve.groupby('strategy')):
        stats=sub.groupby('removed').reachable_fraction.agg(['mean',lambda x:x.quantile(.025),lambda x:x.quantile(.975)])
        x=100*stats.index/len(external);ax[0,1].plot(x,100*stats['mean'],label=strategy,color=PALETTE[i])
        if strategy=='Random':ax[0,1].fill_between(x,100*stats.iloc[:,1],100*stats.iloc[:,2],alpha=.18,color=PALETTE[i])
    ax[0,1].set(xlabel='External nodes removed (%)',ylabel='Reachable roster pairs (%)',title='B  Structural removal experiment');ax[0,1].legend(fontsize=8)
    ax[1,0].hist(md.reachable_fraction*100,bins=20,color=PALETTE[0],alpha=.8)
    ax[1,0].axvline(target_stats['reachable_fraction']*100,color=PALETTE[1],lw=2,label='Top 5% brokerage removal');ax[1,0].legend(fontsize=8)
    ax[1,0].set(xlabel='Reachable roster pairs after removal (%)',ylabel='Degree-stratified random samples',title='C  Does brokerage add more than degree?')
    ax[1,1].barh(sensitivity['sample'],sensitivity.gain_percentage_points,color=PALETTE[2]);ax[1,1].invert_yaxis()
    ax[1,1].set(xlabel='Gain from external nodes (percentage points)',title='D  Boundary effect sensitivity')
    savefig(fig,'02_boundary_brokers','Connectivity measures only pairs of the 520 roster researchers, even when paths pass through observed external coauthors. Country categories are non-additive induced-subgraph scenarios. Removal uses static baseline brokerage; random bands are central 95% simulation intervals. Degree-matched removal at 5% uses log2 degree strata, not exact degrees. This is a roster-centered observed graph, not a complete world network.')
    return {'external_observed':len(external),'brokers_with_score_positive':int((sd.cross_institution_open_roster_pairs>0).sum()),
        'scenarios':sc.to_dict('records'),'degree_matched_removal':matchstats,'removed_top5pct':k,
        'country_groups':{k:len(v) for k,v in groups.items()},'sensitivity':sensitivity.to_dict('records')}


def incidence_null(papers,roster,rng,proposals_per_slot=12):
    """Switch author-paper incidences within year and roster status. Fixed attempts.
    Each row length, annual author incidence and per-paper roster count remain unchanged.
    """
    members=[list(p['ids']) for p in papers];sets=[set(x) for x in members]
    slots=collections.defaultdict(list)
    for j,p in enumerate(papers):
        for k,n in enumerate(p['ids']):slots[(p['year'],n in roster)].append((j,k))
    accepted=attempted=0
    for key,positions in sorted(slots.items()):
        if len(positions)<2:continue
        for _ in range(proposals_per_slot*len(positions)):
            attempted+=1;(i,a),(j,b)=rng.sample(positions,2)
            x,y=members[i][a],members[j][b]
            if i==j or x==y or x in sets[j] or y in sets[i]:continue
            members[i][a],members[j][b]=y,x;sets[i].remove(x);sets[i].add(y);sets[j].remove(y);sets[j].add(x);accepted+=1
    randomized=[{**p,'ids':ids} for p,ids in zip(papers,members)]
    assert all(len(p['ids'])==len(set(p['ids'])) for p in randomized)
    # Per-paper total/roster counts and per-author annual incidence are exact invariants.
    assert [len(set(p['ids'])&roster) for p in randomized]==[len(set(p['ids'])&roster) for p in papers]
    assert collections.Counter((p['year'],n) for p in randomized for n in p['ids'])==collections.Counter((p['year'],n) for p in papers for n in p['ids'])
    return randomized,accepted,attempted


def topic_c(papers,roster,reps,seed):
    rng=random.Random(seed+3)
    ps=[p for p in papers if p['eligible'] and clean(p) and p['year']<=2024]
    stats=[]
    def triad_stats(sub,subset=None):
        e,support=projections(sub,subset);tri=triangles(e)
        assert support<=tri
        return {'triangles':len(tri),'supported_triangles':len(support),
                'unsupported_triangles':len(tri-support),'supported_fraction':len(support)/len(tri) if tri else None}
    for label,subset in [('All observed authors',None),('Roster only',roster)]:stats.append({'population':label,**triad_stats(ps,subset)})
    st=table('c_triangle_decomposition',stats)
    null=[]
    for rep in range(reps):
        randomized,accepted,attempted=incidence_null(ps,roster,rng)
        for label,subset in [('All observed authors',None),('Roster only',roster)]:
            null.append({'replicate':rep,'population':label,'accepted':accepted,'attempted':attempted,**triad_stats(randomized,subset)})
        if rep%25==0:log(f'C: incidence null {rep}/{reps}')
    nd=table('c_incidence_null',null)
    risk=[];closure_events=[]
    # Each cutoff is a separate descriptive risk set; never pool it as independent trials.
    for cutoff in range(2018,2023):
        hist=[p for p in ps if p['year']<=cutoff];future=[p for p in ps if cutoff<p['year']<=cutoff+2]
        E,S=projections(hist);_,F=projections(future);g=adjacency(E);candidates=set()
        for a,ns in g.items():
            for b,c in itertools.combinations(sorted(ns),2):candidates.add(tuple(sorted((a,b,c))))
        candidates-=S
        grouped=collections.defaultdict(lambda:[0,0])
        for t in candidates:
            nedges=sum(pair(a,b) in E for a,b in itertools.combinations(t,2))
            assert nedges in (2,3)
            kind='Open triangle (3 edges)' if nedges==3 else 'Open wedge (2 edges)'
            if t in F:closure_events.append({'cutoff_year':cutoff,'configuration':kind,'triple':'|'.join(t),'all_roster':set(t)<=roster})
            grouped[(kind,'All observed authors')][0]+=1;grouped[(kind,'All observed authors')][1]+=t in F
            if set(t)<=roster:grouped[(kind,'Roster only')][0]+=1;grouped[(kind,'Roster only')][1]+=t in F
        for (kind,pop),(den,num) in sorted(grouped.items()):
            risk.append({'cutoff_year':cutoff,'future_end':cutoff+2,'history_start':2015,'population':pop,
                         'configuration':kind,'candidate_triples':den,'new_joint_triples':num,'closure_rate':num/den})
    rd=table('c_temporal_closure',risk)
    ce=table('c_temporal_closure_events',closure_events)
    sensitivity=[]
    for name,sub in [('Main clean',ps),('Eligible, incl uncertain',[p for p in papers if p['eligible'] and p['year']<=2024]),
                     ('Clean journals',[p for p in ps if p['journal']]),('Clean through 2025',[p for p in papers if p['eligible'] and clean(p) and p['year']<=2025])]:
        for pop,subset in [('All observed authors',None),('Roster only',roster)]:sensitivity.append({'sample':name,'population':pop,**triad_stats(sub,subset)})
    table('c_sensitivity',sensitivity)
    fig,ax=plt.subplots(1,3,figsize=(15,4.9),layout='constrained')
    x=np.arange(len(st));ax[0].bar(x,st.supported_fraction*100,color=PALETTE[0],label='Joint paper supports triple')
    ax[0].bar(x,(1-st.supported_fraction)*100,bottom=st.supported_fraction*100,color=PALETTE[1],label='Only pairwise support')
    ax[0].set_xticks(x,st.population);ax[0].set(ylabel='Projected triangles (%)',title='A  Pairwise vs joint-paper support');ax[0].legend(fontsize=8,loc='lower left')
    for i,r in st.iterrows():ax[0].text(i,103,f'{r.supported_fraction:.1%} joint; n={r.triangles:,}',ha='center',fontsize=9)
    ax[0].set_ylim(0,115)
    sub=nd[nd.population=='All observed authors'];ob=float(st.iloc[0].supported_fraction)
    ax[1].hist(sub.supported_fraction*100,bins=20,color=PALETTE[2]);ax[1].axvline(ob*100,color=PALETTE[1],lw=2,label=f'Observed: {ob:.1%}');ax[1].legend(fontsize=8)
    ax[1].set(xlabel='Triangles with joint-paper support (%)',ylabel='Randomized incidence graphs',title='B  Annual activity + team-size null')
    for i,(kind,sub) in enumerate(rd[rd.population=='All observed authors'].groupby('configuration')):
        ax[2].plot(sub.cutoff_year,sub.closure_rate*100,'o-',color=PALETTE[i],label=kind)
        for r in sub.itertuples():ax[2].annotate(f'{r.new_joint_triples}/{r.candidate_triples}',(r.cutoff_year,r.closure_rate*100),xytext=(0,8 if i==0 else -13),textcoords='offset points',fontsize=6.5,ha='center')
    ax[2].set(xlabel='History through cutoff year',ylabel='Joint-paper closure in next 2 years (%)',title='C  Temporal team formation');ax[2].legend(fontsize=8)
    ax[2].set_yscale('log');ax[2].set_ylim(.06,25);ax[2].set_ylabel('Joint-paper closure in next 2 years (%, log scale)');ax[2].set_xticks(range(2018,2023))
    savefig(fig,'03_higher_order','Clean means edge eligible, complete author list, unambiguous year and no explicit first-10 truncation. Supported triples may be part of larger author teams. Null preserves each author annual publication incidence, each paper size and roster/external composition. Temporal candidates have 2 or 3 prior dyads but no prior joint paper; labels are closures / candidates. Cutoffs overlap, so rates are descriptive, not independent trials.')
    return {'clean_papers':len(ps),'decomposition':stats,
            'nulls':{r['population']:empirical(r['supported_fraction'],nd.loc[nd.population==r['population'],'supported_fraction'],tail='two-sided') for r in stats},
            'incidence_acceptance':float((nd.accepted/nd.attempted).mean()),'temporal':risk,
            'unique_closed_triples':{k:int(v.triple.nunique()) for k,v in ce.groupby('configuration')}}


def project_type_followup(frames,roster,inst,papers,reps,seed):
    rng=random.Random(seed+4)
    P,_=projections([p for p in papers if p['eligible'] and p['year']<=2024],roster)
    rows=[r for r in frames['grantedges'].to_dict('records') if int(r['year'])<=2024 and r['both_recorded_this_year']=='1']
    groups={'Planning / coordination':[r for r in rows if '推動規劃' in r['grant_category']],
            'Other project types':[r for r in rows if '推動規劃' not in r['grant_category']],
            'General research (subset)':[r for r in rows if '一般研究計畫' in r['grant_category']]}
    summary=[];null=[]
    for label,records in groups.items():
        J={pair(r['source_node_id'],r['target_node_id']) for r in records}
        obs=len(P&J)
        vals=[]
        for rep in range(reps):
            ej,accepted=rewire(J,rng,80*len(J),inst)
            vals.append(len(P&ej));null.append({'project_type':label,'replicate':rep,'overlap':vals[-1],
                'accepted':accepted,'proposals':80*len(J),'edge_retention':len(ej&J)/len(J)})
        st=empirical(obs,vals)
        summary.append({'project_type':label,'grant_pairs':len(J),'overlap':obs,'overlap_fraction':obs/len(J),
                        'families':len({r['project_family_key'] for r in records}),
                        'cross_institution_fraction':sum(inst[a]!=inst[b] for a,b in J)/len(J),**st})
    sd=table('a_project_types_followup',summary);table('a_project_type_null',null)
    fig,ax=plt.subplots(1,2,figsize=(12,4.5),layout='constrained');x=np.arange(len(sd))
    ax[0].bar(x,sd.overlap_fraction*100,color=PALETTE[:3]);ax[0].set_xticks(x,['Planning /\ncoordination','Other types','General research\n(subset)'])
    ax[0].set(ylabel='Project pairs also coauthoring (%)',title='A  Coupling differs by project category',ylim=(0,70))
    for i,r in sd.iterrows():ax[0].text(i,r.overlap_fraction*100+2,f'{r.overlap}/{r.grant_pairs}',ha='center')
    for i,r in sd.iterrows():
        mean=100*r.null_mean/r.grant_pairs;lo=100*r.null_q025/r.grant_pairs;hi=100*r.null_q975/r.grant_pairs
        ax[1].errorbar(mean,i,xerr=[[mean-lo],[hi-mean]],fmt='o',color=PALETTE[0],capsize=4)
        ax[1].scatter(r.overlap_fraction*100,i,marker='D',color=PALETTE[1],zorder=3)
    ax[1].set_yticks(x,sd.project_type);ax[1].invert_yaxis();ax[1].set(xlabel='Project pairs also coauthoring (%)',title='B  Degree + institution-mixing null')
    ax[1].plot([],[],'o',color=PALETTE[0],label='Null mean / central 95%');ax[1].plot([],[],'D',color=PALETTE[1],label='Observed');ax[1].legend(fontsize=8,loc='upper center',bbox_to_anchor=(.5,-.18),ncol=2)
    savefig(fig,'04_project_types','Follow-up prompted by the first audit, not a pre-specified confirmatory test. Categories refer to grant_category strings. General research is a subset of Other, and a researcher pair can occur in both Planning and Other. Nulls preserve within-category degree sequences and institution mixing; they do not preserve project-team incidence. Intervals are simulation intervals, not confidence intervals for population effects.')
    return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--reps',type=int,default=499);ap.add_argument('--seed',type=int,default=20270910)
    args=ap.parse_args();assert args.reps>=2
    for d in ['tables','figures']: (BASE/d).mkdir(exist_ok=True)
    files=[p for folder in ['paper','project','network','professor_demo','map'] for p in (FINAL/folder).glob('*.csv')]
    hashes={str(p.relative_to(FINAL)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    frames,master,roster,inst,papers=load();log('Loaded source data')
    start=time.time();result={'settings':{'seed':args.seed,'reps':args.reps,'main_years':[2015,2024],'sensitivity_end':2025},'audit':audit(frames,master,roster,papers)}
    result['A']=topic_a(frames,master,roster,inst,papers,args.reps,args.seed)
    result['B']=topic_b(master,roster,inst,papers,args.reps,args.seed)
    result['project_type_followup']=project_type_followup(frames,roster,inst,papers,args.reps,args.seed)
    result['C']=topic_c(papers,roster,args.reps,args.seed)
    assert all(hashlib.sha256((FINAL/p).read_bytes()).hexdigest()==h for p,h in hashes.items()),'Source data changed during analysis'
    result['provenance']={'source_sha256':hashes,'source_files_unchanged':len(hashes),'python':sys.version,
        'platform':platform.platform(),'numpy':np.__version__,'pandas':pd.__version__,'matplotlib':matplotlib.__version__,
        'elapsed_seconds':time.time()-start}
    (BASE/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    log(f'Completed in {time.time()-start:.1f}s; source files unchanged: {len(hashes)}')

if __name__=='__main__':main()
