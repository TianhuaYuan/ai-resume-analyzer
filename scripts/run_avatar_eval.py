"""Exercise avatar upload -> preview/export on an evaluation resume."""
from __future__ import annotations
import argparse, asyncio, io, json
from pathlib import Path
from PIL import Image
import httpx

async def main(args: argparse.Namespace) -> None:
    root=args.output_dir.resolve(); rows=json.loads((root/'upload_results.json').read_text(encoding='utf-8')); creds=json.loads((root/'runtime_credentials.local.json').read_text(encoding='utf-8'))
    row=next(x for x in rows if int(x['resume_id'])==args.resume_id); account=next(x for x in creds if int(x['user_id'])==int(row['user_id']))
    buf=io.BytesIO(); Image.new('RGB',(128,128),(42,100,180)).save(buf,format='PNG'); payload=buf.getvalue()
    out={'resume_id':args.resume_id,'avatar_bytes':len(payload)}
    async with httpx.AsyncClient(timeout=120) as c:
        # Refresh the token so the evaluation remains valid across backend restarts
        # (JWT signing secrets may differ between development processes).
        login=await c.post(f"{args.base_url}/api/v1/auth/login",json={'email':account['email'],'password':account['password']})
        if login.status_code == 200:
            account_token=login.json().get('access_token')
        else:
            account_token=account.get('access_token')
        h={'Authorization':f"Bearer {account_token}"}
        r=await c.post(f"{args.base_url}/api/v1/resumes/{args.resume_id}/avatar",headers=h,files={'file':('eval-avatar.png',payload,'image/png')}); out['upload']={'status':r.status_code,'body':r.json() if r.headers.get('content-type','').startswith('application/json') else r.text[:1000]}
        p=await c.get(f"{args.base_url}/api/v1/resumes/{args.resume_id}/preview",headers=h); out['preview']={'status':p.status_code,'has_avatar': 'avatar' in p.text.lower(),'size':len(p.content)}
        e=await c.get(f"{args.base_url}/api/v1/resumes/{args.resume_id}/export?format=pdf",headers=h); out['pdf']={'status':e.status_code,'size':len(e.content),'content_type':e.headers.get('content-type')}
    (root/'avatar_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--base-url',default='http://127.0.0.1:8081'); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--resume-id',type=int,required=True); asyncio.run(main(p.parse_args()))
