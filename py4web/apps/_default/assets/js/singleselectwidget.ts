let single_select_sequence = 0;

interface SingleSelectElements {
    $button: HTMLElement;
    $menu: HTMLElement;
    $selected_text: HTMLElement;
    $hidden_input: HTMLInputElement;
    items: HTMLElement[];
}

function get_single_select_elements($container: HTMLElement): SingleSelectElements | null {
    const $button = $container.querySelector<HTMLElement>(".dropdown-toggle");
    const $menu = $container.querySelector<HTMLElement>(".capsule-dropdown-menu");
    const $selected_text = $container.querySelector<HTMLElement>(".selected-text");
    const $hidden_input = $container.querySelector<HTMLInputElement>('input[type="hidden"][name]');
    const $items = Array.from($container.querySelectorAll<HTMLElement>(".dropdown-item"));
    if (!$button || !$menu || !$selected_text || !$hidden_input || !$items.length) {
        return null;
    }
    return { $button, $menu, $selected_text, $hidden_input, items: $items };
}

function init_single_select($container: HTMLElement) {
    if (
        $container.getAttribute("data-enhanced-single-select") === "true" ||
        $container.querySelector('input[type="checkbox"], input[type="radio"]')
    ) {
        return;
    }
    const $elements = get_single_select_elements($container);
    if (!$elements) {
        return;
    }
    const { $button, $menu, $selected_text, $hidden_input, items } = $elements;
    const placeholder = $container.dataset.placeholder || "Maak een keuze...";
    $container.setAttribute("data-enhanced-single-select", "true");
    $button.removeAttribute("data-bs-toggle");
    $button.removeAttribute("data-bs-auto-close");
    $menu.classList.remove("dropdown-menu");
    $menu.id ||= `okl-single-select-${++single_select_sequence}`;
    $menu.setAttribute("aria-label", $button.getAttribute("aria-label") || placeholder);
    $button.setAttribute("aria-haspopup", "listbox");
    $button.setAttribute("aria-controls", $menu.id);
    $selected_text.id ||= `${$menu.id}-value`;
    $button.setAttribute(
        "aria-describedby",
        [$button.getAttribute("aria-describedby"), $selected_text.id].filter(Boolean).join(" "),
    );

    function close_menu(restore_focus = false) {
        if (restore_focus) {
            $button.focus();
        }
        $menu.classList.remove("show");
        $button.setAttribute("aria-expanded", "false");
        document.removeEventListener("click", handle_document_click, true);
    }

    function open_menu() {
        $menu.classList.add("show");
        $button.setAttribute("aria-expanded", "true");
        document.addEventListener("click", handle_document_click, { capture: true, signal: window.okl_page.signal });
        focus_item(
            available_items().find(($item) => {
                return $item.dataset.value === $hidden_input.value;
            }) || available_items()[0],
        );
    }

    function available_items() {
        return items.filter(($item) => {
            return (
                !$item.hidden && !$item.classList.contains("d-none") && $item.getAttribute("aria-disabled") !== "true"
            );
        });
    }

    function focus_item($item: HTMLElement | undefined) {
        $item?.focus();
    }

    function update_display($selected_item: HTMLElement | null) {
        const value = $selected_item?.dataset.value || "";
        const label =
            $selected_item?.querySelector<HTMLElement>(".item-label")?.textContent?.trim() ||
            $selected_item?.textContent?.trim() ||
            placeholder;
        items.forEach(($item) => {
            const selected = $item === $selected_item && Boolean(value);
            $item.classList.toggle("selected", selected);
            $item.setAttribute("aria-selected", selected ? "true" : "false");
        });
        $hidden_input.value = value;
        $selected_text.textContent = value ? label : placeholder;
    }

    function handle_document_click(evt: MouseEvent) {
        if (!(evt.target instanceof Node) || !$container.contains(evt.target)) {
            close_menu();
        }
    }

    $button.addEventListener("click", (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        if ($menu.classList.contains("show")) {
            close_menu();
        } else {
            open_menu();
        }
    });
    $button.addEventListener("keydown", (evt) => {
        if (evt.key === " " || evt.key === "Enter") {
            evt.preventDefault();
            $button.click();
            return;
        }
        if (evt.key === "ArrowDown" || evt.key === "ArrowUp") {
            evt.preventDefault();
            open_menu();
        }
    });
    items.forEach(($item) => {
        $item.tabIndex = -1;

        function select_item(evt: Event) {
            evt.preventDefault();
            if (!available_items().includes($item)) {
                return;
            }
            update_display($item);
            close_menu(true);
            $hidden_input.dispatchEvent(new Event("change", { bubbles: true }));
        }

        $item.addEventListener("click", select_item);
        $item.addEventListener("keydown", (evt) => {
            if (evt.key === " " || evt.key === "Enter") {
                select_item(evt);
            }
        });
    });
    let typed = "";
    let typed_at = 0;
    $menu.addEventListener("keydown", (evt) => {
        const $options = available_items();
        const index = $options.indexOf(document.activeElement as HTMLElement);
        if (evt.key === "Tab") {
            close_menu(true);
        } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(evt.key)) {
            evt.preventDefault();
            let next: number;
            if (evt.key === "Home") {
                next = 0;
            } else if (evt.key === "End") {
                next = $options.length - 1;
            } else {
                const direction = evt.key === "ArrowDown" ? 1 : -1;
                next = Math.max(0, Math.min($options.length - 1, index + direction));
            }
            focus_item($options[next]);
        } else if (evt.key.length === 1 && evt.key !== " ") {
            typed = Date.now() - typed_at > 700 ? evt.key : typed + evt.key;
            typed_at = Date.now();
            focus_item(
                $options.find(($item) => {
                    return $item.textContent?.trim().toLocaleLowerCase().startsWith(typed.toLocaleLowerCase());
                }),
            );
        }
    });
    $container.addEventListener("keydown", (evt) => {
        if (evt.key === "Escape" && $menu.classList.contains("show")) {
            evt.preventDefault();
            evt.stopPropagation();
            close_menu(true);
        }
    });
    $container.addEventListener("focusout", (evt) => {
        if (!(evt.relatedTarget instanceof Node) || !$container.contains(evt.relatedTarget)) {
            close_menu();
        }
    });
    const $initial_item =
        items.find(($item) => {
            return $item.dataset.value === $hidden_input.value;
        }) || null;
    update_display($initial_item);
}

function enhance_all_single_selects($root: HTMLElement) {
    const $scope = $root || document.body;
    $scope.querySelectorAll<HTMLElement>('.capsule-dropdown[data-widget="single-select"]').forEach(init_single_select);
}

document.addEventListener("DOMContentLoaded", () => {
    enhance_all_single_selects(document.body);
});
document.addEventListener("htmx:afterSwap", (evt) => {
    if (evt.target instanceof HTMLElement) {
        enhance_all_single_selects(evt.target);
    }
});
