# VideoMCP on linxuhao-ai

Any capable agent can direct the workflow. This profile exposes 14 atomic video tools and media downloads.
The CPU MCP service and other CPU MCP endpoints can stay online together. A host
service owns the H3 AMD/CUDA workers; it loads them lazily for the first render and
keeps them resident until `video_resources(action="release")`, failure or cancellation.

Current V2: T2V, first and/or last frame (FL2VA), or 1..4 ordered reference
images (Ref2VA). Do not mix references with first/last frames. Canvas presets:
`preview` 608x352 and native `768p` 1344x768, 22..124 frames in 17*k+5 increments,
24fps. Assembly requires identical canvas sizes.

| Task | standard | turbo | Turbo video/audio shifts |
| --- | --- | --- | --- |
| FL2VA preview | 20 | 8 | 12/3 |
| FL2VA 768p | 20 | 8 | 6/3 |
| Ref2VA preview | 20 | 4 | 12/3 |
| Ref2VA 768p | 20 | unavailable | not attested |

Official bypass adapters preserve quantized base weights without a full backup.
The Ref2VA 768p 8-step file exists but its shifts are not documented in the pinned
upstream recipe, so it is not enabled. At768p both VAEs are released before
sampling and reloaded from disk afterwards; AMD encoder and CUDA DiT remain
resident. PyTorch expandable segments are enabled. VAE uses upstream spatial/
temporal tiling and CPU decoded-pixel buffers; full weights never offload to CPU.
Changing model family or resolution reloads only the CUDA worker.

Images are canonicalized once for both Qwen and VAE: first frame stretched,
last frame center-cropped, references aspect-preserving/down-only to canvas area,
32-pixel alignment. Original and canonical hashes, order and role persist with
each take. The encoder limit is4096 tokens including image tokens. Image hidden
numerical parity remains experimental; reference identity and endpoint fidelity
are not guarantees. No reference video/audio, lipsync, subtitles or transitions.

## Deploy

Owned worktree: `/home/linxuhao/vip-gateway-video`, based on GPU-host b9b45d6.
The original `/home/linxuhao/vip-gateway/docker-compose.yml` is untouched.
This worktree's automatically read `docker-compose.override.yml` is required.
Do not invoke the old checkout or explicitly omit the override to start GPU engines:
that bypasses the lease guard. Direct privileged GPU launches are outside this
cooperative scheduler; it is not kernel-level isolation.

```sh
cd /home/linxuhao/vip-gateway-video
gcc -O2 -static video-mcp/gpu-guard.c -o video-mcp/gpu-guard
mkdir -p /home/linxuhao/.local/state/vip-gpu
touch /home/linxuhao/.local/state/vip-gpu/gpu-mode.lock
chmod 600 /home/linxuhao/.local/state/vip-gpu/gpu-mode.lock
# The GPU runtime (formerly the h3-video user unit) runs as the gpu_runtime container
# from the bridge checkout; it creates video-state/runtime.sock that video-mcp mounts.
docker compose -f /home/linxuhao/h3-conditioning-bridge/deploy/docker-compose.yml up -d --build
docker compose --profile video up -d --build video-mcp
```

Runtime/model installation and exact upstream/model pins are in the companion
`/home/linxuhao/h3-conditioning-bridge` README. The host bridge is intentional:
it uses the already validated CUDA/Vulkan libraries; the MCP image has no GPU
access and does not duplicate a 50GB GPU environment. State mounts at `/state`;
backend Unix socket permissions restrict access to the service user/root.
HTTP is bound only to host loopback on 9041 and a private Compose network.

Connect from Codex with SSH stdio (uses existing SSH authentication):

```toml
[mcp_servers.videomcp]
command = "ssh"
args = ["-T", "linxuhao@linxuhao-ai", "docker", "exec", "-i", "video_mcp", "python", "/app/app.py", "--stdio"]
tool_timeout_sec = 960
```

For media preview/download, forward loopback without publishing a public endpoint:
`ssh -N -L 9041:127.0.0.1:9041 linxuhao@linxuhao-ai`.
Then `http://127.0.0.1:9041/mcp` and returned download URLs work on the Mac.
Alternatively the calling agent can copy returned host artifacts with scp/rsync.

## Workflow

1. Prefer the calling agent's built-in advanced image generation (for example,
   Codex imagegen). Use AgentMCP image generation only when no such built-in
   capability is available. Reuse approved character assets; optional AgentMCP
   character/subject storage does not determine the image provider. Store those
   identities in `video_project_create.characters`.
2. `video_import_image` imports a keyframe; its immutable SHA256 asset ID is the
   `image` argument of `video_shot_put`. Omit image for text-only.
3. `video_render_shot` freezes shot revision, image hash, prompt, profile and seed.
   Supply a unique request key; identical retries return the same job.
4. `video_job_wait` waits without poll loops. `video_jobs` returns all candidates,
   failures and output URLs. Present clips before selecting.
5. `video_take_select` records the user's chosen current-revision candidate.
   Updating a shot clears its selection, retaining all older outputs.
6. `video_assemble` takes an ordered shot-ID list, snapshots selected takes and
   streams their video/audio into H.264/AAC. Audio is trimmed/padded to each exact
   frame count; no automated creative decisions. Its manifest records input hashes.

Queued cancellation is immediate. Running cancellation lets current GPU work
finish, marks the job cancelled (not selectable), and unloads workers. A crash
marks in-flight jobs interrupted; queued jobs remain durable. There is no silent
retry of ambiguous work. The process owns a singleton state lock; each GPU child
inherits the mode lease and dies with its parent. Logs and partial files remain.

To switch to existing media/translator engines, first finish/cancel queued video
jobs and release VideoMCP. Start engines through this guarded worktree. To return
to video, stop those exact engines after their work drains, then acquire VideoMCP.
The service refuses foreign GPU containers/processes; it never kills them.
The old media/translator hardware configuration still needs validation after the
7900XTX/5090 upgrade; this change adds exclusion, not an untested ROCm migration.

A reboot may reset AMD power cap. H3 refuses GPU loading if read-back exceeds
280W; use the existing reviewed power configuration procedure. Never delete or
replace a live lock file: all participants must refer to the same inode.

## Workflow prompt

MCP prompt `video_generation_workflow` provides the complete agent-directed
production workflow, including brief/resume, storyboard, characters/keyframes,
GPU mode handoff, candidate review, selective regeneration and assembly.
Both string arguments are optional: `brief` (current request) and `project_id`
(existing project). With no arguments it uses the current conversation context.
Retrieval itself performs no generation or state changes. Clients discover it
via `prompts/list` and retrieve it via `prompts/get`; it is a prompt, not a new tool.

```python
await client.get_prompt("video_generation_workflow", {
    "brief": "做一个两个镜头的小熊猫雪地短片，先看分镜和关键帧",
    "project_id": "",
})
```

Template source: `video-mcp/prompts/video_generation_workflow.md`.
