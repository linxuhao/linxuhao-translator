"""Shared host scheduler address and private service credential."""
import os
import io
import wave
from pathlib import Path
GPU_URL=os.getenv('GPU_SERVICE_URL','http://linxuhao-ai:9041').rstrip('/')
def gpu_headers():
    token=Path(os.getenv('GPU_TOKEN_FILE','/run/secrets/GPU_API_TOKEN')).read_text().strip()
    if not token:raise RuntimeError('GPU service credential is empty')
    return {'Authorization':'Bearer '+token}
async def transcribe(client,wav,language=None):
    # ffmpeg stdout uses unknown RIFF/data lengths; audio.cpp requires concrete sizes.
    try:
        with wave.open(io.BytesIO(wav),'rb') as source:
            params=source.getparams();frames=source.readframes(source.getnframes())
    except (wave.Error,EOFError) as exc:
        raise ValueError('Invalid normalized WAV audio') from exc
    output=io.BytesIO()
    with wave.open(output,'wb') as target:
        target.setparams(params._replace(nframes=0));target.writeframes(frames)
    wav=output.getvalue()
    data={'model':'qwen3-asr'}
    if language:data['language']=language
    response=await client.post(GPU_URL+'/engines/audio/v1/audio/transcriptions/details',
        files={'file':('audio.wav',wav,'audio/wav')},data=data,headers=gpu_headers(),timeout=930)
    response.raise_for_status()
    result=response.json()
    if not isinstance(result.get('text'),str):raise ValueError('ASR response missing text')
    return result
