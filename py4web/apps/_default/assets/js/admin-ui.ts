export {};

function initialize_admin(): void {
    const $content = document.querySelector<HTMLElement>(".okl-admin-content");
    if (!$content || $content.dataset.enhancedAdmin) {
        return;
    }
    const $admin_content = $content;
    $content.dataset.enhancedAdmin = "true";
    const { signal } = window.okl_page;
    const $wrappers = new WeakSet<HTMLElement>();

    function update_overflow($wrapper: HTMLElement): void {
        const $hint = $wrapper.previousElementSibling as HTMLElement | null;
        const overflowing = $wrapper.scrollWidth > $wrapper.clientWidth + 1;
        if ($hint?.classList.contains("admin-table-hint")) {
            $hint.hidden = !overflowing;
        }
        $wrapper.tabIndex = overflowing ? 0 : -1;
    }

    const observer = new ResizeObserver((entries) => {
        entries.forEach((entry) => {
            update_overflow(entry.target as HTMLElement);
        });
    });

    function enhance(): void {
        $admin_content.querySelectorAll<HTMLElement>(".grid-table-wrapper, .table-responsive").forEach(($wrapper) => {
            if ($wrappers.has($wrapper)) {
                update_overflow($wrapper);
                return;
            }
            $wrappers.add($wrapper);
            $wrapper.setAttribute("role", "region");
            $wrapper.setAttribute("aria-label", "Gegevenstabel; scroll horizontaal voor alle kolommen");
            if (!$wrapper.previousElementSibling?.classList.contains("admin-table-hint")) {
                const $hint = document.createElement("p");
                $hint.className = "admin-table-hint";
                $hint.textContent = "Scroll opzij voor alle kolommen.";
                $hint.hidden = true;
                $wrapper.before($hint);
            }
            observer.observe($wrapper);
        });
        $admin_content.querySelectorAll<HTMLTableCellElement>("thead th").forEach(($cell) => {
            if (!$cell.hasAttribute("scope")) {
                $cell.scope = "col";
            }
        });
        $admin_content.querySelectorAll<HTMLElement>(".fa-clipboard[title]:not([role])").forEach(($control) => {
            $control.classList.add("admin-copy-control");
            $control.setAttribute("role", "button");
            $control.setAttribute("aria-label", `Kopieer identifier ${$control.title}`);
            $control.tabIndex = 0;
            $control.addEventListener(
                "keydown",
                (event) => {
                    if (event.key !== "Enter" && event.key !== " ") {
                        return;
                    }
                    event.preventDefault();
                    $control.click();
                },
                { signal },
            );
        });
    }

    document.addEventListener("htmx:afterSettle", enhance, { signal });
    signal.addEventListener(
        "abort",
        () => {
            observer.disconnect();
        },
        { once: true },
    );
    enhance();
}

window.on_okl_ready(initialize_admin);
document.addEventListener("htmx:afterSettle", () => {
    window.on_okl_ready(initialize_admin);
});
