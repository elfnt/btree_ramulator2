# Offline model of the per-node "keys strictly increasing" check under single-bit key flips.
# No simulator involved: pure combinatorics on key arrays, to predict what guard keys can buy.
import random
random.seed(7)
FILL=174; ORDER=253; NODES=12

def real_keys(dist,k,n):
    if dist=='stride': return [(i+5000)<<k for i in range(n)]
    if dist=='random64':
        # 1M uniform keys in [0,2^63): mean gap 2^43. Sample a contiguous run with that gap law.
        g=2**43; x=random.randrange(2**62); out=[]
        for _ in range(n):
            x+=max(3,int(random.expovariate(1.0/g))); out.append(x)
        return out

def leaf_rate(nodes):
    """nodes: list of lists of (key,is_real). Returns detected fraction over real-key single-bit flips,
       split by flip direction (0->1 up, 1->0 down)."""
    det=tot=0
    for nd in nodes:
        for i,(k,real) in enumerate(nd):
            if not real: continue
            lo=nd[i-1][0] if i>0 else None; hi=nd[i+1][0] if i<len(nd)-1 else None
            for b in range(64):
                k2=k^(1<<b); tot+=1
                if (lo is not None and k2<=lo) or (hi is not None and k2>=hi): det+=1
    return det/tot

def chunk(entries,size): return [entries[i:i+size] for i in range(0,len(entries)-size+1,size)]

def data_level(keys,mode,gap=None):
    e=[]
    for K in keys:
        if mode in('left','both'): e.append((K-1,False))
        e.append((K,True))
        if mode in('right','both'): e.append((K+1,False))
        if mode=='mid': e.append((K+gap//2,False))
    return chunk(e,FILL)                      # node still holds 174 entries -> more pages

def slack(keys,mode):
    out=[]
    for nd in chunk(keys,FILL):
        free=ORDER-FILL; per=1 if mode=='right' else 2; n_g=free//per
        pick=set(round(j*FILL/n_g) for j in range(n_g)); e=[]
        for i,K in enumerate(nd):
            g=i in pick
            if g and mode=='both': e.append((K-1,False))
            e.append((K,True))
            if g: e.append((K+1,False))
        out.append(e)
    return out

print("== LEAF: fraction of real-key single-bit flips that break ordering (= caught by the free check) ==")
print(f"{'keys':12}{'none':>7}{'right':>7}{'left':>7}{'both':>7}{'mid':>7} | slack-only: {'right':>6}{'both':>6}")
for name,dist,k in [('stride 2^8','stride',8),('stride 2^16','stride',16),('stride 2^32','stride',32),('random64','random64',0)]:
    ks=real_keys(dist,k,FILL*NODES)
    r=[leaf_rate(chunk([(x,True) for x in ks],FILL))]
    for m in ['right','left','both']: r.append(leaf_rate(data_level(ks,m)))
    r.append(leaf_rate(data_level(ks,'mid',1<<k)) if dist=='stride' else float('nan'))
    s=[leaf_rate(slack(ks,'right')),leaf_rate(slack(ks,'both'))]
    print(f"{name:12}"+''.join(f"{x:7.3f}" for x in r)+" |             "+''.join(f"{x:6.3f}" for x in s))
print("pages needed (data-level): none 1.0x, right/left/mid 2.0x, both 3.0x; slack-only 1.0x")
print(f"slack coverage at {FILL}/{ORDER} fill: right {min(1,(ORDER-FILL)/FILL):.2f} of keys, both {(ORDER-FILL)//2/FILL:.2f} of keys")

print("\n== INTERNAL: per separator, out of 64 single-bit flips: detected / undetected-but-harmless / undetected-and-harmful ==")
def internal(dist,k,mode):
    allk=real_keys(dist,k,FILL*FILL)                      # one internal node worth of leaves
    seps=[(allk[j*FILL],allk[j*FILL-1]) for j in range(1,FILL)]   # (S, L=max key of left leaf)
    nd=[]
    for S,L in seps:
        if mode in('phys_both','route_left'): nd.append((S-1,'g',S,L))
        nd.append((S,'s',S,L))
        if mode in('phys_right','phys_both'): nd.append((S+1,'g',S,L))
    det=harmless=harm=0
    for i,(v,kind,S,L) in enumerate(nd):
        lo=nd[i-1][0] if i>0 else None; hi=nd[i+1][0] if i<len(nd)-1 else None
        for b in range(64):
            v2=v^(1<<b)
            if (lo is not None and v2<=lo) or (hi is not None and v2>=hi): det+=1; continue
            if kind=='s':
                if mode=='route_left': bad = v2>S          # key S itself now falls into the dummy range
                else:                  bad = (v2>S) or (v2<=L)
            else:
                if mode=='route_left': bad = v2<=L         # dummy range swallowed real keys of the left leaf
                else:                  bad = False         # physical guard has no routing role
            if bad: harm+=1
            else: harmless+=1
    n=len(seps); return det/n,harmless/n,harm/n
for name,dist,k in [('stride 2^0','stride',0),('stride 2^16','stride',16),('stride 2^32','stride',32),('random64','random64',0)]:
    for mode,label in [('none','no guard'),('phys_right','non-routing guard S+1'),('phys_both','non-routing guards S-1,S+1'),('route_left','routing dummy node [S-1,S)')]:
        d,h0,h1=internal(dist,k,mode)
        print(f"{name:12}{label:30} detected {d:6.1f}  harmless {h0:5.1f}  HARMFUL-undetected {h1:5.1f}")
