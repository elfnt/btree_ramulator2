# Offline model: what can SANITY-only extensions buy on sparse keys? (no simulator, no CRC)
#   range : child keys must lie in [lo,hi) given by the parent's separators; a leaf's first key must equal lo
#   align : keys are known multiples of 2^k -> low k bits must be zero (stride keys only)
#   slack : unused slots of the node hold dummy keys K+1 (right guards), no extra pages
import random
random.seed(7)
ORDER_FILL={253:174, 64:44, 16:11}

def keys(dist,k,n):
    if dist=='stride': return [(i+5000)<<k for i in range(n)]
    g=2**43; x=random.randrange(2**62); out=[]
    for _ in range(n):
        x+=max(3,int(random.expovariate(1.0/g))); out.append(x)
    return out

def leaf_rate(ks,order,k,rng=False,align=False,slack=False):
    fill=ORDER_FILL[order]; det=tot=0
    nodes=[ks[i:i+fill] for i in range(0,len(ks)-2*fill,fill)]
    for ni,nd in enumerate(nodes):
        lo_f=nd[0]; hi_f=ks[(ni+1)*fill]                    # parent's separators around this leaf
        guards=set()
        if slack:
            n_g=order-fill
            guards=set(round(j*fill/n_g) for j in range(n_g)) if n_g<fill else set(range(fill))
        for i,K in enumerate(nd):
            lo=nd[i-1] if i>0 else None
            hi=nd[i+1] if i<len(nd)-1 else None
            if i>0 and (i-1) in guards: lo=nd[i-1]+1         # left neighbour's right guard
            if i in guards and (hi is None or K+1<hi): hi=K+1
            for b in range(64):
                K2=K^(1<<b); tot+=1; d=False
                if (lo is not None and K2<=lo) or (hi is not None and K2>=hi): d=True
                if rng and ((i==0 and K2!=lo_f) or K2<lo_f or K2>=hi_f): d=True
                if align and k>0 and (K2 & ((1<<k)-1)): d=True
                det+=d
    return det/tot

print("LEAF: fraction of single-bit key flips that violate a SANITY rule")
print(f"{'order':>5} {'keys':12}{'SANITY':>8}{'+range':>8}{'+align':>8}{'+slack':>8}{'+range+slack':>13}{'  formula':>9}")
for order in (253,64,16):
    for name,dist,k in [('2^0','stride',0),('2^16','stride',16),('2^32','stride',32),('random64','random64',0)]:
        ks=keys(dist,k,ORDER_FILL[order]*14)
        r=[leaf_rate(ks,order,k), leaf_rate(ks,order,k,rng=True),
           leaf_rate(ks,order,k,align=True) if dist=='stride' and k>0 else float('nan'),
           leaf_rate(ks,order,k,slack=True) if not(dist=='stride' and k==0) else float('nan'),
           leaf_rate(ks,order,k,rng=True,slack=True) if not(dist=='stride' and k==0) else float('nan')]
        f=(64-k)/64 if dist=='stride' else float('nan')
        print(f"{order:>5} {name:12}"+''.join(f"{x:8.3f}" for x in r[:4])+f"{r[4]:13.3f}{f:9.3f}")

print("\nINTERNAL (level 1, order 253): per separator, harmful flips left undetected after the affected child is next visited")
def internal(dist,k,rng):
    fill=174; allk=keys(dist,k,fill*fill); seps=[(allk[j*fill],allk[j*fill-1]) for j in range(1,fill)]
    harm=0
    for i,(S,L) in enumerate(seps):
        lo=seps[i-1][0] if i>0 else None; hi=seps[i+1][0] if i<len(seps)-1 else None
        for b in range(64):
            S2=S^(1<<b)
            if (lo is not None and S2<=lo) or (hi is not None and S2>=hi): continue      # ordering catches it
            bad=(S2>S) or (S2<=L)
            if bad and not rng: harm+=1          # with range check: right child's first key != S2, or left child has keys >= S2
    return harm/len(seps)
for name,dist,k in [('2^0','stride',0),('2^16','stride',16),('2^32','stride',32),('random64','random64',0)]:
    print(f"  {name:10} SANITY {internal(dist,k,False):5.1f}   SANITY+range {internal(dist,k,True):5.1f}")
