#!/usr/bin/env python3
"""Distingue quote (SOL/WSOL) et base (token) pour chaque offset de montant."""
import json, base64, struct, subprocess, collections, os, pathlib
SC="/tmp/claude-1000/-opt-pumpfun-LOL/fbd60345-4594-48e1-94ca-e22b06e569ab/scratchpad"
WSOL="So11111111111111111111111111111111111111112"; RPC=os.environ["RPC_URL"]
U64=lambda b,o: struct.unpack_from("<Q",b,o)[0]
def rpc(sig):
    pl=json.dumps({"jsonrpc":"2.0","id":1,"method":"getTransaction",
        "params":[sig,{"encoding":"json","maxSupportedTransactionVersion":0}]})
    r=subprocess.run(["curl","-sS","-m","30","-X","POST",RPC,"-H","content-type: application/json","-d",pl],
                     capture_output=True,text=True)
    try: return json.loads(r.stdout).get("result")
    except Exception: return None
quote_off=collections.defaultdict(collections.Counter)
base_off=collections.defaultdict(collections.Counter)
tot=collections.Counter()
for ligne in pathlib.Path(f"{SC}/selection.tsv").read_text().splitlines():
    p=ligne.split("\t")
    if len(p)<4: continue
    nom,taille,sig,payload=p[0] or "(sans nom)",int(p[1]),p[2],p[3]
    r=rpc(sig)
    if not r or not r.get("meta"): continue
    meta=r["meta"]
    pre={b["accountIndex"]:b for b in meta.get("preTokenBalances",[])}
    post={b["accountIndex"]:b for b in meta.get("postTokenBalances",[])}
    q,bs=set(),set()
    for i in set(pre)|set(post):
        a=int(pre.get(i,{}).get("uiTokenAmount",{}).get("amount",0))
        c=int(post.get(i,{}).get("uiTokenAmount",{}).get("amount",0))
        if a==c: continue
        mint=(post.get(i) or pre.get(i)).get("mint")
        (q if mint==WSOL else bs).add(abs(c-a))
    for a,c in zip(meta.get("preBalances",[]),meta.get("postBalances",[])):
        if a!=c: q.add(abs(c-a))
    if not q and not bs: continue
    b=base64.b64decode(payload); f=(nom,taille); tot[f]+=1
    for o in range(0,len(b)-7,8):
        v=U64(b,o)
        if v==0: continue
        if any(abs(v-x)<=1 for x in q): quote_off[f][o]+=1
        if any(abs(v-x)<=1 for x in bs): base_off[f][o]+=1
for f in sorted(tot,key=lambda x:-tot[x]):
    n=tot[f]
    if n<3: continue
    print(f"\n{f[0]} — {f[1]} octets ({n} tx)")
    print("   QUOTE (SOL) :", " ".join(f"@{o}:{c}/{n}" for o,c in sorted(quote_off[f].items()) if c>=n*0.6) or "aucun")
    print("   BASE (token):", " ".join(f"@{o}:{c}/{n}" for o,c in sorted(base_off[f].items()) if c>=n*0.6) or "aucun")
