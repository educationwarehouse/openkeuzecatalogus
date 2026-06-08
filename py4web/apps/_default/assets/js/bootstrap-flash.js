document.addEventListener("DOMContentLoaded", () => {
    const $flash_template = document.getElementById("py4web-flash")
    if (!$flash_template || !$flash_template.content) {
        return
    }

    const $flash_source = $flash_template.content.firstElementChild
    if (!$flash_source) {
        return
    }

    const $flash_host = document.createElement("div")
    $flash_host.className = "position-fixed top-0 end-0 p-3"
    $flash_host.style.zIndex = "1085"
    $flash_host.style.width = "min(24rem, calc(100vw - 1.5rem))"
    $flash_host.style.pointerEvents = "none"
    $flash_host.setAttribute("aria-live", "polite")
    $flash_host.setAttribute("aria-atomic", "true")

    const $flash = $flash_source.cloneNode(true)
    $flash.classList.add("alert-dismissible", "fade", "show", "shadow", "mb-0")
    $flash.style.pointerEvents = "auto"

    if (!$flash.querySelector(".btn-close")) {
        const $close_button = document.createElement("button")
        $close_button.type = "button"
        $close_button.className = "btn-close"
        $close_button.setAttribute("data-bs-dismiss", "alert")
        $close_button.setAttribute("aria-label", "Close")
        $flash.appendChild($close_button)
    }

    $flash.addEventListener("closed.bs.alert", () => {
        $flash_host.remove()
    })

    $flash_host.appendChild($flash)
    document.body.appendChild($flash_host)
})
