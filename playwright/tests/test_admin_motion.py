"""Scroll reveals never rewind visible content and preserve keyboard access."""

from itertools import pairwise

from playwright.sync_api import Page, expect

from .auth_helpers import _create_verified_user, _login_as_user
from .settings import BASE_URL


def test_admin_scroll_reveals_are_continuous_and_do_not_replay(page: Page) -> None:
    """Keep reveal opacity monotonic and avoid replay after HTMX settles."""
    email, password = _create_verified_user(page, prefix="admin-motion", admin=True)
    _login_as_user(page, email=email, password=password)

    for width in (320, 390, 768, 1280):
        page.set_viewport_size({"width": width, "height": 720})
        page.goto(f"{BASE_URL}/admin/index")
        page.evaluate("document.fonts.ready")
        cards = page.locator(".admin-dashboard-card")
        expect(cards).to_have_count(6)
        before = cards.evaluate_all("""elements => elements.map(element => ({
            visible: element.getBoundingClientRect().top < innerHeight,
            opacity: Number(getComputedStyle(element).opacity),
            top: element.offsetTop, height: element.offsetHeight,
        }))""")
        assert all(card["opacity"] == (1 if card["visible"] else 0) for card in before)

        frames = page.evaluate("""async () => {
            const cards = [...document.querySelectorAll('.admin-dashboard-card')];
            const frames = [];
            const end = document.documentElement.scrollHeight - innerHeight;
            const sample = () => cards.map(card => Number(getComputedStyle(card).opacity));
            frames.push(sample());
            for (let y = 0; y <= end + 24; y += 24) {
                window.scrollTo({top: y, behavior: 'instant'});
                await new Promise(requestAnimationFrame);
                frames.push(sample());
            }
            return frames;
        }""")
        for earlier, later in pairwise(frames):
            assert all(after >= before - 0.001 for before, after in zip(earlier, later, strict=True))
        page.wait_for_function("""() => [...document.querySelectorAll('.admin-dashboard-card')]
            .every(card => getComputedStyle(card).opacity === '1' && !card.getAnimations().length)""")
        assert cards.evaluate_all("elements => elements.map(e => ({top:e.offsetTop,height:e.offsetHeight}))") == [
            {"top": card["top"], "height": card["height"]} for card in before
        ]
        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        page.evaluate("""document.dispatchEvent(new CustomEvent('htmx:afterSettle', {
            detail: {elt: document.querySelector('main')}
        }))""")
        assert cards.evaluate_all(
            "elements => elements.every(e => getComputedStyle(e).opacity === '1' && !e.getAnimations().length)"
        )
        dimensions = page.evaluate(
            "({width:document.documentElement.clientWidth, scrollWidth:document.documentElement.scrollWidth})"
        )
        assert dimensions["scrollWidth"] <= dimensions["width"] + 1, dimensions


def test_admin_reveals_respect_focus_and_changed_motion_preference(page: Page) -> None:
    """Reveal focused cards and honor runtime reduced-motion changes."""
    email, password = _create_verified_user(page, prefix="admin-motion-focus", admin=True)
    _login_as_user(page, email=email, password=password)
    page.set_viewport_size({"width": 390, "height": 720})
    page.goto(f"{BASE_URL}/admin/index")
    cards = page.locator(".admin-dashboard-card")
    expect(cards.last).to_have_css("opacity", "0")
    link = cards.last.get_by_role("link")
    link.focus()
    expect(link).to_be_focused()
    expect(cards.last).to_have_css("opacity", "1")
    assert not cards.last.evaluate("""element => element.getAnimations().some(animation =>
        animation.effect.getKeyframes().some(frame => 'opacity' in frame || 'translate' in frame))""")

    page.goto(f"{BASE_URL}/admin/index")
    page.emulate_media(reduced_motion="reduce")
    expect(cards.last).to_have_css("opacity", "1")
    assert cards.evaluate_all("elements => elements.every(e => !e.getAnimations().length)")
    page.reload()
    assert cards.evaluate_all(
        "elements => elements.every(e => getComputedStyle(e).opacity === '1' && !e.getAnimations().length)"
    )
    page.emulate_media(reduced_motion="no-preference")
    assert cards.evaluate_all(
        "elements => elements.every(e => getComputedStyle(e).opacity === '1' && !e.getAnimations().length)"
    )
