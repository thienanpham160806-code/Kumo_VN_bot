"""Lenh /loc phai khop voi menu: ba bo loc dung san (Dot pha, Tich luy, Canh
bao) go duoc bang ten giong het nut bam, va menu khong lan `kn=` (muc khuyen
nghi cua /kn) voi bo loc dung san "Tich luy"."""
import pytest

from bot_phan_tich.analysis import screener as screener_mod
from bot_phan_tich.bot import keyboards
from bot_phan_tich.bot.handlers import screener as screener_handlers


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text: str, **kwargs):
        self.answers.append(text)


@pytest.fixture
def captured(monkeypatch):
    """Bo qua kiem tra snapshot va ghi lai tieu chi duoc dua vao screen_report."""
    calls = []

    async def no_missing_data():
        return None

    def fake_report(criteria):
        calls.append(criteria)
        return screener_mod.ScreenReport(results=[], total_universe=0, as_of=None)

    monkeypatch.setattr(screener_handlers, "_no_data_text", no_missing_data)
    monkeypatch.setattr(screener_handlers, "screen_report", fake_report)
    return calls


@pytest.mark.parametrize(
    "typed, factory",
    [
        ("dotpha", screener_mod.preset_breakout),
        ("Đột phá", screener_mod.preset_breakout),
        ("tichluy", screener_mod.preset_accumulate),
        ("TÍCH LUỸ", screener_mod.preset_accumulate),
        ("canhbao", screener_mod.preset_warning),
        ("canh-bao", screener_mod.preset_warning),
    ],
)
async def test_typed_preset_name_runs_same_screen_as_button(captured, typed, factory):
    message = FakeMessage(f"/loc {typed}")
    await screener_handlers.cmd_screen(message)
    assert captured == [factory()]


def test_every_menu_button_has_a_typed_command():
    buttons = [row[0] for row in keyboards.screener_menu().inline_keyboard]
    button_presets = {b.callback_data.split(":", 1)[1] for b in buttons}
    assert button_presets == set(screener_mod.PRESET_COMMANDS.values())
    for command, key in screener_mod.PRESET_COMMANDS.items():
        assert screener_mod.preset_from_text(command) == screener_mod.PRESETS[key]()


async def test_unknown_bare_word_lists_the_three_presets(captured):
    message = FakeMessage("/loc xyz")
    await screener_handlers.cmd_screen(message)
    assert captured == []
    for command in ("/loc dotpha", "/loc tichluy", "/loc canhbao"):
        assert command in message.answers[0]


async def test_menu_shows_typed_commands_and_separates_kn_from_presets():
    message = FakeMessage("/loc")
    await screener_handlers.cmd_screen(message)
    menu = message.answers[0]
    for command in ("/loc dotpha", "/loc tichluy", "/loc canhbao"):
        assert command in menu
    # kn= la muc khuyen nghi cua /kn, khong duoc mo ta nhu bo loc "tich luy nen gia"
    assert "kn=tichluy</code> (Lọc các mã tích luỹ nền giá)" not in menu
    assert "/kn" in menu
    assert "MUA" in menu and "BÁN" in menu


async def test_custom_conditions_still_work(captured):
    message = FakeMessage("/loc san=HOSE kn=MUA")
    await screener_handlers.cmd_screen(message)
    assert captured[0].exchanges == ["HOSE"]
    assert captured[0].min_action == screener_mod.ACTION_BUY
