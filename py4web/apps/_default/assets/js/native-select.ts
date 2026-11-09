export {};

interface SelectShell {
    $container: HTMLDivElement;
    $button: HTMLButtonElement;
    $selected: HTMLSpanElement;
    $menu: HTMLDivElement;
    $feedback: HTMLDivElement;
}

const $enhanced_selects = new WeakSet<HTMLSelectElement>();
let select_sequence = 0;

function create_select_shell($select: HTMLSelectElement, name: string): SelectShell {
    const $container = document.createElement("div");
    $container.className = "capsule-dropdown okl-select";
    const $button = document.createElement("button");
    $button.type = "button";
    $button.className = "btn dropdown-toggle";
    $button.setAttribute("aria-haspopup", "listbox");
    $button.setAttribute("aria-expanded", "false");
    const $selected = document.createElement("span");
    $selected.className = "selected-text";
    const $caret = document.createElement("i");
    $caret.className = "okl-icon okl-icon--caret-down";
    $caret.setAttribute("aria-hidden", "true");
    $button.append($selected, $caret);
    const $menu = document.createElement("div");
    $menu.className = "capsule-dropdown-menu";
    $menu.id = `okl-select-${++select_sequence}`;
    $menu.setAttribute("role", "listbox");
    $menu.setAttribute("aria-label", name);
    if ($select.multiple) {
        $menu.setAttribute("aria-multiselectable", "true");
    }
    if ($select.required) {
        $menu.setAttribute("aria-required", "true");
    }
    $button.setAttribute("aria-controls", $menu.id);
    const $feedback = document.createElement("div");
    $feedback.id = `${$menu.id}-feedback`;
    $feedback.className = "invalid-feedback";
    $feedback.setAttribute("role", "alert");
    const description = $select.getAttribute("aria-describedby");
    $button.setAttribute("aria-describedby", [description, $feedback.id].filter(Boolean).join(" "));
    $select.before($container);
    $container.append($select, $button, $menu, $feedback);
    $select.classList.add("okl-select__native");
    $select.tabIndex = -1;
    $select.setAttribute("aria-hidden", "true");
    return { $container, $button, $selected, $menu, $feedback };
}

function selectable_options($menu: HTMLElement): HTMLElement[] {
    return Array.from($menu.querySelectorAll<HTMLElement>('[role="option"]:not([aria-disabled="true"]):not([hidden])'));
}

function enhance_select($select: HTMLSelectElement): void {
    if ($enhanced_selects.has($select) || $select.closest(".capsule-dropdown, [data-native-select]")) {
        return;
    }
    $enhanced_selects.add($select);
    const { signal } = window.okl_page;
    const $label = $select.labels?.[0];
    const name = $select.getAttribute("aria-label") || $label?.textContent?.trim() || $select.name;
    const { $container, $button, $selected, $menu, $feedback } = create_select_shell($select, name);

    function close(restore_focus = false): void {
        if (restore_focus) {
            $button.focus();
        }
        $menu.classList.remove("show");
        $button.setAttribute("aria-expanded", "false");
    }

    function open(): void {
        $menu.classList.add("show");
        $button.setAttribute("aria-expanded", "true");
        const $active = selectable_options($menu).find(($item) => {
            return $item.getAttribute("aria-selected") === "true";
        });
        ($active || selectable_options($menu)[0])?.focus();
    }

    function choose_option($option: HTMLOptionElement, disabled: boolean, option_label: string): void {
        if (disabled) {
            return;
        }
        if ($select.multiple) {
            $option.selected = !$option.selected;
        } else {
            $select.value = $option.value;
        }
        $select.dispatchEvent(new Event("input", { bubbles: true }));
        $select.dispatchEvent(new Event("change", { bubbles: true }));
        if (!$select.multiple) {
            close(true);
        } else {
            selectable_options($menu)
                .find(($item) => {
                    return $item.textContent === option_label;
                })
                ?.focus();
        }
    }

    function render(): void {
        $feedback.textContent = "";
        $feedback.style.display = "none";
        $selected.textContent =
            Array.from($select.selectedOptions)
                .map(($option) => {
                    return $option.label;
                })
                .join(", ") || "Maak een keuze…";
        $button.setAttribute("aria-label", `${name}: ${$selected.textContent}`);
        $button.disabled = $select.disabled;
        $button.setAttribute(
            "aria-invalid",
            String($select.classList.contains("is-invalid") || $select.getAttribute("aria-invalid") === "true"),
        );
        $menu.replaceChildren();
        Array.from($select.options).forEach(($option) => {
            const option_label = $option.label || "Maak een keuze…";
            const disabled =
                $option.disabled ||
                ($option.parentElement instanceof HTMLOptGroupElement && $option.parentElement.disabled);
            const $item = document.createElement("div");
            $item.className = "dropdown-item";
            $item.classList.toggle("selected", $option.selected);
            $item.setAttribute("role", "option");
            $item.setAttribute("aria-selected", String($option.selected));
            $item.setAttribute("aria-disabled", String(disabled));
            $item.tabIndex = -1;
            $item.textContent = option_label;
            $item.hidden = $option.hidden;
            $item.addEventListener("click", () => {
                return choose_option($option, disabled, option_label);
            });
            $item.addEventListener("keydown", (event) => {
                if (["Enter", " "].includes(event.key)) {
                    event.preventDefault();
                    choose_option($option, disabled, option_label);
                }
            });
            $menu.append($item);
        });
    }

    $button.addEventListener("click", () => {
        return $menu.classList.contains("show") ? close() : open();
    });
    $button.addEventListener("keydown", (event) => {
        if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            open();
        }
    });
    let typed = "";
    let typed_at = 0;
    $menu.addEventListener("keydown", (event) => {
        const $items = selectable_options($menu);
        const index = $items.indexOf(document.activeElement as HTMLElement);
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            close(true);
        } else if (event.key === "Tab") {
            close(true);
        } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            let next: number;
            if (event.key === "Home") {
                next = 0;
            } else if (event.key === "End") {
                next = $items.length - 1;
            } else {
                const direction = event.key === "ArrowDown" ? 1 : -1;
                next = (index + direction + $items.length) % $items.length;
            }
            $items[next]?.focus();
        } else if (event.key.length === 1 && event.key !== " ") {
            typed = Date.now() - typed_at > 700 ? event.key : typed + event.key;
            typed_at = Date.now();
            $items
                .find(($item) => {
                    return $item.textContent?.toLocaleLowerCase().startsWith(typed.toLocaleLowerCase());
                })
                ?.focus();
        }
    });
    document.addEventListener(
        "click",
        (event) => {
            if (event.target instanceof Node && !$container.contains(event.target)) {
                close();
            }
        },
        { signal },
    );
    $container.addEventListener("focusout", (event) => {
        if (!(event.relatedTarget instanceof Node) || !$container.contains(event.relatedTarget)) {
            close();
        }
    });
    $label?.addEventListener(
        "click",
        (event) => {
            event.preventDefault();
            event.stopPropagation();
            $button.click();
        },
        { signal },
    );
    $select.addEventListener("change", render);
    $select.addEventListener("invalid", (event) => {
        event.preventDefault();
        $button.setAttribute("aria-invalid", "true");
        $feedback.textContent = $select.validationMessage;
        $feedback.style.display = "block";
        $button.focus();
    });
    $select.form?.addEventListener(
        "reset",
        () => {
            return queueMicrotask(render);
        },
        { signal },
    );
    const observer = new MutationObserver(render);
    observer.observe($select, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["disabled", "selected", "label", "aria-invalid"],
    });
    signal.addEventListener(
        "abort",
        () => {
            return observer.disconnect();
        },
        { once: true },
    );
    render();
}

function enhance_selects(): void {
    document.querySelectorAll<HTMLSelectElement>("select").forEach(enhance_select);
}

window.on_okl_ready(enhance_selects);
document.addEventListener("htmx:afterSettle", enhance_selects);
