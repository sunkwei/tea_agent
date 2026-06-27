"""Gateway CLI 入口 — python -m tea_agent.gateway [start|stop|status]"""

import sys, logging
from tea_agent.gateway.gateway import GatewayDaemon

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    gw = GatewayDaemon()
    if cmd == "start":
        res = gw.start(daemon="--foreground" not in sys.argv)
        print(res)
    elif cmd == "stop":
        print(gw.stop())
    elif cmd == "status":
        print(gw.status())
    elif cmd == "foreground":
        gw.start(daemon=False)
    else:
        print(f"用法: python -m tea_agent.gateway [start|stop|status|foreground]")

if __name__ == "__main__":
    main()
