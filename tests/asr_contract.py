import asyncio,base64,sys,json,io,wave,struct
from pathlib import Path
sys.path.insert(0,'/app')
import gpu_client
from routers import translation,record,tutor
import httpx

def handler(request):
 assert request.url.path=='/engines/audio/v1/audio/transcriptions/details'
 assert request.headers['Authorization']=='Bearer fixture'
 body=request.content
 assert b'name="file"' in body and b'RIFF' in body
 assert b'RIFF\xff\xff\xff\xff' not in body
 assert b'to_language' not in body and b'temperature' not in body
 return httpx.Response(200,json={'text':'fixture transcript','language':'English'})

async def main():
 gpu_client.gpu_headers=lambda:{'Authorization':'Bearer fixture'}
 buf=io.BytesIO()
 with wave.open(buf,'wb') as f:
  f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\x00\x00'*160)
 wav=bytearray(buf.getvalue());wav[4:8]=b'\xff'*4;wav[40:44]=b'\xff'*4;wav=bytes(wav)
 encoded=base64.b64encode(wav).decode()
 async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
  for module in [translation,record]:
   forced=await module.asr_transcribe_with_language(client,wav,'zh',.2,0)
   detected=await module.asr_detect_language(client,encoded,.8,1)
   assert forced['error'] is None and forced['detected_lang']=='zh',forced
   assert detected['error'] is None and detected['detected_lang']=='en'
   assert detected['text']=='fixture transcript'
  assert (await gpu_client.transcribe(client,wav))['language']=='English'
 async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(400,json={'error':'invalid audio'}))) as client:
  for module in [translation,record]:
   assert (await module.asr_detect_language(client,encoded,.8,1))['error']
 print('ASR field, language, error compatibility PASS; no quality/latency assertions')
asyncio.run(main())
