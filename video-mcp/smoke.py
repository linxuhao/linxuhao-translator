"""Real MCP workflow smoke; run inside CPU MCP container against its HTTP endpoint."""
import asyncio
import base64
import json
from pathlib import Path
import time
from fastmcp import Client

async def main():
    evidence=Path('/state/evidence/mcp-e2e-first');evidence.mkdir(parents=True,exist_ok=False)
    transcript=[]
    async with Client('http://127.0.0.1:9041/mcp') as c:
        async def call(name,**kw):
            r=await c.call_tool(name,kw)
            transcript.append({'tool':name,'args':{k:v for k,v in kw.items() if k!='image_base64'},'result':r.data})
            (evidence/'transcript.json').write_text(json.dumps(transcript,indent=2))
            if r.is_error:raise RuntimeError(str(r))
            return r.data
        names=[x.name for x in await c.list_tools()]
        assert len(names)==14
        p=await call('video_project_create',title='VideoMCP smoke: panda shots',brief='Technical fixture: a panda in snow, two selected clips. No user creative approval implied.')
        image=await call('video_import_image',image_base64=base64.b64encode(Path('/state/evidence/panda.png').read_bytes()).decode(),source='Existing H3 first-frame fixture')
        prompt='A red panda walking through a snowy forest. <|caption_start|> Hello <|caption_end|>'
        shots=[]
        for i in range(2):shots.append(await call('video_shot_put',project_id=p['id'],prompt=prompt,title='Panda shot '+str(i+1),image=image['asset_id']))
        jobs=[]
        for i,(shot,profile) in enumerate([(shots[0],'standard'),(shots[0],'standard'),(shots[1],'turbo'),(shots[0],'standard')]):
            jobs.append(await call('video_render_shot',shot_id=shot['id'],expected_revision=1,request_key=p['id']+'-'+str(i),profile=profile,seed=42))
        cancelled=await call('video_render_shot',shot_id=shots[1]['id'],expected_revision=1,request_key=p['id']+'-cancel',profile='turbo',seed=99)
        assert (await call('video_job_cancel',job_id=cancelled['id']))['status']=='cancelled'
        for job in jobs:
            r=await call('video_job_wait',job_id=job['id'],timeout=900)
            assert r['status']=='completed',r
        for shot,job in [(shots[0],jobs[1]),(shots[1],jobs[2])]:
            await call('video_take_select',shot_id=shot['id'],take_id=job['id'],expected_revision=1)
        edit=await call('video_assemble',project_id=p['id'],shot_ids=[s['id'] for s in shots],request_key=p['id']+'-edit')
        result=await call('video_job_wait',job_id=edit['id'],timeout=60)
        assert result['status']=='completed',result
        assert result['result']['frames']==248
        status=await call('video_resources')
        print(json.dumps({'project_id':p['id'],'jobs':[j['id'] for j in jobs],'cancelled':cancelled['id'],'edit':result,'resources':status}),flush=True)
        (evidence/'summary.json').write_text(json.dumps({'project_id':p['id'],'jobs':[j['id'] for j in jobs],'edit_id':edit['id'],'tools':names},indent=2))
asyncio.run(main())
