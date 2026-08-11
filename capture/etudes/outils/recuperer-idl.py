#!/usr/bin/env python3
"""Récupère l'IDL Anchor publié on-chain pour un programme donné.

Anchor stocke l'IDL à une adresse dérivée :
  base = findProgramAddress([], programId)
  idl  = createWithSeed(base, "anchor:idl", programId)
Le compte contient : 8 octets de discriminator, 32 d'autorité, puis un Vec<u8>
zlib-compressé qui est le JSON de l'IDL.
"""
import hashlib, json, subprocess, sys, zlib, base64, os

ALPH = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
IDX = {c: i for i, c in enumerate(ALPH)}
P = 2 ** 255 - 19


def b58d(s):
    n = 0
    for c in s:
        n = n * 58 + IDX[c]
    raw = n.to_bytes(32, "big") if n.bit_length() <= 256 else n.to_bytes((n.bit_length() + 7) // 8, "big")
    return raw[-32:].rjust(32, b"\x00")


def b58e(b):
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = ALPH[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + s


def sur_courbe(pk: bytes) -> bool:
    """Un point ed25519 valide se décompresse ; sinon l'adresse est hors courbe."""
    y = int.from_bytes(pk, "little") & ((1 << 255) - 1)
    if y >= P:
        return False
    d = (-121665 * pow(121666, P - 2, P)) % P
    y2 = (y * y) % P
    u = (y2 - 1) % P
    v = (d * y2 + 1) % P
    x2 = (u * pow(v, P - 2, P)) % P
    if x2 == 0:
        return True
    # x2 est-il un résidu quadratique ?
    return pow(x2, (P - 1) // 2, P) == 1


def find_program_address(program_id: bytes) -> bytes:
    """PDA sans seed : on décrémente le bump jusqu'à tomber hors courbe."""
    for bump in range(255, -1, -1):
        h = hashlib.sha256(bytes([bump]) + program_id + b"ProgramDerivedAddress").digest()
        if not sur_courbe(h):
            return h
    raise RuntimeError("aucun bump valide")


def create_with_seed(base: bytes, seed: str, owner: bytes) -> bytes:
    return hashlib.sha256(base + seed.encode() + owner).digest()


def rpc(method, params):
    pl = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    r = subprocess.run(["curl", "-sS", "-m", "40", "-X", "POST", os.environ["RPC_URL"],
                        "-H", "content-type: application/json", "-d", pl],
                       capture_output=True, text=True)
    return json.loads(r.stdout)


prog = sys.argv[1]
pid = b58d(prog)
base = find_program_address(pid)
idl_addr = create_with_seed(base, "anchor:idl", pid)
print(f"programme : {prog}")
print(f"adresse IDL dérivée : {b58e(idl_addr)}")

res = rpc("getAccountInfo", [b58e(idl_addr), {"encoding": "base64"}])
val = (res.get("result") or {}).get("value")
if not val:
    print("→ aucun compte IDL on-chain à cette adresse")
    sys.exit(1)

raw = base64.b64decode(val["data"][0])
print(f"compte trouvé : {len(raw)} octets, propriétaire {val['owner']}")

# 8 discriminator + 32 autorité + 4 longueur + charge zlib
corps = raw[44:]
longueur = int.from_bytes(raw[40:44], "little")
try:
    idl = json.loads(zlib.decompress(corps[:longueur]))
except Exception as e:
    print(f"→ décompression échouée : {e}")
    sys.exit(1)

chemin = f"/tmp/claude-1000/-opt-pumpfun-LOL/fbd60345-4594-48e1-94ca-e22b06e569ab/scratchpad/idl_{prog[:8]}.json"
open(chemin, "w").write(json.dumps(idl, indent=2))
print(f"→ IDL récupéré : {len(idl.get('instructions', []))} instructions, "
      f"{len(idl.get('events', []))} événements, {len(idl.get('types', []))} types")
print(f"   écrit dans {chemin}")
