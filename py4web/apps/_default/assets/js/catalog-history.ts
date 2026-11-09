// Only completed public catalogue views may enter htmx's per-tab history cache.
export function clear_catalog_history(): void {
    try {
        sessionStorage.removeItem("htmx-history-cache");
    } catch {
        // With storage disabled, htmx falls back to a normal server request.
    }
}

clear_catalog_history();
const result_requests = new WeakMap<
    XMLHttpRequest,
    {
        filters: string;
        url: string;
    }
>();

function update_history_policy(): void {
    const $catalog = document.querySelector<HTMLElement>(".okl-catalog-page");
    if ($catalog?.dataset.catalogRendered === "true") {
        delete $catalog.dataset.catalogRendered;
        $catalog.dataset.oklHistoryReady = "true";
        $catalog.dataset.oklHistoryUrl = location.pathname + location.search;
        $catalog.dataset.oklHistoryFilters = filter_state();
    }
    const ready =
        $catalog?.dataset.oklHistoryReady === "true" && !document.body.classList.contains("content-edit-activated");
    if (ready) {
        document.body.removeAttribute("hx-history");
    } else {
        document.body.setAttribute("hx-history", "false");
    }
}

function filter_state(): string {
    const $form = document.querySelector<HTMLFormElement>(".js-catalog-filter-controls");
    const values: string[][] = [];
    if ($form) {
        new FormData($form).forEach((value, name) => {
            return values.push([name, String(value)]);
        });
    }
    return JSON.stringify(values);
}

function invalidate_catalog(force = false): void {
    const $catalog = document.querySelector<HTMLElement>(".okl-catalog-page");
    // A search field fires change again on blur, after its input request has completed.
    if (!force && $catalog?.dataset.oklHistoryFilters === filter_state()) {
        return;
    }
    if ($catalog) {
        delete $catalog.dataset.oklHistoryReady;
    }
    update_history_policy();
}

for (const name of ["input", "change", "reset"]) {
    document.addEventListener(name, (event) => {
        if (event.target instanceof Element && event.target.closest(".js-catalog-filter-controls")) {
            invalidate_catalog();
        }
    });
}
document.addEventListener("ew:state_changed", () => {
    return invalidate_catalog(true);
});
document.addEventListener("htmx:beforeRequest", (event) => {
    const detail = (
        event as CustomEvent<{
            target: HTMLElement;
            xhr: XMLHttpRequest;
        }>
    ).detail;
    if (!detail.target.matches("#product-results, #method-results")) {
        return;
    }
    result_requests.set(detail.xhr, { filters: filter_state(), url: location.pathname + location.search });
    invalidate_catalog(true);
});
document.addEventListener("htmx:afterSwap", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.matches("#product-results, #method-results")) {
        const $catalog = target.closest<HTMLElement>(".okl-catalog-page");
        const request = result_requests.get(
            (
                event as CustomEvent<{
                    xhr: XMLHttpRequest;
                }>
            ).detail.xhr,
        );
        if (
            $catalog &&
            request?.filters === filter_state() &&
            !$catalog.querySelector(".okl-skeleton, .catalog-results-feedback[role=alert]")
        ) {
            $catalog.dataset.oklHistoryReady = "true";
            $catalog.dataset.oklHistoryUrl = request.url;
            $catalog.dataset.oklHistoryFilters = request.filters;
        }
    }
    window.on_okl_ready(update_history_policy);
});
document.addEventListener("htmx:afterSettle", update_history_policy);
window.on_okl_ready(update_history_policy);
document.addEventListener("htmx:afterRequest", (event) => {
    const detail = (
        event as CustomEvent<{
            successful?: boolean;
            requestConfig?: {
                verb?: string;
            };
        }>
    ).detail;
    if (detail.successful && detail.requestConfig?.verb && detail.requestConfig.verb !== "get") {
        clear_catalog_history();
    }
});
document.addEventListener("htmx:historyItemCreated", (event) => {
    const { item, cache } = (
        event as CustomEvent<{
            item: {
                url: string;
                content: string;
            };
            cache: {
                url: string;
            }[];
        }>
    ).detail;
    const $catalog = document.querySelector<HTMLElement>(".okl-catalog-page");
    if (!$catalog?.dataset.oklHistoryUrl) {
        return;
    }
    // Filters replace the URL without an htmx push; save under the actual result URL.
    item.url = $catalog.dataset.oklHistoryUrl;
    for (let index = cache.length - 1; index >= 0; index--) {
        if (cache[index].url === item.url) {
            cache.splice(index, 1);
        }
    }
    const $snapshot = document.createElement("template");
    $snapshot.innerHTML = item.content;
    const root = $snapshot.content;
    root.querySelector(".okl-navigation-progress")?.setAttribute("hidden", "");
    root.querySelector("main")?.removeAttribute("aria-busy");
    root.querySelectorAll(".ct-widget, .modal-backdrop, .tooltip, .popover").forEach(($element) => {
        return $element.remove();
    });
    root.querySelectorAll("[hx-swap-oob]").forEach(($element) => {
        return $element.removeAttribute("hx-swap-oob");
    });
    root.querySelectorAll("header details[open]").forEach(($element) => {
        return $element.removeAttribute("open");
    });
    root.querySelectorAll<HTMLElement>(".catalog-result-item img").forEach(($image) => {
        return $image.style.removeProperty("view-transition-name");
    });
    root.querySelectorAll(".okl-select").forEach(($container) => {
        const $select = $container.querySelector("select");
        if (!$select) {
            return;
        }
        $select.classList.remove("okl-select__native");
        $select.removeAttribute("tabindex");
        $select.removeAttribute("aria-hidden");
        $container.replaceWith($select);
    });
    for (const attribute of [
        "data-enhanced-capsule-select",
        "data-enhanced-single-select",
        "data-catalog-filters-enhanced",
    ]) {
        root.querySelectorAll(`[${attribute}]`).forEach(($element) => {
            return $element.removeAttribute(attribute);
        });
    }
    root.querySelectorAll(".capsule-dropdown-menu.show").forEach(($menu) => {
        return $menu.classList.remove("show");
    });
    root.querySelectorAll(".capsule-dropdown .dropdown-toggle").forEach(($button) => {
        return $button.setAttribute("aria-expanded", "false");
    });
    const $filters = root.querySelector("#catalog-filters");
    // The snapshot already contains both responses; do not replay their initial loads.
    $filters?.removeAttribute("hx-trigger");
    $filters?.removeAttribute("hx-get");
    root.querySelectorAll("input[data-windowed-selection]").forEach(($input) => {
        return $input.parentElement?.remove();
    });
    const $form = root.querySelector<HTMLElement>(".js-catalog-filter-controls");
    if ($form) {
        $form.dataset.catalogRestored = "true";
    }
    item.content = $snapshot.innerHTML;
});
