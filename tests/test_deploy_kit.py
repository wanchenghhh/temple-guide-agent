"""腾讯云部署包：脚本语法正确、关键安全项不缺席。

这些文件不会被单元测试“执行”，但每次改动都容易手滑——所以把必须存在的
安全项写成断言：数据挂盘、密钥模板不含真值、自检脚本能跑。
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "deploy" / "tencent-cloud"


def test_all_scripts_parse():
    for script in ("install.sh", "bootstrap-local.sh", "smoke.sh"):
        path = KIT / script
        assert path.exists(), script
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script}: {result.stderr}"


def test_compose_mounts_data_and_restarts():
    text = (KIT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./data:/app/data" in text, "数据必须挂到宿主机，否则重启丢记忆"
    assert "restart: unless-stopped" in text
    assert "env_file: .env" in text
    assert "healthcheck" in text
    assert "127.0.0.1:8787:8787" in text, "默认不直接暴露端口（由 nginx 前置）"


def test_env_template_has_no_real_secrets():
    text = (KIT / ".env.example.server").read_text(encoding="utf-8")
    for key in ("AUTH_SECRET", "HARNESS_ADMIN_TOKENS", "DEEPSEEK_API_KEY",
                "AMAP_KEY", "QWEATHER_KEY", "BOCHA_API_KEY"):
        match = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
        assert match and match.group(1).strip() == "", f"{key} 必须是空值"
    assert not re.search(r"sk-[A-Za-z0-9]{10,}", text)
    assert "e09c3f" not in text and "e1d764" not in text


def test_installer_generates_random_secrets():
    text = (KIT / "install.sh").read_text(encoding="utf-8")
    assert "urandom" in text and "AUTH_SECRET=" in text
    assert "chmod 600" in text, "含密钥的 .env 必须 600"


def test_nginx_sets_timeouts_for_slow_turns():
    text = (KIT / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_read_timeout 120s" in text, "单轮可能 5–15 秒，别用默认 60s"
    assert "X-Forwarded-Proto" in text
    assert "X-Content-Type-Options" in text


def test_smoke_covers_launch_gates():
    text = (KIT / "smoke.sh").read_text(encoding="utf-8")
    for token in ("/health", "/api/session", "temple_card", "灵验分", "metrics"):
        assert token in text, token


def test_readme_documents_the_icp_pitfall():
    text = (KIT / "README.md").read_text(encoding="utf-8")
    assert "备案" in text and "8787" in text, "大陆服务器不备案只能用 IP:端口"
    assert "备份" in text and "安全组" in text
