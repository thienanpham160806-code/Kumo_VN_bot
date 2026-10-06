"""vnstock la phu thuoc TUY CHON: goi bi PyPI cach ly thi cai dat va bot van
phai chay bang cac nguon con lai."""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from bot_phan_tich.data import cache, vietcap
from bot_phan_tich.data.base import ProviderError

ROOT = Path(__file__).resolve().parents[1]
_VNSTOCK_MODULES = ["vnstock", "vnstock.core", "vnstock.core.utils",
                    "vnstock.core.utils.user_agent", "vnstock.explorer",
                    "vnstock.explorer.vci", "vnstock.explorer.vci.company"]


@pytest.fixture
def no_vnstock(monkeypatch):
    """Gia lap may khong cai duoc vnstock: moi `import vnstock...` -> ImportError."""
    for name in _VNSTOCK_MODULES:
        monkeypatch.setitem(sys.modules, name, None)


def _requirement_names(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line.split(">")[0].split("=")[0].split("<")[0].strip().lower())
    return names


def test_requirements_do_not_hard_depend_on_vnstock():
    assert "vnstock" not in _requirement_names(ROOT / "requirements.txt")


def test_pyproject_declares_vnstock_as_optional_extra():
    tomllib = pytest.importorskip("tomllib")  # Python >= 3.11
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not any(dep.startswith("vnstock") for dep in project.get("dependencies", []))
    assert any(dep.startswith("vnstock") for dep in project["optional-dependencies"]["vnstock"])


def test_vietcap_methods_raise_provider_error_without_vnstock(no_vnstock):
    provider = vietcap.VietcapProvider()
    with pytest.raises(ProviderError, match="vnstock"):
        provider.income_statement("FPT", "year")
    with pytest.raises(ProviderError, match="vnstock"):
        provider.company_news("FPT")


def test_public_endpoint_headers_fall_back_without_vnstock(no_vnstock):
    headers = vietcap._public_headers()
    assert headers["User-Agent"].startswith("Mozilla")
    assert "trading.vietcap.com.vn" in headers["Referer"]


def test_router_returns_empty_fundamentals_instead_of_crashing(no_vnstock, monkeypatch):
    from bot_phan_tich.data.router import DataRouter

    monkeypatch.setattr(cache, "read_frame", lambda *a, **k: None)
    monkeypatch.setattr(cache, "write_frame", lambda *a, **k: None)
    router = DataRouter()
    router._fund_names = ["vietcap"]
    bundle = router.financials("FPT", "year")
    assert set(bundle) == {"income", "balance", "cashflow", "ratios"}
    assert all(isinstance(f, pd.DataFrame) and f.empty for f in bundle.values())


def test_bot_modules_import_without_vnstock():
    """Khoi dong bot (import toan bo handler, router, scheduler) khi vnstock
    hoan toan khong co - chay trong tien trinh rieng de khong anh huong test khac.
    Code cu da import vnstock ben trong ham nen test nay cung qua tren code cu:
    no giu cho dieu do khong bi pha vo ve sau."""
    code = (
        "import sys\n"
        f"for name in {_VNSTOCK_MODULES!r}: sys.modules[name] = None\n"
        "import bot_phan_tich.bot.main, bot_phan_tich.data.router\n"
        "import bot_phan_tich.analysis.snapshot, bot_phan_tich.backtest.walk_forward\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
        cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
