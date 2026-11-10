function show_flash() {
    const $flash_template = document.getElementById("py4web-flash");
    if (!$flash_template || !$flash_template.content) {
        return;
    }
    const $flash_source = $flash_template.content.firstElementChild;
    if (!$flash_source) {
        return;
    }
    $flash_template.remove();
    render_flash($flash_source);
}

function show_flash_message(message, style = "alert-info", delay = 0) {
    const $flash_source = document.createElement("div");
    $flash_source.className = `alert ${style}`;
    $flash_source.setAttribute("role", "alert");
    $flash_source.textContent = message;
    render_flash($flash_source, delay);
}

function render_flash($flash_source, delay = 0) {
    const $previous = document.querySelector("[data-okl-flash]");
    $previous?.remove();
    const $flash_host = document.createElement("div");
    $flash_host.dataset.oklFlash = "true";
    $flash_host.className = "position-fixed top-0 end-0 p-3";
    $flash_host.style.zIndex = "1085";
    $flash_host.style.width = "min(24rem, calc(100vw - 1.5rem))";
    $flash_host.style.pointerEvents = "none";
    $flash_host.setAttribute("aria-live", "polite");
    $flash_host.setAttribute("aria-atomic", "true");
    const $flash = $flash_source.cloneNode(true);
    $flash.classList.add("alert-dismissible", "fade", "show", "shadow", "mb-0");
    $flash.style.pointerEvents = "auto";
    if (!$flash.querySelector(".btn-close")) {
        const $close_button = document.createElement("button");
        $close_button.type = "button";
        $close_button.className = "btn-close";
        $close_button.setAttribute("data-bs-dismiss", "alert");
        $close_button.setAttribute("aria-label", "Close");
        $flash.appendChild($close_button);
    }
    $flash.addEventListener("closed.bs.alert", () => {
        $flash_host.remove();
    });
    $flash_host.appendChild($flash);
    document.body.appendChild($flash_host);
    if (delay > 0) {
        const timeout = window.setTimeout(() => {
            bootstrap.Alert.getOrCreateInstance($flash).close();
        }, delay);
        $flash.addEventListener("closed.bs.alert", () => {
            window.clearTimeout(timeout);
        }, {once: true});
    }
}
window.on_okl_ready(show_flash);
document.addEventListener("htmx:afterSettle", show_flash);
