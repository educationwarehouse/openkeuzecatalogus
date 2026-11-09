const $initialized_headers = new WeakSet<HTMLElement>();

function initialize_platform_navigation(): void {
    const $header = document.querySelector<HTMLElement>(".okl-site-header");
    if (!$header || $initialized_headers.has($header)) {
        return;
    }
    initialize_active_platform_navigation($header);
}

function initialize_active_platform_navigation($header: HTMLElement): void {
    $header.classList.add("is-navigation-ready");
    $initialized_headers.add($header);
    const { signal } = window.okl_page;
    const observers: ResizeObserver[] = [];
    signal.addEventListener(
        "abort",
        () => {
            return observers.forEach((observer) => {
                return observer.disconnect();
            });
        },
        { once: true },
    );
    const location_label =
        $header.querySelector<HTMLElement>(".okl-header-location strong")?.textContent?.trim() || "Menu";
    const $toggle = $header.querySelector<HTMLButtonElement>(".okl-navigation__toggle");
    const desktop_navigation = window.matchMedia("(min-width: 1200px)");
    const $dropdowns = Array.from($header.querySelectorAll<HTMLDetailsElement>(".okl-navigation__dropdown"));

    function close_dropdowns(): void {
        $dropdowns.forEach(($dropdown) => {
            $dropdown.open = false;
        });
    }

    $dropdowns.forEach(($dropdown) => {
        $dropdown.addEventListener("toggle", () => {
            if ($dropdown.open) {
                $dropdowns.forEach(($other) => {
                    if ($other !== $dropdown) {
                        $other.open = false;
                    }
                });
            }
        });
    });
    document.addEventListener(
        "click",
        (event) => {
            if (!(event.target instanceof Element)) {
                return;
            }
            if (!event.target.closest(".okl-navigation__dropdown") || event.target.closest("a[href]")) {
                close_dropdowns();
            }
        },
        { signal },
    );
    document.addEventListener(
        "keydown",
        (event) => {
            if (event.key !== "Escape") {
                return;
            }
            const $open_dropdown = $dropdowns.find(($dropdown) => {
                return $dropdown.open;
            });
            if ($open_dropdown) {
                close_dropdowns();
                $open_dropdown.querySelector("summary")?.focus();
            }
        },
        { signal },
    );
    const $drawer = $header.querySelector<HTMLElement>(".okl-navigation__drawer");
    const $backdrop = $header.querySelector<HTMLElement>(".okl-navigation__backdrop");
    if ($toggle && $drawer && $backdrop && "inert" in HTMLElement.prototype) {
        const $navigation_toggle = $toggle;
        const $navigation_drawer = $drawer;
        const $navigation_backdrop = $backdrop;
        let menu_open = false;
        const $background = new Map<HTMLElement, boolean>();
        const original_role = $header.getAttribute("role");
        $header.classList.add("has-navigation");
        $toggle.hidden = false;
        $drawer.hidden = false;
        $backdrop.hidden = false;
        const $context = $header.querySelector<HTMLElement>(".okl-header-location");
        if ($context) {
            $context.hidden = false;
        }
        $navigation_toggle.setAttribute("aria-label", `Menu openen — ${location_label}`);

        function update_header_position(): void {
            if (menu_open) {
                $header.style.setProperty("--okl-header-bottom", `${$header.getBoundingClientRect().bottom}px`);
            }
        }

        function set_menu_open(open: boolean, restore_focus = true): void {
            if (open && desktop_navigation.matches) {
                return;
            }
            menu_open = open;
            $header.classList.toggle("is-navigation-open", open);
            $navigation_toggle.setAttribute("aria-expanded", String(open));
            $navigation_toggle.setAttribute("aria-label", `Menu ${open ? "sluiten" : "openen"} — ${location_label}`);
            $navigation_drawer.inert = !open;
            document.documentElement.classList.toggle("okl-navigation-open", open);
            if (open) {
                $header.classList.remove("is-hidden");
                $header.setAttribute("role", "dialog");
                $header.setAttribute("aria-modal", "true");
                $header.setAttribute("aria-labelledby", "okl-navigation-title");
                let $branch: HTMLElement = $header;
                while ($branch.parentElement && $branch !== document.body) {
                    Array.from($branch.parentElement.children).forEach(($sibling) => {
                        if (!($sibling instanceof HTMLElement) || $sibling === $branch) {
                            return;
                        }
                        $background.set($sibling, $sibling.inert);
                        $sibling.inert = true;
                    });
                    $branch = $branch.parentElement;
                }
                update_header_position();
            } else {
                if (original_role) {
                    $header.setAttribute("role", original_role);
                } else {
                    $header.removeAttribute("role");
                }
                $header.removeAttribute("aria-modal");
                $header.removeAttribute("aria-labelledby");
                $background.forEach((inert, $element) => {
                    $element.inert = inert;
                });
                $background.clear();
                if (restore_focus) {
                    $navigation_toggle.focus({ preventScroll: true });
                }
            }
        }

        $navigation_toggle.addEventListener("click", () => {
            return set_menu_open(!menu_open);
        });
        desktop_navigation.addEventListener(
            "change",
            () => {
                if (menu_open) {
                    set_menu_open(false, false);
                    const $focus_target = desktop_navigation.matches
                        ? $header.querySelector<HTMLAnchorElement>(".okl-navigation__fallback > a[aria-current]") ||
                          $header.querySelector<HTMLAnchorElement>(".okl-navigation__fallback > a")
                        : $header.querySelector<HTMLAnchorElement>(".okl-header-logo");
                    $focus_target?.focus({ preventScroll: true });
                }
                close_dropdowns();
            },
            { signal },
        );
        $navigation_backdrop.addEventListener("click", () => {
            return set_menu_open(false);
        });
        $navigation_drawer.addEventListener("click", (event) => {
            if (event.target instanceof Element && event.target.closest("a[href]")) {
                set_menu_open(false);
            }
        });
        $header.querySelector<HTMLAnchorElement>(".okl-header-logo")?.addEventListener("click", () => {
            if (menu_open) {
                set_menu_open(false);
            }
        });
        document.addEventListener(
            "keydown",
            (event) => {
                if (!menu_open) {
                    return;
                }
                if (event.key === "Escape") {
                    event.preventDefault();
                    set_menu_open(false);
                    return;
                }
                if (event.key !== "Tab") {
                    return;
                }
                const $controls = Array.from(
                    $header.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex="0"]'),
                ).filter(($element) => {
                    return $element.getClientRects().length > 0;
                });
                const $first = $controls[0];
                const $last = $controls[$controls.length - 1];
                if (event.shiftKey && document.activeElement === $first) {
                    event.preventDefault();
                    $last?.focus();
                } else if (!event.shiftKey && document.activeElement === $last) {
                    event.preventDefault();
                    $first?.focus();
                }
            },
            { signal },
        );
        window.addEventListener("resize", update_header_position, { passive: true, signal });
        if ("ResizeObserver" in window) {
            const observer = new ResizeObserver(update_header_position);
            observer.observe($header);
            observers.push(observer);
        }
    }
    const $main = document.querySelector<HTMLElement>("main.okl-app");
    const $hero = $main?.querySelector<HTMLElement>(
        ":scope > .okl-catalog-page > .okl-catalog-hero, :scope > .comparison-page > .comparison-hero, :scope > .okl-detail-page > .okl-detail-hero, :scope > .wizard-process-shell--stepped, :scope > .wizard-start-page, :scope > .okl-vision-page > .okl-vision-hero",
    );
    const $first_content =
        $main &&
        Array.from($main.children).find(($child) => {
            return !$child.matches("style, script, link");
        });
    if ($main && $hero && ($first_content === $hero || $first_content === $hero.parentElement)) {
        const $hero_main = $main;

        function update_hero_header_height(): void {
            $hero_main.style.setProperty("--okl-header-height", `${$header.getBoundingClientRect().height}px`);
        }

        update_hero_header_height();
        $main.classList.add("has-hero-backdrop");
        $header.classList.add("has-hero-backdrop");
        window.addEventListener("resize", update_hero_header_height, { passive: true, signal });
        if ("ResizeObserver" in window) {
            const observer = new ResizeObserver(update_hero_header_height);
            observer.observe($header);
            observers.push(observer);
        }
    }
    $header.classList.toggle("is-scrolled", window.scrollY > 8);
    let previous_y = window.scrollY;
    let direction_start = previous_y;
    let direction = 0;
    window.addEventListener(
        "scroll",
        () => {
            const y = Math.max(0, window.scrollY);
            const next_direction = Math.sign(y - previous_y);
            if (next_direction !== direction) {
                direction_start = previous_y;
            }
            const menu_open = $header.querySelector('[aria-expanded="true"], .okl-navigation__dropdown[open]') !== null;
            if (Math.abs(y - direction_start) > 12 || y < $header.offsetHeight) {
                $header.classList.toggle("is-hidden", next_direction > 0 && y > $header.offsetHeight && !menu_open);
            }
            $header.classList.toggle("is-scrolled", y > 8);
            previous_y = y;
            direction = next_direction;
        },
        { passive: true, signal },
    );
}

window.on_okl_ready(initialize_platform_navigation);
document.addEventListener("htmx:afterSwap", () => {
    return window.on_okl_ready(initialize_platform_navigation);
});
document.addEventListener("htmx:historyRestore", () => {
    return window.on_okl_ready(initialize_platform_navigation);
});
