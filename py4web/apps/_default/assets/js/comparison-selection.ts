type ComparisonKind = "method" | "product";

type ComparisonItem = {
    gid: string;
    name: string;
};

const $initialized_comparison_scrolls = new WeakSet<HTMLElement>();

function initialize_comparison_scroll_hints() {
    document.querySelectorAll<HTMLElement>(".comparison-scroll").forEach(($scroll) => {
        const $hint = $scroll.closest(".comparison-matrix")?.querySelector<HTMLElement>(".js-comparison-scroll-hint");
        if (!$hint || $initialized_comparison_scrolls.has($scroll)) {
            return;
        }
        const $scroll_hint = $hint;

        function update_hint(): void {
            $scroll_hint.hidden = $scroll.scrollWidth <= $scroll.clientWidth + 1;
        }

        const observer = new ResizeObserver(update_hint);
        observer.observe($scroll);
        const $grid = $scroll.querySelector<HTMLElement>(".comparison-grid");
        if ($grid) {
            observer.observe($grid);
        }
        $initialized_comparison_scrolls.add($scroll);
        update_hint();
    });
}

function storage_key(kind: ComparisonKind) {
    return `catalogue-comparison:${kind}`;
}

function selected_items(kind: ComparisonKind): ComparisonItem[] {
    try {
        const stored = JSON.parse(window.sessionStorage.getItem(storage_key(kind)) || "[]");
        if (!Array.isArray(stored)) {
            return [];
        }
        const items = stored.flatMap((item): ComparisonItem[] => {
            if (typeof item === "string" && item.length > 0) {
                return [{ gid: item, name: item }];
            }
            if (
                typeof item === "object" &&
                item !== null &&
                typeof item.gid === "string" &&
                item.gid.length > 0 &&
                typeof item.name === "string"
            ) {
                return [{ gid: item.gid, name: item.name }];
            }
            return [];
        });
        return items.filter((item, index) => {
            return (
                items.findIndex(({ gid }) => {
                    return gid === item.gid;
                }) === index
            );
        });
    } catch {
        return [];
    }
}

function save_selected_items(kind: ComparisonKind, items: ComparisonItem[]) {
    window.sessionStorage.setItem(storage_key(kind), JSON.stringify(items));
}

function comparison_kind(value: string | undefined): ComparisonKind | null {
    return value === "method" || value === "product" ? value : null;
}

function comparison_url(kind: ComparisonKind, items: ComparisonItem[]) {
    return `/compare/${kind}/${items
        .map(({ gid }) => {
            return encodeURIComponent(gid);
        })
        .join("/")}`;
}

function set_comparison_tray_expanded($tray: HTMLElement, expanded: boolean) {
    const $toggle = $tray.querySelector<HTMLButtonElement>(".comparison-tray__toggle");
    const $content = $tray.querySelector<HTMLElement>(".comparison-tray__content");
    $toggle?.setAttribute("aria-expanded", String(expanded));
    if ($content) {
        $content.hidden = !expanded;
    }
}

function refresh_comparison_selection($scope: ParentNode = document) {
    $scope.querySelectorAll<HTMLInputElement>(".comparison-selection").forEach(($input) => {
        const kind = comparison_kind($input.dataset.comparisonKind);
        const gid = $input.dataset.comparisonGid;
        if (kind && gid) {
            $input.checked = selected_items(kind).some((item) => {
                return item.gid === gid;
            });
        }
    });
    $scope.querySelectorAll<HTMLElement>(".comparison-tray").forEach(($launcher) => {
        const kind = comparison_kind($launcher.dataset.comparisonKind);
        if (!kind) {
            return;
        }
        const items = selected_items(kind);
        const total = selected_items("method").length + selected_items("product").length;
        const label = kind === "method" ? "methodes" : "producten";
        const enabled = items.length >= 2;
        const $link = $launcher.querySelector<HTMLAnchorElement>(".comparison-link");
        const $count = $launcher.querySelector<HTMLElement>(".comparison-count");
        const $items = $launcher.querySelector<HTMLUListElement>(".comparison-items");
        const $hint = $launcher.querySelector<HTMLElement>(".comparison-minimum-hint");
        if ($hint) {
            $hint.hidden = enabled;
            $hint.textContent = `Selecteer minimaal twee ${label} om te vergelijken.`;
        }
        if ($count) {
            $count.textContent = String(total);
        }
        $launcher.querySelectorAll<HTMLButtonElement>(".comparison-kind-toggle button").forEach(($button) => {
            const button_kind = comparison_kind($button.dataset.comparisonKind);
            const $button_count = $button.querySelector<HTMLElement>(".comparison-kind-count");
            $button.setAttribute("aria-pressed", String(button_kind === kind));
            if (button_kind && $button_count) {
                $button_count.textContent = String(selected_items(button_kind).length);
            }
        });
        $launcher.hidden = total === 0;
        if (!total) {
            set_comparison_tray_expanded($launcher, false);
        }
        if ($items) {
            $items.replaceChildren(
                ...items.map((item) => {
                    return comparison_item_element(kind, item);
                }),
            );
        }
        if ($link) {
            $link.textContent = `Vergelijk geselecteerde ${label}`;
            $link.href = enabled ? comparison_url(kind, items) : "";
            $link.classList.toggle("disabled", !enabled);
            $link.setAttribute("aria-disabled", String(!enabled));
            $link.tabIndex = enabled ? 0 : -1;
        }
    });
}

function comparison_item_element(kind: ComparisonKind, item: ComparisonItem) {
    const $item = document.createElement("li");
    $item.className = "comparison-item";
    const $name = document.createElement("span");
    $name.className = "text-truncate";
    $name.textContent = item.name;
    $name.title = item.name;
    $item.append($name);
    const $remove = document.createElement("button");
    $remove.type = "button";
    $remove.className = "btn-close comparison-remove";
    $remove.dataset.comparisonGid = item.gid;
    $remove.dataset.comparisonKind = kind;
    $remove.setAttribute("aria-label", `${item.name} uit vergelijking verwijderen`);
    $item.append($remove);
    return $item;
}

document.addEventListener("DOMContentLoaded", () => {
    refresh_comparison_selection();
    initialize_comparison_scroll_hints();
});
window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
        document.querySelectorAll<HTMLElement>(".comparison-tray").forEach(($tray) => {
            set_comparison_tray_expanded($tray, false);
        });
        refresh_comparison_selection();
    }
});
document.addEventListener("htmx:afterSwap", (event) => {
    const target = (
        event as CustomEvent<{
            target?: EventTarget;
        }>
    ).detail?.target;
    if (target instanceof HTMLElement) {
        refresh_comparison_selection(target);
        initialize_comparison_scroll_hints();
    }
});
document.addEventListener("change", (event) => {
    const $input = event.target;
    if ($input instanceof HTMLInputElement && $input.matches(".comparison-differences-toggle")) {
        $input.closest<HTMLElement>(".comparison-page")?.classList.toggle("only-differences", $input.checked);
        return;
    }
    if (!($input instanceof HTMLInputElement) || !$input.matches(".comparison-selection")) {
        return;
    }
    const kind = comparison_kind($input.dataset.comparisonKind);
    const gid = $input.dataset.comparisonGid;
    const name = $input.dataset.comparisonName;
    if (!kind || !gid || !name) {
        return;
    }
    const items = selected_items(kind);
    save_selected_items(
        kind,
        $input.checked
            ? [
                  ...items.filter((item) => {
                      return item.gid !== gid;
                  }),
                  { gid, name },
              ]
            : items.filter((item) => {
                  return item.gid !== gid;
              }),
    );
    if ($input.checked) {
        document.querySelectorAll<HTMLElement>(".comparison-tray").forEach(($tray) => {
            $tray.dataset.comparisonKind = kind;
        });
    }
    refresh_comparison_selection();
});
document.addEventListener("click", (event) => {
    const $target = event.target as Element | null;
    if (!$target) {
        return;
    }
    const $kind_toggle = $target.closest<HTMLButtonElement>(".comparison-kind-toggle button");
    if ($kind_toggle) {
        const kind = comparison_kind($kind_toggle.dataset.comparisonKind);
        const $tray = $kind_toggle.closest<HTMLElement>(".comparison-tray");
        if (kind && $tray) {
            $tray.dataset.comparisonKind = kind;
            refresh_comparison_selection();
        }
        return;
    }
    const $toggle = $target.closest<HTMLButtonElement>(".comparison-tray__toggle");
    if ($toggle) {
        const $tray = $toggle.closest<HTMLElement>(".comparison-tray");
        if ($tray) {
            const expanded = $toggle.getAttribute("aria-expanded") !== "true";
            document.querySelectorAll<HTMLElement>(".comparison-tray").forEach(($other_tray) => {
                set_comparison_tray_expanded($other_tray, $other_tray === $tray && expanded);
            });
        }
        return;
    }
    const $heading_remove = $target.closest<HTMLAnchorElement>(".comparison-heading-remove");
    if ($heading_remove) {
        const kind = comparison_kind($heading_remove.dataset.comparisonKind);
        const gid = $heading_remove.dataset.comparisonGid;
        if (kind && gid) {
            save_selected_items(
                kind,
                selected_items(kind).filter((item) => {
                    return item.gid !== gid;
                }),
            );
        }
    }
    const $remove = $target.closest<HTMLButtonElement>(".comparison-remove");
    if ($remove) {
        const kind = comparison_kind($remove.dataset.comparisonKind);
        const gid = $remove.dataset.comparisonGid;
        if (kind && gid) {
            save_selected_items(
                kind,
                selected_items(kind).filter((item) => {
                    return item.gid !== gid;
                }),
            );
            refresh_comparison_selection();
            return;
        }
    }
    const $link = $target.closest<HTMLAnchorElement>(".comparison-link");
    if ($link?.getAttribute("aria-disabled") === "true") {
        event.preventDefault();
    }
});
document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !(event.target instanceof Element)) {
        return;
    }
    const $tray = event.target.closest<HTMLElement>(".comparison-tray");
    const $toggle = $tray?.querySelector<HTMLButtonElement>(".comparison-tray__toggle");
    if ($tray && $toggle?.getAttribute("aria-expanded") === "true") {
        event.preventDefault();
        set_comparison_tray_expanded($tray, false);
        $toggle.focus();
    }
});
