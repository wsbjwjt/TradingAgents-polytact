"""一次性探测 47.76.82.76：硬件/OS/Docker/网络出站/数据源连通性。密码不入库。"""
import sys

import paramiko

HOST = "47.76.82.76"

CMDS = {
    "os": "cat /etc/os-release | head -2; uname -m; uptime",
    "cpu_mem_disk": "nproc; free -h | head -2; df -h / | tail -1",
    "docker": "docker version --format '{{.Server.Version}}' 2>/dev/null || echo NO_DOCKER; docker compose version 2>/dev/null || echo NO_COMPOSE",
    "python": "python3 --version 2>/dev/null || echo NO_PY3",
    "curl_git": "curl --version 2>/dev/null | head -1; git --version 2>/dev/null || echo NO_GIT",
    "firewall": "command -v ufw && ufw status 2>/dev/null | head -5; command -v firewall-cmd && firewall-cmd --list-ports 2>/dev/null; echo ---; ss -tlnp 2>/dev/null | grep -E ':(80|3306|8890|8000)\\b' || echo NO_LISTEN_ON_TARGET_PORTS",
    "net_out": "curl -s -o /dev/null -w 'tencent:%{http_code}:%{time_total}s\\n' --max-time 8 'https://qt.gtimg.cn/q=sh600519'; curl -s -o /dev/null -w 'eastmoney:%{http_code}:%{time_total}s\\n' --max-time 8 'https://push2.eastmoney.com/api/qt/stock/get?secid=1.600519&fields=f57'; curl -s -o /dev/null -w 'dashscope:%{http_code}:%{time_total}s\\n' --max-time 8 'https://dashscope.aliyuncs.com/compatible-mode/v1/models'; curl -s -o /dev/null -w 'feishu:%{http_code}:%{time_total}s\\n' --max-time 8 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'; curl -s -o /dev/null -w 'pypi-aliyun:%{http_code}:%{time_total}s\\n' --max-time 8 'https://mirrors.aliyun.com/pypi/simple/'",
    "region": "curl -s --max-time 5 http://100.100.100.200/latest/meta-data/region-id 2>/dev/null || echo NO_METADATA",
    "port80_self": "curl -s -o /dev/null -w 'self80:%{http_code}\\n' --max-time 4 http://127.0.0.1:80/ ; ss -tln | grep ':80\\b' || echo nothing_on_80",
}


def main():
    password = sys.argv[1]
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username="root", password=password, timeout=12,
                allow_agent=False, look_for_keys=False)
    for label, cmd in CMDS.items():
        _in, out, err = cli.exec_command(cmd, timeout=60)
        print(f"===== {label} =====")
        print(out.read().decode(errors="replace").strip())
        e = err.read().decode(errors="replace").strip()
        if e:
            print(f"[stderr] {e[:300]}")
    cli.close()


if __name__ == "__main__":
    main()
