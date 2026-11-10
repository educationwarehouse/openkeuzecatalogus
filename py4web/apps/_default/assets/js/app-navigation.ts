import { clear_catalog_history } from "./catalog-history";

interface HtmxDetail {
    elt: HTMLElement;
    target: HTMLElement;
    xhr: XMLHttpRequest;
    boosted?: boolean;
    successful?: boolean;
    shouldSwap?: boolean;
    isError?: boolean;
    serverResponse?: string;
    swapOverride?: string;
    selectOverride?: string;
    requestConfig?: {
        boosted?: boolean;
        verb?: string;
    };
    issueRequest?: (skip_confirmation: boolean) => void;
}

interface HtmxRuntime {
    config: Record<string, unknown>;
    ajax: (method: string, url: string, options: Record<string, string>) => Promise<void>;
    process: ($element: Element) => void;
}

interface BootstrapComponent {
    getInstance: ($element: Element) => { dispose: () => void } | null;
}

declare const ContentTools: {
    EditorApp: {
        get: () => {
            syncRegions: () => void;
        };
    };
};

declare global {
    interface Window {
        bootstrap: Record<string, BootstrapComponent>;
        htmx: HtmxRuntime;
        okl_page: AbortController;
        on_okl_ready: (callback: () => void) => void;
        okl_track_save: <T>(request: Promise<T>) => Promise<T>;
        okl_assets: Set<Promise<void>>;
    }
}
const runtime = window.htmx;
const preference = matchMedia("(prefers-reduced-motion: reduce)");
const saves = new Set<Promise<unknown>>();
const save_requests = new WeakMap<XMLHttpRequest, (successful: boolean) => void>();
const positions = new Map<string, number>();
const partial_loaders = new Map<XMLHttpRequest, number>();
const error_pages = new WeakMap<XMLHttpRequest, string>();
let last_input = 0;
let failed_save = false;
let previous_url = location.href;
let page_url = location.href;
let navigation = false;
let loading_timer: number | undefined;
let loading_hide_timer: number | undefined;
let loading_started = 0;
let restoring_catalog = false;
let navigation_hash = "";
let catalog_switch_scroll: number | undefined;
let incoming_head: Document | null = null;

function hash_target(): HTMLElement | null {
    if (!location.hash) {
        return null;
    }
    try {
        return document.getElementById(decodeURIComponent(location.hash.slice(1)));
    } catch {
        return null;
    }
}

function resource_key($element: Element): string | null {
    if ($element.matches("script[src]")) {
        return `script:${$element.getAttribute("src")}`;
    }
    if ($element.matches('link[rel="stylesheet"]')) {
        return `style:${$element.getAttribute("href")}`;
    }
    return null;
}

function has_resource(root: ParentNode, key: string): boolean {
    return Array.from(root.querySelectorAll('script[src], link[rel="stylesheet"]')).some(($element) => {
        return resource_key($element) === key;
    });
}

// catalog-history opts completed public overviews in; private forms stay uncached.
runtime.config.historyCacheSize = 4;
runtime.config.historyRestoreAsHxRequest = false;
runtime.config.scrollIntoViewOnBoost = false;
runtime.config.defaultFocusScroll = false;
runtime.config.timeout = 30000;
// The shell restores scroll after its asynchronous swaps; native restoration races it.
history.scrollRestoration = "manual";
window.okl_track_save = function <T>(request: Promise<T>): Promise<T> {
    saves.add(request);
    request
        .then(
            () => {
                failed_save = false;
            },
            () => {
                failed_save = true;
            },
        )
        .finally(() => {
            return saves.delete(request);
        });
    return request;
};

function announce(message: string): void {
    const $status = document.getElementById("okl-page-status");
    if ($status) {
        $status.textContent = message;
    }
}

function set_loading(loading: boolean): void {
    const $indicator = document.querySelector<HTMLElement>(".okl-navigation-progress");
    clearTimeout(loading_hide_timer);
    document.querySelector("main")?.toggleAttribute("aria-busy", loading);
    if (!$indicator) {
        return;
    }
    if (loading) {
        if ($indicator.hidden) {
            loading_started = performance.now();
        }
        $indicator.hidden = false;
    } else if (!$indicator.hidden) {
        // Keep a visible indicator long enough to avoid a flash near the request threshold.
        const remaining = Math.max(0, 400 - (performance.now() - loading_started));
        loading_hide_timer = window.setTimeout(() => {
            $indicator.hidden = true;
        }, remaining);
    }
}

function prepare_page(root: ParentNode = document): void {
    // A complete page already contains its grid footer; OOB applies only to partial responses.
    if (root instanceof Document && root !== document) {
        root.querySelectorAll("[hx-swap-oob]").forEach(($element) => {
            return $element.removeAttribute("hx-swap-oob");
        });
    }
    root.querySelectorAll<HTMLAnchorElement>("a[href]").forEach(($link) => {
        if (
            $link.hasAttribute("download") ||
            $link.target ||
            /\.(pdf|csv|xlsx?)$|\/(logout|impersonate|stop_impersonate|archive|entree)(\/|\?|$)/.test($link.pathname)
        ) {
            $link.setAttribute("hx-boost", "false");
        } else if (!$link.matches("[hx-get], [hx-post]") && !$link.getAttribute("href")?.startsWith("#")) {
            $link.setAttribute("hx-push-url", "true");
        }
    });
    // File uploads and external identity-provider handoffs retain native submission.
    root.querySelectorAll<HTMLFormElement>('form[enctype="multipart/form-data"]').forEach(($form) => {
        return $form.setAttribute("hx-boost", "false");
    });
    root.querySelectorAll<HTMLFormElement>('form:not([hx-get]):not([hx-post]):not([hx-boost="false"])').forEach(
        ($form) => {
            return $form.setAttribute("hx-push-url", "true");
        },
    );
    // A partial request inside a boosted form must not inherit its navigation history.
    root.querySelectorAll<HTMLElement>("[hx-get], [hx-post], [hx-put], [hx-patch], [hx-delete]").forEach(($element) => {
        if (!$element.hasAttribute("hx-push-url")) {
            $element.setAttribute("hx-push-url", "false");
        }
    });
    const $header = root.querySelector<HTMLElement>(".okl-site-header");
    if ($header) {
        $header.style.viewTransitionName = "okl-header";
    }
    const $title = root.querySelector<HTMLElement>(".wizard-process-shell h1");
    if ($title) {
        $title.style.viewTransitionName = "okl-step-title";
    }
    const $artwork = root.querySelector<HTMLElement>(".okl-process-artwork");
    if ($artwork) {
        $artwork.style.viewTransitionName = "okl-step-artwork";
    }
    const $step_content = root.querySelector<HTMLElement>(".wizard-process-shell .wizard-process-container");
    if ($step_content) {
        $step_content.style.viewTransitionName = "okl-step-content";
    }
    const $step_controls = root.querySelector<HTMLElement>(".wizard-process-shell .autosave-toolbar");
    if ($step_controls) {
        $step_controls.style.viewTransitionName = "okl-step-controls";
    }
    const $stepper = root.querySelector<HTMLElement>(".wizard-process-stepper-wrap");
    if ($stepper) {
        $stepper.style.viewTransitionName = "okl-step-navigation";
    }
    const $indicator = root.querySelector<HTMLElement>(".step-lines .active");
    if ($indicator) {
        $indicator.style.viewTransitionName = "okl-step-indicator";
    }
    const $cover = root.querySelector<HTMLElement>(".okl-detail-media img");
    if ($cover) {
        $cover.style.viewTransitionName = "okl-product-cover";
    }
}

function prepare_return_cover(root: ParentNode): void {
    const $link = Array.from(root.querySelectorAll<HTMLAnchorElement>(".catalog-result-item a[href]")).find(($link) => {
        return new URL($link.getAttribute("href") || "", location.origin).href === previous_url;
    });
    const $cover = $link?.closest(".catalog-result-item")?.querySelector<HTMLElement>("img");
    if ($cover) {
        $cover.style.viewTransitionName = "okl-product-cover";
    }
}

function cleanup_page(): void {
    document.querySelectorAll<HTMLDialogElement>("dialog[open]").forEach(($dialog) => {
        return $dialog.close();
    });
    window.okl_page.abort();
    window.okl_page = new AbortController();
    const components = window.bootstrap;
    const selectors = {
        Modal: ".modal",
        Offcanvas: ".offcanvas",
        Tooltip: '[data-bs-toggle="tooltip"]',
        Popover: '[data-bs-toggle="popover"]',
        Collapse: ".collapse",
        Dropdown: '[data-bs-toggle="dropdown"]',
    };
    Object.entries(selectors).forEach(([component, selector]) => {
        document.querySelectorAll(selector).forEach(($element) => {
            components[component].getInstance($element)?.dispose();
        });
    });
    document.documentElement.classList.remove("okl-navigation-open");
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("overflow");
    document.body.style.removeProperty("padding-right");
    ["position", "inset-inline", "top"].forEach((property) => {
        return document.body.style.removeProperty(property);
    });
    document.querySelectorAll(".modal-backdrop, .popover, .tooltip").forEach(($element) => {
        return $element.remove();
    });
}

// htmx owns its history entries; the whitelabel form-state listener only owns legacy entries.
window.addEventListener(
    "popstate",
    (event) => {
        if (event.state?.htmx) {
            event.stopImmediatePropagation();
            // A cached catalogue must not bypass the existing autosave wait/error path.
            if (saves.size || failed_save || Date.now() - last_input < 800) {
                clear_catalog_history();
            }
            window.onpopstate?.call(window, event);
        }
    },
    { capture: true },
);

function assets_changed(response: Document): boolean {
    const selector = 'script[src*="/js/bundled-latest.js"]';
    return (
        response.querySelector(selector)?.getAttribute("src") !== document.querySelector(selector)?.getAttribute("src")
    );
}

// The content editor serializes attributes in a different order. Head support
// compares outerHTML, which would otherwise execute the same bundle again.
document.addEventListener("htmx:beforeHeadMerge", (event) => {
    const detail = (
        event as CustomEvent<{
            xhr?: XMLHttpRequest;
            serverResponse?: string;
            item?: {
                head?: string;
            };
        }>
    ).detail;
    const response = detail.xhr?.response || detail.serverResponse || detail.item?.head;
    incoming_head = response ? new DOMParser().parseFromString(response, "text/html") : null;
});
document.addEventListener("htmx:removingHeadElement", (event) => {
    const { headElement } = (
        event as CustomEvent<{
            headElement: Element;
        }>
    ).detail;
    const key = resource_key(headElement);
    if (key && (headElement.matches("script[src]") || (incoming_head && has_resource(incoming_head, key)))) {
        event.preventDefault();
    }
});
document.addEventListener("htmx:addingHeadElement", (event) => {
    const { headElement } = (
        event as CustomEvent<{
            headElement: DocumentFragment;
        }>
    ).detail;
    const $element = headElement.firstElementChild;
    const key = $element && resource_key($element);
    if (key && has_resource(document.head, key)) {
        event.preventDefault();
        return;
    }
    headElement.querySelectorAll('script[src], link[rel="stylesheet"]').forEach(($element) => {
        const url = new URL($element.getAttribute("src") || $element.getAttribute("href") || "", location.href);
        if (url.origin !== location.origin) {
            return;
        }
        const pending = new Promise<void>((resolve) => {
            $element.addEventListener(
                "load",
                () => {
                    return resolve();
                },
                { once: true },
            );
            $element.addEventListener(
                "error",
                () => {
                    location.reload();
                    resolve();
                },
                { once: true },
            );
        });
        window.okl_assets.add(pending);
        pending.finally(() => {
            return window.okl_assets.delete(pending);
        });
    });
});
document.addEventListener(
    "input",
    (event) => {
        if (
            event.target instanceof Element &&
            event.target.closest('[data-autosave="true"], .attach-points-page, #priorities')
        ) {
            last_input = Date.now();
        }
    },
    true,
);
document.addEventListener("htmx:confirm", async (event) => {
    const detail = (event as CustomEvent<HtmxDetail>).detail;
    if (
        !(detail.elt instanceof HTMLAnchorElement) ||
        detail.elt.matches("[hx-get], [hx-post]") ||
        !detail.issueRequest
    ) {
        return;
    }
    if (document.body.classList.contains("content-edit-activated")) {
        event.preventDefault();
        announce("Rond het bewerken van de tekst af voordat je verdergaat.");
        return;
    }
    if (!saves.size && Date.now() - last_input >= 800 && !failed_save) {
        return;
    }
    event.preventDefault();
    announce("Wijzigingen opslaan…");
    await new Promise((resolve) => setTimeout(resolve, Math.max(0, 800 - (Date.now() - last_input))));
    while (saves.size) {
        await Promise.allSettled([...saves]);
    }
    if (failed_save) {
        announce("Opslaan is niet gelukt. Probeer de wijziging opnieuw voordat je verdergaat.");
        const $feedback = document.querySelector<HTMLElement>(".autosave-error:not(.d-none)");
        $feedback?.setAttribute("tabindex", "-1");
        $feedback?.focus();
        return;
    }
    detail.issueRequest(true);
});
function start_request(event: Event): void {
    if (event.defaultPrevented) {
        return;
    }
    const detail = (event as CustomEvent<HtmxDetail>).detail;
    if (
        detail.requestConfig?.verb !== "get" &&
        detail.elt.closest('[data-autosave="true"], .attach-points-page, #priorities')
    ) {
        const pending = new Promise<boolean>((resolve) => save_requests.set(detail.xhr, resolve));
        saves.add(pending);
        pending.then((successful) => {
            failed_save = !successful;
            saves.delete(pending);
        });
    }
    if (!(detail.boosted || detail.requestConfig?.boosted)) {
        const $background =
            detail.elt.matches('[hx-trigger*="every"], [hx-trigger="ew:repoll"]') ||
            detail.elt.closest('[data-autosave="true"], .attach-points-page, #priorities');
        if (!$background) {
            const timer = window.setTimeout(() => {
                return set_loading(true);
            }, 180);
            partial_loaders.set(detail.xhr, timer);
        }
        return;
    }
    navigation = true;
    restoring_catalog = false;
    catalog_switch_scroll = detail.target.matches(".okl-catalog-page") ? scrollY : undefined;
    document.documentElement.dataset.oklNavigating = "true";
    positions.set(location.href, scrollY);
    previous_url = location.href;
    clearTimeout(loading_timer);
    loading_timer = window.setTimeout(() => {
        set_loading(true);
        announce("Pagina laden…");
    }, 180);
    const $link = detail.elt.closest<HTMLAnchorElement>("a[href]");
    navigation_hash = $link?.hash || "";
    document.querySelectorAll("[data-okl-history-focus]").forEach(($element) => {
        return $element.removeAttribute("data-okl-history-focus");
    });
    if ($link?.closest(".catalog-result-item")) {
        $link.dataset.oklHistoryFocus = "true";
    }
    const $current = document.querySelector(".steps [aria-current=step]");
    const $steps = Array.from(document.querySelectorAll(".steps .step"));
    const $destination =
        $link &&
        $steps.find(($step) => {
            return $step instanceof HTMLAnchorElement && $step.href === $link.href;
        });
    const backward =
        $link?.classList.contains("autosave-nav-btn--prev") ||
        ($current && $destination && $steps.indexOf($destination) < $steps.indexOf($current));
    document.documentElement.dataset.oklDirection = backward ? "back" : "forward";
    const $cover = $link?.closest(".catalog-result-item")?.querySelector<HTMLElement>("img");
    if ($cover) {
        $cover.style.viewTransitionName = "okl-product-cover";
    }
}
document.addEventListener("htmx:beforeRequest", (event) => {
    // Observe cancellation after every listener has had a chance to prevent the request.
    queueMicrotask(() => start_request(event));
});
document.addEventListener("htmx:beforeSwap", (event) => {
    const detail = (event as CustomEvent<HtmxDetail>).detail;
    const response = new DOMParser().parseFromString(detail.serverResponse || "", "text/html");
    const full_page_error = detail.xhr.status >= 400 && response.querySelector("main .error-page");
    if (!detail.requestConfig?.boosted && !full_page_error) {
        return;
    }

    if (full_page_error) {
        // A complete error document must escape partial targets and inherited selectors.
        detail.target = document.body;
        detail.selectOverride = "unset";
        detail.shouldSwap = true;
        detail.isError = true;
        if (!detail.requestConfig?.boosted) {
            positions.set(location.href, scrollY);
            previous_url = location.href;
            navigation_hash = "";
            catalog_switch_scroll = undefined;
            restoring_catalog = false;
            navigation = true;
            error_pages.set(detail.xhr, detail.xhr.responseURL);
        }
    }
    if (!detail.shouldSwap && detail.xhr.status >= 400) {
        // htmx skips 4xx/5xx swaps, which would leave the previous page on screen. Show the
        // error page (and its ticket) as a full page load would.
        if (!response.querySelector("main")) {
            // Not one of our pages (e.g. a proxy error): let the browser render it.
            if (detail.requestConfig?.verb === "get") {
                event.preventDefault();
                location.assign(detail.xhr.responseURL);
            }
            return;
        }
        detail.shouldSwap = true;
        detail.isError = false;
    }
    if (!detail.shouldSwap || !response.querySelector("main")) {
        return;
    }
    document.documentElement.dataset.oklNavigationKind =
        document.querySelector(".wizard-process-shell--stepped") &&
        response.querySelector(".wizard-process-shell--stepped")
            ? "wizard"
            : "page";
    // A deployment replaces the running bundle as one document, never halfway through a swap.
    if (assets_changed(response)) {
        event.preventDefault();
        location.assign(detail.xhr.responseURL);
        return;
    }
    prepare_page(response);
    prepare_return_cover(response);
    detail.serverResponse = response.documentElement.outerHTML;
    if (detail.target.matches(".okl-catalog-page")) {
        // Keep the shared header/footer in place when changing catalogue type.
        detail.swapOverride = "outerHTML show:none";
        return;
    }
    detail.swapOverride = preference.matches ? "innerHTML show:none" : "innerHTML transition:true show:none";
    cleanup_page();
});
document.addEventListener("htmx:afterSwap", (event) => {
    const detail = (event as CustomEvent<HtmxDetail>).detail;
    const error_url = error_pages.get(detail.xhr);
    if (error_url) {
        if (location.href !== error_url) {
            history.pushState({ htmx: true }, "", error_url);
        }
        error_pages.delete(detail.xhr);
    }
});
document.addEventListener("htmx:beforeTransition", (event) => {
    if (preference.matches) {
        event.preventDefault();
    }
});
document.addEventListener("htmx:afterRequest", (event) => {
    const detail = (event as CustomEvent<HtmxDetail>).detail;
    save_requests.get(detail.xhr)?.(Boolean(detail.successful));
    const partial_timer = partial_loaders.get(detail.xhr);
    if (partial_timer !== undefined) {
        clearTimeout(partial_timer);
        partial_loaders.delete(detail.xhr);
        if (!partial_loaders.size && !navigation) {
            set_loading(false);
        }
    }
    if (detail.requestConfig?.boosted && !detail.successful) {
        clearTimeout(loading_timer);
        navigation = false;
        delete document.documentElement.dataset.oklNavigating;
        if (!partial_loaders.size) {
            set_loading(false);
        }
        announce("De pagina kon niet worden geladen. Probeer de link opnieuw.");
    }
});

function finish_navigation(): void {
    navigation = false;
    clearTimeout(loading_timer);
    delete document.documentElement.dataset.oklNavigating;
    if (!partial_loaders.size) {
        set_loading(false);
    }
    const $heading =
        document.querySelector<HTMLElement>("main h1") ||
        document.querySelector<HTMLElement>("main h2") ||
        document.querySelector<HTMLElement>("main");
    $heading?.setAttribute("tabindex", "-1");
    const $return_link = restoring_catalog && document.querySelector<HTMLElement>("[data-okl-history-focus]");
    ($return_link || $heading)?.focus({ preventScroll: true });
    if (navigation_hash && !location.hash) {
        history.replaceState(history.state, "", location.href + navigation_hash);
    }
    navigation_hash = "";
    const $hash = hash_target();
    if ($hash) {
        $hash.scrollIntoView({ behavior: "instant" });
    } else {
        window.scrollTo({ top: catalog_switch_scroll ?? positions.get(location.href) ?? 0, behavior: "instant" });
    }
    catalog_switch_scroll = undefined;
    announce($heading?.matches("h1, h2") ? $heading.innerText.trim().replace(/\s+/g, " ") : document.title);
    document.dispatchEvent(new CustomEvent("okl:navigated", { detail: { from: previous_url, to: location.href } }));
    page_url = location.href;
}

document.addEventListener("htmx:historyCacheHit", (event) => {
    navigation_hash = "";
    catalog_switch_scroll = undefined;
    const detail = (
        event as CustomEvent<{
            item: {
                scroll: number;
            };
            swapSpec: {
                transition?: boolean;
                scroll?: number;
            };
        }>
    ).detail;
    positions.set(page_url, scrollY);
    previous_url = page_url;
    const scroll = positions.get(location.href) ?? detail.item.scroll;
    positions.set(location.href, scroll);
    // finish_navigation restores instantly after controls initialize, without a second smooth scroll.
    delete detail.swapSpec.scroll;
    restoring_catalog = true;
    navigation = true;
    // Back/forward restores the existing view immediately, including during a swipe.
    detail.swapSpec.transition = false;
    cleanup_page();
});
document.addEventListener("htmx:afterSettle", (event) => {
    return window.on_okl_ready(() => {
        const detail = (event as CustomEvent<HtmxDetail>).detail;
        prepare_page(detail.elt || document);
        if (detail.elt?.matches(".okl-catalog-page") && detail.elt.querySelector("[data-editable]")) {
            ContentTools.EditorApp.get().syncRegions();
        }
        // Restore focus/scroll after the other settle listeners have rebuilt the controls.
        if (event.target === document.body || (navigation && detail.elt?.matches(".okl-catalog-page"))) {
            queueMicrotask(finish_navigation);
        }
    });
});
document.addEventListener("htmx:historyCacheMiss", async (event) => {
    navigation_hash = "";
    catalog_switch_scroll = undefined;
    const detail = (
        event as CustomEvent<{
            xhr: XMLHttpRequest;
        }>
    ).detail;
    event.preventDefault();
    restoring_catalog = false;
    positions.set(page_url, scrollY);
    previous_url = page_url;
    navigation = true;
    document.documentElement.dataset.oklNavigating = "true";
    const current_step = Number(/\/fase(\d+)$/.exec(page_url)?.[1] || 0);
    const next_step = Number(/\/fase(\d+)$/.exec(location.href)?.[1] || 0);
    document.documentElement.dataset.oklDirection = next_step < current_step ? "back" : "forward";
    loading_timer = window.setTimeout(() => {
        return set_loading(true);
    }, 180);
    await new Promise((resolve) => setTimeout(resolve, Math.max(0, 800 - (Date.now() - last_input))));
    while (saves.size) {
        await Promise.allSettled([...saves]);
    }
    if (failed_save) {
        clearTimeout(loading_timer);
        navigation = false;
        delete document.documentElement.dataset.oklNavigating;
        set_loading(false);
        history.pushState({ htmx: true }, "", page_url);
        announce("Opslaan is niet gelukt. Probeer de wijziging opnieuw voordat je verdergaat.");
        return;
    }
    detail.xhr.send();
});
document.addEventListener("htmx:historyCacheMissLoad", (event) => {
    const detail = (
        event as CustomEvent<{
            response: string;
            swapSpec: {
                transition?: boolean;
            };
        }>
    ).detail;
    const response = new DOMParser().parseFromString(detail.response, "text/html");
    document.documentElement.dataset.oklNavigationKind =
        document.querySelector(".wizard-process-shell--stepped") &&
        response.querySelector(".wizard-process-shell--stepped")
            ? "wizard"
            : "page";
    if (assets_changed(response)) {
        detail.response = document.documentElement.outerHTML;
        location.reload();
        return;
    }
    prepare_page(response);
    prepare_return_cover(response);
    detail.response = response.documentElement.outerHTML;
    detail.swapSpec.transition = !preference.matches;
    cleanup_page();
});
document.addEventListener("htmx:historyCacheMissLoadError", () => {
    location.reload();
});
window.on_okl_ready(() => {
    prepare_page();
    hash_target()?.scrollIntoView({ behavior: "instant" });
});
