import unittest,tempfile,subprocess,collections,itertools
from pathlib import Path
import numpy as np
import pandas as pd
from research_spatial_concentration import distance_matrix,diagnostics,CODE
class SpatialResearchTests(unittest.TestCase):
    def test_distances_and_bin_boundaries(self):
        d=distance_matrix([0,0],[0,1]);self.assertAlmostEqual(d[0,1],111.1949266,places=5)
        np.testing.assert_allclose(d,d.T);self.assertEqual(d[0,0],0)
        np.testing.assert_array_equal(np.searchsorted([0,10,25,50],[0,9.99,10,25],side='right')-1,[0,0,1,2])
    def test_parent_merge_removes_internal_opportunities(self):
        unit=[0,1,2,3];parent=[0,0,1,2]
        u=sum(unit[a]!=unit[b] for a,b in itertools.combinations(range(4),2))
        p=sum(parent[a]!=parent[b] for a,b in itertools.combinations(range(4),2))
        self.assertEqual((u,p),(6,5))
    def test_diagnostic_detects_between_chain_disagreement(self):
        rng=np.random.default_rng(3);x=rng.normal(size=(4,1000))
        self.assertLess(diagnostics(x)['split_rhat'],1.02)
        x[0]+=5;self.assertGreater(diagnostics(x)['split_rhat'],1.1)
    def test_switch_sampler_against_enumerated_matchings(self):
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);exe=t/'switch';subprocess.run(['c++','-O2','-std=c++17',str(CODE/'spatial_switch.cpp'),'-o',str(exe)],check=True)
            for parent,expected in [([0,1,2,3],2/3),([0,0,1,1],1.)]:
                near={(0,2),(2,0),(1,3),(3,1)};bm=[0 if (a,b) in near else 1 for a in range(4) for b in range(4)]
                (t/'meta').write_text('4\n'+' '.join(map(str,parent))+'\n'+' '.join(map(str,bm)))
                (t/'edges').write_text('2\n0 2\n1 3\n')
                subprocess.run([str(exe),str(t/'meta'),str(t/'edges'),str(t/'out'), '4','2000','200','10','32',str(t/'final')],check=True)
                a=pd.read_csv(t/'out');self.assertAlmostEqual(a.b0.mean(),expected,delta=.06)
                self.assertTrue(((a.b0+a.b1)==2).all())
                for _,g in pd.read_csv(t/'final').groupby('chain'):
                    self.assertEqual(collections.Counter(list(g.a)+list(g.b)),collections.Counter([0,1,2,3]))
                    self.assertTrue(all(parent[a]!=parent[b] for a,b in zip(g.a,g.b)))
if __name__=='__main__':unittest.main()
