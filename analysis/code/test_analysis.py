"""Small independent checks of consequential graph/projection/null definitions."""
import random
import unittest
import analyze as a

class NetworkDefinitions(unittest.TestCase):
    def test_roster_denominator_and_external_bridge(self):
        r={'A','B','C'};e={('A','X'),('B','X')}
        self.assertAlmostEqual(a.graph_stats(e,r)['reachable_fraction'],1/3)
        self.assertEqual(a.graph_stats(e,r,universe=r)['reachable_roster_pairs'],0)
        self.assertEqual(a.graph_stats(e,r,removed={'X'})['roster_lcc'],1)
    def test_triangle_not_equal_to_joint_team(self):
        dyads=[{'ids':['A','B']},{'ids':['B','C']},{'ids':['A','C']}]
        e,s=a.projections(dyads)
        self.assertEqual(len(a.triangles(e)),1);self.assertFalse(s)
        e,s=a.projections([{'ids':['A','B','C','D']}])
        self.assertEqual(len(s),4);self.assertEqual(s,a.triangles(e))
    def test_no_roster_projection_through_external(self):
        e,_=a.projections([{'ids':['A','X']},{'ids':['B','X']}],{'A','B'})
        self.assertEqual(e,set())
    def test_switch_invariants(self):
        e={('A','C'),('B','D'),('A','E'),('B','F')};inst={n:('one' if n in 'AB' else 'two') for n in 'ABCDEF'}
        f,n=a.rewire(e,random.Random(1),1000,inst)
        self.assertEqual(a.collections.Counter(a.itertools.chain.from_iterable(e)),a.collections.Counter(a.itertools.chain.from_iterable(f)))
        self.assertEqual(len(f),4);self.assertGreater(n,0)
    def test_incidence_invariants(self):
        p=[{'ids':['A','X'],'year':2020},{'ids':['B','Y','Z'],'year':2020},{'ids':['A','Z'],'year':2021}]
        q,n,_=a.incidence_null(p,{'A','B'},random.Random(1))
        self.assertEqual([len(x['ids']) for x in q],[2,3,2]);self.assertEqual(q[2],p[2]);self.assertGreater(n,0)
    def test_mc_add_one_and_two_sided(self):
        x=a.empirical(10,[1,2,3],tail='two-sided')
        self.assertEqual(x['p_upper'],.25);self.assertEqual(x['p_mc'],.5)

if __name__=='__main__':unittest.main()
