// Enhances catalogue capsule select controls and keeps their rendered pills in sync with input state.
declare const htmx: { process(element: Element): void; trigger(element: Element, event_name: string): void };
let multi_select_sequence = 0;

function init_windowed_widget($container: HTMLElement) {
    const $button = $container.querySelector<HTMLElement>(".dropdown-toggle")!;
    const $menu = $container.querySelector<HTMLElement>(".capsule-dropdown-menu")!;
    const $results = $container.querySelector<HTMLElement>(".search-results")!;
    const $search = $container.querySelector<HTMLInputElement>(".capsule-search-input")!;
    const $text = $container.querySelector<HTMLElement>(".selected-text")!;
    const $count = $container.querySelector<HTMLElement>(".selected-count");
    const $form = $container.closest<HTMLFormElement>("form")!;
    const slug = $container.dataset.optionSlug!;
    const kind = $container.dataset.optionKind!;
    const limit = $container.dataset.optionLimit || "100";
    const multiple = $container.dataset.widget === "multi-select";
    const selected = new Map<string, string>();
    const $selected_inputs = document.createElement("div");
    $selected_inputs.hidden = true;
    $container.append($selected_inputs);

    $results.querySelectorAll<HTMLInputElement>("input").forEach(($input) => {
        if ($input.checked) {
            selected.set(
                $input.value,
                $input.closest("label")?.querySelector(".item-label")?.textContent || $input.value,
            );
        }
    });

    function sync_visible() {
        $results.querySelectorAll<HTMLInputElement>("input").forEach(($input) => {
            $input.removeAttribute("name");
            $input.checked = selected.has($input.value);
            $input.closest("label")?.classList.toggle("selected", $input.checked);
        });
    }

    function render_selected() {
        $selected_inputs.replaceChildren();
        $text.replaceChildren();
        $text.classList.toggle("is-placeholder", selected.size === 0);
        if (!selected.size) {
            $text.textContent = $container.dataset.placeholder || "Alles";
        }
        selected.forEach((label, value) => {
            const $input = document.createElement("input");
            $input.type = "hidden";
            $input.name = slug;
            $input.value = value;
            $input.dataset.windowedSelection = "true";
            $selected_inputs.append($input);
            $text.append(pill(label, value, !$container.closest("fieldset:disabled")));
        });
        if ($count) {
            $count.textContent = `${selected.size} geselecteerd`;
        }
        sync_visible();
    }

    function notify_change() {
        const $input = document.createElement("input");
        $input.type = "hidden";
        $input.name = slug;
        $selected_inputs.append($input);
        $input.dispatchEvent(new Event("change", { bubbles: true }));
        $input.remove();
    }

    function close_menu() {
        $menu.classList.remove("show");
        $button.setAttribute("aria-expanded", "false");
    }

    function open_menu() {
        $menu.classList.add("show");
        $button.setAttribute("aria-expanded", "true");
        $search.focus();
    }

    $button.removeAttribute("data-bs-toggle");
    $button.removeAttribute("data-bs-auto-close");
    $menu.classList.remove("dropdown-menu");
    $menu.id ||= `okl-multi-select-${++multi_select_sequence}`;
    $menu.setAttribute("role", "group");
    $menu.removeAttribute("aria-multiselectable");
    $button.setAttribute("aria-controls", $menu.id);
    $count?.setAttribute("aria-live", "polite");
    $button.addEventListener("click", () => {
        if ($menu.classList.contains("show")) {
            close_menu();
        } else {
            open_menu();
        }
    });
    $button.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            open_menu();
        } else if (["Backspace", "Delete"].includes(event.key) && selected.size) {
            event.preventDefault();
            const last_value = Array.from(selected.keys()).pop();
            if (last_value) {
                selected.delete(last_value);
            }
            render_selected();
            notify_change();
        }
    });
    $container.querySelector<HTMLElement>(".close-dropdown-btn")?.addEventListener("click", () => {
        close_menu();
        $button.focus();
    });
    document.addEventListener(
        "click",
        (event) => {
            if (event.target instanceof Node && !$container.contains(event.target)) {
                close_menu();
            }
        },
        { signal: window.okl_page.signal },
    );
    $container.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            close_menu();
            $button.focus();
        }
    });
    $search.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown" || event.key === "Enter") {
            event.preventDefault();
            $results.querySelector<HTMLInputElement>("input")?.focus();
        }
    });
    $results.addEventListener("change", (event) => {
        const $input = event.target;
        if (!($input instanceof HTMLInputElement)) {
            return;
        }
        if (!multiple) {
            selected.clear();
        }
        if ($input.checked) {
            selected.set(
                $input.value,
                $input.closest("label")?.querySelector(".item-label")?.textContent || $input.value,
            );
        } else {
            selected.delete($input.value);
        }
        render_selected();
        notify_change();
        if (!multiple) {
            close_menu();
        }
    });
    $results.addEventListener("keydown", (event) => {
        const $input = event.target;
        if (!($input instanceof HTMLInputElement)) {
            return;
        }
        if (event.key === "Enter") {
            event.preventDefault();
            $input.click();
            return;
        }
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            return;
        }
        const inputs = Array.from($results.querySelectorAll<HTMLInputElement>("input"));
        const index = inputs.indexOf($input);
        let next: HTMLInputElement | undefined;
        if (event.key === "Home") {
            next = inputs[0];
        } else if (event.key === "End") {
            next = inputs[inputs.length - 1];
        } else if (event.key === "ArrowDown") {
            next = inputs[index + 1];
        } else {
            next = inputs[index - 1];
        }
        event.preventDefault();
        if (next) {
            next.focus();
        } else if (event.key === "ArrowUp") {
            $search.focus();
        }
    });
    $text.addEventListener("click", (event) => {
        const $remove =
            event.target instanceof Element ? event.target.closest<HTMLElement>(".selected-pill-remove") : null;
        if (!$remove) {
            return;
        }
        event.stopPropagation();
        selected.delete($remove.dataset.value || "");
        render_selected();
        notify_change();
    });
    const url = `${$form.dataset.optionUrl}/${encodeURIComponent(kind)}/${encodeURIComponent(slug)}`;
    $search.setAttribute("hx-get", `${url}?limit=${encodeURIComponent(limit)}`);
    $search.setAttribute("hx-trigger", "catalog:load-options, input changed delay:250ms");
    $search.setAttribute("hx-sync", "this:replace");
    $search.setAttribute("hx-target", `#${($results.id ||= `catalog-options-${++multi_select_sequence}`)}`);
    $search.setAttribute("hx-swap", "innerHTML");
    $search.setAttribute("hx-vals", "js:{q: this.value}");
    $search.setAttribute("hx-include", "closest .capsule-dropdown");
    htmx.process($search);
    const observer = new MutationObserver(() => {
        $results.querySelectorAll<HTMLInputElement>("input").forEach(($input) => {
            if (selected.has($input.value)) {
                selected.set(
                    $input.value,
                    $input.closest("label")?.querySelector(".item-label")?.textContent || $input.value,
                );
            }
        });
        render_selected();
    });
    observer.observe($results, { childList: true, subtree: true });
    window.okl_page.signal.addEventListener("abort", () => observer.disconnect(), { once: true });
    $form.addEventListener("reset", () => {
        if ($container.closest("fieldset:disabled")) {
            return;
        }
        window.setTimeout(() => {
            selected.clear();
            render_selected();
        }, 0);
    });
    $container.addEventListener("catalog:sync-url", () => {
        if ($container.closest("fieldset:disabled")) {
            return;
        }
        const values = new URLSearchParams(location.search).getAll(slug);
        const labels = new Map<string, string>();
        $results.querySelectorAll<HTMLInputElement>("input").forEach(($input) => {
            labels.set(
                $input.value,
                $input.closest("label")?.querySelector(".item-label")?.textContent || $input.value,
            );
        });
        selected.clear();
        values.forEach((value) => selected.set(value, labels.get(value) || value));
        render_selected();
        if (values.some((value) => !labels.has(value))) {
            htmx.trigger($search, "catalog:load-options");
        }
    });
    $container.setAttribute("data-enhanced-capsule-select", "true");
    render_selected();
}

function pill(label: string, value: string, removable: boolean) {
    const $pill = document.createElement("span");
    $pill.className = "selected-pill";
    const $label = document.createElement("span");
    $label.className = "selected-pill-label";
    $label.textContent = label;
    if (!removable) {
        $pill.append($label);
        return $pill;
    }
    const $remove = document.createElement("span");
    $remove.className = "selected-pill-remove";
    $remove.dataset.value = value;
    $remove.textContent = "×";
    $remove.setAttribute("aria-hidden", "true");
    $pill.append($label, $remove);
    return $pill;
}

function init_multiselect_widget($container: HTMLElement) {
    if (!$container || $container.getAttribute("data-enhanced-capsule-select") === "true") {
        return;
    }
    if ($container.dataset.optionSlug) {
        init_windowed_widget($container);
        return;
    }
    const $button = $container.querySelector<HTMLElement>(".dropdown-toggle");
    const $menu = $container.querySelector<HTMLElement>(".capsule-dropdown-menu");
    const $selected_text = $container.querySelector<HTMLElement>(".selected-text");
    const $selected_count = $container.querySelector<HTMLElement>(".selected-count");
    const $close_btn = $container.querySelector<HTMLElement>(".close-dropdown-btn");
    const $search_input = $container.querySelector<HTMLInputElement>(".capsule-search-input");
    const $dropdown_items = Array.from($container.querySelectorAll<HTMLElement>(".dropdown-item"));
    const placeholder = $container.dataset.placeholder || "Alles";
    const is_multiple = $container.dataset.widget === "multi-select";
    const has_selectable_items = $dropdown_items.some(($item) => {
        return $item.querySelector('input[type="checkbox"], input[type="radio"]');
    });
    if (!$button || !$menu || !$selected_text || !has_selectable_items) {
        return;
    }
    if ($close_btn) {
        $close_btn.textContent = "Klaar";
    }
    $button.removeAttribute("data-bs-toggle");
    $button.removeAttribute("data-bs-auto-close");
    $menu.classList.remove("dropdown-menu");
    $menu.id ||= `okl-multi-select-${++multi_select_sequence}`;
    // These are real form controls, not non-interactive listbox options.
    $menu.setAttribute("role", "group");
    $menu.removeAttribute("aria-multiselectable");
    $menu.setAttribute("aria-label", $button.getAttribute("aria-label") || placeholder);
    $button.setAttribute("aria-controls", $menu.id);
    $selected_count?.setAttribute("aria-live", "polite");

    function selected_items() {
        return $dropdown_items.filter(($item: HTMLElement) => {
            const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]');
            return Boolean($input && $input.checked);
        });
    }

    function sync_item_state($item: HTMLElement) {
        const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]');
        const selected = Boolean($input && $input.checked);
        $item.classList.toggle("selected", selected);
        $item.removeAttribute("aria-selected");
    }

    function update_display() {
        const $items = selected_items();
        const labels = $items.map(($item) => {
            return $item.querySelector<HTMLElement>(".item-label")?.textContent?.trim() || "";
        });
        const values = $items.map(($item) => {
            return $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')?.value || "";
        });
        if ($selected_count) {
            $selected_count.textContent = `${values.length} geselecteerd`;
        }
        if (!values.length) {
            $selected_text!.classList.add("is-placeholder");
            $selected_text!.textContent = placeholder;
            return;
        }
        $selected_text!.classList.remove("is-placeholder");
        $selected_text!.textContent = "";
        const $fragment = document.createDocumentFragment();
        labels.forEach((label, index) => {
            $fragment.appendChild(pill(label, values[index], !$container.closest("fieldset:disabled")));
        });
        $selected_text!.appendChild($fragment);
    }

    function filter_items(term: string) {
        const needle = term.trim().toLowerCase();
        $dropdown_items.forEach(($item) => {
            const haystack = ($item.dataset.search || "").toLowerCase();
            $item.classList.toggle("d-none", Boolean(needle) && !haystack.includes(needle));
        });
    }

    function visible_items() {
        return $dropdown_items.filter(($item) => {
            return (
                !$item.hidden &&
                !$item.classList.contains("d-none") &&
                !$item.querySelector<HTMLInputElement>("input")?.disabled
            );
        });
    }

    function focus_item($item: HTMLElement | undefined) {
        $item?.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')?.focus();
    }

    function close_menu() {
        $menu!.classList.remove("show");
        $button!.setAttribute("aria-expanded", "false");
        document.removeEventListener("click", handle_document_click, true);
    }

    function open_menu(focus_options = false) {
        $menu!.classList.add("show");
        $button!.setAttribute("aria-expanded", "true");
        document.addEventListener("click", handle_document_click, { capture: true, signal: window.okl_page.signal });
        if ($search_input) {
            $search_input.value = "";
            filter_items("");
        }
        if (focus_options || !$search_input) {
            focus_item(visible_items()[0]);
        } else {
            $search_input.focus();
        }
    }

    function handle_document_click(evt: MouseEvent) {
        if (!(evt.target instanceof Node) || !$container.contains(evt.target)) {
            close_menu();
        }
    }

    $button!.addEventListener("click", (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        if ($menu!.classList.contains("show")) {
            close_menu();
        } else {
            open_menu();
        }
    });
    $button.addEventListener("keydown", (evt) => {
        if (["Backspace", "Delete"].includes(evt.key) && !$menu.classList.contains("show")) {
            const $last = selected_items().slice(-1)[0]?.querySelector<HTMLInputElement>("input");
            if ($last) {
                evt.preventDefault();
                $last.checked = false;
                $last.dispatchEvent(new Event("change", { bubbles: true }));
            }
            return;
        }
        if (evt.key !== "ArrowDown") {
            return;
        }
        evt.preventDefault();
        open_menu(true);
    });
    $dropdown_items.forEach(($item) => {
        const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]');
        if (!$input) {
            return;
        }
        $item.removeAttribute("role");
        $item.removeAttribute("tabindex");
        $input.tabIndex = 0;
        sync_item_state($item);
        $input.addEventListener("change", () => {
            if (!is_multiple) {
                $dropdown_items.forEach(sync_item_state);
            }
            sync_item_state($item);
            update_display();
            if (!is_multiple) {
                close_menu();
                $button.focus();
            }
        });
        $input.addEventListener("keydown", (evt) => {
            if (evt.key === "Enter") {
                evt.preventDefault();
                $input.click();
                return;
            }
            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(evt.key)) {
                return;
            }
            const $items = visible_items();
            const item_index = $items.indexOf($item);
            let $next_item: HTMLElement | undefined;
            if (evt.key === "Home") {
                $next_item = $items[0];
            } else if (evt.key === "End") {
                $next_item = $items[$items.length - 1];
            } else if (evt.key === "ArrowDown") {
                $next_item = $items[item_index + 1];
            } else {
                $next_item = $items[item_index - 1];
            }
            evt.preventDefault();
            if ($next_item) {
                focus_item($next_item);
            } else if (evt.key === "ArrowUp") {
                ($search_input || $button).focus();
            }
        });
    });
    $selected_text!.addEventListener("click", (evt) => {
        if (!(evt.target instanceof Element)) {
            return;
        }
        const $remove = evt.target.closest<HTMLElement>(".selected-pill-remove");
        if (!$remove) {
            return;
        }
        evt.preventDefault();
        evt.stopPropagation();
        const value = String($remove.dataset.value || "");
        const $input = $container.querySelector<HTMLInputElement>(
            `input[type="checkbox"][value="${CSS.escape(value)}"], input[type="radio"][value="${CSS.escape(value)}"]`,
        );
        if ($input) {
            $input.checked = false;
            $input.dispatchEvent(new Event("change", { bubbles: true }));
        }
    });
    if ($close_btn) {
        $close_btn.addEventListener("click", (evt) => {
            evt.preventDefault();
            close_menu();
            $button.focus();
        });
    }
    $container.addEventListener("keydown", (evt) => {
        if (evt.key === "Escape" && $menu.classList.contains("show")) {
            evt.preventDefault();
            evt.stopPropagation();
            close_menu();
            $button.focus();
        }
    });
    $container.addEventListener("focusout", (evt) => {
        // Clicking label text can briefly move focus to the body before the input.
        // Outside pointer clicks are handled separately by handle_document_click.
        if (
            evt.relatedTarget instanceof Node &&
            (evt.relatedTarget === $button || !$container.contains(evt.relatedTarget))
        ) {
            close_menu();
        }
    });
    if ($search_input) {
        $search_input.addEventListener("input", (evt: Event) => {
            if (!(evt.target instanceof HTMLInputElement)) {
                return;
            }
            filter_items(evt.target.value || "");
        });
        $search_input.addEventListener("keydown", (evt) => {
            if (evt.key === "ArrowDown" || evt.key === "Enter") {
                evt.preventDefault();
                const [$first_item] = visible_items();
                if ($first_item) {
                    focus_item($first_item);
                }
            }
        });
    }
    const $form = $container.closest("form");
    if ($form) {
        $form.addEventListener("reset", () => {
            window.setTimeout(() => {
                $dropdown_items.forEach(sync_item_state);
                filter_items("");
                update_display();
            }, 0);
        });
    }
    $container.setAttribute("data-enhanced-capsule-select", "true");
    update_display();
}

function enhance_all_multiselect($root: HTMLElement) {
    const $scope = $root || document.body;
    $scope
        .querySelectorAll<HTMLElement>('[data-widget="multi-select"], [data-widget="single-select"]')
        .forEach(($elt) => {
            return init_multiselect_widget($elt);
        });
}

export function refresh_multiselect_widget($container: HTMLElement) {
    if ($container.dataset.optionSlug) {
        htmx.trigger($container, "catalog:sync-url");
        return;
    }
    const $selected_text = $container.querySelector<HTMLElement>(".selected-text");
    const $selected_count = $container.querySelector<HTMLElement>(".selected-count");
    const $dropdown_items = Array.from($container.querySelectorAll<HTMLElement>(".dropdown-item"));
    const placeholder = $container.dataset.placeholder || "Alles";
    if (!$selected_text) {
        return;
    }
    const $selected_items = $dropdown_items.filter(($item) => {
        const $input = $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]');
        const selected = Boolean($input && $input.checked);
        $item.classList.toggle("selected", selected);
        $item.removeAttribute("aria-selected");
        return selected;
    });
    const labels = $selected_items.map(($item) => {
        return $item.querySelector<HTMLElement>(".item-label")?.textContent?.trim() || "";
    });
    const values = $selected_items.map(($item) => {
        return $item.querySelector<HTMLInputElement>('input[type="checkbox"], input[type="radio"]')?.value || "";
    });
    if ($selected_count) {
        $selected_count.textContent = `${values.length} geselecteerd`;
    }
    if (!values.length) {
        $selected_text.classList.add("is-placeholder");
        $selected_text.textContent = placeholder;
        return;
    }
    $selected_text.classList.remove("is-placeholder");
    $selected_text.textContent = "";
    const $fragment = document.createDocumentFragment();
    labels.forEach((label, index) => {
        $fragment.appendChild(pill(label, values[index], !$container.closest("fieldset:disabled")));
    });
    $selected_text.appendChild($fragment);
}

document.addEventListener("DOMContentLoaded", () => {
    enhance_all_multiselect(document.body);
});
document.addEventListener("htmx:afterSwap", (evt) => {
    if (evt.target instanceof HTMLElement) {
        enhance_all_multiselect(evt.target);
    }
});
