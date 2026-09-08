from pathlib import Path

USER_FACING_FILES = (
    "apps/library/auth.py",
    "apps/library/booking.py",
    "apps/library/parser.py",
    "apps/library/service.py",
    "apps/library/sessions.py",
    "apps/library/source.py",
    "apps/library/web.py",
    "apps/library/static/app.js",
    "apps/library/static/booking-ui.js",
    "apps/library/static/index.html",
    "apps/library/static/login.html",
    "apps/library/static/login.js",
)

CONVERSATIONAL_FRAGMENTS = (
    "해 줘",
    "보여 줘",
    "할게",
    "이야.",
    "됐어",
    "했어",
    "없어",
    "않아",
    "있어",
    "골라 줘",
    "바꿔봐",
    "사용해.",
    "예약해.",
)


def test_user_facing_copy_uses_neutral_interface_language():
    text = "\n".join(Path(path).read_text(encoding="utf-8") for path in USER_FACING_FILES)

    assert [fragment for fragment in CONVERSATIONAL_FRAGMENTS if fragment in text] == []


def test_logged_in_account_has_an_explicit_visible_label_and_style():
    html = Path("apps/library/static/index.html").read_text(encoding="utf-8")
    css = Path("apps/library/static/style.css").read_text(encoding="utf-8")

    assert 'class="account-menu" aria-label="로그인 정보"' in html
    assert '<small>로그인 계정</small>' in html
    assert 'id="account-label"' in html
    assert ".account-menu{" in css
    assert ".account-state{" in css
