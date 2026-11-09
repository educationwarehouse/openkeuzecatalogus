export {};

interface OverviewRequest {
    elt: HTMLElement;
    target: HTMLElement;
    xhr: XMLHttpRequest;
    successful?: boolean;
    shouldSwap?: boolean;
    serverResponse?: string;
}

interface OverviewState {
    $root: HTMLElement;
    scroll: number;
    horizontal_scroll: number;
    expanded: boolean;
    next_process?: string;
    name: string;
    refresh_archived: boolean;
}

let pending: OverviewState | undefined;
const runtime = window.htmx;

function expand_processes($root: HTMLElement, expanded: boolean): void {
    $root.querySelectorAll(".foldable-row").forEach(($row) => {
        $row.classList.toggle("d-none", !expanded);
    });
    const $button = $root.querySelector<HTMLButtonElement>("#show-more");
    if (!$button) {
        return;
    }
    $button.setAttribute("aria-expanded", String(expanded));
    $button.textContent = expanded ? "Verberg oudere processen" : "Toon oudere processen";
}

function show_error(): void {
    if (!pending) {
        return;
    }
    const { $root } = pending;
    pending = undefined;
    $root.removeAttribute("aria-busy");
    const $feedback = document.createElement("p");
    $feedback.className = "alert alert-danger";
    $feedback.setAttribute("role", "alert");
    $feedback.textContent = "Het overzicht kon niet worden bijgewerkt. Probeer het opnieuw.";
    $root.querySelector("[role=alert]")?.remove();
    $root.prepend($feedback);
}

document.addEventListener("click", (event) => {
    const $element = event.target instanceof Element ? event.target : null;
    const $button = $element?.closest<HTMLButtonElement>("#process-overview #show-more");
    const $root = $button?.closest<HTMLElement>("#process-overview");
    if ($root && $button) {
        expand_processes($root, $button.getAttribute("aria-expanded") !== "true");
    }
});
document.addEventListener("htmx:beforeRequest", (event) => {
    const detail = (event as CustomEvent<OverviewRequest>).detail;
    if (!detail.elt.matches("[data-process-archive]")) {
        return;
    }
    if (pending) {
        event.preventDefault();
        return;
    }
    const $root = detail.target;
    const $row = detail.elt.closest<HTMLElement>("[data-process-id]");
    const $rows = Array.from($root.querySelectorAll<HTMLElement>("[data-process-id]:not(.d-none)"));
    const index = $row ? $rows.indexOf($row) : -1;
    pending = {
        $root,
        scroll: scrollY,
        horizontal_scroll: $root.querySelector(".table-responsive")?.scrollLeft || 0,
        expanded: $root.querySelector("#show-more")?.getAttribute("aria-expanded") === "true",
        next_process: ($rows[index + 1] || $rows[index - 1])?.dataset.processId,
        name: $row?.querySelector(".team-name")?.textContent?.trim() || "Keuzeproces",
        refresh_archived: new URL(location.href).searchParams.get("archived") === "1",
    };
    $root.setAttribute("aria-busy", "true");
});
document.addEventListener("htmx:beforeSwap", (event) => {
    const detail = (event as CustomEvent<OverviewRequest>).detail;
    if (!pending || detail.target !== pending.$root || !detail.shouldSwap) {
        return;
    }
    if (pending.refresh_archived) {
        event.preventDefault();
        pending.refresh_archived = false;
        // The archive endpoint redirects to the active list; retain the user's archived filter.
        runtime
            .ajax("GET", location.href, {
                source: "#process-overview",
                target: "#process-overview",
                select: "#process-overview",
                swap: "outerHTML show:none",
            })
            .catch(show_error);
    } else if (
        !new DOMParser().parseFromString(detail.serverResponse || "", "text/html").querySelector("#process-overview")
    ) {
        event.preventDefault();
        show_error();
    }
});
document.addEventListener("htmx:afterSwap", (event) => {
    const detail = (event as CustomEvent<OverviewRequest>).detail;
    if (!pending || detail.target.id !== "process-overview") {
        return;
    }
    const state = pending;
    pending = undefined;
    const $root = document.getElementById("process-overview");
    if (!$root) {
        return;
    }
    expand_processes($root, state.expanded);
    const $row = Array.from($root.querySelectorAll<HTMLElement>("[data-process-id]")).find(($candidate) => {
        return $candidate.dataset.processId === state.next_process;
    });
    const $focus = $row?.querySelector<HTMLElement>("[data-process-archive], a[aria-label]") || $root;
    $focus.focus({ preventScroll: true });
    const $table = $root.querySelector(".table-responsive");
    if ($table) {
        $table.scrollLeft = state.horizontal_scroll;
    }
    window.scrollTo({ top: state.scroll, behavior: "instant" });
    const $status = document.getElementById("okl-page-status");
    if ($status) {
        $status.textContent = `Keuzeproces van ${state.name} verwijderd.`;
    }
});
document.addEventListener("htmx:afterRequest", (event) => {
    const detail = (event as CustomEvent<OverviewRequest>).detail;
    if (pending && detail.target === pending.$root && detail.successful === false) {
        show_error();
    }
});
for (const name of ["htmx:sendError", "htmx:timeout", "htmx:swapError"]) {
    document.addEventListener(name, (event) => {
        const detail = (event as CustomEvent<OverviewRequest>).detail;
        if (pending && detail.target === pending.$root) {
            show_error();
        }
    });
}
document.addEventListener("okl:navigated", () => {
    pending = undefined;
});
