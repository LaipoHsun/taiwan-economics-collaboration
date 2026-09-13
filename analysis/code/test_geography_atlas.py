import unittest,itertools,math
from geography_atlas import rarefied,frac_summary,dist
class GeographyCalculations(unittest.TestCase):
    def test_rarefaction_matches_enumeration(self):
        labels=['A','A','A','B','B','C','D']
        expected=sum(len(set(x)) for x in itertools.combinations(labels,5))/math.comb(len(labels),5)
        self.assertAlmostEqual(rarefied([3,2,1,1]),expected)
    def test_rarefaction_unavailable_and_limits(self):
        self.assertTrue(math.isnan(rarefied([2,1])))
        self.assertEqual(rarefied([10]),1)
        self.assertEqual(rarefied([1]*10),5)
    def test_country_missingness_not_domestic_or_double_counted(self):
        ps=[{'ids':['r']},{'ids':['r','u']},{'ids':['r','f','u']},{'ids':['r','d']}]
        self.assertEqual(frac_summary(ps,{'r':'TW','u':'','f':'US','d':'TW'}),(4,1,1))
    def test_distance_identical_and_equatorial(self):
        a={'lat':0,'lon':0};b={'lat':0,'lon':1}
        self.assertEqual(dist(a,a),0)
        self.assertAlmostEqual(dist(a,b),111.19492664455873)
        self.assertAlmostEqual(dist(a,b),dist(b,a))
if __name__=='__main__':unittest.main()
