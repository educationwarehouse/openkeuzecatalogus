const cover_image_selector = ".js-okl-cover-image";
const more_button_selector = ".js-okl-reveal-more";
const $initialized_reveal_lists = new WeakSet<HTMLElement>();

function reveal_batch_size($button: HTMLButtonElement): number {
    const batch_size = Number.parseInt($button.dataset.oklRevealBatch || "4", 10);
    return Number.isFinite(batch_size) && batch_size > 0 ? batch_size : 4;
}

function initialize_reveal_groups(): void {
    document.querySelectorAll<HTMLElement>(".js-okl-reveal-group").forEach(($group) => {
        const $button = $group.querySelector<HTMLButtonElement>(more_button_selector);
        const $list = $group.querySelector<HTMLElement>(".js-okl-reveal-list");
        if (!$button || !$list || $initialized_reveal_lists.has($list)) {
            return;
        }
        const batch_size = reveal_batch_size($button);
        const $items = $list.querySelectorAll<HTMLElement>(".js-okl-reveal-item");
        $items.forEach(($item, index) => {
            $item.hidden = index >= batch_size;
        });
        $button.hidden = $items.length <= batch_size;
        $button.setAttribute("aria-expanded", "false");
        $initialized_reveal_lists.add($list);
    });
}

function show_cover_fallback($image: HTMLImageElement): void {
    $image.hidden = true;
    const $fallback = $image.nextElementSibling;
    if ($fallback instanceof HTMLElement && $fallback.classList.contains("okl-cover-fallback")) {
        $fallback.hidden = false;
    }
}

function check_cover_image($image: HTMLImageElement): void {
    if ($image.complete && $image.naturalWidth === 0) {
        show_cover_fallback($image);
    }
}

document.addEventListener(
    "error",
    (event) => {
        const $target = event.target;
        if ($target instanceof HTMLImageElement && $target.matches(cover_image_selector)) {
            show_cover_fallback($target);
        }
    },
    true,
);
document.querySelectorAll<HTMLImageElement>(cover_image_selector).forEach(check_cover_image);
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize_reveal_groups, { once: true });
} else {
    initialize_reveal_groups();
}
document.addEventListener("htmx:afterSwap", (event) => {
    const $target = (
        event as CustomEvent<{
            target?: EventTarget;
        }>
    ).detail?.target;
    if ($target instanceof HTMLElement) {
        $target.querySelectorAll<HTMLImageElement>(cover_image_selector).forEach(check_cover_image);
    }
    initialize_reveal_groups();
});

function reveal_next_batch($button: HTMLButtonElement, user_activated: boolean, activated_with_keyboard = false): void {
    const $group = $button.closest<HTMLElement>(".js-okl-reveal-group");
    const $list = $group?.querySelector<HTMLElement>(".js-okl-reveal-list");
    if (!$list) {
        return;
    }
    const batch_size = reveal_batch_size($button);
    const $hidden_items = Array.from($list.querySelectorAll<HTMLElement>(".js-okl-reveal-item[hidden]"));
    $hidden_items.slice(0, batch_size).forEach(($item) => {
        $item.hidden = false;
    });
    const has_more_items = $list.querySelector(".js-okl-reveal-item[hidden]") !== null;
    const move_focus =
        user_activated && document.activeElement === $button && (!has_more_items || activated_with_keyboard);
    $button.setAttribute("aria-expanded", "true");
    $button.hidden = !has_more_items;
    if (!has_more_items) {
        const $catalog_link = $group?.querySelector<HTMLElement>(".js-okl-more-catalog");
        if ($catalog_link) {
            $catalog_link.classList.remove("d-none");
        }
    }
    if (move_focus) {
        const $first_item = $hidden_items[0];
        const $first_link =
            $first_item?.querySelector<HTMLAnchorElement>("h3 a[href], h4 a[href]") ??
            $first_item?.querySelector<HTMLAnchorElement>('a[href]:not([tabindex="-1"]):not([aria-hidden="true"])');
        $first_link?.focus({ preventScroll: !activated_with_keyboard });
    }
}

document.addEventListener("click", (event) => {
    const $target = event.target;
    const $button = $target instanceof Element ? $target.closest<HTMLButtonElement>(more_button_selector) : null;
    if ($button) {
        reveal_next_batch($button, true, event.detail === 0);
    }
});
