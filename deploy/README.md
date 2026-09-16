# 两台机器,两份 override

这套部署跨两台机器,各自需要一份 compose override,而 compose 只会自动读取名为
`docker-compose.override.yml` 的那一份。两份内容完全不同,却必须叫同一个名字——
所以仓库里按角色存放,机器上各自复制一份到根目录(根目录那份已在 `.gitignore` 里)。

| 仓库中的文件 | 属于哪台机器 | 内容 |
|---|---|---|
| `deploy/gpu.override.yml` | **linxuhao-ai**(GPU 资源层) | `video-mcp` 门面、`sd-server` / `audiocpp-server` / `llamacpp-qwen` / `vllm-qwen` 的 gpu-guard 入口、`continuity`、`media-gen` |
| `deploy/mcp.override.yml` | **linxuhaserver**(MCP 接口层) | `mcp-server` 的 `GPU_SERVICE_URL` 与凭据挂载、`gateway` 的 `gpu_client` 与三个 router |

安装:

```sh
cp deploy/gpu.override.yml docker-compose.override.yml    # 在 linxuhao-ai 上
cp deploy/mcp.override.yml docker-compose.override.yml    # 在 linxuhaserver 上
```

换机部署时,连同 `.env` 一起调整(见 `.env.example`:`BRIDGE_ROOT`、`GPU_LOCK_DIR`、
`GATEWAY_ROOT`、`VIP_SECRETS_DIR`、`LINXUHAO_AI_IP`)。

> 这两份此前都只以未跟踪文件的形式存在于各自机器上,`mcp.override.yml` 更是整套部署的
> 关键一环——它把 `mcp-server` 的构建指向另一个 checkout。谁也无法只凭仓库重建出线上环境,
> 而这正是"换台机器就能部署"卡住的地方,不是路径写死。
