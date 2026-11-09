// Keeps catalogue filter forms in sync with the URL and refreshes capsule select widgets after state changes.
import { refresh_multiselect_widget } from "./multiselectwidget";

declare const htmx: {
    trigger($target: Element, event_name: string): void;
};

const mobile_filter_media = window.matchMedia("(max-width: 991.98px)");

function focus_catalog_results() {
    const $results = document.querySelector<HTMLElement>(".okl-catalog-results");
    if (!$results) {
        return;
    }
    $results.focus({ preventScroll: true });
    $results.scrollIntoView({
        block: "start",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
}

function refresh_mobile_filters($form: HTMLFormElement) {
    const $panel = $form.closest<HTMLElement>(".okl-catalog-filter-panel");
    const $toggle = $panel?.querySelector<HTMLButtonElement>(".js-catalog-mobile-toggle");
    if (!$panel || !$toggle) {
        return;
    }
    const expanded = !mobile_filter_media.matches || $panel.dataset.mobileFiltersOpen === "true";
    $toggle.hidden = !mobile_filter_media.matches;
    $toggle.setAttribute("aria-expanded", String(expanded));
    $form.hidden = !expanded;
    const $label = $toggle.querySelector<HTMLElement>(".js-catalog-filter-toggle-label");
    if ($label) {
        $label.textContent = expanded ? "Filters sluiten" : "Filters tonen";
    }
    const active_fields = new Set<string>();
    new FormData($form).forEach((value, name) => {
        if (!["sort", "page", "view", "kind"].includes(name) && typeof value === "string" && value.trim()) {
            active_fields.add(name);
        }
    });
    const $count = $toggle.querySelector<HTMLElement>(".js-catalog-filter-count");
    if ($count) {
        $count.textContent = String(active_fields.size);
        $count.setAttribute("aria-label", `${active_fields.size} actieve filters`);
    }
}

mobile_filter_media.addEventListener("change", () => {
    document.querySelectorAll<HTMLFormElement>(".js-catalog-filter-controls").forEach(refresh_mobile_filters);
});
document.addEventListener("click", (event) => {
    const $target = event.target instanceof Element ? event.target : null;
    const $toggle = $target?.closest<HTMLButtonElement>(".js-catalog-mobile-toggle");
    if ($toggle) {
        const $panel = $toggle.closest<HTMLElement>(".okl-catalog-filter-panel");
        const $form = $panel?.querySelector<HTMLFormElement>(".js-catalog-filter-controls");
        if ($panel && $form) {
            $panel.dataset.mobileFiltersOpen = String($toggle.getAttribute("aria-expanded") !== "true");
            refresh_mobile_filters($form);
        }
        return;
    }
    if ($target?.closest('a[href="#catalog-filters"]')) {
        const $panel = document.querySelector<HTMLElement>(".okl-catalog-filter-panel");
        const $form = $panel?.querySelector<HTMLFormElement>(".js-catalog-filter-controls");
        if ($panel && $form) {
            $panel.dataset.mobileFiltersOpen = "true";
            refresh_mobile_filters($form);
            $form
                .querySelector<HTMLInputElement>('input[type="search"], input[type="text"]')
                ?.focus({ preventScroll: true });
        }
    }
});

function url_settings() {
    return new URLSearchParams(window.location.search);
}

export function remove_from_array<T>(array: T[], elem: T): T[] {
    return array.filter((val) => {
        return val !== elem;
    });
}

export function new_set<T>(): Set<T> {
    return new Set();
}

export function strip_trailing_slash(str: string): string {
    if (!str) {
        return "";
    }
    return str.replaceAll(/(\/$)|(^\/)/g, "");
}

export function create_url_options(pathname: string, hash: string = ""): [string, string] {
    return [pathname + hash, strip_trailing_slash(pathname) + hash];
}

/**
 * Determines whether a value is "empty".
 *
 * Empty values include:
 * - null or undefined
 * - empty strings: ''
 * - empty arrays: []
 * - empty plain objects: {}
 * - falsy primitives: 0, false, NaN, ''
 *
 * For objects, only plain objects are checked via Object.keys().
 * Other types (e.g., functions, numbers, booleans) are considered empty if falsy.
 *
 * @param value - The value to evaluate for emptiness
 * @returns true if the value is considered empty, false otherwise
 */
export function is_empty(value: any): boolean {
    if (value === null || value === undefined) {
        return true;
    }
    if (typeof value === "string" || Array.isArray(value)) {
        return value.length === 0;
    }
    if (typeof value === "object") {
        return Object.keys(value).length === 0;
    }
    return !value;
}

function append_data_from_form_to_query($params: HTMLFormElement, query: URLSearchParams) {
    const form_data = new FormData($params);
    form_data.forEach((value, key) => {
        if (typeof value === "string" && value) {
            query.append(key, value);
        }
    });
}

function append_data_from_obj_to_query(
    params: Record<string, string | number | boolean | string[] | number[] | boolean[]>,
    query: URLSearchParams,
) {
    Object.entries(params).forEach(([key, value]) => {
        if (key.startsWith("_") || value === "" || value === false) {
            return;
        }
        const values = Array.isArray(value) ? value : [value];
        values.forEach((item) => {
            return query.append(key, String(item));
        });
    });
}

export function update_url_params(
    $params: HTMLFormElement | Record<string, string | number | boolean | string[] | number[] | boolean[]>,
) {
    const query = new URLSearchParams();
    if ($params instanceof HTMLFormElement) {
        append_data_from_form_to_query($params, query);
    } else {
        append_data_from_obj_to_query($params, query);
    }
    const url = new URL(window.location.href);
    const query_string = query.toString();
    url.search = query_string ? `?${query_string}` : "";
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

function url_to_state($form: HTMLFormElement) {
    const settings = url_settings();
    Array.from($form.elements).forEach(($control) => {
        if (!(
            $control instanceof HTMLInputElement ||
            $control instanceof HTMLSelectElement ||
            $control instanceof HTMLTextAreaElement
        )) {
            return;
        }
        if (!$control.name) {
            return;
        }
        if ($control.matches(":disabled")) {
            return;
        }
        const values = settings.getAll($control.name);
        if ($control instanceof HTMLInputElement) {
            const type = $control.type.toLowerCase();
            if (type === "checkbox" || type === "radio") {
                $control.checked = values.includes($control.value) || ($control.value === "1" && values.length > 0);
                return;
            }
            $control.value = values[0] || (type === "hidden" ? $control.defaultValue : "");
            return;
        }
        if ($control instanceof HTMLSelectElement && $control.multiple) {
            Array.from($control.options).forEach(($option) => {
                $option.selected = values.includes($option.value);
            });
            return;
        }
        if ($control instanceof HTMLSelectElement && values.length === 0) {
            return;
        }
        $control.value = values[0] || "";
    });
    $form
        .querySelectorAll<HTMLElement>('[data-widget="multi-select"], [data-widget="single-select"]')
        .forEach(($container) => {
            refresh_multiselect_widget($container);
        });
}

const form_submit_timeout_by_form = new WeakMap<HTMLFormElement, number>();
type SubmitReason =
    | {
          kind: "field_change";
          field: string;
      } // -> set to 1 or keep depending on 'field'
    | {
          kind: "reset";
      } // clean filters -> set page to 1
    | {
          kind: "sync_from_url";
      } // -> keep page as-is in the data
    | null;

function page_input($form: HTMLFormElement) {
    return $form.querySelector<HTMLInputElement>('input[name="page"]');
}

function view_input($form: HTMLFormElement) {
    return $form.querySelector<HTMLInputElement>('input[name="view"]');
}

function edwh_state($base: Element | null = null): HTMLFormElement | null {
    return ($base || document).querySelector<HTMLFormElement>("form.edwh-state");
}

function should_reset_page(reason: SubmitReason) {
    if (!reason) {
        return false;
    }
    if (reason.kind === "reset") {
        return true;
    }
    return reason.kind === "field_change" && reason.field !== "page";
}

function set_page(
    $form: HTMLFormElement,
    page: number,
    {
        submit = false,
        scroll = false,
    }: {
        submit?: boolean;
        scroll?: boolean;
    } = {},
) {
    const $page_input = page_input($form);
    if (!$page_input) {
        return;
    }
    const normalized_page = String(Math.max(1, Math.trunc(page)));
    const page_changed = $page_input.value !== normalized_page;
    $page_input.value = normalized_page;
    if (submit && page_changed) {
        queue_form_submit($form, { kind: "field_change", field: "page" });
    }
    if (scroll) {
        focus_catalog_results();
    }
}

function queue_form_submit($form: HTMLFormElement, reason: SubmitReason = null, delay_ms: number = 0) {
    const existing_timeout = form_submit_timeout_by_form.get($form);
    if (existing_timeout) {
        window.clearTimeout(existing_timeout);
    }
    const timeout = window.setTimeout(() => {
        if (!$form.isConnected) {
            return;
        }
        if (should_reset_page(reason)) {
            set_page($form, 1);
        }
        update_url_params($form);
        refresh_mobile_filters($form);
        htmx.trigger(document.body, "ew:state_changed");
        form_submit_timeout_by_form.delete($form);
    }, delay_ms);
    form_submit_timeout_by_form.set($form, timeout);
}

function enhance_state_form($form: HTMLFormElement) {
    $form.dataset.catalogPath = location.pathname;
    if ($form.getAttribute("data-catalog-filters-enhanced") === "true") {
        return;
    }
    $form.addEventListener("submit", (event) => {
        event.preventDefault();
        queue_form_submit($form, { kind: "field_change", field: "search" });
        const $panel = $form.closest<HTMLElement>(".okl-catalog-filter-panel");
        if ($panel && mobile_filter_media.matches) {
            $panel.dataset.mobileFiltersOpen = "false";
            refresh_mobile_filters($form);
        }
        focus_catalog_results();
    });
    $form.addEventListener("change", (event) => {
        const target = event.target;
        if (!(
            target instanceof HTMLInputElement ||
            target instanceof HTMLSelectElement ||
            target instanceof HTMLTextAreaElement
        )) {
            return;
        }
        if (!target.name) {
            return;
        }
        if (target instanceof HTMLInputElement) {
            const type = target.type.toLowerCase();
            if (type === "search" || type === "text") {
                return;
            }
        }
        queue_form_submit($form, { kind: "field_change", field: target.name });
    });
    $form.addEventListener("input", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
            return;
        }
        if (!target.name) {
            return;
        }
        const type = target.type.toLowerCase();
        if (type !== "search" && type !== "text") {
            return;
        }
        queue_form_submit($form, { kind: "field_change", field: target.name }, 400);
    });
    $form.addEventListener("reset", () => {
        window.setTimeout(() => {
            $form
                .querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
                    ".okl-filter-fields input, .okl-filter-fields select, .okl-filter-fields textarea",
                )
                .forEach(($control) => {
                    if ($control.matches(":disabled")) {
                        return;
                    }
                    if ($control instanceof HTMLInputElement && ["checkbox", "radio"].includes($control.type)) {
                        $control.checked = false;
                    } else if ($control instanceof HTMLSelectElement) {
                        Array.from($control.options).forEach(($option) => {
                            $option.selected = $option.value === "";
                        });
                    } else if (!($control instanceof HTMLInputElement && $control.type === "hidden")) {
                        $control.value = "";
                    }
                });
            $form
                .querySelectorAll<HTMLElement>('[data-widget="multi-select"], [data-widget="single-select"]')
                .forEach(($container) => {
                    if (!$container.dataset.optionSlug) {
                        refresh_multiselect_widget($container);
                    }
                });
            queue_form_submit($form, { kind: "reset" });
        }, 0);
    });
    $form.setAttribute("data-catalog-filters-enhanced", "true");
    url_to_state($form);
    refresh_mobile_filters($form);
    if ($form.dataset.catalogRestored === "true" || $form.dataset.catalogRendered === "true") {
        delete $form.dataset.catalogRestored;
        delete $form.dataset.catalogRendered;
    } else {
        queue_form_submit($form, { kind: "sync_from_url" });
    }
}

function enhance_state_forms($root: HTMLElement) {
    const $scope = $root || document.body;
    const $form = edwh_state($scope);
    if ($form) {
        enhance_state_form($form);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    enhance_state_forms(document.body);
});
document.addEventListener("htmx:afterSwap", (evt) => {
    if (evt.target) {
        enhance_state_forms(evt.target as HTMLElement);
    }
});

function catalog_results_target(event: Event): HTMLElement | null {
    const $target = (
        event as CustomEvent<{
            target?: Element;
        }>
    ).detail?.target;
    if (!($target instanceof HTMLElement)) {
        return null;
    }
    return $target.matches("#product-results, #method-results, #vision-recommendations") ? $target : null;
}

function remove_catalog_results_feedback($target: HTMLElement) {
    $target.querySelectorAll(".catalog-results-feedback").forEach(($feedback) => {
        $feedback.remove();
    });
}

function show_catalog_results_loading($target: HTMLElement) {
    remove_catalog_results_feedback($target);
    $target.setAttribute("aria-busy", "true");
    if ($target.querySelector(".okl-skeleton")) {
        return;
    }
    const $feedback = document.createElement("p");
    $feedback.className = "catalog-results-feedback visually-hidden";
    $feedback.setAttribute("role", "status");
    $feedback.textContent = "Resultaten bijwerken…";
    $target.prepend($feedback);
}

function show_catalog_results_error($target: HTMLElement, message: string) {
    remove_catalog_results_feedback($target);
    $target.setAttribute("aria-busy", "false");
    const $feedback = document.createElement("div");
    $feedback.className =
        "catalog-results-feedback alert alert-danger d-flex justify-content-between align-items-center gap-3 mb-3";
    $feedback.setAttribute("role", "alert");
    const $message = document.createElement("span");
    $message.textContent = message;
    $feedback.append($message);
    const $retry = document.createElement("button");
    $retry.className = "btn btn-sm btn-outline-danger text-nowrap";
    $retry.type = "button";
    $retry.classList.add("js-catalog-results-retry");
    $retry.textContent = "Opnieuw proberen";
    $feedback.append($retry);
    $target.prepend($feedback);
}

document.addEventListener("htmx:beforeRequest", (event) => {
    const $target = catalog_results_target(event);
    if ($target) {
        show_catalog_results_loading($target);
    }
});
document.addEventListener("htmx:afterRequest", (event) => {
    const $target = catalog_results_target(event);
    if ($target) {
        $target.setAttribute("aria-busy", "false");
        $target.querySelector('.catalog-results-feedback[role="status"]')?.remove();
    }
});
document.addEventListener("htmx:responseError", (event) => {
    const $target = catalog_results_target(event);
    if (!$target) {
        return;
    }
    const status = (
        event as CustomEvent<{
            xhr?: XMLHttpRequest;
        }>
    ).detail?.xhr?.status;
    const message =
        status === 400
            ? "De geselecteerde filters zijn niet geldig. Pas ze aan en probeer opnieuw."
            : "De resultaten konden niet worden bijgewerkt. De getoonde resultaten kunnen verouderd zijn.";
    show_catalog_results_error($target, message);
});
document.addEventListener("htmx:sendError", (event) => {
    const $target = catalog_results_target(event);
    if ($target) {
        show_catalog_results_error(
            $target,
            "De resultaten konden niet worden bijgewerkt door een verbindingsprobleem.",
        );
    }
});
document.addEventListener("htmx:timeout", (event) => {
    const $target = catalog_results_target(event);
    if ($target) {
        show_catalog_results_error($target, "Het bijwerken van de resultaten duurt te lang. Probeer opnieuw.");
    }
});
document.addEventListener("click", (event) => {
    const $retry = (event.target as Element | null)?.closest<HTMLElement>(".js-catalog-results-retry");
    if ($retry) {
        htmx.trigger(document.body, "ew:state_changed");
    }
});
document.addEventListener("ew:change_page", (event: Event) => {
    const $form = edwh_state();
    if (!$form) {
        return;
    }
    const page = Number((event as CustomEvent).detail?.page);
    if (!Number.isFinite(page)) {
        return;
    }
    set_page($form, page, { scroll: true, submit: true });
});
document.addEventListener("ew:change_view", (event: Event) => {
    const $form = edwh_state();
    if (!$form) {
        return;
    }
    const $view_input = view_input($form);
    if (!$view_input) {
        return;
    }
    const view = String((event as CustomEvent).detail?.view || "").toLowerCase();
    if ($view_input.value === view) {
        // nothing changed
        return;
    }
    $view_input.value = view;
    set_page($form, 1, { submit: false });
    queue_form_submit($form, { kind: "field_change", field: "view" });
});
window.addEventListener("popstate", () => {
    const $form = edwh_state();
    if ($form && $form.dataset.catalogPath === location.pathname) {
        url_to_state($form);
        queue_form_submit($form, { kind: "sync_from_url" });
    }
});
