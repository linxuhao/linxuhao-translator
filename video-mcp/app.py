"""GPU-side entrypoint: the shared tool surface plus what only exists beside the backend.

The tools, prompts and RPC transport live in video_tools, which the MCP layer imports too.
Everything here needs the local state directory: serving generated files from disk, the
engine proxy the other GPU containers call, and the server itself.
"""
import argparse

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from video_tools import mcp, call, STATE

@mcp.custom_route('/files/{path:path}',methods=['GET'])
async def files(request:Request):
    path=(STATE/request.path_params['path']).resolve()
    # Only generated media and reports are downloadable, never DB/socket/credentials.
    if not path.is_relative_to((STATE/'jobs').resolve()) or path.suffix not in ('.mp4','.png','.wav','.json') or not path.is_file():
        return JSONResponse({'error':'not found'},status_code=404)
    return FileResponse(path)

from engine_routes import register
register(mcp,call,STATE)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stdio',action='store_true');args=p.parse_args()
    if args.stdio:mcp.run(transport='stdio')
    else:
        import uvicorn
        from engine_routes import TokenGate
        uvicorn.run(TokenGate(mcp.http_app()),host='0.0.0.0',port=9041)
