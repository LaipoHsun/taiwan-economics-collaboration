#!/usr/bin/env python3
"""Exploratory spatial decomposition of multiplex overlap, not a causal test."""
from analyze import *

def main():
    f,m,r,inst,p=load();geo=f['insts'].set_index('institution_code').to_dict('index')
    rows=[]
    for name,cs,clean_only,other in [('city_all',{'臺北市'},False,False),('city_clean',{'臺北市'},True,False),('city_other_projects',{'臺北市'},True,True),('metro_clean',{'臺北市','新北市'},True,False)]:
        core={n for n in r if geo[inst[n]]['county'] in cs}
        pub=projections([x for x in p if x['eligible'] and 2015<=x['year']<=2024 and (not clean_only or clean(x))],r)[0]
        grant={pair(x.source_node_id,x.target_node_id) for x in f['grantedges'].itertuples() if x.both_recorded_this_year=='1' and 2015<=int(x.year)<=2024 and (not other or '推動規劃' not in x.grant_category)}
        group=lambda e: int(e[0] in core)+int(e[1] in core)
        rng=random.Random(20270911); state,acc=rewire(grant,rng,100*len(grant),inst); samples=[]
        for _ in range(499):
            state,acc=rewire(state,rng,20*len(grant),inst)
            assert collections.Counter(itertools.chain.from_iterable(state))==collections.Counter(itertools.chain.from_iterable(grant))
            assert collections.Counter(pair(inst[a],inst[b]) for a,b in state)==collections.Counter(pair(inst[a],inst[b]) for a,b in grant)
            samples.append(collections.Counter(group(e) for e in state&pub))
        for k,label in [(2,'Within Taipei'),(1,'Taipei-outside'),(0,'Outside-outside')]:
            pe=sum(group(e)==k for e in pub);ge=sum(group(e)==k for e in grant);oe=sum(group(e)==k for e in grant&pub)
            x=np.array([s[k] for s in samples]);rows.append({'config':name,'group':label,'paper_pairs':pe,'project_pairs':ge,'overlap_pairs':oe,'fraction_project_pairs_also_coauthors':oe/ge if ge else None,'null_overlap_mean':x.mean(),'null_q025':np.quantile(x,.025),'null_q975':np.quantile(x,.975)})
    df=table('spatial_overlap',rows); print(df.to_string(index=False))
    fig,axes=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
    mainrows=[x for x in rows if x['config']=='city_all']; xx=np.arange(3)
    axes[0].bar(xx,[x['project_pairs'] for x in mainrows],color=PALETTE[0],label='Recorded project pairs')
    axes[0].bar(xx,[x['overlap_pairs'] for x in mainrows],color=PALETTE[1],label='Also observed as coauthors')
    for j,x in enumerate(mainrows): axes[0].text(j,x['project_pairs']+1,f"{x['overlap_pairs']}/{x['project_pairs']}",ha='center')
    axes[0].set(ylabel='Distinct author pairs',title='Volume and overlap are different quantities');axes[0].legend(fontsize=8)
    for j,x in enumerate(mainrows):
        mu=x['null_overlap_mean'];axes[1].errorbar(j,mu,yerr=[[mu-x['null_q025']],[x['null_q975']-mu]],fmt='o',color=PALETTE[0],capsize=5,label='Conditional null (95% interval)' if j==0 else None)
    axes[1].scatter(xx,[x['overlap_pairs'] for x in mainrows],color=PALETTE[1],marker='D',label='Observed',zorder=4)
    axes[1].set(ylabel='Overlapping author pairs',title='Preserving degrees and institution mixing');axes[1].legend(fontsize=8)
    for ax in axes:ax.set_xticks(xx,[x['group'] for x in mainrows]);ax.set_ylim(bottom=0)
    savefig(fig,'06_spatial_overlap','2015–2024, 520 roster researchers; current institution locations; Taipei City is an exogenous geographical label, not an inferred network core. Project edges require both researchers recorded in the same year. Co-occurrence across the aggregate period is not project-to-paper conversion. Null rewires project edges while fixing author degrees and institution-pair counts; paper network fixed. Intervals from 499 MCMC draws are descriptive, without convergence diagnostics or multiplicity correction. Does not preserve project teams or project types; see sensitivity table.')
if __name__=='__main__':main()
