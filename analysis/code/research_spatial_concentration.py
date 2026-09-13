#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only spatial collaboration analysis. Run with system Python + C++ compiler.
Outputs: ../spatial_concentration. Reuses source loading/validation from analyze.py.
"""
from analyze import *
import subprocess, tempfile
from scipy.stats import rankdata, norm
CODE=Path(__file__).resolve().parent;OUT=BASE/'spatial_concentration'
for folder in [OUT,OUT/'tables',OUT/'figures',OUT/'diagnostics',OUT/'cache']:folder.mkdir(exist_ok=True)
CFG=json.loads((CODE/'spatial_concentration_config.json').read_text())
LABELS=['<10','10–25','25–50','50–100','100–200','200–400','400+']

def distance_matrix(lat,lon):
    a=np.radians(np.asarray(lat));b=np.radians(np.asarray(lon))
    h=np.sin((a[:,None]-a[None,:])/2)**2+np.cos(a[:,None])*np.cos(a[None,:])*np.sin((b[:,None]-b[None,:])/2)**2
    return 12742*np.arcsin(np.sqrt(np.clip(h,0,1)))

def diagnostics(x):
    """Split-Rhat and simple initial-positive-pair ESS; no convergence proof."""
    x=np.asarray(x,float);c,s=x.shape
    if np.var(x)==0:return dict(split_rhat=1.0,ess=float(c*s),lag1=0.0,constant=True)
    half=s//2;split=np.concatenate([x[:,:half],x[:,-half:]],axis=0)
    w=np.mean(np.var(split,axis=1,ddof=1));between=half*np.var(split.mean(1),ddof=1)
    rhat=math.sqrt(((half-1)/half*w+between/half)/w) if w>0 else float('inf')
    centered=x-x.mean(1,keepdims=True);den=(centered**2).sum();acf=[]
    for lag in range(1,min(s//2,200)):
        acf.append(float((centered[:,:-lag]*centered[:,lag:]).sum()/den*s/(s-lag)))
    pos=0.
    for j in range(0,len(acf)-1,2):
        pair_sum=acf[j]+acf[j+1]
        if pair_sum<=0:break
        pos+=pair_sum
    return dict(split_rhat=rhat,ess=min(float(c*s),float(c*s/(1+2*pos))),lag1=acf[0],constant=False)

def save_table(name,rows):
    df=pd.DataFrame(rows);df.to_csv(OUT/'tables'/f'{name}.csv',index=False);return df

def degree_bins(deg):return np.searchsorted(CFG['matched_degree_bins'],deg,side='right')-1

def run_null(tag,es,parent,bmat,chains=None,draws=None):
    chains=chains or CFG['chains'];draws=draws or CFG['draws_per_chain']
    key=hashlib.sha256(parent.tobytes()+bmat.tobytes()).hexdigest()[:12];meta=OUT/'cache'/f'meta_{key}.txt'
    if not meta.exists():meta.write_text(str(len(parent))+'\n'+' '.join(map(str,parent))+'\n'+' '.join(map(str,bmat.ravel()))+'\n')
    ep=OUT/'cache'/f'{tag}.edges';ep.write_text(str(len(es))+'\n'+'\n'.join(f'{a} {b}' for a,b in sorted(es)))
    result=OUT/'diagnostics'/f'{tag}_samples.csv';final=OUT/'cache'/f'{tag}_final_edges.csv'
    seed=CFG['seed']+int(hashlib.sha256(tag.encode()).hexdigest()[:7],16)
    subprocess.run([str(OUT/'cache'/'spatial_switch'),str(meta),str(ep),str(result),str(chains),str(draws),str(CFG['burn_sweeps']),str(CFG['spacing_sweeps']),str(seed),str(final)],check=True)
    df=pd.read_csv(result);target=collections.Counter(itertools.chain.from_iterable(es))
    # C++ also asserts degree and allowed-edge conditions at EVERY saved draw.
    for _,g in pd.read_csv(final).groupby('chain'):
        ee={pair(int(a),int(b)) for a,b in zip(g.a,g.b)}
        assert len(ee)==len(es) and collections.Counter(itertools.chain.from_iterable(ee))==target
        assert all(a!=b and parent[a]!=parent[b] for a,b in ee)
    return df

def main():
    start=time.time();sourcefiles=[p for p in FINAL.rglob('*.csv') if BASE not in p.parents]
    hashes={str(p.relative_to(FINAL)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sourcefiles}
    subprocess.run(['c++','-O3','-std=c++17',str(CODE/'spatial_switch.cpp'),'-o',str(OUT/'cache'/'spatial_switch')],check=True)
    f,master,roster,inst,papers=load();nodes=sorted(roster);idx={n:j for j,n in enumerate(nodes)};n=len(nodes)
    geo=f['insts'].set_index('institution_code').to_dict('index')
    raw=pd.read_csv(FINAL/'basemap copy/institutions copy.csv',dtype=str).fillna('').set_index('機構代碼').to_dict('index')
    pmap={i:CFG['parent_overrides'].get(i,i) for i in geo};parents=sorted(set(pmap.values()));units=sorted(geo)
    parent=np.array([parents.index(pmap[inst[a]]) for a in nodes],dtype=int)
    unit=np.array([units.index(inst[a]) for a in nodes],dtype=int)
    lat=np.array([float(raw[inst[a]]['緯度lat_原始']) for a in nodes]);lon=np.array([float(raw[inst[a]]['經度lon_原始']) for a in nodes])
    distance=distance_matrix(lat,lon);displaydistance=distance_matrix([float(geo[inst[a]]['lat']) for a in nodes],[float(geo[inst[a]]['lon']) for a in nodes])
    bins=np.searchsorted(CFG['distance_edges_km'],distance,side='right')-1;displaybins=np.searchsorted(CFG['distance_edges_km'],displaydistance,side='right')-1
    tri=np.triu(np.ones((n,n),bool),1)
    mapping=[]
    for i in units:
        mapping.append(dict(unit=i,parent=pmap[i],name=geo[i]['institution_name'],county=geo[i]['county'],roster=sum(inst[a]==i for a in nodes),display_lat=geo[i]['lat'],display_lon=geo[i]['lon'],raw_lat=raw[i]['緯度lat_原始'],raw_lon=raw[i]['經度lon_原始'],source_jitter=raw[i]['是否jitter'],address=raw[i]['地址']))
    save_table('organization_audit',mapping)
    cleanps=[p for p in papers if p['eligible'] and clean(p) and CFG['years'][0]<=p['year']<=CFG['years'][1]]
    projected=lambda ps:{(idx[a],idx[b]) for a,b in projections(ps,roster)[0]}
    base_edges=projected(cleanps);mainedges={e for e in base_edges if parent[e[0]]!=parent[e[1]]}
    degree=np.bincount(np.array(sorted(mainedges)).ravel(),minlength=n)
    active={idx[a] for a in nodes if a in master and master[a]['node_type']=='roster'}
    publishing={idx[a] for p in cleanps for a in p['ids'] if a in roster}
    case_rows=[];distance_rows=[];diag_rows=[];case_graphs={};near_pair_rows=[]
    def calculate(tag,es,ns,par=parent,bm=bins,kind='sensitivity',chains=None,draws=None):
        kept={e for e in es if e[0] in ns and e[1] in ns and par[e[0]]!=par[e[1]]}
        mask=np.zeros(n,bool);mask[list(ns)]=True;allowed=tri&(par[:,None]!=par[None,:])&mask[:,None]&mask[None,:]
        opp=np.bincount(bm[allowed],minlength=7);obs=np.bincount([bm[a,b] for a,b in kept],minlength=7)
        assert obs.sum()==len(kept) and (obs<=opp).all()
        m0=len(kept)*opp/opp.sum() if opp.sum() else np.zeros(7)
        sims=run_null(tag,kept,par,bm,chains,draws);sim=sims[[f'b{j}' for j in range(7)]].to_numpy()
        rr=dict(case=tag,kind=kind,nodes=len(ns),edges=len(kept),possible_pairs=int(opp.sum()))
        for j in range(3):
            o=int(obs[:j+1].sum());op=int(opp[:j+1].sum());e0=float(m0[:j+1].sum());xx=sim[:,:j+1].sum(1);e1=float(xx.mean())
            rr.update({f'obs_{j}':o,f'opp_{j}':op,f'rate_{j}':o/op if op else np.nan,f'm0_{j}':e0,f'm1_{j}':e1,f'ratio0_{j}':o/e0 if e0 else np.nan,f'ratio1_{j}':o/e1 if e1 else np.nan,f'null_q025_{j}':float(np.quantile(xx,.025)),f'null_q975_{j}':float(np.quantile(xx,.975))})
            shape=(int(sims.chain.max())+1,int(sims.draw.max())+1);dg=diagnostics(xx.reshape(shape));diag_rows.append(dict(case=tag,metric=f'lt{CFG["thresholds_km"][j]}',**dg,acceptance=float(sims.accepted.sum()/sims.attempts.sum())))
        for j in range(7):distance_rows.append(dict(case=tag,bin=LABELS[j],observed=int(obs[j]),possible=int(opp[j]),probability=obs[j]/opp[j] if opp[j] else np.nan,m0=m0[j],m1=sim[:,j].mean(),q025=np.quantile(sim[:,j],.025),q975=np.quantile(sim[:,j],.975)))
        case_rows.append(rr)
        if kind!='matched':case_graphs[tag]=dict(edges=sorted(kept),nodes=sorted(ns))
        return rr
    allnodes=set(range(n));asnodes={idx[a] for a in nodes if pmap[inst[a]]=='AS'}
    calculate('main',base_edges,allnodes,kind='main');log('Main parent/raw-coordinate null complete')
    specs=[('units_display',base_edges,allnodes,unit,displaybins),('units_raw',base_edges,allnodes,unit,bins),('parent_display',base_edges,allnodes,parent,displaybins),
      ('journal',projected([p for p in cleanps if p['journal']]),allnodes,parent,bins),('active',base_edges,active,parent,bins),('publishing',base_edges,publishing,parent,bins),
      ('two_roster',projected([p for p in cleanps if len(set(p['ids'])&roster)==2]),allnodes,parent,bins),
      ('early',projected([p for p in cleanps if p['year']<=2019]),allnodes,parent,bins),('late',projected([p for p in cleanps if p['year']>=2020]),allnodes,parent,bins),
      ('through2025',projected([p for p in papers if p['eligible'] and clean(p) and 2015<=p['year']<=2025]),allnodes,parent,bins)]
    for tag,es,ns,par,bm in specs:calculate(tag,es,ns,par,bm);log('Sensitivity '+tag)
    for pp in parents:
        ns={idx[a] for a in nodes if pmap[inst[a]]!=pp};calculate('drop_'+pp,base_edges,ns,kind='leave_organization_out');log('Leave out '+pp)
    # Audit short-distance organization pairs, including all possible opportunities.
    pairdata=collections.defaultdict(lambda:dict(possible=0,edges=0))
    for a,b in itertools.combinations(range(n),2):
        if parent[a]!=parent[b] and bins[a,b]==0:
            key=pair(pmap[inst[nodes[a]]],pmap[inst[nodes[b]]]);pairdata[key]['possible']+=1;pairdata[key]['edges']+=int((a,b) in mainedges)
    for (a,b),v in pairdata.items():near_pair_rows.append(dict(parent_a=a,parent_b=b,**v,probability=v['edges']/v['possible']))
    save_table('near_organization_pairs',near_pair_rows)
    # Matched deletion: bins and total degree, then geographic feasibility (no silent relaxation).
    target=collections.Counter(degree_bins(degree[list(asnodes)]));targetsum=int(degree[list(asnodes)].sum());db=degree_bins(degree);rng=random.Random(CFG['seed'])
    nonas=allnodes-asnodes;taipei={idx[a] for a in nodes if geo[inst[a]]['county']=='臺北市'}-asnodes
    feasibility=[]
    for label,pool in [('national',nonas),('taipei',taipei)]:
        for b,k in sorted(target.items()):feasibility.append(dict(pool=label,degree_bin=int(b),needed=k,available=sum(db[j]==b for j in pool),feasible=sum(db[j]==b for j in pool)>=k))
    save_table('matching_feasibility',feasibility)
    matched=[];removedrows=[];attempts=0
    while len(matched)<CFG['matched_sets'] and attempts<200000:
        attempts+=1;chosen=set()
        for b,k in sorted(target.items()):chosen.update(rng.sample(sorted(j for j in nonas if db[j]==b),k))
        if abs(degree[list(chosen)].sum()-targetsum)>max(1,targetsum*.05):continue
        rep=len(matched);tag=f'match_{rep:03d}';rr=calculate(tag,base_edges,allnodes-chosen,kind='matched',chains=CFG['matched_null_chains'],draws=CFG['matched_null_draws'])
        rr.update(removed_degree_sum=int(degree[list(chosen)].sum()),removed_n=len(chosen),removed_taipei=sum(geo[inst[nodes[j]]]['county']=='臺北市' for j in chosen));matched.append(rr)
        removedrows.extend(dict(rep=rep,node_id=nodes[j],degree=int(degree[j]),degree_bin=int(db[j])) for j in sorted(chosen))
        if rep%50==0:log(f'Matched deletions {rep+1}/{CFG["matched_sets"]}')
    assert len(matched)==CFG['matched_sets'],'Insufficient matched draws'
    save_table('matched_removed_nodes',removedrows)
    save_table('cases',case_rows);save_table('distance_profiles',distance_rows);save_table('chain_diagnostics',diag_rows)
    node_rows=[dict(node_id=a,index=idx[a],unit=inst[a],parent=pmap[inst[a]],lat=lat[idx[a]],lon=lon[idx[a]],degree=int(degree[idx[a]]),name=master.get(a,{}).get('name_zh','')) for a in nodes]
    save_table('nodes',node_rows)
    # Edge provenance lets the report identify dominant institution pairs and author egos.
    edgepapers=collections.defaultdict(list)
    for p in cleanps:
        for a,b in itertools.combinations(sorted(set(p['ids'])&roster),2):
            e=pair(idx[a],idx[b])
            if e in mainedges:edgepapers[e].append(p)
    er=[]
    for (a,b),ps in sorted(edgepapers.items()):er.append(dict(a=nodes[a],b=nodes[b],unit_a=inst[nodes[a]],unit_b=inst[nodes[b]],parent_a=pmap[inst[nodes[a]]],parent_b=pmap[inst[nodes[b]]],distance_km=distance[a,b],papers=len(ps),journal_papers=sum(p['journal'] for p in ps),two_roster_papers=sum(len(set(p['ids'])&roster)==2 for p in ps)))
    save_table('edge_provenance',er)
    manifest=dict(config=CFG,source_sha256=hashes,python=sys.version,numpy=np.__version__,pandas=pd.__version__,elapsed_seconds=time.time()-start,
        matching_attempts=attempts,AS_removed_degree=targetsum,AS_n=len(asnodes),taipei_matching_feasible=all(v['feasible'] for v in feasibility if v['pool']=='taipei'),
        exact_degree_sequence_preserved_every_draw=True,organization_count=len(parents),main_papers=len(cleanps),source_modified=False,
        chain_start='Empirical graph, independent seeded burn-in; mixing diagnostics are not proof of irreducibility')
    assert all(hashlib.sha256((FINAL/path).read_bytes()).hexdigest()==h for path,h in hashes.items())
    manifest['code_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),CODE/'spatial_switch.cpp',CODE/'spatial_concentration_config.json']}
    (OUT/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(OUT/'cache'/'case_graphs.json').write_text(json.dumps(case_graphs))
    log(f'Done: {len(case_rows)} cases; {time.time()-start:.1f}s; all {len(hashes)} source CSV hashes unchanged')
if __name__=='__main__':main()
