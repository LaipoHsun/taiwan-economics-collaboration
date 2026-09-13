// Symmetric simple-graph degree-preserving switches; rejected attempts remain steps.
// A small accelerator called by research_spatial_concentration.py. No network access.
#include <algorithm>
#include <array>
#include <cassert>
#include <fstream>
#include <iostream>
#include <random>
#include <set>
#include <vector>
int main(int argc,char**argv){
 if(argc!=10){std::cerr<<"meta edges output chains draws burn_sweeps spacing_sweeps seed final_edges\n";return 2;}
 std::ifstream meta(argv[1]),ef(argv[2]);int n,m;meta>>n;std::vector<int>par(n),bin(n*n);
 for(auto &x:par)meta>>x;for(auto &x:bin)meta>>x;ef>>m;
 std::vector<std::pair<int,int>> orig(m);std::vector<int> target(n,0);std::set<int>original;
 for(auto &e:orig){ef>>e.first>>e.second;assert(e.first!=e.second&&par[e.first]!=par[e.second]);target[e.first]++;target[e.second]++;original.insert(std::min(e.first,e.second)*n+std::max(e.first,e.second));}
 assert((int)original.size()==m);int chains=std::stoi(argv[4]),draws=std::stoi(argv[5]),burn=std::stoi(argv[6]),spacing=std::stoi(argv[7]);
 std::ofstream out(argv[3]),final(argv[9]);out<<"chain,draw,b0,b1,b2,b3,b4,b5,b6,accepted,attempts,original_edge_overlap\n";final<<"chain,a,b\n";
 for(int chain=0;chain<chains;chain++){
  std::mt19937_64 rng(std::stoull(argv[8])+104729ULL*chain);auto edges=orig;std::vector<unsigned char>adj(n*n,0);
  for(auto e:edges)adj[e.first*n+e.second]=adj[e.second*n+e.first]=1;
  std::uniform_int_distribution<int> ix(0,std::max(0,m-1));
  for(int draw=-1;draw<draws;draw++){
   int attempts=(draw==-1?burn:spacing)*m,accepted=0;
   if(m>=2)for(int step=0;step<attempts;step++){
    int i=ix(rng),j=ix(rng);if(i==j)continue;auto [a,b]=edges[i];auto[c,d]=edges[j];
    if(rng()&1)std::swap(a,b);if(rng()&1)std::swap(c,d);
    if(a==c||a==d||b==c||b==d||par[a]==par[d]||par[c]==par[b]||adj[a*n+d]||adj[c*n+b])continue;
    adj[a*n+b]=adj[b*n+a]=adj[c*n+d]=adj[d*n+c]=0;
    adj[a*n+d]=adj[d*n+a]=adj[c*n+b]=adj[b*n+c]=1;edges[i]={a,d};edges[j]={c,b};accepted++;
   }
   if(draw<0)continue;
   std::array<int,7> counts{};std::vector<int> degree(n,0);int overlap=0;
   for(auto[a,b]:edges){assert(a!=b&&par[a]!=par[b]);counts[bin[a*n+b]]++;degree[a]++;degree[b]++;overlap+=original.count(std::min(a,b)*n+std::max(a,b));}
   assert(degree==target);out<<chain<<","<<draw;for(int x:counts)out<<","<<x;out<<","<<accepted<<","<<attempts<<","<<overlap<<"\n";
  }
  for(auto[a,b]:edges)final<<chain<<","<<a<<","<<b<<"\n";
 }
}
