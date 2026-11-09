const visited_steps = new Map<string, Set<string>>();

function initialize_wizard_progress(): void {
    const $stepper = document.querySelector<HTMLElement>("[data-wizard-history]");
    if (!$stepper) {
        return;
    }
    const key = `okl-wizard-visited:${$stepper.dataset.wizardHistory}`;
    const $steps = Array.from($stepper.querySelectorAll<HTMLElement>(".steps .step"));
    const urls = $steps
        .map(($step) => {
            return $step.dataset.stepUrl;
        })
        .filter((url): url is string => {
            return Boolean(url);
        });
    const visited = visited_steps.get(key) || new Set<string>();
    try {
        const stored: unknown = JSON.parse(localStorage.getItem(key) || "[]");
        if (Array.isArray(stored)) {
            stored.forEach((url) => {
                if (typeof url === "string" && urls.includes(url)) {
                    visited.add(url);
                }
            });
        }
    } catch {
        // Navigation remains available in this document when browser storage is disabled.
    }
    $steps.forEach(($step) => {
        if ($step.dataset.stepUrl && $step.matches(".active, .completed")) {
            visited.add($step.dataset.stepUrl);
        }
    });
    visited_steps.set(key, visited);
    try {
        localStorage.setItem(key, JSON.stringify([...visited]));
    } catch {
        // Retain the in-memory state when storage is unavailable or full.
    }
    const $lines = $stepper.querySelectorAll(".step-lines span");
    const current_index = $steps.findIndex(($step) => {
        return $step.classList.contains("active");
    });
    $steps.forEach(($step, index) => {
        const url = $step.dataset.stepUrl;
        if (index <= current_index || !url || !visited.has(url)) {
            return;
        }
        $step.classList.add("visited");
        $lines[index]?.classList.add("visited");
        if ($step instanceof HTMLAnchorElement) {
            return;
        }
        const $link = document.createElement("a");
        $link.className = $step.className;
        $link.classList.remove("pending");
        $link.classList.add("completed");
        $link.href = url;
        $link.dataset.stepUrl = url;
        $link.setAttribute("hx-push-url", "true");
        $link.setAttribute("aria-label", `${$step.textContent?.trim().replace(/\s+/g, " ")} — eerder bezocht`);
        $link.append(...Array.from($step.childNodes));
        $step.replaceWith($link);
        window.htmx.process($link);
    });
}

window.on_okl_ready(initialize_wizard_progress);
document.addEventListener("htmx:afterSwap", () => {
    return window.on_okl_ready(initialize_wizard_progress);
});
document.addEventListener("htmx:historyRestore", initialize_wizard_progress);
