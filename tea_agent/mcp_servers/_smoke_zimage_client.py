"""MCP 客户端自测：日志名由 argv 指定，服务端 python 用绝对路径。"""

import asyncio
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
SERVER = str(HERE / "zimage_server.py")
OUT = r"C:\Users\Hetin\work\git\tea_agent\output\zimage"
LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "_smoke.log"
PYEXE = sys.executable


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] " + " ".join(str(x) for x in a) + "\n")


async def main():
    log("client python:", PYEXE)
    params = StdioServerParameters(command=PYEXE, args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            log("TOOLS", [t.name for t in (await session.list_tools()).tools])

            t0 = time.time()
            info = await session.call_tool("zimage_info", {})
            log(f"INFO({time.time()-t0:.1f}s)", info.content[0].text[:600])

            t0 = time.time()
            r1 = await session.call_tool(
                "zimage_generate",
                {"prompt": "一只戴墨镜的柴犬，赛博朋克霓虹街头，电影感打光，浅景深",
                 "width": 512, "height": 512, "seed": 42, "output_dir": OUT},
            )
            log(f"GEN512({time.time()-t0:.1f}s)", r1.content[0].text)

            t0 = time.time()
            r2 = await session.call_tool(
                "zimage_generate",
                {"prompt": "赛博朋克城市夜景，霓虹灯牌写着“造相”，雨后街道倒影，超广角，电影质感",
                 "seed": 7, "output_dir": OUT},
            )
            log(f"GEN1024({time.time()-t0:.1f}s)", r2.content[0].text)
            log("ALL_DONE")


try:
    asyncio.run(asyncio.wait_for(main(), timeout=2400))
except Exception as e:
    log("ERROR", type(e).__name__, str(e)[:600])
