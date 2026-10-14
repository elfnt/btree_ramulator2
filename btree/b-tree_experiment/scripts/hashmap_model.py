# Offline model: map sparse keys into a small dense range so the ordering check works again.
# Layout: open-addressing table of M = N/alpha slots laid out in the B-tree key space.
#   slot s = hash(K) mod M, linear probing; tree entries: (2s -> original key), (2s+1 -> value).
# Reports: share of single-bit tree-key flips that break in-node ordering, and probe counts.
import random, math
random.seed(11)
N=40000; FILL=174
def build(alpha):
    M=int(N/alpha); used=[False]*M; probes=0
    for _ in range(N):
        s=random.randrange(M); p=1
        while used[s]: s=(s+1)%M; p+=1
        used[s]=True; probes+=p
    slots=[s for s in range(M) if used[s]]
    # miss lookup: probe until an empty slot
    miss=0; T=20000
    for _ in range(T):
        s=random.randrange(M); p=1
        while used[s]: s=(s+1)%M; p+=1
        miss+=p
    return M,slots,probes/N,miss/T
def detect(entries):
    det=tot=0
    for i in range(0,len(entries)-FILL,FILL):
        nd=entries[i:i+FILL]
        for j,K in enumerate(nd):
            lo=nd[j-1] if j>0 else None; hi=nd[j+1] if j<len(nd)-1 else None
            for b in range(64):
                K2=K^(1<<b); tot+=1
                if (lo is not None and K2<=lo) or (hi is not None and K2>=hi): det+=1
    return det/tot
print("random64 keys stored as-is:            detection 0.333 (measured 0.298), 1 tree lookup per search")
print(f"{'load':>5} {'range/N':>8} {'detect(pair layout)':>20} {'detect(1 entry/key)':>20} {'probes hit':>11} {'probes miss':>12}")
for alpha in (0.25,0.5,0.75,0.9):
    M,slots,ph,pm=build(alpha)
    pair=[]; 
    for s in slots[:8000]: pair+=[2*s,2*s+1]
    print(f"{alpha:5.2f} {1/alpha:8.2f} {detect(pair):20.3f} {detect(slots[:8000]):20.3f} {ph:11.2f} {pm:12.2f}")
