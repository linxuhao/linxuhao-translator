"""Authenticated HTTP facade over the host's shared durable GPU queue."""
import asyncio
import base64
import hmac
import json
import os
from pathlib import Path
import uuid

from starlette.responses import JSONResponse, Response, StreamingResponse


class TokenGate:
    def __init__(self, app):self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type']=='http':
            headers=dict(scope.get('headers',[]))
            token=Path(os.getenv('GPU_TOKEN_FILE','/state/gpu-api.token')).read_text().strip()
            trusted=set(os.getenv('GPU_TRUSTED_CLIENTS','').split(','))
            internal=scope.get('client',('',0))[0] in trusted and scope['path'].startswith('/engines/')
            if not internal and not (token and hmac.compare_digest(headers.get(b'authorization',b''),('Bearer '+token).encode())):
                return await JSONResponse({'error':'unauthorized'},status_code=401)(scope,receive,send)
        await self.app(scope,receive,send)


def register(mcp, call, state):
    token_path=Path(os.environ.get('GPU_TOKEN_FILE','/state/gpu-api.token'))

    def authorized(request):
        token=token_path.read_text().strip()
        return bool(token) and hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+token)

    @mcp.custom_route('/rpc',methods=['POST'])
    async def rpc(request):
        if not authorized(request):return JSONResponse({'error':'unauthorized'},status_code=401)
        data=await request.json()
        try:return JSONResponse({'result':await call(data['action'],**data.get('arguments',{}))})
        except (ValueError,KeyError,TypeError) as e:return JSONResponse({'error':str(e)},status_code=400)

    @mcp.custom_route('/engines/{engine}/{path:path}',methods=['GET','POST'])
    async def engine(request):
        trusted=set(os.getenv('GPU_TRUSTED_CLIENTS','').split(','))
        if request.client.host not in trusted and not authorized(request):return JSONResponse({'error':'unauthorized'},status_code=401)
        if request.path_params['engine']=='sd' and request.method=='GET' and request.path_params['path'].startswith('sdcpp/v1/jobs/'):
            ident=request.path_params['path'].split('/')[-1]
            try:job=await call('job_get',job_id=ident)
            except ValueError:return JSONResponse({'error':'unknown image job'},status_code=404)
            if job['kind']!='engine' or job['request']['engine']!='sd':return JSONResponse({'error':'not an image job'},status_code=404)
            if job['status']=='completed':return JSONResponse(json.loads((state/'jobs'/ident/'response.bin').read_text()))
            return JSONResponse({'id':ident,'status':job['status'],'error':job.get('error')})
        body=await request.body()
        if len(body)>20*1024*1024:return JSONResponse({'error':'request too large'},status_code=413)
        try:
            job=await call('engine_submit',engine=request.path_params['engine'],path='/'+request.path_params['path'],
                method=request.method,body=base64.b64encode(body).decode(),
                content_type=request.headers.get('content-type','application/json'),
                request_key=request.headers.get('x-request-id') or 'http-'+uuid.uuid4().hex)
        except ValueError as e:return JSONResponse({'error':str(e)},status_code=400)
        if request.path_params['engine']=='sd' and request.path_params['path']=='sdcpp/v1/img_gen':
            return JSONResponse({'id':job['id'],'poll_url':'/sdcpp/v1/jobs/'+job['id']})
        directory=state/'jobs'/job['id']
        meta=directory/'response.json'
        while not meta.exists():
            job=await call('job_wait',job_id=job['id'],timeout=1)
            if job['status'] in ('failed','cancelled','interrupted'):
                return JSONResponse({'error':job.get('error') or job['status']},status_code=503)
        headers=json.loads(meta.read_text())

        async def content():
            offset=0
            while True:
                path=directory/'response.bin'
                if path.exists():
                    with path.open('rb') as f:
                        f.seek(offset);chunk=f.read(65536)
                    if chunk:offset+=len(chunk);yield chunk;continue
                job=await call('job_get',job_id=job_id)
                if job['status'] in ('completed','failed','cancelled','interrupted'):
                    # One final read closes the race with the worker's last write.
                    if path.exists():
                        with path.open('rb') as f:f.seek(offset);chunk=f.read()
                        if chunk:yield chunk
                    break
                await asyncio.sleep(.05)
        job_id=job['id']
        return StreamingResponse(content(),status_code=headers['status'],headers={'content-type':headers['content_type']})
