"""Independent CPU VideoMCP. GPU execution belongs to the host resident backend."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import httpx
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

STATE=Path(os.getenv('VIDEO_STATE','/state'))
PUBLIC=os.getenv('VIDEO_PUBLIC_URL','https://agentmcp.linxuhao.app').rstrip('/')
HOST_STATE=os.getenv('VIDEO_HOST_STATE','/home/linxuhao/h3-conditioning-bridge/video-state')
mcp=FastMCP('VideoMCP',instructions='Use the video_generation_workflow MCP prompt for the complete production workflow, suitable for any capable agent. The calling agent directs the film. Prefer its built-in advanced image generation tools, such as Codex imagegen; use AgentMCP image generation only when no such built-in capability is available. Reuse approved character assets independently of generator choice, then import approved keyframes here. Create projects and versioned shots, render standard (20 steps) or turbo (FL2VA 8 steps, Ref2VA preview 4 steps) asynchronously. Present candidate clips to the user; select only their chosen takes, then assemble an explicitly ordered shot list. V2 supports T2V, first/last frames, or 1..4 ordered reference images; preview 608x352 or native 1344x768, up to 124 frames. Ref2VA 768p uses standard only. Do not mix reference images with first/last frames. I2V conditioning parity is experimental. GPU resources are automatically scheduled: auxiliary jobs on GPU0 precede queued video; GPU1 keeps H3 resident. No manual model handoff is needed. No lip-sync or reference-video/audio support.')

@mcp.prompt
async def video_generation_workflow(brief:str='',project_id:str='')->str:
    """适用于所有agent的视频制作流程：需求、人物/分镜、关键帧、H3候选、用户选片与组合。

    Args:
        brief: 本次视频描述或修改要求；留空则使用当前对话中的需求。
        project_id: 已有VideoMCP项目ID；留空则按对话判断新建或恢复。
    """
    template=(Path(__file__).parent/'prompts/video_generation_workflow.md').read_text()
    return template+'\n\n## 本次输入\n'+json.dumps({'brief':brief,'project_id':project_id},ensure_ascii=False)

async def call(action,**arguments):
    from gpu_client import gpu_headers, GPU_URL
    async with httpx.AsyncClient(timeout=930) as client:
        response=await client.post(GPU_URL+'/rpc',json={'action':action,'arguments':arguments},headers=gpu_headers())
    value=response.json()
    if response.status_code!=200:raise ValueError(value.get('error','GPU backend unavailable'))
    def decorate(obj):
        if isinstance(obj,dict):
            if obj.get('output','').startswith(HOST_STATE+'/'):
                obj['download_url']=PUBLIC+'/video/files/'+obj['output'][len(HOST_STATE)+1:]
            for v in list(obj.values()):decorate(v)
        elif isinstance(obj,list):
            for v in obj:decorate(v)
    decorate(value['result']);return value['result']

@mcp.tool
async def video_project_create(title:str,brief:str='',characters:list[dict]|None=None)->dict:
    """Create a film brief; character entries reference existing asset-bank identities."""
    return await call('project_create',title=title,brief=brief,characters=characters or [])
@mcp.tool
async def video_projects()->list:
    """List durable video projects."""
    return await call('project_list')
@mcp.tool
async def video_project_get(project_id:str)->dict:
    """Read the brief, shot revisions and selected takes."""
    return await call('project_get',project_id=project_id)
@mcp.tool
async def video_project_update(project_id:str,expected_revision:int,data:dict)->dict:
    """Update brief/title/character references, refusing stale revisions."""
    return await call('project_update',project_id=project_id,expected_revision=expected_revision,data=data)
@mcp.tool
async def video_import_image(image_base64:str,source:str='user upload')->dict:
    """Import an approved image (maximum 20MiB); returns a content-addressed asset ID."""
    return await call('asset_import',image_base64=image_base64,source=source)
@mcp.tool
async def video_shot_put(project_id:str,prompt:str,title:str='',image:str|None=None,frames:int=124,shot_id:str|None=None,expected_revision:int=0,last_frame:str|None=None,references:list[str]|None=None,resolution:str='preview')->dict:
    """Create/update a shot. Image is the first-frame asset ID; last_frame is optional, including last-only. References is an ordered list of 1..4 asset IDs using Ref2VA; cannot mix with first/last. Editing clears selection but preserves historical takes. Resolution preview=608x352 or 768p=1344x768; frames=17*k+5, 22..124."""
    return await call('shot_put',project_id=project_id,shot_id=shot_id,expected_revision=expected_revision,data={'prompt':prompt,'title':title,'image':image,'frames':frames,'last_frame':last_frame,'references':references or [],'resolution':resolution})
@mcp.tool
async def video_render_shot(shot_id:str,expected_revision:int,request_key:str,profile:str='standard',seed:int=42)->dict:
    """Queue an immutable candidate take; returns immediately. Reuse request_key only for an identical retry. Profiles: standard=20; turbo=8 for FL2VA or 4 for Ref2VA preview. Ref2VA 768p requires standard; no automatic selection."""
    return await call('render_shot',shot_id=shot_id,expected_revision=expected_revision,request_key=request_key,profile=profile,seed=seed)
@mcp.tool
async def video_jobs(project_id:str)->list:
    """List jobs/takes including preserved failures, settings, provenance and clip download URLs."""
    return await call('jobs_list',project_id=project_id)
@mcp.tool
async def video_job_get(job_id:str)->dict:
    """Read current persistent job state and output."""
    return await call('job_get',job_id=job_id)
@mcp.tool
async def video_job_wait(job_id:str,timeout:float=60)->dict:
    """Event-driven wait up to 900 seconds; returns early on completion/failure/cancellation."""
    return await call('job_wait',job_id=job_id,timeout=timeout)
@mcp.tool
async def video_job_cancel(job_id:str)->dict:
    """Cancel queued work immediately. Running work drains current computation then becomes cancelled, never selectable; workers release afterwards."""
    return await call('job_cancel',job_id=job_id)
@mcp.tool
async def video_take_select(shot_id:str,take_id:str,expected_revision:int)->dict:
    """Select the user's chosen completed take for a current shot revision."""
    return await call('take_select',shot_id=shot_id,take_id=take_id,expected_revision=expected_revision)
@mcp.tool
async def video_assemble(project_id:str,shot_ids:list[str],request_key:str)->dict:
    """Queue CPU assembly of only selected takes in explicit shot order; outputs H.264/AAC and an immutable edit manifest."""
    return await call('assemble',project_id=project_id,shot_ids=shot_ids,request_key=request_key)
@mcp.tool
async def video_resources(action:str='status')->dict:
    """status: resident models/queue. acquire: allow next render to load. release: drain current work and unload both GPUs; queued jobs must finish/cancel first."""
    if action not in ('status','acquire','release'):raise ValueError('action must be status, acquire or release')
    return await call('resource_'+action)

