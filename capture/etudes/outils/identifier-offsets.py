#!/usr/bin/env python3
"""Identification stricte : on ne compare qu'aux mouvements des comptes DE
L'UTILISATEUR (pubkey lue a @144, etablie par le taux de repetition).
Reduit massivement les correspondances fortuites."""
import json, base64, struct, subprocess, collections, os, pathlib
SC="/tmp/claude-1000/-opt-pumpfun-LOL/fbd60345-4594-48e1-94ca-e22b06e569ab/scratchpad"
WSOL="So11111111111111111111111111111111111111112"; RPC=os.environ["RPC_URL"]
U64=lambda b,o: struct.unpack_from("<Q",b,o)[0]
ALPH="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58(b):
    n=int.from_bytes(b,'big'); s=''
    while n: n,r=divmod(n,58); s=ALPH[r]+s
    return '1'*(len(b)-len(b.lstrip(b'\x00')))+s
def rpc(sig):
    pl=json.dumps({"jsonrpc":"2.0","id":1,"method":"getTransaction",
        "params":[sig,{"encoding":"json","maxSupportedTransactionVersion":0}]})
    r=subprocess.run(["curl","-sS","-m","30","-X","POST",RPC,"-H","content-type: application/json","-d",pl],
                     capture_output=True,text=True)
    try: return json.loads(r.stdout).get("result")
    except Exception: return None

q_off=collections.defaultdict(collections.Counter); b_off=collections.defaultdict(collections.Counter)
tot=collections.Counter(); trouve_user=collections.Counter()
for ligne in pathlib.Path(f"{SC}/selection.tsv").read_text().splitlines():
    p=ligne.split("\t")
    if len(p)<4: continue
    nom,taille,sig,payload=p[0] or "(sans nom)",int(p[1]),p[2],p[3]
    r=rpc(sig)
    if not r or not r.get("meta"): continue
    buf=base64.b64decode(payload); f=(nom,taille)
    user=b58(buf[144:176])
    meta=r["meta"]
    pre={x["accountIndex"]:x for x in meta.get("preTokenBalances",[])}
    post={x["accountIndex"]:x for x in meta.get("postTokenBalances",[])}
    dq,db=set(),set(); vu=False
    for i in set(pre)|set(post):
        e=post.get(i) or pre.get(i)
        if e.get("owner")!=user: continue
        vu=True
        a=int(pre.get(i,{}).get("uiTokenAmount",{}).get("amount",0))
        c=int(post.get(i,{}).get("uiTokenAmount",{}).get("amount",0))
        if a==c: continue
        (dq if e.get("mint")==WSOL else db).add(abs(c-a))
    # SOL natif de l'utilisateur : son compte figure dans accountKeys
    msg=r["transaction"]["message"]; la=meta.get("loadedAddresses",{}) or {}
    cles=list(msg["accountKeys"])+list(la.get("writable",[]))+list(la.get("readonly",[]))
    if user in cles:
        vu=True
        i=cles.index(user)
        prb,pob=meta.get("preBalances",[]),meta.get("postBalances",[])
        if i<len(prb) and i<len(pob):
            d=pob[i]-prb[i]+(int(meta.get("fee",0)) if i==0 else 0)
            if d!=0: dq.add(abs(d))
    # PumpSwap invoque-t-il en premier niveau, ou la tx est-elle routee ?
    logs=meta.get("logMessages") or []
    direct = any(l.startswith("Program pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA invoke [1]") for l in logs)
    if not direct: continue
    if vu: trouve_user[f]+=1
    if not dq and not db: continue
    tot[f]+=1
    for o in range(0,len(buf)-7,8):
        v=U64(buf,o)
        if v==0: continue
        if any(abs(v-x)<=2 for x in dq): q_off[f][o]+=1
        if any(abs(v-x)<=2 for x in db): b_off[f][o]+=1
for f in sorted(tot,key=lambda x:-tot[x]):
    n=tot[f]
    if n<4: continue
    print(f"\n=== {f[0]} — {f[1]} octets, TX DIRECTES SEULEMENT ({n} tx, utilisateur retrouve dans {trouve_user[f]}) ===")
    print("  QUOTE (SOL/WSOL de l'utilisateur) :")
    for o,c in q_off[f].most_common(4): print(f"      @{o:4d} : {c:3d}/{n}  ({100*c//n:3d} %)")
    print("  BASE (token de l'utilisateur) :")
    for o,c in b_off[f].most_common(4): print(f"      @{o:4d} : {c:3d}/{n}  ({100*c//n:3d} %)")
